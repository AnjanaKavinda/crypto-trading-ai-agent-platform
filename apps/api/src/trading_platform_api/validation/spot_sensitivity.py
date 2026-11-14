"""Offline one-factor sensitivity analysis over exact archived Spot replays."""

from __future__ import annotations

from dataclasses import fields, replace
from datetime import UTC, datetime, timedelta
from decimal import ROUND_HALF_EVEN, Context, Decimal, DecimalException, localcontext
from uuid import NAMESPACE_URL, uuid5

from sqlalchemy.ext.asyncio import AsyncSession

from trading_platform_api.config import DeploymentEnvironment, OperatingMode
from trading_platform_api.contracts.serialization import canonical_sha256
from trading_platform_api.lineage.store import SqlAlchemyLineageStore
from trading_platform_api.validation.contracts import CheckOutcome
from trading_platform_api.validation.contracts_v2 import ValidationArtifactReferenceV2
from trading_platform_api.validation.contracts_v3 import (
    BacktestOutcomeV3,
    BacktestResultV3,
)
from trading_platform_api.validation.cost_models import (
    LiquidityRole,
    build_spot_cost_assumption_set,
)
from trading_platform_api.validation.sensitivity_contracts_v2 import (
    ASSUMPTIONS,
    COST_MULTIPLIERS,
    PARAMETERS,
    WARNINGS,
    SensitivityMetricsPolicyV2,
    SensitivityMetricsV2,
    SensitivityOutcomeV2,
    SensitivityResultV2,
    SensitivityScenarioKindV2,
    SensitivityScenarioV2,
    SensitivityZeroCrossingV2,
)
from trading_platform_api.validation.spot_backtest import (
    SpotBacktestBundle,
    SpotBacktestOutcome,
    SpotBacktestRunRequest,
    SpotBacktestTrace,
    resolve_spot_backtest_result,
    run_spot_backtest,
)
from trading_platform_api.validation.spot_cost_adapter import SpotExecutionCostAdapter
from trading_platform_api.validation.spot_metrics import (
    METHOD as METRICS_METHOD,
)
from trading_platform_api.validation.spot_metrics import (
    MetricsInputError,
    MetricState,
    SpotPerformanceReport,
    calculate_spot_performance_metrics,
)
from trading_platform_api.validation.spot_replay_inputs import StrategyVersionResolver

_ARITHMETIC = Context(prec=50, rounding=ROUND_HALF_EVEN)
_REPORT_NAMESPACE = uuid5(NAMESPACE_URL, f"trading-platform:{METRICS_METHOD}")
_MAX_INTERVAL_SECONDS = 31_536_000
_MAX_QUANTITY = Decimal("1e30")


class SpotSensitivityInputError(ValueError):
    """The frozen sensitivity grid or source input is malformed."""


def _report_digest(report: SpotPerformanceReport) -> str:
    return canonical_sha256(
        {
            item.name: getattr(report, item.name)
            for item in fields(report)
            if item.name not in {"report_id", "content_sha256"}
        }
    )


def _report_identity_is_valid(report: SpotPerformanceReport) -> bool:
    digest = _report_digest(report)
    return report.content_sha256 == digest and report.report_id == uuid5(
        _REPORT_NAMESPACE, digest
    )


def _reference(kind: str, identity, version: str, digest: str):
    return ValidationArtifactReferenceV2(kind, identity, version, digest)


def _time(value: datetime) -> datetime:
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise SpotSensitivityInputError("TIME_MUST_BE_TIMEZONE_AWARE")
    return value.astimezone(UTC)


def _seconds(value: timedelta) -> Decimal:
    microseconds = (
        value.days * 86_400 + value.seconds
    ) * 1_000_000 + value.microseconds
    return Decimal(microseconds) / Decimal(1_000_000)


def _validate_grid(
    request: SpotBacktestRunRequest,
    parameter_name: str,
    values: tuple[Decimal, ...],
) -> tuple[Decimal, ...]:
    if (
        type(request) is not SpotBacktestRunRequest
        or type(parameter_name) is not str
        or parameter_name not in PARAMETERS
        or type(values) is not tuple
        or not 3 <= len(values) <= 5
        or any(type(value) is not Decimal or not value.is_finite() for value in values)
        or any(value <= 0 for value in values)
        or any(left >= right for left, right in zip(values, values[1:]))
    ):
        raise SpotSensitivityInputError("INVALID_SENSITIVITY_GRID_OR_PARAMETER")
    parameters = request.parameters
    baseline = (
        parameters.quantity
        if parameter_name == "quantity"
        else _seconds(getattr(parameters, parameter_name))
    )
    if (
        baseline not in values
        or not any(value < baseline for value in values)
        or not any(value > baseline for value in values)
    ):
        raise SpotSensitivityInputError("GRID_MUST_BRACKET_AND_INCLUDE_BASELINE")
    if parameter_name == "quantity":
        if any(value > _MAX_QUANTITY for value in values) or any(
            value % request.execution_policy.quantity_step != 0 for value in values
        ):
            raise SpotSensitivityInputError("INVALID_QUANTITY_GRID_UNIT_OR_STEP")
    elif any(
        value != value.to_integral_value() or value > _MAX_INTERVAL_SECONDS
        for value in values
    ):
        raise SpotSensitivityInputError("INTERVAL_GRID_REQUIRES_BOUNDED_WHOLE_SECONDS")
    return values


def _with_parameter(
    request: SpotBacktestRunRequest, parameter_name: str, value: Decimal
) -> SpotBacktestRunRequest:
    if parameter_name == "quantity":
        parameters = replace(request.parameters, quantity=value)
    else:
        try:
            interval = timedelta(seconds=int(value))
        except (OverflowError, ValueError) as exc:
            raise SpotSensitivityInputError("INTERVAL_GRID_OUT_OF_RANGE") from exc
        if parameter_name == "entry_expiry":
            parameters = replace(request.parameters, entry_expiry=interval)
        elif parameter_name == "holding_interval":
            parameters = replace(request.parameters, holding_interval=interval)
        else:
            parameters = replace(request.parameters, exit_expiry=interval)
    return replace(request, parameters=parameters)


def _stressed_request(
    request: SpotBacktestRunRequest, multiplier: Decimal
) -> SpotBacktestRunRequest:
    profile = request.cost_adapter.profile
    with localcontext(_ARITHMETIC):
        stressed_profile = replace(
            profile,
            taker_fee_bps=profile.taker_fee_bps * multiplier,
            spread_bps=profile.spread_bps * multiplier,
            slippage_bps=profile.slippage_bps * multiplier,
        )
    assumptions = build_spot_cost_assumption_set(
        profile=stressed_profile,
        strategy_version_id=request.parameters.strategy_version_id,
        as_of=max(stressed_profile.available_at, stressed_profile.effective_from),
        liquidity_role=LiquidityRole.TAKER,
    )
    adapter = SpotExecutionCostAdapter(stressed_profile, assumptions)
    return replace(request, cost_assumptions=assumptions, cost_adapter=adapter)


def _metric_value(
    report: SpotPerformanceReport, name: str, unit: str, minimum: int
) -> Decimal | None:
    try:
        metric = report.get(name)
    except (StopIteration, AttributeError):
        return None
    if (
        metric.state is not MetricState.AVAILABLE
        or metric.metric is None
        or metric.metric.unit != unit
        or metric.sample_count < minimum
        or "INSUFFICIENT_SAMPLE" in metric.warnings
        or not metric.metric.value.is_finite()
    ):
        return None
    return metric.metric.value


def _observed_metrics(
    report: SpotPerformanceReport,
) -> tuple[SensitivityMetricsV2 | None, str | None]:
    cumulative_return = _metric_value(
        report, "cumulative_return", "ratio", report.policy.min_return_sample
    )
    drawdown = _metric_value(
        report,
        "maximum_fractional_drawdown",
        "ratio",
        report.policy.min_return_sample,
    )
    trades = _metric_value(
        report, "total_trades", "count", report.policy.min_trade_sample
    )
    if cumulative_return is None or drawdown is None or trades is None:
        return None, "METRICS_SAMPLE_SUFFICIENCY_NOT_MET"
    if trades != trades.to_integral_value() or trades < 0:
        return None, "INVALID_TOTAL_TRADES_METRIC"
    return (
        SensitivityMetricsV2(cumulative_return, drawdown, int(trades)),
        None,
    )


def _source_failure(
    request: SpotBacktestRunRequest,
    bundle: SpotBacktestBundle,
    report: SpotPerformanceReport,
    *,
    as_of: datetime,
    created_at: datetime,
) -> str | None:
    if (
        bundle.outcome is not SpotBacktestOutcome.OBSERVED
        or type(bundle.result) is not BacktestResultV3
        or type(bundle.trace) is not SpotBacktestTrace
        or bundle.trace.replay_request != request.replay_inputs
        or bundle.trace.parameters != request.parameters
        or bundle.trace.policy != request.execution_policy
        or bundle.trace.cost_assumptions != request.cost_assumptions
        or bundle.trace.execution_dataset_sha256 != request.execution_dataset_sha256
        or bundle.trace.execution_manifest_sha256 != request.execution_manifest_sha256
        or tuple(item.archive_pin for item in bundle.trace.decisions)
        != request.archive_pins
    ):
        return "SOURCE_REPLAY_REQUEST_MISMATCH"
    try:
        result = resolve_spot_backtest_result(bundle)
    except (ValueError, TypeError, KeyError, AttributeError):
        return "SOURCE_REPLAY_PROVENANCE_MISMATCH"
    if (
        result != bundle.result
        or result.market_type != "SPOT"
        or result.outcome is not BacktestOutcomeV3.OBSERVED
        or result.data_integrity is not CheckOutcome.PASSED
        or result.point_in_time_correct is not CheckOutcome.PASSED
        or result.operating_mode is not OperatingMode.BACKTEST
        or result.environment
        not in (DeploymentEnvironment.DEV, DeploymentEnvironment.TEST)
        or report.result_id != result.result_id
        or report.result_schema != result.schema_version
        or report.result_sha256 != result.content_sha256
        or report.trace_sha256 != bundle.trace.content_sha256
        or report.dataset_sha256 != result.dataset_sha256
        or report.manifest_sha256 != result.manifest_sha256
        or report.cost_sha256 != result.cost_assumptions.content_sha256
        or report.strategy_sha256 != result.strategy_version.content_sha256
        or report.method != METRICS_METHOD
        or not _report_identity_is_valid(report)
    ):
        return "SOURCE_METRICS_OR_BACKTEST_PROVENANCE_MISMATCH"
    if (
        report.policy.report_timestamp > as_of
        or result.expires_at <= as_of
        or report.policy.report_timestamp < result.created_at
        or created_at < as_of
    ):
        return "STALE_EXPIRED_OR_NON_POINT_IN_TIME_INPUT"
    try:
        recomputed = calculate_spot_performance_metrics(
            bundle,
            report.policy,
            price_path=bundle.execution_dataset if report.equity else None,
        )
    except (MetricsInputError, ValueError, TypeError, KeyError, AttributeError):
        return "SOURCE_METRICS_RECOMPUTATION_FAILED"
    if recomputed != report:
        return "SOURCE_METRICS_RECOMPUTATION_MISMATCH"
    return None


def _scenario_key(kind: SensitivityScenarioKindV2, value: Decimal) -> str:
    return f"{kind.value.lower()}:{value}"


def _scenario_reference(
    bundle: SpotBacktestBundle,
) -> tuple[
    ValidationArtifactReferenceV2 | None,
    ValidationArtifactReferenceV2 | None,
]:
    if type(bundle.result) is not BacktestResultV3 or bundle.trace is None:
        return None, None
    return (
        _reference("C-027", bundle.result.result_id, "3", bundle.result.content_sha256),
        bundle.result.trace,
    )


def _cost_reference(assumptions) -> ValidationArtifactReferenceV2:
    return _reference(
        "C-027",
        assumptions.assumption_set_id,
        "2",
        assumptions.content_sha256,
    )


def _failed_scenario(
    key: str,
    kind: SensitivityScenarioKindV2,
    value: Decimal,
    multiplier: Decimal,
    cost_assumptions,
    reason: str,
    *,
    bundle: SpotBacktestBundle | None = None,
    report: SpotPerformanceReport | None = None,
    cost_reference: ValidationArtifactReferenceV2 | None = None,
) -> SensitivityScenarioV2:
    backtest = trace = None
    if bundle is not None:
        backtest, trace = _scenario_reference(bundle)
    return SensitivityScenarioV2(
        key,
        kind,
        value,
        multiplier,
        SensitivityOutcomeV2.FAILED,
        backtest,
        trace,
        cost_reference or _cost_reference(cost_assumptions),
        report.report_id if report is not None else None,
        report.content_sha256 if report is not None else None,
        report.input_sha256 if report is not None else None,
        None,
        None,
        None,
        False,
        False,
        False,
        (reason,),
        bundle.result.as_of
        if bundle is not None and type(bundle.result) is BacktestResultV3
        else None,
        bundle.result.created_at
        if bundle is not None and type(bundle.result) is BacktestResultV3
        else None,
        bundle.result.expires_at
        if bundle is not None and type(bundle.result) is BacktestResultV3
        else None,
        report.policy.report_timestamp if report is not None else None,
    )


def _validate_scenario_replay(
    bundle: SpotBacktestBundle,
    request: SpotBacktestRunRequest,
    source: SpotBacktestBundle,
) -> str | None:
    if (
        bundle.outcome is not SpotBacktestOutcome.OBSERVED
        or type(bundle.result) is not BacktestResultV3
        or type(bundle.trace) is not SpotBacktestTrace
    ):
        return "SCENARIO_REPLAY_NOT_OBSERVED"
    try:
        result = resolve_spot_backtest_result(bundle)
        source_result = resolve_spot_backtest_result(source)
    except (ValueError, TypeError, KeyError, AttributeError):
        return "SCENARIO_REPLAY_PROVENANCE_MISMATCH"
    trace = bundle.trace
    source_trace = source.trace
    if source_trace is None:
        return "SOURCE_TRACE_MISSING"
    if (
        result != bundle.result
        or result.market_type != "SPOT"
        or result.outcome is not BacktestOutcomeV3.OBSERVED
        or result.data_integrity is not CheckOutcome.PASSED
        or result.point_in_time_correct is not CheckOutcome.PASSED
        or trace.replay_request != request.replay_inputs
        or trace.parameters != request.parameters
        or trace.policy != request.execution_policy
        or trace.cost_assumptions != request.cost_assumptions
        or trace.execution_dataset_sha256 != request.execution_dataset_sha256
        or trace.execution_manifest_sha256 != request.execution_manifest_sha256
        or trace.input_journal_sha256 != source_trace.input_journal_sha256
        or trace.strategy != source_trace.strategy
        or result.strategy_version != source_result.strategy_version
        or result.dataset_sha256 != source_result.dataset_sha256
        or result.manifest_sha256 != source_result.manifest_sha256
        or result.period_start != source_result.period_start
        or result.period_end != source_result.period_end
        or result.timeframe != source_result.timeframe
        or result.venue != source_result.venue
        or result.instrument_id != source_result.instrument_id
        or result.dataset.dataset_id != source_result.dataset.dataset_id
        or result.dataset.version != source_result.dataset.version
        or result.dataset.lineage_sha256 != source_result.dataset.lineage_sha256
    ):
        return "SCENARIO_UNVARIED_INPUT_MISMATCH"
    return None


def _evaluate_scenario(
    *,
    bundle: SpotBacktestBundle,
    report: SpotPerformanceReport | None,
    key: str,
    kind: SensitivityScenarioKindV2,
    value: Decimal,
    multiplier: Decimal,
    request: SpotBacktestRunRequest,
    source: SpotBacktestBundle,
    source_report: SpotPerformanceReport,
    baseline_metrics: SensitivityMetricsV2 | None,
) -> SensitivityScenarioV2:
    provenance_reason = _validate_scenario_replay(bundle, request, source)
    if provenance_reason is not None:
        return _failed_scenario(
            key,
            kind,
            value,
            multiplier,
            request.cost_assumptions,
            provenance_reason,
            bundle=bundle,
            report=report,
        )
    result = bundle.result
    trace = bundle.trace
    assert result is not None and trace is not None
    expected_cost = request.cost_assumptions
    if report is None:
        return _failed_scenario(
            key,
            kind,
            value,
            multiplier,
            expected_cost,
            "SCENARIO_METRICS_RECOMPUTATION_FAILED",
            bundle=bundle,
        )
    if (
        trace.cost_assumptions != expected_cost
        or result.cost_assumptions.content_sha256 != expected_cost.content_sha256
        or report.result_id != result.result_id
        or report.result_sha256 != result.content_sha256
        or report.trace_sha256 != trace.content_sha256
        or report.dataset_sha256 != result.dataset_sha256
        or report.manifest_sha256 != result.manifest_sha256
        or report.cost_sha256 != expected_cost.content_sha256
        or report.strategy_sha256 != result.strategy_version.content_sha256
        or report.policy != source_report.policy
        or report.method != METRICS_METHOD
        or not _report_identity_is_valid(report)
    ):
        return _failed_scenario(
            key,
            kind,
            value,
            multiplier,
            expected_cost,
            "SCENARIO_METRICS_PROVENANCE_MISMATCH",
            bundle=bundle,
            report=report,
        )
    metrics, metric_reason = _observed_metrics(report)
    backtest, trace_reference = _scenario_reference(bundle)
    if backtest is None or trace_reference is None:
        return _failed_scenario(
            key, kind, value, multiplier, expected_cost, "SCENARIO_RESULT_MISSING"
        )
    if metrics is None:
        return SensitivityScenarioV2(
            key,
            kind,
            value,
            multiplier,
            SensitivityOutcomeV2.INCONCLUSIVE,
            backtest,
            trace_reference,
            _cost_reference(expected_cost),
            report.report_id,
            report.content_sha256,
            report.input_sha256,
            None,
            None,
            None,
            False,
            False,
            False,
            (metric_reason or "METRICS_SAMPLE_SUFFICIENCY_NOT_MET",),
            result.as_of,
            result.created_at,
            result.expires_at,
            report.policy.report_timestamp,
        )
    if baseline_metrics is None:
        return SensitivityScenarioV2(
            key,
            kind,
            value,
            multiplier,
            SensitivityOutcomeV2.INCONCLUSIVE,
            backtest,
            trace_reference,
            _cost_reference(expected_cost),
            report.report_id,
            report.content_sha256,
            report.input_sha256,
            metrics,
            None,
            None,
            False,
            False,
            False,
            ("BASELINE_METRICS_SAMPLE_SUFFICIENCY_NOT_MET",),
            result.as_of,
            result.created_at,
            result.expires_at,
            report.policy.report_timestamp,
        )
    with localcontext(_ARITHMETIC):
        return_delta = metrics.cumulative_return - baseline_metrics.cumulative_return
        drawdown_delta = (
            metrics.maximum_fractional_drawdown
            - baseline_metrics.maximum_fractional_drawdown
        )
    return SensitivityScenarioV2(
        key,
        kind,
        value,
        multiplier,
        SensitivityOutcomeV2.OBSERVED,
        backtest,
        trace_reference,
        _cost_reference(expected_cost),
        report.report_id,
        report.content_sha256,
        report.input_sha256,
        metrics,
        return_delta,
        drawdown_delta,
        return_delta < 0,
        drawdown_delta > 0,
        False,
        (),
        result.as_of,
        result.created_at,
        result.expires_at,
        report.policy.report_timestamp,
    )


def _crossings(
    scenarios: tuple[SensitivityScenarioV2, ...],
    kind: SensitivityScenarioKindV2,
    baseline_value: Decimal,
) -> tuple[SensitivityZeroCrossingV2, ...]:
    if kind is SensitivityScenarioKindV2.COST:
        baseline = next(
            item
            for item in scenarios
            if item.kind is SensitivityScenarioKindV2.PARAMETER
            and item.parameter_value == baseline_value
        )
        ordered = (
            baseline,
            *(
                item
                for item in scenarios
                if item.kind is SensitivityScenarioKindV2.COST
            ),
        )
    else:
        ordered = tuple(item for item in scenarios if item.kind is kind)
    result: list[SensitivityZeroCrossingV2] = []
    for left, right in zip(ordered, ordered[1:]):
        if left.metrics is None or right.metrics is None:
            continue
        first = left.metrics.cumulative_return
        second = right.metrics.cumulative_return
        if first != second and ((first <= 0 <= second) or (second <= 0 <= first)):
            result.append(SensitivityZeroCrossingV2(kind, left.key, right.key))
    return tuple(result)


def _finalize_local_peaks(
    scenarios: tuple[SensitivityScenarioV2, ...],
) -> tuple[SensitivityScenarioV2, ...]:
    parameter_scenarios = tuple(
        item for item in scenarios if item.kind is SensitivityScenarioKindV2.PARAMETER
    )
    peaks = {
        current.key
        for left, current, right in zip(
            parameter_scenarios,
            parameter_scenarios[1:],
            parameter_scenarios[2:],
            strict=False,
        )
        if left.metrics is not None
        and current.metrics is not None
        and right.metrics is not None
        and current.metrics.cumulative_return > left.metrics.cumulative_return
        and current.metrics.cumulative_return > right.metrics.cumulative_return
    }
    return tuple(
        replace(item, local_peak=item.key in peaks)
        if item.kind is SensitivityScenarioKindV2.PARAMETER
        else item
        for item in scenarios
    )


def _result(
    *,
    request: SpotBacktestRunRequest,
    source_bundle: SpotBacktestBundle,
    source_report: SpotPerformanceReport,
    parameter_name: str,
    parameter_grid: tuple[Decimal, ...],
    scenarios: tuple[SensitivityScenarioV2, ...],
    outcome: SensitivityOutcomeV2,
    reasons: tuple[str, ...],
    as_of: datetime,
    created_at: datetime,
) -> SensitivityResultV2:
    result = source_bundle.result
    trace = source_bundle.trace
    assert result is not None and trace is not None
    baseline = (
        request.parameters.quantity
        if parameter_name == "quantity"
        else _seconds(getattr(request.parameters, parameter_name))
    )
    scenarios = _finalize_local_peaks(scenarios)
    crossings = _crossings(
        scenarios, SensitivityScenarioKindV2.PARAMETER, baseline
    ) + _crossings(scenarios, SensitivityScenarioKindV2.COST, baseline)
    result_values = {
        "outcome": outcome,
        "parameter_name": parameter_name,
        "parameter_unit": (
            request.execution_policy.quantity_unit
            if parameter_name == "quantity"
            else PARAMETERS[parameter_name]
        ),
        "quantity_unit": request.execution_policy.quantity_unit,
        "baseline_value": baseline,
        "parameter_grid": parameter_grid,
        "cost_multipliers": COST_MULTIPLIERS,
        "input_request_sha256": canonical_sha256(request),
        "source_bundle_sha256": source_bundle.content_sha256,
        "source_backtest": _reference(
            "C-027", result.result_id, "3", result.content_sha256
        ),
        "source_trace": result.trace,
        "source_metrics_report_id": source_report.report_id,
        "source_metrics_report_sha256": source_report.content_sha256,
        "strategy_version": result.strategy_version,
        "source_cost_assumptions": result.cost_assumptions,
        "source_as_of": result.as_of,
        "source_created_at": result.created_at,
        "source_expires_at": result.expires_at,
        "dataset_id": result.dataset.dataset_id,
        "dataset_version": result.dataset.version,
        "dataset_sha256": result.dataset_sha256,
        "dataset_lineage_sha256": result.dataset.lineage_sha256,
        "manifest_sha256": result.manifest_sha256,
        "venue": result.venue,
        "instrument_id": result.instrument_id,
        "timeframe": result.timeframe,
        "period_start": result.period_start,
        "period_end": result.period_end,
        "metrics_method": source_report.method,
        "metrics_policy": SensitivityMetricsPolicyV2.from_policy(source_report.policy),
        "metrics_policy_sha256": canonical_sha256(source_report.policy),
        "scenarios": scenarios,
        "zero_crossings": crossings,
        "assumptions": ASSUMPTIONS,
        "warnings": WARNINGS if outcome is SensitivityOutcomeV2.OBSERVED else (),
        "reasons": reasons,
        "as_of": as_of,
        "created_at": created_at,
    }
    return SensitivityResultV2.build(**result_values)


async def run_spot_sensitivity(
    *,
    request: SpotBacktestRunRequest,
    observed_bundle: SpotBacktestBundle,
    observed_report: SpotPerformanceReport,
    parameter_name: str,
    parameter_grid: tuple[Decimal, ...],
    session: AsyncSession,
    strategy_registry: StrategyVersionResolver,
    lineage_store: SqlAlchemyLineageStore,
    as_of: datetime,
    created_at: datetime,
) -> SensitivityResultV2:
    """Measure a frozen grid and independent cost stresses; never selects a value."""
    if (
        type(observed_bundle) is not SpotBacktestBundle
        or type(observed_report) is not SpotPerformanceReport
        or type(observed_bundle.result) is not BacktestResultV3
        or type(observed_bundle.trace) is not SpotBacktestTrace
    ):
        raise SpotSensitivityInputError("EXACT_OBSERVED_SPOT_BACKTEST_REQUIRED")
    grid = _validate_grid(request, parameter_name, parameter_grid)
    as_of = _time(as_of)
    created_at = _time(created_at)
    if created_at < as_of:
        raise SpotSensitivityInputError("CREATION_TIME_PRECEDES_AS_OF")
    baseline_value = (
        request.parameters.quantity
        if parameter_name == "quantity"
        else _seconds(getattr(request.parameters, parameter_name))
    )
    source_error = _source_failure(
        request,
        observed_bundle,
        observed_report,
        as_of=as_of,
        created_at=created_at,
    )
    scenario_specs = tuple(
        (
            _scenario_key(SensitivityScenarioKindV2.PARAMETER, value),
            SensitivityScenarioKindV2.PARAMETER,
            value,
            Decimal("1"),
        )
        for value in grid
    ) + tuple(
        (
            _scenario_key(SensitivityScenarioKindV2.COST, multiplier),
            SensitivityScenarioKindV2.COST,
            baseline_value,
            multiplier,
        )
        for multiplier in COST_MULTIPLIERS[1:]
    )
    if source_error is not None:
        failed_scenarios = []
        for key, kind, value, multiplier in scenario_specs:
            failed_request = (
                _stressed_request(request, multiplier)
                if kind is SensitivityScenarioKindV2.COST
                else request
            )
            is_baseline = (
                kind is SensitivityScenarioKindV2.PARAMETER and value == baseline_value
            )
            failed_scenarios.append(
                _failed_scenario(
                    key,
                    kind,
                    value,
                    multiplier,
                    failed_request.cost_assumptions,
                    source_error,
                    bundle=observed_bundle if is_baseline else None,
                    report=observed_report if is_baseline else None,
                    cost_reference=(
                        observed_bundle.result.cost_assumptions if is_baseline else None
                    ),
                )
            )
        failed = tuple(failed_scenarios)
        return _result(
            request=request,
            source_bundle=observed_bundle,
            source_report=observed_report,
            parameter_name=parameter_name,
            parameter_grid=grid,
            scenarios=failed,
            outcome=SensitivityOutcomeV2.FAILED,
            reasons=(source_error,),
            as_of=as_of,
            created_at=created_at,
        )

    baseline_metrics, baseline_reason = _observed_metrics(observed_report)
    reports: dict[
        str,
        tuple[
            SpotBacktestBundle,
            SpotPerformanceReport | None,
            SpotBacktestRunRequest,
        ],
    ] = {}
    baseline_key = _scenario_key(SensitivityScenarioKindV2.PARAMETER, baseline_value)
    reports[baseline_key] = (observed_bundle, observed_report, request)
    for value in grid:
        if value == baseline_value:
            continue
        scenario_request = _with_parameter(request, parameter_name, value)
        bundle = await run_spot_backtest(
            request=scenario_request,
            session=session,
            strategy_registry=strategy_registry,
            lineage_store=lineage_store,
        )
        if bundle.outcome is not SpotBacktestOutcome.OBSERVED:
            reports[_scenario_key(SensitivityScenarioKindV2.PARAMETER, value)] = (
                bundle,
                None,
                scenario_request,
            )
            continue
        try:
            report = calculate_spot_performance_metrics(
                bundle,
                observed_report.policy,
                price_path=bundle.execution_dataset if observed_report.equity else None,
            )
        except (MetricsInputError, ValueError, TypeError, KeyError, DecimalException):
            report = None
        reports[_scenario_key(SensitivityScenarioKindV2.PARAMETER, value)] = (
            bundle,
            report,
            scenario_request,
        )
    for multiplier in COST_MULTIPLIERS[1:]:
        scenario_request = _stressed_request(request, multiplier)
        bundle = await run_spot_backtest(
            request=scenario_request,
            session=session,
            strategy_registry=strategy_registry,
            lineage_store=lineage_store,
        )
        if bundle.outcome is not SpotBacktestOutcome.OBSERVED:
            reports[_scenario_key(SensitivityScenarioKindV2.COST, multiplier)] = (
                bundle,
                None,
                scenario_request,
            )
            continue
        try:
            report = calculate_spot_performance_metrics(
                bundle,
                observed_report.policy,
                price_path=bundle.execution_dataset if observed_report.equity else None,
            )
        except (MetricsInputError, ValueError, TypeError, KeyError, DecimalException):
            report = None
        reports[_scenario_key(SensitivityScenarioKindV2.COST, multiplier)] = (
            bundle,
            report,
            scenario_request,
        )

    scenarios: list[SensitivityScenarioV2] = []
    for key, kind, value, multiplier in scenario_specs:
        bundle, report, scenario_request = reports[key]
        cost = scenario_request.cost_assumptions
        if key == baseline_key:
            scenario = _evaluate_scenario(
                bundle=bundle,
                report=report,
                key=key,
                kind=kind,
                value=value,
                multiplier=multiplier,
                request=scenario_request,
                source=observed_bundle,
                source_report=observed_report,
                baseline_metrics=baseline_metrics,
            )
        elif bundle.outcome is not SpotBacktestOutcome.OBSERVED:
            scenario = _failed_scenario(
                key,
                kind,
                value,
                multiplier,
                cost,
                "SCENARIO_REPLAY_NOT_OBSERVED",
                bundle=bundle,
            )
        else:
            scenario = _evaluate_scenario(
                bundle=bundle,
                report=report,
                key=key,
                kind=kind,
                value=value,
                multiplier=multiplier,
                request=scenario_request,
                source=observed_bundle,
                source_report=observed_report,
                baseline_metrics=baseline_metrics,
            )
        scenarios.append(scenario)
    scenario_tuple = tuple(scenarios)
    if any(item.outcome is SensitivityOutcomeV2.FAILED for item in scenario_tuple):
        outcome = SensitivityOutcomeV2.FAILED
    elif baseline_metrics is None or any(
        item.outcome is SensitivityOutcomeV2.INCONCLUSIVE for item in scenario_tuple
    ):
        outcome = SensitivityOutcomeV2.INCONCLUSIVE
    else:
        outcome = SensitivityOutcomeV2.OBSERVED
    reasons = tuple(
        f"{item.key}:{reason}" for item in scenario_tuple for reason in item.reasons
    )
    if baseline_reason is not None and baseline_reason not in reasons:
        reasons = (*reasons, f"{baseline_key}:{baseline_reason}")
    return _result(
        request=request,
        source_bundle=observed_bundle,
        source_report=observed_report,
        parameter_name=parameter_name,
        parameter_grid=grid,
        scenarios=scenario_tuple,
        outcome=outcome,
        reasons=reasons if outcome is not SensitivityOutcomeV2.OBSERVED else (),
        as_of=as_of,
        created_at=created_at,
    )


__all__ = ["SpotSensitivityInputError", "run_spot_sensitivity"]
