from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID

import pytest
from trading_platform_api.analysis import (
    AgentIndependenceReferenceV2,
    AnalysisContractError,
    AnalysisOutputReferenceV3,
    AnalysisV2ContractError,
    AnalyticalConfidenceV2,
    AnalyticalDirection,
    ConfidenceStatusV2,
    ConflictAssessmentV2,
    ConflictSeverityV2,
    ConfluenceAssessmentV2,
    ConfluenceComponentV2,
    ConfluenceReasonV2,
    ConfluenceStateV2,
    ConfluenceStatusV2,
    EvidenceDependenceV2,
    EvidenceRelation,
    EvidenceStrengthLevel,
    ResolutionStatus,
    VersionReference,
    decode_analysis_contract,
    encode_analysis_contract,
)

NOW = datetime(2026, 10, 18, tzinfo=UTC)
EXPIRES = NOW + timedelta(minutes=1)


def _id(number: int) -> UUID:
    return UUID(f"00000000-0000-0000-0000-{number:012d}")


def _independence_reference() -> AgentIndependenceReferenceV2:
    return AgentIndependenceReferenceV2(
        _id(900), "agent-independence-v1", "1", "1", "a" * 64
    )


def _unavailable_confidence() -> AnalyticalConfidenceV2:
    return AnalyticalConfidenceV2(
        ConfidenceStatusV2.UNAVAILABLE, None, None, "NO_VERSIONED_METHOD"
    )


def test_c009_v2_round_trips_unknown_and_shared_source_dependence() -> None:
    evidence_id = _id(10)
    component = ConfluenceComponentV2(
        "spot-ohlcv",
        AnalyticalDirection.MIXED,
        EvidenceRelation.SUPPORTING,
        EvidenceStrengthLevel.UNKNOWN,
        EvidenceDependenceV2.HIGHLY_CORRELATED,
        (evidence_id,),
        VersionReference("spot-confluence", "spot-profile-v1"),
    )
    assessment = ConfluenceAssessmentV2(
        _id(1),
        "BTC-USDT-SPOT",
        "1m",
        _id(2),
        _id(3),
        NOW,
        EXPIRES,
        ConfluenceStatusV2.PARTIAL,
        ConfluenceReasonV2.INSUFFICIENT_EVIDENCE,
        ConfluenceStateV2.INDETERMINATE,
        (component,),
        _unavailable_confidence(),
        EvidenceStrengthLevel.UNKNOWN,
        _independence_reference(),
        (evidence_id,),
        (VersionReference("C-009-calculation", "2"),),
        "The available same-snapshot evidence is correlated and does not establish independent agreement.",
    )

    encoded = encode_analysis_contract(assessment)
    decoded = decode_analysis_contract(encoded)

    assert decoded == assessment
    assert assessment.schema_version == "2"
    assert component.dependence is EvidenceDependenceV2.HIGHLY_CORRELATED
    assert assessment.analytical_confidence.value is None


@pytest.mark.parametrize(
    ("status", "value", "method", "reason"),
    (
        (ConfidenceStatusV2.AVAILABLE, Decimal("0.5"), None, None),
        (ConfidenceStatusV2.UNAVAILABLE, Decimal("0"), None, "NO_VERSIONED_METHOD"),
    ),
)
def test_analytical_confidence_requires_explicit_value_method_or_reason(
    status: ConfidenceStatusV2,
    value: Decimal,
    method: VersionReference | None,
    reason: str | None,
) -> None:
    with pytest.raises(AnalysisContractError):
        AnalyticalConfidenceV2(status, value, method, reason)


def test_available_confidence_requires_versioned_method_and_bounds() -> None:
    assert AnalyticalConfidenceV2(
        ConfidenceStatusV2.AVAILABLE,
        Decimal("0.5"),
        VersionReference("interpretive-confidence", "1"),
        None,
    ).value == Decimal("0.5")
    with pytest.raises(AnalysisContractError, match=r"\[0, 1\]"):
        AnalyticalConfidenceV2(
            ConfidenceStatusV2.AVAILABLE,
            Decimal("1.1"),
            VersionReference("interpretive-confidence", "1"),
            None,
        )


def test_c009_v2_rejects_available_alignment_without_evidence() -> None:
    with pytest.raises(AnalysisContractError, match="Available confluence"):
        ConfluenceAssessmentV2(
            _id(1),
            "BTC-USDT-SPOT",
            "1m",
            _id(2),
            _id(3),
            NOW,
            EXPIRES,
            ConfluenceStatusV2.AVAILABLE,
            None,
            ConfluenceStateV2.ALIGNED,
            (),
            _unavailable_confidence(),
            EvidenceStrengthLevel.UNKNOWN,
            _independence_reference(),
            (),
            (VersionReference("C-009-calculation", "2"),),
            "No evidence is available.",
        )


def test_c009_v2_unavailable_is_explicit_and_has_no_synthetic_score() -> None:
    assessment = ConfluenceAssessmentV2(
        _id(1),
        "BTC-USDT-SPOT",
        "1m",
        _id(2),
        _id(3),
        NOW,
        EXPIRES,
        ConfluenceStatusV2.UNAVAILABLE,
        ConfluenceReasonV2.QUALITY_NOT_VALID,
        ConfluenceStateV2.INDETERMINATE,
        (),
        _unavailable_confidence(),
        EvidenceStrengthLevel.UNKNOWN,
        _independence_reference(),
        (),
        (VersionReference("C-009-calculation", "2"),),
        "Required evidence failed the quality gate.",
    )
    assert decode_analysis_contract(encode_analysis_contract(assessment)) == assessment
    assert assessment.analytical_confidence.value is None
    assert assessment.evidence_strength is EvidenceStrengthLevel.UNKNOWN


def test_c010_v2_round_trips_categorical_unknown_severity() -> None:
    conflict = ConflictAssessmentV2(
        _id(20),
        "BTC-USDT-SPOT",
        "1m",
        _id(2),
        _id(3),
        NOW,
        EXPIRES,
        (_id(21),),
        (_id(22),),
        ConflictSeverityV2.UNKNOWN,
        VersionReference("conflict-severity-table", "2"),
        "Evidence does not establish the materiality of this conflict.",
        ResolutionStatus.UNRESOLVED,
        (VersionReference("C-010-assessment", "2"),),
    )
    assert decode_analysis_contract(encode_analysis_contract(conflict)) == conflict
    assert conflict.schema_version == "2"


def test_c007_v3_output_reference_rejects_unsupported_nested_schema() -> None:
    with pytest.raises(AnalysisV2ContractError, match="schema version mismatch"):
        AnalysisOutputReferenceV3("C-009", _id(40), "1", "1", "a" * 64)
