"""AI Security Center: aggregate recent events into an advisory report."""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta, timezone

from .ai import AIAnalyzer
from .events import SecurityEvent, parse_file
from .config import load_config


class SummaryDict(dict):
    """Dict-compatible summary that can also be concatenated to Telegram text."""
    def __radd__(self, other):
        if isinstance(other, str):
            return other + self.as_text()
        return NotImplemented

    def as_text(self) -> str:
        return (
            f"Период: {self.get('period_hours', 24)} ч.\n"
            f"Событий: {self.get('events', 0)}\n"
            f"Уникальных IP: {self.get('unique_ips', 0)}\n"
            f"Критических: {self.get('critical', 0)}\n"
            f"Предупреждений: {self.get('warning', 0)}\n"
            f"Типы: {dict(self.get('event_types', {}))}\n"
            f"Топ IP: {self.get('top_ips', [])}"
        )


def _load_events() -> list[SecurityEvent]:
    cfg = load_config()
    return parse_file(cfg.ssh_log, "ssh") + parse_file(cfg.fail2ban_log, "fail2ban")


def summarize(events: list[SecurityEvent] | None = None, hours: int = 24) -> SummaryDict:
    events = events if events is not None else _load_events()
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    recent = []
    for event in events:
        try:
            timestamp = datetime.fromisoformat(event.timestamp.replace("Z", "+00:00"))
        except (ValueError, AttributeError):
            continue
        if timestamp >= cutoff:
            recent.append(event)
    ips = Counter(event.ip for event in recent if event.ip)
    types = Counter(event.event_type for event in recent)
    return SummaryDict({
        "period_hours": hours,
        "events": len(recent),
        "unique_ips": len(ips),
        "top_ips": ips.most_common(10),
        "event_types": types,
        "critical": sum(event.severity == "critical" for event in recent),
        "warning": sum(event.severity == "warning" for event in recent),
    })


def ai_report(events: list[SecurityEvent] | None = None, provider: str | None = None) -> str | None:
    events = events if events is not None else _load_events()
    summary = summarize(events)
    analyzer = AIAnalyzer(provider)
    if not analyzer.enabled():
        return None
    return analyzer.analyze({
        "event_type": "security_summary",
        "severity": "critical" if summary["critical"] else "warning",
        "message": summary,
    })
