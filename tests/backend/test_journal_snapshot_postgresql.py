"""Real PostgreSQL C-107v2: journal against the exact viewed snapshot (E2c2).

The snapshot comes from the existing synthetic provider fixture; no real market
data is used or fabricated.
"""

import asyncio
from datetime import datetime, timedelta
from uuid import uuid4

import pytest
from test_decision_journal import ORIGIN, client
from test_lineage_postgresql import database_url as database_url
from test_spot_research_api import INSTRUMENT, client_for, refresh_body
from test_spot_research_api import persisted_service as persisted_service
from trading_platform_api.journal_api import JournalService, SnapshotJournalRequest
from trading_platform_api.learning.decision_journal import (
    SnapshotDecisionJournalEntry,
)
from trading_platform_api.strategy_api import (
    ApiVersionReference,
    StrategySignalApiError,
)


def test_snapshot_declaration_resolves_verifies_retries_and_fails_closed(
    persisted_service,
):
    research, _, repository, now = persisted_service
    with client_for(research) as c:
        response = c.post(
            f"/api/research/spot/{INSTRUMENT}/refresh",
            json=refresh_body(timeframe="1m", limit=50, now=now),
        )
    assert response.status_code == 200, response.text
    viewed = response.json()
    assert viewed["data_quality"]["status"] == "VALID"
    service = JournalService(
        repository._session_factory, clock=lambda: now, research=research
    )
    request = SnapshotJournalRequest.model_validate(
        {
            "request_id": str(uuid4()),
            "instrument_id": INSTRUMENT,
            "timeframe": "1m",
            "snapshot_id": viewed["snapshot_id"],
            "quality_report_id": viewed["data_quality"]["report_id"],
            "declared_action": "EXTERNAL_TRADE_INTENT",
            "declared_at": now.isoformat(),
            "note": "<b>synthetic</b>",
        }
    )

    async def rejected(changed, clock=None):
        target = (
            service
            if clock is None
            else JournalService(
                repository._session_factory, clock=lambda: clock, research=research
            )
        )
        with pytest.raises(StrategySignalApiError) as failure:
            await target.save_snapshot(changed)
        return failure.value.status, failure.value.code

    async def check():
        first, concurrent = await asyncio.gather(
            service.save_snapshot(request), service.save_snapshot(request)
        )
        assert first == concurrent
        assert type(first) is SnapshotDecisionJournalEntry
        observed = first.snapshot_observation
        assert str(first.source.artifact_id) == viewed["snapshot_id"]
        assert (
            str(first.quality_report.artifact_id)
            == (viewed["data_quality"]["report_id"])
        )
        assert (observed.instrument_id, observed.timeframe) == (INSTRUMENT, "1m")
        assert observed.candle_count == len(viewed["candles"]) == 50
        assert observed.last_candle_open_time == datetime.fromisoformat(
            viewed["candles"][-1]["open_time"].replace("Z", "+00:00")
        )
        assert observed.fresh_until >= first.recorded_at
        assert not first.execution_authorized and not first.trade_facts_verified
        # Identical retry after the snapshot went stale returns the original.
        later = JournalService(
            repository._session_factory,
            clock=lambda: now + timedelta(hours=2),
            research=research,
        )
        assert await later.save_snapshot(request) == first
        assert await service.read_request(request.request_id) == first
        assert await service.read(first.entry_id, first.content_sha256, "2") == first
        assert (await rejected(request.model_copy(update={"note": "changed"})))[
            0
        ] == 409
        fresh = {"request_id": uuid4()}
        # Unknown / no-longer-current snapshot, wrong quality report, wrong scope.
        assert await rejected(
            request.model_copy(update={**fresh, "snapshot_id": uuid4()})
        ) == (422, "JOURNAL_SNAPSHOT_NOT_CURRENT")
        assert await rejected(
            request.model_copy(update={**fresh, "quality_report_id": uuid4()})
        ) == (422, "JOURNAL_SNAPSHOT_QUALITY_MISMATCH")
        assert (
            await rejected(
                request.model_copy(update={**fresh, "instrument_id": "ETH-USDT-SPOT"})
            )
        )[0] == 422
        # Stale: recorded after the last candle close + freshness window.
        assert await rejected(
            request.model_copy(update={"request_id": uuid4()}),
            clock=now + timedelta(minutes=3),
        ) == (422, "JOURNAL_SNAPSHOT_STALE_OR_INVALID")
        correction = request.model_copy(
            update={
                "request_id": uuid4(),
                "declared_action": "ABSTAIN",
                "supersedes": ApiVersionReference(
                    contract_id="C-107",
                    artifact_id=first.entry_id,
                    schema_version="2",
                    content_sha256=first.content_sha256,
                ),
                "correction_reason": "Changed my mind on the same snapshot",
            }
        )
        corrected = await service.save_snapshot(correction)
        assert corrected.supersedes.artifact_id == first.entry_id
        assert corrected.entry_id != first.entry_id
        bad_parent = correction.model_copy(
            update={
                "request_id": uuid4(),
                "supersedes": correction.supersedes.model_copy(
                    update={"content_sha256": "f" * 64}
                ),
            }
        )
        assert (await rejected(bad_parent))[0] == 422
        page = await service.page(20, None)
        listed = {item["entry_id"] for item in page["items"]}
        assert {str(first.entry_id), str(corrected.entry_id)} <= listed
        return first

    first = asyncio.run(check())
    with client() as c:
        c.app.state.journal_service = service
        data = request.model_dump(mode="json")
        result = c.post(
            "/api/research/decision-journal", json=data, headers={"Origin": ORIGIN}
        )
        assert result.status_code == 200, result.text
        body = result.json()
        assert body["entry_id"] == str(first.entry_id)
        assert body["schema_version"] == "2"
        assert body["note"] == "<b>synthetic</b>"
        assert (
            c.get(
                f"/api/research/decision-journal/{first.entry_id}"
                f"?schema_version=2&content_sha256={first.content_sha256}"
            ).json()
            == body
        )
        assert result.headers["cache-control"] == "no-store"
