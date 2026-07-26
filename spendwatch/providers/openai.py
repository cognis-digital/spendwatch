"""OpenAI usage adapter.

Handles completions ``usage`` (with ``prompt_tokens_details.cached_tokens`` and
``completion_tokens_details.reasoning_tokens``) and the org usage API row shape.
Embedding rows are detected and routed to the embedding dimension.
"""

from __future__ import annotations

from ..schema import UsageRecord
from .base import Provider, _get


class OpenAIProvider(Provider):
    name = "openai"

    def parse_row(self, row: dict) -> UsageRecord | None:
        usage = _get(row, "usage", default=row) or row

        prompt = _get(usage, "prompt_tokens", "input_tokens", "n_context_tokens_total", default=0)
        completion = _get(usage, "completion_tokens", "output_tokens", "n_generated_tokens_total", default=0)
        cached = _get(
            usage,
            "prompt_tokens_details.cached_tokens",
            "cached_tokens",
            "input_cached_tokens",
            default=0,
        )
        reasoning = _get(
            usage,
            "completion_tokens_details.reasoning_tokens",
            "reasoning_tokens",
            default=0,
        )

        model = _get(row, "model", "snapshot_id", default="unknown")
        ts = _get(row, "created", "timestamp", "start_time", "aggregation_timestamp", "date")
        project = _get(row, "project", "project_id", "organization_id", default="default")

        # Embedding detection: embedding endpoints report only prompt tokens.
        embedding_tokens = 0
        images = _get(row, "images", "num_images", "n_images", default=0)
        endpoint = str(_get(row, "endpoint", "operation", "api", default="")).lower()
        model_l = str(model).lower()
        is_embedding = "embedding" in endpoint or "embedding" in model_l or _get(row, "is_embedding", default=False)
        if is_embedding:
            embedding_tokens = prompt or _get(usage, "total_tokens", default=0)
            prompt = 0
            completion = 0

        return UsageRecord(
            provider=self.name,
            model=model,
            timestamp=ts,
            input_tokens=prompt,
            output_tokens=completion,
            cached_tokens=cached,
            reasoning_tokens=reasoning,
            embedding_tokens=embedding_tokens,
            images=images,
            embeddings=1 if is_embedding else 0,
            project=project,
            request_id=_get(row, "id", "request_id"),
            session_id=_get(row, "session_id", "user"),
            cost_usd=_get(row, "cost", "cost_usd", "amount"),
            raw=row,
        )
