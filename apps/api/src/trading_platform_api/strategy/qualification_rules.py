from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from uuid import UUID, uuid5

from trading_platform_api.contracts.serialization import canonical_sha256
from trading_platform_api.strategy.contracts import SignalCandidate, VersionReference
from trading_platform_api.strategy.contracts_v2 import SignalEvidencePackageV2
from trading_platform_api.validation.contracts_v2 import (
    CostApplicabilityV2,
    CostAssumptionSetV2,
    QualificationGateResultV2,
    QualificationGateV2,
    QualificationRuleSetV2,
    QualificationValidationResultV2,
    StatisticalSupportStateV2,
    StatisticalUncertaintyEvidenceV2,
    ValidationArtifactReferenceV2,
    ValidationContractError,
    ValidationGateOutcomeV2,
    ValidationOutcomeV2,
)

_EVALUATION_NAMESPACE = UUID("32d42945-3b77-5f3a-8910-e975de3884fa")
_DERIVED_GATES = {
    QualificationGateV2.THRESHOLD,
    QualificationGateV2.STATISTICAL_SUPPORT,
    QualificationGateV2.EXPECTANCY_AFTER_COSTS,
    QualificationGateV2.COST_APPLICABILITY,
}
_UPSTREAM_GATES = set(QualificationGateV2) - _DERIVED_GATES
_GATE_SOURCES: dict[QualificationGateV2, dict[str, set[str]]] = {
    QualificationGateV2.DATA_INTEGRITY: {
        "C-003": {"1", "2"},
        "C-027": {"1"},
    },
    QualificationGateV2.POINT_IN_TIME: {
        "C-027": {"1"},
        "C-092": {"1"},
    },
    QualificationGateV2.SAMPLE_SUFFICIENCY: {
        "C-029": {"1"},
        "C-071": {"1"},
    },
    QualificationGateV2.OOS: {"C-071": {"1"}},
    QualificationGateV2.WALK_FORWARD: {"C-029": {"1"}},
    QualificationGateV2.ROBUSTNESS: {"C-030": {"1"}},
    QualificationGateV2.BIAS_LEAKAGE: {"C-094": {"1"}},
    QualificationGateV2.RISK: {
        "C-035": {"1"},
        "C-082": {"1"},
        "C-083": {"1"},
    },
    QualificationGateV2.REGIME_APPLICABILITY: {"C-074": {"1"}},
}


class QualificationEvaluationReason(StrEnum):
    INPUT_SCOPE_MISMATCH = "INPUT_SCOPE_MISMATCH"
    METHODOLOGY_MISMATCH = "METHODOLOGY_MISMATCH"
    COST_CONFIGURATION_MISMATCH = "COST_CONFIGURATION_MISMATCH"
    REQUIRED_CONFIGURATION_MISSING = "REQUIRED_CONFIGURATION_MISSING"
    INVALID_EVIDENCE_REFERENCE = "INVALID_EVIDENCE_REFERENCE"
    DUPLICATE_OR_UNEXPECTED_GATE = "DUPLICATE_OR_UNEXPECTED_GATE"
    STALE_EVIDENCE = "STALE_EVIDENCE"
    THRESHOLD_EVIDENCE_MISSING = "THRESHOLD_EVIDENCE_MISSING"
    THRESHOLD_BELOW_CONFIG = "THRESHOLD_BELOW_CONFIG"
    SAMPLE_EVIDENCE_INSUFFICIENT = "SAMPLE_EVIDENCE_INSUFFICIENT"
    STATISTICAL_SUPPORT_MISSING = "STATISTICAL_SUPPORT_MISSING"
    STATISTICAL_SUPPORT_FAILED = "STATISTICAL_SUPPORT_FAILED"
    EXPECTANCY_EVIDENCE_MISSING = "EXPECTANCY_EVIDENCE_MISSING"
    EXPECTANCY_NOT_POSITIVE = "EXPECTANCY_NOT_POSITIVE"
    COST_APPLICABILITY_UNKNOWN = "COST_APPLICABILITY_UNKNOWN"
    REQUIRED_GATE_MISSING = "REQUIRED_GATE_MISSING"
    AUTHORITATIVE_GATE_FAILED = "AUTHORITATIVE_GATE_FAILED"
    CALIBRATION_REQUIRED = "CALIBRATION_REQUIRED"


@dataclass(frozen=True, slots=True)
class QualificationRuleEvaluationInput:
    """Exact Spot candidate, v2 evidence package, rule config and Chat 7 evidence."""

    candidate: SignalCandidate
    candidate_reference: VersionReference
    evidence_package: SignalEvidencePackageV2
    rule_set: QualificationRuleSetV2
    cost_assumptions: CostAssumptionSetV2
    observed_conditional_win_rate: Decimal | None
    threshold_evidence: ValidationArtifactReferenceV2 | None
    sample_size: int | None
    effective_sample_size: Decimal | None
    sample_semantics: ValidationArtifactReferenceV2 | None
    after_cost_expectancy: Decimal | None
    expectancy_unit: str | None
    expectancy_evidence: ValidationArtifactReferenceV2 | None
    statistical_uncertainty: StatisticalUncertaintyEvidenceV2 | None
    statistical_support_state: StatisticalSupportStateV2
    calibration: ValidationArtifactReferenceV2 | None
    authoritative_gates: tuple[QualificationGateResultV2, ...]
    methodology: ValidationArtifactReferenceV2
    evaluated_at: datetime


@dataclass(frozen=True, slots=True)
class QualificationRuleEvaluation:
    """Runtime-local #87 result; it is not a C-025 qualification."""

    outcome: ValidationOutcomeV2
    validation: QualificationValidationResultV2 | None
    reasons: tuple[QualificationEvaluationReason, ...]
    evaluated_at: datetime


def evaluate_qualification_rules(
    value: QualificationRuleEvaluationInput,
) -> QualificationRuleEvaluation:
    """Evaluate configured #87 gates and emit C-028v2 when inputs are current.

    Chat 7 measurements and upstream gates are consumed as typed evidence. This
    function performs no backtest, sampling, confidence-interval, expectancy,
    risk, or regime calculation. It only compares the observed rate with the
    bound rule-set threshold, classifies the supplied after-cost expectancy,
    validates explicit cost applicability, and aggregates authoritative gates.
    """

    evaluated_at = _aware_time(value.evaluated_at)
    reasons: list[QualificationEvaluationReason] = []
    if (
        not isinstance(value.evidence_package, SignalEvidencePackageV2)
        or not isinstance(value.rule_set, QualificationRuleSetV2)
        or not isinstance(value.cost_assumptions, CostAssumptionSetV2)
    ):
        return _insufficient(
            evaluated_at, QualificationEvaluationReason.REQUIRED_CONFIGURATION_MISSING
        )
    if value.rule_set.methodology != value.methodology:
        return _insufficient(
            evaluated_at, QualificationEvaluationReason.METHODOLOGY_MISMATCH
        )
    if not _scope_matches(value):
        return _insufficient(
            evaluated_at, QualificationEvaluationReason.INPUT_SCOPE_MISMATCH
        )
    invalid = _input_problem(value)
    if invalid:
        return _insufficient(evaluated_at, *invalid)
    if value.rule_set.calibration_required and value.calibration is None:
        return _insufficient(
            evaluated_at, QualificationEvaluationReason.CALIBRATION_REQUIRED
        )
    if value.calibration is not None and (
        value.calibration.artifact_type != "C-031" or value.calibration.version != "1"
    ):
        return _insufficient(
            evaluated_at, QualificationEvaluationReason.INVALID_EVIDENCE_REFERENCE
        )
    if value.statistical_uncertainty is not None and (
        value.statistical_uncertainty.methodology != value.methodology
    ):
        return _insufficient(
            evaluated_at, QualificationEvaluationReason.METHODOLOGY_MISMATCH
        )

    package_expiry = _aware_time(value.evidence_package.expires_at)
    candidate_expiry = _aware_time(value.candidate.expires_at)
    external_gates, gate_reasons = _normalize_upstream_gates(value.authoritative_gates)
    reasons.extend(gate_reasons)
    known_expiries = [package_expiry, candidate_expiry]
    known_expiries.extend(g.valid_until for g in external_gates.values())
    if any(expiry <= evaluated_at for expiry in known_expiries):
        return _insufficient(evaluated_at, QualificationEvaluationReason.STALE_EVIDENCE)
    valid_until = min(known_expiries)

    gates: dict[QualificationGateV2, QualificationGateResultV2] = dict(external_gates)
    for gate in _UPSTREAM_GATES - set(gates):
        gates[gate] = QualificationGateResultV2(
            gate,
            ValidationGateOutcomeV2.INSUFFICIENT_VALIDATION,
            None,
            valid_until,
        )
        reasons.append(QualificationEvaluationReason.REQUIRED_GATE_MISSING)

    gates[QualificationGateV2.THRESHOLD] = _threshold_gate(value, valid_until, reasons)
    gates[QualificationGateV2.SAMPLE_SUFFICIENCY] = _sample_gate(
        gates[QualificationGateV2.SAMPLE_SUFFICIENCY], value, valid_until, reasons
    )
    gates[QualificationGateV2.STATISTICAL_SUPPORT] = _statistical_support_gate(
        value, valid_until, reasons
    )
    gates[QualificationGateV2.EXPECTANCY_AFTER_COSTS] = _expectancy_gate(
        value, valid_until, reasons
    )
    gates[QualificationGateV2.COST_APPLICABILITY] = _cost_gate(
        value, valid_until, reasons
    )

    ordered_gates = tuple(gates[gate] for gate in QualificationGateV2)
    if any(gate.valid_until < valid_until for gate in ordered_gates):
        return _insufficient(evaluated_at, QualificationEvaluationReason.STALE_EVIDENCE)

    outcomes = tuple(gate.outcome for gate in ordered_gates)
    if ValidationGateOutcomeV2.FAIL not in outcomes and any(
        reason
        in {
            QualificationEvaluationReason.INVALID_EVIDENCE_REFERENCE,
            QualificationEvaluationReason.DUPLICATE_OR_UNEXPECTED_GATE,
        }
        for reason in reasons
    ):
        gates[QualificationGateV2.DATA_INTEGRITY] = _gate(
            QualificationGateV2.DATA_INTEGRITY,
            ValidationGateOutcomeV2.INSUFFICIENT_VALIDATION,
            None,
            valid_until,
        )
        ordered_gates = tuple(gates[gate] for gate in QualificationGateV2)
        outcomes = tuple(gate.outcome for gate in ordered_gates)
    if ValidationGateOutcomeV2.FAIL in outcomes:
        outcome = ValidationOutcomeV2.FAIL
    elif any(state is not ValidationGateOutcomeV2.PASS for state in outcomes):
        outcome = ValidationOutcomeV2.INSUFFICIENT_VALIDATION
    else:
        outcome = ValidationOutcomeV2.PASS

    fingerprint = _input_fingerprint(value, ordered_gates, outcome, valid_until)
    result_id = uuid5(_EVALUATION_NAMESPACE, fingerprint)
    try:
        result = QualificationValidationResultV2.build(
            result_id=result_id,
            candidate_id=value.candidate_reference.artifact_id,
            candidate_sha256=value.candidate_reference.content_sha256,
            evidence_package_id=value.evidence_package.package_id,
            evidence_package_sha256=value.evidence_package.content_sha256,
            strategy_version_id=value.candidate.strategy_version_id,
            asset=value.candidate.asset,
            instrument_type=value.rule_set.instrument_type,
            timeframe=value.candidate.timeframe,
            regime=value.rule_set.regime,
            rule_set=value.rule_set,
            cost_assumptions=value.cost_assumptions,
            observed_conditional_win_rate=value.observed_conditional_win_rate,
            sample_size=value.sample_size,
            effective_sample_size=value.effective_sample_size,
            sample_semantics=value.sample_semantics,
            after_cost_expectancy=value.after_cost_expectancy,
            expectancy_unit=value.expectancy_unit,
            statistical_uncertainty=value.statistical_uncertainty,
            statistical_support_state=value.statistical_support_state,
            calibration=value.calibration,
            gates=ordered_gates,
            outcome=outcome,
            methodology=value.methodology,
            created_at=evaluated_at,
            as_of=evaluated_at,
            valid_until=valid_until,
        )
    except ValidationContractError:
        return _insufficient(
            evaluated_at,
            *dict.fromkeys(
                (*reasons, QualificationEvaluationReason.REQUIRED_CONFIGURATION_MISSING)
            ),
        )
    return QualificationRuleEvaluation(
        outcome=result.outcome,
        validation=result,
        reasons=tuple(dict.fromkeys(reasons)),
        evaluated_at=evaluated_at,
    )


def _input_problem(
    value: QualificationRuleEvaluationInput,
) -> tuple[QualificationEvaluationReason, ...]:
    reasons: list[QualificationEvaluationReason] = []
    if (
        value.candidate_reference.artifact_type != "C-023"
        or value.candidate_reference.version != "1"
        or value.evidence_package.candidate != value.candidate_reference
        or value.evidence_package.schema_version != "2"
        or value.evidence_package.strategy_version.artifact_id
        != value.candidate.strategy_version_id
        or value.evidence_package.candidate.artifact_id != value.candidate.candidate_id
        or value.evidence_package.market_context.artifact_id
        != value.candidate.market_context_id
        or value.evidence_package.analysis_snapshot.artifact_id
        != value.candidate.analysis_snapshot_id
        or value.evidence_package.data_quality_report.artifact_id
        != value.candidate.data_quality_report_id
        or value.rule_set.strategy_version_id != value.candidate.strategy_version_id
        or value.rule_set.asset != value.candidate.asset
        or value.rule_set.timeframe != value.candidate.timeframe
        or value.rule_set.instrument_type != "SPOT"
        or value.cost_assumptions.instrument_type != "SPOT"
    ):
        reasons.append(QualificationEvaluationReason.INPUT_SCOPE_MISMATCH)
    if (
        value.sample_semantics is None
        or value.cost_assumptions.strategy_version_id
        != value.rule_set.strategy_version_id
        or value.cost_assumptions.asset != value.rule_set.asset
        or value.cost_assumptions.instrument_type != value.rule_set.instrument_type
        or value.rule_set.cost_assumption_set != _cost_reference(value.cost_assumptions)
    ):
        reasons.append(QualificationEvaluationReason.REQUIRED_CONFIGURATION_MISSING)
    if not isinstance(value.statistical_support_state, StatisticalSupportStateV2):
        reasons.append(QualificationEvaluationReason.STATISTICAL_SUPPORT_MISSING)
    return tuple(reasons)


def _scope_matches(value: QualificationRuleEvaluationInput) -> bool:
    return (
        value.candidate.lifecycle.value == "CANDIDATE"
        and value.candidate_reference.artifact_id == value.candidate.candidate_id
        and value.evidence_package.strategy_version.artifact_id
        == value.rule_set.strategy_version_id
        and value.evidence_package.strategy_version.version == "1"
        and value.rule_set.asset == value.candidate.asset
        and value.rule_set.timeframe == value.candidate.timeframe
        and value.rule_set.instrument_type == "SPOT"
        and value.cost_assumptions.strategy_version_id
        == value.candidate.strategy_version_id
        and value.cost_assumptions.asset == value.candidate.asset
        and value.cost_assumptions.instrument_type == "SPOT"
    )


def _normalize_upstream_gates(
    values: tuple[QualificationGateResultV2, ...],
) -> tuple[
    dict[QualificationGateV2, QualificationGateResultV2],
    tuple[QualificationEvaluationReason, ...],
]:
    normalized: dict[QualificationGateV2, QualificationGateResultV2] = {}
    reasons: list[QualificationEvaluationReason] = []
    for item in values:
        if not isinstance(item, QualificationGateResultV2):
            reasons.append(QualificationEvaluationReason.INVALID_EVIDENCE_REFERENCE)
            continue
        if item.gate not in _UPSTREAM_GATES or item.gate in normalized:
            reasons.append(QualificationEvaluationReason.DUPLICATE_OR_UNEXPECTED_GATE)
            continue
        if item.evidence is not None and not _gate_reference_supported(
            item.gate, item.evidence
        ):
            normalized[item.gate] = QualificationGateResultV2(
                item.gate,
                ValidationGateOutcomeV2.INSUFFICIENT_VALIDATION,
                item.evidence,
                item.valid_until,
            )
            reasons.append(QualificationEvaluationReason.INVALID_EVIDENCE_REFERENCE)
            continue
        normalized[item.gate] = item
    return normalized, tuple(reasons)


def _gate_reference_supported(
    gate: QualificationGateV2, evidence: ValidationArtifactReferenceV2
) -> bool:
    versions = _GATE_SOURCES.get(gate)
    return versions is not None and evidence.version in versions.get(
        evidence.artifact_type, set()
    )


def _threshold_gate(
    value: QualificationRuleEvaluationInput,
    valid_until: datetime,
    reasons: list[QualificationEvaluationReason],
) -> QualificationGateResultV2:
    evidence = value.threshold_evidence
    if value.observed_conditional_win_rate is None:
        reasons.append(QualificationEvaluationReason.THRESHOLD_EVIDENCE_MISSING)
        return _gate(
            QualificationGateV2.THRESHOLD,
            ValidationGateOutcomeV2.INSUFFICIENT_VALIDATION,
            None,
            valid_until,
        )
    if not _metric_ref_supported(evidence, {"C-071": {"1"}}):
        reasons.append(QualificationEvaluationReason.THRESHOLD_EVIDENCE_MISSING)
        return _gate(
            QualificationGateV2.THRESHOLD,
            ValidationGateOutcomeV2.INSUFFICIENT_VALIDATION,
            None,
            valid_until,
        )
    if (
        value.observed_conditional_win_rate
        < value.rule_set.conditional_win_rate_threshold
    ):
        reasons.append(QualificationEvaluationReason.THRESHOLD_BELOW_CONFIG)
        outcome = ValidationGateOutcomeV2.FAIL
    else:
        outcome = ValidationGateOutcomeV2.PASS
    return _gate(QualificationGateV2.THRESHOLD, outcome, evidence, valid_until)


def _sample_gate(
    gate: QualificationGateResultV2,
    value: QualificationRuleEvaluationInput,
    valid_until: datetime,
    reasons: list[QualificationEvaluationReason],
) -> QualificationGateResultV2:
    if value.sample_size is None or value.sample_size == 0:
        if gate.outcome is ValidationGateOutcomeV2.FAIL:
            return gate
        reasons.append(QualificationEvaluationReason.SAMPLE_EVIDENCE_INSUFFICIENT)
        return _gate(
            QualificationGateV2.SAMPLE_SUFFICIENCY,
            ValidationGateOutcomeV2.INSUFFICIENT_VALIDATION,
            gate.evidence,
            valid_until,
        )
    if gate.outcome is not ValidationGateOutcomeV2.PASS:
        reasons.append(QualificationEvaluationReason.SAMPLE_EVIDENCE_INSUFFICIENT)
    return gate


def _statistical_support_gate(
    value: QualificationRuleEvaluationInput,
    valid_until: datetime,
    reasons: list[QualificationEvaluationReason],
) -> QualificationGateResultV2:
    uncertainty = value.statistical_uncertainty
    supported_result = (
        uncertainty is not None
        and uncertainty.result.artifact_type in {"C-071", "C-029"}
        and uncertainty.result.version == "1"
    )
    evidence = (
        uncertainty.result if uncertainty is not None and supported_result else None
    )
    if (
        value.statistical_support_state is StatisticalSupportStateV2.SUPPORTED
        and supported_result
    ):
        return _gate(
            QualificationGateV2.STATISTICAL_SUPPORT,
            ValidationGateOutcomeV2.PASS,
            evidence,
            valid_until,
        )
    if (
        value.statistical_support_state is StatisticalSupportStateV2.NOT_SUPPORTED
        and supported_result
    ):
        reasons.append(QualificationEvaluationReason.STATISTICAL_SUPPORT_FAILED)
        return _gate(
            QualificationGateV2.STATISTICAL_SUPPORT,
            ValidationGateOutcomeV2.FAIL,
            evidence,
            valid_until,
        )
    reasons.append(QualificationEvaluationReason.STATISTICAL_SUPPORT_MISSING)
    return _gate(
        QualificationGateV2.STATISTICAL_SUPPORT,
        ValidationGateOutcomeV2.INSUFFICIENT_VALIDATION,
        evidence,
        valid_until,
    )


def _expectancy_gate(
    value: QualificationRuleEvaluationInput,
    valid_until: datetime,
    reasons: list[QualificationEvaluationReason],
) -> QualificationGateResultV2:
    evidence = value.expectancy_evidence
    if value.after_cost_expectancy is None or not value.expectancy_unit:
        reasons.append(QualificationEvaluationReason.EXPECTANCY_EVIDENCE_MISSING)
        return _gate(
            QualificationGateV2.EXPECTANCY_AFTER_COSTS,
            ValidationGateOutcomeV2.INSUFFICIENT_VALIDATION,
            None,
            valid_until,
        )
    if not _metric_ref_supported(
        evidence,
        {"C-071": {"1"}, "C-029": {"1"}},
    ):
        reasons.append(QualificationEvaluationReason.EXPECTANCY_EVIDENCE_MISSING)
        return _gate(
            QualificationGateV2.EXPECTANCY_AFTER_COSTS,
            ValidationGateOutcomeV2.INSUFFICIENT_VALIDATION,
            None,
            valid_until,
        )
    if value.after_cost_expectancy <= 0:
        reasons.append(QualificationEvaluationReason.EXPECTANCY_NOT_POSITIVE)
        outcome = ValidationGateOutcomeV2.FAIL
    else:
        outcome = ValidationGateOutcomeV2.PASS
    return _gate(
        QualificationGateV2.EXPECTANCY_AFTER_COSTS, outcome, evidence, valid_until
    )


def _cost_gate(
    value: QualificationRuleEvaluationInput,
    valid_until: datetime,
    reasons: list[QualificationEvaluationReason],
) -> QualificationGateResultV2:
    assumptions = {item.category: item for item in value.cost_assumptions.assumptions}
    required = value.cost_assumptions.required_categories
    unknown = any(
        assumptions[category].applicability is CostApplicabilityV2.UNKNOWN
        for category in required
    )
    if unknown:
        reasons.append(QualificationEvaluationReason.COST_APPLICABILITY_UNKNOWN)
        outcome = ValidationGateOutcomeV2.INSUFFICIENT_VALIDATION
    else:
        outcome = ValidationGateOutcomeV2.PASS
    return _gate(
        QualificationGateV2.COST_APPLICABILITY,
        outcome,
        _cost_reference(value.cost_assumptions),
        valid_until,
    )


def _metric_ref_supported(
    value: ValidationArtifactReferenceV2 | None,
    allowed: dict[str, set[str]],
) -> bool:
    return value is not None and value.version in allowed.get(
        value.artifact_type, set()
    )


def _cost_reference(
    costs: CostAssumptionSetV2,
) -> ValidationArtifactReferenceV2:
    return ValidationArtifactReferenceV2(
        "C-027", costs.assumption_set_id, "2", costs.content_sha256
    )


def _gate(
    gate: QualificationGateV2,
    outcome: ValidationGateOutcomeV2,
    evidence: ValidationArtifactReferenceV2 | None,
    valid_until: datetime,
) -> QualificationGateResultV2:
    return QualificationGateResultV2(gate, outcome, evidence, valid_until)


def _input_fingerprint(
    value: QualificationRuleEvaluationInput,
    gates: tuple[QualificationGateResultV2, ...],
    outcome: ValidationOutcomeV2,
    valid_until: datetime,
) -> str:
    # Deliberately exclude C-023 analytical_confidence/evidence_strength values.
    return canonical_sha256(
        {
            "candidate_reference": value.candidate_reference,
            "candidate_scope": {
                "candidate_id": value.candidate.candidate_id,
                "strategy_version_id": value.candidate.strategy_version_id,
                "asset": value.candidate.asset,
                "instrument_id": value.candidate.instrument_id,
                "timeframe": value.candidate.timeframe,
                "created_at": value.candidate.created_at,
                "expires_at": value.candidate.expires_at,
            },
            "evidence_package": (
                value.evidence_package.package_id,
                value.evidence_package.content_sha256,
            ),
            "rule_set": value.rule_set,
            "cost_assumptions": value.cost_assumptions,
            "observed_conditional_win_rate": value.observed_conditional_win_rate,
            "threshold_evidence": value.threshold_evidence,
            "sample_size": value.sample_size,
            "effective_sample_size": value.effective_sample_size,
            "sample_semantics": value.sample_semantics,
            "after_cost_expectancy": value.after_cost_expectancy,
            "expectancy_unit": value.expectancy_unit,
            "expectancy_evidence": value.expectancy_evidence,
            "statistical_uncertainty": value.statistical_uncertainty,
            "statistical_support_state": value.statistical_support_state,
            "calibration": value.calibration,
            "gates": gates,
            "methodology": value.methodology,
            "evaluated_at": value.evaluated_at,
            "valid_until": valid_until,
            "outcome": outcome,
        }
    )


def _aware_time(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("evaluation time must be timezone-aware.")
    return value.astimezone(UTC)


def _insufficient(
    evaluated_at: datetime,
    *reasons: QualificationEvaluationReason,
) -> QualificationRuleEvaluation:
    return QualificationRuleEvaluation(
        outcome=ValidationOutcomeV2.INSUFFICIENT_VALIDATION,
        validation=None,
        reasons=tuple(dict.fromkeys(reasons)),
        evaluated_at=evaluated_at,
    )


__all__ = [
    "QualificationEvaluationReason",
    "QualificationRuleEvaluation",
    "QualificationRuleEvaluationInput",
    "evaluate_qualification_rules",
]
