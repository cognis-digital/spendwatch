"""Budget-guard tests: thresholds, scopes, periods, exit codes."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from spendwatch.budget import (
    BudgetRule, BudgetGuard, GuardReport, classify, evaluate_rule,
    OK, WARN, DENY, EXIT_OK, EXIT_WARN, EXIT_DENY, BudgetError,
)
from spendwatch.ledger import Ledger
from spendwatch.pricing import PricingTable
from spendwatch.schema import UsageRecord


@pytest.fixture
def pricing():
    return PricingTable.default_table()


def spend_ledger(cost_usd, model="gpt-4o", provider="openai", project="p",
                 when=datetime(2026, 7, 24, 10, tzinfo=timezone.utc)):
    """A ledger whose total computed cost equals cost_usd (via gpt-4o input @2.5/M)."""
    tokens = int(round(cost_usd / 2.5 * 1_000_000))
    return Ledger([UsageRecord(provider=provider, model=model, project=project,
                               input_tokens=tokens, timestamp=when)])


# -- classify (the core threshold logic) ----------------------------------
@pytest.mark.parametrize(
    "spent,warn,deny,limit,expected",
    [
        (0, 8, 10, 10, OK),        # zero spend always OK
        (5, 8, 10, 10, OK),        # below warn
        (7.99, 8, 10, 10, OK),
        (8, 8, 10, 10, WARN),      # at warn threshold
        (9, 8, 10, 10, WARN),
        (9.99, 8, 10, 10, WARN),
        (10, 8, 10, 10, DENY),     # at deny threshold
        (11, 8, 10, 10, DENY),     # over
        (1000, 8, 10, 10, DENY),   # huge overspend
        (0, 0, 0, 0, OK),          # zero cap, zero spend
        (0.01, 0, 0, 0, DENY),     # zero cap, any spend denies
        (5, 0, 10, 10, WARN),      # warn=0 -> any positive spend warns (below deny)
    ],
)
def test_classify(spent, warn, deny, limit, expected):
    assert classify(spent, warn, deny, limit) == expected


def test_classify_negative_spend_is_ok():
    assert classify(-5, 8, 10, 10) == OK


# -- rule construction / validation ---------------------------------------
def test_rule_defaults():
    rule = BudgetRule(scope="global", limit_usd=10.0)
    assert rule.warn_ratio == 0.8
    assert rule.deny_ratio == 1.0
    assert rule.warn_usd == 8.0
    assert rule.deny_usd == 10.0


@pytest.mark.parametrize("scope", ["global", "project", "model", "provider", "day"])
def test_valid_scopes(scope):
    assert BudgetRule(scope=scope, limit_usd=1.0).scope == scope


def test_invalid_scope_raises():
    with pytest.raises(BudgetError):
        BudgetRule(scope="bogus", limit_usd=1.0)


@pytest.mark.parametrize("period", ["all", "day", "month"])
def test_valid_periods(period):
    assert BudgetRule(scope="global", limit_usd=1.0, period=period).period == period


def test_invalid_period_raises():
    with pytest.raises(BudgetError):
        BudgetRule(scope="global", limit_usd=1.0, period="year")


def test_negative_limit_raises():
    with pytest.raises(BudgetError):
        BudgetRule(scope="global", limit_usd=-1.0)


def test_warn_above_deny_raises():
    with pytest.raises(BudgetError):
        BudgetRule(scope="global", limit_usd=10.0, warn_ratio=1.1, deny_ratio=1.0)


def test_negative_ratio_raises():
    with pytest.raises(BudgetError):
        BudgetRule(scope="global", limit_usd=10.0, warn_ratio=-0.1)


@pytest.mark.parametrize(
    "limit,warn_ratio,deny_ratio,expected_warn,expected_deny",
    [
        (100, 0.8, 1.0, 80.0, 100.0),
        (50, 0.5, 0.9, 25.0, 45.0),
        (10, 0.0, 1.0, 0.0, 10.0),
        (200, 0.9, 1.5, 180.0, 300.0),  # deny above 100%
    ],
)
def test_rule_thresholds(limit, warn_ratio, deny_ratio, expected_warn, expected_deny):
    rule = BudgetRule(scope="global", limit_usd=limit, warn_ratio=warn_ratio, deny_ratio=deny_ratio)
    assert rule.warn_usd == expected_warn
    assert rule.deny_usd == expected_deny


def test_rule_label():
    assert BudgetRule(scope="project", key="alpha", limit_usd=1.0, period="day").label == "project:alpha:day"
    assert BudgetRule(scope="global", limit_usd=1.0).label == "global:*:all"
    assert BudgetRule(scope="global", limit_usd=1.0, name="my-cap").label == "my-cap"


def test_rule_from_dict_limit_alias():
    rule = BudgetRule.from_dict({"scope": "global", "limit": 15.0})
    assert rule.limit_usd == 15.0


def test_rule_to_dict_roundtrip():
    rule = BudgetRule(scope="model", key="gpt-4o", limit_usd=5.0, warn_ratio=0.7)
    d = rule.to_dict()
    rebuilt = BudgetRule.from_dict(d)
    assert rebuilt.limit_usd == 5.0
    assert rebuilt.warn_ratio == 0.7


# -- evaluate single rule -------------------------------------------------
@pytest.mark.parametrize(
    "cost,expected",
    [(3.0, OK), (8.0, WARN), (9.5, WARN), (10.0, DENY), (25.0, DENY)],
)
def test_evaluate_global_rule(pricing, cost, expected):
    rule = BudgetRule(scope="global", limit_usd=10.0)
    led = spend_ledger(cost)
    statuses = evaluate_rule(rule, led, pricing)
    assert len(statuses) == 1
    assert statuses[0].status == expected


def test_evaluate_project_specific(pricing):
    rule = BudgetRule(scope="project", key="alpha", limit_usd=10.0)
    led = Ledger([
        UsageRecord(provider="openai", model="gpt-4o", project="alpha",
                    input_tokens=4_000_000),  # $10 -> deny
        UsageRecord(provider="openai", model="gpt-4o", project="beta",
                    input_tokens=1_000_000),  # not counted
    ])
    statuses = evaluate_rule(rule, led, pricing)
    assert len(statuses) == 1
    assert statuses[0].key == "alpha"
    assert statuses[0].status == DENY


def test_evaluate_per_entity_scope_all_keys(pricing):
    # key=None on project scope -> one status per project
    rule = BudgetRule(scope="project", limit_usd=5.0)
    led = Ledger([
        UsageRecord(provider="openai", model="gpt-4o", project="a", input_tokens=1_000_000),  # $2.5 ok
        UsageRecord(provider="openai", model="gpt-4o", project="b", input_tokens=4_000_000),  # $10 deny
    ])
    statuses = evaluate_rule(rule, led, pricing)
    by_key = {s.key: s.status for s in statuses}
    assert by_key["a"] == OK
    assert by_key["b"] == DENY


def test_evaluate_model_scope_all(pricing):
    rule = BudgetRule(scope="model", limit_usd=1.0)
    led = Ledger([
        UsageRecord(provider="openai", model="gpt-4o", input_tokens=1_000_000),  # $2.5 deny
        UsageRecord(provider="local", model="llama3.1:8b", input_tokens=1_000_000),  # $0 ok
    ])
    statuses = evaluate_rule(rule, led, pricing)
    by_key = {s.key: s.status for s in statuses}
    assert by_key["gpt-4o"] == DENY
    assert by_key["llama3.1:8b"] == OK


def test_evaluate_provider_scope(pricing):
    rule = BudgetRule(scope="provider", key="openai", limit_usd=1.0)
    led = spend_ledger(2.5, provider="openai")
    statuses = evaluate_rule(rule, led, pricing)
    assert statuses[0].status == DENY


def test_evaluate_empty_ledger_per_entity(pricing):
    rule = BudgetRule(scope="project", limit_usd=5.0)
    statuses = evaluate_rule(rule, Ledger(), pricing)
    assert len(statuses) == 1
    assert statuses[0].status == OK


def test_status_fields(pricing):
    rule = BudgetRule(scope="global", limit_usd=10.0)
    st = evaluate_rule(rule, spend_ledger(4.0), pricing)[0]
    assert st.spent_usd == 4.0
    assert st.limit_usd == 10.0
    assert st.remaining_usd == 6.0
    assert st.ratio == pytest.approx(0.4)


def test_status_ratio_infinite_on_zero_cap(pricing):
    rule = BudgetRule(scope="global", limit_usd=0.0)
    st = evaluate_rule(rule, spend_ledger(5.0), pricing)[0]
    assert st.ratio == float("inf")
    assert st.status == DENY


# -- period windows -------------------------------------------------------
def test_day_period_filters(pricing):
    as_of = datetime(2026, 7, 24, 15, tzinfo=timezone.utc)
    rule = BudgetRule(scope="global", limit_usd=5.0, period="day")
    led = Ledger([
        spend_ledger(10.0, when=datetime(2026, 7, 23, 10, tzinfo=timezone.utc))[0],  # yesterday
        spend_ledger(2.0, when=datetime(2026, 7, 24, 10, tzinfo=timezone.utc))[0],   # today
    ])
    st = evaluate_rule(rule, led, pricing, as_of=as_of)[0]
    assert st.spent_usd == 2.0
    assert st.status == OK


def test_month_period_filters(pricing):
    as_of = datetime(2026, 7, 24, 15, tzinfo=timezone.utc)
    rule = BudgetRule(scope="global", limit_usd=5.0, period="month")
    led = Ledger([
        spend_ledger(10.0, when=datetime(2026, 6, 30, 10, tzinfo=timezone.utc))[0],  # last month
        spend_ledger(3.0, when=datetime(2026, 7, 1, 10, tzinfo=timezone.utc))[0],    # this month
    ])
    st = evaluate_rule(rule, led, pricing, as_of=as_of)[0]
    assert st.spent_usd == 3.0


# -- guard aggregation & exit codes ---------------------------------------
def test_guard_all_ok_exit_zero(pricing):
    guard = BudgetGuard([BudgetRule(scope="global", limit_usd=100.0)])
    report = guard.evaluate(spend_ledger(5.0), pricing)
    assert report.overall == OK
    assert report.exit_code == EXIT_OK


def test_guard_warn_exit_zero_by_default(pricing):
    guard = BudgetGuard([BudgetRule(scope="global", limit_usd=10.0)])
    report = guard.evaluate(spend_ledger(9.0), pricing)
    assert report.overall == WARN
    assert report.exit_code == EXIT_OK


def test_guard_warn_exit_one_when_strict(pricing):
    guard = BudgetGuard([BudgetRule(scope="global", limit_usd=10.0)], strict_warn=True)
    report = guard.evaluate(spend_ledger(9.0), pricing)
    assert report.overall == WARN
    assert report.exit_code == EXIT_WARN


def test_guard_deny_exit_two(pricing):
    guard = BudgetGuard([BudgetRule(scope="global", limit_usd=10.0)])
    report = guard.evaluate(spend_ledger(15.0), pricing)
    assert report.overall == DENY
    assert report.exit_code == EXIT_DENY
    assert not report.ok


def test_guard_deny_wins_over_warn(pricing):
    guard = BudgetGuard([
        BudgetRule(scope="global", limit_usd=100.0, name="loose"),   # ok
        BudgetRule(scope="global", limit_usd=10.0, name="mid"),      # warn at 9
        BudgetRule(scope="global", limit_usd=8.0, name="tight"),     # deny at 9
    ])
    report = guard.evaluate(spend_ledger(9.0), pricing)
    assert report.overall == DENY
    assert report.exit_code == EXIT_DENY


def test_guard_empty_is_ok(pricing):
    report = BudgetGuard().evaluate(spend_ledger(1000.0), pricing)
    assert report.overall == OK
    assert report.exit_code == EXIT_OK


def test_guard_denied_and_warned_lists(pricing):
    guard = BudgetGuard([
        BudgetRule(scope="global", limit_usd=8.0, name="tight"),
        BudgetRule(scope="global", limit_usd=12.0, name="mid"),
    ])
    report = guard.evaluate(spend_ledger(10.0), pricing)
    labels_denied = [s.rule.label for s in report.denied]
    labels_warned = [s.rule.label for s in report.warned]
    assert "tight" in labels_denied
    assert "mid" in labels_warned


def test_guard_add_validates():
    guard = BudgetGuard()
    with pytest.raises(BudgetError):
        guard.add("not a rule")


def test_guard_from_config(pricing):
    guard = BudgetGuard.from_config({
        "strict_warn": True,
        "rules": [
            {"scope": "global", "limit_usd": 10.0},
            {"scope": "project", "key": "a", "limit": 5.0},
        ],
    })
    assert guard.strict_warn is True
    assert len(guard.rules) == 2


def test_guard_to_dict_roundtrip():
    guard = BudgetGuard([BudgetRule(scope="global", limit_usd=10.0)], strict_warn=True)
    d = guard.to_dict()
    rebuilt = BudgetGuard.from_config(d)
    assert rebuilt.strict_warn is True
    assert rebuilt.rules[0].limit_usd == 10.0


def test_report_to_dict(pricing):
    guard = BudgetGuard([BudgetRule(scope="global", limit_usd=10.0)])
    d = guard.evaluate(spend_ledger(15.0), pricing).to_dict()
    assert d["overall"] == DENY
    assert d["exit_code"] == EXIT_DENY
    assert isinstance(d["statuses"], list)
    assert d["denied"]


def test_status_to_dict_fields(pricing):
    guard = BudgetGuard([BudgetRule(scope="project", key="p", limit_usd=10.0, period="day")])
    d = guard.evaluate(spend_ledger(4.0), pricing).to_dict()
    st = d["statuses"][0]
    for key in ("label", "scope", "key", "period", "spent_usd", "limit_usd",
                "warn_usd", "deny_usd", "status", "ratio", "remaining_usd"):
        assert key in st


@pytest.mark.parametrize(
    "cost,limit,warn_ratio,deny_ratio,expected_status,expected_exit",
    [
        (5, 10, 0.8, 1.0, OK, 0),
        (8, 10, 0.8, 1.0, WARN, 0),
        (10, 10, 0.8, 1.0, DENY, 2),
        (2, 10, 0.1, 0.5, WARN, 0),
        (6, 10, 0.1, 0.5, DENY, 2),
        (0, 10, 0.8, 1.0, OK, 0),
    ],
)
def test_end_to_end_threshold_matrix(pricing, cost, limit, warn_ratio, deny_ratio,
                                     expected_status, expected_exit):
    guard = BudgetGuard([BudgetRule(scope="global", limit_usd=limit,
                                    warn_ratio=warn_ratio, deny_ratio=deny_ratio)])
    report = guard.evaluate(spend_ledger(cost), pricing)
    assert report.overall == expected_status
    assert report.exit_code == expected_exit


def test_prefer_reported_in_guard():
    guard = BudgetGuard([BudgetRule(scope="global", limit_usd=10.0)])
    led = Ledger([UsageRecord(provider="openrouter", model="x",
                              input_tokens=1_000_000, cost_usd=50.0)])
    p = PricingTable.default_table()
    # computed cost is small; reported is 50 -> deny
    assert guard.evaluate(led, p, prefer_reported=False).overall != DENY
    assert guard.evaluate(led, p, prefer_reported=True).overall == DENY
