from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from uuid import uuid4

import pytest
from trading_platform_api.market_data.news_events import (
    EventAssetAttribution,
    EventDisposition,
    EventNormalizationError,
    EventPolicy,
    RawEventObservation,
    normalize_events,
)

T0 = datetime(2026, 1, 1, tzinfo=UTC)
POLICY = EventPolicy()


def observation(**changes: object) -> RawEventObservation:
    values: dict[str, object] = {
        "source_record_id": uuid4(),
        "provider_id": "synthetic-provider",
        "provider_version": "1",
        "raw_schema_version": "1",
        "adapter_version": "1",
        "licensing_reference": "synthetic-fixture",
        "provider_event_id": "provider-event-1",
        "publisher_id": "synthetic-publisher",
        "canonical_event_id": "event-group-1",
        "event_type": "TOKEN_UNLOCK",
        "publication_time": T0,
        "effective_time": T0 + timedelta(days=30),
        "provider_update_time": T0 + timedelta(seconds=1),
        "retrieval_time": T0 + timedelta(seconds=2),
        "ingestion_time": T0 + timedelta(seconds=3),
        "availability_time": T0 + timedelta(seconds=4),
        "disposition": EventDisposition.ORIGINAL,
        "related_event_id": None,
        "asset_ids": ("asset:ETH",),
        "asset_attribution": EventAssetAttribution.OBSERVED,
        "language": "en",
        "raw_source_bytes": b'{"synthetic":true,"event":"unlock"}',
    }
    values.update(changes)
    return RawEventObservation(**values)  # type: ignore[arg-type]


def test_normalization_preserves_event_timing_provenance_and_effective_time() -> None:
    item = observation()
    result = normalize_events((item,), POLICY)

    assert len(result.source_records) == len(result.event_data) == 1
    source = result.source_records[0]
    assert source.content_sha256 == sha256(item.raw_source_bytes).hexdigest()
    assert source.provider_event_time == item.provider_update_time
    canonical = result.event_data[0]
    assert canonical.event_id == item.canonical_event_id
    assert canonical.event_type == "TOKEN_UNLOCK"
    assert canonical.event_time == item.publication_time
    assert canonical.availability_time == item.availability_time
    assert canonical.source_record_id == item.source_record_id
    identity = result.identities[0]
    assert identity.publication_time == T0
    assert identity.effective_time == T0 + timedelta(days=30)
    assert identity.provider_update_time == T0 + timedelta(seconds=1)
    assert identity.retrieval_time == T0 + timedelta(seconds=2)
    assert identity.ingestion_time == T0 + timedelta(seconds=3)
    assert identity.availability_time == T0 + timedelta(seconds=4)
    assert identity.asset_ids == ("asset:ETH",)
    assert identity.asset_attribution is EventAssetAttribution.OBSERVED
    assert identity.language == "en"
    assert result.groups[0].canonical_event_id == item.canonical_event_id
    assert result.groups[0].source_record_ids == (item.source_record_id,)
    assert not hasattr(identity, "raw_source_bytes")
    assert result.duplicate_provider_event_ids == ()


def test_cross_source_grouping_keeps_each_source_reference() -> None:
    first = observation()
    second = observation(
        source_record_id=uuid4(),
        provider_id="second-synthetic-provider",
        provider_version="2",
        provider_event_id="provider-event-2",
        publisher_id="second-synthetic-publisher",
        raw_schema_version="2",
        adapter_version="2",
        licensing_reference="synthetic-fixture-2",
    )
    result = normalize_events((first, second), POLICY)

    assert len(result.event_data) == 2
    assert result.event_data[0].event_id == result.event_data[1].event_id
    assert len(result.groups) == 1
    assert set(result.groups[0].source_record_ids) == {
        first.source_record_id,
        second.source_record_id,
    }
    assert set(result.groups[0].provider_event_ids) == {
        "provider-event-1",
        "provider-event-2",
    }


def test_exact_provider_duplicate_is_removed_and_conflict_is_rejected() -> None:
    item = observation()
    duplicate = normalize_events((item, item), POLICY)
    assert len(duplicate.event_data) == 1
    assert duplicate.duplicate_provider_event_ids == ("provider-event-1",)

    conflict = replace(item, raw_source_bytes=b'{"different":true}')
    with pytest.raises(EventNormalizationError, match="Conflicting"):
        normalize_events((item, conflict), POLICY)


def test_correction_and_retraction_links_remain_explicit() -> None:
    original = observation()
    correction = observation(
        source_record_id=uuid4(),
        provider_event_id="provider-event-correction",
        publication_time=T0 + timedelta(minutes=1),
        provider_update_time=T0 + timedelta(minutes=2),
        retrieval_time=T0 + timedelta(minutes=3),
        ingestion_time=T0 + timedelta(minutes=4),
        availability_time=T0 + timedelta(minutes=5),
        disposition=EventDisposition.CORRECTION,
        related_event_id="provider-event-1",
        raw_source_bytes=b'{"synthetic":true,"correction":true}',
    )
    retraction = observation(
        source_record_id=uuid4(),
        provider_event_id="provider-event-retraction",
        publication_time=T0 + timedelta(minutes=6),
        provider_update_time=T0 + timedelta(minutes=7),
        retrieval_time=T0 + timedelta(minutes=8),
        ingestion_time=T0 + timedelta(minutes=9),
        availability_time=T0 + timedelta(minutes=10),
        disposition=EventDisposition.RETRACTION,
        related_event_id="provider-event-1",
        raw_source_bytes=b'{"synthetic":true,"retraction":true}',
    )
    result = normalize_events((original, correction, retraction), POLICY)

    assert tuple(identity.disposition for identity in result.identities) == (
        EventDisposition.ORIGINAL,
        EventDisposition.CORRECTION,
        EventDisposition.RETRACTION,
    )
    assert result.identities[1].related_event_id == "provider-event-1"
    assert result.identities[2].related_event_id == "provider-event-1"
    assert len(result.groups[0].source_record_ids) == 3


@pytest.mark.parametrize(
    "changes",
    [
        {"event_type": ""},
        {"publication_time": T0 + timedelta(minutes=2)},
        {"asset_ids": ("asset:ETH", "asset:ETH")},
        {"asset_attribution": "INFERRED"},
        {"disposition": "CORRECTION"},
        {
            "disposition": EventDisposition.ORIGINAL,
            "related_event_id": "earlier-event",
        },
        {
            "disposition": EventDisposition.CORRECTION,
            "related_event_id": None,
        },
        {
            "disposition": EventDisposition.CORRECTION,
            "related_event_id": "provider-event-1",
        },
        {"raw_source_bytes": b""},
    ],
)
def test_invalid_or_ambiguous_events_fail_closed(changes: dict[str, object]) -> None:
    with pytest.raises(EventNormalizationError):
        normalize_events((observation(**changes),), POLICY)


def test_conflicting_group_types_and_payload_bounds_fail_closed() -> None:
    first = observation()
    conflict = observation(
        source_record_id=uuid4(),
        provider_event_id="other-provider-event",
        event_type="REGULATORY",
    )
    with pytest.raises(EventNormalizationError, match="conflicting event types"):
        normalize_events((first, conflict), POLICY)

    small_policy = replace(POLICY, maximum_source_bytes=4)
    with pytest.raises(EventNormalizationError, match="bounded raw source"):
        normalize_events((observation(raw_source_bytes=b"12345"),), small_policy)
