"""Bounded setup detection for PERSONAL_SPOT_RESEARCH.

This module consumes exact #80 and #81 results. It never qualifies a setup or
creates execution/risk authority. A C-023 candidate is emitted only for an
unambiguous, evidence-backed, confirmed setup; other outcomes stay runtime-local.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from typing import cast
from uuid import NAMESPACE_URL, UUID, uuid5

from trading_platform_api.analysis.contracts import (
    AnalyticalDirection,
    EvidenceRelation,
)
from trading_platform_api.analysis.versioned_contracts_v4 import (
    AnalysisSnapshotV4,
    ConflictAssessmentV3,
    ConfluenceAssessmentV3,
    ResolvedSpotOHLCVBindingV4,
)
from trading_platform_api.analysis.versioned_contracts_v5 import MarketContextV5
from trading_platform_api.contracts.serialization import canonical_sha256
from trading_platform_api.strategy.condition_evaluator import (
    ConditionTruth,
    SpotConditionContext,
    StrategyConditionEvaluation,
)
from trading_platform_api.strategy.contracts import (
    EligibilityState,
    SetupState,
    SignalCandidate,
    SignalConcept,
    SignalDirection,
    SignalLifecycleState,
    StrategyEligibility,
    StrategyVersion,
    VersionReference,
)
from trading_platform_api.strategy.eligibility import StrategyEligibilityEvaluation
from trading_platform_api.strategy.registry import (
    ResolvedStrategyVersion,
    strategy_version_content_sha256,
)

MAX_TARGET_CONCEPTS = 16
MAX_CONCEPT_TEXT_LENGTH = 512
MAX_SETUP_EVIDENCE_REFERENCES = 4096


class SetupDetectionOutcome(StrEnum):
    SETUP_DETECTED = "SETUP_DETECTED"
    NO_SETUP = "NO_SETUP"
    INSUFFICIENT_INPUT = "INSUFFICIENT_INPUT"


@dataclass(frozen=True, slots=True)
class SetupDetectionEvaluation:
    """Runtime-local gate result; only SETUP_DETECTED carries canonical C-023."""

    outcome: SetupDetectionOutcome
    reason_codes: tuple[str, ...]
    candidate: SignalCandidate | None

    def __post_init__(self) -> None:
        if type(self.outcome) is not SetupDetectionOutcome:
            raise ValueError("setup outcome must be a SetupDetectionOutcome")
        if type(self.reason_codes) is not tuple or any(
            not isinstance(item, str) or not item.strip() for item in self.reason_codes
        ):
            raise ValueError("setup reason codes must be nonempty strings")
        if self.outcome is SetupDetectionOutcome.SETUP_DETECTED:
            if (
                type(self.candidate) is not SignalCandidate
                or self.candidate.setup_state is not SetupState.SETUP_CONFIRMED
                or self.candidate.eligibility_state is not EligibilityState.ELIGIBLE
                or self.reason_codes
            ):
                raise ValueError("detected setup requires one valid confirmed C-023")
        elif self.candidate is not None or not self.reason_codes:
            raise ValueError("non-setup outcome requires reasons and no C-023")


def evaluate_strategy_setup(
    *,
    requested_strategy_version_id: UUID,
    strategy: ResolvedStrategyVersion | None,
    condition_context: SpotConditionContext | None,
    condition_evaluation: StrategyConditionEvaluation | None,
    eligibility_evaluation: StrategyEligibilityEvaluation | None,
    market_context: MarketContextV5 | None,
    manifest: AnalysisSnapshotV4 | None,
    resolved_bindings: tuple[ResolvedSpotOHLCVBindingV4, ...] | None,
    now: datetime,
) -> SetupDetectionEvaluation:
    """Create one C-023 candidate only after exact #80/#81 and provenance gates."""

    at = _utc(now)
    binding_error = _validate_inputs(
        requested_strategy_version_id=requested_strategy_version_id,
        strategy=strategy,
        condition_context=condition_context,
        condition_evaluation=condition_evaluation,
        eligibility_evaluation=eligibility_evaluation,
        market_context=market_context,
        manifest=manifest,
        resolved_bindings=resolved_bindings,
        now=at,
    )
    if binding_error is not None:
        outcome, reason = binding_error
        return _result(outcome, reason)

    assert strategy is not None
    assert condition_context is not None
    assert condition_evaluation is not None
    assert eligibility_evaluation is not None
    assert eligibility_evaluation.eligibility is not None
    assert market_context is not None
    assert manifest is not None
    assert resolved_bindings is not None

    if condition_evaluation.truth is ConditionTruth.FAIL:
        return _result(SetupDetectionOutcome.NO_SETUP, "CONDITIONS_NOT_SATISFIED")
    if condition_evaluation.truth is not ConditionTruth.PASS:
        return _result(SetupDetectionOutcome.INSUFFICIENT_INPUT, "CONDITIONS_UNKNOWN")

    direction, direction_reason = _derive_direction(
        strategy.version, condition_context, condition_evaluation
    )
    if direction is None:
        return _result(SetupDetectionOutcome.INSUFFICIENT_INPUT, direction_reason)

    eligibility = eligibility_evaluation.eligibility
    support_ids = _evidence_for_direction(market_context, direction)
    contradictory_ids = _contradictory_evidence(market_context, direction)
    if not support_ids:
        return _result(
            SetupDetectionOutcome.INSUFFICIENT_INPUT, "SUPPORTING_EVIDENCE_UNAVAILABLE"
        )
    evidence_set = set(market_context.evidence_ids)
    manifest_evidence = set(manifest.evidence_ids)
    if (
        not set(support_ids).issubset(evidence_set)
        or not set(support_ids).issubset(manifest_evidence)
        or not set(contradictory_ids).issubset(evidence_set)
        or not set(contradictory_ids).issubset(manifest_evidence)
    ):
        return _result(
            SetupDetectionOutcome.INSUFFICIENT_INPUT, "EVIDENCE_PROVENANCE_MISMATCH"
        )

    version = strategy.version
    concept_method = VersionReference(
        "C-021",
        version.strategy_version_id,
        version.semantic_version,
        version.content_sha256,
    )
    expiry = min(
        condition_context.expires_at,
        condition_evaluation.expires_at,
        eligibility.expires_at,
        market_context.expires_at,
        market_context.confluence.expires_at,
        market_context.adversarial.expires_at,
        manifest.expires_at,
        resolved_bindings[0].dependency_expires_at,
    )
    if expiry <= at:
        return _result(SetupDetectionOutcome.INSUFFICIENT_INPUT, "SETUP_INPUT_EXPIRED")

    candidate_id = _candidate_id(
        version.strategy_version_id,
        eligibility.eligibility_id,
        market_context.context_id,
        manifest.snapshot_id,
        at,
        direction,
        support_ids,
        contradictory_ids,
    )
    candidate = SignalCandidate(
        candidate_id=candidate_id,
        strategy_id=version.strategy_id,
        strategy_version_id=version.strategy_version_id,
        eligibility_id=eligibility.eligibility_id,
        eligibility_state=EligibilityState.ELIGIBLE,
        market_context_id=market_context.context_id,
        analysis_snapshot_id=manifest.snapshot_id,
        asset=market_context.asset,
        instrument_id=market_context.instrument_id,
        timeframe=manifest.timeframe,
        direction=direction,
        setup_state=SetupState.SETUP_CONFIRMED,
        entry_concept=SignalConcept(
            "ENTRY_CONCEPT", version.entry_concept, (), concept_method
        ),
        invalidation_concept=SignalConcept(
            "INVALIDATION_CONCEPT", version.invalidation_concept, (), concept_method
        ),
        target_concepts=tuple(
            SignalConcept("TARGET_CONCEPT", item, (), concept_method)
            for item in version.target_concepts
        ),
        supporting_evidence_ids=support_ids,
        contradictory_evidence_ids=contradictory_ids,
        data_quality_report_id=eligibility.data_quality_report_id,
        # Chat 6's C-023 example uses zero for these unscored fields. Setup
        # detection does not estimate confidence or construct a score.
        analytical_confidence=Decimal("0"),
        evidence_strength=Decimal("0"),
        lifecycle=SignalLifecycleState.CANDIDATE,
        created_at=at,
        expires_at=expiry,
    )
    return SetupDetectionEvaluation(SetupDetectionOutcome.SETUP_DETECTED, (), candidate)


def _validate_inputs(
    *,
    requested_strategy_version_id: UUID,
    strategy: ResolvedStrategyVersion | None,
    condition_context: SpotConditionContext | None,
    condition_evaluation: StrategyConditionEvaluation | None,
    eligibility_evaluation: StrategyEligibilityEvaluation | None,
    market_context: MarketContextV5 | None,
    manifest: AnalysisSnapshotV4 | None,
    resolved_bindings: tuple[ResolvedSpotOHLCVBindingV4, ...] | None,
    now: datetime,
) -> tuple[SetupDetectionOutcome, str] | None:
    if type(requested_strategy_version_id) is not UUID:
        return SetupDetectionOutcome.INSUFFICIENT_INPUT, "INVALID_STRATEGY_VERSION_ID"
    if (
        type(strategy) is not ResolvedStrategyVersion
        or type(condition_context) is not SpotConditionContext
        or type(condition_evaluation) is not StrategyConditionEvaluation
        or type(eligibility_evaluation) is not StrategyEligibilityEvaluation
        or type(market_context) is not MarketContextV5
        or type(manifest) is not AnalysisSnapshotV4
        or type(resolved_bindings) is not tuple
    ):
        return SetupDetectionOutcome.INSUFFICIENT_INPUT, "REQUIRED_INPUT_UNAVAILABLE"
    version = strategy.version
    if (
        version.strategy_version_id != requested_strategy_version_id
        or strategy.strategy.strategy_id != version.strategy_id
        or strategy_version_content_sha256(version) != version.content_sha256
        or condition_context.strategy != strategy
    ):
        return SetupDetectionOutcome.INSUFFICIENT_INPUT, "STRATEGY_VERSION_MISMATCH"
    if not strategy.selectable_for_research:
        return SetupDetectionOutcome.NO_SETUP, "STRATEGY_NOT_AVAILABLE_FOR_RESEARCH"
    if (
        not isinstance(version.entry_concept, str)
        or not version.entry_concept.strip()
        or not isinstance(version.invalidation_concept, str)
        or not version.invalidation_concept.strip()
        or type(version.target_concepts) is not tuple
        or any(
            not isinstance(item, str) or not item.strip()
            for item in version.target_concepts
        )
    ):
        return SetupDetectionOutcome.INSUFFICIENT_INPUT, "STRATEGY_CONCEPTS_UNAVAILABLE"
    condition = condition_evaluation
    if (
        condition.strategy_id != version.strategy_id
        or condition.strategy_version_id != version.strategy_version_id
        or condition.semantic_version != version.semantic_version
        or condition.content_sha256 != version.content_sha256
        or condition.dsl_version != "1"
        or condition.context_id != condition_context.context_id
        or condition.correlation_id != condition_context.correlation_id
        or condition.trace_id != condition_context.trace_id
        or condition.evaluated_at > now
        or condition.expires_at <= now
        or condition.expires_at != condition_context.expires_at
        or not _condition_structure_matches(version, condition)
    ):
        return SetupDetectionOutcome.INSUFFICIENT_INPUT, "CONDITION_BINDING_MISMATCH"
    eligibility = eligibility_evaluation.eligibility
    if eligibility_evaluation.state is not EligibilityState.ELIGIBLE:
        if eligibility_evaluation.state is EligibilityState.NOT_ELIGIBLE:
            return SetupDetectionOutcome.NO_SETUP, "STRATEGY_NOT_ELIGIBLE"
        return SetupDetectionOutcome.INSUFFICIENT_INPUT, "ELIGIBILITY_INSUFFICIENT_DATA"
    if type(eligibility) is not StrategyEligibility:
        return (
            SetupDetectionOutcome.INSUFFICIENT_INPUT,
            "ELIGIBILITY_RESULT_UNAVAILABLE",
        )
    if (
        eligibility.state is not EligibilityState.ELIGIBLE
        or eligibility.strategy_version_id != version.strategy_version_id
        or eligibility.market_context_id != market_context.context_id
        or eligibility.asset != market_context.asset
        or eligibility.instrument_id != market_context.instrument_id
        or eligibility.timeframe != manifest.timeframe
        or eligibility.regime_id != market_context.regime.regime_id
        or eligibility.evaluated_at > now
        or eligibility.expires_at <= now
    ):
        return SetupDetectionOutcome.INSUFFICIENT_INPUT, "ELIGIBILITY_BINDING_MISMATCH"
    if condition_context.context_id != market_context.context_id:
        return SetupDetectionOutcome.INSUFFICIENT_INPUT, "MARKET_CONTEXT_MISMATCH"
    if (
        market_context.contract_id != "C-006"
        or market_context.schema_version != "5"
        or market_context.as_of > now
        or market_context.expires_at <= now
        or condition_context.evaluated_at > now
        or condition_context.expires_at <= now
    ):
        return SetupDetectionOutcome.INSUFFICIENT_INPUT, "MARKET_CONTEXT_STALE"
    if (
        manifest.expires_at <= now
        or manifest.created_at > now
        or manifest.asset != market_context.asset
        or manifest.instrument_id != market_context.instrument_id
        or manifest.timeframe != market_context.adversarial.timeframe
        or market_context.confluence.timeframe != manifest.timeframe
        or market_context.analysis_snapshot.snapshot_id != manifest.snapshot_id
        or market_context.analysis_snapshot.schema_version != manifest.schema_version
        or market_context.analysis_snapshot.content_sha256 != manifest.content_sha256
        or market_context.confluence.input_snapshot_id != manifest.snapshot_id
    ):
        return SetupDetectionOutcome.INSUFFICIENT_INPUT, "ANALYSIS_SNAPSHOT_MISMATCH"
    if (
        type(resolved_bindings) is not tuple
        or len(resolved_bindings) != 1
        or type(resolved_bindings[0]) is not ResolvedSpotOHLCVBindingV4
    ):
        return SetupDetectionOutcome.INSUFFICIENT_INPUT, "SPOT_BINDING_UNAVAILABLE"
    resolved = resolved_bindings[0]
    binding = resolved.binding
    if (
        len(version.target_concepts) > MAX_TARGET_CONCEPTS
        or any(
            len(item) > MAX_CONCEPT_TEXT_LENGTH
            for item in (
                version.entry_concept,
                version.invalidation_concept,
                *version.target_concepts,
            )
        )
        or len(market_context.evidence_ids) > MAX_SETUP_EVIDENCE_REFERENCES
        or len(manifest.evidence_ids) > MAX_SETUP_EVIDENCE_REFERENCES
    ):
        return SetupDetectionOutcome.INSUFFICIENT_INPUT, "SETUP_INPUT_LIMIT_EXCEEDED"
    if (
        len(manifest.bindings) != 1
        or binding != manifest.bindings[0]
        or binding.instrument_id != market_context.instrument_id
        or binding.timeframe != manifest.timeframe
        or resolved.snapshot.snapshot_id != UUID(binding.market_snapshot.record_id)
        or resolved.report.report_id != UUID(binding.data_quality_report.record_id)
        or resolved.report.snapshot_id != resolved.snapshot.snapshot_id
        or resolved.report.assessed_at > now
        or canonical_sha256(resolved.report)
        != binding.data_quality_report.content_sha256
        or not resolved.direct_inputs_pass
        or resolved.report.status.value != "VALID"
        or resolved.dependency_expires_at <= now
        or eligibility.data_quality_report_id != resolved.report.report_id
        or resolved.regime.regime_id != market_context.regime.regime_id
        or resolved.regime != market_context.regime
    ):
        return SetupDetectionOutcome.INSUFFICIENT_INPUT, "SPOT_PROVENANCE_MISMATCH"
    quality_outputs = cast(
        tuple[ConfluenceAssessmentV3 | ConflictAssessmentV3, ...],
        (market_context.confluence, *market_context.conflicts),
    )
    for output in quality_outputs:
        report_refs = output.data_quality_reports
        if not report_refs or any(
            ref.contract_id != "C-003"
            or ref.record_id != str(resolved.report.report_id)
            or ref.schema_version != "2"
            or ref.lineage_version != "2"
            or ref.content_sha256 != canonical_sha256(resolved.report)
            for ref in report_refs
        ):
            return (
                SetupDetectionOutcome.INSUFFICIENT_INPUT,
                "C003_META_BINDING_MISMATCH",
            )
    return None


def _condition_structure_matches(
    version: StrategyVersion, evaluation: StrategyConditionEvaluation
) -> bool:
    expected_conditions = {item.condition_id: item for item in version.conditions}
    actual_conditions = {item.condition_id: item for item in evaluation.conditions}
    if len(actual_conditions) != len(evaluation.conditions) or set(
        actual_conditions
    ) != set(expected_conditions):
        return False
    for condition_id, expected in expected_conditions.items():
        actual = actual_conditions[condition_id]
        if actual.feature_path != expected.feature_path:
            return False
    expected_groups = {
        item.group_id: (item.operator, item.condition_ids)
        for item in version.condition_groups
    }
    actual_groups = {
        item.group_id: (item.operator, item.condition_ids) for item in evaluation.groups
    }
    return (
        len(actual_groups) == len(evaluation.groups)
        and actual_groups == expected_groups
        and (
            evaluation.truth is not ConditionTruth.PASS
            or all(item.truth is ConditionTruth.PASS for item in evaluation.groups)
        )
    )


def _derive_direction(
    version: StrategyVersion,
    context: SpotConditionContext,
    evaluation: StrategyConditionEvaluation,
) -> tuple[SignalDirection | None, str]:
    condition_by_id = {item.condition_id: item for item in version.conditions}
    features = {item.path: item for item in context.features}
    directions: set[SignalDirection] = set()
    for result in evaluation.conditions:
        condition = condition_by_id.get(result.condition_id)
        if (
            condition is None
            or result.truth is not ConditionTruth.PASS
            or not condition.feature_path.startswith("spot.finding.")
            or not condition.feature_path.endswith(".direction")
            or condition.operator.value != "EQUALS"
            or len(condition.expected_values) != 1
            or result.source_contract_id != "C-009"
            or result.code.value != "EVALUATED"
        ):
            continue
        feature = features.get(condition.feature_path)
        if (
            feature is None
            or feature.availability.value != "PRESENT"
            or type(feature.value) is not str
            or feature.value != condition.expected_values[0]
            or result.source_schema_version != feature.source_schema_version
            or result.provenance != feature.provenance
            or result.source_record_ids != feature.source_record_ids
        ):
            continue
        if feature.value == AnalyticalDirection.BULLISH.value:
            directions.add(SignalDirection.LONG)
        elif feature.value == AnalyticalDirection.BEARISH.value:
            directions.add(SignalDirection.SHORT)
    if not directions:
        return None, "DIRECTION_NOT_ESTABLISHED"
    if len(directions) > 1:
        return None, "DIRECTION_AMBIGUOUS"
    return next(iter(directions)), ""


def _evidence_for_direction(
    market_context: MarketContextV5, direction: SignalDirection
) -> tuple[UUID, ...]:
    wanted = (
        AnalyticalDirection.BULLISH
        if direction is SignalDirection.LONG
        else AnalyticalDirection.BEARISH
    )
    return tuple(
        sorted(
            {
                evidence_id
                for component in market_context.confluence.components
                if component.direction is wanted
                and component.relation is EvidenceRelation.SUPPORTING
                for evidence_id in component.evidence_ids
            },
            key=str,
        )
    )


def _contradictory_evidence(
    market_context: MarketContextV5, direction: SignalDirection
) -> tuple[UUID, ...]:
    opposite = (
        AnalyticalDirection.BEARISH
        if direction is SignalDirection.LONG
        else AnalyticalDirection.BULLISH
    )
    ids = {
        evidence_id
        for component in market_context.confluence.components
        if component.relation is EvidenceRelation.CONTRADICTING
        or (
            component.direction is opposite
            and component.relation is EvidenceRelation.SUPPORTING
        )
        for evidence_id in component.evidence_ids
    }
    ids.update(market_context.adversarial.contradictory_evidence_ids)
    return tuple(sorted(ids, key=str))


def _candidate_id(
    strategy_version_id: UUID,
    eligibility_id: UUID,
    context_id: UUID,
    snapshot_id: UUID,
    evaluated_at: datetime,
    direction: SignalDirection,
    supporting: tuple[UUID, ...],
    contradictory: tuple[UUID, ...],
) -> UUID:
    return uuid5(
        NAMESPACE_URL,
        "personal-spot-strategy-setup/v1/"
        f"{strategy_version_id}/{eligibility_id}/{context_id}/{snapshot_id}/"
        f"{evaluated_at.isoformat()}/{direction.value}/"
        f"{','.join(map(str, supporting))}/{','.join(map(str, contradictory))}",
    )


def _result(outcome: SetupDetectionOutcome, reason: str) -> SetupDetectionEvaluation:
    return SetupDetectionEvaluation(outcome, (reason,), None)


def _utc(value: datetime) -> datetime:
    if (
        not isinstance(value, datetime)
        or value.tzinfo is None
        or value.utcoffset() is None
    ):
        raise ValueError("now must be timezone-aware")
    return value.astimezone(UTC)


__all__ = [
    "SetupDetectionEvaluation",
    "SetupDetectionOutcome",
    "evaluate_strategy_setup",
]
