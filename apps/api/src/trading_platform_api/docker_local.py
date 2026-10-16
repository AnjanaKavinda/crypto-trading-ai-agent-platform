"""ADR-0009's container-only launcher; the native launcher is unchanged."""

from __future__ import annotations

import hmac
import ipaddress
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

from sqlalchemy.engine import URL
from starlette.requests import Request

from trading_platform_api.config import AppSettings, load_app_settings

PROXY_HEADER = "x-local-proxy-secret"
IMAGE_MARKER = Path("/usr/local/share/trading-platform/docker-local")


@dataclass(frozen=True)
class DockerLocalSettings:
    origin: str
    authority: str
    secret: str = field(repr=False)

    def accepts(self, request: Request) -> bool:
        for header in ("host", "origin", PROXY_HEADER):
            values = request.headers.getlist(header)
            if len(values) > 1:
                return False
        supplied = request.headers.get(PROXY_HEADER, "")
        if not re.fullmatch(r"[0-9a-f]{64}", supplied):
            return False
        if not hmac.compare_digest(supplied, self.secret):
            return False
        if request.headers.get("host") != self.authority:
            return False
        origin = request.headers.get("origin")
        if origin is not None:
            return origin == self.origin
        # Same-origin browser GETs often omit Origin. No other methods or
        # endpoints may use that exception.
        path = request.url.path
        return request.method == "GET" and (
            path in {"/health", "/health/live", "/api/research/spot/symbols"}
            or re.fullmatch(r"/api/research/spot/[A-Za-z0-9._:-]+/candles", path)
            is not None
        )


def validate_docker_research(settings: AppSettings) -> None:
    if (
        not IMAGE_MARKER.is_file()
        or not Path("/.dockerenv").is_file()
        or os.environ.get("TRADING_PLATFORM_DOCKER_LOCAL") != "true"
    ):
        raise ValueError("Docker-local startup requires the dedicated Compose image.")
    if (
        os.environ.get("TRADING_PLATFORM_MODE") != "research"
        or settings.mode.value != "research"
        or os.environ.get("ENABLE_LIVE_TRADING") != "false"
        or os.environ.get("ENABLE_AUTO_EXECUTION") != "false"
        or settings.feature_flags.enable_live_trading
        or settings.feature_flags.enable_auto_execution
        or settings.environment.value not in {"dev", "test"}
    ):
        raise ValueError(
            "Docker-local startup requires explicit safe research settings."
        )


def load_docker_local_settings(settings: AppSettings) -> DockerLocalSettings:
    validate_docker_research(settings)
    host = os.environ.get("LOCAL_WEB_HOST", "")
    port = os.environ.get("LOCAL_WEB_PORT", "")
    try:
        address = ipaddress.ip_address(host)
        valid_port = port.isascii() and port.isdecimal() and 1 <= int(port) <= 65535
    except ValueError:
        raise ValueError("LOCAL_WEB_HOST must be a loopback IP literal.") from None
    if not address.is_loopback or not valid_port or port != str(int(port)):
        raise ValueError("Local web publication requires a loopback IP and valid port.")
    hostname = f"[{host}]" if address.version == 6 else host
    authority = hostname if port == "80" else f"{hostname}:{port}"
    origin = os.environ.get("TRADING_PLATFORM_FRONTEND_ORIGIN", "")
    if origin != f"http://{authority}" or urlsplit(origin).netloc != authority:
        raise ValueError("Frontend origin must exactly match the loopback web binding.")
    secret = os.environ.get("LOCAL_PROXY_SECRET", "")
    if not re.fullmatch(r"[0-9a-f]{64}", secret) or len(set(secret)) < 8:
        raise ValueError(
            "Generate LOCAL_PROXY_SECRET as 32 random bytes in lowercase hex."
        )
    return DockerLocalSettings(origin, authority, secret)


def configure_database() -> None:
    credentials = {
        key: os.environ.get(key, "")
        for key in ("POSTGRES_USER", "POSTGRES_PASSWORD", "POSTGRES_DB")
    }
    if not all(credentials.values()):
        raise ValueError("Local PostgreSQL user, password and database are required.")
    local_password = credentials["POSTGRES_PASSWORD"]
    os.environ["DATABASE_URL"] = URL.create(
        "postgresql+asyncpg",
        credentials["POSTGRES_USER"],
        local_password,
        host="postgres",
        port=5432,
        database=credentials["POSTGRES_DB"],
    ).render_as_string(hide_password=False)


def main() -> None:
    import sys

    settings = load_app_settings()
    validate_docker_research(settings)
    configure_database()
    if sys.argv[1:] == ["migrate"]:
        from alembic.config import main as alembic_main

        alembic_main(argv=["-c", "/app/apps/api/alembic.ini", "upgrade", "head"])
    elif not sys.argv[1:]:
        load_docker_local_settings(settings)
        import uvicorn

        from trading_platform_api.main import create_app
        from trading_platform_api.structured_logging import (
            configure_structured_logging,
        )

        configure_structured_logging()
        uvicorn.run(
            create_app(settings, _docker_local=True),
            host="0.0.0.0",
            port=8000,
            proxy_headers=False,
            access_log=False,
        )
    else:
        raise ValueError(
            "Docker-local launcher accepts only the optional migrate command."
        )


if __name__ == "__main__":
    main()
