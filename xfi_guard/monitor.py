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


def _alert_keyboard(ip: str) -> list[list[dict]]:
    """Keyboard consumed by xfi_guard.alert_callbacks."""
    return [
        [
            {"text": "🚫 Заблокировать IP", "callback_data": f"xfi:block:{ip}"},
            {"text": "⚠️ Игнорировать", "callback_data": f"xfi:ignore:{ip}"},
        ],
        [{"text": "📋 Посмотреть логи", "callback_data": f"xfi:detail:{ip}"}],
    ]


def _notify_auto_blocks(results: list[dict]) -> None:
    for item in results:
        ip = str(item.get("ip", ""))
        keyboard = _alert_keyboard(ip) if ip else None
        if item.get("action") == "blocked":
            notify(
                "🚨 XFI Guard — АВТОБЛОКИРОВКА\n\n"
                f"IP: {ip}\n"
                f"Причина: SSH brute-force\n"
                f"Попыток: {item['attempts']}\n"
                f"Уровень: {str(item['risk']).upper()}\n"
                f"Уверенность AI: {item['confidence']:.0%}\n"
                f"AI providers: {', '.join(item.get('providers', [])) or '—'}\n\n"
                f"{item.get('message', 'IP автоматически заблокирован UFW.')}"
                , keyboard=keyboard
            )
        elif item.get("action") == "block_failed":
            notify(
                "⚠️ XFI Guard — автоматическая блокировка не выполнена\n\n"
                f"IP: {ip}\n"
                f"Уровень: {str(item.get('risk', 'unknown')).upper()}\n"
                f"Уверенность AI: {float(item.get('confidence', 0)):.0%}\n\n"
                f"Причина: {item.get('message', 'ошибка UFW')}"
                , keyboard=keyboard
            )
        elif item.get("action") == "none" and str(item.get("risk", "")).lower() in {"high", "critical"}:
            notify(
                "🚨 XFI Guard — требуется решение администратора\n\n"
                f"IP: {ip}\n"
                f"Попыток: {item.get('attempts', 0)}\n"
                f"Уровень: {str(item.get('risk')).upper()}\n"
                f"Уверенность AI: {float(item.get('confidence', 0)):.0%}\n"
                f"AI providers: {', '.join(item.get('providers', [])) or '—'}\n\n"
                f"{item.get('reason', 'AI обнаружил подозрительную активность.')}"
                , keyboard=keyboard
            )


def run_forever(config: MonitorConfig) -> None:
    running = True
    state = StateStore(config.state_file)
    alerts = AlertManager(cooldown=config.telegram_cooldown_seconds) if config.telegram_enabled else None
    ai = AIAnalyzer(config.ai_provider)
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
        "XFI Guard monitor started; AI provider=%s; auto_block=%s; min_attempts=%s; confidence=%.2f",
        config.ai_provider, config.auto_block_enabled, config.auto_block_min_attempts, config.auto_block_confidence,
    )
    while running:
        snapshot = collect_snapshot(config)
        events = collect_security_events(config, state)
        if ai.enabled():
            for event in events[:config.ai_max_events_per_cycle]:
                analysis = ai.analyze(event)
                if analysis:
                    event["ai_provider"] = ai.provider
                    event["ai_analysis"] = analysis

        if events:
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
