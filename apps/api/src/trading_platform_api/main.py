from __future__ import annotations

import ipaddress
import os
import re
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncEngine
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response
from starlette.types import ASGIApp

from trading_platform_api.config import AppSettings, load_app_settings
from trading_platform_api.health import create_router as create_health_router
from trading_platform_api.lineage.archive_storage import LocalFilesystemObjectStore
from trading_platform_api.persistence import (
    create_async_engine_instance,
    create_async_session_factory,
    load_database_settings,
)
from trading_platform_api.problems import (
    ProblemDetail,
    internal_server_problem,
    problem_response,
    request_validation_problem,
)
from trading_platform_api.spot_research import (
    SpotResearchError,
    SpotResearchService,
    approved_quality_policy_template,
    create_research_router,
    load_binance_spot_settings,
    validate_local_origin,
)
from trading_platform_api.spot_research_store import SqlAlchemySpotResearchStore

APP_TITLE = "Trading Platform API"
APP_VERSION = "0.1.0"
_CORRELATION_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}")


def _problem(
    request: Request,
    *,
    status: int,
    code: str,
    title: str,
    detail: str,
) -> JSONResponse:
    correlation_id = getattr(request.state, "correlation_id", str(uuid4()))
    safe_code = re.sub(r"[^A-Z0-9_]", "_", code.upper())[:64]
    problem = ProblemDetail(
        type=f"urn:trading-platform:problem:{safe_code.lower().replace('_', '-')}",
        title=title,
        status=status,
        detail=detail,
        instance=f"urn:trading-platform:problem-instance:{correlation_id}",
        code=safe_code,
        correlation_id=correlation_id,
        timestamp=datetime.now(UTC),
    )
    return problem_response(problem)


class LocalRequestGuard(BaseHTTPMiddleware):
    def __init__(
        self,
        app: ASGIApp,
        *,
        allowed_origin: str | None,
        allow_test_host: bool,
    ) -> None:
        super().__init__(app)
        self.allowed_origin = allowed_origin
        self.allow_test_host = allow_test_host

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        host_header = request.headers.get("host", "")
        hostname = urlsplit(f"//{host_header}").hostname
        peer_host = request.client.host if request.client is not None else None
        loopback_peer = peer_host is not None and (
            _is_loopback_host(peer_host)
            or (self.allow_test_host and peer_host == "testclient")
        )
        if not (
            loopback_peer
            and hostname is not None
            and (
                hostname.lower() == "localhost"
                or _is_loopback_host(hostname)
                or (self.allow_test_host and hostname == "testserver")
            )
        ):
            response: Response = _problem(
                request,
                status=421,
                code="LOCAL_HOST_REQUIRED",
                title="Local access required",
                detail="The research API accepts requests addressed to a loopback host only.",
            )
            response.headers["Cache-Control"] = "no-store"
            return response
        origin = request.headers.get("origin")
        if origin is not None and origin != self.allowed_origin:
            response = _problem(
                request,
                status=403,
                code="ORIGIN_NOT_ALLOWED",
                title="Origin not allowed",
                detail="The request origin does not match the configured local frontend.",
            )
            response.headers["Cache-Control"] = "no-store"
            return response
        supplied = request.headers.get("x-correlation-id", "")
        request.state.correlation_id = (
            supplied if _CORRELATION_ID.fullmatch(supplied) else str(uuid4())
        )
        response = await call_next(request)
        response.headers["X-Correlation-ID"] = request.state.correlation_id
        response.headers["Cache-Control"] = "no-store"
        return response


def _is_loopback_host(hostname: str) -> bool:
    try:
        return ipaddress.ip_address(hostname).is_loopback
    except ValueError:
        return False


def _make_default_research_service(
    *,
    engine_holder: dict[str, AsyncEngine | None],
) -> SpotResearchService:
    provider_settings = load_binance_spot_settings()
    raw_database_url = os.environ.get("DATABASE_URL")
    repository = None
    if raw_database_url is not None:
        database_settings = load_database_settings()
        engine = create_async_engine_instance(database_settings)
        engine_holder["engine"] = engine
        session_factory = create_async_session_factory(engine)
        archive_root = os.environ.get("TRADING_PLATFORM_LOCAL_MARKET_ARCHIVE_ROOT")
        archive_store = (
            LocalFilesystemObjectStore(Path(archive_root)) if archive_root else None
        )
        repository = SqlAlchemySpotResearchStore(
            session_factory, archive_store=archive_store
        )
    return SpotResearchService(
        provider_settings=provider_settings,
        quality_policy=approved_quality_policy_template(),
        repository=repository,
    )


def create_app(
    settings: AppSettings | None = None,
    *,
    research_service: SpotResearchService | None = None,
    allowed_origin: str | None = None,
) -> FastAPI:
    app_settings = settings if settings is not None else load_app_settings()
    engine_holder: dict[str, AsyncEngine | None] = {"engine": None}

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        yield
        engine = engine_holder["engine"]
        if engine is not None:
            await engine.dispose()

    app = FastAPI(
        title=APP_TITLE,
        version=APP_VERSION,
        lifespan=lifespan,
    )
    app.state.settings = app_settings
    app.state.spot_research_service = (
        research_service
        if research_service is not None
        else _make_default_research_service(engine_holder=engine_holder)
    )
    if allowed_origin is None:
        allowed_origin = os.environ.get("TRADING_PLATFORM_FRONTEND_ORIGIN")
    allowed_origin = validate_local_origin(allowed_origin)
    app.state.allowed_origin = allowed_origin
    if allowed_origin is not None:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=[allowed_origin],
            allow_methods=["GET", "POST"],
            allow_headers=["content-type", "x-correlation-id"],
            allow_credentials=False,
            max_age=300,
        )
    app.add_middleware(
        LocalRequestGuard,
        allowed_origin=allowed_origin,
        allow_test_host=app_settings.environment.value == "test",
    )
    app.include_router(create_health_router())
    app.include_router(create_research_router())

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(
        request: Request, exception: RequestValidationError
    ) -> JSONResponse:
        return problem_response(
            request_validation_problem(
                exception.errors(),
                correlation_id=request.state.correlation_id,
                occurred_at=datetime.now(UTC),
            )
        )

    @app.exception_handler(SpotResearchError)
    async def handle_research_error(
        request: Request, exception: SpotResearchError
    ) -> JSONResponse:
        return _problem(
            request,
            status=exception.status,
            code=exception.code,
            title=exception.title,
            detail=exception.detail,
        )

    @app.exception_handler(HTTPException)
    async def handle_http_error(
        request: Request, exception: HTTPException
    ) -> JSONResponse:
        status = exception.status_code
        return _problem(
            request,
            status=status if 400 <= status <= 599 else 500,
            code="HTTP_ERROR",
            title="Request could not be completed",
            detail="The requested resource or operation is unavailable.",
        )

    @app.exception_handler(Exception)
    async def handle_unexpected_error(request: Request, _: Exception) -> JSONResponse:
        return problem_response(
            internal_server_problem(
                correlation_id=request.state.correlation_id,
                occurred_at=datetime.now(UTC),
            )
        )

    return app


app = create_app()
