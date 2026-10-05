"""Deterministic, provenance-bound Spot momentum indicator calculations."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal, localcontext
from enum import StrEnum
from typing import Any
from uuid import UUID

from trading_platform_api.analysis.indicator_registry import (
    SPOT_RESEARCH_INDICATORS,
    IndicatorMetadata,
    IndicatorMetadataError,
    IndicatorPhase,
)
from trading_platform_api.analysis.volatility import VolatilityError, _ohlc
from trading_platform_api.market_data.contracts import (
    DataQualityReport,
    MarketData,
    MarketSnapshot,
)

_DECIMAL_PRECISION = 34
_MAX_CANDLES = 10000


class MomentumError(ValueError):
    """Momentum cannot be calculated safely from the supplied evidence."""


class MomentumStatus(StrEnum):
    READY = "READY"
    WARMUP = "WARMUP"
    UNDEFINED = "UNDEFINED"


class MomentumReason(StrEnum):
    WARMUP = "WARMUP"
    ZERO_RANGE = "ZERO_RANGE"
    ZERO_DEVIATION = "ZERO_DEVIATION"


@dataclass(frozen=True, slots=True)
class MomentumValue:
    value: Decimal | None
    status: MomentumStatus
    reason: MomentumReason | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.status, MomentumStatus):
            raise MomentumError("An indicator value needs a recognized status.")
        if self.status is MomentumStatus.READY:
            if (
                not isinstance(self.value, Decimal)
                or not self.value.is_finite()
                or self.reason is not None
            ):
                raise MomentumError("A ready indicator value must be finite.")
        elif self.value is not None or not isinstance(self.reason, MomentumReason):
            raise MomentumError("An unavailable indicator value needs a reason.")
        if self.status is MomentumStatus.WARMUP and self.reason is not MomentumReason.WARMUP:
            raise MomentumError("Warm-up values must use the WARMUP reason.")
        if self.status is MomentumStatus.UNDEFINED and self.reason not in {
            MomentumReason.ZERO_RANGE,
            MomentumReason.ZERO_DEVIATION,
        }:
            raise MomentumError("Undefined values need a recognized reason.")


@dataclass(frozen=True, slots=True)
class MomentumSeries:
    indicator_id: str
    metadata_version: str
    calculation_version: str
    parameters: tuple[tuple[str, int], ...]
    timeframe: str
    instrument_id: str
    venue_id: str
    snapshot_id: UUID
    quality_report_id: UUID
    as_of: datetime
    unit: str
    price_unit: str
    input_market_data_ids: tuple[UUID, ...]


@dataclass(frozen=True, slots=True)
class RSIPoint:
    candle_end: datetime
    value: MomentumValue


@dataclass(frozen=True, slots=True)
class RSISeries(MomentumSeries):
    points: tuple[RSIPoint, ...]


@dataclass(frozen=True, slots=True)
class MACDPoint:
    candle_end: datetime
    line: MomentumValue
    signal: MomentumValue
    histogram: MomentumValue


@dataclass(frozen=True, slots=True)
class MACDSeries(MomentumSeries):
    points: tuple[MACDPoint, ...]


@dataclass(frozen=True, slots=True)
class StochasticPoint:
    candle_end: datetime
    k: MomentumValue
    d: MomentumValue


@dataclass(frozen=True, slots=True)
class StochasticSeries(MomentumSeries):
    points: tuple[StochasticPoint, ...]


@dataclass(frozen=True, slots=True)
class CCIPoint:
    candle_end: datetime
    value: MomentumValue


@dataclass(frozen=True, slots=True)
class CCISeries(MomentumSeries):
    points: tuple[CCIPoint, ...]


def _metadata(
    indicator_id: str,
    metadata_version: str,
    timeframe: str,
    parameters: tuple[int, ...],
) -> IndicatorMetadata:
    if not isinstance(metadata_version, str):
        raise MomentumError("An exact indicator metadata version is required.")
    try:
        metadata = SPOT_RESEARCH_INDICATORS.get(indicator_id, metadata_version)
    except IndicatorMetadataError as exc:
        raise MomentumError(str(exc)) from exc
    if (
        metadata.phase is not IndicatorPhase.VALIDATED
        or timeframe not in metadata.timeframes
        or len(parameters) != len(metadata.parameters)
        or any(
            type(value) is not int
            or not parameter.minimum <= value <= parameter.maximum
            for value, parameter in zip(parameters, metadata.parameters, strict=True)
        )
    ):
        raise MomentumError("Indicator parameters or timeframe are not supported.")
    return metadata


def _inputs(
    *,
    snapshot: MarketSnapshot,
    observations: tuple[MarketData, ...],
    quality: DataQualityReport,
    timeframe: str,
) -> tuple[tuple[tuple[Decimal, Decimal, Decimal], ...], str]:
    try:
        candles, price_unit = _ohlc(
            snapshot=snapshot,
            observations=observations,
            quality=quality,
            timeframe=timeframe,
        )
    except VolatilityError as exc:
        raise MomentumError(str(exc)) from exc
    if len(observations) > _MAX_CANDLES:
        raise MomentumError("A bounded nonempty observation series is required.")

    volume_unit: str | None = None
    for item in observations:
        volume = next(metric for metric in item.metrics if metric.metric_name == "volume")
        if volume.value < 0 or (
            volume_unit is not None and volume.unit != volume_unit
        ):
            raise MomentumError("Volume metrics must be nonnegative and unit-consistent.")
        volume_unit = volume.unit
    return candles, price_unit


def _value(value: Decimal | None) -> MomentumValue:
    if value is None:
        return MomentumValue(None, MomentumStatus.WARMUP, MomentumReason.WARMUP)
    return MomentumValue(value, MomentumStatus.READY)


def _undefined(reason: MomentumReason) -> MomentumValue:
    return MomentumValue(None, MomentumStatus.UNDEFINED, reason)


def _series_fields(
    *,
    metadata: IndicatorMetadata,
    parameters: tuple[tuple[str, int], ...],
    timeframe: str,
    snapshot: MarketSnapshot,
    quality: DataQualityReport,
    price_unit: str,
) -> dict[str, Any]:
    return {
        "indicator_id": metadata.indicator_id,
        "metadata_version": metadata.metadata_version,
        "calculation_version": metadata.calculation_version,
        "parameters": parameters,
        "timeframe": timeframe,
        "instrument_id": snapshot.instrument_id,
        "venue_id": snapshot.venue_id,
        "snapshot_id": snapshot.snapshot_id,
        "quality_report_id": quality.report_id,
        "as_of": snapshot.as_of,
        "unit": metadata.output_unit,
        "price_unit": price_unit,
        "input_market_data_ids": snapshot.market_data_ids,
    }


def _candle_ends(
    observations: tuple[MarketData, ...], timeframe: str
) -> tuple[datetime, ...]:
    seconds = {"1m": 60, "5m": 300, "15m": 900, "1h": 3600, "4h": 14400, "1d": 86400}[
        timeframe
    ]
    interval = timedelta(seconds=seconds)
    return tuple(item.event_time + interval for item in observations)


def _ema(values: tuple[Decimal, ...], period: int) -> tuple[Decimal | None, ...]:
    output: list[Decimal | None] = [None] * len(values)
    if len(values) < period:
        return tuple(output)
    previous = sum(values[:period], Decimal(0)) / Decimal(period)
    output[period - 1] = previous
    alpha = Decimal(2) / Decimal(period + 1)
    for index in range(period, len(values)):
        previous = alpha * values[index] + (Decimal(1) - alpha) * previous
        output[index] = previous
    return tuple(output)


def calculate_rsi(
    *,
    snapshot: MarketSnapshot,
    observations: tuple[MarketData, ...],
    quality: DataQualityReport,
    period: int = 14,
    timeframe: str = "1m",
    metadata_version: str = "1",
) -> RSISeries:
    """Calculate Wilder RSI with an arithmetic-mean seed and explicit warm-up."""
    metadata = _metadata("rsi", metadata_version, timeframe, (period,))
    candles, price_unit = _inputs(
        snapshot=snapshot,
        observations=observations,
        quality=quality,
        timeframe=timeframe,
    )
    closes = tuple(candle[2] for candle in candles)
    values: list[Decimal | None] = [None] * len(closes)
    with localcontext() as context:
        context.prec = _DECIMAL_PRECISION
        changes = tuple(closes[index] - closes[index - 1] for index in range(1, len(closes)))
        gains = tuple(max(change, Decimal(0)) for change in changes)
        losses = tuple(max(-change, Decimal(0)) for change in changes)
        if len(changes) >= period:
            average_gain = sum(gains[:period], Decimal(0)) / Decimal(period)
            average_loss = sum(losses[:period], Decimal(0)) / Decimal(period)
            for change_index in range(period, len(changes) + 1):
                if change_index > period:
                    index = change_index - 1
                    average_gain = (
                        average_gain * Decimal(period - 1) + gains[index]
                    ) / Decimal(period)
                    average_loss = (
                        average_loss * Decimal(period - 1) + losses[index]
                    ) / Decimal(period)
                candle_index = change_index
                if average_gain == 0 and average_loss == 0:
                    values[candle_index] = Decimal(50)
                elif average_loss == 0:
                    values[candle_index] = Decimal(100)
                elif average_gain == 0:
                    values[candle_index] = Decimal(0)
                else:
                    relative_strength = average_gain / average_loss
                    values[candle_index] = Decimal(100) - (
                        Decimal(100) / (Decimal(1) + relative_strength)
                    )
    parameters = (("period", period),)
    return RSISeries(
        **_series_fields(
            metadata=metadata,
            parameters=parameters,
            timeframe=timeframe,
            snapshot=snapshot,
            quality=quality,
            price_unit=price_unit,
        ),
        points=tuple(
            RSIPoint(candle_end, _value(value))
            for candle_end, value in zip(
                _candle_ends(observations, timeframe), values, strict=True
            )
        ),
    )


def calculate_macd(
    *,
    snapshot: MarketSnapshot,
    observations: tuple[MarketData, ...],
    quality: DataQualityReport,
    fast_period: int = 12,
    slow_period: int = 26,
    signal_period: int = 9,
    timeframe: str = "1m",
    metadata_version: str = "1",
) -> MACDSeries:
    """Calculate SMA-seeded fast/slow EMA MACD, signal, and histogram."""
    if type(fast_period) is not int or type(slow_period) is not int:
        raise MomentumError("MACD periods must be integers with fast below slow.")
    metadata = _metadata(
        "macd",
        metadata_version,
        timeframe,
        (fast_period, slow_period, signal_period),
    )
    if fast_period >= slow_period:
        raise MomentumError("MACD fast period must be less than slow period.")
    candles, price_unit = _inputs(
        snapshot=snapshot,
        observations=observations,
        quality=quality,
        timeframe=timeframe,
    )
    closes = tuple(candle[2] for candle in candles)
    with localcontext() as context:
        context.prec = _DECIMAL_PRECISION
        fast = _ema(closes, fast_period)
        slow = _ema(closes, slow_period)
        lines: list[Decimal | None] = [
            fast_value - slow_value
            if fast_value is not None and slow_value is not None
            else None
            for fast_value, slow_value in zip(fast, slow, strict=True)
        ]
        first_line = next((i for i, value in enumerate(lines) if value is not None), None)
        signal_values: list[Decimal | None] = [None] * len(lines)
        if first_line is not None:
            valid_lines = tuple(value for value in lines[first_line:] if value is not None)
            valid_signal = _ema(valid_lines, signal_period)
            for index, value in enumerate(valid_signal, start=first_line):
                signal_values[index] = value
        points: list[MACDPoint] = []
        for candle_end, line, signal in zip(
            _candle_ends(observations, timeframe),
            lines,
            signal_values,
            strict=True,
        ):
            points.append(
                MACDPoint(
                    candle_end,
                    _value(line),
                    _value(signal),
                    _value(line - signal if line is not None and signal is not None else None),
                )
            )
    parameters = (
        ("fast-period", fast_period),
        ("slow-period", slow_period),
        ("signal-period", signal_period),
    )
    return MACDSeries(
        **_series_fields(
            metadata=metadata,
            parameters=parameters,
            timeframe=timeframe,
            snapshot=snapshot,
            quality=quality,
            price_unit=price_unit,
        ),
        points=tuple(points),
    )


def calculate_stochastic(
    *,
    snapshot: MarketSnapshot,
    observations: tuple[MarketData, ...],
    quality: DataQualityReport,
    k_period: int = 14,
    d_period: int = 3,
    timeframe: str = "1m",
    metadata_version: str = "1",
) -> StochasticSeries:
    """Calculate trailing raw %K and its trailing simple-mean %D."""
    metadata = _metadata(
        "stochastic", metadata_version, timeframe, (k_period, d_period)
    )
    candles, price_unit = _inputs(
        snapshot=snapshot,
        observations=observations,
        quality=quality,
        timeframe=timeframe,
    )
    highs, lows, closes = zip(*candles, strict=True)
    with localcontext() as context:
        context.prec = _DECIMAL_PRECISION
        raw: list[Decimal | None] = [None] * len(candles)
        k_reasons: list[MomentumReason | None] = [None] * len(candles)
        for end in range(k_period, len(candles) + 1):
            start = end - k_period
            highest = max(highs[start:end])
            lowest = min(lows[start:end])
            if highest == lowest:
                k_reasons[end - 1] = MomentumReason.ZERO_RANGE
            else:
                raw[end - 1] = (
                    Decimal(100) * (closes[end - 1] - lowest) / (highest - lowest)
                )
        points: list[StochasticPoint] = []
        for index, candle_end in enumerate(_candle_ends(observations, timeframe)):
            if raw[index] is not None:
                k = _value(raw[index])
            elif k_reasons[index] is not None:
                k = _undefined(k_reasons[index])
            else:
                k = _value(None)
            d_start = index - d_period + 1
            if d_start < k_period - 1:
                d = _value(None)
            else:
                window = raw[d_start : index + 1]
                if any(value is None for value in window):
                    d = _undefined(MomentumReason.ZERO_RANGE)
                else:
                    d = _value(
                        sum((value for value in window if value is not None), Decimal(0))
                        / Decimal(d_period)
                    )
            points.append(StochasticPoint(candle_end, k, d))
    parameters = (("k-period", k_period), ("d-period", d_period))
    return StochasticSeries(
        **_series_fields(
            metadata=metadata,
            parameters=parameters,
            timeframe=timeframe,
            snapshot=snapshot,
            quality=quality,
            price_unit=price_unit,
        ),
        points=tuple(points),
    )


def calculate_cci(
    *,
    snapshot: MarketSnapshot,
    observations: tuple[MarketData, ...],
    quality: DataQualityReport,
    period: int = 20,
    timeframe: str = "1m",
    metadata_version: str = "1",
) -> CCISeries:
    """Calculate CCI from typical price and mean absolute deviation."""
    metadata = _metadata("cci", metadata_version, timeframe, (period,))
    candles, price_unit = _inputs(
        snapshot=snapshot,
        observations=observations,
        quality=quality,
        timeframe=timeframe,
    )
    with localcontext() as context:
        context.prec = _DECIMAL_PRECISION
        typical = tuple((high + low + close) / Decimal(3) for high, low, close in candles)
        values: list[Decimal | None] = [None] * len(candles)
        undefined: set[int] = set()
        for end in range(period, len(candles) + 1):
            window = typical[end - period : end]
            mean = sum(window, Decimal(0)) / Decimal(period)
            deviation = sum((abs(value - mean) for value in window), Decimal(0)) / Decimal(
                period
            )
            if deviation == 0:
                undefined.add(end - 1)
            else:
                values[end - 1] = (typical[end - 1] - mean) / (
                    Decimal("0.015") * deviation
                )
        points = tuple(
            CCIPoint(
                candle_end,
                _undefined(MomentumReason.ZERO_DEVIATION)
                if index in undefined
                else _value(value),
            )
            for index, (candle_end, value) in enumerate(
                zip(_candle_ends(observations, timeframe), values, strict=True)
            )
        )
    parameters = (("period", period),)
    return CCISeries(
        **_series_fields(
            metadata=metadata,
            parameters=parameters,
            timeframe=timeframe,
            snapshot=snapshot,
            quality=quality,
            price_unit=price_unit,
        ),
        points=points,
    )


__all__ = [
    "CCIPoint",
    "CCISeries",
    "MACDPoint",
    "MACDSeries",
    "MomentumError",
    "MomentumReason",
    "MomentumSeries",
    "MomentumStatus",
    "MomentumValue",
    "RSIPoint",
    "RSISeries",
    "StochasticPoint",
    "StochasticSeries",
    "calculate_cci",
    "calculate_macd",
    "calculate_rsi",
    "calculate_stochastic",
]
