"""Read-only security checks for firewall, Fail2Ban, and SSH. Сообщения на русском."""
from __future__ import annotations
import re
from .checks import CheckResult, _run

def check_ufw() -> CheckResult:
    code, stdout, stderr = _run(["ufw", "status"]); output=stdout or stderr
    if code==127: return CheckResult("ufw","warning","UFW не установлен или недоступен",{})
    if re.search(r"Status:\s+active",output,re.I): return CheckResult("ufw","ok","UFW активен",{"output":output})
    if re.search(r"Status:\s+inactive",output,re.I): return CheckResult("ufw","critical","UFW неактивен",{"output":output})
    return CheckResult("ufw","unknown","Не удалось определить состояние UFW",{"output":output})

def check_fail2ban() -> CheckResult:
    code, stdout, stderr = _run(["fail2ban-client","ping"]); output=stdout or stderr
    if code==127: return CheckResult("fail2ban","warning","Fail2Ban не установлен или недоступен",{})
    if code==0 and "pong" in output.lower(): return CheckResult("fail2ban","ok","Fail2Ban отвечает",{"output":output})
    return CheckResult("fail2ban","critical","Fail2Ban не отвечает",{"output":output})

def check_ssh_service() -> CheckResult:
    for service in ("ssh","sshd"):
        code, stdout, stderr = _run(["systemctl","is-active",service])
        if code==0 and stdout=="active": return CheckResult("ssh","ok",f"Служба SSH ({service}) активна",{"service":service})
    return CheckResult("ssh","critical","Служба SSH неактивна",{})

def check_ssh_config() -> CheckResult:
    try:
        with open("/etc/ssh/sshd_config","r",encoding="utf-8") as handle: lines=[line.strip() for line in handle if line.strip() and not line.lstrip().startswith("#")]
    except (FileNotFoundError,PermissionError) as exc: return CheckResult("ssh_config","unknown","Не удалось прочитать sshd_config",{"error":str(exc)})
    password_auth=next((x.split(None,1)[1].lower() for x in lines if x.lower().startswith("passwordauthentication ")),None)
    root_login=next((x.split(None,1)[1].lower() for x in lines if x.lower().startswith("permitrootlogin ")),None)
    findings=[]
    if password_auth=="yes": findings.append("PasswordAuthentication включён")
    if root_login in {"yes","without-password","prohibit-password"}: findings.append(f"PermitRootLogin = {root_login}")
    status="warning" if findings else "ok"; message="; ".join(findings) if findings else "Типовых проблем усиления SSH не обнаружено"
    return CheckResult("ssh_config",status,message,{"password_authentication":password_auth,"permit_root_login":root_login})

def collect_security_checks() -> list[CheckResult]: return [check_ufw(),check_fail2ban(),check_ssh_service(),check_ssh_config()]
