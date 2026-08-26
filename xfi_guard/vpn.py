"""Проверка фактического состояния 3X-UI/Xray и сетевых портов + API-мониторинг."""
from __future__ import annotations
import os,re
from typing import Optional
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from .checks import CheckResult,_run
XRAY_RE=re.compile(r"(?:^|[\s/])(xray|xray-linux(?:-amd64|-arm64|-arm)?)(?:$|[\s])",re.I)
_XRAY_ERROR_RE=re.compile(r"\b(error|failed|failure|fatal|panic|exception)\b",re.I)
def _service_state(service):
    code,out,err=_run(["systemctl","is-active",service]);return out.strip() if code==0 else (out.strip() or err.strip() or "unknown")
def _panel_services():
    found=[]
    for s in ("x-ui","3x-ui"):
        code,_,_=_run(["systemctl","cat",s])
        if code==0:found.append(s)
    return found or ["x-ui","3x-ui"]
def _discover_xui_host()->Optional[str]:
    for key in ("XUI_HOST","XUI_URL","XUI_BASE_URL"):
        v=os.getenv(key,"").strip()
        if v:return v.rstrip("/")
    p=os.getenv("XUI_PORT","").strip()
    if p.isdigit() and 1<=int(p)<=65535:return f"http://127.0.0.1:{p}"
    code,out,_=_run(["ss","-lnt"])
    if code!=0:return None
    preferred=[2053,2083,2087,2096,8080,8000];found=[]
    for line in out.splitlines()[1:]:
        f=line.split();local=f[3] if len(f)>=4 else "";port=local.rsplit(":",1)[-1].strip("[]")
        if port.isdigit() and int(port) in preferred:found.append(int(port))
    return f"http://127.0.0.1:{sorted(set(found),key=lambda x:preferred.index(x))[0]}" if found else None
class XUIApiClient:
    def __init__(self,base_url,token=None,username=None,password=None,web_base_path="/",verify_ssl=True,timeout=8.0):
        self.base_url=base_url.rstrip("/");self.web_base_path=web_base_path or "/";self.web_base_path="/"+self.web_base_path.lstrip("/")
        if self.web_base_path!="/":self.web_base_path=self.web_base_path.rstrip("/")
        self.token=token or os.getenv("XUI_TOKEN");self.username=username or os.getenv("XUI_USERNAME");self.password=password or os.getenv("XUI_PASSWORD");self.verify_ssl=verify_ssl;self.timeout=timeout;self.session=requests.Session();retry=Retry(total=2,connect=2,read=2,backoff_factor=.4,status_forcelist=(502,503,504),allowed_methods=frozenset({"GET","POST"}));self.session.mount("http://",HTTPAdapter(max_retries=retry));self.session.mount("https://",HTTPAdapter(max_retries=retry));self._logged_in=bool(self.token)
        if self.token:self.session.headers["Authorization"]=f"Bearer {self.token}"
    def _url(self,path):return f"{self.base_url}{self.web_base_path}{path if path.startswith('/') else '/'+path}"
    @staticmethod
    def _json(r):
        try:d=r.json()
        except (ValueError,requests.RequestException):return {"success":False,"msg":f"HTTP {r.status_code}"}
        return d if isinstance(d,dict) else {"success":False,"msg":"Invalid JSON response"}
    def login(self):
        if self.token:self._logged_in=True;return True
        if not(self.username and self.password):self._logged_in=False;return False
        try:r=self.session.post(self._url("/login"),data={"username":self.username,"password":self.password},timeout=self.timeout,verify=self.verify_ssl);d=self._json(r);self._logged_in=r.ok and bool(d.get("success"));return self._logged_in
        except requests.RequestException:self._logged_in=False;return False
    def get(self,path):
        if not self._logged_in and not self.login():return {"success":False,"msg":"auth failed"}
        try:
            r=self.session.get(self._url(path),timeout=self.timeout,verify=self.verify_ssl)
            if r.status_code in (401,403) and not self.token:
                self._logged_in=False
                if self.login():r=self.session.get(self._url(path),timeout=self.timeout,verify=self.verify_ssl)
            return self._json(r)
        except requests.RequestException as e:return {"success":False,"msg":str(e)}
    def post(self,path,json_data=None):
        if not self._logged_in and not self.login():return {"success":False,"msg":"auth failed"}
        try:return self._json(self.session.post(self._url(path),json=json_data or {},timeout=self.timeout,verify=self.verify_ssl))
        except requests.RequestException as e:return {"success":False,"msg":str(e)}
    def post_form(self,path,data=None):
        if not self._logged_in and not self.login():return {"success":False,"msg":"auth failed"}
        try:return self._json(self.session.post(self._url(path),data=data or {},timeout=self.timeout,verify=self.verify_ssl))
        except requests.RequestException as e:return {"success":False,"msg":str(e)}
def _get_api_client():
    host=_discover_xui_host()
    if not host:return None
    try:timeout=float(os.getenv("XUI_API_TIMEOUT","8"))
    except ValueError:timeout=8.0
    return XUIApiClient(host,token=os.getenv("XUI_TOKEN"),username=os.getenv("XUI_USERNAME"),password=os.getenv("XUI_PASSWORD"),web_base_path=os.getenv("XUI_WEBBASEPATH","/"),verify_ssl=os.getenv("XUI_VERIFY_SSL","true").lower() not in {"0","false","no"},timeout=timeout)
def _xray_processes():
    code,out,_=_run(["ps","-eo","pid=,comm=,args="])
    if code!=0:return []
    result=[]
    for line in out.splitlines():
        text=line.strip()
        if not text:continue
        fields=text.split(None,2)
        comm=fields[1].lower() if len(fields)>1 else ""
        if comm in {"xray","xray-linux-amd64","xray-linux-arm64","xray-linux-arm"} or XRAY_RE.search(text):result.append(text)
    return result
def check_xray_runtime():
    m=_xray_processes();return CheckResult("xray_runtime","ok","Xray реально запущен и работает как процесс",{"processes":m}) if m else CheckResult("xray_runtime","critical","Процесс Xray не запущен",{})
def check_panel_service(services=("x-ui","3x-ui")):
    a=[s for s in _panel_services() if _service_state(s)=="active"];return CheckResult("xui_panel","ok",f"Панель управления активна: {', '.join(a)}",{"services":a}) if a else CheckResult("xui_panel","warning","Панель 3X-UI/x-ui неактивна",{"services":_panel_services()})
def check_service_candidates(services=("xray","x-ui","3x-ui")):
    raw=[(s,_service_state(s)) for s in services];runtime=bool(_xray_processes());panel=any(s in {"x-ui","3x-ui"} and st=="active" for s,st in raw);out=[]
    for s,st in raw:
        if s=="xray" and runtime:status,msg="ok","Xray работает (фактический процесс активен)"
        elif s=="3x-ui" and st!="active" and panel:status,msg="info","Сервис 3x-ui неактивен, но активен альтернативный сервис x-ui; это штатно"
        elif st=="active":status,msg="ok",f"Сервис {s} активен"
        elif st in {"inactive","failed"}:status,msg="warning",f"Сервис {s} неактивен"
        else:status,msg="unknown",f"Состояние сервиса {s}: {st}"
        out.append(CheckResult("vpn_service",status,msg,{"service":s,"state":st}))
    return out

def check_listening_ports(ports=(22,80,443,2053,2083,2087,2096)):
    code,out,err=_run(["ss","-lntup"])
    if code!=0:return CheckResult("network","unknown","Не удалось проверить открытые сетевые порты",{"output":out or err})
    listeners=[]
    for line in out.splitlines()[1:]:
        f=line.split()
        if len(f)<5:continue
        p=f[3].rsplit(":",1)[-1].strip("[]")
        if p.isdigit() and int(p) in ports:
            m=re.search(r'users:\(\("([^"]+)"',line);listeners.append({"port":int(p),"process":m.group(1) if m else "","line":line})
    return CheckResult("network","ok",f"Обнаружено {len(listeners)} отслеживаемых открытых портов",{"listeners":listeners,"monitored_ports":list(ports)})
def check_api_server_status(client=None):
    client=client or _get_api_client()
    if client is None:return CheckResult("api_server_status","info","3X-UI API не настроен: задайте XUI_HOST/XUI_URL или XUI_PORT",{})
    d=client.get("/panel/api/server/status")
    if not d.get("success"):return CheckResult("api_server_status","warning",f"3X-UI API недоступен: {d.get('msg','unknown error')}",{"raw":d,"host":client.base_url})
    obj=d.get("obj") or {};x=obj.get("xray") or {};state=str(x.get("state") or "").lower();v=x.get("version","");details={"cpu":obj.get("cpu"),"mem":obj.get("mem"),"disk":obj.get("disk"),"uptime":obj.get("uptime"),"xray":x,"host":client.base_url}
    if state=="running":return CheckResult("api_server_status","ok",f"Xray running (API), version={v}",details)
    if state in {"stop","stopped"}:return CheckResult("api_server_status","critical","Xray stopped (API)",details)
    return CheckResult("api_server_status","warning",f"Xray state={state or 'unknown'} (API)",details)
def check_api_online_clients(client=None):
    client=client or _get_api_client()
    if client is None:return CheckResult("api_online_clients","info","3X-UI API не настроен",{})
    d=client.post("/panel/api/clients/onlines") or {}
    if not d.get("success"):d=client.get("/panel/api/clients/onlines")
    if not d.get("success"):return CheckResult("api_online_clients","warning",f"Не удалось получить online-клиентов: {d.get('msg','error')}",{})
    online=d.get("obj") or {};online=list(online.keys()) if isinstance(online,dict) else online;n=len(online) if isinstance(online,list) else 0
    return CheckResult("api_online_clients","ok",f"Online клиентов: {n}",{})
def check_api_inbounds_summary(client=None):
    client=client or _get_api_client()
    if client is None:return CheckResult("api_inbounds","info","3X-UI API не настроен",{})
    d=client.get("/panel/api/inbounds/list")
    if not d.get("success"):return CheckResult("api_inbounds","warning",f"Не удалось получить inbounds: {d.get('msg','error')}",{})
    items=d.get("obj") or [];items=items if isinstance(items,list) else [];return CheckResult("api_inbounds","ok",f"Inbounds: {sum(1 for x in items if x.get('enable'))}/{len(items)} enabled",{"total":len(items)})
def check_api_xray_logs(client=None,count=100,filter_text=""):
    client=client or _get_api_client()
    if client is None:return CheckResult("api_xray_logs","info","3X-UI API не настроен",{})
    form={"showDirect":"true","showBlocked":"true","showProxy":"true"}
    if filter_text:form["filter"]=filter_text
    d=client.post_form(f"/panel/api/server/xraylogs/{max(1,min(int(count),1000))}",form)
    if not d.get("success"):return CheckResult("api_xray_logs","warning",f"Не удалось получить xraylogs: {d.get('msg','error')}",{})
    e=d.get("obj") or [];e=e if isinstance(e,list) else [];errors=[str(x)[:300] for x in e if _XRAY_ERROR_RE.search(str(x))];return CheckResult("api_xray_logs","critical" if errors else "ok",f"В логах Xray найдено {len(errors)} ошибок" if errors else f"Логи Xray без ошибок ({len(e)} записей)",{"errors":errors[:10]})
def check_api_panel_logs(client=None,count=80,level="warning"):
    client=client or _get_api_client()
    if client is None:return CheckResult("api_panel_logs","info","3X-UI API не настроен",{})
    d=client.post_form(f"/panel/api/server/logs/{max(1,min(int(count),1000))}",{"level":level,"syslog":"false"})
    if not d.get("success"):return CheckResult("api_panel_logs","warning",f"Не удалось получить panel logs: {d.get('msg','error')}",{})
    lines=d.get("obj") or [];lines=lines if isinstance(lines,list) else [str(lines)];errors=[str(x)[:300] for x in lines if _XRAY_ERROR_RE.search(str(x))];return CheckResult("api_panel_logs","critical" if errors else "ok",f"В логах панели найдено {len(errors)} ошибок" if errors else f"Логи панели без ошибок ({len(lines)} строк)",{})
def _discover_local_log_paths():
    paths=["/var/log/x-ui/xray.log","/var/log/xray/access.log","/var/log/xray/error.log","/usr/local/x-ui/bin/access.log","/usr/local/x-ui/bin/error.log"]
    for s in ("x-ui","3x-ui"):
        code,out,_=_run(["systemctl","show",s,"-p","ExecStart"])
        if code==0 and out:paths+=re.findall(r"/(?:[^\s\"']+)/(?:access|error)\.log",out)
    return list(dict.fromkeys(paths))
def check_local_xray_logs(log_paths=None,tail_lines=100):
    paths=tuple(log_paths or _discover_local_log_paths());found=None;content=""
    for path in paths:
        if os.path.isfile(path):
            code,out,_=_run(["tail","-n",str(max(1,min(int(tail_lines),2000))),path])
            if code==0:found,content=path,out;break
    if not found:return CheckResult("local_xray_logs","info","Локальный файл логов Xray не найден; проверка через API/journalctl является основной",{"tried_paths":list(paths)})
    errors=[x[:300] for x in content.splitlines() if _XRAY_ERROR_RE.search(x)];return CheckResult("local_xray_logs","critical" if errors else "ok",f"В {found} найдено {len(errors)} ошибок" if errors else f"Логи Xray без ошибок ({found})",{"path":found,"errors":errors[:10]})
def collect_vpn_checks(include_api=True,include_logs=True,include_local_log_fallback=True,ports=(22,80,443,2053,2083,2087,2096)):
    r=[check_panel_service(),check_xray_runtime()];r.extend(check_service_candidates());r.append(check_listening_ports(ports))
    if include_api:
        c=_get_api_client();r += [check_api_server_status(c),check_api_online_clients(c),check_api_inbounds_summary(c)]
        if include_logs:r += [check_api_xray_logs(c),check_api_panel_logs(c)]
    if include_local_log_fallback:r.append(check_local_xray_logs())
    return r
