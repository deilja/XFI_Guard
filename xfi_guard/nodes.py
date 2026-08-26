"""Multi-VPS inventory, diagnostics and safe SSH host-key enrollment."""
from __future__ import annotations
import ipaddress, json, os, re, subprocess, tomllib
from dataclasses import dataclass
from pathlib import Path
DEFAULT_IDENTITY_FILE=Path(os.path.expanduser("~/.ssh/xfi_guard_cluster_ed25519"))
@dataclass(frozen=True)
class Node:
    name:str; host:str; user:str="root"; port:int=22; enabled:bool=True; identity_file:str=str(DEFAULT_IDENTITY_FILE)
def _normalize_host_port(host:str,port:int=22)->tuple[str,int]:
    host=str(host or "").strip()
    try: port=int(port)
    except (TypeError,ValueError): port=22
    m=re.fullmatch(r"\[([^\]]+)\]:(\d{1,5})",host)
    if m:return m.group(1),int(m.group(2))
    if host.count(":")==1:
        a,b=host.rsplit(":",1)
        if b.isdigit() and 1<=int(b)<=65535:return a,int(b)
    return host,port
def load_nodes(path:str|Path="config.toml")->list[Node]:
    p=Path(path)
    if not p.exists():return []
    try:data=tomllib.loads(p.read_text(encoding="utf-8"))
    except (OSError,tomllib.TOMLDecodeError):return []
    out=[]
    for raw in data.get("nodes",[]) or []:
        if not isinstance(raw,dict) or not raw.get("enabled",True):continue
        name=str(raw.get("name","")).strip(); host,port=_normalize_host_port(raw.get("host",""),raw.get("port",22)); user=str(raw.get("user","root")).strip() or "root"; identity=str(raw.get("identity_file",str(DEFAULT_IDENTITY_FILE))).strip() or str(DEFAULT_IDENTITY_FILE)
        if not name or not host or not 1<=port<=65535:continue
        try:ipaddress.ip_address(host)
        except ValueError:
            if any(c in host for c in " /\\\t\r\n"):continue
        out.append(Node(name,host,user,port,True,identity))
    return out
def _ssh_base(node:Node)->list[str]:
    identity=Path(os.path.expanduser(node.identity_file)); cmd=["ssh","-o","BatchMode=yes","-o","IdentitiesOnly=yes","-o","StrictHostKeyChecking=yes","-o","ConnectTimeout=8"]
    if identity.is_file():cmd += ["-i",str(identity)]
    return cmd+["-p",str(node.port),f"{node.user}@{node.host}"]
def host_key_fingerprint(node:Node,timeout:int=10)->tuple[bool,str]:
    cmd=["ssh-keyscan","-T",str(max(1,timeout)),"-t","ed25519","-p",str(node.port),node.host]
    try:
        p=subprocess.run(cmd,text=True,capture_output=True,timeout=timeout+3,check=False); lines=[x.strip() for x in p.stdout.splitlines() if x.strip() and not x.startswith("#")]
        if p.returncode!=0 or not lines:return False,(p.stderr or "ssh-keyscan returned no key").strip()[:300]
        fp=subprocess.run(["ssh-keygen","-lf","-","-E","sha256"],input=lines[0]+"\n",text=True,capture_output=True,timeout=5,check=False); parts=fp.stdout.split()
        return (True,parts[1] if fp.returncode==0 and len(parts)>1 else fp.stdout.strip())
    except Exception as exc:return False,f"{type(exc).__name__}: {exc}"
def enroll_host_key(node:Node,timeout:int=10)->tuple[bool,str]:
    ssh_dir=Path(os.path.expanduser("~/.ssh")); ssh_dir.mkdir(mode=0o700,parents=True,exist_ok=True); known=ssh_dir/"known_hosts"; known.touch(mode=0o600,exist_ok=True); cmd=["ssh-keyscan","-T",str(max(1,timeout)),"-t","ed25519","-p",str(node.port),node.host]
    try:
        p=subprocess.run(cmd,text=True,capture_output=True,timeout=timeout+3,check=False); lines=[x for x in p.stdout.splitlines() if x and not x.startswith("#")]
        if p.returncode!=0 or not lines:return False,(p.stderr or "ssh-keyscan returned no key").strip()[:300]
        existing=known.read_text(encoding="utf-8",errors="replace"); additions=[x for x in lines if x not in existing]
        if additions:
            with known.open("a",encoding="utf-8") as f:
                for line in additions:f.write(line+"\n")
        return True,str(known)
    except Exception as exc:return False,f"{type(exc).__name__}: {exc}"
def probe_node(node:Node,timeout:int=8)->dict:
    script=("import json,platform,subprocess; "+"run=lambda c:subprocess.run(c,shell=True,capture_output=True,text=True,timeout=4).stdout.strip(); "+"print(json.dumps({'hostname':platform.node(),'xfi_guard':run('systemctl is-active xfi-guard.service'),'fail2ban':run('systemctl is-active fail2ban.service'),'ufw':run('systemctl is-active ufw.service'),'load':run('cut -d\" \" -f1-3 /proc/loadavg'),'disk':run(\"df -P / | tail -1 | awk '{print $5, $4}'\"),'memory':run(\"free -m | awk '/^Mem:/{print $3, $2}'\"),'uptime':run('uptime -p')},ensure_ascii=False))")
    try:
        p=subprocess.run(_ssh_base(node)+["python3","-c",script],text=True,capture_output=True,timeout=timeout,check=False)
        if p.returncode!=0:return {"name":node.name,"host":node.host,"status":"offline","error":(p.stderr or "ssh failed").strip()[:500]}
        payload=json.loads(p.stdout.strip().splitlines()[-1]); return {"name":node.name,"host":node.host,"status":"online",**payload}
    except Exception as exc:return {"name":node.name,"host":node.host,"status":"offline","error":f"{type(exc).__name__}: {exc}"}
def collect_nodes(path:str|Path="config.toml")->list[dict]:return [probe_node(n) for n in load_nodes(path)]
