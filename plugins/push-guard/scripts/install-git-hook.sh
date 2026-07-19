#!/bin/sh
# Install the push-guard backstop as the current repo's pre-push hook.
#
# Run from inside a git repo. Honours core.hooksPath. If a pre-push hook is
# already present, it is NOT overwritten: the existing hook is moved aside and a
# small dispatcher runs it first, then the backstop, so both take effect. The
# dispatcher passes stdin (git's ref lines) to both. Idempotent.

set -eu

script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
backstop="$script_dir/pre-push"
scanner="$script_dir/scan_push.py"
marker="# push-guard-dispatcher"

if [ ! -f "$backstop" ] || [ ! -f "$scanner" ]; then
    echo "push-guard: cannot find hook or scanner in $script_dir" >&2
    exit 1
fi

if ! git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    echo "push-guard: not inside a git repository. cd into your repo and retry." >&2
    exit 1
fi

hooks_dir=$(git rev-parse --git-path hooks)
mkdir -p "$hooks_dir"
dest="$hooks_dir/pre-push"
stored="$hooks_dir/push-guard-backstop"

# The scanner is copied next to the hook so the installed hook keeps working
# when the plugin is updated, moved, or uninstalled.
install_backstop() {
    cp "$backstop" "$stored"
    chmod +x "$stored"
    cp "$scanner" "$hooks_dir/push-guard-scan.py"
}

if [ ! -e "$dest" ]; then
    install_backstop
    cp "$backstop" "$dest"
    chmod +x "$dest"
    echo "push-guard: installed pre-push hook -> $dest"
    exit 0
fi

if grep -qF "$marker" "$dest" 2>/dev/null; then
    echo "push-guard: dispatcher already installed in $dest. Refreshing backstop."
    install_backstop
    exit 0
fi
if cmp -s "$backstop" "$dest"; then
    echo "push-guard: backstop already installed in $dest. Refreshing scanner."
    install_backstop
    exit 0
fi

# A foreign pre-push hook exists. Preserve it and chain via a dispatcher.
preserved="$hooks_dir/pre-push.pre-push-guard"
if [ -e "$preserved" ]; then
    n=1
    while [ -e "$preserved.$n" ]; do n=$((n + 1)); done
    preserved="$preserved.$n"
fi
mv "$dest" "$preserved"
chmod +x "$preserved" 2>/dev/null || true
install_backstop

cat > "$dest" <<EOF
#!/bin/sh
$marker
# Runs the repo's previous pre-push hook, then the push-guard backstop.
# git sends the ref lines on stdin, and each hook needs them, so buffer once.
refs=\$(cat)
printf '%s\n' "\$refs" | "$preserved" "\$@" || exit \$?
printf '%s\n' "\$refs" | "$stored" "\$@" || exit \$?
EOF
chmod +x "$dest"

echo "push-guard: chained backstop onto existing hook."
echo "  dispatcher: $dest"
echo "  previous hook preserved: $preserved"
echo "  backstop: $stored"
