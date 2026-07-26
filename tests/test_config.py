"""Config loading / assembly tests."""

from __future__ import annotations

import json
import os

import pytest

from spendwatch import config as cfg
from spendwatch.config import ConfigError


def write_json(tmp_path, name, data):
    path = os.path.join(str(tmp_path), name)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh)
    return path


def test_load_config(tmp_path):
    path = write_json(tmp_path, "c.json", {"sources": []})
    assert cfg.load_config(path) == {"sources": []}


def test_load_config_non_object(tmp_path):
    path = write_json(tmp_path, "c.json", [1, 2, 3])
    with pytest.raises(ConfigError):
        cfg.load_config(path)


def test_build_pricing_default():
    p = cfg.build_pricing({})
    assert "gpt-4o" in p.models


def test_build_pricing_custom(tmp_path):
    ptable = write_json(tmp_path, "p.json", {
        "currency": "USD", "default": {"input": 9.0},
        "models": {"foo": {"input": 1.0}}})
    p = cfg.build_pricing({"pricing_table": "p.json"}, base_dir=str(tmp_path))
    assert "foo" in p.models


def test_build_limits():
    lim = cfg.build_limits({"limits": {"plan_allowance_usd": 100}})
    assert lim.plan_allowance_usd == 100


def test_build_guard():
    guard = cfg.build_guard({"budget": {"rules": [{"scope": "global", "limit_usd": 5}]}})
    assert len(guard.rules) == 1


def test_build_ledger_from_records():
    config = {"sources": [
        {"provider": "openai", "records": [{"model": "gpt-4o", "usage": {"prompt_tokens": 100}}]}]}
    led = cfg.build_ledger(config)
    assert len(led) == 1
    assert led[0].input_tokens == 100


def test_build_ledger_from_payload():
    config = {"sources": [
        {"provider": "anthropic", "payload": {"data": [{"model": "m", "usage": {"input_tokens": 5}}]}}]}
    led = cfg.build_ledger(config)
    assert len(led) == 1


def test_build_ledger_from_fixture(tmp_path):
    fx = write_json(tmp_path, "fx.json", {"data": [{"model": "gpt-4o", "usage": {"prompt_tokens": 7}}]})
    config = {"sources": [{"provider": "openai", "fixture": "fx.json"}]}
    led = cfg.build_ledger(config, base_dir=str(tmp_path))
    assert led[0].input_tokens == 7


def test_build_ledger_missing_provider():
    with pytest.raises(ConfigError):
        cfg.build_ledger({"sources": [{"fixture": "x.json"}]})


def test_build_ledger_missing_source_kind():
    with pytest.raises(ConfigError):
        cfg.build_ledger({"sources": [{"provider": "openai"}]})


def test_build_all(tmp_path):
    fx = write_json(tmp_path, "fx.json", {"data": [{"model": "gpt-4o", "usage": {"prompt_tokens": 1000000}}]})
    config = {
        "sources": [{"provider": "openai", "fixture": "fx.json"}],
        "limits": {"plan_allowance_usd": 100},
        "budget": {"rules": [{"scope": "global", "limit_usd": 10}]},
        "prefer_reported": True,
    }
    led, pricing, guard, limits, prefer = cfg.build_all(config, base_dir=str(tmp_path))
    assert len(led) == 1
    assert prefer is True
    assert limits.plan_allowance_usd == 100
    assert len(guard.rules) == 1


def test_load_and_build_demo():
    path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "fixtures", "demo_config.json")
    led, pricing, guard, limits, prefer = cfg.load_and_build(path)
    assert len(led) >= 13
    assert led.providers() == ["anthropic", "local", "openai", "openrouter"]
    assert len(guard.rules) == 4


def test_absolute_fixture_path(tmp_path):
    fx = write_json(tmp_path, "fx.json", {"data": [{"model": "gpt-4o", "usage": {"prompt_tokens": 1}}]})
    config = {"sources": [{"provider": "openai", "fixture": fx}]}
    led = cfg.build_ledger(config, base_dir="/nonexistent")
    assert len(led) == 1
