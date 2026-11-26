"""Focused tests for the protocol v2 forward (prospective) tracker (E2f2, #516).

All candle and trade data here is SYNTHETIC and exists only to exercise
deterministic behaviour; none of it represents real market history or results.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from trading_platform_api.research.backtest import (
    CostAssumptions,
    SegmentResult,
    Trade,
    run_segment,
)
from trading_platform_api.research.candles import Candle
from trading_platform_api.research.evaluation import WalkForwardProtocol
from trading_platform_api.research.forward import (
    FORWARD_REVIEWS,
    HistoricalVerdict,
    add_months,
    forward_record,
    forward_stage,
    historical_verdict_from_report,
    symbol_forward,
)
from trading_platform_api.research.strategy import RangeReversion4h, TrendDailyRegime

PROSPECTIVE = datetime(2026, 11, 26, tzinfo=UTC)
DAY = timedelta(days=1)
STRATEGY = TrendDailyRegime()


def daily(start: datetime, count: int) -> tuple[Candle, ...]:
    """SYNTHETIC daily wave with uneven ranges (up legs, then sharp drops)."""
    candles = []
    previous = Decimal(100)
    for index in range(count):
        leg = index % 90
        close = previous + (Decimal(1) if leg < 60 else Decimal("-1.6"))
        high = max(previous, close) * Decimal("1.01")
        low = min(previous, close) * Decimal("0.99")
        candles.append(Candle(start + DAY * index, previous, high, low, close, 1))
        previous = close
    return tuple(candles)


def trade(net: str, day: int = 0) -> Trade:
    moment = PROSPECTIVE + DAY * day
    return Trade(
        entry_time=moment,
        entry_price=Decimal(100),
        stop_price=Decimal(90),
        exit_time=moment + DAY,
        exit_price=Decimal(100) * (1 + Decimal(net)),
        exit_reason="SIGNAL_EXIT",
        gross_return=Decimal(net),
        net_return=Decimal(net),
        r_multiple=Decimal(net) * 10,
        bars_held=2,
    )


def segment(trades: list[Trade], equity: list[str]) -> SegmentResult:
    return SegmentResult(
        start=PROSPECTIVE,
        end=PROSPECTIVE + DAY * (len(equity) - 1),
        bars=len(equity),
        trades=tuple(trades),
        equity=tuple(Decimal(v) for v in equity),
        buy_and_hold_equity=tuple(Decimal(1) for _ in equity),
        bars_in_market=len(equity),
    )


def passed(drawdown: str = "0.20") -> HistoricalVerdict:
    return HistoricalVerdict(
        "HISTORICAL_PASS", STRATEGY.content_sha256, Decimal(drawdown)
    )


def test_review_points_are_the_preregistered_ones() -> None:
    assert FORWARD_REVIEWS["trend-daily-regime"].trades == 15
    assert FORWARD_REVIEWS["trend-daily-regime"].months == 6
    assert FORWARD_REVIEWS["range-reversion-4h"].trades == 30
    assert FORWARD_REVIEWS["range-reversion-4h"].months == 3
    assert add_months(PROSPECTIVE, 3) == datetime(2027, 2, 26, tzinfo=UTC)
    assert add_months(PROSPECTIVE, 6) == datetime(2027, 5, 26, tzinfo=UTC)
    assert add_months(datetime(2026, 8, 31, tzinfo=UTC), 6) == datetime(
        2027, 2, 28, tzinfo=UTC
    )


def stage(historical: HistoricalVerdict | None, segments: list, days: int = 10) -> dict:
    return forward_stage(
        STRATEGY,
        historical,
        segments,
        as_of=PROSPECTIVE + DAY * days,
        prospective_start=PROSPECTIVE,
    )


def test_stage_follows_only_the_preregistered_rules() -> None:
    few = [segment([trade("0.02")], ["1", "1.02"])]
    assert stage(None, few)["stage"] == "NOT_VALIDATED"
    failed = HistoricalVerdict("FAIL", STRATEGY.content_sha256, Decimal("0.5"))
    assert stage(failed, few)["stage"] == "FAIL"
    unclear = HistoricalVerdict("INCONCLUSIVE", STRATEGY.content_sha256, Decimal(0))
    assert stage(unclear, few)["reason"] == "HISTORICAL_INCONCLUSIVE"
    other = HistoricalVerdict("HISTORICAL_PASS", "0" * 64, Decimal("0.2"))
    assert stage(other, few)["stage"] == "NOT_VALIDATED"
    assert stage(passed(), [])["stage"] == "HISTORICAL_PASS"
    testing = stage(passed(), few)
    assert testing["stage"] == "FORWARD_TESTING"
    assert testing["forward"]["label"] == "SIMULATED"
    assert testing["forward"]["review_point"] == {
        "trades": 15,
        "date": "2027-05-26T00:00:00Z",
        "reached": False,
    }


def test_review_by_trade_count_or_date_decides_pass_or_fail() -> None:
    wins = [trade("0.01", day) for day in range(15)]
    good = [segment(wins, ["1", "0.9", "1.1"])]  # max DD 10% <= 20% x 1.5
    assert stage(passed(), good)["stage"] == "FORWARD_PASS"
    deep = [segment(wins, ["1", "0.6", "1.1"])]  # max DD 40% > 30%
    assert stage(passed(), deep)["reason"] == "FORWARD_DRAWDOWN_ABOVE_1_5X_HISTORICAL"
    losses = [segment([trade("-0.01")], ["1", "0.99"])]
    by_date = stage(passed(), losses, days=200)  # past 2027-05-26
    assert (by_date["stage"], by_date["reason"]) == (
        "FAIL",
        "FORWARD_EXPECTANCY_NOT_POSITIVE",
    )


def test_forward_record_replays_frozen_rules_from_the_prospective_start() -> None:
    candles = daily(PROSPECTIVE - DAY * 300, 300 + 200)
    record = forward_record(
        STRATEGY,
        {"BTCUSDT": candles},
        historical=None,
        as_of=PROSPECTIVE + DAY * 200,
    )
    assert record["label"] == "SIMULATED RESEARCH EVIDENCE - NOT AN ORDER"
    assert record["stage"] == "NOT_VALIDATED"
    assert set(record["authority"].values()) == {False}
    signals = STRATEGY.signals(candles)
    start = 300
    expected = run_segment(
        candles, signals, CostAssumptions(), start=start, end=len(candles)
    )
    assert expected.trades
    rows = record["signals"]["BTCUSDT"]
    assert [row["entry_time"] for row in rows if "entry_time" in row] == [
        t.entry_time.isoformat().replace("+00:00", "Z") for t in expected.trades
    ]
    assert all(row["entry_time"] >= "2026-11-26" for row in rows if "entry_time" in row)
    closed = [row for row in rows if row["status"] == "CLOSED"]
    assert closed and closed[0]["simulated_net_return"]["label"] == "SIMULATED"
    assert record["forward"]["closed_trades"] == len(closed)


def test_forward_fails_closed_without_warm_up_or_with_misaligned_symbols() -> None:
    short = daily(PROSPECTIVE - DAY * 10, 40)
    with pytest.raises(ValueError, match="not warmed up"):
        symbol_forward(
            STRATEGY,
            "BTCUSDT",
            short,
            prospective_start=PROSPECTIVE,
            costs=CostAssumptions(),
        )
    before = daily(PROSPECTIVE - DAY * 300, 250)
    nothing = symbol_forward(
        STRATEGY,
        "BTCUSDT",
        before,
        prospective_start=PROSPECTIVE,
        costs=CostAssumptions(),
    )
    assert nothing.segment is None and nothing.signals == ()
    with pytest.raises(ValueError, match="same candles"):
        forward_record(
            STRATEGY,
            {
                "BTCUSDT": daily(PROSPECTIVE - DAY * 300, 320),
                "ETHUSDT": daily(PROSPECTIVE - DAY * 300, 330),
            },
            historical=None,
            as_of=PROSPECTIVE,
        )


def report(**changes: object) -> dict:
    base = {
        "report_type": "LEAN_SPOT_WALK_FORWARD_STUDY",
        "stage": "HISTORICAL",
        "strategy": {**STRATEGY.describe(), "content_sha256": STRATEGY.content_sha256},
        "protocol": {"content_sha256": WalkForwardProtocol().content_sha256},
        "verdict": {"status": "HISTORICAL_PASS", "reasons": []},
        "development_era_evidence": {"portfolio": {"max_drawdown": "0.25"}},
    }
    base.update(changes)
    return base


def test_historical_verdict_is_read_from_a_matching_report_only() -> None:
    verdict = historical_verdict_from_report(report())
    assert verdict == HistoricalVerdict(
        "HISTORICAL_PASS", STRATEGY.content_sha256, Decimal("0.25")
    )
    b = RangeReversion4h()
    other = report(strategy={**b.describe(), "content_sha256": b.content_sha256})
    assert historical_verdict_from_report(other).strategy_sha256 == b.content_sha256
    for bad, match in (
        (report(report_type="LEAN_SPOT_STUDY"), "walk-forward"),
        (report(strategy={**STRATEGY.describe(), "content_sha256": "x"}), "digest"),
        (report(protocol={"content_sha256": "x"}), "protocol digest"),
        (report(verdict={"status": "PASS"}), "historical verdict"),
        (report(development_era_evidence={}), "max drawdown"),
    ):
        with pytest.raises(ValueError, match=match):
            historical_verdict_from_report(bad)
