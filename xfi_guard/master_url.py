"""Master URL normalization and safety checks for cluster nodes."""
from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlsplit, urlunsplit


def normalize_master_url(value: str) -> str:
    raw = str(value or "").strip()
    if not raw:
        raise ValueError("MASTER_URL is empty")
    if "://" not in raw:
        raw = "https://" + raw
    parsed = urlsplit(raw)
    if parsed.scheme.lower() not in {"http", "https"}:
        raise ValueError("MASTER_URL must use http or https")
    if not parsed.hostname:
        raise ValueError("MASTER_URL has no host")
    if parsed.username or parsed.password:
        raise ValueError("MASTER_URL must not contain credentials")
    if parsed.query or parsed.fragment:
        raise ValueError("MASTER_URL must not contain query or fragment")
    port = parsed.port
    host = parsed.hostname.lower().rstrip(".")
    if not host:
        raise ValueError("MASTER_URL has no host")
    netloc = f"[{host}]" if ":" in host else host
    if port is not None and not ((parsed.scheme.lower() == "http" and port == 80) or (parsed.scheme.lower() == "https" and port == 443)):
        netloc += f":{port}"
    path = parsed.path.rstrip("/")
    return urlunsplit((parsed.scheme.lower(), netloc, path, "", ""))


def master_host(value: str) -> str:
    return urlsplit(normalize_master_url(value)).hostname or ""


def _resolved_addresses(host: str) -> set[str]:
    try:
        return {item[4][0] for item in socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)}
    except OSError:
        return set()


def assert_master_not_this_vps(master_url: str, local_hostnames: set[str] | None = None) -> str:
    """Reject a Master URL that resolves to the current VPS."""
    normalized = normalize_master_url(master_url)
    host = master_host(normalized)
    names = {socket.gethostname().lower(), socket.getfqdn().lower()}
    if local_hostnames:
        names.update(str(x).strip().lower().rstrip(".") for x in local_hostnames if x)
    if host in names:
        raise ValueError(f"MASTER_URL points to this VPS: {host}")
    try:
        parsed = ipaddress.ip_address(host)
    except ValueError:
        parsed = None
    local_ips = _resolved_addresses(socket.gethostname()) | _resolved_addresses(socket.getfqdn())
    if parsed and str(parsed) in local_ips:
        raise ValueError(f"MASTER_URL points to this VPS IP: {host}")
    resolved_master_ips = _resolved_addresses(host)
    if resolved_master_ips & local_ips:
        raise ValueError(f"MASTER_URL resolves to this VPS: {host}")
    return normalized
