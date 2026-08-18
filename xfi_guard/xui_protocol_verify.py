"""Protocol-aware verification helpers for 3X-UI/Xray inbounds."""
from __future__ import annotations
import base64,json,socket,ssl,time
from urllib.parse import urlparse
SUPPORTED={"vless","vmess","trojan","shadowsocks","socks","http","dokodemo-door","wireguard"}
def _tcp(host,port,timeout=4):
 t=time.monotonic()
 try:
  with socket.create_connection((host,int(port)),timeout=timeout): pass
  return {"ok":True,"latency_ms":round((time.monotonic()-t)*1000,1)}
 except OSError as e:return {"ok":False,"latency_ms":round((time.monotonic()-t)*1000,1),"error":type(e).__name__}
def _tls(host,port,sni=None,timeout=5):
 t=time.monotonic(); ctx=ssl.create_default_context()
 try:
  with socket.create_connection((host,int(port)),timeout=timeout) as raw:
   with ctx.wrap_socket(raw,server_hostname=sni or host) as s: cipher=s.cipher()[0] if s.cipher() else None
  return {"ok":True,"latency_ms":round((time.monotonic()-t)*1000,1),"cipher":cipher}
 except (OSError,ssl.SSLError) as e:return {"ok":False,"latency_ms":round((time.monotonic()-t)*1000,1),"error":type(e).__name__}
def _config_checks(inbound):
 protocol=str(inbound.get("protocol","")).lower(); errors=[]
 if protocol not in SUPPORTED: errors.append("unsupported_protocol")
 try: port=int(inbound.get("port",0)); assert 1<=port<=65535
 except (ValueError,AssertionError): errors.append("invalid_port")
 if not inbound.get("settings"): errors.append("missing_settings")
 return protocol,errors
def verify_inbound(inbound,host,client_test=None):
 protocol,errors=_config_checks(inbound); checks=[]; port=int(inbound.get("port",0) or 0)
 if not errors:
  checks.append({"name":"tcp","protocol":protocol,**_tcp(host,port)})
  stream=inbound.get("streamSettings") or {}; security=str(stream.get("security") or "")
  if security=="tls": checks.append({"name":"tls","protocol":protocol,**_tls(host,port,(stream.get("tlsSettings") or {}).get("serverName") or host)})
  elif security not in ("","none"): checks.append({"name":"transport","ok":True,"security":security})
 if client_test:
  try: checks.append({"name":"client","ok":bool(client_test(inbound))})
  except Exception as e: checks.append({"name":"client","ok":False,"error":type(e).__name__})
 failed=[x for x in checks if not x.get("ok",True)]; state="INVALID" if errors else "DOWN" if failed else "HEALTHY"
 return {"ok":not errors and not failed,"state":state,"protocol":protocol,"port":port,"errors":errors,"checks":checks}
def verify_vmess_link(link):
 try:
  raw=base64.urlsafe_b64decode(link.split("//",1)[1]+"==="); data=json.loads(raw); return {"ok":bool(data.get("add") and data.get("port") and data.get("id")),"format":"vmess"}
 except Exception:return {"ok":False,"format":"vmess","error":"invalid_link"}
def verify_share_link(link):
 scheme=urlparse(link).scheme.lower(); return {"ok":scheme in SUPPORTED,"scheme":scheme}
