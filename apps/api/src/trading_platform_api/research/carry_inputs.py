"""Local E11 research inputs; sourced historical margin tiers, never account APIs."""

from __future__ import annotations

import csv
import io
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from hashlib import sha256
from pathlib import Path
from urllib.parse import urlsplit

from trading_platform_api.research.candles import CSV_HEADER, Candle, parse_candle_csv
from trading_platform_api.research.futures_data import HOUR_MS, SYMBOLS, validate_rows
from trading_platform_api.research.report import StudyError


def utc(value: str) -> datetime:
    at = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if at.tzinfo is None:
        raise StudyError("Input timestamps must have an explicit timezone.")
    return at.astimezone(UTC)


def number(value: object) -> Decimal:
    if not isinstance(value, str):
        raise StudyError("Margin/monetary values must be decimal strings.")
    try:
        result = Decimal(value)
    except InvalidOperation as exc:
        raise StudyError("Invalid financial decimal input.") from exc
    if not result.is_finite():
        raise StudyError("Non-finite financial input.")
    return result


@dataclass(frozen=True)
class MarginTier:
    symbol: str
    start: datetime
    end: datetime
    floor: Decimal
    cap: Decimal
    rate: Decimal
    amount: Decimal


@dataclass(frozen=True)
class MarginSchedule:
    source: str
    retrieved_at: datetime
    tiers: tuple[MarginTier, ...]
    content_sha256: str

    def maintenance(self, symbol: str, at: datetime, notional: Decimal) -> Decimal:
        matches = [
            t
            for t in self.tiers
            if t.symbol == symbol
            and t.start <= at < t.end
            and t.floor <= notional < t.cap
        ]
        if len(matches) != 1:
            raise StudyError(
                f"{symbol} {at.isoformat()}: historical margin tier unavailable"
            )
        tier = matches[0]
        required = notional * tier.rate - tier.amount
        if required < 0:
            raise StudyError("Margin table produces negative maintenance margin.")
        return required


def load_margin_schedule(path: Path) -> MarginSchedule:
    raw = path.read_bytes()
    body = json.loads(raw)
    source = body["source"]
    if not isinstance(source, str) or not source.startswith("https://"):
        raise StudyError("Margin table needs its HTTPS source reference.")
    source_url = urlsplit(source)
    if not source_url.hostname or source_url.username or source_url.password:
        raise StudyError(
            "Margin source must be a public reference without credentials."
        )
    retrieved = utc(body["retrieved_at"])
    tiers = tuple(
        MarginTier(
            row["symbol"],
            utc(row["effective_from"]),
            utc(row["effective_until"]),
            number(row["notional_floor"]),
            number(row["notional_cap"]),
            number(row["maintenance_rate"]),
            number(row["maintenance_amount"]),
        )
        for row in body["tiers"]
    )
    if not tiers:
        raise StudyError("Empty maintenance-margin schedule.")
    for i, tier in enumerate(tiers):
        if (
            tier.symbol not in SYMBOLS
            or tier.start >= tier.end
            or not Decimal(0) <= tier.floor < tier.cap
            or not Decimal(0) < tier.rate < Decimal(1)
            or tier.amount < 0
            or tier.floor * tier.rate - tier.amount < 0
        ):
            raise StudyError("Invalid maintenance-margin tier.")
        for other in tiers[:i]:
            if (
                tier.symbol == other.symbol
                and tier.start < other.end
                and other.start < tier.end
                and tier.floor < other.cap
                and other.floor < tier.cap
            ):
                raise StudyError("Overlapping maintenance-margin tiers.")
    return MarginSchedule(source, retrieved, tiers, sha256(raw).hexdigest())


@dataclass(frozen=True)
class CarryData:
    symbol: str
    spot: tuple[Candle, ...]
    perp: tuple[Candle, ...]
    mark: tuple[Candle, ...]
    funding: tuple[tuple[datetime, Decimal], ...]
    digests: dict[str, str]


def _futures_rows(path: Path, symbol: str, dataset: str) -> tuple[list[list[str]], str]:
    raw = path.read_bytes()
    document = raw.decode("utf-8")
    header, body = document.split("\n", 1)
    prefix, recorded = header.rsplit(" content_sha256=", 1)
    if sha256((prefix + "\n" + body).encode()).hexdigest() != recorded:
        raise StudyError(f"{path.name}: content SHA256 mismatch")
    parts = prefix.removeprefix("# ").split()
    meta = dict(part.split("=", 1) for part in parts)
    if len(parts) != len(meta):
        raise StudyError(f"{path.name}: duplicate provenance field")
    if (
        not header.startswith("# ")
        or len(meta) != 6
        or meta["venue"] != "BINANCE-USDM"
        or meta["symbol"] != symbol
        or meta["dataset"] != dataset
        or not meta["source"]
        or meta["interval"] != ("8h" if dataset == "funding" else "1h")
    ):
        raise StudyError(f"{path.name}: provenance mismatch")
    fetched = utc(meta["fetched_at"])
    reader = csv.reader(io.StringIO(body))
    columns = tuple(next(reader))
    expected = (
        ("funding_time_ms", "funding_rate") if dataset == "funding" else CSV_HEADER
    )
    if columns != expected:
        raise StudyError(f"{path.name}: invalid CSV columns")
    rows = list(reader)
    if not rows:
        raise StudyError(f"{path.name}: empty data")
    # Validate the whole supplied file, including its closure and stated grid.
    start_ms, last_ms = int(rows[0][0]), int(rows[-1][0])
    end_ms = last_ms + (1 if dataset == "funding" else HOUR_MS)
    if end_ms > int(fetched.timestamp() * 1000):
        raise StudyError(f"{path.name}: unsettled or unclosed data")
    validate_rows(
        rows, symbol=symbol, dataset=dataset, start_ms=start_ms, end_ms=end_ms
    )
    return rows, sha256(raw).hexdigest()


def load_carry_data(
    directory: Path, symbol: str, start: datetime, end: datetime
) -> CarryData:
    """Load one fixed set without changing dates or substituting symbols."""
    if symbol not in SYMBOLS:
        raise StudyError("Unregistered carry symbol.")
    start_ms, end_ms = int(start.timestamp() * 1000), int(end.timestamp() * 1000)
    spot_bytes = (directory / "spot" / f"{symbol}_1h.csv").read_bytes()
    spot_series = parse_candle_csv(spot_bytes.decode().replace("\r\n", "\n"))
    if spot_series.symbol != symbol or spot_series.timeframe != "1h":
        raise StudyError("Spot symbol/timeframe mismatch.")
    spot = tuple(c for c in spot_series.candles if start <= c.open_time < end)
    digests = {"spot": sha256(spot_bytes).hexdigest()}
    loaded: dict[str, list[list[str]]] = {}
    for kind in ("klines", "premium", "funding", "mark"):
        interval = "8h" if kind == "funding" else "1h"
        rows, digest = _futures_rows(
            directory / "um-futures" / f"{symbol}_{kind}_{interval}.csv", symbol, kind
        )
        selected = [r for r in rows if start_ms <= int(r[0]) < end_ms]
        validate_rows(
            selected, symbol=symbol, dataset=kind, start_ms=start_ms, end_ms=end_ms
        )
        digests[kind] = digest
        loaded[kind] = selected

    def candles(kind: str) -> tuple[Candle, ...]:
        return tuple(
            Candle(
                datetime.fromtimestamp(int(r[0]) / 1000, UTC),
                *(Decimal(v) for v in r[1:6]),
            )
            for r in loaded[kind]
        )

    perp, mark = candles("klines"), candles("mark")
    if tuple(c.open_time for c in spot) != tuple(c.open_time for c in perp):
        raise StudyError(f"{symbol}: Spot/perpetual timeline mismatch")
    funding = tuple(
        (datetime.fromtimestamp(int(r[0]) / 1000, UTC), Decimal(r[1]))
        for r in loaded["funding"]
    )
    return CarryData(symbol, spot, perp, mark, funding, digests)
