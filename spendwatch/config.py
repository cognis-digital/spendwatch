"""Configuration: assemble a ledger, pricing, budget guard, and limits.

A config is a plain JSON object (no third-party schema library):

    {
      "pricing_table": "pricing.json",          # optional, defaults to built-in
      "prefer_reported": false,                  # trust provider-reported cost?
      "sources": [
        {"provider": "anthropic", "fixture": "fixtures/anthropic_usage.json"},
        {"provider": "openai",    "records": [ ...inline native rows... ]}
      ],
      "limits": { ... },                         # Limits.from_dict
      "budget": {"strict_warn": false, "rules": [ ... ]}
    }

Fixture paths are resolved relative to the config file's directory.
"""

from __future__ import annotations

import json
import os

from .budget import BudgetGuard
from .ledger import Ledger
from .pricing import PricingTable
from .providers import get_provider
from .session import Limits


class ConfigError(ValueError):
    pass


def load_config(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    if not isinstance(data, dict):
        raise ConfigError("config must be a JSON object")
    return data


def build_pricing(config: dict, base_dir: str = ".") -> PricingTable:
    table = config.get("pricing_table")
    if not table:
        return PricingTable.default_table()
    path = table if os.path.isabs(table) else os.path.join(base_dir, table)
    return PricingTable.load(path)


def build_limits(config: dict) -> Limits:
    return Limits.from_dict(config.get("limits", {}))


def build_guard(config: dict) -> BudgetGuard:
    return BudgetGuard.from_config(config.get("budget", {}))


def build_ledger(config: dict, base_dir: str = ".") -> Ledger:
    ledger = Ledger()
    for source in config.get("sources", []):
        provider_name = source.get("provider")
        if not provider_name:
            raise ConfigError("each source needs a 'provider'")
        provider = get_provider(provider_name)

        if "fixture" in source:
            fixture = source["fixture"]
            path = fixture if os.path.isabs(fixture) else os.path.join(base_dir, fixture)
            ledger.extend(provider.load_fixture(path))
        elif "records" in source:
            ledger.extend(provider.parse(source["records"]))
        elif "payload" in source:
            ledger.extend(provider.parse(source["payload"]))
        else:
            raise ConfigError(
                f"source for {provider_name!r} needs 'fixture', 'records', or 'payload'"
            )
    return ledger


def build_all(config: dict, base_dir: str = "."):
    """Return (ledger, pricing, guard, limits, prefer_reported)."""
    ledger = build_ledger(config, base_dir)
    pricing = build_pricing(config, base_dir)
    guard = build_guard(config)
    limits = build_limits(config)
    prefer_reported = bool(config.get("prefer_reported", False))
    return ledger, pricing, guard, limits, prefer_reported


def load_and_build(path: str):
    base_dir = os.path.dirname(os.path.abspath(path))
    config = load_config(path)
    return build_all(config, base_dir)
