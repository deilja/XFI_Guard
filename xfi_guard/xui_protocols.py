"""Protocol profiles and safe post-create verification for 3X-UI 3.6.0."""
from __future__ import annotations
import json, secrets, uuid
from dataclasses import dataclass
PROTOCOLS=("vless","vmess","trojan","shadowsocks","socks","http","dokodemo-door","wireguard")
@dataclass(frozen=True)
class ProtocolProfile:
    protocol:str; port:int; remark:str; settings:dict; stream_settings:dict
def supported_protocols(): return list(PROTOCOLS)
def _port(port):
    port=int(port)
    if not 1<=port<=65535: raise ValueError("port must be 1..65535")
    return port
def build_profile(protocol,port,remark=None,security="none",server_name=None):
    protocol=protocol.lower().strip()
    if protocol not in PROTOCOLS: raise ValueError(f"unsupported protocol: {protocol}")
    port=_port(port); remark=remark or f"XFI-{protocol}-{port}"; client_id=str(uuid.uuid4())
    if protocol in ("vless","vmess"): settings={"clients":[{"id":client_id,"email":remark}]}
    elif protocol=="trojan": settings={"clients":[{"password":secrets.token_urlsafe(24),"email":remark}]}
    elif protocol=="shadowsocks": settings={"method":"2022-blake3-aes-128-gcm","password":secrets.token_urlsafe(24),"network":"tcp,udp"}
    elif protocol in ("socks","http"): settings={"auth":"password","accounts":[{"user":"xfi","pass":secrets.token_urlsafe(18)}],"udp":protocol=="socks"}
    elif protocol=="dokodemo-door": settings={"address":"127.0.0.1","port":port,"network":"tcp,udp"}
    else: settings={"secretKey":"GENERATE_ON_SERVER","peers":[]}
    stream={"network":"tcp","security":security}
    if security=="tls": stream["tlsSettings"]={"serverName":server_name or "localhost"}
    return ProtocolProfile(protocol,port,remark,settings,stream)
def validate_profile(profile):
    errors=[]
    if profile.protocol not in PROTOCOLS: errors.append("unsupported_protocol")
    if not 1<=profile.port<=65535: errors.append("invalid_port")
    security=profile.stream_settings.get("security")
    if security not in ("none","tls","reality"): errors.append("invalid_security")
    if security=="tls" and not profile.stream_settings.get("tlsSettings"): errors.append("missing_tls_settings")
    return {"ok":not errors,"errors":errors}
def to_xui_payload(profile):
    check=validate_profile(profile)
    if not check["ok"]: raise ValueError(",".join(check["errors"]))
    return {"remark":profile.remark,"enable":True,"port":profile.port,"protocol":profile.protocol,"settings":json.dumps(profile.settings,separators=(",",":")),"streamSettings":json.dumps(profile.stream_settings,separators=(",",":")),"sniffing":json.dumps({"enabled":True,"destOverride":["http","tls","quic"]},separators=(",",":"))}
def verify_result(result):
    checks=result.get("checks",[]); api=any(x.get("name")=="api" and x.get("ok") for x in checks); tcp=any(x.get("name")=="tcp" and x.get("ok") for x in checks); tls=[x for x in checks if x.get("name")=="tls"]
    ready=api and tcp and (not tls or tls[0].get("ok",False))
    return {"protocol":result.get("protocol"),"api":api,"tcp":tcp,"tls":tls[0].get("ok") if tls else None,"protocol_ready":ready,"state":"HEALTHY" if ready else "DOWN"}
