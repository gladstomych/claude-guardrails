# claude-guardrails

A small Claude Code plugin marketplace. Several plugins, one job each.

| Plugin | Job | Mechanism |
| :----- | :-- | :-------- |
| [`emdash-guard`](plugins/emdash-guard) | Keep em dashes out of files Claude writes | `PostToolUse` hook counts them and then fixes, ignores, or asks, per `/emdash-guard:autofix` |
| [`commit-guard`](plugins/commit-guard) | Keep `Co-Authored-By: Claude` out of commits | `PreToolUse` hook blocks the commit; a git `commit-msg` backstop strips it for cases the tool layer can't see |
| [`push-guard`](plugins/push-guard) | Keep secrets and half-done work out of a push | `PreToolUse` hook scans the commits a `git push` would send; a git `pre-push` backstop covers pushes made outside Claude |
| [`commit-style`](plugins/commit-style) | Nudge commits toward Conventional Commits | A warning-only git `commit-msg` hook. A guide, not a guard |
| [`session-logger`](plugins/session-logger) | Keep a log of what each session did | `SessionStart` / `PostToolUse` / `Stop` hooks append a per-day markdown log |
| [`plugin-vet`](plugins/plugin-vet) | Security-review a plugin before you install it | `/plugin-vet:vet <repo>` clones it, scans it, reviews it, and returns BLOCK / WARN / CLEAN |

## Install

```shell
/plugin marketplace add gladstomych/claude-guardrails
/plugin install emdash-guard@claude-guardrails
/plugin install commit-guard@claude-guardrails
/plugin install push-guard@claude-guardrails
/plugin install commit-style@claude-guardrails
/plugin install session-logger@claude-guardrails
/plugin install plugin-vet@claude-guardrails
/reload-plugins
```

Install any one on its own; they are independent.

## Dogfooding

This repo runs its own guardrails. If you are working *on* these plugins, install
the marketplace from your checkout, then add the two per-repo git hooks, which no
plugin install can do for you:

```shell
/plugin marketplace add ~/dev/claude-guardrails
/plugin install emdash-guard@claude-guardrails
/plugin install commit-guard@claude-guardrails
/plugin install push-guard@claude-guardrails
/plugin install commit-style@claude-guardrails
/plugin install session-logger@claude-guardrails
/plugin install plugin-vet@claude-guardrails
/reload-plugins

/commit-guard:install-git-hook
/push-guard:install-git-hook
/commit-style:install-git-hook
```

Already installed from GitHub? Pick up local changes with
`/plugin marketplace update claude-guardrails`, then `/plugin update <name>` and
`/reload-plugins`. Plugin hooks run from an installed copy in
`~/.claude/plugins/cache`, not from your working tree, so edits are invisible
until you do that.

Before pushing work on this repo:

```shell
/push-guard:scan     # or: sh tests/smoke.sh
```

## Seeing the guards work

Every guard reports both ways: one styled line to you, the detail Claude needs to
act on to Claude. A block is never silent, and a passing check says so too, because
a silent guard is indistinguishable from an absent one.

Each notice is `<plugin>: <symbol> <message>`. The plugin name is bold cyan in
every plugin, so a glance tells you a guardrail spoke and which one. The body
colour and the symbol say what happened:

| Level | Colour | Symbol | Meaning |
| :---- | :----- | :----- | :------ |
| block | bold red | `x` | refused, the action did not happen |
| warn | yellow | `!` | stopped on a softer signal, or allowed with a caveat |
| ask | bold magenta | `?` | stopped, waiting on a decision from you |
| ok | green | `+` | checked, nothing wrong |
| info | dim grey | | neutral status, nothing to act on |

```
emdash-guard: + checked CLAUDE.md, no em dashes.
emdash-guard: x 3 em dashes / stand-in dashes in README.md, fixing.
commit-guard: x blocked a commit carrying a Claude co-author trailer.
push-guard: x blocked a push, 1 secret in the commits (cfg.py: AWS access key id).
push-guard: ! blocked a push, 2 suspicious changes to check first.
```

Symbols are ASCII so severity survives a log file, a pipe, and a reader who cannot
tell red from green. `NO_COLOR` (any value) or `GUARDRAILS_COLOR=0` drops the
colour and keeps them.

A guard only speaks about a call it acted on: the file it checked, the `git commit`
or `git push` it scanned. `commit-guard` and `push-guard` run on every Bash call and
stay quiet on the rest, so `ls` is never narrated. Silence the pass notices with
`GUARDRAILS_VERBOSE=0`, or one at a time with `EMDASH_GUARD_VERBOSE=0`,
`COMMIT_GUARD_VERBOSE=0`, `PUSH_GUARD_VERBOSE=0`. The per-plugin setting wins.
Nothing silences a block.

## emdash-guard

Set once, applies in every repo:

```shell
/emdash-guard:autofix          # show the current mode
/emdash-guard:autofix on       # default: Claude rewrites each dash with real punctuation
/emdash-guard:autofix off      # only ever show the count, never block, never edit
/emdash-guard:autofix prompt   # Claude asks you first, and rewrites only on a yes
```

`on` hands the flagged lines back to Claude to recast rather than doing a blind
search and replace, because the right replacement for a dash is a judgement call.

Mode lives in `~/.claude/emdash-guard/config.json` (or `$CLAUDE_CONFIG_DIR`);
`EMDASH_GUARD_AUTOFIX` overrides it for one session. Which files get checked is
`EMDASH_GUARD_EXTENSIONS` (default: markdown and plain text; `*` for everything).

## commit-guard

The `PreToolUse` hook is automatic. For the git-level backstop, which catches
`git commit -F file` and editor commits the tool layer never sees:

```shell
/commit-guard:install-git-hook
```

It honours `core.hooksPath`, chains onto an existing `commit-msg` hook rather than
overwriting it, and is idempotent.

**Fail-safe matching.** The hook blocks a Bash call containing both a `git commit`
and the trailer string, anywhere in it. It does not isolate the commit message from
the rest of the command, so a command that commits *and* greps for the trailer is
blocked too. Deliberate: over-blocking never lets a real trailer through, and the
`commit-msg` backstop is the precise layer. Split the command in two if it trips.

**Better still, turn the trailer off at the source** in `~/.claude/settings.json`,
so commit-guard only has to catch the leftovers:

```json
{ "attribution": { "commit": "", "pr": "" } }
```

## push-guard

The `PreToolUse` hook scans any `git push` Claude runs. For pushes you make from a
terminal or an editor, install the backstop per repo:

```shell
/push-guard:install-git-hook
```

Check without pushing:

```shell
/push-guard:scan                    # the unpushed commits
/push-guard:scan origin/main..HEAD  # an explicit range
```

- **HIGH**, blocks: private key blocks, AWS / GitHub / Slack / Stripe / Google /
  Anthropic / OpenAI / npm / PyPI token shapes, JWTs, conflict markers, and paths
  that hold credentials (`.env`, `.npmrc`, `id_rsa`, `*.pem`). `.env.example` is
  explicitly fine.
- **MEDIUM**, also blocks, overridable: a hardcoded-looking `api_key = "..."`, a
  key-shaped string of the wrong length, an embedded certificate, a file over 5 MB,
  a `WIP`/`fixup!`/`squash!` subject.

It reads **added** lines only, so deleting a secret does not block you, and it scans
**each commit against its parent** rather than the collapsed range, because a secret
added in one commit and removed in the next is still in the history a push uploads.

Escape hatches: `PUSH_GUARD_SKIP=1` for either layer, `git push --no-verify` for the
git one.

**What it cannot do.** Regex scanning finds credentials with a recognisable shape.
It will not find a password that looks like an ordinary string, a secret in a
binary, or a token format nobody wrote a rule for. A clean result means "nothing
obvious", not "nothing".

## commit-style

Warns when a commit subject is not Conventional Commits format, never blocks.
Chains alongside commit-guard's backstop; merge, revert, fixup, and squash messages
are left alone.

```shell
/commit-style:install-git-hook
```

## session-logger

One markdown file per day in `~/.claude/session-logs/YYYY-MM-DD.md`, or
`SESSION_LOG_DIR`. A header per session, a line per file write or bash command, a
stop line. Appends only and always exits 0, so it cannot block or slow a session.

## plugin-vet

No hook can intercept `/plugin install`: it is a built-in command, not a tool call,
so nothing fires on it. `plugin-vet` is the gate you run yourself, first:

```shell
/plugin-vet:vet coo-quack/sensitive-canary
```

It clones to a throwaway dir, runs a zero-dep scanner over the hooks and scripts for
exfiltration, reverse shells, credential reads, persistence, npm lifecycle scripts,
and obfuscation, then reviews the code and returns BLOCK / WARN / CLEAN. The
deterministic layer over-flags on purpose; the review step adjudicates. Install only
on CLEAN or an accepted WARN. Standalone:

```shell
python3 plugins/plugin-vet/scripts/scan_plugin.py <plugin-dir>
```

## Companion tools (not in this marketplace)

- **Keep secrets out of Claude:** [`sensitive-canary`](https://github.com/coo-quack/sensitive-canary)
  (MIT) blocks `.env` files and secret/PII values in reads, bash output, and
  prompts. Requires Node.js 22.6+.
- **Notify when a run finishes:** Claude Code's built-in **Channels** feature, with
  per-status and per-branch filtering. No plugin needed.

## Development

```shell
sh tests/smoke.sh
```

Hermetic: throwaway repos and bare remotes under a temp dir, `CLAUDE_CONFIG_DIR`
pointed at a temp path. It never reads your real settings or touches a real remote.

## Credits

`emdash-guard` vendors its checker from
[exmergo/skill-no-em-dashes](https://github.com/exmergo/skill-no-em-dashes) (MIT);
see [`plugins/emdash-guard/NOTICE`](plugins/emdash-guard/NOTICE). Install that skill
alongside `emdash-guard` if you also want Claude to avoid reaching for an em dash in
the first place: prevention plus enforcement.
