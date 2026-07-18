---
description: Security-review a Claude Code plugin before you install it
argument-hint: <owner/repo | git-url | local-path>
---

Vet the plugin at `$ARGUMENTS` for malicious or suspicious code BEFORE it is
installed. Do NOT install it as part of this command. There is no hook that can
intercept `/plugin install` itself, so this is the gate: run it first, install
only on a CLEAN or accepted-WARN verdict.

Work through these steps:

1. Get the code into a throwaway directory (nothing is activated by cloning):
   ```bash
   VET=$(mktemp -d)
   # Accepts "owner/repo", a full git URL, or a local path. Prefer HTTPS to avoid
   # SSH host-key prompts in a non-interactive clone.
   if [ -d "$ARGUMENTS" ]; then
     cp -r "$ARGUMENTS" "$VET/p"
   elif printf '%s' "$ARGUMENTS" | grep -q '://\|@'; then
     git clone --depth 1 "$ARGUMENTS" "$VET/p"
   else
     git clone --depth 1 "https://github.com/$ARGUMENTS" "$VET/p"
   fi
   ```

2. Run the deterministic scanner and show its full output:
   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/scan_plugin.py" "$VET/p"
   ```
   Exit 2 = HIGH (likely malicious), 1 = MEDIUM (suspicious), 0 = clean.

3. Then do your own security review. Read `hooks/hooks.json`,
   `.claude-plugin/plugin.json` (inline `hooks`, `mcpServers`, `monitors`),
   any `package.json` (lifecycle scripts), and every script the hooks or commands
   invoke. Plugin hooks run UNSANDBOXED at the user's trust level, so installing is
   effectively running this code. Look for what the regex cannot catch: obfuscation,
   staged or downloaded payloads, data exfiltration, credential or keychain access,
   persistence, destructive commands, and any hook that does more than its
   description claims.

4. Give a verdict, most severe first:
   - **BLOCK** if anything is malicious. Name the `file:line` and why. Do not print
     an install command.
   - **WARN** if suspicious but plausibly legitimate. List each concern and let the
     user decide.
   - **CLEAN** if nothing was found. Only then print the install commands, e.g.
     `/plugin marketplace add <owner/marketplace-repo>` and
     `/plugin install <name>@<marketplace>`.

5. Remove the temp dir (`rm -rf "$VET"`).
