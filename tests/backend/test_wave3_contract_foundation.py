from __future__ import annotations

from dataclasses import fields
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from trading_platform_api.contracts import serialize_contract
from trading_platform_api.strategy import (
    C093DependenceReferenceV2,
    EvidenceDependence,
    EvidenceDependenceV2,
    EvidenceGraphEdgeV2,
    EvidenceGraphNodeV2,
    EvidenceGraphV2,
    EvidenceNodeTypeV2,
    QualificationStatus,
    SignalEvidencePackage,
    SignalEvidencePackageV2,
    SignalQualification,
    SignalQualificationV2,
    StrategyContractError,
    VersionReference,
)
from trading_platform_api.validation import (
    AssumptionCategory,
    BacktestResult,
    CostApplicabilityV2,
    CostAssumptionSetV2,
    QualificationGateResultV2,
    QualificationGateV2,
    QualificationRuleSetV2,
    QualificationValidationResultV2,
    ResearchAssumptionV2,
    StatisticalSupportStateV2,
    StatisticalUncertaintyEvidenceV2,
    ValidationArtifactReferenceV2,
    ValidationContractError,
    ValidationGateOutcomeV2,
    ValidationOutcomeV2,
    ValidationResult,
)

NOW = datetime(2026, 10, 31, 10, 0, tzinfo=UTC)
SHA = "a" * 64


def test_v1_contract_schema_and_dependence_vocabulary_remain_unchanged() -> None:
    for contract_type in (
        SignalEvidencePackage,
        SignalQualification,
        BacktestResult,
        ValidationResult,
    ):
        assert (
            next(f.default for f in fields(contract_type) if f.name == "schema_version")
            == "1"
        )
    assert tuple(value.value for value in EvidenceDependence) == (
        "INDEPENDENT",
        "PARTIALLY_DEPENDENT",
        "HIGHLY_CORRELATED",
    )


def ref(
    contract_id: str,
    *,
    identity: UUID | None = None,
    version: str = "1",
    digest: str = SHA,
) -> VersionReference:
    return VersionReference(contract_id, identity or uuid4(), version, digest)


def artifact_ref(
    contract_id: str, *, identity: UUID | None = None, version: str = "1"
) -> ValidationArtifactReferenceV2:
    return ValidationArtifactReferenceV2(contract_id, identity or uuid4(), version, SHA)


def spot_costs() -> CostAssumptionSetV2:
    assumptions = (
        ResearchAssumptionV2(
            AssumptionCategory.FEE,
            CostApplicabilityV2.APPLICABLE,
            artifact_ref("C-027"),
            Decimal("0.001"),
            "ratio",
            "Approved Spot fee schedule",
        ),
        ResearchAssumptionV2(
            AssumptionCategory.SPREAD,
            CostApplicabilityV2.APPLICABLE,
            artifact_ref("C-027"),
            Decimal("0.0002"),
            "ratio",
            "Approved spread model",
        ),
        ResearchAssumptionV2(
            AssumptionCategory.SLIPPAGE,
            CostApplicabilityV2.APPLICABLE,
            artifact_ref("C-027"),
            Decimal("0.0001"),
            "ratio",
            "Approved slippage model",
        ),
        ResearchAssumptionV2(
            AssumptionCategory.FUNDING,
            CostApplicabilityV2.NOT_APPLICABLE,
            artifact_ref("C-027"),
            None,
            None,
            "Funding does not apply to unlevered Spot instruments",
        ),
    )
    return CostAssumptionSetV2.build(
        assumption_set_id=uuid4(),
        strategy_version_id=uuid4(),
        asset="BTC-USDT",
        instrument_type="SPOT",
        required_categories=(
            AssumptionCategory.FEE,
            AssumptionCategory.SPREAD,
            AssumptionCategory.SLIPPAGE,
            AssumptionCategory.FUNDING,
        ),
        assumptions=assumptions,
    )


def package(candidate: VersionReference | None = None) -> SignalEvidencePackageV2:
    candidate = candidate or ref("C-023")
    evidence = (ref("C-008"), ref("C-008"))
    nodes = (
        EvidenceGraphNodeV2(
            uuid4(),
            EvidenceNodeTypeV2.EVIDENCE,
            evidence[0],
            EvidenceDependenceV2.UNKNOWN,
            NOW,
            NOW + timedelta(hours=1),
            ref("METHOD"),
        ),
        EvidenceGraphNodeV2(
            uuid4(),
            EvidenceNodeTypeV2.FINDING,
            ref("C-068"),
            EvidenceDependenceV2.PARTIALLY_DEPENDENT,
            NOW,
            NOW + timedelta(hours=1),
            ref("METHOD"),
        ),
        EvidenceGraphNodeV2(
            uuid4(),
            EvidenceNodeTypeV2.STRATEGY_CONDITION,
            ref("C-020"),
            EvidenceDependenceV2.INDEPENDENT,
            NOW,
            NOW + timedelta(hours=1),
            ref("METHOD"),
        ),
        EvidenceGraphNodeV2(
            uuid4(),
            EvidenceNodeTypeV2.CANDIDATE,
            candidate,
            EvidenceDependenceV2.UNKNOWN,
            NOW,
            NOW + timedelta(hours=1),
            ref("METHOD"),
        ),
    )
    graph = EvidenceGraphV2(
        nodes,
        (
            EvidenceGraphEdgeV2(nodes[0].node_id, nodes[1].node_id, "supports"),
            EvidenceGraphEdgeV2(nodes[1].node_id, nodes[2].node_id, "satisfies"),
            EvidenceGraphEdgeV2(nodes[2].node_id, nodes[3].node_id, "supports"),
        ),
    )
    return SignalEvidencePackageV2.build(
        candidate=candidate,
        strategy_version=ref("C-021"),
        eligibility=ref("C-022"),
        market_context=ref("C-006"),
        analysis_snapshot=ref("C-007"),
        data_quality_report=ref("C-003"),
        candidate_valid_until=NOW + timedelta(hours=1),
        market_context_valid_until=NOW + timedelta(hours=1),
        analysis_snapshot_valid_until=NOW + timedelta(hours=1),
        evidence_references=evidence,
        confluence=ref("C-009"),
        conflicts=(ref("C-010"),),
        adversarial_assessment=ref("C-019"),
        adversarial_assessment_required=True,
        uncertainties=(ref("C-069"),),
        dependence=C093DependenceReferenceV2(
            ref("C-093"), EvidenceDependenceV2.UNKNOWN
        ),
        supporting_evidence=(evidence[0],),
        contradictory_evidence=(evidence[1],),
        graph=graph,
        created_at=NOW,
        expires_at=NOW + timedelta(hours=1),
    )


def rebuild_package(pkg: SignalEvidencePackageV2) -> SignalEvidencePackageV2:
    values = {
        item.name: getattr(pkg, item.name)
        for item in fields(pkg)
        if item.name
        not in {"package_id", "content_sha256", "contract_id", "schema_version"}
    }
    return SignalEvidencePackageV2.build(**values)


def gate_results(
    outcome: ValidationGateOutcomeV2 = ValidationGateOutcomeV2.PASS,
    *,
    missing: set[QualificationGateV2] | None = None,
    failed: set[QualificationGateV2] | None = None,
    valid_until: datetime | None = None,
) -> tuple[QualificationGateResultV2, ...]:
    missing = missing or set()
    failed = failed or set()
    source = {
        QualificationGateV2.DATA_INTEGRITY: "C-003",
        QualificationGateV2.POINT_IN_TIME: "C-027",
        QualificationGateV2.OOS: "C-071",
        QualificationGateV2.WALK_FORWARD: "C-029",
        QualificationGateV2.ROBUSTNESS: "C-030",
        QualificationGateV2.BIAS_LEAKAGE: "C-094",
        QualificationGateV2.RISK: "C-035",
        QualificationGateV2.REGIME_APPLICABILITY: "C-074",
    }
    result = []
    for gate in QualificationGateV2:
        if gate in missing:
            state, evidence = ValidationGateOutcomeV2.INSUFFICIENT_VALIDATION, None
        elif gate in failed:
            state, evidence = (
                ValidationGateOutcomeV2.FAIL,
                artifact_ref(source.get(gate, "C-028")),
            )
        else:
            state, evidence = outcome, artifact_ref(source.get(gate, "C-028"))
        result.append(
            QualificationGateResultV2(
                gate, state, evidence, valid_until or NOW + timedelta(days=1)
            )
        )
    return tuple(result)


def validation(
    pkg: SignalEvidencePackageV2,
    *,
    rate: Decimal | None = Decimal("0.75"),
    sample_size: int | None = 500,
    expectancy: Decimal | None = Decimal("0.01"),
    missing: set[QualificationGateV2] | None = None,
    failed: set[QualificationGateV2] | None = None,
    overall: ValidationOutcomeV2 = ValidationOutcomeV2.PASS,
    valid_until: datetime | None = None,
    gate_expiry: datetime | None = None,
) -> QualificationValidationResultV2:
    costs = spot_costs()
    # Keep cost-set identity and strategy scope exactly aligned with the package.
    costs = CostAssumptionSetV2.build(
        assumption_set_id=costs.assumption_set_id,
        strategy_version_id=pkg.strategy_version.artifact_id,
        asset="BTC-USDT",
        instrument_type="SPOT",
        required_categories=costs.required_categories,
        assumptions=costs.assumptions,
    )
    methodology = artifact_ref("C-028")
    rules = QualificationRuleSetV2.build(
        rule_set_id=uuid4(),
        version="1",
        strategy_version_id=pkg.strategy_version.artifact_id,
        asset="BTC-USDT",
        instrument_type="SPOT",
        timeframe="1h",
        regime="TRENDING_UP",
        conditional_event_definition="Candidate satisfies the configured strategy condition",
        conditional_win_rate_threshold=Decimal("0.75"),
        calibration_required=False,
        methodology=methodology,
        cost_assumption_set=ValidationArtifactReferenceV2(
            "C-027", costs.assumption_set_id, "2", costs.content_sha256
        ),
    )
    gates = gate_results(missing=missing, failed=failed, valid_until=gate_expiry)
    if overall is ValidationOutcomeV2.PASS and (missing or failed):
        overall = (
            ValidationOutcomeV2.FAIL
            if failed
            else ValidationOutcomeV2.INSUFFICIENT_VALIDATION
        )
    if rate is not None and rate < rules.conditional_win_rate_threshold:
        overall = ValidationOutcomeV2.FAIL
        gates = tuple(
            QualificationGateResultV2(
                g.gate,
                ValidationGateOutcomeV2.FAIL,
                artifact_ref("C-028"),
                g.valid_until,
            )
            if g.gate is QualificationGateV2.THRESHOLD
            else g
            for g in gates
        )
    if expectancy is not None and expectancy <= 0:
        overall = ValidationOutcomeV2.FAIL
        gates = tuple(
            QualificationGateResultV2(
                g.gate,
                ValidationGateOutcomeV2.FAIL,
                artifact_ref("C-027"),
                g.valid_until,
            )
            if g.gate is QualificationGateV2.EXPECTANCY_AFTER_COSTS
            else g
            for g in gates
        )
    if rate is None:
        gates = tuple(
            QualificationGateResultV2(
                g.gate,
                ValidationGateOutcomeV2.INSUFFICIENT_VALIDATION,
                None,
                g.valid_until,
            )
            if g.gate is QualificationGateV2.THRESHOLD
            else g
            for g in gates
        )
        overall = ValidationOutcomeV2.INSUFFICIENT_VALIDATION
    if sample_size is None:
        gates = tuple(
            QualificationGateResultV2(
                g.gate,
                ValidationGateOutcomeV2.INSUFFICIENT_VALIDATION,
                None,
                g.valid_until,
            )
            if g.gate is QualificationGateV2.SAMPLE_SUFFICIENCY
            else g
            for g in gates
        )
        overall = ValidationOutcomeV2.INSUFFICIENT_VALIDATION
    if expectancy is None:
        gates = tuple(
            QualificationGateResultV2(
                g.gate,
                ValidationGateOutcomeV2.INSUFFICIENT_VALIDATION,
                None,
                g.valid_until,
            )
            if g.gate is QualificationGateV2.EXPECTANCY_AFTER_COSTS
            else g
            for g in gates
        )
        overall = ValidationOutcomeV2.INSUFFICIENT_VALIDATION
    valid = valid_until or NOW + timedelta(hours=2)
    return QualificationValidationResultV2.build(
        result_id=uuid4(),
        candidate_id=pkg.candidate.artifact_id,
        candidate_sha256=pkg.candidate.content_sha256,
        evidence_package_id=pkg.package_id,
        evidence_package_sha256=pkg.content_sha256,
        strategy_version_id=pkg.strategy_version.artifact_id,
        asset="BTC-USDT",
        instrument_type="SPOT",
        timeframe="1h",
        regime="TRENDING_UP",
        rule_set=rules,
        cost_assumptions=costs,
        observed_conditional_win_rate=rate,
        sample_size=sample_size,
        effective_sample_size=Decimal(sample_size) if sample_size is not None else None,
        sample_semantics=artifact_ref("C-028"),
        after_cost_expectancy=expectancy,
        expectancy_unit="return_per_trade" if expectancy is not None else None,
        statistical_uncertainty=StatisticalUncertaintyEvidenceV2(
            artifact_ref("C-028"), artifact_ref("C-028"), ("conditional_win_rate",)
        ),
        statistical_support_state=StatisticalSupportStateV2.SUPPORTED,
        calibration=None,
        gates=gates,
        outcome=overall,
        methodology=methodology,
        created_at=NOW,
        as_of=NOW,
        valid_until=valid,
    )


def qualification(
    pkg: SignalEvidencePackageV2,
    validation_result: QualificationValidationResultV2,
    *,
    status: QualificationStatus = QualificationStatus.QUALIFIED,
) -> SignalQualificationV2:
    return SignalQualificationV2(
        qualification_id=uuid4(),
        candidate=pkg.candidate,
        strategy_version=pkg.strategy_version,
        evidence_package=VersionReference(
            "C-024", pkg.package_id, "2", pkg.content_sha256
        ),
        evidence_package_valid_until=pkg.expires_at,
        validation=validation_result,
        status=status,
        evaluated_at=NOW,
        expires_at=NOW + timedelta(minutes=30),
    )


def test_c024v2_is_prequalification_candidate_graph_and_unknown_survives_serialization() -> (
    None
):
    pkg = package()
    assert pkg.schema_version == "2"
    assert {node.node_type for node in pkg.graph.nodes} == set(EvidenceNodeTypeV2)
    assert pkg.dependence.state is EvidenceDependenceV2.UNKNOWN
    assert pkg.graph.nodes[0].dependence is EvidenceDependenceV2.UNKNOWN
    assert "QUALIFICATION" not in {node.node_type.value for node in pkg.graph.nodes}
    assert '"UNKNOWN"' in serialize_contract(pkg, payload_version="wire-1")
    assert rebuild_package(pkg).package_id == pkg.package_id


def test_c024v2_rejects_candidate_graph_mismatch_and_required_missing_c019() -> None:
    pkg = package()
    with pytest.raises(StrategyContractError, match="terminal graph candidate"):
        SignalEvidencePackageV2.build(
            candidate=ref("C-023"),
            strategy_version=pkg.strategy_version,
            eligibility=pkg.eligibility,
            market_context=pkg.market_context,
            analysis_snapshot=pkg.analysis_snapshot,
            data_quality_report=pkg.data_quality_report,
            candidate_valid_until=pkg.candidate_valid_until,
            market_context_valid_until=pkg.market_context_valid_until,
            analysis_snapshot_valid_until=pkg.analysis_snapshot_valid_until,
            evidence_references=pkg.evidence_references,
            confluence=pkg.confluence,
            conflicts=pkg.conflicts,
            adversarial_assessment=pkg.adversarial_assessment,
            adversarial_assessment_required=True,
            uncertainties=pkg.uncertainties,
            dependence=pkg.dependence,
            supporting_evidence=pkg.supporting_evidence,
            contradictory_evidence=pkg.contradictory_evidence,
            graph=pkg.graph,
            created_at=NOW,
            expires_at=pkg.expires_at,
        )
    with pytest.raises(StrategyContractError, match="required C-019"):
        SignalEvidencePackageV2.build(
            candidate=pkg.candidate,
            strategy_version=pkg.strategy_version,
            eligibility=pkg.eligibility,
            market_context=pkg.market_context,
            analysis_snapshot=pkg.analysis_snapshot,
            data_quality_report=pkg.data_quality_report,
            candidate_valid_until=pkg.candidate_valid_until,
            market_context_valid_until=pkg.market_context_valid_until,
            analysis_snapshot_valid_until=pkg.analysis_snapshot_valid_until,
            evidence_references=pkg.evidence_references,
            confluence=pkg.confluence,
            conflicts=pkg.conflicts,
            adversarial_assessment=None,
            adversarial_assessment_required=True,
            uncertainties=pkg.uncertainties,
            dependence=pkg.dependence,
            supporting_evidence=pkg.supporting_evidence,
            contradictory_evidence=pkg.contradictory_evidence,
            graph=pkg.graph,
            created_at=NOW,
            expires_at=pkg.expires_at,
        )


def test_c027v2_spot_funding_not_applicable_has_no_fabricated_zero() -> None:
    costs = spot_costs()
    funding = next(
        item
        for item in costs.assumptions
        if item.category is AssumptionCategory.FUNDING
    )
    assert funding.applicability is CostApplicabilityV2.NOT_APPLICABLE
    assert funding.value is None and funding.unit is None
    wrong_funding = ResearchAssumptionV2(
        AssumptionCategory.FUNDING,
        CostApplicabilityV2.APPLICABLE,
        artifact_ref("C-027"),
        Decimal("0"),
        "USD",
        "fabricated zero",
    )
    with pytest.raises(
        ValidationContractError, match="Spot funding must be explicitly"
    ):
        CostAssumptionSetV2.build(
            assumption_set_id=uuid4(),
            strategy_version_id=uuid4(),
            asset="BTC-USDT",
            instrument_type="SPOT",
            required_categories=costs.required_categories,
            assumptions=tuple(
                wrong_funding if a.category is AssumptionCategory.FUNDING else a
                for a in costs.assumptions
            ),
        )


def test_c028v2_threshold_equality_passes_only_with_every_authoritative_gate() -> None:
    pkg = package()
    result = validation(pkg)
    assert result.outcome is ValidationOutcomeV2.PASS
    assert (
        result.observed_conditional_win_rate
        == result.rule_set.conditional_win_rate_threshold
    )
    assert all(g.outcome is ValidationGateOutcomeV2.PASS for g in result.gates)
    assert qualification(pkg, result).status is QualificationStatus.QUALIFIED
    serialized = serialize_contract(result, payload_version="wire-1")
    assert '"conditional_win_rate_threshold":"0.75"' in serialized
    assert '"observed_conditional_win_rate":"0.75"' in serialized
    rebuilt = QualificationValidationResultV2.build(
        **{
            item.name: getattr(result, item.name)
            for item in fields(result)
            if item.name not in {"content_sha256", "contract_id", "schema_version"}
        }
    )
    assert rebuilt.content_sha256 == result.content_sha256
    assert rebuilt.result_id == result.result_id


@pytest.mark.parametrize(
    ("kwargs", "expected"),
    [
        ({"rate": Decimal("0.74")}, ValidationOutcomeV2.FAIL),
        ({"sample_size": None}, ValidationOutcomeV2.INSUFFICIENT_VALIDATION),
        (
            {"sample_size": 1, "missing": {QualificationGateV2.SAMPLE_SUFFICIENCY}},
            ValidationOutcomeV2.INSUFFICIENT_VALIDATION,
        ),
        (
            {"missing": {QualificationGateV2.OOS}},
            ValidationOutcomeV2.INSUFFICIENT_VALIDATION,
        ),
        ({"failed": {QualificationGateV2.OOS}}, ValidationOutcomeV2.FAIL),
        (
            {"missing": {QualificationGateV2.ROBUSTNESS}},
            ValidationOutcomeV2.INSUFFICIENT_VALIDATION,
        ),
        ({"expectancy": Decimal("0")}, ValidationOutcomeV2.FAIL),
        (
            {"missing": {QualificationGateV2.RISK}},
            ValidationOutcomeV2.INSUFFICIENT_VALIDATION,
        ),
    ],
)
def test_c028v2_fails_closed_for_missing_or_failed_gates(
    kwargs: dict[str, object], expected: ValidationOutcomeV2
) -> None:
    pkg = package()
    result = validation(pkg, **kwargs)  # type: ignore[arg-type]
    assert result.outcome is expected
    if expected is not ValidationOutcomeV2.PASS:
        with pytest.raises(
            StrategyContractError, match="authoritative validation PASS"
        ):
            qualification(pkg, result)


def test_c028v2_rejects_stale_gate_expiry_and_regime_mismatch() -> None:
    pkg = package()
    with pytest.raises(ValidationContractError, match="bounded by all gate expiries"):
        validation(pkg, valid_until=NOW + timedelta(days=3))
    with pytest.raises(ValidationContractError, match="scope must exactly match"):
        result = validation(pkg)
        altered = QualificationRuleSetV2.build(
            rule_set_id=uuid4(),
            version="2",
            strategy_version_id=result.strategy_version_id,
            asset=result.asset,
            instrument_type="SPOT",
            timeframe=result.timeframe,
            regime="RANGING",
            conditional_event_definition="changed",
            conditional_win_rate_threshold=Decimal("0.75"),
            calibration_required=False,
            methodology=artifact_ref("C-028"),
            cost_assumption_set=ValidationArtifactReferenceV2(
                "C-027",
                result.cost_assumptions.assumption_set_id,
                "2",
                result.cost_assumptions.content_sha256,
            ),
        )
        QualificationValidationResultV2.build(
            result_id=uuid4(),
            candidate_id=result.candidate_id,
            candidate_sha256=result.candidate_sha256,
            evidence_package_id=result.evidence_package_id,
            evidence_package_sha256=result.evidence_package_sha256,
            strategy_version_id=result.strategy_version_id,
            asset=result.asset,
            instrument_type=result.instrument_type,
            timeframe=result.timeframe,
            regime=result.regime,
            rule_set=altered,
            cost_assumptions=result.cost_assumptions,
            observed_conditional_win_rate=result.observed_conditional_win_rate,
            sample_size=result.sample_size,
            effective_sample_size=result.effective_sample_size,
            sample_semantics=result.sample_semantics,
            after_cost_expectancy=result.after_cost_expectancy,
            expectancy_unit=result.expectancy_unit,
            statistical_uncertainty=result.statistical_uncertainty,
            statistical_support_state=result.statistical_support_state,
            calibration=result.calibration,
            gates=result.gates,
            outcome=result.outcome,
            methodology=result.methodology,
            created_at=NOW,
            as_of=NOW,
            valid_until=result.valid_until,
        )


def test_c025v2_requires_exact_package_and_validation_versions_and_not_c023_placeholders() -> (
    None
):
    pkg = package()
    result = validation(pkg)
    assert not {"analytical_confidence", "evidence_strength"} & {
        f.name for f in fields(SignalQualificationV2)
    }
    with pytest.raises(StrategyContractError, match="schema 2"):
        SignalQualificationV2(
            qualification_id=uuid4(),
            candidate=pkg.candidate,
            strategy_version=pkg.strategy_version,
            evidence_package=VersionReference(
                "C-024", pkg.package_id, "1", pkg.content_sha256
            ),
            evidence_package_valid_until=pkg.expires_at,
            validation=result,
            status=QualificationStatus.QUALIFIED,
            evaluated_at=NOW,
            expires_at=NOW + timedelta(minutes=10),
        )
    with pytest.raises(StrategyContractError, match="cannot outlive"):
        SignalQualificationV2(
            qualification_id=uuid4(),
            candidate=pkg.candidate,
            strategy_version=pkg.strategy_version,
            evidence_package=VersionReference(
                "C-024", pkg.package_id, "2", pkg.content_sha256
            ),
            evidence_package_valid_until=NOW + timedelta(minutes=5),
            validation=result,
            status=QualificationStatus.QUALIFIED,
            evaluated_at=NOW,
            expires_at=NOW + timedelta(minutes=10),
        )
    with pytest.raises(StrategyContractError, match="candidate content digest"):
        SignalQualificationV2(
            qualification_id=uuid4(),
            candidate=VersionReference(
                "C-023", pkg.candidate.artifact_id, "1", "b" * 64
            ),
            strategy_version=pkg.strategy_version,
            evidence_package=VersionReference(
                "C-024", pkg.package_id, "2", pkg.content_sha256
            ),
            evidence_package_valid_until=pkg.expires_at,
            validation=result,
            status=QualificationStatus.QUALIFIED,
            evaluated_at=NOW,
            expires_at=NOW + timedelta(minutes=10),
        )


def test_c025v2_withholds_qualification_when_validation_is_expired() -> None:
    pkg = package()
    expired = validation(
        pkg,
        valid_until=NOW + timedelta(minutes=5),
        gate_expiry=NOW + timedelta(minutes=5),
    )
    with pytest.raises(StrategyContractError, match="cannot outlive"):
        qualification(pkg, expired)
