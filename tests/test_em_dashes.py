#!/usr/bin/env python3
"""Tests for the emdash-guard checker.

Focus: the guard must catch dashes standing in for punctuation without flagging
legitimate hyphens. Two over-detections are pinned here as regressions:

  * CLI long options (`git diff --stat`) matched rule 3's `(?<=\\s)--(?=\\S)`
    alternative, which has been removed.
  * Ranges and attributions ("Monday - Friday", "Sunny - Secure Agentics")
    matched rule 4, which now requires a lowercase word after the hyphen.

Run: python3 tests/test_em_dashes.py
"""
import os
import sys

sys.path.insert(
    0,
    os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "plugins", "emdash-guard", "scripts",
    ),
)
from check_em_dashes import check  # noqa: E402

MUST_FLAG = [
    # The real thing and its look-alikes.
    ("em dash", "She paused — then left."),
    ("horizontal bar", "She paused ― then left."),
    ("en dash as pause", "She paused – then left."),
    # Double hyphen, glued and spaced on both sides.
    ("glued double hyphen", "She paused--then left."),
    ("spaced double hyphen", "She paused -- then left."),
    # Spaced hyphen continuing a sentence.
    ("spaced hyphen pause", "She paused - then left."),
    ("spaced hyphen mid-clause", "the run failed - it timed out"),
]

MUST_NOT_FLAG = [
    # Rule 3 regression: CLI long options in prose.
    ("cli flag", "Run npm run ci --silent to check."),
    ("cli flag bare", "psql --version"),
    ("cli flag with value", "aws ssm send-command --instance-ids i-123"),
    ("cli flag short line", "git diff --stat"),
    ("cli flag equals", "python3 -m pytest --maxfail=1"),
    # Rule 4 regression: ranges and attributions.
    ("weekday range", "Open Monday - Friday."),
    ("attribution", "Sunny - Secure Agentics"),
    ("letter range", "see appendix A - B"),
    ("numeric range", "pages 10 - 20"),
    # Already-correct behaviour that must not regress.
    ("hyphenated compound", "a well-known problem"),
    ("markdown list item", "- a bullet point"),
    ("horizontal rule", "---"),
    ("table separator", "| --- | --- |"),
    ("inline code masked", "use `total - spent` here"),
    ("url masked", "see https://example.com/a--b for more"),
    ("negative number", "the delta was -5 today"),
]


def main():
    failures = []

    for label, text in MUST_FLAG:
        if not check(text):
            failures.append(f"MISSED  {label}: {text!r}")
        else:
            print(f"  flags   {label}")

    for label, text in MUST_NOT_FLAG:
        hits = check(text)
        if hits:
            failures.append(
                f"FALSE+  {label}: {text!r} -> {[h[2].strip() for h in hits]}"
            )
        else:
            print(f"  clean   {label}")

    # Fenced code blocks are skipped wholesale.
    fenced = "```\nnpm run ci --silent\ntotal - spent\n```"
    if check(fenced):
        failures.append("FALSE+  fenced code block was checked")
    else:
        print("  clean   fenced code block")

    print()
    if failures:
        for f in failures:
            print(f)
        print(f"{len(failures)} failure(s)")
        return 1
    print(f"all {len(MUST_FLAG) + len(MUST_NOT_FLAG) + 1} checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
