"""CSV output built with the stdlib ``csv`` module.

Two shapes:
* :func:`render_records` — one row per usage record plus its computed cost.
* :func:`render_breakdown` — one row per group (provider/model/project/day).
"""

from __future__ import annotations

import csv
import io

RECORD_COLUMNS = [
    "timestamp",
    "provider",
    "model",
    "project",
    "input_tokens",
    "output_tokens",
    "cached_tokens",
    "cache_write_tokens",
    "reasoning_tokens",
    "embedding_tokens",
    "images",
    "total_tokens",
    "cost_usd",
    "request_id",
    "session_id",
]


def render_records(ledger, pricing=None, prefer_reported: bool = False) -> str:
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\n")
    writer.writerow(RECORD_COLUMNS)
    for rec in ledger:
        if pricing is not None:
            cost = pricing.resolved_cost(rec, prefer_reported=prefer_reported)
        else:
            cost = rec.cost_usd if rec.cost_usd is not None else ""
        writer.writerow(
            [
                rec.to_dict()["timestamp"],
                rec.provider,
                rec.model,
                rec.project,
                rec.input_tokens,
                rec.output_tokens,
                rec.cached_tokens,
                rec.cache_write_tokens,
                rec.reasoning_tokens,
                rec.embedding_tokens,
                rec.images,
                rec.total_tokens,
                cost,
                rec.request_id or "",
                rec.session_id or "",
            ]
        )
    return buf.getvalue()


def render_breakdown(mapping: dict, key_name: str = "key", value_name: str = "cost_usd") -> str:
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\n")
    writer.writerow([key_name, value_name])
    for key in sorted(mapping):
        writer.writerow([key, mapping[key]])
    return buf.getvalue()
