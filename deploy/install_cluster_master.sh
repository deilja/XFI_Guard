#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${XFI_GUARD_DIR:-/opt/xfi-guard}"
UNIT_SRC="$APP_DIR/deploy/multi-vps-master.service.example"
UNIT_DST="/etc/systemd/system/xfi-guard-multi-vps-master.service"
ENV_DIR="/etc/xfi-guard"
ENV_FILE="$ENV_DIR/cluster.env"
STATE_DIR="/var/lib/xfi-guard"

if [[ ! -d "$APP_DIR" ]]; then
  echo "XFI Guard directory not found: $APP_DIR" >&2
  exit 1
fi
if [[ ! -x "$APP_DIR/.venv/bin/python" ]]; then
  echo "XFI Guard virtualenv not found: $APP_DIR/.venv/bin/python" >&2
  exit 1
fi

install -d -m 0750 "$ENV_DIR" "$STATE_DIR"

if [[ ! -f "$ENV_FILE" ]]; then
  install -m 0600 /dev/null "$ENV_FILE"
  cat > "$ENV_FILE" <<'EOF'
XFI_GUARD_CLUSTER_HOST=127.0.0.1
XFI_GUARD_CLUSTER_PORT=8765
XFI_GUARD_CLUSTER_TOKEN=
XFI_GUARD_CLUSTER_SECRET=
XFI_GUARD_CLUSTER_STATE=/var/lib/xfi-guard/cluster-state.json
EOF
  echo "Created $ENV_FILE — set token/secret before exposing the API."
fi

install -m 0644 "$UNIT_SRC" "$UNIT_DST"
systemctl daemon-reload
systemctl enable --now xfi-guard-multi-vps-master.service

sleep 1
systemctl --no-pager --full status xfi-guard-multi-vps-master.service || true

if command -v curl >/dev/null 2>&1; then
  curl -fsS --max-time 3 http://127.0.0.1:8765/health || true
  echo
fi
