#!/usr/bin/env python3
"""PreToolUse hook: block a git commit that carries AI co-author attribution.

Claude Code runs this before every Bash tool call (see hooks.json). It reads the
tool-call JSON on stdin, and if the command is a `git commit` whose message text
contains a `Co-Authored-By: Claude ...` trailer (or a `Claude-Session:` line),
it exits 2 to block the call and tells Claude to drop the attribution and retry.

This is the tool-layer guard. It only sees trailers passed inline on the command
line (e.g. `git commit -m "...\n\nCo-Authored-By: Claude ..."`). A message supplied
through a file (`git commit -F msg.txt`) or an editor is invisible here; the git
commit-msg backstop (scripts/commit-msg, installed per repo) covers that path.
"""

import json
import re
import sys

# A git commit in some form: `git commit`, `git   commit`, `git commit -a`, etc.
GIT_COMMIT = re.compile(r"\bgit\b[^\n|;&]*\bcommit\b", re.IGNORECASE)

# The attribution we refuse: a Co-Authored-By trailer naming Claude, or the
# Claude-Session trailer. Kept narrow so a human co-author is never blocked.
ATTRIBUTION = re.compile(
    r"co-authored-by:\s*claude\b|^\s*claude-session:",
    re.IGNORECASE | re.MULTILINE,
)


def main():
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return 0

    if payload.get("tool_name") != "Bash":
        return 0

    command = (payload.get("tool_input", {}) or {}).get("command", "")
    if not command:
        return 0

    if GIT_COMMIT.search(command) and ATTRIBUTION.search(command):
        sys.stderr.write(
            "commit-guard: refusing this git commit.\n"
            "It carries a 'Co-Authored-By: Claude' (or 'Claude-Session:') trailer, "
            "and this policy forbids AI co-author attribution in commits.\n"
            "Remove those trailer line(s) from the commit message and run the commit again.\n"
        )
        return 2  # exit 2 blocks the tool call and feeds stderr back to Claude

    return 0


if __name__ == "__main__":
    sys.exit(main())
