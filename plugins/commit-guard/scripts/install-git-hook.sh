#!/bin/sh
# Install the commit-guard backstop as the current repo's commit-msg hook.
#
# Run from inside a git repo. Honours core.hooksPath. If a commit-msg hook is
# already present, it is NOT overwritten: the existing hook is moved aside and a
# small dispatcher runs it first, then the backstop, so both take effect even if
# the existing hook ends in `exit 0`. Idempotent: re-running is a no-op.

set -eu

script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
backstop="$script_dir/commit-msg"
marker="# commit-guard-dispatcher"

if [ ! -f "$backstop" ]; then
    echo "commit-guard: cannot find backstop hook at $backstop" >&2
    exit 1
fi

if ! git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    echo "commit-guard: not inside a git repository. cd into your repo and retry." >&2
    exit 1
fi

hooks_dir=$(git rev-parse --git-path hooks)
mkdir -p "$hooks_dir"
dest="$hooks_dir/commit-msg"
stored="$hooks_dir/commit-guard-backstop"

install_backstop() {
    cp "$backstop" "$stored"
    chmod +x "$stored"
}

# No existing hook: install the backstop directly as commit-msg.
if [ ! -e "$dest" ]; then
    cp "$backstop" "$dest"
    chmod +x "$dest"
    echo "commit-guard: installed commit-msg hook -> $dest"
    exit 0
fi

# Already our dispatcher, or already an identical backstop: nothing to do.
if grep -qF "$marker" "$dest" 2>/dev/null; then
    echo "commit-guard: dispatcher already installed in $dest — refreshing backstop."
    install_backstop
    exit 0
fi
if cmp -s "$backstop" "$dest"; then
    echo "commit-guard: backstop already installed in $dest — nothing to do."
    exit 0
fi

# A foreign commit-msg hook exists. Preserve it and chain via a dispatcher.
preserved="$hooks_dir/commit-msg.pre-commit-guard"
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
# Runs the repo's previous commit-msg hook, then the commit-guard backstop.
"$preserved" "\$@" || exit \$?
"$stored" "\$@" || exit \$?
EOF
chmod +x "$dest"

echo "commit-guard: chained backstop onto existing hook."
echo "  dispatcher: $dest"
echo "  previous hook preserved: $preserved"
echo "  backstop: $stored"
