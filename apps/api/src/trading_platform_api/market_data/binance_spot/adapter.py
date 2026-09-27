"""Bounded public REST collection behind the provider-neutral market-data contract."""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any
from uuid import uuid4

import httpx
from websockets.asyncio.client import connect as websocket_connect
from websockets.exceptions import WebSocketException

from trading_platform_api.market_data.contracts import MarketSnapshot
from trading_platform_api.market_data.ohlcv import (
    CandleNormalizationError,
    CandlePolicy,
    RawCandle,
    normalize_ohlcv,
)
from trading_platform_api.market_data.providers import (
    AuthenticationRequirement,
    CapabilitySupport,
    MarketDataRequest,
    ProviderAvailability,
    ProviderBatch,
    ProviderBatchStatus,
    ProviderCapability,
    ProviderDataKind,
    ProviderDescriptor,
    ProviderError,
    ProviderFailureCode,
    RateLimitKnowledge,
    RateLimitPolicy,
)
from trading_platform_api.market_data.trades import (
    RawTradeTick,
    ReportedSide,
    SideSemantics,
    TradeTickNormalizationError,
    TradeTickPolicy,
    normalize_trade_ticks,
)
from trading_platform_api.structured_logging import (
    CorrelationContext,
    build_structured_log_entry,
)

_SYMBOLS = {"BTC-USDT-SPOT": ("BTCUSDT", "BTC"), "ETH-USDT-SPOT": ("ETHUSDT", "ETH")}
_REST_ORIGIN = "https://data-api.binance.vision"
_STREAM_ORIGIN = "wss://stream.binance.com:9443"
_VENUE = "BINANCE-SPOT"
_PROVIDER = "binance-spot-public"
_VERSION = "spot-api-2026-09"
_SCHEMA = "spot-public-v1"
_ADAPTER = "binance-spot-adapter-v1"
_INTERVALS = {"1m": 60, "5m": 300, "15m": 900, "1h": 3600, "4h": 14400, "1d": 86400}
_MAX_BODY = 1_048_576
_LOG = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class BinanceSpotSettings:
    """A deliberate local opt-in; evidence references contain no credentials."""

    enabled: bool = False
    terms_review_reference: str = ""
    region_review_reference: str = ""
    integration_evidence_reference: str = ""
    timeframe: str = "1m"
    rest_origin: str = _REST_ORIGIN
    stream_origin: str = _STREAM_ORIGIN
    maximum_pages: int = 10
    page_size: int = 1000
    timeout_seconds: float = 10.0
    idle_timeout_seconds: float = 15.0

    def __post_init__(self) -> None:
        if self.rest_origin != _REST_ORIGIN or self.stream_origin != _STREAM_ORIGIN:
            raise ValueError("Only approved public Binance Spot endpoints are supported.")
        if self.timeframe not in _INTERVALS:
            raise ValueError("Unsupported UTC candle interval.")
        if type(self.maximum_pages) is not int or not 1 <= self.maximum_pages <= 10:
            raise ValueError("maximum_pages must be in [1, 10].")
        if type(self.page_size) is not int or not 1 <= self.page_size <= 1000:
            raise ValueError("page_size must be in [1, 1000].")
        if not 0 < self.timeout_seconds <= 30 or not 0 < self.idle_timeout_seconds <= 60:
            raise ValueError("Timeout settings are out of bounds.")
        for value in (
            self.terms_review_reference,
            self.region_review_reference,
            self.integration_evidence_reference,
        ):
            if type(value) is not str or (value and re.fullmatch(r"[A-Za-z0-9._/-]{1,128}", value) is None):
                raise ValueError("Evidence references must be bounded plain text.")
        if type(self.enabled) is not bool:
            raise ValueError("enabled must be a boolean.")

    def require_enabled(self) -> None:
        if not self.enabled or not all((
            self.terms_review_reference,
            self.region_review_reference,
            self.integration_evidence_reference,
        )):
            raise ProviderError(
                ProviderFailureCode.LICENSING_RESTRICTED,
                "Public collection requires explicit opt-in and recorded use evidence.",
                retryable=False,
            )

    @property
    def timeframe_seconds(self) -> int:
        return _INTERVALS[self.timeframe]


def _invalid() -> ProviderError:
    return ProviderError(
        ProviderFailureCode.INVALID_RESPONSE,
        "Invalid Binance Spot public market-data response.",
        retryable=False,
    )


def _millis(value: object) -> datetime:
    if type(value) is not int or value < 0:
        raise _invalid()
    try:
        return datetime(1970, 1, 1, tzinfo=UTC) + timedelta(milliseconds=value)
    except OverflowError as exc:
        raise _invalid() from exc


def _decimal(value: object) -> Decimal:
    if type(value) is not str or not value or len(value) > 64:
        raise _invalid()
    try:
        number = Decimal(value)
    except InvalidOperation as exc:
        raise _invalid() from exc
    if not number.is_finite() or number < 0:
        raise _invalid()
    return number


def _integer(value: object) -> int:
    if type(value) is not int or value < 0:
        raise _invalid()
    return value


def _payload(raw: bytes) -> object:
    if not raw or len(raw) > _MAX_BODY:
        raise _invalid()
    try:
        return json.loads(raw)
    except (ValueError, UnicodeError) as exc:
        raise _invalid() from exc


class BinanceSpotProvider:
    """Single venue, public data only. No startup or import-time network I/O."""

    def __init__(
        self,
        settings: BinanceSpotSettings,
        *,
        client: httpx.AsyncClient | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.settings = settings
        self._client = client
        self._clock = clock or (lambda: datetime.now(UTC))
        self._counters: Counter[str] = Counter()

    @property
    def diagnostic_counts(self) -> dict[str, int]:
        """Local diagnostic counts; these confer no trading readiness."""
        return dict(self._counters)

    def _observe(self, event: str, request: MarketDataRequest, *, status: str, started: float, error_code: str | None = None) -> None:
        self._counters[event] += 1
        _LOG.info(build_structured_log_entry(
            level="INFO", service="market-data", component="binance-spot",
            event=event, context=CorrelationContext(request.correlation_id, str(request.request_id)),
            event_id=str(request.request_id), status=status,
            duration_ms=round((time.monotonic() - started) * 1000, 2),
            error_code=error_code, details={"provider_id": _PROVIDER, "data_kind": request.data_kind.value},
        ))

    @property
    def descriptor(self) -> ProviderDescriptor:
        capability = lambda kind: ProviderCapability(  # noqa: E731
            data_kind=kind,
            support=CapabilitySupport.SUPPORTED,
            historical_support=CapabilitySupport.SUPPORTED,
            realtime_support=CapabilitySupport.SUPPORTED,
            rate_limit=RateLimitPolicy(RateLimitKnowledge.UNKNOWN),
            market_types=("spot",),
            asset_ids=("BTC", "ETH"),
            instrument_ids=tuple(_SYMBOLS),
            freshness_target_seconds=30,
        )
        return ProviderDescriptor(
            provider_id=_PROVIDER,
            provider_version=_VERSION,
            provider_type="exchange-market-data",
            availability=(ProviderAvailability.AVAILABLE if self.settings.enabled else ProviderAvailability.UNAVAILABLE),
            authentication=AuthenticationRequirement.NONE,
            raw_schema_version=_SCHEMA,
            adapter_version=_ADAPTER,
            licensing_reference=self.settings.terms_review_reference or "pending-personal-use-review",
            capabilities=(capability(ProviderDataKind.OHLCV), capability(ProviderDataKind.TRADE)),
        )

    def _validate(self, request: MarketDataRequest) -> tuple[str, str]:
        if request.instrument_id not in _SYMBOLS or request.venue_id != _VENUE:
            raise ProviderError(ProviderFailureCode.UNSUPPORTED_CAPABILITY, "Unsupported Spot instrument or venue.", retryable=False)
        if request.data_kind not in (ProviderDataKind.OHLCV, ProviderDataKind.TRADE):
            raise ProviderError(ProviderFailureCode.UNSUPPORTED_CAPABILITY, "Unsupported Spot data kind.", retryable=False)
        if request.maximum_records > self.settings.page_size * self.settings.maximum_pages:
            raise ProviderError(ProviderFailureCode.INVALID_REQUEST, "Request exceeds bounded page budget.", retryable=False)
        if request.range_start is not None and request.range_end is not None:
            if request.range_end - request.range_start > timedelta(days=90):
                raise ProviderError(ProviderFailureCode.INVALID_REQUEST, "Historical window exceeds 90 days.", retryable=False)
            if request.data_kind is ProviderDataKind.TRADE:
                raise ProviderError(ProviderFailureCode.UNSUPPORTED_CAPABILITY, "Time-ranged raw trades require verified archive ingestion.", retryable=False)
        self.settings.require_enabled()
        return _SYMBOLS[request.instrument_id]

    async def _get(self, client: httpx.AsyncClient, path: str, params: dict[str, str | int]) -> bytes:
        try:
            async with client.stream("GET", _REST_ORIGIN + path, params=params, timeout=self.settings.timeout_seconds) as response:
                if response.status_code in (418, 429):
                    raise ProviderError(ProviderFailureCode.RATE_LIMITED, "Public market-data rate limit reached.", retryable=True)
                if response.status_code in (401, 403):
                    raise ProviderError(ProviderFailureCode.AUTHORIZATION_FAILED, "Public market-data access denied.", retryable=False)
                if response.status_code >= 500:
                    raise ProviderError(ProviderFailureCode.UNAVAILABLE, "Public market-data service unavailable.", retryable=True)
                if response.status_code != 200:
                    raise _invalid()
                body = bytearray()
                async for chunk in response.aiter_bytes():
                    body.extend(chunk)
                    if len(body) > _MAX_BODY:
                        raise _invalid()
                return bytes(body)
        except httpx.TimeoutException as exc:
            raise ProviderError(ProviderFailureCode.TIMEOUT, "Public market-data request timed out.", retryable=True) from exc
        except httpx.RequestError as exc:
            raise ProviderError(ProviderFailureCode.UNAVAILABLE, "Public market-data request failed.", retryable=True) from exc

    async def _verify_symbol(self, client: httpx.AsyncClient, symbol: str, base: str) -> None:
        payload = _payload(await self._get(client, "/api/v3/exchangeInfo", {"symbol": symbol}))
        if not isinstance(payload, dict) or not isinstance(payload.get("symbols"), list):
            raise _invalid()
        symbols = payload["symbols"]
        if len(symbols) != 1 or not isinstance(symbols[0], dict):
            raise _invalid()
        metadata = symbols[0]
        if not (
            metadata.get("symbol") == symbol
            and metadata.get("baseAsset") == base
            and metadata.get("quoteAsset") == "USDT"
            and metadata.get("status") == "TRADING"
            and metadata.get("isSpotTradingAllowed") is True
        ):
            raise ProviderError(ProviderFailureCode.UNSUPPORTED_CAPABILITY, "Spot symbol metadata does not confirm eligibility.", retryable=False)

    async def fetch(self, request: MarketDataRequest) -> ProviderBatch:
        started = time.monotonic()
        try:
            symbol, base = self._validate(request)
            if self._client is None:
                async with httpx.AsyncClient(follow_redirects=False) as client:
                    batch = await self._fetch(client, request, symbol, base)
            else:
                batch = await self._fetch(self._client, request, symbol, base)
            self._observe("fetch", request, status=batch.status.value, started=started)
            return batch
        except ProviderError as exc:
            self._observe("fetch_failure", request, status="ERROR", started=started, error_code=exc.code.value)
            raise

    async def _fetch(self, client: httpx.AsyncClient, request: MarketDataRequest, symbol: str, base: str) -> ProviderBatch:
        await self._verify_symbol(client, symbol, base)
        if request.data_kind is ProviderDataKind.OHLCV:
            sources, observations, warnings = await self._candles(client, request, symbol, base)
        else:
            sources, observations, warnings = await self._trades(client, request, symbol, base)
        retrieved = self._clock()
        if retrieved.tzinfo is None:
            raise _invalid()
        return ProviderBatch(
            request_id=request.request_id,
            provider_id=_PROVIDER,
            provider_version=_VERSION,
            data_kind=request.data_kind,
            status=(ProviderBatchStatus.EMPTY if not observations else ProviderBatchStatus.PARTIAL if warnings else ProviderBatchStatus.COMPLETE),
            retrieved_at=retrieved,
            fresh_until=retrieved + timedelta(seconds=30),
            source_records=sources,
            market_data=observations,
            snapshots=(MarketSnapshot(uuid4(), retrieved, retrieved, request.instrument_id, _VENUE, tuple(item.market_data_id for item in observations), tuple(item.source_record_id for item in sources)),) if observations else (),
            warnings=warnings,
        )

    async def _candles(self, client: httpx.AsyncClient, request: MarketDataRequest, symbol: str, base: str) -> tuple[tuple[Any, ...], tuple[Any, ...], tuple[str, ...]]:
        step = _INTERVALS[self.settings.timeframe]
        start: datetime | None
        end: datetime | None
        if request.range_start is not None and request.range_end is not None:
            start, end = request.range_start, request.range_end
            if start >= end or int(start.timestamp()) % step or int(end.timestamp()) % step:
                raise ProviderError(ProviderFailureCode.INVALID_REQUEST, "Candle range must be positive and UTC aligned.", retryable=False)
            if (end - start) // timedelta(seconds=step) > request.maximum_records:
                raise ProviderError(ProviderFailureCode.INVALID_REQUEST, "Candle range exceeds record budget.", retryable=False)
        else:
            start = end = None
        rows: list[RawCandle] = []
        cursor = start
        for _ in range(self.settings.maximum_pages):
            remaining = request.maximum_records - len(rows)
            if remaining <= 0:
                break
            limit = min(remaining, self.settings.page_size)
            params: dict[str, str | int] = {"symbol": symbol, "interval": self.settings.timeframe, "limit": limit}
            if cursor is not None:
                params["startTime"] = int(cursor.timestamp() * 1000)
                assert end is not None
                params["endTime"] = int(end.timestamp() * 1000) - 1
            raw = await self._get(client, "/api/v3/klines", params)
            payload = _payload(raw)
            if not isinstance(payload, list) or len(payload) > limit:
                raise _invalid()
            seen = len(rows)
            for row in payload:
                if not isinstance(row, list) or len(row) != 12:
                    raise _invalid()
                for field in (7, 9, 10, 11):
                    _decimal(row[field])
                opened, closed = _millis(row[0]), _millis(row[6])
                if closed != opened + timedelta(seconds=step, milliseconds=-1):
                    raise _invalid()
                if opened > request.as_of or (cursor is not None and opened < cursor) or (end is not None and opened >= end):
                    raise _invalid()
                moment = self._clock()
                rows.append(RawCandle(
                    source_record_id=uuid4(), market_data_id=uuid4(), instrument_id=request.instrument_id,
                    venue_id=_VENUE, timeframe=self.settings.timeframe, open_time=opened,
                    open=_decimal(row[1]), high=_decimal(row[2]), low=_decimal(row[3]), close=_decimal(row[4]),
                    volume=_decimal(row[5]), price_unit="USDT", volume_unit=base,
                    trade_count=_integer(row[8]), is_final=moment > closed,
                    raw_source_bytes=raw, provider_id=_PROVIDER, provider_version=_VERSION,
                    raw_schema_version=_SCHEMA, adapter_version=_ADAPTER,
                    licensing_reference=self.settings.terms_review_reference,
                    provider_event_time=closed if moment > closed else moment,
                    retrieval_time=moment, ingestion_time=moment, availability_time=moment,
                ))
            if not payload:
                break
            cursor = rows[-1].open_time + timedelta(seconds=step)
            if len(rows) == seen or end is None or (end is not None and cursor >= end):
                break
        try:
            normalized = normalize_ohlcv(tuple(rows), CandlePolicy(request.instrument_id, _VENUE, self.settings.timeframe, "USDT", base, 18, 18, maximum_records=request.maximum_records), range_start=start, range_end=end)
        except CandleNormalizationError as exc:
            raise _invalid() from exc
        warnings = []
        if normalized.quality.missing_open_times:
            warnings.append("Missing candle intervals; no fill was applied.")
        if normalized.quality.provisional_open_times:
            warnings.append("Provisional candle present.")
        return normalized.source_records, normalized.market_data, tuple(warnings)

    async def _trades(self, client: httpx.AsyncClient, request: MarketDataRequest, symbol: str, base: str) -> tuple[tuple[Any, ...], tuple[Any, ...], tuple[str, ...]]:
        # /api/v3/trades has no fromId cursor. Limit to one recent page; historical
        # raw trades require checked archive files rather than aggregate trades.
        if request.maximum_records > 1000:
            raise ProviderError(ProviderFailureCode.INVALID_REQUEST, "Recent raw trades are limited to one page.", retryable=False)
        raw = await self._get(client, "/api/v3/trades", {"symbol": symbol, "limit": request.maximum_records})
        payload = _payload(raw)
        if not isinstance(payload, list) or len(payload) > request.maximum_records:
            raise _invalid()
        rows: list[RawTradeTick] = []
        for item in payload:
            if not isinstance(item, dict) or set(item) != {"id", "price", "qty", "quoteQty", "time", "isBuyerMaker", "isBestMatch"}:
                raise _invalid()
            if type(item["isBuyerMaker"]) is not bool or type(item["isBestMatch"]) is not bool:
                raise _invalid()
            _decimal(item["quoteQty"])
            event_time = _millis(item["time"])
            moment = self._clock()
            if event_time > moment or event_time > request.as_of:
                raise _invalid()
            rows.append(RawTradeTick(
                source_record_id=uuid4(), market_data_id=uuid4(), provider_event_id=str(_integer(item["id"])),
                instrument_id=request.instrument_id, venue_id=_VENUE, data_kind=ProviderDataKind.TRADE,
                event_time=event_time, price=_decimal(item["price"]), quantity=_decimal(item["qty"]),
                price_unit="USDT", quantity_unit=base,
                reported_side=ReportedSide.SELL if item["isBuyerMaker"] else ReportedSide.BUY,
                side_semantics=SideSemantics.AGGRESSOR, sequence=None, sequence_scope=None,
                raw_source_bytes=raw, provider_id=_PROVIDER, provider_version=_VERSION,
                raw_schema_version=_SCHEMA, adapter_version=_ADAPTER,
                licensing_reference=self.settings.terms_review_reference,
                retrieval_time=moment, ingestion_time=moment, availability_time=moment,
            ))
        try:
            result = normalize_trade_ticks(tuple(rows), TradeTickPolicy(request.instrument_id, _VENUE, ProviderDataKind.TRADE, "USDT", base, 18, 18, maximum_records=request.maximum_records))
        except TradeTickNormalizationError as exc:
            raise _invalid() from exc
        if not rows or self._clock() - rows[-1].event_time > timedelta(seconds=30):
            raise ProviderError(ProviderFailureCode.STALE_RESPONSE, "Recent Spot trades are unavailable or stale.", retryable=False)
        return result.source_records, result.market_data, ()

    async def stream(
        self,
        request: MarketDataRequest,
        *,
        maximum_messages: int,
        connect: Callable[..., Any] = websocket_connect,
        pause: Callable[[float], Any] = asyncio.sleep,
    ):  # type: ignore[no-untyped-def]
        """Yield bounded one-message batches; disconnect after data invalidates state.

        Pre-first-message retries are bounded. Once a message is emitted, a
        disconnect requires a new explicit session and external reconciliation.
        """
        symbol, base = self._validate(request)
        if request.range_start is not None:
            raise ProviderError(ProviderFailureCode.INVALID_REQUEST, "Live stream cannot use a historical range.", retryable=False)
        if type(maximum_messages) is not int or not 1 <= maximum_messages <= 1000:
            raise ProviderError(ProviderFailureCode.INVALID_REQUEST, "Stream message budget is out of bounds.", retryable=False)
        if self._client is None:
            async with httpx.AsyncClient(follow_redirects=False) as client:
                async for batch in self._stream(client, request, symbol, base, maximum_messages, connect, pause):
                    yield batch
        else:
            async for batch in self._stream(self._client, request, symbol, base, maximum_messages, connect, pause):
                yield batch

    async def _stream(self, client: httpx.AsyncClient, request: MarketDataRequest, symbol: str, base: str, budget: int, connect: Callable[..., Any], pause: Callable[[float], Any]):  # type: ignore[no-untyped-def]
        stream_name = f"{symbol.lower()}@trade" if request.data_kind is ProviderDataKind.TRADE else f"{symbol.lower()}@kline_{self.settings.timeframe}"
        url = _STREAM_ORIGIN + "/ws/" + stream_name
        previous_trade_id: int | None = None
        previous_open: datetime | None = None
        delivered = 0
        for attempt in range(3):
            await self._verify_symbol(client, symbol, base)
            try:
                async with connect(url, open_timeout=self.settings.timeout_seconds, ping_interval=10, ping_timeout=10, max_size=_MAX_BODY, max_queue=16, close_timeout=5) as connection:
                    while delivered < budget:
                        try:
                            message = await asyncio.wait_for(connection.recv(), timeout=self.settings.idle_timeout_seconds)
                        except TimeoutError as exc:
                            raise ProviderError(ProviderFailureCode.STALE_RESPONSE, "Spot stream idle timeout; session invalidated.", retryable=False) from exc
                        if type(message) is not str:
                            raise _invalid()
                        raw = message.encode("utf-8")
                        payload = _payload(raw)
                        if not isinstance(payload, dict) or payload.get("s") != symbol:
                            raise _invalid()
                        now = self._clock()
                        if request.data_kind is ProviderDataKind.TRADE:
                            if set(payload) != {"e", "E", "s", "t", "p", "q", "T", "m", "M"} or payload["e"] != "trade" or type(payload["m"]) is not bool or type(payload["M"]) is not bool:
                                raise _invalid()
                            trade_id = _integer(payload["t"])
                            event_time = _millis(payload["T"])
                            if _millis(payload["E"]) < event_time or event_time > now:
                                raise _invalid()
                            if now - event_time > timedelta(seconds=30):
                                raise ProviderError(ProviderFailureCode.STALE_RESPONSE, "Spot trade stream is stale; session invalidated.", retryable=False)
                            if previous_trade_id is not None and trade_id <= previous_trade_id:
                                raise _invalid()
                            previous_trade_id = trade_id
                            raw_trade = RawTradeTick(
                                source_record_id=uuid4(), market_data_id=uuid4(), provider_event_id=str(trade_id),
                                instrument_id=request.instrument_id, venue_id=_VENUE, data_kind=ProviderDataKind.TRADE,
                                event_time=event_time, price=_decimal(payload["p"]), quantity=_decimal(payload["q"]),
                                price_unit="USDT", quantity_unit=base,
                                reported_side=ReportedSide.SELL if payload["m"] else ReportedSide.BUY,
                                side_semantics=SideSemantics.AGGRESSOR, sequence=None, sequence_scope=None,
                                raw_source_bytes=raw, provider_id=_PROVIDER, provider_version=_VERSION,
                                raw_schema_version=_SCHEMA, adapter_version=_ADAPTER,
                                licensing_reference=self.settings.terms_review_reference,
                                retrieval_time=now, ingestion_time=now, availability_time=now,
                            )
                            trade_result = normalize_trade_ticks((raw_trade,), TradeTickPolicy(request.instrument_id, _VENUE, ProviderDataKind.TRADE, "USDT", base, 18, 18))
                            sources, observations = trade_result.source_records, trade_result.market_data
                            warnings: tuple[str, ...] = ()
                        else:
                            if set(payload) != {"e", "E", "s", "k"} or payload["e"] != "kline" or not isinstance(payload["k"], dict):
                                raise _invalid()
                            k = payload["k"]
                            required = {"t", "T", "s", "i", "o", "c", "h", "l", "v", "n", "x", "q", "V", "Q", "B", "f", "L"}
                            if set(k) != required or k["s"] != symbol or k["i"] != self.settings.timeframe or type(k["x"]) is not bool:
                                raise _invalid()
                            opened, closed = _millis(k["t"]), _millis(k["T"])
                            if closed != opened + timedelta(seconds=_INTERVALS[self.settings.timeframe], milliseconds=-1) or _millis(payload["E"]) > now:
                                raise _invalid()
                            if now - _millis(payload["E"]) > timedelta(seconds=30):
                                raise ProviderError(ProviderFailureCode.STALE_RESPONSE, "Spot candle stream is stale; session invalidated.", retryable=False)
                            if previous_open is not None and opened < previous_open:
                                raise _invalid()
                            if previous_open is not None and opened > previous_open + timedelta(seconds=_INTERVALS[self.settings.timeframe]):
                                raise ProviderError(ProviderFailureCode.STALE_RESPONSE, "Spot candle interval gap; session invalidated.", retryable=False)
                            previous_open = opened
                            if k["x"] and now <= closed:
                                raise _invalid()
                            candle = RawCandle(
                                source_record_id=uuid4(), market_data_id=uuid4(), instrument_id=request.instrument_id,
                                venue_id=_VENUE, timeframe=self.settings.timeframe, open_time=opened,
                                open=_decimal(k["o"]), high=_decimal(k["h"]), low=_decimal(k["l"]), close=_decimal(k["c"]),
                                volume=_decimal(k["v"]), price_unit="USDT", volume_unit=base,
                                trade_count=_integer(k["n"]), is_final=k["x"], raw_source_bytes=raw,
                                provider_id=_PROVIDER, provider_version=_VERSION, raw_schema_version=_SCHEMA,
                                adapter_version=_ADAPTER, licensing_reference=self.settings.terms_review_reference,
                                provider_event_time=min(_millis(payload["E"]), now),
                                retrieval_time=now, ingestion_time=now, availability_time=now,
                            )
                            candle_result = normalize_ohlcv((candle,), CandlePolicy(request.instrument_id, _VENUE, self.settings.timeframe, "USDT", base, 18, 18))
                            sources, observations = candle_result.source_records, candle_result.market_data
                            warnings = ("Provisional candle present.",) if candle_result.quality.provisional_open_times else ()
                        delivered += 1
                        self._observe("stream_message", request, status="ACCEPTED", started=time.monotonic())
                        yield ProviderBatch(
                            request_id=request.request_id, provider_id=_PROVIDER, provider_version=_VERSION,
                            data_kind=request.data_kind, status=ProviderBatchStatus.PARTIAL if warnings else ProviderBatchStatus.COMPLETE,
                            retrieved_at=now, fresh_until=now + timedelta(seconds=30),
                            source_records=sources, market_data=observations, warnings=warnings,
                            snapshots=(MarketSnapshot(uuid4(), now, now, request.instrument_id, _VENUE, tuple(item.market_data_id for item in observations), tuple(item.source_record_id for item in sources)),),
                        )
                    return
            except (OSError, WebSocketException, TimeoutError) as exc:
                if delivered or attempt == 2:
                    raise ProviderError(ProviderFailureCode.UNAVAILABLE, "Spot stream disconnected; session invalidated.", retryable=False) from exc
                self._observe("stream_reconnect", request, status="RETRY", started=time.monotonic())
                await pause(min(0.25 * (2 ** attempt) + 0.05 * attempt, 1.0))
            except (CandleNormalizationError, TradeTickNormalizationError) as exc:
                raise _invalid() from exc
