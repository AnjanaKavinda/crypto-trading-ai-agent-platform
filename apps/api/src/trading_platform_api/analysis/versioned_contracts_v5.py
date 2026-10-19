"""Additive C-019 v2 and C-006 v5 Spot adversarial contract path."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Mapping, get_args
from uuid import UUID

from trading_platform_api.analysis.contracts import (
    AnalyticalUncertainty,
    MarketRegime,
    VersionReference,
    _text,
    _time,
    _typed_tuple,
    _unique,
    _uuid,
    _uuid_tuple,
)
from trading_platform_api.analysis.versioned_contracts import (
    ANALYSIS_V2_SCHEMA_VERSION,
    AnalysisRecordReference,
    AnalysisV2ContractError,
    AnalyticalConfidenceStateV2,
    AnalyticalConfidenceV2,
    ConflictEvidenceStateV2,
    ConfluenceStatusV2,
    EvidenceItemV2,
    VersionedAssessment,
)
from trading_platform_api.analysis.versioned_contracts_v4 import (
    C007_V4_SCHEMA_VERSION,
    C009_C010_V3_SCHEMA_VERSION,
    AnalysisOutputReferenceV4,
    AnalysisSnapshotReferenceV4,
    AnalysisSnapshotV4,
    ConflictAssessmentV3,
    ConfluenceAssessmentV3,
    ResolvedSpotOHLCVBindingV4,
    resolve_analysis_snapshot_v4,
)
from trading_platform_api.contracts.serialization import canonical_sha256

C019_V2_SCHEMA_VERSION = "2"
C019_V2_LINEAGE_VERSION = "2"
C006_V5_SCHEMA_VERSION = "5"
C006_V5_LINEAGE_VERSION = "5"


@dataclass(frozen=True, slots=True)
class AdversarialEvidenceReferenceV2:
    evidence: AnalysisOutputReferenceV4
    binding_ids: tuple[UUID, ...]
    observation_ids: tuple[UUID, ...]
    source_record_ids: tuple[UUID, ...]

    def __post_init__(self) -> None:
        if (
            type(self.evidence) is not AnalysisOutputReferenceV4
            or self.evidence.contract_id != "C-008"
            or (self.evidence.schema_version, self.evidence.lineage_version)
            != (ANALYSIS_V2_SCHEMA_VERSION, ANALYSIS_V2_SCHEMA_VERSION)
        ):
            raise AnalysisV2ContractError(
                "C-019 v2 evidence must reference C-008 schema/lineage 2."
            )
        for name in ("binding_ids", "observation_ids", "source_record_ids"):
            _uuid_tuple(name, getattr(self, name), empty=False)


@dataclass(frozen=True, slots=True)
class AdversarialAssessmentV2:
    assessment_id: UUID
    asset: str
    instrument_id: str
    timeframe: str
    coverage_start: datetime
    coverage_end: datetime
    snapshot_as_of: datetime
    analysis_cutoff: datetime
    as_of: datetime
    expires_at: datetime
    counter_thesis: str
    alternative_hypotheses: tuple[str, ...]
    evidence: tuple[AdversarialEvidenceReferenceV2, ...]
    contradictory_evidence_ids: tuple[UUID, ...]
    failure_conditions: tuple[str, ...]
    data_limitations: tuple[str, ...]
    measurement_error_risks: tuple[str, ...]
    confirmation_bias_concerns: tuple[str, ...]
    analytical_confidence: AnalyticalConfidenceV2
    analysis_snapshot: AnalysisSnapshotReferenceV4
    data_quality_report: AnalysisRecordReference
    method: VersionReference
    model: VersionReference
    prompt: VersionReference
    contract_id: str = field(default="C-019", init=False)
    schema_version: str = field(default=C019_V2_SCHEMA_VERSION, init=False)

    def __post_init__(self) -> None:
        _uuid("assessment_id", self.assessment_id)
        for name in ("asset", "instrument_id", "timeframe", "counter_thesis"):
            _text(name, getattr(self, name))
        start = _time("coverage_start", self.coverage_start)
        end = _time("coverage_end", self.coverage_end)
        snapshot_as_of = _time("snapshot_as_of", self.snapshot_as_of)
        cutoff = _time("analysis_cutoff", self.analysis_cutoff)
        as_of = _time("as_of", self.as_of)
        expires = _time("expires_at", self.expires_at)
        if (
            start >= end
            or snapshot_as_of > cutoff
            or cutoff != as_of
            or as_of >= expires
        ):
            raise AnalysisV2ContractError("C-019 v2 has invalid Spot time scope.")
        _typed_tuple(
            "alternative_hypotheses",
            self.alternative_hypotheses,
            str,
            empty=False,
        )
        evidence = _typed_tuple(
            "evidence", self.evidence, AdversarialEvidenceReferenceV2, empty=False
        )
        evidence_ids = tuple(item.evidence.record_id for item in evidence)
        if evidence_ids != tuple(sorted(set(evidence_ids), key=str)):
            raise AnalysisV2ContractError(
                "C-019 v2 evidence references must be unique and ordered."
            )
        contradictory = _uuid_tuple(
            "contradictory_evidence_ids", self.contradictory_evidence_ids
        )
        if not set(contradictory).issubset(evidence_ids):
            raise AnalysisV2ContractError(
                "Contradictory evidence must belong to the exact C-019 evidence set."
            )
        for name in (
            "failure_conditions",
            "data_limitations",
            "measurement_error_risks",
            "confirmation_bias_concerns",
        ):
            _typed_tuple(name, getattr(self, name), str)
        if type(self.analytical_confidence) is not AnalyticalConfidenceV2:
            raise AnalysisV2ContractError(
                "C-019 v2 requires an explicit analytical confidence state."
            )
        if type(self.analysis_snapshot) is not AnalysisSnapshotReferenceV4:
            raise AnalysisV2ContractError("C-019 v2 must reference C-007 v4.")
        if (
            type(self.data_quality_report) is not AnalysisRecordReference
            or self.data_quality_report.contract_id != "C-003"
            or (
                self.data_quality_report.schema_version,
                self.data_quality_report.lineage_version,
            )
            != ("2", "2")
        ):
            raise AnalysisV2ContractError("C-019 v2 must reference C-003 schema 2.")
        for name in ("method", "model", "prompt"):
            if type(getattr(self, name)) is not VersionReference:
                raise AnalysisV2ContractError(
                    f"C-019 v2 {name} version reference must be explicit."
                )
        object.__setattr__(self, "coverage_start", start)
        object.__setattr__(self, "coverage_end", end)
        object.__setattr__(self, "snapshot_as_of", snapshot_as_of)
        object.__setattr__(self, "analysis_cutoff", cutoff)
        object.__setattr__(self, "as_of", as_of)
        object.__setattr__(self, "expires_at", expires)


@dataclass(frozen=True, slots=True)
class MarketContextV5:
    context_id: UUID
    asset: str
    instrument_id: str
    as_of: datetime
    expires_at: datetime
    multi_timeframe_state: tuple[str, ...]
    regime: MarketRegime
    assessments: tuple[VersionedAssessment, ...]
    confluence: ConfluenceAssessmentV3
    conflicts: tuple[ConflictAssessmentV3, ...]
    adversarial: AdversarialAssessmentV2
    uncertainties: tuple[AnalyticalUncertainty, ...]
    evidence_ids: tuple[UUID, ...]
    analysis_snapshot: AnalysisSnapshotReferenceV4
    contract_id: str = field(default="C-006", init=False)
    schema_version: str = field(default=C006_V5_SCHEMA_VERSION, init=False)

    def __post_init__(self) -> None:
        _uuid("context_id", self.context_id)
        _text("asset", self.asset)
        _text("instrument_id", self.instrument_id)
        as_of = _time("as_of", self.as_of)
        expires = _time("expires_at", self.expires_at)
        if as_of >= expires:
            raise AnalysisV2ContractError("C-006 v5 has invalid time order.")
        if (
            type(self.multi_timeframe_state) is not tuple
            or not self.multi_timeframe_state
        ):
            raise AnalysisV2ContractError("multi_timeframe_state must not be empty.")
        for item in self.multi_timeframe_state:
            _text("multi_timeframe_state item", item)
        if (
            type(self.regime) is not MarketRegime
            or type(self.confluence) is not ConfluenceAssessmentV3
            or type(self.adversarial) is not AdversarialAssessmentV2
        ):
            raise AnalysisV2ContractError(
                "C-006 v5 contains an invalid typed assessment."
            )
        if (
            type(self.assessments) is not tuple
            or not self.assessments
            or any(
                type(item) not in get_args(VersionedAssessment)
                for item in self.assessments
            )
        ):
            raise AnalysisV2ContractError("C-006 v5 assessments are empty or invalid.")
        _unique(
            "assessment identities",
            tuple(
                (item.contract_id, str(item.assessment_id)) for item in self.assessments
            ),
        )
        _typed_tuple("conflicts", self.conflicts, ConflictAssessmentV3)
        _unique(
            "conflict identities", tuple(item.assessment_id for item in self.conflicts)
        )
        _typed_tuple(
            "uncertainties", self.uncertainties, AnalyticalUncertainty, empty=False
        )
        _uuid_tuple("evidence_ids", self.evidence_ids, empty=False)
        if type(self.analysis_snapshot) is not AnalysisSnapshotReferenceV4:
            raise AnalysisV2ContractError("C-006 v5 must reference C-007 v4.")
        if (
            self.adversarial.analysis_snapshot != self.analysis_snapshot
            or self.adversarial.asset != self.asset
            or self.adversarial.instrument_id != self.instrument_id
            or self.adversarial.as_of != as_of
            or self.adversarial.expires_at > expires
            or self.adversarial.contradictory_evidence_ids
            and not set(self.adversarial.contradictory_evidence_ids).issubset(
                set(self.evidence_ids)
            )
        ):
            raise AnalysisV2ContractError(
                "C-019 v2 does not match its C-006 v5 context."
            )
        object.__setattr__(self, "as_of", as_of)
        object.__setattr__(self, "expires_at", expires)


def validate_market_context_v5(
    context: MarketContextV5,
    manifest: AnalysisSnapshotV4,
    *,
    resolved_bindings: tuple[ResolvedSpotOHLCVBindingV4, ...],
    evidence: Mapping[UUID, EvidenceItemV2],
    supported_independence_reports: tuple[AnalysisOutputReferenceV4, ...],
    supported_adversarial_versions: tuple[VersionReference, ...],
    now: datetime,
) -> None:
    if type(context) is not MarketContextV5 or type(manifest) is not AnalysisSnapshotV4:
        raise AnalysisV2ContractError("Expected exact C-006 v5/C-007 v4 contracts.")
    at = _time("now", now)
    if (
        manifest.created_at > at
        or manifest.expires_at <= at
        or context.expires_at <= at
    ):
        raise AnalysisV2ContractError("Market context or manifest is stale.")
    adversarial = context.adversarial
    if (
        context.analysis_snapshot.snapshot_id != manifest.snapshot_id
        or context.analysis_snapshot.schema_version != C007_V4_SCHEMA_VERSION
        or context.analysis_snapshot.content_sha256 != manifest.content_sha256
        or adversarial.analysis_snapshot != context.analysis_snapshot
        or context.asset != manifest.asset
        or context.instrument_id != manifest.instrument_id
        or context.as_of != manifest.analysis_cutoff
        or context.expires_at > manifest.expires_at
        or context.evidence_ids != manifest.evidence_ids
        or tuple(item.assessment_id for item in context.assessments)
        != manifest.assessment_ids
    ):
        raise AnalysisV2ContractError(
            "C-006 v5/C-019 v2 do not bind to the exact C-007 v4 manifest."
        )
    if (
        type(supported_independence_reports) is not tuple
        or any(
            type(item) is not AnalysisOutputReferenceV4 or item.contract_id != "C-093"
            for item in supported_independence_reports
        )
        or len(set(supported_independence_reports))
        != len(supported_independence_reports)
    ):
        raise AnalysisV2ContractError(
            "C-093 references must come from the owner registry."
        )
    if context.confluence.independence_report not in supported_independence_reports:
        raise AnalysisV2ContractError(
            "C-093 exact schema/lineage/id/digest is not registry-supported."
        )
    required_versions = {adversarial.method, adversarial.model, adversarial.prompt}
    if (
        adversarial.analytical_confidence.state is AnalyticalConfidenceStateV2.AVAILABLE
        and adversarial.analytical_confidence.method is not None
    ):
        required_versions.add(adversarial.analytical_confidence.method)
    if (
        type(supported_adversarial_versions) is not tuple
        or any(
            type(item) is not VersionReference
            for item in supported_adversarial_versions
        )
        or len(set(supported_adversarial_versions))
        != len(supported_adversarial_versions)
        or not required_versions.issubset(set(supported_adversarial_versions))
    ):
        raise AnalysisV2ContractError(
            "C-019 method/model/prompt references are unresolved."
        )
    confidence = adversarial.analytical_confidence
    if confidence.state is AnalyticalConfidenceStateV2.AVAILABLE:
        if confidence.value is None or confidence.method is None:
            raise AnalysisV2ContractError(
                "Available confidence lacks its exact interpretive method/value."
            )
    elif confidence.state is AnalyticalConfidenceStateV2.UNAVAILABLE:
        if confidence.value is not None or confidence.unavailable_reason is None:
            raise AnalysisV2ContractError(
                "Unavailable confidence requires a reason and no value."
            )
    else:
        raise AnalysisV2ContractError("Unsupported analytical confidence state.")
    if (
        set(evidence) != set(manifest.evidence_ids)
        or type(resolved_bindings) is not tuple
    ):
        raise AnalysisV2ContractError(
            "C-008 evidence or C-007 bindings are not exactly resolved."
        )
    if len(resolved_bindings) != 1 or any(
        type(item) is not ResolvedSpotOHLCVBindingV4 for item in resolved_bindings
    ):
        raise AnalysisV2ContractError("Resolved OHLCV bindings have an invalid type.")
    resolved = resolved_bindings[0]
    verified_bindings = resolve_analysis_snapshot_v4(
        manifest,
        now=at,
        snapshots={resolved.snapshot.snapshot_id: resolved.snapshot},
        reports={resolved.report.report_id: resolved.report},
        observations={
            item.market_data_id: item
            for binding in resolved_bindings
            for item in binding.observations
        },
        sources={
            item.source_record_id: item
            for binding in resolved_bindings
            for item in binding.sources
        },
        regimes={item.regime.regime_id: item.regime for item in resolved_bindings},
        evidence=evidence,
    )
    if verified_bindings != resolved_bindings:
        raise AnalysisV2ContractError(
            "Resolved bindings differ from exact C-007 v4 dependencies."
        )
    binding = resolved.binding
    refs = {
        (item.contract_id, item.record_id): item for item in manifest.analysis_outputs
    }
    if context.confluence.independence_report not in manifest.analysis_outputs:
        raise AnalysisV2ContractError(
            "C-007 v4 does not bind the registry-resolved C-093 output."
        )
    expected_outputs = tuple(
        sorted(
            (
                AnalysisOutputReferenceV4(
                    "C-009",
                    context.confluence.assessment_id,
                    "3",
                    "3",
                    canonical_sha256(context.confluence),
                ),
                *(
                    AnalysisOutputReferenceV4(
                        "C-010", item.assessment_id, "3", "3", canonical_sha256(item)
                    )
                    for item in context.conflicts
                ),
                context.confluence.independence_report,
            ),
            key=lambda item: (item.contract_id, str(item.record_id)),
        )
    )
    actual_outputs = tuple(
        item
        for item in manifest.analysis_outputs
        if item.contract_id in {"C-009", "C-010", "C-093"}
    )
    if actual_outputs != expected_outputs:
        raise AnalysisV2ContractError(
            "C-007 v4 does not bind the exact C-009/C-010/C-093 outputs."
        )

    def validate_meta_output(
        output: ConfluenceAssessmentV3 | ConflictAssessmentV3,
    ) -> None:
        reference = refs.get((output.contract_id, output.assessment_id))
        if (
            reference is None
            or reference.schema_version != C009_C010_V3_SCHEMA_VERSION
            or reference.lineage_version != C009_C010_V3_SCHEMA_VERSION
            or reference.content_sha256 != canonical_sha256(output)
            or output.input_snapshot_id != manifest.snapshot_id
            or output.input_snapshot_schema_version != C007_V4_SCHEMA_VERSION
            or (output.asset, output.instrument_id, output.timeframe, output.as_of)
            != (
                manifest.asset,
                manifest.instrument_id,
                manifest.timeframe,
                manifest.analysis_cutoff,
            )
            or output.expires_at > manifest.expires_at
            or output.data_quality_reports != (binding.data_quality_report,)
            or not set(output.evidence_ids).issubset(evidence)
            or (
                isinstance(output, ConfluenceAssessmentV3)
                and output.status is ConfluenceStatusV2.AVAILABLE
                and any(not evidence[item_id].usable for item_id in output.evidence_ids)
            )
            or (
                isinstance(output, ConflictAssessmentV3)
                and output.evidence_state is ConflictEvidenceStateV2.VALID
                and any(not evidence[item_id].usable for item_id in output.evidence_ids)
            )
        ):
            raise AnalysisV2ContractError(
                "C-009/C-010 v3 output does not bind to C-007 v4."
            )

    validate_meta_output(context.confluence)
    for output in context.conflicts:
        validate_meta_output(output)
    if any(
        getattr(component.dependence, "value", None) == "INDEPENDENT"
        for component in context.confluence.components
    ):
        raise AnalysisV2ContractError(
            "A shared OHLCV snapshot cannot establish independent components."
        )
    if (
        context.regime.regime_id != binding.regime.record_id
        or context.regime != resolved.regime
        or context.regime.as_of > at
        or context.regime.expires_at > context.expires_at
    ):
        raise AnalysisV2ContractError("C-005 regime scope or expiry is invalid.")
    for assessment in context.assessments:
        if (
            assessment.asset != manifest.asset
            or assessment.instrument_id != manifest.instrument_id
            or assessment.as_of > manifest.analysis_cutoff
            or assessment.expires_at > min(manifest.expires_at, context.expires_at)
            or assessment.expires_at <= at
        ):
            raise AnalysisV2ContractError(
                "C-006 v5 assessment exceeds the manifest scope/time."
            )
    if (
        (adversarial.asset, adversarial.instrument_id, adversarial.timeframe)
        != (manifest.asset, manifest.instrument_id, manifest.timeframe)
        or (
            adversarial.coverage_start,
            adversarial.coverage_end,
            adversarial.snapshot_as_of,
            adversarial.analysis_cutoff,
        )
        != (
            binding.window_start,
            binding.window_end,
            binding.snapshot_as_of,
            binding.analysis_cutoff,
        )
        or adversarial.as_of != manifest.analysis_cutoff
        or adversarial.expires_at > min(context.expires_at, manifest.expires_at)
        or adversarial.data_quality_report != binding.data_quality_report
        or (
            adversarial.data_quality_report.content_sha256
            != canonical_sha256(resolved.report)
        )
    ):
        raise AnalysisV2ContractError(
            "C-019 v2 scope or C-003 v2 reference does not match C-007 v4."
        )
    usable_references: dict[UUID, AdversarialEvidenceReferenceV2] = {}
    for item in adversarial.evidence:
        evidence_id = item.evidence.record_id
        resolved_evidence = evidence.get(evidence_id)
        if (
            evidence_id not in manifest.evidence_ids
            or resolved_evidence is None
            or not resolved_evidence.usable
            or refs.get(("C-008", evidence_id)) != item.evidence
            or item.evidence.content_sha256 != canonical_sha256(resolved_evidence)
            or item.binding_ids != resolved_evidence.binding_ids
            or item.observation_ids != resolved_evidence.observation_ids
            or item.source_record_ids != resolved_evidence.source_record_ids
            or item.evidence not in binding.evidence
        ):
            raise AnalysisV2ContractError(
                "C-019 v2 evidence is unresolved, unusable, or outside C-007 v4."
            )
        usable_references[evidence_id] = item
    if not set(adversarial.contradictory_evidence_ids).issubset(usable_references):
        raise AnalysisV2ContractError(
            "Contradictory evidence is outside the exact usable C-008 set."
        )
    if adversarial.expires_at <= at or adversarial.as_of > at:
        raise AnalysisV2ContractError("C-019 v2 is stale or expired.")


__all__ = [
    "AdversarialAssessmentV2",
    "AdversarialEvidenceReferenceV2",
    "C006_V5_SCHEMA_VERSION",
    "C006_V5_LINEAGE_VERSION",
    "C019_V2_LINEAGE_VERSION",
    "C019_V2_SCHEMA_VERSION",
    "MarketContextV5",
    "validate_market_context_v5",
]
