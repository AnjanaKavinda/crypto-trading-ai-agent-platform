from __future__ import annotations

from dataclasses import fields, replace
from datetime import timedelta
from decimal import Decimal
from uuid import uuid4

from test_strategy_evidence_package import _detect, _package, _positive_case
from test_wave3_contract_foundation import validation
from trading_platform_api.strategy import (
    QualificationEngineStatus,
    evaluate_signal_qualification_v2,
)
from trading_platform_api.validation import (
    CostAssumptionSetV2,
    QualificationGateV2,
    QualificationRuleSetV2,
    QualificationValidationResultV2,
    ValidationArtifactReferenceV2,
    ValidationGateOutcomeV2,
    ValidationOutcomeV2,
)


def inputs():
    case = _positive_case()
    candidate = _detect(case).candidate
    assert candidate is not None
    package_evaluation = _package(case, candidate=candidate)
    assert package_evaluation.package is not None
    package = package_evaluation.package
    result = validation(package)
    costs = CostAssumptionSetV2.build(
        assumption_set_id=result.cost_assumptions.assumption_set_id,
        strategy_version_id=result.strategy_version_id,
        asset=candidate.asset,
        instrument_type="SPOT",
        required_categories=result.cost_assumptions.required_categories,
        assumptions=result.cost_assumptions.assumptions,
    )
    rules = QualificationRuleSetV2.build(
        rule_set_id=result.rule_set.rule_set_id,
        version=result.rule_set.version,
        strategy_version_id=result.strategy_version_id,
        asset=candidate.asset,
        instrument_type="SPOT",
        timeframe=candidate.timeframe,
        regime=result.regime,
        conditional_event_definition=result.rule_set.conditional_event_definition,
        conditional_win_rate_threshold=result.rule_set.conditional_win_rate_threshold,
        calibration_required=result.rule_set.calibration_required,
        methodology=result.methodology,
        cost_assumption_set=ValidationArtifactReferenceV2(
            "C-027", costs.assumption_set_id, "2", costs.content_sha256
        ),
    )
    result = _rebuild_validation(
        result,
        asset=candidate.asset,
        timeframe=candidate.timeframe,
        cost_assumptions=costs,
        rule_set=rules,
        created_at=candidate.created_at,
        as_of=candidate.created_at,
    )
    return candidate, package, result


def evaluation_time(candidate):
    return candidate.created_at + timedelta(seconds=10)


def _rescope_validation(value, *, strategy_version_id=None, asset=None, timeframe=None):
    strategy_version_id = strategy_version_id or value.strategy_version_id
    asset = asset or value.asset
    timeframe = timeframe or value.timeframe
    costs = CostAssumptionSetV2.build(
        assumption_set_id=value.cost_assumptions.assumption_set_id,
        strategy_version_id=strategy_version_id,
        asset=asset,
        instrument_type=value.cost_assumptions.instrument_type,
        required_categories=value.cost_assumptions.required_categories,
        assumptions=value.cost_assumptions.assumptions,
    )
    rules = QualificationRuleSetV2.build(
        rule_set_id=value.rule_set.rule_set_id,
        version=value.rule_set.version,
        strategy_version_id=strategy_version_id,
        asset=asset,
        instrument_type=value.rule_set.instrument_type,
        timeframe=timeframe,
        regime=value.regime,
        conditional_event_definition=value.rule_set.conditional_event_definition,
        conditional_win_rate_threshold=value.rule_set.conditional_win_rate_threshold,
        calibration_required=value.rule_set.calibration_required,
        methodology=value.methodology,
        cost_assumption_set=ValidationArtifactReferenceV2(
            "C-027", costs.assumption_set_id, "2", costs.content_sha256
        ),
    )
    return _rebuild_validation(
        value,
        strategy_version_id=strategy_version_id,
        asset=asset,
        timeframe=timeframe,
        cost_assumptions=costs,
        rule_set=rules,
    )


def _rebuild_validation(value, **changes):
    values = {
        item.name: getattr(value, item.name)
        for item in fields(value)
        if item.name not in {"content_sha256", "contract_id", "schema_version"}
    }
    values.update(changes)
    return QualificationValidationResultV2.build(**values)


def test_exact_spot_candidate_package_and_validation_produce_deterministic_c025v2():
    candidate, package, result = inputs()
    first = evaluate_signal_qualification_v2(
        candidate=candidate,
        evidence_package=package,
        validation=result,
        evaluated_at=evaluation_time(candidate),
    )
    second = evaluate_signal_qualification_v2(
        candidate=candidate,
        evidence_package=package,
        validation=result,
        evaluated_at=evaluation_time(candidate),
    )

    assert first.status is QualificationEngineStatus.QUALIFIED
    assert first.qualification is not None
    assert first.qualification == second.qualification
    assert first.qualification.schema_version == "2"
    assert first.qualification.validation is result
    assert first.qualification.status.value == "QUALIFIED"
    assert first.qualification.expires_at == min(
        candidate.expires_at, package.expires_at, result.valid_until
    )
    assert candidate.analytical_confidence == 0
    assert candidate.evidence_strength == 0


def test_authoritative_validation_failure_produces_only_rejected_c025():
    candidate, package, result = inputs()
    failed = _rebuild_validation(
        result,
        outcome=ValidationOutcomeV2.FAIL,
        gates=tuple(
            replace(gate, outcome=ValidationGateOutcomeV2.FAIL)
            if gate.gate is QualificationGateV2.OOS
            else gate
            for gate in result.gates
        ),
    )
    evaluated = evaluate_signal_qualification_v2(
        candidate=candidate,
        evidence_package=package,
        validation=failed,
        evaluated_at=evaluation_time(candidate),
    )
    assert evaluated.status is QualificationEngineStatus.NOT_QUALIFIED
    assert evaluated.qualification is not None
    assert evaluated.qualification.status.value == "REJECTED"


def test_missing_or_insufficient_validation_fails_closed_without_c025():
    candidate, package, result = inputs()
    missing = evaluate_signal_qualification_v2(
        candidate=candidate,
        evidence_package=package,
        validation=None,
        evaluated_at=evaluation_time(candidate),
    )
    insufficient = _rebuild_validation(
        result, outcome=ValidationOutcomeV2.INSUFFICIENT_VALIDATION
    )
    evaluated = evaluate_signal_qualification_v2(
        candidate=candidate,
        evidence_package=package,
        validation=insufficient,
        evaluated_at=evaluation_time(candidate),
    )
    assert missing.status is QualificationEngineStatus.INSUFFICIENT_VALIDATION
    assert missing.qualification is None
    assert evaluated.status is QualificationEngineStatus.INSUFFICIENT_VALIDATION
    assert evaluated.qualification is None

    insufficient_gate = _rebuild_validation(
        result,
        outcome=ValidationOutcomeV2.INSUFFICIENT_VALIDATION,
        gates=tuple(
            replace(
                gate,
                outcome=ValidationGateOutcomeV2.INSUFFICIENT_VALIDATION,
                evidence=None,
            )
            if gate.gate is QualificationGateV2.SAMPLE_SUFFICIENCY
            else gate
            for gate in result.gates
        ),
    )
    gate_result = evaluate_signal_qualification_v2(
        candidate=candidate,
        evidence_package=package,
        validation=insufficient_gate,
        evaluated_at=evaluation_time(candidate),
    )
    assert gate_result.status is QualificationEngineStatus.INSUFFICIENT_VALIDATION
    assert gate_result.qualification is None


def test_missing_candidate_or_evidence_package_and_unsupported_validation_fail_closed():
    candidate, package, result = inputs()
    for values in (
        {"candidate": None, "evidence_package": package, "validation": result},
        {"candidate": candidate, "evidence_package": None, "validation": result},
        {"candidate": candidate, "evidence_package": package, "validation": None},
    ):
        evaluated = evaluate_signal_qualification_v2(
            **values, evaluated_at=evaluation_time(candidate)
        )
        assert evaluated.status is QualificationEngineStatus.INSUFFICIENT_VALIDATION
        assert evaluated.qualification is None

    unsupported = evaluate_signal_qualification_v2(
        candidate=candidate,
        evidence_package=package,
        validation=object(),  # type: ignore[arg-type]
        evaluated_at=evaluation_time(candidate),
    )
    assert unsupported.status is QualificationEngineStatus.INVALID_PROVENANCE
    assert unsupported.qualification is None


def test_candidate_identity_digest_strategy_and_package_binding_mismatches_fail_closed():
    candidate, package, result = inputs()
    variants = (
        replace(candidate, candidate_id=uuid4()),
        replace(candidate, analytical_confidence=Decimal("0.1")),
        replace(candidate, strategy_version_id=uuid4()),
    )
    for wrong_candidate in variants:
        evaluated = evaluate_signal_qualification_v2(
            candidate=wrong_candidate,
            evidence_package=package,
            validation=result,
            evaluated_at=evaluation_time(candidate),
        )
        assert evaluated.status is QualificationEngineStatus.INVALID_PROVENANCE
        assert evaluated.qualification is None

    wrong_package = _rebuild_validation(
        result,
        evidence_package_id=uuid4(),
        evidence_package_sha256="b" * 64,
    )
    evaluated = evaluate_signal_qualification_v2(
        candidate=candidate,
        evidence_package=package,
        validation=wrong_package,
        evaluated_at=evaluation_time(candidate),
    )
    assert evaluated.status is QualificationEngineStatus.INVALID_PROVENANCE
    assert evaluated.qualification is None

    wrong_strategy = _rescope_validation(result, strategy_version_id=uuid4())
    evaluated = evaluate_signal_qualification_v2(
        candidate=candidate,
        evidence_package=package,
        validation=wrong_strategy,
        evaluated_at=evaluation_time(candidate),
    )
    assert evaluated.status is QualificationEngineStatus.INVALID_PROVENANCE
    assert evaluated.qualification is None

    wrong_scope = _rescope_validation(result, asset="ETH")
    evaluated = evaluate_signal_qualification_v2(
        candidate=candidate,
        evidence_package=package,
        validation=wrong_scope,
        evaluated_at=evaluation_time(candidate),
    )
    assert evaluated.status is QualificationEngineStatus.INVALID_PROVENANCE
    assert evaluated.qualification is None


def test_stale_and_future_validation_are_rejected_without_c025():
    candidate, package, result = inputs()
    stale = evaluate_signal_qualification_v2(
        candidate=candidate,
        evidence_package=package,
        validation=result,
        evaluated_at=package.expires_at,
    )
    future = _rebuild_validation(
        result,
        created_at=evaluation_time(candidate) + timedelta(minutes=1),
        as_of=evaluation_time(candidate) + timedelta(minutes=1),
    )
    future_result = evaluate_signal_qualification_v2(
        candidate=candidate,
        evidence_package=package,
        validation=future,
        evaluated_at=evaluation_time(candidate),
    )
    assert stale.status is QualificationEngineStatus.STALE_INPUT
    assert stale.qualification is None
    assert future_result.status is QualificationEngineStatus.INVALID_PROVENANCE
    assert future_result.qualification is None


def test_missing_inputs_and_unsupported_package_schema_fail_closed():
    candidate, package, result = inputs()
    missing_package = evaluate_signal_qualification_v2(
        candidate=candidate,
        evidence_package=None,
        validation=result,
        evaluated_at=evaluation_time(candidate),
    )
    unsupported = evaluate_signal_qualification_v2(
        candidate=candidate,
        evidence_package=object(),  # type: ignore[arg-type]
        validation=result,
        evaluated_at=evaluation_time(candidate),
    )
    assert missing_package.status is QualificationEngineStatus.INSUFFICIENT_VALIDATION
    assert unsupported.status is QualificationEngineStatus.INVALID_PROVENANCE
    assert unsupported.qualification is None


def test_high_candidate_confidence_cannot_replace_missing_authoritative_validation():
    candidate, package, _ = inputs()
    confident_candidate = replace(candidate, analytical_confidence=Decimal("0.99"))
    evaluated = evaluate_signal_qualification_v2(
        candidate=confident_candidate,
        evidence_package=package,
        validation=None,
        evaluated_at=evaluation_time(confident_candidate),
    )
    assert evaluated.status is QualificationEngineStatus.INSUFFICIENT_VALIDATION
    assert evaluated.qualification is None
