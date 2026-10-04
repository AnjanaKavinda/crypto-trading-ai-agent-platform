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
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy.engine import make_url

from trading_platform_api.lineage.archive_storage import (
    EncryptedObjectStore,
    LocalFilesystemObjectStore,
)
from trading_platform_api.lineage.backups import BackupLimits
from trading_platform_api.lineage.local_backups import (
    LocalBackupError,
    create_local_backup,
    restore_local_backup,
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
    if service_file.stat().st_mode & 0o077:
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
        raise LocalBackupError(
            "pg_dump service port must match DATABASE_URL's port."
        )
    if database_url.username and section.get("user") != database_url.username:
        raise LocalBackupError(
            "pg_dump service user must match DATABASE_URL's user."
        )
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
    source_database = make_url(load_database_settings().database_url).database
    if section.get("dbname") == source_database:
        raise LocalBackupError("Restore target must differ from the source database.")
    return service_name


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
    arguments = parser.parse_args()
    try:
        if arguments.command == "backup":
            object_key, digest = asyncio.run(_backup())
            print(f"Backup verified: key={object_key} sha256={digest}")
        else:
            digest = asyncio.run(_restore(arguments.object_key))
            print(f"Restore completed: sha256={digest}")
    except (LocalBackupError, OSError, subprocess.SubprocessError) as exc:
        parser.exit(2, f"local backup failed: {exc}\n")


if __name__ == "__main__":
    main()
