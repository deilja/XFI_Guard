#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${XFI_GUARD_DIR:-/opt/xfi-guard}"
UNIT_SRC="$APP_DIR/deploy/multi-vps-master.service.example"
UNIT_DST="/etc/systemd/system/xfi-guard-multi-vps-master.service"
ENV_DIR="/etc/xfi-guard"
ENV_FILE="$ENV_DIR/cluster.env"
STATE_DIR="/var/lib/xfi-guard"

if [[ ! -d "$APP_DIR" ]]; then echo "XFI Guard directory not found: $APP_DIR" >&2; exit 1; fi
if [[ ! -x "$APP_DIR/.venv/bin/python" ]]; then echo "XFI Guard virtualenv not found: $APP_DIR/.venv/bin/python" >&2; exit 1; fi
if [[ ! -f "$UNIT_SRC" ]]; then echo "Cluster Master service template not found: $UNIT_SRC" >&2; exit 1; fi

install -d -m 0750 "$ENV_DIR" "$STATE_DIR"
if [[ ! -f "$ENV_FILE" ]]; then
  install -m 0600 /dev/null "$ENV_FILE"
  cat > "$ENV_FILE" <<'EOF'
# Cluster Master bind. Protect TCP/8765 with firewall/VPN to trusted peers.
XFI_GUARD_CLUSTER_HOST=0.0.0.0
XFI_GUARD_CLUSTER_PORT=8765
XFI_GUARD_CLUSTER_TOKEN=
XFI_GUARD_CLUSTER_SECRET=
XFI_GUARD_CLUSTER_STATE=/var/lib/xfi-guard/cluster-state.json
XFI_GUARD_CLUSTER_TIMEOUT=5
EOF
fi

if ! grep -q '^XFI_GUARD_CLUSTER_TOKEN=..*' "$ENV_FILE"; then
  TOKEN="$(openssl rand -hex 32 2>/dev/null || "$APP_DIR/.venv/bin/python" -c 'import secrets; print(secrets.token_hex(32))')"
  sed -i "s/^XFI_GUARD_CLUSTER_TOKEN=.*/XFI_GUARD_CLUSTER_TOKEN=$TOKEN/" "$ENV_FILE"
fi
if ! grep -q '^XFI_GUARD_CLUSTER_SECRET=..*' "$ENV_FILE"; then
  SECRET="$(openssl rand -hex 32 2>/dev/null || "$APP_DIR/.venv/bin/python" -c 'import secrets; print(secrets.token_hex(32))')"
  sed -i "s/^XFI_GUARD_CLUSTER_SECRET=.*/XFI_GUARD_CLUSTER_SECRET=$SECRET/" "$ENV_FILE"
fi
chmod 0600 "$ENV_FILE"

sed "s#^WorkingDirectory=.*#WorkingDirectory=$APP_DIR#; s#^ExecStart=.*#ExecStart=$APP_DIR/.venv/bin/python -m xfi_guard.cluster_master#" "$UNIT_SRC" > "$UNIT_DST"
chmod 0644 "$UNIT_DST"
systemctl daemon-reload
systemctl enable --now xfi-guard-multi-vps-master.service

sleep 1
if ! systemctl is-active --quiet xfi-guard-multi-vps-master.service; then
  systemctl --no-pager --full status xfi-guard-multi-vps-master.service || true
  journalctl -u xfi-guard-multi-vps-master.service -n 80 --no-pager || true
  exit 1
fi

set -a
# shellcheck disable=SC1090
source "$ENV_FILE"
set +a

if ! command -v curl >/dev/null 2>&1; then echo "curl is required for health verification" >&2; exit 1; fi

HEALTH_URL="http://127.0.0.1:${XFI_GUARD_CLUSTER_PORT}/health"
echo "Cluster Master local health:"
curl -fsS --max-time "${XFI_GUARD_CLUSTER_TIMEOUT:-5}" \
  -H "Authorization: Bearer ${XFI_GUARD_CLUSTER_TOKEN}" "$HEALTH_URL"
echo

echo "Cluster Master listening sockets:"
ss -lntp 2>/dev/null | grep -E ":${XFI_GUARD_CLUSTER_PORT}\b" || {
  echo "Cluster Master is not listening on TCP/${XFI_GUARD_CLUSTER_PORT}" >&2
  exit 1
}

echo "Cluster Master installed: xfi-guard-multi-vps-master.service"
echo "Configuration: $ENV_FILE"
echo "Firewall: allow TCP/${XFI_GUARD_CLUSTER_PORT} only from trusted cluster peers."
if command -v ufw >/dev/null 2>&1 && ufw status | grep -q "Status: active"; then
  echo "UFW is active; no broad allow rule was added automatically."
  echo "Add a peer-specific rule, for example: ufw allow from <NODE_IP> to any port ${XFI_GUARD_CLUSTER_PORT} proto tcp"
fi
