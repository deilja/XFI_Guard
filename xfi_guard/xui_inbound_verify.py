"""End-to-end verification of a 3X-UI inbound after creation/update."""
from __future__ import annotations
import socket, ssl, time

def _tcp(host, port, timeout=4):
    started=time.monotonic()
    try:
        with socket.create_connection((host,int(port)),timeout=timeout): pass
        return {"ok":True,"latency_ms":round((time.monotonic()-started)*1000,1)}
    except OSError as exc:
        return {"ok":False,"latency_ms":round((time.monotonic()-started)*1000,1),"error":type(exc).__name__}

def _tls(host,port,server_name=None,timeout=5):
    started=time.monotonic(); ctx=ssl.create_default_context()
    try:
        with socket.create_connection((host,int(port)),timeout=timeout) as raw:
            with ctx.wrap_socket(raw,server_hostname=server_name or host) as tls: cipher=tls.cipher()[0] if tls.cipher() else None
        return {"ok":True,"latency_ms":round((time.monotonic()-started)*1000,1),"cipher":cipher}
    except (OSError,ssl.SSLError) as exc:
        return {"ok":False,"latency_ms":round((time.monotonic()-started)*1000,1),"error":type(exc).__name__}

def verify(client,inbound_id,host,expected_port=None,ai=None):
    checks=[]; status,obj=client.get_inbound(inbound_id)
    if status>=300 or not obj.get("success",True): return {"ok":False,"state":"DOWN","stage":"api","status":status}
    inbound=obj.get("obj") or {}; port=int(expected_port or inbound.get("port",0)); checks.append({"name":"api","ok":True,"status":status})
    if not port: return {"ok":False,"state":"DOWN","stage":"config","error":"missing_port"}
    checks.append({"name":"tcp","port":port,**_tcp(host,port)})
    stream=inbound.get("streamSettings") or {}; security=stream.get("security") or ""
    if security=="tls": checks.append({"name":"tls","port":port,**_tls(host,port,(stream.get("tlsSettings") or {}).get("serverName") or host)})
    failed=[x for x in checks if x.get("ok") is False]; result={"ok":not failed,"state":"DOWN" if failed else "HEALTHY","inbound_id":inbound_id,"remark":inbound.get("remark"),"protocol":inbound.get("protocol"),"port":port,"security":security,"checks":checks}
    if ai:
        try: result["ai_analysis"]=ai.analyze(result)
        except Exception as exc: result["ai_analysis_error"]=type(exc).__name__
    return result

def verify_all(client,host,ai=None):
    status,body=client.list_inbounds()
    if status>=300 or not body.get("success",True): return {"ok":False,"state":"DOWN","stage":"api","status":status}
    items=body.get("obj") or []; results=[verify(client,int(x.get("id")),host,ai=ai) for x in items if x.get("id") is not None]
    return {"ok":all(x["ok"] for x in results) if results else True,"state":"HEALTHY" if all(x["ok"] for x in results) else "DEGRADED","count":len(results),"results":results}
