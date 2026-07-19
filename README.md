# claude-guardrails

A small Claude Code plugin marketplace. Several plugins, one job each.

| Plugin | Job | Mechanism |
| :----- | :-- | :-------- |
| [`emdash-guard`](plugins/emdash-guard) | Keep em dashes out of files Claude writes | `PostToolUse` hook on `Write`/`Edit`/`NotebookEdit` runs a deterministic checker, tells you how many dashes the file has, and then fixes, ignores, or asks, per `/emdash-guard:autofix` |
| [`commit-guard`](plugins/commit-guard) | Keep `Co-Authored-By: Claude` out of commits | `PreToolUse` hook blocks a `git commit` carrying the trailer; a git `commit-msg` backstop strips it for cases the tool layer can't see |
| [`commit-style`](plugins/commit-style) | Nudge commits toward Conventional Commits | A warning-only git `commit-msg` hook. A guide, not a guard: it never blocks, it only reminds |
| [`session-logger`](plugins/session-logger) | Keep a log of what each session did | `SessionStart` / `PostToolUse` / `Stop` hooks append a per-day markdown log of file writes and bash commands |
| [`push-guard`](plugins/push-guard) | Keep secrets and half-done work out of a push | `PreToolUse` hook scans the commits a `git push` would send for credentials, `.env` files, conflict markers, and WIP commits; a git `pre-push` backstop covers pushes made outside Claude |
| [`plugin-vet`](plugins/plugin-vet) | Security-review a plugin before you install it | `/plugin-vet:vet <repo>` clones it, runs a deterministic malware scan of its hooks and scripts, then an AI review, and gives a BLOCK / WARN / CLEAN verdict |

## Install

```shell
/plugin marketplace add gladstomych/claude-guardrails
/plugin install emdash-guard@claude-guardrails
/plugin install commit-guard@claude-guardrails
/plugin install commit-style@claude-guardrails
/plugin install session-logger@claude-guardrails
/plugin install push-guard@claude-guardrails
/plugin install plugin-vet@claude-guardrails
```

Install any one on its own; they are independent.

### emdash-guard: the counter and the autofix switch

After every write to a prose file, the hook reports what it found:

```
emdash-guard: 3 em dashes / stand-in dashes in README.md (fixing)
```

What happens next is the autofix mode, which you set once and it applies in every
repo:

```shell
/emdash-guard:autofix          # show the current mode
/emdash-guard:autofix on       # default: Claude rewrites each dash with real punctuation
/emdash-guard:autofix off      # only ever show the count, never block, never edit
/emdash-guard:autofix prompt   # Claude asks you first, and rewrites only on a yes
```

`on` does not mangle prose with a blind search and replace: the hook hands the
flagged lines back to Claude, which recasts each one. `off` leaves the file exactly
as written and just keeps you informed. `prompt` is the middle ground for drafts you
may want to keep verbatim.

The mode lives in `~/.claude/emdash-guard/config.json` (or `$CLAUDE_CONFIG_DIR`).
Set `EMDASH_GUARD_AUTOFIX=on|off|prompt` to override it for one session, for example
in CI. The mode script also runs standalone:

```shell
python3 plugins/emdash-guard/scripts/autofix_mode.py off
```

Which files get checked is separate, and still controlled by
`EMDASH_GUARD_EXTENSIONS` (default: markdown and plain-text extensions; `*` checks
everything).

### Seeing the guards work

Every guard reports both ways: one styled line to you, the detail Claude needs to
act to Claude. A block is never silent, and a passing check says so too, because a
silent guard is indistinguishable from an absent one.

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
commit-guard: + checked the message, no Claude trailer.
push-guard: + unpushed commits scanned, clean.
emdash-guard: x 3 em dashes / stand-in dashes in README.md, fixing.
emdash-guard: ? 1 em dash / stand-in dash in draft.md, asking before fixing.
emdash-guard: ! 1 em dash / stand-in dash in draft.md, not fixing.
commit-guard: x blocked a commit carrying a Claude co-author trailer.
push-guard: x blocked a push, 1 secret in the commits (cfg.py: AWS access key id).
push-guard: ! blocked a push, 2 suspicious changes to check first.
```

The symbols are ASCII deliberately: they survive a log file, a pipe, and a reader
who cannot tell red from green. Set `NO_COLOR` (any value) or `GUARDRAILS_COLOR=0`
and the colour drops while the symbols keep carrying severity.

A guard only ever speaks about a call it actually acted on: the file it checked,
the `git commit` or `git push` it scanned. `commit-guard` and `push-guard` run on
every Bash call and stay quiet on all the rest, so `ls` is never narrated, and
`emdash-guard` says nothing about files outside its extension filter.

Turn the pass notices off (blocks are never silenced):

```shell
GUARDRAILS_VERBOSE=0        # every guard
COMMIT_GUARD_VERBOSE=0      # or one at a time
PUSH_GUARD_VERBOSE=0
EMDASH_GUARD_VERBOSE=0
```

The per-plugin setting wins over the global one, so `GUARDRAILS_VERBOSE=0
PUSH_GUARD_VERBOSE=1` keeps only push-guard talking.

### commit-guard: two layers

The `PreToolUse` hook is automatic once the plugin is enabled. For the git-level
backstop (recommended, it catches `git commit -F file` and editor commits that the
tool layer never sees), install the `commit-msg` hook per repo:

```shell
/commit-guard:install-git-hook
```

It honours `core.hooksPath`, never overwrites an existing `commit-msg` hook (it
chains onto it), and is idempotent.

#### Fail-safe matching (by design)

The `PreToolUse` hook blocks a Bash call when the command contains **both** a
`git commit` **and** the string `Co-Authored-By: Claude` (or `Claude-Session:`)
anywhere in it. It does not try to isolate the commit message from the rest of
the command line. So a command that commits and *also* mentions the trailer
string elsewhere (for example, a `grep` that checks for it in the same line) is
blocked even though the commit itself is clean.

This is deliberate: over-blocking never lets a real trailer slip through, and the
git `commit-msg` backstop is the precise layer. If a benign command trips it,
split the commit and the search into two separate commands.

### Also recommended: disable the trailer at the source

commit-guard is enforcement. Turn the behaviour off in the first place with the
native setting in `~/.claude/settings.json`:

```json
{ "attribution": { "commit": "", "pr": "" } }
```

commit-guard then only has to catch the occasional case where Claude adds the
trailer anyway via the Bash tool.

### push-guard: what leaves the machine

The tool-layer hook is automatic once the plugin is enabled: any `git push` Claude
runs is scanned first, and a finding blocks it. For pushes you make yourself, from
a terminal or an editor, install the `pre-push` backstop per repo:

```shell
/push-guard:install-git-hook
```

Check without pushing anything:

```shell
/push-guard:scan                    # the unpushed commits
/push-guard:scan origin/main..HEAD  # an explicit range
```

What it looks for, in the commits a push would send:

- **HIGH**, blocks: private key blocks, AWS / GitHub / Slack / Stripe / Google /
  Anthropic / OpenAI / npm / PyPI token shapes, JWTs, unresolved conflict markers,
  and paths that normally hold credentials (`.env`, `.npmrc`, `id_rsa`, `*.pem`).
  `.env.example` and friends are explicitly fine.
- **MEDIUM**, also blocks, with an override: a hardcoded-looking
  `password = "..."`, an embedded certificate, a file over 5 MB, a commit subject
  starting `WIP`/`fixup!`/`squash!`.

It reads **added** lines only, so deleting a secret does not block you. It scans
**each commit against its parent**, not the collapsed range, because a secret added
in one commit and removed in the next is still in the history the push uploads.

Escape hatches, both deliberate and visible: `PUSH_GUARD_SKIP=1` for either layer,
`git push --no-verify` for the git one.

#### What it cannot do

Regex scanning finds credentials with a recognisable shape. It will not find a
password that looks like an ordinary string, a secret inside a binary, or a token
format nobody has written a rule for. A clean result means "nothing obvious",
not "nothing". Treat it as one layer, not as permission to stop reading diffs.

### commit-style: a guide, not a guard

`commit-style` warns when a commit subject is not Conventional Commits format
(`type(scope): summary`), but it never blocks. Install it per repo:

```shell
/commit-style:install-git-hook
```

It chains cleanly alongside commit-guard's backstop (both run). Merge, revert,
fixup, and squash messages are left alone.

### session-logger: where the logs go

Once enabled, `session-logger` writes one markdown file per day. Default location
is `~/.claude/session-logs/YYYY-MM-DD.md`; set `SESSION_LOG_DIR` to change it. Each
session gets a header, then one line per file write or bash command, then a stop
line. It only ever appends and always exits 0, so it cannot block or slow a session.

### plugin-vet: review before you install

There is no hook that can intercept `/plugin install`: it is a built-in command,
not a tool call, and it does not expand into a prompt, so nothing fires on it.
`plugin-vet` is the gate you run yourself, first:

```shell
/plugin-vet:vet coo-quack/sensitive-canary
```

It clones the plugin to a throwaway dir, runs a zero-dep scanner
(`scripts/scan_plugin.py`) over its hooks and scripts for exfiltration, reverse
shells, credential reads, persistence, npm lifecycle scripts, and obfuscation,
then reviews the code and returns BLOCK / WARN / CLEAN. Install only on CLEAN or an
accepted WARN. The deterministic layer deliberately over-flags (it skips test
files, which do not run on install, but still flags docs and network calls); the
review step adjudicates. The scanner runs standalone too:

```shell
python3 plugins/plugin-vet/scripts/scan_plugin.py <plugin-dir>
```

## Companion tools (not in this marketplace)

Two needs are better served by things that already exist, so this repo just points
at them:

- **Keep secrets out of Claude:** [`sensitive-canary`](https://github.com/coo-quack/sensitive-canary)
  (MIT) blocks `.env` files and secret/PII values in reads, bash output, and prompts.
  Requires Node.js 22.6+.
- **Notify when a run finishes:** Claude Code's built-in **Channels** feature sends
  notifications to Slack, Discord, Telegram, Microsoft Teams, ntfy, PagerDuty, and
  custom webhooks, with per-status and per-branch filtering. No plugin needed.

## Development

Run the smoke tests:

```shell
sh tests/smoke.sh
```

The suite is hermetic: it builds throwaway repos and bare remotes under a temp
dir and points `CLAUDE_CONFIG_DIR` at a temp path, so it never reads your real
settings or touches a real remote.

## Credits

`emdash-guard` vendors its checker from
[exmergo/skill-no-em-dashes](https://github.com/exmergo/skill-no-em-dashes) (MIT).
See [`plugins/emdash-guard/NOTICE`](plugins/emdash-guard/NOTICE). If you also want
Claude to *avoid reaching for* an em dash in the first place (not just get corrected
after), install that skill alongside `emdash-guard`: prevention plus enforcement.
