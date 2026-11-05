"""Bounded PERSONAL_SPOT_RESEARCH strategy/signal API foundation."""

from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from typing import Protocol
from uuid import UUID

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator

from trading_platform_api.contracts.serialization import canonical_sha256

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


class StrategyArtifactView(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    reference: ApiVersionReference
    occurred_at: datetime
    valid_until: datetime | None = None
    projection_state: str | None = Field(default=None, max_length=32)
    reasons: tuple[str, ...] = Field(default=(), max_length=32)
    lineage: tuple[ApiVersionReference, ...] = Field(default=(), max_length=64)

    @field_validator("occurred_at", "valid_until")
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
        if value.contract_id != "C-021":
            raise ValueError("strategy_version must reference C-021")
        return value

    @field_validator("market_context")
    @classmethod
    def validate_context(cls, value: ApiVersionReference) -> ApiVersionReference:
        if value.contract_id != "C-006":
            raise ValueError("market_context must reference C-006")
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
    contract_id: str | None,
    schema_version: str | None,
    projection_state: str | None,
) -> str:
    if occurred_at.tzinfo is None or occurred_at.utcoffset() is None:
        raise ValueError("occurred_at must be timezone-aware")
    payload = {
        "occurred_at": occurred_at.astimezone(UTC).isoformat(),
        "event_id": str(event_id),
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
) -> tuple[datetime, UUID]:
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
        return occurred_at.astimezone(UTC), UUID(payload["event_id"])
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
    "MAX_PAGE_SIZE",
    "PROFILE",
    "StrategyArtifactPage",
    "StrategyArtifactView",
    "StrategyEvaluationRequest",
    "StrategyEvaluationResponse",
    "StrategySignalApiError",
    "StrategySignalApiService",
    "UnavailableStrategySignalApiService",
    "create_strategy_signal_router",
    "decode_cursor",
    "encode_cursor",
    "evaluation_request_digest",
]
