from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from trading_platform_api.persistence.config import DatabaseSettings


class AsyncSessionLifecycle(Protocol):
    async def commit(self) -> None: ...

    async def rollback(self) -> None: ...

    async def close(self) -> None: ...


def create_async_engine_instance(database_settings: DatabaseSettings) -> AsyncEngine:
    return create_async_engine(database_settings.database_url)


def create_async_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


@asynccontextmanager
async def transactional_session(
    session_factory: Callable[[], AsyncSessionLifecycle],
) -> AsyncIterator[AsyncSessionLifecycle]:
    session = session_factory()
    original_error: BaseException | None = None

    try:
        yield session
    except BaseException as exc:
        original_error = exc
        try:
            await session.rollback()
        except BaseException:
            pass
        raise
    else:
        try:
            await session.commit()
        except BaseException as exc:
            original_error = exc
            try:
                await session.rollback()
            except BaseException:
                pass
            raise
    finally:
        try:
            await session.close()
        except BaseException:
            if original_error is None:
                raise
