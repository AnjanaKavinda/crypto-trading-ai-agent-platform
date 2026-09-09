from __future__ import annotations

from enum import Enum
from typing import Literal

from fastapi import APIRouter, Response, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel

SERVICE_NAME = "trading-platform-api"
NO_STORE_CACHE_CONTROL = "no-store"
READINESS_NOT_IMPLEMENTED_REASON = "READINESS_EVALUATOR_NOT_IMPLEMENTED"


class ServiceHealthStatus(str, Enum):
    HEALTHY = "HEALTHY"
    DEGRADED = "DEGRADED"
    UNHEALTHY = "UNHEALTHY"
    UNKNOWN = "UNKNOWN"


class LivenessStatus(str, Enum):
    ALIVE = "ALIVE"


class TradingReadinessStatus(str, Enum):
    READY = "READY"
    DEGRADED = "DEGRADED"
    BLOCKED = "BLOCKED"
    EMERGENCY = "EMERGENCY"
    UNKNOWN = "UNKNOWN"


class ServiceHealthResponse(BaseModel):
    service: Literal[SERVICE_NAME]
    status: ServiceHealthStatus


class LivenessResponse(BaseModel):
    service: Literal[SERVICE_NAME]
    status: LivenessStatus


class TradingReadinessResponse(BaseModel):
    service: Literal[SERVICE_NAME]
    status: TradingReadinessStatus
    ready: bool
    reason_code: Literal[READINESS_NOT_IMPLEMENTED_REASON]


def create_router() -> APIRouter:
    router = APIRouter()

    @router.get("/health", response_model=ServiceHealthResponse)
    def get_health(response: Response) -> ServiceHealthResponse:
        response.headers["Cache-Control"] = NO_STORE_CACHE_CONTROL
        return ServiceHealthResponse(service=SERVICE_NAME, status=ServiceHealthStatus.HEALTHY)

    @router.get("/health/live", response_model=LivenessResponse)
    def get_liveness(response: Response) -> LivenessResponse:
        response.headers["Cache-Control"] = NO_STORE_CACHE_CONTROL
        return LivenessResponse(service=SERVICE_NAME, status=LivenessStatus.ALIVE)

    @router.get(
        "/health/trading-readiness",
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        responses={
            status.HTTP_503_SERVICE_UNAVAILABLE: {
                "model": TradingReadinessResponse,
                "description": "Authoritative trading readiness cannot yet be established.",
            }
        },
    )
    def get_trading_readiness() -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            headers={"Cache-Control": NO_STORE_CACHE_CONTROL},
            content=TradingReadinessResponse(
                service=SERVICE_NAME,
                status=TradingReadinessStatus.UNKNOWN,
                ready=False,
                reason_code=READINESS_NOT_IMPLEMENTED_REASON,
            ).model_dump(mode="json"),
        )

    return router
