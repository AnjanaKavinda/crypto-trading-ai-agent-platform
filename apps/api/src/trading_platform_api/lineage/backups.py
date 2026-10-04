"""Bounded, integrity-checked backup bundles for personal Spot lineage.

Capture of PostgreSQL and enumeration of cold objects are intentionally owned
by the caller. This module packages those already captured bytes, publishes an
immutable bundle, and verifies it before a restore caller can use its contents.
"""

from __future__ import annotations

import hashlib
import io
import json
import re
import zipfile
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol


class BackupBundleError(ValueError):
    """A backup bundle is invalid, over budget, or failed verification."""


@dataclass(frozen=True)
class BackupLimits:
    """Hard byte bounds applied before any backup object is published."""

    max_bundle_bytes: int = 64 * 1024 * 1024

    def __post_init__(self) -> None:
        if type(self.max_bundle_bytes) is not int or self.max_bundle_bytes <= 0:
            raise BackupBundleError("max_bundle_bytes must be a positive integer.")


@dataclass(frozen=True)
class VerifiedBackup:
    backup_id: str
    created_at: datetime
    database_dump: bytes
    archive_objects: Mapping[str, bytes]
    bundle_sha256: str


class BackupObjectStore(Protocol):
    async def put_if_absent(self, key: str, value: bytes) -> None: ...

    async def get(self, key: str) -> bytes: ...


_BACKUP_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$")
_BUNDLE_VERSION = 1
_MANIFEST_NAME = "manifest.json"
_DATABASE_NAME = "database.dump"
_ARCHIVE_PREFIX = "archive/"


def build_backup_bundle(
    *,
    backup_id: str,
    created_at: datetime,
    database_dump: bytes,
    archive_objects: Mapping[str, bytes],
    limits: BackupLimits = BackupLimits(),
) -> bytes:
    """Build a bounded deterministic ZIP bundle with checksummed members."""

    _validate_backup_id(backup_id)
    if created_at.tzinfo is None or created_at.utcoffset() is None:
        raise BackupBundleError("created_at must include a timezone.")
    created_at = created_at.astimezone(UTC)
    if type(database_dump) is not bytes or not database_dump:
        raise BackupBundleError("database_dump must be nonempty bytes.")
    if not isinstance(archive_objects, Mapping):
        raise BackupBundleError("archive_objects must be a mapping.")

    entries: list[tuple[str, bytes]] = [(_DATABASE_NAME, database_dump)]
    manifest_archives: list[dict[str, object]] = []
    for index, (key, payload) in enumerate(sorted(archive_objects.items())):
        _validate_object_key(key)
        if type(payload) is not bytes or not payload:
            raise BackupBundleError("archive object payloads must be nonempty bytes.")
        member_name = f"{_ARCHIVE_PREFIX}{index:08d}"
        entries.append((member_name, payload))
        manifest_archives.append(_member_record(key, member_name, payload))

    manifest = {
        "archive_objects": manifest_archives,
        "backup_id": backup_id,
        "created_at": created_at.isoformat(),
        "database": _member_record("database", _DATABASE_NAME, database_dump),
        "format": "personal-spot-lineage-backup",
        "version": _BUNDLE_VERSION,
    }
    manifest_bytes = json.dumps(
        manifest, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("ascii")
    entries.append((_MANIFEST_NAME, manifest_bytes))

    stream = io.BytesIO()
    with zipfile.ZipFile(stream, mode="w", compression=zipfile.ZIP_STORED) as bundle:
        for name, payload in entries:
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_STORED
            info.external_attr = 0o600 << 16
            bundle.writestr(info, payload)
            if stream.tell() > limits.max_bundle_bytes:
                raise BackupBundleError("Backup exceeds the configured byte limit.")
    result = stream.getvalue()
    if len(result) > limits.max_bundle_bytes:
        raise BackupBundleError("Backup exceeds the configured byte limit.")
    return result


def verify_backup_bundle(
    bundle_bytes: bytes, *, limits: BackupLimits = BackupLimits()
) -> VerifiedBackup:
    """Validate the complete bundle before exposing any restored payload."""

    if type(bundle_bytes) is not bytes or not bundle_bytes:
        raise BackupBundleError("Backup bundle must be nonempty bytes.")
    if len(bundle_bytes) > limits.max_bundle_bytes:
        raise BackupBundleError("Backup exceeds the configured byte limit.")
    try:
        with zipfile.ZipFile(io.BytesIO(bundle_bytes), mode="r") as bundle:
            infos = bundle.infolist()
            names = [entry.filename for entry in infos]
            if len(names) != len(set(names)) or _MANIFEST_NAME not in names:
                raise BackupBundleError("Backup has duplicate members or no manifest.")
            if any(
                entry.is_dir()
                or entry.flag_bits & 0x1
                or entry.file_size > limits.max_bundle_bytes
                for entry in infos
            ):
                raise BackupBundleError(
                    "Backup contains an unsafe or oversized member."
                )
            manifest = json.loads(bundle.read(_MANIFEST_NAME))
            _validate_manifest(manifest, names)
            database = _read_verified_member(bundle, manifest["database"])
            archives: dict[str, bytes] = {}
            for item in manifest["archive_objects"]:
                key = item["key"]
                _validate_object_key(key)
                if key in archives:
                    raise BackupBundleError("Backup contains duplicate archive keys.")
                archives[key] = _read_verified_member(bundle, item)
    except (zipfile.BadZipFile, KeyError, TypeError, json.JSONDecodeError) as exc:
        raise BackupBundleError("Backup bundle is malformed.") from exc

    try:
        backup_time = datetime.fromisoformat(manifest["created_at"])
    except (ValueError, TypeError) as exc:
        raise BackupBundleError("Backup timestamp is invalid.") from exc
    if backup_time.tzinfo is None or backup_time.utcoffset() is None:
        raise BackupBundleError("Backup timestamp has no timezone.")
    return VerifiedBackup(
        backup_id=manifest["backup_id"],
        created_at=backup_time.astimezone(UTC),
        database_dump=database,
        archive_objects=archives,
        bundle_sha256=hashlib.sha256(bundle_bytes).hexdigest(),
    )


async def publish_backup_bundle(
    store: BackupObjectStore,
    *,
    object_key: str,
    bundle_bytes: bytes,
    limits: BackupLimits = BackupLimits(),
) -> str:
    """Publish once and require a full read-back verification before success."""

    try:
        _validate_object_key(object_key)
    except BackupBundleError:
        raise
    except Exception as exc:
        raise BackupBundleError("Backup object key is invalid.") from exc
    verified = verify_backup_bundle(bundle_bytes, limits=limits)
    try:
        await store.put_if_absent(object_key, bundle_bytes)
        read_back = await store.get(object_key)
    except Exception as exc:
        raise BackupBundleError("Backup publication or read-back failed.") from exc
    read_verified = verify_backup_bundle(read_back, limits=limits)
    if read_verified.bundle_sha256 != verified.bundle_sha256:
        raise BackupBundleError("Published backup failed read-back verification.")
    return verified.bundle_sha256


async def load_verified_backup(
    store: BackupObjectStore,
    *,
    object_key: str,
    limits: BackupLimits = BackupLimits(),
) -> VerifiedBackup:
    """Load a backup and validate every member before returning restore bytes."""

    try:
        _validate_object_key(object_key)
        payload = await store.get(object_key)
    except BackupBundleError:
        raise
    except Exception as exc:
        raise BackupBundleError("Backup object is unavailable.") from exc
    return verify_backup_bundle(payload, limits=limits)


def _member_record(key: str, name: str, payload: bytes) -> dict[str, object]:
    return {
        "key": key,
        "name": name,
        "sha256": hashlib.sha256(payload).hexdigest(),
        "size": len(payload),
    }


def _validate_backup_id(value: object) -> None:
    if type(value) is not str or not _BACKUP_ID.fullmatch(value):
        raise BackupBundleError("backup_id is invalid.")


def _validate_object_key(key: object) -> None:
    if (
        type(key) is not str
        or not key
        or key.startswith("/")
        or "\\" in key
        or "\x00" in key
        or any(part in ("", ".", "..") for part in key.split("/"))
    ):
        raise BackupBundleError("archive object key is invalid.")


def _validate_manifest(manifest: object, names: list[str]) -> None:
    expected = {
        "archive_objects",
        "backup_id",
        "created_at",
        "database",
        "format",
        "version",
    }
    if type(manifest) is not dict or set(manifest) != expected:
        raise BackupBundleError("Backup manifest fields are invalid.")
    if (
        manifest["format"] != "personal-spot-lineage-backup"
        or manifest["version"] != _BUNDLE_VERSION
    ):
        raise BackupBundleError("Backup format version is unsupported.")
    _validate_backup_id(manifest["backup_id"])
    if type(manifest["created_at"]) is not str:
        raise BackupBundleError("Backup timestamp is invalid.")
    archives = manifest["archive_objects"]
    if type(archives) is not list:
        raise BackupBundleError("Backup archive manifest is invalid.")
    records = [manifest["database"], *archives]
    if any(
        type(record) is not dict or set(record) != {"key", "name", "sha256", "size"}
        for record in records
    ):
        raise BackupBundleError("Backup member manifest is invalid.")
    expected_names = {_MANIFEST_NAME}
    for record in records:
        if (
            type(record["name"]) is not str
            or type(record["size"]) is not int
            or record["size"] <= 0
            or type(record["sha256"]) is not str
            or not re.fullmatch(r"[0-9a-f]{64}", record["sha256"])
        ):
            raise BackupBundleError("Backup member metadata is invalid.")
        expected_names.add(record["name"])
    if manifest["database"]["name"] != _DATABASE_NAME:
        raise BackupBundleError("Backup database member is invalid.")
    archive_names = [entry["name"] for entry in archives]
    if len(archive_names) != len(set(archive_names)) or any(
        not name.startswith(_ARCHIVE_PREFIX) for name in archive_names
    ):
        raise BackupBundleError("Backup archive member names are invalid.")
    if set(names) != expected_names:
        raise BackupBundleError("Backup contains unlisted or missing members.")


def _read_verified_member(
    bundle: zipfile.ZipFile, record: Mapping[str, object]
) -> bytes:
    try:
        payload = bundle.read(record["name"])
    except (KeyError, OSError, zipfile.BadZipFile) as exc:
        raise BackupBundleError("Backup member could not be read.") from exc
    if (
        len(payload) != record["size"]
        or hashlib.sha256(payload).hexdigest() != record["sha256"]
    ):
        raise BackupBundleError("Backup member failed size or digest verification.")
    return payload
