"""Continuous monitoring loop with optional AI-assisted SSH auto defense."""

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
from .checks import check_disk, check_memory
from .config import MonitorConfig
from .events import deduplicate, parse_file
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


def write_snapshot(path: str, snapshot: list[dict], events: list[dict] | None = None) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    record = {"timestamp": datetime.now(timezone.utc).isoformat(), "results": snapshot, "events": events or []}
    with target.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def _notify_auto_blocks(results: list[dict]) -> None:
    for item in results:
        if item.get("action") == "blocked":
            notify(
                "🚨 XFI Guard — АВТОБЛОКИРОВКА\n\n"
                f"IP: {item['ip']}\n"
                f"Причина: SSH brute-force\n"
                f"Попыток: {item['attempts']}\n"
                f"Уровень: {str(item['risk']).upper()}\n"
                f"Режим AI: {item.get('analysis_mode', 'unknown')}\n"
                f"Уверенность AI: {item['confidence']:.0%}\n\n"
                f"{item.get('message', 'IP автоматически заблокирован UFW.')}"
            )
        elif item.get("action") == "block_failed":
            notify(
                "⚠️ XFI Guard — автоматическая блокировка не выполнена\n\n"
                f"IP: {item['ip']}\n"
                f"Причина: {item.get('message', 'ошибка UFW')}"
            )


def _notify_ai_consensus(event: dict, result: dict) -> None:
    if not result.get("verdicts"):
        return
    risk = result.get("winner", "unknown")
    if risk not in {"high", "critical"}:
        return
    providers = ", ".join(result.get("providers", [])) or "нет"
    providers_used = int(result.get("providers_used", 0) or 0)
    mode = (
        "FULL CONSENSUS" if providers_used >= 3 and result.get("consensus") else
        "PARTIAL CONSENSUS" if providers_used >= 2 and result.get("consensus") else
        "FALLBACK" if providers_used == 1 else "UNAVAILABLE"
    )
    verdict_lines = []
    for item in result.get("verdicts", [])[:3]:
        verdict_lines.append(
            f"• {item['provider']} / {item['model']}: {item['risk'].upper()} ({item['confidence']:.0%}) — {item.get('reason', '')}"
        )
    ip = event.get("ip") or event.get("source_ip") or "не определён"
    notify(
        "🚨 XFI Guard — AI АНАЛИЗ\n\n"
        f"IP: {ip}\n"
        f"Угроза: {risk.upper()}\n"
        f"Режим: {mode}\n"
        f"AI: {providers_used}/{len(result.get('configured_providers', [])) or 3}\n"
        f"Уверенность: {result.get('confidence', 0):.0%}\n"
        f"Согласие: {result.get('agreement', 0):.0%}\n"
        f"Провайдеры: {providers}\n\n"
        + "\n".join(verdict_lines)
    )


def run_forever(config: MonitorConfig) -> None:
    running = True
    state = StateStore(config.state_file)
    alerts = AlertManager(cooldown=config.telegram_cooldown_seconds) if config.telegram_enabled else None
    ai = AIAnalyzer()
    auto_blocker = AutoBlocker(
        enabled=config.auto_block_enabled,
        confidence=config.auto_block_confidence,
        min_attempts=config.auto_block_min_attempts,
        db_path=config.auto_block_db,
    )

    def stop(_signum: int, _frame: object) -> None:
        nonlocal running
        running = False

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    LOG.info(
        "XFI Guard monitor started; AI providers=%s; auto_block=%s; min_attempts=%s; confidence=%.2f",
        ",".join(ai.available_providers()) or "none", config.auto_block_enabled,
        config.auto_block_min_attempts, config.auto_block_confidence,
    )
    while running:
        snapshot = collect_snapshot(config)
        events = collect_security_events(config, state)
        if ai.enabled():
            for event in events[:config.ai_max_events_per_cycle]:
                result = ai.analyze_consensus(event)
                event["ai_consensus"] = result
                event["ai_provider"] = ",".join(result.get("providers", []))
                event["ai_mode"] = (
                    "full_consensus" if result.get("providers_used", 0) >= 3 and result.get("consensus") else
                    "partial_consensus" if result.get("providers_used", 0) >= 2 and result.get("consensus") else
                    "fallback" if result.get("providers_used", 0) == 1 else "unavailable"
                )
                if result.get("verdicts"):
                    event["ai_risk"] = result.get("winner")
                    event["ai_confidence"] = result.get("confidence", 0)
                LOG.info(
                    "AI consensus: event=%s providers=%s risk=%s confidence=%.2f mode=%s degraded=%s errors=%s",
                    event.get("event_type"), result.get("providers", []),
                    result.get("winner"), result.get("confidence", 0), event["ai_mode"],
                    result.get("degraded", False), list((result.get("provider_errors") or {}).keys()),
                )
                _notify_ai_consensus(event, result)

        if events:
            # AutoBlocker reuses event["ai_consensus"], so one security event
            # produces exactly one AI consensus request and one source of truth.
            defense_results = auto_blocker.evaluate(events)
            if defense_results:
                write_snapshot(config.output_file, snapshot, events + [{"event_type": "auto_defense", **item} for item in defense_results])
                _notify_auto_blocks(defense_results)
            else:
                write_snapshot(config.output_file, snapshot, events)
        else:
            write_snapshot(config.output_file, snapshot, events)

        if alerts:
            for event in events:
                if alerts.send(event):
                    LOG.info("security alert sent: %s", event.get("event_type"))
        for _ in range(config.interval_seconds):
            if not running:
                break
            time.sleep(1)
    LOG.info("XFI Guard monitor stopped")
