"""Persistent, root-readable 3X-UI API profiles."""
from __future__ import annotations

import json
import os
from pathlib import Path
from urllib.parse import urlparse

DEFAULT_PATH = "/var/lib/xfi-guard/xui_api.json"


def _valid_url(value: str) -> bool:
    parsed = urlparse(value.strip())
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def load(path: str = DEFAULT_PATH) -> list[dict]:
    p = Path(path)
    if not p.is_file():
        return []
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(raw, list):
        return []
    return [x for x in raw if isinstance(x, dict) and x.get("name") and _valid_url(str(x.get("url", "")))]


def save(items: list[dict], path: str = DEFAULT_PATH) -> None:
    clean = []
    for item in items:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name", "")).strip()
        url = str(item.get("url", "")).strip().rstrip("/")
        token = str(item.get("token", "")).strip()
        if name and _valid_url(url):
            clean.append({"name": name[:80], "url": url, "token": token})
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(clean, ensure_ascii=False, indent=2), encoding="utf-8")
    os.chmod(p, 0o600)


def upsert(name: str, url: str, token: str, path: str = DEFAULT_PATH) -> dict:
    name = name.strip()
    url = url.strip().rstrip("/")
    token = token.strip()
    if not name:
        raise ValueError("Имя узла не задано")
    if not _valid_url(url):
        raise ValueError("URL должен начинаться с http:// или https://")
    items = load(path)
    item = {"name": name[:80], "url": url, "token": token}
    items = [x for x in items if x.get("name") != name]
    items.append(item)
    save(items, path)
    return item


def remove(name: str, path: str = DEFAULT_PATH) -> bool:
    items = load(path)
    new = [x for x in items if x.get("name") != name]
    changed = len(new) != len(items)
    if changed:
        save(new, path)
    return changed


def get(name: str, path: str = DEFAULT_PATH) -> dict | None:
    return next((x for x in load(path) if x.get("name") == name), None)
