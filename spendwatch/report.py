"""Assemble the canonical spendwatch report dict.

Every output surface (JSON, CSV, Prometheus, widget bridge, MCP) is derived
from :func:`build_report` so they never disagree.
"""

from __future__ import annotations

from . import money
from .forecast import forecast_period
from .session import SessionTracker, Limits
from .timeutil import now_utc


def build_report(
    ledger,
    pricing,
    guard=None,
    limits: Limits | None = None,
    as_of=None,
    prefer_reported: bool = False,
) -> dict:
    as_of = as_of or now_utc()
    limits = limits or Limits()

    summary = ledger.summary(pricing, prefer_reported=prefer_reported)
    tracker = SessionTracker(ledger, pricing, limits=limits, prefer_reported=prefer_reported)
    session = tracker.snapshot(as_of=as_of)

    today_cost = session["today"]["cost_usd"]
    month_key = as_of.strftime("%Y-%m")
    month_cost = money.round_usd(
        ledger.cost_by_month(pricing, prefer_reported=prefer_reported).get(month_key, 0.0)
    )

    day_forecast = forecast_period(today_cost, "day", as_of=as_of)
    month_forecast = forecast_period(month_cost, "month", as_of=as_of)

    report = {
        "generated_at": as_of.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "currency": pricing.currency,
        "summary": summary,
        "session": session,
        "forecast": {
            "day": day_forecast.to_dict(),
            "month": month_forecast.to_dict(),
        },
    }
    if guard is not None:
        gr = guard.evaluate(ledger, pricing, as_of=as_of, prefer_reported=prefer_reported)
        report["budget"] = gr.to_dict()
    return report


def remaining_budget(ledger, pricing, guard=None, limits: Limits | None = None,
                     as_of=None, prefer_reported: bool = False) -> dict:
    """Compact 'what's left' answer used by the MCP tool and widget bridge."""
    as_of = as_of or now_utc()
    limits = limits or Limits()
    tracker = SessionTracker(ledger, pricing, limits=limits, prefer_reported=prefer_reported)
    snap = tracker.snapshot(as_of=as_of)

    # Tightest binding budget rule (smallest remaining) if a guard is present.
    tightest = None
    overall = "ok"
    exit_code = 0
    if guard is not None:
        gr = guard.evaluate(ledger, pricing, as_of=as_of, prefer_reported=prefer_reported)
        overall = gr.overall
        exit_code = gr.exit_code
        candidates = [s for s in gr.statuses if s.limit_usd > 0]
        if candidates:
            tightest = min(candidates, key=lambda s: s.remaining_usd)

    result = {
        "as_of": snap["as_of"],
        "currency": pricing.currency,
        "status": overall,
        "exit_code": exit_code,
        "spent_today_usd": snap["today"]["cost_usd"],
        "spent_week_usd": snap["week"]["cost_usd"],
        "spent_lifetime_usd": snap["lifetime"]["cost_usd"],
        "remaining_balance_usd": snap["remaining_balance_usd"],
        "extra_usage_usd": snap["extra_usage_usd"],
        "daily_remaining_usd": snap["today"]["remaining_usd"],
        "weekly_remaining_usd": snap["week"]["remaining_usd"],
    }
    if tightest is not None:
        result["tightest_budget"] = {
            "label": tightest.rule.label,
            "remaining_usd": tightest.remaining_usd,
            "status": tightest.status,
        }
        result["remaining_usd"] = tightest.remaining_usd
    else:
        # Fall back to daily then balance.
        result["remaining_usd"] = (
            snap["today"]["remaining_usd"]
            if snap["today"]["remaining_usd"] is not None
            else snap["remaining_balance_usd"]
        )
    return result
