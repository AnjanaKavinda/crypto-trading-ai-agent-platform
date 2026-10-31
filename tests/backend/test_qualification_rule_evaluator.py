from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from trading_platform_api.strategy import (
    C093DependenceReferenceV2,
    EligibilityState,
    EvidenceDependenceV2,
    EvidenceGraphEdgeV2,
    EvidenceGraphNodeV2,
    EvidenceGraphV2,
    EvidenceNodeTypeV2,
    QualificationEvaluationReason,
    QualificationRuleEvaluationInput,
    SetupState,
    SignalCandidate,
    SignalConcept,
    SignalDirection,
    SignalEvidencePackageV2,
    SignalLifecycleState,
    VersionReference,
    evaluate_qualification_rules,
)
from trading_platform_api.validation import (
    AssumptionCategory,
    CostApplicabilityV2,
    CostAssumptionSetV2,
    QualificationGateResultV2,
    QualificationGateV2,
    QualificationRuleSetV2,
    ResearchAssumptionV2,
    StatisticalSupportStateV2,
    StatisticalUncertaintyEvidenceV2,
    ValidationArtifactReferenceV2,
    ValidationGateOutcomeV2,
    ValidationOutcomeV2,
)

NOW = datetime(2026, 10, 31, 12, 0, tzinfo=UTC)
EXPIRY = NOW + timedelta(hours=2)
SHA = "a" * 64


def ref(contract: str, identity=None, version: str = "1") -> VersionReference:
    return VersionReference(contract, identity or uuid4(), version, SHA)


def validation_ref(contract: str, identity=None, version: str = "1"):
    return ValidationArtifactReferenceV2(contract, identity or uuid4(), version, SHA)


def _costs(
    *, unknown_fee: bool = False, strategy_version_id=None
) -> CostAssumptionSetV2:
    strategy_version_id = strategy_version_id or uuid4()
    assumptions = (
        ResearchAssumptionV2(
            AssumptionCategory.FEE,
            CostApplicabilityV2.UNKNOWN
            if unknown_fee
            else CostApplicabilityV2.APPLICABLE,
            validation_ref("FEE-MODEL"),
            None if unknown_fee else Decimal("0.001"),
            None if unknown_fee else "ratio",
            "Approved Spot fee applicability and model",
        ),
        ResearchAssumptionV2(
            AssumptionCategory.SPREAD,
            CostApplicabilityV2.APPLICABLE,
            validation_ref("SPREAD-MODEL"),
            Decimal("0.0002"),
            "ratio",
            "Approved Spot spread model",
        ),
        ResearchAssumptionV2(
            AssumptionCategory.SLIPPAGE,
            CostApplicabilityV2.APPLICABLE,
            validation_ref("SLIPPAGE-MODEL"),
            Decimal("0.0001"),
            "ratio",
            "Approved Spot slippage model",
        ),
        ResearchAssumptionV2(
            AssumptionCategory.FUNDING,
            CostApplicabilityV2.NOT_APPLICABLE,
            validation_ref("FUNDING-POLICY"),
            None,
            None,
            "Funding is not applicable to Spot instruments",
        ),
    )
    return CostAssumptionSetV2.build(
        assumption_set_id=uuid4(),
        strategy_version_id=strategy_version_id,
        asset="BTC",
        instrument_type="SPOT",
        required_categories=(
            AssumptionCategory.FEE,
            AssumptionCategory.SPREAD,
            AssumptionCategory.SLIPPAGE,
            AssumptionCategory.FUNDING,
        ),
        assumptions=assumptions,
    )


def _candidate(strategy_version_id=None, **overrides) -> SignalCandidate:
    strategy_version_id = strategy_version_id or uuid4()
    candidate_id = uuid4()
    market_context_id = uuid4()
    snapshot_id = uuid4()
    quality_id = uuid4()
    eligibility_id = uuid4()
    concept_method = ref("C-021")

    def concept(name: str) -> SignalConcept:
        return SignalConcept(name, f"{name} concept", (), concept_method)

    values = {
        "candidate_id": candidate_id,
        "strategy_id": uuid4(),
        "strategy_version_id": strategy_version_id,
        "eligibility_id": eligibility_id,
        "eligibility_state": EligibilityState.ELIGIBLE,
        "market_context_id": market_context_id,
        "analysis_snapshot_id": snapshot_id,
        "asset": "BTC",
        "instrument_id": "BTC-USDT-SPOT",
        "timeframe": "1h",
        "direction": SignalDirection.LONG,
        "setup_state": SetupState.SETUP_CONFIRMED,
        "entry_concept": concept("entry"),
        "invalidation_concept": concept("invalidation"),
        "target_concepts": (concept("target"),),
        "supporting_evidence_ids": (uuid4(),),
        "contradictory_evidence_ids": (),
        "data_quality_report_id": quality_id,
        "analytical_confidence": Decimal("0"),
        "evidence_strength": Decimal("0"),
        "lifecycle": SignalLifecycleState.CANDIDATE,
        "created_at": NOW - timedelta(minutes=1),
        "expires_at": EXPIRY,
    }
    values.update(overrides)
    return SignalCandidate(**values)


def _package(candidate: SignalCandidate) -> SignalEvidencePackageV2:
    candidate_ref = VersionReference("C-023", candidate.candidate_id, "1", SHA)
    strategy_ref = VersionReference(
        "C-021", candidate.strategy_version_id, "1", "b" * 64
    )
    evidence_ref = ref("C-008")
    graph_nodes = (
        EvidenceGraphNodeV2(
            uuid4(),
            EvidenceNodeTypeV2.EVIDENCE,
            evidence_ref,
            EvidenceDependenceV2.UNKNOWN,
            NOW - timedelta(minutes=1),
            EXPIRY,
            ref("EVIDENCE-METHOD"),
        ),
        EvidenceGraphNodeV2(
            uuid4(),
            EvidenceNodeTypeV2.FINDING,
            ref("C-068"),
            EvidenceDependenceV2.PARTIALLY_DEPENDENT,
            NOW - timedelta(minutes=1),
            EXPIRY,
            ref("FINDING-METHOD"),
        ),
        EvidenceGraphNodeV2(
            uuid4(),
            EvidenceNodeTypeV2.STRATEGY_CONDITION,
            ref("C-020"),
            EvidenceDependenceV2.UNKNOWN,
            NOW - timedelta(minutes=1),
            EXPIRY,
            ref("CONDITION-METHOD"),
        ),
        EvidenceGraphNodeV2(
            uuid4(),
            EvidenceNodeTypeV2.CANDIDATE,
            candidate_ref,
            EvidenceDependenceV2.UNKNOWN,
            NOW - timedelta(minutes=1),
            EXPIRY,
            ref("CANDIDATE-METHOD"),
        ),
    )
    graph = EvidenceGraphV2(
        graph_nodes,
        (
            EvidenceGraphEdgeV2(
                graph_nodes[0].node_id, graph_nodes[1].node_id, "supports"
            ),
            EvidenceGraphEdgeV2(
                graph_nodes[1].node_id, graph_nodes[2].node_id, "satisfies"
            ),
            EvidenceGraphEdgeV2(
                graph_nodes[2].node_id, graph_nodes[3].node_id, "supports"
            ),
        ),
    )
    return SignalEvidencePackageV2.build(
        candidate=candidate_ref,
        strategy_version=strategy_ref,
        eligibility=VersionReference("C-022", candidate.eligibility_id, "1", SHA),
        market_context=VersionReference("C-006", candidate.market_context_id, "5", SHA),
        analysis_snapshot=VersionReference(
            "C-007", candidate.analysis_snapshot_id, "4", SHA
        ),
        data_quality_report=VersionReference(
            "C-003", candidate.data_quality_report_id, "2", SHA
        ),
        candidate_valid_until=candidate.expires_at,
        market_context_valid_until=candidate.expires_at,
        analysis_snapshot_valid_until=candidate.expires_at,
        evidence_references=(evidence_ref,),
        confluence=ref("C-009"),
        conflicts=(),
        adversarial_assessment=ref("C-019"),
        adversarial_assessment_required=True,
        uncertainties=(ref("C-069"),),
        dependence=C093DependenceReferenceV2(
            ref("C-093"), EvidenceDependenceV2.UNKNOWN
        ),
        supporting_evidence=(evidence_ref,),
        contradictory_evidence=(),
        graph=graph,
        created_at=NOW,
        expires_at=candidate.expires_at,
    )


def _gates(*, failed=(), missing=(), omitted=(), expiry=EXPIRY):
    sources = {
        QualificationGateV2.DATA_INTEGRITY: validation_ref("C-003", version="2"),
        QualificationGateV2.POINT_IN_TIME: validation_ref("C-092"),
        QualificationGateV2.SAMPLE_SUFFICIENCY: validation_ref("C-071"),
        QualificationGateV2.OOS: validation_ref("C-071"),
        QualificationGateV2.WALK_FORWARD: validation_ref("C-029"),
        QualificationGateV2.ROBUSTNESS: validation_ref("C-030"),
        QualificationGateV2.BIAS_LEAKAGE: validation_ref("C-094"),
        QualificationGateV2.RISK: validation_ref("C-035"),
        QualificationGateV2.REGIME_APPLICABILITY: validation_ref("C-074"),
    }
    return tuple(
        QualificationGateResultV2(
            gate,
            ValidationGateOutcomeV2.INSUFFICIENT_VALIDATION
            if gate in missing
            else ValidationGateOutcomeV2.FAIL
            if gate in failed
            else ValidationGateOutcomeV2.PASS,
            None if gate in missing else sources[gate],
            expiry,
        )
        for gate in sources
        if gate not in omitted
    )


def request(**overrides) -> QualificationRuleEvaluationInput:
    candidate = overrides.pop("candidate", None)
    if candidate is None:
        candidate = _candidate()
    package = overrides.pop("evidence_package", None) or _package(candidate)
    costs = overrides.pop("cost_assumptions", None) or _costs(
        strategy_version_id=candidate.strategy_version_id
    )
    methodology = overrides.pop("methodology", validation_ref("QUALIFICATION-METHOD"))
    rule_set = overrides.pop("rule_set", None) or QualificationRuleSetV2.build(
        rule_set_id=uuid4(),
        version="1",
        strategy_version_id=candidate.strategy_version_id,
        asset=candidate.asset,
        instrument_type="SPOT",
        timeframe=candidate.timeframe,
        regime="TRENDING_UP",
        conditional_event_definition="Candidate satisfies the exact C-021 condition group",
        conditional_win_rate_threshold=Decimal("0.75"),
        calibration_required=False,
        methodology=methodology,
        cost_assumption_set=ValidationArtifactReferenceV2(
            "C-027", costs.assumption_set_id, "2", costs.content_sha256
        ),
    )
    values = {
        "candidate": candidate,
        "candidate_reference": package.candidate,
        "evidence_package": package,
        "rule_set": rule_set,
        "cost_assumptions": costs,
        "observed_conditional_win_rate": Decimal("0.75"),
        "threshold_evidence": validation_ref("C-071"),
        "sample_size": 500,
        "effective_sample_size": Decimal("400"),
        "sample_semantics": validation_ref("SAMPLE-SEMANTICS"),
        "after_cost_expectancy": Decimal("0.01"),
        "expectancy_unit": "return_per_trade",
        "expectancy_evidence": validation_ref("C-071"),
        "statistical_uncertainty": StatisticalUncertaintyEvidenceV2(
            validation_ref("C-071"),
            methodology,
            ("conditional_win_rate", "after_cost_expectancy"),
        ),
        "statistical_support_state": StatisticalSupportStateV2.SUPPORTED,
        "calibration": None,
        "authoritative_gates": _gates(),
        "methodology": methodology,
        "evaluated_at": NOW,
    }
    values.update(overrides)
    return QualificationRuleEvaluationInput(**values)


def test_threshold_equality_and_above_pass_only_as_conjunctive_gate() -> None:
    equal = evaluate_qualification_rules(request())
    above = evaluate_qualification_rules(
        request(observed_conditional_win_rate=Decimal("0.80"))
    )
    assert equal.outcome is ValidationOutcomeV2.PASS
    assert above.outcome is ValidationOutcomeV2.PASS
    assert equal.validation is not None and above.validation is not None
    assert (
        next(
            g for g in equal.validation.gates if g.gate is QualificationGateV2.THRESHOLD
        ).outcome
        is ValidationGateOutcomeV2.PASS
    )
    assert all(
        g.outcome is ValidationGateOutcomeV2.PASS for g in equal.validation.gates
    )
    assert equal.validation.rule_set.conditional_win_rate_threshold == Decimal("0.75")
    assert equal.validation.observed_conditional_win_rate == Decimal("0.75")


def test_threshold_is_read_from_rule_set_configuration() -> None:
    value = request()
    configured = QualificationRuleSetV2.build(
        rule_set_id=value.rule_set.rule_set_id,
        version=value.rule_set.version,
        strategy_version_id=value.rule_set.strategy_version_id,
        asset=value.rule_set.asset,
        instrument_type=value.rule_set.instrument_type,
        timeframe=value.rule_set.timeframe,
        regime=value.rule_set.regime,
        conditional_event_definition=value.rule_set.conditional_event_definition,
        conditional_win_rate_threshold=Decimal("0.60"),
        calibration_required=value.rule_set.calibration_required,
        methodology=value.rule_set.methodology,
        cost_assumption_set=value.rule_set.cost_assumption_set,
    )
    result = evaluate_qualification_rules(
        replace(
            value,
            rule_set=configured,
            observed_conditional_win_rate=Decimal("0.60"),
        )
    )
    assert result.outcome is ValidationOutcomeV2.PASS
    assert result.validation is not None
    assert result.validation.rule_set.conditional_win_rate_threshold == Decimal("0.60")


def test_repeated_identical_evaluation_is_deterministic_and_ignores_c023_placeholders() -> (
    None
):
    initial = request()
    first = evaluate_qualification_rules(initial)
    second = evaluate_qualification_rules(initial)
    elevated_placeholders = replace(
        initial,
        candidate=replace(
            initial.candidate,
            analytical_confidence=Decimal("0.99"),
            evidence_strength=Decimal("0.98"),
        ),
    )
    third = evaluate_qualification_rules(elevated_placeholders)
    assert first == second == third
    assert first.validation is not None
    assert first.validation.schema_version == "2"
    assert first.validation.contract_id == "C-028"


@pytest.mark.parametrize(
    ("rate", "expected"),
    [
        (Decimal("0.749999"), ValidationOutcomeV2.FAIL),
        (Decimal("0.74"), ValidationOutcomeV2.FAIL),
    ],
)
def test_below_configured_threshold_fails(rate, expected) -> None:
    result = evaluate_qualification_rules(request(observed_conditional_win_rate=rate))
    assert result.outcome is expected
    assert result.validation is not None
    assert QualificationEvaluationReason.THRESHOLD_BELOW_CONFIG in result.reasons


@pytest.mark.parametrize(
    "changes",
    [
        {"sample_size": None},
        {
            "authoritative_gates": _gates(
                missing={QualificationGateV2.SAMPLE_SUFFICIENCY}
            )
        },
        {
            "authoritative_gates": _gates(
                failed={QualificationGateV2.SAMPLE_SUFFICIENCY}
            )
        },
    ],
)
def test_high_win_rate_cannot_override_sample_sufficiency(changes) -> None:
    result = evaluate_qualification_rules(request(**changes))
    assert result.outcome is not ValidationOutcomeV2.PASS
    assert result.validation is not None
    sample_gate = next(
        g
        for g in result.validation.gates
        if g.gate is QualificationGateV2.SAMPLE_SUFFICIENCY
    )
    assert sample_gate.outcome is not ValidationGateOutcomeV2.PASS


@pytest.mark.parametrize(
    ("state", "uncertainty", "expected"),
    [
        (
            StatisticalSupportStateV2.OBSERVED,
            StatisticalUncertaintyEvidenceV2(
                validation_ref("C-071"),
                validation_ref("STAT-METHOD"),
                ("conditional_win_rate",),
            ),
            ValidationOutcomeV2.INSUFFICIENT_VALIDATION,
        ),
        (
            StatisticalSupportStateV2.INSUFFICIENT,
            None,
            ValidationOutcomeV2.INSUFFICIENT_VALIDATION,
        ),
        (
            StatisticalSupportStateV2.NOT_SUPPORTED,
            StatisticalUncertaintyEvidenceV2(
                validation_ref("C-071"),
                validation_ref("STAT-METHOD"),
                ("conditional_win_rate",),
            ),
            ValidationOutcomeV2.FAIL,
        ),
    ],
)
def test_statistical_support_is_consumed_without_recomputing_intervals(
    state, uncertainty, expected
) -> None:
    value = request()
    if uncertainty is not None:
        uncertainty = StatisticalUncertaintyEvidenceV2(
            uncertainty.result, value.methodology, uncertainty.metric_names
        )
    result = evaluate_qualification_rules(
        replace(
            value,
            statistical_support_state=state,
            statistical_uncertainty=uncertainty,
        )
    )
    assert result.outcome is expected
    assert result.validation is not None


@pytest.mark.parametrize("expectancy", [Decimal("0"), Decimal("-0.001")])
def test_non_positive_after_cost_expectancy_fails(expectancy) -> None:
    result = evaluate_qualification_rules(request(after_cost_expectancy=expectancy))
    assert result.outcome is ValidationOutcomeV2.FAIL
    assert result.validation is not None
    assert QualificationEvaluationReason.EXPECTANCY_NOT_POSITIVE in result.reasons


def test_missing_expectancy_is_insufficient() -> None:
    result = evaluate_qualification_rules(
        request(
            after_cost_expectancy=None, expectancy_unit=None, expectancy_evidence=None
        )
    )
    assert result.outcome is ValidationOutcomeV2.INSUFFICIENT_VALIDATION
    assert result.validation is not None


def test_spot_costs_require_explicit_funding_not_applicable_without_zero() -> None:
    value = request()
    funding = next(
        item
        for item in value.cost_assumptions.assumptions
        if item.category is AssumptionCategory.FUNDING
    )
    assert funding.applicability is CostApplicabilityV2.NOT_APPLICABLE
    assert funding.value is None and funding.unit is None
    result = evaluate_qualification_rules(value)
    assert result.validation is not None
    assert result.outcome is ValidationOutcomeV2.PASS


def test_unknown_required_cost_applicability_blocks_pass() -> None:
    value = request()
    unknown = _costs(
        unknown_fee=True, strategy_version_id=value.candidate.strategy_version_id
    )
    rule_set = QualificationRuleSetV2.build(
        rule_set_id=value.rule_set.rule_set_id,
        version=value.rule_set.version,
        strategy_version_id=value.rule_set.strategy_version_id,
        asset=value.rule_set.asset,
        instrument_type=value.rule_set.instrument_type,
        timeframe=value.rule_set.timeframe,
        regime=value.rule_set.regime,
        conditional_event_definition=value.rule_set.conditional_event_definition,
        conditional_win_rate_threshold=value.rule_set.conditional_win_rate_threshold,
        calibration_required=value.rule_set.calibration_required,
        methodology=value.rule_set.methodology,
        cost_assumption_set=ValidationArtifactReferenceV2(
            "C-027", unknown.assumption_set_id, "2", unknown.content_sha256
        ),
    )
    result = evaluate_qualification_rules(
        replace(value, cost_assumptions=unknown, rule_set=rule_set)
    )
    assert result.outcome is ValidationOutcomeV2.INSUFFICIENT_VALIDATION
    assert result.validation is not None
    assert QualificationEvaluationReason.COST_APPLICABILITY_UNKNOWN in result.reasons


def test_missing_cost_assumptions_are_insufficient() -> None:
    value = request()
    result = evaluate_qualification_rules(replace(value, cost_assumptions=None))
    assert result.outcome is ValidationOutcomeV2.INSUFFICIENT_VALIDATION
    assert result.validation is None
    assert (
        QualificationEvaluationReason.REQUIRED_CONFIGURATION_MISSING in result.reasons
    )


@pytest.mark.parametrize(
    ("gate", "expected"),
    [
        (QualificationGateV2.OOS, ValidationOutcomeV2.FAIL),
        (QualificationGateV2.WALK_FORWARD, ValidationOutcomeV2.FAIL),
        (QualificationGateV2.ROBUSTNESS, ValidationOutcomeV2.FAIL),
        (QualificationGateV2.BIAS_LEAKAGE, ValidationOutcomeV2.FAIL),
        (QualificationGateV2.RISK, ValidationOutcomeV2.FAIL),
        (QualificationGateV2.REGIME_APPLICABILITY, ValidationOutcomeV2.FAIL),
    ],
)
def test_authoritative_failed_gate_blocks_high_win_rate(gate, expected) -> None:
    result = evaluate_qualification_rules(
        request(authoritative_gates=_gates(failed={gate}))
    )
    assert result.outcome is expected
    assert result.validation is not None


@pytest.mark.parametrize(
    "gate",
    [
        QualificationGateV2.OOS,
        QualificationGateV2.WALK_FORWARD,
        QualificationGateV2.ROBUSTNESS,
        QualificationGateV2.BIAS_LEAKAGE,
        QualificationGateV2.RISK,
        QualificationGateV2.REGIME_APPLICABILITY,
    ],
)
def test_missing_authoritative_gate_is_insufficient(gate) -> None:
    result = evaluate_qualification_rules(
        request(authoritative_gates=_gates(missing={gate}))
    )
    assert result.outcome is ValidationOutcomeV2.INSUFFICIENT_VALIDATION
    assert result.validation is not None


@pytest.mark.parametrize(
    "gate",
    [
        QualificationGateV2.OOS,
        QualificationGateV2.WALK_FORWARD,
        QualificationGateV2.ROBUSTNESS,
        QualificationGateV2.BIAS_LEAKAGE,
        QualificationGateV2.RISK,
        QualificationGateV2.REGIME_APPLICABILITY,
    ],
)
def test_absent_authoritative_gate_is_insufficient(gate) -> None:
    result = evaluate_qualification_rules(
        request(authoritative_gates=_gates(omitted={gate}))
    )
    assert result.outcome is ValidationOutcomeV2.INSUFFICIENT_VALIDATION
    assert result.validation is not None


def test_duplicate_authoritative_gate_cannot_leave_an_otherwise_passing_result() -> (
    None
):
    gates = _gates()
    result = evaluate_qualification_rules(
        request(authoritative_gates=(*gates, gates[0]))
    )
    assert result.outcome is ValidationOutcomeV2.INSUFFICIENT_VALIDATION
    assert result.validation is not None
    assert QualificationEvaluationReason.DUPLICATE_OR_UNEXPECTED_GATE in result.reasons


def test_unsupported_authoritative_reference_cannot_pass() -> None:
    gates = list(_gates())
    index = next(
        i for i, gate in enumerate(gates) if gate.gate is QualificationGateV2.OOS
    )
    gates[index] = QualificationGateResultV2(
        QualificationGateV2.OOS,
        ValidationGateOutcomeV2.PASS,
        validation_ref("C-092"),
        EXPIRY,
    )
    result = evaluate_qualification_rules(request(authoritative_gates=tuple(gates)))
    assert result.outcome is ValidationOutcomeV2.INSUFFICIENT_VALIDATION
    assert result.validation is None
    assert QualificationEvaluationReason.INVALID_EVIDENCE_REFERENCE in result.reasons


@pytest.mark.parametrize(
    "candidate_changes",
    [
        {"asset": "ETH"},
        {"timeframe": "4h"},
        {"strategy_version_id": uuid4()},
    ],
)
def test_wrong_candidate_scope_or_strategy_fails_closed(candidate_changes) -> None:
    value = request()
    candidate = replace(value.candidate, **candidate_changes)
    result = evaluate_qualification_rules(replace(value, candidate=candidate))
    assert result.outcome is ValidationOutcomeV2.INSUFFICIENT_VALIDATION
    assert result.validation is None
    assert QualificationEvaluationReason.INPUT_SCOPE_MISMATCH in result.reasons


def test_wrong_methodology_fails_closed() -> None:
    value = request()
    result = evaluate_qualification_rules(
        replace(value, methodology=validation_ref("OTHER-METHOD"))
    )
    assert result.outcome is ValidationOutcomeV2.INSUFFICIENT_VALIDATION
    assert result.validation is None
    assert QualificationEvaluationReason.METHODOLOGY_MISMATCH in result.reasons


def test_stale_gate_evidence_cannot_pass() -> None:
    result = evaluate_qualification_rules(
        request(authoritative_gates=_gates(expiry=NOW))
    )
    assert result.outcome is ValidationOutcomeV2.INSUFFICIENT_VALIDATION
    assert result.validation is None
    assert QualificationEvaluationReason.STALE_EVIDENCE in result.reasons


def test_c023_confidence_and_setup_confidence_are_not_evaluator_inputs() -> None:
    incomplete = request(authoritative_gates=_gates(missing={QualificationGateV2.OOS}))
    high_confidence_candidate = replace(
        incomplete.candidate,
        analytical_confidence=Decimal("1"),
        evidence_strength=Decimal("1"),
    )
    result = evaluate_qualification_rules(
        replace(incomplete, candidate=high_confidence_candidate)
    )
    assert result.outcome is ValidationOutcomeV2.INSUFFICIENT_VALIDATION
    assert result.validation is not None
