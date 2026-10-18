"""Versioned, non-probabilistic C-009/C-010 analysis contracts."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from uuid import UUID

from trading_platform_api.analysis.contracts import (
    AnalysisContractError,
    AnalyticalDirection,
    EvidenceRelation,
    ResolutionStatus,
    VersionReference,
    _text,
    _time,
    _typed_tuple,
    _unique,
    _uuid,
    _uuid_tuple,
    _window,
)


class EvidenceStrengthLevel(StrEnum):
    VERY_STRONG = "VERY_STRONG"
    STRONG = "STRONG"
    MODERATE = "MODERATE"
    WEAK = "WEAK"
    UNKNOWN = "UNKNOWN"


class EvidenceDependenceV2(StrEnum):
    INDEPENDENT = "INDEPENDENT"
    PARTIALLY_DEPENDENT = "PARTIALLY_DEPENDENT"
    HIGHLY_CORRELATED = "HIGHLY_CORRELATED"
    UNKNOWN = "UNKNOWN"


class ConfluenceStateV2(StrEnum):
    ALIGNED = "ALIGNED"
    PARTIALLY_ALIGNED = "PARTIALLY_ALIGNED"
    CONFLICTING = "CONFLICTING"
    STRONGLY_CONFLICTING = "STRONGLY_CONFLICTING"
    INDETERMINATE = "INDETERMINATE"


class ConfluenceStatusV2(StrEnum):
    AVAILABLE = "AVAILABLE"
    PARTIAL = "PARTIAL"
    UNAVAILABLE = "UNAVAILABLE"


class ConfluenceReasonV2(StrEnum):
    MISSING_EVIDENCE = "MISSING_EVIDENCE"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
    QUALITY_NOT_VALID = "QUALITY_NOT_VALID"
    STALE_INPUT = "STALE_INPUT"
    INDEPENDENCE_UNAVAILABLE = "INDEPENDENCE_UNAVAILABLE"
    DETERMINISTIC_CALCULATION_FAILED = "DETERMINISTIC_CALCULATION_FAILED"


class ConfidenceStatusV2(StrEnum):
    AVAILABLE = "AVAILABLE"
    UNAVAILABLE = "UNAVAILABLE"


class ConflictSeverityV2(StrEnum):
    LOW = "LOW"
    MODERATE = "MODERATE"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class AgentIndependenceReferenceV2:
    report_id: UUID
    report_version: str
    schema_version: str
    lineage_version: str
    content_sha256: str
    contract_id: str = field(default="C-093", init=False)

    def __post_init__(self) -> None:
        _uuid("report_id", self.report_id)
        for name in ("report_version", "schema_version", "lineage_version"):
            _text(name, getattr(self, name))
        if self.schema_version != "1":
            raise AnalysisContractError("C-093 reference schema must be 1.")
        digest = _text("content_sha256", self.content_sha256)
        if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
            raise AnalysisContractError("content_sha256 must be lowercase SHA-256.")


def _require_enum(name: str, value: object, expected: type[StrEnum]) -> None:
    if type(value) is not expected:
        raise AnalysisContractError(f"{name} has an invalid enum value.")


def _require_decimal_score(name: str, value: object) -> None:
    if type(value) is not Decimal or not value.is_finite() or not 0 <= value <= 1:
        raise AnalysisContractError(f"{name} must be a finite Decimal in [0, 1].")


@dataclass(frozen=True, slots=True)
class AnalyticalConfidenceV2:
    status: ConfidenceStatusV2
    value: Decimal | None
    method: VersionReference | None
    reason_code: str | None

    def __post_init__(self) -> None:
        _require_enum("confidence status", self.status, ConfidenceStatusV2)
        if self.status is ConfidenceStatusV2.AVAILABLE:
            if self.value is None or type(self.method) is not VersionReference:
                raise AnalysisContractError(
                    "Available analytical confidence requires a value and method."
                )
            _require_decimal_score("analytical confidence", self.value)
            if self.reason_code is not None:
                raise AnalysisContractError(
                    "Available analytical confidence cannot have a reason code."
                )
        elif (
            self.value is not None
            or self.method is not None
            or not isinstance(self.reason_code, str)
            or not self.reason_code.strip()
        ):
            raise AnalysisContractError(
                "Unavailable analytical confidence requires only a reason code."
            )


@dataclass(frozen=True, slots=True)
class ConfluenceComponentV2:
    domain: str
    direction: AnalyticalDirection
    relation: EvidenceRelation
    evidence_strength: EvidenceStrengthLevel
    dependence: EvidenceDependenceV2
    evidence_ids: tuple[UUID, ...]
    method: VersionReference

    def __post_init__(self) -> None:
        _text("domain", self.domain)
        _require_enum("direction", self.direction, AnalyticalDirection)
        _require_enum("relation", self.relation, EvidenceRelation)
        _require_enum(
            "evidence strength", self.evidence_strength, EvidenceStrengthLevel
        )
        _require_enum("dependence", self.dependence, EvidenceDependenceV2)
        _uuid_tuple("evidence_ids", self.evidence_ids, empty=False)
        if type(self.method) is not VersionReference:
            raise AnalysisContractError("component method must be versioned.")


@dataclass(frozen=True, slots=True)
class ConfluenceAssessmentV2:
    assessment_id: UUID
    instrument_id: str
    timeframe: str
    snapshot_id: UUID
    quality_report_id: UUID
    as_of: datetime
    expires_at: datetime
    status: ConfluenceStatusV2
    reason_code: ConfluenceReasonV2 | None
    state: ConfluenceStateV2
    components: tuple[ConfluenceComponentV2, ...]
    analytical_confidence: AnalyticalConfidenceV2
    evidence_strength: EvidenceStrengthLevel
    independence_report: AgentIndependenceReferenceV2
    evidence_ids: tuple[UUID, ...]
    provenance: tuple[VersionReference, ...]
    explanation: str
    contract_id: str = field(default="C-009", init=False)
    schema_version: str = field(default="2", init=False)

    def __post_init__(self) -> None:
        _uuid("assessment_id", self.assessment_id)
        _text("instrument_id", self.instrument_id)
        _text("timeframe", self.timeframe)
        _uuid("snapshot_id", self.snapshot_id)
        _uuid("quality_report_id", self.quality_report_id)
        as_of = _time("as_of", self.as_of)
        expires = _time("expires_at", self.expires_at)
        _window("as_of", as_of, "expires_at", expires)
        _require_enum("status", self.status, ConfluenceStatusV2)
        if self.reason_code is not None:
            _require_enum("reason_code", self.reason_code, ConfluenceReasonV2)
        _require_enum("state", self.state, ConfluenceStateV2)
        components = _typed_tuple("components", self.components, ConfluenceComponentV2)
        _unique("confluence domains", tuple(item.domain for item in components))
        if type(self.analytical_confidence) is not AnalyticalConfidenceV2:
            raise AnalysisContractError("analytical_confidence has an invalid type.")
        _require_enum(
            "evidence strength", self.evidence_strength, EvidenceStrengthLevel
        )
        if type(self.independence_report) is not AgentIndependenceReferenceV2:
            raise AnalysisContractError("independence_report has an invalid type.")
        evidence_ids = _uuid_tuple("evidence_ids", self.evidence_ids)
        component_evidence = {
            evidence_id for item in components for evidence_id in item.evidence_ids
        }
        if not component_evidence.issubset(set(evidence_ids)):
            raise AnalysisContractError(
                "component evidence must be included in assessment evidence_ids."
            )
        provenance = _typed_tuple(
            "provenance", self.provenance, VersionReference, empty=False
        )
        _unique("provenance", provenance)
        _text("explanation", self.explanation)
        if self.status is ConfluenceStatusV2.UNAVAILABLE:
            if (
                self.reason_code is None
                or components
                or evidence_ids
                or self.state is not ConfluenceStateV2.INDETERMINATE
                or self.evidence_strength is not EvidenceStrengthLevel.UNKNOWN
                or self.analytical_confidence.status
                is not ConfidenceStatusV2.UNAVAILABLE
            ):
                raise AnalysisContractError(
                    "Unavailable confluence must be indeterminate with no evidence or score."
                )
        elif self.status is ConfluenceStatusV2.PARTIAL:
            if (
                self.reason_code is None
                or not components
                or not evidence_ids
                or self.state is not ConfluenceStateV2.INDETERMINATE
            ):
                raise AnalysisContractError(
                    "Partial confluence requires evidence and an indeterminate state."
                )
        elif self.reason_code is not None or (
            not components
            or not evidence_ids
            or self.state is ConfluenceStateV2.INDETERMINATE
        ):
            raise AnalysisContractError(
                "Available confluence requires evidence and a determinate state."
            )
        object.__setattr__(self, "as_of", as_of)
        object.__setattr__(self, "expires_at", expires)


@dataclass(frozen=True, slots=True)
class ConflictAssessmentV2:
    assessment_id: UUID
    instrument_id: str
    timeframe: str
    snapshot_id: UUID
    quality_report_id: UUID
    as_of: datetime
    expires_at: datetime
    finding_ids: tuple[UUID, ...]
    evidence_ids: tuple[UUID, ...]
    severity: ConflictSeverityV2
    severity_method: VersionReference
    explanation: str
    resolution_status: ResolutionStatus
    provenance: tuple[VersionReference, ...]
    contract_id: str = field(default="C-010", init=False)
    schema_version: str = field(default="2", init=False)

    def __post_init__(self) -> None:
        _uuid("assessment_id", self.assessment_id)
        _text("instrument_id", self.instrument_id)
        _text("timeframe", self.timeframe)
        _uuid("snapshot_id", self.snapshot_id)
        _uuid("quality_report_id", self.quality_report_id)
        as_of = _time("as_of", self.as_of)
        expires = _time("expires_at", self.expires_at)
        _window("as_of", as_of, "expires_at", expires)
        _uuid_tuple("finding_ids", self.finding_ids, empty=False)
        _uuid_tuple("evidence_ids", self.evidence_ids, empty=False)
        _require_enum("severity", self.severity, ConflictSeverityV2)
        if type(self.severity_method) is not VersionReference:
            raise AnalysisContractError("severity_method must be versioned.")
        _text("explanation", self.explanation)
        _require_enum("resolution_status", self.resolution_status, ResolutionStatus)
        provenance = _typed_tuple(
            "provenance", self.provenance, VersionReference, empty=False
        )
        _unique("provenance", provenance)
        object.__setattr__(self, "as_of", as_of)
        object.__setattr__(self, "expires_at", expires)


__all__ = [
    "AgentIndependenceReferenceV2",
    "AnalyticalConfidenceV2",
    "ConfidenceStatusV2",
    "ConflictAssessmentV2",
    "ConflictSeverityV2",
    "ConfluenceAssessmentV2",
    "ConfluenceComponentV2",
    "ConfluenceStateV2",
    "ConfluenceReasonV2",
    "ConfluenceStatusV2",
    "EvidenceDependenceV2",
    "EvidenceStrengthLevel",
]
