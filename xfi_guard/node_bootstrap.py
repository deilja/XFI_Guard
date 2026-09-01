"""Safe remote VPS bootstrap via the local SSH identity/agent."""
from __future__ import annotations

import os
import shlex
import subprocess
from pathlib import Path

DEFAULT_IDENTITY_FILE = Path(os.path.expanduser("~/.ssh/xfi_guard_cluster_ed25519"))


def _local_cluster_settings() -> tuple[str, str, str, str]:
    """Read cluster credentials and explicit TLS mode only on the controller."""
    try:
        import tomllib
        path = Path(os.getenv("XFI_GUARD_CONFIG", "/opt/xfi-guard/config.toml"))
        data = tomllib.loads(path.read_text(encoding="utf-8"))
        cluster = data.get("cluster", {}) or {}
    except (OSError, ValueError, tomllib.TOMLDecodeError):
        cluster = {}
    master = str(cluster.get("master_url", "") or os.getenv("XFI_GUARD_CLUSTER_MASTER_URL", "")).strip()
    secret = str(cluster.get("secret", "") or os.getenv("XFI_GUARD_CLUSTER_SECRET", "")).strip()
    token = str(cluster.get("token", "") or os.getenv("XFI_GUARD_CLUSTER_TOKEN", "")).strip()
    insecure = str(cluster.get("tls_insecure", "") or os.getenv("XFI_GUARD_CLUSTER_TLS_INSECURE", "")).strip().lower()
    return master, secret, token, insecure


def bootstrap(host: str, user: str = "root", port: int = 22, timeout: int = 60,
              identity_file: str | None = None, *, node_id: str | None = None,
              cluster_master: str | None = None, cluster_secret: str | None = None,
              cluster_token: str | None = None) -> tuple[bool, str]:
    """Install/repair XFI Guard and enroll a VPS only after a real Master heartbeat."""
    if not host or any(c.isspace() for c in host):
        return False, "invalid host"
    if not 1 <= int(port) <= 65535:
        return False, "invalid port"
    target = f"{user}@{host}"

    local_master, local_secret, local_token, local_insecure = _local_cluster_settings()
    cluster_master = cluster_master or local_master
    cluster_secret = cluster_secret or local_secret
    cluster_token = cluster_token or local_token
    node_id = node_id or host
    cluster_enabled = bool(cluster_master and cluster_secret and cluster_token and node_id)

    remote = r'''set -Eeuo pipefail
export DEBIAN_FRONTEND=noninteractive

if command -v apt-get >/dev/null 2>&1; then
  apt-get update -qq
  apt-get install -y -qq git ca-certificates python3 python3-venv python3-pip fail2ban ufw curl
elif command -v dnf >/dev/null 2>&1; then
  dnf install -y git ca-certificates python3 python3-pip fail2ban firewalld curl
elif command -v yum >/dev/null 2>&1; then
  yum install -y git ca-certificates python3 python3-pip fail2ban curl
else
  echo 'UNSUPPORTED_PACKAGE_MANAGER'
  exit 30
fi

INSTALL_DIR=/opt/xfi-guard
CONFIG_BACKUP=$(mktemp)
trap 'rm -f "$CONFIG_BACKUP"' EXIT
if [ -f "$INSTALL_DIR/config.toml" ]; then cp -a "$INSTALL_DIR/config.toml" "$CONFIG_BACKUP"; fi

mkdir -p /var/log/xfi-guard /var/lib/xfi-guard /etc/xfi-guard
chmod 0755 /var/log/xfi-guard
chmod 0700 /var/lib/xfi-guard /etc/xfi-guard

if [ -d "$INSTALL_DIR/.git" ]; then
  git -C "$INSTALL_DIR" fetch --all --prune
  git -C "$INSTALL_DIR" reset --hard origin/main
else
  rm -rf "$INSTALL_DIR"
  git clone --depth 1 https://github.com/deilja/XFI_Guard.git "$INSTALL_DIR"
fi

if [ -s "$CONFIG_BACKUP" ]; then cp -a "$CONFIG_BACKUP" "$INSTALL_DIR/config.toml"; fi
cd "$INSTALL_DIR"
python3 -m venv "$INSTALL_DIR/.venv"
"$INSTALL_DIR/.venv/bin/python" -m pip install -q --upgrade pip
"$INSTALL_DIR/.venv/bin/pip" install -q --upgrade .

install -m 0644 config/fail2ban/filter.d/xfi-guard.conf /etc/fail2ban/filter.d/xfi-guard.conf
install -m 0644 config/fail2ban/jail.d/xfi-guard.conf /etc/fail2ban/jail.d/xfi-guard.conf
touch /var/log/xfi-guard/fail2ban-sync.log
chmod 0640 /var/log/xfi-guard/fail2ban-sync.log

ufw_state=inactive
if command -v ufw >/dev/null 2>&1; then
  ufw_state="$(ufw status | awk 'NR==1 {print tolower($2)}')"
  if [ "$ufw_state" = active ]; then
    ufw allow "${SSH_PORT:-22}/tcp" >/dev/null || true
  fi
fi

install -m 0644 systemd/xfi-guard.service /etc/systemd/system/xfi-guard.service
'''
    if cluster_enabled:
        remote += "\n# XFI Guard cluster enrollment\n"
        remote += "CLUSTER_MASTER=" + shlex.quote(cluster_master) + "\n"
        remote += "CLUSTER_SECRET=" + shlex.quote(cluster_secret) + "\n"
        remote += "CLUSTER_TOKEN=" + shlex.quote(cluster_token) + "\n"
        remote += "CLUSTER_NODE_ID=" + shlex.quote(node_id) + "\n"
        remote += "CLUSTER_TLS_INSECURE=" + shlex.quote(local_insecure) + "\n"
        remote += r'''
python3 - <<'PY'
import json, os, ssl, urllib.request
master=os.environ.get("CLUSTER_MASTER", "").rstrip("/")
token=os.environ.get("CLUSTER_TOKEN", "")
insecure=os.environ.get("CLUSTER_TLS_INSECURE", "").lower() in {"1", "true", "yes"}
if not master or not token:
    raise SystemExit("CLUSTER_MASTER and CLUSTER_TOKEN are required")
req=urllib.request.Request(master + "/health", headers={"Authorization": "Bearer " + token})
context=ssl._create_unverified_context() if insecure and master.lower().startswith("https://") else None
try:
    with urllib.request.urlopen(req, timeout=10, context=context) as response:
        data=json.loads(response.read().decode())
except ssl.SSLCertVerificationError as exc:
    raise SystemExit("CLUSTER_MASTER_TLS_VERIFY_FAILED: Master uses an untrusted certificate. Configure a trusted CA or explicitly set XFI_GUARD_CLUSTER_TLS_INSECURE=1 on the controller.") from exc
if data.get("ok") is not True:
    raise SystemExit("Cluster Master /health is not healthy")
print("CLUSTER_MASTER_HEALTHY")
PY
cat > /etc/xfi-guard/cluster.env <<XFI_CLUSTER_ENV
XFI_GUARD_CLUSTER_MASTER_URL=$CLUSTER_MASTER
XFI_GUARD_CLUSTER_SECRET=$CLUSTER_SECRET
XFI_GUARD_CLUSTER_TOKEN=$CLUSTER_TOKEN
XFI_GUARD_CLUSTER_NODE_ID=$CLUSTER_NODE_ID
XFI_GUARD_CLUSTER_TLS_INSECURE=$CLUSTER_TLS_INSECURE
XFI_CLUSTER_ENV
chmod 0600 /etc/xfi-guard/cluster.env
install -m 0644 systemd/xfi-guard-cluster-agent.service /etc/systemd/system/xfi-guard-cluster-agent.service
'''
    else:
        remote += "\ncluster_enabled=false\n"
    remote += r'''
systemctl daemon-reload
systemctl enable --now fail2ban
fail2ban-client reload >/dev/null 2>&1 || systemctl restart fail2ban
fail2ban-client status xfi-guard >/dev/null
systemctl enable --now xfi-guard.service
'''
    if cluster_enabled:
        remote += r'''
systemctl enable --now xfi-guard-cluster-agent.service
sleep 2
cluster_state="$(systemctl is-active xfi-guard-cluster-agent.service || true)"
if [ "$cluster_state" != "active" ]; then
  echo "CLUSTER_AGENT_NOT_ACTIVE"
  systemctl --no-pager --full status xfi-guard-cluster-agent.service || true
  exit 41
fi

# Registration success is defined by a NEW heartbeat visible on the Master.
heartbeat_ok=false
for _ in $(seq 1 15); do
  if CLUSTER_MASTER="$CLUSTER_MASTER" CLUSTER_TOKEN="$CLUSTER_TOKEN" CLUSTER_NODE_ID="$CLUSTER_NODE_ID" CLUSTER_TLS_INSECURE="$CLUSTER_TLS_INSECURE" python3 - <<'PY'
import json, os, ssl, urllib.request
master=os.environ["CLUSTER_MASTER"].rstrip("/")
token=os.environ["CLUSTER_TOKEN"]
node_id=os.environ["CLUSTER_NODE_ID"]
insecure=os.environ.get("CLUSTER_TLS_INSECURE", "").lower() in {"1", "true", "yes"}
req=urllib.request.Request(master + "/nodes", headers={"Authorization": "Bearer " + token})
context=ssl._create_unverified_context() if insecure and master.lower().startswith("https://") else None
with urllib.request.urlopen(req, timeout=10, context=context) as response:
    data=json.loads(response.read().decode())
for node in data.get("nodes", []):
    if node.get("name") == node_id and node.get("online") is True:
        raise SystemExit(0)
raise SystemExit(1)
PY
  then
    heartbeat_ok=true
    break
  fi
  sleep 2
done
if [ "$heartbeat_ok" != true ]; then
  echo "CLUSTER_HEARTBEAT_NOT_CONFIRMED"
  echo "Agent is active, but Master did not confirm a fresh heartbeat; VPS is NOT registered successfully."
  exit 42
fi
'''
    else:
        remote += "cluster_state=not-configured\n"
    remote += r'''
sleep 2
xfi_state="$(systemctl is-active xfi-guard.service || true)"
f2b_state="$(systemctl is-active fail2ban.service || true)"
jail_state="$(fail2ban-client status xfi-guard 2>/dev/null | awk '/Currently banned:/ {print $NF}' || true)"
printf 'XFI_GUARD_PROVISION_OK\n'
printf 'XFI_GUARD=%s\n' "$xfi_state"
printf 'FAIL2BAN=%s\n' "$f2b_state"
printf 'XFI_JAIL_BANNED=%s\n' "${jail_state:-0}"
printf 'UFW=%s\n' "$ufw_state"
printf 'CLUSTER_AGENT=%s\n' "$cluster_state"
printf 'SSH_PORT=%s\n' "${SSH_PORT:-22}"
if [ "$ufw_state" = inactive ]; then
  printf 'UFW_NOTE=installed_but_left_disabled_to_preserve_unknown_VPN_panel_ports\n'
fi
'''
    if cluster_enabled:
        prefix = (
            "export CLUSTER_MASTER=" + shlex.quote(cluster_master) + "\n"
            "export CLUSTER_SECRET=" + shlex.quote(cluster_secret) + "\n"
            "export CLUSTER_TOKEN=" + shlex.quote(cluster_token) + "\n"
            "export CLUSTER_NODE_ID=" + shlex.quote(node_id) + "\n"
            "export CLUSTER_TLS_INSECURE=" + shlex.quote(local_insecure) + "\n"
        )
        remote = prefix + remote
    cmd = ["ssh"]
    if identity_file:
        identity = Path(os.path.expanduser(identity_file))
        if not identity.is_file():
            return False, f"SSH identity file not found: {identity}"
        cmd += ["-i", str(identity), "-o", "IdentitiesOnly=yes"]
    cmd += ["-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=yes",
            "-o", f"ConnectTimeout={min(int(timeout), 60)}", "-p", str(int(port)),
            target, "bash", "-s"]
    try:
        p = subprocess.run(cmd, input=remote, text=True, capture_output=True,
                           timeout=int(timeout) + 60, check=False)
    except Exception as exc:
        return False, f"SSH error: {type(exc).__name__}: {exc}"
    output = (p.stdout + "\n" + p.stderr).strip()
    if p.returncode:
        return False, output[-3000:]
    return True, output[-3000:]
