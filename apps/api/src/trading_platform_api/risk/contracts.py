from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from typing import TypeVar, cast
from uuid import UUID

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


__all__ = [
    "CONTRACT_SCHEMA_VERSION",
    "AccountSnapshot",
    "AssessmentReference",
    "ContractReference",
    "ExposureValue",
    "LeverageAssessment",
    "LiquidationAssessment",
    "LiquidationAvailability",
    "MarginMode",
    "MoneyValue",
    "PortfolioImpact",
    "PortfolioSnapshot",
    "PositionSide",
    "PositionSizingResult",
    "PositionSnapshot",
    "PriceValue",
    "RatioValue",
    "RevalidationStatus",
    "RevalidationTrigger",
    "RiskAssessment",
    "RiskCheckOutcome",
    "RiskContext",
    "RiskContractError",
    "RiskDecision",
    "RiskLimitResult",
    "RiskLimitSeverity",
    "RiskProposal",
    "RiskRevalidationResult",
    "RiskState",
    "RiskVerdict",
    "SizingMethod",
    "SnapshotState",
    "StopLossAssessment",
    "StressScenarioResult",
    "StressTestResult",
    "TakeProfitAssessment",
    "TakeProfitTarget",
    "VersionReference",
]
