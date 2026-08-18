"""Optional real-client smoke test for Xray/3X-UI inbounds."""
from __future__ import annotations
import json, os, subprocess, time

class LiveTestError(RuntimeError): pass

def run_live_test(inbound: dict, command: list[str], timeout: int = 30) -> dict:
    if not command: raise LiveTestError("test command is empty")
    started=time.monotonic(); env=os.environ.copy(); env["XFI_INBOUND_JSON"]=json.dumps(inbound,ensure_ascii=False)
    try:
        p=subprocess.run(command,text=True,capture_output=True,timeout=timeout,env=env,check=False)
        return {"ok":p.returncode==0,"state":"WORKING" if p.returncode==0 else "FAILED","latency_ms":round((time.monotonic()-started)*1000,1),"exit_code":p.returncode,"stdout":p.stdout[-2000:],"stderr":p.stderr[-2000:]}
    except subprocess.TimeoutExpired:
        return {"ok":False,"state":"TIMEOUT","latency_ms":round((time.monotonic()-started)*1000,1)}

def verify_with_live_client(inbound: dict, command: list[str], timeout: int=30) -> dict:
    result=run_live_test(inbound,command,timeout)
    return {"protocol":inbound.get("protocol"),"port":inbound.get("port"),"config_state":"VALID","transport_test":result,"state":"WORKING" if result["ok"] else "DOWN","ok":result["ok"]}
