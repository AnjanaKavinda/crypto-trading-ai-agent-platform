from dataclasses import FrozenInstanceError, fields, replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from trading_platform_api.execution import (
    ApprovalBindingHash,
    ApprovalDecision,
    ApprovalDecisionType,
    ApprovalLifecycle,
    ApprovalRequest,
    ApprovedTradeParameters,
    AuthenticatedActorReference,
    AuthoritativeSource,
    ExchangeOrder,
    ExecutionContractError,
    ExecutionEnvironment,
    ExecutionIntent,
    ExecutionReport,
    ExecutionReportStatus,
    ExecutionState,
    Fill,
    IdempotencyKey,
    LiquidityRole,
    Order,
    OrderRequest,
    OrderSide,
    OrderState,
    OrderType,
    Position,
    PositionLifecycle,
    ReconciliationDelta,
    ReconciliationReport,
    ReconciliationState,
    TimeInForce,
    Trade,
    TradeOutcome,
)
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

T = tuple(datetime(2026, 1, 1, tzinfo=UTC) + timedelta(minutes=i) for i in range(30))
HASH_A = "a" * 64
HASH_B = "b" * 64
HASH_C = "c" * 64
USD = "SYNTHETIC-USD"


def version(component: str = "synthetic-component") -> VersionReference:
    return VersionReference(component, "synthetic-v1", HASH_A)


def ref(contract_id: str, *, digest: str = HASH_A) -> ContractReference:
    return ContractReference(contract_id, uuid4(), "1", digest, T[20])


def price(amount: str = "100") -> PriceValue:
    return PriceValue(Decimal(amount), USD)


def money(amount: str = "1") -> MoneyValue:
    return MoneyValue(Decimal(amount), USD)


def ratio(amount: str = "0.01", meaning: str = "synthetic-ratio") -> RatioValue:
    return RatioValue(Decimal(amount), meaning)


def target(sequence: int = 1, amount: str = "120") -> TakeProfitTarget:
    return TakeProfitTarget(
        sequence, price(amount), ratio("1", "allocation"), money("20")
    )


def parameters(**overrides: object) -> ApprovedTradeParameters:
    values: dict[str, object] = {
        "exchange_id": "synthetic-exchange",
        "account_id": uuid4(),
        "instrument_id": "SYNTHETIC-BTC-USD",
        "position_side": PositionSide.LONG,
        "order_side": OrderSide.BUY,
        "order_type": OrderType.LIMIT,
        "quantity": Decimal("2"),
        "limit_price": price("100"),
        "trigger_price": None,
        "stop_loss": price("90"),
        "take_profit_targets": (target(),),
        "leverage": Decimal("2"),
        "margin_mode": MarginMode.ISOLATED,
        "reduce_only": False,
        "post_only": False,
        "time_in_force": TimeInForce.GTC,
        "maximum_slippage": ratio("0.005", "maximum-slippage"),
        "environment": ExecutionEnvironment.PAPER,
        "content_sha256": HASH_A,
    }
    values.update(overrides)
    return ApprovedTradeParameters(**values)  # type: ignore[arg-type]


def binding(
    params: ApprovedTradeParameters | None = None, **overrides: object
) -> ApprovalBindingHash:
    params = params or parameters()
    values: dict[str, object] = {
        "digest": HASH_B,
        "algorithm": "SHA-256",
        "canonicalization_version": "canonical-json-v1",
        "signal": ref("C-070"),
        "evidence_package": ref("C-024"),
        "strategy_version": ref("C-021"),
        "validation": ref("C-028"),
        "risk_proposal": ref("C-034"),
        "account_snapshot": ref("C-032"),
        "portfolio_snapshot": ref("C-033"),
        "parameters_sha256": params.content_sha256,
    }
    values.update(overrides)
    return ApprovalBindingHash(**values)  # type: ignore[arg-type]


def approval_request(**overrides: object) -> ApprovalRequest:
    params = overrides.pop("parameters", parameters())
    assert isinstance(params, ApprovedTradeParameters)
    bound = overrides.pop("binding", binding(params))
    assert isinstance(bound, ApprovalBindingHash)
    values: dict[str, object] = {
        "request_id": uuid4(),
        "revision": 1,
        "supersedes_request_id": None,
        "risk_proposal": bound.risk_proposal,
        "risk_revalidation": None,
        "parameters": params,
        "binding": bound,
        "intended_approver_subject": "synthetic-human",
        "lifecycle": ApprovalLifecycle.PRESENTED,
        "reason_codes": (),
        "warnings": (),
        "human_modifiable_fields": ("leverage", "stop_loss"),
        "policy_version": version("approval-policy"),
        "configuration_version": version("approval-configuration"),
        "as_of": T[0],
        "created_at": T[1],
        "presented_at": T[2],
        "expires_at": T[15],
        "content_sha256": HASH_C,
    }
    values.update(overrides)
    return ApprovalRequest(**values)  # type: ignore[arg-type]


def actor(**overrides: object) -> AuthenticatedActorReference:
    values: dict[str, object] = {
        "subject_id": "synthetic-human",
        "authentication_context_ref": "synthetic-auth-context",
        "authentication_method": "synthetic-mfa",
        "assurance_level": "synthetic-high",
        "session_ref": "synthetic-session",
        "authenticated_at": T[2],
    }
    values.update(overrides)
    return AuthenticatedActorReference(**values)  # type: ignore[arg-type]


def approval_decision(**overrides: object) -> ApprovalDecision:
    request = overrides.pop("request", approval_request())
    assert isinstance(request, ApprovalRequest)
    values: dict[str, object] = {
        "decision_id": uuid4(),
        "request": request,
        "binding": request.binding,
        "actor": actor(subject_id=request.intended_approver_subject),
        "decision": ApprovalDecisionType.APPROVE,
        "confirmation": "Synthetic explicit approval for contract testing only.",
        "correlation_id": uuid4(),
        "policy_version": request.policy_version,
        "decided_at": T[3],
        "valid_until": T[14],
        "content_sha256": HASH_A,
    }
    values.update(overrides)
    return ApprovalDecision(**values)  # type: ignore[arg-type]


def idempotency(**overrides: object) -> IdempotencyKey:
    values: dict[str, object] = {
        "namespace": "synthetic-order",
        "key": "synthetic-key-1",
        "request_sha256": HASH_B,
        "created_at": T[3],
        "expires_at": T[13],
    }
    values.update(overrides)
    return IdempotencyKey(**values)  # type: ignore[arg-type]


def intent(**overrides: object) -> ExecutionIntent:
    decision = overrides.pop("approval_decision", approval_decision())
    assert isinstance(decision, ApprovalDecision)
    values: dict[str, object] = {
        "intent_id": uuid4(),
        "approval_decision": decision,
        "risk_proposal": decision.request.risk_proposal,
        "risk_revalidation": decision.request.risk_revalidation,
        "safety_decision": ref("C-058"),
        "readiness_state": ref("C-059"),
        "parameters": decision.request.parameters,
        "binding": decision.binding,
        "idempotency_key": idempotency(),
        "state": ExecutionState.READY,
        "reason_codes": (),
        "policy_version": version("execution-policy"),
        "configuration_version": version("execution-configuration"),
        "as_of": T[3],
        "created_at": T[4],
        "valid_until": T[12],
        "content_sha256": HASH_A,
    }
    values.update(overrides)
    return ExecutionIntent(**values)  # type: ignore[arg-type]


def order_request(**overrides: object) -> OrderRequest:
    value = overrides.pop("intent", intent())
    assert isinstance(value, ExecutionIntent)
    key = idempotency(request_sha256=HASH_B)
    value = replace(value, idempotency_key=key)
    values: dict[str, object] = {
        "request_id": uuid4(),
        "intent": value,
        "parameters": value.parameters,
        "binding": value.binding,
        "idempotency_key": key,
        "client_order_id": "synthetic-client-order",
        "state": ExecutionState.READY,
        "request_version": version("order-request"),
        "constructed_at": T[5],
        "content_sha256": HASH_B,
    }
    values.update(overrides)
    return OrderRequest(**values)  # type: ignore[arg-type]


def order(**overrides: object) -> Order:
    fill_id = uuid4()
    values: dict[str, object] = {
        "order_id": uuid4(),
        "order_request_id": uuid4(),
        "intent_id": uuid4(),
        "client_order_id": "synthetic-client-order",
        "exchange_order_id": "synthetic-exchange-order",
        "exchange_id": "synthetic-exchange",
        "account_id": uuid4(),
        "instrument_id": "SYNTHETIC-BTC-USD",
        "side": OrderSide.BUY,
        "order_type": OrderType.LIMIT,
        "state": OrderState.FILLED,
        "requested_quantity": Decimal("2"),
        "filled_quantity": Decimal("2"),
        "remaining_quantity": Decimal("0"),
        "requested_price": price("100"),
        "average_price": price("100.5"),
        "trigger_price": None,
        "fill_ids": (fill_id,),
        "state_reason": None,
        "record_version": version("internal-order"),
        "created_at": T[5],
        "updated_at": T[7],
        "exchange_timestamp": T[6],
        "content_sha256": HASH_A,
    }
    values.update(overrides)
    return Order(**values)  # type: ignore[arg-type]


def exchange_order(**overrides: object) -> ExchangeOrder:
    values: dict[str, object] = {
        "observation_id": uuid4(),
        "exchange_order_id": "synthetic-exchange-order",
        "client_order_id": "synthetic-client-order",
        "exchange_id": "synthetic-exchange",
        "account_id": uuid4(),
        "instrument_id": "SYNTHETIC-BTC-USD",
        "state": OrderState.FILLED,
        "native_status": "synthetic-closed",
        "requested_quantity": Decimal("2"),
        "executed_quantity": Decimal("2"),
        "remaining_quantity": Decimal("0"),
        "average_price": price("100.5"),
        "exchange_timestamp": T[6],
        "observed_at": T[7],
        "source_version": version("synthetic-adapter"),
        "raw_response_sha256": HASH_A,
        "content_sha256": HASH_B,
    }
    values.update(overrides)
    return ExchangeOrder(**values)  # type: ignore[arg-type]


def fill(**overrides: object) -> Fill:
    values: dict[str, object] = {
        "fill_id": uuid4(),
        "order_id": uuid4(),
        "exchange_order_id": "synthetic-exchange-order",
        "exchange_fill_id": "synthetic-fill-1",
        "exchange_id": "synthetic-exchange",
        "account_id": uuid4(),
        "instrument_id": "SYNTHETIC-BTC-USD",
        "quantity": Decimal("2"),
        "price": price("100.5"),
        "fee": money("0.2"),
        "liquidity_role": LiquidityRole.MAKER,
        "exchange_timestamp": T[6],
        "observed_at": T[7],
        "source_version": version("synthetic-adapter"),
        "content_sha256": HASH_A,
    }
    values.update(overrides)
    return Fill(**values)  # type: ignore[arg-type]


def position(**overrides: object) -> Position:
    values: dict[str, object] = {
        "position_id": uuid4(),
        "account_id": uuid4(),
        "instrument_id": "SYNTHETIC-BTC-USD",
        "side": PositionSide.LONG,
        "lifecycle": PositionLifecycle.OPEN,
        "reconciliation_state": ReconciliationState.IN_SYNC,
        "quantity": Decimal("2"),
        "entry_price": price("100.5"),
        "mark_price": price("101"),
        "realized_pnl": money("0"),
        "unrealized_pnl": money("1"),
        "leverage": Decimal("2"),
        "margin_mode": MarginMode.ISOLATED,
        "margin_used": money("100"),
        "order_ids": (uuid4(),),
        "fill_ids": (uuid4(),),
        "source_version": version("position-source"),
        "as_of": T[7],
        "observed_at": T[8],
        "content_sha256": HASH_A,
    }
    values.update(overrides)
    return Position(**values)  # type: ignore[arg-type]


def trade(**overrides: object) -> Trade:
    bound = overrides.pop("binding", binding())
    assert isinstance(bound, ApprovalBindingHash)
    values: dict[str, object] = {
        "trade_id": uuid4(),
        "execution_intent": ref("C-039"),
        "approval_decision": ref("C-038"),
        "risk_proposal": bound.risk_proposal,
        "signal": bound.signal,
        "strategy_version": bound.strategy_version,
        "binding": bound,
        "account_id": uuid4(),
        "exchange_id": "synthetic-exchange",
        "instrument_id": "SYNTHETIC-BTC-USD",
        "environment": ExecutionEnvironment.PAPER,
        "position_lifecycle": PositionLifecycle.CLOSED,
        "order_ids": (uuid4(),),
        "fill_ids": (uuid4(),),
        "position_id": uuid4(),
        "execution_policy_version": version("execution-policy"),
        "opened_at": T[7],
        "closed_at": T[10],
        "content_sha256": HASH_A,
    }
    values.update(overrides)
    return Trade(**values)  # type: ignore[arg-type]


def delta(**overrides: object) -> ReconciliationDelta:
    values: dict[str, object] = {
        "field_path": "order.state",
        "internal_value_sha256": HASH_A,
        "exchange_value_sha256": HASH_B,
        "classification": "synthetic-state-drift",
        "explanation": "Synthetic mismatch for deterministic contract testing.",
    }
    values.update(overrides)
    return ReconciliationDelta(**values)  # type: ignore[arg-type]


def reconciliation(**overrides: object) -> ReconciliationReport:
    values: dict[str, object] = {
        "report_id": uuid4(),
        "scope": "synthetic-order-scope",
        "internal_orders": (ref("C-040"),),
        "exchange_orders": (exchange_order(),),
        "fills": (fill(),),
        "positions": (ref("C-042"),),
        "trades": (ref("C-043"),),
        "state": ReconciliationState.IN_SYNC,
        "authoritative_source": AuthoritativeSource.EXCHANGE,
        "deltas": (),
        "reason_codes": (),
        "resolution_actions": ("synthetic-comparison-complete",),
        "reconciler_version": version("reconciler"),
        "policy_version": version("reconciliation-policy"),
        "as_of": T[7],
        "started_at": T[8],
        "completed_at": T[9],
        "content_sha256": HASH_A,
    }
    values.update(overrides)
    return ReconciliationReport(**values)  # type: ignore[arg-type]


def outcome(**overrides: object) -> TradeOutcome:
    values: dict[str, object] = {
        "outcome_id": uuid4(),
        "trade": ref("C-043"),
        "actual_entry": price("100"),
        "actual_exit": price("110"),
        "executed_quantity": Decimal("2"),
        "realized_pnl": money("20"),
        "fees": money("1"),
        "funding": money("-0.1"),
        "slippage": money("0.5"),
        "maximum_adverse_excursion": money("2"),
        "maximum_favorable_excursion": money("25"),
        "order_ids": (uuid4(),),
        "fill_ids": (uuid4(),),
        "reconciliation_report": ref("C-096"),
        "method_version": version("outcome-method"),
        "opened_at": T[7],
        "closed_at": T[10],
        "evaluated_at": T[11],
        "content_sha256": HASH_A,
    }
    values.update(overrides)
    return TradeOutcome(**values)  # type: ignore[arg-type]


def execution_report(**overrides: object) -> ExecutionReport:
    bound = overrides.pop("binding", binding())
    assert isinstance(bound, ApprovalBindingHash)
    values: dict[str, object] = {
        "report_id": uuid4(),
        "execution_intent": ref("C-039"),
        "approval_decision": ref("C-038"),
        "signal": bound.signal,
        "strategy_version": bound.strategy_version,
        "risk_proposal": bound.risk_proposal,
        "binding": bound,
        "requested_quantity": Decimal("2"),
        "executed_quantity": Decimal("2"),
        "approved_entry": price("100"),
        "actual_average_price": price("100.5"),
        "fees": money("1"),
        "funding": money("0"),
        "slippage": money("0.5"),
        "latency_ms": 15,
        "order_ids": (uuid4(),),
        "fill_ids": (uuid4(),),
        "position": ref("C-042"),
        "reconciliation_report": ref("C-096"),
        "status": ExecutionReportStatus.SUCCESS,
        "execution_state": ExecutionState.FILLED,
        "order_state": OrderState.FILLED,
        "position_state": PositionLifecycle.CLOSED,
        "reconciliation_state": ReconciliationState.IN_SYNC,
        "reason_codes": (),
        "error_codes": (),
        "source_version": version("execution-reporter"),
        "reported_at": T[12],
        "content_sha256": HASH_A,
    }
    values.update(overrides)
    return ExecutionReport(**values)  # type: ignore[arg-type]


def test_canonical_contract_ids_and_schema_versions() -> None:
    instances = (
        approval_request(),
        approval_decision(),
        intent(),
        order(),
        fill(),
        position(),
        trade(),
        outcome(),
        order_request(),
        exchange_order(),
        execution_report(),
        reconciliation(),
    )
    assert tuple(item.contract_id for item in instances) == (
        "C-037",
        "C-038",
        "C-039",
        "C-040",
        "C-041",
        "C-042",
        "C-043",
        "C-044",
        "C-084",
        "C-085",
        "C-095",
        "C-096",
    )
    assert {item.schema_version for item in instances} == {"1"}


def test_authoritative_enum_vocabularies_are_exact() -> None:
    assert {item.value for item in ExecutionState} == {
        "INTENT_CREATED",
        "PRE_EXECUTION_VALIDATION",
        "READY",
        "SUBMITTING",
        "SUBMITTED",
        "PARTIALLY_FILLED",
        "FILLED",
        "CANCEL_PENDING",
        "CANCELLED",
        "REJECTED",
        "FAILED",
        "UNKNOWN",
        "RECONCILING",
        "RECONCILED",
    }
    assert {item.value for item in ApprovalLifecycle} == {
        "CREATED",
        "PRESENTED",
        "MODIFIED",
        "REVALIDATION_REQUIRED",
        "APPROVED",
        "REJECTED",
        "EXPIRED",
        "CANCELLED",
    }
    assert {item.value for item in ReconciliationState} == {
        "IN_SYNC",
        "DRIFT_DETECTED",
        "RECONCILIATION_REQUIRED",
        "RECONCILIATION_FAILED",
        "UNKNOWN",
    }


def test_contracts_are_frozen_slotted_and_collections_are_tuples() -> None:
    request = approval_request()
    assert "__dict__" not in dir(request)
    with pytest.raises(FrozenInstanceError):
        request.request_id = uuid4()  # type: ignore[misc]
    with pytest.raises(ExecutionContractError, match="tuple"):
        approval_request(warnings=["not-immutable"])
    assert all(field_info.name for field_info in fields(request))


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"quantity": Decimal("NaN")}, "finite Decimal"),
        ({"quantity": 2.0}, "finite Decimal"),
        ({"exchange_id": " "}, "must not be blank"),
        ({"content_sha256": "ABC"}, "lowercase SHA-256"),
        (
            {"post_only": True, "order_type": OrderType.MARKET, "limit_price": None},
            "post_only",
        ),
    ],
)
def test_parameters_reject_invalid_primitive_and_order_combinations(
    overrides: dict[str, object], message: str
) -> None:
    with pytest.raises(ExecutionContractError, match=message):
        parameters(**overrides)
    with pytest.raises(ExecutionContractError, match="currencies"):
        parameters(stop_loss=PriceValue(Decimal("90"), "OTHER-CURRENCY"))


def test_approval_binding_requires_every_hashed_canonical_reference() -> None:
    for name, contract_id in {
        "signal": "C-070",
        "evidence_package": "C-024",
        "strategy_version": "C-021",
        "validation": "C-028",
        "risk_proposal": "C-034",
        "account_snapshot": "C-032",
        "portfolio_snapshot": "C-033",
    }.items():
        with pytest.raises(ExecutionContractError, match=name):
            binding(**{name: ref(contract_id, digest=None)})  # type: ignore[arg-type]
    with pytest.raises(ExecutionContractError, match="must reference C-070"):
        binding(signal=ref("C-023"))


def test_parameter_change_cannot_reuse_previous_binding() -> None:
    changed = parameters(content_sha256=HASH_C, leverage=Decimal("3"))
    with pytest.raises(ExecutionContractError, match="binding mismatch"):
        approval_request(parameters=changed, binding=binding(parameters()))


def test_request_cannot_approve_itself_and_modified_request_needs_reasons() -> None:
    with pytest.raises(ExecutionContractError, match="cannot approve itself"):
        approval_request(lifecycle=ApprovalLifecycle.APPROVED)
    with pytest.raises(ExecutionContractError, match="reason_codes"):
        approval_request(lifecycle=ApprovalLifecycle.REVALIDATION_REQUIRED)
    revised = approval_request(
        request_id=uuid4(),
        revision=2,
        supersedes_request_id=uuid4(),
        risk_revalidation=ref("C-083"),
        lifecycle=ApprovalLifecycle.REVALIDATION_REQUIRED,
        reason_codes=("synthetic-parameter-change",),
    )
    assert revised.revision == 2
    with pytest.raises(ExecutionContractError, match="risk revalidation"):
        approval_request(
            request_id=uuid4(),
            revision=2,
            supersedes_request_id=uuid4(),
        )


def test_approval_requires_explicit_authenticated_intended_actor() -> None:
    request = approval_request()
    with pytest.raises(ExecutionContractError, match="intended approver"):
        approval_decision(request=request, actor=actor(subject_id="different-human"))
    with pytest.raises(ExecutionContractError, match="outlive"):
        approval_decision(request=request, decided_at=T[16], valid_until=T[17])
    rejected = approval_decision(
        request=request,
        decision=ApprovalDecisionType.REJECT,
        confirmation="Synthetic explicit rejection.",
    )
    assert rejected.lifecycle is ApprovalLifecycle.REJECTED


def test_rejected_or_mismatched_approval_cannot_progress_execution() -> None:
    rejected = approval_decision(
        decision=ApprovalDecisionType.REJECT,
        confirmation="Synthetic explicit rejection.",
    )
    with pytest.raises(ExecutionContractError, match="explicitly approved"):
        intent(approval_decision=rejected)
    approved = approval_decision()
    with pytest.raises(ExecutionContractError, match="binding must match"):
        intent(approval_decision=approved, binding=binding(parameters()))


def test_unknown_intent_requires_reason_and_cannot_create_order_request() -> None:
    with pytest.raises(ExecutionContractError, match="reason_codes"):
        intent(state=ExecutionState.UNKNOWN)
    unknown = intent(state=ExecutionState.UNKNOWN, reason_codes=("synthetic-timeout",))
    with pytest.raises(ExecutionContractError, match="READY intent"):
        order_request(intent=unknown)


def test_order_request_is_exactly_bound_and_idempotent() -> None:
    request = order_request()
    assert request.parameters == request.intent.parameters
    assert request.idempotency_key.request_sha256 == request.content_sha256
    with pytest.raises(ExecutionContractError, match="differs from approved intent"):
        replace(request, parameters=parameters(content_sha256=HASH_C))
    with pytest.raises(ExecutionContractError, match="bind request content"):
        replace(request, content_sha256=HASH_C)


def test_order_request_internal_order_and_exchange_order_are_distinct() -> None:
    assert type(order_request()) is OrderRequest
    assert type(order()) is Order
    assert type(exchange_order()) is ExchangeOrder


def test_internal_and_exchange_order_quantity_state_invariants() -> None:
    with pytest.raises(ExecutionContractError, match="filled plus remaining"):
        order(remaining_quantity=Decimal("1"))
    partial_id = uuid4()
    partial = order(
        state=OrderState.PARTIALLY_FILLED,
        filled_quantity=Decimal("1"),
        remaining_quantity=Decimal("1"),
        fill_ids=(partial_id,),
    )
    assert partial.state is OrderState.PARTIALLY_FILLED
    with pytest.raises(ExecutionContractError, match="cannot contain fills"):
        order(
            state=OrderState.OPEN,
            filled_quantity=Decimal("1"),
            remaining_quantity=Decimal("1"),
            fill_ids=(uuid4(),),
        )
    unknown = exchange_order(
        state=OrderState.UNKNOWN,
        native_status="synthetic-unmapped-exchange-status",
        executed_quantity=Decimal("0"),
        remaining_quantity=Decimal("2"),
        average_price=None,
    )
    assert unknown.state is OrderState.UNKNOWN
    assert unknown.average_price is None


def test_fill_requires_attributable_positive_observed_facts() -> None:
    with pytest.raises(ExecutionContractError, match="quantity must be positive"):
        fill(quantity=Decimal("0"))
    with pytest.raises(ExecutionContractError, match="fee must be non-negative"):
        fill(fee=money("-1"))
    value = fill()
    assert value.exchange_fill_id == "synthetic-fill-1"


def test_position_lifecycle_and_reconciliation_fail_closed() -> None:
    with pytest.raises(ExecutionContractError, match="open position"):
        position(quantity=Decimal("0"))
    with pytest.raises(ExecutionContractError, match="orders, and fills"):
        position(order_ids=())
    closed = position(
        lifecycle=PositionLifecycle.CLOSED,
        quantity=Decimal("0"),
        unrealized_pnl=money("0"),
    )
    assert closed.quantity == 0
    with pytest.raises(ExecutionContractError, match="cannot be in sync"):
        position(
            lifecycle=PositionLifecycle.RECONCILIATION_REQUIRED,
            reconciliation_state=ReconciliationState.IN_SYNC,
        )
    with pytest.raises(ExecutionContractError, match="cannot be in sync"):
        position(
            lifecycle=PositionLifecycle.UNKNOWN,
            reconciliation_state=ReconciliationState.IN_SYNC,
        )


def test_trade_requires_exact_binding_lineage_and_unique_children() -> None:
    bound = binding()
    with pytest.raises(ExecutionContractError, match="provenance"):
        trade(binding=bound, signal=ref("C-070", digest=HASH_C))
    with pytest.raises(ExecutionContractError, match="duplicates"):
        child = uuid4()
        trade(order_ids=(child, child))


def test_trade_outcome_is_factual_and_cannot_hide_unknown_values() -> None:
    value = outcome()
    assert value.is_factual is True
    assert "is_factual" not in {
        field_info.name for field_info in fields(TradeOutcome) if field_info.init
    }
    with pytest.raises(ExecutionContractError, match="non-negative"):
        outcome(fees=money("-1"))
    with pytest.raises(ExecutionContractError, match="must be a MoneyValue"):
        outcome(slippage=Decimal("0"))


def test_reconciliation_in_sync_and_drift_are_unambiguous() -> None:
    synchronized = reconciliation()
    assert synchronized.blocks_conflicting_execution is False
    with pytest.raises(ExecutionContractError, match="zero-delta"):
        reconciliation(deltas=(delta(),))
    drift = reconciliation(
        state=ReconciliationState.DRIFT_DETECTED,
        authoritative_source=AuthoritativeSource.EXCHANGE,
        deltas=(delta(),),
        reason_codes=("synthetic-drift",),
        completed_at=None,
    )
    assert drift.blocks_conflicting_execution is True
    with pytest.raises(ExecutionContractError, match="deltas or reasons"):
        reconciliation(
            state=ReconciliationState.UNKNOWN,
            authoritative_source=AuthoritativeSource.UNKNOWN,
            completed_at=None,
        )
    with pytest.raises(ExecutionContractError, match="attributable evidence"):
        reconciliation(
            internal_orders=(),
            exchange_orders=(),
            fills=(),
            positions=(),
            trades=(),
        )


def test_execution_report_preserves_success_partial_failure_and_unknown() -> None:
    assert execution_report().status is ExecutionReportStatus.SUCCESS
    partial = execution_report(
        status=ExecutionReportStatus.PARTIAL,
        execution_state=ExecutionState.PARTIALLY_FILLED,
        order_state=OrderState.PARTIALLY_FILLED,
        executed_quantity=Decimal("1"),
        reconciliation_state=ReconciliationState.RECONCILIATION_REQUIRED,
        reason_codes=("synthetic-partial-fill",),
    )
    assert partial.executed_quantity == Decimal("1")
    unknown = execution_report(
        status=ExecutionReportStatus.UNKNOWN,
        execution_state=ExecutionState.UNKNOWN,
        order_state=OrderState.UNKNOWN,
        executed_quantity=Decimal("0"),
        actual_average_price=None,
        reconciliation_state=ReconciliationState.UNKNOWN,
        reason_codes=("synthetic-uncertain-submission",),
    )
    assert unknown.status is ExecutionReportStatus.UNKNOWN
    assert unknown.reconciliation_state is ReconciliationState.UNKNOWN
    with pytest.raises(ExecutionContractError, match="fully filled"):
        execution_report(executed_quantity=Decimal("1"))
    with pytest.raises(ExecutionContractError, match="order and fill identities"):
        execution_report(order_ids=(), fill_ids=())


def test_unknown_submission_never_implies_retry_or_reconciled_success() -> None:
    report = execution_report(
        status=ExecutionReportStatus.UNKNOWN,
        execution_state=ExecutionState.RECONCILING,
        order_state=OrderState.UNKNOWN,
        executed_quantity=Decimal("0"),
        actual_average_price=None,
        reconciliation_state=ReconciliationState.RECONCILIATION_REQUIRED,
        reason_codes=("reconcile-before-any-retry",),
    )
    assert "retry" not in {field_info.name for field_info in fields(report)}
    assert report.status is not ExecutionReportStatus.SUCCESS


def test_no_runtime_execution_provider_or_secret_surface_is_introduced() -> None:
    source = Path("apps/api/src/trading_platform_api/execution/contracts.py").read_text(
        encoding="utf-8"
    )
    forbidden = (
        "import ccxt",
        "import requests",
        "import httpx",
        "FastAPI",
        "APIRouter",
        "api_key",
        "secret_key",
        "submit_order(",
        "create_order(",
    )
    assert all(token not in source for token in forbidden)
    assert "LIVE TRADING" not in source


def test_public_contract_identifiers_are_actual_uuids() -> None:
    with pytest.raises(ExecutionContractError, match="UUID"):
        approval_request(request_id="not-a-uuid")
    assert isinstance(approval_request().request_id, UUID)
