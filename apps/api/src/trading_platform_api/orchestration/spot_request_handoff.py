"""Build and execute the validated local Spot RSI request handoff."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID, uuid5

from trading_platform_api.analysis.contracts import (
    EvidenceItem,
    MarketRegime,
    VersionReference,
)
from trading_platform_api.analysis.spot_market_regime import (
    SPOT_MARKET_REGIME_METHOD_VERSION,
    SPOT_MARKET_REGIME_PROFILE_VERSION,
    SpotMarketRegimeError,
    calculate_spot_market_regime,
)
from trading_platform_api.analysis.spot_meta_analysis import (
    AgentIndependenceReport,
    C093Registry,
    ConflictCalculationState,
    calculate_spot_conflicts_v3,
    calculate_spot_confluence_v3,
)
from trading_platform_api.analysis.spot_unavailable_context import (
    SpotUnavailableTechnicalContext,
    build_spot_unavailable_technical_context,
    unavailable_technical_assessment_id,
)
from trading_platform_api.analysis.versioned_contracts import (
    AnalysisRecordReference,
    EvidenceItemV2,
    ObservationSourceBinding,
)
from trading_platform_api.analysis.versioned_contracts_v4 import (
    AnalysisOutputReferenceV4,
    AnalysisSnapshotV4,
    ConflictAssessmentV3,
    ConfluenceAssessmentV3,
    InputModalityV4,
    ResolvedSpotOHLCVBindingV4,
    SpotOHLCVBindingV4,
    create_analysis_snapshot_v4,
    resolve_analysis_snapshot_v4,
)
from trading_platform_api.contracts.serialization import canonical_sha256
from trading_platform_api.market_data.contracts import (
    AssessmentPolicyReference,
    DataQualityReport,
    DataQualityReportV2,
    DataQualityStatus,
    DataSourceRecord,
    MarketData,
    MarketSnapshot,
)
from trading_platform_api.market_data.quality import (
    DataQualityAssessmentError,
    DataQualityPolicy,
    assess_approved_spot_ohlcv_v2,
)
from trading_platform_api.orchestration.spot_analysis_fanout import (
    SpotAnalysisFanoutAssessment,
    SpotAnalysisTaskStatus,
    run_spot_analysis_fanout_with_independence,
)
from trading_platform_api.orchestration.spot_rsi_finding import (
    build_spot_rsi14_task,
)

_IDENTITY_NAMESPACE = UUID("c524e30f-bf76-5e95-951d-42aedfb62059")
_REGIME_METHOD = VersionReference(
    "spot-market-regime", SPOT_MARKET_REGIME_METHOD_VERSION
)
_REGIME_PROFILE = VersionReference(
    "spot-ohlcv-regime-profile", SPOT_MARKET_REGIME_PROFILE_VERSION
)


def _validate_final_manifest_outputs(
    *,
    manifest: AnalysisSnapshotV4,
    quality_report: DataQualityReportV2,
    confluence: ConfluenceAssessmentV3,
    conflicts: tuple[ConflictAssessmentV3, ...],
    independence: AgentIndependenceReport,
) -> None:
    """Check the exact C-007 output closure before any model invocation."""
    expected = tuple(
        sorted(
            (
                *(
                    item
                    for item in manifest.analysis_outputs
                    if item.contract_id in {"C-005", "C-008"}
                ),
                AnalysisOutputReferenceV4(
                    "C-009",
                    confluence.assessment_id,
                    "3",
                    "3",
                    canonical_sha256(confluence),
                ),
                *(
                    AnalysisOutputReferenceV4(
                        "C-010",
                        item.assessment_id,
                        "3",
                        "3",
                        canonical_sha256(item),
                    )
                    for item in conflicts
                ),
                C093Registry.reference(independence),
            ),
            key=lambda item: (item.contract_id, str(item.record_id)),
        )
    )
    actual = tuple(
        sorted(
            manifest.analysis_outputs,
            key=lambda item: (item.contract_id, str(item.record_id)),
        )
    )
    if actual != expected:
        raise ValueError("C-007 outputs differ from the deterministic producer set.")
    if (
        confluence.input_snapshot_id != manifest.snapshot_id
        or confluence.input_snapshot_schema_version != manifest.schema_version
        or confluence.expires_at > manifest.expires_at
        or confluence.data_quality_reports
        != (manifest.bindings[0].data_quality_report,)
        or independence.manifest_id != manifest.snapshot_id
        or independence.snapshot_id
        != UUID(manifest.bindings[0].market_snapshot.record_id)
        or independence.quality_report_id != quality_report.report_id
        or independence.binding_id != manifest.bindings[0].binding_id
        or independence.binding_sha256 != canonical_sha256(manifest.bindings[0])
        or independence.expires_at > manifest.expires_at
        or any(
            item.input_snapshot_id != manifest.snapshot_id
            or item.input_snapshot_schema_version != manifest.schema_version
            or item.expires_at > manifest.expires_at
            or item.data_quality_reports != (manifest.bindings[0].data_quality_report,)
            for item in conflicts
        )
    ):
        raise ValueError("C-007 output scope or provenance is invalid.")


@dataclass(frozen=True, slots=True)
class SpotRequestAnalysisUnavailable:
    reason_code: str


@dataclass(frozen=True, slots=True)
class SpotRequestAnalysisHandoff:
    manifest: AnalysisSnapshotV4
    quality_report: DataQualityReportV2
    regime: MarketRegime
    evidence: tuple[EvidenceItemV2, ...]
    resolved_bindings: tuple[ResolvedSpotOHLCVBindingV4, ...]
    assessment: SpotAnalysisFanoutAssessment
    confluence: ConfluenceAssessmentV3
    conflicts: tuple[ConflictAssessmentV3, ...]
    unavailable_technical: SpotUnavailableTechnicalContext


def _to_evidence_v2(
    item: EvidenceItem,
    *,
    binding_id: UUID,
    snapshot: MarketSnapshot,
    observations: tuple[MarketData, ...],
) -> EvidenceItemV2:
    """Bind the regime's exact whole-snapshot evidence to C-008 v2."""
    observation_ids = tuple(item_id for item_id in snapshot.market_data_ids)
    source_ids = tuple(item_id for item_id in snapshot.source_record_ids)
    if not item.source_record_ids or set(item.source_record_ids) != set(source_ids):
        raise ValueError("Regime evidence does not cover the exact Spot sources.")
    if tuple(record.market_data_id for record in observations) != observation_ids:
        raise ValueError("Regime evidence inputs differ from the exact snapshot.")
    if item.quality_status is not DataQualityStatus.VALID or not item.usable:
        raise ValueError("Regime evidence is not usable under validated quality.")
    return EvidenceItemV2(
        item.evidence_id,
        (binding_id,),
        observation_ids,
        source_ids,
        tuple((value.dataset_id, value.version) for value in item.dataset_versions),
        item.feature_ids,
        item.classification,
        item.relation,
        item.observed_at,
        item.available_at,
        item.expires_at,
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


def build_spot_analysis_manifest(
    *,
    snapshot: MarketSnapshot,
    quality_v1: DataQualityReport,
    observations: tuple[MarketData, ...],
    sources: tuple[DataSourceRecord, ...],
    policy: DataQualityPolicy,
    timeframe: str,
    now: datetime,
    unavailable_technical: bool = False,
) -> tuple[
    AnalysisSnapshotV4,
    DataQualityReportV2,
    MarketRegime,
    tuple[EvidenceItemV2, ...],
    tuple[ResolvedSpotOHLCVBindingV4, ...],
]:
    """Create a request-scoped C-007 v4 closure from exact validated inputs."""
    if (
        type(snapshot) is not MarketSnapshot
        or type(quality_v1) is not DataQualityReport
        or type(policy) is not DataQualityPolicy
        or quality_v1.status is not DataQualityStatus.VALID
        or quality_v1.snapshot_id != snapshot.snapshot_id
        or tuple(item.market_data_id for item in observations)
        != snapshot.market_data_ids
        or tuple(item.source_record_id for item in sources)
        != snapshot.source_record_ids
        or len(observations) != len(sources)
        or snapshot.dataset_version is not None
    ):
        raise ValueError("Spot request inputs are not an exact validated closure.")

    now = now.astimezone(snapshot.as_of.tzinfo)
    quality_v2 = assess_approved_spot_ohlcv_v2(
        snapshot,
        observations,
        sources,
        policy,
        timeframe=timeframe,
        assessed_at=quality_v1.assessed_at,
        finalized_market_data_ids=tuple(item.market_data_id for item in observations),
    )
    if quality_v2.status is not DataQualityStatus.VALID:
        raise DataQualityAssessmentError("C-003 v2 did not validate the Spot scope.")

    regime_result = calculate_spot_market_regime(
        snapshot=snapshot,
        observations=observations,
        sources=sources,
        quality=quality_v2,
        timeframe=timeframe,
    )
    binding_id = uuid5(
        _IDENTITY_NAMESPACE,
        f"spot-analysis-binding-v1:{snapshot.snapshot_id}:{quality_v2.report_id}",
    )
    evidence = tuple(
        _to_evidence_v2(
            item,
            binding_id=binding_id,
            snapshot=snapshot,
            observations=observations,
        )
        for item in regime_result.evidence
    )
    expires_at = min(
        snapshot.as_of + timedelta(seconds=policy.freshness_seconds),
        regime_result.regime.expires_at,
        *(item.expires_at for item in evidence),
    )
    if now >= expires_at or quality_v2.assessed_at > now:
        raise ValueError("Spot analysis dependencies are stale or future dated.")

    regime_ref = AnalysisOutputReferenceV4(
        "C-005",
        regime_result.regime.regime_id,
        "1",
        "1",
        canonical_sha256(regime_result.regime),
    )
    evidence_refs = tuple(
        sorted(
            (
                AnalysisOutputReferenceV4(
                    "C-008", item.evidence_id, "2", "2", canonical_sha256(item)
                )
                for item in evidence
            ),
            key=lambda item: str(item.record_id),
        )
    )
    observation_refs = tuple(
        ObservationSourceBinding(
            AnalysisRecordReference(
                "C-001",
                str(observation.market_data_id),
                "1",
                "1",
                canonical_sha256(observation),
            ),
            AnalysisRecordReference(
                "C-091",
                str(source.source_record_id),
                "1",
                "1",
                canonical_sha256(source),
            ),
        )
        for observation, source in zip(observations, sources, strict=True)
    )
    source_refs = tuple(
        AnalysisRecordReference(
            "C-091", str(item.source_record_id), "1", "1", canonical_sha256(item)
        )
        for item in sources
    )
    binding = SpotOHLCVBindingV4(
        binding_id=binding_id,
        modality=InputModalityV4.SPOT_OHLCV,
        market_snapshot=AnalysisRecordReference(
            "C-002", str(snapshot.snapshot_id), "1", "1", canonical_sha256(snapshot)
        ),
        snapshot_as_of=snapshot.as_of,
        analysis_cutoff=quality_v2.assessed_at,
        instrument_id=snapshot.instrument_id,
        venue_id=snapshot.venue_id,
        timeframe=timeframe,
        window_start=policy.coverage_start,
        window_end=policy.coverage_end,
        data_quality_report=AnalysisRecordReference(
            "C-003", str(quality_v2.report_id), "2", "2", canonical_sha256(quality_v2)
        ),
        assessment_policy=AssessmentPolicyReference(
            quality_v2.assessment_policy_id, quality_v2.assessment_policy_version
        ),
        observations=observation_refs,
        source_records=source_refs,
        regime=regime_ref,
        regime_method=_REGIME_METHOD,
        regime_profile=_REGIME_PROFILE,
        evidence=evidence_refs,
    )
    analysis_outputs = tuple(
        sorted(
            (regime_ref, *evidence_refs),
            key=lambda item: (item.contract_id, str(item.record_id)),
        )
    )
    assessment_id = (
        unavailable_technical_assessment_id(snapshot, quality_v2)
        if unavailable_technical
        else regime_result.regime.regime_id
    )
    manifest_identity = (
        f"spot-analysis-manifest-v1:{snapshot.snapshot_id}:{binding_id}"
        if not unavailable_technical
        else f"spot-analysis-manifest-v1:{snapshot.snapshot_id}:{binding_id}:{assessment_id}"
    )
    manifest = create_analysis_snapshot_v4(
        snapshot_id=uuid5(_IDENTITY_NAMESPACE, manifest_identity),
        asset=snapshot.instrument_id.split("-", maxsplit=1)[0],
        instrument_id=snapshot.instrument_id,
        venue_id=snapshot.venue_id,
        timeframe=timeframe,
        analysis_cutoff=quality_v2.assessed_at,
        created_at=quality_v2.assessed_at,
        expires_at=expires_at,
        bindings=(binding,),
        # C-005 is represented by its exact regime binding. The approved
        # producer profile records its C-012 assessment identity separately.
        assessment_ids=(assessment_id,),
        evidence_ids=tuple(sorted((item.evidence_id for item in evidence), key=str)),
        provenance=(_REGIME_METHOD, _REGIME_PROFILE),
        analysis_outputs=analysis_outputs,
    )
    resolved = resolve_analysis_snapshot_v4(
        manifest,
        now=now,
        snapshots={snapshot.snapshot_id: snapshot},
        reports={quality_v2.report_id: quality_v2},
        observations={item.market_data_id: item for item in observations},
        sources={item.source_record_id: item for item in sources},
        regimes={regime_result.regime.regime_id: regime_result.regime},
        evidence={item.evidence_id: item for item in evidence},
    )
    return manifest, quality_v2, regime_result.regime, evidence, resolved


async def run_spot_analysis_request_handoff(
    *,
    snapshot: MarketSnapshot,
    quality_v1: DataQualityReport,
    observations: tuple[MarketData, ...],
    sources: tuple[DataSourceRecord, ...],
    policy: DataQualityPolicy,
    timeframe: str,
    now: datetime,
    correlation_id: UUID,
) -> SpotRequestAnalysisHandoff | SpotRequestAnalysisUnavailable:
    """Resolve validated request inputs, then execute RSI and C-093 fan-in."""
    try:
        manifest, quality_v2, regime, evidence_items, resolved = (
            build_spot_analysis_manifest(
                snapshot=snapshot,
                quality_v1=quality_v1,
                observations=observations,
                sources=sources,
                policy=policy,
                timeframe=timeframe,
                now=now,
                unavailable_technical=True,
            )
        )
    except SpotMarketRegimeError:
        return SpotRequestAnalysisUnavailable("REGIME_UNAVAILABLE")
    except (DataQualityAssessmentError, ValueError, TypeError):
        return SpotRequestAnalysisUnavailable("ANALYSIS_INPUT_UNAVAILABLE")

    evidence = {item.evidence_id: item for item in evidence_items}
    try:
        task = build_spot_rsi14_task(
            manifest=manifest,
            resolved_binding=resolved[0],
            evidence_ids=manifest.evidence_ids,
            evidence_by_id=evidence,
            clock=lambda: now,
        )
        assessment = await run_spot_analysis_fanout_with_independence(
            (task,),
            correlation_id=correlation_id,
            manifest=manifest,
            resolved_bindings=resolved,
            evidence=evidence,
            now=now,
        )
    except (ValueError, TypeError):
        return SpotRequestAnalysisUnavailable("ANALYSIS_HANDOFF_INVALID")
    if not assessment.fanout.outcomes:
        return SpotRequestAnalysisUnavailable("ANALYSIS_RESULT_UNAVAILABLE")
    if assessment.independence_report.statistical_independence_established:
        return SpotRequestAnalysisUnavailable("INDEPENDENCE_INVARIANT_VIOLATION")
    if any(
        outcome.status is SpotAnalysisTaskStatus.FAILED
        for outcome in assessment.fanout.outcomes
    ):
        return SpotRequestAnalysisUnavailable("ANALYSIS_TASK_FAILED")
    try:
        confluence_result, confluence_independence = calculate_spot_confluence_v3(
            manifest=manifest,
            resolved_bindings=resolved,
            evidence=evidence,
            findings=assessment.fanout.findings,
            now=now,
        )
        conflict_result = calculate_spot_conflicts_v3(
            manifest=manifest,
            resolved_bindings=resolved,
            evidence=evidence,
            findings=assessment.fanout.findings,
            now=now,
        )
        # An INDETERMINATE C-009 is still a valid, provenance-bound result: it
        # records that this single-source Spot profile cannot establish enough
        # evidence or independence for confluence. Preserve it in the final
        # manifest so downstream consumers can fail closed on its status.
        if (
            conflict_result.state
            not in {
                ConflictCalculationState.NOT_ASSESSED,
                ConflictCalculationState.NO_CONFLICT,
                ConflictCalculationState.ASSESSED,
            }
            or confluence_independence != assessment.independence_report
        ):
            return SpotRequestAnalysisUnavailable("META_ANALYSIS_UNAVAILABLE")
        confluence = confluence_result.assessment
        conflicts = conflict_result.assessments
        independence_ref = C093Registry.reference(assessment.independence_report)
        outputs = tuple(
            sorted(
                (
                    *(
                        item
                        for item in manifest.analysis_outputs
                        if item.contract_id in {"C-005", "C-008"}
                    ),
                    AnalysisOutputReferenceV4(
                        "C-009",
                        confluence.assessment_id,
                        "3",
                        "3",
                        canonical_sha256(confluence),
                    ),
                    *(
                        AnalysisOutputReferenceV4(
                            "C-010",
                            item.assessment_id,
                            "3",
                            "3",
                            canonical_sha256(item),
                        )
                        for item in conflicts
                    ),
                    independence_ref,
                ),
                key=lambda item: (item.contract_id, str(item.record_id)),
            )
        )
        manifest = create_analysis_snapshot_v4(
            snapshot_id=manifest.snapshot_id,
            asset=manifest.asset,
            instrument_id=manifest.instrument_id,
            venue_id=manifest.venue_id,
            timeframe=manifest.timeframe,
            analysis_cutoff=manifest.analysis_cutoff,
            created_at=manifest.created_at,
            expires_at=manifest.expires_at,
            bindings=manifest.bindings,
            assessment_ids=manifest.assessment_ids,
            evidence_ids=manifest.evidence_ids,
            provenance=manifest.provenance,
            analysis_outputs=outputs,
        )
        _validate_final_manifest_outputs(
            manifest=manifest,
            quality_report=quality_v2,
            confluence=confluence,
            conflicts=conflicts,
            independence=assessment.independence_report,
        )
        resolved = resolve_analysis_snapshot_v4(
            manifest,
            now=now,
            snapshots={snapshot.snapshot_id: snapshot},
            reports={quality_v2.report_id: quality_v2},
            observations={item.market_data_id: item for item in observations},
            sources={item.source_record_id: item for item in sources},
            regimes={regime.regime_id: regime},
            evidence=evidence,
        )
        unavailable = build_spot_unavailable_technical_context(
            snapshot=snapshot,
            quality_report=quality_v2,
            manifest=manifest,
        )
    except (ValueError, TypeError):
        return SpotRequestAnalysisUnavailable("FINAL_ANALYSIS_CLOSURE_INVALID")
    return SpotRequestAnalysisHandoff(
        manifest,
        quality_v2,
        regime,
        evidence_items,
        resolved,
        assessment,
        confluence,
        conflicts,
        unavailable,
    )


__all__ = [
    "SpotRequestAnalysisUnavailable",
    "SpotRequestAnalysisHandoff",
    "build_spot_analysis_manifest",
    "run_spot_analysis_request_handoff",
]
