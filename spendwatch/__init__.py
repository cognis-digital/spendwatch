"""spendwatch — multi-provider LLM usage, cost, and limit meter with budget guards.

A Cognis Digital tool. Zero third-party runtime dependencies (Python stdlib only).

Watch LLM usage, rate limits, and spend across every provider a stack touches —
cloud and local — normalized to one schema, with budget guards, burn-rate
forecasting, a live TUI, JSON / CSV / Prometheus export, a status-widget bridge,
and an MCP server so an agent can check its remaining budget before it spends.
"""

from __future__ import annotations

__version__ = "0.1.0"
__all__ = [
    "__version__",
    "UsageRecord",
    "Ledger",
    "PricingTable",
    "BudgetRule",
    "BudgetGuard",
    "money",
]

from . import money  # noqa: E402
from .schema import UsageRecord  # noqa: E402
from .ledger import Ledger  # noqa: E402
from .pricing import PricingTable  # noqa: E402
from .budget import BudgetRule, BudgetGuard  # noqa: E402
