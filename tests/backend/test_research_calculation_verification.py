"""E2d calculation verification for the lean research lane.

All candles here are SYNTHETIC test fixtures, not market data.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from test_moving_averages import evidence
from trading_platform_api.analysis.moving_averages import (
    MovingAverageKind,
    calculate_moving_average,
)
from trading_platform_api.analysis.volatility import calculate_atr14
from trading_platform_api.market_data.contracts import MetricValue
from trading_platform_api.research.backtest import CostAssumptions, run_segment
from trading_platform_api.research.candles import Candle
from trading_platform_api.research.indicators import atr_wilder, ema
from trading_platform_api.research.strategy import StrategySignals

T0 = datetime(2026, 1, 1, tzinfo=UTC)


def synthetic_ohlc(count: int) -> list[tuple[Decimal, Decimal, Decimal, Decimal]]:
    """SYNTHETIC deterministic OHLC path with gaps, trends and uneven ranges."""
    rows = []
    close = Decimal("100")
    for index in range(count):
        open_ = close + Decimal((index * 7) % 5 - 2) / 4
        close = open_ + Decimal((index * 13) % 11 - 5) / 3
        high = max(open_, close) + Decimal((index * 3) % 4 + 1) / 5
        low = min(open_, close) - Decimal((index * 5) % 3 + 1) / 7
        rows.append((open_, high, low, close))
    return rows


def test_research_indicators_equal_registered_platform_calculators() -> None:
    rows = synthetic_ohlc(160)
    snapshot, observations, quality = evidence(tuple(str(row[3]) for row in rows))
    observations = tuple(
        replace(
            item,
            metrics=(
                MetricValue("open", row[0], "USDT"),
                MetricValue("high", row[1], "USDT"),
                MetricValue("low", row[2], "USDT"),
                MetricValue("close", row[3], "USDT"),
                MetricValue("volume", Decimal(1), "BTC"),
            ),
        )
        for item, row in zip(observations, rows, strict=True)
    )
    candles = [
        Candle(T0 + index * timedelta(minutes=1), *row, Decimal(1))
        for index, row in enumerate(rows)
    ]
    closes = [row[3] for row in rows]
    for period in (20, 50):
        platform = calculate_moving_average(
            snapshot=snapshot,
            observations=observations,
            quality=quality,
            kind=MovingAverageKind.EMA,
            period=period,
            timeframe="1m",
        )
        assert ema(closes, period) == [point.value for point in platform.points]
    platform_atr = calculate_atr14(
        snapshot=snapshot, observations=observations, quality=quality, timeframe="1m"
    )
    research_atr = atr_wilder(candles, 14)
    assert research_atr == [point.value for point in platform_atr.points]
    # The path is non-trivial: true ranges vary, so ATR is not constant.
    assert len({value for value in research_atr if value is not None}) > 50


def _candle(index: int, o: str, h: str, low: str, c: str) -> Candle:
    return Candle(
        T0 + index * timedelta(hours=4),
        Decimal(o),
        Decimal(h),
        Decimal(low),
        Decimal(c),
        Decimal(1),
    )


def test_backtest_golden_trades_hand_computed() -> None:
    # SYNTHETIC 8-bar series. Signals are given directly (ATR = 2, so the
    # 2xATR stop distance is 4) to isolate the execution arithmetic.
    candles = (
        _candle(0, "100", "101", "99", "100"),  # BUY signal
        _candle(1, "100", "103", "99", "102"),  # entry at open
        _candle(2, "102", "104", "101", "103"),  # SELL signal
        _candle(3, "104", "105", "99", "100"),  # exit at open; BUY signal
        _candle(4, "100", "100", "99", "98"),  # entry at open
        _candle(5, "95", "96", "94", "95"),  # gaps through stop 96.05
        _candle(6, "100", "101", "99", "100"),  # BUY signal
        _candle(7, "100", "101", "96", "97"),  # entry, stop hit same bar
    )
    enter = (True, False, False, True, False, False, True, False)
    leave = (False, False, True, False, False, False, False, False)
    signals = StrategySignals(enter, leave, (Decimal(4),) * 8, 0)
    costs = CostAssumptions(Decimal("10"), Decimal("5"))
    result = run_segment(candles, signals, costs, start=0, end=8)

    first, second, third = result.trades
    # Entry fill = open x (1 + 0.0005); stop = fill - 4.
    for trade in result.trades:
        assert trade.entry_price == Decimal("100.0500")
        assert trade.stop_price == Decimal("96.0500")
    assert [t.entry_time for t in result.trades] == [
        candles[1].open_time,
        candles[4].open_time,
        candles[7].open_time,
    ]
    # Trade 1: signal exit at bar 3 open 104 -> fill 104 x 0.9995 = 103.948.
    assert (first.exit_reason, first.exit_price) == ("SIGNAL_EXIT", Decimal("103.948"))
    assert first.gross_return == Decimal("0.04")
    # Net = 0.999 fee in x 103.948 / 100.05 x 0.999 fee out - 1.
    assert round(first.net_return, 10) == Decimal("0.0368836377")
    assert first.bars_held == 3
    # Trade 2: bar 5 opens at 95, below the 96.05 stop -> fills at the open.
    assert (second.exit_reason, second.exit_price) == ("STOP", Decimal("94.9525"))
    assert second.gross_return == Decimal("-0.05")
    assert round(second.net_return, 10) == Decimal("-0.0528466771")
    # Trade 3: entry bar's low 96 touches the stop -> fills at 96.05 less slippage.
    assert (third.exit_reason, third.exit_price) == ("STOP", Decimal("96.001975"))
    assert third.gross_return == Decimal("-0.0395")
    assert round(third.net_return, 10) == Decimal("-0.0423781404")
    assert third.bars_held == 1
    # R multiple: loss / (units x 4); a stop-out costs slightly more than 1R.
    assert round(third.r_multiple, 10) == Decimal("-1.0610442813")
    # Final equity compounds the three trades (100.05 entry, 0.999 fee twice).
    assert round(result.equity[-1], 10) == Decimal("0.9404687289")
    assert result.bars_in_market == 3
