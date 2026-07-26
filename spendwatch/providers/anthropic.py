"""Anthropic usage adapter.

Handles both the message-response ``usage`` shape and the Admin usage/cost API
row shape. Cache-read and cache-creation tokens are mapped to their own
dimensions so they price correctly.
"""

from __future__ import annotations

from ..schema import UsageRecord
from .base import Provider, _get


class AnthropicProvider(Provider):
    name = "anthropic"

    def parse_row(self, row: dict) -> UsageRecord | None:
        usage = _get(row, "usage", default=row) or row

        input_tokens = _get(usage, "input_tokens", "prompt_tokens", default=0)
        output_tokens = _get(usage, "output_tokens", "completion_tokens", default=0)
        cached = _get(
            usage,
            "cache_read_input_tokens",
            "cache_read_tokens",
            "cached_tokens",
            default=0,
        )
        cache_write = _get(
            usage,
            "cache_creation_input_tokens",
            "cache_creation_tokens",
            "cache_write_tokens",
            default=0,
        )
        reasoning = _get(usage, "reasoning_tokens", "thinking_tokens", default=0)

        model = _get(row, "model", "model_id", default="unknown")
        ts = _get(
            row,
            "start_time",
            "timestamp",
            "created_at",
            "created",
            "date",
        )
        project = _get(row, "project", "project_id", "workspace_id", default="default")

        return UsageRecord(
            provider=self.name,
            model=model,
            timestamp=ts,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cached_tokens=cached,
            cache_write_tokens=cache_write,
            reasoning_tokens=reasoning,
            images=_get(row, "images", "image_count", default=0),
            project=project,
            request_id=_get(row, "request_id", "id", "uuid"),
            session_id=_get(row, "session_id", "session"),
            cost_usd=_get(row, "cost", "cost_usd", "amount"),
            raw=row,
        )
