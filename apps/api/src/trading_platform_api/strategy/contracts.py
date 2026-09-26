from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from typing import TypeVar, cast
from uuid import UUID

from trading_platform_api.config import DeploymentEnvironment, OperatingMode

CONTRACT_SCHEMA_VERSION = "1"
_SHA256 = re.compile(r"[0-9a-f]{64}")
_T = TypeVar("_T")


class StrategyContractError(ValueError):
    """Raised when a strategy or signal contract is invalid."""


class StrategyLifecycle(StrEnum):
    RESEARCH = "RESEARCH"
    VALIDATED = "VALIDATED"
    APPROVED_FOR_SHADOW = "APPROVED_FOR_SHADOW"
    APPROVED_FOR_PAPER = "APPROVED_FOR_PAPER"
    APPROVED_FOR_PRODUCTION = "APPROVED_FOR_PRODUCTION"
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"
    REJECTED = "REJECTED"
    ROLLED_BACK = "ROLLED_BACK"


class ConditionOperator(StrEnum):
    EQUALS = "EQUALS"
    NOT_EQUALS = "NOT_EQUALS"
    GREATER_THAN = "GREATER_THAN"
    LESS_THAN = "LESS_THAN"
    GREATER_THAN_OR_EQUAL = "GREATER_THAN_OR_EQUAL"
    LESS_THAN_OR_EQUAL = "LESS_THAN_OR_EQUAL"
    IN_RANGE = "IN_RANGE"
    PERCENTILE_ABOVE = "PERCENTILE_ABOVE"
    PERCENTILE_BELOW = "PERCENTILE_BELOW"
    CROSSES_ABOVE = "CROSSES_ABOVE"
    CROSSES_BELOW = "CROSSES_BELOW"
    PRESENT = "PRESENT"
    ABSENT = "ABSENT"


class ConditionGroupOperator(StrEnum):
    AND = "AND"
    OR = "OR"
    NOT = "NOT"


class EligibilityState(StrEnum):
    ELIGIBLE = "ELIGIBLE"
    NOT_ELIGIBLE = "NOT_ELIGIBLE"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"


class SignalDirection(StrEnum):
    LONG = "LONG"
    SHORT = "SHORT"


class SetupState(StrEnum):
    NO_SETUP = "NO_SETUP"
    DEVELOPING = "DEVELOPING"
    SETUP_FORMING = "SETUP_FORMING"
    SETUP_CONFIRMED = "SETUP_CONFIRMED"
    INVALIDATED = "INVALIDATED"
    EXPIRED = "EXPIRED"


class SignalLifecycleState(StrEnum):
    DRAFT = "DRAFT"
    CANDIDATE = "CANDIDATE"
    QUALIFIED = "QUALIFIED"
    WATCH = "WATCH"
    REJECTED = "REJECTED"
    NO_TRADE = "NO_TRADE"
    EXPIRED = "EXPIRED"
    SUPERSEDED = "SUPERSEDED"


class QualificationStatus(StrEnum):
    QUALIFIED_HIGH_EVIDENCE = "QUALIFIED_HIGH_EVIDENCE"
    QUALIFIED = "QUALIFIED"
    WATCH = "WATCH"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
    CONFLICTED = "CONFLICTED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"


class RuleOutcome(StrEnum):
    PASSED = "PASSED"
    FAILED = "FAILED"
    NOT_EVALUATED = "NOT_EVALUATED"


class ValidationStatus(StrEnum):
    NOT_RUN = "NOT_RUN"
    RUNNING = "RUNNING"
    PASSED = "PASSED"
    FAILED = "FAILED"
    INCONCLUSIVE = "INCONCLUSIVE"
    STALE = "STALE"
    EXPIRED = "EXPIRED"


class EvidenceNodeType(StrEnum):
    EVIDENCE = "EVIDENCE"
    FINDING = "FINDING"
    STRATEGY_CONDITION = "STRATEGY_CONDITION"
    QUALIFICATION = "QUALIFICATION"


class EvidenceDependence(StrEnum):
    INDEPENDENT = "INDEPENDENT"
    PARTIALLY_DEPENDENT = "PARTIALLY_DEPENDENT"
    HIGHLY_CORRELATED = "HIGHLY_CORRELATED"


class NoTradeReason(StrEnum):
    MISSING_DATA = "MISSING_DATA"
    STALE_DATA = "STALE_DATA"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
    UNRESOLVED_CONFLICT = "UNRESOLVED_CONFLICT"
    STRATEGY_INELIGIBLE = "STRATEGY_INELIGIBLE"
    NO_SETUP = "NO_SETUP"
    SETUP_INVALIDATED = "SETUP_INVALIDATED"
    SETUP_EXPIRED = "SETUP_EXPIRED"
    SETUP_SUPERSEDED = "SETUP_SUPERSEDED"
    REGIME_MISMATCH = "REGIME_MISMATCH"
    EVENT_RISK = "EVENT_RISK"
    VALIDATION_MISSING = "VALIDATION_MISSING"
    VALIDATION_FAILED = "VALIDATION_FAILED"
    VALIDATION_INCONCLUSIVE = "VALIDATION_INCONCLUSIVE"
    VALIDATION_STALE = "VALIDATION_STALE"
    DUPLICATE_THESIS = "DUPLICATE_THESIS"
    SAFETY_UNAVAILABLE = "SAFETY_UNAVAILABLE"
    RISK_UNAVAILABLE = "RISK_UNAVAILABLE"


def _text(name: str, value: object) -> str:
    if not isinstance(value, str):
        raise StrategyContractError(f"{name} must be a string.")
    if not value.strip():
        raise StrategyContractError(f"{name} must not be blank.")
    if value != value.strip():
        raise StrategyContractError(f"{name} must not contain surrounding whitespace.")
    return value


def _optional_text(name: str, value: object) -> str | None:
    return None if value is None else _text(name, value)


def _uuid(name: str, value: object) -> UUID:
    if not isinstance(value, UUID):
        raise StrategyContractError(f"{name} must be a UUID.")
    return value


def _time(name: str, value: object) -> datetime:
    if not isinstance(value, datetime):
        raise StrategyContractError(f"{name} must be a datetime.")
    if value.tzinfo is None or value.utcoffset() is None:
        raise StrategyContractError(f"{name} must be timezone-aware.")
    return value.astimezone(UTC)


def _score(name: str, value: object) -> Decimal:
    if (
        not isinstance(value, Decimal)
        or isinstance(value, bool)
        or not value.is_finite()
    ):
        raise StrategyContractError(f"{name} must be a finite Decimal.")
    if not Decimal("0") <= value <= Decimal("1"):
        raise StrategyContractError(f"{name} must be between 0 and 1.")
    return value


def _tuple(name: str, value: object, *, empty: bool = True) -> tuple[object, ...]:
    if not isinstance(value, tuple):
        raise StrategyContractError(f"{name} must be a tuple.")
    if not empty and not value:
        raise StrategyContractError(f"{name} must not be empty.")
    return value


def _typed_tuple(
    name: str, value: object, kind: type[_T], *, empty: bool = True
) -> tuple[_T, ...]:
    values = _tuple(name, value, empty=empty)
    if not all(isinstance(item, kind) for item in values):
        raise StrategyContractError(f"{name} contains an invalid item type.")
    return cast(tuple[_T, ...], values)


def _unique(name: str, values: tuple[object, ...]) -> None:
    try:
        if len(set(values)) != len(values):
            raise StrategyContractError(f"{name} must not contain duplicates.")
    except TypeError as exc:
        raise StrategyContractError(f"{name} items must be hashable.") from exc


def _uuid_tuple(name: str, value: object, *, empty: bool = True) -> tuple[UUID, ...]:
    values = _tuple(name, value, empty=empty)
    result = tuple(_uuid(f"{name}[{i}]", item) for i, item in enumerate(values))
    _unique(name, result)
    return result


def _text_tuple(name: str, value: object, *, empty: bool = True) -> tuple[str, ...]:
    values = _tuple(name, value, empty=empty)
    result = tuple(_text(f"{name}[{i}]", item) for i, item in enumerate(values))
    _unique(name, result)
    return result


def _ordered(
    first_name: str, first: datetime, second_name: str, second: datetime
) -> None:
    if first > second:
        raise StrategyContractError(f"{first_name} must not be after {second_name}.")


def _digest(name: str, value: object) -> str:
    digest = _text(name, value)
    if _SHA256.fullmatch(digest) is None:
        raise StrategyContractError(f"{name} must be a lowercase SHA-256 digest.")
    return digest


@dataclass(frozen=True, slots=True)
class VersionReference:
    artifact_type: str
    artifact_id: UUID
    version: str
    content_sha256: str

    def __post_init__(self) -> None:
        _text("artifact_type", self.artifact_type)
        _uuid("artifact_id", self.artifact_id)
        _text("version", self.version)
        _digest("content_sha256", self.content_sha256)


@dataclass(frozen=True, slots=True)
class StrategyParameter:
    name: str
    value: str
    unit: str | None

    def __post_init__(self) -> None:
        _text("name", self.name)
        _text("value", self.value)
        _optional_text("unit", self.unit)


@dataclass(frozen=True, slots=True)
class StrategyCondition:
    condition_id: UUID
    feature_path: str
    operator: ConditionOperator
    expected_values: tuple[str, ...]
    definition_version: str

    def __post_init__(self) -> None:
        _uuid("condition_id", self.condition_id)
        _text("feature_path", self.feature_path)
        if not isinstance(self.operator, ConditionOperator):
            raise StrategyContractError("operator must be a ConditionOperator.")
        values = _text_tuple("expected_values", self.expected_values)
        if (
            self.operator not in {ConditionOperator.PRESENT, ConditionOperator.ABSENT}
            and not values
        ):
            raise StrategyContractError(
                "comparison condition requires expected_values."
            )
        if (
            self.operator in {ConditionOperator.PRESENT, ConditionOperator.ABSENT}
            and values
        ):
            raise StrategyContractError(
                "presence condition cannot contain expected_values."
            )
        _text("definition_version", self.definition_version)


@dataclass(frozen=True, slots=True)
class ConditionGroup:
    group_id: UUID
    operator: ConditionGroupOperator
    condition_ids: tuple[UUID, ...]

    def __post_init__(self) -> None:
        _uuid("group_id", self.group_id)
        if not isinstance(self.operator, ConditionGroupOperator):
            raise StrategyContractError("operator must be a ConditionGroupOperator.")
        conditions = _uuid_tuple("condition_ids", self.condition_ids, empty=False)
        if self.operator is ConditionGroupOperator.NOT and len(conditions) != 1:
            raise StrategyContractError("NOT group requires exactly one condition.")


@dataclass(frozen=True, slots=True)
class Strategy:
    strategy_id: UUID
    name: str
    description: str
    strategy_type: str
    created_at: datetime
    contract_id: str = field(default="C-020", init=False)
    schema_version: str = field(default=CONTRACT_SCHEMA_VERSION, init=False)

    def __post_init__(self) -> None:
        _uuid("strategy_id", self.strategy_id)
        _text("name", self.name)
        _text("description", self.description)
        _text("strategy_type", self.strategy_type)
        object.__setattr__(self, "created_at", _time("created_at", self.created_at))


@dataclass(frozen=True, slots=True)
class StrategyVersion:
    strategy_version_id: UUID
    strategy_id: UUID
    semantic_version: str
    lifecycle: StrategyLifecycle
    content_sha256: str
    parent_version_id: UUID | None
    parameters: tuple[StrategyParameter, ...]
    conditions: tuple[StrategyCondition, ...]
    condition_groups: tuple[ConditionGroup, ...]
    supported_assets: tuple[str, ...]
    supported_instruments: tuple[str, ...]
    supported_timeframes: tuple[str, ...]
    preferred_regimes: tuple[str, ...]
    acceptable_regimes: tuple[str, ...]
    incompatible_regimes: tuple[str, ...]
    required_evidence_categories: tuple[str, ...]
    entry_concept: str
    invalidation_concept: str
    target_concepts: tuple[str, ...]
    environments: tuple[DeploymentEnvironment, ...]
    operating_modes: tuple[OperatingMode, ...]
    provenance: tuple[VersionReference, ...]
    created_at: datetime
    contract_id: str = field(default="C-021", init=False)
    schema_version: str = field(default=CONTRACT_SCHEMA_VERSION, init=False)

    def __post_init__(self) -> None:
        _uuid("strategy_version_id", self.strategy_version_id)
        _uuid("strategy_id", self.strategy_id)
        _text("semantic_version", self.semantic_version)
        if not isinstance(self.lifecycle, StrategyLifecycle):
            raise StrategyContractError("lifecycle must be a StrategyLifecycle.")
        _digest("content_sha256", self.content_sha256)
        if self.parent_version_id is not None:
            _uuid("parent_version_id", self.parent_version_id)
            if self.parent_version_id == self.strategy_version_id:
                raise StrategyContractError("version cannot be its own parent.")
        parameters = _typed_tuple("parameters", self.parameters, StrategyParameter)
        _unique("parameter names", tuple(item.name for item in parameters))
        conditions = _typed_tuple(
            "conditions", self.conditions, StrategyCondition, empty=False
        )
        condition_ids = tuple(item.condition_id for item in conditions)
        _unique("condition identities", condition_ids)
        groups = _typed_tuple(
            "condition_groups", self.condition_groups, ConditionGroup, empty=False
        )
        _unique("condition group identities", tuple(item.group_id for item in groups))
        known = set(condition_ids)
        if any(
            condition_id not in known
            for group in groups
            for condition_id in group.condition_ids
        ):
            raise StrategyContractError(
                "condition group references an unknown condition."
            )
        for name in (
            "supported_assets",
            "supported_instruments",
            "supported_timeframes",
            "required_evidence_categories",
        ):
            _text_tuple(name, getattr(self, name), empty=False)
        preferred = _text_tuple("preferred_regimes", self.preferred_regimes)
        acceptable = _text_tuple("acceptable_regimes", self.acceptable_regimes)
        incompatible = _text_tuple("incompatible_regimes", self.incompatible_regimes)
        if (set(preferred) | set(acceptable)) & set(incompatible):
            raise StrategyContractError("compatible and incompatible regimes overlap.")
        _text("entry_concept", self.entry_concept)
        _text("invalidation_concept", self.invalidation_concept)
        _text_tuple("target_concepts", self.target_concepts)
        environments = _typed_tuple(
            "environments", self.environments, DeploymentEnvironment, empty=False
        )
        modes = _typed_tuple(
            "operating_modes", self.operating_modes, OperatingMode, empty=False
        )
        _unique("environments", environments)
        _unique("operating_modes", modes)
        provenance = _typed_tuple(
            "provenance", self.provenance, VersionReference, empty=False
        )
        _unique("provenance", provenance)
        object.__setattr__(self, "created_at", _time("created_at", self.created_at))


@dataclass(frozen=True, slots=True)
class StrategyEligibility:
    eligibility_id: UUID
    strategy_version_id: UUID
    market_context_id: UUID
    asset: str
    instrument_id: str
    timeframe: str
    state: EligibilityState
    reason_codes: tuple[str, ...]
    data_quality_report_id: UUID
    regime_id: UUID
    evaluated_at: datetime
    expires_at: datetime
    contract_id: str = field(default="C-022", init=False)
    schema_version: str = field(default=CONTRACT_SCHEMA_VERSION, init=False)

    def __post_init__(self) -> None:
        for name in (
            "eligibility_id",
            "strategy_version_id",
            "market_context_id",
            "data_quality_report_id",
            "regime_id",
        ):
            _uuid(name, getattr(self, name))
        _text("asset", self.asset)
        _text("instrument_id", self.instrument_id)
        _text("timeframe", self.timeframe)
        if not isinstance(self.state, EligibilityState):
            raise StrategyContractError("state must be an EligibilityState.")
        reasons = _text_tuple("reason_codes", self.reason_codes)
        if self.state is not EligibilityState.ELIGIBLE and not reasons:
            raise StrategyContractError("ineligible state requires reason_codes.")
        evaluated = _time("evaluated_at", self.evaluated_at)
        expires = _time("expires_at", self.expires_at)
        _ordered("evaluated_at", evaluated, "expires_at", expires)
        object.__setattr__(self, "evaluated_at", evaluated)
        object.__setattr__(self, "expires_at", expires)


@dataclass(frozen=True, slots=True)
class SignalConcept:
    concept_type: str
    description: str
    reference_values: tuple[str, ...]
    method: VersionReference

    def __post_init__(self) -> None:
        _text("concept_type", self.concept_type)
        _text("description", self.description)
        _text_tuple("reference_values", self.reference_values)
        if not isinstance(self.method, VersionReference):
            raise StrategyContractError("method must be a VersionReference.")


@dataclass(frozen=True, slots=True)
class SignalCandidate:
    candidate_id: UUID
    strategy_id: UUID
    strategy_version_id: UUID
    eligibility_id: UUID
    eligibility_state: EligibilityState
    market_context_id: UUID
    analysis_snapshot_id: UUID
    asset: str
    instrument_id: str
    timeframe: str
    direction: SignalDirection
    setup_state: SetupState
    entry_concept: SignalConcept
    invalidation_concept: SignalConcept
    target_concepts: tuple[SignalConcept, ...]
    supporting_evidence_ids: tuple[UUID, ...]
    contradictory_evidence_ids: tuple[UUID, ...]
    data_quality_report_id: UUID
    analytical_confidence: Decimal
    evidence_strength: Decimal
    lifecycle: SignalLifecycleState
    created_at: datetime
    expires_at: datetime
    contract_id: str = field(default="C-023", init=False)
    schema_version: str = field(default=CONTRACT_SCHEMA_VERSION, init=False)

    def __post_init__(self) -> None:
        for name in (
            "candidate_id",
            "strategy_id",
            "strategy_version_id",
            "eligibility_id",
            "market_context_id",
            "analysis_snapshot_id",
            "data_quality_report_id",
        ):
            _uuid(name, getattr(self, name))
        if self.eligibility_state is not EligibilityState.ELIGIBLE:
            raise StrategyContractError("candidate requires ELIGIBLE strategy state.")
        for name in ("asset", "instrument_id", "timeframe"):
            _text(name, getattr(self, name))
        if not isinstance(self.direction, SignalDirection):
            raise StrategyContractError("direction must be a SignalDirection.")
        if self.setup_state not in {
            SetupState.DEVELOPING,
            SetupState.SETUP_FORMING,
            SetupState.SETUP_CONFIRMED,
        }:
            raise StrategyContractError("candidate setup_state is not active.")
        if not isinstance(self.entry_concept, SignalConcept) or not isinstance(
            self.invalidation_concept, SignalConcept
        ):
            raise StrategyContractError(
                "entry/invalidation concepts have invalid types."
            )
        _typed_tuple("target_concepts", self.target_concepts, SignalConcept)
        _uuid_tuple(
            "supporting_evidence_ids", self.supporting_evidence_ids, empty=False
        )
        _uuid_tuple("contradictory_evidence_ids", self.contradictory_evidence_ids)
        _score("analytical_confidence", self.analytical_confidence)
        _score("evidence_strength", self.evidence_strength)
        if self.lifecycle is not SignalLifecycleState.CANDIDATE:
            raise StrategyContractError("SignalCandidate lifecycle must be CANDIDATE.")
        created = _time("created_at", self.created_at)
        expires = _time("expires_at", self.expires_at)
        _ordered("created_at", created, "expires_at", expires)
        object.__setattr__(self, "created_at", created)
        object.__setattr__(self, "expires_at", expires)


@dataclass(frozen=True, slots=True)
class EvidenceGraphNode:
    node_id: UUID
    node_type: EvidenceNodeType
    referenced_contract_id: str
    referenced_entity_id: UUID
    referenced_version: str
    dependence: EvidenceDependence

    def __post_init__(self) -> None:
        _uuid("node_id", self.node_id)
        if not isinstance(self.node_type, EvidenceNodeType):
            raise StrategyContractError("node_type must be an EvidenceNodeType.")
        contract = _text("referenced_contract_id", self.referenced_contract_id)
        if re.fullmatch(r"C-[0-9]{3}", contract) is None:
            raise StrategyContractError("referenced_contract_id must match C-###.")
        _uuid("referenced_entity_id", self.referenced_entity_id)
        _text("referenced_version", self.referenced_version)
        if not isinstance(self.dependence, EvidenceDependence):
            raise StrategyContractError("dependence must be an EvidenceDependence.")


@dataclass(frozen=True, slots=True)
class EvidenceGraphEdge:
    source_node_id: UUID
    target_node_id: UUID
    relationship: str

    def __post_init__(self) -> None:
        _uuid("source_node_id", self.source_node_id)
        _uuid("target_node_id", self.target_node_id)
        if self.source_node_id == self.target_node_id:
            raise StrategyContractError("evidence edge cannot reference itself.")
        _text("relationship", self.relationship)


@dataclass(frozen=True, slots=True)
class EvidenceGraph:
    nodes: tuple[EvidenceGraphNode, ...]
    edges: tuple[EvidenceGraphEdge, ...]

    def __post_init__(self) -> None:
        nodes = _typed_tuple("nodes", self.nodes, EvidenceGraphNode, empty=False)
        edges = _typed_tuple("edges", self.edges, EvidenceGraphEdge, empty=False)
        node_ids = tuple(node.node_id for node in nodes)
        _unique("node identities", node_ids)
        _unique(
            "evidence edges",
            tuple((e.source_node_id, e.target_node_id, e.relationship) for e in edges),
        )
        known = set(node_ids)
        if any(
            e.source_node_id not in known or e.target_node_id not in known
            for e in edges
        ):
            raise StrategyContractError("evidence edge references an unknown node.")
        node_types = {node.node_id: node.node_type for node in nodes}
        allowed_edges = {
            (EvidenceNodeType.EVIDENCE, EvidenceNodeType.FINDING),
            (EvidenceNodeType.FINDING, EvidenceNodeType.STRATEGY_CONDITION),
            (
                EvidenceNodeType.STRATEGY_CONDITION,
                EvidenceNodeType.QUALIFICATION,
            ),
        }
        if any(
            (node_types[edge.source_node_id], node_types[edge.target_node_id])
            not in allowed_edges
            for edge in edges
        ):
            raise StrategyContractError(
                "evidence edge violates canonical lineage order."
            )
        adjacency: dict[UUID, list[UUID]] = {node_id: [] for node_id in node_ids}
        for edge in edges:
            adjacency[edge.source_node_id].append(edge.target_node_id)
        visiting: set[UUID] = set()
        visited: set[UUID] = set()

        def visit(node_id: UUID) -> None:
            if node_id in visiting:
                raise StrategyContractError("evidence graph must be acyclic.")
            if node_id in visited:
                return
            visiting.add(node_id)
            for target in adjacency[node_id]:
                visit(target)
            visiting.remove(node_id)
            visited.add(node_id)

        for node_id in node_ids:
            visit(node_id)
        present_types = {node.node_type for node in nodes}
        if present_types != set(EvidenceNodeType):
            raise StrategyContractError(
                "evidence graph must contain every required node type."
            )


@dataclass(frozen=True, slots=True)
class SignalEvidencePackage:
    package_id: UUID
    candidate_id: UUID
    strategy_version_id: UUID
    market_context_id: UUID
    graph: EvidenceGraph
    supporting_evidence_ids: tuple[UUID, ...]
    contradictory_evidence_ids: tuple[UUID, ...]
    created_at: datetime
    expires_at: datetime
    content_sha256: str
    contract_id: str = field(default="C-024", init=False)
    schema_version: str = field(default=CONTRACT_SCHEMA_VERSION, init=False)

    def __post_init__(self) -> None:
        for name in (
            "package_id",
            "candidate_id",
            "strategy_version_id",
            "market_context_id",
        ):
            _uuid(name, getattr(self, name))
        if not isinstance(self.graph, EvidenceGraph):
            raise StrategyContractError("graph must be an EvidenceGraph.")
        _uuid_tuple(
            "supporting_evidence_ids", self.supporting_evidence_ids, empty=False
        )
        _uuid_tuple("contradictory_evidence_ids", self.contradictory_evidence_ids)
        created = _time("created_at", self.created_at)
        expires = _time("expires_at", self.expires_at)
        _ordered("created_at", created, "expires_at", expires)
        _digest("content_sha256", self.content_sha256)
        object.__setattr__(self, "created_at", created)
        object.__setattr__(self, "expires_at", expires)


@dataclass(frozen=True, slots=True)
class QualificationRuleResult:
    rule_id: str
    outcome: RuleOutcome
    reason: str

    def __post_init__(self) -> None:
        _text("rule_id", self.rule_id)
        if not isinstance(self.outcome, RuleOutcome):
            raise StrategyContractError("outcome must be a RuleOutcome.")
        _text("reason", self.reason)


@dataclass(frozen=True, slots=True)
class ValidationReference:
    validation_result_id: UUID
    strategy_version_id: UUID
    status: ValidationStatus
    methodology_version: str
    valid_until: datetime
    contract_id: str = field(default="C-028", init=False)

    def __post_init__(self) -> None:
        _uuid("validation_result_id", self.validation_result_id)
        _uuid("strategy_version_id", self.strategy_version_id)
        if not isinstance(self.status, ValidationStatus):
            raise StrategyContractError("status must be a ValidationStatus.")
        _text("methodology_version", self.methodology_version)
        object.__setattr__(self, "valid_until", _time("valid_until", self.valid_until))


@dataclass(frozen=True, slots=True)
class HistoricalPerformanceReference:
    validation_result_id: UUID
    strategy_version_id: UUID
    asset: str
    timeframe: str
    regime: str
    sample_size: int
    test_period_start: datetime
    test_period_end: datetime
    methodology_version: str
    cost_assumptions: str
    slippage_assumptions: str

    def __post_init__(self) -> None:
        _uuid("validation_result_id", self.validation_result_id)
        _uuid("strategy_version_id", self.strategy_version_id)
        for name in (
            "asset",
            "timeframe",
            "regime",
            "methodology_version",
            "cost_assumptions",
            "slippage_assumptions",
        ):
            _text(name, getattr(self, name))
        if (
            not isinstance(self.sample_size, int)
            or isinstance(self.sample_size, bool)
            or self.sample_size < 0
        ):
            raise StrategyContractError("sample_size must be a non-negative integer.")
        start = _time("test_period_start", self.test_period_start)
        end = _time("test_period_end", self.test_period_end)
        _ordered("test_period_start", start, "test_period_end", end)
        object.__setattr__(self, "test_period_start", start)
        object.__setattr__(self, "test_period_end", end)


@dataclass(frozen=True, slots=True)
class SignalQualification:
    qualification_id: UUID
    candidate_id: UUID
    evidence_package_id: UUID
    strategy_version_id: UUID
    status: QualificationStatus
    rule_set: VersionReference
    rule_results: tuple[QualificationRuleResult, ...]
    evidence_fresh: bool
    data_quality_acceptable: bool
    regime_compatible: bool
    conflicts_resolved: bool
    validation: ValidationReference | None
    historical_performance: HistoricalPerformanceReference | None
    evaluated_at: datetime
    expires_at: datetime
    contract_id: str = field(default="C-025", init=False)
    schema_version: str = field(default=CONTRACT_SCHEMA_VERSION, init=False)

    def __post_init__(self) -> None:
        for name in (
            "qualification_id",
            "candidate_id",
            "evidence_package_id",
            "strategy_version_id",
        ):
            _uuid(name, getattr(self, name))
        if not isinstance(self.status, QualificationStatus):
            raise StrategyContractError("status must be a QualificationStatus.")
        if not isinstance(self.rule_set, VersionReference):
            raise StrategyContractError("rule_set must be a VersionReference.")
        results = _typed_tuple(
            "rule_results", self.rule_results, QualificationRuleResult, empty=False
        )
        _unique(
            "qualification rule identities", tuple(item.rule_id for item in results)
        )
        for name in (
            "evidence_fresh",
            "data_quality_acceptable",
            "regime_compatible",
            "conflicts_resolved",
        ):
            if not isinstance(getattr(self, name), bool):
                raise StrategyContractError(f"{name} must be a bool.")
        if self.validation is not None:
            if not isinstance(self.validation, ValidationReference):
                raise StrategyContractError("validation has an invalid type.")
            if self.validation.strategy_version_id != self.strategy_version_id:
                raise StrategyContractError("validation strategy version mismatch.")
        if self.historical_performance is not None:
            if not isinstance(
                self.historical_performance, HistoricalPerformanceReference
            ):
                raise StrategyContractError(
                    "historical_performance has an invalid type."
                )
            if (
                self.historical_performance.strategy_version_id
                != self.strategy_version_id
            ):
                raise StrategyContractError(
                    "historical performance strategy version mismatch."
                )
        evaluated = _time("evaluated_at", self.evaluated_at)
        expires = _time("expires_at", self.expires_at)
        _ordered("evaluated_at", evaluated, "expires_at", expires)
        if self.status in {
            QualificationStatus.QUALIFIED,
            QualificationStatus.QUALIFIED_HIGH_EVIDENCE,
        }:
            if not all(
                (
                    self.evidence_fresh,
                    self.data_quality_acceptable,
                    self.regime_compatible,
                    self.conflicts_resolved,
                )
            ):
                raise StrategyContractError(
                    "qualified status requires all contract gates."
                )
            if any(result.outcome is not RuleOutcome.PASSED for result in results):
                raise StrategyContractError(
                    "qualified status requires passed rule results."
                )
        object.__setattr__(self, "evaluated_at", evaluated)
        object.__setattr__(self, "expires_at", expires)


@dataclass(frozen=True, slots=True)
class NoTradeDecision:
    decision_id: UUID
    market_context_id: UUID
    candidate_id: UUID | None
    strategy_version_id: UUID | None
    reasons: tuple[NoTradeReason, ...]
    explanation: str
    blocking_evidence_ids: tuple[UUID, ...]
    conflict_ids: tuple[UUID, ...]
    uncertainty_ids: tuple[UUID, ...]
    data_quality_report_id: UUID | None
    provenance: tuple[VersionReference, ...]
    correlation_id: str
    lifecycle: SignalLifecycleState
    decided_at: datetime
    expires_at: datetime
    contract_id: str = field(default="C-026", init=False)
    schema_version: str = field(default=CONTRACT_SCHEMA_VERSION, init=False)

    def __post_init__(self) -> None:
        _uuid("decision_id", self.decision_id)
        _uuid("market_context_id", self.market_context_id)
        if self.candidate_id is not None:
            _uuid("candidate_id", self.candidate_id)
        if self.strategy_version_id is not None:
            _uuid("strategy_version_id", self.strategy_version_id)
        reasons = _typed_tuple("reasons", self.reasons, NoTradeReason, empty=False)
        _unique("reasons", reasons)
        _text("explanation", self.explanation)
        for name in ("blocking_evidence_ids", "conflict_ids", "uncertainty_ids"):
            _uuid_tuple(name, getattr(self, name))
        if self.data_quality_report_id is not None:
            _uuid("data_quality_report_id", self.data_quality_report_id)
        provenance = _typed_tuple(
            "provenance", self.provenance, VersionReference, empty=False
        )
        _unique("provenance", provenance)
        _text("correlation_id", self.correlation_id)
        if self.lifecycle is not SignalLifecycleState.NO_TRADE:
            raise StrategyContractError("NoTradeDecision lifecycle must be NO_TRADE.")
        decided = _time("decided_at", self.decided_at)
        expires = _time("expires_at", self.expires_at)
        _ordered("decided_at", decided, "expires_at", expires)
        object.__setattr__(self, "decided_at", decided)
        object.__setattr__(self, "expires_at", expires)


@dataclass(frozen=True, slots=True)
class SignalLineage:
    candidate_id: UUID
    candidate_strategy_version_id: UUID
    evidence_package_id: UUID
    package_candidate_id: UUID
    package_strategy_version_id: UUID
    qualification_id: UUID
    qualification_candidate_id: UUID
    qualification_package_id: UUID
    qualification_strategy_version_id: UUID

    def __post_init__(self) -> None:
        for name in (
            "candidate_id",
            "candidate_strategy_version_id",
            "evidence_package_id",
            "package_candidate_id",
            "package_strategy_version_id",
            "qualification_id",
            "qualification_candidate_id",
            "qualification_package_id",
            "qualification_strategy_version_id",
        ):
            _uuid(name, getattr(self, name))
        if (
            len(
                {
                    self.candidate_id,
                    self.package_candidate_id,
                    self.qualification_candidate_id,
                }
            )
            != 1
        ):
            raise StrategyContractError("candidate lineage mismatch.")
        if self.evidence_package_id != self.qualification_package_id:
            raise StrategyContractError("evidence package lineage mismatch.")
        if (
            len(
                {
                    self.candidate_strategy_version_id,
                    self.package_strategy_version_id,
                    self.qualification_strategy_version_id,
                }
            )
            != 1
        ):
            raise StrategyContractError("strategy version lineage mismatch.")


@dataclass(frozen=True, slots=True)
class Signal:
    signal_id: UUID
    lineage: SignalLineage
    strategy_id: UUID
    strategy_version_id: UUID
    parameter_set: VersionReference
    configuration: VersionReference
    validation: ValidationReference
    qualification_status: QualificationStatus
    market_context_id: UUID
    analysis_snapshot_id: UUID
    asset: str
    instrument_id: str
    timeframe: str
    direction: SignalDirection
    evidence_ids: tuple[UUID, ...]
    data_quality_report_id: UUID
    regime_id: UUID
    conflict_ids: tuple[UUID, ...]
    uncertainty_ids: tuple[UUID, ...]
    lifecycle: SignalLifecycleState
    created_at: datetime
    expires_at: datetime
    execution_authorized: bool = field(default=False, init=False)
    contract_id: str = field(default="C-070", init=False)
    schema_version: str = field(default=CONTRACT_SCHEMA_VERSION, init=False)

    def __post_init__(self) -> None:
        for name in (
            "signal_id",
            "strategy_id",
            "strategy_version_id",
            "market_context_id",
            "analysis_snapshot_id",
            "data_quality_report_id",
            "regime_id",
        ):
            _uuid(name, getattr(self, name))
        if not isinstance(self.lineage, SignalLineage):
            raise StrategyContractError("lineage must be a SignalLineage.")
        if self.lineage.candidate_strategy_version_id != self.strategy_version_id:
            raise StrategyContractError("Signal strategy version lineage mismatch.")
        for name in ("parameter_set", "configuration"):
            if not isinstance(getattr(self, name), VersionReference):
                raise StrategyContractError(f"{name} must be a VersionReference.")
        if not isinstance(self.validation, ValidationReference):
            raise StrategyContractError("validation must be a ValidationReference.")
        if self.validation.strategy_version_id != self.strategy_version_id:
            raise StrategyContractError("validation strategy version mismatch.")
        if self.validation.status is not ValidationStatus.PASSED:
            raise StrategyContractError("Signal requires PASSED validation.")
        if self.qualification_status not in {
            QualificationStatus.QUALIFIED,
            QualificationStatus.QUALIFIED_HIGH_EVIDENCE,
        }:
            raise StrategyContractError("Signal requires qualified status.")
        for name in ("asset", "instrument_id", "timeframe"):
            _text(name, getattr(self, name))
        if not isinstance(self.direction, SignalDirection):
            raise StrategyContractError("direction must be a SignalDirection.")
        _uuid_tuple("evidence_ids", self.evidence_ids, empty=False)
        _uuid_tuple("conflict_ids", self.conflict_ids)
        _uuid_tuple("uncertainty_ids", self.uncertainty_ids)
        if self.lifecycle is not SignalLifecycleState.QUALIFIED:
            raise StrategyContractError("Signal lifecycle must be QUALIFIED.")
        created = _time("created_at", self.created_at)
        expires = _time("expires_at", self.expires_at)
        _ordered("created_at", created, "expires_at", expires)
        if (
            self.validation.valid_until < created
            or self.validation.valid_until < expires
        ):
            raise StrategyContractError(
                "validation expires before Signal validity ends."
            )
        object.__setattr__(self, "created_at", created)
        object.__setattr__(self, "expires_at", expires)


__all__ = [
    "CONTRACT_SCHEMA_VERSION",
    "ConditionGroup",
    "ConditionGroupOperator",
    "ConditionOperator",
    "EligibilityState",
    "EvidenceDependence",
    "EvidenceGraph",
    "EvidenceGraphEdge",
    "EvidenceGraphNode",
    "EvidenceNodeType",
    "HistoricalPerformanceReference",
    "NoTradeDecision",
    "NoTradeReason",
    "QualificationRuleResult",
    "QualificationStatus",
    "RuleOutcome",
    "SetupState",
    "Signal",
    "SignalCandidate",
    "SignalConcept",
    "SignalDirection",
    "SignalEvidencePackage",
    "SignalLifecycleState",
    "SignalLineage",
    "SignalQualification",
    "Strategy",
    "StrategyCondition",
    "StrategyContractError",
    "StrategyEligibility",
    "StrategyLifecycle",
    "StrategyParameter",
    "StrategyVersion",
    "ValidationReference",
    "ValidationStatus",
    "VersionReference",
]
