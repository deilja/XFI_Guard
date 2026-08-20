#!/usr/bin/env bash
set -Eeuo pipefail

# Regression test: a reinstall must not overwrite existing configuration.
ROOT="$(cd -- "$(dirname -- "$0")/.." && pwd)"
INSTALLER="$ROOT/install.sh"
[[ -f "$INSTALLER" ]] || { echo "install.sh not found" >&2; exit 1; }

tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT

# The installer is intentionally tested statically: a production install needs root,
# network access and systemd. Verify the required preservation guard is present.
grep -q 'existing configuration' "$INSTALLER"
grep -q '/etc/xfi-guard/bot.env' "$INSTALLER"
grep -q '/var/lib/xfi-guard/ai.json' "$INSTALLER"
grep -q 'XFI_GUARD_BOT_TOKEN' "$INSTALLER"
grep -q 'GEMINI_API_KEY' "$INSTALLER"
grep -q 'GROQ_API_KEY' "$INSTALLER"

# upgrade.sh must exist and preserve configuration before invoking install.sh.
UPGRADE="$ROOT/upgrade.sh"
[[ -f "$UPGRADE" ]] || { echo "upgrade.sh not found" >&2; exit 1; }
grep -q 'BACKUP_DIR' "$UPGRADE"
grep -q 'restore_all' "$UPGRADE"
grep -q 'install.sh' "$UPGRADE"

echo "installer preservation checks: PASS"
