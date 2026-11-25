"""Validated closed Spot candles loaded from a provenance-stamped CSV file.

File format (written by ``research fetch``)::

    # source=<id> venue=BINANCE-SPOT symbol=BTCUSDT timeframe=4h fetched_at=<UTC>
    open_time_ms,open,high,low,close,volume,close_time_ms
    1546300800000,3701.23,3810.16,3642.00,3797.14,7457.2,1546315199999

Any gap, misalignment, unclosed candle, inconsistent OHLC value or missing
provenance rejects the whole file. Nothing is filled in or repaired.
"""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from hashlib import sha256

TIMEFRAME_SECONDS = {"1h": 3600, "4h": 14400, "1d": 86400}
APPROVED_SPOT_SYMBOLS = {
    "BTCUSDT": "BTC-USDT-SPOT",
    "ETHUSDT": "ETH-USDT-SPOT",
    "BNBUSDT": "BNB-USDT-SPOT",
    "SOLUSDT": "SOL-USDT-SPOT",
    "XRPUSDT": "XRP-USDT-SPOT",
}
CSV_HEADER = ("open_time_ms", "open", "high", "low", "close", "volume", "close_time_ms")
MAX_CANDLES = 200_000


class CandleDataError(ValueError):
    """Candle data is missing, unprovenanced, discontinuous or inconsistent."""


@dataclass(frozen=True, slots=True)
class Candle:
    open_time: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal


@dataclass(frozen=True, slots=True)
class CandleSeries:
    source: str
    venue: str
    symbol: str
    timeframe: str
    fetched_at: datetime
    candles: tuple[Candle, ...]
    content_sha256: str

    @property
    def instrument_id(self) -> str:
        return APPROVED_SPOT_SYMBOLS[self.symbol]

    @property
    def first_open(self) -> datetime:
        return self.candles[0].open_time

    @property
    def last_open(self) -> datetime:
        return self.candles[-1].open_time


def _utc_from_ms(value: str, field: str, line: int) -> datetime:
    if not value.isdigit():
        raise CandleDataError(f"line {line}: {field} must be integer milliseconds.")
    return datetime.fromtimestamp(int(value) / 1000, tz=UTC)


def _decimal(value: str, field: str, line: int) -> Decimal:
    try:
        number = Decimal(value)
    except InvalidOperation as exc:
        raise CandleDataError(f"line {line}: {field} is not a decimal.") from exc
    if not number.is_finite():
        raise CandleDataError(f"line {line}: {field} must be finite.")
    return number


def _parse_metadata(line: str) -> dict[str, str]:
    if not line.startswith("# "):
        raise CandleDataError("The provenance header line is missing.")
    fields: dict[str, str] = {}
    for part in line[2:].split():
        key, separator, value = part.partition("=")
        if not separator or not value or key in fields:
            raise CandleDataError("The provenance header is malformed.")
        fields[key] = value
    for key in ("source", "venue", "symbol", "timeframe", "fetched_at"):
        if key not in fields:
            raise CandleDataError(f"The provenance header lacks {key}.")
    return fields


def parse_candle_csv(text: str) -> CandleSeries:
    """Parse and validate one provenance-stamped candle CSV document."""
    lines = text.splitlines()
    if len(lines) < 3:
        raise CandleDataError("The candle file has no candles.")
    meta = _parse_metadata(lines[0])
    symbol, timeframe = meta["symbol"], meta["timeframe"]
    if symbol not in APPROVED_SPOT_SYMBOLS:
        raise CandleDataError(f"{symbol} is not an approved Spot symbol.")
    if timeframe not in TIMEFRAME_SECONDS:
        raise CandleDataError(f"Unsupported timeframe {timeframe}.")
    if meta["venue"] != "BINANCE-SPOT":
        raise CandleDataError("Only BINANCE-SPOT candles are supported.")
    try:
        fetched_at = datetime.fromisoformat(meta["fetched_at"].replace("Z", "+00:00"))
    except ValueError as exc:
        raise CandleDataError("fetched_at is not an ISO-8601 time.") from exc
    if fetched_at.tzinfo is None:
        raise CandleDataError("fetched_at must be timezone-aware.")
    fetched_at = fetched_at.astimezone(UTC)

    reader = csv.reader(io.StringIO("\n".join(lines[1:])))
    header = tuple(next(reader))
    if header != CSV_HEADER:
        raise CandleDataError("The CSV column header is not the expected header.")
    step_ms = TIMEFRAME_SECONDS[timeframe] * 1000
    candles: list[Candle] = []
    previous_ms: int | None = None
    for offset, row in enumerate(reader):
        line = offset + 3
        if len(row) != len(CSV_HEADER):
            raise CandleDataError(f"line {line}: expected {len(CSV_HEADER)} fields.")
        open_ms = int(row[0]) if row[0].isdigit() else -1
        if open_ms < 0:
            raise CandleDataError(f"line {line}: open_time_ms must be an integer.")
        if open_ms % step_ms != 0:
            raise CandleDataError(f"line {line}: candle is not aligned to {timeframe}.")
        if previous_ms is not None and open_ms != previous_ms + step_ms:
            gap_start = _utc_from_ms(str(previous_ms + step_ms), "gap", line)
            raise CandleDataError(
                f"line {line}: candles are not contiguous; first missing candle "
                f"opens at {gap_start.isoformat()}. Choose a period without gaps."
            )
        close_ms = row[6]
        if close_ms != str(open_ms + step_ms - 1):
            raise CandleDataError(f"line {line}: close_time_ms does not match.")
        open_time = _utc_from_ms(row[0], "open_time_ms", line)
        if _utc_from_ms(close_ms, "close_time_ms", line) >= fetched_at:
            raise CandleDataError(f"line {line}: candle was not closed when fetched.")
        values = [
            _decimal(row[index], CSV_HEADER[index], line) for index in range(1, 6)
        ]
        opening, high, low, close, volume = values
        if min(opening, high, low, close) <= 0 or volume < 0:
            raise CandleDataError(f"line {line}: prices must be positive.")
        if low > min(opening, close) or high < max(opening, close):
            raise CandleDataError(f"line {line}: OHLC values are inconsistent.")
        candles.append(Candle(open_time, opening, high, low, close, volume))
        previous_ms = open_ms
        if len(candles) > MAX_CANDLES:
            raise CandleDataError("The candle file exceeds the supported size.")
    if not candles:
        raise CandleDataError("The candle file has no candles.")
    digest = sha256(text.encode("utf-8")).hexdigest()
    return CandleSeries(
        source=meta["source"],
        venue=meta["venue"],
        symbol=symbol,
        timeframe=timeframe,
        fetched_at=fetched_at,
        candles=tuple(candles),
        content_sha256=digest,
    )


def format_candle_csv(
    *,
    source: str,
    symbol: str,
    timeframe: str,
    fetched_at: datetime,
    rows: list[tuple[int, str, str, str, str, str, int]],
) -> str:
    """Write provider rows verbatim with the provenance header."""
    stamp = fetched_at.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    out = [
        f"# source={source} venue=BINANCE-SPOT symbol={symbol} "
        f"timeframe={timeframe} fetched_at={stamp}",
        ",".join(CSV_HEADER),
    ]
    out.extend(",".join(str(value) for value in row) for row in rows)
    return "\n".join(out) + "\n"
