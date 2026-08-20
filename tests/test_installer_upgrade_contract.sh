#!/usr/bin/env bash
set -Eeuo pipefail
root="$(cd -- "$(dirname -- "$0")/.." && pwd)"
installer="$root/install.sh"
updater="$root/xfi_guard/updater.py"
[[ -f "$installer" && -f "$updater" ]]
# The installer must preserve secrets before reset and restore them afterwards.
grep -q 'preserve_file /etc/xfi-guard/bot.env' "$installer"
grep -q 'preserve_file /var/lib/xfi-guard/ai.json' "$installer"
grep -q 'restore_file /etc/xfi-guard/bot.env' "$installer"
grep -q 'restore_file /var/lib/xfi-guard/ai.json' "$installer"
# Update result notifications must exist for success and failure.
grep -q 'XFI_GUARD_BOT_TOKEN' "$updater"
grep -q 'XFI_GUARD_ADMIN_IDS' "$updater"
grep -q 'XFI Guard обновлён' "$updater"
grep -q 'Обновление XFI Guard не удалось' "$updater"
echo 'upgrade notification/config preservation contract: PASS'
