"""Deterministic, provenance-bound Spot VWAP and volume-profile calculations."""

from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal, localcontext
from enum import StrEnum
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
_INTERVALS = {
    "1m": 60,
    "5m": 300,
    "15m": 900,
    "1h": 3600,
    "4h": 14400,
    "1d": 86400,
}

VWAP_METHOD = "bar-based typical-price VWAP"
VOLUME_PROFILE_METHOD = "candle-assigned volume-profile proxy"


class VolumeAnalysisError(ValueError):
    """VWAP or volume profile cannot be calculated from the supplied evidence."""


class VWAPStatus(StrEnum):
    READY = "READY"
    UNDEFINED = "UNDEFINED"


class VWAPReason(StrEnum):
    ZERO_CUMULATIVE_VOLUME = "ZERO_CUMULATIVE_VOLUME"


class VolumeProfileStatus(StrEnum):
    READY = "READY"
    UNDEFINED = "UNDEFINED"


class VolumeProfileReason(StrEnum):
    ZERO_TOTAL_VOLUME = "ZERO_TOTAL_VOLUME"


@dataclass(frozen=True, slots=True)
class VWAPValue:
    value: Decimal | None
    status: VWAPStatus
    reason: VWAPReason | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.status, VWAPStatus):
            raise VolumeAnalysisError("A VWAP value needs a recognized status.")
        if self.status is VWAPStatus.READY:
            if (
                not isinstance(self.value, Decimal)
                or not self.value.is_finite()
                or self.reason is not None
            ):
                raise VolumeAnalysisError("A ready VWAP value must be finite.")
        elif (
            self.value is not None
            or self.reason is not VWAPReason.ZERO_CUMULATIVE_VOLUME
        ):
            raise VolumeAnalysisError("An undefined VWAP value needs a reason.")


@dataclass(frozen=True, slots=True)
class VWAPPoint:
    candle_end: datetime
    value: VWAPValue


@dataclass(frozen=True, slots=True)
class VWAPSeries:
    indicator_id: str
    metadata_version: str
    calculation_version: str
    parameters: tuple[tuple[str, int], ...]
    method_label: str
    timeframe: str
    instrument_id: str
    venue_id: str
    snapshot_id: UUID
    quality_report_id: UUID
    as_of: datetime
    price_unit: str
    volume_unit: str
    anchor_mode: str
    anchor_time: datetime
    window_start: datetime
    window_end: datetime
    input_market_data_ids: tuple[UUID, ...]
    points: tuple[VWAPPoint, ...]


@dataclass(frozen=True, slots=True)
class VolumeProfileBin:
    index: int
    lower_bound: Decimal
    upper_bound: Decimal
    includes_upper_bound: bool
    assigned_volume: Decimal


@dataclass(frozen=True, slots=True)
class VolumeProfileSeries:
    indicator_id: str
    metadata_version: str
    calculation_version: str
    parameters: tuple[tuple[str, int], ...]
    method_label: str
    timeframe: str
    instrument_id: str
    venue_id: str
    snapshot_id: UUID
    quality_report_id: UUID
    as_of: datetime
    price_unit: str
    volume_unit: str
    window_start: datetime
    window_end: datetime
    input_market_data_ids: tuple[UUID, ...]
    status: VolumeProfileStatus
    reason: VolumeProfileReason | None
    bins: tuple[VolumeProfileBin, ...]
    poc_bin_index: int | None
    value_area_bin_indices: tuple[int, ...]
    value_area_low: Decimal | None
    value_area_high: Decimal | None
    value_area_volume: Decimal | None
    value_area_share: Decimal | None
    high_volume_node_bin_indices: tuple[int, ...]
    low_volume_node_bin_indices: tuple[int, ...]


def _metadata(
    indicator_id: str,
    metadata_version: str,
    timeframe: str,
    parameters: tuple[int, ...],
) -> IndicatorMetadata:
    if not isinstance(metadata_version, str):
        raise VolumeAnalysisError("An exact indicator metadata version is required.")
    try:
        metadata = SPOT_RESEARCH_INDICATORS.get(indicator_id, metadata_version)
    except IndicatorMetadataError as exc:
        raise VolumeAnalysisError(str(exc)) from exc
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
        raise VolumeAnalysisError(
            "Indicator parameters or timeframe are not supported."
        )
    return metadata


def _inputs(
    *,
    snapshot: MarketSnapshot,
    observations: tuple[MarketData, ...],
    quality: DataQualityReport,
    timeframe: str,
) -> tuple[
    tuple[tuple[Decimal, Decimal, Decimal], ...],
    tuple[Decimal, ...],
    str,
    str,
]:
    if (
        not isinstance(snapshot, MarketSnapshot)
        or not isinstance(quality, DataQualityReport)
        or not isinstance(observations, tuple)
        or not observations
        or len(observations) > _MAX_CANDLES
        or not all(isinstance(item, MarketData) for item in observations)
    ):
        raise VolumeAnalysisError(
            "A bounded nonempty tuple of canonical C-001 observations and "
            "matching C-002/C-003 contracts is required."
        )
    try:
        candles, price_unit = _ohlc(
            snapshot=snapshot,
            observations=observations,
            quality=quality,
            timeframe=timeframe,
        )
    except VolatilityError as exc:
        raise VolumeAnalysisError(str(exc)) from exc
    volumes: list[Decimal] = []
    volume_unit: str | None = None
    for item in observations:
        volume_metrics = tuple(
            metric for metric in item.metrics if metric.metric_name == "volume"
        )
        if len(volume_metrics) != 1:
            raise VolumeAnalysisError(
                "Exactly one supplied volume metric is required per candle."
            )
        volume = volume_metrics[0]
        if volume.value < 0:
            raise VolumeAnalysisError("Candle volume must be nonnegative.")
        if volume_unit is not None and volume.unit != volume_unit:
            raise VolumeAnalysisError("Volume units must remain consistent.")
        volume_unit = volume.unit
        volumes.append(volume.value)

    assert volume_unit is not None
    return candles, tuple(volumes), price_unit, volume_unit


def _typical_prices(
    candles: tuple[tuple[Decimal, Decimal, Decimal], ...],
) -> tuple[Decimal, ...]:
    return tuple((high + low + close) / Decimal(3) for high, low, close in candles)


def _candle_end(candle: MarketData, timeframe: str) -> datetime:
    return candle.event_time + timedelta(seconds=_INTERVALS[timeframe])


def _window_end(observations: tuple[MarketData, ...], timeframe: str) -> datetime:
    return _candle_end(observations[-1], timeframe)


def calculate_vwap(
    *,
    snapshot: MarketSnapshot,
    observations: tuple[MarketData, ...],
    quality: DataQualityReport,
    timeframe: str = "1m",
    metadata_version: str = "1",
) -> VWAPSeries:
    """Calculate cumulative bar-based typical-price VWAP from the first candle."""
    metadata = _metadata("vwap", metadata_version, timeframe, ())
    candles, volumes, price_unit, volume_unit = _inputs(
        snapshot=snapshot,
        observations=observations,
        quality=quality,
        timeframe=timeframe,
    )
    with localcontext() as context:
        context.prec = _DECIMAL_PRECISION
        typical_prices = _typical_prices(candles)
        cumulative_volume = Decimal(0)
        cumulative_price_volume = Decimal(0)
        points: list[VWAPPoint] = []
        for item, typical_price, volume in zip(
            observations, typical_prices, volumes, strict=True
        ):
            cumulative_volume += volume
            cumulative_price_volume += typical_price * volume
            value = (
                VWAPValue(
                    cumulative_price_volume / cumulative_volume,
                    VWAPStatus.READY,
                )
                if cumulative_volume > 0
                else VWAPValue(
                    None,
                    VWAPStatus.UNDEFINED,
                    VWAPReason.ZERO_CUMULATIVE_VOLUME,
                )
            )
            points.append(VWAPPoint(_candle_end(item, timeframe), value))

    return VWAPSeries(
        indicator_id=metadata.indicator_id,
        metadata_version=metadata.metadata_version,
        calculation_version=metadata.calculation_version,
        parameters=(),
        method_label=VWAP_METHOD,
        timeframe=timeframe,
        instrument_id=snapshot.instrument_id,
        venue_id=snapshot.venue_id,
        snapshot_id=snapshot.snapshot_id,
        quality_report_id=quality.report_id,
        as_of=snapshot.as_of,
        price_unit=price_unit,
        volume_unit=volume_unit,
        anchor_mode="first-candle",
        anchor_time=observations[0].event_time,
        window_start=observations[0].event_time,
        window_end=_window_end(observations, timeframe),
        input_market_data_ids=snapshot.market_data_ids,
        points=tuple(points),
    )


def _profile_edges(
    minimum: Decimal, maximum: Decimal, bin_count: int
) -> tuple[Decimal, ...]:
    if minimum == maximum:
        return (minimum, maximum)
    span = maximum - minimum
    return tuple(
        minimum + span * Decimal(index) / Decimal(bin_count)
        for index in range(bin_count + 1)
    )


def _profile_precision(
    candles: tuple[tuple[Decimal, Decimal, Decimal], ...], bin_count: int
) -> int:
    prices = tuple(price for candle in candles for price in candle)
    maximum_adjusted = max(price.adjusted() for price in prices)
    minimum_exponent = min(price.as_tuple().exponent for price in prices)
    precision = max(
        _DECIMAL_PRECISION,
        maximum_adjusted - minimum_exponent + len(str(bin_count)) + 8,
    )
    if precision > 4096:
        raise VolumeAnalysisError("Price precision exceeds the calculation bound.")
    return precision


def _assign_volumes(
    typical_prices: tuple[Decimal, ...],
    volumes: tuple[Decimal, ...],
    edges: tuple[Decimal, ...],
    bin_count: int,
) -> tuple[Decimal, ...]:
    assigned = [Decimal(0)] * bin_count
    for price, volume in zip(typical_prices, volumes, strict=True):
        if price == edges[0]:
            index = 0
        elif price == edges[-1]:
            index = bin_count - 1
        else:
            index = bisect_right(edges, price) - 1
        assigned[index] += volume
    return tuple(assigned)


def _nodes(
    assigned_volume: tuple[Decimal, ...],
) -> tuple[tuple[int, ...], tuple[int, ...]]:
    high_nodes = tuple(
        index
        for index in range(1, len(assigned_volume) - 1)
        if assigned_volume[index] > assigned_volume[index - 1]
        and assigned_volume[index] > assigned_volume[index + 1]
    )
    low_nodes = tuple(
        index
        for index in range(1, len(assigned_volume) - 1)
        if assigned_volume[index] < assigned_volume[index - 1]
        and assigned_volume[index] < assigned_volume[index + 1]
    )
    return high_nodes, low_nodes


def calculate_volume_profile(
    *,
    snapshot: MarketSnapshot,
    observations: tuple[MarketData, ...],
    quality: DataQualityReport,
    bin_count: int = 24,
    value_area_percent: int = 70,
    timeframe: str = "1m",
    metadata_version: str = "1",
) -> VolumeProfileSeries:
    """Calculate a candle-assigned typical-price volume-profile proxy."""
    metadata = _metadata(
        "volume-profile",
        metadata_version,
        timeframe,
        (bin_count, value_area_percent),
    )
    candles, volumes, price_unit, volume_unit = _inputs(
        snapshot=snapshot,
        observations=observations,
        quality=quality,
        timeframe=timeframe,
    )

    with localcontext() as context:
        context.prec = _profile_precision(candles, bin_count)
        typical_prices = _typical_prices(candles)
        minimum = min(typical_prices)
        maximum = max(typical_prices)
        edges = _profile_edges(minimum, maximum, bin_count)
        if minimum != maximum and any(
            upper <= lower for lower, upper in zip(edges[:-1], edges[1:], strict=True)
        ):
            raise VolumeAnalysisError(
                "Price range cannot be represented by distinct profile bins."
            )
        effective_bin_count = 1 if minimum == maximum else bin_count
        assigned_volume = _assign_volumes(
            typical_prices, volumes, edges, effective_bin_count
        )
        bins = tuple(
            VolumeProfileBin(
                index=index,
                lower_bound=edges[index],
                upper_bound=edges[index + 1],
                includes_upper_bound=index == effective_bin_count - 1,
                assigned_volume=volume,
            )
            for index, volume in enumerate(assigned_volume)
        )
        total_volume = sum(assigned_volume, Decimal(0))

        if total_volume == 0:
            status = VolumeProfileStatus.UNDEFINED
            reason = VolumeProfileReason.ZERO_TOTAL_VOLUME
            poc_bin_index = None
            value_area_bin_indices: tuple[int, ...] = ()
            value_area_low = None
            value_area_high = None
            value_area_volume = None
            value_area_share = None
            high_nodes: tuple[int, ...] = ()
            low_nodes: tuple[int, ...] = ()
        else:
            status = VolumeProfileStatus.READY
            reason = None
            poc_bin_index = 0
            for index in range(1, effective_bin_count):
                if assigned_volume[index] > assigned_volume[poc_bin_index]:
                    poc_bin_index = index

            target_volume = total_volume * Decimal(value_area_percent) / Decimal(100)
            low_index = high_index = poc_bin_index
            value_area_volume = assigned_volume[poc_bin_index]
            while value_area_volume < target_volume:
                left_index = low_index - 1
                right_index = high_index + 1
                if left_index < 0:
                    chosen_index = right_index
                    high_index = right_index
                elif right_index >= effective_bin_count:
                    chosen_index = left_index
                    low_index = left_index
                elif assigned_volume[left_index] >= assigned_volume[right_index]:
                    chosen_index = left_index
                    low_index = left_index
                else:
                    chosen_index = right_index
                    high_index = right_index
                value_area_volume += assigned_volume[chosen_index]

            value_area_bin_indices = tuple(range(low_index, high_index + 1))
            value_area_low = bins[low_index].lower_bound
            value_area_high = bins[high_index].upper_bound
            value_area_share = value_area_volume / total_volume
            high_nodes, low_nodes = _nodes(assigned_volume)

    return VolumeProfileSeries(
        indicator_id=metadata.indicator_id,
        metadata_version=metadata.metadata_version,
        calculation_version=metadata.calculation_version,
        parameters=(
            ("bin-count", bin_count),
            ("value-area-percent", value_area_percent),
        ),
        method_label=VOLUME_PROFILE_METHOD,
        timeframe=timeframe,
        instrument_id=snapshot.instrument_id,
        venue_id=snapshot.venue_id,
        snapshot_id=snapshot.snapshot_id,
        quality_report_id=quality.report_id,
        as_of=snapshot.as_of,
        price_unit=price_unit,
        volume_unit=volume_unit,
        window_start=observations[0].event_time,
        window_end=_window_end(observations, timeframe),
        input_market_data_ids=snapshot.market_data_ids,
        status=status,
        reason=reason,
        bins=bins,
        poc_bin_index=poc_bin_index,
        value_area_bin_indices=value_area_bin_indices,
        value_area_low=value_area_low,
        value_area_high=value_area_high,
        value_area_volume=value_area_volume,
        value_area_share=value_area_share,
        high_volume_node_bin_indices=high_nodes,
        low_volume_node_bin_indices=low_nodes,
    )


__all__ = [
    "VOLUME_PROFILE_METHOD",
    "VWAP_METHOD",
    "VolumeAnalysisError",
    "VolumeProfileBin",
    "VolumeProfileReason",
    "VolumeProfileSeries",
    "VolumeProfileStatus",
    "VWAPPoint",
    "VWAPReason",
    "VWAPSeries",
    "VWAPStatus",
    "VWAPValue",
    "calculate_volume_profile",
    "calculate_vwap",
]
