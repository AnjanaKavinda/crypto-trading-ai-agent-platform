from dataclasses import replace
from datetime import timedelta
from decimal import Decimal, localcontext
from uuid import uuid4

import pytest
from test_moving_averages import STEP, evidence
from trading_platform_api.analysis import (
    SPOT_RESEARCH_INDICATORS,
    VolumeAnalysisError,
    VolumeProfileReason,
    VolumeProfileStatus,
    VWAPReason,
    VWAPStatus,
    calculate_volume_profile,
    calculate_vwap,
)
from trading_platform_api.market_data.contracts import (
    DataQualityStatus,
    MarketData,
    MarketSnapshot,
)


def with_volumes(
    observations: tuple[MarketData, ...], values: tuple[str, ...]
) -> tuple[MarketData, ...]:
    assert len(observations) == len(values)
    return tuple(
        replace(
            candle,
            metrics=tuple(
                replace(metric, value=Decimal(value))
                if metric.metric_name == "volume"
                else metric
                for metric in candle.metrics
            ),
        )
        for candle, value in zip(observations, values, strict=True)
    )


def test_vwap_is_cumulative_bar_based_and_preserves_first_candle_anchor() -> None:
    snapshot, observations, quality = evidence(("10", "20", "30"))
    observations = with_volumes(observations, ("1", "2", "1"))

    result = calculate_vwap(
        snapshot=snapshot,
        observations=observations,
        quality=quality,
    )

    with localcontext() as context:
        context.prec = 34
        assert tuple(point.value.value for point in result.points) == (
            Decimal(10),
            Decimal(50) / Decimal(3),
            Decimal(20),
        )
    assert all(point.value.status is VWAPStatus.READY for point in result.points)
    assert result.method_label == "bar-based typical-price VWAP"
    assert result.anchor_mode == "first-candle"
    assert result.anchor_time == observations[0].event_time
    assert result.window_start == observations[0].event_time
    assert result.window_end == snapshot.as_of


def test_vwap_zero_cumulative_volume_is_explicit_then_recovers() -> None:
    snapshot, observations, quality = evidence(("10", "20", "30"))
    observations = with_volumes(observations, ("0", "0", "2"))

    result = calculate_vwap(
        snapshot=snapshot,
        observations=observations,
        quality=quality,
    )

    assert all(
        point.value.status is VWAPStatus.UNDEFINED for point in result.points[:2]
    )
    assert all(
        point.value.reason is VWAPReason.ZERO_CUMULATIVE_VOLUME
        and point.value.value is None
        for point in result.points[:2]
    )
    assert result.points[-1].value.value == Decimal(30)
    assert result.points[-1].value.status is VWAPStatus.READY


def test_single_candle_is_a_valid_calculation_window() -> None:
    snapshot, observations, quality = evidence(("10",))

    vwap = calculate_vwap(
        snapshot=snapshot,
        observations=observations,
        quality=quality,
    )
    profile = calculate_volume_profile(
        snapshot=snapshot,
        observations=observations,
        quality=quality,
        bin_count=1,
    )

    assert vwap.points[0].value.value == Decimal(10)
    assert vwap.anchor_time == observations[0].event_time
    assert profile.status is VolumeProfileStatus.READY
    assert len(profile.bins) == 1
    assert profile.poc_bin_index == 0


def test_profile_edges_half_open_assignment_and_final_upper_edge() -> None:
    snapshot, observations, quality = evidence(("10", "20", "30", "40", "50"))

    result = calculate_volume_profile(
        snapshot=snapshot,
        observations=observations,
        quality=quality,
        bin_count=4,
    )

    assert tuple((item.lower_bound, item.upper_bound) for item in result.bins) == (
        (Decimal(10), Decimal(20)),
        (Decimal(20), Decimal(30)),
        (Decimal(30), Decimal(40)),
        (Decimal(40), Decimal(50)),
    )
    assert tuple(item.assigned_volume for item in result.bins) == (
        Decimal(1),
        Decimal(1),
        Decimal(1),
        Decimal(2),
    )
    assert tuple(item.includes_upper_bound for item in result.bins) == (
        False,
        False,
        False,
        True,
    )
    assert result.method_label == "candle-assigned volume-profile proxy"
    assert result.poc_bin_index == 3


def test_profile_preserves_distinct_bins_for_a_narrow_decimal_range() -> None:
    snapshot, observations, quality = evidence(
        ("10", "10.000000000000000000000000000000001")
    )

    result = calculate_volume_profile(
        snapshot=snapshot,
        observations=observations,
        quality=quality,
        bin_count=500,
    )

    assert len(result.bins) == 500
    assert result.bins[0].assigned_volume == Decimal(1)
    assert result.bins[-1].assigned_volume == Decimal(1)
    assert result.poc_bin_index == 0
    assert all(
        lower.upper_bound == upper.lower_bound
        for lower, upper in zip(result.bins, result.bins[1:])
    )


def test_profile_poc_ties_choose_lower_bin_and_value_area_ties_expand_lower_first() -> (
    None
):
    snapshot, observations, quality = evidence(("10", "20", "30", "40", "50"))
    observations = with_volumes(observations, ("2", "3", "10", "1", "2"))

    result = calculate_volume_profile(
        snapshot=snapshot,
        observations=observations,
        quality=quality,
        bin_count=4,
    )
    tied_snapshot, tied_observations, tied_quality = evidence(("10", "50"))
    tied_observations = with_volumes(tied_observations, ("5", "5"))
    tied = calculate_volume_profile(
        snapshot=tied_snapshot,
        observations=tied_observations,
        quality=tied_quality,
        bin_count=4,
    )

    assert result.poc_bin_index == 2
    assert result.value_area_bin_indices == (1, 2)
    assert result.value_area_low == Decimal(20)
    assert result.value_area_high == Decimal(40)
    assert result.value_area_volume == Decimal(13)
    with localcontext() as context:
        context.prec = 34
        assert result.value_area_share == Decimal(13) / Decimal(18)
    assert tied.poc_bin_index == 0


def test_profile_zero_width_and_zero_total_volume_are_distinct() -> None:
    snapshot, observations, quality = evidence(("10", "10", "10"))
    same_price = calculate_volume_profile(
        snapshot=snapshot,
        observations=observations,
        quality=quality,
    )
    zero_observations = with_volumes(observations, ("0", "0", "0"))
    zero_volume = calculate_volume_profile(
        snapshot=snapshot,
        observations=zero_observations,
        quality=quality,
    )

    assert len(same_price.bins) == 1
    assert same_price.bins[0].lower_bound == same_price.bins[0].upper_bound
    assert same_price.poc_bin_index == 0
    assert same_price.value_area_share == Decimal(1)
    assert zero_volume.status is VolumeProfileStatus.UNDEFINED
    assert zero_volume.reason is VolumeProfileReason.ZERO_TOTAL_VOLUME
    assert zero_volume.poc_bin_index is None
    assert zero_volume.value_area_bin_indices == ()
    assert zero_volume.value_area_low is None
    assert zero_volume.value_area_high is None
    assert zero_volume.value_area_share is None
    assert zero_volume.high_volume_node_bin_indices == ()
    assert zero_volume.low_volume_node_bin_indices == ()


def test_profile_nodes_are_strict_interior_extrema_only() -> None:
    snapshot, observations, quality = evidence(("10", "20", "30", "40", "50", "60"))
    observations = with_volumes(observations, ("1", "3", "1", "0", "2", "2"))

    result = calculate_volume_profile(
        snapshot=snapshot,
        observations=observations,
        quality=quality,
        bin_count=5,
    )

    assert tuple(item.assigned_volume for item in result.bins) == (
        Decimal(1),
        Decimal(3),
        Decimal(1),
        Decimal(0),
        Decimal(4),
    )
    assert result.high_volume_node_bin_indices == (1,)
    assert result.low_volume_node_bin_indices == (3,)

    plateau_snapshot, plateau_observations, plateau_quality = evidence(
        ("10", "20", "30", "40")
    )
    plateau_observations = with_volumes(plateau_observations, ("1", "3", "3", "1"))
    plateau = calculate_volume_profile(
        snapshot=plateau_snapshot,
        observations=plateau_observations,
        quality=plateau_quality,
        bin_count=4,
    )
    assert plateau.high_volume_node_bin_indices == ()
    assert plateau.low_volume_node_bin_indices == ()


def test_profile_defaults_parameters_versions_and_repeatability() -> None:
    snapshot, observations, quality = evidence(("10", "20", "30"))
    with localcontext() as context:
        context.prec = 6
        result = calculate_volume_profile(
            snapshot=snapshot,
            observations=observations,
            quality=quality,
        )
        repeated = calculate_volume_profile(
            snapshot=snapshot,
            observations=observations,
            quality=quality,
        )
    vwap = calculate_vwap(
        snapshot=snapshot,
        observations=observations,
        quality=quality,
    )

    assert result == repeated
    assert result.parameters == (("bin-count", 24), ("value-area-percent", 70))
    assert result.metadata_version == "1"
    assert result.calculation_version == "candle-assigned-volume-profile-proxy-v1"
    assert result.method_label == "candle-assigned volume-profile proxy"
    assert result.timeframe == "1m"
    assert result.instrument_id == snapshot.instrument_id
    assert result.venue_id == snapshot.venue_id
    assert result.snapshot_id == snapshot.snapshot_id
    assert result.quality_report_id == quality.report_id
    assert result.as_of == snapshot.as_of
    assert result.window_start == observations[0].event_time
    assert result.window_end == snapshot.as_of
    assert result.price_unit == "USDT"
    assert result.volume_unit == "BTC"
    assert result.input_market_data_ids == snapshot.market_data_ids
    assert vwap.parameters == ()
    assert vwap.metadata_version == "1"
    assert vwap.calculation_version == "bar-typical-price-cumulative-v1"
    assert vwap.method_label == "bar-based typical-price VWAP"
    for indicator_id in ("vwap", "volume-profile"):
        metadata = SPOT_RESEARCH_INDICATORS.get(indicator_id, "1")
        assert not metadata.evidence_independent
        assert metadata.evidence_dependencies


def test_invalid_parameters_timeframes_and_metadata_versions_fail_explicitly() -> None:
    snapshot, observations, quality = evidence()
    for bin_count in (0, 501, True):
        with pytest.raises(VolumeAnalysisError):
            calculate_volume_profile(
                snapshot=snapshot,
                observations=observations,
                quality=quality,
                bin_count=bin_count,
            )
    for value_area_percent in (49, 101, True):
        with pytest.raises(VolumeAnalysisError):
            calculate_volume_profile(
                snapshot=snapshot,
                observations=observations,
                quality=quality,
                value_area_percent=value_area_percent,
            )
    with pytest.raises(VolumeAnalysisError, match="metadata"):
        calculate_vwap(
            snapshot=snapshot,
            observations=observations,
            quality=quality,
            metadata_version="unknown",
        )
    with pytest.raises(VolumeAnalysisError, match="timeframe"):
        calculate_volume_profile(
            snapshot=snapshot,
            observations=observations,
            quality=quality,
            timeframe="2m",
        )


def test_invalid_quality_identity_and_cutoff_fail_closed() -> None:
    snapshot, observations, quality = evidence()
    bad_snapshot = replace(snapshot, snapshot_id=uuid4())
    bad_ids = replace(
        snapshot,
        market_data_ids=(uuid4(),) + snapshot.market_data_ids[1:],
    )
    for supplied_snapshot, supplied_quality in (
        (snapshot, replace(quality, status=DataQualityStatus.DEGRADED)),
        (snapshot, replace(quality, snapshot_id=uuid4())),
        (snapshot, replace(quality, required_data_cutoff=snapshot.as_of - STEP)),
        (bad_snapshot, quality),
        (bad_ids, replace(quality, snapshot_id=bad_ids.snapshot_id)),
    ):
        with pytest.raises(VolumeAnalysisError):
            calculate_vwap(
                snapshot=supplied_snapshot,
                observations=observations,
                quality=supplied_quality,
            )


def test_order_gaps_open_unavailable_ohlc_and_unit_errors_fail_closed() -> None:
    snapshot, observations, quality = evidence(("10", "20", "30", "40", "50"))
    reversed_rows = tuple(reversed(observations))
    duplicate_rows = observations[:2] + (observations[1],) + observations[3:]
    unavailable = observations[:-1] + (
        replace(
            observations[-1],
            availability_time=snapshot.as_of + STEP,
        ),
    )
    broken_ohlc = (
        observations[:2]
        + (
            replace(
                observations[2],
                metrics=tuple(
                    replace(metric, value=Decimal("1"))
                    if metric.metric_name == "high"
                    else metric
                    for metric in observations[2].metrics
                ),
            ),
        )
        + observations[3:]
    )
    missing_volume = (
        observations[:2]
        + (
            replace(
                observations[2],
                metrics=tuple(
                    metric
                    for metric in observations[2].metrics
                    if metric.metric_name != "volume"
                ),
            ),
        )
        + observations[3:]
    )
    negative_volume = with_volumes(observations, ("1", "1", "-1", "1", "1"))
    mixed_volume_units = (
        observations[:2]
        + (
            replace(
                observations[2],
                metrics=tuple(
                    replace(metric, unit="ETH")
                    if metric.metric_name == "volume"
                    else metric
                    for metric in observations[2].metrics
                ),
            ),
        )
        + observations[3:]
    )
    inconsistent_price_units = (
        observations[:2]
        + (
            replace(
                observations[2],
                metrics=tuple(
                    replace(metric, unit="USD")
                    if metric.metric_name == "close"
                    else metric
                    for metric in observations[2].metrics
                ),
            ),
        )
        + observations[3:]
    )
    mismatched_instrument = (
        observations[:2]
        + (replace(observations[2], instrument_id="ETH-USDT-SPOT"),)
        + observations[3:]
    )
    mismatched_venue = (
        observations[:2]
        + (replace(observations[2], venue_id="OTHER-SPOT"),)
        + observations[3:]
    )
    mismatched_source = (
        observations[:2]
        + (replace(observations[2], source_record_id=uuid4()),)
        + observations[3:]
    )
    gapped = tuple(
        replace(
            candle,
            event_time=candle.event_time + timedelta(minutes=1)
            if index
            else candle.event_time,
            provider_time=candle.provider_time + timedelta(minutes=1)
            if index
            else candle.provider_time,
            ingestion_time=candle.ingestion_time + timedelta(minutes=1)
            if index
            else candle.ingestion_time,
            availability_time=candle.availability_time + timedelta(minutes=1)
            if index
            else candle.availability_time,
        )
        for index, candle in enumerate(observations)
    )
    later_snapshot = replace(
        snapshot,
        as_of=snapshot.as_of + STEP,
        created_at=snapshot.created_at + STEP,
    )
    later_quality = replace(
        quality,
        assessed_at=later_snapshot.as_of,
        required_data_cutoff=later_snapshot.as_of,
    )
    open_snapshot = replace(snapshot, as_of=snapshot.as_of - STEP)
    open_quality = replace(
        quality,
        assessed_at=open_snapshot.as_of,
        required_data_cutoff=open_snapshot.as_of,
    )

    invalid_inputs = (
        (snapshot, reversed_rows, quality),
        (snapshot, duplicate_rows, quality),
        (later_snapshot, gapped, later_quality),
        (snapshot, unavailable, quality),
        (snapshot, broken_ohlc, quality),
        (snapshot, missing_volume, quality),
        (snapshot, negative_volume, quality),
        (snapshot, mixed_volume_units, quality),
        (snapshot, inconsistent_price_units, quality),
        (snapshot, mismatched_instrument, quality),
        (snapshot, mismatched_venue, quality),
        (snapshot, mismatched_source, quality),
        (open_snapshot, observations, open_quality),
    )
    for supplied_snapshot, supplied_rows, supplied_quality in invalid_inputs:
        with pytest.raises(VolumeAnalysisError):
            calculate_volume_profile(
                snapshot=supplied_snapshot,
                observations=supplied_rows,
                quality=supplied_quality,
            )


def test_observation_limit_is_enforced() -> None:
    source_id = uuid4()
    base_observation = evidence(("10",))[1][0]
    start = base_observation.event_time
    observations = tuple(
        MarketData(
            market_data_id=uuid4(),
            instrument_id="BTC-USDT-SPOT",
            venue_id="BINANCE-SPOT",
            observation_type="OHLCV",
            event_time=start + index * STEP,
            provider_time=start + index * STEP,
            ingestion_time=start + (index + 1) * STEP,
            availability_time=start + (index + 1) * STEP,
            source_record_id=source_id,
            metrics=base_observation.metrics,
        )
        for index in range(10001)
    )
    cutoff = start + len(observations) * STEP
    snapshot = MarketSnapshot(
        snapshot_id=uuid4(),
        as_of=cutoff,
        created_at=cutoff,
        instrument_id="BTC-USDT-SPOT",
        venue_id="BINANCE-SPOT",
        market_data_ids=tuple(item.market_data_id for item in observations),
        source_record_ids=(source_id,),
    )
    _, _, quality = evidence(("10",))
    quality = replace(
        quality,
        snapshot_id=snapshot.snapshot_id,
        assessed_at=cutoff,
        required_data_cutoff=cutoff,
    )

    with pytest.raises(VolumeAnalysisError, match="bounded"):
        calculate_vwap(
            snapshot=snapshot,
            observations=observations,
            quality=quality,
        )


def test_results_use_requested_non_default_profile_parameters() -> None:
    snapshot, observations, quality = evidence(("10", "20", "30"))
    result = calculate_volume_profile(
        snapshot=snapshot,
        observations=observations,
        quality=quality,
        bin_count=3,
        value_area_percent=80,
        timeframe="1m",
    )

    assert result.parameters == (("bin-count", 3), ("value-area-percent", 80))
    assert len(result.bins) == 3
