from dataclasses import FrozenInstanceError, fields
from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from trading_platform_api.validation import (
    ArtifactReference,
    AssumptionCategory,
    BacktestResult,
    BiasCheck,
    BiasCheckReport,
    BiasCheckType,
    CalibrationBin,
    CalibrationResult,
    CheckOutcome,
    DataPartition,
    DistributionPoint,
    MetricValue,
    MonteCarloResult,
    OOSResult,
    PartitionPurpose,
    RegimeSlice,
    RegimeValidationResult,
    ReproducibilityContext,
    ResearchAssumption,
    ResultReference,
    RobustnessCheck,
    RobustnessCheckType,
    RobustnessResult,
    SensitivityPoint,
    SensitivityResult,
    StatisticalInterval,
    StrategyEvidenceLevel,
    ValidationContractError,
    ValidationFailureCode,
    ValidationGate,
    ValidationGateResult,
    ValidationLifecycle,
    ValidationResult,
    WalkForwardFold,
    WalkForwardResult,
)

T = tuple(datetime(2026, 1, 1, tzinfo=UTC) + timedelta(days=i) for i in range(15))
HASH_A = "a" * 64


def artifact(kind: str) -> ArtifactReference:
    return ArtifactReference(kind, uuid4(), "v1", HASH_A)


def partition(
    purpose: PartitionPurpose,
    start: datetime,
    end: datetime,
    *,
    optimized: bool = False,
) -> DataPartition:
    return DataPartition(uuid4(), purpose, start, end, end, optimized)


def metric(name: str = "conditional_win_rate") -> MetricValue:
    return MetricValue(name, Decimal("0.76"), "ratio", "metric-v1")


def interval(name: str = "conditional_win_rate") -> StatisticalInterval:
    return StatisticalInterval(
        name,
        "synthetic-wilson-test-fixture",
        Decimal("0.95"),
        Decimal("0.70"),
        Decimal("0.76"),
        Decimal("0.81"),
        100,
    )


def assumptions() -> tuple[ResearchAssumption, ...]:
    return tuple(
        ResearchAssumption(
            category,
            artifact(f"{category.value.lower()}-model"),
            Decimal("0"),
            "synthetic-unit",
            "Explicit zero used only by this schema-validation test fixture.",
        )
        for category in AssumptionCategory
    )


def context(**overrides: object) -> ReproducibilityContext:
    values: dict[str, object] = {
        "strategy": artifact("C-020"),
        "strategy_version": artifact("C-021"),
        "parameter_set": artifact("parameter-set"),
        "configuration": artifact("configuration"),
        "dataset": artifact("C-092"),
        "feature_definitions": (artifact("feature-definition"),),
        "execution_model": artifact("execution-model"),
        "validation_methodology": artifact("validation-methodology"),
        "statistical_methodology": artifact("statistical-methodology"),
        "software": artifact("software"),
        "partitions": (
            partition(PartitionPurpose.TRAIN, T[0], T[1], optimized=True),
            partition(PartitionPurpose.VALIDATION, T[1], T[2]),
            partition(PartitionPurpose.OUT_OF_SAMPLE, T[2], T[3]),
        ),
        "assumptions": assumptions(),
        "asset_universe": ("SYNTHETIC-BTC",),
        "instrument_ids": ("SYNTHETIC-BTC-USDT",),
        "timeframe": "1h",
        "strategies_tested": 1,
        "hypotheses_tested": 1,
        "parameter_combinations_tested": 1,
        "correlation_id": "synthetic-trace",
    }
    values.update(overrides)
    return ReproducibilityContext(**values)  # type: ignore[arg-type]


def base_values(
    strategy_version_id: UUID | None = None,
    *,
    lifecycle: ValidationLifecycle = ValidationLifecycle.PASSED,
) -> dict[str, object]:
    return {
        "result_id": uuid4(),
        "strategy_version_id": strategy_version_id or uuid4(),
        "lifecycle": lifecycle,
        "created_at": T[5],
        "as_of": T[4],
        "valid_until": T[10],
        "warnings": (),
        "failures": ()
        if lifecycle is ValidationLifecycle.PASSED
        else (ValidationFailureCode.STATISTICALLY_UNCERTAIN,),
    }


def backtest(
    strategy_version_id: UUID | None = None, **overrides: object
) -> BacktestResult:
    values = {
        **base_values(strategy_version_id),
        "context": context(),
        "metrics": (metric(),),
        "intervals": (interval(),),
        "simulated_trade_count": 100,
        "data_integrity": CheckOutcome.PASSED,
        "point_in_time_correct": CheckOutcome.PASSED,
        "content_sha256": HASH_A,
    }
    values.update(overrides)
    return BacktestResult(**values)  # type: ignore[arg-type]


def oos(strategy_version_id: UUID | None = None, **overrides: object) -> OOSResult:
    values = {
        **base_values(strategy_version_id),
        "backtest_result_id": uuid4(),
        "dataset_version_id": uuid4(),
        "partition": partition(PartitionPurpose.OUT_OF_SAMPLE, T[2], T[3]),
        "metrics": (metric(),),
        "intervals": (interval(),),
        "sample_size": 100,
    }
    values.update(overrides)
    return OOSResult(**values)  # type: ignore[arg-type]


def fold(start: int) -> WalkForwardFold:
    return WalkForwardFold(
        uuid4(),
        partition(PartitionPurpose.TRAIN, T[start], T[start + 1], optimized=True),
        partition(PartitionPurpose.VALIDATION, T[start + 1], T[start + 2]),
        artifact("parameter-set"),
        (metric(),),
        50,
        CheckOutcome.PASSED,
    )


def walk_forward(
    strategy_version_id: UUID | None = None, **overrides: object
) -> WalkForwardResult:
    values = {
        **base_values(strategy_version_id),
        "backtest_result_id": uuid4(),
        "folds": (fold(0), fold(2)),
        "aggregate_metrics": (metric(),),
    }
    values.update(overrides)
    return WalkForwardResult(**values)  # type: ignore[arg-type]


def monte_carlo(
    strategy_version_id: UUID | None = None, **overrides: object
) -> MonteCarloResult:
    values = {
        **base_values(strategy_version_id),
        "input_result_id": uuid4(),
        "technique": "synthetic bootstrap fixture",
        "iterations": 100,
        "seed": 42,
        "seed_policy": "fixed synthetic test seed",
        "sampling_assumptions": ("synthetic trades",),
        "distribution": (
            DistributionPoint(Decimal("0.05"), Decimal("-0.20")),
            DistributionPoint(Decimal("0.50"), Decimal("0.10")),
        ),
        "methodology": artifact("monte-carlo-method"),
    }
    values.update(overrides)
    return MonteCarloResult(**values)  # type: ignore[arg-type]


def sensitivity(
    strategy_version_id: UUID | None = None, **overrides: object
) -> SensitivityResult:
    values = {
        **base_values(strategy_version_id),
        "input_result_id": uuid4(),
        "points": (
            SensitivityPoint("threshold", Decimal("1"), metric(), True),
            SensitivityPoint("threshold", Decimal("2"), metric(), False),
        ),
        "degradation_boundaries": ("threshold > 2",),
    }
    values.update(overrides)
    return SensitivityResult(**values)  # type: ignore[arg-type]


def regime_result(
    strategy_version_id: UUID | None = None, **overrides: object
) -> RegimeValidationResult:
    values = {
        **base_values(strategy_version_id),
        "input_result_id": uuid4(),
        "taxonomy": artifact("regime-taxonomy"),
        "required_regimes": ("trend", "range"),
        "slices": (
            RegimeSlice("trend", 50, (metric(),), CheckOutcome.PASSED),
            RegimeSlice("range", 50, (metric(),), CheckOutcome.PASSED),
        ),
    }
    values.update(overrides)
    return RegimeValidationResult(**values)  # type: ignore[arg-type]


def bias_report(
    strategy_version_id: UUID | None = None, **overrides: object
) -> BiasCheckReport:
    values = {
        **base_values(strategy_version_id),
        "input_result_id": uuid4(),
        "checks": tuple(
            BiasCheck(
                check_type,
                CheckOutcome.PASSED,
                (f"synthetic-{check_type.value.lower()}",),
                "Passed by synthetic contract fixture.",
            )
            for check_type in BiasCheckType
        ),
    }
    values.update(overrides)
    return BiasCheckReport(**values)  # type: ignore[arg-type]


def result_ref(
    contract_id: str,
    strategy_version_id: UUID,
    lifecycle: ValidationLifecycle = ValidationLifecycle.PASSED,
) -> ResultReference:
    return ResultReference(contract_id, uuid4(), strategy_version_id, lifecycle, T[10])


def robustness(
    strategy_version_id: UUID | None = None, **overrides: object
) -> RobustnessResult:
    version_id = strategy_version_id or uuid4()
    values = {
        **base_values(version_id),
        "monte_carlo": result_ref("C-072", version_id),
        "sensitivity": result_ref("C-073", version_id),
        "regime_validation": result_ref("C-074", version_id),
        "cost_slippage_latency_checks": (
            RobustnessCheck(RobustnessCheckType.COST, CheckOutcome.PASSED, "cost"),
            RobustnessCheck(
                RobustnessCheckType.SLIPPAGE, CheckOutcome.PASSED, "slippage"
            ),
            RobustnessCheck(
                RobustnessCheckType.LATENCY, CheckOutcome.PASSED, "latency"
            ),
        ),
        "worst_case_metrics": (metric("worst_case_return"),),
        "evidence_level": StrategyEvidenceLevel.ROBUST,
    }
    values.update(overrides)
    return RobustnessResult(**values)  # type: ignore[arg-type]


def calibration(
    strategy_version_id: UUID | None = None, **overrides: object
) -> CalibrationResult:
    values = {
        **base_values(strategy_version_id),
        "model": artifact("synthetic-probability-model"),
        "target_definition": "Synthetic binary outcome for contract tests only.",
        "prediction_window": "one synthetic interval",
        "observation_window": "one synthetic interval",
        "calibration_method": artifact("calibration-method"),
        "sample_size": 100,
        "bins": (
            CalibrationBin(
                Decimal("0"), Decimal("1"), Decimal("0.5"), Decimal("0.5"), 100
            ),
        ),
        "metrics": (metric("brier_score"),),
        "intervals": (interval("calibrated_probability"),),
    }
    values.update(overrides)
    return CalibrationResult(**values)  # type: ignore[arg-type]


def gates(
    outcome: CheckOutcome = CheckOutcome.PASSED,
) -> tuple[ValidationGateResult, ...]:
    return tuple(
        ValidationGateResult(
            gate, outcome, (f"synthetic-{gate.value.lower()}",), "Synthetic fixture."
        )
        for gate in ValidationGate
    )


def validation_result(
    strategy_version_id: UUID | None = None, **overrides: object
) -> ValidationResult:
    version_id = strategy_version_id or uuid4()
    values = {
        **base_values(version_id),
        "signal_candidate_id": uuid4(),
        "evidence_package_id": uuid4(),
        "backtest": result_ref("C-027", version_id),
        "oos": result_ref("C-071", version_id),
        "walk_forward": result_ref("C-029", version_id),
        "robustness": result_ref("C-030", version_id),
        "bias_report": result_ref("C-094", version_id),
        "calibration": result_ref("C-031", version_id),
        "evidence_level": StrategyEvidenceLevel.ROBUST,
        "gates": gates(),
        "metrics": (metric(),),
        "intervals": (interval(),),
        "invalidation_triggers": ("strategy version changes",),
        "content_sha256": HASH_A,
    }
    values.update(overrides)
    return ValidationResult(**values)  # type: ignore[arg-type]


def test_all_ten_contracts_are_distinct_and_frozen() -> None:
    version_id = uuid4()
    values = (
        backtest(version_id),
        validation_result(version_id),
        walk_forward(version_id),
        robustness(version_id),
        calibration(version_id),
        oos(version_id),
        monte_carlo(version_id),
        sensitivity(version_id),
        regime_result(version_id),
        bias_report(version_id),
    )
    assert [(item.contract_id, item.schema_version) for item in values] == [
        ("C-027", "1"),
        ("C-028", "1"),
        ("C-029", "1"),
        ("C-030", "1"),
        ("C-031", "1"),
        ("C-071", "1"),
        ("C-072", "1"),
        ("C-073", "1"),
        ("C-074", "1"),
        ("C-094", "1"),
    ]
    for item in values:
        with pytest.raises(FrozenInstanceError):
            item.schema_version = "2"  # type: ignore[misc]


def test_reproducibility_context_requires_versions_assumptions_and_no_overlap() -> None:
    value = context()
    assert {item.category for item in value.assumptions} == set(AssumptionCategory)
    with pytest.raises(ValidationContractError, match="assumptions are required"):
        context(assumptions=assumptions()[:-1])
    with pytest.raises(ValidationContractError, match="must not overlap"):
        context(
            partitions=(
                partition(PartitionPurpose.TRAIN, T[0], T[2], optimized=True),
                partition(PartitionPurpose.VALIDATION, T[1], T[3]),
            )
        )
    with pytest.raises(ValidationContractError, match="dataset must reference C-092"):
        context(dataset=artifact("not-a-canonical-dataset"))


def test_explicit_justified_zero_cost_is_allowed_but_omission_is_not() -> None:
    assert all(
        item.value == Decimal("0") and item.justification for item in assumptions()
    )
    with pytest.raises(ValidationContractError, match="must not be empty"):
        context(assumptions=())


def test_partition_rejects_reversal_and_oos_optimization() -> None:
    with pytest.raises(ValidationContractError, match="must not be after"):
        partition(PartitionPurpose.TRAIN, T[2], T[1])
    with pytest.raises(
        ValidationContractError, match="cannot be used for optimization"
    ):
        partition(PartitionPurpose.OUT_OF_SAMPLE, T[1], T[2], optimized=True)


def test_metrics_and_intervals_reject_float_nonfinite_and_bad_bounds() -> None:
    with pytest.raises(ValidationContractError, match="finite Decimal"):
        MetricValue("x", 0.5, "ratio", "v1")  # type: ignore[arg-type]
    with pytest.raises(ValidationContractError, match="finite Decimal"):
        MetricValue("x", Decimal("NaN"), "ratio", "v1")
    with pytest.raises(ValidationContractError, match="lower <= point <= upper"):
        StatisticalInterval(
            "x",
            "method",
            Decimal("0.95"),
            Decimal("0.8"),
            Decimal("0.7"),
            Decimal("0.9"),
            10,
        )


def test_oos_requires_separated_nonoptimization_partition() -> None:
    with pytest.raises(ValidationContractError, match="separated"):
        oos(partition=partition(PartitionPurpose.TRAIN, T[0], T[1], optimized=True))


def test_walk_forward_rejects_empty_overlapping_and_future_leaking_folds() -> None:
    with pytest.raises(ValidationContractError, match="must not be empty"):
        walk_forward(folds=())
    first = fold(0)
    overlapping = WalkForwardFold(
        uuid4(),
        partition(PartitionPurpose.TRAIN, T[0], T[1], optimized=True),
        partition(PartitionPurpose.VALIDATION, T[1], T[2]),
        artifact("parameters"),
        (metric(),),
        50,
        CheckOutcome.PASSED,
    )
    with pytest.raises(ValidationContractError, match="periods overlap"):
        walk_forward(folds=(first, overlapping))
    with pytest.raises(ValidationContractError, match="must not be after"):
        WalkForwardFold(
            uuid4(),
            partition(PartitionPurpose.TRAIN, T[2], T[3], optimized=True),
            partition(PartitionPurpose.VALIDATION, T[1], T[2]),
            artifact("parameters"),
            (metric(),),
            10,
            CheckOutcome.PASSED,
        )


def test_monte_carlo_requires_iterations_seed_and_distribution() -> None:
    with pytest.raises(ValidationContractError, match="positive"):
        monte_carlo(iterations=0)
    with pytest.raises(ValidationContractError, match="seed must be an integer"):
        monte_carlo(seed="random")
    with pytest.raises(ValidationContractError, match="must not be empty"):
        monte_carlo(distribution=())


def test_sensitivity_requires_unique_surrounding_points_and_boundaries() -> None:
    point = SensitivityPoint("x", Decimal("1"), metric(), True)
    with pytest.raises(ValidationContractError, match="surrounding"):
        sensitivity(points=(point,))
    with pytest.raises(ValidationContractError, match="duplicates"):
        sensitivity(points=(point, point))
    with pytest.raises(ValidationContractError, match="exactly one baseline"):
        sensitivity(
            points=(
                SensitivityPoint("x", Decimal("1"), metric(), False),
                SensitivityPoint("x", Decimal("2"), metric(), False),
            )
        )


def test_regime_validation_exposes_missing_and_failed_required_regimes() -> None:
    with pytest.raises(ValidationContractError, match="missing"):
        regime_result(required_regimes=("trend", "range", "bear"))
    with pytest.raises(ValidationContractError, match="cannot hide"):
        regime_result(
            slices=(
                RegimeSlice("trend", 50, (metric(),), CheckOutcome.PASSED),
                RegimeSlice("range", 0, (), CheckOutcome.INCONCLUSIVE),
            )
        )


def test_bias_report_requires_every_passed_critical_check() -> None:
    with pytest.raises(ValidationContractError, match="every critical check"):
        bias_report(checks=bias_report().checks[:-1])
    bad_checks = list(bias_report().checks)
    bad_checks[0] = BiasCheck(
        bad_checks[0].check_type, CheckOutcome.FAILED, ("synthetic-failure",), "Failed."
    )
    with pytest.raises(ValidationContractError, match="all checks to pass"):
        bias_report(checks=tuple(bad_checks))


def test_robust_claim_requires_passed_compatible_components() -> None:
    version_id = uuid4()
    with pytest.raises(ValidationContractError, match="complete passed"):
        robustness(
            version_id,
            monte_carlo=result_ref("C-072", version_id, ValidationLifecycle.STALE),
        )
    with pytest.raises(ValidationContractError, match="version mismatch"):
        robustness(version_id, sensitivity=result_ref("C-073", uuid4()))


def test_calibration_is_separate_and_validates_probability_bins() -> None:
    value = calibration()
    field_names = {item.name for item in fields(value)}
    assert "analytical_confidence" not in field_names
    assert "historical_win_rate" not in field_names
    with pytest.raises(ValidationContractError, match="between 0 and 1"):
        CalibrationBin(Decimal("0"), Decimal("1"), Decimal("1.1"), Decimal("0.5"), 10)


def test_validation_result_requires_all_gates_and_matching_current_components() -> None:
    with pytest.raises(ValidationContractError, match="all 18 gates"):
        validation_result(gates=gates()[:-1])
    version_id = uuid4()
    with pytest.raises(ValidationContractError, match="version mismatch"):
        validation_result(version_id, oos=result_ref("C-071", uuid4()))
    with pytest.raises(ValidationContractError, match="passed components"):
        validation_result(
            version_id,
            oos=result_ref("C-071", version_id, ValidationLifecycle.STALE),
        )
    stale_ref = ResultReference(
        "C-071", uuid4(), version_id, ValidationLifecycle.PASSED, T[6]
    )
    with pytest.raises(ValidationContractError, match="expires before"):
        validation_result(version_id, oos=stale_ref)


def test_validation_result_rejects_contradictory_passed_status() -> None:
    with pytest.raises(ValidationContractError, match="requires all gates"):
        validation_result(gates=gates(CheckOutcome.INCONCLUSIVE))
    with pytest.raises(ValidationContractError, match="contradicts evidence"):
        validation_result(evidence_level=StrategyEvidenceLevel.INSUFFICIENT_DATA)


@pytest.mark.parametrize(
    "lifecycle",
    [
        ValidationLifecycle.FAILED,
        ValidationLifecycle.INCONCLUSIVE,
        ValidationLifecycle.STALE,
        ValidationLifecycle.EXPIRED,
    ],
)
def test_non_authoritative_lifecycle_remains_explicit(
    lifecycle: ValidationLifecycle,
) -> None:
    failures = (
        (ValidationFailureCode.STALE_EVIDENCE,)
        if lifecycle in {ValidationLifecycle.STALE, ValidationLifecycle.EXPIRED}
        else (ValidationFailureCode.STATISTICALLY_UNCERTAIN,)
    )
    result = validation_result(
        lifecycle=lifecycle,
        failures=failures,
        evidence_level=StrategyEvidenceLevel.REJECTED,
        gates=gates(CheckOutcome.FAILED),
    )
    assert result.lifecycle is lifecycle


def test_common_validation_rejects_bad_hash_naive_time_and_mutable_collection() -> None:
    with pytest.raises(ValidationContractError, match="SHA-256"):
        ArtifactReference("x", uuid4(), "v1", "bad")
    with pytest.raises(ValidationContractError, match="timezone-aware"):
        validation_result(created_at=datetime(2026, 1, 1))
    with pytest.raises(ValidationContractError, match="must be a tuple"):
        backtest(metrics=[metric()])


def test_times_normalize_to_utc_and_contracts_have_no_trading_authority() -> None:
    offset = datetime(
        2026, 1, 1, 5, 30, tzinfo=timezone(timedelta(hours=5, minutes=30))
    )
    value = backtest(
        as_of=offset, created_at=offset, valid_until=offset + timedelta(days=1)
    )
    assert value.as_of == T[0]
    prohibited = {
        "position_size",
        "leverage",
        "approval",
        "order",
        "execution_intent",
        "execution_authorized",
    }
    contract_types = (
        BacktestResult,
        ValidationResult,
        WalkForwardResult,
        RobustnessResult,
        CalibrationResult,
        OOSResult,
        MonteCarloResult,
        SensitivityResult,
        RegimeValidationResult,
        BiasCheckReport,
    )
    for contract_type in contract_types:
        assert prohibited.isdisjoint(item.name for item in fields(contract_type))
