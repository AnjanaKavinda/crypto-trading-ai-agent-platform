"""Focused tests for trend-daily-regime v1 strategy markers (E2e part 2, #548).

All candle data here is SYNTHETIC and exists only to exercise deterministic
behaviour; none of it represents real market history or real results.
"""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from trading_platform_api.research.backtest import CostAssumptions, run_segment
from trading_platform_api.research.candles import Candle
from trading_platform_api.research.indicators import atr_wilder, ema, sma
from trading_platform_api.research.markers import (
    build_strategy_markers,
    registered_marker_strategy,
    stop_in_effect,
)
from trading_platform_api.research.strategy import EmaTrendAtrStop, TrendDailyRegime

START = datetime(2022, 1, 1, tzinfo=UTC)
STEP = timedelta(days=1)


def synthetic_daily(length: int = 500) -> tuple[Candle, ...]:
    """SYNTHETIC daily series: long up legs, sharp drops, then recoveries."""
    candles = []
    price = Decimal("100")
    previous = price
    for index in range(length):
        leg = index % 90
        price += Decimal("1") if leg < 60 else Decimal("-1.6")
        price += Decimal("0.05")
        high = max(previous, price) * Decimal("1.01")
        low = min(previous, price) * Decimal("0.99")
        candles.append(
            Candle(START + STEP * index, previous, high, low, price, Decimal("1"))
        )
        previous = price
    return tuple(candles)


def served_indicators(candles: tuple[Candle, ...]) -> dict[str, object]:
    closes = [item.close for item in candles]

    def envelope(values: list[Decimal | None]) -> dict[str, object]:
        return {
            "status": "AVAILABLE",
            "reason_code": None,
            "result": {
                "points": [
                    {"value": None if value is None else str(value)} for value in values
                ]
            },
        }

    return {
        "ema-20": envelope(ema(closes, 20)),
        "ema-50": envelope(ema(closes, 50)),
        "atr-14": envelope(atr_wilder(candles, 14)),
    }


def markers(candles: tuple[Candle, ...], timeframe: str = "1d") -> dict:
    strategy, required = registered_marker_strategy("trend-daily-regime", 1)
    return build_strategy_markers(
        candles=candles,
        data_quality_status="VALID",
        indicators=served_indicators(candles),
        strategy=strategy,
        timeframe=timeframe,
        required_timeframe=required,
    )


def iso(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


def test_registry_is_fixed_and_fails_closed() -> None:
    strategy, required = registered_marker_strategy("trend-daily-regime", 1)
    assert isinstance(strategy, TrendDailyRegime) and required == "1d"
    default, any_timeframe = registered_marker_strategy("ema-trend-atr-stop", 1)
    assert isinstance(default, EmaTrendAtrStop) and any_timeframe is None
    for pair in (("trend-daily-regime", 2), ("range-reversion-4h", 1)):
        with pytest.raises(ValueError, match="no registered markers"):
            registered_marker_strategy(*pair)


def test_markers_match_the_trailing_stop_backtest() -> None:
    candles = synthetic_daily()
    result = markers(candles)
    assert result["status"] == "AVAILABLE"
    assert result["strategy"]["strategy_id"] == "trend-daily-regime"
    assert "trend-daily-regime v1" in result["evidence_scope"]
    strategy = TrendDailyRegime()
    signals = strategy.signals(candles)
    backtest = run_segment(
        candles,
        signals,
        CostAssumptions(),
        start=signals.first_tradable_index,
        end=len(candles),
    )
    assert backtest.trades
    filled = [item for item in result["markers"] if item["status"] == "FILLED"]
    buys = [item for item in filled if item["side"] == "BUY"]
    sells = [item for item in filled if item["side"] == "SELL"]
    assert [b["fill_time"]["value"] for b in buys] == [
        iso(t.entry_time) for t in backtest.trades
    ]
    closed = [t for t in backtest.trades if t.exit_reason != "END_OF_SEGMENT"]
    assert [(s["fill_time"]["value"], s["exit_reason"]) for s in sells] == [
        (iso(t.exit_time), t.exit_reason) for t in closed
    ]

    # BUY: the trend state turned on at the signal close, with SMA200 readout.
    closes = [item.close for item in candles]
    regime = sma(closes, 200)
    first = buys[0]
    index = [iso(c.open_time) for c in candles].index(first["time"]["value"])
    state = first["conditions"][0]
    assert state["sma_200"]["value"] == str(regime[index])
    assert first["indicators"]["sma_200"] == {
        "label": "VERIFIED_FACT",
        "value": str(regime[index]),
        "reason": None,
    }
    assert Decimal(state["close"]["value"]) > Decimal(state["sma_200"]["value"])
    assert Decimal(state["ema_20"]["value"]) > Decimal(state["ema_50"]["value"])
    previous_on = Decimal(state["previous_ema_20"]["value"]) > Decimal(
        state["previous_ema_50"]["value"]
    ) and Decimal(state["previous_close"]["value"]) > Decimal(
        state["previous_sma_200"]["value"]
    )
    assert not previous_on
    assert first["stop_distance"]["reason"] == "3 x ATR14 at signal close"


def test_stop_exit_reports_the_ratcheted_trailing_stop() -> None:
    candles = synthetic_daily()
    result = markers(candles)
    stops = [
        m
        for m in result["markers"]
        if m["side"] == "SELL" and m["exit_reason"] == "STOP"
    ]
    assert stops, "synthetic series must produce a trailing-stop exit"
    raised = 0
    for marker in stops:
        condition = marker["conditions"][0]
        stop = Decimal(condition["stop"]["value"])
        initial = Decimal(condition["initial_stop"]["value"])
        assert condition["stop"]["reason"] == "modelled trailing stop"
        assert stop >= initial
        assert Decimal(condition["low"]["value"]) <= stop
        raised += stop > initial
    assert raised, "at least one stop must have been raised above the initial stop"


def test_stop_in_effect_ratchets_and_is_never_lowered() -> None:
    # SYNTHETIC 4-bar position: closes 10, 12, 11, 13 with trail distance 2.
    closes = [Decimal(v) for v in ("10", "12", "11", "13")]
    candles = tuple(
        Candle(START + STEP * i, c, c, c, c, Decimal("1")) for i, c in enumerate(closes)
    )
    signals = TrendDailyRegime().signals(candles)
    trail = signals.__class__(
        signals.enter_long,
        signals.exit_long,
        signals.stop_distance,
        0,
        (Decimal("2"),) * 4,
    )
    expected = ["7", "8", "10", "10", "11"]
    for bar, value in enumerate(expected):
        got = stop_in_effect(
            candles, trail, entry_index=0, initial_stop=Decimal("7"), bar_index=bar
        )
        assert got == Decimal(value)


def test_timeframe_outside_pre_registration_returns_no_markers() -> None:
    result = markers(synthetic_daily(), timeframe="4h")
    assert result["status"] == "UNAVAILABLE"
    assert result["reason_code"] == "TIMEFRAME_NOT_PRE_REGISTERED"
    assert result["markers"] == []


def test_default_strategy_output_is_unchanged_by_the_registry() -> None:
    candles = synthetic_daily()
    result = build_strategy_markers(
        candles=candles,
        data_quality_status="VALID",
        indicators=served_indicators(candles),
    )
    assert result["strategy"]["strategy_id"] == "ema-trend-atr-stop"
    assert all("sma_200" not in m["indicators"] for m in result["markers"])
