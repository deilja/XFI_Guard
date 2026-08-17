"""Telegram-friendly formatting for Security Brain results."""
from __future__ import annotations


def format_brain_report(report: dict, max_items: int = 10) -> str:
    surface = report.get("surface", {})
    results = report.get("results", [])[:max_items]
    providers = {v.get("provider") for r in results for v in r.get("consensus", {}).get("verdicts", [])}
    lines = ["🧠 SECURITY BRAIN", "", f"Активных IP: {surface.get('active_count', 0)}", f"Заблокировано: {surface.get('blocked_count', 0)}", f"AI-провайдеров: {len(providers)}", ""]
    for item in results:
        consensus = item.get("consensus", {})
        verdicts = consensus.get("verdicts", [])
        lines.append(f"🌐 {item.get('ip')} — {item.get('local_risk')} ({item.get('local_score')}/100)")
        if not verdicts:
            lines.append("  AI: нет ответа")
            continue
        for verdict in verdicts:
            text = str(verdict.get("verdict", "")).replace("\n", " ")
            lines.append(f"  • {verdict.get('provider')}/{verdict.get('model')}: {text[:350]}")
        lines.append(f"  Консенсус: {'ДА' if consensus.get('consensus') else 'НЕТ'}")
    return "\n".join(lines)[:3900]


def format_ai_verdicts(result: dict) -> str:
    lines = [f"🧠 AI VERDICTS — {result.get('ip', '?')}", ""]
    for v in result.get("consensus", {}).get("verdicts", []):
        lines.extend([f"{v.get('provider', '?')} / {v.get('model', '?')}", str(v.get('verdict', 'нет ответа'))[:700], ""])
    if not result.get("consensus", {}).get("verdicts"):
        lines.append("AI не вернул ни одного ответа.")
    return "\n".join(lines)[:3900]
