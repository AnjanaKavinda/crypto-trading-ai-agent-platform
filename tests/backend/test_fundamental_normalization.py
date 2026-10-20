from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from hashlib import sha256
from uuid import uuid4

import pytest
from trading_platform_api.market_data.fundamentals import (
    FundamentalNormalizationError,
    FundamentalPolicy,
    RawFundamentalObservation,
    normalize_fundamentals,
)

T0 = datetime(2026, 1, 1, tzinfo=UTC)
POLICY = FundamentalPolicy("asset:ETH")


def observation(**changes: object) -> RawFundamentalObservation:
    values: dict[str, object] = {
        "source_record_id": uuid4(),
        "provider_event_id": "event-1",
        "asset_id": POLICY.asset_id,
        "metric_name": "circulating_supply",
        "value": Decimal("120000000"),
        "unit": "ETH",
        "publication_time": T0,
        "effective_time": T0,
        "provider_time": T0 + timedelta(seconds=1),
        "retrieval_time": T0 + timedelta(seconds=2),
        "ingestion_time": T0 + timedelta(seconds=3),
        "availability_time": T0 + timedelta(seconds=4),
        "revision_id": "revision-1",
        "supersedes_revision_id": None,
        "provider_id": "synthetic-provider",
        "provider_version": "1",
        "raw_schema_version": "1",
        "adapter_version": "1",
        "licensing_reference": "synthetic-fixture",
        "raw_source_bytes": b'{"synthetic":true,"supply":"120000000"}',
    }
    values.update(changes)
    return RawFundamentalObservation(**values)  # type: ignore[arg-type]


def test_normalization_preserves_publication_effective_revision_and_lineage() -> None:
    item = observation(
        effective_time=T0 + timedelta(days=90),
        revision_id="revision-2",
        supersedes_revision_id="revision-1",
    )
    result = normalize_fundamentals((item,), POLICY)

    assert len(result.source_records) == len(result.fundamental_data) == 1
    source = result.source_records[0]
    assert source.content_sha256 == sha256(item.raw_source_bytes).hexdigest()
    assert source.provider_event_time == item.provider_time
    canonical = result.fundamental_data[0]
    assert canonical.observation_time == item.publication_time
    assert canonical.availability_time == item.availability_time
    assert canonical.source_record_id == item.source_record_id
    assert canonical.metrics[0].metric_name == "circulating_supply"
    assert canonical.metrics[0].value == Decimal("120000000")
    assert canonical.metrics[0].unit == "ETH"
    identity = result.identities[0]
    assert identity.publication_time == T0
    assert identity.effective_time == T0 + timedelta(days=90)
    assert identity.provider_time == T0 + timedelta(seconds=1)
    assert identity.retrieval_time == T0 + timedelta(seconds=2)
    assert identity.ingestion_time == T0 + timedelta(seconds=3)
    assert identity.availability_time == T0 + timedelta(seconds=4)
    assert identity.revision_id == "revision-2"
    assert identity.supersedes_revision_id == "revision-1"


def test_revisions_are_preserved_as_observations_without_overwriting_history() -> None:
    first = observation()
    second = observation(
        source_record_id=uuid4(),
        provider_event_id="event-2",
        value=Decimal("119000000"),
        revision_id="revision-2",
        supersedes_revision_id="revision-1",
        provider_time=T0 + timedelta(minutes=1),
        retrieval_time=T0 + timedelta(minutes=2),
        ingestion_time=T0 + timedelta(minutes=3),
        availability_time=T0 + timedelta(minutes=4),
    )
    result = normalize_fundamentals((first, second), POLICY)

    assert len(result.fundamental_data) == 2
    assert tuple(item.value for row in result.fundamental_data for item in row.metrics) == (
        Decimal("120000000"),
        Decimal("119000000"),
    )
    assert tuple(identity.revision_id for identity in result.identities) == (
        "revision-1",
        "revision-2",
    )


def test_exact_duplicate_is_reported_but_conflicting_event_is_rejected() -> None:
    item = observation()
    duplicate = normalize_fundamentals((item, item), POLICY)
    assert len(duplicate.fundamental_data) == 1
    assert duplicate.duplicate_event_ids == ("event-1",)

    conflict = replace(item, value=Decimal("120000001"))
    with pytest.raises(FundamentalNormalizationError, match="Conflicting"):
        normalize_fundamentals((item, conflict), POLICY)


@pytest.mark.parametrize(
    "changes",
    [
        {"asset_id": "asset:BTC"},
        {"metric_name": ""},
        {"unit": " "},
        {"value": Decimal("NaN")},
        {"raw_source_bytes": b""},
        {"revision_id": ""},
        {
            "revision_id": "revision-1",
            "supersedes_revision_id": "revision-1",
        },
        {"publication_time": T0 + timedelta(days=1)},
    ],
)
def test_invalid_or_ambiguous_observations_fail_closed(
    changes: dict[str, object],
) -> None:
    with pytest.raises(FundamentalNormalizationError):
        normalize_fundamentals((observation(**changes),), POLICY)


def test_duplicate_revision_identity_and_batch_bounds_fail_closed() -> None:
    first = observation()
    duplicate_revision = observation(
        source_record_id=uuid4(),
        provider_event_id="event-2",
    )
    with pytest.raises(FundamentalNormalizationError, match="Duplicate revision"):
        normalize_fundamentals((first, duplicate_revision), POLICY)

    small_policy = replace(POLICY, maximum_records=1)
    second = observation(
        source_record_id=uuid4(),
        provider_event_id="event-2",
        revision_id="revision-2",
    )
    with pytest.raises(FundamentalNormalizationError, match="exceeds policy"):
        normalize_fundamentals((first, second), small_policy)



def test_raw_source_bytes_are_bounded_by_policy() -> None:
    policy = replace(POLICY, maximum_source_bytes=4)
    with pytest.raises(FundamentalNormalizationError, match="bounded raw source"):
        normalize_fundamentals(
            (observation(raw_source_bytes=b"12345"),),
            policy,
        )
