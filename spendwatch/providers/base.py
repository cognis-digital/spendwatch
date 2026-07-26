"""Shared provider machinery."""

from __future__ import annotations

import json
from typing import Any

from ..schema import UsageRecord


class ProviderError(ValueError):
    pass


def _rows(payload: Any) -> list[dict]:
    """Extract the list of usage rows from a variety of envelope shapes.

    Accepts a bare list, ``{"data": [...]}``, ``{"records": [...]}``,
    ``{"results": [...]}``, ``{"usage": [...]}``, or a single row dict.
    """
    if payload is None:
        return []
    if isinstance(payload, list):
        return [r for r in payload if isinstance(r, dict)]
    if isinstance(payload, dict):
        for key in ("data", "records", "results", "usage", "generations", "items"):
            val = payload.get(key)
            if isinstance(val, list):
                return [r for r in val if isinstance(r, dict)]
        # A single usage row.
        return [payload]
    raise ProviderError(f"cannot read usage rows from {type(payload).__name__}")


def _get(row: dict, *keys, default=None):
    """First present key wins (supports dotted paths)."""
    for key in keys:
        if "." in key:
            cur: Any = row
            ok = True
            for part in key.split("."):
                if isinstance(cur, dict) and part in cur:
                    cur = cur[part]
                else:
                    ok = False
                    break
            if ok and cur is not None:
                return cur
        elif key in row and row[key] is not None:
            return row[key]
    return default


class Provider:
    name = "base"

    def parse(self, payload: Any) -> list[UsageRecord]:
        out: list[UsageRecord] = []
        for row in _rows(payload):
            rec = self.parse_row(row)
            if rec is not None:
                out.append(rec)
        return out

    def parse_row(self, row: dict) -> UsageRecord | None:  # pragma: no cover
        raise NotImplementedError

    def load_fixture(self, path: str) -> list[UsageRecord]:
        with open(path, "r", encoding="utf-8") as fh:
            return self.parse(json.load(fh))

    def loads(self, text: str) -> list[UsageRecord]:
        return self.parse(json.loads(text))

    # -- live path (thin, isolated, never touched by tests) ---------------
    def fetch_live(self, url: str, headers: dict | None = None, timeout: float = 30.0):
        """Fetch a native usage payload over HTTP(S) using only stdlib.

        Isolated so the offline pipeline never imports networking implicitly.
        """
        import urllib.request  # local import keeps import graph clean

        req = urllib.request.Request(url, headers=headers or {})
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
            payload = json.loads(resp.read().decode("utf-8"))
        return self.parse(payload)
