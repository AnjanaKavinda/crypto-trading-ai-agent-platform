from dataclasses import FrozenInstanceError, fields
from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from trading_platform_api.config import DeploymentEnvironment, OperatingMode
from trading_platform_api.strategy import (
    ConditionGroup,
    ConditionGroupOperator,
    ConditionOperator,
    EligibilityState,
    EvidenceDependence,
    EvidenceGraph,
    EvidenceGraphEdge,
    EvidenceGraphNode,
    EvidenceNodeType,
    NoTradeDecision,
    NoTradeReason,
    QualificationRuleResult,
    QualificationStatus,
    RuleOutcome,
    SetupState,
    Signal,
    SignalCandidate,
    SignalConcept,
    SignalDirection,
    SignalEvidencePackage,
    SignalLifecycleState,
    SignalLineage,
    SignalQualification,
    Strategy,
    StrategyCondition,
    StrategyContractError,
    StrategyEligibility,
    StrategyLifecycle,
    StrategyParameter,
    StrategyVersion,
    ValidationReference,
    ValidationStatus,
    VersionReference,
)

T0 = datetime(2026, 1, 1, tzinfo=UTC)
T1 = T0 + timedelta(seconds=1)
T2 = T0 + timedelta(seconds=2)
T3 = T0 + timedelta(seconds=3)
HASH_A = "a" * 64
HASH_B = "b" * 64


def reference(
    kind: str = "configuration", artifact_id: UUID | None = None
) -> VersionReference:
    return VersionReference(kind, artifact_id or uuid4(), "v1", HASH_A)


def condition() -> StrategyCondition:
    return StrategyCondition(
        uuid4(), "market.regime", ConditionOperator.EQUALS, ("trend",), "v1"
    )


def strategy_version(**overrides: object) -> StrategyVersion:
    item = condition()
    values: dict[str, object] = {
        "strategy_version_id": uuid4(),
        "strategy_id": uuid4(),
        "semantic_version": "1.0.0",
        "lifecycle": StrategyLifecycle.RESEARCH,
        "content_sha256": HASH_A,
        "parent_version_id": None,
        "parameters": (StrategyParameter("lookback", "20", "bars"),),
        "conditions": (item,),
        "condition_groups": (
            ConditionGroup(uuid4(), ConditionGroupOperator.AND, (item.condition_id,)),
        ),
        "supported_assets": ("BTC",),
        "supported_instruments": ("BTC-USDT-SPOT",),
        "supported_timeframes": ("1h",),
        "preferred_regimes": ("trend",),
        "acceptable_regimes": ("transition",),
        "incompatible_regimes": ("illiquid",),
        "required_evidence_categories": ("technical",),
        "entry_concept": "structure confirmation",
        "invalidation_concept": "structure invalidation",
        "target_concepts": ("analytical reference level",),
        "environments": (DeploymentEnvironment.DEV,),
        "operating_modes": (OperatingMode.RESEARCH,),
        "provenance": (reference("definition"),),
        "created_at": T0,
    }
    values.update(overrides)
    return StrategyVersion(**values)  # type: ignore[arg-type]


def eligibility(**overrides: object) -> StrategyEligibility:
    values: dict[str, object] = {
        "eligibility_id": uuid4(),
        "strategy_version_id": uuid4(),
        "market_context_id": uuid4(),
        "asset": "BTC",
        "instrument_id": "BTC-USDT-SPOT",
        "timeframe": "1h",
        "state": EligibilityState.ELIGIBLE,
        "reason_codes": (),
        "data_quality_report_id": uuid4(),
        "regime_id": uuid4(),
        "evaluated_at": T0,
        "expires_at": T3,
    }
    values.update(overrides)
    return StrategyEligibility(**values)  # type: ignore[arg-type]


def concept(kind: str) -> SignalConcept:
    return SignalConcept(
        kind, f"{kind} analytical concept", ("100",), reference("method")
    )


def candidate(**overrides: object) -> SignalCandidate:
    values: dict[str, object] = {
        "candidate_id": uuid4(),
        "strategy_id": uuid4(),
        "strategy_version_id": uuid4(),
        "eligibility_id": uuid4(),
        "eligibility_state": EligibilityState.ELIGIBLE,
        "market_context_id": uuid4(),
        "analysis_snapshot_id": uuid4(),
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
        "data_quality_report_id": uuid4(),
        "analytical_confidence": Decimal("0.7"),
        "evidence_strength": Decimal("0.6"),
        "lifecycle": SignalLifecycleState.CANDIDATE,
        "created_at": T0,
        "expires_at": T3,
    }
    values.update(overrides)
    return SignalCandidate(**values)  # type: ignore[arg-type]


def graph() -> EvidenceGraph:
    nodes = tuple(
        EvidenceGraphNode(uuid4(), node_type, contract_id, uuid4(), "1", dependence)
        for node_type, contract_id, dependence in (
            (EvidenceNodeType.EVIDENCE, "C-008", EvidenceDependence.INDEPENDENT),
            (EvidenceNodeType.FINDING, "C-007", EvidenceDependence.INDEPENDENT),
            (
                EvidenceNodeType.STRATEGY_CONDITION,
                "C-021",
                EvidenceDependence.PARTIALLY_DEPENDENT,
            ),
            (
                EvidenceNodeType.QUALIFICATION,
                "C-025",
                EvidenceDependence.PARTIALLY_DEPENDENT,
            ),
        )
    )
    return EvidenceGraph(
        nodes,
        (
            EvidenceGraphEdge(nodes[0].node_id, nodes[1].node_id, "supports"),
            EvidenceGraphEdge(nodes[1].node_id, nodes[2].node_id, "satisfies"),
            EvidenceGraphEdge(nodes[2].node_id, nodes[3].node_id, "qualifies"),
        ),
    )


def package(**overrides: object) -> SignalEvidencePackage:
    values: dict[str, object] = {
        "package_id": uuid4(),
        "candidate_id": uuid4(),
        "strategy_version_id": uuid4(),
        "market_context_id": uuid4(),
        "graph": graph(),
        "supporting_evidence_ids": (uuid4(),),
        "contradictory_evidence_ids": (),
        "created_at": T0,
        "expires_at": T3,
        "content_sha256": HASH_A,
    }
    values.update(overrides)
    return SignalEvidencePackage(**values)  # type: ignore[arg-type]


def validation(
    strategy_version_id: UUID, status: ValidationStatus = ValidationStatus.PASSED
) -> ValidationReference:
    return ValidationReference(uuid4(), strategy_version_id, status, "method-v1", T3)


def qualification(**overrides: object) -> SignalQualification:
    strategy_version_id = cast_uuid(overrides.get("strategy_version_id", uuid4()))
    values: dict[str, object] = {
        "qualification_id": uuid4(),
        "candidate_id": uuid4(),
        "evidence_package_id": uuid4(),
        "strategy_version_id": strategy_version_id,
        "status": QualificationStatus.QUALIFIED,
        "rule_set": reference("qualification-rules"),
        "rule_results": (
            QualificationRuleResult("evidence-fresh", RuleOutcome.PASSED, "passed"),
        ),
        "evidence_fresh": True,
        "data_quality_acceptable": True,
        "regime_compatible": True,
        "conflicts_resolved": True,
        "validation": validation(strategy_version_id),
        "historical_performance": None,
        "evaluated_at": T0,
        "expires_at": T2,
    }
    values.update(overrides)
    return SignalQualification(**values)  # type: ignore[arg-type]


def cast_uuid(value: object) -> UUID:
    assert isinstance(value, UUID)
    return value


def signal(**overrides: object) -> Signal:
    strategy_version_id = cast_uuid(overrides.get("strategy_version_id", uuid4()))
    candidate_id = uuid4()
    package_id = uuid4()
    values: dict[str, object] = {
        "signal_id": uuid4(),
        "lineage": SignalLineage(
            candidate_id,
            strategy_version_id,
            package_id,
            candidate_id,
            strategy_version_id,
            uuid4(),
            candidate_id,
            package_id,
            strategy_version_id,
        ),
        "strategy_id": uuid4(),
        "strategy_version_id": strategy_version_id,
        "parameter_set": reference("parameters"),
        "configuration": reference("configuration"),
        "validation": validation(strategy_version_id),
        "qualification_status": QualificationStatus.QUALIFIED,
        "market_context_id": uuid4(),
        "analysis_snapshot_id": uuid4(),
        "asset": "BTC",
        "instrument_id": "BTC-USDT-SPOT",
        "timeframe": "1h",
        "direction": SignalDirection.LONG,
        "evidence_ids": (uuid4(),),
        "data_quality_report_id": uuid4(),
        "regime_id": uuid4(),
        "conflict_ids": (),
        "uncertainty_ids": (uuid4(),),
        "lifecycle": SignalLifecycleState.QUALIFIED,
        "created_at": T1,
        "expires_at": T2,
    }
    values.update(overrides)
    return Signal(**values)  # type: ignore[arg-type]


def test_eight_canonical_contracts_are_distinct_and_frozen() -> None:
    version = strategy_version()
    values = (
        Strategy(uuid4(), "Trend", "Trend template", "trend", T0),
        version,
        eligibility(strategy_version_id=version.strategy_version_id),
        candidate(
            strategy_id=version.strategy_id,
            strategy_version_id=version.strategy_version_id,
        ),
        package(strategy_version_id=version.strategy_version_id),
        qualification(strategy_version_id=version.strategy_version_id),
        NoTradeDecision(
            uuid4(),
            uuid4(),
            None,
            None,
            (NoTradeReason.NO_SETUP,),
            "No setup exists.",
            (),
            (),
            (),
            uuid4(),
            (reference(),),
            "trace-1",
            SignalLifecycleState.NO_TRADE,
            T0,
            T2,
        ),
        signal(strategy_version_id=version.strategy_version_id),
    )
    assert [(item.contract_id, item.schema_version) for item in values] == [
        ("C-020", "1"),
        ("C-021", "1"),
        ("C-022", "1"),
        ("C-023", "1"),
        ("C-024", "1"),
        ("C-025", "1"),
        ("C-026", "1"),
        ("C-070", "1"),
    ]
    for item in values:
        with pytest.raises(FrozenInstanceError):
            item.schema_version = "2"  # type: ignore[misc]


def test_strategy_version_is_hash_bound_and_reconstructable() -> None:
    first = strategy_version(content_sha256=HASH_A)
    second = strategy_version(
        strategy_id=first.strategy_id,
        parent_version_id=first.strategy_version_id,
        semantic_version="1.1.0",
        content_sha256=HASH_B,
    )
    assert first.strategy_version_id != second.strategy_version_id
    assert first.content_sha256 != second.content_sha256
    with pytest.raises(StrategyContractError, match="SHA-256"):
        strategy_version(content_sha256="invalid")


def test_strategy_version_rejects_unknown_conditions_and_regime_overlap() -> None:
    item = condition()
    with pytest.raises(StrategyContractError, match="unknown condition"):
        strategy_version(
            conditions=(item,),
            condition_groups=(
                ConditionGroup(uuid4(), ConditionGroupOperator.AND, (uuid4(),)),
            ),
        )
    with pytest.raises(StrategyContractError, match="overlap"):
        strategy_version(preferred_regimes=("trend",), incompatible_regimes=("trend",))


def test_ineligible_strategy_cannot_form_candidate() -> None:
    value = eligibility(
        state=EligibilityState.NOT_ELIGIBLE, reason_codes=("REGIME_MISMATCH",)
    )
    assert value.contract_id == "C-022"
    with pytest.raises(StrategyContractError, match="requires ELIGIBLE"):
        candidate(eligibility_state=value.state)
    with pytest.raises(StrategyContractError, match="requires reason_codes"):
        eligibility(state=EligibilityState.INSUFFICIENT_DATA, reason_codes=())


def test_candidate_is_time_bounded_and_non_executable() -> None:
    value = candidate()
    assert value.lifecycle is SignalLifecycleState.CANDIDATE
    prohibited = {"order", "quantity", "approval", "execution_intent", "risk_accepted"}
    assert prohibited.isdisjoint(item.name for item in fields(value))
    with pytest.raises(StrategyContractError, match="not active"):
        candidate(setup_state=SetupState.EXPIRED)
    with pytest.raises(StrategyContractError, match="must not be after"):
        candidate(created_at=T2, expires_at=T1)


def test_evidence_graph_rejects_orphans_duplicates_cycles_and_missing_types() -> None:
    valid = graph()
    with pytest.raises(StrategyContractError, match="unknown node"):
        EvidenceGraph(
            valid.nodes,
            valid.edges + (EvidenceGraphEdge(uuid4(), valid.nodes[0].node_id, "bad"),),
        )
    with pytest.raises(StrategyContractError, match="duplicates"):
        EvidenceGraph(valid.nodes, valid.edges + (valid.edges[0],))
    cycle = valid.edges + (
        EvidenceGraphEdge(valid.nodes[-1].node_id, valid.nodes[0].node_id, "cycle"),
    )
    with pytest.raises(StrategyContractError, match="lineage order|acyclic"):
        EvidenceGraph(valid.nodes, cycle)
    with pytest.raises(StrategyContractError, match="every required"):
        EvidenceGraph(valid.nodes[:-1], valid.edges[:-1])
    wrong_order = (
        EvidenceGraphEdge(valid.nodes[1].node_id, valid.nodes[0].node_id, "reversed"),
        *valid.edges[1:],
    )
    with pytest.raises(StrategyContractError, match="lineage order"):
        EvidenceGraph(valid.nodes, wrong_order)


def test_qualification_keeps_contract_gates_and_validation_explicit() -> None:
    value = qualification()
    assert value.validation is not None
    assert value.validation.contract_id == "C-028"
    with pytest.raises(StrategyContractError, match="all contract gates"):
        qualification(evidence_fresh=False)
    with pytest.raises(StrategyContractError, match="passed rule"):
        qualification(
            rule_results=(
                QualificationRuleResult("gate", RuleOutcome.FAILED, "failed"),
            )
        )


@pytest.mark.parametrize(
    "status",
    [
        ValidationStatus.NOT_RUN,
        ValidationStatus.RUNNING,
        ValidationStatus.FAILED,
        ValidationStatus.INCONCLUSIVE,
        ValidationStatus.STALE,
        ValidationStatus.EXPIRED,
    ],
)
def test_non_passed_validation_cannot_create_signal(status: ValidationStatus) -> None:
    strategy_version_id = uuid4()
    with pytest.raises(StrategyContractError, match="PASSED"):
        signal(
            strategy_version_id=strategy_version_id,
            validation=validation(strategy_version_id, status),
        )


def test_signal_rejects_version_status_lifecycle_and_expiry_mismatches() -> None:
    with pytest.raises(StrategyContractError, match="version mismatch"):
        signal(validation=validation(uuid4()))
    with pytest.raises(StrategyContractError, match="qualified status"):
        signal(qualification_status=QualificationStatus.REJECTED)
    with pytest.raises(StrategyContractError, match="lifecycle"):
        signal(lifecycle=SignalLifecycleState.EXPIRED)
    strategy_version_id = uuid4()
    expired_validation = ValidationReference(
        uuid4(), strategy_version_id, ValidationStatus.PASSED, "v1", T1
    )
    with pytest.raises(StrategyContractError, match="expires before"):
        signal(strategy_version_id=strategy_version_id, validation=expired_validation)


def test_signal_rejects_candidate_package_qualification_lineage_mismatch() -> None:
    strategy_version_id = uuid4()
    candidate_id = uuid4()
    package_id = uuid4()
    with pytest.raises(StrategyContractError, match="candidate lineage mismatch"):
        SignalLineage(
            candidate_id,
            strategy_version_id,
            package_id,
            uuid4(),
            strategy_version_id,
            uuid4(),
            candidate_id,
            package_id,
            strategy_version_id,
        )
    valid_lineage = SignalLineage(
        candidate_id,
        strategy_version_id,
        package_id,
        candidate_id,
        strategy_version_id,
        uuid4(),
        candidate_id,
        package_id,
        strategy_version_id,
    )
    with pytest.raises(StrategyContractError, match="Signal strategy version lineage"):
        signal(strategy_version_id=uuid4(), lineage=valid_lineage)


def test_signal_is_explicitly_non_executable() -> None:
    value = signal()
    assert value.execution_authorized is False
    prohibited = {
        "order_type",
        "quantity",
        "exchange_credentials",
        "approval_decision",
        "execution_intent",
        "risk_acceptance",
    }
    assert prohibited.isdisjoint(item.name for item in fields(value))


def test_no_trade_is_complete_successful_abstention() -> None:
    value = NoTradeDecision(
        decision_id=uuid4(),
        market_context_id=uuid4(),
        candidate_id=uuid4(),
        strategy_version_id=uuid4(),
        reasons=(
            NoTradeReason.INSUFFICIENT_EVIDENCE,
            NoTradeReason.UNRESOLVED_CONFLICT,
        ),
        explanation="Evidence is insufficient and conflicted.",
        blocking_evidence_ids=(uuid4(),),
        conflict_ids=(uuid4(),),
        uncertainty_ids=(uuid4(),),
        data_quality_report_id=uuid4(),
        provenance=(reference("decision-policy"),),
        correlation_id="trace-1",
        lifecycle=SignalLifecycleState.NO_TRADE,
        decided_at=T0,
        expires_at=T2,
    )
    assert value.contract_id == "C-026"
    assert value.lifecycle is SignalLifecycleState.NO_TRADE
    with pytest.raises(StrategyContractError, match="must be NO_TRADE"):
        NoTradeDecision(
            value.decision_id,
            value.market_context_id,
            value.candidate_id,
            value.strategy_version_id,
            value.reasons,
            value.explanation,
            value.blocking_evidence_ids,
            value.conflict_ids,
            value.uncertainty_ids,
            value.data_quality_report_id,
            value.provenance,
            value.correlation_id,
            SignalLifecycleState.QUALIFIED,
            value.decided_at,
            value.expires_at,
        )


def test_common_validation_rejects_naive_time_bad_score_and_mutable_collection() -> (
    None
):
    with pytest.raises(StrategyContractError, match="timezone-aware"):
        candidate(created_at=datetime(2026, 1, 1))
    with pytest.raises(StrategyContractError, match="between 0 and 1"):
        candidate(evidence_strength=Decimal("1.1"))
    with pytest.raises(StrategyContractError, match="must be a tuple"):
        candidate(supporting_evidence_ids=[uuid4()])
    with pytest.raises(StrategyContractError, match="surrounding whitespace"):
        candidate(asset=" BTC")


def test_aware_times_normalize_to_utc() -> None:
    offset = datetime(
        2026, 1, 1, 5, 30, tzinfo=timezone(timedelta(hours=5, minutes=30))
    )
    value = candidate(created_at=offset, expires_at=offset + timedelta(seconds=3))
    assert value.created_at == T0
    assert value.created_at.tzinfo is UTC
