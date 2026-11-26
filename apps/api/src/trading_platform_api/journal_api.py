"""Local-only C-107 journal, atomically bound to exact retained Spot evidence."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
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
    SnapshotDecisionJournalEntry,
    SnapshotObservation,
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
from trading_platform_api.market_data.contracts import (
    DataQualityReport,
    DataQualityStatus,
    MarketSnapshot,
)
from trading_platform_api.spot_research import (
    Instrument,
    SpotResearchError,
    SpotResearchService,
    Timeframe,
)
from trading_platform_api.spot_research_store import (
    MAX_READ_CANDLES,
    spot_research_snapshots,
)
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


class SnapshotJournalRequest(BaseModel):
    """C-107v2 input: a declaration against the exact snapshot on screen.

    The client names the snapshot and quality report it is viewing; the server
    resolves and verifies everything else (E2c2, ADR-0031 amendment).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")
    request_id: UUID
    instrument_id: Instrument
    timeframe: Timeframe
    snapshot_id: UUID
    quality_report_id: UUID
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
    def validate_shape(self) -> SnapshotJournalRequest:
        if self.declared_action not in ("ABSTAIN", "EXTERNAL_TRADE_INTENT"):
            raise ValueError("Unsupported declared action.")
        if (self.supersedes is None) != (self.correction_reason is None):
            raise ValueError("Correction requires a reference and reason.")
        if self.supersedes is not None:
            if (
                (self.supersedes.contract_id, self.supersedes.schema_version)
                != ("C-107", "2")
                or not self.correction_reason
                or not self.correction_reason.strip()
            ):
                raise ValueError("Invalid correction parent/reason.")
        return self

    def digest(self) -> str:
        return canonical_sha256(self.model_dump(mode="python"))


JournalEntry = ResearchDecisionJournalEntry | SnapshotDecisionJournalEntry


def view(entry: JournalEntry) -> dict:
    return json.loads(canonical_json_dumps(entry))


def _served_time(value: object) -> datetime:
    if type(value) is not str:
        raise LineageError("Served snapshot time is missing.")
    return utc(datetime.fromisoformat(value.replace("Z", "+00:00")))


class JournalService:
    def __init__(
        self,
        session_factory: Callable[[], AsyncSession],
        *,
        clock: Callable[[], datetime] | None = None,
        research: SpotResearchService | None = None,
    ):
        self.sessions = session_factory
        self.clock = clock or (lambda: datetime.now(UTC))
        self.research = research

    async def _read(
        self, store: SqlAlchemyLineageStore, key: LineageKey
    ) -> JournalEntry:
        if key.version == "2":
            return await self._read_snapshot_entry(store, key, set())
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

    async def _read_snapshot_entry(
        self, store: SqlAlchemyLineageStore, key: LineageKey, seen: set[UUID]
    ) -> SnapshotDecisionJournalEntry:
        # Verify the entry, its exact snapshot/quality digests and its correction
        # chain directly; the snapshot's candles were verified when persisted.
        entry = await store.get(key)
        if type(entry) is not SnapshotDecisionJournalEntry or entry.entry_id in seen:
            raise LineageError("Not a snapshot journal entry or correction cycle.")
        seen.add(entry.entry_id)
        await store._check_references(entry)
        snapshot = await store.get(
            LineageKey("C-002", str(entry.source.artifact_id), "1")
        )
        quality = await store.get(
            LineageKey("C-003", str(entry.quality_report.artifact_id), "1")
        )
        observed = entry.snapshot_observation
        row = (
            (
                await store._session.execute(
                    select(spot_research_snapshots).where(
                        spot_research_snapshots.c.snapshot_id
                        == str(entry.source.artifact_id)
                    )
                )
            )
            .mappings()
            .one_or_none()
        )
        if (
            type(snapshot) is not MarketSnapshot
            or type(quality) is not DataQualityReport
            or quality.status is not DataQualityStatus.VALID
            or quality.snapshot_id != snapshot.snapshot_id
            or snapshot.instrument_id != observed.instrument_id
            or snapshot.as_of != observed.as_of
            or len(snapshot.market_data_ids) != observed.candle_count
            or row is None
            or row["report_id"] != str(quality.report_id)
            or row["timeframe"] != observed.timeframe
        ):
            raise LineageError("Journal snapshot evidence differs.")
        if entry.supersedes is not None:
            parent = await self._read_snapshot_entry(
                store,
                LineageKey("C-107", str(entry.supersedes.artifact_id), "2"),
                seen,
            )
            if (
                parent.recorded_at > entry.recorded_at
                or parent.profile != entry.profile
            ):
                raise LineageError("Journal correction ordering/cycle invalid.")
        return entry

    async def _bound(
        self, session: AsyncSession, request_id: UUID
    ) -> JournalEntry | None:
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
                    if (
                        saved.request_sha256 != digest
                        or type(saved) is not ResearchDecisionJournalEntry
                    ):
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

    async def _lock(self, session: AsyncSession, request_id: UUID) -> None:
        await session.execute(
            select(
                func.pg_advisory_xact_lock(
                    func.hashtextextended("C-107:" + PROFILE + ":" + str(request_id), 0)
                )
            )
        )

    async def save_snapshot(
        self, request: SnapshotJournalRequest
    ) -> SnapshotDecisionJournalEntry:
        digest = request.digest()
        async with self.sessions() as session:
            async with session.begin():
                await self._lock(session, request.request_id)
                saved = await self._bound(session, request.request_id)
                if saved is not None:
                    # An identical retry returns the original even if the
                    # snapshot has since gone stale; it is never re-enriched.
                    if (
                        saved.request_sha256 != digest
                        or type(saved) is not SnapshotDecisionJournalEntry
                    ):
                        raise error(409, "JOURNAL_REQUEST_CONFLICT")
                    return saved
                if self.research is None:
                    raise error(503, "JOURNAL_SNAPSHOT_READER_UNAVAILABLE")
                try:
                    # The same verified read the chart uses: latest accepted
                    # snapshot, deterministic quality revalidation, freshness.
                    served = await self.research.read(
                        instrument_id=request.instrument_id,
                        timeframe=request.timeframe,
                        as_of=None,
                        limit=MAX_READ_CANDLES,
                    )
                except SpotResearchError as exc:
                    raise error(
                        503 if exc.status >= 500 else 422,
                        "JOURNAL_SNAPSHOT_UNAVAILABLE",
                    ) from exc
                if served.get("snapshot_id") != str(request.snapshot_id):
                    raise error(422, "JOURNAL_SNAPSHOT_NOT_CURRENT")
                quality_view = served.get("data_quality") or {}
                if quality_view.get("report_id") != str(request.quality_report_id):
                    raise error(422, "JOURNAL_SNAPSHOT_QUALITY_MISMATCH")
                if (
                    quality_view.get("status") != "VALID"
                    or served.get("temporal_context") != "CURRENT"
                ):
                    raise error(422, "JOURNAL_SNAPSHOT_STALE_OR_INVALID")
                candles = served.get("candles") or ()
                policy = quality_view.get("policy") or {}
                freshness = policy.get("freshness_seconds")
                interval = policy.get("interval_seconds")
                if (
                    not candles
                    or type(freshness) is not int
                    or type(interval) is not int
                ):
                    raise LineageError("Served snapshot facts are incomplete.")
                last_open = _served_time(candles[-1].get("open_time"))
                fresh_until = last_open + timedelta(seconds=interval + freshness)
                store = SqlAlchemyLineageStore(session)
                snapshot = await store.get(
                    LineageKey("C-002", str(request.snapshot_id), "1")
                )
                quality = await store.get(
                    LineageKey("C-003", str(request.quality_report_id), "1")
                )
                if (
                    type(snapshot) is not MarketSnapshot
                    or type(quality) is not DataQualityReport
                    or quality.status is not DataQualityStatus.VALID
                    or quality.snapshot_id != snapshot.snapshot_id
                    or snapshot.instrument_id != request.instrument_id
                    or len(snapshot.market_data_ids) != len(candles)
                    or snapshot.as_of != _served_time(served.get("as_of"))
                ):
                    raise error(422, "JOURNAL_SNAPSHOT_MISMATCH")
                parent = None
                if request.supersedes is not None:
                    parent_ref = ref(request.supersedes)
                    parent = await self._read_snapshot_entry(
                        store,
                        LineageKey("C-107", str(parent_ref.artifact_id), "2"),
                        set(),
                    )
                    if parent.content_sha256 != parent_ref.content_sha256:
                        raise error(422, "JOURNAL_CORRECTION_PARENT_MISMATCH")
                now = utc(self.clock())
                times = [snapshot.as_of, quality.assessed_at]
                if parent is not None:
                    times.append(parent.recorded_at)
                if any(t > now for t in times):
                    raise error(422, "JOURNAL_FUTURE_EVIDENCE_OR_CLOCK_REVERSED")
                if now > fresh_until:
                    raise error(422, "JOURNAL_SNAPSHOT_STALE_OR_INVALID")
                entry = SnapshotDecisionJournalEntry(
                    request_id=request.request_id,
                    request_sha256=digest,
                    source=VersionReference(
                        "C-002",
                        snapshot.snapshot_id,
                        "1",
                        _reference_content_sha256(snapshot),
                    ),
                    quality_report=VersionReference(
                        "C-003",
                        quality.report_id,
                        "1",
                        _reference_content_sha256(quality),
                    ),
                    snapshot_observation=SnapshotObservation(
                        instrument_id=snapshot.instrument_id,
                        timeframe=request.timeframe,
                        as_of=snapshot.as_of,
                        last_candle_open_time=last_open,
                        candle_count=len(candles),
                        fresh_until=fresh_until,
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
                        version="2",
                    )
                )
                if await self._bound(session, request.request_id) != entry:
                    raise LineageError("Journal transaction readback failed.")
            if await self._bound(session, request.request_id) != entry:
                raise LineageError("Journal committed readback failed.")
            return entry

    async def read_request(self, request_id: UUID) -> JournalEntry | None:
        async with self.sessions() as session:
            return await self._bound(session, request_id)

    async def read(
        self, entry_id: UUID, digest: str, schema_version: str = "1"
    ) -> JournalEntry:
        async with self.sessions() as session:
            result = await self._read(
                SqlAlchemyLineageStore(session),
                LineageKey("C-107", str(entry_id), schema_version),
            )
            if result.content_sha256 != digest:
                raise error(404, "JOURNAL_ENTRY_NOT_FOUND")
            return result

    async def page(self, limit: int, before: UUID | None) -> dict:
        async with self.sessions() as session:
            query = select(records.c.record_id, records.c.version).where(
                records.c.contract_id == "C-107", records.c.version.in_(("1", "2"))
            )
            if before is not None:
                # Stable keyset ordering: timestamp + immutable UUID. The cursor is
                # an exact stored entry identity; no offset or client timestamp.
                anchor_version = await session.scalar(
                    select(records.c.version).where(
                        records.c.contract_id == "C-107",
                        records.c.record_id == str(before),
                        records.c.version.in_(("1", "2")),
                    )
                )
                if anchor_version is None:
                    raise LineageError("Journal cursor entry is missing.")
                anchor = await self._read(
                    SqlAlchemyLineageStore(session),
                    LineageKey("C-107", str(before), anchor_version),
                )
                from sqlalchemy import tuple_

                query = query.where(
                    tuple_(records.c.occurred_at, records.c.record_id)
                    < tuple_(anchor.recorded_at, str(anchor.entry_id))
                )
            rows = (
                await session.execute(
                    query.order_by(
                        records.c.occurred_at.desc(), records.c.record_id.desc()
                    ).limit(limit + 1)
                )
            ).all()
            entries = [
                await self._read(
                    SqlAlchemyLineageStore(session),
                    LineageKey("C-107", row[0], row[1]),
                )
                for row in rows[:limit]
            ]
            return {
                "items": [view(e) for e in entries],
                "next_cursor": str(entries[-1].entry_id) if len(rows) > limit else None,
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
                view(result)
                if type(result)
                in (ResearchDecisionJournalEntry, SnapshotDecisionJournalEntry)
                else result
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
        snapshot_request: SnapshotJournalRequest | None = None
        try:
            raw = json.loads(bytes(body))
            # C-107v2 (E2c2): a declaration against the viewed snapshot names
            # snapshot_id; every other request keeps the unchanged C-107v1 shape.
            if type(raw) is dict and "snapshot_id" in raw:
                snapshot_request = SnapshotJournalRequest.model_validate_json(
                    bytes(body)
                )
            else:
                parsed = JournalRequest.model_validate_json(bytes(body))
        except ValueError as exc:
            raise error(422, "JOURNAL_REQUEST_INVALID") from exc
        if snapshot_request is not None:
            return await respond(
                request, service(request).save_snapshot(snapshot_request)
            )
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
        if schema_version not in ("1", "2"):
            raise error(422, "JOURNAL_SCHEMA_UNSUPPORTED")
        return await respond(
            request, service(request).read(entry_id, content_sha256, schema_version)
        )

    return router
