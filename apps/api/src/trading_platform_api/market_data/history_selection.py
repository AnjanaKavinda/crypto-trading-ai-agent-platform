"""Deterministic historical selection from trusted, complete supplied histories."""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from trading_platform_api.contracts.serialization import canonical_sha256
from trading_platform_api.market_data.contracts import (
    CONTRACT_SCHEMA_VERSION,
    DatasetVersion,
    DatasetVersionReference,
    DataSourceRecord,
    _utc_datetime,
)
from trading_platform_api.market_data.history_contracts import (
    HistoricalEvidencePin,
    HistoricalUniverse,
    ObservationRevision,
    ReconstructionManifest,
)
from trading_platform_api.market_data.point_in_time import PointInTimeError


@dataclass(frozen=True, slots=True)
class HistoricalReconstruction:
    universe: HistoricalUniverse
    selected_revisions: tuple[ObservationRevision, ...]
    manifest: ReconstructionManifest


def _key(revision: ObservationRevision) -> tuple[str, str, str, str, str]:
    item = revision.observation
    return (
        revision.provider_id,
        item.venue_id,
        item.instrument_id,
        item.observation_type,
        revision.observation_key,
    )


def reconstruct_history(
    *,
    cutoff: datetime,
    universe: HistoricalUniverse,
    revisions: tuple[ObservationRevision, ...],
    sources: tuple[DataSourceRecord, ...],
    dataset: DatasetVersion,
    expected_universe_sha256: str,
    expected_lineage_sha256: str,
) -> HistoricalReconstruction:
    """Use a pinned complete universe and explicit supersession chains.

    Callers must supply authentic, complete history and independently trusted
    universe/lineage pins. Hash consistency cannot prove a provider omitted no
    records. This selects evidence; it does not certify backtest performance.
    """
    cutoff = _utc_datetime("cutoff", cutoff)
    if type(universe) is not HistoricalUniverse or type(dataset) is not DatasetVersion:
        raise PointInTimeError("Approved universe and dataset contracts are required.")
    if (
        not universe.effective_from <= cutoff < universe.effective_until
        or universe.availability_time > cutoff
        or canonical_sha256(universe) != expected_universe_sha256
        or dataset.lineage_sha256 != expected_lineage_sha256
        or dataset.point_in_time_cutoff != cutoff
        or dataset.canonical_schema_version != CONTRACT_SCHEMA_VERSION
    ):
        raise PointInTimeError("Universe or dataset time/version pin mismatch.")
    if (
        type(revisions) is not tuple
        or not all(type(item) is ObservationRevision for item in revisions)
        or type(sources) is not tuple
        or not all(type(item) is DataSourceRecord for item in sources)
    ):
        raise PointInTimeError("Immutable revision/source evidence is required.")
    source_map = {source.source_record_id: source for source in sources}
    if len(source_map) != len(sources) or len(
        {r.revision_id for r in revisions}
    ) != len(revisions):
        raise PointInTimeError("Duplicate revision or source identity.")
    used_sources = set(universe.source_record_ids)
    for source_id in universe.source_record_ids:
        source = source_map.get(source_id)
        if (
            source is None
            or source.retrieval_time > universe.ingestion_time
            or source.availability_time > universe.availability_time
            or source.provider_event_time > universe.publication_time
        ):
            raise PointInTimeError(
                "Universe source provenance is missing or inconsistent."
            )
    eligible = tuple(
        revision
        for revision in revisions
        if revision.availability_time <= cutoff
        and revision.observation.instrument_id in universe.instrument_ids
    )
    groups: dict[tuple[str, str, str, str, str], list[ObservationRevision]] = {}
    if len({r.observation.market_data_id for r in eligible}) != len(eligible):
        raise PointInTimeError("Distinct revisions require distinct observation IDs.")
    for revision in eligible:
        item = revision.observation
        source = source_map.get(item.source_record_id)
        if (
            source is None
            or source.provider_id != revision.provider_id
            or item.venue_id != universe.venue_id
            or not dataset.coverage_start <= item.event_time <= dataset.coverage_end
            or source.provider_event_time > revision.publication_time
            or source.retrieval_time > item.ingestion_time
            or source.availability_time > item.availability_time
            or item.provider_time > source.retrieval_time
            or (
                revision.finalized_interval_end is not None
                and revision.finalized_interval_end > source.retrieval_time
            )
        ):
            raise PointInTimeError(
                "Revision source, scope or time evidence is inconsistent."
            )
        used_sources.add(item.source_record_id)
        groups.setdefault(_key(revision), []).append(revision)
    selected: list[ObservationRevision] = []
    for key in sorted(groups):
        chain = groups[key]
        if len({r.observation.event_time for r in chain}) != 1:
            raise PointInTimeError(
                "A logical observation key cannot change event time."
            )
        by_id = {revision.revision_id: revision for revision in chain}
        if len({r.observation.market_data_id for r in chain}) != len(chain):
            raise PointInTimeError(
                "Revisions must preserve distinct immutable observation IDs."
            )
        roots = [
            revision for revision in chain if revision.supersedes_revision_id is None
        ]
        children: dict[UUID, ObservationRevision] = {}
        for revision in chain:
            parent_id = revision.supersedes_revision_id
            if parent_id is None:
                continue
            parent = by_id.get(parent_id)
            if (
                parent is None
                or parent_id in children
                or parent.availability_time > revision.availability_time
                or parent.publication_time > revision.publication_time
                or parent.ingestion_time > revision.ingestion_time
            ):
                raise PointInTimeError(
                    "Missing, forked or temporally invalid revision ancestry."
                )
            children[parent_id] = revision
        if len(roots) != 1:
            raise PointInTimeError("Ambiguous or cyclic revision history.")
        current = roots[0]
        visited: set[UUID] = set()
        while True:
            if current.revision_id in visited:
                raise PointInTimeError("Cyclic revision history.")
            visited.add(current.revision_id)
            child = children.get(current.revision_id)
            if child is None:
                break
            current = child
        if visited != set(by_id):
            raise PointInTimeError("Disconnected revision history.")
        selected.append(current)
    if {r.observation.instrument_id for r in selected} != set(universe.instrument_ids):
        raise PointInTimeError(
            "Historical universe observation coverage is incomplete."
        )
    if used_sources != set(dataset.source_record_ids):
        raise PointInTimeError(
            "Dataset source composition does not match reconstruction."
        )
    manifest = ReconstructionManifest(
        cutoff=cutoff,
        universe_id=universe.universe_id,
        universe_version=universe.version,
        universe_sha256=canonical_sha256(universe),
        dataset_version=DatasetVersionReference(dataset.dataset_id, dataset.version),
        dataset_lineage_sha256=dataset.lineage_sha256,
        selected_revision_ids=tuple(r.revision_id for r in selected),
        revision_pins=tuple(
            HistoricalEvidencePin(r.revision_id, canonical_sha256(r))
            for r in sorted(eligible, key=lambda r: str(r.revision_id))
        ),
        source_pins=tuple(
            HistoricalEvidencePin(source_id, canonical_sha256(source_map[source_id]))
            for source_id in sorted(used_sources, key=str)
        ),
    )
    return HistoricalReconstruction(universe, tuple(selected), manifest)
