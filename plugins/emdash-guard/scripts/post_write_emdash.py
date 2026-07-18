#!/usr/bin/env python3
"""PostToolUse hook: check the file Claude just wrote for em dashes and stand-ins.

Claude Code runs this after every Write / Edit / NotebookEdit (see hooks.json).
It receives the tool-call JSON on stdin, pulls out the written file path, runs the
vendored deterministic checker on it, and if the file contains em dashes it exits 2
so the checker output is fed back to Claude as an error to fix. Clean files exit 0.

Scope: only files whose extension is in TEXT_EXTENSIONS are checked, so prose gets
guarded without turning every source-code edit into noise. Override the set with
the EMDASH_GUARD_EXTENSIONS env var (comma-separated, e.g. ".md,.txt,.py"); set it
to "*" to check every written file regardless of extension.
"""

import json
import os
import subprocess
import sys

DEFAULT_EXTENSIONS = {
    ".md", ".markdown", ".mdx", ".txt", ".text", ".rst",
    ".adoc", ".asciidoc", ".org", ".tex",
}


def wanted_extensions():
    raw = os.environ.get("EMDASH_GUARD_EXTENSIONS", "").strip()
    if not raw:
        return DEFAULT_EXTENSIONS
    if raw == "*":
        return None  # check everything
    return {e if e.startswith(".") else "." + e for e in raw.split(",") if e.strip()}


def target_path(payload):
    ti = payload.get("tool_input", {}) or {}
    return ti.get("file_path") or ti.get("notebook_path")


def main():
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return 0  # nothing we can act on; never block on a parse hiccup

    path = target_path(payload)
    if not path or not os.path.isfile(path):
        return 0

    exts = wanted_extensions()
    if exts is not None and os.path.splitext(path)[1].lower() not in exts:
        return 0

    checker = os.path.join(os.path.dirname(os.path.abspath(__file__)), "check_em_dashes.py")
    try:
        result = subprocess.run(
            [sys.executable, checker, path],
            capture_output=True, text=True, timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        return 0  # checker unavailable: fail open, do not block the workflow

    if result.returncode == 1:  # 1 == em dashes found; other nonzero == checker error
        sys.stderr.write(f"emdash-guard: em dash / stand-in dash found in {path}\n\n")
        sys.stderr.write(result.stdout)
        sys.stderr.write(
            "\nRewrite each flagged spot with real punctuation "
            "(comma, colon, semicolon, period, or parentheses), then save again.\n"
        )
        return 2  # feed this back to Claude as a fixable error

    return 0


if __name__ == "__main__":
    sys.exit(main())
