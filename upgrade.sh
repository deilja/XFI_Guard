#!/usr/bin/env bash
set -Eeuo pipefail

# Безопасное обновление XFI Guard поверх существующей установки.
# Сохраняет секреты и пользовательскую конфигурацию до запуска install.sh.

INSTALL_DIR="${XFI_GUARD_DIR:-/opt/xfi-guard}"
STATE_DIR="/var/lib/xfi-guard"
CONFIG_DIR="/etc/xfi-guard"
BACKUP_DIR="${STATE_DIR}/upgrade-backups/$(date +%Y%m%d-%H%M%S)"
TTY=/dev/tty

log(){ printf '\n[XFI Guard] %s\n' "$*"; }
die(){ printf '\n[XFI Guard] ERROR: %s\n' "$*" >&2; exit 1; }

[[ $(id -u) -eq 0 ]] || die "Запустите: sudo bash upgrade.sh"
command -v bash >/dev/null || die "bash не найден"

install -d -m 0700 "$BACKUP_DIR"

# Перечень конфигурации, которую нельзя потерять при обновлении.
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

# Дополнительно сохраняем весь каталог конфигурации, если он существует.
if [[ -d "$CONFIG_DIR" ]]; then
  cp -a "$CONFIG_DIR" "$BACKUP_DIR/etc-xfi-guard"
  chmod -R go-rwx "$BACKUP_DIR/etc-xfi-guard" || true
fi

log "Резервная копия: $BACKUP_DIR"

# install.sh обновляет код и зависимости, но может пересоздать bot.env/ai.json.
# Поэтому после завершения возвращаем старые значения.
SCRIPT_DIR="$(cd -- "$(dirname -- "$0")" && pwd)"
"$SCRIPT_DIR/install.sh"

restore_file(){
  local src="$BACKUP_DIR/$1"
  local dst="/$1"
  if [[ -f "$src" ]]; then
    install -D -m 600 "$src" "$dst"
    log "Восстановлена конфигурация: $dst"
  fi
}

if [[ "$found" -eq 1 ]]; then
  restore_file "etc/xfi-guard/bot.env"
  restore_file "var/lib/xfi-guard/ai.json"
  restore_file "opt/xfi-guard/.env"
  restore_file "opt/xfi-guard/.env.local"
fi

chmod 600 "$CONFIG_DIR/bot.env" 2>/dev/null || true
chmod 600 "$STATE_DIR/ai.json" 2>/dev/null || true

log "Обновление завершено. Существующие .env и секреты сохранены."
log "Backup: $BACKUP_DIR"
