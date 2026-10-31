from __future__ import annotations

from dataclasses import dataclass, field, fields
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, TypeVar, cast
from uuid import UUID, uuid5

from trading_platform_api.contracts.serialization import canonical_sha256
from trading_platform_api.strategy.contracts import (
    QualificationStatus,
    SignalLifecycleState,
    StrategyContractError,
    VersionReference,
)
from trading_platform_api.validation.contracts_v2 import (
    QualificationValidationResultV2,
    ValidationGateOutcomeV2,
    ValidationOutcomeV2,
)

STRATEGY_CONTRACT_SCHEMA_VERSION_V2 = "2"
_PACKAGE_NAMESPACE = UUID("b13d3889-2a7b-5e99-9c7f-0b179f63b8a1")
_T = TypeVar("_T")


def _text(name: str, value: object) -> str:
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise StrategyContractError(f"{name} must be a non-blank trimmed string.")
    return value


def _uuid(name: str, value: object) -> UUID:
    if not isinstance(value, UUID):
        raise StrategyContractError(f"{name} must be a UUID.")
    return value


def _time(name: str, value: object) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise StrategyContractError(f"{name} must be timezone-aware.")
    return value.astimezone(UTC)


def _ref(name: str, value: object, contract_id: str) -> VersionReference:
    if not isinstance(value, VersionReference) or value.artifact_type != contract_id:
        raise StrategyContractError(f"{name} must reference {contract_id}.")
    return value


def _refs(
    name: str, value: object, contract_id: str, *, empty: bool = True
) -> tuple[VersionReference, ...]:
    if not isinstance(value, tuple) or (not empty and not value):
        raise StrategyContractError(f"{name} must be a tuple with required items.")
    result = tuple(
        _ref(f"{name}[{i}]", item, contract_id) for i, item in enumerate(value)
    )
    if len({item.artifact_id for item in result}) != len(result):
        raise StrategyContractError(f"{name} must not contain duplicate identities.")
    return result


class EvidenceNodeTypeV2(StrEnum):
    EVIDENCE = "EVIDENCE"
    FINDING = "FINDING"
    STRATEGY_CONDITION = "STRATEGY_CONDITION"
    CANDIDATE = "CANDIDATE"


class EvidenceDependenceV2(StrEnum):
    INDEPENDENT = "INDEPENDENT"
    PARTIALLY_DEPENDENT = "PARTIALLY_DEPENDENT"
    HIGHLY_CORRELATED = "HIGHLY_CORRELATED"
    UNKNOWN = "UNKNOWN"


class NoTradeReasonV2(StrEnum):
    """C-026 schema-2 reason vocabulary; schema 1 remains frozen."""

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
    INVALID_PROVENANCE = "INVALID_PROVENANCE"


@dataclass(frozen=True, slots=True)
class EvidenceGraphNodeV2:
    node_id: UUID
    node_type: EvidenceNodeTypeV2
    reference: VersionReference
    dependence: EvidenceDependenceV2
    observed_at: datetime
    valid_until: datetime
    method: VersionReference

    def __post_init__(self) -> None:
        _uuid("node_id", self.node_id)
        if not isinstance(self.node_type, EvidenceNodeTypeV2):
            raise StrategyContractError("node_type must be EvidenceNodeTypeV2.")
        if not isinstance(self.reference, VersionReference):
            raise StrategyContractError("reference must be a VersionReference.")
        if not isinstance(self.dependence, EvidenceDependenceV2):
            raise StrategyContractError("dependence must be EvidenceDependenceV2.")
        observed = _time("observed_at", self.observed_at)
        expiry = _time("valid_until", self.valid_until)
        if observed >= expiry:
            raise StrategyContractError(
                "graph evidence expiry must follow observation time."
            )
        if not isinstance(self.method, VersionReference):
            raise StrategyContractError("method must be a VersionReference.")
        object.__setattr__(self, "observed_at", observed)
        object.__setattr__(self, "valid_until", expiry)


@dataclass(frozen=True, slots=True)
class EvidenceGraphEdgeV2:
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
class EvidenceGraphV2:
    nodes: tuple[EvidenceGraphNodeV2, ...]
    edges: tuple[EvidenceGraphEdgeV2, ...]

    def __post_init__(self) -> None:
        if not self.nodes or not self.edges:
            raise StrategyContractError("v2 graph requires nodes and edges.")
        if any(not isinstance(item, EvidenceGraphNodeV2) for item in self.nodes):
            raise StrategyContractError("nodes must contain EvidenceGraphNodeV2.")
        if any(not isinstance(item, EvidenceGraphEdgeV2) for item in self.edges):
            raise StrategyContractError("edges must contain EvidenceGraphEdgeV2.")
        if len(
            {
                (edge.source_node_id, edge.target_node_id, edge.relationship)
                for edge in self.edges
            }
        ) != len(self.edges):
            raise StrategyContractError("graph edges must be unique.")
        ids = tuple(item.node_id for item in self.nodes)
        if len(set(ids)) != len(ids):
            raise StrategyContractError("graph node identities must be unique.")
        by_id = {item.node_id: item.node_type for item in self.nodes}
        if any(
            e.source_node_id not in by_id or e.target_node_id not in by_id
            for e in self.edges
        ):
            raise StrategyContractError("graph edge references an unknown node.")
        allowed = {
            (EvidenceNodeTypeV2.EVIDENCE, EvidenceNodeTypeV2.FINDING),
            (EvidenceNodeTypeV2.FINDING, EvidenceNodeTypeV2.STRATEGY_CONDITION),
            (EvidenceNodeTypeV2.STRATEGY_CONDITION, EvidenceNodeTypeV2.CANDIDATE),
        }
        if any(
            (by_id[e.source_node_id], by_id[e.target_node_id]) not in allowed
            for e in self.edges
        ):
            raise StrategyContractError("v2 graph has an unsupported lifecycle edge.")
        candidates = [
            item.node_id
            for item in self.nodes
            if item.node_type is EvidenceNodeTypeV2.CANDIDATE
        ]
        if len(candidates) != 1 or any(
            e.source_node_id == candidates[0] for e in self.edges
        ):
            raise StrategyContractError(
                "v2 graph must terminate at exactly one candidate."
            )
        adjacency: dict[UUID, list[UUID]] = {node_id: [] for node_id in ids}
        for edge in self.edges:
            adjacency[edge.source_node_id].append(edge.target_node_id)
        visiting: set[UUID] = set()
        visited: set[UUID] = set()

        def walk(node_id: UUID) -> None:
            if node_id in visiting:
                raise StrategyContractError("evidence graph must be acyclic.")
            if node_id in visited:
                return
            visiting.add(node_id)
            for child in adjacency[node_id]:
                walk(child)
            visiting.remove(node_id)
            visited.add(node_id)

        for node_id in ids:
            walk(node_id)
        reverse: dict[UUID, list[UUID]] = {node_id: [] for node_id in ids}
        for edge in self.edges:
            reverse[edge.target_node_id].append(edge.source_node_id)
        reaches_candidate = {candidates[0]}
        pending = [candidates[0]]
        while pending:
            for parent in reverse[pending.pop()]:
                if parent not in reaches_candidate:
                    reaches_candidate.add(parent)
                    pending.append(parent)
        if reaches_candidate != set(ids):
            raise StrategyContractError(
                "every v2 evidence graph node must lead to the candidate."
            )
        type_edges = {
            (by_id[e.source_node_id], by_id[e.target_node_id]) for e in self.edges
        }
        if not all(
            pair in type_edges
            for pair in (
                (EvidenceNodeTypeV2.EVIDENCE, EvidenceNodeTypeV2.FINDING),
                (EvidenceNodeTypeV2.FINDING, EvidenceNodeTypeV2.STRATEGY_CONDITION),
                (EvidenceNodeTypeV2.STRATEGY_CONDITION, EvidenceNodeTypeV2.CANDIDATE),
            )
        ):
            raise StrategyContractError(
                "v2 graph requires an evidence-to-candidate path."
            )


@dataclass(frozen=True, slots=True)
class C093DependenceReferenceV2:
    assessment: VersionReference
    state: EvidenceDependenceV2

    def __post_init__(self) -> None:
        _ref("assessment", self.assessment, "C-093")
        if not isinstance(self.state, EvidenceDependenceV2):
            raise StrategyContractError("state must be EvidenceDependenceV2.")


def _package_identity_values(value: SignalEvidencePackageV2) -> dict[str, object]:
    return {
        item.name: getattr(value, item.name)
        for item in fields(value)
        if item.name not in {"package_id", "content_sha256"}
    }


@dataclass(frozen=True, slots=True)
class SignalEvidencePackageV2:
    package_id: UUID
    candidate: VersionReference
    strategy_version: VersionReference
    eligibility: VersionReference
    market_context: VersionReference
    analysis_snapshot: VersionReference
    data_quality_report: VersionReference
    candidate_valid_until: datetime
    market_context_valid_until: datetime
    analysis_snapshot_valid_until: datetime
    evidence_references: tuple[VersionReference, ...]
    confluence: VersionReference
    conflicts: tuple[VersionReference, ...]
    adversarial_assessment: VersionReference | None
    adversarial_assessment_required: bool
    uncertainties: tuple[VersionReference, ...]
    dependence: C093DependenceReferenceV2
    supporting_evidence: tuple[VersionReference, ...]
    contradictory_evidence: tuple[VersionReference, ...]
    graph: EvidenceGraphV2
    created_at: datetime
    expires_at: datetime
    content_sha256: str
    contract_id: str = field(default="C-024", init=False)
    schema_version: str = field(default=STRATEGY_CONTRACT_SCHEMA_VERSION_V2, init=False)

    def __post_init__(self) -> None:
        _uuid("package_id", self.package_id)
        required = (
            ("candidate", self.candidate, "C-023"),
            ("strategy_version", self.strategy_version, "C-021"),
            ("eligibility", self.eligibility, "C-022"),
            ("market_context", self.market_context, "C-006"),
            ("analysis_snapshot", self.analysis_snapshot, "C-007"),
            ("data_quality_report", self.data_quality_report, "C-003"),
            ("confluence", self.confluence, "C-009"),
        )
        for name, ref, contract in required:
            _ref(name, ref, contract)
        evidence = _refs(
            "evidence_references", self.evidence_references, "C-008", empty=False
        )
        supporting = tuple(item for item in self.supporting_evidence)
        contradictory = tuple(item for item in self.contradictory_evidence)
        if any(
            not isinstance(item, VersionReference) or item.artifact_type != "C-008"
            for item in (*supporting, *contradictory)
        ):
            raise StrategyContractError(
                "supporting and contradictory evidence must reference C-008."
            )
        if not supporting:
            raise StrategyContractError("supporting evidence must not be empty.")
        if any(
            item.artifact_id not in {ref.artifact_id for ref in evidence}
            for item in (*supporting, *contradictory)
        ):
            raise StrategyContractError(
                "evidence classifications must resolve through evidence_references."
            )
        _refs("conflicts", self.conflicts, "C-010")
        _refs("uncertainties", self.uncertainties, "C-069")
        if self.adversarial_assessment is not None:
            _ref("adversarial_assessment", self.adversarial_assessment, "C-019")
        if not isinstance(self.adversarial_assessment_required, bool):
            raise StrategyContractError(
                "adversarial_assessment_required must be a bool."
            )
        if self.adversarial_assessment_required and self.adversarial_assessment is None:
            raise StrategyContractError(
                "required C-019 adversarial assessment is missing."
            )
        if not isinstance(self.dependence, C093DependenceReferenceV2):
            raise StrategyContractError(
                "dependence must preserve a C-093 reference and state."
            )
        if not isinstance(self.graph, EvidenceGraphV2):
            raise StrategyContractError("graph must be EvidenceGraphV2.")
        c093_nodes = [
            node for node in self.graph.nodes if node.reference.artifact_type == "C-093"
        ]
        if any(
            node.reference != self.dependence.assessment
            or node.dependence is not self.dependence.state
            for node in c093_nodes
        ):
            raise StrategyContractError(
                "graph C-093 nodes must preserve the package dependence reference and state."
            )
        candidate_nodes = [
            n for n in self.graph.nodes if n.node_type is EvidenceNodeTypeV2.CANDIDATE
        ]
        if candidate_nodes[0].reference != self.candidate:
            raise StrategyContractError(
                "terminal graph candidate must match package candidate."
            )
        created, expires = (
            _time("created_at", self.created_at),
            _time("expires_at", self.expires_at),
        )
        if created >= expires:
            raise StrategyContractError("package expires_at must follow created_at.")
        source_expiries = tuple(
            _time(name, value)
            for name, value in (
                ("candidate_valid_until", self.candidate_valid_until),
                ("market_context_valid_until", self.market_context_valid_until),
                ("analysis_snapshot_valid_until", self.analysis_snapshot_valid_until),
            )
        )
        if any(created >= value or expires > value for value in source_expiries):
            raise StrategyContractError(
                "package freshness must be bounded by exact candidate, context and snapshot expiry."
            )
        if any(
            node.observed_at > created or node.valid_until < expires
            for node in self.graph.nodes
        ):
            raise StrategyContractError(
                "package freshness must be bounded by source-derived graph expiry."
            )
        if any(
            not isinstance(item, VersionReference)
            for item in (*self.supporting_evidence, *self.contradictory_evidence)
        ):
            raise StrategyContractError(
                "evidence classifications must be VersionReference tuples."
            )
        if not isinstance(self.content_sha256, str) or len(self.content_sha256) != 64:
            raise StrategyContractError(
                "content_sha256 must be a lowercase SHA-256 digest."
            )
        digest = canonical_sha256(_package_identity_values(self))
        if self.content_sha256 != digest or self.package_id != uuid5(
            _PACKAGE_NAMESPACE, digest
        ):
            raise StrategyContractError(
                "package ID/digest must be deterministic for exact content."
            )
        object.__setattr__(self, "created_at", created)
        object.__setattr__(self, "expires_at", expires)

    @classmethod
    def build(cls, **values: object) -> SignalEvidencePackageV2:
        values.pop("package_id", None)
        values.pop("content_sha256", None)
        provisional = object.__new__(cls)
        for item in fields(cls):
            if item.name in {"package_id", "content_sha256"}:
                continue
            if item.name == "contract_id":
                value: object = "C-024"
            elif item.name == "schema_version":
                value = STRATEGY_CONTRACT_SCHEMA_VERSION_V2
            else:
                value = values[item.name]
            object.__setattr__(provisional, item.name, value)
        digest = canonical_sha256(_package_identity_values(provisional))
        return cast(Any, cls)(
            package_id=uuid5(_PACKAGE_NAMESPACE, digest),
            content_sha256=digest,
            **values,
        )


@dataclass(frozen=True, slots=True)
class SignalQualificationV2:
    qualification_id: UUID
    candidate: VersionReference
    strategy_version: VersionReference
    evidence_package: VersionReference
    evidence_package_valid_until: datetime
    validation: QualificationValidationResultV2
    status: QualificationStatus
    evaluated_at: datetime
    expires_at: datetime
    contract_id: str = field(default="C-025", init=False)
    schema_version: str = field(default=STRATEGY_CONTRACT_SCHEMA_VERSION_V2, init=False)

    def __post_init__(self) -> None:
        _uuid("qualification_id", self.qualification_id)
        _ref("candidate", self.candidate, "C-023")
        _ref("strategy_version", self.strategy_version, "C-021")
        _ref("evidence_package", self.evidence_package, "C-024")
        if self.evidence_package.version != "2":
            raise StrategyContractError("C-025v2 requires a C-024 schema 2 reference.")
        if not isinstance(self.validation, QualificationValidationResultV2):
            raise StrategyContractError(
                "validation must be QualificationValidationResultV2."
            )
        if (
            self.validation.schema_version != "2"
            or self.validation.contract_id != "C-028"
        ):
            raise StrategyContractError("C-025v2 requires C-028 schema 2.")
        if self.validation.candidate_id != self.candidate.artifact_id:
            raise StrategyContractError("candidate/validation identity mismatch.")
        if self.validation.candidate_sha256 != self.candidate.content_sha256:
            raise StrategyContractError("candidate content digest mismatch.")
        if self.validation.strategy_version_id != self.strategy_version.artifact_id:
            raise StrategyContractError(
                "strategy version/validation identity mismatch."
            )
        if self.validation.evidence_package_id != self.evidence_package.artifact_id:
            raise StrategyContractError(
                "evidence package/validation identity mismatch."
            )
        if (
            self.validation.evidence_package_sha256
            != self.evidence_package.content_sha256
        ):
            raise StrategyContractError("evidence package digest mismatch.")
        if not isinstance(self.status, QualificationStatus):
            raise StrategyContractError("status must be QualificationStatus.")
        evaluated, expires = (
            _time("evaluated_at", self.evaluated_at),
            _time("expires_at", self.expires_at),
        )
        package_expiry = _time(
            "evidence_package_valid_until", self.evidence_package_valid_until
        )
        if evaluated >= expires:
            raise StrategyContractError("qualification expiry must follow evaluation.")
        if (
            evaluated >= package_expiry
            or evaluated >= self.validation.valid_until
            or self.validation.as_of > evaluated
        ):
            raise StrategyContractError(
                "qualification cannot consume stale or future validation/evidence."
            )
        if self.status in {
            QualificationStatus.QUALIFIED,
            QualificationStatus.QUALIFIED_HIGH_EVIDENCE,
        }:
            if self.validation.outcome is not ValidationOutcomeV2.PASS:
                raise StrategyContractError(
                    "qualified status requires authoritative validation PASS."
                )
            if self.validation.valid_until < expires or package_expiry < expires:
                raise StrategyContractError(
                    "qualified result cannot outlive required evidence."
                )
            if any(
                g.outcome is not ValidationGateOutcomeV2.PASS
                for g in self.validation.gates
            ):
                raise StrategyContractError(
                    "qualified status requires every mandatory gate to PASS."
                )
        object.__setattr__(self, "evaluated_at", evaluated)
        object.__setattr__(self, "expires_at", expires)
        object.__setattr__(self, "evidence_package_valid_until", package_expiry)


@dataclass(frozen=True, slots=True)
class NoTradeDecisionV2:
    """C-026 schema 2; identical decision shape with an additive reason code."""

    decision_id: UUID
    market_context_id: UUID
    candidate_id: UUID | None
    strategy_version_id: UUID | None
    reasons: tuple[NoTradeReasonV2, ...]
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
    schema_version: str = field(default=STRATEGY_CONTRACT_SCHEMA_VERSION_V2, init=False)

    def __post_init__(self) -> None:
        for name in ("decision_id", "market_context_id"):
            _uuid(name, getattr(self, name))
        for name in ("candidate_id", "strategy_version_id", "data_quality_report_id"):
            value = getattr(self, name)
            if value is not None:
                _uuid(name, value)
        if not isinstance(self.reasons, tuple) or not self.reasons:
            raise StrategyContractError("reasons must be a non-empty tuple.")
        if not all(isinstance(item, NoTradeReasonV2) for item in self.reasons):
            raise StrategyContractError("reasons must contain NoTradeReasonV2 values.")
        if len(set(self.reasons)) != len(self.reasons):
            raise StrategyContractError("reasons must not contain duplicates.")
        _text("explanation", self.explanation)
        for name in ("blocking_evidence_ids", "conflict_ids", "uncertainty_ids"):
            values = getattr(self, name)
            if not isinstance(values, tuple):
                raise StrategyContractError(f"{name} must be a tuple.")
            if not all(isinstance(value, UUID) for value in values):
                raise StrategyContractError(f"{name} must contain UUID values.")
            if len(set(values)) != len(values):
                raise StrategyContractError(f"{name} must not contain duplicates.")
        if not isinstance(self.provenance, tuple) or not self.provenance:
            raise StrategyContractError("provenance must be a non-empty tuple.")
        if not all(isinstance(item, VersionReference) for item in self.provenance):
            raise StrategyContractError(
                "provenance must contain VersionReference values."
            )
        if len(set(self.provenance)) != len(self.provenance):
            raise StrategyContractError(
                "provenance must not contain duplicate identities."
            )
        _text("correlation_id", self.correlation_id)
        if self.lifecycle is not SignalLifecycleState.NO_TRADE:
            raise StrategyContractError("NoTradeDecisionV2 lifecycle must be NO_TRADE.")
        decided = _time("decided_at", self.decided_at)
        expires = _time("expires_at", self.expires_at)
        if decided > expires:
            raise StrategyContractError("decided_at must not be after expires_at.")
        object.__setattr__(self, "decided_at", decided)
        object.__setattr__(self, "expires_at", expires)


__all__ = [
    "C093DependenceReferenceV2",
    "EvidenceDependenceV2",
    "EvidenceGraphEdgeV2",
    "EvidenceGraphNodeV2",
    "EvidenceGraphV2",
    "EvidenceNodeTypeV2",
    "NoTradeDecisionV2",
    "NoTradeReasonV2",
    "SignalEvidencePackageV2",
    "SignalQualificationV2",
    "STRATEGY_CONTRACT_SCHEMA_VERSION_V2",
]
