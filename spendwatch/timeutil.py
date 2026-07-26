"""Timestamp normalization shared by every provider adapter.

Providers report time in wildly different shapes: ISO-8601 strings (with or
without ``Z``), epoch seconds (int or float), epoch milliseconds, or nothing at
all. Everything is coerced to a timezone-aware UTC :class:`datetime`.
"""

from __future__ import annotations

from datetime import datetime, timezone, date


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def parse_timestamp(value, default=None) -> datetime:
    """Coerce ``value`` into an aware UTC datetime.

    Accepts: datetime (naive treated as UTC), int/float epoch seconds or
    milliseconds, ISO-8601 string. ``None``/empty -> ``default`` (or now).
    """
    if value is None or value == "":
        return default if default is not None else now_utc()

    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    if isinstance(value, bool):
        raise ValueError("bool is not a timestamp")

    if isinstance(value, (int, float)):
        seconds = float(value)
        # Heuristic: values past ~ year 2200 in seconds are actually ms.
        if seconds > 1e11:
            seconds /= 1000.0
        return datetime.fromtimestamp(seconds, tz=timezone.utc)

    if isinstance(value, str):
        s = value.strip()
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        try:
            dt = datetime.fromisoformat(s)
        except ValueError:
            # Try a couple of common fallbacks.
            for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
                try:
                    dt = datetime.strptime(s, fmt)
                    break
                except ValueError:
                    continue
            else:
                raise ValueError(f"unrecognized timestamp: {value!r}")
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)

    raise ValueError(f"unrecognized timestamp type: {type(value).__name__}")


def to_iso(dt: datetime) -> str:
    """Canonical ISO-8601 with a trailing ``Z`` for UTC."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S") + "Z"


def day_key(dt: datetime) -> str:
    """UTC calendar day, ``YYYY-MM-DD``."""
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%d")


def month_key(dt: datetime) -> str:
    """UTC calendar month, ``YYYY-MM``."""
    return dt.astimezone(timezone.utc).strftime("%Y-%m")


def week_key(dt: datetime) -> str:
    """ISO week key, ``YYYY-Www`` (Monday-anchored)."""
    iso = dt.astimezone(timezone.utc).isocalendar()
    return f"{iso.year}-W{iso.week:02d}"


def start_of_day(dt: datetime) -> datetime:
    dt = dt.astimezone(timezone.utc)
    return dt.replace(hour=0, minute=0, second=0, microsecond=0)


def start_of_month(dt: datetime) -> datetime:
    dt = dt.astimezone(timezone.utc)
    return dt.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def end_of_day(dt: datetime) -> datetime:
    return start_of_day(dt).replace(hour=23, minute=59, second=59, microsecond=999999)


def end_of_month(dt: datetime) -> datetime:
    dt = dt.astimezone(timezone.utc)
    if dt.month == 12:
        nxt = dt.replace(year=dt.year + 1, month=1, day=1)
    else:
        nxt = dt.replace(month=dt.month + 1, day=1)
    nxt = start_of_day(nxt)
    from datetime import timedelta

    return nxt - timedelta(microseconds=1)
