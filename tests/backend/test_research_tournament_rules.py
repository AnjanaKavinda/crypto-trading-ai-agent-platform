"""Tournament v1 candidate rules and indicators (E2t part 1, #516).

All candles here are SYNTHETIC, labelled test fixtures, never market data.
Rules follow the pre-registration in #516 comment 7203109547 exactly.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from test_moving_averages import evidence
from trading_platform_api.analysis.momentum import calculate_rsi
from trading_platform_api.analysis.moving_averages import (
    MovingAverageKind,
    calculate_moving_average,
)
from trading_platform_api.analysis.volatility import calculate_realized_volatility
from trading_platform_api.market_data.contracts import MetricValue
from trading_platform_api.research.backtest import CostAssumptions, run_segment
from trading_platform_api.research.candles import Candle
from trading_platform_api.research.indicators import (
    atr_wilder,
    bollinger,
    ema,
    prior_highest_high,
    prior_lowest_low,
    realised_volatility,
    rsi_wilder,
    sma,
)
from trading_platform_api.research.strategy import (
    TOURNAMENT_CANDIDATES,
    BbReversion1d,
    Donchian2010,
    EmaCross1d,
    Rsi2Uptrend,
    Sma200LongCash,
    Sma200VolTarget,
    StrategySignals,
    TimeSeriesMomentum,
    TrendDailyRegime,
)

ERA = datetime(2021, 9, 30, tzinfo=UTC)
DAY = timedelta(days=1)
NO_COSTS = CostAssumptions(Decimal("0"), Decimal("0"), "synthetic zero-cost test")


def _bar(index: int, o: str, h: str, low: str, c: str) -> Candle:
    return Candle(
        ERA + index * DAY, Decimal(o), Decimal(h), Decimal(low), Decimal(c), Decimal(1)
    )


def wavy(count: int) -> tuple[Candle, ...]:
    """SYNTHETIC daily series: slow up/down cycles with sharp periodic dips."""
    candles = []
    previous = Decimal(100)
    for index in range(count):
        cycle = Decimal((index % 160) - 80 if index % 320 < 160 else 80 - index % 160)
        dip = Decimal(-6) if index % 37 in (30, 31) else Decimal(0)
        close = Decimal(100) + cycle / 4 + Decimal((index * 7) % 11 - 5) / 3 + dip
        high = max(previous, close) + Decimal((index * 3) % 4 + 1) / 4
        low = min(previous, close) - Decimal((index * 5) % 3 + 1) / 4
        candles.append(Candle(ERA + DAY * index, previous, high, low, close, 1))
        previous = close
    return tuple(candles)


def test_candidates_match_the_preregistration() -> None:
    ids = [(cid, c.strategy_id, c.version) for cid, c in TOURNAMENT_CANDIDATES]
    assert ids == [
        ("C1", "sma200-long-cash", 1),
        ("C2", "ema-cross-1d", 1),
        ("C3", "donchian-20-10", 1),
        ("C4", "tsmom-28d", 1),
        ("C5", "tsmom-84d", 1),
        ("C6", "rsi2-uptrend", 1),
        ("C7", "bb-reversion-1d", 1),
        ("C8", "sma200-voltarget", 1),
        ("C9", "trend-daily-regime", 1),
    ]
    by_id = dict(TOURNAMENT_CANDIDATES)
    assert by_id["C5"].describe()["lookback"] == 84
    assert by_id["C6"].describe() == {
        "strategy_id": "rsi2-uptrend",
        "version": 1,
        "candidate_id": "C6",
        "rsi_period": 2,
        "rsi_below": "10",
        "regime_period": 200,
        "exit_period": 5,
        "max_bars_held": 10,
    }
    assert by_id["C7"].describe()["stop_atr_multiple"] == "2"
    assert by_id["C8"].describe()["target_volatility"] == "0.40"
    # C9 is Strategy A unchanged: same digest as the protocol v2 study.
    assert by_id["C9"].content_sha256 == TrendDailyRegime().content_sha256
    assert len({c.content_sha256 for _, c in TOURNAMENT_CANDIDATES}) == 9


def test_rsi2_sma_and_realised_volatility_equal_platform_methods() -> None:
    candles = wavy(120)
    snapshot, observations, quality = evidence(tuple(str(c.close) for c in candles))
    observations = tuple(
        replace(
            item,
            metrics=(
                MetricValue("open", bar.open, "USDT"),
                MetricValue("high", bar.high, "USDT"),
                MetricValue("low", bar.low, "USDT"),
                MetricValue("close", bar.close, "USDT"),
                MetricValue("volume", Decimal(1), "BTC"),
            ),
        )
        for item, bar in zip(observations, candles, strict=True)
    )
    closes = [c.close for c in candles]
    rsi = calculate_rsi(
        snapshot=snapshot,
        observations=observations,
        quality=quality,
        period=2,
        timeframe="1m",
    )
    assert rsi_wilder(closes, 2) == [p.value.value for p in rsi.points]
    for period in (5, 20):
        platform = calculate_moving_average(
            snapshot=snapshot,
            observations=observations,
            quality=quality,
            kind=MovingAverageKind.SMA,
            period=period,
            timeframe="1m",
        )
        assert sma(closes, period) == [p.value for p in platform.points]
    vol = calculate_realized_volatility(
        snapshot=snapshot,
        observations=observations,
        quality=quality,
        period=20,
        timeframe="1m",
    )
    # Same arithmetic; the 1m annualiser is the only timeframe difference.
    assert realised_volatility(closes, 20, 525_600) == [p.value for p in vol.points]


def test_donchian_and_realised_volatility_hand_computed() -> None:
    candles = [
        _bar(0, "10", "12", "9", "11"),
        _bar(1, "11", "15", "10", "14"),
        _bar(2, "14", "14", "8", "9"),
        _bar(3, "9", "13", "9", "12"),
    ]
    assert prior_highest_high(candles, 2) == [None, None, Decimal(15), Decimal(15)]
    assert prior_lowest_low(candles, 2) == [None, None, Decimal(9), Decimal(8)]
    # Returns ln(2), 0 -> sample stdev = ln(2)/sqrt(2); annualiser sqrt(1).
    vol = realised_volatility([Decimal(1), Decimal(2), Decimal(2)], 2, 1)
    assert vol[:2] == [None, None]
    assert vol[2] is not None
    expected = Decimal(2).ln() / Decimal(2).sqrt()
    assert abs(vol[2] - expected) < Decimal("1e-25")


def test_each_rule_matches_its_preregistered_formula() -> None:
    candles = wavy(700)
    closes = [c.close for c in candles]
    s200, s5 = sma(closes, 200), sma(closes, 5)
    e20, e50 = ema(closes, 20), ema(closes, 50)
    upper, lower = prior_highest_high(candles, 20), prior_lowest_low(candles, 10)
    rsi2, bands, atr = rsi_wilder(closes, 2), bollinger(closes, 20), atr_wilder(candles)
    n = len(candles)

    c1 = Sma200LongCash().signals(candles)
    assert c1.stopless and c1.first_tradable_index == 199
    for i in range(n):
        b = s200[i]
        assert c1.enter_long[i] == (b is not None and closes[i] > b)
        assert c1.exit_long[i] == (b is not None and closes[i] <= b)

    c2 = EmaCross1d().signals(candles)
    assert c2.stopless and c2.first_tradable_index == 50
    for i in range(50, n):
        f0, s0, f1, s1 = e20[i - 1], e50[i - 1], e20[i], e50[i]
        assert f0 and s0 and f1 and s1
        assert c2.enter_long[i] == (f0 <= s0 and f1 > s1)
        assert c2.exit_long[i] == (f0 >= s0 and f1 < s1)
    assert not any(c2.enter_long[:50])

    c3 = Donchian2010().signals(candles)
    assert c3.stopless and c3.first_tradable_index == 20
    for i in range(20, n):
        high, low = upper[i], lower[i]
        assert high is not None and low is not None
        assert c3.enter_long[i] == (closes[i] > high)
        assert c3.exit_long[i] == (closes[i] < low)

    for lookback, strategy in (
        (28, TimeSeriesMomentum()),
        (84, dict(TOURNAMENT_CANDIDATES)["C5"]),
    ):
        signals = strategy.signals(candles)
        assert signals.stopless and signals.first_tradable_index == lookback
        assert not any(signals.enter_long[:lookback])
        for i in range(lookback, n):
            up = closes[i] / closes[i - lookback] - 1 > 0
            assert (signals.enter_long[i], signals.exit_long[i]) == (up, not up)

    c6 = Rsi2Uptrend().signals(candles)
    assert c6.stopless and c6.max_bars_held == 10 and c6.first_tradable_index == 199
    for i in range(n):
        r, b, f = rsi2[i], s200[i], s5[i]
        assert c6.enter_long[i] == (
            r is not None and b is not None and r < 10 and closes[i] > b
        )
        assert c6.exit_long[i] == (f is not None and closes[i] > f)
    assert any(c6.enter_long), "synthetic dips in an uptrend must trigger C6"

    c7 = BbReversion1d().signals(candles)
    assert not c7.stopless and c7.max_bars_held == 20
    assert c7.first_tradable_index == 19
    for i in range(n):
        band, a = bands[i], atr[i]
        assert c7.enter_long[i] == (
            band is not None and a is not None and a > 0 and closes[i] < band[2]
        )
        assert c7.exit_long[i] == (band is not None and closes[i] >= band[0])
        assert c7.stop_distance[i] == (None if a is None else a * 2)
    assert any(c7.enter_long)

    c8 = Sma200VolTarget().signals(candles)
    assert c8.stopless and c8.first_tradable_index == 199
    assert (c8.enter_long, c8.exit_long) == (c1.enter_long, c1.exit_long)
    assert c8.position_fraction is not None
    vol = realised_volatility(closes, 20)
    for i in range(20, n):
        v = vol[i]
        assert v is not None and v > 0
        assert c8.position_fraction[i] == min(Decimal(1), Decimal("0.40") / v)


def test_stopless_candidate_holds_through_a_crash_and_exits_on_signal() -> None:
    # SYNTHETIC: entry at bar 1, a crash bar 3 (low 1), exit signal at close 4.
    candles = tuple(
        _bar(i, o, h, low, c)
        for i, (o, h, low, c) in enumerate(
            [
                ("100", "101", "99", "100"),
                ("100", "101", "99", "100"),
                ("100", "101", "99", "100"),
                ("100", "100", "1", "50"),
                ("50", "60", "40", "55"),
                ("55", "56", "54", "55"),
            ]
        )
    )
    flat = (False,) * 6
    signals = StrategySignals(
        enter_long=(True,) + flat[1:],
        exit_long=flat[:4] + (True, False),
        stop_distance=(None,) * 6,
        first_tradable_index=0,
        stopless=True,
    )
    (trade,) = run_segment(candles, signals, NO_COSTS, start=0, end=6).trades
    assert trade.exit_reason == "SIGNAL_EXIT"
    assert (trade.entry_time, trade.exit_time) == (
        candles[1].open_time,
        candles[5].open_time,
    )
    assert trade.stop_price == 0
    assert trade.net_return == Decimal("-0.45")
    assert trade.r_multiple == Decimal("-0.45")


def test_c8_fractional_position_keeps_the_rest_in_cash() -> None:
    # SYNTHETIC: fraction 0.25 at the signal close; price doubles; exit at 200.
    candles = (
        _bar(0, "100", "101", "99", "100"),
        _bar(1, "100", "201", "99", "200"),
        _bar(2, "200", "201", "199", "200"),
    )
    signals = StrategySignals(
        enter_long=(True, False, False),
        exit_long=(False, True, False),
        stop_distance=(None,) * 3,
        first_tradable_index=0,
        stopless=True,
        position_fraction=(Decimal("0.25"), None, None),
    )
    result = run_segment(candles, signals, NO_COSTS, start=0, end=3)
    (trade,) = result.trades
    # 0.25 invested doubles -> 0.5, plus 0.75 cash = 1.25 of equity.
    assert result.equity == (Decimal(1), Decimal("1.25"), Decimal("1.25"))
    assert trade.net_return == Decimal("0.25")
    # With costs the fee applies to the invested part only.
    costs = CostAssumptions(Decimal("10"), Decimal("0"), "synthetic 10 bps fee")
    (trade,) = run_segment(candles, signals, costs, start=0, end=3).trades
    invested = Decimal("0.25") * Decimal("0.999") / 100 * 200 * Decimal("0.999")
    assert trade.net_return == invested + Decimal("0.75") - 1


def test_c7_stop_gap_fills_at_the_open() -> None:
    # SYNTHETIC: stop distance 2 -> stop 98; bar 2 opens at 90 below the stop.
    candles = (
        _bar(0, "100", "101", "99", "100"),
        _bar(1, "100", "101", "99", "100"),
        _bar(2, "90", "91", "85", "88"),
        _bar(3, "88", "89", "87", "88"),
    )
    signals = StrategySignals(
        enter_long=(True, False, False, False),
        exit_long=(False,) * 4,
        stop_distance=(Decimal(2),) * 4,
        first_tradable_index=0,
        max_bars_held=20,
    )
    (trade,) = run_segment(candles, signals, NO_COSTS, start=0, end=4).trades
    assert (trade.exit_reason, trade.exit_price) == ("STOP", Decimal(90))
    assert trade.stop_price == Decimal(98)
