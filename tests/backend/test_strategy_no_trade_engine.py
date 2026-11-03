from __future__ import annotations

from dataclasses import fields, replace
from datetime import timedelta
from uuid import uuid4

import pytest
from test_qualification_rule_evaluator import request
from test_strategy_evidence_package import _package
from test_strategy_setup_detection import _detect, _positive_case
from trading_platform_api.contracts.serialization import canonical_sha256
from trading_platform_api.strategy import (
    EligibilityState,
    EvidencePackageEvaluation,
    EvidencePackageStatus,
    NoTradeEngineStatus,
    NoTradeReasonV2,
    QualificationEngineStatus,
    SetupDetectionOutcome,
    evaluate_no_trade_v2,
    evaluate_qualification_rules,
    evaluate_signal_qualification_v2,
)
from trading_platform_api.validation import (
    QualificationGateResultV2,
    QualificationGateV2,
    ValidationGateOutcomeV2,
    ValidationOutcomeV2,
)


def _chain(
    *,
    failed_gate: QualificationGateV2 | None = None,
    insufficient_gate: QualificationGateV2 | None = None,
):
    case = _positive_case()
    setup = _detect(case)
    assert setup.candidate is not None
    candidate = setup.candidate
    package_evaluation = _package(case, candidate=candidate)
    assert package_evaluation.package is not None
    package = package_evaluation.package
    evaluated_at = candidate.created_at + timedelta(seconds=10)
    rule_input = request(
        candidate=candidate,
        evidence_package=package,
        evaluated_at=evaluated_at,
    )
    if failed_gate is not None or insufficient_gate is not None:
        rule_input = replace(
            rule_input,
            authoritative_gates=tuple(
                QualificationGateResultV2(
                    gate.gate,
                    ValidationGateOutcomeV2.FAIL
                    if gate.gate is failed_gate
                    else ValidationGateOutcomeV2.INSUFFICIENT_VALIDATION
                    if gate.gate is insufficient_gate
                    else gate.outcome,
                    gate.evidence,
                    gate.valid_until,
                )
                for gate in rule_input.authoritative_gates
            ),
        )
    validation = evaluate_qualification_rules(rule_input)
    qualification = evaluate_signal_qualification_v2(
        candidate=candidate,
        evidence_package=package,
        validation=validation.validation,
        evaluated_at=evaluated_at + timedelta(seconds=1),
    )
    return case, setup, package_evaluation, validation, qualification, evaluated_at


def _evaluate(case, setup, package, validation, qualification, at):
    return evaluate_no_trade_v2(
        market_context=case[2].market_context,
        setup=setup,
        eligibility=case[6],
        evidence_package=package,
        validation=validation,
        qualification=qualification,
        evaluated_at=at,
        correlation_id="spot-no-trade-test",
    )


def test_exact_wave3_qualified_path_suppresses_c026():
    case, setup, package, validation, qualification, at = _chain()

    assert validation.outcome is ValidationOutcomeV2.PASS
    assert qualification.status is QualificationEngineStatus.QUALIFIED
    result = _evaluate(case, setup, package, validation, qualification, at)

    assert result.status is NoTradeEngineStatus.NO_TRADE_NOT_APPLICABLE
    assert result.decision is None
    assert result.reasons == ()


def test_exact_wave3_rejected_path_emits_deterministic_c026():
    case, setup, package, validation, qualification, at = _chain(
        failed_gate=QualificationGateV2.OOS
    )

    assert validation.outcome is ValidationOutcomeV2.FAIL
    assert qualification.status is QualificationEngineStatus.NOT_QUALIFIED
    first = _evaluate(case, setup, package, validation, qualification, at)
    second = _evaluate(case, setup, package, validation, qualification, at)

    assert first.status is NoTradeEngineStatus.NO_TRADE
    assert first.decision is not None
    assert first.decision == second.decision
    assert first.decision.contract_id == "C-026"
    assert first.decision.schema_version == "2"
    assert NoTradeReasonV2.VALIDATION_FAILED in first.reasons
    assert first.decision.candidate_id == setup.candidate.candidate_id
    assert first.decision.expires_at <= package.package.expires_at
    assert first.decision.expires_at <= validation.validation.valid_until
    refs = {
        (item.artifact_type, item.artifact_id): item
        for item in first.decision.provenance
    }
    assert refs[("C-006", case[2].market_context.context_id)].content_sha256 == (
        canonical_sha256(case[2].market_context)
    )
    assert refs[("C-007", case[2].market_context.analysis_snapshot.snapshot_id)]
    assert refs[("C-021", setup.candidate.strategy_version_id)] == (
        setup.candidate.entry_concept.method
    )
    assert refs[("C-023", setup.candidate.candidate_id)].content_sha256 == (
        canonical_sha256(setup.candidate)
    )
    assert refs[("C-024", package.package.package_id)].content_sha256 == (
        package.package.content_sha256
    )
    assert refs[("C-028", validation.validation.result_id)].content_sha256 == (
        validation.validation.content_sha256
    )
    assert refs[("C-025", qualification.qualification.qualification_id)]
    assert refs[("C-003", package.package.data_quality_report.artifact_id)]
    assert first.decision.correlation_id == "spot-no-trade-test"
    assert set(first.decision.conflict_ids) == {
        item.assessment_id
        for item in case[2].market_context.conflicts
        if item.resolution_status.value == "unresolved" or item.unsafe_to_rely is True
    }
    assert set(first.decision.uncertainty_ids) == {
        item.uncertainty_id
        for item in case[2].market_context.uncertainties
        if item.resolution_status.value == "unresolved"
    }


def test_exact_wave3_insufficient_validation_path_emits_c026():
    case, setup, package, validation, qualification, at = _chain(
        insufficient_gate=QualificationGateV2.ROBUSTNESS
    )

    assert validation.outcome is ValidationOutcomeV2.INSUFFICIENT_VALIDATION
    assert qualification.status is QualificationEngineStatus.INSUFFICIENT_VALIDATION
    result = _evaluate(case, setup, package, validation, qualification, at)

    assert result.decision is not None
    assert NoTradeReasonV2.VALIDATION_INCONCLUSIVE in result.reasons
    assert result.decision.schema_version == "2"


def test_authoritative_risk_unavailable_is_machine_readable():
    case, setup, package, validation, qualification, at = _chain(
        insufficient_gate=QualificationGateV2.RISK
    )

    assert validation.outcome is ValidationOutcomeV2.INSUFFICIENT_VALIDATION
    result = _evaluate(case, setup, package, validation, qualification, at)

    assert result.decision is not None
    assert NoTradeReasonV2.RISK_UNAVAILABLE in result.reasons


def test_exact_wave3_stale_validation_path_emits_c026_without_rewriting_c028():
    case, setup, package_eval, validation, qualification, at = _chain()
    assert validation.validation is not None
    stale_at = validation.validation.valid_until
    assert setup.candidate is not None and package_eval.package is not None
    stale_qualification = evaluate_signal_qualification_v2(
        candidate=setup.candidate,
        evidence_package=package_eval.package,
        validation=validation.validation,
        evaluated_at=stale_at,
    )

    assert stale_qualification.status is QualificationEngineStatus.STALE_INPUT
    result = _evaluate(
        case, setup, package_eval, validation, stale_qualification, stale_at
    )

    assert result.decision is not None
    assert NoTradeReasonV2.VALIDATION_STALE in result.reasons
    assert result.decision.expires_at == stale_at


def test_exact_wave3_mismatched_validation_is_rejected_as_invalid_provenance():
    case, setup, package_eval, validation, qualification, at = _chain()
    assert setup.candidate is not None
    assert validation.validation is not None
    source = validation.validation
    values = {
        item.name: getattr(source, item.name)
        for item in fields(source)
        if item.name not in {"content_sha256", "contract_id", "schema_version"}
    }
    values["candidate_id"] = uuid4()
    mismatched_validation = type(source).build(**values)
    mismatched_qualification = evaluate_signal_qualification_v2(
        candidate=setup.candidate,
        evidence_package=package_eval.package,
        validation=mismatched_validation,
        evaluated_at=at,
    )

    assert (
        mismatched_qualification.status is QualificationEngineStatus.INVALID_PROVENANCE
    )
    result = _evaluate(
        case, setup, package_eval, validation, mismatched_qualification, at
    )

    assert result.decision is not None
    assert NoTradeReasonV2.INVALID_PROVENANCE in result.reasons


def test_future_dated_candidate_source_maps_to_invalid_provenance():
    case, setup, package, validation, qualification, at = _chain()
    assert setup.candidate is not None
    future_at = setup.candidate.created_at - timedelta(seconds=1)
    result = _evaluate(case, setup, package, None, None, future_at)

    assert result.decision is not None
    assert NoTradeReasonV2.INVALID_PROVENANCE in result.reasons


def test_regime_gate_failure_preserves_regime_mismatch_reason():
    case, setup, package, validation, qualification, at = _chain(
        failed_gate=QualificationGateV2.REGIME_APPLICABILITY
    )

    assert validation.outcome is ValidationOutcomeV2.FAIL
    assert qualification.status is QualificationEngineStatus.NOT_QUALIFIED
    result = _evaluate(case, setup, package, validation, qualification, at)

    assert result.decision is not None
    assert NoTradeReasonV2.VALIDATION_FAILED in result.reasons
    assert NoTradeReasonV2.REGIME_MISMATCH in result.reasons


@pytest.mark.parametrize(
    ("status", "reason"),
    [
        (
            EvidencePackageStatus.INSUFFICIENT_EVIDENCE,
            NoTradeReasonV2.INSUFFICIENT_EVIDENCE,
        ),
        (EvidencePackageStatus.INVALID_PROVENANCE, NoTradeReasonV2.INVALID_PROVENANCE),
        (EvidencePackageStatus.STALE_INPUT, NoTradeReasonV2.STALE_DATA),
    ],
)
def test_evidence_package_status_maps_to_existing_reason(status, reason):
    case, setup, package, validation, qualification, at = _chain()
    blocked = EvidencePackageEvaluation(status, ("UPSTREAM_TEST_STATE",), None)
    result = _evaluate(case, setup, blocked, None, None, at)

    assert result.decision is not None
    assert reason in result.reasons
    assert result.decision.candidate_id == setup.candidate.candidate_id
    assert result.decision.provenance


def test_zero_candidate_placeholders_do_not_suppress_missing_evidence_no_trade():
    case, setup, package, validation, qualification, at = _chain()
    assert setup.candidate is not None
    assert setup.candidate.analytical_confidence == 0
    assert setup.candidate.evidence_strength == 0

    result = _evaluate(case, setup, None, None, None, at)

    assert result.decision is not None
    assert NoTradeReasonV2.INSUFFICIENT_EVIDENCE in result.reasons
    assert NoTradeReasonV2.VALIDATION_MISSING in result.reasons
    assert result.decision.contract_id == "C-026"
    assert result.decision.lifecycle.value == "NO_TRADE"


def test_missing_validation_and_inconclusive_validation_are_distinct():
    case, setup, package, validation, qualification, at = _chain()
    missing = _evaluate(case, setup, package, None, None, at)
    inconclusive_eval = replace(
        validation,
        outcome=ValidationOutcomeV2.INSUFFICIENT_VALIDATION,
        validation=None,
    )
    inconclusive = _evaluate(case, setup, package, inconclusive_eval, None, at)

    assert NoTradeReasonV2.VALIDATION_MISSING in missing.reasons
    assert NoTradeReasonV2.VALIDATION_INCONCLUSIVE in inconclusive.reasons


def test_no_setup_emits_c026_without_fabricating_candidate():
    case, setup, package, validation, qualification, at = _chain()
    no_setup = replace(
        setup,
        outcome=SetupDetectionOutcome.NO_SETUP,
        reason_codes=("CONDITIONS_NOT_SATISFIED",),
        candidate=None,
    )
    result = evaluate_no_trade_v2(
        market_context=case[2].market_context,
        setup=no_setup,
        eligibility=case[6],
        evidence_package=None,
        validation=None,
        qualification=None,
        evaluated_at=at,
        correlation_id="spot-no-setup",
    )

    assert result.decision is not None
    assert result.decision.candidate_id is None
    assert NoTradeReasonV2.NO_SETUP in result.reasons
    assert NoTradeReasonV2.INSUFFICIENT_EVIDENCE in result.reasons
    assert NoTradeReasonV2.UNRESOLVED_CONFLICT in result.reasons


def test_strategy_ineligible_and_insufficient_setup_are_preserved():
    case, setup, package, validation, qualification, at = _chain()
    ineligible = replace(case[6], state=EligibilityState.NOT_ELIGIBLE)
    result = evaluate_no_trade_v2(
        market_context=case[2].market_context,
        setup=setup,
        eligibility=ineligible,
        evidence_package=package,
        validation=None,
        qualification=None,
        evaluated_at=at,
        correlation_id="spot-ineligible",
    )

    assert result.decision is not None
    assert NoTradeReasonV2.STRATEGY_INELIGIBLE in result.reasons
    assert NoTradeReasonV2.INVALID_PROVENANCE not in result.reasons


def test_stale_validation_keeps_stale_reason_and_expires_immediately():
    case, setup, package, validation, qualification, at = _chain()
    assert validation.validation is not None
    # Evaluate at the authoritative expiry boundary; keep C-028 and its digest
    # intact instead of constructing an invalid validation artifact.
    stale_at = validation.validation.valid_until
    result = _evaluate(case, setup, package, validation, None, stale_at)

    assert result.decision is not None
    assert NoTradeReasonV2.VALIDATION_STALE in result.reasons
    assert result.decision.expires_at == stale_at


def test_reason_order_is_canonical_and_contextless_result_emits_no_artifact():
    case, setup, package, validation, qualification, at = _chain()
    first_setup = replace(
        setup,
        outcome=SetupDetectionOutcome.NO_SETUP,
        reason_codes=("NO_SETUP", "INSUFFICIENT_DATA"),
        candidate=None,
    )
    second_setup = replace(
        first_setup, reason_codes=tuple(reversed(first_setup.reason_codes))
    )
    first = evaluate_no_trade_v2(
        market_context=case[2].market_context,
        setup=first_setup,
        eligibility=case[6],
        evidence_package=None,
        validation=None,
        qualification=None,
        evaluated_at=at,
        correlation_id="order-independent",
    )
    second = evaluate_no_trade_v2(
        market_context=case[2].market_context,
        setup=second_setup,
        eligibility=case[6],
        evidence_package=None,
        validation=None,
        qualification=None,
        evaluated_at=at,
        correlation_id="order-independent",
    )
    no_context = evaluate_no_trade_v2(
        market_context=None,
        setup=first_setup,
        eligibility=case[6],
        evidence_package=None,
        validation=None,
        qualification=None,
        evaluated_at=at,
        correlation_id="no-context",
    )

    assert first.decision is not None and second.decision is not None
    assert first.reasons == second.reasons
    assert first.decision.decision_id == second.decision.decision_id
    assert no_context.status is NoTradeEngineStatus.INSUFFICIENT_CONTEXT
    assert no_context.decision is None
