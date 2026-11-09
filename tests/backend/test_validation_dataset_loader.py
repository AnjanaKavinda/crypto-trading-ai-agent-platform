"""Synthetic persisted history only; no provider or performance assertions."""

import asyncio
from dataclasses import replace
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from test_history_selection import STEP, T, history, include, revised
from test_lineage_postgresql import database_url as database_url
from trading_platform_api.contracts.serialization import canonical_sha256
from trading_platform_api.lineage.codec import LineageError, key_for
from trading_platform_api.lineage.store import SqlAlchemyLineageStore
from trading_platform_api.market_data.history_contracts import HistoricalEvidencePin
from trading_platform_api.market_data.history_selection import reconstruct_history
from trading_platform_api.validation.dataset_loader import (
    DatasetLoadError,
    DatasetLoadFailure,
    load_validation_dataset,
)


class MemoryResolver:
    """Deliberately simple to verify the loader's own pin checks as well."""

    def __init__(self, records):
        self.records = {key_for(record): record for record in records}
        self.calls = []

    async def resolve(self, keys, *, maximum_records=2000):
        self.calls.append((keys, maximum_records))
        return dict(self.records)


def closure(args=None):
    args = history() if args is None else args
    expected = reconstruct_history(**args)
    records = (
        *args["sources"],
        args["dataset"],
        args["universe"],
        *(r.observation for r in args["revisions"]),
        *args["revisions"],
        expected.manifest,
    )
    return args, expected, records


def load(resolver, dataset, manifest, **kwargs):
    return asyncio.run(
        load_validation_dataset(
            resolver,
            dataset_sha256=canonical_sha256(dataset),
            manifest_sha256=canonical_sha256(manifest),
            **kwargs,
        )
    )


def test_exact_fixed_universe_replay_and_canonical_order():
    args = history()
    revision, source = revised(args, T + STEP)
    include(args, revision, source)
    args, expected, records = closure(args)
    resolver = MemoryResolver(records)
    first = load(resolver, args["dataset"], expected.manifest)
    second = load(MemoryResolver(reversed(records)), args["dataset"], expected.manifest)
    assert first == second
    assert first.reconstruction == expected
    assert first.reconstruction.selected_revisions == (revision,)
    assert first.dataset_sha256 == canonical_sha256(args["dataset"])
    assert first.manifest_sha256 == canonical_sha256(expected.manifest)
    assert resolver.calls == [((key_for(expected.manifest),), 2000)]


def test_later_revision_and_delisting_cannot_rewrite_pinned_history():
    args, expected, records = closure()
    revision, source = revised(args, T + 3 * STEP)
    today = replace(
        args["universe"],
        version="2",
        instrument_ids=(),
        effective_from=T + 3 * STEP,
        effective_until=T + 10 * STEP,
    )
    resolver = MemoryResolver((*records, revision, source, today))
    result = load(resolver, args["dataset"], expected.manifest)
    assert result.reconstruction == expected
    assert result.reconstruction.universe.instrument_ids == ("BTC-USDT-SPOT",)
    assert result.reconstruction.selected_revisions == args["revisions"]


@pytest.mark.parametrize(
    "kind", ["manifest", "dataset", "universe", "source", "revision"]
)
def test_changed_content_under_same_identity_is_rejected(kind):
    args, expected, records = closure()
    resolver = MemoryResolver(records)
    original = {
        "manifest": expected.manifest,
        "dataset": args["dataset"],
        "universe": args["universe"],
        "source": args["sources"][0],
        "revision": args["revisions"][0],
    }[kind]
    changed = {
        "manifest": lambda: replace(original, selected_revision_ids=()),
        "dataset": lambda: replace(original, coverage_start=T - STEP),
        "universe": lambda: replace(original, definition_version="changed"),
        "source": lambda: replace(original, licensing_reference="changed"),
        "revision": lambda: replace(original, observation_key="changed"),
    }[kind]()
    resolver.records[key_for(original)] = changed
    with pytest.raises(DatasetLoadError) as error:
        load(resolver, args["dataset"], expected.manifest)
    assert error.value.reason is DatasetLoadFailure.INTEGRITY_MISMATCH


@pytest.mark.parametrize(
    "kind", ["dataset", "universe", "revision", "source", "manifest"]
)
def test_missing_proof_has_no_latest_fallback(kind):
    args, expected, records = closure()
    resolver = MemoryResolver(records)
    record = {
        "dataset": args["dataset"],
        "universe": args["universe"],
        "revision": args["revisions"][0],
        "source": args["sources"][0],
        "manifest": expected.manifest,
    }[kind]
    del resolver.records[key_for(record)]
    with pytest.raises(DatasetLoadError) as error:
        load(resolver, args["dataset"], expected.manifest)
    assert error.value.reason is DatasetLoadFailure.UNRESOLVED_LINEAGE


@pytest.mark.parametrize("pin", ["", "latest", "A" * 64, "a" * 63])
def test_invalid_reference_never_reads_store(pin):
    args, expected, records = closure()
    resolver = MemoryResolver(records)
    with pytest.raises(DatasetLoadError) as error:
        asyncio.run(
            load_validation_dataset(
                resolver,
                manifest_sha256=pin,
                dataset_sha256=canonical_sha256(args["dataset"]),
            )
        )
    assert error.value.reason is DatasetLoadFailure.INVALID_REQUEST
    assert resolver.calls == []


@pytest.mark.parametrize("budget", [True, 0, 2001])
def test_invalid_budget_never_reads_store(budget):
    args, expected, records = closure()
    resolver = MemoryResolver(records)
    with pytest.raises(DatasetLoadError):
        load(resolver, args["dataset"], expected.manifest, maximum_records=budget)
    assert resolver.calls == []


@pytest.mark.parametrize(
    "kind", ["cutoff", "coverage", "schema", "missing_parent", "extra_source"]
)
def test_self_consistent_pins_do_not_bypass_temporal_or_membership_validation(kind):
    args, expected, records = closure()
    dataset = args["dataset"]
    manifest = expected.manifest
    if kind == "cutoff":
        dataset = replace(dataset, point_in_time_cutoff=T + 3 * STEP)
    elif kind == "coverage":
        dataset = replace(dataset, coverage_start=T + STEP)
    elif kind == "schema":
        dataset = replace(dataset, canonical_schema_version="unsupported")
    elif kind == "extra_source":
        dataset = replace(
            dataset, source_record_ids=dataset.source_record_ids + (uuid4(),)
        )
    resolver = MemoryResolver(records)
    resolver.records[key_for(dataset)] = dataset
    if kind == "missing_parent":
        revision = replace(args["revisions"][0], supersedes_revision_id=uuid4())
        manifest = replace(
            manifest,
            revision_pins=(
                HistoricalEvidencePin(revision.revision_id, canonical_sha256(revision)),
            ),
        )
        resolver.records[key_for(revision)] = revision
        resolver.records[key_for(manifest)] = manifest
    with pytest.raises(DatasetLoadError) as error:
        load(resolver, dataset, manifest)
    assert error.value.reason is (
        DatasetLoadFailure.UNSUPPORTED_SCHEMA
        if kind == "schema"
        else DatasetLoadFailure.TEMPORAL_OR_MEMBERSHIP_MISMATCH
    )


@pytest.mark.parametrize(
    "kind", ["future_revision", "future_source", "missing_selection"]
)
def test_pinned_future_or_incomplete_selection_is_rejected(kind):
    args, expected, records = closure()
    resolver = MemoryResolver(records)
    manifest = expected.manifest
    if kind == "future_revision":
        revision, source = revised(args, T + 3 * STEP)
        manifest = replace(
            manifest,
            revision_pins=manifest.revision_pins
            + (
                HistoricalEvidencePin(revision.revision_id, canonical_sha256(revision)),
            ),
        )
        resolver.records[key_for(revision)] = revision
        resolver.records[key_for(source)] = source
    elif kind == "future_source":
        source = replace(
            args["sources"][0],
            retrieval_time=T + 3 * STEP,
            availability_time=T + 3 * STEP,
        )
        manifest = replace(
            manifest,
            source_pins=tuple(
                HistoricalEvidencePin(pin.evidence_id, canonical_sha256(source))
                if pin.evidence_id == source.source_record_id
                else pin
                for pin in manifest.source_pins
            ),
        )
        resolver.records[key_for(source)] = source
    else:
        manifest = replace(manifest, selected_revision_ids=())
    resolver.records[key_for(manifest)] = manifest
    with pytest.raises(DatasetLoadError):
        load(resolver, args["dataset"], manifest)


def test_resolver_rejection_is_explicit_and_not_retried():
    args, expected, _ = closure()

    class RejectingResolver:
        async def resolve(self, keys, *, maximum_records):
            raise LineageError("corrupt or unsupported durable evidence")

    with pytest.raises(DatasetLoadError) as error:
        load(RejectingResolver(), args["dataset"], expected.manifest)
    assert error.value.reason is DatasetLoadFailure.UNRESOLVED_LINEAGE


def test_postgresql_loader_replays_after_session_restart_without_writes(database_url):
    async def check():
        engine = create_async_engine(database_url)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        args = history()
        args["dataset"] = replace(args["dataset"], dataset_id=f"loader-{uuid4()}")
        args["universe"] = replace(args["universe"], universe_id=f"loader-{uuid4()}")
        args["expected_universe_sha256"] = canonical_sha256(args["universe"])
        args, expected, records = closure(args)
        try:
            async with sessions.begin() as session:
                store = SqlAlchemyLineageStore(session)
                for record in records:
                    await store.append(record)
            outputs = []
            for _ in range(2):
                async with sessions.begin() as session:
                    from sqlalchemy import text

                    await session.execute(text("SET TRANSACTION READ ONLY"))
                    outputs.append(
                        await load_validation_dataset(
                            SqlAlchemyLineageStore(session),
                            dataset_sha256=canonical_sha256(args["dataset"]),
                            manifest_sha256=canonical_sha256(expected.manifest),
                        )
                    )
            assert outputs[0] == outputs[1]
            assert outputs[0].reconstruction == expected
        finally:
            await engine.dispose()

    asyncio.run(check())
