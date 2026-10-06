import json
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from test_market_structure import HIGHS, LOWS, _analyze
from trading_platform_api.analysis import (
    FibonacciLevel,
    MarketStructureScale,
    PivotKind,
    SPOT_FIBONACCI_METHOD_VERSION,
    SpotFibonacciError,
    SpotFibonacciPolicy,
    calculate_spot_fibonacci,
)
from trading_platform_api.analysis.fibonacci import _fixed_anchor_groups
from trading_platform_api.market_data.contracts import DataQualityStatus

RETRACEMENTS = tuple(
    Decimal(value) for value in ("0.236", "0.382", "0.500", "0.618", "0.786", "1.000")
)
EXTENSIONS = tuple(Decimal(value) for value in ("1.272", "1.618", "2.618"))


def _anchor_pair(structure, scale, origin_kind, endpoint_kind):
    swings = [
        swing
        for swing in structure.swings
        if swing.scale is scale
    ]
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
    assert {(level.category, level.ratio): level.price for level in bullish.levels} == expected
    assert bullish.direction == "bullish"
    assert bullish.assessment.analytical_confidence == Decimal(0)

    bearish_highs = tuple(str(100 - Decimal(low)) for low in LOWS)
    bearish_lows = tuple(str(100 - Decimal(high)) for high in HIGHS)
    bearish_closes = tuple(
        str((Decimal(high) + Decimal(low)) / 2)
        for high, low in zip(bearish_highs, bearish_lows, strict=True)
    )
    snapshot, candles, quality, _, _, _, _, structure = _analyze(
        highs=bearish_highs,
        lows=bearish_lows,
        closes=bearish_closes,
    )
    origin, endpoint = _anchor_pair(
        structure,
        MarketStructureScale.INTERNAL,
        PivotKind.HIGH,
        PivotKind.LOW,
    )
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
    assert {(level.category, level.ratio): level.price for level in bearish.levels} == expected
    assert bearish.direction == "bearish"


def test_fixed_anchor_confluence_is_sorted_and_does_not_chain():
    levels = tuple(
        FibonacciLevel(uuid4(), "retracement-level", Decimal(index), Decimal(price), (), uuid4())
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
    assert len(
        _fixed_anchor_groups(
            (replace(levels[0], price=Decimal("1")), replace(levels[1], price=Decimal("2"))),
            Decimal("1"),
        )
    ) == 1


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
        assert payload["market_structure_evidence_id"] == str(inputs[3].evidence.evidence_id)
        assert payload["uncertainty"]
        assert evidence.source_record_ids == first.source_record_ids
        assert evidence.quality_status is DataQualityStatus.VALID
        assert evidence.expires_at == first.evidence_expires_at


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
