---
description: Install the push-guard git pre-push backstop into the current repo
---

Install the push-guard backstop into the git repository at the current working
directory. This is the git-level enforcement layer that scans the commits a push
would send for secrets and not-ready work, covering pushes the Claude tool-layer
hook never sees: a push from a terminal, an editor, or a script.

Run this exact command and report the result to the user:

```bash
sh "${CLAUDE_PLUGIN_ROOT}/scripts/install-git-hook.sh"
```

If it reports that the repo already has a `pre-push` hook, confirm to the user that
the backstop was chained onto the existing hook rather than overwriting it. If it
reports "not inside a git repository", tell the user to `cd` into their repo first,
or offer to `git init`.

The installer copies the scanner next to the hook, so the hook keeps working after
the plugin is updated or removed. Re-run this command after a plugin update to
refresh that copy.
