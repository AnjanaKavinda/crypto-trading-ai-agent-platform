"""Local-only C-107 journal, atomically bound to exact retained Spot evidence."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Callable
from uuid import UUID

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from trading_platform_api.analysis.versioned_contracts_v5 import MarketContextV5
from trading_platform_api.contracts.serialization import (
    canonical_json_dumps,
    canonical_sha256,
)
from trading_platform_api.learning.decision_journal import (
    SOURCE_SCHEMAS,
    LifecyclePin,
    ResearchDecisionJournalEntry,
    SourceObservation,
    utc,
)
from trading_platform_api.lineage.codec import LineageError, LineageKey
from trading_platform_api.lineage.policy import PERSONAL_SPOT_INSTRUMENTS
from trading_platform_api.lineage.store import (
    SqlAlchemyLineageStore,
    _occurred_at,
    _reference_content_sha256,
)
from trading_platform_api.lineage.tables import records
from trading_platform_api.lineage.tables import research_journal_requests as bindings
from trading_platform_api.strategy.contracts import VersionReference
from trading_platform_api.strategy.lifecycle import (
    SignalLifecycleEvent,
    SqlAlchemySignalLifecycleStore,
)
from trading_platform_api.strategy_api import (
    ApiVersionReference,
    StrategySignalApiError,
    _artifact_view,
    _lifecycle_subject,
)

PROFILE = "PERSONAL_SPOT_RESEARCH"


def error(status: int, code: str) -> StrategySignalApiError:
    return StrategySignalApiError(
        status=status,
        code=code,
        title="Research journal request rejected",
        detail="The journal request or retained evidence could not be verified. No new declaration is confirmed; retry the same request key after recovery.",
    )


def ref(value: ApiVersionReference) -> VersionReference:
    return VersionReference(
        value.contract_id, value.artifact_id, value.schema_version, value.content_sha256
    )


class JournalRequest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    request_id: UUID
    source: ApiVersionReference
    declared_action: str = Field(strict=True)
    declared_at: datetime
    note: str = Field(default="", max_length=2000, strict=True)
    supersedes: ApiVersionReference | None = None
    correction_reason: str | None = Field(default=None, max_length=2000, strict=True)

    @field_validator("declared_at")
    @classmethod
    def timestamp(cls, value: datetime) -> datetime:
        return utc(value)

    @model_validator(mode="after")
    def validate_shape(self) -> JournalRequest:
        if SOURCE_SCHEMAS.get(self.source.contract_id) != self.source.schema_version:
            raise ValueError("Unsupported source contract/schema.")
        if self.declared_action not in ("ABSTAIN", "EXTERNAL_TRADE_INTENT"):
            raise ValueError("Unsupported declared action.")
        if (self.supersedes is None) != (self.correction_reason is None):
            raise ValueError("Correction requires a reference and reason.")
        if self.supersedes is not None:
            if (
                (self.supersedes.contract_id, self.supersedes.schema_version)
                != ("C-107", "1")
                or not self.correction_reason
                or not self.correction_reason.strip()
            ):
                raise ValueError("Invalid correction parent/reason.")
        return self

    def digest(self) -> str:
        # Python-mode UTC values use the existing canonical timestamp codec.
        return canonical_sha256(self.model_dump(mode="python"))


def view(entry: ResearchDecisionJournalEntry) -> dict:
    return json.loads(canonical_json_dumps(entry))


class JournalService:
    def __init__(
        self,
        session_factory: Callable[[], AsyncSession],
        *,
        clock: Callable[[], datetime] | None = None,
    ):
        self.sessions = session_factory
        self.clock = clock or (lambda: datetime.now(UTC))

    async def _read(
        self, store: SqlAlchemyLineageStore, key: LineageKey
    ) -> ResearchDecisionJournalEntry:
        graph = await store.resolve((key,))
        entry = graph[key]
        if type(entry) is not ResearchDecisionJournalEntry:
            raise LineageError("Not a journal entry.")
        for item in graph.values():
            if type(item) is not ResearchDecisionJournalEntry:
                continue
            source_key = LineageKey(
                item.source.artifact_type,
                str(item.source.artifact_id),
                item.source.version,
            )
            source = graph[source_key]
            if (
                getattr(source, "market_context_id", None)
                != item.market_context.artifact_id
            ):
                raise LineageError("Journal source/context mismatch.")
            observation = item.source_observation
            if observation.occurred_at != _occurred_at(
                source
            ) or observation.expires_at != getattr(source, "expires_at", None):
                raise LineageError("Journal source times differ.")
            pin = observation.lifecycle_pin
            subject = _lifecycle_subject(source_key, source)
            if pin is not None:
                if subject is None:
                    raise LineageError("Journal lifecycle subject unavailable.")
                history = await SqlAlchemySignalLifecycleStore(store._session).history(
                    subject
                )
                event = next(
                    (event for event in history if event.event_id == pin.event_id), None
                )
                if (
                    event is None
                    or canonical_sha256(event) != pin.content_sha256
                    or event.resulting_state.value != observation.projection_state
                    or max(event.event_time, event.recorded_at) > item.recorded_at
                ):
                    raise LineageError("Journal pinned lifecycle evidence differs.")
            seen = {item.entry_id}
            child = item
            while child.supersedes is not None:
                parent = graph[
                    LineageKey("C-107", str(child.supersedes.artifact_id), "1")
                ]
                if (
                    type(parent) is not ResearchDecisionJournalEntry
                    or parent.entry_id in seen
                    or parent.recorded_at > child.recorded_at
                    or parent.profile != child.profile
                ):
                    raise LineageError("Journal correction ordering/cycle invalid.")
                seen.add(parent.entry_id)
                child = parent
        return entry

    async def _bound(
        self, session: AsyncSession, request_id: UUID
    ) -> ResearchDecisionJournalEntry | None:
        row = (
            (
                await session.execute(
                    select(bindings).where(
                        bindings.c.profile == PROFILE,
                        bindings.c.request_id == str(request_id),
                    )
                )
            )
            .mappings()
            .one_or_none()
        )
        if row is None:
            return None
        entry = await self._read(
            SqlAlchemyLineageStore(session),
            LineageKey(row["contract_id"], row["record_id"], row["version"]),
        )
        if (
            entry.request_id != request_id
            or entry.request_sha256 != row["request_sha256"]
        ):
            raise LineageError("Corrupt journal request binding.")
        return entry

    async def save(self, request: JournalRequest) -> ResearchDecisionJournalEntry:
        digest = request.digest()
        async with self.sessions() as session:
            async with session.begin():
                # Serialize identical keys across processes/restarts without making a
                # transient reservation or confirming an uncommitted declaration.
                await session.execute(
                    select(
                        func.pg_advisory_xact_lock(
                            func.hashtextextended(
                                "C-107:" + PROFILE + ":" + str(request.request_id), 0
                            )
                        )
                    )
                )
                saved = await self._bound(session, request.request_id)
                if saved is not None:
                    if saved.request_sha256 != digest:
                        raise error(409, "JOURNAL_REQUEST_CONFLICT")
                    return saved
                store = SqlAlchemyLineageStore(session)
                source_ref = ref(request.source)
                key = LineageKey(
                    source_ref.artifact_type,
                    str(source_ref.artifact_id),
                    source_ref.version,
                )
                resolved = await store.resolve((key,))
                source = resolved[key]
                if _reference_content_sha256(source) != source_ref.content_sha256:
                    raise error(422, "JOURNAL_SOURCE_MISMATCH")
                context_id = getattr(source, "market_context_id", None)
                context_key = LineageKey("C-006", str(context_id), "5")
                context = resolved.get(context_key)
                if (
                    type(context) is not MarketContextV5
                    or getattr(context, "instrument_id", None)
                    not in PERSONAL_SPOT_INSTRUMENTS
                ):
                    raise error(422, "JOURNAL_SPOT_CONTEXT_REQUIRED")
                for name in ("instrument_id", "asset", "timeframe"):
                    source_value = getattr(source, name, None)
                    if source_value is not None and source_value != getattr(
                        context, name, None
                    ):
                        raise error(422, "JOURNAL_SCOPE_MISMATCH")
                occurred = _occurred_at(source)
                if occurred is None:
                    raise error(422, "JOURNAL_SOURCE_TIME_REQUIRED")
                artifact = await _artifact_view(store, key, source, occurred)
                pin = None
                history: tuple[SignalLifecycleEvent, ...] = ()
                subject = _lifecycle_subject(key, source)
                if subject is not None and artifact.lifecycle_events:
                    history = await SqlAlchemySignalLifecycleStore(session).history(
                        subject
                    )
                    observed_id = artifact.lifecycle_events[-1].event_id
                    event = next(
                        (e for e in history if e.event_id == observed_id), None
                    )
                    if event is None:
                        raise LineageError("Observed lifecycle event unavailable.")
                    pin = LifecyclePin(event.event_id, canonical_sha256(event))
                parent = None
                if request.supersedes is not None:
                    parent_ref = ref(request.supersedes)
                    parent = await self._read(
                        store, LineageKey("C-107", str(parent_ref.artifact_id), "1")
                    )
                    if (
                        parent.content_sha256 != parent_ref.content_sha256
                        or parent.profile != PROFILE
                    ):
                        raise error(422, "JOURNAL_CORRECTION_PARENT_MISMATCH")
                now = utc(self.clock())
                times = [
                    t
                    for record in resolved.values()
                    if (t := _occurred_at(record)) is not None
                ]
                times += [t for e in history for t in (e.event_time, e.recorded_at)]
                if parent is not None:
                    times.append(parent.recorded_at)
                if any(t > now for t in times):
                    raise error(422, "JOURNAL_FUTURE_EVIDENCE_OR_CLOCK_REVERSED")
                entry = ResearchDecisionJournalEntry(
                    request_id=request.request_id,
                    request_sha256=digest,
                    source=source_ref,
                    market_context=VersionReference(
                        "C-006",
                        context.context_id,
                        "5",
                        _reference_content_sha256(context),
                    ),
                    source_observation=SourceObservation(
                        artifact.projection_state,
                        artifact.reasons,
                        artifact.occurred_at,
                        artifact.valid_until,
                        pin,
                    ),
                    declared_action=request.declared_action,
                    declared_at=request.declared_at,
                    recorded_at=now,
                    note=request.note,
                    supersedes=ref(request.supersedes) if request.supersedes else None,
                    correction_reason=request.correction_reason,
                )
                await store.append(entry)
                await session.execute(
                    insert(bindings).values(
                        profile=PROFILE,
                        request_id=str(request.request_id),
                        request_sha256=digest,
                        contract_id="C-107",
                        record_id=str(entry.entry_id),
                        version="1",
                    )
                )
                if await self._bound(session, request.request_id) != entry:
                    raise LineageError("Journal transaction readback failed.")
            # Success requires committed canonical readback, not only an insert.
            if await self._bound(session, request.request_id) != entry:
                raise LineageError("Journal committed readback failed.")
            return entry

    async def read_request(
        self, request_id: UUID
    ) -> ResearchDecisionJournalEntry | None:
        async with self.sessions() as session:
            return await self._bound(session, request_id)

    async def read(self, entry_id: UUID, digest: str) -> ResearchDecisionJournalEntry:
        async with self.sessions() as session:
            result = await self._read(
                SqlAlchemyLineageStore(session), LineageKey("C-107", str(entry_id), "1")
            )
            if result.content_sha256 != digest:
                raise error(404, "JOURNAL_ENTRY_NOT_FOUND")
            return result

    async def page(self, limit: int, before: UUID | None) -> dict:
        async with self.sessions() as session:
            query = select(records.c.record_id).where(
                records.c.contract_id == "C-107", records.c.version == "1"
            )
            if before is not None:
                # Stable keyset ordering: timestamp + immutable UUID. The cursor is
                # an exact stored entry identity; no offset or client timestamp.
                anchor = await self._read(
                    SqlAlchemyLineageStore(session),
                    LineageKey("C-107", str(before), "1"),
                )
                from sqlalchemy import tuple_

                query = query.where(
                    tuple_(records.c.occurred_at, records.c.record_id)
                    < tuple_(anchor.recorded_at, str(anchor.entry_id))
                )
            ids: list[str] = list(
                (
                    (
                        await session.execute(
                            query.order_by(
                                records.c.occurred_at.desc(), records.c.record_id.desc()
                            ).limit(limit + 1)
                        )
                    )
                    .scalars()
                    .all()
                )
            )
            entries = [
                await self._read(
                    SqlAlchemyLineageStore(session), LineageKey("C-107", value, "1")
                )
                for value in ids[:limit]
            ]
            return {
                "items": [view(e) for e in entries],
                "next_cursor": str(entries[-1].entry_id) if len(ids) > limit else None,
            }


def create_journal_router() -> APIRouter:
    router = APIRouter(
        prefix="/api/research/decision-journal", tags=["research-journal"]
    )

    def service(request: Request) -> JournalService:
        settings = request.app.state.settings
        if settings.mode.value != "research" or settings.environment.value not in {
            "dev",
            "test",
        }:
            raise error(403, "JOURNAL_LOCAL_RESEARCH_REQUIRED")
        result = request.app.state.journal_service
        if result is None:
            raise error(503, "JOURNAL_STORAGE_UNAVAILABLE")
        return result

    async def respond(request: Request, operation) -> JSONResponse:
        try:
            result = await operation
            content = (
                view(result) if type(result) is ResearchDecisionJournalEntry else result
            )
            if content is None:
                raise error(404, "JOURNAL_ENTRY_NOT_FOUND")
            return JSONResponse(content, headers={"Cache-Control": "no-store"})
        except StrategySignalApiError:
            raise
        except (LineageError, ValueError, TypeError) as exc:
            raise error(422, "JOURNAL_EVIDENCE_INVALID") from exc
        except Exception as exc:
            # Never log the body/note or reveal database/provider details.
            raise error(503, "JOURNAL_STORAGE_UNCONFIRMED") from exc

    @router.post("")
    async def save(request: Request) -> JSONResponse:
        allowed = request.app.state.allowed_origin
        if allowed is None or request.headers.get("origin") != allowed:
            raise error(403, "JOURNAL_ORIGIN_REQUIRED")
        if (
            request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
            != "application/json"
        ):
            raise error(415, "JOURNAL_JSON_REQUIRED")
        body = bytearray()
        async for chunk in request.stream():
            if len(body) + len(chunk) > 16384:
                raise error(413, "JOURNAL_REQUEST_TOO_LARGE")
            body.extend(chunk)
        try:
            parsed = JournalRequest.model_validate_json(bytes(body))
        except ValueError as exc:
            raise error(422, "JOURNAL_REQUEST_INVALID") from exc
        return await respond(request, service(request).save(parsed))

    @router.get("")
    async def page(
        request: Request,
        limit: int = Query(default=20, ge=1, le=100),
        cursor: UUID | None = None,
    ) -> JSONResponse:
        return await respond(request, service(request).page(limit, cursor))

    @router.get("/requests/{request_id}")
    async def read_request(request_id: UUID, request: Request) -> JSONResponse:
        return await respond(request, service(request).read_request(request_id))

    @router.get("/{entry_id}")
    async def read(
        entry_id: UUID,
        request: Request,
        schema_version: str = Query(),
        content_sha256: str = Query(pattern="^[0-9a-f]{64}$"),
    ) -> JSONResponse:
        if schema_version != "1":
            raise error(422, "JOURNAL_SCHEMA_UNSUPPORTED")
        return await respond(request, service(request).read(entry_id, content_sha256))

    return router
