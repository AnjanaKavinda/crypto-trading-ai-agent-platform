"""Additive C-007/C-009/C-010/C-006 Spot OHLCV contract path.

This module contains immutable wire models and deterministic reference checks
only. It does not calculate confluence, conflict, or market context.
"""

from __future__ import annotations

from dataclasses import dataclass, field, fields
from datetime import datetime, timedelta
from enum import StrEnum
from hashlib import sha256
from typing import Mapping, get_args
from uuid import UUID

from trading_platform_api.analysis.contracts import (
    AdversarialAssessment,
    AnalyticalUncertainty,
    MarketRegime,
    ResolutionStatus,
    VersionReference,
    _text,
    _time,
    _typed_tuple,
    _unique,
    _uuid,
    _uuid_tuple,
)
from trading_platform_api.analysis.spot_market_regime import (
    SPOT_MARKET_REGIME_METHOD_VERSION,
    SPOT_MARKET_REGIME_PROFILE_VERSION,
)
from trading_platform_api.analysis.versioned_contracts import (
    _SHA256,
    ANALYSIS_V3_SCHEMA_VERSION,
    AnalysisOutputReferenceV3,
    AnalysisRecordReference,
    AnalysisSnapshotReferenceV3,
    AnalysisV2ContractError,
    AnalyticalConfidenceV2,
    ConflictAssessmentV2,
    ConflictEvidenceStateV2,
    ConflictMaterialityV2,
    ConflictReasonV2,
    ConflictSeverityV2,
    ConfluenceAssessmentV2,
    ConfluenceComponentV2,
    ConfluenceEvidenceStrengthV2,
    ConfluenceReasonV2,
    ConfluenceStateV2,
    ConfluenceStatusV2,
    EvidenceItemV2,
    MarketContextV3,
    ObservationSourceBinding,
    VersionedAssessment,
    validate_evidence_item_v2_resolved,
)
from trading_platform_api.contracts.serialization import (
    CANONICAL_JSON_VERSION,
    canonical_json_dumps,
    canonical_sha256,
)
from trading_platform_api.market_data.contracts import (
    AssessmentPolicyReference,
    DataQualityReportV2,
    DataQualityStatus,
    DatasetVersion,
    DataSourceRecord,
    MarketData,
    MarketSnapshot,
)
from trading_platform_api.market_data.quality import (
    DataQualityAssessmentError,
    SpotQualityPolicy,
    validate_spot_ohlcv_quality_v2,
)

C007_V4_SCHEMA_VERSION = "4"
C009_C010_V3_SCHEMA_VERSION = "3"
C006_V4_SCHEMA_VERSION = "4"
C093RegistryReference = "registry-resolved"


class InputModalityV4(StrEnum):
    """C-007 v4 modality; intentionally separate from historical enums."""

    SPOT_OHLCV = "spot-ohlcv"


@dataclass(frozen=True, slots=True)
class AnalysisOutputReferenceV4:
    """Content reference with fixed versions for owned contracts.

    C-093 schema and lineage are deliberately not fixed here: its owner (#67)
    supplies the exact supported reference to the validator.
    """

    contract_id: str
    record_id: UUID
    schema_version: str
    lineage_version: str
    content_sha256: str
    method: VersionReference | None = None

    def __post_init__(self) -> None:
        allowed = {"C-005", "C-008", "C-009", "C-010", "C-093"}
        if self.contract_id not in allowed:
            raise AnalysisV2ContractError("Unsupported C-007 v4 output contract.")
        _uuid("record_id", self.record_id)
        schema = _text("schema_version", self.schema_version)
        lineage = _text("lineage_version", self.lineage_version)
        expected = {
            "C-005": ("1", "1"),
            "C-008": ("2", "2"),
            "C-009": ("3", "3"),
            "C-010": ("3", "3"),
        }
        if (
            self.contract_id in expected
            and (schema, lineage) != expected[self.contract_id]
        ):
            raise AnalysisV2ContractError("Output schema or lineage version mismatch.")
        if self.contract_id == "C-093":
            if type(self.method) is not VersionReference:
                raise AnalysisV2ContractError(
                    "C-093 reference requires its registry-resolved method/version."
                )
        elif self.method is not None:
            raise AnalysisV2ContractError(
                "Method metadata belongs to the C-093 owner reference only."
            )
        if _SHA256.fullmatch(_text("content_sha256", self.content_sha256)) is None:
            raise AnalysisV2ContractError("content_sha256 must be lowercase SHA-256.")


@dataclass(frozen=True, slots=True)
class SpotOHLCVBindingV4:
    binding_id: UUID
    modality: InputModalityV4
    market_snapshot: AnalysisRecordReference
    snapshot_as_of: datetime
    analysis_cutoff: datetime
    instrument_id: str
    venue_id: str
    timeframe: str
    window_start: datetime
    window_end: datetime
    data_quality_report: AnalysisRecordReference
    assessment_policy: AssessmentPolicyReference
    observations: tuple[ObservationSourceBinding, ...]
    source_records: tuple[AnalysisRecordReference, ...]
    regime: AnalysisOutputReferenceV4
    regime_method: VersionReference
    regime_profile: VersionReference
    evidence: tuple[AnalysisOutputReferenceV4, ...]
    dataset_version: AnalysisRecordReference | None = None

    def __post_init__(self) -> None:
        _uuid("binding_id", self.binding_id)
        if (
            type(self.modality) is not InputModalityV4
            or self.modality is not InputModalityV4.SPOT_OHLCV
        ):
            raise AnalysisV2ContractError("C-007 v4 requires spot-ohlcv modality.")
        if (
            type(self.market_snapshot) is not AnalysisRecordReference
            or self.market_snapshot.contract_id != "C-002"
        ):
            raise AnalysisV2ContractError("market_snapshot must reference C-002.")
        if (
            type(self.data_quality_report) is not AnalysisRecordReference
            or self.data_quality_report.contract_id != "C-003"
        ):
            raise AnalysisV2ContractError("data_quality_report must reference C-003.")
        if type(self.assessment_policy) is not AssessmentPolicyReference:
            raise AnalysisV2ContractError("assessment_policy must be exact.")
        if (
            type(self.regime) is not AnalysisOutputReferenceV4
            or self.regime.contract_id != "C-005"
        ):
            raise AnalysisV2ContractError("regime must reference exact C-005 output.")
        if (
            type(self.regime_method) is not VersionReference
            or type(self.regime_profile) is not VersionReference
        ):
            raise AnalysisV2ContractError(
                "C-005 method and profile versions must be explicit."
            )
        if self.regime_method != VersionReference(
            "spot-market-regime", SPOT_MARKET_REGIME_METHOD_VERSION
        ) or self.regime_profile != VersionReference(
            "spot-ohlcv-regime-profile", SPOT_MARKET_REGIME_PROFILE_VERSION
        ):
            raise AnalysisV2ContractError("Unsupported C-005 method/profile version.")
        _text("instrument_id", self.instrument_id)
        _text("venue_id", self.venue_id)
        _text("timeframe", self.timeframe)
        snapshot_time = _time("snapshot_as_of", self.snapshot_as_of)
        cutoff = _time("analysis_cutoff", self.analysis_cutoff)
        start = _time("window_start", self.window_start)
        end = _time("window_end", self.window_end)
        if not start < end or snapshot_time > cutoff:
            raise AnalysisV2ContractError("Invalid OHLCV binding time scope.")
        observations = _typed_tuple(
            "observations", self.observations, ObservationSourceBinding, empty=False
        )
        _unique(
            "OHLCV observation IDs",
            tuple(item.observation.record_id for item in observations),
        )
        sources = _typed_tuple(
            "source_records", self.source_records, AnalysisRecordReference, empty=False
        )
        if any(item.contract_id != "C-091" for item in sources):
            raise AnalysisV2ContractError("source_records must be C-091 references.")
        _unique("source-record IDs", tuple(item.record_id for item in sources))
        evidence = _typed_tuple(
            "evidence", self.evidence, AnalysisOutputReferenceV4, empty=False
        )
        if any(item.contract_id != "C-008" for item in evidence):
            raise AnalysisV2ContractError("evidence must contain C-008 v2 references.")
        if tuple(item.record_id for item in evidence) != tuple(
            sorted({item.record_id for item in evidence}, key=str)
        ):
            raise AnalysisV2ContractError(
                "C-008 references must be unique and ordered."
            )
        if self.dataset_version is not None:
            raise AnalysisV2ContractError(
                "Approved C-003 OHLCV policy does not support C-092 datasets."
            )
        object.__setattr__(self, "snapshot_as_of", snapshot_time)
        object.__setattr__(self, "analysis_cutoff", cutoff)
        object.__setattr__(self, "window_start", start)
        object.__setattr__(self, "window_end", end)


@dataclass(frozen=True, slots=True)
class AnalysisSnapshotV4:
    snapshot_id: UUID
    asset: str
    instrument_id: str
    venue_id: str
    timeframe: str
    analysis_cutoff: datetime
    created_at: datetime
    expires_at: datetime
    bindings: tuple[SpotOHLCVBindingV4, ...]
    assessment_ids: tuple[UUID, ...]
    evidence_ids: tuple[UUID, ...]
    provenance: tuple[VersionReference, ...]
    analysis_outputs: tuple[AnalysisOutputReferenceV4, ...]
    content_sha256: str
    contract_id: str = field(default="C-007", init=False)
    schema_version: str = field(default=C007_V4_SCHEMA_VERSION, init=False)

    def __post_init__(self) -> None:
        _uuid("snapshot_id", self.snapshot_id)
        for name in ("asset", "instrument_id", "venue_id", "timeframe"):
            _text(name, getattr(self, name))
        cutoff = _time("analysis_cutoff", self.analysis_cutoff)
        created = _time("created_at", self.created_at)
        expires = _time("expires_at", self.expires_at)
        if cutoff > created or created > expires:
            raise AnalysisV2ContractError("Invalid C-007 v4 time order.")
        bindings = _typed_tuple(
            "bindings", self.bindings, SpotOHLCVBindingV4, empty=False
        )
        if len(bindings) != 1:
            raise AnalysisV2ContractError(
                "Spot profile v4 requires one exact OHLCV binding."
            )
        binding = bindings[0]
        if (
            binding.analysis_cutoff,
            binding.instrument_id,
            binding.venue_id,
            binding.timeframe,
        ) != (cutoff, self.instrument_id, self.venue_id, self.timeframe):
            raise AnalysisV2ContractError(
                "OHLCV binding differs from the manifest scope."
            )
        _uuid_tuple("assessment_ids", self.assessment_ids, empty=False)
        _uuid_tuple("evidence_ids", self.evidence_ids, empty=False)
        if tuple(item.record_id for item in binding.evidence) != tuple(
            sorted(self.evidence_ids, key=str)
        ):
            raise AnalysisV2ContractError(
                "C-008 evidence references must equal manifest evidence membership."
            )
        provenance = _typed_tuple(
            "provenance", self.provenance, VersionReference, empty=False
        )
        _unique("manifest provenance", provenance)
        if (
            binding.regime_method not in provenance
            or binding.regime_profile not in provenance
        ):
            raise AnalysisV2ContractError(
                "C-007 v4 provenance omits its C-005 method/profile version."
            )
        outputs = _typed_tuple(
            "analysis_outputs",
            self.analysis_outputs,
            AnalysisOutputReferenceV4,
            empty=False,
        )
        keys = tuple((item.contract_id, str(item.record_id)) for item in outputs)
        if keys != tuple(sorted(keys)) or len(set(keys)) != len(keys):
            raise AnalysisV2ContractError(
                "analysis_outputs must be unique and ordered."
            )
        output_ids = {(item.contract_id, item.record_id) for item in outputs}
        required = {
            ("C-005", binding.regime.record_id),
            *(("C-008", item.record_id) for item in binding.evidence),
        }
        if not required.issubset(output_ids):
            raise AnalysisV2ContractError(
                "C-007 v4 omits a required C-005/C-008 output reference."
            )
        if (
            _SHA256.fullmatch(_text("content_sha256", self.content_sha256)) is None
            or analysis_snapshot_v4_sha256(self) != self.content_sha256
        ):
            raise AnalysisV2ContractError("C-007 v4 content digest mismatch.")
        object.__setattr__(self, "analysis_cutoff", cutoff)
        object.__setattr__(self, "created_at", created)
        object.__setattr__(self, "expires_at", expires)


def _manifest_v4_preimage(manifest: AnalysisSnapshotV4) -> dict[str, object]:
    return {
        "canonicalization_version": CANONICAL_JSON_VERSION,
        "contract_id": manifest.contract_id,
        "schema_version": manifest.schema_version,
        "payload_version": "wire-1",
        "payload": {
            item.name: getattr(manifest, item.name)
            for item in fields(manifest)
            if item.name not in {"contract_id", "schema_version", "content_sha256"}
        },
    }


def analysis_snapshot_v4_sha256(manifest: AnalysisSnapshotV4) -> str:
    return sha256(
        canonical_json_dumps(_manifest_v4_preimage(manifest)).encode("utf-8")
    ).hexdigest()


def create_analysis_snapshot_v4(**values: object) -> AnalysisSnapshotV4:
    values = dict(values)
    values["content_sha256"] = "0" * 64
    temporary = object.__new__(AnalysisSnapshotV4)
    for name, value in values.items():
        object.__setattr__(temporary, name, value)
    object.__setattr__(temporary, "contract_id", "C-007")
    object.__setattr__(temporary, "schema_version", C007_V4_SCHEMA_VERSION)
    values["content_sha256"] = analysis_snapshot_v4_sha256(temporary)
    return AnalysisSnapshotV4(**values)  # type: ignore[arg-type]


@dataclass(frozen=True, slots=True)
class ResolvedSpotOHLCVBindingV4:
    binding: SpotOHLCVBindingV4
    snapshot: MarketSnapshot
    report: DataQualityReportV2
    policy: SpotQualityPolicy
    observations: tuple[MarketData, ...]
    sources: tuple[DataSourceRecord, ...]
    dataset: DatasetVersion | None
    dependency_expires_at: datetime
    direct_inputs_pass: bool
    regime: MarketRegime
    evidence: tuple[EvidenceItemV2, ...]


def resolve_analysis_snapshot_v4(
    manifest: AnalysisSnapshotV4,
    *,
    now: datetime,
    snapshots: Mapping[UUID, MarketSnapshot],
    reports: Mapping[UUID, DataQualityReportV2],
    observations: Mapping[UUID, MarketData],
    sources: Mapping[UUID, DataSourceRecord],
    regimes: Mapping[UUID, MarketRegime],
    evidence: Mapping[UUID, EvidenceItemV2],
) -> tuple[ResolvedSpotOHLCVBindingV4, ...]:
    if type(manifest) is not AnalysisSnapshotV4:
        raise AnalysisV2ContractError("Expected exact C-007 schema 4.")
    at = _time("now", now)
    if manifest.created_at > at or manifest.expires_at <= at:
        raise AnalysisV2ContractError("Manifest is expired or not yet available.")
    refs = {
        (item.contract_id, item.record_id): item for item in manifest.analysis_outputs
    }
    resolved: list[ResolvedSpotOHLCVBindingV4] = []
    for binding in manifest.bindings:
        try:
            snap_id = UUID(binding.market_snapshot.record_id)
            report_id = UUID(binding.data_quality_report.record_id)
            snapshot = snapshots[snap_id]
            report = reports[report_id]
        except (ValueError, KeyError, TypeError) as exc:
            raise AnalysisV2ContractError(
                "Missing exact C-002/C-003 dependency."
            ) from exc
        if (
            binding.market_snapshot.content_sha256 != canonical_sha256(snapshot)
            or binding.data_quality_report.content_sha256 != canonical_sha256(report)
            or binding.market_snapshot.schema_version != "1"
            or binding.market_snapshot.lineage_version != "1"
            or binding.data_quality_report.schema_version != "2"
            or binding.data_quality_report.lineage_version != "2"
            or snapshot.snapshot_id != snap_id
            or report.report_id != report_id
            or report.snapshot_id != snap_id
            or binding.snapshot_as_of != snapshot.as_of
            or snapshot.instrument_id != manifest.instrument_id
            or snapshot.venue_id != manifest.venue_id
            or binding.instrument_id != snapshot.instrument_id
            or binding.venue_id != snapshot.venue_id
            or report.assessment_policy_id != binding.assessment_policy.policy_id
            or report.assessment_policy_version != binding.assessment_policy.version
            or snapshot.dataset_version is not None
        ):
            raise AnalysisV2ContractError(
                "C-002/C-003 reference, scope, or digest mismatch."
            )
        try:
            obs = tuple(
                observations[UUID(ref.observation.record_id)]
                for ref in binding.observations
            )
            src = tuple(
                sources[UUID(ref.source.record_id)] for ref in binding.observations
            )
        except (ValueError, KeyError, TypeError) as exc:
            raise AnalysisV2ContractError(
                "Missing exact OHLCV observation/source."
            ) from exc
        for ref, observation, source in zip(
            binding.observations, obs, src, strict=True
        ):
            if (
                ref.observation.content_sha256 != canonical_sha256(observation)
                or ref.source.content_sha256 != canonical_sha256(source)
                or observation.observation_type != "OHLCV"
                or observation.source_record_id != source.source_record_id
                or source.source_record_id != UUID(ref.source.record_id)
                or observation.instrument_id != snapshot.instrument_id
                or observation.venue_id != snapshot.venue_id
            ):
                raise AnalysisV2ContractError(
                    "OHLCV source lineage or digest mismatch."
                )
        if (
            tuple(item.market_data_id for item in obs) != snapshot.market_data_ids
            or tuple(item.source_record_id for item in src)
            != snapshot.source_record_ids
            or tuple(item.market_data_id for item in obs)
            != tuple(UUID(item.observation.record_id) for item in binding.observations)
            or tuple(item.source_record_id for item in src)
            != tuple(UUID(item.record_id) for item in binding.source_records)
            or tuple(item.content_sha256 for item in binding.source_records)
            != tuple(canonical_sha256(item) for item in src)
            or any(
                item.event_time > snapshot.as_of
                or item.availability_time > manifest.analysis_cutoff
                for item in obs
            )
            or any(item.availability_time > manifest.analysis_cutoff for item in src)
            or obs[0].event_time != binding.window_start
            or obs[-1].event_time >= binding.window_end
        ):
            raise AnalysisV2ContractError(
                "OHLCV observation membership/window mismatch."
            )
        try:
            policy = validate_spot_ohlcv_quality_v2(
                report,
                snapshot=snapshot,
                observations=obs,
                sources=src,
                timeframe=binding.timeframe,
            )
        except (DataQualityAssessmentError, ValueError, TypeError) as exc:
            raise AnalysisV2ContractError(
                "C-003 report is not valid for this OHLCV binding."
            ) from exc
        if (
            policy.assessment_policy_id != binding.assessment_policy.policy_id
            or policy.resolved_policy_version != binding.assessment_policy.version
            or policy.coverage_start != binding.window_start
            or policy.coverage_end != binding.window_end
            or report.assessed_at > manifest.analysis_cutoff
        ):
            raise AnalysisV2ContractError("C-003 policy/window/cutoff mismatch.")
        regime_ref = refs.get(("C-005", binding.regime.record_id))
        try:
            regime = regimes[binding.regime.record_id]
        except KeyError as exc:
            raise AnalysisV2ContractError("Missing exact C-005 MarketRegime.") from exc
        if (
            regime_ref != binding.regime
            or type(regime) is not MarketRegime
            or binding.regime.content_sha256 != canonical_sha256(regime)
            or (regime.asset, regime.instrument_id, regime.timeframe, regime.as_of)
            != (
                manifest.asset,
                manifest.instrument_id,
                manifest.timeframe,
                snapshot.as_of,
            )
            or regime.expires_at > manifest.expires_at
            or set(regime.evidence_ids) != {item.record_id for item in binding.evidence}
        ):
            raise AnalysisV2ContractError(
                "C-005 regime is not bound to this snapshot/window/evidence."
            )
        evidence_refs = {item.record_id: item for item in binding.evidence}
        for evidence_id, reference in evidence_refs.items():
            item = evidence.get(evidence_id)
            if (
                item is None
                or reference != refs.get(("C-008", evidence_id))
                or reference.content_sha256 != canonical_sha256(item)
                or item.contract_id != "C-008"
                or item.schema_version != "2"
                or item.binding_ids != (binding.binding_id,)
                or not set(item.observation_ids).issubset(
                    {record.market_data_id for record in obs}
                )
                or set(item.source_record_ids)
                != {
                    record.source_record_id
                    for record in obs
                    if record.market_data_id in item.observation_ids
                }
                or item.quality_status is not DataQualityStatus.VALID
                or not item.usable
                or item.method != binding.regime_method
                or binding.regime_profile not in item.provenance
                or item.method not in item.provenance
                or item.observed_at > manifest.analysis_cutoff
                or item.available_at > manifest.analysis_cutoff
                or item.expires_at > min(manifest.expires_at, regime.expires_at)
            ):
                raise AnalysisV2ContractError(
                    "C-008 v2 evidence does not exactly resolve to C-007 v4."
                )
        resolved.append(
            ResolvedSpotOHLCVBindingV4(
                binding,
                snapshot,
                report,
                policy,
                obs,
                src,
                None,
                min(
                    snapshot.as_of + timedelta(seconds=policy.freshness_seconds),
                    regime.expires_at,
                ),
                True,
                regime,
                tuple(evidence[item_id] for item_id in evidence_refs),
            )
        )
    if any(
        item.dependency_expires_at <= at
        or manifest.expires_at > item.dependency_expires_at
        for item in resolved
    ):
        raise AnalysisV2ContractError("Manifest exceeds an input dependency expiry.")
    return tuple(resolved)


def validate_evidence_item_v2_for_v4(
    evidence: EvidenceItemV2,
    manifest: AnalysisSnapshotV4,
    *,
    resolved_bindings: tuple[ResolvedSpotOHLCVBindingV4, ...],
    now: datetime,
) -> None:
    """Prove unchanged C-008 v2 evidence works with C-007 v4, without conversion."""
    if type(evidence) is not EvidenceItemV2 or type(manifest) is not AnalysisSnapshotV4:
        raise AnalysisV2ContractError("Expected exact C-008 v2/C-007 v4 contracts.")
    if len(resolved_bindings) != 1:
        raise AnalysisV2ContractError(
            "C-007 v4 requires its single resolved OHLCV binding."
        )
    validate_evidence_item_v2_resolved(
        evidence, manifest, resolved_bindings=resolved_bindings, now=now
    )


@dataclass(frozen=True, slots=True)
class AnalysisSnapshotReferenceV4:
    snapshot_id: UUID
    schema_version: str
    content_sha256: str

    def __post_init__(self) -> None:
        _uuid("snapshot_id", self.snapshot_id)
        if (
            _text("schema_version", self.schema_version) != C007_V4_SCHEMA_VERSION
            or _SHA256.fullmatch(_text("content_sha256", self.content_sha256)) is None
        ):
            raise AnalysisV2ContractError("Invalid C-006 v4 snapshot reference.")


@dataclass(frozen=True, slots=True)
class ConfluenceAssessmentV3:
    assessment_id: UUID
    asset: str
    instrument_id: str
    timeframe: str
    as_of: datetime
    expires_at: datetime
    state: ConfluenceStateV2
    status: ConfluenceStatusV2
    status_reason: ConfluenceReasonV2 | None
    components: tuple[ConfluenceComponentV2, ...]
    analytical_confidence: AnalyticalConfidenceV2
    evidence_strength: ConfluenceEvidenceStrengthV2
    independence_report: AnalysisOutputReferenceV4
    input_snapshot_id: UUID
    input_snapshot_schema_version: str
    data_quality_reports: tuple[AnalysisRecordReference, ...]
    evidence_ids: tuple[UUID, ...]
    method: VersionReference
    provenance: tuple[VersionReference, ...]
    contract_id: str = field(default="C-009", init=False)
    schema_version: str = field(default=C009_C010_V3_SCHEMA_VERSION, init=False)

    def __post_init__(self) -> None:
        if self.input_snapshot_schema_version != C007_V4_SCHEMA_VERSION:
            raise AnalysisV2ContractError("C-009 v3 requires C-007 schema 4.")
        if (
            type(self.independence_report) is not AnalysisOutputReferenceV4
            or self.independence_report.contract_id != "C-093"
        ):
            raise AnalysisV2ContractError(
                "C-009 v3 requires a registry-resolved C-093 reference."
            )
        _semantic_confluence_v2(self)


def _semantic_confluence_v2(value: ConfluenceAssessmentV3) -> ConfluenceAssessmentV2:
    ref = AnalysisOutputReferenceV3(
        "C-093",
        value.independence_report.record_id,
        value.independence_report.schema_version,
        value.independence_report.lineage_version,
        value.independence_report.content_sha256,
    )
    return ConfluenceAssessmentV2(
        value.assessment_id,
        value.asset,
        value.instrument_id,
        value.timeframe,
        value.as_of,
        value.expires_at,
        value.state,
        value.status,
        value.status_reason,
        value.components,
        value.analytical_confidence,
        value.evidence_strength,
        ref,
        value.input_snapshot_id,
        ANALYSIS_V3_SCHEMA_VERSION,
        value.data_quality_reports,
        value.evidence_ids,
        value.method,
        value.provenance,
    )


@dataclass(frozen=True, slots=True)
class ConflictAssessmentV3:
    assessment_id: UUID
    asset: str
    instrument_id: str
    timeframe: str
    as_of: datetime
    expires_at: datetime
    finding_ids: tuple[UUID, ...]
    evidence_ids: tuple[UUID, ...]
    severity: ConflictSeverityV2
    evidence_state: ConflictEvidenceStateV2
    materiality: ConflictMaterialityV2
    direct_opposition: bool | None
    required_premise_invalid: bool | None
    unsafe_to_rely: bool | None
    status_reason: ConflictReasonV2 | None
    explanation: str
    resolution_status: ResolutionStatus
    input_snapshot_id: UUID
    input_snapshot_schema_version: str
    data_quality_reports: tuple[AnalysisRecordReference, ...]
    method: VersionReference
    provenance: tuple[VersionReference, ...]
    contract_id: str = field(default="C-010", init=False)
    schema_version: str = field(default=C009_C010_V3_SCHEMA_VERSION, init=False)

    def __post_init__(self) -> None:
        if self.input_snapshot_schema_version != C007_V4_SCHEMA_VERSION:
            raise AnalysisV2ContractError("C-010 v3 requires C-007 schema 4.")
        _semantic_conflict_v2(self)


def _semantic_conflict_v2(value: ConflictAssessmentV3) -> ConflictAssessmentV2:
    return ConflictAssessmentV2(
        value.assessment_id,
        value.asset,
        value.instrument_id,
        value.timeframe,
        value.as_of,
        value.expires_at,
        value.finding_ids,
        value.evidence_ids,
        value.severity,
        value.evidence_state,
        value.materiality,
        value.direct_opposition,
        value.required_premise_invalid,
        value.unsafe_to_rely,
        value.status_reason,
        value.explanation,
        value.resolution_status,
        value.input_snapshot_id,
        ANALYSIS_V3_SCHEMA_VERSION,
        value.data_quality_reports,
        value.method,
        value.provenance,
    )


@dataclass(frozen=True, slots=True)
class MarketContextV4:
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
    adversarial: AdversarialAssessment
    uncertainties: tuple[AnalyticalUncertainty, ...]
    evidence_ids: tuple[UUID, ...]
    analysis_snapshot: AnalysisSnapshotReferenceV4
    contract_id: str = field(default="C-006", init=False)
    schema_version: str = field(default=C006_V4_SCHEMA_VERSION, init=False)

    def __post_init__(self) -> None:
        _uuid("context_id", self.context_id)
        _text("asset", self.asset)
        _text("instrument_id", self.instrument_id)
        as_of = _time("as_of", self.as_of)
        expires = _time("expires_at", self.expires_at)
        if as_of > expires:
            raise AnalysisV2ContractError("C-006 v4 has invalid time order.")
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
            or type(self.adversarial) is not AdversarialAssessment
        ):
            raise AnalysisV2ContractError(
                "C-006 v4 contains an invalid typed assessment."
            )
        if (
            type(self.assessments) is not tuple
            or not self.assessments
            or any(
                type(item) not in get_args(VersionedAssessment)
                for item in self.assessments
            )
        ):
            raise AnalysisV2ContractError("C-006 v4 assessments are empty or invalid.")
        _typed_tuple("conflicts", self.conflicts, ConflictAssessmentV3)
        _typed_tuple(
            "uncertainties", self.uncertainties, AnalyticalUncertainty, empty=False
        )
        _uuid_tuple("evidence_ids", self.evidence_ids, empty=False)
        if type(self.analysis_snapshot) is not AnalysisSnapshotReferenceV4:
            raise AnalysisV2ContractError("C-006 v4 must reference C-007 v4.")
        MarketContextV3(
            self.context_id,
            self.asset,
            self.instrument_id,
            as_of,
            expires,
            self.multi_timeframe_state,
            self.regime,
            self.assessments,
            _semantic_confluence_v2(self.confluence),
            tuple(_semantic_conflict_v2(item) for item in self.conflicts),
            self.adversarial,
            self.uncertainties,
            self.evidence_ids,
            AnalysisSnapshotReferenceV3(
                self.analysis_snapshot.snapshot_id,
                "3",
                self.analysis_snapshot.content_sha256,
            ),
        )
        object.__setattr__(self, "as_of", as_of)
        object.__setattr__(self, "expires_at", expires)


def validate_market_context_v4(
    context: MarketContextV4,
    manifest: AnalysisSnapshotV4,
    *,
    resolved_bindings: tuple[ResolvedSpotOHLCVBindingV4, ...],
    evidence: Mapping[UUID, EvidenceItemV2],
    supported_independence_reports: tuple[AnalysisOutputReferenceV4, ...],
    now: datetime,
) -> None:
    if type(context) is not MarketContextV4 or type(manifest) is not AnalysisSnapshotV4:
        raise AnalysisV2ContractError("Expected exact C-006 v4/C-007 v4 contracts.")
    at = _time("now", now)
    if context.expires_at <= at or manifest.expires_at <= at:
        raise AnalysisV2ContractError("Market context or manifest is expired.")
    if (
        context.analysis_snapshot.snapshot_id != manifest.snapshot_id
        or context.analysis_snapshot.content_sha256 != manifest.content_sha256
        or context.asset != manifest.asset
        or context.instrument_id != manifest.instrument_id
        or context.as_of != manifest.analysis_cutoff
        or context.expires_at > manifest.expires_at
        or context.evidence_ids != manifest.evidence_ids
        or tuple(item.assessment_id for item in context.assessments)
        != manifest.assessment_ids
    ):
        raise AnalysisV2ContractError(
            "C-006 v4 does not bind to the exact C-007 v4 manifest."
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
    if set(evidence) != set(manifest.evidence_ids) or len(resolved_bindings) != 1:
        raise AnalysisV2ContractError(
            "C-008 evidence or C-007 bindings are not exactly resolved."
        )
    if type(resolved_bindings) is not tuple or any(
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
            observation.market_data_id: observation
            for resolved_binding in resolved_bindings
            for observation in resolved_binding.observations
        },
        sources={
            source.source_record_id: source
            for resolved_binding in resolved_bindings
            for source in resolved_binding.sources
        },
        regimes={
            resolved_binding.regime.regime_id: resolved_binding.regime
            for resolved_binding in resolved_bindings
        },
        evidence=evidence,
    )
    if verified_bindings != resolved_bindings:
        raise AnalysisV2ContractError(
            "Resolved bindings differ from exact C-007 v4 dependencies."
        )
    binding_refs = {
        ("C-005", manifest.bindings[0].regime.record_id),
        *(("C-008", item.record_id) for item in manifest.bindings[0].evidence),
    }
    actual_binding_refs = {
        (item.contract_id, item.record_id)
        for item in manifest.analysis_outputs
        if item.contract_id in {"C-005", "C-008"}
    }
    if actual_binding_refs != binding_refs:
        raise AnalysisV2ContractError(
            "C-007 v4 contains missing or unsupported C-005/C-008 references."
        )
    binding = resolved_bindings[0]
    for evidence_id, item in evidence.items():
        if item.evidence_id != evidence_id:
            raise AnalysisV2ContractError(
                "C-008 mapping key differs from evidence identity."
            )
        validate_evidence_item_v2_for_v4(
            item, manifest, resolved_bindings=resolved_bindings, now=at
        )
    refs = {
        (item.contract_id, item.record_id): item for item in manifest.analysis_outputs
    }
    if (
        refs.get(("C-093", context.confluence.independence_report.record_id))
        != context.confluence.independence_report
    ):
        raise AnalysisV2ContractError(
            "C-007 v4 does not bind the registry-resolved C-093 output."
        )
    expected_meta_outputs = tuple(
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
                        "C-010",
                        item.assessment_id,
                        "3",
                        "3",
                        canonical_sha256(item),
                    )
                    for item in context.conflicts
                ),
                context.confluence.independence_report,
            ),
            key=lambda item: (item.contract_id, str(item.record_id)),
        )
    )
    actual_meta_outputs = tuple(
        item
        for item in manifest.analysis_outputs
        if item.contract_id in {"C-009", "C-010", "C-093"}
    )
    if actual_meta_outputs != expected_meta_outputs:
        raise AnalysisV2ContractError(
            "C-007 v4 does not bind the exact C-009/C-010/C-093 outputs."
        )
    meta_outputs: tuple[ConfluenceAssessmentV3 | ConflictAssessmentV3, ...] = (
        context.confluence,
        *context.conflicts,
    )
    for output in meta_outputs:
        ref = refs.get((output.contract_id, output.assessment_id))
        if (
            ref is None
            or ref.schema_version != "3"
            or ref.lineage_version != "3"
            or ref.content_sha256 != canonical_sha256(output)
            or output.input_snapshot_id != manifest.snapshot_id
            or output.input_snapshot_schema_version != "4"
            or (output.asset, output.instrument_id, output.timeframe, output.as_of)
            != (
                manifest.asset,
                manifest.instrument_id,
                manifest.timeframe,
                manifest.analysis_cutoff,
            )
            or output.expires_at > manifest.expires_at
            or not set(output.evidence_ids).issubset(evidence)
            or tuple(output.data_quality_reports)
            != (binding.binding.data_quality_report,)
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
    # One OHLCV snapshot cannot establish independent evidence. This check is
    # intentionally conservative; C-093 remains the owner-resolved authority.
    if any(
        getattr(component.dependence, "value", None) == "INDEPENDENT"
        for component in context.confluence.components
    ):
        raise AnalysisV2ContractError(
            "A shared OHLCV snapshot cannot establish independent components."
        )
    if (
        context.regime.regime_id != binding.binding.regime.record_id
        or context.regime != binding.regime
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
                "C-006 v4 assessment exceeds the manifest scope/time."
            )


__all__ = [
    "AnalysisOutputReferenceV4",
    "AnalysisSnapshotReferenceV4",
    "AnalysisSnapshotV4",
    "C006_V4_SCHEMA_VERSION",
    "C007_V4_SCHEMA_VERSION",
    "C009_C010_V3_SCHEMA_VERSION",
    "ConfluenceAssessmentV3",
    "ConflictAssessmentV3",
    "InputModalityV4",
    "MarketContextV4",
    "ResolvedSpotOHLCVBindingV4",
    "SpotOHLCVBindingV4",
    "analysis_snapshot_v4_sha256",
    "create_analysis_snapshot_v4",
    "resolve_analysis_snapshot_v4",
    "validate_evidence_item_v2_for_v4",
    "validate_market_context_v4",
]
