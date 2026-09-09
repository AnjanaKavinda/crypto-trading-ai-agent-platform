from __future__ import annotations

import json
from collections import Counter

import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from trading_platform_api.config import AppSettings, DeploymentEnvironment, OperatingMode
from trading_platform_api.feature_flags import FeatureFlags
from trading_platform_api.main import create_app

SERVICE_NAME = "trading-platform-api"
NO_STORE_CACHE_CONTROL = "no-store"
HEALTH_PATH = "/health"
LIVENESS_PATH = "/health/live"
TRADING_READINESS_PATH = "/health/trading-readiness"
EXPECTED_ROUTE_PATHS = {HEALTH_PATH, LIVENESS_PATH, TRADING_READINESS_PATH}
EXPECTED_HEALTH_BODY = {"service": SERVICE_NAME, "status": "HEALTHY"}
EXPECTED_LIVENESS_BODY = {"service": SERVICE_NAME, "status": "ALIVE"}
EXPECTED_TRADING_READINESS_BODY = {
    "service": SERVICE_NAME,
    "status": "UNKNOWN",
    "ready": False,
    "reason_code": "READINESS_EVALUATOR_NOT_IMPLEMENTED",
}
CANONICAL_TRADING_READINESS_STATUSES = {
    "READY",
    "DEGRADED",
    "BLOCKED",
    "EMERGENCY",
    "UNKNOWN",
}


def _create_client(settings: AppSettings | None = None) -> TestClient:
    return TestClient(create_app(settings=settings))


def _health_routes(app) -> list[APIRoute]:
    return [
        route
        for route in app.routes
        if isinstance(route, APIRoute) and route.path in EXPECTED_ROUTE_PATHS
    ]


def test_health_routes_are_registered_once_per_application_instance() -> None:
    first_app = create_app()
    second_app = create_app()
    expected_route_counts = Counter(EXPECTED_ROUTE_PATHS)

    first_routes = _health_routes(first_app)
    second_routes = _health_routes(second_app)

    assert Counter(route.path for route in first_routes) == expected_route_counts
    assert Counter(route.path for route in second_routes) == expected_route_counts
    assert all(route.methods == {"GET"} for route in first_routes)
    assert all(route.methods == {"GET"} for route in second_routes)
    assert {id(route) for route in first_routes}.isdisjoint({id(route) for route in second_routes})


@pytest.mark.parametrize("path", sorted(EXPECTED_ROUTE_PATHS))
def test_health_routes_reject_post_requests(path: str) -> None:
    with _create_client() as client:
        response = client.post(path)

    assert response.status_code == 405


def test_health_endpoint_returns_expected_body_and_no_store_header() -> None:
    with _create_client() as client:
        response = client.get(HEALTH_PATH)

    assert response.status_code == 200
    assert response.json() == EXPECTED_HEALTH_BODY
    assert response.headers["Cache-Control"] == NO_STORE_CACHE_CONTROL


def test_liveness_endpoint_returns_expected_body_and_no_store_header() -> None:
    with _create_client() as client:
        response = client.get(LIVENESS_PATH)

    assert response.status_code == 200
    assert response.json() == EXPECTED_LIVENESS_BODY
    assert response.headers["Cache-Control"] == NO_STORE_CACHE_CONTROL


@pytest.mark.parametrize(
    ("path", "expected_body"),
    [
        (HEALTH_PATH, EXPECTED_HEALTH_BODY),
        (LIVENESS_PATH, EXPECTED_LIVENESS_BODY),
    ],
)
def test_health_and_liveness_responses_do_not_include_ready_field(
    path: str,
    expected_body: dict[str, object],
) -> None:
    with _create_client() as client:
        response = client.get(path)

    assert response.json() == expected_body
    assert "ready" not in response.json()


def test_trading_readiness_endpoint_returns_fail_closed_unknown_with_no_store_header() -> None:
    with _create_client() as client:
        response = client.get(TRADING_READINESS_PATH)

    payload = response.json()

    assert response.status_code == 503
    assert payload == EXPECTED_TRADING_READINESS_BODY
    assert response.headers["Cache-Control"] == NO_STORE_CACHE_CONTROL
    assert payload["status"] in CANONICAL_TRADING_READINESS_STATUSES
    assert payload["status"] == "UNKNOWN"
    assert payload["status"] != "EMERGENCY_STOP"


@pytest.mark.parametrize(
    "settings",
    [
        AppSettings(environment=DeploymentEnvironment.DEV, mode=OperatingMode.RESEARCH),
        AppSettings(
            environment=DeploymentEnvironment.PROD,
            mode=OperatingMode.LIVE_SUPERVISED,
        ),
        AppSettings(
            environment=DeploymentEnvironment.DEV,
            mode=OperatingMode.RESEARCH,
            feature_flags=FeatureFlags(enable_live_trading=True),
        ),
        AppSettings(
            environment=DeploymentEnvironment.DEV,
            mode=OperatingMode.RESEARCH,
            feature_flags=FeatureFlags(enable_auto_execution=True),
        ),
        AppSettings(
            environment=DeploymentEnvironment.PROD,
            mode=OperatingMode.LIVE_SUPERVISED,
            feature_flags=FeatureFlags(enable_live_trading=True, enable_auto_execution=True),
        ),
    ],
    ids=[
        "dev-research",
        "prod-live-supervised",
        "live-trading-flag-only",
        "auto-execution-flag-only",
        "prod-live-supervised-with-dangerous-flags",
    ],
)
def test_trading_readiness_stays_fail_closed_in_all_supported_contexts(
    settings: AppSettings,
) -> None:
    with _create_client(settings=settings) as client:
        response = client.get(TRADING_READINESS_PATH)

    assert response.status_code == 503
    assert response.json() == EXPECTED_TRADING_READINESS_BODY


@pytest.mark.parametrize(
    ("path", "expected_keys"),
    [
        (HEALTH_PATH, set(EXPECTED_HEALTH_BODY)),
        (LIVENESS_PATH, set(EXPECTED_LIVENESS_BODY)),
        (TRADING_READINESS_PATH, set(EXPECTED_TRADING_READINESS_BODY)),
    ],
)
def test_health_endpoints_do_not_expose_internal_configuration_or_process_details(
    path: str,
    expected_keys: set[str],
) -> None:
    with _create_client() as client:
        response = client.get(path)

    payload = response.json()
    rendered_payload = json.dumps(payload).lower()

    assert set(payload) == expected_keys
    assert "trading_platform_environment" not in rendered_payload
    assert "trading_platform_mode" not in rendered_payload
    assert "enable_live_trading" not in rendered_payload
    assert "enable_auto_execution" not in rendered_payload
    assert "feature_flags" not in rendered_payload
    assert "traceback" not in rendered_payload
    assert "host" not in rendered_payload
    assert "process" not in rendered_payload


def test_health_openapi_documents_expected_status_codes_and_schemas() -> None:
    with _create_client() as client:
        response = client.get("/openapi.json")

    schema = response.json()
    health_operation = schema["paths"][HEALTH_PATH]["get"]
    liveness_operation = schema["paths"][LIVENESS_PATH]["get"]
    readiness_operation = schema["paths"][TRADING_READINESS_PATH]["get"]

    assert health_operation["responses"]["200"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/ServiceHealthResponse"
    }
    assert liveness_operation["responses"]["200"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/LivenessResponse"
    }
    assert readiness_operation["responses"]["503"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/TradingReadinessResponse"
    }
    assert "200" not in readiness_operation["responses"]
    assert health_operation.get("parameters", []) == []
    assert liveness_operation.get("parameters", []) == []
    assert readiness_operation.get("parameters", []) == []
    assert "requestBody" not in health_operation
    assert "requestBody" not in liveness_operation
    assert "requestBody" not in readiness_operation
