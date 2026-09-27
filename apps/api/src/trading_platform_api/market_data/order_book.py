"""Provider-neutral order-book state and canonical observation normalization."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from enum import StrEnum
from fractions import Fraction
from hashlib import sha256
from typing import Protocol
from uuid import UUID

from trading_platform_api.market_data.contracts import (
    DataSourceRecord,
    MarketData,
    MetricValue,
)


class OrderBookError(ValueError):
    """Sanitized invalid input; raw source content is never included."""


class BookStatus(StrEnum):
    VALID = "VALID"
    INVALID = "INVALID"


class ChecksumStatus(StrEnum):
    VERIFIED = "VERIFIED"
    NOT_AVAILABLE = "NOT_AVAILABLE"
    FAILED = "FAILED"


class BookFailure(StrEnum):
    INVALID_INPUT = "INVALID_INPUT"
    IDENTITY = "IDENTITY"
    DUPLICATE_CONFLICT = "DUPLICATE_CONFLICT"
    SEQUENCE = "SEQUENCE"
    CHECKSUM = "CHECKSUM"
    STALE = "STALE"
    CROSSED = "CROSSED"
    DEPTH = "DEPTH"
    LINEAGE = "LINEAGE"


class BookSide(StrEnum):
    BID = "BID"
    ASK = "ASK"


class _BookValidationError(OrderBookError):
    def __init__(self, reason: BookFailure, message: str) -> None:
        self.reason = reason
        super().__init__(message)


class SequenceVerifier(Protocol):
    def __call__(self, previous: int, start: int, end: int) -> bool: ...


class ChecksumVerifier(Protocol):
    def __call__(
        self, bids: tuple[BookLevel, ...], asks: tuple[BookLevel, ...], checksum: str
    ) -> bool: ...


_MAX_SOURCE_BYTES = 1_048_576
_SENSITIVE_TEXT = re.compile(
    r"(?i)(://[^/\s:@]+:[^/\s@]+@|\b(?:token|password|secret|api[-_ ]?key)\s*[:=]|\bbearer\s+\S+)"
)


def _text(name: str, value: object) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or len(value) > 255
        or any(ord(char) < 32 for char in value)
        or _SENSITIVE_TEXT.search(value)
    ):
        raise OrderBookError(f"{name} must be a bounded identifier.")
    return value


def _utc(name: str, value: object) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise OrderBookError(f"{name} must be timezone-aware.")
    if value.utcoffset() is None:
        raise OrderBookError(f"{name} must be timezone-aware.")
    return value.astimezone(UTC)


def _decimal(name: str, value: object, places: int, *, zero: bool = False) -> Decimal:
    if not isinstance(value, Decimal) or not value.is_finite():
        raise OrderBookError(f"{name} must be a finite Decimal.")
    if value < 0 or (not zero and value == 0):
        raise OrderBookError(f"{name} has an invalid sign.")
    exponent = value.as_tuple().exponent
    if not isinstance(exponent, int) or exponent < -places:
        raise OrderBookError(f"{name} exceeds configured precision.")
    return value


def _sequence(name: str, value: object) -> int:
    if type(value) is not int or value < 0:
        raise OrderBookError(f"{name} must be a non-negative integer.")
    return value


@dataclass(frozen=True, slots=True)
class BookLevel:
    price: Decimal
    quantity: Decimal


@dataclass(frozen=True, slots=True)
class LevelChange:
    side: BookSide
    price: Decimal
    quantity: Decimal


@dataclass(frozen=True, slots=True)
class BookPolicy:
    instrument_id: str
    venue_id: str
    price_unit: str
    quantity_unit: str
    price_places: int
    quantity_places: int
    maximum_depth: int
    maximum_age_seconds: int
    maximum_lineage: int = 100
    maximum_source_bytes: int = _MAX_SOURCE_BYTES
    extreme_spread_bps: Decimal | None = None

    def __post_init__(self) -> None:
        for name in ("instrument_id", "venue_id", "price_unit", "quantity_unit"):
            _text(name, getattr(self, name))
        for name in ("price_places", "quantity_places"):
            value = getattr(self, name)
            if type(value) is not int or not 0 <= value <= 18:
                raise OrderBookError(f"{name} must be an integer in [0, 18].")
        for name, value, ceiling in (
            ("maximum_depth", self.maximum_depth, 100),
            ("maximum_age_seconds", self.maximum_age_seconds, 86400),
            ("maximum_lineage", self.maximum_lineage, 1000),
            ("maximum_source_bytes", self.maximum_source_bytes, _MAX_SOURCE_BYTES),
        ):
            if type(value) is not int or not 1 <= value <= ceiling:
                raise OrderBookError(f"{name} is out of bounds.")
        if self.extreme_spread_bps is not None:
            _decimal("extreme_spread_bps", self.extreme_spread_bps, 8)


@dataclass(frozen=True, slots=True)
class BookSource:
    source_record_id: UUID
    market_data_id: UUID
    event_id: str
    instrument_id: str
    venue_id: str
    provider_id: str
    provider_version: str
    raw_schema_version: str
    adapter_version: str
    licensing_reference: str
    event_time: datetime
    retrieval_time: datetime
    ingestion_time: datetime
    availability_time: datetime
    raw_source_bytes: bytes = field(repr=False)


@dataclass(frozen=True, slots=True)
class BookSnapshot:
    source: BookSource
    bids: tuple[BookLevel, ...]
    asks: tuple[BookLevel, ...]
    sequence: int | None
    checksum: str | None = None


@dataclass(frozen=True, slots=True)
class BookDelta:
    source: BookSource
    changes: tuple[LevelChange, ...]
    sequence_start: int
    sequence_end: int
    checksum: str | None = None


@dataclass(frozen=True, slots=True)
class BookFingerprint:
    event_id: str
    digest: str
    event_time: datetime
    sequence_start: int | None
    sequence_end: int | None
    checksum: str | None
    changes: tuple[LevelChange, ...]


@dataclass(frozen=True, slots=True)
class BookState:
    status: BookStatus
    policy: BookPolicy
    instrument_id: str
    venue_id: str
    provider_identity: tuple[str, str, str, str, str]
    bids: tuple[BookLevel, ...]
    asks: tuple[BookLevel, ...]
    sequence: int | None
    event_time: datetime
    source_lineage: tuple[UUID, ...]
    market_data_ids: tuple[UUID, ...]
    fingerprints: tuple[BookFingerprint, ...]
    failure: BookFailure | None = None
    resync_sequence_floor: int | None = None
    resync_event_time_floor: datetime | None = None


@dataclass(frozen=True, slots=True)
class BookQuality:
    checksum: ChecksumStatus
    extreme_spread: bool | None
    duplicate: bool = False


@dataclass(frozen=True, slots=True)
class BookTransition:
    state: BookState
    source_record: DataSourceRecord | None
    market_data: MarketData | None
    quality: BookQuality


def _source(
    source: BookSource, policy: BookPolicy, as_of: datetime
) -> tuple[DataSourceRecord, str]:
    if type(source) is not BookSource:
        raise OrderBookError("source must be a BookSource.")
    if not isinstance(source.source_record_id, UUID) or not isinstance(
        source.market_data_id, UUID
    ):
        raise OrderBookError("Canonical IDs must be UUIDs.")
    for name, expected in (
        ("instrument_id", policy.instrument_id),
        ("venue_id", policy.venue_id),
    ):
        if _text(name, getattr(source, name)) != expected:
            raise OrderBookError(f"Mismatched {name}.")
    for name in (
        "event_id",
        "provider_id",
        "provider_version",
        "raw_schema_version",
        "adapter_version",
        "licensing_reference",
    ):
        _text(name, getattr(source, name))
    if (
        type(source.raw_source_bytes) is not bytes
        or not 0 < len(source.raw_source_bytes) <= policy.maximum_source_bytes
    ):
        raise OrderBookError("Exact bounded raw source bytes are required.")
    event = _utc("event_time", source.event_time)
    retrieved = _utc("retrieval_time", source.retrieval_time)
    ingested = _utc("ingestion_time", source.ingestion_time)
    available = _utc("availability_time", source.availability_time)
    if not event <= retrieved <= ingested <= available <= as_of:
        raise OrderBookError("Invalid source timestamp chronology.")
    if as_of - event > timedelta(seconds=policy.maximum_age_seconds):
        raise _BookValidationError(BookFailure.STALE, "Stale book event.")
    digest = sha256(source.raw_source_bytes).hexdigest()
    return (
        DataSourceRecord(
            source_record_id=source.source_record_id,
            provider_id=source.provider_id,
            provider_version=source.provider_version,
            provider_event_time=event,
            retrieval_time=retrieved,
            availability_time=available,
            raw_schema_version=source.raw_schema_version,
            adapter_version=source.adapter_version,
            licensing_reference=source.licensing_reference,
            content_sha256=digest,
        ),
        digest,
    )


def _identity(source: BookSource) -> tuple[str, str, str, str, str]:
    return (
        source.provider_id,
        source.provider_version,
        source.raw_schema_version,
        source.adapter_version,
        source.licensing_reference,
    )


def _levels(
    levels: tuple[BookLevel, ...], policy: BookPolicy, *, bid: bool
) -> tuple[BookLevel, ...]:
    if (
        not isinstance(levels, tuple)
        or not levels
        or len(levels) > policy.maximum_depth
    ):
        raise _BookValidationError(
            BookFailure.DEPTH, "Book depth or missing side is invalid."
        )
    prices: set[Decimal] = set()
    for level in levels:
        if type(level) is not BookLevel:
            raise OrderBookError("Invalid book level.")
        price = _decimal("price", level.price, policy.price_places)
        _decimal("quantity", level.quantity, policy.quantity_places)
        if price in prices:
            raise OrderBookError("Duplicate price level.")
        prices.add(price)
    return tuple(sorted(levels, key=lambda item: item.price, reverse=bid))


def _spread(
    bids: tuple[BookLevel, ...], asks: tuple[BookLevel, ...], policy: BookPolicy
) -> bool | None:
    if bids[0].price >= asks[0].price:
        raise _BookValidationError(BookFailure.CROSSED, "Crossed or locked order book.")
    if policy.extreme_spread_bps is None:
        return None
    bid = Fraction(bids[0].price)
    ask = Fraction(asks[0].price)
    return (ask - bid) * 20000 >= Fraction(policy.extreme_spread_bps) * (ask + bid)


def _checksum(
    bids: tuple[BookLevel, ...],
    asks: tuple[BookLevel, ...],
    checksum: str | None,
    verifier: ChecksumVerifier | None,
) -> ChecksumStatus:
    if checksum is None:
        return ChecksumStatus.NOT_AVAILABLE
    _text("checksum", checksum)
    if verifier is None:
        raise _BookValidationError(
            BookFailure.CHECKSUM, "Declared checksum requires a verifier."
        )
    try:
        verified = verifier(bids, asks, checksum)
    except Exception as exc:
        raise _BookValidationError(
            BookFailure.CHECKSUM, "Checksum verifier failed."
        ) from exc
    if verified is not True:
        raise _BookValidationError(BookFailure.CHECKSUM, "Checksum mismatch.")
    return ChecksumStatus.VERIFIED


def _observation(
    source: BookSource,
    bids: tuple[BookLevel, ...],
    asks: tuple[BookLevel, ...],
    policy: BookPolicy,
) -> MarketData:
    metrics: list[MetricValue] = []
    for side, levels in (("bid", bids), ("ask", asks)):
        for index, level in enumerate(levels, start=1):
            metrics.extend(
                (
                    MetricValue(
                        f"{side}_{index}_price", level.price, policy.price_unit
                    ),
                    MetricValue(
                        f"{side}_{index}_quantity",
                        level.quantity,
                        policy.quantity_unit,
                    ),
                )
            )
    return MarketData(
        market_data_id=source.market_data_id,
        instrument_id=policy.instrument_id,
        venue_id=policy.venue_id,
        observation_type="ORDER_BOOK",
        event_time=source.event_time,
        provider_time=source.event_time,
        ingestion_time=source.ingestion_time,
        availability_time=source.availability_time,
        source_record_id=source.source_record_id,
        metrics=tuple(metrics),
    )


def _invalid(
    state: BookState,
    reason: BookFailure,
    *,
    rejected_sequence_end: int | None = None,
    rejected_event_time: datetime | None = None,
) -> BookTransition:
    return BookTransition(
        state=BookState(
            status=BookStatus.INVALID,
            policy=state.policy,
            instrument_id=state.instrument_id,
            venue_id=state.venue_id,
            provider_identity=state.provider_identity,
            bids=state.bids,
            asks=state.asks,
            sequence=state.sequence,
            event_time=state.event_time,
            source_lineage=state.source_lineage,
            market_data_ids=state.market_data_ids,
            fingerprints=state.fingerprints,
            failure=reason,
            resync_sequence_floor=(
                rejected_sequence_end
                if rejected_sequence_end is not None
                else state.resync_sequence_floor
            ),
            resync_event_time_floor=(
                rejected_event_time
                if rejected_event_time is not None
                else state.resync_event_time_floor
            ),
        ),
        source_record=None,
        market_data=None,
        quality=BookQuality(
            ChecksumStatus.FAILED
            if reason is BookFailure.CHECKSUM
            else ChecksumStatus.NOT_AVAILABLE,
            None,
        ),
    )


def normalize_book_snapshot(
    snapshot: BookSnapshot,
    policy: BookPolicy,
    *,
    as_of: datetime,
    checksum_verifier: ChecksumVerifier | None = None,
    resync_of: BookState | None = None,
) -> BookTransition:
    """Create a fresh state; a prior invalid state is reset only explicitly."""
    if not isinstance(policy, BookPolicy) or type(snapshot) is not BookSnapshot:
        raise OrderBookError("Invalid snapshot or policy.")
    if resync_of is not None and (
        type(resync_of) is not BookState
        or resync_of.status is not BookStatus.INVALID
        or resync_of.policy != policy
        or resync_of.instrument_id != policy.instrument_id
        or resync_of.venue_id != policy.venue_id
    ):
        raise OrderBookError("Resync requires a matching invalid state.")
    now = _utc("as_of", as_of)
    source, digest = _source(snapshot.source, policy, now)
    identity = _identity(snapshot.source)
    if resync_of is not None and identity != resync_of.provider_identity:
        raise OrderBookError("Resync provider identity mismatch.")
    sequence = (
        None if snapshot.sequence is None else _sequence("sequence", snapshot.sequence)
    )
    if resync_of is not None and (
        sequence is None
        or resync_of.sequence is None
        or sequence <= resync_of.sequence
        or source.provider_event_time <= resync_of.event_time
        or (
            resync_of.resync_sequence_floor is not None
            and sequence < resync_of.resync_sequence_floor
        )
        or (
            resync_of.resync_event_time_floor is not None
            and source.provider_event_time < resync_of.resync_event_time_floor
        )
    ):
        raise OrderBookError("Resync snapshot must advance sequence and event time.")
    bids = _levels(snapshot.bids, policy, bid=True)
    asks = _levels(snapshot.asks, policy, bid=False)
    spread = _spread(bids, asks, policy)
    checksum = _checksum(bids, asks, snapshot.checksum, checksum_verifier)
    state = BookState(
        status=BookStatus.VALID,
        policy=policy,
        instrument_id=policy.instrument_id,
        venue_id=policy.venue_id,
        provider_identity=identity,
        bids=bids,
        asks=asks,
        sequence=sequence,
        event_time=source.provider_event_time,
        source_lineage=(source.source_record_id,),
        market_data_ids=(snapshot.source.market_data_id,),
        fingerprints=(
            BookFingerprint(
                snapshot.source.event_id,
                digest,
                source.provider_event_time,
                sequence,
                sequence,
                snapshot.checksum,
                (),
            ),
        ),
    )
    return BookTransition(
        state=state,
        source_record=source,
        market_data=_observation(snapshot.source, bids, asks, policy),
        quality=BookQuality(checksum, spread),
    )


def apply_book_delta(
    state: BookState,
    delta: BookDelta,
    policy: BookPolicy,
    *,
    as_of: datetime,
    sequence_verifier: SequenceVerifier | None,
    checksum_verifier: ChecksumVerifier | None = None,
) -> BookTransition:
    """Apply one delta or invalidate the state; never emit partial book output."""
    if type(state) is not BookState or not isinstance(policy, BookPolicy):
        raise OrderBookError("Invalid state or policy.")
    if state.status is BookStatus.INVALID:
        return _invalid(state, state.failure or BookFailure.INVALID_INPUT)
    if type(delta) is not BookDelta:
        return _invalid(state, BookFailure.INVALID_INPUT)
    if type(delta.source) is not BookSource:
        return _invalid(state, BookFailure.INVALID_INPUT)
    if (
        state.policy != policy
        or state.instrument_id != policy.instrument_id
        or state.venue_id != policy.venue_id
        or _identity(delta.source) != state.provider_identity
    ):
        return _invalid(state, BookFailure.IDENTITY)
    try:
        now = _utc("as_of", as_of)
        source, digest = _source(delta.source, policy, now)
        start = _sequence("sequence_start", delta.sequence_start)
        end = _sequence("sequence_end", delta.sequence_end)
        if start > end:
            raise OrderBookError("Inverted sequence range.")
        if not isinstance(delta.changes, tuple) or not delta.changes:
            raise OrderBookError("Non-empty tuple of changes required.")
        if len(delta.changes) > 2 * policy.maximum_depth:
            raise OrderBookError("Delta exceeds depth bound.")
        seen_prices: set[tuple[BookSide, Decimal]] = set()
        for change in delta.changes:
            if type(change) is not LevelChange or not isinstance(change.side, BookSide):
                raise OrderBookError("Invalid level change.")
            price = _decimal("price", change.price, policy.price_places)
            _decimal("quantity", change.quantity, policy.quantity_places, zero=True)
            identity = (change.side, price)
            if identity in seen_prices:
                raise OrderBookError("Duplicate level change.")
            seen_prices.add(identity)
        fingerprint = BookFingerprint(
            delta.source.event_id,
            digest,
            source.provider_event_time,
            start,
            end,
            delta.checksum,
            delta.changes,
        )
        for prior in state.fingerprints:
            if prior.event_id == fingerprint.event_id:
                if prior != fingerprint:
                    return _invalid(state, BookFailure.DUPLICATE_CONFLICT)
                return BookTransition(
                    state=state,
                    source_record=None,
                    market_data=None,
                    quality=BookQuality(
                        ChecksumStatus.NOT_AVAILABLE, None, duplicate=True
                    ),
                )
        if source.source_record_id in state.source_lineage or (
            delta.source.market_data_id in state.market_data_ids
        ):
            return _invalid(state, BookFailure.DUPLICATE_CONFLICT)
        if source.provider_event_time < state.event_time:
            return _invalid(state, BookFailure.INVALID_INPUT)
        if state.sequence is None or sequence_verifier is None:
            return _invalid(
                state,
                BookFailure.SEQUENCE,
                rejected_sequence_end=end,
                rejected_event_time=source.provider_event_time,
            )
        try:
            continuous = sequence_verifier(state.sequence, start, end)
        except Exception:
            return _invalid(
                state,
                BookFailure.SEQUENCE,
                rejected_sequence_end=end,
                rejected_event_time=source.provider_event_time,
            )
        if continuous is not True or end <= state.sequence:
            return _invalid(
                state,
                BookFailure.SEQUENCE,
                rejected_sequence_end=end,
                rejected_event_time=source.provider_event_time,
            )
        if len(state.source_lineage) >= policy.maximum_lineage:
            return _invalid(state, BookFailure.LINEAGE)
        bids = {level.price: level.quantity for level in state.bids}
        asks = {level.price: level.quantity for level in state.asks}
        for change in delta.changes:
            side = bids if change.side is BookSide.BID else asks
            if change.quantity == 0:
                if change.price not in side:
                    raise OrderBookError("Delete of unknown price level.")
                del side[change.price]
            else:
                side[change.price] = change.quantity
        new_bids = _levels(
            tuple(BookLevel(price, quantity) for price, quantity in bids.items()),
            policy,
            bid=True,
        )
        new_asks = _levels(
            tuple(BookLevel(price, quantity) for price, quantity in asks.items()),
            policy,
            bid=False,
        )
        spread = _spread(new_bids, new_asks, policy)
        checksum = _checksum(new_bids, new_asks, delta.checksum, checksum_verifier)
    except _BookValidationError as exc:
        return _invalid(state, exc.reason)
    except OrderBookError:
        return _invalid(state, BookFailure.INVALID_INPUT)
    next_state = BookState(
        status=BookStatus.VALID,
        policy=state.policy,
        instrument_id=state.instrument_id,
        venue_id=state.venue_id,
        provider_identity=state.provider_identity,
        bids=new_bids,
        asks=new_asks,
        sequence=end,
        event_time=source.provider_event_time,
        source_lineage=state.source_lineage + (source.source_record_id,),
        market_data_ids=state.market_data_ids + (delta.source.market_data_id,),
        fingerprints=state.fingerprints + (fingerprint,),
    )
    return BookTransition(
        state=next_state,
        source_record=source,
        market_data=_observation(delta.source, new_bids, new_asks, policy),
        quality=BookQuality(checksum, spread),
    )
