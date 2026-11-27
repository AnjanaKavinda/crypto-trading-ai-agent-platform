"""Versioned rule-based Spot strategies for the lean research lane.

A strategy is an immutable parameter set plus deterministic rules. Any change
to a rule or parameter must ship as a new ``version``; results are always
reported against ``content_sha256``.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from decimal import Decimal
from hashlib import sha256

from trading_platform_api.research.candles import Candle
from trading_platform_api.research.indicators import (
    adx_wilder,
    atr_wilder,
    bollinger,
    ema,
    prior_highest_high,
    prior_lowest_low,
    realised_volatility,
    rsi_wilder,
    sma,
)


@dataclass(frozen=True, slots=True)
class StrategySignals:
    """Per-bar decisions known at that bar's close."""

    enter_long: tuple[bool, ...]
    exit_long: tuple[bool, ...]
    stop_distance: tuple[Decimal | None, ...]
    first_tradable_index: int
    # Trailing stop: after each held bar's close the stop becomes
    # max(stop, highest close since entry - trail_distance[i]). None = fixed.
    trail_distance: tuple[Decimal | None, ...] | None = None
    # Time stop: once a position has been held this many bars (entry bar
    # included) at a close, exit at the next open. None = no time stop.
    max_bars_held: int | None = None
    # No protective stop: ``stop_distance`` is ignored (tournament C1-C6, C8).
    stopless: bool = False
    # Fraction of equity invested at entry, known at the signal close and held
    # for the trade; None = the whole equity (tournament C8 only).
    position_fraction: tuple[Decimal | None, ...] | None = None


@dataclass(frozen=True, slots=True)
class EmaTrendAtrStop:
    """Long-only trend following.

    - Enter long at the next bar's open after EMA(fast) closes above EMA(slow)
      having been at or below it on the previous close.
    - Initial protective stop: entry fill minus ``stop_atr_multiple`` x ATR,
      using the ATR known at the signal close. The stop does not trail.
    - Exit at the next bar's open after EMA(fast) closes below EMA(slow), or at
      the stop if a bar trades through it (at the open if it gaps through).
    """

    strategy_id: str = "ema-trend-atr-stop"
    version: int = 1
    fast_period: int = 20
    slow_period: int = 50
    atr_period: int = 14
    stop_atr_multiple: Decimal = Decimal("2")

    def __post_init__(self) -> None:
        if not 1 < self.fast_period < self.slow_period:
            raise ValueError("Require 1 < fast_period < slow_period.")
        if self.atr_period < 1 or self.stop_atr_multiple <= 0:
            raise ValueError("ATR period and stop multiple must be positive.")

    def describe(self) -> dict[str, object]:
        payload = asdict(self)
        payload["stop_atr_multiple"] = str(self.stop_atr_multiple)
        return payload

    @property
    def content_sha256(self) -> str:
        document = json.dumps(self.describe(), sort_keys=True, separators=(",", ":"))
        return sha256(document.encode("utf-8")).hexdigest()

    def signals(self, candles: tuple[Candle, ...]) -> StrategySignals:
        closes = [item.close for item in candles]
        fast = ema(closes, self.fast_period)
        slow = ema(closes, self.slow_period)
        atr = atr_wilder(candles, self.atr_period)
        enter: list[bool] = []
        leave: list[bool] = []
        stops: list[Decimal | None] = []
        for index in range(len(candles)):
            now_f, now_s = fast[index], slow[index]
            before_f = fast[index - 1] if index > 0 else None
            before_s = slow[index - 1] if index > 0 else None
            ready = None not in (now_f, now_s, before_f, before_s)
            current_atr = atr[index]
            if ready:
                assert now_f is not None and now_s is not None
                assert before_f is not None and before_s is not None
                up = before_f <= before_s and now_f > now_s
                down = before_f >= before_s and now_f < now_s
            else:
                up = down = False
            usable = up and current_atr is not None and current_atr > 0
            enter.append(usable)
            leave.append(down)
            stops.append(
                current_atr * self.stop_atr_multiple
                if current_atr is not None
                else None
            )
        first = max(self.slow_period, self.atr_period + 1)
        return StrategySignals(tuple(enter), tuple(leave), tuple(stops), first)


@dataclass(frozen=True, slots=True)
class TrendDailyRegime:
    """Long-only daily trend regime (pre-registered on #516, 2026-11-26).

    - Trend state ``T(t) = EMA20 > EMA50 AND close > SMA200`` at close t.
    - Enter at the next open when ``T(t)`` is true and ``T(t-1)`` was false.
    - Initial stop: entry fill minus 3 x ATR14 known at the signal close.
    - Trailing stop: after each close, ``max(stop, highest close since entry
      - 3 x ATR14)``; never lowered.
    - Signal exit at the next open when EMA20 < EMA50 at close. No take-profit.
    """

    strategy_id: str = "trend-daily-regime"
    version: int = 1
    fast_period: int = 20
    slow_period: int = 50
    regime_period: int = 200
    atr_period: int = 14
    stop_atr_multiple: Decimal = Decimal("3")
    trail_atr_multiple: Decimal = Decimal("3")

    def __post_init__(self) -> None:
        if not 1 < self.fast_period < self.slow_period:
            raise ValueError("Require 1 < fast_period < slow_period.")
        if self.regime_period < 2 or self.atr_period < 1:
            raise ValueError("Regime and ATR periods must be positive.")
        if self.stop_atr_multiple <= 0 or self.trail_atr_multiple <= 0:
            raise ValueError("ATR multiples must be positive.")

    def describe(self) -> dict[str, object]:
        payload = asdict(self)
        payload["stop_atr_multiple"] = str(self.stop_atr_multiple)
        payload["trail_atr_multiple"] = str(self.trail_atr_multiple)
        return payload

    @property
    def content_sha256(self) -> str:
        document = json.dumps(self.describe(), sort_keys=True, separators=(",", ":"))
        return sha256(document.encode("utf-8")).hexdigest()

    def trend_state(self, candles: tuple[Candle, ...]) -> list[bool | None]:
        """``T(t)`` per bar; None while any input is still warming up."""
        closes = [item.close for item in candles]
        fast = ema(closes, self.fast_period)
        slow = ema(closes, self.slow_period)
        regime = sma(closes, self.regime_period)
        states: list[bool | None] = []
        for close, now_f, now_s, base in zip(closes, fast, slow, regime):
            if now_f is None or now_s is None or base is None:
                states.append(None)
            else:
                states.append(now_f > now_s and close > base)
        return states

    def signals(self, candles: tuple[Candle, ...]) -> StrategySignals:
        closes = [item.close for item in candles]
        fast = ema(closes, self.fast_period)
        slow = ema(closes, self.slow_period)
        atr = atr_wilder(candles, self.atr_period)
        states = self.trend_state(candles)
        enter: list[bool] = []
        leave: list[bool] = []
        stops: list[Decimal | None] = []
        trails: list[Decimal | None] = []
        for index in range(len(candles)):
            now = states[index]
            before = states[index - 1] if index > 0 else None
            current_atr = atr[index]
            turned_on = now is True and before is False
            enter.append(turned_on and current_atr is not None and current_atr > 0)
            now_f, now_s = fast[index], slow[index]
            leave.append(now_f is not None and now_s is not None and now_f < now_s)
            stops.append(
                current_atr * self.stop_atr_multiple
                if current_atr is not None
                else None
            )
            trails.append(
                current_atr * self.trail_atr_multiple
                if current_atr is not None
                else None
            )
        first = max(self.regime_period, self.atr_period + 1)
        return StrategySignals(
            tuple(enter), tuple(leave), tuple(stops), first, tuple(trails)
        )


@dataclass(frozen=True, slots=True)
class RangeReversion4h:
    """Long-only 4h range mean reversion (pre-registered on #516, 2026-11-26).

    - Enter at the next open when at close t: ``ADX14 < 20 AND close < lower
      Bollinger band (20, 2 sigma population) AND RSI14 < 30``.
    - Stop: entry fill minus 1.5 x ATR14 known at the signal close, fixed.
    - Exit at the next open after a close at or above the middle band (SMA20),
      or after 12 held bars (time stop). No take-profit beyond that.
    """

    strategy_id: str = "range-reversion-4h"
    version: int = 1
    band_period: int = 20
    rsi_period: int = 14
    adx_period: int = 14
    atr_period: int = 14
    adx_below: Decimal = Decimal("20")
    rsi_below: Decimal = Decimal("30")
    stop_atr_multiple: Decimal = Decimal("1.5")
    max_bars_held: int = 12

    def __post_init__(self) -> None:
        periods = (self.band_period, self.rsi_period, self.adx_period, self.atr_period)
        if min(periods) < 2 or self.max_bars_held < 1:
            raise ValueError("Periods must be at least 2 and the time stop positive.")
        if self.stop_atr_multiple <= 0:
            raise ValueError("The ATR stop multiple must be positive.")

    def describe(self) -> dict[str, object]:
        payload = asdict(self)
        for key in ("adx_below", "rsi_below", "stop_atr_multiple"):
            payload[key] = str(payload[key])
        return payload

    @property
    def content_sha256(self) -> str:
        document = json.dumps(self.describe(), sort_keys=True, separators=(",", ":"))
        return sha256(document.encode("utf-8")).hexdigest()

    def signals(self, candles: tuple[Candle, ...]) -> StrategySignals:
        closes = [item.close for item in candles]
        bands = bollinger(closes, self.band_period)
        rsi = rsi_wilder(closes, self.rsi_period)
        adx = adx_wilder(candles, self.adx_period)
        atr = atr_wilder(candles, self.atr_period)
        enter: list[bool] = []
        leave: list[bool] = []
        stops: list[Decimal | None] = []
        for index, close in enumerate(closes):
            band, strength, trend, current_atr = (
                bands[index],
                rsi[index],
                adx[index],
                atr[index],
            )
            ready = None not in (band, strength, trend, current_atr)
            if ready:
                assert band is not None and strength is not None
                assert trend is not None and current_atr is not None
                enter.append(
                    trend < self.adx_below
                    and close < band[2]
                    and strength < self.rsi_below
                    and current_atr > 0
                )
            else:
                enter.append(False)
            leave.append(band is not None and close >= band[0])
            stops.append(
                current_atr * self.stop_atr_multiple
                if current_atr is not None
                else None
            )
        first = max(
            self.band_period - 1,
            self.rsi_period,
            2 * self.adx_period - 1,
            self.atr_period,
        )
        return StrategySignals(
            tuple(enter),
            tuple(leave),
            tuple(stops),
            first,
            max_bars_held=self.max_bars_held,
        )


# --- Spot candidate tournament v1 (pre-registered on #516, 2026-11-27) -----
# Daily, long-only, one position per symbol; signal at close t, fill at the
# next open. C1-C6 and C8 have no protective stop. C9 is TrendDailyRegime v1.


def _digest(payload: dict[str, object]) -> str:
    document = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return sha256(document.encode("utf-8")).hexdigest()


def _stopless(
    enter: list[bool],
    leave: list[bool],
    first: int,
    *,
    max_bars_held: int | None = None,
    position_fraction: tuple[Decimal | None, ...] | None = None,
) -> StrategySignals:
    return StrategySignals(
        tuple(enter),
        tuple(leave),
        (None,) * len(enter),
        first,
        max_bars_held=max_bars_held,
        stopless=True,
        position_fraction=position_fraction,
    )


@dataclass(frozen=True, slots=True)
class Sma200LongCash:
    """C1: long while close > SMA200; exit when close <= SMA200."""

    strategy_id: str = "sma200-long-cash"
    version: int = 1
    candidate_id: str = "C1"
    regime_period: int = 200

    def describe(self) -> dict[str, object]:
        return asdict(self)

    @property
    def content_sha256(self) -> str:
        return _digest(self.describe())

    def signals(self, candles: tuple[Candle, ...]) -> StrategySignals:
        closes = [item.close for item in candles]
        base = sma(closes, self.regime_period)
        enter = [b is not None and c > b for c, b in zip(closes, base)]
        leave = [b is not None and c <= b for c, b in zip(closes, base)]
        return _stopless(enter, leave, self.regime_period - 1)


@dataclass(frozen=True, slots=True)
class EmaCross1d:
    """C2: enter when EMA20 crosses above EMA50; exit when it crosses below."""

    strategy_id: str = "ema-cross-1d"
    version: int = 1
    candidate_id: str = "C2"
    fast_period: int = 20
    slow_period: int = 50

    def describe(self) -> dict[str, object]:
        return asdict(self)

    @property
    def content_sha256(self) -> str:
        return _digest(self.describe())

    def signals(self, candles: tuple[Candle, ...]) -> StrategySignals:
        closes = [item.close for item in candles]
        fast = ema(closes, self.fast_period)
        slow = ema(closes, self.slow_period)
        enter: list[bool] = []
        leave: list[bool] = []
        for index in range(len(candles)):
            pair = (fast[index], slow[index])
            prior = (fast[index - 1], slow[index - 1]) if index > 0 else (None, None)
            if None in pair or None in prior:
                enter.append(False)
                leave.append(False)
                continue
            now_f, now_s = pair
            was_f, was_s = prior
            assert now_f is not None and now_s is not None
            assert was_f is not None and was_s is not None
            enter.append(was_f <= was_s and now_f > now_s)
            leave.append(was_f >= was_s and now_f < now_s)
        return _stopless(enter, leave, self.slow_period)


@dataclass(frozen=True, slots=True)
class Donchian2010:
    """C3: enter when close > prior 20-day highest high; exit when close <
    prior 10-day lowest low."""

    strategy_id: str = "donchian-20-10"
    version: int = 1
    candidate_id: str = "C3"
    entry_period: int = 20
    exit_period: int = 10

    def describe(self) -> dict[str, object]:
        return asdict(self)

    @property
    def content_sha256(self) -> str:
        return _digest(self.describe())

    def signals(self, candles: tuple[Candle, ...]) -> StrategySignals:
        upper = prior_highest_high(candles, self.entry_period)
        lower = prior_lowest_low(candles, self.exit_period)
        enter = [u is not None and c.close > u for c, u in zip(candles, upper)]
        leave = [d is not None and c.close < d for c, d in zip(candles, lower)]
        return _stopless(enter, leave, max(self.entry_period, self.exit_period))


@dataclass(frozen=True, slots=True)
class TimeSeriesMomentum:
    """C4 / C5: long while close / close(t - lookback) - 1 > 0; exit when <= 0."""

    strategy_id: str = "tsmom-28d"
    version: int = 1
    candidate_id: str = "C4"
    lookback: int = 28

    def describe(self) -> dict[str, object]:
        return asdict(self)

    @property
    def content_sha256(self) -> str:
        return _digest(self.describe())

    def signals(self, candles: tuple[Candle, ...]) -> StrategySignals:
        closes = [item.close for item in candles]
        n = self.lookback
        momentum = [
            None if index < n else closes[index] / closes[index - n] - Decimal(1)
            for index in range(len(closes))
        ]
        enter = [m is not None and m > 0 for m in momentum]
        leave = [m is not None and m <= 0 for m in momentum]
        return _stopless(enter, leave, n)


@dataclass(frozen=True, slots=True)
class Rsi2Uptrend:
    """C6: enter when RSI2 (Wilder) < 10 AND close > SMA200; exit when close >
    SMA5, or after 10 held bars."""

    strategy_id: str = "rsi2-uptrend"
    version: int = 1
    candidate_id: str = "C6"
    rsi_period: int = 2
    rsi_below: Decimal = Decimal("10")
    regime_period: int = 200
    exit_period: int = 5
    max_bars_held: int = 10

    def describe(self) -> dict[str, object]:
        payload = asdict(self)
        payload["rsi_below"] = str(self.rsi_below)
        return payload

    @property
    def content_sha256(self) -> str:
        return _digest(self.describe())

    def signals(self, candles: tuple[Candle, ...]) -> StrategySignals:
        closes = [item.close for item in candles]
        rsi = rsi_wilder(closes, self.rsi_period)
        base = sma(closes, self.regime_period)
        fast = sma(closes, self.exit_period)
        enter = [
            r is not None and b is not None and r < self.rsi_below and c > b
            for c, r, b in zip(closes, rsi, base)
        ]
        leave = [f is not None and c > f for c, f in zip(closes, fast)]
        first = max(self.regime_period - 1, self.rsi_period, self.exit_period - 1)
        return _stopless(enter, leave, first, max_bars_held=self.max_bars_held)


@dataclass(frozen=True, slots=True)
class BbReversion1d:
    """C7: enter when close < lower Bollinger (20, 2 sigma population); exit
    when close >= middle band, or after 20 held bars; fixed stop entry fill
    minus 2 x ATR14 known at the signal close (gap through -> open)."""

    strategy_id: str = "bb-reversion-1d"
    version: int = 1
    candidate_id: str = "C7"
    band_period: int = 20
    atr_period: int = 14
    stop_atr_multiple: Decimal = Decimal("2")
    max_bars_held: int = 20

    def describe(self) -> dict[str, object]:
        payload = asdict(self)
        payload["stop_atr_multiple"] = str(self.stop_atr_multiple)
        return payload

    @property
    def content_sha256(self) -> str:
        return _digest(self.describe())

    def signals(self, candles: tuple[Candle, ...]) -> StrategySignals:
        closes = [item.close for item in candles]
        bands = bollinger(closes, self.band_period)
        atr = atr_wilder(candles, self.atr_period)
        enter: list[bool] = []
        leave: list[bool] = []
        stops: list[Decimal | None] = []
        for close, band, current_atr in zip(closes, bands, atr):
            enter.append(
                band is not None
                and current_atr is not None
                and current_atr > 0
                and close < band[2]
            )
            leave.append(band is not None and close >= band[0])
            stops.append(
                None if current_atr is None else current_atr * self.stop_atr_multiple
            )
        return StrategySignals(
            tuple(enter),
            tuple(leave),
            tuple(stops),
            max(self.band_period - 1, self.atr_period),
            max_bars_held=self.max_bars_held,
        )


@dataclass(frozen=True, slots=True)
class Sma200VolTarget:
    """C8: C1's signal; invested fraction = min(1, 0.40 / annualised 20-day
    realised volatility of daily close-to-close log returns x sqrt(365)), set
    at the signal close and held for the trade; the rest stays in cash."""

    strategy_id: str = "sma200-voltarget"
    version: int = 1
    candidate_id: str = "C8"
    regime_period: int = 200
    vol_period: int = 20
    target_volatility: Decimal = Decimal("0.40")
    periods_per_year: int = 365

    def describe(self) -> dict[str, object]:
        payload = asdict(self)
        payload["target_volatility"] = str(self.target_volatility)
        return payload

    @property
    def content_sha256(self) -> str:
        return _digest(self.describe())

    def fractions(self, candles: tuple[Candle, ...]) -> list[Decimal | None]:
        closes = [item.close for item in candles]
        vol = realised_volatility(closes, self.vol_period, self.periods_per_year)
        return [
            None
            if v is None
            else Decimal(1)
            if v == 0
            else min(Decimal(1), self.target_volatility / v)
            for v in vol
        ]

    def signals(self, candles: tuple[Candle, ...]) -> StrategySignals:
        base = Sma200LongCash(regime_period=self.regime_period).signals(candles)
        fraction = self.fractions(candles)
        enter = [e and f is not None for e, f in zip(base.enter_long, fraction)]
        return _stopless(
            enter,
            list(base.exit_long),
            max(self.regime_period - 1, self.vol_period),
            position_fraction=tuple(fraction),
        )


TournamentCandidate = (
    Sma200LongCash
    | EmaCross1d
    | Donchian2010
    | TimeSeriesMomentum
    | Rsi2Uptrend
    | BbReversion1d
    | Sma200VolTarget
    | TrendDailyRegime
)

# k = 9 for the Bonferroni correction. Order is the pre-registered C1..C9.
TOURNAMENT_CANDIDATES: tuple[tuple[str, TournamentCandidate], ...] = (
    ("C1", Sma200LongCash()),
    ("C2", EmaCross1d()),
    ("C3", Donchian2010()),
    ("C4", TimeSeriesMomentum()),
    ("C5", TimeSeriesMomentum(strategy_id="tsmom-84d", candidate_id="C5", lookback=84)),
    ("C6", Rsi2Uptrend()),
    ("C7", BbReversion1d()),
    ("C8", Sma200VolTarget()),
    ("C9", TrendDailyRegime()),
)
