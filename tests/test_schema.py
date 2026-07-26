"""UsageRecord normalization / serialization tests."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from spendwatch.schema import UsageRecord, TOKEN_FIELDS, _coerce_int


@pytest.mark.parametrize(
    "value,expected",
    [
        (5, 5),
        (5.4, 5),
        (5.6, 6),
        ("7", 7),
        ("7.9", 8),
        (None, 0),
        ("", 0),
        (-3, 0),
        (-2.5, 0),
        ("garbage", 0),
        (True, 1),
        (False, 0),
        ([], 0),
    ],
)
def test_coerce_int(value, expected):
    assert _coerce_int(value) == expected


def test_defaults_are_zero():
    r = UsageRecord(provider="p", model="m")
    for f in TOKEN_FIELDS:
        assert getattr(r, f) == 0
    assert r.images == 0
    assert r.project == "default"


def test_missing_provider_model_default_unknown():
    r = UsageRecord(provider="", model="")
    assert r.provider == "unknown"
    assert r.model == "unknown"


def test_none_project_defaults():
    r = UsageRecord(provider="p", model="m", project=None)
    assert r.project == "default"


@pytest.mark.parametrize(
    "kw,expected_total",
    [
        (dict(input_tokens=100, output_tokens=50), 150),
        (dict(input_tokens=100, output_tokens=50, cached_tokens=30), 180),
        (dict(cache_write_tokens=10, reasoning_tokens=5, embedding_tokens=2), 17),
        (dict(), 0),
    ],
)
def test_total_tokens(kw, expected_total):
    r = UsageRecord(provider="p", model="m", **kw)
    assert r.total_tokens == expected_total


def test_billable_tokens_excludes_cache_read_and_embedding():
    r = UsageRecord(
        provider="p", model="m",
        input_tokens=100, output_tokens=50, cached_tokens=1000,
        cache_write_tokens=10, reasoning_tokens=5, embedding_tokens=999,
    )
    assert r.billable_tokens == 100 + 50 + 10 + 5


def test_negative_tokens_clamped():
    r = UsageRecord(provider="p", model="m", input_tokens=-100, output_tokens=-1)
    assert r.input_tokens == 0
    assert r.output_tokens == 0


def test_string_timestamp_parsed():
    r = UsageRecord(provider="p", model="m", timestamp="2026-07-24T10:00:00Z")
    assert isinstance(r.timestamp, datetime)
    assert r.timestamp.tzinfo == timezone.utc


def test_epoch_timestamp_parsed():
    r = UsageRecord(provider="p", model="m", timestamp=1785492000)
    assert r.timestamp.year == 2026


def test_naive_timestamp_gets_utc():
    r = UsageRecord(provider="p", model="m", timestamp=datetime(2026, 7, 24, 10))
    assert r.timestamp.tzinfo == timezone.utc


def test_day_month_week_properties():
    r = UsageRecord(provider="p", model="m", timestamp="2026-07-24T10:00:00Z")
    assert r.day == "2026-07-24"
    assert r.month == "2026-07"
    assert r.week.startswith("2026-W")


def test_cost_usd_coercion():
    r = UsageRecord(provider="p", model="m", cost_usd="1.23")
    assert r.cost_usd == 1.23


def test_cost_usd_bad_becomes_none():
    r = UsageRecord(provider="p", model="m", cost_usd="not-a-number")
    assert r.cost_usd is None


def test_cost_usd_default_none():
    r = UsageRecord(provider="p", model="m")
    assert r.cost_usd is None


def test_to_dict_excludes_raw_by_default():
    r = UsageRecord(provider="p", model="m", raw={"x": 1})
    d = r.to_dict()
    assert "raw" not in d
    assert d["timestamp"].endswith("Z")


def test_to_dict_includes_raw_when_asked():
    r = UsageRecord(provider="p", model="m", raw={"x": 1})
    d = r.to_dict(include_raw=True)
    assert d["raw"] == {"x": 1}


def test_from_dict_roundtrip():
    r = UsageRecord(
        provider="openai", model="gpt-4o", input_tokens=100, output_tokens=50,
        timestamp="2026-07-24T10:00:00Z", project="a", request_id="r1",
    )
    d = r.to_dict()
    r2 = UsageRecord.from_dict(d)
    assert r2.provider == r.provider
    assert r2.model == r.model
    assert r2.input_tokens == 100
    assert r2.project == "a"
    assert r2.request_id == "r1"


def test_from_dict_unknown_fields_go_to_raw():
    r = UsageRecord.from_dict(
        {"provider": "p", "model": "m", "input_tokens": 5, "weird_field": 42}
    )
    assert r.raw.get("weird_field") == 42
    assert r.input_tokens == 5


def test_from_dict_merges_existing_raw():
    r = UsageRecord.from_dict(
        {"provider": "p", "model": "m", "raw": {"a": 1}, "extra": 2}
    )
    assert r.raw == {"a": 1, "extra": 2}


def test_float_tokens_rounded():
    r = UsageRecord(provider="p", model="m", input_tokens=99.6)
    assert r.input_tokens == 100
