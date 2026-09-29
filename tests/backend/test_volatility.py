from dataclasses import replace
from decimal import Decimal

import pytest
from test_moving_averages import evidence
from trading_platform_api.analysis.volatility import (
    BandWidthDirection,
    VolatilityError,
    calculate_atr14,
    calculate_bollinger_bands,
    calculate_realized_volatility,
)
from trading_platform_api.market_data.contracts import DataQualityStatus


def test_atr14_uses_true_range_and_wilder_smoothing_after_14_ranges() -> None:
    snapshot, observations, quality = evidence(tuple(str(100 + i) for i in range(16)))
    result = calculate_atr14(
        snapshot=snapshot,
        observations=observations,
        quality=quality,
        timeframe="1m",
    )
    assert result.metadata_version == "2"
    assert result.calculation_version == "atr-wilder-sma-seed-v1"
    assert all(point.value is None for point in result.points[:14])
    assert result.points[14].value == Decimal(2)
    assert result.points[15].value == Decimal(2)
    assert result.unit == "USDT"
    assert result.input_market_data_ids == snapshot.market_data_ids


def test_bollinger_population_bands_and_expansion_compression_direction() -> None:
    snapshot, observations, quality = evidence(("10", "10", "10", "10", "20", "20"))
    result = calculate_bollinger_bands(
        snapshot=snapshot,
        observations=observations,
        quality=quality,
        period=3,
        timeframe="1m",
    )
    assert all(point.bandwidth is None for point in result.points[:2])
    assert result.points[2].middle == Decimal(10)
    assert result.points[2].upper == result.points[2].lower == Decimal(10)
    assert result.points[3].bandwidth_direction is BandWidthDirection.UNCHANGED
    assert result.points[4].bandwidth_direction is BandWidthDirection.EXPANSION
    assert result.points[5].bandwidth_direction is BandWidthDirection.COMPRESSION
    assert result.standard_deviation_multiplier == Decimal(2)


def test_realized_volatility_is_annualized_close_log_return_sample_deviation() -> None:
    snapshot, observations, quality = evidence(("10", "11", "12", "13", "15"))
    result = calculate_realized_volatility(
        snapshot=snapshot,
        observations=observations,
        quality=quality,
        period=3,
        timeframe="1m",
    )
    assert result.indicator_id == "realized-volatility"
    assert result.unit == "annualized-fraction"
    assert all(point.value is None for point in result.points[:3])
    assert result.points[3].value is not None and result.points[3].value > 0
    assert result.points[-1].value is not None and result.points[-1].value > 0


def test_volatility_rejects_invalid_quality_and_inconsistent_ohlc() -> None:
    snapshot, observations, quality = evidence(tuple(str(100 + i) for i in range(16)))
    with pytest.raises(VolatilityError, match="VALID"):
        calculate_atr14(
            snapshot=snapshot,
            observations=observations,
            quality=replace(quality, status=DataQualityStatus.DEGRADED),
            timeframe="1m",
        )
    broken = replace(
        observations[2],
        metrics=tuple(
            replace(metric, value=Decimal("1"))
            if metric.metric_name == "high"
            else metric
            for metric in observations[2].metrics
        ),
    )
    with pytest.raises(VolatilityError, match="inconsistent"):
        calculate_atr14(
            snapshot=snapshot,
            observations=observations[:2] + (broken,) + observations[3:],
            quality=quality,
            timeframe="1m",
        )


def test_volatility_rejects_unsupported_period_and_timeframe() -> None:
    snapshot, observations, quality = evidence()
    with pytest.raises(VolatilityError, match="validated"):
        calculate_bollinger_bands(
            snapshot=snapshot,
            observations=observations,
            quality=quality,
            period=1,
            timeframe="1m",
        )
    with pytest.raises(VolatilityError, match="timeframe"):
        calculate_realized_volatility(
            snapshot=snapshot,
            observations=observations,
            quality=quality,
            period=3,
            timeframe="2m",
        )
