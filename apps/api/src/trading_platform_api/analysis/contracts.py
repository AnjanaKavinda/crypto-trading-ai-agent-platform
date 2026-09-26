from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from typing import ClassVar, TypeVar, cast
from uuid import UUID

from trading_platform_api.market_data import DataQualityStatus, DatasetVersionReference

__all__ = [
    "CONTRACT_SCHEMA_VERSION",
    "AdversarialAssessment",
    "AgentIndependenceReference",
    "AnalysisContractError",
    "AnalysisSnapshot",
    "AnalyticalDirection",
    "AnalyticalFinding",
    "AnalyticalUncertainty",
    "AssessmentStatus",
    "ClaimClassification",
    "ConflictAssessment",
    "ConfluenceAssessment",
    "ConfluenceComponent",
    "ConfluenceState",
    "DerivativesAssessment",
    "DomainObservation",
    "EventRiskAssessment",
    "EvidenceDependence",
    "EvidenceItem",
    "EvidenceRelation",
    "FibonacciAssessment",
    "FundamentalAssessment",
    "MarketContext",
    "MarketRegime",
    "MethodologyCategory",
    "OnChainAssessment",
    "RegimeDimension",
    "ResolutionStatus",
    "SMCAssessment",
    "SentimentAssessment",
    "TechnicalAssessment",
    "UncertaintyCategory",
    "VersionReference",
    "WyckoffAssessment",
]


CONTRACT_SCHEMA_VERSION = "1"
_SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")
_T = TypeVar("_T")


class AnalysisContractError(ValueError):
    """Raised when a canonical analysis contract is invalid."""


class MethodologyCategory(StrEnum):
    FUNDAMENTAL = "fundamental"
    TECHNICAL = "technical"
    ON_CHAIN = "on-chain"
    SENTIMENT = "sentiment"


class ClaimClassification(StrEnum):
    FACT = "fact"
    INFERENCE = "inference"
    ASSUMPTION = "assumption"
    UNCERTAINTY = "uncertainty"


class EvidenceRelation(StrEnum):
    SUPPORTING = "supporting"
    CONTRADICTING = "contradicting"
    NEUTRAL = "neutral"


class AssessmentStatus(StrEnum):
    AVAILABLE = "available"
    PARTIAL = "partial"
    UNAVAILABLE = "unavailable"
    INVALID = "invalid"


class AnalyticalDirection(StrEnum):
    BULLISH = "bullish-context"
    BEARISH = "bearish-context"
    NEUTRAL = "neutral-context"
    MIXED = "mixed-context"
    UNKNOWN = "unknown"


class ConfluenceState(StrEnum):
    ALIGNED = "aligned"
    PARTIALLY_ALIGNED = "partially-aligned"
    CONFLICTING = "conflicting"
    STRONGLY_CONFLICTING = "strongly-conflicting"


class EvidenceDependence(StrEnum):
    INDEPENDENT = "independent"
    PARTIALLY_DEPENDENT = "partially-dependent"
    HIGHLY_CORRELATED = "highly-correlated"


class ResolutionStatus(StrEnum):
    RESOLVED = "resolved"
    UNRESOLVED = "unresolved"
    UNKNOWN = "unknown"


class UncertaintyCategory(StrEnum):
    DATA = "data"
    METHOD = "method"
    MODEL = "model"
    REGIME = "regime"
    INTERPRETATION = "interpretation"
    UNKNOWN = "unknown"


def _text(name: str, value: object) -> str:
    if not isinstance(value, str):
        raise AnalysisContractError(f"{name} must be a string.")
    if not value.strip():
        raise AnalysisContractError(f"{name} must not be blank.")
    if value != value.strip():
        raise AnalysisContractError(f"{name} must not contain surrounding whitespace.")
    return value


def _optional_text(name: str, value: object) -> str | None:
    if value is None:
        return None
    return _text(name, value)


def _uuid(name: str, value: object) -> UUID:
    if not isinstance(value, UUID):
        raise AnalysisContractError(f"{name} must be a UUID.")
    return value


def _time(name: str, value: object) -> datetime:
    if not isinstance(value, datetime):
        raise AnalysisContractError(f"{name} must be a datetime.")
    if value.tzinfo is None or value.utcoffset() is None:
        raise AnalysisContractError(f"{name} must be timezone-aware.")
    return value.astimezone(UTC)


def _score(name: str, value: object) -> Decimal:
    if (
        not isinstance(value, Decimal)
        or isinstance(value, bool)
        or not value.is_finite()
    ):
        raise AnalysisContractError(f"{name} must be a finite Decimal.")
    if value < Decimal("0") or value > Decimal("1"):
        raise AnalysisContractError(f"{name} must be between 0 and 1.")
    return value


def _tuple(name: str, value: object, *, empty: bool = True) -> tuple[object, ...]:
    if not isinstance(value, tuple):
        raise AnalysisContractError(f"{name} must be a tuple.")
    if not empty and not value:
        raise AnalysisContractError(f"{name} must not be empty.")
    return value


def _typed_tuple(
    name: str, value: object, item_type: type[_T], *, empty: bool = True
) -> tuple[_T, ...]:
    values = _tuple(name, value, empty=empty)
    if not all(isinstance(item, item_type) for item in values):
        raise AnalysisContractError(f"{name} contains an invalid item type.")
    return cast(tuple[_T, ...], values)


def _unique(name: str, values: tuple[object, ...]) -> None:
    try:
        if len(set(values)) != len(values):
            raise AnalysisContractError(f"{name} must not contain duplicates.")
    except TypeError as exc:
        raise AnalysisContractError(f"{name} items must be hashable.") from exc


def _uuid_tuple(name: str, value: object, *, empty: bool = True) -> tuple[UUID, ...]:
    values = _tuple(name, value, empty=empty)
    result = tuple(_uuid(f"{name}[{index}]", item) for index, item in enumerate(values))
    _unique(name, result)
    return result


def _text_tuple(name: str, value: object, *, empty: bool = True) -> tuple[str, ...]:
    values = _tuple(name, value, empty=empty)
    result = tuple(_text(f"{name}[{index}]", item) for index, item in enumerate(values))
    _unique(name, result)
    return result


def _window(start_name: str, start: datetime, end_name: str, end: datetime) -> None:
    if start > end:
        raise AnalysisContractError(f"{start_name} must not be after {end_name}.")


@dataclass(frozen=True, slots=True)
class VersionReference:
    component: str
    version: str

    def __post_init__(self) -> None:
        _text("component", self.component)
        _text("version", self.version)


@dataclass(frozen=True, slots=True)
class AgentIndependenceReference:
    report_id: UUID
    report_version: str
    contract_id: str = field(default="C-093", init=False)

    def __post_init__(self) -> None:
        _uuid("report_id", self.report_id)
        _text("report_version", self.report_version)


@dataclass(frozen=True, slots=True)
class AnalyticalFinding:
    finding_id: UUID
    category: str
    classification: ClaimClassification
    statement: str
    evidence_ids: tuple[UUID, ...]
    method: VersionReference
    invalidation_condition: str
    limitations: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _uuid("finding_id", self.finding_id)
        _text("category", self.category)
        if not isinstance(self.classification, ClaimClassification):
            raise AnalysisContractError("classification must be a ClaimClassification.")
        _text("statement", self.statement)
        _uuid_tuple("evidence_ids", self.evidence_ids, empty=False)
        if not isinstance(self.method, VersionReference):
            raise AnalysisContractError("method must be a VersionReference.")
        _text("invalidation_condition", self.invalidation_condition)
        _text_tuple("limitations", self.limitations)


@dataclass(frozen=True, slots=True)
class DomainObservation:
    observation_type: str
    value: str
    unit: str | None
    timeframe: str
    calculation: VersionReference
    evidence_ids: tuple[UUID, ...]

    def __post_init__(self) -> None:
        _text("observation_type", self.observation_type)
        _text("value", self.value)
        _optional_text("unit", self.unit)
        _text("timeframe", self.timeframe)
        if not isinstance(self.calculation, VersionReference):
            raise AnalysisContractError("calculation must be a VersionReference.")
        _uuid_tuple("evidence_ids", self.evidence_ids, empty=False)


@dataclass(frozen=True, slots=True)
class EvidenceItem:
    evidence_id: UUID
    source_record_ids: tuple[UUID, ...]
    dataset_versions: tuple[DatasetVersionReference, ...]
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
    data_quality_report_id: UUID
    reliability: Decimal
    limitations: tuple[str, ...]
    provenance: tuple[VersionReference, ...]
    usable: bool
    contract_id: str = field(default="C-008", init=False)
    schema_version: str = field(default=CONTRACT_SCHEMA_VERSION, init=False)

    def __post_init__(self) -> None:
        _uuid("evidence_id", self.evidence_id)
        _uuid_tuple("source_record_ids", self.source_record_ids, empty=False)
        datasets = _typed_tuple(
            "dataset_versions", self.dataset_versions, DatasetVersionReference
        )
        _unique("dataset_versions", datasets)
        _text_tuple("feature_ids", self.feature_ids)
        if not isinstance(self.classification, ClaimClassification):
            raise AnalysisContractError("classification must be a ClaimClassification.")
        if not isinstance(self.relation, EvidenceRelation):
            raise AnalysisContractError("relation must be an EvidenceRelation.")
        observed = _time("observed_at", self.observed_at)
        available = _time("available_at", self.available_at)
        expires = _time("expires_at", self.expires_at)
        _window("observed_at", observed, "available_at", available)
        _window("available_at", available, "expires_at", expires)
        if not isinstance(self.method, VersionReference):
            raise AnalysisContractError("method must be a VersionReference.")
        _text("value", self.value)
        _optional_text("unit", self.unit)
        _text("interpretation", self.interpretation)
        if not isinstance(self.quality_status, DataQualityStatus):
            raise AnalysisContractError("quality_status must be a DataQualityStatus.")
        _uuid("data_quality_report_id", self.data_quality_report_id)
        _score("reliability", self.reliability)
        _text_tuple("limitations", self.limitations)
        provenance = _typed_tuple(
            "provenance", self.provenance, VersionReference, empty=False
        )
        _unique("provenance", provenance)
        if not isinstance(self.usable, bool):
            raise AnalysisContractError("usable must be a bool.")
        unusable_quality = {
            DataQualityStatus.STALE,
            DataQualityStatus.INVALID,
            DataQualityStatus.UNAVAILABLE,
        }
        if self.usable and self.quality_status in unusable_quality:
            raise AnalysisContractError(
                "unusable data quality cannot be marked usable."
            )
        object.__setattr__(self, "observed_at", observed)
        object.__setattr__(self, "available_at", available)
        object.__setattr__(self, "expires_at", expires)


@dataclass(frozen=True, slots=True)
class _Assessment:
    assessment_id: UUID
    asset: str
    instrument_id: str
    timeframe: str
    as_of: datetime
    available_at: datetime
    expires_at: datetime
    status: AssessmentStatus
    analytical_confidence: Decimal
    findings: tuple[AnalyticalFinding, ...]
    observations: tuple[DomainObservation, ...]
    evidence_ids: tuple[UUID, ...]
    contradiction_ids: tuple[UUID, ...]
    uncertainty_ids: tuple[UUID, ...]
    data_quality_report_id: UUID
    provenance: tuple[VersionReference, ...]
    methodology: MethodologyCategory | None = None
    schema_version: str = field(default=CONTRACT_SCHEMA_VERSION, init=False)
    contract_id: ClassVar[str]
    observation_categories: ClassVar[frozenset[str]]

    def __post_init__(self) -> None:
        _uuid("assessment_id", self.assessment_id)
        _text("asset", self.asset)
        _text("instrument_id", self.instrument_id)
        _text("timeframe", self.timeframe)
        as_of = _time("as_of", self.as_of)
        available = _time("available_at", self.available_at)
        expires = _time("expires_at", self.expires_at)
        _window("as_of", as_of, "available_at", available)
        _window("available_at", available, "expires_at", expires)
        if not isinstance(self.status, AssessmentStatus):
            raise AnalysisContractError("status must be an AssessmentStatus.")
        _score("analytical_confidence", self.analytical_confidence)
        findings = _typed_tuple("findings", self.findings, AnalyticalFinding)
        _unique("finding identities", tuple(item.finding_id for item in findings))
        observations = _typed_tuple(
            "observations", self.observations, DomainObservation
        )
        invalid_categories = {
            item.observation_type
            for item in observations
            if item.observation_type not in self.observation_categories
        }
        if invalid_categories:
            raise AnalysisContractError(
                f"observations contain categories invalid for {type(self).__name__}."
            )
        _uuid_tuple("evidence_ids", self.evidence_ids)
        _uuid_tuple("contradiction_ids", self.contradiction_ids)
        _uuid_tuple("uncertainty_ids", self.uncertainty_ids)
        _uuid("data_quality_report_id", self.data_quality_report_id)
        provenance = _typed_tuple(
            "provenance", self.provenance, VersionReference, empty=False
        )
        _unique("provenance", provenance)
        if self.methodology is not None and not isinstance(
            self.methodology, MethodologyCategory
        ):
            raise AnalysisContractError("methodology must be a MethodologyCategory.")
        if self.status is AssessmentStatus.AVAILABLE and not findings:
            raise AnalysisContractError("available assessment requires findings.")
        object.__setattr__(self, "as_of", as_of)
        object.__setattr__(self, "available_at", available)
        object.__setattr__(self, "expires_at", expires)


@dataclass(frozen=True, slots=True)
class FundamentalAssessment(_Assessment):
    contract_id: ClassVar[str] = "C-011"
    observation_categories: ClassVar[frozenset[str]] = frozenset(
        {
            "use-case",
            "adoption",
            "tokenomics",
            "unlocks",
            "treasury",
            "tvl",
            "revenue",
            "governance",
            "ecosystem-health",
        }
    )


@dataclass(frozen=True, slots=True)
class TechnicalAssessment(_Assessment):
    contract_id: ClassVar[str] = "C-012"
    observation_categories: ClassVar[frozenset[str]] = frozenset(
        {
            "trend",
            "momentum",
            "volatility",
            "volume",
            "market-structure",
            "multi-timeframe",
        }
    )


@dataclass(frozen=True, slots=True)
class SMCAssessment(_Assessment):
    contract_id: ClassVar[str] = "C-013"
    observation_categories: ClassVar[frozenset[str]] = frozenset(
        {
            "order-block",
            "breaker-block",
            "fair-value-gap",
            "liquidity",
            "bos",
            "choch",
            "mss",
            "displacement",
            "imbalance",
            "premium-discount",
        }
    )


@dataclass(frozen=True, slots=True)
class WyckoffAssessment(_Assessment):
    contract_id: ClassVar[str] = "C-014"
    observation_categories: ClassVar[frozenset[str]] = frozenset(
        {
            "phase",
            "event",
            "effort-result",
            "volume-spread",
            "absorption",
            "climactic-action",
        }
    )


@dataclass(frozen=True, slots=True)
class DerivativesAssessment(_Assessment):
    contract_id: ClassVar[str] = "C-015"
    observation_categories: ClassVar[frozenset[str]] = frozenset(
        {"funding", "open-interest", "basis", "positioning", "liquidation", "options"}
    )


@dataclass(frozen=True, slots=True)
class OnChainAssessment(_Assessment):
    contract_id: ClassVar[str] = "C-016"
    observation_categories: ClassVar[frozenset[str]] = frozenset(
        {
            "network-activity",
            "exchange-flow",
            "whale-activity",
            "holder-distribution",
            "stablecoin-flow",
            "network-security",
            "validator-activity",
            "capital-flow",
        }
    )


@dataclass(frozen=True, slots=True)
class SentimentAssessment(_Assessment):
    contract_id: ClassVar[str] = "C-017"
    observation_categories: ClassVar[frozenset[str]] = frozenset(
        {
            "market-sentiment",
            "asset-sentiment",
            "narrative",
            "social-volume",
            "fear-greed",
            "crowding",
            "sentiment-spike",
        }
    )


@dataclass(frozen=True, slots=True)
class EventRiskAssessment(_Assessment):
    contract_id: ClassVar[str] = "C-018"
    observation_categories: ClassVar[frozenset[str]] = frozenset(
        {
            "macro",
            "regulatory",
            "exchange",
            "project",
            "token-unlock",
            "governance",
            "security",
            "stablecoin",
            "etf",
            "protocol",
        }
    )


@dataclass(frozen=True, slots=True)
class FibonacciAssessment(_Assessment):
    contract_id: ClassVar[str] = "C-068"
    observation_categories: ClassVar[frozenset[str]] = frozenset(
        {"anchor", "retracement-level", "extension-level", "invalidation"}
    )


@dataclass(frozen=True, slots=True)
class RegimeDimension:
    name: str
    state: str
    evidence_ids: tuple[UUID, ...]

    def __post_init__(self) -> None:
        _text("name", self.name)
        _text("state", self.state)
        _uuid_tuple("evidence_ids", self.evidence_ids, empty=False)


@dataclass(frozen=True, slots=True)
class MarketRegime:
    regime_id: UUID
    asset: str
    instrument_id: str
    timeframe: str
    as_of: datetime
    expires_at: datetime
    direction: AnalyticalDirection
    dimensions: tuple[RegimeDimension, ...]
    explanation: str
    confidence: Decimal
    evidence_ids: tuple[UUID, ...]
    compatible_strategy_families: tuple[str, ...]
    contract_id: str = field(default="C-005", init=False)
    schema_version: str = field(default=CONTRACT_SCHEMA_VERSION, init=False)

    def __post_init__(self) -> None:
        _uuid("regime_id", self.regime_id)
        _text("asset", self.asset)
        _text("instrument_id", self.instrument_id)
        _text("timeframe", self.timeframe)
        as_of = _time("as_of", self.as_of)
        expires = _time("expires_at", self.expires_at)
        _window("as_of", as_of, "expires_at", expires)
        if not isinstance(self.direction, AnalyticalDirection):
            raise AnalysisContractError("direction must be an AnalyticalDirection.")
        dimensions = _typed_tuple(
            "dimensions", self.dimensions, RegimeDimension, empty=False
        )
        _unique("regime dimension names", tuple(item.name for item in dimensions))
        _text("explanation", self.explanation)
        _score("confidence", self.confidence)
        _uuid_tuple("evidence_ids", self.evidence_ids, empty=False)
        _text_tuple("compatible_strategy_families", self.compatible_strategy_families)
        object.__setattr__(self, "as_of", as_of)
        object.__setattr__(self, "expires_at", expires)


@dataclass(frozen=True, slots=True)
class ConfluenceComponent:
    domain: str
    direction: AnalyticalDirection
    relation: EvidenceRelation
    evidence_strength: Decimal
    dependence: EvidenceDependence
    evidence_ids: tuple[UUID, ...]

    def __post_init__(self) -> None:
        _text("domain", self.domain)
        if not isinstance(self.direction, AnalyticalDirection):
            raise AnalysisContractError("direction must be an AnalyticalDirection.")
        if not isinstance(self.relation, EvidenceRelation):
            raise AnalysisContractError("relation must be an EvidenceRelation.")
        _score("evidence_strength", self.evidence_strength)
        if not isinstance(self.dependence, EvidenceDependence):
            raise AnalysisContractError("dependence must be an EvidenceDependence.")
        _uuid_tuple("evidence_ids", self.evidence_ids, empty=False)


@dataclass(frozen=True, slots=True)
class ConfluenceAssessment:
    assessment_id: UUID
    as_of: datetime
    expires_at: datetime
    state: ConfluenceState
    components: tuple[ConfluenceComponent, ...]
    analytical_confidence: Decimal
    evidence_strength: Decimal
    independence_report: AgentIndependenceReference
    explanation: str
    contract_id: str = field(default="C-009", init=False)
    schema_version: str = field(default=CONTRACT_SCHEMA_VERSION, init=False)

    def __post_init__(self) -> None:
        _uuid("assessment_id", self.assessment_id)
        as_of = _time("as_of", self.as_of)
        expires = _time("expires_at", self.expires_at)
        _window("as_of", as_of, "expires_at", expires)
        if not isinstance(self.state, ConfluenceState):
            raise AnalysisContractError("state must be a ConfluenceState.")
        components = _typed_tuple(
            "components", self.components, ConfluenceComponent, empty=False
        )
        _unique("confluence domains", tuple(item.domain for item in components))
        _score("analytical_confidence", self.analytical_confidence)
        _score("evidence_strength", self.evidence_strength)
        if not isinstance(self.independence_report, AgentIndependenceReference):
            raise AnalysisContractError("independence_report has an invalid type.")
        _text("explanation", self.explanation)
        object.__setattr__(self, "as_of", as_of)
        object.__setattr__(self, "expires_at", expires)


@dataclass(frozen=True, slots=True)
class ConflictAssessment:
    assessment_id: UUID
    as_of: datetime
    expires_at: datetime
    finding_ids: tuple[UUID, ...]
    evidence_ids: tuple[UUID, ...]
    severity: Decimal
    explanation: str
    resolution_status: ResolutionStatus
    contract_id: str = field(default="C-010", init=False)
    schema_version: str = field(default=CONTRACT_SCHEMA_VERSION, init=False)

    def __post_init__(self) -> None:
        _uuid("assessment_id", self.assessment_id)
        as_of = _time("as_of", self.as_of)
        expires = _time("expires_at", self.expires_at)
        _window("as_of", as_of, "expires_at", expires)
        _uuid_tuple("finding_ids", self.finding_ids, empty=False)
        _uuid_tuple("evidence_ids", self.evidence_ids, empty=False)
        _score("severity", self.severity)
        _text("explanation", self.explanation)
        if not isinstance(self.resolution_status, ResolutionStatus):
            raise AnalysisContractError("resolution_status must be a ResolutionStatus.")
        object.__setattr__(self, "as_of", as_of)
        object.__setattr__(self, "expires_at", expires)


@dataclass(frozen=True, slots=True)
class AnalyticalUncertainty:
    uncertainty_id: UUID
    category: UncertaintyCategory
    description: str
    affected_finding_ids: tuple[UUID, ...]
    affected_domains: tuple[str, ...]
    severity: Decimal
    reducible: bool
    required_evidence: tuple[str, ...]
    as_of: datetime
    expires_at: datetime
    resolution_status: ResolutionStatus
    contract_id: str = field(default="C-069", init=False)
    schema_version: str = field(default=CONTRACT_SCHEMA_VERSION, init=False)

    def __post_init__(self) -> None:
        _uuid("uncertainty_id", self.uncertainty_id)
        if not isinstance(self.category, UncertaintyCategory):
            raise AnalysisContractError("category must be an UncertaintyCategory.")
        _text("description", self.description)
        _uuid_tuple("affected_finding_ids", self.affected_finding_ids)
        _text_tuple("affected_domains", self.affected_domains, empty=False)
        _score("severity", self.severity)
        if not isinstance(self.reducible, bool):
            raise AnalysisContractError("reducible must be a bool.")
        required = _text_tuple("required_evidence", self.required_evidence)
        if self.reducible and not required:
            raise AnalysisContractError(
                "reducible uncertainty requires evidence needs."
            )
        as_of = _time("as_of", self.as_of)
        expires = _time("expires_at", self.expires_at)
        _window("as_of", as_of, "expires_at", expires)
        if not isinstance(self.resolution_status, ResolutionStatus):
            raise AnalysisContractError("resolution_status must be a ResolutionStatus.")
        object.__setattr__(self, "as_of", as_of)
        object.__setattr__(self, "expires_at", expires)


@dataclass(frozen=True, slots=True)
class AdversarialAssessment:
    assessment_id: UUID
    as_of: datetime
    expires_at: datetime
    counter_thesis: str
    alternative_hypotheses: tuple[str, ...]
    contradictory_evidence_ids: tuple[UUID, ...]
    failure_conditions: tuple[str, ...]
    data_limitations: tuple[str, ...]
    measurement_error_risks: tuple[str, ...]
    confirmation_bias_concerns: tuple[str, ...]
    analytical_confidence: Decimal
    contract_id: str = field(default="C-019", init=False)
    schema_version: str = field(default=CONTRACT_SCHEMA_VERSION, init=False)

    def __post_init__(self) -> None:
        _uuid("assessment_id", self.assessment_id)
        as_of = _time("as_of", self.as_of)
        expires = _time("expires_at", self.expires_at)
        _window("as_of", as_of, "expires_at", expires)
        _text("counter_thesis", self.counter_thesis)
        _text_tuple("alternative_hypotheses", self.alternative_hypotheses, empty=False)
        _uuid_tuple("contradictory_evidence_ids", self.contradictory_evidence_ids)
        _text_tuple("failure_conditions", self.failure_conditions, empty=False)
        _text_tuple("data_limitations", self.data_limitations)
        _text_tuple("measurement_error_risks", self.measurement_error_risks)
        _text_tuple("confirmation_bias_concerns", self.confirmation_bias_concerns)
        _score("analytical_confidence", self.analytical_confidence)
        object.__setattr__(self, "as_of", as_of)
        object.__setattr__(self, "expires_at", expires)


@dataclass(frozen=True, slots=True)
class AnalysisSnapshot:
    snapshot_id: UUID
    asset: str
    instrument_id: str
    timeframe: str
    as_of: datetime
    created_at: datetime
    expires_at: datetime
    market_snapshot_id: UUID
    data_quality_report_id: UUID
    feature_set_ids: tuple[UUID, ...]
    dataset_versions: tuple[DatasetVersionReference, ...]
    assessment_ids: tuple[UUID, ...]
    evidence_ids: tuple[UUID, ...]
    provenance: tuple[VersionReference, ...]
    content_sha256: str
    contract_id: str = field(default="C-007", init=False)
    schema_version: str = field(default=CONTRACT_SCHEMA_VERSION, init=False)

    def __post_init__(self) -> None:
        _uuid("snapshot_id", self.snapshot_id)
        _text("asset", self.asset)
        _text("instrument_id", self.instrument_id)
        _text("timeframe", self.timeframe)
        as_of = _time("as_of", self.as_of)
        created = _time("created_at", self.created_at)
        expires = _time("expires_at", self.expires_at)
        _window("as_of", as_of, "created_at", created)
        _window("created_at", created, "expires_at", expires)
        _uuid("market_snapshot_id", self.market_snapshot_id)
        _uuid("data_quality_report_id", self.data_quality_report_id)
        _uuid_tuple("feature_set_ids", self.feature_set_ids)
        datasets = _typed_tuple(
            "dataset_versions", self.dataset_versions, DatasetVersionReference
        )
        _unique("dataset_versions", datasets)
        _uuid_tuple("assessment_ids", self.assessment_ids, empty=False)
        _uuid_tuple("evidence_ids", self.evidence_ids, empty=False)
        provenance = _typed_tuple(
            "provenance", self.provenance, VersionReference, empty=False
        )
        _unique("provenance", provenance)
        digest = _text("content_sha256", self.content_sha256)
        if _SHA256_PATTERN.fullmatch(digest) is None:
            raise AnalysisContractError(
                "content_sha256 must be a lowercase SHA-256 digest."
            )
        object.__setattr__(self, "as_of", as_of)
        object.__setattr__(self, "created_at", created)
        object.__setattr__(self, "expires_at", expires)


Assessment = (
    FundamentalAssessment
    | TechnicalAssessment
    | SMCAssessment
    | WyckoffAssessment
    | DerivativesAssessment
    | OnChainAssessment
    | SentimentAssessment
    | EventRiskAssessment
    | FibonacciAssessment
)


@dataclass(frozen=True, slots=True)
class MarketContext:
    context_id: UUID
    asset: str
    instrument_id: str
    as_of: datetime
    expires_at: datetime
    multi_timeframe_state: tuple[str, ...]
    regime: MarketRegime
    assessments: tuple[Assessment, ...]
    confluence: ConfluenceAssessment
    conflicts: tuple[ConflictAssessment, ...]
    adversarial: AdversarialAssessment
    uncertainties: tuple[AnalyticalUncertainty, ...]
    evidence_ids: tuple[UUID, ...]
    analysis_snapshot_id: UUID
    data_quality_report_id: UUID
    contract_id: str = field(default="C-006", init=False)
    schema_version: str = field(default=CONTRACT_SCHEMA_VERSION, init=False)

    def __post_init__(self) -> None:
        _uuid("context_id", self.context_id)
        _text("asset", self.asset)
        _text("instrument_id", self.instrument_id)
        as_of = _time("as_of", self.as_of)
        expires = _time("expires_at", self.expires_at)
        _window("as_of", as_of, "expires_at", expires)
        _text_tuple("multi_timeframe_state", self.multi_timeframe_state, empty=False)
        if not isinstance(self.regime, MarketRegime):
            raise AnalysisContractError("regime must be a MarketRegime.")
        allowed = (
            FundamentalAssessment,
            TechnicalAssessment,
            SMCAssessment,
            WyckoffAssessment,
            DerivativesAssessment,
            OnChainAssessment,
            SentimentAssessment,
            EventRiskAssessment,
            FibonacciAssessment,
        )
        assessments = _tuple("assessments", self.assessments, empty=False)
        if not all(isinstance(item, allowed) for item in assessments):
            raise AnalysisContractError("assessments contains an invalid type.")
        _unique("assessment contract types", tuple(type(item) for item in assessments))
        if not isinstance(self.confluence, ConfluenceAssessment):
            raise AnalysisContractError("confluence has an invalid type.")
        _typed_tuple("conflicts", self.conflicts, ConflictAssessment)
        if not isinstance(self.adversarial, AdversarialAssessment):
            raise AnalysisContractError("adversarial has an invalid type.")
        uncertainties = _typed_tuple(
            "uncertainties", self.uncertainties, AnalyticalUncertainty, empty=False
        )
        _unique(
            "uncertainty identities",
            tuple(item.uncertainty_id for item in uncertainties),
        )
        _uuid_tuple("evidence_ids", self.evidence_ids, empty=False)
        _uuid("analysis_snapshot_id", self.analysis_snapshot_id)
        _uuid("data_quality_report_id", self.data_quality_report_id)
        object.__setattr__(self, "as_of", as_of)
        object.__setattr__(self, "expires_at", expires)
