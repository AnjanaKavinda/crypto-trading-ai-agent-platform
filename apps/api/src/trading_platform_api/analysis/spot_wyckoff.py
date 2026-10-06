"""Deterministic, analysis-only Spot Wyckoff observations."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import ROUND_HALF_EVEN, Decimal, localcontext
from hashlib import sha256
from uuid import UUID, uuid5

from trading_platform_api.analysis.contracts import (
    AnalyticalFinding,
    AssessmentStatus,
    ClaimClassification,
    DomainObservation,
    EvidenceItem,
    EvidenceRelation,
    MethodologyCategory,
    VersionReference,
    WyckoffAssessment,
)
from trading_platform_api.analysis.indicator_registry import (
    SPOT_RESEARCH_INDICATORS,
    IndicatorMetadataError,
    IndicatorPhase,
)
from trading_platform_api.analysis.price_action import _INTERVALS, _bounded_decimal
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

SPOT_WYCKOFF_INDICATOR_ID = "spot-wyckoff-analysis"
SPOT_WYCKOFF_METADATA_VERSION = "1"
SPOT_WYCKOFF_METHOD_VERSION = "spot-wyckoff-v1"
SPOT_WYCKOFF_EVIDENCE_VERSION = "spot-wyckoff-evidence-v1"
_MAX_CANDLES = 10_000
_MAX_POLICY_TEXT = 128
_WORK_PRECISION = 512
_RATIO_PRECISION = 34
_IDENTITY_NAMESPACE = UUID("da17c55a-053b-50a1-b261-957ac9e230c4")
_LIMITATIONS = (
    "Descriptive, same-timeframe Spot OHLCV analysis only; not a signal, "
    "recommendation, validation, risk decision, approval, or execution permission.",
    "Wyckoff phase and event labels are deterministic hypotheses under the exact "
    "caller policy; they are not confirmed market states or universally canonical.",
    "OHLCV cannot establish order flow, hidden liquidity, participant intent, "
    "absorption by a known actor, or a future price direction.",
    "Analytical confidence is uncalibrated and is reported as zero; it is not a "
    "probability or statistical confidence interval.",
)
_UNCERTAINTY = (
    "All observations derive from the same Spot OHLCV source and are correlated.",
    "Alternative explanations include ordinary volatility, gaps in trading interest, "
    "and unrelated participants; OHLCV cannot distinguish these causes.",
)


class SpotWyckoffError(ValueError):
    """Wyckoff observations cannot be calculated safely."""


@dataclass(frozen=True, slots=True)
class SpotWyckoffPolicy:
    """Immutable caller thresholds; registry metadata is never applied as defaults."""

    policy_id: str
    version: str
    range_window: int
    volume_window: int
    breakout_confirmation: int
    maximum_range_fraction: Decimal
    phase_close_fraction: Decimal
    minimum_phase_volume_ratio: Decimal
    event_volume_ratio: Decimal
    high_volume_ratio: Decimal
    low_volume_ratio: Decimal
    wide_spread_ratio: Decimal
    narrow_spread_ratio: Decimal
    absorption_volume_ratio: Decimal
    climactic_volume_ratio: Decimal
    maximum_climactic_close_fraction: Decimal
    maximum_output_records: int

    def __post_init__(self) -> None:
        for name in ("policy_id", "version"):
            value = getattr(self, name)
            if (
                not isinstance(value, str)
                or not value
                or value != value.strip()
                or len(value) > _MAX_POLICY_TEXT
            ):
                raise SpotWyckoffError(f"{name} must be bounded nonblank text.")
        for name in ("range_window", "volume_window", "breakout_confirmation"):
            value = getattr(self, name)
            if type(value) is not int or not 2 <= value <= 500:
                raise SpotWyckoffError(f"{name} must be an integer in [2, 500].")
        for name in (
            "maximum_range_fraction",
            "phase_close_fraction",
            "minimum_phase_volume_ratio",
            "event_volume_ratio",
            "high_volume_ratio",
            "low_volume_ratio",
            "wide_spread_ratio",
            "narrow_spread_ratio",
            "absorption_volume_ratio",
            "climactic_volume_ratio",
            "maximum_climactic_close_fraction",
        ):
            try:
                value = _bounded_decimal(name, getattr(self, name))
            except (TypeError, ValueError) as exc:
                raise SpotWyckoffError(
                    f"{name} must be a bounded finite Decimal."
                ) from exc
            if value < 0 or value > Decimal("1000"):
                raise SpotWyckoffError(f"{name} must be in [0, 1000].")
        fractions = (
            self.maximum_range_fraction,
            self.phase_close_fraction,
            self.maximum_climactic_close_fraction,
        )
        if any(value > 1 for value in fractions):
            raise SpotWyckoffError("Fraction policy values must be in [0, 1].")
        if self.phase_close_fraction >= Decimal("0.5"):
            raise SpotWyckoffError("phase_close_fraction must be below 0.5.")
        if self.maximum_climactic_close_fraction >= Decimal("0.5"):
            raise SpotWyckoffError(
                "maximum_climactic_close_fraction must be below 0.5."
            )
        if self.narrow_spread_ratio > self.wide_spread_ratio:
            raise SpotWyckoffError(
                "narrow_spread_ratio must not exceed wide_spread_ratio."
            )
        if (
            type(self.maximum_output_records) is not int
            or not 1 <= self.maximum_output_records <= _MAX_CANDLES
        ):
            raise SpotWyckoffError(
                f"maximum_output_records must be in [1, {_MAX_CANDLES}]."
            )


@dataclass(frozen=True, slots=True)
class WyckoffObservation:
    category: str
    label: str
    value: str
    timeframe: str
    as_of: datetime
    source_market_data_ids: tuple[UUID, ...]
    supporting_market_data_ids: tuple[UUID, ...]
    contradictory_market_data_ids: tuple[UUID, ...]
    invalidation_condition: str
    alternative_explanation: str
    evidence_id: UUID


@dataclass(frozen=True, slots=True)
class SpotWyckoffAnalysis:
    indicator_id: str
    metadata_version: str
    method_version: str
    timeframe: str
    instrument_id: str
    venue_id: str
    snapshot_id: UUID
    quality_report_id: UUID
    as_of: datetime
    evidence_expires_at: datetime
    source_record_ids: tuple[UUID, ...]
    input_market_data_ids: tuple[UUID, ...]
    policy: SpotWyckoffPolicy
    observations: tuple[WyckoffObservation, ...]
    evidence: tuple[EvidenceItem, ...]
    assessment: WyckoffAssessment


@dataclass(frozen=True, slots=True)
class _Candle:
    observation: MarketData
    opening: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal
    end: datetime

    @property
    def spread(self) -> Decimal:
        return self.high - self.low


@dataclass(frozen=True, slots=True)
class _Record:
    category: str
    label: str
    value: str
    candle_indices: tuple[int, ...]
    supporting_indices: tuple[int, ...]
    contradictory_indices: tuple[int, ...]
    classification: ClaimClassification
    relation: EvidenceRelation
    invalidation_condition: str
    alternative_explanation: str


def _stable_id(*parts: object) -> UUID:
    return uuid5(_IDENTITY_NAMESPACE, canonical_json_dumps(parts))


def _mean(values: tuple[Decimal, ...]) -> Decimal:
    with localcontext() as context:
        context.prec = _WORK_PRECISION
        context.rounding = ROUND_HALF_EVEN
        return sum(values, Decimal(0)) / Decimal(len(values))


def _ratio(numerator: Decimal, denominator: Decimal) -> Decimal | None:
    if denominator == 0:
        return None
    with localcontext() as context:
        context.prec = _RATIO_PRECISION
        context.rounding = ROUND_HALF_EVEN
        return numerator / denominator


def _metric_ratio(value: Decimal | None) -> str:
    return "unavailable:zero-prior-baseline" if value is None else str(value)


def _window_metrics(
    candles: tuple[_Candle, ...], index: int, volume_window: int
) -> tuple[Decimal | None, Decimal | None]:
    if index < volume_window:
        return None, None
    prior = candles[index - volume_window : index]
    return (
        _ratio(candles[index].volume, _mean(tuple(item.volume for item in prior))),
        _ratio(candles[index].spread, _mean(tuple(item.spread for item in prior))),
    )


def _record(
    *,
    category: str,
    label: str,
    value: str,
    indices: tuple[int, ...],
    classification: ClaimClassification,
    invalidation: str,
    alternative: str,
    supporting: tuple[int, ...] | None = None,
    contradictory: tuple[int, ...] = (),
    relation: EvidenceRelation = EvidenceRelation.NEUTRAL,
) -> _Record:
    indices = tuple(dict.fromkeys(indices))
    supporting = tuple(dict.fromkeys(supporting if supporting is not None else indices))
    return _Record(
        category,
        label,
        value,
        indices,
        supporting,
        tuple(dict.fromkeys(contradictory)),
        classification,
        relation,
        invalidation,
        alternative,
    )


def _analyse_records(
    *,
    candles: tuple[_Candle, ...],
    timeframe: str,
    policy: SpotWyckoffPolicy,
) -> tuple[_Record, ...]:
    records: list[_Record] = []
    n = len(candles)
    latest = n - 1
    range_start = latest - policy.range_window
    range_indices = tuple(range(range_start, n))
    prior_range = candles[range_start:latest]
    range_high = max(item.high for item in prior_range)
    range_low = min(item.low for item in prior_range)
    range_width = range_high - range_low
    range_fraction = _ratio(range_width, (range_high + range_low) / Decimal(2))
    prior_volume_ratio, prior_spread_ratio = _window_metrics(
        candles, latest, policy.volume_window
    )

    # Emit explicit per-candle measurements; the current candle is never in its
    # own comparison baseline.
    for index, candle in enumerate(candles):
        volume_ratio, spread_ratio = _window_metrics(
            candles, index, policy.volume_window
        )
        if volume_ratio is not None or index >= policy.volume_window:
            comparison_indices = tuple(
                range(max(0, index - policy.volume_window), index + 1)
            )
            records.append(
                _record(
                    category="volume-spread",
                    label="relative-volume-and-spread",
                    value=canonical_json_dumps(
                        {
                            "volume": str(candle.volume),
                            "volume_ratio": _metric_ratio(volume_ratio),
                            "spread": str(candle.spread),
                            "spread_ratio": _metric_ratio(spread_ratio),
                            "baseline_window": policy.volume_window,
                            "baseline_excludes_current_candle": True,
                        }
                    ),
                    indices=comparison_indices,
                    classification=ClaimClassification.FACT,
                    invalidation="Superseded only by a source correction or a new method/policy version.",
                    alternative="OHLCV spread and reported volume do not reveal order-book depth or trade intent.",
                )
            )
        if volume_ratio is None or spread_ratio is None:
            continue
        progress = abs(candle.close - candle.opening)
        progress_fraction = _ratio(progress, candle.spread)
        if volume_ratio >= policy.high_volume_ratio and (
            progress_fraction is None
            or progress_fraction <= policy.phase_close_fraction
        ):
            records.append(
                _record(
                    category="effort-result",
                    label="high-effort-low-result-candidate",
                    value=canonical_json_dumps(
                        {
                            "volume_ratio": str(volume_ratio),
                            "body_to_spread": _metric_ratio(progress_fraction),
                        }
                    ),
                    indices=tuple(
                        range(max(0, index - policy.volume_window), index + 1)
                    ),
                    classification=ClaimClassification.INFERENCE,
                    relation=EvidenceRelation.SUPPORTING,
                    invalidation="Invalidated if a later closed candle sustains a close beyond this candle's high or low.",
                    alternative="A narrow candle may reflect temporary inactivity, venue aggregation, or an ordinary pause.",
                )
            )
        if (
            volume_ratio >= policy.absorption_volume_ratio
            and spread_ratio <= policy.narrow_spread_ratio
        ):
            records.append(
                _record(
                    category="absorption",
                    label="potential-absorption-pattern",
                    value=canonical_json_dumps(
                        {
                            "volume_ratio": str(volume_ratio),
                            "spread_ratio": str(spread_ratio),
                        }
                    ),
                    indices=tuple(
                        range(max(0, index - policy.volume_window), index + 1)
                    ),
                    classification=ClaimClassification.INFERENCE,
                    relation=EvidenceRelation.SUPPORTING,
                    invalidation="Invalidated if a later closed candle sustains a close beyond this candle's high or low.",
                    alternative="High volume with a narrow spread is not proof of absorption by a specific participant.",
                )
            )
        close_location = (
            None
            if candle.spread == 0
            else _ratio(candle.close - candle.low, candle.spread)
        )
        if (
            volume_ratio >= policy.climactic_volume_ratio
            and spread_ratio >= policy.wide_spread_ratio
            and close_location is not None
            and min(close_location, Decimal(1) - close_location)
            <= policy.maximum_climactic_close_fraction
        ):
            records.append(
                _record(
                    category="climactic-action",
                    label="climactic-action-candidate",
                    value=canonical_json_dumps(
                        {
                            "volume_ratio": str(volume_ratio),
                            "spread_ratio": str(spread_ratio),
                            "close_location": str(close_location),
                        }
                    ),
                    indices=tuple(
                        range(max(0, index - policy.volume_window), index + 1)
                    ),
                    classification=ClaimClassification.INFERENCE,
                    relation=EvidenceRelation.SUPPORTING,
                    invalidation="Candidate expires at the next timeframe boundary; a later close outside the candle range supersedes it.",
                    alternative="A large directional candle can be continuation rather than exhaustion.",
                )
            )
        if (
            volume_ratio <= policy.low_volume_ratio
            and spread_ratio <= policy.narrow_spread_ratio
        ):
            if candle.close >= candle.opening:
                label = "no-demand"
            else:
                label = "no-supply"
            records.append(
                _record(
                    category="event",
                    label=label,
                    value=canonical_json_dumps(
                        {
                            "volume_ratio": str(volume_ratio),
                            "spread_ratio": str(spread_ratio),
                        }
                    ),
                    indices=tuple(
                        range(max(0, index - policy.volume_window), index + 1)
                    ),
                    classification=ClaimClassification.INFERENCE,
                    relation=EvidenceRelation.NEUTRAL,
                    invalidation="Candidate expires at the next timeframe boundary or on a source correction.",
                    alternative="Low volume and a narrow spread do not establish absence of demand or supply.",
                )
            )

    # Range events are evaluated chronologically. An LPS/LPSY can only follow
    # an earlier confirmed SOS/SOW and is invalidated by an intervening close
    # through its reference boundary.
    strength_events: list[tuple[int, Decimal, tuple[int, ...]]] = []
    weakness_events: list[tuple[int, Decimal, tuple[int, ...]]] = []
    for index in range(policy.range_window, n):
        previous_start = index - policy.range_window
        previous = candles[previous_start:index]
        current = candles[index]
        prior_high = max(item.high for item in previous)
        prior_low = min(item.low for item in previous)
        volume_ratio, spread_ratio = _window_metrics(
            candles, index, policy.volume_window
        )
        volume_ok = (
            volume_ratio is not None and volume_ratio >= policy.event_volume_ratio
        )
        event_indices = tuple(range(previous_start, index + 1))
        if current.low < prior_low and current.close > prior_low and volume_ok:
            records.append(
                _record(
                    category="event",
                    label="spring-candidate",
                    value=canonical_json_dumps(
                        {
                            "prior_support": str(prior_low),
                            "low": str(current.low),
                            "close": str(current.close),
                            "volume_ratio": str(volume_ratio),
                        }
                    ),
                    indices=event_indices,
                    classification=ClaimClassification.INFERENCE,
                    relation=EvidenceRelation.SUPPORTING,
                    invalidation="Invalidated by a subsequent closed candle closing below the breached support.",
                    alternative="A brief range breach and recovery can be ordinary volatility, not a spring.",
                )
            )
        if current.high > prior_high and current.close < prior_high and volume_ok:
            records.append(
                _record(
                    category="event",
                    label="upthrust-candidate",
                    value=canonical_json_dumps(
                        {
                            "prior_resistance": str(prior_high),
                            "high": str(current.high),
                            "close": str(current.close),
                            "volume_ratio": str(volume_ratio),
                        }
                    ),
                    indices=event_indices,
                    classification=ClaimClassification.INFERENCE,
                    relation=EvidenceRelation.SUPPORTING,
                    invalidation="Invalidated by a subsequent closed candle closing above the breached resistance.",
                    alternative="A brief range breach and rejection can be ordinary volatility, not an upthrust.",
                )
            )
        if (
            volume_ratio is not None
            and spread_ratio is not None
            and volume_ratio >= policy.event_volume_ratio
            and spread_ratio >= policy.wide_spread_ratio
        ):
            if current.close < current.opening and current.close < previous[-1].close:
                records.append(
                    _record(
                        category="event",
                        label="preliminary-support-candidate",
                        value=canonical_json_dumps(
                            {
                                "volume_ratio": str(volume_ratio),
                                "spread_ratio": str(spread_ratio),
                                "close": str(current.close),
                            }
                        ),
                        indices=event_indices,
                        classification=ClaimClassification.INFERENCE,
                        relation=EvidenceRelation.SUPPORTING,
                        invalidation="Invalidated by a subsequent close below this candle's low.",
                        alternative="A high-volume decline may be continuation rather than preliminary support.",
                    )
                )
            if current.close > current.opening and current.close > previous[-1].close:
                records.append(
                    _record(
                        category="event",
                        label="preliminary-supply-candidate",
                        value=canonical_json_dumps(
                            {
                                "volume_ratio": str(volume_ratio),
                                "spread_ratio": str(spread_ratio),
                                "close": str(current.close),
                            }
                        ),
                        indices=event_indices,
                        classification=ClaimClassification.INFERENCE,
                        relation=EvidenceRelation.SUPPORTING,
                        invalidation="Invalidated by a subsequent close above this candle's high.",
                        alternative="A high-volume advance may be continuation rather than preliminary supply.",
                    )
                )

        first_confirmation = index - policy.breakout_confirmation + 1
        if first_confirmation >= policy.range_window:
            base_start = first_confirmation - policy.range_window
            base = candles[base_start:first_confirmation]
            base_high = max(item.high for item in base)
            base_low = min(item.low for item in base)
            confirmed = candles[first_confirmation : index + 1]
            if all(item.close > base_high for item in confirmed):
                event = _record(
                    category="event",
                    label="sign-of-strength-candidate",
                    value=canonical_json_dumps(
                        {
                            "reference_resistance": str(base_high),
                            "confirmation_closes": tuple(
                                str(item.close) for item in confirmed
                            ),
                            "confirmation_count": policy.breakout_confirmation,
                        }
                    ),
                    indices=tuple(range(base_start, index + 1)),
                    classification=ClaimClassification.INFERENCE,
                    relation=EvidenceRelation.SUPPORTING,
                    invalidation="Invalidated by a subsequent close back at or below the reference resistance.",
                    alternative="A confirmed close breakout may fail or reflect a temporary repricing.",
                )
                records.append(event)
                strength_events.append((index, base_high, event.candle_indices))
            if all(item.close < base_low for item in confirmed):
                event = _record(
                    category="event",
                    label="sign-of-weakness-candidate",
                    value=canonical_json_dumps(
                        {
                            "reference_support": str(base_low),
                            "confirmation_closes": tuple(
                                str(item.close) for item in confirmed
                            ),
                            "confirmation_count": policy.breakout_confirmation,
                        }
                    ),
                    indices=tuple(range(base_start, index + 1)),
                    classification=ClaimClassification.INFERENCE,
                    relation=EvidenceRelation.SUPPORTING,
                    invalidation="Invalidated by a subsequent close back at or above the reference support.",
                    alternative="A confirmed close breakdown may fail or reflect a temporary repricing.",
                )
                records.append(event)
                weakness_events.append((index, base_low, event.candle_indices))

        current = candles[index]
        earlier_strength = (
            strength_events[-1]
            if strength_events and strength_events[-1][0] < index
            else None
        )
        if earlier_strength is not None:
            event_index, resistance, event_sources = earlier_strength
            invalidated = any(
                candles[position].close <= resistance
                for position in range(event_index + 1, index + 1)
            )
            if (
                not invalidated
                and current.low > resistance
                and current.close > current.opening
            ):
                records.append(
                    _record(
                        category="event",
                        label="last-point-of-support-candidate",
                        value=canonical_json_dumps(
                            {
                                "reference_resistance": str(resistance),
                                "low": str(current.low),
                            }
                        ),
                        indices=event_sources + (index,),
                        classification=ClaimClassification.INFERENCE,
                        relation=EvidenceRelation.SUPPORTING,
                        invalidation="Invalidated by a subsequent close below the reference resistance.",
                        alternative="A higher low after a breakout does not prove institutional support.",
                    )
                )
        earlier_weakness = (
            weakness_events[-1]
            if weakness_events and weakness_events[-1][0] < index
            else None
        )
        if earlier_weakness is not None:
            event_index, support, event_sources = earlier_weakness
            invalidated = any(
                candles[position].close >= support
                for position in range(event_index + 1, index + 1)
            )
            if (
                not invalidated
                and current.high < support
                and current.close < current.opening
            ):
                records.append(
                    _record(
                        category="event",
                        label="last-point-of-supply-candidate",
                        value=canonical_json_dumps(
                            {
                                "reference_support": str(support),
                                "high": str(current.high),
                            }
                        ),
                        indices=event_sources + (index,),
                        classification=ClaimClassification.INFERENCE,
                        relation=EvidenceRelation.SUPPORTING,
                        invalidation="Invalidated by a subsequent close above the reference support.",
                        alternative="A lower high after a breakdown does not prove institutional supply.",
                    )
                )

    # The phase classification is a trailing, point-in-time hypothesis. A
    # breakout must be confirmed; a range-phase distinction requires both a
    # caller-defined range width and a caller-defined close-location boundary.
    first_confirmation = latest - policy.breakout_confirmation + 1
    phase_label = "uncertain"
    phase_basis = range_indices
    if first_confirmation >= policy.range_window:
        base_start = first_confirmation - policy.range_window
        base = candles[base_start:first_confirmation]
        base_high = max(item.high for item in base)
        base_low = min(item.low for item in base)
        confirmed = candles[first_confirmation : latest + 1]
        if all(item.close > base_high for item in confirmed):
            phase_label = "markup"
            phase_basis = tuple(range(base_start, latest + 1))
        elif all(item.close < base_low for item in confirmed):
            phase_label = "markdown"
            phase_basis = tuple(range(base_start, latest + 1))
        elif (
            range_fraction is not None
            and range_fraction <= policy.maximum_range_fraction
            and range_low <= candles[latest].close <= range_high
        ):
            close_location = _ratio(candles[latest].close - range_low, range_width)
            if (
                close_location is not None
                and close_location <= policy.phase_close_fraction
                and prior_volume_ratio is not None
                and prior_volume_ratio >= policy.minimum_phase_volume_ratio
            ):
                phase_label = "accumulation-hypothesis"
            elif (
                close_location is not None
                and close_location >= Decimal(1) - policy.phase_close_fraction
                and prior_volume_ratio is not None
                and prior_volume_ratio >= policy.minimum_phase_volume_ratio
            ):
                phase_label = "distribution-hypothesis"
            else:
                phase_label = "trading-range"
            phase_basis = range_indices
    else:
        phase_basis = tuple(range(n))
    phase_conflicts = tuple(
        sorted(
            {
                index
                for item in records
                if item.category == "event"
                and (
                    phase_label in {"accumulation-hypothesis", "markup"}
                    and item.label
                    in {"upthrust-candidate", "sign-of-weakness-candidate"}
                    or phase_label in {"distribution-hypothesis", "markdown"}
                    and item.label in {"spring-candidate", "sign-of-strength-candidate"}
                )
                for index in item.candle_indices
            }
        )
    )
    relation = (
        EvidenceRelation.CONTRADICTING
        if phase_conflicts
        else EvidenceRelation.SUPPORTING
        if phase_label != "uncertain"
        else EvidenceRelation.NEUTRAL
    )
    records.append(
        _record(
            category="phase",
            label=phase_label,
            value=canonical_json_dumps(
                {
                    "trailing_high": str(range_high),
                    "trailing_low": str(range_low),
                    "range_fraction": _metric_ratio(range_fraction),
                    "latest_close": str(candles[latest].close),
                    "latest_volume_ratio": _metric_ratio(prior_volume_ratio),
                    "policy_id": policy.policy_id,
                    "policy_version": policy.version,
                }
            ),
            indices=phase_basis,
            classification=ClaimClassification.INFERENCE,
            relation=relation,
            contradictory=phase_conflicts,
            invalidation="Superseded by a new confirmed phase under the same policy, a source correction, or the next timeframe boundary.",
            alternative="Range position and relative volume cannot establish accumulation or distribution intent.",
        )
    )
    if len(records) > policy.maximum_output_records:
        raise SpotWyckoffError("Wyckoff output exceeds the caller policy bound.")
    return tuple(records)


def _evidence_item(
    *,
    record: _Record,
    candles: tuple[_Candle, ...],
    snapshot: MarketSnapshot,
    quality: DataQualityReport,
    timeframe: str,
    policy: SpotWyckoffPolicy,
    expires_at: datetime,
) -> EvidenceItem:
    selected = tuple(candles[index] for index in record.candle_indices)
    if not selected:
        raise SpotWyckoffError("Every Wyckoff observation must cite source candles.")
    available_at = max(
        quality.assessed_at,
        *(item.observation.availability_time for item in selected),
    )
    payload = {
        "evidence_version": SPOT_WYCKOFF_EVIDENCE_VERSION,
        "method_id": SPOT_WYCKOFF_INDICATOR_ID,
        "method_version": SPOT_WYCKOFF_METHOD_VERSION,
        "policy": policy,
        "timeframe": timeframe,
        "as_of": max(item.end for item in selected),
        "category": record.category,
        "label": record.label,
        "value": record.value,
        "source_market_data_ids": tuple(
            item.observation.market_data_id for item in selected
        ),
        "supporting_market_data_ids": tuple(
            candles[index].observation.market_data_id
            for index in record.supporting_indices
        ),
        "contradictory_market_data_ids": tuple(
            candles[index].observation.market_data_id
            for index in record.contradictory_indices
        ),
        "invalidation_condition": record.invalidation_condition,
        "alternative_explanation": record.alternative_explanation,
        "uncertainty": _UNCERTAINTY,
        "limitations": _LIMITATIONS,
    }
    encoded = canonical_json_dumps(payload)
    if len(encoded.encode("utf-8")) > MAX_DOCUMENT_BYTES:
        raise SpotWyckoffError("Wyckoff evidence exceeds the output size bound.")
    digest = sha256(encoded.encode("utf-8")).hexdigest()
    evidence_id = _stable_id(
        "evidence",
        snapshot.snapshot_id,
        quality.report_id,
        SPOT_WYCKOFF_METHOD_VERSION,
        digest,
    )
    return EvidenceItem(
        evidence_id=evidence_id,
        source_record_ids=tuple(
            dict.fromkeys(item.observation.source_record_id for item in selected)
        ),
        dataset_versions=(snapshot.dataset_version,)
        if snapshot.dataset_version
        else (),
        feature_ids=(
            f"C-002:snapshot:{snapshot.snapshot_id}",
            *(
                f"C-001:market-data:{item.observation.market_data_id}"
                for item in selected
            ),
        ),
        classification=record.classification,
        relation=record.relation,
        observed_at=max(item.end for item in selected),
        available_at=available_at,
        expires_at=expires_at,
        method=VersionReference(SPOT_WYCKOFF_INDICATOR_ID, SPOT_WYCKOFF_METHOD_VERSION),
        value=encoded,
        unit=None,
        interpretation=(
            "Deterministic Spot OHLCV measurement or policy-defined Wyckoff "
            "hypothesis; descriptive analysis only."
        ),
        quality_status=quality.status,
        data_quality_report_id=quality.report_id,
        reliability=quality.source_reliability,
        limitations=(*_LIMITATIONS, *_UNCERTAINTY),
        provenance=(
            VersionReference("C-001", "1"),
            VersionReference("C-002", "1"),
            VersionReference("C-003", "1"),
            VersionReference("C-008", "1"),
            VersionReference("C-014", "1"),
            VersionReference("canonical-json", CANONICAL_JSON_VERSION),
            VersionReference("spot-wyckoff-evidence", SPOT_WYCKOFF_EVIDENCE_VERSION),
            VersionReference(policy.policy_id, policy.version),
        ),
        usable=True,
    )


def calculate_spot_wyckoff(
    *,
    snapshot: MarketSnapshot,
    observations: tuple[MarketData, ...],
    quality: DataQualityReport,
    timeframe: str,
    policy: SpotWyckoffPolicy,
    metadata_version: str = SPOT_WYCKOFF_METADATA_VERSION,
) -> SpotWyckoffAnalysis:
    """Calculate bounded, point-in-time Spot Wyckoff observations."""
    if (
        type(snapshot) is not MarketSnapshot
        or type(quality) is not DataQualityReport
        or type(observations) is not tuple
        or not observations
        or len(observations) > _MAX_CANDLES
        or not all(type(item) is MarketData for item in observations)
    ):
        raise SpotWyckoffError(
            "Canonical bounded snapshot, quality, and candles are required."
        )
    if type(policy) is not SpotWyckoffPolicy:
        raise SpotWyckoffError("An explicit immutable caller policy is required.")
    if type(timeframe) is not str or timeframe not in _INTERVALS:
        raise SpotWyckoffError("Unsupported Spot timeframe.")
    if type(metadata_version) is not str:
        raise SpotWyckoffError("metadata_version must be an exact version string.")
    try:
        metadata = SPOT_RESEARCH_INDICATORS.get(
            SPOT_WYCKOFF_INDICATOR_ID, metadata_version
        )
    except (IndicatorMetadataError, TypeError) as exc:
        raise SpotWyckoffError("Unknown exact Spot Wyckoff metadata version.") from exc
    if (
        metadata.phase is not IndicatorPhase.VALIDATED
        or metadata.calculation_version != SPOT_WYCKOFF_METHOD_VERSION
        or timeframe not in metadata.timeframes
    ):
        raise SpotWyckoffError(
            "Spot Wyckoff method is not validated for this timeframe."
        )
    if not snapshot.instrument_id.endswith("-SPOT") or not snapshot.venue_id.endswith(
        "-SPOT"
    ):
        raise SpotWyckoffError(
            "Only canonical Spot instruments and venues are supported."
        )
    try:
        _, price_unit = _ohlc(
            snapshot=snapshot,
            observations=observations,
            quality=quality,
            timeframe=timeframe,
        )
    except (VolatilityError, ArithmeticError) as exc:
        raise SpotWyckoffError("Spot OHLCV failed shared analysis validation.") from exc
    if (
        tuple(dict.fromkeys(item.source_record_id for item in observations))
        != snapshot.source_record_ids
    ):
        raise SpotWyckoffError("Ordered candle provenance must match the snapshot.")
    interval = timedelta(seconds=_INTERVALS[timeframe])
    if observations[-1].event_time + interval != snapshot.as_of:
        raise SpotWyckoffError("The latest closed candle must end at snapshot cutoff.")
    required_warmup = max(
        metadata.minimum_warmup_candles,
        policy.range_window + policy.breakout_confirmation,
        policy.volume_window + 1,
    )
    if len(observations) < required_warmup:
        raise SpotWyckoffError(
            f"Insufficient warm-up: requires {required_warmup} closed candles."
        )
    candles: list[_Candle] = []
    volume_unit: str | None = None
    for observation in observations:
        metrics = {item.metric_name: item for item in observation.metrics}
        if len(metrics) != len(observation.metrics):
            raise SpotWyckoffError("Duplicate OHLCV metric names are invalid.")
        prices = tuple(metrics[name] for name in ("open", "high", "low", "close"))
        volume = metrics["volume"]
        try:
            for metric in (*prices, volume):
                _bounded_decimal(metric.metric_name, metric.value)
        except (TypeError, ValueError) as exc:
            raise SpotWyckoffError(
                "OHLCV precision or exponent is unsupported."
            ) from exc
        if volume.value < 0:
            raise SpotWyckoffError("Spot candle volume must not be negative.")
        if volume_unit is not None and volume.unit != volume_unit:
            raise SpotWyckoffError("Volume units must remain consistent.")
        volume_unit = volume.unit
        candles.append(
            _Candle(
                observation,
                metrics["open"].value,
                metrics["high"].value,
                metrics["low"].value,
                metrics["close"].value,
                volume.value,
                observation.event_time + interval,
            )
        )
    candle_tuple = tuple(candles)
    as_of = snapshot.as_of
    try:
        # Evidence expires at the next candle boundary, measured from the
        # latest closed candle. A delayed quality assessment must not extend
        # the lifetime of an older snapshot.
        expires_at = as_of + interval
    except OverflowError as exc:
        raise SpotWyckoffError(
            "Wyckoff evidence expiry exceeds timestamp bounds."
        ) from exc
    if quality.assessed_at >= expires_at:
        raise SpotWyckoffError(
            "Quality evidence was assessed at or after the candle expiry."
        )
    with localcontext() as context:
        context.prec = _WORK_PRECISION
        context.rounding = ROUND_HALF_EVEN
        records = _analyse_records(
            candles=candle_tuple,
            timeframe=timeframe,
            policy=policy,
        )
    evidence = tuple(
        _evidence_item(
            record=record,
            candles=candle_tuple,
            snapshot=snapshot,
            quality=quality,
            timeframe=timeframe,
            policy=policy,
            expires_at=expires_at,
        )
        for record in records
    )
    evidence_by_id = {item.evidence_id: item for item in evidence}
    findings = tuple(
        AnalyticalFinding(
            finding_id=_stable_id(
                "finding",
                snapshot.snapshot_id,
                quality.report_id,
                SPOT_WYCKOFF_METHOD_VERSION,
                item.evidence_id,
            ),
            category=record.category,
            classification=record.classification,
            statement=f"{record.label}: {record.value}",
            evidence_ids=(item.evidence_id,),
            method=VersionReference(
                SPOT_WYCKOFF_INDICATOR_ID, SPOT_WYCKOFF_METHOD_VERSION
            ),
            invalidation_condition=record.invalidation_condition,
            limitations=(*_LIMITATIONS, *_UNCERTAINTY),
        )
        for record, item in zip(records, evidence, strict=True)
        if record.classification is ClaimClassification.INFERENCE
    )
    domain_observations = tuple(
        DomainObservation(
            observation_type=record.category,
            value=canonical_json_dumps(
                {
                    "label": record.label,
                    "value": record.value,
                    "as_of": max(
                        candle_tuple[index].end for index in record.candle_indices
                    ),
                    "source_market_data_ids": tuple(
                        candle_tuple[index].observation.market_data_id
                        for index in record.candle_indices
                    ),
                    "supporting_market_data_ids": tuple(
                        candle_tuple[index].observation.market_data_id
                        for index in record.supporting_indices
                    ),
                    "contradictory_market_data_ids": tuple(
                        candle_tuple[index].observation.market_data_id
                        for index in record.contradictory_indices
                    ),
                    "alternative_explanation": record.alternative_explanation,
                    "invalidation_condition": record.invalidation_condition,
                }
            ),
            unit=price_unit if record.category == "phase" else None,
            timeframe=timeframe,
            calculation=VersionReference(
                SPOT_WYCKOFF_INDICATOR_ID, SPOT_WYCKOFF_METHOD_VERSION
            ),
            evidence_ids=(item.evidence_id,),
        )
        for record, item in zip(records, evidence, strict=True)
    )
    contradiction_ids = tuple(
        item.evidence_id
        for item in evidence
        if item.relation is EvidenceRelation.CONTRADICTING
    )
    uncertainty_ids = tuple(item.evidence_id for item in evidence if item.limitations)
    assessment = WyckoffAssessment(
        assessment_id=_stable_id(
            "assessment",
            snapshot.snapshot_id,
            quality.report_id,
            SPOT_WYCKOFF_METHOD_VERSION,
            policy.policy_id,
            policy.version,
            tuple(item.evidence_id for item in evidence),
        ),
        asset=snapshot.instrument_id,
        instrument_id=snapshot.instrument_id,
        timeframe=timeframe,
        as_of=as_of,
        available_at=quality.assessed_at,
        expires_at=expires_at,
        status=AssessmentStatus.AVAILABLE if findings else AssessmentStatus.UNAVAILABLE,
        analytical_confidence=Decimal(0),
        findings=findings,
        observations=domain_observations,
        evidence_ids=tuple(item.evidence_id for item in evidence),
        contradiction_ids=contradiction_ids,
        uncertainty_ids=uncertainty_ids,
        data_quality_report_id=quality.report_id,
        provenance=(
            VersionReference("C-001", "1"),
            VersionReference("C-002", "1"),
            VersionReference("C-003", "1"),
            VersionReference("C-008", "1"),
            VersionReference("C-014", "1"),
            VersionReference(SPOT_WYCKOFF_INDICATOR_ID, SPOT_WYCKOFF_METHOD_VERSION),
            VersionReference(policy.policy_id, policy.version),
        ),
        methodology=MethodologyCategory.TECHNICAL,
    )
    output = tuple(
        WyckoffObservation(
            category=record.category,
            label=record.label,
            value=record.value,
            timeframe=timeframe,
            as_of=max(candle_tuple[index].end for index in record.candle_indices),
            source_market_data_ids=tuple(
                candle_tuple[index].observation.market_data_id
                for index in record.candle_indices
            ),
            supporting_market_data_ids=tuple(
                candle_tuple[index].observation.market_data_id
                for index in record.supporting_indices
            ),
            contradictory_market_data_ids=tuple(
                candle_tuple[index].observation.market_data_id
                for index in record.contradictory_indices
            ),
            invalidation_condition=record.invalidation_condition,
            alternative_explanation=record.alternative_explanation,
            evidence_id=evidence_by_id[item.evidence_id].evidence_id,
        )
        for record, item in zip(records, evidence, strict=True)
    )
    return SpotWyckoffAnalysis(
        indicator_id=metadata.indicator_id,
        metadata_version=metadata.metadata_version,
        method_version=metadata.calculation_version,
        timeframe=timeframe,
        instrument_id=snapshot.instrument_id,
        venue_id=snapshot.venue_id,
        snapshot_id=snapshot.snapshot_id,
        quality_report_id=quality.report_id,
        as_of=as_of,
        evidence_expires_at=expires_at,
        source_record_ids=snapshot.source_record_ids,
        input_market_data_ids=snapshot.market_data_ids,
        policy=policy,
        observations=output,
        evidence=evidence,
        assessment=assessment,
    )
