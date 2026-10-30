from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from test_spot_debate import NOW as SPOT_NOW
from test_spot_debate import _compose, _envelope
from trading_platform_api.analysis.contracts import VersionReference
from trading_platform_api.analysis.spot_meta_analysis import (
    FindingReadiness,
    SpotMetaFinding,
)
from trading_platform_api.config import DeploymentEnvironment, OperatingMode
from trading_platform_api.orchestration.spot_analysis_fanout import (
    SpotAnalysisFanoutResult,
    SpotAnalysisTaskOutcome,
    SpotAnalysisTaskStatus,
)
from trading_platform_api.strategy import (
    ArtifactVersionLifecycle,
    ConditionGroup,
    ConditionGroupOperator,
    ConditionOperator,
    ConditionResultCode,
    ConditionTruth,
    FeatureAvailability,
    ResolvedFeature,
    ResolvedStrategyVersion,
    SpotConditionContext,
    Strategy,
    StrategyAvailability,
    StrategyCondition,
    StrategyLifecycle,
    StrategyParameter,
    StrategyVersion,
    build_spot_condition_context,
    evaluate_strategy_conditions,
    strategy_version_content_sha256,
)
from trading_platform_api.strategy import (
    VersionReference as StrategyVersionReference,
)

NOW = datetime(2026, 10, 30, 12, tzinfo=UTC)
EXPIRY = NOW + timedelta(minutes=5)
PROVENANCE = (VersionReference("C-006", "5"), VersionReference("C-007", "4"))


def _condition(
    path: str = "market.asset",
    operator: ConditionOperator = ConditionOperator.EQUALS,
    values: tuple[str, ...] = ("BTC",),
    *,
    definition_version: str = "1",
) -> StrategyCondition:
    return StrategyCondition(uuid4(), path, operator, values, definition_version)


def _feature(
    path: str,
    value: str | Decimal | bool | None,
    availability: FeatureAvailability = FeatureAvailability.PRESENT,
) -> ResolvedFeature:
    return ResolvedFeature(
        path,
        availability,
        value,
        "C-006",
        "5",
        PROVENANCE,
        (uuid4(),),
    )


def _setup(
    conditions: tuple[StrategyCondition, ...] | None = None,
    *,
    operator: ConditionGroupOperator = ConditionGroupOperator.AND,
    features: tuple[ResolvedFeature, ...] | None = None,
    availability: StrategyAvailability = StrategyAvailability.EXPERIMENTAL,
    c021: StrategyLifecycle = StrategyLifecycle.RESEARCH,
    artifact: ArtifactVersionLifecycle = ArtifactVersionLifecycle.DRAFT,
) -> tuple[ResolvedStrategyVersion, SpotConditionContext]:
    selected = conditions or (_condition(),)
    version = StrategyVersion(
        strategy_version_id=uuid4(),
        strategy_id=uuid4(),
        semantic_version="1.0.0",
        lifecycle=c021,
        content_sha256="0" * 64,
        parent_version_id=None,
        parameters=(StrategyParameter("lookback", "20", "bars"),),
        conditions=selected,
        condition_groups=(
            ConditionGroup(
                uuid4(), operator, tuple(item.condition_id for item in selected)
            ),
        ),
        supported_assets=("BTC",),
        supported_instruments=("BTC-USDT-SPOT",),
        supported_timeframes=("1h",),
        preferred_regimes=("trend",),
        acceptable_regimes=("transition",),
        incompatible_regimes=("illiquid",),
        required_evidence_categories=("technical",),
        entry_concept="structure confirmation",
        invalidation_concept="structure invalidation",
        target_concepts=("analytical reference level",),
        environments=(DeploymentEnvironment.DEV,),
        operating_modes=(OperatingMode.RESEARCH,),
        provenance=(
            StrategyVersionReference("strategy-definition", uuid4(), "1", "a" * 64),
        ),
        created_at=NOW - timedelta(days=1),
    )
    version = replace(version, content_sha256=strategy_version_content_sha256(version))
    strategy = Strategy(
        strategy_id=version.strategy_id,
        name="test strategy",
        description="deterministic test fixture",
        strategy_type="trend",
        created_at=NOW - timedelta(days=1),
    )
    resolved = ResolvedStrategyVersion(strategy, version, availability, c021, artifact)
    if features is None:
        feature_values = (
            _feature("market.asset", "BTC"),
            _feature("spot.finding.spot-momentum.direction", "bullish-context"),
        )
    else:
        feature_values = features
        if not any(item.path.startswith("spot.finding.") for item in feature_values):
            feature_values += (
                _feature("spot.finding.spot-momentum.direction", "bullish-context"),
            )
    context = SpotConditionContext(
        resolved,
        uuid4(),
        uuid4(),
        uuid4(),
        NOW,
        EXPIRY,
        feature_values,
    )
    return resolved, context


def test_typed_equality_and_numeric_comparisons_are_exact_decimal() -> None:
    equality, equality_context = _setup()
    assert (
        evaluate_strategy_conditions(equality, equality_context).truth
        is ConditionTruth.PASS
    )

    condition = _condition(
        "spot.momentum.rsi14.value", ConditionOperator.GREATER_THAN_OR_EQUAL, ("50",)
    )
    numeric, numeric_context = _setup(
        (condition,),
        features=(_feature("spot.momentum.rsi14.value", Decimal("50.25")),),
    )
    result = evaluate_strategy_conditions(numeric, numeric_context)
    assert result.truth is ConditionTruth.PASS
    assert result.conditions[0].source_contract_id == "C-006"
    assert result.conditions[0].provenance == PROVENANCE
    assert (
        result.conditions[0].source_record_ids
        == numeric_context.features[0].source_record_ids
    )


@pytest.mark.parametrize(
    ("operator", "bounds", "expected"),
    [
        (ConditionOperator.IN_RANGE, ("50", "60"), ConditionTruth.PASS),
        (ConditionOperator.IN_RANGE, ("60", "50"), ConditionTruth.UNKNOWN),
        (ConditionOperator.GREATER_THAN, ("52.5",), ConditionTruth.FAIL),
        (ConditionOperator.LESS_THAN_OR_EQUAL, ("52.5",), ConditionTruth.PASS),
    ],
)
def test_numeric_operator_semantics(operator, bounds, expected) -> None:
    condition = _condition("spot.momentum.rsi14.value", operator, bounds)
    strategy, context = _setup(
        (condition,),
        features=(_feature("spot.momentum.rsi14.value", Decimal("52.5")),),
    )
    result = evaluate_strategy_conditions(strategy, context)
    assert result.truth is expected


def test_presence_absence_is_explicit_and_missing_is_unknown() -> None:
    present = _condition("market.asset", ConditionOperator.PRESENT, ())
    strategy, context = _setup((present,))
    assert evaluate_strategy_conditions(strategy, context).truth is ConditionTruth.PASS

    absent = _condition("spot.momentum.rsi14.value", ConditionOperator.ABSENT, ())
    strategy, context = _setup(
        (absent,),
        features=(
            _feature("spot.momentum.rsi14.value", None, FeatureAvailability.ABSENT),
        ),
    )
    assert evaluate_strategy_conditions(strategy, context).truth is ConditionTruth.PASS

    strategy, context = _setup((absent,), features=())
    result = evaluate_strategy_conditions(strategy, context)
    assert result.truth is ConditionTruth.UNKNOWN
    assert result.conditions[0].code is ConditionResultCode.UNAVAILABLE_FEATURE


def test_and_or_not_preserve_unknown_and_require_an_independent_pass() -> None:
    known = _condition("market.asset", ConditionOperator.EQUALS, ("BTC",))
    unknown = _condition("untrusted.field", ConditionOperator.PRESENT, ())
    strategy, context = _setup((known, unknown), operator=ConditionGroupOperator.AND)
    assert (
        evaluate_strategy_conditions(strategy, context).truth is ConditionTruth.UNKNOWN
    )

    strategy, context = _setup((known, unknown), operator=ConditionGroupOperator.OR)
    result = evaluate_strategy_conditions(strategy, context)
    assert result.truth is ConditionTruth.PASS
    assert result.groups[0].truth is ConditionTruth.PASS

    negated_unknown = replace(
        _condition("untrusted.field", ConditionOperator.PRESENT, ()),
    )
    strategy, context = _setup((negated_unknown,), operator=ConditionGroupOperator.NOT)
    assert (
        evaluate_strategy_conditions(strategy, context).truth is ConditionTruth.UNKNOWN
    )


def test_repeated_evaluation_is_deterministic_and_version_bound() -> None:
    strategy, context = _setup()
    first = evaluate_strategy_conditions(strategy, context)
    second = evaluate_strategy_conditions(strategy, context)
    assert first == second
    assert first.strategy_version_id == strategy.version.strategy_version_id
    assert first.content_sha256 == strategy.version.content_sha256
    assert first.dsl_version == "1"

    other, _ = _setup()
    mismatch = evaluate_strategy_conditions(other, context)
    assert mismatch.truth is ConditionTruth.UNKNOWN
    assert mismatch.reason_codes == (ConditionResultCode.VERSION_MISMATCH,)


def test_unreferenced_condition_is_not_silently_ignored() -> None:
    first, second = _condition(), _condition()
    resolved, context = _setup((first, second))
    version = replace(
        resolved.version,
        condition_groups=(
            ConditionGroup(uuid4(), ConditionGroupOperator.AND, (first.condition_id,)),
        ),
        content_sha256="0" * 64,
    )
    version = replace(version, content_sha256=strategy_version_content_sha256(version))
    resolved = replace(resolved, version=version)
    context = replace(context, strategy=resolved)
    result = evaluate_strategy_conditions(resolved, context)
    assert result.truth is ConditionTruth.UNKNOWN
    assert result.reason_codes == (ConditionResultCode.UNSUPPORTED_RUNTIME_CASE,)


def test_unknown_stale_malformed_and_versioned_input_fail_closed() -> None:
    unknown = _condition("llm.output.command", ConditionOperator.EQUALS, ("trade",))
    strategy, context = _setup((unknown,))
    result = evaluate_strategy_conditions(strategy, context)
    assert result.truth is ConditionTruth.UNKNOWN
    assert result.conditions[0].code is ConditionResultCode.UNKNOWN_FEATURE

    stale = evaluate_strategy_conditions(strategy, context, now=EXPIRY)
    assert stale.reason_codes == (ConditionResultCode.STALE_INPUT,)

    malformed = _condition(
        "spot.momentum.rsi14.value", ConditionOperator.EQUALS, ("NaN", "Infinity")
    )
    strategy, context = _setup(
        (malformed,),
        features=(_feature("spot.momentum.rsi14.value", Decimal("51")),),
    )
    result = evaluate_strategy_conditions(strategy, context)
    assert result.truth is ConditionTruth.UNKNOWN
    assert result.conditions[0].code is ConditionResultCode.INVALID_EXPECTED_VALUE

    malformed_numeric = _condition(
        "spot.momentum.rsi14.value", ConditionOperator.GREATER_THAN, ("NaN",)
    )
    strategy, context = _setup(
        (malformed_numeric,),
        features=(_feature("spot.momentum.rsi14.value", Decimal("51")),),
    )
    result = evaluate_strategy_conditions(strategy, context)
    assert result.conditions[0].code is ConditionResultCode.INVALID_EXPECTED_VALUE

    wrong_dsl = _condition(definition_version="2")
    strategy, context = _setup((wrong_dsl,))
    assert (
        evaluate_strategy_conditions(strategy, context).truth is ConditionTruth.UNKNOWN
    )


@pytest.mark.parametrize(
    "operator",
    [
        ConditionOperator.CROSSES_ABOVE,
        ConditionOperator.CROSSES_BELOW,
        ConditionOperator.PERCENTILE_ABOVE,
        ConditionOperator.PERCENTILE_BELOW,
    ],
)
def test_cross_and_percentile_operators_are_explicitly_unsupported(operator) -> None:
    condition = _condition("spot.momentum.rsi14.value", operator, ("50",))
    strategy, context = _setup(
        (condition,),
        features=(_feature("spot.momentum.rsi14.value", Decimal("51")),),
    )
    result = evaluate_strategy_conditions(strategy, context)
    assert result.truth is ConditionTruth.UNKNOWN
    assert result.conditions[0].code is ConditionResultCode.UNSUPPORTED_OPERATOR


def test_bounded_input_and_invalid_registry_states_fail_closed() -> None:
    condition = _condition()
    strategy, context = _setup((condition,))
    too_small_bound = evaluate_strategy_conditions(strategy, context, max_conditions=0)
    assert too_small_bound.truth is ConditionTruth.UNKNOWN
    assert too_small_bound.reason_codes == (ConditionResultCode.INPUT_LIMIT_EXCEEDED,)

    too_many_expected = _condition(
        "market.asset", ConditionOperator.EQUALS, ("BTC", "ETH", "SOL", "XRP", "DOGE")
    )
    strategy, context = _setup((too_many_expected,))
    excessive = evaluate_strategy_conditions(strategy, context)
    assert excessive.truth is ConditionTruth.UNKNOWN
    assert excessive.reason_codes == (ConditionResultCode.INPUT_LIMIT_EXCEEDED,)

    strategy, context = _setup()
    missing_required = replace(
        context,
        features=(_feature("market.asset", "BTC"),),
    )
    missing = evaluate_strategy_conditions(strategy, missing_required)
    assert missing.truth is ConditionTruth.UNKNOWN
    assert missing.reason_codes == (ConditionResultCode.REQUIRED_EVIDENCE_UNAVAILABLE,)

    for kwargs in (
        {"availability": StrategyAvailability.SUSPENDED},
        {"availability": StrategyAvailability.DEPRECATED},
        {"c021": StrategyLifecycle.REJECTED},
        {"c021": StrategyLifecycle.RETIRED},
        {"artifact": ArtifactVersionLifecycle.REJECTED},
        {"artifact": ArtifactVersionLifecycle.ROLLED_BACK},
    ):
        state, state_context = _setup(**kwargs)
        result = evaluate_strategy_conditions(state, state_context)
        assert result.truth is ConditionTruth.UNKNOWN
        assert result.reason_codes == (ConditionResultCode.INVALID_STRATEGY_STATE,)


def test_non_decimal_runtime_value_does_not_coerce_to_numeric() -> None:
    condition = _condition(
        "spot.momentum.rsi14.value", ConditionOperator.GREATER_THAN, ("50",)
    )
    strategy, context = _setup(
        (condition,),
        features=(_feature("spot.momentum.rsi14.value", "55"),),
    )
    result = evaluate_strategy_conditions(strategy, context)
    assert result.truth is ConditionTruth.UNKNOWN
    assert result.conditions[0].code is ConditionResultCode.UNSUPPORTED_RUNTIME_CASE


def test_resolver_consumes_exact_spot_debate_and_fanout_outputs() -> None:
    condition = _condition(
        "spot.momentum.rsi14.value",
        ConditionOperator.GREATER_THAN_OR_EQUAL,
        ("50",),
    )
    strategy, _ = _setup((condition,))
    version = replace(
        strategy.version,
        supported_timeframes=("1m",),
        content_sha256="0" * 64,
    )
    version = replace(version, content_sha256=strategy_version_content_sha256(version))
    strategy = replace(strategy, version=version)

    envelope = _envelope()
    debate = _compose(envelope)
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
    context = build_spot_condition_context(
        strategy=strategy,
        debate=debate,
        fanout=fanout,
        now=SPOT_NOW,
    )
    result = evaluate_strategy_conditions(strategy, context)
    assert result.truth is ConditionTruth.PASS
    assert result.truth is ConditionTruth.PASS
    assert result.conditions[0].source_contract_id == "SPOT_META_FINDING"
    assert result.conditions[0].source_schema_version == "1"
    assert component.component_id in result.conditions[0].source_record_ids
    assert VersionReference("C-007", "4") in result.conditions[0].provenance

    mismatched = replace(fanout, correlation_id=uuid4())
    with pytest.raises(ValueError, match="stale or mismatched"):
        build_spot_condition_context(
            strategy=strategy,
            debate=debate,
            fanout=mismatched,
            now=SPOT_NOW,
        )
