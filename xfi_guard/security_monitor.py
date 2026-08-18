"""Autonomous threat monitor with Telegram alerts and durable AI decisions."""
from __future__ import annotations
import hashlib,json,os,time
from datetime import datetime,timezone
from pathlib import Path
from .ai import AIAnalyzer
from .ai_decision import create as create_ai_decision
from .attack_surface import collect_attack_surface
from .telegram_alerts import send_alert
STATE_FILE=Path(os.getenv("XFI_GUARD_MONITOR_STATE","/var/lib/xfi-guard/security_monitor.json"))
def _load():
    try:
        data=json.loads(STATE_FILE.read_text(encoding="utf-8")); return data if isinstance(data,dict) else {"seen":{},"alerts":[]}
    except (OSError,ValueError): return {"seen":{},"alerts":[]}
def _save(data):
    STATE_FILE.parent.mkdir(parents=True,exist_ok=True); STATE_FILE.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding="utf-8")
    try: STATE_FILE.chmod(0o600)
    except OSError: pass
def _fingerprint(item):
    raw="|".join(str(item.get(k,"")) for k in ("ip","risk_score","risk","events","sources","reasons")); return hashlib.sha256(raw.encode()).hexdigest()[:16]
def scan_once(threshold=60,max_ips=5,notify=True):
    state=_load(); surface=collect_attack_surface(); previous=state.setdefault("seen",{}); candidates=[]
    for item in surface.get("ips",[]):
        ip=str(item.get("ip","")).strip()
        if not ip: continue
        score=int(item.get("risk_score",0) or 0); old_data=previous.get(ip,{}); old=int(old_data.get("score",-1) if isinstance(old_data,dict) else old_data); previous[ip]={"score":score,"fingerprint":_fingerprint(item),"updated_at":datetime.now(timezone.utc).isoformat()}
        if score>=threshold and (old<threshold or score>old+10): candidates.append(item)
    candidates=sorted(candidates,key=lambda x:int(x.get("risk_score",0) or 0),reverse=True)[:max(1,min(max_ips,20))]; alerts=[]; analyzer=AIAnalyzer()
    for item in candidates:
        event={"ip":item.get("ip"),"risk_score":item.get("risk_score"),"risk":item.get("risk"),"events":item.get("events"),"sources":item.get("sources"),"reasons":item.get("reasons")}
        consensus=analyzer.analyze_consensus(event); decision=create_ai_decision(event,consensus)
        alert={"id":_fingerprint(item),"decision_id":decision["id"],"timestamp":datetime.now(timezone.utc).isoformat(),"ip":item.get("ip"),"score":item.get("risk_score"),"risk":item.get("risk"),"consensus":consensus}; alerts.append(alert)
        if notify: send_alert(alert)
    state["alerts"]=(state.get("alerts",[])+alerts)[-200:]; state["updated_at"]=datetime.now(timezone.utc).isoformat(); _save(state); return {"alerts":alerts,"active_count":surface.get("active_count",0),"scanned":len(surface.get("ips",[]))}
def run_forever(interval=300,threshold=60):
    while True:
        try: scan_once(threshold=threshold)
        except Exception as exc:
            data=_load(); data.setdefault("alerts",[]).append({"timestamp":datetime.now(timezone.utc).isoformat(),"error":f"{type(exc).__name__}: {exc}"}); data["alerts"]=data["alerts"][-200:]; _save(data)
        time.sleep(max(30,interval))
if __name__=="__main__": run_forever(int(os.getenv("XFI_GUARD_MONITOR_INTERVAL","300")),int(os.getenv("XFI_GUARD_MONITOR_THRESHOLD","60")))
