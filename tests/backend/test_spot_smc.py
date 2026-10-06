from dataclasses import replace
from datetime import timedelta
from decimal import Decimal

import pytest
from test_market_structure import HIGHS, _analyze, _policies
from trading_platform_api.analysis import (
    BreakDirection,
    MarketStructurePolicy,
    PivotKind,
    SpotSMCError,
    SpotSMCPolicy,
    calculate_spot_market_structure,
    calculate_spot_price_action,
    calculate_spot_smc,
)
from trading_platform_api.market_data.contracts import DataQualityStatus


def _policy(**changes: object) -> SpotSMCPolicy:
    values: dict[str, object] = {
        "policy_id": "test-spot-smc",
        "version": "1",
        "price_tolerance": Decimal("0.1"),
        "sweep_buffer": Decimal("0"),
        "minimum_pivot_count": 2,
        "order_block_lookback": 3,
        "displacement_lookback": 2,
        "minimum_body_fraction": Decimal("0.5"),
        "minimum_range_multiple": Decimal("1.5"),
        "maximum_output_records": 1000,
    }
    values.update(changes)
    return SpotSMCPolicy(**values)  # type: ignore[arg-type]


def _inputs(
    overrides: dict[int, tuple[str, str, str, str]] | None = None,
    *,
    break_count: int = 1,
    availability_delays: dict[int, timedelta] | None = None,
):
    snapshot, original, quality, internal, external, *_ = _analyze()
    overrides = overrides or {}
    availability_delays = availability_delays or {}
    candles = []
    for index, candle in enumerate(original):
        metrics = {metric.metric_name: metric for metric in candle.metrics}
        opening, high, low, close = overrides.get(
            index,
            tuple(
                str(metrics[name].value) for name in ("open", "high", "low", "close")
            ),
        )
        candles.append(
            replace(
                candle,
                availability_time=candle.availability_time
                + availability_delays.get(index, timedelta(0)),
                metrics=tuple(
                    replace(
                        metric,
                        value=Decimal(
                            {
                                "open": opening,
                                "high": high,
                                "low": low,
                                "close": close,
                            }[metric.metric_name]
                        ),
                    )
                    if metric.metric_name in {"open", "high", "low", "close"}
                    else metric
                    for metric in candle.metrics
                ),
            )
        )
    observations = tuple(candles)
    internal_policy, external_policy = _policies()
    internal_action = calculate_spot_price_action(
        snapshot=snapshot,
        observations=observations,
        quality=quality,
        timeframe="1m",
        support_resistance_policy=internal_policy,
    )
    external_action = calculate_spot_price_action(
        snapshot=snapshot,
        observations=observations,
        quality=quality,
        timeframe="1m",
        support_resistance_policy=external_policy,
    )
    structure = calculate_spot_market_structure(
        snapshot=snapshot,
        observations=observations,
        quality=quality,
        timeframe="1m",
        internal_price_action=internal_action,
        external_price_action=external_action,
        internal_pivot_policy=internal_policy,
        external_pivot_policy=external_policy,
        break_policy=MarketStructurePolicy(
            "smc-test-breaks", "1", Decimal("0.5"), break_count
        ),
    )
    return snapshot, observations, quality, structure


def _calculate(
    overrides: dict[int, tuple[str, str, str, str]] | None = None,
    *,
    policy: SpotSMCPolicy | None = None,
    break_count: int = 1,
    availability_delays: dict[int, timedelta] | None = None,
):
    snapshot, observations, quality, structure = _inputs(
        overrides,
        break_count=break_count,
        availability_delays=availability_delays,
    )
    result = calculate_spot_smc(
        snapshot=snapshot,
        observations=observations,
        quality=quality,
        timeframe="1m",
        market_structure=structure,
        policy=policy or _policy(),
    )
    return snapshot, observations, quality, structure, result


def _details(record):
    return {item.name: item.value for item in record.details}


def _area_source(area, structure):
    pivot_map = {swing.pivot.pivot_id: swing.pivot for swing in structure.swings}
    return tuple(
        sorted(
            (
                pivot_map[pivot_id].kind.value,
                pivot_map[pivot_id].source_time,
                pivot_map[pivot_id].price,
            )
            for pivot_id in area.source_pivot_ids
        )
    )


def _fvg_for_creation(result, candle_id):
    return next(
        item
        for item in result.objects
        if item.category == "fair-value-gap"
        and _details(item)["creation_candle_id"] == candle_id
    )


def _latest_source_availability(record, observations):
    data_by_id = {item.market_data_id: item for item in observations}
    return max(
        data_by_id[source_id].availability_time
        for source_id in record.source_market_data_ids
    )


def _fvg_overrides(
    third_low: str = "13", later: tuple[str, str, str, str] | None = None
):
    bars = {
        0: ("9", "10", "8", "9"),
        1: ("11", "12", "10", "11"),
        2: (
            "13.5",
            "14",
            third_low,
            "13.8" if Decimal(third_low) < Decimal("13.8") else third_low,
        ),
    }
    for index in range(3, len(HIGHS)):
        bars[index] = ("30", "31", "30", "30.5")
    if later is not None:
        bars[3] = later
    return bars


def test_fvg_strict_gap_boundary_and_creation_candle_no_lookahead():
    snapshot, observations, _, _, result = _calculate(_fvg_overrides())
    bullish = _fvg_for_creation(result, observations[2].market_data_id)
    assert (bullish.lower_price, bullish.upper_price) == (
        Decimal("10"),
        Decimal("13"),
    )
    assert bullish.lifecycle_state == "active"
    assert bullish.mitigation_percentage == Decimal(0)
    assert bullish.creation_time == observations[2].event_time + timedelta(minutes=1)
    assert bullish.available_at == snapshot.as_of

    _, equal_observations, _, _, equal = _calculate(_fvg_overrides("10"))
    assert not any(
        item.category == "fair-value-gap"
        and _details(item)["creation_candle_id"] == equal_observations[2].market_data_id
        for item in equal.objects
    )


@pytest.mark.parametrize(
    ("later", "expected_state", "expected_fill"),
    (
        (("15", "32", "11.5", "15"), "partially-filled", Decimal("50")),
        (("15", "32", "10", "10"), "filled", Decimal("100")),
        (("15", "32", "9", "9.5"), "invalidated", Decimal("100")),
    ),
)
def test_fvg_lifecycle_wick_fill_and_close_invalidation(
    later, expected_state, expected_fill
):
    _, observations, _, _, result = _calculate(_fvg_overrides(later=later))
    fvg = _fvg_for_creation(result, observations[2].market_data_id)
    assert fvg.lifecycle_state == expected_state
    assert fvg.mitigation_percentage == expected_fill
    if expected_state == "invalidated":
        assert fvg.available_at == _latest_source_availability(fvg, observations)
    else:
        assert fvg.available_at == observations[-1].event_time + timedelta(minutes=1)


def test_filled_fvg_remains_observed_until_later_close_invalidation():
    bars = _fvg_overrides(later=("15", "32", "10", "11"))
    bars[4] = ("15", "32", "9", "9.5")
    _, observations, _, _, result = _calculate(bars)
    fvg = _fvg_for_creation(result, observations[2].market_data_id)
    assert fvg.lifecycle_state == "invalidated"
    assert fvg.mitigation_percentage == Decimal(100)
    assert fvg.available_at == _latest_source_availability(fvg, observations)


def test_lifecycle_availability_includes_delayed_market_data_and_quality():
    _, observations, quality, _, result = _calculate(
        _fvg_overrides(later=("15", "32", "9", "9.5")),
        availability_delays={3: timedelta(seconds=90)},
    )
    fvg = _fvg_for_creation(result, observations[2].market_data_id)
    assert fvg.available_at == _latest_source_availability(fvg, observations)
    assert fvg.available_at == observations[3].availability_time
    assert fvg.available_at > observations[3].event_time + timedelta(minutes=1)
    assert fvg.available_at < quality.assessed_at


def test_displacement_requires_full_prior_history_and_exact_thresholds():
    bars = {
        16: ("10", "12", "10", "10"),
        17: ("10", "12", "10", "10"),
        18: ("10", "14", "10", "12"),
    }
    policy = _policy(
        displacement_lookback=2,
        minimum_body_fraction=Decimal("0.5"),
        minimum_range_multiple=Decimal("2"),
    )
    _, observations, _, _, result = _calculate(bars, policy=policy)
    warmup = next(
        item
        for item in result.objects
        if item.category == "displacement"
        and _details(item)["source_candle_id"] == observations[0].market_data_id
    )
    exact = next(
        item
        for item in result.objects
        if item.category == "displacement"
        and _details(item)["source_candle_id"] == observations[18].market_data_id
    )
    assert warmup.lifecycle_state == "unavailable"
    assert _details(warmup)["unavailable_reason"] == "insufficient-prior-range-history"
    assert exact.lifecycle_state == "displacement"
    assert _details(exact)["body_fraction"] == Decimal("0.5")
    assert _details(exact)["prior_median_range"] == Decimal(2)
    assert _details(exact)["direction"] == BreakDirection.UP.value


def test_order_block_uses_linked_displacement_event_and_breaker_retest_lifecycle():
    bars = {
        15: ("16", "20", "14", "15"),
        16: ("15", "16", "13", "14"),
        17: ("12", "22", "12", "21"),
        18: ("17", "18", "10", "12"),
        19: ("10.5", "13.5", "10", "11"),
    }
    policy = _policy(
        order_block_lookback=3,
        displacement_lookback=2,
        minimum_body_fraction=Decimal("0.5"),
        minimum_range_multiple=Decimal("1.5"),
    )
    _, observations, _, structure, result = _calculate(
        bars, policy=policy, break_count=1
    )
    confirming_id = observations[17].market_data_id
    linked_events = [
        event
        for event in structure.events
        if event.confirming_market_data_id == confirming_id
        and event.event_type.value in {"BOS", "CHoCH", "MSS"}
        and event.direction is BreakDirection.UP
    ]
    assert linked_events
    blocks = [
        item
        for item in result.objects
        if item.category == "order-block"
        and item.subtype == "bullish"
        and _details(item)["origin_candle_id"] == observations[16].market_data_id
    ]
    assert blocks
    block = blocks[0]
    assert (block.lower_price, block.upper_price) == (Decimal("13"), Decimal("16"))
    assert block.lifecycle_state == "invalidated"
    assert block.mitigation_percentage == Decimal(100)
    assert block.available_at == _latest_source_availability(block, observations)
    assert block.source_event_ids
    breaker = next(
        item
        for item in result.objects
        if item.category == "breaker-block"
        and _details(item)["origin_order_block_id"] == block.object_id
    )
    assert breaker.subtype == "bearish"
    assert breaker.lifecycle_state == "mitigated"
    assert breaker.mitigation_percentage > 0
    assert breaker.available_at == _latest_source_availability(breaker, observations)
    assert _details(breaker)["transition_candle_id"] == observations[18].market_data_id
    assert _details(breaker)["origin_event_id"] == block.source_event_ids[0]


def test_order_block_reports_when_no_opposing_candle_is_in_bounded_lookback():
    bars = {
        14: ("13.5", "15", "12", "13.5"),
        15: ("16", "20", "14", "16"),
        16: ("14", "16", "13", "14"),
        17: ("12", "22", "12", "21"),
    }
    policy = _policy(
        order_block_lookback=3,
        displacement_lookback=2,
        minimum_body_fraction=Decimal("0.5"),
        minimum_range_multiple=Decimal("1.5"),
    )
    _, observations, _, structure, result = _calculate(
        bars, policy=policy, break_count=1
    )
    confirming_id = observations[17].market_data_id
    assert any(
        event.confirming_market_data_id == confirming_id
        and event.event_type.value in {"BOS", "CHoCH", "MSS"}
        and event.direction is BreakDirection.UP
        for event in structure.events
    )
    unavailable = [
        item
        for item in result.objects
        if item.category == "order-block"
        and item.subtype == "unavailable-no-opposing-body"
    ]
    assert unavailable
    assert all(
        _details(item)["reason"] == "no-opposing-body-in-bounded-lookback"
        for item in unavailable
    )


def test_potential_liquidity_groups_same_kind_on_a_fixed_anchor_with_lineage():
    policy = _policy(price_tolerance=Decimal("100"))
    _, _, _, structure, result = _calculate(policy=policy)
    pivots = {swing.pivot.pivot_id: swing.pivot for swing in structure.swings}
    areas = [
        item
        for item in result.objects
        if item.category == "liquidity" and item.subtype.startswith("potential-")
    ]
    assert areas
    for area in areas:
        details = _details(area)
        group = tuple(pivots[pivot_id] for pivot_id in details["pivot_ids"])
        expected_kind = (
            PivotKind.HIGH
            if area.subtype == "potential-high-side-area"
            else PivotKind.LOW
        )
        assert all(pivot.kind is expected_kind for pivot in group)
        assert len(group) >= policy.minimum_pivot_count
        assert all(
            abs(pivot.price - group[0].price) <= policy.price_tolerance
            for pivot in group
        )
        assert area.source_pivot_ids == details["pivot_ids"]
        assert area.lower_price == min(pivot.price for pivot in group)
        assert area.upper_price == max(pivot.price for pivot in group)
        assert "potential-area" == area.lifecycle_state
        assert "not a confirmed stop cluster" in area.invalidation_condition


@pytest.mark.parametrize("side", ("high", "low"))
def test_potential_liquidity_sweep_requires_strict_buffer_and_reclaim(side):
    policy = _policy(
        price_tolerance=Decimal("0.1"),
        sweep_buffer=Decimal(1),
    )
    snapshot, _, _, structure, baseline = _calculate(policy=policy)
    side_name = "high-side" if side == "high" else "low-side"
    areas = [
        item
        for item in baseline.objects
        if item.category == "liquidity"
        and item.subtype == f"potential-{side_name}-area"
        and item.available_at <= snapshot.as_of - timedelta(minutes=1)
    ]
    assert areas
    area = areas[0]
    assert area.lower_price is not None and area.upper_price is not None
    target = area.upper_price if side == "high" else area.lower_price
    strict_extreme = target + Decimal("2") if side == "high" else target - Decimal("2")
    equality_extreme = target + Decimal(1) if side == "high" else target - Decimal(1)
    assert strict_extreme > 0 and equality_extreme > 0
    candle_id_index = len(HIGHS) - 1
    _, original_candles, _, _ = _inputs()
    original = {
        metric.metric_name: metric.value
        for metric in original_candles[candle_id_index].metrics
    }

    def analyze(extreme: Decimal):
        if side == "high":
            low = min(original["low"], target - Decimal(1))
            bar = (str(target), str(extreme), str(low), str(target))
        else:
            high = max(original["high"], target + Decimal(1))
            bar = (str(target), str(high), str(extreme), str(target))
        _, final_candles, _, final_structure, result = _calculate(
            {candle_id_index: bar}, policy=policy
        )
        target_source = _area_source(area, structure)
        matching_area = next(
            item
            for item in result.objects
            if item.category == "liquidity"
            and item.subtype == f"potential-{side_name}-area"
            and _area_source(item, final_structure) == target_source
        )
        matching_sweeps = [
            item
            for item in result.objects
            if item.category == "liquidity"
            and item.subtype == "liquidity-sweep"
            and _details(item)["area_id"] == matching_area.object_id
            and _details(item)["source_candle_id"]
            == final_candles[candle_id_index].market_data_id
        ]
        return matching_sweeps

    assert not analyze(equality_extreme)
    sweeps = analyze(strict_extreme)
    assert sweeps
    sweep = sweeps[0]
    assert _details(sweep)["reclaimed"] is True
    assert _details(sweep)["wick_depth"] == Decimal(2)
    assert _details(sweep)["source_candle_id"] == sweep.source_market_data_ids[-1]
    assert "hidden stops" in sweep.limitations[1]


def test_spot_smc_is_repeatable_evidence_linked_and_descriptive_only():
    snapshot, observations, quality, structure, first = _calculate()
    second = calculate_spot_smc(
        snapshot=snapshot,
        observations=observations,
        quality=quality,
        timeframe="1m",
        market_structure=structure,
        policy=first.policy,
    )
    assert first == second
    assert first.method_version == "spot-smc-v1"
    assert first.evidence.contract_id == "C-008"
    assert first.assessment.contract_id == "C-013"
    assert first.assessment.evidence_ids == (
        first.evidence.evidence_id,
        structure.evidence.evidence_id,
    )
    assert all(
        observation.evidence_ids == first.assessment.evidence_ids
        for observation in first.assessment.observations
    )
    assert "execution permission" in first.evidence.limitations[0]


def test_smc_fails_closed_for_quality_lineage_policy_metadata_and_output_bounds():
    snapshot, observations, quality, structure = _inputs()
    args = {
        "snapshot": snapshot,
        "observations": observations,
        "quality": quality,
        "timeframe": "1m",
        "market_structure": structure,
        "policy": _policy(),
    }
    with pytest.raises(SpotSMCError, match="Unknown exact"):
        calculate_spot_smc(**args, metadata_version="2")
    with pytest.raises(SpotSMCError, match="caller policy bound"):
        calculate_spot_smc(**{**args, "policy": _policy(maximum_output_records=1)})
    with pytest.raises(SpotSMCError, match="shared analysis validation"):
        calculate_spot_smc(
            **{
                **args,
                "quality": replace(quality, status=DataQualityStatus.DEGRADED),
            }
        )
    with pytest.raises(SpotSMCError, match="exact #56 method"):
        calculate_spot_smc(
            **{**args, "market_structure": replace(structure, method_version="unknown")}
        )
    with pytest.raises(SpotSMCError, match="price_tolerance"):
        _policy(price_tolerance=Decimal(0))
    gapped = list(observations)
    gapped[4] = replace(
        gapped[4], event_time=gapped[4].event_time - gapped[4].event_time.resolution
    )
    with pytest.raises(SpotSMCError, match="shared analysis validation"):
        calculate_spot_smc(**{**args, "observations": tuple(gapped)})


def test_liquidity_sweeps_stop_at_the_caller_output_bound():
    policy = _policy(price_tolerance=Decimal("0.1"), sweep_buffer=Decimal(0))
    _, _, _, _, baseline = _calculate(policy=policy)
    areas = sum(
        item.category == "liquidity" and item.subtype.startswith("potential-")
        for item in baseline.objects
    )
    sweeps = sum(
        item.category == "liquidity" and item.subtype == "liquidity-sweep"
        for item in baseline.objects
    )
    assert areas and sweeps
    baseline_count = sum(
        item.category
        in {
            "fair-value-gap",
            "displacement",
            "bos",
            "choch",
            "mss",
            "premium-discount",
        }
        for item in baseline.objects
    )
    cap = baseline_count
    assert cap + areas < policy.maximum_output_records
    with pytest.raises(SpotSMCError, match="caller policy bound"):
        _calculate(policy=replace(policy, maximum_output_records=cap + areas))


def test_external_premium_discount_anchor_and_midpoint_boundaries():
    snapshot, observations, quality, structure = _inputs()
    external = [
        swing.pivot for swing in structure.swings if swing.scale.value == "external"
    ]
    highs = [pivot for pivot in external if pivot.kind is PivotKind.HIGH]
    lows = [pivot for pivot in external if pivot.kind is PivotKind.LOW]
    assert highs and lows
    high = max(highs, key=lambda item: item.confirmation_time)
    low = max(lows, key=lambda item: item.confirmation_time)
    assert high.price > low.price
    midpoint = (high.price + low.price) / Decimal(2)
    original_last = observations[-1]
    metrics = {metric.metric_name: metric for metric in original_last.metrics}

    def at_close(close: Decimal):
        bars = {
            len(observations) - 1: (
                str(close),
                str(metrics["high"].value),
                str(metrics["low"].value),
                str(close),
            )
        }
        point_snapshot, point_candles, point_quality, point_structure = _inputs(bars)
        return (
            calculate_spot_smc(
                snapshot=point_snapshot,
                observations=point_candles,
                quality=point_quality,
                timeframe="1m",
                market_structure=point_structure,
                policy=_policy(),
            ),
            point_structure,
        )

    for price, expected in (
        (midpoint, "equilibrium"),
        (midpoint + Decimal("0.1"), "premium"),
        (midpoint - Decimal("0.1"), "discount"),
    ):
        result, point_structure = at_close(price)
        premium = next(
            item for item in result.objects if item.category == "premium-discount"
        )
        assert premium.subtype == expected
        assert _details(premium)["midpoint"] == midpoint
        point_pivots = [
            swing.pivot
            for swing in point_structure.swings
            if swing.scale.value == "external"
        ]
        point_high = max(
            (pivot for pivot in point_pivots if pivot.kind is PivotKind.HIGH),
            key=lambda item: item.confirmation_time,
        )
        point_low = max(
            (pivot for pivot in point_pivots if pivot.kind is PivotKind.LOW),
            key=lambda item: item.confirmation_time,
        )
        assert premium.source_pivot_ids == (point_high.pivot_id, point_low.pivot_id)


def test_missing_external_pivots_are_reported_unavailable_not_guessed():
    bars = {index: ("9", "10", "8", "9") for index in range(len(HIGHS))}
    _, _, _, _, result = _calculate(bars)
    premium = next(
        item for item in result.objects if item.category == "premium-discount"
    )
    assert premium.subtype == "unavailable"
    assert _details(premium)["unavailable_reason"] == (
        "missing-latest-confirmed-external-high-or-low"
    )
