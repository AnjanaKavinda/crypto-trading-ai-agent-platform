"""Tournament v1 runner, hurdles and report (E2t part 2, #516).

All candles are SYNTHETIC, labelled test fixtures, never market data. The
end-to-end tests use a shortened copy of the protocol (dates, resamples) so
they run fast; the pre-registered values are asserted separately.
"""

from __future__ import annotations

import json
import random
from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from trading_platform_api.research.__main__ import main
from trading_platform_api.research.candles import (
    CandleDataError,
    format_candle_csv,
    parse_candle_csv,
)
from trading_platform_api.research.evaluation import (
    CurveStats,
    TradeStats,
    bootstrap_lower_bound,
)
from trading_platform_api.research.report import StudyError
from trading_platform_api.research.strategy import TOURNAMENT_CANDIDATES
from trading_platform_api.research.tournament import (
    TournamentProtocol,
    gold_verdict,
    hurdle_h1,
    hurdle_h2,
    hurdle_h3,
    load_tournament_data,
    run_tournament,
    to_markdown_tournament,
    tournament_verdict,
)

DAY_MS = 86_400_000
SHORT = replace(
    TournamentProtocol(),
    development_end="2022-12-31",
    seen_start="2023-01-01",
    seen_end="2023-03-31",
    s2_symbols=("ADAUSDT", "DOGEUSDT", "LTCUSDT"),
    bootstrap_resamples=300,
)


def synthetic_csv(symbol: str, start: str, days: int, seed: int = 0) -> str:
    """SYNTHETIC daily candles: up/down cycles with periodic dips."""
    base = int(datetime.fromisoformat(start).replace(tzinfo=UTC).timestamp() * 1000)
    rows = []
    previous = Decimal(100)
    for index in range(days):
        k = index + seed * 17
        cycle = Decimal(k % 160 - 80 if k % 320 < 160 else 80 - k % 160)
        dip = Decimal(-6) if k % 37 in (30, 31) else Decimal(0)
        close = Decimal(100) + cycle / 4 + Decimal((k * 7) % 11 - 5) / 3 + dip
        high = max(previous, close) + Decimal((k * 3) % 4 + 1) / 4
        low = min(previous, close) - Decimal((k * 5) % 3 + 1) / 4
        rows.append(
            (
                base + index * DAY_MS,
                str(previous),
                str(high),
                str(low),
                str(close),
                "1",
                base + (index + 1) * DAY_MS - 1,
            )
        )
        previous = close
    return format_candle_csv(
        source="synthetic-test",
        symbol=symbol,
        timeframe="1d",
        fetched_at=datetime.fromtimestamp((base + (days + 1) * DAY_MS) / 1000, UTC),
        rows=rows,
    )


def write_sets(root: Path, *, early: bool = True, late_coin: bool = True) -> None:
    data, early_dir = root / "data", root / "early"
    data.mkdir()
    early_dir.mkdir()
    for seed, symbol in enumerate((*SHORT.s1_symbols, "PAXGUSDT")):
        (data / f"{symbol}_1d.csv").write_text(
            synthetic_csv(symbol, "2021-09-30", 548, seed)
        )
    for seed, symbol in enumerate(SHORT.s2_symbols, start=7):
        start = "2022-01-01" if late_coin and symbol == "LTCUSDT" else "2021-09-30"
        (data / f"{symbol}_1d.csv").write_text(synthetic_csv(symbol, start, 548, seed))
    if early:
        for seed, symbol in enumerate(SHORT.s3_symbols, start=3):
            (early_dir / f"{symbol}_1d.csv").write_text(
                synthetic_csv(symbol, "2020-01-01", 640, seed)
            )


def test_protocol_matches_the_preregistration() -> None:
    p = TournamentProtocol()
    described = p.describe()
    assert described["protocol_id"] == "spot-candidate-tournament"
    assert described["version"] == 1
    assert (p.development_start, p.development_end) == ("2021-09-30", "2025-05-11")
    assert (p.seen_start, p.seen_end, p.early_end) == (
        "2025-05-12",
        "2026-11-25",
        "2021-09-29",
    )
    assert p.s2_symbols == (
        "ADAUSDT",
        "DOGEUSDT",
        "LTCUSDT",
        "LINKUSDT",
        "AVAXUSDT",
        "DOTUSDT",
        "TRXUSDT",
        "BCHUSDT",
    )
    assert p.gold_symbol == "PAXGUSDT"
    assert (p.bootstrap_resamples, p.bootstrap_seed, p.candidates_k) == (
        20_000,
        20261127,
        9,
    )
    assert len(TOURNAMENT_CANDIDATES) == p.candidates_k
    # 5% / 9 one-sided: the 0.556th percentile -> sorted index 111 of 20,000.
    assert p.bootstrap_lower_quantile == Decimal("0.05") / 9
    assert int(p.bootstrap_lower_quantile * p.bootstrap_resamples) == 111
    assert (p.min_trades, p.min_early_trades, p.min_gold_trades) == (30, 10, 10)
    assert (p.max_portfolio_drawdown, p.max_symbol_drawdown) == (
        Decimal("0.30"),
        Decimal("0.40"),
    )


def test_bonferroni_percentile_is_the_seeded_sorted_resample() -> None:
    p = replace(TournamentProtocol(), bootstrap_resamples=2000)
    returns = [Decimal(value) / 100 for value in (-3, 5, 2, -1, 4, -2, 1, 6, -4, 3)]
    rng = random.Random(20261127)
    means = sorted(
        sum((returns[rng.randrange(10)] for _ in range(10)), Decimal(0)) / 10
        for _ in range(2000)
    )
    assert bootstrap_lower_bound(returns, p) == means[11]  # int(2000 x 0.05/9)


def _stats(trades: int, expectancy: str | None) -> TradeStats:
    value = None if expectancy is None else Decimal(expectancy)
    return TradeStats(trades, 0, None, value, None, None, None, None)


def _evidence(
    trades: int,
    expectancy: str,
    *,
    ret: str = "0.5",
    dd: str = "0.2",
    hold: tuple[str, str] = ("0.5", "0.5"),
    coin_dd: str = "0.3",
    lower: str | None = None,
) -> dict[str, object]:
    def curve(total: str, drawdown: str) -> CurveStats:
        r, d = Decimal(total), Decimal(drawdown)
        return CurveStats(r, d, r / d if d > 0 else None)

    return {
        "pooled": _stats(trades, expectancy),
        "portfolio": curve(ret, dd),
        "buy_and_hold_portfolio": curve(*hold),
        "per_symbol": {"BTCUSDT": {"strategy_curve": curve(ret, coin_dd)}},
        "bootstrap_lower_bound_mean_return": None if lower is None else Decimal(lower),
    }


def _windows(*expectancies: str | None) -> list[dict[str, object]]:
    return [{"pooled": _stats(5, value)} for value in expectancies]


def test_hurdles_follow_the_preregistered_rules() -> None:
    p = TournamentProtocol()
    good = _windows("0.01", "0.02", "-0.01", "0.03")
    h1, few = hurdle_h1(_evidence(40, "0.01"), good, p)
    assert h1["met"] and not few and h1["positive_windows"] == 3
    h1, _ = hurdle_h1(_evidence(40, "0.01"), _windows("0.01", None, "-0.1", "0.2"), p)
    assert h1["reasons"] == ["TOO_FEW_POSITIVE_WINDOWS: 2 of 4 < 3"]
    h1, _ = hurdle_h1(_evidence(40, "0.01", dd="0.31", coin_dd="0.41"), good, p)
    assert h1["reasons"] == [
        "PORTFOLIO_DRAWDOWN_LIMIT_EXCEEDED",
        "SYMBOL_DRAWDOWN_LIMIT_EXCEEDED: BTCUSDT 41.00%",
    ]
    h1, few = hurdle_h1(_evidence(29, "0.01"), good, p)
    assert few and not h1["met"]
    # Return/DD must be >= buy-and-hold's: 0.5/0.2 = 2.5 < 3/1 = 3.
    h1, _ = hurdle_h1(_evidence(40, "0.01", hold=("3", "1")), good, p)
    assert h1["reasons"] == ["DOES_NOT_BEAT_BUY_AND_HOLD_RISK_ADJUSTED"]

    h2, _ = hurdle_h2(_evidence(40, "0.01", lower="0.001"), p)
    assert h2["met"]
    h2, _ = hurdle_h2(_evidence(40, "0.01", lower="0"), p)
    assert h2["reasons"] == ["BONFERRONI_BOOTSTRAP_LOWER_BOUND_NOT_ABOVE_ZERO"]
    h2, _ = hurdle_h2(_evidence(40, "0.01", lower="0.01", dd="0.35"), p)
    assert "PORTFOLIO_DRAWDOWN_LIMIT_EXCEEDED" in h2["reasons"]

    assert hurdle_h3(_evidence(10, "0.001"), p)["met"]
    assert not hurdle_h3(_evidence(9, "0.001"), p)["met"]
    assert not hurdle_h3(_evidence(12, "-0.001"), p)["met"]

    assert gold_verdict(_evidence(10, "0.01"), p)["status"] == "GOLD_PASS"
    assert gold_verdict(_evidence(9, "0.01"), p)["status"] == "GOLD_INCONCLUSIVE"
    assert gold_verdict(_evidence(10, "-0.01"), p)["status"] == "GOLD_FAIL"


def test_verdict_order() -> None:
    met, missed = {"met": True}, {"met": False}
    assert tournament_verdict(met, met, met, s1_few=False, s2_few=False)["status"] == (
        "TOURNAMENT_PASS"
    )
    assert (
        tournament_verdict(met, met, None, s1_few=False, s2_few=False)["status"]
        == "PROVISIONAL_PASS"
    )
    # INCONCLUSIVE takes precedence over any other failure.
    result = tournament_verdict(missed, met, met, s1_few=False, s2_few=True)
    assert result == {
        "status": "INCONCLUSIVE",
        "reasons": ["FEWER_THAN_30_TRADES_IN: S2"],
    }
    result = tournament_verdict(met, met, missed, s1_few=False, s2_few=False)
    assert result == {"status": "FAIL", "reasons": ["H3_NOT_MET"]}
    result = tournament_verdict(missed, met, None, s1_few=False, s2_few=False)
    assert result == {"status": "FAIL", "reasons": ["H1_NOT_MET"]}


def test_research_only_symbols_never_pass_the_default_parser() -> None:
    document = synthetic_csv("PAXGUSDT", "2021-09-30", 3)
    with pytest.raises(CandleDataError, match="not an approved Spot symbol"):
        parse_candle_csv(document)
    series = parse_candle_csv(document, research_only=True)
    assert series.instrument_id == "PAXG-USDT-SPOT"


def test_end_to_end_report_covers_every_candidate_and_set(tmp_path: Path) -> None:
    write_sets(tmp_path)
    data = load_tournament_data(tmp_path / "data", tmp_path / "early", SHORT)
    assert [item["symbol"] for item in data.s2_excluded] == ["LTCUSDT"]
    assert "starts 2022-01-01" in data.s2_excluded[0]["reason"]
    candidates = (TOURNAMENT_CANDIDATES[0], TOURNAMENT_CANDIDATES[6])
    report = run_tournament(data, protocol=SHORT, candidates=candidates)
    assert report["report_type"] == "SPOT_CANDIDATE_TOURNAMENT"
    assert report["authority"]["execution_authorized"] is False
    assert report["protocol"]["content_sha256"] == SHORT.content_sha256
    assert [row["candidate_id"] for row in report["candidates"]] == ["C1", "C7"]
    for row in report["candidates"]:
        sets = row["sets"]
        assert set(sets) == {
            "S1",
            "S2",
            "S3",
            "S4_informational",
            "S5",
            "S5_seen_informational",
        }
        assert sets["S1"]["symbols"] == list(SHORT.s1_symbols)
        assert sets["S2"]["symbols"] == ["ADAUSDT", "DOGEUSDT"]
        assert sets["S2"]["bootstrap_index"] == 1  # int(300 x 0.05 / 9)
        assert len(sets["S1"]["windows"]) == 4
        assert sets["S3"]["start"].startswith("2020-")
        assert sets["S3"]["end"] == "2021-09-29T00:00:00Z"
        assert sets["S4_informational"]["status"] == "SEEN_INFORMATIONAL"
        assert sets["S4_informational"]["evidence"]["start"] == "2023-01-01T00:00:00Z"
        assert sets["S5"]["symbols"] == ["PAXGUSDT"]
        assert "weekend_entries" in sets["S5"]["weekend_split"]
        assert row["gold_verdict"]["status"].startswith("GOLD_")
        assert row["verdict"]["status"] in (
            "TOURNAMENT_PASS",
            "PROVISIONAL_PASS",
            "INCONCLUSIVE",
            "FAIL",
        )
        for name, result in sets.items():
            evidence = result.get("evidence", result)
            records = evidence["trade_records"]
            assert len(records) == evidence["pooled"]["trades"]
            assert all(trade["set"] == name for trade in records)
            assert {trade["symbol"] for trade in records} <= set(evidence["symbols"])
        if row["candidate_id"] == "C1":
            assert sets["S1"]["trade_records"]
            assert all(
                trade["stop_price"] is None and trade["r_multiple"] is None
                for trade in sets["S1"]["trade_records"]
            )
        # Benchmarks on every judged set.
        for name in ("S1", "S2", "S3", "S5"):
            assert "buy_and_hold_portfolio" in sets[name]
            assert sets[name]["cash"] == {"total_return": "0", "max_drawdown": "0"}
    # C1 warms up for 200 bars: judging starts at index 199 of S1.
    assert report["candidates"][0]["sets"]["S1"]["start"] == "2022-04-17T00:00:00Z"
    # Deterministic: the same inputs give the same report.
    again = run_tournament(data, protocol=SHORT, candidates=candidates)
    assert again["candidates"] == report["candidates"]
    markdown = to_markdown_tournament(report)
    assert "| C1 | sma200-long-cash v1 |" in markdown
    assert "S2 LTCUSDT: EXCLUDED" in markdown
    assert "| S1 | BTCUSDT |" in markdown


def test_s3_unavailable_when_earlier_history_fails_checks(tmp_path: Path) -> None:
    write_sets(tmp_path, early=False)
    (tmp_path / "early" / "BTCUSDT_1d.csv").write_text(
        synthetic_csv("BTCUSDT", "2020-01-01", 640).replace(",1,", ",-1,", 1)
    )
    data = load_tournament_data(tmp_path / "data", tmp_path / "early", SHORT)
    assert data.s3 is None
    assert data.s3_reason is not None and data.s3_reason.startswith("BTCUSDT")
    report = run_tournament(
        data, protocol=SHORT, candidates=(TOURNAMENT_CANDIDATES[0],)
    )
    (row,) = report["candidates"]
    assert row["sets"]["S3"]["status"] == "UNAVAILABLE"
    assert row["verdict"]["status"] != "TOURNAMENT_PASS"
    assert report["datasets"]["S3"]["status"] == "UNAVAILABLE"


def test_missing_s1_coin_fails_closed(tmp_path: Path) -> None:
    write_sets(tmp_path)
    (tmp_path / "data" / "SOLUSDT_1d.csv").unlink()
    with pytest.raises(StudyError, match="S1 SOLUSDT"):
        load_tournament_data(tmp_path / "data", tmp_path / "early", SHORT)


def test_cli_requires_the_preregistered_protocol(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["tournament", "--protocol", "v2", "--out", str(tmp_path)]) == 2
    assert "not pre-registered" in capsys.readouterr().err
    code = main(
        [
            "tournament",
            "--protocol",
            "tournament-v1",
            "--data",
            str(tmp_path / "missing"),
            "--out",
            str(tmp_path),
        ]
    )
    assert code == 2
    assert "S1 BTCUSDT" in capsys.readouterr().err
    assert not list(tmp_path.glob("*.json"))


def test_report_json_is_serialisable(tmp_path: Path) -> None:
    write_sets(tmp_path)
    data = load_tournament_data(tmp_path / "data", tmp_path / "early", SHORT)
    report = run_tournament(
        data,
        protocol=SHORT,
        candidates=(TOURNAMENT_CANDIDATES[7],),
        created_at=datetime(2026, 11, 27, tzinfo=UTC),
    )
    decoded = json.loads(json.dumps(report))
    assert decoded["candidates"][0]["strategy"]["strategy_id"] == "sma200-voltarget"
    assert decoded["protocol"]["bootstrap_lower_quantile"].startswith("0.00555")
