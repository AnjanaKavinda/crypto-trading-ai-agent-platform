"""Owner-approved E11a public USD-M research files; no trading authority."""

from __future__ import annotations

import csv
import io
import time
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from hashlib import sha256
from typing import Any

import httpx

from trading_platform_api.research.candles import CSV_HEADER, CandleDataError
from trading_platform_api.research.fetch import fetch_klines

SYMBOLS = ("BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT")
BASE_URL = "https://fapi.binance.com"
HOUR_MS = 3_600_000
FUNDING_MS = 8 * HOUR_MS
MAX_ROWS = 200_000


def _stamp(milliseconds: int) -> str:
    return datetime.fromtimestamp(milliseconds / 1000, UTC).isoformat()


def _fail(symbol: str, at: int, reason: str) -> None:
    raise CandleDataError(f"{symbol} {_stamp(at)}: {reason}")


def _number(value: str) -> Decimal:
    try:
        number = Decimal(value)
    except InvalidOperation as exc:
        raise ValueError("invalid decimal") from exc
    if not number.is_finite():
        raise ValueError("non-finite decimal")
    return number


def validate_rows(
    rows: list[list[str]], *, symbol: str, dataset: str, start_ms: int, end_ms: int
) -> None:
    """Require the entire requested half-open grid; never repair provider data."""
    step = FUNDING_MS if dataset == "funding" else HOUR_MS
    expected = start_ms + (-start_ms) % step
    for row in rows:
        try:
            at = int(row[0])
        except (ValueError, IndexError) as exc:
            raise CandleDataError(
                f"{symbol} {_stamp(expected)}: invalid timestamp"
            ) from exc
        if at != expected or at >= end_ms:
            _fail(
                symbol,
                expected,
                "missing, duplicate, off-grid or unexpected observation",
            )
        try:
            if dataset == "funding":
                if len(row) != 2:
                    raise ValueError("invalid funding row")
                _number(row[1])
            else:
                if len(row) != 7:
                    raise ValueError("invalid candle row")
                if int(row[6]) != at + HOUR_MS - 1:
                    raise ValueError("close_time mismatch")
                if at + HOUR_MS > end_ms:
                    raise ValueError("unclosed candle")
                opening, high, low, close, volume = map(_number, row[1:6])
                if (
                    low > min(opening, close)
                    or high < max(opening, close)
                    or low > high
                ):
                    raise ValueError("inconsistent OHLC")
                if volume < 0 or (
                    dataset != "premium" and min(opening, high, low, close) <= 0
                ):
                    raise ValueError("invalid price or volume")
        except (ValueError, InvalidOperation) as exc:
            _fail(symbol, at, str(exc))
        expected += step
    if expected < end_ms or not rows:
        # Funding only needs settlements strictly before the closed-hour boundary.
        _fail(symbol, expected, "missing observation")


def format_dataset(
    rows: list[list[str]], *, symbol: str, dataset: str, fetched_at: datetime
) -> str:
    header = (
        "funding_time_ms,funding_rate" if dataset == "funding" else ",".join(CSV_HEADER)
    )
    interval = "8h" if dataset == "funding" else "1h"
    source = {
        "funding": "fundingRate",
        "premium": "premiumIndexKlines",
        "klines": "klines",
    }[dataset]
    document = (
        f"# source=binance-usdm-rest-{source} venue=BINANCE-USDM symbol={symbol} "
        f"dataset={dataset} interval={interval} fetched_at={fetched_at.isoformat()}\n"
        + header
        + "\n"
        + "".join(",".join(row) + "\n" for row in rows)
    )
    digest = sha256(document.encode("utf-8")).hexdigest()
    return (
        document.split("\n", 1)[0]
        + f" content_sha256={digest}\n"
        + document.split("\n", 1)[1]
    )


def fetch_futures_data(
    *,
    symbol: str,
    start: datetime,
    now: datetime | None = None,
    client: httpx.Client | None = None,
    pause_seconds: float = 0.7,
) -> dict[str, str]:
    """Validate Spot + all three Futures datasets before the caller writes any file.

    Only full hours before fetch time are requested. The current candle is
    deliberately outside the request, rather than silently dropping bad rows.
    Premium-index OHLC can legitimately be negative or zero (it is a rate).
    """
    if start.tzinfo is None or (now is not None and now.tzinfo is None):
        raise CandleDataError("Research fetch requires timezone-aware timestamps.")
    fetched = (now or datetime.now(UTC)).astimezone(UTC)
    end_ms = int(fetched.timestamp()) // 3600 * HOUR_MS
    start_ms = int(start.timestamp() * 1000)
    if symbol not in SYMBOLS or start_ms % HOUR_MS or start_ms >= end_ms:
        _fail(symbol, start_ms, "unsupported symbol or invalid 1h research window")
    owned = client is None
    http = client or httpx.Client(timeout=20.0)
    documents: dict[str, str] = {}
    try:
        for dataset, endpoint in (
            ("klines", "klines"),
            ("premium", "premiumIndexKlines"),
            ("funding", "fundingRate"),
        ):
            cursor = start_ms
            rows: list[list[str]] = []
            step = FUNDING_MS if dataset == "funding" else HOUR_MS
            while cursor < end_ms:
                params: dict[str, Any] = {
                    "symbol": symbol,
                    "startTime": cursor,
                    "endTime": end_ms - 1,
                    "limit": 1000,
                }
                if dataset != "funding":
                    params["interval"] = "1h"
                response = http.get(f"{BASE_URL}/fapi/v1/{endpoint}", params=params)
                response.raise_for_status()
                page = response.json()
                if not isinstance(page, list) or len(page) > 1000:
                    _fail(symbol, cursor, "unexpected provider response")
                if not page:
                    break
                for item in page:
                    try:
                        if dataset == "funding":
                            if item["symbol"] != symbol:
                                raise ValueError("funding symbol mismatch")
                            row = [str(item["fundingTime"]), str(item["fundingRate"])]
                        else:
                            row = [str(item[i]) for i in (0, 1, 2, 3, 4, 5, 6)]
                        at = int(row[0])
                    except (TypeError, KeyError, IndexError, ValueError) as exc:
                        raise CandleDataError(
                            f"{symbol} {_stamp(cursor)}: malformed provider row"
                        ) from exc
                    if at < cursor or at >= end_ms:
                        _fail(symbol, at, "out-of-window or unclosed observation")
                    rows.append(row)
                    if len(rows) > MAX_ROWS:
                        _fail(symbol, at, "research dataset exceeds supported size")
                next_cursor = int(rows[-1][0]) + (1 if dataset == "funding" else step)
                if next_cursor <= cursor:
                    _fail(symbol, cursor, "pagination did not advance")
                cursor = next_cursor
                if cursor < end_ms:
                    time.sleep(pause_seconds)
            validate_rows(
                rows, symbol=symbol, dataset=dataset, start_ms=start_ms, end_ms=end_ms
            )
            documents[dataset] = format_dataset(
                rows, symbol=symbol, dataset=dataset, fetched_at=fetched
            )
        spot = fetch_klines(
            symbol=symbol,
            timeframe="1h",
            start=start,
            now=datetime.fromtimestamp(end_ms / 1000, UTC),
            client=http,
            pause_seconds=pause_seconds,
        )
        spot_rows = list(csv.reader(io.StringIO("\n".join(spot.splitlines()[2:]))))
        validate_rows(
            spot_rows, symbol=symbol, dataset="spot", start_ms=start_ms, end_ms=end_ms
        )
        # Each side has been checked against exactly the same full UTC hour grid.
        documents["spot"] = spot
    finally:
        if owned:
            http.close()
    return documents
