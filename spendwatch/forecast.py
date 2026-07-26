"""Burn-rate forecasting.

Given spend accumulated so far within a period (day or month) and how far into
that period we are, project the end-of-period total by linear extrapolation of
the current burn rate, and estimate when a cap will be hit.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from . import money
from .timeutil import (
    now_utc,
    start_of_day,
    start_of_month,
    end_of_day,
    end_of_month,
)


@dataclass
class Forecast:
    period: str
    spent_usd: float
    elapsed_seconds: float
    total_seconds: float
    burn_per_hour: float
    burn_per_day: float
    projected_total_usd: float
    remaining_seconds: float

    @property
    def elapsed_fraction(self) -> float:
        if self.total_seconds <= 0:
            return 0.0
        return round(self.elapsed_seconds / self.total_seconds, 6)

    @property
    def projected_remaining_usd(self) -> float:
        return money.clamp_nonneg(money.round_usd(self.projected_total_usd - self.spent_usd))

    def to_dict(self) -> dict:
        return {
            "period": self.period,
            "spent_usd": self.spent_usd,
            "elapsed_seconds": round(self.elapsed_seconds, 3),
            "total_seconds": round(self.total_seconds, 3),
            "elapsed_fraction": self.elapsed_fraction,
            "burn_per_hour": self.burn_per_hour,
            "burn_per_day": self.burn_per_day,
            "projected_total_usd": self.projected_total_usd,
            "projected_remaining_usd": self.projected_remaining_usd,
            "remaining_seconds": round(self.remaining_seconds, 3),
        }


def _bounds(period: str, as_of):
    if period == "day":
        return start_of_day(as_of), end_of_day(as_of)
    if period == "month":
        return start_of_month(as_of), end_of_month(as_of)
    raise ValueError(f"period must be 'day' or 'month', got {period!r}")


def burn_rate(spent_usd: float, elapsed_seconds: float) -> float:
    """USD per hour given spend over an elapsed window."""
    if elapsed_seconds <= 0:
        return 0.0
    per_hour = spent_usd / elapsed_seconds * 3600.0
    return money.round_usd(per_hour)


def forecast_period(spent_usd: float, period: str = "day", as_of=None) -> Forecast:
    """Project period-end spend from spend-so-far and elapsed time."""
    as_of = as_of or now_utc()
    start, end = _bounds(period, as_of)
    total_seconds = (end - start).total_seconds()
    # clamp as_of into the window
    if as_of < start:
        as_of = start
    if as_of > end:
        as_of = end
    elapsed_seconds = (as_of - start).total_seconds()
    elapsed_seconds = max(elapsed_seconds, 0.0)

    spent_usd = money.round_usd(spent_usd)
    per_hour = burn_rate(spent_usd, elapsed_seconds)
    per_day = money.round_usd(per_hour * 24.0)

    if elapsed_seconds <= 0:
        projected = spent_usd
    else:
        projected = money.round_usd(spent_usd / elapsed_seconds * total_seconds)
    if projected < spent_usd:
        projected = spent_usd

    remaining_seconds = max(total_seconds - elapsed_seconds, 0.0)
    return Forecast(
        period=period,
        spent_usd=spent_usd,
        elapsed_seconds=elapsed_seconds,
        total_seconds=total_seconds,
        burn_per_hour=per_hour,
        burn_per_day=per_day,
        projected_total_usd=projected,
        remaining_seconds=remaining_seconds,
    )


def seconds_to_cap(spent_usd: float, cap_usd: float, burn_per_hour: float):
    """Seconds until ``cap_usd`` is reached at the current burn rate.

    Returns ``0.0`` if already at/over the cap, ``None`` if burn is zero
    (cap never reached).
    """
    if spent_usd >= cap_usd:
        return 0.0
    if burn_per_hour <= 0:
        return None
    remaining = cap_usd - spent_usd
    hours = remaining / burn_per_hour
    return round(hours * 3600.0, 3)


def eta_to_cap(spent_usd: float, cap_usd: float, burn_per_hour: float, as_of=None):
    """Absolute datetime a cap is projected to be hit, or ``None``."""
    secs = seconds_to_cap(spent_usd, cap_usd, burn_per_hour)
    if secs is None:
        return None
    as_of = as_of or now_utc()
    return as_of + timedelta(seconds=secs)
