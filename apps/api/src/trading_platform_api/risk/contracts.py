from __future__ import annotations

import re
from dataclasses import dataclass, field, fields, replace
from datetime import UTC, datetime
from decimal import (
    ROUND_CEILING,
    ROUND_FLOOR,
    ROUND_HALF_EVEN,
    Context,
    Decimal,
    DecimalException,
    Inexact,
    localcontext,
)
from enum import StrEnum
from itertools import combinations
from typing import TypeVar, cast
from uuid import UUID

from trading_platform_api.contracts.serialization import (
    ContractSerializationError,
    canonical_sha256,
)

CONTRACT_SCHEMA_VERSION = "1"
_SHA256 = re.compile(r"[0-9a-f]{64}")
_CONTRACT_ID = re.compile(r"C-[0-9]{3}")
_T = TypeVar("_T")


class RiskContractError(ValueError):
    """Raised when deterministic risk evidence is structurally invalid."""


class SnapshotState(StrEnum):
    VALID = "VALID"
    STALE = "STALE"
    INCOMPLETE = "INCOMPLETE"
    UNAVAILABLE = "UNAVAILABLE"


class RiskState(StrEnum):
    SAFE = "SAFE"
    LOW_RISK = "LOW_RISK"
    MODERATE_RISK = "MODERATE_RISK"
    HIGH_RISK = "HIGH_RISK"
    EXTREME_RISK = "EXTREME_RISK"
    REJECTED = "REJECTED"
    PAUSED = "PAUSED"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"


class RiskVerdict(StrEnum):
    PASS = "PASS"
    PASS_WITH_WARNING = "PASS_WITH_WARNING"
    REQUIRES_HUMAN_REVIEW = "REQUIRES_HUMAN_REVIEW"
    REJECT = "REJECT"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"


class RiskCheckOutcome(StrEnum):
    PASSED = "PASSED"
    WARNING = "WARNING"
    FAILED = "FAILED"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class RiskLimitSeverity(StrEnum):
    HARD = "HARD"
    SOFT = "SOFT"


class RiskLimitHierarchy(StrEnum):
    SYSTEM = "SYSTEM"
    ACCOUNT = "ACCOUNT"
    PORTFOLIO = "PORTFOLIO"
    STRATEGY = "STRATEGY"
    TRADE = "TRADE"
    USER_REQUEST = "USER_REQUEST"


class RiskPolicyMode(StrEnum):
    RESEARCH = "research"
    BACKTEST = "backtest"
    PAPER = "paper"
    SHADOW = "shadow"
    TESTNET = "testnet"
    LIVE_SUPERVISED = "live-supervised"


class RiskLimitDirection(StrEnum):
    LESS_THAN_OR_EQUAL = "LESS_THAN_OR_EQUAL"
    GREATER_THAN_OR_EQUAL = "GREATER_THAN_OR_EQUAL"


class PositionSide(StrEnum):
    LONG = "LONG"
    SHORT = "SHORT"


class MarginMode(StrEnum):
    ISOLATED = "ISOLATED"
    CROSS = "CROSS"


class SizingMethod(StrEnum):
    RISK_BASED = "RISK_BASED"
    FIXED_NOTIONAL = "FIXED_NOTIONAL"
    PERCENTAGE_OF_EQUITY = "PERCENTAGE_OF_EQUITY"
    VOLATILITY_ADJUSTED = "VOLATILITY_ADJUSTED"
    FRACTIONAL_KELLY = "FRACTIONAL_KELLY"


class LiquidationAvailability(StrEnum):
    AVAILABLE = "AVAILABLE"
    UNAVAILABLE = "UNAVAILABLE"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class RevalidationStatus(StrEnum):
    PASSED = "PASSED"
    FAILED = "FAILED"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"
    STALE = "STALE"
    EXPIRED = "EXPIRED"


class RevalidationTrigger(StrEnum):
    ACCOUNT = "ACCOUNT"
    PORTFOLIO = "PORTFOLIO"
    MARKET = "MARKET"
    SIGNAL_EVIDENCE = "SIGNAL_EVIDENCE"
    STRATEGY_VALIDATION = "STRATEGY_VALIDATION"
    RISK_MODEL = "RISK_MODEL"
    POLICY = "POLICY"
    ENTRY = "ENTRY"
    STOP_LOSS = "STOP_LOSS"
    TAKE_PROFIT = "TAKE_PROFIT"
    AMOUNT_OR_SIZE = "AMOUNT_OR_SIZE"
    LEVERAGE = "LEVERAGE"
    RISK_PERCENTAGE = "RISK_PERCENTAGE"
    MARGIN_MODE = "MARGIN_MODE"
    EXPIRY = "EXPIRY"


def _text(name: str, value: object) -> str:
    if not isinstance(value, str):
        raise RiskContractError(f"{name} must be a string.")
    if not value.strip():
        raise RiskContractError(f"{name} must not be blank.")
    if value != value.strip():
        raise RiskContractError(f"{name} must not contain surrounding whitespace.")
    return value


def _uuid(name: str, value: object) -> UUID:
    if not isinstance(value, UUID):
        raise RiskContractError(f"{name} must be a UUID.")
    return value


def _time(name: str, value: object) -> datetime:
    if not isinstance(value, datetime):
        raise RiskContractError(f"{name} must be a datetime.")
    if value.tzinfo is None or value.utcoffset() is None:
        raise RiskContractError(f"{name} must be timezone-aware.")
    return value.astimezone(UTC)


def _decimal(name: str, value: object) -> Decimal:
    if (
        not isinstance(value, Decimal)
        or isinstance(value, bool)
        or not value.is_finite()
    ):
        raise RiskContractError(f"{name} must be a finite Decimal.")
    return value


def _nonnegative(name: str, value: object) -> Decimal:
    result = _decimal(name, value)
    if result < 0:
        raise RiskContractError(f"{name} must be non-negative.")
    return result


def _positive(name: str, value: object) -> Decimal:
    result = _decimal(name, value)
    if result <= 0:
        raise RiskContractError(f"{name} must be positive.")
    return result


def _positive_int(name: str, value: object) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise RiskContractError(f"{name} must be a positive integer.")
    return value


def _tuple(name: str, value: object, *, empty: bool = True) -> tuple[object, ...]:
    if not isinstance(value, tuple):
        raise RiskContractError(f"{name} must be a tuple.")
    if not empty and not value:
        raise RiskContractError(f"{name} must not be empty.")
    return value


def _unique(name: str, values: tuple[object, ...]) -> None:
    try:
        count = len(set(values))
    except TypeError as exc:
        raise RiskContractError(f"{name} must have hashable identities.") from exc
    if count != len(values):
        raise RiskContractError(f"{name} must not contain duplicates.")


def _typed_tuple(
    name: str, value: object, expected: type[_T], *, empty: bool = True
) -> tuple[_T, ...]:
    values = _tuple(name, value, empty=empty)
    if any(not isinstance(item, expected) for item in values):
        raise RiskContractError(f"{name} contains an invalid type.")
    return cast(tuple[_T, ...], values)


def _text_tuple(name: str, value: object, *, empty: bool = True) -> tuple[str, ...]:
    values = _tuple(name, value, empty=empty)
    result = tuple(_text(f"{name}[{index}]", item) for index, item in enumerate(values))
    _unique(name, result)
    return result


def _uuid_tuple(name: str, value: object, *, empty: bool = True) -> tuple[UUID, ...]:
    values = _tuple(name, value, empty=empty)
    result = tuple(_uuid(f"{name}[{index}]", item) for index, item in enumerate(values))
    _unique(name, result)
    return result


def _digest(name: str, value: object) -> str:
    result = _text(name, value)
    if _SHA256.fullmatch(result) is None:
        raise RiskContractError(f"{name} must be a lowercase SHA-256 digest.")
    return result


def _ordered(
    earlier_name: str, earlier: datetime, later_name: str, later: datetime
) -> None:
    if earlier > later:
        raise RiskContractError(f"{earlier_name} must not be after {later_name}.")


def _temporal(
    as_of: datetime, created: datetime, valid_until: datetime
) -> tuple[datetime, datetime, datetime]:
    normalized = (
        _time("as_of", as_of),
        _time("created_at", created),
        _time("valid_until", valid_until),
    )
    _ordered("as_of", normalized[0], "created_at", normalized[1])
    _ordered("created_at", normalized[1], "valid_until", normalized[2])
    return normalized


@dataclass(frozen=True, slots=True)
class ContractReference:
    contract_id: str
    entity_id: UUID
    schema_version: str
    content_sha256: str | None = None
    valid_until: datetime | None = None

    def __post_init__(self) -> None:
        contract_id = _text("contract_id", self.contract_id)
        if _CONTRACT_ID.fullmatch(contract_id) is None:
            raise RiskContractError("contract_id must match C-###.")
        _uuid("entity_id", self.entity_id)
        _text("schema_version", self.schema_version)
        if self.content_sha256 is not None:
            _digest("content_sha256", self.content_sha256)
        if self.valid_until is not None:
            object.__setattr__(
                self, "valid_until", _time("valid_until", self.valid_until)
            )


@dataclass(frozen=True, slots=True)
class VersionReference:
    component: str
    version: str
    content_sha256: str

    def __post_init__(self) -> None:
        _text("component", self.component)
        _text("version", self.version)
        _digest("content_sha256", self.content_sha256)


@dataclass(frozen=True, slots=True)
class MoneyValue:
    amount: Decimal
    currency: str

    def __post_init__(self) -> None:
        _decimal("amount", self.amount)
        _text("currency", self.currency)


@dataclass(frozen=True, slots=True)
class PriceValue:
    amount: Decimal
    quote_currency: str

    def __post_init__(self) -> None:
        _positive("amount", self.amount)
        _text("quote_currency", self.quote_currency)


@dataclass(frozen=True, slots=True)
class RatioValue:
    value: Decimal
    meaning: str

    def __post_init__(self) -> None:
        value = _decimal("value", self.value)
        if not Decimal("0") <= value <= Decimal("1"):
            raise RiskContractError("value must be between 0 and 1.")
        _text("meaning", self.meaning)


@dataclass(frozen=True, slots=True)
class ExposureValue:
    dimension: str
    key: str
    notional: MoneyValue
    risk_amount: MoneyValue
    equity_ratio: RatioValue

    def __post_init__(self) -> None:
        _text("dimension", self.dimension)
        _text("key", self.key)
        for name in ("notional", "risk_amount"):
            value = getattr(self, name)
            if not isinstance(value, MoneyValue) or value.amount < 0:
                raise RiskContractError(f"{name} must be non-negative MoneyValue.")
        if self.notional.currency != self.risk_amount.currency:
            raise RiskContractError("exposure currencies must match.")
        if not isinstance(self.equity_ratio, RatioValue):
            raise RiskContractError("equity_ratio must be a RatioValue.")


@dataclass(frozen=True, slots=True)
class RiskLimitScope:
    hierarchy: RiskLimitHierarchy
    mode: RiskPolicyMode
    account_id: UUID | None = None
    portfolio_id: UUID | None = None
    strategy_id: str | None = None
    venue: str | None = None
    instrument_id: str | None = None
    trade_id: UUID | None = None
    user_request_id: UUID | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.hierarchy, RiskLimitHierarchy):
            raise RiskContractError("hierarchy must be a RiskLimitHierarchy.")
        if not isinstance(self.mode, RiskPolicyMode):
            raise RiskContractError("mode must be a RiskPolicyMode.")
        for name in ("account_id", "portfolio_id", "trade_id", "user_request_id"):
            value = getattr(self, name)
            if value is not None:
                _uuid(name, value)
        for name in ("strategy_id", "venue", "instrument_id"):
            value = getattr(self, name)
            if value is not None:
                _text(name, value)

        required_by_hierarchy: dict[RiskLimitHierarchy, tuple[str, ...]] = {
            RiskLimitHierarchy.SYSTEM: (),
            RiskLimitHierarchy.ACCOUNT: ("account_id",),
            RiskLimitHierarchy.PORTFOLIO: ("account_id", "portfolio_id"),
            RiskLimitHierarchy.STRATEGY: (
                "account_id",
                "portfolio_id",
                "strategy_id",
            ),
            RiskLimitHierarchy.TRADE: (
                "account_id",
                "portfolio_id",
                "strategy_id",
                "venue",
                "instrument_id",
                "trade_id",
            ),
            RiskLimitHierarchy.USER_REQUEST: (
                "account_id",
                "portfolio_id",
                "strategy_id",
                "venue",
                "instrument_id",
                "trade_id",
                "user_request_id",
            ),
        }
        required = required_by_hierarchy[self.hierarchy]
        if any(getattr(self, name) is None for name in required):
            raise RiskContractError(
                f"{self.hierarchy.value} scope is missing a required identity."
            )
        permitted_by_hierarchy: dict[RiskLimitHierarchy, frozenset[str]] = {
            RiskLimitHierarchy.SYSTEM: frozenset(),
            RiskLimitHierarchy.ACCOUNT: frozenset(
                {"account_id", "venue", "instrument_id"}
            ),
            RiskLimitHierarchy.PORTFOLIO: frozenset(
                {"account_id", "portfolio_id", "venue", "instrument_id"}
            ),
            RiskLimitHierarchy.STRATEGY: frozenset(
                {
                    "account_id",
                    "portfolio_id",
                    "strategy_id",
                    "venue",
                    "instrument_id",
                }
            ),
            RiskLimitHierarchy.TRADE: frozenset(
                {
                    "account_id",
                    "portfolio_id",
                    "strategy_id",
                    "venue",
                    "instrument_id",
                    "trade_id",
                }
            ),
            RiskLimitHierarchy.USER_REQUEST: frozenset(
                {
                    "account_id",
                    "portfolio_id",
                    "strategy_id",
                    "venue",
                    "instrument_id",
                    "trade_id",
                    "user_request_id",
                }
            ),
        }
        permitted = permitted_by_hierarchy[self.hierarchy]
        values = (
            "account_id",
            "portfolio_id",
            "strategy_id",
            "venue",
            "instrument_id",
            "trade_id",
            "user_request_id",
        )
        if any(
            getattr(self, name) is not None and name not in permitted for name in values
        ):
            raise RiskContractError(
                f"{self.hierarchy.value} scope contains an inapplicable identity."
            )


@dataclass(frozen=True, slots=True)
class RiskLimitDefinition:
    limit_id: str
    hierarchy: RiskLimitHierarchy
    metric: str
    direction: RiskLimitDirection
    threshold: Decimal
    unit: str
    severity: RiskLimitSeverity
    scope: RiskLimitScope
    enabled: bool

    def __post_init__(self) -> None:
        _text("limit_id", self.limit_id)
        if not isinstance(self.hierarchy, RiskLimitHierarchy):
            raise RiskContractError("hierarchy must be a RiskLimitHierarchy.")
        _text("metric", self.metric)
        if not isinstance(self.direction, RiskLimitDirection):
            raise RiskContractError("direction must be a RiskLimitDirection.")
        _decimal("threshold", self.threshold)
        _text("unit", self.unit)
        if not isinstance(self.severity, RiskLimitSeverity):
            raise RiskContractError("severity must be a RiskLimitSeverity.")
        if not isinstance(self.scope, RiskLimitScope):
            raise RiskContractError("scope must be a RiskLimitScope.")
        if self.scope.hierarchy is not self.hierarchy:
            raise RiskContractError("limit hierarchy must match its scope hierarchy.")
        if not isinstance(self.enabled, bool) or not self.enabled:
            raise RiskContractError("risk limit definitions must be enabled.")


def _scope_values(scope: RiskLimitScope) -> tuple[object | None, ...]:
    return (
        scope.account_id,
        scope.portfolio_id,
        scope.strategy_id,
        scope.venue,
        scope.instrument_id,
        scope.trade_id,
        scope.user_request_id,
    )


def _scopes_overlap(left: RiskLimitScope, right: RiskLimitScope) -> bool:
    if left.mode is not right.mode:
        return False
    return all(
        left_value is None or right_value is None or left_value == right_value
        for left_value, right_value in zip(
            _scope_values(left), _scope_values(right), strict=True
        )
    )


def _scope_applies_to(parent: RiskLimitScope, child: RiskLimitScope) -> bool:
    if parent.mode is not child.mode:
        return False
    order = tuple(RiskLimitHierarchy)
    if order.index(parent.hierarchy) >= order.index(child.hierarchy):
        return False
    return all(
        parent_value is None or parent_value == child_value
        for parent_value, child_value in zip(
            _scope_values(parent), _scope_values(child), strict=True
        )
    )


@dataclass(frozen=True, slots=True)
class RiskLimitPolicyConfiguration:
    policy_version: VersionReference
    configuration_version: VersionReference
    limits: tuple[RiskLimitDefinition, ...]
    content_sha256: str

    def __post_init__(self) -> None:
        for name in ("policy_version", "configuration_version"):
            if not isinstance(getattr(self, name), VersionReference):
                raise RiskContractError(f"{name} must be a VersionReference.")
        limits = _typed_tuple("limits", self.limits, RiskLimitDefinition, empty=False)
        _unique("limit identities", tuple(item.limit_id for item in limits))

        for index, left in enumerate(limits):
            for right in limits[index + 1 :]:
                if left.metric == right.metric and _scopes_overlap(
                    left.scope, right.scope
                ):
                    if left.hierarchy is right.hierarchy:
                        raise RiskContractError(
                            "same-level risk limit definitions conflict."
                        )
                    hierarchy = tuple(RiskLimitHierarchy)
                    parent, child = (
                        (left, right)
                        if hierarchy.index(left.hierarchy)
                        < hierarchy.index(right.hierarchy)
                        else (right, left)
                    )
                    if not _scope_applies_to(parent.scope, child.scope):
                        raise RiskContractError(
                            "overlapping risk limit definitions have ambiguous or "
                            "incomparable scopes."
                        )
                    if parent.severity is RiskLimitSeverity.HARD:
                        if child.severity is not RiskLimitSeverity.HARD:
                            raise RiskContractError(
                                "lower-level definition cannot soften a HARD limit."
                            )
                        if (
                            parent.unit != child.unit
                            or parent.direction is not child.direction
                        ):
                            raise RiskContractError(
                                "lower-level definition cannot replace a HARD limit "
                                "with a non-comparable definition."
                            )
                        tighter = (
                            child.threshold <= parent.threshold
                            if parent.direction is RiskLimitDirection.LESS_THAN_OR_EQUAL
                            else child.threshold >= parent.threshold
                        )
                        if not tighter:
                            raise RiskContractError(
                                "lower-level definition cannot weaken a HARD limit."
                            )

        preimage = {
            "policy_version": {
                "component": self.policy_version.component,
                "version": self.policy_version.version,
            },
            "configuration_version": {
                "component": self.configuration_version.component,
                "version": self.configuration_version.version,
            },
            "limits": limits,
        }
        expected_digest = canonical_sha256(preimage)
        _digest("content_sha256", self.content_sha256)
        if self.content_sha256 != expected_digest:
            raise RiskContractError("risk policy/configuration digest mismatch.")
        if (
            self.policy_version.content_sha256 != expected_digest
            or self.configuration_version.content_sha256 != expected_digest
        ):
            raise RiskContractError(
                "policy/configuration VersionReference digest mismatch."
            )


@dataclass(frozen=True, slots=True)
class RiskLimitResult:
    limit_id: str
    severity: RiskLimitSeverity
    observed: Decimal
    limit: Decimal
    unit: str
    outcome: RiskCheckOutcome
    reason: str

    def __post_init__(self) -> None:
        _text("limit_id", self.limit_id)
        if not isinstance(self.severity, RiskLimitSeverity):
            raise RiskContractError("severity must be a RiskLimitSeverity.")
        _decimal("observed", self.observed)
        _decimal("limit", self.limit)
        _text("unit", self.unit)
        if not isinstance(self.outcome, RiskCheckOutcome):
            raise RiskContractError("outcome must be a RiskCheckOutcome.")
        _text("reason", self.reason)


@dataclass(frozen=True, slots=True)
class AssessmentReference:
    contract_id: str
    result_id: UUID
    outcome: RiskCheckOutcome
    model_version: VersionReference
    evaluated_at: datetime
    valid_until: datetime

    def __post_init__(self) -> None:
        if _CONTRACT_ID.fullmatch(_text("contract_id", self.contract_id)) is None:
            raise RiskContractError("contract_id must match C-###.")
        _uuid("result_id", self.result_id)
        if not isinstance(self.outcome, RiskCheckOutcome):
            raise RiskContractError("outcome must be a RiskCheckOutcome.")
        if not isinstance(self.model_version, VersionReference):
            raise RiskContractError("model_version must be a VersionReference.")
        evaluated = _time("evaluated_at", self.evaluated_at)
        valid = _time("valid_until", self.valid_until)
        _ordered("evaluated_at", evaluated, "valid_until", valid)
        object.__setattr__(self, "evaluated_at", evaluated)
        object.__setattr__(self, "valid_until", valid)


@dataclass(frozen=True, slots=True)
class RiskContext:
    signal: ContractReference
    validation: ContractReference
    strategy_version: ContractReference
    account_snapshot: ContractReference
    portfolio_snapshot: ContractReference
    asset: str
    instrument_id: str
    side: PositionSide
    as_of: datetime

    def __post_init__(self) -> None:
        expected = {
            "signal": "C-070",
            "validation": "C-028",
            "strategy_version": "C-021",
            "account_snapshot": "C-032",
            "portfolio_snapshot": "C-033",
        }
        for name, contract_id in expected.items():
            ref = getattr(self, name)
            if not isinstance(ref, ContractReference) or ref.contract_id != contract_id:
                raise RiskContractError(f"{name} must reference {contract_id}.")
        _text("asset", self.asset)
        _text("instrument_id", self.instrument_id)
        if not isinstance(self.side, PositionSide):
            raise RiskContractError("side must be a PositionSide.")
        current = _time("as_of", self.as_of)
        for name in expected:
            valid_until = getattr(self, name).valid_until
            if valid_until is not None and valid_until < current:
                raise RiskContractError(f"{name} is expired at risk context as_of.")
        object.__setattr__(self, "as_of", current)


@dataclass(frozen=True, slots=True)
class TakeProfitTarget:
    sequence: int
    price: PriceValue
    allocation: RatioValue
    expected_profit: MoneyValue | None

    def __post_init__(self) -> None:
        _positive_int("sequence", self.sequence)
        if not isinstance(self.price, PriceValue):
            raise RiskContractError("price must be a PriceValue.")
        if not isinstance(self.allocation, RatioValue) or self.allocation.value <= 0:
            raise RiskContractError("allocation must be a positive RatioValue.")
        if self.expected_profit is not None and (
            not isinstance(self.expected_profit, MoneyValue)
            or self.expected_profit.amount < 0
        ):
            raise RiskContractError("expected_profit must be non-negative MoneyValue.")
        if (
            self.expected_profit is not None
            and self.expected_profit.currency != self.price.quote_currency
        ):
            raise RiskContractError("target price/profit currencies must match.")


@dataclass(frozen=True, slots=True)
class StressScenarioResult:
    scenario_id: str
    scenario_type: str
    assumptions: tuple[VersionReference, ...]
    shocked_inputs: tuple[str, ...]
    projected_loss: MoneyValue | None
    projected_drawdown: RatioValue | None
    projected_margin: MoneyValue | None
    liquidation_impact: str
    breached_limit_ids: tuple[str, ...]
    outcome: RiskCheckOutcome

    def __post_init__(self) -> None:
        _text("scenario_id", self.scenario_id)
        _text("scenario_type", self.scenario_type)
        _typed_tuple("assumptions", self.assumptions, VersionReference, empty=False)
        _text_tuple("shocked_inputs", self.shocked_inputs, empty=False)
        for name in ("projected_loss", "projected_margin"):
            value = getattr(self, name)
            if value is not None and (
                not isinstance(value, MoneyValue) or value.amount < 0
            ):
                raise RiskContractError(f"{name} must be non-negative MoneyValue.")
        if self.projected_drawdown is not None and not isinstance(
            self.projected_drawdown, RatioValue
        ):
            raise RiskContractError("projected_drawdown must be a RatioValue.")
        scenario_currencies = {
            item.currency
            for item in (self.projected_loss, self.projected_margin)
            if item is not None
        }
        if len(scenario_currencies) > 1:
            raise RiskContractError("stress scenario currencies must match.")
        _text("liquidation_impact", self.liquidation_impact)
        _text_tuple("breached_limit_ids", self.breached_limit_ids)
        if not isinstance(self.outcome, RiskCheckOutcome):
            raise RiskContractError("outcome must be a RiskCheckOutcome.")
        if self.outcome is RiskCheckOutcome.PASSED and (
            self.projected_loss is None
            or self.projected_drawdown is None
            or self.projected_margin is None
        ):
            raise RiskContractError("passed scenario requires complete outputs.")


def _snapshot_times(
    as_of: datetime, captured_at: datetime, valid_until: datetime
) -> tuple[datetime, datetime, datetime]:
    values = (
        _time("as_of", as_of),
        _time("captured_at", captured_at),
        _time("valid_until", valid_until),
    )
    _ordered("as_of", values[0], "captured_at", values[1])
    _ordered("captured_at", values[1], "valid_until", values[2])
    return values


@dataclass(frozen=True, slots=True)
class AccountSnapshot:
    snapshot_id: UUID
    account_id: UUID
    source_id: str
    state: SnapshotState
    reason_codes: tuple[str, ...]
    currency: str
    equity: MoneyValue | None
    available_balance: MoneyValue | None
    used_margin: MoneyValue | None
    free_margin: MoneyValue | None
    unrealized_pnl: MoneyValue | None
    realized_pnl: MoneyValue | None
    daily_pnl: MoneyValue | None
    weekly_pnl: MoneyValue | None
    current_drawdown: RatioValue | None
    source_version: VersionReference
    as_of: datetime
    captured_at: datetime
    valid_until: datetime
    content_sha256: str
    contract_id: str = field(default="C-032", init=False)
    schema_version: str = field(default=CONTRACT_SCHEMA_VERSION, init=False)

    def __post_init__(self) -> None:
        _uuid("snapshot_id", self.snapshot_id)
        _uuid("account_id", self.account_id)
        _text("source_id", self.source_id)
        if not isinstance(self.state, SnapshotState):
            raise RiskContractError("state must be a SnapshotState.")
        reasons = _text_tuple("reason_codes", self.reason_codes)
        currency = _text("currency", self.currency)
        values = (
            self.equity,
            self.available_balance,
            self.used_margin,
            self.free_margin,
            self.unrealized_pnl,
            self.realized_pnl,
            self.daily_pnl,
            self.weekly_pnl,
        )
        if self.state is SnapshotState.VALID:
            if any(value is None for value in values) or self.current_drawdown is None:
                raise RiskContractError("valid account snapshot requires all values.")
            assert self.equity is not None
            if self.equity.amount <= 0:
                raise RiskContractError("valid account equity must be positive.")
            for value in values[1:4]:
                assert value is not None
                if value.amount < 0:
                    raise RiskContractError(
                        "account balances/margins must be non-negative."
                    )
        elif not reasons:
            raise RiskContractError("non-valid account snapshot requires reason_codes.")
        for value in values:
            if value is not None:
                if not isinstance(value, MoneyValue) or value.currency != currency:
                    raise RiskContractError(
                        "account money values must use snapshot currency."
                    )
        if self.current_drawdown is not None and not isinstance(
            self.current_drawdown, RatioValue
        ):
            raise RiskContractError("current_drawdown must be a RatioValue.")
        if not isinstance(self.source_version, VersionReference):
            raise RiskContractError("source_version must be a VersionReference.")
        as_of, captured, valid = _snapshot_times(
            self.as_of, self.captured_at, self.valid_until
        )
        _digest("content_sha256", self.content_sha256)
        object.__setattr__(self, "as_of", as_of)
        object.__setattr__(self, "captured_at", captured)
        object.__setattr__(self, "valid_until", valid)


class AccountPermissionObservation(StrEnum):
    """Supplied data only; even ALLOWED grants no platform privilege."""

    ALLOWED = "ALLOWED"
    DENIED = "DENIED"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class AccountEvidenceContext:
    """Explicit observed or expected identity; None means unknown, never default."""

    account_id: UUID | None
    source_id: str | None
    source_version: VersionReference | None
    venue: str | None
    mode: RiskPolicyMode | None

    def __post_init__(self) -> None:
        if self.account_id is not None:
            _uuid("account_id", self.account_id)
        for name in ("source_id", "venue"):
            value = getattr(self, name)
            if value is not None:
                _text(name, value)
        if self.source_version is not None:
            if not isinstance(self.source_version, VersionReference):
                raise RiskContractError("source_version must be a VersionReference.")
            VersionReference.__post_init__(self.source_version)
        if self.mode is not None and not isinstance(self.mode, RiskPolicyMode):
            raise RiskContractError("mode must be a RiskPolicyMode.")


@dataclass(frozen=True, slots=True)
class AccountPermissionObservations:
    """Read/trade/withdraw/transfer observations, not authorization or credentials."""

    read: AccountPermissionObservation | None
    trade: AccountPermissionObservation | None
    withdraw: AccountPermissionObservation | None
    transfer: AccountPermissionObservation | None

    def __post_init__(self) -> None:
        for item in fields(self):
            value = getattr(self, item.name)
            if value is not None and not isinstance(
                value, AccountPermissionObservation
            ):
                raise RiskContractError(
                    f"{item.name} must be an AccountPermissionObservation or None."
                )


def _account_evidence_context(name: str, value: object) -> None:
    if value is not None:
        if not isinstance(value, AccountEvidenceContext):
            raise RiskContractError(
                f"{name} must be an AccountEvidenceContext or None."
            )
        AccountEvidenceContext.__post_init__(value)


def _offline_account_inputs(
    snapshot: object, observed_context: object, permissions: object
) -> None:
    if not isinstance(snapshot, AccountSnapshot):
        raise RiskContractError("snapshot must be an AccountSnapshot.")
    # Validate nested money before the legacy VALID constructor dereferences it.
    # The C-032 constructor, layout, and historical digest semantics stay frozen.
    for name in (
        "equity",
        "available_balance",
        "used_margin",
        "free_margin",
        "unrealized_pnl",
        "realized_pnl",
        "daily_pnl",
        "weekly_pnl",
    ):
        value = getattr(snapshot, name)
        if value is not None:
            if not isinstance(value, MoneyValue):
                raise RiskContractError(f"{name} must be a MoneyValue or None.")
            MoneyValue.__post_init__(value)
    if snapshot.current_drawdown is not None:
        if not isinstance(snapshot.current_drawdown, RatioValue):
            raise RiskContractError("current_drawdown must be a RatioValue or None.")
        RatioValue.__post_init__(snapshot.current_drawdown)
    if not isinstance(snapshot.source_version, VersionReference):
        raise RiskContractError("source_version must be a VersionReference.")
    VersionReference.__post_init__(snapshot.source_version)
    if snapshot.contract_id != "C-032" or snapshot.schema_version != "1":
        raise RiskContractError("snapshot must preserve C-032 schema 1 metadata.")
    replace(snapshot)  # Reapply existing C-032 validation without mutating the input.
    _account_evidence_context("observed_context", observed_context)
    if permissions is not None:
        if not isinstance(permissions, AccountPermissionObservations):
            raise RiskContractError(
                "permissions must be AccountPermissionObservations or None."
            )
        AccountPermissionObservations.__post_init__(permissions)


def _offline_account_sha256(value: object) -> str:
    try:
        return canonical_sha256(value)
    except ContractSerializationError as exc:
        raise RiskContractError("offline account evidence is not canonical.") from exc


@dataclass(frozen=True, slots=True)
class OfflineAccountEvidence:
    """Nonpersisted envelope binding the complete supplied C-032 and offline data."""

    snapshot: AccountSnapshot
    observed_context: AccountEvidenceContext | None
    permissions: AccountPermissionObservations | None
    content_sha256: str

    def __post_init__(self) -> None:
        self.verify()

    @classmethod
    def create(
        cls,
        snapshot: AccountSnapshot,
        observed_context: AccountEvidenceContext | None,
        permissions: AccountPermissionObservations | None,
    ) -> OfflineAccountEvidence:
        _offline_account_inputs(snapshot, observed_context, permissions)
        preimage = {
            "snapshot": snapshot,
            "observed_context": observed_context,
            "permissions": permissions,
        }
        return cls(
            snapshot, observed_context, permissions, _offline_account_sha256(preimage)
        )

    def verify(self) -> None:
        """Check structure and content binding, not authenticity or provider truth."""
        _offline_account_inputs(self.snapshot, self.observed_context, self.permissions)
        _digest("content_sha256", self.content_sha256)
        preimage = {
            item.name: getattr(self, item.name)
            for item in fields(self)
            if item.name != "content_sha256"
        }
        if _offline_account_sha256(preimage) != self.content_sha256:
            raise RiskContractError("offline account evidence digest mismatch.")


@dataclass(frozen=True, slots=True)
class OfflineAccountAssessment:
    """Currentness of supplied evidence only; not account truth or a risk decision."""

    evidence: OfflineAccountEvidence
    expected_context: AccountEvidenceContext | None
    evaluated_at: datetime
    current: bool = field(init=False)
    reason_codes: tuple[str, ...] = field(init=False)
    independent_source_reconciliation: str = field(default="UNKNOWN", init=False)

    def __post_init__(self) -> None:
        if not isinstance(self.evidence, OfflineAccountEvidence):
            raise RiskContractError("evidence must be OfflineAccountEvidence.")
        self.evidence.verify()
        _account_evidence_context("expected_context", self.expected_context)
        evaluated_at = _time("evaluated_at", self.evaluated_at)
        snapshot = self.evidence.snapshot
        observed = self.evidence.observed_context
        expected = self.expected_context
        reasons: list[str] = []
        for name in ("account_id", "source_id", "source_version", "venue", "mode"):
            actual = getattr(observed, name) if observed is not None else None
            required = getattr(expected, name) if expected is not None else None
            if actual is None:
                reasons.append(f"OBSERVED_{name.upper()}_UNKNOWN")
            if required is None:
                reasons.append(f"EXPECTED_{name.upper()}_UNKNOWN")
            if actual is not None and required is not None and actual != required:
                reasons.append(f"{name.upper()}_CONTEXT_MISMATCH")
            if name in ("account_id", "source_id", "source_version"):
                if actual is not None and actual != getattr(snapshot, name):
                    reasons.append(f"{name.upper()}_SNAPSHOT_MISMATCH")
        for name in ("read", "trade", "withdraw", "transfer"):
            observation = (
                getattr(self.evidence.permissions, name)
                if self.evidence.permissions is not None
                else None
            )
            if (
                observation is None
                or observation is AccountPermissionObservation.UNKNOWN
            ):
                reasons.append(f"{name.upper()}_PERMISSION_UNKNOWN")
        if snapshot.state is not SnapshotState.VALID:
            reasons.append(f"SNAPSHOT_{snapshot.state.value}")
        if snapshot.as_of > evaluated_at:
            reasons.append("SNAPSHOT_AS_OF_IN_FUTURE")
        if snapshot.captured_at > evaluated_at:
            reasons.append("SNAPSHOT_CAPTURE_IN_FUTURE")
        if evaluated_at > snapshot.valid_until:
            reasons.append("SNAPSHOT_EXPIRED")
        object.__setattr__(self, "evaluated_at", evaluated_at)
        object.__setattr__(self, "current", not reasons)
        object.__setattr__(self, "reason_codes", tuple(reasons))


@dataclass(frozen=True, slots=True)
class PositionSnapshot:
    snapshot_id: UUID
    account_id: UUID
    position_id: UUID
    state: SnapshotState
    reason_codes: tuple[str, ...]
    asset: str
    instrument_id: str
    side: PositionSide
    margin_mode: MarginMode
    quantity: Decimal | None
    entry_price: PriceValue | None
    mark_price: PriceValue | None
    notional: MoneyValue | None
    leverage: Decimal | None
    margin_used: MoneyValue | None
    unrealized_pnl: MoneyValue | None
    liquidation_price: PriceValue | None
    stop_loss: PriceValue | None
    take_profit_targets: tuple[TakeProfitTarget, ...]
    order_ids: tuple[UUID, ...]
    fill_ids: tuple[UUID, ...]
    source_version: VersionReference
    as_of: datetime
    captured_at: datetime
    valid_until: datetime
    content_sha256: str
    contract_id: str = field(default="C-075", init=False)
    schema_version: str = field(default=CONTRACT_SCHEMA_VERSION, init=False)

    def __post_init__(self) -> None:
        for name in ("snapshot_id", "account_id", "position_id"):
            _uuid(name, getattr(self, name))
        if not isinstance(self.state, SnapshotState):
            raise RiskContractError("state must be a SnapshotState.")
        reasons = _text_tuple("reason_codes", self.reason_codes)
        _text("asset", self.asset)
        _text("instrument_id", self.instrument_id)
        if not isinstance(self.side, PositionSide):
            raise RiskContractError("side must be a PositionSide.")
        if not isinstance(self.margin_mode, MarginMode):
            raise RiskContractError("margin_mode must be a MarginMode.")
        orders = _uuid_tuple("order_ids", self.order_ids)
        fills = _uuid_tuple("fill_ids", self.fill_ids)
        targets = _typed_tuple(
            "take_profit_targets", self.take_profit_targets, TakeProfitTarget
        )
        _unique("take_profit sequence", tuple(item.sequence for item in targets))
        required = (
            self.quantity,
            self.entry_price,
            self.mark_price,
            self.notional,
            self.leverage,
            self.margin_used,
            self.unrealized_pnl,
        )
        if self.state is SnapshotState.VALID:
            if any(value is None for value in required):
                raise RiskContractError("valid position snapshot requires all values.")
            if not orders and not fills:
                raise RiskContractError(
                    "valid position requires order or fill attribution."
                )
        elif not reasons:
            raise RiskContractError(
                "non-valid position snapshot requires reason_codes."
            )
        if self.quantity is not None:
            _positive("quantity", self.quantity)
        if self.leverage is not None:
            _positive("leverage", self.leverage)
        for name in ("entry_price", "mark_price", "liquidation_price", "stop_loss"):
            value = getattr(self, name)
            if value is not None and not isinstance(value, PriceValue):
                raise RiskContractError(f"{name} must be a PriceValue.")
        for name in ("notional", "margin_used", "unrealized_pnl"):
            value = getattr(self, name)
            if value is not None and not isinstance(value, MoneyValue):
                raise RiskContractError(f"{name} must be a MoneyValue.")
        currencies = {
            value.quote_currency
            for value in (
                self.entry_price,
                self.mark_price,
                self.liquidation_price,
                self.stop_loss,
            )
            if value is not None
        } | {
            value.currency
            for value in (self.notional, self.margin_used, self.unrealized_pnl)
            if value is not None
        }
        if len(currencies) > 1:
            raise RiskContractError("position price/money currencies must match.")
        if self.notional is not None and self.notional.amount <= 0:
            raise RiskContractError("notional must be positive.")
        if self.margin_used is not None and self.margin_used.amount < 0:
            raise RiskContractError("margin_used must be non-negative.")
        if not isinstance(self.source_version, VersionReference):
            raise RiskContractError("source_version must be a VersionReference.")
        as_of, captured, valid = _snapshot_times(
            self.as_of, self.captured_at, self.valid_until
        )
        _digest("content_sha256", self.content_sha256)
        object.__setattr__(self, "as_of", as_of)
        object.__setattr__(self, "captured_at", captured)
        object.__setattr__(self, "valid_until", valid)


@dataclass(frozen=True, slots=True)
class PortfolioSnapshot:
    snapshot_id: UUID
    account_snapshot: AccountSnapshot
    state: SnapshotState
    reason_codes: tuple[str, ...]
    positions: tuple[PositionSnapshot, ...]
    currency: str
    equity: MoneyValue | None
    cash: MoneyValue | None
    margin: MoneyValue | None
    pending_risk: MoneyValue | None
    total_exposure: MoneyValue | None
    gross_exposure: MoneyValue | None
    net_exposure: MoneyValue | None
    directional_exposures: tuple[ExposureValue, ...]
    asset_exposures: tuple[ExposureValue, ...]
    strategy_exposures: tuple[ExposureValue, ...]
    correlated_exposures: tuple[ExposureValue, ...]
    drawdown: RatioValue | None
    volatility: RatioValue | None
    gross_leverage: Decimal | None
    net_leverage: Decimal | None
    source_version: VersionReference
    as_of: datetime
    captured_at: datetime
    valid_until: datetime
    content_sha256: str
    contract_id: str = field(default="C-033", init=False)
    schema_version: str = field(default=CONTRACT_SCHEMA_VERSION, init=False)

    def __post_init__(self) -> None:
        _uuid("snapshot_id", self.snapshot_id)
        if not isinstance(self.account_snapshot, AccountSnapshot):
            raise RiskContractError("account_snapshot must be an AccountSnapshot.")
        if not isinstance(self.state, SnapshotState):
            raise RiskContractError("state must be a SnapshotState.")
        reasons = _text_tuple("reason_codes", self.reason_codes)
        positions = _typed_tuple("positions", self.positions, PositionSnapshot)
        _unique("position identities", tuple(item.position_id for item in positions))
        currency = _text("currency", self.currency)
        money = (
            self.equity,
            self.cash,
            self.margin,
            self.pending_risk,
            self.total_exposure,
            self.gross_exposure,
            self.net_exposure,
        )
        exposure_groups = (
            self.directional_exposures,
            self.asset_exposures,
            self.strategy_exposures,
            self.correlated_exposures,
        )
        for index, group in enumerate(exposure_groups):
            values = _typed_tuple(
                f"exposures[{index}]",
                group,
                ExposureValue,
                empty=self.state is not SnapshotState.VALID,
            )
            _unique(
                f"exposures[{index}] identities",
                tuple((item.dimension, item.key) for item in values),
            )
        if self.state is SnapshotState.VALID:
            if self.account_snapshot.state is not SnapshotState.VALID:
                raise RiskContractError(
                    "valid portfolio requires valid account snapshot."
                )
            if any(value is None for value in money) or any(
                value is None
                for value in (
                    self.drawdown,
                    self.volatility,
                    self.gross_leverage,
                    self.net_leverage,
                )
            ):
                raise RiskContractError(
                    "valid portfolio snapshot requires all aggregates."
                )
            if any(item.state is not SnapshotState.VALID for item in positions):
                raise RiskContractError(
                    "valid portfolio cannot contain non-valid positions."
                )
            if any(
                item.account_id != self.account_snapshot.account_id
                for item in positions
            ):
                raise RiskContractError("position account identity mismatch.")
        elif not reasons:
            raise RiskContractError(
                "non-valid portfolio snapshot requires reason_codes."
            )
        for value in money:
            if value is not None:
                if not isinstance(value, MoneyValue) or value.currency != currency:
                    raise RiskContractError(
                        "portfolio money values must use its currency."
                    )
        for name in (
            "cash",
            "margin",
            "pending_risk",
            "total_exposure",
            "gross_exposure",
        ):
            value = getattr(self, name)
            if value is not None and value.amount < 0:
                raise RiskContractError(f"{name} must be non-negative.")
        for name in ("drawdown", "volatility"):
            value = getattr(self, name)
            if value is not None and not isinstance(value, RatioValue):
                raise RiskContractError(f"{name} must be a RatioValue.")
        for name in ("gross_leverage", "net_leverage"):
            value = getattr(self, name)
            if value is not None:
                _nonnegative(name, value)
        if not isinstance(self.source_version, VersionReference):
            raise RiskContractError("source_version must be a VersionReference.")
        as_of, captured, valid = _snapshot_times(
            self.as_of, self.captured_at, self.valid_until
        )
        if self.account_snapshot.valid_until < valid:
            raise RiskContractError(
                "account snapshot expires before portfolio snapshot."
            )
        _digest("content_sha256", self.content_sha256)
        object.__setattr__(self, "as_of", as_of)
        object.__setattr__(self, "captured_at", captured)
        object.__setattr__(self, "valid_until", valid)


@dataclass(frozen=True, slots=True)
class _AssessmentBase:
    result_id: UUID
    context: RiskContext
    outcome: RiskCheckOutcome
    reason_codes: tuple[str, ...]
    model_version: VersionReference
    as_of: datetime
    evaluated_at: datetime
    valid_until: datetime
    content_sha256: str
    schema_version: str = field(default=CONTRACT_SCHEMA_VERSION, init=False)

    def __post_init__(self) -> None:
        _uuid("result_id", self.result_id)
        if not isinstance(self.context, RiskContext):
            raise RiskContractError("context must be a RiskContext.")
        if not isinstance(self.outcome, RiskCheckOutcome):
            raise RiskContractError("outcome must be a RiskCheckOutcome.")
        reasons = _text_tuple("reason_codes", self.reason_codes)
        if self.outcome is not RiskCheckOutcome.PASSED and not reasons:
            raise RiskContractError("non-passed assessment requires reason_codes.")
        if not isinstance(self.model_version, VersionReference):
            raise RiskContractError("model_version must be a VersionReference.")
        as_of, evaluated, valid = _temporal(
            self.as_of, self.evaluated_at, self.valid_until
        )
        if self.context.as_of != as_of:
            raise RiskContractError("assessment context as_of mismatch.")
        _digest("content_sha256", self.content_sha256)
        object.__setattr__(self, "as_of", as_of)
        object.__setattr__(self, "evaluated_at", evaluated)
        object.__setattr__(self, "valid_until", valid)


def _limits(name: str, value: object) -> tuple[RiskLimitResult, ...]:
    limits = _typed_tuple(name, value, RiskLimitResult)
    _unique(name, tuple(item.limit_id for item in limits))
    return limits


def _hard_failure(limits: tuple[RiskLimitResult, ...]) -> bool:
    return any(
        item.severity is RiskLimitSeverity.HARD
        and item.outcome
        in {RiskCheckOutcome.FAILED, RiskCheckOutcome.INSUFFICIENT_DATA}
        for item in limits
    )


def _money(name: str, value: object, *, positive: bool = False) -> MoneyValue:
    if not isinstance(value, MoneyValue):
        raise RiskContractError(f"{name} must be a MoneyValue.")
    if positive and value.amount <= 0:
        raise RiskContractError(f"{name} must be positive.")
    if not positive and value.amount < 0:
        raise RiskContractError(f"{name} must be non-negative.")
    return value


@dataclass(frozen=True, slots=True)
class PositionSizingResult(_AssessmentBase):
    method: SizingMethod
    sizing_assumptions: tuple[VersionReference, ...]
    requested_risk: MoneyValue
    requested_notional: MoneyValue | None
    recommended_quantity: Decimal | None
    recommended_notional: MoneyValue | None
    recommended_margin: MoneyValue | None
    stop_distance: Decimal | None
    maximum_loss: MoneyValue | None
    account_risk: RatioValue | None
    minimum_quantity: Decimal | None
    maximum_quantity: Decimal | None
    quantity_step: Decimal | None
    contract_id: str = field(default="C-036", init=False)

    def __post_init__(self) -> None:
        _AssessmentBase.__post_init__(self)
        if not isinstance(self.method, SizingMethod):
            raise RiskContractError("method must be a SizingMethod.")
        _typed_tuple(
            "sizing_assumptions", self.sizing_assumptions, VersionReference, empty=False
        )
        _money("requested_risk", self.requested_risk, positive=True)
        if self.requested_notional is not None:
            _money("requested_notional", self.requested_notional, positive=True)
        for name in (
            "recommended_quantity",
            "stop_distance",
            "minimum_quantity",
            "maximum_quantity",
            "quantity_step",
        ):
            value = getattr(self, name)
            if value is not None:
                _positive(name, value)
        for name in ("recommended_notional", "recommended_margin", "maximum_loss"):
            value = getattr(self, name)
            if value is not None:
                _money(name, value, positive=True)
        if self.account_risk is not None and not isinstance(
            self.account_risk, RatioValue
        ):
            raise RiskContractError("account_risk must be a RatioValue.")
        if (
            self.minimum_quantity is not None
            and self.maximum_quantity is not None
            and self.minimum_quantity > self.maximum_quantity
        ):
            raise RiskContractError(
                "minimum_quantity must not exceed maximum_quantity."
            )
        if self.outcome is RiskCheckOutcome.PASSED:
            required = (
                self.recommended_quantity,
                self.recommended_notional,
                self.recommended_margin,
                self.stop_distance,
                self.maximum_loss,
                self.account_risk,
                self.minimum_quantity,
                self.maximum_quantity,
                self.quantity_step,
            )
            if any(value is None for value in required):
                raise RiskContractError(
                    "passed sizing requires complete bounded output."
                )
            assert self.recommended_quantity is not None
            assert self.minimum_quantity is not None
            assert self.maximum_quantity is not None
            if (
                not self.minimum_quantity
                <= self.recommended_quantity
                <= self.maximum_quantity
            ):
                raise RiskContractError(
                    "recommended quantity violates exchange bounds."
                )


@dataclass(frozen=True, slots=True)
class SizingInstrumentTerms:
    """Caller-supplied linear terms; quantities are in contract units."""

    asset: str
    instrument_id: str
    venue: str
    model: str
    quote_currency: str
    contract_multiplier: Decimal
    tick_size: Decimal
    minimum_quantity: Decimal
    maximum_quantity: Decimal
    quantity_step: Decimal
    maximum_notional: MoneyValue
    initial_margin_per_unit: MoneyValue
    version: VersionReference

    def __post_init__(self) -> None:
        for name in ("asset", "instrument_id", "venue", "model", "quote_currency"):
            _text(name, getattr(self, name))
        for name in (
            "contract_multiplier",
            "tick_size",
            "minimum_quantity",
            "maximum_quantity",
            "quantity_step",
        ):
            _positive(name, getattr(self, name))
        if self.minimum_quantity > self.maximum_quantity:
            raise RiskContractError("minimum quantity exceeds maximum quantity.")
        for name in ("maximum_notional", "initial_margin_per_unit"):
            value = _money(name, getattr(self, name), positive=True)
            if value.currency != self.quote_currency:
                raise RiskContractError("instrument money currency mismatch.")
        if not isinstance(self.version, VersionReference):
            raise RiskContractError("instrument version must be a VersionReference.")


@dataclass(frozen=True, slots=True)
class SizingCosts:
    """Explicit adverse round-trip costs per quantity unit, never inferred."""

    fee: MoneyValue
    slippage: MoneyValue
    funding: MoneyValue
    version: VersionReference

    def __post_init__(self) -> None:
        for name in ("fee", "slippage", "funding"):
            _money(name, getattr(self, name))
        if len({self.fee.currency, self.slippage.currency, self.funding.currency}) != 1:
            raise RiskContractError("cost currencies must match.")
        if not isinstance(self.version, VersionReference):
            raise RiskContractError("cost version must be a VersionReference.")


@dataclass(frozen=True, slots=True)
class PositionSizingRequest:
    """Offline inputs; the caller attests the common assumptions' validity window."""

    result_id: UUID
    context: RiskContext
    account: AccountSnapshot
    portfolio: PortfolioSnapshot
    method: SizingMethod
    mode: RiskPolicyMode
    entry: PriceValue
    stop: PriceValue
    effective_risk: MoneyValue
    policy_version: VersionReference
    configuration_version: VersionReference
    budget_version: VersionReference
    model_version: VersionReference
    evaluated_at: datetime
    assumptions_as_of: datetime
    assumptions_valid_until: datetime
    instrument: SizingInstrumentTerms | None
    costs: SizingCosts | None
    requested_notional: MoneyValue | None = None
    equity_fraction: Decimal | None = None
    volatility_loss_per_unit: MoneyValue | None = None
    volatility_version: VersionReference | None = None
    win_probability: Decimal | None = None
    win_loss_ratio: Decimal | None = None
    kelly_fraction: Decimal | None = None
    kelly_version: VersionReference | None = None

    def __post_init__(self) -> None:
        _uuid("result_id", self.result_id)
        if not isinstance(self.context, RiskContext):
            raise RiskContractError("context must be a RiskContext.")
        if not isinstance(self.account, AccountSnapshot):
            raise RiskContractError("account must be an AccountSnapshot.")
        if not isinstance(self.portfolio, PortfolioSnapshot):
            raise RiskContractError("portfolio must be a PortfolioSnapshot.")
        if not isinstance(self.method, SizingMethod):
            raise RiskContractError("method must be a SizingMethod.")
        if not isinstance(self.mode, RiskPolicyMode):
            raise RiskContractError("mode must be a RiskPolicyMode.")
        for name in ("entry", "stop"):
            if not isinstance(getattr(self, name), PriceValue):
                raise RiskContractError(f"{name} must be a PriceValue.")
        _money("effective_risk", self.effective_risk, positive=True)
        for name in (
            "policy_version",
            "configuration_version",
            "budget_version",
            "model_version",
        ):
            if not isinstance(getattr(self, name), VersionReference):
                raise RiskContractError(f"{name} must be a VersionReference.")
        for name, expected in (
            ("instrument", SizingInstrumentTerms),
            ("costs", SizingCosts),
            ("volatility_version", VersionReference),
            ("kelly_version", VersionReference),
        ):
            value = getattr(self, name)
            if value is not None and not isinstance(value, expected):
                raise RiskContractError(f"{name} has an invalid type.")
        for name in ("requested_notional", "volatility_loss_per_unit"):
            value = getattr(self, name)
            if value is not None:
                _money(name, value, positive=True)
        for name in ("equity_fraction", "kelly_fraction"):
            value = getattr(self, name)
            if value is not None and not Decimal(0) < _decimal(name, value) <= 1:
                raise RiskContractError(f"{name} must be in (0, 1].")
        if self.win_probability is not None:
            value = _decimal("win_probability", self.win_probability)
            if not 0 <= value <= 1:
                raise RiskContractError("win_probability must be in [0, 1].")
        if self.win_loss_ratio is not None:
            _positive("win_loss_ratio", self.win_loss_ratio)
        for name in ("evaluated_at", "assumptions_as_of", "assumptions_valid_until"):
            object.__setattr__(self, name, _time(name, getattr(self, name)))
        _ordered(
            "assumptions_as_of",
            self.assumptions_as_of,
            "assumptions_valid_until",
            self.assumptions_valid_until,
        )
        _ordered("context.as_of", self.context.as_of, "evaluated_at", self.evaluated_at)


@dataclass(frozen=True, slots=True)
class StopLossStructuralEvidence:
    """Caller-attested priced invalidation interval and exact strategy lineage."""

    reference: ContractReference
    context: RiskContext
    strategy_version: ContractReference
    asset: str
    instrument_id: str
    side: PositionSide
    lower_stop: PriceValue
    upper_stop: PriceValue
    version: VersionReference
    as_of: datetime
    valid_until: datetime

    def __post_init__(self) -> None:
        if not isinstance(self.reference, ContractReference):
            raise RiskContractError("reference must be a ContractReference.")
        if self.reference.contract_id != "C-023":
            raise RiskContractError("reference must reference C-023.")
        if not isinstance(self.context, RiskContext):
            raise RiskContractError("context must be a RiskContext.")
        if not isinstance(self.strategy_version, ContractReference):
            raise RiskContractError("strategy_version must be a ContractReference.")
        if self.strategy_version.contract_id != "C-021":
            raise RiskContractError("strategy_version must reference C-021.")
        _text("asset", self.asset)
        _text("instrument_id", self.instrument_id)
        if not isinstance(self.side, PositionSide):
            raise RiskContractError("side must be a PositionSide.")
        for name in ("lower_stop", "upper_stop"):
            if not isinstance(getattr(self, name), PriceValue):
                raise RiskContractError(f"{name} must be a PriceValue.")
        if self.lower_stop.quote_currency != self.upper_stop.quote_currency:
            raise RiskContractError("structural interval currencies must match.")
        if self.lower_stop.amount > self.upper_stop.amount:
            raise RiskContractError("structural interval bounds are reversed.")
        if not isinstance(self.version, VersionReference):
            raise RiskContractError("version must be a VersionReference.")
        as_of = _time("as_of", self.as_of)
        valid_until = _time("valid_until", self.valid_until)
        _ordered("as_of", as_of, "valid_until", valid_until)
        object.__setattr__(self, "as_of", as_of)
        object.__setattr__(self, "valid_until", valid_until)


@dataclass(frozen=True, slots=True)
class StopLossVolatilityEvidence:
    """Caller-supplied minimum-distance threshold; this does not estimate volatility."""

    context: RiskContext
    asset: str
    instrument_id: str
    side: PositionSide
    minimum_distance: Decimal
    quote_currency: str
    version: VersionReference
    as_of: datetime
    valid_until: datetime

    def __post_init__(self) -> None:
        if not isinstance(self.context, RiskContext):
            raise RiskContractError("context must be a RiskContext.")
        _text("asset", self.asset)
        _text("instrument_id", self.instrument_id)
        if not isinstance(self.side, PositionSide):
            raise RiskContractError("side must be a PositionSide.")
        _nonnegative("minimum_distance", self.minimum_distance)
        _text("quote_currency", self.quote_currency)
        if not isinstance(self.version, VersionReference):
            raise RiskContractError("version must be a VersionReference.")
        as_of = _time("as_of", self.as_of)
        valid_until = _time("valid_until", self.valid_until)
        _ordered("as_of", as_of, "valid_until", valid_until)
        object.__setattr__(self, "as_of", as_of)
        object.__setattr__(self, "valid_until", valid_until)


@dataclass(frozen=True, slots=True)
class StopLossLiquidationEvidence:
    """Caller-supplied liquidation boundary; no liquidation model is evaluated."""

    context: RiskContext
    asset: str
    instrument_id: str
    side: PositionSide
    availability: LiquidationAvailability
    liquidation_price: PriceValue | None
    minimum_buffer: Decimal
    quote_currency: str
    fully_funded_spot: bool
    version: VersionReference
    as_of: datetime
    valid_until: datetime

    def __post_init__(self) -> None:
        if not isinstance(self.context, RiskContext):
            raise RiskContractError("context must be a RiskContext.")
        _text("asset", self.asset)
        _text("instrument_id", self.instrument_id)
        if not isinstance(self.side, PositionSide):
            raise RiskContractError("side must be a PositionSide.")
        if not isinstance(self.availability, LiquidationAvailability):
            raise RiskContractError("availability must be LiquidationAvailability.")
        if self.liquidation_price is not None and not isinstance(
            self.liquidation_price, PriceValue
        ):
            raise RiskContractError("liquidation_price must be a PriceValue or None.")
        _nonnegative("minimum_buffer", self.minimum_buffer)
        _text("quote_currency", self.quote_currency)
        if not isinstance(self.fully_funded_spot, bool):
            raise RiskContractError("fully_funded_spot must be a bool.")
        if not isinstance(self.version, VersionReference):
            raise RiskContractError("version must be a VersionReference.")
        as_of = _time("as_of", self.as_of)
        valid_until = _time("valid_until", self.valid_until)
        _ordered("as_of", as_of, "valid_until", valid_until)
        object.__setattr__(self, "as_of", as_of)
        object.__setattr__(self, "valid_until", valid_until)


@dataclass(frozen=True, slots=True)
class StopLossAssessmentRequest:
    """Explicit offline inputs for a bounded C-078 stop-loss assessment."""

    result_id: UUID
    context: RiskContext
    account: AccountSnapshot
    portfolio: PortfolioSnapshot
    entry_price: PriceValue
    stop_loss: PriceValue | None
    quantity: Decimal
    effective_maximum_loss: MoneyValue
    instrument: SizingInstrumentTerms
    costs: SizingCosts
    policy_version: VersionReference
    configuration_version: VersionReference
    model_version: VersionReference
    account_source_version: VersionReference
    portfolio_source_version: VersionReference
    strategy_invalidation: ContractReference
    minimum_stop_distance: Decimal
    adverse_gap_displacement: Decimal
    gap_version: VersionReference
    evaluated_at: datetime
    assumptions_as_of: datetime
    assumptions_valid_until: datetime
    structural_evidence: StopLossStructuralEvidence | None
    volatility_evidence: StopLossVolatilityEvidence | None
    liquidation_evidence: StopLossLiquidationEvidence | None

    def __post_init__(self) -> None:
        _uuid("result_id", self.result_id)
        if not isinstance(self.context, RiskContext):
            raise RiskContractError("context must be a RiskContext.")
        if not isinstance(self.account, AccountSnapshot):
            raise RiskContractError("account must be an AccountSnapshot.")
        if not isinstance(self.portfolio, PortfolioSnapshot):
            raise RiskContractError("portfolio must be a PortfolioSnapshot.")
        for name in ("entry_price",):
            if not isinstance(getattr(self, name), PriceValue):
                raise RiskContractError(f"{name} must be a PriceValue.")
        if self.stop_loss is not None and not isinstance(self.stop_loss, PriceValue):
            raise RiskContractError("stop_loss must be a PriceValue or None.")
        _positive("quantity", self.quantity)
        _money("effective_maximum_loss", self.effective_maximum_loss, positive=True)
        if not isinstance(self.instrument, SizingInstrumentTerms):
            raise RiskContractError("instrument must be SizingInstrumentTerms.")
        if not isinstance(self.costs, SizingCosts):
            raise RiskContractError("costs must be SizingCosts.")
        for name in (
            "policy_version",
            "configuration_version",
            "model_version",
            "account_source_version",
            "portfolio_source_version",
            "gap_version",
        ):
            if not isinstance(getattr(self, name), VersionReference):
                raise RiskContractError(f"{name} must be a VersionReference.")
        if not isinstance(self.strategy_invalidation, ContractReference):
            raise RiskContractError(
                "strategy_invalidation must be a ContractReference."
            )
        if self.strategy_invalidation.contract_id != "C-023":
            raise RiskContractError("strategy_invalidation must reference C-023.")
        _nonnegative("minimum_stop_distance", self.minimum_stop_distance)
        _nonnegative("adverse_gap_displacement", self.adverse_gap_displacement)
        for name, expected in (
            ("structural_evidence", StopLossStructuralEvidence),
            ("volatility_evidence", StopLossVolatilityEvidence),
            ("liquidation_evidence", StopLossLiquidationEvidence),
        ):
            value = getattr(self, name)
            if value is not None and not isinstance(value, expected):
                raise RiskContractError(f"{name} has an invalid type.")
        evaluated = _time("evaluated_at", self.evaluated_at)
        assumptions_as_of = _time("assumptions_as_of", self.assumptions_as_of)
        assumptions_valid_until = _time(
            "assumptions_valid_until", self.assumptions_valid_until
        )
        _ordered(
            "assumptions_as_of",
            assumptions_as_of,
            "assumptions_valid_until",
            assumptions_valid_until,
        )
        _ordered("context.as_of", self.context.as_of, "evaluated_at", evaluated)
        object.__setattr__(self, "evaluated_at", evaluated)
        object.__setattr__(self, "assumptions_as_of", assumptions_as_of)
        object.__setattr__(self, "assumptions_valid_until", assumptions_valid_until)


def _sizing_input_failure(
    request: PositionSizingRequest,
) -> tuple[RiskCheckOutcome, str] | None:
    account, portfolio = request.account, request.portfolio
    if portfolio.account_snapshot != account:
        return RiskCheckOutcome.FAILED, "ACCOUNT_PORTFOLIO_MISMATCH"
    if portfolio.equity != account.equity or portfolio.currency != account.currency:
        return RiskCheckOutcome.FAILED, "PORTFOLIO_EQUITY_MISMATCH"
    for snapshot, reference in (
        (account, request.context.account_snapshot),
        (portfolio, request.context.portfolio_snapshot),
    ):
        if (
            reference.entity_id != snapshot.snapshot_id
            or reference.schema_version != snapshot.schema_version
            or reference.content_sha256 != snapshot.content_sha256
            or reference.valid_until != snapshot.valid_until
        ):
            return RiskCheckOutcome.FAILED, "SNAPSHOT_REFERENCE_MISMATCH"
    snapshots: tuple[AccountSnapshot | PortfolioSnapshot | PositionSnapshot, ...] = (
        account,
        portfolio,
        *portfolio.positions,
    )
    if any(item.state is not SnapshotState.VALID for item in snapshots):
        return RiskCheckOutcome.INSUFFICIENT_DATA, "SNAPSHOT_NOT_VALID"
    if any(
        item.as_of > request.evaluated_at
        or item.captured_at > request.evaluated_at
        or item.valid_until < request.evaluated_at
        for item in snapshots
    ):
        return RiskCheckOutcome.INSUFFICIENT_DATA, "SNAPSHOT_NOT_CURRENT"
    for name in (
        "signal",
        "validation",
        "strategy_version",
        "account_snapshot",
        "portfolio_snapshot",
    ):
        reference = getattr(request.context, name)
        if (
            reference.content_sha256 is None
            or reference.valid_until is None
            or reference.valid_until < request.evaluated_at
        ):
            return RiskCheckOutcome.INSUFFICIENT_DATA, "CONTEXT_EVIDENCE_NOT_CURRENT"
    if (
        request.assumptions_as_of > request.evaluated_at
        or request.assumptions_valid_until < request.evaluated_at
    ):
        return RiskCheckOutcome.INSUFFICIENT_DATA, "ASSUMPTIONS_NOT_CURRENT"
    terms, costs = request.instrument, request.costs
    if terms is None or costs is None:
        return RiskCheckOutcome.INSUFFICIENT_DATA, "SIZING_ASSUMPTIONS_MISSING"
    if terms.model != "LINEAR":
        return RiskCheckOutcome.FAILED, "UNSUPPORTED_INSTRUMENT_MODEL"
    if (
        terms.instrument_id != request.context.instrument_id
        or terms.asset != request.context.asset
    ):
        return RiskCheckOutcome.FAILED, "INSTRUMENT_CONTEXT_MISMATCH"
    currency = terms.quote_currency
    if (
        account.currency != currency
        or request.entry.quote_currency != currency
        or request.stop.quote_currency != currency
        or any(
            value.currency != currency
            for value in (
                request.effective_risk,
                costs.fee,
                costs.slippage,
                costs.funding,
                request.requested_notional,
                request.volatility_loss_per_unit,
            )
            if value is not None
        )
    ):
        return RiskCheckOutcome.FAILED, "SIZING_CURRENCY_MISMATCH"
    if (
        request.context.side is PositionSide.LONG
        and request.stop.amount >= request.entry.amount
    ) or (
        request.context.side is PositionSide.SHORT
        and request.stop.amount <= request.entry.amount
    ):
        return RiskCheckOutcome.FAILED, "INVALID_STOP_DIRECTION"
    if (
        request.entry.amount % terms.tick_size != 0
        or request.stop.amount % terms.tick_size != 0
    ):
        return RiskCheckOutcome.FAILED, "PRICE_OFF_TICK"
    return None


def _sizing_result(
    request: PositionSizingRequest,
    outcome: RiskCheckOutcome,
    reasons: tuple[str, ...],
    *,
    quantity: Decimal | None = None,
    notional: Decimal | None = None,
    margin: Decimal | None = None,
    loss: Decimal | None = None,
    account_risk: Decimal | None = None,
    stop_distance: Decimal | None = None,
) -> PositionSizingResult:
    versions = (
        request.policy_version,
        request.configuration_version,
        request.budget_version,
        request.model_version,
        request.instrument.version if request.instrument is not None else None,
        request.costs.version if request.costs is not None else None,
        request.volatility_version,
        request.kelly_version,
    )
    expiry = min(
        request.assumptions_valid_until,
        request.account.valid_until,
        request.portfolio.valid_until,
        *(item.valid_until for item in request.portfolio.positions),
        *(
            reference.valid_until
            for reference in (
                request.context.signal,
                request.context.validation,
                request.context.strategy_version,
                request.context.account_snapshot,
                request.context.portfolio_snapshot,
            )
            if reference.valid_until is not None
        ),
    )
    currency = request.effective_risk.currency
    terms = request.instrument
    result = PositionSizingResult(
        result_id=request.result_id,
        context=request.context,
        outcome=outcome,
        reason_codes=reasons,
        model_version=request.model_version,
        as_of=request.context.as_of,
        evaluated_at=request.evaluated_at,
        valid_until=max(expiry, request.evaluated_at),
        content_sha256="0" * 64,
        method=request.method,
        sizing_assumptions=tuple(value for value in versions if value is not None),
        requested_risk=request.effective_risk,
        requested_notional=request.requested_notional,
        recommended_quantity=quantity,
        recommended_notional=MoneyValue(notional, currency)
        if notional is not None
        else None,
        recommended_margin=MoneyValue(margin, currency) if margin is not None else None,
        stop_distance=stop_distance,
        maximum_loss=MoneyValue(loss, currency) if loss is not None else None,
        account_risk=RatioValue(account_risk, "maximum-loss/equity")
        if account_risk is not None
        else None,
        minimum_quantity=terms.minimum_quantity if terms is not None else None,
        maximum_quantity=terms.maximum_quantity if terms is not None else None,
        quantity_step=terms.quantity_step if terms is not None else None,
    )
    return replace(
        result,
        content_sha256=_risk_digest(
            "position sizing",
            {
                "request": request,
                "result": {
                    item.name: getattr(result, item.name)
                    for item in fields(result)
                    if item.name != "content_sha256"
                },
            },
        ),
    )


def _sizing_target_notional(
    request: PositionSizingRequest, equity: Decimal
) -> tuple[Decimal | None, tuple[RiskCheckOutcome, str] | None]:
    if request.method is SizingMethod.FIXED_NOTIONAL:
        if request.requested_notional is None:
            return None, (RiskCheckOutcome.INSUFFICIENT_DATA, "NOTIONAL_MISSING")
        return request.requested_notional.amount, None
    if request.method is SizingMethod.PERCENTAGE_OF_EQUITY:
        if request.equity_fraction is None:
            return None, (RiskCheckOutcome.INSUFFICIENT_DATA, "EQUITY_FRACTION_MISSING")
        return equity * request.equity_fraction, None
    if request.method is SizingMethod.FRACTIONAL_KELLY:
        if request.mode not in {RiskPolicyMode.RESEARCH, RiskPolicyMode.BACKTEST}:
            return None, (RiskCheckOutcome.FAILED, "KELLY_RESEARCH_ONLY")
        if (
            request.win_probability is None
            or request.win_loss_ratio is None
            or request.kelly_fraction is None
            or request.kelly_version is None
        ):
            return None, (RiskCheckOutcome.INSUFFICIENT_DATA, "KELLY_INPUTS_MISSING")
        # Round the losing-probability term upward so edge is never overstated.
        with localcontext() as context:
            context.rounding = ROUND_CEILING
            losing_term = (
                Decimal(1) - request.win_probability
            ) / request.win_loss_ratio
        with localcontext() as context:
            context.rounding = ROUND_FLOOR
            fraction = request.kelly_fraction * (request.win_probability - losing_term)
            if fraction <= 0:
                return None, (RiskCheckOutcome.FAILED, "NO_TRADE_NONPOSITIVE_KELLY")
            return equity * fraction, None
    return None, None


def calculate_position_size(request: PositionSizingRequest) -> PositionSizingResult:
    """Calculate offline sizing, never approval, with precision-34 safe caps."""
    if not isinstance(request, PositionSizingRequest):
        raise RiskContractError("request must be a PositionSizingRequest.")
    try:
        with localcontext(Context(prec=34, rounding=ROUND_HALF_EVEN)):
            failure = _sizing_input_failure(request)
            if failure is not None:
                return _sizing_result(request, failure[0], (failure[1],))
            terms, costs = request.instrument, request.costs
            assert terms is not None and costs is not None
            equity, free_margin = request.account.equity, request.account.free_margin
            assert equity is not None and free_margin is not None
            if request.effective_risk.amount > equity.amount:
                return _sizing_result(
                    request, RiskCheckOutcome.FAILED, ("RISK_EXCEEDS_EQUITY",)
                )
            # Exact unit math fails closed if precision 34 cannot represent it.
            with localcontext() as exact:
                exact.traps[Inexact] = True
                distance = abs(request.entry.amount - request.stop.amount)
                stop_loss = distance * terms.contract_multiplier
                loss_basis = stop_loss
                if request.method is SizingMethod.VOLATILITY_ADJUSTED:
                    if (
                        request.volatility_loss_per_unit is None
                        or request.volatility_version is None
                    ):
                        return _sizing_result(
                            request,
                            RiskCheckOutcome.INSUFFICIENT_DATA,
                            ("VOLATILITY_INPUTS_MISSING",),
                        )
                    loss_basis = max(stop_loss, request.volatility_loss_per_unit.amount)
                unit_loss = (
                    loss_basis
                    + costs.fee.amount
                    + costs.slippage.amount
                    + costs.funding.amount
                )
                unit_notional = request.entry.amount * terms.contract_multiplier
                step_loss = unit_loss * terms.quantity_step
                step_notional = unit_notional * terms.quantity_step
                step_margin = terms.initial_margin_per_unit.amount * terms.quantity_step
            with localcontext() as downward:
                downward.rounding = ROUND_FLOOR
                target, failure = _sizing_target_notional(request, equity.amount)
                if failure is not None:
                    return _sizing_result(request, failure[0], (failure[1],))
                caps = (
                    request.effective_risk.amount / step_loss,
                    terms.maximum_quantity / terms.quantity_step,
                    terms.maximum_notional.amount / step_notional,
                    free_margin.amount / step_margin,
                )
                step_count = min(
                    (*caps, target / step_notional) if target is not None else caps
                ).to_integral_value(rounding=ROUND_FLOOR)
            with localcontext() as exact:
                exact.traps[Inexact] = True
                quantity = step_count * terms.quantity_step
                notional = step_count * step_notional
                margin = step_count * step_margin
                loss = step_count * step_loss
            if quantity < terms.minimum_quantity:
                return _sizing_result(
                    request, RiskCheckOutcome.FAILED, ("NO_TRADE_BELOW_MINIMUM",)
                )
            if (
                quantity > terms.maximum_quantity
                or loss > request.effective_risk.amount
                or notional > terms.maximum_notional.amount
                or margin > free_margin.amount
                or (target is not None and notional > target)
            ):
                return _sizing_result(
                    request, RiskCheckOutcome.FAILED, ("SIZING_BOUNDS_VIOLATED",)
                )
            capped = (target is not None and notional < target) or (
                request.method is SizingMethod.VOLATILITY_ADJUSTED
                and loss < request.effective_risk.amount
            )
            return _sizing_result(
                request,
                RiskCheckOutcome.WARNING if capped else RiskCheckOutcome.PASSED,
                ("REQUESTED_TARGET_REDUCED",) if capped else (),
                quantity=quantity,
                notional=notional,
                margin=margin,
                loss=loss,
                account_risk=loss / equity.amount,
                stop_distance=distance,
            )
    except DecimalException as exc:
        raise RiskContractError(
            "sizing arithmetic cannot be represented safely at precision 34."
        ) from exc


@dataclass(frozen=True, slots=True)
class LeverageAssessment(_AssessmentBase):
    requested_leverage: Decimal | None
    maximum_permitted_leverage: Decimal | None
    effective_leverage: Decimal | None
    post_trade_portfolio_leverage: Decimal | None
    margin_mode: MarginMode
    initial_margin: MoneyValue | None
    maintenance_margin: MoneyValue | None
    proposed_margin: MoneyValue | None
    post_trade_free_margin: MoneyValue | None
    exchange_constraints: VersionReference | None
    limits: tuple[RiskLimitResult, ...]
    contract_id: str = field(default="C-076", init=False)

    def __post_init__(self) -> None:
        _AssessmentBase.__post_init__(self)
        if not isinstance(self.margin_mode, MarginMode):
            raise RiskContractError("margin_mode must be a MarginMode.")
        for name in (
            "requested_leverage",
            "maximum_permitted_leverage",
            "effective_leverage",
            "post_trade_portfolio_leverage",
        ):
            value = getattr(self, name)
            if value is not None:
                _positive(name, value)
        for name in (
            "initial_margin",
            "maintenance_margin",
            "proposed_margin",
            "post_trade_free_margin",
        ):
            value = getattr(self, name)
            if value is not None:
                _money(name, value)
        if self.exchange_constraints is not None and not isinstance(
            self.exchange_constraints, VersionReference
        ):
            raise RiskContractError("exchange_constraints must be a VersionReference.")
        limits = _limits("limits", self.limits)
        if _hard_failure(limits) and self.outcome is not RiskCheckOutcome.FAILED:
            raise RiskContractError("hard leverage breach requires FAILED outcome.")
        if self.outcome is RiskCheckOutcome.PASSED:
            if any(
                value is None
                for value in (
                    self.requested_leverage,
                    self.maximum_permitted_leverage,
                    self.effective_leverage,
                    self.post_trade_portfolio_leverage,
                    self.initial_margin,
                    self.maintenance_margin,
                    self.proposed_margin,
                    self.post_trade_free_margin,
                    self.exchange_constraints,
                )
            ):
                raise RiskContractError(
                    "passed leverage assessment requires complete data."
                )
            assert self.requested_leverage is not None
            assert self.maximum_permitted_leverage is not None
            if self.requested_leverage > self.maximum_permitted_leverage:
                raise RiskContractError(
                    "requested leverage exceeds permitted leverage."
                )
            if _hard_failure(limits):
                raise RiskContractError("passed leverage cannot contain a hard breach.")


@dataclass(frozen=True, slots=True)
class LiquidationAssessment(_AssessmentBase):
    availability: LiquidationAvailability
    margin_mode: MarginMode
    entry_price: PriceValue
    stop_loss: PriceValue
    liquidation_price: PriceValue | None
    entry_to_liquidation: RatioValue | None
    stop_to_liquidation: RatioValue | None
    minimum_distance: RatioValue
    volatility_relationship: str
    stress_relationship: str
    formula_version: VersionReference | None
    exchange_constraints: VersionReference | None
    contract_id: str = field(default="C-077", init=False)

    def __post_init__(self) -> None:
        _AssessmentBase.__post_init__(self)
        if not isinstance(self.availability, LiquidationAvailability):
            raise RiskContractError("availability must be LiquidationAvailability.")
        if not isinstance(self.margin_mode, MarginMode):
            raise RiskContractError("margin_mode must be a MarginMode.")
        for name in ("entry_price", "stop_loss"):
            if not isinstance(getattr(self, name), PriceValue):
                raise RiskContractError(f"{name} must be a PriceValue.")
        if self.liquidation_price is not None and not isinstance(
            self.liquidation_price, PriceValue
        ):
            raise RiskContractError("liquidation_price must be a PriceValue.")
        for name in ("entry_to_liquidation", "stop_to_liquidation"):
            value = getattr(self, name)
            if value is not None and not isinstance(value, RatioValue):
                raise RiskContractError(f"{name} must be a RatioValue.")
        if not isinstance(self.minimum_distance, RatioValue):
            raise RiskContractError("minimum_distance must be a RatioValue.")
        _text("volatility_relationship", self.volatility_relationship)
        _text("stress_relationship", self.stress_relationship)
        for name in ("formula_version", "exchange_constraints"):
            value = getattr(self, name)
            if value is not None and not isinstance(value, VersionReference):
                raise RiskContractError(f"{name} must be a VersionReference.")
        available_values = (
            self.liquidation_price,
            self.entry_to_liquidation,
            self.stop_to_liquidation,
            self.formula_version,
            self.exchange_constraints,
        )
        if self.availability is LiquidationAvailability.AVAILABLE:
            if any(value is None for value in available_values):
                raise RiskContractError(
                    "available liquidation requires complete evidence."
                )
        elif any(value is not None for value in available_values[:3]):
            raise RiskContractError(
                "unavailable liquidation cannot carry estimated values."
            )
        if self.outcome is RiskCheckOutcome.PASSED:
            if self.availability is not LiquidationAvailability.AVAILABLE:
                raise RiskContractError("passed liquidation must be available.")
            assert self.entry_to_liquidation is not None
            if self.entry_to_liquidation.value < self.minimum_distance.value:
                raise RiskContractError("liquidation distance is below minimum.")


@dataclass(frozen=True, slots=True)
class StopLossAssessment(_AssessmentBase):
    side: PositionSide
    entry_price: PriceValue
    stop_loss: PriceValue | None
    stop_distance: Decimal | None
    stop_distance_ratio: RatioValue | None
    maximum_loss: MoneyValue | None
    cost_assumptions: tuple[VersionReference, ...]
    strategy_invalidation: ContractReference
    structural_check: RiskCheckOutcome
    volatility_check: RiskCheckOutcome
    liquidation_check: RiskCheckOutcome
    limits: tuple[RiskLimitResult, ...]
    contract_id: str = field(default="C-078", init=False)

    def __post_init__(self) -> None:
        _AssessmentBase.__post_init__(self)
        if not isinstance(self.side, PositionSide):
            raise RiskContractError("side must be a PositionSide.")
        if not isinstance(self.entry_price, PriceValue):
            raise RiskContractError("entry_price must be a PriceValue.")
        if self.stop_loss is not None and not isinstance(self.stop_loss, PriceValue):
            raise RiskContractError("stop_loss must be a PriceValue.")
        if self.stop_distance is not None:
            _positive("stop_distance", self.stop_distance)
        if self.stop_distance_ratio is not None and not isinstance(
            self.stop_distance_ratio, RatioValue
        ):
            raise RiskContractError("stop_distance_ratio must be a RatioValue.")
        if self.maximum_loss is not None:
            _money("maximum_loss", self.maximum_loss, positive=True)
        _typed_tuple(
            "cost_assumptions", self.cost_assumptions, VersionReference, empty=False
        )
        if not isinstance(self.strategy_invalidation, ContractReference):
            raise RiskContractError(
                "strategy_invalidation must be a ContractReference."
            )
        for name in ("structural_check", "volatility_check", "liquidation_check"):
            if not isinstance(getattr(self, name), RiskCheckOutcome):
                raise RiskContractError(f"{name} must be a RiskCheckOutcome.")
        limits = _limits("limits", self.limits)
        if _hard_failure(limits) and self.outcome is not RiskCheckOutcome.FAILED:
            raise RiskContractError("hard stop breach requires FAILED outcome.")
        if self.stop_loss is not None:
            if (
                self.side is PositionSide.LONG
                and self.stop_loss.amount >= self.entry_price.amount
            ):
                raise RiskContractError("LONG stop_loss must be below entry.")
            if (
                self.side is PositionSide.SHORT
                and self.stop_loss.amount <= self.entry_price.amount
            ):
                raise RiskContractError("SHORT stop_loss must be above entry.")
        if self.outcome is RiskCheckOutcome.PASSED:
            if any(
                value is None
                for value in (
                    self.stop_loss,
                    self.stop_distance,
                    self.stop_distance_ratio,
                    self.maximum_loss,
                )
            ):
                raise RiskContractError(
                    "passed stop assessment requires complete evidence."
                )
            if any(
                getattr(self, name) is not RiskCheckOutcome.PASSED
                for name in (
                    "structural_check",
                    "volatility_check",
                    "liquidation_check",
                )
            ) or _hard_failure(limits):
                raise RiskContractError(
                    "passed stop assessment cannot contain failures."
                )


def _stop_assessment_result(
    request: StopLossAssessmentRequest,
    *,
    outcome: RiskCheckOutcome,
    reason_codes: tuple[str, ...],
    valid_until: datetime,
    stop_loss: PriceValue | None,
    stop_distance: Decimal | None,
    stop_distance_ratio: RatioValue | None,
    maximum_loss: MoneyValue | None,
    structural_check: RiskCheckOutcome,
    volatility_check: RiskCheckOutcome,
    liquidation_check: RiskCheckOutcome,
    limits: tuple[RiskLimitResult, ...],
) -> StopLossAssessment:
    result_fields: dict[str, object] = {
        "result_id": request.result_id,
        "context": request.context,
        "outcome": outcome,
        "reason_codes": reason_codes,
        "model_version": request.model_version,
        "as_of": request.context.as_of,
        "evaluated_at": request.evaluated_at,
        "valid_until": valid_until,
        "side": request.context.side,
        "entry_price": request.entry_price,
        "stop_loss": stop_loss,
        "stop_distance": stop_distance,
        "stop_distance_ratio": stop_distance_ratio,
        "maximum_loss": maximum_loss,
        "cost_assumptions": (request.costs.version, request.gap_version),
        "strategy_invalidation": request.strategy_invalidation,
        "structural_check": structural_check,
        "volatility_check": volatility_check,
        "liquidation_check": liquidation_check,
        "limits": limits,
        "contract_id": "C-078",
        "schema_version": CONTRACT_SCHEMA_VERSION,
    }
    digest = _risk_digest(
        "stop assessment",
        {"request": request, "result": result_fields},
    )
    assessment_fields = {
        key: value
        for key, value in result_fields.items()
        if key not in {"contract_id", "schema_version"}
    }
    return StopLossAssessment(
        **{
            **assessment_fields,
            "content_sha256": digest,
        }  # type: ignore[arg-type]
    )


def _stop_reference_status(
    reference: ContractReference,
    expected_contract_id: str,
    evaluated_at: datetime,
) -> tuple[RiskCheckOutcome | None, str | None]:
    if reference.contract_id != expected_contract_id:
        return RiskCheckOutcome.FAILED, "REFERENCE_CONTRACT_MISMATCH"
    if (
        reference.schema_version != CONTRACT_SCHEMA_VERSION
        or reference.content_sha256 is None
        or reference.valid_until is None
    ):
        return RiskCheckOutcome.INSUFFICIENT_DATA, "REFERENCE_PROVENANCE_INCOMPLETE"
    if reference.valid_until < evaluated_at:
        return RiskCheckOutcome.INSUFFICIENT_DATA, "REFERENCE_EXPIRED"
    return None, None


def _stop_evidence_matches(
    context: RiskContext,
    asset: str,
    instrument_id: str,
    side: PositionSide,
    request: StopLossAssessmentRequest,
) -> bool:
    return (
        context == request.context
        and asset == request.context.asset
        and instrument_id == request.context.instrument_id
        and side is request.context.side
    )


def _calculate_stop_loss_assessment(
    request: StopLossAssessmentRequest,
) -> StopLossAssessment:
    if not isinstance(request, StopLossAssessmentRequest):
        raise RiskContractError("request must be a StopLossAssessmentRequest.")

    reasons: list[str] = []
    hard_failure = False
    missing_data = False
    incomplete_expiry = False

    def fail(code: str) -> None:
        nonlocal hard_failure
        hard_failure = True
        reasons.append(code)

    def insufficient(code: str) -> None:
        nonlocal incomplete_expiry, missing_data
        missing_data = True
        incomplete_expiry = True
        reasons.append(code)

    evaluated_at = request.evaluated_at
    expiries = [request.assumptions_valid_until]
    context_references = (
        (request.context.signal, "C-070"),
        (request.context.validation, "C-028"),
        (request.context.strategy_version, "C-021"),
        (request.context.account_snapshot, "C-032"),
        (request.context.portfolio_snapshot, "C-033"),
        (request.strategy_invalidation, "C-023"),
    )
    for reference, contract_id in context_references:
        status, code = _stop_reference_status(reference, contract_id, evaluated_at)
        if status is not None:
            if status is RiskCheckOutcome.FAILED:
                fail(code or "REFERENCE_CONTRACT_MISMATCH")
            else:
                insufficient(code or "REFERENCE_PROVENANCE_INCOMPLETE")
        if reference.valid_until is not None:
            expiries.append(reference.valid_until)

    account, portfolio = request.account, request.portfolio
    if portfolio.account_snapshot != account:
        fail("ACCOUNT_PORTFOLIO_MISMATCH")
    if (
        portfolio.equity != account.equity
        or portfolio.currency != account.currency
        or portfolio.account_snapshot.account_id != account.account_id
    ):
        fail("PORTFOLIO_EQUITY_OR_CURRENCY_MISMATCH")
    for snapshot, reference in (
        (account, request.context.account_snapshot),
        (portfolio, request.context.portfolio_snapshot),
    ):
        if (
            reference.entity_id != snapshot.snapshot_id
            or reference.schema_version != snapshot.schema_version
            or reference.content_sha256 != snapshot.content_sha256
            or reference.valid_until != snapshot.valid_until
        ):
            fail("SNAPSHOT_REFERENCE_MISMATCH")
    if request.account_source_version != account.source_version:
        fail("ACCOUNT_SOURCE_VERSION_MISMATCH")
    if request.portfolio_source_version != portfolio.source_version:
        fail("PORTFOLIO_SOURCE_VERSION_MISMATCH")
    snapshots: tuple[
        AccountSnapshot | PortfolioSnapshot | PositionSnapshot, ...
    ] = (account, portfolio, *portfolio.positions)
    if any(item.state is not SnapshotState.VALID for item in snapshots):
        insufficient("SNAPSHOT_NOT_VALID")
    if any(
        item.as_of > evaluated_at
        or item.captured_at > evaluated_at
        or item.valid_until < evaluated_at
        for item in snapshots
    ):
        insufficient("SNAPSHOT_NOT_CURRENT")
    expiries.extend(item.valid_until for item in snapshots)
    if (
        request.assumptions_as_of > evaluated_at
        or request.assumptions_valid_until < evaluated_at
    ):
        insufficient("ASSUMPTIONS_NOT_CURRENT")

    instrument, costs = request.instrument, request.costs
    currency = instrument.quote_currency
    price_units_valid = (
        request.entry_price.quote_currency == currency
        and (
            request.stop_loss is None
            or request.stop_loss.quote_currency == currency
        )
    )
    cost_units_valid = all(
        value.currency == currency for value in (costs.fee, costs.slippage, costs.funding)
    )
    budget_currency_valid = request.effective_maximum_loss.currency == currency
    instrument_lineage_valid = (
        instrument.asset == request.context.asset
        and instrument.instrument_id == request.context.instrument_id
        and instrument.model == "LINEAR"
    )
    if instrument.asset != request.context.asset:
        fail("INSTRUMENT_ASSET_MISMATCH")
    if instrument.instrument_id != request.context.instrument_id:
        fail("INSTRUMENT_ID_MISMATCH")
    if instrument.model != "LINEAR":
        fail("UNSUPPORTED_INSTRUMENT_MODEL")
    if account.currency != currency or portfolio.currency != currency:
        fail("ACCOUNT_INSTRUMENT_CURRENCY_MISMATCH")
    money_units_valid = (
        account.currency == currency and portfolio.currency == currency
    )
    if request.entry_price.quote_currency != currency:
        fail("ENTRY_CURRENCY_MISMATCH")
    if request.effective_maximum_loss.currency != currency:
        fail("BUDGET_CURRENCY_MISMATCH")
    if costs.fee.currency != currency or costs.slippage.currency != currency:
        fail("COST_CURRENCY_MISMATCH")
    if costs.funding.currency != currency:
        fail("FUNDING_CURRENCY_MISMATCH")
    if any(
        value.amount < 0
        for value in (costs.fee, costs.slippage, costs.funding)
    ):
        fail("NEGATIVE_ADVERSE_COST")
    if request.stop_loss is not None and request.stop_loss.quote_currency != currency:
        fail("STOP_CURRENCY_MISMATCH")
    if request.entry_price.amount % instrument.tick_size != 0:
        fail("ENTRY_PRICE_TICK_MISMATCH")
    if request.quantity % instrument.quantity_step != 0:
        fail("QUANTITY_STEP_MISMATCH")
    if not instrument.minimum_quantity <= request.quantity <= instrument.maximum_quantity:
        fail("QUANTITY_OUT_OF_BOUNDS")

    stop_loss = request.stop_loss
    direction_valid = False
    if stop_loss is None:
        insufficient("STOP_LOSS_MISSING")
    elif (
        request.context.side is PositionSide.LONG
        and stop_loss.amount < request.entry_price.amount
    ) or (
        request.context.side is PositionSide.SHORT
        and stop_loss.amount > request.entry_price.amount
    ):
        direction_valid = True
    else:
        fail("STOP_LOSS_DIRECTION_INVALID")
        stop_loss = None

    stop_distance: Decimal | None = None
    stop_distance_ratio: RatioValue | None = None
    maximum_loss: MoneyValue | None = None
    notional: Decimal | None = None
    if direction_valid and request.stop_loss is not None and price_units_valid:
        stop_distance = abs(request.entry_price.amount - request.stop_loss.amount)
        if request.stop_loss.amount % instrument.tick_size != 0:
            fail("STOP_PRICE_TICK_MISMATCH")
        try:
            with localcontext(
                Context(prec=34, rounding=ROUND_HALF_EVEN)
            ) as ratio_context:
                ratio_context.traps[Inexact] = False
                distance_ratio = stop_distance / request.entry_price.amount
            if distance_ratio > 1:
                stop_distance_ratio = None
                fail("STOP_DISTANCE_RATIO_UNREPRESENTABLE")
            else:
                stop_distance_ratio = RatioValue(
                    distance_ratio, "stop-distance-to-entry"
                )
            with localcontext(
                Context(prec=34, rounding=ROUND_HALF_EVEN)
            ) as exact:
                exact.traps[Inexact] = True
                if instrument_lineage_valid:
                    notional = (
                        request.entry_price.amount
                        * instrument.contract_multiplier
                        * request.quantity
                    )
                if (
                    notional is not None
                    and notional > instrument.maximum_notional.amount
                ):
                    fail("MAXIMUM_NOTIONAL_EXCEEDED")
                if instrument_lineage_valid and cost_units_valid and not any(
                    value.amount < 0
                    for value in (costs.fee, costs.slippage, costs.funding)
                ):
                    unit_loss = (
                        (
                            stop_distance + request.adverse_gap_displacement
                        )
                        * instrument.contract_multiplier
                        + costs.fee.amount
                        + costs.slippage.amount
                        + costs.funding.amount
                    )
                    loss_amount = request.quantity * unit_loss
                    maximum_loss = MoneyValue(loss_amount, currency)
        except DecimalException as exc:
            raise RiskContractError(
                "stop assessment arithmetic cannot be represented safely at "
                "precision 34."
            ) from exc

    limits: list[RiskLimitResult] = []
    if stop_distance is not None:
        policy_passed = stop_distance >= request.minimum_stop_distance
        limits.append(
            RiskLimitResult(
                "POLICY_MINIMUM_STOP_DISTANCE",
                RiskLimitSeverity.HARD,
                stop_distance,
                request.minimum_stop_distance,
                f"price:{currency}",
                RiskCheckOutcome.PASSED if policy_passed else RiskCheckOutcome.FAILED,
                "Explicit policy minimum stop distance.",
            )
        )
        if not policy_passed:
            fail("POLICY_MINIMUM_STOP_DISTANCE_BREACH")
    if maximum_loss is not None:
        if budget_currency_valid:
            budget_passed = (
                maximum_loss.amount <= request.effective_maximum_loss.amount
            )
            limits.append(
                RiskLimitResult(
                    "EFFECTIVE_MAXIMUM_LOSS",
                    RiskLimitSeverity.HARD,
                    maximum_loss.amount,
                    request.effective_maximum_loss.amount,
                    currency,
                    RiskCheckOutcome.PASSED
                    if budget_passed
                    else RiskCheckOutcome.FAILED,
                    "Caller-supplied effective maximum-loss budget.",
                )
            )
            if not budget_passed:
                fail("EFFECTIVE_MAXIMUM_LOSS_EXCEEDED")
    if notional is not None:
        limits.append(
            RiskLimitResult(
                "INSTRUMENT_MAXIMUM_NOTIONAL",
                RiskLimitSeverity.HARD,
                notional,
                instrument.maximum_notional.amount,
                currency,
                RiskCheckOutcome.PASSED
                if notional <= instrument.maximum_notional.amount
                else RiskCheckOutcome.FAILED,
                "Instrument terms maximum notional.",
            )
        )

    structural = request.structural_evidence
    structural_check = RiskCheckOutcome.INSUFFICIENT_DATA
    if structural is None:
        insufficient("STRUCTURAL_EVIDENCE_MISSING")
    else:
        expiries.append(structural.valid_until)
        status, code = _stop_reference_status(
            structural.reference, "C-023", evaluated_at
        )
        if status is not None:
            if status is RiskCheckOutcome.FAILED:
                structural_check = RiskCheckOutcome.FAILED
                fail(code or "STRUCTURAL_REFERENCE_INVALID")
            else:
                insufficient(code or "STRUCTURAL_REFERENCE_INCOMPLETE")
        elif (
            structural.reference != request.strategy_invalidation
            or structural.strategy_version != request.context.strategy_version
            or not _stop_evidence_matches(
                structural.context,
                structural.asset,
                structural.instrument_id,
                structural.side,
                request,
            )
        ):
            structural_check = RiskCheckOutcome.FAILED
            fail("STRUCTURAL_LINEAGE_MISMATCH")
        elif (
            structural.as_of > evaluated_at
            or structural.valid_until < evaluated_at
        ):
            insufficient("STRUCTURAL_EVIDENCE_NOT_CURRENT")
        elif structural.lower_stop.quote_currency != currency:
            structural_check = RiskCheckOutcome.FAILED
            fail("STRUCTURAL_INTERVAL_CURRENCY_MISMATCH")
        elif not direction_valid or request.stop_loss is None:
            insufficient("STRUCTURAL_STOP_UNAVAILABLE")
        elif not (
            structural.lower_stop.amount
            <= request.stop_loss.amount
            <= structural.upper_stop.amount
        ):
            structural_check = RiskCheckOutcome.FAILED
            fail("STOP_OUTSIDE_STRUCTURAL_INTERVAL")
        else:
            structural_check = RiskCheckOutcome.PASSED

    volatility = request.volatility_evidence
    volatility_check = RiskCheckOutcome.INSUFFICIENT_DATA
    if volatility is None:
        insufficient("VOLATILITY_EVIDENCE_MISSING")
    else:
        expiries.append(volatility.valid_until)
        if not _stop_evidence_matches(
            volatility.context,
            volatility.asset,
            volatility.instrument_id,
            volatility.side,
            request,
        ):
            volatility_check = RiskCheckOutcome.FAILED
            fail("VOLATILITY_LINEAGE_MISMATCH")
        elif (
            volatility.as_of > evaluated_at
            or volatility.valid_until < evaluated_at
        ):
            insufficient("VOLATILITY_EVIDENCE_NOT_CURRENT")
        elif volatility.quote_currency != currency:
            volatility_check = RiskCheckOutcome.FAILED
            fail("VOLATILITY_CURRENCY_MISMATCH")
        elif stop_distance is None:
            insufficient("VOLATILITY_STOP_DISTANCE_UNAVAILABLE")
        elif stop_distance < volatility.minimum_distance:
            volatility_check = RiskCheckOutcome.FAILED
            fail("VOLATILITY_MINIMUM_DISTANCE_BREACH")
        else:
            volatility_check = RiskCheckOutcome.PASSED

    liquidation = request.liquidation_evidence
    liquidation_check = RiskCheckOutcome.INSUFFICIENT_DATA
    if liquidation is None:
        insufficient("LIQUIDATION_EVIDENCE_MISSING")
    else:
        expiries.append(liquidation.valid_until)
        if not _stop_evidence_matches(
            liquidation.context,
            liquidation.asset,
            liquidation.instrument_id,
            liquidation.side,
            request,
        ):
            liquidation_check = RiskCheckOutcome.FAILED
            fail("LIQUIDATION_LINEAGE_MISMATCH")
        elif (
            liquidation.as_of > evaluated_at
            or liquidation.valid_until < evaluated_at
        ):
            insufficient("LIQUIDATION_EVIDENCE_NOT_CURRENT")
        elif liquidation.quote_currency != currency or (
            liquidation.liquidation_price is not None
            and liquidation.liquidation_price.quote_currency != currency
        ):
            liquidation_check = RiskCheckOutcome.FAILED
            fail("LIQUIDATION_CURRENCY_MISMATCH")
        elif liquidation.availability is LiquidationAvailability.NOT_APPLICABLE:
            if liquidation.fully_funded_spot:
                liquidation_check = RiskCheckOutcome.PASSED
                reasons.append("LIQUIDATION_NOT_APPLICABLE_FULLY_FUNDED_SPOT")
            else:
                liquidation_check = RiskCheckOutcome.FAILED
                fail("LIQUIDATION_NOT_APPLICABLE_WITHOUT_FUNDED_SPOT_EVIDENCE")
        elif liquidation.availability is LiquidationAvailability.UNAVAILABLE:
            insufficient("LIQUIDATION_APPLICABILITY_UNKNOWN")
        elif liquidation.liquidation_price is None:
            insufficient("LIQUIDATION_PRICE_MISSING")
        elif stop_distance is None or request.stop_loss is None:
            insufficient("LIQUIDATION_STOP_UNAVAILABLE")
        else:
            price_value = liquidation.liquidation_price.amount
            if request.context.side is PositionSide.LONG:
                beyond_stop = price_value < request.stop_loss.amount
                buffer = request.stop_loss.amount - price_value
            else:
                beyond_stop = price_value > request.stop_loss.amount
                buffer = price_value - request.stop_loss.amount
            if not beyond_stop:
                liquidation_check = RiskCheckOutcome.FAILED
                fail("LIQUIDATION_NOT_BEYOND_STOP")
            elif buffer < liquidation.minimum_buffer:
                liquidation_check = RiskCheckOutcome.FAILED
                fail("STOP_TO_LIQUIDATION_BUFFER_BREACH")
            else:
                liquidation_check = RiskCheckOutcome.PASSED

    valid_until = min(expiries)
    if hard_failure:
        outcome = RiskCheckOutcome.FAILED
    elif missing_data or any(
        check is RiskCheckOutcome.INSUFFICIENT_DATA
        for check in (structural_check, volatility_check, liquidation_check)
    ):
        outcome = RiskCheckOutcome.INSUFFICIENT_DATA
    else:
        outcome = RiskCheckOutcome.PASSED
    if incomplete_expiry or valid_until < evaluated_at:
        valid_until = evaluated_at
    if outcome is not RiskCheckOutcome.PASSED and not reasons:
        reasons.append("STOP_ASSESSMENT_INCOMPLETE")
    return _stop_assessment_result(
        request,
        outcome=outcome,
        reason_codes=tuple(dict.fromkeys(reasons)),
        valid_until=valid_until,
        stop_loss=stop_loss,
        stop_distance=stop_distance,
        stop_distance_ratio=stop_distance_ratio,
        maximum_loss=maximum_loss,
        structural_check=structural_check,
        volatility_check=volatility_check,
        liquidation_check=liquidation_check,
        limits=tuple(limits),
    )


def calculate_stop_loss_assessment(
    request: StopLossAssessmentRequest,
) -> StopLossAssessment:
    """Assess explicit stop inputs offline; this does not approve or size a trade."""
    try:
        with localcontext(
            Context(prec=34, rounding=ROUND_HALF_EVEN)
        ) as decimal_context:
            decimal_context.traps[Inexact] = True
            return _calculate_stop_loss_assessment(request)
    except DecimalException as exc:
        raise RiskContractError(
            "stop assessment arithmetic cannot be represented safely at "
            "precision 34."
        ) from exc


@dataclass(frozen=True, slots=True)
class TakeProfitAssessment(_AssessmentBase):
    side: PositionSide
    entry_price: PriceValue
    targets: tuple[TakeProfitTarget, ...]
    expected_profit: MoneyValue | None
    risk_reward_ratio: Decimal | None
    strategy_consistency: RiskCheckOutcome
    invalidation_consistency: RiskCheckOutcome
    assumptions: tuple[VersionReference, ...]
    contract_id: str = field(default="C-079", init=False)

    def __post_init__(self) -> None:
        _AssessmentBase.__post_init__(self)
        if not isinstance(self.side, PositionSide):
            raise RiskContractError("side must be a PositionSide.")
        if not isinstance(self.entry_price, PriceValue):
            raise RiskContractError("entry_price must be a PriceValue.")
        targets = _typed_tuple("targets", self.targets, TakeProfitTarget, empty=False)
        sequences = tuple(item.sequence for item in targets)
        _unique("target sequences", sequences)
        if sequences != tuple(sorted(sequences)):
            raise RiskContractError("targets must be ordered by sequence.")
        if sum((item.allocation.value for item in targets), Decimal("0")) != Decimal(
            "1"
        ):
            raise RiskContractError("target allocations must sum exactly to 1.")
        if any(
            (
                self.side is PositionSide.LONG
                and item.price.amount <= self.entry_price.amount
            )
            or (
                self.side is PositionSide.SHORT
                and item.price.amount >= self.entry_price.amount
            )
            for item in targets
        ):
            raise RiskContractError("take-profit target is on the wrong side of entry.")
        if self.expected_profit is not None:
            _money("expected_profit", self.expected_profit, positive=True)
        if self.risk_reward_ratio is not None:
            _positive("risk_reward_ratio", self.risk_reward_ratio)
        for name in ("strategy_consistency", "invalidation_consistency"):
            if not isinstance(getattr(self, name), RiskCheckOutcome):
                raise RiskContractError(f"{name} must be a RiskCheckOutcome.")
        _typed_tuple("assumptions", self.assumptions, VersionReference, empty=False)
        if self.outcome is RiskCheckOutcome.PASSED:
            if self.expected_profit is None or self.risk_reward_ratio is None:
                raise RiskContractError(
                    "passed target assessment requires backed outputs."
                )
            if self.strategy_consistency is not RiskCheckOutcome.PASSED or (
                self.invalidation_consistency is not RiskCheckOutcome.PASSED
            ):
                raise RiskContractError("passed targets require consistency checks.")


@dataclass(frozen=True, slots=True)
class PortfolioImpact(_AssessmentBase):
    sizing_result_id: UUID
    before_exposures: tuple[ExposureValue, ...]
    after_exposures: tuple[ExposureValue, ...]
    before_margin_utilization: RatioValue | None
    after_margin_utilization: RatioValue | None
    before_free_margin_buffer: RatioValue | None
    after_free_margin_buffer: RatioValue | None
    before_gross_leverage: Decimal | None
    after_gross_leverage: Decimal | None
    before_drawdown: RatioValue | None
    after_drawdown: RatioValue | None
    post_trade_risk: RatioValue | None
    remaining_risk_budget: MoneyValue | None
    limits: tuple[RiskLimitResult, ...]
    policy_version: VersionReference
    contract_id: str = field(default="C-080", init=False)

    def __post_init__(self) -> None:
        _AssessmentBase.__post_init__(self)
        _uuid("sizing_result_id", self.sizing_result_id)
        for name in ("before_exposures", "after_exposures"):
            values = _typed_tuple(name, getattr(self, name), ExposureValue, empty=False)
            _unique(name, tuple((item.dimension, item.key) for item in values))
        for name in (
            "before_margin_utilization",
            "after_margin_utilization",
            "before_free_margin_buffer",
            "after_free_margin_buffer",
            "before_drawdown",
            "after_drawdown",
            "post_trade_risk",
        ):
            value = getattr(self, name)
            if value is not None and not isinstance(value, RatioValue):
                raise RiskContractError(f"{name} must be a RatioValue.")
        for name in ("before_gross_leverage", "after_gross_leverage"):
            value = getattr(self, name)
            if value is not None:
                _nonnegative(name, value)
        if self.remaining_risk_budget is not None:
            _money("remaining_risk_budget", self.remaining_risk_budget)
        limits = _limits("limits", self.limits)
        if _hard_failure(limits) and self.outcome is not RiskCheckOutcome.FAILED:
            raise RiskContractError("hard portfolio breach requires FAILED outcome.")
        if not isinstance(self.policy_version, VersionReference):
            raise RiskContractError("policy_version must be a VersionReference.")
        if self.outcome is RiskCheckOutcome.PASSED:
            required = (
                self.before_margin_utilization,
                self.after_margin_utilization,
                self.before_free_margin_buffer,
                self.after_free_margin_buffer,
                self.before_gross_leverage,
                self.after_gross_leverage,
                self.before_drawdown,
                self.after_drawdown,
                self.post_trade_risk,
                self.remaining_risk_budget,
            )
            if any(value is None for value in required):
                raise RiskContractError(
                    "passed portfolio impact requires complete evidence."
                )
            if _hard_failure(limits):
                raise RiskContractError(
                    "passed portfolio impact cannot contain hard breach."
                )


@dataclass(frozen=True, slots=True)
class StressTestResult(_AssessmentBase):
    scenarios: tuple[StressScenarioResult, ...]
    required_scenario_types: tuple[str, ...]
    scenario_model_version: VersionReference
    cost_model_version: VersionReference
    worst_loss: MoneyValue | None
    worst_drawdown: RatioValue | None
    worst_margin: MoneyValue | None
    worst_liquidation_impact: str | None
    breached_limit_ids: tuple[str, ...]
    contract_id: str = field(default="C-081", init=False)

    def __post_init__(self) -> None:
        _AssessmentBase.__post_init__(self)
        scenarios = _typed_tuple(
            "scenarios", self.scenarios, StressScenarioResult, empty=False
        )
        _unique("scenario identities", tuple(item.scenario_id for item in scenarios))
        required = _text_tuple(
            "required_scenario_types", self.required_scenario_types, empty=False
        )
        present = {item.scenario_type for item in scenarios}
        if not set(required).issubset(present):
            raise RiskContractError("required stress scenarios are missing.")
        for name in ("scenario_model_version", "cost_model_version"):
            if not isinstance(getattr(self, name), VersionReference):
                raise RiskContractError(f"{name} must be a VersionReference.")
        for name in ("worst_loss", "worst_margin"):
            value = getattr(self, name)
            if value is not None:
                _money(name, value)
        if self.worst_drawdown is not None and not isinstance(
            self.worst_drawdown, RatioValue
        ):
            raise RiskContractError("worst_drawdown must be a RatioValue.")
        if self.worst_liquidation_impact is not None:
            _text("worst_liquidation_impact", self.worst_liquidation_impact)
        _text_tuple("breached_limit_ids", self.breached_limit_ids)
        if self.outcome is RiskCheckOutcome.PASSED:
            if any(
                value is None
                for value in (
                    self.worst_loss,
                    self.worst_drawdown,
                    self.worst_margin,
                    self.worst_liquidation_impact,
                )
            ):
                raise RiskContractError(
                    "passed stress result requires aggregate evidence."
                )
            if any(item.outcome is not RiskCheckOutcome.PASSED for item in scenarios):
                raise RiskContractError(
                    "passed stress result requires passed scenarios."
                )
            if self.breached_limit_ids:
                raise RiskContractError("passed stress result cannot contain breaches.")


@dataclass(frozen=True, slots=True)
class RiskAssessment:
    assessment_id: UUID
    context: RiskContext
    position_sizing: PositionSizingResult
    leverage: LeverageAssessment
    liquidation: LiquidationAssessment
    stop_loss: StopLossAssessment
    take_profit: TakeProfitAssessment
    portfolio_impact: PortfolioImpact
    stress_test: StressTestResult
    limits: tuple[RiskLimitResult, ...]
    warnings: tuple[str, ...]
    constraints: tuple[str, ...]
    assumptions: tuple[VersionReference, ...]
    risk_state: RiskState
    outcome: RiskCheckOutcome
    reason_codes: tuple[str, ...]
    risk_model_version: VersionReference
    policy_version: VersionReference
    as_of: datetime
    evaluated_at: datetime
    valid_until: datetime
    content_sha256: str
    contract_id: str = field(default="C-035", init=False)
    schema_version: str = field(default=CONTRACT_SCHEMA_VERSION, init=False)

    def __post_init__(self) -> None:
        _uuid("assessment_id", self.assessment_id)
        if not isinstance(self.context, RiskContext):
            raise RiskContractError("context must be a RiskContext.")
        components = (
            self.position_sizing,
            self.leverage,
            self.liquidation,
            self.stop_loss,
            self.take_profit,
            self.portfolio_impact,
            self.stress_test,
        )
        expected_types = (
            PositionSizingResult,
            LeverageAssessment,
            LiquidationAssessment,
            StopLossAssessment,
            TakeProfitAssessment,
            PortfolioImpact,
            StressTestResult,
        )
        if any(
            not isinstance(component, expected)
            for component, expected in zip(components, expected_types, strict=True)
        ):
            raise RiskContractError("risk assessment component type mismatch.")
        if any(component.context != self.context for component in components):
            raise RiskContractError("risk assessment component context mismatch.")
        if self.portfolio_impact.sizing_result_id != self.position_sizing.result_id:
            raise RiskContractError("portfolio impact sizing identity mismatch.")
        limits = _limits("limits", self.limits)
        warnings = _text_tuple("warnings", self.warnings)
        _text_tuple("constraints", self.constraints)
        _typed_tuple("assumptions", self.assumptions, VersionReference, empty=False)
        if not isinstance(self.risk_state, RiskState):
            raise RiskContractError("risk_state must be a RiskState.")
        if not isinstance(self.outcome, RiskCheckOutcome):
            raise RiskContractError("outcome must be a RiskCheckOutcome.")
        reasons = _text_tuple("reason_codes", self.reason_codes)
        if self.outcome is not RiskCheckOutcome.PASSED and not reasons:
            raise RiskContractError("non-passed risk assessment requires reason_codes.")
        for name in ("risk_model_version", "policy_version"):
            if not isinstance(getattr(self, name), VersionReference):
                raise RiskContractError(f"{name} must be a VersionReference.")
        as_of, evaluated, valid = _temporal(
            self.as_of, self.evaluated_at, self.valid_until
        )
        if self.context.as_of != as_of:
            raise RiskContractError("risk assessment context as_of mismatch.")
        if any(component.valid_until < valid for component in components):
            raise RiskContractError(
                "risk component expires before aggregate assessment."
            )
        hard_failure = _hard_failure(limits) or any(
            component.outcome is RiskCheckOutcome.FAILED for component in components
        )
        insufficient = any(
            component.outcome is RiskCheckOutcome.INSUFFICIENT_DATA
            for component in components
        )
        if hard_failure and (
            self.outcome is not RiskCheckOutcome.FAILED
            or self.risk_state is not RiskState.REJECTED
        ):
            raise RiskContractError("hard failure requires rejected failed assessment.")
        if (
            insufficient
            and not hard_failure
            and (
                self.outcome is not RiskCheckOutcome.INSUFFICIENT_DATA
                or self.risk_state is not RiskState.INSUFFICIENT_DATA
            )
        ):
            raise RiskContractError(
                "unknown evidence requires insufficient-data state."
            )
        if self.outcome is RiskCheckOutcome.PASSED:
            if any(
                component.outcome is not RiskCheckOutcome.PASSED
                for component in components
            ):
                raise RiskContractError("passed assessment requires passed components.")
            if _hard_failure(limits):
                raise RiskContractError("passed assessment cannot contain hard breach.")
            if self.risk_state in {
                RiskState.HIGH_RISK,
                RiskState.EXTREME_RISK,
                RiskState.REJECTED,
                RiskState.PAUSED,
                RiskState.INSUFFICIENT_DATA,
            }:
                raise RiskContractError("passed assessment contradicts risk state.")
            if warnings:
                raise RiskContractError("passed assessment cannot contain warnings.")
        if self.outcome is RiskCheckOutcome.WARNING and not warnings:
            raise RiskContractError("warning assessment requires warnings.")
        _digest("content_sha256", self.content_sha256)
        object.__setattr__(self, "as_of", as_of)
        object.__setattr__(self, "evaluated_at", evaluated)
        object.__setattr__(self, "valid_until", valid)


@dataclass(frozen=True, slots=True)
class RiskDecision:
    decision_id: UUID
    proposal_id: UUID
    assessment: RiskAssessment
    verdict: RiskVerdict
    risk_state: RiskState
    hard_breach_ids: tuple[str, ...]
    soft_warning_ids: tuple[str, ...]
    reason_codes: tuple[str, ...]
    risk_model_version: VersionReference
    policy_version: VersionReference
    as_of: datetime
    decided_at: datetime
    valid_until: datetime
    execution_authorized: bool = field(default=False, init=False)
    contract_id: str = field(default="C-082", init=False)
    schema_version: str = field(default=CONTRACT_SCHEMA_VERSION, init=False)

    def __post_init__(self) -> None:
        _uuid("decision_id", self.decision_id)
        _uuid("proposal_id", self.proposal_id)
        if not isinstance(self.assessment, RiskAssessment):
            raise RiskContractError("assessment must be a RiskAssessment.")
        if not isinstance(self.verdict, RiskVerdict):
            raise RiskContractError("verdict must be a RiskVerdict.")
        if not isinstance(self.risk_state, RiskState):
            raise RiskContractError("risk_state must be a RiskState.")
        hard = _text_tuple("hard_breach_ids", self.hard_breach_ids)
        soft = _text_tuple("soft_warning_ids", self.soft_warning_ids)
        reasons = _text_tuple("reason_codes", self.reason_codes)
        for name in ("risk_model_version", "policy_version"):
            value = getattr(self, name)
            if not isinstance(value, VersionReference):
                raise RiskContractError(f"{name} must be a VersionReference.")
        if self.risk_model_version != self.assessment.risk_model_version or (
            self.policy_version != self.assessment.policy_version
        ):
            raise RiskContractError("decision model/policy version mismatch.")
        as_of, decided, valid = _temporal(self.as_of, self.decided_at, self.valid_until)
        if self.assessment.as_of != as_of or self.assessment.valid_until < valid:
            raise RiskContractError("decision assessment time mismatch.")
        if self.risk_state != self.assessment.risk_state:
            raise RiskContractError("decision risk state mismatch.")
        if self.verdict is RiskVerdict.PASS:
            if self.assessment.outcome is not RiskCheckOutcome.PASSED or hard or soft:
                raise RiskContractError("PASS requires clean passed assessment.")
        elif self.verdict is RiskVerdict.PASS_WITH_WARNING:
            if (
                self.assessment.outcome
                not in {
                    RiskCheckOutcome.PASSED,
                    RiskCheckOutcome.WARNING,
                }
                or hard
                or not soft
            ):
                raise RiskContractError(
                    "PASS_WITH_WARNING requires warnings and no hard breach."
                )
        elif self.verdict is RiskVerdict.REJECT:
            if self.assessment.outcome is not RiskCheckOutcome.FAILED or not hard:
                raise RiskContractError(
                    "REJECT requires failed assessment and hard breach."
                )
        elif self.verdict is RiskVerdict.INSUFFICIENT_DATA:
            if self.assessment.outcome is not RiskCheckOutcome.INSUFFICIENT_DATA:
                raise RiskContractError(
                    "INSUFFICIENT_DATA requires insufficient assessment."
                )
        elif self.verdict is RiskVerdict.REQUIRES_HUMAN_REVIEW:
            if hard or self.assessment.outcome not in {
                RiskCheckOutcome.PASSED,
                RiskCheckOutcome.WARNING,
            }:
                raise RiskContractError(
                    "REQUIRES_HUMAN_REVIEW requires no hard breach."
                )
        if self.verdict is not RiskVerdict.PASS and not reasons:
            raise RiskContractError("non-pass decision requires reason_codes.")
        object.__setattr__(self, "as_of", as_of)
        object.__setattr__(self, "decided_at", decided)
        object.__setattr__(self, "valid_until", valid)


@dataclass(frozen=True, slots=True)
class RiskProposal:
    proposal_id: UUID
    revision: int
    supersedes_proposal_id: UUID | None
    context: RiskContext
    evidence_package: ContractReference
    entry_price: PriceValue
    stop_loss: PriceValue
    take_profit_targets: tuple[TakeProfitTarget, ...]
    position_size: Decimal
    notional_value: MoneyValue
    position_sizing: PositionSizingResult
    margin_required: MoneyValue
    leverage: Decimal
    margin_mode: MarginMode
    maximum_loss: MoneyValue
    expected_profit: MoneyValue | None
    risk_reward_ratio: Decimal | None
    account_risk: RatioValue
    portfolio_risk: RatioValue
    liquidation: LiquidationAssessment
    portfolio_impact: PortfolioImpact
    stress_test: StressTestResult
    assessment: RiskAssessment
    decision: RiskDecision
    warnings: tuple[str, ...]
    constraints: tuple[str, ...]
    assumptions: tuple[VersionReference, ...]
    human_modifiable_fields: tuple[str, ...]
    risk_model_version: VersionReference
    policy_version: VersionReference
    configuration_version: VersionReference
    as_of: datetime
    created_at: datetime
    expires_at: datetime
    content_sha256: str
    executable: bool = field(default=False, init=False)
    approved: bool = field(default=False, init=False)
    contract_id: str = field(default="C-034", init=False)
    schema_version: str = field(default=CONTRACT_SCHEMA_VERSION, init=False)

    def __post_init__(self) -> None:
        _uuid("proposal_id", self.proposal_id)
        _positive_int("revision", self.revision)
        if self.supersedes_proposal_id is not None:
            _uuid("supersedes_proposal_id", self.supersedes_proposal_id)
            if self.supersedes_proposal_id == self.proposal_id:
                raise RiskContractError("proposal cannot supersede itself.")
        if self.revision == 1 and self.supersedes_proposal_id is not None:
            raise RiskContractError("revision 1 cannot supersede another proposal.")
        if self.revision > 1 and self.supersedes_proposal_id is None:
            raise RiskContractError(
                "later revision requires superseded proposal identity."
            )
        if not isinstance(self.context, RiskContext):
            raise RiskContractError("context must be a RiskContext.")
        if (
            not isinstance(self.evidence_package, ContractReference)
            or self.evidence_package.contract_id != "C-024"
        ):
            raise RiskContractError("evidence_package must reference C-024.")
        for name in ("entry_price", "stop_loss"):
            if not isinstance(getattr(self, name), PriceValue):
                raise RiskContractError(f"{name} must be a PriceValue.")
        targets = _typed_tuple(
            "take_profit_targets",
            self.take_profit_targets,
            TakeProfitTarget,
            empty=False,
        )
        if sum((item.allocation.value for item in targets), Decimal("0")) != Decimal(
            "1"
        ):
            raise RiskContractError(
                "proposal target allocations must sum exactly to 1."
            )
        _positive("position_size", self.position_size)
        _money("notional_value", self.notional_value, positive=True)
        if not isinstance(self.position_sizing, PositionSizingResult):
            raise RiskContractError("position_sizing must be PositionSizingResult.")
        _money("margin_required", self.margin_required, positive=True)
        _positive("leverage", self.leverage)
        if not isinstance(self.margin_mode, MarginMode):
            raise RiskContractError("margin_mode must be a MarginMode.")
        _money("maximum_loss", self.maximum_loss, positive=True)
        if self.expected_profit is not None:
            _money("expected_profit", self.expected_profit, positive=True)
        if self.risk_reward_ratio is not None:
            _positive("risk_reward_ratio", self.risk_reward_ratio)
        for name in ("account_risk", "portfolio_risk"):
            if not isinstance(getattr(self, name), RatioValue):
                raise RiskContractError(f"{name} must be a RatioValue.")
        nested = (self.liquidation, self.portfolio_impact, self.stress_test)
        if (
            not isinstance(self.liquidation, LiquidationAssessment)
            or not isinstance(self.portfolio_impact, PortfolioImpact)
            or not isinstance(self.stress_test, StressTestResult)
        ):
            raise RiskContractError("proposal risk component type mismatch.")
        if not isinstance(self.assessment, RiskAssessment):
            raise RiskContractError("assessment must be a RiskAssessment.")
        if not isinstance(self.decision, RiskDecision):
            raise RiskContractError("decision must be a RiskDecision.")
        if self.decision.proposal_id != self.proposal_id:
            raise RiskContractError("decision proposal identity mismatch.")
        if (
            self.position_sizing != self.assessment.position_sizing
            or any(component.context != self.context for component in nested)
            or self.assessment.context != self.context
        ):
            raise RiskContractError("proposal component context mismatch.")
        if (
            self.liquidation != self.assessment.liquidation
            or (self.portfolio_impact != self.assessment.portfolio_impact)
            or self.stress_test != self.assessment.stress_test
        ):
            raise RiskContractError("proposal components differ from assessment.")
        if self.decision.assessment != self.assessment:
            raise RiskContractError("proposal decision assessment mismatch.")
        currencies = {
            self.entry_price.quote_currency,
            self.stop_loss.quote_currency,
            self.notional_value.currency,
            self.margin_required.currency,
            self.maximum_loss.currency,
            *(item.price.quote_currency for item in targets),
        }
        if self.expected_profit is not None:
            currencies.add(self.expected_profit.currency)
        if len(currencies) > 1:
            raise RiskContractError("proposal price/money currencies must match.")
        if (
            self.assessment.stop_loss.side is not self.context.side
            or self.assessment.take_profit.side is not self.context.side
        ):
            raise RiskContractError("proposal direction differs from risk context.")
        if (
            self.entry_price != self.assessment.stop_loss.entry_price
            or self.entry_price != self.assessment.take_profit.entry_price
            or self.entry_price != self.liquidation.entry_price
            or self.stop_loss != self.assessment.stop_loss.stop_loss
            or self.stop_loss != self.liquidation.stop_loss
            or targets != self.assessment.take_profit.targets
        ):
            raise RiskContractError("proposal price/target evidence mismatch.")
        if (
            self.position_size != self.position_sizing.recommended_quantity
            or self.notional_value != self.position_sizing.recommended_notional
            or self.margin_required != self.position_sizing.recommended_margin
            or self.maximum_loss != self.position_sizing.maximum_loss
            or self.account_risk != self.position_sizing.account_risk
        ):
            raise RiskContractError("proposal sizing evidence mismatch.")
        if (
            self.leverage != self.assessment.leverage.requested_leverage
            or self.margin_mode is not self.assessment.leverage.margin_mode
            or self.margin_required != self.assessment.leverage.proposed_margin
        ):
            raise RiskContractError("proposal leverage evidence mismatch.")
        if (
            self.expected_profit != self.assessment.take_profit.expected_profit
            or self.risk_reward_ratio != self.assessment.take_profit.risk_reward_ratio
            or self.portfolio_risk != self.portfolio_impact.post_trade_risk
        ):
            raise RiskContractError("proposal risk/reward evidence mismatch.")
        _text_tuple("warnings", self.warnings)
        _text_tuple("constraints", self.constraints)
        _typed_tuple("assumptions", self.assumptions, VersionReference, empty=False)
        _text_tuple(
            "human_modifiable_fields", self.human_modifiable_fields, empty=False
        )
        for name in (
            "risk_model_version",
            "policy_version",
            "configuration_version",
        ):
            if not isinstance(getattr(self, name), VersionReference):
                raise RiskContractError(f"{name} must be a VersionReference.")
        if self.risk_model_version != self.assessment.risk_model_version or (
            self.policy_version != self.assessment.policy_version
        ):
            raise RiskContractError("proposal model/policy version mismatch.")
        as_of = _time("as_of", self.as_of)
        created = _time("created_at", self.created_at)
        expires = _time("expires_at", self.expires_at)
        _ordered("as_of", as_of, "created_at", created)
        _ordered("created_at", created, "expires_at", expires)
        if (
            self.context.as_of != as_of
            or self.assessment.valid_until < expires
            or (self.decision.valid_until < expires)
        ):
            raise RiskContractError("proposal evidence expires before proposal.")
        _digest("content_sha256", self.content_sha256)
        object.__setattr__(self, "as_of", as_of)
        object.__setattr__(self, "created_at", created)
        object.__setattr__(self, "expires_at", expires)


@dataclass(frozen=True, slots=True)
class RiskRevalidationResult:
    result_id: UUID
    original_proposal: RiskProposal
    replacement_proposal: RiskProposal
    triggers: tuple[RevalidationTrigger, ...]
    changed_fields: tuple[str, ...]
    market_snapshot: ContractReference
    risk_model_version: VersionReference
    policy_version: VersionReference
    replacement_assessment: RiskAssessment
    replacement_decision: RiskDecision
    status: RevalidationStatus
    reason_codes: tuple[str, ...]
    as_of: datetime
    revalidated_at: datetime
    valid_until: datetime
    content_sha256: str
    execution_authorized: bool = field(default=False, init=False)
    contract_id: str = field(default="C-083", init=False)
    schema_version: str = field(default=CONTRACT_SCHEMA_VERSION, init=False)

    def __post_init__(self) -> None:
        _uuid("result_id", self.result_id)
        if not isinstance(self.original_proposal, RiskProposal) or not isinstance(
            self.replacement_proposal, RiskProposal
        ):
            raise RiskContractError("revalidation requires RiskProposal objects.")
        original = self.original_proposal
        replacement = self.replacement_proposal
        if replacement.proposal_id == original.proposal_id or (
            replacement.supersedes_proposal_id != original.proposal_id
        ):
            raise RiskContractError("replacement must supersede a distinct proposal.")
        if replacement.revision <= original.revision:
            raise RiskContractError("replacement revision must increase.")
        triggers = _typed_tuple(
            "triggers", self.triggers, RevalidationTrigger, empty=False
        )
        _unique("triggers", triggers)
        _text_tuple("changed_fields", self.changed_fields, empty=False)
        if (
            not isinstance(self.market_snapshot, ContractReference)
            or self.market_snapshot.contract_id != "C-002"
        ):
            raise RiskContractError("market_snapshot must reference C-002.")
        for name in ("risk_model_version", "policy_version"):
            if not isinstance(getattr(self, name), VersionReference):
                raise RiskContractError(f"{name} must be a VersionReference.")
        if self.risk_model_version != replacement.risk_model_version or (
            self.policy_version != replacement.policy_version
        ):
            raise RiskContractError("revalidation model/policy version mismatch.")
        if self.replacement_assessment != replacement.assessment or (
            self.replacement_decision != replacement.decision
        ):
            raise RiskContractError("replacement evidence mismatch.")
        if not isinstance(self.status, RevalidationStatus):
            raise RiskContractError("status must be a RevalidationStatus.")
        reasons = _text_tuple("reason_codes", self.reason_codes)
        if self.status is not RevalidationStatus.PASSED and not reasons:
            raise RiskContractError("non-passed revalidation requires reason_codes.")
        as_of, revalidated, valid = _temporal(
            self.as_of, self.revalidated_at, self.valid_until
        )
        if replacement.as_of != as_of or replacement.expires_at < valid:
            raise RiskContractError("replacement proposal expires before revalidation.")
        if (
            self.status is RevalidationStatus.PASSED
            and replacement.decision.verdict
            in {
                RiskVerdict.REJECT,
                RiskVerdict.INSUFFICIENT_DATA,
            }
        ):
            raise RiskContractError(
                "passed revalidation requires acceptable risk decision."
            )
        _digest("content_sha256", self.content_sha256)
        object.__setattr__(self, "as_of", as_of)
        object.__setattr__(self, "revalidated_at", revalidated)
        object.__setattr__(self, "valid_until", valid)


@dataclass(frozen=True, slots=True)
class PositionExposureInput:
    """Explicit position snapshot and caller-supplied venue identity."""

    position: PositionSnapshot
    venue: str

    def __post_init__(self) -> None:
        if not isinstance(self.position, PositionSnapshot):
            raise RiskContractError("position must be a PositionSnapshot.")
        _text("venue", self.venue)


@dataclass(frozen=True, slots=True)
class ExposureBreakdown:
    """Gross long/short and signed net for one dimension and currency."""

    dimension: str
    key: str
    currency: str
    gross_long: Decimal
    gross_short: Decimal
    net: Decimal
    gross: Decimal

    def __post_init__(self) -> None:
        for name in ("dimension", "key", "currency"):
            _text(name, getattr(self, name))
        for name in ("gross_long", "gross_short", "net", "gross"):
            _decimal(name, getattr(self, name))
        if self.gross_long < 0 or self.gross_short < 0 or self.gross < 0:
            raise RiskContractError("gross exposure values must be non-negative.")
        with localcontext() as decimal_context:
            decimal_context.prec = 34
            decimal_context.rounding = ROUND_HALF_EVEN
            if self.net != self.gross_long - self.gross_short:
                raise RiskContractError(
                    "net exposure must equal gross long minus short."
                )
            if self.gross != self.gross_long + self.gross_short:
                raise RiskContractError("gross exposure must equal long plus short.")


class ExposureConcentrationState(StrEnum):
    AVAILABLE = "AVAILABLE"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class EquityConcentration:
    """Gross notional/equity only for the account equity currency."""

    currency: str
    gross: Decimal
    state: ExposureConcentrationState
    gross_to_equity: Decimal | None
    reason: str | None

    def __post_init__(self) -> None:
        _text("currency", self.currency)
        _nonnegative("gross", self.gross)
        if not isinstance(self.state, ExposureConcentrationState):
            raise RiskContractError("state must be an ExposureConcentrationState.")
        if self.state is ExposureConcentrationState.AVAILABLE:
            if self.gross_to_equity is None or self.reason is not None:
                raise RiskContractError("available concentration requires a ratio.")
            _nonnegative("gross_to_equity", self.gross_to_equity)
        elif self.gross_to_equity is not None or not self.reason:
            raise RiskContractError(
                "unknown concentration requires an explicit reason."
            )
        if self.reason is not None:
            _text("reason", self.reason)


@dataclass(frozen=True, slots=True)
class AssetEquityConcentration:
    """Gross notional/equity for one asset and quote currency."""

    asset: str
    currency: str
    gross: Decimal
    state: ExposureConcentrationState
    gross_to_equity: Decimal | None
    reason: str | None

    def __post_init__(self) -> None:
        _text("asset", self.asset)
        _text("currency", self.currency)
        _nonnegative("gross", self.gross)
        if not isinstance(self.state, ExposureConcentrationState):
            raise RiskContractError("state must be an ExposureConcentrationState.")
        if self.state is ExposureConcentrationState.AVAILABLE:
            if self.gross_to_equity is None or self.reason is not None:
                raise RiskContractError("available concentration requires a ratio.")
            _nonnegative("gross_to_equity", self.gross_to_equity)
        elif self.gross_to_equity is not None or not self.reason:
            raise RiskContractError(
                "unknown concentration requires an explicit reason."
            )
        if self.reason is not None:
            _text("reason", self.reason)


@dataclass(frozen=True, slots=True)
class PortfolioExposureAggregation:
    """Pure, nonpersisted aggregation of the exact supplied exposure snapshots."""

    account_id: UUID
    account_snapshot_id: UUID
    evaluated_at: datetime
    position_snapshot_ids: tuple[UUID, ...]
    breakdowns: tuple[ExposureBreakdown, ...]
    concentrations: tuple[EquityConcentration, ...]
    asset_concentrations: tuple[AssetEquityConcentration, ...]
    input_digest: str

    def __post_init__(self) -> None:
        _uuid("account_id", self.account_id)
        _uuid("account_snapshot_id", self.account_snapshot_id)
        object.__setattr__(
            self, "evaluated_at", _time("evaluated_at", self.evaluated_at)
        )
        snapshot_ids = _uuid_tuple("position_snapshot_ids", self.position_snapshot_ids)
        if not snapshot_ids:
            raise RiskContractError("position_snapshot_ids must not be empty.")
        _typed_tuple("breakdowns", self.breakdowns, ExposureBreakdown, empty=False)
        _unique(
            "breakdown identities",
            tuple(
                (item.dimension, item.key, item.currency) for item in self.breakdowns
            ),
        )
        _typed_tuple(
            "concentrations", self.concentrations, EquityConcentration, empty=False
        )
        _unique(
            "concentration currencies",
            tuple(item.currency for item in self.concentrations),
        )
        _typed_tuple(
            "asset_concentrations",
            self.asset_concentrations,
            AssetEquityConcentration,
            empty=False,
        )
        _unique(
            "asset concentration identities",
            tuple((item.asset, item.currency) for item in self.asset_concentrations),
        )
        _digest("input_digest", self.input_digest)


def _risk_digest(name: str, value: object) -> str:
    try:
        return canonical_sha256(value)
    except ContractSerializationError as exc:
        raise RiskContractError(f"{name} inputs are not canonical.") from exc


def _safe_decimal(value: Decimal, name: str) -> Decimal:
    if not value.is_finite():
        raise RiskContractError(f"{name} is not finite at precision 34.")
    return value


def aggregate_portfolio_exposure(
    account_snapshot: AccountSnapshot,
    positions: tuple[PositionExposureInput, ...],
    evaluated_at: datetime,
) -> PortfolioExposureAggregation:
    """Aggregate explicit snapshots without valuation, FX, or risk decisions."""
    if not isinstance(account_snapshot, AccountSnapshot):
        raise RiskContractError("account_snapshot must be an AccountSnapshot.")
    _typed_tuple("positions", positions, PositionExposureInput, empty=False)
    evaluated = _time("evaluated_at", evaluated_at)
    _uuid("account_id", account_snapshot.account_id)
    _uuid("account_snapshot_id", account_snapshot.snapshot_id)
    equity = account_snapshot.equity
    if account_snapshot.state is not SnapshotState.VALID:
        raise RiskContractError("account snapshot must be VALID.")
    if equity is None or not isinstance(equity, MoneyValue):
        raise RiskContractError("account snapshot must have positive equity.")
    MoneyValue.__post_init__(equity)
    if equity.amount <= 0:
        raise RiskContractError("account snapshot must have positive equity.")
    account_as_of = _time("account_snapshot.as_of", account_snapshot.as_of)
    account_captured_at = _time(
        "account_snapshot.captured_at", account_snapshot.captured_at
    )
    account_valid_until = _time(
        "account_snapshot.valid_until", account_snapshot.valid_until
    )
    if account_as_of > evaluated or account_captured_at > evaluated:
        raise RiskContractError("account snapshot cannot be from the future.")
    if evaluated > account_valid_until:
        raise RiskContractError("account snapshot is stale.")

    position_ids: set[UUID] = set()
    snapshot_ids: set[UUID] = set()
    for supplied in positions:
        position = supplied.position
        _uuid("position_id", position.position_id)
        _uuid("position_snapshot_id", position.snapshot_id)
        if position.account_id != account_snapshot.account_id:
            raise RiskContractError("position account identity mismatch.")
        if position.state is not SnapshotState.VALID:
            raise RiskContractError("position snapshot must be VALID.")
        position_as_of = _time("position.as_of", position.as_of)
        position_captured_at = _time("position.captured_at", position.captured_at)
        position_valid_until = _time("position.valid_until", position.valid_until)
        if position_as_of > evaluated or position_captured_at > evaluated:
            raise RiskContractError("position snapshot cannot be from the future.")
        if evaluated > position_valid_until:
            raise RiskContractError("position snapshot is stale.")
        if not isinstance(position.side, PositionSide):
            raise RiskContractError("position side must be a PositionSide.")
        _text("position.asset", position.asset)
        _text("position.instrument_id", position.instrument_id)
        if position.notional is None or not isinstance(position.notional, MoneyValue):
            raise RiskContractError("position must have a positive priced notional.")
        MoneyValue.__post_init__(position.notional)
        if position.notional.amount <= 0:
            raise RiskContractError("position must have a positive priced notional.")
        if position.position_id in position_ids:
            raise RiskContractError("duplicate position identity.")
        if position.snapshot_id in snapshot_ids:
            raise RiskContractError("duplicate position snapshot identity.")
        position_ids.add(position.position_id)
        snapshot_ids.add(position.snapshot_id)

    # Sorting makes fixed-precision Decimal summation independent of tuple order.
    ordered_positions = tuple(
        sorted(
            positions,
            key=lambda item: (
                item.position.position_id.hex,
                item.position.snapshot_id.hex,
            ),
        )
    )
    groups: dict[tuple[str, str, str], list[Decimal]] = {}
    with localcontext() as decimal_context:
        decimal_context.prec = 34
        decimal_context.rounding = ROUND_HALF_EVEN
        for supplied in ordered_positions:
            position = supplied.position
            assert position.notional is not None
            currency = position.notional.currency
            keys = (
                ("currency", currency, currency),
                ("asset", position.asset, currency),
                ("instrument", position.instrument_id, currency),
                ("venue", supplied.venue, currency),
                ("direction", position.side.value, currency),
            )
            for group_key in keys:
                totals = groups.setdefault(group_key, [Decimal(0), Decimal(0)])
                side_index = 0 if position.side is PositionSide.LONG else 1
                totals[side_index] = _safe_decimal(
                    totals[side_index] + position.notional.amount, "gross exposure"
                )

        breakdowns: list[ExposureBreakdown] = []
        for (dimension, key, currency), (gross_long, gross_short) in sorted(
            groups.items()
        ):
            net = _safe_decimal(gross_long - gross_short, "net exposure")
            gross = _safe_decimal(gross_long + gross_short, "gross exposure")
            breakdowns.append(
                ExposureBreakdown(
                    dimension, key, currency, gross_long, gross_short, net, gross
                )
            )

        currency_totals = {
            key: values
            for (dimension, key, currency), values in groups.items()
            if dimension == "currency" and key == currency
        }
        concentrations: list[EquityConcentration] = []
        for currency, (gross_long, gross_short) in sorted(currency_totals.items()):
            gross = _safe_decimal(gross_long + gross_short, "currency gross exposure")
            if currency == equity.currency:
                concentration = _safe_decimal(gross / equity.amount, "gross/equity")
                concentrations.append(
                    EquityConcentration(
                        currency,
                        gross,
                        ExposureConcentrationState.AVAILABLE,
                        concentration,
                        None,
                    )
                )
            else:
                concentrations.append(
                    EquityConcentration(
                        currency,
                        gross,
                        ExposureConcentrationState.UNKNOWN,
                        None,
                        "FOREIGN_CURRENCY_NO_FX",
                    )
                )

        asset_totals = {
            (key, currency): values
            for (dimension, key, currency), values in groups.items()
            if dimension == "asset"
        }
        asset_concentrations: list[AssetEquityConcentration] = []
        for (asset, currency), (gross_long, gross_short) in sorted(
            asset_totals.items()
        ):
            gross = _safe_decimal(gross_long + gross_short, "asset gross exposure")
            if currency == equity.currency:
                concentration = _safe_decimal(gross / equity.amount, "gross/equity")
                asset_concentrations.append(
                    AssetEquityConcentration(
                        asset,
                        currency,
                        gross,
                        ExposureConcentrationState.AVAILABLE,
                        concentration,
                        None,
                    )
                )
            else:
                asset_concentrations.append(
                    AssetEquityConcentration(
                        asset,
                        currency,
                        gross,
                        ExposureConcentrationState.UNKNOWN,
                        None,
                        "FOREIGN_CURRENCY_NO_FX",
                    )
                )

    canonical_inputs = {
        "account_snapshot": account_snapshot,
        "positions": ordered_positions,
        "evaluated_at": evaluated,
    }
    return PortfolioExposureAggregation(
        account_snapshot.account_id,
        account_snapshot.snapshot_id,
        evaluated,
        tuple(item.position.snapshot_id for item in ordered_positions),
        tuple(breakdowns),
        tuple(concentrations),
        tuple(asset_concentrations),
        _risk_digest("portfolio exposure", canonical_inputs),
    )


@dataclass(frozen=True, slots=True)
class ReturnObservation:
    """One caller-supplied finite close-to-close log return at an exact timestamp."""

    timestamp: datetime
    log_return: Decimal

    def __post_init__(self) -> None:
        object.__setattr__(self, "timestamp", _time("timestamp", self.timestamp))
        _decimal("log_return", self.log_return)


def _return_series_digest(
    instrument_id: str,
    source_id: str,
    source_version: VersionReference,
    observations: tuple[ReturnObservation, ...],
) -> str:
    return _risk_digest(
        "return series",
        {
            "instrument_id": instrument_id,
            "source_id": source_id,
            "source_version": source_version,
            "observations": observations,
        },
    )


@dataclass(frozen=True, slots=True)
class InstrumentReturnSeries:
    """Caller-supplied immutable, source/version/digest-bound return observations."""

    instrument_id: str
    source_id: str
    source_version: VersionReference
    observations: tuple[ReturnObservation, ...]
    content_sha256: str

    def __post_init__(self) -> None:
        _text("instrument_id", self.instrument_id)
        _text("source_id", self.source_id)
        if not isinstance(self.source_version, VersionReference):
            raise RiskContractError("source_version must be a VersionReference.")
        observations = _typed_tuple(
            "observations", self.observations, ReturnObservation, empty=False
        )
        timestamps = tuple(item.timestamp for item in observations)
        if any(earlier >= later for earlier, later in zip(timestamps, timestamps[1:])):
            raise RiskContractError("return timestamps must be strictly increasing.")
        _digest("content_sha256", self.content_sha256)
        expected = _return_series_digest(
            self.instrument_id, self.source_id, self.source_version, observations
        )
        if self.content_sha256 != expected:
            raise RiskContractError("return series digest mismatch.")


class DescriptiveEstimateState(StrEnum):
    AVAILABLE = "AVAILABLE"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class DescriptiveEstimate:
    """Descriptive number or explicit unknown; never a confidence or trade signal."""

    value: Decimal | None
    state: DescriptiveEstimateState
    reason: str | None
    sample_count: int
    sample_timestamps: tuple[datetime, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.state, DescriptiveEstimateState):
            raise RiskContractError("state must be a DescriptiveEstimateState.")
        if (
            not isinstance(self.sample_count, int)
            or isinstance(self.sample_count, bool)
            or self.sample_count < 0
        ):
            raise RiskContractError("sample_count must be a non-negative integer.")
        timestamps = tuple(
            _time(f"sample_timestamps[{index}]", value)
            for index, value in enumerate(
                _tuple("sample_timestamps", self.sample_timestamps)
            )
        )
        if len(timestamps) != self.sample_count:
            raise RiskContractError("sample_count must match sample timestamps.")
        if any(earlier >= later for earlier, later in zip(timestamps, timestamps[1:])):
            raise RiskContractError("sample timestamps must be strictly increasing.")
        object.__setattr__(self, "sample_timestamps", timestamps)
        if self.state is DescriptiveEstimateState.AVAILABLE:
            if self.value is None or self.reason is not None:
                raise RiskContractError("available estimate requires a value.")
            _decimal("value", self.value)
        elif self.value is not None or self.reason is None:
            raise RiskContractError("unknown estimate requires an explicit reason.")
        else:
            _text("reason", self.reason)


@dataclass(frozen=True, slots=True)
class PairwiseCorrelation:
    instrument_left: str
    instrument_right: str
    estimate: DescriptiveEstimate

    def __post_init__(self) -> None:
        _text("instrument_left", self.instrument_left)
        _text("instrument_right", self.instrument_right)
        if self.instrument_left >= self.instrument_right:
            raise RiskContractError("pair instruments must be uniquely ordered.")
        if not isinstance(self.estimate, DescriptiveEstimate):
            raise RiskContractError("estimate must be a DescriptiveEstimate.")


@dataclass(frozen=True, slots=True)
class InstrumentBeta:
    instrument_id: str
    benchmark_instrument_id: str
    estimate: DescriptiveEstimate

    def __post_init__(self) -> None:
        _text("instrument_id", self.instrument_id)
        _text("benchmark_instrument_id", self.benchmark_instrument_id)
        if self.instrument_id == self.benchmark_instrument_id:
            raise RiskContractError("beta instrument must differ from its benchmark.")
        if not isinstance(self.estimate, DescriptiveEstimate):
            raise RiskContractError("estimate must be a DescriptiveEstimate.")


@dataclass(frozen=True, slots=True)
class ReturnSeriesProvenance:
    instrument_id: str
    source_id: str
    source_version: VersionReference
    content_sha256: str

    def __post_init__(self) -> None:
        _text("instrument_id", self.instrument_id)
        _text("source_id", self.source_id)
        if not isinstance(self.source_version, VersionReference):
            raise RiskContractError("source_version must be a VersionReference.")
        _digest("content_sha256", self.content_sha256)


@dataclass(frozen=True, slots=True)
class PairwiseCorrelationResult:
    window_start: datetime
    window_end: datetime
    min_observations: int
    benchmark_instrument_id: str | None
    series_provenance: tuple[ReturnSeriesProvenance, ...]
    input_digest: str
    correlations: tuple[PairwiseCorrelation, ...]
    betas: tuple[InstrumentBeta, ...]

    def __post_init__(self) -> None:
        start = _time("window_start", self.window_start)
        end = _time("window_end", self.window_end)
        _ordered("window_start", start, "window_end", end)
        _positive_int("min_observations", self.min_observations)
        if self.min_observations < 3:
            raise RiskContractError("min_observations must be at least three.")
        if self.benchmark_instrument_id is not None:
            _text("benchmark_instrument_id", self.benchmark_instrument_id)
        provenance = _typed_tuple(
            "series_provenance",
            self.series_provenance,
            ReturnSeriesProvenance,
            empty=False,
        )
        _unique(
            "series provenance instruments", tuple(x.instrument_id for x in provenance)
        )
        _digest("input_digest", self.input_digest)
        correlations = _typed_tuple(
            "correlations", self.correlations, PairwiseCorrelation
        )
        _unique(
            "correlation pairs",
            tuple((x.instrument_left, x.instrument_right) for x in correlations),
        )
        betas = _typed_tuple("betas", self.betas, InstrumentBeta)
        _unique("beta instruments", tuple(x.instrument_id for x in betas))
        object.__setattr__(self, "window_start", start)
        object.__setattr__(self, "window_end", end)


def _unknown_estimate(
    reason: str, timestamps: tuple[datetime, ...]
) -> DescriptiveEstimate:
    return DescriptiveEstimate(
        None, DescriptiveEstimateState.UNKNOWN, reason, len(timestamps), timestamps
    )


def _paired_returns(
    left: InstrumentReturnSeries,
    right: InstrumentReturnSeries,
    start: datetime,
    end: datetime,
) -> tuple[tuple[Decimal, Decimal, datetime], ...]:
    left_values = {
        item.timestamp: item.log_return
        for item in left.observations
        if start <= item.timestamp <= end
    }
    right_values = {
        item.timestamp: item.log_return
        for item in right.observations
        if start <= item.timestamp <= end
    }
    return tuple(
        (left_values[timestamp], right_values[timestamp], timestamp)
        for timestamp in sorted(left_values.keys() & right_values.keys())
    )


def _moments(
    pairs: tuple[tuple[Decimal, Decimal, datetime], ...],
) -> tuple[Decimal, Decimal, Decimal]:
    with localcontext() as decimal_context:
        decimal_context.prec = 34
        decimal_context.rounding = ROUND_HALF_EVEN
        count = Decimal(len(pairs))
        mean_left = sum((x for x, _, _ in pairs), Decimal(0)) / count
        mean_right = sum((y for _, y, _ in pairs), Decimal(0)) / count
        cross = sum(
            ((x - mean_left) * (y - mean_right) for x, y, _ in pairs), Decimal(0)
        )
        left_square = sum(((x - mean_left) ** 2 for x, _, _ in pairs), Decimal(0))
        right_square = sum(((y - mean_right) ** 2 for _, y, _ in pairs), Decimal(0))
        return (
            _safe_decimal(cross, "sample covariance numerator"),
            _safe_decimal(left_square, "sample variance numerator"),
            _safe_decimal(right_square, "sample variance numerator"),
        )


def pairwise_correlation(
    series: tuple[InstrumentReturnSeries, ...],
    *,
    window_start: datetime,
    window_end: datetime,
    min_observations: int,
    benchmark_instrument_id: str | None = None,
) -> PairwiseCorrelationResult:
    """Calculate descriptive pairwise Pearson correlation and optional beta.

    Only exact timestamp intersections in the inclusive caller-supplied window
    are used. Arithmetic is Decimal-only with precision 34 and no annualization.
    """
    supplied = _typed_tuple("series", series, InstrumentReturnSeries, empty=False)
    start = _time("window_start", window_start)
    end = _time("window_end", window_end)
    _ordered("window_start", start, "window_end", end)
    _positive_int("min_observations", min_observations)
    if min_observations < 3:
        raise RiskContractError("min_observations must be at least three.")
    if len(supplied) < 2:
        raise RiskContractError("at least two instrument series are required.")
    instrument_ids = tuple(item.instrument_id for item in supplied)
    _unique("series instruments", instrument_ids)
    if benchmark_instrument_id is not None:
        _text("benchmark_instrument_id", benchmark_instrument_id)
        if benchmark_instrument_id not in instrument_ids:
            raise RiskContractError(
                "explicit benchmark is absent from supplied series."
            )
    ordered_series = tuple(sorted(supplied, key=lambda item: item.instrument_id))
    by_instrument = {item.instrument_id: item for item in ordered_series}
    pairs: list[PairwiseCorrelation] = []
    beta_results: list[InstrumentBeta] = []
    with localcontext() as decimal_context:
        decimal_context.prec = 34
        decimal_context.rounding = ROUND_HALF_EVEN
        for left, right in combinations(ordered_series, 2):
            observations = _paired_returns(left, right, start, end)
            timestamps = tuple(item[2] for item in observations)
            if len(observations) < min_observations:
                estimate = _unknown_estimate(
                    "INSUFFICIENT_ALIGNED_OBSERVATIONS", timestamps
                )
            else:
                (
                    covariance_numerator,
                    left_variance_numerator,
                    right_variance_numerator,
                ) = _moments(observations)
                if left_variance_numerator == 0 or right_variance_numerator == 0:
                    estimate = _unknown_estimate("ZERO_VARIANCE", timestamps)
                else:
                    variance_product = _safe_decimal(
                        left_variance_numerator * right_variance_numerator,
                        "variance product",
                    )
                    denominator = _safe_decimal(
                        variance_product.sqrt(), "correlation denominator"
                    )
                    correlation = _safe_decimal(
                        covariance_numerator / denominator, "Pearson correlation"
                    )
                    if abs(correlation) > Decimal(1):
                        if abs(correlation) - Decimal(1) > Decimal("1e-32"):
                            raise RiskContractError(
                                "Pearson correlation exceeds its valid range."
                            )
                        correlation = Decimal(1) if correlation > 0 else Decimal(-1)
                    estimate = DescriptiveEstimate(
                        correlation,
                        DescriptiveEstimateState.AVAILABLE,
                        None,
                        len(timestamps),
                        timestamps,
                    )
            pairs.append(
                PairwiseCorrelation(left.instrument_id, right.instrument_id, estimate)
            )

        if benchmark_instrument_id is not None:
            benchmark = by_instrument[benchmark_instrument_id]
            for instrument in ordered_series:
                if instrument.instrument_id == benchmark_instrument_id:
                    continue
                observations = _paired_returns(instrument, benchmark, start, end)
                timestamps = tuple(item[2] for item in observations)
                if len(observations) < min_observations:
                    estimate = _unknown_estimate(
                        "INSUFFICIENT_ALIGNED_OBSERVATIONS", timestamps
                    )
                else:
                    covariance_numerator, _, benchmark_variance_numerator = _moments(
                        observations
                    )
                    if benchmark_variance_numerator == 0:
                        estimate = _unknown_estimate(
                            "ZERO_BENCHMARK_VARIANCE", timestamps
                        )
                    else:
                        estimate = DescriptiveEstimate(
                            _safe_decimal(
                                covariance_numerator / benchmark_variance_numerator,
                                "beta",
                            ),
                            DescriptiveEstimateState.AVAILABLE,
                            None,
                            len(timestamps),
                            timestamps,
                        )
                beta_results.append(
                    InstrumentBeta(
                        instrument.instrument_id,
                        benchmark_instrument_id,
                        estimate,
                    )
                )

    provenance = tuple(
        ReturnSeriesProvenance(
            item.instrument_id,
            item.source_id,
            item.source_version,
            item.content_sha256,
        )
        for item in ordered_series
    )
    input_digest = _risk_digest(
        "correlation",
        {
            "series": ordered_series,
            "window_start": start,
            "window_end": end,
            "min_observations": min_observations,
            "benchmark_instrument_id": benchmark_instrument_id,
        },
    )
    return PairwiseCorrelationResult(
        start,
        end,
        min_observations,
        benchmark_instrument_id,
        provenance,
        input_digest,
        tuple(pairs),
        tuple(beta_results),
    )


__all__ = [
    "CONTRACT_SCHEMA_VERSION",
    "AccountEvidenceContext",
    "AccountPermissionObservation",
    "AccountPermissionObservations",
    "AccountSnapshot",
    "AssetEquityConcentration",
    "AssessmentReference",
    "ContractReference",
    "DescriptiveEstimate",
    "DescriptiveEstimateState",
    "EquityConcentration",
    "ExposureBreakdown",
    "ExposureConcentrationState",
    "ExposureValue",
    "InstrumentBeta",
    "InstrumentReturnSeries",
    "LeverageAssessment",
    "LiquidationAssessment",
    "LiquidationAvailability",
    "MarginMode",
    "MoneyValue",
    "OfflineAccountAssessment",
    "OfflineAccountEvidence",
    "PairwiseCorrelation",
    "PairwiseCorrelationResult",
    "PortfolioImpact",
    "PortfolioExposureAggregation",
    "PortfolioSnapshot",
    "PositionSide",
    "PositionExposureInput",
    "PositionSizingResult",
    "PositionSizingRequest",
    "PositionSnapshot",
    "PriceValue",
    "RatioValue",
    "RevalidationStatus",
    "RevalidationTrigger",
    "ReturnObservation",
    "ReturnSeriesProvenance",
    "RiskAssessment",
    "RiskCheckOutcome",
    "RiskContext",
    "RiskContractError",
    "RiskDecision",
    "RiskLimitDefinition",
    "RiskLimitDirection",
    "RiskLimitHierarchy",
    "RiskLimitPolicyConfiguration",
    "RiskLimitScope",
    "RiskLimitResult",
    "RiskLimitSeverity",
    "RiskPolicyMode",
    "RiskProposal",
    "RiskRevalidationResult",
    "RiskState",
    "RiskVerdict",
    "SizingMethod",
    "SizingInstrumentTerms",
    "SizingCosts",
    "SnapshotState",
    "StopLossAssessment",
    "StopLossAssessmentRequest",
    "StopLossStructuralEvidence",
    "StopLossVolatilityEvidence",
    "StopLossLiquidationEvidence",
    "StressScenarioResult",
    "StressTestResult",
    "TakeProfitAssessment",
    "TakeProfitTarget",
    "VersionReference",
    "aggregate_portfolio_exposure",
    "calculate_position_size",
    "calculate_stop_loss_assessment",
    "pairwise_correlation",
]
