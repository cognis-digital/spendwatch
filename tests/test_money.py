"""Currency-math tests: rounding determinism, precision, formatting."""

from __future__ import annotations

import pytest

from spendwatch import money


@pytest.mark.parametrize(
    "value,places,expected",
    [
        (1.005, 2, 1.01),          # ROUND_HALF_UP, not banker's
        (2.675, 2, 2.68),
        (0.125, 2, 0.13),
        (0.135, 2, 0.14),
        (1.0, 2, 1.0),
        (0.0, 2, 0.0),
        (1.234567, 6, 1.234567),
        (1.2345675, 6, 1.234568),
        (10, 2, 10.0),
        (-1.005, 2, -1.01),        # half-up ties away from zero
        (123456.789, 0, 123457.0),
        (0.000001, 6, 0.000001),
        (0.0000004, 6, 0.0),
        (0.0000005, 6, 0.000001),
    ],
)
def test_round_usd(value, places, expected):
    assert money.round_usd(value, places) == expected


def test_round_usd_default_precision():
    assert money.round_usd(1.23456789) == 1.234568


def test_round_usd_negative_places_raises():
    with pytest.raises(ValueError):
        money.round_usd(1.0, -1)


@pytest.mark.parametrize(
    "value,expected",
    [
        (1.005, 1.01),
        (0.994, 0.99),
        (0.995, 1.0),
        (100.0, 100.0),
        (0, 0.0),
    ],
)
def test_to_cents(value, expected):
    assert money.to_cents(value) == expected


@pytest.mark.parametrize(
    "values,expected",
    [
        ((0.1, 0.2), 0.3),
        ((0.1, 0.1, 0.1), 0.3),
        ((), 0.0),
        ((1.111111, 2.222222), 3.333333),
        ((0.0000005, 0.0000005), 0.000001),
    ],
)
def test_add(values, expected):
    assert money.add(*values) == expected


def test_add_no_float_creep():
    # 0.1 + 0.2 in binary float is 0.30000000000000004
    assert money.add(0.1, 0.2) == 0.3


@pytest.mark.parametrize(
    "qty,price,expected",
    [
        (3, 0.02, 0.06),
        (0, 5.0, 0.0),
        (1000, 0.001, 1.0),
        (2, 0.0048, 0.0096),
        (7, 0.0, 0.0),
    ],
)
def test_mul(qty, price, expected):
    assert money.mul(qty, price) == expected


@pytest.mark.parametrize(
    "tokens,rate,expected",
    [
        (1_000_000, 3.0, 3.0),
        (500_000, 3.0, 1.5),
        (1000, 3.0, 0.003),
        (0, 15.0, 0.0),
        (1_000_000, 0.0, 0.0),
        (12000, 3.0, 0.036),
        (3400, 15.0, 0.051),
        (250, 0.25, 0.000063),
    ],
)
def test_per_million(tokens, rate, expected):
    assert money.per_million(tokens, rate) == expected


def test_per_million_none_inputs():
    assert money.per_million(None, 3.0) == 0.0
    assert money.per_million(1000, None) == 0.0


@pytest.mark.parametrize(
    "value,expected",
    [
        (1.0, "$1.00"),
        (1.5, "$1.50"),
        (1234.5, "$1,234.50"),
        (0, "$0.00"),
        (0.005, "$0.01"),
        (1000000.0, "$1,000,000.00"),
    ],
)
def test_fmt_usd(value, expected):
    assert money.fmt_usd(value) == expected


def test_fmt_usd_never_scientific():
    assert "e" not in money.fmt_usd(0.0000001).lower()


@pytest.mark.parametrize(
    "value,expected",
    [(5.0, 5.0), (-1.0, 0.0), (0.0, 0.0), (-0.0001, 0.0), (0.0001, 0.0001)],
)
def test_clamp_nonneg(value, expected):
    assert money.clamp_nonneg(value) == expected


def test_bool_is_not_treated_as_money_error():
    # booleans coerce through int path deterministically
    assert money.round_usd(True, 2) == 1.0
    assert money.round_usd(False, 2) == 0.0


@pytest.mark.parametrize("bad", ["abc", None, object()])
def test_round_usd_bad_value(bad):
    with pytest.raises(ValueError):
        money.round_usd(bad)
