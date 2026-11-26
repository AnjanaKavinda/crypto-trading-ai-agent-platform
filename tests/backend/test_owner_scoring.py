"""E4 owner-results protocol v1 scoring.

All fills below are SYNTHETIC test fixtures, not market or account data.
"""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

from fastapi.testclient import TestClient
from trading_platform_api.config import (
    AppSettings,
    DeploymentEnvironment,
    OperatingMode,
)
from trading_platform_api.learning.owner_scoring import (
    OwnerResultsProtocol,
    score_owner_results,
)
from trading_platform_api.learning.trade_outcome import OwnerFill, OwnerTradeOutcome
from trading_platform_api.main import create_app
from trading_platform_api.strategy.contracts import VersionReference

T0 = datetime(2026, 1, 1, tzinfo=UTC)


def trade(day: int, buy: str, sell: str, fee: str | None = "0", *, sold: str = "1"):
    fills = (
        OwnerFill(
            "BUY",
            Decimal(1),
            Decimal(buy),
            T0 + timedelta(days=day),
            "STATEMENT",
            Decimal(0),
        ),
        OwnerFill(
            "SELL",
            Decimal(sold),
            Decimal(sell),
            T0 + timedelta(days=day, hours=1),
            "STATEMENT" if fee is not None else "UNKNOWN",
            None if fee is None else Decimal(fee),
        ),
    )
    return OwnerTradeOutcome(
        request_id=uuid4(),
        request_sha256="a" * 64,
        journal_entry=VersionReference("C-107", uuid4(), "1", "b" * 64),
        journal_recorded_at=T0 + timedelta(days=day),
        instrument_id="BTC-USDT-SPOT",
        fills=fills,
        recorded_at=T0 + timedelta(days=400),
    )


def test_small_sample_is_inconclusive_with_exact_stats():
    outcomes = [trade(0, "100", "110"), trade(1, "100", "95", fee="1")]
    result = score_owner_results(outcomes)
    assert result["verdict"] == {
        "status": "INCONCLUSIVE",
        "reasons": ["INSUFFICIENT_SAMPLE: 2 closed trades < 30"],
    }
    stats = result["trades"]
    # Net returns: +10/100 = 0.1 and (-5 - 1)/100 = -0.06.
    assert [item["net_return"] for item in stats["items"]] == ["0.1", "-0.06"]
    assert stats["expectancy"] == "0.02"
    assert stats["win_rate"] == "0.5"
    assert Decimal(stats["profit_factor"]) == Decimal("0.1") / Decimal("0.06")
    # Equity 1.1 then 1.1 x 0.94 = 1.034; drawdown 0.06 from the 1.1 peak.
    assert stats["total_return"] == "0.034"
    assert stats["max_drawdown"] == "0.06"
    assert stats["net_result_usdt"] == "4"
    assert result["baselines"]["CASH"]["total_return"] == "0"
    assert result["baselines"]["BUY_AND_HOLD"]["status"] == "UNAVAILABLE"
    assert result["no_trade_decisions"]["horizon_days"] == 7
    assert result["execution_authorized"] is False


def test_open_unknown_fee_and_superseded_outcomes_are_not_scored():
    original = trade(0, "100", "90")
    corrected = replace(
        trade(0, "100", "120"),
        supersedes=VersionReference(
            "C-108", original.outcome_id, "1", original.content_sha256
        ),
        correction_reason="Wrong sell price",
    )
    open_position = trade(1, "100", "100", sold="0.5")
    unknown_fee = trade(2, "100", "105", fee=None)
    result = score_owner_results([original, corrected, open_position, unknown_fee])
    stats = result["trades"]
    assert [item["outcome_id"] for item in stats["items"]] == [
        str(corrected.outcome_id)
    ]
    assert {item["reason"] for item in stats["excluded"]} == {
        "POSITION_OPEN",
        "FEE_UNKNOWN",
    }


def test_fail_and_pass_rules_apply_at_the_sample_minimum():
    protocol = OwnerResultsProtocol(min_trades=4, bootstrap_resamples=200)
    losing = [trade(day, "100", "90" if day % 2 else "105") for day in range(4)]
    failed = score_owner_results(losing, protocol)["verdict"]
    assert failed["status"] == "FAIL"
    assert "NON_POSITIVE_EXPECTANCY_AFTER_FEES" in failed["reasons"]
    assert "DOES_NOT_BEAT_CASH" in failed["reasons"]
    winning = [trade(day, "100", "104" if day != 2 else "99") for day in range(4)]
    assert score_owner_results(winning, protocol)["verdict"] == {
        "status": "PASS",
        "reasons": [],
    }
    blocked = score_owner_results(
        [*winning, trade(9, "100", "101", fee=None)], protocol
    )
    assert blocked["verdict"]["status"] == "INCONCLUSIVE"
    assert blocked["verdict"]["reasons"] == ["FEE_UNKNOWN_TRADES_PRESENT: 1"]


def test_protocol_digest_is_stable_and_versioned():
    protocol = OwnerResultsProtocol()
    assert protocol.describe()["version"] == 1
    assert protocol.content_sha256 == OwnerResultsProtocol().content_sha256
    assert OwnerResultsProtocol(min_trades=31).content_sha256 != protocol.content_sha256


class _Outcomes:
    def __init__(self, outcomes):
        self.outcomes = outcomes

    async def all_outcomes(self):
        return self.outcomes


def test_score_endpoint_reads_all_outcomes_and_is_not_an_outcome_id():
    app = create_app(
        settings=AppSettings(DeploymentEnvironment.TEST, OperatingMode.RESEARCH)
    )
    with TestClient(app) as c:
        assert c.get("/api/research/owner-outcomes/score").status_code == 503
        app.state.trade_outcome_service = _Outcomes([trade(0, "100", "110")])
        response = c.get("/api/research/owner-outcomes/score")
    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "no-store"
    assert response.json()["trades"]["counted"] == 1
    assert response.json()["verdict"]["status"] == "INCONCLUSIVE"
