#!/usr/bin/env bash
set -u

URL="${XFI_GUARD_CLUSTER_MASTER_URL:-http://127.0.0.1:8765}"
TIMEOUT="${XFI_GUARD_CLUSTER_TIMEOUT:-5}"
TOKEN="${XFI_GUARD_CLUSTER_TOKEN:-}"

printf 'XFI Guard Cluster Master diagnostic\n'
printf 'URL: %s\n\n' "$URL"

if command -v systemctl >/dev/null 2>&1; then
  for unit in xfi-guard-multi-vps-master.service multi-vps-master.service; do
    if systemctl cat "$unit" >/dev/null 2>&1; then
      printf 'Service %s: ' "$unit"
      systemctl is-active "$unit" || true
    fi
  done
fi

printf '\nHTTP health: '
if [ -n "$TOKEN" ]; then
  curl -fsS --max-time "$TIMEOUT" -H "Authorization: Bearer $TOKEN" "$URL/health" && printf '\n'
else
  curl -fsS --max-time "$TIMEOUT" "$URL/health" && printf '\n'
fi

printf '\nListener check:\n'
if command -v ss >/dev/null 2>&1; then
  ss -lntp | grep -E ':8765[[:space:]]' || printf 'No TCP listener on port 8765\n'
fi
