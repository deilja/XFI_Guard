"""Risk scoring and human-confirmed defense decisions."""
from __future__ import annotations
import json
from datetime import datetime, timezone
from pathlib import Path
from .firewall import block_ip, list_blocked_ips, unblock_ip, validate_public_ip
STATE_FILE = Path("/var/lib/xfi-guard/defense.json")
def _load():
    try:
        data=json.loads(STATE_FILE.read_text(encoding="utf-8")); return data if isinstance(data,dict) else {"history":[]}
    except (OSError,ValueError): return {"history":[]}
def _save(data):
    STATE_FILE.parent.mkdir(parents=True,exist_ok=True); STATE_FILE.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding="utf-8")
    try: STATE_FILE.chmod(0o600)
    except OSError: pass
def _audit(ip,action,actor,reason,metadata=None):
    state=_load(); state.setdefault("history",[]).append({"timestamp":datetime.now(timezone.utc).isoformat(),"ip":ip,"actor":str(actor),"action":action,"reason":str(reason)[:500],"metadata":metadata or {}}); state["history"]=state["history"][-500:]; _save(state)
def score_ip(item):
    ip=validate_public_ip(str(item.get("ip",""))); events=max(0,int(item.get("events",0) or 0)); sources=item.get("sources") or []; severity=str(item.get("severity","warning")).lower(); score=min(100,events*5+len(sources)*15+(35 if severity=="critical" else 10 if severity=="warning" else 0)); risk="critical" if score>=80 else "high" if score>=60 else "medium" if score>=30 else "low"; return {"ip":ip,"score":score,"risk":risk,"events":events,"sources":list(sources)}
def pending_candidates(items):
    blocked=set(list_blocked_ips()); result=[]
    for item in items:
        try: scored=score_ip(item)
        except ValueError: continue
        if scored["ip"] not in blocked: result.append(scored)
    return sorted(result,key=lambda x:x["score"],reverse=True)
def confirm_block(ip,actor="admin",reason="manual confirmation",metadata=None):
    ip=validate_public_ip(ip); ok,message=block_ip(ip); _audit(ip,"block" if ok else "block_failed",actor,reason,metadata); return ok,message
def confirm_unblock(ip,actor="admin",reason="manual confirmation",metadata=None):
    ip=validate_public_ip(ip); ok,message=unblock_ip(ip); _audit(ip,"unblock" if ok else "unblock_failed",actor,reason,metadata); return ok,message
def history(limit=50): return _load().get("history",[])[-max(1,min(limit,500)):]
