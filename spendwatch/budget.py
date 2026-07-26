"""Budget guards: per-project / per-day / per-model / global caps with warn and
deny thresholds, and CI-friendly exit codes to stop a runaway run.

A :class:`BudgetRule` describes a cap over some slice of a :class:`Ledger`. A
:class:`BudgetGuard` evaluates every rule against a ledger and produces an
overall :class:`GuardReport` whose ``.exit_code`` is safe to hand straight to
``sys.exit`` in CI.

Exit-code contract
------------------
* ``0`` — all rules OK (or WARN, unless ``strict_warn``)
* ``1`` — highest severity is WARN and ``strict_warn`` is on
* ``2`` — at least one rule DENY

These are exposed as :data:`EXIT_OK`, :data:`EXIT_WARN`, :data:`EXIT_DENY`.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from . import money
from .timeutil import now_utc, start_of_day, start_of_month

OK = "ok"
WARN = "warn"
DENY = "deny"

# Ordering for "highest severity wins".
_SEVERITY = {OK: 0, WARN: 1, DENY: 2}

EXIT_OK = 0
EXIT_WARN = 1
EXIT_DENY = 2

VALID_SCOPES = ("global", "project", "model", "day", "provider")
VALID_PERIODS = ("all", "day", "month")


class BudgetError(ValueError):
    pass


@dataclass
class BudgetRule:
    """One spend cap.

    scope
        ``global`` | ``project`` | ``model`` | ``provider`` | ``day``.
    key
        For ``project`` / ``model`` / ``provider`` scopes, the name this rule
        applies to. ``None`` means "each distinct key" is checked
        independently. For ``global`` / ``day`` scopes ``key`` is ignored.
    limit_usd
        The cap. ``warn_ratio`` and ``deny_ratio`` are fractions of it.
    period
        Time window the spend is measured over: ``all`` | ``day`` | ``month``.
        ``day``/``month`` are relative to the evaluation time (``as_of``).
    """

    scope: str = "global"
    key: str | None = None
    limit_usd: float = 0.0
    warn_ratio: float = 0.8
    deny_ratio: float = 1.0
    period: str = "all"
    name: str | None = None

    def __post_init__(self):
        self.scope = str(self.scope).lower()
        if self.scope not in VALID_SCOPES:
            raise BudgetError(f"invalid scope {self.scope!r}; valid: {VALID_SCOPES}")
        self.period = str(self.period).lower()
        if self.period not in VALID_PERIODS:
            raise BudgetError(f"invalid period {self.period!r}; valid: {VALID_PERIODS}")
        self.limit_usd = float(self.limit_usd)
        if self.limit_usd < 0:
            raise BudgetError("limit_usd must be >= 0")
        self.warn_ratio = float(self.warn_ratio)
        self.deny_ratio = float(self.deny_ratio)
        if self.warn_ratio < 0 or self.deny_ratio < 0:
            raise BudgetError("thresholds must be >= 0")
        if self.warn_ratio > self.deny_ratio:
            raise BudgetError("warn_ratio must be <= deny_ratio")

    @property
    def warn_usd(self) -> float:
        return money.round_usd(self.limit_usd * self.warn_ratio)

    @property
    def deny_usd(self) -> float:
        return money.round_usd(self.limit_usd * self.deny_ratio)

    @property
    def label(self) -> str:
        if self.name:
            return self.name
        target = self.key if self.key is not None else "*"
        return f"{self.scope}:{target}:{self.period}"

    # -- window ------------------------------------------------------------
    def window_start(self, as_of):
        if self.period == "day":
            return start_of_day(as_of)
        if self.period == "month":
            return start_of_month(as_of)
        return None

    def slice_ledger(self, ledger, as_of):
        """Records this rule's cap is measured over."""
        recs = ledger
        start = self.window_start(as_of)
        if start is not None:
            recs = recs.since(start)
        if self.scope == "project" and self.key is not None:
            recs = recs.by_project_name(self.key)
        elif self.scope == "model" and self.key is not None:
            recs = recs.by_model_name(self.key)
        elif self.scope == "provider" and self.key is not None:
            recs = recs.by_provider_name(self.key)
        return recs

    @classmethod
    def from_dict(cls, data: dict) -> "BudgetRule":
        allowed = {"scope", "key", "limit_usd", "warn_ratio", "deny_ratio", "period", "name"}
        # accept "limit" alias
        data = dict(data)
        if "limit" in data and "limit_usd" not in data:
            data["limit_usd"] = data.pop("limit")
        kwargs = {k: v for k, v in data.items() if k in allowed}
        return cls(**kwargs)

    def to_dict(self) -> dict:
        return {
            "scope": self.scope,
            "key": self.key,
            "limit_usd": self.limit_usd,
            "warn_ratio": self.warn_ratio,
            "deny_ratio": self.deny_ratio,
            "period": self.period,
            "name": self.name,
        }


@dataclass
class BudgetStatus:
    """Result of evaluating one rule against one concrete key/slice."""

    rule: BudgetRule
    key: str
    spent_usd: float
    limit_usd: float
    warn_usd: float
    deny_usd: float
    status: str
    ratio: float
    remaining_usd: float

    def to_dict(self) -> dict:
        return {
            "label": self.rule.label,
            "scope": self.rule.scope,
            "key": self.key,
            "period": self.rule.period,
            "spent_usd": self.spent_usd,
            "limit_usd": self.limit_usd,
            "warn_usd": self.warn_usd,
            "deny_usd": self.deny_usd,
            "status": self.status,
            "ratio": self.ratio,
            "remaining_usd": self.remaining_usd,
        }


def classify(spent: float, warn_usd: float, deny_usd: float, limit_usd: float) -> str:
    """Threshold logic. ``>=`` a threshold is a breach; deny wins over warn.

    * Zero spend is always OK.
    * A zero (or negative) cap means "no spend permitted": any spend denies.
    * Otherwise: ``spent >= deny_usd`` -> DENY; ``spent >= warn_usd`` -> WARN.
    """
    if spent <= 0:
        return OK
    if limit_usd <= 0:
        return DENY
    if spent >= deny_usd:
        return DENY
    if spent >= warn_usd:
        return WARN
    return OK


def _evaluate_slice(rule: BudgetRule, key: str, spent: float) -> BudgetStatus:
    warn_usd = rule.warn_usd
    deny_usd = rule.deny_usd
    status = classify(spent, warn_usd, deny_usd, rule.limit_usd)
    ratio = (spent / rule.limit_usd) if rule.limit_usd > 0 else (float("inf") if spent > 0 else 0.0)
    remaining = money.round_usd(rule.limit_usd - spent)
    return BudgetStatus(
        rule=rule,
        key=key,
        spent_usd=money.round_usd(spent),
        limit_usd=money.round_usd(rule.limit_usd),
        warn_usd=warn_usd,
        deny_usd=deny_usd,
        status=status,
        ratio=round(ratio, 6) if ratio != float("inf") else ratio,
        remaining_usd=remaining,
    )


def evaluate_rule(rule: BudgetRule, ledger, pricing, as_of=None, prefer_reported=False) -> list[BudgetStatus]:
    """Evaluate one rule; returns one status per concrete key it covers."""
    as_of = as_of or now_utc()
    recs = rule.slice_ledger(ledger, as_of)

    statuses: list[BudgetStatus] = []
    if rule.scope in ("global", "day") or rule.key is not None:
        key = rule.key if rule.key is not None else rule.scope
        spent = recs.total_cost(pricing, prefer_reported=prefer_reported)
        statuses.append(_evaluate_slice(rule, key, spent))
    else:
        # key is None on a per-entity scope: check each distinct key.
        if rule.scope == "project":
            groups = recs.cost_by_project(pricing, prefer_reported=prefer_reported)
        elif rule.scope == "model":
            groups = recs.cost_by_model(pricing, prefer_reported=prefer_reported)
        else:  # provider
            groups = recs.cost_by_provider(pricing, prefer_reported=prefer_reported)
        if not groups:
            statuses.append(_evaluate_slice(rule, "*", 0.0))
        for key in sorted(groups):
            statuses.append(_evaluate_slice(rule, key, groups[key]))
    return statuses


@dataclass
class GuardReport:
    statuses: list[BudgetStatus] = field(default_factory=list)
    strict_warn: bool = False

    @property
    def overall(self) -> str:
        worst = OK
        for s in self.statuses:
            if _SEVERITY[s.status] > _SEVERITY[worst]:
                worst = s.status
        return worst

    @property
    def exit_code(self) -> int:
        overall = self.overall
        if overall == DENY:
            return EXIT_DENY
        if overall == WARN:
            return EXIT_WARN if self.strict_warn else EXIT_OK
        return EXIT_OK

    @property
    def denied(self) -> list[BudgetStatus]:
        return [s for s in self.statuses if s.status == DENY]

    @property
    def warned(self) -> list[BudgetStatus]:
        return [s for s in self.statuses if s.status == WARN]

    @property
    def ok(self) -> bool:
        return self.overall != DENY

    def to_dict(self) -> dict:
        return {
            "overall": self.overall,
            "exit_code": self.exit_code,
            "strict_warn": self.strict_warn,
            "statuses": [s.to_dict() for s in self.statuses],
            "denied": [s.rule.label for s in self.denied],
            "warned": [s.rule.label for s in self.warned],
        }


class BudgetGuard:
    def __init__(self, rules=None, strict_warn: bool = False):
        self.rules: list[BudgetRule] = list(rules or [])
        self.strict_warn = strict_warn

    def add(self, rule: BudgetRule) -> "BudgetGuard":
        if not isinstance(rule, BudgetRule):
            raise BudgetError("add() expects a BudgetRule")
        self.rules.append(rule)
        return self

    def evaluate(self, ledger, pricing, as_of=None, prefer_reported=False) -> GuardReport:
        as_of = as_of or now_utc()
        statuses: list[BudgetStatus] = []
        for rule in self.rules:
            statuses.extend(
                evaluate_rule(rule, ledger, pricing, as_of=as_of, prefer_reported=prefer_reported)
            )
        return GuardReport(statuses=statuses, strict_warn=self.strict_warn)

    @classmethod
    def from_config(cls, data: dict) -> "BudgetGuard":
        data = data or {}
        rules = [BudgetRule.from_dict(r) for r in data.get("rules", [])]
        return cls(rules=rules, strict_warn=bool(data.get("strict_warn", False)))

    def to_dict(self) -> dict:
        return {
            "strict_warn": self.strict_warn,
            "rules": [r.to_dict() for r in self.rules],
        }
