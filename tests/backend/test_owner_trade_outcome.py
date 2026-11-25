"""Focused C-108 owner trade-outcome arithmetic, identity and admission checks.

All fills below are synthetic test fixtures, not market or account data.
"""

import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from test_decision_journal import ORIGIN, client
from trading_platform_api.learning.trade_outcome import OwnerFill, OwnerTradeOutcome
from trading_platform_api.lineage.codec import LineageError, decode, encode
from trading_platform_api.strategy.contracts import VersionReference
from trading_platform_api.trade_outcome_api import TradeOutcomeRequest

NOW = datetime(2026, 11, 25, tzinfo=UTC)
PATH = "/api/research/owner-outcomes"


def fill(side, quantity, price, minutes, source="STATEMENT", fee="0.1"):
    return OwnerFill(
        side,
        Decimal(quantity),
        Decimal(price),
        NOW + timedelta(minutes=minutes),
        source,
        None if fee is None else Decimal(fee),
    )


def outcome(*fills, journal_recorded_at=NOW):
    return OwnerTradeOutcome(
        request_id=uuid4(),
        request_sha256="a" * 64,
        journal_entry=VersionReference("C-107", uuid4(), "1", "b" * 64),
        journal_recorded_at=journal_recorded_at,
        instrument_id="BTC-USDT-SPOT",
        fills=fills,
        recorded_at=NOW + timedelta(days=1),
    )


def test_closed_trade_net_result_is_exact_decimal():
    value = outcome(
        fill("BUY", "0.015", "60000.10", 1, fee="0.9"),
        fill("SELL", "0.005", "61000", 2, fee="0.305"),
        fill("SELL", "0.010", "62000.5", 3, fee="0.62"),
    )
    assert value.position_status == "CLOSED"
    # 305 + 620.005 - 900.0015 = 25.0035; fees 1.825.
    assert value.gross_result_usdt == Decimal("25.0035")
    assert value.total_fees_usdt == Decimal("1.825")
    assert value.net_result_usdt == Decimal("23.1785")
    assert value.net_result_basis == "STATEMENT_FEES"
    assert value.net_result_reason is None
    assert value.decision_recorded_before_first_fill is True
    assert not (value.trade_facts_verified or value.execution_authorized)


def test_estimated_unknown_fees_open_position_and_retrospective_decision():
    estimated = outcome(
        fill("BUY", "1", "10", 1), fill("SELL", "1", "9", 2, "ESTIMATE")
    )
    assert estimated.net_result_usdt == Decimal("-1.2")
    assert estimated.net_result_basis == "INCLUDES_ESTIMATED_FEES"

    unknown = outcome(
        fill("BUY", "1", "10", 1), fill("SELL", "1", "11", 2, "UNKNOWN", None)
    )
    assert unknown.gross_result_usdt == Decimal("1")
    assert unknown.total_fees_usdt is None and unknown.net_result_usdt is None
    assert (unknown.net_result_basis, unknown.net_result_reason) == (
        "UNAVAILABLE",
        "FEE_UNKNOWN",
    )

    open_position = outcome(fill("BUY", "2", "10", 1), fill("SELL", "1", "11", 2))
    assert open_position.position_status == "OPEN"
    assert open_position.gross_result_usdt is None
    assert open_position.total_fees_usdt == Decimal("0.2")
    assert open_position.net_result_reason == "POSITION_OPEN"

    late = outcome(
        fill("BUY", "1", "10", 1),
        fill("SELL", "1", "11", 2),
        journal_recorded_at=NOW + timedelta(minutes=5),
    )
    assert late.decision_recorded_before_first_fill is False


@pytest.mark.parametrize(
    "fills",
    [
        (),
        (fill("SELL", "1", "10", 1),),
        (fill("BUY", "1", "10", 1), fill("SELL", "2", "10", 2)),
        (fill("BUY", "1", "10", 2), fill("SELL", "1", "10", 1)),
    ],
)
def test_invalid_spot_fill_sequences_fail_closed(fills):
    with pytest.raises(ValueError):
        outcome(*fills)


def test_invalid_fill_values_fail_closed():
    for args in [
        ("SHORT", Decimal(1), Decimal(1), NOW, "STATEMENT", Decimal(0)),
        ("BUY", Decimal(0), Decimal(1), NOW, "STATEMENT", Decimal(0)),
        ("BUY", Decimal(1), Decimal("-1"), NOW, "STATEMENT", Decimal(0)),
        ("BUY", Decimal(1), Decimal("1e-19"), NOW, "STATEMENT", Decimal(0)),
        ("BUY", Decimal(1), Decimal(1), NOW, "UNKNOWN", Decimal(0)),
        ("BUY", Decimal(1), Decimal(1), NOW, "ESTIMATE", None),
        ("BUY", Decimal(1), Decimal(1), NOW.replace(tzinfo=None), "ESTIMATE", None),
    ]:
        with pytest.raises(ValueError):
            OwnerFill(*args)
    future = fill("BUY", "1", "1", 60 * 24 * 2)
    with pytest.raises(ValueError):
        outcome(future)


def test_closed_codec_identity_and_tamper_rejection():
    value = outcome(fill("BUY", "1", "10", 1), fill("SELL", "1", "11", 2))
    assert decode(encode(value)) == value
    assert value.outcome_id.version == 5
    changed = replace(value, note="changed")
    assert changed.outcome_id == value.outcome_id  # keyed by the request id
    assert changed.content_sha256 != value.content_sha256
    for mutate in [
        lambda x: x["payload"].update(net_result_usdt="999"),
        lambda x: x["payload"].update(trade_facts_verified=True),
        lambda x: x["payload"].update(extra="invalid"),
        lambda x: x.update(schema_version="2"),
    ]:
        document = json.loads(encode(value))
        mutate(document)
        with pytest.raises(LineageError):
            decode(json.dumps(document))


def body(**changes):
    data = {
        "request_id": str(uuid4()),
        "journal_entry": {
            "contract_id": "C-107",
            "artifact_id": str(uuid4()),
            "schema_version": "1",
            "content_sha256": "b" * 64,
        },
        "fills": [
            {
                "side": "BUY",
                "quantity": "0.5",
                "price_usdt": "100",
                "executed_at": NOW.isoformat(),
                "fee_source": "STATEMENT",
                "fee_usdt": "0.05",
            }
        ],
    }
    data.update(changes)
    return data


def test_request_rejects_floats_authority_fields_and_wrong_links():
    TradeOutcomeRequest.model_validate(body())
    base_fill = body()["fills"][0]
    for changes in [
        {"fills": [{**base_fill, "quantity": 0.5}]},
        {"fills": [{**base_fill, "quantity": "1e3"}]},
        {"fills": [{**base_fill, "fee_source": "UNKNOWN"}]},
        {"fills": [{**base_fill, "executed_at": "2026-11-25T00:00:00"}]},
        {"fills": []},
        {"execution_authorized": True},
        {"net_result_usdt": "5"},
        {"journal_entry": {**body()["journal_entry"], "contract_id": "C-026"}},
        {"correction_reason": "missing parent"},
    ]:
        with pytest.raises(ValueError):
            TradeOutcomeRequest.model_validate(body(**changes))


def test_local_write_admission_and_no_store():
    with client() as c:
        for headers, payload, status in [
            ({}, body(), 403),
            ({"Origin": "http://evil.example"}, body(), 403),
            ({"Origin": ORIGIN}, {**body(), "execution_authorized": True}, 422),
            ({"Origin": ORIGIN}, body(), 503),
        ]:
            r = c.post(PATH, json=payload, headers=headers)
            assert r.status_code == status, r.text
            assert r.headers["cache-control"] == "no-store"
        assert c.post(PATH, content="x", headers={"Origin": ORIGIN}).status_code == 415
        assert c.get(PATH).status_code == 503
