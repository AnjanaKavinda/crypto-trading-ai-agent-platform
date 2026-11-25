"""Real PostgreSQL C-107 trade intent -> C-108 owner outcome checkpoint.

The NO_TRADE source and every fill are synthetic test fixtures.
"""

import asyncio
from datetime import timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select
from test_lineage_postgresql import database_url as database_url
from test_spot_research_api import INSTRUMENT, client_for, refresh_body
from test_spot_research_api import persisted_service as persisted_service
from trading_platform_api.contracts.serialization import canonical_sha256
from trading_platform_api.journal_api import JournalRequest, JournalService
from trading_platform_api.lineage.store import SqlAlchemyLineageStore
from trading_platform_api.lineage.tables import spot_producer_request_reservations
from trading_platform_api.strategy.contracts import (
    SignalLifecycleState,
    VersionReference,
)
from trading_platform_api.strategy.contracts_v2 import (
    NoTradeDecisionV2,
    NoTradeReasonV2,
)
from trading_platform_api.strategy_api import (
    ApiVersionReference,
    StrategySignalApiError,
)
from trading_platform_api.trade_outcome_api import (
    TradeOutcomeRequest,
    TradeOutcomeService,
)


def test_owner_outcome_links_trade_intent_retries_and_corrections(persisted_service):
    research, _, repository, now = persisted_service
    with client_for(research) as c:
        response = c.post(
            f"/api/research/spot/{INSTRUMENT}/refresh",
            json=refresh_body(timeframe="1m", limit=50, now=now),
        )
    assert response.status_code == 200, response.text

    async def seed():
        async with repository._session_factory() as session:
            row = (
                (
                    await session.execute(
                        select(spot_producer_request_reservations).where(
                            spot_producer_request_reservations.c.snapshot_id
                            == response.json()["snapshot_id"],
                            spot_producer_request_reservations.c.status == "COMPLETED",
                        )
                    )
                )
                .mappings()
                .one()
            )
            context = VersionReference(
                "C-006", UUID(row["context_record_id"]), "5", row["context_sha256"]
            )
            source = NoTradeDecisionV2(
                uuid4(),
                context.artifact_id,
                None,
                None,
                (NoTradeReasonV2.MISSING_DATA,),
                "Synthetic persisted NO_TRADE outcome fixture",
                (),
                (),
                (),
                None,
                (context,),
                "outcome-checkpoint",
                SignalLifecycleState.NO_TRADE,
                now,
                now + timedelta(minutes=5),
            )
            await SqlAlchemyLineageStore(session).append(source)
            await session.commit()
            return source

    source = asyncio.run(seed())
    journal = JournalService(
        repository._session_factory, clock=lambda: now + timedelta(hours=1)
    )

    def declaration(action):
        return JournalRequest.model_validate(
            {
                "request_id": str(uuid4()),
                "source": {
                    "contract_id": "C-026",
                    "artifact_id": str(source.decision_id),
                    "schema_version": "2",
                    "content_sha256": canonical_sha256(source),
                },
                "declared_action": action,
                "declared_at": now.isoformat(),
            }
        )

    def link(entry):
        return {
            "contract_id": "C-107",
            "artifact_id": str(entry.entry_id),
            "schema_version": "1",
            "content_sha256": entry.content_sha256,
        }

    def fill(side, quantity, price, hours, fee):
        return {
            "side": side,
            "quantity": quantity,
            "price_usdt": price,
            "executed_at": (now + timedelta(hours=hours)).isoformat(),
            "fee_source": "STATEMENT",
            "fee_usdt": fee,
        }

    service = TradeOutcomeService(
        repository._session_factory, clock=lambda: now + timedelta(hours=4)
    )

    async def check():
        intent = await journal.save(declaration("EXTERNAL_TRADE_INTENT"))
        abstain = await journal.save(declaration("ABSTAIN"))
        request = TradeOutcomeRequest.model_validate(
            {
                "request_id": str(uuid4()),
                "journal_entry": link(intent),
                "fills": [
                    fill("BUY", "0.01", "50000", 2, "0.5"),
                    fill("SELL", "0.01", "51000", 3, "0.51"),
                ],
                "note": "<img src=x onerror=alert(1)>",
            }
        )
        first, concurrent = await asyncio.gather(
            service.save(request), service.save(request)
        )
        assert first == concurrent
        assert first.instrument_id == INSTRUMENT
        assert str(first.net_result_usdt) == "8.99"
        assert first.net_result_basis == "STATEMENT_FEES"
        assert first.decision_recorded_before_first_fill is True
        assert not first.trade_facts_verified and not first.execution_authorized
        later = TradeOutcomeService(
            repository._session_factory, clock=lambda: now + timedelta(days=3)
        )
        assert await later.save(request) == first  # retry keeps the original
        with pytest.raises(StrategySignalApiError) as conflict:
            await service.save(request.model_copy(update={"note": "changed"}))
        assert conflict.value.status == 409
        with pytest.raises(StrategySignalApiError) as not_intent:
            await service.save(
                request.model_copy(
                    update={
                        "request_id": uuid4(),
                        "journal_entry": ApiVersionReference(**link(abstain)),
                    }
                )
            )
        assert not_intent.value.code == "TRADE_OUTCOME_TRADE_INTENT_REQUIRED"
        with pytest.raises(StrategySignalApiError):
            await service.save(
                request.model_copy(
                    update={
                        "request_id": uuid4(),
                        "journal_entry": ApiVersionReference(
                            **{**link(intent), "content_sha256": "f" * 64}
                        ),
                    }
                )
            )
        correction = TradeOutcomeRequest.model_validate(
            {
                **request.model_dump(mode="json"),
                "request_id": str(uuid4()),
                "fills": [
                    fill("BUY", "0.01", "50000", 2, "0.5"),
                    fill("SELL", "0.01", "50900", 3, "0.509"),
                ],
                "supersedes": {
                    "contract_id": "C-108",
                    "artifact_id": str(first.outcome_id),
                    "schema_version": "1",
                    "content_sha256": first.content_sha256,
                },
                "correction_reason": "Statement sell price was 50900",
            }
        )
        corrected = await service.save(correction)
        assert corrected.supersedes.artifact_id == first.outcome_id
        assert str(corrected.net_result_usdt) == "7.991"
        assert await service.read(first.outcome_id, first.content_sha256) == first
        assert await service.read_request(correction.request_id) == corrected
        page = await service.page(1, None)
        assert len(page["items"]) == 1 and page["next_cursor"]
        assert (await service.page(5, UUID(page["next_cursor"])))["items"]

    asyncio.run(check())
