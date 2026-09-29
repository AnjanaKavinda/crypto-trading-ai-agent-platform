import asyncio
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import httpx
import pytest
from test_binance_spot_adapter import NOW, OPEN, candle, metadata, request, settings
from test_data_failure_gate import _policy
from trading_platform_api.analysis.moving_averages import (
    MovingAverageError,
    MovingAverageKind,
    calculate_moving_average,
)
from trading_platform_api.market_data import assess_complete_binance_spot_batch
from trading_platform_api.market_data.binance_spot import BinanceSpotProvider
from trading_platform_api.market_data.contracts import (
    DataQualityReport,
    DataQualityStatus,
    MarketData,
    MarketSnapshot,
    MetricValue,
)

START = datetime(2026, 1, 1, tzinfo=UTC)
STEP = timedelta(minutes=1)


def evidence(
    closes: tuple[str, ...] = ("10", "11", "12", "13", "14"),
) -> tuple[MarketSnapshot, tuple[MarketData, ...], DataQualityReport]:
    source_id = uuid4()
    observations = tuple(
        MarketData(
            market_data_id=uuid4(),
            instrument_id="BTC-USDT-SPOT",
            venue_id="BINANCE-SPOT",
            observation_type="OHLCV",
            event_time=START + index * STEP,
            provider_time=START + index * STEP,
            ingestion_time=START + (index + 1) * STEP,
            availability_time=START + (index + 1) * STEP,
            source_record_id=source_id,
            metrics=(
                MetricValue("open", Decimal(close), "USDT"),
                MetricValue("high", Decimal(close) + 1, "USDT"),
                MetricValue("low", Decimal(close) - 1, "USDT"),
                MetricValue("close", Decimal(close), "USDT"),
                MetricValue("volume", Decimal(1), "BTC"),
            ),
        )
        for index, close in enumerate(closes)
    )
    cutoff = START + len(closes) * STEP
    snapshot = MarketSnapshot(
        snapshot_id=uuid4(),
        as_of=cutoff,
        created_at=cutoff,
        instrument_id="BTC-USDT-SPOT",
        venue_id="BINANCE-SPOT",
        market_data_ids=tuple(item.market_data_id for item in observations),
        source_record_ids=(source_id,),
    )
    quality = DataQualityReport(
        report_id=uuid4(),
        snapshot_id=snapshot.snapshot_id,
        assessed_at=cutoff,
        required_data_cutoff=cutoff,
        completeness=Decimal(1),
        freshness=Decimal(1),
        accuracy=Decimal(1),
        consistency=Decimal(1),
        source_reliability=Decimal(1),
        coverage=Decimal(1),
        continuity=Decimal(1),
        status=DataQualityStatus.VALID,
    )
    return snapshot, observations, quality


def run(
    kind: MovingAverageKind,
    period: int,
    *,
    snapshot: MarketSnapshot | None = None,
    observations: tuple[MarketData, ...] | None = None,
    quality: DataQualityReport | None = None,
):
    default_snapshot, default_observations, default_quality = evidence()
    return calculate_moving_average(
        snapshot=snapshot or default_snapshot,
        observations=observations or default_observations,
        quality=quality or default_quality,
        kind=kind,
        period=period,
        timeframe="1m",
    )


def test_hand_computed_sma_ema_wma_and_exact_provenance() -> None:
    snapshot, observations, quality = evidence()
    args = dict(snapshot=snapshot, observations=observations, quality=quality)
    sma = run(MovingAverageKind.SMA, 3, **args)
    ema = run(MovingAverageKind.EMA, 3, **args)
    wma = run(MovingAverageKind.WMA, 3, **args)
    assert tuple(point.value for point in sma.points) == (
        None,
        None,
        Decimal(11),
        Decimal(12),
        Decimal(13),
    )
    assert tuple(point.value for point in ema.points) == (
        None,
        None,
        Decimal(11),
        Decimal(12),
        Decimal(13),
    )
    assert tuple(point.value for point in wma.points)[2] == Decimal(68) / Decimal(6)
    assert wma.points[-1].value == Decimal(80) / Decimal(6)
    assert sma.points[-1].candle_end == snapshot.as_of
    assert sma.snapshot_id == snapshot.snapshot_id
    assert sma.quality_report_id == quality.report_id
    assert sma.input_market_data_ids == snapshot.market_data_ids
    assert sma.calculation_version == "sma-close-v1"
    assert ema.calculation_version == "ema-sma-seed-v1"


def test_ema_uses_seed_once_and_does_not_round_intermediate_values() -> None:
    snapshot, observations, quality = evidence(("2", "3", "5", "6", "9"))
    values = run(
        MovingAverageKind.EMA,
        3,
        snapshot=snapshot,
        observations=observations,
        quality=quality,
    ).points
    assert values[0].value is None and values[1].value is None
    assert values[2].value == Decimal(10) / Decimal(3)
    assert values[3].value == (Decimal(10) / Decimal(3) + Decimal(6)) / 2
    assert values[4].value is not None and values[3].value is not None
    assert (
        values[4].value
        == Decimal("0.5") * Decimal(9) + Decimal("0.5") * values[3].value
    )


def test_insufficient_warmup_is_unavailable_not_a_number() -> None:
    result = run(MovingAverageKind.SMA, 6)
    assert all(point.value is None for point in result.points)
    assert len(result.points) == 5


def test_real_adapter_to_quality_to_indicator_handoff_uses_retrieval_cutoff() -> None:
    """Offline HTTP fixture through the real Spot adapter; never a live price claim."""

    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path.endswith("exchangeInfo"):
            return httpx.Response(200, json=metadata())
        return httpx.Response(
            200, json=[candle(OPEN + timedelta(minutes=i)) for i in range(3)]
        )

    async def collect():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await BinanceSpotProvider(
                settings(), client=client, clock=lambda: NOW
            ).fetch(
                request(
                    maximum_records=3,
                    range_start=OPEN,
                    range_end=OPEN + timedelta(minutes=3),
                )
            )

    batch = asyncio.run(collect())
    report = assess_complete_binance_spot_batch(batch, _policy(3), assessed_at=NOW)
    assert report.status is DataQualityStatus.VALID
    series = calculate_moving_average(
        snapshot=batch.snapshots[0],
        observations=batch.market_data,
        quality=report,
        kind=MovingAverageKind.EMA,
        period=2,
        timeframe="1m",
    )
    assert series.points[-1].candle_end == OPEN + timedelta(minutes=3)
    assert series.points[-1].candle_end < series.as_of == NOW
    assert series.points[-1].value is not None
    assert series.input_market_data_ids == batch.snapshots[0].market_data_ids


def test_quality_cutoff_identity_and_availability_fail_closed() -> None:
    snapshot, observations, quality = evidence()
    changes = (
        dict(quality=replace(quality, status=DataQualityStatus.STALE)),
        dict(quality=replace(quality, status=DataQualityStatus.DEGRADED)),
        dict(quality=replace(quality, snapshot_id=uuid4())),
        dict(quality=replace(quality, required_data_cutoff=START + STEP)),
        dict(observations=tuple(reversed(observations))),
        dict(
            observations=observations[:-1]
            + (replace(observations[-1], availability_time=snapshot.as_of + STEP),)
        ),
        dict(
            observations=observations[:3]
            + (
                replace(
                    observations[3],
                    event_time=START + 4 * STEP,
                    provider_time=START + 4 * STEP,
                ),
            )
            + observations[4:]
        ),
    )
    for changeset in changes:
        supplied = dict(snapshot=snapshot, observations=observations, quality=quality)
        supplied.update(changeset)
        with pytest.raises(MovingAverageError):
            run(MovingAverageKind.SMA, 3, **supplied)


def test_invalid_period_timeframe_and_price_unit_are_rejected() -> None:
    snapshot, observations, quality = evidence()
    for period in (0, 1, 501, True):
        with pytest.raises(MovingAverageError):
            run(
                MovingAverageKind.SMA,
                period,
                snapshot=snapshot,
                observations=observations,
                quality=quality,
            )
    with pytest.raises(MovingAverageError, match="timeframe"):
        calculate_moving_average(
            snapshot=snapshot,
            observations=observations,
            quality=quality,
            kind=MovingAverageKind.SMA,
            period=3,
            timeframe="2m",
        )
    changed = replace(
        observations[3],
        metrics=tuple(
            replace(metric, unit="USD") if metric.metric_name == "close" else metric
            for metric in observations[3].metrics
        ),
    )
    with pytest.raises(MovingAverageError, match="unit"):
        run(
            MovingAverageKind.SMA,
            3,
            snapshot=snapshot,
            observations=observations[:3] + (changed,) + observations[4:],
            quality=quality,
        )
