"""Shared pytest fixtures for the spendwatch suite."""

from __future__ import annotations

import os
from datetime import datetime, timezone

import pytest

from spendwatch.ledger import Ledger
from spendwatch.pricing import PricingTable
from spendwatch.schema import UsageRecord
from spendwatch import config as cfgmod

FIXTURE_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "fixtures")


def fixture_path(name: str) -> str:
    return os.path.join(FIXTURE_DIR, name)


@pytest.fixture
def fixtures_dir():
    return FIXTURE_DIR


@pytest.fixture
def pricing():
    return PricingTable.default_table()


@pytest.fixture
def as_of():
    return datetime(2026, 7, 24, 15, 0, 0, tzinfo=timezone.utc)


def make_record(**kw):
    base = dict(
        provider="anthropic",
        model="claude-sonnet-4",
        timestamp=datetime(2026, 7, 24, 10, 0, 0, tzinfo=timezone.utc),
        input_tokens=1000,
        output_tokens=500,
    )
    base.update(kw)
    return UsageRecord(**base)


@pytest.fixture
def sample_record():
    return make_record()


@pytest.fixture
def sample_ledger():
    recs = [
        make_record(provider="anthropic", model="claude-sonnet-4", project="a",
                    input_tokens=10000, output_tokens=2000, cached_tokens=5000,
                    cache_write_tokens=1000,
                    timestamp=datetime(2026, 7, 24, 10, 0, tzinfo=timezone.utc)),
        make_record(provider="openai", model="gpt-4o", project="a",
                    input_tokens=8000, output_tokens=3000, cached_tokens=2000,
                    timestamp=datetime(2026, 7, 24, 11, 0, tzinfo=timezone.utc)),
        make_record(provider="openai", model="o3-mini", project="b",
                    input_tokens=3000, output_tokens=1000, reasoning_tokens=4000,
                    timestamp=datetime(2026, 7, 24, 12, 0, tzinfo=timezone.utc)),
        make_record(provider="openrouter", model="meta-llama/llama-3.1-70b-instruct",
                    project="b", input_tokens=20000, output_tokens=6000,
                    timestamp=datetime(2026, 7, 23, 12, 0, tzinfo=timezone.utc)),
        make_record(provider="local", model="llama3.1:8b", project="a",
                    input_tokens=5000, output_tokens=2000,
                    timestamp=datetime(2026, 7, 24, 13, 0, tzinfo=timezone.utc)),
    ]
    return Ledger(recs)


@pytest.fixture
def demo_context():
    return cfgmod.load_and_build(fixture_path("demo_config.json"))


@pytest.fixture
def demo_ledger(demo_context):
    return demo_context[0]
