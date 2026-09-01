from __future__ import annotations

import socket

import pytest

from xfi_guard.master_url import assert_master_not_this_vps, normalize_master_url


def test_normalize_master_url_adds_https_and_strips_trailing_slash():
    assert normalize_master_url("MASTER.EXAMPLE:443/") == "https://master.example"
    assert normalize_master_url("http://master.example:8765///") == "http://master.example:8765"


def test_normalize_master_url_rejects_unsafe_forms():
    with pytest.raises(ValueError):
        normalize_master_url("ftp://master.example")
    with pytest.raises(ValueError):
        normalize_master_url("https://user:pass@master.example")
    with pytest.raises(ValueError):
        normalize_master_url("https://master.example/?x=1")


def test_master_must_not_be_this_vps(monkeypatch):
    monkeypatch.setattr(socket, "gethostname", lambda: "ger")
    monkeypatch.setattr(socket, "getfqdn", lambda: "ger.example")
    with pytest.raises(ValueError, match="this VPS"):
        assert_master_not_this_vps("https://ger:8765")


def test_external_master_is_accepted(monkeypatch):
    monkeypatch.setattr(socket, "gethostname", lambda: "ger")
    monkeypatch.setattr(socket, "getfqdn", lambda: "ger.example")

    def fake_getaddrinfo(host, *args, **kwargs):
        ip = "198.51.100.10" if host in {"ger", "ger.example"} else "203.0.113.10"
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, 0))]

    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)
    assert assert_master_not_this_vps("fin.example:8765") == "https://fin.example:8765"
