"""Bot-safe VPS node management backed by config.toml."""
from __future__ import annotations

import ipaddress
import os
import re
import tomllib
from pathlib import Path

DEFAULT_PATH = Path(os.getenv("XFI_GUARD_CONFIG", "/opt/xfi-guard/config.toml"))


def _valid_host(value: str) -> bool:
    value = value.strip()
    if not value or len(value) > 253 or any(c in value for c in " /\\\t\r\n"):
        return False
    try:
        ipaddress.ip_address(value)
        return True
    except ValueError:
        return bool(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9.-]*", value))


def _load(path: Path) -> list[dict]:
    if not path.exists():
        return []
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    return [dict(x) for x in data.get("nodes", []) if isinstance(x, dict)]


def _quote(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def add_node(name: str, host: str, user: str = "root", port: int = 22, path: str | Path = DEFAULT_PATH) -> tuple[bool, str]:
    name, host, user = name.strip(), host.strip(), user.strip() or "root"
    try: port = int(port)
    except (TypeError, ValueError): return False, "SSH порт должен быть числом"
    if not re.fullmatch(r"[A-Za-z0-9_.-]{1,64}", name): return False, "Некорректное имя узла"
    if not _valid_host(host): return False, "Некорректный IP/DNS"
    if not re.fullmatch(r"[A-Za-z0-9_.@-]{1,64}", user): return False, "Некорректный SSH пользователь"
    if not 1 <= port <= 65535: return False, "Некорректный SSH порт"
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    nodes = _load(p)
    if any(str(n.get("name", "")) == name for n in nodes): return False, "Узел с таким именем уже существует"
    with p.open("a", encoding="utf-8") as f:
        if p.stat().st_size and not p.read_text(encoding="utf-8").endswith("\n"): f.write("\n")
        f.write("[[nodes]]\n")
        f.write(f"name = {_quote(name)}\n")
        f.write(f"host = {_quote(host)}\n")
        f.write(f"user = {_quote(user)}\n")
        f.write(f"port = {port}\n")
        f.write("enabled = true\n\n")
    return True, name


def remove_node(name: str, path: str | Path = DEFAULT_PATH) -> tuple[bool, str]:
    p = Path(path)
    if not p.exists(): return False, "Конфигурация не найдена"
    text = p.read_text(encoding="utf-8")
    lines = text.splitlines(keepends=True)
    out, i, removed = [], 0, False
    while i < len(lines):
        if lines[i].strip() == "[[nodes]]":
            start = i; i += 1
            while i < len(lines) and lines[i].strip() != "[[nodes]]": i += 1
            block = lines[start:i]
            if any(x.strip() == f'name = "{name}"' for x in block): removed = True; continue
            out.extend(block); continue
        out.append(lines[i]); i += 1
    if not removed: return False, "Узел не найден"
    p.write_text("".join(out), encoding="utf-8")
    return True, name


def list_node_names(path: str | Path = DEFAULT_PATH) -> list[str]:
    return [str(x.get("name")) for x in _load(Path(path)) if x.get("name")]
