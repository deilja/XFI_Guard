#!/usr/bin/env bash
set -Eeuo pipefail
REPO="${XFI_GUARD_REPO:-https://github.com/deilja/XFI_Guard.git}"
INSTALL_DIR="${XFI_GUARD_DIR:-/opt/xfi-guard}"
PYTHON_BIN="${PYTHON_BIN:-python3}"
TTY=/dev/tty
log(){ printf '\n[XFI Guard] %s\n' "$*"; }
die(){ printf '\n[XFI Guard] ERROR: %s\n' "$*" >&2; exit 1; }
ask(){ local __v="$1"; shift; local __x=""; if [[ -r "$TTY" ]]; then IFS= read -r -p "$*" __x < "$TTY" || true; else IFS= read -r -p "$*" __x || true; fi; printf -v "$__v" '%s' "$__x"; }
[[ $(id -u) -eq 0 ]] || die "Запустите: sudo bash install.sh"
command -v apt-get >/dev/null || die "Поддерживаются Ubuntu/Debian"
export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y git ca-certificates python3 python3-venv python3-pip nginx openssl certbot python3-certbot-nginx fail2ban
PRESERVE_DIR="$(mktemp -d)"
cleanup(){ rm -rf "$PRESERVE_DIR"; }
trap cleanup EXIT
preserve_file(){ local src="$1" dst="$PRESERVE_DIR/$(echo "$1" | sed 's#^/##; s#/#_#g')"; [[ -f "$src" ]] || return 0; cp -a "$src" "$dst"; log "Сохранена конфигурация: $src"; }
restore_file(){ local src="$PRESERVE_DIR/$(echo "$1" | sed 's#^/##; s#/#_#g')" dst="$1"; [[ -f "$src" ]] || return 0; install -d "$(dirname "$dst")"; cp -a "$src" "$dst"; chmod 600 "$dst" 2>/dev/null || true; log "Восстановлена конфигурация: $dst"; }
preserve_file /etc/xfi-guard/bot.env
preserve_file /var/lib/xfi-guard/ai.json
preserve_file "$INSTALL_DIR/.env"
preserve_file "$INSTALL_DIR/.env.local"
if [[ -d "$INSTALL_DIR/.git" ]]; then git -C "$INSTALL_DIR" fetch --all --prune; git -C "$INSTALL_DIR" reset --hard origin/main; else rm -rf "$INSTALL_DIR"; git clone --depth 1 "$REPO" "$INSTALL_DIR"; fi
cd "$INSTALL_DIR"
"$PYTHON_BIN" -m venv "$INSTALL_DIR/.venv"
"$INSTALL_DIR/.venv/bin/python" -m pip install --upgrade pip
"$INSTALL_DIR/.venv/bin/pip" install --upgrade .
"$INSTALL_DIR/.venv/bin/pip" install --upgrade 'pytest>=8,<9'
install -d -m 0755 /var/log/xfi-guard
install -d -m 0700 /var/lib/xfi-guard /etc/xfi-guard
restore_file /etc/xfi-guard/bot.env
restore_file /var/lib/xfi-guard/ai.json
restore_file "$INSTALL_DIR/.env"
restore_file "$INSTALL_DIR/.env.local"
log "Запуск pytest"
"$INSTALL_DIR/.venv/bin/python" -m pytest -q || die "pytest завершился с ошибкой; сервисы не будут включены"
install -d -m 0755 /etc/fail2ban/filter.d /etc/fail2ban/jail.d
install -m 0644 config/fail2ban/filter.d/xfi-guard.conf /etc/fail2ban/filter.d/xfi-guard.conf
install -m 0644 config/fail2ban/jail.d/xfi-guard.conf /etc/fail2ban/jail.d/xfi-guard.conf
touch /var/log/xfi-guard/fail2ban-sync.log
chmod 0640 /var/log/xfi-guard/fail2ban-sync.log
systemctl enable --now fail2ban
fail2ban-client reload || systemctl restart fail2ban
fail2ban-client status xfi-guard >/dev/null || die "Fail2Ban jail xfi-guard не запустился"
install -m 0644 systemd/xfi-guard.service /etc/systemd/system/xfi-guard.service
# Install updater/checker units from GitHub so the bot can update itself safely.
for unit in xfi-guard-update.service xfi-guard-update-check.service xfi-guard-update-check.timer; do
  [[ -f "systemd/$unit" ]] && install -m 0644 "systemd/$unit" "/etc/systemd/system/$unit"
done
printf '\n========================================\n XFI Guard — первоначальная настройка\n========================================\n\n'
BOT_TOKEN=""; ADMIN_IDS=""; WEBHOOK_DOMAIN=""; EXISTING_CONFIG=0
[[ -f /etc/xfi-guard/bot.env ]] && EXISTING_CONFIG=1
if [[ "$EXISTING_CONFIG" -eq 1 ]]; then
  log "Найдена существующая конфигурация. Секреты будут сохранены; повторный ввод не требуется."
  _load_bot_env(){ while IFS= read -r line; do [[ -z "$line" || "$line" == \#* || "$line" != *=* ]] && continue; key="${line%%=*}"; value="${line#*=}"; case "$key" in XFI_GUARD_BOT_TOKEN) BOT_TOKEN="$value";; XFI_GUARD_ADMIN_IDS) ADMIN_IDS="$value";; XFI_GUARD_WEBHOOK_DOMAIN) WEBHOOK_DOMAIN="$value";; esac; done < /etc/xfi-guard/bot.env; }
  _load_bot_env
else
  ask BOT_TOKEN "Telegram Bot Token (Enter — пропустить): "
  if [[ -n "$BOT_TOKEN" ]]; then
    ask ADMIN_IDS "Telegram Admin ID (например 123456789): "
    [[ "$ADMIN_IDS" =~ ^[0-9]+(,[0-9]+)*$ ]] || die "ADMIN_IDS должен содержать Telegram ID через запятую"
    ask WEBHOOK_DOMAIN "Домен для Telegram Webhook (например fin.deilja.online, Enter — polling): "
    WEBHOOK_DOMAIN="${WEBHOOK_DOMAIN#https://}"; WEBHOOK_DOMAIN="${WEBHOOK_DOMAIN#http://}"; WEBHOOK_DOMAIN="${WEBHOOK_DOMAIN%%/*}"
    if [[ -n "$WEBHOOK_DOMAIN" ]]; then
      [[ "$WEBHOOK_DOMAIN" =~ ^[A-Za-z0-9.-]+$ ]] || die "Некорректное имя домена"
      WEBHOOK_SECRET="$(openssl rand -hex 32)"
      cat >/etc/xfi-guard/bot.env <<EOF
XFI_GUARD_BOT_TOKEN=$BOT_TOKEN
XFI_GUARD_ADMIN_IDS=$ADMIN_IDS
XFI_GUARD_WEBHOOK_DOMAIN=$WEBHOOK_DOMAIN
XFI_GUARD_WEBHOOK_PATH=/xfi-guard/webhook
XFI_GUARD_WEBHOOK_SECRET=$WEBHOOK_SECRET
XFI_GUARD_WEBHOOK_HOST=127.0.0.1
XFI_GUARD_WEBHOOK_PORT=8080
EOF
      chmod 600 /etc/xfi-guard/bot.env
      log "Настройка Nginx для $WEBHOOK_DOMAIN"
      cat >/etc/nginx/sites-available/xfi-guard-webhook.conf <<EOF
server { listen 80; listen [::]:80; server_name $WEBHOOK_DOMAIN; location /.well-known/acme-challenge/ { root /var/www/html; } location / { return 404; } }
EOF
      ln -sf /etc/nginx/sites-available/xfi-guard-webhook.conf /etc/nginx/sites-enabled/xfi-guard-webhook.conf
      rm -f /etc/nginx/sites-enabled/default; mkdir -p /var/www/html; nginx -t; systemctl enable --now nginx; systemctl reload nginx
      if [[ ! -f "/etc/letsencrypt/live/$WEBHOOK_DOMAIN/fullchain.pem" ]]; then certbot certonly --webroot -w /var/www/html -d "$WEBHOOK_DOMAIN" --non-interactive --agree-tos --register-unsafely-without-email || die "Не удалось получить SSL для $WEBHOOK_DOMAIN."; fi
      cat >/etc/nginx/sites-available/xfi-guard-webhook.conf <<EOF
server { listen 80; listen [::]:80; server_name $WEBHOOK_DOMAIN; location /.well-known/acme-challenge/ { root /var/www/html; } location / { return 301 https://\$host\$request_uri; } }
server { listen 443 ssl http2; listen [::]:443 ssl http2; server_name $WEBHOOK_DOMAIN; ssl_certificate /etc/letsencrypt/live/$WEBHOOK_DOMAIN/fullchain.pem; ssl_certificate_key /etc/letsencrypt/live/$WEBHOOK_DOMAIN/privkey.pem; location = /xfi-guard/webhook { proxy_pass http://127.0.0.1:8080; proxy_http_version 1.1; proxy_set_header Host \$host; proxy_set_header X-Real-IP \$remote_addr; proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for; proxy_set_header X-Forwarded-Proto https; } location / { return 404; } }
EOF
      nginx -t && systemctl reload nginx
    else
      cat >/etc/xfi-guard/bot.env <<EOF
XFI_GUARD_BOT_TOKEN=$BOT_TOKEN
XFI_GUARD_ADMIN_IDS=$ADMIN_IDS
EOF
      chmod 600 /etc/xfi-guard/bot.env
      log "Домен не указан: бот будет работать через polling."
    fi
  else
    log "Telegram Bot пропущен; его можно настроить позже."
  fi
fi
# Single-VPS mode: no cluster/multi-VPS services, node enrollment or remote SSH management.
rm -f /etc/systemd/system/xfi-guard-multi-vps-master.service /etc/systemd/system/xfi-guard-cluster-node.service /etc/systemd/system/xfi-guard-multi-vps.service
systemctl daemon-reload || true
systemctl disable --now xfi-guard-multi-vps-master.service 2>/dev/null || true
systemctl disable --now xfi-guard-cluster-node.service 2>/dev/null || true
# Remove legacy cluster configuration and state left by older releases.
rm -f /etc/xfi-guard/cluster.env /etc/xfi-guard/cluster-node.env
rm -f /var/lib/xfi-guard/cluster-state.json
if [[ -f systemd/xfi-guard-bot.service ]]; then
  install -m 0644 systemd/xfi-guard-bot.service /etc/systemd/system/xfi-guard-bot.service
  sed -i "s#^ExecStart=.*#ExecStart=$INSTALL_DIR/.venv/bin/python -m xfi_guard.bot#" /etc/systemd/system/xfi-guard-bot.service
  systemctl daemon-reload
fi
if [[ ! -f /var/lib/xfi-guard/ai.json ]]; then
  cat >/var/lib/xfi-guard/ai.json <<'EOF'
{"provider":"gemini","gemini_model":"gemini-2.5-pro","groq_model":"llama-3.3-70b-versatile","gemini_key":"","groq_key":""}
EOF
  chmod 600 /var/lib/xfi-guard/ai.json
fi
log "AI по умолчанию: Gemini"
systemctl daemon-reload
systemctl enable --now xfi-guard
sleep 2
systemctl is-active --quiet xfi-guard || { journalctl -u xfi-guard -n 80 --no-pager || true; die "XFI Guard не запустился"; }
if [[ -n "$BOT_TOKEN" ]]; then
  systemctl enable --now xfi-guard-bot
  sleep 2
  systemctl is-active --quiet xfi-guard-bot || { journalctl -u xfi-guard-bot -n 80 --no-pager || true; die "Telegram bot не запустился"; }
  systemctl enable --now xfi-guard-update-check.timer 2>/dev/null || true
fi
log "Установка/обновление завершено; Fail2Ban xfi-guard активен, bantime=7d; режим: один VPS."
printf '\nMonitor: systemctl status xfi-guard --no-pager\nLogs:    journalctl -u xfi-guard -f\nJSONL:   /var/log/xfi-guard/monitor.jsonl\nFail2Ban: fail2ban-client status xfi-guard\n'
[[ -z "$BOT_TOKEN" ]] || printf 'Bot:     systemctl status xfi-guard-bot --no-pager\nUpdater: systemctl status xfi-guard-update-check.timer --no-pager\nAI:      настройка Gemini ↔ Groq через Telegram → 🤖 AI\n'
