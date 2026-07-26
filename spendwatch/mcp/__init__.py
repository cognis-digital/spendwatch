"""Minimal, self-contained MCP-style server (no external MCP SDK).

Exposes a ``remaining_budget`` tool so an agent can ask 'what is my remaining
budget?' before a large job and get a structured answer it can act on.
"""

from __future__ import annotations

from .server import MCPServer, build_context, PROTOCOL_VERSION

__all__ = ["MCPServer", "build_context", "PROTOCOL_VERSION"]
