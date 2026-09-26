from dataclasses import FrozenInstanceError, fields
from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal
from uuid import uuid4

import pytest
from trading_platform_api.analysis import (
    AdversarialAssessment,
    AgentIndependenceReference,
    AnalysisContractError,
    AnalysisSnapshot,
    AnalyticalDirection,
    AnalyticalFinding,
    AnalyticalUncertainty,
    AssessmentStatus,
    ClaimClassification,
    ConflictAssessment,
    ConfluenceAssessment,
    ConfluenceComponent,
    ConfluenceState,
    DerivativesAssessment,
    DomainObservation,
    EventRiskAssessment,
    EvidenceDependence,
    EvidenceItem,
    EvidenceRelation,
    FibonacciAssessment,
    FundamentalAssessment,
    MarketContext,
    MarketRegime,
    MethodologyCategory,
    OnChainAssessment,
    RegimeDimension,
    ResolutionStatus,
    SentimentAssessment,
    SMCAssessment,
    TechnicalAssessment,
    UncertaintyCategory,
    VersionReference,
    WyckoffAssessment,
)
from trading_platform_api.market_data import DataQualityStatus, DatasetVersionReference

T0 = datetime(2026, 1, 1, tzinfo=UTC)
T1 = T0 + timedelta(seconds=1)
T2 = T0 + timedelta(seconds=2)
HASH = "a" * 64


def version(component: str = "method") -> VersionReference:
    return VersionReference(component=component, version="v1")


def finding(**overrides: object) -> AnalyticalFinding:
    values: dict[str, object] = {
        "finding_id": uuid4(),
        "category": "trend",
        "classification": ClaimClassification.FACT,
        "statement": "Observed structure is rising.",
        "evidence_ids": (uuid4(),),
        "method": version(),
        "invalidation_condition": "Structure changes.",
        "limitations": (),
    }
    values.update(overrides)
    return AnalyticalFinding(**values)  # type: ignore[arg-type]


def observation(kind: str = "trend") -> DomainObservation:
    return DomainObservation(
        observation_type=kind,
        value="rising",
        unit=None,
        timeframe="1h",
        calculation=version("calculation"),
        evidence_ids=(uuid4(),),
    )


def assessment(cls: type[FundamentalAssessment], **overrides: object) -> object:
    observation_type = next(iter(cls.observation_categories))
    values: dict[str, object] = {
        "assessment_id": uuid4(),
        "asset": "BTC",
        "instrument_id": "BTC-USDT-SPOT",
        "timeframe": "1h",
        "as_of": T0,
        "available_at": T1,
        "expires_at": T2,
        "status": AssessmentStatus.AVAILABLE,
        "analytical_confidence": Decimal("0.7"),
        "findings": (finding(),),
        "observations": (observation(observation_type),),
        "evidence_ids": (uuid4(),),
        "contradiction_ids": (),
        "uncertainty_ids": (uuid4(),),
        "data_quality_report_id": uuid4(),
        "provenance": (version("agent"),),
    }
    values.update(overrides)
    return cls(**values)  # type: ignore[arg-type]


def regime(**overrides: object) -> MarketRegime:
    evidence_id = uuid4()
    values: dict[str, object] = {
        "regime_id": uuid4(),
        "asset": "BTC",
        "instrument_id": "BTC-USDT-SPOT",
        "timeframe": "1h",
        "as_of": T0,
        "expires_at": T2,
        "direction": AnalyticalDirection.MIXED,
        "dimensions": (
            RegimeDimension(
                name="volatility", state="high", evidence_ids=(evidence_id,)
            ),
        ),
        "explanation": "Volatility is elevated.",
        "confidence": Decimal("0.6"),
        "evidence_ids": (evidence_id,),
        "compatible_strategy_families": ("trend-following",),
    }
    values.update(overrides)
    return MarketRegime(**values)  # type: ignore[arg-type]


def confluence(**overrides: object) -> ConfluenceAssessment:
    values: dict[str, object] = {
        "assessment_id": uuid4(),
        "as_of": T0,
        "expires_at": T2,
        "state": ConfluenceState.CONFLICTING,
        "components": (
            ConfluenceComponent(
                domain="technical",
                direction=AnalyticalDirection.BULLISH,
                relation=EvidenceRelation.SUPPORTING,
                evidence_strength=Decimal("0.7"),
                dependence=EvidenceDependence.PARTIALLY_DEPENDENT,
                evidence_ids=(uuid4(),),
            ),
        ),
        "analytical_confidence": Decimal("0.5"),
        "evidence_strength": Decimal("0.6"),
        "independence_report": AgentIndependenceReference(uuid4(), "v1"),
        "explanation": "Evidence is not fully independent.",
    }
    values.update(overrides)
    return ConfluenceAssessment(**values)  # type: ignore[arg-type]


def conflict(**overrides: object) -> ConflictAssessment:
    values: dict[str, object] = {
        "assessment_id": uuid4(),
        "as_of": T0,
        "expires_at": T2,
        "finding_ids": (uuid4(),),
        "evidence_ids": (uuid4(),),
        "severity": Decimal("0.8"),
        "explanation": "Domains disagree.",
        "resolution_status": ResolutionStatus.UNRESOLVED,
    }
    values.update(overrides)
    return ConflictAssessment(**values)  # type: ignore[arg-type]


def uncertainty(**overrides: object) -> AnalyticalUncertainty:
    values: dict[str, object] = {
        "uncertainty_id": uuid4(),
        "category": UncertaintyCategory.DATA,
        "description": "Coverage is incomplete.",
        "affected_finding_ids": (uuid4(),),
        "affected_domains": ("on-chain",),
        "severity": Decimal("0.7"),
        "reducible": True,
        "required_evidence": ("additional source",),
        "as_of": T0,
        "expires_at": T2,
        "resolution_status": ResolutionStatus.UNRESOLVED,
    }
    values.update(overrides)
    return AnalyticalUncertainty(**values)  # type: ignore[arg-type]


def adversarial(**overrides: object) -> AdversarialAssessment:
    values: dict[str, object] = {
        "assessment_id": uuid4(),
        "as_of": T0,
        "expires_at": T2,
        "counter_thesis": "The observed move may be temporary.",
        "alternative_hypotheses": ("Liquidity effect",),
        "contradictory_evidence_ids": (uuid4(),),
        "failure_conditions": ("Structure reverses",),
        "data_limitations": ("Short history",),
        "measurement_error_risks": ("Source latency",),
        "confirmation_bias_concerns": ("Shared inputs",),
        "analytical_confidence": Decimal("0.5"),
    }
    values.update(overrides)
    return AdversarialAssessment(**values)  # type: ignore[arg-type]


ASSESSMENTS = (
    (FundamentalAssessment, "C-011", MethodologyCategory.FUNDAMENTAL),
    (TechnicalAssessment, "C-012", MethodologyCategory.TECHNICAL),
    (SMCAssessment, "C-013", MethodologyCategory.TECHNICAL),
    (WyckoffAssessment, "C-014", MethodologyCategory.TECHNICAL),
    (DerivativesAssessment, "C-015", None),
    (OnChainAssessment, "C-016", MethodologyCategory.ON_CHAIN),
    (SentimentAssessment, "C-017", MethodologyCategory.SENTIMENT),
    (EventRiskAssessment, "C-018", None),
    (FibonacciAssessment, "C-068", MethodologyCategory.TECHNICAL),
)


@pytest.mark.parametrize(("cls", "contract_id", "methodology"), ASSESSMENTS)
def test_distinct_domain_assessments_are_validated(
    cls: type[FundamentalAssessment],
    contract_id: str,
    methodology: MethodologyCategory | None,
) -> None:
    value = assessment(cls, methodology=methodology)
    assert value.contract_id == contract_id  # type: ignore[attr-defined]
    assert value.schema_version == "1"  # type: ignore[attr-defined]
    with pytest.raises(FrozenInstanceError):
        value.status = AssessmentStatus.INVALID  # type: ignore[attr-defined]
    with pytest.raises(AnalysisContractError, match="invalid for"):
        assessment(cls, observations=(observation("wrong-domain"),))


def test_evidence_preserves_lineage_freshness_and_provenance() -> None:
    evidence = EvidenceItem(
        evidence_id=uuid4(),
        source_record_ids=(uuid4(),),
        dataset_versions=(DatasetVersionReference("btc-hourly", "v1"),),
        feature_ids=("trend-1h",),
        classification=ClaimClassification.FACT,
        relation=EvidenceRelation.CONTRADICTING,
        observed_at=T0,
        available_at=T1,
        expires_at=T2,
        method=version(),
        value="elevated",
        unit=None,
        interpretation="Observed value is elevated.",
        quality_status=DataQualityStatus.VALID,
        data_quality_report_id=uuid4(),
        reliability=Decimal("0.8"),
        limitations=("One venue",),
        provenance=(version("agent"), version("configuration")),
        usable=True,
    )
    assert evidence.contract_id == "C-008"
    assert evidence.relation is EvidenceRelation.CONTRADICTING


@pytest.mark.parametrize(
    "quality",
    [DataQualityStatus.STALE, DataQualityStatus.INVALID, DataQualityStatus.UNAVAILABLE],
)
def test_unusable_quality_cannot_masquerade_as_usable(
    quality: DataQualityStatus,
) -> None:
    with pytest.raises(AnalysisContractError, match="cannot be marked usable"):
        EvidenceItem(
            uuid4(),
            (uuid4(),),
            (),
            (),
            ClaimClassification.FACT,
            EvidenceRelation.NEUTRAL,
            T0,
            T1,
            T2,
            version(),
            "x",
            None,
            "x",
            quality,
            uuid4(),
            Decimal("0.5"),
            (),
            (version("agent"),),
            True,
        )


def test_common_validation_rejects_bad_time_score_and_collections() -> None:
    with pytest.raises(AnalysisContractError, match="timezone-aware"):
        regime(as_of=datetime(2026, 1, 1))
    with pytest.raises(AnalysisContractError, match="must not be after"):
        regime(as_of=T2, expires_at=T1)
    with pytest.raises(AnalysisContractError, match="between 0 and 1"):
        regime(confidence=Decimal("1.1"))
    with pytest.raises(AnalysisContractError, match="must be a tuple"):
        regime(evidence_ids=[uuid4()])
    with pytest.raises(AnalysisContractError, match="surrounding whitespace"):
        regime(asset=" BTC")


def test_times_normalize_to_utc() -> None:
    offset = datetime(
        2026, 1, 1, 5, 30, tzinfo=timezone(timedelta(hours=5, minutes=30))
    )
    value = regime(as_of=offset, expires_at=offset + timedelta(seconds=2))
    assert value.as_of == T0
    assert value.as_of.tzinfo is UTC


def test_confluence_keeps_confidence_strength_and_independence_separate() -> None:
    value = confluence()
    assert value.analytical_confidence != value.evidence_strength
    assert value.independence_report.contract_id == "C-093"
    assert fields(AgentIndependenceReference)[0].name == "report_id"


def test_conflict_uncertainty_and_adversarial_state_remain_explicit() -> None:
    assert conflict().resolution_status is ResolutionStatus.UNRESOLVED
    assert uncertainty().required_evidence == ("additional source",)
    assert adversarial().alternative_hypotheses == ("Liquidity effect",)
    with pytest.raises(AnalysisContractError, match="requires evidence"):
        uncertainty(required_evidence=())


def test_analysis_snapshot_is_reproducible_and_integrity_bound() -> None:
    value = AnalysisSnapshot(
        snapshot_id=uuid4(),
        asset="BTC",
        instrument_id="BTC-USDT-SPOT",
        timeframe="1h",
        as_of=T0,
        created_at=T1,
        expires_at=T2,
        market_snapshot_id=uuid4(),
        data_quality_report_id=uuid4(),
        feature_set_ids=(uuid4(),),
        dataset_versions=(DatasetVersionReference("btc-hourly", "v1"),),
        assessment_ids=(uuid4(),),
        evidence_ids=(uuid4(),),
        provenance=(version("agent"), version("model"), version("prompt")),
        content_sha256=HASH,
    )
    assert value.contract_id == "C-007"
    with pytest.raises(AnalysisContractError, match="SHA-256"):
        AnalysisSnapshot(
            value.snapshot_id,
            value.asset,
            value.instrument_id,
            value.timeframe,
            value.as_of,
            value.created_at,
            value.expires_at,
            value.market_snapshot_id,
            value.data_quality_report_id,
            value.feature_set_ids,
            value.dataset_versions,
            value.assessment_ids,
            value.evidence_ids,
            value.provenance,
            "invalid",
        )


def test_market_context_composes_analysis_without_trading_authority() -> None:
    domain_assessments = tuple(
        assessment(cls, methodology=methodology) for cls, _, methodology in ASSESSMENTS
    )
    value = MarketContext(
        context_id=uuid4(),
        asset="BTC",
        instrument_id="BTC-USDT-SPOT",
        as_of=T0,
        expires_at=T2,
        multi_timeframe_state=("1h mixed", "4h rising"),
        regime=regime(),
        assessments=domain_assessments,
        confluence=confluence(),
        conflicts=(conflict(),),
        adversarial=adversarial(),
        uncertainties=(uncertainty(),),
        evidence_ids=(uuid4(),),
        analysis_snapshot_id=uuid4(),
        data_quality_report_id=uuid4(),
    )
    assert value.contract_id == "C-006"
    forbidden = {
        "signal",
        "order",
        "approval",
        "leverage",
        "position_size",
        "win_rate",
        "profit_probability",
        "execution",
    }
    assert forbidden.isdisjoint(item.name for item in fields(value))


def test_all_seventeen_canonical_contract_ids() -> None:
    domain_ids = {contract_id for _, contract_id, _ in ASSESSMENTS}
    remaining = {
        regime().contract_id,
        confluence().contract_id,
        conflict().contract_id,
        uncertainty().contract_id,
        adversarial().contract_id,
        EvidenceItem.__dataclass_fields__["contract_id"].default,
        AnalysisSnapshot.__dataclass_fields__["contract_id"].default,
        MarketContext.__dataclass_fields__["contract_id"].default,
    }
    assert domain_ids | remaining == {
        "C-005",
        "C-006",
        "C-007",
        "C-008",
        "C-009",
        "C-010",
        "C-011",
        "C-012",
        "C-013",
        "C-014",
        "C-015",
        "C-016",
        "C-017",
        "C-018",
        "C-019",
        "C-068",
        "C-069",
    }
