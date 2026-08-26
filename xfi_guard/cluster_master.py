"""Persistent, authenticated HTTP master for XFI Guard Multi-VPS synchronization."""
from __future__ import annotations
import hashlib,hmac,json,os,threading,time
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
from .cluster import accept_event
from .cluster_auth import verify_heartbeat
from .cluster_notify import notify_global_block_sync
from .cluster_policy import evaluate
from .threat_intel import active
STATE_PATH=Path(os.getenv("XFI_GUARD_CLUSTER_STATE",str(Path.home()/".cache/xfi-guard/cluster-state.json")))
NODES:dict[str,dict]={};COMMANDS:dict[str,list[dict]]={};BLOCKS:dict[str,dict]={};LOCK=threading.RLock();HEARTBEAT_TTL=90
def _load():
    try:data=json.loads(STATE_PATH.read_text())
    except (FileNotFoundError,ValueError,OSError):return
    with LOCK: COMMANDS.update(data.get("commands",{}));BLOCKS.update(data.get("blocks",{}))
def _save():
    try: STATE_PATH.parent.mkdir(parents=True,exist_ok=True); tmp=STATE_PATH.with_suffix(".tmp");tmp.write_text(json.dumps({"commands":COMMANDS,"blocks":BLOCKS},ensure_ascii=False,indent=2));os.replace(tmp,STATE_PATH)
    except OSError:
        fallback=Path.home()/".cache/xfi-guard/cluster-state.json";fallback.parent.mkdir(parents=True,exist_ok=True);tmp=fallback.with_suffix(".tmp");tmp.write_text(json.dumps({"commands":COMMANDS,"blocks":BLOCKS},ensure_ascii=False,indent=2));os.replace(tmp,fallback)
def _json(handler,code,payload):
    body=json.dumps(payload,ensure_ascii=False).encode();handler.send_response(code);handler.send_header("Content-Type","application/json");handler.send_header("Cache-Control","no-store");handler.send_header("Content-Length",str(len(body)));handler.end_headers();handler.wfile.write(body)
def _command_id(ip,until):return hashlib.sha256(f"{ip}|{int(until)}".encode()).hexdigest()[:24]
def _prune_expired(now=None):
    now=time.time() if now is None else now;expired=[ip for ip,item in BLOCKS.items() if float(item.get("until",0))<=now]
    for ip in expired:BLOCKS.pop(ip,None)
    return expired
def _node_secret(node):return os.getenv(f"XFI_GUARD_NODE_SECRET_{node}","") or os.getenv("XFI_GUARD_CLUSTER_SECRET","")
def _configured():return bool(os.getenv("XFI_GUARD_CLUSTER_TOKEN","").strip() and os.getenv("XFI_GUARD_CLUSTER_SECRET","").strip())
class Handler(BaseHTTPRequestHandler):
    def log_message(self,fmt,*args):return
    def _body(self):
        length=int(self.headers.get("Content-Length","0"));
        if length>65536:raise ValueError("request too large")
        return json.loads(self.rfile.read(length).decode())
    def _auth(self):
        expected=os.getenv("XFI_GUARD_CLUSTER_TOKEN","").strip()
        if not expected:return False
        return hmac.compare_digest(self.headers.get("Authorization",""),f"Bearer {expected}")
    def _require_configured(self):
        if not _configured():_json(self,503,{"error":"cluster authentication is not configured"});return False
        return True
    def do_POST(self):
        if not self._require_configured():return
        if not self._auth():return _json(self,401,{"error":"unauthorized"})
        try:
            payload=self._body()
            if self.path=="/heartbeat":
                node=str(payload.get("node",""))[:128];signature=str(payload.pop("signature",""))
                if not node:raise ValueError("missing node")
                secret=_node_secret(node)
                if not secret or not verify_heartbeat(payload,signature,secret):return _json(self,401,{"error":"invalid node heartbeat"})
                now=time.time()
                with LOCK:
                    previous=NODES.get(node,{})
                    NODES[node]={**previous,"node_id":str(payload.get("node_id",previous.get("node_id","")))[:128],"last_seen":now,"status":"online","hostname":str(payload.get("hostname",""))[:255],"blocked":[x for x in payload.get("blocked",[]) if isinstance(x,str)][:500]}
                    commands=[c for c in COMMANDS.get(node,[]) if float(c.get("until",0))>now];COMMANDS[node]=[]
                    for c in commands:
                        b=BLOCKS.get(c["ip"])
                        if b:b.setdefault("nodes",{})[node]="queued"
                    _prune_expired(now);_save()
                return _json(self,200,{"ok":True,"commands":commands,"server_time":now})
            if self.path=="/threat":
                secret=os.getenv("XFI_GUARD_CLUSTER_SECRET","");signature=str(payload.get("signature",""));signed_payload=dict(payload);signed_payload.pop("signature",None);item=accept_event(signed_payload,signature,secret);source_node=str(signed_payload.get("node","unknown"));decision=evaluate(item.get("score",0),item.get("risk","low"),len(item.get("origin_nodes",[])),require_two_nodes=False);blocked_nodes=[]
                if decision.allowed:
                    until=time.time()+604800;cid=_command_id(item["ip"],until)
                    with LOCK:
                        block=BLOCKS.setdefault(item["ip"],{"command_id":cid,"until":until,"source_node":source_node,"nodes":{}});block["until"]=max(float(block.get("until",0)),until);block["command_id"]=cid;block["source_node"]=source_node;block["risk"]=item.get("risk","unknown");block["score"]=item.get("score",0);block["confidence"]=signed_payload.get("confidence","-");block["providers"]=signed_payload.get("providers","-")
                        for node,state in NODES.items():
                            if time.time()-state["last_seen"]<=HEARTBEAT_TTL and node!=source_node:
                                if state.get("blocked") and item["ip"] in state["blocked"]:block["nodes"][node]="blocked";continue
                                if not any(c.get("command_id")==cid for c in COMMANDS.setdefault(node,[])):COMMANDS[node].append({"action":"block","ip":item["ip"],"until":until,"source_node":source_node,"command_id":cid})
                                block["nodes"][node]="queued";blocked_nodes.append(node)
                        _save()
                    event=dict(item);event.update({"source_node":source_node,"until":until,"confidence":signed_payload.get("confidence","-"),"providers":signed_payload.get("providers","-")})
                    try:notify_global_block_sync(event,blocked_nodes)
                    except Exception:pass
                return _json(self,200,{"ok":True,"threat":item,"global_block":decision.allowed,"blocked_nodes":blocked_nodes})
            return _json(self,404,{"error":"not found"})
        except Exception as exc:return _json(self,400,{"error":str(exc)})
    def do_GET(self):
        if not self._require_configured():return
        if not self._auth():return _json(self,401,{"error":"unauthorized"})
        now=time.time()
        if self.path=="/health":
            with LOCK:_prune_expired(now);online=sum(1 for n in NODES.values() if now-n["last_seen"]<=HEARTBEAT_TTL);return _json(self,200,{"ok":True,"nodes":len(NODES),"online":online,"threats":len(active(500)),"blocks":len(BLOCKS)})
        if self.path=="/nodes":
            with LOCK:return _json(self,200,{"nodes":[{"name":n,**s,"online":now-s["last_seen"]<=HEARTBEAT_TTL} for n,s in NODES.items()]})
        if self.path=="/blocks":
            with LOCK:_prune_expired(now);items=[{"ip":ip,**item} for ip,item in BLOCKS.items()];items.sort(key=lambda x:float(x.get("until",0)),reverse=True);return _json(self,200,{"blocks":items[:500],"total":len(items)})
        if self.path.startswith("/block/"):
            ip=self.path.removeprefix("/block/");
            with LOCK:_prune_expired(now);return _json(self,200,BLOCKS.get(ip,{"ip":ip,"nodes":{}}))
        return _json(self,404,{"error":"not found"})
def main():
    _load();host=os.getenv("XFI_GUARD_CLUSTER_HOST","127.0.0.1");port=int(os.getenv("XFI_GUARD_CLUSTER_PORT","8765"));ThreadingHTTPServer((host,port),Handler).serve_forever()
if __name__=="__main__":main()
