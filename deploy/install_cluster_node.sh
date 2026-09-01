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
XFI_GUARD_CLUSTER_MASTER_URL=https://CHANGE_ME_MASTER
XFI_GUARD_CLUSTER_TOKEN=CHANGE_ME_LONG_RANDOM_TOKEN
XFI_GUARD_CLUSTER_SECRET=CHANGE_ME_LONG_RANDOM_SECRET
XFI_GUARD_CLUSTER_HEARTBEAT_INTERVAL=30
XFI_GUARD_CLUSTER_NODE_STATE=/var/lib/xfi-guard/node-state.json
EOF
  echo "Created $ENV_FILE. Configure node name, Master URL, token and secret, then rerun this installer."
  exit 0
fi

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

NORMALIZED_MASTER="$($APP_DIR/.venv/bin/python - "$XFI_GUARD_CLUSTER_MASTER_URL" <<'PY'
import sys
from xfi_guard.master_url import assert_master_not_this_vps
print(assert_master_not_this_vps(sys.argv[1]))
PY
)" || { echo "Invalid MASTER_URL: $XFI_GUARD_CLUSTER_MASTER_URL" >&2; exit 1; }

python_env_tmp="$(mktemp)"
trap 'rm -f "$python_env_tmp"' EXIT
sed "s#^XFI_GUARD_CLUSTER_MASTER_URL=.*#XFI_GUARD_CLUSTER_MASTER_URL=$NORMALIZED_MASTER#" "$ENV_FILE" > "$python_env_tmp"
install -m 0600 "$python_env_tmp" "$ENV_FILE"
source "$ENV_FILE"

if ! command -v curl >/dev/null 2>&1; then
  echo "curl is required for Master health verification" >&2
  exit 1
fi
HEALTH_URL="${XFI_GUARD_CLUSTER_MASTER_URL%/}/health"
echo "Checking Cluster Master: $HEALTH_URL"
HEALTH="$(curl -fsS --max-time 10 -H "Authorization: Bearer ${XFI_GUARD_CLUSTER_TOKEN}" "$HEALTH_URL")" || {
  echo "Cluster Master is unavailable; VPS was NOT registered and Agent was NOT started." >&2
  exit 1
}
"$APP_DIR/.venv/bin/python" - "$HEALTH" <<'PY'
import json, sys
try:
    payload=json.loads(sys.argv[1])
except Exception as exc:
    raise SystemExit(f"Invalid Master /health JSON: {exc}")
if payload.get("ok") is not True:
    raise SystemExit("Master /health reports unhealthy")
print(f"Master healthy: nodes={payload.get('nodes', 0)} online={payload.get('online', 0)}")
PY

echo "Master accepted for Agent installation: $XFI_GUARD_CLUSTER_MASTER_URL"
chmod 0600 "$ENV_FILE"

sed "s#^WorkingDirectory=.*#WorkingDirectory=$APP_DIR#; s#^ExecStart=.*#ExecStart=$APP_DIR/.venv/bin/python -m xfi_guard.cluster_node#" "$UNIT_SRC" > "$UNIT"
chmod 0644 "$UNIT"
systemctl daemon-reload
HEARTBEAT_CHECK_START="$(date +%s)"
systemctl enable --now xfi-guard-cluster-node.service
systemctl restart xfi-guard-cluster-node.service

# A node is not considered connected until a NEW authenticated heartbeat has
# been accepted by the Master. Never use an old last_ok as proof of connection.
for _ in {1..15}; do
  if "$APP_DIR/.venv/bin/python" - "$HEARTBEAT_CHECK_START" <<'PY'
import json, sys
from pathlib import Path
try:
    last_ok=float(json.loads(Path("/var/lib/xfi-guard/node-state.json").read_text()).get("last_ok", 0))
except (OSError, ValueError, TypeError):
    last_ok=0
raise SystemExit(0 if last_ok > float(sys.argv[1]) else 1)
PY
  then
    echo "Cluster Node installed; Master: $XFI_GUARD_CLUSTER_MASTER_URL; authenticated heartbeat confirmed."
    exit 0
  fi
  sleep 1
done

echo "Agent started, but authenticated heartbeat did not succeed. VPS is NOT marked connected." >&2
systemctl --no-pager --full status xfi-guard-cluster-node.service || true
exit 1
