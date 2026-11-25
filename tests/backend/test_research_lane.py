"""Focused tests for the lean Spot strategy research lane (ADR-0032).

All candle data here is SYNTHETIC and exists only to exercise deterministic
behaviour; none of it represents real market history or real results.
"""

import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import httpx
import pytest
from trading_platform_api.research.__main__ import main
from trading_platform_api.research.backtest import (
    CostAssumptions,
    SegmentResult,
    Trade,
    run_segment,
)
from trading_platform_api.research.candles import (
    Candle,
    CandleDataError,
    format_candle_csv,
    parse_candle_csv,
)
from trading_platform_api.research.evaluation import (
    EvaluationProtocol,
    curve_stats,
    decide,
)
from trading_platform_api.research.fetch import fetch_klines
from trading_platform_api.research.indicators import atr_wilder, ema
from trading_platform_api.research.report import run_study, to_markdown
from trading_platform_api.research.strategy import EmaTrendAtrStop, StrategySignals

START = datetime(2024, 1, 1, tzinfo=UTC)
STEP = timedelta(hours=4)
STEP_MS = 4 * 3600 * 1000
NO_COSTS = CostAssumptions(Decimal("0"), Decimal("0"), "synthetic zero-cost test")


def synthetic_rows(closes, *, start=START):
    rows = []
    previous = closes[0]
    base = int(start.timestamp() * 1000)
    for index, close in enumerate(closes):
        opening = previous
        high = max(opening, close) * Decimal("1.001")
        low = min(opening, close) * Decimal("0.999")
        open_ms = base + index * STEP_MS
        rows.append(
            (
                open_ms,
                str(opening),
                str(high),
                str(low),
                str(close),
                "1",
                open_ms + STEP_MS - 1,
            )
        )
        previous = close
    return rows


def synthetic_csv(closes, *, symbol="BTCUSDT", start=START):
    rows = synthetic_rows(closes, start=start)
    fetched = START + STEP * (len(closes) + 1)
    return format_candle_csv(
        source="synthetic-test",
        symbol=symbol,
        timeframe="4h",
        fetched_at=fetched,
        rows=rows,
    )


def wave(length, *, base="100", amplitude="30", period=120, drift="0"):
    """SYNTHETIC trending wave: alternating up and down legs."""
    out = []
    price = Decimal(base)
    half = period // 2
    for index in range(length):
        leg = Decimal(amplitude) / half
        price += (leg if (index // half) % 2 == 0 else -leg) + Decimal(drift)
        out.append(price.quantize(Decimal("0.0001")))
    return out


def test_ema_and_atr_use_registered_formulas():
    values = [Decimal(v) for v in (1, 2, 3, 4, 5)]
    result = ema(values, 3)
    assert result[:2] == [None, None]
    assert result[2] == Decimal(2)
    assert result[3] == Decimal("3.0")
    assert result[4] == Decimal("4.00")
    candles = parse_candle_csv(
        synthetic_csv([Decimal(100 + i) for i in range(20)])
    ).candles
    atr = atr_wilder(candles, 14)
    assert atr[13] is None and atr[14] is not None and atr[15] is not None


def test_csv_round_trip_and_fail_closed_cases():
    closes = [Decimal(100 + i) for i in range(10)]
    document = synthetic_csv(closes)
    series = parse_candle_csv(document)
    assert len(series.candles) == 10 and series.instrument_id == "BTC-USDT-SPOT"
    assert series.content_sha256 == parse_candle_csv(document).content_sha256

    lines = document.splitlines()
    gap = "\n".join(lines[:5] + lines[6:]) + "\n"
    with pytest.raises(CandleDataError, match="not contiguous"):
        parse_candle_csv(gap)
    unclosed = document.replace(
        lines[0].split("fetched_at=")[1],
        (START + STEP * 5).strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
    )
    with pytest.raises(CandleDataError, match="not closed"):
        parse_candle_csv(unclosed)
    with pytest.raises(CandleDataError, match="provenance header"):
        parse_candle_csv("\n".join(lines[1:]))
    with pytest.raises(CandleDataError, match="approved Spot symbol"):
        parse_candle_csv(document.replace("symbol=BTCUSDT", "symbol=DOGEUSDT"))
    bad = lines[2].split(",")
    bad[2] = "1"  # high below open/close
    with pytest.raises(CandleDataError, match="inconsistent"):
        parse_candle_csv("\n".join(lines[:2] + [",".join(bad)] + lines[3:]))


def _signals(n, enter=(), leave=(), distance=Decimal("5")):
    return StrategySignals(
        enter_long=tuple(i in enter for i in range(n)),
        exit_long=tuple(i in leave for i in range(n)),
        stop_distance=tuple(distance for _ in range(n)),
        first_tradable_index=0,
    )


def test_entry_fills_next_open_and_costs_apply_both_sides():
    closes = [Decimal(100 + i) for i in range(10)]
    candles = parse_candle_csv(synthetic_csv(closes)).candles
    signals = _signals(10, enter={2}, leave={6})
    costs = CostAssumptions(Decimal("10"), Decimal("5"), "synthetic")
    result = run_segment(candles, signals, costs, start=0, end=10)
    (trade,) = result.trades
    assert trade.entry_time == candles[3].open_time
    assert trade.exit_time == candles[7].open_time
    assert trade.exit_reason == "SIGNAL_EXIT"
    buy = candles[3].open * Decimal("1.0005")
    sell = candles[7].open * Decimal("0.9995")
    expected = (Decimal("0.999") / buy) * sell * Decimal("0.999") - 1
    assert trade.entry_price == buy
    assert trade.net_return == expected
    assert trade.gross_return == candles[7].open / candles[3].open - 1
    assert trade.net_return < trade.gross_return


def test_stop_gap_through_fills_at_open():
    closes = [Decimal(100)] * 4 + [Decimal(80)] + [Decimal(80)] * 3
    candles = list(parse_candle_csv(synthetic_csv(closes)).candles)
    gapped = candles[5]
    candles[5] = Candle(
        gapped.open_time, Decimal(70), Decimal(81), Decimal(69), Decimal(80), Decimal(1)
    )
    signals = _signals(8, enter={1}, distance=Decimal(5))
    result = run_segment(tuple(candles), signals, NO_COSTS, start=0, end=8)
    (trade,) = result.trades
    assert trade.exit_reason == "STOP"
    # bar 4 opens at 100, low 79.92 < stop 95 -> stop fills at 95 on bar 4.
    assert trade.exit_time == candles[4].open_time
    assert trade.exit_price == Decimal(95)
    candles2 = list(candles)
    candles2[4] = Candle(
        candles[4].open_time,
        Decimal(90),
        Decimal(91),
        Decimal(89),
        Decimal(90),
        Decimal(1),
    )
    (trade2,) = run_segment(tuple(candles2), signals, NO_COSTS, start=0, end=8).trades
    assert trade2.exit_price == Decimal(90)  # gapped below the stop: open


def test_future_bars_do_not_change_earlier_decisions():
    closes = wave(400)
    strategy = EmaTrendAtrStop()
    base = parse_candle_csv(synthetic_csv(closes)).candles
    changed_closes = closes[:300] + [c * 3 for c in closes[300:]]
    changed = parse_candle_csv(synthetic_csv(changed_closes)).candles
    a = run_segment(base, strategy.signals(base), NO_COSTS, start=60, end=400)
    b = run_segment(changed, strategy.signals(changed), NO_COSTS, start=60, end=400)
    cutoff = base[299].open_time
    early_a = [t for t in a.trades if t.exit_time < cutoff]
    early_b = [t for t in b.trades if t.exit_time < cutoff]
    assert early_a and early_a == early_b


def _trade(net):
    moment = START
    return Trade(
        moment,
        Decimal(1),
        Decimal("0.9"),
        moment,
        Decimal(1),
        "SIGNAL_EXIT",
        net,
        net,
        net * 10,
        2,
    )


def _segment(returns, equity, hold):
    return SegmentResult(
        START,
        START,
        len(equity),
        tuple(_trade(Decimal(r)) for r in returns),
        tuple(Decimal(v) for v in equity),
        tuple(Decimal(v) for v in hold),
        1,
    )


def test_verdict_states():
    protocol = EvaluationProtocol(bootstrap_resamples=500)
    few = _segment(["0.05"] * 5, ["1", "1.2"], ["1", "1.1"])
    verdict, _ = decide(protocol, [few])
    assert (
        verdict.status == "INCONCLUSIVE" and "INSUFFICIENT_SAMPLE" in verdict.reasons[0]
    )

    losing = _segment(["-0.01"] * 40, ["1", "0.9"], ["1", "1.1"])
    verdict, _ = decide(protocol, [losing])
    assert verdict.status == "FAIL"
    assert "NON_POSITIVE_EXPECTANCY_AFTER_COSTS" in verdict.reasons

    returns = ["0.04", "-0.01"] * 20
    strong = _segment(returns, ["1", "1.3", "1.25", "1.5"], ["1", "1.4", "0.9", "1.1"])
    verdict, evidence = decide(protocol, [strong])
    assert verdict.status == "PASS", verdict
    assert evidence["bootstrap_lower_bound_mean_return"] > 0

    worse_than_holding = _segment(
        returns, ["1", "1.1", "0.95", "1.05"], ["1", "2", "1.9", "2.5"]
    )
    verdict, _ = decide(protocol, [worse_than_holding])
    assert "DOES_NOT_BEAT_BUY_AND_HOLD_RISK_ADJUSTED" in verdict.reasons


def test_curve_drawdown():
    stats = curve_stats([Decimal(v) for v in ("1.2", "0.9", "1.5", "1.2")])
    assert stats.max_drawdown == Decimal("0.25")
    assert stats.total_return == Decimal("0.2")


def test_study_is_deterministic_and_carries_no_authority():
    series = [
        parse_candle_csv(synthetic_csv(wave(900, drift="0.01"), symbol="BTCUSDT")),
        parse_candle_csv(
            synthetic_csv(wave(900, base="50", period=90), symbol="ETHUSDT")
        ),
    ]
    created = datetime(2026, 11, 25, tzinfo=UTC)
    protocol = EvaluationProtocol(bootstrap_resamples=200)
    first = run_study(series, protocol=protocol, created_at=created)
    second = run_study(series, protocol=protocol, created_at=created)
    assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)
    assert first["verdict"]["status"] in {"PASS", "FAIL", "INCONCLUSIVE"}
    assert set(first["authority"].values()) == {False}
    assert first["periods"]["holdout_bars"] == int(
        Decimal(first["periods"]["holdout_bars"] + first["periods"]["development_bars"])
        * Decimal("0.30")
    )
    assert "RESEARCH EVIDENCE ONLY" in to_markdown(first)


def test_strategy_version_digest_changes_with_parameters():
    base = EmaTrendAtrStop()
    assert (
        base.content_sha256 != replace(base, version=2, slow_period=100).content_sha256
    )


def test_fetch_drops_unclosed_candles_and_paginates():
    now = START + STEP * 3 + timedelta(minutes=30)
    rows = synthetic_rows([Decimal(100 + i) for i in range(4)])

    def handler(request):
        start_ms = int(request.url.params["startTime"])
        page = [list(r[:6]) + [r[6]] for r in rows if r[0] >= start_ms]
        return httpx.Response(200, json=page)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    document = fetch_klines(
        symbol="BTCUSDT",
        timeframe="4h",
        start=START,
        client=client,
        now=now,
        pause_seconds=0,
    )
    series = parse_candle_csv(document)
    assert len(series.candles) == 3  # fourth candle still open at fetch time


def test_cli_run_fails_closed_without_data(tmp_path: Path, capsys):
    code = main(
        ["run", "--data", str(tmp_path / "missing"), "--out", str(tmp_path / "out")]
    )
    assert code == 2
    assert "fail closed" in capsys.readouterr().err
