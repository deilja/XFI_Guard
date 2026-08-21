#!/usr/bin/env bash
set -euo pipefail

# Privileged helper for the one-time VPS password bootstrap.
# The Telegram bot must not execute arbitrary package-manager commands.

if [[ "${EUID}" -ne 0 ]]; then
  echo "Run as root: sudo bash scripts/install_sshpass.sh" >&2
  exit 1
fi

if command -v sshpass >/dev/null 2>&1; then
  echo "sshpass: already installed at $(command -v sshpass)"
  exit 0
fi

if ! command -v apt-get >/dev/null 2>&1; then
  echo "apt-get is required to install sshpass automatically" >&2
  exit 2
fi

export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y --no-install-recommends sshpass

command -v sshpass >/dev/null 2>&1
echo "sshpass installed at $(command -v sshpass)"
