# claude-guardrails

A small Claude Code plugin marketplace. Several plugins, one job each.

| Plugin | Job | Mechanism |
| :----- | :-- | :-------- |
| [`emdash-guard`](plugins/emdash-guard) | Keep em dashes out of files Claude writes | `PostToolUse` hook on `Write`/`Edit`/`NotebookEdit` runs a deterministic checker; on a hit it asks Claude to rewrite with real punctuation |
| [`commit-guard`](plugins/commit-guard) | Keep `Co-Authored-By: Claude` out of commits | `PreToolUse` hook blocks a `git commit` carrying the trailer; a git `commit-msg` backstop strips it for cases the tool layer can't see |
| [`commit-style`](plugins/commit-style) | Nudge commits toward Conventional Commits | A warning-only git `commit-msg` hook. A guide, not a guard: it never blocks, it only reminds |
| [`session-logger`](plugins/session-logger) | Keep a log of what each session did | `SessionStart` / `PostToolUse` / `Stop` hooks append a per-day markdown log of file writes and bash commands |
| [`plugin-vet`](plugins/plugin-vet) | Security-review a plugin before you install it | `/vet-plugin <repo>` clones it, runs a deterministic malware scan of its hooks and scripts, then an AI review, and gives a BLOCK / WARN / CLEAN verdict |

## Install

```shell
/plugin marketplace add gladstomych/claude-guardrails
/plugin install emdash-guard@claude-guardrails
/plugin install commit-guard@claude-guardrails
/plugin install commit-style@claude-guardrails
/plugin install session-logger@claude-guardrails
/plugin install plugin-vet@claude-guardrails
```

Install any one on its own; they are independent.

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
/vet-plugin coo-quack/sensitive-canary
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

## Credits

`emdash-guard` vendors its checker from
[exmergo/skill-no-em-dashes](https://github.com/exmergo/skill-no-em-dashes) (MIT).
See [`plugins/emdash-guard/NOTICE`](plugins/emdash-guard/NOTICE). If you also want
Claude to *avoid reaching for* an em dash in the first place (not just get corrected
after), install that skill alongside `emdash-guard`: prevention plus enforcement.
