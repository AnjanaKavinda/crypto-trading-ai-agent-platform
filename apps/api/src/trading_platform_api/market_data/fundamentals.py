"""Provider-neutral point-in-time fundamental observation normalization.

This module has no network, storage, or trading-decision authority. It uses
synthetic/provider-supplied records and keeps effective dates and revisions in
an in-memory identity sidecar because C-002 v1 does not serialize them.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from hashlib import sha256
from uuid import UUID

from trading_platform_api.market_data.contracts import (
    DataSourceRecord,
    FundamentalData,
    MetricValue,
)


class FundamentalNormalizationError(ValueError):
    """A sanitized failure of a fundamental observation batch."""


def _identifier(name: str, value: object, *, maximum: int = 255) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or len(value) > maximum
        or any(ord(char) < 32 for char in value)
    ):
        raise FundamentalNormalizationError(f"{name} must be a bounded identifier.")
    return value


def _utc(name: str, value: object) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise FundamentalNormalizationError(f"{name} must be timezone-aware.")
    if value.utcoffset() is None:
        raise FundamentalNormalizationError(f"{name} must be timezone-aware.")
    return value.astimezone(UTC)


@dataclass(frozen=True, slots=True)
class FundamentalPolicy:
    asset_id: str
    maximum_records: int = 1000
    maximum_source_bytes: int = 1_048_576

    def __post_init__(self) -> None:
        _identifier("asset_id", self.asset_id)
        if (
            type(self.maximum_records) is not int
            or not 1 <= self.maximum_records <= 1000
        ):
            raise FundamentalNormalizationError("maximum_records is out of bounds.")
        if (
            type(self.maximum_source_bytes) is not int
            or not 1 <= self.maximum_source_bytes <= 1_048_576
        ):
            raise FundamentalNormalizationError(
                "maximum_source_bytes is out of bounds."
            )


@dataclass(frozen=True, slots=True)
class RawFundamentalObservation:
    source_record_id: UUID
    provider_event_id: str
    asset_id: str
    metric_name: str
    value: Decimal
    unit: str
    publication_time: datetime
    effective_time: datetime
    provider_time: datetime
    retrieval_time: datetime
    ingestion_time: datetime
    availability_time: datetime
    revision_id: str
    supersedes_revision_id: str | None
    provider_id: str
    provider_version: str
    raw_schema_version: str
    adapter_version: str
    licensing_reference: str
    raw_source_bytes: bytes = field(repr=False)


@dataclass(frozen=True, slots=True)
class FundamentalIdentity:
    source_record_id: UUID
    provider_event_id: str
    asset_id: str
    metric_name: str
    publication_time: datetime
    effective_time: datetime
    provider_time: datetime
    retrieval_time: datetime
    ingestion_time: datetime
    availability_time: datetime
    revision_id: str
    supersedes_revision_id: str | None


@dataclass(frozen=True, slots=True)
class NormalizedFundamentals:
    source_records: tuple[DataSourceRecord, ...]
    fundamental_data: tuple[FundamentalData, ...]
    identities: tuple[FundamentalIdentity, ...]
    duplicate_event_ids: tuple[str, ...]


def normalize_fundamentals(
    observations: tuple[RawFundamentalObservation, ...],
    policy: FundamentalPolicy,
) -> NormalizedFundamentals:
    """Normalize a bounded batch without inferring continuity or revisions.

    Publication time becomes the canonical observation time. Effective time
    may be in the future (for example, a scheduled unlock) and is preserved
    only in the sidecar. Callers must keep that sidecar with the canonical
    rows; C-002 v1 does not serialize effective/revision metadata.
    """
    if type(policy) is not FundamentalPolicy:
        raise FundamentalNormalizationError("Invalid fundamental policy.")
    if type(observations) is not tuple or len(observations) > policy.maximum_records:
        raise FundamentalNormalizationError("Observation batch exceeds policy.")

    sources: list[DataSourceRecord] = []
    fundamentals: list[FundamentalData] = []
    identities: list[FundamentalIdentity] = []
    duplicates: list[str] = []
    seen_events: dict[tuple[str, str, str], tuple[object, ...]] = {}
    seen_revisions: set[tuple[str, str, str]] = set()
    source_ids: set[UUID] = set()
    provider: tuple[str, ...] | None = None

    for item in observations:
        if not isinstance(item, RawFundamentalObservation):
            raise FundamentalNormalizationError("Invalid observation type.")
        if not isinstance(item.source_record_id, UUID):
            raise FundamentalNormalizationError("Invalid source identity.")

        asset_id = _identifier("asset_id", item.asset_id)
        if asset_id != policy.asset_id:
            raise FundamentalNormalizationError("Mismatched asset_id.")
        event_id = _identifier("provider_event_id", item.provider_event_id)
        metric_name = _identifier("metric_name", item.metric_name)
        unit = _identifier("unit", item.unit)
        revision_id = _identifier("revision_id", item.revision_id)
        supersedes_revision_id = (
            _identifier("supersedes_revision_id", item.supersedes_revision_id)
            if item.supersedes_revision_id is not None
            else None
        )
        if supersedes_revision_id == revision_id:
            raise FundamentalNormalizationError("A revision cannot supersede itself.")

        for name in (
            "provider_id",
            "provider_version",
            "raw_schema_version",
            "adapter_version",
            "licensing_reference",
        ):
            _identifier(name, getattr(item, name))
        current_provider = (
            item.provider_id,
            item.provider_version,
            item.raw_schema_version,
            item.adapter_version,
            item.licensing_reference,
        )
        if provider is not None and provider != current_provider:
            raise FundamentalNormalizationError("Mixed provider identity.")
        provider = current_provider

        if type(item.value) is not Decimal or not item.value.is_finite():
            raise FundamentalNormalizationError("Metric value must be finite Decimal.")

        published = _utc("publication_time", item.publication_time)
        effective = _utc("effective_time", item.effective_time)
        provider_time = _utc("provider_time", item.provider_time)
        retrieved = _utc("retrieval_time", item.retrieval_time)
        ingested = _utc("ingestion_time", item.ingestion_time)
        available = _utc("availability_time", item.availability_time)
        if not published <= provider_time <= retrieved <= ingested <= available:
            raise FundamentalNormalizationError("Invalid source chronology.")
        # Effective time is deliberately independent: a published schedule can
        # describe a future date, and revisions can describe past effective data.

        raw_bytes = item.raw_source_bytes
        if (
            type(raw_bytes) is not bytes
            or not 0 < len(raw_bytes) <= policy.maximum_source_bytes
        ):
            raise FundamentalNormalizationError(
                "Exact bounded raw source bytes are required."
            )
        digest = sha256(raw_bytes).hexdigest()
        event_key = (asset_id, metric_name, event_id)
        revision_key = (asset_id, metric_name, revision_id)
        fingerprint = (
            digest,
            item.value,
            unit,
            published,
            effective,
            provider_time,
            retrieved,
            ingested,
            available,
            revision_id,
            supersedes_revision_id,
            current_provider,
        )
        if event_key in seen_events:
            if seen_events[event_key] != fingerprint:
                raise FundamentalNormalizationError(
                    "Conflicting provider event identity."
                )
            if event_id not in duplicates:
                duplicates.append(event_id)
            continue
        if revision_key in seen_revisions:
            raise FundamentalNormalizationError("Duplicate revision identity.")
        seen_events[event_key] = fingerprint
        seen_revisions.add(revision_key)

        if item.source_record_id in source_ids:
            raise FundamentalNormalizationError("Duplicate source record identity.")
        source_ids.add(item.source_record_id)

        sources.append(
            DataSourceRecord(
                source_record_id=item.source_record_id,
                provider_id=item.provider_id,
                provider_version=item.provider_version,
                provider_event_time=provider_time,
                retrieval_time=retrieved,
                availability_time=available,
                raw_schema_version=item.raw_schema_version,
                adapter_version=item.adapter_version,
                licensing_reference=item.licensing_reference,
                content_sha256=digest,
            )
        )
        fundamentals.append(
            FundamentalData(
                observation_time=published,
                availability_time=available,
                source_record_id=item.source_record_id,
                metrics=(MetricValue(metric_name, item.value, unit),),
            )
        )
        identities.append(
            FundamentalIdentity(
                source_record_id=item.source_record_id,
                provider_event_id=event_id,
                asset_id=asset_id,
                metric_name=metric_name,
                publication_time=published,
                effective_time=effective,
                provider_time=provider_time,
                retrieval_time=retrieved,
                ingestion_time=ingested,
                availability_time=available,
                revision_id=revision_id,
                supersedes_revision_id=supersedes_revision_id,
            )
        )

    return NormalizedFundamentals(
        source_records=tuple(sources),
        fundamental_data=tuple(fundamentals),
        identities=tuple(identities),
        duplicate_event_ids=tuple(duplicates),
    )
