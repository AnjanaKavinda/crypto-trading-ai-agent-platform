"""Operator-triggered hot-payload removal after verified cold retention."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select, tuple_
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from trading_platform_api.contracts.serialization import canonical_sha256
from trading_platform_api.lineage.archival import read_archived_market_batch
from trading_platform_api.lineage.archive_storage import ImmutableObjectStore
from trading_platform_api.lineage.codec import LineageError, LineageKey, encode
from trading_platform_api.lineage.store import SqlAlchemyLineageStore
from trading_platform_api.lineage.tables import (
    archive_members,
    links,
    market_payloads,
    payload_events,
    records,
)

_HOT_RETENTION = timedelta(days=90)
_MAX_REFERENCE_ROOTS = 1000


@dataclass(frozen=True, slots=True)
class HotPayloadRemovalResult:
    members: tuple[LineageKey, ...]
    removed: tuple[LineageKey, ...]


def _key_tuple(key: LineageKey) -> tuple[str, str, str]:
    return key.contract_id, key.record_id, key.version


async def remove_archived_hot_payloads(
    session: AsyncSession,
    archive_store: ImmutableObjectStore,
    object_key: str,
    *,
    now: datetime | None = None,
    expected_record_ids: tuple[str, ...] | None = None,
    expected_removed_record_ids: tuple[str, ...] | None = None,
) -> HotPayloadRemovalResult:
    """Remove one verified old archive batch's hot copies in the caller's txn.

    This function never deletes lineage anchors, archive members, or dependency
    edges. The operator CLI runs it on the restored copy first, verifies the
    cold resolver and retained references, and only then runs it on the source.
    """

    if type(object_key) is not str or not object_key:
        raise LineageError("An exact cold archive object key is required.")
    moment = now or datetime.now(UTC)
    if moment.tzinfo is None or moment.utcoffset() is None:
        raise LineageError("Payload removal time must include a timezone.")
    moment = moment.astimezone(UTC)

    member_rows = (
        (
            await session.execute(
                select(archive_members)
                .where(archive_members.c.object_key == object_key)
                .order_by(archive_members.c.event_time, archive_members.c.record_id)
                .limit(501)
            )
        )
        .mappings()
        .all()
    )
    if not member_rows or len(member_rows) > 500:
        raise LineageError("Cold archive object has no bounded C-001 membership.")
    keys = tuple(
        LineageKey(row["contract_id"], row["record_id"], row["version"])
        for row in member_rows
    )
    if any(key.contract_id != "C-001" for key in keys):
        raise LineageError("Hot-payload removal is limited to C-001 observations.")
    if expected_record_ids is not None and set(expected_record_ids) != {
        key.record_id for key in keys
    }:
        raise LineageError(
            "Source cold membership differs from the validated disposable restore."
        )
    expected_removed = (
        None
        if expected_removed_record_ids is None
        else set(expected_removed_record_ids)
    )
    if expected_removed is not None and not expected_removed.issubset(
        {key.record_id for key in keys}
    ):
        raise LineageError(
            "Validated restore removal set differs from its cold membership."
        )
    archived_records = await read_archived_market_batch(
        session, archive_store, object_key
    )
    if set(archived_records) != set(keys):
        raise LineageError("Cold object membership differs from its archive index.")
    if any(row["event_time"] + _HOT_RETENTION > moment for row in member_rows):
        raise LineageError("Market payload is still inside the 90-day hot window.")

    key_values = [_key_tuple(key) for key in keys]
    reference_statement = (
        select(
            links.c.contract_id,
            links.c.record_id,
            links.c.version,
            links.c.target_contract_id,
            links.c.target_record_id,
            links.c.target_version,
        )
        .where(
            tuple_(
                links.c.target_contract_id,
                links.c.target_record_id,
                links.c.target_version,
            ).in_(key_values)
        )
        .order_by(
            links.c.contract_id,
            links.c.record_id,
            links.c.version,
            links.c.target_contract_id,
            links.c.target_record_id,
            links.c.target_version,
        )
    )
    edges_before = tuple(
        tuple(row) for row in (await session.execute(reference_statement)).all()
    )
    root_keys = tuple(
        sorted(
            {LineageKey(row[0], row[1], row[2]) for row in edges_before},
            key=lambda item: (item.contract_id, item.record_id, item.version),
        )
    )
    if len(root_keys) > _MAX_REFERENCE_ROOTS:
        raise LineageError("Affected reference roots exceed the bounded read budget.")

    cold_events = (
        (
            await session.execute(
                select(payload_events).where(
                    payload_events.c.object_key == object_key,
                    payload_events.c.event_type == "COLD_VERIFIED",
                    tuple_(
                        payload_events.c.contract_id,
                        payload_events.c.record_id,
                        payload_events.c.version,
                    ).in_(key_values),
                )
            )
        )
        .mappings()
        .all()
    )
    cold_event_keys = {
        (row["contract_id"], row["record_id"], row["version"]): row["payload_sha256"]
        for row in cold_events
    }

    lineage = SqlAlchemyLineageStore(session, archive_store=archive_store)
    removed: list[LineageKey] = []
    for member in member_rows:
        key = LineageKey(member["contract_id"], member["record_id"], member["version"])
        identity = _key_tuple(key)
        archived = archived_records[key]
        document = encode(archived)
        document_sha = hashlib.sha256(document.encode("utf-8")).hexdigest()
        evidence_sha = canonical_sha256(archived)
        if (
            member["document_sha256"] != document_sha
            or member["evidence_sha256"] != evidence_sha
            or cold_event_keys.get(identity) != document_sha
        ):
            raise LineageError("Cold archive evidence is incomplete or inconsistent.")

        anchor = (
            (
                await session.execute(
                    select(records).where(
                        tuple_(
                            records.c.contract_id,
                            records.c.record_id,
                            records.c.version,
                        )
                        == identity
                    )
                )
            )
            .mappings()
            .one_or_none()
        )
        if (
            anchor is None
            or anchor["document_sha256"] != document_sha
            or anchor["evidence_sha256"] != evidence_sha
        ):
            raise LineageError("Cold member differs from its retained lineage anchor.")
        if await lineage.get(key) != archived:
            raise LineageError("Hot or cold resolver differs from the archived record.")

        hot = (
            (
                await session.execute(
                    select(market_payloads).where(
                        tuple_(
                            market_payloads.c.contract_id,
                            market_payloads.c.record_id,
                            market_payloads.c.version,
                        )
                        == identity
                    )
                )
            )
            .mappings()
            .one_or_none()
        )
        removed_event = (
            (
                await session.execute(
                    select(payload_events).where(
                        tuple_(
                            payload_events.c.contract_id,
                            payload_events.c.record_id,
                            payload_events.c.version,
                        )
                        == identity,
                        payload_events.c.object_key == object_key,
                        payload_events.c.event_type == "HOT_REMOVED",
                        payload_events.c.payload_sha256 == document_sha,
                    )
                )
            )
            .mappings()
            .one_or_none()
        )
        if hot is None:
            if removed_event is None:
                raise LineageError("Hot payload is missing without removal evidence.")
            if expected_removed is not None and key.record_id in expected_removed:
                raise LineageError(
                    "Source hot state differs from the validated disposable restore."
                )
            continue
        if expected_removed is not None and key.record_id not in expected_removed:
            raise LineageError(
                "Source hot state differs from the validated disposable restore."
            )
        if removed_event is not None:
            raise LineageError("Hot payload conflicts with prior removal evidence.")
        if (
            hot["document"] != document
            or hot["document_sha256"] != document_sha
            or hot["evidence_sha256"] != evidence_sha
        ):
            raise LineageError("Hot payload differs from verified cold evidence.")

        event_material = "|".join(
            (
                key.contract_id,
                key.record_id,
                key.version,
                "HOT_REMOVED",
                document_sha,
            )
        )
        await session.execute(
            pg_insert(payload_events)
            .values(
                event_id=hashlib.sha256(event_material.encode("utf-8")).hexdigest(),
                contract_id=key.contract_id,
                record_id=key.record_id,
                version=key.version,
                event_type="HOT_REMOVED",
                object_key=object_key,
                payload_sha256=document_sha,
                occurred_at=moment,
            )
            .on_conflict_do_nothing(index_elements=[payload_events.c.event_id])
        )
        deleted_record_id = await session.scalar(
            delete(market_payloads)
            .where(
                tuple_(
                    market_payloads.c.contract_id,
                    market_payloads.c.record_id,
                    market_payloads.c.version,
                )
                == identity
            )
            .returning(market_payloads.c.record_id)
        )
        if deleted_record_id != key.record_id:
            raise LineageError("Hot-payload removal did not affect one exact record.")
        removed.append(key)
        if await lineage.get(key) != archived:
            raise LineageError("Cold resolver failed after hot-payload removal.")

    if root_keys:
        graph = await lineage.resolve(root_keys, maximum_records=1000)
        if any(graph.get(key) != archived_records[key] for key in keys):
            raise LineageError("Retained reference roots no longer resolve exactly.")
    else:
        for key in keys:
            if await lineage.get(key) != archived_records[key]:
                raise LineageError("Cold resolver failed for an unreferenced key.")

    edges_after = tuple(
        tuple(row) for row in (await session.execute(reference_statement)).all()
    )
    if edges_after != edges_before:
        raise LineageError("Hot-payload removal changed retained dependency edges.")

    anchors_after = (
        await session.execute(
            select(records.c.contract_id, records.c.record_id, records.c.version)
            .where(
                tuple_(
                    records.c.contract_id,
                    records.c.record_id,
                    records.c.version,
                ).in_(key_values)
            )
            .order_by(records.c.contract_id, records.c.record_id, records.c.version)
        )
    ).all()
    if {tuple(row) for row in anchors_after} != set(key_values):
        raise LineageError("Hot-payload removal changed lineage anchors.")

    return HotPayloadRemovalResult(keys, tuple(removed))
