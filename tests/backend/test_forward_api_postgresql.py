"""Real PostgreSQL checkpoint for C-109 verdict import and the forward API.

Every report here is a SYNTHETIC fixture; no real study result is represented.
"""

import asyncio
import json
from datetime import UTC, datetime
from hashlib import sha256

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool
from test_lineage_postgresql import database_url as database_url
from test_spot_research_api import client_for
from test_spot_research_api import persisted_service as persisted_service
from test_study_verdict import report
from trading_platform_api.forward_api import ForwardService
from trading_platform_api.research.strategy import TrendDailyRegime
from trading_platform_api.strategy_api import StrategySignalApiError

ORIGIN = "http://127.0.0.1:5173"


def test_verdict_import_is_idempotent_and_drives_the_forward_api(
    database_url, persisted_service
):
    research, _, _, now = persisted_service
    engine = create_async_engine(database_url, poolclass=NullPool)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    # A unique synthetic report so reruns against a retained database differ.
    body = json.dumps(report(created_at=now.isoformat()), sort_keys=True).encode()
    service = ForwardService(sessions, clock=lambda: now)

    async def check():
        first, concurrent = await asyncio.gather(
            service.import_report(body), service.import_report(body)
        )
        assert first == concurrent
        assert first.report_sha256 == sha256(body).hexdigest()
        later = ForwardService(sessions, clock=lambda: datetime(2030, 1, 1, tzinfo=UTC))
        assert await later.import_report(body) == first
        assert first in await service.verdicts()
        latest = await service.latest_verdict(TrendDailyRegime().content_sha256)
        assert latest is not None and latest.recorded_at >= first.recorded_at
        with pytest.raises(StrategySignalApiError) as rejected:
            await service.import_report(json.dumps(report(timeframe="4h")).encode())
        assert rejected.value.code == "FORWARD_REPORT_REJECTED"
        with pytest.raises(StrategySignalApiError) as not_json:
            await service.import_report(b"[1, 2]")
        assert not_json.value.code == "FORWARD_REPORT_NOT_JSON"

    try:
        asyncio.run(check())
        with client_for(research, allowed_origin=ORIGIN) as client:
            client.app.state.forward_service = service
            listed = client.get("/api/research/forward/verdicts")
            assert listed.status_code == 200, listed.text
            assert listed.json()["items"]
            no_origin = client.post(
                "/api/research/forward/verdicts",
                content=body,
                headers={"content-type": "application/json"},
            )
            assert no_origin.status_code == 403
            saved = client.post(
                "/api/research/forward/verdicts",
                content=body,
                headers={"content-type": "application/json", "origin": ORIGIN},
            )
            assert saved.status_code == 200, saved.text
            assert saved.json()["report_sha256"] == sha256(body).hexdigest()
            unknown = client.get("/api/research/forward/range-reversion-4h?version=2")
            assert unknown.status_code == 404
            # No 1d snapshots are persisted for this fixture: fail closed.
            missing = client.get("/api/research/forward/trend-daily-regime")
            assert missing.status_code == 422
            assert missing.json()["code"] in {
                "FORWARD_SNAPSHOT_UNAVAILABLE",
                "FORWARD_SNAPSHOT_NOT_VALID",
                "FORWARD_HISTORY_INSUFFICIENT",
            }
    finally:
        asyncio.run(engine.dispose())
