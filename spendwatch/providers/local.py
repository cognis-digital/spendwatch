"""Local provider adapter for self-hosted runtimes (Ollama / LM Studio).

Offline-first: local providers need no API keys. Two native shapes are handled:

* Ollama generate/chat responses: ``prompt_eval_count`` / ``eval_count``.
* LM Studio (OpenAI-compatible): ``usage.prompt_tokens`` / ``completion_tokens``.

Local usage costs $0 by default (see the ``local`` provider rates), but tokens
are still tracked so self-hosted volume shows up in the same view as cloud.
"""

from __future__ import annotations

from ..schema import UsageRecord
from .base import Provider, _get


class LocalProvider(Provider):
    name = "local"

    def parse_row(self, row: dict) -> UsageRecord | None:
        usage = _get(row, "usage", default=None)

        if usage and isinstance(usage, dict):
            # LM Studio / OpenAI-compatible shape.
            input_tokens = _get(usage, "prompt_tokens", "input_tokens", default=0)
            output_tokens = _get(usage, "completion_tokens", "output_tokens", default=0)
        else:
            # Ollama shape.
            input_tokens = _get(row, "prompt_eval_count", "prompt_tokens", "input_tokens", default=0)
            output_tokens = _get(row, "eval_count", "completion_tokens", "output_tokens", default=0)

        model = _get(row, "model", "name", default="unknown")
        ts = _get(row, "created_at", "created", "timestamp", "date")
        project = _get(row, "project", "label", default="local")
        runtime = _get(row, "runtime", "engine", default=None)

        rec = UsageRecord(
            provider=self.name,
            model=model,
            timestamp=ts,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            reasoning_tokens=_get(row, "reasoning_tokens", default=0),
            project=project,
            request_id=_get(row, "id", "request_id"),
            session_id=_get(row, "session_id", "session"),
            raw=row,
        )
        if runtime:
            rec.raw.setdefault("runtime", runtime)
        return rec
