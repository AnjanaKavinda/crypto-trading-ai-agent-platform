"""E2e: trend-daily-regime v1 and protocol spot-walk-forward-prospective v2.

All candles and trades here are SYNTHETIC test fixtures, not market data.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from test_moving_averages import evidence
from trading_platform_api.analysis.moving_averages import (
    MovingAverageKind,
    calculate_moving_average,
)
from trading_platform_api.research.__main__ import main
from trading_platform_api.research.backtest import (
    CostAssumptions,
    SegmentResult,
    Trade,
    run_segment,
)
from trading_platform_api.research.candles import (
    Candle,
    format_candle_csv,
    parse_candle_csv,
)
from trading_platform_api.research.evaluation import WalkForwardProtocol
from trading_platform_api.research.indicators import sma
from trading_platform_api.research.report import StudyError
from trading_platform_api.research.strategy import StrategySignals, TrendDailyRegime
from trading_platform_api.research.walk_forward import (
    historical_verdict,
    run_walk_forward_study,
    to_markdown_v2,
    window_bounds,
)

DAY = timedelta(days=1)
DAY_MS = 86_400_000
ERA = datetime(2021, 9, 30, tzinfo=UTC)
NO_COSTS = CostAssumptions(Decimal("0"), Decimal("0"), "synthetic zero-cost test")


def _bar(index: int, o: str, h: str, low: str, c: str) -> Candle:
    return Candle(
        ERA + index * DAY, Decimal(o), Decimal(h), Decimal(low), Decimal(c), Decimal(1)
    )


def test_parameters_match_the_preregistration() -> None:
    strategy = TrendDailyRegime()
    assert strategy.describe() == {
        "strategy_id": "trend-daily-regime",
        "version": 1,
        "fast_period": 20,
        "slow_period": 50,
        "regime_period": 200,
        "atr_period": 14,
        "stop_atr_multiple": "3",
        "trail_atr_multiple": "3",
    }
    protocol = WalkForwardProtocol()
    assert (protocol.protocol_id, protocol.version) == (
        "spot-walk-forward-prospective",
        2,
    )
    assert (protocol.development_start, protocol.seen_start) == (
        "2021-09-30",
        "2025-05-12",
    )
    assert (protocol.windows, protocol.min_positive_windows) == (4, 3)
    assert protocol.min_holdout_trades == 30
    assert protocol.max_portfolio_drawdown == Decimal("0.30")
    assert protocol.max_symbol_drawdown == Decimal("0.40")
    assert protocol.min_profit_factor == Decimal("1.20")


def test_sma_equals_registered_platform_sma() -> None:
    closes = tuple(str(Decimal(100) + Decimal((i * 37) % 23) / 7) for i in range(260))
    snapshot, observations, quality = evidence(closes)
    platform = calculate_moving_average(
        snapshot=snapshot,
        observations=observations,
        quality=quality,
        kind=MovingAverageKind.SMA,
        period=200,
        timeframe="1m",
    )
    assert sma([Decimal(v) for v in closes], 200) == [
        point.value for point in platform.points
    ]


def test_entry_only_when_trend_state_turns_true() -> None:
    # SYNTHETIC: small periods isolate the state-transition rule.
    strategy = replace(
        TrendDailyRegime(), fast_period=2, slow_period=3, regime_period=4, atr_period=2
    )
    closes = ["10", "10", "10", "10", "12", "13", "14", "9", "8", "12", "14", "15"]
    candles = tuple(
        _bar(i, c, str(Decimal(c) + 1), str(Decimal(c) - 1), c)
        for i, c in enumerate(closes)
    )
    states = strategy.trend_state(candles)
    # Warm-up (SMA4 needs 4 closes); flat start is not a trend; rally turns
    # it on, the drop turns it off, the second rally turns it on again.
    # Bar 9 by hand: EMA2 10.944 > EMA3 10.75 and close 12 > SMA4 10.75.
    assert states == [
        None,
        None,
        None,
        False,
        True,
        True,
        True,
        False,
        False,
        True,
        True,
        True,
    ]
    signals = strategy.signals(candles)
    assert [i for i, flag in enumerate(signals.enter_long) if flag] == [4, 9]
    # Holding while T stays true never re-signals an entry.
    assert not any(signals.enter_long[5:7])
    # Signal exit is EMA fast < EMA slow at close (a level, not a cross).
    assert signals.exit_long[7] and signals.exit_long[8]
    assert signals.stop_distance[4] == signals.trail_distance[4]  # type: ignore[index]


def test_trailing_stop_ratchets_up_and_is_never_lowered() -> None:
    # SYNTHETIC 6-bar series, zero costs, initial stop distance 6.
    candles = (
        _bar(0, "100", "101", "99", "100"),  # BUY signal
        _bar(1, "100", "103", "99", "102"),  # entry 100, stop 94 -> trail 98
        _bar(2, "102", "102", "99", "101"),  # lower close, wider ATR: stays 98
        _bar(3, "101", "111", "100", "110"),  # new high close -> stop 106
        _bar(4, "108", "109", "105", "107"),  # low 105 <= 106: stop fill 106
        _bar(5, "107", "108", "106", "107"),
    )
    trail = (Decimal(4), Decimal(4), Decimal(5), Decimal(4), Decimal(4), Decimal(4))
    enter = (True,) + (False,) * 5
    signals = StrategySignals(enter, (False,) * 6, (Decimal(6),) * 6, 0, trail)
    result = run_segment(candles, signals, NO_COSTS, start=0, end=6)
    (trade,) = result.trades
    assert trade.entry_price == Decimal(100)
    assert trade.stop_price == Decimal(94)  # initial stop kept for R
    assert (trade.exit_reason, trade.exit_price) == ("STOP", Decimal(106))
    assert trade.exit_time == candles[4].open_time
    assert trade.r_multiple == Decimal(1)  # (106 - 100) / 6

    # Same path, but bar 4 opens at 104 below the trailed 106: fills at open.
    gapped = (*candles[:4], _bar(4, "104", "105", "103", "104"), candles[5])
    (trade,) = run_segment(gapped, signals, NO_COSTS, start=0, end=6).trades
    assert (trade.exit_reason, trade.exit_price) == ("STOP", Decimal(104))

    # Without a trailing distance the stop stays at 94 (v1 behaviour).
    fixed = replace(signals, trail_distance=None)
    (trade,) = run_segment(candles, fixed, NO_COSTS, start=0, end=6).trades
    assert trade.exit_reason == "END_OF_SEGMENT"


def test_window_split_is_four_consecutive_equal_windows() -> None:
    assert window_bounds(200, 1150, 4) == [
        (200, 437),
        (437, 674),
        (674, 911),
        (911, 1150),
    ]
    with pytest.raises(StudyError):
        window_bounds(10, 13, 4)


def _trade(net: str) -> Trade:
    value = Decimal(net)
    return Trade(
        ERA,
        Decimal(1),
        Decimal("0.9"),
        ERA,
        Decimal(1),
        "SIGNAL_EXIT",
        value,
        value,
        value * 10,
        2,
    )


def _segment(returns: list[str], equity: list[str], hold: list[str]) -> SegmentResult:
    return SegmentResult(
        ERA,
        ERA,
        len(equity),
        tuple(_trade(r) for r in returns),
        tuple(Decimal(v) for v in equity),
        tuple(Decimal(v) for v in hold),
        1,
    )


def test_historical_verdict_states() -> None:
    protocol = WalkForwardProtocol(bootstrap_resamples=500)
    returns = ["0.04", "-0.01"] * 20
    strong = _segment(returns, ["1", "1.3", "1.25", "1.5"], ["1", "1.4", "0.9", "1.1"])
    good = [_trade("0.02")]
    bad = [_trade("-0.02")]

    verdict, _, positive = historical_verdict(
        protocol, [strong], ["BTCUSDT"], [good, good, good, bad]
    )
    assert (verdict.status, positive) == ("HISTORICAL_PASS", 3)

    verdict, _, positive = historical_verdict(
        protocol, [strong], ["BTCUSDT"], [good, bad, [], good]
    )
    assert verdict.status == "FAIL" and positive == 2
    assert verdict.reasons == ("TOO_FEW_POSITIVE_WINDOWS: 2 of 4 < 3",)

    losing = _segment(["-0.01"] * 40, ["1", "0.9"], ["1", "1.1"])
    verdict, _, _ = historical_verdict(protocol, [losing], ["BTCUSDT"], [bad] * 4)
    assert verdict.status == "FAIL"
    assert "NON_POSITIVE_EXPECTANCY_AFTER_COSTS" in verdict.reasons
    assert verdict.reasons[-1].startswith("TOO_FEW_POSITIVE_WINDOWS")

    few = _segment(["0.05"] * 5, ["1", "1.2"], ["1", "1.1"])
    verdict, _, _ = historical_verdict(protocol, [few], ["BTCUSDT"], [bad] * 4)
    assert verdict.status == "INCONCLUSIVE"
    assert verdict.reasons == ("INSUFFICIENT_SAMPLE: 5 development-era trades < 30",)


def _daily_csv(symbol: str, days: int, start: datetime = ERA) -> str:
    """SYNTHETIC daily trending wave with uneven ranges."""
    rows = []
    price = Decimal(100)
    base = int(start.timestamp() * 1000)
    for index in range(days):
        opening = price
        step = Decimal(3) if (index // 90) % 3 != 2 else Decimal(-4)
        price = max(Decimal(10), price + step + Decimal((index * 7) % 5 - 2))
        high = max(opening, price) + Decimal((index * 3) % 4 + 1)
        low = min(opening, price) - Decimal((index * 5) % 3 + 1)
        open_ms = base + index * DAY_MS
        rows.append(
            (
                open_ms,
                str(opening),
                str(high),
                str(low),
                str(price),
                "1",
                open_ms + DAY_MS - 1,
            )
        )
    return format_candle_csv(
        source="synthetic-test",
        symbol=symbol,
        timeframe="1d",
        fetched_at=start + DAY * (days + 1),
        rows=rows,
    )


def test_walk_forward_study_end_to_end_on_synthetic_data() -> None:
    # 2021-09-30 .. 2026-11-27: two bars fall in the prospective period.
    days = (datetime(2026, 11, 27, tzinfo=UTC) - ERA).days + 1
    series = [
        parse_candle_csv(_daily_csv(symbol, days)) for symbol in ("BTCUSDT", "ETHUSDT")
    ]
    created = datetime(2026, 11, 26, tzinfo=UTC)
    protocol = WalkForwardProtocol(bootstrap_resamples=200)
    first = run_walk_forward_study(series, protocol=protocol, created_at=created)
    again = run_walk_forward_study(series, protocol=protocol, created_at=created)
    assert first == again
    assert first["report_type"] == "LEAN_SPOT_WALK_FORWARD_STUDY"
    assert first["verdict"]["status"] in {"HISTORICAL_PASS", "FAIL", "INCONCLUSIVE"}
    periods = first["periods"]
    # Trading starts once SMA200 and the previous trend state exist.
    assert periods["development_start"] == "2022-04-18T00:00:00Z"
    assert periods["development_end"] == "2025-05-11T00:00:00Z"
    assert periods["prospective_bars_present_not_evaluated"] == 2
    assert [row["window"] for row in first["windows"]] == [1, 2, 3, 4]
    assert first["windows"][0]["start"] == "2022-04-18T00:00:00Z"
    assert first["windows"][-1]["end"] == "2025-05-11T00:00:00Z"
    seen = first["seen_holdout_informational"]
    assert seen["status"] == "CONTAMINATED_INFORMATIONAL"
    for item in first["per_symbol"].values():
        for trade in item["development_era_trades"]:
            assert trade["entry_time"] < "2025-05-12"
    assert set(first["authority"].values()) == {False}
    markdown = to_markdown_v2(first)
    assert "CONTAMINATED_INFORMATIONAL" in markdown
    assert "Historical verdict" in markdown


def test_walk_forward_study_fails_closed_on_late_or_wrong_data() -> None:
    late = parse_candle_csv(_daily_csv("BTCUSDT", 1500, ERA + DAY))
    with pytest.raises(StudyError, match="after the development era start"):
        run_walk_forward_study([late])
    short = parse_candle_csv(_daily_csv("BTCUSDT", 300))
    with pytest.raises(StudyError, match="before the end of the development era"):
        run_walk_forward_study([short])


def test_cli_rejects_unregistered_strategy_protocol_pairs(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    out = ["--data", str(tmp_path), "--out", str(tmp_path / "out")]
    code = main(["run", "--strategy", "ema-trend-atr-stop", "--protocol", "v2", *out])
    assert code == 2 and "not pre-registered" in capsys.readouterr().err
    code = main(
        ["run", "--strategy", "trend-daily-regime", "--protocol", "v2"]
        + ["--timeframe", "4h", *out]
    )
    assert code == 2 and "pre-registered for 1d" in capsys.readouterr().err
    code = main(["run", "--strategy", "trend-daily-regime", "--protocol", "v2", *out])
    assert code == 2 and "fail closed" in capsys.readouterr().err  # no data files
