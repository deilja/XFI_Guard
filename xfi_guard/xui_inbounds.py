"""3X-UI 3.6.0 inbound lifecycle: create, inspect and verify reachability."""
from __future__ import annotations
import json,socket,time
from urllib import request,error
class XUIClient:
    def __init__(self,base_url,token=None,timeout=10): self.base=base_url.rstrip('/'); self.token=token; self.timeout=timeout
    def _request(self,method,path,payload=None):
        headers={'Accept':'application/json','Content-Type':'application/json'}
        if self.token: headers['Authorization']=f'Bearer {self.token}'
        data=None if payload is None else json.dumps(payload).encode(); req=request.Request(self.base+path,data=data,headers=headers,method=method)
        try:
            with request.urlopen(req,timeout=self.timeout) as r:return r.status,json.loads(r.read().decode())
        except error.HTTPError as e:return e.code,{'success':False,'msg':'HTTP error'}
    def list_inbounds(self): return self._request('GET','/panel/api/inbounds/list')
    def get_inbound(self,inbound_id): return self._request('GET',f'/panel/api/inbounds/get/{int(inbound_id)}')
    def add_inbound(self,payload): return self._request('POST','/panel/api/inbounds/add',payload)
    def update_inbound(self,inbound_id,payload): return self._request('POST',f'/panel/api/inbounds/update/{int(inbound_id)}',payload)
    def set_enable(self,inbound_id,enabled): return self._request('POST',f'/panel/api/inbounds/setEnable/{int(inbound_id)}',{'enable':bool(enabled)})
    def delete_inbound(self,inbound_id): return self._request('POST',f'/panel/api/inbounds/del/{int(inbound_id)}')
def validate_inbound_payload(payload):
    required=('remark','port','protocol','settings','streamSettings','sniffing'); missing=[x for x in required if x not in payload]; port=payload.get('port')
    if port is not None and not isinstance(port,int): missing.append('port:int')
    if isinstance(port,int) and not 1<=port<=65535: missing.append('port:range')
    if not isinstance(payload.get('settings'),dict): missing.append('settings:object')
    if not isinstance(payload.get('streamSettings'),dict): missing.append('streamSettings:object')
    return {'valid':not missing,'errors':missing}
def tcp_check(host,port,timeout=3):
    started=time.monotonic()
    try:
        with socket.create_connection((host,port),timeout=timeout):pass
        return {'ok':True,'latency_ms':round((time.monotonic()-started)*1000,1)}
    except OSError as exc:return {'ok':False,'latency_ms':round((time.monotonic()-started)*1000,1),'error':type(exc).__name__}
def verify_inbound(client,inbound_id,host,port=None):
    status,body=client.get_inbound(inbound_id)
    if status>=300 or not body.get('success',True):return {'ok':False,'stage':'api_get','status':status}
    obj=body.get('obj') or {}; target_port=port or obj.get('port')
    if not target_port:return {'ok':False,'stage':'config','error':'missing_port'}
    check=tcp_check(host,int(target_port)); return {'ok':check['ok'],'stage':'tcp','inbound_id':inbound_id,'port':target_port,'api_status':status,**check}
