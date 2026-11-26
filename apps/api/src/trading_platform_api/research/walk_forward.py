"""Protocol v2 study: development-era judgement plus a contaminated holdout.

Implements ``spot-walk-forward-prospective`` v2 exactly as pre-registered on
#516 (2026-11-26) for ``trend-daily-regime`` v1:

- Candles before ``development_start`` are ignored; indicators warm up from
  that date, so trading starts once every input is defined.
- Historical stage: one continuous backtest per symbol over the development
  era (trading start up to, not including, ``seen_start``). All v1 criteria
  apply pooled across symbols, plus positive pooled expectancy after costs in
  at least ``min_positive_windows`` of ``windows`` consecutive equal windows.
  A trade belongs to the window that contains its entry bar.
- The v1 holdout (``seen_start`` to ``seen_end``) is run separately and
  reported as CONTAMINATED_INFORMATIONAL; it never affects the verdict.
- Bars from ``prospective_start`` onward are counted, never evaluated here.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from trading_platform_api.research.backtest import (
    CostAssumptions,
    SegmentResult,
    Trade,
    run_segment,
)
from trading_platform_api.research.candles import TIMEFRAME_SECONDS, CandleSeries
from trading_platform_api.research.evaluation import (
    Verdict,
    WalkForwardProtocol,
    decide,
    trade_stats,
)
from trading_platform_api.research.report import (
    LIMITATIONS,
    METHOD_VERSION,
    StudyError,
    _jsonable,
    _num,
    _pct,
    _segment_summary,
)
from trading_platform_api.research.strategy import TrendDailyRegime

V2_LIMITATIONS = (
    *LIMITATIONS,
    "The development era was not blind: crypto history up to 2025 was broadly "
    "known when the candidate was chosen. Only the prospective stage is unseen.",
    "The 2025-05-12 to 2026-11-25 period was seen in the v1 study; its figures "
    "are informational and contaminated.",
)


def _day(value: str) -> datetime:
    return datetime.fromisoformat(value).replace(tzinfo=UTC)


def window_bounds(start: int, end: int, count: int) -> list[tuple[int, int]]:
    """``count`` consecutive equal windows over ``[start, end)``.

    Each window has ``(end - start) // count`` bars; the last also takes the
    remainder.
    """
    size = (end - start) // count
    if size < 1:
        raise StudyError("The development era is shorter than the window count.")
    edges = [start + size * index for index in range(count)] + [end]
    return list(zip(edges[:-1], edges[1:]))


def historical_verdict(
    protocol: WalkForwardProtocol,
    era: list[SegmentResult],
    symbols: list[str],
    window_trades: list[list[Trade]],
) -> tuple[Verdict, dict[str, object], int]:
    base, evidence = decide(protocol, era, symbols, sample_label="development-era")
    positive = 0
    for trades in window_trades:
        stats = trade_stats(trades)
        if stats.expectancy is not None and stats.expectancy > 0:
            positive += 1
    if base.status == "INCONCLUSIVE" and base.reasons[0].startswith(
        "INSUFFICIENT_SAMPLE"
    ):
        return base, evidence, positive
    window_failure = positive < protocol.min_positive_windows
    reason = (
        f"TOO_FEW_POSITIVE_WINDOWS: {positive} of {protocol.windows} < "
        f"{protocol.min_positive_windows}"
    )
    if base.status == "FAIL":
        reasons = (*base.reasons, reason) if window_failure else base.reasons
        return Verdict("FAIL", reasons), evidence, positive
    if window_failure:
        return Verdict("FAIL", (reason,)), evidence, positive
    if base.status == "PASS":
        return (
            Verdict("HISTORICAL_PASS", ("ALL_PREREGISTERED_CRITERIA_MET",)),
            evidence,
            positive,
        )
    return base, evidence, positive


def run_walk_forward_study(
    series: list[CandleSeries],
    *,
    strategy: TrendDailyRegime | None = None,
    protocol: WalkForwardProtocol | None = None,
    costs: CostAssumptions | None = None,
    created_at: datetime | None = None,
) -> dict[str, Any]:
    strategy = strategy or TrendDailyRegime()
    protocol = protocol or WalkForwardProtocol()
    costs = costs or CostAssumptions()
    if not series:
        raise StudyError("At least one candle series is required.")
    symbols = [item.symbol for item in series]
    if len(set(symbols)) != len(symbols):
        raise StudyError("Use one file per symbol.")
    if {item.timeframe for item in series} != {"1d"}:
        raise StudyError("trend-daily-regime v1 is pre-registered for 1d only.")
    step = timedelta(seconds=TIMEFRAME_SECONDS["1d"])
    era_start = _day(protocol.development_start)
    seen_start = _day(protocol.seen_start)
    seen_end = _day(protocol.seen_end)
    prospective_start = _day(protocol.prospective_start)
    for item in series:
        if item.first_open > era_start:
            raise StudyError(
                f"{item.symbol} starts {item.first_open.date()}, after the "
                f"development era start {era_start.date()}; fetch with "
                f"--start {protocol.development_start}."
            )
        if item.last_open < seen_start - step:
            raise StudyError(
                f"{item.symbol} ends {item.last_open.date()}, before the end of "
                f"the development era {(seen_start - step).date()}."
            )

    def offset(moment: datetime) -> int:
        return int((moment - era_start) / step)

    era_segments: list[SegmentResult] = []
    seen_segments: list[SegmentResult] = []
    window_trades: list[list[Trade]] = [[] for _ in range(protocol.windows)]
    per_symbol: dict[str, dict[str, Any]] = {}
    windows: list[tuple[int, int]] = []
    trade_start_index = 0
    prospective_bars = 0
    for item in series:
        candles = tuple(c for c in item.candles if c.open_time >= era_start)
        signals = strategy.signals(candles)
        trade_start_index = signals.first_tradable_index
        era_end = offset(seen_start)
        if trade_start_index >= era_end:
            raise StudyError("The development era is shorter than the warm-up.")
        windows = window_bounds(trade_start_index, era_end, protocol.windows)
        era = run_segment(candles, signals, costs, start=trade_start_index, end=era_end)
        era_segments.append(era)
        for trade in era.trades:
            entry = offset(trade.entry_time)
            for number, (low, high) in enumerate(windows):
                if low <= entry < high:
                    window_trades[number].append(trade)
        seen_finish = min(len(candles), offset(seen_end) + 1)
        seen: SegmentResult | None = None
        if seen_finish > era_end:
            seen = run_segment(candles, signals, costs, start=era_end, end=seen_finish)
            seen_segments.append(seen)
        prospective_bars = max(
            prospective_bars,
            sum(1 for c in candles if c.open_time >= prospective_start),
        )
        per_symbol[item.symbol] = {
            "development_era": _segment_summary(era),
            "development_era_trades": era.trades,
            "seen_holdout_informational": (
                _segment_summary(seen) if seen is not None else None
            ),
        }

    verdict, evidence, positive = historical_verdict(
        protocol, era_segments, symbols, window_trades
    )
    window_rows = [
        {
            "window": number + 1,
            "start": era_start + step * low,
            "end": era_start + step * (high - 1),
            "bars": high - low,
            "pooled": trade_stats(window_trades[number]),
        }
        for number, (low, high) in enumerate(windows)
    ]
    seen_evidence: dict[str, object] | None = None
    if (
        len(seen_segments) == len(series)
        and len({item.bars for item in seen_segments}) == 1
    ):
        _, seen_evidence = decide(protocol, seen_segments, symbols)
    report = {
        "report_type": "LEAN_SPOT_WALK_FORWARD_STUDY",
        "label": "RESEARCH EVIDENCE ONLY - NO TRADING AUTHORITY",
        "method_version": METHOD_VERSION,
        "created_at": created_at or datetime.now(UTC),
        "strategy": {**strategy.describe(), "content_sha256": strategy.content_sha256},
        "protocol": {**protocol.describe(), "content_sha256": protocol.content_sha256},
        "costs": costs,
        "datasets": [
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
            for item in series
        ],
        "periods": {
            "development_start": era_start + step * trade_start_index,
            "development_end": seen_start - step,
            "seen_start": seen_start,
            "seen_end": seen_end,
            "prospective_start": prospective_start,
            "prospective_bars_present_not_evaluated": prospective_bars,
        },
        "stage": "HISTORICAL",
        "verdict": verdict,
        "next_stage": (
            "PROSPECTIVE: record signals forward from "
            f"{protocol.prospective_start}; review at 15 trades or 6 months"
            if verdict.status == "HISTORICAL_PASS"
            else "NONE: only a HISTORICAL_PASS moves to the prospective stage"
        ),
        "development_era_evidence": evidence,
        "positive_windows": positive,
        "windows": window_rows,
        "seen_holdout_informational": {
            "status": "CONTAMINATED_INFORMATIONAL",
            "note": "Seen in the v1 study; never used for this verdict.",
            "evidence": seen_evidence,
        },
        "per_symbol": per_symbol,
        "limitations": V2_LIMITATIONS,
        "authority": {
            "qualification_authorized": False,
            "approval_authorized": False,
            "execution_authorized": False,
        },
    }
    return _jsonable(report)


def to_markdown_v2(report: dict[str, Any]) -> str:
    verdict = report["verdict"]
    evidence = report["development_era_evidence"]
    pooled = evidence["pooled"]
    portfolio = evidence["portfolio"]
    holding = evidence["buy_and_hold_portfolio"]
    periods = report["periods"]
    protocol = report["protocol"]
    lines = [
        f"# Strategy study: {report['strategy']['strategy_id']} "
        f"v{report['strategy']['version']} (protocol {protocol['protocol_id']} "
        f"v{protocol['version']})",
        "",
        f"**{report['label']}**",
        "",
        f"## Historical verdict: {verdict['status']}",
        "",
        *[f"- {reason}" for reason in verdict["reasons"]],
        "",
        f"Next stage: {report['next_stage']}.",
        "",
        f"Development era (judged): {periods['development_start']} to "
        f"{periods['development_end']}. Positive windows: "
        f"{report['positive_windows']} of {protocol['windows']} "
        f"(need {protocol['min_positive_windows']}).",
        "",
        "## Development era, all symbols pooled (after costs)",
        "",
        "| Measure | Strategy | Buy and hold |",
        "|---|---|---|",
        f"| Trades | {pooled['trades']} | 1 per symbol |",
        f"| Win rate | {_pct(pooled['win_rate'])} | |",
        f"| Expectancy per trade | {_pct(pooled['expectancy'])} | |",
        f"| Profit factor | {_num(pooled['profit_factor'])} | |",
        f"| Bootstrap 5% lower bound of mean trade | "
        f"{_pct(evidence['bootstrap_lower_bound_mean_return'])} | |",
        f"| Portfolio return | {_pct(portfolio['total_return'])} | "
        f"{_pct(holding['total_return'])} |",
        f"| Portfolio max drawdown | {_pct(portfolio['max_drawdown'])} | "
        f"{_pct(holding['max_drawdown'])} |",
        f"| Return / drawdown | {_num(portfolio['return_to_drawdown'])} | "
        f"{_num(holding['return_to_drawdown'])} |",
        "",
        "## Windows (pooled, trade assigned by entry bar)",
        "",
        "| Window | Start | End | Trades | Expectancy |",
        "|---|---|---|---|---|",
        *[
            f"| {row['window']} | {row['start']} | {row['end']} | "
            f"{row['pooled']['trades']} | {_pct(row['pooled']['expectancy'])} |"
            for row in report["windows"]
        ],
        "",
        "## Per symbol (development era)",
        "",
        "| Symbol | Trades | Expectancy | Return | Max DD | B&H return | B&H max DD |",
        "|---|---|---|---|---|---|---|",
    ]
    for symbol, item in report["per_symbol"].items():
        era = item["development_era"]
        stats = era["trade_stats"]
        lines.append(
            f"| {symbol} | {stats['trades']} | {_pct(stats['expectancy'])} | "
            f"{_pct(era['strategy_curve']['total_return'])} | "
            f"{_pct(era['strategy_curve']['max_drawdown'])} | "
            f"{_pct(era['buy_and_hold_curve']['total_return'])} | "
            f"{_pct(era['buy_and_hold_curve']['max_drawdown'])} |"
        )
    seen = report["seen_holdout_informational"]
    lines += [
        "",
        f"## Seen v1 holdout {periods['seen_start']} to {periods['seen_end']}: "
        f"{seen['status']}",
        "",
        seen["note"],
        "",
    ]
    if seen["evidence"] is not None:
        seen_pooled = seen["evidence"]["pooled"]
        lines += [
            f"- Trades {seen_pooled['trades']}, expectancy "
            f"{_pct(seen_pooled['expectancy'])}, portfolio return "
            f"{_pct(seen['evidence']['portfolio']['total_return'])}, max drawdown "
            f"{_pct(seen['evidence']['portfolio']['max_drawdown'])}",
            "",
        ]
    costs = report["costs"]
    lines += [
        f"Bars from {periods['prospective_start']} present in the data and not "
        f"evaluated: {periods['prospective_bars_present_not_evaluated']}.",
        "",
        "## Provenance",
        "",
        f"- Method: `{report['method_version']}`",
        f"- Strategy digest: `{report['strategy']['content_sha256']}`",
        f"- Protocol `{protocol['protocol_id']}` v{protocol['version']}: "
        f"`{protocol['content_sha256']}`",
        f"- Costs: {costs['fee_bps_per_side']} bps fee + "
        f"{costs['slippage_bps_per_side']} bps slippage per side ({costs['basis']})",
        *[
            f"- {item['symbol']} {item['timeframe']}: {item['candles']} candles, "
            f"{item['first_open']} to {item['last_open']}, fetched "
            f"{item['fetched_at']}, sha256 `{item['content_sha256']}`"
            for item in report["datasets"]
        ],
        "",
        "## Limitations",
        "",
        *[f"- {item}" for item in report["limitations"]],
        "",
    ]
    return "\n".join(lines)
