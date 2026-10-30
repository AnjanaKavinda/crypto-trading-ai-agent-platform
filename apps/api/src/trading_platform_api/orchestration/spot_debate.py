"""Compose validated Spot evidence into a non-authoritative debate handoff.

This module does not call models or create new analytical claims. It keeps the
existing C-009 directional components, C-010 conflicts, C-019 challenge,
C-069 uncertainty, C-093 dependence report, C-062 result, and C-066 evaluation
together for a later strategy layer. The result is orchestration-local and is
not a canonical domain contract or a trade signal.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID

from trading_platform_api.agents.contracts import (
    AgentEvaluation,
    AgentEvaluationOutcome,
    AgentEvaluationSchemaState,
    AgentResult,
    AgentResultStatus,
)
from trading_platform_api.agents.registry import PERSONAL_SPOT_RESEARCH_AGENT
from trading_platform_api.agents.result_validation import (
    AgentResultExpectation,
    validate_agent_result,
)
from trading_platform_api.analysis.contracts import (
    AnalyticalDirection,
    EvidenceRelation,
    VersionReference,
)
from trading_platform_api.analysis.spot_meta_analysis import (
    AgentIndependenceReport,
    C093Registry,
)
from trading_platform_api.analysis.versioned_contracts import EvidenceItemV2
from trading_platform_api.analysis.versioned_contracts_v4 import (
    AnalysisSnapshotV4,
    ConfluenceAssessmentV3,
    ConfluenceComponentV2,
    ConfluenceStateV2,
    ResolvedSpotOHLCVBindingV4,
)
from trading_platform_api.analysis.versioned_contracts_v5 import (
    MarketContextV5,
    validate_market_context_v5,
)
from trading_platform_api.contracts.serialization import canonical_sha256


class SpotDebateError(ValueError):
    """Raised when the validated Spot debate input envelope is inconsistent."""


class SpotDebateConclusion(StrEnum):
    BULLISH_EVIDENCE_UNRESOLVED = "BULLISH_EVIDENCE_UNRESOLVED"
    BEARISH_EVIDENCE_UNRESOLVED = "BEARISH_EVIDENCE_UNRESOLVED"
    MIXED_OR_CONFLICTED = "MIXED_OR_CONFLICTED"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
    NO_DEFENSIBLE_DIRECTION = "NO_DEFENSIBLE_DIRECTION"
    NO_TRADE = "NO_TRADE"


@dataclass(frozen=True, slots=True)
class SpotThesisBranch:
    """Evidence references organized by direction, without a vote or score."""

    direction: AnalyticalDirection
    component_ids: tuple[UUID, ...]
    components: tuple[ConfluenceComponentV2, ...]
    evidence_ids: tuple[UUID, ...]
    available: bool


@dataclass(frozen=True, slots=True)
class SpotDebateResult:
    """Internal handoff preserving opposing evidence and unresolved challenges."""

    result_id: UUID
    task_id: UUID
    context_id: UUID
    correlation_id: UUID
    trace_id: UUID
    agent_result: AgentResult
    agent_evaluation: AgentEvaluation
    market_context: MarketContextV5
    bullish: SpotThesisBranch
    bearish: SpotThesisBranch
    independence_report: AgentIndependenceReport
    conclusion: SpotDebateConclusion
    disagreement_preserved: bool
    expires_at: datetime


def compose_spot_debate(
    *,
    agent_result: AgentResult,
    agent_evaluation: AgentEvaluation,
    expectation: AgentResultExpectation,
    correlation_id: UUID,
    trace_id: UUID,
    market_context: MarketContextV5,
    manifest: AnalysisSnapshotV4,
    resolved_bindings: tuple[ResolvedSpotOHLCVBindingV4, ...],
    evidence: Mapping[UUID, EvidenceItemV2],
    independence_reports: Mapping[UUID, AgentIndependenceReport],
    supported_adversarial_versions: tuple[VersionReference, ...],
    now: datetime,
) -> SpotDebateResult:
    """Validate exact inputs, then preserve bull/bear/critic evidence separately.

    C-062/C-066 identity validation and the C-006/C-007/C-008/C-093/C-019
    lineage validators are reused. Missing or stale input is rejected; it is
    never interpreted as neutral support. No C-066 is manufactured here.
    """

    if not isinstance(correlation_id, UUID) or not isinstance(trace_id, UUID):
        raise SpotDebateError("correlation_id and trace_id must be UUIDs.")
    if not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None:
        raise SpotDebateError("now must be timezone-aware.")
    try:
        validated_result = validate_agent_result(
            agent_result, expectation=expectation, now=now
        )
    except (TypeError, ValueError):
        raise SpotDebateError("C-062 result failed exact validation.") from None
    if (
        validated_result.agent_id != PERSONAL_SPOT_RESEARCH_AGENT.agent_id
        or validated_result.agent_version != PERSONAL_SPOT_RESEARCH_AGENT.agent_version
        or validated_result.tool_access_ids
        or expectation.allowed_tool_access_ids
    ):
        raise SpotDebateError("Spot debate requires the tool-free registered agent.")
    if type(agent_evaluation) is not AgentEvaluation:
        raise SpotDebateError("a typed C-066 evaluation is required for C-062.")
    if (
        agent_evaluation.result_id != validated_result.result_id
        or agent_evaluation.result_contract_id != validated_result.contract_id
        or agent_evaluation.result_schema_version != validated_result.schema_version
        or agent_evaluation.task_id != validated_result.task_id
        or agent_evaluation.context_id != validated_result.context_id
        or agent_evaluation.correlation_id != correlation_id
        or agent_evaluation.trace_id != trace_id
        or agent_evaluation.agent_id != validated_result.agent_id
        or agent_evaluation.agent_version != validated_result.agent_version
        or agent_evaluation.routing_decision_ref.entity_id
        != validated_result.routing_decision.request_id
        or agent_evaluation.provider_id != validated_result.routing_decision.provider_id
        or agent_evaluation.model_id != validated_result.routing_decision.model_id
        or agent_evaluation.model_version
        != validated_result.routing_decision.model_version
        or agent_evaluation.prompt_id != validated_result.routing_decision.prompt_id
        or agent_evaluation.prompt_version
        != validated_result.routing_decision.prompt_version
        or agent_evaluation.outcome is not AgentEvaluationOutcome.COMPLETED
        or agent_evaluation.schema_state is not AgentEvaluationSchemaState.VALID
        or agent_evaluation.result_status is not validated_result.status
    ):
        raise SpotDebateError("C-066 is not the completed evaluation of this C-062.")
    if type(validated_result.output) is not MarketContextV5:
        raise SpotDebateError("C-062 output must be the registered C-006 schema 5.")
    if validated_result.context_id != market_context.context_id:
        raise SpotDebateError("C-062 and C-006 context identities differ.")
    if (
        agent_evaluation.output_contract_id != "C-006"
        or agent_evaluation.output_schema_version != market_context.schema_version
        or canonical_sha256(validated_result.output) != canonical_sha256(market_context)
    ):
        raise SpotDebateError("C-062/C-066 output binding differs from C-006.")

    try:
        validate_market_context_v5(
            market_context,
            manifest,
            resolved_bindings=resolved_bindings,
            evidence=evidence,
            supported_independence_reports=(
                market_context.confluence.independence_report,
            ),
            supported_adversarial_versions=supported_adversarial_versions,
            now=now,
        )
        independence = C093Registry.resolve(
            market_context.confluence.independence_report, independence_reports
        )
    except (TypeError, ValueError):
        raise SpotDebateError(
            "C-006 lineage, C-019, or C-093 binding is invalid."
        ) from None

    if (
        independence.report_id
        != market_context.confluence.independence_report.record_id
        or independence.expires_at <= now
        or market_context.adversarial.expires_at <= now
        or market_context.confluence.expires_at <= now
    ):
        raise SpotDebateError("Spot debate inputs are stale or expired.")

    bullish, bearish = _thesis_branches(market_context.confluence)
    conclusion = _conclusion(
        result_status=validated_result.status,
        confluence=market_context.confluence,
        conflicts=bool(market_context.conflicts)
        or bool(market_context.adversarial.contradictory_evidence_ids),
        bullish=bullish,
        bearish=bearish,
    )

    expiry_values = (
        validated_result.expires_at,
        market_context.expires_at,
        market_context.adversarial.expires_at,
        market_context.confluence.expires_at,
        independence.expires_at,
        *(item.expires_at for item in market_context.conflicts),
        *(item.expires_at for item in market_context.uncertainties),
    )
    expiry = min(expiry_values)
    if expiry <= now:
        raise SpotDebateError("Spot debate result has no remaining freshness window.")

    return SpotDebateResult(
        result_id=validated_result.result_id,
        task_id=validated_result.task_id,
        context_id=validated_result.context_id,
        correlation_id=correlation_id,
        trace_id=trace_id,
        agent_result=validated_result,
        agent_evaluation=agent_evaluation,
        market_context=market_context,
        bullish=bullish,
        bearish=bearish,
        independence_report=independence,
        conclusion=conclusion,
        disagreement_preserved=(bullish.available and bearish.available)
        or bool(market_context.conflicts)
        or market_context.confluence.state
        in {ConfluenceStateV2.CONFLICTING, ConfluenceStateV2.STRONGLY_CONFLICTING}
        or bool(market_context.adversarial.contradictory_evidence_ids),
        expires_at=expiry,
    )


__all__ = [
    "SpotDebateConclusion",
    "SpotDebateError",
    "SpotDebateResult",
    "SpotThesisBranch",
    "compose_spot_debate",
]


def _thesis_branches(
    confluence: ConfluenceAssessmentV3,
) -> tuple[SpotThesisBranch, SpotThesisBranch]:
    """Project only C-009's typed direction and exact evidence references."""

    if type(confluence) is not ConfluenceAssessmentV3:
        raise SpotDebateError("C-009 v3 is required to organize thesis evidence.")
    groups = tuple(
        tuple(item for item in confluence.components if item.direction is direction)
        for direction in (AnalyticalDirection.BULLISH, AnalyticalDirection.BEARISH)
    )
    return tuple(
        SpotThesisBranch(
            direction=direction,
            component_ids=tuple(item.component_id for item in group),
            components=group,
            evidence_ids=tuple(
                sorted(
                    {value for item in group for value in item.evidence_ids}, key=str
                )
            ),
            available=any(
                item.relation is EvidenceRelation.SUPPORTING for item in group
            ),
        )
        for direction, group in zip(
            (AnalyticalDirection.BULLISH, AnalyticalDirection.BEARISH), groups
        )
    )  # type: ignore[return-value]


def _conclusion(
    *,
    result_status: AgentResultStatus,
    confluence: ConfluenceAssessmentV3,
    conflicts: bool,
    bullish: SpotThesisBranch,
    bearish: SpotThesisBranch,
) -> SpotDebateConclusion:
    """Return an unresolved categorical handoff; never choose a winner."""

    if result_status is AgentResultStatus.NO_TRADE:
        return SpotDebateConclusion.NO_TRADE
    if result_status is not AgentResultStatus.COMPLETE:
        return SpotDebateConclusion.INSUFFICIENT_EVIDENCE
    if bullish.available and bearish.available:
        return SpotDebateConclusion.MIXED_OR_CONFLICTED
    if confluence.status.value == "INDETERMINATE":
        return SpotDebateConclusion.INSUFFICIENT_EVIDENCE
    if bullish.available:
        return SpotDebateConclusion.BULLISH_EVIDENCE_UNRESOLVED
    if bearish.available:
        return SpotDebateConclusion.BEARISH_EVIDENCE_UNRESOLVED
    if conflicts or confluence.state in {
        ConfluenceStateV2.CONFLICTING,
        ConfluenceStateV2.STRONGLY_CONFLICTING,
    }:
        return SpotDebateConclusion.MIXED_OR_CONFLICTED
    return SpotDebateConclusion.NO_DEFENSIBLE_DIRECTION
