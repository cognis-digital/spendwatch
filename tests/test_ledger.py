"""Ledger aggregation / grouping tests."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from spendwatch.ledger import Ledger
from spendwatch.schema import UsageRecord


def r(**kw):
    base = dict(provider="anthropic", model="claude-sonnet-4",
                timestamp=datetime(2026, 7, 24, 10, tzinfo=timezone.utc))
    base.update(kw)
    return UsageRecord(**base)


def test_empty_ledger(pricing):
    led = Ledger()
    assert len(led) == 0
    assert led.total_cost(pricing) == 0.0
    assert led.providers() == []
    assert led.span() == (None, None)


def test_add_and_extend():
    led = Ledger()
    led.add(r())
    led.extend([r(), r()])
    assert len(led) == 3


def test_iteration_and_index():
    led = Ledger([r(model="a"), r(model="b")])
    assert [x.model for x in led] == ["a", "b"]
    assert led[0].model == "a"


def test_len_matches(sample_ledger):
    assert len(sample_ledger) == 5


def test_distinct_keys(sample_ledger):
    assert sample_ledger.providers() == ["anthropic", "local", "openai", "openrouter"]
    assert "a" in sample_ledger.projects()
    assert "b" in sample_ledger.projects()


def test_tokens_aggregation(sample_ledger):
    toks = sample_ledger.tokens()
    assert toks["input_tokens"] == 10000 + 8000 + 3000 + 20000 + 5000
    assert toks["output_tokens"] == 2000 + 3000 + 1000 + 6000 + 2000
    assert toks["cached_tokens"] == 5000 + 2000
    assert toks["reasoning_tokens"] == 4000
    assert "total_tokens" in toks
    assert "billable_tokens" in toks


def test_total_tokens_matches_records(sample_ledger):
    assert sample_ledger.total_tokens() == sum(x.total_tokens for x in sample_ledger)


def test_filter(sample_ledger):
    openai_only = sample_ledger.by_provider_name("openai")
    assert len(openai_only) == 2
    assert all(x.provider == "openai" for x in openai_only)


def test_by_project(sample_ledger):
    proj_a = sample_ledger.by_project_name("a")
    assert len(proj_a) == 3


def test_by_model(sample_ledger):
    m = sample_ledger.by_model_name("gpt-4o")
    assert len(m) == 1


def test_since_until_between(sample_ledger):
    cut = datetime(2026, 7, 24, 0, tzinfo=timezone.utc)
    assert len(sample_ledger.since(cut)) == 4  # one record is on 07-23
    assert len(sample_ledger.until(cut)) == 1
    start = datetime(2026, 7, 24, 10, 30, tzinfo=timezone.utc)
    end = datetime(2026, 7, 24, 12, 30, tzinfo=timezone.utc)
    assert len(sample_ledger.between(start, end)) == 2


def test_cost_by_provider_sums(sample_ledger, pricing):
    by_p = sample_ledger.cost_by_provider(pricing)
    assert set(by_p) == {"anthropic", "openai", "openrouter", "local"}
    assert sum(by_p.values()) == pytest.approx(sample_ledger.total_cost(pricing))


def test_cost_by_model(sample_ledger, pricing):
    by_m = sample_ledger.cost_by_model(pricing)
    assert "gpt-4o" in by_m
    assert by_m["llama3.1:8b"] == 0.0


def test_cost_by_project(sample_ledger, pricing):
    by_proj = sample_ledger.cost_by_project(pricing)
    assert set(by_proj) == {"a", "b"}


def test_cost_by_day(sample_ledger, pricing):
    by_day = sample_ledger.cost_by_day(pricing)
    assert "2026-07-24" in by_day
    assert "2026-07-23" in by_day


def test_cost_by_month(sample_ledger, pricing):
    by_month = sample_ledger.cost_by_month(pricing)
    assert "2026-07" in by_month


def test_days_sorted(sample_ledger):
    assert sample_ledger.days() == ["2026-07-23", "2026-07-24"]


def test_span(sample_ledger):
    lo, hi = sample_ledger.span()
    assert lo < hi


def test_sorted():
    led = Ledger([
        r(timestamp=datetime(2026, 7, 24, 12, tzinfo=timezone.utc), model="late"),
        r(timestamp=datetime(2026, 7, 24, 8, tzinfo=timezone.utc), model="early"),
    ])
    s = led.sorted()
    assert s[0].model == "early"


def test_to_dicts_and_from_dicts(sample_ledger):
    dicts = sample_ledger.to_dicts()
    assert len(dicts) == 5
    led2 = Ledger.from_dicts(dicts)
    assert len(led2) == 5
    assert led2.providers() == sample_ledger.providers()


def test_summary_shape(sample_ledger, pricing):
    s = sample_ledger.summary(pricing)
    for key in ("records", "providers", "models", "projects", "tokens",
                "cost_usd", "cost_breakdown", "cost_by_provider",
                "cost_by_model", "cost_by_project", "cost_by_day"):
        assert key in s
    assert s["records"] == 5


def test_summary_cost_consistency(sample_ledger, pricing):
    s = sample_ledger.summary(pricing)
    assert s["cost_usd"] == pytest.approx(s["cost_breakdown"]["total"])


def test_prefer_reported_changes_total():
    led = Ledger([r(model="gpt-4o", provider="openai", input_tokens=1_000_000, cost_usd=50.0)])
    from spendwatch.pricing import PricingTable
    p = PricingTable.default_table()
    assert led.total_cost(p, prefer_reported=False) == 2.5
    assert led.total_cost(p, prefer_reported=True) == 50.0
