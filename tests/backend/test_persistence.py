from __future__ import annotations

import asyncio
import importlib

import asyncpg
import pytest

from trading_platform_api.persistence import (
    APPROVED_DATABASE_DRIVER,
    DatabaseSettingsError,
    create_async_engine_instance,
    create_async_session_factory,
    load_database_settings,
    transactional_session,
)

VALID_DATABASE_URL = (
    "******example.internal:5432/trading_platform"
)
SECRET_QUERY_DATABASE_URL = (
    "******example.internal:5432/trading_platform"
    "?sslmode=require&api_token=query_secret"
)


class FakeSession:
    def __init__(
        self,
        *,
        commit_error: BaseException | None = None,
        rollback_error: BaseException | None = None,
        close_error: BaseException | None = None,
    ) -> None:
        self.commit_error = commit_error
        self.rollback_error = rollback_error
        self.close_error = close_error
        self.events: list[str] = []

    async def commit(self) -> None:
        self.events.append("commit")
        if self.commit_error is not None:
            raise self.commit_error

    async def rollback(self) -> None:
        self.events.append("rollback")
        if self.rollback_error is not None:
            raise self.rollback_error

    async def close(self) -> None:
        self.events.append("close")
        if self.close_error is not None:
            raise self.close_error


def test_persistence_imports_and_application_creation_do_not_require_database_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    persistence_session_module = importlib.import_module("trading_platform_api.persistence.session")

    def fail_engine_creation(*args, **kwargs):
        raise AssertionError("application import and creation must not construct a database engine")

    monkeypatch.setattr(persistence_session_module, "create_async_engine", fail_engine_creation)

    main_module = importlib.import_module("trading_platform_api.main")
    reloaded_main_module = importlib.reload(main_module)
    created_app = reloaded_main_module.create_app()

    assert created_app.title == "Trading Platform API"


def test_explicit_valid_async_postgresql_url_is_accepted() -> None:
    settings = load_database_settings({"DATABASE_URL": VALID_DATABASE_URL})

    assert settings.database_url == VALID_DATABASE_URL
    assert settings.drivername == APPROVED_DATABASE_DRIVER


@pytest.mark.parametrize(
    ("environment_mapping", "expected_message"),
    [
        ({}, "DATABASE_URL is required"),
        ({"DATABASE_URL": ""}, "DATABASE_URL must not be blank."),
        ({"DATABASE_URL": "   "}, "DATABASE_URL must not be whitespace-only."),
        (
            {"DATABASE_URL": "postgresql+asyncpg://"},
            "DATABASE_URL must include a PostgreSQL host and database name.",
        ),
        (
            {"DATABASE_URL": "******example.internal:5432/trading_platform"},
            "DATABASE_URL must use the postgresql+asyncpg:// SQLAlchemy async dialect.",
        ),
        (
            {"DATABASE_URL": "sqlite:///tmp/trading_platform.db?api_token=query_secret"},
            "DATABASE_URL must use PostgreSQL via the postgresql+asyncpg:// SQLAlchemy async dialect.",
        ),
        (
            {"DATABASE_URL": "******example.internal:3306/trading_platform"},
            "DATABASE_URL must be a valid postgresql+asyncpg:// SQLAlchemy URL.",
        ),
    ],
)
def test_invalid_database_urls_fail_closed_with_sanitized_errors(
    environment_mapping: dict[str, str],
    expected_message: str,
) -> None:
    with pytest.raises(DatabaseSettingsError) as exc_info:
        load_database_settings(environment_mapping)

    assert str(exc_info.value) == expected_message
    rendered_error = str(exc_info.value)
    assert "db_user" not in rendered_error
    assert "db_password" not in rendered_error
    assert "example.internal" not in rendered_error
    assert "query_secret" not in rendered_error


def test_database_settings_and_errors_redact_secret_bearing_url_details() -> None:
    settings = load_database_settings({"DATABASE_URL": SECRET_QUERY_DATABASE_URL})
    rendered_settings = f"{settings!r} {settings}"

    assert SECRET_QUERY_DATABASE_URL not in rendered_settings
    assert "db_user" not in rendered_settings
    assert "db_password" not in rendered_settings
    assert "example.internal" not in rendered_settings
    assert "query_secret" not in rendered_settings

    with pytest.raises(DatabaseSettingsError) as exc_info:
        load_database_settings(
            {
                "DATABASE_URL": "sqlite:///tmp/trading_platform.db?username=db_user&******"
            }
        )

    rendered_error = str(exc_info.value)
    assert "db_user" not in rendered_error
    assert "db_password" not in rendered_error
    assert "sqlite:///tmp/trading_platform.db?username=db_user&******" not in rendered_error


def test_engine_and_session_factories_use_async_stack_without_connecting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connect_calls: list[tuple[tuple[object, ...], dict[str, object]]] = []

    async def fail_connect(*args, **kwargs):
        connect_calls.append((args, kwargs))
        raise AssertionError("engine and session factory construction must not connect")

    monkeypatch.setattr(asyncpg, "connect", fail_connect)

    engine = create_async_engine_instance(load_database_settings({"DATABASE_URL": VALID_DATABASE_URL}))
    session_factory = create_async_session_factory(engine)

    try:
        assert engine.url.drivername == APPROVED_DATABASE_DRIVER
        assert engine.dialect.name == "postgresql"
        assert engine.dialect.driver == "asyncpg"
        assert session_factory.kw["expire_on_commit"] is False
        assert connect_calls == []
    finally:
        asyncio.run(engine.dispose())


def test_successful_transaction_scope_commits_once_and_closes() -> None:
    session = FakeSession()

    async def run_scope() -> None:
        async with transactional_session(lambda: session) as managed_session:
            assert managed_session is session
            session.events.append("body")

    asyncio.run(run_scope())

    assert session.events == ["body", "commit", "close"]


def test_failed_transaction_scope_rolls_back_closes_and_reraises_original_exception() -> None:
    session = FakeSession()
    original_error = RuntimeError("transaction body failed")

    async def run_scope() -> None:
        async with transactional_session(lambda: session):
            session.events.append("body")
            raise original_error

    with pytest.raises(RuntimeError) as exc_info:
        asyncio.run(run_scope())

    assert exc_info.value is original_error
    assert session.events == ["body", "rollback", "close"]


def test_commit_failure_rolls_back_closes_and_propagates_original_failure() -> None:
    original_error = RuntimeError("commit failed")
    session = FakeSession(commit_error=original_error)

    async def run_scope() -> None:
        async with transactional_session(lambda: session):
            session.events.append("body")

    with pytest.raises(RuntimeError) as exc_info:
        asyncio.run(run_scope())

    assert exc_info.value is original_error
    assert session.events == ["body", "commit", "rollback", "close"]


def test_persistence_package_introduces_foundation_only_and_no_repository_crud_exports() -> None:
    persistence_module = importlib.import_module("trading_platform_api.persistence")

    assert "transactional_session" in persistence_module.__all__
    assert not any("repository" in exported_name.lower() for exported_name in persistence_module.__all__)
