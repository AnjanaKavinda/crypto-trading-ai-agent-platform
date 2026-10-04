"""Minimal immutable-object storage port and local development implementation."""

from __future__ import annotations

import asyncio
import os
import tempfile
from pathlib import Path, PurePosixPath
from typing import Protocol


class ArchiveStorageError(OSError):
    """An archive object is missing, conflicting, or could not be verified."""


class ImmutableObjectStore(Protocol):
    async def put_if_absent(self, key: str, value: bytes) -> None: ...

    async def get(self, key: str) -> bytes: ...


class LocalFilesystemObjectStore:
    """Local-only immutable object store for development and integration tests.

    Production cold storage must use a separately configured object-store
    adapter with versioning, access controls, and tested backup/restore.
    """

    def __init__(self, root: Path):
        self._root = root.expanduser().resolve()

    def _path(self, key: str) -> Path:
        if type(key) is not str or not key or "\\" in key:
            raise ArchiveStorageError("Invalid archive object key.")
        relative = PurePosixPath(key)
        if relative.is_absolute() or any(
            part in ("", ".", "..") for part in relative.parts
        ):
            raise ArchiveStorageError("Invalid archive object key.")
        target = self._root.joinpath(*relative.parts)
        try:
            target.parent.resolve().relative_to(self._root)
        except ValueError as exc:
            raise ArchiveStorageError("Archive object path escapes its root.") from exc
        if target.is_symlink():
            raise ArchiveStorageError("Archive object path must not be a symlink.")
        return target

    async def put_if_absent(self, key: str, value: bytes) -> None:
        if type(value) is not bytes or not value:
            raise ArchiveStorageError("Archive object must be nonempty bytes.")
        await asyncio.to_thread(self._put_if_absent, key, value)

    def _put_if_absent(self, key: str, value: bytes) -> None:
        target = self._path(key)
        target.parent.mkdir(parents=True, exist_ok=True)
        target = self._path(key)
        temporary_name: str | None = None
        try:
            with tempfile.NamedTemporaryFile(dir=target.parent, delete=False) as temp:
                temporary_name = temp.name
                temp.write(value)
                temp.flush()
                os.fsync(temp.fileno())
            try:
                os.link(temporary_name, target)
            except FileExistsError:
                if target.read_bytes() != value:
                    raise ArchiveStorageError(
                        "Immutable archive key already contains different bytes."
                    )
        finally:
            if temporary_name is not None:
                Path(temporary_name).unlink(missing_ok=True)

    async def get(self, key: str) -> bytes:
        return await asyncio.to_thread(self._get, key)

    def _get(self, key: str) -> bytes:
        target = self._path(key)
        try:
            return target.read_bytes()
        except FileNotFoundError as exc:
            raise ArchiveStorageError("Archive object is missing.") from exc
