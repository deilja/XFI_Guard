#!/usr/bin/env bash
set -Eeuo pipefail

REPO="${XFI_GUARD_REPO:-https://github.com/deilja/XFI_Guard.git}"
INSTALL_DIR="${XFI_GUARD_DIR:-/opt/xfi-guard}"
PYTHON_BIN="${PYTHON_BIN:-python3}"

log(){ printf '\n[XFI Guard] %s\n' "$*"; }
die(){ printf '\n[XFI Guard] ERROR: %s\n' "$*" >&2; exit 1; }

[[ "$(id -u)" -eq 0 ]] || die "Запустите установку от root: sudo bash install.sh"
command -v apt-get >/dev/null 2>&1 || die "Поддерживаются Ubuntu/Debian"

export DEBIAN_FRONTEND=noninteractive
log "Установка системных зависимостей"
apt-get update
apt-get install -y git ca-certificates python3 python3-venv python3-pip

if [[ -d "$INSTALL_DIR/.git" ]]; then
  log "Обновление существующей установки"
  git -C "$INSTALL_DIR" fetch --all --prune
  git -C "$INSTALL_DIR" reset --hard origin/main
else
  log "Загрузка XFI Guard"
  rm -rf "$INSTALL_DIR"
  git clone --depth 1 "$REPO" "$INSTALL_DIR"
fi

cd "$INSTALL_DIR"
log "Создание Python окружения"
"$PYTHON_BIN" -m venv "$INSTALL_DIR/.venv"
"$INSTALL_DIR/.venv/bin/python" -m pip install --upgrade pip
if [[ -f requirements.txt ]]; then
  "$INSTALL_DIR/.venv/bin/pip" install -r requirements.txt
fi

log "Подготовка каталогов"
install -d -m 0755 /var/log/xfi-guard
install -d -m 0700 /var/lib/xfi-guard
install -d -m 0700 /etc/xfi-guard

if [[ -f systemd/xfi-guard.service ]]; then
  install -m 0644 systemd/xfi-guard.service /etc/systemd/system/xfi-guard.service
else
  cat >/etc/systemd/system/xfi-guard.service <<EOF
[Unit]
Description=XFI Guard VPS Security Monitor
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=root
WorkingDirectory=$INSTALL_DIR
ExecStart=$INSTALL_DIR/.venv/bin/python -m xfi_guard.daemon --config $INSTALL_DIR/config.toml
Restart=on-failure
RestartSec=5
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=full
ProtectHome=true
ReadWritePaths=/var/log/xfi-guard /var/lib/xfi-guard

[Install]
WantedBy=multi-user.target
EOF
fi

systemctl daemon-reload
systemctl enable --now xfi-guard
sleep 2

if ! systemctl is-active --quiet xfi-guard; then
  journalctl -u xfi-guard -n 80 --no-pager || true
  die "XFI Guard не запустился"
fi

if [[ -f systemd/xfi-guard-bot.service ]]; then
  install -m 0644 systemd/xfi-guard-bot.service /etc/systemd/system/xfi-guard-bot.service
  log "Telegram Bot service установлен, но не запускается без /etc/xfi-guard/bot.env"
fi

log "Установка завершена"
printf '\nУстановка: %s\nСервис:    systemctl status xfi-guard\nЛоги:      journalctl -u xfi-guard -f\nJSONL:     /var/log/xfi-guard/monitor.jsonl\nКаталог:   %s\n' "$INSTALL_DIR" "$INSTALL_DIR"
