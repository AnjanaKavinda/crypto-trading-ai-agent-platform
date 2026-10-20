from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from hashlib import sha256
from uuid import uuid4

import pytest
from trading_platform_api.market_data.on_chain import (
    AssetAttribution,
    FinalityStatus,
    OnChainNormalizationError,
    OnChainPolicy,
    RawOnChainObservation,
    normalize_on_chain,
)

T0 = datetime(2026, 1, 1, tzinfo=UTC)
POLICY = OnChainPolicy("eip155:1", "ethereum-mainnet", "ETH")


def observation(**changes: object) -> RawOnChainObservation:
    values: dict[str, object] = {
        "source_record_id": uuid4(),
        "provider_event_id": "event-1",
        "chain_id": POLICY.chain_id,
        "network_id": POLICY.network_id,
        "asset_id": POLICY.asset_id,
        "asset_attribution": AssetAttribution.OBSERVED,
        "metric_name": "active_addresses",
        "value": Decimal("1250"),
        "unit": "addresses",
        "observation_time": T0,
        "provider_time": T0,
        "retrieval_time": T0 + timedelta(seconds=1),
        "ingestion_time": T0 + timedelta(seconds=2),
        "availability_time": T0 + timedelta(seconds=3),
        "provider_id": "synthetic-provider",
        "provider_version": "1",
        "raw_schema_version": "1",
        "adapter_version": "1",
        "licensing_reference": "synthetic-fixture",
        "finality_status": FinalityStatus.FINALIZED,
        "finality_basis": "provider-finalized",
        "block_height": 100,
        "block_hash": "block-100",
        "parent_block_hash": "block-99",
        "window_start": None,
        "window_end": None,
        "reorged_event_id": None,
        "raw_source_bytes": b'{"synthetic":true,"count":1250}',
    }
    values.update(changes)
    return RawOnChainObservation(**values)  # type: ignore[arg-type]


def test_normalization_preserves_chain_finality_units_and_source_lineage() -> None:
    item = observation()
    result = normalize_on_chain((item,), POLICY)

    assert len(result.source_records) == len(result.on_chain_data) == 1
    source = result.source_records[0]
    assert source.content_sha256 == sha256(item.raw_source_bytes).hexdigest()
    assert source.provider_event_time == T0
    data = result.on_chain_data[0]
    assert data.source_record_id == item.source_record_id
    assert data.metrics[0].metric_name == "active_addresses"
    assert data.metrics[0].value == Decimal("1250")
    assert data.metrics[0].unit == "addresses"
    identity = result.identities[0]
    assert identity.chain_id == "eip155:1"
    assert identity.network_id == "ethereum-mainnet"
    assert identity.asset_id == "ETH"
    assert identity.asset_attribution is AssetAttribution.OBSERVED
    assert identity.provider_time == T0
    assert identity.retrieval_time == T0 + timedelta(seconds=1)
    assert identity.ingestion_time == T0 + timedelta(seconds=2)
    assert identity.availability_time == T0 + timedelta(seconds=3)
    assert identity.finality_status is FinalityStatus.FINALIZED
    assert identity.finality_basis == "provider-finalized"
    assert identity.block_height == 100
    assert identity.block_hash == "block-100"
    assert identity.parent_block_hash == "block-99"
    assert result.duplicate_event_ids == ()


def test_unknown_finality_and_aggregate_window_remain_explicit() -> None:
    item = observation(
        asset_attribution=AssetAttribution.INFERRED,
        finality_status=FinalityStatus.UNKNOWN,
        finality_basis=None,
        block_height=None,
        block_hash=None,
        parent_block_hash=None,
        window_start=T0 - timedelta(hours=1),
        window_end=T0 - timedelta(minutes=1),
    )
    result = normalize_on_chain((item,), POLICY)
    identity = result.identities[0]
    assert identity.asset_attribution is AssetAttribution.INFERRED
    assert identity.finality_status is FinalityStatus.UNKNOWN
    assert identity.finality_basis is None
    assert identity.block_height is None
    assert identity.window_start == T0 - timedelta(hours=1)
    assert identity.window_end == T0 - timedelta(minutes=1)


def test_non_canonical_observation_keeps_explicit_reorg_reference() -> None:
    item = observation(
        provider_event_id="reorg-event",
        finality_status=FinalityStatus.NON_CANONICAL,
        reorged_event_id="original-event",
    )
    result = normalize_on_chain((item,), POLICY)
    assert result.identities[0].finality_status is FinalityStatus.NON_CANONICAL
    assert result.identities[0].reorged_event_id == "original-event"


def test_exact_duplicate_is_reported_but_conflicting_event_is_rejected() -> None:
    item = observation()
    duplicate = normalize_on_chain((item, item), POLICY)
    assert len(duplicate.on_chain_data) == 1
    assert duplicate.duplicate_event_ids == ("event-1",)

    conflict = replace(item, value=Decimal("1251"))
    with pytest.raises(OnChainNormalizationError, match="Conflicting"):
        normalize_on_chain((item, conflict), POLICY)


@pytest.mark.parametrize(
    "changes",
    [
        {"chain_id": "eip155:10"},
        {"asset_attribution": "INFERRED"},
        {"network_id": ""},
        {"asset_id": "BTC"},
        {"value": Decimal("NaN")},
        {"raw_source_bytes": b""},
        {"block_height": None},
        {"block_hash": None},
        {"finality_basis": None},
        {
            "block_height": None,
            "block_hash": None,
            "parent_block_hash": "parent-without-block",
        },
        {
            "finality_status": FinalityStatus.NON_CANONICAL,
            "reorged_event_id": None,
        },
        {
            "finality_status": FinalityStatus.NON_CANONICAL,
            "reorged_event_id": "event-1",
        },
        {
            "finality_status": FinalityStatus.UNKNOWN,
            "finality_basis": "invented-finality",
        },
        {
            "window_start": T0,
            "window_end": T0,
        },
        {
            "window_start": T0 - timedelta(minutes=1),
            "window_end": T0 + timedelta(minutes=1),
        },
        {"availability_time": T0},
    ],
)
def test_invalid_or_ambiguous_observations_fail_closed(
    changes: dict[str, object],
) -> None:
    with pytest.raises(OnChainNormalizationError):
        normalize_on_chain((observation(**changes),), POLICY)


def test_out_of_order_observations_and_oversized_batches_fail_closed() -> None:
    first = observation()
    second = observation(
        provider_event_id="event-2",
        source_record_id=uuid4(),
        observation_time=T0 - timedelta(seconds=1),
        provider_time=T0,
        retrieval_time=T0 + timedelta(seconds=1),
        ingestion_time=T0 + timedelta(seconds=2),
        availability_time=T0 + timedelta(seconds=3),
    )
    with pytest.raises(OnChainNormalizationError, match="Out-of-order"):
        normalize_on_chain((first, second), POLICY)

    small_policy = replace(POLICY, maximum_records=1)
    with pytest.raises(OnChainNormalizationError, match="exceeds policy"):
        normalize_on_chain((first, second), small_policy)
