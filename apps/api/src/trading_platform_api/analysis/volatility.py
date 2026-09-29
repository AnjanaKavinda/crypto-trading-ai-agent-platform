"""Deterministic volatility measures over provenance-validated closed Spot OHLCV."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal, localcontext
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
_PERIODS_PER_YEAR = {
    "1m": 525_600,
    "5m": 105_120,
    "15m": 35_040,
    "1h": 8_760,
    "4h": 2_190,
    "1d": 365,
}


class VolatilityError(ValueError):
    """Volatility cannot be calculated safely from the supplied evidence."""


class BandWidthDirection(StrEnum):
    EXPANSION = "expansion"
    COMPRESSION = "compression"
    UNCHANGED = "unchanged"


@dataclass(frozen=True, slots=True)
class VolatilityPoint:
    candle_end: datetime
    value: Decimal | None


@dataclass(frozen=True, slots=True)
class VolatilitySeries:
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
    unit: str
    input_market_data_ids: tuple[UUID, ...]
    points: tuple[VolatilityPoint, ...]


@dataclass(frozen=True, slots=True)
class BollingerPoint:
    candle_end: datetime
    middle: Decimal | None
    upper: Decimal | None
    lower: Decimal | None
    bandwidth: Decimal | None
    bandwidth_direction: BandWidthDirection | None


@dataclass(frozen=True, slots=True)
class BollingerSeries:
    indicator_id: str
    metadata_version: str
    calculation_version: str
    period: int
    standard_deviation_multiplier: Decimal
    timeframe: str
    instrument_id: str
    venue_id: str
    snapshot_id: UUID
    quality_report_id: UUID
    as_of: datetime
    price_unit: str
    input_market_data_ids: tuple[UUID, ...]
    points: tuple[BollingerPoint, ...]


def _ohlc(
    *,
    snapshot: MarketSnapshot,
    observations: tuple[MarketData, ...],
    quality: DataQualityReport,
    timeframe: str,
) -> tuple[tuple[tuple[Decimal, Decimal, Decimal], ...], str]:
    if timeframe not in _INTERVALS:
        raise VolatilityError("Unsupported candle timeframe.")
    if (
        quality.snapshot_id != snapshot.snapshot_id
        or quality.status is not DataQualityStatus.VALID
    ):
        raise VolatilityError("Matching VALID C-003 quality evidence is required.")
    if (
        quality.required_data_cutoff != snapshot.as_of
        or quality.assessed_at < snapshot.as_of
    ):
        raise VolatilityError("Quality cutoff must match the snapshot as-of time.")
    if not observations or len(observations) > 10000:
        raise VolatilityError("A bounded nonempty observation series is required.")
    if tuple(item.market_data_id for item in observations) != snapshot.market_data_ids:
        raise VolatilityError("Observation order and identity must match the snapshot.")

    interval = timedelta(seconds=_INTERVALS[timeframe])
    unit: str | None = None
    previous_start: datetime | None = None
    candles: list[tuple[Decimal, Decimal, Decimal]] = []
    for item in observations:
        if (
            item.instrument_id != snapshot.instrument_id
            or item.venue_id != snapshot.venue_id
            or item.observation_type != "OHLCV"
            or item.source_record_id not in snapshot.source_record_ids
        ):
            raise VolatilityError("Observation identity or provenance does not match.")
        if (
            item.availability_time > snapshot.as_of
            or item.ingestion_time > snapshot.as_of
        ):
            raise VolatilityError("Observation was unavailable at the cutoff.")
        if item.event_time.tzinfo is None or item.event_time.utcoffset() is None:
            raise VolatilityError("Candle time must be timezone-aware.")
        if previous_start is not None and item.event_time - previous_start != interval:
            raise VolatilityError("Candles must be ordered and contiguous.")
        if item.event_time.astimezone(UTC).timestamp() % _INTERVALS[timeframe] != 0:
            raise VolatilityError("Candle time is not aligned to its timeframe.")
        if item.event_time + interval > snapshot.as_of:
            raise VolatilityError("A candle is not closed by the cutoff.")

        metrics = {metric.metric_name: metric for metric in item.metrics}
        if len(metrics) != len(item.metrics) or not all(
            name in metrics for name in ("open", "high", "low", "close", "volume")
        ):
            raise VolatilityError("Required unique closed OHLCV metrics are absent.")
        opening, high, low, close = (
            metrics[name] for name in ("open", "high", "low", "close")
        )
        if any(metric.value <= 0 for metric in (opening, high, low, close)):
            raise VolatilityError("OHLC prices must be positive.")
        if (
            low.value > min(opening.value, close.value)
            or high.value < max(opening.value, close.value)
            or low.value > high.value
        ):
            raise VolatilityError("OHLC values are internally inconsistent.")
        if any(metric.unit != close.unit for metric in (opening, high, low)):
            raise VolatilityError("OHLC price units must match.")
        if unit is not None and unit != close.unit:
            raise VolatilityError("Price units must remain consistent across candles.")
        unit = close.unit
        candles.append((high.value, low.value, close.value))
        previous_start = item.event_time

    assert unit is not None
    return tuple(candles), unit


def _metadata(indicator_id: str, period: int, timeframe: str):
    metadata = SPOT_RESEARCH_INDICATORS.get(
        indicator_id, "2" if indicator_id == "atr-14" else "1"
    )
    if (
        metadata.phase is not IndicatorPhase.VALIDATED
        or timeframe not in metadata.timeframes
        or type(period) is not int
        or not metadata.parameters[0].minimum
        <= period
        <= metadata.parameters[0].maximum
    ):
        raise VolatilityError(
            "Indicator or period is not validated for this timeframe."
        )
    return metadata


def _series(
    *,
    indicator_id: str,
    period: int,
    timeframe: str,
    snapshot: MarketSnapshot,
    quality: DataQualityReport,
    unit: str,
    values: list[Decimal | None],
    observations: tuple[MarketData, ...],
) -> VolatilitySeries:
    metadata = _metadata(indicator_id, period, timeframe)
    interval = timedelta(seconds=_INTERVALS[timeframe])
    return VolatilitySeries(
        indicator_id=metadata.indicator_id,
        metadata_version=metadata.metadata_version,
        calculation_version=metadata.calculation_version,
        period=period,
        timeframe=timeframe,
        instrument_id=snapshot.instrument_id,
        venue_id=snapshot.venue_id,
        snapshot_id=snapshot.snapshot_id,
        quality_report_id=quality.report_id,
        as_of=snapshot.as_of,
        unit=unit,
        input_market_data_ids=snapshot.market_data_ids,
        points=tuple(
            VolatilityPoint(item.event_time + interval, value)
            for item, value in zip(observations, values, strict=True)
        ),
    )


def calculate_atr14(
    *,
    snapshot: MarketSnapshot,
    observations: tuple[MarketData, ...],
    quality: DataQualityReport,
    timeframe: str,
) -> VolatilitySeries:
    """ATR-14: 14 true ranges, first TR starts with candle two; Wilder recurrence."""
    period = 14
    _metadata("atr-14", period, timeframe)
    candles, unit = _ohlc(
        snapshot=snapshot,
        observations=observations,
        quality=quality,
        timeframe=timeframe,
    )
    ranges: list[Decimal] = []
    for index in range(1, len(candles)):
        high, low, _ = candles[index]
        previous_close = candles[index - 1][2]
        ranges.append(
            max(high - low, abs(high - previous_close), abs(low - previous_close))
        )
    values: list[Decimal | None] = [None] * len(candles)
    if len(ranges) >= period:
        with localcontext() as context:
            context.prec = 34
            previous = sum(ranges[:period], Decimal(0)) / Decimal(period)
            values[period] = previous
            for index, true_range in enumerate(ranges[period:], start=period + 1):
                previous = (previous * Decimal(period - 1) + true_range) / Decimal(
                    period
                )
                values[index] = previous
    return _series(
        indicator_id="atr-14",
        period=period,
        timeframe=timeframe,
        snapshot=snapshot,
        quality=quality,
        unit=unit,
        values=values,
        observations=observations,
    )


def calculate_bollinger_bands(
    *,
    snapshot: MarketSnapshot,
    observations: tuple[MarketData, ...],
    quality: DataQualityReport,
    period: int,
    timeframe: str,
) -> BollingerSeries:
    """Population standard deviation bands, fixed 2σ; width direction vs prior width."""
    metadata = _metadata("bollinger-bands", period, timeframe)
    candles, unit = _ohlc(
        snapshot=snapshot,
        observations=observations,
        quality=quality,
        timeframe=timeframe,
    )
    closes = tuple(item[2] for item in candles)
    points: list[BollingerPoint] = []
    prior_width: Decimal | None = None
    with localcontext() as context:
        context.prec = 34
        for end, candle in enumerate(observations, start=1):
            if end < period:
                points.append(
                    BollingerPoint(
                        candle.event_time + timedelta(seconds=_INTERVALS[timeframe]),
                        None,
                        None,
                        None,
                        None,
                        None,
                    )
                )
                continue
            window = closes[end - period : end]
            middle = sum(window, Decimal(0)) / Decimal(period)
            variance = sum(
                ((value - middle) ** 2 for value in window), Decimal(0)
            ) / Decimal(period)
            deviation = variance.sqrt()
            upper = middle + Decimal(2) * deviation
            lower = middle - Decimal(2) * deviation
            width = (upper - lower) / middle
            direction = None
            if prior_width is not None:
                direction = (
                    BandWidthDirection.EXPANSION
                    if width > prior_width
                    else BandWidthDirection.COMPRESSION
                    if width < prior_width
                    else BandWidthDirection.UNCHANGED
                )
            points.append(
                BollingerPoint(
                    candle.event_time + timedelta(seconds=_INTERVALS[timeframe]),
                    middle,
                    upper,
                    lower,
                    width,
                    direction,
                )
            )
            prior_width = width
    return BollingerSeries(
        indicator_id=metadata.indicator_id,
        metadata_version=metadata.metadata_version,
        calculation_version=metadata.calculation_version,
        period=period,
        standard_deviation_multiplier=Decimal(2),
        timeframe=timeframe,
        instrument_id=snapshot.instrument_id,
        venue_id=snapshot.venue_id,
        snapshot_id=snapshot.snapshot_id,
        quality_report_id=quality.report_id,
        as_of=snapshot.as_of,
        price_unit=unit,
        input_market_data_ids=snapshot.market_data_ids,
        points=tuple(points),
    )


def calculate_realized_volatility(
    *,
    snapshot: MarketSnapshot,
    observations: tuple[MarketData, ...],
    quality: DataQualityReport,
    period: int,
    timeframe: str,
) -> VolatilitySeries:
    """Sample stdev of close log returns, annualized for a continuous 365-day market."""
    _metadata("realized-volatility", period, timeframe)
    candles, _ = _ohlc(
        snapshot=snapshot,
        observations=observations,
        quality=quality,
        timeframe=timeframe,
    )
    closes = tuple(item[2] for item in candles)
    values: list[Decimal | None] = [None] * len(closes)
    with localcontext() as context:
        context.prec = 34
        returns = tuple(
            closes[index].ln() - closes[index - 1].ln()
            for index in range(1, len(closes))
        )
        annualizer = Decimal(_PERIODS_PER_YEAR[timeframe]).sqrt()
        for end in range(period, len(returns) + 1):
            window = returns[end - period : end]
            mean = sum(window, Decimal(0)) / Decimal(period)
            variance = sum(
                ((value - mean) ** 2 for value in window), Decimal(0)
            ) / Decimal(period - 1)
            values[end] = variance.sqrt() * annualizer
    return _series(
        indicator_id="realized-volatility",
        period=period,
        timeframe=timeframe,
        snapshot=snapshot,
        quality=quality,
        unit="annualized-fraction",
        values=values,
        observations=observations,
    )
