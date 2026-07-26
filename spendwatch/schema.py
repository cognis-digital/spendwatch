"""The single normalized usage schema every provider is mapped onto.

Cloud usage/cost APIs and local token logs all differ. spendwatch collapses
them into one :class:`UsageRecord` so a mixed cloud + self-hosted stack lives in
a single view.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import datetime

from .timeutil import parse_timestamp, to_iso, day_key, month_key, week_key, now_utc

# Token dimensions that carry an independent price.
TOKEN_FIELDS = (
    "input_tokens",
    "output_tokens",
    "cached_tokens",
    "cache_write_tokens",
    "reasoning_tokens",
    "embedding_tokens",
)


def _coerce_int(value) -> int:
    """Missing/None/garbage -> 0. Negative -> clamped to 0."""
    if value is None or value == "":
        return 0
    if isinstance(value, bool):
        return int(value)
    try:
        n = int(round(float(value)))
    except (TypeError, ValueError):
        return 0
    return n if n > 0 else 0


@dataclass
class UsageRecord:
    """One normalized unit of LLM usage.

    Token counts default to ``0`` so partial payloads never crash ingest.
    ``cost_usd`` is the *provider-reported* cost when present (used only if a
    caller opts into reported pricing); otherwise cost is computed from tokens.
    """

    provider: str
    model: str
    timestamp: datetime = field(default_factory=now_utc)
    input_tokens: int = 0
    output_tokens: int = 0
    cached_tokens: int = 0          # cache-read (discounted) input tokens
    cache_write_tokens: int = 0     # cache-creation tokens
    reasoning_tokens: int = 0       # hidden reasoning / thinking tokens
    embedding_tokens: int = 0
    images: int = 0                 # image generations / inputs billed per unit
    embeddings: int = 0             # count of embedding requests (informational)
    project: str = "default"
    request_id: str | None = None
    session_id: str | None = None
    cost_usd: float | None = None   # provider-reported cost, optional
    raw: dict = field(default_factory=dict)

    def __post_init__(self):
        self.provider = str(self.provider or "unknown")
        self.model = str(self.model or "unknown")
        self.project = str(self.project or "default")
        if not isinstance(self.timestamp, datetime):
            self.timestamp = parse_timestamp(self.timestamp)
        elif self.timestamp.tzinfo is None:
            self.timestamp = parse_timestamp(self.timestamp)
        for f in TOKEN_FIELDS:
            setattr(self, f, _coerce_int(getattr(self, f)))
        self.images = _coerce_int(self.images)
        self.embeddings = _coerce_int(self.embeddings)
        if self.cost_usd is not None:
            try:
                self.cost_usd = float(self.cost_usd)
            except (TypeError, ValueError):
                self.cost_usd = None

    # -- derived -----------------------------------------------------------
    @property
    def total_tokens(self) -> int:
        """All token dimensions summed (billed + reasoning + embedding)."""
        return sum(getattr(self, f) for f in TOKEN_FIELDS)

    @property
    def billable_tokens(self) -> int:
        """Input + output + cache-write + reasoning (the usual 'used' figure)."""
        return (
            self.input_tokens
            + self.output_tokens
            + self.cache_write_tokens
            + self.reasoning_tokens
        )

    @property
    def day(self) -> str:
        return day_key(self.timestamp)

    @property
    def month(self) -> str:
        return month_key(self.timestamp)

    @property
    def week(self) -> str:
        return week_key(self.timestamp)

    # -- serialization -----------------------------------------------------
    def to_dict(self, include_raw: bool = False) -> dict:
        d = asdict(self)
        d["timestamp"] = to_iso(self.timestamp)
        if not include_raw:
            d.pop("raw", None)
        return d

    @classmethod
    def from_dict(cls, data: dict) -> "UsageRecord":
        data = dict(data)
        known = {f for f in cls.__dataclass_fields__}
        raw = data.pop("raw", {}) or {}
        kwargs = {k: v for k, v in data.items() if k in known}
        extra = {k: v for k, v in data.items() if k not in known}
        if extra:
            raw = {**raw, **extra}
        kwargs["raw"] = raw
        return cls(**kwargs)
