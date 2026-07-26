"""Provider adapter tests: native payload -> normalized schema."""

from __future__ import annotations

import json

import pytest

from spendwatch.providers import (
    PROVIDERS,
    get_provider,
    normalize,
    load_fixture,
    ProviderError,
)
from spendwatch.providers.base import _rows, _get


# -- registry -------------------------------------------------------------
@pytest.mark.parametrize("name", ["anthropic", "openai", "openrouter", "local"])
def test_registry_has_provider(name):
    assert name in PROVIDERS
    assert get_provider(name).name == name


def test_get_provider_case_insensitive():
    assert get_provider("Anthropic").name == "anthropic"
    assert get_provider("  OPENAI ").name == "openai"


def test_get_provider_unknown_raises():
    with pytest.raises(ProviderError):
        get_provider("nope")


# -- envelope extraction --------------------------------------------------
@pytest.mark.parametrize(
    "payload,count",
    [
        ([{"a": 1}, {"b": 2}], 2),
        ({"data": [{"a": 1}]}, 1),
        ({"records": [{"a": 1}, {"b": 2}]}, 2),
        ({"results": [{"a": 1}]}, 1),
        ({"usage": [{"a": 1}]}, 1),
        ({"a": 1}, 1),  # single row
        (None, 0),
        ([], 0),
        ([1, 2, "x"], 0),  # non-dict rows dropped
    ],
)
def test_rows(payload, count):
    assert len(_rows(payload)) == count


def test_rows_bad_type_raises():
    with pytest.raises(ProviderError):
        _rows(12345)


def test_get_first_present():
    assert _get({"b": 2}, "a", "b") == 2
    assert _get({"a": 1}, "a", "b") == 1
    assert _get({}, "a", "b", default="d") == "d"


def test_get_dotted_path():
    row = {"usage": {"details": {"cached": 7}}}
    assert _get(row, "usage.details.cached") == 7
    assert _get(row, "usage.missing", default=0) == 0


def test_get_ignores_none_values():
    assert _get({"a": None, "b": 5}, "a", "b") == 5


# -- anthropic ------------------------------------------------------------
def test_anthropic_basic():
    payload = {"data": [{
        "model": "claude-sonnet-4-20250514",
        "start_time": "2026-07-24T10:00:00Z",
        "project_id": "proj_a",
        "request_id": "req_1",
        "usage": {
            "input_tokens": 1000, "output_tokens": 500,
            "cache_read_input_tokens": 200, "cache_creation_input_tokens": 100,
        },
    }]}
    recs = normalize("anthropic", payload)
    assert len(recs) == 1
    r = recs[0]
    assert r.provider == "anthropic"
    assert r.model == "claude-sonnet-4-20250514"
    assert r.input_tokens == 1000
    assert r.output_tokens == 500
    assert r.cached_tokens == 200
    assert r.cache_write_tokens == 100
    assert r.project == "proj_a"
    assert r.request_id == "req_1"


def test_anthropic_reasoning_tokens():
    recs = normalize("anthropic", {"model": "claude-opus-4", "usage": {
        "input_tokens": 10, "output_tokens": 20, "reasoning_tokens": 5}})
    assert recs[0].reasoning_tokens == 5


def test_anthropic_missing_usage_defaults_zero():
    recs = normalize("anthropic", {"model": "claude-sonnet-4"})
    assert recs[0].input_tokens == 0
    assert recs[0].output_tokens == 0


def test_anthropic_flat_usage_shape():
    # usage fields at top level (no nested 'usage')
    recs = normalize("anthropic", {"model": "m", "input_tokens": 7, "output_tokens": 3})
    assert recs[0].input_tokens == 7


def test_anthropic_images():
    recs = normalize("anthropic", {"model": "m", "images": 4})
    assert recs[0].images == 4


# -- openai ---------------------------------------------------------------
def test_openai_basic():
    payload = {"data": [{
        "id": "cmpl_1", "model": "gpt-4o", "created": 1785492000, "project": "p",
        "usage": {
            "prompt_tokens": 800, "completion_tokens": 400,
            "prompt_tokens_details": {"cached_tokens": 100},
            "completion_tokens_details": {"reasoning_tokens": 50},
        },
    }]}
    r = normalize("openai", payload)[0]
    assert r.input_tokens == 800
    assert r.output_tokens == 400
    assert r.cached_tokens == 100
    assert r.reasoning_tokens == 50
    assert r.request_id == "cmpl_1"


def test_openai_embedding_detected_by_endpoint():
    r = normalize("openai", {
        "model": "text-embedding-3-large", "endpoint": "/v1/embeddings",
        "usage": {"prompt_tokens": 5000, "total_tokens": 5000},
    })[0]
    assert r.embedding_tokens == 5000
    assert r.input_tokens == 0
    assert r.embeddings == 1


def test_openai_embedding_detected_by_model_name():
    r = normalize("openai", {
        "model": "text-embedding-3-small",
        "usage": {"prompt_tokens": 1000},
    })[0]
    assert r.embedding_tokens == 1000


def test_openai_images():
    r = normalize("openai", {"model": "gpt-4o", "num_images": 3,
                             "usage": {"prompt_tokens": 10}})[0]
    assert r.images == 3


def test_openai_missing_details():
    r = normalize("openai", {"model": "gpt-4o", "usage": {"prompt_tokens": 5}})[0]
    assert r.cached_tokens == 0
    assert r.reasoning_tokens == 0


# -- openrouter -----------------------------------------------------------
def test_openrouter_basic():
    r = normalize("openrouter", {
        "id": "gen_1", "model": "anthropic/claude-3.5-sonnet",
        "created_at": "2026-07-24T11:00:00Z", "app": "proj_b",
        "tokens_prompt": 600, "tokens_completion": 300, "total_cost": 0.012,
    })[0]
    assert r.input_tokens == 600
    assert r.output_tokens == 300
    assert r.cost_usd == 0.012
    assert r.project == "proj_b"
    assert r.request_id == "gen_1"


def test_openrouter_reasoning_and_cached():
    r = normalize("openrouter", {
        "model": "m", "tokens_prompt": 10, "tokens_completion": 5,
        "native_tokens_reasoning": 3, "native_tokens_cached": 2,
    })[0]
    assert r.reasoning_tokens == 3
    assert r.cached_tokens == 2


def test_openrouter_usage_as_number():
    r = normalize("openrouter", {"model": "m", "tokens_prompt": 1, "usage": 0.05})[0]
    assert r.cost_usd == 0.05


def test_openrouter_native_token_fallback():
    r = normalize("openrouter", {"model": "m", "native_tokens_prompt": 100,
                                 "native_tokens_completion": 50})[0]
    assert r.input_tokens == 100
    assert r.output_tokens == 50


# -- local ----------------------------------------------------------------
def test_local_ollama_shape():
    r = normalize("local", {
        "model": "llama3.1:8b", "created_at": "2026-07-24T12:00:00Z",
        "prompt_eval_count": 500, "eval_count": 250, "runtime": "ollama",
    })[0]
    assert r.provider == "local"
    assert r.input_tokens == 500
    assert r.output_tokens == 250
    assert r.raw.get("runtime") == "ollama"


def test_local_lmstudio_shape():
    r = normalize("local", {
        "model": "local-model", "created": 1785492000,
        "usage": {"prompt_tokens": 300, "completion_tokens": 150},
    })[0]
    assert r.input_tokens == 300
    assert r.output_tokens == 150


def test_local_default_project():
    r = normalize("local", {"model": "m", "prompt_eval_count": 1})[0]
    assert r.project == "local"


# -- fixtures round-trip --------------------------------------------------
@pytest.mark.parametrize(
    "name,fixture,min_count",
    [
        ("anthropic", "anthropic_usage.json", 3),
        ("openai", "openai_usage.json", 4),
        ("openrouter", "openrouter_usage.json", 3),
        ("local", "local_usage.json", 3),
    ],
)
def test_load_fixtures(name, fixture, min_count, fixtures_dir):
    import os
    recs = load_fixture(name, os.path.join(fixtures_dir, fixture))
    assert len(recs) >= min_count
    for r in recs:
        assert r.provider == name
        assert r.total_tokens >= 0


def test_loads_from_text():
    p = get_provider("openai")
    text = json.dumps({"model": "gpt-4o", "usage": {"prompt_tokens": 5}})
    recs = p.loads(text)
    assert recs[0].input_tokens == 5


@pytest.mark.parametrize("name", ["anthropic", "openai", "openrouter", "local"])
def test_empty_payload_yields_no_records(name):
    assert normalize(name, {"data": []}) == []


@pytest.mark.parametrize("name", ["anthropic", "openai", "openrouter", "local"])
def test_provider_never_crashes_on_sparse_row(name):
    # a nearly-empty row must still produce a record with zeros
    recs = normalize(name, {"model": "x"})
    assert len(recs) == 1
    assert recs[0].total_tokens == 0
