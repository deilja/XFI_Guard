#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${XFI_GUARD_DIR:-/opt/xfi-guard}"
ENV_DIR="/etc/xfi-guard"
ENV_FILE="$ENV_DIR/cluster-node.env"
UNIT_SRC="$APP_DIR/deploy/cluster-node.service.example"
UNIT="/etc/systemd/system/xfi-guard-cluster-node.service"

[[ -d "$APP_DIR" ]] || { echo "XFI Guard directory not found: $APP_DIR" >&2; exit 1; }
[[ -x "$APP_DIR/.venv/bin/python" ]] || { echo "Virtualenv not found: $APP_DIR/.venv/bin/python" >&2; exit 1; }
[[ -f "$UNIT_SRC" ]] || { echo "Cluster Node service template not found: $UNIT_SRC" >&2; exit 1; }

install -d -m 0750 "$ENV_DIR" /var/lib/xfi-guard

if [[ ! -f "$ENV_FILE" ]]; then
  install -m 0600 /dev/null "$ENV_FILE"
  cat > "$ENV_FILE" <<'EOF'
XFI_GUARD_CLUSTER_NODE_NAME=CHANGE_ME_NODE_NAME
XFI_GUARD_CLUSTER_MASTER_URL=http://10.70.0.1:8765
XFI_GUARD_CLUSTER_TOKEN=CHANGE_ME_LONG_RANDOM_TOKEN
XFI_GUARD_CLUSTER_SECRET=CHANGE_ME_LONG_RANDOM_SECRET
XFI_GUARD_CLUSTER_HEARTBEAT_INTERVAL=30
XFI_GUARD_CLUSTER_NODE_STATE=/var/lib/xfi-guard/node-state.json
EOF
  echo "Created $ENV_FILE. Configure node name, Master URL, token and secret, then rerun this installer."
  exit 0
fi

# Do not start a node with placeholder credentials or URL.
set -a
# shellcheck disable=SC1090
source "$ENV_FILE"
set +a

for required in XFI_GUARD_CLUSTER_NODE_NAME XFI_GUARD_CLUSTER_MASTER_URL XFI_GUARD_CLUSTER_TOKEN XFI_GUARD_CLUSTER_SECRET; do
  value="${!required:-}"
  if [[ -z "$value" || "$value" == CHANGE_ME* ]]; then
    echo "$required is not configured in $ENV_FILE" >&2
    exit 1
  fi
done

chmod 0600 "$ENV_FILE"

sed "s#^WorkingDirectory=.*#WorkingDirectory=$APP_DIR#; s#^ExecStart=.*#ExecStart=$APP_DIR/.venv/bin/python -m xfi_guard.cluster_node#" "$UNIT_SRC" > "$UNIT"
chmod 0644 "$UNIT"
systemctl daemon-reload
systemctl enable --now xfi-guard-cluster-node.service
systemctl --no-pager --full status xfi-guard-cluster-node.service || true
