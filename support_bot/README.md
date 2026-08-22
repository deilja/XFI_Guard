# XFI Support Bot

Telegram-бот технической поддержки XFI с синхронным Groq-клиентом.

## Возможности

- поддержка пользователей через Telegram;
- AI-предварительный ответ через Groq;
- модель `llama-3.3-70b-versatile`;
- маршрутизация тикетов инженерам;
- админ-панель `/admin`;
- установка, проверка и удаление Groq API Key прямо через Telegram;
- недействительный Groq API Key не сохраняется;
- API Key не хранится в Git;
- Groq API Key хранится локально с правами `600`;
- синхронный `Groq` используется через `asyncio.to_thread`, чтобы не блокировать Telegram polling.

## Установка одной командой

Установщик сам запросит:

1. Telegram BOT TOKEN;
2. Telegram ADMIN ID.

Выполните на Ubuntu/Debian:

```bash
curl -fsSL https://raw.githubusercontent.com/deilja/XFI_Guard/main/support_bot/install.sh | sudo bash
```

После запуска появится:

```text
Введите Telegram BOT TOKEN:
Введите Telegram ADMIN ID:
```

После установки бот автоматически создаётся как systemd-сервис:

```text
xfi-support-bot.service
```

Каталог установки:

```text
/opt/xfi-support-bot
```

## Настройка Groq

Groq API Key не требуется при установке.

После запуска откройте бота и отправьте:

```text
/admin
```

Затем:

```text
🔑 Установить / изменить Groq API Key
```

Бот проверит ключ реальным запросом к Groq. Только после успешной проверки ключ будет сохранён.

Доступны также:

```text
🔎 Проверить Groq
🗑 Удалить Groq API Key
```

## Управление сервисом

```bash
systemctl status xfi-support-bot --no-pager
```

Логи:

```bash
journalctl -u xfi-support-bot -n 100 --no-pager
```

Перезапуск:

```bash
systemctl restart xfi-support-bot
```

Остановка:

```bash
systemctl stop xfi-support-bot
```

## Конфигурация

Основной файл:

```text
/opt/xfi-support-bot/main.py
```

Переменные Telegram:

```text
/opt/xfi-support-bot/.env
```

Groq API Key:

```text
/opt/xfi-support-bot/.groq_api_key
```

Оба файла имеют ограниченные права доступа и не должны попадать в Git.

## Безопасность

Новый Groq API Key принимается только от Telegram-пользователя с указанным `ADMIN_ID`.

Ключ не выводится полностью в админ-панели. При проверке бот сообщает только состояние подключения и маскированное значение ключа.

Если Groq API Key недействителен, он не заменяет предыдущий рабочий ключ.
