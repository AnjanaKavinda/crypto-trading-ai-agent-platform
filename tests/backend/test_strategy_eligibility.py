from __future__ import annotations

from dataclasses import replace
from decimal import Decimal
from uuid import uuid4

import pytest
from test_spot_debate import NOW, _compose, _envelope
from test_strategy_condition_evaluator import _setup
from trading_platform_api.analysis.contracts import VersionReference
from trading_platform_api.analysis.spot_meta_analysis import (
    FindingReadiness,
    SpotMetaFinding,
)
from trading_platform_api.analysis.versioned_contracts import AnalysisRecordReference
from trading_platform_api.analysis.versioned_contracts_v4 import (
    AnalysisSnapshotReferenceV4,
)
from trading_platform_api.config import DeploymentEnvironment, OperatingMode
from trading_platform_api.orchestration.spot_analysis_fanout import (
    SpotAnalysisFanoutResult,
    SpotAnalysisTaskOutcome,
    SpotAnalysisTaskStatus,
)
from trading_platform_api.strategy import (
    ArtifactVersionLifecycle,
    ConditionOperator,
    ConditionResultCode,
    ConditionTruth,
    EligibilityState,
    StrategyAvailability,
    StrategyLifecycle,
    build_spot_condition_context,
    evaluate_strategy_conditions,
    evaluate_strategy_eligibility,
    strategy_version_content_sha256,
)


def _case():
    envelope = _envelope()
    debate = _compose(envelope)
    strategy, _ = _setup()
    version = replace(
        strategy.version,
        supported_assets=(debate.market_context.asset,),
        supported_instruments=(debate.market_context.instrument_id,),
        supported_timeframes=(debate.market_context.adversarial.timeframe,),
        preferred_regimes=("trend",),
        acceptable_regimes=("transition",),
        incompatible_regimes=(),
        environments=(DeploymentEnvironment.TEST,),
        operating_modes=(OperatingMode.RESEARCH,),
        content_sha256="0" * 64,
    )
    version = replace(version, content_sha256=strategy_version_content_sha256(version))
    strategy = replace(strategy, version=version)
    component = next(
        item
        for item in debate.market_context.confluence.components
        if item.domain == "spot-momentum"
    )
    finding = SpotMetaFinding(
        component.component_id,
        component.domain,
        component.direction,
        component.relation,
        component.evidence_strength,
        FindingReadiness.READY,
        component.evidence_ids,
        component.input_binding_ids,
        VersionReference("spot-rsi-momentum-finding", "1"),
        result_value=Decimal("55"),
        result_unit="percent",
        provenance=(
            VersionReference("rsi", "rsi-wilder-sma-seed-v1"),
            VersionReference("indicator-metadata:rsi", "1"),
        ),
    )
    fanout = SpotAnalysisFanoutResult(
        envelope.correlation_id,
        (
            SpotAnalysisTaskOutcome(
                envelope.correlation_id,
                uuid4(),
                component.domain,
                SpotAnalysisTaskStatus.COMPLETE,
                finding,
                None,
            ),
        ),
    )
    condition_context = build_spot_condition_context(
        strategy=strategy, debate=debate, fanout=fanout, now=NOW
    )
    condition_evaluation = evaluate_strategy_conditions(strategy, condition_context)
    assert condition_evaluation.truth is ConditionTruth.PASS
    return envelope, debate, strategy, condition_context, condition_evaluation


def _evaluate(case, **overrides):
    envelope, debate, strategy, condition_context, condition_evaluation = case
    return evaluate_strategy_eligibility(
        requested_strategy_version_id=overrides.get(
            "requested_strategy_version_id", strategy.version.strategy_version_id
        ),
        strategy=overrides.get("strategy", strategy),
        condition_context=overrides.get("condition_context", condition_context),
        condition_evaluation=overrides.get(
            "condition_evaluation", condition_evaluation
        ),
        market_context=overrides.get("market_context", debate.market_context),
        manifest=overrides.get("manifest", envelope.manifest),
        resolved_bindings=overrides.get("resolved_bindings", envelope.resolved),
        environment=overrides.get("environment", DeploymentEnvironment.TEST),
        mode=overrides.get("mode", OperatingMode.RESEARCH),
        now=overrides.get("now", NOW),
    )


def test_exact_c003_c007_c006_c009_chain_produces_c022_deterministically() -> None:
    case = _case()
    first, second = _evaluate(case), _evaluate(case)
    assert first == second
    assert first.state is EligibilityState.ELIGIBLE
    assert first.eligibility is not None
    binding = case[0].resolved[0].binding
    assert first.eligibility.data_quality_report_id == uuid_from_ref(
        binding.data_quality_report
    )
    assert first.eligibility.strategy_version_id == case[2].version.strategy_version_id
    assert first.eligibility.market_context_id == case[1].market_context.context_id


def uuid_from_ref(reference: AnalysisRecordReference):
    from uuid import UUID

    return UUID(reference.record_id)


def test_missing_or_ambiguous_authoritative_c003_binding_has_no_c022() -> None:
    case = _case()
    missing = _evaluate(case, resolved_bindings=())
    ambiguous = _evaluate(case, resolved_bindings=case[0].resolved * 2)
    assert missing.state is EligibilityState.INSUFFICIENT_DATA
    assert missing.eligibility is None
    assert ambiguous.state is EligibilityState.INSUFFICIENT_DATA
    assert ambiguous.eligibility is None


@pytest.mark.parametrize(
    "mutation", ["wrong_report", "other_snapshot", "stale_binding"]
)
def test_invalid_c003_resolution_fails_closed_without_c022(mutation: str) -> None:
    case = _case()
    resolved = case[0].resolved[0]
    if mutation == "wrong_report":
        bad_report = replace(resolved.report, report_id=uuid4())
        resolved = replace(resolved, report=bad_report)
    elif mutation == "other_snapshot":
        bad_report = replace(resolved.report, snapshot_id=uuid4())
        resolved = replace(resolved, report=bad_report)
    else:
        resolved = replace(resolved, dependency_expires_at=NOW)
    result = _evaluate(case, resolved_bindings=(resolved,))
    assert result.state is EligibilityState.INSUFFICIENT_DATA
    assert result.eligibility is None


def test_c007_and_c009_provenance_mismatches_fail_closed() -> None:
    case = _case()
    other_reference = AnalysisSnapshotReferenceV4(uuid4(), "4", "c" * 64)
    adversarial = replace(
        case[1].market_context.adversarial, analysis_snapshot=other_reference
    )
    changed_context = replace(
        case[1].market_context,
        analysis_snapshot=other_reference,
        adversarial=adversarial,
    )
    assert _evaluate(case, market_context=changed_context).eligibility is None

    wrong_dq = AnalysisRecordReference("C-003", str(uuid4()), "2", "2", "b" * 64)
    changed_confluence = replace(
        case[1].market_context.confluence, data_quality_reports=(wrong_dq,)
    )
    changed_context = replace(case[1].market_context, confluence=changed_confluence)
    result = _evaluate(case, market_context=changed_context)
    assert result.state is EligibilityState.INSUFFICIENT_DATA
    assert result.eligibility is None


def test_lifecycle_profile_mode_and_condition_results_are_enforced() -> None:
    case = _case()
    suspended = replace(case[2], availability=StrategyAvailability.SUSPENDED)
    context = replace(case[3], strategy=suspended)
    condition = evaluate_strategy_conditions(suspended, context)
    result = _evaluate(
        case,
        strategy=suspended,
        condition_context=context,
        condition_evaluation=condition,
    )
    assert result.state is EligibilityState.NOT_ELIGIBLE

    retired = replace(case[2], c021_lifecycle=StrategyLifecycle.RETIRED)
    context = replace(case[3], strategy=retired)
    condition = evaluate_strategy_conditions(retired, context)
    assert (
        _evaluate(
            case,
            strategy=retired,
            condition_context=context,
            condition_evaluation=condition,
        ).state
        is EligibilityState.NOT_ELIGIBLE
    )

    rejected = replace(case[2], artifact_lifecycle=ArtifactVersionLifecycle.REJECTED)
    context = replace(case[3], strategy=rejected)
    condition = evaluate_strategy_conditions(rejected, context)
    assert (
        _evaluate(
            case,
            strategy=rejected,
            condition_context=context,
            condition_evaluation=condition,
        ).state
        is EligibilityState.NOT_ELIGIBLE
    )

    artifact_retired = replace(
        case[2], artifact_lifecycle=ArtifactVersionLifecycle.RETIRED
    )
    context = replace(case[3], strategy=artifact_retired)
    condition = evaluate_strategy_conditions(artifact_retired, context)
    assert (
        _evaluate(
            case,
            strategy=artifact_retired,
            condition_context=context,
            condition_evaluation=condition,
        ).state
        is EligibilityState.NOT_ELIGIBLE
    )

    deprecated = replace(case[2], c021_lifecycle=StrategyLifecycle.RETIRED)
    context = replace(case[3], strategy=deprecated)
    condition = evaluate_strategy_conditions(deprecated, context)
    assert (
        _evaluate(
            case,
            strategy=deprecated,
            condition_context=context,
            condition_evaluation=condition,
        ).state
        is EligibilityState.NOT_ELIGIBLE
    )

    unknown = replace(case[4], truth=ConditionTruth.UNKNOWN)
    result = _evaluate(case, condition_evaluation=unknown)
    assert result.state is EligibilityState.INSUFFICIENT_DATA
    unsupported = replace(
        case[4],
        reason_codes=(*case[4].reason_codes, ConditionResultCode.UNSUPPORTED_OPERATOR),
    )
    assert (
        _evaluate(case, condition_evaluation=unsupported).state
        is EligibilityState.INSUFFICIENT_DATA
    )
    assert (
        _evaluate(case, mode=OperatingMode.PAPER).state is EligibilityState.NOT_ELIGIBLE
    )


def test_exact_support_mismatches_and_context_expiry_fail_closed() -> None:
    case = _case()
    version = replace(
        case[2].version, supported_assets=("ETH",), content_sha256="0" * 64
    )
    version = replace(version, content_sha256=strategy_version_content_sha256(version))
    strategy = replace(case[2], version=version)
    context = replace(case[3], strategy=strategy)
    conditions = evaluate_strategy_conditions(strategy, context)
    result = _evaluate(
        case,
        strategy=strategy,
        condition_context=context,
        condition_evaluation=conditions,
    )
    assert result.state is EligibilityState.NOT_ELIGIBLE
    assert "UNSUPPORTED_ASSET" in result.reason_codes
    assert (
        _evaluate(case, now=case[0].manifest.expires_at).state
        is EligibilityState.INSUFFICIENT_DATA
    )


def test_instrument_timeframe_and_unsupported_regime_fail_closed() -> None:
    case = _case()
    for changes, expected, state in (
        (
            {"supported_instruments": ("ETH-USDT-SPOT",)},
            "UNSUPPORTED_INSTRUMENT",
            EligibilityState.NOT_ELIGIBLE,
        ),
        (
            {"supported_timeframes": ("1h",)},
            "UNSUPPORTED_TIMEFRAME",
            EligibilityState.NOT_ELIGIBLE,
        ),
        (
            {"incompatible_regimes": ("illiquid",)},
            "UNSUPPORTED_REGIME_REQUIREMENT",
            EligibilityState.INSUFFICIENT_DATA,
        ),
    ):
        version = replace(case[2].version, **changes, content_sha256="0" * 64)
        version = replace(
            version, content_sha256=strategy_version_content_sha256(version)
        )
        strategy = replace(case[2], version=version)
        context = replace(case[3], strategy=strategy)
        conditions = evaluate_strategy_conditions(strategy, context)
        result = _evaluate(
            case,
            strategy=strategy,
            condition_context=context,
            condition_evaluation=conditions,
        )
        assert result.state is state
        assert expected in result.reason_codes


def test_percentile_condition_remains_unknown_and_cannot_pass_eligibility() -> None:
    case = _case()
    condition = replace(
        case[2].version.conditions[0], operator=ConditionOperator.PERCENTILE_ABOVE
    )
    version = replace(case[2].version, conditions=(condition,), content_sha256="0" * 64)
    version = replace(version, content_sha256=strategy_version_content_sha256(version))
    strategy = replace(case[2], version=version)
    context = replace(case[3], strategy=strategy)
    condition_result = evaluate_strategy_conditions(strategy, context)
    assert condition_result.truth is ConditionTruth.UNKNOWN
    result = _evaluate(
        case,
        strategy=strategy,
        condition_context=context,
        condition_evaluation=condition_result,
    )
    assert result.state is EligibilityState.INSUFFICIENT_DATA


def test_unknown_version_and_malformed_condition_bindings_fail_closed() -> None:
    case = _case()
    other = _case()[2]
    result = _evaluate(case, strategy=other)
    assert result.state is EligibilityState.INSUFFICIENT_DATA
    malformed = replace(case[4], strategy_version_id=uuid4())
    assert (
        _evaluate(case, condition_evaluation=malformed).state
        is EligibilityState.INSUFFICIENT_DATA
    )
    detached = replace(case[3], correlation_id=uuid4())
    assert (
        _evaluate(case, condition_context=detached).state
        is EligibilityState.INSUFFICIENT_DATA
    )
