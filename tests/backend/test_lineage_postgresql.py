"""Real PostgreSQL integration on an explicitly disposable local database."""

import asyncio
import base64
import hashlib
import json
import os
import shutil
from dataclasses import replace
from datetime import UTC, datetime
from hashlib import sha256
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import delete, insert, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from test_history_selection import history
from test_lineage_quality import records_for_report
from test_point_in_time import evidence
from trading_platform_api.lineage.archival import archive_market_data_batch
from trading_platform_api.lineage.archive_storage import LocalFilesystemObjectStore
from trading_platform_api.lineage.codec import LineageError, encode, key_for
from trading_platform_api.lineage.local_backup_cli import _backup, _restore
from trading_platform_api.lineage.store import (
    SqlAlchemyLineageStore,
    append_validated_market_snapshot,
)
from trading_platform_api.lineage.tables import (
    archive_members,
    links,
    market_payloads,
    payload_events,
    records,
)
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


def test_postgresql_valid_quality_report_is_linked_and_replayable(database_url):
    async def check():
        engine = create_async_engine(database_url)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        sources, observations, snapshot, quality = records_for_report()
        try:
            async with sessions.begin() as session:
                store = SqlAlchemyLineageStore(session)
                await append_validated_market_snapshot(
                    store,
                    sources=sources,
                    observations=observations,
                    snapshot=snapshot,
                    quality=quality,
                )
            async with sessions() as session:
                store = SqlAlchemyLineageStore(session)
                graph = await store.resolve((key_for(quality),))
                assert graph[key_for(quality)] == quality
                assert graph[key_for(snapshot)] == snapshot
                assert all(graph[key_for(item)] == item for item in observations)
                assert all(graph[key_for(item)] == item for item in sources)
                assert len(graph) == len(sources) + len(observations) + 2
        finally:
            await engine.dispose()

    asyncio.run(check())


def test_postgresql_verified_archive_resolves_cold_and_fails_closed_on_tamper(
    database_url, tmp_path
):
    class RollbackArchiveFixture(Exception):
        pass

    async def check():
        engine = create_async_engine(database_url)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        sources, observations, snapshot, quality = records_for_report()
        object_store = LocalFilesystemObjectStore(tmp_path / "archive")
        keys = tuple(key_for(item) for item in observations)
        try:
            with pytest.raises(RollbackArchiveFixture):
                async with sessions.begin() as session:
                    store = SqlAlchemyLineageStore(session, archive_store=object_store)
                    await append_validated_market_snapshot(
                        store,
                        sources=sources,
                        observations=observations,
                        snapshot=snapshot,
                        quality=quality,
                    )
                    object_key = await archive_market_data_batch(
                        session,
                        object_store,
                        keys,
                        now=datetime(2026, 10, 4, tzinfo=UTC),
                    )
                    archive = (
                        (
                            await session.execute(
                                select(archive_members).where(
                                    archive_members.c.object_key == object_key
                                )
                            )
                        )
                        .mappings()
                        .all()
                    )
                    assert len(archive) == len(observations)

                    # Exercise the database-gated lifecycle transition and
                    # prove the normal resolver reads and verifies cold bytes.
                    for item, key in zip(observations, keys, strict=True):
                        document_sha = sha256(encode(item).encode("utf-8")).hexdigest()
                        event_material = "|".join(
                            (
                                key.contract_id,
                                key.record_id,
                                key.version,
                                "HOT_REMOVED",
                                document_sha,
                            )
                        )
                        await session.execute(
                            insert(payload_events).values(
                                event_id=hashlib.sha256(
                                    event_material.encode("utf-8")
                                ).hexdigest(),
                                contract_id=key.contract_id,
                                record_id=key.record_id,
                                version=key.version,
                                event_type="HOT_REMOVED",
                                object_key=object_key,
                                payload_sha256=document_sha,
                                occurred_at=datetime(2026, 10, 4, tzinfo=UTC),
                            )
                        )
                        deleted = await session.execute(
                            delete(market_payloads).where(
                                market_payloads.c.contract_id == key.contract_id,
                                market_payloads.c.record_id == key.record_id,
                                market_payloads.c.version == key.version,
                            )
                        )
                        assert deleted.rowcount == 1
                        assert await store.get(key) == item

                    graph = await store.resolve((key_for(quality),))
                    assert all(graph[key_for(item)] == item for item in observations)

                    archive_file = tmp_path / "archive" / object_key
                    archive_file.write_bytes(b"tampered")
                    with pytest.raises(LineageError, match="digest"):
                        await store.get(keys[0])
                    raise RollbackArchiveFixture()
        finally:
            await engine.dispose()

    asyncio.run(check())


def test_postgresql_local_backup_restore_preserves_cold_c001_references(
    database_url, tmp_path, monkeypatch
):
    source_url = make_url(database_url).set(database="trading_backup_source_ci")
    monkeypatch.setenv("DATABASE_URL", source_url.render_as_string(hide_password=False))
    command.upgrade(Config("apps/api/alembic.ini"), "head")

    async def check():
        restore_database = "trading_restore_ci"
        service_file = tmp_path / "pg_service.conf"
        service_file.write_text(
            "\n".join(
                (
                    "[trading_dump]",
                    "host=127.0.0.1",
                    f"port={source_url.port or 5432}",
                    f"dbname={source_url.database}",
                    f"user={source_url.username or 'postgres'}",
                    "",
                    "[trading_restore_ci]",
                    "host=127.0.0.1",
                    f"port={source_url.port or 5432}",
                    f"dbname={restore_database}",
                    f"user={source_url.username or 'postgres'}",
                    "",
                )
            ),
            encoding="utf-8",
        )
        service_file.chmod(0o600)
        archive_root = tmp_path / "archive"
        backup_root = tmp_path / "backup"
        monkeypatch.setenv("TRADING_PLATFORM_PG_SERVICE_FILE", str(service_file))
        monkeypatch.setenv("TRADING_PLATFORM_PG_DUMP_SERVICE", "trading_dump")
        monkeypatch.setenv("TRADING_PLATFORM_PG_RESTORE_SERVICE", restore_database)
        monkeypatch.setenv("TRADING_PLATFORM_LOCAL_ARCHIVE_ROOT", str(archive_root))
        monkeypatch.setenv("TRADING_PLATFORM_LOCAL_BACKUP_ROOT", str(backup_root))
        monkeypatch.setenv("TRADING_PLATFORM_LOCAL_ENCRYPTION_ACTIVE_KEY_ID", "ci")
        monkeypatch.setenv(
            "TRADING_PLATFORM_LOCAL_ENCRYPTION_KEYS_JSON",
            json.dumps({"ci": base64.b64encode(b"\x19" * 32).decode("ascii")}),
        )

        sources, observations, snapshot, quality = records_for_report()
        keys = tuple(key_for(item) for item in observations)
        archive_store = LocalFilesystemObjectStore(archive_root)

        async def remove_hot_payloads(session):
            for item, key in zip(observations, keys, strict=True):
                document_sha = sha256(encode(item).encode("utf-8")).hexdigest()
                event_material = "|".join(
                    (
                        key.contract_id,
                        key.record_id,
                        key.version,
                        "HOT_REMOVED",
                        document_sha,
                    )
                )
                await session.execute(
                    insert(payload_events).values(
                        event_id=hashlib.sha256(
                            event_material.encode("utf-8")
                        ).hexdigest(),
                        contract_id=key.contract_id,
                        record_id=key.record_id,
                        version=key.version,
                        event_type="HOT_REMOVED",
                        object_key=object_key,
                        payload_sha256=document_sha,
                        occurred_at=datetime.now(UTC),
                    )
                )
                deleted = await session.execute(
                    delete(market_payloads).where(
                        market_payloads.c.contract_id == key.contract_id,
                        market_payloads.c.record_id == key.record_id,
                        market_payloads.c.version == key.version,
                    )
                )
                assert deleted.rowcount == 1

        source_engine = create_async_engine(database_url)
        source_sessions = async_sessionmaker(source_engine, expire_on_commit=False)
        try:
            async with source_sessions.begin() as session:
                store = SqlAlchemyLineageStore(session, archive_store=archive_store)
                await append_validated_market_snapshot(
                    store,
                    sources=sources,
                    observations=observations,
                    snapshot=snapshot,
                    quality=quality,
                )
                object_key = await archive_market_data_batch(
                    session,
                    archive_store,
                    keys,
                    now=datetime.now(UTC),
                )
        finally:
            await source_engine.dispose()

        backup_key, backup_sha256 = await _backup()
        shutil.rmtree(archive_root)
        restored_sha256 = await _restore(backup_key)
        assert restored_sha256 == backup_sha256

        restore_url = source_url.set(database=restore_database).render_as_string(
            hide_password=False
        )
        restore_engine = create_async_engine(restore_url)
        restore_sessions = async_sessionmaker(restore_engine)
        restored_store = LocalFilesystemObjectStore(archive_root)
        try:
            async with restore_sessions.begin() as session:
                await remove_hot_payloads(session)
            async with restore_sessions() as session:
                lineage = SqlAlchemyLineageStore(session, archive_store=restored_store)
                graph = await lineage.resolve((key_for(quality),))
                assert graph[key_for(quality)] == quality
                assert graph[key_for(snapshot)] == snapshot
                assert all(graph[key_for(item)] == item for item in sources)
                assert all(graph[key_for(item)] == item for item in observations)

                hot_rows = (
                    await session.execute(
                        select(market_payloads).where(
                            market_payloads.c.contract_id == "C-001",
                            market_payloads.c.record_id.in_(
                                [key.record_id for key in keys]
                            ),
                        )
                    )
                ).all()
                assert hot_rows == []
                retained_members = (
                    await session.execute(
                        select(archive_members).where(
                            archive_members.c.object_key == object_key
                        )
                    )
                ).all()
                assert len(retained_members) == len(observations)
                retained_events = (
                    await session.execute(
                        select(payload_events).where(
                            payload_events.c.object_key == object_key,
                            payload_events.c.event_type == "HOT_REMOVED",
                        )
                    )
                ).all()
                assert len(retained_events) == len(observations)
        finally:
            await restore_engine.dispose()

        source_engine = create_async_engine(database_url)
        source_sessions = async_sessionmaker(source_engine)
        try:
            async with source_sessions.begin() as session:
                await remove_hot_payloads(session)
            async with source_sessions() as session:
                lineage = SqlAlchemyLineageStore(session, archive_store=restored_store)
                graph = await lineage.resolve((key_for(quality),))
                assert all(graph[key_for(item)] == item for item in observations)
        finally:
            await source_engine.dispose()

    asyncio.run(check())
