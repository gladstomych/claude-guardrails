# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A Claude Code plugin marketplace. No build, no package manager, no dependencies:
every plugin is stdlib-only Python 3 or POSIX `sh`, run directly by the Claude Code
hook runner or by git. There is nothing to compile or install to develop here.

## Commands

```shell
sh tests/smoke.sh                                     # the whole test suite
python3 plugins/plugin-vet/scripts/scan_plugin.py DIR # run the vet scanner standalone
```

`tests/smoke.sh` is a single POSIX shell script with no test framework and no
per-test selection. To run one case, copy its lines into a shell or comment out
the surrounding sections. It counts `pass`/`fail`, prints a summary, and exits 1
if anything failed. Add cases with the existing helpers: `run_hook`, `assert_exit`,
`assert_contains`, `assert_absent`.

Tests drive hooks exactly as Claude Code does (JSON payload on stdin, assertions
on exit code and stderr), and build throwaway git repos under `mktemp -d` to
exercise the git-level hooks end to end.

## Architecture

Two enforcement layers, deliberately distinct:

- **Tool layer** (`hooks/hooks.json` + a Python script). Fires on Claude's tool
  calls. Sees only what is in the tool payload. Two ways to report a verdict:
  exit **2** with stderr (used by `commit-guard`, a pure block), or exit **0**
  with JSON on stdout (used by `emdash-guard`, because it also needs to say
  something to the user). In the JSON form, `decision: "block"` plus `reason`
  goes to Claude and `systemMessage` goes to the user; omit the decision to
  report without interrupting. Both paths are verified against the live harness.
- **Git layer** (`scripts/commit-msg*` + `scripts/install-git-hook.sh`, installed
  per repo by a slash command). Catches what the tool layer structurally cannot see:
  `git commit -F file`, editor commits, commits made outside Claude.

`commit-guard` is the only plugin with both. `emdash-guard` and `session-logger`
are tool-layer only; `commit-style` is git-layer only (no `hooks.json`);
`plugin-vet` is a slash command plus a standalone scanner (no hooks at all).

Registration is by hand in two places for every plugin: `.claude-plugin/marketplace.json`
at repo root (name, `./plugins/<name>` source, description) and
`plugins/<name>/.claude-plugin/plugin.json` (name, description, version, author).
Hook commands always reference scripts as `python3 "${CLAUDE_PLUGIN_ROOT}"/scripts/x.py`.

### Invariants

- **Hooks never crash the session.** Malformed stdin, missing files, unreadable
  paths: swallow and exit 0. Smoke tests assert this for every hook.
- **Guards over-block, guides never block.** `commit-guard`'s tool hook matches
  `git commit` and the trailer string anywhere in the command, on purpose. A
  false positive is acceptable, a missed trailer is not, and the `commit-msg`
  backstop is the precise layer. `commit-style` only warns on stderr and always
  exits 0. Keep that split; do not make a guide block or a guard lenient.
- **User-facing settings are per user, not per repo.** `emdash-guard`'s autofix
  mode resolves env var, then `$CLAUDE_CONFIG_DIR/emdash-guard/config.json`
  (default `~/.claude`), then the built-in default; a corrupt or absent file
  falls back rather than raising. `tests/smoke.sh` points `CLAUDE_CONFIG_DIR` at
  a temp dir, so add config-reading scripts to that isolation or tests will read
  the developer's real settings.
- **Git hook installers chain, never clobber.** `install-git-hook.sh` honours
  `core.hooksPath`, moves an existing `commit-msg` aside to
  `commit-msg.pre-commit-guard` and calls it, and is idempotent on re-run.
  commit-guard's and commit-style's installers must coexist in one repo.
- **`plugin-vet`'s scanner over-flags by design.** Deterministic regex pass
  (HIGH → exit 2, MED → exit 1, clean → 0); the AI review step in
  `commands/vet.md` adjudicates. It skips test files (they don't run on install)
  but not docs. Don't tune rules for precision at the cost of recall.
- **Source files stay ASCII.** `tests/smoke.sh` builds em/en dashes from
  `printf '\342\200\224'` byte escapes rather than embedding them, so the test
  file does not trip `emdash-guard` itself.

### Writing commits here

This repo's own `commit-guard` refuses a `Co-Authored-By: Claude` or
`Claude-Session:` trailer. Commit messages must omit both.

## Docs

`README.md` is the user-facing surface and documents each plugin's behaviour,
install steps, env vars (`EMDASH_GUARD_EXTENSIONS`, `SESSION_LOG_DIR`), and the
rationale for the fail-safe matching. Behaviour changes belong there too.

`plugins/emdash-guard/scripts/check_em_dashes.py` is vendored from
[exmergo/skill-no-em-dashes](https://github.com/exmergo/skill-no-em-dashes) (MIT);
see `plugins/emdash-guard/NOTICE`. Prefer re-vendoring upstream over patching it.
