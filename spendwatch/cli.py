"""spendwatch command-line interface.

    spendwatch report   [--config C] [--json|--table]
    spendwatch budget   [--config C] [--strict] [--json]     # exit code != 0 on deny
    spendwatch export   [--config C] --format json|csv|prometheus [--breakdown ...]
    spendwatch widget   [--config C] --out path.json
    spendwatch tui      [--config C] [--once] [--iterations N] [--interval S]
    spendwatch metrics  [--config C] [--host H] [--port P]
    spendwatch mcp      [--config C]
    spendwatch pricing  [--pricing-table T] [--model M] [--provider P]
    spendwatch ingest   --provider P --fixture F [--json|--csv]

Everything is offline-first: with no ``--config`` the commands operate on an
empty ledger (useful for smoke tests and schema inspection).
"""

from __future__ import annotations

import argparse
import json
import sys

from . import __version__
from .budget import BudgetGuard
from .config import load_config, build_all, ConfigError
from .ledger import Ledger
from .pricing import PricingTable
from .providers import get_provider, PROVIDERS
from .report import build_report, remaining_budget
from .session import Limits
from .outputs import json_out, csv_out, prometheus, widget, tui


def _load_context(args):
    """Return (ledger, pricing, guard, limits, prefer_reported)."""
    if getattr(args, "config", None):
        import os

        base_dir = os.path.dirname(os.path.abspath(args.config))
        config = load_config(args.config)
        return build_all(config, base_dir)
    pricing = (
        PricingTable.load(args.pricing_table)
        if getattr(args, "pricing_table", None)
        else PricingTable.default_table()
    )
    return Ledger(), pricing, BudgetGuard(), Limits(), False


# -- command handlers -----------------------------------------------------
def cmd_report(args) -> int:
    ledger, pricing, guard, limits, prefer = _load_context(args)
    report = build_report(ledger, pricing, guard=guard, limits=limits, prefer_reported=prefer)
    if args.table:
        print(tui.render_dashboard(report))
    else:
        print(json_out.render(report))
    return 0


def cmd_budget(args) -> int:
    ledger, pricing, guard, limits, prefer = _load_context(args)
    if args.strict:
        guard.strict_warn = True
    gr = guard.evaluate(ledger, pricing, prefer_reported=prefer)
    if args.json:
        print(json_out.render(gr.to_dict()))
    else:
        print(f"budget: {gr.overall.upper()} (exit {gr.exit_code})")
        for st in gr.statuses:
            print(
                f"  [{st.status.upper():4}] {st.rule.label}: "
                f"${st.spent_usd:.4f} / ${st.limit_usd:.4f}"
            )
    return gr.exit_code


def cmd_export(args) -> int:
    ledger, pricing, guard, limits, prefer = _load_context(args)
    fmt = args.format
    if fmt == "json":
        report = build_report(ledger, pricing, guard=guard, limits=limits, prefer_reported=prefer)
        print(json_out.render(report))
    elif fmt == "records":
        print(json_out.render_records(ledger, include_raw=args.raw))
    elif fmt == "csv":
        if args.breakdown:
            mapping = _breakdown_map(ledger, pricing, args.breakdown, prefer)
            print(csv_out.render_breakdown(mapping, key_name=args.breakdown), end="")
        else:
            print(csv_out.render_records(ledger, pricing, prefer_reported=prefer), end="")
    elif fmt == "prometheus":
        report = build_report(ledger, pricing, guard=guard, limits=limits, prefer_reported=prefer)
        print(prometheus.render(report), end="")
    else:  # pragma: no cover - argparse choices guard this
        print(f"unknown format: {fmt}", file=sys.stderr)
        return 2
    return 0


def _breakdown_map(ledger, pricing, dimension, prefer):
    fn = {
        "provider": ledger.cost_by_provider,
        "model": ledger.cost_by_model,
        "project": ledger.cost_by_project,
        "day": ledger.cost_by_day,
    }.get(dimension)
    if fn is None:
        raise ConfigError(f"unknown breakdown dimension: {dimension}")
    return fn(pricing, prefer_reported=prefer)


def cmd_widget(args) -> int:
    ledger, pricing, guard, limits, prefer = _load_context(args)
    report = build_report(ledger, pricing, guard=guard, limits=limits, prefer_reported=prefer)
    if args.out:
        widget.write(report, args.out, indent=2)
        print(f"wrote widget payload to {args.out}")
    else:
        print(widget.render(report, indent=2))
    return 0


def cmd_tui(args) -> int:
    ledger, pricing, guard, limits, prefer = _load_context(args)

    def _report():
        return build_report(ledger, pricing, guard=guard, limits=limits, prefer_reported=prefer)

    if args.once:
        print(tui.render_dashboard(_report()))
        return 0
    tui.run(_report, interval=args.interval, iterations=args.iterations)
    return 0


def cmd_metrics(args) -> int:  # pragma: no cover - long-running server
    from .metrics_server import serve

    ledger, pricing, guard, limits, prefer = _load_context(args)

    def _report():
        return build_report(ledger, pricing, guard=guard, limits=limits, prefer_reported=prefer)

    print(f"serving metrics on http://{args.host}:{args.port}/metrics")
    serve(_report, host=args.host, port=args.port)
    return 0


def cmd_mcp(args) -> int:  # pragma: no cover - stdio loop
    from .mcp import MCPServer, build_context

    ledger, pricing, guard, limits, prefer = _load_context(args)
    ctx = build_context(ledger, pricing, guard=guard, limits=limits, prefer_reported=prefer)
    MCPServer(ctx).serve()
    return 0


def cmd_pricing(args) -> int:
    pricing = (
        PricingTable.load(args.pricing_table)
        if args.pricing_table
        else PricingTable.default_table()
    )
    if args.model:
        rates = pricing.rates_for(args.model, args.provider)
        source = pricing.resolved_source(args.model, args.provider)
        print(json.dumps({"model": args.model, "provider": args.provider,
                          "resolved_from": source, "rates": rates}, indent=2, sort_keys=True))
    else:
        print(json.dumps({
            "currency": pricing.currency,
            "unit": pricing.unit,
            "models": sorted(pricing.models),
            "providers": sorted(pricing.providers),
        }, indent=2, sort_keys=True))
    return 0


def cmd_ingest(args) -> int:
    provider = get_provider(args.provider)
    records = provider.load_fixture(args.fixture)
    ledger = Ledger(records)
    if args.csv:
        pricing = (
            PricingTable.load(args.pricing_table)
            if args.pricing_table
            else PricingTable.default_table()
        )
        print(csv_out.render_records(ledger, pricing), end="")
    else:
        print(json_out.render_records(ledger, include_raw=args.raw))
    return 0


def cmd_providers(args) -> int:
    print(json.dumps(sorted(PROVIDERS), indent=2))
    return 0


# -- parser ---------------------------------------------------------------
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="spendwatch",
        description="Multi-provider LLM usage, cost, and limit meter with budget guards.",
    )
    parser.add_argument("--version", action="version", version=f"spendwatch {__version__}")
    sub = parser.add_subparsers(dest="command")

    def add_config(p):
        p.add_argument("--config", "-c", help="path to a spendwatch config JSON")
        p.add_argument("--pricing-table", help="path to a pricing table JSON")

    p = sub.add_parser("report", help="print a full report")
    add_config(p)
    g = p.add_mutually_exclusive_group()
    g.add_argument("--json", action="store_true", help="JSON output (default)")
    g.add_argument("--table", action="store_true", help="text dashboard output")
    p.set_defaults(func=cmd_report)

    p = sub.add_parser("budget", help="evaluate budget guards (exit != 0 on deny)")
    add_config(p)
    p.add_argument("--strict", action="store_true", help="warn also yields non-zero exit")
    p.add_argument("--json", action="store_true", help="JSON output")
    p.set_defaults(func=cmd_budget)

    p = sub.add_parser("export", help="export usage/report in a chosen format")
    add_config(p)
    p.add_argument("--format", "-f", default="json",
                   choices=["json", "records", "csv", "prometheus"])
    p.add_argument("--breakdown", choices=["provider", "model", "project", "day"],
                   help="CSV breakdown dimension (csv format only)")
    p.add_argument("--raw", action="store_true", help="include raw payloads (records)")
    p.set_defaults(func=cmd_export)

    p = sub.add_parser("widget", help="emit the status-widget bridge JSON")
    add_config(p)
    p.add_argument("--out", "-o", help="write to this path (else stdout)")
    p.set_defaults(func=cmd_widget)

    p = sub.add_parser("tui", help="live TUI dashboard")
    add_config(p)
    p.add_argument("--once", action="store_true", help="render one frame and exit")
    p.add_argument("--iterations", type=int, default=None, help="stop after N refreshes")
    p.add_argument("--interval", type=float, default=2.0, help="refresh seconds")
    p.set_defaults(func=cmd_tui)

    p = sub.add_parser("metrics", help="serve a Prometheus metrics endpoint")
    add_config(p)
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=9109)
    p.set_defaults(func=cmd_metrics)

    p = sub.add_parser("mcp", help="run the MCP stdio server")
    add_config(p)
    p.set_defaults(func=cmd_mcp)

    p = sub.add_parser("pricing", help="inspect the pricing table")
    p.add_argument("--pricing-table", help="path to a pricing table JSON")
    p.add_argument("--model", help="resolve rates for this model")
    p.add_argument("--provider", help="provider hint for resolution")
    p.set_defaults(func=cmd_pricing)

    p = sub.add_parser("ingest", help="normalize a provider fixture to records")
    p.add_argument("--provider", "-p", required=True, choices=sorted(PROVIDERS))
    p.add_argument("--fixture", "-f", required=True, help="path to a native payload JSON")
    p.add_argument("--pricing-table", help="path to a pricing table JSON")
    p.add_argument("--csv", action="store_true", help="CSV output")
    p.add_argument("--raw", action="store_true", help="include raw payloads")
    p.set_defaults(func=cmd_ingest)

    p = sub.add_parser("providers", help="list known providers")
    p.set_defaults(func=cmd_providers)

    return parser


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "command", None):
        parser.print_help()
        return 0
    try:
        return args.func(args)
    except (ConfigError, FileNotFoundError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
