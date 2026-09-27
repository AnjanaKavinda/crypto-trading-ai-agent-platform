"""Synthetic Binance-shaped responses; these are not actual market observations."""

from __future__ import annotations

import asyncio
import io
import json
import zipfile
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from uuid import uuid4

import httpx
import pytest
from trading_platform_api.market_data.binance_spot import (
    BinanceSpotArchive,
    BinanceSpotProvider,
    BinanceSpotSettings,
)
from trading_platform_api.market_data.binance_spot.smoke import (
    _request as smoke_request,
)
from trading_platform_api.market_data.providers import (
    MarketDataProvider,
    MarketDataRequest,
    ProviderBatchStatus,
    ProviderDataKind,
    ProviderError,
    ProviderFailureCode,
)

NOW = datetime(2026, 9, 27, 12, 5, tzinfo=UTC)
OPEN = datetime(2026, 9, 27, 12, 0, tzinfo=UTC)
MS = lambda moment: int(moment.timestamp() * 1000)  # noqa: E731


def test_owner_smoke_bounds_closed_candles_and_recent_trades() -> None:
    candles = smoke_request("BTC-USDT-SPOT", ProviderDataKind.OHLCV)
    trades = smoke_request("BTC-USDT-SPOT", ProviderDataKind.TRADE)
    assert candles.range_start is not None and candles.range_end is not None
    assert candles.range_end - candles.range_start == timedelta(minutes=2)
    assert candles.range_end <= candles.requested_at - timedelta(minutes=1)
    assert candles.maximum_records == trades.maximum_records == 2
    assert trades.range_start is None and trades.range_end is None


def settings(**changes: object) -> BinanceSpotSettings:
    values = dict(
        enabled=True,
        terms_review_reference="personal-terms-review-1",
        region_review_reference="regional-check-1",
        integration_evidence_reference="offline-fixtures-1",
    )
    values.update(changes)
    return BinanceSpotSettings(**values)  # type: ignore[arg-type]


def request(
    kind: ProviderDataKind = ProviderDataKind.OHLCV, **changes: object
) -> MarketDataRequest:
    values = dict(
        request_id=uuid4(),
        correlation_id="fixture-1",
        data_kind=kind,
        instrument_id="BTC-USDT-SPOT",
        venue_id="BINANCE-SPOT",
        requested_at=NOW,
        as_of=NOW,
        maximum_records=2,
    )
    values.update(changes)
    return MarketDataRequest(**values)  # type: ignore[arg-type]


def candle(opened: datetime = OPEN) -> list[object]:
    return [
        MS(opened),
        "10.00",
        "11.00",
        "9.00",
        "10.50",
        "2.000",
        MS(opened + timedelta(minutes=1)) - 1,
        "21.00",
        2,
        "1.000",
        "10.50",
        "0",
    ]


def trade(
    id_: int = 1, when: datetime = NOW - timedelta(seconds=5)
) -> dict[str, object]:
    return dict(
        id=id_,
        price="10.50",
        qty="2.000",
        quoteQty="21.00",
        time=MS(when),
        isBuyerMaker=True,
        isBestMatch=True,
    )


def metadata(symbol: str = "BTCUSDT") -> dict[str, object]:
    return {
        "symbols": [
            dict(
                symbol=symbol,
                baseAsset="BTC",
                quoteAsset="USDT",
                status="TRADING",
                isSpotTradingAllowed=True,
            )
        ]
    }


def client_for(handler):  # type: ignore[no-untyped-def]
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def run(coroutine):  # type: ignore[no-untyped-def]
    return asyncio.run(coroutine)


def test_disabled_and_scope_rejected_before_network() -> None:
    def forbidden(_: httpx.Request) -> httpx.Response:
        raise AssertionError("network call before opt-in")

    async def check() -> None:
        async with client_for(forbidden) as client:
            provider = BinanceSpotProvider(
                BinanceSpotSettings(), client=client, clock=lambda: NOW
            )
            assert isinstance(provider, MarketDataProvider)
            with pytest.raises(ProviderError) as denied:
                await provider.fetch(request())
            assert denied.value.code is ProviderFailureCode.LICENSING_RESTRICTED
            provider = BinanceSpotProvider(settings(), client=client, clock=lambda: NOW)
            for changes in (
                dict(instrument_id="SOL-USDT-SPOT"),
                dict(venue_id="BINANCE-FUTURES"),
                dict(data_kind=ProviderDataKind.ORDER_BOOK),
            ):
                with pytest.raises(ProviderError) as unsupported:
                    await provider.fetch(request(**changes))
                assert (
                    unsupported.value.code is ProviderFailureCode.UNSUPPORTED_CAPABILITY
                )

    run(check())
    with pytest.raises(ValueError, match="public"):
        BinanceSpotSettings(rest_origin="https://api.binance.com")


def test_paginated_candles_preserve_provenance_and_explicit_gap() -> None:
    paths: list[str] = []
    raw = json.dumps([candle(OPEN)]).encode()
    raw2 = json.dumps([candle(OPEN + timedelta(minutes=2))]).encode()

    def handler(req: httpx.Request) -> httpx.Response:
        paths.append(req.url.path)
        if req.url.path.endswith("exchangeInfo"):
            return httpx.Response(200, json=metadata())
        assert req.url.path == "/api/v3/klines"
        assert req.url.params["symbol"] == "BTCUSDT"
        assert req.url.params["interval"] == "1m"
        return httpx.Response(
            200, content=raw if len(paths) == 2 else raw2 if len(paths) == 3 else b"[]"
        )

    async def check() -> None:
        async with client_for(handler) as client:
            provider = BinanceSpotProvider(
                settings(page_size=1), client=client, clock=lambda: NOW
            )
            result = await provider.fetch(
                request(
                    maximum_records=3,
                    range_start=OPEN,
                    range_end=OPEN + timedelta(minutes=3),
                )
            )
            assert result.status is ProviderBatchStatus.PARTIAL
            assert len(result.market_data) == 2
            assert "Missing candle" in result.warnings[0]
            assert result.source_records[0].content_sha256 == sha256(raw).hexdigest()
            assert result.source_records[1].content_sha256 == sha256(raw2).hexdigest()
            assert (
                result.source_records[0].licensing_reference
                == "personal-terms-review-1"
            )
            assert result.snapshots[0].market_data_ids == tuple(
                item.market_data_id for item in result.market_data
            )

    run(check())
    assert paths == ["/api/v3/exchangeInfo", "/api/v3/klines", "/api/v3/klines"]


def test_recent_raw_trade_maps_aggressor_without_invented_sequence() -> None:
    raw = json.dumps([trade()]).encode()

    def handler(req: httpx.Request) -> httpx.Response:
        return (
            httpx.Response(200, json=metadata())
            if req.url.path.endswith("exchangeInfo")
            else httpx.Response(200, content=raw)
        )

    async def check() -> None:
        async with client_for(handler) as client:
            result = await BinanceSpotProvider(
                settings(), client=client, clock=lambda: NOW
            ).fetch(request(ProviderDataKind.TRADE))
            assert result.status is ProviderBatchStatus.COMPLETE
            assert result.source_records[0].content_sha256 == sha256(raw).hexdigest()
            assert (
                dict(
                    (item.metric_name, item.value)
                    for item in result.market_data[0].metrics
                )["aggressor_sign"]
                == -1
            )

    run(check())


@pytest.mark.parametrize(
    "status,code",
    [
        (429, ProviderFailureCode.RATE_LIMITED),
        (403, ProviderFailureCode.AUTHORIZATION_FAILED),
        (503, ProviderFailureCode.UNAVAILABLE),
    ],
)
def test_http_failure_mapping_is_sanitized(
    status: int, code: ProviderFailureCode
) -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(status, text="sensitive body must not surface")

    async def check() -> None:
        async with client_for(handler) as client:
            with pytest.raises(ProviderError) as result:
                await BinanceSpotProvider(
                    settings(), client=client, clock=lambda: NOW
                ).fetch(request())
            assert result.value.code is code
            assert "sensitive" not in str(result.value)

    run(check())


def test_schema_drift_and_unverified_symbol_fail_closed() -> None:
    async def check(body: object) -> ProviderFailureCode:
        def handler(req: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200, json=body if req.url.path.endswith("exchangeInfo") else [candle()]
            )

        async with client_for(handler) as client:
            with pytest.raises(ProviderError) as result:
                await BinanceSpotProvider(
                    settings(), client=client, clock=lambda: NOW
                ).fetch(request())
            return result.value.code

    assert run(check({"symbols": []})) is ProviderFailureCode.INVALID_RESPONSE
    bad = metadata()
    bad["symbols"][0]["status"] = "BREAK"  # type: ignore[index]
    assert run(check(bad)) is ProviderFailureCode.UNSUPPORTED_CAPABILITY


def test_stream_lifecycle_and_disconnect_invalidates_session() -> None:
    event_time = NOW - timedelta(seconds=5)
    event = dict(
        e="trade",
        E=MS(event_time),
        s="BTCUSDT",
        t=1,
        p="10.50",
        q="2.000",
        T=MS(event_time),
        m=False,
        M=True,
    )
    exits = []

    class Socket:
        async def __aenter__(self):  # type: ignore[no-untyped-def]
            return self

        async def __aexit__(self, *_):  # type: ignore[no-untyped-def]
            exits.append(True)

        async def recv(self):  # type: ignore[no-untyped-def]
            return json.dumps(event)

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=metadata())

    async def check() -> None:
        async with client_for(handler) as client:
            provider = BinanceSpotProvider(settings(), client=client, clock=lambda: NOW)
            batches = [
                item
                async for item in provider.stream(
                    request(ProviderDataKind.TRADE),
                    maximum_messages=1,
                    connect=lambda *_, **__: Socket(),
                )
            ]
            assert len(batches) == 1
            assert batches[0].market_data[0].observation_type == "TRADE"

    run(check())
    assert exits == [True]


def test_stale_recent_trade_and_invalid_schema_fail_closed() -> None:
    async def check(raw: bytes) -> ProviderFailureCode:
        def handler(req: httpx.Request) -> httpx.Response:
            return (
                httpx.Response(200, json=metadata())
                if req.url.path.endswith("exchangeInfo")
                else httpx.Response(200, content=raw)
            )

        async with client_for(handler) as client:
            with pytest.raises(ProviderError) as result:
                await BinanceSpotProvider(
                    settings(), client=client, clock=lambda: NOW
                ).fetch(request(ProviderDataKind.TRADE))
            return result.value.code

    assert (
        run(check(json.dumps([trade(when=OPEN)]).encode()))
        is ProviderFailureCode.STALE_RESPONSE
    )
    malformed = trade()
    malformed["unexpected"] = 1
    assert (
        run(check(json.dumps([malformed]).encode()))
        is ProviderFailureCode.INVALID_RESPONSE
    )


def test_stream_retry_is_bounded_before_first_message() -> None:
    attempts = []
    pauses = []

    def fail(*_, **__):  # type: ignore[no-untyped-def]
        attempts.append(True)
        raise OSError("connection failed")

    async def pause(seconds: float) -> None:
        pauses.append(seconds)

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=metadata())

    async def check() -> None:
        async with client_for(handler) as client:
            provider = BinanceSpotProvider(settings(), client=client, clock=lambda: NOW)
            with pytest.raises(ProviderError) as result:
                async for _ in provider.stream(
                    request(), maximum_messages=1, connect=fail, pause=pause
                ):
                    pass
            assert result.value.code is ProviderFailureCode.UNAVAILABLE

    run(check())
    assert len(attempts) == 3
    assert pauses == [0.25, 0.55]


def test_duplicate_stream_trade_invalidates_session() -> None:
    event_time = NOW - timedelta(seconds=5)
    message = json.dumps(
        dict(
            e="trade",
            E=MS(event_time),
            s="BTCUSDT",
            t=1,
            p="10.50",
            q="2.000",
            T=MS(event_time),
            m=True,
            M=True,
        )
    )
    exits = []

    class Socket:
        async def __aenter__(self):  # type: ignore[no-untyped-def]
            return self

        async def __aexit__(self, *_):  # type: ignore[no-untyped-def]
            exits.append(True)

        async def recv(self):  # type: ignore[no-untyped-def]
            return message

    async def check() -> None:
        async with client_for(lambda _: httpx.Response(200, json=metadata())) as client:
            provider = BinanceSpotProvider(settings(), client=client, clock=lambda: NOW)
            with pytest.raises(ProviderError) as result:
                async for _ in provider.stream(
                    request(ProviderDataKind.TRADE),
                    maximum_messages=2,
                    connect=lambda *_, **__: Socket(),
                ):
                    pass
            assert result.value.code is ProviderFailureCode.INVALID_RESPONSE

    run(check())
    assert exits == [True]


@pytest.mark.parametrize("kind", [ProviderDataKind.OHLCV, ProviderDataKind.TRADE])
def test_checked_archive_microsecond_schema_and_tamper_rejection(
    kind: ProviderDataKind,
) -> None:
    day = (NOW - timedelta(days=1)).date()
    prefix = "BTCUSDT-1m" if kind is ProviderDataKind.OHLCV else "BTCUSDT-trades"
    filename = f"{prefix}-{day}.zip"
    opened = datetime(2026, 9, 26, tzinfo=UTC)
    us = lambda time: int(time.timestamp() * 1_000_000)  # noqa: E731
    row = (
        f"{us(opened)},10.00,11.00,9.00,10.50,2.000,{us(opened + timedelta(minutes=1)) - 1},21.00,2,1.000,10.50,0\n"
        if kind is ProviderDataKind.OHLCV
        else f"1,10.50,2.000,21.00,{us(opened)},True,True\n"
    ).encode()
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(filename[:-4] + ".csv", row)
    content = buffer.getvalue()

    async def check(tamper: bool) -> list[object]:
        def handler(req: httpx.Request) -> httpx.Response:
            if req.url.path.endswith("exchangeInfo"):
                return httpx.Response(200, json=metadata())
            if req.url.path.endswith(".CHECKSUM"):
                digest = "0" * 64 if tamper else sha256(content).hexdigest()
                return httpx.Response(200, content=f"{digest}  {filename}\n".encode())
            return httpx.Response(200, content=content)

        async with client_for(handler) as client:
            provider = BinanceSpotProvider(settings(), client=client, clock=lambda: NOW)
            return [
                batch
                async for batch in BinanceSpotArchive(provider).day(
                    instrument_id="BTC-USDT-SPOT", kind=kind, day=day, client=client
                )
            ]

    batches = run(check(False))
    assert len(batches) == 1
    assert batches[0].source_records[0].content_sha256 == sha256(row).hexdigest()
    assert batches[0].market_data[0].observation_type == kind.value
    assert (
        batches[0].snapshots[0].dataset_version.version == sha256(content).hexdigest()
    )
    assert batches[0].datasets[0].lineage_sha256
    with pytest.raises(ProviderError) as result:
        run(check(True))
    assert result.value.code is ProviderFailureCode.INVALID_RESPONSE
