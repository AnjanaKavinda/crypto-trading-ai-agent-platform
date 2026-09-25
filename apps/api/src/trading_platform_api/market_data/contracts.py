from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from typing import TypeVar, cast
from uuid import UUID


class MarketDataContractError(ValueError):
    """Raised when a canonical market-data contract is invalid."""


class DataQualityStatus(StrEnum):
    VALID = "VALID"
    DEGRADED = "DEGRADED"
    STALE = "STALE"
    INCOMPLETE = "INCOMPLETE"
    INVALID = "INVALID"
    UNAVAILABLE = "UNAVAILABLE"


CONTRACT_SCHEMA_VERSION = "1"
_SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")
_T = TypeVar("_T")


def _required_text(field_name: str, value: object) -> str:
    if not isinstance(value, str):
        raise MarketDataContractError(f"{field_name} must be a string.")
    if not value.strip():
        raise MarketDataContractError(f"{field_name} must not be blank.")
    if value != value.strip():
        raise MarketDataContractError(
            f"{field_name} must not contain surrounding whitespace."
        )
    return value


def _uuid(field_name: str, value: object) -> UUID:
    if not isinstance(value, UUID):
        raise MarketDataContractError(f"{field_name} must be a UUID.")
    return value


def _utc_datetime(field_name: str, value: object) -> datetime:
    if not isinstance(value, datetime):
        raise MarketDataContractError(f"{field_name} must be a datetime.")
    if value.tzinfo is None or value.utcoffset() is None:
        raise MarketDataContractError(f"{field_name} must be timezone-aware.")
    return value.astimezone(UTC)


def _decimal(field_name: str, value: object) -> Decimal:
    if not isinstance(value, Decimal) or isinstance(value, bool):
        raise MarketDataContractError(f"{field_name} must be a Decimal.")
    if not value.is_finite():
        raise MarketDataContractError(f"{field_name} must be finite.")
    return value


def _quality_dimension(field_name: str, value: object) -> Decimal:
    dimension = _decimal(field_name, value)
    if dimension < Decimal("0") or dimension > Decimal("1"):
        raise MarketDataContractError(f"{field_name} must be between 0 and 1.")
    return dimension


def _sha256(field_name: str, value: object) -> str:
    digest = _required_text(field_name, value)
    if _SHA256_PATTERN.fullmatch(digest) is None:
        raise MarketDataContractError(
            f"{field_name} must be a lowercase 64-character SHA-256 digest."
        )
    return digest


def _tuple(field_name: str, value: object, *, allow_empty: bool) -> tuple[object, ...]:
    if not isinstance(value, tuple):
        raise MarketDataContractError(f"{field_name} must be a tuple.")
    if not allow_empty and not value:
        raise MarketDataContractError(f"{field_name} must not be empty.")
    return value


def _unique(field_name: str, values: tuple[_T, ...]) -> None:
    try:
        unique_count = len(set(values))
    except TypeError as exc:
        raise MarketDataContractError(
            f"{field_name} values must have stable, hashable identities."
        ) from exc
    if unique_count != len(values):
        raise MarketDataContractError(f"{field_name} must not contain duplicates.")


def _text_tuple(field_name: str, value: object) -> tuple[str, ...]:
    values = _tuple(field_name, value, allow_empty=True)
    normalized = tuple(
        _required_text(f"{field_name}[{index}]", item)
        for index, item in enumerate(values)
    )
    _unique(field_name, normalized)
    return normalized


def _uuid_tuple(
    field_name: str, value: object, *, allow_empty: bool = False
) -> tuple[UUID, ...]:
    values = _tuple(field_name, value, allow_empty=allow_empty)
    normalized = tuple(
        _uuid(f"{field_name}[{index}]", item) for index, item in enumerate(values)
    )
    _unique(field_name, normalized)
    return normalized


def _ordered(
    *, earlier_name: str, earlier: datetime, later_name: str, later: datetime
) -> None:
    if earlier > later:
        raise MarketDataContractError(f"{earlier_name} must not be after {later_name}.")


@dataclass(frozen=True, slots=True)
class MetricValue:
    metric_name: str
    value: Decimal
    unit: str

    def __post_init__(self) -> None:
        _required_text("metric_name", self.metric_name)
        _decimal("value", self.value)
        _required_text("unit", self.unit)


@dataclass(frozen=True, slots=True)
class FeatureValue:
    feature_id: str
    feature_name: str
    value: Decimal
    unit: str
    definition_version: str

    def __post_init__(self) -> None:
        _required_text("feature_id", self.feature_id)
        _required_text("feature_name", self.feature_name)
        _decimal("value", self.value)
        _required_text("unit", self.unit)
        _required_text("definition_version", self.definition_version)


@dataclass(frozen=True, slots=True)
class DatasetVersionReference:
    dataset_id: str
    version: str

    def __post_init__(self) -> None:
        _required_text("dataset_id", self.dataset_id)
        _required_text("version", self.version)


@dataclass(frozen=True, slots=True)
class EventData:
    event_id: str
    event_type: str
    event_time: datetime
    availability_time: datetime
    source_record_id: UUID

    def __post_init__(self) -> None:
        _required_text("event_id", self.event_id)
        _required_text("event_type", self.event_type)
        event_time = _utc_datetime("event_time", self.event_time)
        availability_time = _utc_datetime("availability_time", self.availability_time)
        _uuid("source_record_id", self.source_record_id)
        _ordered(
            earlier_name="event_time",
            earlier=event_time,
            later_name="availability_time",
            later=availability_time,
        )
        object.__setattr__(self, "event_time", event_time)
        object.__setattr__(self, "availability_time", availability_time)


@dataclass(frozen=True, slots=True)
class _MetricObservation:
    observation_time: datetime
    availability_time: datetime
    source_record_id: UUID
    metrics: tuple[MetricValue, ...]

    def __post_init__(self) -> None:
        observation_time = _utc_datetime("observation_time", self.observation_time)
        availability_time = _utc_datetime("availability_time", self.availability_time)
        _uuid("source_record_id", self.source_record_id)
        metrics = _tuple("metrics", self.metrics, allow_empty=False)
        if not all(isinstance(metric, MetricValue) for metric in metrics):
            raise MarketDataContractError(
                "metrics must contain only MetricValue objects."
            )
        typed_metrics = cast(tuple[MetricValue, ...], metrics)
        _unique("metric names", tuple(metric.metric_name for metric in typed_metrics))
        _ordered(
            earlier_name="observation_time",
            earlier=observation_time,
            later_name="availability_time",
            later=availability_time,
        )
        object.__setattr__(self, "observation_time", observation_time)
        object.__setattr__(self, "availability_time", availability_time)


@dataclass(frozen=True, slots=True)
class FundamentalData(_MetricObservation):
    pass


@dataclass(frozen=True, slots=True)
class OnChainData(_MetricObservation):
    pass


@dataclass(frozen=True, slots=True)
class DerivativesData(_MetricObservation):
    pass


@dataclass(frozen=True, slots=True)
class SentimentData(_MetricObservation):
    pass


@dataclass(frozen=True, slots=True)
class MacroData(_MetricObservation):
    pass


@dataclass(frozen=True, slots=True)
class DataSourceRecord:
    source_record_id: UUID
    provider_id: str
    provider_version: str
    provider_event_time: datetime
    retrieval_time: datetime
    availability_time: datetime
    raw_schema_version: str
    adapter_version: str
    licensing_reference: str
    content_sha256: str
    contract_id: str = field(default="C-091", init=False)
    schema_version: str = field(default=CONTRACT_SCHEMA_VERSION, init=False)

    def __post_init__(self) -> None:
        _uuid("source_record_id", self.source_record_id)
        for field_name in (
            "provider_id",
            "provider_version",
            "raw_schema_version",
            "adapter_version",
            "licensing_reference",
        ):
            _required_text(field_name, getattr(self, field_name))
        provider_event_time = _utc_datetime(
            "provider_event_time", self.provider_event_time
        )
        retrieval_time = _utc_datetime("retrieval_time", self.retrieval_time)
        availability_time = _utc_datetime("availability_time", self.availability_time)
        _ordered(
            earlier_name="provider_event_time",
            earlier=provider_event_time,
            later_name="retrieval_time",
            later=retrieval_time,
        )
        _ordered(
            earlier_name="retrieval_time",
            earlier=retrieval_time,
            later_name="availability_time",
            later=availability_time,
        )
        _sha256("content_sha256", self.content_sha256)
        object.__setattr__(self, "provider_event_time", provider_event_time)
        object.__setattr__(self, "retrieval_time", retrieval_time)
        object.__setattr__(self, "availability_time", availability_time)


@dataclass(frozen=True, slots=True)
class MarketData:
    market_data_id: UUID
    instrument_id: str
    venue_id: str
    observation_type: str
    event_time: datetime
    provider_time: datetime
    ingestion_time: datetime
    availability_time: datetime
    source_record_id: UUID
    metrics: tuple[MetricValue, ...]
    contract_id: str = field(default="C-001", init=False)
    schema_version: str = field(default=CONTRACT_SCHEMA_VERSION, init=False)

    def __post_init__(self) -> None:
        _uuid("market_data_id", self.market_data_id)
        _uuid("source_record_id", self.source_record_id)
        for field_name in ("instrument_id", "venue_id", "observation_type"):
            _required_text(field_name, getattr(self, field_name))
        event_time = _utc_datetime("event_time", self.event_time)
        provider_time = _utc_datetime("provider_time", self.provider_time)
        ingestion_time = _utc_datetime("ingestion_time", self.ingestion_time)
        availability_time = _utc_datetime("availability_time", self.availability_time)
        _ordered(
            earlier_name="event_time",
            earlier=event_time,
            later_name="provider_time",
            later=provider_time,
        )
        _ordered(
            earlier_name="provider_time",
            earlier=provider_time,
            later_name="ingestion_time",
            later=ingestion_time,
        )
        _ordered(
            earlier_name="ingestion_time",
            earlier=ingestion_time,
            later_name="availability_time",
            later=availability_time,
        )
        metrics = _tuple("metrics", self.metrics, allow_empty=False)
        if not all(isinstance(metric, MetricValue) for metric in metrics):
            raise MarketDataContractError(
                "metrics must contain only MetricValue objects."
            )
        typed_metrics = cast(tuple[MetricValue, ...], metrics)
        _unique("metric names", tuple(metric.metric_name for metric in typed_metrics))
        object.__setattr__(self, "event_time", event_time)
        object.__setattr__(self, "provider_time", provider_time)
        object.__setattr__(self, "ingestion_time", ingestion_time)
        object.__setattr__(self, "availability_time", availability_time)


@dataclass(frozen=True, slots=True)
class DatasetVersion:
    dataset_id: str
    version: str
    created_at: datetime
    coverage_start: datetime
    coverage_end: datetime
    point_in_time_cutoff: datetime
    source_record_ids: tuple[UUID, ...]
    canonical_schema_version: str
    lineage_sha256: str
    contract_id: str = field(default="C-092", init=False)
    schema_version: str = field(default=CONTRACT_SCHEMA_VERSION, init=False)

    def __post_init__(self) -> None:
        _required_text("dataset_id", self.dataset_id)
        _required_text("version", self.version)
        _required_text("canonical_schema_version", self.canonical_schema_version)
        created_at = _utc_datetime("created_at", self.created_at)
        coverage_start = _utc_datetime("coverage_start", self.coverage_start)
        coverage_end = _utc_datetime("coverage_end", self.coverage_end)
        point_in_time_cutoff = _utc_datetime(
            "point_in_time_cutoff", self.point_in_time_cutoff
        )
        _ordered(
            earlier_name="coverage_start",
            earlier=coverage_start,
            later_name="coverage_end",
            later=coverage_end,
        )
        _ordered(
            earlier_name="coverage_end",
            earlier=coverage_end,
            later_name="point_in_time_cutoff",
            later=point_in_time_cutoff,
        )
        _ordered(
            earlier_name="point_in_time_cutoff",
            earlier=point_in_time_cutoff,
            later_name="created_at",
            later=created_at,
        )
        _uuid_tuple("source_record_ids", self.source_record_ids)
        _sha256("lineage_sha256", self.lineage_sha256)
        object.__setattr__(self, "created_at", created_at)
        object.__setattr__(self, "coverage_start", coverage_start)
        object.__setattr__(self, "coverage_end", coverage_end)
        object.__setattr__(self, "point_in_time_cutoff", point_in_time_cutoff)


_OBSERVATION_TYPES = (
    EventData,
    FundamentalData,
    OnChainData,
    DerivativesData,
    SentimentData,
    MacroData,
)


@dataclass(frozen=True, slots=True)
class MarketSnapshot:
    snapshot_id: UUID
    as_of: datetime
    created_at: datetime
    instrument_id: str
    venue_id: str
    market_data_ids: tuple[UUID, ...]
    source_record_ids: tuple[UUID, ...]
    dataset_version: DatasetVersionReference | None = None
    event_data: tuple[EventData, ...] = ()
    fundamental_data: tuple[FundamentalData, ...] = ()
    on_chain_data: tuple[OnChainData, ...] = ()
    derivatives_data: tuple[DerivativesData, ...] = ()
    sentiment_data: tuple[SentimentData, ...] = ()
    macro_data: tuple[MacroData, ...] = ()
    contract_id: str = field(default="C-002", init=False)
    schema_version: str = field(default=CONTRACT_SCHEMA_VERSION, init=False)

    def __post_init__(self) -> None:
        _uuid("snapshot_id", self.snapshot_id)
        _required_text("instrument_id", self.instrument_id)
        _required_text("venue_id", self.venue_id)
        as_of = _utc_datetime("as_of", self.as_of)
        created_at = _utc_datetime("created_at", self.created_at)
        _ordered(
            earlier_name="as_of",
            earlier=as_of,
            later_name="created_at",
            later=created_at,
        )
        _uuid_tuple("market_data_ids", self.market_data_ids)
        source_record_ids = _uuid_tuple("source_record_ids", self.source_record_ids)
        if self.dataset_version is not None and not isinstance(
            self.dataset_version, DatasetVersionReference
        ):
            raise MarketDataContractError(
                "dataset_version must be a DatasetVersionReference when supplied."
            )

        referenced_sources: list[UUID] = []
        for field_name, expected_type in (
            ("event_data", EventData),
            ("fundamental_data", FundamentalData),
            ("on_chain_data", OnChainData),
            ("derivatives_data", DerivativesData),
            ("sentiment_data", SentimentData),
            ("macro_data", MacroData),
        ):
            observations = _tuple(
                field_name, getattr(self, field_name), allow_empty=True
            )
            if not all(isinstance(item, expected_type) for item in observations):
                raise MarketDataContractError(
                    f"{field_name} contains an invalid embedded value type."
                )
            _unique(field_name, observations)
            if field_name == "event_data":
                typed_events = cast(tuple[EventData, ...], observations)
                _unique("event IDs", tuple(item.event_id for item in typed_events))
            for observation in observations:
                if not isinstance(observation, _OBSERVATION_TYPES):
                    raise MarketDataContractError(
                        f"{field_name} contains an invalid observation."
                    )
                if observation.availability_time > as_of:
                    raise MarketDataContractError(
                        f"{field_name} contains data unavailable at snapshot as_of."
                    )
                referenced_sources.append(observation.source_record_id)

        if not set(referenced_sources).issubset(set(source_record_ids)):
            raise MarketDataContractError(
                "Every embedded value source must appear in source_record_ids."
            )
        object.__setattr__(self, "as_of", as_of)
        object.__setattr__(self, "created_at", created_at)


@dataclass(frozen=True, slots=True)
class DataQualityReport:
    report_id: UUID
    snapshot_id: UUID
    assessed_at: datetime
    required_data_cutoff: datetime
    completeness: Decimal
    freshness: Decimal
    accuracy: Decimal
    consistency: Decimal
    source_reliability: Decimal
    coverage: Decimal
    continuity: Decimal
    status: DataQualityStatus
    missing_fields: tuple[str, ...] = ()
    invalid_record_ids: tuple[str, ...] = ()
    duplicate_record_ids: tuple[str, ...] = ()
    anomalies: tuple[str, ...] = ()
    source_conflicts: tuple[str, ...] = ()
    contract_id: str = field(default="C-003", init=False)
    schema_version: str = field(default=CONTRACT_SCHEMA_VERSION, init=False)

    def __post_init__(self) -> None:
        _uuid("report_id", self.report_id)
        _uuid("snapshot_id", self.snapshot_id)
        assessed_at = _utc_datetime("assessed_at", self.assessed_at)
        required_data_cutoff = _utc_datetime(
            "required_data_cutoff", self.required_data_cutoff
        )
        _ordered(
            earlier_name="required_data_cutoff",
            earlier=required_data_cutoff,
            later_name="assessed_at",
            later=assessed_at,
        )
        for field_name in (
            "completeness",
            "freshness",
            "accuracy",
            "consistency",
            "source_reliability",
            "coverage",
            "continuity",
        ):
            _quality_dimension(field_name, getattr(self, field_name))
        if not isinstance(self.status, DataQualityStatus):
            raise MarketDataContractError("status must be a DataQualityStatus.")
        for field_name in (
            "missing_fields",
            "invalid_record_ids",
            "duplicate_record_ids",
            "anomalies",
            "source_conflicts",
        ):
            _text_tuple(field_name, getattr(self, field_name))
        if self.status is DataQualityStatus.VALID and any(
            getattr(self, field_name)
            for field_name in (
                "missing_fields",
                "invalid_record_ids",
                "duplicate_record_ids",
                "anomalies",
                "source_conflicts",
            )
        ):
            raise MarketDataContractError(
                "VALID status cannot contain unresolved quality findings."
            )
        object.__setattr__(self, "assessed_at", assessed_at)
        object.__setattr__(self, "required_data_cutoff", required_data_cutoff)


@dataclass(frozen=True, slots=True)
class FeatureSet:
    feature_set_id: UUID
    market_snapshot_id: UUID
    calculated_at: datetime
    as_of: datetime
    definition_set_version: str
    features: tuple[FeatureValue, ...]
    source_record_ids: tuple[UUID, ...]
    dataset_version: DatasetVersionReference | None = None
    contract_id: str = field(default="C-004", init=False)
    schema_version: str = field(default=CONTRACT_SCHEMA_VERSION, init=False)

    def __post_init__(self) -> None:
        _uuid("feature_set_id", self.feature_set_id)
        _uuid("market_snapshot_id", self.market_snapshot_id)
        _required_text("definition_set_version", self.definition_set_version)
        as_of = _utc_datetime("as_of", self.as_of)
        calculated_at = _utc_datetime("calculated_at", self.calculated_at)
        _ordered(
            earlier_name="as_of",
            earlier=as_of,
            later_name="calculated_at",
            later=calculated_at,
        )
        features = _tuple("features", self.features, allow_empty=False)
        if not all(isinstance(feature, FeatureValue) for feature in features):
            raise MarketDataContractError(
                "features must contain only FeatureValue objects."
            )
        typed_features = cast(tuple[FeatureValue, ...], features)
        _unique("feature IDs", tuple(feature.feature_id for feature in typed_features))
        _unique(
            "feature names", tuple(feature.feature_name for feature in typed_features)
        )
        _uuid_tuple("source_record_ids", self.source_record_ids)
        if self.dataset_version is not None and not isinstance(
            self.dataset_version, DatasetVersionReference
        ):
            raise MarketDataContractError(
                "dataset_version must be a DatasetVersionReference when supplied."
            )
        object.__setattr__(self, "as_of", as_of)
        object.__setattr__(self, "calculated_at", calculated_at)
