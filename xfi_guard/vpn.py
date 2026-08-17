"""Проверка VPN/Xray-сервисов и сетевых портов."""
from __future__ import annotations
from typing import Any
from .checks import CheckResult,_run

def check_service_candidates(services:tuple[str,...]=( "xray","x-ui","3x-ui" ))->list[CheckResult]:
    raw=[]
    for service in services:
        code,stdout,stderr=_run(["systemctl","is-active",service])
        if code==0 and stdout=="active": raw.append((service,"ok","active"))
        elif stdout in {"inactive","failed"}: raw.append((service,"critical",stdout))
        else: raw.append((service,"unknown",stdout or stderr))
    manager_active=any(service in {"x-ui","3x-ui"} and status=="ok" for service,status,_ in raw)
    results=[]
    for service,status,output in raw:
        if status=="critical" and manager_active and service=="xray":
            status="warning"; message=f"Сервис {service} не запущен как отдельный systemd-сервис; панель управления активна"
        elif status=="ok": message=f"Сервис {service} активен"
        elif status=="critical": message=f"Сервис {service} неактивен"
        else: message=f"Состояние сервиса {service} недоступно"
        results.append(CheckResult("vpn_service",status,message,{"service":service,"output":output}))
    return results

def check_listening_ports(ports:tuple[int,...]=(22,80,443,2053,2083,2087,2096))->CheckResult:
    code,stdout,stderr=_run(["ss","-lntup"])
    if code!=0: return CheckResult("network","unknown","Не удалось проверить открытые сетевые порты",{"output":stdout or stderr})
    listeners:list[dict[str,Any]]=[]
    for line in stdout.splitlines()[1:]:
        fields=line.split()
        if len(fields)<5: continue
        local=fields[4]; port_text=local.rsplit(":",1)[-1].strip("[]")
        if port_text.isdigit() and int(port_text) in ports: listeners.append({"port":int(port_text),"line":line})
    return CheckResult("network","ok",f"Обнаружено {len(listeners)} отслеживаемых открытых портов",{"listeners":listeners,"monitored_ports":list(ports)})
def collect_vpn_checks()->list[CheckResult]: return check_service_candidates()+[check_listening_ports()]
