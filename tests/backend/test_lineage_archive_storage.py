import base64
import json
from pathlib import Path

import pytest
from trading_platform_api.lineage.archive_storage import (
    ArchiveStorageError,
    EncryptedObjectStore,
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


def test_local_encrypted_store_encrypts_at_rest_and_reads_back(
    tmp_path: Path,
) -> None:
    async def check() -> None:
        import asyncio

        key = b"\x19" * 32
        environment = {
            "TRADING_PLATFORM_LOCAL_ENCRYPTION_ACTIVE_KEY_ID": "phase1",
            "TRADING_PLATFORM_LOCAL_ENCRYPTION_KEYS_JSON": json.dumps(
                {"phase1": base64.b64encode(key).decode("ascii")}
            ),
        }
        store = EncryptedObjectStore.from_environment(tmp_path, environment)
        plaintext = b"private backup payload"
        await store.put_if_absent("daily/backup.zip", plaintext)
        await store.put_if_absent("daily/backup.zip", plaintext)
        stored_bytes = (tmp_path / "daily" / "backup.zip").read_bytes()

        assert plaintext not in stored_bytes
        assert await store.get("daily/backup.zip") == plaintext

    import asyncio

    asyncio.run(check())
