from __future__ import annotations

import asyncio
import hashlib
from datetime import UTC, datetime

import pytest
from trading_platform_api.lineage.backups import BackupBundleError, verify_backup_bundle
from trading_platform_api.lineage.local_backups import (
    LocalBackupError,
    collect_referenced_archive_objects,
    create_local_backup,
    restore_local_backup,
)


class MemoryStore:
    def __init__(self, objects: dict[str, bytes] | None = None) -> None:
        self.objects = {} if objects is None else dict(objects)

    async def put_if_absent(self, key: str, value: bytes) -> None:
        if key in self.objects and self.objects[key] != value:
            raise ValueError("immutable key conflict")
        self.objects[key] = value

    async def get(self, key: str) -> bytes:
        return self.objects[key]


class Rows:
    def __init__(self, values: list[tuple[str, str, str, str]]) -> None:
        self.values = values

    def all(self) -> list[tuple[str, str, str, str]]:
        return self.values


class Session:
    def __init__(self, rows: list[tuple[str, str, str, str]]) -> None:
        self.rows = rows

    async def execute(self, _statement: object) -> Rows:
        return Rows(self.rows)


def digests(values: dict[str, bytes]) -> list[tuple[str, str, str, str]]:
    return [
        (
            key,
            hashlib.sha256(payload).hexdigest(),
            f"{key}.manifest.json",
            hashlib.sha256(values[f"{key}.manifest.json"]).hexdigest(),
        )
        for key, payload in values.items()
        if not key.endswith(".manifest.json")
    ]


def test_local_backup_captures_referenced_archive_objects_and_manifest() -> None:
    async def check() -> None:
        objects = {
            "spot-ohlcv/data.gz": b"cold data",
            "spot-ohlcv/data.gz.manifest.json": b"manifest",
        }
        archive = MemoryStore(objects)
        backups = MemoryStore()
        session = Session(digests(objects))

        digest = await create_local_backup(
            session,
            archive,
            backups,
            backup_id="run-20261004T120000Z",
            created_at=datetime(2026, 10, 4, 12, tzinfo=UTC),
            database_dump=b"postgres dump",
        )

        key = "daily/2026/10/04/run-20261004T120000Z.zip"
        verified = verify_backup_bundle(backups.objects[key])
        assert verified.bundle_sha256 == digest
        assert verified.database_dump == b"postgres dump"
        assert verified.archive_objects == objects

    asyncio.run(check())


def test_local_backup_fails_closed_if_referenced_object_is_missing() -> None:
    async def check() -> None:
        archive = MemoryStore({"cold.gz": b"bytes"})
        session = Session(
            [
                (
                    "cold.gz",
                    hashlib.sha256(b"bytes").hexdigest(),
                    "missing.json",
                    "0" * 64,
                )
            ]
        )

        with pytest.raises(LocalBackupError, match="unavailable"):
            await collect_referenced_archive_objects(session, archive)

    asyncio.run(check())


def test_local_backup_restore_verifies_before_restoring_database() -> None:
    async def check() -> None:
        objects = {"cold.gz": b"cold data", "cold.gz.manifest.json": b"manifest"}
        source = MemoryStore(objects)
        backups = MemoryStore()
        session = Session(digests(objects))
        await create_local_backup(
            session,
            source,
            backups,
            backup_id="restore-check",
            created_at=datetime(2026, 10, 4, tzinfo=UTC),
            database_dump=b"postgres dump",
        )
        backup_key = "daily/2026/10/04/restore-check.zip"
        restored_archives = MemoryStore()
        restored_database: list[bytes] = []

        async def restore_dump(payload: bytes) -> None:
            restored_database.append(payload)

        await restore_local_backup(
            backups,
            restored_archives,
            object_key=backup_key,
            restore_database=restore_dump,
        )

        assert restored_archives.objects == objects
        assert restored_database == [b"postgres dump"]

    asyncio.run(check())


def test_local_backup_restore_rejects_corrupt_bundle_before_database_callback() -> None:
    async def check() -> None:
        backups = MemoryStore({"bad.zip": b"not a zip"})
        called = False

        async def restore_dump(_payload: bytes) -> None:
            nonlocal called
            called = True

        with pytest.raises(BackupBundleError, match="malformed"):
            await restore_local_backup(
                backups,
                MemoryStore(),
                object_key="bad.zip",
                restore_database=restore_dump,
            )
        assert not called

    asyncio.run(check())
