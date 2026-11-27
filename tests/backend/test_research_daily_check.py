"""Focused tests for the daily research check (E2c3).

Every API response here is a SYNTHETIC fake served by an in-memory transport;
none of it is real market data or a real snapshot.
"""

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from trading_platform_api.research import daily_check
from trading_platform_api.research.daily_check import (
    REQUIRED_INDICATORS,
    refresh_body,
    run_daily_check,
    to_markdown,
)

NOW = datetime(2026, 11, 26, 17, 30, 12, tzinfo=UTC)


def synthetic_snapshot(timeframe, *, quality="VALID", overrides=None):
    indicators = {
        name: {"status": "AVAILABLE", "reason_code": None, "result": {}}
        for name in REQUIRED_INDICATORS
    }
    indicators.update(overrides or {})
    return {
        "snapshot_id": "synthetic-snapshot",
        "as_of": "2026-11-26T16:00:00Z",
        "temporal_context": "CURRENT",
        "data_quality": {"status": quality, "report_id": "synthetic-report"},
        "candles": [{}] * 3,
        "indicators": indicators,
    }


FORWARD_RECORD = {
    "stage": "NOT_VALIDATED",
    "reason": "NO_HISTORICAL_VERDICT_RECORDED",
    "forward": {"closed_trades": 0},
}


def covered_history(url):
    """SYNTHETIC historical read that already covers the requested window."""
    as_of = url.split("as_of=")[1].replace("%3A", ":")
    return {
        "data_quality": {"status": "VALID"},
        "candles": [
            {"open_time": "2020-01-01T00:00:00Z", "close_time": "2020-01-02T00:00:00Z"},
            {"open_time": "2020-01-02T00:00:00Z", "close_time": as_of},
        ],
    }


class FakeTransport:
    def __init__(self, responses=None, history_covered=True):
        self.calls = []
        self.responses = responses or {}
        self.history_covered = history_covered

    def __call__(self, method, url, headers, body):
        self.calls.append((method, url, dict(headers), body))
        for fragment, response in self.responses.items():
            if fragment in url:
                status, payload = response
                return status, json.dumps(payload).encode()
        if method == "POST":
            timeframe = json.loads(body)["timeframe"]
            return 200, json.dumps(synthetic_snapshot(timeframe)).encode()
        if "/candles?" in url:
            if self.history_covered:
                return 200, json.dumps(covered_history(url)).encode()
            return 404, b'{"code": "SPOT_SNAPSHOT_NOT_FOUND"}'
        if "/api/research/forward/" in url:
            return 200, json.dumps(FORWARD_RECORD).encode()
        return 200, b'{"items": [], "next_cursor": null}'


def run(transport, sleeps=None):
    return run_daily_check(
        base_url="http://127.0.0.1:5173",
        transport=transport,
        now=lambda: NOW,
        sleep=(sleeps.append if sleeps is not None else lambda _: None),
    )


def test_all_ready_refreshes_every_pair_and_only_reads_otherwise():
    transport = FakeTransport()
    sleeps = []
    results = run(transport, sleeps)

    assert all(item.ready for item in results)
    posts = [call for call in transport.calls if call[0] == "POST"]
    assert [call[1].rsplit("/", 2)[1] for call in posts] == list(
        daily_check.INSTRUMENTS
    ) * 2
    assert all(call[1].endswith("/refresh") for call in posts)
    assert all(call[2]["Origin"] == "http://127.0.0.1:5173" for call in posts)
    gets = [call for call in transport.calls if call[0] == "GET"]
    assert [
        call[1]
        for call in gets
        if "/candles?" not in call[1] and "/forward/" not in call[1]
    ] == [
        "http://127.0.0.1:5173/api/research/decision-journal?limit=20",
        "http://127.0.0.1:5173/api/research/strategy-signals"
        "?contract_id=C-026&schema_version=2&limit=20",
    ]
    assert [call[1] for call in gets if "/forward/" in call[1]] == [
        "http://127.0.0.1:5173/api/research/forward/trend-daily-regime?version=1",
        "http://127.0.0.1:5173/api/research/forward/range-reversion-4h?version=1",
    ]
    assert all("Origin" not in call[2] for call in gets)
    # Only refresh POSTs and reads: nothing else is ever written.
    assert {call[0] for call in transport.calls} == {"POST", "GET"}
    assert len(sleeps) == 9 and all(value >= 1 for value in sleeps)
    one_day = next(
        item for item in results if item.name == "BTC-USDT-SPOT 1d indicators"
    )
    assert one_day.ready and one_day.detail == "all required available"


def test_refresh_window_is_aligned_to_closed_candles_and_bounded():
    four_hour = refresh_body("4h", NOW)
    assert four_hour == {
        "timeframe": "4h",
        "coverage_start": "2026-09-04T04:00:00Z",
        "coverage_end": "2026-11-26T16:00:00Z",
        "limit": 501,
    }
    # 1d is bounded by candle count: 501 daily candles (enough for SMA200 and
    # EMA500), not the 90-day window used below 1d.
    one_day = refresh_body("1d", NOW)
    assert one_day == {
        "timeframe": "1d",
        "coverage_start": "2025-07-13T00:00:00Z",
        "coverage_end": "2026-11-26T00:00:00Z",
        "limit": 501,
    }


@pytest.mark.parametrize(
    ("responses", "failed", "detail"),
    [
        (
            {
                "SOL-USDT-SPOT/refresh": (
                    503,
                    {"code": "PROVIDER_UNAVAILABLE", "title": "Provider down"},
                )
            },
            ["SOL-USDT-SPOT 4h refresh", "SOL-USDT-SPOT 1d refresh"],
            "HTTP 503 (PROVIDER_UNAVAILABLE; Provider down)",
        ),
        (
            {"decision-journal": (421, {"title": "Local access required"})},
            ["decision journal read"],
            "HTTP 421 (Local access required)",
        ),
        (
            {"strategy-signals": (500, {})},
            ["strategy-signal read"],
            "HTTP 500",
        ),
    ],
)
def test_http_failures_are_problems(responses, failed, detail):
    results = run(FakeTransport(responses))
    problems = [item for item in results if not item.ready]
    assert [item.name for item in problems] == failed
    assert all(item.detail == detail for item in problems)


def test_stale_quality_and_missing_indicator_are_problems():
    stale = synthetic_snapshot("4h", quality="STALE")
    warm = synthetic_snapshot(
        "4h",
        overrides={
            "rsi-14": {"status": "UNAVAILABLE", "reason_code": "X", "result": None}
        },
    )
    results = run(
        FakeTransport(
            {
                "BTC-USDT-SPOT/refresh": (200, stale),
                "ETH-USDT-SPOT/refresh": (200, warm),
            }
        )
    )
    problems = {item.name: item.detail for item in results if not item.ready}
    assert set(problems) == {
        "BTC-USDT-SPOT 4h quality",
        "BTC-USDT-SPOT 1d quality",
        "ETH-USDT-SPOT 4h indicators",
        "ETH-USDT-SPOT 1d indicators",
    }
    assert problems["BTC-USDT-SPOT 4h quality"].startswith("quality STALE")
    assert problems["ETH-USDT-SPOT 4h indicators"] == "rsi-14 UNAVAILABLE (X)"


def test_ema_500_is_required_on_4h_and_1d():
    # A 501-candle refresh warms up EMA 500 on both timeframes (E2e2).
    cold = synthetic_snapshot(
        "4h",
        overrides={
            "ema-500": {
                "status": "WARMUP",
                "reason_code": "INSUFFICIENT_WARMUP",
                "result": None,
            }
        },
    )
    results = run(FakeTransport({"XRP-USDT-SPOT/refresh": (200, cold)}))
    problems = [item.name for item in results if not item.ready]
    assert problems == ["XRP-USDT-SPOT 4h indicators", "XRP-USDT-SPOT 1d indicators"]


def test_unreachable_api_is_a_problem_not_a_crash():
    def transport(method, url, headers, body):
        raise ConnectionRefusedError("connection refused")

    results = run(transport)
    assert results and not any(item.ready for item in results)
    assert results[0].detail.startswith("unreachable")


def test_report_and_cli_exit_code(tmp_path: Path, monkeypatch):
    from trading_platform_api.research.__main__ import main

    responses = {"strategy-signals": (500, {})}
    monkeypatch.setattr(
        daily_check,
        "run_daily_check",
        lambda base_url: run(FakeTransport(responses)),
    )
    assert main(["daily-check", "--out", str(tmp_path)]) == 1
    [report] = tmp_path.glob("daily-check-*.md")
    text = report.read_text("utf-8")
    assert "Overall: **PROBLEM** (1 problem(s), 34 checks)" in text
    assert "| strategy-signal read | PROBLEM | HTTP 500 |" in text
    assert "no decision, journal entry, outcome or order was recorded" in text

    monkeypatch.setattr(
        daily_check, "run_daily_check", lambda base_url: run(FakeTransport())
    )
    assert main(["daily-check", "--out", str(tmp_path)]) == 0
    assert "Overall: **READY**" in report.read_text("utf-8")


def test_markdown_escapes_pipes():
    text = to_markdown(
        [daily_check.CheckResult("x", False, "a|b")],
        generated_at=NOW,
        base_url="http://127.0.0.1:5173",
    )
    assert "| x | PROBLEM | a\\|b |" in text


def test_backfill_windows_are_fixed_and_bounded():
    # Strategy A (1d) warms up from 2026-05-10, inside the current 501-candle
    # 1d refresh (from 2025-07-13), so nothing needs backfilling.
    assert (
        daily_check.backfill_windows("1d", datetime(2026, 5, 10, tzinfo=UTC), NOW) == []
    )
    # An earlier start is backfilled in fixed 501-candle windows.
    assert daily_check.backfill_windows(
        "1d", datetime(2024, 1, 1, tzinfo=UTC), NOW
    ) == [
        (datetime(2024, 1, 1, tzinfo=UTC), datetime(2025, 5, 16, tzinfo=UTC)),
        (datetime(2025, 5, 16, tzinfo=UTC), datetime(2025, 7, 13, tzinfo=UTC)),
    ]
    # Strategy B (4h) is still inside the current 501-candle refresh.
    start_b = datetime(2026, 11, 21, 12, tzinfo=UTC)
    assert daily_check.backfill_windows("4h", start_b, NOW) == []
    later = datetime(2027, 3, 1, tzinfo=UTC)
    windows = daily_check.backfill_windows("4h", start_b, later)
    assert windows[0][0] == start_b
    assert all(b - a <= timedelta(days=80) for a, b in windows)
    assert all(a == b for (_, a), (b, _) in zip(windows, windows[1:]))


def test_missing_history_is_backfilled_and_forward_stage_reported(monkeypatch):
    # SYNTHETIC: pretend Strategy A warms up from 2024-01-01 so 1d history
    # falls outside the current 501-candle refresh.
    real_start = daily_check.history_start
    monkeypatch.setattr(
        daily_check,
        "history_start",
        lambda strategy: (
            datetime(2024, 1, 1, tzinfo=UTC)
            if strategy.strategy_id == "trend-daily-regime"
            else real_start(strategy)
        ),
    )
    transport = FakeTransport(history_covered=False)
    results = run(transport)
    backfills = [
        json.loads(call[3])
        for call in transport.calls
        if call[0] == "POST" and json.loads(call[3])["coverage_end"] < "2026-11"
    ]
    assert len(backfills) == 2 * len(daily_check.INSTRUMENTS)
    assert {
        (b["coverage_start"], b["coverage_end"], b["limit"]) for b in backfills
    } == {
        ("2024-01-01T00:00:00Z", "2025-05-16T00:00:00Z", 501),
        ("2025-05-16T00:00:00Z", "2025-07-13T00:00:00Z", 58),
    }
    stage = next(i for i in results if i.name == "forward stage trend-daily-regime v1")
    assert stage.ready and stage.detail.startswith("NOT_VALIDATED")
    assert all(item.ready for item in results)


def test_forward_stage_failure_is_a_problem():
    responses = {
        "forward/range-reversion-4h": (422, {"code": "FORWARD_HISTORY_INSUFFICIENT"})
    }
    results = run(FakeTransport(responses))
    failed = [item for item in results if not item.ready]
    assert [item.name for item in failed] == ["forward stage range-reversion-4h v1"]
    assert "FORWARD_HISTORY_INSUFFICIENT" in failed[0].detail
