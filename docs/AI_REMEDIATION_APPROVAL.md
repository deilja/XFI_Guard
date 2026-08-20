# AI Remediation Approval

XFI Guard использует отдельный approval-token для связи AI-предложения с конкретным изменением.

## Поток

1. AI анализирует инцидент.
2. XFI Guard формирует `RemediationPlan`.
3. Telegram показывает администратору действие, цель, риск и затронутых клиентов.
4. При подтверждении создаётся короткоживущий HMAC approval-token.
5. Executor принимает только план с валидным token, совпадающим с fingerprint плана и Telegram admin ID.
6. После применения выполняется verify.
7. При ошибке verify запускается rollback, если для операции он предусмотрен.

## Защита

- token действует ограниченное время;
- token привязан к полному fingerprint плана;
- token привязан к конкретному admin ID;
- секрет хранится только в окружении `XFI_GUARD_APPROVAL_SECRET`;
- отсутствие секрета блокирует выдачу token;
- AI не получает shell-доступ;
- destructive/network actions не исполняются generic executor.

Секрет можно создать командой `openssl rand -hex 32` и поместить в защищённый environment-файл systemd.
