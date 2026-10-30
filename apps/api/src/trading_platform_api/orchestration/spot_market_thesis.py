"""Compose a bounded Spot thesis view from the validated debate handoff.

This projection adds no market interpretation. It organizes the exact C-009
components already validated by ``compose_spot_debate`` into explicit bull,
bear, and neutral cases, while retaining the source artifacts and their
uncertainty, conflict, adversarial, and dependence semantics.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import NAMESPACE_URL, UUID, uuid5

from trading_platform_api.analysis.contracts import (
    AnalyticalDirection,
    AnalyticalUncertainty,
    EvidenceRelation,
)
from trading_platform_api.analysis.versioned_contracts_v4 import (
    ConflictAssessmentV3,
    ConfluenceComponentV2,
)
from trading_platform_api.orchestration.spot_debate import (
    SpotDebateConclusion,
    SpotDebateResult,
)


class SpotMarketThesisError(ValueError):
    """Raised when a debate handoff cannot safely produce a thesis view."""


class ThesisCaseState(StrEnum):
    AVAILABLE = "AVAILABLE"
    UNAVAILABLE = "UNAVAILABLE"


class ThesisAssumptionState(StrEnum):
    NOT_PROVIDED_BY_APPROVED_INPUTS = "NOT_PROVIDED_BY_APPROVED_INPUTS"


class ThesisInvalidationState(StrEnum):
    UNASSIGNED = "UNASSIGNED"


@dataclass(frozen=True, slots=True)
class SpotThesisCase:
    """One directional or neutral case, supported only by exact C-009 refs."""

    direction: AnalyticalDirection
    state: ThesisCaseState
    supporting_component_ids: tuple[UUID, ...]
    supporting_evidence_ids: tuple[UUID, ...]
    contradictory_component_ids: tuple[UUID, ...]
    contradictory_evidence_ids: tuple[UUID, ...]
    assumptions: tuple[str, ...]
    assumptions_state: ThesisAssumptionState


@dataclass(frozen=True, slots=True)
class ThesisInvalidationCandidate:
    """An exact C-019 failure condition not assigned to a case or action."""

    text: str
    source_contract_id: str
    source_schema_version: str
    source_assessment_id: UUID
    state: ThesisInvalidationState


@dataclass(frozen=True, slots=True)
class SpotMarketThesis:
    """Deterministic, non-authoritative Spot thesis projection."""

    thesis_id: UUID
    schema_version: str
    context_id: UUID
    task_id: UUID
    correlation_id: UUID
    trace_id: UUID
    bullish: SpotThesisCase
    bearish: SpotThesisCase
    base: SpotThesisCase
    invalidation_candidates: tuple[ThesisInvalidationCandidate, ...]
    source_debate: SpotDebateResult
    unresolved_conflicts: tuple[ConflictAssessmentV3, ...]
    unresolved_uncertainties: tuple[AnalyticalUncertainty, ...]
    critic_contradictory_evidence_ids: tuple[UUID, ...]
    decision_state: SpotDebateConclusion
    no_trade_compatible: bool
    as_of: datetime
    expires_at: datetime


def compose_spot_market_thesis(
    debate: SpotDebateResult, *, now: datetime
) -> SpotMarketThesis:
    """Project a validated #75 debate without recalculating or voting.

    C-009, C-010, C-019, C-069, and C-093 are carried through by reference in
    ``source_debate``. Empty cases remain unavailable. C-019 failure conditions
    are retained verbatim as unassigned invalidation candidates because the
    approved input does not bind each condition to one thesis branch.
    """

    if type(debate) is not SpotDebateResult:
        raise SpotMarketThesisError("a validated SpotDebateResult is required.")
    if (
        not isinstance(now, datetime)
        or now.tzinfo is None
        or now.utcoffset() is None
        or debate.expires_at <= now
    ):
        raise SpotMarketThesisError("debate handoff must be current and unexpired.")
    if (
        debate.market_context.context_id != debate.context_id
        or debate.agent_result.context_id != debate.context_id
        or debate.agent_result.task_id != debate.task_id
        or debate.agent_evaluation.context_id != debate.context_id
        or debate.agent_evaluation.task_id != debate.task_id
        or debate.agent_evaluation.correlation_id != debate.correlation_id
        or debate.agent_evaluation.trace_id != debate.trace_id
        or debate.agent_result.output != debate.market_context
    ):
        raise SpotMarketThesisError("debate identity or C-006 binding is mismatched.")
    if debate.market_context.expires_at <= now:
        raise SpotMarketThesisError("C-006 context is stale or expired.")

    context = debate.market_context
    thesis_id = uuid5(
        NAMESPACE_URL,
        "personal-spot-market-thesis/v1/"
        f"{debate.result_id}/{debate.context_id}/"
        f"{debate.correlation_id}/{debate.trace_id}",
    )
    invalidation_candidates = tuple(
        ThesisInvalidationCandidate(
            text=condition,
            source_contract_id=context.adversarial.contract_id,
            source_schema_version=context.adversarial.schema_version,
            source_assessment_id=context.adversarial.assessment_id,
            state=ThesisInvalidationState.UNASSIGNED,
        )
        for condition in context.adversarial.failure_conditions
    )

    return SpotMarketThesis(
        thesis_id=thesis_id,
        schema_version="1",
        context_id=debate.context_id,
        task_id=debate.task_id,
        correlation_id=debate.correlation_id,
        trace_id=debate.trace_id,
        bullish=_case(context.confluence.components, AnalyticalDirection.BULLISH),
        bearish=_case(context.confluence.components, AnalyticalDirection.BEARISH),
        base=_case(context.confluence.components, AnalyticalDirection.NEUTRAL),
        invalidation_candidates=invalidation_candidates,
        source_debate=debate,
        unresolved_conflicts=context.conflicts,
        unresolved_uncertainties=context.uncertainties,
        critic_contradictory_evidence_ids=(
            context.adversarial.contradictory_evidence_ids
        ),
        decision_state=debate.conclusion,
        no_trade_compatible=True,
        as_of=context.as_of,
        expires_at=min(debate.expires_at, context.expires_at),
    )


def _case(
    components: tuple[ConfluenceComponentV2, ...], direction: AnalyticalDirection
) -> SpotThesisCase:
    selected = tuple(item for item in components if item.direction is direction)
    supporting = tuple(
        item for item in selected if item.relation is EvidenceRelation.SUPPORTING
    )
    contradictory = tuple(
        item for item in selected if item.relation is EvidenceRelation.CONTRADICTING
    )
    return SpotThesisCase(
        direction=direction,
        state=(ThesisCaseState.AVAILABLE if supporting else ThesisCaseState.UNAVAILABLE),
        supporting_component_ids=tuple(item.component_id for item in supporting),
        supporting_evidence_ids=_ordered_evidence(supporting),
        contradictory_component_ids=tuple(item.component_id for item in contradictory),
        contradictory_evidence_ids=_ordered_evidence(contradictory),
        assumptions=(),
        assumptions_state=ThesisAssumptionState.NOT_PROVIDED_BY_APPROVED_INPUTS,
    )


def _ordered_evidence(
    components: tuple[ConfluenceComponentV2, ...],
) -> tuple[UUID, ...]:
    return tuple(
        sorted(
            {evidence_id for item in components for evidence_id in item.evidence_ids},
            key=str,
        )
    )


__all__ = [
    "SpotMarketThesis",
    "SpotMarketThesisError",
    "SpotThesisCase",
    "ThesisAssumptionState",
    "ThesisCaseState",
    "ThesisInvalidationCandidate",
    "ThesisInvalidationState",
    "compose_spot_market_thesis",
]
