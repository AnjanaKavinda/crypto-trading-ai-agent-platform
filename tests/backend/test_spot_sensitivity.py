"""Synthetic contract evidence for the C-073v2 Spot sensitivity boundary."""

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import NAMESPACE_URL, uuid5

import pytest
from trading_platform_api.contracts.serialization import canonical_sha256
from trading_platform_api.lineage.codec import LineageError, decode, encode, key_for
from trading_platform_api.lineage.store import references
from trading_platform_api.validation.contracts_v2 import (
    ValidationArtifactReferenceV2,
)
from trading_platform_api.validation.sensitivity_contracts_v2 import (
    COST_MULTIPLIERS,
    METRICS_METHOD,
    SensitivityMetricsPolicyV2,
    SensitivityMetricsV2,
    SensitivityOutcomeV2,
    SensitivityResultV2,
    SensitivityScenarioKindV2,
    SensitivityScenarioV2,
    SensitivityZeroCrossingV2,
)

D = Decimal
NOW = datetime(2026, 1, 1, tzinfo=UTC)
HASH = "a" * 64


def _reference(kind: str, version: str, key: str) -> ValidationArtifactReferenceV2:
    digest = canonical_sha256((kind, version, key))
    return ValidationArtifactReferenceV2(
        kind,
        uuid5(NAMESPACE_URL, digest),
        version,
        digest,
    )


def _scenario(
    *,
    key: str,
    kind: SensitivityScenarioKindV2,
    parameter_value: Decimal,
    multiplier: Decimal,
    cumulative_return: Decimal,
    drawdown: Decimal,
    baseline_return: Decimal,
    baseline_drawdown: Decimal,
) -> SensitivityScenarioV2:
    return_delta = cumulative_return - baseline_return
    drawdown_delta = drawdown - baseline_drawdown
    report_digest = canonical_sha256(("report", key))
    return SensitivityScenarioV2(
        key,
        kind,
        parameter_value,
        multiplier,
        SensitivityOutcomeV2.OBSERVED,
        _reference("C-027", "3", f"backtest:{key}"),
        _reference("SIMULATION_TRACE", "spot-strategy-backtest-v1", f"trace:{key}"),
        _reference("C-027", "2", f"cost:{key}"),
        uuid5(NAMESPACE_URL, f"report:{key}"),
        report_digest,
        canonical_sha256(("input", key)),
        SensitivityMetricsV2(cumulative_return, drawdown, 3),
        return_delta,
        drawdown_delta,
        return_delta < 0,
        drawdown_delta > 0,
        key == "parameter:2",
        (),
        NOW,
        NOW,
        NOW + timedelta(days=1),
        NOW,
    )


def _result_values() -> dict[str, object]:
    baseline_return = D("0.03")
    baseline_drawdown = D("0.05")
    grid = (D("1"), D("2"), D("3"))
    scenarios = tuple(
        _scenario(
            key=f"parameter:{value}",
            kind=SensitivityScenarioKindV2.PARAMETER,
            parameter_value=value,
            multiplier=D("1"),
            cumulative_return=returns[value],
            drawdown=drawdowns[value],
            baseline_return=baseline_return,
            baseline_drawdown=baseline_drawdown,
        )
        for value in grid
    ) + tuple(
        _scenario(
            key=f"cost:{multiplier}",
            kind=SensitivityScenarioKindV2.COST,
            parameter_value=D("2"),
            multiplier=multiplier,
            cumulative_return=returns_by_cost[multiplier],
            drawdown=drawdown_by_cost[multiplier],
            baseline_return=baseline_return,
            baseline_drawdown=baseline_drawdown,
        )
        for multiplier in COST_MULTIPLIERS[1:]
    )
    metrics_policy = SensitivityMetricsPolicyV2(
        METRICS_METHOD,
        "1",
        "USDT",
        "BAR_CLOSE",
        60,
        D("525600"),
        D(0),
        D(0),
        1,
        1,
        NOW,
    )
    return {
        "outcome": SensitivityOutcomeV2.OBSERVED,
        "parameter_name": "holding_interval",
        "parameter_unit": "seconds",
        "quantity_unit": "BTC",
        "baseline_value": D("2"),
        "parameter_grid": grid,
        "cost_multipliers": COST_MULTIPLIERS,
        "input_request_sha256": HASH,
        "source_bundle_sha256": "b" * 64,
        "source_backtest": _reference("C-027", "3", "source-backtest"),
        "source_trace": _reference(
            "SIMULATION_TRACE", "spot-strategy-backtest-v1", "source-trace"
        ),
        "source_metrics_report_id": uuid5(NAMESPACE_URL, "source-report"),
        "source_metrics_report_sha256": "c" * 64,
        "strategy_version": _reference("C-021", "2", "strategy"),
        "source_cost_assumptions": _reference("C-027", "2", "source-cost"),
        "source_as_of": NOW,
        "source_created_at": NOW,
        "source_expires_at": NOW + timedelta(days=1),
        "dataset_id": "synthetic-dataset",
        "dataset_version": "1",
        "dataset_sha256": HASH,
        "dataset_lineage_sha256": "d" * 64,
        "manifest_sha256": "e" * 64,
        "venue": "synthetic-test-only",
        "instrument_id": "SYNTHETIC-BTC-USDT",
        "timeframe": "1m",
        "period_start": NOW,
        "period_end": NOW + timedelta(minutes=10),
        "metrics_method": METRICS_METHOD,
        "metrics_policy": metrics_policy,
        "metrics_policy_sha256": canonical_sha256(metrics_policy),
        "scenarios": scenarios,
        "zero_crossings": (
            SensitivityZeroCrossingV2(
                SensitivityScenarioKindV2.COST, "cost:2", "cost:3"
            ),
        ),
        "assumptions": (
            "ONE_PARAMETER_VARIED_AT_A_TIME",
            "COST_STRESS_VARIED_SEPARATELY_FROM_PARAMETER_GRID",
            "CONDITIONAL_ON_EXACT_OBSERVED_SPOT_DATA_AND_POLICY",
            "DESCRIPTIVE_NOT_SELECTION_OR_QUALIFICATION",
            "NOT_OUT_OF_SAMPLE_OR_FUTURE_PERFORMANCE_EVIDENCE",
        ),
        "warnings": (
            "NO_OPTIMAL_PARAMETER_SELECTED",
            "LOCAL_PEAKS_AND_DEGRADATION_ARE_DESCRIPTIVE_ONLY",
            "DOES_NOT_COMPLETE_FUTURES_VALIDATION",
        ),
        "reasons": (),
        "as_of": NOW,
        "created_at": NOW,
    }


returns = {D("1"): D("0.01"), D("2"): D("0.03"), D("3"): D("0.02")}
drawdowns = {D("1"): D("0.10"), D("2"): D("0.05"), D("3"): D("0.08")}
returns_by_cost = {
    D("1.25"): D("0.02"),
    D("1.5"): D("0.01"),
    D("2"): D("0"),
    D("3"): D("-0.01"),
}
drawdown_by_cost = {
    D("1.25"): D("0.06"),
    D("1.5"): D("0.07"),
    D("2"): D("0.08"),
    D("3"): D("0.09"),
}


def test_c073v2_identity_records_every_point_and_rejects_retention():
    result = SensitivityResultV2.build(**_result_values())
    repeated = SensitivityResultV2.build(**_result_values())

    assert result == repeated
    assert len(result.scenarios) == 7
    assert tuple(item.parameter_value for item in result.scenarios[:3]) == (
        D("1"),
        D("2"),
        D("3"),
    )
    assert tuple(item.local_peak for item in result.scenarios[:3]) == (
        False,
        True,
        False,
    )
    assert result.scenarios[0].return_degraded
    assert result.scenarios[0].drawdown_degraded
    assert tuple(item.cost_multiplier for item in result.scenarios[3:]) == (
        D("1.25"),
        D("1.5"),
        D("2"),
        D("3"),
    )
    assert result.zero_crossings == (
        SensitivityZeroCrossingV2(
            SensitivityScenarioKindV2.COST, "cost:2", "cost:3"
        ),
    )
    document = encode(result)
    assert decode(document) == result
    assert key_for(result).contract_id == "C-073"
    assert key_for(result).version == "2"
    with pytest.raises(LineageError, match="retention is not authorized"):
        references(result)

    unsupported = json.loads(document)
    unsupported["schema_version"] = "1"
    unsupported["payload"]["schema_version"] = "1"
    with pytest.raises(LineageError):
        decode(json.dumps(unsupported, sort_keys=True, separators=(",", ":")))


def test_c073v2_cannot_be_substituted_for_v1_c030_sensitivity():
    from test_validation_contracts import robustness

    result = SensitivityResultV2.build(**_result_values())
    with pytest.raises(ValueError):
        robustness(sensitivity=result)
