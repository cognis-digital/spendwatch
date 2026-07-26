"""A ledger is an ordered collection of normalized :class:`UsageRecord` with
grouping and aggregation helpers. It is pricing-agnostic — pass a
:class:`PricingTable` to any method that needs dollars.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Callable, Iterable

from . import money
from .schema import UsageRecord, TOKEN_FIELDS


class Ledger:
    def __init__(self, records: Iterable[UsageRecord] | None = None):
        self.records: list[UsageRecord] = list(records or [])

    # -- container semantics ----------------------------------------------
    def __len__(self) -> int:
        return len(self.records)

    def __iter__(self):
        return iter(self.records)

    def __getitem__(self, idx):
        return self.records[idx]

    def add(self, record: UsageRecord) -> "Ledger":
        self.records.append(record)
        return self

    def extend(self, records: Iterable[UsageRecord]) -> "Ledger":
        self.records.extend(records)
        return self

    def sorted(self) -> "Ledger":
        return Ledger(sorted(self.records, key=lambda r: r.timestamp))

    # -- filtering ---------------------------------------------------------
    def filter(self, predicate: Callable[[UsageRecord], bool]) -> "Ledger":
        return Ledger([r for r in self.records if predicate(r)])

    def by_provider_name(self, provider: str) -> "Ledger":
        return self.filter(lambda r: r.provider == provider)

    def by_project_name(self, project: str) -> "Ledger":
        return self.filter(lambda r: r.project == project)

    def by_model_name(self, model: str) -> "Ledger":
        return self.filter(lambda r: r.model == model)

    def since(self, dt) -> "Ledger":
        return self.filter(lambda r: r.timestamp >= dt)

    def until(self, dt) -> "Ledger":
        return self.filter(lambda r: r.timestamp <= dt)

    def between(self, start, end) -> "Ledger":
        return self.filter(lambda r: start <= r.timestamp <= end)

    # -- token aggregation -------------------------------------------------
    def tokens(self) -> dict:
        totals = {f: 0 for f in TOKEN_FIELDS}
        totals["images"] = 0
        totals["embeddings"] = 0
        for r in self.records:
            for f in TOKEN_FIELDS:
                totals[f] += getattr(r, f)
            totals["images"] += r.images
            totals["embeddings"] += r.embeddings
        totals["total_tokens"] = sum(totals[f] for f in TOKEN_FIELDS)
        totals["billable_tokens"] = (
            totals["input_tokens"]
            + totals["output_tokens"]
            + totals["cache_write_tokens"]
            + totals["reasoning_tokens"]
        )
        return totals

    def total_tokens(self) -> int:
        return sum(r.total_tokens for r in self.records)

    # -- cost aggregation --------------------------------------------------
    def total_cost(self, pricing, prefer_reported: bool = False) -> float:
        return pricing.total(self.records, prefer_reported=prefer_reported)

    def _group_cost(self, keyfn, pricing, prefer_reported=False) -> dict:
        buckets: dict = defaultdict(list)
        for r in self.records:
            buckets[keyfn(r)].append(r)
        return {
            k: pricing.total(v, prefer_reported=prefer_reported)
            for k, v in buckets.items()
        }

    def cost_by_provider(self, pricing, prefer_reported=False) -> dict:
        return self._group_cost(lambda r: r.provider, pricing, prefer_reported)

    def cost_by_model(self, pricing, prefer_reported=False) -> dict:
        return self._group_cost(lambda r: r.model, pricing, prefer_reported)

    def cost_by_project(self, pricing, prefer_reported=False) -> dict:
        return self._group_cost(lambda r: r.project, pricing, prefer_reported)

    def cost_by_day(self, pricing, prefer_reported=False) -> dict:
        return self._group_cost(lambda r: r.day, pricing, prefer_reported)

    def cost_by_month(self, pricing, prefer_reported=False) -> dict:
        return self._group_cost(lambda r: r.month, pricing, prefer_reported)

    # -- distinct keys -----------------------------------------------------
    def providers(self) -> list[str]:
        return sorted({r.provider for r in self.records})

    def models(self) -> list[str]:
        return sorted({r.model for r in self.records})

    def projects(self) -> list[str]:
        return sorted({r.project for r in self.records})

    def days(self) -> list[str]:
        return sorted({r.day for r in self.records})

    def span(self):
        """(earliest, latest) timestamps, or (None, None) if empty."""
        if not self.records:
            return (None, None)
        ts = [r.timestamp for r in self.records]
        return (min(ts), max(ts))

    # -- serialization -----------------------------------------------------
    def to_dicts(self, include_raw: bool = False) -> list[dict]:
        return [r.to_dict(include_raw=include_raw) for r in self.records]

    @classmethod
    def from_dicts(cls, rows) -> "Ledger":
        return cls([UsageRecord.from_dict(r) for r in rows])

    def summary(self, pricing, prefer_reported: bool = False) -> dict:
        """A compact roll-up used by outputs, MCP, and the widget bridge."""
        toks = self.tokens()
        breakdown = pricing.breakdown_many(self.records)
        return {
            "records": len(self.records),
            "providers": self.providers(),
            "models": self.models(),
            "projects": self.projects(),
            "tokens": toks,
            "cost_usd": self.total_cost(pricing, prefer_reported),
            "cost_breakdown": breakdown.to_dict(),
            "cost_by_provider": self.cost_by_provider(pricing, prefer_reported),
            "cost_by_model": self.cost_by_model(pricing, prefer_reported),
            "cost_by_project": self.cost_by_project(pricing, prefer_reported),
            "cost_by_day": self.cost_by_day(pricing, prefer_reported),
        }
