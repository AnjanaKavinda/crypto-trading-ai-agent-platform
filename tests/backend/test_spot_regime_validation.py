"""Focused C-074v2 contract and codec tests."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import NAMESPACE_URL, uuid5

import pytest
from trading_platform_api.analysis.spot_market_regime import (
    SPOT_MARKET_REGIME_PROFILE_VERSION,
)
from trading_platform_api.analysis.versioned_contracts_v4 import (
    AnalysisOutputReferenceV4,
    AnalysisSnapshotReferenceV4,
)
from trading_platform_api.contracts.serialization import (
    canonical_sha256,
)
from trading_platform_api.lineage.codec import LineageError, decode, encode, key_for
from trading_platform_api.lineage.store import references
from trading_platform_api.validation.contracts import ValidationContractError
from trading_platform_api.validation.contracts_v2 import ValidationArtifactReferenceV2
from trading_platform_api.validation.regime_contracts_v2 import (
    WARNINGS,
    DecisionAttributionRuleV2,
    RegimeContextCoverageV2,
    RegimeContextKeyV2,
    RegimeCoverageStateV2,
    RegimeMetricObservationV2,
    RegimeMetricsPolicyV2,
    RegimeMetricStateV2,
    RegimeObservationStateV2,
    SpotRegimeObservationV2,
    SpotRegimeValidationResultV2,
)
from trading_platform_api.validation.spot_metrics import METHOD as METRICS_METHOD
from trading_platform_api.validation.spot_metrics import MetricsPolicy

D = Decimal
NOW = datetime(2026, 1, 1, tzinfo=UTC)
HASH = "a" * 64


def _id(name: str):
    return uuid5(NAMESPACE_URL, f"spot-regime-test:{name}")


def _ref(kind: str, version: str, name: str) -> ValidationArtifactReferenceV2:
    digest = canonical_sha256((kind, version, name))
    return ValidationArtifactReferenceV2(kind, _id(name), version, digest)


def _policy() -> MetricsPolicy:
    return MetricsPolicy(
        METRICS_METHOD,
        "1",
        "USDT",
        "BAR_CLOSE",
        60,
        D("525600"),
        D("0"),
        D("0"),
        2,
        2,
        NOW,
    )


def _key(**overrides) -> RegimeContextKeyV2:
    values = {
        "venue": "synthetic-venue",
        "asset": "SYNTHETIC",
        "instrument_id": "SYNTHETIC-USDT",
        "timeframe": "1m",
        "profile_version": SPOT_MARKET_REGIME_PROFILE_VERSION,
        "trend": "bullish",
        "realized_volatility": "typical",
        "transition": "not-observed-in-lookback",
    }
    values.update(overrides)
    return RegimeContextKeyV2(**values)


def _metric(
    name: str,
    unit: str,
    value: Decimal | None,
    *,
    sufficient: bool = True,
    reason: str | None = None,
) -> RegimeMetricObservationV2:
    return RegimeMetricObservationV2(
        name,
        RegimeMetricStateV2.AVAILABLE
        if value is not None
        else RegimeMetricStateV2.UNAVAILABLE,
        value,
        unit,
        3 if sufficient else 1,
        sufficient,
        reason,
        () if sufficient else ("INSUFFICIENT_SAMPLE",),
    )


def _observation(
    *,
    run_index: int = 0,
    request_sha256: str = "b" * 64,
    state: RegimeObservationStateV2 = RegimeObservationStateV2.OBSERVED,
    context_key: RegimeContextKeyV2 | None = None,
    attributed: bool = True,
    metrics: tuple[RegimeMetricObservationV2, ...] | None = None,
) -> SpotRegimeObservationV2:
    policy = RegimeMetricsPolicyV2.from_policy(_policy())
    context_key = (context_key or _key()) if attributed else None
    result_ref = _ref("C-027", "3", f"result-{run_index}")
    return SpotRegimeObservationV2(
        run_index=run_index,
        state=state,
        reason_codes=()
        if state is RegimeObservationStateV2.OBSERVED
        else ("METRIC_SAMPLE_SUFFICIENCY_NOT_MET",),
        request_sha256=request_sha256,
        request_parameters_sha256="c" * 64,
        execution_policy_sha256="d" * 64,
        metrics_policy=policy,
        metrics_policy_sha256=canonical_sha256(policy),
        backtest=result_ref,
        trace=_ref(
            "SIMULATION_TRACE", "spot-strategy-backtest-v1", f"trace-{run_index}"
        ),
        source_bundle_sha256="e" * 64,
        metrics_report_id=_id(f"report-{run_index}"),
        metrics_report_sha256="f" * 64,
        metrics_input_sha256="1" * 64,
        strategy_version=_ref("C-021", "2", "strategy"),
        cost_assumptions=_ref("C-027", "2", f"cost-{run_index}"),
        cost_adapter=_ref(
            "SPOT-COST-ADAPTER",
            "spot-execution-cost-adapter-v1",
            f"adapter-{run_index}",
        ),
        dataset_id="synthetic-dataset",
        dataset_version="1",
        dataset_sha256="2" * 64,
        dataset_lineage_sha256="3" * 64,
        manifest_sha256="4" * 64,
        quote_unit="USDT",
        quantity_unit="SYN",
        venue="synthetic-venue",
        asset="SYNTHETIC",
        instrument_id="SYNTHETIC-USDT",
        timeframe="1m",
        source_as_of=NOW,
        source_created_at=NOW,
        source_expires_at=NOW + timedelta(days=1),
        metrics_report_timestamp=NOW,
        period_start=NOW,
        period_end=NOW + timedelta(minutes=3),
        attribution_rule=DecisionAttributionRuleV2.ENTRY_ORDER_DECISION
        if attributed
        else None,
        decision_id=_id(f"decision-{run_index}") if attributed else None,
        decision_time=NOW if attributed else None,
        market_context=_ref("C-006", "5", f"context-{run_index}")
        if attributed
        else None,
        analysis_snapshot=AnalysisSnapshotReferenceV4(_id("snapshot"), "4", HASH)
        if attributed
        else None,
        regime=AnalysisOutputReferenceV4("C-005", _id("regime"), "1", "1", HASH)
        if attributed
        else None,
        evidence=(
            (AnalysisOutputReferenceV4("C-008", _id("evidence"), "2", "2", HASH),)
            if attributed
            else ()
        ),
        context_key=context_key,
        metrics=metrics
        or (
            _metric("cumulative_return", "ratio", D("0.10")),
            _metric("maximum_fractional_drawdown", "ratio", D("0.05")),
            _metric("total_trades", "count", D("3")),
        ),
    )


def _result(
    *,
    observations: tuple[SpotRegimeObservationV2, ...] | None = None,
    required: tuple[RegimeContextKeyV2, ...] | None = None,
    contexts: tuple[RegimeContextCoverageV2, ...] | None = None,
    outcome: RegimeObservationStateV2 = RegimeObservationStateV2.OBSERVED,
    reasons: tuple[str, ...] = (),
):
    key = _key()
    observations = observations or (_observation(context_key=key),)
    required = required or (key,)
    contexts = contexts or (
        RegimeContextCoverageV2(
            key,
            True,
            RegimeCoverageStateV2.OBSERVED,
            (0,),
            (0,) if observations[0].state is RegimeObservationStateV2.OBSERVED else (),
        ),
    )
    return SpotRegimeValidationResultV2.build(
        outcome=outcome,
        strategy_version=_ref("C-021", "2", "strategy"),
        metrics_method=METRICS_METHOD,
        metrics_method_version="1",
        minimum_trade_sample=2,
        minimum_return_sample=2,
        required_contexts=required,
        observations=observations,
        contexts=contexts,
        warnings=WARNINGS,
        reasons=reasons,
        as_of=NOW,
        created_at=NOW,
    )


def test_complete_observation_has_canonical_identity_and_codec_round_trip():
    result = _result()

    assert result.outcome is RegimeObservationStateV2.OBSERVED
    assert result.observations[0].metrics[0].unit == "ratio"
    assert result.observations[0].metrics[2].unit == "count"
    assert key_for(result).contract_id == "C-074"
    assert decode(encode(result)) == result
    with pytest.raises(LineageError, match="retention is not authorized"):
        references(result)


def test_missing_context_and_partial_metrics_remain_inconclusive():
    key = _key()
    missing_observation = _observation(
        state=RegimeObservationStateV2.INCONCLUSIVE,
        attributed=False,
        metrics=(
            _metric("cumulative_return", "ratio", D("0.10")),
            _metric(
                "maximum_fractional_drawdown",
                "ratio",
                None,
                sufficient=False,
                reason="PRICE_PATH_NOT_PROVIDED",
            ),
            _metric("total_trades", "count", D("1"), sufficient=False),
        ),
    )
    missing = _result(
        observations=(missing_observation,),
        contexts=(
            RegimeContextCoverageV2(key, True, RegimeCoverageStateV2.MISSING, (), ()),
        ),
        outcome=RegimeObservationStateV2.INCONCLUSIVE,
        reasons=("REQUIRED_CONTEXT_COVERAGE_MISSING",),
    )

    assert missing.contexts[0].state is RegimeCoverageStateV2.MISSING
    assert missing.observations[0].metrics[0].value == D("0.10")
    assert not missing.observations[0].metrics[1].sufficient


def test_contract_rejects_unknown_labels_duplicate_requests_and_unknown_versions():
    with pytest.raises(ValidationContractError, match="Unknown C-005 Spot trend"):
        _key(trend="ranging")
    with pytest.raises(ValidationContractError, match="Unsupported C-005 Spot regime"):
        _key(profile_version="spot-unknown-v9")

    first = _observation()
    second = replace(first, run_index=1, backtest=_ref("C-027", "3", "second-result"))
    with pytest.raises(
        ValidationContractError, match="planned requests must be unique"
    ):
        _result(
            observations=(first, second),
            contexts=(
                RegimeContextCoverageV2(
                    _key(),
                    True,
                    RegimeCoverageStateV2.OBSERVED,
                    (0, 1),
                    (0, 1),
                ),
            ),
        )

    document = encode(_result()).replace(
        '"payload_version":"wire-1","schema_version":"2"}',
        '"payload_version":"wire-1","schema_version":"99"}',
    )
    with pytest.raises(LineageError):
        decode(document)


def test_equivalent_decimal_representations_have_identical_result_identity():
    first_metric = _metric("cumulative_return", "ratio", D("0.10"))
    second_metric = _metric("cumulative_return", "ratio", D("0.100"))
    first_metrics = (
        first_metric,
        _metric("maximum_fractional_drawdown", "ratio", D("0.05")),
        _metric("total_trades", "count", D("3")),
    )
    second_metrics = (
        second_metric,
        _metric("maximum_fractional_drawdown", "ratio", D("0.0500")),
        _metric("total_trades", "count", D("3.0")),
    )
    first = _result(observations=(_observation(metrics=first_metrics),))
    second = _result(observations=(_observation(metrics=second_metrics),))

    assert first.content_sha256 == second.content_sha256
    assert first.result_id == second.result_id
