from dataclasses import FrozenInstanceError, fields, replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from uuid import UUID, uuid4

import pytest
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
    LiquidationAssessment,
    LiquidationAvailability,
    MarginMode,
    MoneyValue,
    OfflineAccountAssessment,
    OfflineAccountEvidence,
    PairwiseCorrelationResult,
    PortfolioExposureAggregation,
    PortfolioImpact,
    PortfolioSnapshot,
    PositionExposureInput,
    PositionSide,
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
    SizingMethod,
    SnapshotState,
    StopLossAssessment,
    StressScenarioResult,
    StressTestResult,
    TakeProfitAssessment,
    TakeProfitTarget,
    VersionReference,
    aggregate_portfolio_exposure,
    pairwise_correlation,
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
    assert unaligned.reason == "INSUFFICIENT_ALIGNED_OBSERVATIONS"
    assert unaligned.sample_count == 0


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
