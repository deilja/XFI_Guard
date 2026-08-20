#!/usr/bin/env bash
set -Eeuo pipefail

# Безопасное обновление XFI Guard поверх существующей установки.
# Сохраняет .env, Telegram secrets и AI configuration до запуска install.sh.

INSTALL_DIR="${XFI_GUARD_DIR:-/opt/xfi-guard}"
STATE_DIR="/var/lib/xfi-guard"
CONFIG_DIR="/etc/xfi-guard"
BACKUP_DIR="${STATE_DIR}/upgrade-backups/$(date +%Y%m%d-%H%M%S)"

log(){ printf '\n[XFI Guard] %s\n' "$*"; }
die(){ printf '\n[XFI Guard] ERROR: %s\n' "$*" >&2; exit 1; }

[[ $(id -u) -eq 0 ]] || die "Запустите: sudo bash upgrade.sh"
command -v bash >/dev/null || die "bash не найден"

install -d -m 0700 "$BACKUP_DIR"

FILES=(
  "$CONFIG_DIR/bot.env"
  "$STATE_DIR/ai.json"
  "$INSTALL_DIR/.env"
  "$INSTALL_DIR/.env.local"
)

found=0
for file in "${FILES[@]}"; do
  if [[ -f "$file" ]]; then
    found=1
    rel="${file#/}"
    install -d -m 0700 "$BACKUP_DIR/$(dirname "$rel")"
    cp -a "$file" "$BACKUP_DIR/$rel"
    chmod 600 "$BACKUP_DIR/$rel"
    log "Сохранена конфигурация: $file"
  fi
done

# Проверяем наличие ключевых переменных без вывода их значений.
check_env(){
  local file="$1"
  [[ -f "$file" ]] || return 0
  log "Проверка конфигурации $file"
  local key
  for key in XFI_GUARD_BOT_TOKEN XFI_GUARD_ADMIN_IDS XFI_GUARD_WEBHOOK_DOMAIN GEMINI_API_KEY GROQ_API_KEY OPENROUTER_API_KEY; do
    if grep -Eq "^[[:space:]]*${key}[[:space:]]*=[[:space:]]*.+" "$file"; then
      printf '  %-28s SET\n' "$key"
    else
      printf '  %-28s NOT SET\n' "$key"
    fi
  done
}
check_env "$CONFIG_DIR/bot.env"
check_env "$INSTALL_DIR/.env"
check_env "$INSTALL_DIR/.env.local"

# Полная резервная копия /etc/xfi-guard для возможности восстановления.
if [[ -d "$CONFIG_DIR" ]]; then
  cp -a "$CONFIG_DIR" "$BACKUP_DIR/etc-xfi-guard"
  chmod -R go-rwx "$BACKUP_DIR/etc-xfi-guard" || true
fi

log "Резервная копия: $BACKUP_DIR"

restore_file(){
  local src="$BACKUP_DIR/$1"
  local dst="/$1"
  if [[ -f "$src" ]]; then
    install -D -m 600 "$src" "$dst"
    log "Восстановлена конфигурация: $dst"
  fi
}

restore_all(){
  restore_file "etc/xfi-guard/bot.env"
  restore_file "var/lib/xfi-guard/ai.json"
  restore_file "opt/xfi-guard/.env"
  restore_file "opt/xfi-guard/.env.local"
  chmod 600 "$CONFIG_DIR/bot.env" 2>/dev/null || true
  chmod 600 "$STATE_DIR/ai.json" 2>/dev/null || true
}

# Даже при ошибке установки старые данные возвращаются.
trap 'status=$?; restore_all; if [[ $status -ne 0 ]]; then log "Обновление завершилось с ошибкой ($status), конфигурация восстановлена"; fi; exit $status' EXIT

SCRIPT_DIR="$(cd -- "$(dirname -- "$0")" && pwd)"
"$SCRIPT_DIR/install.sh"

log "Обновление завершено. Существующие .env и секреты сохранены."
log "Backup: $BACKUP_DIR"
