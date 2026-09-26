from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from typing import ClassVar, TypeVar, cast
from uuid import UUID

from trading_platform_api.risk import ContractReference, VersionReference
from trading_platform_api.validation import CalibrationResult

CONTRACT_SCHEMA_VERSION = "1"
_SHA256 = re.compile(r"[0-9a-f]{64}")
_T = TypeVar("_T")


class LearningContractError(ValueError):
    """Raised when learning or governance evidence is structurally invalid."""


class ExperienceStatus(StrEnum):
    EXECUTED = "EXECUTED"
    REJECTED = "REJECTED"
    NO_TRADE = "NO_TRADE"
    FAILED = "FAILED"
    INCOMPLETE = "INCOMPLETE"


class LearningPipelineState(StrEnum):
    EXPERIENCE_CAPTURED = "EXPERIENCE_CAPTURED"
    EVALUATED = "EVALUATED"
    OBSERVATION_CREATED = "OBSERVATION_CREATED"
    INSIGHT_CREATED = "INSIGHT_CREATED"
    HYPOTHESIS_CREATED = "HYPOTHESIS_CREATED"
    EXPERIMENT_PLANNED = "EXPERIMENT_PLANNED"
    EXPERIMENT_RUNNING = "EXPERIMENT_RUNNING"
    RESULT_RECORDED = "RESULT_RECORDED"
    GOVERNANCE_PENDING = "GOVERNANCE_PENDING"
    REJECTED = "REJECTED"


class ExperimentStatus(StrEnum):
    DRAFT = "DRAFT"
    APPROVED_FOR_RESEARCH = "APPROVED_FOR_RESEARCH"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    EVALUATED = "EVALUATED"
    CANCELLED = "CANCELLED"
    FAILED = "FAILED"


class ExperimentResultStatus(StrEnum):
    VALIDATED = "VALIDATED"
    INCONCLUSIVE = "INCONCLUSIVE"
    DEGRADED = "DEGRADED"
    FAILED = "FAILED"
    UNKNOWN = "UNKNOWN"


class KnowledgeStatus(StrEnum):
    OBSERVED = "OBSERVED"
    HYPOTHESIS = "HYPOTHESIS"
    VALIDATED = "VALIDATED"
    INVALIDATED = "INVALIDATED"
    RETIRED = "RETIRED"


class StrategyDecayState(StrEnum):
    HEALTHY = "HEALTHY"
    WATCH = "WATCH"
    DEGRADED = "DEGRADED"
    SUSPENDED = "SUSPENDED"
    RETIRED = "RETIRED"


class ArtifactLifecycle(StrEnum):
    DRAFT = "DRAFT"
    CANDIDATE = "CANDIDATE"
    VALIDATED = "VALIDATED"
    APPROVED_FOR_SHADOW = "APPROVED_FOR_SHADOW"
    APPROVED_FOR_PAPER = "APPROVED_FOR_PAPER"
    APPROVED_FOR_PRODUCTION = "APPROVED_FOR_PRODUCTION"
    ACTIVE = "ACTIVE"
    REJECTED = "REJECTED"
    RETIRED = "RETIRED"
    ROLLED_BACK = "ROLLED_BACK"


class DriftDimension(StrEnum):
    DATA = "DATA"
    CONCEPT = "CONCEPT"
    MODEL = "MODEL"
    PROMPT = "PROMPT"
    STRATEGY = "STRATEGY"
    CALIBRATION = "CALIBRATION"
    FEATURE = "FEATURE"
    REGIME = "REGIME"


class DriftStatus(StrEnum):
    NONE = "NONE"
    WATCH = "WATCH"
    DETECTED = "DETECTED"
    SEVERE = "SEVERE"
    UNKNOWN = "UNKNOWN"


class AwarenessStatus(StrEnum):
    READY = "READY"
    DEGRADED = "DEGRADED"
    BLOCKED = "BLOCKED"
    UNKNOWN = "UNKNOWN"


class GovernanceDecisionType(StrEnum):
    APPROVE_FOR_SHADOW = "APPROVE_FOR_SHADOW"
    APPROVE_FOR_PAPER = "APPROVE_FOR_PAPER"
    APPROVE_FOR_PRODUCTION = "APPROVE_FOR_PRODUCTION"
    ACTIVATE = "ACTIVATE"
    REJECT = "REJECT"
    RETIRE = "RETIRE"
    ROLLBACK = "ROLLBACK"


class CounterfactualClassification(StrEnum):
    HYPOTHETICAL = "HYPOTHETICAL"


class EvaluationMode(StrEnum):
    OFFLINE = "OFFLINE"
    BACKTEST = "BACKTEST"
    PAPER = "PAPER"
    SHADOW = "SHADOW"


class ComparisonOutcome(StrEnum):
    CHALLENGER_BETTER = "CHALLENGER_BETTER"
    CHAMPION_BETTER = "CHAMPION_BETTER"
    EQUIVALENT = "EQUIVALENT"
    INCONCLUSIVE = "INCONCLUSIVE"
    DEGRADED = "DEGRADED"
    UNKNOWN = "UNKNOWN"


def _text(name: str, value: object, *, maximum: int = 1024) -> str:
    if not isinstance(value, str):
        raise LearningContractError(f"{name} must be a string.")
    if not value.strip():
        raise LearningContractError(f"{name} must not be blank.")
    if value != value.strip():
        raise LearningContractError(f"{name} must not contain surrounding whitespace.")
    if len(value) > maximum:
        raise LearningContractError(f"{name} must not exceed {maximum} characters.")
    return value


def _uuid(name: str, value: object) -> UUID:
    if not isinstance(value, UUID):
        raise LearningContractError(f"{name} must be a UUID.")
    return value


def _time(name: str, value: object) -> datetime:
    if not isinstance(value, datetime):
        raise LearningContractError(f"{name} must be a datetime.")
    if value.tzinfo is None or value.utcoffset() is None:
        raise LearningContractError(f"{name} must be timezone-aware.")
    return value.astimezone(UTC)


def _decimal(name: str, value: object) -> Decimal:
    if (
        not isinstance(value, Decimal)
        or isinstance(value, bool)
        or not value.is_finite()
    ):
        raise LearningContractError(f"{name} must be a finite Decimal.")
    return value


def _ratio(name: str, value: object) -> Decimal:
    result = _decimal(name, value)
    if not Decimal("0") <= result <= Decimal("1"):
        raise LearningContractError(f"{name} must be between 0 and 1.")
    return result


def _positive_int(name: str, value: object) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise LearningContractError(f"{name} must be a positive integer.")
    return value


def _bool(name: str, value: object) -> bool:
    if not isinstance(value, bool):
        raise LearningContractError(f"{name} must be a boolean.")
    return value


def _digest(name: str, value: object) -> str:
    result = _text(name, value, maximum=64)
    if _SHA256.fullmatch(result) is None:
        raise LearningContractError(f"{name} must be a lowercase SHA-256 digest.")
    return result


def _tuple(name: str, value: object, *, empty: bool = True) -> tuple[object, ...]:
    if not isinstance(value, tuple):
        raise LearningContractError(f"{name} must be a tuple.")
    if not empty and not value:
        raise LearningContractError(f"{name} must not be empty.")
    return value


def _unique(name: str, values: tuple[object, ...]) -> None:
    try:
        count = len(set(values))
    except TypeError as exc:
        raise LearningContractError(f"{name} must have hashable identities.") from exc
    if count != len(values):
        raise LearningContractError(f"{name} must not contain duplicates.")


def _typed_tuple(
    name: str, value: object, expected: type[_T], *, empty: bool = True
) -> tuple[_T, ...]:
    values = _tuple(name, value, empty=empty)
    if any(not isinstance(item, expected) for item in values):
        raise LearningContractError(f"{name} contains an invalid type.")
    return cast(tuple[_T, ...], values)


def _text_tuple(name: str, value: object, *, empty: bool = True) -> tuple[str, ...]:
    values = _tuple(name, value, empty=empty)
    result = tuple(_text(f"{name}[{index}]", item) for index, item in enumerate(values))
    _unique(name, result)
    return result


def _references(
    name: str,
    value: object,
    *,
    allowed: set[str] | None = None,
    empty: bool = True,
) -> tuple[ContractReference, ...]:
    values = _typed_tuple(name, value, ContractReference, empty=empty)
    if allowed is not None and any(item.contract_id not in allowed for item in values):
        expected = ", ".join(sorted(allowed))
        raise LearningContractError(f"{name} must contain only {expected} references.")
    _unique(name, tuple((item.contract_id, item.entity_id) for item in values))
    return values


def _reference(
    name: str, value: object, contract_id: str | set[str]
) -> ContractReference:
    allowed = {contract_id} if isinstance(contract_id, str) else contract_id
    if not isinstance(value, ContractReference) or value.contract_id not in allowed:
        expected = ", ".join(sorted(allowed))
        raise LearningContractError(f"{name} must be a {expected} reference.")
    return value


def _optional_reference(
    name: str, value: object, contract_id: str | set[str]
) -> ContractReference | None:
    if value is None:
        return None
    return _reference(name, value, contract_id)


def _version(name: str, value: object) -> VersionReference:
    if not isinstance(value, VersionReference):
        raise LearningContractError(f"{name} must be a VersionReference.")
    return value


def _enum(name: str, value: object, expected: type[_T]) -> _T:
    if not isinstance(value, expected):
        raise LearningContractError(f"{name} must be a {expected.__name__}.")
    return value


def _ordered(
    earlier_name: str, earlier: datetime, later_name: str, later: datetime
) -> None:
    if earlier > later:
        raise LearningContractError(f"{earlier_name} must not be after {later_name}.")


def _normalize_window(
    start: datetime, end: datetime, *, prefix: str = "window"
) -> tuple[datetime, datetime]:
    normalized_start = _time(f"{prefix}_start", start)
    normalized_end = _time(f"{prefix}_end", end)
    _ordered(f"{prefix}_start", normalized_start, f"{prefix}_end", normalized_end)
    if normalized_start == normalized_end:
        raise LearningContractError(f"{prefix} must have positive duration.")
    return normalized_start, normalized_end


@dataclass(frozen=True, slots=True)
class EvidenceReference:
    evidence_id: UUID
    evidence_type: str
    source: str
    source_version: str
    content_sha256: str

    def __post_init__(self) -> None:
        _uuid("evidence_id", self.evidence_id)
        for name in ("evidence_type", "source", "source_version"):
            _text(name, getattr(self, name))
        _digest("content_sha256", self.content_sha256)


@dataclass(frozen=True, slots=True)
class MetricObservation:
    name: str
    value: Decimal
    unit: str
    sample_size: int
    method_version: VersionReference
    evidence: tuple[EvidenceReference, ...]
    interval_lower: Decimal | None = None
    interval_upper: Decimal | None = None

    def __post_init__(self) -> None:
        _text("name", self.name)
        value = _decimal("value", self.value)
        _text("unit", self.unit)
        _positive_int("sample_size", self.sample_size)
        _version("method_version", self.method_version)
        _typed_tuple("evidence", self.evidence, EvidenceReference, empty=False)
        if (self.interval_lower is None) != (self.interval_upper is None):
            raise LearningContractError(
                "metric interval bounds must be supplied together."
            )
        if self.interval_lower is not None and self.interval_upper is not None:
            lower = _decimal("interval_lower", self.interval_lower)
            upper = _decimal("interval_upper", self.interval_upper)
            if lower > value or value > upper:
                raise LearningContractError(
                    "metric value must lie inside its interval."
                )


@dataclass(frozen=True, slots=True)
class EvaluationScope:
    assets: tuple[str, ...]
    timeframes: tuple[str, ...]
    regimes: tuple[str, ...]
    task: str

    def __post_init__(self) -> None:
        for name in ("assets", "timeframes", "regimes"):
            _text_tuple(name, getattr(self, name), empty=False)
        _text("task", self.task)


@dataclass(frozen=True, slots=True)
class VersionedArtifact:
    artifact_id: UUID
    artifact_type: str
    version: VersionReference
    lifecycle: ArtifactLifecycle

    def __post_init__(self) -> None:
        _uuid("artifact_id", self.artifact_id)
        _text("artifact_type", self.artifact_type)
        _version("version", self.version)
        _enum("lifecycle", self.lifecycle, ArtifactLifecycle)


@dataclass(frozen=True, slots=True)
class GovernanceActorReference:
    actor_id: str
    authority: str
    authentication_evidence: EvidenceReference

    def __post_init__(self) -> None:
        _text("actor_id", self.actor_id)
        _text("authority", self.authority)
        if not isinstance(self.authentication_evidence, EvidenceReference):
            raise LearningContractError(
                "authentication_evidence must be an EvidenceReference."
            )


@dataclass(frozen=True, slots=True)
class Experience:
    CONTRACT_ID: ClassVar[str] = "C-045"
    SCHEMA_VERSION: ClassVar[str] = CONTRACT_SCHEMA_VERSION

    experience_id: UUID
    status: ExperienceStatus
    market_refs: tuple[ContractReference, ...]
    analysis_refs: tuple[ContractReference, ...]
    strategy_refs: tuple[ContractReference, ...]
    decision_refs: tuple[ContractReference, ...]
    validation_refs: tuple[ContractReference, ...]
    risk_refs: tuple[ContractReference, ...]
    approval_ref: ContractReference | None
    execution_refs: tuple[ContractReference, ...]
    factual_outcome_ref: ContractReference | None
    agent_output_refs: tuple[EvidenceReference, ...]
    safety_refs: tuple[ContractReference, ...]
    awareness_ref: ContractReference | None
    correlation_id: str
    occurred_at: datetime
    recorded_at: datetime
    content_sha256: str
    contract_id: str = field(default="C-045", init=False)
    schema_version: str = field(default=CONTRACT_SCHEMA_VERSION, init=False)

    def __post_init__(self) -> None:
        _uuid("experience_id", self.experience_id)
        _enum("status", self.status, ExperienceStatus)
        _references(
            "market_refs",
            self.market_refs,
            allowed=set(f"C-{i:03d}" for i in range(1, 7)),
            empty=False,
        )
        _references(
            "analysis_refs",
            self.analysis_refs,
            allowed=set(f"C-{i:03d}" for i in range(7, 20)),
            empty=False,
        )
        _references(
            "strategy_refs",
            self.strategy_refs,
            allowed={"C-020", "C-021", "C-022"},
            empty=False,
        )
        decisions = _references(
            "decision_refs",
            self.decision_refs,
            allowed={"C-023", "C-024", "C-025", "C-026"},
            empty=False,
        )
        _references(
            "validation_refs",
            self.validation_refs,
            allowed={"C-027", "C-028", "C-029", "C-030", "C-031"},
        )
        _references(
            "risk_refs",
            self.risk_refs,
            allowed={"C-032", "C-033", "C-034", "C-035", "C-036"},
        )
        approval = _optional_reference("approval_ref", self.approval_ref, "C-038")
        executions = _references(
            "execution_refs",
            self.execution_refs,
            allowed={"C-039", "C-040", "C-041", "C-042", "C-043"},
        )
        outcome = _optional_reference(
            "factual_outcome_ref", self.factual_outcome_ref, "C-044"
        )
        _typed_tuple(
            "agent_output_refs", self.agent_output_refs, EvidenceReference, empty=False
        )
        _references(
            "safety_refs", self.safety_refs, allowed={"C-058", "C-059"}, empty=False
        )
        _optional_reference("awareness_ref", self.awareness_ref, "C-054")
        _text("correlation_id", self.correlation_id)
        occurred = _time("occurred_at", self.occurred_at)
        recorded = _time("recorded_at", self.recorded_at)
        _ordered("occurred_at", occurred, "recorded_at", recorded)
        object.__setattr__(self, "occurred_at", occurred)
        object.__setattr__(self, "recorded_at", recorded)
        _digest("content_sha256", self.content_sha256)

        if self.status is ExperienceStatus.EXECUTED:
            if approval is None or not executions or outcome is None:
                raise LearningContractError(
                    "EXECUTED experience requires approval, execution, and factual outcome."
                )
            if "C-043" not in {item.contract_id for item in executions}:
                raise LearningContractError(
                    "EXECUTED experience requires a C-043 trade."
                )
        elif self.status is ExperienceStatus.NO_TRADE:
            if not any(item.contract_id == "C-026" for item in decisions):
                raise LearningContractError(
                    "NO_TRADE experience requires C-026 evidence."
                )
            if approval is not None or executions or outcome is not None:
                raise LearningContractError(
                    "NO_TRADE experience cannot contain approval or execution facts."
                )
        elif self.status is ExperienceStatus.REJECTED:
            if approval is None:
                raise LearningContractError(
                    "REJECTED experience requires C-038 evidence."
                )
            if executions or outcome is not None:
                raise LearningContractError(
                    "REJECTED experience cannot contain execution or outcome facts."
                )
        if outcome is not None and not executions:
            raise LearningContractError(
                "Factual outcome requires execution provenance."
            )


ExperienceRecord = Experience


@dataclass(frozen=True, slots=True)
class LearningObservation:
    CONTRACT_ID: ClassVar[str] = "C-046"
    SCHEMA_VERSION: ClassVar[str] = CONTRACT_SCHEMA_VERSION

    observation_id: UUID
    experience_refs: tuple[ContractReference, ...]
    scope: EvaluationScope
    statement: str
    sample_size: int
    evidence: tuple[EvidenceReference, ...]
    uncertainty: Decimal
    limitations: tuple[str, ...]
    observed_at: datetime
    method_version: VersionReference
    content_sha256: str
    contract_id: str = field(default="C-046", init=False)
    schema_version: str = field(default=CONTRACT_SCHEMA_VERSION, init=False)

    def __post_init__(self) -> None:
        _uuid("observation_id", self.observation_id)
        _references(
            "experience_refs", self.experience_refs, allowed={"C-045"}, empty=False
        )
        if not isinstance(self.scope, EvaluationScope):
            raise LearningContractError("scope must be an EvaluationScope.")
        _text("statement", self.statement, maximum=4096)
        _positive_int("sample_size", self.sample_size)
        _typed_tuple("evidence", self.evidence, EvidenceReference, empty=False)
        _ratio("uncertainty", self.uncertainty)
        _text_tuple("limitations", self.limitations, empty=False)
        object.__setattr__(self, "observed_at", _time("observed_at", self.observed_at))
        _version("method_version", self.method_version)
        _digest("content_sha256", self.content_sha256)


@dataclass(frozen=True, slots=True)
class LearningInsight:
    CONTRACT_ID: ClassVar[str] = "C-047"
    SCHEMA_VERSION: ClassVar[str] = CONTRACT_SCHEMA_VERSION

    insight_id: UUID
    observation_refs: tuple[ContractReference, ...]
    scope: EvaluationScope
    statement: str
    evidence: tuple[EvidenceReference, ...]
    uncertainty: Decimal
    limitations: tuple[str, ...]
    created_at: datetime
    method_version: VersionReference
    content_sha256: str
    contract_id: str = field(default="C-047", init=False)
    schema_version: str = field(default=CONTRACT_SCHEMA_VERSION, init=False)

    def __post_init__(self) -> None:
        _uuid("insight_id", self.insight_id)
        _references(
            "observation_refs", self.observation_refs, allowed={"C-046"}, empty=False
        )
        if not isinstance(self.scope, EvaluationScope):
            raise LearningContractError("scope must be an EvaluationScope.")
        _text("statement", self.statement, maximum=4096)
        _typed_tuple("evidence", self.evidence, EvidenceReference, empty=False)
        _ratio("uncertainty", self.uncertainty)
        _text_tuple("limitations", self.limitations, empty=False)
        object.__setattr__(self, "created_at", _time("created_at", self.created_at))
        _version("method_version", self.method_version)
        _digest("content_sha256", self.content_sha256)


@dataclass(frozen=True, slots=True)
class Hypothesis:
    CONTRACT_ID: ClassVar[str] = "C-048"
    SCHEMA_VERSION: ClassVar[str] = CONTRACT_SCHEMA_VERSION

    hypothesis_id: UUID
    insight_refs: tuple[ContractReference, ...]
    scope: EvaluationScope
    statement: str
    expected_effect: str
    falsification_criteria: tuple[str, ...]
    success_criteria: tuple[str, ...]
    evidence: tuple[EvidenceReference, ...]
    created_at: datetime
    content_sha256: str
    contract_id: str = field(default="C-048", init=False)
    schema_version: str = field(default=CONTRACT_SCHEMA_VERSION, init=False)

    def __post_init__(self) -> None:
        _uuid("hypothesis_id", self.hypothesis_id)
        _references("insight_refs", self.insight_refs, allowed={"C-047"}, empty=False)
        if not isinstance(self.scope, EvaluationScope):
            raise LearningContractError("scope must be an EvaluationScope.")
        _text("statement", self.statement, maximum=4096)
        _text("expected_effect", self.expected_effect, maximum=4096)
        _text_tuple("falsification_criteria", self.falsification_criteria, empty=False)
        _text_tuple("success_criteria", self.success_criteria, empty=False)
        _typed_tuple("evidence", self.evidence, EvidenceReference, empty=False)
        object.__setattr__(self, "created_at", _time("created_at", self.created_at))
        _digest("content_sha256", self.content_sha256)


@dataclass(frozen=True, slots=True)
class Experiment:
    CONTRACT_ID: ClassVar[str] = "C-049"
    SCHEMA_VERSION: ClassVar[str] = CONTRACT_SCHEMA_VERSION

    experiment_id: UUID
    hypothesis_ref: ContractReference
    status: ExperimentStatus
    baseline: VersionedArtifact
    candidate: VersionedArtifact
    dataset: VersionedArtifact
    method_version: VersionReference
    scope: EvaluationScope
    metric_names: tuple[str, ...]
    fold_ids: tuple[str, ...]
    assumptions: tuple[str, ...]
    research_approval: EvidenceReference | None
    window_start: datetime
    window_end: datetime
    created_at: datetime
    content_sha256: str
    contract_id: str = field(default="C-049", init=False)
    schema_version: str = field(default=CONTRACT_SCHEMA_VERSION, init=False)

    def __post_init__(self) -> None:
        _uuid("experiment_id", self.experiment_id)
        _reference("hypothesis_ref", self.hypothesis_ref, "C-048")
        _enum("status", self.status, ExperimentStatus)
        for name in ("baseline", "candidate", "dataset"):
            if not isinstance(getattr(self, name), VersionedArtifact):
                raise LearningContractError(f"{name} must be a VersionedArtifact.")
        if self.baseline.artifact_id == self.candidate.artifact_id and (
            self.baseline.version == self.candidate.version
        ):
            raise LearningContractError(
                "baseline and candidate must be distinct versions."
            )
        _version("method_version", self.method_version)
        if not isinstance(self.scope, EvaluationScope):
            raise LearningContractError("scope must be an EvaluationScope.")
        _text_tuple("metric_names", self.metric_names, empty=False)
        _text_tuple("fold_ids", self.fold_ids, empty=False)
        _text_tuple("assumptions", self.assumptions, empty=False)
        if self.status is not ExperimentStatus.DRAFT and not isinstance(
            self.research_approval, EvidenceReference
        ):
            raise LearningContractError(
                "non-draft experiment requires research approval evidence."
            )
        if self.research_approval is not None and not isinstance(
            self.research_approval, EvidenceReference
        ):
            raise LearningContractError(
                "research_approval must be an EvidenceReference."
            )
        start, end = _normalize_window(self.window_start, self.window_end)
        created = _time("created_at", self.created_at)
        if created > start:
            raise LearningContractError("experiment must be created before its window.")
        object.__setattr__(self, "window_start", start)
        object.__setattr__(self, "window_end", end)
        object.__setattr__(self, "created_at", created)
        _digest("content_sha256", self.content_sha256)


@dataclass(frozen=True, slots=True)
class ExperimentResult:
    CONTRACT_ID: ClassVar[str] = "C-050"
    SCHEMA_VERSION: ClassVar[str] = CONTRACT_SCHEMA_VERSION

    result_id: UUID
    experiment_ref: ContractReference
    experiment_version: VersionReference
    status: ExperimentResultStatus
    baseline: VersionedArtifact
    candidate: VersionedArtifact
    metrics: tuple[MetricObservation, ...]
    validation_refs: tuple[ContractReference, ...]
    evidence: tuple[EvidenceReference, ...]
    uncertainty: Decimal
    limitations: tuple[str, ...]
    evaluated_at: datetime
    content_sha256: str
    contract_id: str = field(default="C-050", init=False)
    schema_version: str = field(default=CONTRACT_SCHEMA_VERSION, init=False)

    def __post_init__(self) -> None:
        _uuid("result_id", self.result_id)
        _reference("experiment_ref", self.experiment_ref, "C-049")
        _version("experiment_version", self.experiment_version)
        _enum("status", self.status, ExperimentResultStatus)
        for name in ("baseline", "candidate"):
            if not isinstance(getattr(self, name), VersionedArtifact):
                raise LearningContractError(f"{name} must be a VersionedArtifact.")
        metrics = _typed_tuple("metrics", self.metrics, MetricObservation, empty=False)
        _unique("metric names", tuple(item.name for item in metrics))
        _references(
            "validation_refs",
            self.validation_refs,
            allowed={"C-027", "C-028", "C-029", "C-030", "C-031"},
            empty=False,
        )
        _typed_tuple("evidence", self.evidence, EvidenceReference, empty=False)
        _ratio("uncertainty", self.uncertainty)
        _text_tuple("limitations", self.limitations, empty=False)
        object.__setattr__(
            self, "evaluated_at", _time("evaluated_at", self.evaluated_at)
        )
        _digest("content_sha256", self.content_sha256)


@dataclass(frozen=True, slots=True)
class StrategyChangeProposal:
    CONTRACT_ID: ClassVar[str] = "C-051"
    SCHEMA_VERSION: ClassVar[str] = CONTRACT_SCHEMA_VERSION

    proposal_id: UUID
    result_refs: tuple[ContractReference, ...]
    current_artifact: VersionedArtifact
    proposed_artifact: VersionedArtifact
    rationale: str
    expected_effect: str
    compatibility_refs: tuple[EvidenceReference, ...]
    rollback_target: VersionedArtifact
    created_at: datetime
    content_sha256: str
    contract_id: str = field(default="C-051", init=False)
    schema_version: str = field(default=CONTRACT_SCHEMA_VERSION, init=False)

    def __post_init__(self) -> None:
        _uuid("proposal_id", self.proposal_id)
        _references("result_refs", self.result_refs, allowed={"C-050"}, empty=False)
        for name in ("current_artifact", "proposed_artifact", "rollback_target"):
            if not isinstance(getattr(self, name), VersionedArtifact):
                raise LearningContractError(f"{name} must be a VersionedArtifact.")
        if self.proposed_artifact.lifecycle not in {
            ArtifactLifecycle.DRAFT,
            ArtifactLifecycle.CANDIDATE,
            ArtifactLifecycle.VALIDATED,
        }:
            raise LearningContractError(
                "learning proposal may contain only draft, candidate, or validated artifacts."
            )
        if self.current_artifact.version == self.proposed_artifact.version:
            raise LearningContractError(
                "proposal must introduce a new immutable version."
            )
        if self.rollback_target.version != self.current_artifact.version:
            raise LearningContractError(
                "rollback target must preserve the current version."
            )
        _text("rationale", self.rationale, maximum=4096)
        _text("expected_effect", self.expected_effect, maximum=4096)
        _typed_tuple(
            "compatibility_refs",
            self.compatibility_refs,
            EvidenceReference,
            empty=False,
        )
        object.__setattr__(self, "created_at", _time("created_at", self.created_at))
        _digest("content_sha256", self.content_sha256)


@dataclass(frozen=True, slots=True)
class AgentPerformance:
    CONTRACT_ID: ClassVar[str] = "C-052"
    SCHEMA_VERSION: ClassVar[str] = CONTRACT_SCHEMA_VERSION

    performance_id: UUID
    agent: VersionedArtifact
    model_version: VersionReference
    prompt_version: VersionReference
    scope: EvaluationScope
    sample_size: int
    metrics: tuple[MetricObservation, ...]
    calibration_ref: ContractReference | None
    drift_ref: ContractReference | None
    evidence: tuple[EvidenceReference, ...]
    uncertainty: Decimal
    limitations: tuple[str, ...]
    window_start: datetime
    window_end: datetime
    evaluated_at: datetime
    content_sha256: str
    contract_id: str = field(default="C-052", init=False)
    schema_version: str = field(default=CONTRACT_SCHEMA_VERSION, init=False)

    def __post_init__(self) -> None:
        _uuid("performance_id", self.performance_id)
        if not isinstance(self.agent, VersionedArtifact):
            raise LearningContractError("agent must be a VersionedArtifact.")
        _version("model_version", self.model_version)
        _version("prompt_version", self.prompt_version)
        if not isinstance(self.scope, EvaluationScope):
            raise LearningContractError("scope must be an EvaluationScope.")
        _positive_int("sample_size", self.sample_size)
        metrics = _typed_tuple("metrics", self.metrics, MetricObservation, empty=False)
        _unique("metric names", tuple(item.name for item in metrics))
        if any(item.sample_size > self.sample_size for item in metrics):
            raise LearningContractError(
                "metric sample size cannot exceed performance sample size."
            )
        _optional_reference("calibration_ref", self.calibration_ref, "C-031")
        _optional_reference("drift_ref", self.drift_ref, "C-055")
        _typed_tuple("evidence", self.evidence, EvidenceReference, empty=False)
        _ratio("uncertainty", self.uncertainty)
        _text_tuple("limitations", self.limitations, empty=False)
        start, end = _normalize_window(self.window_start, self.window_end)
        evaluated = _time("evaluated_at", self.evaluated_at)
        _ordered("window_end", end, "evaluated_at", evaluated)
        object.__setattr__(self, "window_start", start)
        object.__setattr__(self, "window_end", end)
        object.__setattr__(self, "evaluated_at", evaluated)
        _digest("content_sha256", self.content_sha256)


@dataclass(frozen=True, slots=True)
class StrategyPerformance:
    CONTRACT_ID: ClassVar[str] = "C-053"
    SCHEMA_VERSION: ClassVar[str] = CONTRACT_SCHEMA_VERSION

    performance_id: UUID
    strategy: VersionedArtifact
    scope: EvaluationScope
    sample_size: int
    metrics: tuple[MetricObservation, ...]
    recent_metrics: tuple[MetricObservation, ...]
    long_term_metrics: tuple[MetricObservation, ...]
    decay_state: StrategyDecayState
    drift_ref: ContractReference | None
    validation_refs: tuple[ContractReference, ...]
    evidence: tuple[EvidenceReference, ...]
    uncertainty: Decimal
    limitations: tuple[str, ...]
    window_start: datetime
    window_end: datetime
    evaluated_at: datetime
    content_sha256: str
    contract_id: str = field(default="C-053", init=False)
    schema_version: str = field(default=CONTRACT_SCHEMA_VERSION, init=False)

    def __post_init__(self) -> None:
        _uuid("performance_id", self.performance_id)
        if not isinstance(self.strategy, VersionedArtifact):
            raise LearningContractError("strategy must be a VersionedArtifact.")
        if not isinstance(self.scope, EvaluationScope):
            raise LearningContractError("scope must be an EvaluationScope.")
        _positive_int("sample_size", self.sample_size)
        for name in ("metrics", "recent_metrics", "long_term_metrics"):
            metrics = _typed_tuple(
                name, getattr(self, name), MetricObservation, empty=False
            )
            _unique(f"{name} names", tuple(item.name for item in metrics))
            if any(item.sample_size > self.sample_size for item in metrics):
                raise LearningContractError(
                    f"{name} sample size cannot exceed performance sample size."
                )
        _enum("decay_state", self.decay_state, StrategyDecayState)
        _optional_reference("drift_ref", self.drift_ref, "C-055")
        _references(
            "validation_refs",
            self.validation_refs,
            allowed={"C-027", "C-028", "C-029", "C-030", "C-031"},
            empty=False,
        )
        _typed_tuple("evidence", self.evidence, EvidenceReference, empty=False)
        _ratio("uncertainty", self.uncertainty)
        _text_tuple("limitations", self.limitations, empty=False)
        start, end = _normalize_window(self.window_start, self.window_end)
        evaluated = _time("evaluated_at", self.evaluated_at)
        _ordered("window_end", end, "evaluated_at", evaluated)
        object.__setattr__(self, "window_start", start)
        object.__setattr__(self, "window_end", end)
        object.__setattr__(self, "evaluated_at", evaluated)
        _digest("content_sha256", self.content_sha256)


@dataclass(frozen=True, slots=True)
class SystemAwarenessSnapshot:
    CONTRACT_ID: ClassVar[str] = "C-054"
    SCHEMA_VERSION: ClassVar[str] = CONTRACT_SCHEMA_VERSION

    snapshot_id: UUID
    status: AwarenessStatus
    data_health_refs: tuple[ContractReference, ...]
    market_regime_refs: tuple[ContractReference, ...]
    agent_performance_refs: tuple[ContractReference, ...]
    strategy_performance_refs: tuple[ContractReference, ...]
    validation_refs: tuple[ContractReference, ...]
    drift_refs: tuple[ContractReference, ...]
    portfolio_risk_refs: tuple[ContractReference, ...]
    execution_health_refs: tuple[ContractReference, ...]
    learning_state: LearningPipelineState
    safety_ref: ContractReference
    readiness_ref: ContractReference
    unknowns: tuple[str, ...]
    limitations: tuple[str, ...]
    as_of: datetime
    created_at: datetime
    valid_until: datetime
    content_sha256: str
    contract_id: str = field(default="C-054", init=False)
    schema_version: str = field(default=CONTRACT_SCHEMA_VERSION, init=False)

    def __post_init__(self) -> None:
        _uuid("snapshot_id", self.snapshot_id)
        _enum("status", self.status, AwarenessStatus)
        _references(
            "data_health_refs",
            self.data_health_refs,
            allowed={"C-002", "C-003"},
            empty=False,
        )
        _references(
            "market_regime_refs",
            self.market_regime_refs,
            allowed={"C-005"},
            empty=False,
        )
        _references(
            "agent_performance_refs", self.agent_performance_refs, allowed={"C-052"}
        )
        _references(
            "strategy_performance_refs",
            self.strategy_performance_refs,
            allowed={"C-053"},
        )
        _references(
            "validation_refs",
            self.validation_refs,
            allowed={"C-027", "C-028", "C-029", "C-030", "C-031"},
        )
        _references("drift_refs", self.drift_refs, allowed={"C-055"})
        _references(
            "portfolio_risk_refs",
            self.portfolio_risk_refs,
            allowed={"C-032", "C-033", "C-034", "C-035"},
            empty=False,
        )
        _references(
            "execution_health_refs",
            self.execution_health_refs,
            allowed={"C-095", "C-096"},
            empty=False,
        )
        _enum("learning_state", self.learning_state, LearningPipelineState)
        _reference("safety_ref", self.safety_ref, "C-058")
        _reference("readiness_ref", self.readiness_ref, "C-059")
        unknowns = _text_tuple("unknowns", self.unknowns)
        limitations = _text_tuple("limitations", self.limitations)
        as_of = _time("as_of", self.as_of)
        created = _time("created_at", self.created_at)
        valid_until = _time("valid_until", self.valid_until)
        _ordered("as_of", as_of, "created_at", created)
        _ordered("created_at", created, "valid_until", valid_until)
        if created == valid_until:
            raise LearningContractError("awareness validity window must be positive.")
        object.__setattr__(self, "as_of", as_of)
        object.__setattr__(self, "created_at", created)
        object.__setattr__(self, "valid_until", valid_until)
        _digest("content_sha256", self.content_sha256)
        if self.status is AwarenessStatus.READY and (unknowns or limitations):
            raise LearningContractError(
                "READY awareness cannot contain unknowns or unresolved limitations."
            )
        if self.status is not AwarenessStatus.READY and not (unknowns or limitations):
            raise LearningContractError(
                "non-READY awareness requires unknowns or limitations."
            )


@dataclass(frozen=True, slots=True)
class DriftAssessment:
    CONTRACT_ID: ClassVar[str] = "C-055"
    SCHEMA_VERSION: ClassVar[str] = CONTRACT_SCHEMA_VERSION

    assessment_id: UUID
    dimension: DriftDimension
    status: DriftStatus
    subject: VersionedArtifact
    baseline_start: datetime
    baseline_end: datetime
    current_start: datetime
    current_end: datetime
    method_version: VersionReference
    metrics: tuple[MetricObservation, ...]
    evidence: tuple[EvidenceReference, ...]
    uncertainty: Decimal
    limitations: tuple[str, ...]
    assessed_at: datetime
    content_sha256: str
    contract_id: str = field(default="C-055", init=False)
    schema_version: str = field(default=CONTRACT_SCHEMA_VERSION, init=False)

    def __post_init__(self) -> None:
        _uuid("assessment_id", self.assessment_id)
        _enum("dimension", self.dimension, DriftDimension)
        _enum("status", self.status, DriftStatus)
        if not isinstance(self.subject, VersionedArtifact):
            raise LearningContractError("subject must be a VersionedArtifact.")
        baseline_start, baseline_end = _normalize_window(
            self.baseline_start, self.baseline_end, prefix="baseline"
        )
        current_start, current_end = _normalize_window(
            self.current_start, self.current_end, prefix="current"
        )
        _ordered("baseline_end", baseline_end, "current_start", current_start)
        assessed = _time("assessed_at", self.assessed_at)
        _ordered("current_end", current_end, "assessed_at", assessed)
        object.__setattr__(self, "baseline_start", baseline_start)
        object.__setattr__(self, "baseline_end", baseline_end)
        object.__setattr__(self, "current_start", current_start)
        object.__setattr__(self, "current_end", current_end)
        object.__setattr__(self, "assessed_at", assessed)
        _version("method_version", self.method_version)
        metrics = _typed_tuple("metrics", self.metrics, MetricObservation, empty=False)
        _unique("metric names", tuple(item.name for item in metrics))
        _typed_tuple("evidence", self.evidence, EvidenceReference, empty=False)
        _ratio("uncertainty", self.uncertainty)
        limitations = _text_tuple("limitations", self.limitations)
        if self.status is DriftStatus.UNKNOWN and not limitations:
            raise LearningContractError("UNKNOWN drift requires limitations.")
        _digest("content_sha256", self.content_sha256)


@dataclass(frozen=True, slots=True)
class KnowledgeArtifact:
    CONTRACT_ID: ClassVar[str] = "C-056"
    SCHEMA_VERSION: ClassVar[str] = CONTRACT_SCHEMA_VERSION

    knowledge_id: UUID
    status: KnowledgeStatus
    title: str
    statement: str
    scope: EvaluationScope
    provenance_refs: tuple[ContractReference, ...]
    validation_refs: tuple[ContractReference, ...]
    evidence: tuple[EvidenceReference, ...]
    sample_size: int
    uncertainty: Decimal
    limitations: tuple[str, ...]
    created_at: datetime
    validated_at: datetime | None
    retired_at: datetime | None
    content_sha256: str
    contract_id: str = field(default="C-056", init=False)
    schema_version: str = field(default=CONTRACT_SCHEMA_VERSION, init=False)

    def __post_init__(self) -> None:
        _uuid("knowledge_id", self.knowledge_id)
        _enum("status", self.status, KnowledgeStatus)
        _text("title", self.title)
        _text("statement", self.statement, maximum=4096)
        if not isinstance(self.scope, EvaluationScope):
            raise LearningContractError("scope must be an EvaluationScope.")
        _references(
            "provenance_refs",
            self.provenance_refs,
            allowed={"C-045", "C-046", "C-047", "C-048", "C-049", "C-050", "C-090"},
            empty=False,
        )
        validations = _references(
            "validation_refs",
            self.validation_refs,
            allowed={"C-027", "C-028", "C-029", "C-030", "C-031", "C-050"},
        )
        _typed_tuple("evidence", self.evidence, EvidenceReference, empty=False)
        _positive_int("sample_size", self.sample_size)
        _ratio("uncertainty", self.uncertainty)
        _text_tuple("limitations", self.limitations, empty=False)
        created = _time("created_at", self.created_at)
        validated = (
            None
            if self.validated_at is None
            else _time("validated_at", self.validated_at)
        )
        retired = (
            None if self.retired_at is None else _time("retired_at", self.retired_at)
        )
        if validated is not None:
            _ordered("created_at", created, "validated_at", validated)
        if retired is not None:
            _ordered("created_at", created, "retired_at", retired)
        object.__setattr__(self, "created_at", created)
        object.__setattr__(self, "validated_at", validated)
        object.__setattr__(self, "retired_at", retired)
        _digest("content_sha256", self.content_sha256)
        if self.status is KnowledgeStatus.VALIDATED and (
            validated is None or not validations
        ):
            raise LearningContractError(
                "VALIDATED knowledge requires validation evidence and timestamp."
            )
        if self.status in {KnowledgeStatus.INVALIDATED, KnowledgeStatus.RETIRED}:
            if retired is None:
                raise LearningContractError(
                    "invalidated or retired knowledge requires retired_at."
                )


_GOVERNANCE_TRANSITIONS = {
    GovernanceDecisionType.APPROVE_FOR_SHADOW: (
        ArtifactLifecycle.VALIDATED,
        ArtifactLifecycle.APPROVED_FOR_SHADOW,
    ),
    GovernanceDecisionType.APPROVE_FOR_PAPER: (
        ArtifactLifecycle.APPROVED_FOR_SHADOW,
        ArtifactLifecycle.APPROVED_FOR_PAPER,
    ),
    GovernanceDecisionType.APPROVE_FOR_PRODUCTION: (
        ArtifactLifecycle.APPROVED_FOR_PAPER,
        ArtifactLifecycle.APPROVED_FOR_PRODUCTION,
    ),
    GovernanceDecisionType.ACTIVATE: (
        ArtifactLifecycle.APPROVED_FOR_PRODUCTION,
        ArtifactLifecycle.ACTIVE,
    ),
    GovernanceDecisionType.RETIRE: (
        ArtifactLifecycle.ACTIVE,
        ArtifactLifecycle.RETIRED,
    ),
    GovernanceDecisionType.ROLLBACK: (
        ArtifactLifecycle.ACTIVE,
        ArtifactLifecycle.ROLLED_BACK,
    ),
}


@dataclass(frozen=True, slots=True)
class GovernanceDecision:
    CONTRACT_ID: ClassVar[str] = "C-057"
    SCHEMA_VERSION: ClassVar[str] = CONTRACT_SCHEMA_VERSION

    decision_id: UUID
    decision: GovernanceDecisionType
    artifact: VersionedArtifact
    from_lifecycle: ArtifactLifecycle
    to_lifecycle: ArtifactLifecycle
    proposal_ref: ContractReference | None
    evidence_refs: tuple[ContractReference, ...]
    actor: GovernanceActorReference
    conditions: tuple[str, ...]
    audit_ref: ContractReference
    rollback_target: VersionedArtifact | None
    rationale: str
    decided_at: datetime
    effective_at: datetime
    content_sha256: str
    contract_id: str = field(default="C-057", init=False)
    schema_version: str = field(default=CONTRACT_SCHEMA_VERSION, init=False)

    def __post_init__(self) -> None:
        _uuid("decision_id", self.decision_id)
        _enum("decision", self.decision, GovernanceDecisionType)
        if not isinstance(self.artifact, VersionedArtifact):
            raise LearningContractError("artifact must be a VersionedArtifact.")
        _enum("from_lifecycle", self.from_lifecycle, ArtifactLifecycle)
        _enum("to_lifecycle", self.to_lifecycle, ArtifactLifecycle)
        _optional_reference("proposal_ref", self.proposal_ref, "C-051")
        _references(
            "evidence_refs",
            self.evidence_refs,
            allowed={"C-028", "C-030", "C-050", "C-051", "C-053", "C-055", "C-100"},
            empty=False,
        )
        if not isinstance(self.actor, GovernanceActorReference):
            raise LearningContractError("actor must be a GovernanceActorReference.")
        _text_tuple("conditions", self.conditions)
        _reference("audit_ref", self.audit_ref, "C-060")
        if self.rollback_target is not None and not isinstance(
            self.rollback_target, VersionedArtifact
        ):
            raise LearningContractError("rollback_target must be a VersionedArtifact.")
        _text("rationale", self.rationale, maximum=4096)
        decided = _time("decided_at", self.decided_at)
        effective = _time("effective_at", self.effective_at)
        _ordered("decided_at", decided, "effective_at", effective)
        object.__setattr__(self, "decided_at", decided)
        object.__setattr__(self, "effective_at", effective)
        _digest("content_sha256", self.content_sha256)

        if self.artifact.lifecycle is not self.from_lifecycle:
            raise LearningContractError("artifact lifecycle must match from_lifecycle.")
        if self.decision is GovernanceDecisionType.REJECT:
            if self.to_lifecycle is not ArtifactLifecycle.REJECTED:
                raise LearningContractError("REJECT must transition to REJECTED.")
            if self.from_lifecycle in {
                ArtifactLifecycle.REJECTED,
                ArtifactLifecycle.RETIRED,
                ArtifactLifecycle.ROLLED_BACK,
            }:
                raise LearningContractError(
                    "terminal artifact cannot be rejected again."
                )
        else:
            expected = _GOVERNANCE_TRANSITIONS[self.decision]
            if (self.from_lifecycle, self.to_lifecycle) != expected:
                raise LearningContractError(
                    "governance decision does not match the canonical transition."
                )
        if self.decision is GovernanceDecisionType.ROLLBACK:
            if self.rollback_target is None:
                raise LearningContractError("ROLLBACK requires a rollback target.")
            if self.rollback_target.lifecycle is not ArtifactLifecycle.ACTIVE:
                raise LearningContractError(
                    "rollback target must identify a known active version."
                )
        elif self.rollback_target is not None:
            raise LearningContractError(
                "rollback_target is allowed only for a ROLLBACK decision."
            )


@dataclass(frozen=True, slots=True)
class CounterfactualAnalysis:
    CONTRACT_ID: ClassVar[str] = "C-090"
    SCHEMA_VERSION: ClassVar[str] = CONTRACT_SCHEMA_VERSION

    analysis_id: UUID
    source_experience_ref: ContractReference
    scenario: str
    assumptions: tuple[str, ...]
    simulation_method: VersionReference
    metrics: tuple[MetricObservation, ...]
    evidence: tuple[EvidenceReference, ...]
    uncertainty: Decimal
    limitations: tuple[str, ...]
    evaluated_at: datetime
    content_sha256: str
    classification: CounterfactualClassification = field(
        default=CounterfactualClassification.HYPOTHETICAL, init=False
    )
    contract_id: str = field(default="C-090", init=False)
    schema_version: str = field(default=CONTRACT_SCHEMA_VERSION, init=False)

    def __post_init__(self) -> None:
        _uuid("analysis_id", self.analysis_id)
        _reference("source_experience_ref", self.source_experience_ref, "C-045")
        _text("scenario", self.scenario, maximum=4096)
        _text_tuple("assumptions", self.assumptions, empty=False)
        _version("simulation_method", self.simulation_method)
        metrics = _typed_tuple("metrics", self.metrics, MetricObservation, empty=False)
        _unique("metric names", tuple(item.name for item in metrics))
        _typed_tuple("evidence", self.evidence, EvidenceReference, empty=False)
        _ratio("uncertainty", self.uncertainty)
        _text_tuple("limitations", self.limitations, empty=False)
        object.__setattr__(
            self, "evaluated_at", _time("evaluated_at", self.evaluated_at)
        )
        _digest("content_sha256", self.content_sha256)


@dataclass(frozen=True, slots=True)
class ChampionChallengerRecord:
    CONTRACT_ID: ClassVar[str] = "C-100"
    SCHEMA_VERSION: ClassVar[str] = CONTRACT_SCHEMA_VERSION

    record_id: UUID
    champion: VersionedArtifact
    challenger: VersionedArtifact
    mode: EvaluationMode
    method_version: VersionReference
    dataset: VersionedArtifact
    scope: EvaluationScope
    metrics: tuple[MetricObservation, ...]
    outcome: ComparisonOutcome
    experiment_result_ref: ContractReference
    governance_refs: tuple[ContractReference, ...]
    evidence: tuple[EvidenceReference, ...]
    uncertainty: Decimal
    limitations: tuple[str, ...]
    challenger_has_live_effect: bool
    evaluated_at: datetime
    content_sha256: str
    contract_id: str = field(default="C-100", init=False)
    schema_version: str = field(default=CONTRACT_SCHEMA_VERSION, init=False)

    def __post_init__(self) -> None:
        _uuid("record_id", self.record_id)
        for name in ("champion", "challenger", "dataset"):
            if not isinstance(getattr(self, name), VersionedArtifact):
                raise LearningContractError(f"{name} must be a VersionedArtifact.")
        if self.champion.version == self.challenger.version:
            raise LearningContractError(
                "champion and challenger must be distinct versions."
            )
        _enum("mode", self.mode, EvaluationMode)
        _version("method_version", self.method_version)
        if not isinstance(self.scope, EvaluationScope):
            raise LearningContractError("scope must be an EvaluationScope.")
        metrics = _typed_tuple("metrics", self.metrics, MetricObservation, empty=False)
        _unique("metric names", tuple(item.name for item in metrics))
        _enum("outcome", self.outcome, ComparisonOutcome)
        _reference("experiment_result_ref", self.experiment_result_ref, "C-050")
        _references("governance_refs", self.governance_refs, allowed={"C-057"})
        _typed_tuple("evidence", self.evidence, EvidenceReference, empty=False)
        _ratio("uncertainty", self.uncertainty)
        _text_tuple("limitations", self.limitations, empty=False)
        _bool("challenger_has_live_effect", self.challenger_has_live_effect)
        if self.challenger_has_live_effect:
            raise LearningContractError(
                "challenger evaluation cannot affect live execution."
            )
        object.__setattr__(
            self, "evaluated_at", _time("evaluated_at", self.evaluated_at)
        )
        _digest("content_sha256", self.content_sha256)


CalibrationRecord = CalibrationResult


__all__ = [
    "AgentPerformance",
    "ArtifactLifecycle",
    "AwarenessStatus",
    "CalibrationRecord",
    "ChampionChallengerRecord",
    "ComparisonOutcome",
    "CONTRACT_SCHEMA_VERSION",
    "CounterfactualAnalysis",
    "CounterfactualClassification",
    "DriftAssessment",
    "DriftDimension",
    "DriftStatus",
    "EvaluationMode",
    "EvaluationScope",
    "EvidenceReference",
    "Experience",
    "ExperienceRecord",
    "ExperienceStatus",
    "Experiment",
    "ExperimentResult",
    "ExperimentResultStatus",
    "ExperimentStatus",
    "GovernanceActorReference",
    "GovernanceDecision",
    "GovernanceDecisionType",
    "Hypothesis",
    "KnowledgeArtifact",
    "KnowledgeStatus",
    "LearningContractError",
    "LearningInsight",
    "LearningObservation",
    "LearningPipelineState",
    "MetricObservation",
    "StrategyChangeProposal",
    "StrategyDecayState",
    "StrategyPerformance",
    "SystemAwarenessSnapshot",
    "VersionedArtifact",
]
