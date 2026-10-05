"""Deterministic, analysis-only Spot candle and support/resistance observations."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal, localcontext
from enum import StrEnum
from uuid import UUID, uuid5

from trading_platform_api.analysis.contracts import (
    AnalyticalFinding,
    AssessmentStatus,
    ClaimClassification,
    EvidenceItem,
    EvidenceRelation,
    MethodologyCategory,
    TechnicalAssessment,
    VersionReference,
)
from trading_platform_api.analysis.indicator_registry import (
    SPOT_RESEARCH_INDICATORS,
    IndicatorMetadataError,
    IndicatorPhase,
)
from trading_platform_api.analysis.volatility import VolatilityError, _ohlc
from trading_platform_api.contracts.serialization import (
    CANONICAL_JSON_VERSION,
    MAX_DOCUMENT_BYTES,
    canonical_json_dumps,
)
from trading_platform_api.market_data.contracts import (
    DataQualityReport,
    MarketData,
    MarketSnapshot,
)

PRICE_ACTION_INDICATOR_ID = "price-action-support-resistance"
PRICE_ACTION_METADATA_VERSION = "1"
PRICE_ACTION_METHOD_VERSION = "spot-price-action-geometry-patterns-pivots-zones-v1"
EVIDENCE_SCHEMA_VERSION = "spot-price-action-evidence-v1"
BASELINE_METHOD_VERSION = (
    "prior-closed-ranges-arithmetic-mean-34dp-strict-boundaries-v1"
)

_INTERVALS = {
    "1m": 60,
    "5m": 300,
    "15m": 900,
    "1h": 3600,
    "4h": 14400,
    "1d": 86400,
}
_MAX_CANDLES = 10_000
_MAX_POLICY_TEXT = 128
_WORK_PRECISION = 512
_RATIO_PRECISION = 34
_IDENTITY_NAMESPACE = UUID("f3c843ab-ea8f-5e24-9622-17a21c065f1c")


class PriceActionError(ValueError):
    """Price-action observations cannot be calculated safely."""


class CloseLocationReason(StrEnum):
    ZERO_RANGE = "ZERO_RANGE"


class RangeComparisonReason(StrEnum):
    NO_CALLER_BASELINE = "NO_CALLER_BASELINE"
    INSUFFICIENT_BASELINE = "INSUFFICIENT_BASELINE"
    ZERO_BASELINE = "ZERO_BASELINE"


class RangeDirection(StrEnum):
    EXPANSION = "EXPANSION"
    CONTRACTION = "CONTRACTION"
    UNCHANGED = "UNCHANGED"


class PatternLabel(StrEnum):
    ENGULFING_BULLISH = "engulfing-bullish"
    ENGULFING_BEARISH = "engulfing-bearish"
    PIN_BAR_BULLISH = "pin-bar-bullish"
    PIN_BAR_BEARISH = "pin-bar-bearish"
    HAMMER = "hammer"
    SHOOTING_STAR = "shooting-star"
    INSIDE_BAR = "inside-bar"
    OUTSIDE_BAR = "outside-bar"
    DOJI = "doji"
    MORNING_STAR = "morning-star"
    EVENING_STAR = "evening-star"


class PivotKind(StrEnum):
    HIGH = "HIGH"
    LOW = "LOW"


class ZoneStatus(StrEnum):
    CANDIDATE = "CANDIDATE"
    REPEATED = "REPEATED"
    BROKEN = "BROKEN"


def _bounded_decimal(name: str, value: object) -> Decimal:
    if type(value) is not Decimal or not value.is_finite():
        raise PriceActionError(f"{name} must be a finite Decimal.")
    decimal_tuple = value.as_tuple()
    if (
        len(decimal_tuple.digits) > 64
        or not isinstance(decimal_tuple.exponent, int)
        or abs(decimal_tuple.exponent) > 128
        or abs(value.adjusted()) > 128
    ):
        raise PriceActionError(f"{name} exceeds Decimal precision or exponent bounds.")
    return value


def _bounded_text(name: str, value: object) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or len(value) > _MAX_POLICY_TEXT
    ):
        raise PriceActionError(f"{name} must be bounded nonblank text.")
    return value


def _policy_decimal(
    name: str,
    value: object,
    *,
    minimum: Decimal,
    maximum: Decimal,
    minimum_exclusive: bool = False,
) -> Decimal:
    result = _bounded_decimal(name, value)
    if (
        result < minimum
        or result > maximum
        or (minimum_exclusive and result == minimum)
    ):
        raise PriceActionError(f"{name} is outside its supported policy bounds.")
    return result


def _positive_window(name: str, value: object, *, maximum: int = 500) -> int:
    if type(value) is not int or not 1 <= value <= maximum:
        raise PriceActionError(f"{name} must be an integer in [1, {maximum}].")
    return value


@dataclass(frozen=True, slots=True)
class RangeBaselinePolicy:
    """Compare each range with the prior-period arithmetic mean at 34 digits.

    Expansion and contraction use strict `mean * (1 +/- threshold)` boundaries;
    equality is unchanged. The current candle is excluded from its baseline.
    """

    policy_id: str
    version: str
    period: int
    expansion_contraction_threshold: Decimal

    def __post_init__(self) -> None:
        _bounded_text("policy_id", self.policy_id)
        _bounded_text("version", self.version)
        _positive_window("baseline period", self.period)
        _policy_decimal(
            "expansion_contraction_threshold",
            self.expansion_contraction_threshold,
            minimum=Decimal(0),
            maximum=Decimal(1),
        )
        if self.expansion_contraction_threshold == Decimal(1):
            raise PriceActionError("Range threshold must be less than one.")


@dataclass(frozen=True, slots=True)
class PatternPolicy:
    """Caller thresholds define these contextual rules; no implicit values apply.

    Engulfing requires opposite nonzero body signs, both body/range fractions at
    least the configured minimum, and current real-body endpoints covering the
    previous real body inclusively. Pin bars require the configured dominant
    wick/body minimum, body/range maximum, and opposite-wick/range maximum; lower
    wick yields bullish and upper wick bearish. Hammer uses the configured lower
    wick/body minimum and close-location minimum, plus the pin body/opposite-wick
    maxima. Shooting star uses the corresponding upper wick/body minimum and
    close-location maximum. Inside/outside bars require strict range containment
    or strict range enclosure respectively (identical ranges match neither).
    Doji compares absolute body/range to its maximum. Morning/evening stars require
    opposite first/third body signs, a middle body no larger than the configured
    fraction of the first body, and third-close penetration of the first body by
    the configured fraction. No opening-gap assumption is made.
    """

    policy_id: str
    version: str
    engulfing_minimum_body_fraction: Decimal
    pin_bar_minimum_wick_to_body: Decimal
    pin_bar_maximum_body_fraction: Decimal
    pin_bar_maximum_opposite_wick_fraction: Decimal
    hammer_minimum_lower_wick_to_body: Decimal
    hammer_minimum_close_location: Decimal
    shooting_star_minimum_upper_wick_to_body: Decimal
    shooting_star_maximum_close_location: Decimal
    doji_maximum_body_fraction: Decimal
    star_middle_maximum_body_to_first_body: Decimal
    star_minimum_first_body_penetration: Decimal

    def __post_init__(self) -> None:
        _bounded_text("policy_id", self.policy_id)
        _bounded_text("version", self.version)
        for name in (
            "engulfing_minimum_body_fraction",
            "pin_bar_maximum_body_fraction",
            "pin_bar_maximum_opposite_wick_fraction",
            "hammer_minimum_close_location",
            "shooting_star_maximum_close_location",
            "doji_maximum_body_fraction",
            "star_middle_maximum_body_to_first_body",
            "star_minimum_first_body_penetration",
        ):
            _policy_decimal(
                name,
                getattr(self, name),
                minimum=Decimal(0),
                maximum=Decimal(1),
            )
        for name in (
            "pin_bar_minimum_wick_to_body",
            "hammer_minimum_lower_wick_to_body",
            "shooting_star_minimum_upper_wick_to_body",
        ):
            _policy_decimal(
                name,
                getattr(self, name),
                minimum=Decimal(1),
                maximum=Decimal(1000),
            )


@dataclass(frozen=True, slots=True)
class SupportResistancePolicy:
    policy_id: str
    version: str
    left_window: int
    right_window: int
    price_tolerance: Decimal
    price_unit: str
    minimum_repeated_interactions: int
    close_break_buffer: Decimal
    break_close_count: int

    def __post_init__(self) -> None:
        _bounded_text("policy_id", self.policy_id)
        _bounded_text("version", self.version)
        _bounded_text("price_unit", self.price_unit)
        _positive_window("left_window", self.left_window)
        _positive_window("right_window", self.right_window)
        _policy_decimal(
            "price_tolerance",
            self.price_tolerance,
            minimum=Decimal(0),
            maximum=Decimal("1e128"),
            minimum_exclusive=True,
        )
        _positive_window(
            "minimum_repeated_interactions",
            self.minimum_repeated_interactions,
            maximum=_MAX_CANDLES,
        )
        _policy_decimal(
            "close_break_buffer",
            self.close_break_buffer,
            minimum=Decimal(0),
            maximum=Decimal("1e128"),
        )
        _positive_window("break_close_count", self.break_close_count)


@dataclass(frozen=True, slots=True)
class PatternObservation:
    label: PatternLabel
    source_market_data_ids: tuple[UUID, ...]
    source_times: tuple[datetime, ...]
    confirmation_market_data_id: UUID
    confirmation_time: datetime
    method_version: str
    policy_id: str
    policy_version: str
    invalidation_condition: str


@dataclass(frozen=True, slots=True)
class CandleGeometry:
    market_data_id: UUID
    candle_time: datetime
    candle_end: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    signed_body: Decimal
    absolute_body: Decimal
    range: Decimal
    upper_wick: Decimal
    lower_wick: Decimal
    close_location: Decimal | None
    close_location_reason: CloseLocationReason | None
    baseline_mean_range: Decimal | None
    baseline_period: int | None
    baseline_policy_id: str | None
    baseline_policy_version: str | None
    baseline_method_version: str | None
    range_direction: RangeDirection | None
    range_comparison_reason: RangeComparisonReason | None
    patterns: tuple[PatternObservation, ...]


@dataclass(frozen=True, slots=True)
class PivotObservation:
    pivot_id: UUID
    kind: PivotKind
    price: Decimal
    source_market_data_id: UUID
    source_time: datetime
    confirmation_market_data_id: UUID
    confirmation_time: datetime
    left_window: int
    right_window: int
    tie_rule: str
    method_version: str


@dataclass(frozen=True, slots=True)
class ZoneInteraction:
    market_data_id: UUID
    candle_time: datetime
    candle_end: datetime


@dataclass(frozen=True, slots=True)
class SupportResistanceZone:
    zone_id: UUID
    kind: PivotKind
    anchor_price: Decimal
    lower_price: Decimal
    upper_price: Decimal
    price_unit: str
    timeframe: str
    method_version: str
    policy_id: str
    policy_version: str
    creation_time: datetime
    confirmation_market_data_id: UUID
    contributor_pivot_ids: tuple[UUID, ...]
    contributor_market_data_ids: tuple[UUID, ...]
    interactions: tuple[ZoneInteraction, ...]
    status: ZoneStatus
    invalidated_at: datetime | None
    invalidation_condition: str


@dataclass(frozen=True, slots=True)
class _EvidencePayload:
    payload_version: str
    method_version: str
    timeframe: str
    instrument_id: str
    venue_id: str
    price_unit: str
    snapshot_id: UUID
    quality_report_id: UUID
    as_of: datetime
    source_record_ids: tuple[UUID, ...]
    input_market_data_ids: tuple[UUID, ...]
    range_baseline_policy: RangeBaselinePolicy | None
    pattern_policy: PatternPolicy | None
    support_resistance_policy: SupportResistancePolicy | None
    geometry: tuple[CandleGeometry, ...]
    pivots: tuple[PivotObservation, ...]
    zones: tuple[SupportResistanceZone, ...]
    uncertainty: tuple[str, ...]
    limitations: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class PriceActionAnalysis:
    indicator_id: str
    metadata_version: str
    method_version: str
    timeframe: str
    instrument_id: str
    venue_id: str
    snapshot_id: UUID
    quality_report_id: UUID
    as_of: datetime
    source_record_ids: tuple[UUID, ...]
    input_market_data_ids: tuple[UUID, ...]
    price_unit: str
    range_baseline_policy: RangeBaselinePolicy | None
    pattern_policy: PatternPolicy | None
    support_resistance_policy: SupportResistancePolicy | None
    geometry: tuple[CandleGeometry, ...]
    pivots: tuple[PivotObservation, ...]
    zones: tuple[SupportResistanceZone, ...]
    uncertainty: tuple[str, ...]
    limitations: tuple[str, ...]
    evidence: EvidenceItem
    assessment: TechnicalAssessment


def _candle_end(candle: MarketData, timeframe: str) -> datetime:
    return candle.event_time + timedelta(seconds=_INTERVALS[timeframe])


def _decimals(observations: tuple[MarketData, ...]) -> tuple[tuple[Decimal, ...], ...]:
    values: list[tuple[Decimal, ...]] = []
    for candle in observations:
        metrics = {metric.metric_name: metric for metric in candle.metrics}
        if len(metrics) != len(candle.metrics):
            raise PriceActionError("Candle metric names must be unique.")
        required = ("open", "high", "low", "close", "volume")
        if not all(name in metrics for name in required):
            raise PriceActionError("Every input candle must contain canonical OHLCV.")
        values.append(
            tuple(_bounded_decimal(name, metrics[name].value) for name in required)
        )
    return tuple(values)


def _geometry(
    *,
    observations: tuple[MarketData, ...],
    values: tuple[tuple[Decimal, ...], ...],
    timeframe: str,
    baseline_policy: RangeBaselinePolicy | None,
    pattern_policy: PatternPolicy | None,
) -> tuple[CandleGeometry, ...]:
    result: list[CandleGeometry] = []
    with localcontext() as context:
        context.prec = _WORK_PRECISION
        ranges = tuple(high - low for _, high, low, _, _ in values)
        for index, (candle, (opening, high, low, close, _)) in enumerate(
            zip(observations, values, strict=True)
        ):
            body = close - opening
            candle_range = ranges[index]
            upper_wick = high - max(opening, close)
            lower_wick = min(opening, close) - low
            if candle_range:
                with localcontext() as ratio_context:
                    ratio_context.prec = _RATIO_PRECISION
                    close_location = (close - low) / candle_range
            else:
                close_location = None
            baseline_mean: Decimal | None = None
            direction: RangeDirection | None = None
            comparison_reason: RangeComparisonReason | None = None
            baseline_period: int | None = None
            baseline_id: str | None = None
            baseline_version: str | None = None
            if baseline_policy is None:
                comparison_reason = RangeComparisonReason.NO_CALLER_BASELINE
            else:
                baseline_period = baseline_policy.period
                baseline_id = baseline_policy.policy_id
                baseline_version = baseline_policy.version
                if index < baseline_policy.period:
                    comparison_reason = RangeComparisonReason.INSUFFICIENT_BASELINE
                else:
                    prior_ranges = ranges[index - baseline_policy.period : index]
                    with localcontext() as baseline_context:
                        baseline_context.prec = _RATIO_PRECISION
                        baseline_mean = sum(prior_ranges, Decimal(0)) / Decimal(
                            baseline_policy.period
                        )
                    if baseline_mean == 0:
                        comparison_reason = RangeComparisonReason.ZERO_BASELINE
                    else:
                        comparison = candle_range / baseline_mean
                        threshold = baseline_policy.expansion_contraction_threshold
                        if comparison > Decimal(1) + threshold:
                            direction = RangeDirection.EXPANSION
                        elif comparison < Decimal(1) - threshold:
                            direction = RangeDirection.CONTRACTION
                        else:
                            direction = RangeDirection.UNCHANGED
            patterns = (
                _patterns(
                    index=index,
                    observations=observations,
                    values=values,
                    policy=pattern_policy,
                    timeframe=timeframe,
                )
                if pattern_policy is not None
                else ()
            )
            result.append(
                CandleGeometry(
                    market_data_id=candle.market_data_id,
                    candle_time=candle.event_time,
                    candle_end=_candle_end(candle, timeframe),
                    open=opening,
                    high=high,
                    low=low,
                    close=close,
                    signed_body=body,
                    absolute_body=abs(body),
                    range=candle_range,
                    upper_wick=upper_wick,
                    lower_wick=lower_wick,
                    close_location=close_location,
                    close_location_reason=(
                        CloseLocationReason.ZERO_RANGE if not candle_range else None
                    ),
                    baseline_mean_range=baseline_mean,
                    baseline_period=baseline_period,
                    baseline_policy_id=baseline_id,
                    baseline_policy_version=baseline_version,
                    baseline_method_version=(
                        BASELINE_METHOD_VERSION if baseline_policy is not None else None
                    ),
                    range_direction=direction,
                    range_comparison_reason=comparison_reason,
                    patterns=patterns,
                )
            )
    return tuple(result)


def _make_pattern(
    *,
    label: PatternLabel,
    indices: tuple[int, ...],
    observations: tuple[MarketData, ...],
    policy: PatternPolicy,
    timeframe: str,
) -> PatternObservation:
    confirmation_index = indices[-1]
    confirmation = observations[confirmation_index]
    return PatternObservation(
        label=label,
        source_market_data_ids=tuple(
            observations[index].market_data_id for index in indices
        ),
        source_times=tuple(observations[index].event_time for index in indices),
        confirmation_market_data_id=confirmation.market_data_id,
        confirmation_time=_candle_end(confirmation, timeframe),
        method_version=PRICE_ACTION_METHOD_VERSION,
        policy_id=policy.policy_id,
        policy_version=policy.version,
        invalidation_condition=(
            "Superseded if a source candle is corrected or the named method or "
            "pattern-policy version changes."
        ),
    )


def _patterns(
    *,
    index: int,
    observations: tuple[MarketData, ...],
    values: tuple[tuple[Decimal, ...], ...],
    policy: PatternPolicy | None,
    timeframe: str,
) -> tuple[PatternObservation, ...]:
    if policy is None:
        return ()
    current = values[index]
    opening, high, low, close, _ = current
    current_body = close - opening
    current_range = high - low
    if current_range == 0:
        return ()
    current_body_size = abs(current_body)
    current_upper = high - max(opening, close)
    current_lower = min(opening, close) - low
    current_location = (close - low) / current_range
    current_body_fraction = current_body_size / current_range
    result: list[PatternObservation] = []

    if index >= 1:
        previous = values[index - 1]
        previous_open, previous_high, previous_low, previous_close, _ = previous
        previous_body = previous_close - previous_open
        previous_range = previous_high - previous_low
        if (
            previous_range > 0
            and current_body
            and previous_body
            and current_body_fraction >= policy.engulfing_minimum_body_fraction
            and abs(previous_body) / previous_range
            >= policy.engulfing_minimum_body_fraction
            and current_body * previous_body < 0
            and min(opening, close) <= min(previous_open, previous_close)
            and max(opening, close) >= max(previous_open, previous_close)
        ):
            label = (
                PatternLabel.ENGULFING_BULLISH
                if current_body > 0
                else PatternLabel.ENGULFING_BEARISH
            )
            result.append(
                _make_pattern(
                    label=label,
                    indices=(index - 1, index),
                    observations=observations,
                    policy=policy,
                    timeframe=timeframe,
                )
            )
        if (
            high <= previous_high
            and low >= previous_low
            and (high < previous_high or low > previous_low)
        ):
            result.append(
                _make_pattern(
                    label=PatternLabel.INSIDE_BAR,
                    indices=(index - 1, index),
                    observations=observations,
                    policy=policy,
                    timeframe=timeframe,
                )
            )
        if (
            high >= previous_high
            and low <= previous_low
            and (high > previous_high or low < previous_low)
        ):
            result.append(
                _make_pattern(
                    label=PatternLabel.OUTSIDE_BAR,
                    indices=(index - 1, index),
                    observations=observations,
                    policy=policy,
                    timeframe=timeframe,
                )
            )
    if current_body_size:
        if (
            current_lower / current_body_size >= policy.pin_bar_minimum_wick_to_body
            and current_body_fraction <= policy.pin_bar_maximum_body_fraction
            and current_upper / current_range
            <= policy.pin_bar_maximum_opposite_wick_fraction
        ):
            result.append(
                _make_pattern(
                    label=PatternLabel.PIN_BAR_BULLISH,
                    indices=(index,),
                    observations=observations,
                    policy=policy,
                    timeframe=timeframe,
                )
            )
        if (
            current_upper / current_body_size >= policy.pin_bar_minimum_wick_to_body
            and current_body_fraction <= policy.pin_bar_maximum_body_fraction
            and current_lower / current_range
            <= policy.pin_bar_maximum_opposite_wick_fraction
        ):
            result.append(
                _make_pattern(
                    label=PatternLabel.PIN_BAR_BEARISH,
                    indices=(index,),
                    observations=observations,
                    policy=policy,
                    timeframe=timeframe,
                )
            )
    if (
        current_body_size
        and current_lower / current_body_size
        >= policy.hammer_minimum_lower_wick_to_body
        and current_location >= policy.hammer_minimum_close_location
        and current_upper / current_range
        <= policy.pin_bar_maximum_opposite_wick_fraction
        and current_body_fraction <= policy.pin_bar_maximum_body_fraction
    ):
        result.append(
            _make_pattern(
                label=PatternLabel.HAMMER,
                indices=(index,),
                observations=observations,
                policy=policy,
                timeframe=timeframe,
            )
        )
    if (
        current_body_size
        and current_upper / current_body_size
        >= policy.shooting_star_minimum_upper_wick_to_body
        and current_location <= policy.shooting_star_maximum_close_location
        and current_lower / current_range
        <= policy.pin_bar_maximum_opposite_wick_fraction
        and current_body_fraction <= policy.pin_bar_maximum_body_fraction
    ):
        result.append(
            _make_pattern(
                label=PatternLabel.SHOOTING_STAR,
                indices=(index,),
                observations=observations,
                policy=policy,
                timeframe=timeframe,
            )
        )
    if current_body_fraction <= policy.doji_maximum_body_fraction:
        result.append(
            _make_pattern(
                label=PatternLabel.DOJI,
                indices=(index,),
                observations=observations,
                policy=policy,
                timeframe=timeframe,
            )
        )
    if index >= 2:
        first_open, _, _, first_close, _ = values[index - 2]
        middle_open, _, _, middle_close, _ = values[index - 1]
        first_body = first_close - first_open
        middle_body = middle_close - middle_open
        if (
            first_body < 0
            and current_body > 0
            and abs(middle_body)
            <= abs(first_body) * policy.star_middle_maximum_body_to_first_body
            and (close - first_close) / abs(first_body)
            >= policy.star_minimum_first_body_penetration
        ):
            result.append(
                _make_pattern(
                    label=PatternLabel.MORNING_STAR,
                    indices=(index - 2, index - 1, index),
                    observations=observations,
                    policy=policy,
                    timeframe=timeframe,
                )
            )
        if (
            first_body > 0
            and current_body < 0
            and abs(middle_body)
            <= abs(first_body) * policy.star_middle_maximum_body_to_first_body
            and (first_close - close) / abs(first_body)
            >= policy.star_minimum_first_body_penetration
        ):
            result.append(
                _make_pattern(
                    label=PatternLabel.EVENING_STAR,
                    indices=(index - 2, index - 1, index),
                    observations=observations,
                    policy=policy,
                    timeframe=timeframe,
                )
            )
    return tuple(result)


def _pivots(
    *,
    observations: tuple[MarketData, ...],
    values: tuple[tuple[Decimal, ...], ...],
    policy: SupportResistancePolicy,
    timeframe: str,
) -> tuple[PivotObservation, ...]:
    result: list[PivotObservation] = []
    with localcontext() as context:
        context.prec = _WORK_PRECISION
        for index in range(policy.left_window, len(observations) - policy.right_window):
            current_high = values[index][1]
            current_low = values[index][2]
            left = range(index - policy.left_window, index)
            right = range(index + 1, index + policy.right_window + 1)
            high_pivot = all(current_high > values[item][1] for item in left) and all(
                current_high >= values[item][1] for item in right
            )
            low_pivot = all(current_low < values[item][2] for item in left) and all(
                current_low <= values[item][2] for item in right
            )
            for kind, is_pivot, price in (
                (PivotKind.HIGH, high_pivot, current_high),
                (PivotKind.LOW, low_pivot, current_low),
            ):
                if not is_pivot:
                    continue
                confirm_index = index + policy.right_window
                source = observations[index]
                confirmation = observations[confirm_index]
                pivot_id = _stable_id(
                    "pivot",
                    source.market_data_id,
                    kind.value,
                    policy.policy_id,
                    policy.version,
                )
                result.append(
                    PivotObservation(
                        pivot_id=pivot_id,
                        kind=kind,
                        price=price,
                        source_market_data_id=source.market_data_id,
                        source_time=source.event_time,
                        confirmation_market_data_id=confirmation.market_data_id,
                        confirmation_time=_candle_end(confirmation, timeframe),
                        left_window=policy.left_window,
                        right_window=policy.right_window,
                        tie_rule=(
                            "earliest equal extreme wins: strictly more extreme than "
                            "all left candles and at least as extreme as all right "
                            "candles"
                        ),
                        method_version=PRICE_ACTION_METHOD_VERSION,
                    )
                )
    return tuple(sorted(result, key=lambda item: (item.source_time, item.kind.value)))


def _stable_id(*parts: object) -> UUID:
    return uuid5(_IDENTITY_NAMESPACE, "|".join(str(part) for part in parts))


def _zones(
    *,
    pivots: tuple[PivotObservation, ...],
    observations: tuple[MarketData, ...],
    values: tuple[tuple[Decimal, ...], ...],
    policy: SupportResistancePolicy,
    price_unit: str,
    timeframe: str,
) -> tuple[SupportResistanceZone, ...]:
    zones: list[SupportResistanceZone] = []
    with localcontext() as context:
        context.prec = _WORK_PRECISION
        for kind in (PivotKind.HIGH, PivotKind.LOW):
            same_kind = sorted(
                (pivot for pivot in pivots if pivot.kind is kind),
                key=lambda pivot: (pivot.price, pivot.source_time),
            )
            groups: list[list[PivotObservation]] = []
            for pivot in same_kind:
                if (
                    not groups
                    or pivot.price - groups[-1][0].price > policy.price_tolerance
                ):
                    groups.append([pivot])
                else:
                    groups[-1].append(pivot)
            for group in groups:
                anchor = group[0].price
                upper = group[-1].price
                creation = max(group, key=lambda item: item.confirmation_time)
                interactions = tuple(
                    ZoneInteraction(
                        market_data_id=candle.market_data_id,
                        candle_time=candle.event_time,
                        candle_end=_candle_end(candle, timeframe),
                    )
                    for candle, (_, high, low, _, _) in zip(
                        observations, values, strict=True
                    )
                    if candle.event_time >= creation.confirmation_time
                    and high >= anchor
                    and low <= upper
                )
                boundary = upper if kind is PivotKind.HIGH else anchor
                consecutive = 0
                broken_at: datetime | None = None
                for candle, (_, _, _, close, _) in zip(
                    observations, values, strict=True
                ):
                    if candle.event_time < creation.confirmation_time:
                        continue
                    is_beyond = (
                        close > boundary + policy.close_break_buffer
                        if kind is PivotKind.HIGH
                        else close < boundary - policy.close_break_buffer
                    )
                    consecutive = consecutive + 1 if is_beyond else 0
                    if consecutive >= policy.break_close_count:
                        broken_at = _candle_end(candle, timeframe)
                        break
                status = (
                    ZoneStatus.BROKEN
                    if broken_at is not None
                    else ZoneStatus.REPEATED
                    if len(interactions) >= policy.minimum_repeated_interactions
                    else ZoneStatus.CANDIDATE
                )
                zones.append(
                    SupportResistanceZone(
                        zone_id=_stable_id(
                            "zone",
                            policy.policy_id,
                            policy.version,
                            kind.value,
                            anchor,
                            *(pivot.pivot_id for pivot in group),
                        ),
                        kind=kind,
                        anchor_price=anchor,
                        lower_price=anchor,
                        upper_price=upper,
                        price_unit=price_unit,
                        timeframe=timeframe,
                        method_version=PRICE_ACTION_METHOD_VERSION,
                        policy_id=policy.policy_id,
                        policy_version=policy.version,
                        creation_time=creation.confirmation_time,
                        confirmation_market_data_id=creation.confirmation_market_data_id,
                        contributor_pivot_ids=tuple(pivot.pivot_id for pivot in group),
                        contributor_market_data_ids=tuple(
                            pivot.source_market_data_id for pivot in group
                        ),
                        interactions=interactions,
                        status=status,
                        invalidated_at=broken_at,
                        invalidation_condition=(
                            f"{policy.break_close_count} consecutive closed Spot candle "
                            f"closes strictly {'above' if kind is PivotKind.HIGH else 'below'} "
                            f"the zone boundary by more than {policy.close_break_buffer} "
                            f"{price_unit}; price-only, without volume confirmation."
                        ),
                    )
                )
    return tuple(sorted(zones, key=lambda zone: (zone.kind.value, zone.anchor_price)))


def _make_contract_evidence(
    *,
    payload: _EvidencePayload,
    snapshot: MarketSnapshot,
    quality: DataQualityReport,
    timeframe: str,
) -> tuple[EvidenceItem, TechnicalAssessment]:
    try:
        encoded = canonical_json_dumps(payload)
    except ValueError as exc:
        raise PriceActionError(
            "Canonical analysis evidence could not be encoded."
        ) from exc
    if len(encoded.encode("utf-8")) > MAX_DOCUMENT_BYTES:
        raise PriceActionError("Price-action evidence exceeds the bounded output size.")
    evidence_id = _stable_id(
        "evidence",
        snapshot.snapshot_id,
        quality.report_id,
        PRICE_ACTION_METHOD_VERSION,
        payload.payload_version,
    )
    evidence_method = VersionReference(
        PRICE_ACTION_INDICATOR_ID, PRICE_ACTION_METHOD_VERSION
    )
    provenance = (
        VersionReference("C-001", "1"),
        VersionReference("C-002", "1"),
        VersionReference("C-003", "1"),
        VersionReference("canonical-json", CANONICAL_JSON_VERSION),
    )
    evidence = EvidenceItem(
        evidence_id=evidence_id,
        source_record_ids=snapshot.source_record_ids,
        dataset_versions=(snapshot.dataset_version,)
        if snapshot.dataset_version
        else (),
        feature_ids=(),
        classification=ClaimClassification.FACT,
        relation=EvidenceRelation.NEUTRAL,
        observed_at=payload.geometry[0].candle_time,
        available_at=quality.assessed_at,
        expires_at=quality.assessed_at,
        method=evidence_method,
        value=encoded,
        unit=payload.price_unit,
        interpretation=(
            "Deterministic Spot OHLCV-derived price-action and support/resistance "
            "observations; descriptive evidence only."
        ),
        quality_status=quality.status,
        data_quality_report_id=quality.report_id,
        reliability=quality.source_reliability,
        limitations=payload.limitations,
        provenance=provenance
        + (VersionReference("price-action-evidence", EVIDENCE_SCHEMA_VERSION),),
        usable=True,
    )
    evidence_ids = (evidence.evidence_id,)
    findings = (
        AnalyticalFinding(
            finding_id=_stable_id("finding", evidence_id, "price-action"),
            category="price-action-observation",
            classification=ClaimClassification.FACT,
            statement=(
                "Candle geometry and any caller-policy pattern labels are available "
                "as versioned structured records in linked C-008 evidence."
            ),
            evidence_ids=evidence_ids,
            method=evidence_method,
            invalidation_condition=(
                "Superseded by correction of a source candle or a change to the named "
                "method or caller-policy version."
            ),
            limitations=payload.limitations,
        ),
        AnalyticalFinding(
            finding_id=_stable_id("finding", evidence_id, "support-resistance"),
            category="support-resistance-observation",
            classification=ClaimClassification.FACT,
            statement=(
                "Right-confirmed local pivots and fixed-anchor price zones, when "
                "requested by policy, are recorded in linked C-008 evidence."
            ),
            evidence_ids=evidence_ids,
            method=evidence_method,
            invalidation_condition=(
                "A zone is broken only by its recorded caller-policy consecutive "
                "close rule; source corrections or method/policy changes supersede it."
            ),
            limitations=payload.limitations,
        ),
    )
    assessment = TechnicalAssessment(
        assessment_id=_stable_id("assessment", evidence_id),
        asset=snapshot.instrument_id,
        instrument_id=snapshot.instrument_id,
        timeframe=timeframe,
        as_of=snapshot.as_of,
        available_at=quality.assessed_at,
        expires_at=quality.assessed_at,
        status=AssessmentStatus.AVAILABLE,
        analytical_confidence=Decimal(1),
        findings=findings,
        observations=(),
        evidence_ids=evidence_ids,
        contradiction_ids=(),
        uncertainty_ids=(),
        data_quality_report_id=quality.report_id,
        provenance=provenance
        + (VersionReference("price-action-evidence", EVIDENCE_SCHEMA_VERSION),),
        methodology=MethodologyCategory.TECHNICAL,
    )
    return evidence, assessment


def calculate_spot_price_action(
    *,
    snapshot: MarketSnapshot,
    observations: tuple[MarketData, ...],
    quality: DataQualityReport,
    timeframe: str,
    range_baseline_policy: RangeBaselinePolicy | None = None,
    pattern_policy: PatternPolicy | None = None,
    support_resistance_policy: SupportResistancePolicy | None = None,
    metadata_version: str = PRICE_ACTION_METADATA_VERSION,
) -> PriceActionAnalysis:
    """Calculate exact candle, pattern, pivot, and level observations for Spot OHLCV.

    Pivot ties use the earliest equal extreme: a high/low must be strictly more
    extreme than all left candles and at least as extreme as all right candles.
    A pivot appears only after its complete right window is closed. Zones are
    partitioned by pivot kind and built from sorted prices against a fixed lowest
    anchor, so a cluster can never exceed the caller's price tolerance.
    """
    if not isinstance(snapshot, MarketSnapshot) or not isinstance(
        quality, DataQualityReport
    ):
        raise PriceActionError("Canonical snapshot and quality contracts are required.")
    if type(observations) is not tuple or not all(
        isinstance(item, MarketData) for item in observations
    ):
        raise PriceActionError("Observations must be a tuple of canonical MarketData.")
    if not observations or len(observations) > _MAX_CANDLES:
        raise PriceActionError("A bounded nonempty Spot OHLCV series is required.")
    if type(timeframe) is not str or timeframe not in _INTERVALS:
        raise PriceActionError("Unsupported Spot candle timeframe.")
    if type(metadata_version) is not str:
        raise PriceActionError("metadata_version must be an exact version string.")
    try:
        metadata = SPOT_RESEARCH_INDICATORS.get(
            PRICE_ACTION_INDICATOR_ID, metadata_version
        )
    except (IndicatorMetadataError, TypeError) as exc:
        raise PriceActionError("Unknown exact price-action metadata version.") from exc
    if (
        metadata.phase is not IndicatorPhase.VALIDATED
        or timeframe not in metadata.timeframes
    ):
        raise PriceActionError("Price-action method is not validated for timeframe.")
    if not snapshot.instrument_id.endswith("-SPOT") or not snapshot.venue_id.endswith(
        "-SPOT"
    ):
        raise PriceActionError(
            "Only canonical Spot instruments and venues are supported."
        )
    try:
        _ohlc(
            snapshot=snapshot,
            observations=observations,
            quality=quality,
            timeframe=timeframe,
        )
    except (VolatilityError, ArithmeticError) as exc:
        raise PriceActionError(
            "Spot OHLCV failed the shared analysis validation."
        ) from exc
    for name, policy in (
        ("range_baseline_policy", range_baseline_policy),
        ("pattern_policy", pattern_policy),
        ("support_resistance_policy", support_resistance_policy),
    ):
        expected_type = {
            "range_baseline_policy": RangeBaselinePolicy,
            "pattern_policy": PatternPolicy,
            "support_resistance_policy": SupportResistancePolicy,
        }[name]
        if policy is not None and type(policy) is not expected_type:
            raise PriceActionError(f"{name} must use its immutable versioned policy.")

    values = _decimals(observations)
    price_unit = next(
        metric.unit
        for metric in observations[0].metrics
        if metric.metric_name == "close"
    )
    if (
        support_resistance_policy is not None
        and support_resistance_policy.price_unit != price_unit
    ):
        raise PriceActionError("Price tolerance unit must match the Spot price unit.")
    geometry = _geometry(
        observations=observations,
        values=values,
        timeframe=timeframe,
        baseline_policy=range_baseline_policy,
        pattern_policy=pattern_policy,
    )
    pivots = (
        _pivots(
            observations=observations,
            values=values,
            policy=support_resistance_policy,
            timeframe=timeframe,
        )
        if support_resistance_policy is not None
        else ()
    )
    zones = (
        _zones(
            pivots=pivots,
            observations=observations,
            values=values,
            policy=support_resistance_policy,
            price_unit=price_unit,
            timeframe=timeframe,
        )
        if support_resistance_policy is not None
        else ()
    )
    limitations = (
        "Analysis-only observations; they are not a signal, recommendation, "
        "validation result, risk decision, approval, or execution permission.",
        "All findings derive from the same validated Spot OHLCV candles and are "
        "correlated, not independent confirmations.",
        "Pivot ties select the earliest equal extreme; pivots remain unavailable "
        "until every caller-selected right confirmation candle has closed.",
        "Zones use a fixed lowest-price anchor and caller tolerance; they do not "
        "claim major significance, liquidity, or historical strength.",
        "Break status uses closes and the supplied buffer/count only; it is not "
        "volume confirmation or breakout/reclaim strategy logic.",
        "Pattern rules are descriptive, policy-versioned observations and do not "
        "imply future direction or profitability.",
        "The C-012 analytical confidence value reflects deterministic rule "
        "application to validated inputs only; it is not probability or trade "
        "confidence.",
    )
    uncertainty = (
        "OHLCV candle data cannot establish trade-level order flow or hidden "
        "liquidity.",
        "No statistical strength, significance, or probability is inferred.",
    )
    payload = _EvidencePayload(
        payload_version=EVIDENCE_SCHEMA_VERSION,
        method_version=PRICE_ACTION_METHOD_VERSION,
        timeframe=timeframe,
        instrument_id=snapshot.instrument_id,
        venue_id=snapshot.venue_id,
        price_unit=price_unit,
        snapshot_id=snapshot.snapshot_id,
        quality_report_id=quality.report_id,
        as_of=snapshot.as_of,
        source_record_ids=snapshot.source_record_ids,
        input_market_data_ids=snapshot.market_data_ids,
        range_baseline_policy=range_baseline_policy,
        pattern_policy=pattern_policy,
        support_resistance_policy=support_resistance_policy,
        geometry=geometry,
        pivots=pivots,
        zones=zones,
        uncertainty=uncertainty,
        limitations=limitations,
    )
    evidence, assessment = _make_contract_evidence(
        payload=payload,
        snapshot=snapshot,
        quality=quality,
        timeframe=timeframe,
    )
    return PriceActionAnalysis(
        indicator_id=metadata.indicator_id,
        metadata_version=metadata.metadata_version,
        method_version=metadata.calculation_version,
        timeframe=timeframe,
        instrument_id=snapshot.instrument_id,
        venue_id=snapshot.venue_id,
        snapshot_id=snapshot.snapshot_id,
        quality_report_id=quality.report_id,
        as_of=snapshot.as_of,
        source_record_ids=snapshot.source_record_ids,
        input_market_data_ids=snapshot.market_data_ids,
        price_unit=price_unit,
        range_baseline_policy=range_baseline_policy,
        pattern_policy=pattern_policy,
        support_resistance_policy=support_resistance_policy,
        geometry=geometry,
        pivots=pivots,
        zones=zones,
        uncertainty=uncertainty,
        limitations=limitations,
        evidence=evidence,
        assessment=assessment,
    )
