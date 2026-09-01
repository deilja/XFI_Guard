"""Safe remote VPS bootstrap via the local SSH identity/agent."""
from __future__ import annotations

import os
import shlex
import subprocess
from pathlib import Path

# Canonical XFI Guard cluster SSH identity shared by node enrollment and UI.
DEFAULT_IDENTITY_FILE = Path(os.path.expanduser("~/.ssh/xfi_guard_cluster_ed25519"))


def _local_cluster_settings() -> tuple[str, str, str]:
    """Read cluster credentials only on the XFI Guard controller during provisioning."""
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
    return master, secret, token


def bootstrap(host: str, user: str = "root", port: int = 22, timeout: int = 60,
              identity_file: str | None = None, *, node_id: str | None = None,
              cluster_master: str | None = None, cluster_secret: str | None = None,
              cluster_token: str | None = None) -> tuple[bool, str]:
    """Install/repair XFI Guard, protection stack and automatically enroll the VPS in the cluster."""
    if not host or any(c.isspace() for c in host):
        return False, "invalid host"
    if not 1 <= int(port) <= 65535:
        return False, "invalid port"
    target = f"{user}@{host}"

    local_master, local_secret, local_token = _local_cluster_settings()
    cluster_master = cluster_master or local_master
    cluster_secret = cluster_secret or local_secret
    cluster_token = cluster_token or local_token
    node_id = node_id or host
    cluster_enabled = bool(cluster_master and cluster_secret and node_id)

    remote = r'''set -Eeuo pipefail
export DEBIAN_FRONTEND=noninteractive

if command -v apt-get >/dev/null 2>&1; then
  apt-get update -qq
  apt-get install -y -qq git ca-certificates python3 python3-venv python3-pip fail2ban ufw
elif command -v dnf >/dev/null 2>&1; then
  dnf install -y git ca-certificates python3 python3-pip fail2ban firewalld
elif command -v yum >/dev/null 2>&1; then
  yum install -y git ca-certificates python3 python3-pip fail2ban
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
        remote += "cat > /etc/xfi-guard/cluster.env <<'XFI_CLUSTER_ENV'\n"
        remote += "XFI_GUARD_CLUSTER_MASTER_URL=" + shlex.quote(cluster_master) + "\n"
        remote += "XFI_GUARD_CLUSTER_SECRET=" + shlex.quote(cluster_secret) + "\n"
        remote += "XFI_GUARD_CLUSTER_TOKEN=" + shlex.quote(cluster_token or "") + "\n"
        remote += "XFI_GUARD_CLUSTER_NODE_ID=" + shlex.quote(node_id) + "\n"
        remote += "XFI_CLUSTER_ENV\nchmod 0600 /etc/xfi-guard/cluster.env\n"
        remote += "install -m 0644 systemd/xfi-guard-cluster-agent.service /etc/systemd/system/xfi-guard-cluster-agent.service\n"
    remote += r'''
systemctl daemon-reload
systemctl enable --now fail2ban
fail2ban-client reload >/dev/null 2>&1 || systemctl restart fail2ban
fail2ban-client status xfi-guard >/dev/null
systemctl enable --now xfi-guard.service
'''
    if cluster_enabled:
        remote += r'''systemctl enable --now xfi-guard-cluster-agent.service
sleep 3
cluster_state="$(systemctl is-active xfi-guard-cluster-agent.service || true)"
'''
    else:
        remote += "cluster_state=not-configured\n"
    remote += r'''sleep 2
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
                           timeout=int(timeout) + 30, check=False)
    except Exception as exc:
        return False, f"SSH error: {type(exc).__name__}: {exc}"
    output = (p.stdout + "\n" + p.stderr).strip()
    if p.returncode:
        return False, output[-3000:]
    return True, output[-3000:]
