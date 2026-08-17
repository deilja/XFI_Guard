#!/usr/bin/env bash
set -Eeuo pipefail
REPO="${XFI_GUARD_REPO:-https://github.com/deilja/XFI_Guard.git}"
INSTALL_DIR="${XFI_GUARD_DIR:-/opt/xfi-guard}"
PYTHON_BIN="${PYTHON_BIN:-python3}"
TTY=/dev/tty
log(){ printf '\n[XFI Guard] %s\n' "$*"; }
die(){ printf '\n[XFI Guard] ERROR: %s\n' "$*" >&2; exit 1; }
ask(){ local __v="$1"; shift; local __x; if [[ -r "$TTY" ]]; then read -r -p "$*" __x < "$TTY"; else read -r -p "$*" __x; fi; printf -v "$__v" '%s' "$__x"; }
[[ $(id -u) -eq 0 ]] || die "Запустите: sudo bash install.sh"
command -v apt-get >/dev/null || die "Поддерживаются Ubuntu/Debian"
export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y git ca-certificates python3 python3-venv python3-pip
if [[ -d "$INSTALL_DIR/.git" ]]; then git -C "$INSTALL_DIR" fetch --all --prune; git -C "$INSTALL_DIR" reset --hard origin/main; else rm -rf "$INSTALL_DIR"; git clone --depth 1 "$REPO" "$INSTALL_DIR"; fi
cd "$INSTALL_DIR"
"$PYTHON_BIN" -m venv "$INSTALL_DIR/.venv"
"$INSTALL_DIR/.venv/bin/python" -m pip install --upgrade pip
[[ ! -f requirements.txt ]] || "$INSTALL_DIR/.venv/bin/pip" install -r requirements.txt
install -d -m 0755 /var/log/xfi-guard
install -d -m 0700 /var/lib/xfi-guard /etc/xfi-guard
install -m 0644 systemd/xfi-guard.service /etc/systemd/system/xfi-guard.service
systemctl daemon-reload
systemctl enable --now xfi-guard
sleep 2
systemctl is-active --quiet xfi-guard || { journalctl -u xfi-guard -n 80 --no-pager || true; die "XFI Guard не запустился"; }

printf '\n========================================\n XFI Guard — первоначальная настройка\n========================================\n\n'
BOT_TOKEN=""; ADMIN_IDS=""
ask BOT_TOKEN "Telegram Bot Token (Enter — пропустить): "
if [[ -n "$BOT_TOKEN" ]]; then
  ask ADMIN_IDS "Telegram Admin ID (например 123456789): "
  [[ "$ADMIN_IDS" =~ ^[0-9]+(,[0-9]+)*$ ]] || die "ADMIN_IDS должен содержать Telegram ID через запятую"
  cat >/etc/xfi-guard/bot.env <<EOF
XFI_GUARD_BOT_TOKEN=$BOT_TOKEN
XFI_GUARD_ADMIN_IDS=$ADMIN_IDS
EOF
  chmod 600 /etc/xfi-guard/bot.env
  if [[ -f systemd/xfi-guard-bot.service ]]; then
    install -m 0644 systemd/xfi-guard-bot.service /etc/systemd/system/xfi-guard-bot.service
    sed -i "s#^ExecStart=.*#ExecStart=$INSTALL_DIR/.venv/bin/python -m xfi_guard.bot#" /etc/systemd/system/xfi-guard-bot.service
    systemctl daemon-reload
    systemctl enable --now xfi-guard-bot
  fi
  AI_PROVIDER=""
  ask AI_PROVIDER "AI provider [gemini/groq/skip, Enter=gemini]: "
  AI_PROVIDER="${AI_PROVIDER:-gemini}"
  case "$AI_PROVIDER" in gemini|groq) ;; skip) AI_PROVIDER="" ;; *) die "AI provider: gemini, groq или skip" ;; esac
  if [[ -n "$AI_PROVIDER" ]]; then
    cat >/var/lib/xfi-guard/ai.json <<EOF
{"provider":"$AI_PROVIDER","gemini_model":"gemini-2.5-pro","groq_model":"llama-3.3-70b-versatile","gemini_key":"","groq_key":""}
EOF
    chmod 600 /var/lib/xfi-guard/ai.json
    KEY=""
    if [[ "$AI_PROVIDER" == gemini ]]; then ask KEY "Gemini API key (Enter — добавить позже в Telegram): "; else ask KEY "Groq API key (Enter — добавить позже в Telegram): "; fi
    if [[ -n "$KEY" ]]; then
      if [[ "$AI_PROVIDER" == gemini ]]; then sed -i "s#\"gemini_key\":\"\"#\"gemini_key\":\"$KEY\"#" /var/lib/xfi-guard/ai.json; else sed -i "s#\"groq_key\":\"\"#\"groq_key\":\"$KEY\"#" /var/lib/xfi-guard/ai.json; fi
    fi
    chmod 600 /var/lib/xfi-guard/ai.json
  fi
else log "Telegram Bot пропущен; его можно настроить позже."; fi
log "Установка завершена"
printf '\nMonitor: systemctl status xfi-guard --no-pager\nLogs: journalctl -u xfi-guard -f\nJSONL: /var/log/xfi-guard/monitor.jsonl\n'
[[ -z "$BOT_TOKEN" ]] || printf 'Bot: systemctl status xfi-guard-bot --no-pager\nAI: настройка Gemini ↔ Groq через Telegram → 🤖 AI\n'
