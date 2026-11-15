"""On-demand C-106 freshness comparison for one exact C-028v2/C-024v2 pair."""

from __future__ import annotations

from dataclasses import fields, is_dataclass
from datetime import datetime

from trading_platform_api.contracts.serialization import canonical_sha256
from trading_platform_api.strategy.contracts import VersionReference
from trading_platform_api.strategy.contracts_v2 import SignalEvidencePackageV2
from trading_platform_api.validation.contracts_v2 import (
    QualificationGateV2,
    QualificationValidationResultV2,
    ValidationArtifactReferenceV2,
    ValidationOutcomeV2,
)
from trading_platform_api.validation.freshness_contracts_v1 import (
    FreshnessContractError,
    FreshnessIdentityComparisonV1,
    GovernanceReviewStateV1,
    PerformanceDecayStateV1,
    ValidationFreshnessAssessmentV1,
    ValidationFreshnessSnapshotV1,
    ValidationFreshnessStateV1,
    evidence_package_digest,
    validation_result_digest,
)

_CURRENT_REQUIREMENTS = (
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
)


def _as_validation_reference(value: VersionReference) -> ValidationArtifactReferenceV2:
    return ValidationArtifactReferenceV2(
        value.artifact_type,
        value.artifact_id,
        value.version,
        value.content_sha256,
    )


def _verify_source_pair(
    result: QualificationValidationResultV2,
    package: SignalEvidencePackageV2,
) -> dict[str, ValidationArtifactReferenceV2 | str | None]:
    if type(result) is not QualificationValidationResultV2 or (
        result.contract_id != "C-028" or result.schema_version != "2"
    ):
        raise FreshnessContractError("C-028v2 source is required.")
    if type(package) is not SignalEvidencePackageV2 or (
        package.contract_id != "C-024" or package.schema_version != "2"
    ):
        raise FreshnessContractError("C-024v2 source is required.")
    if result.content_sha256 != validation_result_digest(result):
        raise FreshnessContractError("C-028v2 source digest is invalid.")
    if package.content_sha256 != evidence_package_digest(package):
        raise FreshnessContractError("C-024v2 source digest is invalid.")
    package_values = {
        item.name: getattr(package, item.name)
        for item in fields(package)
        if item.name
        not in {"package_id", "content_sha256", "contract_id", "schema_version"}
    }
    rebuilt_package = SignalEvidencePackageV2.build(**package_values)  # type: ignore[arg-type]
    if rebuilt_package != package:
        raise FreshnessContractError("C-024v2 source identity is invalid.")
    if result.cost_assumptions.content_sha256 != canonical_sha256(
        {
            item.name: getattr(result.cost_assumptions, item.name)
            for item in fields(result.cost_assumptions)
            if item.name != "content_sha256"
        }
    ):
        raise FreshnessContractError("C-027v2 cost-assumption digest is invalid.")
    if result.rule_set.content_sha256 != canonical_sha256(
        {
            item.name: getattr(result.rule_set, item.name)
            for item in fields(result.rule_set)
            if item.name != "content_sha256"
        }
    ):
        raise FreshnessContractError(
            "rule-set content digest (C-025-RULESET) is invalid."
        )

    candidate = _as_validation_reference(package.candidate)
    strategy = _as_validation_reference(package.strategy_version)
    evidence_package = ValidationArtifactReferenceV2(
        "C-024", package.package_id, "2", package.content_sha256
    )
    if (
        result.candidate_id != candidate.artifact_id
        or result.candidate_sha256 != candidate.content_sha256
        or result.strategy_version_id != strategy.artifact_id
        or result.evidence_package_id != package.package_id
        or result.evidence_package_sha256 != package.content_sha256
    ):
        raise FreshnessContractError("C-028v2 and C-024v2 source identities conflict.")
    if result.methodology != result.rule_set.methodology:
        raise FreshnessContractError("C-028v2 methodology references conflict.")
    data_gate = next(
        item for item in result.gates if item.gate is QualificationGateV2.DATA_INTEGRITY
    )
    package_quality = _as_validation_reference(package.data_quality_report)
    if (
        data_gate.evidence is not None
        and data_gate.evidence.artifact_type == "C-003"
        and data_gate.evidence != package_quality
    ):
        raise FreshnessContractError(
            "C-028v2 and C-024v2 data-quality references conflict."
        )
    regime_gate = next(
        item
        for item in result.gates
        if item.gate is QualificationGateV2.REGIME_APPLICABILITY
    )
    regime = regime_gate.evidence
    if regime is not None and regime.artifact_type != "C-074":
        raise FreshnessContractError("regime evidence is not the typed C-074 source.")
    code_builds: set[ValidationArtifactReferenceV2] = set()
    pending: list[object] = [result, package]
    visited: set[int] = set()
    while pending:
        value = pending.pop()
        if id(value) in visited:
            continue
        visited.add(id(value))
        if isinstance(value, (VersionReference, ValidationArtifactReferenceV2)):
            if value.artifact_type == "CODE_BUILD":
                code_builds.add(
                    ValidationArtifactReferenceV2(
                        value.artifact_type,
                        value.artifact_id,
                        value.version,
                        value.content_sha256,
                    )
                )
            continue
        if is_dataclass(value):
            pending.extend(getattr(value, item.name) for item in fields(value))
        elif isinstance(value, (tuple, list)):
            pending.extend(value)
    if len(code_builds) > 1:
        raise FreshnessContractError("C-028v2/C-024v2 code-build references conflict.")
    point_in_time_gate = next(
        item for item in result.gates if item.gate is QualificationGateV2.POINT_IN_TIME
    )
    dataset = (
        point_in_time_gate.evidence
        if point_in_time_gate.evidence is not None
        and point_in_time_gate.evidence.artifact_type == "C-092"
        else None
    )
    return {
        "candidate": candidate,
        "strategy_version": strategy,
        "evidence_package": evidence_package,
        "data_quality_report": _as_validation_reference(package.data_quality_report),
        "dataset": dataset,
        "cost_assumptions": result.rule_set.cost_assumption_set,
        "methodology": result.methodology,
        "rule_set": result.rule_set.reference,
        "market_context": _as_validation_reference(package.market_context),
        "asset": result.asset,
        "instrument_type": result.instrument_type,
        "timeframe": result.timeframe,
        "regime": result.regime,
        "regime_validation": regime,
        # Only an explicitly typed CODE_BUILD source reference in the exact
        # immutable input closure may establish the original build identity.
        "code_build": next(iter(code_builds), None),
    }


def _result_expiries(
    result: QualificationValidationResultV2,
    package: SignalEvidencePackageV2,
) -> tuple[datetime, ...]:
    values = {
        result.valid_until,
        *(gate.valid_until for gate in result.gates),
        package.expires_at,
        package.candidate_valid_until,
        package.market_context_valid_until,
        package.analysis_snapshot_valid_until,
        *(node.valid_until for node in package.graph.nodes),
    }
    return tuple(sorted(values))


def assess_spot_validation_freshness(
    *,
    validation: QualificationValidationResultV2,
    evidence_package: SignalEvidencePackageV2,
    current: ValidationFreshnessSnapshotV1,
    as_of: datetime,
) -> ValidationFreshnessAssessmentV1:
    """Assess explicit current identities without resolving external/latest state."""
    if type(current) is not ValidationFreshnessSnapshotV1:
        raise FreshnessContractError("an explicit typed current snapshot is required.")
    if type(as_of) is not datetime or as_of.tzinfo is None or as_of.utcoffset() is None:
        raise FreshnessContractError("as_of must be timezone-aware and explicit.")
    original = _verify_source_pair(validation, evidence_package)
    at = as_of.astimezone(current.observed_at.tzinfo)
    if current.observed_at > at:
        raise FreshnessContractError("current snapshot is later than explicit as_of.")
    if as_of.astimezone(validation.created_at.tzinfo) < validation.created_at:
        raise FreshnessContractError("as_of precedes the source validation creation.")

    current_values = {name: getattr(current, name) for name in _CURRENT_REQUIREMENTS}
    comparisons: list[FreshnessIdentityComparisonV1] = []
    reasons: list[str] = []
    mismatched = False
    unavailable = False
    for name in _CURRENT_REQUIREMENTS:
        expected = original[name]
        observed = current_values[name]
        matches = None if expected is None or observed is None else expected == observed
        comparisons.append(
            FreshnessIdentityComparisonV1(name, expected, observed, matches)
        )
        if matches is False:
            mismatched = True
            reasons.append(f"{name.upper()}_IDENTITY_MISMATCH")
        elif matches is None:
            unavailable = True
            if name == "code_build":
                reasons.append("ORIGINAL_CODE_BUILD_IDENTITY_UNAVAILABLE")
            elif expected is None:
                reasons.append(f"ORIGINAL_{name.upper()}_IDENTITY_UNAVAILABLE")
            else:
                reasons.append(f"CURRENT_{name.upper()}_IDENTITY_UNAVAILABLE")

    expiries = _result_expiries(validation, evidence_package)
    if unavailable:
        state = ValidationFreshnessStateV1.INCONCLUSIVE
    elif mismatched:
        state = ValidationFreshnessStateV1.STALE
    elif any(expiry <= as_of.astimezone(expiry.tzinfo) for expiry in expiries):
        state = ValidationFreshnessStateV1.EXPIRED
        reasons.append("DECLARED_EVIDENCE_OR_RESULT_EXPIRY_REACHED")
    else:
        state = ValidationFreshnessStateV1.CURRENT
    review = (
        GovernanceReviewStateV1.CURRENT_FOR_GOVERNANCE_REVIEW
        if validation.outcome is ValidationOutcomeV2.PASS
        and state is ValidationFreshnessStateV1.CURRENT
        else GovernanceReviewStateV1.NOT_ELIGIBLE
    )
    return ValidationFreshnessAssessmentV1.build(
        validation_result_id=validation.result_id,
        validation_schema_version=validation.schema_version,
        validation_result_sha256=validation.content_sha256,
        evidence_package_id=evidence_package.package_id,
        evidence_package_schema_version=evidence_package.schema_version,
        evidence_package_sha256=evidence_package.content_sha256,
        current_snapshot_sha256=canonical_sha256(current),
        current_snapshot_observed_at=current.observed_at,
        as_of=as_of,
        freshness=state,
        original_validation_outcome=validation.outcome,
        original_gates=validation.gates,
        governance_review_state=review,
        identity_comparisons=tuple(comparisons),
        reasons=tuple(reasons),
        declared_expiries=expiries,
        expires_at=min(expiries) if expiries else None,
        performance_decay=PerformanceDecayStateV1.NOT_ASSESSED,
        performance_decay_reason="ROLLING_PERFORMANCE_DECAY_NOT_ASSESSED",
        qualification_changed=False,
        production_eligibility=False,
        approval_granted=False,
        activation_granted=False,
        readiness_granted=False,
    )


__all__ = ["assess_spot_validation_freshness"]
