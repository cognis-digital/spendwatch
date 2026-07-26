"""Session / limits tracking tests."""

from __future__ import annotations

from datetime import datetime, timezone, timedelta

import pytest

from spendwatch.session import SessionTracker, Limits
from spendwatch.ledger import Ledger
from spendwatch.pricing import PricingTable
from spendwatch.schema import UsageRecord


@pytest.fixture
def pricing():
    return PricingTable.default_table()


def rec(cost_usd, when, model="gpt-4o", project="p"):
    tokens = int(round(cost_usd / 2.5 * 1_000_000))
    return UsageRecord(provider="openai", model=model, project=project,
                       input_tokens=tokens, timestamp=when)


@pytest.fixture
def as_of():
    return datetime(2026, 7, 24, 15, 0, 0, tzinfo=timezone.utc)


def test_limits_from_dict():
    lim = Limits.from_dict({"plan_allowance_usd": 100, "weekly_limit_usd": 50,
                            "daily_limit_usd": 20, "session_window_minutes": 120})
    assert lim.plan_allowance_usd == 100
    assert lim.session_window_minutes == 120


def test_limits_ignores_unknown_keys():
    lim = Limits.from_dict({"plan_allowance_usd": 10, "bogus": 1})
    assert lim.plan_allowance_usd == 10


def test_empty_limits_defaults():
    lim = Limits()
    assert lim.plan_allowance_usd is None
    assert lim.session_window_minutes == 300.0


def test_current_session_window(pricing, as_of):
    led = Ledger([
        rec(1.0, as_of - timedelta(minutes=10)),   # in window
        rec(2.0, as_of - timedelta(minutes=299)),  # in window
        rec(3.0, as_of - timedelta(minutes=400)),  # out of window
    ])
    t = SessionTracker(led, pricing, Limits(session_window_minutes=300))
    session = t.current_session_records(as_of)
    assert len(session) == 2


def test_today_records(pricing, as_of):
    led = Ledger([
        rec(1.0, datetime(2026, 7, 24, 2, tzinfo=timezone.utc)),
        rec(2.0, datetime(2026, 7, 23, 23, tzinfo=timezone.utc)),
    ])
    t = SessionTracker(led, pricing)
    assert len(t.today_records(as_of)) == 1


def test_week_records(pricing, as_of):
    led = Ledger([
        rec(1.0, datetime(2026, 7, 24, tzinfo=timezone.utc)),
        rec(2.0, datetime(2026, 7, 20, tzinfo=timezone.utc)),  # same ISO week (Mon 7/20)
        rec(3.0, datetime(2026, 7, 10, tzinfo=timezone.utc)),  # earlier week
    ])
    t = SessionTracker(led, pricing)
    assert len(t.week_records(as_of)) == 2


def test_extra_usage_over_allowance(pricing, as_of):
    led = Ledger([rec(120.0, as_of)])
    t = SessionTracker(led, pricing, Limits(plan_allowance_usd=100.0))
    assert t.extra_usage_usd(as_of) == 20.0


def test_extra_usage_under_allowance(pricing, as_of):
    led = Ledger([rec(50.0, as_of)])
    t = SessionTracker(led, pricing, Limits(plan_allowance_usd=100.0))
    assert t.extra_usage_usd(as_of) == 0.0


def test_extra_usage_no_allowance(pricing, as_of):
    led = Ledger([rec(50.0, as_of)])
    t = SessionTracker(led, pricing, Limits())
    assert t.extra_usage_usd(as_of) == 0.0


def test_remaining_balance(pricing, as_of):
    led = Ledger([rec(30.0, as_of)])
    t = SessionTracker(led, pricing, Limits(plan_allowance_usd=100.0))
    assert t.remaining_balance_usd(as_of) == 70.0


def test_remaining_balance_never_negative(pricing, as_of):
    led = Ledger([rec(150.0, as_of)])
    t = SessionTracker(led, pricing, Limits(plan_allowance_usd=100.0))
    assert t.remaining_balance_usd(as_of) == 0.0


def test_remaining_balance_none_without_allowance(pricing, as_of):
    t = SessionTracker(Ledger([rec(10.0, as_of)]), pricing, Limits())
    assert t.remaining_balance_usd(as_of) is None


def test_per_model_usage(pricing, as_of):
    led = Ledger([
        rec(5.0, as_of, model="gpt-4o"),
        rec(3.0, as_of, model="o3-mini"),
    ])
    lim = Limits(per_model_usd={"gpt-4o": 10.0})
    t = SessionTracker(led, pricing, lim)
    pm = t.per_model_usage(as_of)
    assert pm["gpt-4o"]["spent_usd"] == 5.0
    assert pm["gpt-4o"]["remaining_usd"] == 5.0
    assert pm["gpt-4o"]["limit_usd"] == 10.0
    assert pm["o3-mini"]["limit_usd"] is None


def test_per_model_token_cap(pricing, as_of):
    led = Ledger([rec(5.0, as_of, model="gpt-4o")])
    lim = Limits(per_model_tokens={"gpt-4o": 5_000_000})
    t = SessionTracker(led, pricing, lim)
    pm = t.per_model_usage(as_of)
    assert pm["gpt-4o"]["limit_tokens"] == 5_000_000
    assert pm["gpt-4o"]["remaining_tokens"] is not None


def test_snapshot_shape(pricing, as_of):
    led = Ledger([rec(10.0, as_of)])
    lim = Limits(plan_allowance_usd=100, weekly_limit_usd=50, daily_limit_usd=20)
    t = SessionTracker(led, pricing, lim)
    snap = t.snapshot(as_of)
    for key in ("as_of", "session", "today", "week", "lifetime",
                "plan_allowance_usd", "remaining_balance_usd",
                "extra_usage_usd", "per_model"):
        assert key in snap


def test_snapshot_today_pct(pricing, as_of):
    led = Ledger([rec(10.0, as_of)])
    t = SessionTracker(led, pricing, Limits(daily_limit_usd=20.0))
    snap = t.snapshot(as_of)
    assert snap["today"]["pct"] == pytest.approx(0.5)
    assert snap["today"]["remaining_usd"] == 10.0


def test_snapshot_week_limit_none(pricing, as_of):
    led = Ledger([rec(10.0, as_of)])
    t = SessionTracker(led, pricing, Limits())
    snap = t.snapshot(as_of)
    assert snap["week"]["limit_usd"] is None
    assert snap["week"]["pct"] is None


def test_prefer_reported_flag(as_of):
    p = PricingTable.default_table()
    led = Ledger([UsageRecord(provider="openrouter", model="x",
                              input_tokens=1_000_000, cost_usd=99.0, timestamp=as_of)])
    t = SessionTracker(led, p, Limits(plan_allowance_usd=100), prefer_reported=True)
    assert t.extra_usage_usd(as_of) == 0.0
    assert t.remaining_balance_usd(as_of) == 1.0
