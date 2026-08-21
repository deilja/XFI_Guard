#!/usr/bin/env bash
set -euo pipefail

if command -v sshpass >/dev/null 2>&1; then
  echo "sshpass: already installed"
  exit 0
fi

export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y --no-install-recommends sshpass
sshpass -V
