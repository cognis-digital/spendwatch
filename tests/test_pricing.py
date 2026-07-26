"""Pricing resolution + cost-model tests."""

from __future__ import annotations

import pytest

from spendwatch.pricing import PricingTable, CostBreakdown, RATE_KEYS, PricingError
from spendwatch.schema import UsageRecord


@pytest.fixture
def table():
    return PricingTable.default_table()


def rec(model, provider="anthropic", **kw):
    return UsageRecord(provider=provider, model=model, **kw)


def test_load_default_table(table):
    assert table.currency == "USD"
    assert table.unit == "per_million_tokens"
    assert "gpt-4o" in table.models


def test_rate_keys_complete(table):
    for entry in table.models.values():
        for k in RATE_KEYS:
            assert k in entry


def test_invalid_table_raises():
    with pytest.raises(PricingError):
        PricingTable("not a dict")


def test_exact_model_match(table):
    rates = table.rates_for("gpt-4o")
    assert rates["input"] == 2.5
    assert rates["output"] == 10.0


@pytest.mark.parametrize(
    "model,expected_source",
    [
        ("gpt-4o", "model:gpt-4o"),
        ("gpt-4o-2024-08-06", "model-prefix:gpt-4o"),
        ("gpt-4o-mini", "model:gpt-4o-mini"),
        ("claude-opus-4-20250514", "model-prefix:claude-opus-4"),
        ("totally-unknown-model", "provider:anthropic"),
    ],
)
def test_resolution_source(table, model, expected_source):
    assert table.resolved_source(model, "anthropic") == expected_source


def test_prefix_longest_match_wins(table):
    # gpt-4o-mini must resolve to its own entry, not gpt-4o
    rates = table.rates_for("gpt-4o-mini")
    assert rates["input"] == 0.15


def test_unknown_model_known_provider_falls_to_provider(table):
    rates = table.rates_for("mystery", "openai")
    assert rates == table.providers["openai"]


def test_unknown_model_unknown_provider_falls_to_default(table):
    rates = table.rates_for("mystery", "no-such-provider")
    assert rates == table.default


def test_no_provider_falls_to_default(table):
    rates = table.rates_for("mystery")
    assert rates == table.default


@pytest.mark.parametrize(
    "model,input_tok,output_tok,expected",
    [
        ("gpt-4o", 1_000_000, 0, 2.5),
        ("gpt-4o", 0, 1_000_000, 10.0),
        ("claude-sonnet-4", 1_000_000, 0, 3.0),
        ("claude-sonnet-4", 0, 1_000_000, 15.0),
        ("claude-opus-4", 1_000_000, 1_000_000, 90.0),
        ("gpt-4o-mini", 1_000_000, 1_000_000, 0.75),
    ],
)
def test_input_output_cost(table, model, input_tok, output_tok, expected):
    r = rec(model, input_tokens=input_tok, output_tokens=output_tok)
    assert table.cost(r) == expected


def test_cached_tokens_priced_separately(table):
    r = rec("claude-sonnet-4", cached_tokens=1_000_000)
    assert table.cost(r) == 0.3


def test_cache_write_priced_separately(table):
    r = rec("claude-sonnet-4", cache_write_tokens=1_000_000)
    assert table.cost(r) == 3.75


def test_reasoning_tokens_priced(table):
    r = rec("o3-mini", provider="openai", reasoning_tokens=1_000_000)
    assert table.cost(r) == 4.4


def test_embedding_tokens_priced(table):
    r = rec("text-embedding-3-large", provider="openai", embedding_tokens=1_000_000)
    assert table.cost(r) == 0.13


def test_image_priced_per_unit(table):
    r = rec("gpt-4o", provider="openai", images=10)
    # gpt-4o image rate 0.003825
    assert table.cost(r) == pytest.approx(0.03825)


def test_zero_usage_zero_cost(table):
    assert table.cost(rec("gpt-4o")) == 0.0


def test_breakdown_sums_to_cost(table):
    r = rec("claude-sonnet-4", input_tokens=12000, output_tokens=3400,
            cached_tokens=8000, cache_write_tokens=1500, images=1)
    bd = table.breakdown(r)
    assert isinstance(bd, CostBreakdown)
    assert bd.total == table.cost(r)


def test_breakdown_fields(table):
    r = rec("claude-sonnet-4", input_tokens=1_000_000, output_tokens=1_000_000)
    bd = table.breakdown(r)
    assert bd.input == 3.0
    assert bd.output == 15.0
    assert bd.cached == 0.0


def test_breakdown_to_dict_has_total(table):
    bd = table.breakdown(rec("gpt-4o", input_tokens=1000))
    d = bd.to_dict()
    assert "total" in d
    assert set(d) == {"input", "output", "cached", "cache_write", "reasoning",
                      "embedding", "image", "total"}


def test_breakdown_addition():
    a = CostBreakdown(input=1.0, output=2.0)
    b = CostBreakdown(input=0.5, image=1.0)
    c = a + b
    assert c.input == 1.5
    assert c.output == 2.0
    assert c.image == 1.0
    assert c.total == 4.5


def test_breakdown_many(table):
    recs = [rec("gpt-4o", input_tokens=1_000_000), rec("gpt-4o", output_tokens=1_000_000)]
    bd = table.breakdown_many(recs)
    assert bd.total == 12.5


def test_total_empty(table):
    assert table.total([]) == 0.0


def test_resolved_cost_prefers_reported_when_asked(table):
    r = rec("gpt-4o", input_tokens=1_000_000, cost_usd=99.0)
    assert table.resolved_cost(r, prefer_reported=True) == 99.0
    assert table.resolved_cost(r, prefer_reported=False) == 2.5


def test_resolved_cost_reported_none_falls_back(table):
    r = rec("gpt-4o", input_tokens=1_000_000)
    assert table.resolved_cost(r, prefer_reported=True) == 2.5


def test_local_model_zero_cost(table):
    r = rec("llama3.1:8b", provider="local", input_tokens=1_000_000, output_tokens=1_000_000)
    assert table.cost(r) == 0.0


def test_custom_table_from_dict():
    t = PricingTable({
        "currency": "USD",
        "default": {"input": 5.0, "output": 5.0},
        "models": {"foo": {"input": 1.0, "output": 2.0}},
    })
    assert t.cost(rec("foo", provider="x", input_tokens=1_000_000)) == 1.0
    assert t.cost(rec("bar", provider="x", input_tokens=1_000_000)) == 5.0


def test_missing_rate_keys_default_zero():
    t = PricingTable({"models": {"foo": {"input": 3.0}}})
    r = rec("foo", provider="x", input_tokens=1_000_000, output_tokens=1_000_000)
    # output rate missing -> 0
    assert t.cost(r) == 3.0


def test_bad_rate_value_becomes_zero():
    t = PricingTable({"models": {"foo": {"input": "oops"}}})
    assert t.rates_for("foo")["input"] == 0.0


@pytest.mark.parametrize("model", [
    "claude-opus-4", "claude-sonnet-4", "claude-3-5-haiku",
    "gpt-4o", "gpt-4o-mini", "gpt-4.1", "o1", "o3", "o3-mini",
])
def test_all_known_models_resolve_exact(table, model):
    assert table.resolved_source(model) == f"model:{model}"


def test_huge_spend_precision(table):
    r = rec("claude-opus-4", input_tokens=1_000_000_000, output_tokens=1_000_000_000)
    # 15 * 1000 + 75 * 1000
    assert table.cost(r) == 90000.0
