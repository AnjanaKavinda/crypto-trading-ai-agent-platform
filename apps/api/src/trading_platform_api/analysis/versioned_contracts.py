from __future__ import annotations

import re
from dataclasses import dataclass, field, fields
from datetime import datetime, timedelta
from decimal import Decimal
from enum import StrEnum
from hashlib import sha256
from typing import ClassVar, Mapping, TypeAlias, get_args
from uuid import UUID

from trading_platform_api.contracts.serialization import (
    CANONICAL_JSON_VERSION,
    canonical_json_dumps,
    canonical_sha256,
)
from trading_platform_api.market_data.contracts import (
    AssessmentPolicyReference,
    DataQualityDimension,
    DataQualityDimensionReasonCode,
    DataQualityDimensionResult,
    DataQualityDimensionState,
    DataQualityReportV2,
    DataQualityStatus,
    DataSourceRecord,
    DatasetVersion,
    MarketData,
    MarketSnapshot,
    MetricValue,
)
from trading_platform_api.market_data.providers import ProviderDataKind
from trading_platform_api.market_data.quality import (
    DataQualityAssessmentError,
    SpotQualityPolicy,
)

from trading_platform_api.analysis.contracts import (
    AdversarialAssessment,
    AnalyticalUncertainty,
    Assessment,
    ClaimClassification,
    ConflictAssessment,
    ConfluenceAssessment,
    EvidenceRelation,
    MarketRegime,
    VersionReference,
    _text,
    _time,
    _typed_tuple,
    _unique,
    _uuid,
    _uuid_tuple,
)

ANALYSIS_V2_SCHEMA_VERSION = "2"
_SHA256 = re.compile(r"[0-9a-f]{64}")


class AnalysisV2ContractError(ValueError):
    """Raised when a versioned analysis contract or reference is invalid."""


class InputModality(StrEnum):
    SPOT_TRADES = "spot-trades"
    SPOT_TICKS = "spot-ticks"
    ORDER_BOOK = "order-book"


class OrderFlowMetricName(StrEnum):
    SPREAD = "spread"
    DISPLAYED_DEPTH = "displayed-depth"
    BOOK_IMBALANCE = "book-imbalance"
    TRADE_VOLUME = "trade-volume"
    VOLUME_DELTA = "volume-delta"
    CUMULATIVE_DELTA = "cumulative-delta"


class OrderFlowMetricState(StrEnum):
    AVAILABLE = "AVAILABLE"
    PARTIAL = "PARTIAL"
    UNAVAILABLE = "UNAVAILABLE"


class OrderFlowAssessmentState(StrEnum):
    AVAILABLE = "AVAILABLE"
    PARTIAL = "PARTIAL"
    UNAVAILABLE = "UNAVAILABLE"


@dataclass(frozen=True, slots=True)
class AnalysisRecordReference:
    contract_id: str
    record_id: str
    schema_version: str
    lineage_version: str
    content_sha256: str

    def __post_init__(self) -> None:
        if self.contract_id not in {"C-001", "C-002", "C-003", "C-091", "C-092"}:
            raise AnalysisV2ContractError("Unsupported analysis dependency contract.")
        _text("record_id", self.record_id)
        schema = _text("schema_version", self.schema_version)
        lineage = _text("lineage_version", self.lineage_version)
        expected = {
            "C-001": ("1", "1"),
            "C-002": ("1", "1"),
            "C-003": ("2", "2"),
            "C-091": ("1", "1"),
        }
        if self.contract_id in expected and (schema, lineage) != expected[self.contract_id]:
            raise AnalysisV2ContractError("Dependency schema or lineage version mismatch.")
        if self.contract_id == "C-092" and schema != "1":
            raise AnalysisV2ContractError("C-092 schema version must be 1.")
        if _SHA256.fullmatch(_text("content_sha256", self.content_sha256)) is None:
            raise AnalysisV2ContractError("content_sha256 must be a lowercase SHA-256 digest.")


@dataclass(frozen=True, slots=True)
class ObservationSourceBinding:
    observation: AnalysisRecordReference
    source: AnalysisRecordReference

    def __post_init__(self) -> None:
        if (
            type(self.observation) is not AnalysisRecordReference
            or self.observation.contract_id != "C-001"
            or type(self.source) is not AnalysisRecordReference
            or self.source.contract_id != "C-091"
        ):
            raise AnalysisV2ContractError("Observation/source references have invalid types.")
        try:
            UUID(self.observation.record_id)
            UUID(self.source.record_id)
        except ValueError as exc:
            raise AnalysisV2ContractError("C-001/C-091 record IDs must be UUIDs.") from exc


@dataclass(frozen=True, slots=True)
class InputBindingV2:
    binding_id: UUID
    modality: InputModality
    market_snapshot: AnalysisRecordReference
    snapshot_as_of: datetime
    analysis_cutoff: datetime
    instrument_id: str
    venue_id: str
    data_quality_report: AnalysisRecordReference
    assessment_policy: AssessmentPolicyReference
    observations: tuple[ObservationSourceBinding, ...]
    source_records: tuple[AnalysisRecordReference, ...]
    dataset_version: AnalysisRecordReference | None = None

    def __post_init__(self) -> None:
        _uuid("binding_id", self.binding_id)
        if type(self.modality) is not InputModality:
            raise AnalysisV2ContractError("modality must be an InputModality.")
        if (
            type(self.market_snapshot) is not AnalysisRecordReference
            or self.market_snapshot.contract_id != "C-002"
        ):
            raise AnalysisV2ContractError("market_snapshot must reference C-002 schema 1.")
        if (
            type(self.data_quality_report) is not AnalysisRecordReference
            or self.data_quality_report.contract_id != "C-003"
        ):
            raise AnalysisV2ContractError("data_quality_report must reference C-003 schema 2.")
        if type(self.assessment_policy) is not AssessmentPolicyReference:
            raise AnalysisV2ContractError("assessment_policy must be an exact policy reference.")
        for name in ("instrument_id", "venue_id"):
            _text(name, getattr(self, name))
        snapshot_time = _time("snapshot_as_of", self.snapshot_as_of)
        analysis_time = _time("analysis_cutoff", self.analysis_cutoff)
        if snapshot_time > analysis_time:
            raise AnalysisV2ContractError("snapshot_as_of must not be after analysis_cutoff.")
        observations = _typed_tuple(
            "observations", self.observations, ObservationSourceBinding, empty=False
        )
        observation_ids = tuple(item.observation.record_id for item in observations)
        _unique("observation references", observation_ids)
        sources = _typed_tuple(
            "source_records", self.source_records, AnalysisRecordReference, empty=False
        )
        if any(item.contract_id != "C-091" for item in sources):
            raise AnalysisV2ContractError("source_records must contain only C-091 references.")
        _unique("source-record references", tuple(item.record_id for item in sources))
        if self.dataset_version is not None and (
            type(self.dataset_version) is not AnalysisRecordReference
            or self.dataset_version.contract_id != "C-092"
        ):
            raise AnalysisV2ContractError("dataset_version must reference C-092 when present.")
        object.__setattr__(self, "snapshot_as_of", snapshot_time)
        object.__setattr__(self, "analysis_cutoff", analysis_time)


def _manifest_preimage(manifest: AnalysisSnapshotV2) -> dict[str, object]:
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


def analysis_snapshot_v2_sha256(manifest: AnalysisSnapshotV2) -> str:
    return sha256(canonical_json_dumps(_manifest_preimage(manifest)).encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class AnalysisSnapshotV2:
    snapshot_id: UUID
    asset: str
    instrument_id: str
    venue_id: str
    timeframe: str
    analysis_cutoff: datetime
    created_at: datetime
    expires_at: datetime
    bindings: tuple[InputBindingV2, ...]
    assessment_ids: tuple[UUID, ...]
    evidence_ids: tuple[UUID, ...]
    provenance: tuple[VersionReference, ...]
    content_sha256: str
    contract_id: str = field(default="C-007", init=False)
    schema_version: str = field(default=ANALYSIS_V2_SCHEMA_VERSION, init=False)

    def __post_init__(self) -> None:
        _uuid("snapshot_id", self.snapshot_id)
        for name in ("asset", "instrument_id", "venue_id", "timeframe"):
            _text(name, getattr(self, name))
        cutoff = _time("analysis_cutoff", self.analysis_cutoff)
        created = _time("created_at", self.created_at)
        expires = _time("expires_at", self.expires_at)
        if cutoff > created or created > expires:
            raise AnalysisV2ContractError("Invalid manifest analysis/creation/expiry order.")
        bindings = _typed_tuple("bindings", self.bindings, InputBindingV2, empty=False)
        if bindings != tuple(
            sorted(
                bindings,
                key=lambda item: (item.modality.value, item.market_snapshot.record_id),
            )
        ):
            raise AnalysisV2ContractError("bindings must use deterministic modality/snapshot order.")
        _unique("binding IDs", tuple(item.binding_id for item in bindings))
        _unique(
            "bound snapshots",
            tuple(item.market_snapshot.record_id for item in bindings),
        )
        _unique(
            "bound quality reports",
            tuple(item.data_quality_report.record_id for item in bindings),
        )
        if any(
            (item.analysis_cutoff, item.instrument_id, item.venue_id)
            != (cutoff, self.instrument_id, self.venue_id)
            for item in bindings
        ):
            raise AnalysisV2ContractError("Every binding must match the manifest context.")
        assessments = _uuid_tuple("assessment_ids", self.assessment_ids, empty=False)
        evidence = _uuid_tuple("evidence_ids", self.evidence_ids, empty=False)
        provenance = _typed_tuple(
            "provenance", self.provenance, VersionReference, empty=False
        )
        _unique("provenance", provenance)
        digest = _text("content_sha256", self.content_sha256)
        if _SHA256.fullmatch(digest) is None:
            raise AnalysisV2ContractError("content_sha256 must be a lowercase SHA-256 digest.")
        object.__setattr__(self, "analysis_cutoff", cutoff)
        object.__setattr__(self, "created_at", created)
        object.__setattr__(self, "expires_at", expires)
        if analysis_snapshot_v2_sha256(self) != digest:
            raise AnalysisV2ContractError("manifest content_sha256 does not match its canonical content.")


def create_analysis_snapshot_v2(**values: object) -> AnalysisSnapshotV2:
    values = dict(values)
    values["content_sha256"] = "0" * 64
    temporary = object.__new__(AnalysisSnapshotV2)
    for name, value in values.items():
        object.__setattr__(temporary, name, value)
    object.__setattr__(temporary, "contract_id", "C-007")
    object.__setattr__(temporary, "schema_version", ANALYSIS_V2_SCHEMA_VERSION)
    values["content_sha256"] = analysis_snapshot_v2_sha256(temporary)
    return AnalysisSnapshotV2(**values)  # type: ignore[arg-type]


@dataclass(frozen=True, slots=True)
class EvidenceItemV2:
    evidence_id: UUID
    binding_ids: tuple[UUID, ...]
    observation_ids: tuple[UUID, ...]
    source_record_ids: tuple[UUID, ...]
    dataset_versions: tuple[tuple[str, str], ...]
    feature_ids: tuple[str, ...]
    classification: ClaimClassification
    relation: EvidenceRelation
    observed_at: datetime
    available_at: datetime
    expires_at: datetime
    method: VersionReference
    value: str
    unit: str | None
    interpretation: str
    quality_status: DataQualityStatus
    reliability: Decimal
    limitations: tuple[str, ...]
    provenance: tuple[VersionReference, ...]
    usable: bool
    contract_id: str = field(default="C-008", init=False)
    schema_version: str = field(default=ANALYSIS_V2_SCHEMA_VERSION, init=False)

    def __post_init__(self) -> None:
        _uuid("evidence_id", self.evidence_id)
        _uuid_tuple("binding_ids", self.binding_ids, empty=False)
        _uuid_tuple("observation_ids", self.observation_ids, empty=False)
        _uuid_tuple("source_record_ids", self.source_record_ids, empty=False)
        if type(self.dataset_versions) is not tuple:
            raise AnalysisV2ContractError("dataset_versions must be a tuple.")
        datasets: list[tuple[str, str]] = []
        for value in self.dataset_versions:
            if type(value) is not tuple or len(value) != 2:
                raise AnalysisV2ContractError("dataset_versions must contain identity pairs.")
            datasets.append((_text("dataset_id", value[0]), _text("dataset_version", value[1])))
        _unique("dataset_versions", tuple(datasets))
        if type(self.feature_ids) is not tuple or any(
            not isinstance(item, str) or not item.strip() for item in self.feature_ids
        ):
            raise AnalysisV2ContractError("feature_ids must be a tuple of nonblank strings.")
        _unique("feature_ids", self.feature_ids)
        if type(self.classification) is not ClaimClassification:
            raise AnalysisV2ContractError("classification must be a ClaimClassification.")
        if type(self.relation) is not EvidenceRelation:
            raise AnalysisV2ContractError("relation must be an EvidenceRelation.")
        observed = _time("observed_at", self.observed_at)
        available = _time("available_at", self.available_at)
        expires = _time("expires_at", self.expires_at)
        if observed > available or available > expires:
            raise AnalysisV2ContractError("Invalid evidence time order.")
        if type(self.method) is not VersionReference:
            raise AnalysisV2ContractError("method must be a VersionReference.")
        _text("value", self.value)
        if self.unit is not None:
            _text("unit", self.unit)
        _text("interpretation", self.interpretation)
        if type(self.quality_status) is not DataQualityStatus:
            raise AnalysisV2ContractError("quality_status must be a DataQualityStatus.")
        if (
            type(self.reliability) is not Decimal
            or not self.reliability.is_finite()
            or not Decimal("0") <= self.reliability <= Decimal("1")
        ):
            raise AnalysisV2ContractError("reliability must be a finite score between 0 and 1.")
        if type(self.limitations) is not tuple:
            raise AnalysisV2ContractError("limitations must be a tuple.")
        for item in self.limitations:
            _text("limitation", item)
        provenance = _typed_tuple(
            "provenance", self.provenance, VersionReference, empty=False
        )
        _unique("provenance", provenance)
        if type(self.usable) is not bool:
            raise AnalysisV2ContractError("usable must be a bool.")
        if self.usable and self.quality_status not in {
            DataQualityStatus.VALID,
            DataQualityStatus.DEGRADED,
        }:
            raise AnalysisV2ContractError("Unusable quality cannot be marked usable.")
        object.__setattr__(self, "observed_at", observed)
        object.__setattr__(self, "available_at", available)
        object.__setattr__(self, "expires_at", expires)


@dataclass(frozen=True, slots=True)
class OrderFlowMetric:
    name: OrderFlowMetricName
    state: OrderFlowMetricState
    value: Decimal | None
    unit: str
    calculated_at: datetime
    window_start: datetime
    window_end: datetime
    method: VersionReference
    evidence_ids: tuple[UUID, ...]
    binding_ids: tuple[UUID, ...]
    limitations: tuple[str, ...] = ()
    unavailable_reason: str | None = None

    def __post_init__(self) -> None:
        if type(self.name) is not OrderFlowMetricName:
            raise AnalysisV2ContractError("name must be an OrderFlowMetricName.")
        if type(self.state) is not OrderFlowMetricState:
            raise AnalysisV2ContractError("state must be an OrderFlowMetricState.")
        _text("unit", self.unit)
        calculated = _time("calculated_at", self.calculated_at)
        start = _time("window_start", self.window_start)
        end = _time("window_end", self.window_end)
        if start > end:
            raise AnalysisV2ContractError("window_start must not be after window_end.")
        if self.value is not None and (
            type(self.value) is not Decimal or not self.value.is_finite()
        ):
            raise AnalysisV2ContractError("value must be a finite Decimal when present.")
        if self.state is OrderFlowMetricState.UNAVAILABLE:
            if self.value is not None or self.unavailable_reason is None:
                raise AnalysisV2ContractError(
                    "UNAVAILABLE metrics require no value and an explicit reason."
                )
            _text("unavailable_reason", self.unavailable_reason)
        elif self.value is None:
            raise AnalysisV2ContractError("Available/partial metrics require a value.")
        elif self.unavailable_reason is not None:
            raise AnalysisV2ContractError(
                "Available/partial metrics cannot carry an unavailable reason."
            )
        if self.state is OrderFlowMetricState.PARTIAL and not self.limitations:
            raise AnalysisV2ContractError("PARTIAL metrics require explicit limitations.")
        if type(self.limitations) is not tuple:
            raise AnalysisV2ContractError("limitations must be a tuple.")
        for limitation in self.limitations:
            _text("limitation", limitation)
        if type(self.method) is not VersionReference:
            raise AnalysisV2ContractError("method must be a VersionReference.")
        _uuid_tuple("evidence_ids", self.evidence_ids, empty=False)
        binding_ids = _uuid_tuple("binding_ids", self.binding_ids, empty=False)
        if len(binding_ids) != 1:
            raise AnalysisV2ContractError(
                "This schema permits only one modality binding per metric."
            )
        object.__setattr__(self, "calculated_at", calculated)
        object.__setattr__(self, "window_start", start)
        object.__setattr__(self, "window_end", end)


@dataclass(frozen=True, slots=True)
class OrderFlowAssessment:
    assessment_id: UUID
    asset: str
    instrument_id: str
    venue_id: str
    as_of: datetime
    expires_at: datetime
    state: OrderFlowAssessmentState
    metrics: tuple[OrderFlowMetric, ...]
    contract_id: str = field(default="C-104", init=False)
    schema_version: str = field(default="1", init=False)
    metric_contract_ids: ClassVar[frozenset[str]] = frozenset(
        metric.value for metric in OrderFlowMetricName
    )

    def __post_init__(self) -> None:
        _uuid("assessment_id", self.assessment_id)
        for name in ("asset", "instrument_id", "venue_id"):
            _text(name, getattr(self, name))
        as_of = _time("as_of", self.as_of)
        expires = _time("expires_at", self.expires_at)
        if as_of > expires:
            raise AnalysisV2ContractError("as_of must not be after expires_at.")
        if type(self.state) is not OrderFlowAssessmentState:
            raise AnalysisV2ContractError("state must be an OrderFlowAssessmentState.")
        metrics = _typed_tuple("metrics", self.metrics, OrderFlowMetric, empty=False)
        _unique("order-flow metric names", tuple(item.name for item in metrics))
        all_available = all(item.state is OrderFlowMetricState.AVAILABLE for item in metrics)
        all_unavailable = all(item.state is OrderFlowMetricState.UNAVAILABLE for item in metrics)
        expected = (
            OrderFlowAssessmentState.AVAILABLE
            if all_available
            else OrderFlowAssessmentState.UNAVAILABLE
            if all_unavailable
            else OrderFlowAssessmentState.PARTIAL
        )
        if self.state is not expected:
            raise AnalysisV2ContractError("Assessment state does not match metric states.")
        object.__setattr__(self, "as_of", as_of)
        object.__setattr__(self, "expires_at", expires)


VersionedAssessment: TypeAlias = Assessment | OrderFlowAssessment


@dataclass(frozen=True, slots=True)
class AnalysisSnapshotReference:
    snapshot_id: UUID
    schema_version: str
    content_sha256: str

    def __post_init__(self) -> None:
        _uuid("snapshot_id", self.snapshot_id)
        if _text("schema_version", self.schema_version) != ANALYSIS_V2_SCHEMA_VERSION:
            raise AnalysisV2ContractError("C-006 v2 must reference C-007 schema 2.")
        if _SHA256.fullmatch(_text("content_sha256", self.content_sha256)) is None:
            raise AnalysisV2ContractError("content_sha256 must be a lowercase SHA-256 digest.")


@dataclass(frozen=True, slots=True)
class MarketContextV2:
    context_id: UUID
    asset: str
    instrument_id: str
    as_of: datetime
    expires_at: datetime
    multi_timeframe_state: tuple[str, ...]
    regime: MarketRegime
    assessments: tuple[VersionedAssessment, ...]
    confluence: ConfluenceAssessment
    conflicts: tuple[ConflictAssessment, ...]
    adversarial: AdversarialAssessment
    uncertainties: tuple[AnalyticalUncertainty, ...]
    evidence_ids: tuple[UUID, ...]
    analysis_snapshot: AnalysisSnapshotReference
    contract_id: str = field(default="C-006", init=False)
    schema_version: str = field(default=ANALYSIS_V2_SCHEMA_VERSION, init=False)

    def __post_init__(self) -> None:
        _uuid("context_id", self.context_id)
        _text("asset", self.asset)
        _text("instrument_id", self.instrument_id)
        as_of = _time("as_of", self.as_of)
        expires = _time("expires_at", self.expires_at)
        if as_of > expires:
            raise AnalysisV2ContractError("as_of must not be after expires_at.")
        if type(self.multi_timeframe_state) is not tuple or not self.multi_timeframe_state:
            raise AnalysisV2ContractError("multi_timeframe_state must not be empty.")
        for item in self.multi_timeframe_state:
            _text("multi_timeframe_state item", item)
        if type(self.regime) is not MarketRegime:
            raise AnalysisV2ContractError("regime must be a MarketRegime.")
        assessments = self.assessments
        if type(assessments) is not tuple or not assessments or any(
            type(item) not in {
                *get_args(Assessment),
                OrderFlowAssessment,
            }
            for item in assessments
        ):
            raise AnalysisV2ContractError("assessments contains an invalid type.")
        _unique(
            "assessment identities",
            tuple((item.contract_id, str(item.assessment_id)) for item in assessments),
        )
        if type(self.confluence) is not ConfluenceAssessment:
            raise AnalysisV2ContractError("confluence has an invalid type.")
        if type(self.conflicts) is not tuple or any(
            type(item) is not ConflictAssessment for item in self.conflicts
        ):
            raise AnalysisV2ContractError("conflicts contains an invalid type.")
        if type(self.adversarial) is not AdversarialAssessment:
            raise AnalysisV2ContractError("adversarial has an invalid type.")
        if type(self.uncertainties) is not tuple or not self.uncertainties or any(
            type(item) is not AnalyticalUncertainty for item in self.uncertainties
        ):
            raise AnalysisV2ContractError("uncertainties contains an invalid type.")
        _uuid_tuple("evidence_ids", self.evidence_ids, empty=False)
        if type(self.analysis_snapshot) is not AnalysisSnapshotReference:
            raise AnalysisV2ContractError("analysis_snapshot has an invalid type.")
        object.__setattr__(self, "as_of", as_of)
        object.__setattr__(self, "expires_at", expires)


def _dimension_passes(
    report: DataQualityReportV2,
    policy: SpotQualityPolicy,
    required: tuple[DataQualityDimension, ...],
) -> bool:
    dimensions = {item.dimension: item for item in report.dimensions}
    if policy.expected_record_count is None:
        return False
    expected = policy.expected_record_count
    for dimension in required:
        result = dimensions[dimension]
        if result.state is not DataQualityDimensionState.MEASURED:
            return False
        if result.numerator is None or result.denominator is None:
            return False
        expected_denominator = (
            expected * len(policy.metric_rules)
            if dimension is DataQualityDimension.COMPLETENESS
            else policy.expected_transition_count
            if dimension is DataQualityDimension.CONTINUITY
            else expected
        )
        expected_unit = {
            DataQualityDimension.COMPLETENESS: "metric_cells",
            DataQualityDimension.FRESHNESS: "observations",
            DataQualityDimension.ACCURACY: "observations",
            DataQualityDimension.CONSISTENCY: "observations",
            DataQualityDimension.SOURCE_RELIABILITY: "source_records",
            DataQualityDimension.COVERAGE: "observations",
            DataQualityDimension.CONTINUITY: "sequence_transitions",
        }[dimension]
        if (
            expected_denominator is None
            or result.denominator != expected_denominator
            or result.numerator != result.denominator
            or result.score != Decimal("1")
            or result.basis_unit != expected_unit
        ):
            return False
    return True


@dataclass(frozen=True, slots=True)
class ResolvedInputBinding:
    binding: InputBindingV2
    snapshot: MarketSnapshot
    report: DataQualityReportV2
    policy: SpotQualityPolicy
    observations: tuple[MarketData, ...]
    sources: tuple[DataSourceRecord, ...]
    dataset: DatasetVersion | None
    dependency_expires_at: datetime
    direct_inputs_pass: bool


def resolve_analysis_snapshot_v2(
    manifest: AnalysisSnapshotV2,
    *,
    snapshots: Mapping[UUID, MarketSnapshot],
    reports: Mapping[UUID, DataQualityReportV2],
    observations: Mapping[UUID, MarketData],
    sources: Mapping[UUID, DataSourceRecord],
    datasets: Mapping[tuple[str, str], DatasetVersion] | None = None,
) -> tuple[ResolvedInputBinding, ...]:
    if type(manifest) is not AnalysisSnapshotV2:
        raise AnalysisV2ContractError("Expected an exact AnalysisSnapshotV2.")
    resolved: list[ResolvedInputBinding] = []
    for binding in manifest.bindings:
        try:
            snapshot_id = UUID(binding.market_snapshot.record_id)
            report_id = UUID(binding.data_quality_report.record_id)
            snapshot = snapshots[snapshot_id]
            report = reports[report_id]
        except (ValueError, KeyError, TypeError) as exc:
            raise AnalysisV2ContractError("Missing exact C-002 or C-003 dependency.") from exc
        if (
            type(snapshot) is not MarketSnapshot
            or type(report) is not DataQualityReportV2
            or snapshot.snapshot_id != snapshot_id
            or report.report_id != report_id
            or binding.market_snapshot.content_sha256 != canonical_sha256(snapshot)
            or binding.data_quality_report.content_sha256 != canonical_sha256(report)
            or binding.snapshot_as_of != snapshot.as_of
            or binding.instrument_id != snapshot.instrument_id
            or binding.venue_id != snapshot.venue_id
            or report.snapshot_id != snapshot.snapshot_id
            or report.required_data_cutoff != snapshot.as_of
            or report.assessment_policy_id != binding.assessment_policy.policy_id
            or report.assessment_policy_version != binding.assessment_policy.version
            or snapshot.instrument_id != manifest.instrument_id
            or snapshot.venue_id != manifest.venue_id
        ):
            raise AnalysisV2ContractError("C-002/C-003 identity, digest, policy, or cutoff mismatch.")
        try:
            policy = SpotQualityPolicy.resolve_reference(
                report.assessment_policy_id, report.assessment_policy_version
            )
        except (DataQualityAssessmentError, ValueError, TypeError) as exc:
            raise AnalysisV2ContractError("Unknown C-003 assessment policy/version.") from exc
        expected_kind = {
            InputModality.SPOT_TRADES: ProviderDataKind.TRADE,
            InputModality.SPOT_TICKS: ProviderDataKind.TICK,
            InputModality.ORDER_BOOK: ProviderDataKind.ORDER_BOOK,
        }[binding.modality]
        if (
            policy.data_kind is not expected_kind
            or policy.instrument_id != snapshot.instrument_id
            or policy.venue_id != snapshot.venue_id
            or policy.required_data_cutoff != snapshot.as_of
            or policy.assessment_policy_id != report.assessment_policy_id
            or policy.resolved_policy_version != report.assessment_policy_version
        ):
            raise AnalysisV2ContractError("C-003 policy scope does not match its binding.")
        if snapshot.dataset_version is None:
            if binding.dataset_version is not None:
                raise AnalysisV2ContractError("Unexpected C-092 reference.")
            dataset = None
        else:
            dataset_ref = binding.dataset_version
            if dataset_ref is None or datasets is None:
                raise AnalysisV2ContractError("Required exact C-092 dataset is unresolved.")
            try:
                dataset = datasets[(snapshot.dataset_version.dataset_id, snapshot.dataset_version.version)]
            except KeyError as exc:
                raise AnalysisV2ContractError("Missing exact C-092 dataset.") from exc
            if (
                type(dataset) is not DatasetVersion
                or dataset_ref.contract_id != "C-092"
                or dataset_ref.record_id != dataset.dataset_id
                or dataset_ref.lineage_version != dataset.version
                or dataset_ref.content_sha256 != canonical_sha256(dataset)
                or snapshot.dataset_version.dataset_id != dataset.dataset_id
                or snapshot.dataset_version.version != dataset.version
                or dataset.source_record_ids != snapshot.source_record_ids
                or dataset.point_in_time_cutoff > snapshot.as_of
            ):
                raise AnalysisV2ContractError("C-092 identity, digest, or membership mismatch.")
        observation_values: list[MarketData] = []
        source_values: list[DataSourceRecord] = []
        direct_inputs_pass = True
        for ref in binding.observations:
            try:
                observation = observations[UUID(ref.observation.record_id)]
                source = sources[UUID(ref.source.record_id)]
            except (ValueError, KeyError, TypeError) as exc:
                raise AnalysisV2ContractError("Missing exact C-001/C-091 dependency.") from exc
            if (
                type(observation) is not MarketData
                or type(source) is not DataSourceRecord
                or observation.market_data_id != UUID(ref.observation.record_id)
                or source.source_record_id != UUID(ref.source.record_id)
                or ref.observation.content_sha256 != canonical_sha256(observation)
                or ref.source.content_sha256 != canonical_sha256(source)
                or ref.source.record_id != str(observation.source_record_id)
                or source.source_record_id != observation.source_record_id
                or observation.instrument_id != snapshot.instrument_id
                or observation.venue_id != snapshot.venue_id
                or observation.observation_type != expected_kind.value
                or any(
                    time > snapshot.as_of
                    for time in (
                        observation.event_time,
                        observation.provider_time,
                        observation.ingestion_time,
                        observation.availability_time,
                        source.provider_event_time,
                        source.retrieval_time,
                        source.availability_time,
                    )
                )
                or source.provider_event_time != observation.provider_time
                or source.retrieval_time > observation.ingestion_time
                or source.availability_time > observation.availability_time
            ):
                raise AnalysisV2ContractError("C-001/C-091 provenance or cutoff mismatch.")
            metrics = {metric.metric_name: metric for metric in observation.metrics}
            if any(
                (metric := metrics.get(rule.name)) is None
                or type(metric) is not MetricValue
                or metric.unit != rule.unit
                or not rule.minimum <= metric.value <= rule.maximum
                for rule in policy.metric_rules
            ):
                direct_inputs_pass = False
            observation_values.append(observation)
            source_values.append(source)
        if (
            tuple(item.market_data_id for item in observation_values)
            != snapshot.market_data_ids
            or tuple(item.source_record_id for item in source_values)
            != snapshot.source_record_ids
            or tuple(item.record_id for item in binding.source_records)
            != tuple(str(item.source_record_id) for item in source_values)
            or tuple(item.content_sha256 for item in binding.source_records)
            != tuple(canonical_sha256(item) for item in source_values)
            or tuple(item.source_record_id for item in observation_values)
            != tuple(item.source_record_id for item in source_values)
        ):
            raise AnalysisV2ContractError("C-002 exact C-001/C-091 membership mismatch.")
        if report.assessed_at > manifest.created_at or snapshot.created_at > manifest.created_at:
            raise AnalysisV2ContractError("Input report or snapshot postdates manifest creation.")
        quality_refs = {
            ("C-002", str(snapshot.snapshot_id), snapshot.schema_version, canonical_sha256(snapshot)),
            *(
                ("C-001", str(item.market_data_id), item.schema_version, canonical_sha256(item))
                for item in observation_values
            ),
            *(
                ("C-091", str(item.source_record_id), item.schema_version, canonical_sha256(item))
                for item in source_values
            ),
        }
        if dataset is not None:
            quality_refs.add(
                ("C-092", dataset.dataset_id, dataset.version, canonical_sha256(dataset))
            )
        for dimension in report.dimensions:
            ref = dimension.evidence_reference
            if ref is not None and (
                ref.contract_id,
                ref.record_id,
                ref.version,
                ref.evidence_sha256,
            ) not in quality_refs:
                raise AnalysisV2ContractError("C-003 quality evidence is outside exact input closure.")
        freshness = policy.freshness_seconds
        if any(
            not timedelta(0) <= snapshot.as_of - item.event_time <= timedelta(seconds=freshness)
            for item in observation_values
        ):
            direct_inputs_pass = False
        dependency_expiry = snapshot.as_of + timedelta(seconds=freshness)
        resolved.append(
            ResolvedInputBinding(
                binding,
                snapshot,
                report,
                policy,
                tuple(observation_values),
                tuple(source_values),
                dataset,
                dependency_expiry,
                direct_inputs_pass,
            )
        )
    if any(manifest.expires_at > item.dependency_expires_at for item in resolved):
        raise AnalysisV2ContractError("Manifest expires after a bound input dependency.")
    return tuple(resolved)


def _required_dimensions(item: ResolvedInputBinding) -> tuple[DataQualityDimension, ...]:
    base = (
        DataQualityDimension.COMPLETENESS,
        DataQualityDimension.FRESHNESS,
        DataQualityDimension.ACCURACY,
        DataQualityDimension.CONSISTENCY,
        DataQualityDimension.SOURCE_RELIABILITY,
        DataQualityDimension.COVERAGE,
    )
    if item.binding.modality is InputModality.ORDER_BOOK and item.policy.assessment_policy_id.startswith(
        "spot-order-book-point"
    ):
        return base
    return (*base, DataQualityDimension.CONTINUITY)


def _quality_eligible(item: ResolvedInputBinding) -> bool:
    report = item.report
    if report.status not in {DataQualityStatus.VALID, DataQualityStatus.DEGRADED}:
        return False
    if (
        item.policy.require_independent_comparison
        or item.policy.require_checksum
        or not item.direct_inputs_pass
        or item.policy.expected_record_count != len(item.observations)
    ):
        return False
    dimensions = {value.dimension: value for value in report.dimensions}
    if (
        item.binding.modality is InputModality.ORDER_BOOK
        and item.policy.assessment_policy_id.startswith("spot-order-book-point")
    ):
        continuity = dimensions[DataQualityDimension.CONTINUITY]
        if (
            continuity.state is not DataQualityDimensionState.NOT_APPLICABLE
            or
            continuity.reason_code
            is not DataQualityDimensionReasonCode.SINGLE_POINT_SNAPSHOT
            or continuity.not_applicable_policy
            != AssessmentPolicyReference(
                report.assessment_policy_id, report.assessment_policy_version
            )
            or item.policy.expected_record_count != 1
            or len(item.observations) != 1
        ):
            return False
    return _dimension_passes(report, item.policy, _required_dimensions(item))


def validate_evidence_item_v2(
    evidence: EvidenceItemV2,
    manifest: AnalysisSnapshotV2,
    *,
    resolved_bindings: tuple[ResolvedInputBinding, ...],
) -> None:
    if type(evidence) is not EvidenceItemV2 or type(manifest) is not AnalysisSnapshotV2:
        raise AnalysisV2ContractError("Invalid C-008 v2 evidence or C-007 manifest.")
    by_id = {item.binding.binding_id: item for item in resolved_bindings}
    selected = []
    for binding_id in evidence.binding_ids:
        item = by_id.get(binding_id)
        if item is None:
            raise AnalysisV2ContractError("Evidence references an unknown manifest binding.")
        selected.append(item)
    if evidence.expires_at > min(
        manifest.expires_at, *(item.dependency_expires_at for item in selected)
    ):
        raise AnalysisV2ContractError("Evidence expires after one of its input dependencies.")
    selected_observations = {
        observation.market_data_id: observation
        for item in selected
        for observation in item.observations
    }
    if not set(evidence.observation_ids).issubset(selected_observations):
        raise AnalysisV2ContractError("Evidence observation is outside its selected binding(s).")
    sources_by_observation = {
        observation.market_data_id: observation.source_record_id
        for item in selected
        for observation in item.observations
    }
    if set(evidence.source_record_ids) != {
        sources_by_observation[observation_id] for observation_id in evidence.observation_ids
    }:
        raise AnalysisV2ContractError("Evidence C-001/C-091 source closure is incomplete.")
    selected_datasets = {
        (item.dataset.dataset_id, item.dataset.version)
        for item in selected
        if item.dataset is not None
    }
    if set(evidence.dataset_versions) - selected_datasets:
        raise AnalysisV2ContractError("Evidence references an unbound dataset version.")
    if evidence.observed_at > min(item.binding.analysis_cutoff for item in selected):
        raise AnalysisV2ContractError("Evidence contains a future observation.")
    if evidence.available_at > manifest.created_at:
        raise AnalysisV2ContractError("Evidence was not available when the manifest was created.")
    if evidence.usable and any(
        item.report.status is DataQualityStatus.DEGRADED for item in selected
    ):
        required_limitations = {
            text
            for item in selected
            for text in (
                *item.report.missing_fields,
                *item.report.invalid_record_ids,
                *item.report.duplicate_record_ids,
                *item.report.anomalies,
                *item.report.source_conflicts,
            )
        }
        if not required_limitations.issubset(set(evidence.limitations)):
            raise AnalysisV2ContractError("DEGRADED report findings must remain limitations.")


def validate_order_flow_assessment(
    assessment: OrderFlowAssessment,
    manifest: AnalysisSnapshotV2,
    *,
    resolved_bindings: tuple[ResolvedInputBinding, ...],
    evidence: Mapping[UUID, EvidenceItemV2],
) -> None:
    if type(assessment) is not OrderFlowAssessment:
        raise AnalysisV2ContractError("Expected an exact C-104 OrderFlowAssessment.")
    if (
        assessment.asset != manifest.asset
        or assessment.instrument_id != manifest.instrument_id
        or assessment.venue_id != manifest.venue_id
        or assessment.as_of != manifest.analysis_cutoff
        or assessment.expires_at > manifest.expires_at
    ):
        raise AnalysisV2ContractError("C-104 assessment does not match its C-007 manifest.")
    by_binding = {item.binding.binding_id: item for item in resolved_bindings}
    for metric in assessment.metrics:
        binding_id = metric.binding_ids[0]
        item = by_binding.get(binding_id)
        if item is None:
            raise AnalysisV2ContractError("Metric references an unknown C-007 binding.")
        book_metric = metric.name in {
            OrderFlowMetricName.SPREAD,
            OrderFlowMetricName.DISPLAYED_DEPTH,
            OrderFlowMetricName.BOOK_IMBALANCE,
        }
        if (book_metric and item.binding.modality is not InputModality.ORDER_BOOK) or (
            not book_metric and item.binding.modality is not InputModality.SPOT_TRADES
        ):
            raise AnalysisV2ContractError("Metric cannot use an incompatible modality.")
        if not item.snapshot.as_of <= metric.calculated_at <= manifest.analysis_cutoff:
            raise AnalysisV2ContractError(
                "Metric calculation must follow its input cutoff and precede the analysis cutoff."
            )
        if book_metric:
            if (
                metric.window_start != item.snapshot.as_of
                or metric.window_end != item.snapshot.as_of
                or len(item.observations) != 1
            ):
                raise AnalysisV2ContractError("Book metrics require one exact point snapshot.")
        elif (
            metric.window_end != item.snapshot.as_of
            or metric.window_start >= metric.window_end
            or metric.window_start
            != min(observation.event_time for observation in item.observations)
            or any(
                observation.event_time < metric.window_start
                or observation.event_time > metric.window_end
                for observation in item.observations
            )
        ):
            raise AnalysisV2ContractError("Trade metric window does not match its bound snapshot.")
        selected_evidence: list[EvidenceItemV2] = []
        for evidence_id in metric.evidence_ids:
            item_evidence = evidence.get(evidence_id)
            if item_evidence is None or evidence_id not in manifest.evidence_ids:
                raise AnalysisV2ContractError("Metric references unresolved C-008 evidence.")
            validate_evidence_item_v2(
                item_evidence, manifest, resolved_bindings=resolved_bindings
            )
            if item_evidence.binding_ids != (binding_id,):
                raise AnalysisV2ContractError("Metric evidence must bind only its used input.")
            selected_evidence.append(item_evidence)
        evidence_observation_ids = {
            observation_id
            for item_evidence in selected_evidence
            for observation_id in item_evidence.observation_ids
        }
        if evidence_observation_ids != {
            observation.market_data_id for observation in item.observations
        }:
            raise AnalysisV2ContractError(
                "Metric evidence must close over every C-001 input in its window."
            )
        if not _quality_eligible(item):
            if metric.state is not OrderFlowMetricState.UNAVAILABLE:
                raise AnalysisV2ContractError(
                    "A failed required C-003 dimension makes this metric unavailable."
                )
        if metric.state is OrderFlowMetricState.UNAVAILABLE:
            continue
        if any(not value.usable for value in selected_evidence):
            raise AnalysisV2ContractError("Available metrics require usable evidence.")
        if (
            item.report.status is DataQualityStatus.DEGRADED
            and not set(
                (
                    *item.report.missing_fields,
                    *item.report.invalid_record_ids,
                    *item.report.duplicate_record_ids,
                    *item.report.anomalies,
                    *item.report.source_conflicts,
                )
            ).issubset(set(metric.limitations))
        ):
            raise AnalysisV2ContractError("DEGRADED report findings must remain limitations.")
        if metric.name in {
            OrderFlowMetricName.VOLUME_DELTA,
            OrderFlowMetricName.CUMULATIVE_DELTA,
        } and any(
            finding.startswith("unknown-aggressor:")
            for finding in item.report.anomalies
        ):
            raise AnalysisV2ContractError(
                "Unknown aggressor side makes full-window signed flow unavailable."
            )


def validate_market_context_v2(
    context: MarketContextV2,
    manifest: AnalysisSnapshotV2,
    *,
    resolved_bindings: tuple[ResolvedInputBinding, ...],
    evidence: Mapping[UUID, EvidenceItemV2],
) -> None:
    if type(context) is not MarketContextV2 or type(manifest) is not AnalysisSnapshotV2:
        raise AnalysisV2ContractError("Expected exact C-006/C-007 schema-2 contracts.")
    if (
        context.analysis_snapshot.snapshot_id != manifest.snapshot_id
        or context.analysis_snapshot.content_sha256 != manifest.content_sha256
        or context.analysis_snapshot.schema_version != manifest.schema_version
        or context.asset != manifest.asset
        or context.instrument_id != manifest.instrument_id
        or context.as_of != manifest.analysis_cutoff
        or context.expires_at > manifest.expires_at
        or context.evidence_ids != manifest.evidence_ids
        or tuple(str(item.assessment_id) for item in context.assessments)
        != tuple(str(item) for item in manifest.assessment_ids)
    ):
        raise AnalysisV2ContractError("C-006 v2 does not resolve to the exact C-007 manifest.")
    if set(evidence) != set(manifest.evidence_ids):
        raise AnalysisV2ContractError("C-008 evidence membership is not exactly resolved.")
    for item in evidence.values():
        validate_evidence_item_v2(
            item, manifest, resolved_bindings=resolved_bindings
        )
    by_id = {item.binding.binding_id: item for item in resolved_bindings}
    for metric_assessment in (
        item for item in context.assessments if type(item) is OrderFlowAssessment
    ):
        validate_order_flow_assessment(
            metric_assessment,
            manifest,
            resolved_bindings=resolved_bindings,
            evidence=evidence,
        )
    for binding in manifest.bindings:
        if binding.binding_id not in by_id:
            raise AnalysisV2ContractError("Manifest binding was not fully resolved.")
    context_assessments = (
        context.regime,
        *context.assessments,
        context.confluence,
        *context.conflicts,
        context.adversarial,
        *context.uncertainties,
    )
    for assessment in context_assessments:
        assessment_as_of = _time("assessment.as_of", assessment.as_of)
        assessment_expiry = _time("assessment.expires_at", assessment.expires_at)
        if assessment_as_of > manifest.analysis_cutoff or assessment_expiry > manifest.expires_at:
            raise AnalysisV2ContractError("Assessment time exceeds its manifest bounds.")


__all__ = [
    "ANALYSIS_V2_SCHEMA_VERSION",
    "AnalysisRecordReference",
    "AnalysisSnapshotReference",
    "AnalysisSnapshotV2",
    "AnalysisV2ContractError",
    "EvidenceItemV2",
    "InputBindingV2",
    "InputModality",
    "MarketContextV2",
    "ObservationSourceBinding",
    "OrderFlowAssessment",
    "OrderFlowAssessmentState",
    "OrderFlowMetric",
    "OrderFlowMetricName",
    "OrderFlowMetricState",
    "ResolvedInputBinding",
    "VersionedAssessment",
    "analysis_snapshot_v2_sha256",
    "create_analysis_snapshot_v2",
    "resolve_analysis_snapshot_v2",
    "validate_evidence_item_v2",
    "validate_market_context_v2",
    "validate_order_flow_assessment",
]
