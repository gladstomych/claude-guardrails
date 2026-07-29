#!/usr/bin/env python3
"""Tests for emdash-guard's new-vs-pre-existing accounting.

The behaviour under test: editing one line of a document that already contains em
dashes must flag only what the edit introduced. Before this, the guard counted the
whole file, so a two-dash edit to a changelog with twenty pre-existing dashes
reported twenty-two and demanded all of them be rewritten, including published
text.

Run: python3 tests/test_baseline.py
"""
import json
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.join(os.path.dirname(HERE), "plugins", "emdash-guard", "scripts")
sys.path.insert(0, SCRIPTS)
from post_write_emdash import (  # noqa: E402
    hit_line_numbers,
    hit_signatures,
    split_new_and_preexisting,
)

HOOK = os.path.join(SCRIPTS, "post_write_emdash.py")
CHECKER = os.path.join(SCRIPTS, "check_em_dashes.py")

failures = []


def check(label, got, want):
    if got == want:
        print(f"  PASS  {label}")
    else:
        failures.append(f"FAIL  {label}: got {got!r} want {want!r}")
        print(f"  FAIL  {label}: got {got!r} want {want!r}")


def run_checker(text):
    return subprocess.run(
        [sys.executable, CHECKER], input=text,
        capture_output=True, text=True, timeout=30,
    ).stdout


# ── unit: parsing ────────────────────────────────────────────────────────────

def test_parsing():
    out = run_checker("clean line\nShe paused — then left.\n")
    check("hit_line_numbers finds the right line", hit_line_numbers(out), [2])
    check(
        "hit_signatures normalises whitespace",
        hit_signatures(out, "clean line\nShe   paused  —  then left.\n"),
        ["She paused — then left."],
    )
    check("no hits parses to empty", hit_line_numbers("all clean\n"), [])


# ── unit: the diff itself ────────────────────────────────────────────────────

def test_split():
    baseline = "Old entry — with a dash.\n"
    current = "New entry — added now.\nOld entry — with a dash.\n"
    new_lines, pre = split_new_and_preexisting(
        run_checker(current), current, run_checker(baseline), baseline,
    )
    check("one new hit identified", new_lines, [1])
    check("one pre-existing hit ignored", pre, 1)

    # Line numbers shift when text is inserted above. Keying on content must not
    # care: the old hit moves from line 1 to line 3 and stays pre-existing.
    current2 = "intro\nmore intro\nOld entry — with a dash.\n"
    new_lines2, pre2 = split_new_and_preexisting(
        run_checker(current2), current2, run_checker(baseline), baseline,
    )
    check("shifted line is still pre-existing", (new_lines2, pre2), ([], 1))

    # A duplicated flagged line means the copy is new.
    current3 = "Old entry — with a dash.\nOld entry — with a dash.\n"
    new_lines3, pre3 = split_new_and_preexisting(
        run_checker(current3), current3, run_checker(baseline), baseline,
    )
    check("duplicate of a flagged line counts as new", (len(new_lines3), pre3), (1, 1))

    # No baseline hits at all: everything is new.
    clean = "nothing here\n"
    new_lines4, pre4 = split_new_and_preexisting(
        run_checker(current), current, run_checker(clean), clean,
    )
    check("clean baseline -> all new", (len(new_lines4), pre4), (2, 0))


# ── integration: the hook against a real git repo ────────────────────────────

def run_hook(path, env=None):
    payload = json.dumps({"tool_name": "Edit", "tool_input": {"file_path": path}})
    merged = dict(os.environ)
    merged["EMDASH_GUARD_AUTOFIX"] = "on"
    if env:
        merged.update(env)
    out = subprocess.run(
        [sys.executable, HOOK], input=payload,
        capture_output=True, text=True, timeout=60, env=merged,
    ).stdout
    try:
        return json.loads(out)
    except (json.JSONDecodeError, ValueError):
        return {}


def git(*args, cwd):
    subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True)


def test_hook_integration():
    with tempfile.TemporaryDirectory() as tmp:
        git("init", "-q", cwd=tmp)
        git("config", "user.email", "t@example.com", cwd=tmp)
        git("config", "user.name", "T", cwd=tmp)
        doc = os.path.join(tmp, "CHANGELOG.md")

        # Commit a file that already has three em dashes.
        with open(doc, "w", encoding="utf-8") as fh:
            fh.write("v1 — first\nv2 — second\nv3 — third\n")
        git("add", "CHANGELOG.md", cwd=tmp)
        git("commit", "-q", "-m", "seed", cwd=tmp)

        # Touch the file without adding a dash: must not block.
        with open(doc, "a", encoding="utf-8") as fh:
            fh.write("v4 clean entry\n")
        verdict = run_hook(doc)
        check("pre-existing only -> no block", verdict.get("decision"), None)
        check(
            "pre-existing only -> reported as pre-existing",
            "pre-existing" in verdict.get("systemMessage", ""),
            True,
        )

        # Now add one dash of our own: must block, and name only that line.
        with open(doc, "a", encoding="utf-8") as fh:
            fh.write("v5 — mine\n")
        verdict = run_hook(doc)
        check("new hit -> blocks", verdict.get("decision"), "block")
        reason = verdict.get("reason", "")
        check("reason says 1 new", "1 new" in reason, True)
        check("reason points at line 5", "line 5" in reason, True)
        check("reason says 3 pre-existing are not ours", "3 further hit(s)" in reason, True)
        check("reason does not demand all 4", "4 em" not in reason, True)

        # Opt-out restores whole-file counting.
        verdict = run_hook(doc, env={"EMDASH_GUARD_BASELINE": "off"})
        check("BASELINE=off blocks on the whole file", verdict.get("decision"), "block")
        check(
            "BASELINE=off counts all 4",
            "4 em dashes" in verdict.get("reason", ""),
            True,
        )

        # An untracked file has no baseline: every hit is new.
        fresh = os.path.join(tmp, "NEW.md")
        with open(fresh, "w", encoding="utf-8") as fh:
            fh.write("brand new — with a dash\n")
        verdict = run_hook(fresh)
        check("untracked file -> blocks", verdict.get("decision"), "block")


def main():
    test_parsing()
    test_split()
    test_hook_integration()
    print()
    if failures:
        print(f"{len(failures)} failure(s)")
        return 1
    print("all baseline checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
