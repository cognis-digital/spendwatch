"""Status-widget bridge.

Emits a tiny, flat JSON any secondary-display or stream-controller widget can
render at a glance — covering *all* providers, not one. Kept intentionally
small and stable so a resource-constrained widget can poll it cheaply.
"""

from __future__ import annotations

import json
import os
import tempfile

from .. import money


def build(report: dict) -> dict:
    """Flatten a full report into a compact widget payload."""
    summary = report.get("summary", {})
    session = report.get("session", {})
    forecast = report.get("forecast", {})
    budget = report.get("budget") or {}

    day_fc = forecast.get("day", {})

    status = budget.get("overall", "ok")
    spent_today = session.get("today", {}).get("cost_usd", 0.0)
    remaining_today = session.get("today", {}).get("remaining_usd")

    payload = {
        "v": 1,
        "generated_at": report.get("generated_at"),
        "status": status,
        "spent_today_usd": spent_today,
        "spent_today": money.fmt_usd(spent_today),
        "spent_total_usd": summary.get("cost_usd", 0.0),
        "spent_total": money.fmt_usd(summary.get("cost_usd", 0.0)),
        "remaining_today_usd": remaining_today,
        "remaining_balance_usd": session.get("remaining_balance_usd"),
        "projected_day_usd": day_fc.get("projected_total_usd", 0.0),
        "burn_per_hour_usd": day_fc.get("burn_per_hour", 0.0),
        "providers": summary.get("providers", []),
        "records": summary.get("records", 0),
        "exit_code": budget.get("exit_code", 0),
    }
    return payload


def render(report: dict, indent: int | None = None) -> str:
    return json.dumps(build(report), indent=indent, sort_keys=True, ensure_ascii=False)


def write(report: dict, path: str, indent: int | None = None) -> str:
    """Atomically write the widget JSON to ``path``; returns the path.

    Uses a temp file + replace so a polling widget never reads a half-written
    file.
    """
    text = render(report, indent=indent)
    directory = os.path.dirname(os.path.abspath(path)) or "."
    os.makedirs(directory, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=directory, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)
    return path
