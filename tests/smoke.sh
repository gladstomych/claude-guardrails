#!/bin/sh
# Smoke tests for claude-guardrails. Exercises both plugins' hooks the way
# Claude Code drives them: JSON on stdin, assert on exit code and output.
# Exits nonzero if any check fails.

set -u

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
EMD="$ROOT/plugins/emdash-guard/scripts"
CMG="$ROOT/plugins/commit-guard/scripts"
CHECKER="$EMD/check_em_dashes.py"

WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT

# UTF-8 dash bytes so the source file itself stays ASCII-clean.
EMDASH=$(printf '\342\200\224')       # U+2014 em dash
ENDASH=$(printf '\342\200\223')       # U+2013 en dash
HBAR=$(printf '\342\200\225')         # U+2015 horizontal bar

pass=0
fail=0
ok()   { pass=$((pass + 1)); printf '  ok   %s\n' "$1"; }
bad()  { fail=$((fail + 1)); printf '  FAIL %s\n' "$1"; }

# assert_exit <name> <expected-code> <actual-code>
assert_exit() {
    if [ "$2" = "$3" ]; then ok "$1"; else bad "$1 (want exit $2, got $3)"; fi
}
# assert_contains <name> <needle> <file>
assert_contains() {
    if grep -qF "$2" "$3"; then ok "$1"; else bad "$1 (missing '$2')"; fi
}
# assert_absent <name> <needle> <file>
assert_absent() {
    if grep -qF "$2" "$3"; then bad "$1 (found '$2')"; else ok "$1"; fi
}

# Feed a JSON payload to a hook, capture exit + stderr.
# run_hook <script> <json>   -> sets RC and STDERR_FILE
run_hook() {
    STDERR_FILE="$WORK/stderr"
    printf '%s' "$2" | python3 "$1" >"$WORK/stdout" 2>"$STDERR_FILE"
    RC=$?
}

json_write() { # <file_path>
    printf '{"tool_name":"Write","tool_input":{"file_path":"%s"}}' "$1"
}

echo "== check_em_dashes.py (vendored checker) =="
printf 'clean line, no dashes here.\n' > "$WORK/clean.md"
python3 "$CHECKER" "$WORK/clean.md" >/dev/null 2>&1; assert_exit "checker: clean -> 0" 0 $?
printf 'a pause %s then more.\n' "$EMDASH" > "$WORK/dirty.md"
python3 "$CHECKER" "$WORK/dirty.md" >/dev/null 2>&1; assert_exit "checker: em dash -> 1" 1 $?
printf 'range 2019-2024 and well-known compound.\n' > "$WORK/hyphen.md"
python3 "$CHECKER" "$WORK/hyphen.md" >/dev/null 2>&1; assert_exit "checker: legit hyphens -> 0" 0 $?

echo "== emdash-guard PostToolUse (post_write_emdash.py) =="

f="$WORK/note.md"; printf 'she paused %s then left.\n' "$EMDASH" > "$f"
run_hook "$EMD/post_write_emdash.py" "$(json_write "$f")"
assert_exit "md with em dash -> block (2)" 2 "$RC"
assert_contains "block message names the file" "$f" "$STDERR_FILE"

f="$WORK/enbar.md"; printf 'x %s y and a %s b\n' "$ENDASH" "$HBAR" > "$f"
run_hook "$EMD/post_write_emdash.py" "$(json_write "$f")"
assert_exit "md with en dash / horizontal bar -> block (2)" 2 "$RC"

f="$WORK/good.md"; printf 'clean prose, honest punctuation.\n' > "$f"
run_hook "$EMD/post_write_emdash.py" "$(json_write "$f")"
assert_exit "clean md -> pass (0)" 0 "$RC"

f="$WORK/code.py"; printf 'x = 1  # a note %s really\n' "$EMDASH" > "$f"
run_hook "$EMD/post_write_emdash.py" "$(json_write "$f")"
assert_exit ".py skipped by default extension filter -> 0" 0 "$RC"

f="$WORK/code2.py"; printf 'x = 1  # a note %s really\n' "$EMDASH" > "$f"
STDERR_FILE="$WORK/stderr"
printf '%s' "$(json_write "$f")" | EMDASH_GUARD_EXTENSIONS='*' python3 "$EMD/post_write_emdash.py" >/dev/null 2>"$STDERR_FILE"
assert_exit "EMDASH_GUARD_EXTENSIONS=* checks .py -> block (2)" 2 $?

run_hook "$EMD/post_write_emdash.py" '{"tool_name":"Write","tool_input":{"file_path":"/no/such/file.md"}}'
assert_exit "missing file -> pass (0)" 0 "$RC"

f="$WORK/edit.md"; printf 'edited %s badly\n' "$EMDASH" > "$f"
run_hook "$EMD/post_write_emdash.py" "$(printf '{"tool_name":"Edit","tool_input":{"file_path":"%s"}}' "$f")"
assert_exit "Edit tool payload -> block (2)" 2 "$RC"

f="$WORK/nb.ipynb"; printf 'cell text %s here\n' "$EMDASH" > "$f"
run_hook "$EMD/post_write_emdash.py" "$(printf '{"tool_name":"NotebookEdit","tool_input":{"notebook_path":"%s"}}' "$f")"
assert_exit "NotebookEdit notebook_path (.ipynb not in default exts) -> 0" 0 "$RC"

run_hook "$EMD/post_write_emdash.py" 'not json at all'
assert_exit "malformed JSON -> pass (0)" 0 "$RC"

echo "== commit-guard PreToolUse (block_coauthor.py) =="

json_bash() { printf '{"tool_name":"Bash","tool_input":{"command":%s}}' "$1"; }
# jq-free JSON string encoder for a command containing newlines/quotes.
jstr() { python3 -c 'import json,sys; print(json.dumps(sys.stdin.read()))'; }

cmd=$(printf 'git commit -m "feat: x\n\nCo-Authored-By: Claude <noreply@anthropic.com>"' | jstr)
run_hook "$CMG/block_coauthor.py" "$(json_bash "$cmd")"
assert_exit "git commit + Claude trailer -> block (2)" 2 "$RC"
assert_contains "block message explains" "commit-guard" "$STDERR_FILE"

cmd=$(printf 'git commit -m "feat: x\n\nClaude-Session: https://claude.ai/x"' | jstr)
run_hook "$CMG/block_coauthor.py" "$(json_bash "$cmd")"
assert_exit "git commit + Claude-Session trailer -> block (2)" 2 "$RC"

cmd=$(printf 'git commit -m "feat: x"' | jstr)
run_hook "$CMG/block_coauthor.py" "$(json_bash "$cmd")"
assert_exit "clean git commit -> pass (0)" 0 "$RC"

cmd=$(printf 'git commit -m "feat: x\n\nCo-Authored-By: Dana Dev <dana@example.com>"' | jstr)
run_hook "$CMG/block_coauthor.py" "$(json_bash "$cmd")"
assert_exit "human co-author -> pass (0)" 0 "$RC"

cmd=$(printf 'echo Co-Authored-By: Claude' | jstr)
run_hook "$CMG/block_coauthor.py" "$(json_bash "$cmd")"
assert_exit "non-commit command mentioning trailer -> pass (0)" 0 "$RC"

run_hook "$CMG/block_coauthor.py" '{"tool_name":"Read","tool_input":{"file_path":"x"}}'
assert_exit "non-Bash tool -> pass (0)" 0 "$RC"

run_hook "$CMG/block_coauthor.py" 'garbage'
assert_exit "malformed JSON -> pass (0)" 0 "$RC"

echo "== commit-guard git backstop (commit-msg + install-git-hook.sh) =="

git_env() { GIT_AUTHOR_NAME=T GIT_AUTHOR_EMAIL=t@e GIT_COMMITTER_NAME=T GIT_COMMITTER_EMAIL=t@e "$@"; }

# Direct commit-msg invocation: strips Claude trailer, keeps human + subject.
msg="$WORK/msg1"; printf 'feat: y\n\nBody.\nCo-Authored-By: Claude <noreply@anthropic.com>\nCo-Authored-By: Dana <dana@e>\n' > "$msg"
sh "$CMG/commit-msg" "$msg" 2>/dev/null
assert_absent  "backstop strips Claude co-author" "Co-Authored-By: Claude" "$msg"
assert_contains "backstop keeps human co-author" "Co-Authored-By: Dana" "$msg"
assert_contains "backstop keeps subject" "feat: y" "$msg"

# Fresh repo: install, then a real commit with the trailer comes out clean.
R1="$WORK/repo1"; mkdir -p "$R1"; ( cd "$R1" && git init -q )
( cd "$R1" && sh "$CMG/install-git-hook.sh" >/dev/null )
[ -x "$R1/.git/hooks/commit-msg" ] && ok "install: commit-msg hook created & executable" || bad "install: hook missing/not executable"
( cd "$R1" && : > a && git add a && \
  git_env git commit -q -m "$(printf 'feat: z\n\nCo-Authored-By: Claude <noreply@anthropic.com>')" )
( cd "$R1" && git log -1 --pretty=%B > "$WORK/log1" )
assert_absent "real commit: Claude trailer stripped" "Co-Authored-By: Claude" "$WORK/log1"
assert_contains "real commit: subject survived" "feat: z" "$WORK/log1"

# Idempotent: second install is a no-op and the hook still works.
( cd "$R1" && sh "$CMG/install-git-hook.sh" >/dev/null 2>&1 ) && ok "install: idempotent re-run ok" || bad "install: re-run failed"

# Chaining: a pre-existing commit-msg hook keeps running after install.
R2="$WORK/repo2"; mkdir -p "$R2"; ( cd "$R2" && git init -q )
cat > "$R2/.git/hooks/commit-msg" <<EOF
#!/bin/sh
touch "$R2/existing-ran"
exit 0
EOF
chmod +x "$R2/.git/hooks/commit-msg"
( cd "$R2" && sh "$CMG/install-git-hook.sh" >/dev/null )
[ -f "$R2/.git/hooks/commit-msg.pre-commit-guard" ] && ok "chain: previous hook preserved" || bad "chain: previous hook not preserved"
( cd "$R2" && : > b && git add b && \
  git_env git commit -q -m "$(printf 'fix: w\n\nCo-Authored-By: Claude <noreply@anthropic.com>')" )
[ -f "$R2/existing-ran" ] && ok "chain: existing hook still ran (despite its exit 0)" || bad "chain: existing hook did not run"
( cd "$R2" && git log -1 --pretty=%B > "$WORK/log2" )
assert_absent "chain: backstop still stripped trailer" "Co-Authored-By: Claude" "$WORK/log2"

echo
echo "-------------------------------------"
printf 'passed: %s   failed: %s\n' "$pass" "$fail"
[ "$fail" -eq 0 ] || exit 1
