#!/usr/bin/env python3
"""Stop hook: chat shell snippets must run in the user's own shell.

Claude Code runs this when a reply finishes (see hooks.json). Commands shown in
chat get copy-pasted into the user's terminal, and that terminal runs whatever
$SHELL says, not whatever dialect the model happened to write. A fish user who
pastes `export VAR=val` gets a syntax error; a bash user who pastes
`set -gx VAR val` gets nonsense. This hook reads the turn's assistant text from
the transcript, checks each fenced shell snippet against the user's shell, and
if any would break, blocks the stop once so Claude re-emits the affected
commands natively.

The target shell is dynamic, never hardcoded: $SHELL decides which rule set
applies (fish gets checked for bash-isms, POSIX-family shells for fish-isms).
PASTE_GUARD_SHELL overrides the detection for a session; set it to `off` to
stand the guard down. An unrecognised shell is left alone.

Scope is chat text only, on purpose. Scripts Claude writes to disk go through
Write/Edit and are invisible here; a script *displayed* in chat is skipped when
it opens with a shebang (its dialect is declared, not the user's problem) or is
longer than PASTE_GUARD_MAX_LINES (default 25; that is a file listing, not a
paste). Only fenced blocks tagged as shell (```bash, ```sh, ```zsh, ```fish,
```shell, ```console, ```terminal) are checked; untagged fences are ignored.

Loop safety: when `stop_hook_active` is true this stop is already a hook's
continuation, and the hook stands down unconditionally. One block, one re-emit,
never a cycle. Always exits 0; the verdict travels in the JSON.
"""

import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from hookout import style, verbose  # noqa: E402

MAX_TRANSCRIPT_TAIL = 512 * 1024

FENCE = re.compile(r"^```([^\n`]*)\n(.*?)^```[ \t]*$", re.M | re.S)
SHELL_TAGS = {"bash", "sh", "shell", "zsh", "fish", "console", "terminal"}

# Shell family decides which rule set applies. Anything not listed (nu, pwsh,
# csh, ...) is left alone rather than guessed at.
POSIX_FAMILY = {"bash", "zsh", "sh", "dash", "ksh", "ash", "busybox"}

# Each rule: (regex, what the snippet says, what the user's shell wants).
# Deliberately the high-confidence breakers only: constructs the target shell
# rejects outright, not style differences.

# POSIX-isms that fish rejects.
BASHISMS = [
    (re.compile(r"^\s*export\s+[A-Za-z_]\w*=", re.M),
     "export VAR=val", "set -x VAR val"),
    (re.compile(r"^\s*[A-Za-z_]\w*=[^\s(=][^\s]*\s*$", re.M),
     "VAR=val assignment", "set VAR val"),
    (re.compile(r"^\s*[A-Za-z_]\w*=\(", re.M),
     "arr=( ... ) array", "set arr a b c"),
    (re.compile(r"\$\{[A-Za-z_]\w*[^}]*\}"),
     "${VAR} expansion", "$VAR (or {$VAR}foo)"),
    (re.compile(r"<<-?\s*['\"]?[A-Za-z_]\w*['\"]?\s*$", re.M),
     "heredoc", "printf/echo piping, fish has no heredocs"),
    (re.compile(r"`[^`\n]+`"),
     "backtick substitution", "(cmd) or $(cmd)"),
    (re.compile(r"(?:^|;)\s*then\b", re.M),
     "if ...; then", "if test ...; ...; end"),
    (re.compile(r"(?:^|;)\s*(?:do|done)\b", re.M),
     "for/while ...; do ... done", "for x in ...; ...; end"),
    (re.compile(r"^\s*(?:function\s+)?[A-Za-z_]\w*\s*\(\)\s*\{", re.M),
     "name() { ... } function", "function name; ...; end"),
    (re.compile(r"^\s*(?:declare|typeset|local|readonly)\s+", re.M),
     "declare/typeset/local/readonly", "set (scope with -l / -g)"),
    (re.compile(r"^\s*unset\s+[A-Za-z_]\w*", re.M),
     "unset VAR", "set -e VAR"),
]

# fish-isms that POSIX shells reject.
FISHISMS = [
    (re.compile(r"^\s*set\s+-[A-Za-z]*[gxUl][A-Za-z]*\s+[A-Za-z_]\w*(\s|$)", re.M),
     "fish set -gx VAR val", "export VAR=val"),
    (re.compile(r"^\s*set\s+-e\s+[A-Za-z_]\w*\s*$", re.M),
     "fish set -e VAR", "unset VAR"),
    (re.compile(r"^\s*function\s+[A-Za-z_][-\w]*\s*$", re.M),
     "function ... end", "name() { ...; }"),
    (re.compile(r"(?:^|;)\s*end\s*$", re.M),
     "end keyword", "fi / done / }"),
    # Bare (cmd) substitutes in fish but is a syntax error in POSIX shells
    # anywhere but command position. Only argument position is flagged: the
    # paren must follow a word-ish token (`--flag (cmd)`, `set x (cmd)`), so
    # legitimate subshells (`(cd x && make)`, `a && (b)`) and $(cmd) pass.
    (re.compile(r"[\w\"'\]}=/-][ \t]+\([^)\s]", re.M),
     "(cmd) substitution as an argument", "$(cmd)"),
]

RULESETS = {"fish": BASHISMS, "posix": FISHISMS}


def target_shell():
    """(name, family) of the shell pastes will land in, or (None, None).

    PASTE_GUARD_SHELL wins over $SHELL so the target can be pinned or the guard
    stood down (`off`) without touching the login shell.
    """
    raw = os.environ.get("PASTE_GUARD_SHELL", "").strip() or \
        os.environ.get("SHELL", "").strip()
    name = os.path.basename(raw).lower()
    if not name or name in ("off", "0", "none"):
        return None, None
    if name == "fish":
        return name, "fish"
    if name in POSIX_FAMILY:
        return name, "posix"
    return None, None


def max_lines():
    try:
        return int(os.environ.get("PASTE_GUARD_MAX_LINES", "25"))
    except ValueError:
        return 25


def turn_text(transcript_path):
    """All assistant text since the last real user message, joined.

    Tool results are user-role entries without text blocks and do not reset the
    collection; only a message the human actually typed does.
    """
    try:
        with open(transcript_path, "rb") as fh:
            fh.seek(0, os.SEEK_END)
            size = fh.tell()
            fh.seek(max(0, size - MAX_TRANSCRIPT_TAIL))
            raw = fh.read().decode("utf-8", "replace")
    except OSError:
        return ""

    texts = []
    for line in raw.splitlines():
        try:
            msg = (json.loads(line) or {}).get("message") or {}
        except ValueError:
            continue
        role, content = msg.get("role"), msg.get("content")
        if role == "user":
            typed = isinstance(content, str) or any(
                isinstance(b, dict) and b.get("type") == "text"
                for b in (content if isinstance(content, list) else [])
            )
            if typed:
                texts = []
        elif role == "assistant":
            if isinstance(content, str):
                texts.append(content)
            elif isinstance(content, list):
                texts.extend(b.get("text", "") for b in content
                             if isinstance(b, dict) and b.get("type") == "text")
    return "\n\n".join(texts)


COMMENT_LINE = re.compile(r"^[ \t]*#.*$", re.M)
SINGLE_QUOTED = re.compile(r"'[^']*'", re.S)
TRAILING_COMMENT = re.compile(r"\s#.*$", re.M)


def neutralise_literals(body):
    """Blank out regions every shell treats literally, keeping line structure.

    Backticks in a single-quoted SQL string or a `code` mention in a comment
    are not shell syntax and must not trip a rule; session history showed both,
    full-line and trailing. Full-line comments go first so an apostrophe in
    prose does not open a bogus quote span; trailing comments go after the
    quote pass so a '#' inside a quoted string is not mistaken for one.
    Blanked spans keep their newlines, so finding line numbers hold.
    """
    body = COMMENT_LINE.sub(lambda m: " " * len(m.group(0)), body)
    body = SINGLE_QUOTED.sub(
        lambda m: "".join(c if c == "\n" else " " for c in m.group(0)), body)
    return TRAILING_COMMENT.sub(lambda m: " " * len(m.group(0)), body)


def paste_snippets(text):
    """The fenced blocks a user would copy: shell-tagged, short, no shebang."""
    snippets = []
    for tag, body in FENCE.findall(text):
        word = tag.strip().split()[0].lower() if tag.strip() else ""
        if word not in SHELL_TAGS:
            continue
        lines = body.splitlines()
        if not lines or len(lines) > max_lines():
            continue
        if lines[0].startswith("#!"):
            continue  # a displayed script declares its own dialect
        # Console-style blocks prefix commands with "$ "; strip the prompt.
        cleaned = "\n".join(l[2:] if l.startswith("$ ") else l for l in lines)
        snippets.append(neutralise_literals(cleaned))
    return snippets


def findings_in(snippets, rules):
    found = []
    for idx, body in enumerate(snippets, 1):
        for regex, what, native in rules:
            m = regex.search(body)
            if m:
                line_no = body.count("\n", 0, m.start()) + 1
                found.append(f"snippet {idx}, line {line_no}: {what} -> {native}")
    return found


def emit(payload):
    json.dump(payload, sys.stdout)
    sys.stdout.write("\n")
    return 0


def main():
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return 0

    if payload.get("stop_hook_active"):
        return 0  # already a hook continuation; one re-emit, never a loop

    shell, family = target_shell()
    if not family:
        return 0

    text = turn_text(payload.get("transcript_path") or "")
    if "```" not in text:
        return 0

    snippets = paste_snippets(text)
    if not snippets:
        return 0  # nothing paste-shaped; stay quiet about irrelevant replies

    found = findings_in(snippets, RULESETS[family])

    if not found:
        if verbose("PASTE_GUARD"):
            n = len(snippets)
            return emit({"systemMessage": style(
                "paste-guard",
                f"checked {n} shell snippet{'' if n == 1 else 's'}, "
                f"pastes clean into {shell}.",
            )})
        return 0

    shown = found[:6]
    more = len(found) - len(shown)
    reason_lines = [
        f"paste-guard: this reply shows shell snippet(s) the user will "
        f"copy-paste into their terminal, and their shell is {shell}. "
        f"These lines would break there:",
        *(f"  {f}" for f in shown),
        *([f"  ... and {more} more"] if more > 0 else []),
        f"Re-emit just the affected command(s) in {shell} syntax in a brief "
        "follow-up so the paste works. Do not run tools and do not edit any "
        "file. If a snippet was an excerpt of an existing script file rather "
        "than a command for the user to run, leave it as it is and say which "
        "shell the script is for.",
    ]
    return emit({
        "decision": "block",
        "reason": "\n".join(reason_lines),
        "systemMessage": style(
            "paste-guard",
            f"flagged {len(found)} line{'' if len(found) == 1 else 's'} that "
            f"would break in {shell}; asked for a native re-emit.",
            "block",
        ),
    })


if __name__ == "__main__":
    sys.exit(main())
