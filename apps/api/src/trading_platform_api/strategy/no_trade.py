"""Deterministic C-026v2 NO_TRADE mapping for PERSONAL_SPOT_RESEARCH."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from uuid import UUID, uuid5

from trading_platform_api.analysis.contracts import ResolutionStatus
from trading_platform_api.analysis.versioned_contracts_v5 import MarketContextV5
from trading_platform_api.contracts.serialization import canonical_sha256
from trading_platform_api.strategy.contracts import (
    EligibilityState,
    QualificationStatus,
    SignalCandidate,
    SignalLifecycleState,
    VersionReference,
)
from trading_platform_api.strategy.contracts_v2 import (
    NoTradeDecisionV2,
    NoTradeReasonV2,
    SignalEvidencePackageV2,
    SignalQualificationV2,
)
from trading_platform_api.strategy.eligibility import StrategyEligibilityEvaluation
from trading_platform_api.strategy.evidence_package import (
    EvidencePackageEvaluation,
    EvidencePackageStatus,
)
from trading_platform_api.strategy.qualification import (
    QualificationEngineResult,
    QualificationEngineStatus,
)
from trading_platform_api.strategy.qualification_rules import (
    QualificationRuleEvaluation,
)
from trading_platform_api.strategy.setup_detection import (
    SetupDetectionEvaluation,
    SetupDetectionOutcome,
)
from trading_platform_api.validation.contracts_v2 import (
    QualificationGateV2,
    QualificationValidationResultV2,
    ValidationGateOutcomeV2,
    ValidationOutcomeV2,
)

_NO_TRADE_NAMESPACE = UUID("5d2cbb95-73cb-5c8b-9c3d-ae449cb72f0c")


class NoTradeEngineStatus(StrEnum):
    NO_TRADE = "NO_TRADE"
    NO_TRADE_NOT_APPLICABLE = "NO_TRADE_NOT_APPLICABLE"
    INSUFFICIENT_CONTEXT = "INSUFFICIENT_CONTEXT"


@dataclass(frozen=True, slots=True)
class NoTradeEngineResult:
    """Local result; only NO_TRADE carries the successful C-026v2 artifact."""

    status: NoTradeEngineStatus
    reasons: tuple[NoTradeReasonV2, ...]
    decision: NoTradeDecisionV2 | None
    evaluated_at: datetime

    def __post_init__(self) -> None:
        if type(self.status) is not NoTradeEngineStatus:
            raise ValueError("status must be NoTradeEngineStatus")
        if type(self.reasons) is not tuple or any(
            type(reason) is not NoTradeReasonV2 for reason in self.reasons
        ):
            raise ValueError("reasons must contain NoTradeReasonV2 values")
        if len(set(self.reasons)) != len(self.reasons):
            raise ValueError("reasons must be unique")
        if self.status is NoTradeEngineStatus.NO_TRADE:
            if self.decision is None or self.decision.reasons != self.reasons:
                raise ValueError("NO_TRADE requires a matching C-026v2 decision")
        elif self.decision is not None or self.reasons:
            raise ValueError("non-emitting outcomes cannot carry C-026v2 reasons")
        object.__setattr__(self, "evaluated_at", _utc(self.evaluated_at))


def evaluate_no_trade_v2(
    *,
    market_context: MarketContextV5 | None,
    setup: SetupDetectionEvaluation | None,
    eligibility: StrategyEligibilityEvaluation | None,
    evidence_package: EvidencePackageEvaluation | None,
    validation: QualificationRuleEvaluation | None,
    qualification: QualificationEngineResult | None,
    evaluated_at: datetime,
    correlation_id: str,
) -> NoTradeEngineResult:
    """Map exact Spot chain outcomes to C-026v2 without recalculating evidence.

    The evaluator reads #80/#81/#82 runtime states, #85 package status, #87
    C-028v2 outcome, and #86 C-025v2 result. It neither creates a candidate nor
    duplicates validation, risk, or execution behavior.
    """

    at = _utc(evaluated_at)
    if type(market_context) is not MarketContextV5:
        return _cannot_emit(at)

    inputs = (setup, eligibility, evidence_package, validation, qualification)
    if any(value is not None and not _supported_input(value) for value in inputs):
        reasons: tuple[NoTradeReasonV2, ...] = (NoTradeReasonV2.INVALID_PROVENANCE,)
    else:
        reasons = _collect_reasons(
            market_context,
            setup,
            eligibility,
            evidence_package,
            validation,
            qualification,
            at,
        )

    candidate = setup.candidate if setup is not None else None
    package = (
        evidence_package.package
        if evidence_package is not None
        and evidence_package.status is EvidencePackageStatus.PACKAGE_READY
        else None
    )
    validation_result = validation.validation if validation is not None else None
    qualification_artifact = (
        qualification.qualification if qualification is not None else None
    )

    # A current, exactly bound C-025v2 QUALIFIED result is authoritative for
    # this decision context. The market context may retain unresolved source
    # conflicts/uncertainties that the approved validation gates already
    # assessed; those must not create a contradictory C-026 for the same path.
    provenance, provenance_error = _provenance(
        market_context,
        candidate,
        eligibility,
        package,
        validation_result,
        qualification_artifact,
    )
    exact_qualified_path = (
        setup is not None
        and candidate is not None
        and eligibility is not None
        and eligibility.state is EligibilityState.ELIGIBLE
        and evidence_package is not None
        and evidence_package.status is EvidencePackageStatus.PACKAGE_READY
        and validation is not None
        and validation.outcome is ValidationOutcomeV2.PASS
        and not provenance_error
        and not _has_provenance_mismatch(
            market_context,
            candidate,
            eligibility,
            package,
            validation_result,
            qualification_artifact,
        )
        and _exact_qualified_path(
            market_context,
            candidate,
            package,
            validation_result,
            qualification,
            qualification_artifact,
            at,
        )
    )
    if exact_qualified_path:
        return NoTradeEngineResult(
            NoTradeEngineStatus.NO_TRADE_NOT_APPLICABLE, (), None, at
        )

    if not reasons:
        # A partial chain cannot imply permission to trade or a qualified result.
        reasons = (NoTradeReasonV2.VALIDATION_INCONCLUSIVE,)

    reasons = tuple(sorted(set(reasons), key=lambda reason: reason.value))
    if provenance_error:
        reasons = tuple(
            sorted(
                {*reasons, NoTradeReasonV2.INVALID_PROVENANCE},
                key=lambda reason: reason.value,
            )
        )

    if not provenance:
        return _cannot_emit(at)

    context_ref = _reference_for_contract(
        provenance, "C-006", market_context.context_id
    )
    if context_ref is None:
        return _cannot_emit(at)

    candidate_id = candidate.candidate_id if candidate is not None else None
    strategy_version_id = _strategy_version_id(
        candidate, eligibility, package, qualification_artifact
    )
    quality_id = (
        candidate.data_quality_report_id
        if candidate is not None
        else package.data_quality_report.artifact_id
        if package is not None
        else None
    )
    blocking_ids = _blocking_evidence_ids(candidate, package, validation_result)
    conflict_ids = _conflict_ids(market_context)
    uncertainty_ids = tuple(
        sorted(
            {
                item.uncertainty_id
                for item in market_context.uncertainties
                if item.resolution_status is ResolutionStatus.UNRESOLVED
            },
            key=str,
        )
    )
    expiry = _decision_expiry(
        at,
        market_context,
        candidate,
        eligibility,
        package,
        validation_result,
        qualification_artifact,
    )
    identity_values = {
        "market_context_id": market_context.context_id,
        "candidate_id": candidate_id,
        "strategy_version_id": strategy_version_id,
        "reasons": tuple(reason.value for reason in reasons),
        "provenance": provenance,
        "blocking_evidence_ids": blocking_ids,
        "conflict_ids": conflict_ids,
        "uncertainty_ids": uncertainty_ids,
        "data_quality_report_id": quality_id,
        "correlation_id": correlation_id,
        "decided_at": at,
        "expires_at": expiry,
    }
    decision = NoTradeDecisionV2(
        decision_id=uuid5(_NO_TRADE_NAMESPACE, canonical_sha256(identity_values)),
        market_context_id=market_context.context_id,
        candidate_id=candidate_id,
        strategy_version_id=strategy_version_id,
        reasons=reasons,
        explanation="NO_TRADE: " + ", ".join(reason.value for reason in reasons),
        blocking_evidence_ids=blocking_ids,
        conflict_ids=conflict_ids,
        uncertainty_ids=uncertainty_ids,
        data_quality_report_id=quality_id,
        provenance=provenance,
        correlation_id=correlation_id,
        lifecycle=SignalLifecycleState.NO_TRADE,
        decided_at=at,
        expires_at=expiry,
    )
    return NoTradeEngineResult(NoTradeEngineStatus.NO_TRADE, reasons, decision, at)


def _collect_reasons(
    context: MarketContextV5,
    setup: SetupDetectionEvaluation | None,
    eligibility: StrategyEligibilityEvaluation | None,
    package_eval: EvidencePackageEvaluation | None,
    validation_eval: QualificationRuleEvaluation | None,
    qualification_eval: QualificationEngineResult | None,
    at: datetime,
) -> tuple[NoTradeReasonV2, ...]:
    reasons: set[NoTradeReasonV2] = set()
    candidate = setup.candidate if setup is not None else None
    package = (
        package_eval.package
        if package_eval is not None
        and package_eval.status is EvidencePackageStatus.PACKAGE_READY
        else None
    )
    validation = validation_eval.validation if validation_eval is not None else None
    qualification = (
        qualification_eval.qualification if qualification_eval is not None else None
    )

    if setup is None:
        reasons.add(NoTradeReasonV2.MISSING_DATA)
    elif setup.outcome is SetupDetectionOutcome.NO_SETUP:
        reasons.update(_setup_reasons(setup.reason_codes, NoTradeReasonV2.NO_SETUP))
    elif setup.outcome is SetupDetectionOutcome.INSUFFICIENT_INPUT:
        reasons.update(
            _setup_reasons(setup.reason_codes, NoTradeReasonV2.INSUFFICIENT_DATA)
        )

    if eligibility is None:
        reasons.add(NoTradeReasonV2.MISSING_DATA)
    elif eligibility.state is EligibilityState.NOT_ELIGIBLE:
        reasons.add(NoTradeReasonV2.STRATEGY_INELIGIBLE)
    elif eligibility.state is EligibilityState.INSUFFICIENT_DATA:
        reasons.add(NoTradeReasonV2.INSUFFICIENT_DATA)

    if package_eval is None:
        reasons.add(NoTradeReasonV2.INSUFFICIENT_EVIDENCE)
    elif package_eval.status is EvidencePackageStatus.INSUFFICIENT_EVIDENCE:
        reasons.add(NoTradeReasonV2.INSUFFICIENT_EVIDENCE)
    elif package_eval.status is EvidencePackageStatus.INVALID_PROVENANCE:
        reasons.add(NoTradeReasonV2.INVALID_PROVENANCE)
    elif package_eval.status is EvidencePackageStatus.STALE_INPUT:
        reasons.add(NoTradeReasonV2.STALE_DATA)

    if validation_eval is None:
        reasons.add(NoTradeReasonV2.VALIDATION_MISSING)
    elif validation_eval.outcome is ValidationOutcomeV2.FAIL:
        reasons.add(NoTradeReasonV2.VALIDATION_FAILED)
    elif validation_eval.outcome is ValidationOutcomeV2.INSUFFICIENT_VALIDATION:
        reasons.add(NoTradeReasonV2.VALIDATION_INCONCLUSIVE)

    if validation is not None:
        for gate in validation.gates:
            if gate.outcome is ValidationGateOutcomeV2.FAIL:
                reasons.add(NoTradeReasonV2.VALIDATION_FAILED)
                if gate.gate is QualificationGateV2.REGIME_APPLICABILITY:
                    reasons.add(NoTradeReasonV2.REGIME_MISMATCH)
            elif (
                gate.gate is QualificationGateV2.RISK
                and gate.outcome is ValidationGateOutcomeV2.INSUFFICIENT_VALIDATION
            ):
                reasons.add(NoTradeReasonV2.RISK_UNAVAILABLE)

    if qualification_eval is None:
        # A completed validation without its qualification handoff is inconclusive.
        reasons.add(NoTradeReasonV2.VALIDATION_INCONCLUSIVE)
    elif qualification_eval.status is QualificationEngineStatus.NOT_QUALIFIED:
        reasons.add(NoTradeReasonV2.VALIDATION_FAILED)
    elif qualification_eval.status is QualificationEngineStatus.INSUFFICIENT_VALIDATION:
        reasons.add(NoTradeReasonV2.VALIDATION_INCONCLUSIVE)
    elif qualification_eval.status is QualificationEngineStatus.INVALID_PROVENANCE:
        reasons.add(NoTradeReasonV2.INVALID_PROVENANCE)
    elif qualification_eval.status is QualificationEngineStatus.STALE_INPUT:
        reasons.add(
            NoTradeReasonV2.VALIDATION_STALE
            if _validation_is_stale(validation, at)
            else NoTradeReasonV2.STALE_DATA
        )

    if context.expires_at <= at:
        reasons.add(NoTradeReasonV2.STALE_DATA)
    if context.as_of > at:
        reasons.add(NoTradeReasonV2.INVALID_PROVENANCE)
    if candidate is not None:
        if candidate.created_at > at:
            reasons.add(NoTradeReasonV2.INVALID_PROVENANCE)
        if candidate.expires_at <= at:
            reasons.add(NoTradeReasonV2.STALE_DATA)
    if package is not None:
        if package.created_at > at:
            reasons.add(NoTradeReasonV2.INVALID_PROVENANCE)
        if package.expires_at <= at:
            reasons.add(NoTradeReasonV2.STALE_DATA)
    if validation is not None:
        if validation.created_at > at or validation.as_of > at:
            reasons.add(NoTradeReasonV2.INVALID_PROVENANCE)
        if _validation_is_stale(validation, at):
            reasons.add(NoTradeReasonV2.VALIDATION_STALE)
    if qualification is not None:
        if qualification.evaluated_at > at:
            reasons.add(NoTradeReasonV2.INVALID_PROVENANCE)
        if qualification.expires_at <= at:
            reasons.add(NoTradeReasonV2.VALIDATION_STALE)

    if any(
        item.resolution_status is ResolutionStatus.UNRESOLVED
        or item.unsafe_to_rely is True
        for item in context.conflicts
    ):
        reasons.add(NoTradeReasonV2.UNRESOLVED_CONFLICT)
    if any(
        item.resolution_status is ResolutionStatus.UNRESOLVED
        for item in context.uncertainties
    ):
        reasons.add(NoTradeReasonV2.INSUFFICIENT_EVIDENCE)

    if _has_provenance_mismatch(
        context, candidate, eligibility, package, validation, qualification
    ):
        reasons.add(NoTradeReasonV2.INVALID_PROVENANCE)
    return tuple(reasons)


def _setup_reasons(
    reason_codes: tuple[str, ...], default: NoTradeReasonV2
) -> set[NoTradeReasonV2]:
    exact = {
        "MISSING_DATA": NoTradeReasonV2.MISSING_DATA,
        "STALE_DATA": NoTradeReasonV2.STALE_DATA,
        "INSUFFICIENT_DATA": NoTradeReasonV2.INSUFFICIENT_DATA,
        "INSUFFICIENT_EVIDENCE": NoTradeReasonV2.INSUFFICIENT_EVIDENCE,
        "UNRESOLVED_CONFLICT": NoTradeReasonV2.UNRESOLVED_CONFLICT,
        "STRATEGY_INELIGIBLE": NoTradeReasonV2.STRATEGY_INELIGIBLE,
        "NO_SETUP": NoTradeReasonV2.NO_SETUP,
        "SETUP_INVALIDATED": NoTradeReasonV2.SETUP_INVALIDATED,
        "SETUP_EXPIRED": NoTradeReasonV2.SETUP_EXPIRED,
        "SETUP_SUPERSEDED": NoTradeReasonV2.SETUP_SUPERSEDED,
        "REGIME_MISMATCH": NoTradeReasonV2.REGIME_MISMATCH,
        "EVENT_RISK": NoTradeReasonV2.EVENT_RISK,
        "SAFETY_UNAVAILABLE": NoTradeReasonV2.SAFETY_UNAVAILABLE,
        "RISK_UNAVAILABLE": NoTradeReasonV2.RISK_UNAVAILABLE,
        "INVALID_PROVENANCE": NoTradeReasonV2.INVALID_PROVENANCE,
    }
    mapped = {exact[code] for code in reason_codes if code in exact}
    return mapped or {default}


def _supported_input(value: object) -> bool:
    return type(value) in {
        SetupDetectionEvaluation,
        StrategyEligibilityEvaluation,
        EvidencePackageEvaluation,
        QualificationRuleEvaluation,
        QualificationEngineResult,
    }


def _exact_qualified_path(
    context: MarketContextV5,
    candidate: SignalCandidate | None,
    package: SignalEvidencePackageV2 | None,
    validation: QualificationValidationResultV2 | None,
    qualification_eval: QualificationEngineResult | None,
    qualification: SignalQualificationV2 | None,
    at: datetime,
) -> bool:
    if (
        candidate is None
        or package is None
        or validation is None
        or qualification_eval is None
        or qualification_eval.status is not QualificationEngineStatus.QUALIFIED
        or qualification is None
        or qualification.status is not QualificationStatus.QUALIFIED
        or qualification.contract_id != "C-025"
        or qualification.schema_version != "2"
        or validation.outcome is not ValidationOutcomeV2.PASS
        or validation.contract_id != "C-028"
        or validation.schema_version != "2"
        or context.expires_at <= at
        or candidate.expires_at <= at
        or package.expires_at <= at
        or validation.valid_until <= at
        or qualification.expires_at <= at
    ):
        return False
    candidate_ref = VersionReference(
        "C-023",
        candidate.candidate_id,
        candidate.schema_version,
        canonical_sha256(candidate),
    )
    package_ref = VersionReference(
        "C-024", package.package_id, package.schema_version, package.content_sha256
    )
    return (
        candidate.market_context_id == context.context_id
        and package.candidate == candidate_ref
        and package.market_context.artifact_id == context.context_id
        and package.market_context.content_sha256 == canonical_sha256(context)
        and validation.candidate_id == candidate.candidate_id
        and validation.candidate_sha256 == candidate_ref.content_sha256
        and validation.evidence_package_id == package.package_id
        and validation.evidence_package_sha256 == package.content_sha256
        and qualification.candidate == candidate_ref
        and qualification.evidence_package == package_ref
        and qualification.validation == validation
        and qualification.strategy_version == package.strategy_version
        and qualification.validation.valid_until >= qualification.expires_at
        and package.expires_at >= qualification.expires_at
        and all(g.outcome is ValidationGateOutcomeV2.PASS for g in validation.gates)
    )


def _has_provenance_mismatch(
    context: MarketContextV5,
    candidate: SignalCandidate | None,
    eligibility: StrategyEligibilityEvaluation | None,
    package: SignalEvidencePackageV2 | None,
    validation: QualificationValidationResultV2 | None,
    qualification: SignalQualificationV2 | None,
) -> bool:
    if candidate is not None and (
        candidate.contract_id != "C-023"
        or candidate.schema_version != "1"
        or candidate.market_context_id != context.context_id
        or candidate.asset != context.asset
        or candidate.instrument_id != context.instrument_id
    ):
        return True
    eligibility_record = eligibility.eligibility if eligibility is not None else None
    if eligibility_record is not None and (
        eligibility_record.market_context_id != context.context_id
        or (
            candidate is not None
            and eligibility_record.strategy_version_id != candidate.strategy_version_id
        )
    ):
        return True
    if package is not None:
        if (
            package.contract_id != "C-024"
            or package.schema_version != "2"
            or package.market_context.artifact_id != context.context_id
            or package.market_context.content_sha256 != canonical_sha256(context)
            or (
                candidate is not None
                and package.candidate.artifact_id != candidate.candidate_id
            )
        ):
            return True
    if validation is not None:
        if (
            validation.contract_id != "C-028"
            or validation.schema_version != "2"
            or (
                candidate is not None
                and validation.candidate_id != candidate.candidate_id
            )
            or (
                package is not None
                and validation.evidence_package_id != package.package_id
            )
            or (
                package is not None
                and validation.evidence_package_sha256 != package.content_sha256
            )
            or (
                candidate is not None
                and validation.strategy_version_id != candidate.strategy_version_id
            )
        ):
            return True
    if qualification is not None:
        if (
            qualification.contract_id != "C-025"
            or qualification.schema_version != "2"
            or (
                candidate is not None
                and qualification.candidate.artifact_id != candidate.candidate_id
            )
            or (
                package is not None
                and qualification.evidence_package.artifact_id != package.package_id
            )
            or (validation is not None and qualification.validation != validation)
        ):
            return True
    return False


def _provenance(
    context: MarketContextV5,
    candidate: SignalCandidate | None,
    eligibility: StrategyEligibilityEvaluation | None,
    package: SignalEvidencePackageV2 | None,
    validation: QualificationValidationResultV2 | None,
    qualification: SignalQualificationV2 | None,
) -> tuple[tuple[VersionReference, ...], bool]:
    refs: list[VersionReference] = [
        VersionReference(
            "C-006",
            context.context_id,
            context.schema_version,
            canonical_sha256(context),
        ),
        VersionReference(
            "C-007",
            context.analysis_snapshot.snapshot_id,
            context.analysis_snapshot.schema_version,
            context.analysis_snapshot.content_sha256,
        ),
    ]
    if candidate is not None:
        refs.append(
            VersionReference(
                "C-023",
                candidate.candidate_id,
                candidate.schema_version,
                canonical_sha256(candidate),
            )
        )
        refs.append(candidate.entry_concept.method)
    if eligibility is not None and eligibility.eligibility is not None:
        item = eligibility.eligibility
        refs.append(
            VersionReference(
                "C-022",
                item.eligibility_id,
                item.schema_version,
                canonical_sha256(item),
            )
        )
    if package is not None:
        refs.extend(_package_references(package))
        refs.append(
            VersionReference(
                "C-024",
                package.package_id,
                package.schema_version,
                package.content_sha256,
            )
        )
    if validation is not None:
        refs.append(
            VersionReference(
                "C-028",
                validation.result_id,
                validation.schema_version,
                validation.content_sha256,
            )
        )
        refs.append(
            VersionReference(
                validation.methodology.artifact_type,
                validation.methodology.artifact_id,
                validation.methodology.version,
                validation.methodology.content_sha256,
            )
        )
    if qualification is not None:
        refs.append(
            VersionReference(
                "C-025",
                qualification.qualification_id,
                qualification.schema_version,
                canonical_sha256(qualification),
            )
        )

    by_identity: dict[tuple[str, UUID, str], VersionReference] = {}
    mismatch = False
    for ref in refs:
        identity = (ref.artifact_type, ref.artifact_id, ref.version)
        previous = by_identity.get(identity)
        if previous is not None and previous.content_sha256 != ref.content_sha256:
            mismatch = True
        by_identity[identity] = ref
    ordered = tuple(
        sorted(
            by_identity.values(),
            key=lambda item: (
                item.artifact_type,
                str(item.artifact_id),
                item.version,
                item.content_sha256,
            ),
        )
    )
    return ordered, mismatch


def _package_references(
    package: SignalEvidencePackageV2,
) -> tuple[VersionReference, ...]:
    refs = [
        package.candidate,
        package.strategy_version,
        package.eligibility,
        package.market_context,
        package.analysis_snapshot,
        package.data_quality_report,
        package.confluence,
        package.dependence.assessment,
        *package.evidence_references,
        *package.conflicts,
        *package.uncertainties,
        *package.supporting_evidence,
        *package.contradictory_evidence,
    ]
    if package.adversarial_assessment is not None:
        refs.append(package.adversarial_assessment)
    refs.extend(node.reference for node in package.graph.nodes)
    refs.extend(node.method for node in package.graph.nodes)
    return tuple(refs)


def _blocking_evidence_ids(
    candidate: SignalCandidate | None,
    package: SignalEvidencePackageV2 | None,
    validation: QualificationValidationResultV2 | None,
) -> tuple[UUID, ...]:
    ids: set[UUID] = set(candidate.contradictory_evidence_ids if candidate else ())
    if package is not None:
        ids.update(item.artifact_id for item in package.contradictory_evidence)
    if validation is not None:
        ids.update(
            gate.evidence.artifact_id
            for gate in validation.gates
            if gate.outcome is not ValidationGateOutcomeV2.PASS
            and gate.evidence is not None
        )
    return tuple(sorted(ids, key=str))


def _conflict_ids(context: MarketContextV5) -> tuple[UUID, ...]:
    return tuple(
        sorted(
            {
                item.assessment_id
                for item in context.conflicts
                if item.resolution_status is ResolutionStatus.UNRESOLVED
                or item.unsafe_to_rely is True
            },
            key=str,
        )
    )


def _strategy_version_id(
    candidate: SignalCandidate | None,
    eligibility: StrategyEligibilityEvaluation | None,
    package: SignalEvidencePackageV2 | None,
    qualification: SignalQualificationV2 | None,
) -> UUID | None:
    if candidate is not None:
        return candidate.strategy_version_id
    if package is not None:
        return package.strategy_version.artifact_id
    if qualification is not None:
        return qualification.strategy_version.artifact_id
    if eligibility is not None and eligibility.eligibility is not None:
        return eligibility.eligibility.strategy_version_id
    return None


def _validation_is_stale(
    validation: QualificationValidationResultV2 | None, at: datetime
) -> bool:
    return validation is not None and (
        validation.valid_until <= at
        or any(gate.valid_until <= at for gate in validation.gates)
    )


def _decision_expiry(
    at: datetime,
    context: MarketContextV5,
    candidate: SignalCandidate | None,
    eligibility: StrategyEligibilityEvaluation | None,
    package: SignalEvidencePackageV2 | None,
    validation: QualificationValidationResultV2 | None,
    qualification: SignalQualificationV2 | None,
) -> datetime:
    boundaries = [context.expires_at]
    if candidate is not None:
        boundaries.append(candidate.expires_at)
    if eligibility is not None and eligibility.eligibility is not None:
        boundaries.append(eligibility.eligibility.expires_at)
    if package is not None:
        boundaries.append(package.expires_at)
    if validation is not None:
        boundaries.append(validation.valid_until)
        boundaries.extend(gate.valid_until for gate in validation.gates)
    if qualification is not None:
        boundaries.append(qualification.expires_at)
    earliest = min(_utc(boundary) for boundary in boundaries)
    # Stale abstention is an instantaneous decision at evaluation time. The
    # reason retains staleness, and equality prevents the artifact implying a
    # fresh validity interval for expired upstream evidence.
    return max(at, earliest)


def _reference_for_contract(
    refs: tuple[VersionReference, ...], contract_id: str, artifact_id: UUID
) -> VersionReference | None:
    matches = [
        ref
        for ref in refs
        if ref.artifact_type == contract_id and ref.artifact_id == artifact_id
    ]
    if (
        not matches
        or len({(item.version, item.content_sha256) for item in matches}) != 1
    ):
        return None
    return matches[0]


def _cannot_emit(at: datetime) -> NoTradeEngineResult:
    return NoTradeEngineResult(NoTradeEngineStatus.INSUFFICIENT_CONTEXT, (), None, at)


def _utc(value: datetime) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise ValueError("NO_TRADE timestamps must be timezone-aware")
    return value.astimezone(UTC)


__all__ = [
    "NoTradeEngineResult",
    "NoTradeEngineStatus",
    "evaluate_no_trade_v2",
]
