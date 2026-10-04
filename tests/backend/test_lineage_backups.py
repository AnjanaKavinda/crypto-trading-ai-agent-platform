import asyncio
import io
import zipfile
from datetime import UTC, datetime

import pytest
from trading_platform_api.lineage.backups import (
    BackupBundleError,
    BackupLimits,
    build_backup_bundle,
    load_verified_backup,
    publish_backup_bundle,
    verify_backup_bundle,
)


class MemoryObjectStore:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    async def put_if_absent(self, key: str, value: bytes) -> None:
        if key in self.objects and self.objects[key] != value:
            raise ValueError("immutable key contains different bytes")
        self.objects.setdefault(key, value)

    async def get(self, key: str) -> bytes:
        return self.objects[key]


def test_backup_bundle_is_deterministic_and_restores_exact_inputs() -> None:
    created_at = datetime(2026, 10, 4, 14, 0, tzinfo=UTC)
    objects = {
        "spot-ohlcv/v1/archive-a.gz": b"cold-object-a",
        "spot-ohlcv/v1/archive-b.gz": b"cold-object-b",
    }
    first = build_backup_bundle(
        backup_id="daily-20261004",
        created_at=created_at,
        database_dump=b"postgres dump bytes",
        archive_objects=objects,
    )
    second = build_backup_bundle(
        backup_id="daily-20261004",
        created_at=created_at,
        database_dump=b"postgres dump bytes",
        archive_objects=dict(reversed(tuple(objects.items()))),
    )

    assert first == second
    restored = verify_backup_bundle(first)
    assert restored.backup_id == "daily-20261004"
    assert restored.created_at == created_at
    assert restored.database_dump == b"postgres dump bytes"
    assert dict(restored.archive_objects) == objects


def test_backup_bundle_rejects_invalid_keys_and_hard_byte_limit() -> None:
    with pytest.raises(BackupBundleError, match="archive object key"):
        build_backup_bundle(
            backup_id="daily-1",
            created_at=datetime(2026, 10, 4, tzinfo=UTC),
            database_dump=b"dump",
            archive_objects={"../escape": b"payload"},
        )

    with pytest.raises(BackupBundleError, match="byte limit"):
        build_backup_bundle(
            backup_id="daily-1",
            created_at=datetime(2026, 10, 4, tzinfo=UTC),
            database_dump=b"x" * 2048,
            archive_objects={},
            limits=BackupLimits(max_bundle_bytes=512),
        )


def test_backup_bundle_fails_closed_on_corrupt_member() -> None:
    bundle_bytes = build_backup_bundle(
        backup_id="daily-1",
        created_at=datetime(2026, 10, 4, tzinfo=UTC),
        database_dump=b"valid dump",
        archive_objects={"spot-ohlcv/v1/archive.gz": b"valid archive"},
    )
    source = zipfile.ZipFile(io.BytesIO(bundle_bytes))
    corrupted = io.BytesIO()
    with (
        source,
        zipfile.ZipFile(corrupted, "w", compression=zipfile.ZIP_STORED) as target,
    ):
        for item in source.infolist():
            content = source.read(item.filename)
            if item.filename == "database.dump":
                content = b"corrupt dump"
            target.writestr(item, content)

    with pytest.raises(BackupBundleError, match="size or digest"):
        verify_backup_bundle(corrupted.getvalue())


def test_backup_bundle_rejects_unlisted_members() -> None:
    bundle_bytes = build_backup_bundle(
        backup_id="daily-1",
        created_at=datetime(2026, 10, 4, tzinfo=UTC),
        database_dump=b"dump",
        archive_objects={},
    )
    source = zipfile.ZipFile(io.BytesIO(bundle_bytes))
    altered = io.BytesIO()
    with (
        source,
        zipfile.ZipFile(altered, "w", compression=zipfile.ZIP_STORED) as target,
    ):
        for item in source.infolist():
            target.writestr(item, source.read(item.filename))
        target.writestr("unlisted.txt", b"extra")

    with pytest.raises(BackupBundleError, match="unlisted or missing"):
        verify_backup_bundle(altered.getvalue())


def test_publish_and_load_verify_immutable_backup() -> None:
    store = MemoryObjectStore()
    bundle = build_backup_bundle(
        backup_id="daily-1",
        created_at=datetime(2026, 10, 4, tzinfo=UTC),
        database_dump=b"dump",
        archive_objects={"spot-ohlcv/v1/archive.gz": b"archive"},
    )
    key = "personal-spot-backups/2026/10/04/daily-1.zip"

    async def check() -> None:
        digest = await publish_backup_bundle(store, object_key=key, bundle_bytes=bundle)
        assert digest == verify_backup_bundle(bundle).bundle_sha256
        restored = await load_verified_backup(store, object_key=key)
        assert restored.database_dump == b"dump"
        assert restored.archive_objects["spot-ohlcv/v1/archive.gz"] == b"archive"

    asyncio.run(check())


def test_publish_refuses_immutable_key_conflict() -> None:
    store = MemoryObjectStore()
    first = build_backup_bundle(
        backup_id="daily-1",
        created_at=datetime(2026, 10, 4, tzinfo=UTC),
        database_dump=b"first",
        archive_objects={},
    )
    second = build_backup_bundle(
        backup_id="daily-1",
        created_at=datetime(2026, 10, 4, tzinfo=UTC),
        database_dump=b"second",
        archive_objects={},
    )

    async def check() -> None:
        await publish_backup_bundle(
            store, object_key="backup/daily-1.zip", bundle_bytes=first
        )
        with pytest.raises(BackupBundleError, match="publication or read-back"):
            await publish_backup_bundle(
                store, object_key="backup/daily-1.zip", bundle_bytes=second
            )

    asyncio.run(check())
