"""Проверка фактического состояния 3X-UI/Xray и сетевых портов + API-мониторинг."""
from __future__ import annotations
import os, re
from typing import Any, Optional
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from .checks import CheckResult, _run

XRAY_RE = re.compile(r"(?:^|[\s/])(xray|xray-linux(?:-amd64|-arm64|-arm)?)(?:$|[\s])", re.IGNORECASE)
_XRAY_ERROR_RE = re.compile(r"\b(error|failed|failure|fatal|panic|exception)\b", re.IGNORECASE)

def _service_state(service: str) -> str:
    code, stdout, stderr = _run(["systemctl", "is-active", service])
    return stdout.strip() if code == 0 else (stdout.strip() or stderr.strip() or "unknown")

def _panel_services() -> list[str]:
    found=[]
    for service in ("x-ui", "3x-ui"):
        code, _, _ = _run(["systemctl", "cat", service])
        if code == 0: found.append(service)
    return found or ["x-ui", "3x-ui"]

def _discover_xui_host() -> Optional[str]:
    for key in ("XUI_HOST", "XUI_URL", "XUI_BASE_URL"):
        value=os.getenv(key, "").strip()
        if value: return value.rstrip("/")
    # Allow a non-standard local panel port through configuration instead of guessing.
    port=os.getenv("XUI_PORT", "").strip()
    if port.isdigit() and 1 <= int(port) <= 65535:
        return f"http://127.0.0.1:{port}"
    code, stdout, _ = _run(["ss", "-lnt"])
    if code != 0: return None
    preferred=[2053,2083,2087,2096,8080,8000]
    found=[]
    for line in stdout.splitlines()[1:]:
        fields=line.split(); local=fields[3] if len(fields)>=4 else ""
        p=local.rsplit(":",1)[-1].strip("[]")
        if p.isdigit() and int(p) in preferred: found.append(int(p))
    return f"http://127.0.0.1:{sorted(set(found), key=lambda p: preferred.index(p))[0]}" if found else None

class XUIApiClient:
    def __init__(self, base_url: str, token: Optional[str]=None, username: Optional[str]=None, password: Optional[str]=None, web_base_path: str="/", verify_ssl: bool=True, timeout: float=8.0):
        self.base_url=base_url.rstrip("/"); self.web_base_path=web_base_path or "/"
        if not self.web_base_path.startswith("/"): self.web_base_path="/"+self.web_base_path
        if self.web_base_path!="/": self.web_base_path=self.web_base_path.rstrip("/")
        self.token=token or os.getenv("XUI_TOKEN"); self.username=username or os.getenv("XUI_USERNAME"); self.password=password or os.getenv("XUI_PASSWORD")
        self.verify_ssl=verify_ssl; self.timeout=timeout; self.session=requests.Session()
        retry=Retry(total=2,connect=2,read=2,backoff_factor=.4,status_forcelist=(502,503,504),allowed_methods=frozenset({"GET","POST"}))
        self.session.mount("http://",HTTPAdapter(max_retries=retry)); self.session.mount("https://",HTTPAdapter(max_retries=retry))
        if self.token: self.session.headers["Authorization"]=f"Bearer {self.token}"
        self._logged_in=bool(self.token)
    def _url(self,path): return f"{self.base_url}{self.web_base_path}{path if path.startswith('/') else '/'+path}"
    @staticmethod
    def _json(response):
        try: data=response.json()
        except (ValueError,requests.RequestException): return {"success":False,"msg":f"HTTP {response.status_code}"}
        return data if isinstance(data,dict) else {"success":False,"msg":"Invalid JSON response"}
    def login(self):
        if self.token: self._logged_in=True; return True
        if not (self.username and self.password): self._logged_in=False; return False
        try:
            r=self.session.post(self._url("/login"),data={"username":self.username,"password":self.password},timeout=self.timeout,verify=self.verify_ssl); d=self._json(r); self._logged_in=r.ok and bool(d.get("success")); return self._logged_in
        except requests.RequestException: self._logged_in=False; return False
    def get(self,path):
        if not self._logged_in and not self.login(): return {"success":False,"msg":"auth failed"}
        try:
            r=self.session.get(self._url(path),timeout=self.timeout,verify=self.verify_ssl)
            if r.status_code in (401,403) and not self.token:
                self._logged_in=False
                if self.login(): r=self.session.get(self._url(path),timeout=self.timeout,verify=self.verify_ssl)
            return self._json(r)
        except requests.RequestException as exc: return {"success":False,"msg":str(exc)}
    def post(self,path,json_data=None):
        if not self._logged_in and not self.login(): return {"success":False,"msg":"auth failed"}
        try: return self._json(self.session.post(self._url(path),json=json_data or {},timeout=self.timeout,verify=self.verify_ssl))
        except requests.RequestException as exc: return {"success":False,"msg":str(exc)}
    def post_form(self,path,data=None):
        if not self._logged_in and not self.login(): return {"success":False,"msg":"auth failed"}
        try: return self._json(self.session.post(self._url(path),data=data or {},timeout=self.timeout,verify=self.verify_ssl))
        except requests.RequestException as exc: return {"success":False,"msg":str(exc)}

def _get_api_client():
    host=_discover_xui_host()
    if not host: return None
    try: timeout=float(os.getenv("XUI_API_TIMEOUT","8"))
    except ValueError: timeout=8.0
    return XUIApiClient(host,token=os.getenv("XUI_TOKEN"),username=os.getenv("XUI_USERNAME"),password=os.getenv("XUI_PASSWORD"),web_base_path=os.getenv("XUI_WEBBASEPATH","/"),verify_ssl=os.getenv("XUI_VERIFY_SSL","true").lower() not in {"0","false","no"},timeout=timeout)

def _xray_processes():
    code,stdout,_=_run(["ps","-eo","pid=,comm=,args="])
    if code!=0:return []
    return [line.strip() for line in stdout.splitlines() if line.strip() and (line.split(None,2)[1].lower() in {"xray","xray-linux-amd64","xray-linux-arm64","xray-linux-arm"} or XRAY_RE.search(line))]

def check_xray_runtime():
    matches=_xray_processes(); return CheckResult("xray_runtime","ok","Xray реально запущен и работает как процесс",{"processes":matches}) if matches else CheckResult("xray_runtime","critical","Процесс Xray не запущен",{})

def check_panel_service(services=("x-ui","3x-ui")):
    active=[s for s in _panel_services() if _service_state(s)=="active"]
    return CheckResult("xui_panel","ok",f"Панель управления активна: {', '.join(active)}",{"services":active}) if active else CheckResult("xui_panel","warning","Панель 3X-UI/x-ui неактивна",{"services":_panel_services()})

def check_service_candidates(services=("xray","x-ui","3x-ui")):
    raw=[(s,_service_state(s)) for s in services]; runtime=bool(_xray_processes()); panel=any(s in {"x-ui","3x-ui"} and st=="active" for s,st in raw); out=[]
    for service,state in raw:
        if service=="xray" and runtime: status,msg="ok","Xray работает (фактический процесс активен)"
        elif service=="3x-ui" and state!="active" and panel: status,msg="info","Сервис 3x-ui неактивен, но активен альтернативный сервис x-ui; это штатно"
        elif state=="active": status,msg="ok",f"Сервис {service} активен"
        elif state in {"inactive","failed"}: status,msg="warning",f"Сервис {service} неактивен"
        else: status,msg="unknown",f"Состояние сервиса {service}: {state}"
        out.append(CheckResult("vpn_service",status,msg,{"service":service,"state":state}))
    return out

def check_listening_ports(ports=(22,80,443,2053,2083,2087,2096)):
    code,stdout,stderr=_run(["ss","-lntup"])
    if code!=0:return CheckResult("network","unknown","Не удалось проверить открытые сетевые порты",{"output":stdout or stderr})
    listeners=[]
    for line in stdout.splitlines()[1:]:
        f=line.split()
        if len(f)<5:continue
        local=f[3]; p=local.rsplit(":",1)[-1].strip("[]")
        if p.isdigit() and int(p) in ports:
            m=re.search(r'users:\(\("([^"]+)"',line); listeners.append({"port":int(p),"process":m.group(1) if m else "","line":line})
    return CheckResult("network","ok",f"Обнаружено {len(listeners)} отслеживаемых открытых портов",{"listeners":listeners,"monitored_ports":list(ports)})

def check_api_server_status(client=None):
    client=client or _get_api_client()
    if client is None:return CheckResult("api_server_status","info","3X-UI API не настроен: задайте XUI_HOST/XUI_URL или XUI_PORT",{})
    data=client.get("/panel/api/server/status")
    if not data.get("success"):return CheckResult("api_server_status","warning",f"3X-UI API недоступен: {data.get('msg','unknown error')}",{"raw":data,"host":client.base_url})
    obj=data.get("obj") or {}; xray=obj.get("xray") or {}; state=str(xray.get("state") or "").lower(); version=xray.get("version",""); details={"cpu":obj.get("cpu"),"mem":obj.get("mem"),"disk":obj.get("disk"),"uptime":obj.get("uptime"),"xray":xray,"host":client.base_url}
    if state=="running":return CheckResult("api_server_status","ok",f"Xray running (API), version={version}",details)
    if state in {"stop","stopped"}:return CheckResult("api_server_status","critical","Xray stopped (API)",details)
    return CheckResult("api_server_status","warning",f"Xray state={state or 'unknown'} (API)",details)

def check_api_online_clients(client=None):
    client=client or _get_api_client()
    if client is None:return CheckResult("api_online_clients","info","3X-UI API не настроен",{})
    data=client.post("/panel/api/clients/onlines") or {}
    if not data.get("success"):data=client.get("/panel/api/clients/onlines")
    if not data.get("success"):return CheckResult("api_online_clients","warning",f"Не удалось получить online-клиентов: {data.get('msg','error')}",{})
    online=data.get("obj") or []; online=list(online.keys()) if isinstance(online,dict) else online
    return CheckResult("api_online_clients","ok",f"Online клиентов: {len(online) if isinstance(online,list) else 0",{}})

def check_api_inbounds_summary(client=None):
    client=client or _get_api_client()
    if client is None:return CheckResult("api_inbounds","info","3X-UI API не настроен",{})
    data=client.get("/panel/api/inbounds/list")
    if not data.get("success"):return CheckResult("api_inbounds","warning",f"Не удалось получить inbounds: {data.get('msg','error')}",{})
    items=data.get("obj") or []; items=items if isinstance(items,list) else []
    return CheckResult("api_inbounds","ok",f"Inbounds: {sum(1 for x in items if x.get('enable'))}/{len(items)} enabled",{"total":len(items)})

def check_api_xray_logs(client=None,count=100,filter_text=""):
    client=client or _get_api_client()
    if client is None:return CheckResult("api_xray_logs","info","3X-UI API не настроен",{})
    form={"showDirect":"true","showBlocked":"true","showProxy":"true"};
    if filter_text:form["filter"]=filter_text
    data=client.post_form(f"/panel/api/server/xraylogs/{max(1,min(int(count),1000))}",form)
    if not data.get("success"):return CheckResult("api_xray_logs","warning",f"Не удалось получить xraylogs: {data.get('msg','error')}",{})
    entries=data.get("obj") or []; entries=entries if isinstance(entries,list) else []; errors=[str(x)[:300] for x in entries if _XRAY_ERROR_RE.search(str(x))]
    return CheckResult("api_xray_logs","critical" if errors else "ok",f"В логах Xray найдено {len(errors)} ошибок" if errors else f"Логи Xray без ошибок ({len(entries)} записей)",{"errors":errors[:10]})

def check_api_panel_logs(client=None,count=80,level="warning"):
    client=client or _get_api_client()
    if client is None:return CheckResult("api_panel_logs","info","3X-UI API не настроен",{})
    data=client.post_form(f"/panel/api/server/logs/{max(1,min(int(count),1000))}",{"level":level,"syslog":"false"})
    if not data.get("success"):return CheckResult("api_panel_logs","warning",f"Не удалось получить panel logs: {data.get('msg','error')}",{})
    lines=data.get("obj") or []; lines=lines if isinstance(lines,list) else [str(lines)]; errors=[str(x)[:300] for x in lines if _XRAY_ERROR_RE.search(str(x))]
    return CheckResult("api_panel_logs","critical" if errors else "ok",f"В логах панели найдено {len(errors)} ошибок" if errors else f"Логи панели без ошибок ({len(lines)} строк)",{})

def _discover_local_log_paths():
    paths=["/var/log/x-ui/xray.log","/var/log/xray/access.log","/var/log/xray/error.log","/usr/local/x-ui/bin/access.log","/usr/local/x-ui/bin/error.log"]
    for service in ("x-ui","3x-ui"):
        code,stdout,_=_run(["systemctl","show",service,"-p","ExecStart"])
        if code==0 and stdout:
            paths += re.findall(r"/(?:[^\s\"']+)/(?:access|error)\.log",stdout)
    return list(dict.fromkeys(paths))

def check_local_xray_logs(log_paths=None,tail_lines=100):
    paths=tuple(log_paths or _discover_local_log_paths()); found=None; content=""
    for path in paths:
        if os.path.isfile(path):
            code,stdout,_=_run(["tail","-n",str(max(1,min(int(tail_lines),2000))),path])
            if code==0:found,content=path,stdout;break
    if not found:return CheckResult("local_xray_logs","info","Локальный файл логов Xray не найден; проверка через API/journalctl является основной",{"tried_paths":list(paths)})
    errors=[x[:300] for x in content.splitlines() if _XRAY_ERROR_RE.search(x)]
    return CheckResult("local_xray_logs","critical" if errors else "ok",f"В {found} найдено {len(errors)} ошибок" if errors else f"Логи Xray без ошибок ({found})",{"path":found,"errors":errors[:10]})

def collect_vpn_checks(include_api=True,include_logs=True,include_local_log_fallback=True,ports=(22,80,443,2053,2083,2087,2096)):
    results=[check_panel_service(),check_xray_runtime()];results.extend(check_service_candidates());results.append(check_listening_ports(ports))
    if include_api:
        client=_get_api_client();results += [check_api_server_status(client),check_api_online_clients(client),check_api_inbounds_summary(client)]
        if include_logs:results += [check_api_xray_logs(client),check_api_panel_logs(client)]
    if include_local_log_fallback:results.append(check_local_xray_logs())
    return results
