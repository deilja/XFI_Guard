#!/usr/bin/env bash
set -Eeuo pipefail

REPO_RAW="https://raw.githubusercontent.com/deilja/XFI_Guard/main/support_bot"
INSTALL_DIR="/opt/xfi-support-bot"
SERVICE_NAME="xfi-support-bot"
ENV_FILE="$INSTALL_DIR/.env"
TTY=/dev/tty

log() { printf '\n[XFI Support] %s\n' "$*"; }
die() { printf '\n[XFI Support] ERROR: %s\n' "$*" >&2; exit 1; }
ask() {
    local __var="$1"
    local __value=""
    shift
    if [[ -r "$TTY" ]]; then
        IFS= read -r -p "$*" __value < "$TTY" || true
    else
        IFS= read -r -p "$*" __value || true
    fi
    printf -v "$__var" '%s' "$__value"
}

[[ "$(id -u)" -eq 0 ]] || die "Запустите установку от root или через sudo."
command -v apt-get >/dev/null 2>&1 || die "Поддерживаются Ubuntu/Debian."
command -v curl >/dev/null 2>&1 || { apt-get update -y; apt-get install -y curl; }

ask BOT_TOKEN "Введите Telegram BOT TOKEN: "
[[ -n "$BOT_TOKEN" ]] || die "BOT TOKEN не указан."

ask ADMIN_ID "Введите Telegram ADMIN ID: "
[[ "$ADMIN_ID" =~ ^[0-9]+$ ]] || die "ADMIN ID должен содержать только цифры."

log "Установка системных пакетов..."
export DEBIAN_FRONTEND=noninteractive
apt-get update -y
apt-get install -y ca-certificates curl python3 python3-venv python3-pip

log "Создание каталога $INSTALL_DIR..."
install -d -m 700 "$INSTALL_DIR"

log "Загрузка файлов XFI Support Bot..."
curl -fsSL "$REPO_RAW/main.py" -o "$INSTALL_DIR/main.py"
curl -fsSL "https://raw.githubusercontent.com/deilja/XFI_Guard/main/requirements-bot.txt" -o "$INSTALL_DIR/requirements.txt"

log "Создание Python virtualenv..."
python3 -m venv "$INSTALL_DIR/.venv"
"$INSTALL_DIR/.venv/bin/pip" install --upgrade pip
"$INSTALL_DIR/.venv/bin/pip" install -r "$INSTALL_DIR/requirements.txt"

log "Создание конфигурации..."
cat > "$ENV_FILE" <<EOF
BOT_TOKEN=$BOT_TOKEN
ADMIN_ID=$ADMIN_ID
GROQ_KEY_FILE=$INSTALL_DIR/.groq_api_key
EOF
chmod 600 "$ENV_FILE"

cat > "$INSTALL_DIR/.groq_api_key" <<EOF

EOF
chmod 600 "$INSTALL_DIR/.groq_api_key"

log "Создание systemd-сервиса..."
cat > "/etc/systemd/system/$SERVICE_NAME.service" <<EOF
[Unit]
Description=XFI Support Telegram Bot
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=root
WorkingDirectory=$INSTALL_DIR
EnvironmentFile=$ENV_FILE
Environment=PYTHONUNBUFFERED=1
ExecStart=$INSTALL_DIR/.venv/bin/python $INSTALL_DIR/main.py
Restart=always
RestartSec=5
TimeoutStopSec=30

[Install]
WantedBy=multi-user.target
EOF

chmod 600 "$INSTALL_DIR/.groq_api_key"
systemctl daemon-reload
systemctl enable --now "$SERVICE_NAME"

sleep 2

if systemctl is-active --quiet "$SERVICE_NAME"; then
    log "Установка завершена."
    echo
    echo "Telegram bot: запущен"
    echo "Admin ID: $ADMIN_ID"
    echo "Groq API Key: добавляется через /admin"
    echo
    echo "Команды:"
    echo "  systemctl status $SERVICE_NAME --no-pager"
    echo "  journalctl -u $SERVICE_NAME -n 100 --no-pager"
    echo
    echo "Откройте бота в Telegram и отправьте: /admin"
else
    echo
    echo "Сервис не запустился. Последние логи:"
    journalctl -u "$SERVICE_NAME" -n 50 --no-pager || true
    exit 1
fi
