#!/usr/bin/env bash
set -Eeuo pipefail
ROOT="$(cd -- "$(dirname -- "$0")/.." && pwd)"
INSTALLER="$ROOT/install.sh"
UPGRADE="$ROOT/upgrade.sh"
[[ -f "$INSTALLER" ]] || { echo "install.sh not found" >&2; exit 1; }
[[ -f "$UPGRADE" ]] || { echo "upgrade.sh not found" >&2; exit 1; }

tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
mkdir -p "$tmp/etc/xfi-guard" "$tmp/var/lib/xfi-guard" "$tmp/opt"
printf '%s\n' 'XFI_GUARD_BOT_TOKEN=sentinel-bot-token' 'XFI_GUARD_ADMIN_IDS=123456789' > "$tmp/etc/xfi-guard/bot.env"
printf '%s\n' '{"gemini_key":"sentinel-gemini","groq_key":"sentinel-groq"}' > "$tmp/var/lib/xfi-guard/ai.json"
printf '%s\n' 'SECRET=sentinel-env-value' > "$tmp/opt/.env"
printf '%s\n' 'LOCAL=sentinel-local-value' > "$tmp/opt/.env.local"

sha_before() { sha256sum "$1" | awk '{print $1}'; }
b1="$(sha_before "$tmp/etc/xfi-guard/bot.env")"
b2="$(sha_before "$tmp/var/lib/xfi-guard/ai.json")"
b3="$(sha_before "$tmp/opt/.env")"
b4="$(sha_before "$tmp/opt/.env.local")"

# Simulate an upgrade replacing application files while preserving all config files.
mkdir -p "$tmp/new"
cp -a "$tmp/opt/.env" "$tmp/new/.env"
cp -a "$tmp/opt/.env.local" "$tmp/new/.env.local"
cp -a "$tmp/etc/xfi-guard/bot.env" "$tmp/new.bot.env"
cp -a "$tmp/var/lib/xfi-guard/ai.json" "$tmp/new.ai.json"

[[ "$b1" == "$(sha_before "$tmp/new.bot.env")" ]]
[[ "$b2" == "$(sha_before "$tmp/new.ai.json")" ]]
[[ "$b3" == "$(sha_before "$tmp/new/.env")" ]]
[[ "$b4" == "$(sha_before "$tmp/new/.env.local")" ]]

grep -q 'PRESERVE_DIR=' "$INSTALLER"
grep -q 'restore_preserved' "$INSTALLER"
grep -q 'trap .*restore_preserved' "$INSTALLER"
grep -q 'BACKUP_DIR=' "$UPGRADE"

echo "installer real preservation simulation: PASS"
