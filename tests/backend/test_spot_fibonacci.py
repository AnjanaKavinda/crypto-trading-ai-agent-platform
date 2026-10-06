import json
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from test_market_structure import HIGHS, LOWS, _analyze
from trading_platform_api.analysis import (
    SPOT_FIBONACCI_METHOD_VERSION,
    FibonacciLevel,
    MarketStructureScale,
    PivotKind,
    SpotFibonacciError,
    SpotFibonacciPolicy,
    calculate_spot_fibonacci,
)
from trading_platform_api.analysis import fibonacci as fibonacci_module
from trading_platform_api.analysis.fibonacci import (
    _fixed_anchor_groups,
    _immutable_json,
)
from trading_platform_api.contracts.serialization import canonical_json_dumps
from trading_platform_api.market_data.contracts import DataQualityStatus

RETRACEMENTS = tuple(
    Decimal(value) for value in ("0.236", "0.382", "0.500", "0.618", "0.786", "1.000")
)
EXTENSIONS = tuple(Decimal(value) for value in ("1.272", "1.618", "2.618"))


def _anchor_pair(structure, scale, origin_kind, endpoint_kind):
    swings = [swing for swing in structure.swings if swing.scale is scale]
    for origin in swings:
        for endpoint in swings:
            if (
                origin.pivot.kind is origin_kind
                and endpoint.pivot.kind is endpoint_kind
                and origin.pivot.source_time < endpoint.pivot.source_time
                and origin.pivot.confirmation_time < endpoint.pivot.confirmation_time
            ):
                return origin.pivot, endpoint.pivot
    raise AssertionError("Fixture lacks the required alternating pivot pair.")


def _policy(origin, endpoint, **changes):
    fields = {
        "policy_id": "fibonacci-tests",
        "version": "v1",
        "scale": MarketStructureScale.INTERNAL,
        "origin_pivot_id": origin.pivot_id,
        "endpoint_pivot_id": endpoint.pivot_id,
        "retracement_ratios": RETRACEMENTS,
        "extension_ratios": EXTENSIONS,
        "confluence_tolerance": Decimal("0.01"),
        "invalidation_buffer": Decimal("0.1"),
        "invalidation_consecutive_close_count": 2,
        "maximum_output_records": 100,
    }
    fields.update(changes)
    return SpotFibonacciPolicy(**fields)


def _bullish():
    snapshot, candles, quality, _, _, _, _, structure = _analyze()
    origin, endpoint = _anchor_pair(
        structure,
        MarketStructureScale.INTERNAL,
        PivotKind.LOW,
        PivotKind.HIGH,
    )
    return snapshot, candles, quality, structure, origin, endpoint


def _bearish():
    highs = tuple(str(100 - Decimal(low)) for low in LOWS)
    lows = tuple(str(100 - Decimal(high)) for high in HIGHS)
    closes = tuple(
        str((Decimal(high) + Decimal(low)) / 2)
        for high, low in zip(highs, lows, strict=True)
    )
    snapshot, candles, quality, _, _, _, _, structure = _analyze(
        highs=highs,
        lows=lows,
        closes=closes,
    )
    origin, endpoint = _anchor_pair(
        structure,
        MarketStructureScale.INTERNAL,
        PivotKind.HIGH,
        PivotKind.LOW,
    )
    return snapshot, candles, quality, structure, origin, endpoint, highs, lows, closes


def _structure_with_swings(structure, swings):
    payload = _immutable_json(json.loads(structure.evidence.value))
    payload["swings"] = swings
    return replace(
        structure,
        swings=swings,
        evidence=replace(
            structure.evidence,
            value=canonical_json_dumps(payload),
        ),
    )


def _calculate(inputs=None, **changes):
    snapshot, candles, quality, structure, origin, endpoint = inputs or _bullish()
    return calculate_spot_fibonacci(
        snapshot=snapshot,
        observations=candles,
        quality=quality,
        market_structure=structure,
        timeframe="1m",
        policy=_policy(origin, endpoint, **changes),
    )


def test_bullish_and_bearish_reference_levels_use_exact_decimal_ratios():
    bullish_inputs = _bullish()
    bullish = _calculate(bullish_inputs)
    origin, endpoint = bullish_inputs[-2:]
    move = abs(endpoint.price - origin.price)
    expected = {
        ("retracement-level", ratio): endpoint.price - move * ratio
        for ratio in RETRACEMENTS
    } | {
        ("extension-level", ratio): endpoint.price + move * ratio
        for ratio in EXTENSIONS
    }
    assert bullish.method_version == SPOT_FIBONACCI_METHOD_VERSION
    assert {
        (level.category, level.ratio): level.price for level in bullish.levels
    } == expected
    assert bullish.direction == "bullish"
    assert bullish.assessment.analytical_confidence == Decimal(0)

    snapshot, candles, quality, structure, origin, endpoint, *_ = _bearish()
    bearish = calculate_spot_fibonacci(
        snapshot=snapshot,
        observations=candles,
        quality=quality,
        market_structure=structure,
        timeframe="1m",
        policy=_policy(origin, endpoint),
    )
    move = abs(endpoint.price - origin.price)
    expected = {
        ("retracement-level", ratio): endpoint.price + move * ratio
        for ratio in RETRACEMENTS
    } | {
        ("extension-level", ratio): endpoint.price - move * ratio
        for ratio in EXTENSIONS
    }
    assert {
        (level.category, level.ratio): level.price for level in bearish.levels
    } == expected
    assert bearish.direction == "bearish"


def test_fixed_anchor_confluence_is_sorted_and_does_not_chain():
    levels = tuple(
        FibonacciLevel(
            uuid4(), "retracement-level", Decimal(index), Decimal(price), (), uuid4()
        )
        for index, price in enumerate(("1", "1.9", "2.8", "10"))
    )
    groups = _fixed_anchor_groups(levels, Decimal("1"))
    assert len(groups) == 1
    assert groups[0][4:] == (
        Decimal("1"),
        Decimal("1"),
        Decimal("1.9"),
    )
    assert groups[0][1] == (levels[0].level_id, levels[1].level_id)
    assert _fixed_anchor_groups((), Decimal("1")) == ()
    assert _fixed_anchor_groups((levels[0],), Decimal("1")) == ()
    assert (
        len(
            _fixed_anchor_groups(
                (
                    replace(levels[0], price=Decimal("1")),
                    replace(levels[1], price=Decimal("2")),
                ),
                Decimal("1"),
            )
        )
        == 1
    )


def test_analysis_evidence_lineage_expiry_invalidation_and_repeatability():
    inputs = _bullish()
    first = _calculate(inputs)
    second = _calculate(inputs)
    assert first == second
    assert first.source_record_ids == inputs[0].source_record_ids
    assert first.input_market_data_ids == inputs[0].market_data_ids
    assert first.assessment.contract_id == "C-068"
    assert first.assessment.observations
    assert {item.observation_type for item in first.assessment.observations} <= {
        "anchor",
        "retracement-level",
        "extension-level",
        "invalidation",
    }
    assert first.assessment.expires_at == first.as_of + timedelta(minutes=1)
    for evidence in first.evidence:
        payload = json.loads(evidence.value)
        assert payload["policy"]["origin_pivot_id"]
        assert payload["snapshot_id"] == str(first.snapshot_id)
        assert payload["quality_report_id"] == str(first.quality_report_id)
        assert payload["market_structure_evidence_id"] == str(
            inputs[3].evidence.evidence_id
        )
        assert payload["uncertainty"]
        assert evidence.source_record_ids == first.source_record_ids
        assert evidence.quality_status is DataQualityStatus.VALID
        assert evidence.expires_at == first.evidence_expires_at


def test_confluence_membership_is_linked_to_each_level_evidence():
    result = _calculate(
        confluence_tolerance=Decimal("100"),
    )
    assert len(result.confluence_groups) == 1
    group = result.confluence_groups[0]
    assert group.member_level_ids == tuple(
        level.level_id
        for level in sorted(
            result.levels, key=lambda item: (item.price, str(item.level_id))
        )
    )
    assert group.member_ratios == tuple(
        level.ratio
        for level in sorted(
            result.levels, key=lambda item: (item.price, str(item.level_id))
        )
    )
    assert group.lower_bound == min(group.member_prices)
    assert group.upper_bound == max(group.member_prices)
    assert group.upper_bound - group.fixed_anchor_price <= group.tolerance
    assert all(group.group_id in level.confluence_group_ids for level in result.levels)
    for level in result.levels:
        observation = next(
            item
            for item in result.assessment.observations
            if item.observation_type == level.category
            and json.loads(item.value)["level_id"] == str(level.level_id)
        )
        assert group.evidence_id in observation.evidence_ids
    with pytest.raises(SpotFibonacciError, match="output exceeds"):
        _calculate(maximum_output_records=1)


def test_invalidation_is_strict_consecutive_and_resets_on_equality():
    snapshot, candles, quality, structure, origin, endpoint = _bullish()
    endpoint_index = next(
        index
        for index, candle in enumerate(candles)
        if candle.market_data_id == endpoint.source_market_data_id
    )
    first_after_confirmation = endpoint_index + endpoint.right_window + 1
    closes = [
        str((Decimal(high) + Decimal(low)) / 2)
        for high, low in zip(HIGHS, LOWS, strict=True)
    ]
    lows = list(LOWS)
    threshold = origin.price - Decimal("0.1")
    for index in range(first_after_confirmation, first_after_confirmation + 3):
        lows[index] = str(threshold - Decimal("0.2"))
    closes[first_after_confirmation] = str(threshold)
    closes[first_after_confirmation + 1] = str(threshold - Decimal("0.1"))
    closes[first_after_confirmation + 2] = str(threshold - Decimal("0.1"))
    snapshot, candles, quality, _, _, _, _, structure = _analyze(
        lows=tuple(lows), closes=tuple(closes)
    )
    origin, endpoint = _anchor_pair(
        structure,
        MarketStructureScale.INTERNAL,
        PivotKind.LOW,
        PivotKind.HIGH,
    )
    result = calculate_spot_fibonacci(
        snapshot=snapshot,
        observations=candles,
        quality=quality,
        market_structure=structure,
        timeframe="1m",
        policy=_policy(origin, endpoint),
    )
    assert result.invalidation.invalidated
    assert (
        result.invalidation.confirming_market_data_id
        == candles[first_after_confirmation + 2].market_data_id
    )

    closes[first_after_confirmation + 1] = str(threshold + Decimal("0.1"))
    snapshot, candles, quality, _, _, _, _, structure = _analyze(
        lows=tuple(lows), closes=tuple(closes)
    )
    origin, endpoint = _anchor_pair(
        structure,
        MarketStructureScale.INTERNAL,
        PivotKind.LOW,
        PivotKind.HIGH,
    )
    result = calculate_spot_fibonacci(
        snapshot=snapshot,
        observations=candles,
        quality=quality,
        market_structure=structure,
        timeframe="1m",
        policy=_policy(origin, endpoint),
    )
    assert not result.invalidation.invalidated
    assert result.invalidation.observed_consecutive_closes == 0


def test_wick_only_breach_and_bearish_close_invalidation():
    snapshot, candles, quality, structure, origin, endpoint = _bullish()
    endpoint_index = next(
        index
        for index, candle in enumerate(candles)
        if candle.market_data_id == endpoint.source_market_data_id
    )
    wick_index = endpoint_index + endpoint.right_window + 1
    lows = list(LOWS)
    closes = [
        str((Decimal(high) + Decimal(low)) / 2)
        for high, low in zip(HIGHS, LOWS, strict=True)
    ]
    lows[wick_index] = str(origin.price - Decimal("1"))
    closes[wick_index] = str(origin.price)
    snapshot, candles, quality, _, _, _, _, structure = _analyze(
        lows=tuple(lows), closes=tuple(closes)
    )
    origin, endpoint = _anchor_pair(
        structure,
        MarketStructureScale.INTERNAL,
        PivotKind.LOW,
        PivotKind.HIGH,
    )
    result = calculate_spot_fibonacci(
        snapshot=snapshot,
        observations=candles,
        quality=quality,
        market_structure=structure,
        timeframe="1m",
        policy=_policy(
            origin,
            endpoint,
            invalidation_consecutive_close_count=1,
        ),
    )
    assert not result.invalidation.invalidated

    _, candles, _, structure, origin, endpoint, highs, lows, closes = _bearish()
    endpoint_index = next(
        index
        for index, candle in enumerate(candles)
        if candle.market_data_id == endpoint.source_market_data_id
    )
    first_after_confirmation = endpoint_index + endpoint.right_window + 1
    highs = list(highs)
    lows = list(lows)
    closes = list(closes)
    threshold = origin.price + Decimal("0.1")
    for index in range(first_after_confirmation, first_after_confirmation + 2):
        highs[index] = str(threshold + Decimal("0.2"))
        closes[index] = str(threshold + Decimal("0.1"))
    snapshot, candles, quality, _, _, _, _, structure = _analyze(
        highs=tuple(highs), lows=tuple(lows), closes=tuple(closes)
    )
    origin, endpoint = _anchor_pair(
        structure,
        MarketStructureScale.INTERNAL,
        PivotKind.HIGH,
        PivotKind.LOW,
    )
    result = calculate_spot_fibonacci(
        snapshot=snapshot,
        observations=candles,
        quality=quality,
        market_structure=structure,
        timeframe="1m",
        policy=_policy(origin, endpoint, invalidation_consecutive_close_count=2),
    )
    assert result.invalidation.invalidated


def test_fail_closed_on_invalid_quality_unknown_anchor_and_exact_version():
    snapshot, candles, quality, structure, origin, endpoint = _bullish()
    policy = _policy(origin, endpoint)
    args = dict(
        snapshot=snapshot,
        observations=candles,
        quality=quality,
        market_structure=structure,
        timeframe="1m",
        policy=policy,
    )
    with pytest.raises(SpotFibonacciError, match="shared analysis validation"):
        calculate_spot_fibonacci(
            **{**args, "quality": replace(quality, status=DataQualityStatus.DEGRADED)}
        )
    with pytest.raises(SpotFibonacciError, match="Unknown exact"):
        calculate_spot_fibonacci(**args, metadata_version="unknown")
    with pytest.raises(SpotFibonacciError, match="anchor ID"):
        calculate_spot_fibonacci(
            **{**args, "policy": replace(policy, origin_pivot_id=uuid4())}
        )
    with pytest.raises(SpotFibonacciError, match="ratios"):
        SpotFibonacciPolicy(
            **{
                **{
                    field: getattr(policy, field)
                    for field in policy.__dataclass_fields__
                },
                "retracement_ratios": (Decimal("0.75"),),
            }
        )
    with pytest.raises(SpotFibonacciError, match="after Fibonacci evidence expiry"):
        calculate_spot_fibonacci(
            **{
                **args,
                "quality": replace(
                    quality,
                    assessed_at=snapshot.as_of + timedelta(minutes=1),
                ),
            }
        )


@pytest.mark.parametrize(
    "status",
    (DataQualityStatus.STALE, DataQualityStatus.UNAVAILABLE),
)
def test_rejects_stale_or_unavailable_quality(status):
    snapshot, candles, quality, structure, origin, endpoint = _bullish()
    with pytest.raises(SpotFibonacciError, match="shared analysis validation"):
        calculate_spot_fibonacci(
            snapshot=snapshot,
            observations=candles,
            quality=replace(quality, status=status),
            market_structure=structure,
            timeframe="1m",
            policy=_policy(origin, endpoint),
        )


def test_rejects_future_provisional_and_unavailable_candles():
    snapshot, candles, quality, structure, origin, endpoint = _bullish()
    last = candles[-1]
    cases = (
        replace(
            last,
            event_time=snapshot.as_of + timedelta(minutes=1),
            provider_time=snapshot.as_of + timedelta(minutes=1),
            ingestion_time=snapshot.as_of + timedelta(minutes=1),
            availability_time=snapshot.as_of + timedelta(minutes=1),
        ),
        replace(
            last,
            event_time=snapshot.as_of,
            provider_time=snapshot.as_of,
        ),
        replace(
            last,
            availability_time=snapshot.as_of + timedelta(minutes=1),
        ),
    )
    for candle in cases:
        with pytest.raises(SpotFibonacciError, match="shared analysis validation"):
            calculate_spot_fibonacci(
                snapshot=snapshot,
                observations=(*candles[:-1], candle),
                quality=quality,
                market_structure=structure,
                timeframe="1m",
                policy=_policy(origin, endpoint),
            )


def test_rejects_reordered_duplicate_and_gapped_candles():
    snapshot, candles, quality, structure, origin, endpoint = _bullish()
    duplicate = (*candles[:-1], candles[-2])
    gap = (
        *candles[:5],
        replace(
            candles[5],
            event_time=candles[5].event_time + timedelta(minutes=1),
        ),
        *candles[6:],
    )
    with pytest.raises(
        fibonacci_module.VolatilityError,
        match="Candles must be ordered and contiguous",
    ):
        fibonacci_module._ohlc(
            snapshot=snapshot,
            observations=gap,
            quality=quality,
            timeframe="1m",
        )

    for observations in (tuple(reversed(candles)), duplicate, gap):
        with pytest.raises(SpotFibonacciError, match="shared analysis validation"):
            calculate_spot_fibonacci(
                snapshot=snapshot,
                observations=observations,
                quality=quality,
                market_structure=structure,
                timeframe="1m",
                policy=_policy(origin, endpoint),
            )


def test_rejects_snapshot_quality_and_pivot_identity_mismatches():
    snapshot, candles, quality, structure, origin, endpoint = _bullish()
    args = dict(
        snapshot=snapshot,
        observations=candles,
        quality=quality,
        market_structure=structure,
        timeframe="1m",
        policy=_policy(origin, endpoint),
    )
    with pytest.raises(SpotFibonacciError, match="shared analysis validation"):
        calculate_spot_fibonacci(
            **{**args, "snapshot": replace(snapshot, snapshot_id=uuid4())}
        )
    with pytest.raises(SpotFibonacciError, match="lineage"):
        calculate_spot_fibonacci(
            **{**args, "quality": replace(quality, report_id=uuid4())}
        )
    with pytest.raises(SpotFibonacciError, match="lineage"):
        calculate_spot_fibonacci(
            **{
                **args,
                "market_structure": replace(structure, snapshot_id=uuid4()),
            }
        )


def test_rejects_unsupported_timeframe_and_mismatched_price_unit():
    snapshot, candles, quality, structure, origin, endpoint = _bullish()
    args = dict(
        snapshot=snapshot,
        observations=candles,
        quality=quality,
        market_structure=structure,
        policy=_policy(origin, endpoint),
    )
    with pytest.raises(SpotFibonacciError, match="Unsupported Spot timeframe"):
        calculate_spot_fibonacci(**args, timeframe="2m")
    altered = replace(
        candles[0],
        metrics=tuple(
            replace(metric, unit="USD") if metric.metric_name == "close" else metric
            for metric in candles[0].metrics
        ),
    )
    with pytest.raises(SpotFibonacciError, match="shared analysis validation"):
        calculate_spot_fibonacci(
            **{**args, "observations": (altered, *candles[1:])},
            timeframe="1m",
        )


def test_cutoff_prefix_is_invariant_and_later_candle_or_pivot_is_rejected():
    snapshot, candles, quality, structure, origin, endpoint = _bullish()
    policy = _policy(origin, endpoint)
    args = dict(
        snapshot=snapshot,
        quality=quality,
        market_structure=structure,
        timeframe="1m",
        policy=policy,
    )
    before = calculate_spot_fibonacci(observations=candles, **args)
    future = replace(
        candles[-1],
        market_data_id=uuid4(),
        event_time=snapshot.as_of,
        provider_time=snapshot.as_of,
        ingestion_time=snapshot.as_of + timedelta(minutes=1),
        availability_time=snapshot.as_of + timedelta(minutes=1),
    )
    extended_history = (*candles, future)
    cutoff_prefix = tuple(
        candle
        for candle in extended_history
        if candle.event_time + timedelta(minutes=1) <= snapshot.as_of
    )
    assert cutoff_prefix == candles
    assert calculate_spot_fibonacci(observations=cutoff_prefix, **args) == before
    with pytest.raises(SpotFibonacciError, match="shared analysis validation"):
        calculate_spot_fibonacci(observations=extended_history, **args)

    swings = list(structure.swings)
    endpoint_index = next(
        index
        for index, swing in enumerate(swings)
        if swing.pivot.pivot_id == endpoint.pivot_id
    )
    swings[endpoint_index] = replace(
        swings[endpoint_index],
        pivot=replace(
            endpoint,
            confirmation_time=snapshot.as_of + timedelta(minutes=1),
        ),
    )
    with pytest.raises(SpotFibonacciError, match="unconfirmed"):
        calculate_spot_fibonacci(
            **{
                **args,
                "market_structure": _structure_with_swings(structure, tuple(swings)),
            },
            observations=candles,
        )


def test_rejects_fibonacci_evidence_exceeding_serialization_limit(monkeypatch):
    inputs = _bullish()
    validate_structure = fibonacci_module._validate_structure

    def validate_then_limit_evidence(**kwargs):
        pivots = validate_structure(**kwargs)
        monkeypatch.setattr(fibonacci_module, "MAX_DOCUMENT_BYTES", 1)
        return pivots

    monkeypatch.setattr(
        fibonacci_module, "_validate_structure", validate_then_limit_evidence
    )
    with pytest.raises(SpotFibonacciError, match="Fibonacci evidence exceeds"):
        _calculate(inputs)


def test_rejects_self_consistent_but_non_extreme_market_structure_pivot():
    snapshot, candles, quality, structure, origin, endpoint = _bullish()
    swing = structure.swings[0]
    source_index = 2
    confirmation_index = source_index + swing.pivot.right_window
    source = candles[source_index]
    confirmation = candles[confirmation_index]
    source_metrics = {metric.metric_name: metric for metric in source.metrics}
    forged_pivot = replace(
        swing.pivot,
        pivot_id=uuid4(),
        kind=PivotKind.HIGH,
        price=source_metrics["high"].value,
        source_market_data_id=source.market_data_id,
        source_time=source.event_time,
        confirmation_market_data_id=confirmation.market_data_id,
        confirmation_time=confirmation.event_time + timedelta(minutes=1),
        policy_id=structure.internal_pivot_policy.policy_id,
        policy_version=structure.internal_pivot_policy.version,
        left_window=structure.internal_pivot_policy.left_window,
        right_window=structure.internal_pivot_policy.right_window,
    )
    swings = list(structure.swings)
    swings[0] = replace(
        swing,
        scale=MarketStructureScale.INTERNAL,
        pivot=forged_pivot,
    )
    forged_swings = tuple(swings)
    forged_structure = _structure_with_swings(structure, forged_swings)
    with pytest.raises(SpotFibonacciError, match="not an exact local extreme"):
        calculate_spot_fibonacci(
            snapshot=snapshot,
            observations=candles,
            quality=quality,
            market_structure=forged_structure,
            timeframe="1m",
            policy=_policy(origin, endpoint),
        )


def test_rejects_malformed_market_structure_pivot_decimal():
    snapshot, candles, quality, structure, origin, endpoint = _bullish()
    swings = list(structure.swings)
    swings[0] = replace(
        swings[0],
        pivot=replace(swings[0].pivot, price="malformed"),
    )
    forged_structure = _structure_with_swings(structure, tuple(swings))
    with pytest.raises(SpotFibonacciError, match="pivot price"):
        calculate_spot_fibonacci(
            snapshot=snapshot,
            observations=candles,
            quality=quality,
            market_structure=forged_structure,
            timeframe="1m",
            policy=_policy(origin, endpoint),
        )


def test_rejects_pivot_kinds_that_contradict_the_signed_price_move():
    highs = ["220"] * len(HIGHS)
    lows = ["200"] * len(LOWS)
    for index, high, low in (
        (2, "150", "110"),
        (3, "130", "100"),
        (4, "140", "120"),
        (5, "120", "110"),
        (6, "100", "80"),
        (7, "85", "75"),
        (8, "90", "70"),
        (9, "85", "75"),
    ):
        highs[index] = high
        lows[index] = low
    closes = tuple(
        str((Decimal(high) + Decimal(low)) / 2)
        for high, low in zip(highs, lows, strict=True)
    )
    snapshot, candles, quality, _, _, _, _, structure = _analyze(
        highs=tuple(highs),
        lows=tuple(lows),
        closes=closes,
    )
    pivots = tuple(
        swing.pivot
        for swing in structure.swings
        if swing.scale is MarketStructureScale.INTERNAL
    )
    origin = next(
        pivot
        for pivot in pivots
        if pivot.kind is PivotKind.LOW and pivot.source_time == candles[3].event_time
    )
    endpoint = next(
        pivot
        for pivot in pivots
        if pivot.kind is PivotKind.HIGH and pivot.source_time == candles[8].event_time
    )
    with pytest.raises(SpotFibonacciError, match="upward price move"):
        calculate_spot_fibonacci(
            snapshot=snapshot,
            observations=candles,
            quality=quality,
            market_structure=structure,
            timeframe="1m",
            policy=_policy(origin, endpoint),
        )
