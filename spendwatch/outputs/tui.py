"""Live TUI dashboard.

The frame renderer (:func:`render_dashboard`) is a pure function returning a
plain-text block, so it is fully testable and also works as a one-shot text
view. :func:`run` drives a refreshing live loop; it prefers ``curses`` when a
real terminal is available and otherwise falls back to a plain reprinting view.
"""

from __future__ import annotations

import time

from .. import money

BOX_WIDTH = 62


def _rule(char: str = "-", width: int = BOX_WIDTH) -> str:
    return char * width


def _row(label: str, value: str, width: int = BOX_WIDTH) -> str:
    label = str(label)
    value = str(value)
    pad = width - len(label) - len(value)
    if pad < 1:
        pad = 1
    return f"{label}{' ' * pad}{value}"


def _bar(fraction, width: int = 24) -> str:
    if fraction is None:
        return "[" + " " * width + "] n/a"
    try:
        frac = float(fraction)
    except (TypeError, ValueError):
        frac = 0.0
    frac = max(0.0, min(frac, 1.0))
    filled = int(round(frac * width))
    return "[" + "#" * filled + "-" * (width - filled) + f"] {frac * 100:5.1f}%"


def render_dashboard(report: dict) -> str:
    lines: list[str] = []
    summary = report.get("summary", {})
    session = report.get("session", {})
    forecast = report.get("forecast", {})
    budget = report.get("budget")

    lines.append(_rule("="))
    lines.append(_row("spendwatch", report.get("generated_at", "")))
    lines.append(_rule("="))

    # Spend overview
    lines.append(_row("Total spend", money.fmt_usd(summary.get("cost_usd", 0.0))))
    lines.append(_row("Records", str(summary.get("records", 0))))
    providers = summary.get("providers", [])
    lines.append(_row("Providers", ", ".join(providers) if providers else "-"))
    lines.append(_rule())

    # Session / today / week
    today = session.get("today", {})
    week = session.get("week", {})
    sess = session.get("session", {})
    lines.append(_row("Session (%s min)" % sess.get("window_minutes", "?"),
                      money.fmt_usd(sess.get("cost_usd", 0.0))))
    lines.append(_row("Today", money.fmt_usd(today.get("cost_usd", 0.0))))
    if today.get("limit_usd") is not None:
        lines.append("  " + _bar(today.get("pct"), width=20))
    lines.append(_row("This week", money.fmt_usd(week.get("cost_usd", 0.0))))
    if week.get("limit_usd") is not None:
        lines.append("  " + _bar(week.get("pct"), width=20))
    bal = session.get("remaining_balance_usd")
    if bal is not None:
        lines.append(_row("Remaining balance", money.fmt_usd(bal)))
    extra = session.get("extra_usage_usd")
    if extra:
        lines.append(_row("Extra usage", money.fmt_usd(extra)))
    lines.append(_rule())

    # Forecast
    day_fc = forecast.get("day", {})
    lines.append(_row("Burn/hour", money.fmt_usd(day_fc.get("burn_per_hour", 0.0))))
    lines.append(_row("Projected today", money.fmt_usd(day_fc.get("projected_total_usd", 0.0))))
    month_fc = forecast.get("month", {})
    lines.append(_row("Projected month", money.fmt_usd(month_fc.get("projected_total_usd", 0.0))))
    lines.append(_rule())

    # Top models
    by_model = summary.get("cost_by_model", {})
    if by_model:
        lines.append("Top models:")
        top = sorted(by_model.items(), key=lambda kv: kv[1], reverse=True)[:5]
        for model, cost in top:
            lines.append("  " + _row(model[:40], money.fmt_usd(cost)))
        lines.append(_rule())

    # Budget
    if budget:
        lines.append(_row("Budget", budget.get("overall", "ok").upper()))
        for st in budget.get("statuses", []):
            marker = {"ok": "  ", "warn": "! ", "deny": "X "}.get(st["status"], "  ")
            lines.append(
                marker
                + _row(
                    st["label"][:34],
                    f"{money.fmt_usd(st['spent_usd'])}/{money.fmt_usd(st['limit_usd'])}",
                    width=BOX_WIDTH - 2,
                )
            )
        lines.append(_rule("="))

    return "\n".join(lines)


def run(build_report_fn, interval: float = 2.0, iterations: int | None = None):  # pragma: no cover
    """Drive a live refreshing dashboard.

    ``build_report_fn`` is a zero-arg callable returning a fresh report dict.
    ``iterations`` bounds the loop (used in scripted/demo mode); ``None`` runs
    until interrupted.
    """
    try:
        import curses
    except Exception:  # pragma: no cover - non-curses platforms
        curses = None

    if curses is None:
        _run_plain(build_report_fn, interval, iterations)
        return

    def _loop(stdscr):
        curses.curs_set(0)
        stdscr.nodelay(True)
        count = 0
        while iterations is None or count < iterations:
            stdscr.erase()
            frame = render_dashboard(build_report_fn())
            for i, line in enumerate(frame.splitlines()):
                try:
                    stdscr.addstr(i, 0, line)
                except curses.error:
                    pass
            stdscr.refresh()
            ch = stdscr.getch()
            if ch in (ord("q"), ord("Q")):
                break
            time.sleep(interval)
            count += 1

    curses.wrapper(_loop)


def _run_plain(build_report_fn, interval, iterations):  # pragma: no cover
    count = 0
    while iterations is None or count < iterations:
        print("\033[2J\033[H", end="")
        print(render_dashboard(build_report_fn()))
        time.sleep(interval)
        count += 1
