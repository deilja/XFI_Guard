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
- Telegram Webhook через Nginx + HTTPS;
- Gemini / Groq с выбором провайдера и модели;
- AI Security Center;
- JSONL журнал мониторинга;
- systemd;
- unit-тесты и GitHub Actions CI.

## Установка одной командой

Для Ubuntu 22.04/24.04 и Debian 12+:

```bash
curl -fsSL https://raw.githubusercontent.com/deilja/XFI_Guard/main/install.sh | sudo bash
```

Альтернативно через wget:

```bash
wget -qO- https://raw.githubusercontent.com/deilja/XFI_Guard/main/install.sh | sudo bash
```

Скрипт автоматически:

1. устанавливает системные зависимости;
2. загружает XFI Guard в `/opt/xfi-guard`;
3. создаёт Python virtualenv;
4. устанавливает Python-зависимости;
5. создаёт `/var/log/xfi-guard` и `/var/lib/xfi-guard`;
6. устанавливает systemd unit;
7. запускает `xfi-guard`;
8. при настройке Telegram спрашивает домен webhook;
9. при указанном домене устанавливает Nginx и Certbot, получает Let's Encrypt SSL и проксирует `/xfi-guard/webhook` на `127.0.0.1:8080`;
10. запускает Telegram-бота и регистрирует webhook через Telegram API;
11. проверяет, что сервисы запущены.

### Домен Telegram Webhook

После ввода Telegram Bot Token и Admin ID установщик задаёт вопрос:

```text
Домен для Telegram Webhook (например fin.deilja.online, Enter — polling):
```

Например:

```text
fin.deilja.online
```

В результате бот работает через:

```text
https://fin.deilja.online/xfi-guard/webhook
```

Nginx принимает HTTPS и передаёт запросы локальному боту:

```text
Telegram → HTTPS/Nginx → 127.0.0.1:8080 → XFI Guard
```

Перед установкой домен должен указывать на VPS, а TCP-порт 80 должен быть доступен для получения сертификата Let's Encrypt. Если домен не указан, сохраняется режим polling.

### Конфигурация webhook

Переменные сохраняются в `/etc/xfi-guard/bot.env`:

```text
XFI_GUARD_WEBHOOK_DOMAIN=fin.deilja.online
XFI_GUARD_WEBHOOK_PATH=/xfi-guard/webhook
XFI_GUARD_WEBHOOK_SECRET=<generated-secret>
XFI_GUARD_WEBHOOK_HOST=127.0.0.1
XFI_GUARD_WEBHOOK_PORT=8080
```

Секрет webhook генерируется автоматически и не попадает в Git.

Пользовательские переменные можно передать перед запуском:

```bash
sudo XFI_GUARD_DIR=/opt/xfi-guard bash -c 'curl -fsSL https://raw.githubusercontent.com/deilja/XFI_Guard/main/install.sh | bash'
```

## Проверка

```bash
systemctl status xfi-guard --no-pager
journalctl -u xfi-guard -n 100 --no-pager
tail -n 20 /var/log/xfi-guard/monitor.jsonl
```

Для Telegram webhook:

```bash
systemctl status xfi-guard-bot --no-pager
journalctl -u xfi-guard-bot -n 100 --no-pager
nginx -t
curl -I https://fin.deilja.online/xfi-guard/webhook
```

Статус webhook можно проверить через Telegram Bot API `getWebhookInfo`.

## Telegram Bot

Создайте Telegram-бота через BotFather и подготовьте Telegram ID администратора.

```bash
install -d -m 0700 /etc/xfi-guard
nano /etc/xfi-guard/bot.env
chmod 600 /etc/xfi-guard/bot.env
```

Содержимое для polling:

```text
XFI_GUARD_BOT_TOKEN=YOUR_TELEGRAM_BOT_TOKEN
XFI_GUARD_ADMIN_IDS=123456789
```

Для webhook дополнительные переменные создаёт установщик автоматически.

Для нескольких администраторов:

```text
XFI_GUARD_ADMIN_IDS=123456789,987654321
```

Если в репозитории присутствует `systemd/xfi-guard-bot.service`:

```bash
install -m 0644 /opt/xfi-guard/systemd/xfi-guard-bot.service /etc/systemd/system/xfi-guard-bot.service
systemctl daemon-reload
systemctl enable --now xfi-guard-bot
systemctl status xfi-guard-bot --no-pager
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
- 🔄 Обновить XFI Guard

## Gemini / Groq

AI-провайдер и ключи управляются через Telegram и не должны находиться в Git.

В меню **🤖 AI** доступны:

- выбор Gemini/Groq;
- Gemini API key;
- Groq API key;
- модель Gemini;
- модель Groq;
- проверка API;
- статус AI.

Настройки сохраняются локально:

```text
/var/lib/xfi-guard/ai.json
```

Файл должен иметь права `600`.

## AI Security Center

В Telegram доступны:

- анализ событий за 24 часа;
- топ атакующих IP;
- AI-анализ сводки;
- обновление статистики.

AI используется как аналитический слой. Разрушительные действия не выполняются автоматически.

## Конфигурация

```text
/opt/xfi-guard/config.toml
/var/lib/xfi-guard/state.json
/var/log/xfi-guard/monitor.jsonl
```

## Обновление

```bash
cd /opt/xfi-guard
git pull --ff-only
/opt/xfi-guard/.venv/bin/pip install -r requirements.txt 2>/dev/null || true
systemctl restart xfi-guard
systemctl restart xfi-guard-bot 2>/dev/null || true
```

## Диагностика

```bash
systemctl status xfi-guard --no-pager
journalctl -u xfi-guard -f
systemctl status xfi-guard-bot --no-pager
journalctl -u xfi-guard-bot -n 100 --no-pager
```

## Безопасность

- секреты не хранятся в Git;
- API keys хранятся локально с ограниченными правами;
- webhook secret хранится только в `/etc/xfi-guard/bot.env`;
- мониторинг read-only по умолчанию;
- потенциально разрушительные действия должны требовать явного подтверждения администратора;
- Telegram-управление ограничено `XFI_GUARD_ADMIN_IDS`.
