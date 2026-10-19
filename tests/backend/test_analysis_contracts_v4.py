"""Synthetic compatibility and canonical-wire tests for the Spot C-007 v4 path."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from hashlib import sha256
from types import SimpleNamespace
from uuid import UUID

import pytest
from trading_platform_api.analysis import (
    C006_V5_LINEAGE_VERSION,
    C006_V5_SCHEMA_VERSION,
    C019_V2_LINEAGE_VERSION,
    C019_V2_SCHEMA_VERSION,
    AdversarialAssessment,
    AdversarialAssessmentV2,
    AdversarialEvidenceReferenceV2,
    AnalysisOutputReferenceV4,
    AnalysisRecordReference,
    AnalysisSnapshotReferenceV4,
    AnalysisV2ContractError,
    AnalyticalConfidenceReasonV2,
    AnalyticalConfidenceStateV2,
    AnalyticalConfidenceV2,
    AnalyticalDirection,
    AnalyticalUncertainty,
    AssessmentStatus,
    C093Registry,
    ClaimClassification,
    ConflictAssessmentV3,
    ConflictCalculationState,
    ConflictEvidenceStateV2,
    ConflictMaterialityV2,
    ConflictReasonV2,
    ConflictSeverityV2,
    ConfluenceAssessmentV3,
    ConfluenceCalculationState,
    ConfluenceComponentV2,
    ConfluenceEvidenceStrengthV2,
    ConfluenceStateV2,
    ConfluenceStatusV2,
    DependenceFactor,
    DomainObservation,
    EvidenceDependenceV2,
    EvidenceItemV2,
    EvidenceRelation,
    FindingReadiness,
    FundamentalAssessment,
    InputModalityV4,
    MarketContextV4,
    MarketContextV5,
    MarketRegime,
    MetaAnalysisReason,
    ObservationSourceBinding,
    RegimeDimension,
    ResolutionStatus,
    SpotMetaFinding,
    SpotOHLCVBindingV4,
    UncertaintyCategory,
    VersionReference,
    analysis_snapshot_v4_sha256,
    assess_agent_independence,
    calculate_spot_conflicts_v3,
    calculate_spot_confluence_v3,
    calculate_spot_market_regime,
    create_analysis_snapshot_v4,
    decode_analysis_contract,
    encode_analysis_contract,
    resolve_analysis_snapshot_v4,
    validate_evidence_item_v2_for_v4,
    validate_market_context_v4,
    validate_market_context_v5,
)
from trading_platform_api.analysis.spot_meta_analysis import _conflict_severity
from trading_platform_api.contracts.serialization import canonical_sha256
from trading_platform_api.market_data import (
    AssessmentPolicyReference,
    DataQualityStatus,
    DataSourceRecord,
    MarketData,
    MarketSnapshot,
    MetricValue,
    ProviderBatch,
    ProviderBatchStatus,
    ProviderDataKind,
    assess_complete_binance_spot_batch,
)
from trading_platform_api.market_data.quality import assess_approved_spot_ohlcv_v2
from trading_platform_api.spot_research import approved_quality_policy_template

NOW = datetime(2026, 10, 19, 12, 0, tzinfo=UTC)
HASH = "a" * 64


def _id(number: int) -> UUID:
    return UUID(f"00000000-0000-0000-0000-{number:012d}")


def _evidence(
    binding_id: UUID, observation_id: UUID, source_id: UUID
) -> EvidenceItemV2:
    return EvidenceItemV2(
        _id(5),
        (binding_id,),
        (observation_id,),
        (source_id,),
        (),
        ("spot:close:1m",),
        ClaimClassification.FACT,
        EvidenceRelation.SUPPORTING,
        NOW - timedelta(minutes=1),
        NOW - timedelta(seconds=30),
        NOW + timedelta(seconds=30),
        VersionReference("spot-market-regime", "spot-market-regime-v1"),
        "100.0",
        "USDT",
        "Synthetic test evidence.",
        DataQualityStatus.VALID,
        Decimal("1"),
        (),
        (
            VersionReference("spot-market-regime", "spot-market-regime-v1"),
            VersionReference(
                "spot-ohlcv-regime-profile", "spot-ohlcv-regime-profile-v1"
            ),
        ),
        True,
    )


def _manifest(evidence: EvidenceItemV2):
    binding_id = evidence.binding_ids[0]
    observation_id = evidence.observation_ids[0]
    source_id = evidence.source_record_ids[0]
    regime = AnalysisOutputReferenceV4("C-005", _id(6), "1", "1", HASH)
    evidence_ref = AnalysisOutputReferenceV4(
        "C-008", evidence.evidence_id, "2", "2", canonical_sha256(evidence)
    )
    binding = SpotOHLCVBindingV4(
        binding_id,
        InputModalityV4.SPOT_OHLCV,
        AnalysisRecordReference("C-002", str(_id(1)), "1", "1", HASH),
        NOW - timedelta(minutes=1),
        NOW,
        "BTC-USDT-SPOT",
        "BINANCE-SPOT",
        "1m",
        NOW - timedelta(minutes=2),
        NOW,
        AnalysisRecordReference("C-003", str(_id(2)), "2", "2", HASH),
        # This fixture checks the contract's wire closure. The full resolver
        # obtains this policy from the authoritative C-003 registry.
        AssessmentPolicyReference("personal-binance-spot-ohlcv-v1", "1"),
        (
            ObservationSourceBinding(
                AnalysisRecordReference("C-001", str(observation_id), "1", "1", HASH),
                AnalysisRecordReference("C-091", str(source_id), "1", "1", HASH),
            ),
        ),
        (AnalysisRecordReference("C-091", str(source_id), "1", "1", HASH),),
        regime,
        VersionReference("spot-market-regime", "spot-market-regime-v1"),
        VersionReference("spot-ohlcv-regime-profile", "spot-ohlcv-regime-profile-v1"),
        (evidence_ref,),
    )
    refs = tuple(
        sorted(
            (regime, evidence_ref),
            key=lambda item: (item.contract_id, str(item.record_id)),
        )
    )
    return create_analysis_snapshot_v4(
        snapshot_id=_id(7),
        asset="BTC",
        instrument_id="BTC-USDT-SPOT",
        venue_id="BINANCE-SPOT",
        timeframe="1m",
        analysis_cutoff=NOW,
        created_at=NOW,
        expires_at=NOW + timedelta(minutes=1),
        bindings=(binding,),
        assessment_ids=(_id(8),),
        evidence_ids=(evidence.evidence_id,),
        provenance=(
            VersionReference("spot-market-regime", "spot-market-regime-v1"),
            VersionReference(
                "spot-ohlcv-regime-profile", "spot-ohlcv-regime-profile-v1"
            ),
        ),
        analysis_outputs=refs,
    )


def test_c007_v4_wire_round_trip_and_digest_commit_to_binding_and_outputs() -> None:
    evidence = _evidence(_id(3), _id(4), _id(9))
    manifest = _manifest(evidence)

    assert manifest.content_sha256 == analysis_snapshot_v4_sha256(manifest)
    assert decode_analysis_contract(encode_analysis_contract(manifest)) == manifest
    assert manifest.schema_version == "4"
    assert manifest.bindings[0].modality == "spot-ohlcv"

    changed_evidence = AnalysisOutputReferenceV4(
        "C-008", evidence.evidence_id, "2", "2", "b" * 64
    )
    changed_binding = SpotOHLCVBindingV4(
        **{
            **{
                field: getattr(manifest.bindings[0], field)
                for field in manifest.bindings[0].__dataclass_fields__
                if field not in {"evidence"}
            },
            "evidence": (changed_evidence,),
        }
    )
    changed_refs = tuple(
        sorted(
            (manifest.bindings[0].regime, changed_evidence),
            key=lambda item: (item.contract_id, str(item.record_id)),
        )
    )
    changed_manifest = create_analysis_snapshot_v4(
        **{
            **{
                field: getattr(manifest, field)
                for field in manifest.__dataclass_fields__
                if field
                not in {
                    "content_sha256",
                    "bindings",
                    "analysis_outputs",
                    "contract_id",
                    "schema_version",
                }
            },
            "bindings": (changed_binding,),
            "analysis_outputs": changed_refs,
        }
    )
    assert changed_manifest.content_sha256 != manifest.content_sha256


def test_c008_v2_evidence_is_validated_against_v4_without_wire_conversion() -> None:
    evidence = _evidence(_id(3), _id(4), _id(9))
    manifest = _manifest(evidence)
    observation = SimpleNamespace(
        market_data_id=_id(4),
        source_record_id=_id(9),
        event_time=NOW - timedelta(minutes=1),
        availability_time=NOW - timedelta(seconds=30),
    )
    source = SimpleNamespace(
        source_record_id=_id(9),
        provider_event_time=NOW - timedelta(minutes=1),
        retrieval_time=NOW - timedelta(seconds=30),
        availability_time=NOW - timedelta(seconds=30),
    )
    resolved = SimpleNamespace(
        binding=manifest.bindings[0],
        observations=(observation,),
        sources=(source,),
        dataset=None,
        dependency_expires_at=NOW + timedelta(minutes=1),
        report=SimpleNamespace(status=DataQualityStatus.VALID),
    )

    original_wire = encode_analysis_contract(evidence)
    decoded = decode_analysis_contract(original_wire)
    assert decoded == evidence
    validate_evidence_item_v2_for_v4(
        evidence, manifest, resolved_bindings=(resolved,), now=NOW
    )
    assert encode_analysis_contract(decoded) == original_wire

    with pytest.raises(AnalysisV2ContractError, match="source closure"):
        invalid = replace(evidence, source_record_ids=(_id(10),))
        validate_evidence_item_v2_for_v4(
            invalid, manifest, resolved_bindings=(resolved,), now=NOW
        )


def test_v4_output_references_pin_owned_versions_but_leave_c093_registry_owned() -> (
    None
):
    assert AnalysisOutputReferenceV4("C-005", _id(1), "1", "1", HASH)
    assert AnalysisOutputReferenceV4("C-008", _id(2), "2", "2", HASH)
    assert AnalysisOutputReferenceV4("C-009", _id(3), "3", "3", HASH)
    assert AnalysisOutputReferenceV4("C-010", _id(4), "3", "3", HASH)
    # C-093 versions are supplied by the #67 owner registry, not guessed here.
    assert AnalysisOutputReferenceV4(
        "C-093",
        _id(5),
        "owner-schema",
        "owner-lineage",
        HASH,
        VersionReference("owner-method", "owner-method-version"),
    )
    with pytest.raises(AnalysisV2ContractError, match="version mismatch"):
        AnalysisOutputReferenceV4("C-009", _id(3), "2", "2", HASH)


def test_c009_c010_v3_preserve_categorical_semantics_and_round_trip() -> None:
    evidence_id = _id(31)
    binding_id = _id(32)
    snapshot_id = _id(33)
    report = AnalysisRecordReference("C-003", str(_id(34)), "2", "2", HASH)
    c093 = AnalysisOutputReferenceV4(
        "C-093",
        _id(35),
        "registry-schema",
        "registry-lineage",
        HASH,
        VersionReference("owner-method", "owner-method-version"),
    )
    confluence = ConfluenceAssessmentV3(
        _id(36),
        "BTC",
        "BTC-USDT-SPOT",
        "1m",
        NOW,
        NOW + timedelta(minutes=1),
        ConfluenceStateV2.PARTIALLY_ALIGNED,
        ConfluenceStatusV2.AVAILABLE,
        None,
        (
            ConfluenceComponentV2(
                _id(37),
                "spot-ohlcv-trend",
                AnalyticalDirection.MIXED,
                EvidenceRelation.SUPPORTING,
                ConfluenceEvidenceStrengthV2.MODERATE,
                EvidenceDependenceV2.PARTIALLY_DEPENDENT,
                (evidence_id,),
                (binding_id,),
            ),
        ),
        AnalyticalConfidenceV2(
            AnalyticalConfidenceStateV2.AVAILABLE,
            Decimal("0.5"),
            VersionReference("deterministic-confidence", "v1"),
            None,
        ),
        ConfluenceEvidenceStrengthV2.MODERATE,
        c093,
        snapshot_id,
        "4",
        (report,),
        (evidence_id,),
        VersionReference("confluence-method", "v3"),
        (VersionReference("spot-profile", "v1"),),
    )
    assert confluence.schema_version == "3"
    assert decode_analysis_contract(encode_analysis_contract(confluence)) == confluence
    with pytest.raises(AnalysisV2ContractError, match="schema 4"):
        replace(confluence, input_snapshot_schema_version="3")

    conflict = ConflictAssessmentV3(
        _id(38),
        "BTC",
        "BTC-USDT-SPOT",
        "1m",
        NOW,
        NOW + timedelta(minutes=1),
        (),
        (),
        ConflictSeverityV2.UNKNOWN,
        ConflictEvidenceStateV2.MISSING,
        ConflictMaterialityV2.UNKNOWN,
        None,
        None,
        None,
        ConflictReasonV2.MISSING_EVIDENCE,
        "No conflict finding was established from missing evidence.",
        ResolutionStatus.UNRESOLVED,
        snapshot_id,
        "4",
        (report,),
        VersionReference("conflict-method", "v3"),
        (VersionReference("spot-profile", "v1"),),
    )
    assert conflict.schema_version == "3"
    assert decode_analysis_contract(encode_analysis_contract(conflict)) == conflict

    assessment = FundamentalAssessment(
        _id(39),
        "BTC",
        "BTC-USDT-SPOT",
        "1m",
        NOW,
        NOW,
        NOW + timedelta(minutes=1),
        AssessmentStatus.UNAVAILABLE,
        Decimal("0.5"),
        (),
        (
            DomainObservation(
                "use-case",
                "outside bounded profile",
                None,
                "1m",
                VersionReference("synthetic-fundamental-method", "v1"),
                (evidence_id,),
            ),
        ),
        (evidence_id,),
        (),
        (),
        UUID(report.record_id),
        (VersionReference("fundamental-profile", "v1"),),
    )
    regime = MarketRegime(
        _id(40),
        "BTC",
        "BTC-USDT-SPOT",
        "1m",
        NOW,
        NOW + timedelta(minutes=1),
        AnalyticalDirection.MIXED,
        (RegimeDimension("trend", "mixed", (evidence_id,)),),
        "Synthetic versioned context fixture.",
        Decimal("0"),
        (evidence_id,),
        (),
    )
    adversarial = AdversarialAssessment(
        _id(41),
        NOW,
        NOW + timedelta(minutes=1),
        "A counter-thesis is required.",
        ("Synthetic alternative",),
        (),
        ("The evidence expires",),
        (),
        (),
        (),
        Decimal("0.5"),
    )
    uncertainty = AnalyticalUncertainty(
        _id(42),
        UncertaintyCategory.DATA,
        "Synthetic uncertainty.",
        (),
        ("spot",),
        Decimal("0.2"),
        False,
        (),
        NOW,
        NOW + timedelta(minutes=1),
        ResolutionStatus.UNRESOLVED,
    )
    context = MarketContextV4(
        _id(43),
        "BTC",
        "BTC-USDT-SPOT",
        NOW,
        NOW + timedelta(minutes=1),
        ("1m",),
        regime,
        (assessment,),
        confluence,
        (conflict,),
        adversarial,
        (uncertainty,),
        (evidence_id,),
        AnalysisSnapshotReferenceV4(snapshot_id, "4", HASH),
    )
    assert context.schema_version == "4"
    assert decode_analysis_contract(encode_analysis_contract(context)) == context


def test_v4_resolver_binds_synthetic_spot_c005_and_c008_to_exact_ohlcv() -> None:
    count = 50
    step = timedelta(minutes=1)
    start = NOW - count * step
    observations: list[MarketData] = []
    sources: list[DataSourceRecord] = []
    for index in range(count):
        opened = start + index * step
        closed = opened + step
        source_id = _id(1000 + index)
        close = Decimal(100 + index)
        sources.append(
            DataSourceRecord(
                source_id,
                "binance-spot-public",
                "spot-api-2026-09",
                opened,
                closed,
                closed,
                "spot-public-v1",
                "binance-spot-adapter-v1",
                "synthetic-test-terms",
                HASH,
            )
        )
        observations.append(
            MarketData(
                _id(2000 + index),
                "BTC-USDT-SPOT",
                "BINANCE-SPOT",
                "OHLCV",
                opened,
                opened,
                closed,
                closed,
                source_id,
                (
                    MetricValue("open", close - Decimal("0.2"), "USDT"),
                    MetricValue("high", close + Decimal("1"), "USDT"),
                    MetricValue("low", close - Decimal("1"), "USDT"),
                    MetricValue("close", close, "USDT"),
                    MetricValue("volume", Decimal("2"), "BTC"),
                ),
            )
        )
    snapshot = MarketSnapshot(
        _id(3000),
        NOW,
        NOW,
        "BTC-USDT-SPOT",
        "BINANCE-SPOT",
        tuple(item.market_data_id for item in observations),
        tuple(item.source_record_id for item in sources),
    )
    policy = approved_quality_policy_template().for_request(
        instrument_id=snapshot.instrument_id,
        timeframe="1m",
        cutoff=NOW,
        coverage_start=start,
        coverage_end=NOW,
    )
    batch = ProviderBatch(
        _id(3001),
        "binance-spot-public",
        "spot-api-2026-09",
        ProviderDataKind.OHLCV,
        ProviderBatchStatus.COMPLETE,
        NOW,
        NOW + timedelta(seconds=30),
        tuple(sources),
        tuple(observations),
        (snapshot,),
    )
    quality_v1 = assess_complete_binance_spot_batch(batch, policy, assessed_at=NOW)
    quality_v2 = assess_approved_spot_ohlcv_v2(
        snapshot,
        tuple(observations),
        tuple(sources),
        policy,
        timeframe="1m",
        assessed_at=NOW,
        finalized_market_data_ids=tuple(item.market_data_id for item in observations),
    )
    profile = calculate_spot_market_regime(
        snapshot=snapshot,
        observations=tuple(observations),
        sources=tuple(sources),
        quality=quality_v2,
        timeframe="1m",
    )
    binding_id = _id(3002)
    v2_evidence = tuple(
        EvidenceItemV2(
            item.evidence_id,
            (binding_id,),
            tuple(record.market_data_id for record in observations),
            tuple(record.source_record_id for record in sources),
            (),
            item.feature_ids,
            item.classification,
            item.relation,
            item.observed_at,
            item.available_at,
            min(item.expires_at, NOW + timedelta(minutes=1)),
            item.method,
            item.value,
            item.unit,
            item.interpretation,
            item.quality_status,
            item.reliability,
            item.limitations,
            item.provenance,
            item.usable,
        )
        for item in profile.evidence
    )
    regime_ref = AnalysisOutputReferenceV4(
        "C-005", profile.regime.regime_id, "1", "1", canonical_sha256(profile.regime)
    )
    evidence_refs = tuple(
        sorted(
            (
                AnalysisOutputReferenceV4(
                    "C-008", item.evidence_id, "2", "2", canonical_sha256(item)
                )
                for item in v2_evidence
            ),
            key=lambda item: str(item.record_id),
        )
    )
    binding = SpotOHLCVBindingV4(
        binding_id,
        InputModalityV4.SPOT_OHLCV,
        AnalysisRecordReference(
            "C-002", str(snapshot.snapshot_id), "1", "1", canonical_sha256(snapshot)
        ),
        snapshot.as_of,
        NOW,
        snapshot.instrument_id,
        snapshot.venue_id,
        "1m",
        start,
        NOW,
        AnalysisRecordReference(
            "C-003", str(quality_v2.report_id), "2", "2", canonical_sha256(quality_v2)
        ),
        AssessmentPolicyReference(
            quality_v2.assessment_policy_id, quality_v2.assessment_policy_version
        ),
        tuple(
            ObservationSourceBinding(
                AnalysisRecordReference(
                    "C-001", str(item.market_data_id), "1", "1", canonical_sha256(item)
                ),
                AnalysisRecordReference(
                    "C-091",
                    str(item.source_record_id),
                    "1",
                    "1",
                    canonical_sha256(source),
                ),
            )
            for item, source in zip(observations, sources, strict=True)
        ),
        tuple(
            AnalysisRecordReference(
                "C-091", str(item.source_record_id), "1", "1", canonical_sha256(item)
            )
            for item in sources
        ),
        regime_ref,
        VersionReference("spot-market-regime", "spot-market-regime-v1"),
        VersionReference("spot-ohlcv-regime-profile", "spot-ohlcv-regime-profile-v1"),
        evidence_refs,
    )
    manifest = create_analysis_snapshot_v4(
        snapshot_id=_id(3003),
        asset="BTC",
        instrument_id=snapshot.instrument_id,
        venue_id=snapshot.venue_id,
        timeframe="1m",
        analysis_cutoff=NOW,
        created_at=NOW,
        expires_at=NOW + timedelta(minutes=1),
        bindings=(binding,),
        assessment_ids=(_id(3004),),
        evidence_ids=tuple(sorted((item.evidence_id for item in v2_evidence), key=str)),
        provenance=(
            VersionReference("spot-market-regime", "spot-market-regime-v1"),
            VersionReference(
                "spot-ohlcv-regime-profile", "spot-ohlcv-regime-profile-v1"
            ),
        ),
        analysis_outputs=tuple(
            sorted(
                (regime_ref, *evidence_refs),
                key=lambda item: (item.contract_id, str(item.record_id)),
            )
        ),
    )

    resolved = resolve_analysis_snapshot_v4(
        manifest,
        now=NOW,
        snapshots={snapshot.snapshot_id: snapshot},
        reports={quality_v2.report_id: quality_v2},
        observations={item.market_data_id: item for item in observations},
        sources={item.source_record_id: item for item in sources},
        regimes={profile.regime.regime_id: profile.regime},
        evidence={item.evidence_id: item for item in v2_evidence},
    )
    assert len(resolved) == 1
    assert resolved[0].snapshot == snapshot
    assert resolved[0].report == quality_v2
    assert resolved[0].regime == profile.regime
    assert len(resolved[0].evidence) == 3
    assert quality_v1.status is DataQualityStatus.VALID
    for rejected_status in (DataQualityStatus.STALE, DataQualityStatus.INVALID):
        rejected_report = replace(quality_v2, status=rejected_status)
        rejected_binding = replace(
            binding,
            data_quality_report=AnalysisRecordReference(
                "C-003",
                str(rejected_report.report_id),
                "2",
                "2",
                canonical_sha256(rejected_report),
            ),
        )
        rejected_manifest = create_analysis_snapshot_v4(
            snapshot_id=manifest.snapshot_id,
            asset=manifest.asset,
            instrument_id=manifest.instrument_id,
            venue_id=manifest.venue_id,
            timeframe=manifest.timeframe,
            analysis_cutoff=manifest.analysis_cutoff,
            created_at=manifest.created_at,
            expires_at=manifest.expires_at,
            bindings=(rejected_binding,),
            assessment_ids=manifest.assessment_ids,
            evidence_ids=manifest.evidence_ids,
            provenance=manifest.provenance,
            analysis_outputs=manifest.analysis_outputs,
        )
        with pytest.raises(AnalysisV2ContractError, match="C-003 report is not valid"):
            resolve_analysis_snapshot_v4(
                rejected_manifest,
                now=NOW,
                snapshots={snapshot.snapshot_id: snapshot},
                reports={rejected_report.report_id: rejected_report},
                observations={item.market_data_id: item for item in observations},
                sources={item.source_record_id: item for item in sources},
                regimes={profile.regime.regime_id: profile.regime},
                evidence={item.evidence_id: item for item in v2_evidence},
            )
    with pytest.raises(AnalysisV2ContractError, match="expired or not yet available"):
        resolve_analysis_snapshot_v4(
            manifest,
            now=NOW + timedelta(minutes=2),
            snapshots={snapshot.snapshot_id: snapshot},
            reports={quality_v2.report_id: quality_v2},
            observations={item.market_data_id: item for item in observations},
            sources={item.source_record_id: item for item in sources},
            regimes={profile.regime.regime_id: profile.regime},
            evidence={item.evidence_id: item for item in v2_evidence},
        )

    # Exercise the complete C-006 v4 validator using the exact resolved OHLCV
    # path and an owner-supplied C-093 reference (no C-093 version is inferred).
    c093 = AnalysisOutputReferenceV4(
        "C-093",
        _id(3010),
        "owner-schema-4",
        "owner-lineage-9",
        HASH,
        VersionReference("owner-method", "owner-method-version"),
    )
    confluence = ConfluenceAssessmentV3(
        _id(3011),
        "BTC",
        "BTC-USDT-SPOT",
        "1m",
        NOW,
        NOW + timedelta(minutes=1),
        ConfluenceStateV2.PARTIALLY_ALIGNED,
        ConfluenceStatusV2.AVAILABLE,
        None,
        (
            ConfluenceComponentV2(
                _id(3012),
                "spot-ohlcv-trend",
                AnalyticalDirection.MIXED,
                EvidenceRelation.SUPPORTING,
                ConfluenceEvidenceStrengthV2.MODERATE,
                EvidenceDependenceV2.PARTIALLY_DEPENDENT,
                (v2_evidence[0].evidence_id,),
                (binding_id,),
            ),
        ),
        AnalyticalConfidenceV2(
            AnalyticalConfidenceStateV2.AVAILABLE,
            Decimal("0.5"),
            VersionReference("deterministic-confidence", "v1"),
            None,
        ),
        ConfluenceEvidenceStrengthV2.MODERATE,
        c093,
        manifest.snapshot_id,
        "4",
        (binding.data_quality_report,),
        (v2_evidence[0].evidence_id,),
        VersionReference("confluence-method", "v3"),
        (VersionReference("spot-profile", "v1"),),
    )
    fundamental = FundamentalAssessment(
        _id(3004),
        "BTC",
        "BTC-USDT-SPOT",
        "1m",
        NOW,
        NOW,
        NOW + timedelta(minutes=1),
        AssessmentStatus.UNAVAILABLE,
        Decimal("0.5"),
        (),
        (
            DomainObservation(
                "use-case",
                "outside bounded profile",
                None,
                "1m",
                VersionReference("synthetic-fundamental-method", "v1"),
                (v2_evidence[0].evidence_id,),
            ),
        ),
        (v2_evidence[0].evidence_id,),
        (),
        (),
        quality_v2.report_id,
        (VersionReference("fundamental-profile", "v1"),),
    )
    upgraded_manifest = create_analysis_snapshot_v4(
        snapshot_id=manifest.snapshot_id,
        asset=manifest.asset,
        instrument_id=manifest.instrument_id,
        venue_id=manifest.venue_id,
        timeframe=manifest.timeframe,
        analysis_cutoff=manifest.analysis_cutoff,
        created_at=manifest.created_at,
        expires_at=manifest.expires_at,
        bindings=manifest.bindings,
        assessment_ids=(fundamental.assessment_id,),
        evidence_ids=manifest.evidence_ids,
        provenance=manifest.provenance,
        analysis_outputs=tuple(
            sorted(
                (
                    *manifest.analysis_outputs,
                    AnalysisOutputReferenceV4(
                        "C-009",
                        confluence.assessment_id,
                        "3",
                        "3",
                        canonical_sha256(confluence),
                    ),
                    c093,
                ),
                key=lambda item: (item.contract_id, str(item.record_id)),
            )
        ),
    )
    upgraded_resolved = resolve_analysis_snapshot_v4(
        upgraded_manifest,
        now=NOW,
        snapshots={snapshot.snapshot_id: snapshot},
        reports={quality_v2.report_id: quality_v2},
        observations={item.market_data_id: item for item in observations},
        sources={item.source_record_id: item for item in sources},
        regimes={profile.regime.regime_id: profile.regime},
        evidence={item.evidence_id: item for item in v2_evidence},
    )
    context = MarketContextV4(
        _id(3013),
        "BTC",
        "BTC-USDT-SPOT",
        NOW,
        NOW + timedelta(minutes=1),
        ("1m",),
        profile.regime,
        (fundamental,),
        confluence,
        (),
        AdversarialAssessment(
            _id(3014),
            NOW,
            NOW + timedelta(minutes=1),
            "A counter-thesis is required.",
            ("Synthetic alternative",),
            (),
            ("The evidence expires",),
            (),
            (),
            (),
            Decimal("0.5"),
        ),
        (
            AnalyticalUncertainty(
                _id(3015),
                UncertaintyCategory.DATA,
                "Synthetic uncertainty.",
                (),
                ("spot",),
                Decimal("0.2"),
                False,
                (),
                NOW,
                NOW + timedelta(minutes=1),
                ResolutionStatus.UNRESOLVED,
            ),
        ),
        upgraded_manifest.evidence_ids,
        AnalysisSnapshotReferenceV4(
            upgraded_manifest.snapshot_id,
            "4",
            upgraded_manifest.content_sha256,
        ),
    )
    supported_c093 = (c093,)
    validate_market_context_v4(
        context,
        upgraded_manifest,
        resolved_bindings=upgraded_resolved,
        evidence={item.evidence_id: item for item in v2_evidence},
        supported_independence_reports=supported_c093,
        now=NOW,
    )
    with pytest.raises(AnalysisV2ContractError, match="not registry-supported"):
        validate_market_context_v4(
            context,
            upgraded_manifest,
            resolved_bindings=upgraded_resolved,
            evidence={item.evidence_id: item for item in v2_evidence},
            supported_independence_reports=(),
            now=NOW,
        )
    independent_confluence = replace(
        confluence,
        components=(
            replace(
                confluence.components[0],
                dependence=EvidenceDependenceV2.INDEPENDENT,
            ),
        ),
    )
    independent_manifest = create_analysis_snapshot_v4(
        snapshot_id=upgraded_manifest.snapshot_id,
        asset=upgraded_manifest.asset,
        instrument_id=upgraded_manifest.instrument_id,
        venue_id=upgraded_manifest.venue_id,
        timeframe=upgraded_manifest.timeframe,
        analysis_cutoff=upgraded_manifest.analysis_cutoff,
        created_at=upgraded_manifest.created_at,
        expires_at=upgraded_manifest.expires_at,
        bindings=upgraded_manifest.bindings,
        assessment_ids=upgraded_manifest.assessment_ids,
        evidence_ids=upgraded_manifest.evidence_ids,
        provenance=upgraded_manifest.provenance,
        analysis_outputs=tuple(
            sorted(
                (
                    *(
                        item
                        for item in upgraded_manifest.analysis_outputs
                        if item.contract_id != "C-009"
                    ),
                    AnalysisOutputReferenceV4(
                        "C-009",
                        independent_confluence.assessment_id,
                        "3",
                        "3",
                        canonical_sha256(independent_confluence),
                    ),
                ),
                key=lambda item: (item.contract_id, str(item.record_id)),
            )
        ),
    )
    independent_context = replace(
        context,
        confluence=independent_confluence,
        analysis_snapshot=AnalysisSnapshotReferenceV4(
            independent_manifest.snapshot_id,
            "4",
            independent_manifest.content_sha256,
        ),
    )
    with pytest.raises(AnalysisV2ContractError, match="cannot establish independent"):
        validate_market_context_v4(
            independent_context,
            independent_manifest,
            resolved_bindings=upgraded_resolved,
            evidence={item.evidence_id: item for item in v2_evidence},
            supported_independence_reports=supported_c093,
            now=NOW,
        )

    evidence_map = {item.evidence_id: item for item in v2_evidence}
    first, second = v2_evidence[:2]
    first_finding = SpotMetaFinding(
        _id(4100),
        "spot-trend",
        profile.regime.direction,
        first.relation,
        ConfluenceEvidenceStrengthV2.MODERATE,
        FindingReadiness.READY,
        (first.evidence_id,),
        (binding_id,),
        first.method,
        ConflictMaterialityV2.MATERIAL,
        False,
        False,
    )
    second_finding = SpotMetaFinding(
        _id(4101),
        "spot-momentum",
        profile.regime.direction,
        second.relation,
        ConfluenceEvidenceStrengthV2.STRONG,
        FindingReadiness.READY,
        (second.evidence_id,),
        (binding_id,),
        second.method,
        ConflictMaterialityV2.MATERIAL,
        False,
        False,
    )
    confluence, independence = calculate_spot_confluence_v3(
        manifest=manifest,
        resolved_bindings=resolved,
        evidence=evidence_map,
        findings=(first_finding, second_finding),
        now=NOW,
    )
    assert confluence.state is ConfluenceCalculationState.INDETERMINATE
    assert confluence.reason is MetaAnalysisReason.DEPENDENCE_UNESTABLISHED
    assert confluence.assessment.status is ConfluenceStatusV2.INDETERMINATE
    assert confluence.assessment.state is ConfluenceStateV2.INDETERMINATE
    assert (
        confluence.assessment.evidence_strength is ConfluenceEvidenceStrengthV2.UNKNOWN
    )
    assert tuple(item.direction for item in confluence.assessment.components) == (
        profile.regime.direction,
        profile.regime.direction,
    )
    assert all(
        item.dependence is EvidenceDependenceV2.PARTIALLY_DEPENDENT
        for item in confluence.assessment.components
    )
    assert confluence.assessment.analytical_confidence.value is None
    assert confluence.assessment.analytical_confidence.method is None
    assert confluence.assessment.analytical_confidence.unavailable_reason is not None
    assert set(confluence.assessment.evidence_ids) == {
        *profile.regime.evidence_ids,
        first.evidence_id,
        second.evidence_id,
    }
    assert independence.overall_dependence is EvidenceDependenceV2.PARTIALLY_DEPENDENT
    assert all(
        item.dependence is EvidenceDependenceV2.PARTIALLY_DEPENDENT
        for item in independence.comparisons
    )
    assert independence.statistical_independence_established is False
    assert {item.domain for item in independence.participants} == {
        "spot-market-regime",
        "spot-trend",
        "spot-momentum",
    }
    assert all(
        item.input_binding_ids == (binding_id,) for item in independence.participants
    )
    observed_factors = {
        factor for item in independence.comparisons for factor in item.factors
    }
    assert {
        DependenceFactor.SHARED_BINDING,
        DependenceFactor.SHARED_SOURCE,
        DependenceFactor.SHARED_OBSERVATION,
        DependenceFactor.OVERLAPPING_WINDOW,
    }.issubset(observed_factors)
    assert all(
        DependenceFactor.SHARED_METHOD in item.factors
        for item in independence.comparisons
        if item.left_finding_id == first_finding.finding_id
        and item.right_finding_id == second_finding.finding_id
    )
    assert independence.snapshot_sha256 == canonical_sha256(snapshot)
    assert independence.manifest_id == manifest.snapshot_id
    assert independence.binding_sha256 == canonical_sha256(binding)
    assert independence.regime_sha256 == canonical_sha256(profile.regime)
    assert independence.quality_report_sha256 == canonical_sha256(quality_v2)
    assert independence.method.component == "agent-independence"
    assert (
        decode_analysis_contract(encode_analysis_contract(independence)) == independence
    )
    registered_ref = C093Registry.reference(independence)
    assert (
        C093Registry.resolve(registered_ref, {independence.report_id: independence})
        == independence
    )
    with pytest.raises(AnalysisV2ContractError, match="digest mismatch"):
        C093Registry.resolve(
            replace(registered_ref, content_sha256="f" * 64),
            {independence.report_id: independence},
        )
    with pytest.raises(AnalysisV2ContractError, match="unsupported"):
        C093Registry.resolve(
            replace(registered_ref, schema_version="2"),
            {independence.report_id: independence},
        )
    with pytest.raises(AnalysisV2ContractError, match="unsupported"):
        C093Registry.resolve(
            replace(
                registered_ref,
                method=VersionReference("unregistered-method", "v9"),
            ),
            {independence.report_id: independence},
        )
    with pytest.raises(AnalysisV2ContractError, match="statistical independence"):
        replace(
            independence.comparisons[0],
            dependence=EvidenceDependenceV2.INDEPENDENT,
        )
    with pytest.raises(AnalysisV2ContractError, match="does not claim statistical"):
        replace(independence, statistical_independence_established=True)
    with pytest.raises(ValueError, match="limitations must be a tuple"):
        replace(independence, limitations=["mutable limitation"])
    with pytest.raises(AnalysisV2ContractError, match="overall dependence"):
        replace(independence, overall_dependence=EvidenceDependenceV2.UNKNOWN)
    with pytest.raises(AnalysisV2ContractError, match="digest mismatch"):
        C093Registry.resolve(registered_ref, {})

    permuted_confluence, permuted_independence = calculate_spot_confluence_v3(
        manifest=manifest,
        resolved_bindings=resolved,
        evidence=evidence_map,
        findings=(second_finding, first_finding),
        now=NOW,
    )
    assert permuted_confluence == confluence
    assert permuted_independence == independence

    conflicts = calculate_spot_conflicts_v3(
        manifest=manifest,
        resolved_bindings=resolved,
        evidence=evidence_map,
        findings=(
            first_finding,
            replace(second_finding, direction=AnalyticalDirection.BEARISH),
        ),
        now=NOW,
    )
    assert conflicts.state is ConflictCalculationState.ASSESSED
    assert any(
        item.severity is ConflictSeverityV2.HIGH
        and item.evidence_state is ConflictEvidenceStateV2.VALID
        and item.direct_opposition is True
        for item in conflicts.assessments
    )
    assert all(
        item.resolution_status is ResolutionStatus.UNRESOLVED
        for item in conflicts.assessments
    )
    assert any(
        item.severity is ConflictSeverityV2.LOW
        and item.materiality is ConflictMaterialityV2.LOCALIZED
        and item.direct_opposition is True
        for item in calculate_spot_conflicts_v3(
            manifest=manifest,
            resolved_bindings=resolved,
            evidence=evidence_map,
            findings=(
                replace(first_finding, materiality=ConflictMaterialityV2.LOCALIZED),
                replace(
                    second_finding,
                    direction=AnalyticalDirection.BEARISH,
                    materiality=ConflictMaterialityV2.LOCALIZED,
                ),
            ),
            now=NOW,
        ).assessments
    )
    assert (
        _conflict_severity(
            ConflictMaterialityV2.MATERIAL,
            required_premise_invalid=False,
            unsafe_to_rely=False,
            direct_opposition=False,
        )
        is ConflictSeverityV2.MODERATE
    )
    assert (
        _conflict_severity(
            ConflictMaterialityV2.UNKNOWN,
            required_premise_invalid=False,
            unsafe_to_rely=False,
            direct_opposition=True,
        )
        is ConflictSeverityV2.UNKNOWN
    )
    assert (
        _conflict_severity(
            ConflictMaterialityV2.MATERIAL,
            required_premise_invalid=True,
            unsafe_to_rely=False,
            direct_opposition=False,
        )
        is ConflictSeverityV2.CRITICAL
    )
    assert any(
        item.severity is ConflictSeverityV2.UNKNOWN
        and item.evidence_state is ConflictEvidenceStateV2.INSUFFICIENT
        and item.status_reason is ConflictReasonV2.MATERIALITY_UNESTABLISHED
        and item.direct_opposition is None
        for item in conflicts.assessments
    )
    critical_conflicts = calculate_spot_conflicts_v3(
        manifest=manifest,
        resolved_bindings=resolved,
        evidence=evidence_map,
        findings=(
            first_finding,
            replace(
                second_finding,
                direction=AnalyticalDirection.BEARISH,
                materiality=ConflictMaterialityV2.UNKNOWN,
                unsafe_to_rely=True,
            ),
        ),
        now=NOW,
    )
    assert any(
        item.severity is ConflictSeverityV2.CRITICAL
        and item.unsafe_to_rely is True
        and item.required_premise_invalid is None
        for item in critical_conflicts.assessments
    )
    assert all(
        item.resolution_status is ResolutionStatus.UNRESOLVED
        for item in critical_conflicts.assessments
    )
    no_conflict = calculate_spot_conflicts_v3(
        manifest=manifest,
        resolved_bindings=resolved,
        evidence=evidence_map,
        findings=(first_finding, second_finding),
        now=NOW,
    )
    assert no_conflict.state is ConflictCalculationState.NO_CONFLICT
    assert no_conflict.assessments == ()
    neutral_only = calculate_spot_conflicts_v3(
        manifest=manifest,
        resolved_bindings=resolved,
        evidence=evidence_map,
        findings=(
            replace(first_finding, direction=AnalyticalDirection.NEUTRAL),
            second_finding,
        ),
        now=NOW,
    )
    assert neutral_only.state is ConflictCalculationState.NO_CONFLICT
    assert neutral_only.assessments == ()
    final_outputs = (
        *manifest.analysis_outputs,
        AnalysisOutputReferenceV4(
            "C-009",
            confluence.assessment.assessment_id,
            "3",
            "3",
            canonical_sha256(confluence.assessment),
        ),
        registered_ref,
        *(
            AnalysisOutputReferenceV4(
                "C-010",
                item.assessment_id,
                "3",
                "3",
                canonical_sha256(item),
            )
            for item in conflicts.assessments
        ),
    )
    final_manifest = create_analysis_snapshot_v4(
        snapshot_id=manifest.snapshot_id,
        asset=manifest.asset,
        instrument_id=manifest.instrument_id,
        venue_id=manifest.venue_id,
        timeframe=manifest.timeframe,
        analysis_cutoff=manifest.analysis_cutoff,
        created_at=manifest.created_at,
        expires_at=manifest.expires_at,
        bindings=manifest.bindings,
        assessment_ids=upgraded_manifest.assessment_ids,
        evidence_ids=manifest.evidence_ids,
        provenance=manifest.provenance,
        analysis_outputs=tuple(
            sorted(
                final_outputs,
                key=lambda item: (item.contract_id, str(item.record_id)),
            )
        ),
    )
    final_resolved = resolve_analysis_snapshot_v4(
        final_manifest,
        now=NOW,
        snapshots={snapshot.snapshot_id: snapshot},
        reports={quality_v2.report_id: quality_v2},
        observations={item.market_data_id: item for item in observations},
        sources={item.source_record_id: item for item in sources},
        regimes={profile.regime.regime_id: profile.regime},
        evidence=evidence_map,
    )
    repeated_confluence, repeated_independence = calculate_spot_confluence_v3(
        manifest=final_manifest,
        resolved_bindings=final_resolved,
        evidence=evidence_map,
        findings=(first_finding, second_finding),
        now=NOW,
    )
    repeated_conflicts = calculate_spot_conflicts_v3(
        manifest=final_manifest,
        resolved_bindings=final_resolved,
        evidence=evidence_map,
        findings=(
            first_finding,
            replace(second_finding, direction=AnalyticalDirection.BEARISH),
        ),
        now=NOW,
    )
    assert repeated_confluence == confluence
    assert repeated_independence == independence
    assert repeated_conflicts == conflicts
    assert (
        decode_analysis_contract(encode_analysis_contract(final_manifest))
        == final_manifest
    )
    actual_context = replace(
        context,
        confluence=confluence.assessment,
        conflicts=conflicts.assessments,
        analysis_snapshot=AnalysisSnapshotReferenceV4(
            final_manifest.snapshot_id,
            final_manifest.schema_version,
            final_manifest.content_sha256,
        ),
    )
    validate_market_context_v4(
        actual_context,
        final_manifest,
        resolved_bindings=final_resolved,
        evidence=evidence_map,
        supported_independence_reports=(registered_ref,),
        now=NOW,
    )
    assert (
        decode_analysis_contract(encode_analysis_contract(actual_context))
        == actual_context
    )
    actual_context_wire = encode_analysis_contract(actual_context)
    assert (
        canonical_sha256(actual_context),
        sha256(actual_context_wire.encode("utf-8")).hexdigest(),
    ) == (
        "195248d9a31b7ec7" "8dc399f1e9d0af08" "e9a3e43f45e848c3" "d2bd79b4e1b4d0f8",
        "2d571fc60f32c2e3" "aa69fdb35be1ee2a" "f87255e99b93816a" "86981ccedbd495b4",
    )
    adversarial_method = VersionReference("spot-adversarial-assessment", "v2")
    adversarial_model = VersionReference("spot-adversarial-model", "v1")
    adversarial_prompt = VersionReference("spot-adversarial-prompt", "v1")
    confidence_method = VersionReference("spot-interpretive-confidence", "v1")
    adversarial = AdversarialAssessmentV2(
        _id(4300),
        "BTC",
        "BTC-USDT-SPOT",
        "1m",
        final_manifest.bindings[0].window_start,
        final_manifest.bindings[0].window_end,
        final_manifest.bindings[0].snapshot_as_of,
        final_manifest.analysis_cutoff,
        NOW,
        NOW + timedelta(minutes=1),
        "The observed trend may fail at its invalidation boundary.",
        ("The move may be a temporary continuation failure.",),
        tuple(
            AdversarialEvidenceReferenceV2(
                AnalysisOutputReferenceV4(
                    "C-008",
                    item.evidence_id,
                    "2",
                    "2",
                    canonical_sha256(item),
                ),
                item.binding_ids,
                item.observation_ids,
                item.source_record_ids,
            )
            for item in sorted(
                evidence_map.values(), key=lambda value: str(value.evidence_id)
            )
        ),
        (min(evidence_map, key=str),),
        ("The input may not persist through the next window.",),
        ("Only one OHLCV source contributes to this analysis.",),
        (),
        ("The thesis may overweight recent directional movement.",),
        AnalyticalConfidenceV2(
            AnalyticalConfidenceStateV2.AVAILABLE,
            Decimal("0.5"),
            confidence_method,
            None,
        ),
        AnalysisSnapshotReferenceV4(
            final_manifest.snapshot_id,
            "4",
            final_manifest.content_sha256,
        ),
        final_manifest.bindings[0].data_quality_report,
        adversarial_method,
        adversarial_model,
        adversarial_prompt,
    )
    adversarial_context = MarketContextV5(
        _id(4301),
        actual_context.asset,
        actual_context.instrument_id,
        actual_context.as_of,
        actual_context.expires_at,
        actual_context.multi_timeframe_state,
        actual_context.regime,
        actual_context.assessments,
        actual_context.confluence,
        actual_context.conflicts,
        adversarial,
        actual_context.uncertainties,
        actual_context.evidence_ids,
        actual_context.analysis_snapshot,
    )
    adversarial_wire = encode_analysis_contract(adversarial)
    assert decode_analysis_contract(adversarial_wire) == adversarial
    assert (
        decode_analysis_contract(encode_analysis_contract(adversarial_context))
        == adversarial_context
    )
    assert adversarial_context.schema_version == "5"
    assert adversarial.schema_version == "2"
    assert not hasattr(adversarial.analytical_confidence, "probability")
    assert (C019_V2_SCHEMA_VERSION, C019_V2_LINEAGE_VERSION) == ("2", "2")
    assert (C006_V5_SCHEMA_VERSION, C006_V5_LINEAGE_VERSION) == ("5", "5")
    with pytest.raises(AnalysisV2ContractError, match="Unknown analysis contract"):
        encoded = encode_analysis_contract(adversarial)
        prefix, suffix = encoded.rsplit('"schema_version":"2"', 1)
        decode_analysis_contract(f'{prefix}"schema_version":"99"{suffix}')
    with pytest.raises(AnalysisV2ContractError, match="invalid typed assessment"):
        replace(adversarial_context, adversarial=actual_context.adversarial)
    assert not any(
        item.contract_id == "C-019" for item in final_manifest.analysis_outputs
    )
    supported_adversarial_versions = (
        adversarial_method,
        adversarial_model,
        adversarial_prompt,
        confidence_method,
    )
    validate_market_context_v5(
        adversarial_context,
        final_manifest,
        resolved_bindings=final_resolved,
        evidence=evidence_map,
        supported_independence_reports=(registered_ref,),
        supported_adversarial_versions=supported_adversarial_versions,
        now=NOW,
    )
    evidence_id = adversarial.evidence[0].evidence.record_id
    mismatched_evidence = replace(
        evidence_map[evidence_id],
        evidence_id=_id(4397),
    )
    with pytest.raises(AnalysisV2ContractError, match="mapping keys"):
        validate_market_context_v5(
            adversarial_context,
            final_manifest,
            resolved_bindings=final_resolved,
            evidence={**evidence_map, evidence_id: mismatched_evidence},
            supported_independence_reports=(registered_ref,),
            supported_adversarial_versions=supported_adversarial_versions,
            now=NOW,
        )
    subset_adversarial = replace(
        adversarial,
        evidence=adversarial.evidence[:-1],
        contradictory_evidence_ids=(adversarial.evidence[0].evidence.record_id,),
    )
    validate_market_context_v5(
        replace(adversarial_context, adversarial=subset_adversarial),
        final_manifest,
        resolved_bindings=final_resolved,
        evidence=evidence_map,
        supported_independence_reports=(registered_ref,),
        supported_adversarial_versions=supported_adversarial_versions,
        now=NOW,
    )
    unavailable_adversarial = replace(
        adversarial,
        analytical_confidence=AnalyticalConfidenceV2(
            AnalyticalConfidenceStateV2.UNAVAILABLE,
            None,
            None,
            AnalyticalConfidenceReasonV2.NOT_ASSESSED,
        ),
    )
    assert unavailable_adversarial.analytical_confidence.value is None
    unavailable_context = replace(
        adversarial_context, adversarial=unavailable_adversarial
    )
    assert (
        decode_analysis_contract(encode_analysis_contract(unavailable_context))
        == unavailable_context
    )
    validate_market_context_v5(
        unavailable_context,
        final_manifest,
        resolved_bindings=final_resolved,
        evidence=evidence_map,
        supported_independence_reports=(registered_ref,),
        supported_adversarial_versions=supported_adversarial_versions,
        now=NOW,
    )
    with pytest.raises(AnalysisV2ContractError, match="requires a reason"):
        replace(
            unavailable_adversarial.analytical_confidence,
            unavailable_reason=None,
        )
    with pytest.raises(AnalysisV2ContractError, match="requires a reason"):
        replace(
            unavailable_adversarial.analytical_confidence,
            value=Decimal("0"),
        )
    with pytest.raises(AnalysisV2ContractError, match="exact C-019 evidence set"):
        replace(adversarial, contradictory_evidence_ids=(_id(4399),))
    with pytest.raises(AnalysisV2ContractError, match="references are unresolved"):
        validate_market_context_v5(
            adversarial_context,
            final_manifest,
            resolved_bindings=final_resolved,
            evidence=evidence_map,
            supported_independence_reports=(registered_ref,),
            supported_adversarial_versions=(),
            now=NOW,
        )
    with pytest.raises(AnalysisV2ContractError, match="references are unresolved"):
        validate_market_context_v5(
            adversarial_context,
            final_manifest,
            resolved_bindings=final_resolved,
            evidence=evidence_map,
            supported_independence_reports=(registered_ref,),
            supported_adversarial_versions=(
                adversarial_method,
                adversarial_model,
                adversarial_prompt,
            ),
            now=NOW,
        )
    bad_manifest_reference = AnalysisSnapshotReferenceV4(
        final_manifest.snapshot_id, "4", "f" * 64
    )
    bad_manifest_context = replace(
        adversarial_context,
        analysis_snapshot=bad_manifest_reference,
        adversarial=replace(adversarial, analysis_snapshot=bad_manifest_reference),
    )
    with pytest.raises(AnalysisV2ContractError, match="exact C-007 v4 manifest"):
        validate_market_context_v5(
            bad_manifest_context,
            final_manifest,
            resolved_bindings=final_resolved,
            evidence=evidence_map,
            supported_independence_reports=(registered_ref,),
            supported_adversarial_versions=supported_adversarial_versions,
            now=NOW,
        )
    bad_quality_reference = replace(
        adversarial,
        data_quality_report=replace(
            adversarial.data_quality_report, content_sha256="f" * 64
        ),
    )
    with pytest.raises(AnalysisV2ContractError, match="C-003 v2 reference"):
        validate_market_context_v5(
            replace(adversarial_context, adversarial=bad_quality_reference),
            final_manifest,
            resolved_bindings=final_resolved,
            evidence=evidence_map,
            supported_independence_reports=(registered_ref,),
            supported_adversarial_versions=supported_adversarial_versions,
            now=NOW,
        )
    tampered_adversarial = replace(
        adversarial,
        evidence=(
            replace(
                adversarial.evidence[0],
                evidence=replace(
                    adversarial.evidence[0].evidence,
                    content_sha256="f" * 64,
                ),
            ),
            *adversarial.evidence[1:],
        ),
    )
    assert canonical_sha256(tampered_adversarial) != canonical_sha256(adversarial)
    with pytest.raises(AnalysisV2ContractError, match="C-019 v2 evidence"):
        validate_market_context_v5(
            replace(adversarial_context, adversarial=tampered_adversarial),
            final_manifest,
            resolved_bindings=final_resolved,
            evidence=evidence_map,
            supported_independence_reports=(registered_ref,),
            supported_adversarial_versions=supported_adversarial_versions,
            now=NOW,
        )
    tampered_lineage = replace(
        adversarial,
        evidence=(
            replace(adversarial.evidence[0], observation_ids=(_id(4398),)),
            *adversarial.evidence[1:],
        ),
    )
    with pytest.raises(AnalysisV2ContractError, match="C-019 v2 evidence"):
        validate_market_context_v5(
            replace(adversarial_context, adversarial=tampered_lineage),
            final_manifest,
            resolved_bindings=final_resolved,
            evidence=evidence_map,
            supported_independence_reports=(registered_ref,),
            supported_adversarial_versions=supported_adversarial_versions,
            now=NOW,
        )
    expired_adversarial = replace(adversarial, expires_at=NOW + timedelta(seconds=30))
    with pytest.raises(AnalysisV2ContractError, match="expired"):
        validate_market_context_v5(
            replace(adversarial_context, adversarial=expired_adversarial),
            final_manifest,
            resolved_bindings=final_resolved,
            evidence=evidence_map,
            supported_independence_reports=(registered_ref,),
            supported_adversarial_versions=supported_adversarial_versions,
            now=NOW + timedelta(seconds=31),
        )
    with pytest.raises(AnalysisV2ContractError, match="Unsupported C-007 v4 output"):
        AnalysisOutputReferenceV4("C-019", _id(4302), "2", "2", HASH)
    unavailable = calculate_spot_confluence_v3(
        manifest=manifest,
        resolved_bindings=resolved,
        evidence=evidence_map,
        findings=(replace(first_finding, readiness=FindingReadiness.STALE),),
        now=NOW,
    )[0]
    assert unavailable.state is ConfluenceCalculationState.INDETERMINATE
    assert unavailable.assessment.components == ()
    for readiness, reason in (
        (FindingReadiness.PARTIAL, MetaAnalysisReason.PARTIAL_EVIDENCE),
        (FindingReadiness.WARMUP, MetaAnalysisReason.INSUFFICIENT_WARMUP),
        (FindingReadiness.UNAVAILABLE, MetaAnalysisReason.INPUT_UNAVAILABLE),
        (FindingReadiness.INVALID, MetaAnalysisReason.INVALID_EVIDENCE),
        (FindingReadiness.STALE, MetaAnalysisReason.STALE_EVIDENCE),
    ):
        not_ready = replace(first_finding, readiness=readiness)
        result, report = calculate_spot_confluence_v3(
            manifest=manifest,
            resolved_bindings=resolved,
            evidence=evidence_map,
            findings=(not_ready,),
            now=NOW,
        )
        assert result.state is ConfluenceCalculationState.INDETERMINATE
        assert result.reason is reason
        assert result.assessment.components == ()
        assert (
            calculate_spot_conflicts_v3(
                manifest=manifest,
                resolved_bindings=resolved,
                evidence=evidence_map,
                findings=(not_ready,),
                now=NOW,
            ).state
            is ConflictCalculationState.NOT_ASSESSED
        )
        assert report.participants

    contradictory, _ = calculate_spot_confluence_v3(
        manifest=manifest,
        resolved_bindings=resolved,
        evidence=evidence_map,
        findings=(
            first_finding,
            replace(second_finding, direction=AnalyticalDirection.BEARISH),
        ),
        now=NOW,
    )
    assert contradictory.assessment.state is ConfluenceStateV2.INDETERMINATE
    assert tuple(item.direction for item in contradictory.assessment.components) == (
        profile.regime.direction,
        AnalyticalDirection.BEARISH,
    )
    assert contradictory.state is ConfluenceCalculationState.INDETERMINATE

    partial_lineage = SpotMetaFinding(
        _id(4201),
        "spot-volume",
        AnalyticalDirection.UNKNOWN,
        EvidenceRelation.NEUTRAL,
        ConfluenceEvidenceStrengthV2.UNKNOWN,
        FindingReadiness.PARTIAL,
        (),
        (),
        None,
    )
    partial_report = assess_agent_independence(
        manifest=manifest,
        resolved_bindings=resolved,
        evidence=evidence_map,
        findings=(partial_lineage,),
        now=NOW,
    )
    partial_participant = next(
        item
        for item in partial_report.participants
        if item.finding_id == partial_lineage.finding_id
    )
    assert partial_participant.readiness is FindingReadiness.PARTIAL
    assert partial_participant.evidence_ids == ()
    assert partial_participant.input_binding_ids == ()
    assert partial_participant.method is None

    with pytest.raises(AnalysisV2ContractError, match="outside C-007 v4"):
        calculate_spot_confluence_v3(
            manifest=manifest,
            resolved_bindings=resolved,
            evidence=evidence_map,
            findings=(replace(first_finding, evidence_ids=(_id(4299),)),),
            now=NOW,
        )
    with pytest.raises(AnalysisV2ContractError, match="C-008 evidence identity"):
        calculate_spot_confluence_v3(
            manifest=manifest,
            resolved_bindings=resolved,
            evidence={
                **evidence_map,
                first.evidence_id: replace(
                    first,
                    binding_ids=(_id(4298),),
                ),
            },
            findings=(first_finding,),
            now=NOW,
        )
    with pytest.raises(AnalysisV2ContractError, match="expired or not yet available"):
        calculate_spot_confluence_v3(
            manifest=manifest,
            resolved_bindings=resolved,
            evidence=evidence_map,
            findings=(first_finding,),
            now=NOW + timedelta(minutes=2),
        )
    with pytest.raises(AnalysisV2ContractError, match="OHLCV binding differs"):
        replace(manifest, timeframe="5m")
    with pytest.raises(AnalysisV2ContractError, match="Resolved Spot dependencies"):
        calculate_spot_confluence_v3(
            manifest=manifest,
            resolved_bindings=(
                replace(
                    resolved[0],
                    snapshot=replace(snapshot, snapshot_id=_id(4297)),
                ),
            ),
            evidence=evidence_map,
            findings=(first_finding,),
            now=NOW,
        )
    with pytest.raises(AnalysisV2ContractError, match="Resolved Spot dependencies"):
        calculate_spot_confluence_v3(
            manifest=manifest,
            resolved_bindings=(
                replace(
                    resolved[0],
                    report=replace(quality_v2, report_id=_id(4296)),
                ),
            ),
            evidence=evidence_map,
            findings=(first_finding,),
            now=NOW,
        )
    unknown_direction = calculate_spot_confluence_v3(
        manifest=manifest,
        resolved_bindings=resolved,
        evidence=evidence_map,
        findings=(replace(first_finding, direction=AnalyticalDirection.UNKNOWN),),
        now=NOW,
    )[0]
    assert unknown_direction.state is ConfluenceCalculationState.INDETERMINATE
    with pytest.raises(AnalysisV2ContractError, match="exact Spot input"):
        calculate_spot_confluence_v3(
            manifest=manifest,
            resolved_bindings=resolved,
            evidence=evidence_map,
            findings=(replace(first_finding, input_binding_ids=(_id(4199),)),),
            now=NOW,
        )
    with pytest.raises(
        AnalysisV2ContractError, match="outside the approved Spot profile"
    ):
        SpotMetaFinding(
            _id(4200),
            "on-chain",
            AnalyticalDirection.BULLISH,
            first.relation,
            ConfluenceEvidenceStrengthV2.MODERATE,
            FindingReadiness.READY,
            (first.evidence_id,),
            (binding_id,),
            first.method,
        )
