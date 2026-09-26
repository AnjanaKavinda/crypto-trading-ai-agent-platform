from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from typing import TypeVar, cast
from uuid import UUID

from trading_platform_api.risk import (
    ContractReference,
    MarginMode,
    MoneyValue,
    PositionSide,
    PriceValue,
    RatioValue,
    TakeProfitTarget,
    VersionReference,
)

CONTRACT_SCHEMA_VERSION = "1"
_SHA256 = re.compile(r"[0-9a-f]{64}")
_T = TypeVar("_T")


class ExecutionContractError(ValueError):
    """Raised when approval or execution evidence is structurally invalid."""


class ApprovalLifecycle(StrEnum):
    CREATED = "CREATED"
    PRESENTED = "PRESENTED"
    MODIFIED = "MODIFIED"
    REVALIDATION_REQUIRED = "REVALIDATION_REQUIRED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"


class ApprovalDecisionType(StrEnum):
    APPROVE = "APPROVE"
    REJECT = "REJECT"
    CANCEL = "CANCEL"


class ExecutionState(StrEnum):
    INTENT_CREATED = "INTENT_CREATED"
    PRE_EXECUTION_VALIDATION = "PRE_EXECUTION_VALIDATION"
    READY = "READY"
    SUBMITTING = "SUBMITTING"
    SUBMITTED = "SUBMITTED"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    CANCEL_PENDING = "CANCEL_PENDING"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"
    FAILED = "FAILED"
    UNKNOWN = "UNKNOWN"
    RECONCILING = "RECONCILING"
    RECONCILED = "RECONCILED"


class OrderState(StrEnum):
    OPEN = "OPEN"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"
    UNKNOWN = "UNKNOWN"


class OrderSide(StrEnum):
    BUY = "BUY"
    SELL = "SELL"


class OrderType(StrEnum):
    MARKET = "MARKET"
    LIMIT = "LIMIT"
    STOP = "STOP"
    STOP_LIMIT = "STOP_LIMIT"
    TAKE_PROFIT = "TAKE_PROFIT"
    TAKE_PROFIT_LIMIT = "TAKE_PROFIT_LIMIT"
    TRAILING_STOP = "TRAILING_STOP"


class TimeInForce(StrEnum):
    GTC = "GTC"
    IOC = "IOC"
    FOK = "FOK"
    PO = "PO"


class ExecutionEnvironment(StrEnum):
    PAPER = "PAPER"
    SANDBOX = "SANDBOX"
    TESTNET = "TESTNET"
    LIVE = "LIVE"


class PositionLifecycle(StrEnum):
    PENDING_OPEN = "PENDING_OPEN"
    OPEN = "OPEN"
    INCREASING = "INCREASING"
    REDUCING = "REDUCING"
    CLOSING = "CLOSING"
    CLOSED = "CLOSED"
    OUTCOME_RECORDED = "OUTCOME_RECORDED"
    UNKNOWN = "UNKNOWN"
    RECONCILIATION_REQUIRED = "RECONCILIATION_REQUIRED"


class ReconciliationState(StrEnum):
    IN_SYNC = "IN_SYNC"
    DRIFT_DETECTED = "DRIFT_DETECTED"
    RECONCILIATION_REQUIRED = "RECONCILIATION_REQUIRED"
    RECONCILIATION_FAILED = "RECONCILIATION_FAILED"
    UNKNOWN = "UNKNOWN"


class ExecutionReportStatus(StrEnum):
    SUCCESS = "SUCCESS"
    PARTIAL = "PARTIAL"
    FAILED = "FAILED"
    UNKNOWN = "UNKNOWN"


class LiquidityRole(StrEnum):
    MAKER = "MAKER"
    TAKER = "TAKER"
    UNKNOWN = "UNKNOWN"


class AuthoritativeSource(StrEnum):
    INTERNAL = "INTERNAL"
    EXCHANGE = "EXCHANGE"
    COMPOSITE = "COMPOSITE"
    UNKNOWN = "UNKNOWN"


def _text(name: str, value: object) -> str:
    if not isinstance(value, str):
        raise ExecutionContractError(f"{name} must be a string.")
    if not value.strip():
        raise ExecutionContractError(f"{name} must not be blank.")
    if value != value.strip():
        raise ExecutionContractError(f"{name} must not contain surrounding whitespace.")
    return value


def _uuid(name: str, value: object) -> UUID:
    if not isinstance(value, UUID):
        raise ExecutionContractError(f"{name} must be a UUID.")
    return value


def _time(name: str, value: object) -> datetime:
    if not isinstance(value, datetime):
        raise ExecutionContractError(f"{name} must be a datetime.")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ExecutionContractError(f"{name} must be timezone-aware.")
    return value.astimezone(UTC)


def _decimal(name: str, value: object) -> Decimal:
    if (
        not isinstance(value, Decimal)
        or isinstance(value, bool)
        or not value.is_finite()
    ):
        raise ExecutionContractError(f"{name} must be a finite Decimal.")
    return value


def _nonnegative(name: str, value: object) -> Decimal:
    result = _decimal(name, value)
    if result < 0:
        raise ExecutionContractError(f"{name} must be non-negative.")
    return result


def _positive(name: str, value: object) -> Decimal:
    result = _decimal(name, value)
    if result <= 0:
        raise ExecutionContractError(f"{name} must be positive.")
    return result


def _positive_int(name: str, value: object) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise ExecutionContractError(f"{name} must be a positive integer.")
    return value


def _tuple(name: str, value: object, *, empty: bool = True) -> tuple[object, ...]:
    if not isinstance(value, tuple):
        raise ExecutionContractError(f"{name} must be a tuple.")
    if not empty and not value:
        raise ExecutionContractError(f"{name} must not be empty.")
    return value


def _typed_tuple(
    name: str, value: object, expected: type[_T], *, empty: bool = True
) -> tuple[_T, ...]:
    values = _tuple(name, value, empty=empty)
    if any(not isinstance(item, expected) for item in values):
        raise ExecutionContractError(f"{name} contains an invalid type.")
    return cast(tuple[_T, ...], values)


def _unique(name: str, values: tuple[object, ...]) -> None:
    try:
        if len(set(values)) != len(values):
            raise ExecutionContractError(f"{name} must not contain duplicates.")
    except TypeError as exc:
        raise ExecutionContractError(f"{name} must contain hashable values.") from exc


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
        raise ExecutionContractError(f"{name} must be a lowercase SHA-256 digest.")
    return result


def _reference(
    name: str, value: object, contract_id: str, *, hashed: bool = True
) -> ContractReference:
    if not isinstance(value, ContractReference) or value.contract_id != contract_id:
        raise ExecutionContractError(f"{name} must reference {contract_id}.")
    if hashed and value.content_sha256 is None:
        raise ExecutionContractError(f"{name} must include a content SHA-256.")
    return value


def _ordered(
    first_name: str, first: datetime, second_name: str, second: datetime
) -> None:
    if first > second:
        raise ExecutionContractError(f"{first_name} must not be after {second_name}.")


def _version(name: str, value: object) -> VersionReference:
    if not isinstance(value, VersionReference):
        raise ExecutionContractError(f"{name} must be a VersionReference.")
    return value


def _money(name: str, value: object, *, nonnegative: bool = False) -> MoneyValue:
    if not isinstance(value, MoneyValue):
        raise ExecutionContractError(f"{name} must be a MoneyValue.")
    if nonnegative and value.amount < 0:
        raise ExecutionContractError(f"{name} must be non-negative.")
    return value


def _price(name: str, value: object) -> PriceValue:
    if not isinstance(value, PriceValue):
        raise ExecutionContractError(f"{name} must be a PriceValue.")
    return value


@dataclass(frozen=True, slots=True)
class AuthenticatedActorReference:
    subject_id: str
    authentication_context_ref: str
    authentication_method: str
    assurance_level: str
    session_ref: str
    authenticated_at: datetime

    def __post_init__(self) -> None:
        for name in (
            "subject_id",
            "authentication_context_ref",
            "authentication_method",
            "assurance_level",
            "session_ref",
        ):
            _text(name, getattr(self, name))
        object.__setattr__(
            self, "authenticated_at", _time("authenticated_at", self.authenticated_at)
        )


@dataclass(frozen=True, slots=True)
class ApprovedTradeParameters:
    exchange_id: str
    account_id: UUID
    instrument_id: str
    position_side: PositionSide
    order_side: OrderSide
    order_type: OrderType
    quantity: Decimal
    limit_price: PriceValue | None
    trigger_price: PriceValue | None
    stop_loss: PriceValue
    take_profit_targets: tuple[TakeProfitTarget, ...]
    leverage: Decimal
    margin_mode: MarginMode
    reduce_only: bool
    post_only: bool
    time_in_force: TimeInForce
    maximum_slippage: RatioValue
    environment: ExecutionEnvironment
    content_sha256: str

    def __post_init__(self) -> None:
        _text("exchange_id", self.exchange_id)
        _uuid("account_id", self.account_id)
        _text("instrument_id", self.instrument_id)
        if not isinstance(self.position_side, PositionSide):
            raise ExecutionContractError("position_side must be a PositionSide.")
        if not isinstance(self.order_side, OrderSide):
            raise ExecutionContractError("order_side must be an OrderSide.")
        if not isinstance(self.order_type, OrderType):
            raise ExecutionContractError("order_type must be an OrderType.")
        _positive("quantity", self.quantity)
        if self.limit_price is not None:
            _price("limit_price", self.limit_price)
        if self.trigger_price is not None:
            _price("trigger_price", self.trigger_price)
        _price("stop_loss", self.stop_loss)
        targets = _typed_tuple(
            "take_profit_targets",
            self.take_profit_targets,
            TakeProfitTarget,
            empty=False,
        )
        _unique(
            "take_profit_targets.sequence", tuple(target.sequence for target in targets)
        )
        if sum(
            (target.allocation.value for target in targets), Decimal("0")
        ) != Decimal("1"):
            raise ExecutionContractError(
                "take-profit allocations must sum exactly to 1."
            )
        currencies = {
            self.stop_loss.quote_currency,
            *(target.price.quote_currency for target in targets),
        }
        if self.limit_price is not None:
            currencies.add(self.limit_price.quote_currency)
        if self.trigger_price is not None:
            currencies.add(self.trigger_price.quote_currency)
        if len(currencies) != 1:
            raise ExecutionContractError("trade parameter price currencies must match.")
        _positive("leverage", self.leverage)
        if not isinstance(self.margin_mode, MarginMode):
            raise ExecutionContractError("margin_mode must be a MarginMode.")
        if not isinstance(self.reduce_only, bool) or not isinstance(
            self.post_only, bool
        ):
            raise ExecutionContractError("reduce_only and post_only must be booleans.")
        if not isinstance(self.time_in_force, TimeInForce):
            raise ExecutionContractError("time_in_force must be a TimeInForce.")
        if not isinstance(self.maximum_slippage, RatioValue):
            raise ExecutionContractError("maximum_slippage must be a RatioValue.")
        if not isinstance(self.environment, ExecutionEnvironment):
            raise ExecutionContractError("environment must be an ExecutionEnvironment.")
        if (
            self.order_type
            in {OrderType.LIMIT, OrderType.STOP_LIMIT, OrderType.TAKE_PROFIT_LIMIT}
            and self.limit_price is None
        ):
            raise ExecutionContractError("limit order types require limit_price.")
        if (
            self.order_type
            in {
                OrderType.STOP,
                OrderType.STOP_LIMIT,
                OrderType.TAKE_PROFIT,
                OrderType.TAKE_PROFIT_LIMIT,
                OrderType.TRAILING_STOP,
            }
            and self.trigger_price is None
        ):
            raise ExecutionContractError("triggered order types require trigger_price.")
        if self.post_only and self.order_type is not OrderType.LIMIT:
            raise ExecutionContractError("post_only requires LIMIT order type.")
        _digest("content_sha256", self.content_sha256)


@dataclass(frozen=True, slots=True)
class ApprovalBindingHash:
    digest: str
    algorithm: str
    canonicalization_version: str
    signal: ContractReference
    evidence_package: ContractReference
    strategy_version: ContractReference
    validation: ContractReference
    risk_proposal: ContractReference
    account_snapshot: ContractReference
    portfolio_snapshot: ContractReference
    parameters_sha256: str

    def __post_init__(self) -> None:
        _digest("digest", self.digest)
        if _text("algorithm", self.algorithm) != "SHA-256":
            raise ExecutionContractError("algorithm must be SHA-256.")
        _text("canonicalization_version", self.canonicalization_version)
        expected = {
            "signal": "C-070",
            "evidence_package": "C-024",
            "strategy_version": "C-021",
            "validation": "C-028",
            "risk_proposal": "C-034",
            "account_snapshot": "C-032",
            "portfolio_snapshot": "C-033",
        }
        for name, contract_id in expected.items():
            _reference(name, getattr(self, name), contract_id)
        _digest("parameters_sha256", self.parameters_sha256)


@dataclass(frozen=True, slots=True)
class IdempotencyKey:
    namespace: str
    key: str
    request_sha256: str
    created_at: datetime
    expires_at: datetime | None = None

    def __post_init__(self) -> None:
        _text("namespace", self.namespace)
        _text("key", self.key)
        _digest("request_sha256", self.request_sha256)
        created = _time("created_at", self.created_at)
        object.__setattr__(self, "created_at", created)
        if self.expires_at is not None:
            expires = _time("expires_at", self.expires_at)
            _ordered("created_at", created, "expires_at", expires)
            object.__setattr__(self, "expires_at", expires)


@dataclass(frozen=True, slots=True)
class ReconciliationDelta:
    field_path: str
    internal_value_sha256: str | None
    exchange_value_sha256: str | None
    classification: str
    explanation: str

    def __post_init__(self) -> None:
        _text("field_path", self.field_path)
        if self.internal_value_sha256 is not None:
            _digest("internal_value_sha256", self.internal_value_sha256)
        if self.exchange_value_sha256 is not None:
            _digest("exchange_value_sha256", self.exchange_value_sha256)
        if (
            self.internal_value_sha256 == self.exchange_value_sha256
            and self.internal_value_sha256 is not None
        ):
            raise ExecutionContractError("reconciliation delta values must differ.")
        _text("classification", self.classification)
        _text("explanation", self.explanation)


@dataclass(frozen=True, slots=True)
class ApprovalRequest:
    request_id: UUID
    revision: int
    supersedes_request_id: UUID | None
    risk_proposal: ContractReference
    risk_revalidation: ContractReference | None
    parameters: ApprovedTradeParameters
    binding: ApprovalBindingHash
    intended_approver_subject: str
    lifecycle: ApprovalLifecycle
    reason_codes: tuple[str, ...]
    warnings: tuple[str, ...]
    human_modifiable_fields: tuple[str, ...]
    policy_version: VersionReference
    configuration_version: VersionReference
    as_of: datetime
    created_at: datetime
    presented_at: datetime | None
    expires_at: datetime
    content_sha256: str
    contract_id: str = field(default="C-037", init=False)
    schema_version: str = field(default=CONTRACT_SCHEMA_VERSION, init=False)

    def __post_init__(self) -> None:
        _uuid("request_id", self.request_id)
        _positive_int("revision", self.revision)
        if self.supersedes_request_id is not None:
            _uuid("supersedes_request_id", self.supersedes_request_id)
            if self.supersedes_request_id == self.request_id:
                raise ExecutionContractError(
                    "approval request cannot supersede itself."
                )
        if (self.revision == 1) != (self.supersedes_request_id is None):
            raise ExecutionContractError(
                "request revision and supersession are inconsistent."
            )
        _reference("risk_proposal", self.risk_proposal, "C-034")
        if self.risk_revalidation is not None:
            _reference("risk_revalidation", self.risk_revalidation, "C-083")
        if self.revision > 1 and self.risk_revalidation is None:
            raise ExecutionContractError(
                "revised approval request requires risk revalidation evidence."
            )
        if not isinstance(self.parameters, ApprovedTradeParameters):
            raise ExecutionContractError("parameters must be ApprovedTradeParameters.")
        if not isinstance(self.binding, ApprovalBindingHash):
            raise ExecutionContractError("binding must be an ApprovalBindingHash.")
        if (
            self.binding.risk_proposal != self.risk_proposal
            or self.binding.parameters_sha256 != self.parameters.content_sha256
        ):
            raise ExecutionContractError("approval request binding mismatch.")
        _text("intended_approver_subject", self.intended_approver_subject)
        if not isinstance(self.lifecycle, ApprovalLifecycle):
            raise ExecutionContractError("lifecycle must be an ApprovalLifecycle.")
        reasons = _text_tuple("reason_codes", self.reason_codes)
        _text_tuple("warnings", self.warnings)
        _text_tuple(
            "human_modifiable_fields", self.human_modifiable_fields, empty=False
        )
        _version("policy_version", self.policy_version)
        _version("configuration_version", self.configuration_version)
        as_of = _time("as_of", self.as_of)
        created = _time("created_at", self.created_at)
        expires = _time("expires_at", self.expires_at)
        _ordered("as_of", as_of, "created_at", created)
        _ordered("created_at", created, "expires_at", expires)
        if self.presented_at is not None:
            presented = _time("presented_at", self.presented_at)
            _ordered("created_at", created, "presented_at", presented)
            _ordered("presented_at", presented, "expires_at", expires)
            object.__setattr__(self, "presented_at", presented)
        elif self.lifecycle is not ApprovalLifecycle.CREATED:
            raise ExecutionContractError("non-created request requires presented_at.")
        if (
            self.lifecycle
            in {
                ApprovalLifecycle.MODIFIED,
                ApprovalLifecycle.REVALIDATION_REQUIRED,
                ApprovalLifecycle.REJECTED,
                ApprovalLifecycle.EXPIRED,
                ApprovalLifecycle.CANCELLED,
            }
            and not reasons
        ):
            raise ExecutionContractError(
                "non-current approval lifecycle requires reason_codes."
            )
        if self.lifecycle is ApprovalLifecycle.APPROVED:
            raise ExecutionContractError("ApprovalRequest cannot approve itself.")
        _digest("content_sha256", self.content_sha256)
        object.__setattr__(self, "as_of", as_of)
        object.__setattr__(self, "created_at", created)
        object.__setattr__(self, "expires_at", expires)


@dataclass(frozen=True, slots=True)
class ApprovalDecision:
    decision_id: UUID
    request: ApprovalRequest
    binding: ApprovalBindingHash
    actor: AuthenticatedActorReference
    decision: ApprovalDecisionType
    confirmation: str
    correlation_id: UUID
    policy_version: VersionReference
    decided_at: datetime
    valid_until: datetime
    content_sha256: str
    lifecycle: ApprovalLifecycle = field(init=False)
    contract_id: str = field(default="C-038", init=False)
    schema_version: str = field(default=CONTRACT_SCHEMA_VERSION, init=False)

    def __post_init__(self) -> None:
        _uuid("decision_id", self.decision_id)
        if not isinstance(self.request, ApprovalRequest):
            raise ExecutionContractError("request must be an ApprovalRequest.")
        if self.request.lifecycle is not ApprovalLifecycle.PRESENTED:
            raise ExecutionContractError("only a presented request may be decided.")
        if (
            not isinstance(self.binding, ApprovalBindingHash)
            or self.binding != self.request.binding
        ):
            raise ExecutionContractError("decision binding must exactly match request.")
        if not isinstance(self.actor, AuthenticatedActorReference):
            raise ExecutionContractError("actor must be authenticated actor evidence.")
        if self.actor.subject_id != self.request.intended_approver_subject:
            raise ExecutionContractError("decision actor is not the intended approver.")
        if not isinstance(self.decision, ApprovalDecisionType):
            raise ExecutionContractError("decision must be an ApprovalDecisionType.")
        _text("confirmation", self.confirmation)
        _uuid("correlation_id", self.correlation_id)
        _version("policy_version", self.policy_version)
        if self.policy_version != self.request.policy_version:
            raise ExecutionContractError("approval policy version mismatch.")
        decided = _time("decided_at", self.decided_at)
        valid = _time("valid_until", self.valid_until)
        _ordered(
            "actor.authenticated_at", self.actor.authenticated_at, "decided_at", decided
        )
        _ordered("request.created_at", self.request.created_at, "decided_at", decided)
        _ordered("decided_at", decided, "valid_until", valid)
        if decided > self.request.expires_at or valid > self.request.expires_at:
            raise ExecutionContractError("decision cannot outlive approval request.")
        lifecycle = {
            ApprovalDecisionType.APPROVE: ApprovalLifecycle.APPROVED,
            ApprovalDecisionType.REJECT: ApprovalLifecycle.REJECTED,
            ApprovalDecisionType.CANCEL: ApprovalLifecycle.CANCELLED,
        }[self.decision]
        object.__setattr__(self, "lifecycle", lifecycle)
        _digest("content_sha256", self.content_sha256)
        object.__setattr__(self, "decided_at", decided)
        object.__setattr__(self, "valid_until", valid)


@dataclass(frozen=True, slots=True)
class ExecutionIntent:
    intent_id: UUID
    approval_decision: ApprovalDecision
    risk_proposal: ContractReference
    risk_revalidation: ContractReference | None
    safety_decision: ContractReference
    readiness_state: ContractReference
    parameters: ApprovedTradeParameters
    binding: ApprovalBindingHash
    idempotency_key: IdempotencyKey
    state: ExecutionState
    reason_codes: tuple[str, ...]
    policy_version: VersionReference
    configuration_version: VersionReference
    as_of: datetime
    created_at: datetime
    valid_until: datetime
    content_sha256: str
    contract_id: str = field(default="C-039", init=False)
    schema_version: str = field(default=CONTRACT_SCHEMA_VERSION, init=False)

    def __post_init__(self) -> None:
        _uuid("intent_id", self.intent_id)
        if not isinstance(self.approval_decision, ApprovalDecision):
            raise ExecutionContractError("approval_decision must be ApprovalDecision.")
        if self.approval_decision.decision is not ApprovalDecisionType.APPROVE:
            raise ExecutionContractError(
                "execution intent requires an explicitly approved decision."
            )
        _reference("risk_proposal", self.risk_proposal, "C-034")
        if self.risk_revalidation is not None:
            _reference("risk_revalidation", self.risk_revalidation, "C-083")
        _reference("safety_decision", self.safety_decision, "C-058")
        _reference("readiness_state", self.readiness_state, "C-059")
        if (
            not isinstance(self.parameters, ApprovedTradeParameters)
            or self.parameters != self.approval_decision.request.parameters
        ):
            raise ExecutionContractError(
                "intent parameters must match approved request."
            )
        if (
            not isinstance(self.binding, ApprovalBindingHash)
            or self.binding != self.approval_decision.binding
        ):
            raise ExecutionContractError("intent binding must match approval decision.")
        if self.risk_proposal != self.binding.risk_proposal:
            raise ExecutionContractError("intent risk proposal binding mismatch.")
        if not isinstance(self.idempotency_key, IdempotencyKey):
            raise ExecutionContractError("idempotency_key must be IdempotencyKey.")
        if not isinstance(self.state, ExecutionState):
            raise ExecutionContractError("state must be an ExecutionState.")
        reasons = _text_tuple("reason_codes", self.reason_codes)
        _version("policy_version", self.policy_version)
        _version("configuration_version", self.configuration_version)
        as_of = _time("as_of", self.as_of)
        created = _time("created_at", self.created_at)
        valid = _time("valid_until", self.valid_until)
        _ordered("as_of", as_of, "created_at", created)
        _ordered("created_at", created, "valid_until", valid)
        if valid > self.approval_decision.valid_until:
            raise ExecutionContractError("intent cannot outlive approval decision.")
        if (
            self.state
            in {
                ExecutionState.READY,
                ExecutionState.SUBMITTING,
                ExecutionState.SUBMITTED,
                ExecutionState.PARTIALLY_FILLED,
                ExecutionState.FILLED,
            }
            and self.approval_decision.decision is not ApprovalDecisionType.APPROVE
        ):
            raise ExecutionContractError(
                "execution progression requires explicit approval."
            )
        if (
            self.state
            in {
                ExecutionState.REJECTED,
                ExecutionState.FAILED,
                ExecutionState.UNKNOWN,
                ExecutionState.RECONCILING,
            }
            and not reasons
        ):
            raise ExecutionContractError(
                "blocked/unknown execution state requires reason_codes."
            )
        _digest("content_sha256", self.content_sha256)
        object.__setattr__(self, "as_of", as_of)
        object.__setattr__(self, "created_at", created)
        object.__setattr__(self, "valid_until", valid)


@dataclass(frozen=True, slots=True)
class OrderRequest:
    request_id: UUID
    intent: ExecutionIntent
    parameters: ApprovedTradeParameters
    binding: ApprovalBindingHash
    idempotency_key: IdempotencyKey
    client_order_id: str
    state: ExecutionState
    request_version: VersionReference
    constructed_at: datetime
    content_sha256: str
    contract_id: str = field(default="C-084", init=False)
    schema_version: str = field(default=CONTRACT_SCHEMA_VERSION, init=False)

    def __post_init__(self) -> None:
        _uuid("request_id", self.request_id)
        if not isinstance(self.intent, ExecutionIntent):
            raise ExecutionContractError("intent must be ExecutionIntent.")
        if self.intent.state is not ExecutionState.READY:
            raise ExecutionContractError("order request requires READY intent.")
        if (
            self.parameters != self.intent.parameters
            or self.binding != self.intent.binding
        ):
            raise ExecutionContractError("order request differs from approved intent.")
        if self.idempotency_key != self.intent.idempotency_key:
            raise ExecutionContractError("order request idempotency mismatch.")
        _text("client_order_id", self.client_order_id)
        if self.state is not ExecutionState.READY:
            raise ExecutionContractError("new order request state must be READY.")
        _version("request_version", self.request_version)
        constructed = _time("constructed_at", self.constructed_at)
        if not self.intent.created_at <= constructed <= self.intent.valid_until:
            raise ExecutionContractError(
                "order request constructed outside intent validity."
            )
        _digest("content_sha256", self.content_sha256)
        if self.idempotency_key.request_sha256 != self.content_sha256:
            raise ExecutionContractError("idempotency key must bind request content.")
        object.__setattr__(self, "constructed_at", constructed)


def _order_quantities(
    state: OrderState, requested: Decimal, filled: Decimal, remaining: Decimal
) -> None:
    if filled + remaining != requested:
        raise ExecutionContractError(
            "filled plus remaining must equal requested quantity."
        )
    if state is OrderState.FILLED and (filled != requested or remaining != 0):
        raise ExecutionContractError("FILLED order must have no remaining quantity.")
    if state is OrderState.PARTIALLY_FILLED and not (
        0 < filled < requested and remaining > 0
    ):
        raise ExecutionContractError("PARTIALLY_FILLED quantities are inconsistent.")
    if state is OrderState.OPEN and remaining <= 0:
        raise ExecutionContractError("OPEN order requires remaining quantity.")
    if state is OrderState.OPEN and (filled != 0 or remaining != requested):
        raise ExecutionContractError("OPEN order cannot contain fills.")


@dataclass(frozen=True, slots=True)
class Order:
    order_id: UUID
    order_request_id: UUID
    intent_id: UUID
    client_order_id: str
    exchange_order_id: str | None
    exchange_id: str
    account_id: UUID
    instrument_id: str
    side: OrderSide
    order_type: OrderType
    state: OrderState
    requested_quantity: Decimal
    filled_quantity: Decimal
    remaining_quantity: Decimal
    requested_price: PriceValue | None
    average_price: PriceValue | None
    trigger_price: PriceValue | None
    fill_ids: tuple[UUID, ...]
    state_reason: str | None
    record_version: VersionReference
    created_at: datetime
    updated_at: datetime
    exchange_timestamp: datetime | None
    content_sha256: str
    contract_id: str = field(default="C-040", init=False)
    schema_version: str = field(default=CONTRACT_SCHEMA_VERSION, init=False)

    def __post_init__(self) -> None:
        for name in ("order_id", "order_request_id", "intent_id", "account_id"):
            _uuid(name, getattr(self, name))
        _text("client_order_id", self.client_order_id)
        if self.exchange_order_id is not None:
            _text("exchange_order_id", self.exchange_order_id)
        _text("exchange_id", self.exchange_id)
        _text("instrument_id", self.instrument_id)
        if (
            not isinstance(self.side, OrderSide)
            or not isinstance(self.order_type, OrderType)
            or not isinstance(self.state, OrderState)
        ):
            raise ExecutionContractError("order side/type/state is invalid.")
        requested = _positive("requested_quantity", self.requested_quantity)
        filled = _nonnegative("filled_quantity", self.filled_quantity)
        remaining = _nonnegative("remaining_quantity", self.remaining_quantity)
        _order_quantities(self.state, requested, filled, remaining)
        for name in ("requested_price", "average_price", "trigger_price"):
            value = getattr(self, name)
            if value is not None:
                _price(name, value)
        price_values = tuple(
            value
            for value in (
                self.requested_price,
                self.average_price,
                self.trigger_price,
            )
            if value is not None
        )
        if len({value.quote_currency for value in price_values}) > 1:
            raise ExecutionContractError("order price currencies must match.")
        _uuid_tuple("fill_ids", self.fill_ids)
        if filled > 0 and not self.fill_ids:
            raise ExecutionContractError("filled quantity requires fill identities.")
        if self.state_reason is not None:
            _text("state_reason", self.state_reason)
        if (
            self.state in {OrderState.REJECTED, OrderState.EXPIRED, OrderState.UNKNOWN}
            and self.state_reason is None
        ):
            raise ExecutionContractError(
                "non-success order state requires state_reason."
            )
        _version("record_version", self.record_version)
        created = _time("created_at", self.created_at)
        updated = _time("updated_at", self.updated_at)
        _ordered("created_at", created, "updated_at", updated)
        object.__setattr__(self, "created_at", created)
        object.__setattr__(self, "updated_at", updated)
        if self.exchange_timestamp is not None:
            object.__setattr__(
                self,
                "exchange_timestamp",
                _time("exchange_timestamp", self.exchange_timestamp),
            )
        _digest("content_sha256", self.content_sha256)


@dataclass(frozen=True, slots=True)
class ExchangeOrder:
    observation_id: UUID
    exchange_order_id: str
    client_order_id: str
    exchange_id: str
    account_id: UUID
    instrument_id: str
    state: OrderState
    native_status: str
    requested_quantity: Decimal
    executed_quantity: Decimal
    remaining_quantity: Decimal
    average_price: PriceValue | None
    exchange_timestamp: datetime
    observed_at: datetime
    source_version: VersionReference
    raw_response_sha256: str
    content_sha256: str
    contract_id: str = field(default="C-085", init=False)
    schema_version: str = field(default=CONTRACT_SCHEMA_VERSION, init=False)

    def __post_init__(self) -> None:
        _uuid("observation_id", self.observation_id)
        for name in (
            "exchange_order_id",
            "client_order_id",
            "exchange_id",
            "instrument_id",
            "native_status",
        ):
            _text(name, getattr(self, name))
        _uuid("account_id", self.account_id)
        if not isinstance(self.state, OrderState):
            raise ExecutionContractError("state must be an OrderState.")
        requested = _positive("requested_quantity", self.requested_quantity)
        executed = _nonnegative("executed_quantity", self.executed_quantity)
        remaining = _nonnegative("remaining_quantity", self.remaining_quantity)
        _order_quantities(self.state, requested, executed, remaining)
        if self.average_price is not None:
            _price("average_price", self.average_price)
        exchange_time = _time("exchange_timestamp", self.exchange_timestamp)
        observed = _time("observed_at", self.observed_at)
        _ordered("exchange_timestamp", exchange_time, "observed_at", observed)
        object.__setattr__(self, "exchange_timestamp", exchange_time)
        object.__setattr__(self, "observed_at", observed)
        _version("source_version", self.source_version)
        _digest("raw_response_sha256", self.raw_response_sha256)
        _digest("content_sha256", self.content_sha256)


@dataclass(frozen=True, slots=True)
class Fill:
    fill_id: UUID
    order_id: UUID
    exchange_order_id: str
    exchange_fill_id: str
    exchange_id: str
    account_id: UUID
    instrument_id: str
    quantity: Decimal
    price: PriceValue
    fee: MoneyValue
    liquidity_role: LiquidityRole
    exchange_timestamp: datetime
    observed_at: datetime
    source_version: VersionReference
    content_sha256: str
    contract_id: str = field(default="C-041", init=False)
    schema_version: str = field(default=CONTRACT_SCHEMA_VERSION, init=False)

    def __post_init__(self) -> None:
        for name in ("fill_id", "order_id", "account_id"):
            _uuid(name, getattr(self, name))
        for name in (
            "exchange_order_id",
            "exchange_fill_id",
            "exchange_id",
            "instrument_id",
        ):
            _text(name, getattr(self, name))
        _positive("quantity", self.quantity)
        _price("price", self.price)
        fee = _money("fee", self.fee, nonnegative=True)
        if fee.currency != self.price.quote_currency:
            raise ExecutionContractError("fill fee and price currencies must match.")
        if not isinstance(self.liquidity_role, LiquidityRole):
            raise ExecutionContractError("liquidity_role must be a LiquidityRole.")
        exchange_time = _time("exchange_timestamp", self.exchange_timestamp)
        observed = _time("observed_at", self.observed_at)
        _ordered("exchange_timestamp", exchange_time, "observed_at", observed)
        object.__setattr__(self, "exchange_timestamp", exchange_time)
        object.__setattr__(self, "observed_at", observed)
        _version("source_version", self.source_version)
        _digest("content_sha256", self.content_sha256)


@dataclass(frozen=True, slots=True)
class Position:
    position_id: UUID
    account_id: UUID
    instrument_id: str
    side: PositionSide
    lifecycle: PositionLifecycle
    reconciliation_state: ReconciliationState
    quantity: Decimal
    entry_price: PriceValue | None
    mark_price: PriceValue | None
    realized_pnl: MoneyValue
    unrealized_pnl: MoneyValue
    leverage: Decimal
    margin_mode: MarginMode
    margin_used: MoneyValue
    order_ids: tuple[UUID, ...]
    fill_ids: tuple[UUID, ...]
    source_version: VersionReference
    as_of: datetime
    observed_at: datetime
    content_sha256: str
    contract_id: str = field(default="C-042", init=False)
    schema_version: str = field(default=CONTRACT_SCHEMA_VERSION, init=False)

    def __post_init__(self) -> None:
        _uuid("position_id", self.position_id)
        _uuid("account_id", self.account_id)
        _text("instrument_id", self.instrument_id)
        if (
            not isinstance(self.side, PositionSide)
            or not isinstance(self.lifecycle, PositionLifecycle)
            or not isinstance(self.reconciliation_state, ReconciliationState)
        ):
            raise ExecutionContractError(
                "position side/lifecycle/reconciliation state is invalid."
            )
        quantity = _nonnegative("quantity", self.quantity)
        if self.entry_price is not None:
            _price("entry_price", self.entry_price)
        if self.mark_price is not None:
            _price("mark_price", self.mark_price)
        realized = _money("realized_pnl", self.realized_pnl)
        unrealized = _money("unrealized_pnl", self.unrealized_pnl)
        margin = _money("margin_used", self.margin_used, nonnegative=True)
        if len({realized.currency, unrealized.currency, margin.currency}) != 1:
            raise ExecutionContractError("position money currencies must match.")
        _positive("leverage", self.leverage)
        if not isinstance(self.margin_mode, MarginMode):
            raise ExecutionContractError("margin_mode must be a MarginMode.")
        _uuid_tuple("order_ids", self.order_ids)
        _uuid_tuple("fill_ids", self.fill_ids)
        open_states = {
            PositionLifecycle.OPEN,
            PositionLifecycle.INCREASING,
            PositionLifecycle.REDUCING,
            PositionLifecycle.CLOSING,
        }
        if self.lifecycle in open_states and (
            quantity <= 0 or not self.order_ids or not self.fill_ids
        ):
            raise ExecutionContractError(
                "open position requires quantity, orders, and fills."
            )
        if (
            self.lifecycle
            in {PositionLifecycle.CLOSED, PositionLifecycle.OUTCOME_RECORDED}
            and quantity != 0
        ):
            raise ExecutionContractError("closed position must have zero quantity.")
        if (
            self.lifecycle
            in {
                PositionLifecycle.UNKNOWN,
                PositionLifecycle.RECONCILIATION_REQUIRED,
            }
            and self.reconciliation_state is ReconciliationState.IN_SYNC
        ):
            raise ExecutionContractError(
                "unknown or reconciliation-required position cannot be in sync."
            )
        _version("source_version", self.source_version)
        as_of = _time("as_of", self.as_of)
        observed = _time("observed_at", self.observed_at)
        _ordered("as_of", as_of, "observed_at", observed)
        object.__setattr__(self, "as_of", as_of)
        object.__setattr__(self, "observed_at", observed)
        _digest("content_sha256", self.content_sha256)


@dataclass(frozen=True, slots=True)
class Trade:
    trade_id: UUID
    execution_intent: ContractReference
    approval_decision: ContractReference
    risk_proposal: ContractReference
    signal: ContractReference
    strategy_version: ContractReference
    binding: ApprovalBindingHash
    account_id: UUID
    exchange_id: str
    instrument_id: str
    environment: ExecutionEnvironment
    position_lifecycle: PositionLifecycle
    order_ids: tuple[UUID, ...]
    fill_ids: tuple[UUID, ...]
    position_id: UUID
    execution_policy_version: VersionReference
    opened_at: datetime
    closed_at: datetime | None
    content_sha256: str
    contract_id: str = field(default="C-043", init=False)
    schema_version: str = field(default=CONTRACT_SCHEMA_VERSION, init=False)

    def __post_init__(self) -> None:
        _uuid("trade_id", self.trade_id)
        expected = {
            "execution_intent": "C-039",
            "approval_decision": "C-038",
            "risk_proposal": "C-034",
            "signal": "C-070",
            "strategy_version": "C-021",
        }
        for name, contract_id in expected.items():
            _reference(name, getattr(self, name), contract_id)
        if not isinstance(self.binding, ApprovalBindingHash):
            raise ExecutionContractError("binding must be ApprovalBindingHash.")
        if (
            self.binding.risk_proposal != self.risk_proposal
            or self.binding.signal != self.signal
            or self.binding.strategy_version != self.strategy_version
        ):
            raise ExecutionContractError(
                "trade provenance differs from approval binding."
            )
        _uuid("account_id", self.account_id)
        _text("exchange_id", self.exchange_id)
        _text("instrument_id", self.instrument_id)
        if not isinstance(self.environment, ExecutionEnvironment) or not isinstance(
            self.position_lifecycle, PositionLifecycle
        ):
            raise ExecutionContractError("trade environment/lifecycle is invalid.")
        _uuid_tuple("order_ids", self.order_ids, empty=False)
        _uuid_tuple("fill_ids", self.fill_ids, empty=False)
        _uuid("position_id", self.position_id)
        _version("execution_policy_version", self.execution_policy_version)
        opened = _time("opened_at", self.opened_at)
        object.__setattr__(self, "opened_at", opened)
        if self.closed_at is not None:
            closed = _time("closed_at", self.closed_at)
            _ordered("opened_at", opened, "closed_at", closed)
            object.__setattr__(self, "closed_at", closed)
        elif self.position_lifecycle in {
            PositionLifecycle.CLOSED,
            PositionLifecycle.OUTCOME_RECORDED,
        }:
            raise ExecutionContractError("closed trade lifecycle requires closed_at.")
        _digest("content_sha256", self.content_sha256)


@dataclass(frozen=True, slots=True)
class TradeOutcome:
    outcome_id: UUID
    trade: ContractReference
    actual_entry: PriceValue
    actual_exit: PriceValue
    executed_quantity: Decimal
    realized_pnl: MoneyValue
    fees: MoneyValue
    funding: MoneyValue
    slippage: MoneyValue | None
    maximum_adverse_excursion: MoneyValue | None
    maximum_favorable_excursion: MoneyValue | None
    order_ids: tuple[UUID, ...]
    fill_ids: tuple[UUID, ...]
    reconciliation_report: ContractReference
    method_version: VersionReference
    opened_at: datetime
    closed_at: datetime
    evaluated_at: datetime
    content_sha256: str
    is_factual: bool = field(default=True, init=False)
    contract_id: str = field(default="C-044", init=False)
    schema_version: str = field(default=CONTRACT_SCHEMA_VERSION, init=False)

    def __post_init__(self) -> None:
        _uuid("outcome_id", self.outcome_id)
        _reference("trade", self.trade, "C-043")
        _price("actual_entry", self.actual_entry)
        _price("actual_exit", self.actual_exit)
        _positive("executed_quantity", self.executed_quantity)
        values = [
            _money("realized_pnl", self.realized_pnl),
            _money("fees", self.fees, nonnegative=True),
            _money("funding", self.funding),
        ]
        for name in (
            "slippage",
            "maximum_adverse_excursion",
            "maximum_favorable_excursion",
        ):
            value = getattr(self, name)
            if value is not None:
                values.append(_money(name, value, nonnegative=True))
        if len({value.currency for value in values}) != 1:
            raise ExecutionContractError("trade outcome money currencies must match.")
        if (
            len(
                {
                    self.actual_entry.quote_currency,
                    self.actual_exit.quote_currency,
                    *(value.currency for value in values),
                }
            )
            != 1
        ):
            raise ExecutionContractError(
                "trade outcome price and money currencies must match."
            )
        _uuid_tuple("order_ids", self.order_ids, empty=False)
        _uuid_tuple("fill_ids", self.fill_ids, empty=False)
        _reference("reconciliation_report", self.reconciliation_report, "C-096")
        _version("method_version", self.method_version)
        opened = _time("opened_at", self.opened_at)
        closed = _time("closed_at", self.closed_at)
        evaluated = _time("evaluated_at", self.evaluated_at)
        _ordered("opened_at", opened, "closed_at", closed)
        _ordered("closed_at", closed, "evaluated_at", evaluated)
        object.__setattr__(self, "opened_at", opened)
        object.__setattr__(self, "closed_at", closed)
        object.__setattr__(self, "evaluated_at", evaluated)
        _digest("content_sha256", self.content_sha256)


@dataclass(frozen=True, slots=True)
class ReconciliationReport:
    report_id: UUID
    scope: str
    internal_orders: tuple[ContractReference, ...]
    exchange_orders: tuple[ExchangeOrder, ...]
    fills: tuple[Fill, ...]
    positions: tuple[ContractReference, ...]
    trades: tuple[ContractReference, ...]
    state: ReconciliationState
    authoritative_source: AuthoritativeSource
    deltas: tuple[ReconciliationDelta, ...]
    reason_codes: tuple[str, ...]
    resolution_actions: tuple[str, ...]
    reconciler_version: VersionReference
    policy_version: VersionReference
    as_of: datetime
    started_at: datetime
    completed_at: datetime | None
    content_sha256: str
    blocks_conflicting_execution: bool = field(init=False)
    contract_id: str = field(default="C-096", init=False)
    schema_version: str = field(default=CONTRACT_SCHEMA_VERSION, init=False)

    def __post_init__(self) -> None:
        _uuid("report_id", self.report_id)
        _text("scope", self.scope)
        internal = _typed_tuple(
            "internal_orders", self.internal_orders, ContractReference
        )
        for index, item in enumerate(internal):
            _reference(f"internal_orders[{index}]", item, "C-040")
        exchange = _typed_tuple("exchange_orders", self.exchange_orders, ExchangeOrder)
        fills = _typed_tuple("fills", self.fills, Fill)
        _unique("exchange_orders", tuple(item.exchange_order_id for item in exchange))
        _unique("fills", tuple(item.exchange_fill_id for item in fills))
        positions = _typed_tuple("positions", self.positions, ContractReference)
        for index, item in enumerate(positions):
            _reference(f"positions[{index}]", item, "C-042")
        trades = _typed_tuple("trades", self.trades, ContractReference)
        for index, item in enumerate(trades):
            _reference(f"trades[{index}]", item, "C-043")
        if not (internal or exchange or fills or positions or trades):
            raise ExecutionContractError(
                "reconciliation report requires attributable evidence."
            )
        if not isinstance(self.state, ReconciliationState) or not isinstance(
            self.authoritative_source, AuthoritativeSource
        ):
            raise ExecutionContractError("reconciliation state/source is invalid.")
        deltas = _typed_tuple("deltas", self.deltas, ReconciliationDelta)
        _unique("deltas.field_path", tuple(delta.field_path for delta in deltas))
        reasons = _text_tuple("reason_codes", self.reason_codes)
        _text_tuple("resolution_actions", self.resolution_actions)
        _version("reconciler_version", self.reconciler_version)
        _version("policy_version", self.policy_version)
        as_of = _time("as_of", self.as_of)
        started = _time("started_at", self.started_at)
        _ordered("as_of", as_of, "started_at", started)
        object.__setattr__(self, "as_of", as_of)
        object.__setattr__(self, "started_at", started)
        if self.completed_at is not None:
            completed = _time("completed_at", self.completed_at)
            _ordered("started_at", started, "completed_at", completed)
            object.__setattr__(self, "completed_at", completed)
        if self.state is ReconciliationState.IN_SYNC:
            if (
                deltas
                or reasons
                or self.completed_at is None
                or self.authoritative_source is AuthoritativeSource.UNKNOWN
            ):
                raise ExecutionContractError(
                    "IN_SYNC requires completed, known, zero-delta evidence."
                )
            blocked = False
        else:
            if not deltas and not reasons:
                raise ExecutionContractError(
                    "non-sync reconciliation requires deltas or reasons."
                )
            blocked = True
        object.__setattr__(self, "blocks_conflicting_execution", blocked)
        _digest("content_sha256", self.content_sha256)


@dataclass(frozen=True, slots=True)
class ExecutionReport:
    report_id: UUID
    execution_intent: ContractReference
    approval_decision: ContractReference
    signal: ContractReference
    strategy_version: ContractReference
    risk_proposal: ContractReference
    binding: ApprovalBindingHash
    requested_quantity: Decimal
    executed_quantity: Decimal
    approved_entry: PriceValue | None
    actual_average_price: PriceValue | None
    fees: MoneyValue | None
    funding: MoneyValue | None
    slippage: MoneyValue | None
    latency_ms: int | None
    order_ids: tuple[UUID, ...]
    fill_ids: tuple[UUID, ...]
    position: ContractReference | None
    reconciliation_report: ContractReference | None
    status: ExecutionReportStatus
    execution_state: ExecutionState
    order_state: OrderState
    position_state: PositionLifecycle
    reconciliation_state: ReconciliationState
    reason_codes: tuple[str, ...]
    error_codes: tuple[str, ...]
    source_version: VersionReference
    reported_at: datetime
    content_sha256: str
    contract_id: str = field(default="C-095", init=False)
    schema_version: str = field(default=CONTRACT_SCHEMA_VERSION, init=False)

    def __post_init__(self) -> None:
        _uuid("report_id", self.report_id)
        expected = {
            "execution_intent": "C-039",
            "approval_decision": "C-038",
            "signal": "C-070",
            "strategy_version": "C-021",
            "risk_proposal": "C-034",
        }
        for name, contract_id in expected.items():
            _reference(name, getattr(self, name), contract_id)
        if not isinstance(self.binding, ApprovalBindingHash):
            raise ExecutionContractError("binding must be ApprovalBindingHash.")
        if (
            self.binding.signal != self.signal
            or self.binding.strategy_version != self.strategy_version
            or self.binding.risk_proposal != self.risk_proposal
        ):
            raise ExecutionContractError(
                "execution report provenance differs from binding."
            )
        requested = _positive("requested_quantity", self.requested_quantity)
        executed = _nonnegative("executed_quantity", self.executed_quantity)
        if executed > requested:
            raise ExecutionContractError(
                "executed quantity cannot exceed requested quantity."
            )
        if self.approved_entry is not None:
            _price("approved_entry", self.approved_entry)
        if self.actual_average_price is not None:
            _price("actual_average_price", self.actual_average_price)
        values: list[MoneyValue] = []
        for name in ("fees", "slippage"):
            value = getattr(self, name)
            if value is not None:
                values.append(_money(name, value, nonnegative=True))
        if self.funding is not None:
            values.append(_money("funding", self.funding))
        if values and len({value.currency for value in values}) != 1:
            raise ExecutionContractError(
                "execution report money currencies must match."
            )
        if self.latency_ms is not None and (
            not isinstance(self.latency_ms, int)
            or isinstance(self.latency_ms, bool)
            or self.latency_ms < 0
        ):
            raise ExecutionContractError("latency_ms must be a non-negative integer.")
        _uuid_tuple("order_ids", self.order_ids)
        _uuid_tuple("fill_ids", self.fill_ids)
        if self.position is not None:
            _reference("position", self.position, "C-042")
        if self.reconciliation_report is not None:
            _reference("reconciliation_report", self.reconciliation_report, "C-096")
        enum_values = (
            self.status,
            self.execution_state,
            self.order_state,
            self.position_state,
            self.reconciliation_state,
        )
        enum_types = (
            ExecutionReportStatus,
            ExecutionState,
            OrderState,
            PositionLifecycle,
            ReconciliationState,
        )
        if any(
            not isinstance(value, kind)
            for value, kind in zip(enum_values, enum_types, strict=True)
        ):
            raise ExecutionContractError(
                "execution report state vocabulary is invalid."
            )
        reasons = _text_tuple("reason_codes", self.reason_codes)
        errors = _text_tuple("error_codes", self.error_codes)
        if self.status is ExecutionReportStatus.SUCCESS:
            if not self.order_ids or not self.fill_ids:
                raise ExecutionContractError(
                    "SUCCESS requires order and fill identities."
                )
            if (
                executed != requested
                or self.execution_state is not ExecutionState.FILLED
                or self.order_state is not OrderState.FILLED
                or self.reconciliation_state is not ReconciliationState.IN_SYNC
            ):
                raise ExecutionContractError(
                    "SUCCESS requires fully filled, reconciled evidence."
                )
        elif self.status is ExecutionReportStatus.PARTIAL:
            if not 0 < executed < requested:
                raise ExecutionContractError(
                    "PARTIAL requires partial executed quantity."
                )
            if not self.order_ids or not self.fill_ids:
                raise ExecutionContractError(
                    "PARTIAL requires order and fill identities."
                )
        elif not reasons and not errors:
            raise ExecutionContractError(
                "failed/unknown report requires reason or error codes."
            )
        if (
            self.status is ExecutionReportStatus.UNKNOWN
            and self.execution_state
            not in {ExecutionState.UNKNOWN, ExecutionState.RECONCILING}
        ):
            raise ExecutionContractError(
                "UNKNOWN report requires unknown/reconciling execution state."
            )
        _version("source_version", self.source_version)
        object.__setattr__(self, "reported_at", _time("reported_at", self.reported_at))
        _digest("content_sha256", self.content_sha256)


__all__ = [
    "CONTRACT_SCHEMA_VERSION",
    "ApprovalBindingHash",
    "ApprovalDecision",
    "ApprovalDecisionType",
    "ApprovalLifecycle",
    "ApprovalRequest",
    "ApprovedTradeParameters",
    "AuthenticatedActorReference",
    "AuthoritativeSource",
    "ExchangeOrder",
    "ExecutionContractError",
    "ExecutionEnvironment",
    "ExecutionIntent",
    "ExecutionReport",
    "ExecutionReportStatus",
    "ExecutionState",
    "Fill",
    "IdempotencyKey",
    "LiquidityRole",
    "Order",
    "OrderRequest",
    "OrderSide",
    "OrderState",
    "OrderType",
    "Position",
    "PositionLifecycle",
    "ReconciliationDelta",
    "ReconciliationReport",
    "ReconciliationState",
    "TimeInForce",
    "Trade",
    "TradeOutcome",
]
