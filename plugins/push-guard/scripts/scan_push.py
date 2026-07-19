#!/usr/bin/env python3
"""push-guard scanner: look for secrets and not-ready code in commits about to be pushed.

Usage:
    python3 scan_push.py [--repo DIR] [--range BASE..HEAD]

With no --range it works out what is unpushed on its own: every commit reachable
from HEAD that no remote branch already has. Nothing unpushed means nothing to
scan, which exits 0.

It reads only ADDED lines from the diff, so a secret you are deleting does not
block the push, and it looks at the commit subjects and changed file sizes for
the readiness checks.

Prints findings as  <SEV>  <file>:<line>: <why>  and exits:
  2  if any HIGH-severity finding (a shaped credential, a conflict marker),
  1  if only MEDIUM-severity findings (suspicious, worth a look),
  0  if clean.

Deterministic and offline. Regex secret scanning catches credentials with a
recognisable shape; it cannot catch a password that looks like an ordinary
string. Treat a clean result as "nothing obvious", not "nothing".
"""

import argparse
import os
import re
import subprocess
import sys

HIGH = "HIGH"
MED = "MED"

EMPTY_TREE = "4b825dc642cb6eb9a060e54bf8d69288fbee4904"
MAX_BLOB_BYTES = 5 * 1024 * 1024
MAX_COMMITS = 500  # a push bigger than this gets its newest 500 commits scanned

# (severity, regex, why). Shaped credentials are HIGH: a match is rarely an
# accident. The generic assignment rule is MED because config examples and test
# fixtures trip it constantly.
RULES = [
    (HIGH, re.compile(r'-----BEGIN (?:RSA |DSA |EC |OPENSSH |PGP )?PRIVATE KEY'),
     "private key block"),
    (HIGH, re.compile(r'\bAKIA[0-9A-Z]{16}\b'),
     "AWS access key id"),
    (HIGH, re.compile(r'\baws_secret_access_key\b\s*[:=]\s*\S{40}', re.IGNORECASE),
     "AWS secret access key"),
    (HIGH, re.compile(r'\bgh[pousr]_[A-Za-z0-9]{36,}\b'),
     "GitHub token"),
    (HIGH, re.compile(r'\bgithub_pat_[A-Za-z0-9_]{40,}\b'),
     "GitHub fine-grained token"),
    (HIGH, re.compile(r'\bxox[abprs]-[A-Za-z0-9-]{10,}\b'),
     "Slack token"),
    (HIGH, re.compile(r'\b[sr]k_(?:live|test)_[A-Za-z0-9]{16,}\b'),
     "Stripe key"),
    (HIGH, re.compile(r'\bAIza[0-9A-Za-z_\-]{35}\b'),
     "Google API key"),
    (HIGH, re.compile(r'\bsk-ant-[A-Za-z0-9_\-]{20,}\b'),
     "Anthropic API key"),
    (HIGH, re.compile(r'\bsk-[A-Za-z0-9]{32,}\b'),
     "OpenAI-style API key"),
    (HIGH, re.compile(r'\bpypi-AgEIcHlwaS5vcmc[A-Za-z0-9_\-]{10,}'),
     "PyPI upload token"),
    (HIGH, re.compile(r'\bnpm_[A-Za-z0-9]{36}\b'),
     "npm token"),
    (HIGH, re.compile(r'\beyJ[A-Za-z0-9_\-]{10,}\.eyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}'),
     "JSON Web Token"),
    (HIGH, re.compile(r'^(?:<{7}|>{7}) '),
     "unresolved merge conflict marker"),
    (MED, re.compile(
        r'\b(?:password|passwd|secret|api[_-]?key|access[_-]?token|auth[_-]?token)\b'
        r'\s*[:=]\s*[\'"][^\'"]{8,}[\'"]', re.IGNORECASE),
     "hardcoded credential assignment"),
    (MED, re.compile(r'\bBEGIN CERTIFICATE\b'),
     "embedded certificate"),
]

# Only ever applied to MED findings: these read as documentation, not a leak.
PLACEHOLDER = re.compile(
    r'example|placeholder|redacted|changeme|dummy|your[_-]|<[a-z_ -]+>|'
    r'xxxx|\*{4}|fake|sample|\bTODO\b', re.IGNORECASE)

# Paths that should not be in a push at all.
SECRET_PATHS = re.compile(
    r'(^|/)\.env(\.|$)|(^|/)\.npmrc$|(^|/)id_(rsa|dsa|ecdsa|ed25519)$|'
    r'(^|/)\.aws/credentials$|\.(pem|pfx|p12|keystore|jks)$', re.IGNORECASE)
# ... except the ones that exist precisely to be committed.
SECRET_PATH_OK = re.compile(r'\.env\.(example|sample|template)$|\.env\.dist$',
                            re.IGNORECASE)

NOT_READY_SUBJECT = re.compile(r'^(wip\b|fixup!|squash!|amend!|do not merge)',
                               re.IGNORECASE)


def git(args, cwd):
    """Run a git command, returning stdout, or None if git itself failed."""
    try:
        r = subprocess.run(["git"] + args, cwd=cwd, capture_output=True,
                           text=True, timeout=60)
    except (OSError, subprocess.SubprocessError):
        return None
    return r.stdout if r.returncode == 0 else None


def unpushed_base(cwd):
    """The commit to diff against: the parent of the oldest commit no remote has.

    Returns None when there is nothing unpushed (or no commits at all), and the
    empty-tree hash when the unpushed history goes all the way back to the root.
    """
    out = git(["rev-list", "HEAD", "--not", "--remotes"], cwd)
    if out is None:
        return None
    commits = out.split()
    if not commits:
        return None  # everything is already on a remote
    oldest = commits[-1]
    parent = git(["rev-parse", "--verify", "--quiet", oldest + "^"], cwd)
    return parent.strip() if parent and parent.strip() else EMPTY_TREE


def commits_in(cwd, base, head):
    """Every commit in base..head, oldest first, capped so a huge push stays fast."""
    out = git(["rev-list", "--reverse", "--max-count", str(MAX_COMMITS),
               f"{base}..{head}"], cwd)
    return (out or "").split()


def added_lines(cwd, base, head):
    """Yield (path, line_no, text) for every line added by any commit in base..head.

    Deliberately per-commit rather than a single base..HEAD diff. A collapsed diff
    shows the net change, so a secret added in one commit and deleted in the next
    disappears from it, while git still carries that blob to the remote forever.
    Scanning each commit against its parent catches it.
    """
    for commit in commits_in(cwd, base, head):
        parent = git(["rev-parse", "--verify", "--quiet", commit + "^"], cwd)
        parent = parent.strip() if parent and parent.strip() else EMPTY_TREE
        for item in added_lines_between(cwd, parent, commit):
            yield item


def added_lines_between(cwd, base, head):
    """Yield (path, line_no, text) for added lines in one diff.

    Line numbers come from the hunk headers, so they point at the new file.
    """
    out = git(["diff", "--unified=0", "--no-color", "--no-ext-diff",
               "--diff-filter=ACMR", f"{base}..{head}"], cwd)
    if out is None:
        return
    path = None
    line_no = 0
    hunk = re.compile(r'^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@')
    for raw in out.splitlines():
        if raw.startswith("+++ "):
            target = raw[4:].strip()
            path = None if target == "/dev/null" else target[2:] if target[:2] == "b/" else target
        elif raw.startswith("@@"):
            m = hunk.match(raw)
            line_no = int(m.group(1)) if m else 0
        elif raw.startswith("+") and not raw.startswith("+++"):
            if path is not None:
                yield path, line_no, raw[1:]
            line_no += 1


def changed_paths(cwd, base, head):
    out = git(["diff", "--name-only", "--diff-filter=ACMR", f"{base}..{head}"], cwd)
    return [p for p in (out or "").splitlines() if p.strip()]


def blob_size(cwd, head, path):
    out = git(["ls-tree", "-r", "-l", head, "--", path], cwd)
    if not out:
        return 0
    for line in out.splitlines():
        parts = line.split(None, 4)
        if len(parts) >= 4 and parts[3].isdigit():
            return int(parts[3])
    return 0


def scan_content(cwd, base, head):
    # A line touched by several commits would otherwise be reported once per
    # commit, so keep the first sighting of each distinct finding.
    seen = set()
    findings = []
    for path, line_no, text in added_lines(cwd, base, head):
        for sev, rx, why in RULES:
            if not rx.search(text):
                continue
            if sev == MED and PLACEHOLDER.search(text):
                continue  # documentation, not a leak
            key = (sev, path, line_no, why)
            if key in seen:
                continue
            seen.add(key)
            findings.append((sev, path, line_no, why, text.strip()[:100]))
    return findings


def scan_paths(cwd, base, head):
    findings = []
    for path in changed_paths(cwd, base, head):
        if SECRET_PATHS.search(path) and not SECRET_PATH_OK.search(path):
            findings.append((HIGH, path, 0, "file that normally holds credentials", path))
        size = blob_size(cwd, head, path)
        if size > MAX_BLOB_BYTES:
            findings.append((MED, path, 0,
                             f"large file ({size // (1024 * 1024)} MB) in the push", path))
    return findings


def scan_subjects(cwd, base, head):
    out = git(["log", "--format=%H %s", f"{base}..{head}"], cwd)
    findings = []
    for line in (out or "").splitlines():
        sha, _, subject = line.partition(" ")
        if NOT_READY_SUBJECT.match(subject.strip()):
            findings.append((MED, sha[:8], 0, "commit is marked not-ready", subject[:100]))
    return findings


def scan(cwd, rev_range=None):
    """Return (findings, base, head). An empty base means there was nothing to do."""
    if rev_range:
        base, _, head = rev_range.partition("..")
        head = head or "HEAD"
    else:
        base = unpushed_base(cwd)
        head = "HEAD"
    if not base:
        return [], None, head

    findings = scan_content(cwd, base, head)
    findings += scan_paths(cwd, base, head)
    findings += scan_subjects(cwd, base, head)
    findings.sort(key=lambda f: (f[0] != HIGH, f[1], f[2]))
    return findings, base, head


def report(findings, stream=sys.stdout):
    for sev, path, line_no, why, excerpt in findings:
        where = f"{path}:{line_no}" if line_no else path
        print(f"{sev:4} {where}: {why}", file=stream)
        if excerpt:
            print(f"       {excerpt}", file=stream)


def verdict(findings):
    if any(f[0] == HIGH for f in findings):
        return 2
    return 1 if findings else 0


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--repo", default=".", help="repository to scan (default: cwd)")
    ap.add_argument("--range", dest="rev_range",
                    help="explicit BASE..HEAD range instead of the unpushed one")
    args = ap.parse_args()

    if git(["rev-parse", "--git-dir"], args.repo) is None:
        print(f"not a git repository: {args.repo}", file=sys.stderr)
        return 2

    findings, base, _ = scan(args.repo, args.rev_range)
    if base is None:
        print("push-guard: nothing unpushed to scan.")
        return 0
    if not findings:
        print("push-guard: clean, no secrets or readiness problems in the unpushed commits.")
        return 0
    report(findings)
    return verdict(findings)


if __name__ == "__main__":
    sys.exit(main())
