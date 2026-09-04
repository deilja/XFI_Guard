# Полный аудит логов VPS

XFI Guard содержит `scripts/xfi-vps-log-audit.sh` для комплексного анализа журналов **только текущего VPS**.

## Запуск

После установки:

```bash
bash /opt/xfi-guard/scripts/xfi-vps-log-audit.sh
```

По умолчанию анализируется период последних 7 дней. Другой период:

```bash
XFI_AUDIT_SINCE='24 hours ago' bash /opt/xfi-guard/scripts/xfi-vps-log-audit.sh
```

Результат сохраняется в:

```text
/var/log/xfi-guard/audits/<дата-время>/
/var/log/xfi-guard/audits/xfi-vps-audit-<дата-время>.tar.gz
```

Архив создаётся с правами `600`.

## Что проверяется

- ошибки и предупреждения systemd journal;
- kernel/OOM/I/O/filesystem/segfault/panic;
- SSH-аутентификация и brute-force признаки;
- Fail2Ban и все обнаруженные jail;
- UFW и nftables;
- слушающие TCP/UDP порты, маршруты и правила IP;
- процессы CPU/RAM;
- systemd services и timers;
- cron root и `/etc/cron.d`;
- XFI Guard, Telegram bot и updater;
- Xray/x-ui/Nginx;
- массовые security-события;
- самые большие файлы в `/var/log`.

## Безопасность

Скрипт предназначен для **read-only диагностики**: он не блокирует IP, не перезапускает службы и не изменяет firewall.

Секретные файлы `/etc/xfi-guard/bot.env` и `/var/lib/xfi-guard/ai.json` не читаются и не попадают в архив. Используйте архив только на доверенной машине: журналы VPS могут содержать IP-адреса, имена пользователей и другие операционные данные.

## Быстрый анализ

Первым открывайте `SUMMARY.txt`, затем:

1. `journal-errors.txt`
2. `kernel-errors.txt`
3. `ssh.txt`
4. `fail2ban.txt`
5. `firewall.txt`
6. `network.txt`
7. `xfi-guard.txt`
8. `vpn-web.txt`
9. `security-events.txt`

Скрипт не требует подключения к другим VPS и не содержит функций удалённого управления.
