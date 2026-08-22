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
if [[ ! -f "$UNIT_SRC" ]]; then
  echo "Cluster Master service template not found: $UNIT_SRC" >&2
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
XFI_GUARD_CLUSTER_TIMEOUT=5
EOF
fi

# Do not leave a newly installed Master unauthenticated.
# Existing non-empty credentials are preserved.
if ! grep -q '^XFI_GUARD_CLUSTER_TOKEN=..*' "$ENV_FILE"; then
  TOKEN=""
  if command -v openssl >/dev/null 2>&1; then
    TOKEN="$(openssl rand -hex 32)"
  else
    TOKEN="$(python3 - <<'PY'
import secrets
print(secrets.token_hex(32))
PY
)"
  fi
  sed -i "s/^XFI_GUARD_CLUSTER_TOKEN=.*/XFI_GUARD_CLUSTER_TOKEN=$TOKEN/" "$ENV_FILE"
  echo "Generated XFI_GUARD_CLUSTER_TOKEN."
fi

if ! grep -q '^XFI_GUARD_CLUSTER_SECRET=..*' "$ENV_FILE"; then
  SECRET=""
  if command -v openssl >/dev/null 2>&1; then
    SECRET="$(openssl rand -hex 32)"
  else
    SECRET="$(python3 - <<'PY'
import secrets
print(secrets.token_hex(32))
PY
)"
  fi
  sed -i "s/^XFI_GUARD_CLUSTER_SECRET=.*/XFI_GUARD_CLUSTER_SECRET=$SECRET/" "$ENV_FILE"
  echo "Generated XFI_GUARD_CLUSTER_SECRET."
fi

chmod 0600 "$ENV_FILE"

# Materialize the service with the actual installation directory.
sed "s#^WorkingDirectory=.*#WorkingDirectory=$APP_DIR#; s#^ExecStart=.*#ExecStart=$APP_DIR/.venv/bin/python -m xfi_guard.cluster_master#" "$UNIT_SRC" > "$UNIT_DST"
chmod 0644 "$UNIT_DST"
systemctl daemon-reload
systemctl enable --now xfi-guard-multi-vps-master.service

sleep 1
systemctl --no-pager --full status xfi-guard-multi-vps-master.service || true

if command -v curl >/dev/null 2>&1; then
  # Source only the two generated credentials; do not print them.
  set -a
  # shellcheck disable=SC1090
  source "$ENV_FILE"
  set +a
  echo "\nCluster Master health:"
  if curl -fsS --max-time "${XFI_GUARD_CLUSTER_TIMEOUT:-5}" \
      -H "Authorization: Bearer ${XFI_GUARD_CLUSTER_TOKEN}" \
      "http://${XFI_GUARD_CLUSTER_HOST}:${XFI_GUARD_CLUSTER_PORT}/health"; then
    echo
  else
    echo "Cluster Master health check failed." >&2
    exit 1
  fi
fi

echo "Cluster Master installed: xfi-guard-multi-vps-master.service"
echo "Configuration: $ENV_FILE"
