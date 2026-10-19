"""Deterministic, provenance-bound Spot confluence and conflict assessment.

This module only evaluates explicitly typed analytical findings. It does not
infer direction from prose or raw indicator strings, estimate probabilities,
or grant strategy, risk, approval, or execution authority.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Mapping
from uuid import UUID, uuid5

from trading_platform_api.analysis.contracts import (
    AnalyticalDirection,
    EvidenceRelation,
    MarketRegime,
    ResolutionStatus,
    VersionReference,
    _text,
    _text_tuple,
    _time,
    _typed_tuple,
    _unique,
    _uuid,
    _uuid_tuple,
)
from trading_platform_api.analysis.versioned_contracts import (
    AnalysisV2ContractError,
    AnalyticalConfidenceReasonV2,
    AnalyticalConfidenceStateV2,
    AnalyticalConfidenceV2,
    ConflictEvidenceStateV2,
    ConflictMaterialityV2,
    ConflictReasonV2,
    ConflictSeverityV2,
    ConfluenceEvidenceStrengthV2,
    ConfluenceReasonV2,
    ConfluenceStateV2,
    ConfluenceStatusV2,
    EvidenceDependenceV2,
    EvidenceItemV2,
)
from trading_platform_api.analysis.versioned_contracts_v4 import (
    C007_V4_SCHEMA_VERSION,
    AnalysisOutputReferenceV4,
    AnalysisSnapshotV4,
    ConflictAssessmentV3,
    ConfluenceAssessmentV3,
    ConfluenceComponentV2,
    ResolvedSpotOHLCVBindingV4,
    validate_evidence_item_v2_for_v4,
)
from trading_platform_api.contracts.serialization import canonical_sha256
from trading_platform_api.market_data.contracts import (
    DataQualityReportV2,
    DataQualityStatus,
    MarketSnapshot,
)

C093_SCHEMA_VERSION = "1"
C093_LINEAGE_VERSION = "1"
C093_METHOD = VersionReference("agent-independence", "c093-deterministic-v1")
C007_V4_LINEAGE_VERSION = "4"
SPOT_CONFLUENCE_METHOD = VersionReference("spot-confluence", "spot-confluence-v1")
SPOT_CONFLICT_METHOD = VersionReference("spot-conflict", "spot-conflict-v1")
_IDENTITY_NAMESPACE = UUID("9d640cf4-becb-5c55-9327-4bfa4b302160")
SUPPORTED_SPOT_FINDING_DOMAINS = frozenset(
    {
        "spot-market-regime",
        "spot-technical-indicator",
        "spot-trend",
        "spot-momentum",
        "spot-volatility",
        "spot-volume",
        "spot-vwap",
        "spot-volume-profile",
        "spot-market-structure",
        "spot-price-action",
        "spot-fibonacci",
        "spot-smc",
        "spot-wyckoff",
    }
)


class FindingReadiness(StrEnum):
    READY = "READY"
    PARTIAL = "PARTIAL"
    WARMUP = "WARMUP"
    UNAVAILABLE = "UNAVAILABLE"
    INVALID = "INVALID"
    STALE = "STALE"


class MetaAnalysisReason(StrEnum):
    MISSING_EVIDENCE = "MISSING_EVIDENCE"
    PARTIAL_EVIDENCE = "PARTIAL_EVIDENCE"
    INSUFFICIENT_WARMUP = "INSUFFICIENT_WARMUP"
    INPUT_UNAVAILABLE = "INPUT_UNAVAILABLE"
    INVALID_EVIDENCE = "INVALID_EVIDENCE"
    STALE_EVIDENCE = "STALE_EVIDENCE"
    DIRECTION_UNESTABLISHED = "DIRECTION_UNESTABLISHED"
    DEPENDENCE_UNESTABLISHED = "DEPENDENCE_UNESTABLISHED"
    MATERIALITY_UNESTABLISHED = "MATERIALITY_UNESTABLISHED"


class DependenceFactor(StrEnum):
    SHARED_BINDING = "SHARED_BINDING"
    SHARED_SOURCE = "SHARED_SOURCE"
    SHARED_OBSERVATION = "SHARED_OBSERVATION"
    OVERLAPPING_WINDOW = "OVERLAPPING_WINDOW"
    SHARED_METHOD = "SHARED_METHOD"
    SHARED_AGENT = "SHARED_AGENT"
    SHARED_MODEL = "SHARED_MODEL"
    SHARED_PROMPT = "SHARED_PROMPT"


@dataclass(frozen=True, slots=True)
class SpotMetaFinding:
    """Typed upstream finding; direction/materiality are never parsed from prose."""

    finding_id: UUID
    domain: str
    direction: AnalyticalDirection
    relation: EvidenceRelation
    evidence_strength: ConfluenceEvidenceStrengthV2
    readiness: FindingReadiness
    evidence_ids: tuple[UUID, ...]
    input_binding_ids: tuple[UUID, ...]
    method: VersionReference | None
    materiality: ConflictMaterialityV2 = ConflictMaterialityV2.UNKNOWN
    required_premise_invalid: bool | None = None
    unsafe_to_rely: bool | None = None
    agent_id: str | None = None
    model: VersionReference | None = None
    prompt: VersionReference | None = None

    def __post_init__(self) -> None:
        _uuid("finding_id", self.finding_id)
        _text("domain", self.domain)
        if self.domain not in SUPPORTED_SPOT_FINDING_DOMAINS:
            raise AnalysisV2ContractError(
                "finding domain is outside the approved Spot profile."
            )
        if type(self.direction) is not AnalyticalDirection:
            raise AnalysisV2ContractError("finding direction has an invalid type.")
        if type(self.relation) is not EvidenceRelation:
            raise AnalysisV2ContractError("finding relation has an invalid type.")
        if type(self.evidence_strength) is not ConfluenceEvidenceStrengthV2:
            raise AnalysisV2ContractError(
                "finding evidence strength has an invalid type."
            )
        if type(self.readiness) is not FindingReadiness:
            raise AnalysisV2ContractError("finding readiness has an invalid type.")
        if type(self.materiality) is not ConflictMaterialityV2:
            raise AnalysisV2ContractError("finding materiality has an invalid type.")
        evidence_ids = _uuid_tuple("evidence_ids", self.evidence_ids)
        binding_ids = _uuid_tuple("input_binding_ids", self.input_binding_ids)
        _unique("finding evidence IDs", evidence_ids)
        _unique("finding binding IDs", binding_ids)
        if self.readiness is FindingReadiness.READY and (
            not evidence_ids or not binding_ids or self.method is None
        ):
            raise AnalysisV2ContractError(
                "Ready findings require evidence, bindings, and a method."
            )
        if self.method is not None and type(self.method) is not VersionReference:
            raise AnalysisV2ContractError("finding method has an invalid type.")
        if self.model is not None and type(self.model) is not VersionReference:
            raise AnalysisV2ContractError("finding model has an invalid type.")
        if self.prompt is not None and type(self.prompt) is not VersionReference:
            raise AnalysisV2ContractError("finding prompt has an invalid type.")
        if self.agent_id is not None:
            _text("agent_id", self.agent_id)
        for name, value in (
            ("required_premise_invalid", self.required_premise_invalid),
            ("unsafe_to_rely", self.unsafe_to_rely),
        ):
            if value is not None and type(value) is not bool:
                raise AnalysisV2ContractError(f"{name} must be bool or None.")


@dataclass(frozen=True, slots=True)
class IndependenceParticipant:
    finding_id: UUID
    domain: str
    readiness: FindingReadiness
    evidence_ids: tuple[UUID, ...]
    input_binding_ids: tuple[UUID, ...]
    observation_ids: tuple[UUID, ...]
    source_record_ids: tuple[UUID, ...]
    timeframe: str
    window_start: datetime
    window_end: datetime
    method: VersionReference | None
    agent_id: str | None
    model: VersionReference | None
    prompt: VersionReference | None

    def __post_init__(self) -> None:
        _uuid("finding_id", self.finding_id)
        _text("domain", self.domain)
        if type(self.readiness) is not FindingReadiness:
            raise AnalysisV2ContractError("participant readiness has an invalid type.")
        evidence_ids = _uuid_tuple("evidence_ids", self.evidence_ids)
        binding_ids = _uuid_tuple("input_binding_ids", self.input_binding_ids)
        _unique("participant evidence IDs", evidence_ids)
        _unique("participant binding IDs", binding_ids)
        _uuid_tuple("observation_ids", self.observation_ids)
        _uuid_tuple("source_record_ids", self.source_record_ids)
        _text("timeframe", self.timeframe)
        start = _time("window_start", self.window_start)
        end = _time("window_end", self.window_end)
        if start >= end:
            raise AnalysisV2ContractError("participant window is invalid.")
        if self.method is not None and type(self.method) is not VersionReference:
            raise AnalysisV2ContractError("participant method has an invalid type.")
        if self.model is not None and type(self.model) is not VersionReference:
            raise AnalysisV2ContractError("participant model has an invalid type.")
        if self.prompt is not None and type(self.prompt) is not VersionReference:
            raise AnalysisV2ContractError("participant prompt has an invalid type.")
        if self.agent_id is not None:
            _text("agent_id", self.agent_id)
        if self.readiness is FindingReadiness.READY and (
            not evidence_ids or not binding_ids or self.method is None
        ):
            raise AnalysisV2ContractError(
                "Ready C-093 participants require exact evidence, binding, and method references."
            )
        object.__setattr__(self, "window_start", start)
        object.__setattr__(self, "window_end", end)


@dataclass(frozen=True, slots=True)
class IndependenceComparison:
    left_finding_id: UUID
    right_finding_id: UUID
    factors: tuple[DependenceFactor, ...]
    dependence: EvidenceDependenceV2
    statistical_independence_established: bool = False

    def __post_init__(self) -> None:
        _uuid("left_finding_id", self.left_finding_id)
        _uuid("right_finding_id", self.right_finding_id)
        if self.left_finding_id == self.right_finding_id:
            raise AnalysisV2ContractError("independence comparison must be pairwise.")
        factors = _typed_tuple("factors", self.factors, DependenceFactor)
        if tuple(sorted(factors, key=lambda item: item.value)) != factors:
            raise AnalysisV2ContractError("dependence factors must be ordered.")
        _unique("dependence factors", factors)
        if type(self.dependence) is not EvidenceDependenceV2:
            raise AnalysisV2ContractError("dependence has an invalid type.")
        if self.statistical_independence_established is not False:
            raise AnalysisV2ContractError(
                "The Spot profile has no statistical independence evidence."
            )
        if not factors and self.dependence is not EvidenceDependenceV2.UNKNOWN:
            raise AnalysisV2ContractError("No observed overlap requires UNKNOWN.")
        if self.dependence in {
            EvidenceDependenceV2.INDEPENDENT,
            EvidenceDependenceV2.HIGHLY_CORRELATED,
        }:
            raise AnalysisV2ContractError(
                "C-093 v1 cannot establish statistical independence or correlation."
            )


@dataclass(frozen=True, slots=True)
class AgentIndependenceReport:
    report_id: UUID
    snapshot_id: UUID
    snapshot_schema_version: str
    snapshot_lineage_version: str
    snapshot_sha256: str
    manifest_id: UUID
    manifest_schema_version: str
    manifest_lineage_version: str
    binding_sha256: str
    binding_id: UUID
    regime_id: UUID
    regime_sha256: str
    quality_report_id: UUID
    quality_report_schema_version: str
    quality_report_lineage_version: str
    quality_report_sha256: str
    instrument_id: str
    timeframe: str
    window_start: datetime
    window_end: datetime
    as_of: datetime
    expires_at: datetime
    participants: tuple[IndependenceParticipant, ...]
    comparisons: tuple[IndependenceComparison, ...]
    overall_dependence: EvidenceDependenceV2
    statistical_independence_established: bool
    limitations: tuple[str, ...]
    method: VersionReference
    contract_id: str = field(default="C-093", init=False)
    schema_version: str = field(default=C093_SCHEMA_VERSION, init=False)
    lineage_version: str = field(default=C093_LINEAGE_VERSION, init=False)

    def __post_init__(self) -> None:
        _uuid("report_id", self.report_id)
        _uuid("snapshot_id", self.snapshot_id)
        _uuid("manifest_id", self.manifest_id)
        _uuid("binding_id", self.binding_id)
        _uuid("regime_id", self.regime_id)
        _uuid("quality_report_id", self.quality_report_id)
        if (
            _text("snapshot_schema_version", self.snapshot_schema_version),
            _text("snapshot_lineage_version", self.snapshot_lineage_version),
        ) != ("1", "1"):
            raise AnalysisV2ContractError("C-093 v1 requires C-002 schema/lineage 1/1.")
        if (
            _text("manifest_schema_version", self.manifest_schema_version),
            _text("manifest_lineage_version", self.manifest_lineage_version),
        ) != (C007_V4_SCHEMA_VERSION, C007_V4_LINEAGE_VERSION):
            raise AnalysisV2ContractError("C-093 v1 requires C-007 schema/lineage 4/4.")
        if (
            _text("quality_report_schema_version", self.quality_report_schema_version),
            _text(
                "quality_report_lineage_version", self.quality_report_lineage_version
            ),
        ) != ("2", "2"):
            raise AnalysisV2ContractError("C-093 v1 requires C-003 schema/lineage 2/2.")
        for name in (
            "snapshot_sha256",
            "binding_sha256",
            "regime_sha256",
            "quality_report_sha256",
        ):
            value = getattr(self, name)
            if len(value) != 64 or any(
                char not in "0123456789abcdef" for char in value
            ):
                raise AnalysisV2ContractError(f"{name} must be lowercase SHA-256.")
        _text("instrument_id", self.instrument_id)
        _text("timeframe", self.timeframe)
        start = _time("window_start", self.window_start)
        end = _time("window_end", self.window_end)
        as_of = _time("as_of", self.as_of)
        expires = _time("expires_at", self.expires_at)
        if not start < end or as_of > expires:
            raise AnalysisV2ContractError("C-093 time scope is invalid.")
        participants = _typed_tuple(
            "participants", self.participants, IndependenceParticipant, empty=False
        )
        _unique(
            "participant identities", tuple(item.finding_id for item in participants)
        )
        comparisons = _typed_tuple(
            "comparisons", self.comparisons, IndependenceComparison
        )
        _unique(
            "pairwise comparisons",
            tuple(
                (item.left_finding_id, item.right_finding_id) for item in comparisons
            ),
        )
        participant_ids = {item.finding_id for item in participants}
        if any(
            item.left_finding_id not in participant_ids
            or item.right_finding_id not in participant_ids
            for item in comparisons
        ):
            raise AnalysisV2ContractError("comparison refers to a missing participant.")
        if type(self.overall_dependence) is not EvidenceDependenceV2:
            raise AnalysisV2ContractError("overall_dependence has an invalid type.")
        if self.overall_dependence in {
            EvidenceDependenceV2.INDEPENDENT,
            EvidenceDependenceV2.HIGHLY_CORRELATED,
        }:
            raise AnalysisV2ContractError(
                "C-093 v1 cannot establish statistical independence or correlation."
            )
        if self.statistical_independence_established is not False:
            raise AnalysisV2ContractError(
                "C-093 v1 does not claim statistical independence."
            )
        if self.method != C093_METHOD:
            raise AnalysisV2ContractError(
                "C-093 report method is not owner-registered."
            )
        limitations = _text_tuple("limitations", self.limitations, empty=False)
        if not limitations:
            raise AnalysisV2ContractError("C-093 requires explicit limitations.")
        _unique("C-093 limitations", limitations)
        if (
            tuple(sorted(participants, key=lambda item: str(item.finding_id)))
            != participants
        ):
            raise AnalysisV2ContractError(
                "C-093 participants must be canonically ordered."
            )
        expected_pairs = tuple(
            (participants[left].finding_id, participants[right].finding_id)
            for left in range(len(participants))
            for right in range(left + 1, len(participants))
        )
        actual_pairs = tuple(
            (item.left_finding_id, item.right_finding_id) for item in comparisons
        )
        if actual_pairs != expected_pairs:
            raise AnalysisV2ContractError(
                "C-093 must contain every pair exactly once in order."
            )
        if any(
            item.timeframe != self.timeframe
            or item.window_start != start
            or item.window_end != end
            or (
                (item.evidence_ids or item.readiness is FindingReadiness.READY)
                and self.binding_id not in item.input_binding_ids
            )
            for item in participants
        ):
            raise AnalysisV2ContractError(
                "C-093 participant scope differs from report scope."
            )
        expected_dependence = (
            EvidenceDependenceV2.PARTIALLY_DEPENDENT
            if any(
                item.dependence is EvidenceDependenceV2.PARTIALLY_DEPENDENT
                for item in comparisons
            )
            else EvidenceDependenceV2.UNKNOWN
        )
        if self.overall_dependence is not expected_dependence:
            raise AnalysisV2ContractError(
                "C-093 overall dependence does not match pairwise findings."
            )
        object.__setattr__(self, "window_start", start)
        object.__setattr__(self, "window_end", end)
        object.__setattr__(self, "as_of", as_of)
        object.__setattr__(self, "expires_at", expires)
        object.__setattr__(self, "limitations", limitations)


class C093Registry:
    """Authoritative owner registry for the first C-093 implementation."""

    contract_id = "C-093"
    schema_version = C093_SCHEMA_VERSION
    lineage_version = C093_LINEAGE_VERSION
    method = C093_METHOD

    @classmethod
    def reference(cls, report: AgentIndependenceReport) -> AnalysisOutputReferenceV4:
        if type(report) is not AgentIndependenceReport:
            raise AnalysisV2ContractError(
                "C-093 registry accepts its canonical report only."
            )
        if (report.schema_version, report.lineage_version) != (
            cls.schema_version,
            cls.lineage_version,
        ):
            raise AnalysisV2ContractError("C-093 reference is not owner-registered.")
        if report.method != cls.method:
            raise AnalysisV2ContractError(
                "C-093 report method is not owner-registered."
            )
        return AnalysisOutputReferenceV4(
            cls.contract_id,
            report.report_id,
            cls.schema_version,
            cls.lineage_version,
            canonical_sha256(report),
            cls.method,
        )

    @classmethod
    def resolve(
        cls,
        reference: AnalysisOutputReferenceV4,
        reports: Mapping[UUID, AgentIndependenceReport],
    ) -> AgentIndependenceReport:
        if (
            type(reference) is not AnalysisOutputReferenceV4
            or reference.contract_id != cls.contract_id
            or (reference.schema_version, reference.lineage_version)
            != (cls.schema_version, cls.lineage_version)
            or reference.method != cls.method
        ):
            raise AnalysisV2ContractError(
                "C-093 reference is unsupported by its registry."
            )
        report = reports.get(reference.record_id)
        if (
            type(report) is not AgentIndependenceReport
            or report.report_id != reference.record_id
            or canonical_sha256(report) != reference.content_sha256
        ):
            raise AnalysisV2ContractError("C-093 report identity or digest mismatch.")
        return report


class ConfluenceCalculationState(StrEnum):
    AVAILABLE = "AVAILABLE"
    INDETERMINATE = "INDETERMINATE"


@dataclass(frozen=True, slots=True)
class ConfluenceCalculationResult:
    state: ConfluenceCalculationState
    reason: MetaAnalysisReason | None
    assessment: ConfluenceAssessmentV3

    def __post_init__(self) -> None:
        if type(self.state) is not ConfluenceCalculationState:
            raise AnalysisV2ContractError("confluence calculation state is invalid.")
        if type(self.assessment) is not ConfluenceAssessmentV3:
            raise AnalysisV2ContractError(
                "confluence calculation assessment is invalid."
            )
        if self.state is ConfluenceCalculationState.AVAILABLE:
            if (
                self.reason is not None
                or self.assessment.status is not ConfluenceStatusV2.AVAILABLE
            ):
                raise AnalysisV2ContractError(
                    "available confluence must be determinate."
                )
        elif (
            self.reason is None
            or self.assessment.status is not ConfluenceStatusV2.INDETERMINATE
        ):
            raise AnalysisV2ContractError("indeterminate confluence requires a reason.")


class ConflictCalculationState(StrEnum):
    ASSESSED = "ASSESSED"
    NO_CONFLICT = "NO_CONFLICT"
    NOT_ASSESSED = "NOT_ASSESSED"


@dataclass(frozen=True, slots=True)
class ConflictCalculationResult:
    state: ConflictCalculationState
    reason: MetaAnalysisReason | None
    assessments: tuple[ConflictAssessmentV3, ...]

    def __post_init__(self) -> None:
        if type(self.state) is not ConflictCalculationState:
            raise AnalysisV2ContractError("conflict calculation state is invalid.")
        assessments = _typed_tuple(
            "conflict assessments", self.assessments, ConflictAssessmentV3
        )
        if self.state is ConflictCalculationState.ASSESSED:
            if self.reason is not None or not assessments:
                raise AnalysisV2ContractError(
                    "assessed conflicts require records and no reason."
                )
        elif self.state is ConflictCalculationState.NO_CONFLICT:
            if self.reason is not None or assessments:
                raise AnalysisV2ContractError(
                    "no-conflict result cannot include records or a reason."
                )
        elif self.reason is None or assessments:
            raise AnalysisV2ContractError(
                "unassessed conflicts require a reason and no records."
            )


def _readiness_reason(
    findings: tuple[SpotMetaFinding, ...],
) -> MetaAnalysisReason | None:
    if not findings:
        return MetaAnalysisReason.MISSING_EVIDENCE
    priority = (
        (FindingReadiness.STALE, MetaAnalysisReason.STALE_EVIDENCE),
        (FindingReadiness.INVALID, MetaAnalysisReason.INVALID_EVIDENCE),
        (FindingReadiness.UNAVAILABLE, MetaAnalysisReason.INPUT_UNAVAILABLE),
        (FindingReadiness.WARMUP, MetaAnalysisReason.INSUFFICIENT_WARMUP),
        (FindingReadiness.PARTIAL, MetaAnalysisReason.PARTIAL_EVIDENCE),
    )
    return next(
        (
            reason
            for state, reason in priority
            if any(item.readiness is state for item in findings)
        ),
        None,
    )


def _validate_scope(
    manifest: AnalysisSnapshotV4,
    resolved: tuple[ResolvedSpotOHLCVBindingV4, ...],
    evidence: Mapping[UUID, EvidenceItemV2],
    findings: tuple[SpotMetaFinding, ...],
    *,
    now: datetime,
) -> ResolvedSpotOHLCVBindingV4:
    if type(manifest) is not AnalysisSnapshotV4 or len(resolved) != 1:
        raise AnalysisV2ContractError(
            "Spot meta-analysis requires one resolved C-007 v4 binding."
        )
    if manifest.created_at > now or manifest.expires_at <= now:
        raise AnalysisV2ContractError(
            "C-007 v4 manifest is expired or not yet available."
        )
    binding = resolved[0]
    if type(binding) is not ResolvedSpotOHLCVBindingV4:
        raise AnalysisV2ContractError("Resolved Spot binding has an invalid type.")
    if (
        len(manifest.bindings) != 1
        or binding.binding != manifest.bindings[0]
        or not binding.direct_inputs_pass
        or type(binding.snapshot) is not MarketSnapshot
        or type(binding.report) is not DataQualityReportV2
        or type(binding.regime) is not MarketRegime
        or binding.report.status is not DataQualityStatus.VALID
        or binding.binding.market_snapshot.contract_id != "C-002"
        or binding.binding.market_snapshot.schema_version != "1"
        or binding.binding.market_snapshot.lineage_version != "1"
        or binding.binding.data_quality_report.lineage_version != "2"
        or binding.snapshot.snapshot_id
        != UUID(binding.binding.market_snapshot.record_id)
        or canonical_sha256(binding.snapshot)
        != binding.binding.market_snapshot.content_sha256
        or binding.report.report_id
        != UUID(binding.binding.data_quality_report.record_id)
        or canonical_sha256(binding.report)
        != binding.binding.data_quality_report.content_sha256
        or binding.report.snapshot_id != binding.snapshot.snapshot_id
        or binding.binding.data_quality_report.contract_id != "C-003"
        or binding.binding.data_quality_report.schema_version != "2"
        or binding.binding.timeframe != manifest.timeframe
        or binding.binding.instrument_id != manifest.instrument_id
        or binding.snapshot.venue_id != manifest.venue_id
        or binding.regime.regime_id != binding.binding.regime.record_id
        or canonical_sha256(binding.regime) != binding.binding.regime.content_sha256
        or binding.regime.expires_at <= now
        or binding.regime.expires_at > manifest.expires_at
        or set(binding.regime.evidence_ids)
        != {item.record_id for item in binding.binding.evidence}
        or manifest.expires_at > binding.dependency_expires_at
        or binding.binding.regime
        != next(
            (item for item in manifest.analysis_outputs if item.contract_id == "C-005"),
            None,
        )
    ):
        raise AnalysisV2ContractError(
            "Resolved Spot dependencies do not match C-007 v4."
        )
    manifest_evidence_ids = {item.record_id for item in binding.binding.evidence}
    if manifest_evidence_ids != {item.evidence_id for item in binding.evidence}:
        raise AnalysisV2ContractError(
            "Resolved C-008 membership differs from C-007 v4."
        )
    evidence_by_id = {item.evidence_id: item for item in binding.evidence}
    if any(
        evidence.get(item_id) != item
        or canonical_sha256(item)
        != next(
            ref.content_sha256
            for ref in binding.binding.evidence
            if ref.record_id == item_id
        )
        for item_id, item in evidence_by_id.items()
    ):
        raise AnalysisV2ContractError(
            "Resolved C-008 evidence identity or digest mismatch."
        )
    _unique("finding IDs", tuple(item.finding_id for item in findings))
    _unique("finding domains", tuple(item.domain for item in findings))
    resolved_ids = {item.evidence_id for item in binding.evidence}
    for finding in findings:
        if not set(finding.evidence_ids).issubset(resolved_ids):
            raise AnalysisV2ContractError("finding cites evidence outside C-007 v4.")
        if finding.input_binding_ids and finding.input_binding_ids != (
            binding.binding.binding_id,
        ):
            raise AnalysisV2ContractError(
                "finding is not bound to the exact Spot input."
            )
        if finding.readiness is FindingReadiness.READY and (
            not finding.evidence_ids
            or not finding.input_binding_ids
            or finding.method is None
        ):
            raise AnalysisV2ContractError(
                "Ready finding has incomplete exact provenance."
            )
        for evidence_id in finding.evidence_ids:
            item = evidence.get(evidence_id)
            if item is None:
                raise AnalysisV2ContractError(
                    "finding references missing C-008 evidence."
                )
            validate_evidence_item_v2_for_v4(
                item, manifest, resolved_bindings=resolved, now=now
            )
            if item.quality_status is not DataQualityStatus.VALID or not item.usable:
                raise AnalysisV2ContractError(
                    "finding evidence is not usable and valid."
                )
            if finding.method not in {item.method, *item.provenance}:
                raise AnalysisV2ContractError(
                    "finding method is absent from its evidence provenance."
                )
            if item.relation is not finding.relation:
                raise AnalysisV2ContractError(
                    "finding relation differs from its evidence relation."
                )
    if any(item.domain == "spot-market-regime" for item in findings):
        raise AnalysisV2ContractError(
            "The exact C-005 regime is supplied by the resolved binding."
        )
    return binding


def _participant(
    finding: SpotMetaFinding,
    evidence: Mapping[UUID, EvidenceItemV2],
    binding: ResolvedSpotOHLCVBindingV4,
) -> IndependenceParticipant:
    items = tuple(
        evidence[item_id] for item_id in finding.evidence_ids if item_id in evidence
    )
    return IndependenceParticipant(
        finding.finding_id,
        finding.domain,
        finding.readiness,
        finding.evidence_ids,
        finding.input_binding_ids,
        tuple(sorted({oid for item in items for oid in item.observation_ids}, key=str)),
        tuple(
            sorted({sid for item in items for sid in item.source_record_ids}, key=str)
        ),
        binding.binding.timeframe,
        binding.binding.window_start,
        binding.binding.window_end,
        finding.method,
        finding.agent_id,
        finding.model,
        finding.prompt,
    )


def _regime_finding(binding: ResolvedSpotOHLCVBindingV4) -> SpotMetaFinding:
    """Create a non-strength-bearing participant for the exact C-005 result."""
    return SpotMetaFinding(
        binding.regime.regime_id,
        "spot-market-regime",
        binding.regime.direction,
        EvidenceRelation.SUPPORTING,
        ConfluenceEvidenceStrengthV2.UNKNOWN,
        FindingReadiness.READY,
        tuple(sorted(binding.regime.evidence_ids, key=str)),
        (binding.binding.binding_id,),
        binding.binding.regime_method,
    )


def _ordered_provenance(
    findings: tuple[SpotMetaFinding, ...],
    method: VersionReference,
    binding: ResolvedSpotOHLCVBindingV4,
) -> tuple[VersionReference, ...]:
    values = {C093_METHOD, method}
    values.update((binding.binding.regime_method, binding.binding.regime_profile))
    values.update(item.method for item in findings if item.method is not None)
    return tuple(sorted(values, key=lambda item: (item.component, item.version)))


def _input_scope_fingerprint(
    manifest: AnalysisSnapshotV4, binding: ResolvedSpotOHLCVBindingV4
) -> str:
    """Hash immutable input identity without output references added later."""
    return canonical_sha256(
        (
            manifest.snapshot_id,
            manifest.schema_version,
            manifest.asset,
            manifest.instrument_id,
            manifest.venue_id,
            manifest.timeframe,
            manifest.analysis_cutoff,
            binding.binding,
            binding.snapshot,
            binding.report,
            binding.regime,
            binding.evidence,
        )
    )


def _pairwise(
    left: IndependenceParticipant, right: IndependenceParticipant
) -> IndependenceComparison:
    factors: set[DependenceFactor] = set()
    if set(left.input_binding_ids) & set(right.input_binding_ids):
        factors.add(DependenceFactor.SHARED_BINDING)
    if set(left.source_record_ids) & set(right.source_record_ids):
        factors.add(DependenceFactor.SHARED_SOURCE)
    if set(left.observation_ids) & set(right.observation_ids):
        factors.add(DependenceFactor.SHARED_OBSERVATION)
    if max(left.window_start, right.window_start) < min(
        left.window_end, right.window_end
    ):
        factors.add(DependenceFactor.OVERLAPPING_WINDOW)
    if left.method is not None and left.method == right.method:
        factors.add(DependenceFactor.SHARED_METHOD)
    if left.agent_id is not None and left.agent_id == right.agent_id:
        factors.add(DependenceFactor.SHARED_AGENT)
    if left.model is not None and left.model == right.model:
        factors.add(DependenceFactor.SHARED_MODEL)
    if left.prompt is not None and left.prompt == right.prompt:
        factors.add(DependenceFactor.SHARED_PROMPT)
    ordered = tuple(sorted(factors, key=lambda item: item.value))
    observed_shared_inputs = {
        DependenceFactor.SHARED_BINDING,
        DependenceFactor.SHARED_SOURCE,
        DependenceFactor.SHARED_OBSERVATION,
    }
    other_shared_context = {
        DependenceFactor.OVERLAPPING_WINDOW,
        DependenceFactor.SHARED_METHOD,
        DependenceFactor.SHARED_AGENT,
        DependenceFactor.SHARED_MODEL,
        DependenceFactor.SHARED_PROMPT,
    }
    dependence = (
        EvidenceDependenceV2.PARTIALLY_DEPENDENT
        if factors & observed_shared_inputs
        else EvidenceDependenceV2.PARTIALLY_DEPENDENT
        if factors & other_shared_context
        else EvidenceDependenceV2.UNKNOWN
    )
    return IndependenceComparison(
        left.finding_id, right.finding_id, ordered, dependence
    )


def assess_agent_independence(
    *,
    manifest: AnalysisSnapshotV4,
    resolved_bindings: tuple[ResolvedSpotOHLCVBindingV4, ...],
    evidence: Mapping[UUID, EvidenceItemV2],
    findings: tuple[SpotMetaFinding, ...],
    now: datetime,
) -> AgentIndependenceReport:
    at = _time("now", now)
    binding = _validate_scope(manifest, resolved_bindings, evidence, findings, now=at)
    regime_finding = _regime_finding(binding)
    if regime_finding.finding_id in {item.finding_id for item in findings}:
        raise AnalysisV2ContractError("C-005 regime identity collides with a finding.")
    ordered_findings = tuple(sorted(findings, key=lambda item: str(item.finding_id)))
    participants = tuple(
        sorted(
            (
                _participant(regime_finding, evidence, binding),
                *(_participant(item, evidence, binding) for item in ordered_findings),
            ),
            key=lambda item: str(item.finding_id),
        )
    )
    pairs = tuple(
        _pairwise(participants[left], participants[right])
        for left in range(len(participants))
        for right in range(left + 1, len(participants))
    )
    if not pairs:
        overall = EvidenceDependenceV2.UNKNOWN
    elif any(
        item.dependence is EvidenceDependenceV2.PARTIALLY_DEPENDENT for item in pairs
    ):
        overall = EvidenceDependenceV2.PARTIALLY_DEPENDENT
    else:
        overall = EvidenceDependenceV2.UNKNOWN
    report_id = uuid5(
        _IDENTITY_NAMESPACE,
        "c093-v1:"
        + canonical_sha256(
            (_input_scope_fingerprint(manifest, binding), ordered_findings)
        ),
    )
    return AgentIndependenceReport(
        report_id,
        binding.snapshot.snapshot_id,
        "1",
        "1",
        canonical_sha256(binding.snapshot),
        manifest.snapshot_id,
        manifest.schema_version,
        C007_V4_LINEAGE_VERSION,
        canonical_sha256(binding.binding),
        binding.binding.binding_id,
        binding.regime.regime_id,
        canonical_sha256(binding.regime),
        binding.report.report_id,
        "2",
        "2",
        canonical_sha256(binding.report),
        manifest.instrument_id,
        manifest.timeframe,
        binding.binding.window_start,
        binding.binding.window_end,
        manifest.analysis_cutoff,
        min(manifest.expires_at, binding.dependency_expires_at),
        participants,
        pairs,
        overall,
        False,
        (
            "Dependence labels describe observed shared inputs only; they are not statistical correlation estimates.",
            "Distinct labels, methods, agents, models, or prompts do not establish statistical independence.",
            "All findings in this Spot profile are bounded to one validated OHLCV snapshot.",
        ),
        C093_METHOD,
    )


def _component_dependence(
    finding_id: UUID, report: AgentIndependenceReport
) -> EvidenceDependenceV2:
    values = [
        item.dependence
        for item in report.comparisons
        if finding_id in {item.left_finding_id, item.right_finding_id}
    ]
    if EvidenceDependenceV2.HIGHLY_CORRELATED in values:
        return EvidenceDependenceV2.HIGHLY_CORRELATED
    if EvidenceDependenceV2.PARTIALLY_DEPENDENT in values:
        return EvidenceDependenceV2.PARTIALLY_DEPENDENT
    return EvidenceDependenceV2.UNKNOWN


def _state(findings: tuple[SpotMetaFinding, ...]) -> ConfluenceStateV2 | None:
    directions = {item.direction for item in findings}
    directional = directions & {
        AnalyticalDirection.BULLISH,
        AnalyticalDirection.BEARISH,
    }
    if (
        directions & {AnalyticalDirection.MIXED, AnalyticalDirection.UNKNOWN}
        or not directional
    ):
        return None
    if len(directional) == 2:
        return ConfluenceStateV2.CONFLICTING
    if AnalyticalDirection.NEUTRAL in directions:
        return ConfluenceStateV2.PARTIALLY_ALIGNED
    return ConfluenceStateV2.ALIGNED


def calculate_spot_confluence_v3(
    *,
    manifest: AnalysisSnapshotV4,
    resolved_bindings: tuple[ResolvedSpotOHLCVBindingV4, ...],
    evidence: Mapping[UUID, EvidenceItemV2],
    findings: tuple[SpotMetaFinding, ...],
    now: datetime,
) -> tuple[ConfluenceCalculationResult, AgentIndependenceReport]:
    at = _time("now", now)
    binding = _validate_scope(manifest, resolved_bindings, evidence, findings, now=at)
    report = assess_agent_independence(
        manifest=manifest,
        resolved_bindings=resolved_bindings,
        evidence=evidence,
        findings=findings,
        now=at,
    )
    ordered_findings = tuple(sorted(findings, key=lambda item: str(item.finding_id)))
    reason = _readiness_reason(ordered_findings)
    components: tuple[ConfluenceComponentV2, ...] = ()
    assessment_evidence_ids: tuple[UUID, ...] = ()
    status = ConfluenceStatusV2.INDETERMINATE
    status_reason = ConfluenceReasonV2.INSUFFICIENT_EVIDENCE
    strength = ConfluenceEvidenceStrengthV2.UNKNOWN
    state = ConfluenceStateV2.INDETERMINATE
    confidence = AnalyticalConfidenceV2(
        AnalyticalConfidenceStateV2.UNAVAILABLE,
        None,
        None,
        AnalyticalConfidenceReasonV2.NOT_ASSESSED,
    )
    if reason is None:
        if not ordered_findings:
            reason = MetaAnalysisReason.MISSING_EVIDENCE
        else:
            components = tuple(
                ConfluenceComponentV2(
                    item.finding_id,
                    item.domain,
                    item.direction,
                    item.relation,
                    item.evidence_strength,
                    _component_dependence(item.finding_id, report),
                    item.evidence_ids,
                    item.input_binding_ids,
                )
                for item in ordered_findings
            )
            assessment_evidence_ids = tuple(
                sorted(
                    {eid for item in ordered_findings for eid in item.evidence_ids}
                    | set(binding.regime.evidence_ids),
                    key=str,
                )
            )
            computed_state = _state((_regime_finding(binding), *ordered_findings))
            if computed_state is None:
                reason = MetaAnalysisReason.DIRECTION_UNESTABLISHED
            elif any(
                item.evidence_strength is ConfluenceEvidenceStrengthV2.UNKNOWN
                for item in ordered_findings
            ):
                reason = MetaAnalysisReason.INPUT_UNAVAILABLE
            else:
                # C-007 v4 is one OHLCV source. It can show directional
                # agreement, but cannot establish the independent streams
                # required for a valid Chat 5 confluence result.
                reason = MetaAnalysisReason.DEPENDENCE_UNESTABLISHED
    if reason is not None:
        status_reason = {
            MetaAnalysisReason.MISSING_EVIDENCE: ConfluenceReasonV2.MISSING_EVIDENCE,
            MetaAnalysisReason.PARTIAL_EVIDENCE: ConfluenceReasonV2.PARTIAL_EVIDENCE,
            MetaAnalysisReason.INSUFFICIENT_WARMUP: ConfluenceReasonV2.INSUFFICIENT_EVIDENCE,
            MetaAnalysisReason.INPUT_UNAVAILABLE: ConfluenceReasonV2.INSUFFICIENT_EVIDENCE,
            MetaAnalysisReason.INVALID_EVIDENCE: ConfluenceReasonV2.INVALID_EVIDENCE,
            MetaAnalysisReason.STALE_EVIDENCE: ConfluenceReasonV2.STALE_EVIDENCE,
            MetaAnalysisReason.DIRECTION_UNESTABLISHED: ConfluenceReasonV2.INSUFFICIENT_EVIDENCE,
            MetaAnalysisReason.DEPENDENCE_UNESTABLISHED: ConfluenceReasonV2.INSUFFICIENT_EVIDENCE,
            MetaAnalysisReason.MATERIALITY_UNESTABLISHED: ConfluenceReasonV2.INSUFFICIENT_EVIDENCE,
        }[reason]
    dqr = binding.binding.data_quality_report
    assessment_id = uuid5(
        _IDENTITY_NAMESPACE,
        "confluence-v3:"
        + canonical_sha256(
            (_input_scope_fingerprint(manifest, binding), ordered_findings)
        ),
    )
    assessment = ConfluenceAssessmentV3(
        assessment_id,
        manifest.asset,
        manifest.instrument_id,
        manifest.timeframe,
        manifest.analysis_cutoff,
        min(manifest.expires_at, binding.dependency_expires_at),
        state,
        status,
        status_reason,
        components,
        confidence,
        strength,
        C093Registry.reference(report),
        manifest.snapshot_id,
        C007_V4_SCHEMA_VERSION,
        (dqr,),
        assessment_evidence_ids,
        SPOT_CONFLUENCE_METHOD,
        _ordered_provenance(ordered_findings, SPOT_CONFLUENCE_METHOD, binding),
    )
    result_state = (
        ConfluenceCalculationState.AVAILABLE
        if status is ConfluenceStatusV2.AVAILABLE
        else ConfluenceCalculationState.INDETERMINATE
    )
    return ConfluenceCalculationResult(result_state, reason, assessment), report


def _conflict_severity(
    materiality: ConflictMaterialityV2,
    *,
    required_premise_invalid: bool | None,
    unsafe_to_rely: bool | None,
    direct_opposition: bool,
) -> ConflictSeverityV2:
    if required_premise_invalid is True or unsafe_to_rely is True:
        return ConflictSeverityV2.CRITICAL
    if materiality is ConflictMaterialityV2.UNKNOWN:
        return ConflictSeverityV2.UNKNOWN
    if materiality is ConflictMaterialityV2.MATERIAL:
        return (
            ConflictSeverityV2.HIGH
            if direct_opposition
            else ConflictSeverityV2.MODERATE
        )
    return ConflictSeverityV2.LOW


def calculate_spot_conflicts_v3(
    *,
    manifest: AnalysisSnapshotV4,
    resolved_bindings: tuple[ResolvedSpotOHLCVBindingV4, ...],
    evidence: Mapping[UUID, EvidenceItemV2],
    findings: tuple[SpotMetaFinding, ...],
    now: datetime,
) -> ConflictCalculationResult:
    at = _time("now", now)
    binding = _validate_scope(manifest, resolved_bindings, evidence, findings, now=at)
    ordered_findings = tuple(sorted(findings, key=lambda item: str(item.finding_id)))
    reason = _readiness_reason(ordered_findings)
    if reason is not None or not ordered_findings:
        return ConflictCalculationResult(
            ConflictCalculationState.NOT_ASSESSED,
            reason or MetaAnalysisReason.MISSING_EVIDENCE,
            (),
        )
    directions = {AnalyticalDirection.BULLISH, AnalyticalDirection.BEARISH}
    conflicts: list[ConflictAssessmentV3] = []
    comparable_findings = tuple(
        sorted(
            (_regime_finding(binding), *ordered_findings),
            key=lambda item: str(item.finding_id),
        )
    )
    for index, left in enumerate(comparable_findings):
        for right in comparable_findings[index + 1 :]:
            if {left.direction, right.direction} != directions:
                continue
            ids = tuple(
                sorted(set(left.evidence_ids) | set(right.evidence_ids), key=str)
            )
            if not ids or any(item not in evidence for item in ids):
                continue
            required_invalid_values = (
                left.required_premise_invalid,
                right.required_premise_invalid,
            )
            unsafe_values = (left.unsafe_to_rely, right.unsafe_to_rely)
            premise_invalid = (
                True
                if True in required_invalid_values
                else False
                if all(value is False for value in required_invalid_values)
                else None
            )
            unsafe = (
                True
                if True in unsafe_values
                else False
                if all(value is False for value in unsafe_values)
                else None
            )
            critical = premise_invalid is True or unsafe is True
            materiality = (
                ConflictMaterialityV2.UNKNOWN
                if ConflictMaterialityV2.UNKNOWN
                in {left.materiality, right.materiality}
                else ConflictMaterialityV2.MATERIAL
                if ConflictMaterialityV2.MATERIAL
                in {left.materiality, right.materiality}
                else ConflictMaterialityV2.LOCALIZED
            )
            assessment_id = uuid5(
                _IDENTITY_NAMESPACE,
                "conflict-v3:"
                + canonical_sha256(
                    (_input_scope_fingerprint(manifest, binding), left, right)
                ),
            )
            if not critical and (
                premise_invalid is None
                or unsafe is None
                or materiality is ConflictMaterialityV2.UNKNOWN
            ):
                severity = ConflictSeverityV2.UNKNOWN
                evidence_state = ConflictEvidenceStateV2.INSUFFICIENT
                premise_invalid = None
                unsafe = None
                direct_opposition = None
                status_reason = ConflictReasonV2.MATERIALITY_UNESTABLISHED
            else:
                severity = _conflict_severity(
                    materiality,
                    required_premise_invalid=premise_invalid,
                    unsafe_to_rely=unsafe,
                    direct_opposition=True,
                )
                evidence_state = ConflictEvidenceStateV2.VALID
                direct_opposition = True
                status_reason = None
            conflicts.append(
                ConflictAssessmentV3(
                    assessment_id,
                    manifest.asset,
                    manifest.instrument_id,
                    manifest.timeframe,
                    manifest.analysis_cutoff,
                    min(manifest.expires_at, binding.dependency_expires_at),
                    (left.finding_id, right.finding_id),
                    ids,
                    severity,
                    evidence_state,
                    materiality,
                    direct_opposition,
                    premise_invalid,
                    unsafe,
                    status_reason,
                    "Opposing directional findings share the exact validated Spot scope; severity is categorical and does not create a trading gate.",
                    ResolutionStatus.UNRESOLVED,
                    manifest.snapshot_id,
                    C007_V4_SCHEMA_VERSION,
                    (binding.binding.data_quality_report,),
                    SPOT_CONFLICT_METHOD,
                    _ordered_provenance((left, right), SPOT_CONFLICT_METHOD, binding),
                )
            )
    if not conflicts:
        return ConflictCalculationResult(ConflictCalculationState.NO_CONFLICT, None, ())
    return ConflictCalculationResult(
        ConflictCalculationState.ASSESSED, None, tuple(conflicts)
    )


__all__ = [
    "AgentIndependenceReport",
    "C093Registry",
    "C093_LINEAGE_VERSION",
    "C093_METHOD",
    "C093_SCHEMA_VERSION",
    "ConflictCalculationResult",
    "ConflictCalculationState",
    "ConfluenceCalculationResult",
    "ConfluenceCalculationState",
    "DependenceFactor",
    "FindingReadiness",
    "IndependenceComparison",
    "IndependenceParticipant",
    "MetaAnalysisReason",
    "SPOT_CONFLICT_METHOD",
    "SPOT_CONFLUENCE_METHOD",
    "SUPPORTED_SPOT_FINDING_DOMAINS",
    "SpotMetaFinding",
    "assess_agent_independence",
    "calculate_spot_conflicts_v3",
    "calculate_spot_confluence_v3",
]
