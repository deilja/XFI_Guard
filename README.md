# XFI Guard

Security and monitoring toolkit for VPS infrastructure.

## Рабочая версия v1.0

XFI Guard устанавливается на Ubuntu/Debian VPS и запускается как systemd-сервис. По умолчанию мониторинг работает в безопасном read-only режиме.

### Что входит

- мониторинг CPU/RAM/диска;
- UFW, Fail2Ban и SSH checks;
- контроль Xray / x-ui / 3x-ui;
- контроль сетевых портов;
- анализ SSH/Fail2Ban событий;
- дедупликация событий и persistent state;
- Telegram-бот администратора;
- Telegram-кнопки управления;
- Gemini / Groq с выбором провайдера и модели;
- AI Security Center;
- JSONL журнал мониторинга;
- systemd;
- unit-тесты и GitHub Actions CI.

## Быстрая установка

Требования: Ubuntu 22.04/24.04 или Debian 12+, root/sudo, Python 3.11+.

```bash
sudo apt update
sudo apt install -y git python3 python3-venv python3-pip
sudo mkdir -p /opt
sudo git clone https://github.com/deilja/XFI_Guard.git /opt/xfi-guard
cd /opt/xfi-guard
sudo python3 -m venv /opt/xfi-guard/.venv
sudo /opt/xfi-guard/.venv/bin/pip install --upgrade pip
if [ -f requirements.txt ]; then sudo /opt/xfi-guard/.venv/bin/pip install -r requirements.txt; fi
sudo mkdir -p /var/log/xfi-guard /var/lib/xfi-guard
sudo install -m 0644 systemd/xfi-guard.service /etc/systemd/system/xfi-guard.service
sudo systemctl daemon-reload
sudo systemctl enable --now xfi-guard
sudo systemctl status xfi-guard --no-pager
```

## Проверка установки

```bash
sudo journalctl -u xfi-guard -n 100 --no-pager
sudo tail -n 20 /var/log/xfi-guard/monitor.jsonl
sudo /opt/xfi-guard/.venv/bin/python -m pytest -q
```

Если сервис не запускается:

```bash
sudo systemctl stop xfi-guard
cd /opt/xfi-guard
sudo /opt/xfi-guard/.venv/bin/python -m xfi_guard.daemon --config /opt/xfi-guard/config.toml
```

## Telegram Bot

Создайте Telegram-бота через BotFather и подготовьте администратора.

```bash
sudo install -d -m 0700 /etc/xfi-guard
sudo nano /etc/xfi-guard/bot.env
```

Файл:

```text
XFI_GUARD_BOT_TOKEN=YOUR_TELEGRAM_BOT_TOKEN
XFI_GUARD_ADMIN_IDS=123456789
```

Для нескольких администраторов:

```text
XFI_GUARD_ADMIN_IDS=123456789,987654321
```

Права:

```bash
sudo chmod 600 /etc/xfi-guard/bot.env
```

Установите сервис бота, если он присутствует в текущей версии репозитория:

```bash
sudo install -m 0644 systemd/xfi-guard-bot.service /etc/systemd/system/xfi-guard-bot.service
sudo systemctl daemon-reload
sudo systemctl enable --now xfi-guard-bot
sudo systemctl status xfi-guard-bot --no-pager
```

В Telegram доступны кнопки:

- 📊 Статус
- 🔐 Безопасность
- 🛡 Fail2Ban
- 🔥 UFW
- 🌐 VPN/Xray
- 📋 События
- 🤖 AI
- 🧠 AI Security Center
- 🔄 Проверка сейчас

## Gemini / Groq

AI-провайдер и ключи не нужно прописывать в Git. Настройки управляются из Telegram-бота.

В меню **🤖 AI** доступны:

- выбор Gemini/Groq;
- Gemini API key;
- Groq API key;
- модель Gemini;
- модель Groq;
- проверка API;
- статус AI.

Настройки сохраняются локально в:

```text
/var/lib/xfi-guard/ai.json
```

Файл должен иметь права `600`.

Для Gemini по умолчанию используется `gemini-2.5-pro`.

Для Groq по умолчанию используется `llama-3.3-70b-versatile`.

## AI Security Center

В Telegram доступны:

- анализ событий за 24 часа;
- топ атакующих IP;
- AI-анализ сводки;
- обновление статистики.

AI работает только как аналитический слой. Автоматические разрушительные действия не выполняются.

## Конфигурация

Основной конфигурационный файл:

```text
/opt/xfi-guard/config.toml
```

Состояние:

```text
/var/lib/xfi-guard/state.json
```

Журнал:

```text
/var/log/xfi-guard/monitor.jsonl
```

## Безопасность

- секреты не должны храниться в Git;
- API keys хранятся только локально с ограниченными правами;
- мониторинг по умолчанию read-only;
- любые потенциально разрушительные действия должны требовать явного подтверждения администратора;
- Telegram-управление ограничено `XFI_GUARD_ADMIN_IDS`.

## Обновление

```bash
cd /opt/xfi-guard
sudo git pull --ff-only
sudo /opt/xfi-guard/.venv/bin/pip install -r requirements.txt 2>/dev/null || true
sudo systemctl restart xfi-guard
sudo systemctl restart xfi-guard-bot 2>/dev/null || true
```

## Диагностика

```bash
sudo systemctl status xfi-guard --no-pager
sudo journalctl -u xfi-guard -f
sudo systemctl status xfi-guard-bot --no-pager
sudo journalctl -u xfi-guard-bot -n 100 --no-pager
```

## Принцип проекта

XFI Guard предназначен для безопасного мониторинга VPS и VPN-инфраструктуры. По умолчанию он не изменяет firewall, маршрутизацию, пользователей или системные настройки. Секреты и API-ключи не включаются в репозиторий.
