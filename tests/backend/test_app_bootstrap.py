from fastapi import FastAPI

from trading_platform_api.main import app, create_app


def test_create_app_returns_fastapi_instance() -> None:
    assert isinstance(create_app(), FastAPI)


def test_module_level_app_is_fastapi_instance() -> None:
    assert isinstance(app, FastAPI)


def test_factory_returns_separate_instances() -> None:
    first_app = create_app()
    second_app = create_app()

    assert first_app is not second_app


def test_app_metadata_is_static_and_expected() -> None:
    created_app = create_app()

    assert created_app.title == "Trading Platform API"
    assert created_app.version == "0.1.0"
