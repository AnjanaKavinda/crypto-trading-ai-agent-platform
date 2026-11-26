"""Focused tests for C-109 study verdict import (E2f2 part 2, #558).

The report documents here are SYNTHETIC; no real study result is represented.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal
from hashlib import sha256
from pathlib import Path

import pytest
from trading_platform_api.research.__main__ import record_verdict
from trading_platform_api.research.evaluation import WalkForwardProtocol
from trading_platform_api.research.strategy import RangeReversion4h, TrendDailyRegime
from trading_platform_api.research.study_verdict import (
    StudyVerdictRecord,
    verdict_record_from_report,
)

NOW = datetime(2026, 11, 27, tzinfo=UTC)
DIGEST = "a" * 64


def report(strategy=None, timeframe: str = "1d", **changes: object) -> dict:
    strategy = strategy or TrendDailyRegime()
    protocol = WalkForwardProtocol()
    base = {
        "report_type": "LEAN_SPOT_WALK_FORWARD_STUDY",
        "created_at": "2026-11-26T20:00:00Z",
        "stage": "HISTORICAL",
        "strategy": {**strategy.describe(), "content_sha256": strategy.content_sha256},
        "protocol": {**protocol.describe(), "content_sha256": protocol.content_sha256},
        "datasets": [
            {"symbol": "BTCUSDT", "timeframe": timeframe, "content_sha256": DIGEST},
            {"symbol": "ETHUSDT", "timeframe": timeframe, "content_sha256": "b" * 64},
        ],
        "verdict": {"status": "FAIL", "reasons": ["DOES_NOT_BEAT_CASH"]},
        "development_era_evidence": {"portfolio": {"max_drawdown": "0.41"}},
    }
    base.update(changes)
    return base


def test_report_becomes_an_append_only_verdict_record() -> None:
    record = verdict_record_from_report(report(), report_sha256=DIGEST, recorded_at=NOW)
    assert type(record) is StudyVerdictRecord
    assert (record.contract_id, record.schema_version) == ("C-109", "1")
    assert record.strategy_id == "trend-daily-regime"
    assert record.verdict_status == "FAIL"
    assert record.verdict_reasons == ("DOES_NOT_BEAT_CASH",)
    assert record.development_max_drawdown == Decimal("0.41")
    assert [item.symbol for item in record.datasets] == ["BTCUSDT", "ETHUSDT"]
    assert not (
        record.qualification_authorized
        or record.approval_authorized
        or record.execution_authorized
    )
    # Identity follows the report bytes, so an identical re-import is idempotent.
    later = verdict_record_from_report(
        report(), report_sha256=DIGEST, recorded_at=datetime(2027, 1, 1, tzinfo=UTC)
    )
    assert later.verdict_id == record.verdict_id
    assert later.content_sha256 != record.content_sha256
    assert record.historical().status == "FAIL"
    b = RangeReversion4h()
    four_hour = verdict_record_from_report(
        report(b, "4h"), report_sha256="c" * 64, recorded_at=NOW
    )
    assert four_hour.strategy_sha256 == b.content_sha256


@pytest.mark.parametrize(
    ("document", "match"),
    [
        (report(timeframe="4h"), "not all 1d"),
        (report(datasets=[]), "datasets"),
        (report(created_at=None), "creation time"),
        (report(protocol={"content_sha256": "x"}), "protocol digest"),
        (report(verdict=None), "historical verdict"),
        (report(strategy=None) | {"strategy": {"strategy_id": "x"}}, "registered"),
    ],
)
def test_malformed_or_mismatched_reports_fail_closed(document, match) -> None:
    with pytest.raises(ValueError, match=match):
        verdict_record_from_report(document, report_sha256=DIGEST, recorded_at=NOW)
    with pytest.raises(ValueError, match="SHA-256"):
        verdict_record_from_report(report(), report_sha256="nope", recorded_at=NOW)


def test_cli_posts_the_exact_report_bytes(tmp_path: Path, capsys) -> None:
    path = tmp_path / "study.json"
    path.write_text(json.dumps(report()), encoding="utf-8")
    calls = []

    def transport(method, url, headers, body):
        calls.append((method, url, dict(headers), body))
        result = {
            "strategy_id": "trend-daily-regime",
            "strategy_version": "1",
            "verdict_status": "FAIL",
            "report_sha256": sha256(body).hexdigest(),
        }
        return 200, json.dumps(result).encode()

    assert (
        record_verdict(path, base_url="http://127.0.0.1:5173/", transport=transport)
        == 0
    )
    method, url, headers, body = calls[0]
    assert (method, url) == (
        "POST",
        "http://127.0.0.1:5173/api/research/forward/verdicts",
    )
    assert headers["Origin"] == "http://127.0.0.1:5173"
    assert body == path.read_bytes()
    assert "trend-daily-regime v1: FAIL" in capsys.readouterr().out

    def rejected(method, url, headers, body):
        return 422, b'{"code":"FORWARD_REPORT_REJECTED","detail":"digest"}'

    assert record_verdict(path, base_url="http://x", transport=rejected) == 1
    assert "HTTP 422 digest" in capsys.readouterr().err

    def down(method, url, headers, body):
        raise OSError("refused")

    assert record_verdict(path, base_url="http://x", transport=down) == 1
    assert record_verdict(tmp_path / "missing.json", base_url="http://x") == 2
