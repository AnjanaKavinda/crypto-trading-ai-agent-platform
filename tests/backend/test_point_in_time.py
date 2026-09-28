"""Synthetic historical evidence; no historical performance claims."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from trading_platform_api.market_data.contracts import (
    CONTRACT_SCHEMA_VERSION,
    DatasetVersion,
    DatasetVersionReference,
    DataSourceRecord,
    FundamentalData,
    MarketData,
    MarketSnapshot,
    MetricValue,
)
from trading_platform_api.market_data.point_in_time import (
    PointInTimeError,
    reconstruct_pinned_snapshot,
)

T = datetime(2026, 1, 1, tzinfo=UTC)
STEP = timedelta(minutes=1)


def evidence():
    source = DataSourceRecord(
        uuid4(),
        "fixture",
        "1",
        T,
        T + STEP,
        T + STEP,
        "raw-1",
        "adapter-1",
        "synthetic",
        "a" * 64,
    )
    data = MarketData(
        uuid4(),
        "BTC-USDT-SPOT",
        "fixture",
        "TRADE",
        T,
        T,
        T + STEP,
        T + STEP,
        source.source_record_id,
        (MetricValue("price", Decimal("10"), "USDT"),),
    )
    dataset = DatasetVersion(
        "fixture",
        "1",
        T + 3 * STEP,
        T,
        T + 2 * STEP,
        T + 2 * STEP,
        (source.source_record_id,),
        CONTRACT_SCHEMA_VERSION,
        "b" * 64,
    )
    snapshot = MarketSnapshot(
        uuid4(),
        T + 2 * STEP,
        T + 3 * STEP,
        data.instrument_id,
        data.venue_id,
        (data.market_data_id,),
        (source.source_record_id,),
        DatasetVersionReference("fixture", "1"),
    )
    return dict(
        snapshot=snapshot,
        dataset=dataset,
        observations=(data,),
        sources=(source,),
        expected_lineage_sha256="b" * 64,
        survivorship_sensitive=False,
    )


def test_exact_pinned_snapshot_at_boundary():
    args = evidence()
    source = replace(args["sources"][0], availability_time=T + 2 * STEP)
    data = replace(args["observations"][0], availability_time=T + 2 * STEP)
    args.update(sources=(source,), observations=(data,))
    result = reconstruct_pinned_snapshot(**args)
    assert result.snapshot is args["snapshot"]
    assert result.observations == (data,)


@pytest.mark.parametrize("field", ["availability_time", "retrieval_time"])
def test_late_source_or_historical_backfill_blocked(field):
    args = evidence()
    changes = {"availability_time": T + 3 * STEP}
    changes[field] = T + 3 * STEP
    args["sources"] = (replace(args["sources"][0], **changes),)
    with pytest.raises(PointInTimeError):
        reconstruct_pinned_snapshot(**args)


@pytest.mark.parametrize("change", ["version", "lineage", "cutoff", "schema"])
def test_dataset_pin_mismatch(change):
    args = evidence()
    changes = {
        "version": {"version": "revised"},
        "lineage": {"lineage_sha256": "c" * 64},
        "cutoff": {"point_in_time_cutoff": T + 3 * STEP},
        "schema": {"canonical_schema_version": "unknown"},
    }
    args["dataset"] = replace(args["dataset"], **changes[change])
    with pytest.raises(PointInTimeError):
        reconstruct_pinned_snapshot(**args)


@pytest.mark.parametrize("change", ["late", "unknown_source", "venue", "duplicate"])
def test_observation_failures(change):
    args = evidence()
    data = args["observations"][0]
    changes = {
        "late": {"availability_time": T + 3 * STEP},
        "unknown_source": {"source_record_id": uuid4()},
        "venue": {"venue_id": "another-venue"},
        "duplicate": {},
    }
    updated = replace(data, **changes[change])
    args["observations"] = (updated, updated) if change == "duplicate" else (updated,)
    with pytest.raises(PointInTimeError):
        reconstruct_pinned_snapshot(**args)


def test_survivorship_claim_is_explicitly_blocked():
    args = evidence()
    args["survivorship_sensitive"] = True
    with pytest.raises(PointInTimeError, match="universe-membership"):
        reconstruct_pinned_snapshot(**args)


def test_new_revision_cannot_replace_pinned_observation():
    args = evidence()
    revised = replace(args["observations"][0], market_data_id=uuid4())
    args["observations"] = (revised,)
    with pytest.raises(PointInTimeError, match="membership"):
        reconstruct_pinned_snapshot(**args)


def test_duplicate_source_cannot_hide_conflicting_revision():
    args = evidence()
    source = args["sources"][0]
    args["sources"] = (source, replace(source, content_sha256="d" * 64))
    with pytest.raises(PointInTimeError, match="membership"):
        reconstruct_pinned_snapshot(**args)


def test_result_uses_snapshot_order_not_input_order():
    args = evidence()
    first = args["observations"][0]
    second = replace(
        first, market_data_id=uuid4(), event_time=T + STEP, provider_time=T + STEP
    )
    args["snapshot"] = replace(
        args["snapshot"], market_data_ids=(first.market_data_id, second.market_data_id)
    )
    args["observations"] = (second, first)
    assert reconstruct_pinned_snapshot(**args).observations == (first, second)


@pytest.mark.parametrize("end", [None, T + 3 * STEP, T.replace(tzinfo=None)])
def test_unproven_future_or_naive_candle_close_blocked(end):
    args = evidence()
    data = replace(args["observations"][0], observation_type="OHLCV")
    args["observations"] = (data,)
    args["finalized_candle_ends"] = () if end is None else ((data.market_data_id, end),)
    with pytest.raises(PointInTimeError):
        reconstruct_pinned_snapshot(**args)


def test_closed_candle_with_pinned_finality():
    args = evidence()
    data = replace(args["observations"][0], observation_type="OHLCV")
    args["observations"] = (data,)
    args["finalized_candle_ends"] = ((data.market_data_id, T + STEP),)
    assert reconstruct_pinned_snapshot(**args).observations == (data,)


def test_embedded_revision_cannot_predate_its_source_availability():
    args = evidence()
    source = args["sources"][0]
    embedded = FundamentalData(
        T, T, source.source_record_id, args["observations"][0].metrics
    )
    args["snapshot"] = replace(args["snapshot"], fundamental_data=(embedded,))
    with pytest.raises(PointInTimeError, match="Embedded"):
        reconstruct_pinned_snapshot(**args)
