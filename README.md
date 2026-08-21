# XFI Guard

**XFI Guard** — интеллектуальная система защиты и централизованного управления VPS-инфраструктурой. Она объединяет мониторинг, Threat Intelligence, AI-анализ, Fail2Ban, UFW, SSH-защиту, Telegram-управление и Multi-VPS синхронизацию в единую систему.

## Возможности

- автоматическое обнаружение атак и подозрительных событий;
- анализ SSH brute-force и Fail2Ban событий;
- Threat Intelligence и рейтинг угроз 0–100;
- AI Security Center и консилиум AI-провайдеров;
- Gemini, Groq, OpenRouter и RouterAI;
- выбор моделей через API провайдера;
- fallback между доступными AI-провайдерами;
- автоматическая блокировка критических угроз без подтверждения администратора;
- интеграция с Fail2Ban;
- срок автоматической блокировки — **7 дней**;
- синхронизация блокировок между VPS;
- UFW как дополнительный уровень сетевой защиты;
- Telegram-уведомления о новых блокировках с IP, причиной, рейтингом и AI confidence;
- централизованное управление несколькими VPS;
- добавление VPS непосредственно из Telegram;
- SSH Agent / `known_hosts` без хранения приватных SSH-ключей XFI Guard;
- проверка состояния XFI Guard и Fail2Ban на узлах;
- удалённое подключение и bootstrap XFI Guard;
- persistent state и JSONL журнал событий;
- systemd-сервисы;
- unit-тесты и GitHub Actions CI.

## Архитектура защиты

```text
Атака
  ↓
Логи VPS
  ↓
XFI Guard Monitor
  ↓
Threat Scoring
  ↓
AI Consensus / Fallback
  ↓
CRITICAL ≥ 90
  ↓
Автоматический BAN
  ↓
Fail2Ban + UFW
  ↓
7 дней
  ↓
Cluster Master
  ↓
Все доступные VPS
  ↓
Telegram уведомление
```

Критическая угроза, обнаруженная на одном узле, может быть автоматически распространена на остальные подключённые VPS. Каждый узел применяет блокировку локально через Fail2Ban.

## Multi-VPS

XFI Guard поддерживает кластер из нескольких VPS.

Узлы управляются через Telegram:

```text
🖥 VPS узлы
├─ ➕ Добавить VPS
├─ 🔐 Добавить по паролю
├─ 🗑 Удалить VPS
├─ 🔌 Подключить XFI Guard
├─ 🔄 Проверить VPS
└─ ⬅️ Главное меню
```

При добавлении VPS бот запрашивает имя, IP/DNS, SSH пользователя и порт, после чего выполняется проверка SSH host key.

Пароль может использоваться только для первичного подключения и не сохраняется XFI Guard. Для постоянного доступа используется SSH Agent/known_hosts.

## Автоматическая блокировка

AI-критические угрозы блокируются автоматически.

Пример логики:

```text
AI confidence ≥ заданного порога
        +
Threat score = CRITICAL
        ↓
Fail2Ban xfi-guard
        ↓
bantime = 604800 секунд
        ↓
7 дней
        ↓
Cluster synchronization
        ↓
Telegram notification
```

Уведомление содержит IP, уровень угрозы, рейтинг, причину, AI-провайдера, уверенность AI, исходный VPS и узлы, на которых применён бан.

## AI Security Center

AI используется как аналитический слой для оценки событий и выбора наиболее подходящего решения.

Поддерживаются:

- Gemini;
- Groq;
- OpenRouter;
- RouterAI;
- fallback между провайдерами;
- получение и выбор моделей через API;
- health-check провайдеров;
- AI consensus;
- анализ событий безопасности.

API-ключи хранятся локально и не должны попадать в Git.

## Telegram Bot

Telegram является основной административной панелью XFI Guard.

Доступ ограничивается `XFI_GUARD_ADMIN_IDS`.

Основные разделы:

- 📊 Статус;
- 🔐 Безопасность;
- 🛡 Fail2Ban;
- 🔥 UFW;
- 🌐 VPN/Xray;
- 📋 События;
- 🤖 AI;
- 🧠 AI Security Center;
- 🖥 VPS узлы;
- 🔄 Проверка сейчас;
- 🔄 Обновление XFI Guard.

## Установка

Для Ubuntu 22.04/24.04 и Debian 12+:

```bash
curl -fsSL https://raw.githubusercontent.com/deilja/XFI_Guard/main/install.sh | sudo bash
```

Альтернативно:

```bash
wget -qO- https://raw.githubusercontent.com/deilja/XFI_Guard/main/install.sh | sudo bash
```

Установщик создаёт Python virtualenv, устанавливает зависимости, настраивает systemd, каталоги состояния и журналов и запускает XFI Guard.

## Telegram Webhook

Поддерживается polling и HTTPS webhook через Nginx.

Схема webhook:

```text
Telegram
   ↓
HTTPS / Nginx
   ↓
127.0.0.1:8080
   ↓
XFI Guard Bot
```

Webhook secret генерируется автоматически и не хранится в Git.

## Конфигурация

Основные файлы:

```text
/opt/xfi-guard/config.toml
/etc/xfi-guard/bot.env
/var/lib/xfi-guard/state.json
/var/lib/xfi-guard/ai.json
/var/log/xfi-guard/monitor.jsonl
```

Multi-VPS узлы добавляются через Telegram или через `[[nodes]]` в `config.toml`.

## Fail2Ban

XFI Guard использует отдельный jail `xfi-guard` для автоматических блокировок.

Рекомендуемый срок блокировки:

```text
604800 секунд = 7 дней
```

Проверка:

```bash
sudo fail2ban-client status
sudo fail2ban-client status xfi-guard
sudo fail2ban-client get xfi-guard bantime
```

## Проверка системы

```bash
systemctl status xfi-guard --no-pager
systemctl status xfi-guard-bot --no-pager
journalctl -u xfi-guard -n 100 --no-pager
journalctl -u xfi-guard-bot -n 100 --no-pager
sudo fail2ban-client status xfi-guard
```

## Обновление

```bash
cd /opt/xfi-guard
git pull --ff-only origin main
/opt/xfi-guard/.venv/bin/pip install -r requirements.txt 2>/dev/null || true
sudo systemctl restart xfi-guard
sudo systemctl restart xfi-guard-bot
```

## Безопасность

- секреты и API-ключи не хранятся в Git;
- Telegram-управление ограничено администраторами;
- SSH private keys не хранятся XFI Guard;
- SSH host keys проверяются через `known_hosts`;
- пароли для bootstrap не сохраняются;
- межузловые команды должны проходить проверку подлинности;
- блокировка применяется локально через Fail2Ban;
- AI-автоматизация ограничивается настроенным порогом угрозы.

## Статус проекта

XFI Guard развивается как распределённая система защиты VPS-инфраструктуры с единым Telegram Control Center, AI-анализом и автоматической реакцией на критические угрозы.