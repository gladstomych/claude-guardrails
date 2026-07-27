#!/usr/bin/env python3
"""Hook output helpers, and the house style for everything a guard says.

A hook that exits 2 sends its stderr to Claude only. The user sees nothing, so a
guard doing its job looks identical to a guard that is not installed. Returning
JSON instead splits the audience: the decision reason goes to Claude, and
`systemMessage` is shown to the user.

Copied, not imported, into each guard plugin. The plugins in this marketplace are
independently installable, so none of them may depend on another being present.
Change this file and copy it to the others, or they drift.

STYLE GUIDE
-----------
Every notice is one line: `<plugin>: <symbol> <message>`.

The plugin name is bold cyan in every plugin, always. It is the suite's
signature, so a glance tells you a guardrail spoke and which one.

The message colour and symbol carry what happened:

  level   colour        symbol  meaning
  block   bold red      x       refused; the action did not happen
  warn    yellow        !       stopped on a softer signal, or allowed with a caveat
  ask     bold magenta  ?       stopped, waiting on a decision from you
  ok      green         +       checked, nothing wrong
  info    dim grey              neutral status, nothing to act on

Symbols are ASCII on purpose. This repo keeps its source ASCII-clean, and a
symbol that survives a log file, a pipe, or a colourblind reader is worth more
than a prettier glyph that only works in a colour terminal.

Wording rules, so the lines read as one voice:
  - Lower case after the colon, ending in a period.
  - Lead with the verb in past tense: "blocked a push...", "checked...".
  - A block states the decisive evidence inline, so the one line is actionable
    without expanding anything: "blocked a push, 1 secret (cfg.py: AWS key)".
  - Counts are numeric and agree in number: "1 em dash", "3 em dashes".
  - One line, no newlines, under ~100 characters. The full findings list is
    Claude's channel, not the user's.

Colour is ANSI on stdout, never gated on isatty, because a hook's stdout is a
pipe to the harness by definition. NO_COLOR (any value) or GUARDRAILS_COLOR=0
turns colour off; the symbols stay, so severity survives without it.

Reporting a PASS is on by default, because a silent guard is an invisible guard.
The caller is responsible for only speaking on a RELEVANT tool call: the file
actually checked, the `git commit` or `git push` actually scanned. A guard hooked
to Bash must not narrate `ls`. Silence pass notices with <PLUGIN>_VERBOSE=0, or
GUARDRAILS_VERBOSE=0 for all of them. Nothing silences a block.
"""

import json
import os
import sys

OFF = ("0", "false", "no", "off")

RESET = "\033[0m"
BRAND = "\033[1;36m"  # bold cyan, the suite's signature

# level -> (colour, ascii symbol)
LEVELS = {
    "block": ("\033[1;31m", "x"),
    "warn": ("\033[33m", "!"),
    "ask": ("\033[1;35m", "?"),
    "ok": ("\033[32m", "+"),
    "info": ("\033[2m", ""),
}


def _setting(name):
    """True/False if the env var is set to something meaningful, else None."""
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return None
    return raw.strip().lower() not in OFF


def verbose(plugin_env_prefix):
    """Should a passing check be reported? Per-plugin setting wins, then global."""
    for name in (f"{plugin_env_prefix}_VERBOSE", "GUARDRAILS_VERBOSE"):
        setting = _setting(name)
        if setting is not None:
            return setting
    return True  # visible by default


def colour():
    if os.environ.get("NO_COLOR") is not None:
        return False  # the NO_COLOR convention: presence is enough, value ignored
    setting = _setting("GUARDRAILS_COLOR")
    return True if setting is None else setting


def style(plugin, message, level="ok"):
    """Render one notice in house style. See the STYLE GUIDE above."""
    tone, symbol = LEVELS.get(level, LEVELS["ok"])
    body = f"{symbol} {message}" if symbol else message
    if not colour():
        return f"{plugin}: {body}"
    return f"{BRAND}{plugin}{RESET}: {tone}{body}{RESET}"


def _write(payload):
    json.dump(payload, sys.stdout)
    sys.stdout.write("\n")
    return 0


def deny(reason, plugin, message, level="block"):
    """Block the tool call: `reason` to Claude, one styled line to the user.

    `level` is "block" for a refusal on hard evidence and "warn" for one on a
    softer signal the user can override. Both stop the call; the colour says how
    sure the guard is.
    """
    return _write({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        },
        "systemMessage": style(plugin, message, level),
    })


def note(plugin, message, level="ok"):
    """Tell the user something without blocking or involving Claude."""
    return _write({"systemMessage": style(plugin, message, level)})
