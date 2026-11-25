"""Focused tests for ema-trend-atr-stop v1 strategy markers (E3, #525).

All candle data here is SYNTHETIC and exists only to exercise deterministic
behaviour; none of it represents real market history or real results.
"""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from trading_platform_api.research.backtest import CostAssumptions, run_segment
from trading_platform_api.research.candles import Candle
from trading_platform_api.research.indicators import atr_wilder, ema
from trading_platform_api.research.markers import (
    SIZING_INPUTS_MISSING,
    build_strategy_markers,
    position_size,
)
from trading_platform_api.research.strategy import EmaTrendAtrStop

START = datetime(2024, 1, 1, tzinfo=UTC)
STEP = timedelta(hours=4)


def synthetic_candles(length: int = 400) -> tuple[Candle, ...]:
    """SYNTHETIC trending wave with a small drift, alternating legs."""
    candles = []
    price = Decimal("100")
    previous = price
    for index in range(length):
        price += Decimal("0.5") if (index // 60) % 2 == 0 else Decimal("-0.5")
        price += Decimal("0.01")
        high = max(previous, price) * Decimal("1.001")
        low = min(previous, price) * Decimal("0.999")
        candles.append(
            Candle(START + STEP * index, previous, high, low, price, Decimal("1"))
        )
        previous = price
    return tuple(candles)


def served_indicators(candles: tuple[Candle, ...]) -> dict[str, object]:
    """Mirror of the snapshot indicator envelope, from the shared formulas."""
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


def test_markers_match_the_research_backtest_on_synthetic_data() -> None:
    candles = synthetic_candles()
    result = build_strategy_markers(
        candles=candles,
        data_quality_status="VALID",
        indicators=served_indicators(candles),
    )
    assert result["status"] == "AVAILABLE"
    strategy = EmaTrendAtrStop()
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
    assert [item["fill_time"]["value"] for item in buys] == [
        trade.entry_time.isoformat().replace("+00:00", "Z") for trade in backtest.trades
    ]
    closed = [t for t in backtest.trades if t.exit_reason != "END_OF_SEGMENT"]
    assert [item["fill_time"]["value"] for item in sells] == [
        trade.exit_time.isoformat().replace("+00:00", "Z") for trade in closed
    ]
    assert [item["modelled_entry_fill"]["value"] for item in buys] == [
        str(trade.entry_price) for trade in backtest.trades
    ]
    first = buys[0]
    assert first["entry_open"]["label"] == "VERIFIED_FACT"
    assert first["stop"]["label"] == "RESEARCH_PROPOSAL"
    assert first["position_size"]["quantity"] == {
        "label": "UNAVAILABLE",
        "value": None,
        "reason": SIZING_INPUTS_MISSING,
    }
    for name in ("leverage", "take_profit", "funding"):
        assert result["not_applicable"][name]["label"] == "NOT_APPLICABLE"
    # Hover readout equals the served snapshot indicator values at the signal.
    served = served_indicators(candles)
    index = [c.open_time for c in candles].index(
        datetime.fromisoformat(first["time"]["value"].replace("Z", "+00:00"))
    )
    for key, name in (("ema_20", "ema-20"), ("ema_50", "ema-50"), ("atr_14", "atr-14")):
        point = served[name]["result"]["points"][index]  # type: ignore[index]
        assert first["indicators"][key]["value"] == point["value"]
    cross = first["conditions"][0]
    assert Decimal(cross["previous_ema_20"]["value"]) <= Decimal(
        cross["previous_ema_50"]["value"]
    )
    assert Decimal(cross["ema_20"]["value"]) > Decimal(cross["ema_50"]["value"])


def test_sizing_arithmetic_and_spot_cap() -> None:
    sized = position_size(
        entry=Decimal("100"),
        stop=Decimal("95"),
        account_size=Decimal("1000"),
        risk_pct=Decimal("1"),
    )
    assert sized["capped"] is False
    assert sized["quantity"]["value"] == "2.00000000"
    assert sized["risk_amount_usdt"]["value"] == "10"
    assert sized["loss_at_stop_usdt"]["value"] == "10.00000000"
    capped = position_size(
        entry=Decimal("100"),
        stop=Decimal("99.5"),
        account_size=Decimal("1000"),
        risk_pct=Decimal("10"),
    )
    assert capped["capped"] is True
    assert capped["quantity"]["value"] == "10.00000000"
    assert "no leverage" in capped["quantity"]["reason"]
    missing = position_size(
        entry=Decimal("100"),
        stop=Decimal("95"),
        account_size=Decimal("1000"),
        risk_pct=None,
    )
    assert missing["quantity"]["label"] == "UNAVAILABLE"
    with pytest.raises(ValueError):
        position_size(
            entry=Decimal("100"),
            stop=Decimal("95"),
            account_size=Decimal("1000"),
            risk_pct=Decimal("101"),
        )


def test_sizing_inputs_flow_into_every_filled_buy_marker() -> None:
    candles = synthetic_candles()
    result = build_strategy_markers(
        candles=candles,
        data_quality_status="VALID",
        indicators=served_indicators(candles),
        account_size=Decimal("5000"),
        risk_pct=Decimal("0.5"),
    )
    buys = [
        item
        for item in result["markers"]
        if item["side"] == "BUY" and item["status"] == "FILLED"
    ]
    assert buys
    for item in buys:
        entry = Decimal(item["modelled_entry_fill"]["value"])
        stop = Decimal(item["stop"]["value"])
        expected = position_size(
            entry=entry,
            stop=stop,
            account_size=Decimal("5000"),
            risk_pct=Decimal("0.5"),
        )
        assert item["position_size"] == expected
        assert item["position_size"]["quantity"]["label"] == "RESEARCH_PROPOSAL"


@pytest.mark.parametrize("status", ["STALE", "INVALID", "DEGRADED"])
def test_stale_or_invalid_data_returns_no_markers(status: str) -> None:
    candles = synthetic_candles()
    result = build_strategy_markers(
        candles=candles,
        data_quality_status=status,
        indicators=served_indicators(candles),
    )
    assert result["status"] == "UNAVAILABLE"
    assert result["reason_code"] == f"DATA_QUALITY_{status}"
    assert result["markers"] == []


def test_unavailable_indicator_or_parity_mismatch_returns_no_markers() -> None:
    candles = synthetic_candles()
    indicators = served_indicators(candles)
    indicators["atr-14"] = {
        "status": "UNAVAILABLE",
        "reason_code": "STALE_FOR_SERVING_CUTOFF",
        "result": None,
    }
    result = build_strategy_markers(
        candles=candles, data_quality_status="VALID", indicators=indicators
    )
    assert (result["status"], result["markers"]) == ("UNAVAILABLE", [])
    assert result["reason_code"] == "STALE_FOR_SERVING_CUTOFF"

    tampered = served_indicators(candles)
    points = tampered["ema-20"]["result"]["points"]  # type: ignore[index]
    for point in points:
        if point["value"] is not None:
            point["value"] = str(Decimal(point["value"]) + Decimal("0.0001"))
    result = build_strategy_markers(
        candles=candles, data_quality_status="VALID", indicators=tampered
    )
    assert (result["status"], result["markers"]) == ("UNAVAILABLE", [])
    assert result["reason_code"] == "INDICATOR_PARITY_FAILED"


def test_short_history_is_warmup_without_markers() -> None:
    candles = synthetic_candles(51)
    result = build_strategy_markers(
        candles=candles,
        data_quality_status="VALID",
        indicators=served_indicators(candles),
    )
    assert (result["status"], result["reason_code"]) == (
        "WARMUP",
        "INSUFFICIENT_HISTORY",
    )
    assert result["markers"] == []
