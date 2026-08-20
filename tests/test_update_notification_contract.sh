#!/usr/bin/env bash
set -Eeuo pipefail
ROOT="$(cd -- "$(dirname -- "$0")/.." && pwd)"
UPDATER="$ROOT/xfi_guard/updater.py"
SERVICE="$ROOT/systemd/xfi-guard-update.service"
BOT="$ROOT/xfi_guard/bot.py"

[[ -f "$UPDATER" && -f "$SERVICE" && -f "$BOT" ]]
# The production update service must run the updater as root and load the same
# Telegram configuration used by the bot.
grep -q 'EnvironmentFile=-/etc/xfi-guard/bot.env' "$SERVICE"
grep -q 'python -m xfi_guard.updater apply' "$SERVICE"
# The updater must load bot.env and send notifications to every configured admin.
grep -q 'ENV_FILE = Path("/etc/xfi-guard/bot.env")' "$UPDATER"
grep -q 'XFI_GUARD_BOT_TOKEN' "$UPDATER"
grep -q 'XFI_GUARD_ADMIN_IDS' "$UPDATER"
grep -q 'sendMessage' "$UPDATER"
grep -q 'update_button' "$BOT"
grep -q 'xfi-guard-update.service' "$BOT"

echo "update notification contract: PASS"
