"""Local-only forward (prospective) stage API for protocol v2 candidates (E2f2).

- ``POST /api/research/forward/verdicts`` imports one owner study report as a
  C-109v1 verdict (digests checked, append-only, identical re-import returns
  the stored record).
- ``GET /api/research/forward/verdicts`` lists the imported verdicts.
- ``GET /api/research/forward/{strategy_id}?version=1`` replays the frozen
  candidate over the persisted Spot snapshots from the prospective start and
  returns its SIMULATED signals, forward stats and stage status.

Research evidence only: no order path, no qualification/approval/execution
authority.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from hashlib import sha256
from typing import Any

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from trading_platform_api.contracts.serialization import canonical_json_dumps
from trading_platform_api.lineage.codec import LineageError, LineageKey
from trading_platform_api.lineage.policy import PERSONAL_SPOT_INSTRUMENTS
from trading_platform_api.lineage.store import SqlAlchemyLineageStore
from trading_platform_api.lineage.tables import records
from trading_platform_api.research.candles import TIMEFRAME_SECONDS, Candle
from trading_platform_api.research.forward import (
    FORWARD_STRATEGIES,
    forward_record,
    history_start,
)
from trading_platform_api.research.forward_history import (
    covering_snapshots,
    merge_windows,
)
from trading_platform_api.research.report import _jsonable
from trading_platform_api.research.study_verdict import (
    StudyVerdictRecord,
    verdict_record_from_report,
)
from trading_platform_api.research.walk_forward import V2_STRATEGIES
from trading_platform_api.spot_research import SpotResearchError
from trading_platform_api.spot_research_store import MAX_READ_CANDLES
from trading_platform_api.strategy_api import StrategySignalApiError

PROFILE = "PERSONAL_SPOT_RESEARCH"
MAX_REPORT_BYTES = 4 * 1024 * 1024
MAX_VERDICTS = 1000


def error(status: int, code: str, detail: str | None = None) -> StrategySignalApiError:
    return StrategySignalApiError(
        status=status,
        code=code,
        title="Forward research request rejected",
        detail=detail
        or "The forward research evidence could not be verified; nothing is shown.",
    )


def view(record: StudyVerdictRecord) -> dict[str, Any]:
    return json.loads(canonical_json_dumps(record))


class ForwardService:
    def __init__(
        self,
        session_factory: Callable[[], AsyncSession],
        *,
        clock: Callable[[], datetime] | None = None,
    ):
        self.sessions = session_factory
        self.clock = clock or (lambda: datetime.now(UTC))

    async def _read(
        self, store: SqlAlchemyLineageStore, record_id: str
    ) -> StudyVerdictRecord:
        key = LineageKey("C-109", record_id, "1")
        record = (await store.resolve((key,)))[key]
        if type(record) is not StudyVerdictRecord:
            raise LineageError("Not a study verdict.")
        return record

    async def _ids(self, session: AsyncSession) -> list[str]:
        ids: list[str] = list(
            (
                await session.execute(
                    select(records.c.record_id)
                    .where(records.c.contract_id == "C-109", records.c.version == "1")
                    .order_by(records.c.occurred_at, records.c.record_id)
                    .limit(MAX_VERDICTS + 1)
                )
            )
            .scalars()
            .all()
        )
        if len(ids) > MAX_VERDICTS:
            raise ValueError("Too many study verdicts.")
        return ids

    async def import_report(self, body: bytes) -> StudyVerdictRecord:
        report_sha256 = sha256(body).hexdigest()
        try:
            report = json.loads(body)
        except ValueError as exc:
            raise error(422, "FORWARD_REPORT_NOT_JSON") from exc
        if type(report) is not dict:
            raise error(422, "FORWARD_REPORT_NOT_JSON")
        try:
            record = verdict_record_from_report(
                report, report_sha256=report_sha256, recorded_at=self.clock()
            )
        except ValueError as exc:
            raise error(422, "FORWARD_REPORT_REJECTED", str(exc)) from exc
        async with self.sessions() as session:
            async with session.begin():
                await session.execute(
                    select(
                        func.pg_advisory_xact_lock(
                            func.hashtextextended(
                                "C-109:" + PROFILE + ":" + report_sha256, 0
                            )
                        )
                    )
                )
                store = SqlAlchemyLineageStore(session)
                if str(record.verdict_id) in await self._ids(session):
                    saved = await self._read(store, str(record.verdict_id))
                    if saved.report_sha256 != report_sha256:
                        raise LineageError("Corrupt study verdict identity.")
                    return saved
                await store.append(record)
                if await self._read(store, str(record.verdict_id)) != record:
                    raise LineageError("Study verdict transaction readback failed.")
            return record

    async def verdicts(self) -> list[StudyVerdictRecord]:
        async with self.sessions() as session:
            store = SqlAlchemyLineageStore(session)
            return [
                await self._read(store, value) for value in await self._ids(session)
            ]

    async def latest_verdict(self, strategy_sha256: str) -> StudyVerdictRecord | None:
        matching = [
            item
            for item in await self.verdicts()
            if item.strategy_sha256 == strategy_sha256
        ]
        return max(matching, key=lambda item: item.recorded_at, default=None)


def research_candles(served: dict[str, Any]) -> tuple[Candle, ...]:
    return tuple(
        Candle(
            open_time=datetime.fromisoformat(item["open_time"].replace("Z", "+00:00")),
            open=Decimal(item["metrics"]["open"]["value"]),
            high=Decimal(item["metrics"]["high"]["value"]),
            low=Decimal(item["metrics"]["low"]["value"]),
            close=Decimal(item["metrics"]["close"]["value"]),
            volume=Decimal(item["metrics"]["volume"]["value"]),
        )
        for item in served["candles"]
    )


async def _valid_read(
    spot: Any,
    instrument: str,
    timeframe: str,
    as_of: datetime | None,
    correlation_id: str | None,
) -> dict[str, Any]:
    label = f"{instrument} {timeframe}" + ("" if as_of is None else f" at {as_of}")
    try:
        served: dict[str, Any] = await spot.read(
            instrument_id=instrument,
            timeframe=timeframe,
            as_of=as_of,
            limit=MAX_READ_CANDLES,
            correlation_id=correlation_id,
        )
    except SpotResearchError as exc:
        raise error(
            422, "FORWARD_SNAPSHOT_UNAVAILABLE", f"{label}: {exc.code}"
        ) from exc
    status = served["data_quality"]["status"]
    if status != "VALID":
        raise error(
            422, "FORWARD_SNAPSHOT_NOT_VALID", f"{label}: data quality {status}"
        )
    return served


async def stitched_history(
    spot: Any,
    instrument: str,
    timeframe: str,
    *,
    start: datetime,
    step: timedelta,
    correlation_id: str | None,
) -> tuple[str, tuple[Candle, ...]]:
    """Contiguous persisted candles from the fixed warm-up ``start`` onward."""
    latest = await _valid_read(spot, instrument, timeframe, None, correlation_id)
    windows = [research_candles(latest)]
    if not windows[0]:
        raise error(422, "FORWARD_HISTORY_INSUFFICIENT", f"{instrument}: no candles")
    try:
        if windows[0][0].open_time > start:
            if spot.repository is None:
                raise error(503, "FORWARD_SNAPSHOTS_UNAVAILABLE")
            available = await spot.repository.snapshot_windows(
                instrument_id=instrument, timeframe=timeframe, since=start
            )
            for as_of in covering_snapshots(
                available,
                covered_from=windows[0][0].open_time,
                start=start,
                step=step,
            ):
                older = await _valid_read(
                    spot, instrument, timeframe, as_of, correlation_id
                )
                windows.append(research_candles(older))
        candles = merge_windows(windows, start=start, step=step)
    except ValueError as exc:
        raise error(
            422, "FORWARD_HISTORY_INSUFFICIENT", f"{instrument} {timeframe}: {exc}"
        ) from exc
    return str(latest["symbol"]), candles


def create_forward_router() -> APIRouter:
    router = APIRouter(prefix="/api/research/forward", tags=["forward-research"])

    def service(request: Request) -> ForwardService:
        settings = request.app.state.settings
        if settings.mode.value != "research" or settings.environment.value not in {
            "dev",
            "test",
        }:
            raise error(403, "FORWARD_LOCAL_RESEARCH_REQUIRED")
        result = getattr(request.app.state, "forward_service", None)
        if result is None:
            raise error(503, "FORWARD_STORAGE_UNAVAILABLE")
        return result

    async def respond(operation: Any) -> JSONResponse:
        try:
            content = await operation
            return JSONResponse(content, headers={"Cache-Control": "no-store"})
        except StrategySignalApiError:
            raise
        except (LineageError, ValueError, TypeError, ArithmeticError) as exc:
            raise error(422, "FORWARD_EVIDENCE_INVALID") from exc
        except Exception as exc:
            raise error(503, "FORWARD_STORAGE_UNCONFIRMED") from exc

    @router.post("/verdicts")
    async def import_verdict(request: Request) -> JSONResponse:
        allowed = request.app.state.allowed_origin
        if allowed is None or request.headers.get("origin") != allowed:
            raise error(403, "FORWARD_ORIGIN_REQUIRED")
        if (
            request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
            != "application/json"
        ):
            raise error(415, "FORWARD_JSON_REQUIRED")
        body = bytearray()
        async for chunk in request.stream():
            if len(body) + len(chunk) > MAX_REPORT_BYTES:
                raise error(413, "FORWARD_REPORT_TOO_LARGE")
            body.extend(chunk)
        forward = service(request)

        async def run() -> dict[str, Any]:
            return view(await forward.import_report(bytes(body)))

        return await respond(run())

    @router.get("/verdicts")
    async def list_verdicts(request: Request) -> JSONResponse:
        forward = service(request)

        async def run() -> dict[str, Any]:
            return {"items": [view(item) for item in await forward.verdicts()]}

        return await respond(run())

    @router.get("/{strategy_id}")
    async def read_forward(
        strategy_id: str,
        request: Request,
        version: int = Query(default=1, ge=1),
    ) -> JSONResponse:
        strategy = FORWARD_STRATEGIES.get(strategy_id)
        if strategy is None or strategy.version != version:
            raise error(404, "FORWARD_STRATEGY_NOT_REGISTERED")
        forward = service(request)
        spot = request.app.state.spot_research_service
        if spot is None:
            raise error(503, "FORWARD_SNAPSHOTS_UNAVAILABLE")
        timeframe = V2_STRATEGIES[strategy_id][0]

        async def run() -> dict[str, Any]:
            series: dict[str, tuple[Candle, ...]] = {}
            start = history_start(strategy)
            step = timedelta(seconds=TIMEFRAME_SECONDS[timeframe])
            for instrument in sorted(PERSONAL_SPOT_INSTRUMENTS):
                symbol, candles = await stitched_history(
                    spot,
                    instrument,
                    timeframe,
                    start=start,
                    step=step,
                    correlation_id=request.state.correlation_id,
                )
                series[symbol] = candles
            verdict = await forward.latest_verdict(strategy.content_sha256)
            try:
                record = forward_record(
                    strategy,
                    series,
                    historical=None if verdict is None else verdict.historical(),
                    as_of=forward.clock(),
                )
            except ValueError as exc:
                raise error(422, "FORWARD_HISTORY_INSUFFICIENT", str(exc)) from exc
            record["historical_verdict"] = None if verdict is None else view(verdict)
            result: dict[str, Any] = _jsonable(record)
            return result

        return await respond(run())

    return router
