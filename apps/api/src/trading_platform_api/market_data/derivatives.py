"""Bounded, provider-neutral funding and open-interest normalization.

This module has no network, execution, or trading-decision authority.
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
    DerivativesData,
    MarketData,
    MetricValue,
)
from trading_platform_api.market_data.providers import ProviderDataKind


class DerivativesNormalizationError(ValueError):
    """A sanitized failure of the complete candidate batch."""


class OpenInterestUnit(StrEnum):
    CONTRACTS = "contracts"
    BASE_ASSET = "base_asset"
    QUOTE_ASSET = "quote_asset"


def _identifier(name: str, value: object) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or len(value) > 255
        or any(ord(char) < 32 for char in value)
    ):
        raise DerivativesNormalizationError(f"{name} must be a bounded identifier.")
    return value


def _utc(name: str, value: object) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise DerivativesNormalizationError(f"{name} must be timezone-aware.")
    if value.utcoffset() is None:
        raise DerivativesNormalizationError(f"{name} must be timezone-aware.")
    return value.astimezone(UTC)


@dataclass(frozen=True, slots=True)
class DerivativesPolicy:
    instrument_id: str
    venue_id: str
    market_type: str
    contract_id: str
    maximum_records: int = 1000
    maximum_source_bytes: int = 1_048_576

    def __post_init__(self) -> None:
        for name in ("instrument_id", "venue_id", "market_type", "contract_id"):
            _identifier(name, getattr(self, name))
        if self.market_type not in ("PERPETUAL", "DATED_FUTURE"):
            raise DerivativesNormalizationError("Unsupported derivative market type.")
        if (
            type(self.maximum_records) is not int
            or not 1 <= self.maximum_records <= 1000
        ):
            raise DerivativesNormalizationError("maximum_records is out of bounds.")
        if (
            type(self.maximum_source_bytes) is not int
            or not 1 <= self.maximum_source_bytes <= 1_048_576
        ):
            raise DerivativesNormalizationError(
                "maximum_source_bytes is out of bounds."
            )


@dataclass(frozen=True, slots=True)
class RawDerivativesObservation:
    source_record_id: UUID
    market_data_id: UUID
    provider_event_id: str
    instrument_id: str
    venue_id: str
    market_type: str
    contract_id: str
    data_kind: ProviderDataKind
    observation_time: datetime
    value: Decimal
    open_interest_unit: OpenInterestUnit | None
    funding_interval_seconds: int | None
    provider_id: str
    provider_version: str
    raw_schema_version: str
    adapter_version: str
    licensing_reference: str
    raw_source_bytes: bytes = field(repr=False)
    retrieval_time: datetime
    ingestion_time: datetime
    availability_time: datetime


@dataclass(frozen=True, slots=True)
class DerivativesIdentity:
    provider_event_id: str
    contract_id: str
    market_type: str
    data_kind: ProviderDataKind
    source_record_id: UUID
    market_data_id: UUID


@dataclass(frozen=True, slots=True)
class NormalizedDerivatives:
    source_records: tuple[DataSourceRecord, ...]
    market_data: tuple[MarketData, ...]
    derivatives_data: tuple[DerivativesData, ...]
    identities: tuple[DerivativesIdentity, ...]
    duplicate_event_ids: tuple[str, ...]


def normalize_derivatives(
    observations: tuple[RawDerivativesObservation, ...], policy: DerivativesPolicy
) -> NormalizedDerivatives:
    """Normalize a finite batch; duplicates are tracked only within this call.

    No continuity, exchange-wide coverage, or durable deduplication is inferred.
    """
    if type(observations) is not tuple or len(observations) > policy.maximum_records:
        raise DerivativesNormalizationError("Observation batch exceeds policy.")
    sources: list[DataSourceRecord] = []
    market: list[MarketData] = []
    derivatives: list[DerivativesData] = []
    identities: list[DerivativesIdentity] = []
    duplicates: list[str] = []
    seen: dict[tuple[ProviderDataKind, str], tuple[object, ...]] = {}
    source_ids: set[UUID] = set()
    market_ids: set[UUID] = set()
    previous_time: datetime | None = None
    provider: tuple[str, ...] | None = None
    for item in observations:
        if not isinstance(item, RawDerivativesObservation):
            raise DerivativesNormalizationError("Invalid observation type.")
        if not isinstance(item.source_record_id, UUID) or not isinstance(
            item.market_data_id, UUID
        ):
            raise DerivativesNormalizationError("Invalid canonical identity.")
        for name in ("instrument_id", "venue_id", "market_type", "contract_id"):
            if _identifier(name, getattr(item, name)) != getattr(policy, name):
                raise DerivativesNormalizationError(f"Mismatched {name}.")
        event_id = _identifier("provider_event_id", item.provider_event_id)
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
            raise DerivativesNormalizationError("Mixed provider identity.")
        provider = current_provider
        if type(item.data_kind) is not ProviderDataKind or item.data_kind not in (
            ProviderDataKind.FUNDING,
            ProviderDataKind.OPEN_INTEREST,
        ):
            raise DerivativesNormalizationError("Unsupported derivatives kind.")
        if type(item.value) is not Decimal or not item.value.is_finite():
            raise DerivativesNormalizationError("Value must be a finite Decimal.")
        metrics: tuple[MetricValue, ...]
        if item.data_kind is ProviderDataKind.FUNDING:
            if (
                item.market_type != "PERPETUAL"
                or item.open_interest_unit is not None
                or type(item.funding_interval_seconds) is not int
                or not 1 <= item.funding_interval_seconds <= 604800
            ):
                raise DerivativesNormalizationError(
                    "Funding interval or unit is invalid."
                )
            metrics = (
                MetricValue("funding_rate", item.value, "fraction_per_interval"),
                MetricValue(
                    "funding_interval_seconds",
                    Decimal(item.funding_interval_seconds),
                    "seconds",
                ),
            )
        else:
            if (
                not isinstance(item.open_interest_unit, OpenInterestUnit)
                or item.funding_interval_seconds is not None
                or item.value < 0
            ):
                raise DerivativesNormalizationError(
                    "Open interest unit or value is invalid."
                )
            metrics = (
                MetricValue("open_interest", item.value, item.open_interest_unit.value),
            )
        observed = _utc("observation_time", item.observation_time)
        retrieved = _utc("retrieval_time", item.retrieval_time)
        ingested = _utc("ingestion_time", item.ingestion_time)
        available = _utc("availability_time", item.availability_time)
        if not observed <= retrieved <= ingested <= available:
            raise DerivativesNormalizationError("Invalid observation chronology.")
        if previous_time is not None and observed < previous_time:
            raise DerivativesNormalizationError("Out-of-order observations.")
        if (
            type(item.raw_source_bytes) is not bytes
            or not 0 < len(item.raw_source_bytes) <= policy.maximum_source_bytes
        ):
            raise DerivativesNormalizationError("Exact bounded raw source required.")
        digest = sha256(item.raw_source_bytes).hexdigest()
        key = (item.data_kind, event_id)
        fingerprint = (digest, observed, item.value, metrics, current_provider)
        if key in seen:
            if seen[key] != fingerprint:
                raise DerivativesNormalizationError(
                    "Conflicting provider event identity."
                )
            if event_id not in duplicates:
                duplicates.append(event_id)
            continue
        seen[key] = fingerprint
        if item.source_record_id in source_ids or item.market_data_id in market_ids:
            raise DerivativesNormalizationError("Duplicate canonical identity.")
        source_ids.add(item.source_record_id)
        market_ids.add(item.market_data_id)
        previous_time = observed
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
        market.append(
            MarketData(
                market_data_id=item.market_data_id,
                instrument_id=item.instrument_id,
                venue_id=item.venue_id,
                observation_type=item.data_kind.value,
                event_time=observed,
                provider_time=observed,
                ingestion_time=ingested,
                availability_time=available,
                source_record_id=item.source_record_id,
                metrics=metrics,
            )
        )
        derivatives.append(
            DerivativesData(
                observation_time=observed,
                availability_time=available,
                source_record_id=item.source_record_id,
                metrics=metrics,
            )
        )
        identities.append(
            DerivativesIdentity(
                provider_event_id=event_id,
                contract_id=item.contract_id,
                market_type=item.market_type,
                data_kind=item.data_kind,
                source_record_id=item.source_record_id,
                market_data_id=item.market_data_id,
            )
        )
    return NormalizedDerivatives(
        tuple(sources),
        tuple(market),
        tuple(derivatives),
        tuple(identities),
        tuple(duplicates),
    )
