---
description: Show or set how emdash-guard handles em dashes it finds (on / off / prompt)
argument-hint: "[on | off | prompt]"
---

Show or change emdash-guard's autofix mode. Run exactly this, passing `$ARGUMENTS`
through unchanged (empty arguments means "just report the current mode"):

```bash
python3 "${CLAUDE_PLUGIN_ROOT}"/scripts/autofix_mode.py $ARGUMENTS
```

Report the script's output to the user verbatim and stop. Do not edit any file, do
not go looking for em dashes, and do not set a mode the user did not ask for.

The modes, for when the user asks what to pick:

| Mode | What the hook does after a write with em dashes in it |
| :--- | :--- |
| `on` (default) | Tells the user the count, then hands the flagged lines back to Claude to rewrite with real punctuation |
| `off` | Tells the user the count and nothing else. Never blocks, never edits |
| `prompt` | Tells the user the count, then Claude asks whether to remove them and rewrites only on a yes |

The setting is per user, not per repo: it is stored in
`$CLAUDE_CONFIG_DIR/emdash-guard/config.json` (default
`~/.claude/emdash-guard/config.json`) and applies everywhere. If
`EMDASH_GUARD_AUTOFIX` is set in the environment it wins for that session, and the
script says so.
