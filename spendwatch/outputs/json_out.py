"""JSON output. Deterministic (sorted keys) so diffs and CI snapshots are stable."""

from __future__ import annotations

import json


def render(report: dict, indent: int | None = 2, sort_keys: bool = True) -> str:
    return json.dumps(report, indent=indent, sort_keys=sort_keys, ensure_ascii=False)


def render_records(ledger, include_raw: bool = False, indent: int | None = 2) -> str:
    return json.dumps(
        ledger.to_dicts(include_raw=include_raw),
        indent=indent,
        sort_keys=True,
        ensure_ascii=False,
    )
