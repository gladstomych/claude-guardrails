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

Hyphens setting (see scripts/hyphen_mode.py and /emdash-guard:hyphens):
  flag    a spaced hyphen used as a pause counts as a stand-in dash (default)
  allow   spaced hyphens are the user's own style and are never flagged; real
          em/en dashes and the other unicode stand-ins still count

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
from hyphen_mode import current_mode as hyphen_mode  # noqa: E402

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


def drop_hyphen_hits(checker_stdout):
    """Strip spaced-hyphen hits, for when the user's hyphens setting is `allow`.

    A plain hyphen is the one stand-in some writers use on purpose ("point 1 - so
    and so"). Real em/en dashes and the other unicode stand-ins keep counting.
    """
    return "\n".join(
        line for line in checker_stdout.splitlines()
        if not (": found '" in line and line.rstrip().endswith("'-'"))
    )


def hit_line_numbers(checker_stdout):
    """1-indexed line number for each hit, in the order reported.

    Output shape is "{label}:{line}:{col}: found '{ch}'". rsplit is used rather
    than split because a label can itself contain colons (an absolute Windows
    path, for one).
    """
    nums = []
    for line in checker_stdout.splitlines():
        if ": found '" not in line:
            continue
        head = line.split(": found '", 1)[0]
        parts = head.rsplit(":", 2)
        if len(parts) != 3:
            continue
        try:
            nums.append(int(parts[1]))
        except ValueError:
            continue
    return nums


def hit_signatures(checker_stdout, text):
    """One signature per hit: the whitespace-normalised text of its line.

    Keyed on line *content* rather than line number on purpose. Inserting a
    paragraph shifts the number of every hit below it, so a number-based diff
    would report the whole tail of the file as new. The line's own text is stable
    across insertions above it.
    """
    lines = text.splitlines()
    sigs = []
    for n in hit_line_numbers(checker_stdout):
        if 1 <= n <= len(lines):
            sigs.append(" ".join(lines[n - 1].split()))
    return sigs


def git_head_text(path):
    """The committed version of `path`, or None if unavailable.

    None covers every "no baseline to compare against" case: not a git repo, a
    brand-new untracked file, a detached/empty HEAD, git missing entirely. Callers
    treat None as "every hit is new", which is the pre-baseline behaviour.
    """
    directory = os.path.dirname(os.path.abspath(path))
    try:
        top = subprocess.run(
            ["git", "-C", directory, "rev-parse", "--show-toplevel"],
            capture_output=True, text=True, timeout=10,
        )
        if top.returncode != 0:
            return None
        root = top.stdout.strip()
        rel = os.path.relpath(os.path.abspath(path), root).replace(os.sep, "/")
        show = subprocess.run(
            ["git", "-C", root, "show", f"HEAD:{rel}"],
            capture_output=True, text=True, timeout=10,
        )
        if show.returncode != 0:
            return None
        return show.stdout
    except (OSError, subprocess.SubprocessError):
        return None


def split_new_and_preexisting(current_stdout, current_text, baseline_stdout,
                             baseline_text):
    """(new_line_numbers, preexisting_count) for the hits in the current file.

    A hit counts as pre-existing when the committed file already had a hit on an
    identically-worded line. Multiplicity is respected: if the baseline had one
    flagged line and the edit duplicated it, the copy is new.
    """
    current_lines = hit_line_numbers(current_stdout)
    current_sigs = hit_signatures(current_stdout, current_text)
    baseline_sigs = hit_signatures(baseline_stdout, baseline_text)

    budget = {}
    for sig in baseline_sigs:
        budget[sig] = budget.get(sig, 0) + 1

    new_lines = []
    for line_no, sig in zip(current_lines, current_sigs):
        if budget.get(sig, 0) > 0:
            budget[sig] -= 1
        else:
            new_lines.append(line_no)
    return new_lines, len(current_lines) - len(new_lines)


def baseline_enabled():
    """EMDASH_GUARD_BASELINE=off restores whole-file counting."""
    return os.environ.get("EMDASH_GUARD_BASELINE", "").strip().lower() != "off"


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

    name = os.path.basename(path)
    allow_hyphens = hyphen_mode() == "allow"
    hits = drop_hyphen_hits(result.stdout) if allow_hyphens else result.stdout

    total = count_hits(hits)
    if total == 0:
        # Everything flagged was a spaced hyphen, and those are the user's style.
        if verbose("EMDASH_GUARD"):
            emit(f"checked {name}, no em dashes (spaced hyphens allowed).")
        return 0

    mode = current_mode()

    # Only the dashes this edit introduced are actionable. Counting the whole file
    # meant that touching one line of a long document demanded a rewrite of every
    # pre-existing dash in it, including published text that was not ours to
    # change -- a two-dash edit to a changelog reported twenty-two.
    new_lines, preexisting = [], 0
    if baseline_enabled():
        baseline_text = git_head_text(path)
        if baseline_text is not None:
            try:
                with open(path, "r", encoding="utf-8") as fh:
                    current_text = fh.read()
                baseline_run = subprocess.run(
                    [sys.executable, checker],
                    input=baseline_text, capture_output=True, text=True, timeout=30,
                )
                baseline_hits = (drop_hyphen_hits(baseline_run.stdout)
                                 if allow_hyphens else baseline_run.stdout)
                new_lines, preexisting = split_new_and_preexisting(
                    hits, current_text, baseline_hits, baseline_text,
                )
            except (OSError, subprocess.SubprocessError, UnicodeDecodeError):
                new_lines, preexisting = [], 0  # fail open: treat all as new

    if preexisting and not new_lines:
        # Everything flagged was already committed. Report it so the count is not
        # a surprise later, but do not make it this edit's problem.
        emit(
            f"{preexisting} pre-existing em dash{'' if preexisting == 1 else 'es'} "
            f"in {name}, none added by this edit.",
            level="warn",
        )
        return 0

    count = len(new_lines) if preexisting else total
    singular = count == 1
    noun = "em dash / stand-in dash" if singular else "em dashes / stand-in dashes"
    short_noun = "em dash" if singular else "em dashes"

    if mode == "off":
        emit(f"{count} {noun} in {name}, not fixing.", level="warn")
        return 0

    hyphen_note = (
        "Spaced hyphens ('-') are allowed by the user's setting; if the checker "
        "lists any, leave them alone.\n"
    ) if allow_hyphens else ""

    if preexisting:
        where = ", ".join(f"line {n}" for n in new_lines)
        detail = (
            f"emdash-guard: {count} new {noun} in {path} ({where}).\n"
            f"{preexisting} further hit(s) were already in the committed file and "
            f"are NOT yours to fix -- leave them alone.\n"
            f"To see everything, new and pre-existing: python3 {checker} {path}\n"
            f"{hyphen_note}"
        )
    else:
        detail = (
            f"emdash-guard: {count} {noun} found in {path}\n"
            f"For the exact spots (path:line:col per hit) run: "
            f"python3 {checker} {path}\n"
            f"{hyphen_note}"
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
