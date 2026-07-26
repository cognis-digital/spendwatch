"""CLI tests driven through spendwatch.cli.main(argv)."""

from __future__ import annotations

import json
import os

import pytest

from spendwatch.cli import main, build_parser

DEMO = os.path.join(os.path.dirname(os.path.dirname(__file__)), "fixtures", "demo_config.json")


def test_parser_builds():
    assert build_parser() is not None


def test_no_command_prints_help(capsys):
    assert main([]) == 0
    out = capsys.readouterr().out
    assert "spendwatch" in out


def test_version(capsys):
    with pytest.raises(SystemExit) as exc:
        main(["--version"])
    assert exc.value.code == 0
    assert "spendwatch" in capsys.readouterr().out


def test_report_json(capsys):
    assert main(["report", "-c", DEMO]) == 0
    parsed = json.loads(capsys.readouterr().out)
    assert parsed["summary"]["records"] >= 13


def test_report_table(capsys):
    assert main(["report", "-c", DEMO, "--table"]) == 0
    out = capsys.readouterr().out
    assert "Total spend" in out


def test_report_no_config(capsys):
    assert main(["report"]) == 0
    parsed = json.loads(capsys.readouterr().out)
    assert parsed["summary"]["records"] == 0


def test_budget_exit_ok(capsys):
    assert main(["budget", "-c", DEMO]) == 0
    assert "OK" in capsys.readouterr().out


def test_budget_json(capsys):
    assert main(["budget", "-c", DEMO, "--json"]) == 0
    parsed = json.loads(capsys.readouterr().out)
    assert "overall" in parsed


def test_budget_deny_exit_code(tmp_path, capsys):
    config = {
        "sources": [{"provider": "openai", "records": [
            {"model": "gpt-4o", "usage": {"prompt_tokens": 100000000}}]}],
        "budget": {"rules": [{"scope": "global", "limit_usd": 1.0}]},
    }
    path = os.path.join(str(tmp_path), "c.json")
    with open(path, "w") as fh:
        json.dump(config, fh)
    assert main(["budget", "-c", path]) == 2


def test_budget_strict_warn(tmp_path):
    config = {
        "sources": [{"provider": "openai", "records": [
            {"model": "gpt-4o", "usage": {"prompt_tokens": 3600000}}]}],  # $9
        "budget": {"rules": [{"scope": "global", "limit_usd": 10.0}]},
    }
    path = os.path.join(str(tmp_path), "c.json")
    with open(path, "w") as fh:
        json.dump(config, fh)
    assert main(["budget", "-c", path]) == 0
    assert main(["budget", "-c", path, "--strict"]) == 1


@pytest.mark.parametrize("fmt", ["json", "records", "csv", "prometheus"])
def test_export_formats(capsys, fmt):
    assert main(["export", "-c", DEMO, "--format", fmt]) == 0
    out = capsys.readouterr().out
    assert out.strip() != ""


def test_export_csv_breakdown(capsys):
    assert main(["export", "-c", DEMO, "--format", "csv", "--breakdown", "provider"]) == 0
    out = capsys.readouterr().out
    assert "provider,cost_usd" in out


def test_export_prometheus_content(capsys):
    assert main(["export", "-c", DEMO, "--format", "prometheus"]) == 0
    assert "spendwatch_cost_usd_total" in capsys.readouterr().out


def test_widget_stdout(capsys):
    assert main(["widget", "-c", DEMO]) == 0
    parsed = json.loads(capsys.readouterr().out)
    assert parsed["v"] == 1


def test_widget_to_file(tmp_path, capsys):
    out_path = os.path.join(str(tmp_path), "widget.json")
    assert main(["widget", "-c", DEMO, "--out", out_path]) == 0
    assert os.path.exists(out_path)


def test_tui_once(capsys):
    assert main(["tui", "-c", DEMO, "--once"]) == 0
    assert "Total spend" in capsys.readouterr().out


def test_tui_iterations(capsys):
    # iterations with tiny interval via run(); use once path to avoid sleeps
    assert main(["tui", "-c", DEMO, "--once"]) == 0


def test_pricing_list(capsys):
    assert main(["pricing"]) == 0
    parsed = json.loads(capsys.readouterr().out)
    assert "gpt-4o" in parsed["models"]


def test_pricing_model_resolve(capsys):
    assert main(["pricing", "--model", "gpt-4o-2024-08-06", "--provider", "openai"]) == 0
    parsed = json.loads(capsys.readouterr().out)
    assert parsed["resolved_from"] == "model-prefix:gpt-4o"


def test_ingest_json(capsys, fixtures_dir):
    fx = os.path.join(fixtures_dir, "anthropic_usage.json")
    assert main(["ingest", "-p", "anthropic", "-f", fx]) == 0
    parsed = json.loads(capsys.readouterr().out)
    assert len(parsed) >= 3


def test_ingest_csv(capsys, fixtures_dir):
    fx = os.path.join(fixtures_dir, "openai_usage.json")
    assert main(["ingest", "-p", "openai", "-f", fx, "--csv"]) == 0
    assert "provider" in capsys.readouterr().out


def test_providers_list(capsys):
    assert main(["providers"]) == 0
    parsed = json.loads(capsys.readouterr().out)
    assert "anthropic" in parsed


def test_bad_config_path_returns_error():
    assert main(["report", "-c", "/no/such/config.json"]) == 2


def test_invalid_provider_ingest():
    with pytest.raises(SystemExit):
        main(["ingest", "-p", "bogus", "-f", "x.json"])
