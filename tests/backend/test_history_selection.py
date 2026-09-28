"""Synthetic universe/revision histories; no provider or performance claims."""

import json
from dataclasses import replace
from uuid import uuid4

import pytest
from contract_harness import ContractHarnessCase, assert_canonical_round_trip
from test_point_in_time import STEP, T, evidence
from trading_platform_api.contracts import describe_dataclass_contract
from trading_platform_api.contracts.serialization import (
    canonical_sha256,
    serialize_contract,
)
from trading_platform_api.market_data.contracts import MarketDataContractError
from trading_platform_api.market_data.history_contracts import (
    HistoricalUniverse,
    ObservationRevision,
)
from trading_platform_api.market_data.history_selection import reconstruct_history
from trading_platform_api.market_data.point_in_time import PointInTimeError


def history():
    old = evidence()
    source = old["sources"][0]
    universe_source = replace(
        source,
        source_record_id=uuid4(),
        provider_event_time=T - 5 * STEP,
        retrieval_time=T - 4 * STEP,
        availability_time=T - 4 * STEP,
    )
    universe = HistoricalUniverse(
        "fixture-universe",
        "1",
        "all-listed-spot-v1",
        "fixture",
        T - 10 * STEP,
        T + 3 * STEP,
        T - 5 * STEP,
        T - 4 * STEP,
        T - 4 * STEP,
        ("BTC-USDT-SPOT",),
        (universe_source.source_record_id,),
        True,
    )
    revision = ObservationRevision(
        uuid4(),
        "fixture",
        "trade-1",
        None,
        old["observations"][0],
        T + STEP,
        T + STEP,
        T + STEP,
    )
    dataset = replace(
        old["dataset"],
        source_record_ids=(source.source_record_id, universe_source.source_record_id),
    )
    return dict(
        cutoff=T + 2 * STEP,
        universe=universe,
        revisions=(revision,),
        sources=(source, universe_source),
        dataset=dataset,
        expected_universe_sha256=canonical_sha256(universe),
        expected_lineage_sha256=dataset.lineage_sha256,
    )


def revised(args, moment):
    parent = args["revisions"][0]
    source = replace(
        args["sources"][0],
        source_record_id=uuid4(),
        provider_event_time=moment,
        retrieval_time=moment,
        availability_time=moment,
    )
    item = replace(
        parent.observation,
        market_data_id=uuid4(),
        source_record_id=source.source_record_id,
        provider_time=moment,
        ingestion_time=moment,
        availability_time=moment,
    )
    revision = replace(
        parent,
        revision_id=uuid4(),
        supersedes_revision_id=parent.revision_id,
        observation=item,
        publication_time=moment,
        ingestion_time=moment,
        availability_time=moment,
    )
    return revision, source


def include(args, revision, source):
    args["revisions"] += (revision,)
    args["sources"] += (source,)
    args["dataset"] = replace(
        args["dataset"],
        source_record_ids=args["dataset"].source_record_ids
        + (source.source_record_id,),
    )


def test_later_revision_does_not_change_earlier_manifest():
    args = history()
    before = reconstruct_history(**args)
    revision, source = revised(args, T + 3 * STEP)
    args["revisions"] += (revision,)
    args["sources"] += (source,)
    after = reconstruct_history(**args)
    assert after == before
    assert canonical_sha256(after.manifest) == canonical_sha256(before.manifest)


def test_explicit_ancestry_resolves_equal_timestamp_revision():
    args = history()
    revision, source = revised(args, T + STEP)
    include(args, revision, source)
    result = reconstruct_history(**args)
    assert result.selected_revisions == (revision,)
    assert len(result.manifest.revision_pins) == 2
    args["revisions"] = tuple(reversed(args["revisions"]))
    args["sources"] = tuple(reversed(args["sources"]))
    assert reconstruct_history(**args) == result


def test_delisting_does_not_rewrite_prior_membership():
    args = history()
    earlier = reconstruct_history(**args)
    universe = replace(
        args["universe"],
        version="2",
        instrument_ids=(),
        effective_from=T + 3 * STEP,
        effective_until=T + 10 * STEP,
    )
    later = dict(
        args,
        cutoff=T + 4 * STEP,
        universe=universe,
        expected_universe_sha256=canonical_sha256(universe),
        dataset=replace(
            args["dataset"],
            created_at=T + 4 * STEP,
            point_in_time_cutoff=T + 4 * STEP,
            source_record_ids=universe.source_record_ids,
        ),
    )
    assert reconstruct_history(**later).selected_revisions == ()
    assert reconstruct_history(**args) == earlier
    assert earlier.universe.instrument_ids == ("BTC-USDT-SPOT",)


@pytest.mark.parametrize(
    "kind",
    ["missing_parent", "fork", "two_roots", "cycle", "backdated", "same_observation"],
)
def test_invalid_ancestry_is_blocked(kind):
    args = history()
    revision, source = revised(args, T + STEP)
    if kind == "missing_parent":
        revision = replace(revision, supersedes_revision_id=uuid4())
    elif kind == "two_roots":
        revision = replace(revision, supersedes_revision_id=None)
    elif kind == "cycle":
        args["revisions"] = (
            replace(args["revisions"][0], supersedes_revision_id=revision.revision_id),
        )
    elif kind == "backdated":
        args["revisions"] = (
            replace(args["revisions"][0], availability_time=T + 2 * STEP),
        )
    elif kind == "same_observation":
        revision = replace(
            revision,
            observation=replace(
                revision.observation,
                market_data_id=args["revisions"][0].observation.market_data_id,
            ),
        )
    include(args, revision, source)
    if kind == "fork":
        args["revisions"] += (
            replace(
                revision,
                revision_id=uuid4(),
                observation=replace(revision.observation, market_data_id=uuid4()),
            ),
        )
    with pytest.raises(PointInTimeError):
        reconstruct_history(**args)


@pytest.mark.parametrize(
    "kind",
    [
        "late_universe",
        "universe_end",
        "wrong_pin",
        "missing_source",
        "coverage",
        "wrong_provider",
        "late_source",
        "wrong_lineage",
        "dataset_sources",
    ],
)
def test_bad_provenance_or_scope_is_blocked(kind):
    args = history()
    if kind == "late_universe":
        args["universe"] = replace(args["universe"], availability_time=T + 3 * STEP)
        args["expected_universe_sha256"] = canonical_sha256(args["universe"])
    elif kind == "universe_end":
        args["cutoff"] = args["universe"].effective_until
    elif kind == "wrong_pin":
        args["expected_universe_sha256"] = "0" * 64
    elif kind == "missing_source":
        args["sources"] = args["sources"][:1]
    elif kind == "coverage":
        args["universe"] = replace(
            args["universe"], instrument_ids=("BTC-USDT-SPOT", "DELISTED-USDT-SPOT")
        )
        args["expected_universe_sha256"] = canonical_sha256(args["universe"])
    elif kind == "wrong_provider":
        args["revisions"] = (replace(args["revisions"][0], provider_id="other"),)
    elif kind == "late_source":
        args["sources"] = (
            replace(
                args["sources"][0],
                retrieval_time=T + 3 * STEP,
                availability_time=T + 3 * STEP,
            ),
            args["sources"][1],
        )
    elif kind == "wrong_lineage":
        args["expected_lineage_sha256"] = "0" * 64
    elif kind == "dataset_sources":
        args["dataset"] = replace(args["dataset"], source_record_ids=(uuid4(),))
    with pytest.raises(PointInTimeError):
        reconstruct_history(**args)


def test_new_contracts_use_existing_canonical_serialization():
    args = history()
    manifest = reconstruct_history(**args).manifest
    for record, contract_id in (
        (args["universe"], "C-101"),
        (args["revisions"][0], "C-102"),
        (manifest, "C-103"),
    ):
        serialized = serialize_contract(record, payload_version="wire-1")
        assert_canonical_round_trip(
            ContractHarnessCase.from_contract(record, payload_version="wire-1")
        )
        assert serialized == serialize_contract(record, payload_version="wire-1")
        assert json.loads(serialized)["contract_id"] == contract_id
        assert (
            describe_dataclass_contract(
                type(record), payload_version="wire-1"
            ).schema_version
            == "1"
        )


@pytest.mark.parametrize(
    "changes",
    [
        {"complete": False},
        {"effective_from": T.replace(tzinfo=None)},
        {"instrument_ids": ("BTC", "BTC")},
    ],
)
def test_invalid_universe_contract(changes):
    with pytest.raises(MarketDataContractError):
        replace(history()["universe"], **changes)


def test_unknown_order_policy_and_naive_revision_time_rejected():
    revision = history()["revisions"][0]
    for changes in (
        {"ordering_policy": "guess-latest"},
        {"publication_time": T.replace(tzinfo=None)},
    ):
        with pytest.raises(MarketDataContractError):
            replace(revision, **changes)


def test_closed_candle_evidence_is_required_and_validated():
    args = history()
    revision = args["revisions"][0]
    candle = replace(revision.observation, observation_type="OHLCV")
    with pytest.raises(MarketDataContractError):
        replace(revision, observation=candle)
    args["revisions"] = (
        replace(revision, observation=candle, finalized_interval_end=T + STEP),
    )
    assert reconstruct_history(**args).selected_revisions == args["revisions"]


def test_manifest_rejects_unpinned_selection():
    manifest = reconstruct_history(**history()).manifest
    with pytest.raises(MarketDataContractError):
        replace(manifest, selected_revision_ids=(uuid4(),))
