"""Focused tests for range-reversion-4h v1 and its indicators (E2f, #516).

All candle data here is SYNTHETIC and exists only to exercise deterministic
behaviour; none of it represents real market history or real results.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from test_moving_averages import evidence
from trading_platform_api.analysis.momentum import calculate_rsi
from trading_platform_api.analysis.volatility import calculate_bollinger_bands
from trading_platform_api.market_data.contracts import MetricValue
from trading_platform_api.research.__main__ import main
from trading_platform_api.research.backtest import CostAssumptions, run_segment
from trading_platform_api.research.candles import (
    Candle,
    format_candle_csv,
    parse_candle_csv,
)
from trading_platform_api.research.evaluation import WalkForwardProtocol
from trading_platform_api.research.indicators import (
    adx_wilder,
    atr_wilder,
    bollinger,
    rsi_wilder,
)
from trading_platform_api.research.report import StudyError
from trading_platform_api.research.strategy import RangeReversion4h, StrategySignals
from trading_platform_api.research.walk_forward import run_walk_forward_study

ERA = datetime(2021, 9, 30, tzinfo=UTC)
STEP = timedelta(hours=4)
STEP_MS = 14_400_000
NO_COSTS = CostAssumptions(Decimal("0"), Decimal("0"), "synthetic zero-cost test")


def _bar(index: int, o: str, h: str, low: str, c: str) -> Candle:
    return Candle(
        ERA + index * STEP, Decimal(o), Decimal(h), Decimal(low), Decimal(c), Decimal(1)
    )


def ranging(count: int) -> list[Candle]:
    """SYNTHETIC 4h range: a slow oscillation with periodic sharp dips."""
    candles = []
    previous = Decimal(100)
    for index in range(count):
        wave = Decimal((index * 7) % 24 - 12) / 8
        phase = index % 47
        dip = Decimal(-2 * (phase - 35)) if 36 <= phase <= 41 else Decimal(0)
        close = Decimal(100) + wave + dip
        high = max(previous, close) + Decimal((index * 3) % 4 + 1) / 5
        low = min(previous, close) - Decimal((index * 5) % 3 + 1) / 5
        candles.append(Candle(ERA + STEP * index, previous, high, low, close, 1))
        previous = close
    return candles


def test_parameters_match_the_preregistration() -> None:
    assert RangeReversion4h().describe() == {
        "strategy_id": "range-reversion-4h",
        "version": 1,
        "band_period": 20,
        "rsi_period": 14,
        "adx_period": 14,
        "atr_period": 14,
        "adx_below": "20",
        "rsi_below": "30",
        "stop_atr_multiple": "1.5",
        "max_bars_held": 12,
    }


def test_rsi_and_bollinger_equal_registered_platform_methods() -> None:
    candles = ranging(160)
    closes = tuple(str(item.close) for item in candles)
    snapshot, observations, quality = evidence(closes)
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
    values = [item.close for item in candles]
    platform_rsi = calculate_rsi(
        snapshot=snapshot,
        observations=observations,
        quality=quality,
        period=14,
        timeframe="1m",
    )
    assert rsi_wilder(values, 14) == [p.value.value for p in platform_rsi.points]
    platform_bands = calculate_bollinger_bands(
        snapshot=snapshot,
        observations=observations,
        quality=quality,
        period=20,
        timeframe="1m",
    )
    assert bollinger(values, 20) == [
        None if p.middle is None else (p.middle, p.upper, p.lower)
        for p in platform_bands.points
    ]


def test_adx_hand_computed_with_period_two() -> None:
    candles = [
        _bar(0, "9", "10", "8", "9"),
        _bar(1, "9", "12", "9", "11"),
        _bar(2, "11", "11", "7", "8"),
        _bar(3, "8", "13", "8", "12"),
        _bar(4, "12", "14", "11", "13"),
    ]
    # +DM: 2,0,2,1  -DM: 0,2,0,0  TR: 3,4,5,3.
    # DX at candle 2 = 0, candle 3 = 50 -> ADX(3) = 25;
    # DX at candle 4 = 100 x 1.0 / 1.5 -> ADX(4) = (25 + 66.67) / 2 = 275/6.
    values = adx_wilder(candles, 2)
    assert values[:3] == [None, None, None]
    assert values[3] == Decimal(25)
    assert values[4] is not None
    assert abs(values[4] - Decimal(275) / Decimal(6)) < Decimal("1e-25")


def test_entry_exit_and_stop_follow_the_preregistered_rules() -> None:
    candles = tuple(ranging(400))
    strategy = RangeReversion4h()
    signals = strategy.signals(candles)
    closes = [item.close for item in candles]
    bands = bollinger(closes, 20)
    rsi = rsi_wilder(closes, 14)
    adx = adx_wilder(candles, 14)
    atr = atr_wilder(candles, 14)
    assert signals.first_tradable_index == 27
    assert signals.max_bars_held == 12
    assert any(signals.enter_long), "synthetic dips must trigger entries"
    for index, close in enumerate(closes):
        band, strength, trend = bands[index], rsi[index], adx[index]
        if band is None or strength is None or trend is None:
            assert not signals.enter_long[index]
            continue
        expected = trend < 20 and close < band[2] and strength < 30
        assert signals.enter_long[index] == expected
        assert signals.exit_long[index] == (close >= band[0])
        value = atr[index]
        assert value is not None
        assert signals.stop_distance[index] == value * Decimal("1.5")


def test_time_stop_exits_at_the_next_open_after_twelve_held_bars() -> None:
    # SYNTHETIC flat series: entry signal at bar 0, no exit signal, no stop hit.
    candles = tuple(_bar(i, "100", "101", "99", "100") for i in range(20))
    flat = (False,) * 20
    signals = StrategySignals(
        enter_long=(True,) + flat[1:],
        exit_long=flat,
        stop_distance=(Decimal(5),) * 20,
        first_tradable_index=0,
        max_bars_held=12,
    )
    result = run_segment(candles, signals, NO_COSTS, start=0, end=20)
    (trade,) = result.trades
    # Entry at bar 1's open; held bars 1..12; exit at bar 13's open.
    assert trade.entry_time == candles[1].open_time
    assert trade.exit_time == candles[13].open_time
    assert trade.exit_reason == "TIME_EXIT"
    assert trade.bars_held == 13
    # A signal exit on the same close keeps SIGNAL_EXIT.
    both = replace(signals, exit_long=flat[:12] + (True,) + flat[13:])
    (trade,) = run_segment(candles, both, NO_COSTS, start=0, end=20).trades
    assert (trade.exit_time, trade.exit_reason) == (
        candles[13].open_time,
        "SIGNAL_EXIT",
    )
    # Without a time stop the position runs to the end of the segment.
    (trade,) = run_segment(
        candles, replace(signals, max_bars_held=None), NO_COSTS, start=0, end=20
    ).trades
    assert trade.exit_reason == "END_OF_SEGMENT"


def _csv(symbol: str, count: int, timeframe: str = "4h") -> str:
    step = STEP_MS if timeframe == "4h" else 86_400_000
    base = int(ERA.timestamp() * 1000)
    rows = [
        (
            base + index * step,
            str(bar.open),
            str(bar.high),
            str(bar.low),
            str(bar.close),
            "1",
            base + (index + 1) * step - 1,
        )
        for index, bar in enumerate(ranging(count))
    ]
    return format_candle_csv(
        source="synthetic-test",
        symbol=symbol,
        timeframe=timeframe,
        fetched_at=ERA + timedelta(milliseconds=step * (count + 1)),
        rows=rows,
    )


def test_walk_forward_study_runs_strategy_b_on_4h_only() -> None:
    # 2021-09-30 .. 2025-05-13: covers the development era and a few seen bars.
    count = int((datetime(2025, 5, 13, tzinfo=UTC) - ERA) / STEP)
    series = [parse_candle_csv(_csv("BTCUSDT", count))]
    created = datetime(2026, 11, 26, tzinfo=UTC)
    protocol = WalkForwardProtocol(bootstrap_resamples=50)
    strategy = RangeReversion4h()
    report = run_walk_forward_study(
        series, strategy=strategy, protocol=protocol, created_at=created
    )
    assert report == run_walk_forward_study(
        series, strategy=strategy, protocol=protocol, created_at=created
    )
    assert report["strategy"]["strategy_id"] == "range-reversion-4h"
    assert report["verdict"]["status"] in {"HISTORICAL_PASS", "FAIL", "INCONCLUSIVE"}
    assert report["periods"]["development_end"] == "2025-05-11T20:00:00Z"
    reasons = {
        trade["exit_reason"]
        for trade in report["per_symbol"]["BTCUSDT"]["development_era_trades"]
    }
    assert reasons <= {"SIGNAL_EXIT", "TIME_EXIT", "STOP", "END_OF_SEGMENT"}
    daily = [parse_candle_csv(_csv("BTCUSDT", 1400, "1d"))]
    with pytest.raises(StudyError, match="pre-registered for 4h only"):
        run_walk_forward_study(daily, strategy=strategy)


def test_cli_accepts_strategy_b_only_on_4h(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    out = ["--data", str(tmp_path), "--out", str(tmp_path / "out")]
    code = main(
        ["run", "--strategy", "range-reversion-4h", "--protocol", "v2"]
        + ["--timeframe", "1d", *out]
    )
    assert code == 2 and "pre-registered for 4h" in capsys.readouterr().err
    code = main(["run", "--strategy", "range-reversion-4h", "--protocol", "v1", *out])
    assert code == 2 and "not pre-registered" in capsys.readouterr().err
    code = main(["run", "--strategy", "range-reversion-4h", "--protocol", "v2", *out])
    assert code == 2 and "fail closed" in capsys.readouterr().err  # no data files
