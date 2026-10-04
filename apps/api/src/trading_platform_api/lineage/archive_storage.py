"""Minimal immutable-object storage port and local development implementation."""

from __future__ import annotations

import asyncio
import base64
import binascii
import importlib
import json
import os
import re
import secrets
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from types import MappingProxyType
from typing import Any, Protocol
from urllib.parse import urlsplit

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM


class ArchiveStorageError(OSError):
    """An archive object is missing, conflicting, or could not be verified."""


class ArchiveObjectMissing(ArchiveStorageError):
    """An archive object does not exist."""


class ImmutableObjectStore(Protocol):
    async def put_if_absent(self, key: str, value: bytes) -> None: ...

    async def get(self, key: str) -> bytes: ...


@dataclass(frozen=True)
class ClientSideEncryption:
    """AES-GCM envelope encryption with externally supplied key material."""

    active_key_id: str
    keys: Mapping[str, bytes] = field(repr=False)

    _MAGIC = b"TPB2ENC1"
    _NONCE_SIZE = 12
    _TAG_SIZE = 16
    _KEY_ID_RE = re.compile(r"^[A-Za-z0-9._-]{1,64}$")

    def __post_init__(self) -> None:
        copied = dict(self.keys)
        if (
            not self._KEY_ID_RE.fullmatch(self.active_key_id)
            or self.active_key_id not in copied
            or not copied
            or any(
                not self._KEY_ID_RE.fullmatch(key_id)
                or type(key) is not bytes
                or len(key) != 32
                for key_id, key in copied.items()
            )
        ):
            raise ArchiveStorageError("Invalid client-side encryption keyring.")
        object.__setattr__(self, "keys", MappingProxyType(copied))

    @classmethod
    def from_environment(
        cls,
        environ: Mapping[str, str] | None = None,
        *,
        prefix: str = "TRADING_PLATFORM_B2",
    ) -> ClientSideEncryption:
        source = os.environ if environ is None else environ
        active_key_id = source.get(f"{prefix}_ENCRYPTION_ACTIVE_KEY_ID")
        keyring_json = source.get(f"{prefix}_ENCRYPTION_KEYS_JSON")
        if not active_key_id or not keyring_json:
            raise ArchiveStorageError("Client-side encryption is not configured.")
        try:
            parsed: Any = json.loads(keyring_json)
            if type(parsed) is not dict:
                raise ValueError
            keys = {
                key_id: base64.b64decode(encoded, validate=True)
                for key_id, encoded in parsed.items()
                if type(key_id) is str and type(encoded) is str
            }
            if len(keys) != len(parsed):
                raise ValueError
            return cls(active_key_id=active_key_id, keys=keys)
        except (ValueError, TypeError, binascii.Error) as exc:
            raise ArchiveStorageError(
                "Client-side encryption keyring is invalid."
            ) from exc

    def encrypt(self, object_key: str, plaintext: bytes) -> bytes:
        key_id = self.active_key_id.encode("ascii")
        nonce = secrets.token_bytes(self._NONCE_SIZE)
        associated_data = (
            self._MAGIC + b"\0" + object_key.encode("utf-8") + b"\0" + key_id
        )
        ciphertext = AESGCM(self.keys[self.active_key_id]).encrypt(
            nonce, plaintext, associated_data
        )
        return self._MAGIC + bytes((len(key_id),)) + key_id + nonce + ciphertext

    def decrypt(self, object_key: str, envelope: bytes) -> bytes:
        minimum_size = len(self._MAGIC) + 1 + 1 + self._NONCE_SIZE + self._TAG_SIZE
        if type(envelope) is not bytes or len(envelope) < minimum_size:
            raise ArchiveStorageError("Encrypted B2 object is malformed.")
        if not envelope.startswith(self._MAGIC):
            raise ArchiveStorageError("Encrypted B2 object has an unknown format.")
        key_id_size = envelope[len(self._MAGIC)]
        key_id_start = len(self._MAGIC) + 1
        nonce_start = key_id_start + key_id_size
        ciphertext_start = nonce_start + self._NONCE_SIZE
        if key_id_size < 1 or ciphertext_start + self._TAG_SIZE > len(envelope):
            raise ArchiveStorageError("Encrypted B2 object is malformed.")
        try:
            key_id = envelope[key_id_start:nonce_start].decode("ascii")
            key = self.keys[key_id]
            nonce = envelope[nonce_start:ciphertext_start]
            associated_data = (
                self._MAGIC
                + b"\0"
                + object_key.encode("utf-8")
                + b"\0"
                + key_id.encode("ascii")
            )
            return AESGCM(key).decrypt(
                nonce, envelope[ciphertext_start:], associated_data
            )
        except (KeyError, UnicodeDecodeError, InvalidTag, ValueError) as exc:
            raise ArchiveStorageError(
                "Encrypted B2 object failed authentication or its key is unavailable."
            ) from exc


@dataclass(frozen=True)
class B2S3Settings:
    endpoint_url: str
    region: str
    bucket: str
    access_key_id: str = field(repr=False)
    application_key: str = field(repr=False)

    @classmethod
    def from_environment(cls, environ: Mapping[str, str] | None = None) -> B2S3Settings:
        source = os.environ if environ is None else environ
        names = (
            "TRADING_PLATFORM_B2_ENDPOINT_URL",
            "TRADING_PLATFORM_B2_REGION",
            "TRADING_PLATFORM_B2_BUCKET",
            "TRADING_PLATFORM_B2_APPLICATION_KEY_ID",
            "TRADING_PLATFORM_B2_APPLICATION_KEY",
        )
        values = {name: source.get(name, "") for name in names}
        if any(not value.strip() for value in values.values()):
            raise ArchiveStorageError("B2 S3-compatible storage is not configured.")
        settings = cls(
            endpoint_url=values[names[0]],
            region=values[names[1]],
            bucket=values[names[2]],
            access_key_id=values[names[3]],
            application_key=values[names[4]],
        )
        settings.validate()
        return settings

    def validate(self) -> None:
        parsed = urlsplit(self.endpoint_url)
        expected_host = f"s3.{self.region}.backblazeb2.com"
        if (
            parsed.scheme != "https"
            or parsed.hostname != expected_host
            or parsed.username is not None
            or parsed.password is not None
            or parsed.path not in ("", "/")
            or parsed.query
            or parsed.fragment
            or not self.bucket
            or "/" in self.bucket
            or "\\" in self.bucket
            or any(ch.isspace() for ch in self.bucket)
        ):
            raise ArchiveStorageError("B2 S3-compatible settings are invalid.")


class B2S3Client(Protocol):
    def get_bucket_versioning(self, *, Bucket: str) -> Mapping[str, Any]: ...

    def get_object(self, *, Bucket: str, Key: str) -> Mapping[str, Any]: ...

    def put_object(
        self, *, Bucket: str, Key: str, Body: bytes, ContentType: str
    ) -> Mapping[str, Any]: ...


class BackblazeB2ObjectStore:
    """Client-encrypted object store over the Backblaze B2 S3-compatible API.

    The archive writer supplies content-addressed keys. This adapter confirms
    bucket versioning, checks existing plaintext before retrying, and reads
    every new object back before reporting success. It never deletes objects.
    """

    def __init__(
        self, client: B2S3Client, bucket: str, encryption: ClientSideEncryption
    ) -> None:
        if not bucket or "/" in bucket or "\\" in bucket:
            raise ArchiveStorageError("Invalid B2 bucket name.")
        self._client = client
        self._bucket = bucket
        self._encryption = encryption

    @classmethod
    def from_environment(
        cls, environ: Mapping[str, str] | None = None
    ) -> BackblazeB2ObjectStore:
        source = os.environ if environ is None else environ
        settings = B2S3Settings.from_environment(source)
        encryption = ClientSideEncryption.from_environment(source)
        try:
            boto3 = importlib.import_module("boto3")
            botocore_config = importlib.import_module("botocore.config")
        except ImportError as exc:
            raise ArchiveStorageError(
                "Install the archive extra to enable Backblaze B2 storage."
            ) from exc
        client = boto3.client(
            "s3",
            endpoint_url=settings.endpoint_url,
            region_name=settings.region,
            aws_access_key_id=settings.access_key_id,
            aws_secret_access_key=settings.application_key,
            config=botocore_config.Config(signature_version="s3v4"),
        )
        return cls(client, settings.bucket, encryption)

    async def put_if_absent(self, key: str, value: bytes) -> None:
        _validate_object_key(key)
        if type(value) is not bytes or not value:
            raise ArchiveStorageError("Archive object must be nonempty bytes.")
        await asyncio.to_thread(self._put_if_absent, key, value)

    def _put_if_absent(self, key: str, value: bytes) -> None:
        try:
            existing = self._get_sync(key)
        except ArchiveObjectMissing:
            existing = None
        if existing is not None:
            if existing != value:
                raise ArchiveStorageError(
                    "Immutable archive key already contains different bytes."
                )
            return

        try:
            versioning = self._client.get_bucket_versioning(Bucket=self._bucket)
        except Exception as exc:
            raise ArchiveStorageError(
                "B2 bucket versioning could not be verified."
            ) from exc
        if versioning.get("Status") != "Enabled":
            raise ArchiveStorageError("B2 bucket versioning must be enabled.")

        encrypted = self._encryption.encrypt(key, value)
        try:
            self._client.put_object(
                Bucket=self._bucket,
                Key=key,
                Body=encrypted,
                ContentType="application/octet-stream",
            )
        except Exception as exc:
            raise ArchiveStorageError("B2 archive upload failed.") from exc
        if self._get_sync(key) != value:
            raise ArchiveStorageError("B2 archive failed encrypted read-back check.")

    async def get(self, key: str) -> bytes:
        _validate_object_key(key)
        return await asyncio.to_thread(self._get_sync, key)

    def _get_sync(self, key: str) -> bytes:
        try:
            response = self._client.get_object(Bucket=self._bucket, Key=key)
        except Exception as exc:
            if _is_not_found(exc):
                raise ArchiveObjectMissing("Archive object is missing.") from exc
            raise ArchiveStorageError("B2 archive read failed.") from exc
        body = response.get("Body")
        read = getattr(body, "read", None)
        if not callable(read):
            raise ArchiveStorageError("B2 archive response has no readable body.")
        try:
            encrypted = read()
        except Exception as exc:
            raise ArchiveStorageError("B2 archive response could not be read.") from exc
        finally:
            close = getattr(body, "close", None)
            if callable(close):
                close()
        if type(encrypted) is not bytes:
            raise ArchiveStorageError("B2 archive response was not binary data.")
        return self._encryption.decrypt(key, encrypted)


class LocalFilesystemObjectStore:
    """Local-only immutable object store for development and integration tests.

    Production cold storage must use a separately configured object-store
    adapter with versioning, access controls, and tested backup/restore.
    """

    def __init__(self, root: Path):
        self._root = root.expanduser().resolve()

    def _path(self, key: str) -> Path:
        _validate_object_key(key)
        relative = PurePosixPath(key)
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
            raise ArchiveObjectMissing("Archive object is missing.") from exc


class EncryptedObjectStore:
    """Encrypt immutable objects before writing them to a local filesystem."""

    def __init__(
        self, store: ImmutableObjectStore, encryption: ClientSideEncryption
    ) -> None:
        self._store = store
        self._encryption = encryption

    @classmethod
    def from_environment(
        cls,
        root: Path,
        environ: Mapping[str, str] | None = None,
    ) -> EncryptedObjectStore:
        return cls(
            LocalFilesystemObjectStore(root),
            ClientSideEncryption.from_environment(
                environ, prefix="TRADING_PLATFORM_LOCAL"
            ),
        )

    async def put_if_absent(self, key: str, value: bytes) -> None:
        _validate_object_key(key)
        if type(value) is not bytes or not value:
            raise ArchiveStorageError("Archive object must be nonempty bytes.")
        try:
            existing = await self._store.get(key)
        except ArchiveObjectMissing:
            existing = None
        if existing is not None:
            if self._encryption.decrypt(key, existing) != value:
                raise ArchiveStorageError(
                    "Immutable archive key already contains different bytes."
                )
            return
        encrypted = self._encryption.encrypt(key, value)
        try:
            await self._store.put_if_absent(key, encrypted)
        except ArchiveStorageError:
            # Another writer may have won the immutable create race. Accept it
            # only when the stored ciphertext authenticates to the same bytes.
            try:
                existing = await self._store.get(key)
            except ArchiveStorageError:
                raise
            if self._encryption.decrypt(key, existing) != value:
                raise ArchiveStorageError(
                    "Immutable archive key already contains different bytes."
                )
        if await self.get(key) != value:
            raise ArchiveStorageError("Local encrypted object failed read-back check.")

    async def get(self, key: str) -> bytes:
        _validate_object_key(key)
        encrypted = await self._store.get(key)
        return self._encryption.decrypt(key, encrypted)


def _validate_object_key(key: str) -> None:
    if (
        type(key) is not str
        or not key
        or key.startswith("/")
        or "\\" in key
        or "\x00" in key
        or any(part in ("", ".", "..") for part in key.split("/"))
    ):
        raise ArchiveStorageError("Invalid archive object key.")


def _is_not_found(exc: Exception) -> bool:
    response = getattr(exc, "response", None)
    if not isinstance(response, Mapping):
        return False
    error = response.get("Error", {})
    metadata = response.get("ResponseMetadata", {})
    code = error.get("Code") if isinstance(error, Mapping) else None
    status = metadata.get("HTTPStatusCode") if isinstance(metadata, Mapping) else None
    return code in {"404", "NoSuchKey", "NotFound"} or status == 404
