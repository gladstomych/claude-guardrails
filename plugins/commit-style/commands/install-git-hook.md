---
description: Install the commit-style Conventional Commits guide into the current repo
---

Install the commit-style guide into the git repository at the current working
directory. It is a warning-only `commit-msg` hook: when a commit subject is not
Conventional Commits format it prints a reminder, but it never blocks the commit.

Run this exact command and report the result to the user:

```bash
sh "${CLAUDE_PLUGIN_ROOT}/scripts/install-git-hook.sh"
```

If the repo already has a `commit-msg` hook (for example commit-guard's backstop),
confirm to the user that the guide was chained onto it rather than overwriting it.
If it reports "not inside a git repository", tell the user to `cd` into their repo
first, or offer to `git init`.
