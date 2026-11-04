"""Exact persisted point-in-time historical dataset loader for Chat 7."""

from __future__ import annotations

from typing import Protocol

from trading_platform_api.contracts.serialization import canonical_sha256
from trading_platform_api.lineage.codec import LineageError, LineageKey
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


class HistoricalDatasetLoaderError(ValueError):
    """Persisted history cannot prove the requested exact reconstruction."""


class HistoricalLineageResolver(Protocol):
    async def resolve(
        self,
        keys: tuple[LineageKey, ...],
        *,
        maximum_records: int = 2000,
    ) -> dict[LineageKey, object]: ...


async def load_historical_reconstruction(
    resolver: HistoricalLineageResolver,
    *,
    manifest_sha256: str,
    maximum_records: int = 2000,
) -> HistoricalReconstruction:
    """Resolve one exact C-103 closure and replay its deterministic selection.

    The caller supplies the immutable C-103 content digest as the identity.
    No "latest" lookup, synthesized universe, inferred revision, or unpinned
    source is permitted.
    """
    if (
        type(manifest_sha256) is not str
        or len(manifest_sha256) != 64
        or any(ch not in "0123456789abcdef" for ch in manifest_sha256)
    ):
        raise HistoricalDatasetLoaderError(
            "manifest_sha256 must be a lowercase SHA-256 digest."
        )
    if type(maximum_records) is not int or not 1 <= maximum_records <= 2000:
        raise HistoricalDatasetLoaderError("Invalid bounded lineage read budget.")

    key = LineageKey("C-103", manifest_sha256)
    try:
        resolved = await resolver.resolve((key,), maximum_records=maximum_records)
        manifest = resolved.get(key)
        if (
            type(manifest) is not ReconstructionManifest
            or canonical_sha256(manifest) != manifest_sha256
        ):
            raise HistoricalDatasetLoaderError(
                "Resolved C-103 identity does not match the requested digest."
            )

        dataset_key = LineageKey(
            "C-092",
            manifest.dataset_version.dataset_id,
            manifest.dataset_version.version,
        )
        universe_key = LineageKey(
            "C-101", manifest.universe_id, manifest.universe_version
        )
        dataset = resolved.get(dataset_key)
        universe = resolved.get(universe_key)
        if type(dataset) is not DatasetVersion or type(universe) is not HistoricalUniverse:
            raise HistoricalDatasetLoaderError(
                "C-103 dataset or universe dependency is unavailable."
            )

        revision_keys = tuple(
            LineageKey("C-102", str(pin.evidence_id))
            for pin in manifest.revision_pins
        )
        source_keys = tuple(
            LineageKey("C-091", str(pin.evidence_id))
            for pin in manifest.source_pins
        )
        revisions = tuple(resolved.get(item) for item in revision_keys)
        sources = tuple(resolved.get(item) for item in source_keys)
        if (
            any(type(item) is not ObservationRevision for item in revisions)
            or any(type(item) is not DataSourceRecord for item in sources)
        ):
            raise HistoricalDatasetLoaderError(
                "C-103 revision or source dependency is unavailable."
            )
        typed_revisions = tuple(
            item for item in revisions if type(item) is ObservationRevision
        )
        typed_sources = tuple(item for item in sources if type(item) is DataSourceRecord)
        if len(typed_revisions) != len(revisions) or len(typed_sources) != len(sources):
            raise HistoricalDatasetLoaderError(
                "Resolved historical dependency type mismatch."
            )
        if any(not item.licensing_reference.strip() for item in typed_sources):
            raise HistoricalDatasetLoaderError(
                "Historical source licensing reference is unavailable."
            )

        reconstruction = reconstruct_history(
            cutoff=manifest.cutoff,
            universe=universe,
            revisions=typed_revisions,
            sources=typed_sources,
            dataset=dataset,
            expected_universe_sha256=manifest.universe_sha256,
            expected_lineage_sha256=manifest.dataset_lineage_sha256,
        )
        if reconstruction.manifest != manifest:
            raise HistoricalDatasetLoaderError(
                "Persisted C-103 does not reproduce from its exact dependency closure."
            )
        return reconstruction
    except HistoricalDatasetLoaderError:
        raise
    except (LineageError, PointInTimeError, KeyError, TypeError, ValueError) as exc:
        raise HistoricalDatasetLoaderError(
            "Historical reconstruction could not be proven from persisted lineage."
        ) from exc


__all__ = [
    "HistoricalDatasetLoaderError",
    "HistoricalLineageResolver",
    "load_historical_reconstruction",
]
