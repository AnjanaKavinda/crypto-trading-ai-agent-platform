"""Checksum-verified daily Spot archive reader with bounded file and row batches."""

from __future__ import annotations

import csv
import io
import re
import tempfile
import zipfile
from collections.abc import AsyncIterator
from datetime import UTC, date, datetime, timedelta
from hashlib import sha256
from typing import Any
from uuid import uuid4

import httpx

from trading_platform_api.market_data.contracts import (
    DatasetVersion,
    DatasetVersionReference,
    MarketSnapshot,
)
from trading_platform_api.market_data.ohlcv import (
    CandlePolicy,
    RawCandle,
    normalize_ohlcv,
)
from trading_platform_api.market_data.providers import (
    ProviderBatch,
    ProviderBatchStatus,
    ProviderDataKind,
    ProviderError,
    ProviderFailureCode,
)
from trading_platform_api.market_data.trades import (
    RawTradeTick,
    ReportedSide,
    SideSemantics,
    TradeTickPolicy,
    normalize_trade_ticks,
)

from .adapter import (
    _ADAPTER,
    _PROVIDER,
    _SCHEMA,
    _SYMBOLS,
    _VENUE,
    _VERSION,
    BinanceSpotProvider,
    _decimal,
    _integer,
    _invalid,
)

_ARCHIVE_ORIGIN = "https://data.binance.vision"
_MAX_ZIP = 256 * 1024 * 1024
_MAX_CSV = 1024 * 1024 * 1024
_MAX_CHECKSUM = 256
_MAX_ROW = 4096
_CHECKSUM_FORMAT = re.compile(rb"^([0-9a-fA-F]{64})\s+\*?([A-Za-z0-9_.-]+)\s*$")


def _archive_time(value: str) -> datetime:
    number = _integer(int(value))
    # The approved 90-day window is after the 2025-01-01 microsecond switch.
    if number < 1_000_000_000_000_000:
        raise _invalid()
    try:
        return datetime(1970, 1, 1, tzinfo=UTC) + timedelta(microseconds=number)
    except OverflowError as exc:
        raise _invalid() from exc


class BinanceSpotArchive:
    """Explicit archive ingestion; each yielded batch carries its own raw row hash."""

    def __init__(self, provider: BinanceSpotProvider) -> None:
        self.provider = provider

    async def day(
        self,
        *,
        instrument_id: str,
        kind: ProviderDataKind,
        day: date,
        maximum_records: int = 2_000_000,
        client: httpx.AsyncClient | None = None,
    ) -> AsyncIterator[ProviderBatch]:
        self.provider.settings.require_enabled()
        if instrument_id not in _SYMBOLS or kind not in (
            ProviderDataKind.OHLCV,
            ProviderDataKind.TRADE,
        ):
            raise ProviderError(
                ProviderFailureCode.UNSUPPORTED_CAPABILITY,
                "Unsupported Spot archive selection.",
                retryable=False,
            )
        if (
            type(day) is not date
            or type(maximum_records) is not int
            or not 1 <= maximum_records <= 2_000_000
        ):
            raise ProviderError(
                ProviderFailureCode.INVALID_REQUEST,
                "Invalid archive day or record budget.",
                retryable=False,
            )
        now = self.provider._clock()
        if (
            not (now - timedelta(days=1)).date()
            >= day
            >= (now - timedelta(days=90)).date()
        ):
            raise ProviderError(
                ProviderFailureCode.INVALID_REQUEST,
                "Archive day must be available within the 90-day window.",
                retryable=False,
            )
        symbol, base = _SYMBOLS[instrument_id]
        dataset = "klines" if kind is ProviderDataKind.OHLCV else "trades"
        name = (
            f"{symbol}-{self.provider.settings.timeframe}-{day.isoformat()}.zip"
            if dataset == "klines"
            else f"{symbol}-trades-{day.isoformat()}.zip"
        )
        path = f"/data/spot/daily/{dataset}/{symbol}/"
        if dataset == "klines":
            path += self.provider.settings.timeframe + "/"
        path += name
        if client is None:
            async with httpx.AsyncClient(follow_redirects=False) as owned:
                async for batch in self._read(
                    owned,
                    instrument_id,
                    symbol,
                    base,
                    kind,
                    day,
                    path,
                    name,
                    maximum_records,
                ):
                    yield batch
        else:
            async for batch in self._read(
                client,
                instrument_id,
                symbol,
                base,
                kind,
                day,
                path,
                name,
                maximum_records,
            ):
                yield batch

    async def _download(
        self, client: httpx.AsyncClient, path: str, file: Any, limit: int
    ) -> bytes:
        digest = sha256()
        size = 0
        try:
            async with client.stream(
                "GET",
                _ARCHIVE_ORIGIN + path,
                timeout=self.provider.settings.timeout_seconds,
            ) as response:
                if response.status_code in (418, 429):
                    raise ProviderError(
                        ProviderFailureCode.RATE_LIMITED,
                        "Spot archive rate limit reached.",
                        retryable=True,
                    )
                if response.status_code != 200:
                    raise ProviderError(
                        ProviderFailureCode.UNAVAILABLE,
                        "Spot archive unavailable.",
                        retryable=True,
                    )
                async for chunk in response.aiter_bytes():
                    size += len(chunk)
                    if size > limit:
                        raise _invalid()
                    digest.update(chunk)
                    file.write(chunk)
        except httpx.TimeoutException as exc:
            raise ProviderError(
                ProviderFailureCode.TIMEOUT, "Spot archive timeout.", retryable=True
            ) from exc
        except httpx.RequestError as exc:
            raise ProviderError(
                ProviderFailureCode.UNAVAILABLE,
                "Spot archive request failed.",
                retryable=True,
            ) from exc
        if not size:
            raise _invalid()
        return digest.hexdigest().encode("ascii")

    async def _read(
        self,
        client: httpx.AsyncClient,
        instrument: str,
        symbol: str,
        base: str,
        kind: ProviderDataKind,
        day: date,
        path: str,
        name: str,
        maximum_records: int,
    ) -> AsyncIterator[ProviderBatch]:
        await self.provider._verify_symbol(client, symbol, base)
        with tempfile.SpooledTemporaryFile(max_size=8 * 1024 * 1024) as file:
            digest = await self._download(client, path, file, _MAX_ZIP)
            with io.BytesIO() as check:
                await self._download(client, path + ".CHECKSUM", check, _MAX_CHECKSUM)
                match = _CHECKSUM_FORMAT.fullmatch(check.getvalue())
                if (
                    match is None
                    or match.group(2) != name.encode("ascii")
                    or match.group(1).lower() != digest
                ):
                    raise _invalid()
            file.seek(0)
            try:
                with zipfile.ZipFile(file) as archive:
                    files = archive.infolist()
                    if (
                        len(files) != 1
                        or files[0].filename != name[:-4] + ".csv"
                        or files[0].file_size > _MAX_CSV
                        or files[0].flag_bits & 1
                    ):
                        raise _invalid()
                    # Verify every row and the total budget before emitting any data.
                    count = 0
                    previous: tuple[datetime, int] | None = None
                    gap = False
                    for raw in self._rows(archive, files[0]):
                        count += 1
                        if count > maximum_records:
                            raise _invalid()
                        key = self._parse(
                            raw, instrument, base, kind, day, validate_only=True
                        )
                        if previous is not None and key <= previous:
                            raise _invalid()
                        if (
                            kind is ProviderDataKind.OHLCV
                            and previous is not None
                            and key[0]
                            != previous[0]
                            + timedelta(
                                seconds=self.provider.settings.timeframe_seconds
                            )
                        ):
                            gap = True
                        previous = key
                    if not count:
                        raise _invalid()
                    with archive.open(files[0]) as stream:
                        for page_start in range(0, count, 1000):
                            rows = [
                                stream.readline()
                                for _ in range(min(1000, count - page_start))
                            ]
                            if any(not row or len(row) > _MAX_ROW for row in rows):
                                raise _invalid()
                            yield self._batch(
                                rows,
                                instrument,
                                base,
                                kind,
                                day,
                                gap,
                                name,
                                digest.decode("ascii"),
                                page_start,
                            )
            except (zipfile.BadZipFile, RuntimeError, UnicodeError, ValueError) as exc:
                raise _invalid() from exc

    def _rows(self, archive: zipfile.ZipFile, info: zipfile.ZipInfo):
        consumed = 0
        with archive.open(info) as stream:
            while raw := stream.readline(_MAX_ROW + 1):
                consumed += len(raw)
                if len(raw) > _MAX_ROW or consumed > _MAX_CSV:
                    raise _invalid()
                yield raw

    def _parse(
        self,
        raw: bytes,
        instrument: str,
        base: str,
        kind: ProviderDataKind,
        day: date,
        *,
        validate_only: bool = False,
    ):  # type: ignore[no-untyped-def]
        try:
            row = next(csv.reader([raw.decode("ascii")], strict=True))
            if kind is ProviderDataKind.OHLCV:
                if len(row) != 12:
                    raise _invalid()
                opened, closed = _archive_time(row[0]), _archive_time(row[6])
                if closed != opened + timedelta(
                    seconds=self.provider.settings.timeframe_seconds, microseconds=-1
                ):
                    raise _invalid()
                for field in (1, 2, 3, 4, 5):
                    _decimal(row[field])
                _integer(int(row[8]))
                moment, identity = opened, int(row[0])
            else:
                if (
                    len(row) != 7
                    or row[5] not in ("True", "False")
                    or row[6] not in ("True", "False")
                ):
                    raise _invalid()
                moment, identity = _archive_time(row[4]), _integer(int(row[0]))
                _decimal(row[1])
                _decimal(row[2])
                _decimal(row[3])
            if moment.date() != day:
                raise _invalid()
            return (moment, identity)
        except (csv.Error, UnicodeError, IndexError, ValueError) as exc:
            raise _invalid() from exc

    def _batch(
        self,
        lines: list[bytes],
        instrument: str,
        base: str,
        kind: ProviderDataKind,
        day: date,
        gap: bool,
        name: str,
        archive_sha: str,
        offset: int,
    ) -> ProviderBatch:
        now = self.provider._clock()
        candles = []
        trades = []
        for raw in lines:
            self._parse(raw, instrument, base, kind, day)
            row = next(csv.reader([raw.decode("ascii")]))
            if kind is ProviderDataKind.OHLCV:
                opened, closed = _archive_time(row[0]), _archive_time(row[6])
                candles.append(
                    RawCandle(
                        source_record_id=uuid4(),
                        market_data_id=uuid4(),
                        instrument_id=instrument,
                        venue_id=_VENUE,
                        timeframe=self.provider.settings.timeframe,
                        open_time=opened,
                        open=_decimal(row[1]),
                        high=_decimal(row[2]),
                        low=_decimal(row[3]),
                        close=_decimal(row[4]),
                        volume=_decimal(row[5]),
                        price_unit="USDT",
                        volume_unit=base,
                        trade_count=_integer(int(row[8])),
                        is_final=True,
                        raw_source_bytes=raw,
                        provider_id=_PROVIDER,
                        provider_version=_VERSION,
                        raw_schema_version=_SCHEMA + "-archive-us",
                        adapter_version=_ADAPTER,
                        licensing_reference=self.provider.settings.terms_review_reference,
                        provider_event_time=closed,
                        retrieval_time=now,
                        ingestion_time=now,
                        availability_time=now,
                    )
                )
            else:
                trades.append(
                    RawTradeTick(
                        uuid4(),
                        uuid4(),
                        row[0],
                        instrument,
                        _VENUE,
                        ProviderDataKind.TRADE,
                        _archive_time(row[4]),
                        _decimal(row[1]),
                        _decimal(row[2]),
                        "USDT",
                        base,
                        ReportedSide.SELL if row[5] == "True" else ReportedSide.BUY,
                        SideSemantics.AGGRESSOR,
                        None,
                        None,
                        raw,
                        _PROVIDER,
                        _VERSION,
                        _SCHEMA + "-archive-us",
                        _ADAPTER,
                        self.provider.settings.terms_review_reference,
                        now,
                        now,
                        now,
                    )
                )
        if kind is ProviderDataKind.OHLCV:
            candle_result = normalize_ohlcv(
                tuple(candles),
                CandlePolicy(
                    instrument,
                    _VENUE,
                    self.provider.settings.timeframe,
                    "USDT",
                    base,
                    18,
                    18,
                ),
            )
            sources, observations = (
                candle_result.source_records,
                candle_result.market_data,
            )
            warnings = (
                ("Missing candle intervals in archive day.",)
                if gap or candle_result.quality.missing_open_times
                else ()
            )
        else:
            trade_result = normalize_trade_ticks(
                tuple(trades),
                TradeTickPolicy(
                    instrument, _VENUE, ProviderDataKind.TRADE, "USDT", base, 18, 18
                ),
            )
            sources, observations = (
                trade_result.source_records,
                trade_result.market_data,
            )
            warnings = ()
        dataset_id = f"binance-spot/{name}/{offset}"
        lineage = sha256(
            (
                archive_sha
                + ":"
                + ":".join(source.content_sha256 for source in sources)
            ).encode("ascii")
        ).hexdigest()
        dataset = DatasetVersion(
            dataset_id=dataset_id,
            version=archive_sha,
            created_at=now,
            coverage_start=observations[0].event_time,
            coverage_end=observations[-1].event_time,
            point_in_time_cutoff=now,
            source_record_ids=tuple(source.source_record_id for source in sources),
            canonical_schema_version=observations[0].schema_version,
            lineage_sha256=lineage,
        )
        snapshot = MarketSnapshot(
            snapshot_id=uuid4(),
            as_of=now,
            created_at=now,
            instrument_id=instrument,
            venue_id=_VENUE,
            market_data_ids=tuple(item.market_data_id for item in observations),
            source_record_ids=dataset.source_record_ids,
            dataset_version=DatasetVersionReference(dataset_id, archive_sha),
        )
        return ProviderBatch(
            request_id=uuid4(),
            provider_id=_PROVIDER,
            provider_version=_VERSION,
            data_kind=kind,
            status=ProviderBatchStatus.PARTIAL
            if warnings
            else ProviderBatchStatus.COMPLETE,
            retrieved_at=now,
            fresh_until=now + timedelta(seconds=30),
            source_records=sources,
            market_data=observations,
            warnings=warnings,
            snapshots=(snapshot,),
            datasets=(dataset,),
        )
