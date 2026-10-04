"""Verified, immutable cold copies for bounded C-001 OHLCV batches."""

from __future__ import annotations

import gzip
import hashlib
import io
import json
import zlib
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, cast

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from trading_platform_api.contracts.serialization import canonical_sha256
from trading_platform_api.lineage.archive_storage import (
    ArchiveStorageError,
    ImmutableObjectStore,
)
from trading_platform_api.lineage.codec import (
    LineageError,
    LineageKey,
    decode,
    encode,
    key_for,
)
from trading_platform_api.lineage.policy import is_personal_spot_ohlcv
from trading_platform_api.lineage.tables import (
    archive_members,
    archive_objects,
    payload_events,
    records,
)
from trading_platform_api.market_data.contracts import MarketData

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

_MAX_RECORDS_PER_OBJECT = 500
_MAX_BUNDLE_BYTES = 32 * 1024 * 1024
_HOT_RETENTION = timedelta(days=90)


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _json_bytes(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def _event_id(key: LineageKey, event_type: str, digest: str) -> str:
    value = "|".join((key.contract_id, key.record_id, key.version, event_type, digest))
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _manifest_key(object_key: str) -> str:
    return object_key.removesuffix(".jsonl.gz") + ".manifest.json"


def _object_key(record: MarketData, bundle_sha256: str) -> str:
    venue = hashlib.sha256(record.venue_id.encode("utf-8")).hexdigest()[:16]
    instrument = hashlib.sha256(record.instrument_id.encode("utf-8")).hexdigest()[:16]
    event_date = record.event_time.astimezone(UTC).date().isoformat()
    return (
        f"spot-ohlcv/v1/date={event_date}/venue={venue}/instrument={instrument}/"
        f"{bundle_sha256}.jsonl.gz"
    )


def _archive_manifest(
    *,
    object_key: str,
    bundle_sha256: str,
    compressed_sha256: str,
    members: list[dict[str, str]],
) -> bytes:
    return _json_bytes(
        {
            "format": "lineage-market-archive-v1",
            "object_key": object_key,
            "bundle_sha256": bundle_sha256,
            "compressed_sha256": compressed_sha256,
            "record_count": len(members),
            "members": members,
        }
    )


async def archive_market_data_batch(
    session: AsyncSession,
    object_store: ImmutableObjectStore,
    keys: tuple[LineageKey, ...],
    *,
    now: datetime | None = None,
) -> str:
    """Publish and verify one old, single-partition C-001 batch to cold storage.

    The caller owns the PostgreSQL transaction. This function publishes an
    immutable cold copy and its database manifest, but never removes the hot
    payload. Hot removal is a later, separately gated lifecycle operation.
    """
    if (
        type(keys) is not tuple
        or not keys
        or len(keys) > _MAX_RECORDS_PER_OBJECT
        or len(set(keys)) != len(keys)
        or not all(
            type(key) is LineageKey and key.contract_id == "C-001" for key in keys
        )
    ):
        raise LineageError("Archive batch requires 1–500 unique C-001 keys.")
    moment = now or datetime.now(UTC)
    if moment.tzinfo is None or moment.utcoffset() is None:
        raise LineageError("Archive cutoff must be timezone-aware.")
    moment = moment.astimezone(UTC)

    # Local import avoids a store/archival module cycle.
    from trading_platform_api.lineage.store import SqlAlchemyLineageStore

    store = SqlAlchemyLineageStore(session, archive_store=object_store)
    loaded = [await store.get(key) for key in keys]
    if not all(type(record) is MarketData for record in loaded):
        raise LineageError("Only canonical C-001 market data can be archived.")
    market_records = sorted(
        cast(list[MarketData], loaded),
        key=lambda item: (item.event_time, str(item.market_data_id)),
    )
    first = market_records[0]
    if not all(is_personal_spot_ohlcv(item) for item in market_records):
        raise LineageError(
            "Cold archive is limited to the five approved Spot OHLCV pairs."
        )
    partition_date = first.event_time.astimezone(UTC).date()
    if any(
        item.instrument_id != first.instrument_id
        or item.venue_id != first.venue_id
        or item.event_time.astimezone(UTC).date() != partition_date
        for item in market_records
    ):
        raise LineageError(
            "Archive batches must share UTC date, venue, and instrument."
        )
    if any(item.event_time + _HOT_RETENTION > moment for item in market_records):
        raise LineageError("Market payload is still inside the 90-day hot window.")

    documents = [encode(item) for item in market_records]
    bundle = ("\n".join(documents) + "\n").encode("utf-8")
    if len(bundle) > _MAX_BUNDLE_BYTES:
        raise LineageError("Archive batch exceeds the 32 MiB uncompressed limit.")
    bundle_sha = _digest(bundle)
    compressed = gzip.compress(bundle, compresslevel=9, mtime=0)
    compressed_sha = _digest(compressed)
    object_key = _object_key(first, bundle_sha)
    manifest_key = _manifest_key(object_key)
    members = [
        {
            "contract_id": "C-001",
            "record_id": str(item.market_data_id),
            "version": "1",
            "document_sha256": _digest(document.encode("utf-8")),
            "evidence_sha256": canonical_sha256(item),
            "event_time": item.event_time.isoformat(),
        }
        for item, document in zip(market_records, documents, strict=True)
    ]
    manifest = _archive_manifest(
        object_key=object_key,
        bundle_sha256=bundle_sha,
        compressed_sha256=compressed_sha,
        members=members,
    )
    manifest_sha = _digest(manifest)

    try:
        await object_store.put_if_absent(object_key, compressed)
        stored_compressed = await object_store.get(object_key)
        if _digest(stored_compressed) != compressed_sha:
            raise LineageError("Cold archive object failed read-back verification.")
        with gzip.GzipFile(fileobj=io.BytesIO(stored_compressed), mode="rb") as stream:
            read_back_bundle = stream.read(_MAX_BUNDLE_BYTES + 1)
        if len(read_back_bundle) > _MAX_BUNDLE_BYTES or read_back_bundle != bundle:
            raise LineageError("Cold archive content differs after decompression.")
        await object_store.put_if_absent(manifest_key, manifest)
        stored_manifest = await object_store.get(manifest_key)
        if stored_manifest != manifest or _digest(stored_manifest) != manifest_sha:
            raise LineageError("Cold archive manifest failed read-back verification.")
    except ArchiveStorageError as exc:
        raise LineageError(
            "Cold archive storage is unavailable or conflicting."
        ) from exc

    object_row = {
        "object_key": object_key,
        "compressed_sha256": compressed_sha,
        "bundle_sha256": bundle_sha,
        "manifest_key": manifest_key,
        "manifest_sha256": manifest_sha,
        "record_count": len(members),
        "first_event_time": market_records[0].event_time,
        "last_event_time": market_records[-1].event_time,
        "archived_at": moment,
    }
    await session.execute(
        pg_insert(archive_objects)
        .values(**object_row)
        .on_conflict_do_nothing(index_elements=[archive_objects.c.object_key])
    )
    stored_object = (
        (
            await session.execute(
                select(archive_objects).where(
                    archive_objects.c.object_key == object_key
                )
            )
        )
        .mappings()
        .one()
    )
    if any(
        stored_object[name] != value
        for name, value in object_row.items()
        if name != "archived_at"
    ):
        raise LineageError("Archive object key already has conflicting metadata.")

    for item, member in zip(market_records, members, strict=True):
        key = key_for(item)
        identity = {
            "contract_id": key.contract_id,
            "record_id": key.record_id,
            "version": key.version,
        }
        anchor = (
            (
                await session.execute(
                    select(records).where(
                        *[records.c[name] == value for name, value in identity.items()]
                    )
                )
            )
            .mappings()
            .one()
        )
        if (
            anchor["document_sha256"] != member["document_sha256"]
            or anchor["evidence_sha256"] != member["evidence_sha256"]
        ):
            raise LineageError("Archive member digests differ from the lineage anchor.")
        member_row = {
            **identity,
            "object_key": object_key,
            "document_sha256": member["document_sha256"],
            "evidence_sha256": member["evidence_sha256"],
            "event_time": item.event_time,
        }
        await session.execute(
            pg_insert(archive_members)
            .values(**member_row)
            .on_conflict_do_nothing(
                index_elements=[
                    archive_members.c.contract_id,
                    archive_members.c.record_id,
                    archive_members.c.version,
                ]
            )
        )
        existing_member = (
            (
                await session.execute(
                    select(archive_members).where(
                        *[
                            archive_members.c[name] == value
                            for name, value in identity.items()
                        ]
                    )
                )
            )
            .mappings()
            .one()
        )
        if any(existing_member[name] != value for name, value in member_row.items()):
            raise LineageError(
                "Market payload already maps to different cold evidence."
            )
        event = {
            "event_id": _event_id(key, "COLD_VERIFIED", member["document_sha256"]),
            **identity,
            "event_type": "COLD_VERIFIED",
            "object_key": object_key,
            "payload_sha256": member["document_sha256"],
            "occurred_at": moment,
        }
        await session.execute(
            pg_insert(payload_events)
            .values(**event)
            .on_conflict_do_nothing(index_elements=[payload_events.c.event_id])
        )

    # Exercise the same cold resolver before the caller can commit the manifest.
    for key in keys:
        anchor = (
            (
                await session.execute(
                    select(records).where(
                        *[
                            records.c[name] == value
                            for name, value in _identity(key).items()
                        ]
                    )
                )
            )
            .mappings()
            .one()
        )
        if anchor["document"] is None:
            payload_result = await store.get(key)
            if key_for(payload_result) != key:
                raise LineageError(
                    "Cold resolver returned a different lineage identity."
                )
    return object_key


def _identity(key: LineageKey) -> dict[str, str]:
    return {
        "contract_id": key.contract_id,
        "record_id": key.record_id,
        "version": key.version,
    }


async def read_archived_market_document(
    session: AsyncSession,
    key: LineageKey,
    object_store: ImmutableObjectStore,
    *,
    document_sha256: str,
    evidence_sha256: str,
) -> str:
    """Fetch and fully verify one member from a cold immutable batch."""
    identity = _identity(key)
    member = (
        (
            await session.execute(
                select(archive_members).where(
                    *[
                        archive_members.c[name] == value
                        for name, value in identity.items()
                    ]
                )
            )
        )
        .mappings()
        .one_or_none()
    )
    if member is None:
        raise LineageError(
            "Exact lineage payload is missing from hot and cold storage."
        )
    if (
        member["document_sha256"] != document_sha256
        or member["evidence_sha256"] != evidence_sha256
    ):
        raise LineageError("Cold archive member differs from its lineage anchor.")
    object_row = (
        (
            await session.execute(
                select(archive_objects).where(
                    archive_objects.c.object_key == member["object_key"]
                )
            )
        )
        .mappings()
        .one_or_none()
    )
    if object_row is None:
        raise LineageError("Cold archive manifest is missing.")
    cached_batches = session.info.get("_verified_archived_market_batches", {})
    cached_records = cached_batches.get(member["object_key"])
    if cached_records is not None:
        record = cached_records.get(key)
        if record is None:
            raise LineageError("Cold archive member is absent from its verified batch.")
        document = encode(record)
        if (
            _digest(document.encode("utf-8")) != document_sha256
            or canonical_sha256(record) != evidence_sha256
        ):
            raise LineageError("Cold archive cache differs from its lineage anchor.")
        return document
    try:
        compressed = await object_store.get(object_row["object_key"])
        manifest = await object_store.get(object_row["manifest_key"])
    except ArchiveStorageError as exc:
        raise LineageError("Cold archive payload is unavailable.") from exc
    if (
        _digest(compressed) != object_row["compressed_sha256"]
        or _digest(manifest) != object_row["manifest_sha256"]
    ):
        raise LineageError("Cold archive object or manifest digest mismatch.")
    try:
        if len(compressed) > _MAX_BUNDLE_BYTES:
            raise LineageError("Cold archive object exceeds its compressed-size limit.")
        manifest_data = json.loads(manifest)
        with gzip.GzipFile(fileobj=io.BytesIO(compressed), mode="rb") as stream:
            bundle = stream.read(_MAX_BUNDLE_BYTES + 1)
    except (ValueError, OSError, EOFError, zlib.error) as exc:
        raise LineageError("Cold archive object is corrupt.") from exc
    if (
        type(manifest_data) is not dict
        or manifest_data.get("format") != "lineage-market-archive-v1"
        or manifest_data.get("object_key") != object_row["object_key"]
        or manifest_data.get("compressed_sha256") != object_row["compressed_sha256"]
        or manifest_data.get("bundle_sha256") != object_row["bundle_sha256"]
        or manifest_data.get("record_count") != object_row["record_count"]
        or len(bundle) > _MAX_BUNDLE_BYTES
        or _digest(bundle) != object_row["bundle_sha256"]
    ):
        raise LineageError("Cold archive manifest does not match its database record.")
    db_members = (
        (
            await session.execute(
                select(archive_members)
                .where(archive_members.c.object_key == object_row["object_key"])
                .limit(_MAX_RECORDS_PER_OBJECT + 1)
            )
        )
        .mappings()
        .all()
    )
    if (
        len(db_members) != object_row["record_count"]
        or len(db_members) > _MAX_RECORDS_PER_OBJECT
    ):
        raise LineageError("Cold archive member count is inconsistent.")
    db_manifest_members = sorted(
        [
            {
                "contract_id": row["contract_id"],
                "record_id": row["record_id"],
                "version": row["version"],
                "document_sha256": row["document_sha256"],
                "evidence_sha256": row["evidence_sha256"],
                "event_time": row["event_time"].isoformat(),
            }
            for row in db_members
        ],
        key=lambda row: (row["event_time"], row["record_id"]),
    )
    if manifest_data.get("members") != db_manifest_members:
        raise LineageError("Cold archive manifest membership is inconsistent.")
    if len(bundle) > _MAX_BUNDLE_BYTES:
        raise LineageError("Cold archive bundle exceeds its read limit.")
    lines = bundle.splitlines()
    if len(lines) != object_row["record_count"]:
        raise LineageError("Cold archive bundle record count mismatch.")
    for line in lines:
        try:
            document = line.decode("utf-8")
            from trading_platform_api.lineage.codec import decode

            record = decode(document)
        except (UnicodeDecodeError, LineageError) as exc:
            raise LineageError(
                "Cold archive contains an invalid canonical record."
            ) from exc
        record_key = key_for(record)
        if record_key == key:
            if (
                _digest(document.encode("utf-8")) != document_sha256
                or canonical_sha256(record) != evidence_sha256
            ):
                raise LineageError(
                    "Cold archive payload digest differs from its anchor."
                )
            return document
    raise LineageError("Cold archive manifest does not contain the requested key.")


async def read_archived_market_batch(
    session: AsyncSession,
    object_store: ImmutableObjectStore,
    object_key: str,
) -> dict[LineageKey, MarketData]:
    """Read and verify every member in one cold object with a single pass."""

    object_row = (
        (
            await session.execute(
                select(archive_objects).where(
                    archive_objects.c.object_key == object_key
                )
            )
        )
        .mappings()
        .one_or_none()
    )
    if object_row is None:
        raise LineageError("Cold archive manifest is missing.")
    try:
        compressed = await object_store.get(object_row["object_key"])
        manifest = await object_store.get(object_row["manifest_key"])
    except ArchiveStorageError as exc:
        raise LineageError("Cold archive payload is unavailable.") from exc
    if (
        _digest(compressed) != object_row["compressed_sha256"]
        or _digest(manifest) != object_row["manifest_sha256"]
    ):
        raise LineageError("Cold archive object or manifest digest mismatch.")
    try:
        if len(compressed) > _MAX_BUNDLE_BYTES:
            raise LineageError("Cold archive object exceeds its compressed-size limit.")
        manifest_data = json.loads(manifest)
        with gzip.GzipFile(fileobj=io.BytesIO(compressed), mode="rb") as stream:
            bundle = stream.read(_MAX_BUNDLE_BYTES + 1)
    except (ValueError, OSError, EOFError, zlib.error) as exc:
        raise LineageError("Cold archive object is corrupt.") from exc
    if (
        type(manifest_data) is not dict
        or manifest_data.get("format") != "lineage-market-archive-v1"
        or manifest_data.get("object_key") != object_key
        or manifest_data.get("compressed_sha256") != object_row["compressed_sha256"]
        or manifest_data.get("bundle_sha256") != object_row["bundle_sha256"]
        or manifest_data.get("record_count") != object_row["record_count"]
        or len(bundle) > _MAX_BUNDLE_BYTES
        or _digest(bundle) != object_row["bundle_sha256"]
    ):
        raise LineageError("Cold archive manifest does not match its database record.")

    member_rows = (
        (
            await session.execute(
                select(archive_members)
                .where(archive_members.c.object_key == object_key)
                .order_by(archive_members.c.event_time, archive_members.c.record_id)
                .limit(_MAX_RECORDS_PER_OBJECT + 1)
            )
        )
        .mappings()
        .all()
    )
    if (
        not member_rows
        or len(member_rows) != object_row["record_count"]
        or len(member_rows) > _MAX_RECORDS_PER_OBJECT
    ):
        raise LineageError("Cold archive member count is inconsistent.")

    manifest_members = [
        {
            "contract_id": row["contract_id"],
            "record_id": row["record_id"],
            "version": row["version"],
            "document_sha256": row["document_sha256"],
            "evidence_sha256": row["evidence_sha256"],
            "event_time": row["event_time"].isoformat(),
        }
        for row in member_rows
    ]
    if manifest_data.get("members") != manifest_members:
        raise LineageError("Cold archive manifest membership is inconsistent.")

    lines = bundle.splitlines()
    if len(lines) != len(member_rows):
        raise LineageError("Cold archive bundle record count mismatch.")
    verified: dict[LineageKey, MarketData] = {}
    for line, member in zip(lines, member_rows, strict=True):
        try:
            document = line.decode("utf-8")
            record = decode(document)
        except (UnicodeDecodeError, LineageError) as exc:
            raise LineageError(
                "Cold archive contains an invalid canonical record."
            ) from exc
        key = key_for(record)
        if (
            type(record) is not MarketData
            or key.contract_id != member["contract_id"]
            or key.record_id != member["record_id"]
            or key.version != member["version"]
            or record.event_time != member["event_time"]
            or _digest(document.encode("utf-8")) != member["document_sha256"]
            or canonical_sha256(record) != member["evidence_sha256"]
            or not is_personal_spot_ohlcv(record)
            or key in verified
        ):
            raise LineageError("Cold archive member differs from its lineage anchor.")
        verified[key] = record
    session.info.setdefault("_verified_archived_market_batches", {})[object_key] = (
        verified
    )
    return verified
