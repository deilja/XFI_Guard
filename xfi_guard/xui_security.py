"""Defense-in-depth controls for a 3X-UI 3.6.0 installation."""
from __future__ import annotations
import re, subprocess
XUI_SERVICE="x-ui"
XUI_VERSION="3.6.0"
def _run(*args, timeout=15):
    return subprocess.run(args,text=True,capture_output=True,timeout=timeout,check=False)
def service_health():
    p=_run("systemctl","is-active",XUI_SERVICE); e=_run("systemctl","is-enabled",XUI_SERVICE)
    return {"active":p.stdout.strip()=="active","enabled":e.stdout.strip()=="enabled","state":p.stdout.strip()}
def recent_failed_ssh(lines=300):
    p=_run("journalctl","-u","ssh","-n",str(max(1,min(lines,1000))),"--no-pager")
    ips=re.findall(r'(?:Failed password|Invalid user).*?from (\d{1,3}(?:\.\d{1,3}){3})',p.stdout); counts={}
    for ip in ips: counts[ip]=counts.get(ip,0)+1
    return sorted(counts.items(),key=lambda x:x[1],reverse=True)
def firewall_status():
    p=_run("ufw","status","numbered"); return {"ok":p.returncode==0,"output":p.stdout[-10000:]}
def nftables_status():
    p=_run("nft","list","ruleset"); return {"ok":p.returncode==0,"rules":p.stdout[-12000:]}
def security_snapshot():
    return {"xui_version_target":XUI_VERSION,"xui_service":service_health(),"failed_ssh":recent_failed_ssh(),"ufw":firewall_status(),"nftables":nftables_status()}
