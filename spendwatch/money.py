"""Deterministic currency math.

All monetary values in spendwatch are USD floats, but every arithmetic result
that a user (or a budget threshold) will compare against is passed through
:func:`round_usd` so that repeated runs are byte-identical and free of binary
float drift. Rounding uses ``Decimal`` with ROUND_HALF_UP.
"""

from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP, InvalidOperation

# Internal precision for accumulating token costs.
PRECISION = 6
# Display precision for dollars-and-cents surfaces.
CENTS = 2


def _to_decimal(value) -> Decimal:
    if isinstance(value, Decimal):
        return value
    if isinstance(value, bool):  # guard: bool is an int subclass
        return Decimal(int(value))
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as exc:  # pragma: no cover
        raise ValueError(f"not a monetary value: {value!r}") from exc


def round_usd(value, places: int = PRECISION) -> float:
    """Round ``value`` to ``places`` decimal places (ROUND_HALF_UP) as a float."""
    if places < 0:
        raise ValueError("places must be >= 0")
    q = Decimal(1).scaleb(-places)
    return float(_to_decimal(value).quantize(q, rounding=ROUND_HALF_UP))


def to_cents(value) -> float:
    """Round to whole cents (2 dp)."""
    return round_usd(value, CENTS)


def add(*values) -> float:
    """Sum monetary values at internal precision (avoids float creep)."""
    total = Decimal(0)
    for v in values:
        total += _to_decimal(v)
    return round_usd(total, PRECISION)


def mul(quantity, unit_price) -> float:
    """Multiply a count by a unit price at internal precision."""
    return round_usd(_to_decimal(quantity) * _to_decimal(unit_price), PRECISION)


def per_million(tokens, price_per_million) -> float:
    """Cost of ``tokens`` at a price expressed per 1,000,000 tokens."""
    if tokens is None or price_per_million is None:
        return 0.0
    result = _to_decimal(tokens) * _to_decimal(price_per_million) / Decimal(1_000_000)
    return round_usd(result, PRECISION)


def fmt_usd(value, places: int = CENTS) -> str:
    """Human string like ``$1.23`` (never scientific notation)."""
    rounded = round_usd(value, places)
    return f"${rounded:,.{places}f}"


def clamp_nonneg(value: float) -> float:
    return value if value > 0 else 0.0
