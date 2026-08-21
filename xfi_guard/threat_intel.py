"""Local threat-intelligence store for multi-VPS XFI Guard deployments."""
from __future__ import annotations

import ipaddress
import json
import os
import sqlite3
import time
from pathlib import Path

DB_PATH = Path(os.getenv("XFI_GUARD_THREAT_DB", "/var/lib/xfi-guard/threat-intel.db"))


def _ip(value: str) -> str:
    parsed = ipaddress.ip_address(str(value).strip())
    if parsed.version != 4 or parsed.is_private or parsed.is_loopback or parsed.is_multicast or parsed.is_reserved:
        raise ValueError("only public IPv4 addresses are accepted")
    return str(parsed)


def _connect():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("""CREATE TABLE IF NOT EXISTS threats (
        ip TEXT PRIMARY KEY, score INTEGER NOT NULL DEFAULT 0,
        risk TEXT NOT NULL DEFAULT 'low', events INTEGER NOT NULL DEFAULT 0,
        sources TEXT NOT NULL DEFAULT '[]', first_seen REAL NOT NULL,
        last_seen REAL NOT NULL, blocked_until REAL, blocked_by TEXT,
        origin_nodes TEXT NOT NULL DEFAULT '[]'
    )""")
    return db


def report(ip: str, node: str, score: int, risk: str, events: int = 1, source: str = "unknown") -> dict:
    ip = _ip(ip)
    now = time.time()
    node = str(node).strip()[:128] or "unknown"
    with _connect() as db:
        row = db.execute("SELECT * FROM threats WHERE ip=?", (ip,)).fetchone()
        nodes = set(json.loads(row["origin_nodes"]) if row else [])
        sources = set(json.loads(row["sources"]) if row else [])
        nodes.add(node); sources.add(str(source)[:128])
        old_score = int(row["score"]) if row else 0
        new_score = max(old_score, max(0, min(100, int(score))))
        total_events = (int(row["events"]) if row else 0) + max(0, int(events))
        if row:
            db.execute("UPDATE threats SET score=?,risk=?,events=?,sources=?,last_seen=?,origin_nodes=? WHERE ip=?",
                       (new_score, str(risk).lower(), total_events, json.dumps(sorted(sources)), now, json.dumps(sorted(nodes)), ip))
        else:
            db.execute("INSERT INTO threats(ip,score,risk,events,sources,first_seen,last_seen,origin_nodes) VALUES(?,?,?,?,?,?,?,?)",
                       (ip,new_score,str(risk).lower(),total_events,json.dumps(sorted(sources)),now,now,json.dumps(sorted(nodes))))
        return get(ip)


def mark_blocked(ip: str, node: str, until: float, actor: str = "xfi-guard") -> dict:
    ip = _ip(ip)
    with _connect() as db:
        db.execute("UPDATE threats SET blocked_until=?, blocked_by=? WHERE ip=?", (float(until), f"{node}:{actor}", ip))
    return get(ip)


def get(ip: str) -> dict:
    ip = _ip(ip)
    with _connect() as db:
        row = db.execute("SELECT * FROM threats WHERE ip=?", (ip,)).fetchone()
        if not row:
            return {}
        return dict(row) | {"sources": json.loads(row["sources"]), "origin_nodes": json.loads(row["origin_nodes"])}


def active(limit: int = 50) -> list[dict]:
    now = time.time()
    with _connect() as db:
        rows = db.execute("SELECT * FROM threats ORDER BY score DESC,last_seen DESC LIMIT ?", (max(1, min(limit, 500)),)).fetchall()
    result=[]
    for row in rows:
        item=dict(row) | {"sources": json.loads(row["sources"]), "origin_nodes": json.loads(row["origin_nodes"])}
        item["blocked"] = bool(item.get("blocked_until") and float(item["blocked_until"]) > now)
        result.append(item)
    return result
