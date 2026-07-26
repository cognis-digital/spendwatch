"""OpenRouter usage adapter.

OpenRouter's generation/activity rows use ``tokens_prompt`` / ``tokens_completion``
and frequently carry an authoritative ``total_cost`` (or ``usage``) already
denominated in USD, which callers may prefer via ``prefer_reported``.
"""

from __future__ import annotations

from ..schema import UsageRecord
from .base import Provider, _get


class OpenRouterProvider(Provider):
    name = "openrouter"

    def parse_row(self, row: dict) -> UsageRecord | None:
        input_tokens = _get(
            row,
            "tokens_prompt",
            "native_tokens_prompt",
            "prompt_tokens",
            "usage.prompt_tokens",
            default=0,
        )
        output_tokens = _get(
            row,
            "tokens_completion",
            "native_tokens_completion",
            "completion_tokens",
            "usage.completion_tokens",
            default=0,
        )
        cached = _get(row, "native_tokens_cached", "cached_tokens", default=0)
        reasoning = _get(row, "native_tokens_reasoning", "reasoning_tokens", default=0)

        model = _get(row, "model", "model_permaslug", default="unknown")
        ts = _get(row, "created_at", "timestamp", "created", "generation_time")
        project = _get(row, "app", "app_name", "project", "label", default="default")

        # OpenRouter reports total_cost in USD, or 'usage' as a USD number.
        reported = _get(row, "total_cost", "cost", "cost_usd")
        if reported is None:
            usage_val = row.get("usage")
            if isinstance(usage_val, (int, float)):
                reported = usage_val

        return UsageRecord(
            provider=self.name,
            model=model,
            timestamp=ts,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cached_tokens=cached,
            reasoning_tokens=reasoning,
            images=_get(row, "num_media_prompt", "images", default=0),
            project=project,
            request_id=_get(row, "id", "generation_id"),
            session_id=_get(row, "session_id"),
            cost_usd=reported,
            raw=row,
        )
