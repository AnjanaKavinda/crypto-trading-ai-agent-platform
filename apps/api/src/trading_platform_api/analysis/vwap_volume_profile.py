"""Deterministic, provenance-bound Spot volume and price-volume calculations."""

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
    DataQualityStatus,
    MarketData,
    MarketSnapshot,
)

_DECIMAL_PRECISION = 34
_MAX_DECIMAL_PRECISION = 4096
_MAX_DECIMAL_EXPONENT = 4096
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
PIVOT_COMPARISON_METHOD = (
    "caller-specified pivot price and raw-volume direction comparison"
)
PIVOT_COMPARISON_VERSION = "explicit-pivot-opposing-deltas-v1"


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


class VolumeConfirmationPointStatus(StrEnum):
    READY = "READY"
    UNAVAILABLE = "UNAVAILABLE"


class VolumeConfirmationPointReason(StrEnum):
    INSUFFICIENT_PRIOR_CANDLES = "INSUFFICIENT_PRIOR_CANDLES"
    ZERO_PRIOR_VOLUME_BASELINE = "ZERO_PRIOR_VOLUME_BASELINE"


class CandidateBreakoutDirection(StrEnum):
    UP = "UP"
    DOWN = "DOWN"


class VolumePivotPriceField(StrEnum):
    HIGH = "high"
    LOW = "low"


class PriceVolumeComparisonStatus(StrEnum):
    DIVERGENT = "DIVERGENT"
    ALIGNED = "ALIGNED"
    NON_DIRECTIONAL = "NON_DIRECTIONAL"
    INDETERMINATE = "INDETERMINATE"


class PriceVolumeComparisonReason(StrEnum):
    MISSING_COMPARISON_CONTEXT = "MISSING_COMPARISON_CONTEXT"
    PIVOT_CANDLE_NOT_IN_SERIES = "PIVOT_CANDLE_NOT_IN_SERIES"
    PIVOTS_NOT_IN_CHRONOLOGICAL_ORDER = "PIVOTS_NOT_IN_CHRONOLOGICAL_ORDER"
    PIVOT_DISTANCE_EXCEEDED = "PIVOT_DISTANCE_EXCEEDED"
    BELOW_CALLER_THRESHOLDS = "BELOW_CALLER_THRESHOLDS"


class VolumeEventAssessmentStatus(StrEnum):
    SUPPORTING = "SUPPORTING"
    NOT_CONFIRMING = "NOT_CONFIRMING"
    INDETERMINATE = "INDETERMINATE"


class VolumeEventAssessmentReason(StrEnum):
    MISSING_EVENT_CONTEXT = "MISSING_EVENT_CONTEXT"
    MISSING_CONFIRMATION_POLICY = "MISSING_CONFIRMATION_POLICY"
    CANDIDATE_CANDLE_NOT_IN_SERIES = "CANDIDATE_CANDLE_NOT_IN_SERIES"
    INSUFFICIENT_PRIOR_CANDLES = "INSUFFICIENT_PRIOR_CANDLES"
    ZERO_PRIOR_VOLUME_BASELINE = "ZERO_PRIOR_VOLUME_BASELINE"
    PRICE_EVENT_NOT_OBSERVED = "PRICE_EVENT_NOT_OBSERVED"


class VolumeExhaustionStatus(StrEnum):
    DATA_UNAVAILABLE = "DATA_UNAVAILABLE"


class VolumeExhaustionReason(StrEnum):
    RELIABLE_ORDER_FLOW_NOT_SUPPLIED = "RELIABLE_ORDER_FLOW_NOT_SUPPLIED"


@dataclass(frozen=True, slots=True)
class VolumeConfirmationPolicy:
    policy_id: str
    version: str
    minimum_relative_volume: Decimal

    def __post_init__(self) -> None:
        for name, value in (("policy_id", self.policy_id), ("version", self.version)):
            if (
                not isinstance(value, str)
                or not value
                or value != value.strip()
                or len(value) > 128
            ):
                raise VolumeAnalysisError(f"{name} must be bounded nonblank text.")
        if (
            type(self.minimum_relative_volume) is not Decimal
            or not self.minimum_relative_volume.is_finite()
            or self.minimum_relative_volume < 0
            or _decimal_exceeds_bounds(self.minimum_relative_volume)
        ):
            raise VolumeAnalysisError(
                "minimum_relative_volume must be a bounded nonnegative Decimal."
            )


@dataclass(frozen=True, slots=True)
class CandidateBreakoutEvent:
    market_data_id: UUID
    direction: CandidateBreakoutDirection
    reference_context_id: str
    reference_level: Decimal
    reference_unit: str

    def __post_init__(self) -> None:
        if not isinstance(self.market_data_id, UUID):
            raise VolumeAnalysisError("Candidate event needs a canonical candle ID.")
        if not isinstance(self.direction, CandidateBreakoutDirection):
            raise VolumeAnalysisError("Candidate event direction is invalid.")
        if (
            not isinstance(self.reference_context_id, str)
            or not self.reference_context_id
            or self.reference_context_id != self.reference_context_id.strip()
            or len(self.reference_context_id) > 128
        ):
            raise VolumeAnalysisError(
                "Candidate event needs explicit bounded reference context."
            )
        if (
            type(self.reference_level) is not Decimal
            or not self.reference_level.is_finite()
            or self.reference_level <= 0
            or _decimal_exceeds_bounds(self.reference_level)
        ):
            raise VolumeAnalysisError(
                "Candidate event reference level must be a bounded positive Decimal."
            )
        if (
            not isinstance(self.reference_unit, str)
            or not self.reference_unit
            or self.reference_unit != self.reference_unit.strip()
            or len(self.reference_unit) > 128
        ):
            raise VolumeAnalysisError("Candidate event reference unit is invalid.")


@dataclass(frozen=True, slots=True)
class PriceVolumeComparisonContext:
    context_id: str
    version: str
    first_pivot_market_data_id: UUID
    second_pivot_market_data_id: UUID
    price_field: VolumePivotPriceField
    maximum_candle_distance: int
    minimum_price_change: Decimal
    minimum_volume_change: Decimal

    def __post_init__(self) -> None:
        for name, text_value in (
            ("context_id", self.context_id),
            ("version", self.version),
        ):
            if (
                not isinstance(text_value, str)
                or not text_value
                or text_value != text_value.strip()
                or len(text_value) > 128
            ):
                raise VolumeAnalysisError(f"{name} must be bounded nonblank text.")
        if not isinstance(self.first_pivot_market_data_id, UUID) or not isinstance(
            self.second_pivot_market_data_id, UUID
        ):
            raise VolumeAnalysisError("Comparison pivots need canonical candle IDs.")
        if not isinstance(self.price_field, VolumePivotPriceField):
            raise VolumeAnalysisError("Comparison price field must be high or low.")
        if (
            type(self.maximum_candle_distance) is not int
            or not 1 <= self.maximum_candle_distance <= 500
        ):
            raise VolumeAnalysisError(
                "Maximum comparison distance must be an integer in [1, 500]."
            )
        for name, threshold_value in (
            ("minimum_price_change", self.minimum_price_change),
            ("minimum_volume_change", self.minimum_volume_change),
        ):
            if (
                type(threshold_value) is not Decimal
                or not threshold_value.is_finite()
                or threshold_value < 0
                or _decimal_exceeds_bounds(threshold_value)
            ):
                raise VolumeAnalysisError(
                    f"{name} must be a bounded nonnegative Decimal."
                )


@dataclass(frozen=True, slots=True)
class VolumeConfirmationPoint:
    candle_end: datetime
    raw_volume: Decimal
    prior_volume_sum: Decimal | None
    trailing_average: Decimal | None
    relative_volume: Decimal | None
    status: VolumeConfirmationPointStatus
    reason: VolumeConfirmationPointReason | None = None

    def __post_init__(self) -> None:
        if (
            not isinstance(self.candle_end, datetime)
            or self.candle_end.utcoffset() is None
        ):
            raise VolumeAnalysisError("Volume point candle end must be timezone-aware.")
        if (
            type(self.raw_volume) is not Decimal
            or not self.raw_volume.is_finite()
            or self.raw_volume < 0
        ):
            raise VolumeAnalysisError("Raw candle volume must be a finite Decimal.")
        if not isinstance(self.status, VolumeConfirmationPointStatus):
            raise VolumeAnalysisError("Volume point status is invalid.")
        if self.status is VolumeConfirmationPointStatus.READY:
            if (
                type(self.prior_volume_sum) is not Decimal
                or not self.prior_volume_sum.is_finite()
                or self.prior_volume_sum <= 0
                or type(self.trailing_average) is not Decimal
                or not self.trailing_average.is_finite()
                or self.trailing_average <= 0
                or type(self.relative_volume) is not Decimal
                or not self.relative_volume.is_finite()
                or self.reason is not None
            ):
                raise VolumeAnalysisError("A ready volume point needs valid values.")
        elif self.reason is VolumeConfirmationPointReason.INSUFFICIENT_PRIOR_CANDLES:
            if (
                self.prior_volume_sum is not None
                or self.trailing_average is not None
                or self.relative_volume is not None
            ):
                raise VolumeAnalysisError(
                    "A warm-up volume point cannot expose a baseline."
                )
        elif self.reason is VolumeConfirmationPointReason.ZERO_PRIOR_VOLUME_BASELINE:
            if (
                type(self.prior_volume_sum) is not Decimal
                or self.prior_volume_sum != 0
                or type(self.trailing_average) is not Decimal
                or self.trailing_average != 0
                or self.relative_volume is not None
            ):
                raise VolumeAnalysisError(
                    "A zero-baseline volume point must preserve its zero baseline."
                )
        else:
            raise VolumeAnalysisError(
                "An unavailable volume point needs a stable reason."
            )


@dataclass(frozen=True, slots=True)
class VolumeEventAssessment:
    status: VolumeEventAssessmentStatus
    reason: VolumeEventAssessmentReason | None
    event_market_data_id: UUID | None
    direction: CandidateBreakoutDirection | None
    reference_context_id: str | None
    reference_level: Decimal | None
    reference_unit: str | None
    event_close: Decimal | None
    raw_volume: Decimal | None
    prior_volume_sum: Decimal | None
    trailing_average: Decimal | None
    relative_volume: Decimal | None
    policy_id: str | None
    policy_version: str | None
    minimum_relative_volume: Decimal | None


@dataclass(frozen=True, slots=True)
class PriceVolumeComparison:
    status: PriceVolumeComparisonStatus
    reason: PriceVolumeComparisonReason | None
    context_id: str | None
    context_version: str | None
    first_pivot_market_data_id: UUID | None
    second_pivot_market_data_id: UUID | None
    price_field: VolumePivotPriceField | None
    maximum_candle_distance: int | None
    first_price: Decimal | None
    second_price: Decimal | None
    first_volume: Decimal | None
    second_volume: Decimal | None
    minimum_price_change: Decimal | None
    minimum_volume_change: Decimal | None
    price_unit: str | None
    volume_unit: str | None
    method: str
    method_version: str


@dataclass(frozen=True, slots=True)
class VolumeExhaustionAssessment:
    status: VolumeExhaustionStatus
    reason: VolumeExhaustionReason
    method_version: str


@dataclass(frozen=True, slots=True)
class VolumeConfirmationSeries:
    indicator_id: str
    metadata_version: str
    calculation_version: str
    method_label: str
    timeframe: str
    instrument_id: str
    venue_id: str
    snapshot_id: UUID
    quality_report_id: UUID
    quality_status: DataQualityStatus
    as_of: datetime
    source_record_ids: tuple[UUID, ...]
    volume_unit: str
    price_unit: str
    lookback: int
    calculation_precision: int
    window_start: datetime
    window_end: datetime
    input_market_data_ids: tuple[UUID, ...]
    points: tuple[VolumeConfirmationPoint, ...]
    assessment: VolumeEventAssessment
    price_volume_comparison: PriceVolumeComparison
    exhaustion_assessment: VolumeExhaustionAssessment
    limitations: tuple[str, ...]


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


def _decimal_exceeds_bounds(value: Decimal) -> bool:
    exponent = value.as_tuple().exponent
    return (
        not isinstance(exponent, int)
        or abs(exponent) > _MAX_DECIMAL_EXPONENT
        or abs(value.adjusted()) > _MAX_DECIMAL_EXPONENT
    )


def _relative_volume_meets_threshold(
    volume: Decimal,
    prior_volume_sum: Decimal,
    lookback: int,
    threshold: Decimal,
) -> bool:
    volume_numerator, volume_denominator = volume.as_integer_ratio()
    sum_numerator, sum_denominator = prior_volume_sum.as_integer_ratio()
    threshold_numerator, threshold_denominator = threshold.as_integer_ratio()
    return (
        volume_numerator * lookback * threshold_denominator * sum_denominator
        >= threshold_numerator * sum_numerator * volume_denominator
    )


def _absolute_change_meets_threshold(
    first: Decimal,
    second: Decimal,
    threshold: Decimal,
) -> bool:
    first_numerator, first_denominator = first.as_integer_ratio()
    second_numerator, second_denominator = second.as_integer_ratio()
    threshold_numerator, threshold_denominator = threshold.as_integer_ratio()
    return (
        abs(second_numerator * first_denominator - first_numerator * second_denominator)
        * threshold_denominator
        >= threshold_numerator * first_denominator * second_denominator
    )


def _price_volume_comparison(
    *,
    context: PriceVolumeComparisonContext | None,
    observations: tuple[MarketData, ...],
    points: tuple[VolumeConfirmationPoint, ...],
    price_unit: str,
    volume_unit: str,
) -> PriceVolumeComparison:
    status = PriceVolumeComparisonStatus.INDETERMINATE
    reason: PriceVolumeComparisonReason | None = None
    first_index: int | None = None
    second_index: int | None = None
    first_price: Decimal | None = None
    second_price: Decimal | None = None
    first_volume: Decimal | None = None
    second_volume: Decimal | None = None

    if context is None:
        reason = PriceVolumeComparisonReason.MISSING_COMPARISON_CONTEXT
    else:
        index_by_id = {
            item.market_data_id: index for index, item in enumerate(observations)
        }
        first_index = index_by_id.get(context.first_pivot_market_data_id)
        second_index = index_by_id.get(context.second_pivot_market_data_id)
        if first_index is None or second_index is None:
            reason = PriceVolumeComparisonReason.PIVOT_CANDLE_NOT_IN_SERIES
        elif first_index >= second_index:
            reason = PriceVolumeComparisonReason.PIVOTS_NOT_IN_CHRONOLOGICAL_ORDER
        elif second_index - first_index > context.maximum_candle_distance:
            reason = PriceVolumeComparisonReason.PIVOT_DISTANCE_EXCEEDED
        else:
            first_price = next(
                metric.value
                for metric in observations[first_index].metrics
                if metric.metric_name == context.price_field.value
            )
            second_price = next(
                metric.value
                for metric in observations[second_index].metrics
                if metric.metric_name == context.price_field.value
            )
            first_volume = points[first_index].raw_volume
            second_volume = points[second_index].raw_volume
            price_increased = second_price > first_price
            price_decreased = second_price < first_price
            volume_increased = second_volume > first_volume
            volume_decreased = second_volume < first_volume
            if not (
                _absolute_change_meets_threshold(
                    first_price, second_price, context.minimum_price_change
                )
                and _absolute_change_meets_threshold(
                    first_volume, second_volume, context.minimum_volume_change
                )
            ):
                reason = PriceVolumeComparisonReason.BELOW_CALLER_THRESHOLDS
            elif not (price_increased or price_decreased) or not (
                volume_increased or volume_decreased
            ):
                status = PriceVolumeComparisonStatus.NON_DIRECTIONAL
            elif price_increased != volume_increased:
                status = PriceVolumeComparisonStatus.DIVERGENT
            else:
                status = PriceVolumeComparisonStatus.ALIGNED

    return PriceVolumeComparison(
        status=status,
        reason=reason,
        context_id=context.context_id if context is not None else None,
        context_version=context.version if context is not None else None,
        first_pivot_market_data_id=(
            context.first_pivot_market_data_id if context is not None else None
        ),
        second_pivot_market_data_id=(
            context.second_pivot_market_data_id if context is not None else None
        ),
        price_field=context.price_field if context is not None else None,
        maximum_candle_distance=(
            context.maximum_candle_distance if context is not None else None
        ),
        first_price=first_price,
        second_price=second_price,
        first_volume=first_volume,
        second_volume=second_volume,
        minimum_price_change=(
            context.minimum_price_change if context is not None else None
        ),
        minimum_volume_change=(
            context.minimum_volume_change if context is not None else None
        ),
        price_unit=price_unit if context is not None else None,
        volume_unit=volume_unit if context is not None else None,
        method=PIVOT_COMPARISON_METHOD,
        method_version=PIVOT_COMPARISON_VERSION,
    )


def _typical_prices(
    candles: tuple[tuple[Decimal, Decimal, Decimal], ...],
) -> tuple[Decimal, ...]:
    return tuple((high + low + close) / Decimal(3) for high, low, close in candles)


def _assess_candidate_event(
    *,
    event: CandidateBreakoutEvent | None,
    policy: VolumeConfirmationPolicy | None,
    observations: tuple[MarketData, ...],
    price_unit: str,
    points: tuple[VolumeConfirmationPoint, ...],
    lookback: int,
) -> VolumeEventAssessment:
    status = VolumeEventAssessmentStatus.INDETERMINATE
    reason: VolumeEventAssessmentReason | None = None
    index: int | None = None

    if event is None:
        reason = VolumeEventAssessmentReason.MISSING_EVENT_CONTEXT
    elif event.reference_unit != price_unit:
        raise VolumeAnalysisError(
            "Candidate reference level unit must match the Spot price unit."
        )
    else:
        index = next(
            (
                position
                for position, item in enumerate(observations)
                if item.market_data_id == event.market_data_id
            ),
            None,
        )
        if index is None:
            reason = VolumeEventAssessmentReason.CANDIDATE_CANDLE_NOT_IN_SERIES
        elif policy is None:
            reason = VolumeEventAssessmentReason.MISSING_CONFIRMATION_POLICY
        elif index < lookback:
            reason = VolumeEventAssessmentReason.INSUFFICIENT_PRIOR_CANDLES
        elif (
            points[index].reason
            is VolumeConfirmationPointReason.ZERO_PRIOR_VOLUME_BASELINE
        ):
            reason = VolumeEventAssessmentReason.ZERO_PRIOR_VOLUME_BASELINE
        else:
            previous_close = next(
                metric.value
                for metric in observations[index - 1].metrics
                if metric.metric_name == "close"
            )
            close = next(
                metric.value
                for metric in observations[index].metrics
                if metric.metric_name == "close"
            )
            event_crossed = (
                previous_close <= event.reference_level < close
                if event.direction is CandidateBreakoutDirection.UP
                else previous_close >= event.reference_level > close
            )
            if not event_crossed:
                reason = VolumeEventAssessmentReason.PRICE_EVENT_NOT_OBSERVED
            else:
                event_point = points[index]
                if (
                    event_point.relative_volume is None
                    or event_point.prior_volume_sum is None
                    or event_point.trailing_average is None
                ):
                    reason = VolumeEventAssessmentReason.INSUFFICIENT_PRIOR_CANDLES
                else:
                    status = (
                        VolumeEventAssessmentStatus.SUPPORTING
                        if _relative_volume_meets_threshold(
                            event_point.raw_volume,
                            event_point.prior_volume_sum,
                            lookback,
                            policy.minimum_relative_volume,
                        )
                        else VolumeEventAssessmentStatus.NOT_CONFIRMING
                    )

    event_close = None
    selected_point: VolumeConfirmationPoint | None = None
    if index is not None:
        event_close = next(
            metric.value
            for metric in observations[index].metrics
            if metric.metric_name == "close"
        )
        selected_point = points[index]

    return VolumeEventAssessment(
        status=status,
        reason=reason,
        event_market_data_id=event.market_data_id if event is not None else None,
        direction=event.direction if event is not None else None,
        reference_context_id=event.reference_context_id if event is not None else None,
        reference_level=event.reference_level if event is not None else None,
        reference_unit=event.reference_unit if event is not None else None,
        event_close=event_close,
        raw_volume=selected_point.raw_volume if selected_point is not None else None,
        prior_volume_sum=(
            selected_point.prior_volume_sum if selected_point is not None else None
        ),
        trailing_average=(
            selected_point.trailing_average if selected_point is not None else None
        ),
        relative_volume=(
            selected_point.relative_volume if selected_point is not None else None
        ),
        policy_id=policy.policy_id if policy is not None else None,
        policy_version=policy.version if policy is not None else None,
        minimum_relative_volume=(
            policy.minimum_relative_volume if policy is not None else None
        ),
    )


def calculate_volume_confirmation(
    *,
    snapshot: MarketSnapshot,
    observations: tuple[MarketData, ...],
    quality: DataQualityReport,
    lookback: int = 20,
    timeframe: str = "1m",
    metadata_version: str = "1",
    candidate_event: CandidateBreakoutEvent | None = None,
    policy: VolumeConfirmationPolicy | None = None,
    comparison_context: PriceVolumeComparisonContext | None = None,
) -> VolumeConfirmationSeries:
    """Calculate descriptive trailing relative volume and an optional event assessment.

    Each candle's baseline uses exactly the preceding ``lookback`` completed
    candles, excluding the candle being measured. A classification is produced
    only for a supplied candidate event and explicit versioned policy. This
    calculation does not discover price levels or pivots. Its optional pivot
    comparison uses explicitly selected high/low fields, raw candle volumes,
    and caller-supplied minimum changes; it labels only opposite changes meeting
    both thresholds. Because this accepts OHLCV only, any exhaustion/order-flow
    assessment remains DATA_UNAVAILABLE rather than inferred from candle data.
    """
    metadata = _metadata(
        "volume-confirmation", metadata_version, timeframe, (lookback,)
    )
    if candidate_event is not None and not isinstance(
        candidate_event, CandidateBreakoutEvent
    ):
        raise VolumeAnalysisError("candidate_event must be explicit event context.")
    if policy is not None and not isinstance(policy, VolumeConfirmationPolicy):
        raise VolumeAnalysisError("policy must be an explicit confirmation policy.")
    if comparison_context is not None and not isinstance(
        comparison_context, PriceVolumeComparisonContext
    ):
        raise VolumeAnalysisError("comparison_context must explicitly identify pivots.")
    candles, volumes, price_unit, volume_unit = _inputs(
        snapshot=snapshot,
        observations=observations,
        quality=quality,
        timeframe=timeframe,
    )
    precision = _calculation_precision(candles, volumes, 1)
    interval = timedelta(seconds=_INTERVALS[timeframe])
    with localcontext() as context:
        context.prec = precision
        points: list[VolumeConfirmationPoint] = []
        for index, (item, volume) in enumerate(zip(observations, volumes, strict=True)):
            end = item.event_time + interval
            if index < lookback:
                points.append(
                    VolumeConfirmationPoint(
                        candle_end=end,
                        raw_volume=volume,
                        prior_volume_sum=None,
                        trailing_average=None,
                        relative_volume=None,
                        status=VolumeConfirmationPointStatus.UNAVAILABLE,
                        reason=VolumeConfirmationPointReason.INSUFFICIENT_PRIOR_CANDLES,
                    )
                )
                continue
            prior_volume_sum = sum(volumes[index - lookback : index], Decimal(0))
            if prior_volume_sum == 0:
                points.append(
                    VolumeConfirmationPoint(
                        candle_end=end,
                        raw_volume=volume,
                        prior_volume_sum=prior_volume_sum,
                        trailing_average=Decimal(0),
                        relative_volume=None,
                        status=VolumeConfirmationPointStatus.UNAVAILABLE,
                        reason=VolumeConfirmationPointReason.ZERO_PRIOR_VOLUME_BASELINE,
                    )
                )
                continue
            baseline = prior_volume_sum / Decimal(lookback)
            points.append(
                VolumeConfirmationPoint(
                    candle_end=end,
                    raw_volume=volume,
                    prior_volume_sum=prior_volume_sum,
                    trailing_average=baseline,
                    relative_volume=(volume * Decimal(lookback) / prior_volume_sum),
                    status=VolumeConfirmationPointStatus.READY,
                )
            )

    typed_points = tuple(points)
    assessment = _assess_candidate_event(
        event=candidate_event,
        policy=policy,
        observations=observations,
        price_unit=price_unit,
        points=typed_points,
        lookback=lookback,
    )
    comparison = _price_volume_comparison(
        context=comparison_context,
        observations=observations,
        points=typed_points,
        price_unit=price_unit,
        volume_unit=volume_unit,
    )
    exhaustion = VolumeExhaustionAssessment(
        status=VolumeExhaustionStatus.DATA_UNAVAILABLE,
        reason=VolumeExhaustionReason.RELIABLE_ORDER_FLOW_NOT_SUPPLIED,
        method_version="reliable-order-flow-input-required-v1",
    )
    return VolumeConfirmationSeries(
        indicator_id=metadata.indicator_id,
        metadata_version=metadata.metadata_version,
        calculation_version=metadata.calculation_version,
        method_label="trailing mean of prior completed candle volumes",
        timeframe=timeframe,
        instrument_id=snapshot.instrument_id,
        venue_id=snapshot.venue_id,
        snapshot_id=snapshot.snapshot_id,
        quality_report_id=quality.report_id,
        quality_status=quality.status,
        as_of=snapshot.as_of,
        source_record_ids=snapshot.source_record_ids,
        volume_unit=volume_unit,
        price_unit=price_unit,
        lookback=lookback,
        calculation_precision=precision,
        window_start=observations[0].event_time,
        window_end=_window_end(observations, timeframe),
        input_market_data_ids=snapshot.market_data_ids,
        points=typed_points,
        assessment=assessment,
        price_volume_comparison=comparison,
        exhaustion_assessment=exhaustion,
        limitations=(
            "Analysis-only descriptive evidence; it is not a signal, strategy "
            "decision, validation result, risk decision, or execution permission.",
            "Volume measurements are correlated with the supplied OHLCV, VWAP, "
            "volume profile, and other OHLCV-derived features.",
            "Price-volume comparison is descriptive only: it compares caller-named "
            "high/low pivot candles and labels opposing raw price/volume changes as "
            "divergent; it does not infer hidden pivots or validate pivot quality.",
            "Exhaustion/order-flow evidence is DATA_UNAVAILABLE because reliable "
            "order-flow inputs are not supplied; OHLCV alone cannot establish "
            "trade-level absorption or aggressive buying/selling.",
            "No support/resistance discovery or order-flow claim is produced; OHLCV "
            "alone cannot establish trade-level absorption or aggressive "
            "buying/selling.",
        ),
    )


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
        context.prec = _calculation_precision(candles, volumes, 1)
        cumulative_volume = Decimal(0)
        cumulative_price_volume = Decimal(0)
        points: list[VWAPPoint] = []
        for item, candle, volume in zip(observations, candles, volumes, strict=True):
            cumulative_volume += volume
            cumulative_price_volume += sum(candle, Decimal(0)) * volume
            value = (
                VWAPValue(
                    cumulative_price_volume / (Decimal(3) * cumulative_volume),
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


def _calculation_precision(
    candles: tuple[tuple[Decimal, Decimal, Decimal], ...],
    volumes: tuple[Decimal, ...],
    bin_count: int,
) -> int:
    values = tuple(value for candle in candles for value in candle) + volumes
    significant_values = tuple(value for value in values if value != 0)
    exponents: list[int] = []
    for value in significant_values:
        exponent = value.as_tuple().exponent
        if not isinstance(exponent, int):
            raise VolumeAnalysisError("Finite Decimal input values are required.")
        if (
            abs(exponent) > _MAX_DECIMAL_EXPONENT
            or abs(value.adjusted()) > _MAX_DECIMAL_EXPONENT
        ):
            raise VolumeAnalysisError("Input exponent exceeds the calculation bound.")
        exponents.append(exponent)
    input_span = (
        max(value.adjusted() for value in significant_values) - min(exponents) + 1
    )
    precision = max(
        _DECIMAL_PRECISION,
        2 * input_span + len(str(len(volumes))) + len(str(bin_count)) + 8,
    )
    if precision > _MAX_DECIMAL_PRECISION:
        raise VolumeAnalysisError("Input precision exceeds the calculation bound.")
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
        context.prec = _calculation_precision(candles, volumes, bin_count)
        typical_prices = _typical_prices(candles)
        minimum = min(low for _, low, _ in candles)
        maximum = max(high for high, _, _ in candles)
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
    "CandidateBreakoutDirection",
    "CandidateBreakoutEvent",
    "PIVOT_COMPARISON_METHOD",
    "PIVOT_COMPARISON_VERSION",
    "PriceVolumeComparison",
    "PriceVolumeComparisonContext",
    "PriceVolumeComparisonReason",
    "PriceVolumeComparisonStatus",
    "VOLUME_PROFILE_METHOD",
    "VWAP_METHOD",
    "VolumePivotPriceField",
    "VolumeAnalysisError",
    "VolumeConfirmationPoint",
    "VolumeConfirmationPointReason",
    "VolumeConfirmationPointStatus",
    "VolumeConfirmationSeries",
    "VolumeEventAssessment",
    "VolumeEventAssessmentReason",
    "VolumeEventAssessmentStatus",
    "VolumeExhaustionAssessment",
    "VolumeExhaustionReason",
    "VolumeExhaustionStatus",
    "VolumeConfirmationPolicy",
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
