"""Provider-neutral fixture normalization for supplemental derivatives records.

No network I/O or interpretation occurs here. Returned records retain
source-specific semantics in an in-memory sidecar; C-002 v1 cannot persist all
of those distinctions, so callers must not persist canonical metrics alone.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from hashlib import sha256
from uuid import UUID


class SupplementalDerivativesError(ValueError):
    """A sanitized failure of a supplemental derivatives batch."""


class SupplementalDerivativesKind(StrEnum):
    BASIS = "BASIS"
    LIQUIDATION = "LIQUIDATION"
    POSITIONING = "POSITIONING"


class CoverageStatus(StrEnum):
    COMPLETE_WITH_DECLARED_SCOPE = "COMPLETE_WITH_DECLARED_SCOPE"
    PARTIAL = "PARTIAL"
    SAMPLED = "SAMPLED"
    UNKNOWN = "UNKNOWN"


def _text(name: str, value: object, *, maximum: int = 255) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or len(value) > maximum
        or any(ord(char) < 32 for char in value)
    ):
        raise SupplementalDerivativesError(f"{name} must be a bounded identifier.")
    return value


def _utc(name: str, value: object) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise SupplementalDerivativesError(f"{name} must be timezone-aware.")
    if value.utcoffset() is None:
        raise SupplementalDerivativesError(f"{name} must be timezone-aware.")
    return value.astimezone(UTC)


def _positive_int(name: str, value: object, *, maximum: int) -> int:
    if type(value) is not int or not 1 <= value <= maximum:
        raise SupplementalDerivativesError(f"{name} is out of bounds.")
    return value


@dataclass(frozen=True, slots=True)
class SupplementalDerivativesPolicy:
    instrument_id: str
    venue_id: str
    market_type: str
    contract_id: str
    maximum_records: int = 1000
    maximum_source_bytes: int = 1_048_576

    def __post_init__(self) -> None:
        for name in ("instrument_id", "venue_id", "market_type", "contract_id"):
            _text(name, getattr(self, name))
        if self.market_type not in ("PERPETUAL", "DATED_FUTURE"):
            raise SupplementalDerivativesError("Unsupported derivative market type.")
        _positive_int("maximum_records", self.maximum_records, maximum=1000)
        _positive_int("maximum_source_bytes", self.maximum_source_bytes, maximum=1_048_576)


@dataclass(frozen=True, slots=True)
class RawSupplementalDerivativeRecord:
    source_record_id: UUID
    market_data_id: UUID
    provider_event_id: str
    kind: SupplementalDerivativesKind
    instrument_id: str
    venue_id: str
    market_type: str
    contract_id: str
    observation_time: datetime
    provider_time: datetime
    retrieval_time: datetime
    ingestion_time: datetime
    availability_time: datetime
    metric_name: str
    value: Decimal
    unit: str
    coverage_status: CoverageStatus
    coverage_scope: str | None
    window_start: datetime | None
    window_end: datetime | None
    # Basis semantics
    reference_kind: str | None = None
    reference_instrument_id: str | None = None
    reference_time: datetime | None = None
    basis_period_seconds: int | None = None
    # Liquidation semantics; preserve the provider's label verbatim.
    provider_side_label: str | None = None
    provider_side_semantics: str | None = None
    # Positioning semantics
    population: str | None = None
    cohort: str | None = None
    sample_count: int | None = None
    population_count: int | None = None
    provider_id: str = ""
    provider_version: str = ""
    raw_schema_version: str = ""
    adapter_version: str = ""
    licensing_reference: str = ""
    raw_source_bytes: bytes = field(repr=False, default=b"")


@dataclass(frozen=True, slots=True)
class SupplementalDerivativeRecord:
    source_record_id: UUID
    market_data_id: UUID
    provider_event_id: str
    kind: SupplementalDerivativesKind
    instrument_id: str
    venue_id: str
    market_type: str
    contract_id: str
    observation_time: datetime
    provider_time: datetime
    retrieval_time: datetime
    ingestion_time: datetime
    availability_time: datetime
    metric_name: str
    value: Decimal
    unit: str
    coverage_status: CoverageStatus
    coverage_scope: str | None
    window_start: datetime | None
    window_end: datetime | None
    reference_kind: str | None
    reference_instrument_id: str | None
    reference_time: datetime | None
    basis_period_seconds: int | None
    provider_side_label: str | None
    provider_side_semantics: str | None
    population: str | None
    cohort: str | None
    sample_count: int | None
    population_count: int | None
    provider_id: str
    provider_version: str
    raw_schema_version: str
    adapter_version: str
    licensing_reference: str
    content_sha256: str


@dataclass(frozen=True, slots=True)
class NormalizedSupplementalDerivatives:
    records: tuple[SupplementalDerivativeRecord, ...]
    duplicate_event_ids: tuple[str, ...]


def normalize_supplemental_derivatives(
    observations: tuple[RawSupplementalDerivativeRecord, ...],
    policy: SupplementalDerivativesPolicy,
) -> NormalizedSupplementalDerivatives:
    """Validate bounded basis, liquidation, and positioning fixture batches.

    This preserves source-declared labels and coverage. It does not calculate
    basis, annualize values, convert side labels to long/short, aggregate
    venues, or infer completeness.
    """
    if type(policy) is not SupplementalDerivativesPolicy:
        raise SupplementalDerivativesError("Invalid derivatives policy.")
    if type(observations) is not tuple or len(observations) > policy.maximum_records:
        raise SupplementalDerivativesError("Observation batch exceeds policy.")

    records: list[SupplementalDerivativeRecord] = []
    duplicates: list[str] = []
    seen: dict[tuple[SupplementalDerivativesKind, str], tuple[object, ...]] = {}
    source_ids: set[UUID] = set()
    market_ids: set[UUID] = set()
    previous_time: datetime | None = None
    provider: tuple[str, ...] | None = None

    for item in observations:
        if type(item) is not RawSupplementalDerivativeRecord:
            raise SupplementalDerivativesError("Invalid observation type.")
        if not isinstance(item.source_record_id, UUID) or not isinstance(
            item.market_data_id, UUID
        ):
            raise SupplementalDerivativesError("Invalid canonical identity.")
        for name in ("instrument_id", "venue_id", "market_type", "contract_id"):
            if _text(name, getattr(item, name)) != getattr(policy, name):
                raise SupplementalDerivativesError(f"Mismatched {name}.")
        event_id = _text("provider_event_id", item.provider_event_id)
        if type(item.kind) is not SupplementalDerivativesKind:
            raise SupplementalDerivativesError("Unsupported derivatives record kind.")
        if type(item.coverage_status) is not CoverageStatus:
            raise SupplementalDerivativesError("Coverage status must be explicit.")
        if type(item.value) is not Decimal or not item.value.is_finite():
            raise SupplementalDerivativesError("Value must be a finite Decimal.")
        metric_name = _text("metric_name", item.metric_name)
        unit = _text("unit", item.unit)

        for name in (
            "provider_id",
            "provider_version",
            "raw_schema_version",
            "adapter_version",
            "licensing_reference",
        ):
            _text(name, getattr(item, name))
        current_provider = (
            item.provider_id,
            item.provider_version,
            item.raw_schema_version,
            item.adapter_version,
            item.licensing_reference,
        )
        if provider is not None and provider != current_provider:
            raise SupplementalDerivativesError("Mixed provider identity.")
        provider = current_provider

        scope = (
            _text("coverage_scope", item.coverage_scope)
            if item.coverage_scope is not None
            else None
        )
        if (
            item.coverage_status is CoverageStatus.COMPLETE_WITH_DECLARED_SCOPE
            and scope is None
        ):
            raise SupplementalDerivativesError(
                "Complete coverage requires a declared scope."
            )
        window_start = (
            _utc("window_start", item.window_start)
            if item.window_start is not None
            else None
        )
        window_end = (
            _utc("window_end", item.window_end)
            if item.window_end is not None
            else None
        )
        if (window_start is None) != (window_end is None):
            raise SupplementalDerivativesError("Window bounds must be supplied together.")
        if window_start is not None and window_end is not None:
            if window_start >= window_end:
                raise SupplementalDerivativesError("Invalid coverage window.")

        reference_kind = (
            _text("reference_kind", item.reference_kind)
            if item.reference_kind is not None
            else None
        )
        reference_instrument_id = (
            _text("reference_instrument_id", item.reference_instrument_id)
            if item.reference_instrument_id is not None
            else None
        )
        reference_time = (
            _utc("reference_time", item.reference_time)
            if item.reference_time is not None
            else None
        )
        basis_period_seconds = item.basis_period_seconds
        side_label = (
            _text("provider_side_label", item.provider_side_label)
            if item.provider_side_label is not None
            else None
        )
        side_semantics = (
            _text("provider_side_semantics", item.provider_side_semantics)
            if item.provider_side_semantics is not None
            else None
        )
        population = (
            _text("population", item.population) if item.population is not None else None
        )
        cohort = _text("cohort", item.cohort) if item.cohort is not None else None

        if item.kind is SupplementalDerivativesKind.BASIS:
            if (
                reference_kind is None
                or reference_instrument_id is None
                or reference_time is None
                or basis_period_seconds is None
            ):
                raise SupplementalDerivativesError(
                    "Basis requires explicit reference and period semantics."
                )
            _positive_int("basis_period_seconds", basis_period_seconds, maximum=31_536_000)
            if side_label is not None or population is not None or cohort is not None:
                raise SupplementalDerivativesError("Unexpected non-basis semantics.")
        elif item.kind is SupplementalDerivativesKind.LIQUIDATION:
            if side_label is None or side_semantics is None or window_start is None:
                raise SupplementalDerivativesError(
                    "Liquidations require source side semantics and a coverage window."
                )
            if item.value < 0:
                raise SupplementalDerivativesError("Liquidation quantity must be non-negative.")
            if population is not None or reference_instrument_id is not None:
                raise SupplementalDerivativesError("Unexpected non-liquidation semantics.")
        else:
            if (
                population is None
                or cohort is None
                or window_start is None
                or item.sample_count is None
                or item.population_count is None
            ):
                raise SupplementalDerivativesError(
                    "Positioning requires population, cohort, window, and counts."
                )
            if (
                type(item.sample_count) is not int
                or type(item.population_count) is not int
                or item.sample_count < 0
                or item.population_count < 0
                or item.sample_count > item.population_count
            ):
                raise SupplementalDerivativesError("Invalid positioning coverage counts.")
            if side_label is not None or reference_instrument_id is not None:
                raise SupplementalDerivativesError("Unexpected non-positioning semantics.")

        observed = _utc("observation_time", item.observation_time)
        provider_time = _utc("provider_time", item.provider_time)
        retrieved = _utc("retrieval_time", item.retrieval_time)
        ingested = _utc("ingestion_time", item.ingestion_time)
        available = _utc("availability_time", item.availability_time)
        if not observed <= provider_time <= retrieved <= ingested <= available:
            raise SupplementalDerivativesError("Invalid observation chronology.")
        if previous_time is not None and observed < previous_time:
            raise SupplementalDerivativesError("Out-of-order observations.")
        if window_end is not None and window_end > retrieved:
            raise SupplementalDerivativesError("Coverage window cannot follow retrieval.")
        if (
            item.kind is not SupplementalDerivativesKind.LIQUIDATION
            and window_end is not None
            and window_end > observed
        ):
            raise SupplementalDerivativesError(
                "Coverage window cannot end after its observation."
            )
        if item.kind is SupplementalDerivativesKind.LIQUIDATION:
            if (
                window_start is None
                or window_end is None
                or not window_start <= observed <= window_end
            ):
                raise SupplementalDerivativesError(
                    "Liquidation event must fall within its coverage window."
                )
        if reference_time is not None and reference_time > observed:
            raise SupplementalDerivativesError("Basis reference cannot be from the future.")

        raw = item.raw_source_bytes
        if type(raw) is not bytes or not 0 < len(raw) <= policy.maximum_source_bytes:
            raise SupplementalDerivativesError("Exact bounded raw source bytes required.")
        digest = sha256(raw).hexdigest()
        key = (item.kind, event_id)
        fingerprint = (
            digest,
            item.source_record_id,
            item.market_data_id,
            item.instrument_id,
            item.venue_id,
            item.market_type,
            item.contract_id,
            observed,
            provider_time,
            retrieved,
            ingested,
            available,
            item.value,
            unit,
            item.coverage_status,
            scope,
            window_start,
            window_end,
            reference_kind,
            reference_instrument_id,
            reference_time,
            basis_period_seconds,
            side_label,
            side_semantics,
            population,
            cohort,
            item.sample_count,
            item.population_count,
            current_provider,
        )
        if key in seen:
            if seen[key] != fingerprint:
                raise SupplementalDerivativesError(
                    "Conflicting provider event identity."
                )
            if event_id not in duplicates:
                duplicates.append(event_id)
            continue
        seen[key] = fingerprint
        if item.source_record_id in source_ids or item.market_data_id in market_ids:
            raise SupplementalDerivativesError("Duplicate canonical identity.")
        source_ids.add(item.source_record_id)
        market_ids.add(item.market_data_id)
        previous_time = observed

        records.append(
            SupplementalDerivativeRecord(
                source_record_id=item.source_record_id,
                market_data_id=item.market_data_id,
                provider_event_id=event_id,
                kind=item.kind,
                instrument_id=item.instrument_id,
                venue_id=item.venue_id,
                market_type=item.market_type,
                contract_id=item.contract_id,
                observation_time=observed,
                provider_time=provider_time,
                retrieval_time=retrieved,
                ingestion_time=ingested,
                availability_time=available,
                metric_name=metric_name,
                value=item.value,
                unit=unit,
                coverage_status=item.coverage_status,
                coverage_scope=scope,
                window_start=window_start,
                window_end=window_end,
                reference_kind=reference_kind,
                reference_instrument_id=reference_instrument_id,
                reference_time=reference_time,
                basis_period_seconds=basis_period_seconds,
                provider_side_label=side_label,
                provider_side_semantics=side_semantics,
                population=population,
                cohort=cohort,
                sample_count=item.sample_count,
                population_count=item.population_count,
                provider_id=item.provider_id,
                provider_version=item.provider_version,
                raw_schema_version=item.raw_schema_version,
                adapter_version=item.adapter_version,
                licensing_reference=item.licensing_reference,
                content_sha256=digest,
            )
        )

    return NormalizedSupplementalDerivatives(tuple(records), tuple(duplicates))
