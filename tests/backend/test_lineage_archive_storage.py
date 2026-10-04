from pathlib import Path

import pytest
from trading_platform_api.lineage.archive_storage import (
    ArchiveStorageError,
    LocalFilesystemObjectStore,
)


def test_local_archive_object_store_is_idempotent_and_never_overwrites(
    tmp_path: Path,
) -> None:
    async def check() -> None:
        store = LocalFilesystemObjectStore(tmp_path / "archive")
        await store.put_if_absent("market/day/object.bin", b"verified-payload")
        await store.put_if_absent("market/day/object.bin", b"verified-payload")
        assert await store.get("market/day/object.bin") == b"verified-payload"
        with pytest.raises(ArchiveStorageError, match="different bytes"):
            await store.put_if_absent("market/day/object.bin", b"replacement")

    import asyncio

    asyncio.run(check())


@pytest.mark.parametrize(
    "key", ["/absolute/object", "../escape", "a/../../escape", "a\\b"]
)
def test_local_archive_object_store_rejects_unsafe_keys(
    tmp_path: Path, key: str
) -> None:
    async def check() -> None:
        store = LocalFilesystemObjectStore(tmp_path / "archive")
        with pytest.raises(ArchiveStorageError, match="key"):
            await store.put_if_absent(key, b"payload")

    import asyncio

    asyncio.run(check())


def test_local_archive_object_store_rejects_symlinks_and_missing_objects(
    tmp_path: Path,
) -> None:
    async def check() -> None:
        root = tmp_path / "archive"
        store = LocalFilesystemObjectStore(root)
        with pytest.raises(ArchiveStorageError, match="missing"):
            await store.get("missing.bin")
        root.mkdir()
        outside = tmp_path / "outside"
        outside.mkdir()
        (root / "escape").symlink_to(outside, target_is_directory=True)
        with pytest.raises(ArchiveStorageError, match="symlink|escapes"):
            await store.put_if_absent("escape/payload.bin", b"payload")

    import asyncio

    asyncio.run(check())
