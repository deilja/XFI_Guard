# Telegram Webhook

XFI Guard supports an aiogram webhook runner behind Nginx. Polling remains the default until the webhook endpoint is configured, so an existing installation is not broken by upgrading the package.

## Environment

Add to `/etc/xfi-guard/bot.env`:

```text
XFI_GUARD_BOT_TOKEN=...
XFI_GUARD_ADMIN_IDS=1432243715
XFI_GUARD_WEBHOOK_URL=https://ger.deilja.online
XFI_GUARD_WEBHOOK_PATH=/xfi-guard/webhook
XFI_GUARD_WEBHOOK_HOST=127.0.0.1
XFI_GUARD_WEBHOOK_PORT=8080
XFI_GUARD_WEBHOOK_SECRET=<random-32-64-character-secret>
```

The public URL must be HTTPS. The secret is sent by Telegram in `X-Telegram-Bot-Api-Secret-Token` and is verified by aiogram.

Generate a secret, for example:

```bash
openssl rand -hex 32
```

## Nginx

Use `docs/nginx-xfi-guard-webhook.conf` as the starting point. TLS remains on Nginx; XFI Guard listens only on `127.0.0.1`.

## Enable

Install the service and switch off the polling service before enabling the webhook service:

```bash
install -m 0644 systemd/xfi-guard-webhook.service /etc/systemd/system/xfi-guard-webhook.service
systemctl daemon-reload
systemctl disable --now xfi-guard-bot.service
systemctl enable --now xfi-guard-webhook.service
```

Do not run polling and webhook at the same time. Telegram does not deliver updates through both mechanisms simultaneously.

## Verify

```bash
systemctl status xfi-guard-webhook --no-pager
journalctl -u xfi-guard-webhook -n 50 --no-pager
```

Then verify the webhook with Telegram's `getWebhookInfo` or by sending `/start` to the bot.
