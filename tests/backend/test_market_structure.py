from dataclasses import replace
from decimal import Decimal
from uuid import uuid4

import pytest
from test_moving_averages import evidence
from trading_platform_api.analysis import (
    BreakDirection,
    MarketStructureError,
    MarketStructurePolicy,
    MarketStructureScale,
    StructureDirection,
    StructureEventType,
    SupportResistancePolicy,
    SwingClassification,
    calculate_spot_market_structure,
    calculate_spot_price_action,
)
from trading_platform_api.market_data.contracts import DataQualityStatus

HIGHS = (
    "12",
    "15",
    "13",
    "17",
    "14",
    "16.5",
    "15",
    "15.5",
    "18",
    "16",
    "14",
    "17",
    "16",
    "19",
    "15",
    "20",
    "16",
    "15",
    "22",
    "23",
)
LOWS = (
    "9",
    "10",
    "8",
    "11",
    "10.5",
    "12",
    "9",
    "12",
    "10.5",
    "12",
    "10",
    "13",
    "11.5",
    "13",
    "12.5",
    "14",
    "13",
    "12",
    "10",
    "9",
)


def _policies() -> tuple[SupportResistancePolicy, SupportResistancePolicy]:
    return (
        SupportResistancePolicy(
            "internal-pivots",
            "1",
            1,
            1,
            Decimal("0.1"),
            "USDT",
            2,
            Decimal(0),
            1,
        ),
        SupportResistancePolicy(
            "external-pivots",
            "1",
            2,
            2,
            Decimal("0.1"),
            "USDT",
            2,
            Decimal(0),
            1,
        ),
    )


def _analyze(
    *,
    closes: tuple[str, ...] | None = None,
    highs: tuple[str, ...] = HIGHS,
    lows: tuple[str, ...] = LOWS,
    quality_status: DataQualityStatus = DataQualityStatus.VALID,
    break_count: int = 1,
):
    values = tuple(
        closes
        or tuple(
            str((Decimal(high) + Decimal(low)) / 2)
            for high, low in zip(HIGHS, LOWS, strict=True)
        )
    )
    snapshot, original, quality = evidence(values)
    observations = tuple(
        replace(
            candle,
            metrics=tuple(
                replace(
                    metric,
                    value={
                        "open": min(Decimal(high), max(Decimal(low), Decimal(close))),
                        "high": Decimal(high),
                        "low": Decimal(low),
                        "close": min(Decimal(high), max(Decimal(low), Decimal(close))),
                    }[metric.metric_name],
                )
                if metric.metric_name in {"open", "high", "low", "close"}
                else metric
                for metric in candle.metrics
            ),
        )
        for candle, close, high, low in zip(
            original, values, highs[: len(values)], lows[: len(values)], strict=True
        )
    )
    if quality_status is not DataQualityStatus.VALID:
        quality = replace(quality, status=quality_status)
    internal, external = _policies()
    internal_pa = calculate_spot_price_action(
        snapshot=snapshot,
        observations=observations,
        quality=quality,
        timeframe="1m",
        support_resistance_policy=internal,
    )
    external_pa = calculate_spot_price_action(
        snapshot=snapshot,
        observations=observations,
        quality=quality,
        timeframe="1m",
        support_resistance_policy=external,
    )
    result = calculate_spot_market_structure(
        snapshot=snapshot,
        observations=observations,
        quality=quality,
        timeframe="1m",
        internal_price_action=internal_pa,
        external_price_action=external_pa,
        internal_pivot_policy=internal,
        external_pivot_policy=external,
        break_policy=MarketStructurePolicy(
            "test-breaks", "2", Decimal("0.5"), break_count
        ),
    )
    return (
        snapshot,
        observations,
        quality,
        internal,
        external,
        internal_pa,
        external_pa,
        result,
    )


def test_hand_classifies_confirmed_swings_and_derives_bullish_states_on_both_scales():
    *_, result = _analyze()
    internal_highs = [
        swing
        for swing in result.swings
        if swing.scale is MarketStructureScale.INTERNAL
        and swing.pivot.kind.value == "HIGH"
    ]
    internal_lows = [
        swing
        for swing in result.swings
        if swing.scale is MarketStructureScale.INTERNAL
        and swing.pivot.kind.value == "LOW"
    ]
    assert internal_highs[0].classification is None
    assert internal_highs[-1].classification is SwingClassification.HIGHER_HIGH
    assert internal_lows[-1].classification is SwingClassification.HIGHER_LOW
    assert tuple(state.direction for state in result.states) == (
        StructureDirection.BULLISH,
        StructureDirection.BULLISH,
    )


def test_equal_pivots_are_reported_without_directional_classification():
    highs = list(HIGHS)
    highs[5] = "17"
    highs[6] = "14"
    highs[7] = "14"
    _, _, _, _, _, _, _, result = _analyze(highs=tuple(highs))
    internal_highs = [
        swing
        for swing in result.swings
        if swing.scale is MarketStructureScale.INTERNAL
        and swing.pivot.kind.value == "HIGH"
    ]
    assert any(
        swing.classification is SwingClassification.EQUAL_HIGH
        for swing in internal_highs
    )


def test_bearish_and_mixed_states_are_reported_on_the_assigned_scales():
    bearish_highs = tuple(str(30 - Decimal(low)) for low in LOWS)
    bearish_lows = tuple(str(30 - Decimal(high)) for high in HIGHS)
    bearish_closes = tuple(
        str((Decimal(high) + Decimal(low)) / 2)
        for high, low in zip(bearish_highs, bearish_lows, strict=True)
    )
    *_, bearish = _analyze(
        highs=bearish_highs, lows=bearish_lows, closes=bearish_closes
    )
    assert tuple(state.direction for state in bearish.states) == (
        StructureDirection.BEARISH,
        StructureDirection.BEARISH,
    )

    mixed_highs = list(HIGHS)
    mixed_highs[13] = "18"
    mixed_highs[15] = "17"
    *_, mixed = _analyze(highs=tuple(mixed_highs))
    assert tuple(state.direction for state in mixed.states) == (
        StructureDirection.MIXED,
        StructureDirection.MIXED,
    )
    assert all(
        "conflict" in state.reason or "equal" in state.reason for state in mixed.states
    )


def test_missing_pivot_history_is_explicitly_mixed_on_both_scales():
    highs = ("11",) * len(HIGHS)
    lows = ("9",) * len(HIGHS)
    *_, result = _analyze(highs=highs, lows=lows)
    assert tuple(state.direction for state in result.states) == (
        StructureDirection.MIXED,
        StructureDirection.MIXED,
    )
    assert all(
        state.reason == "insufficient-confirmed-high-low-history"
        for state in result.states
    )
    assert not result.events


def test_bos_requires_strict_close_buffer_and_consecutive_closes():
    closes = [
        str((Decimal(high) + Decimal(low)) / 2)
        for high, low in zip(HIGHS, LOWS, strict=True)
    ]
    closes[18] = "20.5"
    closes[19] = "21"
    *_, result = _analyze(closes=tuple(closes), break_count=2)
    assert not result.events

    closes[18] = "20.6"
    closes[19] = "20.7"
    *_, result = _analyze(closes=tuple(closes), break_count=2)
    internal_bos = [
        event
        for event in result.events
        if event.scale is MarketStructureScale.INTERNAL
        and event.event_type is StructureEventType.BREAK_OF_STRUCTURE
    ]
    assert internal_bos
    assert internal_bos[-1].direction is BreakDirection.UP
    assert internal_bos[-1].reference_price == Decimal("20")
    assert internal_bos[-1].confirming_close == Decimal("20.7")
    assert internal_bos[-1].confirmation_time == result.as_of
    assert (
        internal_bos[-1].confirmation_time
        > internal_bos[-1].reference_pivot.confirmation_time
    )
    assert internal_bos[-1].reference_pivot.source_market_data_id
    assert internal_bos[-1].detection_rule
    assert internal_bos[-1].invalidation_condition


def test_counter_breaks_are_internal_choch_and_external_mss():
    closes = [
        str((Decimal(high) + Decimal(low)) / 2)
        for high, low in zip(HIGHS, LOWS, strict=True)
    ]
    closes[18] = "9"
    closes[19] = "8.5"
    lows = list(LOWS)
    lows[18] = "8"
    lows[19] = "7"
    *_, result = _analyze(closes=tuple(closes), lows=tuple(lows))
    events = {(event.scale, event.event_type) for event in result.events}
    assert (
        MarketStructureScale.INTERNAL,
        StructureEventType.CHANGE_OF_CHARACTER,
    ) in events
    assert (
        MarketStructureScale.EXTERNAL,
        StructureEventType.MARKET_STRUCTURE_SHIFT,
    ) in events
    assert all(event.direction is BreakDirection.DOWN for event in result.events)


def test_wick_only_crossing_does_not_break_and_evidence_links_c008_c012():
    highs = list(HIGHS)
    closes = [
        str((Decimal(high) + Decimal(low)) / 2)
        for high, low in zip(HIGHS, LOWS, strict=True)
    ]
    closes[18] = "20"
    highs[18] = "21"
    *_, result = _analyze(closes=tuple(closes), highs=tuple(highs))
    assert not result.events
    assert result.evidence.contract_id == "C-008"
    assert result.assessment.contract_id == "C-012"
    assert result.assessment.evidence_ids == (result.evidence.evidence_id,)
    assert result.assessment.observations
    assert all(
        item.observation_type == "market-structure"
        for item in result.assessment.observations
    )
    assert result.evidence.quality_status is DataQualityStatus.VALID
    assert result.evidence.expires_at == result.evidence_expires_at


def test_mixed_state_breaks_remain_unclassified():
    mixed_highs = list(HIGHS)
    mixed_highs[13] = "18"
    mixed_highs[15] = "17"
    closes = [
        str((Decimal(high) + Decimal(low)) / 2)
        for high, low in zip(mixed_highs, LOWS, strict=True)
    ]
    closes[18] = "22"
    *_, result = _analyze(highs=tuple(mixed_highs), closes=tuple(closes))
    assert result.events
    assert all(
        event.event_type is StructureEventType.UNCLASSIFIED_BREAK
        for event in result.events
    )


def test_lineage_quality_policy_and_exact_version_fail_closed():
    snapshot, candles, quality, internal, external, int_pa, ext_pa, _ = _analyze()
    args = dict(
        snapshot=snapshot,
        observations=candles,
        quality=quality,
        timeframe="1m",
        internal_price_action=int_pa,
        external_price_action=ext_pa,
        internal_pivot_policy=internal,
        external_pivot_policy=external,
        break_policy=MarketStructurePolicy("test", "1", Decimal("0.1"), 1),
    )
    with pytest.raises(MarketStructureError, match="lineage"):
        calculate_spot_market_structure(
            **{
                **args,
                "internal_price_action": replace(int_pa, snapshot_id=uuid4()),
            }
        )
    with pytest.raises(MarketStructureError, match="External windows"):
        calculate_spot_market_structure(
            **{**args, "external_pivot_policy": replace(internal, policy_id="external")}
        )
    with pytest.raises(MarketStructureError, match="designated pivot policy"):
        calculate_spot_market_structure(
            **{
                **args,
                "external_pivot_policy": replace(external, policy_id="other"),
            }
        )
    with pytest.raises(MarketStructureError, match="Unregistered"):
        calculate_spot_market_structure(
            **{
                **args,
                "internal_price_action": replace(
                    int_pa, method_version="unregistered-pivot-method"
                ),
            }
        )
    with pytest.raises(MarketStructureError, match="positive"):
        MarketStructurePolicy("invalid", "1", Decimal(0), 1)
    with pytest.raises(MarketStructureError, match="validation"):
        calculate_spot_market_structure(
            **{
                **args,
                "quality": replace(quality, status=DataQualityStatus.DEGRADED),
            }
        )
    with pytest.raises(MarketStructureError, match="exact"):
        calculate_spot_market_structure(**args, metadata_version="2")
    gap = list(candles)
    gap[4] = replace(
        gap[4], event_time=gap[4].event_time - gap[4].event_time.resolution
    )
    with pytest.raises(MarketStructureError, match="validation"):
        calculate_spot_market_structure(**{**args, "observations": tuple(gap)})
    with pytest.raises(MarketStructureError, match="validation"):
        calculate_spot_market_structure(
            **{**args, "observations": tuple(reversed(candles))}
        )
    with pytest.raises(MarketStructureError, match="validation"):
        calculate_spot_market_structure(**{**args, "timeframe": "5m"})
    oversized = candles * 501
    with pytest.raises(MarketStructureError, match="bounded"):
        calculate_spot_market_structure(**{**args, "observations": oversized})


def test_calculation_is_repeatable_and_source_bound():
    snapshot, candles, quality, internal, external, int_pa, ext_pa, first = _analyze()
    second = calculate_spot_market_structure(
        snapshot=snapshot,
        observations=candles,
        quality=quality,
        timeframe="1m",
        internal_price_action=int_pa,
        external_price_action=ext_pa,
        internal_pivot_policy=internal,
        external_pivot_policy=external,
        break_policy=first.break_policy,
    )
    assert first == second
    assert first.evidence.source_record_ids == first.source_record_ids
    assert first.method_version == "spot-market-structure-v1"
