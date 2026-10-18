"""Deterministic, provenance-bound Spot OHLCV regime context (C-005)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid5

from trading_platform_api.analysis.contracts import (
    AnalyticalDirection,
    ClaimClassification,
    EvidenceItem,
    EvidenceRelation,
    MarketRegime,
    RegimeDimension,
    VersionReference,
)
from trading_platform_api.analysis.moving_averages import (
    MovingAverageKind,
    MovingAverageSeries,
    calculate_moving_average,
)
from trading_platform_api.analysis.volatility import (
    VolatilitySeries,
    calculate_realized_volatility,
)
from trading_platform_api.market_data.contracts import (
    DataQualityReport,
    DataQualityStatus,
    MarketData,
    MarketSnapshot,
)

SPOT_MARKET_REGIME_METHOD_VERSION = "spot-market-regime-v1"
SPOT_MARKET_REGIME_PROFILE_VERSION = "spot-ohlcv-regime-profile-v1"
_IDENTITY_NAMESPACE = UUID("6c9239e9-cf4c-5f37-b8c2-9c13a6e1f82e")
_TIMEFRAME_SECONDS = {
    "1m": 60,
    "5m": 300,
    "15m": 900,
    "1h": 3600,
    "4h": 14400,
    "1d": 86400,
}
_VOLATILITY_REFERENCE_POINTS = 20
_VOLATILITY_HIGH_RATIO = Decimal("1.5")
_VOLATILITY_LOW_RATIO = Decimal("0.5")
_TRANSITION_LOOKBACK_CANDLES = 5


class SpotMarketRegimeError(ValueError):
    """Spot regime cannot be safely classified from the supplied evidence."""


class SpotMarketRegimeWarmup(SpotMarketRegimeError):
    """The exact profile inputs have not completed their required warm-up."""


@dataclass(frozen=True, slots=True)
class SpotMarketRegimeResult:
    regime: MarketRegime
    evidence: tuple[EvidenceItem, ...]
    profile_id: str
    profile_version: str
    transition_state: str
    transition_lookback_candles: int
    uncertainty: tuple[str, ...]
    limitations: tuple[str, ...]
    confidence_semantics: str


def _median(values: tuple[Decimal, ...]) -> Decimal:
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / Decimal(2)


def _trend_state(close: Decimal, ema20: Decimal, ema50: Decimal) -> str:
    if close > ema20 > ema50:
        return "bullish"
    if close < ema20 < ema50:
        return "bearish"
    return "mixed"


def _volatility_state(current: Decimal, baseline: Decimal) -> tuple[str, Decimal]:
    if baseline <= 0:
        raise SpotMarketRegimeError("The prior realized-volatility baseline is zero.")
    ratio = current / baseline
    state = (
        "high"
        if ratio >= _VOLATILITY_HIGH_RATIO
        else "low"
        if ratio <= _VOLATILITY_LOW_RATIO
        else "typical"
    )
    return state, ratio


def _transition_state(current: str, recent: tuple[str, ...]) -> str:
    return (
        "possible"
        if current == "mixed" or any(state != current for state in recent)
        else "not-observed-in-lookback"
    )


def _stable_id(snapshot_id: UUID, feature_id: str) -> UUID:
    return uuid5(
        _IDENTITY_NAMESPACE,
        f"{snapshot_id}:{SPOT_MARKET_REGIME_METHOD_VERSION}:{feature_id}",
    )


def _evidence(
    *,
    snapshot: MarketSnapshot,
    quality: DataQualityReport,
    timeframe: str,
    observed_at: datetime,
    feature_id: str,
    value: str,
    unit: str | None,
    interpretation: str,
    source_method_versions: tuple[VersionReference, ...],
) -> EvidenceItem:
    method = VersionReference(
        component="spot-market-regime",
        version=SPOT_MARKET_REGIME_METHOD_VERSION,
    )
    provenance = (
        VersionReference(component="C-001", version="1"),
        VersionReference(component="C-002", version="1"),
        VersionReference(component="C-003", version="1"),
        method,
        VersionReference(
            component="spot-ohlcv-regime-profile",
            version=SPOT_MARKET_REGIME_PROFILE_VERSION,
        ),
        *source_method_versions,
    )
    unique_provenance = tuple(dict.fromkeys(provenance))
    dataset_versions = (
        (snapshot.dataset_version,) if snapshot.dataset_version is not None else ()
    )
    return EvidenceItem(
        evidence_id=_stable_id(snapshot.snapshot_id, feature_id),
        source_record_ids=snapshot.source_record_ids,
        dataset_versions=dataset_versions,
        feature_ids=(f"{feature_id}:{timeframe}",),
        classification=ClaimClassification.INFERENCE,
        relation=EvidenceRelation.SUPPORTING,
        observed_at=observed_at,
        available_at=quality.assessed_at,
        expires_at=quality.assessed_at
        + timedelta(seconds=_TIMEFRAME_SECONDS[timeframe]),
        method=method,
        value=value,
        unit=unit,
        interpretation=interpretation,
        quality_status=quality.status,
        data_quality_report_id=quality.report_id,
        reliability=quality.source_reliability,
        limitations=(
            "Deterministic descriptive rule; not a signal, forecast, or trade decision.",
            "All dimensions use the same Spot OHLCV source and are correlated.",
        ),
        provenance=unique_provenance,
        usable=True,
    )


def _aligned_latest(
    series: MovingAverageSeries | VolatilitySeries,
    *,
    snapshot: MarketSnapshot,
    quality: DataQualityReport,
    timeframe: str,
    expected_candle_end: datetime,
) -> Decimal:
    if (
        series.instrument_id != snapshot.instrument_id
        or series.venue_id != snapshot.venue_id
        or series.snapshot_id != snapshot.snapshot_id
        or series.quality_report_id != quality.report_id
        or series.as_of != snapshot.as_of
        or series.timeframe != timeframe
        or series.input_market_data_ids != snapshot.market_data_ids
        or not series.points
    ):
        raise SpotMarketRegimeError("Calculated inputs are not bound to this snapshot.")
    latest = series.points[-1]
    if latest.candle_end != expected_candle_end or latest.value is None:
        raise SpotMarketRegimeWarmup("Required latest indicator value is unavailable.")
    return latest.value


def calculate_spot_market_regime(
    *,
    snapshot: MarketSnapshot,
    observations: tuple[MarketData, ...],
    quality: DataQualityReport,
    timeframe: str,
) -> SpotMarketRegimeResult:
    """Classify trend/volatility context from one exact VALID Spot snapshot.

    Profile v1 requires EMA 20/50, current RV20, and 20 prior RV20 values.
    Volatility is high at >=1.5x the prior-window median and low at <=0.5x.
    This thresholded description is versioned and is not statistically validated.
    """
    if quality.status is not DataQualityStatus.VALID:
        raise SpotMarketRegimeError(
            "Matching VALID C-003 quality evidence is required."
        )
    if quality.snapshot_id != snapshot.snapshot_id:
        raise SpotMarketRegimeError("C-003 quality report does not match the snapshot.")
    if timeframe not in _TIMEFRAME_SECONDS:
        raise SpotMarketRegimeError("Unsupported Spot regime timeframe.")
    if (
        not observations
        or tuple(item.market_data_id for item in observations)
        != snapshot.market_data_ids
    ):
        raise SpotMarketRegimeError("Observation identity does not match the snapshot.")
    if snapshot.instrument_id.split("-")[-1] != "SPOT":
        raise SpotMarketRegimeError(
            "The selected profile accepts Spot instruments only."
        )

    ema20 = calculate_moving_average(
        snapshot=snapshot,
        observations=observations,
        quality=quality,
        kind=MovingAverageKind.EMA,
        period=20,
        timeframe=timeframe,
    )
    ema50 = calculate_moving_average(
        snapshot=snapshot,
        observations=observations,
        quality=quality,
        kind=MovingAverageKind.EMA,
        period=50,
        timeframe=timeframe,
    )
    rv20 = calculate_realized_volatility(
        snapshot=snapshot,
        observations=observations,
        quality=quality,
        period=20,
        timeframe=timeframe,
    )
    last_close_time = observations[-1].event_time + timedelta(
        seconds=_TIMEFRAME_SECONDS[timeframe]
    )
    _aligned_latest(
        ema20,
        snapshot=snapshot,
        quality=quality,
        timeframe=timeframe,
        expected_candle_end=last_close_time,
    )
    _aligned_latest(
        ema50,
        snapshot=snapshot,
        quality=quality,
        timeframe=timeframe,
        expected_candle_end=last_close_time,
    )
    latest_rv = _aligned_latest(
        rv20,
        snapshot=snapshot,
        quality=quality,
        timeframe=timeframe,
        expected_candle_end=last_close_time,
    )

    reference_values = tuple(
        point.value for point in rv20.points[:-1] if point.value is not None
    )[-_VOLATILITY_REFERENCE_POINTS:]
    if len(reference_values) < _VOLATILITY_REFERENCE_POINTS:
        raise SpotMarketRegimeWarmup(
            "Twenty completed prior RV20 observations are required."
        )
    volatility_baseline = _median(reference_values)
    volatility_state, ratio = _volatility_state(latest_rv, volatility_baseline)

    close_metric = next(
        (
            metric
            for metric in observations[-1].metrics
            if metric.metric_name == "close"
        ),
        None,
    )
    ema20_latest = ema20.points[-1].value
    ema50_latest = ema50.points[-1].value
    if close_metric is None or ema20_latest is None or ema50_latest is None:
        raise SpotMarketRegimeWarmup("Latest close and EMA values are required.")
    trend = _trend_state(close_metric.value, ema20_latest, ema50_latest)
    trend_states = tuple(
        _trend_state(
            next(
                metric.value
                for metric in observation.metrics
                if metric.metric_name == "close"
            ),
            ema20_point.value,
            ema50_point.value,
        )
        for observation, ema20_point, ema50_point in zip(
            observations[-_TRANSITION_LOOKBACK_CANDLES:],
            ema20.points[-_TRANSITION_LOOKBACK_CANDLES:],
            ema50.points[-_TRANSITION_LOOKBACK_CANDLES:],
            strict=True,
        )
        if ema20_point.value is not None and ema50_point.value is not None
    )
    transition_state = _transition_state(trend, trend_states)

    trend_methods = (
        VersionReference(
            component="ema-20",
            version=f"{ema20.metadata_version}:{ema20.calculation_version}",
        ),
        VersionReference(
            component="ema-50",
            version=f"{ema50.metadata_version}:{ema50.calculation_version}",
        ),
    )
    volatility_methods = (
        VersionReference(
            component="realized-volatility-20",
            version=f"{rv20.metadata_version}:{rv20.calculation_version}",
        ),
    )
    trend_evidence = _evidence(
        snapshot=snapshot,
        quality=quality,
        timeframe=timeframe,
        observed_at=last_close_time,
        feature_id="spot-trend-ema-20-50-v1",
        value=(
            f"state={trend}; close={close_metric.value}; "
            f"ema20={ema20_latest}; ema50={ema50_latest}"
        ),
        unit=close_metric.unit,
        interpretation=(
            "Bullish or bearish requires close and EMA 20/50 ordering to agree; "
            "other ordering is mixed context."
        ),
        source_method_versions=trend_methods,
    )
    volatility_evidence = _evidence(
        snapshot=snapshot,
        quality=quality,
        timeframe=timeframe,
        observed_at=last_close_time,
        feature_id="spot-volatility-rv20-relative-median-v1",
        value=(
            f"state={volatility_state}; current={latest_rv}; "
            f"prior_median={volatility_baseline}; ratio={ratio}"
        ),
        unit=rv20.unit,
        interpretation=(
            "Relative realized-volatility state against the median of the prior "
            "20 available RV20 observations."
        ),
        source_method_versions=volatility_methods,
    )
    transition_evidence = _evidence(
        snapshot=snapshot,
        quality=quality,
        timeframe=timeframe,
        observed_at=last_close_time,
        feature_id="spot-trend-transition-five-candles-v1",
        value=f"state={transition_state}; current_trend={trend}; recent={trend_states}",
        unit="candles",
        interpretation=(
            "A possible transition is flagged for mixed current ordering or a "
            "different trend state within the latest five candles. No observed "
            "transition does not establish that a regime is stable."
        ),
        source_method_versions=trend_methods,
    )
    evidence = (trend_evidence, volatility_evidence, transition_evidence)
    direction = {
        "bullish": AnalyticalDirection.BULLISH,
        "bearish": AnalyticalDirection.BEARISH,
        "mixed": AnalyticalDirection.MIXED,
    }[trend]
    dimensions = (
        RegimeDimension("trend", trend, (trend_evidence.evidence_id,)),
        RegimeDimension(
            "realized-volatility", volatility_state, (volatility_evidence.evidence_id,)
        ),
        RegimeDimension(
            "transition", transition_state, (transition_evidence.evidence_id,)
        ),
    )
    all_evidence_ids = tuple(item.evidence_id for item in evidence)
    regime = MarketRegime(
        regime_id=_stable_id(snapshot.snapshot_id, "market-regime"),
        asset=snapshot.instrument_id.split("-", maxsplit=1)[0],
        instrument_id=snapshot.instrument_id,
        timeframe=timeframe,
        as_of=last_close_time,
        expires_at=quality.assessed_at
        + timedelta(seconds=_TIMEFRAME_SECONDS[timeframe]),
        direction=direction,
        dimensions=dimensions,
        explanation=(
            f"Spot OHLCV profile {SPOT_MARKET_REGIME_PROFILE_VERSION} classifies "
            f"trend as {trend}, relative realized volatility as {volatility_state}, "
            f"and transition state as {transition_state}. This is market context "
            "only; the dimensions share price-derived inputs and are not independent "
            "trade confirmations."
        ),
        confidence=Decimal(0),
        evidence_ids=all_evidence_ids,
        compatible_strategy_families=(),
    )
    return SpotMarketRegimeResult(
        regime=regime,
        evidence=evidence,
        profile_id="spot-ohlcv",
        profile_version=SPOT_MARKET_REGIME_PROFILE_VERSION,
        transition_state=transition_state,
        transition_lookback_candles=_TRANSITION_LOOKBACK_CANDLES,
        uncertainty=(
            "C-005 confidence is uncalibrated and intentionally zero; it is not a "
            "probability or a measure of trade success.",
            "EMA ordering is lagging and cannot establish future direction.",
            "Relative-volatility thresholds are descriptive profile rules, not "
            "statistically validated regime boundaries.",
            "No transition observed in the five-candle lookback does not prove stability.",
            "Liquidity, trades/order flow, derivatives, cross-asset correlation, and "
            "macro are outside this Spot OHLCV profile and remain unassessed.",
        ),
        limitations=(
            "All evidence derives from the same validated Spot OHLCV snapshot and is correlated.",
            "No strategy family compatibility, signal, validation, risk, approval, or execution is produced.",
        ),
        confidence_semantics="uncalibrated-zero; not a probability",
    )
