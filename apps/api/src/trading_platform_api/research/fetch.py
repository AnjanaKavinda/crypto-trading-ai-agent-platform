"""Download closed Binance Spot klines from the public market-data endpoint.

Public, unauthenticated, read-only market data. No API key is used or
accepted. Only candles closed before the fetch time are written; the provider
values are written verbatim (no repair or interpolation).
"""

from __future__ import annotations

import time
from datetime import UTC, datetime
from pathlib import Path

import httpx

from trading_platform_api.research.candles import (
    APPROVED_SPOT_SYMBOLS,
    RESEARCH_ONLY_SPOT_SYMBOLS,
    TIMEFRAME_SECONDS,
    format_candle_csv,
    parse_candle_csv,
)

DEFAULT_BASE_URL = "https://data-api.binance.vision"
SOURCE_ID = "binance-spot-rest-v3-klines"
_PAGE = 1000


def fetch_klines(
    *,
    symbol: str,
    timeframe: str,
    start: datetime,
    base_url: str = DEFAULT_BASE_URL,
    client: httpx.Client | None = None,
    now: datetime | None = None,
    pause_seconds: float = 0.2,
    research_only: bool = False,
) -> str:
    """Return a validated candle CSV document for one symbol."""
    if symbol not in APPROVED_SPOT_SYMBOLS and not (
        research_only and symbol in RESEARCH_ONLY_SPOT_SYMBOLS
    ):
        raise ValueError(f"{symbol} is not an approved Spot symbol.")
    if timeframe not in TIMEFRAME_SECONDS:
        raise ValueError(f"Unsupported timeframe {timeframe}.")
    fetched_at = (now or datetime.now(UTC)).astimezone(UTC)
    cutoff_ms = int(fetched_at.timestamp() * 1000)
    step_ms = TIMEFRAME_SECONDS[timeframe] * 1000
    cursor = int(start.astimezone(UTC).timestamp() * 1000)
    cursor += (-cursor) % step_ms
    rows: list[tuple[int, str, str, str, str, str, int]] = []
    owned = client is None
    http = client or httpx.Client(timeout=20.0)
    try:
        while cursor < cutoff_ms:
            response = http.get(
                f"{base_url.rstrip('/')}/api/v3/klines",
                params={
                    "symbol": symbol,
                    "interval": timeframe,
                    "startTime": cursor,
                    "limit": _PAGE,
                },
            )
            response.raise_for_status()
            page = response.json()
            if not isinstance(page, list):
                raise ValueError("Unexpected provider response shape.")
            for item in page:
                open_ms, close_ms = int(item[0]), int(item[6])
                if close_ms >= cutoff_ms:
                    continue
                rows.append(
                    (open_ms, item[1], item[2], item[3], item[4], item[5], close_ms)
                )
            if len(page) < _PAGE:
                break
            cursor = int(page[-1][0]) + step_ms
            time.sleep(pause_seconds)
    finally:
        if owned:
            http.close()
    document = format_candle_csv(
        source=SOURCE_ID,
        symbol=symbol,
        timeframe=timeframe,
        fetched_at=fetched_at,
        rows=rows,
    )
    parse_candle_csv(
        document, research_only=research_only
    )  # fail closed before anything is saved
    return document


def write_dataset(document: str, directory: Path, symbol: str, timeframe: str) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{symbol}_{timeframe}.csv"
    path.write_text(document, encoding="utf-8")
    return path
