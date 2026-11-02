from __future__ import annotations

from dataclasses import replace
from datetime import timedelta

from test_qualification_rule_evaluator import request
from test_strategy_evidence_package import _package
from test_strategy_setup_detection import _detect, _positive_case
from trading_platform_api.strategy import (
    QualificationEngineStatus,
    evaluate_qualification_rules,
    evaluate_signal_qualification_v2,
)
from trading_platform_api.validation import (
    QualificationGateV2,
    ValidationGateOutcomeV2,
    ValidationOutcomeV2,
)


def _real_spot_chain(*, fail_oos: bool = False):
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
    if fail_oos:
        rule_input = replace(
            rule_input,
            authoritative_gates=tuple(
                replace(gate, outcome=ValidationGateOutcomeV2.FAIL)
                if gate.gate is QualificationGateV2.OOS
                else gate
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
    return candidate, package, validation, qualification


def test_real_82_85_semantic_strategy_reference_reaches_87_pass_and_86_qualified():
    candidate, package, validation, qualification = _real_spot_chain()

    assert package.strategy_version == candidate.entry_concept.method
    assert package.strategy_version.artifact_id == candidate.strategy_version_id
    assert package.strategy_version.version == "1.0.0"
    assert validation.outcome is ValidationOutcomeV2.PASS
    assert validation.validation is not None
    assert qualification.status is QualificationEngineStatus.QUALIFIED
    assert qualification.qualification is not None
    assert qualification.qualification.validation == validation.validation


def test_real_82_85_semantic_strategy_reference_flows_87_fail_to_86_rejected():
    candidate, package, validation, qualification = _real_spot_chain(fail_oos=True)

    assert package.strategy_version == candidate.entry_concept.method
    assert validation.outcome is ValidationOutcomeV2.FAIL
    assert validation.validation is not None
    assert qualification.status is QualificationEngineStatus.NOT_QUALIFIED
    assert qualification.qualification is not None
    assert qualification.qualification.status.value == "REJECTED"
