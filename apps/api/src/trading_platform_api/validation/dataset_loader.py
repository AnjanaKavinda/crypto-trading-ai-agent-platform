"""Read-only validation loading from exact, persisted historical evidence."""

from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol, TypeVar, cast

from trading_platform_api.contracts.serialization import canonical_sha256
from trading_platform_api.lineage.codec import LineageError, LineageKey, key_for
from trading_platform_api.market_data.contracts import DatasetVersion, DataSourceRecord
from trading_platform_api.market_data.history_contracts import (
    HistoricalUniverse,
    ObservationRevision,
    ReconstructionManifest,
)
from trading_platform_api.market_data.history_selection import (
    HistoricalReconstruction,
    reconstruct_history,
)
from trading_platform_api.market_data.point_in_time import PointInTimeError

HistoricalRecord = TypeVar(
    "HistoricalRecord",
    bound=DatasetVersion
    | DataSourceRecord
    | HistoricalUniverse
    | ObservationRevision
    | ReconstructionManifest,
)


class DatasetLoadFailure(StrEnum):
    INVALID_REQUEST = "INVALID_REQUEST"
    UNSUPPORTED_SCHEMA = "UNSUPPORTED_SCHEMA"
    UNRESOLVED_LINEAGE = "UNRESOLVED_LINEAGE"
    INTEGRITY_MISMATCH = "INTEGRITY_MISMATCH"
    UNAVAILABLE_SOURCE = "UNAVAILABLE_SOURCE"
    TEMPORAL_OR_MEMBERSHIP_MISMATCH = "TEMPORAL_OR_MEMBERSHIP_MISMATCH"


class DatasetLoadError(ValueError):
    """Evidence is unavailable/inconclusive; never permission to fill gaps."""

    def __init__(self, reason: DatasetLoadFailure, message: str) -> None:
        super().__init__(message)
        self.reason = reason


class HistoricalLineageResolver(Protocol):
    async def resolve(
        self, keys: tuple[LineageKey, ...], *, maximum_records: int = 2000
    ) -> dict[LineageKey, object]: ...


@dataclass(frozen=True, slots=True)
class LoadedValidationDataset:
    """Internal result; retain both canonical digests in downstream results.

    C-103 binds selection, revision ancestry and sources. Its C-092 reference
    pins identity/lineage, while dataset_sha256 additionally pins coverage and
    every other C-092 field. Neither digest proves external source completeness.
    """

    dataset: DatasetVersion
    dataset_sha256: str
    manifest_sha256: str
    reconstruction: HistoricalReconstruction
    sources: tuple[DataSourceRecord, ...]


def _digest(value: str) -> None:
    if (
        type(value) is not str
        or len(value) != 64
        or any(ch not in "0123456789abcdef" for ch in value)
    ):
        raise DatasetLoadError(
            DatasetLoadFailure.INVALID_REQUEST, "Exact lowercase SHA-256 pins required."
        )


async def load_validation_dataset(
    resolver: HistoricalLineageResolver,
    *,
    manifest_sha256: str,
    dataset_sha256: str,
    maximum_records: int = 2000,
) -> LoadedValidationDataset:
    """Replay an exact C-103 closure, including a fixed historical universe.

    Only approved schema 1 and historical-selection-v1 are supported. No raw
    caller rows, mutable selectors, provider requests or writes are accepted.
    Availability is historical, not relative to today's wall clock: old source
    evidence remains valid if it proves the pinned cutoff.
    """
    _digest(manifest_sha256)
    _digest(dataset_sha256)
    if type(maximum_records) is not int or not 1 <= maximum_records <= 2000:
        raise DatasetLoadError(
            DatasetLoadFailure.INVALID_REQUEST, "Invalid bounded lineage read budget."
        )
    manifest_key = LineageKey("C-103", manifest_sha256)
    try:
        resolved = await resolver.resolve(
            (manifest_key,), maximum_records=maximum_records
        )
    except LineageError as exc:
        raise DatasetLoadError(
            DatasetLoadFailure.UNRESOLVED_LINEAGE,
            "Exact persisted lineage could not be resolved or validated.",
        ) from exc

    def exact(
        key: LineageKey, model: type[HistoricalRecord], digest: str | None = None
    ) -> HistoricalRecord:
        record = resolved.get(key)
        if type(record) is not model:
            raise DatasetLoadError(
                DatasetLoadFailure.UNRESOLVED_LINEAGE,
                "Required approved historical evidence is unavailable.",
            )
        typed_record = cast(HistoricalRecord, record)
        if typed_record.schema_version != "1":
            raise DatasetLoadError(
                DatasetLoadFailure.UNSUPPORTED_SCHEMA, "Unsupported historical schema."
            )
        if key_for(record) != key or (
            digest is not None and canonical_sha256(record) != digest
        ):
            raise DatasetLoadError(
                DatasetLoadFailure.INTEGRITY_MISMATCH,
                "Resolved identity or canonical content does not match its pin.",
            )
        return typed_record

    manifest = exact(manifest_key, ReconstructionManifest, manifest_sha256)
    if manifest.policy_version != "historical-selection-v1":
        raise DatasetLoadError(
            DatasetLoadFailure.UNSUPPORTED_SCHEMA, "Unsupported selection policy."
        )
    dataset = exact(
        LineageKey(
            "C-092",
            manifest.dataset_version.dataset_id,
            manifest.dataset_version.version,
        ),
        DatasetVersion,
        dataset_sha256,
    )
    if dataset.canonical_schema_version != "1":
        raise DatasetLoadError(
            DatasetLoadFailure.UNSUPPORTED_SCHEMA,
            "Unsupported dataset canonical schema.",
        )
    universe = exact(
        LineageKey("C-101", manifest.universe_id, manifest.universe_version),
        HistoricalUniverse,
        manifest.universe_sha256,
    )
    revisions = tuple(
        exact(
            LineageKey("C-102", str(pin.evidence_id)),
            ObservationRevision,
            pin.content_sha256,
        )
        for pin in manifest.revision_pins
    )
    sources = tuple(
        exact(
            LineageKey("C-091", str(pin.evidence_id)),
            DataSourceRecord,
            pin.content_sha256,
        )
        for pin in manifest.source_pins
    )
    if any(not source.licensing_reference.strip() for source in sources):
        raise DatasetLoadError(
            DatasetLoadFailure.UNAVAILABLE_SOURCE, "Source licensing proof unavailable."
        )
    try:
        reconstruction = reconstruct_history(
            cutoff=manifest.cutoff,
            universe=universe,
            revisions=revisions,
            sources=sources,
            dataset=dataset,
            expected_universe_sha256=manifest.universe_sha256,
            expected_lineage_sha256=manifest.dataset_lineage_sha256,
        )
    except PointInTimeError as exc:
        raise DatasetLoadError(
            DatasetLoadFailure.TEMPORAL_OR_MEMBERSHIP_MISMATCH,
            "Historical times, coverage, universe or revision ancestry cannot be proven.",
        ) from exc
    if reconstruction.manifest != manifest:
        raise DatasetLoadError(
            DatasetLoadFailure.INTEGRITY_MISMATCH,
            "Exact persisted manifest does not reproduce from its pinned closure.",
        )
    return LoadedValidationDataset(
        dataset, dataset_sha256, manifest_sha256, reconstruction, sources
    )
