"""One-time SSH password bootstrap for VPS enrollment.

The password is supplied only in memory via SSHPASS. It is never written to
config.toml, logs, command arguments, or the node database. After the first
successful login an ed25519 key is installed for future use.
"""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path


def bootstrap_with_password(host: str, user: str, port: int, password: str, timeout: int = 30) -> tuple[bool, str]:
    if not password:
        return False, "SSH пароль пустой"
    if not shutil.which("sshpass"):
        return False, "sshpass не установлен. Установите пакет sshpass."
    if not host or any(c.isspace() for c in host) or ":" in host or not user or any(c.isspace() for c in user):
        return False, "Некорректный SSH host/user; host должен быть без :port"
    if not 1 <= int(port) <= 65535:
        return False, "Некорректный SSH порт"

    ssh_dir = Path(os.path.expanduser("~/.ssh"))
    ssh_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    key = ssh_dir / "xfi_guard_cluster_ed25519"
    pub = Path(str(key) + ".pub")
    if not key.exists():
        p = subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(key)], text=True, capture_output=True, timeout=10, check=False)
        if p.returncode != 0:
            return False, (p.stderr or "ssh-keygen failed")[:500]
    if not pub.exists():
        return False, "Не найден публичный SSH ключ"

    env = os.environ.copy()
    env["SSHPASS"] = password
    target = f"{user}@{host}"
    ssh_options = ["-o", "StrictHostKeyChecking=accept-new", "-o", "ConnectTimeout=10", "-p", str(port)]
    remote = "mkdir -p ~/.ssh && chmod 700 ~/.ssh && touch ~/.ssh/authorized_keys && chmod 600 ~/.ssh/authorized_keys && cat >> ~/.ssh/authorized_keys"
    try:
        with pub.open("r", encoding="utf-8") as fh:
            command = ["sshpass", "-e", "ssh", *ssh_options, target, remote]
            p = subprocess.run(command, stdin=fh, text=True, capture_output=True, timeout=timeout, env=env, check=False)
        if p.returncode != 0:
            return False, (p.stderr or p.stdout or "SSH password authentication failed")[-1200:]
        subprocess.run(["chmod", "600", str(key)], check=False)
        test = [
            "ssh", "-i", str(key), "-o", "IdentitiesOnly=yes", "-o", "BatchMode=yes",
            "-o", "StrictHostKeyChecking=yes", "-o", "ConnectTimeout=10", "-p", str(port), target, "true",
        ]
        verify = subprocess.run(test, text=True, capture_output=True, timeout=timeout, check=False)
        if verify.returncode != 0:
            return False, (verify.stderr or "SSH key verification failed")[-1200:]
        return True, "SSH ключ установлен. Пароль больше не требуется."
    except Exception as exc:
        return False, f"{type(exc).__name__}: {exc}"
    finally:
        env["SSHPASS"] = ""
