"""Synthetic, non-factual OHLCV fixtures; no provider or market assertion."""

from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal
from hashlib import sha256
from uuid import uuid4

import pytest
from trading_platform_api.market_data import (
    CandleNormalizationError,
    CandlePolicy,
    DataSourceRecord,
    MarketData,
    RawCandle,
    normalize_ohlcv,
)

MONDAY = datetime(2026, 1, 5, tzinfo=UTC)
ONE_MINUTE = timedelta(minutes=1)


def policy(**changes: object) -> CandlePolicy:
    values: dict[str, object] = {
        "instrument_id": "synthetic-instrument",
        "venue_id": "synthetic-venue",
        "timeframe": "1m",
        "price_unit": "synthetic-quote",
        "volume_unit": "synthetic-base",
        "price_places": 2,
        "volume_places": 3,
        "maximum_records": 12,
    }
    values.update(changes)
    return CandlePolicy(**values)  # type: ignore[arg-type]


def candle(
    opened: datetime = MONDAY,
    *,
    span: timedelta = ONE_MINUTE,
    **changes: object,
) -> RawCandle:
    values: dict[str, object] = {
        "source_record_id": uuid4(),
        "market_data_id": uuid4(),
        "instrument_id": "synthetic-instrument",
        "venue_id": "synthetic-venue",
        "timeframe": "1m",
        "open_time": opened,
        "open": Decimal("10.00"),
        "high": Decimal("11.00"),
        "low": Decimal("9.00"),
        "close": Decimal("10.50"),
        "volume": Decimal("2.000"),
        "price_unit": "synthetic-quote",
        "volume_unit": "synthetic-base",
        "trade_count": 2,
        "is_final": True,
        "raw_source_bytes": b"synthetic fixture only",
        "provider_id": "synthetic-provider",
        "provider_version": "fixture-v1",
        "raw_schema_version": "fixture-schema-v1",
        "adapter_version": "fixture-adapter-v1",
        "licensing_reference": "synthetic-fixture",
        "provider_event_time": opened + span / 2,
        "retrieval_time": opened + span,
        "ingestion_time": opened + span + timedelta(seconds=1),
        "availability_time": opened + span + timedelta(seconds=2),
    }
    values.update(changes)
    return RawCandle(**values)  # type: ignore[arg-type]


def test_exact_canonical_output_and_raw_provenance() -> None:
    raw = candle()
    result = normalize_ohlcv((raw,), policy())
    assert result.timeframe == "1m"
    assert len(result.source_records) == len(result.market_data) == 1
    source, data = result.source_records[0], result.market_data[0]
    assert type(source) is DataSourceRecord
    assert type(data) is MarketData
    assert (source.contract_id, data.contract_id) == ("C-091", "C-001")
    assert source.source_record_id == data.source_record_id == raw.source_record_id
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
    assert data.event_time == MONDAY
    assert data.provider_time == raw.provider_event_time
    assert data.ingestion_time == raw.ingestion_time
    assert data.availability_time == raw.availability_time
    assert data.observation_type == "OHLCV"
    assert tuple(item.metric_name for item in data.metrics) == (
        "open",
        "high",
        "low",
        "close",
        "volume",
        "trade_count",
    )
    assert tuple(item.unit for item in data.metrics) == (
        "synthetic-quote",
        "synthetic-quote",
        "synthetic-quote",
        "synthetic-quote",
        "synthetic-base",
        "count",
    )
    assert result.quality.empty is False
    assert result.quality.missing_open_times == ()
    assert "synthetic fixture only" not in repr(raw)


def test_offset_timestamps_normalize_to_utc_and_open_time_is_canonical() -> None:
    offset = timezone(timedelta(hours=5, minutes=30))
    local_open = MONDAY.astimezone(offset)
    raw = candle(
        local_open,
        provider_event_time=(MONDAY + timedelta(seconds=30)).astimezone(offset),
        retrieval_time=(MONDAY + ONE_MINUTE).astimezone(offset),
        ingestion_time=(MONDAY + timedelta(seconds=61)).astimezone(offset),
        availability_time=(MONDAY + timedelta(seconds=62)).astimezone(offset),
    )
    result = normalize_ohlcv((raw,), policy())
    assert result.market_data[0].event_time is not local_open
    assert result.market_data[0].event_time == MONDAY
    assert result.source_records[0].availability_time.tzinfo is UTC


@pytest.mark.parametrize(
    "timeframe,span",
    [
        ("1m", 60),
        ("3m", 180),
        ("5m", 300),
        ("15m", 900),
        ("30m", 1800),
        ("1h", 3600),
        ("2h", 7200),
        ("4h", 14400),
        ("6h", 21600),
        ("12h", 43200),
        ("1d", 86400),
        ("1w", 604800),
    ],
)
def test_each_supported_timeframe_including_monday_week_anchor(
    timeframe: str, span: int
) -> None:
    raw = candle(timeframe=timeframe, span=timedelta(seconds=span))
    assert normalize_ohlcv((raw,), policy(timeframe=timeframe)).timeframe == timeframe


def test_unsupported_misaligned_or_naive_times_fail() -> None:
    with pytest.raises(CandleNormalizationError, match="Unsupported timeframe"):
        policy(timeframe="1M")
    for opened in (MONDAY + timedelta(seconds=1), MONDAY.replace(tzinfo=None)):
        with pytest.raises(CandleNormalizationError):
            normalize_ohlcv((candle(opened),), policy())
    with pytest.raises(CandleNormalizationError, match="align"):
        normalize_ohlcv(
            (candle(timeframe="1w", span=timedelta(weeks=1)),),
            policy(timeframe="1w"),
            range_start=MONDAY + timedelta(days=1),
            range_end=MONDAY + timedelta(weeks=1),
        )
    with pytest.raises(CandleNormalizationError, match="timezone-aware"):
        normalize_ohlcv(
            (candle(),),
            policy(),
            range_start=MONDAY.replace(tzinfo=None),
            range_end=MONDAY + ONE_MINUTE,
        )


@pytest.mark.parametrize(
    "field,value",
    [
        ("open", Decimal("0")),
        ("high", Decimal("9.99")),
        ("low", Decimal("10.51")),
        ("close", Decimal("-1")),
        ("volume", Decimal("-1")),
        ("volume", Decimal("NaN")),
        ("open", Decimal("Infinity")),
        ("open", 10.0),
        ("close", Decimal("10.501")),
        ("volume", Decimal("2.0001")),
    ],
)
def test_invalid_ohlc_decimal_and_precision_rejected(field: str, value: object) -> None:
    with pytest.raises(CandleNormalizationError):
        normalize_ohlcv((candle(**{field: value}),), policy())


def test_precision_policy_is_explicit_and_never_rounds() -> None:
    raw = candle(close=Decimal("10.50"))
    assert next(
        metric.value
        for metric in normalize_ohlcv((raw,), policy()).market_data[0].metrics
        if metric.metric_name == "close"
    ) == Decimal("10.50")
    with pytest.raises(CandleNormalizationError, match="precision"):
        normalize_ohlcv((raw,), policy(price_places=1))
    for invalid in (True, -1, 19):
        with pytest.raises(CandleNormalizationError):
            policy(price_places=invalid)


def test_missing_intervals_are_reported_without_filling() -> None:
    first = candle()
    third = candle(MONDAY + 2 * ONE_MINUTE)
    result = normalize_ohlcv(
        (first, third), policy(), range_start=MONDAY, range_end=MONDAY + 4 * ONE_MINUTE
    )
    assert tuple(item.event_time for item in result.market_data) == (
        MONDAY,
        MONDAY + 2 * ONE_MINUTE,
    )
    assert result.quality.missing_open_times == (
        MONDAY + ONE_MINUTE,
        MONDAY + 3 * ONE_MINUTE,
    )
    assert len(result.source_records) == 2


def test_implicit_gap_is_bounded_and_reported() -> None:
    result = normalize_ohlcv((candle(), candle(MONDAY + 2 * ONE_MINUTE)), policy())
    assert result.quality.missing_open_times == (MONDAY + ONE_MINUTE,)
    with pytest.raises(CandleNormalizationError, match="Implicit range"):
        normalize_ohlcv((candle(), candle(MONDAY + 12 * ONE_MINUTE)), policy())


def test_duplicate_open_identity_out_of_order_and_mixed_provider_rejected() -> None:
    first = candle()
    for second in (
        candle(),
        candle(MONDAY - ONE_MINUTE),
        candle(MONDAY + ONE_MINUTE, source_record_id=first.source_record_id),
        candle(MONDAY + ONE_MINUTE, market_data_id=first.market_data_id),
        candle(MONDAY + ONE_MINUTE, provider_id="other-provider"),
        candle(MONDAY + ONE_MINUTE, raw_schema_version="other-schema"),
        candle(MONDAY + ONE_MINUTE, licensing_reference="other-license"),
    ):
        with pytest.raises(CandleNormalizationError):
            normalize_ohlcv((first, second), policy())


def test_zero_volume_provisional_and_absent_trade_count_are_explicit() -> None:
    raw = candle(
        volume=Decimal("0.000"),
        trade_count=None,
        is_final=False,
        retrieval_time=MONDAY + timedelta(seconds=30),
        ingestion_time=MONDAY + timedelta(seconds=31),
        availability_time=MONDAY + timedelta(seconds=32),
    )
    result = normalize_ohlcv((raw,), policy())
    assert result.quality.zero_volume_open_times == (MONDAY,)
    assert result.quality.provisional_open_times == (MONDAY,)
    assert "trade_count" not in {
        metric.metric_name for metric in result.market_data[0].metrics
    }
    with pytest.raises(CandleNormalizationError, match="Final candle"):
        normalize_ohlcv((replace(raw, is_final=True),), policy())


def test_empty_batch_and_range_bounds_have_no_quality_approval() -> None:
    result = normalize_ohlcv(
        (), policy(), range_start=MONDAY, range_end=MONDAY + 2 * ONE_MINUTE
    )
    assert result.quality.empty is True
    assert result.quality.missing_open_times == (MONDAY, MONDAY + ONE_MINUTE)
    assert result.source_records == result.market_data == ()
    assert not hasattr(result.quality, "status")
    with pytest.raises(CandleNormalizationError, match="Requested range"):
        normalize_ohlcv(
            (), policy(), range_start=MONDAY, range_end=MONDAY + 13 * ONE_MINUTE
        )
    with pytest.raises(CandleNormalizationError, match="outside requested range"):
        normalize_ohlcv(
            (candle(),),
            policy(),
            range_start=MONDAY + ONE_MINUTE,
            range_end=MONDAY + 2 * ONE_MINUTE,
        )


def test_source_hash_bytes_chronology_and_units_fail_closed() -> None:
    for raw in (
        candle(raw_source_bytes=b""),
        candle(raw_source_bytes="not bytes"),
        candle(provider_event_time=MONDAY - timedelta(seconds=1)),
        candle(availability_time=MONDAY + timedelta(seconds=30)),
        candle(volume_unit="unapproved-unit"),
        candle(timeframe="5m"),
        candle(licensing_reference=" "),
        candle(licensing_reference="token=not-a-real-value"),
    ):
        with pytest.raises(CandleNormalizationError):
            normalize_ohlcv((raw,), policy())
    with pytest.raises(CandleNormalizationError, match="bounded raw_source_bytes"):
        normalize_ohlcv(
            (candle(raw_source_bytes=b"x" * 9),),
            policy(maximum_source_bytes=8),
        )


def test_no_partial_success_on_invalid_second_candle_and_no_mutation() -> None:
    first = candle()
    second = candle(MONDAY + ONE_MINUTE, high=Decimal("1.00"))
    with pytest.raises(CandleNormalizationError, match="OHLC"):
        normalize_ohlcv((first, second), policy())
    with pytest.raises(FrozenInstanceError):
        first.close = Decimal("1")  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        policy().timeframe = "5m"  # type: ignore[misc]


def test_bounded_batch_and_input_types() -> None:
    with pytest.raises(CandleNormalizationError, match="maximum_records"):
        normalize_ohlcv(
            tuple(candle(MONDAY + i * ONE_MINUTE) for i in range(13)), policy()
        )
    with pytest.raises(CandleNormalizationError, match="tuple"):
        normalize_ohlcv([candle()], policy())  # type: ignore[arg-type]
    with pytest.raises(CandleNormalizationError, match="non-negative"):
        normalize_ohlcv((candle(trade_count=-1),), policy())
    with pytest.raises(CandleNormalizationError, match="Range boundaries"):
        normalize_ohlcv((candle(),), policy(), range_start=MONDAY)
    with pytest.raises(CandleNormalizationError, match="maximum_source_bytes"):
        policy(maximum_source_bytes=0)
