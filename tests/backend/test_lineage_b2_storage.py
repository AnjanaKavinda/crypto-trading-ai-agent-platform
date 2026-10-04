import asyncio
import base64
import io
from collections.abc import Mapping
from typing import Any

import pytest
from trading_platform_api.lineage.archive_storage import (
    ArchiveStorageError,
    B2S3Settings,
    BackblazeB2ObjectStore,
    ClientSideEncryption,
)


class FakeS3Error(Exception):
    def __init__(self, status: int) -> None:
        self.response = {
            "Error": {"Code": str(status)},
            "ResponseMetadata": {"HTTPStatusCode": status},
        }


class FakeB2Client:
    def __init__(self, *, versioning: str = "Enabled") -> None:
        self.versioning = versioning
        self.objects: dict[str, list[bytes]] = {}
        self.put_calls: list[str] = []

    def get_bucket_versioning(self, *, Bucket: str) -> Mapping[str, Any]:
        assert Bucket == "test-archive"
        return {"Status": self.versioning}

    def get_object(self, *, Bucket: str, Key: str) -> Mapping[str, Any]:
        assert Bucket == "test-archive"
        versions = self.objects.get(Key)
        if not versions:
            raise FakeS3Error(404)
        return {"Body": io.BytesIO(versions[-1])}

    def put_object(
        self, *, Bucket: str, Key: str, Body: bytes, ContentType: str
    ) -> Mapping[str, Any]:
        assert Bucket == "test-archive"
        assert ContentType == "application/octet-stream"
        self.put_calls.append(Key)
        self.objects.setdefault(Key, []).append(Body)
        return {"VersionId": str(len(self.objects[Key]))}


def encryption(key_id: str = "key-v1") -> ClientSideEncryption:
    return ClientSideEncryption(active_key_id=key_id, keys={key_id: b"k" * 32})


@pytest.fixture(autouse=True)
def run_blocking_adapter_calls_inline(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep adapter tests deterministic in runners that disable worker threads."""

    async def run_inline(function: Any, /, *args: Any, **kwargs: Any) -> Any:
        return function(*args, **kwargs)

    monkeypatch.setattr(asyncio, "to_thread", run_inline)


def test_client_encryption_authenticates_bytes_and_object_key() -> None:
    cipher = encryption()
    encrypted = cipher.encrypt("archive/object", b"canonical archive bytes")

    assert b"canonical archive bytes" not in encrypted
    assert cipher.decrypt("archive/object", encrypted) == b"canonical archive bytes"
    with pytest.raises(ArchiveStorageError, match="authentication"):
        cipher.decrypt("archive/other", encrypted)
    tampered = encrypted[:-1] + bytes((encrypted[-1] ^ 1,))
    with pytest.raises(ArchiveStorageError, match="authentication"):
        cipher.decrypt("archive/object", tampered)


def test_client_encryption_keyring_supports_old_keys_after_rotation() -> None:
    old = encryption("key-v1")
    encrypted = old.encrypt("archive/object", b"payload")
    rotated = ClientSideEncryption(
        active_key_id="key-v2",
        keys={"key-v1": b"k" * 32, "key-v2": b"n" * 32},
    )

    assert rotated.decrypt("archive/object", encrypted) == b"payload"
    assert (
        rotated.decrypt("archive/new", rotated.encrypt("archive/new", b"new payload"))
        == b"new payload"
    )


def test_client_encryption_rejects_invalid_environment_keyring() -> None:
    with pytest.raises(ArchiveStorageError, match="keyring"):
        ClientSideEncryption.from_environment(
            {
                "TRADING_PLATFORM_B2_ENCRYPTION_ACTIVE_KEY_ID": "key-v1",
                "TRADING_PLATFORM_B2_ENCRYPTION_KEYS_JSON": '{"key-v1":"not-base64"}',
            }
        )

    key = base64.b64encode(b"k" * 32).decode("ascii")
    parsed = ClientSideEncryption.from_environment(
        {
            "TRADING_PLATFORM_B2_ENCRYPTION_ACTIVE_KEY_ID": "key-v1",
            "TRADING_PLATFORM_B2_ENCRYPTION_KEYS_JSON": f'{{"key-v1":"{key}"}}',
        }
    )
    assert (
        parsed.decrypt("archive/object", parsed.encrypt("archive/object", b"ok"))
        == b"ok"
    )


def test_b2_settings_require_https_and_region_matched_b2_endpoint() -> None:
    values = {
        "TRADING_PLATFORM_B2_ENDPOINT_URL": "https://s3.us-west-004.backblazeb2.com",
        "TRADING_PLATFORM_B2_REGION": "us-west-004",
        "TRADING_PLATFORM_B2_BUCKET": "spot-archive",
        "TRADING_PLATFORM_B2_APPLICATION_KEY_ID": "external-key-id",
        "TRADING_PLATFORM_B2_APPLICATION_KEY": "external-secret",
    }
    assert B2S3Settings.from_environment(values).bucket == "spot-archive"

    values["TRADING_PLATFORM_B2_ENDPOINT_URL"] = "http://s3.us-west-004.backblazeb2.com"
    with pytest.raises(ArchiveStorageError, match="settings"):
        B2S3Settings.from_environment(values)


def test_b2_storage_encrypts_uploads_and_verifies_idempotent_readback() -> None:
    client = FakeB2Client()
    store = BackblazeB2ObjectStore(client, "test-archive", encryption())
    key = (
        "spot-ohlcv/v1/date=2026-01-01/venue=0123456789abcdef/instrument=fedcba9876543210/"
        + "a" * 64
        + ".jsonl.gz"
    )
    value = b"compressed archive bytes"

    async def check() -> None:
        await store.put_if_absent(key, value)
        assert await store.get(key) == value
        await store.put_if_absent(key, value)

    asyncio.run(check())
    assert len(client.put_calls) == 1
    assert client.objects[key][0] != value


def test_b2_storage_fails_on_existing_conflict_without_overwriting() -> None:
    client = FakeB2Client()
    store = BackblazeB2ObjectStore(client, "test-archive", encryption())
    key = (
        "spot-ohlcv/v1/date=2026-01-01/venue=0123456789abcdef/instrument=fedcba9876543210/"
        + "a" * 64
        + ".jsonl.gz"
    )

    async def check() -> None:
        await store.put_if_absent(key, b"first content")
        with pytest.raises(ArchiveStorageError, match="different bytes"):
            await store.put_if_absent(key, b"conflicting content")

    asyncio.run(check())
    assert len(client.put_calls) == 1


def test_b2_storage_refuses_writes_without_enabled_bucket_versioning() -> None:
    client = FakeB2Client(versioning="Suspended")
    store = BackblazeB2ObjectStore(client, "test-archive", encryption())
    key = (
        "spot-ohlcv/v1/date=2026-01-01/venue=0123456789abcdef/instrument=fedcba9876543210/"
        + "a" * 64
        + ".jsonl.gz"
    )

    async def check() -> None:
        with pytest.raises(ArchiveStorageError, match="versioning must be enabled"):
            await store.put_if_absent(key, b"payload")

    asyncio.run(check())
    assert client.put_calls == []


def test_b2_storage_distinguishes_missing_from_access_denied() -> None:
    client = FakeB2Client()
    store = BackblazeB2ObjectStore(client, "test-archive", encryption())
    key = (
        "spot-ohlcv/v1/date=2026-01-01/venue=0123456789abcdef/instrument=fedcba9876543210/"
        + "a" * 64
        + ".jsonl.gz"
    )

    async def check() -> None:
        with pytest.raises(ArchiveStorageError, match="missing"):
            await store.get(key)

        def denied(*, Bucket: str, Key: str) -> Mapping[str, Any]:
            raise FakeS3Error(403)

        client.get_object = denied  # type: ignore[method-assign]
        with pytest.raises(ArchiveStorageError, match="read failed"):
            await store.get(key)

    asyncio.run(check())
