#!/usr/bin/env python3
"""plugin-vet deterministic scanner: flag malware-ish patterns in a plugin dir.

Usage: python3 scan_plugin.py <plugin-dir>

Walks the directory and scans text files (hooks.json, plugin.json, package.json,
scripts, command markdown) for known-bad and suspicious patterns. Plugin hooks run
UNSANDBOXED at the user's trust level, so an install is effectively arbitrary code
execution; this is the fast first gate before that happens.

Prints findings as  <SEV>  <file>:<line>: <why>  and exits:
  2  if any HIGH-severity (likely malicious) finding,
  1  if only MEDIUM-severity (suspicious, review) findings,
  0  if clean.

Deterministic and offline. It cannot see logic-level threats (staged payloads,
clever obfuscation); pair it with a human or AI review of the same files.
"""

import json
import os
import re
import sys

HIGH = "HIGH"
MED = "MED"

# (severity, regex, why)
RULES = [
    (HIGH, re.compile(r'\b(curl|wget)\b[^\n|]*\|\s*(sudo\s+)?(ba)?sh\b'),
     "pipes a network download straight into a shell"),
    (HIGH, re.compile(r'\bbase64\b.*(-d|--decode).*\|\s*((ba)?sh|python[0-9]*|node)\b'),
     "decodes base64 and pipes it to an interpreter"),
    (HIGH, re.compile(r'/dev/tcp/|\bnc\b[^\n]*\s-e\b|\bbash\s+-i\b'),
     "reverse-shell / raw TCP socket pattern"),
    (HIGH, re.compile(r'\benv\b\s*\|\s*(curl|wget|nc|ncat)\b'),
     "pipes environment variables to the network (exfiltration)"),
    (HIGH, re.compile(r'\b(cat|cp|tar|scp|rsync)\b[^\n]*(\.ssh|\.aws|\.config/gcloud|\.npmrc|/\.env)\b'),
     "reads ssh/aws/gcloud/npm/env credential files"),
    (HIGH, re.compile(r'\bcrontab\b\s+-|/etc/cron|/etc/systemd/'),
     "installs cron/systemd persistence"),
    (HIGH, re.compile(r'>>?\s*~?/?(\.bashrc|\.zshrc|\.profile|\.bash_profile|\.config/fish)\b'),
     "writes to a shell startup file (persistence)"),
    (HIGH, re.compile(r'\bchmod\b\s+[0-7]*[+]?s\b'),
     "sets the setuid/setgid bit"),
    (MED, re.compile(r'\b(curl|wget|nc|ncat)\b'),
     "makes a network call (a hook phoning home deserves scrutiny)"),
    (MED, re.compile(r'\beval\b'),
     "uses eval"),
    (MED, re.compile(r'\bsudo\b'),
     "uses sudo"),
    (MED, re.compile(r'\brm\s+-[rf]{1,2}\s+\S*\$'),
     "rm -rf with a variable path"),
    (MED, re.compile(r'\bpython[0-9]*\s+-c\b|\bnode\s+-e\b'),
     "runs an inline code one-liner"),
    (MED, re.compile(r'(\\x[0-9a-fA-F]{2}){4,}'),
     "hex-encoded (possibly obfuscated) string"),
]

TEXT_EXT = {".sh", ".bash", ".zsh", ".fish", ".py", ".js", ".mjs", ".cjs",
            ".ts", ".json", ".md", ".txt", ".yml", ".yaml", ".toml", ""}
SKIP_DIRS = {".git", "node_modules", ".venv", "__pycache__", "dist", "build",
             "__tests__", "__test__"}
# Test files do not execute on install, and they routinely contain the very
# patterns this scanner hunts for (a test asserting the hook catches `curl`).
# Skip them here; the paired review step still reads anything a hook invokes.
SKIP_FILE = re.compile(r'\.(test|spec)\.[^.]+$')
LIFECYCLE = ("preinstall", "install", "postinstall", "prepare", "prepublish")


def is_text(path):
    return os.path.splitext(path)[1].lower() in TEXT_EXT


def scan_file(path, rel):
    out = []
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as fh:
            for i, line in enumerate(fh, 1):
                for sev, rx, why in RULES:
                    if rx.search(line):
                        out.append((sev, rel, i, why, line.strip()[:100]))
    except OSError:
        pass
    return out


def check_package_json(path, rel):
    out = []
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return out
    scripts = data.get("scripts", {}) if isinstance(data, dict) else {}
    for name in LIFECYCLE:
        if name in scripts:
            out.append((HIGH, rel, 0,
                        f"npm lifecycle script '{name}' runs code on install",
                        str(scripts[name])[:100]))
    return out


def main():
    if len(sys.argv) < 2:
        print("usage: scan_plugin.py <plugin-dir>", file=sys.stderr)
        return 2
    root = sys.argv[1]
    if not os.path.isdir(root):
        print(f"not a directory: {root}", file=sys.stderr)
        return 2

    findings = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for fn in filenames:
            if SKIP_FILE.search(fn):
                continue
            p = os.path.join(dirpath, fn)
            rel = os.path.relpath(p, root)
            if fn == "package.json":
                findings += check_package_json(p, rel)
            if is_text(p):
                findings += scan_file(p, rel)

    highs = [f for f in findings if f[0] == HIGH]
    meds = [f for f in findings if f[0] == MED]

    for sev, rel, ln, why, snippet in highs + meds:
        loc = f"{rel}:{ln}" if ln else rel
        print(f"{sev:4} {loc}: {why}")
        if snippet:
            print(f"       > {snippet}")

    print()
    print(f"scan of {root}: {len(highs)} HIGH, {len(meds)} MEDIUM")
    if highs:
        return 2
    if meds:
        return 1
    print("clean: no known-bad or suspicious patterns found.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
