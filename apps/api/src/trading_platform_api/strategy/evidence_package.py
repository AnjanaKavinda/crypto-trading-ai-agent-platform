"""Fail-closed C-024 schema-2 evidence-package construction for Spot research."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Mapping, NoReturn, TypedDict, cast
from uuid import NAMESPACE_URL, UUID, uuid5

from trading_platform_api.analysis.contracts import (
    VersionReference as AnalysisReference,
)
from trading_platform_api.analysis.spot_meta_analysis import AgentIndependenceReport
from trading_platform_api.analysis.versioned_contracts import EvidenceItemV2
from trading_platform_api.analysis.versioned_contracts_v4 import (
    AnalysisOutputReferenceV4,
    AnalysisSnapshotV4,
    ConfluenceAssessmentV3,
    ResolvedSpotOHLCVBindingV4,
    resolve_analysis_snapshot_v4,
)
from trading_platform_api.analysis.versioned_contracts_v5 import (
    MarketContextV5,
    validate_market_context_v5,
)
from trading_platform_api.contracts.serialization import canonical_sha256
from trading_platform_api.strategy.condition_evaluator import (
    ConditionTruth,
    SpotConditionContext,
    StrategyConditionEvaluation,
)
from trading_platform_api.strategy.contracts import (
    EligibilityState,
    SignalCandidate,
    StrategyEligibility,
    VersionReference,
)
from trading_platform_api.strategy.contracts_v2 import (
    C093DependenceReferenceV2,
    EvidenceDependenceV2,
    EvidenceGraphEdgeV2,
    EvidenceGraphNodeV2,
    EvidenceGraphV2,
    EvidenceNodeTypeV2,
    SignalEvidencePackageV2,
)
from trading_platform_api.strategy.eligibility import StrategyEligibilityEvaluation
from trading_platform_api.strategy.registry import (
    ResolvedStrategyVersion,
    strategy_version_content_sha256,
)
from trading_platform_api.strategy.setup_detection import (
    SetupDetectionOutcome,
    evaluate_strategy_setup,
)

_GRAPH_NAMESPACE = UUID("6d6de912-8964-50db-aaef-184ef3e7ae0c")


class EvidencePackageStatus(StrEnum):
    PACKAGE_READY = "PACKAGE_READY"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
    INVALID_PROVENANCE = "INVALID_PROVENANCE"
    STALE_INPUT = "STALE_INPUT"


@dataclass(frozen=True, slots=True)
class EvidencePackageEvaluation:
    status: EvidencePackageStatus
    reason_codes: tuple[str, ...]
    package: SignalEvidencePackageV2 | None

    def __post_init__(self) -> None:
        if type(self.status) is not EvidencePackageStatus:
            raise ValueError("status must be an EvidencePackageStatus")
        if type(self.reason_codes) is not tuple:
            raise ValueError("reason_codes must be a tuple")
        if self.status is EvidencePackageStatus.PACKAGE_READY:
            if self.package is None or self.reason_codes:
                raise ValueError("ready result requires a package and no reasons")
        elif self.package is not None or not self.reason_codes:
            raise ValueError("failed result requires reasons and no package")


@dataclass(frozen=True, slots=True)
class _Failure(Exception):
    status: EvidencePackageStatus
    reason: str


class _ResolvedReferences(TypedDict):
    candidate: VersionReference
    strategy: VersionReference
    eligibility: VersionReference
    context: VersionReference
    manifest: VersionReference
    quality: VersionReference
    evidence: dict[UUID, VersionReference]
    confluence: VersionReference
    conflicts: tuple[VersionReference, ...]
    adversarial: VersionReference
    uncertainties: tuple[VersionReference, ...]
    dependence: C093DependenceReferenceV2


def build_signal_evidence_package_v2(
    *,
    candidate: SignalCandidate | None,
    strategy: ResolvedStrategyVersion | None,
    condition_context: SpotConditionContext | None,
    condition_evaluation: StrategyConditionEvaluation | None,
    eligibility_evaluation: StrategyEligibilityEvaluation | None,
    market_context: MarketContextV5 | None,
    manifest: AnalysisSnapshotV4 | None,
    resolved_bindings: tuple[ResolvedSpotOHLCVBindingV4, ...] | None,
    evidence: Mapping[UUID, EvidenceItemV2] | None,
    independence_report: AgentIndependenceReport | None,
    supported_independence_reports: tuple[AnalysisOutputReferenceV4, ...] | None,
    supported_adversarial_versions: tuple[AnalysisReference, ...] | None,
    now: datetime,
) -> EvidencePackageEvaluation:
    """Build C-024v2 only when the exact #82 candidate and its Spot graph resolve.

    The C-023 zero-valued confidence fields are identity-bound as part of the
    candidate but are never read as scores or evidence.
    """

    if (
        type(candidate) is not SignalCandidate
        or type(strategy) is not ResolvedStrategyVersion
        or type(condition_context) is not SpotConditionContext
        or type(condition_evaluation) is not StrategyConditionEvaluation
        or type(eligibility_evaluation) is not StrategyEligibilityEvaluation
        or type(market_context) is not MarketContextV5
        or type(manifest) is not AnalysisSnapshotV4
        or type(resolved_bindings) is not tuple
        or not isinstance(evidence, Mapping)
        or type(independence_report) is not AgentIndependenceReport
        or type(supported_independence_reports) is not tuple
        or type(supported_adversarial_versions) is not tuple
    ):
        return EvidencePackageEvaluation(
            EvidencePackageStatus.INSUFFICIENT_EVIDENCE,
            ("REQUIRED_INPUT_MISSING",),
            None,
        )
    try:
        package = _build(
            candidate=cast(SignalCandidate, candidate),
            strategy=cast(ResolvedStrategyVersion, strategy),
            condition_context=cast(SpotConditionContext, condition_context),
            condition_evaluation=cast(
                StrategyConditionEvaluation, condition_evaluation
            ),
            eligibility_evaluation=cast(
                StrategyEligibilityEvaluation, eligibility_evaluation
            ),
            market_context=cast(MarketContextV5, market_context),
            manifest=cast(AnalysisSnapshotV4, manifest),
            resolved_bindings=cast(
                tuple[ResolvedSpotOHLCVBindingV4, ...], resolved_bindings
            ),
            evidence=cast(Mapping[UUID, EvidenceItemV2], evidence),
            independence_report=cast(AgentIndependenceReport, independence_report),
            supported_independence_reports=cast(
                tuple[AnalysisOutputReferenceV4, ...], supported_independence_reports
            ),
            supported_adversarial_versions=cast(
                tuple[AnalysisReference, ...], supported_adversarial_versions
            ),
            now=now,
        )
    except _Failure as failure:
        return EvidencePackageEvaluation(failure.status, (failure.reason,), None)
    except (TypeError, ValueError, KeyError, AttributeError):
        return EvidencePackageEvaluation(
            EvidencePackageStatus.INVALID_PROVENANCE,
            ("PROVENANCE_RESOLUTION_FAILED",),
            None,
        )
    return EvidencePackageEvaluation(EvidencePackageStatus.PACKAGE_READY, (), package)


def _build(
    *,
    candidate: SignalCandidate,
    strategy: ResolvedStrategyVersion,
    condition_context: SpotConditionContext,
    condition_evaluation: StrategyConditionEvaluation,
    eligibility_evaluation: StrategyEligibilityEvaluation,
    market_context: MarketContextV5,
    manifest: AnalysisSnapshotV4,
    resolved_bindings: tuple[ResolvedSpotOHLCVBindingV4, ...],
    evidence: Mapping[UUID, EvidenceItemV2],
    independence_report: AgentIndependenceReport,
    supported_independence_reports: tuple[AnalysisOutputReferenceV4, ...],
    supported_adversarial_versions: tuple[AnalysisReference, ...],
    now: datetime,
) -> SignalEvidencePackageV2:
    at = _utc(now)
    eligibility = eligibility_evaluation.eligibility
    if type(eligibility) is not StrategyEligibility:
        _fail(EvidencePackageStatus.INSUFFICIENT_EVIDENCE, "C022_UNAVAILABLE")
    assert type(eligibility) is StrategyEligibility
    if eligibility_evaluation.state is not EligibilityState.ELIGIBLE:
        _fail(EvidencePackageStatus.INSUFFICIENT_EVIDENCE, "C022_NOT_ELIGIBLE")

    if candidate.expires_at <= at:
        _fail(EvidencePackageStatus.STALE_INPUT, "C023_EXPIRED")
    if eligibility.expires_at <= at:
        _fail(EvidencePackageStatus.STALE_INPUT, "C022_EXPIRED")
    if market_context.expires_at <= at:
        _fail(EvidencePackageStatus.STALE_INPUT, "C006_EXPIRED")
    if manifest.expires_at <= at:
        _fail(EvidencePackageStatus.STALE_INPUT, "C007_EXPIRED")
    if market_context.confluence.expires_at <= at:
        _fail(EvidencePackageStatus.STALE_INPUT, "C009_EXPIRED")
    if any(item.expires_at <= at for item in market_context.conflicts):
        _fail(EvidencePackageStatus.STALE_INPUT, "C010_EXPIRED")
    if market_context.adversarial.expires_at <= at:
        _fail(EvidencePackageStatus.STALE_INPUT, "C019_EXPIRED")
    if any(item.expires_at <= at for item in market_context.uncertainties):
        _fail(EvidencePackageStatus.STALE_INPUT, "C069_EXPIRED")
    if condition_evaluation.expires_at <= at or condition_context.expires_at <= at:
        _fail(EvidencePackageStatus.STALE_INPUT, "CONDITION_INPUT_EXPIRED")

    version = strategy.version
    if (
        candidate.created_at > at
        or eligibility.evaluated_at > at
        or market_context.as_of > at
        or manifest.created_at > at
        or condition_evaluation.evaluated_at > at
        or candidate.strategy_version_id != version.strategy_version_id
        or strategy_version_content_sha256(version) != version.content_sha256
        or candidate.entry_concept.method
        != VersionReference(
            "C-021",
            version.strategy_version_id,
            version.semantic_version,
            version.content_sha256,
        )
        or candidate.eligibility_id != eligibility.eligibility_id
        or candidate.eligibility_state is not EligibilityState.ELIGIBLE
        or eligibility.strategy_version_id != version.strategy_version_id
        or eligibility.market_context_id != market_context.context_id
        or candidate.market_context_id != market_context.context_id
        or candidate.analysis_snapshot_id != manifest.snapshot_id
        or market_context.analysis_snapshot.snapshot_id != manifest.snapshot_id
        or candidate.data_quality_report_id != eligibility.data_quality_report_id
        or candidate.asset != market_context.asset
        or candidate.instrument_id != market_context.instrument_id
        or candidate.timeframe != manifest.timeframe
    ):
        _fail(EvidencePackageStatus.INVALID_PROVENANCE, "CANDIDATE_BINDING_MISMATCH")
    if (
        condition_evaluation.truth is not ConditionTruth.PASS
        or condition_evaluation.strategy_version_id != version.strategy_version_id
        or condition_evaluation.context_id != market_context.context_id
        or condition_context.context_id != market_context.context_id
        or condition_evaluation.content_sha256 != version.content_sha256
        or condition_evaluation.semantic_version != version.semantic_version
        or condition_evaluation.correlation_id != condition_context.correlation_id
        or condition_evaluation.trace_id != condition_context.trace_id
    ):
        _fail(EvidencePackageStatus.INVALID_PROVENANCE, "C080_BINDING_MISMATCH")
    if len(resolved_bindings) != 1:
        _fail(EvidencePackageStatus.INSUFFICIENT_EVIDENCE, "SPOT_BINDING_UNAVAILABLE")

    # Re-run the canonical #82 producer with its original creation timestamp.
    # This checks candidate identity/provenance without interpreting score fields.
    setup = evaluate_strategy_setup(
        requested_strategy_version_id=version.strategy_version_id,
        strategy=strategy,
        condition_context=condition_context,
        condition_evaluation=condition_evaluation,
        eligibility_evaluation=eligibility_evaluation,
        market_context=market_context,
        manifest=manifest,
        resolved_bindings=resolved_bindings,
        now=candidate.created_at,
    )
    if (
        setup.outcome is not SetupDetectionOutcome.SETUP_DETECTED
        or setup.candidate != candidate
    ):
        _fail(EvidencePackageStatus.INVALID_PROVENANCE, "C023_NOT_CURRENT_SETUP_OUTPUT")

    binding = resolved_bindings[0]
    if binding.dependency_expires_at <= at:
        _fail(EvidencePackageStatus.STALE_INPUT, "C003_DEPENDENCY_EXPIRED")
    if independence_report.expires_at <= at:
        _fail(EvidencePackageStatus.STALE_INPUT, "C093_EXPIRED")
    required_evidence_ids = set(candidate.supporting_evidence_ids) | set(
        candidate.contradictory_evidence_ids
    )
    if not required_evidence_ids.issubset(evidence):
        _fail(EvidencePackageStatus.INSUFFICIENT_EVIDENCE, "C008_EVIDENCE_MISSING")

    # Resolve C-007 and its complete C-002/C-003/C-001/C-091/C-005/C-008
    # dependency closure again; do not trust a detached reference map.
    resolved_again = resolve_analysis_snapshot_v4(
        manifest,
        now=at,
        snapshots={binding.snapshot.snapshot_id: binding.snapshot},
        reports={binding.report.report_id: binding.report},
        observations={item.market_data_id: item for item in binding.observations},
        sources={item.source_record_id: item for item in binding.sources},
        regimes={binding.regime.regime_id: binding.regime},
        evidence=evidence,
    )
    if resolved_again != resolved_bindings:
        _fail(EvidencePackageStatus.INVALID_PROVENANCE, "C007_RESOLUTION_MISMATCH")

    validate_market_context_v5(
        market_context,
        manifest,
        resolved_bindings=resolved_bindings,
        evidence=evidence,
        supported_independence_reports=supported_independence_reports,
        supported_adversarial_versions=supported_adversarial_versions,
        now=at,
    )
    _validate_c093(independence_report, market_context, manifest, binding)

    refs = _resolve_refs(
        candidate,
        strategy,
        eligibility,
        market_context,
        manifest,
        binding,
        evidence,
        independence_report,
    )

    # The candidate lists are the authoritative C-023 classification. Confirm
    # every listed item is in the current C-009 graph and canonical C-007 set.
    candidate_evidence_ids = set(candidate.supporting_evidence_ids) | set(
        candidate.contradictory_evidence_ids
    )
    confluence = market_context.confluence
    if (
        not candidate.supporting_evidence_ids
        or not candidate_evidence_ids.issubset(set(confluence.evidence_ids))
        or not candidate_evidence_ids.issubset(set(manifest.evidence_ids))
        or not candidate_evidence_ids.issubset(evidence)
    ):
        _fail(EvidencePackageStatus.INSUFFICIENT_EVIDENCE, "C008_EVIDENCE_INCOMPLETE")

    all_evidence_ids = tuple(sorted(candidate_evidence_ids, key=str))
    evidence_refs = tuple(refs["evidence"][item] for item in all_evidence_ids)
    supporting = tuple(
        refs["evidence"][item] for item in candidate.supporting_evidence_ids
    )
    contradictory = tuple(
        refs["evidence"][item] for item in candidate.contradictory_evidence_ids
    )
    for item_id in all_evidence_ids:
        item = evidence[item_id]
        if item.expires_at <= at:
            _fail(EvidencePackageStatus.STALE_INPUT, "C008_EVIDENCE_EXPIRED")
        if not item.usable or item.available_at > at:
            _fail(EvidencePackageStatus.INSUFFICIENT_EVIDENCE, "C008_EVIDENCE_UNUSABLE")

    # C-009 is the finding node: each evidence edge is supported by its exact
    # evidence_ids membership. The #80 PASS result binds this finding to the
    # exact C-021 version; #82 binds the strategy condition to the candidate.
    graph = _build_graph(
        candidate=candidate,
        strategy_ref=refs["strategy"],
        confluence=confluence,
        confluence_ref=refs["confluence"],
        evidence_ids=all_evidence_ids,
        evidence=evidence,
        dependence=refs["dependence"].state,
        condition_evaluation=condition_evaluation,
    )

    expiries = [
        candidate.expires_at,
        eligibility.expires_at,
        market_context.expires_at,
        manifest.expires_at,
        binding.dependency_expires_at,
        condition_context.expires_at,
        condition_evaluation.expires_at,
        confluence.expires_at,
        market_context.adversarial.expires_at,
        independence_report.expires_at,
        *(item.expires_at for item in market_context.conflicts),
        *(item.expires_at for item in market_context.uncertainties),
        *(evidence[item_id].expires_at for item_id in all_evidence_ids),
    ]
    expires_at = min(_utc(item) for item in expiries)
    if expires_at <= at:
        _fail(EvidencePackageStatus.STALE_INPUT, "UPSTREAM_GRAPH_EXPIRED")

    try:
        return SignalEvidencePackageV2.build(
            candidate=refs["candidate"],
            strategy_version=refs["strategy"],
            eligibility=refs["eligibility"],
            market_context=refs["context"],
            analysis_snapshot=refs["manifest"],
            data_quality_report=refs["quality"],
            candidate_valid_until=_utc(candidate.expires_at),
            market_context_valid_until=_utc(market_context.expires_at),
            analysis_snapshot_valid_until=_utc(manifest.expires_at),
            evidence_references=evidence_refs,
            confluence=refs["confluence"],
            conflicts=refs["conflicts"],
            adversarial_assessment=refs["adversarial"],
            adversarial_assessment_required=True,
            uncertainties=refs["uncertainties"],
            dependence=refs["dependence"],
            supporting_evidence=supporting,
            contradictory_evidence=contradictory,
            graph=graph,
            created_at=at,
            expires_at=expires_at,
        )
    except ValueError as exc:
        if "freshness" in str(exc) or "expires" in str(exc):
            _fail(EvidencePackageStatus.STALE_INPUT, "PACKAGE_FRESHNESS_BOUND_FAILED")
        _fail(EvidencePackageStatus.INVALID_PROVENANCE, "C024_CONTRACT_REJECTED")


def _resolve_refs(
    candidate: SignalCandidate,
    strategy: ResolvedStrategyVersion,
    eligibility: StrategyEligibility,
    context: MarketContextV5,
    manifest: AnalysisSnapshotV4,
    binding: ResolvedSpotOHLCVBindingV4,
    evidence: Mapping[UUID, EvidenceItemV2],
    dependence_report: AgentIndependenceReport,
) -> _ResolvedReferences:
    version = strategy.version
    strategy_ref = VersionReference(
        "C-021",
        version.strategy_version_id,
        version.semantic_version,
        strategy_version_content_sha256(version),
    )
    candidate_ref = _contract_ref(candidate, "C-023", "1", candidate.candidate_id)
    eligibility_ref = _contract_ref(
        eligibility, "C-022", eligibility.schema_version, eligibility.eligibility_id
    )
    context_ref = _contract_ref(
        context, "C-006", context.schema_version, context.context_id
    )
    manifest_ref = VersionReference(
        "C-007",
        manifest.snapshot_id,
        manifest.schema_version,
        manifest.content_sha256,
    )
    quality_ref = _contract_ref(
        binding.report,
        "C-003",
        binding.report.schema_version,
        binding.report.report_id,
    )
    output_refs = {
        (item.contract_id, item.record_id): item for item in manifest.analysis_outputs
    }
    evidence_refs = {
        item_id: _output_ref(
            output_refs, "C-008", item_id, "2", "2", canonical_sha256(evidence[item_id])
        )
        for item_id in set(candidate.supporting_evidence_ids)
        | set(candidate.contradictory_evidence_ids)
    }
    confluence = context.confluence
    confluence_ref = _output_ref(
        output_refs,
        "C-009",
        confluence.assessment_id,
        "3",
        "3",
        canonical_sha256(confluence),
    )
    conflicts = tuple(
        _output_ref(
            output_refs, "C-010", item.assessment_id, "3", "3", canonical_sha256(item)
        )
        for item in context.conflicts
    )
    adversarial = context.adversarial
    adversarial_ref = _contract_ref(
        adversarial, "C-019", adversarial.schema_version, adversarial.assessment_id
    )
    uncertainties = tuple(
        _contract_ref(item, "C-069", item.schema_version, item.uncertainty_id)
        for item in context.uncertainties
    )
    dependence_output = confluence.independence_report
    dependence_ref = _output_ref(
        output_refs,
        "C-093",
        dependence_report.report_id,
        dependence_report.schema_version,
        dependence_report.lineage_version,
        canonical_sha256(dependence_report),
    )
    if (
        dependence_output.record_id != dependence_ref.artifact_id
        or dependence_output.schema_version != dependence_ref.version
        or dependence_output.lineage_version != dependence_report.lineage_version
        or dependence_output.content_sha256 != dependence_ref.content_sha256
    ):
        _fail(EvidencePackageStatus.INVALID_PROVENANCE, "C093_REFERENCE_MISMATCH")
    state = _dependence_state(dependence_report.overall_dependence)
    return {
        "candidate": candidate_ref,
        "strategy": strategy_ref,
        "eligibility": eligibility_ref,
        "context": context_ref,
        "manifest": manifest_ref,
        "quality": quality_ref,
        "evidence": evidence_refs,
        "confluence": confluence_ref,
        "conflicts": conflicts,
        "adversarial": adversarial_ref,
        "uncertainties": uncertainties,
        "dependence": C093DependenceReferenceV2(dependence_ref, state),
    }


def _dependence_state(value: object) -> EvidenceDependenceV2:
    """Map C-093 dependence by literal contract value without promotion."""
    try:
        return EvidenceDependenceV2(getattr(value, "value"))
    except (AttributeError, TypeError, ValueError):
        _fail(EvidencePackageStatus.INSUFFICIENT_EVIDENCE, "C093_DEPENDENCE_UNMAPPED")


def _component_dependence(
    evidence_id: UUID, confluence: ConfluenceAssessmentV3
) -> EvidenceDependenceV2:
    states = {
        item.dependence
        for item in confluence.components
        if evidence_id in item.evidence_ids
    }
    if not states:
        _fail(EvidencePackageStatus.INSUFFICIENT_EVIDENCE, "C009_DEPENDENCE_MISSING")
    if len(states) != 1:
        _fail(EvidencePackageStatus.INVALID_PROVENANCE, "C009_DEPENDENCE_AMBIGUOUS")
    return _dependence_state(next(iter(states)))


def _build_graph(
    *,
    candidate: SignalCandidate,
    strategy_ref: VersionReference,
    confluence: ConfluenceAssessmentV3,
    confluence_ref: VersionReference,
    evidence_ids: tuple[UUID, ...],
    evidence: Mapping[UUID, EvidenceItemV2],
    dependence: EvidenceDependenceV2,
    condition_evaluation: StrategyConditionEvaluation,
) -> EvidenceGraphV2:
    evidence_nodes = tuple(
        _node(
            EvidenceNodeTypeV2.EVIDENCE,
            _contract_ref(evidence[item_id], "C-008", "2", item_id),
            _component_dependence(item_id, confluence),
            evidence[item_id].observed_at,
            evidence[item_id].expires_at,
            _method_ref(evidence[item_id].method),
        )
        for item_id in evidence_ids
    )
    finding = _node(
        EvidenceNodeTypeV2.FINDING,
        confluence_ref,
        dependence,
        confluence.as_of,
        confluence.expires_at,
        _method_ref(confluence.method),
    )
    condition = _node(
        EvidenceNodeTypeV2.STRATEGY_CONDITION,
        strategy_ref,
        dependence,
        condition_evaluation.evaluated_at,
        condition_evaluation.expires_at,
        strategy_ref,
    )
    candidate_node = _node(
        EvidenceNodeTypeV2.CANDIDATE,
        _contract_ref(candidate, "C-023", "1", candidate.candidate_id),
        dependence,
        candidate.created_at,
        candidate.expires_at,
        strategy_ref,
    )
    edges = tuple(
        EvidenceGraphEdgeV2(item.node_id, finding.node_id, "EVIDENCE_TO_FINDING")
        for item in evidence_nodes
    ) + (
        EvidenceGraphEdgeV2(
            finding.node_id, condition.node_id, "FINDING_EVALUATED_BY_CONDITION"
        ),
        EvidenceGraphEdgeV2(
            condition.node_id, candidate_node.node_id, "CONDITION_PRODUCED_CANDIDATE"
        ),
    )
    return EvidenceGraphV2((*evidence_nodes, finding, condition, candidate_node), edges)


def _node(
    node_type: EvidenceNodeTypeV2,
    reference: VersionReference,
    dependence: EvidenceDependenceV2,
    observed_at: datetime,
    valid_until: datetime,
    method: VersionReference,
) -> EvidenceGraphNodeV2:
    identity = canonical_sha256(
        {
            "node_type": node_type.value,
            "reference": reference,
        }
    )
    return EvidenceGraphNodeV2(
        uuid5(_GRAPH_NAMESPACE, identity),
        node_type,
        reference,
        dependence,
        observed_at,
        valid_until,
        method,
    )


def _method_ref(value: object) -> VersionReference:
    """Preserve a source method's exact type/version in the package reference type."""
    if type(value) is VersionReference:
        return value
    if type(value) is AnalysisReference:
        digest = canonical_sha256(value)
        identity = uuid5(
            NAMESPACE_URL, f"analysis-method-v1:{value.component}:{value.version}"
        )
        return VersionReference(value.component, identity, value.version, digest)
    _fail(EvidencePackageStatus.INVALID_PROVENANCE, "GRAPH_METHOD_REFERENCE_INVALID")


def _validate_c093(
    report: AgentIndependenceReport,
    context: MarketContextV5,
    manifest: AnalysisSnapshotV4,
    binding: ResolvedSpotOHLCVBindingV4,
) -> None:
    ref = context.confluence.independence_report
    if (
        report.contract_id != "C-093"
        or report.snapshot_id != binding.snapshot.snapshot_id
        or report.manifest_id != manifest.snapshot_id
        or report.binding_id != binding.binding.binding_id
        or report.regime_id != binding.regime.regime_id
        or report.quality_report_id != binding.report.report_id
        or report.snapshot_sha256 != canonical_sha256(binding.snapshot)
        or report.binding_sha256 != canonical_sha256(binding.binding)
        or report.regime_sha256 != canonical_sha256(binding.regime)
        or report.quality_report_sha256 != canonical_sha256(binding.report)
        or report.instrument_id != manifest.instrument_id
        or report.timeframe != manifest.timeframe
        or report.as_of > manifest.analysis_cutoff
        or report.statistical_independence_established is not False
        or ref.record_id != report.report_id
        or ref.content_sha256 != canonical_sha256(report)
    ):
        _fail(EvidencePackageStatus.INVALID_PROVENANCE, "C093_GRAPH_MISMATCH")


def _contract_ref(
    value: object,
    contract_id: str,
    version: str,
    artifact_id: UUID,
    *,
    content_sha256: str | None = None,
) -> VersionReference:
    actual_contract = getattr(value, "contract_id", None)
    actual_version = getattr(value, "schema_version", None)
    actual_id = _artifact_id(value, contract_id)
    digest = content_sha256 or canonical_sha256(value)
    if (
        actual_contract != contract_id
        or actual_version != version
        or actual_id != artifact_id
        or canonical_sha256(value) != digest
    ):
        _fail(
            EvidencePackageStatus.INVALID_PROVENANCE,
            f"{contract_id}_REFERENCE_MISMATCH",
        )
    return VersionReference(contract_id, artifact_id, version, digest)


def _output_ref(
    refs: Mapping[tuple[str, UUID], AnalysisOutputReferenceV4],
    contract_id: str,
    artifact_id: UUID,
    schema_version: str,
    lineage_version: str,
    digest: str,
) -> VersionReference:
    item = refs.get((contract_id, artifact_id))
    if (
        type(item) is not AnalysisOutputReferenceV4
        or item.schema_version != schema_version
        or item.lineage_version != lineage_version
        or item.content_sha256 != digest
    ):
        _fail(
            EvidencePackageStatus.INVALID_PROVENANCE, f"{contract_id}_OUTPUT_MISMATCH"
        )
    return VersionReference(contract_id, artifact_id, schema_version, digest)


def _artifact_id(value: object, contract_id: str) -> UUID | None:
    field_name = {
        "C-003": "report_id",
        "C-006": "context_id",
        "C-008": "evidence_id",
        "C-019": "assessment_id",
        "C-022": "eligibility_id",
        "C-023": "candidate_id",
        "C-069": "uncertainty_id",
        "C-007": "snapshot_id",
    }.get(contract_id)
    result = getattr(value, field_name, None) if field_name is not None else None
    return result if type(result) is UUID else None


def _utc(value: datetime) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None:
        _fail(EvidencePackageStatus.INVALID_PROVENANCE, "INVALID_TIMESTAMP")
    return value.astimezone(UTC)


def _fail(status: EvidencePackageStatus, reason: str) -> NoReturn:
    raise _Failure(status, reason)


__all__ = [
    "EvidencePackageEvaluation",
    "EvidencePackageStatus",
    "build_signal_evidence_package_v2",
    "_dependence_state",
    "_component_dependence",
]
