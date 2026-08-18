"""Production-safe orchestration for 3X-UI inbound verification and AI review."""
from __future__ import annotations
import time
from .ai import AIAnalyzer
from .xui_inbound_verify import verify
MODES={"DRY-RUN","VERIFY","ENFORCE","EMERGENCY"}
def run_verify(client,inbound_id,host,mode="VERIFY",ai=None,expected_port=None):
    mode=mode.upper()
    if mode not in MODES: raise ValueError("invalid mode")
    result=verify(client,inbound_id,host,expected_port=expected_port,ai=ai)
    event={"event_type":"xui_inbound_verification","mode":mode,"result":result}
    consensus=None
    if ai is not False:
        engine=ai if ai is not None else AIAnalyzer()
        try: consensus=engine.analyze_consensus(event)
        except Exception as exc: consensus={"consensus":False,"error":type(exc).__name__}
    result["ai_consensus"]=consensus; result["mode"]=mode; result["verified_at"]=time.time()
    return result
