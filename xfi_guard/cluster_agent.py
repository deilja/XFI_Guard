"""Lightweight Multi-VPS cluster agent."""
from __future__ import annotations

import argparse
import json
import logging
import os
import time
import urllib.request

from .cluster import make_event, register_global_block
from .cluster_apply import fail2ban_block
from .firewall import list_blocked_ips

LOG = logging.getLogger("xfi_guard.cluster_agent")


def _post(url: str, payload: dict, token: str = "") -> dict:
    body = json.dumps(payload).encode()
    headers = {"Content-Type": "application/json"}
    if token: headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, body, method="POST", headers=headers)
    with urllib.request.urlopen(req, timeout=10) as response:
        return json.loads(response.read().decode())


def heartbeat(master: str, node: str, secret: str, token: str = "") -> dict:
    payload = {"node": node, "timestamp": time.time(), "status": "online", "blocked": list_blocked_ips()[:500]}
    payload["event"] = make_event("1.1.1.1", node, 0, "info", 0, "heartbeat", secret)
    return _post(master.rstrip("/") + "/heartbeat", payload, token)


def publish(master: str, node: str, secret: str, threat: dict, token: str = "") -> dict:
    event = make_event(threat["ip"], node, threat.get("score", 0), threat.get("risk", "low"), threat.get("events", 1), "xfi-guard", secret)
    return _post(master.rstrip("/") + "/threat", event, token)


def apply_commands(commands: list[dict]) -> int:
    count = 0
    for command in commands:
        if command.get("action") != "block": continue
        ip = command.get("ip"); until = float(command.get("until", 0))
        if not ip or until <= time.time(): continue
        ok, detail = fail2ban_block(ip)
        if ok:
            register_global_block(ip, command.get("source_node", "cluster"), until)
            count += 1
            LOG.warning("cluster block applied via Fail2Ban: ip=%s source=%s", ip, command.get("source_node", "cluster"))
        else:
            LOG.error("cluster Fail2Ban block failed: ip=%s error=%s", ip, detail)
    return count


def run(config: dict) -> None:
    cluster = config.get("cluster", {})
    if not cluster.get("enabled"):
        LOG.info("Multi-VPS cluster disabled"); return
    master = cluster.get("master_url")
    secret = os.getenv("XFI_GUARD_CLUSTER_SECRET", cluster.get("secret", ""))
    node = cluster.get("node_id", os.uname().nodename)
    token = os.getenv("XFI_GUARD_CLUSTER_TOKEN", cluster.get("token", ""))
    if not master or not secret or secret == "CHANGE_ME_TO_A_LONG_RANDOM_SECRET":
        raise RuntimeError("cluster requires master_url and a non-default secret")
    interval = max(15, int(cluster.get("heartbeat_interval", 30)))
    while True:
        try:
            response = heartbeat(master, node, secret, token)
            applied = apply_commands(response.get("commands", []))
            LOG.debug("cluster heartbeat sent: %s; blocks applied=%s", node, applied)
        except Exception as exc:
            LOG.warning("cluster heartbeat failed: %s", exc)
        time.sleep(interval)


def main() -> None:
    parser = argparse.ArgumentParser(); parser.add_argument("--config", default="/opt/xfi-guard/config.toml")
    args = parser.parse_args()
    import tomllib
    with open(args.config, "rb") as fh: config = tomllib.load(fh)
    logging.basicConfig(level=os.getenv("XFI_GUARD_LOG_LEVEL", "INFO")); run(config)


if __name__ == "__main__": main()
