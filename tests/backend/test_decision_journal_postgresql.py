"""One focused real producer->retained NO_TRADE->C-107 API storage checkpoint."""

import asyncio
from datetime import timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError
from test_decision_journal import ORIGIN, client
from test_lineage_postgresql import database_url as database_url
from test_spot_research_api import INSTRUMENT, client_for, refresh_body
from test_spot_research_api import persisted_service as persisted_service
from trading_platform_api.contracts.serialization import canonical_sha256
from trading_platform_api.journal_api import JournalRequest, JournalService
from trading_platform_api.lineage.codec import LineageError
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


def test_journal_producer_storage_api_retry_corrections_and_failures(
    persisted_service, monkeypatch
):
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
                "C-006",
                UUID(row["context_record_id"]),
                "5",
                row["context_sha256"],
            )
            source = NoTradeDecisionV2(
                uuid4(),
                context.artifact_id,
                None,
                None,
                (NoTradeReasonV2.MISSING_DATA,),
                "Synthetic persisted NO_TRADE journal fixture",
                (),
                (),
                (),
                None,
                (context,),
                "journal-checkpoint",
                SignalLifecycleState.NO_TRADE,
                now,
                now + timedelta(minutes=5),
            )
            await SqlAlchemyLineageStore(session).append(source)
            await session.commit()
            return source

    source = asyncio.run(seed())
    reference = {
        "contract_id": "C-026",
        "artifact_id": str(source.decision_id),
        "schema_version": "2",
        "content_sha256": canonical_sha256(source),
    }
    service = JournalService(
        repository._session_factory, clock=lambda: now + timedelta(hours=1)
    )
    request = JournalRequest.model_validate(
        {
            "request_id": str(uuid4()),
            "source": reference,
            "declared_action": "EXTERNAL_TRADE_INTENT",
            "declared_at": now.isoformat(),
            "note": "<img src=x onerror=alert(1)>",
        }
    )

    async def check():
        first, concurrent = await asyncio.gather(
            service.save(request), service.save(request)
        )
        assert first == concurrent
        assert first.source_observation.projection_state == "NO_TRADE"
        assert first.source_observation.expires_at < first.recorded_at
        assert first.source_observation.lifecycle_pin is None
        assert not first.execution_authorized and not first.trade_facts_verified
        restarted = JournalService(
            repository._session_factory, clock=lambda: now - timedelta(days=1)
        )
        assert (
            await restarted.save(request) == first
        )  # Retry does not re-enrich/re-time.
        with pytest.raises(StrategySignalApiError) as conflict:
            await service.save(request.model_copy(update={"note": "changed"}))
        assert conflict.value.status == 409
        correction = request.model_copy(
            update={
                "request_id": uuid4(),
                "supersedes": ApiVersionReference(
                    contract_id="C-107",
                    artifact_id=first.entry_id,
                    schema_version="1",
                    content_sha256=first.content_sha256,
                ),
                "correction_reason": "Corrected user intent",
                "declared_action": "ABSTAIN",
            }
        )
        corrected = await service.save(correction)
        assert corrected.supersedes.artifact_id == first.entry_id
        assert corrected.entry_id != first.entry_id
        assert await service.read(first.entry_id, first.content_sha256) == first
        page = await service.page(1, None)
        assert len(page["items"]) == 1 and page["next_cursor"]
        assert len((await service.page(1, UUID(page["next_cursor"])))["items"]) >= 1
        for changed, clock in [
            (
                request.model_copy(
                    update={
                        "request_id": uuid4(),
                        "declared_at": now + timedelta(days=2),
                    }
                ),
                now,
            ),
            (
                correction.model_copy(update={"request_id": uuid4()}),
                now + timedelta(minutes=30),
            ),
        ]:
            with pytest.raises((ValueError, StrategySignalApiError)):
                await JournalService(
                    repository._session_factory, clock=lambda: clock
                ).save(changed)
        bad = request.model_copy(
            update={
                "request_id": uuid4(),
                "source": request.source.model_copy(
                    update={"content_sha256": "f" * 64}
                ),
            }
        )
        with pytest.raises(StrategySignalApiError):
            await service.save(bad)
        original = service._bound
        calls = 0

        async def fail_readback(session, key):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise LineageError("Injected transaction readback failure")
            return await original(session, key)

        failed = request.model_copy(update={"request_id": uuid4()})
        monkeypatch.setattr(service, "_bound", fail_readback)
        with pytest.raises(LineageError):
            await service.save(failed)
        monkeypatch.setattr(service, "_bound", original)
        assert await service.read_request(failed.request_id) is None
        # A failure after insert rolled the whole transaction back; exact retry works.
        assert (await service.save(failed)).request_id == failed.request_id
        committed_request = request.model_copy(update={"request_id": uuid4()})
        calls = 0

        async def lose_commit_ack(session, key):
            nonlocal calls
            calls += 1
            if calls == 3:
                raise LineageError("Injected lost committed readback")
            return await original(session, key)

        monkeypatch.setattr(service, "_bound", lose_commit_ack)
        with pytest.raises(LineageError):
            await service.save(committed_request)
        monkeypatch.setattr(service, "_bound", original)
        recovered = await service.read_request(committed_request.request_id)
        assert recovered is not None
        assert await service.save(committed_request) == recovered
        async with repository._session_factory() as session:
            with pytest.raises(DBAPIError):
                await session.execute(
                    text(
                        "UPDATE research_journal_requests SET request_sha256=request_sha256"
                    )
                )
            await session.rollback()
        return first

    first = asyncio.run(check())
    with client() as c:
        c.app.state.journal_service = service
        headers = {"Origin": ORIGIN}
        data = request.model_dump(mode="json")
        result = c.post("/api/research/decision-journal", json=data, headers=headers)
        assert result.status_code == 200, result.text
        assert result.json()["entry_id"] == str(first.entry_id)
        assert (
            c.get(
                "/api/research/decision-journal/requests/" + str(request.request_id)
            ).json()
            == result.json()
        )
        assert (
            c.get(
                f"/api/research/decision-journal/{first.entry_id}?schema_version=1&content_sha256={first.content_sha256}"
            ).json()
            == result.json()
        )
        assert c.get("/api/research/decision-journal?limit=20").status_code == 200
        assert result.headers["cache-control"] == "no-store"
        assert (
            c.post(
                "/api/research/decision-journal",
                json={**data, "note": "conflict"},
                headers=headers,
            ).status_code
            == 409
        )
