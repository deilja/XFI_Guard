#!/usr/bin/env bash
set -Eeuo pipefail

INSTALL_DIR="${XFI_GUARD_DIR:-/opt/xfi-guard}"
SYSTEMD_FILE="$INSTALL_DIR/systemd/xfi-guard-monitor.service"
TARGET="/etc/systemd/system/xfi-guard-monitor.service"

[[ "$(id -u)" -eq 0 ]] || { echo "Запустите от root: sudo bash scripts/enable_security_monitor.sh" >&2; exit 1; }
[[ -f "$SYSTEMD_FILE" ]] || { echo "Не найден $SYSTEMD_FILE" >&2; exit 1; }
[[ -f "$INSTALL_DIR/xfi_guard/security_monitor.py" ]] || { echo "Не найден security_monitor.py" >&2; exit 1; }

install -m 0644 "$SYSTEMD_FILE" "$TARGET"
install -d -m 0700 /var/lib/xfi-guard
systemctl daemon-reload
systemctl enable --now xfi-guard-monitor.service
sleep 2
systemctl is-active --quiet xfi-guard-monitor.service || {
  journalctl -u xfi-guard-monitor.service -n 80 --no-pager || true
  exit 1
}

echo "XFI Guard Security Monitor: active"
echo "Проверка: journalctl -u xfi-guard-monitor.service -n 80 --no-pager"
