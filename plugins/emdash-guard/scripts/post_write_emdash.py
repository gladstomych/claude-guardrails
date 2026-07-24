#!/usr/bin/env python3
"""PostToolUse hook: check the file Claude just wrote for em dashes and stand-ins.

Claude Code runs this after every Write / Edit / NotebookEdit (see hooks.json).
It receives the tool-call JSON on stdin, pulls out the written file path, runs the
vendored deterministic checker on it, and reports what it found as hook JSON on
stdout: a `systemMessage` counting the dashes for the user, and, unless autofix is
off, a `decision: block` whose `reason` tells Claude what to do about them.

The client renders a block's `reason` in the user's transcript, not just to Claude,
so the reason carries the count and the checker command that reproduces the
locations rather than the per-hit listing itself: forty flagged dashes must not
paint forty lines into the UI. Claude re-runs the checker (or greps the file it
just wrote) to find the spots.

Autofix mode (see scripts/autofix_mode.py and /emdash-guard:autofix):
  on      block, and have Claude rewrite each dash with real punctuation (default)
  off     never block; only show the user the count
  prompt  block, but have Claude ask the user before rewriting anything

A clean file is reported as clean, so the guard is visible when it is working;
silence that with EMDASH_GUARD_VERBOSE=0 or GUARDRAILS_VERBOSE=0. Only files the
hook actually checked are ever mentioned.

Scope: only files whose extension is in TEXT_EXTENSIONS are checked, so prose gets
guarded without turning every source-code edit into noise. Override the set with
the EMDASH_GUARD_EXTENSIONS env var (comma-separated, e.g. ".md,.txt,.py"); set it
to "*" to check every written file regardless of extension.

Always exits 0: the verdict travels in the JSON, and a checker that cannot run
must never stall a session.
"""

import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from autofix_mode import current_mode  # noqa: E402
from hookout import style, verbose  # noqa: E402

DEFAULT_EXTENSIONS = {
    ".md", ".markdown", ".mdx", ".txt", ".text", ".rst",
    ".adoc", ".asciidoc", ".org", ".tex",
}

REWRITE = ("Rewrite each flagged spot with real punctuation "
           "(comma, colon, semicolon, period, or parentheses).")


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


def count_hits(checker_stdout):
    """How many dashes the checker flagged: one line per hit, "path:l:c: found '-'"."""
    return sum(1 for line in checker_stdout.splitlines() if ": found '" in line)


def emit(message, reason=None, level="ok"):
    """Write the hook's PostToolUse JSON verdict to stdout.

    systemMessage is shown to the user, styled like every other guard in the
    suite; a decision of "block" hands `reason` back to Claude to act on.
    Omitting the decision reports without interrupting.
    """
    out = {"systemMessage": style("emdash-guard", message, level)}
    if reason is not None:
        out["decision"] = "block"
        out["reason"] = reason
    json.dump(out, sys.stdout)
    sys.stdout.write("\n")


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

    if result.returncode != 1:  # 1 == dashes found; anything else == clean or broken
        if result.returncode == 0 and verbose("EMDASH_GUARD"):
            emit(f"checked {os.path.basename(path)}, no em dashes.")
        return 0

    count = count_hits(result.stdout)
    singular = count == 1
    noun = "em dash / stand-in dash" if singular else "em dashes / stand-in dashes"
    short_noun = "em dash" if singular else "em dashes"
    name = os.path.basename(path)
    mode = current_mode()

    if mode == "off":
        emit(f"{count} {noun} in {name}, not fixing.", level="warn")
        return 0

    detail = (
        f"emdash-guard: {count} {noun} found in {path}\n"
        f"For the exact spots (path:line:col per hit) run: "
        f"python3 {checker} {path}\n"
    )

    if mode == "prompt":
        emit(
            f"{count} {noun} in {name}, asking before fixing.",
            detail + "Autofix is set to 'prompt'. Ask the user with AskUserQuestion: "
            f"\"Remove the {count} {short_noun} in {name}?\" Rewrite the file only if "
            f"they say yes, and leave it exactly as written if they decline. {REWRITE}",
            level="ask",
        )
        return 0

    emit(
        f"{count} {noun} in {name}, fixing.",
        detail + REWRITE + " Then save the file again.",
        level="block",
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
