from fastapi import FastAPI
from fastapi.routing import APIRoute

from trading_platform_api.config import AppSettings, DeploymentEnvironment, OperatingMode
from trading_platform_api.main import app, create_app


def test_create_app_returns_fastapi_instance() -> None:
    assert isinstance(create_app(), FastAPI)


def test_module_level_app_is_fastapi_instance() -> None:
    assert isinstance(app, FastAPI)


def test_factory_returns_separate_instances() -> None:
    first_app = create_app()
    second_app = create_app()

    assert first_app is not second_app
    assert first_app.state.settings is not second_app.state.settings


def test_app_metadata_is_static_and_expected() -> None:
    created_app = create_app()

    assert created_app.title == "Trading Platform API"
    assert created_app.version == "0.1.0"


def test_injected_settings_are_attached_to_created_app_instance() -> None:
    settings = AppSettings(
        environment=DeploymentEnvironment.STAGING,
        mode=OperatingMode.PAPER,
    )

    created_app = create_app(settings=settings)

    assert created_app.state.settings is settings


def test_live_supervised_mode_is_context_only_and_adds_no_trading_routes() -> None:
    created_app = create_app(
        settings=AppSettings(
            environment=DeploymentEnvironment.PROD,
            mode=OperatingMode.LIVE_SUPERVISED,
        )
    )

    route_paths: set[str] = set()

    for route in created_app.routes:
        if isinstance(route, APIRoute):
            route_paths.add(route.path)
            continue

        included_router = getattr(getattr(route, "include_context", None), "included_router", None)
        if included_router is None:
            continue

        route_paths.update(
            nested_route.path
            for nested_route in included_router.routes
            if isinstance(nested_route, APIRoute)
        )

    assert created_app.state.settings.mode is OperatingMode.LIVE_SUPERVISED
    assert not any("trade" in route_path or "execute" in route_path for route_path in route_paths)
