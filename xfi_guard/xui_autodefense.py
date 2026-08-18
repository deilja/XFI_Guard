"""Conservative automatic defense for 3X-UI: detect and quarantine abusive IPs."""
from __future__ import annotations
import ipaddress, subprocess, time
from pathlib import Path
STATE=Path('/var/lib/xfi-guard/xui_blocklist.txt')
CHAIN='XFI_GUARD_XUI'
def _run(*args,timeout=10): return subprocess.run(args,text=True,capture_output=True,timeout=timeout,check=False)
def _valid_ip(value):
    try: ipaddress.ip_address(value); return True
    except ValueError:return False
def ensure_chain():
    p=_run('nft','list','chain','inet','filter',CHAIN)
    if p.returncode==0:return True
    return _run('nft','add','chain','inet','filter',CHAIN).returncode==0
def block_ip(ip,reason='xui-abuse'):
    if not _valid_ip(ip): return {'ok':False,'error':'invalid_ip'}
    if not ensure_chain(): return {'ok':False,'error':'nft_chain_unavailable'}
    family='ip' if ':' not in ip else 'ip6'; existing=_run('nft','list','chain','inet','filter',CHAIN).stdout
    if ip in existing:return {'ok':True,'already_blocked':True}
    p=_run('nft','add','rule','inet','filter',CHAIN,family,'saddr',ip,'drop','comment',f'XFI {reason}')
    if p.returncode==0:
        STATE.parent.mkdir(parents=True,exist_ok=True); STATE.touch(mode=0o600,exist_ok=True); STATE.open('a',encoding='utf-8').write(f'{int(time.time())}\t{ip}\t{reason}\n')
    return {'ok':p.returncode==0,'already_blocked':False,'error':p.stderr[-300:]}
def unblock_ip(ip):
    if not _valid_ip(ip): return {'ok':False,'error':'invalid_ip'}
    rules=_run('nft','-a','list','chain','inet','filter',CHAIN).stdout; removed=0
    for line in rules.splitlines():
        if ip in line and '# handle ' in line:
            handle=line.rsplit('# handle ',1)[1].split()[0]; removed+=_run('nft','delete','rule','inet','filter',CHAIN,'handle',handle).returncode==0
    return {'ok':removed>0,'removed':removed}
def block_candidates(failed_ssh,threshold=8):
    return [{"ip":ip,"count":count,**block_ip(ip,'ssh-bruteforce')} for ip,count in failed_ssh if count>=threshold]
