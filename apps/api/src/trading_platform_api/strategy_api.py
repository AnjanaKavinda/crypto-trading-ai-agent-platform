"""Bounded PERSONAL_SPOT_RESEARCH strategy/signal API foundation."""

from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from typing import Any, Callable, Protocol
from uuid import UUID

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from trading_platform_api.config import DeploymentEnvironment, OperatingMode
from trading_platform_api.contracts.serialization import canonical_sha256
from trading_platform_api.strategy.contracts import VersionReference
from trading_platform_api.strategy.lifecycle import SqlAlchemySignalLifecycleStore

PROFILE = "PERSONAL_SPOT_RESEARCH"
MAX_PAGE_SIZE = 100


class StrategySignalApiError(RuntimeError):
    def __init__(
        self,
        *,
        status: int,
        code: str,
        title: str,
        detail: str,
    ) -> None:
        super().__init__(code)
        self.status = status
        self.code = code
        self.title = title
        self.detail = detail


class ApiVersionReference(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    contract_id: str = Field(min_length=1, max_length=32, strict=True)
    artifact_id: UUID
    schema_version: str = Field(min_length=1, max_length=128, strict=True)
    content_sha256: str = Field(min_length=64, max_length=64, strict=True)

    @field_validator("content_sha256")
    @classmethod
    def validate_digest(cls, value: str) -> str:
        if any(ch not in "0123456789abcdef" for ch in value):
            raise ValueError("content_sha256 must be lowercase SHA-256")
        return value


class LifecycleEventView(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    event_id: UUID
    prior_state: str | None
    resulting_state: str
    event_type: str
    cause: str
    event_time: datetime
    recorded_at: datetime
    correlation_id: str
    source_references: tuple[ApiVersionReference, ...] = Field(max_length=32)

    @field_validator("event_time", "recorded_at")
    @classmethod
    def normalize_event_time(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("timestamps must be timezone-aware")
        return value.astimezone(UTC)


class StrategyArtifactView(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    reference: ApiVersionReference
    occurred_at: datetime
    as_of: datetime | None = None
    valid_until: datetime | None = None
    projection_state: str | None = Field(default=None, max_length=32)
    reasons: tuple[str, ...] = Field(default=(), max_length=32)
    lineage: tuple[ApiVersionReference, ...] = Field(default=(), max_length=64)
    lifecycle_events: tuple[LifecycleEventView, ...] = Field(default=(), max_length=64)

    @field_validator("occurred_at", "as_of", "valid_until")
    @classmethod
    def normalize_time(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("timestamps must be timezone-aware")
        return value.astimezone(UTC)


class StrategyArtifactPage(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    items: tuple[StrategyArtifactView, ...]
    next_cursor: str | None
    watch_status: str = "UNAVAILABLE_NOT_PRODUCED"


class StrategyEvaluationRequest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    profile: str = Field(default=PROFILE, strict=True)
    strategy_version: ApiVersionReference
    market_context: ApiVersionReference

    @field_validator("profile")
    @classmethod
    def validate_profile(cls, value: str) -> str:
        if value != PROFILE:
            raise ValueError("unsupported research profile")
        return value

    @field_validator("strategy_version")
    @classmethod
    def validate_strategy(cls, value: ApiVersionReference) -> ApiVersionReference:
        if value.contract_id != "C-021" or value.schema_version != "2":
            raise ValueError("strategy_version must reference C-021 schema 2")
        return value

    @field_validator("market_context")
    @classmethod
    def validate_context(cls, value: ApiVersionReference) -> ApiVersionReference:
        if value.contract_id != "C-006" or value.schema_version != "5":
            raise ValueError("market_context must reference C-006 schema 5")
        return value


class StrategyEvaluationResponse(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    request_digest: str
    projection_state: str
    artifacts: tuple[StrategyArtifactView, ...]
    watch_status: str = "UNAVAILABLE_NOT_PRODUCED"

    @field_validator("request_digest")
    @classmethod
    def validate_request_digest(cls, value: str) -> str:
        if len(value) != 64 or any(ch not in "0123456789abcdef" for ch in value):
            raise ValueError("request_digest must be lowercase SHA-256")
        return value


@dataclass(frozen=True, slots=True)
class ArtifactListQuery:
    contract_id: str | None
    schema_version: str | None
    projection_state: str | None
    limit: int
    cursor: str | None


class StrategySignalApiService(Protocol):
    async def list_artifacts(
        self, query: ArtifactListQuery
    ) -> StrategyArtifactPage: ...

    async def get_artifact(
        self,
        *,
        contract_id: str,
        artifact_id: UUID,
        schema_version: str,
        content_sha256: str,
    ) -> StrategyArtifactView | None: ...

    async def evaluate(
        self,
        request: StrategyEvaluationRequest,
        *,
        correlation_id: str,
    ) -> StrategyEvaluationResponse: ...


class UnavailableStrategySignalApiService:
    """Fail-closed default until exact domain resolvers are injected."""

    @staticmethod
    def _unavailable() -> StrategySignalApiError:
        return StrategySignalApiError(
            status=503,
            code="STRATEGY_SIGNAL_RESOLVER_UNAVAILABLE",
            title="Strategy research resolver unavailable",
            detail="The exact strategy research resolver is not configured.",
        )

    async def list_artifacts(self, query: ArtifactListQuery) -> StrategyArtifactPage:
        del query
        raise self._unavailable()

    async def get_artifact(
        self,
        *,
        contract_id: str,
        artifact_id: UUID,
        schema_version: str,
        content_sha256: str,
    ) -> StrategyArtifactView | None:
        del contract_id, artifact_id, schema_version, content_sha256
        raise self._unavailable()

    async def evaluate(
        self,
        request: StrategyEvaluationRequest,
        *,
        correlation_id: str,
    ) -> StrategyEvaluationResponse:
        del request, correlation_id
        raise self._unavailable()


class SqlAlchemyStrategySignalApiService:
    """Exact immutable artifact reads and fail-closed evaluate binding service."""

    _ARTIFACTS = frozenset({"C-023", "C-024", "C-025", "C-026", "C-028", "C-070"})
    _SCHEMAS = {
        "C-023": frozenset({"1"}),
        "C-024": frozenset({"2"}),
        "C-025": frozenset({"2"}),
        "C-026": frozenset({"2"}),
        "C-028": frozenset({"2"}),
        "C-070": frozenset({"2"}),
    }

    def __init__(
        self,
        session_factory: Callable[[], AsyncSession],
        *,
        environment: DeploymentEnvironment,
        mode: OperatingMode,
    ) -> None:
        self._session_factory = session_factory
        self._environment = environment
        self._mode = mode

    async def list_artifacts(self, query: ArtifactListQuery) -> StrategyArtifactPage:
        if query.contract_id is not None and query.contract_id not in self._ARTIFACTS:
            raise StrategySignalApiError(
                status=422,
                code="UNSUPPORTED_ARTIFACT_FILTER",
                title="Unsupported artifact filter",
                detail="The requested strategy artifact contract is not supported.",
            )
        if query.schema_version is not None and (
            query.schema_version not in self._supported_schemas(query.contract_id)
        ):
            raise StrategySignalApiError(
                status=422,
                code="UNSUPPORTED_ARTIFACT_SCHEMA",
                title="Unsupported artifact schema",
                detail="The requested strategy artifact schema is not supported.",
            )
        cursor_position = (
            decode_cursor(
                query.cursor,
                contract_id=query.contract_id,
                schema_version=query.schema_version,
                projection_state=query.projection_state,
            )
            if query.cursor is not None
            else None
        )
        scan_after: tuple[datetime, str, str, str] | None = (
            (
                cursor_position[0],
                cursor_position[1],
                cursor_position[2],
                str(cursor_position[3]),
            )
            if cursor_position is not None
            else None
        )
        items: list[StrategyArtifactView] = []
        scanned = 0
        exhausted = False
        async with self._session_factory() as session:
            from trading_platform_api.lineage.store import SqlAlchemyLineageStore

            store = SqlAlchemyLineageStore(session)
            while len(items) <= query.limit and not exhausted and scanned < 2000:
                batch_limit = min(100, max(query.limit + 1 - len(items), 1))
                batch = await store.list_strategy_artifact_records(
                    contract_id=query.contract_id,
                    schema_version=query.schema_version,
                    limit=batch_limit,
                    after=scan_after,
                )
                if not batch:
                    exhausted = True
                    break
                for key, record, occurred_at in batch:
                    scan_after = (
                        occurred_at,
                        key.contract_id,
                        key.version,
                        key.record_id,
                    )
                    scanned += 1
                    view = await _artifact_view(store, key, record, occurred_at)
                    if (
                        query.projection_state is None
                        or view.projection_state == query.projection_state
                    ):
                        items.append(view)
                        if len(items) > query.limit:
                            break
                if len(batch) < batch_limit:
                    exhausted = True
            if scanned >= 2000 and len(items) <= query.limit and not exhausted:
                raise StrategySignalApiError(
                    status=503,
                    code="ARTIFACT_FILTER_SCAN_LIMIT",
                    title="Artifact page could not be completed",
                    detail="The requested filter exceeds the bounded read budget.",
                )
        has_more = len(items) > query.limit or (not exhausted and scanned > 0)
        page_items = tuple(items[: query.limit])
        next_cursor = None
        if has_more and page_items:
            last = page_items[-1]
            next_cursor = encode_cursor(
                occurred_at=last.occurred_at,
                event_id=last.reference.artifact_id,
                event_contract_id=last.reference.contract_id,
                event_schema_version=last.reference.schema_version,
                contract_id=query.contract_id,
                schema_version=query.schema_version,
                projection_state=query.projection_state,
            )
        elif has_more and scan_after is not None:
            # An empty filtered page can still advance past nonmatching rows.
            next_cursor = encode_cursor(
                occurred_at=scan_after[0],
                event_id=UUID(scan_after[3]),
                event_contract_id=scan_after[1],
                event_schema_version=scan_after[2],
                contract_id=query.contract_id,
                schema_version=query.schema_version,
                projection_state=query.projection_state,
            )
        return StrategyArtifactPage(items=page_items, next_cursor=next_cursor)

    async def get_artifact(
        self,
        *,
        contract_id: str,
        artifact_id: UUID,
        schema_version: str,
        content_sha256: str,
    ) -> StrategyArtifactView | None:
        if contract_id not in self._ARTIFACTS:
            return None
        if schema_version not in self._SCHEMAS[contract_id]:
            return None
        from trading_platform_api.lineage.codec import LineageError, LineageKey
        from trading_platform_api.lineage.store import (
            SqlAlchemyLineageStore,
            _occurred_at,
            _reference_content_sha256,
        )

        key = LineageKey(contract_id, str(artifact_id), schema_version)
        async with self._session_factory() as session:
            store = SqlAlchemyLineageStore(session)
            try:
                record = await store.get(key)
            except LineageError as exc:
                if "missing" in str(exc).lower():
                    return None
                raise StrategySignalApiError(
                    status=503,
                    code="ARTIFACT_INTEGRITY_FAILURE",
                    title="Strategy artifact could not be verified",
                    detail="The exact artifact or its provenance failed verification.",
                ) from exc
            if _reference_content_sha256(record) != content_sha256:
                return None
            occurred_at = _occurred_at(record)
            if occurred_at is None:
                raise StrategySignalApiError(
                    status=503,
                    code="ARTIFACT_TIME_UNAVAILABLE",
                    title="Strategy artifact could not be projected",
                    detail="The exact artifact has no valid occurrence timestamp.",
                )
            return await _artifact_view(store, key, record, occurred_at)

    @classmethod
    def _supported_schemas(cls, contract_id: str | None) -> frozenset[str]:
        if contract_id is not None:
            return cls._SCHEMAS[contract_id]
        return frozenset().union(*cls._SCHEMAS.values())

    async def evaluate(
        self,
        request: StrategyEvaluationRequest,
        *,
        correlation_id: str,
    ) -> StrategyEvaluationResponse:
        request_document = json.dumps(
            request.model_dump(mode="json"), sort_keys=True, separators=(",", ":")
        )
        request_digest = evaluation_request_digest(request)
        async with self._session_factory() as session:
            from trading_platform_api.lineage.codec import LineageError, LineageKey
            from trading_platform_api.lineage.store import (
                SqlAlchemyLineageStore,
                _reference_content_sha256,
            )

            store = SqlAlchemyLineageStore(session)
            response: StrategyEvaluationResponse | None = None
            async with session.begin():
                await store.lock_evaluate_binding(
                    profile=PROFILE, request_digest=request_digest
                )
                strategy_key = LineageKey(
                    request.strategy_version.contract_id,
                    str(request.strategy_version.artifact_id),
                    request.strategy_version.schema_version,
                )
                context_key = LineageKey(
                    request.market_context.contract_id,
                    str(request.market_context.artifact_id),
                    request.market_context.schema_version,
                )
                try:
                    resolved = await store.resolve((strategy_key, context_key))
                except LineageError as exc:
                    raise StrategySignalApiError(
                        status=422,
                        code="EXACT_EVALUATION_INPUT_INVALID",
                        title="Strategy evaluation inputs could not be verified",
                        detail=(
                            "Both exact immutable references and their full provenance "
                            "must resolve before evaluation."
                        ),
                    ) from exc
                for reference, key in (
                    (request.strategy_version, strategy_key),
                    (request.market_context, context_key),
                ):
                    if (
                        key not in resolved
                        or _reference_content_sha256(resolved[key])
                        != reference.content_sha256
                    ):
                        raise StrategySignalApiError(
                            status=422,
                            code="EXACT_EVALUATION_INPUT_INVALID",
                            title="Strategy evaluation inputs could not be verified",
                            detail=(
                                "The supplied digest does not match the exact immutable "
                                "strategy or Spot context."
                            ),
                        )
                saved = await store.get_evaluate_binding(
                    profile=PROFILE,
                    request_digest=request_digest,
                    request_document=request_document,
                )
                if saved is not None:
                    response = StrategyEvaluationResponse.model_validate_json(saved)
                    if response.request_digest != request_digest:
                        raise StrategySignalApiError(
                            status=503,
                            code="EVALUATION_BINDING_INTEGRITY_FAILURE",
                            title="Stored evaluation could not be verified",
                            detail="The stored evaluation does not match its exact request.",
                        )
                    return response
                context = resolved[context_key]
                try:
                    handoff = await store.get_spot_agent_handoff(context_key)
                    if handoff is None:
                        raise StrategySignalApiError(
                            status=503,
                            code="SPOT_AGENT_HANDOFF_UNAVAILABLE",
                            title="Validated Spot agent handoff unavailable",
                            detail=(
                                "The exact producer-owned C-062/C-066/C-067 handoff "
                                "for this C-006 context has not been persisted."
                            ),
                        )
                    result, evaluation, handoff_correlation, handoff_trace = handoff
                    inputs = await _compose_persisted_spot_debate(
                        session=session,
                        store=store,
                        context_key=context_key,
                        context=context,
                        result=result,
                        evaluation=evaluation,
                        correlation_id=handoff_correlation,
                        trace_id=handoff_trace,
                        now=datetime.now(UTC),
                    )
                except StrategySignalApiError:
                    raise
                except (LineageError, TypeError, ValueError) as exc:
                    raise StrategySignalApiError(
                        status=503,
                        code="SPOT_AGENT_HANDOFF_INTEGRITY_FAILURE",
                        title="Validated Spot agent handoff could not be verified",
                        detail=(
                            "The exact persisted handoff, fan-out, or Spot debate "
                            "failed deterministic provenance validation."
                        ),
                    ) from exc
                try:
                    artifacts = await _evaluate_persisted_spot_inputs(
                        session=session,
                        store=store,
                        request=request,
                        inputs=inputs,
                        environment=self._environment,
                        mode=self._mode,
                        now=datetime.now(UTC),
                    )
                except (LineageError, TypeError, ValueError) as exc:
                    raise StrategySignalApiError(
                        status=503,
                        code="STRATEGY_EVALUATION_INTEGRITY_FAILURE",
                        title="Strategy evaluation could not be verified",
                        detail=(
                            "The deterministic strategy chain failed exact provenance "
                            "or durable artifact validation."
                        ),
                    ) from exc
                response = StrategyEvaluationResponse(
                    request_digest=request_digest,
                    projection_state="NO_TRADE",
                    artifacts=tuple(artifacts),
                )
                outcome_document = response.model_dump_json()
                saved_outcome = await store.append_evaluate_binding(
                    profile=PROFILE,
                    request_digest=request_digest,
                    request_document=request_document,
                    outcome_document=outcome_document,
                    created_at=datetime.now(UTC),
                )
                try:
                    response = StrategyEvaluationResponse.model_validate_json(
                        saved_outcome
                    )
                except ValueError as exc:
                    raise StrategySignalApiError(
                        status=503,
                        code="EVALUATION_BINDING_INTEGRITY_FAILURE",
                        title="Stored evaluation could not be verified",
                        detail="The stored evaluation response is invalid.",
                    ) from exc
                if response.request_digest != request_digest:
                    raise StrategySignalApiError(
                        status=503,
                        code="EVALUATION_BINDING_INTEGRITY_FAILURE",
                        title="Stored evaluation could not be verified",
                        detail="The stored evaluation does not match its exact request.",
                    )
            verified_outcome = await store.get_evaluate_binding(
                profile=PROFILE,
                request_digest=request_digest,
                request_document=request_document,
            )
            if (
                response is None
                or verified_outcome is None
                or verified_outcome != saved_outcome
            ):
                raise StrategySignalApiError(
                    status=503,
                    code="EVALUATION_BINDING_INTEGRITY_FAILURE",
                    title="Stored evaluation could not be verified",
                    detail="The committed evaluation binding failed exact read-back.",
                )
            return response


async def _artifact_view(
    store: object, key: object, record: object, occurred_at: datetime
) -> StrategyArtifactView:
    from trading_platform_api.lineage.codec import LineageKey
    from trading_platform_api.lineage.store import (
        SqlAlchemyLineageStore,
        _reference_content_sha256,
        references,
    )

    if (
        type(store) is not SqlAlchemyLineageStore
        or type(key) is not LineageKey
        or occurred_at.tzinfo is None
    ):
        raise StrategySignalApiError(
            status=503,
            code="ARTIFACT_INTEGRITY_FAILURE",
            title="Strategy artifact could not be projected",
            detail="The exact artifact identity or occurrence time is invalid.",
        )
    reference = ApiVersionReference(
        contract_id=key.contract_id,
        artifact_id=UUID(key.record_id),
        schema_version=key.version,
        content_sha256=_reference_content_sha256(record),
    )
    state = None
    reason_values: tuple[str, ...] = ()
    for name in ("lifecycle", "status", "state", "outcome"):
        value = getattr(record, name, None)
        if value is not None:
            state = getattr(value, "value", value)
            if isinstance(state, str):
                break
            state = None
    raw_reasons = getattr(record, "reason_codes", None)
    if raw_reasons is None:
        raw_reasons = getattr(record, "reasons", ())
    if isinstance(raw_reasons, (tuple, list)):
        reason_values = tuple(
            str(getattr(reason, "value", reason))
            for reason in raw_reasons[:32]
            if isinstance(getattr(reason, "value", reason), str)
        )
    lineage: list[ApiVersionReference] = []
    for item in references(record):
        target = item.key
        try:
            target_id = UUID(target.record_id)
        except (ValueError, AttributeError) as exc:
            raise StrategySignalApiError(
                status=503,
                code="ARTIFACT_LINEAGE_IDENTITY_UNSUPPORTED",
                title="Strategy artifact lineage could not be projected",
                detail="A referenced artifact has an unsupported API identity.",
            ) from exc
        try:
            target_record = await store.get(target)
            digest = _reference_content_sha256(target_record)
        except (ValueError, TypeError):
            raise StrategySignalApiError(
                status=503,
                code="ARTIFACT_LINEAGE_UNAVAILABLE",
                title="Strategy artifact lineage could not be verified",
                detail="A referenced immutable artifact failed exact resolution.",
            )
        lineage.append(
            ApiVersionReference(
                contract_id=target.contract_id,
                artifact_id=target_id,
                schema_version=target.version,
                content_sha256=digest,
            )
        )
    subject = _lifecycle_subject(key, record)
    history = (
        await SqlAlchemySignalLifecycleStore(store._session).history(subject)
        if subject is not None
        else ()
    )
    lifecycle_events = tuple(
        LifecycleEventView(
            event_id=event.event_id,
            prior_state=event.prior_state.value if event.prior_state else None,
            resulting_state=event.resulting_state.value,
            event_type=event.event_type.value,
            cause=event.cause.value,
            event_time=event.event_time,
            recorded_at=event.recorded_at,
            correlation_id=event.correlation_id,
            source_references=tuple(
                _api_reference(reference) for reference in event.source_references
            ),
        )
        for event in history
    )
    if history:
        state = history[-1].resulting_state.value
    elif subject is not None:
        state = None
    if len(lineage) > 64:
        raise StrategySignalApiError(
            status=503,
            code="ARTIFACT_LINEAGE_TOO_LARGE",
            title="Strategy artifact lineage could not be projected",
            detail="The exact artifact lineage exceeds the bounded API response size.",
        )
    if len(lifecycle_events) > 64:
        raise StrategySignalApiError(
            status=503,
            code="ARTIFACT_LIFECYCLE_TOO_LARGE",
            title="Strategy artifact lifecycle could not be projected",
            detail="The immutable lifecycle history exceeds the bounded API response size.",
        )
    as_of = getattr(record, "as_of", None)
    valid_until = getattr(record, "valid_until", None)
    if not isinstance(valid_until, datetime):
        valid_until = getattr(record, "expires_at", None)
    return StrategyArtifactView(
        reference=reference,
        occurred_at=occurred_at,
        as_of=as_of if isinstance(as_of, datetime) else None,
        valid_until=valid_until if isinstance(valid_until, datetime) else None,
        projection_state=state,
        reasons=reason_values,
        lineage=tuple(lineage),
        lifecycle_events=lifecycle_events,
    )


async def _compose_persisted_spot_debate(
    *,
    session: AsyncSession,
    store: object,
    context_key: object,
    context: object,
    result: object,
    evaluation: object,
    correlation_id: UUID,
    trace_id: UUID,
    now: datetime,
) -> PersistedSpotDebateInputs:
    """Rebuild the orchestration-only debate from exact persisted inputs."""
    from trading_platform_api.agents.contracts import AgentEvaluation, AgentResult
    from trading_platform_api.agents.registry import PERSONAL_SPOT_RESEARCH_AGENT
    from trading_platform_api.agents.result_validation import AgentResultExpectation
    from trading_platform_api.analysis.contracts import MarketRegime, VersionReference
    from trading_platform_api.analysis.versioned_contracts import EvidenceItemV2
    from trading_platform_api.analysis.versioned_contracts_v4 import (
        AnalysisSnapshotV4,
        resolve_analysis_snapshot_v4,
    )
    from trading_platform_api.analysis.versioned_contracts_v5 import MarketContextV5
    from trading_platform_api.lineage.codec import LineageError, LineageKey
    from trading_platform_api.lineage.store import SqlAlchemyLineageStore
    from trading_platform_api.market_data.contracts import (
        DataQualityReportV2,
        DataSourceRecord,
        MarketData,
        MarketSnapshot,
    )
    from trading_platform_api.orchestration.spot_analysis_fanout import (
        SpotAnalysisFanoutResult,
    )
    from trading_platform_api.orchestration.spot_debate import compose_spot_debate
    from trading_platform_api.spot_research_store import (
        SqlAlchemySpotResearchStore,
        spot_research_analysis,
    )

    if (
        type(store) is not SqlAlchemyLineageStore
        or type(context_key) is not LineageKey
        or type(context) is not MarketContextV5
        or type(result) is not AgentResult
        or type(evaluation) is not AgentEvaluation
    ):
        raise LineageError("Exact typed Spot handoff inputs are required.")
    resolved = await store.resolve((context_key,), maximum_records=2_000)
    manifest_key = LineageKey(
        "C-007",
        str(context.analysis_snapshot.snapshot_id),
        context.analysis_snapshot.schema_version,
    )
    manifest = resolved.get(manifest_key)
    if type(manifest) is not AnalysisSnapshotV4:
        raise LineageError("Exact C-007 manifest is unavailable.")
    if len(manifest.bindings) != 1:
        raise LineageError("Spot analysis requires one exact OHLCV binding.")
    snapshot_id = manifest.bindings[0].market_snapshot.record_id
    row = (
        (
            await session.execute(
                select(spot_research_analysis).where(
                    spot_research_analysis.c.snapshot_id == snapshot_id
                )
            )
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        raise LineageError("Exact persisted Spot fan-out row is missing.")
    stored = await SqlAlchemySpotResearchStore._read_analysis(
        store, row, snapshot_id=snapshot_id
    )
    if (
        stored.fanout is None
        or stored.fanout.correlation_id != correlation_id
        or evaluation.correlation_id != correlation_id
        or evaluation.trace_id != trace_id
        or stored.manifest.snapshot_id != context.analysis_snapshot.snapshot_id
    ):
        raise LineageError("C-066 and stored fan-out do not share exact identity.")

    if manifest != stored.manifest:
        raise LineageError("Exact C-007 manifest differs from stored Spot analysis.")
    values = tuple(resolved.values())
    snapshots = {
        item.snapshot_id: item for item in values if type(item) is MarketSnapshot
    }
    reports = {
        item.report_id: item for item in values if type(item) is DataQualityReportV2
    }
    observations = {
        item.market_data_id: item for item in values if type(item) is MarketData
    }
    sources = {
        item.source_record_id: item for item in values if type(item) is DataSourceRecord
    }
    regimes = {item.regime_id: item for item in values if type(item) is MarketRegime}
    evidence = {
        item.evidence_id: item for item in values if type(item) is EvidenceItemV2
    }
    bindings = resolve_analysis_snapshot_v4(
        manifest,
        now=now,
        snapshots=snapshots,
        reports=reports,
        observations=observations,
        sources=sources,
        regimes=regimes,
        evidence=evidence,
    )
    expectation = AgentResultExpectation(
        task_id=result.task_id,
        context_id=context.context_id,
        agent_id=PERSONAL_SPOT_RESEARCH_AGENT.agent_id,
        agent_version=PERSONAL_SPOT_RESEARCH_AGENT.agent_version,
        routing_decision=result.routing_decision,
        allowed_tool_access_ids=(),
        allowed_evidence_ids=context.evidence_ids,
        allowed_output_schemas={"C-006": ("5", MarketContextV5)},
    )
    adversarial = context.adversarial
    supported_versions = [
        adversarial.method,
        adversarial.model,
        adversarial.prompt,
    ]
    if adversarial.analytical_confidence.method is not None:
        supported_versions.append(adversarial.analytical_confidence.method)
    if any(type(item) is not VersionReference for item in supported_versions):
        raise LineageError("C-019 version provenance is not exact.")
    debate = compose_spot_debate(
        agent_result=result,
        agent_evaluation=evaluation,
        expectation=expectation,
        correlation_id=correlation_id,
        trace_id=trace_id,
        market_context=context,
        manifest=manifest,
        resolved_bindings=bindings,
        evidence={item.evidence_id: item for item in stored.evidence},
        independence_reports={
            stored.independence_report.report_id: stored.independence_report
        },
        supported_adversarial_versions=tuple(supported_versions),
        now=now,
    )
    if type(stored.fanout) is not SpotAnalysisFanoutResult:
        raise LineageError("Stored Spot fan-out did not decode to its closed type.")
    return PersistedSpotDebateInputs(
        debate=debate,
        fanout=stored.fanout,
        manifest=manifest,
        resolved_bindings=bindings,
        evidence={item.evidence_id: item for item in stored.evidence},
        independence_report=stored.independence_report,
        supported_independence_reports=tuple(
            item for item in manifest.analysis_outputs if item.contract_id == "C-093"
        ),
        supported_adversarial_versions=tuple(supported_versions),
    )


@dataclass(frozen=True, slots=True)
class PersistedSpotDebateInputs:
    debate: Any
    fanout: Any
    manifest: Any
    resolved_bindings: tuple[Any, ...]
    evidence: dict[UUID, Any]
    independence_report: Any
    supported_independence_reports: tuple[Any, ...]
    supported_adversarial_versions: tuple[Any, ...]


async def _evaluate_persisted_spot_inputs(
    *,
    session: AsyncSession,
    store: object,
    request: StrategyEvaluationRequest,
    inputs: PersistedSpotDebateInputs,
    environment: DeploymentEnvironment,
    mode: OperatingMode,
    now: datetime,
) -> list[StrategyArtifactView]:
    """Run the existing deterministic Spot chain and persist its fail-closed result."""
    from trading_platform_api.analysis.spot_meta_analysis import AgentIndependenceReport
    from trading_platform_api.analysis.versioned_contracts_v4 import (
        AnalysisOutputReferenceV4,
        AnalysisSnapshotV4,
        ResolvedSpotOHLCVBindingV4,
    )
    from trading_platform_api.analysis.versioned_contracts_v5 import MarketContextV5
    from trading_platform_api.lineage.codec import LineageKey
    from trading_platform_api.lineage.store import SqlAlchemyLineageStore
    from trading_platform_api.strategy.condition_evaluator import (
        build_spot_condition_context,
        evaluate_strategy_conditions,
    )
    from trading_platform_api.strategy.contracts_v2 import StrategyVersionV2
    from trading_platform_api.strategy.eligibility import evaluate_strategy_eligibility
    from trading_platform_api.strategy.evidence_package import (
        build_signal_evidence_package_v2,
    )
    from trading_platform_api.strategy.lifecycle import (
        SignalLifecycleCause,
        SignalLifecycleEvent,
        SignalLifecycleEventType,
        SignalLifecycleProjection,
        SignalLifecycleRuntime,
        SqlAlchemySignalLifecycleStore,
    )
    from trading_platform_api.strategy.no_trade import evaluate_no_trade_v2
    from trading_platform_api.strategy.qualification import (
        evaluate_signal_qualification_v2,
    )
    from trading_platform_api.strategy.registry import StrategyRegistry
    from trading_platform_api.strategy.registry_store import (
        SqlAlchemyStrategyRegistryStore,
    )
    from trading_platform_api.strategy.setup_detection import evaluate_strategy_setup

    if type(store) is not SqlAlchemyLineageStore:
        raise ValueError("Exact lineage store is required.")
    context_key = LineageKey(
        request.market_context.contract_id,
        str(request.market_context.artifact_id),
        request.market_context.schema_version,
    )
    context = await store.get(context_key)
    version = await store.get(
        LineageKey(
            request.strategy_version.contract_id,
            str(request.strategy_version.artifact_id),
            request.strategy_version.schema_version,
        )
    )
    if (
        type(context) is not MarketContextV5
        or type(version) is not StrategyVersionV2
        or type(inputs.manifest) is not AnalysisSnapshotV4
        or type(inputs.independence_report) is not AgentIndependenceReport
        or any(
            type(item) is not ResolvedSpotOHLCVBindingV4
            for item in inputs.resolved_bindings
        )
        or any(
            type(item) is not AnalysisOutputReferenceV4
            for item in inputs.supported_independence_reports
        )
    ):
        raise ValueError("Exact typed Spot evaluation inputs are required.")
    registry = StrategyRegistry(
        SqlAlchemyStrategyRegistryStore(session),
        reference_resolver=None,
        clock=lambda: now,
    )
    strategy = await registry.resolve_version(
        strategy_id=version.strategy_id,
        strategy_version_id=version.strategy_version_id,
        as_of=now,
    )
    debate = inputs.debate
    fanout = inputs.fanout
    condition_context = build_spot_condition_context(
        strategy=strategy, debate=debate, fanout=fanout, now=now
    )
    condition = evaluate_strategy_conditions(strategy, condition_context)
    eligibility = evaluate_strategy_eligibility(
        requested_strategy_version_id=version.strategy_version_id,
        strategy=strategy,
        condition_context=condition_context,
        condition_evaluation=condition,
        market_context=context,
        manifest=inputs.manifest,
        resolved_bindings=inputs.resolved_bindings,
        environment=environment,
        mode=mode,
        now=now,
    )
    setup = evaluate_strategy_setup(
        requested_strategy_version_id=version.strategy_version_id,
        strategy=strategy,
        condition_context=condition_context,
        condition_evaluation=condition,
        eligibility_evaluation=eligibility,
        market_context=context,
        manifest=inputs.manifest,
        resolved_bindings=inputs.resolved_bindings,
        now=now,
    )
    candidate = setup.candidate
    package = build_signal_evidence_package_v2(
        candidate=candidate,
        strategy=strategy,
        condition_context=condition_context,
        condition_evaluation=condition,
        eligibility_evaluation=eligibility,
        market_context=context,
        manifest=inputs.manifest,
        resolved_bindings=inputs.resolved_bindings,
        evidence=inputs.evidence,
        independence_report=inputs.independence_report,
        supported_independence_reports=inputs.supported_independence_reports,
        supported_adversarial_versions=inputs.supported_adversarial_versions,
        now=now,
    )
    # Chat 7 validation configuration and authoritative historical measurements
    # are not persisted in this profile. Missing validation stays explicit.
    qualification = evaluate_signal_qualification_v2(
        candidate=candidate,
        evidence_package=package.package,
        validation=None,
        evaluated_at=now,
    )
    no_trade = evaluate_no_trade_v2(
        market_context=context,
        setup=setup,
        eligibility=eligibility,
        evidence_package=package,
        validation=None,
        qualification=qualification,
        evaluated_at=now,
        correlation_id=str(debate.correlation_id),
    )
    if no_trade.decision is None:
        raise ValueError("The exact Spot chain did not produce a fail-closed decision.")

    records: list[object] = []
    if eligibility.eligibility is not None:
        records.append(eligibility.eligibility)
    if candidate is not None:
        records.append(candidate)
    if package.package is not None:
        records.append(package.package)
    records.append(no_trade.decision)
    artifact_views: list[StrategyArtifactView] = []
    for record in records:
        key = await store.append(record)
        persisted = await store.get(key)
        occurred_at = getattr(
            record,
            "created_at",
            getattr(record, "decided_at", getattr(record, "evaluated_at", None)),
        )
        if not isinstance(occurred_at, datetime):
            raise ValueError("Strategy artifact occurrence time is unavailable.")
        artifact_views.append(await _artifact_view(store, key, persisted, occurred_at))
    if candidate is not None:
        from trading_platform_api.contracts.serialization import canonical_sha256
        from trading_platform_api.strategy.contracts import VersionReference

        candidate_ref = VersionReference(
            "C-023", candidate.candidate_id, "1", canonical_sha256(candidate)
        )
        candidate_sources = [candidate_ref]
        if eligibility.eligibility is not None:
            candidate_sources.append(
                VersionReference(
                    "C-022",
                    eligibility.eligibility.eligibility_id,
                    "1",
                    canonical_sha256(eligibility.eligibility),
                )
            )
        lifecycle = SignalLifecycleRuntime(SqlAlchemySignalLifecycleStore(session))
        created = SignalLifecycleEvent(
            subject=candidate_ref,
            prior_state=None,
            resulting_state=SignalLifecycleProjection.CANDIDATE,
            event_type=SignalLifecycleEventType.CREATED,
            cause=SignalLifecycleCause.SOURCE_DECISION,
            source_references=tuple(candidate_sources),
            event_time=candidate.created_at,
            recorded_at=now,
            correlation_id=str(debate.correlation_id),
        )
        created_result = await lifecycle.record(created, actor="strategy-signal-api")
        if not created_result.accepted:
            raise ValueError("Candidate lifecycle creation was rejected.")
        decision_ref = VersionReference(
            "C-026",
            no_trade.decision.decision_id,
            "2",
            canonical_sha256(no_trade.decision),
        )
        no_trade_event = SignalLifecycleEvent(
            subject=candidate_ref,
            prior_state=SignalLifecycleProjection.CANDIDATE,
            resulting_state=SignalLifecycleProjection.NO_TRADE,
            event_type=SignalLifecycleEventType.NO_TRADE,
            cause=SignalLifecycleCause.SOURCE_DECISION,
            source_references=(decision_ref,),
            event_time=no_trade.decision.decided_at,
            recorded_at=now,
            correlation_id=str(debate.correlation_id),
        )
        no_trade_result = await lifecycle.record(
            no_trade_event, actor="strategy-signal-api"
        )
        if not no_trade_result.accepted:
            raise ValueError("NO_TRADE lifecycle transition was rejected.")
        candidate_view_index = next(
            (
                index
                for index, view in enumerate(artifact_views)
                if view.reference.contract_id == "C-023"
            ),
            None,
        )
        if candidate_view_index is not None:
            candidate_view = artifact_views[candidate_view_index]
            artifact_views[candidate_view_index] = candidate_view.model_copy(
                update={
                    "projection_state": SignalLifecycleProjection.NO_TRADE.value,
                    "lifecycle_events": tuple(
                        LifecycleEventView(
                            event_id=event.event_id,
                            prior_state=(
                                event.prior_state.value if event.prior_state else None
                            ),
                            resulting_state=event.resulting_state.value,
                            event_type=event.event_type.value,
                            cause=event.cause.value,
                            event_time=event.event_time,
                            recorded_at=event.recorded_at,
                            correlation_id=event.correlation_id,
                            source_references=tuple(
                                _api_reference(reference)
                                for reference in event.source_references
                            ),
                        )
                        for event in await SqlAlchemySignalLifecycleStore(
                            session
                        ).history(candidate_ref)
                    ),
                }
            )
    return artifact_views


def _api_reference(reference: VersionReference) -> ApiVersionReference:
    schema_version = "2" if reference.artifact_type == "C-021" else reference.version
    return ApiVersionReference(
        contract_id=reference.artifact_type,
        artifact_id=reference.artifact_id,
        schema_version=schema_version,
        content_sha256=reference.content_sha256,
    )


def _lifecycle_subject(key: object, record: object) -> VersionReference | None:
    from trading_platform_api.lineage.codec import LineageKey

    if type(key) is not LineageKey:
        return None
    if key.contract_id == "C-023":
        return VersionReference(
            "C-023", UUID(key.record_id), "1", canonical_sha256(record)
        )
    lineage = getattr(record, "lineage", None)
    candidate = getattr(lineage, "candidate", None)
    if type(candidate) is VersionReference:
        return candidate
    candidate = getattr(record, "candidate", None)
    if type(candidate) is VersionReference:
        return candidate
    provenance = getattr(record, "provenance", ())
    if isinstance(provenance, tuple):
        candidate = next(
            (
                item
                for item in provenance
                if type(item) is VersionReference and item.artifact_type == "C-023"
            ),
            None,
        )
        if candidate is not None:
            return candidate
    candidate_id = getattr(record, "candidate_id", None)
    candidate_digest = getattr(record, "candidate_sha256", None)
    if isinstance(candidate_id, UUID) and isinstance(candidate_digest, str):
        return VersionReference("C-023", candidate_id, "1", candidate_digest)
    return None


def evaluation_request_digest(request: StrategyEvaluationRequest) -> str:
    return canonical_sha256(
        {
            "profile": request.profile,
            "strategy_version": request.strategy_version.model_dump(mode="json"),
            "market_context": request.market_context.model_dump(mode="json"),
        }
    )


def encode_cursor(
    *,
    occurred_at: datetime,
    event_id: UUID,
    event_contract_id: str,
    event_schema_version: str,
    contract_id: str | None,
    schema_version: str | None,
    projection_state: str | None,
) -> str:
    if occurred_at.tzinfo is None or occurred_at.utcoffset() is None:
        raise ValueError("occurred_at must be timezone-aware")
    payload = {
        "occurred_at": occurred_at.astimezone(UTC).isoformat(),
        "event_id": str(event_id),
        "event_contract_id": event_contract_id,
        "event_schema_version": event_schema_version,
        "contract_id": contract_id,
        "schema_version": schema_version,
        "projection_state": projection_state,
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    envelope = {
        "payload": payload,
        "checksum": sha256(canonical.encode("utf-8")).hexdigest(),
    }
    encoded = json.dumps(envelope, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )
    return base64.urlsafe_b64encode(encoded).decode("ascii").rstrip("=")


def decode_cursor(
    cursor: str,
    *,
    contract_id: str | None,
    schema_version: str | None,
    projection_state: str | None,
) -> tuple[datetime, str, str, UUID]:
    try:
        padding = "=" * (-len(cursor) % 4)
        document = json.loads(
            base64.urlsafe_b64decode((cursor + padding).encode("ascii")).decode("utf-8")
        )
        if type(document) is not dict or set(document) != {"payload", "checksum"}:
            raise ValueError
        payload = document["payload"]
        if type(payload) is not dict or set(payload) != {
            "occurred_at",
            "event_id",
            "event_contract_id",
            "event_schema_version",
            "contract_id",
            "schema_version",
            "projection_state",
        }:
            raise ValueError
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        if sha256(canonical.encode("utf-8")).hexdigest() != document["checksum"]:
            raise ValueError
        if (
            payload["contract_id"] != contract_id
            or payload["schema_version"] != schema_version
            or payload["projection_state"] != projection_state
        ):
            raise ValueError
        occurred_at = datetime.fromisoformat(payload["occurred_at"])
        if occurred_at.tzinfo is None or occurred_at.utcoffset() is None:
            raise ValueError
        event_id = UUID(payload["event_id"])
        event_contract_id = payload["event_contract_id"]
        event_schema_version = payload["event_schema_version"]
        from trading_platform_api.lineage.codec import LineageKey

        key = LineageKey(event_contract_id, str(event_id), event_schema_version)
        return (
            occurred_at.astimezone(UTC),
            key.contract_id,
            key.version,
            event_id,
        )
    except (ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
        raise StrategySignalApiError(
            status=400,
            code="INVALID_CURSOR",
            title="Invalid pagination cursor",
            detail="The pagination cursor is invalid for the requested filters.",
        ) from exc


def _success(content: BaseModel, *, correlation_id: str) -> JSONResponse:
    return JSONResponse(
        content=content.model_dump(mode="json"),
        headers={
            "Cache-Control": "no-store",
            "X-Correlation-ID": correlation_id,
        },
    )


def create_strategy_signal_router() -> APIRouter:
    router = APIRouter(
        prefix="/api/research/strategy-signals",
        tags=["strategy-signal-research"],
    )

    @router.get("")
    async def list_artifacts(
        request: Request,
        contract_id: str | None = Query(default=None, max_length=32),
        schema_version: str | None = Query(default=None, max_length=128),
        projection_state: str | None = Query(default=None, max_length=32),
        limit: int = Query(default=50, ge=1, le=MAX_PAGE_SIZE),
        cursor: str | None = Query(default=None, max_length=4096),
    ) -> JSONResponse:
        if cursor is not None:
            decode_cursor(
                cursor,
                contract_id=contract_id,
                schema_version=schema_version,
                projection_state=projection_state,
            )
        service: StrategySignalApiService = request.app.state.strategy_signal_service
        page = await service.list_artifacts(
            ArtifactListQuery(
                contract_id=contract_id,
                schema_version=schema_version,
                projection_state=projection_state,
                limit=limit,
                cursor=cursor,
            )
        )
        return _success(page, correlation_id=request.state.correlation_id)

    @router.get("/{contract_id}/{artifact_id}")
    async def get_artifact(
        contract_id: str,
        artifact_id: UUID,
        request: Request,
        schema_version: str = Query(min_length=1, max_length=128),
        content_sha256: str = Query(min_length=64, max_length=64),
    ) -> JSONResponse:
        if len(content_sha256) != 64 or any(
            ch not in "0123456789abcdef" for ch in content_sha256
        ):
            raise StrategySignalApiError(
                status=422,
                code="INVALID_ARTIFACT_DIGEST",
                title="Invalid artifact digest",
                detail="The artifact digest must be a lowercase SHA-256 value.",
            )
        service: StrategySignalApiService = request.app.state.strategy_signal_service
        artifact = await service.get_artifact(
            contract_id=contract_id,
            artifact_id=artifact_id,
            schema_version=schema_version,
            content_sha256=content_sha256,
        )
        if artifact is None:
            raise StrategySignalApiError(
                status=404,
                code="STRATEGY_ARTIFACT_NOT_FOUND",
                title="Strategy artifact not found",
                detail="No exact artifact matches the requested reference.",
            )
        return _success(artifact, correlation_id=request.state.correlation_id)

    @router.post("/evaluate")
    async def evaluate(
        body: StrategyEvaluationRequest,
        request: Request,
    ) -> JSONResponse:
        service: StrategySignalApiService = request.app.state.strategy_signal_service
        result = await service.evaluate(
            body,
            correlation_id=request.state.correlation_id,
        )
        if result.request_digest != evaluation_request_digest(body):
            raise StrategySignalApiError(
                status=500,
                code="EVALUATION_IDEMPOTENCY_MISMATCH",
                title="Evaluation result could not be verified",
                detail="The evaluation result does not match the exact request references.",
            )
        return _success(result, correlation_id=request.state.correlation_id)

    return router


__all__ = [
    "ApiVersionReference",
    "ArtifactListQuery",
    "LifecycleEventView",
    "MAX_PAGE_SIZE",
    "PROFILE",
    "StrategyArtifactPage",
    "StrategyArtifactView",
    "StrategyEvaluationRequest",
    "StrategyEvaluationResponse",
    "SqlAlchemyStrategySignalApiService",
    "StrategySignalApiError",
    "StrategySignalApiService",
    "UnavailableStrategySignalApiService",
    "create_strategy_signal_router",
    "decode_cursor",
    "encode_cursor",
    "evaluation_request_digest",
]
