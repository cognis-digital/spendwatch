"""Output surfaces: JSON, CSV, Prometheus, status-widget bridge, and TUI."""

from __future__ import annotations

from . import json_out, csv_out, prometheus, widget, tui

__all__ = ["json_out", "csv_out", "prometheus", "widget", "tui"]
