"""Canonical report + remaining_budget tests."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from spendwatch.report import build_report, remaining_budget
from spendwatch.budget import BudgetGuard, BudgetRule
from spendwatch.ledger import Ledger
from spendwatch.pricing import PricingTable
from spendwatch.session import Limits
from spendwatch.schema import UsageRecord


@pytest.fixture
def pricing():
    return PricingTable.default_table()


@pytest.fixture
def as_of():
    return datetime(2026, 7, 24, 12, tzinfo=timezone.utc)


def rec(cost_usd, when, model="gpt-4o", project="p"):
    tokens = int(round(cost_usd / 2.5 * 1_000_000))
    return UsageRecord(provider="openai", model=model, project=project,
                       input_tokens=tokens, timestamp=when)


def test_build_report_shape(pricing, as_of):
    led = Ledger([rec(10.0, as_of)])
    report = build_report(led, pricing, as_of=as_of)
    for key in ("generated_at", "currency", "summary", "session", "forecast"):
        assert key in report
    assert "day" in report["forecast"]
    assert "month" in report["forecast"]


def test_build_report_includes_budget_when_guard(pricing, as_of):
    led = Ledger([rec(10.0, as_of)])
    guard = BudgetGuard([BudgetRule(scope="global", limit_usd=100.0)])
    report = build_report(led, pricing, guard=guard, as_of=as_of)
    assert "budget" in report
    assert report["budget"]["overall"] == "ok"


def test_build_report_no_budget_without_guard(pricing, as_of):
    report = build_report(Ledger([rec(1.0, as_of)]), pricing, as_of=as_of)
    assert "budget" not in report


def test_build_report_empty_ledger(pricing, as_of):
    report = build_report(Ledger(), pricing, as_of=as_of)
    assert report["summary"]["records"] == 0
    assert report["summary"]["cost_usd"] == 0.0


def test_remaining_budget_shape(pricing, as_of):
    led = Ledger([rec(10.0, as_of)])
    lim = Limits(plan_allowance_usd=100, daily_limit_usd=20, weekly_limit_usd=50)
    rb = remaining_budget(led, pricing, limits=lim, as_of=as_of)
    for key in ("as_of", "currency", "status", "exit_code", "spent_today_usd",
                "spent_week_usd", "spent_lifetime_usd", "remaining_balance_usd",
                "extra_usage_usd", "remaining_usd"):
        assert key in rb


def test_remaining_budget_status_from_guard(pricing, as_of):
    led = Ledger([rec(15.0, as_of)])
    guard = BudgetGuard([BudgetRule(scope="global", limit_usd=10.0)])
    rb = remaining_budget(led, pricing, guard=guard, as_of=as_of)
    assert rb["status"] == "deny"
    assert rb["exit_code"] == 2


def test_remaining_budget_tightest(pricing, as_of):
    led = Ledger([rec(5.0, as_of)])
    guard = BudgetGuard([
        BudgetRule(scope="global", limit_usd=100.0, name="loose"),
        BudgetRule(scope="global", limit_usd=8.0, name="tight"),
    ])
    rb = remaining_budget(led, pricing, guard=guard, as_of=as_of)
    assert rb["tightest_budget"]["label"] == "tight"
    assert rb["remaining_usd"] == 3.0


def test_remaining_budget_fallback_to_daily(pricing, as_of):
    led = Ledger([rec(5.0, as_of)])
    lim = Limits(daily_limit_usd=20.0)
    rb = remaining_budget(led, pricing, limits=lim, as_of=as_of)
    assert rb["remaining_usd"] == 15.0


def test_remaining_budget_ok_status_default(pricing, as_of):
    rb = remaining_budget(Ledger(), pricing, as_of=as_of)
    assert rb["status"] == "ok"
    assert rb["exit_code"] == 0


def test_remaining_budget_spent_figures(pricing, as_of):
    led = Ledger([rec(10.0, as_of)])
    rb = remaining_budget(led, pricing, as_of=as_of)
    assert rb["spent_today_usd"] == 10.0
    assert rb["spent_lifetime_usd"] == 10.0
