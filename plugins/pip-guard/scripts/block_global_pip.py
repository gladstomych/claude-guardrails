#!/usr/bin/env python3
"""PreToolUse hook: keep pip installs inside a virtual environment.

Claude Code runs this before every Bash tool call (see hooks.json). If the
command runs `pip install` (pip, pip3, pipX.Y, or `python -m pip`) into the
global system or user site-packages, it blocks the call and points Claude at
the project venv: the default and recommended way to install Python packages
is a virtual environment, unless the user has explicitly said otherwise.

The guard stands down when the install already targets an isolated
environment: a VIRTUAL_ENV or CONDA_PREFIX inherited from the session, an
interpreter path-qualified into an env (`.venv/bin/pip`), an activation earlier
in the same command, or an install redirected off the global site-packages
(--target/--prefix/--root). Merely creating a venv (`python -m venv`,
`virtualenv`, `uv venv`) earns no pass: a bare pip after creation still hits
the global site-packages. `uv pip install` passes on uv's own venv enforcement
except its explicit global forms (--system, or --python pointing outside an
env); the rest of uv (add/sync/run) manages its own envs and is not pip.
When the user has explicitly asked for a global install, rerunning the command
prefixed with PIP_GUARD_ALLOW=1 (or setting it in the environment) lets it
through.

Tool layer only: a pip run from inside a script file is invisible here. That
is the accepted trade; the remit is the commands Claude itself writes.
"""

import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from hookout import deny, note, verbose  # noqa: E402

# One shell segment per pipeline/list element; pip is identified per segment,
# so `cd x && pip install y` and `pip install y | tee log` both resolve.
SEGMENTS = re.compile(r"[|;&\n]+")

# The executables that matter: pip / pip3 / pip3.12, python / python3.12.
PIP = re.compile(r"^pip[0-9]*(?:\.[0-9]+)?$")
PYTHON = re.compile(r"^python[0-9]*(?:\.[0-9]+)?$")

# Wrappers to look through before the real executable.
WRAPPERS = {"sudo", "env", "command", "exec", "nohup", "time"}

# A pip path-qualified into these is still the system's, not an env's.
SYSTEM_PREFIXES = ("/usr/", "/bin/", "/sbin/")

# The command enters a venv, so a bare pip after it is the venv's. Activation
# only: merely *creating* one (`python -m venv`, `virtualenv`, `uv venv`) does
# not redirect a bare pip in the same command, so creation earns no pass.
ACTIVATION = re.compile(r"(?:^|[\s;&|(])(?:source|\.)\s+\S*bin/activate")

# Install options that deliberately redirect off the global site-packages.
REDIRECTS = {"--target", "--prefix", "--root"}


def allow_override(command):
    """Has the user's explicit go-ahead been recorded, inline or in the env?"""
    inline = re.search(r"\bPIP_GUARD_ALLOW=(\S+)", command)
    raw = inline.group(1) if inline else os.environ.get("PIP_GUARD_ALLOW", "")
    return raw.strip().strip("'\"").lower() not in ("", "0", "false", "no", "off")


def venv_interpreter(exe):
    """A pip/python path-qualified under some env's bin/, not the system's."""
    return "/bin/" in exe and not exe.startswith(SYSTEM_PREFIXES)


def install_target(segment):
    """None if the segment is not a pip install, else "venv" or "global"."""
    tokens = segment.split()
    venv_assigned = False
    i = 0
    while i < len(tokens):
        tok = tokens[i]
        if re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", tok):
            venv_assigned = venv_assigned or tok.startswith("VIRTUAL_ENV=")
            i += 1
            continue
        if os.path.basename(tok) in WRAPPERS:
            i += 1
            continue
        break
    if i >= len(tokens):
        return None

    exe, rest = tokens[i], tokens[i + 1:]
    base = os.path.basename(exe)
    uv = False
    if base == "uv":
        if rest and rest[0] == "pip":
            uv = True
            rest = rest[1:]
        else:
            return None  # uv add/sync/venv/run manage their own envs
    elif PYTHON.match(base):
        if len(rest) >= 2 and rest[0] == "-m" and PIP.match(rest[1]):
            rest = rest[2:]
        else:
            return None
    elif not PIP.match(base):
        return None

    subcommand = next((t for t in rest if not t.startswith("-")), "")
    if subcommand != "install":
        return None  # list/show/freeze/... never mutate an environment

    if uv:
        # uv refuses to touch anything but a venv unless told otherwise, so a
        # plain `uv pip install` is venv-targeted by uv's own enforcement. The
        # told-otherwise forms are the global ones.
        for j, tok in enumerate(rest):
            opt, _, val = tok.partition("=")
            if opt == "--system":
                return "global"
            if opt in ("--python", "-p"):
                target = val or (rest[j + 1] if j + 1 < len(rest) else "")
                if not venv_interpreter(target):
                    return "global"
        return "venv"

    if venv_assigned or venv_interpreter(exe):
        return "venv"
    if any(t.split("=", 1)[0] in REDIRECTS for t in rest):
        return "venv"
    return "global"


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

    installs = [t for t in map(install_target, SEGMENTS.split(command)) if t]
    if not installs:
        return 0  # not a pip install; this hook must not narrate `ls`

    isolated = (
        "global" not in installs
        or os.environ.get("VIRTUAL_ENV")
        or os.environ.get("CONDA_PREFIX")
        or ACTIVATION.search(command)
    )
    if isolated:
        if verbose("PIP_GUARD"):
            return note("pip-guard", "checked the pip install, it targets a venv.")
        return 0

    if allow_override(command):
        if verbose("PIP_GUARD"):
            return note("pip-guard",
                        "allowed a global pip install, PIP_GUARD_ALLOW is set.", "warn")
        return 0

    return deny(
        "pip-guard: refusing this pip install.\n"
        "It would install into the global (system or user) site-packages, and the "
        "default and recommended way here is a virtual environment.\n"
        "Use the project's venv: run `.venv/bin/pip install ...` or activate it first "
        "(`source .venv/bin/activate`); if the project has no venv yet, create one "
        "with `python3 -m venv .venv`.\n"
        "Only if the user has explicitly asked for a global install in this session, "
        "rerun the exact command prefixed with `PIP_GUARD_ALLOW=1 `. Do not route "
        "around the guard otherwise.",
        "pip-guard",
        "blocked a pip install outside a venv; use the project venv "
        "(PIP_GUARD_ALLOW=1 overrides).",
    )


if __name__ == "__main__":
    sys.exit(main())
