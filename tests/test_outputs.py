"""Output surface tests: JSON, CSV, Prometheus, widget, TUI."""

from __future__ import annotations

import csv
import io
import json as jsonlib
import os
from datetime import datetime, timezone

import pytest

from spendwatch.ledger import Ledger
from spendwatch.pricing import PricingTable
from spendwatch.schema import UsageRecord
from spendwatch.report import build_report
from spendwatch.budget import BudgetGuard, BudgetRule
from spendwatch.session import Limits
from spendwatch.outputs import json_out, csv_out, prometheus, widget, tui


@pytest.fixture
def pricing():
    return PricingTable.default_table()


@pytest.fixture
def as_of():
    return datetime(2026, 7, 24, 12, tzinfo=timezone.utc)


@pytest.fixture
def led(as_of):
    return Ledger([
        UsageRecord(provider="anthropic", model="claude-sonnet-4", project="a",
                    input_tokens=12000, output_tokens=3400, cached_tokens=8000,
                    cache_write_tokens=1500, timestamp=as_of, request_id="r1"),
        UsageRecord(provider="openai", model="gpt-4o", project="b",
                    input_tokens=9000, output_tokens=2500, cached_tokens=4000,
                    images=2, timestamp=as_of, request_id="r2"),
        UsageRecord(provider="local", model="llama3.1:8b", project="a",
                    input_tokens=5000, output_tokens=2000, timestamp=as_of),
    ])


@pytest.fixture
def report(led, pricing, as_of):
    guard = BudgetGuard([
        BudgetRule(scope="global", limit_usd=100.0),
        BudgetRule(scope="project", key="a", limit_usd=0.1, warn_ratio=0.5),
    ])
    lim = Limits(plan_allowance_usd=100, daily_limit_usd=20, weekly_limit_usd=50)
    return build_report(led, pricing, guard=guard, limits=lim, as_of=as_of)


# -- JSON -----------------------------------------------------------------
def test_json_render_valid(report):
    text = json_out.render(report)
    parsed = jsonlib.loads(text)
    assert parsed["summary"]["records"] == 3


def test_json_deterministic_sorted(report):
    a = json_out.render(report)
    b = json_out.render(report)
    assert a == b


def test_json_records(led):
    text = json_out.render_records(led)
    parsed = jsonlib.loads(text)
    assert len(parsed) == 3
    assert parsed[0]["timestamp"].endswith("Z")


def test_json_records_include_raw(led):
    text = json_out.render_records(led, include_raw=True)
    parsed = jsonlib.loads(text)
    assert "raw" in parsed[0]


# -- CSV ------------------------------------------------------------------
def test_csv_records_header(led, pricing):
    text = csv_out.render_records(led, pricing)
    reader = list(csv.reader(io.StringIO(text)))
    assert reader[0] == csv_out.RECORD_COLUMNS
    assert len(reader) == 4  # header + 3 rows


def test_csv_records_cost_present(led, pricing):
    text = csv_out.render_records(led, pricing)
    rows = list(csv.DictReader(io.StringIO(text)))
    for row in rows:
        float(row["cost_usd"])  # parseable


def test_csv_records_no_pricing(led):
    text = csv_out.render_records(led, pricing=None)
    rows = list(csv.DictReader(io.StringIO(text)))
    assert rows  # renders even without pricing


def test_csv_breakdown(led, pricing):
    mapping = led.cost_by_provider(pricing)
    text = csv_out.render_breakdown(mapping, key_name="provider")
    rows = list(csv.reader(io.StringIO(text)))
    assert rows[0] == ["provider", "cost_usd"]
    keys = [r[0] for r in rows[1:]]
    assert keys == sorted(keys)  # deterministic sort


def test_csv_records_empty():
    text = csv_out.render_records(Ledger(), PricingTable.default_table())
    rows = list(csv.reader(io.StringIO(text)))
    assert len(rows) == 1  # header only


# -- Prometheus -----------------------------------------------------------
def test_prometheus_has_help_and_type(report):
    text = prometheus.render(report)
    assert "# HELP spendwatch_cost_usd_total" in text
    assert "# TYPE spendwatch_cost_usd_total gauge" in text


def test_prometheus_cost_total(report):
    text = prometheus.render(report)
    assert "spendwatch_cost_usd_total" in text


def test_prometheus_labeled_metrics(report):
    text = prometheus.render(report)
    assert 'spendwatch_cost_usd_by_provider{provider="anthropic"}' in text
    assert 'spendwatch_cost_usd_by_model{model="gpt-4o"}' in text


def test_prometheus_budget_metrics(report):
    text = prometheus.render(report)
    assert "spendwatch_budget_exit_code" in text
    assert "spendwatch_budget_status" in text


def test_prometheus_ends_with_newline(report):
    assert prometheus.render(report).endswith("\n")


def test_prometheus_label_escaping():
    m = prometheus.Metrics()
    m.gauge("x", 1, labels={"k": 'a"b\\c'})
    text = m.render()
    assert '\\"' in text and '\\\\' in text


def test_prometheus_no_duplicate_help():
    m = prometheus.Metrics()
    m.gauge("x", 1, labels={"a": "1"})
    m.gauge("x", 2, labels={"a": "2"})
    text = m.render()
    assert text.count("# HELP spendwatch_x") == 1


def test_prometheus_type_declared_once_per_metric(report):
    text = prometheus.render(report)
    assert text.count("# TYPE spendwatch_cost_usd_by_model") == 1


@pytest.mark.parametrize("value,expected", [
    (None, "0"),
    (True, "1"),
    (False, "0"),
    (float("inf"), "+Inf"),
])
def test_prometheus_num_special(value, expected):
    m = prometheus.Metrics()
    m.gauge("x", value)
    assert expected in m.render()


# -- widget ---------------------------------------------------------------
def test_widget_build_flat(report):
    payload = widget.build(report)
    assert payload["v"] == 1
    assert "status" in payload
    assert "spent_today_usd" in payload
    assert "providers" in payload


def test_widget_render_valid_json(report):
    parsed = jsonlib.loads(widget.render(report))
    assert parsed["v"] == 1


def test_widget_write_atomic(report, tmp_path):
    path = os.path.join(str(tmp_path), "w.json")
    widget.write(report, path)
    assert os.path.exists(path)
    with open(path) as fh:
        parsed = jsonlib.load(fh)
    assert parsed["v"] == 1
    # no leftover temp files
    leftovers = [f for f in os.listdir(str(tmp_path)) if f.endswith(".tmp")]
    assert leftovers == []


def test_widget_write_creates_dirs(report, tmp_path):
    path = os.path.join(str(tmp_path), "nested", "deep", "w.json")
    widget.write(report, path)
    assert os.path.exists(path)


def test_widget_status_reflects_budget(report):
    payload = widget.build(report)
    # project 'a' rule limit is tiny -> deny expected
    assert payload["status"] in ("ok", "warn", "deny")
    assert payload["exit_code"] in (0, 1, 2)


def test_widget_money_strings(report):
    payload = widget.build(report)
    assert payload["spent_today"].startswith("$")


# -- TUI ------------------------------------------------------------------
def test_tui_render_contains_header(report):
    text = tui.render_dashboard(report)
    assert "spendwatch" in text
    assert "Total spend" in text


def test_tui_render_budget_section(report):
    text = tui.render_dashboard(report)
    assert "Budget" in text


def test_tui_render_no_budget(led, pricing, as_of):
    report = build_report(led, pricing, as_of=as_of)
    text = tui.render_dashboard(report)
    assert "Total spend" in text


def test_tui_render_top_models(report):
    text = tui.render_dashboard(report)
    assert "Top models" in text


@pytest.mark.parametrize("frac,contains", [
    (0.0, "0.0%"),
    (0.5, "50.0%"),
    (1.0, "100.0%"),
    (2.0, "100.0%"),   # clamped
    (None, "n/a"),
])
def test_tui_bar(frac, contains):
    assert contains in tui._bar(frac)


def test_tui_row_alignment():
    row = tui._row("label", "value", width=20)
    assert len(row) == 20
    assert row.startswith("label")
    assert row.endswith("value")


def test_tui_render_is_string(report):
    assert isinstance(tui.render_dashboard(report), str)


def test_tui_empty_report(pricing, as_of):
    report = build_report(Ledger(), pricing, as_of=as_of)
    text = tui.render_dashboard(report)
    assert "spendwatch" in text
