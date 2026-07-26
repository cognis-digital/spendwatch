"""Burn-rate forecasting tests."""

from __future__ import annotations

from datetime import datetime, timezone, timedelta

import pytest

from spendwatch import forecast as fc


@pytest.mark.parametrize(
    "spent,elapsed_s,expected",
    [
        (10.0, 3600, 10.0),      # $10 in 1h -> $10/h
        (10.0, 7200, 5.0),       # $10 in 2h -> $5/h
        (0.0, 3600, 0.0),
        (5.0, 0, 0.0),           # no elapsed time -> 0
        (1.0, 1800, 2.0),        # $1 in 30min -> $2/h
    ],
)
def test_burn_rate(spent, elapsed_s, expected):
    assert fc.burn_rate(spent, elapsed_s) == expected


def test_forecast_day_midday():
    # at 12:00 UTC, exactly half the day elapsed
    as_of = datetime(2026, 7, 24, 12, 0, 0, tzinfo=timezone.utc)
    f = fc.forecast_period(10.0, "day", as_of=as_of)
    assert f.period == "day"
    assert f.spent_usd == 10.0
    assert f.elapsed_fraction == pytest.approx(0.5, abs=0.01)
    # projected roughly double
    assert f.projected_total_usd == pytest.approx(20.0, rel=0.01)


def test_forecast_day_quarter():
    as_of = datetime(2026, 7, 24, 6, 0, 0, tzinfo=timezone.utc)
    f = fc.forecast_period(5.0, "day", as_of=as_of)
    assert f.projected_total_usd == pytest.approx(20.0, rel=0.02)


def test_forecast_start_of_day_no_elapsed():
    as_of = datetime(2026, 7, 24, 0, 0, 0, tzinfo=timezone.utc)
    f = fc.forecast_period(0.0, "day", as_of=as_of)
    assert f.elapsed_seconds == 0.0
    assert f.projected_total_usd == 0.0


def test_forecast_projection_never_below_spent():
    as_of = datetime(2026, 7, 24, 23, 59, 0, tzinfo=timezone.utc)
    f = fc.forecast_period(100.0, "day", as_of=as_of)
    assert f.projected_total_usd >= 100.0


def test_forecast_month():
    as_of = datetime(2026, 7, 15, 12, 0, 0, tzinfo=timezone.utc)
    f = fc.forecast_period(100.0, "month", as_of=as_of)
    assert f.period == "month"
    # 14.5 of 31 days elapsed -> 100 * 31/14.5 ~= 213.8 projected
    assert f.projected_total_usd == pytest.approx(213.79, rel=0.02)


def test_forecast_bad_period():
    with pytest.raises(ValueError):
        fc.forecast_period(1.0, "year")


def test_forecast_to_dict():
    as_of = datetime(2026, 7, 24, 12, tzinfo=timezone.utc)
    d = fc.forecast_period(10.0, "day", as_of=as_of).to_dict()
    for key in ("period", "spent_usd", "elapsed_seconds", "total_seconds",
                "elapsed_fraction", "burn_per_hour", "burn_per_day",
                "projected_total_usd", "projected_remaining_usd", "remaining_seconds"):
        assert key in d


def test_projected_remaining_nonneg():
    as_of = datetime(2026, 7, 24, 23, 59, tzinfo=timezone.utc)
    f = fc.forecast_period(100.0, "day", as_of=as_of)
    assert f.projected_remaining_usd >= 0.0


def test_burn_per_day_is_24x_hour():
    as_of = datetime(2026, 7, 24, 12, tzinfo=timezone.utc)
    f = fc.forecast_period(10.0, "day", as_of=as_of)
    assert f.burn_per_day == pytest.approx(f.burn_per_hour * 24, rel=0.001)


@pytest.mark.parametrize(
    "spent,cap,burn,expected",
    [
        (5.0, 10.0, 5.0, 3600.0),   # $5 left at $5/h -> 1h
        (0.0, 10.0, 10.0, 3600.0),
        (10.0, 10.0, 5.0, 0.0),     # already at cap
        (15.0, 10.0, 5.0, 0.0),     # over cap
        (5.0, 10.0, 0.0, None),     # no burn -> never
    ],
)
def test_seconds_to_cap(spent, cap, burn, expected):
    assert fc.seconds_to_cap(spent, cap, burn) == expected


def test_eta_to_cap():
    as_of = datetime(2026, 7, 24, 12, tzinfo=timezone.utc)
    eta = fc.eta_to_cap(5.0, 10.0, 5.0, as_of=as_of)
    assert eta == as_of + timedelta(hours=1)


def test_eta_to_cap_none_when_no_burn():
    assert fc.eta_to_cap(5.0, 10.0, 0.0) is None


def test_elapsed_fraction_zero_total():
    f = fc.Forecast(period="day", spent_usd=0, elapsed_seconds=0, total_seconds=0,
                    burn_per_hour=0, burn_per_day=0, projected_total_usd=0,
                    remaining_seconds=0)
    assert f.elapsed_fraction == 0.0


def test_as_of_before_window_clamped():
    # as_of before start_of_day is clamped to start
    as_of = datetime(2026, 7, 24, 0, 0, tzinfo=timezone.utc)
    f = fc.forecast_period(0.0, "day", as_of=as_of)
    assert f.elapsed_seconds >= 0
