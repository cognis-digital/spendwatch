"""Live limits & session tracking.

Computes, from a ledger, the figures a usage meter surfaces: the current
session, weekly and per-model usage against configured limits, extra-usage
spend (spend beyond an included plan allowance), and remaining balance.
Everything is derived from ingested records — nothing is scraped.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta

from . import money
from .timeutil import now_utc, start_of_day, week_key


@dataclass
class Limits:
    """Configured allowances. All optional; ``None`` means 'untracked'."""

    plan_allowance_usd: float | None = None   # included spend before overage
    weekly_limit_usd: float | None = None
    daily_limit_usd: float | None = None
    session_window_minutes: float = 300.0     # 5h rolling session window
    per_model_usd: dict = field(default_factory=dict)   # model -> weekly cap
    per_model_tokens: dict = field(default_factory=dict)  # model -> token cap

    @classmethod
    def from_dict(cls, data: dict) -> "Limits":
        data = data or {}
        allowed = {
            "plan_allowance_usd",
            "weekly_limit_usd",
            "daily_limit_usd",
            "session_window_minutes",
            "per_model_usd",
            "per_model_tokens",
        }
        return cls(**{k: v for k, v in data.items() if k in allowed})


def _remaining(limit, used):
    if limit is None:
        return None
    return money.round_usd(limit - used)


def _pct(limit, used):
    if not limit:
        return None
    return round(used / limit, 6)


@dataclass
class SessionTracker:
    ledger: object
    pricing: object
    limits: Limits = field(default_factory=Limits)
    prefer_reported: bool = False

    # -- windows -----------------------------------------------------------
    def current_session_records(self, as_of=None):
        as_of = as_of or now_utc()
        window = timedelta(minutes=self.limits.session_window_minutes)
        cutoff = as_of - window
        return self.ledger.filter(lambda r: cutoff <= r.timestamp <= as_of)

    def today_records(self, as_of=None):
        as_of = as_of or now_utc()
        return self.ledger.since(start_of_day(as_of))

    def week_records(self, as_of=None):
        as_of = as_of or now_utc()
        wk = week_key(as_of)
        return self.ledger.filter(lambda r: r.week == wk)

    # -- computed figures --------------------------------------------------
    def _cost(self, sub_ledger):
        return sub_ledger.total_cost(self.pricing, prefer_reported=self.prefer_reported)

    def extra_usage_usd(self, as_of=None):
        """Spend beyond the included plan allowance (0 if under allowance)."""
        total = self._cost(self.ledger)
        if self.limits.plan_allowance_usd is None:
            return 0.0
        return money.clamp_nonneg(money.round_usd(total - self.limits.plan_allowance_usd))

    def remaining_balance_usd(self, as_of=None):
        """Included allowance remaining (never negative)."""
        if self.limits.plan_allowance_usd is None:
            return None
        total = self._cost(self.ledger)
        return money.clamp_nonneg(money.round_usd(self.limits.plan_allowance_usd - total))

    def per_model_usage(self, as_of=None):
        by_model_cost = self.week_records(as_of).cost_by_model(
            self.pricing, prefer_reported=self.prefer_reported
        )
        by_model_tokens = {}
        for rec in self.week_records(as_of):
            by_model_tokens[rec.model] = by_model_tokens.get(rec.model, 0) + rec.billable_tokens
        out = {}
        models = set(by_model_cost) | set(self.limits.per_model_usd) | set(self.limits.per_model_tokens)
        for model in sorted(models):
            spent = by_model_cost.get(model, 0.0)
            tokens = by_model_tokens.get(model, 0)
            usd_cap = self.limits.per_model_usd.get(model)
            tok_cap = self.limits.per_model_tokens.get(model)
            out[model] = {
                "spent_usd": money.round_usd(spent),
                "tokens": tokens,
                "limit_usd": usd_cap,
                "limit_tokens": tok_cap,
                "remaining_usd": _remaining(usd_cap, spent),
                "remaining_tokens": (None if tok_cap is None else max(tok_cap - tokens, 0)),
                "pct_usd": _pct(usd_cap, spent),
            }
        return out

    def snapshot(self, as_of=None) -> dict:
        as_of = as_of or now_utc()
        session = self.current_session_records(as_of)
        today = self.today_records(as_of)
        week = self.week_records(as_of)

        session_cost = self._cost(session)
        today_cost = self._cost(today)
        week_cost = self._cost(week)
        total_cost = self._cost(self.ledger)

        return {
            "as_of": as_of.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "session": {
                "records": len(session),
                "window_minutes": self.limits.session_window_minutes,
                "cost_usd": session_cost,
                "tokens": session.total_tokens(),
            },
            "today": {
                "records": len(today),
                "cost_usd": today_cost,
                "limit_usd": self.limits.daily_limit_usd,
                "remaining_usd": _remaining(self.limits.daily_limit_usd, today_cost),
                "pct": _pct(self.limits.daily_limit_usd, today_cost),
            },
            "week": {
                "records": len(week),
                "cost_usd": week_cost,
                "limit_usd": self.limits.weekly_limit_usd,
                "remaining_usd": _remaining(self.limits.weekly_limit_usd, week_cost),
                "pct": _pct(self.limits.weekly_limit_usd, week_cost),
            },
            "lifetime": {
                "records": len(self.ledger),
                "cost_usd": total_cost,
            },
            "plan_allowance_usd": self.limits.plan_allowance_usd,
            "remaining_balance_usd": self.remaining_balance_usd(as_of),
            "extra_usage_usd": self.extra_usage_usd(as_of),
            "per_model": self.per_model_usage(as_of),
        }
