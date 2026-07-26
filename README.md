# spendwatch

**One place to watch LLM usage, rate limits, and spend across every provider your
stack touches** — cloud and local — with budget guards, a live dashboard,
machine-readable exports, and an MCP endpoint an agent can query *before* it
spends.

A Cognis Digital tool. **Zero third-party runtime dependencies** — Python 3.11+
standard library only. The TUI uses `curses` (with a plain-text fallback), HTTP
uses `urllib`/`http.server`, and Prometheus metrics are hand-emitted in the text
exposition format. `pytest` is required only to run the test suite.

---

## Why spendwatch

Most usage meters watch a *single* provider, often scraped from a browser
session. But every serious agent stack spans multiple clouds **plus** local
models, and it needs two things a single-provider widget can't give you:

1. **Budget guards** that actually stop a runaway run (CI-friendly exit codes).
2. **An endpoint an agent can ask** — "what's my remaining budget?" — before it
   kicks off an expensive job.

spendwatch unifies all of it: cloud and self-hosted spend in one normalized
view, guarded, forecast, and exportable to the tools you already run.

## Features

- **Multi-provider ingest, one schema.** Adapters for Anthropic, OpenAI,
  OpenRouter, and local runtimes (Ollama / LM Studio) normalize wildly different
  native payloads into a single `UsageRecord`. Cloud usage/cost APIs and local
  token logs live side by side.
- **Live limits & session tracking.** Current session (rolling window), daily,
  weekly, per-model usage against configured limits, spend beyond an included
  plan allowance ("extra usage"), and remaining balance — all derived from
  ingested records, refreshed on demand.
- **Budget guards.** Per-project / per-day / per-model / per-provider / global
  caps, each with independent **warn** and **deny** thresholds. Evaluates to a
  CI-friendly exit code: `0` ok, `0` (or `1` in `--strict` mode) on warn, `2` on
  deny.
- **Cost model.** Per-token pricing for input, output, cached, cache-write, and
  hidden reasoning tokens, plus per-image and per-embedding rates. Ships an
  editable JSON pricing table with deterministic model→rate resolution
  (exact → longest-prefix → provider default → table default).
- **Burn-rate forecasting.** Projects end-of-day and end-of-month spend from the
  current burn rate and estimates when a cap will be hit.
- **Outputs everywhere.** Live TUI dashboard, deterministic JSON, CSV (records
  or grouped breakdowns), and a Prometheus metrics endpoint for existing
  observability stacks.
- **MCP server.** A tiny self-contained JSON-RPC/stdio server (no external MCP
  SDK) exposing a `remaining_budget` tool an agent can call before a large job.
- **Status-widget bridge.** Emits a tiny, flat JSON file any secondary-display
  or stream-controller widget can poll — covering all providers at a glance.
- **Offline-first.** Local providers need no keys, and every adapter runs in a
  deterministic fixture mode so the whole pipeline is testable without touching a
  paid API. The live HTTP path is a thin, isolated layer.

## Install

```bash
pip install -e .
# or, for development (adds pytest)
pip install -e ".[dev]"
```

Runs from a checkout with no install, too:

```bash
python -m spendwatch --help
```

## Quick start

```bash
# Full report as JSON (uses the bundled demo config + fixtures)
python -m spendwatch report --config fixtures/demo_config.json

# Text dashboard
python -m spendwatch report --config fixtures/demo_config.json --table

# Evaluate budget guards; exit code is non-zero on deny (great for CI)
python -m spendwatch budget --config fixtures/demo_config.json
echo "exit code: $?"

# Export for other tools
python -m spendwatch export -c fixtures/demo_config.json --format csv
python -m spendwatch export -c fixtures/demo_config.json --format prometheus

# Emit the status-widget bridge JSON
python -m spendwatch widget -c fixtures/demo_config.json --out status.json

# Normalize a single provider payload to records
python -m spendwatch ingest --provider anthropic --fixture fixtures/anthropic_usage.json
```

## Configuration

A config is a plain JSON object. Fixture paths resolve relative to the config
file's directory.

```json
{
  "prefer_reported": false,
  "sources": [
    {"provider": "anthropic",  "fixture": "anthropic_usage.json"},
    {"provider": "openai",     "fixture": "openai_usage.json"},
    {"provider": "openrouter", "fixture": "openrouter_usage.json"},
    {"provider": "local",      "fixture": "local_usage.json"}
  ],
  "limits": {
    "plan_allowance_usd": 100.0,
    "weekly_limit_usd": 50.0,
    "daily_limit_usd": 20.0,
    "session_window_minutes": 300,
    "per_model_usd": {"claude-opus-4-20250514": 5.0}
  },
  "budget": {
    "strict_warn": false,
    "rules": [
      {"scope": "global",   "limit_usd": 25.0, "warn_ratio": 0.8, "deny_ratio": 1.0, "period": "all"},
      {"scope": "project",  "key": "proj_alpha", "limit_usd": 10.0, "period": "day"},
      {"scope": "model",    "limit_usd": 8.0, "period": "all"},
      {"scope": "provider", "key": "anthropic", "limit_usd": 15.0}
    ]
  }
}
```

A `source` may provide a `fixture` (path), inline `records` (native rows), or a
full `payload` (native envelope).

### Budget rules

| Field         | Meaning                                                             |
|---------------|--------------------------------------------------------------------|
| `scope`       | `global`, `project`, `model`, `provider`, or `day`                  |
| `key`         | The project/model/provider a rule targets; omit to check **each**  |
| `limit_usd`   | The cap                                                             |
| `warn_ratio`  | Fraction of the cap that triggers a **warn** (default `0.8`)        |
| `deny_ratio`  | Fraction of the cap that triggers a **deny** (default `1.0`)        |
| `period`      | `all`, `day`, or `month` (relative to evaluation time)             |

**Exit-code contract:** `0` = ok (and warn, unless `strict_warn`), `1` = warn in
strict mode, `2` = deny. Drop `spendwatch budget` into a CI step to hard-stop a
job that would blow the budget.

## Pricing table

`spendwatch/pricing_table.json` is fully editable. Rates are USD per 1,000,000
tokens (except `image`, which is USD per image). Resolution is deterministic:

```
exact model id  ->  longest-prefix model id  ->  provider default  ->  table default
```

Inspect resolution:

```bash
python -m spendwatch pricing --model gpt-4o-2024-08-06 --provider openai
```

> The bundled rates are reasonable starting points, not a live price feed —
> spendwatch never phones home. Edit the table to match your contracts.

## MCP: `remaining_budget`

Run the stdio MCP server:

```bash
python -m spendwatch mcp --config fixtures/demo_config.json
```

It speaks newline-delimited JSON-RPC 2.0 and implements `initialize`,
`tools/list`, and `tools/call`. The single tool, `remaining_budget`, returns
spend so far (today/week/lifetime), remaining daily/weekly/plan balance, the
tightest binding budget rule, an overall status, and a CI exit code — optionally
scoped to a `project` or `provider`. The `isError` flag is set when status is
`deny`, so an agent can refuse to start an expensive job.

## Prometheus endpoint

```bash
python -m spendwatch metrics --config fixtures/demo_config.json --port 9109
# then scrape http://127.0.0.1:9109/metrics
```

Also serves `/report` (JSON) and `/healthz`. Metrics rebuild per scrape so they
stay live.

## Programmatic use

```python
from spendwatch.config import load_and_build
from spendwatch.report import build_report, remaining_budget

ledger, pricing, guard, limits, prefer = load_and_build("fixtures/demo_config.json")

report = build_report(ledger, pricing, guard=guard, limits=limits)
print(report["summary"]["cost_usd"])

rb = remaining_budget(ledger, pricing, guard=guard, limits=limits)
print(rb["status"], rb["remaining_usd"])
```

## Project layout

```
spendwatch/
  __init__.py          package exports
  __main__.py          python -m spendwatch
  cli.py               argparse CLI + console entry point
  schema.py            UsageRecord — the one normalized schema
  money.py             deterministic USD math (Decimal, ROUND_HALF_UP)
  timeutil.py          timestamp normalization + period keys
  pricing.py           cost model + resolution cascade
  pricing_table.json   editable pricing table
  ledger.py            record collection + aggregation
  budget.py            budget rules, guards, thresholds, exit codes
  forecast.py          burn-rate forecasting
  session.py           session/limits tracking
  report.py            canonical report + remaining_budget
  config.py            config -> ledger/pricing/guard/limits
  metrics_server.py    Prometheus HTTP endpoint (stdlib http.server)
  providers/           anthropic, openai, openrouter, local adapters
  outputs/             json, csv, prometheus, widget bridge, tui
  mcp/                 self-contained JSON-RPC/stdio MCP server
tests/                 comprehensive pytest suite
fixtures/              sample provider payloads + demo config
```

## Tests

```bash
python -m pytest -q
```

The suite covers ingest normalization across all four providers, the cost model
and pricing tiers, budget-guard thresholds and exit codes, forecast math, every
output format, the MCP endpoint, the CLI, and edge cases (zero usage, missing
fields, huge spend, currency rounding, cache/reasoning tokens).

## License

MIT — see [LICENSE](LICENSE).
