"""Reconstruct explicitly pinned evidence; never select a guessed latest revision."""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from trading_platform_api.market_data.contracts import (
    CONTRACT_SCHEMA_VERSION,
    DatasetVersion,
    DataSourceRecord,
    MarketData,
    MarketSnapshot,
)


class PointInTimeError(ValueError):
    """The supplied evidence cannot prove the requested reconstruction."""


@dataclass(frozen=True, slots=True)
class ReconstructedEvidence:
    snapshot: MarketSnapshot
    dataset: DatasetVersion
    observations: tuple[MarketData, ...]
    sources: tuple[DataSourceRecord, ...]


def reconstruct_pinned_snapshot(
    *,
    snapshot: MarketSnapshot,
    dataset: DatasetVersion,
    observations: tuple[MarketData, ...],
    sources: tuple[DataSourceRecord, ...],
    expected_lineage_sha256: str,
    survivorship_sensitive: bool,
    finalized_candle_ends: tuple[tuple[UUID, datetime], ...] = (),
) -> ReconstructedEvidence:
    """Validate exact historical evidence, returning it in pinned identity order.

    The lineage pin and candle close evidence must come from trusted provenance,
    not an LLM or from copying values out of the candidate dataset. This checks
    the pin, not the raw-content hash preimage. Universe-membership and revision
    ordering contracts are absent: survivorship-sensitive requests are blocked,
    and callers must supply the exact historical version rather than 'latest'.
    """
    if type(survivorship_sensitive) is not bool:
        raise PointInTimeError("Explicit survivorship policy is required.")
    if survivorship_sensitive:
        raise PointInTimeError("Historical universe-membership proof is unavailable.")
    if type(snapshot) is not MarketSnapshot or type(dataset) is not DatasetVersion:
        raise PointInTimeError("Approved snapshot and dataset contracts are required.")
    if (
        type(observations) is not tuple
        or not observations
        or not all(type(item) is MarketData for item in observations)
        or type(sources) is not tuple
        or not sources
        or not all(type(item) is DataSourceRecord for item in sources)
    ):
        raise PointInTimeError("Immutable observations and sources are required.")
    cutoff = snapshot.as_of
    reference = snapshot.dataset_version
    if (
        reference is None
        or (reference.dataset_id, reference.version)
        != (dataset.dataset_id, dataset.version)
        or dataset.point_in_time_cutoff != cutoff
        or dataset.created_at > snapshot.created_at
        or dataset.canonical_schema_version != CONTRACT_SCHEMA_VERSION
        or type(expected_lineage_sha256) is not str
        or expected_lineage_sha256 != dataset.lineage_sha256
    ):
        raise PointInTimeError("Dataset version, cutoff or lineage pin mismatch.")
    by_id = {item.market_data_id: item for item in observations}
    by_source = {item.source_record_id: item for item in sources}
    if (
        len(by_id) != len(observations)
        or len(by_source) != len(sources)
        or set(by_id) != set(snapshot.market_data_ids)
        or set(by_source) != set(snapshot.source_record_ids)
        or set(by_source) != set(dataset.source_record_ids)
    ):
        raise PointInTimeError("Exact dataset and snapshot membership is required.")
    for source_record in sources:
        if source_record.availability_time > cutoff:
            raise PointInTimeError("Source was not available at the cutoff.")
    if type(finalized_candle_ends) is not tuple:
        raise PointInTimeError("Immutable candle finality evidence is required.")
    ends: dict[UUID, datetime] = {}
    for pair in finalized_candle_ends:
        if (
            type(pair) is not tuple
            or len(pair) != 2
            or type(pair[0]) is not UUID
            or type(pair[1]) is not datetime
            or pair[1].utcoffset() is None
            or pair[0] in ends
        ):
            raise PointInTimeError("Invalid or duplicate candle close evidence.")
        ends[pair[0]] = pair[1]
    if set(ends) != {
        item.market_data_id for item in observations if item.observation_type == "OHLCV"
    }:
        raise PointInTimeError("Exact trusted candle finality evidence is required.")
    used_sources: set[UUID] = set()
    for item in observations:
        source = by_source.get(item.source_record_id)
        if (
            source is None
            or item.instrument_id != snapshot.instrument_id
            or item.venue_id != snapshot.venue_id
            or not dataset.coverage_start <= item.event_time <= dataset.coverage_end
            or item.availability_time > cutoff
            or item.provider_time > source.retrieval_time
            or source.retrieval_time > item.ingestion_time
            or source.availability_time > item.availability_time
        ):
            raise PointInTimeError(
                "Observation identity, chronology or coverage mismatch."
            )
        if item.observation_type == "OHLCV" and not (
            item.event_time < ends[item.market_data_id] <= source.retrieval_time
            and ends[item.market_data_id] <= cutoff
        ):
            raise PointInTimeError("Candle was not closed at the cutoff.")
        used_sources.add(item.source_record_id)
    for name in (
        "event_data",
        "fundamental_data",
        "on_chain_data",
        "derivatives_data",
        "sentiment_data",
        "macro_data",
    ):
        for embedded in getattr(snapshot, name):
            source = by_source.get(embedded.source_record_id)
            if (
                source is None
                or source.availability_time > embedded.availability_time
                or embedded.availability_time > cutoff
            ):
                raise PointInTimeError(
                    "Embedded evidence was unavailable at the cutoff."
                )
            used_sources.add(embedded.source_record_id)
    if used_sources != set(by_source):
        raise PointInTimeError("Unreferenced sources cannot enter the reconstruction.")
    return ReconstructedEvidence(
        snapshot,
        dataset,
        tuple(by_id[item_id] for item_id in snapshot.market_data_ids),
        tuple(by_source[source_id] for source_id in snapshot.source_record_ids),
    )
