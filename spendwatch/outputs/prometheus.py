"""Prometheus text exposition format, hand-emitted (no client library).

Emits gauges for spend, tokens, forecasts, and budget status so an existing
scrape target can graph and alert on LLM cost with no extra dependency.
"""

from __future__ import annotations

PREFIX = "spendwatch"


def _sanitize_label(value: str) -> str:
    s = str(value)
    return s.replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ")


def _labels(pairs: dict) -> str:
    if not pairs:
        return ""
    inner = ",".join(f'{k}="{_sanitize_label(v)}"' for k, v in sorted(pairs.items()))
    return "{" + inner + "}"


def _num(value) -> str:
    if value is None:
        return "0"
    if isinstance(value, bool):
        return "1" if value else "0"
    if value == float("inf"):
        return "+Inf"
    if value == float("-inf"):
        return "-Inf"
    return repr(float(value))


class Metrics:
    """Accumulate metrics then render the exposition text once."""

    def __init__(self):
        self._lines: list[str] = []
        self._declared: set[str] = set()

    def gauge(self, name: str, value, labels: dict | None = None, help_text: str | None = None):
        full = f"{PREFIX}_{name}"
        if full not in self._declared:
            self._lines.append(f"# HELP {full} {help_text or name}")
            self._lines.append(f"# TYPE {full} gauge")
            self._declared.add(full)
        self._lines.append(f"{full}{_labels(labels or {})} {_num(value)}")
        return self

    def render(self) -> str:
        return "\n".join(self._lines) + "\n"


def render(report: dict) -> str:
    m = Metrics()
    summary = report.get("summary", {})
    m.gauge("cost_usd_total", summary.get("cost_usd", 0.0), help_text="Total LLM spend (USD)")
    m.gauge("records_total", summary.get("records", 0), help_text="Number of usage records")

    tokens = summary.get("tokens", {})
    for field in ("input_tokens", "output_tokens", "cached_tokens", "cache_write_tokens",
                  "reasoning_tokens", "embedding_tokens", "total_tokens"):
        m.gauge("tokens_total", tokens.get(field, 0), labels={"kind": field},
                help_text="Token counts by kind")

    for provider, cost in sorted(summary.get("cost_by_provider", {}).items()):
        m.gauge("cost_usd_by_provider", cost, labels={"provider": provider},
                help_text="Spend by provider (USD)")
    for model, cost in sorted(summary.get("cost_by_model", {}).items()):
        m.gauge("cost_usd_by_model", cost, labels={"model": model},
                help_text="Spend by model (USD)")
    for project, cost in sorted(summary.get("cost_by_project", {}).items()):
        m.gauge("cost_usd_by_project", cost, labels={"project": project},
                help_text="Spend by project (USD)")

    forecast = report.get("forecast", {})
    for period in ("day", "month"):
        fc = forecast.get(period)
        if fc:
            m.gauge("forecast_projected_usd", fc.get("projected_total_usd", 0.0),
                    labels={"period": period}, help_text="Projected end-of-period spend (USD)")
            m.gauge("burn_per_hour_usd", fc.get("burn_per_hour", 0.0),
                    labels={"period": period}, help_text="Burn rate (USD/hour)")

    session = report.get("session", {})
    if session:
        m.gauge("remaining_balance_usd", session.get("remaining_balance_usd") or 0.0,
                help_text="Remaining plan allowance (USD)")
        m.gauge("extra_usage_usd", session.get("extra_usage_usd") or 0.0,
                help_text="Spend beyond plan allowance (USD)")

    budget = report.get("budget")
    if budget:
        status_code = {"ok": 0, "warn": 1, "deny": 2}
        m.gauge("budget_exit_code", budget.get("exit_code", 0),
                help_text="Aggregate budget exit code (0 ok, 1 warn, 2 deny)")
        m.gauge("budget_overall", status_code.get(budget.get("overall", "ok"), 0),
                help_text="Aggregate budget status (0 ok, 1 warn, 2 deny)")
        for st in budget.get("statuses", []):
            labels = {"label": st["label"], "scope": st["scope"], "key": st["key"]}
            m.gauge("budget_spent_usd", st["spent_usd"], labels=labels,
                    help_text="Spend measured against a budget rule (USD)")
            m.gauge("budget_limit_usd", st["limit_usd"], labels=labels,
                    help_text="Budget rule limit (USD)")
            m.gauge("budget_status", status_code.get(st["status"], 0), labels=labels,
                    help_text="Per-rule budget status (0 ok, 1 warn, 2 deny)")
    return m.render()
