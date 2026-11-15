from __future__ import annotations

from dataclasses import fields, replace
from datetime import datetime, timedelta
from uuid import UUID

import pytest
from test_wave3_contract_foundation import (
    NOW,
    package,
)
from test_wave3_contract_foundation import (
    validation as make_validation,
)
from trading_platform_api.contracts.serialization import canonical_sha256
from trading_platform_api.lineage.codec import LineageError, decode, encode, key_for
from trading_platform_api.strategy.contracts import VersionReference
from trading_platform_api.strategy.contracts_v2 import (
    EvidenceGraphV2,
    SignalEvidencePackageV2,
)
from trading_platform_api.validation.contracts_v2 import (
    QualificationGateV2,
    QualificationValidationResultV2,
    ValidationArtifactReferenceV2,
    ValidationOutcomeV2,
)
from trading_platform_api.validation.freshness_contracts_v1 import (
    FreshnessContractError,
    FreshnessIdentityComparisonV1,
    ValidationFreshnessSnapshotV1,
    ValidationFreshnessStateV1,
)
from trading_platform_api.validation.spot_validation_freshness import (
    assess_spot_validation_freshness,
)

BUILD_REFERENCE = VersionReference(
    "CODE_BUILD",
    UUID("e756ec24-2e12-4179-9b29-79c73592b160"),
    "build-1",
    "b" * 64,
)
DATASET_REFERENCE = ValidationArtifactReferenceV2(
    "C-092", UUID(int=92), "dataset-v1", "e" * 64
)


def validation(pkg, **kwargs):
    base = make_validation(pkg, **kwargs)
    data_quality = ValidationArtifactReferenceV2(
        pkg.data_quality_report.artifact_type,
        pkg.data_quality_report.artifact_id,
        pkg.data_quality_report.version,
        pkg.data_quality_report.content_sha256,
    )
    gates = tuple(
        replace(gate, evidence=DATASET_REFERENCE)
        if gate.gate is QualificationGateV2.POINT_IN_TIME
        else replace(gate, evidence=data_quality)
        if gate.gate is QualificationGateV2.DATA_INTEGRITY
        and gate.evidence is not None
        and gate.evidence.artifact_type == "C-003"
        else gate
        for gate in base.gates
    )
    values = {
        item.name: getattr(base, item.name)
        for item in fields(base)
        if item.name not in {"content_sha256", "contract_id", "schema_version"}
    }
    values["gates"] = gates
    return QualificationValidationResultV2.build(**values)


def sources():
    original = package()
    graph = EvidenceGraphV2(
        tuple(replace(node, method=BUILD_REFERENCE) for node in original.graph.nodes),
        original.graph.edges,
    )
    package_values = {
        item.name: getattr(original, item.name)
        for item in fields(original)
        if item.name
        not in {"package_id", "content_sha256", "contract_id", "schema_version"}
    }
    package_values["graph"] = graph
    pkg = SignalEvidencePackageV2.build(**package_values)
    return pkg, validation(pkg)


def current_snapshot(pkg, result, **changes):
    regime = next(
        gate.evidence
        for gate in result.gates
        if gate.gate is QualificationGateV2.REGIME_APPLICABILITY
    )
    values = {
        "candidate": ValidationArtifactReferenceV2(
            pkg.candidate.artifact_type,
            pkg.candidate.artifact_id,
            pkg.candidate.version,
            pkg.candidate.content_sha256,
        ),
        "strategy_version": ValidationArtifactReferenceV2(
            pkg.strategy_version.artifact_type,
            pkg.strategy_version.artifact_id,
            pkg.strategy_version.version,
            pkg.strategy_version.content_sha256,
        ),
        "evidence_package": ValidationArtifactReferenceV2(
            "C-024", pkg.package_id, "2", pkg.content_sha256
        ),
        "data_quality_report": ValidationArtifactReferenceV2(
            pkg.data_quality_report.artifact_type,
            pkg.data_quality_report.artifact_id,
            pkg.data_quality_report.version,
            pkg.data_quality_report.content_sha256,
        ),
        "dataset": DATASET_REFERENCE,
        "cost_assumptions": result.rule_set.cost_assumption_set,
        "methodology": result.methodology,
        "rule_set": result.rule_set.reference,
        "market_context": ValidationArtifactReferenceV2(
            pkg.market_context.artifact_type,
            pkg.market_context.artifact_id,
            pkg.market_context.version,
            pkg.market_context.content_sha256,
        ),
        "asset": result.asset,
        "instrument_type": result.instrument_type,
        "timeframe": result.timeframe,
        "regime": result.regime,
        "regime_validation": regime,
        "code_build": ValidationArtifactReferenceV2(
            BUILD_REFERENCE.artifact_type,
            BUILD_REFERENCE.artifact_id,
            BUILD_REFERENCE.version,
            BUILD_REFERENCE.content_sha256,
        ),
        "observed_at": NOW,
    }
    values.update(changes)
    return ValidationFreshnessSnapshotV1(**values)


def assess(pkg=None, result=None, snapshot=None, as_of=None):
    if pkg is None or result is None:
        pkg, result = sources()
    return assess_spot_validation_freshness(
        validation=result,
        evidence_package=pkg,
        current=snapshot or current_snapshot(pkg, result),
        as_of=as_of or NOW + timedelta(minutes=5),
    )


def test_exact_identity_match_is_current_and_only_pass_maps_to_review():
    pkg, result = sources()
    report = assess(pkg, result)

    assert report.freshness is ValidationFreshnessStateV1.CURRENT
    assert report.original_validation_outcome is ValidationOutcomeV2.PASS
    assert report.original_gates == result.gates
    assert report.governance_review_state.value == "CURRENT_FOR_GOVERNANCE_REVIEW"
    assert all(item.matches is True for item in report.identity_comparisons)
    comparisons = {item.identity: item.matches for item in report.identity_comparisons}
    assert comparisons["rule_set"] is True
    assert comparisons["market_context"] is True
    assert report.performance_decay.value == "NOT_ASSESSED"
    assert report.qualification_changed is False
    assert report.production_eligibility is False
    assert report.approval_granted is False
    assert report.activation_granted is False
    assert report.readiness_granted is False


@pytest.mark.parametrize(
    "field",
    (
        "candidate",
        "strategy_version",
        "evidence_package",
        "data_quality_report",
        "dataset",
        "cost_assumptions",
        "methodology",
        "rule_set",
        "market_context",
        "regime_validation",
        "code_build",
    ),
)
@pytest.mark.parametrize("difference", ("identity", "digest", "schema"))
def test_each_bound_identity_mismatch_is_stale(field, difference):
    pkg, result = sources()
    snapshot = current_snapshot(pkg, result)
    reference = getattr(snapshot, field)
    changes = {
        "identity": {"artifact_id": UUID(int=999)},
        "digest": {"content_sha256": "c" * 64},
        "schema": {"version": "99"},
    }[difference]
    changed = replace(reference, **changes)
    report = assess(pkg, result, replace(snapshot, **{field: changed}))

    assert report.freshness is ValidationFreshnessStateV1.STALE
    comparison = next(
        item for item in report.identity_comparisons if item.identity == field
    )
    assert comparison.matches is False
    assert comparison.original != comparison.current


@pytest.mark.parametrize("field", ("asset", "instrument_type", "timeframe", "regime"))
def test_each_current_scope_mismatch_is_stale(field):
    pkg, result = sources()
    snapshot = current_snapshot(pkg, result)

    report = assess(pkg, result, replace(snapshot, **{field: "changed-scope"}))

    assert report.freshness is ValidationFreshnessStateV1.STALE
    comparison = next(
        item for item in report.identity_comparisons if item.identity == field
    )
    assert comparison.matches is False
    assert comparison.original == getattr(result, field)
    assert comparison.current == "changed-scope"


def test_all_current_scope_mismatches_are_reported_as_stale():
    pkg, result = sources()
    snapshot = current_snapshot(pkg, result)
    changed = replace(
        snapshot,
        asset="changed-asset",
        instrument_type="changed-instrument",
        timeframe="changed-timeframe",
        regime="changed-regime",
    )

    report = assess(pkg, result, changed)

    assert report.freshness is ValidationFreshnessStateV1.STALE
    comparisons = {item.identity: item.matches for item in report.identity_comparisons}
    assert all(
        comparisons[name] is False
        for name in ("asset", "instrument_type", "timeframe", "regime")
    )


def test_original_market_context_reference_is_derived_from_exact_package():
    pkg, result = sources()

    report = assess(pkg, result)
    market_context = next(
        item
        for item in report.identity_comparisons
        if item.identity == "market_context"
    )

    assert market_context.original == ValidationArtifactReferenceV2(
        pkg.market_context.artifact_type,
        pkg.market_context.artifact_id,
        pkg.market_context.version,
        pkg.market_context.content_sha256,
    )


def test_original_rule_set_reference_is_derived_from_exact_validation():
    pkg, result = sources()

    report = assess(pkg, result)
    rule_set = next(
        item for item in report.identity_comparisons if item.identity == "rule_set"
    )

    assert rule_set.original == ValidationArtifactReferenceV2(
        "C-025-RULESET",
        result.rule_set.rule_set_id,
        result.rule_set.version,
        result.rule_set.content_sha256,
    )


def test_embedded_rule_set_digest_is_verified_against_exact_validation_source():
    pkg, result = sources()
    object.__setattr__(result.rule_set, "content_sha256", "d" * 64)
    values = {
        item.name: getattr(result, item.name)
        for item in fields(result)
        if item.name not in {"content_sha256", "contract_id", "schema_version"}
    }
    corrupted_result = QualificationValidationResultV2.build(**values)

    with pytest.raises(FreshnessContractError, match="rule-set content digest"):
        assess(pkg, corrupted_result)


@pytest.mark.parametrize(
    "field",
    (
        "candidate",
        "strategy_version",
        "evidence_package",
        "data_quality_report",
        "dataset",
        "cost_assumptions",
        "methodology",
        "rule_set",
        "market_context",
        "asset",
        "instrument_type",
        "timeframe",
        "regime",
        "regime_validation",
        "code_build",
    ),
)
def test_missing_required_current_identity_is_inconclusive(field):
    pkg, result = sources()
    snapshot = current_snapshot(pkg, result, **{field: None})

    assert (
        assess(pkg, result, snapshot).freshness
        is ValidationFreshnessStateV1.INCONCLUSIVE
    )


def test_absent_original_code_build_is_inconclusive_without_substitution():
    pkg, _ = sources()
    methods = tuple(
        replace(
            node,
            method=VersionReference("METHOD", UUID(int=8), "1", "d" * 64),
        )
        for node in pkg.graph.nodes
    )
    graph = EvidenceGraphV2(methods, pkg.graph.edges)
    values = {
        item.name: getattr(pkg, item.name)
        for item in fields(pkg)
        if item.name
        not in {"package_id", "content_sha256", "contract_id", "schema_version"}
    }
    values["graph"] = graph
    no_build = SignalEvidencePackageV2.build(**values)
    no_build_result = validation(no_build)
    current = current_snapshot(no_build, no_build_result)

    report = assess(no_build, no_build_result, current)

    assert report.freshness is ValidationFreshnessStateV1.INCONCLUSIVE
    assert "ORIGINAL_CODE_BUILD_IDENTITY_UNAVAILABLE" in report.reasons


def test_expiry_is_inclusive_at_declared_package_boundary():
    pkg, result = sources()
    snapshot = current_snapshot(pkg, result)

    before = assess(pkg, result, snapshot, pkg.expires_at - timedelta(microseconds=1))
    boundary = assess(pkg, result, snapshot, pkg.expires_at)

    assert before.freshness is ValidationFreshnessStateV1.CURRENT
    assert boundary.freshness is ValidationFreshnessStateV1.EXPIRED
    assert boundary.expires_at == pkg.expires_at


def test_result_and_gate_expiry_boundaries_are_inclusive():
    pkg, _ = sources()
    deadline = NOW + timedelta(minutes=30)
    result = validation(
        pkg,
        valid_until=deadline,
        gate_expiry=deadline,
    )
    snapshot = current_snapshot(pkg, result)

    report = assess(pkg, result, snapshot, deadline)

    assert report.freshness is ValidationFreshnessStateV1.EXPIRED
    assert report.expires_at == deadline


def test_missing_identity_precedes_mismatch_and_expiry_precedes_neither():
    pkg, result = sources()
    matching = current_snapshot(pkg, result)
    snapshot = current_snapshot(
        pkg,
        result,
        candidate=replace(
            matching.candidate,
            artifact_id=UUID(int=999),
        ),
        code_build=None,
    )
    at_expiry = pkg.expires_at

    report = assess(pkg, result, snapshot, at_expiry)

    assert report.freshness is ValidationFreshnessStateV1.INCONCLUSIVE
    assert "CANDIDATE_IDENTITY_MISMATCH" in report.reasons
    assert "ORIGINAL_CODE_BUILD_IDENTITY_UNAVAILABLE" in report.reasons


def test_stale_mismatch_precedes_expiry_when_all_identities_are_comparable():
    pkg, result = sources()
    snapshot = current_snapshot(pkg, result)
    candidate = replace(snapshot.candidate, artifact_id=UUID(int=999))
    changed = replace(snapshot, candidate=candidate)

    report = assess(pkg, result, changed, pkg.expires_at)

    assert report.freshness is ValidationFreshnessStateV1.STALE


@pytest.mark.parametrize(
    ("outcome", "failed"),
    (
        (ValidationOutcomeV2.FAIL, {QualificationGateV2.RISK}),
        (
            ValidationOutcomeV2.INSUFFICIENT_VALIDATION,
            None,
        ),
    ),
)
def test_original_failed_or_insufficient_validation_is_never_upgraded(outcome, failed):
    pkg, _ = sources()
    result = validation(pkg, overall=outcome, failed=failed)
    report = assess(pkg, result)

    assert report.original_validation_outcome is outcome
    assert report.governance_review_state.value == "NOT_ELIGIBLE"
    assert report.freshness is ValidationFreshnessStateV1.CURRENT


def test_assessment_identity_and_digest_are_deterministic_for_exact_inputs():
    pkg, result = sources()
    current = current_snapshot(pkg, result)
    first = assess(pkg, result, current)
    second = assess(pkg, result, current)

    assert first == second
    assert first.assessment_id == second.assessment_id
    assert first.content_sha256 == second.content_sha256
    assert first.current_snapshot_sha256 == canonical_sha256(current)
    assert key_for(first).contract_id == "C-106"
    assert decode(encode(first)) == first


def test_duplicate_comparison_identity_is_rejected():
    report = assess()
    duplicate = FreshnessIdentityComparisonV1(
        "candidate",
        report.identity_comparisons[0].original,
        report.identity_comparisons[0].current,
        True,
    )
    with pytest.raises(FreshnessContractError, match="complete ordered identity set"):
        replace(
            report,
            identity_comparisons=(duplicate, *report.identity_comparisons),
        )


def test_unknown_c106_codec_schema_is_rejected():
    import json

    envelope = json.loads(encode(assess()))
    envelope["schema_version"] = "2"
    with pytest.raises(LineageError, match="corrupt"):
        decode(json.dumps(envelope))


def test_naive_as_of_is_rejected():
    pkg, result = sources()
    with pytest.raises(FreshnessContractError, match="timezone-aware"):
        assess(pkg, result, as_of=datetime(2026, 11, 15, 10))


def test_conflicting_validation_and_package_bindings_are_rejected():
    original, _ = sources()
    other_package = package()
    result = validation(other_package)
    with pytest.raises(FreshnessContractError, match="identities conflict"):
        assess(original, result, current_snapshot(original, result))


def test_conflicting_original_code_build_references_are_rejected():
    original = package()
    other_build = VersionReference("CODE_BUILD", UUID(int=123), "build-2", "f" * 64)
    nodes = tuple(
        replace(
            node,
            method=BUILD_REFERENCE if index == 0 else other_build,
        )
        for index, node in enumerate(original.graph.nodes)
    )
    package_values = {
        item.name: getattr(original, item.name)
        for item in fields(original)
        if item.name
        not in {"package_id", "content_sha256", "contract_id", "schema_version"}
    }
    package_values["graph"] = EvidenceGraphV2(nodes, original.graph.edges)
    conflicting = SignalEvidencePackageV2.build(**package_values)
    result = validation(conflicting)

    with pytest.raises(FreshnessContractError, match="code-build references conflict"):
        assess(conflicting, result)


def test_untyped_current_identity_is_rejected():
    pkg, result = sources()
    snapshot = current_snapshot(pkg, result)

    with pytest.raises(FreshnessContractError, match="typed reference"):
        replace(snapshot, candidate="C-023")


def test_wrong_source_contract_types_are_rejected():
    pkg, result = sources()

    with pytest.raises(FreshnessContractError, match="C-028v2 source is required"):
        assess_spot_validation_freshness(
            validation=object(),
            evidence_package=pkg,
            current=current_snapshot(pkg, result),
            as_of=NOW + timedelta(minutes=5),
        )
