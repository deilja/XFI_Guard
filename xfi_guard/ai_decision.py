"""Durable AI Security Decision Records for XFI Guard."""
from __future__ import annotations
import hashlib,json
from datetime import datetime,timezone
from pathlib import Path
STATE_FILE=Path("/var/lib/xfi-guard/ai_decisions.json")
def _load():
    try:
        data=json.loads(STATE_FILE.read_text(encoding="utf-8")); return data if isinstance(data,dict) else {"decisions":[]}
    except (OSError,ValueError): return {"decisions":[]}
def _save(data):
    STATE_FILE.parent.mkdir(parents=True,exist_ok=True); STATE_FILE.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding="utf-8")
    try: STATE_FILE.chmod(0o600)
    except OSError: pass
def create(event:dict,consensus:dict)->dict:
    providers=consensus.get("verdicts") or []
    normalized={"ip":event.get("ip"),"risk_score":event.get("risk_score",event.get("score")),"risk":event.get("risk"),"events":event.get("events"),"sources":event.get("sources"),"reasons":event.get("reasons"),"providers":providers,"consensus":bool(consensus.get("consensus")),"providers_used":consensus.get("providers_used",0),"models_used":consensus.get("models_used",len(providers)),"models":consensus.get("models",[]),"winner":consensus.get("winner"),"weighted_score":consensus.get("weighted_score"),"agreement":consensus.get("agreement"),"conflict":consensus.get("conflict"),"confidence":consensus.get("confidence"),"min_consensus":consensus.get("min_consensus")}
    decision_id=hashlib.sha256(json.dumps(normalized,ensure_ascii=False,sort_keys=True,default=str).encode()).hexdigest()[:20]
    record={"id":decision_id,"timestamp":datetime.now(timezone.utc).isoformat(),**normalized}
    data=_load(); data.setdefault("decisions",[]).append(record); data["decisions"]=data["decisions"][-500:]; _save(data); return record
def get(decision_id:str): return next((x for x in reversed(_load().get("decisions",[])) if x.get("id")==decision_id),None)
def recent(limit=20): return _load().get("decisions",[])[-max(1,min(limit,500)):]
