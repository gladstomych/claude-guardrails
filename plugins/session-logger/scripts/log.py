#!/usr/bin/env python3
"""session-logger: append a markdown log line for a Claude Code session event.

hooks.json calls this with one argument naming the event:
  start  (SessionStart)  -> write a session header
  tool   (PostToolUse)   -> append the tool call (file write or bash command)
  stop   (Stop)          -> append a session-stop line

It reads the event JSON on stdin, appends to a per-day markdown file, and always
exits 0: logging must never block or slow the session.

Log directory: $SESSION_LOG_DIR if set, else ~/.claude/session-logs.
"""

import datetime
import json
import os
import sys


def log_dir():
    d = os.environ.get("SESSION_LOG_DIR") or os.path.join(
        os.path.expanduser("~"), ".claude", "session-logs"
    )
    os.makedirs(d, exist_ok=True)
    return d


def log_path():
    return os.path.join(log_dir(), datetime.date.today().isoformat() + ".md")


def now():
    return datetime.datetime.now().strftime("%H:%M:%S")


def append(line):
    try:
        with open(log_path(), "a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    except OSError:
        pass  # never break the session over a log write


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else ""
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        payload = {}

    sid = str(payload.get("session_id", ""))[:8] or "????????"
    cwd = payload.get("cwd") or os.getcwd()

    if mode == "start":
        append(f"\n## {now()} - session {sid} start")
        append(f"`{cwd}`")
    elif mode == "stop":
        append(f"- {now()} session {sid} stop")
    elif mode == "tool":
        tool = payload.get("tool_name", "?")
        ti = payload.get("tool_input", {}) or {}
        if tool == "Bash":
            first = (ti.get("command", "") or "").splitlines()
            cmd = (first[0] if first else "")[:120]
            append(f"- {now()} `$ {cmd}`")
        else:
            path = ti.get("file_path") or ti.get("notebook_path") or ""
            append(f"- {now()} {tool} {path}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
