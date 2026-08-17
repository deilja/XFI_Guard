"""Continuous read-only monitoring loop."""

from __future__ import annotations

import json
import logging
import signal
import time
from datetime import datetime, timezone
from pathlib import Path

from .ai import AIAnalyzer
from .alerts import AlertManager
from .checks import check_disk, check_memory
from .config import MonitorConfig
from .events import deduplicate, parse_file
from .security import collect_security_checks
from .state import StateStore
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


def run_forever(config: MonitorConfig) -> None:
    running = True
    state = StateStore(config.state_file)
    alerts = AlertManager(cooldown=config.telegram_cooldown_seconds) if config.telegram_enabled else None
    ai = AIAnalyzer(config.ai_provider)

    def stop(_signum: int, _frame: object) -> None:
        nonlocal running
        running = False

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    LOG.info("XFI Guard monitor started; AI provider=%s", config.ai_provider)
    while running:
        snapshot = collect_snapshot(config)
        events = collect_security_events(config, state)
        if ai.enabled():
            for event in events[:config.ai_max_events_per_cycle]:
                analysis = ai.analyze(event)
                if analysis:
                    event["ai_provider"] = ai.provider
                    event["ai_analysis"] = analysis
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
