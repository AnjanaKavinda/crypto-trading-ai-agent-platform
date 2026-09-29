"""Deterministic moving averages on already validated closed Spot candles."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from enum import StrEnum
from uuid import UUID

from trading_platform_api.analysis.indicator_registry import (
    SPOT_RESEARCH_INDICATORS,
    IndicatorPhase,
)
from trading_platform_api.market_data.contracts import (
    DataQualityReport,
    DataQualityStatus,
    MarketData,
    MarketSnapshot,
)

_INTERVALS = {"1m": 60, "5m": 300, "15m": 900, "1h": 3600, "4h": 14400, "1d": 86400}


class MovingAverageError(ValueError):
    """A moving average cannot be computed from the supplied evidence."""


class MovingAverageKind(StrEnum):
    SMA = "sma"
    EMA = "ema"
    WMA = "wma"


@dataclass(frozen=True, slots=True)
class MovingAveragePoint:
    candle_end: datetime
    value: Decimal | None


@dataclass(frozen=True, slots=True)
class MovingAverageSeries:
    indicator_id: str
    metadata_version: str
    calculation_version: str
    period: int
    timeframe: str
    instrument_id: str
    venue_id: str
    snapshot_id: UUID
    quality_report_id: UUID
    as_of: datetime
    price_unit: str
    input_market_data_ids: tuple[UUID, ...]
    points: tuple[MovingAveragePoint, ...]


def _closes(
    snapshot: MarketSnapshot,
    observations: tuple[MarketData, ...],
    quality: DataQualityReport,
    timeframe: str,
) -> tuple[tuple[Decimal, ...], str]:
    if timeframe not in _INTERVALS:
        raise MovingAverageError("Unsupported candle timeframe.")
    if (
        quality.snapshot_id != snapshot.snapshot_id
        or quality.status is not DataQualityStatus.VALID
    ):
        raise MovingAverageError("Matching VALID C-003 quality evidence is required.")
    if (
        quality.required_data_cutoff != snapshot.as_of
        or quality.assessed_at < snapshot.as_of
    ):
        raise MovingAverageError("Quality cutoff must match the snapshot as-of time.")
    if not observations or len(observations) > 10000:
        raise MovingAverageError("A bounded nonempty observation series is required.")
    if tuple(item.market_data_id for item in observations) != snapshot.market_data_ids:
        raise MovingAverageError(
            "Observation order and identity must match the snapshot."
        )
    interval = timedelta(seconds=_INTERVALS[timeframe])
    prices: list[Decimal] = []
    unit: str | None = None
    previous_start: datetime | None = None
    for item in observations:
        if (
            item.instrument_id != snapshot.instrument_id
            or item.venue_id != snapshot.venue_id
            or item.observation_type != "OHLCV"
            or item.source_record_id not in snapshot.source_record_ids
        ):
            raise MovingAverageError(
                "Observation identity or provenance does not match."
            )
        if (
            item.availability_time > snapshot.as_of
            or item.ingestion_time > snapshot.as_of
        ):
            raise MovingAverageError("Observation was unavailable at the cutoff.")
        if previous_start is not None and item.event_time - previous_start != interval:
            raise MovingAverageError("Candles must be ordered and contiguous.")
        if item.event_time.tzinfo is None or item.event_time.utcoffset() is None:
            raise MovingAverageError("Candle time must be timezone-aware.")
        if item.event_time.astimezone(UTC).timestamp() % _INTERVALS[timeframe] != 0:
            raise MovingAverageError("Candle time is not aligned to its timeframe.")
        if item.event_time + interval > snapshot.as_of:
            raise MovingAverageError("A candle is not closed by the cutoff.")
        metrics = {metric.metric_name: metric for metric in item.metrics}
        if not all(
            name in metrics for name in ("open", "high", "low", "close", "volume")
        ):
            raise MovingAverageError("Required closed OHLCV metrics are absent.")
        close = metrics["close"]
        if (
            close.value <= 0
            or (unit is not None and close.unit != unit)
            or any(metrics[name].unit != close.unit for name in ("open", "high", "low"))
        ):
            raise MovingAverageError("Price or price unit is invalid/inconsistent.")
        unit = close.unit
        prices.append(close.value)
        previous_start = item.event_time
    # A real provider snapshot is timestamped at retrieval, which may be later
    # than the last closed candle. C-003 owns the explicit freshness policy.
    assert unit is not None
    return tuple(prices), unit


def calculate_moving_average(
    *,
    snapshot: MarketSnapshot,
    observations: tuple[MarketData, ...],
    quality: DataQualityReport,
    kind: MovingAverageKind,
    period: int,
    timeframe: str,
) -> MovingAverageSeries:
    """SMA trailing mean; EMA SMA seed and alpha 2/(N+1); WMA oldest=1..newest=N.

    Warm-up points are None. No quantization or strategy threshold is applied.
    The caller must obtain C-003 from the reviewed quality assessor, not invent it.
    """
    if not isinstance(kind, MovingAverageKind):
        raise MovingAverageError("Unknown moving-average kind.")
    metadata = SPOT_RESEARCH_INDICATORS.get(kind.value, "1")
    bounds = metadata.parameters[0]
    if type(period) is not int or not bounds.minimum <= period <= bounds.maximum:
        raise MovingAverageError("Period is outside the registered bounds.")
    if (
        metadata.phase is not IndicatorPhase.VALIDATED
        or timeframe not in metadata.timeframes
    ):
        raise MovingAverageError("Indicator is not validated for this timeframe.")
    closes, unit = _closes(snapshot, observations, quality, timeframe)
    if len(closes) < period:
        values: list[Decimal | None] = [None] * len(closes)
    else:
        values = [None] * (period - 1)
        divisor = Decimal(period)
        seed = sum(closes[:period], Decimal(0)) / divisor
        if kind is MovingAverageKind.EMA:
            values.append(seed)
            alpha = Decimal(2) / Decimal(period + 1)
            previous = seed
            for close in closes[period:]:
                previous = alpha * close + (Decimal(1) - alpha) * previous
                values.append(previous)
        elif kind is MovingAverageKind.SMA:
            running = sum(closes[:period], Decimal(0))
            values.append(running / divisor)
            for index in range(period, len(closes)):
                running += closes[index] - closes[index - period]
                values.append(running / divisor)
        else:
            weight_sum = Decimal(period * (period + 1) // 2)
            for end in range(period, len(closes) + 1):
                values.append(
                    sum(
                        (
                            Decimal(weight) * close
                            for weight, close in enumerate(
                                closes[end - period : end], start=1
                            )
                        ),
                        Decimal(0),
                    )
                    / weight_sum
                )
    interval = timedelta(seconds=_INTERVALS[timeframe])
    return MovingAverageSeries(
        indicator_id=kind.value,
        metadata_version=metadata.metadata_version,
        calculation_version=metadata.calculation_version,
        period=period,
        timeframe=timeframe,
        instrument_id=snapshot.instrument_id,
        venue_id=snapshot.venue_id,
        snapshot_id=snapshot.snapshot_id,
        quality_report_id=quality.report_id,
        as_of=snapshot.as_of,
        price_unit=unit,
        input_market_data_ids=snapshot.market_data_ids,
        points=tuple(
            MovingAveragePoint(item.event_time + interval, value)
            for item, value in zip(observations, values, strict=True)
        ),
    )
