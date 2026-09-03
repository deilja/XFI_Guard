"""Telegram UI for diagnostics of the VPS where XFI Guard is installed."""
from __future__ import annotations
import os, shutil, socket, subprocess
from aiogram import Dispatcher, F
from aiogram.types import KeyboardButton, ReplyKeyboardMarkup
from .admin_auth import authorized

def _admin(message) -> bool: return authorized(message)
def _kb(rows): return ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text=x) for x in row] for row in rows], resize_keyboard=True, is_persistent=True)
def vps_menu(): return _kb([["📊 Статус VPS"],["🧠 Ресурсы", "🌐 Сеть"],["🛡 Безопасность"],["📋 Логи", "🔄 Проверить"],["⬅️ Главное меню"]])
def _read(path, default="—"):
    try:
        with open(path, encoding="utf-8") as f: return f.read().strip() or default
    except OSError: return default
def _mem():
    data={}
    for line in _read("/proc/meminfo", "").splitlines():
        parts=line.split()
        if len(parts)>=2:
            try: data[parts[0].rstrip(":")]=int(parts[1])
            except ValueError: pass
    total,available=data.get("MemTotal",0),data.get("MemAvailable",data.get("MemFree",0)); used=max(0,total-available)
    return used/total*100 if total else 0, used/1024/1024, total/1024/1024
def _disk():
    total,used,_=shutil.disk_usage("/"); return used/total*100 if total else 0, used/1024**3, total/1024**3
def _load():
    try: a,b,c=os.getloadavg(); return f"{a:.2f} / {b:.2f} / {c:.2f}"
    except OSError: return "—"
def _uptime():
    try: seconds=int(float(_read("/proc/uptime","0").split()[0]))
    except (ValueError,IndexError): return "—"
    days,seconds=divmod(seconds,86400); hours,seconds=divmod(seconds,3600); minutes=seconds//60
    return f"{days}д {hours}ч {minutes}м"
def _cpu():
    try:
        p=subprocess.run(["top","-bn1"],capture_output=True,text=True,timeout=3,check=False)
        import re
        for line in p.stdout.splitlines():
            if "Cpu(s)" in line or "%Cpu(s)" in line:
                idle=re.search(r"([\d.,]+)\s*id",line)
                if idle: return max(0.,100.-float(idle.group(1).replace(",",".")))
    except (OSError,ValueError,subprocess.SubprocessError): pass
    return 0.
def status_text():
    mem_used,mem_used_gb,mem_total_gb=_mem(); disk_used,disk_used_gb,disk_total_gb=_disk()
    return "\n".join(["📊 СТАТУС VPS","",f"Hostname: {socket.gethostname()}",f"Uptime: {_uptime()}",f"CPU: {_cpu():.1f}%",f"RAM: {mem_used:.1f}% ({mem_used_gb:.1f}/{mem_total_gb:.1f} GB)",f"Disk /: {disk_used:.1f}% ({disk_used_gb:.1f}/{disk_total_gb:.1f} GB)",f"Load: {_load()}"])
def network_text():
    try:
        p=subprocess.run(["ip","-brief","addr"],capture_output=True,text=True,timeout=3,check=False); routes=subprocess.run(["ip","route","show","default"],capture_output=True,text=True,timeout=3,check=False)
        return "🌐 СЕТЬ\n\n"+(p.stdout.strip() or "Интерфейсы не получены")[:2400]+"\n\nDefault route:\n"+(routes.stdout.strip() or "нет")
    except (OSError,subprocess.SubprocessError): return "❌ Не удалось получить сведения о сети."
def security_text():
    def active(service):
        try: return subprocess.run(["systemctl","is-active",service],capture_output=True,text=True,timeout=3,check=False).stdout.strip() or "unknown"
        except (OSError,subprocess.SubprocessError): return "unknown"
    return "\n".join(["🛡 БЕЗОПАСНОСТЬ VPS","",f"XFI Guard: {active('xfi-guard')}",f"Fail2Ban: {active('fail2ban')}",f"UFW: {active('ufw')}",f"SSH: {active('ssh')}"])
def logs_text():
    try:
        p=subprocess.run(["journalctl","-u","xfi-guard","-u","xfi-guard-bot","-u","fail2ban","-n","30","--no-pager"],capture_output=True,text=True,timeout=6,check=False)
        return "📋 ПОСЛЕДНИЕ ЛОГИ\n\n"+(p.stdout or p.stderr or "Событий нет.")[-3400:]
    except (OSError,subprocess.SubprocessError): return "❌ Не удалось получить журналы."
def install_vps_handlers(dp:Dispatcher,main_kb)->None:
    if getattr(dp,"_xfi_vps_handlers_installed",False): return
    dp._xfi_vps_handlers_installed=True
    @dp.message(F.text=="🖥 VPS")
    async def vps(message):
        if _admin(message): await message.answer("🖥 VPS\n\nДиагностика и управление только текущим VPS, на котором установлен XFI Guard.",reply_markup=vps_menu())
    @dp.message(F.text=="📊 Статус VPS")
    async def status(message):
        if _admin(message): await message.answer(status_text(),reply_markup=vps_menu())
    @dp.message(F.text=="🧠 Ресурсы")
    async def resources(message):
        if _admin(message): await message.answer(status_text().replace("📊 СТАТУС VPS","🧠 РЕСУРСЫ VPS"),reply_markup=vps_menu())
    @dp.message(F.text=="🌐 Сеть")
    async def network(message):
        if _admin(message): await message.answer(network_text(),reply_markup=vps_menu())
    @dp.message(F.text=="🛡 Безопасность")
    async def security(message):
        if _admin(message): await message.answer(security_text(),reply_markup=vps_menu())
    @dp.message(F.text=="📋 Логи")
    async def logs(message):
        if _admin(message): await message.answer(logs_text(),reply_markup=vps_menu())
    @dp.message(F.text=="🔄 Проверить")
    async def check(message):
        if _admin(message):
            await message.answer("⏳ Проверяю VPS...",reply_markup=vps_menu()); await message.answer(status_text()+"\n\n"+security_text(),reply_markup=vps_menu())
    @dp.message(F.text=="🚫 Блокировки")
    async def blocks(message):
        if _admin(message):
            from .bot import blocked_view
            await message.answer(blocked_view(),reply_markup=vps_menu())
