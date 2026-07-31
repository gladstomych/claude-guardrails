---
description: Show or set whether emdash-guard flags spaced hyphens used as pauses (flag / allow)
argument-hint: "[flag | allow]"
---

Show or change how emdash-guard treats spaced hyphens. Run exactly this, passing
`$ARGUMENTS` through unchanged (empty arguments means "just report the current
setting"):

```bash
python3 "${CLAUDE_PLUGIN_ROOT}"/scripts/hyphen_mode.py $ARGUMENTS
```

Report the script's output to the user verbatim and stop. Do not edit any file,
do not go looking for dashes, and do not set a mode the user did not ask for.

The modes, for when the user asks what to pick:

| Mode | What the hook does with a spaced hyphen used as a pause |
| :--- | :--- |
| `flag` (default) | Counts it as a stand-in dash, like the upstream checker |
| `allow` | Leaves it alone as the user's own style; real em/en dashes and other unicode stand-ins still count |

The setting is per user, not per repo: it is stored in
`$CLAUDE_CONFIG_DIR/emdash-guard/config.json` (default
`~/.claude/emdash-guard/config.json`) next to the autofix mode and applies
everywhere. If `EMDASH_GUARD_HYPHENS` is set in the environment it wins for that
session, and the script says so.
