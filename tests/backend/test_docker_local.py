"""Offline regression coverage for ADR-0009's opt-in container boundary."""

from __future__ import annotations

import secrets
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.engine import make_url
from trading_platform_api.config import load_app_settings
from trading_platform_api.docker_local import (
    IMAGE_MARKER,
    PROXY_HEADER,
    configure_database,
    load_docker_local_settings,
)
from trading_platform_api.main import create_app

ORIGIN = "http://127.0.0.1:5173"
HOST = "127.0.0.1:5173"


@pytest.fixture
def docker_environment(monkeypatch):
    values = {
        "TRADING_PLATFORM_DOCKER_LOCAL": "true",
        "TRADING_PLATFORM_ENVIRONMENT": "test",
        "TRADING_PLATFORM_MODE": "research",
        "ENABLE_LIVE_TRADING": "false",
        "ENABLE_AUTO_EXECUTION": "false",
        "LOCAL_WEB_HOST": "127.0.0.1",
        "LOCAL_WEB_PORT": "5173",
        "TRADING_PLATFORM_FRONTEND_ORIGIN": ORIGIN,
        "LOCAL_PROXY_SECRET": secrets.token_hex(32),
        "TRADING_PLATFORM_BINANCE_SPOT_ENABLED": "false",
    }
    for key, value in values.items():
        monkeypatch.setenv(key, value)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    original = Path.is_file
    monkeypatch.setattr(
        Path,
        "is_file",
        lambda path: (
            True if path in {IMAGE_MARKER, Path("/.dockerenv")} else original(path)
        ),
    )
    return values


def client():
    return TestClient(
        create_app(_docker_local=True),
        base_url=ORIGIN,
        client=("172.20.0.5", 40000),
    )


def test_authenticated_proxy_reads_without_origin(docker_environment):
    with client() as api:
        response = api.get(
            "/api/research/spot/symbols",
            headers={PROXY_HEADER: docker_environment["LOCAL_PROXY_SECRET"]},
        )
    assert response.status_code == 200
    assert docker_environment["LOCAL_PROXY_SECRET"] not in response.text
    assert response.headers["cache-control"] == "no-store"


@pytest.mark.parametrize(
    "headers",
    [
        {},
        {PROXY_HEADER: "wrong"},
        {"host": "api:8000"},
        {"host": "192.168.1.5:5173"},
        {"host": "127.0.0.1:9999"},
        {"host": "localhost:5173"},
        {"host": "127.0.0.1:5173@evil.invalid"},
        {"host": "[invalid"},
        {"origin": "http://evil.invalid"},
        {"origin": "http://192.168.1.5:5173"},
        {"origin": "null"},
        {"origin": ""},
        {"origin": ORIGIN + "/"},
        {"x-forwarded-host": HOST, "host": "evil.invalid"},
    ],
)
def test_direct_or_spoofed_requests_rejected(docker_environment, headers):
    supplied = {PROXY_HEADER: docker_environment["LOCAL_PROXY_SECRET"]}
    if not headers:
        supplied = {}
    supplied.update(headers)
    with client() as api:
        response = api.get("/health", headers=supplied)
    assert response.status_code == 421


@pytest.mark.parametrize("header", ["host", "origin", PROXY_HEADER])
def test_duplicate_security_headers_rejected(docker_environment, header):
    headers = [
        ("host", HOST),
        ("origin", ORIGIN),
        (PROXY_HEADER, docker_environment["LOCAL_PROXY_SECRET"]),
    ]
    headers.append(next(item for item in headers if item[0] == header))
    with client() as api:
        assert api.get("/health", headers=headers).status_code == 421


def test_protected_request_requires_exact_origin(docker_environment):
    headers = {PROXY_HEADER: docker_environment["LOCAL_PROXY_SECRET"]}
    with client() as api:
        assert (
            api.post("/api/research/spot/anything/refresh", headers=headers).status_code
            == 421
        )
        headers["origin"] = ORIGIN
        # Passing the guard does not authorize an invalid instrument or refresh.
        assert (
            api.post("/api/research/spot/anything/refresh", headers=headers).status_code
            == 422
        )
        assert (
            api.get(
                "/openapi.json", headers={PROXY_HEADER: headers[PROXY_HEADER]}
            ).status_code
            == 421
        )


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("TRADING_PLATFORM_DOCKER_LOCAL", "false"),
        ("TRADING_PLATFORM_MODE", None),
        ("TRADING_PLATFORM_MODE", "paper"),
        ("ENABLE_LIVE_TRADING", None),
        ("ENABLE_LIVE_TRADING", "true"),
        ("ENABLE_AUTO_EXECUTION", None),
        ("ENABLE_AUTO_EXECUTION", "true"),
        ("TRADING_PLATFORM_ENVIRONMENT", "prod"),
        ("LOCAL_WEB_HOST", "0.0.0.0"),
        ("LOCAL_WEB_HOST", "localhost"),
        ("LOCAL_WEB_PORT", "0"),
        ("LOCAL_WEB_PORT", "05173"),
        ("LOCAL_WEB_PORT", "65536"),
        ("TRADING_PLATFORM_FRONTEND_ORIGIN", "http://evil.invalid:5173"),
        ("TRADING_PLATFORM_FRONTEND_ORIGIN", ORIGIN + "/"),
        ("LOCAL_PROXY_SECRET", None),
        ("LOCAL_PROXY_SECRET", "placeholder"),
        ("LOCAL_PROXY_SECRET", "0" * 64),
    ],
)
def test_unsafe_startup_fails_closed(docker_environment, monkeypatch, key, value):
    if value is None:
        monkeypatch.delenv(key)
    else:
        monkeypatch.setenv(key, value)
    with pytest.raises(ValueError):
        create_app(_docker_local=True)


@pytest.mark.parametrize("missing", [IMAGE_MARKER, Path("/.dockerenv")])
def test_native_cannot_activate_container_path(
    docker_environment, monkeypatch, missing
):
    monkeypatch.setattr(Path, "is_file", lambda path: path != missing)
    with pytest.raises(ValueError, match="dedicated Compose image"):
        load_docker_local_settings(load_app_settings())


def test_native_guard_ignores_docker_environment_and_secret(docker_environment):
    with TestClient(create_app(), base_url=ORIGIN, client=("172.20.0.5", 12345)) as api:
        assert (
            api.get(
                "/health",
                headers={PROXY_HEADER: docker_environment["LOCAL_PROXY_SECRET"]},
            ).status_code
            == 421
        )
    with TestClient(create_app(), base_url=ORIGIN) as api:
        assert api.get("/health").status_code == 200


def test_database_credentials_are_encoded_not_interpolated(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "")
    local_password = secrets.token_urlsafe(32) + "@:/#"
    monkeypatch.setenv("POSTGRES_USER", "research")
    monkeypatch.setenv("POSTGRES_PASSWORD", local_password)
    monkeypatch.setenv("POSTGRES_DB", "research")
    configure_database()
    import os

    parsed = make_url(os.environ["DATABASE_URL"])
    assert parsed.password == local_password
    assert parsed.host == "postgres"
