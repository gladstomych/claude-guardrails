#!/usr/bin/env python3
"""Read or set emdash-guard's spaced-hyphen handling.

Usage:
    python3 hyphen_mode.py            # print the current mode and where it came from
    python3 hyphen_mode.py flag       # spaced hyphens count as stand-in dashes (default)
    python3 hyphen_mode.py allow      # spaced hyphens are fine; only real dashes count

The vendored checker treats a spaced hyphen used as a pause ("results - mixed")
as a stand-in dash. Some writers use exactly that on purpose; `allow` keeps the
guard for em/en dashes and other unicode stand-ins while leaving plain hyphens
alone.

The mode lives in the same per-user file as autofix,
$CLAUDE_CONFIG_DIR/emdash-guard/config.json (default
~/.claude/emdash-guard/config.json), so it applies across every repo. The
EMDASH_GUARD_HYPHENS env var overrides the file for a single session and is
reported here but never written.

Exits 0 on success, 2 on an unknown mode or an unwritable config file.
"""

import json
import os
import sys

MODES = ("flag", "allow")
DEFAULT_MODE = "flag"

DESCRIPTIONS = {
    "flag": "spaced hyphens count as stand-in dashes, like upstream",
    "allow": "spaced hyphens are fine; only real em/en dashes and stand-ins count",
}


def config_path():
    base = os.environ.get("CLAUDE_CONFIG_DIR") or os.path.join(
        os.path.expanduser("~"), ".claude"
    )
    return os.path.join(base, "emdash-guard", "config.json")


def env_mode():
    raw = os.environ.get("EMDASH_GUARD_HYPHENS", "").strip().lower()
    return raw if raw in MODES else None


def file_mode():
    try:
        with open(config_path(), encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    raw = str(data.get("hyphens", "")).strip().lower()
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
    data["hyphens"] = mode
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2)
        fh.write("\n")


def main():
    args = [a for a in sys.argv[1:] if a.strip()]

    if not args:
        mode = current_mode()
        source = (
            "EMDASH_GUARD_HYPHENS env var" if env_mode()
            else config_path() if file_mode()
            else "default (no config file yet)"
        )
        print(f"emdash-guard hyphens: {mode} ({DESCRIPTIONS[mode]})")
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

    print(f"emdash-guard hyphens set to: {mode} ({DESCRIPTIONS[mode]})")
    print(f"  saved to: {config_path()}")
    if env_mode() and env_mode() != mode:
        print(f"  note: EMDASH_GUARD_HYPHENS={env_mode()} is set and still wins "
              "for this session", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
