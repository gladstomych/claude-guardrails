#!/bin/sh
# Install the commit-style guide as the current repo's commit-msg hook.
#
# Same install strategy as commit-guard: honours core.hooksPath, never
# overwrites an existing commit-msg hook (moves it aside and runs it first via a
# dispatcher), idempotent. Because commit-style only warns, it is safe to chain
# alongside commit-guard's backstop.

set -eu

script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
guide="$script_dir/commit-msg-style"
marker="# commit-style-dispatcher"

if [ ! -f "$guide" ]; then
    echo "commit-style: cannot find guide hook at $guide" >&2
    exit 1
fi

if ! git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    echo "commit-style: not inside a git repository. cd into your repo and retry." >&2
    exit 1
fi

hooks_dir=$(git rev-parse --git-path hooks)
mkdir -p "$hooks_dir"
dest="$hooks_dir/commit-msg"
stored="$hooks_dir/commit-style-guide"

install_guide() {
    cp "$guide" "$stored"
    chmod +x "$stored"
}

if [ ! -e "$dest" ]; then
    cp "$guide" "$dest"
    chmod +x "$dest"
    echo "commit-style: installed commit-msg hook -> $dest"
    exit 0
fi

if grep -qF "$marker" "$dest" 2>/dev/null; then
    echo "commit-style: dispatcher already installed in $dest — refreshing guide."
    install_guide
    exit 0
fi
if cmp -s "$guide" "$dest"; then
    echo "commit-style: guide already installed in $dest — nothing to do."
    exit 0
fi

# A foreign commit-msg hook exists (possibly commit-guard's). Preserve and chain.
preserved="$hooks_dir/commit-msg.pre-commit-style"
if [ -e "$preserved" ]; then
    n=1
    while [ -e "$preserved.$n" ]; do n=$((n + 1)); done
    preserved="$preserved.$n"
fi
mv "$dest" "$preserved"
chmod +x "$preserved" 2>/dev/null || true
install_guide

cat > "$dest" <<EOF
#!/bin/sh
$marker
# Runs the repo's previous commit-msg hook, then the commit-style guide.
"$preserved" "\$@" || exit \$?
"$stored" "\$@" || exit \$?
EOF
chmod +x "$dest"

echo "commit-style: chained guide onto existing hook."
echo "  dispatcher: $dest"
echo "  previous hook preserved: $preserved"
echo "  guide: $stored"
