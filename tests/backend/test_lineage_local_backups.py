from __future__ import annotations

import asyncio
import hashlib
import sys
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from trading_platform_api.lineage import local_backup_cli
from trading_platform_api.lineage.backups import BackupBundleError, verify_backup_bundle
from trading_platform_api.lineage.local_backup_cli import (
    RestoreDrillCleanupError,
    _owned_restore_database,
    _restore_drill,
    _validate_restore_service,
    main,
)
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


def test_restore_cli_allows_only_loopback_disposable_service(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service_file = tmp_path / "pg_service.conf"
    service_file.write_text(
        "[trading_restore_test]\nhost=127.0.0.1\ndbname=trading_restore_test\n"
        "user=user\n"
    )
    service_file.chmod(0o600)
    monkeypatch.setenv("TRADING_PLATFORM_PG_SERVICE_FILE", str(service_file))
    monkeypatch.setenv("TRADING_PLATFORM_PG_RESTORE_SERVICE", "trading_restore_test")
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://user@localhost/source")

    assert _validate_restore_service() == "trading_restore_test"


def test_restore_cli_rejects_non_disposable_or_remote_service(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service_file = tmp_path / "pg_service.conf"
    service_file.write_text("[production]\nhost=example.com\ndbname=production\n")
    service_file.chmod(0o600)
    monkeypatch.setenv("TRADING_PLATFORM_PG_SERVICE_FILE", str(service_file))
    monkeypatch.setenv("TRADING_PLATFORM_PG_RESTORE_SERVICE", "production")

    with pytest.raises(LocalBackupError, match="local loopback"):
        _validate_restore_service()


def test_prune_hot_cli_requires_explicit_confirmation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sys, "argv", ["local_backup_cli", "prune-hot", "cold.gz"])
    with pytest.raises(SystemExit) as result:
        main()
    assert result.value.code == 2


def test_restore_drill_refuses_preexisting_target() -> None:
    async def check() -> None:
        section = {"dbname": "trading_restore_owned"}
        with (
            patch.object(
                local_backup_cli, "_validate_dump_service", return_value="source"
            ),
            patch.object(
                local_backup_cli,
                "_validate_restore_service",
                return_value="trading_restore_owned",
            ),
            patch.object(local_backup_cli, "_service_config", return_value=section),
            patch.object(local_backup_cli, "load_database_settings") as settings,
            patch.object(
                local_backup_cli,
                "_database_identity",
                new=AsyncMock(return_value=(True, None)),
            ),
            patch.object(local_backup_cli, "_run_database_utility") as utility,
        ):
            settings.return_value.database_url = (
                "postgresql+asyncpg://user@127.0.0.1/source"
            )
            with pytest.raises(LocalBackupError, match="already exists"):
                async with _owned_restore_database():
                    pass
        utility.assert_not_called()

    asyncio.run(check())


def test_restore_drill_creates_marks_and_removes_only_owned_target(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def check() -> None:
        target = "trading_restore_owned"
        marker = "trading-platform-restore-drill:" + "a" * 32
        section = {"dbname": target}
        monkeypatch.setenv("TRADING_PLATFORM_RESTORE_DRILL_ID", "a" * 32)
        with (
            patch.object(
                local_backup_cli, "_validate_dump_service", return_value="source"
            ),
            patch.object(
                local_backup_cli,
                "_validate_restore_service",
                return_value=target,
            ),
            patch.object(local_backup_cli, "_service_config", return_value=section),
            patch.object(local_backup_cli, "load_database_settings") as settings,
            patch.object(
                local_backup_cli,
                "_database_identity",
                new=AsyncMock(
                    side_effect=[
                        (False, None),
                        (True, marker),
                        (True, marker),
                        (False, None),
                    ]
                ),
            ),
            patch.object(local_backup_cli, "_mark_database", new=AsyncMock()) as mark,
            patch.object(local_backup_cli, "_run_database_utility") as utility,
        ):
            settings.return_value.database_url = (
                "postgresql+asyncpg://user@127.0.0.1/source"
            )
            async with _owned_restore_database() as observed:
                assert observed == target
        mark.assert_awaited_once_with(target, marker)
        assert utility.call_args_list[0].args == (
            "createdb",
            ["--maintenance-db=service=source", target],
        )
        assert utility.call_args_list[1].args == (
            "dropdb",
            ["--force", "--maintenance-db=service=source", target],
        )

    asyncio.run(check())


def test_restore_drill_cleanup_fails_closed_on_marker_mismatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def check() -> None:
        target = "trading_restore_owned"
        marker = "trading-platform-restore-drill:" + "a" * 32
        monkeypatch.setenv("TRADING_PLATFORM_RESTORE_DRILL_ID", "a" * 32)
        with (
            patch.object(
                local_backup_cli, "_validate_dump_service", return_value="source"
            ),
            patch.object(
                local_backup_cli, "_validate_restore_service", return_value=target
            ),
            patch.object(
                local_backup_cli, "_service_config", return_value={"dbname": target}
            ),
            patch.object(local_backup_cli, "load_database_settings") as settings,
            patch.object(
                local_backup_cli,
                "_database_identity",
                new=AsyncMock(
                    side_effect=[
                        (False, None),
                        (True, marker),
                        (True, "different-owner"),
                    ]
                ),
            ),
            patch.object(local_backup_cli, "_mark_database", new=AsyncMock()),
            patch.object(local_backup_cli, "_run_database_utility") as utility,
        ):
            settings.return_value.database_url = (
                "postgresql+asyncpg://user@127.0.0.1/source"
            )
            with pytest.raises(RestoreDrillCleanupError) as failure:
                async with _owned_restore_database():
                    pass
        assert failure.value.database == target
        assert utility.call_count == 1

    asyncio.run(check())


def test_restore_drill_reports_exact_target_when_drop_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def check() -> None:
        target = "trading_restore_owned"
        marker = "trading-platform-restore-drill:" + "a" * 32
        monkeypatch.setenv("TRADING_PLATFORM_RESTORE_DRILL_ID", "a" * 32)
        with (
            patch.object(
                local_backup_cli, "_validate_dump_service", return_value="source"
            ),
            patch.object(
                local_backup_cli, "_validate_restore_service", return_value=target
            ),
            patch.object(
                local_backup_cli, "_service_config", return_value={"dbname": target}
            ),
            patch.object(local_backup_cli, "load_database_settings") as settings,
            patch.object(
                local_backup_cli,
                "_database_identity",
                new=AsyncMock(
                    side_effect=[
                        (False, None),
                        (True, marker),
                        (True, marker),
                    ]
                ),
            ),
            patch.object(local_backup_cli, "_mark_database", new=AsyncMock()),
            patch.object(
                local_backup_cli,
                "_run_database_utility",
                side_effect=[None, LocalBackupError("private drop failure")],
            ),
        ):
            settings.return_value.database_url = (
                "postgresql+asyncpg://user@127.0.0.1/source"
            )
            with pytest.raises(RestoreDrillCleanupError) as failure:
                async with _owned_restore_database():
                    pass
        assert failure.value.database == target

    asyncio.run(check())


def test_restore_drill_verifies_lineage_before_owned_cleanup() -> None:
    async def check() -> None:
        events: list[str] = []

        @asynccontextmanager
        async def owned():
            events.append("created")
            yield "trading_restore_owned"
            events.append("cleaned")

        async def restore(_key: str) -> str:
            events.append("restored")
            return "b" * 64

        async def verify(database: str) -> int:
            assert database == "trading_restore_owned"
            events.append("resolved")
            return 3

        with (
            patch.object(local_backup_cli, "_owned_restore_database", owned),
            patch.object(local_backup_cli, "_restore", restore),
            patch.object(local_backup_cli, "_verify_restored_lineage", verify),
        ):
            result = await _restore_drill("verified.zip")
        assert result == ("b" * 64, "trading_restore_owned", 3)
        assert events == ["created", "restored", "resolved", "cleaned"]

    asyncio.run(check())
