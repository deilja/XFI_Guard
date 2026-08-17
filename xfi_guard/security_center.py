"""AI Security Center: aggregate recent events into an advisory report."""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta, timezone

from .ai import AIAnalyzer
from .events import SecurityEvent


def summarize(events: list[SecurityEvent], hours: int = 24) -> dict:
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    recent = []
    for event in events:
        try:
            timestamp = datetime.fromisoformat(event.timestamp.replace("Z", "+00:00"))
        except ValueError:
            continue
        if timestamp >= cutoff:
            recent.append(event)
    ips = Counter(event.ip for event in recent if event.ip)
    types = Counter(event.event_type for event in recent)
    return {
        "period_hours": hours,
        "events": len(recent),
        "unique_ips": len(ips),
        "top_ips": ips.most_common(10),
        "event_types": types,
        "critical": sum(event.severity == "critical" for event in recent),
        "warning": sum(event.severity == "warning" for event in recent),
    }


def ai_report(events: list[SecurityEvent], provider: str | None = None) -> str | None:
    summary = summarize(events)
    analyzer = AIAnalyzer(provider)
    if not analyzer.enabled():
        return None
    return analyzer.analyze({"event_type": "security_summary", "severity": "critical" if summary["critical"] else "warning", "message": summary})
