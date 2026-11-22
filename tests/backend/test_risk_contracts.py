from dataclasses import FrozenInstanceError, fields, replace
from datetime import UTC, datetime, timedelta
from decimal import ROUND_DOWN, ROUND_UP, Context, Decimal, Inexact, localcontext
from pathlib import Path
from uuid import UUID, uuid4

import pytest
import trading_platform_api.risk.contracts as risk_contracts
from trading_platform_api.contracts.serialization import canonical_sha256
from trading_platform_api.risk import (
    AccountEvidenceContext,
    AccountPermissionObservation,
    AccountPermissionObservations,
    AccountSnapshot,
    ContractReference,
    DescriptiveEstimateState,
    ExposureConcentrationState,
    ExposureValue,
    InstrumentReturnSeries,
    LeverageAssessment,
    LeverageAssessmentRequest,
    LinearMarginRuleEvidence,
    LiquidationAssessment,
    LiquidationAssessmentRequest,
    LiquidationAvailability,
    LiquidationCostEvidence,
    LiquidationDistanceThresholds,
    LiquidationPriceEvidence,
    MarginMode,
    MoneyValue,
    OfflineAccountAssessment,
    OfflineAccountEvidence,
    PairwiseCorrelationResult,
    PortfolioConcentrationLimit,
    PortfolioCorrelationScenario,
    PortfolioExposureAggregation,
    PortfolioImpact,
    PortfolioImpactBasis,
    PortfolioImpactPolicy,
    PortfolioImpactRequest,
    PortfolioLiquidityEvidence,
    PortfolioPositionEvidence,
    PortfolioSnapshot,
    PositionExposureInput,
    PositionSide,
    PositionSizingRequest,
    PositionSizingResult,
    PositionSnapshot,
    PriceValue,
    RatioValue,
    ReturnObservation,
    RevalidationStatus,
    RevalidationTrigger,
    RiskAssessment,
    RiskCheckOutcome,
    RiskContext,
    RiskContractError,
    RiskDecision,
    RiskLimitDefinition,
    RiskLimitDirection,
    RiskLimitHierarchy,
    RiskLimitPolicyConfiguration,
    RiskLimitResult,
    RiskLimitScope,
    RiskLimitSeverity,
    RiskPolicyMode,
    RiskProposal,
    RiskRevalidationResult,
    RiskState,
    RiskVerdict,
    RuinPathEvidence,
    SizingCosts,
    SizingInstrumentTerms,
    SizingMethod,
    SnapshotState,
    StopLossAssessment,
    StopLossAssessmentRequest,
    StopLossLiquidationEvidence,
    StopLossStructuralEvidence,
    StopLossVolatilityEvidence,
    StressAssessmentPolicy,
    StressAssessmentRequest,
    StressProjectionEvidence,
    StressScenarioResult,
    StressShock,
    StressTestResult,
    TakeProfitAssessment,
    TakeProfitAssessmentRequest,
    TakeProfitTarget,
    TakeProfitTargetBound,
    VersionReference,
    aggregate_portfolio_exposure,
    calculate_leverage_assessment,
    calculate_liquidation_assessment,
    calculate_portfolio_impact,
    calculate_position_size,
    calculate_ruin_observation,
    calculate_stop_loss_assessment,
    calculate_stress_assessment,
    calculate_take_profit_assessment,
    pairwise_correlation,
    portfolio_group_key,
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


def policy_limit(
    *,
    hierarchy: RiskLimitHierarchy = RiskLimitHierarchy.SYSTEM,
    metric: str = "daily-loss",
    direction: RiskLimitDirection = RiskLimitDirection.LESS_THAN_OR_EQUAL,
    threshold: str = "100",
    unit: str = "SYNTHETIC-USD",
    severity: RiskLimitSeverity = RiskLimitSeverity.HARD,
    mode: RiskPolicyMode = RiskPolicyMode.RESEARCH,
    account_id: UUID | None = None,
    portfolio_id: UUID | None = None,
    strategy_id: str | None = None,
    venue: str | None = None,
    instrument_id: str | None = None,
    trade_id: UUID | None = None,
    user_request_id: UUID | None = None,
    limit_id: str = "synthetic-policy-limit",
    enabled: bool = True,
) -> RiskLimitDefinition:
    scope = RiskLimitScope(
        hierarchy,
        mode,
        account_id,
        portfolio_id,
        strategy_id,
        venue,
        instrument_id,
        trade_id,
        user_request_id,
    )
    return RiskLimitDefinition(
        limit_id,
        hierarchy,
        metric,
        direction,
        Decimal(threshold),
        unit,
        severity,
        scope,
        enabled,
    )


def risk_policy(
    limits: tuple[RiskLimitDefinition, ...],
) -> RiskLimitPolicyConfiguration:
    policy_component = "synthetic-risk-policy"
    policy_version = "synthetic-policy-v1"
    configuration_component = "synthetic-risk-configuration"
    configuration_version = "synthetic-configuration-v1"
    preimage = {
        "policy_version": {
            "component": policy_component,
            "version": policy_version,
        },
        "configuration_version": {
            "component": configuration_component,
            "version": configuration_version,
        },
        "limits": limits,
    }
    digest = canonical_sha256(preimage)
    return RiskLimitPolicyConfiguration(
        VersionReference(policy_component, policy_version, digest),
        VersionReference(configuration_component, configuration_version, digest),
        limits,
        digest,
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
    assert {item.value for item in RiskPolicyMode} == {
        "research",
        "backtest",
        "paper",
        "shadow",
        "testnet",
        "live-supervised",
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


def offline_context(snapshot: AccountSnapshot) -> AccountEvidenceContext:
    return AccountEvidenceContext(
        snapshot.account_id,
        snapshot.source_id,
        snapshot.source_version,
        "synthetic-venue",
        RiskPolicyMode.RESEARCH,
    )


def offline_permissions() -> AccountPermissionObservations:
    return AccountPermissionObservations(
        AccountPermissionObservation.ALLOWED,
        AccountPermissionObservation.DENIED,
        AccountPermissionObservation.DENIED,
        AccountPermissionObservation.DENIED,
    )


def offline_evidence() -> OfflineAccountEvidence:
    snapshot = account()
    return OfflineAccountEvidence.create(
        snapshot, offline_context(snapshot), offline_permissions()
    )


def test_offline_account_currentness_is_deterministic_data_not_authorization() -> None:
    evidence = offline_evidence()
    expected = evidence.observed_context
    result = OfflineAccountAssessment(evidence, expected, T[3])
    assert result == OfflineAccountAssessment(evidence, expected, T[3])
    assert result.current
    assert result.reason_codes == ()
    assert result.independent_source_reconciliation == "UNKNOWN"
    assert evidence.permissions == offline_permissions()
    assert not hasattr(result, "approved")
    assert not hasattr(result, "execution_authorized")
    assert not hasattr(evidence, "contract_id")
    assert not hasattr(result, "contract_id")
    assert not hasattr(evidence, "schema_version")
    for value, name, replacement in (
        (evidence, "content_sha256", "b" * 64),
        (expected, "venue", "other-venue"),
        (evidence.permissions, "read", AccountPermissionObservation.UNKNOWN),
        (result, "current", False),
    ):
        with pytest.raises(FrozenInstanceError):
            setattr(value, name, replacement)


@pytest.mark.parametrize("observation", list(AccountPermissionObservation))
def test_offline_known_denied_and_allowed_permissions_are_complete(
    observation: AccountPermissionObservation,
) -> None:
    evidence = offline_evidence()
    permissions = AccountPermissionObservations(*(observation,) * 4)
    evidence = OfflineAccountEvidence.create(
        evidence.snapshot, evidence.observed_context, permissions
    )
    result = OfflineAccountAssessment(evidence, evidence.observed_context, T[3])
    assert result.current is (observation is not AccountPermissionObservation.UNKNOWN)
    assert result.independent_source_reconciliation == "UNKNOWN"


@pytest.mark.parametrize("name", ["read", "trade", "withdraw", "transfer"])
@pytest.mark.parametrize("observation", [None, AccountPermissionObservation.UNKNOWN])
def test_offline_missing_permission_observations_are_noncurrent(
    name: str, observation: AccountPermissionObservation | None
) -> None:
    evidence = offline_evidence()
    assert evidence.permissions is not None
    permissions = replace(evidence.permissions, **{name: observation})
    evidence = OfflineAccountEvidence.create(
        evidence.snapshot, evidence.observed_context, permissions
    )
    result = OfflineAccountAssessment(evidence, evidence.observed_context, T[3])
    assert not result.current
    assert result.reason_codes == (f"{name.upper()}_PERMISSION_UNKNOWN",)


@pytest.mark.parametrize(
    ("name", "conflict"),
    [
        ("account_id", UUID(int=1)),
        ("source_id", "other-source"),
        ("source_version", VersionReference("account-source", "other-v", HASH_A)),
        ("source_version", VersionReference("other-component", "synthetic-v1", HASH_A)),
        (
            "source_version",
            VersionReference("account-source", "synthetic-v1", "b" * 64),
        ),
        ("venue", "other-venue"),
        ("mode", RiskPolicyMode.PAPER),
    ],
)
def test_offline_expected_context_mismatches_are_noncurrent(
    name: str, conflict: object
) -> None:
    evidence = offline_evidence()
    assert evidence.observed_context is not None
    expected = replace(evidence.observed_context, **{name: conflict})
    result = OfflineAccountAssessment(evidence, expected, T[3])
    assert not result.current
    assert result.reason_codes == (f"{name.upper()}_CONTEXT_MISMATCH",)


@pytest.mark.parametrize(
    ("name", "conflict"),
    [
        ("account_id", UUID(int=1)),
        ("source_id", "other-source"),
        ("source_version", VersionReference("other-component", "other-v", "b" * 64)),
    ],
)
def test_offline_observed_context_must_also_bind_snapshot(
    name: str, conflict: object
) -> None:
    original = offline_evidence()
    assert original.observed_context is not None
    observed = replace(original.observed_context, **{name: conflict})
    evidence = OfflineAccountEvidence.create(
        original.snapshot, observed, original.permissions
    )
    result = OfflineAccountAssessment(evidence, observed, T[3])
    assert not result.current
    assert result.reason_codes == (f"{name.upper()}_SNAPSHOT_MISMATCH",)


@pytest.mark.parametrize(
    "name", ["account_id", "source_id", "source_version", "venue", "mode"]
)
@pytest.mark.parametrize("side", ["observed", "expected"])
def test_offline_unknown_context_fields_are_not_inferred(name: str, side: str) -> None:
    original = offline_evidence()
    assert original.observed_context is not None
    unknown = replace(original.observed_context, **{name: None})
    observed = unknown if side == "observed" else original.observed_context
    expected = unknown if side == "expected" else original.observed_context
    evidence = OfflineAccountEvidence.create(
        original.snapshot, observed, original.permissions
    )
    result = OfflineAccountAssessment(evidence, expected, T[3])
    assert not result.current
    assert result.reason_codes == (f"{side.upper()}_{name.upper()}_UNKNOWN",)


def test_offline_entirely_missing_context_and_permissions_remain_unknown() -> None:
    evidence = OfflineAccountEvidence.create(account(), None, None)
    result = OfflineAccountAssessment(evidence, None, T[3])
    assert not result.current
    assert len(result.reason_codes) == 14
    assert "OBSERVED_ACCOUNT_ID_UNKNOWN" in result.reason_codes
    assert "EXPECTED_MODE_UNKNOWN" in result.reason_codes
    assert "TRANSFER_PERMISSION_UNKNOWN" in result.reason_codes
    assert evidence.observed_context is None
    assert evidence.permissions is None


@pytest.mark.parametrize(
    "state", [s for s in SnapshotState if s is not SnapshotState.VALID]
)
def test_offline_nonvalid_snapshot_cannot_be_current(state: SnapshotState) -> None:
    snapshot = account(state=state, reason_codes=("SYNTHETIC_SOURCE_LIMITATION",))
    evidence = OfflineAccountEvidence.create(
        snapshot, offline_context(snapshot), offline_permissions()
    )
    result = OfflineAccountAssessment(evidence, evidence.observed_context, T[3])
    assert not result.current
    assert result.reason_codes == (f"SNAPSHOT_{state.value}",)


@pytest.mark.parametrize(
    ("evaluated_at", "reasons"),
    [
        (
            T[0] - timedelta(microseconds=1),
            ("SNAPSHOT_AS_OF_IN_FUTURE", "SNAPSHOT_CAPTURE_IN_FUTURE"),
        ),
        (T[0], ("SNAPSHOT_CAPTURE_IN_FUTURE",)),
        (T[1] - timedelta(microseconds=1), ("SNAPSHOT_CAPTURE_IN_FUTURE",)),
        (T[1], ()),
        (T[15], ()),
        (T[15] + timedelta(microseconds=1), ("SNAPSHOT_EXPIRED",)),
    ],
)
def test_offline_time_boundaries_are_explicit_and_inclusive(
    evaluated_at: datetime, reasons: tuple[str, ...]
) -> None:
    evidence = offline_evidence()
    result = OfflineAccountAssessment(evidence, evidence.observed_context, evaluated_at)
    assert result.reason_codes == reasons
    assert result.current is (not reasons)


def test_offline_asof_capture_and_expiry_equality_passes() -> None:
    snapshot = account(as_of=T[3], captured_at=T[3], valid_until=T[3])
    evidence = OfflineAccountEvidence.create(
        snapshot, offline_context(snapshot), offline_permissions()
    )
    assert OfflineAccountAssessment(evidence, evidence.observed_context, T[3]).current


def test_offline_times_normalize_to_utc_and_reject_naive_or_malformed_input() -> None:
    evidence = offline_evidence()
    local_time = datetime.fromisoformat("2026-01-04T05:30:00+05:30")
    result = OfflineAccountAssessment(evidence, evidence.observed_context, local_time)
    assert result.evaluated_at == T[3]
    assert result.evaluated_at.tzinfo is UTC
    for invalid in (datetime(2026, 1, 4), "2026-01-04", None):
        with pytest.raises(RiskContractError, match="evaluated_at"):
            OfflineAccountAssessment(
                evidence,
                evidence.observed_context,
                invalid,  # type: ignore[arg-type]
            )
    snapshot = replace(
        evidence.snapshot,
        as_of=evidence.snapshot.as_of.astimezone(local_time.tzinfo),
        captured_at=evidence.snapshot.captured_at.astimezone(local_time.tzinfo),
        valid_until=evidence.snapshot.valid_until.astimezone(local_time.tzinfo),
    )
    equivalent = OfflineAccountEvidence.create(
        snapshot, evidence.observed_context, evidence.permissions
    )
    assert equivalent == evidence


def test_offline_digest_binds_complete_snapshot_without_authenticating_it() -> None:
    evidence = offline_evidence()
    preimage = {
        item.name: getattr(evidence, item.name)
        for item in fields(evidence)
        if item.name != "content_sha256"
    }
    assert evidence.content_sha256 == canonical_sha256(preimage)
    assert evidence.snapshot.content_sha256 == HASH_A
    assert evidence.snapshot.contract_id == "C-032"
    assert evidence.snapshot.schema_version == "1"
    evidence.verify()
    changed_snapshot = replace(evidence.snapshot, content_sha256="b" * 64)
    changed = OfflineAccountEvidence.create(
        changed_snapshot, evidence.observed_context, evidence.permissions
    )
    assert changed.content_sha256 != evidence.content_sha256
    with pytest.raises(RiskContractError, match="digest mismatch"):
        replace(evidence, snapshot=changed_snapshot)
    with pytest.raises(RiskContractError, match="digest mismatch"):
        replace(evidence, content_sha256="0" * 64)
    assert OfflineAccountAssessment(changed, changed.observed_context, T[3]).current


@pytest.mark.parametrize("name", [item.name for item in fields(AccountSnapshot)])
def test_offline_digest_rejects_tampering_with_every_snapshot_field(name: str) -> None:
    evidence = offline_evidence()
    snapshot = replace(evidence.snapshot)
    original = getattr(snapshot, name)
    if isinstance(original, UUID):
        changed: object = UUID(int=1)
    elif isinstance(original, MoneyValue):
        changed = replace(original, amount=original.amount + Decimal("1"))
    elif isinstance(original, RatioValue):
        changed = replace(original, value=Decimal("0.02"))
    elif isinstance(original, VersionReference):
        changed = replace(original, content_sha256="b" * 64)
    elif isinstance(original, datetime):
        changed = original + timedelta(microseconds=1)
    elif isinstance(original, tuple):
        changed = ("SYNTHETIC_CHANGED",)
    elif isinstance(original, SnapshotState):
        changed = SnapshotState.STALE
    else:
        changed = "b" * 64 if name == "content_sha256" else "synthetic-changed"
    object.__setattr__(snapshot, name, changed)  # Simulate bypassing frozen storage.
    with pytest.raises(RiskContractError):
        replace(evidence, snapshot=snapshot)


@pytest.mark.parametrize(
    "name", ["account_id", "source_id", "source_version", "venue", "mode"]
)
def test_offline_digest_binds_each_observed_identity(name: str) -> None:
    evidence = offline_evidence()
    assert evidence.observed_context is not None
    observed = replace(evidence.observed_context, **{name: None})
    with pytest.raises(RiskContractError, match="digest mismatch"):
        replace(evidence, observed_context=observed)


@pytest.mark.parametrize("name", ["read", "trade", "withdraw", "transfer"])
def test_offline_digest_binds_every_permission_observation(name: str) -> None:
    evidence = offline_evidence()
    assert evidence.permissions is not None
    permissions = replace(
        evidence.permissions, **{name: AccountPermissionObservation.UNKNOWN}
    )
    with pytest.raises(RiskContractError, match="digest mismatch"):
        replace(evidence, permissions=permissions)


def test_offline_assessment_reverifies_evidence() -> None:
    evidence = offline_evidence()
    object.__setattr__(
        evidence, "snapshot", replace(evidence.snapshot, available_balance=money("1"))
    )
    with pytest.raises(RiskContractError, match="digest mismatch"):
        OfflineAccountAssessment(evidence, evidence.observed_context, T[3])


@pytest.mark.parametrize(
    "invalid",
    [
        True,
        1,
        1.0,
        "1",
        Decimal("NaN"),
        Decimal("sNaN"),
        Decimal("Infinity"),
        Decimal("-Infinity"),
    ],
)
def test_offline_boundary_rejects_malformed_nested_money(invalid: object) -> None:
    snapshot = account()
    malformed = money()
    object.__setattr__(malformed, "amount", invalid)
    object.__setattr__(snapshot, "equity", malformed)
    with pytest.raises(RiskContractError, match="finite Decimal"):
        OfflineAccountEvidence.create(
            snapshot, offline_context(snapshot), offline_permissions()
        )


def test_offline_preserves_c032_rules_without_fund_inference() -> None:
    with pytest.raises(RiskContractError, match="snapshot currency"):
        account(available_balance=MoneyValue(Decimal("1"), "OTHER-SYNTHETIC-USD"))
    with pytest.raises(RiskContractError, match="non-negative"):
        account(free_margin=money("-1"))
    with pytest.raises(RiskContractError, match="positive"):
        account(equity=money("0"))
    snapshot = account(
        state=SnapshotState.INCOMPLETE,
        reason_codes=("SYNTHETIC_MISSING_FUNDS",),
        available_balance=None,
        free_margin=None,
        used_margin=None,
        current_drawdown=None,
    )
    evidence = OfflineAccountEvidence.create(
        snapshot, offline_context(snapshot), offline_permissions()
    )
    result = OfflineAccountAssessment(evidence, evidence.observed_context, T[3])
    assert not result.current
    assert evidence.snapshot.available_balance is None
    assert evidence.snapshot.free_margin is None
    assert evidence.snapshot.used_margin is None
    assert evidence.snapshot.current_drawdown is None
    # C-032 accepts supplied values without imposing reconciliation formulas.
    unusual = account(available_balance=money("50000"), free_margin=money("0"))
    assert OfflineAccountAssessment(
        OfflineAccountEvidence.create(
            unusual, offline_context(unusual), offline_permissions()
        ),
        offline_context(unusual),
        T[3],
    ).current


@pytest.mark.parametrize(
    ("name", "invalid"),
    [
        ("account_id", "not-a-uuid"),
        ("source_id", ""),
        ("source_version", "not-a-version"),
        ("venue", " synthetic-venue"),
        ("mode", "research"),
    ],
)
def test_offline_context_rejects_malformed_supplied_values(
    name: str, invalid: object
) -> None:
    with pytest.raises(RiskContractError):
        replace(offline_context(account()), **{name: invalid})


@pytest.mark.parametrize("name", ["read", "trade", "withdraw", "transfer"])
@pytest.mark.parametrize("invalid", ["ALLOWED", "DENIED", "UNKNOWN", True, 1, 1.0])
def test_offline_permission_values_require_typed_observations(
    name: str, invalid: object
) -> None:
    with pytest.raises(RiskContractError, match="AccountPermissionObservation"):
        replace(offline_permissions(), **{name: invalid})


@pytest.mark.parametrize("name", ["as_of", "captured_at", "valid_until"])
def test_offline_snapshot_times_must_be_timezone_aware(name: str) -> None:
    with pytest.raises(RiskContractError, match="timezone-aware"):
        account(**{name: datetime(2026, 1, 2)})


def test_offline_snapshot_state_rejects_raw_enum_strings() -> None:
    with pytest.raises(RiskContractError, match="SnapshotState"):
        account(state="VALID")


def test_offline_boundary_rejects_wrong_value_types_as_risk_contract_errors() -> None:
    evidence = offline_evidence()
    with pytest.raises(RiskContractError, match="snapshot"):
        OfflineAccountEvidence.create(None, None, None)  # type: ignore[arg-type]
    with pytest.raises(RiskContractError, match="observed_context"):
        replace(evidence, observed_context={})
    with pytest.raises(RiskContractError, match="permissions"):
        OfflineAccountEvidence.create(
            evidence.snapshot,
            evidence.observed_context,
            (),  # type: ignore[arg-type]
        )
    with pytest.raises(RiskContractError, match="read"):
        replace(offline_permissions(), read=True)  # type: ignore[arg-type]
    with pytest.raises(RiskContractError, match="expected_context"):
        OfflineAccountAssessment(evidence, "research", T[3])  # type: ignore[arg-type]
    with pytest.raises(RiskContractError, match="evidence"):
        OfflineAccountAssessment(None, None, T[3])  # type: ignore[arg-type]
    snapshot = replace(evidence.snapshot)
    object.__setattr__(snapshot, "equity", "100")
    with pytest.raises(RiskContractError, match="MoneyValue"):
        OfflineAccountEvidence.create(snapshot, None, None)


def test_offline_evidence_does_not_change_account_or_portfolio_consumers() -> None:
    snapshot = account()
    original_fields = (
        "snapshot_id",
        "account_id",
        "source_id",
        "state",
        "reason_codes",
        "currency",
        "equity",
        "available_balance",
        "used_margin",
        "free_margin",
        "unrealized_pnl",
        "realized_pnl",
        "daily_pnl",
        "weekly_pnl",
        "current_drawdown",
        "source_version",
        "as_of",
        "captured_at",
        "valid_until",
        "content_sha256",
        "contract_id",
        "schema_version",
    )
    assert tuple(item.name for item in fields(AccountSnapshot)) == original_fields
    original_digest = canonical_sha256(snapshot)
    evidence = OfflineAccountEvidence.create(
        snapshot, offline_context(snapshot), offline_permissions()
    )
    assert evidence.snapshot is snapshot
    assert canonical_sha256(snapshot) == original_digest
    assert portfolio(snapshot).account_snapshot is snapshot
    arguments = tuple(
        getattr(snapshot, item.name) for item in fields(AccountSnapshot) if item.init
    )
    assert AccountSnapshot(*arguments) == snapshot


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


def sizing_request(
    method: SizingMethod = SizingMethod.RISK_BASED,
    **overrides: object,
) -> PositionSizingRequest:
    account_value = account()
    portfolio_value = portfolio(account_value)
    ctx = replace(
        context(),
        account_snapshot=ContractReference(
            "C-032",
            account_value.snapshot_id,
            "1",
            account_value.content_sha256,
            account_value.valid_until,
        ),
        portfolio_snapshot=ContractReference(
            "C-033",
            portfolio_value.snapshot_id,
            "1",
            portfolio_value.content_sha256,
            portfolio_value.valid_until,
        ),
    )
    values: dict[str, object] = {
        "result_id": UUID(int=106),
        "context": ctx,
        "account": account_value,
        "portfolio": portfolio_value,
        "method": method,
        "mode": RiskPolicyMode.RESEARCH,
        "entry": price("100"),
        "stop": price("90"),
        "effective_risk": money("120"),
        "policy_version": version("policy"),
        "configuration_version": version("configuration"),
        "budget_version": version("effective-budget"),
        "model_version": version("sizing"),
        "evaluated_at": T[4],
        "assumptions_as_of": T[2],
        "assumptions_valid_until": T[14],
        "instrument": SizingInstrumentTerms(
            ctx.asset,
            ctx.instrument_id,
            "synthetic-venue",
            "LINEAR",
            USD,
            Decimal("1"),
            Decimal("0.01"),
            Decimal("0.1"),
            Decimal("100"),
            Decimal("0.1"),
            money("100000"),
            money("20"),
            version("instrument"),
        ),
        "costs": SizingCosts(money("1"), money("0.5"), money("0.5"), version("cost")),
    }
    values.update(overrides)
    return PositionSizingRequest(**values)  # type: ignore[arg-type]


def leverage_request(
    *,
    side: PositionSide = PositionSide.LONG,
    margin_mode: MarginMode = MarginMode.ISOLATED,
    **overrides: object,
) -> LeverageAssessmentRequest:
    sizing_value = sizing_request()
    assert sizing_value.instrument is not None
    clean_portfolio = replace(
        sizing_value.portfolio,
        gross_exposure=money("101"),
    )
    sizing_value = replace(sizing_value, portfolio=clean_portfolio)
    if side is PositionSide.SHORT:
        sizing_value = replace(
            sizing_value,
            context=replace(sizing_value.context, side=side),
            stop=price("110"),
        )
    rule = LinearMarginRuleEvidence(
        sizing_value.instrument.venue,
        sizing_value.instrument.instrument_id,
        sizing_value.account.account_id,
        sizing_value.account.snapshot_id,
        margin_mode,
        money("0"),
        money("100000"),
        Decimal("0.05"),
        Decimal("0.01"),
        "LINEAR",
        version("margin-rule"),
        T[3],
        T[13],
    )
    values: dict[str, object] = {
        "result_id": UUID(int=107),
        "evaluated_at": sizing_value.evaluated_at,
        "sizing_request": sizing_value,
        "requested_leverage": Decimal("5"),
        "margin_mode": margin_mode,
        "policy_maximum_leverage": Decimal("10"),
        "account_maximum_leverage": Decimal("10"),
        "venue_maximum_leverage": Decimal("10"),
        "maximum_post_trade_gross_leverage": Decimal("1"),
        "minimum_remaining_free_margin": money("6000"),
        "additional_reserved_cost": money("30"),
        "margin_rule": rule,
    }
    values.update(overrides)
    return LeverageAssessmentRequest(**values)  # type: ignore[arg-type]


def liquidation_assessment_request(
    *,
    side: PositionSide = PositionSide.LONG,
    margin_mode: MarginMode = MarginMode.ISOLATED,
    liquidation_price: str | None = None,
    estimate_overrides: dict[str, object] | None = None,
    threshold_overrides: dict[str, object] | None = None,
    cost_overrides: dict[str, object] | None = None,
    leverage_overrides: dict[str, object] | None = None,
    stop_loss: PriceValue | None = None,
) -> LiquidationAssessmentRequest:
    leverage_value = leverage_request(
        side=side, margin_mode=margin_mode, **(leverage_overrides or {})
    )
    sizing_value = leverage_value.sizing_request
    if (
        leverage_overrides
        and "sizing_request" in leverage_overrides
        and leverage_value.margin_rule is not None
    ):
        # Bind this synthetic rule to the explicitly supplied fixture account.
        leverage_value = replace(
            leverage_value,
            margin_rule=replace(
                leverage_value.margin_rule,
                account_id=sizing_value.account.account_id,
                account_snapshot_id=sizing_value.account.snapshot_id,
            ),
        )
    expected_stop = stop_loss or sizing_value.stop
    expected_liquidation = liquidation_price or (
        "80" if side is PositionSide.LONG else "120"
    )
    sized = calculate_position_size(sizing_value)
    assert sized.recommended_quantity is not None
    account_value, portfolio_value = sizing_value.account, sizing_value.portfolio
    ctx = sizing_value.context
    estimate_values: dict[str, object] = {
        "context": ctx,
        "asset": ctx.asset,
        "instrument_id": ctx.instrument_id,
        "venue": sizing_value.instrument.venue,  # type: ignore[union-attr]
        "account_id": account_value.account_id,
        "account_snapshot_id": account_value.snapshot_id,
        "portfolio_snapshot_id": portfolio_value.snapshot_id,
        "side": side,
        "margin_mode": margin_mode,
        "entry_price": sizing_value.entry,
        "stop_loss": expected_stop,
        "quantity": sized.recommended_quantity,
        "liquidation_price": price(expected_liquidation),
        "formula_model": "LINEAR",
        "formula_version": version("supplied-linear-formula"),
        "source_id": "synthetic-liquidation-source",
        "source_version": version("synthetic-liquidation-source"),
        "exchange_constraints": version("synthetic-exchange-constraints"),
        "basis_request": leverage_value,
        "as_of": T[3],
        "valid_until": T[13],
    }
    estimate_values.update(estimate_overrides or {})
    estimate_value = LiquidationPriceEvidence(**estimate_values)  # type: ignore[arg-type]
    threshold_values: dict[str, object] = {
        "context": ctx,
        "asset": ctx.asset,
        "instrument_id": ctx.instrument_id,
        "side": side,
        "minimum_entry_distance_ratio": Decimal("0.1"),
        "minimum_ratio_version": version("minimum-liquidation-distance"),
        "minimum_stop_buffer": Decimal("5"),
        "normal_adverse_displacement": Decimal("10"),
        "normal_version": version("normal-liquidation-displacement"),
        "stress_adverse_displacement": Decimal("15"),
        "stress_version": version("stress-liquidation-displacement"),
        "quote_currency": USD,
        "as_of": T[3],
        "valid_until": T[13],
    }
    threshold_values.update(threshold_overrides or {})
    thresholds = LiquidationDistanceThresholds(**threshold_values)  # type: ignore[arg-type]
    cost_values: dict[str, object] = {
        "fee_reserve": money("2"),
        "funding_reserve": money("3"),
        "treatment": "ALREADY_INCLUDED_IN_SUPPLIED_ESTIMATE",
        "version": version("liquidation-cost-reserves"),
        "as_of": T[3],
        "valid_until": T[13],
    }
    cost_values.update(cost_overrides or {})
    costs = LiquidationCostEvidence(**cost_values)  # type: ignore[arg-type]
    if not estimate_overrides or "cost_basis" not in estimate_overrides:
        estimate_value = replace(estimate_value, cost_basis=costs)
    return LiquidationAssessmentRequest(
        UUID(int=110),
        leverage_value.evaluated_at,
        leverage_value,
        expected_stop,
        estimate_value,
        thresholds,
        costs,
    )


def stop_assessment_request(
    side: PositionSide = PositionSide.LONG, **overrides: object
) -> StopLossAssessmentRequest:
    account_value = account()
    portfolio_value = portfolio(account_value)
    ctx = replace(
        context(),
        side=side,
        account_snapshot=ContractReference(
            "C-032",
            account_value.snapshot_id,
            "1",
            account_value.content_sha256,
            account_value.valid_until,
        ),
        portfolio_snapshot=ContractReference(
            "C-033",
            portfolio_value.snapshot_id,
            "1",
            portfolio_value.content_sha256,
            portfolio_value.valid_until,
        ),
    )
    invalidation = ref("C-023", valid_until=T[12])
    entry = price("100")
    stop_loss = price("90") if side is PositionSide.LONG else price("110")
    bounds = (
        (price("80"), price("95"))
        if side is PositionSide.LONG
        else (price("105"), price("120"))
    )
    values: dict[str, object] = {
        "result_id": UUID(int=107),
        "context": ctx,
        "account": account_value,
        "portfolio": portfolio_value,
        "entry_price": entry,
        "stop_loss": stop_loss,
        "quantity": Decimal("2"),
        "effective_maximum_loss": money("24.5"),
        "instrument": SizingInstrumentTerms(
            ctx.asset,
            ctx.instrument_id,
            "synthetic-venue",
            "LINEAR",
            USD,
            Decimal("1"),
            Decimal("0.01"),
            Decimal("0.1"),
            Decimal("100"),
            Decimal("0.1"),
            money("100000"),
            money("20"),
            version("instrument"),
        ),
        "costs": SizingCosts(money("1"), money("0.5"), money("0.5"), version("cost")),
        "policy_version": version("policy"),
        "configuration_version": version("configuration"),
        "model_version": version("stop-model"),
        "account_source_version": account_value.source_version,
        "portfolio_source_version": portfolio_value.source_version,
        "strategy_invalidation": invalidation,
        "minimum_stop_distance": Decimal("10"),
        "price_unit_currency": USD,
        "adverse_gap_displacement": Decimal("0.25"),
        "gap_version": version("gap"),
        "evaluated_at": T[4],
        "assumptions_as_of": T[2],
        "assumptions_valid_until": T[10],
        "structural_evidence": StopLossStructuralEvidence(
            invalidation,
            ctx,
            ctx.strategy_version,
            ctx.asset,
            ctx.instrument_id,
            side,
            bounds[0],
            bounds[1],
            version("strategy-invalidation"),
            T[3],
            T[11],
        ),
        "volatility_evidence": StopLossVolatilityEvidence(
            ctx,
            ctx.asset,
            ctx.instrument_id,
            side,
            Decimal("10"),
            USD,
            version("volatility-boundary"),
            T[3],
            T[11],
        ),
        "liquidation_evidence": StopLossLiquidationEvidence(
            ctx,
            ctx.asset,
            ctx.instrument_id,
            side,
            LiquidationAvailability.AVAILABLE,
            price("70") if side is PositionSide.LONG else price("130"),
            Decimal("15"),
            USD,
            False,
            version("liquidation-input"),
            T[3],
            T[11],
        ),
    }
    values.update(overrides)
    return StopLossAssessmentRequest(**values)  # type: ignore[arg-type]


def unpriced_target(sequence: int = 1, allocation: str = "1") -> TakeProfitTarget:
    return replace(target(sequence, allocation), expected_profit=None)


def take_profit_assessment_request(
    side: PositionSide = PositionSide.LONG,
    *,
    targets: tuple[TakeProfitTarget, ...] | None = None,
    target_costs: tuple[SizingCosts, ...] | None = None,
    stop_request: StopLossAssessmentRequest | None = None,
    minimum_risk_reward: Decimal = Decimal("1.4"),
) -> TakeProfitAssessmentRequest:
    stop_request = stop_request or stop_assessment_request(side)
    ctx = stop_request.context
    tp_targets = targets or (
        replace(
            unpriced_target(),
            price=price("120") if side is PositionSide.LONG else price("80"),
        ),
    )
    tp_costs = target_costs or (
        SizingCosts(money("1"), money("0.5"), money("0.5"), version("tp-cost")),
    ) * len(tp_targets)
    sizing_result = PositionSizingResult(
        result_id=UUID(int=108),
        context=ctx,
        outcome=RiskCheckOutcome.PASSED,
        reason_codes=(),
        model_version=version("sizing-model"),
        as_of=T[3],
        evaluated_at=T[4],
        valid_until=T[10],
        content_sha256=HASH_A,
        method=SizingMethod.RISK_BASED,
        sizing_assumptions=(
            stop_request.instrument.version,
            stop_request.costs.version,
        ),
        requested_risk=money("100"),
        requested_notional=money("200"),
        recommended_quantity=stop_request.quantity,
        recommended_notional=money("200"),
        recommended_margin=money("40"),
        stop_distance=Decimal("10"),
        maximum_loss=money("24"),
        account_risk=ratio("0.01", "account-risk"),
        minimum_quantity=Decimal("0.1"),
        maximum_quantity=Decimal("100"),
        quantity_step=Decimal("0.1"),
    )
    bound_limits = (
        (price("100.01"), price("130"))
        if side is PositionSide.LONG
        else (price("70"), price("99.99"))
    )
    target_bounds = tuple(
        TakeProfitTargetBound(
            item.sequence,
            ctx,
            ctx.strategy_version,
            stop_request.strategy_invalidation,
            ctx.asset,
            ctx.instrument_id,
            side,
            bound_limits[0],
            bound_limits[1],
            version(f"target-bound-{item.sequence}"),
            T[3],
            T[9],
        )
        for item in tp_targets
    )
    return TakeProfitAssessmentRequest(
        result_id=UUID(int=109),
        context=ctx,
        entry_price=stop_request.entry_price,
        stop_loss_request=stop_request,
        sizing_result=sizing_result,
        targets=tp_targets,
        target_bounds=target_bounds,
        target_costs=tp_costs,
        minimum_risk_reward=minimum_risk_reward,
        minimum_risk_reward_version=version("minimum-risk-reward"),
        assumptions_version=version("take-profit-assumptions"),
        model_version=version("take-profit-model"),
        evaluated_at=T[4],
        assumptions_as_of=T[2],
        assumptions_valid_until=T[14],
    )


@pytest.mark.parametrize("side", [PositionSide.LONG, PositionSide.SHORT])
def test_stop_assessment_calculates_bounded_loss_for_both_sides(
    side: PositionSide,
) -> None:
    request = stop_assessment_request(side)
    result = calculate_stop_loss_assessment(request)

    assert result.contract_id == "C-078"
    assert result.schema_version == "1"
    assert result.outcome is RiskCheckOutcome.PASSED
    assert result.side is side
    assert result.stop_distance == Decimal("10")
    assert result.stop_distance_ratio == ratio("0.1", "stop-distance-to-entry")
    assert result.maximum_loss == money("24.5")
    assert result.cost_assumptions == (request.costs.version,)
    assert result.valid_until == T[10]
    assert result.content_sha256 != HASH_A


@pytest.mark.parametrize("schema_version", ["1", "2", "3"])
def test_stop_assessment_accepts_only_registered_upstream_reference_versions(
    schema_version: str,
) -> None:
    request = stop_assessment_request()
    ctx = replace(
        request.context,
        signal=replace(request.context.signal, schema_version=schema_version),
        validation=replace(request.context.validation, schema_version=schema_version),
        strategy_version=replace(
            request.context.strategy_version, schema_version=schema_version
        ),
    )
    assert request.structural_evidence is not None
    assert request.volatility_evidence is not None
    assert request.liquidation_evidence is not None
    request = replace(
        request,
        context=ctx,
        structural_evidence=replace(
            request.structural_evidence,
            context=ctx,
            strategy_version=ctx.strategy_version,
        ),
        volatility_evidence=replace(request.volatility_evidence, context=ctx),
        liquidation_evidence=replace(request.liquidation_evidence, context=ctx),
    )
    result = calculate_stop_loss_assessment(request)

    if schema_version in {"1", "2"}:
        assert result.outcome is RiskCheckOutcome.PASSED
        assert result.context == ctx
        assert result.schema_version == "1"
    else:
        assert result.outcome is RiskCheckOutcome.INSUFFICIENT_DATA
        assert "REFERENCE_PROVENANCE_INCOMPLETE" in result.reason_codes


@pytest.mark.parametrize(
    "reference_name",
    ["account_snapshot", "portfolio_snapshot", "strategy_invalidation"],
)
def test_stop_assessment_rejects_schema_two_for_schema_one_only_references(
    reference_name: str,
) -> None:
    request = stop_assessment_request()
    if reference_name == "strategy_invalidation":
        request = replace(
            request,
            strategy_invalidation=replace(
                request.strategy_invalidation, schema_version="2"
            ),
        )
    else:
        request = replace(
            request,
            context=replace(
                request.context,
                **{
                    reference_name: replace(
                        getattr(request.context, reference_name), schema_version="2"
                    )
                },
            ),
        )
    result = calculate_stop_loss_assessment(request)

    assert result.outcome is not RiskCheckOutcome.PASSED
    assert "REFERENCE_PROVENANCE_INCOMPLETE" in result.reason_codes


@pytest.mark.parametrize(
    ("stop_loss", "outcome", "reason"),
    [
        (price("100"), RiskCheckOutcome.FAILED, "STOP_LOSS_DIRECTION_INVALID"),
        (price("101"), RiskCheckOutcome.FAILED, "STOP_LOSS_DIRECTION_INVALID"),
        (None, RiskCheckOutcome.INSUFFICIENT_DATA, "STOP_LOSS_MISSING"),
    ],
)
def test_stop_assessment_fail_closed_for_invalid_or_missing_stop(
    stop_loss: PriceValue | None,
    outcome: RiskCheckOutcome,
    reason: str,
) -> None:
    result = calculate_stop_loss_assessment(
        stop_assessment_request(stop_loss=stop_loss)
    )

    assert result.outcome is outcome
    assert reason in result.reason_codes
    assert result.stop_loss is None
    assert result.stop_distance is None
    assert result.stop_distance_ratio is None
    assert result.maximum_loss is None
    assert canonical_sha256(result)


def test_stop_assessment_fails_closed_when_ratio_cannot_fit_c078() -> None:
    request = stop_assessment_request(
        PositionSide.SHORT,
        stop_loss=price("201"),
    )
    result = calculate_stop_loss_assessment(request)

    assert result.outcome is RiskCheckOutcome.FAILED
    assert "STOP_DISTANCE_RATIO_UNREPRESENTABLE" in result.reason_codes
    assert result.stop_distance == Decimal("101")
    assert result.stop_distance_ratio is None


@pytest.mark.parametrize(
    ("stop_amount", "expected_outcome"),
    [
        ("5.999999999999999999999999999999999", RiskCheckOutcome.PASSED),
        ("6", RiskCheckOutcome.PASSED),
        ("6.000000000000000000000000000000001", RiskCheckOutcome.FAILED),
    ],
)
def test_stop_assessment_checks_exact_ratio_boundary_before_rounding(
    stop_amount: str, expected_outcome: RiskCheckOutcome
) -> None:
    request = stop_assessment_request(PositionSide.SHORT)
    assert request.structural_evidence is not None
    assert request.volatility_evidence is not None
    assert request.liquidation_evidence is not None
    request = replace(
        request,
        entry_price=price("3"),
        stop_loss=price(stop_amount),
        quantity=Decimal("1"),
        minimum_stop_distance=Decimal("0"),
        adverse_gap_displacement=Decimal("0"),
        effective_maximum_loss=money("100"),
        costs=SizingCosts(money("0"), money("0"), money("0"), version("zero-cost")),
        instrument=replace(
            request.instrument, tick_size=Decimal("1e-33"), quantity_step=Decimal("1")
        ),
        structural_evidence=replace(
            request.structural_evidence, lower_stop=price("5"), upper_stop=price("7")
        ),
        volatility_evidence=replace(
            request.volatility_evidence, minimum_distance=Decimal("0")
        ),
        liquidation_evidence=replace(
            request.liquidation_evidence,
            liquidation_price=price("10"),
            minimum_buffer=Decimal("0"),
        ),
    )
    result = calculate_stop_loss_assessment(request)

    assert result.outcome is expected_outcome
    if expected_outcome is RiskCheckOutcome.FAILED:
        assert "STOP_DISTANCE_RATIO_UNREPRESENTABLE" in result.reason_codes
        assert result.stop_distance_ratio is None
    else:
        assert result.stop_distance_ratio is not None
        assert result.stop_distance_ratio.value <= 1


def test_stop_assessment_enforces_tick_quantity_currency_and_notional_limits() -> None:
    tick_mismatch = calculate_stop_loss_assessment(
        stop_assessment_request(entry_price=price("100.005"))
    )
    assert tick_mismatch.outcome is RiskCheckOutcome.FAILED
    assert "ENTRY_PRICE_TICK_MISMATCH" in tick_mismatch.reason_codes

    step_mismatch = calculate_stop_loss_assessment(
        stop_assessment_request(quantity=Decimal("0.15"))
    )
    assert step_mismatch.outcome is RiskCheckOutcome.FAILED
    assert "QUANTITY_STEP_MISMATCH" in step_mismatch.reason_codes

    quantity_out_of_bounds = calculate_stop_loss_assessment(
        stop_assessment_request(quantity=Decimal("100.1"))
    )
    assert quantity_out_of_bounds.outcome is RiskCheckOutcome.FAILED
    assert "QUANTITY_OUT_OF_BOUNDS" in quantity_out_of_bounds.reason_codes

    stop_currency_mismatch = calculate_stop_loss_assessment(
        stop_assessment_request(stop_loss=PriceValue(Decimal("90"), "SYNTHETIC-EUR"))
    )
    assert stop_currency_mismatch.outcome is RiskCheckOutcome.FAILED
    assert "STOP_CURRENCY_MISMATCH" in stop_currency_mismatch.reason_codes
    assert stop_currency_mismatch.maximum_loss is None

    distance_currency_mismatch = calculate_stop_loss_assessment(
        stop_assessment_request(price_unit_currency="SYNTHETIC-EUR")
    )
    assert distance_currency_mismatch.outcome is RiskCheckOutcome.FAILED
    assert "PRICE_DISTANCE_CURRENCY_MISMATCH" in distance_currency_mismatch.reason_codes
    assert distance_currency_mismatch.maximum_loss is None

    cost_currency_mismatch = calculate_stop_loss_assessment(
        stop_assessment_request(
            costs=SizingCosts(
                MoneyValue(Decimal("1"), "SYNTHETIC-EUR"),
                MoneyValue(Decimal("0.5"), "SYNTHETIC-EUR"),
                MoneyValue(Decimal("0.5"), "SYNTHETIC-EUR"),
                version("foreign-costs"),
            )
        )
    )
    assert cost_currency_mismatch.outcome is RiskCheckOutcome.FAILED
    assert "COST_CURRENCY_MISMATCH" in cost_currency_mismatch.reason_codes
    assert cost_currency_mismatch.maximum_loss is None

    small_notional = replace(
        stop_assessment_request(),
        instrument=replace(
            stop_assessment_request().instrument,
            maximum_notional=money("100"),
        ),
    )
    notional_result = calculate_stop_loss_assessment(small_notional)
    assert notional_result.outcome is RiskCheckOutcome.FAILED
    assert "MAXIMUM_NOTIONAL_EXCEEDED" in notional_result.reason_codes


def test_stop_assessment_policy_volatility_and_structural_boundaries() -> None:
    base_request = stop_assessment_request()
    volatility = base_request.volatility_evidence
    assert volatility is not None
    exact_boundary = calculate_stop_loss_assessment(base_request)
    assert exact_boundary.outcome is RiskCheckOutcome.PASSED

    policy_breach = calculate_stop_loss_assessment(
        stop_assessment_request(minimum_stop_distance=Decimal("10.01"))
    )
    assert policy_breach.outcome is RiskCheckOutcome.FAILED
    assert "POLICY_MINIMUM_STOP_DISTANCE_BREACH" in policy_breach.reason_codes

    volatility_breach = calculate_stop_loss_assessment(
        replace(
            base_request,
            volatility_evidence=replace(
                volatility,
                minimum_distance=Decimal("10.01"),
            ),
        )
    )
    assert volatility_breach.outcome is RiskCheckOutcome.FAILED
    assert "VOLATILITY_MINIMUM_DISTANCE_BREACH" in volatility_breach.reason_codes

    interval = base_request.structural_evidence
    assert interval is not None
    upper_edge = calculate_stop_loss_assessment(
        replace(
            base_request,
            stop_loss=interval.upper_stop,
            minimum_stop_distance=Decimal("5"),
            volatility_evidence=replace(volatility, minimum_distance=Decimal("5")),
        )
    )
    assert upper_edge.outcome is RiskCheckOutcome.PASSED
    outside = calculate_stop_loss_assessment(
        stop_assessment_request(stop_loss=price("79"))
    )
    assert outside.outcome is RiskCheckOutcome.FAILED
    assert "STOP_OUTSIDE_STRUCTURAL_INTERVAL" in outside.reason_codes

    wrong_lineage = replace(
        interval,
        strategy_version=ref("C-021"),
    )
    wrong_lineage_result = calculate_stop_loss_assessment(
        replace(base_request, structural_evidence=wrong_lineage)
    )
    assert wrong_lineage_result.outcome is RiskCheckOutcome.FAILED
    assert "STRUCTURAL_LINEAGE_MISMATCH" in wrong_lineage_result.reason_codes


def test_stop_assessment_liquidation_side_buffer_applicability_and_staleness() -> None:
    base_request = stop_assessment_request()
    liquidation = base_request.liquidation_evidence
    assert liquidation is not None
    wrong_side_evidence = replace(
        liquidation,
        liquidation_price=price("95"),
    )
    wrong_side = calculate_stop_loss_assessment(
        replace(base_request, liquidation_evidence=wrong_side_evidence)
    )
    assert wrong_side.outcome is RiskCheckOutcome.FAILED
    assert "LIQUIDATION_NOT_BEYOND_STOP" in wrong_side.reason_codes

    short_request = stop_assessment_request(PositionSide.SHORT)
    short_liquidation = short_request.liquidation_evidence
    assert short_liquidation is not None
    short_wrong_side = calculate_stop_loss_assessment(
        replace(
            short_request,
            liquidation_evidence=replace(
                short_liquidation, liquidation_price=price("105")
            ),
        )
    )
    assert short_wrong_side.outcome is RiskCheckOutcome.FAILED
    assert "LIQUIDATION_NOT_BEYOND_STOP" in short_wrong_side.reason_codes

    insufficient_buffer = replace(
        liquidation,
        liquidation_price=price("80"),
        minimum_buffer=Decimal("11"),
    )
    buffer_result = calculate_stop_loss_assessment(
        replace(base_request, liquidation_evidence=insufficient_buffer)
    )
    assert buffer_result.outcome is RiskCheckOutcome.FAILED
    assert "STOP_TO_LIQUIDATION_BUFFER_BREACH" in buffer_result.reason_codes

    spot_not_applicable = replace(
        liquidation,
        availability=LiquidationAvailability.NOT_APPLICABLE,
        liquidation_price=None,
        fully_funded_spot=True,
    )
    spot_result = calculate_stop_loss_assessment(
        replace(base_request, liquidation_evidence=spot_not_applicable)
    )
    assert spot_result.outcome is RiskCheckOutcome.PASSED
    assert "LIQUIDATION_NOT_APPLICABLE_FULLY_FUNDED_SPOT" in spot_result.reason_codes

    unknown = replace(
        liquidation,
        availability=LiquidationAvailability.UNAVAILABLE,
        liquidation_price=None,
    )
    unknown_result = calculate_stop_loss_assessment(
        replace(base_request, liquidation_evidence=unknown)
    )
    assert unknown_result.outcome is RiskCheckOutcome.INSUFFICIENT_DATA
    assert "LIQUIDATION_APPLICABILITY_UNKNOWN" in unknown_result.reason_codes

    stale = replace(
        liquidation,
        valid_until=T[3],
    )
    stale_result = calculate_stop_loss_assessment(
        replace(base_request, liquidation_evidence=stale)
    )
    assert stale_result.outcome is RiskCheckOutcome.INSUFFICIENT_DATA
    assert "LIQUIDATION_EVIDENCE_NOT_CURRENT" in stale_result.reason_codes
    assert stale_result.valid_until == T[4]


def test_stop_assessment_matches_context_versions_budget_and_digest() -> None:
    request = stop_assessment_request()
    result = calculate_stop_loss_assessment(request)
    assert result.outcome is RiskCheckOutcome.PASSED

    bad_source_version = calculate_stop_loss_assessment(
        replace(request, account_source_version=version("unexpected-account-source"))
    )
    assert bad_source_version.outcome is RiskCheckOutcome.FAILED
    assert "ACCOUNT_SOURCE_VERSION_MISMATCH" in bad_source_version.reason_codes

    bad_snapshot_reference_context = replace(
        request.context,
        account_snapshot=replace(
            request.context.account_snapshot, content_sha256="b" * 64
        ),
    )
    bad_snapshot_reference = calculate_stop_loss_assessment(
        replace(request, context=bad_snapshot_reference_context)
    )
    assert bad_snapshot_reference.outcome is RiskCheckOutcome.FAILED
    assert "SNAPSHOT_REFERENCE_MISMATCH" in bad_snapshot_reference.reason_codes

    under_budget = calculate_stop_loss_assessment(
        replace(request, effective_maximum_loss=money("24.49"))
    )
    assert under_budget.outcome is RiskCheckOutcome.FAILED
    assert "EFFECTIVE_MAXIMUM_LOSS_EXCEEDED" in under_budget.reason_codes
    assert under_budget.maximum_loss == money("24.5")

    changed_request = replace(request, adverse_gap_displacement=Decimal("0.5"))
    changed_result = calculate_stop_loss_assessment(changed_request)
    assert changed_result.content_sha256 != result.content_sha256
    assert changed_result.maximum_loss == money("25")
    changed_quantity = calculate_stop_loss_assessment(
        replace(request, quantity=Decimal("1"))
    )
    assert changed_quantity.content_sha256 != result.content_sha256

    expired_assumptions = calculate_stop_loss_assessment(
        replace(request, assumptions_valid_until=T[3])
    )
    assert expired_assumptions.outcome is RiskCheckOutcome.INSUFFICIENT_DATA
    assert "ASSUMPTIONS_NOT_CURRENT" in expired_assumptions.reason_codes
    assert expired_assumptions.valid_until == T[4]

    missing_evidence = calculate_stop_loss_assessment(
        replace(
            request,
            structural_evidence=None,
            volatility_evidence=None,
            liquidation_evidence=None,
        )
    )
    assert missing_evidence.outcome is RiskCheckOutcome.INSUFFICIENT_DATA
    assert {
        "STRUCTURAL_EVIDENCE_MISSING",
        "VOLATILITY_EVIDENCE_MISSING",
        "LIQUIDATION_EVIDENCE_MISSING",
    }.issubset(missing_evidence.reason_codes)
    assert missing_evidence.valid_until == T[4]

    at_expiry = calculate_stop_loss_assessment(
        replace(request, assumptions_valid_until=T[4])
    )
    assert at_expiry.outcome is RiskCheckOutcome.PASSED


def test_stop_assessment_isolated_decimal_context_and_loss_budget_boundary() -> None:
    request = stop_assessment_request()
    with localcontext(Context(prec=2, rounding=ROUND_DOWN)):
        exact_budget = calculate_stop_loss_assessment(request)
        below_budget = calculate_stop_loss_assessment(
            replace(request, effective_maximum_loss=money("24.499"))
        )

    assert exact_budget.outcome is RiskCheckOutcome.PASSED
    assert exact_budget.maximum_loss == money("24.5")
    assert exact_budget.maximum_loss is not None
    assert exact_budget.maximum_loss.amount <= request.effective_maximum_loss.amount
    assert below_budget.outcome is RiskCheckOutcome.FAILED

    explicit_zero_costs = calculate_stop_loss_assessment(
        replace(
            request,
            costs=SizingCosts(
                money("0"),
                money("0"),
                money("0"),
                version("explicit-zero-costs"),
            ),
            adverse_gap_displacement=Decimal("0"),
            effective_maximum_loss=money("20"),
        )
    )
    assert explicit_zero_costs.outcome is RiskCheckOutcome.PASSED
    assert explicit_zero_costs.maximum_loss == money("20")

    unrepresentable = replace(
        request,
        quantity=Decimal("1.2345678901234567890123456789012345"),
    )
    with pytest.raises(RiskContractError, match="precision 34"):
        calculate_stop_loss_assessment(unrepresentable)


@pytest.mark.parametrize(
    ("method", "inputs", "quantity", "loss"),
    [
        (SizingMethod.RISK_BASED, {}, "10", "120"),
        (
            SizingMethod.FIXED_NOTIONAL,
            {"requested_notional": money("600")},
            "6",
            "72",
        ),
        (
            SizingMethod.PERCENTAGE_OF_EQUITY,
            {"equity_fraction": Decimal("0.02")},
            "2",
            "24",
        ),
        (
            SizingMethod.VOLATILITY_ADJUSTED,
            {
                "volatility_loss_per_unit": money("22"),
                "volatility_version": version("volatility"),
            },
            "5",
            "120",
        ),
        (
            SizingMethod.FRACTIONAL_KELLY,
            {
                "win_probability": Decimal("0.6"),
                "win_loss_ratio": Decimal("1"),
                "kelly_fraction": Decimal("0.25"),
                "kelly_version": version("kelly"),
            },
            "5",
            "60",
        ),
    ],
)
def test_sizing_calculates_all_five_methods(
    method: SizingMethod, inputs: dict[str, object], quantity: str, loss: str
) -> None:
    request = sizing_request(method, **inputs)
    result = calculate_position_size(request)
    assert result.outcome is RiskCheckOutcome.PASSED
    assert result.contract_id == "C-036" and result.schema_version == "1"
    assert result.recommended_quantity == Decimal(quantity)
    assert result.recommended_notional == money(str(Decimal(quantity) * 100))
    assert result.recommended_margin == money(str(Decimal(quantity) * 20))
    assert result.maximum_loss == money(loss)
    assert result.account_risk == ratio(
        str(Decimal(loss) / 10000), "maximum-loss/equity"
    )
    assert result.stop_distance == Decimal("10")
    assert result.valid_until == T[14]
    assert calculate_position_size(request) == result
    assert request.budget_version in result.sizing_assumptions
    assert request.policy_version in result.sizing_assumptions
    assert request.configuration_version in result.sizing_assumptions
    assert request.instrument is not None and request.costs is not None
    assert request.instrument.version in result.sizing_assumptions
    assert request.costs.version in result.sizing_assumptions


@pytest.mark.parametrize(
    ("updates", "expected"),
    [
        ({"maximum_quantity": Decimal("3.09")}, "3"),
        ({"maximum_notional": money("305")}, "3"),
        ({"initial_margin_per_unit": money("2300")}, "3"),
        ({"quantity_step": Decimal("3")}, "9"),
    ],
)
def test_sizing_applies_quantity_notional_margin_and_step_caps(
    updates: dict[str, object], expected: str
) -> None:
    request = sizing_request()
    assert request.instrument is not None
    request = replace(request, instrument=replace(request.instrument, **updates))
    result = calculate_position_size(request)
    assert result.recommended_quantity == Decimal(expected)
    assert result.maximum_loss is not None
    assert result.maximum_loss.amount <= request.effective_risk.amount
    assert result.recommended_margin is not None
    assert request.account.free_margin is not None
    assert result.recommended_margin.amount <= request.account.free_margin.amount
    assert result.recommended_notional is not None
    assert (
        result.recommended_notional.amount <= request.instrument.maximum_notional.amount
    )


@pytest.mark.parametrize(
    ("method", "inputs"),
    [
        (SizingMethod.FIXED_NOTIONAL, {"requested_notional": money("2000")}),
        (SizingMethod.PERCENTAGE_OF_EQUITY, {"equity_fraction": Decimal("0.2")}),
        (
            SizingMethod.FRACTIONAL_KELLY,
            {
                "win_probability": Decimal("0.8"),
                "win_loss_ratio": Decimal("1"),
                "kelly_fraction": Decimal("1"),
                "kelly_version": version("kelly"),
            },
        ),
    ],
)
def test_sizing_reduced_targets_are_explicit(
    method: SizingMethod, inputs: dict[str, object]
) -> None:
    result = calculate_position_size(sizing_request(method, **inputs))
    assert result.outcome is RiskCheckOutcome.WARNING
    assert result.reason_codes == ("REQUESTED_TARGET_REDUCED",)
    assert result.recommended_quantity == Decimal("10")


@pytest.mark.parametrize(
    ("updates", "expected"),
    [
        ({"maximum_quantity": Decimal("3")}, "3"),
        ({"quantity_step": Decimal("2")}, "4"),
    ],
)
def test_sizing_volatility_target_reductions_are_explicit(
    updates: dict[str, object], expected: str
) -> None:
    request = sizing_request(
        SizingMethod.VOLATILITY_ADJUSTED,
        volatility_loss_per_unit=money("22"),
        volatility_version=version("volatility"),
    )
    assert request.instrument is not None
    request = replace(request, instrument=replace(request.instrument, **updates))
    result = calculate_position_size(request)
    assert result.outcome is RiskCheckOutcome.WARNING
    assert result.reason_codes == ("REQUESTED_TARGET_REDUCED",)
    assert result.recommended_quantity == Decimal(expected)
    assert result.maximum_loss is not None
    assert result.maximum_loss.amount <= request.effective_risk.amount


def test_sizing_rounds_down_and_never_raises_quantity_to_minimum() -> None:
    request = sizing_request(effective_risk=money("1"))
    result = calculate_position_size(request)
    assert result.outcome is RiskCheckOutcome.FAILED
    assert result.reason_codes == ("NO_TRADE_BELOW_MINIMUM",)
    assert result.recommended_quantity is None
    assert result.recommended_notional is None
    assert result.recommended_margin is None
    assert result.maximum_loss is None
    result = calculate_position_size(
        sizing_request(SizingMethod.FIXED_NOTIONAL, requested_notional=money("605"))
    )
    assert result.recommended_quantity == Decimal("6")
    assert result.reason_codes == ("REQUESTED_TARGET_REDUCED",)


@pytest.mark.parametrize(
    ("method", "reason"),
    [
        (SizingMethod.FIXED_NOTIONAL, "NOTIONAL_MISSING"),
        (SizingMethod.PERCENTAGE_OF_EQUITY, "EQUITY_FRACTION_MISSING"),
        (SizingMethod.VOLATILITY_ADJUSTED, "VOLATILITY_INPUTS_MISSING"),
        (SizingMethod.FRACTIONAL_KELLY, "KELLY_INPUTS_MISSING"),
    ],
)
def test_sizing_missing_method_inputs_never_fall_back(
    method: SizingMethod, reason: str
) -> None:
    result = calculate_position_size(sizing_request(method))
    assert result.outcome is RiskCheckOutcome.INSUFFICIENT_DATA
    assert result.reason_codes == (reason,)
    assert result.recommended_quantity is None


@pytest.mark.parametrize(
    "mode",
    [
        RiskPolicyMode.PAPER,
        RiskPolicyMode.SHADOW,
        RiskPolicyMode.TESTNET,
        RiskPolicyMode.LIVE_SUPERVISED,
    ],
)
def test_sizing_kelly_is_research_only(mode: RiskPolicyMode) -> None:
    result = calculate_position_size(
        sizing_request(
            SizingMethod.FRACTIONAL_KELLY,
            mode=mode,
            win_probability=Decimal("0.6"),
            win_loss_ratio=Decimal("1"),
            kelly_fraction=Decimal("0.25"),
            kelly_version=version("kelly"),
        )
    )
    assert result.reason_codes == ("KELLY_RESEARCH_ONLY",)
    assert result.recommended_quantity is None


@pytest.mark.parametrize("probability", ["0", "0.4", "0.5"])
def test_sizing_nonpositive_kelly_returns_no_trade(probability: str) -> None:
    result = calculate_position_size(
        sizing_request(
            SizingMethod.FRACTIONAL_KELLY,
            win_probability=Decimal(probability),
            win_loss_ratio=Decimal("1"),
            kelly_fraction=Decimal("0.25"),
            kelly_version=version("kelly"),
        )
    )
    assert result.outcome is RiskCheckOutcome.FAILED
    assert result.reason_codes == ("NO_TRADE_NONPOSITIVE_KELLY",)
    assert result.recommended_quantity is None


@pytest.mark.parametrize(
    ("updates", "reason"),
    [
        ({"stop": price("100")}, "INVALID_STOP_DIRECTION"),
        ({"stop": price("110")}, "INVALID_STOP_DIRECTION"),
        ({"stop": PriceValue(Decimal("90"), "FOREIGN")}, "SIZING_CURRENCY_MISMATCH"),
        (
            {"effective_risk": MoneyValue(Decimal("120"), "FOREIGN")},
            "SIZING_CURRENCY_MISMATCH",
        ),
        ({"entry": price("100.001")}, "PRICE_OFF_TICK"),
        ({"instrument": None}, "SIZING_ASSUMPTIONS_MISSING"),
        ({"costs": None}, "SIZING_ASSUMPTIONS_MISSING"),
        ({"assumptions_valid_until": T[3]}, "ASSUMPTIONS_NOT_CURRENT"),
        ({"assumptions_as_of": T[5]}, "ASSUMPTIONS_NOT_CURRENT"),
        ({"evaluated_at": T[16]}, "SNAPSHOT_NOT_CURRENT"),
        ({"effective_risk": money("10001")}, "RISK_EXCEEDS_EQUITY"),
    ],
)
def test_sizing_rejects_invalid_and_unknown_evidence(
    updates: dict[str, object], reason: str
) -> None:
    result = calculate_position_size(sizing_request(**updates))
    assert result.reason_codes == (reason,)
    assert result.outcome in {
        RiskCheckOutcome.FAILED,
        RiskCheckOutcome.INSUFFICIENT_DATA,
    }
    assert result.recommended_quantity is None


def test_sizing_short_direction_multiplier_and_explicit_zero_costs() -> None:
    request = sizing_request(stop=price("110"))
    assert request.instrument is not None and request.costs is not None
    request = replace(
        request,
        context=replace(request.context, side=PositionSide.SHORT),
        instrument=replace(request.instrument, contract_multiplier=Decimal("2")),
        costs=SizingCosts(money("0"), money("0"), money("0"), version("zero-cost")),
    )
    result = calculate_position_size(request)
    assert result.outcome is RiskCheckOutcome.PASSED
    assert result.recommended_quantity == Decimal("6")
    assert result.recommended_notional == money("1200")
    assert result.maximum_loss == money("120")
    assert calculate_position_size(replace(request, stop=price("90"))).reason_codes == (
        "INVALID_STOP_DIRECTION",
    )


def test_sizing_checks_context_snapshot_identity_freshness_and_model() -> None:
    request = sizing_request()
    assert request.instrument is not None
    changed = replace(request.context.account_snapshot, content_sha256="b" * 64)
    invalid_context = replace(request.context, account_snapshot=changed)
    assert calculate_position_size(
        replace(request, context=invalid_context)
    ).reason_codes == ("SNAPSHOT_REFERENCE_MISMATCH",)
    invalid_portfolio = portfolio()
    assert calculate_position_size(
        replace(request, portfolio=invalid_portfolio)
    ).reason_codes == ("ACCOUNT_PORTFOLIO_MISMATCH",)
    invalid_signal = replace(request.context.signal, valid_until=T[3])
    assert calculate_position_size(
        replace(request, context=replace(request.context, signal=invalid_signal))
    ).reason_codes == ("CONTEXT_EVIDENCE_NOT_CURRENT",)
    assert calculate_position_size(
        replace(request, instrument=replace(request.instrument, model="INVERSE"))
    ).reason_codes == ("UNSUPPORTED_INSTRUMENT_MODEL",)
    assert calculate_position_size(
        replace(request, instrument=replace(request.instrument, instrument_id="OTHER"))
    ).reason_codes == ("INSTRUMENT_CONTEXT_MISMATCH",)
    assert (
        calculate_position_size(replace(request, evaluated_at=T[14])).outcome
        is RiskCheckOutcome.PASSED
    )
    assert (
        calculate_position_size(replace(request, evaluated_at=T[3])).outcome
        is RiskCheckOutcome.PASSED
    )


def test_sizing_digest_binds_inputs_versions_and_outputs() -> None:
    request = sizing_request()
    result = calculate_position_size(request)
    expected = canonical_sha256(
        {
            "request": request,
            "result": {
                item.name: getattr(result, item.name)
                for item in fields(result)
                if item.name != "content_sha256"
            },
        }
    )
    assert result.content_sha256 == expected
    altered = replace(request, policy_version=version("different-policy"))
    assert calculate_position_size(altered).content_sha256 != result.content_sha256
    assert (
        calculate_position_size(
            replace(request, effective_risk=money("119"))
        ).content_sha256
        != result.content_sha256
    )
    with localcontext() as ambient:
        ambient.prec = 5
        ambient.rounding = ROUND_UP
        ambient.traps[Inexact] = True
        assert calculate_position_size(request) == result


def test_sizing_nonterminating_risk_division_never_exceeds_budget() -> None:
    request = sizing_request(effective_risk=money("1"))
    assert request.instrument is not None
    request = replace(
        request,
        stop=price("99.7"),
        instrument=replace(
            request.instrument,
            quantity_step=Decimal("0.001"),
            minimum_quantity=Decimal("0.001"),
        ),
        costs=SizingCosts(money("0"), money("0"), money("0"), version("zero-cost")),
    )
    result = calculate_position_size(request)
    assert result.recommended_quantity == Decimal("3.333")
    assert result.maximum_loss == money("0.9999")
    assert result.maximum_loss.amount <= request.effective_risk.amount
    with pytest.raises(RiskContractError, match="precision 34"):
        calculate_position_size(
            replace(
                request,
                instrument=replace(
                    request.instrument,
                    contract_multiplier=Decimal("1.123456789012345678901234567890123"),
                ),
            )
        )


def test_sizing_low_volatility_cannot_reduce_stop_risk() -> None:
    request = sizing_request(
        SizingMethod.VOLATILITY_ADJUSTED,
        volatility_loss_per_unit=money("1"),
        volatility_version=version("volatility"),
    )
    result = calculate_position_size(request)
    assert result.recommended_quantity == Decimal("10")
    assert result.maximum_loss == money("120")
    assert request.volatility_version in result.sizing_assumptions


def test_sizing_rejects_nonvalid_future_and_inconsistent_portfolio_evidence() -> None:
    request = sizing_request()
    invalid = replace(
        request.portfolio, state=SnapshotState.STALE, reason_codes=("STALE",)
    )
    assert calculate_position_size(
        replace(request, portfolio=invalid)
    ).reason_codes == ("SNAPSHOT_NOT_VALID",)
    assert calculate_position_size(
        replace(request, portfolio=replace(request.portfolio, equity=money("9000")))
    ).reason_codes == ("PORTFOLIO_EQUITY_MISMATCH",)
    future = replace(request.portfolio, as_of=T[5], captured_at=T[6])
    assert calculate_position_size(replace(request, portfolio=future)).reason_codes == (
        "SNAPSHOT_NOT_CURRENT",
    )
    stale_position = replace(request.portfolio.positions[0], valid_until=T[3])
    assert calculate_position_size(
        replace(
            request,
            portfolio=replace(request.portfolio, positions=(stale_position,)),
        )
    ).reason_codes == ("SNAPSHOT_NOT_CURRENT",)
    assert request.instrument is not None and request.costs is not None
    with pytest.raises(RiskContractError, match="positive"):
        replace(request.instrument, initial_margin_per_unit=money("0"))
    with pytest.raises(RiskContractError, match="non-negative"):
        replace(request.costs, funding=money("-1"))


@pytest.mark.parametrize(
    "updates",
    [
        {"effective_risk": money("0")},
        {"equity_fraction": Decimal("0")},
        {"kelly_fraction": Decimal("1.1")},
        {"win_probability": Decimal("-0.1")},
        {"win_loss_ratio": Decimal("0")},
        {"equity_fraction": Decimal("NaN")},
        {"win_probability": 0.6},
    ],
)
def test_sizing_rejects_malformed_request(updates: dict[str, object]) -> None:
    with pytest.raises(RiskContractError):
        sizing_request(**updates)


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


@pytest.mark.parametrize(
    ("side", "margin_mode"),
    [
        (PositionSide.LONG, MarginMode.ISOLATED),
        (PositionSide.SHORT, MarginMode.CROSS),
    ],
)
def test_leverage_assessment_calculates_bounded_linear_margin(
    side: PositionSide, margin_mode: MarginMode
) -> None:
    request = leverage_request(side=side, margin_mode=margin_mode)

    result = calculate_leverage_assessment(request)

    assert result.outcome is RiskCheckOutcome.PASSED
    assert result.margin_mode is margin_mode
    assert result.requested_leverage == Decimal("5")
    assert result.maximum_permitted_leverage == Decimal("10")
    assert result.effective_leverage == Decimal("5")
    assert result.post_trade_portfolio_leverage == Decimal("0.1101")
    assert result.initial_margin == money("200")
    assert result.maintenance_margin == money("10")
    assert result.proposed_margin == money("200")
    assert result.post_trade_free_margin == money("6770")
    assert result.exchange_constraints == request.margin_rule.version
    assert result.content_sha256 != HASH_A


def test_leverage_assessment_accepts_exact_caps_buffers_zero_reserve_and_tier() -> None:
    request = leverage_request()
    request = replace(
        request,
        requested_leverage=Decimal("10"),
        maximum_post_trade_gross_leverage=Decimal("0.1101"),
        minimum_remaining_free_margin=money("6800"),
        additional_reserved_cost=money("0"),
        margin_rule=replace(
            request.margin_rule,
            tier_lower_bound=money("1101"),
            tier_upper_bound=money("1101"),
            maintenance_margin_rate=Decimal("0"),
        ),
    )

    result = calculate_leverage_assessment(request)

    assert result.outcome is RiskCheckOutcome.PASSED
    assert result.initial_margin == money("200")
    assert result.maintenance_margin == money("0")
    assert result.post_trade_free_margin == money("6800")
    assert result.post_trade_portfolio_leverage == Decimal("0.1101")


@pytest.mark.parametrize(
    "cap_name",
    [
        "policy_maximum_leverage",
        "account_maximum_leverage",
        "venue_maximum_leverage",
    ],
)
def test_leverage_assessment_enforces_each_explicit_leverage_cap(
    cap_name: str,
) -> None:
    request = leverage_request(**{cap_name: Decimal("5")})
    assert calculate_leverage_assessment(request).outcome is RiskCheckOutcome.PASSED

    failed = calculate_leverage_assessment(
        replace(request, **{cap_name: Decimal("4.99")})
    )
    assert failed.outcome is RiskCheckOutcome.FAILED
    assert "REQUESTED_LEVERAGE_EXCEEDS_CAP" in failed.reason_codes


@pytest.mark.parametrize(
    ("updates", "reason"),
    [
        ({"requested_leverage": Decimal("11")}, "REQUESTED_LEVERAGE_EXCEEDS_CAP"),
        (
            {"maximum_post_trade_gross_leverage": Decimal("0.11")},
            "POST_TRADE_GROSS_LEVERAGE_EXCEEDS_CAP",
        ),
        (
            {"minimum_remaining_free_margin": money("6801")},
            "FREE_MARGIN_BUFFER_BREACHED",
        ),
    ],
)
def test_leverage_assessment_fails_hard_limits_without_recommendations(
    updates: dict[str, object], reason: str
) -> None:
    result = calculate_leverage_assessment(leverage_request(**updates))

    assert result.outcome is RiskCheckOutcome.FAILED
    assert reason in result.reason_codes
    assert result.initial_margin is None
    assert result.effective_leverage is None
    assert result.post_trade_portfolio_leverage is None


def test_leverage_assessment_rejects_margin_and_funds_shortfalls() -> None:
    too_high_rate = leverage_request()
    too_high_rate = replace(
        too_high_rate,
        margin_rule=replace(
            too_high_rate.margin_rule,
            initial_margin_rate=Decimal("0.5"),
        ),
    )
    margin_result = calculate_leverage_assessment(too_high_rate)
    assert margin_result.outcome is RiskCheckOutcome.FAILED
    assert "PROPOSED_MARGIN_INSUFFICIENT" in margin_result.reason_codes

    request = leverage_request()
    account_value = replace(
        request.sizing_request.account,
        available_balance=money("100"),
    )
    portfolio_value = replace(
        request.sizing_request.portfolio,
        account_snapshot=account_value,
    )
    sizing_value = replace(
        request.sizing_request,
        account=account_value,
        portfolio=portfolio_value,
    )
    funds_result = calculate_leverage_assessment(
        replace(request, sizing_request=sizing_value)
    )
    assert funds_result.outcome is RiskCheckOutcome.FAILED
    assert "AVAILABLE_BALANCE_INSUFFICIENT" in funds_result.reason_codes

    free_margin_result = calculate_leverage_assessment(
        leverage_request(additional_reserved_cost=money("7000"))
    )
    assert free_margin_result.outcome is RiskCheckOutcome.FAILED
    assert "FREE_MARGIN_INSUFFICIENT" in free_margin_result.reason_codes


def test_leverage_assessment_propagates_upstream_sizing_failure() -> None:
    request = leverage_request()
    failed_sizing = replace(
        request.sizing_request,
        effective_risk=money("1"),
    )

    result = calculate_leverage_assessment(
        replace(request, sizing_request=failed_sizing)
    )

    assert result.outcome is RiskCheckOutcome.FAILED
    assert "NO_TRADE_BELOW_MINIMUM" in result.reason_codes
    assert result.proposed_margin is None


def test_leverage_assessment_rejects_inconsistent_recomputed_sizing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = leverage_request()
    recomputed = calculate_position_size(request.sizing_request)
    inconsistent = replace(recomputed, recommended_notional=money("999"))
    monkeypatch.setattr(
        risk_contracts,
        "calculate_position_size",
        lambda _: inconsistent,
    )

    result = calculate_leverage_assessment(request)

    assert result.outcome is RiskCheckOutcome.FAILED
    assert "SIZING_AMOUNT_INCONSISTENT" in result.reason_codes


def test_leverage_assessment_sums_gross_positions_and_supports_explicit_empty() -> None:
    request = leverage_request()
    opposite = replace(
        request.sizing_request.portfolio.positions[0],
        snapshot_id=uuid4(),
        position_id=uuid4(),
        side=PositionSide.SHORT,
    )
    portfolio_value = replace(
        request.sizing_request.portfolio,
        positions=(*request.sizing_request.portfolio.positions, opposite),
        gross_exposure=money("202"),
    )
    gross_result = calculate_leverage_assessment(
        replace(
            request,
            sizing_request=replace(request.sizing_request, portfolio=portfolio_value),
        )
    )
    assert gross_result.outcome is RiskCheckOutcome.PASSED
    assert gross_result.post_trade_portfolio_leverage == Decimal("0.1202")

    empty_portfolio = replace(
        request.sizing_request.portfolio,
        positions=(),
        gross_exposure=money("0"),
    )
    empty_result = calculate_leverage_assessment(
        replace(
            request,
            sizing_request=replace(request.sizing_request, portfolio=empty_portfolio),
        )
    )
    assert empty_result.outcome is RiskCheckOutcome.PASSED
    assert empty_result.post_trade_portfolio_leverage == Decimal("0.1")


def test_leverage_assessment_requires_current_matching_rule_and_positions() -> None:
    request = leverage_request()
    assert (
        calculate_leverage_assessment(replace(request, margin_rule=None)).outcome
        is RiskCheckOutcome.INSUFFICIENT_DATA
    )
    assert (
        calculate_leverage_assessment(
            replace(
                request,
                margin_rule=replace(request.margin_rule, valid_until=T[3]),
            )
        ).outcome
        is RiskCheckOutcome.INSUFFICIENT_DATA
    )
    assert (
        calculate_leverage_assessment(
            replace(
                request,
                margin_rule=replace(request.margin_rule, valid_until=T[4]),
            )
        ).outcome
        is RiskCheckOutcome.PASSED
    )
    assert (
        calculate_leverage_assessment(
            replace(
                request,
                margin_rule=replace(request.margin_rule, model="UNKNOWN"),
            )
        ).outcome
        is RiskCheckOutcome.FAILED
    )
    assert (
        calculate_leverage_assessment(
            replace(
                request,
                margin_rule=replace(request.margin_rule, margin_mode=MarginMode.CROSS),
            )
        ).outcome
        is RiskCheckOutcome.FAILED
    )
    assert (
        calculate_leverage_assessment(
            replace(
                request,
                margin_rule=replace(
                    request.margin_rule,
                    account_id=uuid4(),
                ),
            )
        ).outcome
        is RiskCheckOutcome.FAILED
    )
    assert (
        calculate_leverage_assessment(
            replace(
                request,
                margin_rule=replace(
                    request.margin_rule,
                    tier_lower_bound=money("1102"),
                ),
            )
        ).outcome
        is RiskCheckOutcome.FAILED
    )
    assert (
        calculate_leverage_assessment(
            replace(
                request,
                margin_rule=replace(
                    request.margin_rule,
                    tier_lower_bound=MoneyValue(Decimal("0"), "OTHER-USD"),
                    tier_upper_bound=MoneyValue(Decimal("100000"), "OTHER-USD"),
                ),
            )
        ).outcome
        is RiskCheckOutcome.FAILED
    )

    position_value = request.sizing_request.portfolio.positions[0]
    stale = replace(position_value, valid_until=T[3])
    stale_portfolio = replace(request.sizing_request.portfolio, positions=(stale,))
    assert (
        calculate_leverage_assessment(
            replace(
                request,
                sizing_request=replace(
                    request.sizing_request, portfolio=stale_portfolio
                ),
            )
        ).outcome
        is RiskCheckOutcome.INSUFFICIENT_DATA
    )
    foreign_position = replace(position_value, account_id=uuid4())
    foreign_portfolio = replace(
        request.sizing_request.portfolio,
        state=SnapshotState.INCOMPLETE,
        reason_codes=("INCOMPLETE",),
        positions=(foreign_position,),
    )
    foreign_result = calculate_leverage_assessment(
        replace(
            request,
            sizing_request=replace(request.sizing_request, portfolio=foreign_portfolio),
        )
    )
    assert foreign_result.outcome is RiskCheckOutcome.FAILED
    assert "POSITION_ACCOUNT_MISMATCH" in foreign_result.reason_codes

    duplicate = replace(
        position_value,
        snapshot_id=position_value.snapshot_id,
        position_id=uuid4(),
    )
    duplicate_portfolio = replace(
        request.sizing_request.portfolio,
        positions=(position_value, duplicate),
        gross_exposure=money("202"),
    )
    assert (
        calculate_leverage_assessment(
            replace(
                request,
                sizing_request=replace(
                    request.sizing_request, portfolio=duplicate_portfolio
                ),
            )
        ).outcome
        is RiskCheckOutcome.FAILED
    )


def test_leverage_assessment_schema_two_warnings_digest_and_decimal_context() -> None:
    request = leverage_request()
    context_value = request.sizing_request.context
    schema_two = replace(
        context_value,
        signal=replace(context_value.signal, schema_version="2"),
        validation=replace(context_value.validation, schema_version="2"),
        strategy_version=replace(context_value.strategy_version, schema_version="2"),
    )
    warning_sizing = replace(
        request.sizing_request,
        context=schema_two,
        method=SizingMethod.FIXED_NOTIONAL,
        requested_notional=money("2000"),
    )
    warning_request = replace(request, sizing_request=warning_sizing)
    with localcontext(Context(prec=4, rounding=ROUND_DOWN)):
        result = calculate_leverage_assessment(warning_request)
    assert result.outcome is RiskCheckOutcome.WARNING
    assert "REQUESTED_TARGET_REDUCED" in result.reason_codes
    assert (
        result.content_sha256 != calculate_leverage_assessment(request).content_sha256
    )
    assert (
        calculate_leverage_assessment(
            replace(request, requested_leverage=Decimal("6"))
        ).content_sha256
        != calculate_leverage_assessment(request).content_sha256
    )
    expiry_boundary = replace(
        request,
        sizing_request=replace(
            request.sizing_request,
            assumptions_valid_until=request.evaluated_at,
        ),
        margin_rule=replace(
            request.margin_rule,
            valid_until=request.evaluated_at,
        ),
    )
    assert (
        calculate_leverage_assessment(expiry_boundary).outcome
        is RiskCheckOutcome.PASSED
    )


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


@pytest.mark.parametrize("side", [PositionSide.LONG, PositionSide.SHORT])
def test_take_profit_calculates_after_cost_directional_profit_for_both_sides(
    side: PositionSide,
) -> None:
    request = take_profit_assessment_request(side)
    result = calculate_take_profit_assessment(request)

    assert result.contract_id == "C-079"
    assert result.schema_version == "1"
    assert result.result_id == request.result_id
    assert result.evaluated_at == request.evaluated_at
    assert result.outcome is RiskCheckOutcome.PASSED
    assert result.expected_profit == money("36")
    assert result.targets[0].expected_profit == money("36")
    assert result.risk_reward_ratio is not None
    assert result.valid_until == T[9]
    assert result.content_sha256 != HASH_A


def test_take_profit_partial_targets_use_each_explicit_cost_and_exact_steps() -> None:
    request = take_profit_assessment_request(
        targets=(
            replace(unpriced_target(sequence=1, allocation="0.5"), price=price("110")),
            replace(unpriced_target(sequence=2, allocation="0.5"), price=price("120")),
        ),
        target_costs=(
            SizingCosts(money("1"), money("0.5"), money("0.5"), version("cost-one")),
            SizingCosts(money("1"), money("0.5"), money("0.5"), version("cost-two")),
        ),
        minimum_risk_reward=Decimal("1"),
    )
    result = calculate_take_profit_assessment(request)
    assert result.outcome is RiskCheckOutcome.PASSED
    assert tuple(item.expected_profit for item in result.targets) == (
        money("8"),
        money("18"),
    )
    assert result.expected_profit == money("26")
    assert version("cost-one") in result.assumptions
    assert version("cost-two") in result.assumptions


def test_take_profit_uses_exact_threshold_under_independent_decimal_context() -> None:
    stop_request = stop_assessment_request(
        costs=SizingCosts(
            money("0"),
            money("0"),
            money("0"),
            version("zero-stop-cost"),
        ),
        adverse_gap_displacement=Decimal("1"),
    )
    request = take_profit_assessment_request(
        stop_request=stop_request,
        targets=(replace(unpriced_target(), price=price("122")),),
        target_costs=(
            SizingCosts(
                money("0"),
                money("0"),
                money("0"),
                version("zero-target-cost"),
            ),
        ),
        minimum_risk_reward=Decimal("2"),
    )
    request = replace(
        request,
        sizing_result=replace(request.sizing_result, maximum_loss=money("20")),
    )
    with localcontext(Context(prec=3, rounding=ROUND_DOWN)):
        result = calculate_take_profit_assessment(request)
    assert result.outcome is RiskCheckOutcome.PASSED
    assert result.expected_profit == money("44")
    assert result.risk_reward_ratio == Decimal("2")
    rejected = calculate_take_profit_assessment(
        replace(request, minimum_risk_reward=Decimal("2.01"))
    )
    assert rejected.outcome is RiskCheckOutcome.FAILED
    assert "MINIMUM_RISK_REWARD_NOT_MET" in rejected.reason_codes


def test_take_profit_hard_failure_dominates_upstream_warning() -> None:
    request = take_profit_assessment_request()
    request = replace(
        request,
        sizing_result=replace(
            request.sizing_result,
            outcome=RiskCheckOutcome.WARNING,
            reason_codes=("REQUESTED_TARGET_REDUCED",),
        ),
        stop_loss_request=replace(
            request.stop_loss_request,
            minimum_stop_distance=Decimal("11"),
        ),
    )
    result = calculate_take_profit_assessment(request)
    assert result.outcome is RiskCheckOutcome.FAILED
    assert "STOP_ASSESSMENT_FAILED" in result.reason_codes
    assert result.strategy_consistency is RiskCheckOutcome.FAILED


def test_take_profit_propagates_current_sizing_warning() -> None:
    request = take_profit_assessment_request()
    request = replace(
        request,
        sizing_result=replace(
            request.sizing_result,
            outcome=RiskCheckOutcome.WARNING,
            reason_codes=("REQUESTED_TARGET_REDUCED",),
        ),
    )
    result = calculate_take_profit_assessment(request)
    assert result.outcome is RiskCheckOutcome.WARNING
    assert "REQUESTED_TARGET_REDUCED" in result.reason_codes
    assert result.expected_profit == money("36")


def test_take_profit_schema_two_lineage_is_supported_without_down_conversion() -> None:
    request = take_profit_assessment_request()
    ctx = replace(
        request.context,
        signal=replace(request.context.signal, schema_version="2"),
        validation=replace(request.context.validation, schema_version="2"),
        strategy_version=replace(request.context.strategy_version, schema_version="2"),
    )
    stop_request = request.stop_loss_request
    assert stop_request.structural_evidence is not None
    assert stop_request.volatility_evidence is not None
    assert stop_request.liquidation_evidence is not None
    stop_request = replace(
        stop_request,
        context=ctx,
        structural_evidence=replace(
            stop_request.structural_evidence,
            context=ctx,
            strategy_version=ctx.strategy_version,
        ),
        volatility_evidence=replace(stop_request.volatility_evidence, context=ctx),
        liquidation_evidence=replace(stop_request.liquidation_evidence, context=ctx),
    )
    request = replace(
        request,
        context=ctx,
        stop_loss_request=stop_request,
        sizing_result=replace(request.sizing_result, context=ctx),
        target_bounds=tuple(
            replace(
                bound,
                context=ctx,
                strategy_version=ctx.strategy_version,
            )
            for bound in request.target_bounds
        ),
    )
    result = calculate_take_profit_assessment(request)
    assert result.outcome is RiskCheckOutcome.PASSED
    assert result.context.strategy_version.schema_version == "2"
    assert result.context.signal.schema_version == "2"


def test_take_profit_fails_closed_for_target_tick_bound_and_partial_step() -> None:
    request = take_profit_assessment_request()
    unticked = replace(request.targets[0], price=price("120.005"))
    result = calculate_take_profit_assessment(replace(request, targets=(unticked,)))
    assert result.outcome is RiskCheckOutcome.FAILED
    assert "TARGET_PRICE_TICK_MISMATCH" in result.reason_codes

    outside = replace(request.targets[0], price=price("135"))
    result = calculate_take_profit_assessment(replace(request, targets=(outside,)))
    assert result.outcome is RiskCheckOutcome.FAILED
    assert "TARGET_OUTSIDE_STRATEGY_BOUND" in result.reason_codes
    assert result.invalidation_consistency is RiskCheckOutcome.FAILED

    split = take_profit_assessment_request(
        targets=(
            replace(
                unpriced_target(sequence=1, allocation="0.333"), price=price("110")
            ),
            replace(
                unpriced_target(sequence=2, allocation="0.667"), price=price("120")
            ),
        ),
        minimum_risk_reward=Decimal("0.1"),
    )
    result = calculate_take_profit_assessment(split)
    assert result.outcome is RiskCheckOutcome.FAILED
    assert "TARGET_QUANTITY_STEP_MISMATCH" in result.reason_codes

    non_progressive = take_profit_assessment_request(
        targets=(
            replace(unpriced_target(sequence=1, allocation="0.5"), price=price("120")),
            replace(unpriced_target(sequence=2, allocation="0.5"), price=price("115")),
        ),
        minimum_risk_reward=Decimal("0.1"),
    )
    result = calculate_take_profit_assessment(non_progressive)
    assert result.outcome is RiskCheckOutcome.FAILED
    assert "TARGET_PRICES_NOT_PROGRESSIVE" in result.reason_codes

    below_minimum = take_profit_assessment_request(
        targets=(
            replace(unpriced_target(sequence=1, allocation="0.05"), price=price("110")),
            replace(unpriced_target(sequence=2, allocation="0.95"), price=price("120")),
        ),
        minimum_risk_reward=Decimal("0.1"),
    )
    stop_request = replace(below_minimum.stop_loss_request, quantity=Decimal("1"))
    sizing_result = replace(
        below_minimum.sizing_result,
        recommended_quantity=Decimal("1"),
        maximum_loss=money("12"),
    )
    result = calculate_take_profit_assessment(
        replace(
            below_minimum,
            stop_loss_request=stop_request,
            sizing_result=sizing_result,
        )
    )
    assert result.outcome is RiskCheckOutcome.FAILED
    assert "TARGET_QUANTITY_OUT_OF_BOUNDS" in result.reason_codes


def test_take_profit_rejects_bad_shapes_and_unrepresentable_arithmetic() -> None:
    request = take_profit_assessment_request()
    with pytest.raises(RiskContractError, match="ascending sequences"):
        replace(
            request,
            targets=(
                replace(request.targets[0], sequence=2),
                replace(unpriced_target(sequence=1, allocation="0.5")),
            ),
        )
    with pytest.raises(RiskContractError, match="allocations must sum exactly"):
        replace(
            request,
            targets=(replace(request.targets[0], allocation=ratio("0.9")),),
        )

    huge = price("12345678901234567890123456789012345")
    huge_request = replace(
        request,
        targets=(replace(request.targets[0], price=huge),),
        target_bounds=(
            replace(
                request.target_bounds[0],
                upper_price=huge,
            ),
        ),
    )
    with pytest.raises(RiskContractError, match="precision 34"):
        calculate_take_profit_assessment(huge_request)


@pytest.mark.parametrize("amount", ["0", "999"])
def test_take_profit_rejects_caller_populated_target_profit(amount: str) -> None:
    request = take_profit_assessment_request()
    with pytest.raises(RiskContractError, match="expected_profit must be unset"):
        replace(
            request,
            targets=(replace(request.targets[0], expected_profit=money(amount)),),
        )


def test_take_profit_reports_conservative_nonterminating_ratio() -> None:
    request = take_profit_assessment_request()
    with localcontext(Context(prec=80)):
        exact_ratio = Decimal("36") / Decimal("24.5")
    with localcontext(Context(prec=2, rounding=ROUND_UP)) as caller:
        caller.traps[Inexact] = True
        result = calculate_take_profit_assessment(request)
    assert result.outcome is RiskCheckOutcome.PASSED
    assert result.risk_reward_ratio == Decimal("1.469387755102040816326530612244897")
    assert result.risk_reward_ratio <= exact_ratio


@pytest.mark.parametrize(
    ("updates", "reason"),
    [
        ({"recommended_notional": money("201")}, "SIZING_NOTIONAL_MISMATCH"),
        ({"recommended_margin": money("41")}, "SIZING_MARGIN_MISMATCH"),
        (
            {"recommended_notional": MoneyValue(Decimal("200"), "OTHER")},
            "SIZING_CURRENCY_MISMATCH",
        ),
        (
            {"recommended_margin": MoneyValue(Decimal("40"), "OTHER")},
            "SIZING_CURRENCY_MISMATCH",
        ),
        (
            {"maximum_loss": MoneyValue(Decimal("24"), "OTHER")},
            "SIZING_CURRENCY_MISMATCH",
        ),
        (
            {"requested_risk": MoneyValue(Decimal("100"), "OTHER")},
            "SIZING_CURRENCY_MISMATCH",
        ),
        (
            {"requested_notional": MoneyValue(Decimal("200"), "OTHER")},
            "SIZING_CURRENCY_MISMATCH",
        ),
        ({"minimum_quantity": Decimal("0.2")}, "SIZING_BOUNDS_MISMATCH"),
        ({"maximum_quantity": Decimal("90")}, "SIZING_BOUNDS_MISMATCH"),
        ({"quantity_step": Decimal("0.2")}, "SIZING_BOUNDS_MISMATCH"),
        ({"requested_risk": money("23")}, "SIZING_RISK_BUDGET_EXCEEDED"),
    ],
)
@pytest.mark.parametrize("warning", [False, True])
def test_take_profit_rejects_inconsistent_sizing_outputs(
    updates: dict[str, object], reason: str, warning: bool
) -> None:
    request = take_profit_assessment_request()
    sizing = replace(
        request.sizing_result,
        **updates,
        outcome=RiskCheckOutcome.WARNING if warning else RiskCheckOutcome.PASSED,
        reason_codes=("REQUESTED_TARGET_REDUCED",) if warning else (),
    )
    result = calculate_take_profit_assessment(replace(request, sizing_result=sizing))
    assert result.outcome is RiskCheckOutcome.FAILED
    assert reason in result.reason_codes


@pytest.mark.parametrize(
    "field",
    [
        "recommended_notional",
        "recommended_margin",
        "minimum_quantity",
        "maximum_quantity",
        "quantity_step",
    ],
)
def test_take_profit_warning_cannot_hide_missing_sizing_outputs(field: str) -> None:
    request = take_profit_assessment_request()
    sizing = replace(
        request.sizing_result,
        **{field: None},
        outcome=RiskCheckOutcome.WARNING,
        reason_codes=("REQUESTED_TARGET_REDUCED",),
    )
    result = calculate_take_profit_assessment(replace(request, sizing_result=sizing))
    assert result.outcome is RiskCheckOutcome.INSUFFICIENT_DATA
    assert result.expected_profit is None
    assert result.risk_reward_ratio is None


def test_take_profit_binds_all_inputs_and_uses_earliest_expiry() -> None:
    request = take_profit_assessment_request()
    result = calculate_take_profit_assessment(request)
    changed = replace(
        request,
        target_costs=(
            replace(
                request.target_costs[0],
                version=version("different-cost-version"),
            ),
        ),
        target_bounds=(replace(request.target_bounds[0], valid_until=T[8]),),
    )
    changed_result = calculate_take_profit_assessment(changed)
    assert changed_result.content_sha256 != result.content_sha256
    assert changed_result.valid_until == T[8]


def test_take_profit_missing_lineage_is_insufficient_but_hard_mismatch_fails() -> None:
    request = take_profit_assessment_request()
    stale = replace(
        request,
        target_bounds=(replace(request.target_bounds[0], valid_until=T[3]),),
    )
    result = calculate_take_profit_assessment(stale)
    assert result.outcome is RiskCheckOutcome.INSUFFICIENT_DATA
    assert result.valid_until == T[4]
    assert result.expected_profit is None

    mismatched = replace(
        request,
        target_bounds=(
            replace(
                request.target_bounds[0],
                strategy_invalidation=ref("C-023"),
            ),
        ),
    )
    result = calculate_take_profit_assessment(mismatched)
    assert result.outcome is RiskCheckOutcome.FAILED
    assert "TARGET_BOUND_INVALIDATION_MISMATCH" in result.reason_codes
    assert result.invalidation_consistency is RiskCheckOutcome.FAILED


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


def test_policy_limit_rejects_malformed_nonfinite_and_unknown_values() -> None:
    with pytest.raises(RiskContractError, match="required identity"):
        RiskLimitScope(RiskLimitHierarchy.ACCOUNT, RiskPolicyMode.RESEARCH)
    with pytest.raises(RiskContractError, match="required identity"):
        RiskLimitScope(
            RiskLimitHierarchy.STRATEGY,
            RiskPolicyMode.RESEARCH,
            account_id=uuid4(),
            strategy_id="synthetic-strategy",
        )
    with pytest.raises(RiskContractError, match="RiskLimitHierarchy"):
        RiskLimitScope("SYSTEM", RiskPolicyMode.RESEARCH)  # type: ignore[arg-type]
    with pytest.raises(RiskContractError, match="RiskPolicyMode"):
        RiskLimitScope(
            RiskLimitHierarchy.SYSTEM,
            "UNKNOWN",  # type: ignore[arg-type]
        )
    with pytest.raises(RiskContractError, match="RiskLimitDirection"):
        RiskLimitDefinition(
            "synthetic",
            RiskLimitHierarchy.SYSTEM,
            "daily-loss",
            "LESS_THAN_OR_EQUAL",  # type: ignore[arg-type]
            Decimal("1"),
            "SYNTHETIC-USD",
            RiskLimitSeverity.HARD,
            RiskLimitScope(RiskLimitHierarchy.SYSTEM, RiskPolicyMode.RESEARCH),
            True,
        )
    for value in (Decimal("NaN"), Decimal("Infinity"), Decimal("-Infinity")):
        with pytest.raises(RiskContractError, match="finite Decimal"):
            policy_limit(threshold=str(value))


def test_policy_requires_nonempty_typed_unique_limit_definitions() -> None:
    with pytest.raises(RiskContractError, match="must not be empty"):
        risk_policy(())
    first = policy_limit(limit_id="same")
    second = policy_limit(metric="weekly-loss", limit_id="same")
    with pytest.raises(RiskContractError, match="must not contain duplicates"):
        risk_policy((first, second))
    with pytest.raises(RiskContractError, match="enabled"):
        policy_limit(enabled=False)


def test_policy_digest_and_exact_version_references_bind_content() -> None:
    hard_limit = policy_limit()
    value = risk_policy((hard_limit,))
    assert value.policy_version.content_sha256 == value.content_sha256
    assert value.configuration_version.content_sha256 == value.content_sha256
    with pytest.raises(RiskContractError, match="digest mismatch"):
        replace(value, content_sha256="b" * 64)
    changed = replace(hard_limit, threshold=Decimal("101"))
    with pytest.raises(RiskContractError, match="digest mismatch"):
        replace(value, limits=(changed,))
    with pytest.raises(RiskContractError, match="digest mismatch"):
        replace(value, policy_version=version("different-policy"))
    for field_name in ("policy_version", "configuration_version"):
        with pytest.raises(RiskContractError, match="VersionReference digest mismatch"):
            replace(
                value,
                **{
                    field_name: replace(
                        getattr(value, field_name), content_sha256="b" * 64
                    )
                },
            )


def test_policy_rejects_same_level_conflicts_and_ambiguous_scopes() -> None:
    account_id = uuid4()
    portfolio_id = uuid4()
    strategy_id = "synthetic-strategy"
    broad = policy_limit(
        hierarchy=RiskLimitHierarchy.STRATEGY,
        account_id=account_id,
        portfolio_id=portfolio_id,
        strategy_id=strategy_id,
        limit_id="strategy-broad",
    )
    portfolio_specific = policy_limit(
        hierarchy=RiskLimitHierarchy.STRATEGY,
        account_id=account_id,
        portfolio_id=portfolio_id,
        strategy_id=strategy_id,
        venue="synthetic-venue",
        threshold="90",
        limit_id="strategy-specific",
    )
    with pytest.raises(RiskContractError, match="same-level"):
        risk_policy((broad, portfolio_specific))

    overlapping_duplicate = replace(broad, limit_id="strategy-conflict")
    with pytest.raises(RiskContractError, match="same-level"):
        risk_policy((broad, overlapping_duplicate))

    disjoint = policy_limit(
        hierarchy=RiskLimitHierarchy.STRATEGY,
        account_id=account_id,
        portfolio_id=portfolio_id,
        strategy_id="another-strategy",
        limit_id="different-strategy",
    )
    assert len(risk_policy((broad, disjoint)).limits) == 2
    other_account = policy_limit(
        hierarchy=RiskLimitHierarchy.ACCOUNT,
        account_id=uuid4(),
        limit_id="different-account",
    )
    assert len(risk_policy((policy_limit(), other_account)).limits) == 2


def test_policy_rejects_ambiguous_cross_level_scope_overlap() -> None:
    account_id = uuid4()
    portfolio_id = uuid4()
    parent = policy_limit(
        hierarchy=RiskLimitHierarchy.PORTFOLIO,
        account_id=account_id,
        portfolio_id=portfolio_id,
        venue="synthetic-venue",
        threshold="100",
        limit_id="portfolio-hard-limit",
    )
    child = policy_limit(
        hierarchy=RiskLimitHierarchy.STRATEGY,
        account_id=account_id,
        portfolio_id=portfolio_id,
        strategy_id="synthetic-strategy",
        threshold="101",
        limit_id="strategy-ambiguous-limit",
    )
    with pytest.raises(RiskContractError, match="ambiguous or incomparable scopes"):
        risk_policy((parent, child))


def test_hard_parent_is_inherited_and_lower_scopes_may_only_tighten() -> None:
    account_id = uuid4()
    parent = policy_limit()
    account_tighter = policy_limit(
        hierarchy=RiskLimitHierarchy.ACCOUNT,
        account_id=account_id,
        threshold="90",
        limit_id="account-tighter",
    )
    account_equal = replace(account_tighter, threshold=Decimal("100"))
    assert len(risk_policy((parent, account_tighter)).limits) == 2
    assert len(risk_policy((parent, account_equal)).limits) == 2
    assert len(risk_policy((parent,)).limits) == 1

    weaker = replace(account_tighter, threshold=Decimal("101"))
    with pytest.raises(RiskContractError, match="weaken"):
        risk_policy((parent, weaker))
    softened = replace(
        account_tighter,
        severity=RiskLimitSeverity.SOFT,
    )
    with pytest.raises(RiskContractError, match="soften"):
        risk_policy((parent, softened))
    non_comparable = replace(
        account_tighter,
        unit="SYNTHETIC-PERCENT",
    )
    with pytest.raises(RiskContractError, match="non-comparable"):
        risk_policy((parent, non_comparable))
    with pytest.raises(RiskContractError, match="enabled"):
        replace(account_tighter, enabled=False)


def test_hard_parent_greater_equal_direction_can_only_tighten_upward() -> None:
    parent = policy_limit(
        metric="minimum-buffer",
        direction=RiskLimitDirection.GREATER_THAN_OR_EQUAL,
        threshold="10",
        unit="SYNTHETIC-USD",
    )
    child = policy_limit(
        hierarchy=RiskLimitHierarchy.ACCOUNT,
        account_id=uuid4(),
        metric="minimum-buffer",
        direction=RiskLimitDirection.GREATER_THAN_OR_EQUAL,
        threshold="11",
        unit="SYNTHETIC-USD",
        limit_id="account-buffer",
    )
    assert len(risk_policy((parent, child)).limits) == 2
    with pytest.raises(RiskContractError, match="weaken"):
        risk_policy((parent, replace(child, threshold=Decimal("9"))))
    with pytest.raises(RiskContractError, match="non-comparable"):
        risk_policy(
            (
                parent,
                replace(child, direction=RiskLimitDirection.LESS_THAN_OR_EQUAL),
            )
        )


def test_soft_warning_verdict_semantics_remain_non_enforcing_for_review() -> None:
    warning_assessment = assessment(
        outcome=RiskCheckOutcome.WARNING,
        warnings=("Synthetic soft limit warning.",),
        reason_codes=("SOFT_LIMIT_WARNING",),
        limits=(
            limit(
                severity=RiskLimitSeverity.SOFT,
                outcome=RiskCheckOutcome.WARNING,
            ),
        ),
    )
    value = decision(
        warning_assessment,
        uuid4(),
        verdict=RiskVerdict.PASS_WITH_WARNING,
        soft_warning_ids=("synthetic-soft-limit",),
        reason_codes=("SOFT_LIMIT_WARNING",),
    )
    assert value.verdict is RiskVerdict.PASS_WITH_WARNING
    assert value.execution_authorized is False


def exposure_input(
    account_id: UUID,
    amount: str,
    *,
    side: PositionSide = PositionSide.LONG,
    currency: str = USD,
    asset: str = "SYNTHETIC-BTC",
    instrument_id: str = "SYNTHETIC-BTC-USD",
    venue: str = "synthetic-venue",
    **overrides: object,
) -> PositionExposureInput:
    position_value = position(
        account_id,
        side=side,
        asset=asset,
        instrument_id=instrument_id,
        entry_price=PriceValue(Decimal("100"), currency),
        mark_price=PriceValue(Decimal("101"), currency),
        liquidation_price=PriceValue(Decimal("50"), currency),
        stop_loss=PriceValue(Decimal("90"), currency),
        notional=MoneyValue(Decimal(amount), currency),
        margin_used=MoneyValue(Decimal("0"), currency),
        unrealized_pnl=MoneyValue(Decimal("0"), currency),
        take_profit_targets=(),
        **overrides,
    )
    return PositionExposureInput(position_value, venue)


def return_series(
    instrument_id: str,
    values: tuple[str, ...],
    *,
    timestamps: tuple[datetime, ...] | None = None,
    source_id: str = "synthetic-returns",
    source_version: VersionReference | None = None,
) -> InstrumentReturnSeries:
    sample_times = timestamps or T[: len(values)]
    observations = tuple(
        ReturnObservation(timestamp, Decimal(value))
        for timestamp, value in zip(sample_times, values, strict=True)
    )
    series_version = source_version or version("synthetic-return-source")
    digest = canonical_sha256(
        {
            "instrument_id": instrument_id,
            "source_id": source_id,
            "source_version": series_version,
            "observations": observations,
        }
    )
    return InstrumentReturnSeries(
        instrument_id,
        source_id,
        series_version,
        observations,
        digest,
    )


def test_exposure_aggregation_preserves_gross_offsets_and_dimensions() -> None:
    account_value = account()
    long = exposure_input(
        account_value.account_id, "150", instrument_id="SYNTHETIC-PAIR"
    )
    short = exposure_input(
        account_value.account_id,
        "70",
        side=PositionSide.SHORT,
        instrument_id="SYNTHETIC-PAIR",
        venue="synthetic-venue-2",
    )
    result = aggregate_portfolio_exposure(
        account_value, (long, short), evaluated_at=T[14]
    )
    currency = next(
        item
        for item in result.breakdowns
        if item.dimension == "currency" and item.key == USD
    )
    assert (
        currency.gross_long,
        currency.gross_short,
        currency.net,
        currency.gross,
    ) == (Decimal("150"), Decimal("70"), Decimal("80"), Decimal("220"))
    instrument = next(
        item
        for item in result.breakdowns
        if item.dimension == "instrument" and item.key == "SYNTHETIC-PAIR"
    )
    assert instrument.gross == Decimal("220")
    assert instrument.net == Decimal("80")
    assert (
        len([item for item in result.breakdowns if item.dimension == "direction"]) == 2
    )
    assert (
        result.input_digest
        == aggregate_portfolio_exposure(
            account_value, (short, long), evaluated_at=T[14]
        ).input_digest
    )
    assert result.position_snapshot_ids == tuple(
        item.position.snapshot_id
        for item in sorted(
            (long, short), key=lambda item: item.position.position_id.hex
        )
    )


def test_exposure_aggregation_groups_currency_asset_instrument_venue_direction() -> (
    None
):
    account_value = account()
    inputs = (
        exposure_input(
            account_value.account_id,
            "60",
            asset="SYNTHETIC-A",
            instrument_id="SYNTHETIC-A-USD",
            venue="venue-a",
        ),
        exposure_input(
            account_value.account_id,
            "40",
            asset="SYNTHETIC-A",
            instrument_id="SYNTHETIC-B-USD",
            venue="venue-a",
        ),
        exposure_input(
            account_value.account_id,
            "50",
            currency="SYNTHETIC-EUR",
            asset="SYNTHETIC-A",
            instrument_id="SYNTHETIC-B-EUR",
            venue="venue-b",
        ),
    )
    result = aggregate_portfolio_exposure(account_value, inputs, T[14])
    asset_a = next(
        item
        for item in result.breakdowns
        if item.dimension == "asset"
        and item.key == "SYNTHETIC-A"
        and item.currency == USD
    )
    assert asset_a.currency == USD and asset_a.gross == Decimal("100")
    asset_a_foreign = next(
        item
        for item in result.breakdowns
        if item.dimension == "asset"
        and item.key == "SYNTHETIC-A"
        and item.currency == "SYNTHETIC-EUR"
    )
    assert asset_a_foreign.gross == Decimal("50")
    venue_a = next(
        item
        for item in result.breakdowns
        if item.dimension == "venue" and item.key == "venue-a"
    )
    assert venue_a.gross == Decimal("100")
    assert {
        item.currency for item in result.breakdowns if item.dimension == "currency"
    } == {USD, "SYNTHETIC-EUR"}
    foreign = next(
        item for item in result.concentrations if item.currency == "SYNTHETIC-EUR"
    )
    assert foreign.state is ExposureConcentrationState.UNKNOWN
    assert foreign.gross_to_equity is None
    assert foreign.reason == "FOREIGN_CURRENCY_NO_FX"


def test_exposure_same_currency_concentration_is_gross_and_not_clamped() -> None:
    account_value = account()
    result = aggregate_portfolio_exposure(
        account_value,
        (
            exposure_input(account_value.account_id, "7000"),
            exposure_input(
                account_value.account_id,
                "5000",
                side=PositionSide.SHORT,
            ),
        ),
        T[14],
    )
    concentration = result.concentrations[0]
    assert concentration.state is ExposureConcentrationState.AVAILABLE
    assert concentration.gross == Decimal("12000")
    assert concentration.gross_to_equity == Decimal("1.2")
    asset_concentration = result.asset_concentrations[0]
    assert asset_concentration.asset == "SYNTHETIC-BTC"
    assert asset_concentration.gross == Decimal("12000")
    assert asset_concentration.gross_to_equity == Decimal("1.2")


def test_exposure_asset_concentration_is_individual_and_currency_aware() -> None:
    account_value = account()
    result = aggregate_portfolio_exposure(
        account_value,
        (
            exposure_input(account_value.account_id, "6000", asset="SYNTHETIC-A"),
            exposure_input(
                account_value.account_id,
                "4000",
                asset="SYNTHETIC-B",
                instrument_id="SYNTHETIC-B-USD",
            ),
            exposure_input(
                account_value.account_id,
                "500",
                currency="SYNTHETIC-EUR",
                asset="SYNTHETIC-A",
                instrument_id="SYNTHETIC-A-EUR",
            ),
        ),
        T[14],
    )
    asset_a = next(
        item
        for item in result.asset_concentrations
        if item.asset == "SYNTHETIC-A" and item.currency == USD
    )
    asset_b = next(
        item
        for item in result.asset_concentrations
        if item.asset == "SYNTHETIC-B" and item.currency == USD
    )
    foreign_asset_a = next(
        item
        for item in result.asset_concentrations
        if item.asset == "SYNTHETIC-A" and item.currency == "SYNTHETIC-EUR"
    )
    assert (asset_a.gross, asset_a.gross_to_equity) == (
        Decimal("6000"),
        Decimal("0.6"),
    )
    assert (asset_b.gross, asset_b.gross_to_equity) == (
        Decimal("4000"),
        Decimal("0.4"),
    )
    assert foreign_asset_a.state is ExposureConcentrationState.UNKNOWN
    assert foreign_asset_a.gross_to_equity is None
    assert foreign_asset_a.reason == "FOREIGN_CURRENCY_NO_FX"


def test_exposure_rejects_bad_account_position_venue_and_freshness_inputs() -> None:
    account_value = account()
    valid_position = exposure_input(account_value.account_id, "10")
    with pytest.raises(RiskContractError, match="must be VALID"):
        aggregate_portfolio_exposure(
            account(state=SnapshotState.STALE, reason_codes=("STALE",)),
            (valid_position,),
            T[3],
        )
    with pytest.raises(RiskContractError, match="identity mismatch"):
        aggregate_portfolio_exposure(
            account_value, (exposure_input(uuid4(), "10"),), T[3]
        )
    with pytest.raises(RiskContractError, match="stale"):
        aggregate_portfolio_exposure(account_value, (valid_position,), T[15])
    future = exposure_input(
        account_value.account_id, "10", as_of=T[4], captured_at=T[5]
    )
    with pytest.raises(RiskContractError, match="future"):
        aggregate_portfolio_exposure(account_value, (future,), T[3])
    with pytest.raises(RiskContractError, match="must not be empty"):
        aggregate_portfolio_exposure(account_value, (), T[3])
    with pytest.raises(RiskContractError, match="must not be blank"):
        PositionExposureInput(valid_position.position, " ")
    with pytest.raises(RiskContractError, match="timezone-aware"):
        aggregate_portfolio_exposure(
            account_value,
            (valid_position,),
            datetime(2026, 1, 4),
        )

    account_future = account(as_of=T[4], captured_at=T[5])
    with pytest.raises(
        RiskContractError, match="account snapshot cannot be from the future"
    ):
        aggregate_portfolio_exposure(account_future, (valid_position,), T[3])
    # Expiry equality is accepted by both account and position checks.
    accepted = replace(valid_position.position, valid_until=T[15])
    result = aggregate_portfolio_exposure(
        account_value, (PositionExposureInput(accepted, "synthetic-venue"),), T[15]
    )
    assert result.evaluated_at == T[15]


def test_exposure_rejects_invalid_unpriced_and_duplicate_position_inputs() -> None:
    account_value = account()
    base = exposure_input(account_value.account_id, "10")
    invalid = replace(
        base.position,
        state=SnapshotState.INCOMPLETE,
        reason_codes=("NOT_PRICED",),
        notional=None,
    )
    with pytest.raises(RiskContractError, match="must be VALID"):
        aggregate_portfolio_exposure(
            account_value, (PositionExposureInput(invalid, "venue"),), T[3]
        )
    unpriced = replace(base.position)
    object.__setattr__(unpriced, "notional", None)
    with pytest.raises(RiskContractError, match="positive priced notional"):
        aggregate_portfolio_exposure(
            account_value, (PositionExposureInput(unpriced, "venue"),), T[3]
        )
    duplicate_snapshot = replace(base.position, snapshot_id=uuid4())
    with pytest.raises(RiskContractError, match="duplicate position identity"):
        aggregate_portfolio_exposure(
            account_value,
            (
                base,
                PositionExposureInput(duplicate_snapshot, "venue"),
            ),
            T[3],
        )
    with pytest.raises(RiskContractError, match="must be a tuple"):
        aggregate_portfolio_exposure(
            account_value,
            [base],
            T[3],  # type: ignore[arg-type]
        )


def test_pairwise_correlation_and_beta_are_exact_and_provenance_bound() -> None:
    benchmark = return_series("SYNTHETIC-BENCH", ("-3", "-1", "1", "3"))
    asset = return_series(
        "SYNTHETIC-ASSET",
        ("-6", "-2", "2", "6"),
        source_id="synthetic-source-asset",
        source_version=version("asset-return-source"),
    )
    inverse = return_series("SYNTHETIC-INVERSE", ("3", "1", "-1", "-3"))
    result = pairwise_correlation(
        (asset, inverse, benchmark),
        window_start=T[0],
        window_end=T[3],
        min_observations=3,
        benchmark_instrument_id=benchmark.instrument_id,
    )
    assert isinstance(result, PairwiseCorrelationResult)
    assert result.correlations[0].instrument_left == "SYNTHETIC-ASSET"
    assert result.correlations[0].instrument_right == "SYNTHETIC-BENCH"
    assert result.correlations[0].estimate.value == Decimal("1")
    assert result.correlations[0].estimate.sample_count == 4
    inverse_correlation = next(
        item
        for item in result.correlations
        if item.instrument_left == "SYNTHETIC-BENCH"
        and item.instrument_right == "SYNTHETIC-INVERSE"
    )
    assert inverse_correlation.estimate.value == Decimal("-1")
    beta = next(
        item for item in result.betas if item.instrument_id == asset.instrument_id
    )
    assert beta.estimate.value == Decimal("2")
    assert beta.estimate.sample_timestamps == T[:4]
    assert result.window_start == T[0] and result.window_end == T[3]
    provenance = next(
        item
        for item in result.series_provenance
        if item.instrument_id == asset.instrument_id
    )
    assert provenance.source_id == "synthetic-source-asset"
    assert provenance.source_version == asset.source_version
    assert provenance.content_sha256 == asset.content_sha256
    assert len(result.input_digest) == 64
    repeated = pairwise_correlation(
        (benchmark, inverse, asset),
        window_start=T[0],
        window_end=T[3],
        min_observations=3,
        benchmark_instrument_id=benchmark.instrument_id,
    )
    assert repeated == result


@pytest.mark.parametrize("opposite", [False, True])
def test_pairwise_correlation_bounds_decimal_rounding(opposite: bool) -> None:
    values = (
        "-0.648857566271132852749344965975",
        "0.901732323717895592504053270155",
        "0.698638443136872307396148201025",
        "0.297735541716413254094506681617",
        "0.576158120893557105055281624696",
    )
    inverse_values = tuple(
        value[1:] if value.startswith("-") else f"-{value}" for value in values
    )
    result = pairwise_correlation(
        (
            return_series("A", values),
            return_series("B", inverse_values if opposite else values),
        ),
        window_start=T[0],
        window_end=T[4],
        min_observations=3,
    )
    estimate = result.correlations[0].estimate
    assert estimate.state is DescriptiveEstimateState.AVAILABLE
    assert estimate.value == Decimal("-1" if opposite else "1")


def test_pairwise_correlation_rejects_material_range_violation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import trading_platform_api.risk.contracts as risk_contracts

    monkeypatch.setattr(
        risk_contracts,
        "_moments",
        lambda pairs: (Decimal("1.01"), Decimal("1"), Decimal("1")),
    )
    with pytest.raises(RiskContractError, match="exceeds its valid range"):
        pairwise_correlation(
            (return_series("A", ("1", "2", "3")), return_series("B", ("1", "2", "3"))),
            window_start=T[0],
            window_end=T[2],
            min_observations=3,
        )


def test_pairwise_window_is_inclusive_and_alignment_uses_exact_timestamps() -> None:
    benchmark = return_series(
        "SYNTHETIC-BENCH",
        ("0", "1", "2", "3", "100"),
        timestamps=T[:5],
    )
    asset = return_series(
        "SYNTHETIC-ASSET",
        ("999", "2", "4", "6", "200"),
        timestamps=T[:5],
    )
    inclusive = pairwise_correlation(
        (benchmark, asset),
        window_start=T[1],
        window_end=T[4],
        min_observations=3,
    )
    estimate = inclusive.correlations[0].estimate
    assert estimate.sample_timestamps == T[1:5]
    assert estimate.value == Decimal("1")

    shifted_times = tuple(item + timedelta(hours=1) for item in T[:5])
    shifted = return_series(
        "SYNTHETIC-SHIFTED",
        ("0", "2", "4", "6", "8"),
        timestamps=shifted_times,
    )
    unaligned = (
        pairwise_correlation(
            (benchmark, shifted),
            window_start=T[0],
            window_end=T[4],
            min_observations=3,
        )
        .correlations[0]
        .estimate
    )
    assert unaligned.state is DescriptiveEstimateState.UNKNOWN
    assert unaligned.value is None
    assert unaligned.reason == "TIMESTAMP_MISMATCH"
    assert unaligned.sample_count == 0


@pytest.mark.parametrize(
    ("left_indexes", "right_indexes"),
    [
        ((0, 1, 2, 3), (0, 1, 2)),
        ((0, 1, 2), (0, 1, 2, 3)),
        ((0, 1, 2, 3), (0, 1, 3, 4)),
    ],
)
def test_pairwise_partial_overlap_is_unknown_without_dropping_observations(
    left_indexes: tuple[int, ...], right_indexes: tuple[int, ...]
) -> None:
    left = return_series(
        "SYNTHETIC-A",
        tuple(str(index + 1) for index in left_indexes),
        timestamps=tuple(T[index] for index in left_indexes),
    )
    right = return_series(
        "SYNTHETIC-B",
        tuple(str(2 * (index + 1)) for index in right_indexes),
        timestamps=tuple(T[index] for index in right_indexes),
    )
    # A matching third series proves that a mismatch affects only its own pairs.
    peer = return_series(
        "SYNTHETIC-C",
        tuple(str(3 * (index + 1)) for index in left_indexes),
        timestamps=tuple(item.timestamp for item in left.observations),
    )
    result = pairwise_correlation(
        (left, right, peer),
        window_start=T[0],
        window_end=T[4],
        min_observations=3,
        benchmark_instrument_id=left.instrument_id,
    )
    for pair in result.correlations:
        if right.instrument_id in (pair.instrument_left, pair.instrument_right):
            assert pair.estimate.state is DescriptiveEstimateState.UNKNOWN
            assert pair.estimate.value is None
            assert pair.estimate.reason == "TIMESTAMP_MISMATCH"
            assert pair.estimate.sample_count == 0
            assert pair.estimate.sample_timestamps == ()
        else:
            assert pair.estimate.state is DescriptiveEstimateState.AVAILABLE
            assert pair.estimate.value == Decimal("1")
    betas = {item.instrument_id: item.estimate for item in result.betas}
    assert betas[right.instrument_id].state is DescriptiveEstimateState.UNKNOWN
    assert betas[right.instrument_id].value is None
    assert betas[right.instrument_id].reason == "TIMESTAMP_MISMATCH"
    assert betas[right.instrument_id].sample_timestamps == ()
    assert betas[right.instrument_id].sample_count == 0
    assert betas[peer.instrument_id].value == Decimal("3")


def test_pairwise_timestamp_mismatch_outside_window_does_not_affect_estimates() -> None:
    left = return_series("SYNTHETIC-A", ("999", "1", "2", "3"), timestamps=T[:4])
    right = return_series("SYNTHETIC-B", ("2", "4", "6", "999"), timestamps=T[1:5])
    result = pairwise_correlation(
        (left, right),
        window_start=T[1],
        window_end=T[3],
        min_observations=3,
        benchmark_instrument_id=left.instrument_id,
    )
    assert result.correlations[0].estimate.value == Decimal("1")
    assert result.correlations[0].estimate.sample_timestamps == T[1:4]
    assert result.betas[0].estimate.value == Decimal("2")
    assert result.betas[0].estimate.sample_timestamps == T[1:4]


def test_pairwise_minimum_observations_zero_variance_and_explicit_benchmark() -> None:
    short = return_series("SYNTHETIC-SHORT", ("1", "2"))
    short_peer = return_series("SYNTHETIC-SHORT-PEER", ("2", "4"))
    insufficient = (
        pairwise_correlation(
            (short, short_peer),
            window_start=T[0],
            window_end=T[1],
            min_observations=3,
        )
        .correlations[0]
        .estimate
    )
    assert insufficient.state is DescriptiveEstimateState.UNKNOWN
    assert insufficient.reason == "INSUFFICIENT_ALIGNED_OBSERVATIONS"
    assert insufficient.sample_count == 2

    constant = return_series("SYNTHETIC-CONSTANT", ("1", "1", "1"))
    variable = return_series("SYNTHETIC-VARIABLE", ("1", "2", "3"))
    zero_variance = pairwise_correlation(
        (constant, variable),
        window_start=T[0],
        window_end=T[2],
        min_observations=3,
        benchmark_instrument_id=constant.instrument_id,
    )
    assert (
        zero_variance.correlations[0].estimate.state is DescriptiveEstimateState.UNKNOWN
    )
    assert zero_variance.correlations[0].estimate.reason == "ZERO_VARIANCE"
    assert zero_variance.betas[0].estimate.state is DescriptiveEstimateState.UNKNOWN
    assert zero_variance.betas[0].estimate.reason == "ZERO_BENCHMARK_VARIANCE"
    assert zero_variance.betas[0].estimate.value is None

    with pytest.raises(RiskContractError, match="at least three"):
        pairwise_correlation(
            (constant, variable),
            window_start=T[0],
            window_end=T[2],
            min_observations=2,
        )
    with pytest.raises(RiskContractError, match="explicit benchmark"):
        pairwise_correlation(
            (constant, variable),
            window_start=T[0],
            window_end=T[2],
            min_observations=3,
            benchmark_instrument_id="UNSUPPLIED",
        )


def test_return_series_rejects_malformed_nonfinite_duplicate_and_unbound_inputs() -> (
    None
):
    for value in (Decimal("NaN"), Decimal("Infinity"), Decimal("-Infinity")):
        with pytest.raises(RiskContractError, match="finite Decimal"):
            ReturnObservation(T[0], value)
    with pytest.raises(RiskContractError, match="timezone-aware"):
        ReturnObservation(datetime(2026, 1, 1), Decimal("0.1"))
    with pytest.raises(RiskContractError, match="strictly increasing"):
        return_series(
            "SYNTHETIC-DUPLICATE-TIME",
            ("1", "2"),
            timestamps=(T[0], T[0]),
        )
    value = return_series("SYNTHETIC-BOUND", ("1", "2", "3"))
    with pytest.raises(RiskContractError, match="digest mismatch"):
        replace(value, content_sha256="b" * 64)
    with pytest.raises(RiskContractError, match="must not contain duplicates"):
        pairwise_correlation(
            (value, value),
            window_start=T[0],
            window_end=T[2],
            min_observations=3,
        )
    with pytest.raises(RiskContractError, match="must not be after"):
        pairwise_correlation(
            (value, return_series("SYNTHETIC-OTHER", ("1", "2", "3"))),
            window_start=T[2],
            window_end=T[0],
            min_observations=3,
        )


def test_new_risk_values_are_immutable_and_do_not_change_c033_or_c075() -> None:
    account_value = account()
    result = aggregate_portfolio_exposure(
        account_value,
        (exposure_input(account_value.account_id, "100"),),
        T[3],
    )
    assert isinstance(result, PortfolioExposureAggregation)
    with pytest.raises(FrozenInstanceError):
        result.input_digest = HASH_A  # type: ignore[misc]
    assert portfolio(account_value).contract_id == "C-033"
    assert position(account_value.account_id).contract_id == "C-075"


def test_leverage_known_cap_breach_dominates_missing_rule() -> None:
    request = leverage_request(requested_leverage=Decimal("11"), margin_rule=None)
    result = calculate_leverage_assessment(request)
    assert result.outcome is RiskCheckOutcome.FAILED
    assert "REQUESTED_LEVERAGE_EXCEEDS_CAP" in result.reason_codes
    assert "MARGIN_RULE_MISSING" in result.reason_codes


def test_leverage_warning_retains_bounded_computed_evidence() -> None:
    request = leverage_request()
    request = replace(
        request,
        sizing_request=replace(
            request.sizing_request,
            method=SizingMethod.FIXED_NOTIONAL,
            requested_notional=money("2000"),
        ),
    )
    result = calculate_leverage_assessment(request)
    assert result.outcome is RiskCheckOutcome.WARNING
    assert result.proposed_margin == money("200")
    assert result.initial_margin == money("200")
    assert result.effective_leverage == Decimal("5")
    assert result.post_trade_free_margin == money("6770")


def test_leverage_missing_equity_is_insufficient_not_known_breach() -> None:
    request = leverage_request()
    account_value = replace(
        request.sizing_request.account,
        equity=None,
        state=SnapshotState.INCOMPLETE,
        reason_codes=("EQUITY_UNKNOWN",),
    )
    portfolio_value = replace(
        request.sizing_request.portfolio,
        account_snapshot=account_value,
        equity=None,
        state=SnapshotState.INCOMPLETE,
        reason_codes=("EQUITY_UNKNOWN",),
    )
    result = calculate_leverage_assessment(
        replace(
            request,
            sizing_request=replace(
                request.sizing_request, account=account_value, portfolio=portfolio_value
            ),
        )
    )
    assert result.outcome is RiskCheckOutcome.INSUFFICIENT_DATA
    assert result.proposed_margin is None


def test_leverage_rounds_reported_exposure_up_and_uses_exact_cap() -> None:
    request = leverage_request(requested_leverage=Decimal("6"))
    sizing_value = request.sizing_request
    assert sizing_value.instrument is not None
    request = replace(
        request,
        sizing_request=replace(
            sizing_value,
            instrument=replace(
                sizing_value.instrument, initial_margin_per_unit=money("17")
            ),
        ),
    )
    result = calculate_leverage_assessment(request)
    assert result.outcome is RiskCheckOutcome.PASSED
    with localcontext(Context(prec=80)):
        exact_ratio = Decimal("1000") / Decimal("170")
    assert result.effective_leverage is not None
    assert result.effective_leverage > exact_ratio
    assert result.effective_leverage == Decimal("5.882352941176470588235294117647059")
    capped = calculate_leverage_assessment(
        replace(
            request,
            requested_leverage=Decimal("5"),
            policy_maximum_leverage=Decimal("5"),
        )
    )
    assert capped.outcome is RiskCheckOutcome.FAILED
    assert "EFFECTIVE_LEVERAGE_EXCEEDS_CAP" in capped.reason_codes


def test_leverage_rejects_inexact_reserve_addition() -> None:
    request = leverage_request(additional_reserved_cost=money("1e-40"))
    with pytest.raises(RiskContractError, match="precision 34"):
        calculate_leverage_assessment(request)


def test_leverage_validity_includes_earliest_position() -> None:
    request = leverage_request()
    position_value = replace(
        request.sizing_request.portfolio.positions[0], valid_until=T[5]
    )
    portfolio_value = replace(
        request.sizing_request.portfolio, positions=(position_value,)
    )
    result = calculate_leverage_assessment(
        replace(
            request,
            sizing_request=replace(request.sizing_request, portfolio=portfolio_value),
        )
    )
    assert result.outcome is RiskCheckOutcome.PASSED
    assert result.valid_until == T[5]


@pytest.mark.parametrize(
    ("side", "liquidation_price"),
    [(PositionSide.LONG, "80"), (PositionSide.SHORT, "120")],
)
def test_liquidation_assessment_exact_long_short_thresholds(
    side: PositionSide, liquidation_price: str
) -> None:
    request = liquidation_assessment_request(
        side=side,
        liquidation_price=liquidation_price,
        threshold_overrides={
            "minimum_entry_distance_ratio": Decimal("0.2"),
            "minimum_stop_buffer": Decimal("10"),
            "normal_adverse_displacement": Decimal("20"),
            "stress_adverse_displacement": Decimal("20"),
        },
    )
    result = calculate_liquidation_assessment(request)
    assert result.outcome is RiskCheckOutcome.PASSED
    assert result.availability is LiquidationAvailability.AVAILABLE
    assert result.entry_to_liquidation == ratio("0.2", "entry-distance/entry")
    assert result.stop_to_liquidation == ratio("0.1", "stop-clearance/entry")
    assert result.valid_until == T[13]


def test_liquidation_stop_buffer_and_inside_stop_hard_failures() -> None:
    buffered = calculate_liquidation_assessment(
        liquidation_assessment_request(
            threshold_overrides={"minimum_stop_buffer": Decimal("11")}
        )
    )
    assert buffered.outcome is RiskCheckOutcome.FAILED
    assert buffered.availability is LiquidationAvailability.AVAILABLE
    assert "STOP_BUFFER_BREACHED" in buffered.reason_codes
    at_stop = calculate_liquidation_assessment(
        liquidation_assessment_request(liquidation_price="90")
    )
    assert at_stop.outcome is RiskCheckOutcome.FAILED
    assert "LIQUIDATION_AT_OR_INSIDE_STOP" in at_stop.reason_codes
    beyond_stop = calculate_liquidation_assessment(
        liquidation_assessment_request(liquidation_price="85")
    )
    assert beyond_stop.outcome is RiskCheckOutcome.PASSED


@pytest.mark.parametrize(
    ("side", "liquidation_price", "reason"),
    [
        (PositionSide.LONG, "90", "LIQUIDATION_AT_OR_INSIDE_STOP"),
        (PositionSide.LONG, "95", "LIQUIDATION_AT_OR_INSIDE_STOP"),
        (PositionSide.LONG, "110", "LIQUIDATION_ON_WRONG_SIDE_OF_ENTRY"),
        (PositionSide.SHORT, "110", "LIQUIDATION_AT_OR_INSIDE_STOP"),
        (PositionSide.SHORT, "105", "LIQUIDATION_AT_OR_INSIDE_STOP"),
        (PositionSide.SHORT, "90", "LIQUIDATION_ON_WRONG_SIDE_OF_ENTRY"),
    ],
)
def test_liquidation_invalid_side_or_stop_prices_fail_without_estimates(
    side: PositionSide,
    liquidation_price: str,
    reason: str,
) -> None:
    result = calculate_liquidation_assessment(
        liquidation_assessment_request(
            side=side,
            liquidation_price=liquidation_price,
        )
    )
    assert result.outcome is RiskCheckOutcome.FAILED
    assert result.availability is LiquidationAvailability.UNAVAILABLE
    assert result.liquidation_price is None
    assert result.entry_to_liquidation is None
    assert result.stop_to_liquidation is None
    assert reason in result.reason_codes


def test_liquidation_mode_is_not_substituted_and_cross_requires_complete_rule() -> None:
    request = liquidation_assessment_request()
    estimate = request.estimate
    assert estimate is not None
    mismatch = replace(
        request,
        estimate=replace(estimate, margin_mode=MarginMode.CROSS),
    )
    result = calculate_liquidation_assessment(mismatch)
    assert result.outcome is RiskCheckOutcome.FAILED
    assert result.availability is LiquidationAvailability.UNAVAILABLE
    assert "LIQUIDATION_MARGIN_MODE_MISMATCH" in result.reason_codes
    cross = liquidation_assessment_request(margin_mode=MarginMode.CROSS)
    assert calculate_liquidation_assessment(cross).outcome is RiskCheckOutcome.PASSED
    unavailable = calculate_liquidation_assessment(
        liquidation_assessment_request(
            margin_mode=MarginMode.CROSS,
            leverage_overrides={"margin_rule": None},
        )
    )
    assert unavailable.outcome is RiskCheckOutcome.INSUFFICIENT_DATA
    assert unavailable.liquidation_price is None


@pytest.mark.parametrize(
    ("estimate_updates", "expected_reason"),
    [
        ({"formula_model": "UNKNOWN"}, "LIQUIDATION_FORMULA_UNSUPPORTED"),
        ({"formula_model": None}, "LIQUIDATION_FORMULA_UNSUPPORTED"),
        (
            {"formula_version": None, "source_id": None, "source_version": None},
            "LIQUIDATION_FORMULA_OR_SOURCE_DATA_MISSING",
        ),
        ({"as_of": T[5]}, "LIQUIDATION_ESTIMATE_FUTURE_DATED"),
        ({"valid_until": T[3]}, "LIQUIDATION_ESTIMATE_EXPIRED"),
    ],
)
def test_liquidation_unknown_or_noncurrent_estimate_is_unavailable(
    estimate_updates: dict[str, object], expected_reason: str
) -> None:
    request = liquidation_assessment_request(estimate_overrides=estimate_updates)
    result = calculate_liquidation_assessment(request)
    assert result.outcome is RiskCheckOutcome.INSUFFICIENT_DATA
    assert result.availability is LiquidationAvailability.UNAVAILABLE
    assert result.liquidation_price is None
    assert expected_reason in result.reason_codes


def test_liquidation_basis_cost_currency_and_unknown_treatment_fail_closed() -> None:
    request = liquidation_assessment_request()
    assert request.estimate is not None
    altered_basis = replace(
        request.estimate.basis_request, requested_leverage=Decimal("4")
    )
    mismatch = replace(
        request,
        estimate=replace(request.estimate, basis_request=altered_basis),
    )
    mismatched = calculate_liquidation_assessment(mismatch)
    assert mismatched.outcome is RiskCheckOutcome.FAILED
    assert mismatched.liquidation_price is None
    wrong_currency = calculate_liquidation_assessment(
        liquidation_assessment_request(
            cost_overrides={"fee_reserve": MoneyValue(Decimal("0"), "OTHER-USD")}
        )
    )
    assert wrong_currency.outcome is RiskCheckOutcome.FAILED
    assert "LIQUIDATION_CURRENCY_MISMATCH" in wrong_currency.reason_codes
    unknown_treatment = calculate_liquidation_assessment(
        liquidation_assessment_request(
            cost_overrides={"treatment": "ADJUST_SUPPLIED_PRICE"}
        )
    )
    assert unknown_treatment.outcome is RiskCheckOutcome.INSUFFICIENT_DATA
    assert unknown_treatment.liquidation_price is None
    zero_reserves = calculate_liquidation_assessment(
        liquidation_assessment_request(
            cost_overrides={
                "fee_reserve": money("0"),
                "funding_reserve": money("0"),
            }
        )
    )
    assert zero_reserves.outcome is RiskCheckOutcome.PASSED


def test_liquidation_propagates_upstream_failure_and_warning() -> None:
    failed = calculate_liquidation_assessment(
        liquidation_assessment_request(
            leverage_overrides={"requested_leverage": Decimal("11")}
        )
    )
    assert failed.outcome is RiskCheckOutcome.FAILED
    assert failed.availability is LiquidationAvailability.UNAVAILABLE
    assert failed.liquidation_price is None
    request = liquidation_assessment_request()
    leverage_value = request.leverage_request
    warning_sizing = replace(
        leverage_value.sizing_request,
        method=SizingMethod.FIXED_NOTIONAL,
        requested_notional=money("2000"),
    )
    warned_leverage = replace(leverage_value, sizing_request=warning_sizing)
    assert (
        calculate_leverage_assessment(warned_leverage).outcome
        is RiskCheckOutcome.WARNING
    )
    warned = liquidation_assessment_request(
        leverage_overrides={"sizing_request": warning_sizing}
    )
    result = calculate_liquidation_assessment(warned)
    assert result.outcome is RiskCheckOutcome.WARNING
    assert result.availability is LiquidationAvailability.AVAILABLE
    assert result.liquidation_price is not None


def test_liquidation_context_schema_digest_and_expiry_binding() -> None:
    request = liquidation_assessment_request()
    context_value = request.leverage_request.sizing_request.context
    signal_v2 = replace(context_value.signal, schema_version="2")
    context_v2 = replace(
        context_value,
        signal=signal_v2,
        validation=replace(context_value.validation, schema_version="2"),
        strategy_version=replace(context_value.strategy_version, schema_version="2"),
    )
    sizing_v2 = replace(request.leverage_request.sizing_request, context=context_v2)
    leverage_v2 = replace(request.leverage_request, sizing_request=sizing_v2)
    assert request.estimate is not None
    estimate_v2 = replace(
        request.estimate,
        context=context_v2,
        basis_request=leverage_v2,
    )
    thresholds_v2 = replace(request.thresholds, context=context_v2)
    result = calculate_liquidation_assessment(
        replace(
            request,
            leverage_request=leverage_v2,
            estimate=estimate_v2,
            thresholds=thresholds_v2,
        )
    )
    assert result.outcome is RiskCheckOutcome.PASSED
    assert result.valid_until == T[13]
    same_boundary = liquidation_assessment_request(
        estimate_overrides={"valid_until": T[4]}
    )
    assert (
        calculate_liquidation_assessment(same_boundary).outcome
        is RiskCheckOutcome.PASSED
    )
    earliest = liquidation_assessment_request(threshold_overrides={"valid_until": T[6]})
    assert calculate_liquidation_assessment(earliest).valid_until == T[6]
    assert (
        calculate_liquidation_assessment(request).content_sha256
        != result.content_sha256
    )
    changed_source = liquidation_assessment_request(
        estimate_overrides={"source_id": "another-explicit-source"}
    )
    source_mismatch = calculate_liquidation_assessment(changed_source)
    assert source_mismatch.outcome is RiskCheckOutcome.FAILED
    assert "LIQUIDATION_SOURCE_IDENTITY_MISMATCH" in source_mismatch.reason_codes
    assert (
        calculate_liquidation_assessment(request).content_sha256
        != source_mismatch.content_sha256
    )
    changed_threshold = liquidation_assessment_request(
        threshold_overrides={"stress_adverse_displacement": Decimal("16")}
    )
    assert (
        calculate_liquidation_assessment(request).content_sha256
        != calculate_liquidation_assessment(changed_threshold).content_sha256
    )


def test_liquidation_reference_provenance_and_hard_failure_precedence() -> None:
    request = liquidation_assessment_request()
    sizing_value = request.leverage_request.sizing_request
    missing_digest_context = replace(
        sizing_value.context,
        account_snapshot=replace(
            sizing_value.context.account_snapshot, content_sha256=None
        ),
    )
    missing_digest_sizing = replace(sizing_value, context=missing_digest_context)
    missing_digest_leverage = replace(
        request.leverage_request, sizing_request=missing_digest_sizing
    )
    assert request.estimate is not None
    missing_digest_result = calculate_liquidation_assessment(
        replace(
            request,
            leverage_request=missing_digest_leverage,
            estimate=replace(
                request.estimate,
                context=missing_digest_context,
                basis_request=missing_digest_leverage,
            ),
            thresholds=replace(request.thresholds, context=missing_digest_context),
        )
    )
    assert missing_digest_result.outcome is RiskCheckOutcome.INSUFFICIENT_DATA
    assert (
        "SNAPSHOT_REFERENCE_PROVENANCE_INCOMPLETE" in missing_digest_result.reason_codes
    )
    hard_with_missing = calculate_liquidation_assessment(
        replace(request, estimate=None, stop_loss=price("110"))
    )
    assert hard_with_missing.outcome is RiskCheckOutcome.FAILED
    assert hard_with_missing.liquidation_price is None
    assert "LIQUIDATION_ESTIMATE_MISSING" in hard_with_missing.reason_codes
    assert "STOP_ON_WRONG_SIDE_OF_ENTRY" in hard_with_missing.reason_codes


def test_liquidation_ratio_bounds_exact_arithmetic_and_decimal_context() -> None:
    oversized = calculate_liquidation_assessment(
        liquidation_assessment_request(
            side=PositionSide.SHORT,
            liquidation_price="250",
        )
    )
    assert oversized.outcome is RiskCheckOutcome.INSUFFICIENT_DATA
    assert "DISTANCE_NOT_REPRESENTABLE" in oversized.reason_codes
    assert oversized.liquidation_price is None
    precision_request = liquidation_assessment_request(
        threshold_overrides={
            "minimum_entry_distance_ratio": Decimal(
                "0.3333333333333333333333333333333333"
            )
        }
    )
    leverage_value = precision_request.leverage_request
    precise_sizing = replace(
        leverage_value.sizing_request,
        entry=price("99"),
        stop=price("89"),
    )
    precise_leverage = replace(leverage_value, sizing_request=precise_sizing)
    precise_quantity = calculate_position_size(precise_sizing).recommended_quantity
    assert precise_quantity is not None
    assert precision_request.estimate is not None
    precision_request = replace(
        precision_request,
        leverage_request=precise_leverage,
        stop_loss=price("89"),
        estimate=replace(
            precision_request.estimate,
            entry_price=price("99"),
            stop_loss=price("89"),
            quantity=precise_quantity,
            basis_request=precise_leverage,
        ),
    )
    with pytest.raises(RiskContractError, match="precision 34"):
        calculate_liquidation_assessment(precision_request)
    request = liquidation_assessment_request()
    with localcontext(Context(prec=3, rounding=ROUND_UP)):
        result = calculate_liquidation_assessment(request)
    assert result.outcome is RiskCheckOutcome.PASSED
    assert result.entry_to_liquidation == ratio("0.2", "entry-distance/entry")
    assert (
        calculate_liquidation_assessment(replace(request, estimate=None)).availability
        is LiquidationAvailability.UNAVAILABLE
    )


def test_c077_schema_one_constructor_and_unavailable_contract_remain_unchanged() -> (
    None
):
    expected_names = {
        "availability",
        "margin_mode",
        "entry_price",
        "stop_loss",
        "liquidation_price",
        "entry_to_liquidation",
        "stop_to_liquidation",
        "minimum_distance",
        "volatility_relationship",
        "stress_relationship",
        "formula_version",
        "exchange_constraints",
    }
    assert expected_names <= {item.name for item in fields(LiquidationAssessment)}
    assert LiquidationAssessment.__dataclass_fields__["availability"].init
    assert (
        liquidation(
            availability=LiquidationAvailability.UNAVAILABLE,
            liquidation_price=None,
            entry_to_liquidation=None,
            stop_to_liquidation=None,
            formula_version=None,
            exchange_constraints=None,
            outcome=RiskCheckOutcome.INSUFFICIENT_DATA,
            reason_codes=("LIQUIDATION_MODEL_UNAVAILABLE",),
        ).availability
        is LiquidationAvailability.UNAVAILABLE
    )


def test_liquidation_estimate_cannot_reuse_changed_cost_assumptions() -> None:
    request = liquidation_assessment_request()
    changed = replace(request, costs=replace(request.costs, fee_reserve=money("200")))
    result = calculate_liquidation_assessment(changed)
    assert result.outcome is RiskCheckOutcome.FAILED
    assert result.availability is LiquidationAvailability.UNAVAILABLE
    assert result.liquidation_price is None
    assert "LIQUIDATION_ESTIMATE_COST_BASIS_MISMATCH" in result.reason_codes


def test_liquidation_unknown_sizing_quantity_does_not_prove_mismatch() -> None:
    request = liquidation_assessment_request()
    assert request.estimate is not None
    leverage_value = replace(
        request.leverage_request,
        sizing_request=replace(
            request.leverage_request.sizing_request, instrument=None
        ),
    )
    result = calculate_liquidation_assessment(
        replace(
            request,
            leverage_request=leverage_value,
            estimate=replace(request.estimate, basis_request=leverage_value),
        )
    )
    assert result.outcome is RiskCheckOutcome.INSUFFICIENT_DATA
    assert "LIQUIDATION_ESTIMATE_BASIS_MISMATCH" not in result.reason_codes


@pytest.mark.parametrize("kind", ["quantity", "venue", "currency"])
def test_liquidation_unusable_price_cannot_report_passing_comparison(kind: str) -> None:
    request = liquidation_assessment_request()
    assert request.estimate is not None
    if kind == "quantity":
        estimate = replace(request.estimate, quantity=Decimal("11"))
    elif kind == "venue":
        estimate = replace(request.estimate, venue="different-venue")
    else:
        estimate = replace(
            request.estimate, liquidation_price=PriceValue(Decimal("80"), "OTHER-USD")
        )
    result = calculate_liquidation_assessment(replace(request, estimate=estimate))
    assert result.outcome is RiskCheckOutcome.FAILED
    assert result.availability is LiquidationAvailability.UNAVAILABLE
    assert "PASSED" not in result.volatility_relationship
    assert "PASSED" not in result.stress_relationship


def test_liquidation_missing_cost_binding_is_unavailable() -> None:
    request = liquidation_assessment_request(estimate_overrides={"cost_basis": None})
    result = calculate_liquidation_assessment(request)
    assert result.outcome is RiskCheckOutcome.INSUFFICIENT_DATA
    assert result.availability is LiquidationAvailability.UNAVAILABLE
    assert "LIQUIDATION_ESTIMATE_COST_BASIS_MISSING" in result.reason_codes
    assert "PASSED" not in result.stress_relationship


@pytest.mark.parametrize("field", ["content_sha256", "valid_until"])
def test_sizing_missing_snapshot_provenance_stays_unknown(field: str) -> None:
    request = sizing_request()
    reference = replace(request.context.account_snapshot, **{field: None})
    result = calculate_position_size(
        replace(request, context=replace(request.context, account_snapshot=reference))
    )
    assert result.outcome is RiskCheckOutcome.INSUFFICIENT_DATA
    assert result.recommended_quantity is None


@pytest.mark.parametrize(
    "field,value", [("content_sha256", "b" * 64), ("valid_until", T[14])]
)
def test_sizing_known_snapshot_provenance_conflict_still_fails(
    field: str, value: object
) -> None:
    request = sizing_request()
    reference = replace(request.context.account_snapshot, **{field: value})
    result = calculate_position_size(
        replace(request, context=replace(request.context, account_snapshot=reference))
    )
    assert result.outcome is RiskCheckOutcome.FAILED
    assert "SNAPSHOT_REFERENCE_MISMATCH" in result.reason_codes


def portfolio_impact_request(
    *,
    side: PositionSide = PositionSide.LONG,
    empty: bool = False,
    opposite: bool = False,
    pending: str = "0",
    warning: bool = False,
    schema_two: bool = False,
    equity: str = "10000",
) -> PortfolioImpactRequest:
    leverage_value = leverage_request(side=side)
    sizing_value = leverage_value.sizing_request
    account_value = replace(sizing_value.account, equity=money(equity))
    sizing_value = replace(
        sizing_value,
        account=account_value,
        portfolio=replace(
            sizing_value.portfolio, account_snapshot=account_value, equity=money(equity)
        ),
    )
    positions = () if empty else sizing_value.portfolio.positions
    if opposite:
        positions = (
            *positions,
            replace(
                positions[0],
                snapshot_id=uuid4(),
                position_id=uuid4(),
                side=PositionSide.SHORT,
            ),
        )
    gross = sum((p.notional.amount for p in positions if p.notional), Decimal(0))
    net = sum(
        (
            p.notional.amount * (1 if p.side is PositionSide.LONG else -1)
            for p in positions
            if p.notional
        ),
        Decimal(0),
    )
    portfolio_value = replace(
        sizing_value.portfolio,
        positions=positions,
        gross_exposure=MoneyValue(gross, USD),
        net_exposure=MoneyValue(net, USD),
        pending_risk=money(pending),
    )
    ctx = sizing_value.context
    if schema_two:
        ctx = replace(
            ctx,
            signal=replace(ctx.signal, schema_version="2"),
            validation=replace(ctx.validation, schema_version="2"),
            strategy_version=replace(ctx.strategy_version, schema_version="2"),
        )
    sizing_value = replace(sizing_value, portfolio=portfolio_value, context=ctx)
    if warning:
        sizing_value = replace(
            sizing_value,
            method=SizingMethod.FIXED_NOTIONAL,
            requested_notional=money("2000"),
        )
    leverage_value = replace(leverage_value, sizing_request=sizing_value)
    sized = calculate_position_size(sizing_value)
    assert sized.recommended_quantity is not None
    stop_value = stop_assessment_request(side)
    assert stop_value.structural_evidence is not None
    assert stop_value.volatility_evidence is not None
    assert stop_value.liquidation_evidence is not None
    stop_value = replace(
        stop_value,
        context=ctx,
        account=sizing_value.account,
        portfolio=portfolio_value,
        entry_price=sizing_value.entry,
        stop_loss=sizing_value.stop,
        quantity=sized.recommended_quantity,
        effective_maximum_loss=money("150"),
        instrument=sizing_value.instrument,
        costs=sizing_value.costs,
        account_source_version=sizing_value.account.source_version,
        portfolio_source_version=portfolio_value.source_version,
        structural_evidence=replace(
            stop_value.structural_evidence,
            context=ctx,
            strategy_version=ctx.strategy_version,
        ),
        volatility_evidence=replace(stop_value.volatility_evidence, context=ctx),
        liquidation_evidence=replace(stop_value.liquidation_evidence, context=ctx),
    )
    stopped = calculate_stop_loss_assessment(stop_value)
    assert stopped.outcome is RiskCheckOutcome.PASSED
    assert stopped.maximum_loss is not None
    basis = PortfolioImpactBasis(leverage_value, stop_value)
    common = dict(
        basis=basis,
        version=version("portfolio-evidence"),
        as_of=T[3],
        valid_until=T[12],
    )
    groups = tuple(
        PortfolioPositionEvidence(
            **common,
            position=p,
            venue="synthetic-venue",
            strategy_version=ctx.strategy_version,
            regime=version("synthetic-regime"),
            correlation_groups=("shared-market",),
            open_risk=money("10"),
        )
        for p in positions
    )
    proposal = PortfolioPositionEvidence(
        **common,
        position=None,
        venue="synthetic-venue",
        strategy_version=ctx.strategy_version,
        regime=version("synthetic-regime"),
        correlation_groups=("shared-market",),
        open_risk=stopped.maximum_loss,
    )
    caps = (
        PortfolioConcentrationLimit("asset", ctx.asset, Decimal("0.5")),
        PortfolioConcentrationLimit(
            "strategy", portfolio_group_key(ctx.strategy_version), Decimal("0.5")
        ),
        PortfolioConcentrationLimit(
            "regime", portfolio_group_key(proposal.regime), Decimal("0.5")
        ),
        PortfolioConcentrationLimit("correlation", "shared-market", Decimal("0.5")),
    )
    policy = PortfolioImpactPolicy(
        **{**common, "version": sizing_value.policy_version},
        configuration_version=sizing_value.configuration_version,
        maximum_gross=money("10000"),
        maximum_absolute_net=money("10000"),
        maximum_gross_leverage=Decimal("1"),
        maximum_drawdown=Decimal("0.2"),
        maximum_margin_utilization=Decimal("0.5"),
        minimum_free_margin=money("6000"),
        total_risk_budget=money("500"),
        concentration_limits=caps,
    )
    scenarios = (
        PortfolioCorrelationScenario(
            **common,
            group_id="shared-market",
            instruments=(ctx.instrument_id,),
            methodology="Caller-supplied conservative shared-market scenario, not measured correlation.",
        ),
    )
    liquidity = (
        PortfolioLiquidityEvidence(
            **common,
            venue="synthetic-venue",
            instrument_id=ctx.instrument_id,
            capacity=money("5000"),
            assumptions="Explicit synthetic gross-exposure capacity at the bound snapshot marks and entry.",
        ),
    )
    return PortfolioImpactRequest(
        UUID(int=111), T[4], basis, groups, proposal, scenarios, liquidity, policy
    )


@pytest.mark.parametrize("side", list(PositionSide))
def test_portfolio_impact_hand_calculated_opening_projection(
    side: PositionSide,
) -> None:
    request = portfolio_impact_request(side=side)
    result = calculate_portfolio_impact(request)
    assert result.outcome is RiskCheckOutcome.PASSED
    assert result.contract_id == "C-080" and result.schema_version == "1"
    before = {(x.dimension, x.key): x for x in result.before_exposures}
    after = {(x.dimension, x.key): x for x in result.after_exposures}
    assert before[("total", "gross")].notional == money("101")
    assert after[("total", "gross")].notional == money("1101")
    assert after[("total", "gross")].risk_amount == money("132.5")
    assert result.remaining_risk_budget == money("367.5")
    assert result.before_gross_leverage == Decimal("0.0101")
    assert result.after_gross_leverage == Decimal("0.1101")
    assert result.post_trade_risk.value == Decimal("0.01325")
    assert result.before_margin_utilization.value == Decimal("0.1")
    assert result.after_margin_utilization.value == Decimal("0.12")
    assert result.before_free_margin_buffer.value == Decimal("0.7")
    assert result.after_free_margin_buffer.value == Decimal("0.677")
    assert (
        result.before_drawdown
        == result.after_drawdown
        == request.basis.leverage_request.sizing_request.portfolio.drawdown
    )
    net_limit = next(x for x in result.limits if x.limit_id == "after/net")
    assert net_limit.observed == Decimal(
        "1101" if side is PositionSide.LONG else "-899"
    )
    assert result.valid_until == T[10]


def test_portfolio_opposite_positions_keep_gross_and_risk() -> None:
    result = calculate_portfolio_impact(portfolio_impact_request(opposite=True))
    assert result.outcome is RiskCheckOutcome.PASSED
    total = next(x for x in result.after_exposures if x.dimension == "total")
    assert total.notional == money("1202")
    assert total.risk_amount == money("142.5")
    assert next(x for x in result.limits if x.limit_id == "before/net").observed == 0


def test_portfolio_explicit_empty_is_not_missing_positions() -> None:
    request = portfolio_impact_request(empty=True)
    result = calculate_portfolio_impact(request)
    assert result.outcome is RiskCheckOutcome.PASSED
    assert len(result.before_exposures) == 1
    assert result.before_exposures[0].notional == money("0")
    assert result.before_exposures[0].risk_amount == money("0")
    assert result.after_gross_leverage == Decimal("0.1")
    with pytest.raises(RiskContractError, match="COVERAGE_INCOMPLETE"):
        calculate_portfolio_impact(replace(portfolio_impact_request(), positions=()))


@pytest.mark.parametrize(
    "field,value",
    [
        ("maximum_gross", money("1100")),
        ("maximum_absolute_net", money("1100")),
        ("maximum_gross_leverage", Decimal("0.11")),
        ("maximum_drawdown", Decimal("0")),
        ("maximum_margin_utilization", Decimal("0.1")),
        ("minimum_free_margin", money("6771")),
        ("total_risk_budget", money("130")),
    ],
)
def test_portfolio_each_aggregate_veto_dominates_single_trade_pass(
    field: str, value: object
) -> None:
    request = portfolio_impact_request()
    assert (
        calculate_leverage_assessment(request.basis.leverage_request).outcome
        is RiskCheckOutcome.PASSED
    )
    assert (
        calculate_stop_loss_assessment(request.basis.stop_request).outcome
        is RiskCheckOutcome.PASSED
    )
    result = calculate_portfolio_impact(
        replace(request, policy=replace(request.policy, **{field: value}))
    )
    assert result.outcome is RiskCheckOutcome.FAILED
    assert any(x.outcome is RiskCheckOutcome.FAILED for x in result.limits)
    if field == "total_risk_budget":
        assert result.remaining_risk_budget is None


@pytest.mark.parametrize("dimension", ["asset", "strategy", "regime", "correlation"])
def test_portfolio_each_concentration_cap_is_enforced(dimension: str) -> None:
    request = portfolio_impact_request()
    caps = tuple(
        replace(x, maximum=Decimal("0.11")) if x.dimension == dimension else x
        for x in request.policy.concentration_limits
    )
    result = calculate_portfolio_impact(
        replace(request, policy=replace(request.policy, concentration_limits=caps))
    )
    assert result.outcome is RiskCheckOutcome.FAILED
    assert any(
        "concentration" in x.limit_id and x.outcome is RiskCheckOutcome.FAILED
        for x in result.limits
    )


def test_portfolio_exact_boundaries_pass() -> None:
    request = portfolio_impact_request()
    policy = replace(
        request.policy,
        maximum_gross=money("1101"),
        maximum_absolute_net=money("1101"),
        maximum_gross_leverage=Decimal("0.1101"),
        maximum_drawdown=Decimal("0.01"),
        minimum_free_margin=money("6770"),
        total_risk_budget=money("132.5"),
        concentration_limits=tuple(
            replace(x, maximum=Decimal("0.1101"))
            for x in request.policy.concentration_limits
        ),
    )
    result = calculate_portfolio_impact(
        replace(
            request,
            policy=policy,
            liquidity=(replace(request.liquidity[0], capacity=money("1101")),),
        )
    )
    assert result.outcome is RiskCheckOutcome.PASSED
    assert result.remaining_risk_budget == money("0")


@pytest.mark.parametrize("missing", ["policy", "scenarios", "liquidity", "cap"])
def test_portfolio_missing_policy_or_evidence_never_passes(missing: str) -> None:
    request = portfolio_impact_request()
    if missing == "cap":
        request = replace(
            request,
            policy=replace(
                request.policy,
                concentration_limits=request.policy.concentration_limits[:-1],
            ),
        )
    else:
        request = replace(request, **{missing: None if missing == "policy" else ()})
    result = calculate_portfolio_impact(request)
    assert result.outcome is RiskCheckOutcome.INSUFFICIENT_DATA


def test_portfolio_liquidity_shortfall_is_not_hidden_by_missing_cap() -> None:
    request = portfolio_impact_request()
    result = calculate_portfolio_impact(
        replace(
            request,
            policy=None,
            liquidity=(replace(request.liquidity[0], capacity=money("1000")),),
        )
    )
    assert result.outcome is RiskCheckOutcome.FAILED
    assert "PORTFOLIO_POLICY_MISSING" in result.reason_codes


def test_portfolio_pending_risk_counts_but_unattributed_exposure_blocks_pass() -> None:
    request = portfolio_impact_request(pending="50")
    result = calculate_portfolio_impact(request)
    assert result.outcome is RiskCheckOutcome.INSUFFICIENT_DATA
    assert result.post_trade_risk.value == Decimal("0.01825")
    assert result.remaining_risk_budget == money("317.5")
    breached = calculate_portfolio_impact(
        replace(request, policy=replace(request.policy, total_risk_budget=money("150")))
    )
    assert breached.outcome is RiskCheckOutcome.FAILED


def test_portfolio_overlapping_scenarios_count_total_risk_once() -> None:
    request = portfolio_impact_request()
    proposal = replace(request.proposal, correlation_groups=("shared-market", "second"))
    positions = tuple(
        replace(x, correlation_groups=("shared-market", "second"))
        for x in request.positions
    )
    second = replace(request.scenarios[0], group_id="second")
    caps = (
        *request.policy.concentration_limits,
        PortfolioConcentrationLimit("correlation", "second", Decimal("0.5")),
    )
    result = calculate_portfolio_impact(
        replace(
            request,
            proposal=proposal,
            positions=positions,
            scenarios=(*request.scenarios, second),
            policy=replace(request.policy, concentration_limits=caps),
        )
    )
    assert result.outcome is RiskCheckOutcome.PASSED
    totals = {
        x.key: x.risk_amount
        for x in result.after_exposures
        if x.dimension in {"total", "correlation"}
    }
    assert set(totals.values()) == {money("132.5")}
    assert result.post_trade_risk.value == Decimal("0.01325")


@pytest.mark.parametrize("field", ["policy", "liquidity", "scenarios"])
def test_portfolio_evidence_expiry_and_basis_are_bound(field: str) -> None:
    request = portfolio_impact_request()
    value = request.policy if field == "policy" else getattr(request, field)[0]

    def with_value(replacement: object) -> PortfolioImpactRequest:
        return replace(
            request, **{field: replacement if field == "policy" else (replacement,)}
        )

    expired = calculate_portfolio_impact(with_value(replace(value, valid_until=T[3])))
    assert expired.outcome is RiskCheckOutcome.INSUFFICIENT_DATA
    assert expired.valid_until == T[4]
    boundary = calculate_portfolio_impact(with_value(replace(value, valid_until=T[4])))
    assert boundary.outcome is RiskCheckOutcome.PASSED and boundary.valid_until == T[4]
    foreign_basis = replace(
        request.basis,
        leverage_request=replace(
            request.basis.leverage_request, requested_leverage=Decimal("6")
        ),
    )
    mismatched = calculate_portfolio_impact(
        with_value(replace(value, basis=foreign_basis))
    )
    assert mismatched.outcome is RiskCheckOutcome.FAILED


@pytest.mark.parametrize("schema_two,warning", [(True, False), (False, True)])
def test_portfolio_preserves_schema_two_and_upstream_warnings(
    schema_two: bool, warning: bool
) -> None:
    result = calculate_portfolio_impact(
        portfolio_impact_request(schema_two=schema_two, warning=warning)
    )
    assert result.outcome is (
        RiskCheckOutcome.WARNING if warning else RiskCheckOutcome.PASSED
    )
    assert result.after_exposures and result.after_free_margin_buffer is not None


def test_portfolio_digest_and_arithmetic_are_caller_context_independent() -> None:
    request = portfolio_impact_request()
    expected = calculate_portfolio_impact(request)
    with localcontext(Context(prec=3, rounding=ROUND_DOWN)):
        observed = calculate_portfolio_impact(request)
    assert observed == expected
    edited = replace(
        request, liquidity=(replace(request.liquidity[0], capacity=money("4900")),)
    )
    assert calculate_portfolio_impact(edited).content_sha256 != expected.content_sha256
    tiny_risk = replace(request.positions[0], open_risk=money("1e-40"))
    with pytest.raises(RiskContractError, match="precision 34"):
        calculate_portfolio_impact(replace(request, positions=(tiny_risk,)))


def test_portfolio_refuses_unrepresentable_ratio_without_clamping() -> None:
    request = portfolio_impact_request()
    large = replace(request.positions[0].position, notional=money("10000"))
    sized = request.basis.leverage_request.sizing_request
    portfolio_value = replace(
        sized.portfolio,
        positions=(large,),
        gross_exposure=money("10000"),
        net_exposure=money("10000"),
    )
    sizing_value = replace(sized, portfolio=portfolio_value)
    leverage_value = replace(
        request.basis.leverage_request, sizing_request=sizing_value
    )
    stop_value = replace(request.basis.stop_request, portfolio=portfolio_value)
    basis = PortfolioImpactBasis(leverage_value, stop_value)
    request = replace(
        request,
        basis=basis,
        positions=(replace(request.positions[0], basis=basis, position=large),),
        proposal=replace(request.proposal, basis=basis),
        scenarios=tuple(replace(x, basis=basis) for x in request.scenarios),
        liquidity=tuple(replace(x, basis=basis) for x in request.liquidity),
        policy=replace(request.policy, basis=basis),
    )
    with pytest.raises(RiskContractError, match="RATIO_NOT_REPRESENTABLE"):
        calculate_portfolio_impact(request)


@pytest.mark.parametrize(
    "problem",
    ["duplicate", "foreign", "stale", "currency", "proposal-loss", "scenario-coverage"],
)
def test_portfolio_rejects_unsafe_position_or_proposal_evidence(problem: str) -> None:
    request = portfolio_impact_request()
    if problem == "duplicate":
        request = replace(
            request, positions=(request.positions[0], request.positions[0])
        )
    elif problem == "foreign":
        p = replace(request.positions[0].position, account_id=uuid4())
        request = replace(
            request, positions=(replace(request.positions[0], position=p),)
        )
    elif problem == "stale":
        request = replace(
            request, positions=(replace(request.positions[0], valid_until=T[3]),)
        )
    elif problem == "currency":
        request = replace(
            request,
            positions=(
                replace(
                    request.positions[0],
                    open_risk=MoneyValue(Decimal("10"), "OTHER-USD"),
                ),
            ),
        )
    elif problem == "proposal-loss":
        request = replace(
            request, proposal=replace(request.proposal, open_risk=money("1"))
        )
    else:
        request = replace(
            request,
            scenarios=(
                replace(request.scenarios[0], instruments=("different-instrument",)),
            ),
        )
        result = calculate_portfolio_impact(request)
        assert result.outcome is RiskCheckOutcome.FAILED
        return
    with pytest.raises(RiskContractError):
        calculate_portfolio_impact(request)


def test_portfolio_nonterminating_observations_round_conservatively() -> None:
    result = calculate_portfolio_impact(portfolio_impact_request(equity="30000"))
    assert result.outcome is RiskCheckOutcome.PASSED
    total = next(x for x in result.before_exposures if x.dimension == "total")
    with localcontext(Context(prec=80)):
        exact_exposure = Decimal("101") / Decimal("30000")
        exact_free = Decimal("6770") / Decimal("30000")
    assert total.equity_ratio.value > exact_exposure
    assert result.after_free_margin_buffer.value < exact_free


def test_portfolio_known_upstream_failure_cannot_be_upgraded() -> None:
    request = portfolio_impact_request()
    basis = replace(
        request.basis,
        stop_request=replace(
            request.basis.stop_request, effective_maximum_loss=money("1")
        ),
    )
    assert (
        calculate_stop_loss_assessment(basis.stop_request).outcome
        is RiskCheckOutcome.FAILED
    )
    request = replace(
        request,
        basis=basis,
        positions=tuple(replace(x, basis=basis) for x in request.positions),
        proposal=replace(request.proposal, basis=basis),
        scenarios=tuple(replace(x, basis=basis) for x in request.scenarios),
        liquidity=tuple(replace(x, basis=basis) for x in request.liquidity),
        policy=replace(request.policy, basis=basis),
    )
    result = calculate_portfolio_impact(request)
    assert result.outcome is RiskCheckOutcome.FAILED
    assert set(
        calculate_stop_loss_assessment(basis.stop_request).reason_codes
    ).issubset(result.reason_codes)


@pytest.mark.parametrize("mode", ["missing", "conflicting"])
def test_portfolio_incomplete_or_conflicting_upstream_provenance_never_passes(
    mode: str,
) -> None:
    request = portfolio_impact_request()
    sizing_value = request.basis.leverage_request.sizing_request
    ctx = replace(
        sizing_value.context,
        account_snapshot=replace(
            sizing_value.context.account_snapshot,
            content_sha256=None if mode == "missing" else "b" * 64,
        ),
    )
    sizing_value = replace(sizing_value, context=ctx)
    assert calculate_position_size(sizing_value).outcome is (
        RiskCheckOutcome.INSUFFICIENT_DATA
        if mode == "missing"
        else RiskCheckOutcome.FAILED
    )
    basis = replace(
        request.basis,
        leverage_request=replace(
            request.basis.leverage_request, sizing_request=sizing_value
        ),
    )
    with pytest.raises(RiskContractError):
        calculate_portfolio_impact(replace(request, basis=basis))


def test_portfolio_no_unknown_correlation_can_imply_independence() -> None:
    request = portfolio_impact_request()
    result = calculate_portfolio_impact(
        replace(request, proposal=replace(request.proposal, correlation_groups=()))
    )
    assert result.outcome is RiskCheckOutcome.INSUFFICIENT_DATA
    assert "CORRELATION_MEMBERSHIP_UNKNOWN" in result.reason_codes


def stress_assessment_request(
    *,
    paths: tuple[tuple[str, ...], ...] | None = None,
    warning: bool = False,
) -> StressAssessmentRequest:
    portfolio_value = portfolio_impact_request(warning=warning)
    common = dict(
        portfolio_request=portfolio_value,
        scenario_model_version=version("synthetic-stress-model"),
        cost_model_version=version("synthetic-stress-costs"),
        source_version=version("synthetic-stress-source"),
        as_of=T[3],
        valid_until=T[12],
    )
    kinds = ("VOLATILITY", "GAP", "LIQUIDITY", "FUNDING", "CORRELATION", "RISK_OF_RUIN")
    policy = StressAssessmentPolicy(
        **common,
        required_scenario_types=kinds,
        maximum_loss=money("1000"),
        maximum_drawdown=Decimal("0.2"),
        maximum_margin_utilization=Decimal("0.5"),
        minimum_liquidation_distance=Decimal("0.05"),
        ruin_equity_floor=money("5000"),
        maximum_ruin_frequency=Decimal("0"),
        minimum_path_count=3,
    )
    instrument = (
        portfolio_value.basis.leverage_request.sizing_request.context.instrument_id
    )
    projections = tuple(
        StressProjectionEvidence(
            **common,
            scenario_id="synthetic/" + kind,
            scenario_type=kind,
            shocks=(
                StressShock(instrument, kind, Decimal("-0.05"), "model-defined-ratio"),
            ),
            projected_loss=money("500"),
            projected_margin=money("1500"),
            minimum_liquidation_distance=Decimal("0.1"),
            included_cost_reserve=money("10"),
            cost_treatment="INCLUDED_IN_PROJECTED_LOSS",
            assumptions=(version("synthetic-scenario-assumptions"),),
        )
        for kind in kinds[:-1]
    )
    raw_paths = paths if paths is not None else (("-100", "-100"),) * 3
    evidence = RuinPathEvidence.build(
        **common,
        horizon_steps=2,
        paths=tuple(tuple(money(x) for x in path) for path in raw_paths),
        assumptions=(version("synthetic-net-pnl-path-assumptions"),),
    )
    return StressAssessmentRequest(
        UUID(int=112), T[4], portfolio_value, policy, projections, evidence
    )


def test_stress_assessment_hand_calculated_aggregates_and_no_cost_double_count() -> (
    None
):
    request = stress_assessment_request()
    result = calculate_stress_assessment(request)
    assert result.outcome is RiskCheckOutcome.PASSED
    assert result.contract_id == "C-081" and result.schema_version == "1"
    assert result.worst_loss == money("500")
    assert result.worst_drawdown == ratio(
        "0.0595", "worst-fixed-high-water-mark-drawdown"
    )
    assert result.worst_margin == money("1500")
    assert len(result.scenarios) == 6
    assert result.valid_until == T[10]
    assert "PATH_LIQUIDATION_NOT_MODELED" in result.worst_liquidation_impact
    assert not result.breached_limit_ids
    assert (
        next(
            x for x in result.scenarios if x.scenario_type == "RISK_OF_RUIN"
        ).liquidation_impact
        == "NOT_MODELED_FOR_PNL_PATHS"
    )


@pytest.mark.parametrize(
    "field,value,reason",
    [
        ("maximum_loss", money("499"), "loss"),
        ("maximum_drawdown", Decimal("0.0594"), "drawdown"),
        ("maximum_margin_utilization", Decimal("0.15"), "margin"),
        ("minimum_liquidation_distance", Decimal("0.1001"), "liquidation_distance"),
    ],
)
def test_stress_assessment_each_hard_limit_vetoes(
    field: str, value: object, reason: str
) -> None:
    request = stress_assessment_request()
    result = calculate_stress_assessment(
        replace(request, policy=replace(request.policy, **{field: value}))
    )
    assert result.outcome is RiskCheckOutcome.FAILED
    assert any(x.endswith("/" + reason) for x in result.breached_limit_ids)


def test_stress_assessment_exact_limit_boundaries_pass() -> None:
    request = stress_assessment_request()
    policy = replace(
        request.policy,
        maximum_loss=money("500"),
        maximum_drawdown=Decimal("0.0595"),
        maximum_margin_utilization=Decimal("0.2"),
        minimum_liquidation_distance=Decimal("0.1"),
    )
    assert (
        calculate_stress_assessment(replace(request, policy=policy)).outcome
        is RiskCheckOutcome.PASSED
    )


@pytest.mark.parametrize(
    "missing", ["projection", "ruin", "liquidation", "margin", "costs", "shocks"]
)
def test_stress_assessment_missing_evidence_never_becomes_zero_or_pass(
    missing: str,
) -> None:
    request = stress_assessment_request()
    if missing == "ruin":
        request = replace(request, ruin_paths=None)
    elif missing == "projection":
        request = replace(request, projections=request.projections[1:])
    else:
        names = {
            "liquidation": "minimum_liquidation_distance",
            "margin": "projected_margin",
            "costs": "included_cost_reserve",
            "shocks": "shocks",
        }
        first = replace(
            request.projections[0],
            **{names[missing]: () if missing == "shocks" else None},
        )
        request = replace(request, projections=(first, *request.projections[1:]))
    result = calculate_stress_assessment(request)
    assert result.outcome is RiskCheckOutcome.INSUFFICIENT_DATA
    assert any(
        x.outcome is RiskCheckOutcome.INSUFFICIENT_DATA for x in result.scenarios
    )
    assert result.worst_liquidation_impact is None or missing in {
        "projection",
        "ruin",
        "margin",
    }


def test_stress_assessment_known_breach_dominates_missing_liquidation() -> None:
    request = stress_assessment_request()
    first = replace(
        request.projections[0],
        projected_loss=money("2000"),
        minimum_liquidation_distance=None,
    )
    result = calculate_stress_assessment(
        replace(request, projections=(first, *request.projections[1:]))
    )
    assert result.outcome is RiskCheckOutcome.FAILED
    assert any(x.endswith("/loss") for x in result.breached_limit_ids)


@pytest.mark.parametrize("field,value", [("as_of", T[5]), ("valid_until", T[3])])
def test_stress_assessment_noncurrent_projection_is_explicitly_unavailable(
    field: str, value: datetime
) -> None:
    request = stress_assessment_request()
    first = replace(request.projections[0], **{field: value})
    result = calculate_stress_assessment(
        replace(request, projections=(first, *request.projections[1:]))
    )
    assert result.outcome is RiskCheckOutcome.INSUFFICIENT_DATA
    observed = next(x for x in result.scenarios if x.scenario_id == first.scenario_id)
    assert observed.projected_loss is None
    assert result.worst_loss is None


def test_stress_assessment_basis_and_cost_edits_cannot_reuse_source() -> None:
    request = stress_assessment_request()
    first = replace(
        request.projections[0], cost_model_version=version("different-costs")
    )
    result = calculate_stress_assessment(
        replace(request, projections=(first, *request.projections[1:]))
    )
    assert result.outcome is RiskCheckOutcome.FAILED
    assert "STRESS_MODEL_OR_COST_VERSION_MISMATCH" in result.reason_codes
    other_basis = replace(request.portfolio_request, result_id=uuid4())
    first = replace(request.projections[0], portfolio_request=other_basis)
    assert (
        calculate_stress_assessment(
            replace(request, projections=(first, *request.projections[1:]))
        ).outcome
        is RiskCheckOutcome.FAILED
    )


@pytest.mark.parametrize(
    "field", ["projected_loss", "projected_margin", "included_cost_reserve"]
)
def test_stress_assessment_foreign_currency_cannot_pass(field: str) -> None:
    request = stress_assessment_request()
    first = replace(
        request.projections[0], **{field: MoneyValue(Decimal("100"), "OTHER-USD")}
    )
    with pytest.raises(RiskContractError, match="CURRENCY_MISMATCH"):
        calculate_stress_assessment(
            replace(request, projections=(first, *request.projections[1:]))
        )


@pytest.mark.parametrize(
    "paths,expected_hits",
    [
        ((("-100", "-100"),) * 3, 0),
        ((("-5000", "100"),) * 3, 3),
        ((("-5000", "100"), ("-100", "-100"), ("0", "0")), 1),
    ],
)
def test_ruin_observation_counts_touch_and_recovery(
    paths: tuple[tuple[str, ...], ...], expected_hits: int
) -> None:
    request = stress_assessment_request(paths=paths)
    policy = replace(request.policy, maximum_ruin_frequency=Decimal("1"))
    result = calculate_ruin_observation(request.ruin_paths, policy, T[4])
    assert result.path_count == 3 and result.hit_count == expected_hits
    assert result.outcome is RiskCheckOutcome.PASSED
    if expected_hits == 1:
        assert result.hit_frequency == Decimal("0.3333333333333333333333333333333334")
    else:
        assert result.hit_frequency == Decimal(expected_hits) / Decimal(3)


def test_ruin_observation_frequency_policy_uses_counts_not_rounded_probability() -> (
    None
):
    request = stress_assessment_request(
        paths=(("-5000", "100"), ("0", "0"), ("0", "0"))
    )
    passed = calculate_ruin_observation(
        request.ruin_paths,
        replace(request.policy, maximum_ruin_frequency=Decimal("0.34")),
        T[4],
    )
    failed = calculate_ruin_observation(
        request.ruin_paths,
        replace(request.policy, maximum_ruin_frequency=Decimal("0.33")),
        T[4],
    )
    assert passed.outcome is RiskCheckOutcome.PASSED
    assert failed.outcome is RiskCheckOutcome.FAILED
    assert failed.hit_count == 1 and failed.hit_frequency is not None
    integrated = calculate_stress_assessment(
        replace(
            request,
            policy=replace(request.policy, maximum_ruin_frequency=Decimal("0.33")),
        )
    )
    assert integrated.outcome is RiskCheckOutcome.FAILED
    assert "ruin/observation/ruin_frequency" in integrated.breached_limit_ids


@pytest.mark.parametrize("paths", [(), (("0", "0"),)])
def test_ruin_observation_insufficient_samples_are_unknown(
    paths: tuple[tuple[str, ...], ...],
) -> None:
    request = stress_assessment_request(paths=paths)
    result = calculate_ruin_observation(request.ruin_paths, request.policy, T[4])
    assert result.outcome is RiskCheckOutcome.INSUFFICIENT_DATA
    assert result.hit_frequency is None and result.hit_count is None
    assert (
        calculate_stress_assessment(request).outcome
        is RiskCheckOutcome.INSUFFICIENT_DATA
    )


def test_ruin_observation_rejects_tampering_horizons_currency_and_work_bounds() -> None:
    request = stress_assessment_request()
    evidence = request.ruin_paths
    assert evidence is not None
    with pytest.raises(RiskContractError, match="DIGEST_MISMATCH"):
        calculate_ruin_observation(
            replace(evidence, paths=((money("0"), money("0")),) * 3),
            request.policy,
            T[4],
        )
    with pytest.raises(RiskContractError, match="horizon"):
        replace(evidence, horizon_steps=3)
    with pytest.raises(RiskContractError, match="bound"):
        replace(evidence, horizon_steps=1000001)
    foreign = RuinPathEvidence.build(
        portfolio_request=request.portfolio_request,
        scenario_model_version=evidence.scenario_model_version,
        cost_model_version=evidence.cost_model_version,
        source_version=evidence.source_version,
        as_of=T[3],
        valid_until=T[12],
        horizon_steps=2,
        paths=((MoneyValue(Decimal("0"), "OTHER-USD"), money("0")),) * 3,
        assumptions=evidence.assumptions,
    )
    with pytest.raises(RiskContractError, match="CURRENCY_MISMATCH"):
        calculate_ruin_observation(foreign, request.policy, T[4])


def test_stress_assessment_no_equity_or_drawdown_clamping() -> None:
    request = stress_assessment_request()
    first = replace(request.projections[0], projected_loss=money("20000"))
    result = calculate_stress_assessment(
        replace(request, projections=(first, *request.projections[1:]))
    )
    assert result.outcome is RiskCheckOutcome.FAILED
    observed = next(x for x in result.scenarios if x.scenario_id == first.scenario_id)
    assert observed.projected_loss == money("20000")
    assert observed.projected_drawdown is None
    assert result.worst_loss == money("20000")
    assert result.worst_drawdown is None


def test_stress_assessment_warning_digest_and_decimal_context() -> None:
    request = stress_assessment_request(warning=True)
    expected = calculate_stress_assessment(request)
    assert expected.outcome is RiskCheckOutcome.WARNING
    with localcontext(Context(prec=3, rounding=ROUND_DOWN)):
        actual = calculate_stress_assessment(request)
    assert actual == expected
    first = replace(request.projections[0], projected_loss=money("600"))
    assert (
        calculate_stress_assessment(
            replace(request, projections=(first, *request.projections[1:]))
        ).content_sha256
        != expected.content_sha256
    )
    tiny = replace(request.projections[0], projected_loss=money("1e-40"))
    with pytest.raises(RiskContractError, match="precision 34"):
        calculate_stress_assessment(
            replace(request, projections=(tiny, *request.projections[1:]))
        )


def test_stress_assessment_expiry_boundary_and_duplicate_ids() -> None:
    request = stress_assessment_request()
    first = replace(request.projections[0], valid_until=T[4])
    result = calculate_stress_assessment(
        replace(request, projections=(first, *request.projections[1:]))
    )
    assert result.outcome is RiskCheckOutcome.PASSED and result.valid_until == T[4]
    with pytest.raises(RiskContractError, match="duplicate"):
        replace(request, projections=(request.projections[0], request.projections[0]))
    with pytest.raises(RiskContractError, match="require ruin"):
        replace(request.policy, required_scenario_types=("RISK_OF_RUIN",))


def test_ruin_observation_validity_cannot_outlive_exact_portfolio_basis() -> None:
    request = stress_assessment_request()
    result = calculate_ruin_observation(request.ruin_paths, request.policy, T[4])
    assert result.valid_until == T[10]


def test_stress_assessment_zero_liquidation_distance_is_a_breach_even_at_zero_cap() -> (
    None
):
    request = stress_assessment_request()
    first = replace(request.projections[0], minimum_liquidation_distance=Decimal("0"))
    result = calculate_stress_assessment(
        replace(
            request,
            policy=replace(request.policy, minimum_liquidation_distance=Decimal("0")),
            projections=(first, *request.projections[1:]),
        )
    )
    assert result.outcome is RiskCheckOutcome.FAILED
    assert any(x.endswith("/liquidation_distance") for x in result.breached_limit_ids)


def test_ruin_observation_exact_frequency_equality_passes() -> None:
    request = stress_assessment_request(
        paths=(("-5000", "100"), ("-5000", "100"), ("0", "0"), ("0", "0"))
    )
    result = calculate_ruin_observation(
        request.ruin_paths,
        replace(request.policy, maximum_ruin_frequency=Decimal("0.5")),
        T[4],
    )
    assert result.outcome is RiskCheckOutcome.PASSED
    assert result.hit_count == 2 and result.path_count == 4
    assert result.hit_frequency == Decimal("0.5")


@pytest.mark.parametrize("field,value", [("as_of", T[5]), ("valid_until", T[3])])
def test_ruin_observation_noncurrent_evidence_cannot_report_zero_risk(
    field: str, value: datetime
) -> None:
    request = stress_assessment_request()
    evidence = replace(request.ruin_paths, **{field: value})
    evidence = replace(evidence, content_sha256=evidence.identity_digest())
    result = calculate_ruin_observation(evidence, request.policy, T[4])
    assert result.outcome is RiskCheckOutcome.INSUFFICIENT_DATA
    assert result.hit_frequency is None


def test_stress_assessment_upstream_portfolio_veto_cannot_be_overridden() -> None:
    request = stress_assessment_request()
    portfolio_value = replace(
        request.portfolio_request,
        policy=replace(request.portfolio_request.policy, total_risk_budget=money("1")),
    )
    evidence = replace(request.ruin_paths, portfolio_request=portfolio_value)
    evidence = replace(evidence, content_sha256=evidence.identity_digest())
    request = replace(
        request,
        portfolio_request=portfolio_value,
        policy=replace(request.policy, portfolio_request=portfolio_value),
        projections=tuple(
            replace(x, portfolio_request=portfolio_value) for x in request.projections
        ),
        ruin_paths=evidence,
    )
    assert calculate_stress_assessment(request).outcome is RiskCheckOutcome.FAILED
    assert (
        calculate_ruin_observation(evidence, request.policy, T[4]).outcome
        is RiskCheckOutcome.FAILED
    )


def test_stress_assessment_rejects_untyped_paths_and_preserves_c081_schema() -> None:
    request = stress_assessment_request()
    with pytest.raises(RiskContractError, match="C-072 is not accepted"):
        replace(request, ruin_paths=object())
    assert stress().schema_version == "1"
    assert StressTestResult.__dataclass_fields__["schema_version"].default == "1"
    assert "ruin_probability" not in StressTestResult.__dataclass_fields__


@pytest.mark.parametrize("kind", ["projection", "ruin"])
def test_stress_assessment_source_version_mismatch_cannot_supply_numbers(
    kind: str,
) -> None:
    request = stress_assessment_request()
    if kind == "projection":
        first = replace(
            request.projections[0], source_version=version("foreign-source")
        )
        request = replace(request, projections=(first, *request.projections[1:]))
        identity = first.scenario_id
    else:
        evidence = replace(request.ruin_paths, source_version=version("foreign-source"))
        evidence = replace(evidence, content_sha256=evidence.identity_digest())
        observation = calculate_ruin_observation(evidence, request.policy, T[4])
        assert observation.outcome is RiskCheckOutcome.FAILED
        assert observation.hit_count is None and observation.hit_frequency is None
        request = replace(request, ruin_paths=evidence)
        identity = "ruin/observation"
    result = calculate_stress_assessment(request)
    assert result.outcome is RiskCheckOutcome.FAILED
    assert "STRESS_SOURCE_VERSION_MISMATCH" in result.reason_codes
    scenario = next(x for x in result.scenarios if x.scenario_id == identity)
    assert scenario.projected_loss is None and scenario.projected_margin is None
    assert scenario.projected_drawdown is None


@pytest.mark.parametrize(
    "field", ["projected_loss", "projected_margin", "included_cost_reserve"]
)
def test_stress_assessment_negative_projection_money_is_rejected(field: str) -> None:
    request = stress_assessment_request()
    with pytest.raises(RiskContractError, match="non-negative"):
        replace(request.projections[0], **{field: money("-1")})


@pytest.mark.parametrize("field", ["maximum_loss", "ruin_equity_floor"])
def test_stress_assessment_negative_policy_money_is_rejected(field: str) -> None:
    request = stress_assessment_request()
    with pytest.raises(RiskContractError, match="non-negative"):
        replace(request.policy, **{field: money("-1")})


@pytest.mark.parametrize("loss", ["2000", "10000"])
@pytest.mark.parametrize(
    "missing",
    [
        "included_cost_reserve",
        "shocks",
        "projected_margin",
        "minimum_liquidation_distance",
    ],
)
def test_stress_assessment_known_loss_veto_survives_incomplete_evidence(
    loss: str, missing: str
) -> None:
    request = stress_assessment_request()
    first = replace(
        request.projections[0],
        projected_loss=money(loss),
        **{missing: () if missing == "shocks" else None},
    )
    result = calculate_stress_assessment(
        replace(request, projections=(first, *request.projections[1:]))
    )
    assert result.outcome is RiskCheckOutcome.FAILED
    assert first.scenario_id + "/loss" in result.breached_limit_ids
    if loss == "10000":
        assert first.scenario_id + "/equity_exhausted" in result.breached_limit_ids
    if missing in {"included_cost_reserve", "shocks"}:
        assert result.worst_loss is None  # partial metadata grants no numeric authority


@pytest.mark.parametrize(
    "field,other",
    [
        ("projected_margin", {"projected_loss": None}),
        ("projected_loss", {"included_cost_reserve": None}),
        ("included_cost_reserve", {"cost_treatment": None}),
        ("projected_margin", {"as_of": T[5]}),
        ("projected_loss", {"source_version": version("foreign-source")}),
        ("included_cost_reserve", {"shocks": ()}),
    ],
)
def test_stress_assessment_foreign_currency_rejected_even_with_other_missing_evidence(
    field: str, other: dict[str, object]
) -> None:
    request = stress_assessment_request()
    first = replace(
        request.projections[0],
        **{**other, field: MoneyValue(Decimal("100"), "OTHER-USD")},
    )
    with pytest.raises(RiskContractError, match="CURRENCY_MISMATCH"):
        calculate_stress_assessment(
            replace(request, projections=(first, *request.projections[1:]))
        )


def test_stress_assessment_known_margin_veto_survives_missing_loss() -> None:
    request = stress_assessment_request()
    first = replace(
        request.projections[0], projected_loss=None, projected_margin=money("6000")
    )
    result = calculate_stress_assessment(
        replace(request, projections=(first, *request.projections[1:]))
    )
    assert result.outcome is RiskCheckOutcome.FAILED
    assert first.scenario_id + "/margin" in result.breached_limit_ids
    assert result.worst_loss is None
