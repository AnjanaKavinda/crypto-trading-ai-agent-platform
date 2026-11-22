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
class LinearMarginRuleEvidence:
    """Caller-attested incremental linear margin tier for one account and mode."""

    venue: str
    instrument_id: str
    account_id: UUID
    account_snapshot_id: UUID
    margin_mode: MarginMode
    tier_lower_bound: MoneyValue
    tier_upper_bound: MoneyValue
    initial_margin_rate: Decimal
    maintenance_margin_rate: Decimal
    model: str
    version: VersionReference
    as_of: datetime
    valid_until: datetime

    def __post_init__(self) -> None:
        for name in ("venue", "instrument_id", "model"):
            _text(name, getattr(self, name))
        _uuid("account_id", self.account_id)
        _uuid("account_snapshot_id", self.account_snapshot_id)
        if not isinstance(self.margin_mode, MarginMode):
            raise RiskContractError("margin_mode must be a MarginMode.")
        lower = _money("tier_lower_bound", self.tier_lower_bound)
        upper = _money("tier_upper_bound", self.tier_upper_bound, positive=True)
        if lower.currency != upper.currency or lower.amount > upper.amount:
            raise RiskContractError(
                "margin tier bounds must be ordered in one currency."
            )
        _decimal("initial_margin_rate", self.initial_margin_rate)
        _decimal("maintenance_margin_rate", self.maintenance_margin_rate)
        if (
            not (
                Decimal(0)
                <= self.maintenance_margin_rate
                <= self.initial_margin_rate
                <= Decimal(1)
            )
            or self.initial_margin_rate <= 0
        ):
            raise RiskContractError(
                "margin rates must satisfy 0 <= maintenance <= initial <= 1."
            )
        if not isinstance(self.version, VersionReference):
            raise RiskContractError("version must be a VersionReference.")
        as_of = _time("as_of", self.as_of)
        valid_until = _time("valid_until", self.valid_until)
        _ordered("as_of", as_of, "valid_until", valid_until)
        object.__setattr__(self, "as_of", as_of)
        object.__setattr__(self, "valid_until", valid_until)


@dataclass(frozen=True, slots=True)
class LeverageAssessmentRequest:
    """Explicit offline inputs for a bounded C-076 leverage assessment."""

    result_id: UUID
    evaluated_at: datetime
    sizing_request: PositionSizingRequest
    requested_leverage: Decimal
    margin_mode: MarginMode
    policy_maximum_leverage: Decimal
    account_maximum_leverage: Decimal
    venue_maximum_leverage: Decimal
    maximum_post_trade_gross_leverage: Decimal
    minimum_remaining_free_margin: MoneyValue
    additional_reserved_cost: MoneyValue
    margin_rule: LinearMarginRuleEvidence | None

    def __post_init__(self) -> None:
        _uuid("result_id", self.result_id)
        evaluated_at = _time("evaluated_at", self.evaluated_at)
        if not isinstance(self.sizing_request, PositionSizingRequest):
            raise RiskContractError("sizing_request must be a PositionSizingRequest.")
        if self.sizing_request.evaluated_at != evaluated_at:
            raise RiskContractError("sizing_request evaluation time mismatch.")
        for name in (
            "requested_leverage",
            "policy_maximum_leverage",
            "account_maximum_leverage",
            "venue_maximum_leverage",
            "maximum_post_trade_gross_leverage",
        ):
            _positive(name, getattr(self, name))
        if self.requested_leverage < 1:
            raise RiskContractError("requested_leverage must be at least one.")
        if not isinstance(self.margin_mode, MarginMode):
            raise RiskContractError("margin_mode must be a MarginMode.")
        _money("minimum_remaining_free_margin", self.minimum_remaining_free_margin)
        _money("additional_reserved_cost", self.additional_reserved_cost)
        if self.margin_rule is not None and not isinstance(
            self.margin_rule, LinearMarginRuleEvidence
        ):
            raise RiskContractError(
                "margin_rule must be LinearMarginRuleEvidence or None."
            )
        object.__setattr__(self, "evaluated_at", evaluated_at)


@dataclass(frozen=True, slots=True)
class LiquidationPriceEvidence:
    """Caller-attested linear estimate; it is not generated or authenticated here."""

    context: RiskContext
    asset: str
    instrument_id: str
    venue: str
    account_id: UUID
    account_snapshot_id: UUID
    portfolio_snapshot_id: UUID
    side: PositionSide
    margin_mode: MarginMode
    entry_price: PriceValue
    stop_loss: PriceValue
    quantity: Decimal
    liquidation_price: PriceValue
    formula_model: str | None
    formula_version: VersionReference | None
    source_id: str | None
    source_version: VersionReference | None
    exchange_constraints: VersionReference | None
    basis_request: LeverageAssessmentRequest
    as_of: datetime
    valid_until: datetime
    cost_basis: LiquidationCostEvidence | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.context, RiskContext):
            raise RiskContractError("context must be a RiskContext.")
        for name in ("asset", "instrument_id", "venue"):
            _text(name, getattr(self, name))
        for name in ("formula_model", "source_id"):
            value = getattr(self, name)
            if value is not None:
                _text(name, value)
        for name in ("account_id", "account_snapshot_id", "portfolio_snapshot_id"):
            _uuid(name, getattr(self, name))
        if not isinstance(self.side, PositionSide):
            raise RiskContractError("side must be a PositionSide.")
        if not isinstance(self.margin_mode, MarginMode):
            raise RiskContractError("margin_mode must be a MarginMode.")
        for name in ("entry_price", "stop_loss", "liquidation_price"):
            if not isinstance(getattr(self, name), PriceValue):
                raise RiskContractError(f"{name} must be a PriceValue.")
        _positive("quantity", self.quantity)
        for name in ("formula_version", "source_version", "exchange_constraints"):
            value = getattr(self, name)
            if value is not None and not isinstance(value, VersionReference):
                raise RiskContractError(f"{name} must be a VersionReference or None.")
        if not isinstance(self.basis_request, LeverageAssessmentRequest):
            raise RiskContractError(
                "basis_request must be a LeverageAssessmentRequest."
            )
        if self.cost_basis is not None and not isinstance(
            self.cost_basis, LiquidationCostEvidence
        ):
            raise RiskContractError(
                "cost_basis must be LiquidationCostEvidence or None."
            )
        as_of = _time("as_of", self.as_of)
        valid_until = _time("valid_until", self.valid_until)
        _ordered("as_of", as_of, "valid_until", valid_until)
        object.__setattr__(self, "as_of", as_of)
        object.__setattr__(self, "valid_until", valid_until)


@dataclass(frozen=True, slots=True)
class LiquidationDistanceThresholds:
    """Versioned quote-price distance limits supplied by the caller."""

    context: RiskContext
    asset: str
    instrument_id: str
    side: PositionSide
    minimum_entry_distance_ratio: Decimal
    minimum_ratio_version: VersionReference
    minimum_stop_buffer: Decimal
    normal_adverse_displacement: Decimal
    normal_version: VersionReference
    stress_adverse_displacement: Decimal
    stress_version: VersionReference
    quote_currency: str
    as_of: datetime
    valid_until: datetime

    def __post_init__(self) -> None:
        if not isinstance(self.context, RiskContext):
            raise RiskContractError("context must be a RiskContext.")
        _text("asset", self.asset)
        _text("instrument_id", self.instrument_id)
        if not isinstance(self.side, PositionSide):
            raise RiskContractError("side must be a PositionSide.")
        ratio = _nonnegative(
            "minimum_entry_distance_ratio", self.minimum_entry_distance_ratio
        )
        if ratio > 1:
            raise RiskContractError("minimum_entry_distance_ratio must be in [0, 1].")
        for name in (
            "minimum_ratio_version",
            "normal_version",
            "stress_version",
        ):
            if not isinstance(getattr(self, name), VersionReference):
                raise RiskContractError(f"{name} must be a VersionReference.")
        for name in (
            "minimum_stop_buffer",
            "normal_adverse_displacement",
            "stress_adverse_displacement",
        ):
            _nonnegative(name, getattr(self, name))
        _text("quote_currency", self.quote_currency)
        as_of = _time("as_of", self.as_of)
        valid_until = _time("valid_until", self.valid_until)
        _ordered("as_of", as_of, "valid_until", valid_until)
        object.__setattr__(self, "as_of", as_of)
        object.__setattr__(self, "valid_until", valid_until)


@dataclass(frozen=True, slots=True)
class LiquidationCostEvidence:
    """Reserves are bound as already included; no liquidation-price adjustment."""

    fee_reserve: MoneyValue
    funding_reserve: MoneyValue
    treatment: str | None
    version: VersionReference | None
    as_of: datetime
    valid_until: datetime

    def __post_init__(self) -> None:
        _money("fee_reserve", self.fee_reserve)
        _money("funding_reserve", self.funding_reserve)
        if self.treatment is not None:
            _text("treatment", self.treatment)
        if self.version is not None and not isinstance(self.version, VersionReference):
            raise RiskContractError("version must be a VersionReference or None.")
        as_of = _time("as_of", self.as_of)
        valid_until = _time("valid_until", self.valid_until)
        _ordered("as_of", as_of, "valid_until", valid_until)
        object.__setattr__(self, "as_of", as_of)
        object.__setattr__(self, "valid_until", valid_until)


@dataclass(frozen=True, slots=True)
class LiquidationAssessmentRequest:
    """Nonpersisted inputs for a bounded, supplied-estimate C-077 assessment."""

    result_id: UUID
    evaluated_at: datetime
    leverage_request: LeverageAssessmentRequest
    stop_loss: PriceValue
    estimate: LiquidationPriceEvidence | None
    thresholds: LiquidationDistanceThresholds
    costs: LiquidationCostEvidence

    def __post_init__(self) -> None:
        _uuid("result_id", self.result_id)
        evaluated_at = _time("evaluated_at", self.evaluated_at)
        if not isinstance(self.leverage_request, LeverageAssessmentRequest):
            raise RiskContractError(
                "leverage_request must be a LeverageAssessmentRequest."
            )
        if self.leverage_request.evaluated_at != evaluated_at:
            raise RiskContractError("leverage request evaluation time mismatch.")
        if not isinstance(self.stop_loss, PriceValue):
            raise RiskContractError("stop_loss must be a PriceValue.")
        if self.estimate is not None and not isinstance(
            self.estimate, LiquidationPriceEvidence
        ):
            raise RiskContractError(
                "estimate must be LiquidationPriceEvidence or None."
            )
        if not isinstance(self.thresholds, LiquidationDistanceThresholds):
            raise RiskContractError("thresholds must be LiquidationDistanceThresholds.")
        if not isinstance(self.costs, LiquidationCostEvidence):
            raise RiskContractError("costs must be LiquidationCostEvidence.")
        object.__setattr__(self, "evaluated_at", evaluated_at)


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
    price_unit_currency: str
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
        _text("price_unit_currency", self.price_unit_currency)
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
            or (
                reference.content_sha256 is not None
                and reference.content_sha256 != snapshot.content_sha256
            )
            or (
                reference.valid_until is not None
                and reference.valid_until != snapshot.valid_until
            )
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


def _leverage_assessment_result(
    request: LeverageAssessmentRequest,
    sizing: PositionSizingResult,
    outcome: RiskCheckOutcome,
    reasons: tuple[str, ...],
    limits: tuple[RiskLimitResult, ...],
    *,
    maximum_permitted_leverage: Decimal | None = None,
    effective_leverage: Decimal | None = None,
    portfolio_leverage: Decimal | None = None,
    initial_margin: MoneyValue | None = None,
    maintenance_margin: MoneyValue | None = None,
    proposed_margin: MoneyValue | None = None,
    post_trade_free_margin: MoneyValue | None = None,
) -> LeverageAssessment:
    sizing_request = request.sizing_request
    valid_until = min(
        sizing.valid_until,
        request.margin_rule.valid_until
        if request.margin_rule is not None
        else sizing.valid_until,
    )
    valid_until = max(valid_until, request.evaluated_at)
    result = LeverageAssessment(
        result_id=request.result_id,
        context=sizing_request.context,
        outcome=outcome,
        reason_codes=reasons,
        model_version=sizing_request.model_version,
        as_of=sizing_request.context.as_of,
        evaluated_at=request.evaluated_at,
        valid_until=valid_until,
        content_sha256="0" * 64,
        requested_leverage=request.requested_leverage,
        maximum_permitted_leverage=maximum_permitted_leverage,
        effective_leverage=effective_leverage,
        post_trade_portfolio_leverage=portfolio_leverage,
        margin_mode=request.margin_mode,
        initial_margin=initial_margin,
        maintenance_margin=maintenance_margin,
        proposed_margin=proposed_margin,
        post_trade_free_margin=post_trade_free_margin,
        exchange_constraints=(
            request.margin_rule.version if request.margin_rule is not None else None
        ),
        limits=limits,
    )
    return replace(
        result,
        content_sha256=_risk_digest(
            "leverage assessment",
            {
                "request": request,
                "sizing_result": sizing,
                "result": {
                    item.name: getattr(result, item.name)
                    for item in fields(result)
                    if item.name != "content_sha256"
                },
            },
        ),
    )


def calculate_leverage_assessment(
    request: LeverageAssessmentRequest,
) -> LeverageAssessment:
    """Assess explicit incremental linear margin evidence; never authorize trading."""
    if not isinstance(request, LeverageAssessmentRequest):
        raise RiskContractError("request must be a LeverageAssessmentRequest.")
    sizing_request = request.sizing_request
    try:
        with localcontext(Context(prec=34, rounding=ROUND_HALF_EVEN)):
            sizing = calculate_position_size(sizing_request)
            reasons: list[str] = list(sizing.reason_codes)
            limits: list[RiskLimitResult] = []
            failed = sizing.outcome is RiskCheckOutcome.FAILED
            insufficient = sizing.outcome is RiskCheckOutcome.INSUFFICIENT_DATA
            warned = sizing.outcome is RiskCheckOutcome.WARNING

            def record(code: str, outcome: RiskCheckOutcome) -> None:
                nonlocal failed, insufficient, warned
                if code not in reasons:
                    reasons.append(code)
                failed = failed or outcome is RiskCheckOutcome.FAILED
                insufficient = (
                    insufficient or outcome is RiskCheckOutcome.INSUFFICIENT_DATA
                )
                warned = warned or outcome is RiskCheckOutcome.WARNING

            def check(
                limit_id: str,
                observed: Decimal,
                boundary: Decimal,
                unit: str,
                passed: bool,
                reason: str,
            ) -> None:
                outcome = RiskCheckOutcome.PASSED if passed else RiskCheckOutcome.FAILED
                limits.append(
                    RiskLimitResult(
                        limit_id,
                        RiskLimitSeverity.HARD,
                        observed,
                        boundary,
                        unit,
                        outcome,
                        reason,
                    )
                )
                if not passed:
                    record(reason, RiskCheckOutcome.FAILED)

            refs = (
                (sizing_request.context.signal, "C-070"),
                (sizing_request.context.validation, "C-028"),
                (sizing_request.context.strategy_version, "C-021"),
                (sizing_request.context.account_snapshot, "C-032"),
                (sizing_request.context.portfolio_snapshot, "C-033"),
            )
            for reference, contract_id in refs:
                status, code = _stop_reference_status(
                    reference, contract_id, request.evaluated_at
                )
                if status is not None:
                    record(code or "REFERENCE_PROVENANCE_INCOMPLETE", status)

            account, portfolio = sizing_request.account, sizing_request.portfolio
            terms, rule = sizing_request.instrument, request.margin_rule
            if terms is None:
                record("SIZING_INSTRUMENT_MISSING", RiskCheckOutcome.INSUFFICIENT_DATA)
            if rule is None:
                record("MARGIN_RULE_MISSING", RiskCheckOutcome.INSUFFICIENT_DATA)
            if account.state is not SnapshotState.VALID:
                record("ACCOUNT_SNAPSHOT_NOT_VALID", RiskCheckOutcome.INSUFFICIENT_DATA)
            if portfolio.state is not SnapshotState.VALID:
                record(
                    "PORTFOLIO_SNAPSHOT_NOT_VALID", RiskCheckOutcome.INSUFFICIENT_DATA
                )
            if account.account_id != portfolio.account_snapshot.account_id:
                record("PORTFOLIO_ACCOUNT_MISMATCH", RiskCheckOutcome.FAILED)
            if account.currency != portfolio.currency:
                record("PORTFOLIO_CURRENCY_MISMATCH", RiskCheckOutcome.FAILED)
            if account.equity is None or portfolio.equity is None:
                record("EQUITY_MISSING", RiskCheckOutcome.INSUFFICIENT_DATA)
            elif (
                account.equity.amount <= 0
                or portfolio.equity.amount <= 0
                or portfolio.equity != account.equity
            ):
                record("POSITIVE_MATCHING_EQUITY_REQUIRED", RiskCheckOutcome.FAILED)
            if terms is not None and (
                account.currency != terms.quote_currency
                or portfolio.currency != terms.quote_currency
                or request.minimum_remaining_free_margin.currency
                != terms.quote_currency
                or request.additional_reserved_cost.currency != terms.quote_currency
                or (
                    rule is not None
                    and rule.tier_lower_bound.currency != terms.quote_currency
                )
            ):
                record("LEVERAGE_CURRENCY_MISMATCH", RiskCheckOutcome.FAILED)

            if rule is not None and rule.model != "LINEAR":
                record("UNSUPPORTED_MARGIN_MODEL", RiskCheckOutcome.FAILED)
            if rule is not None and terms is not None and rule.venue != terms.venue:
                record("MARGIN_RULE_VENUE_MISMATCH", RiskCheckOutcome.FAILED)
            if (
                rule is not None
                and terms is not None
                and rule.instrument_id != terms.instrument_id
            ):
                record("MARGIN_RULE_INSTRUMENT_MISMATCH", RiskCheckOutcome.FAILED)
            if rule is not None and (
                rule.account_id != account.account_id
                or rule.account_snapshot_id != account.snapshot_id
            ):
                record("MARGIN_RULE_ACCOUNT_MISMATCH", RiskCheckOutcome.FAILED)
            if rule is not None and rule.margin_mode is not request.margin_mode:
                record("MARGIN_RULE_MODE_MISMATCH", RiskCheckOutcome.FAILED)
            if rule is not None and rule.as_of > request.evaluated_at:
                record("MARGIN_RULE_FUTURE_DATED", RiskCheckOutcome.INSUFFICIENT_DATA)
            if rule is not None and rule.valid_until < request.evaluated_at:
                record("MARGIN_RULE_EXPIRED", RiskCheckOutcome.INSUFFICIENT_DATA)
            if sizing_request.assumptions_as_of > request.evaluated_at:
                record("ASSUMPTIONS_FUTURE_DATED", RiskCheckOutcome.INSUFFICIENT_DATA)
            if sizing_request.assumptions_valid_until < request.evaluated_at:
                record("ASSUMPTIONS_EXPIRED", RiskCheckOutcome.INSUFFICIENT_DATA)

            positions = portfolio.positions
            if len({item.snapshot_id for item in positions}) != len(positions) or len(
                {item.position_id for item in positions}
            ) != len(positions):
                record("DUPLICATE_POSITION_IDENTITY", RiskCheckOutcome.FAILED)
            if (
                len(
                    {
                        account.snapshot_id,
                        portfolio.snapshot_id,
                        *(item.snapshot_id for item in positions),
                    }
                )
                != len(positions) + 2
            ):
                record("DUPLICATE_SNAPSHOT_IDENTITY", RiskCheckOutcome.FAILED)
            for item in positions:
                if item.account_id != account.account_id:
                    record("POSITION_ACCOUNT_MISMATCH", RiskCheckOutcome.FAILED)
                if (
                    terms is not None
                    and item.instrument_id == terms.instrument_id
                    and item.asset != terms.asset
                ):
                    record("POSITION_INSTRUMENT_MISMATCH", RiskCheckOutcome.FAILED)
                if item.state is not SnapshotState.VALID:
                    record(
                        "POSITION_SNAPSHOT_NOT_VALID",
                        RiskCheckOutcome.INSUFFICIENT_DATA,
                    )
                if (
                    item.as_of > request.evaluated_at
                    or item.captured_at > request.evaluated_at
                    or item.valid_until < request.evaluated_at
                ):
                    record(
                        "POSITION_SNAPSHOT_NOT_CURRENT",
                        RiskCheckOutcome.INSUFFICIENT_DATA,
                    )
                if not isinstance(item.source_version, VersionReference):
                    record(
                        "POSITION_PROVENANCE_INCOMPLETE",
                        RiskCheckOutcome.INSUFFICIENT_DATA,
                    )
                if item.notional is None:
                    record(
                        "POSITION_NOTIONAL_MISSING", RiskCheckOutcome.INSUFFICIENT_DATA
                    )
                elif (
                    terms is not None and item.notional.currency != terms.quote_currency
                ):
                    record("POSITION_CURRENCY_MISMATCH", RiskCheckOutcome.FAILED)

            if sizing.outcome in {
                RiskCheckOutcome.FAILED,
                RiskCheckOutcome.INSUFFICIENT_DATA,
            }:
                failed = failed or sizing.outcome is RiskCheckOutcome.FAILED
                insufficient = (
                    insufficient or sizing.outcome is RiskCheckOutcome.INSUFFICIENT_DATA
                )
            elif any(
                value is None
                for value in (
                    sizing.recommended_quantity,
                    sizing.recommended_notional,
                    sizing.recommended_margin,
                )
            ):
                record("SIZING_OUTPUT_INCOMPLETE", RiskCheckOutcome.INSUFFICIENT_DATA)

            # A known request/policy breach is conclusive even when venue
            # evidence is missing; do not let an unknown hide a hard failure.
            maximum_leverage = min(
                request.policy_maximum_leverage,
                request.account_maximum_leverage,
                request.venue_maximum_leverage,
            )
            check(
                "requested-leverage-cap",
                request.requested_leverage,
                maximum_leverage,
                "leverage",
                request.requested_leverage <= maximum_leverage,
                "REQUESTED_LEVERAGE_EXCEEDS_CAP",
            )
            if failed or insufficient:
                outcome = (
                    RiskCheckOutcome.FAILED
                    if failed
                    else RiskCheckOutcome.INSUFFICIENT_DATA
                )
                return _leverage_assessment_result(
                    request, sizing, outcome, tuple(reasons), tuple(limits)
                )

            assert terms is not None
            assert rule is not None
            assert account.equity is not None
            assert account.available_balance is not None
            assert account.free_margin is not None
            assert portfolio.gross_exposure is not None
            assert sizing.recommended_quantity is not None
            assert sizing.recommended_notional is not None
            assert sizing.recommended_margin is not None
            quantity = sizing.recommended_quantity
            notional = sizing.recommended_notional.amount
            proposed_margin = sizing.recommended_margin.amount
            currency = terms.quote_currency
            with localcontext() as arithmetic:
                arithmetic.prec = 34
                arithmetic.rounding = ROUND_HALF_EVEN
                arithmetic.traps[Inexact] = True
                expected_notional = (
                    quantity * sizing_request.entry.amount * terms.contract_multiplier
                )
                expected_margin = quantity * terms.initial_margin_per_unit.amount
                gross_exposure = sum(
                    (
                        item.notional.amount
                        for item in positions
                        if item.notional is not None
                    ),
                    Decimal(0),
                )
                instrument_gross = sum(
                    (
                        item.notional.amount
                        for item in positions
                        if item.instrument_id == terms.instrument_id
                        and item.asset == terms.asset
                        and item.notional is not None
                    ),
                    Decimal(0),
                )
                if notional != expected_notional or proposed_margin != expected_margin:
                    record("SIZING_AMOUNT_INCONSISTENT", RiskCheckOutcome.FAILED)
                check(
                    "portfolio-gross-exposure",
                    gross_exposure,
                    portfolio.gross_exposure.amount,
                    currency,
                    gross_exposure == portfolio.gross_exposure.amount,
                    "PORTFOLIO_GROSS_EXPOSURE_MISMATCH",
                )
                post_trade_gross = gross_exposure + notional
                instrument_post_gross = instrument_gross + notional
                equity = account.equity.amount
                check(
                    "margin-tier-lower",
                    instrument_post_gross,
                    rule.tier_lower_bound.amount,
                    currency,
                    instrument_post_gross >= rule.tier_lower_bound.amount,
                    "MARGIN_TIER_LOWER_BOUND_MISSED",
                )
                check(
                    "margin-tier-upper",
                    instrument_post_gross,
                    rule.tier_upper_bound.amount,
                    currency,
                    instrument_post_gross <= rule.tier_upper_bound.amount,
                    "MARGIN_TIER_UPPER_BOUND_EXCEEDED",
                )
                with localcontext(Context(prec=34, rounding=ROUND_CEILING)):
                    divided_margin = notional / request.requested_leverage
                    effective_leverage = notional / proposed_margin
                    portfolio_leverage = post_trade_gross / equity
                required_margin = max(
                    proposed_margin,
                    divided_margin,
                    notional * rule.initial_margin_rate,
                )
                maintenance_margin = notional * rule.maintenance_margin_rate
                check(
                    "effective-leverage-cap",
                    notional,
                    proposed_margin * maximum_leverage,
                    f"{currency}-notional-cross-multiplied",
                    notional <= proposed_margin * maximum_leverage,
                    "EFFECTIVE_LEVERAGE_EXCEEDS_CAP",
                )
                check(
                    "initial-margin-coverage",
                    proposed_margin,
                    required_margin,
                    currency,
                    proposed_margin >= required_margin,
                    "PROPOSED_MARGIN_INSUFFICIENT",
                )
                consumed_funds = (
                    proposed_margin + request.additional_reserved_cost.amount
                )
                check(
                    "available-balance",
                    consumed_funds,
                    account.available_balance.amount,
                    currency,
                    consumed_funds <= account.available_balance.amount,
                    "AVAILABLE_BALANCE_INSUFFICIENT",
                )
                check(
                    "free-margin-available",
                    consumed_funds,
                    account.free_margin.amount,
                    currency,
                    consumed_funds <= account.free_margin.amount,
                    "FREE_MARGIN_INSUFFICIENT",
                )
                post_free_margin = account.free_margin.amount - consumed_funds
                check(
                    "minimum-free-margin",
                    post_free_margin,
                    request.minimum_remaining_free_margin.amount,
                    currency,
                    post_free_margin >= request.minimum_remaining_free_margin.amount,
                    "FREE_MARGIN_BUFFER_BREACHED",
                )
                check(
                    "gross-portfolio-leverage-cap",
                    post_trade_gross,
                    equity * request.maximum_post_trade_gross_leverage,
                    f"{currency}-notional-cross-multiplied",
                    post_trade_gross
                    <= equity * request.maximum_post_trade_gross_leverage,
                    "POST_TRADE_GROSS_LEVERAGE_EXCEEDS_CAP",
                )

            if failed:
                outcome = RiskCheckOutcome.FAILED
            elif insufficient:
                outcome = RiskCheckOutcome.INSUFFICIENT_DATA
            elif warned:
                outcome = RiskCheckOutcome.WARNING
            else:
                outcome = RiskCheckOutcome.PASSED
            if outcome in {
                RiskCheckOutcome.FAILED,
                RiskCheckOutcome.INSUFFICIENT_DATA,
            }:
                return _leverage_assessment_result(
                    request, sizing, outcome, tuple(reasons), tuple(limits)
                )
            return _leverage_assessment_result(
                request,
                sizing,
                outcome,
                tuple(reasons),
                tuple(limits),
                maximum_permitted_leverage=maximum_leverage,
                effective_leverage=effective_leverage,
                portfolio_leverage=portfolio_leverage,
                initial_margin=MoneyValue(required_margin, currency),
                maintenance_margin=MoneyValue(maintenance_margin, currency),
                proposed_margin=MoneyValue(proposed_margin, currency),
                post_trade_free_margin=MoneyValue(post_free_margin, currency),
            )
    except DecimalException as exc:
        raise RiskContractError(
            "leverage arithmetic cannot be represented safely at precision 34."
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


def calculate_liquidation_assessment(
    request: LiquidationAssessmentRequest,
) -> LiquidationAssessment:
    """Assess caller-supplied linear liquidation evidence without pricing it."""
    if not isinstance(request, LiquidationAssessmentRequest):
        raise RiskContractError("request must be a LiquidationAssessmentRequest.")
    try:
        with localcontext(Context(prec=34, rounding=ROUND_HALF_EVEN)) as arithmetic:
            arithmetic.traps[Inexact] = True
            leverage_request = request.leverage_request
            sizing_request = leverage_request.sizing_request
            context = sizing_request.context
            account, portfolio = sizing_request.account, sizing_request.portfolio
            terms = sizing_request.instrument
            thresholds, estimate = request.thresholds, request.estimate
            leverage = calculate_leverage_assessment(leverage_request)
            sizing = calculate_position_size(sizing_request)
            reasons: list[str] = []
            failed = leverage.outcome is RiskCheckOutcome.FAILED
            insufficient = leverage.outcome is RiskCheckOutcome.INSUFFICIENT_DATA
            warned = leverage.outcome is RiskCheckOutcome.WARNING

            def record(code: str, outcome: RiskCheckOutcome) -> None:
                nonlocal failed, insufficient, warned
                if code not in reasons:
                    reasons.append(code)
                failed = failed or outcome is RiskCheckOutcome.FAILED
                insufficient = (
                    insufficient or outcome is RiskCheckOutcome.INSUFFICIENT_DATA
                )
                warned = warned or outcome is RiskCheckOutcome.WARNING

            for upstream_reason in leverage.reason_codes:
                if upstream_reason not in reasons:
                    reasons.append(upstream_reason)
            expiries = [
                leverage.valid_until,
                sizing_request.assumptions_valid_until,
            ]
            expiries.extend(item.valid_until for item in portfolio.positions)
            if estimate is None:
                record(
                    "LIQUIDATION_ESTIMATE_MISSING",
                    RiskCheckOutcome.INSUFFICIENT_DATA,
                )

            for reference, contract_id in (
                (context.signal, "C-070"),
                (context.validation, "C-028"),
                (context.strategy_version, "C-021"),
                (context.account_snapshot, "C-032"),
                (context.portfolio_snapshot, "C-033"),
            ):
                status, code = _stop_reference_status(
                    reference, contract_id, request.evaluated_at
                )
                if status is not None:
                    record(code or "REFERENCE_PROVENANCE_INCOMPLETE", status)
                if reference.valid_until is not None:
                    expiries.append(reference.valid_until)
            for reference, snapshot, contract_id in (
                (context.account_snapshot, account, "C-032"),
                (context.portfolio_snapshot, portfolio, "C-033"),
            ):
                if reference.entity_id != snapshot.snapshot_id or (
                    reference.content_sha256 is not None
                    and reference.content_sha256 != snapshot.content_sha256
                ):
                    record("SNAPSHOT_REFERENCE_MISMATCH", RiskCheckOutcome.FAILED)
                if (
                    reference.content_sha256 is None
                    or reference.schema_version != "1"
                    or snapshot.contract_id != contract_id
                    or snapshot.schema_version != "1"
                ):
                    record(
                        "SNAPSHOT_REFERENCE_PROVENANCE_INCOMPLETE",
                        RiskCheckOutcome.INSUFFICIENT_DATA,
                    )
                if snapshot.valid_until < request.evaluated_at:
                    record("SNAPSHOT_EXPIRED", RiskCheckOutcome.INSUFFICIENT_DATA)
                if snapshot.as_of > request.evaluated_at or (
                    snapshot.captured_at > request.evaluated_at
                ):
                    record("SNAPSHOT_FUTURE_DATED", RiskCheckOutcome.INSUFFICIENT_DATA)
                expiries.append(snapshot.valid_until)

            if terms is None:
                record("SIZING_INSTRUMENT_MISSING", RiskCheckOutcome.INSUFFICIENT_DATA)
            else:
                if (
                    thresholds.quote_currency != terms.quote_currency
                    or request.stop_loss.quote_currency != terms.quote_currency
                    or request.costs.fee_reserve.currency != terms.quote_currency
                    or request.costs.funding_reserve.currency != terms.quote_currency
                ):
                    record("LIQUIDATION_CURRENCY_MISMATCH", RiskCheckOutcome.FAILED)
                if (
                    context.asset != terms.asset
                    or context.instrument_id != terms.instrument_id
                ):
                    record("LIQUIDATION_INSTRUMENT_MISMATCH", RiskCheckOutcome.FAILED)

            if request.costs.treatment != "ALREADY_INCLUDED_IN_SUPPLIED_ESTIMATE":
                record(
                    "LIQUIDATION_COST_TREATMENT_UNSUPPORTED",
                    RiskCheckOutcome.INSUFFICIENT_DATA,
                )
            if request.costs.version is None:
                record(
                    "LIQUIDATION_COST_VERSION_MISSING",
                    RiskCheckOutcome.INSUFFICIENT_DATA,
                )
            if (
                request.costs.fee_reserve.currency
                != request.costs.funding_reserve.currency
            ):
                record(
                    "LIQUIDATION_COST_CURRENCY_MISMATCH",
                    RiskCheckOutcome.FAILED,
                )

            for item, name in (
                (thresholds, "LIQUIDATION_THRESHOLDS"),
                (request.costs, "LIQUIDATION_COSTS"),
            ):
                if item.as_of < context.as_of:
                    record(f"{name}_STALE", RiskCheckOutcome.INSUFFICIENT_DATA)
                if item.as_of > request.evaluated_at:
                    record(f"{name}_FUTURE_DATED", RiskCheckOutcome.INSUFFICIENT_DATA)
                if item.valid_until < request.evaluated_at:
                    record(f"{name}_EXPIRED", RiskCheckOutcome.INSUFFICIENT_DATA)
                expiries.append(item.valid_until)
            if thresholds.minimum_entry_distance_ratio > 1:
                record(
                    "DISTANCE_NOT_REPRESENTABLE",
                    RiskCheckOutcome.INSUFFICIENT_DATA,
                )

            expected_basis = (
                context,
                context.asset,
                context.instrument_id,
                context.side,
            )
            if (
                thresholds.context != context
                or (
                    thresholds.asset,
                    thresholds.instrument_id,
                    thresholds.side,
                )
                != expected_basis[1:]
            ):
                record(
                    "LIQUIDATION_THRESHOLD_BASIS_MISMATCH",
                    RiskCheckOutcome.FAILED,
                )

            if estimate is not None:
                if estimate.context != context or (
                    estimate.asset,
                    estimate.instrument_id,
                    estimate.side,
                    estimate.entry_price,
                    estimate.stop_loss,
                    estimate.basis_request,
                ) != (
                    context.asset,
                    context.instrument_id,
                    context.side,
                    sizing_request.entry,
                    request.stop_loss,
                    leverage_request,
                ):
                    record(
                        "LIQUIDATION_ESTIMATE_BASIS_MISMATCH",
                        RiskCheckOutcome.FAILED,
                    )
                if (
                    sizing.recommended_quantity is not None
                    and estimate.quantity != sizing.recommended_quantity
                ):
                    record(
                        "LIQUIDATION_ESTIMATE_BASIS_MISMATCH", RiskCheckOutcome.FAILED
                    )
                if estimate.cost_basis is None:
                    record(
                        "LIQUIDATION_ESTIMATE_COST_BASIS_MISSING",
                        RiskCheckOutcome.INSUFFICIENT_DATA,
                    )
                elif estimate.cost_basis != request.costs:
                    record(
                        "LIQUIDATION_ESTIMATE_COST_BASIS_MISMATCH",
                        RiskCheckOutcome.FAILED,
                    )
                if estimate.margin_mode is not leverage_request.margin_mode:
                    record("LIQUIDATION_MARGIN_MODE_MISMATCH", RiskCheckOutcome.FAILED)
                if estimate.account_id != account.account_id:
                    record("LIQUIDATION_ACCOUNT_MISMATCH", RiskCheckOutcome.FAILED)
                if estimate.account_snapshot_id != account.snapshot_id:
                    record(
                        "LIQUIDATION_ACCOUNT_SNAPSHOT_MISMATCH",
                        RiskCheckOutcome.FAILED,
                    )
                if estimate.portfolio_snapshot_id != portfolio.snapshot_id:
                    record(
                        "LIQUIDATION_PORTFOLIO_SNAPSHOT_MISMATCH",
                        RiskCheckOutcome.FAILED,
                    )
                if terms is not None and (
                    estimate.venue != terms.venue
                    or estimate.instrument_id != terms.instrument_id
                ):
                    record(
                        "LIQUIDATION_SOURCE_INSTRUMENT_MISMATCH",
                        RiskCheckOutcome.FAILED,
                    )
                if estimate.formula_model != "LINEAR":
                    record(
                        "LIQUIDATION_FORMULA_UNSUPPORTED",
                        RiskCheckOutcome.INSUFFICIENT_DATA,
                    )
                if (
                    estimate.formula_version is None
                    or estimate.source_id is None
                    or estimate.source_version is None
                    or estimate.exchange_constraints is None
                ):
                    record(
                        "LIQUIDATION_FORMULA_OR_SOURCE_DATA_MISSING",
                        RiskCheckOutcome.INSUFFICIENT_DATA,
                    )
                elif estimate.source_version.component != estimate.source_id:
                    record(
                        "LIQUIDATION_SOURCE_IDENTITY_MISMATCH",
                        RiskCheckOutcome.FAILED,
                    )
                if estimate.as_of > request.evaluated_at:
                    record(
                        "LIQUIDATION_ESTIMATE_FUTURE_DATED",
                        RiskCheckOutcome.INSUFFICIENT_DATA,
                    )
                if estimate.as_of < context.as_of:
                    record(
                        "LIQUIDATION_ESTIMATE_STALE",
                        RiskCheckOutcome.INSUFFICIENT_DATA,
                    )
                if estimate.valid_until < request.evaluated_at:
                    record(
                        "LIQUIDATION_ESTIMATE_EXPIRED",
                        RiskCheckOutcome.INSUFFICIENT_DATA,
                    )
                expiries.append(estimate.valid_until)
                if (
                    estimate.entry_price.quote_currency
                    != estimate.liquidation_price.quote_currency
                ):
                    record(
                        "LIQUIDATION_PRICE_CURRENCY_MISMATCH",
                        RiskCheckOutcome.FAILED,
                    )
                if estimate.entry_price != sizing_request.entry or (
                    estimate.stop_loss != request.stop_loss
                ):
                    record("LIQUIDATION_PRICE_BASIS_MISMATCH", RiskCheckOutcome.FAILED)
                if terms is not None and (
                    estimate.entry_price.quote_currency != terms.quote_currency
                    or estimate.stop_loss.quote_currency != terms.quote_currency
                    or estimate.liquidation_price.quote_currency != terms.quote_currency
                ):
                    record(
                        "LIQUIDATION_CURRENCY_MISMATCH",
                        RiskCheckOutcome.FAILED,
                    )

            if request.stop_loss.quote_currency != sizing_request.entry.quote_currency:
                record("ENTRY_STOP_CURRENCY_MISMATCH", RiskCheckOutcome.FAILED)
            if request.stop_loss != sizing_request.stop:
                record("LIQUIDATION_STOP_BASIS_MISMATCH", RiskCheckOutcome.FAILED)
            if (
                context.side is PositionSide.LONG
                and request.stop_loss.amount >= sizing_request.entry.amount
            ) or (
                context.side is PositionSide.SHORT
                and request.stop_loss.amount <= sizing_request.entry.amount
            ):
                record("STOP_ON_WRONG_SIDE_OF_ENTRY", RiskCheckOutcome.FAILED)

            entry_distance: Decimal | None = None
            stop_clearance: Decimal | None = None
            if estimate is not None:
                entry = sizing_request.entry.amount
                liquidation_price = estimate.liquidation_price.amount
                stop = request.stop_loss.amount
                if context.side is PositionSide.LONG:
                    entry_distance = entry - liquidation_price
                    stop_clearance = stop - liquidation_price
                    if liquidation_price >= stop:
                        record("LIQUIDATION_AT_OR_INSIDE_STOP", RiskCheckOutcome.FAILED)
                    if liquidation_price >= entry:
                        record(
                            "LIQUIDATION_ON_WRONG_SIDE_OF_ENTRY",
                            RiskCheckOutcome.FAILED,
                        )
                else:
                    entry_distance = liquidation_price - entry
                    stop_clearance = liquidation_price - stop
                    if liquidation_price <= stop:
                        record("LIQUIDATION_AT_OR_INSIDE_STOP", RiskCheckOutcome.FAILED)
                    if liquidation_price <= entry:
                        record(
                            "LIQUIDATION_ON_WRONG_SIDE_OF_ENTRY",
                            RiskCheckOutcome.FAILED,
                        )
                if entry_distance <= 0:
                    record(
                        "LIQUIDATION_ON_WRONG_SIDE_OF_ENTRY", RiskCheckOutcome.FAILED
                    )
                if stop_clearance <= 0:
                    record("LIQUIDATION_AT_OR_INSIDE_STOP", RiskCheckOutcome.FAILED)

            entry_ratio: Decimal | None = None
            stop_ratio: Decimal | None = None
            normal_minimum = Decimal(0)
            stress_minimum = Decimal(0)
            if (
                entry_distance is not None
                and stop_clearance is not None
                and terms is not None
            ):
                with localcontext() as exact:
                    exact.traps[Inexact] = True
                    minimum_distance = (
                        thresholds.minimum_entry_distance_ratio
                        * sizing_request.entry.amount
                    )
                    normal_minimum = max(
                        thresholds.normal_adverse_displacement, minimum_distance
                    )
                    stress_minimum = max(
                        thresholds.stress_adverse_displacement, minimum_distance
                    )
                if not (
                    0 < entry_distance <= sizing_request.entry.amount
                    and 0 < stop_clearance <= sizing_request.entry.amount
                ):
                    record(
                        "DISTANCE_NOT_REPRESENTABLE",
                        RiskCheckOutcome.INSUFFICIENT_DATA,
                    )
                if entry_distance < minimum_distance:
                    record("MINIMUM_DISTANCE_BREACHED", RiskCheckOutcome.FAILED)
                if entry_distance < thresholds.normal_adverse_displacement:
                    record("NORMAL_DISPLACEMENT_BREACHED", RiskCheckOutcome.FAILED)
                if entry_distance < thresholds.stress_adverse_displacement:
                    record("STRESS_DISPLACEMENT_BREACHED", RiskCheckOutcome.FAILED)
                if stop_clearance < thresholds.minimum_stop_buffer:
                    record("STOP_BUFFER_BREACHED", RiskCheckOutcome.FAILED)
                if (
                    0 < entry_distance <= sizing_request.entry.amount
                    and 0 < stop_clearance <= sizing_request.entry.amount
                ):
                    with localcontext(Context(prec=34, rounding=ROUND_FLOOR)):
                        entry_ratio = entry_distance / sizing_request.entry.amount
                        stop_ratio = stop_clearance / sizing_request.entry.amount
                    if entry_ratio <= 0 or stop_ratio <= 0:
                        entry_ratio = None
                        stop_ratio = None
                        record(
                            "DISTANCE_NOT_REPRESENTABLE",
                            RiskCheckOutcome.INSUFFICIENT_DATA,
                        )

            comparison_available = (
                estimate is not None
                and terms is not None
                and entry_distance is not None
                and stop_clearance is not None
                and leverage.outcome
                not in {
                    RiskCheckOutcome.FAILED,
                    RiskCheckOutcome.INSUFFICIENT_DATA,
                }
                and estimate.as_of >= context.as_of
                and estimate.as_of <= request.evaluated_at
                and estimate.valid_until >= request.evaluated_at
                and estimate.venue == terms.venue
                and estimate.quantity == sizing.recommended_quantity
                and estimate.cost_basis == request.costs
                and estimate.cost_basis is not None
                and estimate.liquidation_price.quote_currency == terms.quote_currency
                and estimate.entry_price.quote_currency == terms.quote_currency
                and estimate.stop_loss.quote_currency == terms.quote_currency
                and request.stop_loss == sizing_request.stop
                and thresholds.quote_currency == terms.quote_currency
                and request.costs.fee_reserve.currency == terms.quote_currency
                and request.costs.funding_reserve.currency == terms.quote_currency
                and 0 < entry_distance <= sizing_request.entry.amount
                and 0 < stop_clearance <= sizing_request.entry.amount
                and estimate.context == context
                and estimate.asset == context.asset
                and estimate.instrument_id == context.instrument_id
                and estimate.side is context.side
                and estimate.margin_mode is leverage_request.margin_mode
                and estimate.entry_price == sizing_request.entry
                and estimate.stop_loss == request.stop_loss
                and estimate.basis_request == leverage_request
                and estimate.account_id == account.account_id
                and estimate.account_snapshot_id == account.snapshot_id
                and estimate.portfolio_snapshot_id == portfolio.snapshot_id
                and estimate.formula_model == "LINEAR"
                and estimate.formula_version is not None
                and estimate.source_id is not None
                and estimate.source_version is not None
                and estimate.source_version.component == estimate.source_id
                and estimate.exchange_constraints is not None
                and thresholds.context == context
                and thresholds.asset == context.asset
                and thresholds.instrument_id == context.instrument_id
                and thresholds.side is context.side
                and thresholds.as_of >= context.as_of
                and thresholds.as_of <= request.evaluated_at
                and thresholds.valid_until >= request.evaluated_at
                and request.costs.version is not None
                and request.costs.as_of >= context.as_of
                and request.costs.as_of <= request.evaluated_at
                and request.costs.valid_until >= request.evaluated_at
                and request.costs.treatment == "ALREADY_INCLUDED_IN_SUPPLIED_ESTIMATE"
            )
            normal_passed = (
                comparison_available
                and entry_distance is not None
                and entry_distance >= normal_minimum
            )
            stress_passed = (
                comparison_available
                and entry_distance is not None
                and entry_distance >= stress_minimum
            )
            volatility_relationship = (
                "entry_distance >= max(minimum_ratio * entry, normal_displacement): "
                f"{'PASSED' if normal_passed else 'FAILED' if comparison_available else 'UNAVAILABLE'}; "
                + (
                    "comparison met."
                    if normal_passed
                    else "comparison breached."
                    if comparison_available
                    else "current comparison evidence unavailable."
                )
            )
            stress_relationship = (
                "entry_distance >= max(minimum_ratio * entry, stress_displacement): "
                f"{'PASSED' if stress_passed else 'FAILED' if comparison_available else 'UNAVAILABLE'}; "
                + (
                    "comparison met."
                    if stress_passed
                    else "comparison breached."
                    if comparison_available
                    else "current comparison evidence unavailable."
                )
            )
            if comparison_available and stop_clearance is not None:
                stop_relationship = (
                    "stop_clearance >= minimum_stop_buffer: "
                    f"{'PASSED' if stop_clearance >= thresholds.minimum_stop_buffer else 'FAILED'}; "
                    + (
                        "comparison met."
                        if stop_clearance >= thresholds.minimum_stop_buffer
                        else "comparison breached."
                    )
                )
            else:
                stop_relationship = (
                    "stop_clearance >= minimum_stop_buffer: UNAVAILABLE; "
                    "current comparison evidence unavailable."
                )
            volatility_relationship += " " + stop_relationship

            outcome = (
                RiskCheckOutcome.FAILED
                if failed
                else RiskCheckOutcome.INSUFFICIENT_DATA
                if insufficient
                else RiskCheckOutcome.WARNING
                if warned
                else RiskCheckOutcome.PASSED
            )
            unusable_codes = {
                "LIQUIDATION_ESTIMATE_MISSING",
                "LIQUIDATION_ESTIMATE_COST_BASIS_MISSING",
                "LIQUIDATION_ESTIMATE_COST_BASIS_MISMATCH",
                "REFERENCE_PROVENANCE_INCOMPLETE",
                "REFERENCE_EXPIRED",
                "SNAPSHOT_REFERENCE_MISMATCH",
                "SNAPSHOT_REFERENCE_PROVENANCE_INCOMPLETE",
                "SNAPSHOT_EXPIRED",
                "SNAPSHOT_FUTURE_DATED",
                "SIZING_INSTRUMENT_MISSING",
                "LIQUIDATION_CURRENCY_MISMATCH",
                "LIQUIDATION_INSTRUMENT_MISMATCH",
                "LIQUIDATION_COST_TREATMENT_UNSUPPORTED",
                "LIQUIDATION_COST_VERSION_MISSING",
                "LIQUIDATION_COST_CURRENCY_MISMATCH",
                "LIQUIDATION_THRESHOLDS_FUTURE_DATED",
                "LIQUIDATION_THRESHOLDS_EXPIRED",
                "LIQUIDATION_COSTS_FUTURE_DATED",
                "LIQUIDATION_COSTS_EXPIRED",
                "LIQUIDATION_THRESHOLDS_STALE",
                "LIQUIDATION_COSTS_STALE",
                "DISTANCE_NOT_REPRESENTABLE",
                "LIQUIDATION_THRESHOLD_BASIS_MISMATCH",
                "LIQUIDATION_ESTIMATE_BASIS_MISMATCH",
                "LIQUIDATION_MARGIN_MODE_MISMATCH",
                "LIQUIDATION_ACCOUNT_MISMATCH",
                "LIQUIDATION_ACCOUNT_SNAPSHOT_MISMATCH",
                "LIQUIDATION_PORTFOLIO_SNAPSHOT_MISMATCH",
                "LIQUIDATION_SOURCE_INSTRUMENT_MISMATCH",
                "LIQUIDATION_SOURCE_IDENTITY_MISMATCH",
                "LIQUIDATION_FORMULA_UNSUPPORTED",
                "LIQUIDATION_FORMULA_OR_SOURCE_DATA_MISSING",
                "LIQUIDATION_ESTIMATE_FUTURE_DATED",
                "LIQUIDATION_ESTIMATE_EXPIRED",
                "LIQUIDATION_ESTIMATE_STALE",
                "LIQUIDATION_PRICE_CURRENCY_MISMATCH",
                "LIQUIDATION_PRICE_BASIS_MISMATCH",
                "LIQUIDATION_STOP_BASIS_MISMATCH",
                "ENTRY_STOP_CURRENCY_MISMATCH",
                "STOP_ON_WRONG_SIDE_OF_ENTRY",
            }
            available = (
                estimate is not None
                and entry_ratio is not None
                and stop_ratio is not None
                and leverage.outcome
                not in {
                    RiskCheckOutcome.FAILED,
                    RiskCheckOutcome.INSUFFICIENT_DATA,
                }
                and not any(code in unusable_codes for code in reasons)
            )
            if not reasons and outcome is not RiskCheckOutcome.PASSED:
                reasons.append("LIQUIDATION_ASSESSMENT_NOT_PASSED")
            model_version = sizing_request.model_version
            valid_until = max(request.evaluated_at, min(expiries))
            result = LiquidationAssessment(
                result_id=request.result_id,
                context=context,
                outcome=outcome,
                reason_codes=tuple(reasons),
                model_version=model_version,
                as_of=context.as_of,
                evaluated_at=request.evaluated_at,
                valid_until=valid_until,
                content_sha256="0" * 64,
                availability=(
                    LiquidationAvailability.AVAILABLE
                    if available
                    else LiquidationAvailability.UNAVAILABLE
                ),
                margin_mode=leverage_request.margin_mode,
                entry_price=sizing_request.entry,
                stop_loss=request.stop_loss,
                liquidation_price=(
                    estimate.liquidation_price
                    if available and estimate is not None
                    else None
                ),
                entry_to_liquidation=(
                    RatioValue(entry_ratio, "entry-distance/entry")
                    if available and entry_ratio is not None
                    else None
                ),
                stop_to_liquidation=(
                    RatioValue(stop_ratio, "stop-clearance/entry")
                    if available and stop_ratio is not None
                    else None
                ),
                minimum_distance=RatioValue(
                    thresholds.minimum_entry_distance_ratio,
                    "minimum-entry-distance/entry",
                ),
                volatility_relationship=volatility_relationship,
                stress_relationship=stress_relationship,
                formula_version=estimate.formula_version if estimate else None,
                exchange_constraints=estimate.exchange_constraints
                if estimate
                else None,
            )
            return replace(
                result,
                content_sha256=_risk_digest(
                    "liquidation assessment",
                    {
                        "request": request,
                        "leverage_assessment": leverage,
                        "result": {
                            item.name: getattr(result, item.name)
                            for item in fields(result)
                            if item.name != "content_sha256"
                        },
                    },
                ),
            )
    except DecimalException as exc:
        raise RiskContractError(
            "liquidation arithmetic cannot be represented safely at precision 34."
        ) from exc


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
        "cost_assumptions": (request.costs.version,),
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
    supported_schemas = (
        {"1", "2"} if expected_contract_id in {"C-021", "C-028", "C-070"} else {"1"}
    )
    if (
        reference.schema_version not in supported_schemas
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
    snapshots: tuple[AccountSnapshot | PortfolioSnapshot | PositionSnapshot, ...] = (
        account,
        portfolio,
        *portfolio.positions,
    )
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
        and request.price_unit_currency == currency
        and (request.stop_loss is None or request.stop_loss.quote_currency == currency)
    )
    cost_units_valid = all(
        value.currency == currency
        for value in (costs.fee, costs.slippage, costs.funding)
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
    if request.entry_price.quote_currency != currency:
        fail("ENTRY_CURRENCY_MISMATCH")
    if request.price_unit_currency != currency:
        fail("PRICE_DISTANCE_CURRENCY_MISMATCH")
    if request.effective_maximum_loss.currency != currency:
        fail("BUDGET_CURRENCY_MISMATCH")
    if costs.fee.currency != currency or costs.slippage.currency != currency:
        fail("COST_CURRENCY_MISMATCH")
    if costs.funding.currency != currency:
        fail("FUNDING_CURRENCY_MISMATCH")
    if any(value.amount < 0 for value in (costs.fee, costs.slippage, costs.funding)):
        fail("NEGATIVE_ADVERSE_COST")
    if request.stop_loss is not None and request.stop_loss.quote_currency != currency:
        fail("STOP_CURRENCY_MISMATCH")
    if request.entry_price.amount % instrument.tick_size != 0:
        fail("ENTRY_PRICE_TICK_MISMATCH")
    if request.quantity % instrument.quantity_step != 0:
        fail("QUANTITY_STEP_MISMATCH")
    if (
        not instrument.minimum_quantity
        <= request.quantity
        <= instrument.maximum_quantity
    ):
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
            if stop_distance > request.entry_price.amount:
                stop_distance_ratio = None
                fail("STOP_DISTANCE_RATIO_UNREPRESENTABLE")
            else:
                with localcontext(
                    Context(prec=34, rounding=ROUND_HALF_EVEN)
                ) as ratio_context:
                    ratio_context.traps[Inexact] = False
                    distance_ratio = stop_distance / request.entry_price.amount
                stop_distance_ratio = RatioValue(
                    distance_ratio, "stop-distance-to-entry"
                )
            with localcontext(Context(prec=34, rounding=ROUND_HALF_EVEN)) as exact:
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
                if (
                    instrument_lineage_valid
                    and cost_units_valid
                    and not any(
                        value.amount < 0
                        for value in (costs.fee, costs.slippage, costs.funding)
                    )
                ):
                    unit_loss = (
                        (stop_distance + request.adverse_gap_displacement)
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
            budget_passed = maximum_loss.amount <= request.effective_maximum_loss.amount
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
        elif structural.as_of > evaluated_at or structural.valid_until < evaluated_at:
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
        elif volatility.as_of > evaluated_at or volatility.valid_until < evaluated_at:
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
        elif liquidation.as_of > evaluated_at or liquidation.valid_until < evaluated_at:
            insufficient("LIQUIDATION_EVIDENCE_NOT_CURRENT")
        elif liquidation.quote_currency != currency or (
            liquidation.liquidation_price is not None
            and liquidation.liquidation_price.quote_currency != currency
        ):
            liquidation_check = RiskCheckOutcome.FAILED
            fail("LIQUIDATION_CURRENCY_MISMATCH")
        elif liquidation.availability is LiquidationAvailability.NOT_APPLICABLE:
            if liquidation.liquidation_price is not None:
                liquidation_check = RiskCheckOutcome.FAILED
                fail("LIQUIDATION_APPLICABILITY_CONFLICT")
            elif liquidation.fully_funded_spot:
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
            "stop assessment arithmetic cannot be represented safely at precision 34."
        ) from exc


@dataclass(frozen=True, slots=True)
class TakeProfitTargetBound:
    """Current, priced strategy invalidation bounds for one target."""

    sequence: int
    context: RiskContext
    strategy_version: ContractReference
    strategy_invalidation: ContractReference
    asset: str
    instrument_id: str
    side: PositionSide
    lower_price: PriceValue
    upper_price: PriceValue
    version: VersionReference
    as_of: datetime
    valid_until: datetime

    def __post_init__(self) -> None:
        _positive_int("sequence", self.sequence)
        if not isinstance(self.context, RiskContext):
            raise RiskContractError("context must be a RiskContext.")
        if (
            not isinstance(self.strategy_version, ContractReference)
            or self.strategy_version.contract_id != "C-021"
        ):
            raise RiskContractError("strategy_version must reference C-021.")
        if (
            not isinstance(self.strategy_invalidation, ContractReference)
            or self.strategy_invalidation.contract_id != "C-023"
        ):
            raise RiskContractError("strategy_invalidation must reference C-023.")
        _text("asset", self.asset)
        _text("instrument_id", self.instrument_id)
        if not isinstance(self.side, PositionSide):
            raise RiskContractError("side must be a PositionSide.")
        for name in ("lower_price", "upper_price"):
            if not isinstance(getattr(self, name), PriceValue):
                raise RiskContractError(f"{name} must be a PriceValue.")
        if (
            self.lower_price.quote_currency != self.upper_price.quote_currency
            or self.lower_price.amount > self.upper_price.amount
        ):
            raise RiskContractError("target price bounds are invalid.")
        if not isinstance(self.version, VersionReference):
            raise RiskContractError("version must be a VersionReference.")
        as_of = _time("as_of", self.as_of)
        valid_until = _time("valid_until", self.valid_until)
        _ordered("as_of", as_of, "valid_until", valid_until)
        object.__setattr__(self, "as_of", as_of)
        object.__setattr__(self, "valid_until", valid_until)


@dataclass(frozen=True, slots=True)
class TakeProfitAssessmentRequest:
    """Explicit offline inputs for a bounded C-079 target assessment."""

    result_id: UUID
    context: RiskContext
    entry_price: PriceValue
    stop_loss_request: StopLossAssessmentRequest
    sizing_result: PositionSizingResult
    targets: tuple[TakeProfitTarget, ...]
    target_bounds: tuple[TakeProfitTargetBound, ...]
    target_costs: tuple[SizingCosts, ...]
    minimum_risk_reward: Decimal
    minimum_risk_reward_version: VersionReference
    assumptions_version: VersionReference
    model_version: VersionReference
    evaluated_at: datetime
    assumptions_as_of: datetime
    assumptions_valid_until: datetime

    def __post_init__(self) -> None:
        _uuid("result_id", self.result_id)
        if not isinstance(self.context, RiskContext):
            raise RiskContractError("context must be a RiskContext.")
        if not isinstance(self.entry_price, PriceValue):
            raise RiskContractError("entry_price must be a PriceValue.")
        if not isinstance(self.stop_loss_request, StopLossAssessmentRequest):
            raise RiskContractError(
                "stop_loss_request must be a StopLossAssessmentRequest."
            )
        if not isinstance(self.sizing_result, PositionSizingResult):
            raise RiskContractError("sizing_result must be a PositionSizingResult.")
        targets = _typed_tuple("targets", self.targets, TakeProfitTarget, empty=False)
        if any(target.expected_profit is not None for target in targets):
            raise RiskContractError("target expected_profit must be unset on input.")
        bounds = _typed_tuple(
            "target_bounds", self.target_bounds, TakeProfitTargetBound, empty=False
        )
        costs = _typed_tuple(
            "target_costs", self.target_costs, SizingCosts, empty=False
        )
        sequences = tuple(target.sequence for target in targets)
        if sequences != tuple(sorted(sequences)) or len(set(sequences)) != len(
            sequences
        ):
            raise RiskContractError("targets must have unique ascending sequences.")
        if tuple(bound.sequence for bound in bounds) != sequences:
            raise RiskContractError("target bounds must match target sequences.")
        if len(costs) != len(targets):
            raise RiskContractError("each target requires explicit versioned costs.")
        try:
            with localcontext(Context(prec=34, rounding=ROUND_HALF_EVEN)) as context:
                context.traps[Inexact] = True
                allocation_total = sum(
                    (target.allocation.value for target in targets), Decimal("0")
                )
        except DecimalException as exc:
            raise RiskContractError(
                "target allocations cannot be represented exactly at precision 34."
            ) from exc
        if allocation_total != 1:
            raise RiskContractError("target allocations must sum exactly to 1.")
        if any(
            (
                self.context.side is PositionSide.LONG
                and target.price.amount <= self.entry_price.amount
            )
            or (
                self.context.side is PositionSide.SHORT
                and target.price.amount >= self.entry_price.amount
            )
            for target in targets
        ):
            raise RiskContractError("take-profit target is on the wrong side of entry.")
        _positive("minimum_risk_reward", self.minimum_risk_reward)
        for name in (
            "minimum_risk_reward_version",
            "assumptions_version",
            "model_version",
        ):
            if not isinstance(getattr(self, name), VersionReference):
                raise RiskContractError(f"{name} must be a VersionReference.")
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


def _take_profit_assessment_result(
    request: TakeProfitAssessmentRequest,
    *,
    outcome: RiskCheckOutcome,
    reason_codes: tuple[str, ...],
    valid_until: datetime,
    targets: tuple[TakeProfitTarget, ...],
    expected_profit: MoneyValue | None,
    risk_reward_ratio: Decimal | None,
    strategy_consistency: RiskCheckOutcome,
    invalidation_consistency: RiskCheckOutcome,
    assumptions: tuple[VersionReference, ...],
) -> TakeProfitAssessment:
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
        "targets": targets,
        "expected_profit": expected_profit,
        "risk_reward_ratio": risk_reward_ratio,
        "strategy_consistency": strategy_consistency,
        "invalidation_consistency": invalidation_consistency,
        "assumptions": assumptions,
        "contract_id": "C-079",
        "schema_version": CONTRACT_SCHEMA_VERSION,
    }
    digest = _risk_digest(
        "take-profit assessment",
        {"request": request, "result": result_fields},
    )
    assessment_fields = {
        key: value
        for key, value in result_fields.items()
        if key not in {"contract_id", "schema_version"}
    }
    return TakeProfitAssessment(
        **{
            **assessment_fields,
            "content_sha256": digest,
        }  # type: ignore[arg-type]
    )


def _calculate_take_profit_assessment(
    request: TakeProfitAssessmentRequest,
) -> TakeProfitAssessment:
    if not isinstance(request, TakeProfitAssessmentRequest):
        raise RiskContractError("request must be a TakeProfitAssessmentRequest.")

    evaluated_at = request.evaluated_at
    stop_request = request.stop_loss_request
    sizing = request.sizing_result
    terms = stop_request.instrument
    reasons: list[str] = []
    hard_failure = False
    insufficient = False
    warning = False
    strategy_check = RiskCheckOutcome.PASSED
    invalidation_check = RiskCheckOutcome.PASSED

    def fail(code: str, *, invalidation: bool = False) -> None:
        nonlocal hard_failure, strategy_check, invalidation_check
        hard_failure = True
        reasons.append(code)
        if invalidation:
            invalidation_check = RiskCheckOutcome.FAILED
        else:
            strategy_check = RiskCheckOutcome.FAILED

    def missing(code: str, *, invalidation: bool = False) -> None:
        nonlocal insufficient, strategy_check, invalidation_check
        insufficient = True
        reasons.append(code)
        if invalidation:
            invalidation_check = RiskCheckOutcome.INSUFFICIENT_DATA
        else:
            strategy_check = RiskCheckOutcome.INSUFFICIENT_DATA

    if (
        request.assumptions_as_of > evaluated_at
        or request.assumptions_valid_until < evaluated_at
    ):
        missing("ASSUMPTIONS_NOT_CURRENT")
    expiries = [request.assumptions_valid_until]
    context_references = (
        (request.context.signal, "C-070"),
        (request.context.validation, "C-028"),
        (request.context.strategy_version, "C-021"),
        (request.context.account_snapshot, "C-032"),
        (request.context.portfolio_snapshot, "C-033"),
        (stop_request.strategy_invalidation, "C-023"),
    )
    for reference, contract_id in context_references:
        is_invalidation = contract_id == "C-023"
        status, code = _stop_reference_status(reference, contract_id, evaluated_at)
        if status is RiskCheckOutcome.FAILED:
            fail(
                code or "REFERENCE_CONTRACT_MISMATCH",
                invalidation=is_invalidation,
            )
        elif status is RiskCheckOutcome.INSUFFICIENT_DATA:
            missing(
                code or "REFERENCE_PROVENANCE_INCOMPLETE",
                invalidation=is_invalidation,
            )
        if reference.valid_until is not None:
            expiries.append(reference.valid_until)

    if request.context != stop_request.context:
        fail("STOP_CONTEXT_MISMATCH")
    if (
        request.entry_price != stop_request.entry_price
        or request.entry_price.quote_currency != stop_request.instrument.quote_currency
    ):
        fail("STOP_ENTRY_MISMATCH")
    if stop_request.evaluated_at != evaluated_at:
        fail("STOP_EVALUATION_TIME_MISMATCH")
    if (
        stop_request.assumptions_as_of > evaluated_at
        or stop_request.assumptions_valid_until < evaluated_at
    ):
        missing("STOP_ASSUMPTIONS_NOT_CURRENT")
    if sizing.contract_id != "C-036" or sizing.schema_version != "1":
        missing("SIZING_SCHEMA_UNSUPPORTED")
    if sizing.context != request.context:
        fail("SIZING_CONTEXT_MISMATCH")
    if sizing.outcome is RiskCheckOutcome.FAILED:
        fail("SIZING_FAILED")
    elif sizing.outcome is RiskCheckOutcome.INSUFFICIENT_DATA:
        missing("SIZING_INSUFFICIENT_DATA")
    elif sizing.outcome not in {
        RiskCheckOutcome.PASSED,
        RiskCheckOutcome.WARNING,
    }:
        missing("SIZING_NOT_PASSING")
    if (
        sizing.as_of > evaluated_at
        or sizing.evaluated_at > evaluated_at
        or sizing.valid_until < evaluated_at
    ):
        missing("SIZING_NOT_CURRENT")
    expiries.append(sizing.valid_until)

    # C-036 is caller-supplied evidence; validate its backed outputs even when
    # WARNING is legitimate, since that constructor allows incomplete warnings.
    sizing_money = (
        sizing.requested_risk,
        sizing.requested_notional,
        sizing.recommended_notional,
        sizing.recommended_margin,
        sizing.maximum_loss,
    )
    if any(
        value is not None and value.currency != terms.quote_currency
        for value in sizing_money
    ):
        fail("SIZING_CURRENCY_MISMATCH")
    if any(
        value is None
        for value in (
            sizing.recommended_notional,
            sizing.recommended_margin,
            sizing.maximum_loss,
            sizing.minimum_quantity,
            sizing.maximum_quantity,
            sizing.quantity_step,
        )
    ):
        missing("SIZING_BOUNDED_OUTPUTS_UNAVAILABLE")
    if any(
        supplied is not None and supplied != expected
        for supplied, expected in (
            (sizing.minimum_quantity, terms.minimum_quantity),
            (sizing.maximum_quantity, terms.maximum_quantity),
            (sizing.quantity_step, terms.quantity_step),
        )
    ):
        fail("SIZING_BOUNDS_MISMATCH")
    sized_quantity = sizing.recommended_quantity
    if sized_quantity is not None:
        if not terms.minimum_quantity <= sized_quantity <= terms.maximum_quantity:
            fail("SIZING_QUANTITY_OUT_OF_BOUNDS")
        if sized_quantity % terms.quantity_step != 0:
            fail("SIZING_QUANTITY_STEP_MISMATCH")
        expected_notional = (
            request.entry_price.amount * terms.contract_multiplier * sized_quantity
        )
        if sizing.recommended_notional is not None and (
            sizing.recommended_notional.amount != expected_notional
            or sizing.recommended_notional.amount > terms.maximum_notional.amount
        ):
            fail("SIZING_NOTIONAL_MISMATCH")
        expected_margin = terms.initial_margin_per_unit.amount * sized_quantity
        free_margin = stop_request.account.free_margin
        if sizing.recommended_margin is not None:
            if sizing.recommended_margin.amount != expected_margin:
                fail("SIZING_MARGIN_MISMATCH")
            if free_margin is None:
                missing("SIZING_FREE_MARGIN_UNAVAILABLE")
            elif (
                free_margin.currency != terms.quote_currency
                or sizing.recommended_margin.amount > free_margin.amount
            ):
                fail("SIZING_MARGIN_UNAVAILABLE")
    if (
        sizing.maximum_loss is not None
        and sizing.maximum_loss.amount > sizing.requested_risk.amount
    ):
        fail("SIZING_RISK_BUDGET_EXCEEDED")

    stop_assessment = calculate_stop_loss_assessment(stop_request)
    if stop_assessment.outcome is RiskCheckOutcome.FAILED:
        fail("STOP_ASSESSMENT_FAILED")
    elif stop_assessment.outcome is RiskCheckOutcome.INSUFFICIENT_DATA:
        missing("STOP_ASSESSMENT_INSUFFICIENT_DATA")
    elif stop_assessment.outcome is RiskCheckOutcome.WARNING:
        warning = True
        reasons.extend(stop_assessment.reason_codes)
    if stop_assessment.context != request.context:
        fail("STOP_ASSESSMENT_CONTEXT_MISMATCH")
    if (
        stop_assessment.entry_price != request.entry_price
        or stop_assessment.side is not request.context.side
    ):
        fail("STOP_ASSESSMENT_TRADE_MISMATCH")
    expiries.append(stop_assessment.valid_until)
    if stop_assessment.outcome in {
        RiskCheckOutcome.PASSED,
        RiskCheckOutcome.WARNING,
    }:
        if (
            sizing.recommended_quantity is None
            or sizing.recommended_quantity != stop_request.quantity
        ):
            fail("SIZING_QUANTITY_MISMATCH")
        if sizing.stop_distance is None or (
            stop_assessment.stop_distance is not None
            and sizing.stop_distance != stop_assessment.stop_distance
        ):
            fail("SIZING_STOP_DISTANCE_MISMATCH")
        if (
            terms.version not in sizing.sizing_assumptions
            or stop_request.costs.version not in sizing.sizing_assumptions
        ):
            fail("SIZING_ASSUMPTIONS_MISMATCH")
        if sizing.maximum_loss is None or stop_assessment.maximum_loss is None:
            fail("SIZING_MAXIMUM_LOSS_MISMATCH")
        else:
            gap_loss = (
                stop_request.adverse_gap_displacement
                * terms.contract_multiplier
                * stop_request.quantity
            )
            if (
                sizing.maximum_loss.amount + gap_loss
                != stop_assessment.maximum_loss.amount
            ):
                fail("SIZING_MAXIMUM_LOSS_MISMATCH")
    if sizing.outcome is RiskCheckOutcome.WARNING:
        warning = True
        reasons.extend(sizing.reason_codes)
    if any(
        item.severity is RiskLimitSeverity.SOFT
        and item.outcome is RiskCheckOutcome.WARNING
        for item in stop_assessment.limits
    ):
        warning = True
        reasons.extend(
            item.reason
            for item in stop_assessment.limits
            if item.severity is RiskLimitSeverity.SOFT
            and item.outcome is RiskCheckOutcome.WARNING
        )

    if terms.asset != request.context.asset or (
        terms.instrument_id != request.context.instrument_id
    ):
        fail("INSTRUMENT_LINEAGE_MISMATCH")
    if terms.model != "LINEAR":
        fail("UNSUPPORTED_INSTRUMENT_MODEL")
    if request.entry_price.quote_currency != terms.quote_currency:
        fail("ENTRY_CURRENCY_MISMATCH")
    quantity = sizing.recommended_quantity
    if quantity is None:
        missing("SIZING_QUANTITY_UNAVAILABLE")

    for bound in request.target_bounds:
        expiries.append(bound.valid_until)
        if bound.context != request.context:
            fail("TARGET_BOUND_CONTEXT_MISMATCH")
        if bound.strategy_version != request.context.strategy_version:
            fail("TARGET_BOUND_STRATEGY_MISMATCH")
        if bound.strategy_invalidation != stop_request.strategy_invalidation:
            fail("TARGET_BOUND_INVALIDATION_MISMATCH", invalidation=True)
        if (
            bound.asset != request.context.asset
            or bound.instrument_id != request.context.instrument_id
            or bound.side is not request.context.side
        ):
            fail("TARGET_BOUND_INSTRUMENT_OR_SIDE_MISMATCH")
        if bound.as_of > evaluated_at or bound.valid_until < evaluated_at:
            missing("TARGET_BOUND_NOT_CURRENT")
        bound_status, bound_code = _stop_reference_status(
            bound.strategy_version, "C-021", evaluated_at
        )
        if bound_status is RiskCheckOutcome.FAILED:
            fail(bound_code or "TARGET_STRATEGY_REFERENCE_MISMATCH")
        elif bound_status is RiskCheckOutcome.INSUFFICIENT_DATA:
            missing(bound_code or "TARGET_STRATEGY_REFERENCE_INCOMPLETE")
        invalidation_status, invalidation_code = _stop_reference_status(
            bound.strategy_invalidation, "C-023", evaluated_at
        )
        if invalidation_status is RiskCheckOutcome.FAILED:
            fail(
                invalidation_code or "TARGET_INVALIDATION_REFERENCE_MISMATCH",
                invalidation=True,
            )
        elif invalidation_status is RiskCheckOutcome.INSUFFICIENT_DATA:
            missing(
                invalidation_code or "TARGET_INVALIDATION_REFERENCE_INCOMPLETE",
                invalidation=True,
            )

    if any(
        target.price.quote_currency != terms.quote_currency
        for target in request.targets
    ):
        fail("TARGET_CURRENCY_MISMATCH")
    if any(target.price.amount % terms.tick_size != 0 for target in request.targets):
        fail("TARGET_PRICE_TICK_MISMATCH")
    if any(
        (
            request.context.side is PositionSide.LONG
            and earlier.price.amount >= later.price.amount
        )
        or (
            request.context.side is PositionSide.SHORT
            and earlier.price.amount <= later.price.amount
        )
        for earlier, later in zip(request.targets, request.targets[1:])
    ):
        fail("TARGET_PRICES_NOT_PROGRESSIVE")

    computed_targets: list[TakeProfitTarget] = []
    total_profit = Decimal("0")
    profit_available = quantity is not None
    for target, costs, bound in zip(
        request.targets, request.target_costs, request.target_bounds, strict=True
    ):
        if not (
            bound.lower_price.quote_currency
            == bound.upper_price.quote_currency
            == target.price.quote_currency
            == terms.quote_currency
        ):
            fail("TARGET_BOUND_CURRENCY_MISMATCH", invalidation=True)
        elif not (
            bound.lower_price.amount <= target.price.amount <= bound.upper_price.amount
        ):
            fail("TARGET_OUTSIDE_STRATEGY_BOUND", invalidation=True)
        if any(
            value.currency != terms.quote_currency
            for value in (costs.fee, costs.slippage, costs.funding)
        ):
            fail("TARGET_COST_CURRENCY_MISMATCH")
        target_profit: Decimal | None = None
        if quantity is not None and stop_request.stop_loss is not None:
            allocated_quantity = quantity * target.allocation.value
            if allocated_quantity % terms.quantity_step != 0:
                fail("TARGET_QUANTITY_STEP_MISMATCH")
            if not (
                terms.minimum_quantity <= allocated_quantity <= terms.maximum_quantity
            ):
                fail("TARGET_QUANTITY_OUT_OF_BOUNDS")
            directional_move = (
                target.price.amount - request.entry_price.amount
                if request.context.side is PositionSide.LONG
                else request.entry_price.amount - target.price.amount
            )
            gross_profit = (
                directional_move * terms.contract_multiplier * allocated_quantity
            )
            cost_per_unit = (
                costs.fee.amount + costs.slippage.amount + costs.funding.amount
            )
            target_profit = gross_profit - cost_per_unit * allocated_quantity
            if target_profit <= 0:
                fail("TARGET_COSTS_EXCEED_DIRECTIONAL_PROFIT")
                target_profit = None
                profit_available = False
            else:
                total_profit += target_profit
        else:
            profit_available = False
        computed_targets.append(
            replace(
                target,
                expected_profit=(
                    MoneyValue(target_profit, terms.quote_currency)
                    if target_profit is not None
                    else None
                ),
            )
        )

    expected_profit: MoneyValue | None = None
    risk_reward_ratio: Decimal | None = None
    maximum_loss = stop_assessment.maximum_loss
    if (
        profit_available
        and maximum_loss is not None
        and maximum_loss.amount > 0
        and total_profit > 0
    ):
        expected_profit = MoneyValue(total_profit, terms.quote_currency)
        if total_profit < request.minimum_risk_reward * maximum_loss.amount:
            fail("MINIMUM_RISK_REWARD_NOT_MET")
        with localcontext(Context(prec=34, rounding=ROUND_FLOOR)):
            risk_reward_ratio = total_profit / maximum_loss.amount
    else:
        missing("RISK_REWARD_INPUTS_UNAVAILABLE")

    assumptions = tuple(
        dict.fromkeys(
            (
                request.assumptions_version,
                request.minimum_risk_reward_version,
                request.model_version,
                stop_request.model_version,
                stop_request.policy_version,
                stop_request.configuration_version,
                stop_request.gap_version,
                stop_request.instrument.version,
                stop_request.costs.version,
                sizing.model_version,
                *sizing.sizing_assumptions,
                *(cost.version for cost in request.target_costs),
                *(bound.version for bound in request.target_bounds),
            )
        )
    )
    valid_until = min(expiries)
    if valid_until < evaluated_at:
        valid_until = evaluated_at
        insufficient = True
        reasons.append("ASSESSMENT_EVIDENCE_EXPIRED")
    if hard_failure:
        outcome = RiskCheckOutcome.FAILED
    elif insufficient:
        outcome = RiskCheckOutcome.INSUFFICIENT_DATA
    elif warning:
        outcome = RiskCheckOutcome.WARNING
        if not reasons:
            reasons.append("UPSTREAM_WARNING")
    else:
        outcome = RiskCheckOutcome.PASSED
    if outcome is not RiskCheckOutcome.PASSED and not reasons:
        reasons.append("TAKE_PROFIT_ASSESSMENT_INCOMPLETE")
    if outcome is RiskCheckOutcome.INSUFFICIENT_DATA:
        expected_profit = None
        risk_reward_ratio = None
        computed_targets = [
            replace(target, expected_profit=None) for target in request.targets
        ]
    return _take_profit_assessment_result(
        request,
        outcome=outcome,
        reason_codes=tuple(dict.fromkeys(reasons)),
        valid_until=valid_until,
        targets=tuple(computed_targets),
        expected_profit=expected_profit,
        risk_reward_ratio=risk_reward_ratio,
        strategy_consistency=strategy_check,
        invalidation_consistency=invalidation_check,
        assumptions=assumptions,
    )


def calculate_take_profit_assessment(
    request: TakeProfitAssessmentRequest,
) -> TakeProfitAssessment:
    """Assess explicit take-profit inputs offline; grants no trade authority."""
    try:
        with localcontext(
            Context(prec=34, rounding=ROUND_HALF_EVEN)
        ) as decimal_context:
            decimal_context.traps[Inexact] = True
            return _calculate_take_profit_assessment(request)
    except DecimalException as exc:
        raise RiskContractError(
            "take-profit arithmetic cannot be represented safely at precision 34."
        ) from exc


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
class PortfolioImpactBasis:
    leverage_request: LeverageAssessmentRequest
    stop_request: StopLossAssessmentRequest

    def __post_init__(self) -> None:
        if not isinstance(self.leverage_request, LeverageAssessmentRequest):
            raise RiskContractError(
                "leverage_request must be LeverageAssessmentRequest."
            )
        if not isinstance(self.stop_request, StopLossAssessmentRequest):
            raise RiskContractError("stop_request must be StopLossAssessmentRequest.")


@dataclass(frozen=True, slots=True)
class _PortfolioEvidence:
    basis: PortfolioImpactBasis
    version: VersionReference
    as_of: datetime
    valid_until: datetime

    def __post_init__(self) -> None:
        if not isinstance(self.basis, PortfolioImpactBasis):
            raise RiskContractError("basis must be PortfolioImpactBasis.")
        if not isinstance(self.version, VersionReference):
            raise RiskContractError("version must be VersionReference.")
        start, end = _time("as_of", self.as_of), _time("valid_until", self.valid_until)
        _ordered("as_of", start, "valid_until", end)
        object.__setattr__(self, "as_of", start)
        object.__setattr__(self, "valid_until", end)


def portfolio_group_key(value: ContractReference | VersionReference) -> str:
    """Version-qualified group identity; reference expiry is not strategy identity."""
    if isinstance(value, ContractReference):
        return _risk_digest(
            "portfolio group",
            {
                "contract_id": value.contract_id,
                "entity_id": value.entity_id,
                "schema_version": value.schema_version,
                "content_sha256": value.content_sha256,
            },
        )
    if isinstance(value, VersionReference):
        return _risk_digest("portfolio group", value)
    raise RiskContractError("group identity requires a version-qualified reference.")


@dataclass(frozen=True, slots=True)
class PortfolioPositionEvidence(_PortfolioEvidence):
    position: PositionSnapshot | None
    venue: str
    strategy_version: ContractReference
    regime: VersionReference
    correlation_groups: tuple[str, ...]
    open_risk: MoneyValue

    def __post_init__(self) -> None:
        _PortfolioEvidence.__post_init__(self)
        if self.position is not None and not isinstance(
            self.position, PositionSnapshot
        ):
            raise RiskContractError(
                "position must be PositionSnapshot or None for proposal."
            )
        _text("venue", self.venue)
        if not isinstance(self.strategy_version, ContractReference):
            raise RiskContractError("strategy_version must be ContractReference.")
        if self.strategy_version.contract_id != "C-021":
            raise RiskContractError("strategy_version must reference C-021.")
        if not isinstance(self.regime, VersionReference):
            raise RiskContractError("regime must be VersionReference.")
        groups = _text_tuple("correlation_groups", self.correlation_groups)
        _unique("correlation groups", groups)
        _money("open_risk", self.open_risk)


@dataclass(frozen=True, slots=True)
class PortfolioCorrelationScenario(_PortfolioEvidence):
    group_id: str
    instruments: tuple[str, ...]
    methodology: str

    def __post_init__(self) -> None:
        _PortfolioEvidence.__post_init__(self)
        _text("group_id", self.group_id)
        values = _text_tuple("instruments", self.instruments)
        if not values:
            raise RiskContractError("scenario instruments must not be empty.")
        _unique("scenario instruments", values)
        _text("methodology", self.methodology)


@dataclass(frozen=True, slots=True)
class PortfolioLiquidityEvidence(_PortfolioEvidence):
    venue: str
    instrument_id: str
    capacity: MoneyValue
    assumptions: str

    def __post_init__(self) -> None:
        _PortfolioEvidence.__post_init__(self)
        _text("venue", self.venue)
        _text("instrument_id", self.instrument_id)
        _money("capacity", self.capacity)
        _text("assumptions", self.assumptions)


@dataclass(frozen=True, slots=True)
class PortfolioConcentrationLimit:
    dimension: str
    key: str
    maximum: Decimal

    def __post_init__(self) -> None:
        if self.dimension not in {"asset", "strategy", "regime", "correlation"}:
            raise RiskContractError("unsupported concentration dimension.")
        _text("key", self.key)
        _nonnegative("maximum", self.maximum)
        if self.maximum > 1:
            raise RiskContractError("concentration cap must be in [0, 1].")


@dataclass(frozen=True, slots=True)
class PortfolioImpactPolicy(_PortfolioEvidence):
    configuration_version: VersionReference
    maximum_gross: MoneyValue
    maximum_absolute_net: MoneyValue
    maximum_gross_leverage: Decimal
    maximum_drawdown: Decimal
    maximum_margin_utilization: Decimal
    minimum_free_margin: MoneyValue
    total_risk_budget: MoneyValue
    concentration_limits: tuple[PortfolioConcentrationLimit, ...]

    def __post_init__(self) -> None:
        _PortfolioEvidence.__post_init__(self)
        if not isinstance(self.configuration_version, VersionReference):
            raise RiskContractError("configuration_version must be VersionReference.")
        for name in (
            "maximum_gross",
            "maximum_absolute_net",
            "minimum_free_margin",
            "total_risk_budget",
        ):
            _money(name, getattr(self, name))
        _positive("maximum_gross_leverage", self.maximum_gross_leverage)
        for name in ("maximum_drawdown", "maximum_margin_utilization"):
            _nonnegative(name, getattr(self, name))
            if getattr(self, name) > 1:
                raise RiskContractError(f"{name} must be in [0, 1].")
        caps = _typed_tuple(
            "concentration_limits",
            self.concentration_limits,
            PortfolioConcentrationLimit,
        )
        _unique(
            "concentration limit identities", tuple((x.dimension, x.key) for x in caps)
        )


@dataclass(frozen=True, slots=True)
class PortfolioImpactRequest:
    result_id: UUID
    evaluated_at: datetime
    basis: PortfolioImpactBasis
    positions: tuple[PortfolioPositionEvidence, ...]
    proposal: PortfolioPositionEvidence
    scenarios: tuple[PortfolioCorrelationScenario, ...]
    liquidity: tuple[PortfolioLiquidityEvidence, ...]
    policy: PortfolioImpactPolicy | None

    def __post_init__(self) -> None:
        _uuid("result_id", self.result_id)
        when = _time("evaluated_at", self.evaluated_at)
        if not isinstance(self.basis, PortfolioImpactBasis):
            raise RiskContractError("basis must be PortfolioImpactBasis.")
        if (
            when != self.basis.leverage_request.evaluated_at
            or when != self.basis.stop_request.evaluated_at
        ):
            raise RiskContractError("portfolio evaluation times must match.")
        _typed_tuple("positions", self.positions, PortfolioPositionEvidence)
        if (
            not isinstance(self.proposal, PortfolioPositionEvidence)
            or self.proposal.position is not None
        ):
            raise RiskContractError(
                "proposal requires position-free PortfolioPositionEvidence."
            )
        _typed_tuple("scenarios", self.scenarios, PortfolioCorrelationScenario)
        _typed_tuple("liquidity", self.liquidity, PortfolioLiquidityEvidence)
        _unique("scenario identities", tuple(x.group_id for x in self.scenarios))
        _unique(
            "liquidity identities",
            tuple((x.venue, x.instrument_id) for x in self.liquidity),
        )
        if self.policy is not None and not isinstance(
            self.policy, PortfolioImpactPolicy
        ):
            raise RiskContractError("policy must be PortfolioImpactPolicy or None.")
        object.__setattr__(self, "evaluated_at", when)


def calculate_portfolio_impact(request: PortfolioImpactRequest) -> PortfolioImpact:
    """Static offline opening-position projection; no source or trading authority."""
    if not isinstance(request, PortfolioImpactRequest):
        raise RiskContractError("request must be PortfolioImpactRequest.")
    try:
        with localcontext(Context(prec=34, rounding=ROUND_HALF_EVEN)) as arithmetic:
            arithmetic.traps[Inexact] = True
            return _calculate_portfolio_impact(request)
    except DecimalException as exc:
        raise RiskContractError(
            "portfolio arithmetic cannot be represented exactly at precision 34."
        ) from exc


def _calculate_portfolio_impact(request: PortfolioImpactRequest) -> PortfolioImpact:
    basis = request.basis
    leverage_request, stop_request = basis.leverage_request, basis.stop_request
    sizing_request = leverage_request.sizing_request
    account, portfolio, context = (
        sizing_request.account,
        sizing_request.portfolio,
        sizing_request.context,
    )
    terms = sizing_request.instrument
    sizing = calculate_position_size(sizing_request)
    leverage = calculate_leverage_assessment(leverage_request)
    stop = calculate_stop_loss_assessment(stop_request)
    if terms is None or any(
        x is None
        for x in (
            sizing.recommended_quantity,
            sizing.recommended_notional,
            sizing.recommended_margin,
            stop.maximum_loss,
            account.equity,
            account.used_margin,
            account.free_margin,
            portfolio.pending_risk,
            portfolio.drawdown,
        )
    ):
        raise RiskContractError(
            "PORTFOLIO_ESSENTIAL_EVIDENCE_MISSING: cannot form truthful C-080 buckets."
        )
    if (
        stop_request.context != context
        or stop_request.account != account
        or stop_request.portfolio != portfolio
        or stop_request.entry_price != sizing_request.entry
        or stop_request.stop_loss != sizing_request.stop
        or stop_request.quantity != sizing.recommended_quantity
        or stop_request.instrument != terms
        or stop_request.costs != sizing_request.costs
        or stop_request.policy_version != sizing_request.policy_version
        or stop_request.configuration_version != sizing_request.configuration_version
    ):
        raise RiskContractError("PORTFOLIO_UPSTREAM_BASIS_MISMATCH")
    assert (
        account.equity is not None
        and account.used_margin is not None
        and account.free_margin is not None
    )
    assert portfolio.pending_risk is not None and portfolio.drawdown is not None
    assert (
        sizing.recommended_notional is not None
        and sizing.recommended_margin is not None
    )
    assert stop.maximum_loss is not None
    equity, currency = account.equity.amount, account.currency
    if equity <= 0:
        raise RiskContractError("PORTFOLIO_POSITIVE_EQUITY_REQUIRED")
    if (
        portfolio.account_snapshot != account
        or portfolio.currency != currency
        or portfolio.equity != account.equity
    ):
        raise RiskContractError("PORTFOLIO_ACCOUNT_BASIS_MISMATCH")
    if (
        account.state is not SnapshotState.VALID
        or portfolio.state is not SnapshotState.VALID
    ):
        raise RiskContractError("PORTFOLIO_CURRENT_SNAPSHOTS_REQUIRED")
    reasons: list[str] = []
    limits: list[RiskLimitResult] = []
    failed = False
    insufficient = False
    warned = False
    expiries = [sizing.valid_until, leverage.valid_until, stop.valid_until]

    def record(code: str, outcome: RiskCheckOutcome) -> None:
        nonlocal failed, insufficient, warned
        if code not in reasons:
            reasons.append(code)
        failed |= outcome is RiskCheckOutcome.FAILED
        insufficient |= outcome is RiskCheckOutcome.INSUFFICIENT_DATA
        warned |= outcome is RiskCheckOutcome.WARNING

    for upstream_result in (sizing, leverage, stop):
        for code in upstream_result.reason_codes:
            record(code, upstream_result.outcome)
        if (
            upstream_result.outcome is not RiskCheckOutcome.PASSED
            and not upstream_result.reason_codes
        ):
            record("UPSTREAM_NOT_PASSED", upstream_result.outcome)

    def current(evidence: _PortfolioEvidence, name: str) -> bool:
        expiries.append(evidence.valid_until)
        if evidence.basis != basis:
            record(name + "_BASIS_MISMATCH", RiskCheckOutcome.FAILED)
            return False
        if (
            evidence.as_of > request.evaluated_at
            or evidence.valid_until < request.evaluated_at
        ):
            record(name + "_NOT_CURRENT", RiskCheckOutcome.INSUFFICIENT_DATA)
            return False
        return True

    def money(value: MoneyValue) -> Decimal:
        if value.currency != currency:
            raise RiskContractError("PORTFOLIO_CURRENCY_MISMATCH")
        return value.amount

    def ratio(value: Decimal, label: str, *, lower: bool = False) -> RatioValue:
        if value < 0 or value > equity:
            raise RiskContractError("PORTFOLIO_RATIO_NOT_REPRESENTABLE: " + label)
        with localcontext(
            Context(prec=34, rounding=ROUND_FLOOR if lower else ROUND_CEILING)
        ):
            return RatioValue(value / equity, label)

    def check(
        identity: str, observed: Decimal, boundary: Decimal, passed: bool, unit: str
    ) -> None:
        outcome = RiskCheckOutcome.PASSED if passed else RiskCheckOutcome.FAILED
        reason = identity.upper().replace("/", "_") + "_BREACHED"
        limits.append(
            RiskLimitResult(
                identity,
                RiskLimitSeverity.HARD,
                observed,
                boundary,
                unit,
                outcome,
                reason if not passed else "WITHIN_LIMIT",
            )
        )
        if not passed:
            record(reason, outcome)

    supplied: dict[UUID, PortfolioPositionEvidence] = {}
    for item in request.positions:
        if item.position is None or item.position.snapshot_id in supplied:
            raise RiskContractError("PORTFOLIO_POSITION_COVERAGE_INVALID")
        supplied[item.position.snapshot_id] = item
    if set(supplied) != {p.snapshot_id for p in portfolio.positions}:
        raise RiskContractError("PORTFOLIO_POSITION_COVERAGE_INCOMPLETE")
    if len({p.snapshot_id for p in portfolio.positions}) != len(
        portfolio.positions
    ) or len({p.position_id for p in portfolio.positions}) != len(portfolio.positions):
        raise RiskContractError("PORTFOLIO_DUPLICATE_POSITION")
    for position in portfolio.positions:
        evidence = supplied[position.snapshot_id]
        if evidence.position != position or position.account_id != account.account_id:
            raise RiskContractError("PORTFOLIO_POSITION_BASIS_MISMATCH")
        if not current(evidence, "POSITION"):
            raise RiskContractError("PORTFOLIO_POSITION_EVIDENCE_UNUSABLE")
        money(evidence.open_risk)
    if not current(request.proposal, "PROPOSAL"):
        raise RiskContractError("PORTFOLIO_PROPOSAL_EVIDENCE_UNUSABLE")
    if (
        request.proposal.venue != terms.venue
        or request.proposal.strategy_version != context.strategy_version
    ):
        raise RiskContractError("PORTFOLIO_PROPOSAL_BASIS_MISMATCH")
    if money(request.proposal.open_risk) != money(stop.maximum_loss):
        raise RiskContractError("PORTFOLIO_PROPOSAL_LOSS_MISMATCH")
    aggregation = None
    if portfolio.positions:
        with localcontext(Context(prec=34, rounding=ROUND_HALF_EVEN)):
            aggregation = aggregate_portfolio_exposure(
                account,
                tuple(
                    PositionExposureInput(p, supplied[p.snapshot_id].venue)
                    for p in portfolio.positions
                ),
                request.evaluated_at,
            )
    else:
        for snapshot in (account, portfolio):
            if (
                snapshot.as_of > request.evaluated_at
                or snapshot.captured_at > request.evaluated_at
                or snapshot.valid_until < request.evaluated_at
            ):
                raise RiskContractError("PORTFOLIO_SNAPSHOT_NOT_CURRENT")
    # Per-bucket nonnegative gross notional and risk; signed net stays in limit observations.
    before: dict[tuple[str, str], tuple[Decimal, Decimal]] = {
        ("total", "gross"): (Decimal(0), money(portfolio.pending_risk))
    }
    after: dict[tuple[str, str], tuple[Decimal, Decimal]]
    long_before = Decimal(0)
    short_before = Decimal(0)
    scenario_members: dict[str, set[str]] = {}
    instrument_gross: dict[tuple[str, str], list[Decimal]] = {}

    def add(
        buckets: dict[tuple[str, str], tuple[Decimal, Decimal]],
        item: PortfolioPositionEvidence,
        asset: str,
        instrument: str,
        side: PositionSide,
        notional: Decimal,
        risk: Decimal,
    ) -> None:
        status, code = _stop_reference_status(
            item.strategy_version, "C-021", request.evaluated_at
        )
        if status is not None:
            record(code or "STRATEGY_PROVENANCE_MISSING", status)
        if item.strategy_version.valid_until is not None:
            expiries.append(item.strategy_version.valid_until)
        if not item.correlation_groups:
            record("CORRELATION_MEMBERSHIP_UNKNOWN", RiskCheckOutcome.INSUFFICIENT_DATA)
        keys = [
            ("total", "gross"),
            ("asset", asset),
            ("strategy", portfolio_group_key(item.strategy_version)),
            ("regime", portfolio_group_key(item.regime)),
            ("instrument", _risk_digest("venue instrument", (item.venue, instrument))),
            ("direction", side.value),
        ]
        for group in item.correlation_groups:
            scenario_members.setdefault(group, set()).add(instrument)
            keys.append(("correlation", group))
        for key in keys:
            old_notional, old_risk = buckets.get(key, (Decimal(0), Decimal(0)))
            buckets[key] = (old_notional + notional, old_risk + risk)

    for position in portfolio.positions:
        assert position.notional is not None
        item = supplied[position.snapshot_id]
        notional = money(position.notional)
        add(
            before,
            item,
            position.asset,
            position.instrument_id,
            position.side,
            notional,
            money(item.open_risk),
        )
        if position.side is PositionSide.LONG:
            long_before += notional
        else:
            short_before += notional
        instrument_gross.setdefault(
            (item.venue, position.instrument_id), [Decimal(0), Decimal(0)]
        )[0] += notional
    gross_before = long_before + short_before
    net_before = long_before - short_before
    if (
        portfolio.gross_exposure is None
        or portfolio.net_exposure is None
        or money(portfolio.gross_exposure) != gross_before
        or money(portfolio.net_exposure) != net_before
    ):
        raise RiskContractError("PORTFOLIO_EXPOSURE_SNAPSHOT_MISMATCH")
    after = dict(before)
    proposal_notional = money(sizing.recommended_notional)
    proposal_margin = money(sizing.recommended_margin)
    proposal_loss = money(stop.maximum_loss)
    add(
        after,
        request.proposal,
        context.asset,
        context.instrument_id,
        context.side,
        proposal_notional,
        proposal_loss,
    )
    gross_after = gross_before + proposal_notional
    net_after = net_before + (
        proposal_notional if context.side is PositionSide.LONG else -proposal_notional
    )
    liquidity_key = (terms.venue, terms.instrument_id)
    instrument_gross.setdefault(liquidity_key, [Decimal(0), Decimal(0)])
    for values in instrument_gross.values():
        values[1] = values[0]
    instrument_gross[liquidity_key][1] += proposal_notional
    if portfolio.pending_risk.amount != 0:
        record(
            "PENDING_EXPOSURE_ATTRIBUTION_UNKNOWN", RiskCheckOutcome.INSUFFICIENT_DATA
        )
    scenarios = {x.group_id: x for x in request.scenarios}
    for group, instruments in sorted(scenario_members.items()):
        scenario = scenarios.get(group)
        if scenario is None:
            record("CORRELATION_SCENARIO_MISSING", RiskCheckOutcome.INSUFFICIENT_DATA)
        elif current(scenario, "CORRELATION_SCENARIO") and not instruments.issubset(
            scenario.instruments
        ):
            record("CORRELATION_INSTRUMENT_COVERAGE_MISMATCH", RiskCheckOutcome.FAILED)
    for scenario in request.scenarios:
        if scenario.group_id not in scenario_members:
            raise RiskContractError("UNRELATED_CORRELATION_SCENARIO")
    capacities = {(x.venue, x.instrument_id): x for x in request.liquidity}
    if set(capacities) - set(instrument_gross):
        raise RiskContractError("UNRELATED_LIQUIDITY_EVIDENCE")
    for key, values in sorted(instrument_gross.items()):
        capacity = capacities.get(key)
        if capacity is None:
            record("LIQUIDITY_EVIDENCE_MISSING", RiskCheckOutcome.INSUFFICIENT_DATA)
        elif current(capacity, "LIQUIDITY"):
            boundary = money(capacity.capacity)
            for phase, amount in zip(("before", "after"), values, strict=True):
                check(
                    phase + "/liquidity/" + _risk_digest("capacity key", key),
                    amount,
                    boundary,
                    amount <= boundary,
                    currency,
                )
    margin_before = money(account.used_margin)
    margin_after = margin_before + proposal_margin
    free_before = money(account.free_margin)
    free_after = (
        free_before - proposal_margin - money(leverage_request.additional_reserved_cost)
    )
    risk_after = after[("total", "gross")][1]
    policy = request.policy
    remaining: MoneyValue | None = None
    if policy is None:
        record("PORTFOLIO_POLICY_MISSING", RiskCheckOutcome.INSUFFICIENT_DATA)
    elif current(policy, "PORTFOLIO_POLICY"):
        if (
            policy.version != sizing_request.policy_version
            or policy.configuration_version != sizing_request.configuration_version
        ):
            record("PORTFOLIO_POLICY_VERSION_MISMATCH", RiskCheckOutcome.FAILED)
        caps = {(x.dimension, x.key): x.maximum for x in policy.concentration_limits}
        expected_caps = {
            key
            for key in after
            if key[0] in {"asset", "strategy", "regime", "correlation"}
        }
        if set(caps) - expected_caps:
            raise RiskContractError("UNRELATED_CONCENTRATION_LIMIT")
        for key in sorted(expected_caps):
            if key not in caps:
                record(
                    "CONCENTRATION_LIMIT_MISSING", RiskCheckOutcome.INSUFFICIENT_DATA
                )
                continue
            boundary = equity * caps[key]
            for phase, buckets in (("before", before), ("after", after)):
                value = buckets.get(key, (Decimal(0), Decimal(0)))[0]
                check(
                    phase + "/concentration/" + _risk_digest("cap key", key),
                    value,
                    boundary,
                    value <= boundary,
                    currency,
                )
        for phase, gross, net, margin, free in (
            ("before", gross_before, net_before, margin_before, free_before),
            ("after", gross_after, net_after, margin_after, free_after),
        ):
            check(
                phase + "/gross",
                gross,
                money(policy.maximum_gross),
                gross <= money(policy.maximum_gross),
                currency,
            )
            check(
                phase + "/net",
                net,
                money(policy.maximum_absolute_net),
                abs(net) <= money(policy.maximum_absolute_net),
                currency + "-signed-net",
            )
            check(
                phase + "/leverage",
                gross,
                equity * policy.maximum_gross_leverage,
                gross <= equity * policy.maximum_gross_leverage,
                currency + "-cross-multiplied",
            )
            check(
                phase + "/margin",
                margin,
                equity * policy.maximum_margin_utilization,
                margin <= equity * policy.maximum_margin_utilization,
                currency + "-cross-multiplied",
            )
            check(
                phase + "/free",
                free,
                money(policy.minimum_free_margin),
                free >= money(policy.minimum_free_margin),
                currency,
            )
            check(
                phase + "/drawdown",
                portfolio.drawdown.value,
                policy.maximum_drawdown,
                portfolio.drawdown.value <= policy.maximum_drawdown,
                "drawdown-ratio",
            )
            observed_risk = (
                before[("total", "gross")][1] if phase == "before" else risk_after
            )
            check(
                phase + "/risk",
                observed_risk,
                money(policy.total_risk_budget),
                observed_risk <= money(policy.total_risk_budget),
                currency,
            )
        remainder = money(policy.total_risk_budget) - risk_after
        if remainder >= 0:
            remaining = MoneyValue(remainder, currency)

    def exposure_values(
        buckets: dict[tuple[str, str], tuple[Decimal, Decimal]],
    ) -> tuple[ExposureValue, ...]:
        return tuple(
            ExposureValue(
                dimension,
                key,
                MoneyValue(n, currency),
                MoneyValue(r, currency),
                ratio(n, "gross-notional/equity"),
            )
            for (dimension, key), (n, r) in sorted(buckets.items())
        )

    before_values, after_values = exposure_values(before), exposure_values(after)
    outcome = (
        RiskCheckOutcome.FAILED
        if failed
        else RiskCheckOutcome.INSUFFICIENT_DATA
        if insufficient
        else RiskCheckOutcome.WARNING
        if warned
        else RiskCheckOutcome.PASSED
    )
    with localcontext(Context(prec=34, rounding=ROUND_CEILING)):
        before_leverage, after_leverage = gross_before / equity, gross_after / equity
    result = PortfolioImpact(
        result_id=request.result_id,
        context=context,
        outcome=outcome,
        reason_codes=tuple(reasons),
        model_version=sizing_request.model_version,
        as_of=context.as_of,
        evaluated_at=request.evaluated_at,
        valid_until=max(request.evaluated_at, min(expiries)),
        content_sha256="0" * 64,
        sizing_result_id=sizing.result_id,
        before_exposures=before_values,
        after_exposures=after_values,
        before_margin_utilization=ratio(margin_before, "used-margin/equity"),
        after_margin_utilization=ratio(margin_after, "used-margin/equity"),
        before_free_margin_buffer=ratio(free_before, "free-margin/equity", lower=True),
        after_free_margin_buffer=ratio(free_after, "free-margin/equity", lower=True)
        if free_after >= 0
        else None,
        before_gross_leverage=before_leverage,
        after_gross_leverage=after_leverage,
        before_drawdown=portfolio.drawdown,
        after_drawdown=portfolio.drawdown,
        post_trade_risk=ratio(
            risk_after, "open-plus-pending-plus-proposal-risk/equity"
        ),
        remaining_risk_budget=remaining,
        limits=tuple(limits),
        policy_version=sizing_request.policy_version,
    )
    return replace(
        result,
        content_sha256=_risk_digest(
            "portfolio impact",
            {
                "request": request,
                "sizing": sizing,
                "leverage": leverage,
                "stop": stop,
                "exposure_aggregation": aggregation,
                "result": {
                    item.name: getattr(result, item.name)
                    for item in fields(result)
                    if item.name != "content_sha256"
                },
            },
        ),
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


_STRESS_TYPES = frozenset(
    {"VOLATILITY", "GAP", "LIQUIDITY", "FUNDING", "CORRELATION", "RISK_OF_RUIN"}
)


@dataclass(frozen=True, slots=True)
class _StressEvidence:
    portfolio_request: PortfolioImpactRequest
    scenario_model_version: VersionReference
    cost_model_version: VersionReference
    source_version: VersionReference
    as_of: datetime
    valid_until: datetime

    def __post_init__(self) -> None:
        if not isinstance(self.portfolio_request, PortfolioImpactRequest):
            raise RiskContractError("portfolio_request must be PortfolioImpactRequest.")
        for name in ("scenario_model_version", "cost_model_version", "source_version"):
            if not isinstance(getattr(self, name), VersionReference):
                raise RiskContractError(f"{name} must be VersionReference.")
        start, end = _time("as_of", self.as_of), _time("valid_until", self.valid_until)
        _ordered("as_of", start, "valid_until", end)
        object.__setattr__(self, "as_of", start)
        object.__setattr__(self, "valid_until", end)


@dataclass(frozen=True, slots=True)
class StressShock:
    instrument_id: str
    name: str
    value: Decimal
    unit: str

    def __post_init__(self) -> None:
        _text("instrument_id", self.instrument_id)
        _text("name", self.name)
        _decimal("value", self.value)
        _text("unit", self.unit)


@dataclass(frozen=True, slots=True)
class StressProjectionEvidence(_StressEvidence):
    scenario_id: str
    scenario_type: str
    shocks: tuple[StressShock, ...]
    projected_loss: MoneyValue | None
    projected_margin: MoneyValue | None
    minimum_liquidation_distance: Decimal | None
    included_cost_reserve: MoneyValue | None
    cost_treatment: str | None
    assumptions: tuple[VersionReference, ...]

    def __post_init__(self) -> None:
        _StressEvidence.__post_init__(self)
        _text("scenario_id", self.scenario_id)
        if (
            self.scenario_id.startswith("missing/")
            or self.scenario_id == "ruin/observation"
        ):
            raise RiskContractError("reserved scenario identity.")
        if self.scenario_type not in _STRESS_TYPES - {"RISK_OF_RUIN"}:
            raise RiskContractError("unsupported stress projection type.")
        shocks = _typed_tuple("shocks", self.shocks, StressShock)
        _unique("shock identities", tuple((x.instrument_id, x.name) for x in shocks))
        _typed_tuple("assumptions", self.assumptions, VersionReference, empty=False)
        for name in ("projected_loss", "projected_margin", "included_cost_reserve"):
            value = getattr(self, name)
            if value is not None:
                _money(name, value)
        if self.minimum_liquidation_distance is not None:
            _nonnegative(
                "minimum_liquidation_distance", self.minimum_liquidation_distance
            )
            if self.minimum_liquidation_distance > 1:
                raise RiskContractError(
                    "minimum liquidation distance must be in [0, 1]."
                )
        if self.cost_treatment is not None:
            _text("cost_treatment", self.cost_treatment)


@dataclass(frozen=True, slots=True)
class StressAssessmentPolicy(_StressEvidence):
    required_scenario_types: tuple[str, ...]
    maximum_loss: MoneyValue
    maximum_drawdown: Decimal
    maximum_margin_utilization: Decimal
    minimum_liquidation_distance: Decimal
    ruin_equity_floor: MoneyValue
    maximum_ruin_frequency: Decimal
    minimum_path_count: int

    def __post_init__(self) -> None:
        _StressEvidence.__post_init__(self)
        kinds = _text_tuple(
            "required_scenario_types", self.required_scenario_types, empty=False
        )
        _unique("required scenario types", kinds)
        if (
            not set(kinds).issubset(_STRESS_TYPES)
            or "RISK_OF_RUIN" not in kinds
            or len(kinds) < 2
        ):
            raise RiskContractError(
                "require ruin and at least one supported stress type."
            )
        for name in ("maximum_loss", "ruin_equity_floor"):
            _money(name, getattr(self, name))
        if self.maximum_loss.currency != self.ruin_equity_floor.currency:
            raise RiskContractError("stress policy money currencies must match.")
        for name in (
            "maximum_drawdown",
            "maximum_margin_utilization",
            "minimum_liquidation_distance",
            "maximum_ruin_frequency",
        ):
            _nonnegative(name, getattr(self, name))
            if getattr(self, name) > 1:
                raise RiskContractError(f"{name} must be in [0, 1].")
        _positive_int("minimum_path_count", self.minimum_path_count)
        if self.minimum_path_count > 10000:
            raise RiskContractError("minimum_path_count exceeds the 10000-path bound.")


@dataclass(frozen=True, slots=True)
class RuinPathEvidence(_StressEvidence):
    horizon_steps: int
    paths: tuple[tuple[MoneyValue, ...], ...]
    assumptions: tuple[VersionReference, ...]
    content_sha256: str
    method_version: str = field(default="finite-net-quote-pnl-paths-v1", init=False)

    def __post_init__(self) -> None:
        _StressEvidence.__post_init__(self)
        _positive_int("horizon_steps", self.horizon_steps)
        if not isinstance(self.paths, tuple) or len(self.paths) > 10000:
            raise RiskContractError(
                "paths must be an immutable tuple of at most 10000 paths."
            )
        if (
            self.horizon_steps > 1000000
            or len(self.paths) * self.horizon_steps > 1000000
        ):
            raise RiskContractError("ruin paths exceed the 1000000-increment bound.")
        for path in self.paths:
            values = _typed_tuple("path", path, MoneyValue)
            if len(values) != self.horizon_steps:
                raise RiskContractError(
                    "every path must have the exact declared horizon."
                )
        _typed_tuple("assumptions", self.assumptions, VersionReference, empty=False)
        _digest("content_sha256", self.content_sha256)

    def identity_digest(self) -> str:
        return _risk_digest(
            "ruin paths",
            {
                item.name: getattr(self, item.name)
                for item in fields(self)
                if item.name != "content_sha256"
            },
        )

    @classmethod
    def build(
        cls,
        *,
        portfolio_request: PortfolioImpactRequest,
        scenario_model_version: VersionReference,
        cost_model_version: VersionReference,
        source_version: VersionReference,
        as_of: datetime,
        valid_until: datetime,
        horizon_steps: int,
        paths: tuple[tuple[MoneyValue, ...], ...],
        assumptions: tuple[VersionReference, ...],
    ) -> RuinPathEvidence:
        value = cls(
            portfolio_request,
            scenario_model_version,
            cost_model_version,
            source_version,
            as_of,
            valid_until,
            horizon_steps,
            paths,
            assumptions,
            "0" * 64,
        )
        return replace(value, content_sha256=value.identity_digest())


@dataclass(frozen=True, slots=True)
class RuinObservation:
    path_count: int
    hit_count: int | None
    horizon_steps: int
    hit_frequency: Decimal | None
    maximum_loss: MoneyValue | None
    outcome: RiskCheckOutcome
    reason_codes: tuple[str, ...]
    valid_until: datetime
    content_sha256: str
    method_version: str = field(default="finite-net-quote-pnl-paths-v1", init=False)


def _stress_evidence_reasons(
    evidence: _StressEvidence, policy: StressAssessmentPolicy, evaluated_at: datetime
) -> tuple[tuple[str, RiskCheckOutcome], ...]:
    reasons: list[tuple[str, RiskCheckOutcome]] = []
    if evidence.portfolio_request != policy.portfolio_request:
        reasons.append(("STRESS_BASIS_MISMATCH", RiskCheckOutcome.FAILED))
    if (
        evidence.scenario_model_version != policy.scenario_model_version
        or evidence.cost_model_version != policy.cost_model_version
    ):
        reasons.append(
            ("STRESS_MODEL_OR_COST_VERSION_MISMATCH", RiskCheckOutcome.FAILED)
        )
    if evidence.as_of > evaluated_at or evidence.valid_until < evaluated_at:
        reasons.append(
            ("STRESS_EVIDENCE_NOT_CURRENT", RiskCheckOutcome.INSUFFICIENT_DATA)
        )
    if policy.as_of > evaluated_at or policy.valid_until < evaluated_at:
        reasons.append(
            ("STRESS_POLICY_NOT_CURRENT", RiskCheckOutcome.INSUFFICIENT_DATA)
        )
    return tuple(reasons)


def calculate_ruin_observation(
    evidence: RuinPathEvidence, policy: StressAssessmentPolicy, evaluated_at: datetime
) -> RuinObservation:
    """Conditional finite-path hit counts; no fitted or calibrated probability."""
    if not isinstance(evidence, RuinPathEvidence) or not isinstance(
        policy, StressAssessmentPolicy
    ):
        raise RiskContractError("typed ruin evidence and stress policy are required.")
    when = _time("evaluated_at", evaluated_at)
    if when != policy.portfolio_request.evaluated_at:
        raise RiskContractError("ruin evaluation time differs from the bound basis.")
    if evidence.identity_digest() != evidence.content_sha256:
        raise RiskContractError("RUIN_PATH_DIGEST_MISMATCH")
    try:
        with localcontext(Context(prec=34, rounding=ROUND_HALF_EVEN)) as arithmetic:
            arithmetic.traps[Inexact] = True
            account = (
                policy.portfolio_request.basis.leverage_request.sizing_request.account
            )
            if account.equity is None or account.equity.amount <= 0:
                raise RiskContractError("RUIN_POSITIVE_EQUITY_REQUIRED")
            currency, equity = account.currency, account.equity.amount
            if (
                policy.ruin_equity_floor.currency != currency
                or policy.ruin_equity_floor.amount > equity
            ):
                raise RiskContractError("RUIN_FLOOR_CURRENCY_OR_RANGE_INVALID")
            portfolio_basis = calculate_portfolio_impact(policy.portfolio_request)
            reasons = list(_stress_evidence_reasons(evidence, policy, when))
            if portfolio_basis.outcome in {
                RiskCheckOutcome.FAILED,
                RiskCheckOutcome.INSUFFICIENT_DATA,
            }:
                reasons.append(
                    ("RUIN_PORTFOLIO_EVIDENCE_NOT_PASSED", portfolio_basis.outcome)
                )
            if (
                account.state is not SnapshotState.VALID
                or account.as_of > when
                or account.captured_at > when
                or account.valid_until < when
            ):
                reasons.append(
                    ("RUIN_ACCOUNT_NOT_CURRENT", RiskCheckOutcome.INSUFFICIENT_DATA)
                )
            for path in evidence.paths:
                if any(value.currency != currency for value in path):
                    raise RiskContractError("RUIN_PATH_CURRENCY_MISMATCH")
            if len(evidence.paths) < policy.minimum_path_count:
                reasons.append(
                    ("RUIN_SAMPLE_INSUFFICIENT", RiskCheckOutcome.INSUFFICIENT_DATA)
                )
            hits: int | None = None
            frequency: Decimal | None = None
            worst: MoneyValue | None = None
            if not reasons:
                hits = 0
                maximum_loss = Decimal(0)
                for path in evidence.paths:
                    capital = equity
                    hit = capital <= policy.ruin_equity_floor.amount
                    for increment in path:
                        capital += increment.amount
                        hit |= capital <= policy.ruin_equity_floor.amount
                        maximum_loss = max(maximum_loss, equity - capital)
                    hits += int(hit)
                worst = MoneyValue(maximum_loss, currency)
                if Decimal(hits) > policy.maximum_ruin_frequency * Decimal(
                    len(evidence.paths)
                ):
                    reasons.append(("RUIN_FREQUENCY_BREACHED", RiskCheckOutcome.FAILED))
                with localcontext(Context(prec=34, rounding=ROUND_CEILING)):
                    frequency = Decimal(hits) / Decimal(len(evidence.paths))
            outcome = (
                RiskCheckOutcome.FAILED
                if any(x[1] is RiskCheckOutcome.FAILED for x in reasons)
                else RiskCheckOutcome.INSUFFICIENT_DATA
                if reasons
                else RiskCheckOutcome.PASSED
            )
            result = RuinObservation(
                len(evidence.paths),
                hits,
                evidence.horizon_steps,
                frequency,
                worst,
                outcome,
                tuple(dict.fromkeys(x[0] for x in reasons)),
                max(
                    when,
                    min(
                        evidence.valid_until,
                        policy.valid_until,
                        account.valid_until,
                        portfolio_basis.valid_until,
                    ),
                ),
                "0" * 64,
            )
            return replace(
                result,
                content_sha256=_risk_digest(
                    "ruin observation",
                    {
                        "evidence": evidence,
                        "policy": policy,
                        "evaluated_at": when,
                        "result": {
                            x.name: getattr(result, x.name)
                            for x in fields(result)
                            if x.name != "content_sha256"
                        },
                    },
                ),
            )
    except DecimalException as exc:
        raise RiskContractError(
            "ruin arithmetic cannot be represented exactly at precision 34."
        ) from exc


@dataclass(frozen=True, slots=True)
class StressAssessmentRequest:
    result_id: UUID
    evaluated_at: datetime
    portfolio_request: PortfolioImpactRequest
    policy: StressAssessmentPolicy
    projections: tuple[StressProjectionEvidence, ...]
    ruin_paths: RuinPathEvidence | None

    def __post_init__(self) -> None:
        _uuid("result_id", self.result_id)
        when = _time("evaluated_at", self.evaluated_at)
        if not isinstance(
            self.portfolio_request, PortfolioImpactRequest
        ) or not isinstance(self.policy, StressAssessmentPolicy):
            raise RiskContractError(
                "typed portfolio request and stress policy are required."
            )
        if when != self.portfolio_request.evaluated_at:
            raise RiskContractError("stress evaluation times must match.")
        if self.policy.portfolio_request != self.portfolio_request:
            raise RiskContractError("STRESS_POLICY_BASIS_MISMATCH")
        values = _typed_tuple("projections", self.projections, StressProjectionEvidence)
        if len(values) > 128:
            raise RiskContractError("stress projections exceed the 128-scenario bound.")
        _unique("scenario identities", tuple(x.scenario_id for x in values))
        if any(
            x.scenario_type not in self.policy.required_scenario_types for x in values
        ):
            raise RiskContractError("unrequested stress projection type.")
        if self.ruin_paths is not None and not isinstance(
            self.ruin_paths, RuinPathEvidence
        ):
            raise RiskContractError(
                "ruin_paths must be RuinPathEvidence or None; C-072 is not accepted."
            )
        object.__setattr__(self, "evaluated_at", when)


def calculate_stress_assessment(request: StressAssessmentRequest) -> StressTestResult:
    """Assess supplied projections and finite paths; never generate source evidence."""
    if not isinstance(request, StressAssessmentRequest):
        raise RiskContractError("request must be StressAssessmentRequest.")
    try:
        with localcontext(Context(prec=34, rounding=ROUND_HALF_EVEN)) as arithmetic:
            arithmetic.traps[Inexact] = True
            return _calculate_stress_assessment(request)
    except DecimalException as exc:
        raise RiskContractError(
            "stress arithmetic cannot be represented exactly at precision 34."
        ) from exc


def _calculate_stress_assessment(request: StressAssessmentRequest) -> StressTestResult:
    policy = request.policy
    portfolio = calculate_portfolio_impact(request.portfolio_request)
    basis = request.portfolio_request.basis
    sizing = basis.leverage_request.sizing_request
    account = sizing.account
    assert account.equity is not None
    assert account.used_margin is not None
    assert sizing.portfolio.drawdown is not None
    equity, currency, current_drawdown = (
        account.equity.amount,
        account.currency,
        sizing.portfolio.drawdown.value,
    )
    if policy.maximum_loss.currency != currency:
        raise RiskContractError("STRESS_POLICY_CURRENCY_MISMATCH")
    reasons = list(portfolio.reason_codes)
    failed = portfolio.outcome is RiskCheckOutcome.FAILED
    insufficient = portfolio.outcome is RiskCheckOutcome.INSUFFICIENT_DATA
    warned = portfolio.outcome is RiskCheckOutcome.WARNING
    expiries = [portfolio.valid_until, policy.valid_until]
    breaches: set[str] = set()
    scenarios: list[StressScenarioResult] = []
    required_instruments = {p.instrument_id for p in sizing.portfolio.positions} | {
        sizing.context.instrument_id
    }
    policy_reasons = _stress_evidence_reasons(policy, policy, request.evaluated_at)
    for reason, state in policy_reasons:
        if reason not in reasons:
            reasons.append(reason)
        failed |= state is RiskCheckOutcome.FAILED
        insufficient |= state is RiskCheckOutcome.INSUFFICIENT_DATA

    def scenario(
        identity: str,
        kind: str,
        assumptions: tuple[VersionReference, ...],
        shocks: tuple[str, ...],
        loss: MoneyValue | None,
        margin: MoneyValue | None,
        liquidation_distance: Decimal | None,
        errors: tuple[tuple[str, RiskCheckOutcome], ...],
        *,
        ruin: RuinObservation | None = None,
    ) -> None:
        nonlocal failed, insufficient
        local_reasons = list(errors)
        local_breaches: list[str] = []
        drawdown: RatioValue | None = None
        impact = (
            "NOT_MODELED_FOR_PNL_PATHS" if kind == "RISK_OF_RUIN" else "UNAVAILABLE"
        )

        def breach(name: str) -> None:
            local_breaches.append(identity + "/" + name)
            local_reasons.append(
                ("STRESS_" + name.upper() + "_BREACHED", RiskCheckOutcome.FAILED)
            )

        # Only current, matching source projections support numerical comparisons.
        source_available = not local_reasons or (
            ruin is not None
            and ruin.maximum_loss is not None
            and local_reasons == [("RUIN_FREQUENCY_BREACHED", RiskCheckOutcome.FAILED)]
        )
        if source_available:
            if (
                loss is None
                or margin is None
                or (kind != "RISK_OF_RUIN" and liquidation_distance is None)
            ):
                local_reasons.append(
                    ("STRESS_PROJECTION_INCOMPLETE", RiskCheckOutcome.INSUFFICIENT_DATA)
                )
            if loss is not None:
                if loss.currency != currency:
                    raise RiskContractError("STRESS_LOSS_CURRENCY_MISMATCH")
                if loss.amount > policy.maximum_loss.amount:
                    breach("loss")
                numerator = (
                    current_drawdown * equity
                    + (Decimal(1) - current_drawdown) * loss.amount
                )
                if numerator > policy.maximum_drawdown * equity:
                    breach("drawdown")
                if loss.amount >= equity:
                    breach("equity_exhausted")
                    if kind != "RISK_OF_RUIN":
                        impact = "EQUITY_EXHAUSTED"
                if numerator <= equity:
                    with localcontext(Context(prec=34, rounding=ROUND_CEILING)):
                        drawdown = RatioValue(
                            numerator / equity, "fixed-high-water-mark-drawdown"
                        )
                else:
                    local_reasons.append(
                        ("STRESS_DRAWDOWN_NOT_REPRESENTABLE", RiskCheckOutcome.FAILED)
                    )
                if margin is not None:
                    if margin.currency != currency:
                        raise RiskContractError("STRESS_MARGIN_CURRENCY_MISMATCH")
                    projected_equity = equity - loss.amount
                    if (
                        projected_equity <= 0
                        or margin.amount
                        > projected_equity * policy.maximum_margin_utilization
                    ):
                        breach("margin")
            if kind != "RISK_OF_RUIN" and liquidation_distance is not None:
                if impact != "EQUITY_EXHAUSTED":
                    impact = "WITHIN_SUPPLIED_DISTANCE_LIMIT"
                if (
                    liquidation_distance <= 0
                    or liquidation_distance < policy.minimum_liquidation_distance
                ):
                    if impact != "EQUITY_EXHAUSTED":
                        impact = "DISTANCE_BREACHED"
                    breach("liquidation_distance")
        else:
            loss = None
            margin = None
        if ruin is not None and "RUIN_FREQUENCY_BREACHED" in ruin.reason_codes:
            local_breaches.append(identity + "/ruin_frequency")
        state = (
            RiskCheckOutcome.FAILED
            if any(x[1] is RiskCheckOutcome.FAILED for x in local_reasons)
            else RiskCheckOutcome.INSUFFICIENT_DATA
            if local_reasons
            else RiskCheckOutcome.PASSED
        )
        for reason, _ in local_reasons:
            if reason not in reasons:
                reasons.append(reason)
        failed |= state is RiskCheckOutcome.FAILED
        insufficient |= state is RiskCheckOutcome.INSUFFICIENT_DATA
        breaches.update(local_breaches)
        scenarios.append(
            StressScenarioResult(
                identity,
                kind,
                assumptions,
                shocks,
                loss,
                drawdown,
                margin,
                impact,
                tuple(sorted(set(local_breaches))),
                state,
            )
        )

    for projection in sorted(request.projections, key=lambda x: x.scenario_id):
        expiries.append(projection.valid_until)
        errors = list(
            _stress_evidence_reasons(projection, policy, request.evaluated_at)
        )
        shock_instruments = {x.instrument_id for x in projection.shocks}
        if shock_instruments != required_instruments:
            errors.append(
                (
                    "STRESS_SHOCK_COVERAGE_INCOMPLETE",
                    RiskCheckOutcome.INSUFFICIENT_DATA
                    if shock_instruments.issubset(required_instruments)
                    else RiskCheckOutcome.FAILED,
                )
            )
        if (
            projection.cost_treatment != "INCLUDED_IN_PROJECTED_LOSS"
            or projection.included_cost_reserve is None
        ):
            errors.append(
                ("STRESS_COST_ASSUMPTIONS_UNKNOWN", RiskCheckOutcome.INSUFFICIENT_DATA)
            )
        elif projection.included_cost_reserve.currency != currency:
            errors.append(("STRESS_COST_CURRENCY_MISMATCH", RiskCheckOutcome.FAILED))
        scenario(
            projection.scenario_id,
            projection.scenario_type,
            (
                *projection.assumptions,
                projection.source_version,
                projection.scenario_model_version,
                projection.cost_model_version,
            ),
            tuple(
                f"{x.instrument_id}:{x.name}={x.value} {x.unit}"
                for x in projection.shocks
            )
            or ("SHOCK_INPUTS_UNAVAILABLE",),
            projection.projected_loss,
            projection.projected_margin,
            projection.minimum_liquidation_distance,
            tuple(errors),
        )
    observation: RuinObservation | None = None
    if request.ruin_paths is not None:
        observation = calculate_ruin_observation(
            request.ruin_paths, policy, request.evaluated_at
        )
        expiries.append(observation.valid_until)
        assert sizing.instrument is not None
        planned_margin = (
            account.used_margin.amount
            + basis.stop_request.quantity
            * sizing.instrument.initial_margin_per_unit.amount
        )
        scenario(
            "ruin/observation",
            "RISK_OF_RUIN",
            (
                request.ruin_paths.source_version,
                policy.scenario_model_version,
                policy.cost_model_version,
                *request.ruin_paths.assumptions,
            ),
            (
                f"finite net-PnL paths={observation.path_count}; hits={observation.hit_count}; horizon={observation.horizon_steps}; observed_frequency={observation.hit_frequency}; not calibrated probability",
                "STATIC_PLANNED_MARGIN; PATH_LIQUIDATION_NOT_MODELED",
            ),
            observation.maximum_loss,
            MoneyValue(planned_margin, currency),
            None,
            tuple((x, observation.outcome) for x in observation.reason_codes),
            ruin=observation,
        )
    present = {x.scenario_type for x in scenarios}
    for kind in sorted(set(policy.required_scenario_types) - present):
        scenario(
            "missing/" + kind,
            kind,
            (
                policy.scenario_model_version,
                policy.cost_model_version,
                policy.source_version,
            ),
            ("REQUIRED_EVIDENCE_UNAVAILABLE",),
            None,
            None,
            None,
            (("REQUIRED_STRESS_SCENARIO_MISSING", RiskCheckOutcome.INSUFFICIENT_DATA),),
        )
    scenarios.sort(key=lambda x: x.scenario_id)
    loss_values = [
        x.projected_loss.amount for x in scenarios if x.projected_loss is not None
    ]
    margin_values = [
        x.projected_margin.amount for x in scenarios if x.projected_margin is not None
    ]
    drawdowns = [
        x.projected_drawdown.value
        for x in scenarios
        if x.projected_drawdown is not None
    ]
    impacts = [
        x.liquidation_impact for x in scenarios if x.scenario_type != "RISK_OF_RUIN"
    ]
    outcome = (
        RiskCheckOutcome.FAILED
        if failed
        else RiskCheckOutcome.INSUFFICIENT_DATA
        if insufficient
        else RiskCheckOutcome.WARNING
        if warned
        else RiskCheckOutcome.PASSED
    )
    result = StressTestResult(
        result_id=request.result_id,
        context=sizing.context,
        outcome=outcome,
        reason_codes=tuple(reasons),
        model_version=policy.scenario_model_version,
        as_of=sizing.context.as_of,
        evaluated_at=request.evaluated_at,
        valid_until=max(request.evaluated_at, min(expiries)),
        content_sha256="0" * 64,
        scenarios=tuple(scenarios),
        required_scenario_types=policy.required_scenario_types,
        scenario_model_version=policy.scenario_model_version,
        cost_model_version=policy.cost_model_version,
        worst_loss=MoneyValue(max(loss_values), currency)
        if len(loss_values) == len(scenarios)
        else None,
        worst_drawdown=RatioValue(
            max(drawdowns), "worst-fixed-high-water-mark-drawdown"
        )
        if len(drawdowns) == len(scenarios)
        else None,
        worst_margin=MoneyValue(max(margin_values), currency)
        if len(margin_values) == len(scenarios)
        else None,
        worst_liquidation_impact=(
            "EQUITY_EXHAUSTED"
            if "EQUITY_EXHAUSTED" in impacts
            else "DISTANCE_BREACHED"
            if "DISTANCE_BREACHED" in impacts
            else "WITHIN_SUPPLIED_DISTANCE_LIMITS; PATH_LIQUIDATION_NOT_MODELED"
        )
        if "UNAVAILABLE" not in impacts
        else None,
        breached_limit_ids=tuple(sorted(breaches)),
    )
    return replace(
        result,
        content_sha256=_risk_digest(
            "stress assessment",
            {
                "request": request,
                "portfolio_impact": portfolio,
                "ruin_observation": observation,
                "result": {
                    x.name: getattr(result, x.name)
                    for x in fields(result)
                    if x.name != "content_sha256"
                },
            },
        ),
    )


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
) -> tuple[tuple[Decimal, Decimal, datetime], ...] | None:
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
    if left_values.keys() != right_values.keys():
        return None
    return tuple(
        (left_values[timestamp], right_values[timestamp], timestamp)
        for timestamp in sorted(left_values)
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

    Each pair requires identical timestamps in the inclusive supplied window.
    Arithmetic is Decimal-only with precision 34 and no annualization.
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
            timestamps = tuple(item[2] for item in observations or ())
            if observations is None:
                estimate = _unknown_estimate("TIMESTAMP_MISMATCH", ())
            elif len(observations) < min_observations:
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
                timestamps = tuple(item[2] for item in observations or ())
                if observations is None:
                    estimate = _unknown_estimate("TIMESTAMP_MISMATCH", ())
                elif len(observations) < min_observations:
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
    "LeverageAssessmentRequest",
    "LinearMarginRuleEvidence",
    "LiquidationAssessmentRequest",
    "LiquidationAssessment",
    "LiquidationAvailability",
    "LiquidationCostEvidence",
    "LiquidationDistanceThresholds",
    "LiquidationPriceEvidence",
    "MarginMode",
    "MoneyValue",
    "OfflineAccountAssessment",
    "OfflineAccountEvidence",
    "PairwiseCorrelation",
    "PairwiseCorrelationResult",
    "PortfolioImpact",
    "PortfolioImpactBasis",
    "PortfolioPositionEvidence",
    "PortfolioCorrelationScenario",
    "PortfolioLiquidityEvidence",
    "PortfolioConcentrationLimit",
    "PortfolioImpactPolicy",
    "PortfolioImpactRequest",
    "portfolio_group_key",
    "calculate_portfolio_impact",
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
    "StressShock",
    "StressProjectionEvidence",
    "StressAssessmentPolicy",
    "RuinPathEvidence",
    "RuinObservation",
    "StressAssessmentRequest",
    "calculate_ruin_observation",
    "calculate_stress_assessment",
    "TakeProfitAssessment",
    "TakeProfitAssessmentRequest",
    "TakeProfitTarget",
    "TakeProfitTargetBound",
    "VersionReference",
    "aggregate_portfolio_exposure",
    "calculate_leverage_assessment",
    "calculate_liquidation_assessment",
    "calculate_position_size",
    "calculate_stop_loss_assessment",
    "calculate_take_profit_assessment",
    "pairwise_correlation",
]
