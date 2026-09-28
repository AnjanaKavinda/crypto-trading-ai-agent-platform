"""Real PostgreSQL integration on an explicitly disposable local database."""

import asyncio
import os
from dataclasses import replace
from hashlib import sha256
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import insert, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from test_history_selection import history
from test_point_in_time import evidence
from trading_platform_api.lineage.codec import LineageError, encode, key_for
from trading_platform_api.lineage.store import SqlAlchemyLineageStore
from trading_platform_api.lineage.tables import links, records
from trading_platform_api.market_data.contracts import DatasetVersionReference
from trading_platform_api.market_data.history_selection import reconstruct_history
from trading_platform_api.market_data.point_in_time import reconstruct_pinned_snapshot


@pytest.fixture(scope="module")
def database_url():
    value = os.environ.get("LINEAGE_TEST_DATABASE_URL")
    if not value:
        pytest.skip(
            "Real PostgreSQL requires LINEAGE_TEST_DATABASE_URL (enabled in Product CI)."
        )
    url = make_url(value)
    assert url.drivername == "postgresql+asyncpg"
    assert url.host in ("127.0.0.1", "localhost") and url.database == "lineage_test"
    previous = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = value
    config = Config("apps/api/alembic.ini")
    command.upgrade(config, "head")
    try:
        yield value
    finally:
        command.downgrade(config, "0002_audit_event_foundation")
        if previous is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = previous


def test_postgresql_roundtrip_graph_and_replay(database_url):
    async def check():
        engine = create_async_engine(database_url)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        args = history()
        expected = reconstruct_history(**args)
        ordered = (
            *args["sources"],
            args["dataset"],
            args["universe"],
            args["revisions"][0].observation,
            args["revisions"][0],
            expected.manifest,
        )
        try:
            async with sessions.begin() as session:
                store = SqlAlchemyLineageStore(session)
                for record in ordered:
                    assert await store.append(record) == key_for(record)
                    assert await store.append(record) == key_for(record)
            async with sessions() as session:
                store = SqlAlchemyLineageStore(session)
                graph = await store.resolve((key_for(expected.manifest),))
                assert len(graph) == len(ordered)
                for record in ordered:
                    assert graph[key_for(record)] == record
                replay = dict(
                    args,
                    universe=graph[key_for(args["universe"])],
                    dataset=graph[key_for(args["dataset"])],
                    revisions=tuple(graph[key_for(r)] for r in args["revisions"]),
                    sources=tuple(graph[key_for(s)] for s in args["sources"]),
                )
                assert reconstruct_history(**replay) == expected
                with pytest.raises(LineageError, match="budget"):
                    await store.resolve(
                        (key_for(expected.manifest),), maximum_records=1
                    )
        finally:
            await engine.dispose()

    asyncio.run(check())


def test_postgresql_rollback_missing_refs_and_mutations(database_url):
    async def check():
        engine = create_async_engine(database_url)
        sessions = async_sessionmaker(engine)
        args = history()
        source = args["sources"][0]
        try:
            with pytest.raises(LineageError):
                async with sessions.begin() as session:
                    store = SqlAlchemyLineageStore(session)
                    await store.append(source)
                    await store.append(args["universe"])
            async with sessions() as session:
                with pytest.raises(LineageError, match="missing"):
                    await SqlAlchemyLineageStore(session).get(key_for(source))
            async with sessions.begin() as session:
                await SqlAlchemyLineageStore(session).append(source)
            with pytest.raises(LineageError, match="different content"):
                async with sessions.begin() as session:
                    await SqlAlchemyLineageStore(session).append(
                        replace(source, content_sha256="d" * 64)
                    )
            for table in ("lineage_records", "lineage_links"):
                for sql in (
                    f"DELETE FROM {table}",
                    f"UPDATE {table} SET version=version",
                    f"TRUNCATE {table} CASCADE",
                ):
                    with pytest.raises(DBAPIError):
                        async with sessions.begin() as session:
                            await session.execute(text(sql))
            with pytest.raises(DBAPIError):
                async with sessions.begin() as session:
                    await session.execute(
                        insert(links).values(
                            contract_id="C-091",
                            record_id=str(source.source_record_id),
                            version="1",
                            target_contract_id="C-091",
                            target_record_id="missing",
                            target_version="1",
                        )
                    )
        finally:
            await engine.dispose()

    asyncio.run(check())


def test_postgresql_concurrent_duplicate_and_conflict(database_url):
    async def check():
        engine = create_async_engine(database_url)
        sessions = async_sessionmaker(engine)
        source = history()["sources"][0]

        async def append(record):
            async with sessions.begin() as session:
                return await SqlAlchemyLineageStore(session).append(record)

        try:
            result = await asyncio.gather(append(source), append(source))
            assert result[0] == result[1]
            fresh = history()["sources"][0]
            outcomes = await asyncio.gather(
                append(fresh),
                append(replace(fresh, content_sha256="c" * 64)),
                return_exceptions=True,
            )
            assert sum(isinstance(item, LineageError) for item in outcomes) == 1
            async with sessions() as session:
                assert (
                    await SqlAlchemyLineageStore(session).get(key_for(source)) == source
                )
        finally:
            await engine.dispose()

    asyncio.run(check())


def test_postgresql_read_rejects_corrupt_insert(database_url):
    async def check():
        engine = create_async_engine(database_url)
        sessions = async_sessionmaker(engine)
        source = history()["sources"][0]
        key = key_for(source)
        document = encode(source)
        try:
            async with sessions.begin() as session:
                await session.execute(
                    insert(records).values(
                        contract_id=key.contract_id,
                        record_id=key.record_id,
                        version=key.version,
                        document=document,
                        document_sha256=sha256(document.encode()).hexdigest(),
                        evidence_sha256="0" * 64,
                    )
                )
            async with sessions() as session:
                with pytest.raises(LineageError, match="digest mismatch"):
                    await SqlAlchemyLineageStore(session).get(key)
        finally:
            await engine.dispose()

    asyncio.run(check())


def test_postgresql_legacy_snapshot_roundtrip(database_url):
    async def check():
        engine = create_async_engine(database_url)
        sessions = async_sessionmaker(engine)
        args = evidence()
        dataset = replace(args["dataset"], dataset_id=str(uuid4()))
        snapshot = replace(
            args["snapshot"],
            dataset_version=DatasetVersionReference(
                dataset.dataset_id, dataset.version
            ),
        )
        args.update(dataset=dataset, snapshot=snapshot)
        ordered = (*args["sources"], *args["observations"], dataset, snapshot)
        try:
            async with sessions.begin() as session:
                store = SqlAlchemyLineageStore(session)
                for record in ordered:
                    await store.append(record)
            async with sessions() as session:
                graph = await SqlAlchemyLineageStore(session).resolve(
                    (key_for(snapshot),)
                )
                replay = dict(
                    args,
                    snapshot=graph[key_for(snapshot)],
                    dataset=graph[key_for(dataset)],
                    observations=tuple(
                        graph[key_for(item)] for item in args["observations"]
                    ),
                    sources=tuple(graph[key_for(item)] for item in args["sources"]),
                )
                assert reconstruct_pinned_snapshot(
                    **replay
                ) == reconstruct_pinned_snapshot(**args)
        finally:
            await engine.dispose()

    asyncio.run(check())
