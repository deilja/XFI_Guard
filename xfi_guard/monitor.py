"""Continuous read-only monitoring loop."""

from __future__ import annotations

import json
import logging
import signal
import time
from datetime import datetime, timezone
from pathlib import Path

from .checks import check_disk, check_memory
from .config import MonitorConfig
from .security import collect_security_checks
from .vpn import check_listening_ports, check_service_candidates

LOG = logging.getLogger("xfi_guard.monitor")


def collect_snapshot(config: MonitorConfig) -> list[dict]:
    results = [
        check_disk(warning_percent=config.disk_warning_percent),
        check_memory(warning_percent=config.memory_warning_percent),
    ]
    results.extend(collect_security_checks())
    results.extend(check_service_candidates(config.vpn_services))
    results.append(check_listening_ports(config.vpn_ports))
    return [item.to_dict() for item in results]


def write_snapshot(path: str, snapshot: list[dict]) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "results": snapshot,
    }
    with target.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def run_forever(config: MonitorConfig) -> None:
    running = True

    def stop(_signum: int, _frame: object) -> None:
        nonlocal running
        running = False

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    LOG.info("XFI Guard monitor started; interval=%ss", config.interval_seconds)
    while running:
        snapshot = collect_snapshot(config)
        write_snapshot(config.output_file, snapshot)
        LOG.info("monitor snapshot written: %d checks", len(snapshot))
        for _ in range(config.interval_seconds):
            if not running:
                break
            time.sleep(1)
    LOG.info("XFI Guard monitor stopped")
