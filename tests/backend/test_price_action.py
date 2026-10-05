import json
from dataclasses import FrozenInstanceError, replace
from datetime import timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from test_moving_averages import START, STEP, evidence
from trading_platform_api.analysis import (
    PRICE_ACTION_METHOD_VERSION,
    SPOT_RESEARCH_INDICATORS,
    AssessmentStatus,
    CloseLocationReason,
    IndicatorCategory,
    IndicatorMetadataError,
    IndicatorPhase,
    PatternLabel,
    PatternPolicy,
    PivotKind,
    PriceActionError,
    RangeBaselinePolicy,
    RangeComparisonReason,
    RangeDirection,
    SupportResistancePolicy,
    ZoneStatus,
    calculate_spot_price_action,
)
from trading_platform_api.market_data.contracts import (
    DataQualityReport,
    DataQualityStatus,
    MarketData,
    MarketSnapshot,
)


def _bars(
    values: tuple[tuple[str, str, str, str], ...],
) -> tuple[MarketSnapshot, tuple[MarketData, ...], DataQualityReport]:
    snapshot, observations, quality = evidence(tuple("10" for _ in values))
    custom: list[MarketData] = []
    for candle, value in zip(observations, values, strict=True):
        prices = dict(
            zip(("open", "high", "low", "close"), map(Decimal, value), strict=True)
        )
        custom.append(
            replace(
                candle,
                metrics=tuple(
                    replace(metric, value=prices[metric.metric_name], unit="USDT")
                    if metric.metric_name in prices
                    else metric
                    for metric in candle.metrics
                ),
            )
        )
    return snapshot, tuple(custom), quality


def _pattern_policy(**changes: object) -> PatternPolicy:
    return replace(
        PatternPolicy(
            policy_id="test-patterns",
            version="1",
            engulfing_minimum_body_fraction=Decimal("0.25"),
            pin_bar_minimum_wick_to_body=Decimal(2),
            pin_bar_maximum_body_fraction=Decimal("0.25"),
            pin_bar_maximum_opposite_wick_fraction=Decimal("0.15"),
            hammer_minimum_lower_wick_to_body=Decimal(2),
            hammer_minimum_close_location=Decimal("0.65"),
            shooting_star_minimum_upper_wick_to_body=Decimal(2),
            shooting_star_maximum_close_location=Decimal("0.35"),
            doji_maximum_body_fraction=Decimal("0.05"),
            star_middle_maximum_body_to_first_body=Decimal("0.3"),
            star_minimum_first_body_penetration=Decimal("0.5"),
        ),
        **changes,
    )


def _zone_policy(**changes: object) -> SupportResistancePolicy:
    return replace(
        SupportResistancePolicy(
            policy_id="test-zones",
            version="1",
            left_window=1,
            right_window=1,
            price_tolerance=Decimal("1"),
            price_unit="USDT",
            minimum_repeated_interactions=2,
            close_break_buffer=Decimal("0.5"),
            break_close_count=2,
        ),
        **changes,
    )


def _calculate(
    snapshot: MarketSnapshot,
    observations: tuple[MarketData, ...],
    quality: DataQualityReport,
    **policies: object,
):
    timeframe = policies.pop("timeframe", "1m")
    return calculate_spot_price_action(
        snapshot=snapshot,
        observations=observations,
        quality=quality,
        timeframe=timeframe,  # type: ignore[arg-type]
        **policies,  # type: ignore[arg-type]
    )


def _labels(
    bars: tuple[tuple[str, str, str, str], ...],
    policy: PatternPolicy | None = None,
) -> set[PatternLabel]:
    snapshot, observations, quality = _bars(bars)
    result = _calculate(
        snapshot,
        observations,
        quality,
        pattern_policy=policy or _pattern_policy(),
    )
    return {pattern.label for candle in result.geometry for pattern in candle.patterns}


def test_exact_decimal_candle_geometry_and_caller_selected_range_baseline() -> None:
    snapshot, observations, quality = _bars(
        (
            ("10", "11", "9", "10.5"),
            ("10", "11", "9", "10.5"),
            ("10", "12.5", "9.5", "12"),
            ("10", "10.5", "9.5", "10"),
        )
    )
    baseline = RangeBaselinePolicy("prior-two", "v3", 2, Decimal("0.25"))

    result = _calculate(
        snapshot,
        observations,
        quality,
        range_baseline_policy=baseline,
    )
    first, expansion, contraction = (
        result.geometry[0],
        result.geometry[2],
        result.geometry[3],
    )
    assert (
        first.signed_body,
        first.absolute_body,
        first.range,
        first.upper_wick,
        first.lower_wick,
        first.close_location,
    ) == (
        Decimal("0.5"),
        Decimal("0.5"),
        Decimal(2),
        Decimal("0.5"),
        Decimal(1),
        Decimal("0.75"),
    )
    assert expansion.baseline_mean_range == Decimal(2)
    assert expansion.baseline_period == 2
    assert expansion.baseline_policy_version == "v3"
    assert expansion.baseline_method_version
    assert expansion.range_direction is RangeDirection.EXPANSION
    assert contraction.baseline_mean_range == Decimal("2.5")
    assert contraction.range_direction is RangeDirection.CONTRACTION
    assert result.geometry[0].range_comparison_reason is (
        RangeComparisonReason.INSUFFICIENT_BASELINE
    )
    assert result.snapshot_id == snapshot.snapshot_id
    assert result.quality_report_id == quality.report_id
    assert result.input_market_data_ids == snapshot.market_data_ids


def test_zero_range_close_location_is_explicitly_unavailable() -> None:
    snapshot, observations, quality = _bars((("10", "10", "10", "10"),))
    point = _calculate(snapshot, observations, quality).geometry[0]
    assert point.range == 0
    assert point.close_location is None
    assert point.close_location_reason is CloseLocationReason.ZERO_RANGE
    assert point.range_comparison_reason is RangeComparisonReason.NO_CALLER_BASELINE


@pytest.mark.parametrize(
    ("bars", "expected"),
    (
        (
            (("11", "12", "9", "10"), ("9", "12", "9", "11.5")),
            PatternLabel.ENGULFING_BULLISH,
        ),
        (
            (("9", "11", "8", "10.5"), ("11", "12", "8", "8.5")),
            PatternLabel.ENGULFING_BEARISH,
        ),
        (
            (("10", "11.1", "7", "11"),),
            PatternLabel.PIN_BAR_BULLISH,
        ),
        (
            (("11", "14", "9.9", "10"),),
            PatternLabel.PIN_BAR_BEARISH,
        ),
        (
            (("10", "12", "8", "10"), ("9.5", "12", "9", "10.5")),
            PatternLabel.INSIDE_BAR,
        ),
        (
            (("10", "11", "9", "10"), ("9", "12", "9", "10.5")),
            PatternLabel.OUTSIDE_BAR,
        ),
        (
            (("10", "11", "9", "10.1"),),
            PatternLabel.DOJI,
        ),
        (
            (
                ("12", "12.5", "9", "10"),
                ("10.1", "10.5", "10", "10.2"),
                ("10.4", "11.2", "10.3", "11.1"),
            ),
            PatternLabel.MORNING_STAR,
        ),
        (
            (
                ("10", "13", "9.5", "12"),
                ("11.8", "12", "11.5", "11.9"),
                ("11.6", "11.7", "10.8", "10.9"),
            ),
            PatternLabel.EVENING_STAR,
        ),
    ),
)
def test_versioned_policy_emits_each_contextual_pattern(
    bars: tuple[tuple[str, str, str, str], ...],
    expected: PatternLabel,
) -> None:
    snapshot, observations, quality = _bars(bars)
    policy = _pattern_policy()
    result = _calculate(
        snapshot,
        observations,
        quality,
        pattern_policy=policy,
    )
    assert expected in {
        item.label for point in result.geometry for item in point.patterns
    }
    matched = next(
        item
        for point in result.geometry
        for item in point.patterns
        if item.label is expected
    )
    assert matched.policy_id == policy.policy_id
    assert matched.policy_version == policy.version
    assert matched.confirmation_time == observations[-1].event_time + STEP
    assert matched.invalidation_condition


def test_pattern_threshold_boundary_missing_policy_and_overlap_are_explicit() -> None:
    snapshot, observations, quality = _bars((("10", "11", "9", "10.1"),))
    no_policy = _calculate(snapshot, observations, quality)
    assert no_policy.geometry[0].patterns == ()

    exactly_at_boundary = _calculate(
        snapshot,
        observations,
        quality,
        pattern_policy=_pattern_policy(doji_maximum_body_fraction=Decimal("0.05")),
    )
    below_boundary = _calculate(
        snapshot,
        observations,
        quality,
        pattern_policy=_pattern_policy(doji_maximum_body_fraction=Decimal("0.049")),
    )
    assert PatternLabel.DOJI in {
        item.label for item in exactly_at_boundary.geometry[0].patterns
    }
    assert PatternLabel.DOJI not in {
        item.label for item in below_boundary.geometry[0].patterns
    }

    overlap = _labels((("10", "11.1", "7", "11"),))
    assert {PatternLabel.PIN_BAR_BULLISH, PatternLabel.HAMMER} <= overlap

    with pytest.raises(PriceActionError):
        _pattern_policy(pin_bar_minimum_wick_to_body=Decimal("0.99"))
    with pytest.raises(PriceActionError):
        _pattern_policy(doji_maximum_body_fraction=Decimal("1.01"))
    with pytest.raises(FrozenInstanceError):
        _pattern_policy().version = "2"  # type: ignore[misc]


def test_policy_threshold_edges_for_single_two_and_three_candle_patterns() -> None:
    assert PatternLabel.ENGULFING_BULLISH in _labels(
        (("11", "11.5", "9.5", "10"), ("9.5", "11.5", "9.5", "11.5")),
        _pattern_policy(engulfing_minimum_body_fraction=Decimal("0.5")),
    )
    assert PatternLabel.ENGULFING_BULLISH not in _labels(
        (("11", "11.5", "9.5", "10"), ("9.5", "11.5", "9.5", "11.5")),
        _pattern_policy(engulfing_minimum_body_fraction=Decimal("0.5001")),
    )

    bullish_pin = (("10", "12", "8", "11"),)
    assert {
        PatternLabel.PIN_BAR_BULLISH,
        PatternLabel.HAMMER,
    } <= _labels(
        bullish_pin,
        _pattern_policy(
            pin_bar_minimum_wick_to_body=Decimal(2),
            pin_bar_maximum_body_fraction=Decimal("0.25"),
            pin_bar_maximum_opposite_wick_fraction=Decimal("0.25"),
            hammer_minimum_lower_wick_to_body=Decimal(2),
            hammer_minimum_close_location=Decimal("0.75"),
        ),
    )
    above_pin_ratio = _labels(
        bullish_pin,
        _pattern_policy(
            pin_bar_minimum_wick_to_body=Decimal("2.01"),
            pin_bar_maximum_body_fraction=Decimal("0.25"),
            pin_bar_maximum_opposite_wick_fraction=Decimal("0.25"),
        ),
    )
    assert PatternLabel.PIN_BAR_BULLISH not in above_pin_ratio
    assert PatternLabel.HAMMER not in _labels(
        bullish_pin,
        _pattern_policy(
            hammer_minimum_close_location=Decimal("0.751"),
            pin_bar_maximum_body_fraction=Decimal("0.25"),
            pin_bar_maximum_opposite_wick_fraction=Decimal("0.25"),
        ),
    )

    bearish_pin = (("11", "13", "9", "10"),)
    assert {
        PatternLabel.PIN_BAR_BEARISH,
        PatternLabel.SHOOTING_STAR,
    } <= _labels(
        bearish_pin,
        _pattern_policy(
            pin_bar_minimum_wick_to_body=Decimal(2),
            pin_bar_maximum_body_fraction=Decimal("0.25"),
            pin_bar_maximum_opposite_wick_fraction=Decimal("0.25"),
            shooting_star_minimum_upper_wick_to_body=Decimal(2),
            shooting_star_maximum_close_location=Decimal("0.25"),
        ),
    )
    assert PatternLabel.SHOOTING_STAR not in _labels(
        bearish_pin,
        _pattern_policy(
            shooting_star_maximum_close_location=Decimal("0.249"),
            pin_bar_maximum_body_fraction=Decimal("0.25"),
            pin_bar_maximum_opposite_wick_fraction=Decimal("0.25"),
        ),
    )

    morning_star = (
        ("12", "12", "9", "10"),
        ("10", "11", "10", "10.6"),
        ("10.5", "11", "10.5", "11"),
    )
    assert PatternLabel.MORNING_STAR in _labels(
        morning_star,
        _pattern_policy(
            star_middle_maximum_body_to_first_body=Decimal("0.3"),
            star_minimum_first_body_penetration=Decimal("0.5"),
        ),
    )
    assert PatternLabel.MORNING_STAR not in _labels(
        morning_star,
        _pattern_policy(star_middle_maximum_body_to_first_body=Decimal("0.29")),
    )
    assert PatternLabel.MORNING_STAR not in _labels(
        morning_star,
        _pattern_policy(star_minimum_first_body_penetration=Decimal("0.501")),
    )

    evening_star = (
        ("10", "13", "10", "12"),
        ("12", "12", "11", "11.4"),
        ("11.5", "11.5", "11", "11"),
    )
    assert PatternLabel.EVENING_STAR in _labels(
        evening_star,
        _pattern_policy(
            star_middle_maximum_body_to_first_body=Decimal("0.3"),
            star_minimum_first_body_penetration=Decimal("0.5"),
        ),
    )


def test_pivots_wait_for_closed_right_window_and_do_not_repaint() -> None:
    snapshot, observations, quality = _bars(
        (("2", "3", "1", "2"), ("3", "5", "2", "4"), ("2", "4", "2", "3"))
    )
    policy = _zone_policy(right_window=2)
    assert not _calculate(
        snapshot, observations, quality, support_resistance_policy=policy
    ).pivots

    extended_snapshot, extended, extended_quality = _bars(
        (
            ("2", "3", "1", "2"),
            ("3", "5", "2", "4"),
            ("2", "4", "2", "3"),
            ("2", "3", "2", "2.5"),
            ("2", "3", "2", "2.5"),
        )
    )
    prefix_snapshot = replace(
        extended_snapshot,
        as_of=START + STEP * 4,
        market_data_ids=tuple(candle.market_data_id for candle in extended[:4]),
    )
    prefix_quality = replace(
        extended_quality,
        snapshot_id=prefix_snapshot.snapshot_id,
        assessed_at=prefix_snapshot.as_of,
        required_data_cutoff=prefix_snapshot.as_of,
    )
    first = _calculate(
        prefix_snapshot,
        extended[:4],
        prefix_quality,
        support_resistance_policy=_zone_policy(),
    )
    pivot = next(item for item in first.pivots if item.kind is PivotKind.HIGH)
    assert pivot.source_market_data_id == extended[1].market_data_id
    assert pivot.source_time == extended[1].event_time
    assert pivot.confirmation_market_data_id == extended[2].market_data_id
    assert pivot.confirmation_time == extended[2].event_time + STEP

    later = _calculate(
        extended_snapshot,
        extended,
        extended_quality,
        support_resistance_policy=_zone_policy(),
    )
    assert next(item for item in later.pivots if item.kind is PivotKind.HIGH) == pivot


def test_pivot_ties_choose_the_earliest_equal_extreme_and_edges_warm_up() -> None:
    snapshot, observations, quality = _bars(
        (
            ("2", "3", "1", "2"),
            ("3", "5", "2", "4"),
            ("3", "5", "2", "4"),
            ("2", "4", "2", "3"),
        )
    )
    result = _calculate(
        snapshot,
        observations,
        quality,
        support_resistance_policy=_zone_policy(),
    )
    highs = tuple(item for item in result.pivots if item.kind is PivotKind.HIGH)
    assert len(highs) == 1
    assert highs[0].source_market_data_id == observations[1].market_data_id

    short_snapshot, short_observations, short_quality = _bars(
        (("2", "3", "1", "2"), ("3", "5", "2", "4"))
    )
    short = _calculate(
        short_snapshot,
        short_observations,
        short_quality,
        support_resistance_policy=_zone_policy(),
    )
    assert short.pivots == ()


def test_zones_use_fixed_lowest_anchor_and_count_distinct_later_interactions() -> None:
    snapshot, observations, quality = _bars(
        (
            ("7", "8", "5", "7"),
            ("9", "10", "6", "9"),
            ("6", "7", "5", "6"),
            ("10", "11", "6", "10"),
            ("6", "7", "5", "6"),
            ("11", "12", "6", "11"),
            ("6", "7", "5", "6"),
            ("8", "9", "6", "8"),
        )
    )
    candidate_result = _calculate(
        snapshot,
        observations,
        quality,
        support_resistance_policy=_zone_policy(minimum_repeated_interactions=2),
    )
    candidate = next(
        zone
        for zone in candidate_result.zones
        if zone.kind is PivotKind.HIGH and zone.anchor_price == Decimal(10)
    )
    assert candidate.status is ZoneStatus.CANDIDATE

    policy = _zone_policy(minimum_repeated_interactions=1)
    result = _calculate(
        snapshot,
        observations,
        quality,
        support_resistance_policy=policy,
    )
    assert (
        _calculate(
            snapshot,
            observations,
            quality,
            support_resistance_policy=policy,
        )
        == result
    )
    high_zones = tuple(zone for zone in result.zones if zone.kind is PivotKind.HIGH)
    assert tuple(zone.anchor_price for zone in high_zones) == (
        Decimal(10),
        Decimal(12),
    )
    first = high_zones[0]
    assert first.upper_price == Decimal(11)
    assert first.status is ZoneStatus.REPEATED
    assert len(first.interactions) == len(
        {item.market_data_id for item in first.interactions}
    )
    assert first.interactions
    assert all(item.candle_time >= first.creation_time for item in first.interactions)
    assert first.contributor_market_data_ids == (
        observations[1].market_data_id,
        observations[3].market_data_id,
    )
    assert high_zones[1].status is ZoneStatus.CANDIDATE
    assert "strictly above" in first.invalidation_condition


def test_zone_break_requires_policy_close_count_and_records_invalidation() -> None:
    snapshot, observations, quality = _bars(
        (
            ("6.5", "8", "6", "7"),
            ("9", "10", "8", "9.5"),
            ("5.5", "7", "5", "6"),
            ("9.5", "11", "8", "10.5"),
            ("10.5", "12", "9", "10.6"),
            ("11.5", "13", "10", "10.7"),
        )
    )
    result = _calculate(
        snapshot,
        observations,
        quality,
        support_resistance_policy=_zone_policy(),
    )
    zone = next(zone for zone in result.zones if zone.kind is PivotKind.HIGH)
    assert zone.anchor_price == Decimal(10)
    assert zone.status is ZoneStatus.BROKEN
    assert zone.invalidated_at == observations[5].event_time + STEP


def test_canonical_evidence_and_c012_findings_preserve_lineage_without_observations() -> (
    None
):
    snapshot, observations, quality = _bars(
        (("10", "11", "9", "10.5"), ("10", "11", "9", "10.5"))
    )
    result = _calculate(snapshot, observations, quality)
    repeated = _calculate(snapshot, observations, quality)
    encoded = json.loads(result.evidence.value)
    assert encoded["snapshot_id"] == str(snapshot.snapshot_id)
    assert encoded["quality_report_id"] == str(quality.report_id)
    assert encoded["input_market_data_ids"] == [
        str(identifier) for identifier in snapshot.market_data_ids
    ]
    assert result.evidence.source_record_ids == snapshot.source_record_ids
    assert result.evidence.data_quality_report_id == quality.report_id
    assert result.evidence.method.version == result.method_version
    assert repeated == result
    assert result.assessment.contract_id == "C-012"
    assert result.assessment.status is AssessmentStatus.AVAILABLE
    assert result.assessment.observations == ()
    assert {finding.category for finding in result.assessment.findings} == {
        "price-action-observation",
        "support-resistance-observation",
    }
    assert all(
        finding.evidence_ids == (result.evidence.evidence_id,)
        and finding.invalidation_condition
        for finding in result.assessment.findings
    )
    assert result.uncertainty and result.limitations


@pytest.mark.parametrize(
    "changes",
    (
        {"quality": "stale"},
        {"quality": "degraded"},
        {"quality_snapshot": True},
        {"quality_cutoff": True},
        {"reordered": True},
        {"duplicate": True},
        {"gap": True},
        {"unaligned": True},
        {"availability": True},
        {"provenance": True},
        {"unit": True},
        {"ohlc": True},
        {"non_spot": True},
    ),
)
def test_invalid_quality_lineage_order_gap_availability_ohlc_or_units_fail_closed(
    changes: dict[str, object],
) -> None:
    snapshot, observations, quality = _bars(
        (
            ("10", "11", "9", "10.5"),
            ("10", "11", "9", "10.5"),
            ("10", "11", "9", "10.5"),
        )
    )
    if changes.get("quality") == "stale":
        quality = replace(quality, status=DataQualityStatus.STALE)
    if changes.get("quality") == "degraded":
        quality = replace(quality, status=DataQualityStatus.DEGRADED)
    if changes.get("quality_snapshot"):
        quality = replace(quality, snapshot_id=uuid4())
    if changes.get("quality_cutoff"):
        quality = replace(quality, required_data_cutoff=snapshot.as_of - STEP)
    if changes.get("reordered"):
        observations = tuple(reversed(observations))
    if changes.get("duplicate"):
        observations = observations[:1] + (observations[0],) + observations[2:]
    if changes.get("gap"):
        candle = observations[1]
        observations = (
            observations[:1]
            + (
                replace(
                    candle,
                    event_time=candle.event_time + STEP,
                    provider_time=candle.provider_time + STEP,
                    ingestion_time=candle.ingestion_time + STEP,
                    availability_time=candle.availability_time + STEP,
                ),
            )
            + observations[2:]
        )
    if changes.get("unaligned"):
        offset = timedelta(seconds=30)
        observations = tuple(
            replace(
                candle,
                event_time=candle.event_time + offset,
                provider_time=candle.provider_time + offset,
                ingestion_time=candle.ingestion_time + offset,
                availability_time=candle.availability_time + offset,
            )
            for candle in observations
        )
        snapshot = replace(
            snapshot,
            as_of=snapshot.as_of + offset,
            created_at=snapshot.created_at + offset,
        )
        quality = replace(
            quality,
            assessed_at=quality.assessed_at + offset,
            required_data_cutoff=quality.required_data_cutoff + offset,
        )
    if changes.get("availability"):
        observations = observations[:-1] + (
            replace(
                observations[-1],
                availability_time=snapshot.as_of + STEP,
            ),
        )
    if changes.get("provenance"):
        observations = observations[:-1] + (
            replace(observations[-1], source_record_id=uuid4()),
        )
    if changes.get("unit"):
        candle = observations[-1]
        observations = observations[:-1] + (
            replace(
                candle,
                metrics=tuple(
                    replace(metric, unit="USD")
                    if metric.metric_name == "high"
                    else metric
                    for metric in candle.metrics
                ),
            ),
        )
    if changes.get("ohlc"):
        candle = observations[-1]
        observations = observations[:-1] + (
            replace(
                candle,
                metrics=tuple(
                    replace(metric, value=Decimal("8"))
                    if metric.metric_name == "high"
                    else metric
                    for metric in candle.metrics
                ),
            ),
        )
    if changes.get("non_spot"):
        snapshot = replace(
            snapshot,
            instrument_id="BTC-USDT-PERP",
            venue_id="BINANCE-PERP",
        )
        observations = tuple(
            replace(
                candle,
                instrument_id="BTC-USDT-PERP",
                venue_id="BINANCE-PERP",
            )
            for candle in observations
        )

    with pytest.raises(PriceActionError):
        _calculate(snapshot, observations, quality)


def test_invalid_policies_timeframes_versions_and_oversized_series_fail_closed() -> (
    None
):
    snapshot, observations, quality = _bars((("10", "11", "9", "10.5"),))
    with pytest.raises(PriceActionError):
        SupportResistancePolicy("bad", "1", 1, 1, Decimal(0), "USDT", 1, Decimal(0), 1)
    with pytest.raises(PriceActionError):
        _zone_policy(left_window=True)
    with pytest.raises(PriceActionError):
        _zone_policy(price_tolerance=Decimal("1e129"))
    with pytest.raises(PriceActionError, match="unit"):
        _calculate(
            snapshot,
            observations,
            quality,
            support_resistance_policy=_zone_policy(price_unit="BTC"),
        )
    with pytest.raises(PriceActionError):
        RangeBaselinePolicy("bad", "1", 1, Decimal(1))
    with pytest.raises(PriceActionError):
        _calculate(snapshot, observations, quality, timeframe="1w")
    with pytest.raises(PriceActionError):
        _calculate(snapshot, observations, quality, timeframe=[])
    with pytest.raises(PriceActionError):
        _calculate(snapshot, observations, quality, metadata_version="2")
    with pytest.raises(IndicatorMetadataError):
        SPOT_RESEARCH_INDICATORS.get("price-action-support-resistance", "2")

    large_snapshot, large_observations, large_quality = evidence(
        tuple("10" for _ in range(10_001))
    )
    with pytest.raises(PriceActionError, match="bounded"):
        _calculate(large_snapshot, large_observations, large_quality)


def test_registry_metadata_marks_method_validated_correlated_and_exact_versioned() -> (
    None
):
    metadata = SPOT_RESEARCH_INDICATORS.get("price-action-support-resistance", "1")
    assert metadata.phase is IndicatorPhase.VALIDATED
    assert metadata.category is IndicatorCategory.PRICE_ACTION
    assert metadata.calculation_version == PRICE_ACTION_METHOD_VERSION
    assert metadata.timeframes == ("1m", "5m", "15m", "1h", "4h", "1d")
    assert not metadata.evidence_independent
    assert metadata.evidence_dependencies
    assert metadata.output_nullable
    assert metadata.failure_modes
    with pytest.raises(IndicatorMetadataError, match="exact"):
        SPOT_RESEARCH_INDICATORS.get("price-action-support-resistance", "latest")
