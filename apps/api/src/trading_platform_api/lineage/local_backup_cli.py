"""Local-only pg_dump/pg_restore command for the Phase 1 lineage backup."""

from __future__ import annotations

import argparse
import asyncio
import configparser
import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import async_sessionmaker

from trading_platform_api.lineage.archive_storage import (
    EncryptedObjectStore,
    LocalFilesystemObjectStore,
)
from trading_platform_api.lineage.backups import BackupLimits
from trading_platform_api.lineage.codec import LineageError
from trading_platform_api.lineage.local_backups import (
    LocalBackupError,
    create_local_backup,
    restore_local_backup,
)
from trading_platform_api.lineage.payload_retention import (
    remove_archived_hot_payloads,
)
from trading_platform_api.persistence.config import load_database_settings
from trading_platform_api.persistence.session import (
    create_async_engine_instance,
    create_async_session_factory,
)

_SERVICE_NAME = re.compile(r"^[A-Za-z0-9_.-]{1,63}$")
_RESTORE_PREFIX = "trading_restore_"


def _local_roots() -> tuple[Path, Path]:
    try:
        archive = Path(os.environ["TRADING_PLATFORM_LOCAL_ARCHIVE_ROOT"]).expanduser()
        backup = Path(os.environ["TRADING_PLATFORM_LOCAL_BACKUP_ROOT"]).expanduser()
    except KeyError as exc:
        raise LocalBackupError("Local archive and backup roots are required.") from exc
    archive = archive.resolve()
    backup = backup.resolve()
    if archive == backup or archive in backup.parents or backup in archive.parents:
        raise LocalBackupError(
            "Local archive and backup roots must be separate directories."
        )
    return archive, backup


def _service_config(service_name: str) -> configparser.SectionProxy:
    if not _SERVICE_NAME.fullmatch(service_name):
        raise LocalBackupError("PostgreSQL service name is invalid.")
    service_file_value = os.environ.get("TRADING_PLATFORM_PG_SERVICE_FILE")
    if not service_file_value:
        raise LocalBackupError("A protected PostgreSQL service file is required.")
    service_file = Path(service_file_value).expanduser()
    if service_file.is_symlink() or not service_file.is_file():
        raise LocalBackupError("PostgreSQL service file is unavailable.")
    if service_file.stat().st_mode & 0o777 != 0o600:
        raise LocalBackupError("PostgreSQL service file permissions must be 0600.")
    parser = configparser.ConfigParser(interpolation=None)
    try:
        parser.read(service_file)
        section = parser[service_name]
    except (OSError, KeyError, configparser.Error) as exc:
        raise LocalBackupError("PostgreSQL service configuration is invalid.") from exc
    host = section.get("host", "")
    if host not in {"localhost", "127.0.0.1", "::1"}:
        raise LocalBackupError("PostgreSQL service must use a local loopback host.")
    return section


def _validate_dump_service() -> str:
    service_name = os.environ.get("TRADING_PLATFORM_PG_DUMP_SERVICE", "")
    section = _service_config(service_name)
    settings = load_database_settings()
    database_url = make_url(settings.database_url)
    if database_url.host not in {"localhost", "127.0.0.1", "::1"}:
        raise LocalBackupError("DATABASE_URL must point to local PostgreSQL.")
    if section.get("dbname") != database_url.database:
        raise LocalBackupError(
            "pg_dump service database must match DATABASE_URL's database."
        )
    service_port = section.getint("port", fallback=5432)
    if service_port != (database_url.port or 5432):
        raise LocalBackupError("pg_dump service port must match DATABASE_URL's port.")
    if database_url.username and section.get("user") != database_url.username:
        raise LocalBackupError("pg_dump service user must match DATABASE_URL's user.")
    return service_name


def _validate_restore_service() -> str:
    service_name = os.environ.get("TRADING_PLATFORM_PG_RESTORE_SERVICE", "")
    section = _service_config(service_name)
    if not service_name.startswith(_RESTORE_PREFIX) or not section.get(
        "dbname", ""
    ).startswith(_RESTORE_PREFIX):
        raise LocalBackupError(
            "Restore is allowed only to a local disposable trading_restore_* database."
        )
    source_url = make_url(load_database_settings().database_url)
    source_database = source_url.database
    if source_url.host not in {"localhost", "127.0.0.1", "::1"}:
        raise LocalBackupError(
            "Restore source settings must point to local PostgreSQL."
        )
    if section.get("dbname") == source_database:
        raise LocalBackupError("Restore target must differ from the source database.")
    if section.getint("port", fallback=5432) != (source_url.port or 5432):
        raise LocalBackupError("Restore service port must match the local source port.")
    if source_url.username and section.get("user") != source_url.username:
        raise LocalBackupError("Restore service user must match the local source user.")
    return service_name


async def _ensure_empty_restore_target() -> None:
    """Refuse to restore into any database containing user relations."""
    service_name = os.environ.get("TRADING_PLATFORM_PG_RESTORE_SERVICE", "")
    section = _service_config(service_name)
    settings = load_database_settings()
    target_url = make_url(settings.database_url).set(database=section["dbname"])
    target_settings = replace(
        settings,
        database_url=target_url.render_as_string(hide_password=False),
    )
    engine = create_async_engine_instance(target_settings)
    try:
        async with engine.connect() as connection:
            relation_count = await connection.scalar(
                text(
                    "SELECT count(*) FROM pg_class AS relation "
                    "JOIN pg_namespace AS namespace "
                    "ON namespace.oid = relation.relnamespace "
                    "WHERE relation.relkind IN ('r', 'p', 'v', 'm', 'S', 'f') "
                    "AND namespace.nspname <> 'information_schema' "
                    "AND namespace.nspname !~ '^pg_'"
                )
            )
    finally:
        await engine.dispose()
    if relation_count:
        raise LocalBackupError(
            "Restore target must be empty; no tables or other user relations may exist."
        )


def _run_pg_dump(service_name: str) -> bytes:
    binary = shutil.which("pg_dump")
    if binary is None:
        raise LocalBackupError("pg_dump is required for local backup capture.")
    with tempfile.TemporaryDirectory(prefix="trading-backup-") as directory:
        dump_path = Path(directory) / "database.dump"
        environment = os.environ.copy()
        environment["PGSERVICEFILE"] = os.environ["TRADING_PLATFORM_PG_SERVICE_FILE"]
        result = subprocess.run(
            [
                binary,
                "--no-password",
                "--format=custom",
                "--no-owner",
                "--no-privileges",
                f"--dbname=service={service_name}",
                f"--file={dump_path}",
            ],
            env=environment,
            capture_output=True,
            check=False,
            timeout=300,
        )
        if result.returncode != 0:
            raise LocalBackupError("pg_dump failed; no backup was published.")
        payload = dump_path.read_bytes()
    if not payload:
        raise LocalBackupError("pg_dump produced an empty database dump.")
    return payload


def _restore_with_pg_restore(service_name: str, dump: bytes) -> None:
    binary = shutil.which("pg_restore")
    if binary is None:
        raise LocalBackupError("pg_restore is required for local restoration.")
    with tempfile.TemporaryDirectory(prefix="trading-restore-") as directory:
        dump_path = Path(directory) / "database.dump"
        dump_path.write_bytes(dump)
        os.chmod(dump_path, 0o600)
        environment = os.environ.copy()
        environment["PGSERVICEFILE"] = os.environ["TRADING_PLATFORM_PG_SERVICE_FILE"]
        result = subprocess.run(
            [
                binary,
                "--no-password",
                "--exit-on-error",
                "--no-owner",
                "--no-privileges",
                f"--dbname=service={service_name}",
                str(dump_path),
            ],
            env=environment,
            capture_output=True,
            check=False,
            timeout=600,
        )
        if result.returncode != 0:
            raise LocalBackupError(
                "pg_restore failed in the disposable database; inspect local logs."
            )


async def _backup() -> tuple[str, str]:
    archive_root, backup_root = _local_roots()
    service = _validate_dump_service()
    database_dump = _run_pg_dump(service)
    encryption_store = EncryptedObjectStore.from_environment(backup_root)
    archive_store = LocalFilesystemObjectStore(archive_root)
    now = datetime.now(UTC)
    backup_id = now.strftime("daily-%Y%m%dT%H%M%SZ")
    settings = load_database_settings()
    engine = create_async_engine_instance(settings)
    try:
        session_factory = create_async_session_factory(engine)
        async with session_factory() as session:
            digest = await create_local_backup(
                session,
                archive_store,
                encryption_store,
                backup_id=backup_id,
                created_at=now,
                database_dump=database_dump,
                limits=BackupLimits(),
            )
    finally:
        await engine.dispose()
    return f"daily/{now:%Y/%m/%d}/{backup_id}.zip", digest


async def _restore(object_key: str) -> str:
    archive_root, backup_root = _local_roots()
    service = _validate_restore_service()
    await _ensure_empty_restore_target()
    archive_store = LocalFilesystemObjectStore(archive_root)
    encryption_store = EncryptedObjectStore.from_environment(backup_root)

    async def restore_database(payload: bytes) -> None:
        _restore_with_pg_restore(service, payload)

    return await restore_local_backup(
        encryption_store,
        archive_store,
        object_key=object_key,
        restore_database=restore_database,
        limits=BackupLimits(),
    )


async def _remove_hot_payloads_from_database(
    object_key: str,
    database_url: str | None = None,
    *,
    expected_record_ids: tuple[str, ...] | None = None,
    expected_removed_record_ids: tuple[str, ...] | None = None,
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    archive_root, _ = _local_roots()
    settings = load_database_settings()
    if database_url is not None:
        settings = replace(settings, database_url=database_url)
    engine = create_async_engine_instance(settings)
    try:
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        async with sessions.begin() as session:
            removed = await remove_archived_hot_payloads(
                session,
                LocalFilesystemObjectStore(archive_root),
                object_key,
                expected_record_ids=expected_record_ids,
                expected_removed_record_ids=expected_removed_record_ids,
            )
        return (
            tuple(key.record_id for key in removed.members),
            tuple(key.record_id for key in removed.removed),
        )
    finally:
        await engine.dispose()


async def _prune_hot(object_key: str) -> tuple[str, str, int]:
    """Back up, restore, validate, then remove one cold object from source."""
    _local_roots()
    _validate_dump_service()
    _validate_restore_service()
    await _ensure_empty_restore_target()

    backup_key, backup_digest = await _backup()
    restored_digest = await _restore(backup_key)
    if restored_digest != backup_digest:
        raise LocalBackupError("Disposable restore digest differs from the new backup.")

    # The restored copy must pass all removal and retained-reference checks
    # before the same transaction is allowed to affect the source database.
    restore_service = os.environ["TRADING_PLATFORM_PG_RESTORE_SERVICE"]
    restore_database = _service_config(restore_service)["dbname"]
    restore_url = make_url(load_database_settings().database_url).set(
        database=restore_database
    )
    restored_members, restored_removed = await _remove_hot_payloads_from_database(
        object_key, restore_url.render_as_string(hide_password=False)
    )
    source_members, source_removed = await _remove_hot_payloads_from_database(
        object_key,
        expected_record_ids=restored_members,
        expected_removed_record_ids=restored_removed,
    )
    if source_members != restored_members or source_removed != restored_removed:
        raise LocalBackupError("Source removal differs from the validated restore.")
    return backup_key, backup_digest, len(source_removed)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Create or restore a local encrypted lineage backup."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("backup", help="capture PostgreSQL and referenced archives")
    restore_parser = subparsers.add_parser(
        "restore", help="restore into a disposable local PostgreSQL database"
    )
    restore_parser.add_argument("object_key")
    prune_parser = subparsers.add_parser(
        "prune-hot",
        help="manually back up, restore-check, then remove one eligible cold batch",
    )
    prune_parser.add_argument("object_key")
    prune_parser.add_argument(
        "--confirm",
        action="store_true",
        required=True,
        help="confirm this one-time, operator-triggered source payload removal",
    )
    arguments = parser.parse_args()
    try:
        if arguments.command == "backup":
            object_key, digest = asyncio.run(_backup())
            print(f"Backup verified: key={object_key} sha256={digest}")
        elif arguments.command == "restore":
            digest = asyncio.run(_restore(arguments.object_key))
            print(f"Restore completed: sha256={digest}")
        else:
            object_key, digest, count = asyncio.run(_prune_hot(arguments.object_key))
            print(
                f"Hot payload removal verified: backup={object_key} "
                f"sha256={digest} removed={count}"
            )
    except (
        LineageError,
        LocalBackupError,
        OSError,
        SQLAlchemyError,
        subprocess.SubprocessError,
    ) as exc:
        parser.exit(2, f"local backup failed: {exc}\n")


if __name__ == "__main__":
    main()
