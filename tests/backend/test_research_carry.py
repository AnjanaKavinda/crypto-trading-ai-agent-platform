"""SYNTHETIC carry examples; no network, database, or real strategy results."""

import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal, localcontext

import pytest
from test_research_futures_data import synthetic_client
from trading_platform_api.research import carry
from trading_platform_api.research.__main__ import main
from trading_platform_api.research.candles import Candle, format_candle_csv
from trading_platform_api.research.carry_inputs import (
    CarryData,
    MarginSchedule,
    MarginTier,
    load_carry_data,
    load_margin_schedule,
)
from trading_platform_api.research.evaluation import CurveStats
from trading_platform_api.research.futures_data import (
    fetch_futures_data,
    format_dataset,
)
from trading_platform_api.research.report import StudyError

D = Decimal
START = datetime(2024, 1, 1, tzinfo=UTC)
HOUR = timedelta(hours=1)


def synthetic_data(*, rates=None, count=37, basis_hour=None, liquidation_hour=None):
    bars = tuple(
        Candle(START + i * HOUR, D(100), D(100), D(100), D(100), D(1))
        for i in range(count)
    )
    perp = list(bars)
    mark = list(bars)
    if basis_hour is not None:
        perp[basis_hour] = replace(perp[basis_hour], close=D(103), high=D(103))
    if liquidation_hour is not None:
        mark[liquidation_hour] = replace(mark[liquidation_hour], high=D(201))
    funding_times = range(0, count, 8)
    rates = rates or [D("0.0002")] * len(funding_times)
    return CarryData(
        "BTCUSDT",
        bars,
        tuple(perp),
        tuple(mark),
        tuple(
            (START + i * HOUR, rate)
            for i, rate in zip(funding_times, rates, strict=True)
        ),
        {k: "a" * 64 for k in ("spot", "klines", "premium", "funding", "mark")},
    )


def synthetic_margins():
    return MarginSchedule(
        "https://example.invalid/SYNTHETIC",
        START,
        (
            MarginTier(
                "BTCUSDT",
                START,
                START + timedelta(days=10),
                D(0),
                D(1000000),
                D("0.005"),
                D(0),
            ),
        ),
        "b" * 64,
    )


def test_golden_next_open_costs_funding_and_cash_reconciliation():
    result = carry.simulate(synthetic_data(), synthetic_margins(), D(1000))
    (episode,) = result.episodes
    assert episode.entry_time == START + 17 * HOUR
    assert episode.exit_time == START + 37 * HOUR
    assert episode.spot_entry == D("100.0500")
    assert episode.perp_entry == D("99.9500")
    assert episode.spot_exit == D("99.9500")
    assert episode.perp_exit == D("100.0500")
    with localcontext() as context:
        context.prec = 40
        n = D(1000) / D("2.0015")
        qs, qp = n / D("100.05"), n / D("99.95")
        # No funding at 00/08/16: the position did not exist before settlement.
        funding = D(2) * D("0.0002") * qp * D(100)
        fees = (
            n * D("0.0015")
            + qs * D("99.95") * D("0.001")
            + qp * D("100.05") * D("0.0005")
        )
        basis = qs * D("-0.10") + qp * D("-0.10")
        assert abs(episode.funding - funding) < D("1e-30")
        assert abs(episode.fees - fees) < D("1e-30")
        assert abs(episode.net - (basis + funding - fees)) < D("1e-30")
        assert abs(result.equity[-1] - (1 + episode.net / 1000)) < D("1e-30")
    assert episode.slippage > 0
    assert episode.exit_reason == "END_OF_SET"


def test_negative_funding_is_paid_then_exit_at_next_open():
    rates = [D("0.0002")] * 3 + [D("-0.001"), D("-0.001")]
    result = carry.simulate(synthetic_data(rates=rates), synthetic_margins(), D(1000))
    (episode,) = result.episodes
    assert episode.exit_time == START + 25 * HOUR
    assert episode.exit_reason == "FUNDING_EXIT" and episode.funding < 0


def test_basis_stop_and_mark_high_liquidation():
    (episode,) = carry.simulate(
        synthetic_data(basis_hour=18, count=23), synthetic_margins(), D(1000)
    ).episodes
    assert (
        episode.exit_reason == "BASIS_STOP" and episode.exit_time == START + 19 * HOUR
    )
    result = carry.simulate(
        synthetic_data(liquidation_hour=18, count=23), synthetic_margins(), D(1000)
    )
    (episode,) = result.episodes
    assert (
        episode.exit_reason == "LIQUIDATION" and episode.exit_time == START + 19 * HOUR
    )
    assert episode.perp_exit is None
    assert episode.net < -episode.notional_per_leg
    assert D("0.49") < result.equity[-1] < D("0.50")


def test_naive_baseline_stays_open_ignoring_funding_and_basis_exits():
    data = synthetic_data(basis_hour=18, rates=[D("-0.001")] * 5)
    strategy = carry.simulate(data, synthetic_margins(), D(1000))
    assert not strategy.episodes
    naive = carry.simulate(data, synthetic_margins(), D(1000), always_on=True)
    (episode,) = naive.episodes
    assert episode.entry_time == START and episode.exit_reason == "END_OF_SET"
    assert episode.funding < 0
    assert len(naive.buy_and_hold) == len(naive.equity) == 38


def test_liquidation_loses_margin_including_credited_funding():
    result = carry.simulate(
        synthetic_data(liquidation_hour=30, count=31), synthetic_margins(), D(1000)
    )
    (episode,) = result.episodes
    assert episode.funding > 0 and episode.exit_reason == "LIQUIDATION"
    assert episode.net < -episode.notional_per_leg
    assert D("0.49") < result.equity[-1] < D("0.50")


def test_equal_windows_and_deterministic_simulation():
    data = synthetic_data()
    first = carry.simulate(data, synthetic_margins(), D(1000))
    assert first == carry.simulate(data, synthetic_margins(), D(1000))
    summary = carry.set_summary([first], [first], development=True)
    assert [(w["start_bar"], w["end_bar_exclusive"]) for w in summary["windows"]] == [
        (0, 9),
        (9, 18),
        (18, 27),
        (27, 37),
    ]
    assert summary["windows"][0]["start"] == START
    assert summary["windows"][-1]["end_exclusive"] == START + 37 * HOUR


def synthetic_summary():
    return {
        "status": "AVAILABLE",
        "episode_count": 20,
        "days_in_position": D(365),
        "portfolio": CurveStats(D("0.1"), D("0.05"), D(2)),
        "naive_carry": CurveStats(D("0.05"), D("0.05"), D(1)),
        "bootstrap_lower_bound": D("0.001"),
        "positive_windows": 3,
    }


@pytest.mark.parametrize(
    "change", ["net", "dd", "ratio", "bootstrap", "windows", "unseen"]
)
def test_each_verdict_failure(change):
    dev, held, unseen = synthetic_summary(), synthetic_summary(), synthetic_summary()
    if change == "net":
        held["portfolio"] = CurveStats(D(0), D("0.05"), D(0))
    elif change == "dd":
        held["portfolio"] = CurveStats(D("0.1"), D("0.11"), D(1))
    elif change == "ratio":
        dev["naive_carry"] = CurveStats(D(1), D("0.01"), D(100))
    elif change == "bootstrap":
        dev["bootstrap_lower_bound"] = D(0)
    elif change == "windows":
        dev["positive_windows"] = 2
    else:
        unseen["portfolio"] = CurveStats(D(0), D(0), None)
    assert carry.verdict(dev, held, unseen)["status"] == "FAIL"


def test_pass_inconclusive_and_unavailable_verdicts():
    summaries = [synthetic_summary() for _ in range(3)]
    assert carry.verdict(*summaries)["status"] == "PASS"
    for index, key, value in (
        (0, "episode_count", 19),
        (0, "days_in_position", D(364)),
        (1, "episode_count", 9),
    ):
        altered = [synthetic_summary() for _ in range(3)]
        altered[index][key] = value
        assert carry.verdict(*altered)["status"] == "INCONCLUSIVE"
    summaries[2]["status"] = "UNAVAILABLE"
    assert carry.verdict(*summaries)["status"] == "UNAVAILABLE"


def test_holdout_requires_development_written_and_is_once_across_output_paths(
    tmp_path, monkeypatch
):
    binding = {"capital_usdt": D(1000), "protocol_sha256": "x"}
    report_path = tmp_path / "report.json"
    calls = []
    monkeypatch.setattr(
        carry,
        "evaluate_set",
        lambda *a, **k: calls.append(a) or {"status": "AVAILABLE"},
    )
    with pytest.raises(OSError):
        carry.evaluate_holdout_once(
            tmp_path / "data", report_path, binding, None, D(1000)
        )
    dev = {"status": "AVAILABLE", "dataset_sha256": "SYNTHETIC"}
    carry._write_json(
        report_path,
        {"binding": binding, "development": dev, "development_sha256": "wrong"},
    )
    with pytest.raises(StudyError, match="Development"):
        carry.evaluate_holdout_once(
            tmp_path / "data", report_path, binding, None, D(1000)
        )
    carry._write_json(
        report_path,
        {
            "binding": binding,
            "development": dev,
            "development_sha256": carry.digest(dev),
        },
    )
    carry.evaluate_holdout_once(tmp_path / "data", report_path, binding, None, D(1000))
    second = tmp_path / "different-out.json"
    second.write_bytes(report_path.read_bytes())
    with pytest.raises(StudyError, match="already claimed"):
        carry.evaluate_holdout_once(tmp_path / "data", second, binding, None, D(1000))
    assert len(calls) == 1


def test_missing_inputs_write_unavailable_report_without_holdout_access(tmp_path):
    report = carry.run_carry_study(tmp_path / "data", tmp_path / "out", D(1000), None)
    assert report["verdict"]["status"] == "UNAVAILABLE"
    assert not (tmp_path / "data" / ".futures-carry-v1-holdout.claim.json").exists()
    raw = (tmp_path / "out" / "futures-carry-v1.json").read_bytes()
    assert b"\r\n" not in raw
    decoded = json.loads(raw)
    recorded = decoded.pop("report_sha256")
    assert recorded == carry.digest(decoded)
    assert (tmp_path / "out" / "futures-carry-v1.md").is_file()
    assert (
        main(
            [
                "carry",
                "--protocol",
                "futures-carry-v1",
                "--capital",
                "NaN",
                "--out",
                str(tmp_path / "bad"),
            ]
        )
        == 2
    )


def synthetic_tier_file(tmp_path):
    path = tmp_path / "tiers.json"
    path.write_text(
        json.dumps(
            {
                "source": "https://example.invalid/SYNTHETIC",
                "retrieved_at": START.isoformat(),
                "tiers": [
                    {
                        "symbol": "BTCUSDT",
                        "effective_from": START.isoformat(),
                        "effective_until": (START + timedelta(days=10)).isoformat(),
                        "notional_floor": "0",
                        "notional_cap": "1000000",
                        "maintenance_rate": "0.005",
                        "maintenance_amount": "0",
                    }
                ],
            }
        )
    )
    return path


def test_sourced_tiers_require_effective_coverage_and_reject_overlap(tmp_path):
    path = synthetic_tier_file(tmp_path)
    schedule = load_margin_schedule(path)
    assert schedule.maintenance("BTCUSDT", START, D(1000)) == D(5)
    with pytest.raises(StudyError, match="unavailable"):
        schedule.maintenance("BTCUSDT", START - HOUR, D(1000))
    body = json.loads(path.read_text())
    body["tiers"] *= 2
    path.write_text(json.dumps(body))
    with pytest.raises(StudyError, match="Overlapping"):
        load_margin_schedule(path)


def test_public_mark_fetch_is_opt_in_and_roundtrip_loader(tmp_path):
    with synthetic_client() as client:
        documents = fetch_futures_data(
            symbol="BTCUSDT",
            start=START,
            now=START + 16 * HOUR,
            client=client,
            pause_seconds=0,
            include_mark=True,
        )
    assert set(documents) == {"spot", "klines", "premium", "funding", "mark"}
    for kind, document in documents.items():
        directory = tmp_path / ("spot" if kind == "spot" else "um-futures")
        directory.mkdir(exist_ok=True)
        interval = "8h" if kind == "funding" else "1h"
        name = "BTCUSDT_1h.csv" if kind == "spot" else f"BTCUSDT_{kind}_{interval}.csv"
        (directory / name).write_text(document, encoding="utf-8", newline="\n")
    data = load_carry_data(tmp_path, "BTCUSDT", START, START + 16 * HOUR)
    assert len(data.mark) == len(data.spot) == 16 and len(data.funding) == 2
    mark_path = tmp_path / "um-futures" / "BTCUSDT_mark_1h.csv"
    mark_path.write_bytes(mark_path.read_bytes().replace(b"100", b"101", 1))
    with pytest.raises(StudyError, match="SHA256"):
        load_carry_data(tmp_path, "BTCUSDT", START, START + 16 * HOUR)


def test_synthetic_full_runner_writes_development_before_holdout(tmp_path, monkeypatch):
    # Shortened dates ONLY in this labelled synthetic test; CLI has no override.
    protocol = replace(
        carry.PROTOCOL,
        development_start="2024-01-01",
        development_end_exclusive="2024-01-03",
        holdout_start="2024-01-03",
        holdout_end_exclusive="2024-01-05",
    )
    monkeypatch.setattr(carry, "PROTOCOL", protocol)
    directory, out = tmp_path / "data", tmp_path / "out"
    symbols = (*protocol.development_symbols, *protocol.unseen_symbols)
    fetched = START + 97 * HOUR
    rows = [
        [
            str(int((START + i * HOUR).timestamp() * 1000)),
            "100",
            "100",
            "100",
            "100",
            "1",
            str(int((START + (i + 1) * HOUR).timestamp() * 1000) - 1),
        ]
        for i in range(96)
    ]
    for symbol in symbols:
        for kind in ("spot", "klines", "premium", "funding", "mark"):
            folder = directory / ("spot" if kind == "spot" else "um-futures")
            folder.mkdir(parents=True, exist_ok=True)
            interval = "8h" if kind == "funding" else "1h"
            name = (
                f"{symbol}_1h.csv"
                if kind == "spot"
                else f"{symbol}_{kind}_{interval}.csv"
            )
            if kind == "spot":
                document = format_candle_csv(
                    source="SYNTHETIC",
                    symbol=symbol,
                    timeframe="1h",
                    fetched_at=fetched,
                    rows=[tuple(row) for row in rows],
                )
            else:
                values = (
                    [[row[0], "0.0002"] for row in rows[::8]]
                    if kind == "funding"
                    else rows
                )
                document = format_dataset(
                    values, symbol=symbol, dataset=kind, fetched_at=fetched
                )
            (folder / name).write_text(document, encoding="utf-8", newline="\n")
    margin_path = synthetic_tier_file(tmp_path)
    table = json.loads(margin_path.read_text())
    table["tiers"] = [dict(table["tiers"][0], symbol=symbol) for symbol in symbols]
    margin_path.write_text(json.dumps(table))
    original = carry.evaluate_set
    calls = []

    def checked(*args, **kwargs):
        if args[4] == carry.day(protocol.holdout_start):
            recorded = json.loads((out / "futures-carry-v1.json").read_text())
            assert recorded["development_sha256"] == carry.digest(
                recorded["development"]
            )
            assert "holdout" not in recorded
            assert (directory / ".futures-carry-v1-holdout.claim.json").exists()
            calls.append("holdout")
        return original(*args, **kwargs)

    monkeypatch.setattr(carry, "evaluate_set", checked)
    report = carry.run_carry_study(directory, out, D(1000), margin_path)
    assert calls == ["holdout"]
    assert report["verdict"]["status"] == "INCONCLUSIVE"
    assert all(
        report[key]["status"] == "AVAILABLE"
        for key in ("development", "holdout", "unseen")
    )
    assert (
        len(report["development"]["datasets"]) == 2
        and len(report["unseen"]["datasets"]) == 3
    )
    markdown = (out / "futures-carry-v1.md").read_text("utf-8")
    assert all(
        name in markdown
        for name in ("naive_carry", "buy_and_hold", "windows", "funding", "slippage")
    )
    with pytest.raises(StudyError, match="already claimed"):
        carry.run_carry_study(
            directory, tmp_path / "different-out", D(1000), margin_path
        )
