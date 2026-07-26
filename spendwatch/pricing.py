"""Cost model: turn a :class:`UsageRecord` into dollars.

Pricing is resolved with a deterministic cascade:

1. exact model id match in ``models``
2. longest-prefix model match (``gpt-4o-2024-08-06`` -> ``gpt-4o``)
3. provider default (``providers[record.provider]``)
4. table-wide ``default``

Every token dimension is priced independently so cache reads, cache writes,
and hidden reasoning tokens are billed at their own rates. Images bill per
unit; embeddings bill per-token on the ``embedding`` rate.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass

from . import money
from .schema import UsageRecord

_DEFAULT_TABLE_PATH = os.path.join(os.path.dirname(__file__), "pricing_table.json")

# Rate keys per model entry.
RATE_KEYS = ("input", "output", "cached", "cache_write", "reasoning", "embedding", "image")

# Map token field -> rate key.
_TOKEN_RATE = {
    "input_tokens": "input",
    "output_tokens": "output",
    "cached_tokens": "cached",
    "cache_write_tokens": "cache_write",
    "reasoning_tokens": "reasoning",
    "embedding_tokens": "embedding",
}


@dataclass
class CostBreakdown:
    """Per-dimension cost decomposition for one record (or an aggregate)."""

    input: float = 0.0
    output: float = 0.0
    cached: float = 0.0
    cache_write: float = 0.0
    reasoning: float = 0.0
    embedding: float = 0.0
    image: float = 0.0

    @property
    def total(self) -> float:
        return money.add(
            self.input,
            self.output,
            self.cached,
            self.cache_write,
            self.reasoning,
            self.embedding,
            self.image,
        )

    def to_dict(self) -> dict:
        d = {
            "input": self.input,
            "output": self.output,
            "cached": self.cached,
            "cache_write": self.cache_write,
            "reasoning": self.reasoning,
            "embedding": self.embedding,
            "image": self.image,
        }
        d["total"] = self.total
        return d

    def __add__(self, other: "CostBreakdown") -> "CostBreakdown":
        return CostBreakdown(
            input=money.add(self.input, other.input),
            output=money.add(self.output, other.output),
            cached=money.add(self.cached, other.cached),
            cache_write=money.add(self.cache_write, other.cache_write),
            reasoning=money.add(self.reasoning, other.reasoning),
            embedding=money.add(self.embedding, other.embedding),
            image=money.add(self.image, other.image),
        )


class PricingError(ValueError):
    pass


class PricingTable:
    def __init__(self, data: dict):
        if not isinstance(data, dict):
            raise PricingError("pricing table must be an object")
        self.currency = data.get("currency", "USD")
        self.unit = data.get("unit", "per_million_tokens")
        self.default = self._complete(data.get("default", {}))
        self.providers = {
            k: self._complete(v) for k, v in (data.get("providers") or {}).items()
        }
        self.models = {
            k: self._complete(v) for k, v in (data.get("models") or {}).items()
        }
        # Precompute prefix keys sorted longest-first for deterministic matching.
        self._model_keys_by_len = sorted(self.models, key=len, reverse=True)

    # -- construction ------------------------------------------------------
    @staticmethod
    def _complete(entry: dict) -> dict:
        entry = dict(entry or {})
        out = {}
        for k in RATE_KEYS:
            v = entry.get(k, 0.0)
            try:
                out[k] = float(v)
            except (TypeError, ValueError):
                out[k] = 0.0
        return out

    @classmethod
    def load(cls, path: str | None = None) -> "PricingTable":
        path = path or _DEFAULT_TABLE_PATH
        with open(path, "r", encoding="utf-8") as fh:
            return cls(json.load(fh))

    @classmethod
    def default_table(cls) -> "PricingTable":
        return cls.load(_DEFAULT_TABLE_PATH)

    # -- resolution --------------------------------------------------------
    def rates_for(self, model: str, provider: str | None = None) -> dict:
        """Resolve the rate dict for a model, applying the cascade."""
        model = model or ""
        if model in self.models:
            return self.models[model]
        # longest-prefix match
        for key in self._model_keys_by_len:
            if model.startswith(key):
                return self.models[key]
        if provider and provider in self.providers:
            return self.providers[provider]
        return self.default

    def resolved_source(self, model: str, provider: str | None = None) -> str:
        """Return which tier supplied the rate (for diagnostics)."""
        model = model or ""
        if model in self.models:
            return f"model:{model}"
        for key in self._model_keys_by_len:
            if model.startswith(key):
                return f"model-prefix:{key}"
        if provider and provider in self.providers:
            return f"provider:{provider}"
        return "default"

    # -- costing -----------------------------------------------------------
    def breakdown(self, record: UsageRecord) -> CostBreakdown:
        rates = self.rates_for(record.model, record.provider)
        bd = CostBreakdown()
        for field_name, rate_key in _TOKEN_RATE.items():
            tokens = getattr(record, field_name)
            setattr(bd, rate_key, money.per_million(tokens, rates[rate_key]))
        bd.image = money.mul(record.images, rates["image"])
        return bd

    def cost(self, record: UsageRecord) -> float:
        return self.breakdown(record).total

    def resolved_cost(self, record: UsageRecord, prefer_reported: bool = False) -> float:
        """Cost for a record; optionally trust a provider-reported figure."""
        if prefer_reported and record.cost_usd is not None:
            return money.round_usd(record.cost_usd)
        return self.cost(record)

    def breakdown_many(self, records) -> CostBreakdown:
        total = CostBreakdown()
        for r in records:
            total = total + self.breakdown(r)
        return total

    def total(self, records, prefer_reported: bool = False) -> float:
        return money.add(*[self.resolved_cost(r, prefer_reported) for r in records]) if records else 0.0
