"""Additive, immutable historical-evidence contracts approved in Issue #45."""

from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID

from trading_platform_api.market_data.contracts import (
    CONTRACT_SCHEMA_VERSION,
    DatasetVersionReference,
    MarketData,
    MarketDataContractError,
    _required_text,
    _sha256,
    _text_tuple,
    _utc_datetime,
    _uuid,
    _uuid_tuple,
)


def _times(record: object, names: tuple[str, ...]) -> None:
    values = tuple(_utc_datetime(name, getattr(record, name)) for name in names)
    if any(left > right for left, right in zip(values, values[1:])):
        raise MarketDataContractError("Historical evidence chronology is invalid.")
    for name, value in zip(names, values):
        object.__setattr__(record, name, value)


@dataclass(frozen=True, slots=True)
class HistoricalUniverse:
    universe_id: str
    version: str
    definition_version: str
    venue_id: str
    effective_from: datetime
    effective_until: datetime
    publication_time: datetime
    ingestion_time: datetime
    availability_time: datetime
    instrument_ids: tuple[str, ...]
    source_record_ids: tuple[UUID, ...]
    complete: bool
    contract_id: str = field(default="C-101", init=False)
    schema_version: str = field(default=CONTRACT_SCHEMA_VERSION, init=False)

    def __post_init__(self) -> None:
        for name in ("universe_id", "version", "definition_version", "venue_id"):
            _required_text(name, getattr(self, name))
        _times(self, ("effective_from", "effective_until"))
        _times(self, ("publication_time", "ingestion_time", "availability_time"))
        if self.effective_from == self.effective_until:
            raise MarketDataContractError(
                "Universe effective interval must be nonempty."
            )
        _text_tuple("instrument_ids", self.instrument_ids)
        _uuid_tuple("source_record_ids", self.source_record_ids)
        if type(self.complete) is not bool or not self.complete:
            raise MarketDataContractError("Complete universe evidence is required.")
        object.__setattr__(self, "instrument_ids", tuple(sorted(self.instrument_ids)))
        object.__setattr__(
            self, "source_record_ids", tuple(sorted(self.source_record_ids, key=str))
        )


@dataclass(frozen=True, slots=True)
class ObservationRevision:
    revision_id: UUID
    provider_id: str
    observation_key: str
    supersedes_revision_id: UUID | None
    observation: MarketData
    publication_time: datetime
    ingestion_time: datetime
    availability_time: datetime
    finalized_interval_end: datetime | None = None
    ordering_policy: str = "explicit-supersedes-v1"
    contract_id: str = field(default="C-102", init=False)
    schema_version: str = field(default=CONTRACT_SCHEMA_VERSION, init=False)

    def __post_init__(self) -> None:
        _uuid("revision_id", self.revision_id)
        for name in ("provider_id", "observation_key"):
            _required_text(name, getattr(self, name))
        if self.supersedes_revision_id is not None:
            _uuid("supersedes_revision_id", self.supersedes_revision_id)
            if self.supersedes_revision_id == self.revision_id:
                raise MarketDataContractError("Revision cannot supersede itself.")
        if type(self.observation) is not MarketData:
            raise MarketDataContractError("Revision requires C-001 evidence.")
        if self.ordering_policy != "explicit-supersedes-v1":
            raise MarketDataContractError("Unsupported revision ordering policy.")
        _times(self, ("publication_time", "ingestion_time", "availability_time"))
        if (
            self.observation.provider_time > self.publication_time
            or self.observation.ingestion_time > self.ingestion_time
            or self.observation.availability_time > self.availability_time
        ):
            raise MarketDataContractError("Revision predates its observation evidence.")
        if self.observation.observation_type == "OHLCV":
            closed = _utc_datetime(
                "finalized_interval_end", self.finalized_interval_end
            )
            if not self.observation.event_time < closed <= self.publication_time:
                raise MarketDataContractError("Invalid closed candle evidence.")
            object.__setattr__(self, "finalized_interval_end", closed)
        elif self.finalized_interval_end is not None:
            raise MarketDataContractError("Finality interval is only valid for OHLCV.")


@dataclass(frozen=True, slots=True)
class HistoricalEvidencePin:
    evidence_id: UUID
    content_sha256: str

    def __post_init__(self) -> None:
        _uuid("evidence_id", self.evidence_id)
        _sha256("content_sha256", self.content_sha256)


@dataclass(frozen=True, slots=True)
class ReconstructionManifest:
    cutoff: datetime
    universe_id: str
    universe_version: str
    universe_sha256: str
    dataset_version: DatasetVersionReference
    dataset_lineage_sha256: str
    selected_revision_ids: tuple[UUID, ...]
    revision_pins: tuple[HistoricalEvidencePin, ...]
    source_pins: tuple[HistoricalEvidencePin, ...]
    policy_version: str = "historical-selection-v1"
    contract_id: str = field(default="C-103", init=False)
    schema_version: str = field(default=CONTRACT_SCHEMA_VERSION, init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "cutoff", _utc_datetime("cutoff", self.cutoff))
        for name in ("universe_id", "universe_version"):
            _required_text(name, getattr(self, name))
        for name in ("universe_sha256", "dataset_lineage_sha256"):
            _sha256(name, getattr(self, name))
        if type(self.dataset_version) is not DatasetVersionReference:
            raise MarketDataContractError("Exact dataset version is required.")
        if self.policy_version != "historical-selection-v1":
            raise MarketDataContractError("Unsupported selection policy.")
        _uuid_tuple(
            "selected_revision_ids", self.selected_revision_ids, allow_empty=True
        )
        for name in ("revision_pins", "source_pins"):
            pins = getattr(self, name)
            if type(pins) is not tuple or not all(
                type(pin) is HistoricalEvidencePin for pin in pins
            ):
                raise MarketDataContractError("Immutable evidence pins are required.")
            _uuid_tuple(
                name,
                tuple(pin.evidence_id for pin in pins),
                allow_empty=name == "revision_pins",
            )
        if not set(self.selected_revision_ids).issubset(
            {pin.evidence_id for pin in self.revision_pins}
        ):
            raise MarketDataContractError("Selected revisions must be pinned.")
