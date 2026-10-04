"""Local backup orchestration for PostgreSQL dumps and referenced cold objects.

The caller captures the database with pg_dump. This module gathers every
archive object still referenced by lineage metadata, verifies it, and stores
the complete backup bundle in an immutable local target.
"""

from __future__ import annotations

import hashlib
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Protocol

from sqlalchemy import select

from trading_platform_api.lineage.backups import (
    BackupLimits,
    build_backup_bundle,
    load_verified_backup,
    publish_backup_bundle,
)
from trading_platform_api.lineage.tables import archive_members, archive_objects


class LocalBackupError(ValueError):
    """A local backup is incomplete or failed integrity verification."""


class LocalObjectStore(Protocol):
    async def put_if_absent(self, key: str, value: bytes) -> None: ...

    async def get(self, key: str) -> bytes: ...


async def collect_referenced_archive_objects(
    session: object,
    archive_store: LocalObjectStore,
) -> dict[str, bytes]:
    """Read and verify each archive object and manifest referenced in Postgres."""

    statement = (
        select(
            archive_objects.object_key,
            archive_objects.compressed_sha256,
            archive_objects.manifest_key,
            archive_objects.manifest_sha256,
        )
        .join(
            archive_members,
            archive_members.c.object_key == archive_objects.c.object_key,
        )
        .distinct()
        .order_by(archive_objects.c.object_key)
    )
    execute = getattr(session, "execute", None)
    if not callable(execute):
        raise LocalBackupError("An async database session is required.")
    result = await execute(statement)
    rows = result.all()
    objects: dict[str, bytes] = {}
    for row in rows:
        object_key, object_digest, manifest_key, manifest_digest = row
        for key, expected_digest in (
            (object_key, object_digest),
            (manifest_key, manifest_digest),
        ):
            if key in objects:
                continue
            try:
                payload = await archive_store.get(key)
            except Exception as exc:
                raise LocalBackupError(
                    "A referenced local archive object is unavailable."
                ) from exc
            if hashlib.sha256(payload).hexdigest() != expected_digest:
                raise LocalBackupError(
                    "A referenced local archive object failed digest verification."
                )
            objects[key] = payload
    return objects


async def create_local_backup(
    session: object,
    archive_store: LocalObjectStore,
    backup_store: LocalObjectStore,
    *,
    backup_id: str,
    created_at: datetime,
    database_dump: bytes,
    limits: BackupLimits = BackupLimits(),
) -> str:
    """Create a bounded backup containing the dump and all referenced archives."""

    if created_at.tzinfo is None or created_at.utcoffset() is None:
        raise LocalBackupError("created_at must include a timezone.")
    objects = await collect_referenced_archive_objects(session, archive_store)
    bundle = build_backup_bundle(
        backup_id=backup_id,
        created_at=created_at,
        database_dump=database_dump,
        archive_objects=objects,
        limits=limits,
    )
    moment = created_at.astimezone(UTC)
    object_key = f"daily/{moment:%Y/%m/%d}/{backup_id}.zip"
    return await publish_backup_bundle(
        backup_store,
        object_key=object_key,
        bundle_bytes=bundle,
        limits=limits,
    )


async def restore_local_backup(
    backup_store: LocalObjectStore,
    archive_store: LocalObjectStore,
    *,
    object_key: str,
    restore_database: Callable[[bytes], Awaitable[None]],
    limits: BackupLimits = BackupLimits(),
) -> str:
    """Verify, republish archives, then pass the dump to a restore callback.

    The callback must restore into a disposable local PostgreSQL database. This
    helper intentionally never chooses, drops, or connects to a database.
    """

    backup = await load_verified_backup(
        backup_store, object_key=object_key, limits=limits
    )
    for key, payload in backup.archive_objects.items():
        await archive_store.put_if_absent(key, payload)
        if await archive_store.get(key) != payload:
            raise LocalBackupError("Restored archive object failed read-back check.")
    await restore_database(backup.database_dump)
    return backup.bundle_sha256
