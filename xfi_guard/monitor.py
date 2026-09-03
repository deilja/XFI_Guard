"""Continuous monitoring loop with AI-assisted automatic defense."""
from __future__ import annotations

import json
import logging
import signal
import time
from datetime import datetime, timezone
from pathlib import Path

from .ai import AIAnalyzer
from .alerts import AlertManager
from .auto_blocker import AutoBlocker
from .auto_defense import reconcile_expired
from .checks import check_disk, check_memory
from .config import MonitorConfig
from .events import deduplicate, parse_file
from .fail2ban import all_banned
from .security import collect_security_checks
from .state import StateStore
from .updater import notify
from .vpn import check_listening_ports, check_service_candidates

LOG = logging.getLogger("xfi_guard.monitor")


def collect_snapshot(config: MonitorConfig) -> list[dict]:
    results = [check_disk(warning_percent=config.disk_warning_percent), check_memory(warning_percent=config.memory_warning_percent)]
    results.extend(collect_security_checks())
    results.extend(check_service_candidates(config.vpn_services))
    results.append(check_listening_ports(config.vpn_ports))
    return [item.to_dict() for item in results]


def collect_security_events(config: MonitorConfig, state: StateStore) -> list[dict]:
    events = parse_file(config.ssh_log, "ssh") + parse_file(config.fail2ban_log, "fail2ban")
    fresh = []
    for event in deduplicate(events)[-config.max_events_per_cycle:]:
        if state.seen(event.fingerprint):
            continue
        state.mark_seen(event.fingerprint, event.timestamp)
        fresh.append(event.to_dict())
    if fresh:
        state.save()
    return fresh


def write_snapshot(path: str, snapshot: list[dict], events=None) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    record = {"timestamp": datetime.now(timezone.utc).isoformat(), "results": snapshot, "events": events or []}
    with target.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def _notify_auto_blocks(results):
    blocked = [item for item in results if item.get("action") == "blocked"]
    failed = [item for item in results if item.get("action") == "block_failed"]
    if blocked:
        lines = ["🚨 XFI Guard — АВТОМАТИЧЕСКАЯ AI-БЛОКИРОВКА", "", f"Заблокировано IP: {len(blocked)}", "Срок: 7 дней", "Backend: Fail2Ban + UFW", "", "IP:"]
        for item in blocked[:30]:
            lines.append(f"• {item['ip']} — {item['attempts']} попыток — {str(item['risk']).upper()} — AI {item['confidence']:.0%} — {item.get('analysis_mode', 'unknown')} — VPS: локальный")
        if len(blocked) > 30:
            lines.append(f"… ещё {len(blocked) - 30} IP")
        notify("\n".join(lines)[:3900])
    if failed:
        notify("\n".join(["⚠️ XFI Guard — AI-блокировка не выполнена", ""] + [f"• {x['ip']} — {x.get('message', 'ошибка Fail2Ban/UFW')}" for x in failed[:20]])[:3900])


def _notify_fail2ban_new_bans(new_bans):
    if not new_bans:
        return
    total = sum(len(v) for v in new_bans.values())
    lines = ["🛡 XFI Guard — Fail2Ban БЛОКИРОВКА", "", f"Новых IP: {total}", "Срок xfi-guard: 7 дней", "", "IP:"]
    for jail, ips in new_bans.items():
        for ip in ips[:50]:
            lines.append(f"• {ip} — jail: {jail}")
    notify("\n".join(lines)[:3900])


def _notify_expired(expired):
    if not expired:
        return
    lines = ["🔓 XFI Guard — блокировки автоматически сняты", "", "Причина: истёк срок 7 дней", "Backend: Fail2Ban + UFW", "", "IP:"]
    lines.extend(f"• {item['ip']}" for item in expired[:50])
    if len(expired) > 50:
        lines.append(f"… ещё {len(expired) - 50} IP")
    notify("\n".join(lines)[:3900])


def _notify_ai_consensus(event, result):
    if not result.get("verdicts"):
        return
    risk = result.get("winner", "unknown")
    if risk not in {"high", "critical"}:
        return
    providers = ", ".join(result.get("providers", [])) or "нет"
    providers_used = int(result.get("providers_used", 0) or 0)
    mode = "FULL CONSENSUS" if providers_used >= 3 and result.get("consensus") else "PARTIAL CONSENSUS" if providers_used >= 2 and result.get("consensus") else "FALLBACK" if providers_used == 1 else "UNAVAILABLE"
    agreement = f"{result.get('agreement', 0):.0%}" if providers_used > 1 else "N/A"
    verdict_lines = [f"• {x['provider']} / {x['model']}: {x['risk'].upper()} ({x['confidence']:.0%}) — {x.get('reason', '')}" for x in result.get("verdicts", [])[:3]]
    ip = event.get("ip") or event.get("source_ip") or "не определён"
    notify("🚨 XFI Guard — AI АНАЛИЗ\n\n" f"IP: {ip}\nУгроза: {risk.upper()}\nРежим: {mode}\nAI: {providers_used}/{len(result.get('configured_providers', [])) or 3}\nУверенность: {result.get('confidence', 0):.0%}\nСогласие: {agreement}\nПровайдеры: {providers}\n\n" + "\n".join(verdict_lines))


def run_forever(config: MonitorConfig) -> None:
    running = True
    state = StateStore(config.state_file)
    alerts = AlertManager(cooldown=config.telegram_cooldown_seconds) if config.telegram_enabled else None
    ai = AIAnalyzer()
    auto_blocker = AutoBlocker(enabled=config.auto_block_enabled, confidence=config.auto_block_confidence, min_attempts=config.auto_block_min_attempts, db_path=config.auto_block_db)
    known_f2b = None

    def stop(_signum, _frame):
        nonlocal running
        running = False

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    LOG.info("XFI Guard monitor started; AI providers=%s; auto_block=%s; min_attempts=%s; confidence=%.2f", ",".join(ai.available_providers()) or "none", config.auto_block_enabled, config.auto_block_min_attempts, config.auto_block_confidence)
    while running:
        snapshot = collect_snapshot(config)
        events = collect_security_events(config, state)
        if ai.enabled():
            for event in events[:config.ai_max_events_per_cycle]:
                result = ai.analyze_consensus(event)
                event["ai_consensus"] = result
                event["ai_provider"] = ",".join(result.get("providers", []))
                event["ai_mode"] = "full_consensus" if result.get("providers_used", 0) >= 3 and result.get("consensus") else "partial_consensus" if result.get("providers_used", 0) >= 2 and result.get("consensus") else "fallback" if result.get("providers_used", 0) == 1 else "unavailable"
                if result.get("verdicts"):
                    event["ai_risk"] = result.get("winner")
                    event["ai_confidence"] = result.get("confidence", 0)
                LOG.info("AI consensus: event=%s providers=%s risk=%s confidence=%.2f mode=%s degraded=%s errors=%s", event.get("event_type"), result.get("providers", []), result.get("winner"), result.get("confidence", 0), event["ai_mode"], result.get("degraded", False), list((result.get("provider_errors") or {}).keys()))
                _notify_ai_consensus(event, result)

        if events:
            defense_results = auto_blocker.evaluate(events)
            if defense_results:
                for item in defense_results:
                    if item.get("action") == "blocked":
                        LOG.warning("XFI-GUARD THREAT %s", item["ip"])
                write_snapshot(config.output_file, snapshot, events + [{"event_type": "auto_defense", **item} for item in defense_results])
                _notify_auto_blocks(defense_results)
            else:
                write_snapshot(config.output_file, snapshot, events)
        else:
            write_snapshot(config.output_file, snapshot, events)

        current_f2b = all_banned()
        if known_f2b is None:
            known_f2b = {jail: set(ips) for jail, ips in current_f2b.items()}
        else:
            new_bans = {jail: [ip for ip in ips if ip not in known_f2b.get(jail, set())] for jail, ips in current_f2b.items()}
            new_bans = {jail: ips for jail, ips in new_bans.items() if ips}
            if new_bans:
                _notify_fail2ban_new_bans(new_bans)
            known_f2b = {jail: set(ips) for jail, ips in current_f2b.items()}

        expired = reconcile_expired()
        if expired:
            _notify_expired(expired)
            LOG.info("expired XFI Guard bans reconciled: %s", [item["ip"] for item in expired])
        if alerts:
            for event in events:
                if alerts.send(event):
                    LOG.info("security alert sent: %s", event.get("event_type"))
        for _ in range(config.interval_seconds):
            if not running:
                break
            time.sleep(1)
    LOG.info("XFI Guard monitor stopped")
