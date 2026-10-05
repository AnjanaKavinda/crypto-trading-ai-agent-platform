from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal, localcontext
from uuid import uuid4

import pytest
from test_moving_averages import STEP, evidence
from trading_platform_api.analysis.indicator_registry import (
    SPOT_RESEARCH_INDICATORS,
    IndicatorMetadataError,
    IndicatorRegistry,
)
from trading_platform_api.analysis.momentum import (
    MomentumError,
    MomentumReason,
    MomentumStatus,
    calculate_cci,
    calculate_macd,
    calculate_rsi,
    calculate_stochastic,
)
from trading_platform_api.market_data.contracts import (
    DataQualityStatus,
    MarketData,
    MarketSnapshot,
    MetricValue,
)


def test_rsi_uses_wilder_sma_seed_and_handles_boundaries() -> None:
    snapshot, observations, quality = evidence(("10", "11", "10", "12", "11", "13"))
    result = calculate_rsi(
        snapshot=snapshot,
        observations=observations,
        quality=quality,
        period=2,
    )
    assert [point.value.status for point in result.points[:2]] == [
        MomentumStatus.WARMUP,
        MomentumStatus.WARMUP,
    ]
    assert result.points[2].value.value == Decimal(50)
    with localcontext() as context:
        context.prec = 34
        assert result.points[3].value.value == Decimal(100) - Decimal(100) / Decimal(6)
    assert result.points[4].value.value == Decimal(50)
    with localcontext() as context:
        context.prec = 34
        assert result.points[-1].value.value == Decimal(100) - (
            Decimal(100) / (Decimal(1) + Decimal("1.3125") / Decimal("0.3125"))
        )
    flat_snapshot, flat_observations, flat_quality = evidence(("7", "7", "7"))
    assert calculate_rsi(
        snapshot=flat_snapshot,
        observations=flat_observations,
        quality=flat_quality,
        period=2,
    ).points[-1].value.value == Decimal(50)

    for closes, expected in ((("3", "4", "5"), 100), (("5", "4", "3"), 0)):
        flat_snapshot, flat_observations, flat_quality = evidence(closes)
        boundary = calculate_rsi(
            snapshot=flat_snapshot,
            observations=flat_observations,
            quality=flat_quality,
            period=2,
        )
        assert boundary.points[-1].value.value == Decimal(expected)


def test_macd_uses_sma_seeded_emas_and_component_warmups() -> None:
    snapshot, observations, quality = evidence(("10", "11", "12", "13", "15"))
    result = calculate_macd(
        snapshot=snapshot,
        observations=observations,
        quality=quality,
        fast_period=2,
        slow_period=3,
        signal_period=2,
    )
    assert all(
        point.line.status is MomentumStatus.WARMUP for point in result.points[:2]
    )
    assert result.points[2].line.value == Decimal("0.5")
    assert result.points[2].signal.reason is MomentumReason.WARMUP
    assert result.points[3].signal.value == Decimal("0.5")
    assert result.points[3].histogram.value == Decimal(0)
    with localcontext() as context:
        context.prec = 34
        assert abs(
            result.points[4].histogram.value - Decimal(1) / Decimal(18)
        ) < Decimal("2e-33")


def test_stochastic_warmup_zero_range_and_trailing_d() -> None:
    snapshot, observations, quality = evidence(("10", "12", "14", "16"))
    result = calculate_stochastic(
        snapshot=snapshot,
        observations=observations,
        quality=quality,
        k_period=2,
        d_period=2,
    )
    assert result.points[0].k.reason is MomentumReason.WARMUP
    assert result.points[1].k.value == Decimal(75)
    assert result.points[1].d.reason is MomentumReason.WARMUP
    assert result.points[2].d.value == Decimal(75)

    flat_snapshot, flat_observations, flat_quality = evidence(("5", "5", "5"))
    flat = tuple(
        replace(
            candle,
            metrics=tuple(
                replace(metric, value=Decimal(5))
                if metric.metric_name in {"open", "high", "low", "close"}
                else metric
                for metric in candle.metrics
            ),
        )
        for candle in flat_observations
    )
    zero_range = calculate_stochastic(
        snapshot=flat_snapshot,
        observations=flat,
        quality=flat_quality,
        k_period=2,
        d_period=2,
    )
    assert zero_range.points[1].k.reason is MomentumReason.ZERO_RANGE
    assert zero_range.points[2].d.reason is MomentumReason.ZERO_RANGE


def test_cci_typical_price_mean_deviation_and_zero_deviation() -> None:
    snapshot, observations, quality = evidence(("10", "11", "12", "13"))
    result = calculate_cci(
        snapshot=snapshot,
        observations=observations,
        quality=quality,
        period=3,
    )
    assert result.points[:2][0].value.reason is MomentumReason.WARMUP
    assert result.points[2].value.value == Decimal(100)

    flat_snapshot, flat_observations, flat_quality = evidence(("5", "5", "5"))
    flat = tuple(
        replace(
            candle,
            metrics=tuple(
                replace(metric, value=Decimal(5))
                if metric.metric_name in {"open", "high", "low", "close"}
                else metric
                for metric in candle.metrics
            ),
        )
        for candle in flat_observations
    )
    zero_deviation = calculate_cci(
        snapshot=flat_snapshot,
        observations=flat,
        quality=flat_quality,
        period=2,
    )
    assert zero_deviation.points[1].value.reason is MomentumReason.ZERO_DEVIATION


def test_results_preserve_lineage_versions_parameters_units_and_repeatability() -> None:
    snapshot, observations, quality = evidence(("10", "11", "13", "17"))
    result = calculate_rsi(
        snapshot=snapshot,
        observations=observations,
        quality=quality,
        period=2,
    )
    with localcontext() as context:
        context.prec = 6
        repeated = calculate_rsi(
            snapshot=snapshot,
            observations=observations,
            quality=quality,
            period=2,
        )
    assert repeated.points == result.points
    assert result.indicator_id == "rsi"
    assert result.metadata_version == "1"
    assert result.calculation_version == "rsi-wilder-sma-seed-v1"
    assert result.parameters == (("period", 2),)
    assert result.timeframe == "1m"
    assert result.instrument_id == snapshot.instrument_id
    assert result.venue_id == snapshot.venue_id
    assert result.snapshot_id == snapshot.snapshot_id
    assert result.quality_report_id == quality.report_id
    assert result.as_of == snapshot.as_of
    assert result.price_unit == "USDT"
    assert result.unit == "percent"
    assert result.input_market_data_ids == snapshot.market_data_ids
    assert result.points[-1].candle_end == snapshot.as_of
    for indicator_id in ("rsi", "macd", "stochastic", "cci"):
        metadata = SPOT_RESEARCH_INDICATORS.get(indicator_id, "1")
        assert not metadata.evidence_independent
        assert "price-derived-momentum-indicators" in metadata.evidence_dependencies
    with pytest.raises(IndicatorMetadataError, match="Duplicate"):
        IndicatorRegistry(
            (
                SPOT_RESEARCH_INDICATORS.get("rsi", "1"),
                SPOT_RESEARCH_INDICATORS.get("rsi", "1"),
            )
        )


def test_invalid_parameters_metadata_and_insufficient_history_fail_or_warm_up() -> None:
    snapshot, observations, quality = evidence(("10", "11"))
    warmup = calculate_rsi(
        snapshot=snapshot,
        observations=observations,
        quality=quality,
        period=14,
    )
    assert all(point.value.reason is MomentumReason.WARMUP for point in warmup.points)
    for period in (True, 1, 501):
        with pytest.raises(MomentumError):
            calculate_rsi(
                snapshot=snapshot,
                observations=observations,
                quality=quality,
                period=period,
            )
    with pytest.raises(MomentumError, match="fast period"):
        calculate_macd(
            snapshot=snapshot,
            observations=observations,
            quality=quality,
            fast_period=3,
            slow_period=3,
        )
    with pytest.raises(MomentumError, match="metadata version"):
        calculate_cci(
            snapshot=snapshot,
            observations=observations,
            quality=quality,
            metadata_version="unknown",
        )
    with pytest.raises(MomentumError):
        calculate_stochastic(
            snapshot=snapshot,
            observations=observations,
            quality=quality,
            timeframe="2m",
        )


def test_invalid_quality_snapshot_order_candles_and_provenance_fail_closed() -> None:
    snapshot, observations, quality = evidence()
    variants = (
        (observations, replace(quality, status=DataQualityStatus.STALE)),
        (observations, replace(quality, snapshot_id=uuid4())),
        (observations, replace(quality, required_data_cutoff=snapshot.as_of - STEP)),
        (tuple(reversed(observations)), quality),
        (
            observations[:-1]
            + (replace(observations[-1], availability_time=snapshot.as_of + STEP),),
            quality,
        ),
        (
            observations[:2]
            + (
                replace(
                    observations[2],
                    event_time=observations[2].event_time + STEP,
                    provider_time=observations[2].provider_time + STEP,
                    ingestion_time=observations[2].ingestion_time + STEP,
                    availability_time=observations[2].availability_time + STEP,
                ),
            )
            + observations[3:],
            quality,
        ),
        (
            observations[:2]
            + (replace(observations[2], instrument_id="ETH-USDT-SPOT"),)
            + observations[3:],
            quality,
        ),
        (
            observations[:2]
            + (replace(observations[2], source_record_id=uuid4()),)
            + observations[3:],
            quality,
        ),
    )
    for supplied, report in variants:
        with pytest.raises(MomentumError):
            calculate_rsi(
                snapshot=snapshot,
                observations=supplied,
                quality=report,
                period=2,
            )

    unsupported_snapshot = replace(snapshot, as_of=snapshot.as_of - STEP)
    open_quality = replace(
        quality,
        assessed_at=unsupported_snapshot.as_of,
        required_data_cutoff=unsupported_snapshot.as_of,
    )
    with pytest.raises(MomentumError):
        calculate_cci(
            snapshot=unsupported_snapshot,
            observations=observations,
            quality=open_quality,
            period=2,
        )


def test_inconsistent_price_volume_units_and_invalid_ohlc_fail_closed() -> None:
    snapshot, observations, quality = evidence()
    modifications = (
        replace(
            observations[2],
            metrics=tuple(
                replace(metric, unit="USD") if metric.metric_name == "close" else metric
                for metric in observations[2].metrics
            ),
        ),
        replace(
            observations[2],
            metrics=tuple(
                replace(metric, value=Decimal("1"))
                if metric.metric_name == "high"
                else metric
                for metric in observations[2].metrics
            ),
        ),
        replace(
            observations[2],
            metrics=tuple(
                replace(metric, unit="ETH")
                if metric.metric_name == "volume"
                else metric
                for metric in observations[2].metrics
            ),
        ),
        replace(
            observations[2],
            metrics=tuple(
                replace(metric, value=Decimal("-1"))
                if metric.metric_name == "volume"
                else metric
                for metric in observations[2].metrics
            ),
        ),
    )
    for modified in modifications:
        supplied = observations[:2] + (modified,) + observations[3:]
        with pytest.raises(MomentumError):
            calculate_stochastic(
                snapshot=snapshot,
                observations=supplied,
                quality=quality,
                k_period=2,
            )


def test_large_observation_sequences_are_rejected() -> None:
    source_id = uuid4()
    observations = tuple(
        MarketData(
            market_data_id=uuid4(),
            instrument_id="BTC-USDT-SPOT",
            venue_id="BINANCE-SPOT",
            observation_type="OHLCV",
            event_time=datetime(2026, 1, 1, tzinfo=UTC) + index * STEP,
            provider_time=datetime(2026, 1, 1, tzinfo=UTC) + index * STEP,
            ingestion_time=datetime(2026, 1, 1, tzinfo=UTC) + (index + 1) * STEP,
            availability_time=datetime(2026, 1, 1, tzinfo=UTC) + (index + 1) * STEP,
            source_record_id=source_id,
            metrics=(
                MetricValue("open", Decimal(10), "USDT"),
                MetricValue("high", Decimal(11), "USDT"),
                MetricValue("low", Decimal(9), "USDT"),
                MetricValue("close", Decimal(10), "USDT"),
                MetricValue("volume", Decimal(1), "BTC"),
            ),
        )
        for index in range(10001)
    )
    cutoff = datetime(2026, 1, 1, tzinfo=UTC) + len(observations) * STEP
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
    with pytest.raises(MomentumError):
        calculate_rsi(
            snapshot=snapshot,
            observations=observations,
            quality=quality,
            period=2,
        )


def test_duplicate_observation_is_rejected_by_each_indicator() -> None:
    snapshot, observations, quality = evidence(("10", "11", "12", "13", "14"))
    duplicated = observations[:2] + (observations[1],) + observations[3:]
    calculations = (
        (
            calculate_rsi,
            {
                "snapshot": snapshot,
                "observations": duplicated,
                "quality": quality,
                "period": 2,
            },
        ),
        (
            calculate_macd,
            {
                "snapshot": snapshot,
                "observations": duplicated,
                "quality": quality,
                "fast_period": 2,
                "slow_period": 3,
                "signal_period": 2,
            },
        ),
        (
            calculate_stochastic,
            {
                "snapshot": snapshot,
                "observations": duplicated,
                "quality": quality,
                "k_period": 2,
                "d_period": 2,
            },
        ),
        (
            calculate_cci,
            {
                "snapshot": snapshot,
                "observations": duplicated,
                "quality": quality,
                "period": 2,
            },
        ),
    )
    for calculate, arguments in calculations:
        with pytest.raises(MomentumError, match="order and identity"):
            calculate(**arguments)


def test_default_parameters_produce_ready_values_for_all_indicators() -> None:
    snapshot, observations, quality = evidence(
        tuple(str(100 + index) for index in range(34))
    )

    rsi = calculate_rsi(snapshot=snapshot, observations=observations, quality=quality)
    assert rsi.parameters == (("period", 14),)
    assert rsi.points[-1].value.status is MomentumStatus.READY

    macd = calculate_macd(snapshot=snapshot, observations=observations, quality=quality)
    assert macd.parameters == (
        ("fast-period", 12),
        ("slow-period", 26),
        ("signal-period", 9),
    )
    assert macd.points[-1].line.status is MomentumStatus.READY
    assert macd.points[-1].signal.status is MomentumStatus.READY
    assert macd.points[-1].histogram.status is MomentumStatus.READY

    stochastic = calculate_stochastic(
        snapshot=snapshot, observations=observations, quality=quality
    )
    assert stochastic.parameters == (("k-period", 14), ("d-period", 3))
    assert stochastic.points[-1].k.status is MomentumStatus.READY
    assert stochastic.points[-1].d.status is MomentumStatus.READY

    cci = calculate_cci(snapshot=snapshot, observations=observations, quality=quality)
    assert cci.parameters == (("period", 20),)
    assert cci.points[-1].value.status is MomentumStatus.READY
