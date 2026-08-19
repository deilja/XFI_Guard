"""Telegram UI helpers for guarded remediation approvals.

This module only builds presentation/callback data. Execution remains in the
remediation workflow and requires a separately issued approval token.
"""
from __future__ import annotations

from typing import Any

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def _risk_label(risk: Any) -> str:
    value = getattr(risk, "value", str(risk)).lower()
    return {
        "safe": "🟢 Низкий",
        "low": "🟢 Низкий",
        "medium": "🟡 Средний",
        "high": "🟠 Высокий",
        "destructive": "🔴 Разрушающий",
    }.get(value, "⚪ Неизвестный")


def remediation_text(plan: Any) -> str:
    return (
        "🛡 <b>Предложение AI по защите</b>\n\n"
        f"Действие: <code>{plan.action}</code>\n"
        f"Цель: <code>{plan.target}</code>\n"
        f"Риск: {_risk_label(plan.risk)}\n"
        f"Причина: {plan.reason}\n\n"
        "AI только предлагает действие. Выполнение требует явного подтверждения администратора."
    )


def remediation_keyboard(plan_id: str, *, allow_confirm: bool = True) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    if allow_confirm:
        rows.append([InlineKeyboardButton(text="✅ Подтвердить", callback_data=f"xfi:rem:approve:{plan_id}")])
    rows.append([
        InlineKeyboardButton(text="❌ Отклонить", callback_data=f"xfi:rem:reject:{plan_id}"),
        InlineKeyboardButton(text="🔎 Детали", callback_data=f"xfi:rem:detail:{plan_id}"),
    ])
    rows.append([InlineKeyboardButton(text="⏱ Отмена", callback_data=f"xfi:rem:cancel:{plan_id}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def result_text(status: str, plan_id: str, detail: str = "") -> str:
    labels = {
        "approved": "🟢 Подтверждение принято",
        "rejected": "⚪ Предложение отклонено",
        "applied": "🛠 Изменение выполнено",
        "verified": "✅ Изменение проверено",
        "rollback": "↩️ Выполнен откат",
        "failed": "❌ Выполнение не удалось",
    }
    title = labels.get(status, "ℹ️ Статус remediation")
    return f"{title}\n\nPlan ID: <code>{plan_id}</code>\n{detail}".strip()
