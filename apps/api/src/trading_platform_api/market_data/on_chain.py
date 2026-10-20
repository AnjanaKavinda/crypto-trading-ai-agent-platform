"""Provider-neutral on-chain observation normalization.

This module uses synthetic/provider-supplied records only. It performs no
network I/O and does not infer chain finality, attribution, or market meaning.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from hashlib import sha256
from uuid import UUID

from trading_platform_api.market_data.contracts import (
    DataSourceRecord,
    MetricValue,
    OnChainData,
)


class OnChainNormalizationError(ValueError):
    """A sanitized failure of an on-chain observation batch."""


class FinalityStatus(StrEnum):
    PROVISIONAL = "PROVISIONAL"
    FINALIZED = "FINALIZED"
    NON_CANONICAL = "NON_CANONICAL"
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
        raise OnChainNormalizationError(f"{name} must be a bounded identifier.")
    return value


def _utc(name: str, value: object) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise OnChainNormalizationError(f"{name} must be timezone-aware.")
    if value.utcoffset() is None:
        raise OnChainNormalizationError(f"{name} must be timezone-aware.")
    return value.astimezone(UTC)


@dataclass(frozen=True, slots=True)
class OnChainPolicy:
    chain_id: str
    network_id: str
    asset_id: str
    maximum_records: int = 1000
    maximum_source_bytes: int = 1_048_576

    def __post_init__(self) -> None:
        for name in ("chain_id", "network_id", "asset_id"):
            _identifier(name, getattr(self, name))
        if type(self.maximum_records) is not int or not 1 <= self.maximum_records <= 1000:
            raise OnChainNormalizationError("maximum_records is out of bounds.")
        if (
            type(self.maximum_source_bytes) is not int
            or not 1 <= self.maximum_source_bytes <= 1_048_576
        ):
            raise OnChainNormalizationError("maximum_source_bytes is out of bounds.")


@dataclass(frozen=True, slots=True)
class RawOnChainObservation:
    source_record_id: UUID
    provider_event_id: str
    chain_id: str
    network_id: str
    asset_id: str
    metric_name: str
    value: Decimal
    unit: str
    observation_time: datetime
    provider_time: datetime
    retrieval_time: datetime
    ingestion_time: datetime
    availability_time: datetime
    provider_id: str
    provider_version: str
    raw_schema_version: str
    adapter_version: str
    licensing_reference: str
    finality_status: FinalityStatus
    finality_basis: str | None
    block_height: int | None
    block_hash: str | None
    parent_block_hash: str | None
    window_start: datetime | None
    window_end: datetime | None
    reorged_event_id: str | None
    raw_source_bytes: bytes = field(repr=False)


@dataclass(frozen=True, slots=True)
class OnChainIdentity:
    source_record_id: UUID
    provider_event_id: str
    chain_id: str
    network_id: str
    asset_id: str
    metric_name: str
    finality_status: FinalityStatus
    finality_basis: str | None
    block_height: int | None
    block_hash: str | None
    parent_block_hash: str | None
    window_start: datetime | None
    window_end: datetime | None
    reorged_event_id: str | None


@dataclass(frozen=True, slots=True)
class NormalizedOnChain:
    source_records: tuple[DataSourceRecord, ...]
    on_chain_data: tuple[OnChainData, ...]
    identities: tuple[OnChainIdentity, ...]
    duplicate_event_ids: tuple[str, ...]


def normalize_on_chain(
    observations: tuple[RawOnChainObservation, ...], policy: OnChainPolicy
) -> NormalizedOnChain:
    """Normalize one bounded batch without inferring finality or continuity.

    The returned identity sidecar must travel with the canonical metric/source
    rows. C-002 v1 does not serialize chain/block/finality metadata; callers
    must not persist only the canonical rows and claim those semantics survived.
    """
    if type(observations) is not tuple or len(observations) > policy.maximum_records:
        raise OnChainNormalizationError("Observation batch exceeds policy.")

    sources: list[DataSourceRecord] = []
    on_chain: list[OnChainData] = []
    identities: list[OnChainIdentity] = []
    duplicates: list[str] = []
    seen: dict[tuple[str, str, str, str], tuple[object, ...]] = {}
    source_ids: set[UUID] = set()
    previous_time: datetime | None = None
    provider: tuple[str, ...] | None = None

    for item in observations:
        if not isinstance(item, RawOnChainObservation):
            raise OnChainNormalizationError("Invalid observation type.")
        if not isinstance(item.source_record_id, UUID):
            raise OnChainNormalizationError("Invalid source identity.")

        for name in ("chain_id", "network_id", "asset_id"):
            value = _identifier(name, getattr(item, name))
            if value != getattr(policy, name):
                raise OnChainNormalizationError(f"Mismatched {name}.")

        event_id = _identifier("provider_event_id", item.provider_event_id)
        metric_name = _identifier("metric_name", item.metric_name)
        unit = _identifier("unit", item.unit)
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
            raise OnChainNormalizationError("Mixed provider identity.")
        provider = current_provider

        if type(item.value) is not Decimal or not item.value.is_finite():
            raise OnChainNormalizationError("Metric value must be a finite Decimal.")
        if type(item.finality_status) is not FinalityStatus:
            raise OnChainNormalizationError("Invalid finality status.")
        finality_basis = item.finality_basis
        if finality_basis is not None:
            finality_basis = _identifier("finality_basis", finality_basis)

        if (item.block_height is None) != (item.block_hash is None):
            raise OnChainNormalizationError("Block height and hash must be supplied together.")
        if item.block_height is not None and (
            type(item.block_height) is not int or item.block_height < 0
        ):
            raise OnChainNormalizationError("block_height must be non-negative.")
        block_hash = (
            _identifier("block_hash", item.block_hash)
            if item.block_hash is not None
            else None
        )
        parent_hash = (
            _identifier("parent_block_hash", item.parent_block_hash)
            if item.parent_block_hash is not None
            else None
        )
        if parent_hash is not None and block_hash is None:
            raise OnChainNormalizationError("Parent block hash requires a block identity.")

        if (item.window_start is None) != (item.window_end is None):
            raise OnChainNormalizationError("Window bounds must be supplied together.")
        window_start = (
            _utc("window_start", item.window_start) if item.window_start is not None else None
        )
        window_end = (
            _utc("window_end", item.window_end) if item.window_end is not None else None
        )
        if window_start is not None and window_end is not None and window_start >= window_end:
            raise OnChainNormalizationError("window_start must precede window_end.")

        if item.finality_status in (
            FinalityStatus.PROVISIONAL,
            FinalityStatus.FINALIZED,
            FinalityStatus.NON_CANONICAL,
        ):
            if (block_hash is None and window_end is None) or finality_basis is None:
                raise OnChainNormalizationError(
                    "Claimed finality requires an anchored observation and basis."
                )
        elif finality_basis is not None:
            raise OnChainNormalizationError(
                "Unknown/not-applicable finality cannot carry an inferred basis."
            )

        reorged_event_id = (
            _identifier("reorged_event_id", item.reorged_event_id)
            if item.reorged_event_id is not None
            else None
        )
        if item.finality_status is FinalityStatus.NON_CANONICAL:
            if reorged_event_id is None or reorged_event_id == event_id:
                raise OnChainNormalizationError(
                    "Non-canonical observations require a distinct reorg reference."
                )
        elif reorged_event_id is not None:
            raise OnChainNormalizationError(
                "Reorg references are valid only for non-canonical observations."
            )

        observed = _utc("observation_time", item.observation_time)
        provider_time = _utc("provider_time", item.provider_time)
        retrieved = _utc("retrieval_time", item.retrieval_time)
        ingested = _utc("ingestion_time", item.ingestion_time)
        available = _utc("availability_time", item.availability_time)
        if not observed <= provider_time <= retrieved <= ingested <= available:
            raise OnChainNormalizationError("Invalid observation chronology.")
        if window_end is not None and window_end > observed:
            raise OnChainNormalizationError("window_end cannot follow observation_time.")
        if previous_time is not None and observed < previous_time:
            raise OnChainNormalizationError("Out-of-order observations.")
        previous_time = observed

        raw_bytes = item.raw_source_bytes
        if (
            type(raw_bytes) is not bytes
            or not 0 < len(raw_bytes) <= policy.maximum_source_bytes
        ):
            raise OnChainNormalizationError("Exact bounded raw source bytes are required.")
        digest = sha256(raw_bytes).hexdigest()
        key = (item.chain_id, item.network_id, event_id, metric_name)
        finality_status = item.finality_status
        fingerprint = (
            digest,
            item.value,
            unit,
            observed,
            provider_time,
            finality_status,
            finality_basis,
            item.block_height,
            block_hash,
            parent_hash,
            window_start,
            window_end,
            reorged_event_id,
            current_provider,
        )
        if key in seen:
            if seen[key] != fingerprint:
                raise OnChainNormalizationError("Conflicting provider event identity.")
            if event_id not in duplicates:
                duplicates.append(event_id)
            continue
        seen[key] = fingerprint

        if item.source_record_id in source_ids:
            raise OnChainNormalizationError("Duplicate source record identity.")
        source_ids.add(item.source_record_id)

        sources.append(
            DataSourceRecord(
                source_record_id=item.source_record_id,
                provider_id=item.provider_id,
                provider_version=item.provider_version,
                provider_event_time=observed,
                retrieval_time=retrieved,
                availability_time=available,
                raw_schema_version=item.raw_schema_version,
                adapter_version=item.adapter_version,
                licensing_reference=item.licensing_reference,
                content_sha256=digest,
            )
        )
        metric = MetricValue(metric_name, item.value, unit)
        on_chain.append(
            OnChainData(
                observation_time=observed,
                availability_time=available,
                source_record_id=item.source_record_id,
                metrics=(metric,),
            )
        )
        identities.append(
            OnChainIdentity(
                source_record_id=item.source_record_id,
                provider_event_id=event_id,
                chain_id=item.chain_id,
                network_id=item.network_id,
                asset_id=item.asset_id,
                metric_name=metric_name,
                finality_status=finality_status,
                finality_basis=finality_basis,
                block_height=item.block_height,
                block_hash=block_hash,
                parent_block_hash=parent_hash,
                window_start=window_start,
                window_end=window_end,
                reorged_event_id=reorged_event_id,
            )
        )

    return NormalizedOnChain(
        source_records=tuple(sources),
        on_chain_data=tuple(on_chain),
        identities=tuple(identities),
        duplicate_event_ids=tuple(duplicates),
    )
