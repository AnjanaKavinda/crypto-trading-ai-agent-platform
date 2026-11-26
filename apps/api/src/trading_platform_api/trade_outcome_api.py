"""Local-only C-108 owner trade outcomes, linked to an exact C-107 trade intent."""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from decimal import Decimal
from typing import Callable, Literal
from uuid import UUID, uuid5

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import func, select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from trading_platform_api.analysis.versioned_contracts_v5 import MarketContextV5
from trading_platform_api.contracts.serialization import (
    canonical_json_dumps,
    canonical_sha256,
)
from trading_platform_api.journal_api import JournalService, ref
from trading_platform_api.learning.decision_journal import (
    ResearchDecisionJournalEntry,
    utc,
)
from trading_platform_api.learning.trade_outcome import (
    MAX_FILLS,
    OUTCOME_NAMESPACE,
    OwnerFill,
    OwnerTradeOutcome,
)
from trading_platform_api.lineage.codec import LineageError, LineageKey
from trading_platform_api.lineage.policy import PERSONAL_SPOT_INSTRUMENTS
from trading_platform_api.lineage.store import SqlAlchemyLineageStore
from trading_platform_api.lineage.tables import records
from trading_platform_api.strategy_api import (
    ApiVersionReference,
    StrategySignalApiError,
)

PROFILE = "PERSONAL_SPOT_RESEARCH"
DECIMAL_TEXT = re.compile(r"^(0|[1-9][0-9]{0,14})(\.[0-9]{1,18})?$")


def error(status: int, code: str) -> StrategySignalApiError:
    return StrategySignalApiError(
        status=status,
        code=code,
        title="Trade outcome request rejected",
        detail="The trade outcome or its linked journal entry could not be verified. No outcome is confirmed; retry the same request key after recovery.",
    )


def decimal_text(value: str) -> Decimal:
    if type(value) is not str or not DECIMAL_TEXT.fullmatch(value):
        raise ValueError("Amounts are plain decimal strings, e.g. '0.015'.")
    return Decimal(value)


class FillRequest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    side: Literal["BUY", "SELL"]
    quantity: str = Field(strict=True)
    price_usdt: str = Field(strict=True)
    executed_at: datetime
    fee_source: Literal["STATEMENT", "ESTIMATE", "UNKNOWN"]
    fee_usdt: str | None = Field(default=None, strict=True)

    @field_validator("executed_at")
    @classmethod
    def timestamp(cls, value: datetime) -> datetime:
        return utc(value)

    @field_validator("quantity", "price_usdt", "fee_usdt")
    @classmethod
    def amount(cls, value: str | None) -> str | None:
        if value is not None:
            decimal_text(value)
        return value

    def fill(self) -> OwnerFill:
        return OwnerFill(
            self.side,
            decimal_text(self.quantity),
            decimal_text(self.price_usdt),
            self.executed_at,
            self.fee_source,
            None if self.fee_usdt is None else decimal_text(self.fee_usdt),
        )


class TradeOutcomeRequest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    request_id: UUID
    journal_entry: ApiVersionReference
    fills: tuple[FillRequest, ...] = Field(min_length=1, max_length=MAX_FILLS)
    note: str = Field(default="", max_length=2000, strict=True)
    supersedes: ApiVersionReference | None = None
    correction_reason: str | None = Field(default=None, max_length=2000, strict=True)

    @model_validator(mode="after")
    def validate_shape(self) -> TradeOutcomeRequest:
        if (self.journal_entry.contract_id, self.journal_entry.schema_version) != (
            "C-107",
            "1",
        ):
            raise ValueError("An exact C-107v1 journal entry is required.")
        if (self.supersedes is None) != (self.correction_reason is None):
            raise ValueError("Correction requires a reference and reason.")
        if self.supersedes is not None and (
            (self.supersedes.contract_id, self.supersedes.schema_version)
            != ("C-108", "1")
            or not self.correction_reason
            or not self.correction_reason.strip()
        ):
            raise ValueError("Invalid correction parent/reason.")
        for fill in self.fills:
            fill.fill()
        return self

    def digest(self) -> str:
        return canonical_sha256(self.model_dump(mode="python"))


def view(outcome: OwnerTradeOutcome) -> dict:
    return json.loads(canonical_json_dumps(outcome))


def outcome_key(request_id: UUID) -> LineageKey:
    return LineageKey("C-108", str(uuid5(OUTCOME_NAMESPACE, f"C-108:1:{request_id}")))


class TradeOutcomeService:
    def __init__(
        self,
        session_factory: Callable[[], AsyncSession],
        *,
        clock: Callable[[], datetime] | None = None,
    ):
        self.sessions = session_factory
        self.clock = clock or (lambda: datetime.now(UTC))
        self.journal = JournalService(session_factory)

    async def _read(
        self, store: SqlAlchemyLineageStore, key: LineageKey
    ) -> OwnerTradeOutcome:
        graph = await store.resolve((key,))
        outcome = graph[key]
        if type(outcome) is not OwnerTradeOutcome:
            raise LineageError("Not a trade outcome.")
        child = outcome
        seen = {child.outcome_id}
        while child.supersedes is not None:
            parent = graph[LineageKey("C-108", str(child.supersedes.artifact_id))]
            if (
                type(parent) is not OwnerTradeOutcome
                or parent.outcome_id in seen
                or parent.recorded_at > child.recorded_at
                or parent.journal_entry != child.journal_entry
            ):
                raise LineageError("Trade outcome correction ordering invalid.")
            seen.add(parent.outcome_id)
            child = parent
        return outcome

    async def _existing(
        self, session: AsyncSession, request_id: UUID
    ) -> OwnerTradeOutcome | None:
        key = outcome_key(request_id)
        found = (
            await session.execute(
                select(records.c.record_id).where(
                    records.c.contract_id == key.contract_id,
                    records.c.record_id == key.record_id,
                    records.c.version == key.version,
                )
            )
        ).scalar_one_or_none()
        if found is None:
            return None
        outcome = await self._read(SqlAlchemyLineageStore(session), key)
        if outcome.request_id != request_id:
            raise LineageError("Corrupt trade outcome request identity.")
        return outcome

    async def save(self, request: TradeOutcomeRequest) -> OwnerTradeOutcome:
        digest = request.digest()
        async with self.sessions() as session:
            async with session.begin():
                await session.execute(
                    select(
                        func.pg_advisory_xact_lock(
                            func.hashtextextended(
                                "C-108:" + PROFILE + ":" + str(request.request_id), 0
                            )
                        )
                    )
                )
                saved = await self._existing(session, request.request_id)
                if saved is not None:
                    if saved.request_sha256 != digest:
                        raise error(409, "TRADE_OUTCOME_REQUEST_CONFLICT")
                    return saved
                store = SqlAlchemyLineageStore(session)
                journal_ref = ref(request.journal_entry)
                journal_key = LineageKey("C-107", str(journal_ref.artifact_id), "1")
                journal = await self.journal._read(store, journal_key)
                if (
                    type(journal) is not ResearchDecisionJournalEntry
                    or journal.content_sha256 != journal_ref.content_sha256
                ):
                    raise error(422, "TRADE_OUTCOME_JOURNAL_MISMATCH")
                if journal.declared_action != "EXTERNAL_TRADE_INTENT":
                    raise error(422, "TRADE_OUTCOME_TRADE_INTENT_REQUIRED")
                context_key = LineageKey(
                    "C-006", str(journal.market_context.artifact_id), "5"
                )
                context = (await store.resolve((context_key,)))[context_key]
                instrument = getattr(context, "instrument_id", None)
                if (
                    type(context) is not MarketContextV5
                    or instrument not in PERSONAL_SPOT_INSTRUMENTS
                ):
                    raise error(422, "TRADE_OUTCOME_SPOT_CONTEXT_REQUIRED")
                if request.supersedes is not None:
                    parent_ref = ref(request.supersedes)
                    parent = await self._read(
                        store, LineageKey("C-108", str(parent_ref.artifact_id))
                    )
                    if (
                        parent.content_sha256 != parent_ref.content_sha256
                        or parent.journal_entry != journal_ref
                    ):
                        raise error(422, "TRADE_OUTCOME_CORRECTION_PARENT_MISMATCH")
                now = utc(self.clock())
                try:
                    outcome = OwnerTradeOutcome(
                        request_id=request.request_id,
                        request_sha256=digest,
                        journal_entry=journal_ref,
                        journal_recorded_at=journal.recorded_at,
                        instrument_id=str(instrument),
                        fills=tuple(fill.fill() for fill in request.fills),
                        recorded_at=now,
                        note=request.note,
                        supersedes=(
                            ref(request.supersedes) if request.supersedes else None
                        ),
                        correction_reason=request.correction_reason,
                    )
                except ValueError as exc:
                    raise error(422, "TRADE_OUTCOME_FACTS_INVALID") from exc
                await store.append(outcome)
                if await self._existing(session, request.request_id) != outcome:
                    raise LineageError("Trade outcome transaction readback failed.")
            if await self._existing(session, request.request_id) != outcome:
                raise LineageError("Trade outcome committed readback failed.")
            return outcome

    async def read(self, outcome_id: UUID, digest: str) -> OwnerTradeOutcome:
        async with self.sessions() as session:
            result = await self._read(
                SqlAlchemyLineageStore(session), LineageKey("C-108", str(outcome_id))
            )
            if result.content_sha256 != digest:
                raise error(404, "TRADE_OUTCOME_NOT_FOUND")
            return result

    async def read_request(self, request_id: UUID) -> OwnerTradeOutcome | None:
        async with self.sessions() as session:
            return await self._existing(session, request_id)

    async def page(self, limit: int, before: UUID | None) -> dict:
        async with self.sessions() as session:
            store = SqlAlchemyLineageStore(session)
            query = select(records.c.record_id).where(
                records.c.contract_id == "C-108", records.c.version == "1"
            )
            if before is not None:
                anchor = await self._read(store, LineageKey("C-108", str(before)))
                query = query.where(
                    tuple_(records.c.occurred_at, records.c.record_id)
                    < tuple_(anchor.recorded_at, str(anchor.outcome_id))
                )
            ids: list[str] = list(
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
            items = [
                await self._read(store, LineageKey("C-108", value))
                for value in ids[:limit]
            ]
            return {
                "items": [view(item) for item in items],
                "next_cursor": str(items[-1].outcome_id) if len(ids) > limit else None,
            }


def create_trade_outcome_router() -> APIRouter:
    router = APIRouter(prefix="/api/research/owner-outcomes", tags=["owner-outcomes"])

    def service(request: Request) -> TradeOutcomeService:
        settings = request.app.state.settings
        if settings.mode.value != "research" or settings.environment.value not in {
            "dev",
            "test",
        }:
            raise error(403, "TRADE_OUTCOME_LOCAL_RESEARCH_REQUIRED")
        result = request.app.state.trade_outcome_service
        if result is None:
            raise error(503, "TRADE_OUTCOME_STORAGE_UNAVAILABLE")
        return result

    async def respond(operation) -> JSONResponse:
        try:
            result = await operation
            content = view(result) if type(result) is OwnerTradeOutcome else result
            if content is None:
                raise error(404, "TRADE_OUTCOME_NOT_FOUND")
            return JSONResponse(content, headers={"Cache-Control": "no-store"})
        except StrategySignalApiError:
            raise
        except (LineageError, ValueError, TypeError) as exc:
            raise error(422, "TRADE_OUTCOME_EVIDENCE_INVALID") from exc
        except Exception as exc:
            # Never log the body/note or reveal database details.
            raise error(503, "TRADE_OUTCOME_STORAGE_UNCONFIRMED") from exc

    @router.post("")
    async def save(request: Request) -> JSONResponse:
        allowed = request.app.state.allowed_origin
        if allowed is None or request.headers.get("origin") != allowed:
            raise error(403, "TRADE_OUTCOME_ORIGIN_REQUIRED")
        if (
            request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
            != "application/json"
        ):
            raise error(415, "TRADE_OUTCOME_JSON_REQUIRED")
        body = bytearray()
        async for chunk in request.stream():
            if len(body) + len(chunk) > 65536:
                raise error(413, "TRADE_OUTCOME_REQUEST_TOO_LARGE")
            body.extend(chunk)
        try:
            parsed = TradeOutcomeRequest.model_validate_json(bytes(body))
        except ValueError as exc:
            raise error(422, "TRADE_OUTCOME_REQUEST_INVALID") from exc
        return await respond(service(request).save(parsed))

    @router.get("")
    async def page(
        request: Request,
        limit: int = Query(default=20, ge=1, le=100),
        cursor: UUID | None = None,
    ) -> JSONResponse:
        return await respond(service(request).page(limit, cursor))

    @router.get("/requests/{request_id}")
    async def read_request(request_id: UUID, request: Request) -> JSONResponse:
        return await respond(service(request).read_request(request_id))

    @router.get("/{outcome_id}")
    async def read(
        outcome_id: UUID,
        request: Request,
        schema_version: str = Query(),
        content_sha256: str = Query(pattern="^[0-9a-f]{64}$"),
    ) -> JSONResponse:
        if schema_version != "1":
            raise error(422, "TRADE_OUTCOME_SCHEMA_UNSUPPORTED")
        return await respond(service(request).read(outcome_id, content_sha256))

    return router
