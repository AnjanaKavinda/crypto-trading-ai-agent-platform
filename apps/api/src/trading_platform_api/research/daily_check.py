"""Daily research check through the local API (E2c3, ADR-0032).

Explicitly refreshes the approved Spot pairs on 4h and 1d through the same
local web endpoint the browser uses, then checks data quality, the required
indicators and the journal and strategy-signal reads. For the protocol v2
forward stage it also refreshes any missing historical window back to each
candidate's fixed warm-up start (fixed, aligned windows) and reads each
candidate's forward stage. It separately reads public PAXG daily candles for
the C2 paper tracker. The READY / PROBLEM report records check results and
simulated research evidence. It has no decision, journal or order write path.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlsplit

import httpx

from trading_platform_api.research.candles import parse_candle_csv
from trading_platform_api.research.fetch import fetch_klines
from trading_platform_api.research.forward import (
    FORWARD_STRATEGIES,
    PAXG_HISTORY_START,
    PAXG_SYMBOL,
    history_start,
    paxg_forward_record,
)
from trading_platform_api.research.report import _jsonable
from trading_platform_api.research.walk_forward import V2_STRATEGIES

DEFAULT_BASE_URL = "http://127.0.0.1:5173"
INSTRUMENTS = (
    "BTC-USDT-SPOT",
    "ETH-USDT-SPOT",
    "BNB-USDT-SPOT",
    "SOL-USDT-SPOT",
    "XRP-USDT-SPOT",
)
# Candles per explicit refresh: the API bounds one refresh to 501 candles (and
# 90 days below 1d), so both 4h and 1d get 501 and EMA 500 warms up on both.
REFRESH_LIMITS = {"4h": 501, "1d": 501}
TIMEFRAME_SECONDS = {"4h": 14_400, "1d": 86_400}
REQUIRED_INDICATORS = (
    "ema-20",
    "ema-50",
    "ema-500",
    "atr-14",
    "bollinger-bands-20",
    "rsi-14",
)
# Indicators reported but not required, per timeframe (none: a 501-candle
# refresh warms up EMA 500 on 4h and 1d).
NOT_REQUIRED: dict[str, frozenset[str]] = {}
READ_PATHS = (
    ("decision journal read", "/api/research/decision-journal?limit=20"),
    (
        "strategy-signal read",
        "/api/research/strategy-signals?contract_id=C-026&schema_version=2&limit=20",
    ),
)
# The API refuses refreshes started less than one second apart.
REFRESH_PAUSE_SECONDS = 1.5

# (method, url, headers, body) -> (status, response body)
Transport = Callable[[str, str, Mapping[str, str], bytes | None], tuple[int, bytes]]


@dataclass(frozen=True, slots=True)
class CheckResult:
    name: str
    ready: bool
    detail: str
    evidence: dict[str, Any] | None = None


def urllib_transport(
    method: str, url: str, headers: Mapping[str, str], body: bytes | None
) -> tuple[int, bytes]:
    """Plain HTTP to the loopback web server, ignoring any proxy settings."""
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    request = urllib.request.Request(url, data=body, method=method)
    for key, value in headers.items():
        request.add_header(key, value)
    try:
        with opener.open(request, timeout=90) as response:
            return int(response.status), bytes(response.read())
    except urllib.error.HTTPError as exc:
        return int(exc.code), bytes(exc.read())


def _headers(*, origin: str | None, json_body: bool) -> dict[str, str]:
    headers = {"Accept": "application/json", "X-Correlation-ID": str(uuid.uuid4())}
    if json_body:
        headers["Content-Type"] = "application/json"
    if origin is not None:
        # Browsers send Origin on POST; same-origin GETs omit it.
        headers["Origin"] = origin
    return headers


def _problem_text(status: int, payload: bytes) -> str:
    try:
        problem = json.loads(payload)
    except ValueError:
        return f"HTTP {status}"
    if not isinstance(problem, dict):
        return f"HTTP {status}"
    parts = [str(problem[key]) for key in ("code", "title") if problem.get(key)]
    return f"HTTP {status}" + (f" ({'; '.join(parts)})" if parts else "")


# Candles per historical backfill window (each refresh is bounded to 501
# candles, and to 90 days below 1d).
BACKFILL_CANDLES = {"4h": 480, "1d": 501}


def _iso(moment: datetime) -> str:
    return moment.astimezone(UTC).isoformat().replace("+00:00", "Z")


def backfill_windows(
    timeframe: str, start: datetime, now: datetime
) -> list[tuple[datetime, datetime]]:
    """Fixed, aligned historical windows from ``start`` that end before the
    current refresh window; identical on every run."""
    step = timedelta(seconds=TIMEFRAME_SECONDS[timeframe])
    width = step * BACKFILL_CANDLES[timeframe]
    end_ts = int(now.astimezone(UTC).timestamp()) // int(step.total_seconds())
    current_start = (
        datetime.fromtimestamp(end_ts * int(step.total_seconds()), UTC)
        - step * REFRESH_LIMITS[timeframe]
    )
    windows = []
    cursor = start
    while cursor < current_start:
        windows.append((cursor, min(cursor + width, current_start)))
        cursor += width
    return [(a, b) for a, b in windows if (b - a) >= step * 2]


def _covered(snapshot: Any, start: datetime, end: datetime) -> bool:
    if not isinstance(snapshot, dict):
        return False
    candles = snapshot.get("candles") or ()
    if (snapshot.get("data_quality") or {}).get("status") != "VALID" or not candles:
        return False
    first = datetime.fromisoformat(str(candles[0]["open_time"]).replace("Z", "+00:00"))
    last = datetime.fromisoformat(str(candles[-1]["close_time"]).replace("Z", "+00:00"))
    return first <= start and last >= end


def refresh_body(timeframe: str, now: datetime) -> dict[str, Any]:
    seconds = TIMEFRAME_SECONDS[timeframe]
    limit = REFRESH_LIMITS[timeframe]
    end_ts = int(now.astimezone(UTC).timestamp()) // seconds * seconds
    end = datetime.fromtimestamp(end_ts, UTC)
    start = end - timedelta(seconds=seconds * limit)
    return {
        "timeframe": timeframe,
        "coverage_start": start.isoformat().replace("+00:00", "Z"),
        "coverage_end": end.isoformat().replace("+00:00", "Z"),
        "limit": limit,
    }


def _snapshot_checks(
    label: str, timeframe: str, snapshot: Mapping[str, Any]
) -> list[CheckResult]:
    quality = snapshot.get("data_quality") or {}
    status = quality.get("status")
    context = snapshot.get("temporal_context")
    ready = status == "VALID" and context == "CURRENT"
    results = [
        CheckResult(
            f"{label} quality",
            ready,
            f"quality {status}, {context}, as of {snapshot.get('as_of')}, "
            f"snapshot {snapshot.get('snapshot_id')}",
        )
    ]
    indicators = snapshot.get("indicators") or {}
    missing = []
    notes = []
    for indicator in REQUIRED_INDICATORS:
        entry = indicators.get(indicator) or {}
        state = entry.get("status", "MISSING")
        if state == "AVAILABLE":
            continue
        reason = entry.get("reason_code")
        text = f"{indicator} {state}" + (f" ({reason})" if reason else "")
        if indicator in NOT_REQUIRED.get(timeframe, frozenset()):
            notes.append(f"{text}, not required on {timeframe}")
        else:
            missing.append(text)
    detail = "all required available" if not missing else "; ".join(missing)
    if notes:
        detail = f"{detail}; {'; '.join(notes)}"
    results.append(CheckResult(f"{label} indicators", not missing, detail))
    return results


def run_daily_check(
    *,
    base_url: str = DEFAULT_BASE_URL,
    transport: Transport = urllib_transport,
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
    sleep: Callable[[float], None] = time.sleep,
    paxg_fetch: Callable[..., str] = fetch_klines,
) -> list[CheckResult]:
    base = base_url.rstrip("/")
    parts = urlsplit(base)
    origin = f"{parts.scheme}://{parts.netloc}"
    results: list[CheckResult] = []
    first = True
    for timeframe in ("4h", "1d"):
        for instrument in INSTRUMENTS:
            label = f"{instrument} {timeframe}"
            if not first:
                sleep(REFRESH_PAUSE_SECONDS)
            first = False
            body = json.dumps(refresh_body(timeframe, now())).encode("utf-8")
            try:
                status, payload = transport(
                    "POST",
                    f"{base}/api/research/spot/{instrument}/refresh",
                    _headers(origin=origin, json_body=True),
                    body,
                )
            except OSError as exc:
                results.append(
                    CheckResult(f"{label} refresh", False, f"unreachable: {exc}")
                )
                continue
            if status != 200:
                results.append(
                    CheckResult(
                        f"{label} refresh", False, _problem_text(status, payload)
                    )
                )
                continue
            try:
                snapshot = json.loads(payload)
            except ValueError:
                snapshot = None
            if not isinstance(snapshot, dict):
                results.append(
                    CheckResult(f"{label} refresh", False, "unreadable response")
                )
                continue
            results.append(
                CheckResult(
                    f"{label} refresh",
                    True,
                    f"HTTP 200, {len(snapshot.get('candles') or ())} candles",
                )
            )
            results.extend(_snapshot_checks(label, timeframe, snapshot))
    for name, path in READ_PATHS:
        try:
            status, payload = transport(
                "GET", f"{base}{path}", _headers(origin=None, json_body=False), None
            )
        except OSError as exc:
            results.append(CheckResult(name, False, f"unreachable: {exc}"))
            continue
        detail = "HTTP 200" if status == 200 else _problem_text(status, payload)
        results.append(CheckResult(name, status == 200, detail))
    as_of = now()
    results.extend(_forward_checks(base, origin, transport, as_of, sleep))
    results.append(_paxg_forward_check(as_of, paxg_fetch))
    return results


def _paxg_forward_check(now: datetime, fetch: Callable[..., str]) -> CheckResult:
    name = "forward stage PAXGUSDT ema-cross-1d v1 (research only)"
    try:
        document = fetch(
            symbol=PAXG_SYMBOL,
            timeframe="1d",
            start=PAXG_HISTORY_START,
            research_only=True,
            now=now,
        )
        record = paxg_forward_record(parse_candle_csv(document, research_only=True))
    except (
        httpx.HTTPError,
        OSError,
        ValueError,
        TypeError,
        KeyError,
        IndexError,
        ArithmeticError,
    ) as exc:
        return CheckResult(
            name, False, f"PAXG research data unavailable ({type(exc).__name__})"
        )
    detail = (
        f"{record['stage']} ({record['reason']}), "
        f"{record['closed_trades']} closed SIMULATED trades"
    )
    return CheckResult(name, True, detail, record)


def _forward_checks(
    base: str,
    origin: str,
    transport: Transport,
    now: datetime,
    sleep: Callable[[float], None],
) -> list[CheckResult]:
    results: list[CheckResult] = []
    for strategy_id, strategy in FORWARD_STRATEGIES.items():
        timeframe = V2_STRATEGIES[strategy_id][0]
        start = history_start(strategy)
        for instrument in INSTRUMENTS:
            for low, high in backfill_windows(timeframe, start, now):
                label = f"{instrument} {timeframe} history {_iso(low)[:10]}"
                query = f"timeframe={timeframe}&limit=501&as_of={quote(_iso(high))}"
                try:
                    status, payload = transport(
                        "GET",
                        f"{base}/api/research/spot/{instrument}/candles?{query}",
                        _headers(origin=None, json_body=False),
                        None,
                    )
                    snapshot = json.loads(payload) if status == 200 else None
                except (OSError, ValueError):
                    snapshot = None
                if _covered(snapshot, low, high):
                    continue
                sleep(REFRESH_PAUSE_SECONDS)
                body = {
                    "timeframe": timeframe,
                    "coverage_start": _iso(low),
                    "coverage_end": _iso(high),
                    "limit": int((high - low).total_seconds())
                    // TIMEFRAME_SECONDS[timeframe],
                }
                try:
                    status, payload = transport(
                        "POST",
                        f"{base}/api/research/spot/{instrument}/refresh",
                        _headers(origin=origin, json_body=True),
                        json.dumps(body).encode("utf-8"),
                    )
                except OSError as exc:
                    results.append(CheckResult(label, False, f"unreachable: {exc}"))
                    continue
                detail = (
                    "backfilled (HTTP 200)"
                    if status == 200
                    else _problem_text(status, payload)
                )
                results.append(CheckResult(label, status == 200, detail))
        name = f"forward stage {strategy_id} v{strategy.version}"
        try:
            status, payload = transport(
                "GET",
                f"{base}/api/research/forward/{strategy_id}?version={strategy.version}",
                _headers(origin=None, json_body=False),
                None,
            )
        except OSError as exc:
            results.append(CheckResult(name, False, f"unreachable: {exc}"))
            continue
        if status != 200:
            results.append(CheckResult(name, False, _problem_text(status, payload)))
            continue
        try:
            record = json.loads(payload)
            detail = (
                f"{record['stage']} ({record['reason']}), "
                f"{record['forward']['closed_trades']} closed SIMULATED trades"
            )
        except (ValueError, KeyError, TypeError):
            results.append(CheckResult(name, False, "unreadable response"))
            continue
        results.append(CheckResult(name, True, detail))
    return results


def to_markdown(
    results: list[CheckResult], *, generated_at: datetime, base_url: str
) -> str:
    overall = "READY" if all(item.ready for item in results) else "PROBLEM"
    problems = sum(1 for item in results if not item.ready)
    lines = [
        f"# Daily research check {generated_at.astimezone(UTC):%Y-%m-%d}",
        "",
        f"- Overall: **{overall}** ({problems} problem(s), {len(results)} checks)",
        f"- Run at: {generated_at.astimezone(UTC).isoformat()}",
        f"- Local API: {base_url}",
        "- Scope: explicit refresh and reads only; no decision, journal entry, "
        "outcome or order was recorded.",
        "",
        "| Check | Result | Detail |",
        "|---|---|---|",
    ]
    for item in results:
        result = "READY" if item.ready else "PROBLEM"
        detail = item.detail.replace("|", "\\|")
        lines.append(f"| {item.name} | {result} | {detail} |")
    for item in results:
        if item.evidence is not None:
            lines.extend(
                [
                    "",
                    f"## {item.name} evidence",
                    "",
                    "```json",
                    json.dumps(_jsonable(item.evidence), indent=2, sort_keys=True),
                    "```",
                ]
            )
    return "\n".join(lines) + "\n"


def write_report(
    results: list[CheckResult],
    *,
    out: Path,
    generated_at: datetime,
    base_url: str,
) -> Path:
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"daily-check-{generated_at.astimezone(UTC):%Y-%m-%d}.md"
    path.write_text(
        to_markdown(results, generated_at=generated_at, base_url=base_url),
        encoding="utf-8",
    )
    return path
