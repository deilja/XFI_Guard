#!/usr/bin/env bash
set -Eeuo pipefail

REPO_RAW="https://raw.githubusercontent.com/deilja/XFI_Guard/main/support_bot"
INSTALL_DIR="/opt/xfi-support-bot"
SERVICE_NAME="xfi-support-bot"
ENV_FILE="$INSTALL_DIR/.env"
GROQ_KEY_FILE="$INSTALL_DIR/.groq_api_key"
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

# ============================================================
# СОХРАНЕНИЕ СУЩЕСТВУЮЩИХ ДАННЫХ
# ============================================================

EXISTING_BOT_TOKEN=""
EXISTING_ADMIN_ID=""

if [[ -f "$ENV_FILE" ]]; then
    EXISTING_BOT_TOKEN="$(grep -E '^BOT_TOKEN=' "$ENV_FILE" | head -n1 | cut -d= -f2- || true)"
    EXISTING_ADMIN_ID="$(grep -E '^ADMIN_ID=' "$ENV_FILE" | head -n1 | cut -d= -f2- || true)"
fi

if [[ -n "$EXISTING_BOT_TOKEN" ]]; then
    BOT_TOKEN="$EXISTING_BOT_TOKEN"
    log "Существующий BOT TOKEN найден — сохраняем, повторный ввод не требуется."
else
    ask BOT_TOKEN "Введите Telegram BOT TOKEN: "
    [[ -n "$BOT_TOKEN" ]] || die "BOT TOKEN не указан."
fi

if [[ -n "$EXISTING_ADMIN_ID" && "$EXISTING_ADMIN_ID" =~ ^[0-9]+$ ]]; then
    ADMIN_ID="$EXISTING_ADMIN_ID"
    log "Существующий ADMIN ID найден — сохраняем."
else
    ask ADMIN_ID "Введите Telegram ADMIN ID: "
    [[ "$ADMIN_ID" =~ ^[0-9]+$ ]] || die "ADMIN ID должен содержать только цифры."
fi

# ============================================================
# ПАКЕТЫ
# ============================================================

log "Установка системных пакетов..."
export DEBIAN_FRONTEND=noninteractive
apt-get update -y
apt-get install -y ca-certificates curl python3 python3-venv python3-pip

# ============================================================
# КАТАЛОГ
# ============================================================

log "Подготовка каталога $INSTALL_DIR..."
install -d -m 700 "$INSTALL_DIR"

# Останавливаем только текущий сервис этого бота.
# XFI Guard и другие сервисы не затрагиваются.
if systemctl list-unit-files | grep -q "^${SERVICE_NAME}\.service"; then
    systemctl stop "$SERVICE_NAME" || true
fi

# ============================================================
# ОБНОВЛЕНИЕ ФАЙЛОВ
# ============================================================

log "Загрузка обновленного XFI Support Bot..."
curl -fsSL "$REPO_RAW/main.py" -o "$INSTALL_DIR/main.py"
curl -fsSL "https://raw.githubusercontent.com/deilja/XFI_Guard/main/requirements-bot.txt" -o "$INSTALL_DIR/requirements.txt"

# ============================================================
# PYTHON ENVIRONMENT
# ============================================================

log "Обновление Python virtualenv..."
if [[ ! -x "$INSTALL_DIR/.venv/bin/python" ]]; then
    python3 -m venv "$INSTALL_DIR/.venv"
fi

"$INSTALL_DIR/.venv/bin/pip" install --upgrade pip
"$INSTALL_DIR/.venv/bin/pip" install -r "$INSTALL_DIR/requirements.txt"

# ============================================================
# CONFIG — НЕ ПЕРЕЗАПИСЫВАЕМ СЕКРЕТЫ
# ============================================================

log "Обновление конфигурации без удаления BOT TOKEN..."

if [[ -f "$ENV_FILE" ]]; then
    # Обновляем только GROQ_KEY_FILE, если он уже отсутствует.
    if ! grep -q '^GROQ_KEY_FILE=' "$ENV_FILE"; then
        printf '\nGROQ_KEY_FILE=%s\n' "$GROQ_KEY_FILE" >> "$ENV_FILE"
    fi
else
    cat > "$ENV_FILE" <<EOF
BOT_TOKEN=$BOT_TOKEN
ADMIN_ID=$ADMIN_ID
GROQ_KEY_FILE=$GROQ_KEY_FILE
EOF
fi

chmod 600 "$ENV_FILE"

# Создаем файл Groq только если его еще нет.
# Существующий рабочий/нерабочий ключ НЕ удаляется.
if [[ ! -f "$GROQ_KEY_FILE" ]]; then
    : > "$GROQ_KEY_FILE"
    chmod 600 "$GROQ_KEY_FILE"
else
    chmod 600 "$GROQ_KEY_FILE"
    log "Существующий Groq API Key сохранен."
fi

# ============================================================
# SYSTEMD
# ============================================================

log "Обновление systemd-сервиса..."
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

systemctl daemon-reload
systemctl enable --now "$SERVICE_NAME"

sleep 2

if systemctl is-active --quiet "$SERVICE_NAME"; then
    log "Обновление завершено."
    echo
    echo "Telegram bot: запущен"
    echo "BOT TOKEN: сохранен"
    echo "ADMIN ID: $ADMIN_ID"
    echo "Groq API Key: сохранен"
    echo
    echo "Админ-панель Telegram: /admin"
    echo
    echo "Статус:"
    echo "  systemctl status $SERVICE_NAME --no-pager"
    echo
    echo "Логи:"
    echo "  journalctl -u $SERVICE_NAME -n 100 --no-pager"
else
    echo
    echo "Сервис не запустился. Последние логи:"
    journalctl -u "$SERVICE_NAME" -n 50 --no-pager || true
    exit 1
fi
