"""Prometheus HTTP endpoint tests (real server on an ephemeral port)."""

from __future__ import annotations

import json
import threading
import urllib.request
from datetime import datetime, timezone

import pytest

from spendwatch.metrics_server import make_server, make_handler
from spendwatch.ledger import Ledger
from spendwatch.pricing import PricingTable
from spendwatch.report import build_report
from spendwatch.schema import UsageRecord


@pytest.fixture
def report_fn():
    as_of = datetime(2026, 7, 24, 12, tzinfo=timezone.utc)
    led = Ledger([UsageRecord(provider="openai", model="gpt-4o",
                              input_tokens=1_000_000, timestamp=as_of)])
    pricing = PricingTable.default_table()
    return lambda: build_report(led, pricing, as_of=as_of)


@pytest.fixture
def server(report_fn):
    srv = make_server(report_fn, host="127.0.0.1", port=0)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    yield srv
    srv.shutdown()
    srv.server_close()


def _get(server, path):
    host, port = server.server_address
    with urllib.request.urlopen(f"http://{host}:{port}{path}", timeout=5) as resp:
        return resp.status, resp.read().decode("utf-8"), resp.headers


def test_metrics_endpoint(server):
    status, body, headers = _get(server, "/metrics")
    assert status == 200
    assert "spendwatch_cost_usd_total" in body
    assert "text/plain" in headers["Content-Type"]


def test_report_endpoint(server):
    status, body, _ = _get(server, "/report")
    assert status == 200
    parsed = json.loads(body)
    assert parsed["summary"]["records"] == 1


def test_healthz(server):
    status, body, _ = _get(server, "/healthz")
    assert status == 200
    assert body.strip() == "ok"


def test_index(server):
    status, body, _ = _get(server, "/")
    assert status == 200
    assert "metrics" in body


def test_404(server):
    host, port = server.server_address
    with pytest.raises(urllib.error.HTTPError) as exc:
        urllib.request.urlopen(f"http://{host}:{port}/nope", timeout=5)
    assert exc.value.code == 404


def test_make_handler_callable(report_fn):
    handler = make_handler(report_fn)
    assert handler is not None
