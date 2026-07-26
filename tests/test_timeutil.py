"""Timestamp normalization tests."""

from __future__ import annotations

from datetime import datetime, timezone, timedelta

import pytest

from spendwatch import timeutil as tu


@pytest.mark.parametrize(
    "value",
    [
        "2026-07-24T10:00:00Z",
        "2026-07-24T10:00:00+00:00",
        "2026-07-24 10:00:00",
        "2026-07-24T10:00:00",
    ],
)
def test_parse_iso_variants_to_utc(value):
    dt = tu.parse_timestamp(value)
    assert dt.tzinfo is not None
    assert dt.year == 2026 and dt.month == 7 and dt.day == 24
    assert dt.hour == 10


def test_parse_date_only():
    dt = tu.parse_timestamp("2026-07-24")
    assert (dt.year, dt.month, dt.day) == (2026, 7, 24)
    assert dt.hour == 0


def test_parse_offset_normalized_to_utc():
    dt = tu.parse_timestamp("2026-07-24T12:00:00+02:00")
    assert dt.hour == 10
    assert dt.utcoffset() == timedelta(0)


@pytest.mark.parametrize(
    "epoch,expected_year",
    [
        (1785492000, 2026),
        (0, 1970),
        (1000000000, 2001),
    ],
)
def test_parse_epoch_seconds(epoch, expected_year):
    dt = tu.parse_timestamp(epoch)
    assert dt.year == expected_year
    assert dt.tzinfo == timezone.utc


def test_parse_epoch_millis_detected():
    ms = 1785492000000
    dt = tu.parse_timestamp(ms)
    assert dt.year == 2026


def test_parse_epoch_float():
    dt = tu.parse_timestamp(1785492000.5)
    assert dt.year == 2026


@pytest.mark.parametrize("value", [None, ""])
def test_parse_empty_uses_default(value):
    default = datetime(2020, 1, 1, tzinfo=timezone.utc)
    assert tu.parse_timestamp(value, default=default) == default


def test_parse_empty_without_default_is_now():
    before = tu.now_utc()
    dt = tu.parse_timestamp(None)
    after = tu.now_utc()
    assert before <= dt <= after


def test_parse_naive_datetime_gets_utc():
    naive = datetime(2026, 7, 24, 10, 0, 0)
    dt = tu.parse_timestamp(naive)
    assert dt.tzinfo == timezone.utc
    assert dt.hour == 10


def test_parse_aware_datetime_converted():
    aware = datetime(2026, 7, 24, 12, 0, 0, tzinfo=timezone(timedelta(hours=3)))
    dt = tu.parse_timestamp(aware)
    assert dt.hour == 9


def test_parse_bool_raises():
    with pytest.raises(ValueError):
        tu.parse_timestamp(True)


def test_parse_garbage_string_raises():
    with pytest.raises(ValueError):
        tu.parse_timestamp("not a date")


def test_parse_unknown_type_raises():
    with pytest.raises(ValueError):
        tu.parse_timestamp(object())


def test_to_iso_roundtrip():
    dt = datetime(2026, 7, 24, 10, 30, 15, tzinfo=timezone.utc)
    assert tu.to_iso(dt) == "2026-07-24T10:30:15Z"


@pytest.mark.parametrize(
    "dt,expected",
    [
        (datetime(2026, 7, 24, 10, tzinfo=timezone.utc), "2026-07-24"),
        (datetime(2026, 1, 1, 0, tzinfo=timezone.utc), "2026-01-01"),
        (datetime(2026, 12, 31, 23, 59, tzinfo=timezone.utc), "2026-12-31"),
    ],
)
def test_day_key(dt, expected):
    assert tu.day_key(dt) == expected


@pytest.mark.parametrize(
    "dt,expected",
    [
        (datetime(2026, 7, 24, tzinfo=timezone.utc), "2026-07"),
        (datetime(2026, 1, 15, tzinfo=timezone.utc), "2026-01"),
    ],
)
def test_month_key(dt, expected):
    assert tu.month_key(dt) == expected


def test_week_key_format():
    wk = tu.week_key(datetime(2026, 7, 24, tzinfo=timezone.utc))
    assert wk.startswith("2026-W")
    assert len(wk.split("W")[1]) == 2


def test_start_of_day():
    dt = datetime(2026, 7, 24, 15, 30, 45, tzinfo=timezone.utc)
    s = tu.start_of_day(dt)
    assert (s.hour, s.minute, s.second, s.microsecond) == (0, 0, 0, 0)
    assert s.day == 24


def test_start_of_month():
    dt = datetime(2026, 7, 24, 15, tzinfo=timezone.utc)
    s = tu.start_of_month(dt)
    assert s.day == 1 and s.hour == 0


def test_end_of_day():
    dt = datetime(2026, 7, 24, 5, tzinfo=timezone.utc)
    e = tu.end_of_day(dt)
    assert e.hour == 23 and e.minute == 59 and e.second == 59


@pytest.mark.parametrize(
    "dt,expected_last_day",
    [
        (datetime(2026, 7, 10, tzinfo=timezone.utc), 31),
        (datetime(2026, 2, 10, tzinfo=timezone.utc), 28),
        (datetime(2024, 2, 10, tzinfo=timezone.utc), 29),  # leap
        (datetime(2026, 12, 10, tzinfo=timezone.utc), 31),
        (datetime(2026, 4, 10, tzinfo=timezone.utc), 30),
    ],
)
def test_end_of_month(dt, expected_last_day):
    e = tu.end_of_month(dt)
    assert e.day == expected_last_day
    assert e.hour == 23 and e.minute == 59


def test_end_of_month_december_rollover():
    e = tu.end_of_month(datetime(2026, 12, 15, tzinfo=timezone.utc))
    assert e.month == 12 and e.year == 2026 and e.day == 31


def test_now_utc_is_aware():
    assert tu.now_utc().tzinfo == timezone.utc
