"""Synthetic compatibility and canonical-wire tests for the Spot C-007 v4 path."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from uuid import UUID

import pytest
from trading_platform_api.analysis import (
    AdversarialAssessment,
    AnalysisOutputReferenceV4,
    AnalysisRecordReference,
    AnalysisSnapshotReferenceV4,
    AnalysisV2ContractError,
    AnalyticalConfidenceStateV2,
    AnalyticalConfidenceV2,
    AnalyticalDirection,
    AnalyticalUncertainty,
    AssessmentStatus,
    ClaimClassification,
    ConflictAssessmentV3,
    ConflictEvidenceStateV2,
    ConflictMaterialityV2,
    ConflictReasonV2,
    ConflictSeverityV2,
    ConfluenceAssessmentV3,
    ConfluenceComponentV2,
    ConfluenceEvidenceStrengthV2,
    ConfluenceStateV2,
    ConfluenceStatusV2,
    DomainObservation,
    EvidenceDependenceV2,
    EvidenceItemV2,
    EvidenceRelation,
    FundamentalAssessment,
    InputModalityV4,
    MarketContextV4,
    MarketRegime,
    ObservationSourceBinding,
    RegimeDimension,
    ResolutionStatus,
    SpotOHLCVBindingV4,
    UncertaintyCategory,
    VersionReference,
    analysis_snapshot_v4_sha256,
    calculate_spot_market_regime,
    create_analysis_snapshot_v4,
    decode_analysis_contract,
    encode_analysis_contract,
    resolve_analysis_snapshot_v4,
    validate_evidence_item_v2_for_v4,
    validate_market_context_v4,
)
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
