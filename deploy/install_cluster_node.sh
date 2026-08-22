#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${XFI_GUARD_DIR:-/opt/xfi-guard}"
ENV_DIR="/etc/xfi-guard"
ENV_FILE="$ENV_DIR/cluster-node.env"
UNIT="/etc/systemd/system/xfi-guard-cluster-node.service"

[[ -d "$APP_DIR" ]] || { echo "XFI Guard directory not found: $APP_DIR" >&2; exit 1; }
[[ -x "$APP_DIR/.venv/bin/python" ]] || { echo "Virtualenv not found: $APP_DIR/.venv/bin/python" >&2; exit 1; }

install -d -m 0750 "$ENV_DIR" /var/lib/xfi-guard

if [[ ! -f "$ENV_FILE" ]]; then
  install -m 0600 /dev/null "$ENV_FILE"
  cat > "$ENV_FILE" <<'EOF'
XFI_GUARD_CLUSTER_NODE_NAME=CHANGE_ME_NODE_NAME
XFI_GUARD_CLUSTER_MASTER_URL=http://10.70.0.1:8765
XFI_GUARD_CLUSTER_TOKEN=CHANGE_ME_LONG_RANDOM_TOKEN
XFI_GUARD_CLUSTER_HEARTBEAT_INTERVAL=30
XFI_GUARD_CLUSTER_NODE_STATE=/var/lib/xfi-guard/node-state.json
EOF
  echo "Created $ENV_FILE. Configure it and rerun this installer."
  exit 0
fi

install -m 0644 "$APP_DIR/deploy/cluster-node.service.example" "$UNIT"
systemctl daemon-reload
systemctl enable --now xfi-guard-cluster-node.service
systemctl --no-pager --full status xfi-guard-cluster-node.service || true
