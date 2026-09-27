"""Deterministic OHLCV normalization; no provider parsing or quality approval."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from hashlib import sha256
from uuid import UUID

from trading_platform_api.market_data.contracts import (
    DataSourceRecord,
    MarketData,
    MetricValue,
)


class CandleNormalizationError(ValueError):
    """Sanitized rejection of an entire invalid candle batch."""


_TIMEFRAMES = {
    "1m": 60,
    "3m": 180,
    "5m": 300,
    "15m": 900,
    "30m": 1800,
    "1h": 3600,
    "2h": 7200,
    "4h": 14400,
    "6h": 21600,
    "12h": 43200,
    "1d": 86400,
    "1w": 604800,
}
_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
_WEEK_ANCHOR = datetime(1970, 1, 5, tzinfo=UTC)
_MAX_RECORDS = 10_000
_MAX_SOURCE_BYTES = 1_048_576
_SENSITIVE_REFERENCE = re.compile(
    r"(?i)(://[^/\s:@]+:[^/\s@]+@|\b(?:token|password|secret|api[-_ ]?key)\s*[:=]|\bbearer\s+\S+)"
)


def _text(name: str, value: object) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or len(value) > 255
        or any(ord(char) < 32 for char in value)
        or _SENSITIVE_REFERENCE.search(value)
    ):
        raise CandleNormalizationError(f"{name} must be a bounded identifier.")
    return value


def _utc(name: str, value: object) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise CandleNormalizationError(f"{name} must be timezone-aware.")
    if value.utcoffset() is None:
        raise CandleNormalizationError(f"{name} must be timezone-aware.")
    return value.astimezone(UTC)


def _uuid(name: str, value: object) -> None:
    if not isinstance(value, UUID):
        raise CandleNormalizationError(f"{name} must be a UUID.")


def _aligned(name: str, value: datetime, step: int, timeframe: str) -> None:
    anchor = _WEEK_ANCHOR if timeframe == "1w" else _EPOCH
    elapsed = value - anchor
    if elapsed.microseconds or (elapsed.days * 86400 + elapsed.seconds) % step:
        raise CandleNormalizationError(f"{name} must align to the timeframe.")


def _decimal(name: str, value: object, places: int, *, positive: bool) -> Decimal:
    if not isinstance(value, Decimal) or not value.is_finite():
        raise CandleNormalizationError(f"{name} must be a finite Decimal.")
    if value < 0 or (positive and value == 0):
        raise CandleNormalizationError(f"{name} has an invalid sign.")
    exponent = value.as_tuple().exponent
    if not isinstance(exponent, int) or exponent < -places:
        raise CandleNormalizationError(f"{name} exceeds configured precision.")
    return value


@dataclass(frozen=True, slots=True)
class CandlePolicy:
    instrument_id: str
    venue_id: str
    timeframe: str
    price_unit: str
    volume_unit: str
    price_places: int
    volume_places: int
    maximum_records: int = 1000
    maximum_source_bytes: int = _MAX_SOURCE_BYTES

    def __post_init__(self) -> None:
        for name in ("instrument_id", "venue_id", "price_unit", "volume_unit"):
            _text(name, getattr(self, name))
        if type(self.timeframe) is not str or self.timeframe not in _TIMEFRAMES:
            raise CandleNormalizationError("Unsupported timeframe.")
        for name in ("price_places", "volume_places"):
            value = getattr(self, name)
            if type(value) is not int or not 0 <= value <= 18:
                raise CandleNormalizationError(f"{name} must be an integer in [0, 18].")
        if (
            type(self.maximum_records) is not int
            or not 1 <= self.maximum_records <= _MAX_RECORDS
        ):
            raise CandleNormalizationError("maximum_records is out of bounds.")
        if (
            type(self.maximum_source_bytes) is not int
            or not 1 <= self.maximum_source_bytes <= _MAX_SOURCE_BYTES
        ):
            raise CandleNormalizationError("maximum_source_bytes is out of bounds.")


@dataclass(frozen=True, slots=True)
class RawCandle:
    source_record_id: UUID
    market_data_id: UUID
    instrument_id: str
    venue_id: str
    timeframe: str
    open_time: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal
    price_unit: str
    volume_unit: str
    trade_count: int | None
    is_final: bool
    raw_source_bytes: bytes = field(repr=False)
    provider_id: str
    provider_version: str
    raw_schema_version: str
    adapter_version: str
    licensing_reference: str
    provider_event_time: datetime
    retrieval_time: datetime
    ingestion_time: datetime
    availability_time: datetime


@dataclass(frozen=True, slots=True)
class CandleQualityReport:
    """Findings only; this is not the canonical C-003 quality verdict."""

    missing_open_times: tuple[datetime, ...]
    zero_volume_open_times: tuple[datetime, ...]
    provisional_open_times: tuple[datetime, ...]
    empty: bool


@dataclass(frozen=True, slots=True)
class NormalizedCandles:
    timeframe: str
    source_records: tuple[DataSourceRecord, ...]
    market_data: tuple[MarketData, ...]
    quality: CandleQualityReport


def normalize_ohlcv(
    candles: tuple[RawCandle, ...],
    policy: CandlePolicy,
    *,
    range_start: datetime | None = None,
    range_end: datetime | None = None,
) -> NormalizedCandles:
    """Normalize one bounded ordered batch; requested range is half-open.

    Provider adapters must pass exact raw bytes and vetted identity metadata.
    A rejection yields no partial canonical result or external side effect.
    """
    if not isinstance(policy, CandlePolicy):
        raise CandleNormalizationError("policy must be a CandlePolicy.")
    if not isinstance(candles, tuple) or not all(
        type(item) is RawCandle for item in candles
    ):
        raise CandleNormalizationError("candles must be a tuple of RawCandle.")
    if len(candles) > policy.maximum_records:
        raise CandleNormalizationError("Candle batch exceeds maximum_records.")
    if (range_start is None) != (range_end is None):
        raise CandleNormalizationError("Range boundaries must be supplied together.")
    step = _TIMEFRAMES[policy.timeframe]
    start: datetime | None
    end: datetime | None
    if range_start is not None and range_end is not None:
        start = _utc("range_start", range_start)
        end = _utc("range_end", range_end)
        _aligned("range_start", start, step, policy.timeframe)
        _aligned("range_end", end, step, policy.timeframe)
        if end <= start:
            raise CandleNormalizationError("Range end must follow range start.")
        if (end - start) // timedelta(seconds=step) > policy.maximum_records:
            raise CandleNormalizationError("Requested range exceeds maximum_records.")
    else:
        start = end = None

    sources: list[DataSourceRecord] = []
    observations: list[MarketData] = []
    zero_volume: list[datetime] = []
    provisional: list[datetime] = []
    opens: list[datetime] = []
    source_ids: set[UUID] = set()
    observation_ids: set[UUID] = set()
    previous: datetime | None = None
    provider_identity: tuple[str, str, str, str, str] | None = None

    for index, candle in enumerate(candles):
        _uuid("source_record_id", candle.source_record_id)
        _uuid("market_data_id", candle.market_data_id)
        if (
            candle.source_record_id in source_ids
            or candle.market_data_id in observation_ids
        ):
            raise CandleNormalizationError("Duplicate canonical identity.")
        source_ids.add(candle.source_record_id)
        observation_ids.add(candle.market_data_id)
        for name, expected in (
            ("instrument_id", policy.instrument_id),
            ("venue_id", policy.venue_id),
            ("timeframe", policy.timeframe),
            ("price_unit", policy.price_unit),
            ("volume_unit", policy.volume_unit),
        ):
            if _text(name, getattr(candle, name)) != expected:
                raise CandleNormalizationError(f"Candle {index} has mismatched {name}.")
        for name in (
            "provider_id",
            "provider_version",
            "raw_schema_version",
            "adapter_version",
            "licensing_reference",
        ):
            _text(name, getattr(candle, name))
        identity = (
            candle.provider_id,
            candle.provider_version,
            candle.raw_schema_version,
            candle.adapter_version,
            candle.licensing_reference,
        )
        if provider_identity is not None and identity != provider_identity:
            raise CandleNormalizationError("Mixed source schema or identity in batch.")
        provider_identity = identity
        opened = _utc("open_time", candle.open_time)
        _aligned("open_time", opened, step, policy.timeframe)
        if previous is not None and opened <= previous:
            raise CandleNormalizationError("Duplicate or out-of-order candle.")
        previous = opened
        if start is not None and end is not None and not start <= opened < end:
            raise CandleNormalizationError("Candle outside requested range.")
        values = {
            name: _decimal(
                name,
                getattr(candle, name),
                policy.volume_places if name == "volume" else policy.price_places,
                positive=name != "volume",
            )
            for name in ("open", "high", "low", "close", "volume")
        }
        if (
            values["high"] < max(values["open"], values["close"])
            or values["low"] > min(values["open"], values["close"])
            or values["high"] < values["low"]
        ):
            raise CandleNormalizationError("Invalid OHLC relationship.")
        if candle.trade_count is not None and (
            type(candle.trade_count) is not int or candle.trade_count < 0
        ):
            raise CandleNormalizationError("trade_count must be non-negative.")
        if type(candle.is_final) is not bool:
            raise CandleNormalizationError("is_final must be a boolean.")
        if (
            type(candle.raw_source_bytes) is not bytes
            or not 0 < len(candle.raw_source_bytes) <= policy.maximum_source_bytes
        ):
            raise CandleNormalizationError(
                "Exact bounded raw_source_bytes are required."
            )
        event = _utc("provider_event_time", candle.provider_event_time)
        retrieval = _utc("retrieval_time", candle.retrieval_time)
        ingestion = _utc("ingestion_time", candle.ingestion_time)
        available = _utc("availability_time", candle.availability_time)
        if not opened <= event <= retrieval <= ingestion <= available:
            raise CandleNormalizationError("Invalid source timestamp chronology.")
        if candle.is_final and retrieval < opened + timedelta(seconds=step):
            raise CandleNormalizationError(
                "Final candle retrieved before interval end."
            )

        sources.append(
            DataSourceRecord(
                source_record_id=candle.source_record_id,
                provider_id=candle.provider_id,
                provider_version=candle.provider_version,
                provider_event_time=event,
                retrieval_time=retrieval,
                availability_time=available,
                raw_schema_version=candle.raw_schema_version,
                adapter_version=candle.adapter_version,
                licensing_reference=candle.licensing_reference,
                content_sha256=sha256(candle.raw_source_bytes).hexdigest(),
            )
        )
        metrics = tuple(
            MetricValue(
                name,
                values[name],
                policy.volume_unit if name == "volume" else policy.price_unit,
            )
            for name in ("open", "high", "low", "close", "volume")
        )
        if candle.trade_count is not None:
            metrics += (
                MetricValue("trade_count", Decimal(candle.trade_count), "count"),
            )
        observations.append(
            MarketData(
                market_data_id=candle.market_data_id,
                instrument_id=policy.instrument_id,
                venue_id=policy.venue_id,
                observation_type="OHLCV",
                event_time=opened,
                provider_time=event,
                ingestion_time=ingestion,
                availability_time=available,
                source_record_id=candle.source_record_id,
                metrics=metrics,
            )
        )
        opens.append(opened)
        if values["volume"] == 0:
            zero_volume.append(opened)
        if not candle.is_final:
            provisional.append(opened)

    if start is None or end is None:
        start = opens[0] if opens else None
        end = opens[-1] + timedelta(seconds=step) if opens else None
        if (
            start is not None
            and end is not None
            and ((end - start) // timedelta(seconds=step) > policy.maximum_records)
        ):
            raise CandleNormalizationError("Implicit range exceeds maximum_records.")
    missing: list[datetime] = []
    if start is not None and end is not None:
        present = set(opens)
        cursor = start
        while cursor < end:
            if cursor not in present:
                missing.append(cursor)
            cursor += timedelta(seconds=step)
    return NormalizedCandles(
        timeframe=policy.timeframe,
        source_records=tuple(sources),
        market_data=tuple(observations),
        quality=CandleQualityReport(
            missing_open_times=tuple(missing),
            zero_volume_open_times=tuple(zero_volume),
            provisional_open_times=tuple(provisional),
            empty=not candles,
        ),
    )
