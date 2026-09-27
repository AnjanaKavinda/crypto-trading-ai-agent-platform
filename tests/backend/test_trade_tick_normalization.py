"""Synthetic, non-factual trade/tick fixtures with no live provider access."""

from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal
from hashlib import sha256
from uuid import uuid4

import pytest
from trading_platform_api.market_data import (
    DataSourceRecord,
    MarketData,
    NormalizedTradeTicks,
    ProviderDataKind,
    RawTradeTick,
    ReportedSide,
    SideSemantics,
    TradeTickNormalizationError,
    TradeTickPolicy,
    normalize_trade_ticks,
)

T0 = datetime(2026, 1, 1, tzinfo=UTC)


def policy(**changes: object) -> TradeTickPolicy:
    values: dict[str, object] = {
        "instrument_id": "synthetic-instrument",
        "venue_id": "synthetic-venue",
        "data_kind": ProviderDataKind.TRADE,
        "price_unit": "synthetic-quote",
        "quantity_unit": "synthetic-base",
        "price_places": 2,
        "quantity_places": 3,
        "maximum_records": 5,
    }
    values.update(changes)
    return TradeTickPolicy(**values)  # type: ignore[arg-type]


def event(
    event_id: str = "synthetic-event-1",
    *,
    when: datetime = T0,
    **changes: object,
) -> RawTradeTick:
    values: dict[str, object] = {
        "source_record_id": uuid4(),
        "market_data_id": uuid4(),
        "provider_event_id": event_id,
        "instrument_id": "synthetic-instrument",
        "venue_id": "synthetic-venue",
        "data_kind": ProviderDataKind.TRADE,
        "event_time": when,
        "price": Decimal("10.50"),
        "quantity": Decimal("2.000"),
        "price_unit": "synthetic-quote",
        "quantity_unit": "synthetic-base",
        "reported_side": ReportedSide.BUY,
        "side_semantics": SideSemantics.UNKNOWN,
        "sequence": None,
        "sequence_scope": None,
        "raw_source_bytes": b"synthetic event payload",
        "provider_id": "synthetic-provider",
        "provider_version": "fixture-v1",
        "raw_schema_version": "fixture-schema-v1",
        "adapter_version": "fixture-adapter-v1",
        "licensing_reference": "synthetic-fixture",
        "retrieval_time": when + timedelta(seconds=1),
        "ingestion_time": when + timedelta(seconds=2),
        "availability_time": when + timedelta(seconds=3),
    }
    values.update(changes)
    return RawTradeTick(**values)  # type: ignore[arg-type]


def test_trade_canonical_records_preserve_provider_event_identity() -> None:
    raw = event()
    result = normalize_trade_ticks((raw,), policy())
    assert type(result) is NormalizedTradeTicks
    assert result.data_kind is ProviderDataKind.TRADE
    source, data, identity = (
        result.source_records[0],
        result.market_data[0],
        result.identities[0],
    )
    assert type(source) is DataSourceRecord
    assert type(data) is MarketData
    assert (source.contract_id, data.contract_id) == ("C-091", "C-001")
    assert identity.provider_event_id == raw.provider_event_id
    assert identity.source_record_id == source.source_record_id == data.source_record_id
    assert identity.market_data_id == data.market_data_id == raw.market_data_id
    assert source.content_sha256 == sha256(raw.raw_source_bytes).hexdigest()
    assert (source.provider_id, source.provider_version) == (
        raw.provider_id,
        raw.provider_version,
    )
    assert (source.raw_schema_version, source.adapter_version) == (
        raw.raw_schema_version,
        raw.adapter_version,
    )
    assert source.licensing_reference == raw.licensing_reference
    assert data.event_time == data.provider_time == raw.event_time
    assert data.ingestion_time == raw.ingestion_time
    assert data.availability_time == raw.availability_time
    assert data.observation_type == "TRADE"
    assert tuple(metric.metric_name for metric in data.metrics) == ("price", "quantity")
    assert tuple(metric.unit for metric in data.metrics) == (
        "synthetic-quote",
        "synthetic-base",
    )
    assert result.quality.unknown_aggressor_event_ids == (raw.provider_event_id,)
    assert result.quality.sequence_verified is False
    assert "synthetic event payload" not in repr(raw)


def test_tick_requires_identity_but_allows_absent_quantity() -> None:
    raw = event(data_kind=ProviderDataKind.TICK, quantity=None)
    result = normalize_trade_ticks((raw,), policy(data_kind=ProviderDataKind.TICK))
    assert result.market_data[0].observation_type == "TICK"
    assert tuple(metric.metric_name for metric in result.market_data[0].metrics) == (
        "price",
    )
    assert result.identities[0].provider_event_id == raw.provider_event_id
    with pytest.raises(TradeTickNormalizationError, match="quantity"):
        normalize_trade_ticks((event(quantity=None),), policy())
    with pytest.raises(TradeTickNormalizationError, match="provider_event_id"):
        normalize_trade_ticks((event(event_id=" "),), policy())


@pytest.mark.parametrize(
    ("semantics", "reported", "expected"),
    [
        (SideSemantics.UNKNOWN, ReportedSide.BUY, ReportedSide.UNKNOWN),
        (SideSemantics.MAKER, ReportedSide.SELL, ReportedSide.UNKNOWN),
        (SideSemantics.AGGRESSOR, ReportedSide.UNKNOWN, ReportedSide.UNKNOWN),
        (SideSemantics.AGGRESSOR, ReportedSide.BUY, ReportedSide.BUY),
        (SideSemantics.AGGRESSOR, ReportedSide.SELL, ReportedSide.SELL),
    ],
)
def test_only_authoritative_aggressor_side_produces_signed_metric(
    semantics: SideSemantics, reported: ReportedSide, expected: ReportedSide
) -> None:
    raw = event(side_semantics=semantics, reported_side=reported)
    result = normalize_trade_ticks((raw,), policy())
    identity = result.identities[0]
    assert (identity.reported_side, identity.side_semantics) == (reported, semantics)
    assert identity.aggressor_side is expected
    signed = [
        metric
        for metric in result.market_data[0].metrics
        if metric.metric_name == "aggressor_sign"
    ]
    if expected is ReportedSide.UNKNOWN:
        assert signed == []
        assert result.quality.unknown_aggressor_event_ids == (raw.provider_event_id,)
    else:
        assert len(signed) == 1
        assert signed[0].value == (
            Decimal(1) if expected is ReportedSide.BUY else Decimal(-1)
        )
        assert signed[0].unit == "sign"
        assert result.quality.unknown_aggressor_event_ids == ()


def test_identical_retransmission_deduplicates_within_this_batch_only() -> None:
    first = event()
    retransmit = event()
    second = event("synthetic-event-2", when=T0 + timedelta(seconds=1))
    result = normalize_trade_ticks((first, second, retransmit), policy())
    assert (
        len(result.source_records)
        == len(result.market_data)
        == len(result.identities)
        == 2
    )
    assert result.quality.duplicate_event_ids == (first.provider_event_id,)
    assert tuple(identity.provider_event_id for identity in result.identities) == (
        first.provider_event_id,
        second.provider_event_id,
    )
    assert (
        normalize_trade_ticks((retransmit,), policy()).quality.duplicate_event_ids == ()
    )


@pytest.mark.parametrize(
    "change",
    [
        {"raw_source_bytes": b"different fixture payload"},
        {"price": Decimal("11.00")},
        {"side_semantics": SideSemantics.MAKER},
        {"sequence": 2, "sequence_scope": "synthetic-stream"},
    ],
)
def test_conflicting_duplicate_rejects_entire_batch(change: dict[str, object]) -> None:
    with pytest.raises(TradeTickNormalizationError, match="Conflicting provider"):
        normalize_trade_ticks((event(), event(**change)), policy())


def test_equal_event_timestamps_with_distinct_ids_are_valid() -> None:
    result = normalize_trade_ticks((event(), event("synthetic-event-2")), policy())
    assert len(result.market_data) == 2
    assert result.market_data[0].event_time == result.market_data[1].event_time


def test_sequence_scope_and_contiguity_are_verified_only_when_authoritative() -> None:
    first = event(sequence=77, sequence_scope="synthetic-stream")
    second = event(
        "synthetic-event-2",
        when=T0 + timedelta(seconds=1),
        sequence=78,
        sequence_scope="synthetic-stream",
    )
    result = normalize_trade_ticks((first, second), policy())
    assert result.quality.sequence_verified is True
    assert tuple(identity.sequence for identity in result.identities) == (77, 78)
    for changed in (
        replace(second, sequence=79),
        replace(second, sequence=77),
        replace(second, sequence_scope="other-stream"),
        replace(second, sequence=None, sequence_scope=None),
    ):
        with pytest.raises(TradeTickNormalizationError):
            normalize_trade_ticks((first, changed), policy())
    with pytest.raises(TradeTickNormalizationError, match="together"):
        normalize_trade_ticks((replace(first, sequence_scope=None),), policy())


def test_out_of_order_timestamps_and_duplicate_canonical_ids_fail() -> None:
    first = event(when=T0 + timedelta(seconds=1))
    with pytest.raises(TradeTickNormalizationError, match="Out-of-order"):
        normalize_trade_ticks((first, event("synthetic-event-2")), policy())
    with pytest.raises(TradeTickNormalizationError, match="canonical identity"):
        normalize_trade_ticks(
            (
                first,
                event(
                    "synthetic-event-2",
                    when=T0 + timedelta(seconds=2),
                    market_data_id=first.market_data_id,
                ),
            ),
            policy(),
        )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("price", Decimal("0")),
        ("price", Decimal("-1")),
        ("price", Decimal("NaN")),
        ("price", Decimal("Infinity")),
        ("price", Decimal("10.501")),
        ("price", 10.5),
        ("quantity", Decimal("0")),
        ("quantity", Decimal("-1")),
        ("quantity", Decimal("2.0001")),
        ("quantity", True),
    ],
)
def test_invalid_numeric_values_and_precision_rejected(
    field: str, value: object
) -> None:
    with pytest.raises(TradeTickNormalizationError):
        normalize_trade_ticks((event(**{field: value}),), policy())


def test_timezone_and_source_chronology_are_exact() -> None:
    offset = timezone(timedelta(hours=5, minutes=30))
    local = T0.astimezone(offset)
    raw = event(
        when=local,
        retrieval_time=(T0 + timedelta(seconds=1)).astimezone(offset),
        ingestion_time=(T0 + timedelta(seconds=2)).astimezone(offset),
        availability_time=(T0 + timedelta(seconds=3)).astimezone(offset),
    )
    result = normalize_trade_ticks((raw,), policy())
    assert result.market_data[0].event_time == T0
    assert result.market_data[0].event_time.tzinfo is UTC
    for invalid in (
        event(when=T0.replace(tzinfo=None)),
        event(retrieval_time=T0 - timedelta(seconds=1)),
        event(availability_time=T0 + timedelta(seconds=1)),
    ):
        with pytest.raises(TradeTickNormalizationError):
            normalize_trade_ticks((invalid,), policy())


def test_policy_mismatch_schema_drift_and_secret_reference_fail() -> None:
    first = event()
    for invalid in (
        event(instrument_id="other-instrument"),
        event(venue_id="other-venue"),
        event(price_unit="other-unit"),
        event(data_kind=ProviderDataKind.TICK),
        event(licensing_reference="token=" + "synthetic"),
    ):
        with pytest.raises(TradeTickNormalizationError):
            normalize_trade_ticks((invalid,), policy())
    for second in (
        event("synthetic-event-2", raw_schema_version="other-schema"),
        event("synthetic-event-2", provider_id="other-provider"),
        event("synthetic-event-2", adapter_version="other-adapter"),
    ):
        with pytest.raises(TradeTickNormalizationError, match="Mixed source"):
            normalize_trade_ticks((first, second), policy())


def test_empty_and_bounded_batches_without_quality_approval() -> None:
    empty = normalize_trade_ticks((), policy())
    assert empty.market_data == empty.source_records == empty.identities == ()
    assert empty.quality.empty is True
    assert empty.quality.sequence_verified is False
    assert not hasattr(empty.quality, "status")
    with pytest.raises(TradeTickNormalizationError, match="maximum_records"):
        normalize_trade_ticks(tuple(event(f"event-{i}") for i in range(6)), policy())
    with pytest.raises(TradeTickNormalizationError, match="bounded raw_source_bytes"):
        normalize_trade_ticks(
            (event(raw_source_bytes=b"x" * 9),), policy(maximum_source_bytes=8)
        )
    with pytest.raises(TradeTickNormalizationError, match="tuple"):
        normalize_trade_ticks([event()], policy())  # type: ignore[arg-type]


def test_immutable_inputs_and_rejection_do_not_emit_partial_result() -> None:
    valid = event()
    with pytest.raises(TradeTickNormalizationError, match="positive"):
        normalize_trade_ticks(
            (valid, event("synthetic-event-2", price=Decimal("-1"))), policy()
        )
    with pytest.raises(FrozenInstanceError):
        valid.price = Decimal("20")  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        policy().data_kind = ProviderDataKind.TICK  # type: ignore[misc]


def test_invalid_policy_boundaries() -> None:
    for changes in (
        {"data_kind": "TRADE"},
        {"data_kind": ProviderDataKind.OHLCV},
        {"price_places": True},
        {"quantity_places": 19},
        {"maximum_records": 0},
        {"maximum_source_bytes": 0},
    ):
        with pytest.raises(TradeTickNormalizationError):
            policy(**changes)
