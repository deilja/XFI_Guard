"""Safe orchestration for live inbound verification."""
from __future__ import annotations
from .xui_live_test import run_live_test
SUPPORTED={"vless","vmess","trojan","shadowsocks","socks","http","dokodemo-door","wireguard"}
def protocol_test_plan(inbound: dict)->dict:
    protocol=str(inbound.get("protocol","")).lower()
    return {"protocol":protocol,"supported":protocol in SUPPORTED,"requires_real_client":protocol in {"vless","vmess","trojan","shadowsocks","wireguard"},"transport_only":protocol in {"socks","http","dokodemo-door"}}
def execute(inbound: dict,command: list[str],timeout:int=30)->dict:
    plan=protocol_test_plan(inbound)
    if not plan["supported"]: return {"ok":False,"state":"INVALID","plan":plan}
    result=run_live_test(inbound,command,timeout)
    return {"ok":result["ok"],"state":"WORKING" if result["ok"] else "DOWN","plan":plan,"test":result}
