from __future__ import annotations

from dataclasses import replace
from uuid import uuid4

import pytest
from test_strategy_eligibility import _case, _evaluate
from trading_platform_api.analysis.contracts import (
    AnalyticalDirection,
    EvidenceRelation,
)
from trading_platform_api.analysis.contracts import (
    VersionReference as AnalysisVersionReference,
)
from trading_platform_api.analysis.versioned_contracts_v4 import (
    AnalysisSnapshotReferenceV4,
)
from trading_platform_api.strategy import (
    ConditionGroupOperator,
    ConditionOperator,
    ConditionTruth,
    EligibilityState,
    FeatureAvailability,
    ResolvedFeature,
    SetupDetectionOutcome,
    SetupState,
    SignalDirection,
    StrategyAvailability,
    StrategyCondition,
    evaluate_strategy_conditions,
    evaluate_strategy_setup,
    strategy_version_content_sha256,
)


def _positive_case():
    case = _case()
    envelope, debate, original_strategy, original_context, _ = case
    component = next(
        item
        for item in debate.market_context.confluence.components
        if item.direction in {AnalyticalDirection.BULLISH, AnalyticalDirection.BEARISH}
        and item.relation is EvidenceRelation.SUPPORTING
        and item.evidence_ids
    )
    path = f"spot.finding.{component.domain}.direction"
    condition = replace(
        original_strategy.version.conditions[0],
        feature_path=path,
        operator=ConditionOperator.EQUALS,
        expected_values=(component.direction.value,),
    )
    group = replace(
        original_strategy.version.condition_groups[0],
        condition_ids=(condition.condition_id,),
    )
    version = replace(
        original_strategy.version,
        conditions=(condition,),
        condition_groups=(group,),
        content_sha256="0" * 64,
    )
    version = replace(version, content_sha256=strategy_version_content_sha256(version))
    strategy = replace(original_strategy, version=version)
    feature = ResolvedFeature(
        path,
        FeatureAvailability.PRESENT,
        component.direction.value,
        "C-009",
        debate.market_context.confluence.schema_version,
        (
            AnalysisVersionReference(
                "C-009", debate.market_context.confluence.schema_version
            ),
            debate.market_context.confluence.method,
            AnalysisVersionReference(
                "C-007", debate.market_context.analysis_snapshot.schema_version
            ),
        ),
        (component.component_id, *component.evidence_ids),
    )
    features = tuple(item for item in original_context.features if item.path != path)
    context = replace(
        original_context, strategy=strategy, features=features + (feature,)
    )
    condition_result = evaluate_strategy_conditions(strategy, context)
    assert condition_result.truth is ConditionTruth.PASS
    eligibility_result = _evaluate(
        case,
        strategy=strategy,
        condition_context=context,
        condition_evaluation=condition_result,
    )
    assert eligibility_result.state is EligibilityState.ELIGIBLE
    return (
        case,
        envelope,
        debate,
        strategy,
        context,
        condition_result,
        eligibility_result,
    )


def _detect(case, **overrides):
    _, envelope, debate, strategy, context, condition, eligibility = case
    return evaluate_strategy_setup(
        requested_strategy_version_id=overrides.get(
            "requested_strategy_version_id", strategy.version.strategy_version_id
        ),
        strategy=overrides.get("strategy", strategy),
        condition_context=overrides.get("condition_context", context),
        condition_evaluation=overrides.get("condition_evaluation", condition),
        eligibility_evaluation=overrides.get("eligibility_evaluation", eligibility),
        market_context=overrides.get("market_context", debate.market_context),
        manifest=overrides.get("manifest", envelope.manifest),
        resolved_bindings=overrides.get("resolved_bindings", envelope.resolved),
        now=overrides.get("now", envelope.manifest.created_at),
    )


def test_exact_spot_strategy_and_80_81_gates_produce_repeatable_c023() -> None:
    case = _positive_case()
    now = case[1].manifest.created_at
    first = _detect(case, now=now)
    second = _detect(case, now=now)
    assert first == second
    assert first.outcome is SetupDetectionOutcome.SETUP_DETECTED
    candidate = first.candidate
    assert candidate is not None
    assert candidate.contract_id == "C-023"
    assert candidate.strategy_id == case[3].strategy.strategy_id
    assert candidate.strategy_version_id == case[3].version.strategy_version_id
    assert candidate.eligibility_id == case[6].eligibility.eligibility_id
    assert candidate.eligibility_state is EligibilityState.ELIGIBLE
    assert candidate.market_context_id == case[2].market_context.context_id
    assert candidate.analysis_snapshot_id == case[1].manifest.snapshot_id
    assert (
        candidate.data_quality_report_id == case[6].eligibility.data_quality_report_id
    )
    assert candidate.setup_state is SetupState.SETUP_CONFIRMED
    assert candidate.direction in {SignalDirection.LONG, SignalDirection.SHORT}
    assert candidate.supporting_evidence_ids
    assert candidate.lifecycle.value == "CANDIDATE"
    assert candidate.analytical_confidence == 0
    assert candidate.evidence_strength == 0
    assert candidate.entry_concept.reference_values == ()
    assert candidate.invalidation_concept.reference_values == ()
    assert all(item.reference_values == () for item in candidate.target_concepts)


@pytest.mark.parametrize(
    ("truth", "outcome", "reason"),
    [
        (
            ConditionTruth.FAIL,
            SetupDetectionOutcome.NO_SETUP,
            "CONDITIONS_NOT_SATISFIED",
        ),
        (
            ConditionTruth.UNKNOWN,
            SetupDetectionOutcome.INSUFFICIENT_INPUT,
            "CONDITIONS_UNKNOWN",
        ),
    ],
)
def test_condition_fail_or_unknown_never_creates_candidate(truth, outcome, reason):
    case = _positive_case()
    changed = replace(case[5], truth=truth)
    result = _detect(
        case, condition_evaluation=changed, now=case[1].manifest.created_at
    )
    assert result.outcome is outcome
    assert result.reason_codes == (reason,)
    assert result.candidate is None


@pytest.mark.parametrize(
    "state", [EligibilityState.NOT_ELIGIBLE, EligibilityState.INSUFFICIENT_DATA]
)
def test_noneligible_or_insufficient_81_result_never_creates_candidate(state):
    case = _positive_case()
    changed = replace(case[6], state=state)
    result = _detect(
        case, eligibility_evaluation=changed, now=case[1].manifest.created_at
    )
    assert result.outcome is (
        SetupDetectionOutcome.NO_SETUP
        if state is EligibilityState.NOT_ELIGIBLE
        else SetupDetectionOutcome.INSUFFICIENT_INPUT
    )
    assert result.candidate is None


@pytest.mark.parametrize(
    ("mutation", "reason"),
    [
        ("unknown_version", "REQUIRED_INPUT_UNAVAILABLE"),
        ("version_mismatch", "STRATEGY_VERSION_MISMATCH"),
        ("condition_binding", "CONDITION_BINDING_MISMATCH"),
        ("correlation_binding", "CONDITION_BINDING_MISMATCH"),
        ("missing_c022", "ELIGIBILITY_RESULT_UNAVAILABLE"),
        ("expired_c022", "ELIGIBILITY_BINDING_MISMATCH"),
        ("context", "ELIGIBILITY_BINDING_MISMATCH"),
        ("snapshot", "ANALYSIS_SNAPSHOT_MISMATCH"),
        ("quality_id", "SPOT_PROVENANCE_MISMATCH"),
        ("evidence", "EVIDENCE_PROVENANCE_MISMATCH"),
        ("asset", "ELIGIBILITY_BINDING_MISMATCH"),
        ("instrument", "ELIGIBILITY_BINDING_MISMATCH"),
        ("timeframe", "ELIGIBILITY_BINDING_MISMATCH"),
        ("c009_quality", "C003_META_BINDING_MISMATCH"),
    ],
)
def test_malformed_or_stale_bindings_fail_closed(mutation, reason):
    case = _positive_case()
    now = case[1].manifest.created_at
    changes = {}
    if mutation == "unknown_version":
        changes["strategy"] = None
    elif mutation == "version_mismatch":
        changes["requested_strategy_version_id"] = uuid4()
    elif mutation == "condition_binding":
        changes["condition_evaluation"] = replace(case[5], context_id=uuid4())
    elif mutation == "correlation_binding":
        changes["condition_evaluation"] = replace(case[5], correlation_id=uuid4())
    elif mutation == "missing_c022":
        changes["eligibility_evaluation"] = replace(case[6], eligibility=None)
    elif mutation == "expired_c022":
        expired = replace(case[6].eligibility, expires_at=now)
        changes["eligibility_evaluation"] = replace(case[6], eligibility=expired)
    elif mutation == "context":
        changes["market_context"] = replace(
            case[2].market_context,
            context_id=uuid4(),
        )
    elif mutation == "snapshot":
        wrong_ref = AnalysisSnapshotReferenceV4(uuid4(), "4", "f" * 64)
        wrong_adversarial = replace(
            case[2].market_context.adversarial, analysis_snapshot=wrong_ref
        )
        changes["market_context"] = replace(
            case[2].market_context,
            analysis_snapshot=wrong_ref,
            adversarial=wrong_adversarial,
        )
    elif mutation == "quality_id":
        changed_c022 = replace(case[6].eligibility, data_quality_report_id=uuid4())
        changes["eligibility_evaluation"] = replace(case[6], eligibility=changed_c022)
    elif mutation in {"asset", "instrument", "timeframe"}:
        field_name = {
            "asset": "asset",
            "instrument": "instrument_id",
            "timeframe": "timeframe",
        }[mutation]
        changed_c022 = replace(
            case[6].eligibility,
            **{
                field_name: "OTHER"
                if mutation == "asset"
                else "OTHER-INSTRUMENT"
                if mutation == "instrument"
                else "5m"
            },
        )
        changes["eligibility_evaluation"] = replace(case[6], eligibility=changed_c022)
    elif mutation == "c009_quality":
        wrong_ref = replace(
            case[2].market_context.confluence.data_quality_reports[0],
            record_id=str(uuid4()),
        )
        changed_confluence = replace(
            case[2].market_context.confluence,
            data_quality_reports=(wrong_ref,),
        )
        changes["market_context"] = replace(
            case[2].market_context, confluence=changed_confluence
        )
    else:
        changed_adversarial = replace(
            case[2].market_context.adversarial,
            contradictory_evidence_ids=(),
        )
        changed_context = replace(
            case[2].market_context,
            evidence_ids=(uuid4(),),
            adversarial=changed_adversarial,
        )
        changes["market_context"] = changed_context
    result = _detect(case, now=now, **changes)
    assert result.outcome is SetupDetectionOutcome.INSUFFICIENT_INPUT
    assert reason in result.reason_codes
    assert result.candidate is None


def test_missing_or_ambiguous_direction_is_not_guessed() -> None:
    case = _positive_case()
    strategy, context = case[3], case[4]
    unsupported = replace(
        strategy.version.conditions[0],
        feature_path="market.regime.direction",
        expected_values=("bullish-context",),
    )
    version = replace(
        strategy.version,
        conditions=(unsupported,),
        condition_groups=(
            replace(
                strategy.version.condition_groups[0],
                condition_ids=(unsupported.condition_id,),
            ),
        ),
        content_sha256="0" * 64,
    )
    version = replace(version, content_sha256=strategy_version_content_sha256(version))
    changed_strategy = replace(strategy, version=version)
    changed_context = replace(context, strategy=changed_strategy)
    condition = evaluate_strategy_conditions(changed_strategy, changed_context)
    changed_eligibility = _evaluate(
        case[0],
        strategy=changed_strategy,
        condition_context=changed_context,
        condition_evaluation=condition,
    )
    original_case = (
        *case[:3],
        changed_strategy,
        changed_context,
        condition,
        changed_eligibility,
    )
    result = _detect(original_case, now=case[1].manifest.created_at)
    assert result.outcome is SetupDetectionOutcome.INSUFFICIENT_INPUT
    assert result.reason_codes == ("DIRECTION_NOT_ESTABLISHED",)
    assert result.candidate is None


def test_suspended_registry_version_cannot_reuse_old_eligible_c022() -> None:
    case = _positive_case()
    suspended = replace(case[3], availability=StrategyAvailability.SUSPENDED)
    changed_context = replace(case[4], strategy=suspended)
    changed_condition = evaluate_strategy_conditions(suspended, changed_context)
    changed_case = (
        *case[:3],
        suspended,
        changed_context,
        changed_condition,
        case[6],
    )
    result = _detect(changed_case, now=case[1].manifest.created_at)
    assert result.outcome is SetupDetectionOutcome.NO_SETUP
    assert result.reason_codes == ("STRATEGY_NOT_AVAILABLE_FOR_RESEARCH",)
    assert result.candidate is None


def test_expired_market_context_cannot_produce_candidate() -> None:
    case = _positive_case()
    result = _detect(
        case,
        now=case[2].market_context.expires_at,
    )
    assert result.outcome is SetupDetectionOutcome.INSUFFICIENT_INPUT
    assert result.candidate is None


def test_missing_entry_concept_in_malformed_registry_value_fails_closed() -> None:
    case = _positive_case()
    version = case[3].version
    object.__setattr__(version, "entry_concept", "")
    object.__setattr__(
        version, "content_sha256", strategy_version_content_sha256(version)
    )
    malformed_strategy = replace(case[3], version=version)
    malformed_context = replace(case[4], strategy=malformed_strategy)
    condition_result = evaluate_strategy_conditions(
        malformed_strategy, malformed_context
    )
    eligibility = _evaluate(
        case[0],
        strategy=malformed_strategy,
        condition_context=malformed_context,
        condition_evaluation=condition_result,
    )
    malformed_case = (
        *case[:3],
        malformed_strategy,
        malformed_context,
        condition_result,
        eligibility,
    )
    result = _detect(malformed_case, now=case[1].manifest.created_at)
    assert result.outcome is SetupDetectionOutcome.INSUFFICIENT_INPUT
    assert result.reason_codes == ("STRATEGY_CONCEPTS_UNAVAILABLE",)
    assert result.candidate is None


def test_opposing_passed_direction_conditions_are_ambiguous() -> None:
    case = _positive_case()
    original = case[3]
    components = {
        item.direction: item
        for item in case[2].market_context.confluence.components
        if item.direction in {AnalyticalDirection.BULLISH, AnalyticalDirection.BEARISH}
        and item.relation is EvidenceRelation.SUPPORTING
        and item.evidence_ids
    }
    ordered_components = tuple(
        sorted(components.items(), key=lambda pair: pair[0].value)
    )
    conditions = tuple(
        StrategyCondition(
            uuid4(),
            f"spot.finding.{component.domain}.direction",
            ConditionOperator.EQUALS,
            (direction.value,),
            "1",
        )
        for direction, component in ordered_components
    )
    assert len(conditions) == 2
    group = replace(
        original.version.condition_groups[0],
        operator=ConditionGroupOperator.OR,
        condition_ids=tuple(item.condition_id for item in conditions),
    )
    version = replace(
        original.version,
        conditions=conditions,
        condition_groups=(group,),
        content_sha256="0" * 64,
    )
    version = replace(version, content_sha256=strategy_version_content_sha256(version))
    strategy = replace(original, version=version)
    feature_by_path = {item.path: item for item in case[4].features}
    for condition, (_, component) in zip(conditions, ordered_components, strict=True):
        feature_by_path[condition.feature_path] = ResolvedFeature(
            condition.feature_path,
            FeatureAvailability.PRESENT,
            component.direction.value,
            "C-009",
            case[2].market_context.confluence.schema_version,
            (
                AnalysisVersionReference(
                    "C-009", case[2].market_context.confluence.schema_version
                ),
                case[2].market_context.confluence.method,
                AnalysisVersionReference(
                    "C-007", case[2].market_context.analysis_snapshot.schema_version
                ),
            ),
            (component.component_id, *component.evidence_ids),
        )
    context = replace(
        case[4], strategy=strategy, features=tuple(feature_by_path.values())
    )
    condition_result = evaluate_strategy_conditions(strategy, context)
    eligibility = _evaluate(
        case[0],
        strategy=strategy,
        condition_context=context,
        condition_evaluation=condition_result,
    )
    changed_case = (*case[:3], strategy, context, condition_result, eligibility)
    result = _detect(changed_case, now=case[1].manifest.created_at)
    assert condition_result.truth is ConditionTruth.PASS
    assert result.outcome is SetupDetectionOutcome.INSUFFICIENT_INPUT
    assert result.reason_codes == ("DIRECTION_AMBIGUOUS",)
    assert result.candidate is None


def test_missing_authoritative_spot_binding_fails_before_c023() -> None:
    case = _positive_case()
    result = _detect(case, resolved_bindings=(), now=case[1].manifest.created_at)
    assert result.outcome is SetupDetectionOutcome.INSUFFICIENT_INPUT
    assert result.reason_codes == ("SPOT_BINDING_UNAVAILABLE",)
    assert result.candidate is None
