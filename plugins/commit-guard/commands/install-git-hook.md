---
description: Install the commit-guard git commit-msg backstop into the current repo
---

Install the commit-guard backstop into the git repository at the current working
directory. This is the git-level enforcement layer that strips `Co-Authored-By:
Claude` and `Claude-Session:` trailers from commit messages, covering the cases
the Claude tool-layer hook cannot see (messages passed via `git commit -F` or the
editor).

Run this exact command and report the result to the user:

```bash
sh "${CLAUDE_PLUGIN_ROOT}/scripts/install-git-hook.sh"
```

If it reports that the repo already has a `commit-msg` hook, confirm to the user
that the backstop was chained onto the existing hook rather than overwriting it.
If it reports "not inside a git repository", tell the user to `cd` into their repo
first, or offer to `git init`.
