from __future__ import annotations

import asyncio
from dataclasses import replace

import pytest
from test_history_selection import history
from trading_platform_api.contracts.serialization import canonical_sha256
from trading_platform_api.lineage.codec import LineageKey, key_for
from trading_platform_api.market_data.history_loader import (
    HistoricalDatasetLoaderError,
    load_historical_reconstruction,
)
from trading_platform_api.market_data.history_selection import reconstruct_history


class MemoryResolver:
    def __init__(self, records: tuple[object, ...]) -> None:
        self.records = {key_for(record): record for record in records}
        self.requested: tuple[LineageKey, ...] | None = None

    async def resolve(
        self, keys: tuple[LineageKey, ...], *, maximum_records: int = 2000
    ) -> dict[LineageKey, object]:
        assert maximum_records <= 2000
        self.requested = keys
        return dict(self.records)


def _closure():
    args = history()
    expected = reconstruct_history(**args)
    records = (
        expected.manifest,
        args["dataset"],
        args["universe"],
        *args["revisions"],
        *args["sources"],
    )
    return args, expected, records


def test_exact_persisted_manifest_replays_identically() -> None:
    _, expected, records = _closure()
    digest = canonical_sha256(expected.manifest)
    resolver = MemoryResolver(records)
    result = asyncio.run(
        load_historical_reconstruction(resolver, manifest_sha256=digest)
    )
    assert result == expected
    assert resolver.requested == (LineageKey("C-103", digest),)


@pytest.mark.parametrize("digest", ["", "A" * 64, "a" * 63])
def test_invalid_manifest_identity_fails_closed(digest: str) -> None:
    _, _, records = _closure()
    with pytest.raises(HistoricalDatasetLoaderError):
        asyncio.run(
            load_historical_reconstruction(
                MemoryResolver(records),
                manifest_sha256=digest,
            )
        )


def test_missing_exact_dependency_fails_closed() -> None:
    _, expected, records = _closure()
    digest = canonical_sha256(expected.manifest)
    resolver = MemoryResolver(records[:-1])
    with pytest.raises(HistoricalDatasetLoaderError, match="source dependency"):
        asyncio.run(
            load_historical_reconstruction(resolver, manifest_sha256=digest)
        )


def test_manifest_cannot_be_replayed_with_changed_dataset_or_revision() -> None:
    args, expected, records = _closure()
    digest = canonical_sha256(expected.manifest)
    changed_dataset = replace(args["dataset"], lineage_sha256="f" * 64)
    resolver = MemoryResolver(
        tuple(changed_dataset if item is args["dataset"] else item for item in records)
    )
    with pytest.raises(HistoricalDatasetLoaderError):
        asyncio.run(
            load_historical_reconstruction(resolver, manifest_sha256=digest)
        )


def test_loader_never_guesses_latest_manifest() -> None:
    _, expected, records = _closure()
    digest = canonical_sha256(expected.manifest)
    later = replace(expected.manifest, policy_version="unsupported")
    resolver = MemoryResolver((*records, later))
    result = asyncio.run(
        load_historical_reconstruction(resolver, manifest_sha256=digest)
    )
    assert result.manifest == expected.manifest
