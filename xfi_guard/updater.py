"""Безопасное обновление XFI Guard через Git с автоматическим откатом."""
from __future__ import annotations
import json, os, shutil, subprocess, sys, time, urllib.request
from pathlib import Path
from .admin_auth import admin_ids

REPO = Path(os.getenv("XFI_GUARD_REPO", "/opt/xfi-guard"))
SERVICE = os.getenv("XFI_GUARD_SERVICE", "xfi-guard-bot")
STATE_DIR = Path(os.getenv("XFI_GUARD_STATE_DIR", "/var/lib/xfi-guard"))
LOCK_FILE = Path(os.getenv("XFI_GUARD_UPDATE_LOCK", "/run/xfi-guard-update.lock"))
NOTIFIED_FILE = STATE_DIR / "update-notified"
STATUS_FILE = STATE_DIR / "update-status.json"
ENV_FILE = Path(os.getenv("XFI_GUARD_ENV_FILE", "/etc/xfi-guard/bot.env"))
ROLLBACK_BRANCH = "xfi-guard-pre-update"
GENERATED_DIRS = ("xfi_guard/__pycache__", "tests/__pycache__", ".pytest_cache", "xfi_guard.egg-info")
SUCCESS_NOTIFICATION = "✅ XFI Guard обновлён"
FAILURE_NOTIFICATION = "❌ Обновление XFI Guard не удалось"
# Kept explicit for the updater contract: administrator recipients are defined by this environment variable.
ADMIN_IDS_ENV = "XFI_GUARD_ADMIN_IDS"


def _load_env_file() -> None:
    if not ENV_FILE.is_file(): return
    for raw in ENV_FILE.read_text(encoding="utf-8").splitlines():
        line=raw.strip()
        if not line or line.startswith("#") or "=" not in line: continue
        key,value=line.split("=",1); key=key.strip(); value=value.strip().strip('"').strip("'")
        if key and key not in os.environ: os.environ[key]=value
_load_env_file()


def run(*args: str, check: bool = True, timeout: int = 120) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args,cwd=REPO,text=True,capture_output=True,timeout=timeout,check=check)


def _cleanup_generated() -> None:
    for relative in GENERATED_DIRS:
        p=REPO/relative
        if p.is_dir(): shutil.rmtree(p,ignore_errors=True)
        elif p.exists():
            try:p.unlink()
            except OSError:pass
    for p in REPO.rglob("*.pyc"):
        try:p.unlink()
        except OSError:pass


def _write_status(status: str,message: str,old: str="",new: str="") -> None:
    try:
        STATE_DIR.mkdir(parents=True,exist_ok=True)
        STATUS_FILE.write_text(json.dumps({"status":status,"message":message,"old":old,"new":new,"time":int(time.time())},ensure_ascii=False,indent=2),encoding="utf-8")
        os.chmod(STATUS_FILE,0o600)
    except OSError: pass


def notify(text: str, keyboard: bool=False) -> bool:
    _load_env_file(); token=os.getenv("XFI_GUARD_BOT_TOKEN","").strip()
    # admin_ids() is the single authorization parser; ADMIN_IDS_ENV keeps the configuration contract explicit.
    recipients=sorted(admin_ids()) if os.getenv(ADMIN_IDS_ENV, "").strip() else []
    if not token or not recipients:return False
    endpoint=f"https://api.telegram.org/bot{token}/sendMessage"; ok=True
    markup={"inline_keyboard":[[{"text":"🔄 Обновить XFI Guard","callback_data":"xfi_apply_update"}]]} if keyboard else None
    for chat_id in recipients:
        payload={"chat_id":int(chat_id),"text":text}
        if markup:payload["reply_markup"]=markup
        req=urllib.request.Request(endpoint,data=json.dumps(payload,ensure_ascii=False).encode(),headers={"Content-Type":"application/json","User-Agent":"XFI-Guard-Updater"},method="POST")
        try:
            with urllib.request.urlopen(req,timeout=15) as response:
                if not json.loads(response.read().decode()).get("ok"): raise RuntimeError("Telegram API returned ok=false")
        except Exception as exc:
            ok=False; print(f"Telegram notification failed: {type(exc).__name__}: {exc}",file=sys.stderr)
    return ok


def github_head() -> str:
    """Read main SHA via Git transport; do not depend on GitHub REST API availability."""
    remote=os.getenv("XFI_GUARD_GIT_REMOTE","origin")
    url=run("git","remote","get-url",remote,timeout=20).stdout.strip()
    if not url: raise RuntimeError("Git remote не настроен")
    for attempt in range(3):
        result=subprocess.run(["git","ls-remote",url,"refs/heads/main"],cwd=REPO,text=True,capture_output=True,timeout=30,check=False)
        sha=(result.stdout.strip().split()[0] if result.returncode==0 and result.stdout.strip() else "")
        if len(sha)==40:return sha
        if attempt<2:time.sleep(2*(attempt+1))
    raise RuntimeError((result.stderr or "git ls-remote не вернул main").strip()[-500:])


def local_head() -> str:return run("git","rev-parse","HEAD").stdout.strip()


def preserve_local_changes() -> str:
    _cleanup_generated(); status=run("git","status","--porcelain").stdout.strip()
    if not status:return ""
    marker=f"xfi-guard-auto-preserve-{int(time.time())}"
    result=run("git","stash","push","--include-untracked","-m",marker,check=False)
    if result.returncode!=0:raise RuntimeError(f"Не удалось сохранить локальные изменения: {result.stderr.strip()[-500:]}")
    for line in run("git","stash","list","--format=%H %gs").stdout.splitlines():
        if marker in line:return line.split(" ",1)[0]
    raise RuntimeError("Git stash создан, но идентификатор не найден")


def restore_local_changes(stash: str) -> None:
    if not stash:return
    _cleanup_generated(); result=run("git","stash","apply","--index",stash,check=False)
    if result.returncode!=0:raise RuntimeError(f"Локальные изменения не применились; stash сохранён: {stash}")
    run("git","stash","drop",stash,check=False)


def acquire_lock() -> bool:
    LOCK_FILE.parent.mkdir(parents=True,exist_ok=True)
    try:
        fd=os.open(LOCK_FILE,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
        with os.fdopen(fd,"w",encoding="utf-8") as h:h.write(str(os.getpid()))
        return True
    except FileExistsError:return False


def release_lock() -> None:
    try:
        if LOCK_FILE.read_text(encoding="utf-8").strip()==str(os.getpid()):LOCK_FILE.unlink()
    except (FileNotFoundError,OSError):pass


def bot_healthy(wait:int=40) -> bool:
    deadline=time.time()+wait
    while time.time()<deadline:
        status=subprocess.run(["systemctl","is-active",SERVICE],text=True,capture_output=True).stdout.strip()
        if status=="active":return True
        time.sleep(2)
    return False


def validate() -> None:
    py=REPO/".venv/bin/python"
    if not py.exists():raise RuntimeError(f"Не найден Python venv: {py}")
    run(str(py),"-m","compileall","-q","xfi_guard",timeout=120)
    probe=run(str(py),"-c","import xfi_guard.bot; print('IMPORT_OK')",timeout=30)
    if "IMPORT_OK" not in probe.stdout:raise RuntimeError("Не удалось импортировать xfi_guard.bot")


def _install(remote:str) -> None:
    run("git","reset","--hard",remote)
    req=REPO/"requirements-bot.txt"
    if req.exists():run(str(REPO/".venv/bin/pip"),"install","-r",str(req),timeout=300)
    validate(); subprocess.run(["systemctl","daemon-reload"],check=True,timeout=30); subprocess.run(["systemctl","restart",SERVICE],check=True,timeout=60)
    if not bot_healthy():raise RuntimeError("Новая версия не прошла health-check")


def apply_update() -> int:
    if not acquire_lock():return 2
    old="";stash="";old_req="";req=REPO/"requirements-bot.txt"
    try:
        old=local_head();stash=preserve_local_changes();old_req=req.read_text(encoding="utf-8") if req.exists() else ""
        run("git","fetch","--prune","origin","main",timeout=120)
        remote=run("git","rev-parse","origin/main").stdout.strip()
        if old==remote and not stash:_write_status("актуально","Сервер уже на актуальном main.",old,remote);return 0
        _write_status("обновление","Устанавливается новая версия.",old,remote)
        run("git","branch","-f",ROLLBACK_BRANCH,old);_install(remote);restore_local_changes(stash)
        if not bot_healthy():raise RuntimeError("Бот не прошёл повторный health-check")
        _write_status("успешно","Обновление завершено.",old,remote);NOTIFIED_FILE.unlink(missing_ok=True);notify(f"{SUCCESS_NOTIFICATION}\nБыло: {old[:8]}\nСтало: {remote[:8]}\nБот работает.");return 0
    except Exception as exc:
        rollback_ok=False
        try:
            if old:
                run("git","reset","--hard",old,timeout=120)
                if old_req:req.write_text(old_req,encoding="utf-8")
                if stash:
                    try:restore_local_changes(stash)
                    except Exception as e:print(f"Restore after rollback failed: {e}",file=sys.stderr)
                if req.exists():subprocess.run([str(REPO/".venv/bin/pip"),"install","-r",str(req)],check=False,timeout=300)
                subprocess.run(["systemctl","daemon-reload"],check=False,timeout=30);subprocess.run(["systemctl","restart",SERVICE],check=False,timeout=60);rollback_ok=bot_healthy()
        except Exception as e:print(f"Rollback failed: {type(e).__name__}: {e}",file=sys.stderr)
        _write_status("ошибка",str(exc),old);notify(f"{FAILURE_NOTIFICATION}. Откат: {'успешен' if rollback_ok else 'НЕ УДАЛОСЬ'}");return 1
    finally:release_lock()


def check_update() -> int:
    try:
        remote=github_head();local=local_head();changed=remote!=local
        if changed:
            previous=NOTIFIED_FILE.read_text(encoding="utf-8").strip() if NOTIFIED_FILE.exists() else ""
            if previous!=remote:
                STATE_DIR.mkdir(parents=True,exist_ok=True);NOTIFIED_FILE.write_text(remote,encoding="utf-8")
                notify(f"🔔 Доступно обновление XFI Guard\nТекущая версия: {local[:8]}\nНовая версия: {remote[:8]}",keyboard=True)
        _write_status("доступно" if changed else "актуально","Есть новая версия." if changed else "Сервер уже на актуальном main.",local,remote);return 0
    except Exception as exc:
        _write_status("временно недоступно",str(exc));return 0


if __name__=="__main__":
    raise SystemExit(apply_update() if len(sys.argv)>1 and sys.argv[1]=="apply" else check_update())
