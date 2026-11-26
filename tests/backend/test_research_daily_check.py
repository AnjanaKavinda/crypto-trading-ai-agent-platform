"""Focused tests for the daily research check (E2c3).

Every API response here is a SYNTHETIC fake served by an in-memory transport;
none of it is real market data or a real snapshot.
"""

import json
from datetime import UTC, datetime
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
    if timeframe == "1d":
        indicators["ema-500"] = {
            "status": "WARMUP",
            "reason_code": "INSUFFICIENT_WARMUP",
            "result": None,
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


class FakeTransport:
    def __init__(self, responses=None):
        self.calls = []
        self.responses = responses or {}

    def __call__(self, method, url, headers, body):
        self.calls.append((method, url, dict(headers), body))
        for fragment, response in self.responses.items():
            if fragment in url:
                status, payload = response
                return status, json.dumps(payload).encode()
        if method == "POST":
            timeframe = json.loads(body)["timeframe"]
            return 200, json.dumps(synthetic_snapshot(timeframe)).encode()
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
    assert [call[1] for call in gets] == [
        "http://127.0.0.1:5173/api/research/decision-journal?limit=20",
        "http://127.0.0.1:5173/api/research/strategy-signals"
        "?contract_id=C-026&schema_version=2&limit=20",
    ]
    assert all("Origin" not in call[2] for call in gets)
    # Only refresh POSTs and reads: nothing else is ever written.
    assert {call[0] for call in transport.calls} == {"POST", "GET"}
    assert len(sleeps) == 9 and all(value >= 1 for value in sleeps)
    one_day = next(
        item for item in results if item.name == "BTC-USDT-SPOT 1d indicators"
    )
    assert "ema-500 WARMUP" in one_day.detail and "not required on 1d" in one_day.detail


def test_refresh_window_is_aligned_to_closed_candles_and_bounded():
    four_hour = refresh_body("4h", NOW)
    assert four_hour == {
        "timeframe": "4h",
        "coverage_start": "2026-09-04T04:00:00Z",
        "coverage_end": "2026-11-26T16:00:00Z",
        "limit": 501,
    }
    one_day = refresh_body("1d", NOW)
    assert one_day["coverage_end"] == "2026-11-26T00:00:00Z"
    assert one_day["coverage_start"] == "2026-08-28T00:00:00Z"
    assert one_day["limit"] == 90


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


def test_ema_500_is_required_on_4h():
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
    assert problems == ["XRP-USDT-SPOT 4h indicators"]


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
    assert "Overall: **PROBLEM** (1 problem(s), 32 checks)" in text
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
