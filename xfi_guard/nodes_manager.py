"""Admin-managed VPS node configuration.

Only host/user/port/name are stored. SSH authentication remains delegated to
OpenSSH agent/config/known_hosts; XFI Guard never stores private keys or passwords.
"""
from __future__ import annotations

import ipaddress
import os
import re
import tempfile
from pathlib import Path

import tomllib

CONFIG_PATH = Path(os.getenv("XFI_GUARD_CONFIG", "/opt/xfi-guard/config.toml"))


def _valid_name(value: str) -> bool:
    return bool(re.fullmatch(r"[A-Za-z0-9_.-]{1,64}", value))


def _normalize_host_port(host: str, port: int = 22) -> tuple[str, int]:
    """Normalize legacy host values such as 2.27.37.78:22.

    Older configurations could accidentally store the SSH port inside `host`.
    SSH and ssh-keyscan must receive the hostname and port as separate values.
    """
    host = str(host or "").strip()
    try:
        port = int(port)
    except (TypeError, ValueError):
        port = 22

    m = re.fullmatch(r"\[([^\]]+)\]:(\d{1,5})", host)
    if m:
        return m.group(1), int(m.group(2))

    if host.count(":") == 1:
        candidate, candidate_port = host.rsplit(":", 1)
        if candidate_port.isdigit() and 1 <= int(candidate_port) <= 65535:
            return candidate, int(candidate_port)

    return host, port


def _valid_host(value: str) -> bool:
    if len(value) > 253 or any(c in value for c in " /\\\t\r\n"):
        return False
    try:
        ipaddress.ip_address(value)
        return True
    except ValueError:
        return bool(re.fullmatch(r"[A-Za-z0-9_.:-]+", value))


def _load() -> dict:
    if not CONFIG_PATH.exists():
        return {}
    return tomllib.loads(CONFIG_PATH.read_text(encoding="utf-8"))


def list_configured_nodes() -> list[dict]:
    result: list[dict] = []
    for raw in (_load().get("nodes", []) or []):
        if not isinstance(raw, dict):
            continue
        node = dict(raw)
        host, port = _normalize_host_port(node.get("host", ""), node.get("port", 22))
        node["host"] = host
        node["port"] = port
        result.append(node)
    return result


def add_node(name: str, host: str, user: str = "root", port: int = 22) -> None:
    name, host, user = name.strip(), host.strip(), user.strip() or "root"
    host, port = _normalize_host_port(host, port)
    if not _valid_name(name):
        raise ValueError("Имя VPS: только A-Z, a-z, 0-9, _, ., -; максимум 64 символа")
    if not _valid_host(host):
        raise ValueError("Некорректный IP/DNS")
    if not re.fullmatch(r"[A-Za-z0-9_.@-]{1,64}", user):
        raise ValueError("Некорректный SSH пользователь")
    if not 1 <= int(port) <= 65535:
        raise ValueError("SSH порт должен быть от 1 до 65535")
    nodes = list_configured_nodes()
    if any(str(n.get("name")) == name for n in nodes):
        raise ValueError(f"VPS с именем {name} уже существует")
    block = f"\n[[nodes]]\nname = {name!r}\nhost = {host!r}\nuser = {user!r}\nport = {int(port)}\nenabled = true\n"
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    old = CONFIG_PATH.read_text(encoding="utf-8") if CONFIG_PATH.exists() else ""
    fd, tmp = tempfile.mkstemp(prefix="config.toml.", dir=str(CONFIG_PATH.parent), text=True)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(old.rstrip() + block)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, CONFIG_PATH)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def remove_node(name: str) -> None:
    name = name.strip()
    text = CONFIG_PATH.read_text(encoding="utf-8")
    lines = text.splitlines(keepends=True)
    starts = [i for i, line in enumerate(lines) if line.strip() == "[[nodes]]"]
    for pos, start in reversed(list(enumerate(starts))):
        end = starts[pos + 1] if pos + 1 < len(starts) else len(lines)
        block = "".join(lines[start:end])
        if re.search(r"^name\s*=\s*[\"']" + re.escape(name) + r"[\"']\s*$", block, re.M):
            del lines[start:end]
            CONFIG_PATH.write_text("".join(lines).rstrip() + "\n", encoding="utf-8")
            return
    raise ValueError(f"VPS {name} не найден")
