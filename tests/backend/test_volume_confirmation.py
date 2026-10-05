from dataclasses import replace
from decimal import Decimal
from uuid import uuid4

import pytest
from test_moving_averages import evidence
from trading_platform_api.analysis import (
    CandidateBreakoutDirection,
    CandidateBreakoutEvent,
    VolumeAnalysisError,
    VolumeConfirmationPointReason,
    VolumeConfirmationPointStatus,
    VolumeConfirmationPolicy,
    VolumeEventAssessmentReason,
    VolumeEventAssessmentStatus,
    calculate_volume_confirmation,
)
from trading_platform_api.market_data.contracts import (
    DataQualityStatus,
    MarketData,
)


def with_volumes(
    observations: tuple[MarketData, ...], values: tuple[str, ...]
) -> tuple[MarketData, ...]:
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


def policy(threshold: str = "4") -> VolumeConfirmationPolicy:
    return VolumeConfirmationPolicy(
        policy_id="test-policy",
        version="v1",
        minimum_relative_volume=Decimal(threshold),
    )


def event(
    observations: tuple[MarketData, ...],
    *,
    direction: CandidateBreakoutDirection = CandidateBreakoutDirection.UP,
    level: str = "11",
) -> CandidateBreakoutEvent:
    return CandidateBreakoutEvent(
        market_data_id=observations[2].market_data_id,
        direction=direction,
        reference_context_id="caller-defined-level-1",
        reference_level=Decimal(level),
        reference_unit="USDT",
    )


def calculate(
    snapshot,
    observations: tuple[MarketData, ...],
    quality,
    **kwargs,
):
    return calculate_volume_confirmation(
        snapshot=snapshot,
        observations=observations,
        quality=quality,
        lookback=2,
        timeframe="1m",
        **kwargs,
    )


def test_hand_calculated_volume_mean_relative_volume_and_current_exclusion() -> None:
    snapshot, observations, quality = evidence(("10", "11", "12", "13"))
    observations = with_volumes(observations, ("0", "2", "4", "6"))

    result = calculate(snapshot, observations, quality)

    assert tuple(item.raw_volume for item in result.points) == tuple(
        map(Decimal, ("0", "2", "4", "6"))
    )
    assert tuple(item.trailing_average for item in result.points) == (
        None,
        None,
        Decimal(1),
        Decimal(3),
    )
    assert tuple(item.relative_volume for item in result.points) == (
        None,
        None,
        Decimal(4),
        Decimal(2),
    )
    assert tuple(item.reason for item in result.points[:2]) == (
        VolumeConfirmationPointReason.INSUFFICIENT_PRIOR_CANDLES,
    ) * 2
    assert all(
        item.status is VolumeConfirmationPointStatus.READY for item in result.points[2:]
    )
    assert result.input_market_data_ids == snapshot.market_data_ids


def test_zero_volume_is_valid_and_zero_baseline_is_explicitly_unavailable() -> None:
    snapshot, observations, quality = evidence(("10", "11", "12", "13"))
    observations = with_volumes(observations, ("2", "4", "0", "5"))
    result = calculate(snapshot, observations, quality)
    assert result.points[2].relative_volume == 0
    assert result.points[2].status is VolumeConfirmationPointStatus.READY

    zero_snapshot, zero_observations, zero_quality = evidence(("10", "11", "12"))
    zero_observations = with_volumes(zero_observations, ("0", "0", "5"))
    zero_result = calculate(zero_snapshot, zero_observations, zero_quality)
    assert zero_result.points[2].trailing_average == 0
    assert zero_result.points[2].relative_volume is None
    assert (
        zero_result.points[2].reason
        is VolumeConfirmationPointReason.ZERO_PRIOR_VOLUME_BASELINE
    )


@pytest.mark.parametrize("lookback", [1, 501, True])
def test_lookback_bounds_are_enforced(lookback: int) -> None:
    snapshot, observations, quality = evidence(("10", "11", "12"))
    with pytest.raises(VolumeAnalysisError, match="parameters or timeframe"):
        calculate_volume_confirmation(
            snapshot=snapshot,
            observations=observations,
            quality=quality,
            lookback=lookback,
            timeframe="1m",
        )


def test_versioned_policy_supports_breakout_and_breakdown_at_threshold() -> None:
    snapshot, observations, quality = evidence(("10", "11", "12", "13"))
    observations = with_volumes(observations, ("0", "2", "4", "6"))
    breakout = calculate(
        snapshot,
        observations,
        quality,
        candidate_event=event(observations),
        policy=policy("4"),
    )
    assert breakout.assessment.status is VolumeEventAssessmentStatus.SUPPORTING
    assert breakout.assessment.reason is None
    assert breakout.assessment.relative_volume == Decimal(4)
    assert breakout.assessment.minimum_relative_volume == Decimal(4)
    assert breakout.assessment.policy_id == "test-policy"
    assert breakout.assessment.policy_version == "v1"
    assert breakout.assessment.reference_context_id == "caller-defined-level-1"
    assert breakout.assessment.event_market_data_id == observations[2].market_data_id

    down_snapshot, down_observations, down_quality = evidence(("14", "13", "12", "11"))
    down_observations = with_volumes(down_observations, ("0", "2", "4", "6"))
    breakdown = calculate(
        down_snapshot,
        down_observations,
        down_quality,
        candidate_event=event(
            down_observations,
            direction=CandidateBreakoutDirection.DOWN,
            level="13",
        ),
        policy=policy("4"),
    )
    assert breakdown.assessment.status is VolumeEventAssessmentStatus.SUPPORTING


def test_low_volume_fails_confirmation_and_unobserved_price_event_is_indeterminate() -> None:
    snapshot, observations, quality = evidence(("10", "11", "12"))
    observations = with_volumes(observations, ("0", "2", "4"))
    low_volume = calculate(
        snapshot,
        observations,
        quality,
        candidate_event=event(observations),
        policy=policy("4.0001"),
    )
    assert low_volume.assessment.status is VolumeEventAssessmentStatus.NOT_CONFIRMING

    no_cross = calculate(
        snapshot,
        observations,
        quality,
        candidate_event=event(observations, level="12"),
        policy=policy(),
    )
    assert no_cross.assessment.status is VolumeEventAssessmentStatus.INDETERMINATE
    assert (
        no_cross.assessment.reason
        is VolumeEventAssessmentReason.PRICE_EVENT_NOT_OBSERVED
    )


def test_threshold_assessment_uses_exact_ratio_not_rounded_display_value() -> None:
    snapshot, observations, quality = evidence(("10", "11", "12"))
    observations = with_volumes(observations, ("3", "3", "2"))
    rounded_two_thirds = Decimal("0.6666666666666666666666666666666667")

    result = calculate(
        snapshot,
        observations,
        quality,
        candidate_event=event(observations),
        policy=policy(str(rounded_two_thirds)),
    )

    assert result.points[2].relative_volume == rounded_two_thirds
    assert result.assessment.status is VolumeEventAssessmentStatus.NOT_CONFIRMING


def test_missing_policy_event_and_insufficient_context_are_indeterminate() -> None:
    snapshot, observations, quality = evidence(("10", "11", "12"))
    observations = with_volumes(observations, ("0", "2", "4"))
    no_context = calculate(snapshot, observations, quality)
    assert no_context.assessment.status is VolumeEventAssessmentStatus.INDETERMINATE
    assert (
        no_context.assessment.reason
        is VolumeEventAssessmentReason.MISSING_EVENT_CONTEXT
    )

    no_policy = calculate(
        snapshot, observations, quality, candidate_event=event(observations)
    )
    assert no_policy.assessment.status is VolumeEventAssessmentStatus.INDETERMINATE
    assert (
        no_policy.assessment.reason
        is VolumeEventAssessmentReason.MISSING_CONFIRMATION_POLICY
    )

    short_event = replace(event(observations), market_data_id=observations[1].market_data_id)
    insufficient = calculate(
        snapshot,
        observations,
        quality,
        candidate_event=short_event,
        policy=policy(),
    )
    assert insufficient.assessment.status is VolumeEventAssessmentStatus.INDETERMINATE
    assert (
        insufficient.assessment.reason
        is VolumeEventAssessmentReason.INSUFFICIENT_PRIOR_CANDLES
    )

    missing_candle = replace(event(observations), market_data_id=uuid4())
    missing = calculate(
        snapshot,
        observations,
        quality,
        candidate_event=missing_candle,
        policy=policy(),
    )
    assert missing.assessment.status is VolumeEventAssessmentStatus.INDETERMINATE
    assert (
        missing.assessment.reason
        is VolumeEventAssessmentReason.CANDIDATE_CANDLE_NOT_IN_SERIES
    )


def test_zero_baseline_candidate_is_not_confirmed_or_neutral() -> None:
    snapshot, observations, quality = evidence(("10", "11", "12"))
    observations = with_volumes(observations, ("0", "0", "5"))
    result = calculate(
        snapshot,
        observations,
        quality,
        candidate_event=event(observations),
        policy=policy(),
    )
    assert result.assessment.status is VolumeEventAssessmentStatus.INDETERMINATE
    assert (
        result.assessment.reason
        is VolumeEventAssessmentReason.ZERO_PRIOR_VOLUME_BASELINE
    )


def test_metadata_repeatability_and_correlation_limits_are_preserved() -> None:
    snapshot, observations, quality = evidence(("10", "11", "12"))
    observations = with_volumes(observations, ("0", "2", "4"))
    result = calculate(snapshot, observations, quality)
    assert result == calculate(snapshot, observations, quality)
    assert result.indicator_id == "volume-confirmation"
    assert result.metadata_version == "1"
    assert result.calculation_version == "trailing-prior-volume-mean-relative-v1"
    assert result.lookback == 2
    assert result.timeframe == "1m"
    assert result.quality_report_id == quality.report_id
    assert result.source_record_ids == snapshot.source_record_ids
    assert "correlated" in result.limitations[1]
    assert "comparison/pivot" in result.limitations[2]
    assert "order-flow" in result.limitations[3]


def test_invalid_quality_order_units_and_volume_fail_closed() -> None:
    snapshot, observations, quality = evidence(("10", "11", "12"))
    with pytest.raises(VolumeAnalysisError, match="VALID"):
        calculate(
            snapshot,
            observations,
            replace(quality, status=DataQualityStatus.DEGRADED),
        )
    with pytest.raises(VolumeAnalysisError, match="VALID"):
        calculate(snapshot, observations, replace(quality, status=DataQualityStatus.STALE))
    with pytest.raises(VolumeAnalysisError, match="order and identity"):
        calculate(snapshot, tuple(reversed(observations)), quality)

    wrong_source = replace(observations[0], source_record_id=uuid4())
    with pytest.raises(VolumeAnalysisError, match="provenance"):
        calculate(snapshot, (wrong_source, *observations[1:]), quality)

    gap_time = observations[1].event_time.replace(second=1)
    gap = replace(
        observations[1],
        event_time=gap_time,
        provider_time=gap_time,
        ingestion_time=gap_time + (observations[1].ingestion_time - observations[1].event_time),
        availability_time=gap_time
        + (observations[1].availability_time - observations[1].event_time),
    )
    with pytest.raises(VolumeAnalysisError, match="contiguous"):
        calculate(snapshot, (observations[0], gap, observations[2]), quality)

    unavailable = replace(
        observations[2],
        availability_time=snapshot.as_of.replace(minute=snapshot.as_of.minute + 1),
    )
    with pytest.raises(VolumeAnalysisError, match="unavailable"):
        calculate(snapshot, (observations[0], observations[1], unavailable), quality)

    inconsistent_ohlc = replace(
        observations[2],
        metrics=tuple(
            replace(metric, value=Decimal(1))
            if metric.metric_name == "high"
            else metric
            for metric in observations[2].metrics
        ),
    )
    with pytest.raises(VolumeAnalysisError, match="inconsistent"):
        calculate(snapshot, (*observations[:2], inconsistent_ohlc), quality)

    mismatched_price_unit = replace(
        observations[2],
        metrics=tuple(
            replace(metric, unit="BTC")
            if metric.metric_name == "close"
            else metric
            for metric in observations[2].metrics
        ),
    )
    with pytest.raises(VolumeAnalysisError, match="price units"):
        calculate(snapshot, (*observations[:2], mismatched_price_unit), quality)

    mismatched_volume_unit = tuple(
        replace(
            candle,
            metrics=tuple(
                replace(metric, unit="lots")
                if metric.metric_name == "volume"
                else metric
                for metric in candle.metrics
            ),
        )
        if index == 1
        else candle
        for index, candle in enumerate(observations)
    )
    with pytest.raises(VolumeAnalysisError, match="Volume units"):
        calculate(snapshot, mismatched_volume_unit, quality)

    missing_volume = replace(
        observations[0],
        metrics=tuple(
            metric for metric in observations[0].metrics if metric.metric_name != "volume"
        ),
    )
    with pytest.raises(VolumeAnalysisError, match="Required unique"):
        calculate(snapshot, (missing_volume, *observations[1:]), quality)

    negative_volume = replace(
        observations[0],
        metrics=tuple(
            replace(metric, value=Decimal(-1))
            if metric.metric_name == "volume"
            else metric
            for metric in observations[0].metrics
        ),
    )
    with pytest.raises(VolumeAnalysisError, match="nonnegative"):
        calculate(snapshot, (negative_volume, *observations[1:]), quality)

    shifted = tuple(
        replace(
            candle,
            event_time=candle.event_time.replace(minute=candle.event_time.minute + 1),
            provider_time=candle.provider_time.replace(
                minute=candle.provider_time.minute + 1
            ),
        )
        for candle in observations
    )
    with pytest.raises(VolumeAnalysisError, match="not closed"):
        calculate(snapshot, shifted, quality)

    bad_reference = event(observations)
    with pytest.raises(VolumeAnalysisError, match="unit"):
        calculate(
            snapshot,
            observations,
            quality,
            candidate_event=replace(bad_reference, reference_unit="BTC"),
            policy=policy(),
        )


def test_series_size_limit_rejects_oversized_input() -> None:
    snapshot, observations, quality = evidence(("10",) * 10001)
    with pytest.raises(VolumeAnalysisError, match="bounded"):
        calculate(snapshot, observations, quality)
