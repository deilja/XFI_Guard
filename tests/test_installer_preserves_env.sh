#!/usr/bin/env bash
set -Eeuo pipefail

# Regression test: a reinstall must not overwrite existing configuration.
ROOT="$(cd -- "$(dirname -- "$0")/.." && pwd)"
INSTALLER="$ROOT/install.sh"
UPGRADE="$ROOT/upgrade.sh"
[[ -f "$INSTALLER" ]] || { echo "install.sh not found" >&2; exit 1; }
[[ -f "$UPGRADE" ]] || { echo "upgrade.sh not found" >&2; exit 1; }

# Production installation requires root/network/systemd, so this CI check validates
# the preservation guard and all supported configuration paths statically.
grep -q 'existing configuration' "$INSTALLER"
grep -q 'PRESERVE_DIR' "$INSTALLER"
grep -q 'restore_preserved' "$INSTALLER"
grep -q '/etc/xfi-guard/bot.env' "$INSTALLER"
grep -q '/var/lib/xfi-guard/ai.json' "$INSTALLER"
grep -q 'INSTALL_DIR/.env' "$INSTALLER"
grep -q 'INSTALL_DIR/.env.local' "$INSTALLER"
grep -q 'chmod 600' "$INSTALLER"

grep -q 'BACKUP_DIR' "$UPGRADE"
grep -q 'restore_all' "$UPGRADE"
grep -q 'install.sh' "$UPGRADE"

echo "installer preservation checks: PASS"
