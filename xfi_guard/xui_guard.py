"""Hardened 3X-UI 3.6.0 management adapter."""
from __future__ import annotations
import os, subprocess
from urllib import error, request
XUI_VERSION="3.6.0"

def _run(*args, timeout=15):
    return subprocess.run(args,text=True,capture_output=True,timeout=timeout,check=False)

def detect_version():
    p=_run("x-ui","version"); text=(p.stdout+p.stderr).strip()
    return XUI_VERSION if XUI_VERSION in text else (text[-160:] if text else "unknown")

def status():
    p=_run("systemctl","is-active","x-ui")
    return {"expected_version":XUI_VERSION,"version":detect_version(),"service_active":p.stdout.strip()=="active","service_state":p.stdout.strip() or p.stderr.strip()}

def safe_restart():
    p=_run("systemctl","restart","x-ui",timeout=30)
    return {"ok":p.returncode==0,"stderr":p.stderr[-500:],"status":status()}

def service_logs(lines=100):
    n=max(1,min(int(lines),500)); return _run("journalctl","-u","x-ui","-n",str(n),"--no-pager").stdout[-12000:]

def panel_health(base_url,token=None,timeout=8):
    token=token or os.getenv("XUI_API_TOKEN"); url=base_url.rstrip("/")+"/panel/api/inbounds/list"; headers={"Accept":"application/json"}
    if token: headers["Authorization"]=f"Bearer {token}"
    try:
        req=request.Request(url,headers=headers,method="GET")
        with request.urlopen(req,timeout=timeout) as r: return {"ok":200<=r.status<300,"status":r.status}
    except error.HTTPError as exc:return {"ok":False,"status":exc.code,"error":"HTTP error"}
    except Exception as exc:return {"ok":False,"error":type(exc).__name__}

def public_status():
    s=status(); return {"version":s["version"],"service_active":s["service_active"],"expected_version":XUI_VERSION}
