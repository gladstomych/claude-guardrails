#!/usr/bin/env python3
"""Read or set emdash-guard's autofix mode.

Usage:
    python3 autofix_mode.py            # print the current mode and where it came from
    python3 autofix_mode.py on         # block and have Claude rewrite (default)
    python3 autofix_mode.py off        # never block, only report the count
    python3 autofix_mode.py prompt     # block, but ask the user before rewriting

The mode lives in one per-user file, $CLAUDE_CONFIG_DIR/emdash-guard/config.json
(default ~/.claude/emdash-guard/config.json), so it applies across every repo.
The EMDASH_GUARD_AUTOFIX env var overrides the file for a single session and is
reported here but never written.

Exits 0 on success, 2 on an unknown mode or an unwritable config file.
"""

import json
import os
import sys

MODES = ("on", "off", "prompt")
DEFAULT_MODE = "on"

DESCRIPTIONS = {
    "on": "block the write and have Claude rewrite each dash with real punctuation",
    "off": "never block; just report how many dashes the file has",
    "prompt": "block, and have Claude ask you first before rewriting",
}


def config_path():
    base = os.environ.get("CLAUDE_CONFIG_DIR") or os.path.join(
        os.path.expanduser("~"), ".claude"
    )
    return os.path.join(base, "emdash-guard", "config.json")


def env_mode():
    raw = os.environ.get("EMDASH_GUARD_AUTOFIX", "").strip().lower()
    return raw if raw in MODES else None


def file_mode():
    try:
        with open(config_path(), encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    raw = str(data.get("autofix", "")).strip().lower()
    return raw if raw in MODES else None


def current_mode():
    """The mode the hook will actually use: env var, then file, then default."""
    return env_mode() or file_mode() or DEFAULT_MODE


def write_mode(mode):
    path = config_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    data = {}
    try:
        with open(path, encoding="utf-8") as fh:
            loaded = json.load(fh)
        if isinstance(loaded, dict):
            data = loaded
    except (OSError, ValueError):
        pass  # absent or corrupt: start clean rather than fail the toggle
    data["autofix"] = mode
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2)
        fh.write("\n")


def main():
    args = [a for a in sys.argv[1:] if a.strip()]

    if not args:
        mode = current_mode()
        source = (
            "EMDASH_GUARD_AUTOFIX env var" if env_mode()
            else config_path() if file_mode()
            else "default (no config file yet)"
        )
        print(f"emdash-guard autofix: {mode} ({DESCRIPTIONS[mode]})")
        print(f"  source: {source}")
        return 0

    mode = args[0].strip().lower()
    if mode not in MODES:
        print(f"unknown mode: {args[0]!r}. Use one of: {', '.join(MODES)}",
              file=sys.stderr)
        return 2

    try:
        write_mode(mode)
    except OSError as exc:
        print(f"could not write {config_path()}: {exc}", file=sys.stderr)
        return 2

    print(f"emdash-guard autofix set to: {mode} ({DESCRIPTIONS[mode]})")
    print(f"  saved to: {config_path()}")
    if env_mode() and env_mode() != mode:
        print(f"  note: EMDASH_GUARD_AUTOFIX={env_mode()} is set and still wins "
              "for this session", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
