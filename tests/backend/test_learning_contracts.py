from __future__ import annotations

from dataclasses import FrozenInstanceError, fields, replace
from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal
from uuid import uuid4

import pytest
import trading_platform_api.learning as learning_package
from trading_platform_api.learning import (
    AgentPerformance,
    ArtifactLifecycle,
    AwarenessStatus,
    CalibrationRecord,
    ChampionChallengerRecord,
    ComparisonOutcome,
    CounterfactualAnalysis,
    CounterfactualClassification,
    DriftAssessment,
    DriftDimension,
    DriftStatus,
    EvaluationMode,
    EvaluationScope,
    EvidenceReference,
    Experience,
    ExperienceRecord,
    ExperienceStatus,
    Experiment,
    ExperimentResult,
    ExperimentResultStatus,
    ExperimentStatus,
    GovernanceActorReference,
    GovernanceDecision,
    GovernanceDecisionType,
    Hypothesis,
    KnowledgeArtifact,
    KnowledgeStatus,
    LearningContractError,
    LearningInsight,
    LearningObservation,
    LearningPipelineState,
    MetricObservation,
    StrategyChangeProposal,
    StrategyDecayState,
    StrategyPerformance,
    SystemAwarenessSnapshot,
    VersionedArtifact,
)
from trading_platform_api.risk import ContractReference, VersionReference
from trading_platform_api.validation import CalibrationResult

NOW = datetime(2026, 9, 26, 12, 0, tzinfo=UTC)
SHA_A = "a" * 64
SHA_B = "b" * 64
SHA_C = "c" * 64


def version(component: str = "learning", sha: str = SHA_A) -> VersionReference:
    return VersionReference(component=component, version="1.0.0", content_sha256=sha)


def ref(contract_id: str) -> ContractReference:
    return ContractReference(
        contract_id=contract_id,
        entity_id=uuid4(),
        schema_version="1",
        content_sha256=SHA_A,
        valid_until=NOW + timedelta(days=1),
    )


def evidence(evidence_type: str = "SYNTHETIC_TEST_EVIDENCE") -> EvidenceReference:
    return EvidenceReference(
        evidence_id=uuid4(),
        evidence_type=evidence_type,
        source="synthetic-test",
        source_version="1",
        content_sha256=SHA_A,
    )


def metric(name: str = "accuracy", **overrides: object) -> MetricObservation:
    values: dict[str, object] = {
        "name": name,
        "value": Decimal("0.75"),
        "unit": "ratio",
        "sample_size": 10,
        "method_version": version("metric-method"),
        "evidence": (evidence(),),
        "interval_lower": Decimal("0.70"),
        "interval_upper": Decimal("0.80"),
    }
    values.update(overrides)
    return MetricObservation(**values)  # type: ignore[arg-type]


def scope() -> EvaluationScope:
    return EvaluationScope(
        assets=("BTC-USDT",),
        timeframes=("1h",),
        regimes=("TRENDING",),
        task="signal-evaluation",
    )


def artifact(
    component: str,
    lifecycle: ArtifactLifecycle = ArtifactLifecycle.VALIDATED,
    sha: str = SHA_A,
) -> VersionedArtifact:
    return VersionedArtifact(
        artifact_id=uuid4(),
        artifact_type=component,
        version=version(component, sha),
        lifecycle=lifecycle,
    )


def experience(**overrides: object) -> Experience:
    values: dict[str, object] = {
        "experience_id": uuid4(),
        "status": ExperienceStatus.EXECUTED,
        "market_refs": (ref("C-002"), ref("C-005")),
        "analysis_refs": (ref("C-007"), ref("C-008")),
        "strategy_refs": (ref("C-020"), ref("C-021")),
        "decision_refs": (ref("C-023"), ref("C-024")),
        "validation_refs": (ref("C-028"), ref("C-031")),
        "risk_refs": (ref("C-032"), ref("C-034")),
        "approval_ref": ref("C-038"),
        "execution_refs": (ref("C-039"), ref("C-043")),
        "factual_outcome_ref": ref("C-044"),
        "agent_output_refs": (evidence("AGENT_OUTPUT"),),
        "safety_refs": (ref("C-058"), ref("C-059")),
        "awareness_ref": ref("C-054"),
        "correlation_id": "correlation-1",
        "occurred_at": NOW - timedelta(minutes=1),
        "recorded_at": NOW,
        "content_sha256": SHA_A,
    }
    values.update(overrides)
    return Experience(**values)  # type: ignore[arg-type]


def observation(**overrides: object) -> LearningObservation:
    values: dict[str, object] = {
        "observation_id": uuid4(),
        "experience_refs": (ref("C-045"),),
        "scope": scope(),
        "statement": "Synthetic observation",
        "sample_size": 20,
        "evidence": (evidence(),),
        "uncertainty": Decimal("0.20"),
        "limitations": ("Synthetic test data only",),
        "observed_at": NOW,
        "method_version": version("observation-method"),
        "content_sha256": SHA_A,
    }
    values.update(overrides)
    return LearningObservation(**values)  # type: ignore[arg-type]


def insight(**overrides: object) -> LearningInsight:
    values: dict[str, object] = {
        "insight_id": uuid4(),
        "observation_refs": (ref("C-046"),),
        "scope": scope(),
        "statement": "Synthetic insight",
        "evidence": (evidence(),),
        "uncertainty": Decimal("0.25"),
        "limitations": ("Requires independent validation",),
        "created_at": NOW,
        "method_version": version("insight-method"),
        "content_sha256": SHA_A,
    }
    values.update(overrides)
    return LearningInsight(**values)  # type: ignore[arg-type]


def hypothesis(**overrides: object) -> Hypothesis:
    values: dict[str, object] = {
        "hypothesis_id": uuid4(),
        "insight_refs": (ref("C-047"),),
        "scope": scope(),
        "statement": "Candidate filter may improve evidence quality",
        "expected_effect": "Reduce false positive signals",
        "falsification_criteria": ("False-positive rate does not improve",),
        "success_criteria": ("Pre-registered metric threshold is met",),
        "evidence": (evidence(),),
        "created_at": NOW,
        "content_sha256": SHA_A,
    }
    values.update(overrides)
    return Hypothesis(**values)  # type: ignore[arg-type]


def experiment(**overrides: object) -> Experiment:
    values: dict[str, object] = {
        "experiment_id": uuid4(),
        "hypothesis_ref": ref("C-048"),
        "status": ExperimentStatus.APPROVED_FOR_RESEARCH,
        "baseline": artifact("strategy", sha=SHA_A),
        "candidate": artifact("strategy", sha=SHA_B),
        "dataset": artifact("dataset", sha=SHA_C),
        "method_version": version("experiment-method"),
        "scope": scope(),
        "metric_names": ("accuracy", "calibration"),
        "fold_ids": ("fold-1", "fold-2"),
        "assumptions": ("Dataset remains immutable",),
        "research_approval": evidence("RESEARCH_APPROVAL"),
        "window_start": NOW + timedelta(hours=1),
        "window_end": NOW + timedelta(hours=2),
        "created_at": NOW,
        "content_sha256": SHA_A,
    }
    values.update(overrides)
    return Experiment(**values)  # type: ignore[arg-type]


def experiment_result(**overrides: object) -> ExperimentResult:
    values: dict[str, object] = {
        "result_id": uuid4(),
        "experiment_ref": ref("C-049"),
        "experiment_version": version("experiment"),
        "status": ExperimentResultStatus.VALIDATED,
        "baseline": artifact("strategy", sha=SHA_A),
        "candidate": artifact("strategy", sha=SHA_B),
        "metrics": (metric(),),
        "validation_refs": (ref("C-028"), ref("C-031")),
        "evidence": (evidence(),),
        "uncertainty": Decimal("0.15"),
        "limitations": ("Synthetic test data only",),
        "evaluated_at": NOW,
        "content_sha256": SHA_A,
    }
    values.update(overrides)
    return ExperimentResult(**values)  # type: ignore[arg-type]


def strategy_proposal(**overrides: object) -> StrategyChangeProposal:
    current = artifact("strategy", ArtifactLifecycle.ACTIVE, SHA_A)
    values: dict[str, object] = {
        "proposal_id": uuid4(),
        "result_refs": (ref("C-050"),),
        "current_artifact": current,
        "proposed_artifact": artifact("strategy", ArtifactLifecycle.VALIDATED, SHA_B),
        "rationale": "Validated experiment supports governed review",
        "expected_effect": "Improve evidence quality",
        "compatibility_refs": (evidence("COMPATIBILITY"),),
        "rollback_target": current,
        "created_at": NOW,
        "content_sha256": SHA_A,
    }
    values.update(overrides)
    return StrategyChangeProposal(**values)  # type: ignore[arg-type]


def agent_performance(**overrides: object) -> AgentPerformance:
    values: dict[str, object] = {
        "performance_id": uuid4(),
        "agent": artifact("analysis-agent"),
        "model_version": version("model"),
        "prompt_version": version("prompt"),
        "scope": scope(),
        "sample_size": 20,
        "metrics": (metric(),),
        "calibration_ref": ref("C-031"),
        "drift_ref": ref("C-055"),
        "evidence": (evidence(),),
        "uncertainty": Decimal("0.10"),
        "limitations": ("Synthetic test data only",),
        "window_start": NOW - timedelta(hours=2),
        "window_end": NOW - timedelta(hours=1),
        "evaluated_at": NOW,
        "content_sha256": SHA_A,
    }
    values.update(overrides)
    return AgentPerformance(**values)  # type: ignore[arg-type]


def strategy_performance(**overrides: object) -> StrategyPerformance:
    values: dict[str, object] = {
        "performance_id": uuid4(),
        "strategy": artifact("strategy"),
        "scope": scope(),
        "sample_size": 20,
        "metrics": (metric("expectancy"),),
        "recent_metrics": (metric("recent-expectancy"),),
        "long_term_metrics": (metric("long-term-expectancy"),),
        "decay_state": StrategyDecayState.HEALTHY,
        "drift_ref": ref("C-055"),
        "validation_refs": (ref("C-028"),),
        "evidence": (evidence(),),
        "uncertainty": Decimal("0.10"),
        "limitations": ("Synthetic test data only",),
        "window_start": NOW - timedelta(hours=2),
        "window_end": NOW - timedelta(hours=1),
        "evaluated_at": NOW,
        "content_sha256": SHA_A,
    }
    values.update(overrides)
    return StrategyPerformance(**values)  # type: ignore[arg-type]


def awareness(**overrides: object) -> SystemAwarenessSnapshot:
    values: dict[str, object] = {
        "snapshot_id": uuid4(),
        "status": AwarenessStatus.READY,
        "data_health_refs": (ref("C-003"),),
        "market_regime_refs": (ref("C-005"),),
        "agent_performance_refs": (ref("C-052"),),
        "strategy_performance_refs": (ref("C-053"),),
        "validation_refs": (ref("C-028"),),
        "drift_refs": (ref("C-055"),),
        "portfolio_risk_refs": (ref("C-033"), ref("C-035")),
        "execution_health_refs": (ref("C-095"), ref("C-096")),
        "learning_state": LearningPipelineState.GOVERNANCE_PENDING,
        "safety_ref": ref("C-058"),
        "readiness_ref": ref("C-059"),
        "unknowns": (),
        "limitations": (),
        "as_of": NOW - timedelta(seconds=2),
        "created_at": NOW - timedelta(seconds=1),
        "valid_until": NOW + timedelta(minutes=5),
        "content_sha256": SHA_A,
    }
    values.update(overrides)
    return SystemAwarenessSnapshot(**values)  # type: ignore[arg-type]


def drift(**overrides: object) -> DriftAssessment:
    values: dict[str, object] = {
        "assessment_id": uuid4(),
        "dimension": DriftDimension.MODEL,
        "status": DriftStatus.NONE,
        "subject": artifact("model"),
        "baseline_start": NOW - timedelta(days=4),
        "baseline_end": NOW - timedelta(days=3),
        "current_start": NOW - timedelta(days=2),
        "current_end": NOW - timedelta(days=1),
        "method_version": version("drift-method"),
        "metrics": (metric("population-stability-index"),),
        "evidence": (evidence(),),
        "uncertainty": Decimal("0.10"),
        "limitations": (),
        "assessed_at": NOW,
        "content_sha256": SHA_A,
    }
    values.update(overrides)
    return DriftAssessment(**values)  # type: ignore[arg-type]


def knowledge(**overrides: object) -> KnowledgeArtifact:
    values: dict[str, object] = {
        "knowledge_id": uuid4(),
        "status": KnowledgeStatus.VALIDATED,
        "title": "Synthetic validated finding",
        "statement": "A bounded finding for test purposes",
        "scope": scope(),
        "provenance_refs": (ref("C-047"), ref("C-050")),
        "validation_refs": (ref("C-050"),),
        "evidence": (evidence(),),
        "sample_size": 20,
        "uncertainty": Decimal("0.10"),
        "limitations": ("Synthetic test data only",),
        "created_at": NOW - timedelta(minutes=1),
        "validated_at": NOW,
        "retired_at": None,
        "content_sha256": SHA_A,
    }
    values.update(overrides)
    return KnowledgeArtifact(**values)  # type: ignore[arg-type]


def governance(**overrides: object) -> GovernanceDecision:
    values: dict[str, object] = {
        "decision_id": uuid4(),
        "decision": GovernanceDecisionType.APPROVE_FOR_SHADOW,
        "artifact": artifact("strategy", ArtifactLifecycle.VALIDATED),
        "from_lifecycle": ArtifactLifecycle.VALIDATED,
        "to_lifecycle": ArtifactLifecycle.APPROVED_FOR_SHADOW,
        "proposal_ref": ref("C-051"),
        "evidence_refs": (ref("C-050"), ref("C-051")),
        "actor": GovernanceActorReference(
            actor_id="human-governor",
            authority="strategy-governance",
            authentication_evidence=evidence("AUTHENTICATION"),
        ),
        "conditions": ("Shadow evaluation only",),
        "audit_ref": ref("C-060"),
        "rollback_target": None,
        "rationale": "Bounded approval for shadow evaluation",
        "decided_at": NOW,
        "effective_at": NOW + timedelta(seconds=1),
        "content_sha256": SHA_A,
    }
    values.update(overrides)
    return GovernanceDecision(**values)  # type: ignore[arg-type]


def counterfactual(**overrides: object) -> CounterfactualAnalysis:
    values: dict[str, object] = {
        "analysis_id": uuid4(),
        "source_experience_ref": ref("C-045"),
        "scenario": "Alternative stop distance",
        "assumptions": ("Market path is held constant",),
        "simulation_method": version("counterfactual-simulator"),
        "metrics": (metric("hypothetical-pnl"),),
        "evidence": (evidence(),),
        "uncertainty": Decimal("0.30"),
        "limitations": ("This is not a factual outcome",),
        "evaluated_at": NOW,
        "content_sha256": SHA_A,
    }
    values.update(overrides)
    return CounterfactualAnalysis(**values)  # type: ignore[arg-type]


def champion_challenger(**overrides: object) -> ChampionChallengerRecord:
    values: dict[str, object] = {
        "record_id": uuid4(),
        "champion": artifact("strategy", ArtifactLifecycle.ACTIVE, SHA_A),
        "challenger": artifact("strategy", ArtifactLifecycle.CANDIDATE, SHA_B),
        "mode": EvaluationMode.SHADOW,
        "method_version": version("comparison-method"),
        "dataset": artifact("dataset", sha=SHA_C),
        "scope": scope(),
        "metrics": (metric(),),
        "outcome": ComparisonOutcome.CHALLENGER_BETTER,
        "experiment_result_ref": ref("C-050"),
        "governance_refs": (ref("C-057"),),
        "evidence": (evidence(),),
        "uncertainty": Decimal("0.10"),
        "limitations": ("Shadow evaluation only",),
        "challenger_has_live_effect": False,
        "evaluated_at": NOW,
        "content_sha256": SHA_A,
    }
    values.update(overrides)
    return ChampionChallengerRecord(**values)  # type: ignore[arg-type]


def canonical_instances() -> tuple[object, ...]:
    return (
        experience(),
        observation(),
        insight(),
        hypothesis(),
        experiment(),
        experiment_result(),
        strategy_proposal(),
        agent_performance(),
        strategy_performance(),
        awareness(),
        drift(),
        knowledge(),
        governance(),
        counterfactual(),
        champion_challenger(),
    )


def test_all_canonical_contracts_are_exported_frozen_and_identified() -> None:
    expected = tuple(f"C-{number:03d}" for number in (*range(45, 58), 90, 100))
    instances = canonical_instances()
    assert tuple(item.contract_id for item in instances) == expected
    for item in instances:
        assert item.schema_version == "1"
        assert getattr(learning_package, type(item).__name__) is type(item)
        assert "__dict__" not in dir(item)
        with pytest.raises(FrozenInstanceError):
            item.contract_id = "C-999"  # type: ignore[misc]


def test_registry_aliases_reuse_canonical_contracts() -> None:
    assert ExperienceRecord is Experience
    assert CalibrationRecord is CalibrationResult
    assert "CalibrationResult" not in learning_package.__all__


@pytest.mark.parametrize(
    ("status", "changes"),
    [
        (
            ExperienceStatus.NO_TRADE,
            {
                "decision_refs": (ref("C-026"),),
                "approval_ref": None,
                "execution_refs": (),
                "factual_outcome_ref": None,
            },
        ),
        (
            ExperienceStatus.REJECTED,
            {"execution_refs": (), "factual_outcome_ref": None},
        ),
        (
            ExperienceStatus.FAILED,
            {
                "approval_ref": None,
                "execution_refs": (),
                "factual_outcome_ref": None,
            },
        ),
        (
            ExperienceStatus.INCOMPLETE,
            {
                "approval_ref": None,
                "execution_refs": (),
                "factual_outcome_ref": None,
            },
        ),
    ],
)
def test_non_executed_experience_paths_are_first_class(
    status: ExperienceStatus, changes: dict[str, object]
) -> None:
    assert experience(status=status, **changes).status is status


@pytest.mark.parametrize(
    "changes",
    [
        {"approval_ref": None},
        {"execution_refs": ()},
        {"factual_outcome_ref": None},
        {"execution_refs": (ref("C-039"),)},
    ],
)
def test_executed_experience_requires_complete_factual_provenance(
    changes: dict[str, object],
) -> None:
    with pytest.raises(LearningContractError):
        experience(**changes)


def test_no_trade_and_rejected_paths_cannot_claim_execution() -> None:
    with pytest.raises(LearningContractError):
        experience(status=ExperienceStatus.NO_TRADE)
    with pytest.raises(LearningContractError):
        experience(
            status=ExperienceStatus.REJECTED,
            execution_refs=(ref("C-043"),),
            factual_outcome_ref=ref("C-044"),
        )


def test_complete_learning_chain_uses_exact_canonical_references() -> None:
    chain = canonical_instances()[:7]
    expected_inputs = (
        "C-045",
        "C-046",
        "C-047",
        "C-048",
        "C-049",
        "C-050",
    )
    actual_inputs = (
        chain[1].experience_refs[0].contract_id,
        chain[2].observation_refs[0].contract_id,
        chain[3].insight_refs[0].contract_id,
        chain[4].hypothesis_ref.contract_id,
        chain[5].experiment_ref.contract_id,
        chain[6].result_refs[0].contract_id,
    )
    assert actual_inputs == expected_inputs


def test_counterfactual_is_permanently_hypothetical_and_not_factual() -> None:
    item = counterfactual()
    assert item.classification is CounterfactualClassification.HYPOTHETICAL
    assert "factual_outcome_ref" not in {field.name for field in fields(item)}
    with pytest.raises(TypeError):
        CounterfactualAnalysis(
            **{
                **{
                    field.name: getattr(item, field.name)
                    for field in fields(item)
                    if field.init
                },
                "classification": CounterfactualClassification.HYPOTHETICAL,
            }
        )


def test_learning_and_performance_contracts_have_no_authority_fields() -> None:
    forbidden = {
        "approval_decision",
        "execution_intent",
        "order",
        "risk_authority",
        "production_mutation",
        "auto_promote",
    }
    for item in canonical_instances()[1:13]:
        assert forbidden.isdisjoint(field.name for field in fields(item))


def test_proposal_cannot_self_promote_candidate() -> None:
    with pytest.raises(LearningContractError, match="learning proposal"):
        strategy_proposal(
            proposed_artifact=artifact(
                "strategy", ArtifactLifecycle.APPROVED_FOR_PRODUCTION, SHA_B
            )
        )


@pytest.mark.parametrize(
    ("decision", "start", "target"),
    [
        (
            GovernanceDecisionType.APPROVE_FOR_SHADOW,
            ArtifactLifecycle.VALIDATED,
            ArtifactLifecycle.APPROVED_FOR_SHADOW,
        ),
        (
            GovernanceDecisionType.APPROVE_FOR_PAPER,
            ArtifactLifecycle.APPROVED_FOR_SHADOW,
            ArtifactLifecycle.APPROVED_FOR_PAPER,
        ),
        (
            GovernanceDecisionType.APPROVE_FOR_PRODUCTION,
            ArtifactLifecycle.APPROVED_FOR_PAPER,
            ArtifactLifecycle.APPROVED_FOR_PRODUCTION,
        ),
        (
            GovernanceDecisionType.ACTIVATE,
            ArtifactLifecycle.APPROVED_FOR_PRODUCTION,
            ArtifactLifecycle.ACTIVE,
        ),
        (
            GovernanceDecisionType.RETIRE,
            ArtifactLifecycle.ACTIVE,
            ArtifactLifecycle.RETIRED,
        ),
    ],
)
def test_governance_accepts_only_canonical_promotion_transitions(
    decision: GovernanceDecisionType,
    start: ArtifactLifecycle,
    target: ArtifactLifecycle,
) -> None:
    item = governance(
        decision=decision,
        artifact=artifact("strategy", start),
        from_lifecycle=start,
        to_lifecycle=target,
    )
    assert item.to_lifecycle is target


def test_governance_rejects_skipped_promotion_and_requires_rollback_target() -> None:
    with pytest.raises(LearningContractError, match="canonical transition"):
        governance(to_lifecycle=ArtifactLifecycle.APPROVED_FOR_PRODUCTION)
    with pytest.raises(LearningContractError, match="rollback target"):
        governance(
            decision=GovernanceDecisionType.ROLLBACK,
            artifact=artifact("strategy", ArtifactLifecycle.ACTIVE),
            from_lifecycle=ArtifactLifecycle.ACTIVE,
            to_lifecycle=ArtifactLifecycle.ROLLED_BACK,
        )


def test_governance_eligibility_has_no_trade_authority() -> None:
    names = {field.name for field in fields(GovernanceDecision)}
    assert {"approval_request", "approval_decision", "execution_intent"}.isdisjoint(
        names
    )


def test_challenger_cannot_have_live_effect_or_live_mode() -> None:
    assert set(EvaluationMode) == {
        EvaluationMode.OFFLINE,
        EvaluationMode.BACKTEST,
        EvaluationMode.PAPER,
        EvaluationMode.SHADOW,
    }
    with pytest.raises(LearningContractError, match="live execution"):
        champion_challenger(challenger_has_live_effect=True)


def test_ready_awareness_fails_closed_on_unknowns() -> None:
    with pytest.raises(LearningContractError, match="READY"):
        awareness(unknowns=("exchange health unavailable",))
    blocked = awareness(
        status=AwarenessStatus.UNKNOWN,
        unknowns=("exchange health unavailable",),
    )
    assert blocked.status is AwarenessStatus.UNKNOWN


def test_unknown_drift_requires_explicit_limitations() -> None:
    with pytest.raises(LearningContractError, match="limitations"):
        drift(status=DriftStatus.UNKNOWN)
    assert (
        drift(
            status=DriftStatus.UNKNOWN,
            limitations=("insufficient current samples",),
        ).status
        is DriftStatus.UNKNOWN
    )


def test_knowledge_lifecycle_requires_validation_and_retirement_evidence() -> None:
    with pytest.raises(LearningContractError, match="validation evidence"):
        knowledge(validation_refs=(), validated_at=None)
    with pytest.raises(LearningContractError, match="retired_at"):
        knowledge(status=KnowledgeStatus.RETIRED, validated_at=None)
    retired = knowledge(
        status=KnowledgeStatus.RETIRED,
        validated_at=None,
        retired_at=NOW,
    )
    assert retired.status is KnowledgeStatus.RETIRED


@pytest.mark.parametrize("bad_value", [1.0, True, Decimal("NaN"), Decimal("Infinity")])
def test_metric_rejects_non_decimal_or_non_finite_values(bad_value: object) -> None:
    with pytest.raises(LearningContractError, match="finite Decimal"):
        metric(value=bad_value)


def test_metric_rejects_invalid_samples_and_intervals() -> None:
    with pytest.raises(LearningContractError, match="positive integer"):
        metric(sample_size=0)
    with pytest.raises(LearningContractError, match="inside its interval"):
        metric(interval_lower=Decimal("0.80"), interval_upper=Decimal("0.90"))
    with pytest.raises(LearningContractError, match="supplied together"):
        metric(interval_upper=None)


def test_contracts_reject_naive_or_misordered_timestamps() -> None:
    with pytest.raises(LearningContractError, match="timezone-aware"):
        experience(recorded_at=datetime(2026, 9, 26, 12, 0))
    with pytest.raises(LearningContractError, match="must not be after"):
        experience(
            occurred_at=NOW,
            recorded_at=NOW - timedelta(seconds=1),
        )
    with pytest.raises(LearningContractError, match="positive duration"):
        agent_performance(window_start=NOW, window_end=NOW)


def test_contracts_reject_duplicate_references_and_invalid_hashes() -> None:
    duplicate = ref("C-045")
    with pytest.raises(LearningContractError, match="duplicates"):
        observation(experience_refs=(duplicate, duplicate))
    with pytest.raises(LearningContractError, match="SHA-256"):
        experience(content_sha256="not-a-digest")


def test_contracts_reject_wrong_reference_types_and_blank_claims() -> None:
    with pytest.raises(LearningContractError, match="C-045"):
        observation(experience_refs=(ref("C-044"),))
    with pytest.raises(LearningContractError, match="must not be blank"):
        insight(statement=" ")


def test_performance_sample_sizes_are_consistent() -> None:
    with pytest.raises(LearningContractError, match="sample size"):
        agent_performance(sample_size=5)
    with pytest.raises(LearningContractError, match="sample size"):
        strategy_performance(sample_size=5)


def test_experiment_requires_approval_and_distinct_versions() -> None:
    with pytest.raises(LearningContractError, match="research approval"):
        experiment(research_approval=None)
    same = artifact("strategy", sha=SHA_A)
    with pytest.raises(LearningContractError, match="distinct versions"):
        experiment(baseline=same, candidate=same)


def test_no_contract_exposes_secret_or_credential_payload_fields() -> None:
    forbidden_fragments = ("password", "private_key", "api_key", "token", "secret")
    for item in canonical_instances():
        for item_field in fields(item):
            assert not any(
                fragment in item_field.name.lower() for fragment in forbidden_fragments
            )


def test_timezone_values_are_normalized_to_utc() -> None:
    offset = timezone(timedelta(hours=5, minutes=30))
    item = experience(
        occurred_at=datetime(2026, 9, 26, 17, 29, tzinfo=offset),
        recorded_at=datetime(2026, 9, 26, 17, 30, tzinfo=offset),
    )
    assert item.recorded_at.tzinfo is UTC
    assert item.recorded_at.hour == 12


def test_dataclass_replace_revalidates_invariants() -> None:
    with pytest.raises(LearningContractError):
        replace(
            strategy_proposal(),
            proposed_artifact=artifact("strategy", ArtifactLifecycle.ACTIVE, SHA_B),
        )
