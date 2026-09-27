"""Synthetic, non-factual order-book fixtures; no live provider algorithm."""

from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal
from hashlib import sha256
from uuid import uuid4

import pytest
from trading_platform_api.market_data import (
    BookDelta,
    BookFailure,
    BookLevel,
    BookPolicy,
    BookSide,
    BookSnapshot,
    BookSource,
    BookStatus,
    ChecksumStatus,
    LevelChange,
    OrderBookError,
    apply_book_delta,
    normalize_book_snapshot,
)

T0 = datetime(2026, 1, 1, tzinfo=UTC)


def policy(**changes: object) -> BookPolicy:
    values: dict[str, object] = {
        "instrument_id": "synthetic-instrument",
        "venue_id": "synthetic-venue",
        "price_unit": "synthetic-quote",
        "quantity_unit": "synthetic-base",
        "price_places": 2,
        "quantity_places": 3,
        "maximum_depth": 3,
        "maximum_age_seconds": 60,
        "maximum_lineage": 3,
        "extreme_spread_bps": Decimal("100"),
    }
    values.update(changes)
    return BookPolicy(**values)  # type: ignore[arg-type]


def source(
    event_id: str = "synthetic-snapshot", when: datetime = T0, **changes: object
) -> BookSource:
    values: dict[str, object] = {
        "source_record_id": uuid4(),
        "market_data_id": uuid4(),
        "event_id": event_id,
        "instrument_id": "synthetic-instrument",
        "venue_id": "synthetic-venue",
        "provider_id": "synthetic-provider",
        "provider_version": "fixture-v1",
        "raw_schema_version": "fixture-schema-v1",
        "adapter_version": "fixture-adapter-v1",
        "licensing_reference": "synthetic-fixture",
        "event_time": when,
        "retrieval_time": when + timedelta(seconds=1),
        "ingestion_time": when + timedelta(seconds=2),
        "availability_time": when + timedelta(seconds=3),
        "raw_source_bytes": b"synthetic raw book",
    }
    values.update(changes)
    return BookSource(**values)  # type: ignore[arg-type]


def snapshot(**changes: object) -> BookSnapshot:
    values: dict[str, object] = {
        "source": source(),
        "bids": (
            BookLevel(Decimal("98.00"), Decimal("1.000")),
            BookLevel(Decimal("99.00"), Decimal("2.000")),
        ),
        "asks": (
            BookLevel(Decimal("102.00"), Decimal("1.000")),
            BookLevel(Decimal("101.00"), Decimal("3.000")),
        ),
        "sequence": 10,
        "checksum": None,
    }
    values.update(changes)
    return BookSnapshot(**values)  # type: ignore[arg-type]


def delta(event_id: str = "synthetic-delta", **changes: object) -> BookDelta:
    values: dict[str, object] = {
        "source": source(event_id, T0 + timedelta(seconds=4)),
        "changes": (
            LevelChange(BookSide.BID, Decimal("100.00"), Decimal("2.000")),
            LevelChange(BookSide.ASK, Decimal("102.00"), Decimal("0.000")),
        ),
        "sequence_start": 11,
        "sequence_end": 11,
        "checksum": None,
    }
    values.update(changes)
    return BookDelta(**values)  # type: ignore[arg-type]


def contiguous(previous: int, start: int, end: int) -> bool:
    """Synthetic verifier used only by these non-factual fixtures."""
    return start == previous + 1 and end == start


def initial(*, selected_policy: BookPolicy | None = None):
    return normalize_book_snapshot(
        snapshot(), selected_policy or policy(), as_of=T0 + timedelta(seconds=3)
    )


def test_snapshot_sorted_canonical_output_provenance_and_quality() -> None:
    item = snapshot()
    result = normalize_book_snapshot(item, policy(), as_of=T0 + timedelta(seconds=3))
    assert result.state.status is BookStatus.VALID
    assert result.state.sequence == 10
    assert tuple(level.price for level in result.state.bids) == (
        Decimal("99.00"),
        Decimal("98.00"),
    )
    assert tuple(level.price for level in result.state.asks) == (
        Decimal("101.00"),
        Decimal("102.00"),
    )
    assert result.state.source_lineage == (item.source.source_record_id,)
    assert result.state.market_data_ids == (item.source.market_data_id,)
    assert result.source_record is not None and result.market_data is not None
    assert (result.source_record.contract_id, result.market_data.contract_id) == (
        "C-091",
        "C-001",
    )
    assert (
        result.source_record.content_sha256
        == sha256(item.source.raw_source_bytes).hexdigest()
    )
    assert result.source_record.source_record_id == result.market_data.source_record_id
    assert result.market_data.observation_type == "ORDER_BOOK"
    assert tuple(metric.metric_name for metric in result.market_data.metrics) == (
        "bid_1_price",
        "bid_1_quantity",
        "bid_2_price",
        "bid_2_quantity",
        "ask_1_price",
        "ask_1_quantity",
        "ask_2_price",
        "ask_2_quantity",
    )
    assert result.quality.checksum is ChecksumStatus.NOT_AVAILABLE
    assert result.quality.extreme_spread is True
    assert "synthetic raw book" not in repr(item)


def test_delta_replace_delete_and_full_lineage_handoff() -> None:
    before = initial()
    change = delta()
    result = apply_book_delta(
        before.state,
        change,
        policy(),
        as_of=T0 + timedelta(seconds=7),
        sequence_verifier=contiguous,
    )
    assert result.state.status is BookStatus.VALID
    assert result.state.sequence == 11
    assert tuple(level.price for level in result.state.bids) == (
        Decimal("100.00"),
        Decimal("99.00"),
        Decimal("98.00"),
    )
    assert tuple(level.price for level in result.state.asks) == (Decimal("101.00"),)
    assert result.quality.extreme_spread is False
    assert result.source_record is not None and result.market_data is not None
    assert result.market_data.source_record_id == change.source.source_record_id
    assert result.state.source_lineage == (
        before.state.source_lineage[0],
        change.source.source_record_id,
    )
    assert result.market_data.metrics[0].metric_name == "bid_1_price"
    assert result.market_data.metrics[0].value == Decimal("100.00")
    assert (
        result.source_record.content_sha256
        == sha256(change.source.raw_source_bytes).hexdigest()
    )


def test_gap_invalidates_and_later_deltas_cannot_restore() -> None:
    before = initial()
    gap = apply_book_delta(
        before.state,
        delta(sequence_start=12, sequence_end=12),
        policy(),
        as_of=T0 + timedelta(seconds=7),
        sequence_verifier=contiguous,
    )
    assert gap.state.status is BookStatus.INVALID
    assert gap.state.failure is BookFailure.SEQUENCE
    assert gap.source_record is gap.market_data is None
    assert gap.quality.checksum is ChecksumStatus.NOT_AVAILABLE
    later = apply_book_delta(
        gap.state,
        delta("later"),
        policy(),
        as_of=T0 + timedelta(seconds=7),
        sequence_verifier=contiguous,
    )
    assert later.state.status is BookStatus.INVALID
    assert later.market_data is None
    assert later.state.source_lineage == before.state.source_lineage


def test_explicit_snapshot_reinitializes_matching_invalid_state() -> None:
    invalid = apply_book_delta(
        initial().state,
        delta(sequence_start=12),
        policy(),
        as_of=T0 + timedelta(seconds=7),
        sequence_verifier=contiguous,
    )
    recovered = normalize_book_snapshot(
        snapshot(source=source("new-snapshot", T0 + timedelta(seconds=8)), sequence=30),
        policy(),
        as_of=T0 + timedelta(seconds=11),
        resync_of=invalid.state,
    )
    assert recovered.state.status is BookStatus.VALID
    assert recovered.state.sequence == 30
    assert len(recovered.state.source_lineage) == 1
    with pytest.raises(OrderBookError, match="Resync"):
        normalize_book_snapshot(
            snapshot(),
            policy(),
            as_of=T0 + timedelta(seconds=3),
            resync_of=initial().state,
        )


def test_declared_checksum_needs_verifier_and_mismatch_invalidates_delta() -> None:
    with pytest.raises(OrderBookError, match="verifier"):
        normalize_book_snapshot(
            snapshot(checksum="synthetic-checksum"),
            policy(),
            as_of=T0 + timedelta(seconds=3),
        )
    verified = normalize_book_snapshot(
        snapshot(checksum="synthetic-checksum"),
        policy(),
        as_of=T0 + timedelta(seconds=3),
        checksum_verifier=lambda bids, asks, checksum: (
            checksum == "synthetic-checksum" and bids[0].price < asks[0].price
        ),
    )
    assert verified.quality.checksum is ChecksumStatus.VERIFIED
    mismatch = apply_book_delta(
        verified.state,
        delta(checksum="synthetic-wrong"),
        policy(),
        as_of=T0 + timedelta(seconds=7),
        sequence_verifier=contiguous,
        checksum_verifier=lambda bids, asks, checksum: False,
    )
    assert mismatch.state.failure is BookFailure.CHECKSUM
    assert mismatch.market_data is None


def test_missing_continuity_verifier_or_snapshot_sequence_invalidates() -> None:
    before = initial()
    missing = apply_book_delta(
        before.state,
        delta(),
        policy(),
        as_of=T0 + timedelta(seconds=7),
        sequence_verifier=None,
    )
    assert missing.state.failure is BookFailure.SEQUENCE
    unsequenced = normalize_book_snapshot(
        snapshot(sequence=None),
        policy(),
        as_of=T0 + timedelta(seconds=3),
    )
    result = apply_book_delta(
        unsequenced.state,
        delta(),
        policy(),
        as_of=T0 + timedelta(seconds=7),
        sequence_verifier=contiguous,
    )
    assert result.state.failure is BookFailure.SEQUENCE


@pytest.mark.parametrize(
    "bids,asks",
    [
        ((), (BookLevel(Decimal("101.00"), Decimal("1.000")),)),
        (
            (BookLevel(Decimal("101.00"), Decimal("1.000")),),
            (BookLevel(Decimal("101.00"), Decimal("1.000")),),
        ),
        (
            (BookLevel(Decimal("102.00"), Decimal("1.000")),),
            (BookLevel(Decimal("101.00"), Decimal("1.000")),),
        ),
        (
            (
                BookLevel(Decimal("99.00"), Decimal("1.000")),
                BookLevel(Decimal("99.00"), Decimal("2.000")),
            ),
            (BookLevel(Decimal("101.00"), Decimal("1.000")),),
        ),
        (
            (BookLevel(Decimal("99.00"), Decimal("-1.000")),),
            (BookLevel(Decimal("101.00"), Decimal("1.000")),),
        ),
        (
            (BookLevel(Decimal("99.001"), Decimal("1.000")),),
            (BookLevel(Decimal("101.00"), Decimal("1.000")),),
        ),
    ],
)
def test_snapshot_missing_crossed_duplicate_negative_or_precision_rejected(
    bids: tuple[BookLevel, ...], asks: tuple[BookLevel, ...]
) -> None:
    with pytest.raises(OrderBookError):
        normalize_book_snapshot(
            snapshot(bids=bids, asks=asks),
            policy(),
            as_of=T0 + timedelta(seconds=3),
        )


def test_no_silent_depth_truncation_or_unbounded_lineage() -> None:
    with pytest.raises(OrderBookError, match="depth"):
        normalize_book_snapshot(
            snapshot(), policy(maximum_depth=1), as_of=T0 + timedelta(seconds=3)
        )
    before = initial(selected_policy=policy(maximum_lineage=1))
    result = apply_book_delta(
        before.state,
        delta(),
        policy(maximum_lineage=1),
        as_of=T0 + timedelta(seconds=7),
        sequence_verifier=contiguous,
    )
    assert result.state.failure is BookFailure.LINEAGE
    assert result.market_data is None


def test_zero_delete_unknown_level_and_crossed_delta_invalidate() -> None:
    for changes, reason in (
        (
            (LevelChange(BookSide.BID, Decimal("97.00"), Decimal("0.000")),),
            BookFailure.INVALID_INPUT,
        ),
        (
            (LevelChange(BookSide.BID, Decimal("102.00"), Decimal("1.000")),),
            BookFailure.CROSSED,
        ),
        (
            (LevelChange(BookSide.BID, Decimal("100.00"), Decimal("-1.000")),),
            BookFailure.INVALID_INPUT,
        ),
    ):
        result = apply_book_delta(
            initial().state,
            delta(changes=changes),
            policy(),
            as_of=T0 + timedelta(seconds=7),
            sequence_verifier=contiguous,
        )
        assert result.state.failure is reason
        assert result.market_data is None


def test_duplicate_delta_is_explicit_and_conflict_invalidates() -> None:
    before = initial()
    item = delta()
    first = apply_book_delta(
        before.state,
        item,
        policy(),
        as_of=T0 + timedelta(seconds=7),
        sequence_verifier=contiguous,
    )
    duplicate = apply_book_delta(
        first.state,
        item,
        policy(),
        as_of=T0 + timedelta(seconds=7),
        sequence_verifier=contiguous,
    )
    assert duplicate.quality.duplicate is True
    assert duplicate.market_data is None
    assert duplicate.state == first.state
    conflict = apply_book_delta(
        first.state,
        replace(item, checksum="different"),
        policy(),
        as_of=T0 + timedelta(seconds=7),
        sequence_verifier=contiguous,
    )
    assert conflict.state.failure is BookFailure.DUPLICATE_CONFLICT


def test_stale_and_out_of_order_events_invalidate_without_book_output() -> None:
    before = initial()
    short_age_policy = policy(maximum_age_seconds=4)
    short_age_state = initial(selected_policy=short_age_policy)
    stale = apply_book_delta(
        short_age_state.state,
        delta(),
        short_age_policy,
        as_of=T0 + timedelta(seconds=10),
        sequence_verifier=contiguous,
    )
    assert stale.state.failure is BookFailure.STALE
    older = apply_book_delta(
        before.state,
        delta(source=source("older", T0 - timedelta(seconds=1))),
        policy(),
        as_of=T0 + timedelta(seconds=7),
        sequence_verifier=contiguous,
    )
    assert older.market_data is None
    assert older.state.status is BookStatus.INVALID
    bad_as_of = apply_book_delta(
        before.state,
        delta(),
        policy(),
        as_of=T0.replace(tzinfo=None),
        sequence_verifier=contiguous,
    )
    assert bad_as_of.state.status is BookStatus.INVALID
    assert bad_as_of.market_data is None


def test_malformed_delta_source_invalidates_without_unhandled_error() -> None:
    malformed = replace(delta(), source=object())  # type: ignore[arg-type]
    result = apply_book_delta(
        initial().state,
        malformed,
        policy(),
        as_of=T0 + timedelta(seconds=7),
        sequence_verifier=contiguous,
    )
    assert result.state.failure is BookFailure.INVALID_INPUT
    assert result.market_data is None


def test_provider_schema_and_canonical_identity_mismatch_invalidate() -> None:
    before = initial()
    changed_policy = apply_book_delta(
        before.state,
        delta(),
        policy(price_unit="another-unit"),
        as_of=T0 + timedelta(seconds=7),
        sequence_verifier=contiguous,
    )
    assert changed_policy.state.failure is BookFailure.IDENTITY
    assert changed_policy.market_data is None
    for invalid in (
        delta(
            source=source(
                "other", T0 + timedelta(seconds=4), provider_id="another-provider"
            )
        ),
        delta(
            source=source(
                "other", T0 + timedelta(seconds=4), raw_schema_version="another-schema"
            )
        ),
        delta(
            source=source(
                "other",
                T0 + timedelta(seconds=4),
                source_record_id=before.state.source_lineage[0],
            )
        ),
    ):
        result = apply_book_delta(
            before.state,
            invalid,
            policy(),
            as_of=T0 + timedelta(seconds=7),
            sequence_verifier=contiguous,
        )
        assert result.state.status is BookStatus.INVALID
        assert result.market_data is None


def test_offset_to_utc_and_invalid_source_boundaries() -> None:
    offset = timezone(timedelta(hours=5, minutes=30))
    local = T0.astimezone(offset)
    item = snapshot(
        source=source(
            when=local,
            retrieval_time=(T0 + timedelta(seconds=1)).astimezone(offset),
            ingestion_time=(T0 + timedelta(seconds=2)).astimezone(offset),
            availability_time=(T0 + timedelta(seconds=3)).astimezone(offset),
        )
    )
    result = normalize_book_snapshot(
        item,
        policy(),
        as_of=(T0 + timedelta(seconds=3)).astimezone(offset),
    )
    assert result.market_data is not None and result.market_data.event_time == T0
    for invalid in (
        source(when=T0.replace(tzinfo=None)),
        source(retrieval_time=T0 - timedelta(seconds=1)),
        source(raw_source_bytes=b""),
        source(licensing_reference="token=" + "synthetic"),
    ):
        with pytest.raises(OrderBookError):
            normalize_book_snapshot(
                snapshot(source=invalid),
                policy(),
                as_of=T0 + timedelta(seconds=3),
            )


def test_immutable_policy_boundaries_and_no_quality_approval() -> None:
    for changes in (
        {"maximum_depth": 0},
        {"maximum_depth": 101},
        {"price_places": True},
        {"quantity_places": 19},
        {"maximum_age_seconds": 0},
        {"maximum_lineage": 0},
        {"maximum_source_bytes": 0},
    ):
        with pytest.raises(OrderBookError):
            policy(**changes)
    state = initial().state
    with pytest.raises(FrozenInstanceError):
        state.sequence = 30  # type: ignore[misc]
    assert not hasattr(initial().quality, "status")
