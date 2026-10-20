"""Provider-neutral event/news observation normalization.

The normalizer accepts bounded provider payload bytes for hashing and synthetic
fixtures, but emits no article text or instructions. It performs no network,
storage, sentiment scoring, or trading-decision work.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from hashlib import sha256
from uuid import UUID

from trading_platform_api.market_data.contracts import (
    DataSourceRecord,
    EventData,
)


class EventNormalizationError(ValueError):
    """A sanitized failure of an event observation batch."""


class EventDisposition(StrEnum):
    ORIGINAL = "ORIGINAL"
    CORRECTION = "CORRECTION"
    RETRACTION = "RETRACTION"


class EventAssetAttribution(StrEnum):
    OBSERVED = "OBSERVED"
    INFERRED = "INFERRED"
    UNKNOWN = "UNKNOWN"
    NOT_APPLICABLE = "NOT_APPLICABLE"


def _identifier(name: str, value: object, *, maximum: int = 255) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or len(value) > maximum
        or any(ord(char) < 32 for char in value)
    ):
        raise EventNormalizationError(f"{name} must be a bounded identifier.")
    return value


def _utc(name: str, value: object) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise EventNormalizationError(f"{name} must be timezone-aware.")
    if value.utcoffset() is None:
        raise EventNormalizationError(f"{name} must be timezone-aware.")
    return value.astimezone(UTC)


@dataclass(frozen=True, slots=True)
class EventPolicy:
    maximum_records: int = 1000
    maximum_source_bytes: int = 1_048_576

    def __post_init__(self) -> None:
        if (
            type(self.maximum_records) is not int
            or not 1 <= self.maximum_records <= 1000
        ):
            raise EventNormalizationError("maximum_records is out of bounds.")
        if (
            type(self.maximum_source_bytes) is not int
            or not 1 <= self.maximum_source_bytes <= 1_048_576
        ):
            raise EventNormalizationError("maximum_source_bytes is out of bounds.")


@dataclass(frozen=True, slots=True)
class RawEventObservation:
    source_record_id: UUID
    provider_id: str
    provider_version: str
    raw_schema_version: str
    adapter_version: str
    licensing_reference: str
    provider_event_id: str
    publisher_id: str
    canonical_event_id: str
    event_type: str
    publication_time: datetime
    effective_time: datetime
    provider_update_time: datetime
    retrieval_time: datetime
    ingestion_time: datetime
    availability_time: datetime
    disposition: EventDisposition
    related_event_id: str | None
    asset_ids: tuple[str, ...]
    asset_attribution: EventAssetAttribution
    language: str | None
    raw_source_bytes: bytes = field(repr=False)


@dataclass(frozen=True, slots=True)
class EventIdentity:
    source_record_id: UUID
    provider_id: str
    provider_event_id: str
    publisher_id: str
    canonical_event_id: str
    event_type: str
    publication_time: datetime
    effective_time: datetime
    provider_update_time: datetime
    retrieval_time: datetime
    ingestion_time: datetime
    availability_time: datetime
    disposition: EventDisposition
    related_event_id: str | None
    asset_ids: tuple[str, ...]
    asset_attribution: EventAssetAttribution
    language: str | None


@dataclass(frozen=True, slots=True)
class NormalizedEventGroup:
    canonical_event_id: str
    event_type: str
    source_record_ids: tuple[UUID, ...]
    provider_event_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class NormalizedEvents:
    source_records: tuple[DataSourceRecord, ...]
    event_data: tuple[EventData, ...]
    identities: tuple[EventIdentity, ...]
    groups: tuple[NormalizedEventGroup, ...]
    duplicate_provider_event_ids: tuple[str, ...]


def normalize_events(
    observations: tuple[RawEventObservation, ...],
    policy: EventPolicy,
) -> NormalizedEvents:
    """Normalize one bounded batch while preserving source and event timing.

    Publication time is the canonical EventData event time. Effective time,
    update/correction status, asset attribution, language, and multi-source
    grouping remain in sidecars because C-002 v1 does not serialize them.
    Group IDs are supplied by the caller; no fuzzy event clustering is inferred.
    """
    if type(policy) is not EventPolicy:
        raise EventNormalizationError("Invalid event policy.")
    if type(observations) is not tuple or len(observations) > policy.maximum_records:
        raise EventNormalizationError("Observation batch exceeds policy.")

    sources: list[DataSourceRecord] = []
    events: list[EventData] = []
    identities: list[EventIdentity] = []
    duplicates: list[str] = []
    seen: dict[tuple[str, str], tuple[object, ...]] = {}
    source_ids: set[UUID] = set()
    groups: dict[str, tuple[str, list[UUID], list[str]]] = {}

    for item in observations:
        if not isinstance(item, RawEventObservation):
            raise EventNormalizationError("Invalid observation type.")
        if not isinstance(item.source_record_id, UUID):
            raise EventNormalizationError("Invalid source identity.")

        provider_id = _identifier("provider_id", item.provider_id)
        provider_event_id = _identifier(
            "provider_event_id", item.provider_event_id
        )
        publisher_id = _identifier("publisher_id", item.publisher_id)
        canonical_event_id = _identifier(
            "canonical_event_id", item.canonical_event_id
        )
        event_type = _identifier("event_type", item.event_type)
        for name in (
            "provider_version",
            "raw_schema_version",
            "adapter_version",
            "licensing_reference",
        ):
            _identifier(name, getattr(item, name))

        if type(item.disposition) is not EventDisposition:
            raise EventNormalizationError("Invalid event disposition.")
        if type(item.asset_attribution) is not EventAssetAttribution:
            raise EventNormalizationError("Invalid asset attribution.")
        if type(item.asset_ids) is not tuple:
            raise EventNormalizationError("asset_ids must be a tuple.")
        asset_ids = tuple(
            _identifier(f"asset_ids[{index}]", value)
            for index, value in enumerate(item.asset_ids)
        )
        if len(set(asset_ids)) != len(asset_ids):
            raise EventNormalizationError("asset_ids must not contain duplicates.")
        language = (
            _identifier("language", item.language, maximum=35)
            if item.language is not None
            else None
        )
        related_event_id = (
            _identifier("related_event_id", item.related_event_id)
            if item.related_event_id is not None
            else None
        )
        if item.disposition is EventDisposition.ORIGINAL:
            if related_event_id is not None:
                raise EventNormalizationError(
                    "Original events cannot reference a superseded event."
                )
        elif related_event_id is None or related_event_id == provider_event_id:
            raise EventNormalizationError(
                "Corrections and retractions require a distinct related event."
            )

        published = _utc("publication_time", item.publication_time)
        effective = _utc("effective_time", item.effective_time)
        updated = _utc("provider_update_time", item.provider_update_time)
        retrieved = _utc("retrieval_time", item.retrieval_time)
        ingested = _utc("ingestion_time", item.ingestion_time)
        available = _utc("availability_time", item.availability_time)
        if not published <= updated <= retrieved <= ingested <= available:
            raise EventNormalizationError("Invalid event chronology.")
        # Effective time is independent and may precede or follow publication.

        raw_bytes = item.raw_source_bytes
        if (
            type(raw_bytes) is not bytes
            or not 0 < len(raw_bytes) <= policy.maximum_source_bytes
        ):
            raise EventNormalizationError(
                "Exact bounded raw source bytes are required."
            )
        digest = sha256(raw_bytes).hexdigest()
        provider_key = (provider_id, provider_event_id)
        provider_identity = (
            provider_id,
            item.provider_version,
            item.raw_schema_version,
            item.adapter_version,
            item.licensing_reference,
        )
        fingerprint = (
            digest,
            publisher_id,
            canonical_event_id,
            event_type,
            published,
            effective,
            updated,
            retrieved,
            ingested,
            available,
            item.disposition,
            related_event_id,
            asset_ids,
            item.asset_attribution,
            language,
            provider_identity,
        )
        if provider_key in seen:
            if seen[provider_key] != fingerprint:
                raise EventNormalizationError(
                    "Conflicting provider event identity."
                )
            if provider_event_id not in duplicates:
                duplicates.append(provider_event_id)
            continue
        seen[provider_key] = fingerprint

        if item.source_record_id in source_ids:
            raise EventNormalizationError("Duplicate source record identity.")
        source_ids.add(item.source_record_id)

        group = groups.get(canonical_event_id)
        if group is not None and group[0] != event_type:
            raise EventNormalizationError(
                "Canonical event group has conflicting event types."
            )
        if group is None:
            group = (event_type, [], [])
            groups[canonical_event_id] = group
        group[1].append(item.source_record_id)
        group[2].append(provider_event_id)

        sources.append(
            DataSourceRecord(
                source_record_id=item.source_record_id,
                provider_id=provider_id,
                provider_version=item.provider_version,
                provider_event_time=updated,
                retrieval_time=retrieved,
                availability_time=available,
                raw_schema_version=item.raw_schema_version,
                adapter_version=item.adapter_version,
                licensing_reference=item.licensing_reference,
                content_sha256=digest,
            )
        )
        events.append(
            EventData(
                event_id=canonical_event_id,
                event_type=event_type,
                event_time=published,
                availability_time=available,
                source_record_id=item.source_record_id,
            )
        )
        identities.append(
            EventIdentity(
                source_record_id=item.source_record_id,
                provider_id=provider_id,
                provider_event_id=provider_event_id,
                publisher_id=publisher_id,
                canonical_event_id=canonical_event_id,
                event_type=event_type,
                publication_time=published,
                effective_time=effective,
                provider_update_time=updated,
                retrieval_time=retrieved,
                ingestion_time=ingested,
                availability_time=available,
                disposition=item.disposition,
                related_event_id=related_event_id,
                asset_ids=asset_ids,
                asset_attribution=item.asset_attribution,
                language=language,
            )
        )

    normalized_groups = tuple(
        NormalizedEventGroup(
            canonical_event_id=canonical_event_id,
            event_type=group[0],
            source_record_ids=tuple(group[1]),
            provider_event_ids=tuple(group[2]),
        )
        for canonical_event_id, group in groups.items()
    )
    return NormalizedEvents(
        source_records=tuple(sources),
        event_data=tuple(events),
        identities=tuple(identities),
        groups=normalized_groups,
        duplicate_provider_event_ids=tuple(duplicates),
    )
