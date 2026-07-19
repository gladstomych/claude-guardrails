#!/usr/bin/env python3
"""PreToolUse hook: refuse a git push that would carry secrets or half-done work.

Claude Code runs this before every Bash tool call (see hooks.json). If the command
is a `git push`, it scans the commits that push would send (see scan_push.py) and
exits 2 to block on any finding, handing the findings back to Claude.

This is the tool-layer guard, so it only covers pushes Claude makes. The git
pre-push hook (scripts/pre-push, installed per repo) covers pushes made from a
terminal, an editor, or anything else.

Both severities block. A HIGH is a shaped credential or a conflict marker; a MED
is suspicious enough to be worth a human look. Over-blocking is the intended
failure direction, and the escape hatch is deliberate and visible:
PUSH_GUARD_SKIP=1 in the environment.
"""

import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from scan_push import HIGH, scan, verdict  # noqa: E402

# A git push in some form: `git push`, `git -C dir push`, `git push --force`.
# Deliberately loose, matching commit-guard's fail-safe stance: a false positive
# costs one PUSH_GUARD_SKIP, a false negative costs a leaked credential.
GIT_PUSH = re.compile(r"\bgit\b[^\n|;&]*\bpush\b", re.IGNORECASE)

# A dry run sends nothing, so there is nothing to guard.
DRY_RUN = re.compile(r"--dry-run\b")


def main():
    if os.environ.get("PUSH_GUARD_SKIP", "").strip() not in ("", "0", "false"):
        return 0

    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return 0  # nothing we can act on; never block on a parse hiccup

    if payload.get("tool_name") != "Bash":
        return 0

    command = (payload.get("tool_input", {}) or {}).get("command", "") or ""
    if not GIT_PUSH.search(command) or DRY_RUN.search(command):
        return 0

    cwd = payload.get("cwd") or os.getcwd()

    try:
        findings, base, _ = scan(cwd)
    except Exception:  # noqa: BLE001 - a scanner bug must not wedge the session
        return 0

    if base is None or not findings:
        return 0

    high = [f for f in findings if f[0] == HIGH]
    kind = "secret or blocker" if high else "suspicious change"
    sys.stderr.write(
        f"push-guard: refusing this push, {len(findings)} {kind}"
        f"{'' if len(findings) == 1 else 's'} in the commits it would send.\n\n"
    )
    for sev, path, line_no, why, excerpt in findings:
        where = f"{path}:{line_no}" if line_no else path
        sys.stderr.write(f"{sev:4} {where}: {why}\n")
        if excerpt:
            sys.stderr.write(f"       {excerpt}\n")

    if high:
        sys.stderr.write(
            "\nDo not push this. Remove the credential from the commits (rewriting "
            "history, not just adding a follow-up commit, since the old commit still "
            "carries it), and rotate anything that was real. Tell the user what was "
            "found and let them decide.\n"
        )
    else:
        sys.stderr.write(
            "\nShow the user these findings and ask whether to push anyway. If they "
            "confirm it is fine, re-run the push with PUSH_GUARD_SKIP=1 set.\n"
        )
    return 2  # block, and feed this back to Claude


if __name__ == "__main__":
    sys.exit(main())
