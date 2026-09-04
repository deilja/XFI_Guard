#!/usr/bin/env bash
set -Eeuo pipefail

# XFI Guard: безопасный аудит логов текущего VPS.
# Только чтение. Не выполняет блокировку, перезапуск или изменение конфигурации.
# Секреты и содержимое bot.env/AI-конфигурации намеренно не собираются.

SINCE="${XFI_AUDIT_SINCE:-7 days ago}"
OUT_BASE="${XFI_AUDIT_OUT:-/var/log/xfi-guard/audits}"
STAMP="$(date +%Y%m%d-%H%M%S)"
OUT="$OUT_BASE/$STAMP"
ARCHIVE="$OUT_BASE/xfi-vps-audit-$STAMP.tar.gz"

mkdir -p "$OUT"
umask 077

run(){
  local file="$1"; shift
  { echo "# $*"; echo "# generated: $(date -Is)"; echo; "$@"; } >"$OUT/$file" 2>&1 || true
}

journal(){
  journalctl --since "$SINCE" --no-pager -o short-iso "$@"
}

run system.txt bash -c 'cat /etc/os-release; echo; uname -a; echo; uptime; echo; free -h; echo; df -hT'
run failed-services.txt systemctl --failed --no-pager
run services.txt systemctl list-units --type=service --state=running --no-pager
run timers.txt systemctl list-timers --all --no-pager
run journal-errors.txt journal -p err..alert
run journal-warnings.txt journal -p warning
run kernel.txt journal -k
run kernel-errors.txt bash -c 'journal -k | grep -Ei "oom|out of memory|killed process|I/O error|filesystem|ext4|xfs|nvme|segfault|panic|BUG:" || true'

run ssh.txt bash -c '
  journal -u ssh -u sshd || true
  for f in /var/log/auth.log /var/log/secure; do
    if [ -r "$f" ]; then
      echo "===== $f ====="
      grep -Ei "failed|invalid|authentication failure|accepted|break-in|refused|disconnect" "$f" || true
    fi
  done
'

run fail2ban.txt bash -c '
  fail2ban-client status 2>&1 || true
  echo
  jails="$(fail2ban-client status 2>/dev/null | sed -n "s/.*Jail list:[[:space:]]*//p" | tr "," " ")"
  for jail in $jails; do
    echo "===== $jail ====="
    fail2ban-client status "$jail" 2>&1 || true
  done
  echo
  journal -u fail2ban || true
'

run firewall.txt bash -c '
  command -v ufw >/dev/null && { ufw status verbose; ufw status numbered; } || true
  echo "===== nftables ====="
  command -v nft >/dev/null && nft list ruleset || true
'

run network.txt bash -c 'ss -lntup; echo; ip -br addr; echo; ip route; echo; ip rule'
run processes.txt bash -c 'ps aux --sort=-%mem | head -40; echo; ps aux --sort=-%cpu | head -40'
run cron.txt bash -c '
  echo "===== root crontab ====="; crontab -l 2>&1 || true
  echo "===== /etc/crontab ====="; cat /etc/crontab 2>&1 || true
  echo "===== /etc/cron.d ====="
  for f in /etc/cron.d/*; do [ -f "$f" ] || continue; echo "--- $f"; cat "$f"; done
'

run xfi-guard.txt bash -c '
  systemctl status xfi-guard --no-pager -l || true
  echo "===== service journal ====="
  journal -u xfi-guard || true
  echo "===== bot ====="
  systemctl status xfi-guard-bot --no-pager -l || true
  journal -u xfi-guard-bot || true
  echo "===== updater ====="
  systemctl status xfi-guard-update-check.timer --no-pager -l || true
  journal -u xfi-guard-update-check || true
'

run vpn-web.txt bash -c '
  for unit in x-ui xray nginx; do
    echo "===== $unit status ====="
    systemctl status "$unit" --no-pager -l || true
    echo "===== $unit journal ====="
    journal -u "$unit" || true
  done
  echo "===== nginx config test ====="
  command -v nginx >/dev/null && nginx -t || true
'

run security-events.txt bash -c 'journal | grep -Ei "failed|failure|error|critical|attack|ban|blocked|denied|unauthorized|invalid|segfault|panic|oom|brute|scan" || true'
run large-log-files.txt bash -c 'find /var/log -type f -printf "%s %p\n" 2>/dev/null | sort -nr | head -100'

# Compact, privacy-preserving summary for quick review.
{
  echo "XFI Guard VPS log audit"
  echo "Generated: $(date -Is)"
  echo "Period: $SINCE"
  echo "Directory: $OUT"
  echo
  echo "Error lines: $(wc -l < "$OUT/journal-errors.txt")"
  echo "Warning lines: $(wc -l < "$OUT/journal-warnings.txt")"
  echo "Listening sockets: $(grep -Ec "LISTEN" "$OUT/network.txt" || true)"
  echo "Failed services: $(grep -Ec "● .*\.service" "$OUT/failed-services.txt" || true)"
} >"$OUT/SUMMARY.txt"

# Archive is created with restrictive permissions; secrets are not collected by this script.
tar -czf "$ARCHIVE" -C "$OUT_BASE" "$STAMP"
chmod 600 "$ARCHIVE"
printf '%s\n' "$ARCHIVE"
