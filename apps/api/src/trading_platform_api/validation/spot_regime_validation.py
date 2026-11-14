"""Frozen offline Spot regime observations over archived backtest evidence."""

from __future__ import annotations

from dataclasses import dataclass, fields
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from trading_platform_api.analysis.contracts import MarketRegime
from trading_platform_api.analysis.spot_market_regime import (
    SPOT_MARKET_REGIME_METHOD_VERSION,
    SPOT_MARKET_REGIME_PROFILE_VERSION,
)
from trading_platform_api.analysis.versioned_contracts import EvidenceItemV2
from trading_platform_api.analysis.versioned_contracts_v4 import (
    AnalysisSnapshotV4,
    AnalysisSnapshotReferenceV4,
)
from trading_platform_api.analysis.versioned_contracts_v5 import MarketContextV5
from trading_platform_api.contracts.serialization import canonical_sha256
from trading_platform_api.lineage.store import SqlAlchemyLineageStore
from trading_platform_api.market_data.ohlcv import _TIMEFRAMES
from trading_platform_api.strategy.contracts_v2 import StrategyVersionV2
from trading_platform_api.strategy.registry import strategy_version_content_sha256
from trading_platform_api.validation.contracts import CheckOutcome
from trading_platform_api.validation.contracts_v2 import ValidationArtifactReferenceV2
from trading_platform_api.validation.contracts_v3 import (
    BacktestOutcomeV3,
    BacktestResultV3,
)
from trading_platform_api.validation.regime_contracts_v2 import (
    DecisionAttributionRuleV2,
    RegimeContextCoverageV2,
    RegimeContextKeyV2,
    RegimeCoverageStateV2,
    RegimeMetricObservationV2,
    RegimeMetricStateV2,
    RegimeMetricsPolicyV2,
    RegimeObservationStateV2,
    SpotRegimeObservationV2,
    SpotRegimeValidationResultV2,
    WARNINGS as REGIME_WARNINGS,
)
from trading_platform_api.validation.spot_backtest import (
    SpotBacktestBundle,
    SpotBacktestDecision,
    SpotBacktestOutcome,
    SpotBacktestRunRequest,
    SpotBacktestTrace,
    _trace_payload,
    resolve_spot_backtest_result,
    run_spot_backtest,
)
from trading_platform_api.validation.spot_metrics import (
    METHOD as METRICS_METHOD,
)
from trading_platform_api.validation.spot_metrics import (
    MetricsInputError,
    MetricsPolicy,
    MetricState,
    SpotPerformanceReport,
    calculate_spot_performance_metrics,
)
from trading_platform_api.validation.spot_oos import _request_digest
from trading_platform_api.validation.spot_replay_inputs import (
    SpotReplayDecisionRecord,
    StrategyVersionResolver,
)


class SpotRegimeValidationInputError(ValueError):
    """The frozen analysis plan is malformed or incompatible."""


@dataclass(frozen=True, slots=True)
class SpotRegimeRunInput:
    request: SpotBacktestRunRequest
    metrics_policy: MetricsPolicy

    def __post_init__(self) -> None:
        if (
            type(self.request) is not SpotBacktestRunRequest
            or type(self.metrics_policy) is not MetricsPolicy
        ):
            raise SpotRegimeValidationInputError(
                "EXACT_REQUEST_AND_METRICS_POLICY_REQUIRED"
            )


@dataclass(frozen=True, slots=True)
class SpotRegimeValidationPlan:
    runs: tuple[SpotRegimeRunInput, ...]
    strategy_version: StrategyVersionV2
    required_contexts: tuple[RegimeContextKeyV2, ...]
    as_of: datetime
    created_at: datetime

    def __post_init__(self) -> None:
        if (
            type(self.runs) is not tuple
            or not 1 <= len(self.runs) <= 32
            or any(type(item) is not SpotRegimeRunInput for item in self.runs)
        ):
            raise SpotRegimeValidationInputError("INVALID_FROZEN_RUN_PLAN")
        if (
            type(self.strategy_version) is not StrategyVersionV2
            or strategy_version_content_sha256(self.strategy_version)
            != self.strategy_version.content_sha256
        ):
            raise SpotRegimeValidationInputError("INVALID_IMMUTABLE_STRATEGY_VERSION")
        if (
            type(self.required_contexts) is not tuple
            or not 1 <= len(self.required_contexts) <= 32
            or any(
                type(item) is not RegimeContextKeyV2 for item in self.required_contexts
            )
            or len(set(self.required_contexts)) != len(self.required_contexts)
        ):
            raise SpotRegimeValidationInputError("INVALID_REQUIRED_CONTEXT_PLAN")
        as_of = _time("as_of", self.as_of)
        created_at = _time("created_at", self.created_at)
        if created_at < as_of:
            raise SpotRegimeValidationInputError("CREATION_TIME_PRECEDES_AS_OF")
        object.__setattr__(self, "as_of", as_of)
        object.__setattr__(self, "created_at", created_at)
        strategy_id = self.strategy_version.strategy_version_id
        strategy_sha = self.strategy_version.content_sha256
        request_digests = tuple(_request_digest(item.request) for item in self.runs)
        if len(set(request_digests)) != len(request_digests):
            raise SpotRegimeValidationInputError("DUPLICATE_REQUEST_IDENTITY")
        first_policy = self.runs[0].metrics_policy
        for item, request_digest in zip(self.runs, request_digests, strict=True):
            request = item.request
            policy = item.metrics_policy
            timeframe = request.replay_inputs.scope.timeframe
            if (
                request.parameters.strategy_version_id != strategy_id
                or request.parameters.strategy_sha256 != strategy_sha
            ):
                raise SpotRegimeValidationInputError("MIXED_STRATEGY_VERSION")
            if (
                policy.method != METRICS_METHOD
                or policy.version != "1"
                or policy.quote_unit != request.execution_policy.quote_unit
                or policy.interval_seconds != _TIMEFRAMES.get(timeframe)
            ):
                raise SpotRegimeValidationInputError(
                    f"INCOMPATIBLE_METRICS_POLICY:{request_digest}"
                )
            if (
                policy.method != first_policy.method
                or policy.version != first_policy.version
                or policy.min_trade_sample != first_policy.min_trade_sample
                or policy.min_return_sample != first_policy.min_return_sample
            ):
                raise SpotRegimeValidationInputError(
                    "MIXED_METRICS_METHOD_OR_SAMPLE_POLICY"
                )
            if (
                request.created_at > as_of
                or request.expires_at <= as_of
                or policy.report_timestamp > as_of
            ):
                raise SpotRegimeValidationInputError(
                    "INVALID_ANALYSIS_INPUT_CHRONOLOGY"
                )


def _time(name: str, value: datetime) -> datetime:
    if type(value) is not datetime or value.utcoffset() is None:
        raise SpotRegimeValidationInputError(f"TIMEZONE_AWARE_{name.upper()}_REQUIRED")
    return value.astimezone(UTC)


def _bundle_digest(bundle: SpotBacktestBundle) -> str:
    return canonical_sha256(
        {
            "method": "spot-strategy-backtest-v1",
            "outcome": bundle.outcome,
            "reason_codes": bundle.reason_codes,
            "input_journal": bundle.input_journal,
            "execution_dataset": bundle.execution_dataset,
            "trace": None if bundle.trace is None else _trace_payload(bundle.trace),
            "result": bundle.result,
            "artifacts": bundle.artifacts,
        }
    )


def _report_digest(report: SpotPerformanceReport) -> str:
    return canonical_sha256(
        {
            item.name: getattr(report, item.name)
            for item in fields(report)
            if item.name not in {"report_id", "content_sha256"}
        }
    )


def _reference(kind: str, identity: UUID, version: str, digest: str):
    return ValidationArtifactReferenceV2(kind, identity, version, digest)


def _metric_observations(
    report: SpotPerformanceReport | None, policy: MetricsPolicy
) -> tuple[RegimeMetricObservationV2, ...]:
    specifications = (
        ("cumulative_return", "ratio", policy.min_return_sample),
        ("maximum_fractional_drawdown", "ratio", policy.min_return_sample),
        ("total_trades", "count", policy.min_trade_sample),
    )
    observations: list[RegimeMetricObservationV2] = []
    for name, unit, minimum in specifications:
        if report is None:
            observations.append(
                RegimeMetricObservationV2(
                    name,
                    RegimeMetricStateV2.UNAVAILABLE,
                    None,
                    unit,
                    0,
                    False,
                    "METRICS_REPORT_UNAVAILABLE",
                    (),
                )
            )
            continue
        try:
            metric = report.get(name)
        except (StopIteration, AttributeError):
            observations.append(
                RegimeMetricObservationV2(
                    name,
                    RegimeMetricStateV2.UNAVAILABLE,
                    None,
                    unit,
                    0,
                    False,
                    "METRIC_NOT_PROVIDED",
                    (),
                )
            )
            continue
        state = RegimeMetricStateV2(metric.state.value)
        value = metric.metric.value if metric.metric is not None else None
        valid = (
            metric.metric is not None
            and metric.metric.name == name
            and metric.metric.unit == unit
            and value is not None
            and value.is_finite()
        )
        if state is RegimeMetricStateV2.AVAILABLE and not valid:
            state = RegimeMetricStateV2.UNAVAILABLE
            value = None
            reason = "METRIC_VALUE_OR_UNIT_INVALID"
        else:
            reason = metric.reason
        sufficient = (
            state is RegimeMetricStateV2.AVAILABLE
            and metric.sample_count >= minimum
            and "INSUFFICIENT_SAMPLE" not in metric.warnings
        )
        observations.append(
            RegimeMetricObservationV2(
                name,
                state,
                value,
                unit,
                metric.sample_count,
                sufficient,
                reason,
                metric.warnings,
            )
        )
    return tuple(observations)


def _failed_observation(
    index: int,
    run: SpotRegimeRunInput,
    strategy_ref: ValidationArtifactReferenceV2,
    reason: str,
    *,
    state: RegimeObservationStateV2 = RegimeObservationStateV2.FAILED,
    bundle: SpotBacktestBundle | None = None,
    report: SpotPerformanceReport | None = None,
) -> SpotRegimeObservationV2:
    request = run.request
    result = bundle.result if bundle is not None else None
    trace = bundle.trace if bundle is not None else None
    resolved = type(result) is BacktestResultV3 and type(trace) is SpotBacktestTrace
    reasons = tuple(
        dict.fromkeys((reason, *(bundle.reason_codes if bundle is not None else ())))
    )
    metrics_policy = RegimeMetricsPolicyV2.from_policy(run.metrics_policy)
    return SpotRegimeObservationV2(
        index,
        state,
        reasons,
        _request_digest(request),
        canonical_sha256(
            {
                "parameters": {
                    "strategy_version_id": request.parameters.strategy_version_id,
                    "strategy_sha256": request.parameters.strategy_sha256,
                    "quantity": request.parameters.quantity,
                    "entry_expiry_microseconds": _duration_microseconds(
                        request.parameters.entry_expiry
                    ),
                    "holding_interval_microseconds": _duration_microseconds(
                        request.parameters.holding_interval
                    ),
                    "exit_expiry_microseconds": _duration_microseconds(
                        request.parameters.exit_expiry
                    ),
                    "maximum_entries": request.parameters.maximum_entries,
                    "partial_fill_policy": request.parameters.partial_fill_policy,
                }
            }
        ),
        canonical_sha256(request.execution_policy),
        metrics_policy,
        canonical_sha256(metrics_policy),
        _reference("C-027", result.result_id, "3", result.content_sha256)
        if resolved
        else None,
        result.trace if resolved else None,
        _bundle_digest(bundle) if resolved else None,
        report.report_id if report is not None else None,
        report.content_sha256 if report is not None else None,
        report.input_sha256 if report is not None else None,
        strategy_ref,
        _reference(
            "C-027",
            request.cost_assumptions.assumption_set_id,
            "2",
            request.cost_assumptions.content_sha256,
        ),
        request.cost_adapter.adapter_reference,
        result.dataset.dataset_id if resolved else None,
        result.dataset.version if resolved else None,
        request.execution_dataset_sha256,
        result.dataset.lineage_sha256 if resolved else None,
        request.execution_manifest_sha256,
        request.execution_policy.quote_unit,
        request.execution_policy.quantity_unit,
        request.execution_policy.venue,
        request.execution_policy.asset,
        request.execution_policy.instrument_id,
        request.execution_policy.timeframe,
        result.as_of if resolved else None,
        result.created_at if resolved else None,
        result.expires_at if resolved else None,
        report.policy.report_timestamp if report is not None else None,
        request.execution_policy.period_start,
        request.execution_policy.period_end,
        None,
        None,
        None,
        None,
        None,
        None,
        None,
        _metric_observations(report, run.metrics_policy),
    )


def _duration_microseconds(value) -> int:
    return (value.days * 86_400 + value.seconds) * 1_000_000 + value.microseconds


def _replay_failure_state(bundle: SpotBacktestBundle) -> RegimeObservationStateV2:
    invalid_markers = (
        "MISMATCH",
        "INVALID",
        "FAILED",
        "UNSUPPORTED",
        "STALE",
        "EXPIRED",
    )
    return (
        RegimeObservationStateV2.FAILED
        if any(
            marker in reason
            for reason in bundle.reason_codes
            for marker in invalid_markers
        )
        else RegimeObservationStateV2.INCONCLUSIVE
    )


def _source_failure(
    request: SpotBacktestRunRequest,
    policy: MetricsPolicy,
    bundle: SpotBacktestBundle,
    report: SpotPerformanceReport,
    *,
    as_of: datetime,
) -> str | None:
    if (
        bundle.outcome is not SpotBacktestOutcome.OBSERVED
        or type(bundle.result) is not BacktestResultV3
        or type(bundle.trace) is not SpotBacktestTrace
        or bundle.input_journal is None
        or bundle.execution_dataset is None
    ):
        return "REPLAY_NOT_OBSERVED"
    report = None
    try:
        result = resolve_spot_backtest_result(bundle)
    except (ValueError, TypeError, KeyError, AttributeError):
        return "REPLAY_PROVENANCE_MISMATCH"
    trace = bundle.trace
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
        or trace.cost_adapter != request.cost_adapter.adapter_reference
        or trace.execution_dataset_sha256 != request.execution_dataset_sha256
        or trace.execution_manifest_sha256 != request.execution_manifest_sha256
        or tuple(item.archive_pin for item in trace.decisions) != request.archive_pins
        or (result.as_of, result.created_at, result.expires_at)
        != (request.result_as_of, request.created_at, request.expires_at)
        or result.strategy_version.artifact_id != request.parameters.strategy_version_id
        or result.strategy_version.content_sha256 != request.parameters.strategy_sha256
        or result.dataset_sha256 != request.execution_dataset_sha256
        or result.manifest_sha256 != request.execution_manifest_sha256
    ):
        return "REPLAY_REQUEST_OR_RESULT_PIN_MISMATCH"
    if (
        report.policy != policy
        or report.method != METRICS_METHOD
        or report.result_id != result.result_id
        or report.result_schema != result.schema_version
        or report.result_sha256 != result.content_sha256
        or report.trace_sha256 != trace.content_sha256
        or report.dataset_sha256 != result.dataset_sha256
        or report.manifest_sha256 != result.manifest_sha256
        or report.cost_sha256 != result.cost_assumptions.content_sha256
        or report.strategy_sha256 != result.strategy_version.content_sha256
        or report.content_sha256 != _report_digest(report)
    ):
        return "METRICS_OR_BACKTEST_PROVENANCE_MISMATCH"
    if (
        result.created_at > as_of
        or result.expires_at <= as_of
        or result.as_of > result.created_at
        or report.policy.report_timestamp < result.created_at
        or report.policy.report_timestamp > as_of
    ):
        return "STALE_EXPIRED_OR_NON_POINT_IN_TIME_SOURCE"
    return None


def _attribution(
    request: SpotBacktestRunRequest,
    bundle: SpotBacktestBundle,
) -> tuple[
    DecisionAttributionRuleV2,
    SpotBacktestDecision,
    RegimeContextKeyV2,
    ValidationArtifactReferenceV2,
    AnalysisSnapshotReferenceV4,
    object,
    tuple[object, ...],
]:
    trace = bundle.trace
    journal = bundle.input_journal
    if (
        type(trace) is not SpotBacktestTrace
        or journal is None
        or not trace.decisions
        or len(trace.decisions) != len(journal.decisions)
    ):
        raise SpotRegimeValidationInputError("DECISION_JOURNAL_CLOSURE_INVALID")
    entry_orders = trace.entry_trace.orders
    if len(entry_orders) > 1:
        raise SpotRegimeValidationInputError("MULTIPLE_ENTRY_ORDERS_UNSUPPORTED")
    if entry_orders:
        order_id = entry_orders[0].order_id
        matching = tuple(item for item in trace.decisions if item.order_id == order_id)
        if len(matching) != 1:
            raise SpotRegimeValidationInputError("ENTRY_ORDER_DECISION_MISMATCH")
        decision = matching[0]
        rule = DecisionAttributionRuleV2.ENTRY_ORDER_DECISION
    else:
        decision = trace.decisions[0]
        rule = DecisionAttributionRuleV2.NO_ENTRY_FIRST_DECISION
    try:
        index = trace.decisions.index(decision)
        record = journal.decisions[index]
        closure = decision.archived_analysis
        context = closure.debate.market_context
        manifest = closure.manifest
        regime = context.regime
        if (
            type(decision) is not SpotBacktestDecision
            or type(record) is not SpotReplayDecisionRecord
            or type(context) is not MarketContextV5
            or type(manifest) is not AnalysisSnapshotV4
            or type(regime) is not MarketRegime
        ):
            raise SpotRegimeValidationInputError("ARCHIVED_REGIME_CLOSURE_INVALID")
        binding = manifest.bindings[0]
        scope = record.scope
        cutoff = record.information_cutoff
        if (
            record.decision_id != decision.decision_id
            or record.decision_time != decision.decision_time
            or context.as_of != cutoff
            or context.expires_at <= decision.decision_time
            or manifest.analysis_cutoff != cutoff
            or manifest.expires_at <= decision.decision_time
            or (context.asset, context.instrument_id)
            != (scope.asset, scope.instrument_id)
            or (manifest.venue_id, manifest.timeframe)
            != (scope.venue_id, scope.timeframe)
            or (binding.venue_id, binding.instrument_id, binding.timeframe)
            != (scope.venue_id, scope.instrument_id, scope.timeframe)
            or (regime.asset, regime.instrument_id, regime.timeframe)
            != (scope.asset, scope.instrument_id, scope.timeframe)
            or regime.as_of > cutoff
            or regime.expires_at <= decision.decision_time
        ):
            raise SpotRegimeValidationInputError(
                "DECISION_TIME_SCOPE_OR_EXPIRY_MISMATCH"
            )
        if (
            binding.regime.record_id != regime.regime_id
            or binding.regime.content_sha256 != canonical_sha256(regime)
            or binding.regime_method.component != "spot-market-regime"
            or binding.regime_method.version != SPOT_MARKET_REGIME_METHOD_VERSION
            or binding.regime_profile.component != "spot-ohlcv-regime-profile"
            or binding.regime_profile.version != SPOT_MARKET_REGIME_PROFILE_VERSION
        ):
            raise SpotRegimeValidationInputError("C005_REFERENCE_OR_PROFILE_MISMATCH")
        dimensions = {item.name: item for item in regime.dimensions}
        if set(dimensions) != {"trend", "realized-volatility", "transition"}:
            raise SpotRegimeValidationInputError("UNKNOWN_C005_DIMENSION_SET")
        evidence_by_id = {item.evidence_id: item for item in closure.evidence}
        dimension_evidence = {
            evidence_id
            for dimension in dimensions.values()
            for evidence_id in dimension.evidence_ids
        }
        if set(regime.evidence_ids) - set(
            evidence_by_id
        ) or not dimension_evidence.issubset(regime.evidence_ids):
            raise SpotRegimeValidationInputError("C005_EVIDENCE_CLOSURE_INCOMPLETE")
        for evidence_id in regime.evidence_ids:
            evidence = evidence_by_id[evidence_id]
            if (
                type(evidence) is not EvidenceItemV2
                or not evidence.usable
                or evidence.observed_at > evidence.available_at
                or evidence.available_at > cutoff
                or evidence.expires_at <= decision.decision_time
            ):
                raise SpotRegimeValidationInputError(
                    "C005_EVIDENCE_UNAVAILABLE_OR_EXPIRED_AT_DECISION"
                )
        profile_version = binding.regime_profile.version
        context_key = RegimeContextKeyV2(
            scope.venue_id,
            scope.asset,
            scope.instrument_id,
            scope.timeframe,
            profile_version,
            dimensions["trend"].state,
            dimensions["realized-volatility"].state,
            dimensions["transition"].state,
        )
        context_ref = _reference(
            "C-006", context.context_id, "5", canonical_sha256(context)
        )
        evidence_references = tuple(binding.evidence)
        if tuple(str(item.record_id) for item in evidence_references) != tuple(
            sorted(str(item.evidence_id) for item in closure.evidence)
        ):
            raise SpotRegimeValidationInputError(
                "C008_EVIDENCE_ORDER_OR_CLOSURE_MISMATCH"
            )
        if any(
            item.content_sha256 != canonical_sha256(evidence_by_id[item.record_id])
            for item in evidence_references
        ):
            raise SpotRegimeValidationInputError("C008_EVIDENCE_DIGEST_MISMATCH")
        return (
            rule,
            decision,
            context_key,
            context_ref,
            context.analysis_snapshot,
            binding.regime,
            evidence_references,
        )
    except SpotRegimeValidationInputError:
        raise
    except (AttributeError, IndexError, KeyError, TypeError, ValueError) as exc:
        raise SpotRegimeValidationInputError("ARCHIVED_REGIME_CLOSURE_INVALID") from exc


def _observed(
    index: int,
    run: SpotRegimeRunInput,
    strategy_ref: ValidationArtifactReferenceV2,
    bundle: SpotBacktestBundle,
    report: SpotPerformanceReport,
    metrics: tuple[RegimeMetricObservationV2, ...],
    attribution,
) -> SpotRegimeObservationV2:
    result = bundle.result
    trace = bundle.trace
    assert type(result) is BacktestResultV3 and type(trace) is SpotBacktestTrace
    (
        attribution_rule,
        decision,
        context_key,
        context_ref,
        snapshot_ref,
        regime_ref,
        evidence_refs,
    ) = attribution
    sufficient = all(item.sufficient for item in metrics)
    state = (
        RegimeObservationStateV2.OBSERVED
        if sufficient
        else RegimeObservationStateV2.INCONCLUSIVE
    )
    reasons = () if sufficient else ("METRIC_SAMPLE_SUFFICIENCY_NOT_MET",)
    metrics_policy = RegimeMetricsPolicyV2.from_policy(run.metrics_policy)
    return SpotRegimeObservationV2(
        index,
        state,
        reasons,
        _request_digest(run.request),
        canonical_sha256(
            {
                "strategy_version_id": run.request.parameters.strategy_version_id,
                "strategy_sha256": run.request.parameters.strategy_sha256,
                "quantity": run.request.parameters.quantity,
                "entry_expiry_microseconds": _duration_microseconds(
                    run.request.parameters.entry_expiry
                ),
                "holding_interval_microseconds": _duration_microseconds(
                    run.request.parameters.holding_interval
                ),
                "exit_expiry_microseconds": _duration_microseconds(
                    run.request.parameters.exit_expiry
                ),
                "maximum_entries": run.request.parameters.maximum_entries,
                "partial_fill_policy": run.request.parameters.partial_fill_policy,
            }
        ),
        canonical_sha256(run.request.execution_policy),
        metrics_policy,
        canonical_sha256(metrics_policy),
        _reference("C-027", result.result_id, "3", result.content_sha256),
        result.trace,
        _bundle_digest(bundle),
        report.report_id,
        report.content_sha256,
        report.input_sha256,
        result.strategy_version,
        result.cost_assumptions,
        trace.cost_adapter,
        result.dataset.dataset_id,
        result.dataset.version,
        result.dataset_sha256,
        result.dataset.lineage_sha256,
        result.manifest_sha256,
        run.request.execution_policy.quote_unit,
        run.request.execution_policy.quantity_unit,
        result.venue,
        run.request.replay_inputs.scope.asset,
        result.instrument_id,
        result.timeframe,
        result.as_of,
        result.created_at,
        result.expires_at,
        report.policy.report_timestamp,
        result.period_start,
        result.period_end,
        attribution_rule,
        decision.decision_id,
        decision.decision_time,
        context_ref,
        snapshot_ref,
        regime_ref,
        evidence_refs,
        context_key,
        metrics,
    )


async def run_spot_regime_validation(
    *,
    plan: SpotRegimeValidationPlan,
    session: AsyncSession,
    strategy_registry: StrategyVersionResolver,
    lineage_store: SqlAlchemyLineageStore,
) -> SpotRegimeValidationResultV2:
    """Replay the frozen plan once and report descriptive per-run/context evidence."""
    if type(plan) is not SpotRegimeValidationPlan:
        raise SpotRegimeValidationInputError("FROZEN_REGIME_PLAN_REQUIRED")
    strategy_ref = _reference(
        "C-021",
        plan.strategy_version.strategy_version_id,
        "2",
        plan.strategy_version.content_sha256,
    )
    observations: list[SpotRegimeObservationV2] = []
    result_ids: set[UUID] = set()
    request_ids: set[str] = set()
    for index, run in enumerate(plan.runs):
        request_sha = _request_digest(run.request)
        if request_sha in request_ids:
            observations.append(
                _failed_observation(
                    index, run, strategy_ref, "DUPLICATE_REQUEST_IDENTITY"
                )
            )
            continue
        request_ids.add(request_sha)
        try:
            bundle = await run_spot_backtest(
                request=run.request,
                session=session,
                strategy_registry=strategy_registry,
                lineage_store=lineage_store,
            )
        except Exception as exc:
            observations.append(
                _failed_observation(
                    index,
                    run,
                    strategy_ref,
                    f"REPLAY_FAILED:{type(exc).__name__}",
                )
            )
            continue
        if bundle.outcome is not SpotBacktestOutcome.OBSERVED:
            replay_state = _replay_failure_state(bundle)
            observations.append(
                _failed_observation(
                    index,
                    run,
                    strategy_ref,
                    "REPLAY_NOT_OBSERVED",
                    state=replay_state,
                    bundle=bundle,
                )
            )
            continue
        if type(bundle.result) is not BacktestResultV3:
            observations.append(
                _failed_observation(
                    index,
                    run,
                    strategy_ref,
                    "REPLAY_RESULT_TYPE_INVALID",
                    bundle=bundle,
                )
            )
            continue
        if bundle.result.result_id in result_ids:
            observations.append(
                _failed_observation(
                    index, run, strategy_ref, "DUPLICATE_RESULT_IDENTITY"
                )
            )
            continue
        result_ids.add(bundle.result.result_id)
        try:
            result = resolve_spot_backtest_result(bundle)
            report = calculate_spot_performance_metrics(
                bundle,
                run.metrics_policy,
                price_path=bundle.execution_dataset,
            )
            source_failure = _source_failure(
                run.request, run.metrics_policy, bundle, report, as_of=plan.as_of
            )
            if source_failure is not None:
                raise SpotRegimeValidationInputError(source_failure)
            attribution = _attribution(run.request, bundle)
            metrics = _metric_observations(report, run.metrics_policy)
            observations.append(
                _observed(
                    index,
                    run,
                    strategy_ref,
                    bundle,
                    report,
                    metrics,
                    attribution,
                )
            )
        except SpotRegimeValidationInputError as exc:
            observations.append(
                _failed_observation(
                    index,
                    run,
                    strategy_ref,
                    str(exc),
                    bundle=bundle,
                    report=report,
                )
            )
        except (
            MetricsInputError,
            ValueError,
            TypeError,
            KeyError,
            AttributeError,
        ) as exc:
            observations.append(
                _failed_observation(
                    index,
                    run,
                    strategy_ref,
                    f"METRICS_OR_ATTRIBUTION_FAILED:{type(exc).__name__}",
                    bundle=bundle,
                    report=report,
                )
            )
    ordered_observations = tuple(observations)
    extras = tuple(
        dict.fromkeys(
            item.context_key
            for item in ordered_observations
            if item.context_key is not None
            and item.context_key not in plan.required_contexts
        )
    )
    coverage: list[RegimeContextCoverageV2] = []
    for key in (*plan.required_contexts, *extras):
        run_indexes = tuple(
            item.run_index for item in ordered_observations if item.context_key == key
        )
        sufficient_indexes = tuple(
            item.run_index
            for item in ordered_observations
            if item.context_key == key
            and item.state is RegimeObservationStateV2.OBSERVED
        )
        state = (
            RegimeCoverageStateV2.MISSING
            if not run_indexes
            else RegimeCoverageStateV2.OBSERVED
            if sufficient_indexes
            else RegimeCoverageStateV2.FAILED
            if all(
                ordered_observations[index].state is RegimeObservationStateV2.FAILED
                for index in run_indexes
            )
            else RegimeCoverageStateV2.INCONCLUSIVE
        )
        coverage.append(
            RegimeContextCoverageV2(
                key,
                key in plan.required_contexts,
                state,
                run_indexes,
                sufficient_indexes,
            )
        )
    outcome = (
        RegimeObservationStateV2.FAILED
        if any(
            item.state is RegimeObservationStateV2.FAILED
            for item in ordered_observations
        )
        else RegimeObservationStateV2.INCONCLUSIVE
        if any(
            item.state is not RegimeCoverageStateV2.OBSERVED
            for item in coverage
            if item.required
        )
        or any(
            item.state is not RegimeObservationStateV2.OBSERVED for item in observations
        )
        else RegimeObservationStateV2.OBSERVED
    )
    reasons = tuple(
        dict.fromkeys(
            reason for item in ordered_observations for reason in item.reason_codes
        )
    )
    if any(item.state is RegimeCoverageStateV2.MISSING for item in coverage):
        reasons = tuple(dict.fromkeys((*reasons, "REQUIRED_CONTEXT_COVERAGE_MISSING")))
    return SpotRegimeValidationResultV2.build(
        outcome=outcome,
        strategy_version=strategy_ref,
        metrics_method=METRICS_METHOD,
        metrics_method_version=run.metrics_policy.version,
        minimum_trade_sample=plan.runs[0].metrics_policy.min_trade_sample,
        minimum_return_sample=plan.runs[0].metrics_policy.min_return_sample,
        required_contexts=plan.required_contexts,
        observations=ordered_observations,
        contexts=tuple(coverage),
        warnings=REGIME_WARNINGS,
        reasons=reasons,
        as_of=plan.as_of,
        created_at=plan.created_at,
    )
