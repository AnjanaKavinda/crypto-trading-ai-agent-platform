"""Deterministic trade/tick normalization without provider or execution authority."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from hashlib import sha256
from uuid import UUID

from trading_platform_api.market_data.contracts import (
    DataSourceRecord,
    MarketData,
    MetricValue,
)
from trading_platform_api.market_data.providers import ProviderDataKind


class TradeTickNormalizationError(ValueError):
    """Sanitized rejection of an invalid entire trade/tick batch."""


class ReportedSide(StrEnum):
    BUY = "BUY"
    SELL = "SELL"
    UNKNOWN = "UNKNOWN"


class SideSemantics(StrEnum):
    AGGRESSOR = "AGGRESSOR"
    MAKER = "MAKER"
    UNKNOWN = "UNKNOWN"


_MAX_RECORDS = 10_000
_MAX_SOURCE_BYTES = 1_048_576
_SENSITIVE_TEXT = re.compile(
    r"(?i)(://[^/\s:@]+:[^/\s@]+@|\b(?:token|password|secret|api[-_ ]?key)\s*[:=]|\bbearer\s+\S+)"
)


def _text(name: str, value: object) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or len(value) > 255
        or any(ord(char) < 32 for char in value)
        or _SENSITIVE_TEXT.search(value)
    ):
        raise TradeTickNormalizationError(f"{name} must be a bounded identifier.")
    return value


def _utc(name: str, value: object) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise TradeTickNormalizationError(f"{name} must be timezone-aware.")
    if value.utcoffset() is None:
        raise TradeTickNormalizationError(f"{name} must be timezone-aware.")
    return value.astimezone(UTC)


def _uuid(name: str, value: object) -> None:
    if not isinstance(value, UUID):
        raise TradeTickNormalizationError(f"{name} must be a UUID.")


def _decimal(name: str, value: object, places: int) -> Decimal:
    if not isinstance(value, Decimal) or not value.is_finite() or value <= 0:
        raise TradeTickNormalizationError(f"{name} must be a positive finite Decimal.")
    exponent = value.as_tuple().exponent
    if not isinstance(exponent, int) or exponent < -places:
        raise TradeTickNormalizationError(f"{name} exceeds configured precision.")
    return value


@dataclass(frozen=True, slots=True)
class TradeTickPolicy:
    instrument_id: str
    venue_id: str
    data_kind: ProviderDataKind
    price_unit: str
    quantity_unit: str
    price_places: int
    quantity_places: int
    maximum_records: int = 1000
    maximum_source_bytes: int = _MAX_SOURCE_BYTES

    def __post_init__(self) -> None:
        for name in ("instrument_id", "venue_id", "price_unit", "quantity_unit"):
            _text(name, getattr(self, name))
        if type(self.data_kind) is not ProviderDataKind or self.data_kind not in (
            ProviderDataKind.TRADE,
            ProviderDataKind.TICK,
        ):
            raise TradeTickNormalizationError("data_kind must be TRADE or TICK.")
        for name in ("price_places", "quantity_places"):
            value = getattr(self, name)
            if type(value) is not int or not 0 <= value <= 18:
                raise TradeTickNormalizationError(
                    f"{name} must be an integer in [0, 18]."
                )
        if (
            type(self.maximum_records) is not int
            or not 1 <= self.maximum_records <= _MAX_RECORDS
        ):
            raise TradeTickNormalizationError("maximum_records is out of bounds.")
        if (
            type(self.maximum_source_bytes) is not int
            or not 1 <= self.maximum_source_bytes <= _MAX_SOURCE_BYTES
        ):
            raise TradeTickNormalizationError("maximum_source_bytes is out of bounds.")


@dataclass(frozen=True, slots=True)
class RawTradeTick:
    source_record_id: UUID
    market_data_id: UUID
    provider_event_id: str
    instrument_id: str
    venue_id: str
    data_kind: ProviderDataKind
    event_time: datetime
    price: Decimal
    quantity: Decimal | None
    price_unit: str
    quantity_unit: str
    reported_side: ReportedSide
    side_semantics: SideSemantics
    sequence: int | None
    sequence_scope: str | None
    raw_source_bytes: bytes = field(repr=False)
    provider_id: str
    provider_version: str
    raw_schema_version: str
    adapter_version: str
    licensing_reference: str
    retrieval_time: datetime
    ingestion_time: datetime
    availability_time: datetime


@dataclass(frozen=True, slots=True)
class TradeTickIdentity:
    provider_event_id: str
    source_record_id: UUID
    market_data_id: UUID
    sequence: int | None
    sequence_scope: str | None
    reported_side: ReportedSide
    side_semantics: SideSemantics
    aggressor_side: ReportedSide


@dataclass(frozen=True, slots=True)
class TradeTickQuality:
    duplicate_event_ids: tuple[str, ...]
    unknown_aggressor_event_ids: tuple[str, ...]
    sequence_verified: bool
    empty: bool


@dataclass(frozen=True, slots=True)
class NormalizedTradeTicks:
    data_kind: ProviderDataKind
    source_records: tuple[DataSourceRecord, ...]
    market_data: tuple[MarketData, ...]
    identities: tuple[TradeTickIdentity, ...]
    quality: TradeTickQuality


def normalize_trade_ticks(
    events: tuple[RawTradeTick, ...], policy: TradeTickPolicy
) -> NormalizedTradeTicks:
    """Return canonical records and the inseparable provider-identity handoff.

    Exact duplicates are suppressed only within this call. Durable idempotency
    and provider parsing belong to later integration work.
    """
    if not isinstance(policy, TradeTickPolicy):
        raise TradeTickNormalizationError("policy must be a TradeTickPolicy.")
    if not isinstance(events, tuple) or not all(
        type(event) is RawTradeTick for event in events
    ):
        raise TradeTickNormalizationError("events must be a tuple of RawTradeTick.")
    if len(events) > policy.maximum_records:
        raise TradeTickNormalizationError("Batch exceeds maximum_records.")

    sources: list[DataSourceRecord] = []
    observations: list[MarketData] = []
    identities: list[TradeTickIdentity] = []
    duplicates: list[str] = []
    unknown_sides: list[str] = []
    seen: dict[str, tuple[object, ...]] = {}
    source_ids: set[UUID] = set()
    market_ids: set[UUID] = set()
    provider_identity: tuple[str, str, str, str, str] | None = None
    previous_time: datetime | None = None
    previous_sequence: int | None = None
    sequence_scope: str | None = None
    has_sequence: bool | None = None

    for index, event in enumerate(events):
        _uuid("source_record_id", event.source_record_id)
        _uuid("market_data_id", event.market_data_id)
        event_id = _text("provider_event_id", event.provider_event_id)
        for name, expected in (
            ("instrument_id", policy.instrument_id),
            ("venue_id", policy.venue_id),
            ("price_unit", policy.price_unit),
            ("quantity_unit", policy.quantity_unit),
        ):
            if _text(name, getattr(event, name)) != expected:
                raise TradeTickNormalizationError(
                    f"Event {index} has mismatched {name}."
                )
        if event.data_kind is not policy.data_kind:
            raise TradeTickNormalizationError("Mixed or unsupported data_kind.")
        for name in (
            "provider_id",
            "provider_version",
            "raw_schema_version",
            "adapter_version",
            "licensing_reference",
        ):
            _text(name, getattr(event, name))
        current_provider = (
            event.provider_id,
            event.provider_version,
            event.raw_schema_version,
            event.adapter_version,
            event.licensing_reference,
        )
        if provider_identity is not None and current_provider != provider_identity:
            raise TradeTickNormalizationError("Mixed source schema or identity.")
        provider_identity = current_provider
        if not isinstance(event.reported_side, ReportedSide) or not isinstance(
            event.side_semantics, SideSemantics
        ):
            raise TradeTickNormalizationError("Invalid side or side semantics.")
        if event.sequence is not None and (
            type(event.sequence) is not int or event.sequence < 0
        ):
            raise TradeTickNormalizationError("sequence must be non-negative.")
        if (event.sequence is None) != (event.sequence_scope is None):
            raise TradeTickNormalizationError(
                "sequence and sequence_scope must be supplied together."
            )
        if event.sequence_scope is not None:
            _text("sequence_scope", event.sequence_scope)
        event_time = _utc("event_time", event.event_time)
        retrieval = _utc("retrieval_time", event.retrieval_time)
        ingestion = _utc("ingestion_time", event.ingestion_time)
        available = _utc("availability_time", event.availability_time)
        if not event_time <= retrieval <= ingestion <= available:
            raise TradeTickNormalizationError("Invalid source timestamp chronology.")
        price = _decimal("price", event.price, policy.price_places)
        if event.quantity is None:
            if policy.data_kind is ProviderDataKind.TRADE:
                raise TradeTickNormalizationError("TRADE requires quantity.")
            quantity = None
        else:
            quantity = _decimal("quantity", event.quantity, policy.quantity_places)
        if (
            type(event.raw_source_bytes) is not bytes
            or not 0 < len(event.raw_source_bytes) <= policy.maximum_source_bytes
        ):
            raise TradeTickNormalizationError(
                "Exact bounded raw_source_bytes required."
            )
        digest = sha256(event.raw_source_bytes).hexdigest()
        fingerprint: tuple[object, ...] = (
            digest,
            event_time,
            price,
            quantity,
            event.reported_side,
            event.side_semantics,
            event.sequence,
            event.sequence_scope,
            current_provider,
        )
        if event_id in seen:
            if seen[event_id] != fingerprint:
                raise TradeTickNormalizationError(
                    "Conflicting provider event identity."
                )
            if event_id not in duplicates:
                duplicates.append(event_id)
            continue
        seen[event_id] = fingerprint
        if has_sequence is not None and (event.sequence is not None) != has_sequence:
            raise TradeTickNormalizationError("Mixed sequence availability.")
        has_sequence = event.sequence is not None
        if event.sequence_scope is not None:
            if sequence_scope is not None and event.sequence_scope != sequence_scope:
                raise TradeTickNormalizationError("Mixed sequence scope.")
            sequence_scope = event.sequence_scope
        if event.source_record_id in source_ids or event.market_data_id in market_ids:
            raise TradeTickNormalizationError("Duplicate canonical identity.")
        source_ids.add(event.source_record_id)
        market_ids.add(event.market_data_id)
        if previous_time is not None and event_time < previous_time:
            raise TradeTickNormalizationError("Out-of-order event time.")
        previous_time = event_time
        if event.sequence is not None:
            if (
                previous_sequence is not None
                and event.sequence != previous_sequence + 1
            ):
                raise TradeTickNormalizationError("Sequence gap or reversal.")
            previous_sequence = event.sequence

        aggressor_side = (
            event.reported_side
            if event.side_semantics is SideSemantics.AGGRESSOR
            else ReportedSide.UNKNOWN
        )
        if aggressor_side is ReportedSide.UNKNOWN:
            unknown_sides.append(event_id)
        metrics = [MetricValue("price", price, policy.price_unit)]
        if quantity is not None:
            metrics.append(MetricValue("quantity", quantity, policy.quantity_unit))
        if aggressor_side is not ReportedSide.UNKNOWN:
            sign = 1 if aggressor_side is ReportedSide.BUY else -1
            metrics.append(MetricValue("aggressor_sign", Decimal(sign), "sign"))
        sources.append(
            DataSourceRecord(
                source_record_id=event.source_record_id,
                provider_id=event.provider_id,
                provider_version=event.provider_version,
                provider_event_time=event_time,
                retrieval_time=retrieval,
                availability_time=available,
                raw_schema_version=event.raw_schema_version,
                adapter_version=event.adapter_version,
                licensing_reference=event.licensing_reference,
                content_sha256=digest,
            )
        )
        observations.append(
            MarketData(
                market_data_id=event.market_data_id,
                instrument_id=policy.instrument_id,
                venue_id=policy.venue_id,
                observation_type=policy.data_kind.value,
                event_time=event_time,
                provider_time=event_time,
                ingestion_time=ingestion,
                availability_time=available,
                source_record_id=event.source_record_id,
                metrics=tuple(metrics),
            )
        )
        identities.append(
            TradeTickIdentity(
                provider_event_id=event_id,
                source_record_id=event.source_record_id,
                market_data_id=event.market_data_id,
                sequence=event.sequence,
                sequence_scope=event.sequence_scope,
                reported_side=event.reported_side,
                side_semantics=event.side_semantics,
                aggressor_side=aggressor_side,
            )
        )
    return NormalizedTradeTicks(
        data_kind=policy.data_kind,
        source_records=tuple(sources),
        market_data=tuple(observations),
        identities=tuple(identities),
        quality=TradeTickQuality(
            duplicate_event_ids=tuple(duplicates),
            unknown_aggressor_event_ids=tuple(unknown_sides),
            sequence_verified=bool(has_sequence),
            empty=not events,
        ),
    )
