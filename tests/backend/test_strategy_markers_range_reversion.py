"""Focused tests for range-reversion-4h v1 strategy markers (E2f part 2, #555).

All candle data here is SYNTHETIC and exists only to exercise deterministic
behaviour; none of it represents real market history or real results.
"""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from trading_platform_api.research.backtest import CostAssumptions, run_segment
from trading_platform_api.research.candles import Candle
from trading_platform_api.research.indicators import (
    adx_wilder,
    atr_wilder,
    bollinger,
    rsi_wilder,
)
from trading_platform_api.research.markers import (
    build_strategy_markers,
    registered_marker_strategy,
)
from trading_platform_api.research.strategy import RangeReversion4h

START = datetime(2024, 1, 1, tzinfo=UTC)
STEP = timedelta(hours=4)


def synthetic_range(length: int = 400) -> tuple[Candle, ...]:
    """SYNTHETIC 4h range: a slow oscillation with periodic gradual dips."""
    candles = []
    previous = Decimal(100)
    for index in range(length):
        wave = Decimal((index * 7) % 24 - 12) / 8
        phase = index % 47
        dip = Decimal(-2 * (phase - 35)) if 36 <= phase <= 41 else Decimal(0)
        close = Decimal(100) + wave + dip
        high = max(previous, close) + Decimal((index * 3) % 4 + 1) / 5
        low = min(previous, close) - Decimal((index * 5) % 3 + 1) / 5
        candles.append(Candle(START + STEP * index, previous, high, low, close, 1))
        previous = close
    return tuple(candles)


def served_indicators(candles: tuple[Candle, ...]) -> dict[str, object]:
    """Mirror of the snapshot envelopes (RSI values carry a status object)."""
    closes = [item.close for item in candles]

    def text(value: Decimal | None) -> str | None:
        return None if value is None else str(value)

    def envelope(points: list[dict[str, object]]) -> dict[str, object]:
        return {
            "status": "AVAILABLE",
            "reason_code": None,
            "result": {"points": points},
        }

    bands = bollinger(closes, 20)
    return {
        "atr-14": envelope([{"value": text(v)} for v in atr_wilder(candles, 14)]),
        "rsi-14": envelope(
            [
                {"value": {"value": text(v), "status": "READY", "reason": None}}
                for v in rsi_wilder(closes, 14)
            ]
        ),
        "bollinger-bands-20": envelope(
            [
                {
                    "middle": text(None if b is None else b[0]),
                    "upper": text(None if b is None else b[1]),
                    "lower": text(None if b is None else b[2]),
                }
                for b in bands
            ]
        ),
    }


def markers(
    candles: tuple[Candle, ...],
    *,
    timeframe: str = "4h",
    indicators: dict[str, object] | None = None,
) -> dict:
    strategy, required = registered_marker_strategy("range-reversion-4h", 1)
    return build_strategy_markers(
        candles=candles,
        data_quality_status="VALID",
        indicators=indicators or served_indicators(candles),
        strategy=strategy,
        timeframe=timeframe,
        required_timeframe=required,
    )


def iso(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


def test_registry_serves_strategy_b_on_4h_only() -> None:
    strategy, required = registered_marker_strategy("range-reversion-4h", 1)
    assert isinstance(strategy, RangeReversion4h) and required == "4h"
    result = markers(synthetic_range(), timeframe="1d")
    assert (result["status"], result["reason_code"]) == (
        "UNAVAILABLE",
        "TIMEFRAME_NOT_PRE_REGISTERED",
    )


def test_markers_match_the_time_stop_backtest() -> None:
    candles = synthetic_range()
    result = markers(candles)
    assert result["status"] == "AVAILABLE"
    assert "range-reversion-4h v1" in result["evidence_scope"]
    signals = RangeReversion4h().signals(candles)
    backtest = run_segment(
        candles,
        signals,
        CostAssumptions(),
        start=signals.first_tradable_index,
        end=len(candles),
    )
    assert backtest.trades
    filled = [m for m in result["markers"] if m["status"] == "FILLED"]
    buys = [m for m in filled if m["side"] == "BUY"]
    sells = [m for m in filled if m["side"] == "SELL"]
    assert [b["fill_time"]["value"] for b in buys] == [
        iso(t.entry_time) for t in backtest.trades
    ]
    closed = [t for t in backtest.trades if t.exit_reason != "END_OF_SEGMENT"]
    assert [(s["fill_time"]["value"], s["exit_reason"]) for s in sells] == [
        (iso(t.exit_time), t.exit_reason) for t in closed
    ]

    # BUY conditions carry the pre-registered thresholds with their values.
    first = buys[0]
    adx, lower, rsi, atr = first["conditions"]
    assert Decimal(adx["adx_14"]["value"]) < 20
    assert Decimal(lower["close"]["value"]) < Decimal(lower["bb_lower"]["value"])
    assert Decimal(rsi["rsi_14"]["value"]) < 30
    assert Decimal(atr["atr_14"]["value"]) > 0
    index = [iso(c.open_time) for c in candles].index(first["time"]["value"])
    assert first["indicators"]["adx_14"]["value"] == str(adx_wilder(candles, 14)[index])
    assert first["stop_distance"]["reason"] == "1.5 x ATR14 at signal close"
    for key in ("rsi_14", "bb_middle", "bb_upper", "bb_lower", "atr_14"):
        assert first["indicators"][key]["label"] == "VERIFIED_FACT"
    assert "ema_20" not in first["indicators"]


def test_middle_band_exits_explain_themselves() -> None:
    result = markers(synthetic_range())
    sells = [m for m in result["markers"] if m["side"] == "SELL"]
    assert {m["exit_reason"] for m in sells} == {"SIGNAL_EXIT"}
    for marker in sells:
        condition = marker["conditions"][0]
        assert Decimal(condition["close"]["value"]) >= Decimal(
            condition["bb_middle"]["value"]
        )


def flat_after_first_entry(extra: int) -> tuple[Candle, ...]:
    """SYNTHETIC: the range up to the first entry signal, then flat bars.

    The flat close stays below the middle band (older, higher closes are
    still in the 20-bar window) and well above the stop, so only the time
    stop can close the position.
    """
    candles = synthetic_range()
    signal = RangeReversion4h().signals(candles).enter_long.index(True)
    head = candles[: signal + 1]
    close = head[-1].close
    tail = tuple(
        Candle(
            head[-1].open_time + STEP * (number + 1),
            close,
            close + Decimal("0.1"),
            close - Decimal("0.1"),
            close,
            1,
        )
        for number in range(extra)
    )
    return head + tail


def test_time_stop_exit_after_twelve_held_bars() -> None:
    # Entry fills at bar s+1; held bars s+1..s+12; exit at the open of s+13.
    result = markers(flat_after_first_entry(14))
    sells = [m for m in result["markers"] if m["side"] == "SELL"]
    assert [(m["status"], m["exit_reason"]) for m in sells] == [("FILLED", "TIME_EXIT")]
    condition = sells[0]["conditions"][0]
    assert condition["condition"] == "position held 12 bars at close (time stop)"
    assert condition["bars_held"]["value"] == 12


def test_time_stop_on_the_last_candle_is_a_pending_sell() -> None:
    result = markers(flat_after_first_entry(12))
    assert result["position"] == "OPEN"
    last = result["markers"][-1]
    assert (last["side"], last["status"], last["exit_reason"]) == (
        "SELL",
        "PENDING_FILL",
        "TIME_EXIT",
    )
    assert last["conditions"][0]["bars_held"]["value"] == 12
    assert result["current_stop"]["label"] == "RESEARCH_PROPOSAL"


def test_rsi_or_band_mismatch_returns_no_markers() -> None:
    candles = synthetic_range()
    served = served_indicators(candles)
    points = served["rsi-14"]["result"]["points"]  # type: ignore[index]
    for point in points:
        if point["value"]["value"] is not None:
            point["value"]["value"] = "1"
    result = markers(candles, indicators=served)
    assert (result["status"], result["reason_code"]) == (
        "UNAVAILABLE",
        "INDICATOR_PARITY_FAILED",
    )
    missing = served_indicators(candles)
    del missing["bollinger-bands-20"]
    assert markers(candles, indicators=missing)["status"] == "UNAVAILABLE"
