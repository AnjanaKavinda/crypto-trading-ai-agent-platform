from __future__ import annotations

from dataclasses import replace
from uuid import uuid4

import pytest
from test_strategy_setup_detection import _detect, _positive_case
from trading_platform_api.analysis.spot_meta_analysis import (
    EvidenceDependenceV2,
)
from trading_platform_api.contracts.serialization import canonical_sha256
from trading_platform_api.strategy import (
    EvidenceDependenceV2 as StrategyEvidenceDependenceV2,
)
from trading_platform_api.strategy import (
    EvidenceNodeTypeV2,
    EvidencePackageStatus,
    build_signal_evidence_package_v2,
)


def _package(case, *, candidate=None, now=None, **overrides):
    _, envelope, debate, strategy, condition_context, condition, eligibility = case
    candidate = candidate or _detect(case, now=envelope.manifest.created_at).candidate
    assert candidate is not None
    values = {
        "candidate": candidate,
        "strategy": strategy,
        "condition_context": condition_context,
        "condition_evaluation": condition,
        "eligibility_evaluation": eligibility,
        "market_context": debate.market_context,
        "manifest": envelope.manifest,
        "resolved_bindings": envelope.resolved,
        "evidence": envelope.evidence,
        "independence_report": debate.independence_report,
        "supported_independence_reports": (
            debate.market_context.confluence.independence_report,
        ),
        "supported_adversarial_versions": envelope.supported_adversarial_versions,
        "now": now or envelope.manifest.created_at,
    }
    values.update(overrides)
    return build_signal_evidence_package_v2(**values)


def test_exact_spot_candidate_builds_deterministic_c024v2_and_bounded_graph():
    case = _positive_case()
    first = _package(case)
    second = _package(case)

    assert first.status is EvidencePackageStatus.PACKAGE_READY
    assert first.package is not None
    assert second.package == first.package
    package = first.package
    _, envelope, debate, strategy, _, _, eligibility = case
    candidate = _detect(case, now=envelope.manifest.created_at).candidate
    assert candidate is not None
    assert package.candidate.artifact_id == candidate.candidate_id
    assert package.strategy_version.artifact_id == strategy.version.strategy_version_id
    assert package.strategy_version.content_sha256 == strategy.version.content_sha256
    assert package.eligibility.artifact_id == eligibility.eligibility.eligibility_id
    assert package.market_context.artifact_id == debate.market_context.context_id
    assert package.analysis_snapshot.artifact_id == envelope.manifest.snapshot_id
    assert package.analysis_snapshot.content_sha256 == envelope.manifest.content_sha256
    assert (
        package.data_quality_report.artifact_id == envelope.resolved[0].report.report_id
    )
    assert package.data_quality_report.content_sha256 == canonical_sha256(
        envelope.resolved[0].report
    )
    assert (
        package.confluence.artifact_id == debate.market_context.confluence.assessment_id
    )
    assert {item.artifact_id for item in package.evidence_references} == (
        set(candidate.supporting_evidence_ids)
        | set(candidate.contradictory_evidence_ids)
    )
    assert (
        package.adversarial_assessment.artifact_id
        == debate.market_context.adversarial.assessment_id
    )
    assert {item.artifact_id for item in package.uncertainties} == {
        item.uncertainty_id for item in debate.market_context.uncertainties
    }
    candidate_nodes = [
        item
        for item in package.graph.nodes
        if item.node_type is EvidenceNodeTypeV2.CANDIDATE
    ]
    assert len(candidate_nodes) == 1
    assert candidate_nodes[0].reference == package.candidate
    assert all(
        edge.source_node_id != candidate_nodes[0].node_id
        for edge in package.graph.edges
    )
    assert package.expires_at == min(
        package.candidate_valid_until,
        package.market_context_valid_until,
        package.analysis_snapshot_valid_until,
        eligibility.eligibility.expires_at,
        *(item.valid_until for item in package.graph.nodes),
        *(item.expires_at for item in case[2].market_context.conflicts),
        *(item.expires_at for item in case[2].market_context.uncertainties),
        case[2].market_context.adversarial.expires_at,
        case[2].independence_report.expires_at,
        case[5].expires_at,
        case[1].resolved[0].dependency_expires_at,
        *(
            case[1].evidence[item].expires_at
            for item in candidate.supporting_evidence_ids
        ),
        *(
            case[1].evidence[item].expires_at
            for item in candidate.contradictory_evidence_ids
        ),
    )
    assert package.content_sha256 == first.package.content_sha256
    assert package.package_id == first.package.package_id
    assert package.adversarial_assessment_required
    assert package.dependence.state is StrategyEvidenceDependenceV2.PARTIALLY_DEPENDENT
    assert package.dependence.assessment.artifact_id == (
        case[2].independence_report.report_id
    )
    assert {item.artifact_id for item in package.conflicts} == {
        item.assessment_id for item in case[2].market_context.conflicts
    }
    assert {item.artifact_id for item in package.supporting_evidence} == set(
        candidate.supporting_evidence_ids
    )
    assert {item.artifact_id for item in package.contradictory_evidence} == set(
        candidate.contradictory_evidence_ids
    )
    assert len(package.conflicts) == len(case[2].market_context.conflicts)
    assert package.adversarial_assessment is not None
    assert package.uncertainties


def test_missing_c008_evidence_fails_without_package():
    case = _positive_case()
    _, envelope, *_ = case
    candidate = _detect(case, now=envelope.manifest.created_at).candidate
    assert candidate is not None
    missing = dict(envelope.evidence)
    missing.pop(candidate.supporting_evidence_ids[0])
    result = _package(case, evidence=missing)
    assert result.status is EvidencePackageStatus.INSUFFICIENT_EVIDENCE
    assert result.package is None


def test_mismatched_c008_content_and_c008_not_in_candidate_fail_closed():
    case = _positive_case()
    _, envelope, *_ = case
    evidence = dict(envelope.evidence)
    evidence_id = next(iter(evidence))
    evidence[evidence_id] = replace(evidence[evidence_id], value="changed")
    result = _package(case, evidence=evidence)
    assert result.status is EvidencePackageStatus.INVALID_PROVENANCE
    assert result.package is None

    candidate = _detect(case, now=envelope.manifest.created_at).candidate
    assert candidate is not None
    changed = replace(
        candidate,
        supporting_evidence_ids=(uuid4(),),
    )
    result = _package(case, candidate=changed)
    assert result.status is EvidencePackageStatus.INVALID_PROVENANCE
    assert result.package is None


def test_candidate_mismatch_fails_without_package():
    case = _positive_case()
    candidate = _detect(case, now=case[1].manifest.created_at).candidate
    assert candidate is not None
    changed = replace(candidate, candidate_id=uuid4())
    result = _package(case, candidate=changed)
    assert result.status is EvidencePackageStatus.INVALID_PROVENANCE
    assert result.package is None


def test_stale_candidate_fails_without_package():
    case = _positive_case()
    candidate = _detect(case, now=case[1].manifest.created_at).candidate
    assert candidate is not None
    result = _package(case, candidate=candidate, now=candidate.expires_at)
    assert result.status is EvidencePackageStatus.STALE_INPUT
    assert result.package is None


def test_c093_dependence_value_is_preserved_without_score_interpretation():
    case = _positive_case()
    result = _package(case)
    assert result.package is not None
    report = case[2].independence_report
    assert report.overall_dependence is EvidenceDependenceV2.PARTIALLY_DEPENDENT
    assert result.package.dependence.state.value == report.overall_dependence.value
    candidate = _detect(case, now=case[1].manifest.created_at).candidate
    assert candidate is not None
    assert candidate.analytical_confidence == 0
    assert candidate.evidence_strength == 0
    assert not hasattr(result.package, "analytical_confidence")
    assert not hasattr(result.package, "evidence_strength")


def test_unknown_c093_dependence_maps_to_unknown_without_promotion():
    from trading_platform_api.strategy.evidence_package import _dependence_state

    assert (
        _dependence_state(EvidenceDependenceV2.UNKNOWN)
        is StrategyEvidenceDependenceV2.UNKNOWN
    )


def test_evidence_component_dependence_must_be_unambiguous():
    from trading_platform_api.strategy.evidence_package import _component_dependence

    context = _positive_case()[2].market_context
    evidence_id = context.confluence.components[0].evidence_ids[0]
    duplicate = replace(
        context.confluence.components[0],
        component_id=uuid4(),
        domain="distinct-domain",
        dependence=(
            EvidenceDependenceV2.UNKNOWN
            if context.confluence.components[0].dependence
            is not EvidenceDependenceV2.UNKNOWN
            else EvidenceDependenceV2.PARTIALLY_DEPENDENT
        ),
    )
    ambiguous = replace(
        context.confluence, components=(*context.confluence.components, duplicate)
    )
    with pytest.raises(Exception) as error:
        _component_dependence(evidence_id, ambiguous)
    assert getattr(error.value, "reason") == "C009_DEPENDENCE_AMBIGUOUS"


@pytest.mark.parametrize(
    ("changed_field", "reason"),
    [
        ("eligibility_id", "CANDIDATE_BINDING_MISMATCH"),
        ("market_context_id", "CANDIDATE_BINDING_MISMATCH"),
        ("analysis_snapshot_id", "CANDIDATE_BINDING_MISMATCH"),
        ("data_quality_report_id", "CANDIDATE_BINDING_MISMATCH"),
    ],
)
def test_candidate_provenance_mismatches_fail_closed(changed_field, reason):
    case = _positive_case()
    candidate = _detect(case, now=case[1].manifest.created_at).candidate
    assert candidate is not None
    result = _package(case, candidate=replace(candidate, **{changed_field: uuid4()}))
    assert result.status is EvidencePackageStatus.INVALID_PROVENANCE
    assert result.reason_codes == (reason,)
    assert result.package is None


def test_strategy_version_mismatch_fails_closed():
    case = _positive_case()
    _, envelope, debate, strategy, context, condition, eligibility = case
    wrong_version = replace(strategy.version, strategy_version_id=uuid4())
    wrong_strategy = replace(strategy, version=wrong_version)
    candidate = _detect(case, now=envelope.manifest.created_at).candidate
    assert candidate is not None
    result = _package(case, candidate=candidate, strategy=wrong_strategy)
    assert result.status is EvidencePackageStatus.INVALID_PROVENANCE
    assert result.package is None


def test_wrong_c022_object_fails_closed():
    case = _positive_case()
    eligibility_result = case[6]
    assert eligibility_result.eligibility is not None
    wrong_eligibility = replace(eligibility_result.eligibility, eligibility_id=uuid4())
    wrong_result = replace(eligibility_result, eligibility=wrong_eligibility)
    result = _package(case, eligibility_evaluation=wrong_result)
    assert result.status is EvidencePackageStatus.INVALID_PROVENANCE
    assert result.package is None


def test_c069_uncertainty_requires_the_exact_candidate_context():
    case = _positive_case()
    candidate = _detect(case, now=case[1].manifest.created_at).candidate
    assert candidate is not None
    context = case[2].market_context
    changed_uncertainty = replace(context.uncertainties[0], uncertainty_id=uuid4())
    changed_context = replace(
        context,
        context_id=uuid4(),
        uncertainties=(changed_uncertainty, *context.uncertainties[1:]),
    )
    result = _package(case, candidate=candidate, market_context=changed_context)
    assert result.status is EvidencePackageStatus.INVALID_PROVENANCE
    assert result.package is None


def test_mismatched_c003_resolution_fails_closed():
    case = _positive_case()
    _, envelope, *_ = case
    binding = envelope.resolved[0]
    wrong_report = replace(binding.report, report_id=uuid4())
    result = _package(case, resolved_bindings=(replace(binding, report=wrong_report),))
    assert result.status is EvidencePackageStatus.INVALID_PROVENANCE
    assert result.package is None


def test_mismatched_c009_c010_c093_and_missing_c019_registry_proof_fail_closed():
    case = _positive_case()
    _, envelope, debate, *_ = case
    context = debate.market_context
    wrong_context = replace(
        context,
        conflicts=(
            replace(context.conflicts[0], assessment_id=uuid4()),
            *context.conflicts[1:],
        ),
    )
    assert (
        _package(case, market_context=wrong_context).status
        is EvidencePackageStatus.INVALID_PROVENANCE
    )
    wrong_confluence = replace(context.confluence, assessment_id=uuid4())
    assert (
        _package(
            case, market_context=replace(context, confluence=wrong_confluence)
        ).status
        is EvidencePackageStatus.INVALID_PROVENANCE
    )
    assert (
        _package(case, supported_adversarial_versions=()).status
        is EvidencePackageStatus.INVALID_PROVENANCE
    )
    wrong_report = replace(debate.independence_report, report_id=uuid4())
    assert (
        _package(case, independence_report=wrong_report).status
        is EvidencePackageStatus.INVALID_PROVENANCE
    )
    assert (
        _package(case, supported_independence_reports=()).status
        is EvidencePackageStatus.INVALID_PROVENANCE
    )
    assert (
        _package(case, independence_report=None).status
        is EvidencePackageStatus.INSUFFICIENT_EVIDENCE
    )


def test_stale_context_and_snapshot_fail_with_stale_result():
    case = _positive_case()
    now = case[2].market_context.expires_at
    assert _package(case, now=now).status is EvidencePackageStatus.STALE_INPUT
    candidate = _detect(case, now=case[1].manifest.created_at).candidate
    assert candidate is not None
    assert (
        _package(case, now=case[1].manifest.expires_at).status
        is EvidencePackageStatus.STALE_INPUT
    )
