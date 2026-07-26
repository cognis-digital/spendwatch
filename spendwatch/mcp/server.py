"""A tiny JSON-RPC 2.0 / stdio MCP server with zero third-party dependencies.

Implements just enough of the Model Context Protocol handshake to be usable by
an agent runtime: ``initialize``, ``tools/list``, and ``tools/call``. Messages
are newline-delimited JSON objects on stdin/stdout (one JSON-RPC message per
line), which keeps the transport fully self-contained and testable.

The single exposed tool, ``remaining_budget``, answers "what is my remaining
budget?" — optionally scoped to a project or provider — from the live ledger.
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass

from ..report import remaining_budget as _remaining_budget
from ..session import Limits

PROTOCOL_VERSION = "2024-11-05"
SERVER_NAME = "spendwatch"
SERVER_VERSION = "0.1.0"

# JSON-RPC error codes.
PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603


REMAINING_BUDGET_TOOL = {
    "name": "remaining_budget",
    "description": (
        "Report remaining LLM budget before starting a large job. Returns "
        "spend so far (today/week/lifetime), remaining daily/weekly/plan "
        "balance, the tightest binding budget rule, an overall status "
        "(ok/warn/deny), and a CI exit code."
    ),
    "inputSchema": {
        "type": "object",
        "properties": {
            "project": {"type": "string", "description": "Restrict to one project."},
            "provider": {"type": "string", "description": "Restrict to one provider."},
        },
        "additionalProperties": False,
    },
}


@dataclass
class Context:
    ledger: object
    pricing: object
    guard: object = None
    limits: Limits = None
    prefer_reported: bool = False


def build_context(ledger, pricing, guard=None, limits=None, prefer_reported=False) -> Context:
    return Context(
        ledger=ledger,
        pricing=pricing,
        guard=guard,
        limits=limits or Limits(),
        prefer_reported=prefer_reported,
    )


def _ok(request_id, result):
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def _err(request_id, code, message, data=None):
    error = {"code": code, "message": message}
    if data is not None:
        error["data"] = data
    return {"jsonrpc": "2.0", "id": request_id, "error": error}


class MCPServer:
    def __init__(self, context: Context, as_of=None):
        self.context = context
        self.as_of = as_of
        self._initialized = False

    # -- tool implementation ----------------------------------------------
    def remaining_budget(self, arguments: dict | None = None) -> dict:
        arguments = arguments or {}
        ledger = self.context.ledger
        project = arguments.get("project")
        provider = arguments.get("provider")
        if project:
            ledger = ledger.by_project_name(project)
        if provider:
            ledger = ledger.by_provider_name(provider)
        result = _remaining_budget(
            ledger,
            self.context.pricing,
            guard=self.context.guard,
            limits=self.context.limits,
            as_of=self.as_of,
            prefer_reported=self.context.prefer_reported,
        )
        if project:
            result["project"] = project
        if provider:
            result["provider"] = provider
        return result

    # -- JSON-RPC dispatch -------------------------------------------------
    def handle(self, message: dict) -> dict | None:
        if not isinstance(message, dict):
            return _err(None, INVALID_REQUEST, "request must be an object")
        if message.get("jsonrpc") != "2.0":
            return _err(message.get("id"), INVALID_REQUEST, "jsonrpc must be '2.0'")

        method = message.get("method")
        request_id = message.get("id")
        params = message.get("params") or {}
        is_notification = "id" not in message

        try:
            if method == "initialize":
                self._initialized = True
                result = {
                    "protocolVersion": PROTOCOL_VERSION,
                    "capabilities": {"tools": {"listChanged": False}},
                    "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
                }
                return None if is_notification else _ok(request_id, result)

            if method in ("notifications/initialized", "initialized"):
                return None  # notification, no response

            if method == "ping":
                return None if is_notification else _ok(request_id, {})

            if method == "tools/list":
                result = {"tools": [REMAINING_BUDGET_TOOL]}
                return None if is_notification else _ok(request_id, result)

            if method == "tools/call":
                name = params.get("name")
                arguments = params.get("arguments") or {}
                if name != "remaining_budget":
                    return _err(request_id, INVALID_PARAMS, f"unknown tool: {name}")
                payload = self.remaining_budget(arguments)
                result = {
                    "content": [
                        {"type": "text", "text": json.dumps(payload, sort_keys=True)}
                    ],
                    "structuredContent": payload,
                    "isError": payload.get("status") == "deny",
                }
                return None if is_notification else _ok(request_id, result)

            if is_notification:
                return None
            return _err(request_id, METHOD_NOT_FOUND, f"unknown method: {method}")

        except Exception as exc:  # pragma: no cover - defensive
            if is_notification:
                return None
            return _err(request_id, INTERNAL_ERROR, str(exc))

    def handle_text(self, line: str) -> str | None:
        line = line.strip()
        if not line:
            return None
        try:
            message = json.loads(line)
        except json.JSONDecodeError as exc:
            return json.dumps(_err(None, PARSE_ERROR, f"parse error: {exc}"))
        response = self.handle(message)
        if response is None:
            return None
        return json.dumps(response)

    def serve(self, stdin=None, stdout=None):  # pragma: no cover - I/O loop
        stdin = stdin or sys.stdin
        stdout = stdout or sys.stdout
        for line in stdin:
            out = self.handle_text(line)
            if out is not None:
                stdout.write(out + "\n")
                stdout.flush()
