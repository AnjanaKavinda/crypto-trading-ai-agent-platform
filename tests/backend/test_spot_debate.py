from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from trading_platform_api.agents.contracts import AgentResultStatus
from trading_platform_api.analysis.contracts import (
    AnalyticalDirection,
    EvidenceRelation,
    VersionReference,
)
from trading_platform_api.analysis.spot_meta_analysis import C093Registry
from trading_platform_api.analysis.versioned_contracts import (
    AnalyticalConfidenceReasonV2,
    AnalyticalConfidenceStateV2,
    AnalyticalConfidenceV2,
    ConfluenceEvidenceStrengthV2,
    ConfluenceReasonV2,
    ConfluenceStateV2,
    ConfluenceStatusV2,
    EvidenceDependenceV2,
)
from trading_platform_api.analysis.versioned_contracts_v4 import (
    AnalysisOutputReferenceV4,
    ConfluenceAssessmentV3,
    ConfluenceComponentV2,
)
from trading_platform_api.orchestration.spot_debate import (
    SpotDebateConclusion,
    SpotDebateError,
    _conclusion,
    _thesis_branches,
)

NOW = datetime(2026, 10, 30, 12, 0, tzinfo=UTC)


def _id(number: int) -> UUID:
    return UUID(f"00000000-0000-0000-0000-{number:012d}")


def _component(
    number: int, direction: AnalyticalDirection, evidence_id: UUID
) -> ConfluenceComponentV2:
    return ConfluenceComponentV2(
        component_id=_id(number),
        domain=f"synthetic-domain-{number}",
        direction=direction,
        relation=EvidenceRelation.SUPPORTING,
        evidence_strength=ConfluenceEvidenceStrengthV2.MODERATE,
        dependence=EvidenceDependenceV2.UNKNOWN,
        evidence_ids=(evidence_id,),
        input_binding_ids=(_id(90),),
    )


def _confluence(
    components: tuple[ConfluenceComponentV2, ...],
    *,
    status: ConfluenceStatusV2 = ConfluenceStatusV2.AVAILABLE,
) -> ConfluenceAssessmentV3:
    return ConfluenceAssessmentV3(
        assessment_id=_id(20),
        asset="BTC",
        instrument_id="BTC-USDT-SPOT",
        timeframe="1m",
        as_of=NOW,
        expires_at=NOW + timedelta(minutes=5),
        state=(
            ConfluenceStateV2.INDETERMINATE
            if status is ConfluenceStatusV2.INDETERMINATE
            else ConfluenceStateV2.PARTIALLY_ALIGNED
        ),
        status=status,
        status_reason=(
            ConfluenceReasonV2.INSUFFICIENT_EVIDENCE
            if status is ConfluenceStatusV2.INDETERMINATE
            else None
        ),
        components=components,
        analytical_confidence=AnalyticalConfidenceV2(
            AnalyticalConfidenceStateV2.UNAVAILABLE,
            None,
            None,
            AnalyticalConfidenceReasonV2.NOT_ASSESSED,
        ),
        evidence_strength=(
            ConfluenceEvidenceStrengthV2.UNKNOWN
            if status is ConfluenceStatusV2.INDETERMINATE
            else ConfluenceEvidenceStrengthV2.MODERATE
        ),
        independence_report=AnalysisOutputReferenceV4(
            "C-093",
            _id(21),
            C093Registry.schema_version,
            C093Registry.lineage_version,
            "a" * 64,
            C093Registry.method,
        ),
        input_snapshot_id=_id(22),
        input_snapshot_schema_version="4",
        data_quality_reports=(),
        evidence_ids=tuple(
            sorted({value for c in components for value in c.evidence_ids}, key=str)
        ),
        method=VersionReference("spot-confluence", "spot-confluence-v1"),
        provenance=(VersionReference("spot-profile", "v1"),),
    )


def test_directional_evidence_is_separated_and_exact_references_are_retained() -> None:
    bull_evidence, bear_evidence = _id(1), _id(2)
    confluence = _confluence(
        (
            _component(3, AnalyticalDirection.BULLISH, bull_evidence),
            _component(4, AnalyticalDirection.BEARISH, bear_evidence),
        )
    )

    bullish, bearish = _thesis_branches(confluence)

    assert bullish.available and bullish.evidence_ids == (bull_evidence,)
    assert bearish.available and bearish.evidence_ids == (bear_evidence,)
    assert bullish.component_ids == (_id(3),)
    assert bearish.component_ids == (_id(4),)


def test_missing_branch_is_unavailable_and_never_assigned_neutral_evidence() -> None:
    bullish, bearish = _thesis_branches(
        _confluence((_component(3, AnalyticalDirection.BULLISH, _id(1)),))
    )
    assert bullish.available
    assert not bearish.available
    assert bearish.evidence_ids == ()
    assert (
        _conclusion(
            result_status=AgentResultStatus.COMPLETE,
            confluence=_confluence(
                (_component(3, AnalyticalDirection.BULLISH, _id(1)),)
            ),
            conflicts=False,
            bullish=bullish,
            bearish=bearish,
        )
        is SpotDebateConclusion.BULLISH_EVIDENCE_UNRESOLVED
    )


def test_contradicting_only_component_does_not_become_thesis_support() -> None:
    component = replace(
        _component(3, AnalyticalDirection.BULLISH, _id(1)),
        relation=EvidenceRelation.CONTRADICTING,
    )
    bullish, bearish = _thesis_branches(_confluence((component,)))

    assert not bullish.available
    assert bullish.evidence_ids == (_id(1),)
    assert bullish.components == (component,)
    assert not bearish.available


def test_conflicting_branches_are_preserved_without_selecting_a_winner() -> None:
    confluence = _confluence(
        (
            _component(3, AnalyticalDirection.BULLISH, _id(1)),
            _component(4, AnalyticalDirection.BEARISH, _id(2)),
        )
    )
    bullish, bearish = _thesis_branches(confluence)

    assert (
        _conclusion(
            result_status=AgentResultStatus.COMPLETE,
            confluence=confluence,
            conflicts=True,
            bullish=bullish,
            bearish=bearish,
        )
        is SpotDebateConclusion.MIXED_OR_CONFLICTED
    )


def test_no_trade_and_indeterminate_analysis_remain_first_class() -> None:
    confluence = _confluence((), status=ConfluenceStatusV2.INDETERMINATE)
    bullish, bearish = _thesis_branches(confluence)

    assert (
        _conclusion(
            result_status=AgentResultStatus.COMPLETE,
            confluence=confluence,
            conflicts=False,
            bullish=bullish,
            bearish=bearish,
        )
        is SpotDebateConclusion.INSUFFICIENT_EVIDENCE
    )
    assert (
        _conclusion(
            result_status=AgentResultStatus.NO_TRADE,
            confluence=confluence,
            conflicts=False,
            bullish=bullish,
            bearish=bearish,
        )
        is SpotDebateConclusion.NO_TRADE
    )


def test_untyped_confluence_fails_closed() -> None:
    with pytest.raises(SpotDebateError, match="C-009 v3"):
        _thesis_branches(object())  # type: ignore[arg-type]
