"""Versioned research indicator metadata; no indicator values or authority."""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from enum import StrEnum
from types import MappingProxyType
from typing import Mapping


class IndicatorMetadataError(ValueError):
    """Invalid or ambiguous indicator metadata."""


class IndicatorCategory(StrEnum):
    TREND = "trend"
    MOMENTUM = "momentum"
    VOLATILITY_RISK = "volatility-risk"
    VOLUME_STRUCTURE = "volume-structure"
    MARKET_STRUCTURE = "market-structure"
    VOLUME_CONFIRMATION = "volume-confirmation"


class IndicatorPhase(StrEnum):
    PLANNED = "planned"
    VALIDATED = "validated"


class IndicatorTiming(StrEnum):
    LAGGING = "lagging"
    CONFIRMATORY = "confirmatory"
    EARLY_WARNING = "early-warning"


_IDENTIFIER = re.compile(r"[a-z][a-z0-9-]{1,63}\Z")
_VERSION = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}\Z")
_TIMEFRAMES = frozenset({"1m", "5m", "15m", "1h", "4h", "1d"})


def _text(name: str, value: object) -> None:
    if not isinstance(value, str) or not value or value != value.strip():
        raise IndicatorMetadataError(f"{name} must be nonblank plain text.")
    if len(value) > 512:
        raise IndicatorMetadataError(f"{name} exceeds the metadata limit.")


def _texts(name: str, values: object, *, allow_empty: bool = False) -> None:
    if not isinstance(values, tuple) or (not values and not allow_empty):
        raise IndicatorMetadataError(f"{name} must be a nonempty tuple.")
    for value in values:
        _text(name, value)
    if len(set(values)) != len(values):
        raise IndicatorMetadataError(f"{name} must not contain duplicates.")


@dataclass(frozen=True, slots=True)
class ParameterMetadata:
    name: str
    unit: str
    default: int
    minimum: int
    maximum: int

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not _IDENTIFIER.fullmatch(self.name):
            raise IndicatorMetadataError("Invalid parameter name.")
        _text("parameter unit", self.unit)
        if (
            type(self.default) is not int
            or type(self.minimum) is not int
            or type(self.maximum) is not int
            or not 1 <= self.minimum <= self.default <= self.maximum <= 10000
        ):
            raise IndicatorMetadataError("Invalid parameter bounds or default.")


@dataclass(frozen=True, slots=True)
class IndicatorMetadata:
    indicator_id: str
    metadata_version: str
    calculation_version: str
    display_name: str
    category: IndicatorCategory
    purpose: str
    inputs: tuple[str, ...]
    timeframes: tuple[str, ...]
    parameters: tuple[ParameterMetadata, ...]
    minimum_warmup_candles: int
    output_unit: str
    output_schema: str
    output_nullable: bool
    timing: IndicatorTiming
    best_regimes: tuple[str, ...]
    weak_regimes: tuple[str, ...]
    failure_modes: tuple[str, ...]
    evidence_independent: bool
    evidence_dependencies: tuple[str, ...]
    evidence_graph_role: str
    phase: IndicatorPhase = IndicatorPhase.PLANNED

    def __post_init__(self) -> None:
        if not isinstance(self.indicator_id, str) or not _IDENTIFIER.fullmatch(
            self.indicator_id
        ):
            raise IndicatorMetadataError("Invalid indicator ID.")
        for name, version in (
            ("metadata version", self.metadata_version),
            ("calculation version", self.calculation_version),
        ):
            if not isinstance(version, str) or not _VERSION.fullmatch(version):
                raise IndicatorMetadataError(f"Invalid {name}.")
        for name in (
            "display_name",
            "purpose",
            "output_unit",
            "output_schema",
            "evidence_graph_role",
        ):
            _text(name, getattr(self, name))
        if not isinstance(self.category, IndicatorCategory):
            raise IndicatorMetadataError("Invalid indicator category.")
        if not isinstance(self.timing, IndicatorTiming):
            raise IndicatorMetadataError("Invalid indicator timing.")
        if not isinstance(self.phase, IndicatorPhase):
            raise IndicatorMetadataError("Invalid indicator phase.")
        for name in (
            "inputs",
            "timeframes",
            "best_regimes",
            "weak_regimes",
            "failure_modes",
            "evidence_dependencies",
        ):
            _texts(
                name, getattr(self, name), allow_empty=name == "evidence_dependencies"
            )
        if set(self.timeframes) - _TIMEFRAMES:
            raise IndicatorMetadataError("Unsupported timeframe in metadata.")
        if (
            not isinstance(self.parameters, tuple)
            or not all(isinstance(item, ParameterMetadata) for item in self.parameters)
            or len({item.name for item in self.parameters}) != len(self.parameters)
        ):
            raise IndicatorMetadataError("Invalid or duplicate parameter metadata.")
        if (
            type(self.minimum_warmup_candles) is not int
            or self.minimum_warmup_candles < 1
        ):
            raise IndicatorMetadataError("Invalid minimum warm-up.")
        if type(self.output_nullable) is not bool:
            raise IndicatorMetadataError("output_nullable must be a boolean.")
        if type(self.evidence_independent) is not bool:
            raise IndicatorMetadataError("evidence_independent must be a boolean.")
        if self.evidence_independent and self.evidence_dependencies:
            raise IndicatorMetadataError(
                "Independent evidence cannot declare dependencies."
            )
        if not self.evidence_independent and not self.evidence_dependencies:
            raise IndicatorMetadataError(
                "Dependent evidence must identify dependencies."
            )
        if (
            self.phase is IndicatorPhase.VALIDATED
            and self.calculation_version.startswith("planned-")
        ):
            raise IndicatorMetadataError(
                "A planned calculation version cannot be marked validated."
            )
        if (
            self.phase is IndicatorPhase.PLANNED
            and not self.calculation_version.startswith("planned-")
        ):
            raise IndicatorMetadataError(
                "A planned indicator needs a planned calculation version."
            )


class IndicatorRegistry:
    """Exact-version lookup; never substitutes latest metadata or values."""

    def __init__(self, entries: tuple[IndicatorMetadata, ...]) -> None:
        if not isinstance(entries, tuple) or not all(
            isinstance(item, IndicatorMetadata) for item in entries
        ):
            raise IndicatorMetadataError("Entries must be indicator metadata.")
        indexed: dict[tuple[str, str], IndicatorMetadata] = {}
        for entry in entries:
            key = (entry.indicator_id, entry.metadata_version)
            if key in indexed:
                raise IndicatorMetadataError("Duplicate indicator metadata version.")
            indexed[key] = entry
        self._entries: Mapping[tuple[str, str], IndicatorMetadata] = MappingProxyType(
            indexed
        )

    def get(self, indicator_id: str, metadata_version: str) -> IndicatorMetadata:
        try:
            return self._entries[(indicator_id, metadata_version)]
        except KeyError as exc:
            raise IndicatorMetadataError(
                "Unknown exact indicator metadata version."
            ) from exc

    def list_entries(self) -> tuple[IndicatorMetadata, ...]:
        return tuple(self._entries[key] for key in sorted(self._entries))


_SPOT_TIMEFRAMES = ("1m", "5m", "15m", "1h", "4h", "1d")


def _ema(period: int) -> IndicatorMetadata:
    return IndicatorMetadata(
        indicator_id=f"ema-{period}",
        metadata_version="1",
        calculation_version="planned-ema-v1",
        display_name=f"EMA {period}",
        category=IndicatorCategory.TREND,
        purpose="Describe a smoothed price trend for research context.",
        inputs=("C-001:closed-spot-ohlcv.close", "C-003:quality"),
        timeframes=_SPOT_TIMEFRAMES,
        parameters=(ParameterMetadata("period", "candles", period, 2, 500),),
        minimum_warmup_candles=period,
        output_unit="quote-currency-per-base-unit",
        output_schema="nullable finite Decimal price; source snapshot and method version required",
        output_nullable=True,
        timing=IndicatorTiming.LAGGING,
        best_regimes=("sustained-trend",),
        weak_regimes=("sideways-whipsaw", "stale-or-gapped-market"),
        failure_modes=("lag", "whipsaw", "insufficient-warmup", "missing-data"),
        evidence_independent=False,
        evidence_dependencies=("spot-close-price", "other-price-derived-indicators"),
        evidence_graph_role="Technical trend context; correlated with price and other EMAs.",
    )


def _atr() -> IndicatorMetadata:
    return IndicatorMetadata(
        indicator_id="atr-14",
        metadata_version="1",
        calculation_version="planned-atr-v1",
        display_name="ATR 14",
        category=IndicatorCategory.VOLATILITY_RISK,
        purpose="Describe recent true-range volatility, without sizing authority.",
        inputs=(
            "C-001:closed-spot-ohlcv.high",
            "C-001:closed-spot-ohlcv.low",
            "C-001:closed-spot-ohlcv.close",
            "C-003:quality",
        ),
        timeframes=_SPOT_TIMEFRAMES,
        parameters=(ParameterMetadata("period", "candles", 14, 2, 500),),
        minimum_warmup_candles=15,
        output_unit="quote-currency-per-base-unit",
        output_schema="nullable finite Decimal true-range price; source snapshot and method version required",
        output_nullable=True,
        timing=IndicatorTiming.CONFIRMATORY,
        best_regimes=("observable-volatility",),
        weak_regimes=("stale-or-gapped-market",),
        failure_modes=("lag", "insufficient-warmup", "missing-data"),
        evidence_independent=False,
        evidence_dependencies=("spot-high-low-close", "price-derived-indicators"),
        evidence_graph_role="Technical volatility context; not independent trade support.",
    )


def _momentum(
    *,
    indicator_id: str,
    display_name: str,
    calculation_version: str,
    purpose: str,
    inputs: tuple[str, ...],
    parameters: tuple[ParameterMetadata, ...],
    warmup: int,
    unit: str,
    output_schema: str,
    failure_modes: tuple[str, ...],
) -> IndicatorMetadata:
    return IndicatorMetadata(
        indicator_id=indicator_id,
        metadata_version="1",
        calculation_version=calculation_version,
        display_name=display_name,
        category=IndicatorCategory.MOMENTUM,
        purpose=purpose,
        inputs=inputs + ("C-003:quality",),
        timeframes=_SPOT_TIMEFRAMES,
        parameters=parameters,
        minimum_warmup_candles=warmup,
        output_unit=unit,
        output_schema=output_schema,
        output_nullable=True,
        timing=IndicatorTiming.CONFIRMATORY,
        best_regimes=("observable-momentum",),
        weak_regimes=("stale-or-gapped-market",),
        failure_modes=failure_modes + ("insufficient-warmup", "missing-data"),
        evidence_independent=False,
        evidence_dependencies=("spot-close-price", "price-derived-momentum-indicators"),
        evidence_graph_role=(
            "Descriptive momentum context; correlated with shared Spot price inputs "
            "and other momentum indicators, not independent evidence."
        ),
        phase=IndicatorPhase.VALIDATED,
    )


_MOMENTUM_METADATA = (
    _momentum(
        indicator_id="rsi",
        display_name="Relative Strength Index",
        calculation_version="rsi-wilder-sma-seed-v1",
        purpose="Describe Wilder-smoothed close-to-close momentum.",
        inputs=("C-001:closed-spot-ohlcv.close",),
        parameters=(ParameterMetadata("period", "candles", 14, 2, 500),),
        warmup=15,
        unit="percent",
        output_schema="nullable Decimal from 0 to 100 with explicit warm-up status",
        failure_modes=("flat-price-boundary",),
    ),
    _momentum(
        indicator_id="macd",
        display_name="Moving Average Convergence Divergence",
        calculation_version="macd-sma-seed-ema-v1",
        purpose="Describe the difference between fast and slow SMA-seeded EMAs.",
        inputs=("C-001:closed-spot-ohlcv.close",),
        parameters=(
            ParameterMetadata("fast-period", "candles", 12, 2, 499),
            ParameterMetadata("slow-period", "candles", 26, 3, 500),
            ParameterMetadata("signal-period", "candles", 9, 2, 500),
        ),
        warmup=34,
        unit="quote-currency-per-base-unit",
        output_schema=(
            "nullable Decimal MACD line, signal line, and histogram with per-component "
            "warm-up status"
        ),
        failure_modes=("invalid-period-relationship",),
    ),
    _momentum(
        indicator_id="stochastic",
        display_name="Stochastic Oscillator",
        calculation_version="stochastic-trailing-sma-v1",
        purpose="Describe close location within a trailing Spot high-low range.",
        inputs=(
            "C-001:closed-spot-ohlcv.high",
            "C-001:closed-spot-ohlcv.low",
            "C-001:closed-spot-ohlcv.close",
        ),
        parameters=(
            ParameterMetadata("k-period", "candles", 14, 2, 500),
            ParameterMetadata("d-period", "candles", 3, 2, 500),
        ),
        warmup=16,
        unit="percent",
        output_schema=(
            "nullable Decimal %K and %D with explicit warm-up and zero-range reasons"
        ),
        failure_modes=("zero-high-low-range",),
    ),
    _momentum(
        indicator_id="cci",
        display_name="Commodity Channel Index",
        calculation_version="cci-typical-price-mean-deviation-v1",
        purpose="Describe typical-price displacement from its trailing mean.",
        inputs=(
            "C-001:closed-spot-ohlcv.high",
            "C-001:closed-spot-ohlcv.low",
            "C-001:closed-spot-ohlcv.close",
        ),
        parameters=(ParameterMetadata("period", "candles", 20, 2, 500),),
        warmup=20,
        unit="dimensionless-index",
        output_schema="nullable Decimal CCI with explicit warm-up and zero-deviation reasons",
        failure_modes=("zero-mean-deviation",),
    ),
)

_VOLUME_STRUCTURE_METADATA = (
    IndicatorMetadata(
        indicator_id="volume-confirmation",
        metadata_version="1",
        calculation_version="trailing-prior-volume-mean-relative-v1",
        display_name="Trailing Relative Volume Confirmation",
        category=IndicatorCategory.VOLUME_CONFIRMATION,
        purpose=(
            "Describe raw and trailing-relative Spot candle volume; assess only an "
            "explicit candidate event under its caller-supplied confirmation policy."
        ),
        inputs=(
            "C-001:closed-spot-ohlcv.high",
            "C-001:closed-spot-ohlcv.low",
            "C-001:closed-spot-ohlcv.close",
            "C-001:closed-spot-ohlcv.volume",
            "C-002:snapshot",
            "C-003:quality",
        ),
        timeframes=_SPOT_TIMEFRAMES,
        parameters=(ParameterMetadata("lookback", "candles", 20, 2, 500),),
        minimum_warmup_candles=3,
        output_unit="input-volume-unit-and-dimensionless-ratio",
        output_schema=(
            "per-candle Decimal raw volume, exact prior-volume sum, trailing mean "
            "excluding current candle, and nullable relative volume with explicit "
            "unavailable reason"
        ),
        output_nullable=True,
        timing=IndicatorTiming.CONFIRMATORY,
        best_regimes=("observable-volume",),
        weak_regimes=("stale-or-gapped-market",),
        failure_modes=(
            "insufficient-prior-volume",
            "zero-prior-volume-baseline",
            "missing-or-invalid-volume",
            "calculation-precision-limit",
            "calculation-exponent-limit",
        ),
        evidence_independent=False,
        evidence_dependencies=("spot-price-volume", "ohlcv-derived-indicators"),
        evidence_graph_role=(
            "Descriptive Spot OHLCV volume evidence; correlated with its source "
            "candles, VWAP, volume profile, and other OHLCV-derived features."
        ),
        phase=IndicatorPhase.VALIDATED,
    ),
    IndicatorMetadata(
        indicator_id="vwap",
        metadata_version="1",
        calculation_version="bar-typical-price-cumulative-v1",
        display_name="Bar-based Typical-price VWAP",
        category=IndicatorCategory.VOLUME_STRUCTURE,
        purpose=(
            "Describe cumulative typical-price VWAP from the first supplied candle; "
            "this OHLCV approximation is not trade-by-trade VWAP."
        ),
        inputs=(
            "C-001:closed-spot-ohlcv.high",
            "C-001:closed-spot-ohlcv.low",
            "C-001:closed-spot-ohlcv.close",
            "C-001:closed-spot-ohlcv.volume",
            "C-002:snapshot",
            "C-003:quality",
        ),
        timeframes=_SPOT_TIMEFRAMES,
        parameters=(),
        minimum_warmup_candles=1,
        output_unit="input-price-unit",
        output_schema="per-candle nullable Decimal with explicit undefined reason",
        output_nullable=True,
        timing=IndicatorTiming.CONFIRMATORY,
        best_regimes=("observable-volume",),
        weak_regimes=("stale-or-gapped-market",),
        failure_modes=(
            "zero-cumulative-volume",
            "missing-or-invalid-volume",
            "calculation-precision-limit",
            "calculation-exponent-limit",
        ),
        evidence_independent=False,
        evidence_dependencies=("spot-price-volume", "ohlcv-derived-indicators"),
        evidence_graph_role=(
            "Descriptive bar-based price-volume context; correlated with its Spot "
            "OHLCV inputs and not independent evidence."
        ),
        phase=IndicatorPhase.VALIDATED,
    ),
    IndicatorMetadata(
        indicator_id="volume-profile",
        metadata_version="1",
        calculation_version="candle-assigned-volume-profile-proxy-v1",
        display_name="Candle-assigned Volume Profile Proxy",
        category=IndicatorCategory.VOLUME_STRUCTURE,
        purpose=(
            "Describe candle-assigned volume across typical-price bins; this OHLCV "
            "proxy is not trade-level volume-at-price or exact VPVR."
        ),
        inputs=(
            "C-001:closed-spot-ohlcv.high",
            "C-001:closed-spot-ohlcv.low",
            "C-001:closed-spot-ohlcv.close",
            "C-001:closed-spot-ohlcv.volume",
            "C-002:snapshot",
            "C-003:quality",
        ),
        timeframes=_SPOT_TIMEFRAMES,
        parameters=(
            ParameterMetadata("bin-count", "bins", 24, 1, 500),
            ParameterMetadata("value-area-percent", "percent", 70, 50, 100),
        ),
        minimum_warmup_candles=1,
        output_unit="input-volume-unit-per-price-bin",
        output_schema=(
            "nullable Decimal bin distribution with optional POC/value-area/nodes "
            "and explicit undefined reason"
        ),
        output_nullable=True,
        timing=IndicatorTiming.CONFIRMATORY,
        best_regimes=("observable-volume",),
        weak_regimes=("stale-or-gapped-market",),
        failure_modes=(
            "zero-total-volume",
            "missing-or-invalid-volume",
            "calculation-precision-limit",
            "calculation-exponent-limit",
        ),
        evidence_independent=False,
        evidence_dependencies=("spot-price-volume", "ohlcv-derived-indicators"),
        evidence_graph_role=(
            "Descriptive candle-assigned price-volume proxy; correlated with its Spot "
            "OHLCV inputs and not independent evidence."
        ),
        phase=IndicatorPhase.VALIDATED,
    ),
)


SPOT_RESEARCH_INDICATORS = IndicatorRegistry(
    (
        *_MOMENTUM_METADATA,
        *_VOLUME_STRUCTURE_METADATA,
        _ema(20),
        _ema(50),
        replace(
            _ema(20),
            metadata_version="2",
            calculation_version="ema-sma-seed-v1",
            phase=IndicatorPhase.VALIDATED,
        ),
        replace(
            _ema(50),
            metadata_version="2",
            calculation_version="ema-sma-seed-v1",
            phase=IndicatorPhase.VALIDATED,
        ),
        *(
            IndicatorMetadata(
                indicator_id=kind,
                metadata_version="1",
                calculation_version=(
                    "ema-sma-seed-v1" if kind == "ema" else f"{kind}-close-v1"
                ),
                display_name=kind.upper(),
                category=IndicatorCategory.TREND,
                purpose="Describe a trailing price trend for research context.",
                inputs=("C-001:closed-spot-ohlcv.close", "C-003:quality"),
                timeframes=_SPOT_TIMEFRAMES,
                parameters=(ParameterMetadata("period", "candles", 20, 2, 500),),
                minimum_warmup_candles=2,
                output_unit="quote-currency-per-base-unit",
                output_schema="nullable finite Decimal price; source snapshot and method version required",
                output_nullable=True,
                timing=IndicatorTiming.LAGGING,
                best_regimes=("sustained-trend",),
                weak_regimes=("sideways-whipsaw", "stale-or-gapped-market"),
                failure_modes=(
                    "lag",
                    "whipsaw",
                    "insufficient-warmup",
                    "missing-data",
                ),
                evidence_independent=False,
                evidence_dependencies=(
                    "spot-close-price",
                    "other-price-derived-indicators",
                ),
                evidence_graph_role="Technical trend context; correlated with price.",
                phase=IndicatorPhase.VALIDATED,
            )
            for kind in ("sma", "ema", "wma")
        ),
        _atr(),
        replace(
            _atr(),
            metadata_version="2",
            calculation_version="atr-wilder-sma-seed-v1",
            phase=IndicatorPhase.VALIDATED,
        ),
        *(
            IndicatorMetadata(
                indicator_id=indicator_id,
                metadata_version="1",
                calculation_version=calculation_version,
                display_name=display_name,
                category=IndicatorCategory.VOLATILITY_RISK,
                purpose=purpose,
                inputs=inputs,
                timeframes=_SPOT_TIMEFRAMES,
                parameters=(ParameterMetadata("period", "candles", 20, 2, 500),),
                minimum_warmup_candles=warmup,
                output_unit=unit,
                output_schema=output_schema,
                output_nullable=True,
                timing=IndicatorTiming.CONFIRMATORY,
                best_regimes=("observable-volatility",),
                weak_regimes=("stale-or-gapped-market",),
                failure_modes=("insufficient-warmup", "missing-data", "lag"),
                evidence_independent=False,
                evidence_dependencies=("spot-close-price", "price-derived-indicators"),
                evidence_graph_role="Price-derived volatility context; not independent evidence.",
                phase=IndicatorPhase.VALIDATED,
            )
            for (
                indicator_id,
                calculation_version,
                display_name,
                purpose,
                inputs,
                warmup,
                unit,
                output_schema,
            ) in (
                (
                    "bollinger-bands",
                    "bollinger-population-2sigma-v1",
                    "Bollinger Bands",
                    "Describe a trailing close range using population standard deviation.",
                    ("C-001:closed-spot-ohlcv.close", "C-003:quality"),
                    20,
                    "quote-currency-per-base-unit",
                    "nullable finite Decimal middle, upper and lower bands; fixed 2 sigma multiplier",
                ),
                (
                    "bollinger-bandwidth",
                    "bollinger-width-ratio-v1",
                    "Bollinger Band Width",
                    "Describe relative band width; direction is compared with the prior width.",
                    ("C-001:closed-spot-ohlcv.close", "C-003:quality"),
                    20,
                    "dimensionless-ratio",
                    "nullable finite Decimal (upper-lower)/middle ratio and prior-period direction",
                ),
                (
                    "realized-volatility",
                    "annualized-close-log-return-sample-stdev-v1",
                    "Annualized Realized Volatility",
                    "Describe annualized sample dispersion of close-to-close log returns.",
                    ("C-001:closed-spot-ohlcv.close", "C-003:quality"),
                    21,
                    "annualized-fraction",
                    "nullable finite Decimal fraction; 365-day continuous-market annualization",
                ),
            )
        ),
    )
)
