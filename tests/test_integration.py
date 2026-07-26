"""End-to-end integration across the whole pipeline using bundled fixtures."""

from __future__ import annotations

import json
import os

import pytest

from spendwatch import config as cfg
from spendwatch.report import build_report, remaining_budget
from spendwatch.outputs import json_out, csv_out, prometheus, widget, tui
from spendwatch.mcp import MCPServer, build_context

FIXTURES = os.path.join(os.path.dirname(os.path.dirname(__file__)), "fixtures")
DEMO = os.path.join(FIXTURES, "demo_config.json")


@pytest.fixture
def ctx():
    return cfg.load_and_build(DEMO)


def test_full_pipeline_records(ctx):
    led, pricing, guard, limits, prefer = ctx
    assert len(led) >= 13
    assert led.total_cost(pricing) > 0


def test_all_four_providers_present(ctx):
    led = ctx[0]
    assert set(led.providers()) == {"anthropic", "openai", "openrouter", "local"}


def test_local_is_free(ctx):
    led, pricing, *_ = ctx
    local = led.by_provider_name("local")
    assert local.total_cost(pricing) == 0.0
    assert local.total_tokens() > 0  # but tokens are tracked


def test_report_all_outputs_render(ctx):
    led, pricing, guard, limits, prefer = ctx
    report = build_report(led, pricing, guard=guard, limits=limits, prefer_reported=prefer)
    # every output surface must render without error and be non-trivial
    assert json.loads(json_out.render(report))
    assert prometheus.render(report).count("spendwatch_") > 5
    assert json.loads(widget.render(report))["v"] == 1
    assert "spendwatch" in tui.render_dashboard(report)
    assert csv_out.render_records(led, pricing).count("\n") >= len(led)


def test_outputs_agree_on_total(ctx):
    led, pricing, guard, limits, prefer = ctx
    report = build_report(led, pricing, guard=guard, limits=limits, prefer_reported=prefer)
    total = report["summary"]["cost_usd"]
    w = json.loads(widget.render(report))
    assert w["spent_total_usd"] == total
    assert f"{total!r}" in prometheus.render(report)


def test_mcp_over_fixtures(ctx):
    led, pricing, guard, limits, prefer = ctx
    srv = MCPServer(build_context(led, pricing, guard=guard, limits=limits, prefer_reported=prefer))
    resp = srv.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                       "params": {"name": "remaining_budget", "arguments": {}}})
    payload = resp["result"]["structuredContent"]
    assert payload["spent_lifetime_usd"] == led.total_cost(pricing)


def test_cost_by_provider_sums_to_total(ctx):
    led, pricing, *_ = ctx
    by_p = led.cost_by_provider(pricing)
    assert sum(by_p.values()) == pytest.approx(led.total_cost(pricing))


def test_prefer_reported_toggle_matters(ctx):
    led, pricing, *_ = ctx
    computed = led.total_cost(pricing, prefer_reported=False)
    reported = led.total_cost(pricing, prefer_reported=True)
    # openrouter rows carry total_cost, so the two differ
    assert computed != reported


def test_widget_write_and_read(ctx, tmp_path):
    led, pricing, guard, limits, prefer = ctx
    report = build_report(led, pricing, guard=guard, limits=limits)
    path = os.path.join(str(tmp_path), "bridge.json")
    widget.write(report, path)
    with open(path) as fh:
        data = json.load(fh)
    assert data["records"] == len(led)


def test_remaining_budget_project_scope(ctx):
    led, pricing, guard, limits, prefer = ctx
    alpha = led.by_project_name("proj_alpha")
    rb = remaining_budget(alpha, pricing, guard=guard, limits=limits)
    assert rb["spent_lifetime_usd"] == alpha.total_cost(pricing)


def test_json_report_is_stable(ctx):
    led, pricing, guard, limits, prefer = ctx
    from datetime import datetime, timezone
    as_of = datetime(2026, 7, 25, 12, tzinfo=timezone.utc)
    r1 = json_out.render(build_report(led, pricing, guard=guard, limits=limits, as_of=as_of))
    r2 = json_out.render(build_report(led, pricing, guard=guard, limits=limits, as_of=as_of))
    assert r1 == r2
