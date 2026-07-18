# claude-guardrails

A small Claude Code plugin marketplace. Two plugins, one job each.

| Plugin | Job | Mechanism |
| :----- | :-- | :-------- |
| [`emdash-guard`](plugins/emdash-guard) | Keep em dashes out of files Claude writes | `PostToolUse` hook on `Write`/`Edit`/`NotebookEdit` runs a deterministic checker; on a hit it asks Claude to rewrite with real punctuation |
| [`commit-guard`](plugins/commit-guard) | Keep `Co-Authored-By: Claude` out of commits | `PreToolUse` hook blocks a `git commit` carrying the trailer; a git `commit-msg` backstop strips it for cases the tool layer can't see |

## Install

```shell
/plugin marketplace add gladstomych/claude-guardrails
/plugin install emdash-guard@claude-guardrails
/plugin install commit-guard@claude-guardrails
```

Install either one on its own; they are independent.

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
