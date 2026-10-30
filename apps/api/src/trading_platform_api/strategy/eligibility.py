"""Bounded deterministic strategy eligibility for PERSONAL_SPOT_RESEARCH."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import NAMESPACE_URL, UUID, uuid5

from trading_platform_api.analysis.contracts import MarketRegime
from trading_platform_api.analysis.versioned_contracts_v4 import (
    AnalysisSnapshotReferenceV4,
    AnalysisSnapshotV4,
    ResolvedSpotOHLCVBindingV4,
    resolve_analysis_snapshot_v4,
)
from trading_platform_api.analysis.versioned_contracts_v5 import MarketContextV5
from trading_platform_api.config import DeploymentEnvironment, OperatingMode
from trading_platform_api.contracts.serialization import canonical_sha256
from trading_platform_api.strategy.condition_evaluator import (
    ConditionResultCode,
    ConditionTruth,
    SpotConditionContext,
    StrategyConditionEvaluation,
)
from trading_platform_api.strategy.contracts import (
    EligibilityState,
    StrategyEligibility,
    StrategyVersion,
)
from trading_platform_api.strategy.registry import (
    ArtifactVersionLifecycle,
    ResolvedStrategyVersion,
    StrategyAvailability,
    StrategyLifecycle,
    strategy_version_content_sha256,
)

MAX_REGIME_DIMENSIONS = 16
_SUPPORTED_REGIME_DIMENSIONS = frozenset({"trend", "realized-volatility", "transition"})
_SUPPORTED_REGIME_STATES = {
    "trend": frozenset({"bullish", "bearish", "mixed"}),
    "realized-volatility": frozenset({"high", "low", "typical"}),
    "transition": frozenset({"possible", "not-observed-in-lookback"}),
}


@dataclass(frozen=True, slots=True)
class StrategyEligibilityEvaluation:
    """Runtime result; C-022 is absent when its mandatory provenance is unproven."""

    state: EligibilityState
    reason_codes: tuple[str, ...]
    eligibility: StrategyEligibility | None


def evaluate_strategy_eligibility(
    *,
    requested_strategy_version_id: UUID,
    strategy: ResolvedStrategyVersion | None,
    condition_context: SpotConditionContext,
    condition_evaluation: StrategyConditionEvaluation,
    market_context: MarketContextV5,
    manifest: AnalysisSnapshotV4 | None,
    resolved_bindings: tuple[ResolvedSpotOHLCVBindingV4, ...] | None,
    environment: DeploymentEnvironment,
    mode: OperatingMode,
    now: datetime,
) -> StrategyEligibilityEvaluation:
    """Evaluate the exact registry version and validated C-006/C-007/C-003 chain."""

    at = _utc(now)
    provenance_failure, report_id = _validate_provenance(
        market_context, manifest, resolved_bindings, at
    )
    if provenance_failure is not None or report_id is None:
        return StrategyEligibilityEvaluation(
            EligibilityState.INSUFFICIENT_DATA,
            (provenance_failure or "SPOT_PROVENANCE_UNAVAILABLE",),
            None,
        )
    if manifest is None or resolved_bindings is None:
        return _insufficient("SPOT_PROVENANCE_UNAVAILABLE")
    if type(requested_strategy_version_id) is not UUID:
        return _insufficient("INVALID_REQUESTED_STRATEGY_VERSION")

    reasons: list[str] = []
    state = EligibilityState.ELIGIBLE

    def insufficient(reason: str) -> None:
        nonlocal state
        if state is EligibilityState.ELIGIBLE:
            state = EligibilityState.INSUFFICIENT_DATA
        if reason not in reasons:
            reasons.append(reason)

    def reject(reason: str) -> None:
        nonlocal state
        if state is not EligibilityState.INSUFFICIENT_DATA:
            state = EligibilityState.NOT_ELIGIBLE
        if reason not in reasons:
            reasons.append(reason)

    if (
        type(strategy) is not ResolvedStrategyVersion
        or type(condition_context) is not SpotConditionContext
        or type(condition_evaluation) is not StrategyConditionEvaluation
    ):
        insufficient("STRATEGY_OR_CONDITION_INPUT_UNAVAILABLE")
    else:
        version = strategy.version
        if (
            version.strategy_version_id != requested_strategy_version_id
            or strategy.strategy.strategy_id != version.strategy_id
            or strategy_version_content_sha256(version) != version.content_sha256
            or condition_context.strategy != strategy
        ):
            insufficient("STRATEGY_VERSION_BINDING_MISMATCH")
        if (
            condition_evaluation.strategy_id != version.strategy_id
            or condition_evaluation.strategy_version_id != version.strategy_version_id
            or condition_evaluation.semantic_version != version.semantic_version
            or condition_evaluation.content_sha256 != version.content_sha256
            or condition_evaluation.dsl_version != "1"
        ):
            insufficient("CONDITION_VERSION_BINDING_MISMATCH")
        invalid_lifecycle = (
            strategy.availability
            in {StrategyAvailability.SUSPENDED, StrategyAvailability.DEPRECATED}
            or strategy.c021_lifecycle
            in {
                StrategyLifecycle.REJECTED,
                StrategyLifecycle.RETIRED,
                StrategyLifecycle.ROLLED_BACK,
            }
            or strategy.artifact_lifecycle
            in {
                ArtifactVersionLifecycle.REJECTED,
                ArtifactVersionLifecycle.RETIRED,
                ArtifactVersionLifecycle.ROLLED_BACK,
            }
            or not strategy.selectable_for_research
        )
        if invalid_lifecycle:
            reject("INVALID_STRATEGY_LIFECYCLE")
        expected_condition_ids = {item.condition_id for item in version.conditions}
        expected_groups = {
            (item.group_id, item.operator, item.condition_ids)
            for item in version.condition_groups
        }
        actual_groups = {
            (item.group_id, item.operator, item.condition_ids)
            for item in condition_evaluation.groups
        }
        if not (
            invalid_lifecycle
            and ConditionResultCode.INVALID_STRATEGY_STATE
            in condition_evaluation.reason_codes
        ) and (
            {item.condition_id for item in condition_evaluation.conditions}
            != expected_condition_ids
            or len(condition_evaluation.conditions) != len(expected_condition_ids)
            or actual_groups != expected_groups
            or len(condition_evaluation.groups) != len(expected_groups)
            or condition_evaluation.evaluated_at != condition_context.evaluated_at
        ):
            insufficient("MALFORMED_CONDITION_EVALUATION_BINDING")
        if (
            condition_context.context_id != market_context.context_id
            or condition_evaluation.context_id != market_context.context_id
            or condition_evaluation.correlation_id != condition_context.correlation_id
            or condition_evaluation.trace_id != condition_context.trace_id
        ):
            insufficient("CONTEXT_CORRELATION_MISMATCH")
        if (
            condition_evaluation.evaluated_at > at
            or condition_evaluation.expires_at <= at
            or condition_context.expires_at <= at
            or market_context.expires_at <= at
            or market_context.regime.expires_at <= at
            or market_context.confluence.expires_at <= at
        ):
            insufficient("STALE_OR_UNSUPPORTED_INPUT")
        if (
            type(environment) is not DeploymentEnvironment
            or type(mode) is not OperatingMode
        ):
            insufficient("MISSING_OR_INVALID_OPERATING_CONTEXT")
        elif (
            mode is not OperatingMode.RESEARCH
            or mode not in version.operating_modes
            or environment not in version.environments
        ):
            reject("UNSUPPORTED_OPERATING_CONTEXT")
        if market_context.asset not in version.supported_assets:
            reject("UNSUPPORTED_ASSET")
        if market_context.instrument_id not in version.supported_instruments:
            reject("UNSUPPORTED_INSTRUMENT")
        timeframe = market_context.adversarial.timeframe
        if timeframe not in version.supported_timeframes:
            reject("UNSUPPORTED_TIMEFRAME")
        regime_reasons, incompatible = _regime_outcome(version, market_context)
        for reason in regime_reasons:
            insufficient(reason)
        if incompatible:
            reject("INCOMPATIBLE_REGIME")

        if invalid_lifecycle:
            pass
        elif condition_evaluation.truth is ConditionTruth.FAIL:
            reject("REQUIRED_CONDITIONS_FAILED")
        elif condition_evaluation.truth is ConditionTruth.UNKNOWN:
            insufficient("REQUIRED_CONDITIONS_UNKNOWN")
        elif condition_evaluation.truth is not ConditionTruth.PASS:
            insufficient("INVALID_CONDITION_EVALUATION")
        if any(
            code
            in {
                ConditionResultCode.UNSUPPORTED_OPERATOR,
                ConditionResultCode.UNSUPPORTED_RUNTIME_CASE,
                ConditionResultCode.REQUIRED_EVIDENCE_UNAVAILABLE,
                ConditionResultCode.STALE_INPUT,
                ConditionResultCode.VERSION_MISMATCH,
                ConditionResultCode.INPUT_LIMIT_EXCEEDED,
                ConditionResultCode.INVALID_EXPECTED_VALUE,
            }
            for code in condition_evaluation.reason_codes
        ):
            insufficient("CONDITION_EVIDENCE_UNSUPPORTED_OR_INVALID")

    if not reasons:
        reasons.append("ELIGIBLE_FOR_SETUP_DETECTION")
    expires_at = min(
        market_context.expires_at,
        market_context.regime.expires_at,
        market_context.confluence.expires_at,
        condition_context.expires_at,
        condition_evaluation.expires_at,
        manifest.expires_at,
        resolved_bindings[0].dependency_expires_at,
    )
    if expires_at < at:
        expires_at = at
    identity = (
        f"C-022:{requested_strategy_version_id}:"
        f"{market_context.context_id}:{at.isoformat()}:"
        f"{state.value}:{','.join(reasons)}"
    )
    result = StrategyEligibility(
        eligibility_id=uuid5(NAMESPACE_URL, identity),
        strategy_version_id=requested_strategy_version_id,
        market_context_id=market_context.context_id,
        asset=market_context.asset,
        instrument_id=market_context.instrument_id,
        timeframe=market_context.adversarial.timeframe,
        state=state,
        reason_codes=tuple(reasons),
        data_quality_report_id=report_id,
        regime_id=market_context.regime.regime_id,
        evaluated_at=at,
        expires_at=expires_at,
    )
    return StrategyEligibilityEvaluation(state, tuple(reasons), result)


def _validate_provenance(
    context: MarketContextV5,
    manifest: AnalysisSnapshotV4 | None,
    resolved_bindings: tuple[ResolvedSpotOHLCVBindingV4, ...] | None,
    now: datetime,
) -> tuple[str | None, UUID | None]:
    if (
        type(context) is not MarketContextV5
        or type(manifest) is not AnalysisSnapshotV4
        or type(resolved_bindings) is not tuple
        or len(resolved_bindings) != 1
        or type(resolved_bindings[0]) is not ResolvedSpotOHLCVBindingV4
    ):
        return "SPOT_PROVENANCE_UNAVAILABLE", None
    resolved = resolved_bindings[0]
    binding = resolved.binding
    report = resolved.report
    report_reference = binding.data_quality_report
    if (
        type(context.analysis_snapshot) is not AnalysisSnapshotReferenceV4
        or context.analysis_snapshot.snapshot_id != manifest.snapshot_id
        or context.analysis_snapshot.schema_version != manifest.schema_version
        or context.analysis_snapshot.content_sha256 != manifest.content_sha256
        or (context.asset, context.instrument_id, context.as_of)
        != (manifest.asset, manifest.instrument_id, manifest.analysis_cutoff)
        or context.adversarial.analysis_snapshot != context.analysis_snapshot
        or context.adversarial.timeframe != manifest.timeframe
        or context.evidence_ids != manifest.evidence_ids
        or context.regime != resolved.regime
        or context.confluence.input_snapshot_id != manifest.snapshot_id
        or context.confluence.input_snapshot_schema_version != manifest.schema_version
        or context.confluence.data_quality_reports != (report_reference,)
        or (
            context.confluence.asset,
            context.confluence.instrument_id,
            context.confluence.timeframe,
            context.confluence.as_of,
        )
        != (
            manifest.asset,
            manifest.instrument_id,
            manifest.timeframe,
            manifest.analysis_cutoff,
        )
        or any(
            item.input_snapshot_id != manifest.snapshot_id
            or item.input_snapshot_schema_version != manifest.schema_version
            or item.data_quality_reports != (report_reference,)
            or (item.asset, item.instrument_id, item.timeframe, item.as_of)
            != (
                manifest.asset,
                manifest.instrument_id,
                manifest.timeframe,
                manifest.analysis_cutoff,
            )
            for item in context.conflicts
        )
    ):
        return "SPOT_PROVENANCE_MISMATCH", None
    c009 = next(
        (
            item
            for item in manifest.analysis_outputs
            if item.contract_id == "C-009"
            and item.record_id == context.confluence.assessment_id
        ),
        None,
    )
    if (
        c009 is None
        or c009.schema_version != context.confluence.schema_version
        or c009.lineage_version != context.confluence.schema_version
        or c009.content_sha256 != canonical_sha256(context.confluence)
    ):
        return "C009_MANIFEST_BINDING_MISMATCH", None
    for conflict in context.conflicts:
        reference = next(
            (
                item
                for item in manifest.analysis_outputs
                if item.contract_id == "C-010"
                and item.record_id == conflict.assessment_id
            ),
            None,
        )
        if (
            reference is None
            or reference.schema_version != conflict.schema_version
            or reference.lineage_version != conflict.schema_version
            or reference.content_sha256 != canonical_sha256(conflict)
        ):
            return "C010_MANIFEST_BINDING_MISMATCH", None
    if (
        report_reference.contract_id != "C-003"
        or report_reference.schema_version != "2"
        or report_reference.lineage_version != "2"
        or report_reference.content_sha256 != canonical_sha256(report)
        or report_reference.record_id != str(report.report_id)
        or report.status.value != "VALID"
        or report.assessed_at > now
        or not resolved.direct_inputs_pass
        or resolved.dependency_expires_at <= now
    ):
        return "C003_INVALID_STALE_OR_MISMATCHED", None
    try:
        verified = resolve_analysis_snapshot_v4(
            manifest,
            now=now,
            snapshots={resolved.snapshot.snapshot_id: resolved.snapshot},
            reports={report.report_id: report},
            observations={item.market_data_id: item for item in resolved.observations},
            sources={item.source_record_id: item for item in resolved.sources},
            regimes={resolved.regime.regime_id: resolved.regime},
            evidence={item.evidence_id: item for item in resolved.evidence},
        )
    except (KeyError, TypeError, ValueError):
        return "SPOT_BINDING_RESOLUTION_FAILED", None
    if verified != resolved_bindings or len(verified) != 1:
        return "SPOT_BINDING_RESOLUTION_MISMATCH", None
    if (binding.instrument_id, binding.timeframe) != (
        context.instrument_id,
        context.adversarial.timeframe,
    ):
        return "SPOT_BINDING_SCOPE_MISMATCH", None
    return None, report.report_id


def _regime_outcome(
    version: StrategyVersion, context: MarketContextV5
) -> tuple[tuple[str, ...], bool]:
    strategy_version = version
    regime: MarketRegime = context.regime
    if (
        regime.contract_id != "C-005"
        or regime.schema_version != "1"
        or regime.asset != context.asset
        or regime.instrument_id != context.instrument_id
        or regime.timeframe != context.adversarial.timeframe
        or len(regime.dimensions) > MAX_REGIME_DIMENSIONS
    ):
        return ("REGIME_CONTEXT_MISMATCH_OR_LIMIT",), False
    dimensions = {item.name: item.state for item in regime.dimensions}
    if any(
        name not in _SUPPORTED_REGIME_DIMENSIONS
        or value not in _SUPPORTED_REGIME_STATES[name]
        for name, value in dimensions.items()
    ):
        return ("UNSUPPORTED_REGIME_PROFILE",), False
    configured = (
        strategy_version.preferred_regimes
        + strategy_version.acceptable_regimes
        + strategy_version.incompatible_regimes
    )
    if any(name not in _SUPPORTED_REGIME_DIMENSIONS for name in configured):
        return ("UNSUPPORTED_REGIME_REQUIREMENT",), False
    if any(
        name not in dimensions
        for name in strategy_version.preferred_regimes
        + strategy_version.acceptable_regimes
    ):
        return ("REQUIRED_REGIME_DIMENSION_UNAVAILABLE",), False
    return (), any(name in dimensions for name in strategy_version.incompatible_regimes)


def _insufficient(reason: str) -> StrategyEligibilityEvaluation:
    return StrategyEligibilityEvaluation(
        EligibilityState.INSUFFICIENT_DATA, (reason,), None
    )


def _utc(value: datetime) -> datetime:
    if (
        not isinstance(value, datetime)
        or value.tzinfo is None
        or value.utcoffset() is None
    ):
        raise ValueError("now must be timezone-aware")
    return value.astimezone(UTC)
