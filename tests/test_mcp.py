"""MCP stdio/JSON-RPC server tests."""

from __future__ import annotations

import io
import json
from datetime import datetime, timezone

import pytest

from spendwatch.mcp import MCPServer, build_context, PROTOCOL_VERSION
from spendwatch.mcp.server import (
    METHOD_NOT_FOUND, INVALID_PARAMS, INVALID_REQUEST, PARSE_ERROR,
    REMAINING_BUDGET_TOOL,
)
from spendwatch.ledger import Ledger
from spendwatch.pricing import PricingTable
from spendwatch.budget import BudgetGuard, BudgetRule
from spendwatch.session import Limits
from spendwatch.schema import UsageRecord


@pytest.fixture
def as_of():
    return datetime(2026, 7, 24, 12, tzinfo=timezone.utc)


def rec(cost_usd, when, project="p", provider="openai"):
    tokens = int(round(cost_usd / 2.5 * 1_000_000))
    return UsageRecord(provider=provider, model="gpt-4o", project=project,
                       input_tokens=tokens, timestamp=when)


@pytest.fixture
def server(as_of):
    led = Ledger([rec(10.0, as_of, project="alpha"), rec(5.0, as_of, project="beta")])
    pricing = PricingTable.default_table()
    guard = BudgetGuard([BudgetRule(scope="global", limit_usd=100.0)])
    lim = Limits(plan_allowance_usd=100, daily_limit_usd=50)
    ctx = build_context(led, pricing, guard=guard, limits=lim)
    return MCPServer(ctx, as_of=as_of)


def req(method, id=1, params=None):
    m = {"jsonrpc": "2.0", "id": id, "method": method}
    if params is not None:
        m["params"] = params
    return m


# -- handshake ------------------------------------------------------------
def test_initialize(server):
    resp = server.handle(req("initialize"))
    assert resp["result"]["protocolVersion"] == PROTOCOL_VERSION
    assert resp["result"]["serverInfo"]["name"] == "spendwatch"
    assert "capabilities" in resp["result"]


def test_initialized_notification(server):
    # notification (no id) returns None
    assert server.handle({"jsonrpc": "2.0", "method": "notifications/initialized"}) is None


def test_ping(server):
    resp = server.handle(req("ping"))
    assert resp["result"] == {}


# -- tools/list -----------------------------------------------------------
def test_tools_list(server):
    resp = server.handle(req("tools/list"))
    tools = resp["result"]["tools"]
    assert len(tools) == 1
    assert tools[0]["name"] == "remaining_budget"
    assert "inputSchema" in tools[0]


def test_tool_schema_shape():
    assert REMAINING_BUDGET_TOOL["inputSchema"]["type"] == "object"
    assert "project" in REMAINING_BUDGET_TOOL["inputSchema"]["properties"]


# -- tools/call -----------------------------------------------------------
def test_tools_call_remaining_budget(server):
    resp = server.handle(req("tools/call", params={"name": "remaining_budget", "arguments": {}}))
    result = resp["result"]
    assert "structuredContent" in result
    assert "content" in result
    payload = result["structuredContent"]
    assert payload["spent_lifetime_usd"] == 15.0
    assert result["isError"] is False


def test_tools_call_content_is_json(server):
    resp = server.handle(req("tools/call", params={"name": "remaining_budget", "arguments": {}}))
    text = resp["result"]["content"][0]["text"]
    parsed = json.loads(text)
    assert parsed == resp["result"]["structuredContent"]


def test_tools_call_project_filter(server):
    resp = server.handle(req("tools/call", params={
        "name": "remaining_budget", "arguments": {"project": "alpha"}}))
    payload = resp["result"]["structuredContent"]
    assert payload["project"] == "alpha"
    assert payload["spent_lifetime_usd"] == 10.0


def test_tools_call_provider_filter(server):
    resp = server.handle(req("tools/call", params={
        "name": "remaining_budget", "arguments": {"provider": "openai"}}))
    payload = resp["result"]["structuredContent"]
    assert payload["provider"] == "openai"


def test_tools_call_is_error_on_deny(as_of):
    led = Ledger([rec(50.0, as_of)])
    guard = BudgetGuard([BudgetRule(scope="global", limit_usd=10.0)])
    ctx = build_context(led, PricingTable.default_table(), guard=guard)
    srv = MCPServer(ctx, as_of=as_of)
    resp = srv.handle(req("tools/call", params={"name": "remaining_budget", "arguments": {}}))
    assert resp["result"]["isError"] is True


def test_tools_call_unknown_tool(server):
    resp = server.handle(req("tools/call", params={"name": "nope"}))
    assert resp["error"]["code"] == INVALID_PARAMS


# -- errors ---------------------------------------------------------------
def test_unknown_method(server):
    resp = server.handle(req("does/not/exist"))
    assert resp["error"]["code"] == METHOD_NOT_FOUND


def test_bad_jsonrpc_version(server):
    resp = server.handle({"jsonrpc": "1.0", "id": 1, "method": "ping"})
    assert resp["error"]["code"] == INVALID_REQUEST


def test_non_object_request(server):
    resp = server.handle(["not", "an", "object"])
    assert resp["error"]["code"] == INVALID_REQUEST


def test_unknown_notification_returns_none(server):
    assert server.handle({"jsonrpc": "2.0", "method": "some/notification"}) is None


# -- text transport -------------------------------------------------------
def test_handle_text_roundtrip(server):
    line = json.dumps(req("tools/list"))
    out = server.handle_text(line)
    parsed = json.loads(out)
    assert parsed["result"]["tools"][0]["name"] == "remaining_budget"


def test_handle_text_blank_returns_none(server):
    assert server.handle_text("   ") is None


def test_handle_text_parse_error(server):
    out = server.handle_text("{not valid json")
    parsed = json.loads(out)
    assert parsed["error"]["code"] == PARSE_ERROR


def test_handle_text_notification_returns_none(server):
    line = json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"})
    assert server.handle_text(line) is None


def test_serve_loop_via_streams(server):
    lines = [
        json.dumps(req("initialize", id=1)),
        json.dumps(req("tools/list", id=2)),
        json.dumps(req("tools/call", id=3, params={"name": "remaining_budget", "arguments": {}})),
    ]
    stdin = io.StringIO("\n".join(lines) + "\n")
    stdout = io.StringIO()
    server.serve(stdin=stdin, stdout=stdout)
    responses = [json.loads(l) for l in stdout.getvalue().splitlines() if l.strip()]
    assert len(responses) == 3
    assert responses[0]["id"] == 1
    assert responses[2]["result"]["structuredContent"]["spent_lifetime_usd"] == 15.0


def test_initialize_as_notification(server):
    # initialize sent without id -> notification, no response
    assert server.handle({"jsonrpc": "2.0", "method": "initialize", "params": {}}) is None
