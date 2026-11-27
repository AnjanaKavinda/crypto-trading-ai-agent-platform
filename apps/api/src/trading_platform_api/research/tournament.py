"""Spot candidate tournament, protocol ``spot-candidate-tournament`` v1.

Implements the pre-registration on #516 (comment 7203109547, owner approval
"tournament OK") with Amendment 1 (gold set S5, ``owner-answer:tournament-gold``)
exactly; no tuning and no extra candidates.

- Candidates C1..C9 (``strategy.TOURNAMENT_CANDIDATES``), 1d, long-only, the
  protocol v2 backtest engine, 10 bps fee + 5 bps slippage per side.
- Each candidate trades once all its indicators exist (warm-up from the set's
  first judged candle); bars before that are not judged.
- S1 development (seen): the five approved coins, 2021-09-30 to 2025-05-11, in
  4 equal consecutive windows over the judged bars (trade assigned to the
  window of its entry bar). Hurdle H1.
- S2 unseen coins: eight research-only coins, same dates. A coin failing data
  checks is excluded and reported; no substitute. Hurdle H2 with a Bonferroni
  bootstrap lower bound (one-sided 5% / k, k = 9; 20,000 resamples, seed
  20261127; the ``int(q x resamples)``-th sorted resampled mean).
- S3 earlier history: BTC and ETH from their first Binance 1d candle (the
  later of the two, for a common timeline) to 2021-09-29. Any data failure
  makes S3 UNAVAILABLE; no date is moved. Hurdle H3.
- S4 seen period 2025-05-12 to 2026-11-25 on the S1 coins: informational only,
  never judged (indicators continue from S1, no new warm-up).
- S5 gold (PAXGUSDT): S1 dates, judged on its own with GOLD_PASS / GOLD_FAIL /
  GOLD_INCONCLUSIVE and a weekend/weekday entry split, plus S4-style
  informational figures. Never part of the tournament verdict.

Verdict order: INCONCLUSIVE if S1 or S2 has fewer than 30 trades; else
TOURNAMENT_PASS if H1, H2 and H3 are met; PROVISIONAL_PASS if H1 and H2 are met
with S3 UNAVAILABLE; FAIL otherwise. Benchmarks on every set: equal-weight
buy-and-hold over the same judged bars and cash (0% return, 0% drawdown).
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from hashlib import sha256
from pathlib import Path
from typing import Any

from trading_platform_api.research.backtest import (
    CostAssumptions,
    SegmentResult,
    Trade,
    run_segment,
)
from trading_platform_api.research.candles import (
    APPROVED_SPOT_SYMBOLS,
    CandleDataError,
    CandleSeries,
    parse_candle_csv,
)
from trading_platform_api.research.evaluation import (
    CurveStats,
    bootstrap_lower_bound,
    curve_stats,
    portfolio_curve,
    trade_stats,
)
from trading_platform_api.research.report import (
    LIMITATIONS,
    METHOD_VERSION,
    StudyError,
    _jsonable,
    _num,
    _pct,
    _trade_records,
    _trade_table,
)
from trading_platform_api.research.strategy import (
    TOURNAMENT_CANDIDATES,
    TournamentCandidate,
)
from trading_platform_api.research.walk_forward import window_bounds

DAY = timedelta(days=1)


@dataclass(frozen=True, slots=True)
class TournamentProtocol:
    protocol_id: str = "spot-candidate-tournament"
    version: int = 1
    timeframe: str = "1d"
    development_start: str = "2021-09-30"
    development_end: str = "2025-05-11"
    seen_start: str = "2025-05-12"
    seen_end: str = "2026-11-25"
    early_end: str = "2021-09-29"
    s1_symbols: tuple[str, ...] = tuple(APPROVED_SPOT_SYMBOLS)
    s2_symbols: tuple[str, ...] = (
        "ADAUSDT",
        "DOGEUSDT",
        "LTCUSDT",
        "LINKUSDT",
        "AVAXUSDT",
        "DOTUSDT",
        "TRXUSDT",
        "BCHUSDT",
    )
    s3_symbols: tuple[str, ...] = ("BTCUSDT", "ETHUSDT")
    gold_symbol: str = "PAXGUSDT"
    candidates_k: int = 9
    windows: int = 4
    min_positive_windows: int = 3
    min_trades: int = 30
    min_early_trades: int = 10
    min_gold_trades: int = 10
    max_portfolio_drawdown: Decimal = Decimal("0.30")
    max_symbol_drawdown: Decimal = Decimal("0.40")
    family_alpha: Decimal = Decimal("0.05")
    bootstrap_resamples: int = 20_000
    bootstrap_seed: int = 20261127
    amendments: tuple[str, ...] = (
        "1: gold set S5 (PAXGUSDT), owner-answer:tournament-gold",
    )

    @property
    def bootstrap_lower_quantile(self) -> Decimal:
        return self.family_alpha / Decimal(self.candidates_k)

    def describe(self) -> dict[str, object]:
        payload = asdict(self)
        for key, value in payload.items():
            if isinstance(value, Decimal):
                payload[key] = str(value)
            elif isinstance(value, tuple):
                payload[key] = list(value)
        payload["bootstrap_lower_quantile"] = str(self.bootstrap_lower_quantile)
        return payload

    @property
    def content_sha256(self) -> str:
        document = json.dumps(self.describe(), sort_keys=True, separators=(",", ":"))
        return sha256(document.encode("utf-8")).hexdigest()


def _day(value: str) -> datetime:
    return datetime.fromisoformat(value).replace(tzinfo=UTC)


@dataclass(frozen=True, slots=True)
class TournamentData:
    s1: list[CandleSeries]
    s2: list[CandleSeries]
    s2_excluded: list[dict[str, str]]
    s3: list[CandleSeries] | None
    s3_reason: str | None
    gold: CandleSeries | None
    gold_reason: str | None


def _read(path: Path) -> CandleSeries:
    return parse_candle_csv(path.read_text("utf-8"), research_only=True)


def _coverage_problem(
    item: CandleSeries, begin: datetime, last: datetime, timeframe: str
) -> str | None:
    if item.timeframe != timeframe:
        return f"timeframe {item.timeframe}, need {timeframe}"
    if item.first_open > begin:
        return f"starts {item.first_open.date()}, after {begin.date()}"
    if item.last_open < last:
        return f"ends {item.last_open.date()}, before {last.date()}"
    return None


def load_tournament_data(
    data: Path, early: Path, protocol: TournamentProtocol | None = None
) -> TournamentData:
    """Load every set; S1 failures stop the run, other sets are reported."""
    protocol = protocol or TournamentProtocol()
    tf = protocol.timeframe
    begin, last = _day(protocol.development_start), _day(protocol.development_end)

    def problem(symbol: str, directory: Path) -> tuple[CandleSeries | None, str]:
        try:
            item = _read(directory / f"{symbol}_{tf}.csv")
        except OSError as exc:
            return None, f"file not readable: {exc.strerror or exc}"
        except CandleDataError as exc:
            return None, f"data check failed: {exc}"
        if item.symbol != symbol:
            return None, f"file holds {item.symbol}, not {symbol}"
        return item, ""

    s1: list[CandleSeries] = []
    for symbol in protocol.s1_symbols:
        item, reason = problem(symbol, data)
        if item is not None:
            reason = _coverage_problem(item, begin, last, tf) or ""
        if item is None or reason:
            raise StudyError(
                f"S1 {symbol}: {reason}; fetch with --timeframe 1d --start "
                f"{protocol.development_start}."
            )
        s1.append(item)
    s2: list[CandleSeries] = []
    excluded: list[dict[str, str]] = []
    for symbol in protocol.s2_symbols:
        item, reason = problem(symbol, data)
        if item is not None:
            reason = _coverage_problem(item, begin, last, tf) or ""
        if item is None or reason:
            excluded.append({"symbol": symbol, "reason": reason})
        else:
            s2.append(item)
    early_series: list[CandleSeries] = []
    s3_reason: str | None = None
    early_last = _day(protocol.early_end)
    for symbol in protocol.s3_symbols:
        item, reason = problem(symbol, early)
        if item is not None:
            if item.timeframe != tf:
                reason = f"timeframe {item.timeframe}, need {tf}"
            elif item.last_open < early_last:
                reason = f"ends {item.last_open.date()}, before {early_last.date()}"
            elif item.first_open >= begin:
                reason = f"starts {item.first_open.date()}, no earlier history"
        if item is None or reason:
            s3_reason = f"{symbol}: {reason}"
            break
        early_series.append(item)
    s3 = None if s3_reason else early_series
    gold, gold_reason = problem(protocol.gold_symbol, data)
    if gold is not None:
        coverage = _coverage_problem(gold, begin, last, tf)
        if coverage:
            gold, gold_reason = None, coverage
    return TournamentData(
        s1, s2, excluded, s3, s3_reason, gold, gold_reason if gold is None else None
    )


@dataclass(frozen=True, slots=True)
class SetRun:
    segments: list[SegmentResult]
    informational: list[SegmentResult] | None
    begin: datetime
    trade_start: int


def _run_set(
    series: Sequence[CandleSeries],
    strategy: TournamentCandidate,
    costs: CostAssumptions,
    *,
    begin: datetime,
    judged_end: datetime,
    info_end: datetime | None = None,
) -> SetRun:
    """Judged segment [warm-up, judged_end]; optional informational segment
    (judged_end, info_end] on the same signals (no new warm-up)."""
    judged_bars = int((judged_end - begin) / DAY) + 1
    info_bars = int((info_end - begin) / DAY) + 1 if info_end else judged_bars
    segments: list[SegmentResult] = []
    extra: list[SegmentResult] | None = [] if info_end else None
    trade_start = 0
    for item in series:
        stop = info_end or judged_end
        candles = tuple(c for c in item.candles if begin <= c.open_time <= stop)
        if len(candles) < judged_bars:
            raise StudyError(f"{item.symbol} does not cover {begin} to {judged_end}.")
        signals = strategy.signals(candles)
        trade_start = signals.first_tradable_index
        if trade_start >= judged_bars:
            raise StudyError("The judged period is shorter than the warm-up.")
        segments.append(
            run_segment(candles, signals, costs, start=trade_start, end=judged_bars)
        )
        if extra is not None:
            if len(candles) == info_bars:
                extra.append(
                    run_segment(
                        candles, signals, costs, start=judged_bars, end=info_bars
                    )
                )
            else:
                extra = None
    return SetRun(segments, extra, begin, trade_start)


def _beats_buy_and_hold(strategy: CurveStats, holding: CurveStats) -> bool:
    """Return/drawdown >= buy-and-hold's (same rule as protocol v1/v2)."""
    if holding.return_to_drawdown is None:
        return True
    if strategy.return_to_drawdown is None:
        return strategy.total_return > holding.total_return
    return strategy.return_to_drawdown >= holding.return_to_drawdown


def _evidence(
    segments: Sequence[SegmentResult],
    symbols: Sequence[str],
    set_name: str,
    bootstrap: TournamentProtocol | None = None,
) -> dict[str, Any]:
    pooled = [trade for segment in segments for trade in segment.trades]
    strategy = curve_stats(portfolio_curve([s.equity for s in segments]))
    holding = curve_stats(portfolio_curve([s.buy_and_hold_equity for s in segments]))
    result: dict[str, Any] = {
        "start": segments[0].start,
        "end": segments[0].end,
        "bars": segments[0].bars,
        "symbols": list(symbols),
        "trade_records": [
            row
            for symbol, segment in zip(symbols, segments, strict=True)
            for row in _trade_records(segment, symbol, set_name)
        ],
        "pooled": trade_stats(pooled),
        "portfolio": strategy,
        "buy_and_hold_portfolio": holding,
        "cash": {"total_return": Decimal(0), "max_drawdown": Decimal(0)},
        "per_symbol": {
            name: {
                "trade_stats": trade_stats(segment.trades),
                "strategy_curve": curve_stats(segment.equity),
                "buy_and_hold_curve": curve_stats(segment.buy_and_hold_equity),
                "exposure": Decimal(segment.bars_in_market) / Decimal(segment.bars),
            }
            for name, segment in zip(symbols, segments, strict=True)
        },
    }
    if bootstrap is not None:
        result["bootstrap_lower_bound_mean_return"] = bootstrap_lower_bound(
            [trade.net_return for trade in pooled], bootstrap
        )
        result["bootstrap_lower_quantile"] = bootstrap.bootstrap_lower_quantile
        result["bootstrap_index"] = int(
            bootstrap.bootstrap_lower_quantile * bootstrap.bootstrap_resamples
        )
    return result


def _windows(run: SetRun, count: int) -> list[dict[str, Any]]:
    judged_end = run.trade_start + run.segments[0].bars
    bounds = window_bounds(run.trade_start, judged_end, count)
    buckets: list[list[Trade]] = [[] for _ in bounds]
    for segment in run.segments:
        for trade in segment.trades:
            entry = int((trade.entry_time - run.begin) / DAY)
            for number, (low, high) in enumerate(bounds):
                if low <= entry < high:
                    buckets[number].append(trade)
    return [
        {
            "window": number + 1,
            "start": run.begin + DAY * low,
            "end": run.begin + DAY * (high - 1),
            "bars": high - low,
            "pooled": trade_stats(buckets[number]),
        }
        for number, (low, high) in enumerate(bounds)
    ]


def _hurdle(failures: list[str]) -> dict[str, Any]:
    return {"met": not failures, "reasons": failures or ["MET"]}


def _common(
    evidence: dict[str, Any], minimum: int, label: str
) -> tuple[list[str], bool]:
    """Expectancy, trade count and risk-adjusted benchmark checks."""
    stats = evidence["pooled"]
    failures: list[str] = []
    few = stats.trades < minimum
    if few:
        failures.append(
            f"INSUFFICIENT_SAMPLE: {stats.trades} {label} trades < {minimum}"
        )
    if stats.expectancy is None or stats.expectancy <= 0:
        failures.append("NON_POSITIVE_EXPECTANCY_AFTER_COSTS")
    if not _beats_buy_and_hold(
        evidence["portfolio"], evidence["buy_and_hold_portfolio"]
    ):
        failures.append("DOES_NOT_BEAT_BUY_AND_HOLD_RISK_ADJUSTED")
    return failures, few


def hurdle_h1(
    evidence: dict[str, Any], windows: list[dict[str, Any]], p: TournamentProtocol
) -> tuple[dict[str, Any], bool]:
    failures, few = _common(evidence, p.min_trades, "S1")
    positive = sum(
        1
        for row in windows
        if row["pooled"].expectancy is not None and row["pooled"].expectancy > 0
    )
    if positive < p.min_positive_windows:
        failures.append(
            f"TOO_FEW_POSITIVE_WINDOWS: {positive} of {p.windows} < "
            f"{p.min_positive_windows}"
        )
    if evidence["portfolio"].max_drawdown > p.max_portfolio_drawdown:
        failures.append("PORTFOLIO_DRAWDOWN_LIMIT_EXCEEDED")
    for name, item in evidence["per_symbol"].items():
        drawdown = item["strategy_curve"].max_drawdown
        if drawdown > p.max_symbol_drawdown:
            failures.append(
                f"SYMBOL_DRAWDOWN_LIMIT_EXCEEDED: {name} {(drawdown * 100):.2f}%"
            )
    result = _hurdle(failures)
    result["positive_windows"] = positive
    return result, few


def hurdle_h2(
    evidence: dict[str, Any], p: TournamentProtocol
) -> tuple[dict[str, Any], bool]:
    failures, few = _common(evidence, p.min_trades, "S2")
    lower = evidence["bootstrap_lower_bound_mean_return"]
    if lower is None or lower <= 0:
        failures.append("BONFERRONI_BOOTSTRAP_LOWER_BOUND_NOT_ABOVE_ZERO")
    if evidence["portfolio"].max_drawdown > p.max_portfolio_drawdown:
        failures.append("PORTFOLIO_DRAWDOWN_LIMIT_EXCEEDED")
    return _hurdle(failures), few


def hurdle_h3(evidence: dict[str, Any], p: TournamentProtocol) -> dict[str, Any]:
    failures, _ = _common(evidence, p.min_early_trades, "S3")
    return _hurdle(failures)


def gold_verdict(evidence: dict[str, Any], p: TournamentProtocol) -> dict[str, Any]:
    stats = evidence["pooled"]
    if stats.trades < p.min_gold_trades:
        return {
            "status": "GOLD_INCONCLUSIVE",
            "reasons": [
                f"INSUFFICIENT_SAMPLE: {stats.trades} S5 trades < {p.min_gold_trades}"
            ],
        }
    failures, _ = _common(evidence, p.min_gold_trades, "S5")
    if failures:
        return {"status": "GOLD_FAIL", "reasons": failures}
    return {"status": "GOLD_PASS", "reasons": ["ALL_GOLD_CRITERIA_MET"]}


def tournament_verdict(
    h1: dict[str, Any],
    h2: dict[str, Any],
    h3: dict[str, Any] | None,
    *,
    s1_few: bool,
    s2_few: bool,
) -> dict[str, Any]:
    if s1_few or s2_few:
        sets = [name for name, few in (("S1", s1_few), ("S2", s2_few)) if few]
        return {
            "status": "INCONCLUSIVE",
            "reasons": [f"FEWER_THAN_30_TRADES_IN: {', '.join(sets)}"],
        }
    if h1["met"] and h2["met"] and h3 is not None and h3["met"]:
        return {"status": "TOURNAMENT_PASS", "reasons": ["H1_H2_H3_MET"]}
    if h1["met"] and h2["met"] and h3 is None:
        return {"status": "PROVISIONAL_PASS", "reasons": ["H1_H2_MET_S3_UNAVAILABLE"]}
    reasons = [
        f"{name}_NOT_MET"
        for name, hurdle in (("H1", h1), ("H2", h2), ("H3", h3))
        if hurdle is not None and not hurdle["met"]
    ]
    return {"status": "FAIL", "reasons": reasons}


def _split_weekend(segments: Sequence[SegmentResult]) -> dict[str, Any]:
    trades = [trade for segment in segments for trade in segment.trades]
    weekend = [t for t in trades if t.entry_time.weekday() >= 5]
    weekday = [t for t in trades if t.entry_time.weekday() < 5]
    return {
        "note": "Information only: split by entry day (UTC); PAXG trades 24/7 "
        "while the main gold markets close at weekends.",
        "weekend_entries": trade_stats(weekend),
        "weekday_entries": trade_stats(weekday),
    }


_SET_ORDER = ("S1", "S2", "S3", "S5", "S4_informational", "S5_seen_informational")

TOURNAMENT_LIMITATIONS = (
    *LIMITATIONS,
    "S1 was not blind: the five coins and 2021-2025 history were known when the "
    "candidates were chosen. S2 coins and S3 dates were not used to choose them.",
    "C9 already failed protocol v2 on S1; it is included as the reference.",
    "S4 (2025-05-12 to 2026-11-25) was seen in the v1 study and is never judged.",
    "Gold (S5) is one instrument; a GOLD_PASS can at most qualify a candidate "
    "for forward paper tracking on PAXG.",
    "C8 trade returns and drawdowns are on its whole equity, including cash.",
)


def run_tournament(
    data: TournamentData,
    *,
    protocol: TournamentProtocol | None = None,
    costs: CostAssumptions | None = None,
    candidates: Sequence[tuple[str, TournamentCandidate]] = TOURNAMENT_CANDIDATES,
    created_at: datetime | None = None,
) -> dict[str, Any]:
    p = protocol or TournamentProtocol()
    costs = costs or CostAssumptions()
    begin = _day(p.development_start)
    judged_end = _day(p.development_end)
    seen_end = _day(p.seen_end)
    s1_names = [item.symbol for item in data.s1]
    s2_names = [item.symbol for item in data.s2]
    s3_begin = max(item.first_open for item in data.s3) if data.s3 else None
    rows: list[dict[str, Any]] = []
    for candidate_id, strategy in candidates:
        sets: dict[str, Any] = {}
        s1 = _run_set(
            data.s1,
            strategy,
            costs,
            begin=begin,
            judged_end=judged_end,
            info_end=seen_end,
        )
        s1_evidence = _evidence(s1.segments, s1_names, "S1")
        windows = _windows(s1, p.windows)
        h1, s1_few = hurdle_h1(s1_evidence, windows, p)
        sets["S1"] = {**s1_evidence, "windows": windows, "hurdle": h1}
        sets["S4_informational"] = {
            "status": "SEEN_INFORMATIONAL" if s1.informational else "UNAVAILABLE",
            "evidence": _evidence(s1.informational, s1_names, "S4_informational")
            if s1.informational
            else None,
        }
        if data.s2:
            s2 = _run_set(data.s2, strategy, costs, begin=begin, judged_end=judged_end)
            s2_evidence = _evidence(s2.segments, s2_names, "S2", bootstrap=p)
            h2, s2_few = hurdle_h2(s2_evidence, p)
            sets["S2"] = {**s2_evidence, "hurdle": h2}
        else:
            h2, s2_few = _hurdle(["NO_S2_COIN_PASSED_DATA_CHECKS"]), True
            sets["S2"] = {"status": "UNAVAILABLE", "hurdle": h2}
        h3: dict[str, Any] | None = None
        if data.s3 and s3_begin is not None:
            s3 = _run_set(
                data.s3, strategy, costs, begin=s3_begin, judged_end=_day(p.early_end)
            )
            s3_evidence = _evidence(
                s3.segments, [item.symbol for item in data.s3], "S3"
            )
            h3 = hurdle_h3(s3_evidence, p)
            sets["S3"] = {**s3_evidence, "hurdle": h3}
        else:
            sets["S3"] = {"status": "UNAVAILABLE", "reason": data.s3_reason}
        gold: dict[str, Any] = {"status": "UNAVAILABLE", "reasons": [data.gold_reason]}
        if data.gold is not None:
            s5 = _run_set(
                [data.gold],
                strategy,
                costs,
                begin=begin,
                judged_end=judged_end,
                info_end=seen_end,
            )
            s5_evidence = _evidence(s5.segments, [data.gold.symbol], "S5")
            gold = gold_verdict(s5_evidence, p)
            sets["S5"] = {
                **s5_evidence,
                "weekend_split": _split_weekend(s5.segments),
                "gold_verdict": gold,
            }
            sets["S5_seen_informational"] = {
                "status": "SEEN_INFORMATIONAL" if s5.informational else "UNAVAILABLE",
                "evidence": _evidence(
                    s5.informational, [data.gold.symbol], "S5_seen_informational"
                )
                if s5.informational
                else None,
            }
        else:
            sets["S5"] = {"status": "UNAVAILABLE", "reason": data.gold_reason}
        rows.append(
            {
                "candidate_id": candidate_id,
                "strategy": {
                    **strategy.describe(),
                    "content_sha256": strategy.content_sha256,
                },
                "verdict": tournament_verdict(h1, h2, h3, s1_few=s1_few, s2_few=s2_few),
                "gold_verdict": gold,
                "sets": {key: sets[key] for key in _SET_ORDER if key in sets},
            }
        )

    def datasets(items: Sequence[CandleSeries]) -> list[dict[str, Any]]:
        return [
            {
                "symbol": item.symbol,
                "instrument_id": item.instrument_id,
                "venue": item.venue,
                "timeframe": item.timeframe,
                "source": item.source,
                "fetched_at": item.fetched_at,
                "first_open": item.first_open,
                "last_open": item.last_open,
                "candles": len(item.candles),
                "content_sha256": item.content_sha256,
            }
            for item in items
        ]

    passing = [
        row["candidate_id"]
        for row in rows
        if row["verdict"]["status"] in ("TOURNAMENT_PASS", "PROVISIONAL_PASS")
    ]
    report = {
        "report_type": "SPOT_CANDIDATE_TOURNAMENT",
        "label": "RESEARCH EVIDENCE ONLY - NO TRADING AUTHORITY",
        "method_version": METHOD_VERSION,
        "created_at": created_at or datetime.now(UTC),
        "protocol": {**p.describe(), "content_sha256": p.content_sha256},
        "costs": costs,
        "datasets": {
            "S1": datasets(data.s1),
            "S2": {"included": datasets(data.s2), "excluded": data.s2_excluded},
            "S3": {
                "status": "AVAILABLE" if data.s3 else "UNAVAILABLE",
                "reason": data.s3_reason,
                "judged_start": s3_begin,
                "included": datasets(data.s3 or []),
            },
            "S5": {
                "status": "AVAILABLE" if data.gold else "UNAVAILABLE",
                "reason": data.gold_reason,
                "included": datasets([data.gold] if data.gold else []),
            },
        },
        "candidates": rows,
        "summary": {
            "passing_candidates": passing,
            "conclusion": (
                "Passing candidates go to forward paper tracking (E2f2) with a "
                "6-month review; only a forward pass could justify real money."
                if passing
                else "No candidate passed: these simple rules show no defensible "
                "edge on Binance Spot after costs. No further candidates are "
                "added to this tournament."
            ),
        },
        "limitations": TOURNAMENT_LIMITATIONS,
        "authority": {
            "qualification_authorized": False,
            "approval_authorized": False,
            "execution_authorized": False,
        },
    }
    return _jsonable(report)


def _set_cell(item: dict[str, Any]) -> str:
    if item.get("status") == "UNAVAILABLE":
        return "UNAVAILABLE"
    pooled = item["pooled"]
    return f"{pooled['trades']} / {_pct(pooled['expectancy'])}"


def to_markdown_tournament(report: dict[str, Any]) -> str:
    protocol = report["protocol"]
    data = report["datasets"]
    lines = [
        f"# Spot candidate tournament (protocol {protocol['protocol_id']} "
        f"v{protocol['version']})",
        "",
        f"**{report['label']}**",
        "",
        report["summary"]["conclusion"],
        "",
        "## Verdicts",
        "",
        "| ID | Strategy | Verdict | H1 (S1) | H2 (S2) | H3 (S3) | Gold (S5) |",
        "|---|---|---|---|---|---|---|",
    ]
    for row in report["candidates"]:
        sets = row["sets"]

        def met(name: str) -> str:
            hurdle = sets[name].get("hurdle")
            if hurdle is None:
                return "UNAVAILABLE"
            return "met" if hurdle["met"] else "not met"

        lines.append(
            f"| {row['candidate_id']} | {row['strategy']['strategy_id']} "
            f"v{row['strategy']['version']} | **{row['verdict']['status']}** | "
            f"{met('S1')} | {met('S2')} | {met('S3')} | "
            f"{row['gold_verdict']['status']} |"
        )
    lines += [
        "",
        "## Trades / expectancy per trade after costs",
        "",
        "| ID | S1 | S2 | S2 Bonferroni lower bound | S3 | S5 gold | S4 seen (info) |",
        "|---|---|---|---|---|---|---|",
    ]
    for row in report["candidates"]:
        sets = row["sets"]
        seen = sets["S4_informational"]
        lines.append(
            f"| {row['candidate_id']} | {_set_cell(sets['S1'])} | "
            f"{_set_cell(sets['S2'])} | "
            f"{_pct(sets['S2'].get('bootstrap_lower_bound_mean_return'))} | "
            f"{_set_cell(sets['S3'])} | {_set_cell(sets['S5'])} | "
            f"{_set_cell(seen['evidence']) if seen['evidence'] else 'UNAVAILABLE'} |"
        )
    for row in report["candidates"]:
        lines += [
            "",
            f"## {row['candidate_id']} {row['strategy']['strategy_id']} "
            f"v{row['strategy']['version']}: {row['verdict']['status']}",
            "",
            *[f"- {reason}" for reason in row["verdict"]["reasons"]],
            "",
            "| Set | Period | Trades | Win rate | Expectancy | Return | Max DD | "
            "Return/DD | B&H return | B&H max DD | B&H return/DD | Cash |",
            "|---|---|---|---|---|---|---|---|---|---|---|---|",
        ]
        for name, item in row["sets"].items():
            evidence = item.get("evidence", item) if "pooled" not in item else item
            if not evidence or "pooled" not in evidence:
                lines.append(f"| {name} | UNAVAILABLE | | | | | | | | | | |")
                continue
            pooled = evidence["pooled"]
            port = evidence["portfolio"]
            hold = evidence["buy_and_hold_portfolio"]
            lines.append(
                f"| {name} | {evidence['start'][:10]} to {evidence['end'][:10]} | "
                f"{pooled['trades']} | {_pct(pooled['win_rate'])} | "
                f"{_pct(pooled['expectancy'])} | {_pct(port['total_return'])} | "
                f"{_pct(port['max_drawdown'])} | {_num(port['return_to_drawdown'])} | "
                f"{_pct(hold['total_return'])} | {_pct(hold['max_drawdown'])} | "
                f"{_num(hold['return_to_drawdown'])} | 0.00% |"
            )
        evidence_sets = [item.get("evidence", item) for item in row["sets"].values()]
        if any(item is not None and "trade_records" in item for item in evidence_sets):
            lines.extend(
                _trade_table(
                    [
                        trade
                        for item in evidence_sets
                        if item is not None
                        for trade in item.get("trade_records", [])
                    ]
                )
            )
        for name in ("S1", "S2", "S3"):
            hurdle = row["sets"][name].get("hurdle")
            if hurdle is not None:
                lines.append(f"\n{name} hurdle: {', '.join(hurdle['reasons'])}")
        windows = row["sets"]["S1"]["windows"]
        lines.append(
            "\nS1 windows (trades / expectancy): "
            + "; ".join(
                f"{w['window']}: {w['pooled']['trades']} / "
                f"{_pct(w['pooled']['expectancy'])}"
                for w in windows
            )
        )
        gold = row["sets"]["S5"]
        if "weekend_split" in gold:
            split = gold["weekend_split"]
            lines.append(
                f"\nS5 gold: {row['gold_verdict']['status']} "
                f"({', '.join(row['gold_verdict']['reasons'])}); weekend entries "
                f"{split['weekend_entries']['trades']} / "
                f"{_pct(split['weekend_entries']['expectancy'])}, weekday entries "
                f"{split['weekday_entries']['trades']} / "
                f"{_pct(split['weekday_entries']['expectancy'])} (information only)"
            )
    costs = report["costs"]
    lines += [
        "",
        "## Data sets",
        "",
        *[
            f"- S1 {item['symbol']}: {item['candles']} candles, {item['first_open']} "
            f"to {item['last_open']}, sha256 `{item['content_sha256']}`"
            for item in data["S1"]
        ],
        *[
            f"- S2 {item['symbol']}: {item['candles']} candles, {item['first_open']} "
            f"to {item['last_open']}, sha256 `{item['content_sha256']}`"
            for item in data["S2"]["included"]
        ],
        *[
            f"- S2 {item['symbol']}: EXCLUDED ({item['reason']})"
            for item in data["S2"]["excluded"]
        ],
        f"- S3: {data['S3']['status']}"
        + (f" ({data['S3']['reason']})" if data["S3"]["reason"] else "")
        + (
            f", judged from {data['S3']['judged_start']}"
            if data["S3"]["judged_start"]
            else ""
        ),
        *[
            f"- S3 {item['symbol']}: {item['candles']} candles, {item['first_open']} "
            f"to {item['last_open']}, sha256 `{item['content_sha256']}`"
            for item in data["S3"]["included"]
        ],
        f"- S5: {data['S5']['status']}"
        + (f" ({data['S5']['reason']})" if data["S5"]["reason"] else ""),
        *[
            f"- S5 {item['symbol']}: {item['candles']} candles, {item['first_open']} "
            f"to {item['last_open']}, sha256 `{item['content_sha256']}`"
            for item in data["S5"]["included"]
        ],
        "",
        "## Provenance",
        "",
        f"- Method: `{report['method_version']}`",
        f"- Protocol `{protocol['protocol_id']}` v{protocol['version']}: "
        f"`{protocol['content_sha256']}`",
        f"- Bootstrap: {protocol['bootstrap_resamples']} resamples, seed "
        f"{protocol['bootstrap_seed']}, lower quantile "
        f"{protocol['bootstrap_lower_quantile']} (5% / {protocol['candidates_k']})",
        f"- Costs: {costs['fee_bps_per_side']} bps fee + "
        f"{costs['slippage_bps_per_side']} bps slippage per side ({costs['basis']})",
        *[
            f"- {row['candidate_id']} digest: `{row['strategy']['content_sha256']}`"
            for row in report["candidates"]
        ],
        "",
        "## Limitations",
        "",
        *[f"- {item}" for item in report["limitations"]],
        "",
    ]
    return "\n".join(lines)
