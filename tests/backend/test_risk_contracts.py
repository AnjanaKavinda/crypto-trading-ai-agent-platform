from dataclasses import FrozenInstanceError, fields, replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from trading_platform_api.risk import (
    AccountSnapshot,
    ContractReference,
    ExposureValue,
    LeverageAssessment,
    LiquidationAssessment,
    LiquidationAvailability,
    MarginMode,
    MoneyValue,
    PortfolioImpact,
    PortfolioSnapshot,
    PositionSide,
    PositionSizingResult,
    PositionSnapshot,
    PriceValue,
    RatioValue,
    RevalidationStatus,
    RevalidationTrigger,
    RiskAssessment,
    RiskCheckOutcome,
    RiskContext,
    RiskContractError,
    RiskDecision,
    RiskLimitResult,
    RiskLimitSeverity,
    RiskProposal,
    RiskRevalidationResult,
    RiskState,
    RiskVerdict,
    SizingMethod,
    SnapshotState,
    StopLossAssessment,
    StressScenarioResult,
    StressTestResult,
    TakeProfitAssessment,
    TakeProfitTarget,
    VersionReference,
)

T = tuple(datetime(2026, 1, 1, tzinfo=UTC) + timedelta(days=i) for i in range(20))
HASH_A = "a" * 64
USD = "SYNTHETIC-USD"


def version(component: str = "synthetic-model") -> VersionReference:
    return VersionReference(component, "synthetic-v1", HASH_A)


def money(amount: str = "100") -> MoneyValue:
    return MoneyValue(Decimal(amount), USD)


def price(amount: str = "100") -> PriceValue:
    return PriceValue(Decimal(amount), USD)


def ratio(amount: str = "0.10", meaning: str = "synthetic-ratio") -> RatioValue:
    return RatioValue(Decimal(amount), meaning)


def ref(contract_id: str, *, valid_until: datetime | None = T[14]) -> ContractReference:
    return ContractReference(contract_id, uuid4(), "1", HASH_A, valid_until)


def limit(
    *,
    severity: RiskLimitSeverity = RiskLimitSeverity.HARD,
    outcome: RiskCheckOutcome = RiskCheckOutcome.PASSED,
    limit_id: str = "synthetic-limit",
) -> RiskLimitResult:
    return RiskLimitResult(
        limit_id,
        severity,
        Decimal("0.10"),
        Decimal("0.20"),
        "ratio",
        outcome,
        "Synthetic deterministic fixture only.",
    )


def account(**overrides: object) -> AccountSnapshot:
    values: dict[str, object] = {
        "snapshot_id": uuid4(),
        "account_id": uuid4(),
        "source_id": "synthetic-account-source",
        "state": SnapshotState.VALID,
        "reason_codes": (),
        "currency": USD,
        "equity": money("10000"),
        "available_balance": money("8000"),
        "used_margin": money("1000"),
        "free_margin": money("7000"),
        "unrealized_pnl": money("-10"),
        "realized_pnl": money("20"),
        "daily_pnl": money("5"),
        "weekly_pnl": money("10"),
        "current_drawdown": ratio("0.01", "drawdown"),
        "source_version": version("account-source"),
        "as_of": T[0],
        "captured_at": T[1],
        "valid_until": T[15],
        "content_sha256": HASH_A,
    }
    values.update(overrides)
    return AccountSnapshot(**values)  # type: ignore[arg-type]


def target(sequence: int = 1, allocation: str = "1") -> TakeProfitTarget:
    return TakeProfitTarget(
        sequence, price("120"), ratio(allocation, "allocation"), money("20")
    )


def position(account_id: UUID, **overrides: object) -> PositionSnapshot:
    values: dict[str, object] = {
        "snapshot_id": uuid4(),
        "account_id": account_id,
        "position_id": uuid4(),
        "state": SnapshotState.VALID,
        "reason_codes": (),
        "asset": "SYNTHETIC-BTC",
        "instrument_id": "SYNTHETIC-BTC-USD",
        "side": PositionSide.LONG,
        "margin_mode": MarginMode.ISOLATED,
        "quantity": Decimal("1"),
        "entry_price": price("100"),
        "mark_price": price("101"),
        "notional": money("101"),
        "leverage": Decimal("2"),
        "margin_used": money("50.5"),
        "unrealized_pnl": money("1"),
        "liquidation_price": price("50"),
        "stop_loss": price("90"),
        "take_profit_targets": (target(),),
        "order_ids": (uuid4(),),
        "fill_ids": (uuid4(),),
        "source_version": version("position-source"),
        "as_of": T[0],
        "captured_at": T[1],
        "valid_until": T[14],
        "content_sha256": HASH_A,
    }
    values.update(overrides)
    return PositionSnapshot(**values)  # type: ignore[arg-type]


def exposure(key: str = "LONG") -> ExposureValue:
    return ExposureValue("direction", key, money("100"), money("10"), ratio("0.01"))


def portfolio(
    account_value: AccountSnapshot | None = None, **overrides: object
) -> PortfolioSnapshot:
    account_value = account_value or account()
    values: dict[str, object] = {
        "snapshot_id": uuid4(),
        "account_snapshot": account_value,
        "state": SnapshotState.VALID,
        "reason_codes": (),
        "positions": (position(account_value.account_id),),
        "currency": USD,
        "equity": money("10000"),
        "cash": money("8000"),
        "margin": money("1000"),
        "pending_risk": money("50"),
        "total_exposure": money("100"),
        "gross_exposure": money("100"),
        "net_exposure": money("100"),
        "directional_exposures": (exposure(),),
        "asset_exposures": (exposure("SYNTHETIC-BTC"),),
        "strategy_exposures": (exposure("synthetic-strategy"),),
        "correlated_exposures": (exposure("synthetic-crypto"),),
        "drawdown": ratio("0.01", "drawdown"),
        "volatility": ratio("0.20", "volatility"),
        "gross_leverage": Decimal("0.01"),
        "net_leverage": Decimal("0.01"),
        "source_version": version("portfolio-source"),
        "as_of": T[1],
        "captured_at": T[2],
        "valid_until": T[14],
        "content_sha256": HASH_A,
    }
    values.update(overrides)
    return PortfolioSnapshot(**values)  # type: ignore[arg-type]


def context() -> RiskContext:
    return RiskContext(
        ref("C-070"),
        ref("C-028"),
        ref("C-021"),
        ref("C-032"),
        ref("C-033"),
        "SYNTHETIC-BTC",
        "SYNTHETIC-BTC-USD",
        PositionSide.LONG,
        T[3],
    )


def base(ctx: RiskContext | None = None) -> dict[str, object]:
    return {
        "result_id": uuid4(),
        "context": ctx or context(),
        "outcome": RiskCheckOutcome.PASSED,
        "reason_codes": (),
        "model_version": version(),
        "as_of": T[3],
        "evaluated_at": T[4],
        "valid_until": T[12],
        "content_sha256": HASH_A,
    }


def sizing(ctx: RiskContext | None = None, **overrides: object) -> PositionSizingResult:
    values = {
        **base(ctx),
        "method": SizingMethod.RISK_BASED,
        "sizing_assumptions": (version("sizing"), version("cost")),
        "requested_risk": money("100"),
        "requested_notional": money("1000"),
        "recommended_quantity": Decimal("1"),
        "recommended_notional": money("1000"),
        "recommended_margin": money("500"),
        "stop_distance": Decimal("10"),
        "maximum_loss": money("100"),
        "account_risk": ratio("0.01", "account-risk"),
        "minimum_quantity": Decimal("0.001"),
        "maximum_quantity": Decimal("10"),
        "quantity_step": Decimal("0.001"),
    }
    values.update(overrides)
    return PositionSizingResult(**values)  # type: ignore[arg-type]


def leverage(ctx: RiskContext | None = None, **overrides: object) -> LeverageAssessment:
    values = {
        **base(ctx),
        "requested_leverage": Decimal("2"),
        "maximum_permitted_leverage": Decimal("5"),
        "effective_leverage": Decimal("2"),
        "post_trade_portfolio_leverage": Decimal("0.2"),
        "margin_mode": MarginMode.ISOLATED,
        "initial_margin": money("500"),
        "maintenance_margin": money("100"),
        "proposed_margin": money("500"),
        "post_trade_free_margin": money("6500"),
        "exchange_constraints": version("exchange-constraints"),
        "limits": (limit(limit_id="leverage-limit"),),
    }
    values.update(overrides)
    return LeverageAssessment(**values)  # type: ignore[arg-type]


def liquidation(
    ctx: RiskContext | None = None, **overrides: object
) -> LiquidationAssessment:
    values = {
        **base(ctx),
        "availability": LiquidationAvailability.AVAILABLE,
        "margin_mode": MarginMode.ISOLATED,
        "entry_price": price("100"),
        "stop_loss": price("90"),
        "liquidation_price": price("50"),
        "entry_to_liquidation": ratio("0.50", "entry-to-liquidation"),
        "stop_to_liquidation": ratio("0.44", "stop-to-liquidation"),
        "minimum_distance": ratio("0.20", "minimum-distance"),
        "volatility_relationship": "Outside synthetic volatility boundary.",
        "stress_relationship": "Outside synthetic stress boundary.",
        "formula_version": version("liquidation-formula"),
        "exchange_constraints": version("exchange-constraints"),
    }
    values.update(overrides)
    return LiquidationAssessment(**values)  # type: ignore[arg-type]


def stop(ctx: RiskContext | None = None, **overrides: object) -> StopLossAssessment:
    values = {
        **base(ctx),
        "side": PositionSide.LONG,
        "entry_price": price("100"),
        "stop_loss": price("90"),
        "stop_distance": Decimal("10"),
        "stop_distance_ratio": ratio("0.10", "stop-distance"),
        "maximum_loss": money("100"),
        "cost_assumptions": (version("fee"), version("slippage")),
        "strategy_invalidation": ref("C-023"),
        "structural_check": RiskCheckOutcome.PASSED,
        "volatility_check": RiskCheckOutcome.PASSED,
        "liquidation_check": RiskCheckOutcome.PASSED,
        "limits": (limit(limit_id="stop-limit"),),
    }
    values.update(overrides)
    return StopLossAssessment(**values)  # type: ignore[arg-type]


def take_profit(
    ctx: RiskContext | None = None, **overrides: object
) -> TakeProfitAssessment:
    values = {
        **base(ctx),
        "side": PositionSide.LONG,
        "entry_price": price("100"),
        "targets": (target(),),
        "expected_profit": money("200"),
        "risk_reward_ratio": Decimal("2"),
        "strategy_consistency": RiskCheckOutcome.PASSED,
        "invalidation_consistency": RiskCheckOutcome.PASSED,
        "assumptions": (version("reward-model"),),
    }
    values.update(overrides)
    return TakeProfitAssessment(**values)  # type: ignore[arg-type]


def portfolio_impact(
    ctx: RiskContext | None = None, sizing_id: UUID | None = None, **overrides: object
) -> PortfolioImpact:
    values = {
        **base(ctx),
        "sizing_result_id": sizing_id or uuid4(),
        "before_exposures": (exposure("before"),),
        "after_exposures": (exposure("after"),),
        "before_margin_utilization": ratio("0.10", "margin-utilization"),
        "after_margin_utilization": ratio("0.15", "margin-utilization"),
        "before_free_margin_buffer": ratio("0.70", "free-margin-buffer"),
        "after_free_margin_buffer": ratio("0.65", "free-margin-buffer"),
        "before_gross_leverage": Decimal("0.10"),
        "after_gross_leverage": Decimal("0.20"),
        "before_drawdown": ratio("0.01", "drawdown"),
        "after_drawdown": ratio("0.02", "drawdown"),
        "post_trade_risk": ratio("0.02", "portfolio-risk"),
        "remaining_risk_budget": money("200"),
        "limits": (limit(limit_id="portfolio-limit"),),
        "policy_version": version("risk-policy"),
    }
    values.update(overrides)
    return PortfolioImpact(**values)  # type: ignore[arg-type]


def scenario(
    *, outcome: RiskCheckOutcome = RiskCheckOutcome.PASSED
) -> StressScenarioResult:
    return StressScenarioResult(
        "synthetic-volatility-2x",
        "VOLATILITY_2X",
        (version("stress-assumption"),),
        ("synthetic-price-shock",),
        money("200") if outcome is RiskCheckOutcome.PASSED else None,
        ratio("0.05", "drawdown") if outcome is RiskCheckOutcome.PASSED else None,
        money("600") if outcome is RiskCheckOutcome.PASSED else None,
        "No synthetic liquidation breach.",
        (),
        outcome,
    )


def stress(ctx: RiskContext | None = None, **overrides: object) -> StressTestResult:
    values = {
        **base(ctx),
        "scenarios": (scenario(),),
        "required_scenario_types": ("VOLATILITY_2X",),
        "scenario_model_version": version("scenario-model"),
        "cost_model_version": version("cost-model"),
        "worst_loss": money("200"),
        "worst_drawdown": ratio("0.05", "drawdown"),
        "worst_margin": money("600"),
        "worst_liquidation_impact": "No synthetic liquidation breach.",
        "breached_limit_ids": (),
    }
    values.update(overrides)
    return StressTestResult(**values)  # type: ignore[arg-type]


def assessment(ctx: RiskContext | None = None, **overrides: object) -> RiskAssessment:
    ctx = ctx or context()
    size = sizing(ctx)
    values: dict[str, object] = {
        "assessment_id": uuid4(),
        "context": ctx,
        "position_sizing": size,
        "leverage": leverage(ctx),
        "liquidation": liquidation(ctx),
        "stop_loss": stop(ctx),
        "take_profit": take_profit(ctx),
        "portfolio_impact": portfolio_impact(ctx, size.result_id),
        "stress_test": stress(ctx),
        "limits": (limit(limit_id="aggregate-limit"),),
        "warnings": (),
        "constraints": ("Synthetic hard limits remain binding.",),
        "assumptions": (version("aggregate-assumption"),),
        "risk_state": RiskState.LOW_RISK,
        "outcome": RiskCheckOutcome.PASSED,
        "reason_codes": (),
        "risk_model_version": version("risk-model"),
        "policy_version": version("risk-policy"),
        "as_of": T[3],
        "evaluated_at": T[5],
        "valid_until": T[11],
        "content_sha256": HASH_A,
    }
    values.update(overrides)
    return RiskAssessment(**values)  # type: ignore[arg-type]


def decision(
    assessment_value: RiskAssessment,
    proposal_id: UUID,
    **overrides: object,
) -> RiskDecision:
    values: dict[str, object] = {
        "decision_id": uuid4(),
        "proposal_id": proposal_id,
        "assessment": assessment_value,
        "verdict": RiskVerdict.PASS,
        "risk_state": assessment_value.risk_state,
        "hard_breach_ids": (),
        "soft_warning_ids": (),
        "reason_codes": (),
        "risk_model_version": assessment_value.risk_model_version,
        "policy_version": assessment_value.policy_version,
        "as_of": T[3],
        "decided_at": T[6],
        "valid_until": T[10],
    }
    values.update(overrides)
    return RiskDecision(**values)  # type: ignore[arg-type]


def proposal(
    *,
    revision: int = 1,
    supersedes: UUID | None = None,
    proposal_id: UUID | None = None,
) -> RiskProposal:
    proposal_id = proposal_id or uuid4()
    ctx = context()
    assessment_value = assessment(ctx)
    decision_value = decision(assessment_value, proposal_id)
    return RiskProposal(
        proposal_id,
        revision,
        supersedes,
        ctx,
        ref("C-024"),
        price("100"),
        price("90"),
        (target(),),
        Decimal("1"),
        money("1000"),
        assessment_value.position_sizing,
        money("500"),
        Decimal("2"),
        MarginMode.ISOLATED,
        money("100"),
        money("200"),
        Decimal("2"),
        ratio("0.01", "account-risk"),
        ratio("0.02", "portfolio-risk"),
        assessment_value.liquidation,
        assessment_value.portfolio_impact,
        assessment_value.stress_test,
        assessment_value,
        decision_value,
        (),
        ("Synthetic hard limits remain binding.",),
        (version("proposal-assumption"),),
        ("entry_price", "stop_loss", "take_profit", "amount", "leverage"),
        assessment_value.risk_model_version,
        assessment_value.policy_version,
        version("risk-configuration"),
        T[3],
        T[7],
        T[9],
        HASH_A,
    )


def test_all_canonical_contract_ids_schema_and_immutability() -> None:
    account_value = account()
    portfolio_value = portfolio(account_value)
    ctx = context()
    size = sizing(ctx)
    assessment_value = assessment(ctx)
    proposal_value = proposal()
    replacement = proposal(revision=2, supersedes=proposal_value.proposal_id)
    revalidation = RiskRevalidationResult(
        uuid4(),
        proposal_value,
        replacement,
        (RevalidationTrigger.ENTRY,),
        ("entry_price",),
        ref("C-002"),
        replacement.risk_model_version,
        replacement.policy_version,
        replacement.assessment,
        replacement.decision,
        RevalidationStatus.PASSED,
        (),
        T[3],
        T[8],
        T[9],
        HASH_A,
    )
    values = (
        account_value,
        portfolio_value,
        proposal_value,
        assessment_value,
        size,
        portfolio_value.positions[0],
        assessment_value.leverage,
        assessment_value.liquidation,
        assessment_value.stop_loss,
        assessment_value.take_profit,
        assessment_value.portfolio_impact,
        assessment_value.stress_test,
        proposal_value.decision,
        revalidation,
    )
    assert [item.contract_id for item in values] == [
        "C-032",
        "C-033",
        "C-034",
        "C-035",
        "C-036",
        "C-075",
        "C-076",
        "C-077",
        "C-078",
        "C-079",
        "C-080",
        "C-081",
        "C-082",
        "C-083",
    ]
    assert all(item.schema_version == "1" for item in values)
    with pytest.raises(FrozenInstanceError):
        proposal_value.approved = True  # type: ignore[misc]


def test_enum_vocabularies_are_exact() -> None:
    assert {item.value for item in SnapshotState} == {
        "VALID",
        "STALE",
        "INCOMPLETE",
        "UNAVAILABLE",
    }
    assert {item.value for item in RiskVerdict} == {
        "PASS",
        "PASS_WITH_WARNING",
        "REQUIRES_HUMAN_REVIEW",
        "REJECT",
        "INSUFFICIENT_DATA",
    }
    assert {item.value for item in SizingMethod} == {
        "RISK_BASED",
        "FIXED_NOTIONAL",
        "PERCENTAGE_OF_EQUITY",
        "VOLATILITY_ADJUSTED",
        "FRACTIONAL_KELLY",
    }


def test_common_types_reject_bad_decimal_text_hash_and_naive_time() -> None:
    with pytest.raises(RiskContractError, match="finite Decimal"):
        MoneyValue(1.0, USD)  # type: ignore[arg-type]
    with pytest.raises(RiskContractError, match="surrounding whitespace"):
        MoneyValue(Decimal("1"), f" {USD}")
    with pytest.raises(RiskContractError, match="SHA-256"):
        VersionReference("x", "v1", "bad")
    with pytest.raises(RiskContractError, match="timezone-aware"):
        replace(account(), captured_at=datetime(2026, 1, 1))


def test_contract_references_are_canonical_and_current_in_context() -> None:
    with pytest.raises(RiskContractError, match="C-###"):
        ref("signal")
    with pytest.raises(RiskContractError, match="signal must reference C-070"):
        replace(context(), signal=ref("C-023"))
    with pytest.raises(RiskContractError, match="expired"):
        replace(context(), signal=ref("C-070", valid_until=T[2]))


def test_account_unknown_values_are_explicit_and_fail_closed() -> None:
    value = account(
        state=SnapshotState.UNAVAILABLE,
        reason_codes=("ACCOUNT_UNAVAILABLE",),
        equity=None,
        available_balance=None,
        used_margin=None,
        free_margin=None,
        unrealized_pnl=None,
        realized_pnl=None,
        daily_pnl=None,
        weekly_pnl=None,
        current_drawdown=None,
    )
    assert value.equity is None
    with pytest.raises(RiskContractError, match="requires all values"):
        account(equity=None)


def test_valid_position_requires_attribution_and_positive_values() -> None:
    account_id = uuid4()
    with pytest.raises(RiskContractError, match="order or fill attribution"):
        position(account_id, order_ids=(), fill_ids=())
    with pytest.raises(RiskContractError, match="quantity must be positive"):
        position(account_id, quantity=Decimal("0"))


def test_portfolio_rejects_account_mismatch_duplicates_and_unknown_aggregates() -> None:
    account_value = account()
    wrong = position(uuid4())
    with pytest.raises(RiskContractError, match="account identity mismatch"):
        portfolio(account_value, positions=(wrong,))
    item = position(account_value.account_id)
    with pytest.raises(RiskContractError, match="must not contain duplicates"):
        portfolio(account_value, positions=(item, item))
    with pytest.raises(RiskContractError, match="requires all aggregates"):
        portfolio(account_value, volatility=None)


def test_position_sizing_requires_complete_bounded_output() -> None:
    with pytest.raises(RiskContractError, match="complete bounded output"):
        sizing(recommended_quantity=None)
    with pytest.raises(RiskContractError, match="violates exchange bounds"):
        sizing(recommended_quantity=Decimal("11"))
    insufficient = sizing(
        outcome=RiskCheckOutcome.INSUFFICIENT_DATA,
        reason_codes=("CONSTRAINTS_UNKNOWN",),
        recommended_quantity=None,
        recommended_notional=None,
        recommended_margin=None,
        stop_distance=None,
        maximum_loss=None,
        account_risk=None,
        minimum_quantity=None,
        maximum_quantity=None,
        quantity_step=None,
    )
    assert insufficient.outcome is RiskCheckOutcome.INSUFFICIENT_DATA


def test_leverage_hard_limit_and_unknown_constraints_cannot_pass() -> None:
    with pytest.raises(RiskContractError, match="exceeds permitted"):
        leverage(requested_leverage=Decimal("6"))
    with pytest.raises(RiskContractError, match="hard leverage breach"):
        leverage(limits=(limit(outcome=RiskCheckOutcome.FAILED),))
    with pytest.raises(RiskContractError, match="requires FAILED"):
        leverage(
            outcome=RiskCheckOutcome.WARNING,
            reason_codes=("WARNING_CANNOT_HIDE_HARD_BREACH",),
            limits=(limit(outcome=RiskCheckOutcome.FAILED),),
        )
    with pytest.raises(RiskContractError, match="complete data"):
        leverage(exchange_constraints=None)


def test_liquidation_unavailable_never_carries_or_passes_estimate() -> None:
    with pytest.raises(RiskContractError, match="cannot carry estimated"):
        liquidation(availability=LiquidationAvailability.UNAVAILABLE)
    value = liquidation(
        availability=LiquidationAvailability.UNAVAILABLE,
        liquidation_price=None,
        entry_to_liquidation=None,
        stop_to_liquidation=None,
        formula_version=None,
        exchange_constraints=None,
        outcome=RiskCheckOutcome.INSUFFICIENT_DATA,
        reason_codes=("LIQUIDATION_MODEL_UNAVAILABLE",),
    )
    assert value.liquidation_price is None
    with pytest.raises(RiskContractError, match="must be available"):
        replace(value, outcome=RiskCheckOutcome.PASSED, reason_codes=())


def test_stop_loss_rejects_wrong_side_missing_and_failed_checks() -> None:
    with pytest.raises(RiskContractError, match="below entry"):
        stop(stop_loss=price("110"))
    with pytest.raises(RiskContractError, match="complete evidence"):
        stop(stop_loss=None)
    with pytest.raises(RiskContractError, match="cannot contain failures"):
        stop(structural_check=RiskCheckOutcome.FAILED)


def test_take_profit_requires_exact_allocation_and_correct_side() -> None:
    with pytest.raises(RiskContractError, match="sum exactly to 1"):
        take_profit(targets=(target(allocation="0.5"),))
    with pytest.raises(RiskContractError, match="wrong side"):
        take_profit(targets=(replace(target(), price=price("90")),))


def test_portfolio_impact_hard_breach_or_missing_evidence_cannot_pass() -> None:
    with pytest.raises(RiskContractError, match="hard portfolio breach"):
        portfolio_impact(limits=(limit(outcome=RiskCheckOutcome.FAILED),))
    with pytest.raises(RiskContractError, match="complete evidence"):
        portfolio_impact(after_margin_utilization=None)


def test_stress_test_requires_scenarios_and_propagates_unknown() -> None:
    with pytest.raises(RiskContractError, match="required stress scenarios"):
        stress(required_scenario_types=("LIQUIDITY_COLLAPSE",))
    with pytest.raises(RiskContractError, match="passed scenarios"):
        stress(scenarios=(scenario(outcome=RiskCheckOutcome.INSUFFICIENT_DATA),))


def test_assessment_requires_matching_context_and_component_freshness() -> None:
    with pytest.raises(RiskContractError, match="component context mismatch"):
        assessment(leverage=leverage(context()))
    stale = replace(sizing(context()), valid_until=T[8])
    with pytest.raises(RiskContractError, match="expires before"):
        assessment(
            stale.context,
            position_sizing=stale,
            portfolio_impact=portfolio_impact(stale.context, stale.result_id),
        )


def test_hard_failure_dominates_warnings_in_assessment() -> None:
    ctx = context()
    failed_leverage = leverage(
        ctx,
        outcome=RiskCheckOutcome.FAILED,
        reason_codes=("HARD_LEVERAGE_BREACH",),
        limits=(limit(outcome=RiskCheckOutcome.FAILED),),
    )
    with pytest.raises(RiskContractError, match="hard failure requires"):
        assessment(ctx, leverage=failed_leverage, warnings=("warning",))


def test_unknown_component_requires_insufficient_assessment() -> None:
    ctx = context()
    unavailable = liquidation(
        ctx,
        availability=LiquidationAvailability.UNAVAILABLE,
        liquidation_price=None,
        entry_to_liquidation=None,
        stop_to_liquidation=None,
        formula_version=None,
        exchange_constraints=None,
        outcome=RiskCheckOutcome.INSUFFICIENT_DATA,
        reason_codes=("LIQUIDATION_UNKNOWN",),
    )
    with pytest.raises(RiskContractError, match="insufficient-data state"):
        assessment(ctx, liquidation=unavailable)


def test_risk_decision_is_non_executing_and_verdict_consistent() -> None:
    assessment_value = assessment()
    value = decision(assessment_value, uuid4())
    assert value.execution_authorized is False
    assert "execution_authorized" in {item.name for item in fields(value)}
    with pytest.raises(RiskContractError, match="PASS requires clean"):
        replace(value, soft_warning_ids=("soft",))
    with pytest.raises(RiskContractError, match="REJECT requires"):
        replace(value, verdict=RiskVerdict.REJECT, reason_codes=("rejected",))


def test_risk_proposal_is_non_executable_versioned_and_bound() -> None:
    value = proposal()
    assert value.approved is False and value.executable is False
    with pytest.raises(RiskContractError, match="later revision requires"):
        replace(value, revision=2)
    with pytest.raises(RiskContractError, match="decision proposal identity mismatch"):
        replace(value, proposal_id=uuid4())


def test_revalidation_requires_new_higher_revision_and_fresh_evidence() -> None:
    original = proposal()
    replacement = proposal(revision=2, supersedes=original.proposal_id)
    value = RiskRevalidationResult(
        uuid4(),
        original,
        replacement,
        (RevalidationTrigger.LEVERAGE,),
        ("leverage",),
        ref("C-002"),
        replacement.risk_model_version,
        replacement.policy_version,
        replacement.assessment,
        replacement.decision,
        RevalidationStatus.PASSED,
        (),
        T[3],
        T[8],
        T[9],
        HASH_A,
    )
    assert value.execution_authorized is False
    same_revision_original = proposal(revision=2, supersedes=uuid4())
    same_revision_replacement = proposal(
        revision=2, supersedes=same_revision_original.proposal_id
    )
    with pytest.raises(RiskContractError, match="revision must increase"):
        replace(
            value,
            original_proposal=same_revision_original,
            replacement_proposal=same_revision_replacement,
            risk_model_version=same_revision_replacement.risk_model_version,
            policy_version=same_revision_replacement.policy_version,
            replacement_assessment=same_revision_replacement.assessment,
            replacement_decision=same_revision_replacement.decision,
        )


def test_material_change_cannot_reuse_original_decision() -> None:
    original = proposal()
    replacement = proposal(revision=2, supersedes=original.proposal_id)
    with pytest.raises(RiskContractError, match="replacement evidence mismatch"):
        RiskRevalidationResult(
            uuid4(),
            original,
            replacement,
            (RevalidationTrigger.ENTRY,),
            ("entry_price",),
            ref("C-002"),
            replacement.risk_model_version,
            replacement.policy_version,
            replacement.assessment,
            original.decision,
            RevalidationStatus.PASSED,
            (),
            T[3],
            T[8],
            T[9],
            HASH_A,
        )


def test_collections_are_tuple_only() -> None:
    with pytest.raises(RiskContractError, match="must be a tuple"):
        replace(proposal(), warnings=["mutable"])  # type: ignore[arg-type]


def test_contract_module_has_no_runtime_engine_or_integration_surface() -> None:
    source = Path("apps/api/src/trading_platform_api/risk/contracts.py").read_text()
    forbidden = (
        "fastapi",
        "sqlalchemy",
        "ccxt",
        "requests",
        "httpx",
        "Kafka",
        "RabbitMQ",
        "Redis",
        "create_engine",
        "@router",
        "place_order",
        "submit_order",
        "api_key",
        "secret_key",
    )
    assert not any(token in source for token in forbidden)
