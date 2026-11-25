"""Run the pre-registered study over several symbols and build reports."""

from __future__ import annotations

import json
from dataclasses import fields, is_dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from trading_platform_api.research.backtest import (
    CostAssumptions,
    SegmentResult,
    run_segment,
)
from trading_platform_api.research.candles import TIMEFRAME_SECONDS, CandleSeries
from trading_platform_api.research.evaluation import (
    EvaluationProtocol,
    curve_stats,
    decide,
    trade_stats,
)
from trading_platform_api.research.strategy import EmaTrendAtrStop

METHOD_VERSION = "lean-spot-backtest-v1"
LIMITATIONS = (
    "Costs are configured assumptions, not observed exchange fills.",
    "Stops are assumed to fill at the stop price (or the open on a gap); real "
    "fills in fast markets can be worse.",
    "Symbols are correlated, so pooled trades are not independent; the "
    "bootstrap assumes independence and overstates certainty.",
    "One fixed parameter set was tested with no tuning, but the strategy family "
    "was chosen with general knowledge of crypto history; this is not a blind "
    "study.",
    "Spot long-only; no funding, borrowing, taxes or capacity limits.",
    "A historical result is not a probability that a future trade wins and "
    "grants no qualification, approval or execution authority.",
)


class StudyError(ValueError):
    """The study inputs cannot support a valid run."""


def _jsonable(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return value.astimezone(UTC).isoformat().replace("+00:00", "Z")
    if is_dataclass(value) and not isinstance(value, type):
        return {
            item.name: _jsonable(getattr(value, item.name)) for item in fields(value)
        }
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    return value


def _segment_summary(segment: SegmentResult) -> dict[str, Any]:
    return {
        "start": segment.start,
        "end": segment.end,
        "bars": segment.bars,
        "exposure": Decimal(segment.bars_in_market) / Decimal(segment.bars),
        "trade_stats": trade_stats(segment.trades),
        "strategy_curve": curve_stats(segment.equity),
        "buy_and_hold_curve": curve_stats(segment.buy_and_hold_equity),
    }


def run_study(
    series: list[CandleSeries],
    *,
    strategy: EmaTrendAtrStop | None = None,
    protocol: EvaluationProtocol | None = None,
    costs: CostAssumptions | None = None,
    created_at: datetime | None = None,
) -> dict[str, Any]:
    strategy = strategy or EmaTrendAtrStop()
    protocol = protocol or EvaluationProtocol()
    costs = costs or CostAssumptions()
    if not series:
        raise StudyError("At least one candle series is required.")
    timeframes = {item.timeframe for item in series}
    symbols = [item.symbol for item in series]
    if len(timeframes) != 1 or len(set(symbols)) != len(symbols):
        raise StudyError("Use one timeframe and one file per symbol.")
    step = timedelta(seconds=TIMEFRAME_SECONDS[series[0].timeframe])
    common_start = max(item.first_open for item in series)
    common_end = min(item.last_open for item in series)
    signals = {item.symbol: strategy.signals(item.candles) for item in series}

    def index_of(item: CandleSeries, moment: datetime) -> int:
        return int((moment - item.first_open) / step)

    warmup = max(
        signals[item.symbol].first_tradable_index - index_of(item, common_start)
        for item in series
    )
    trade_start = common_start + step * max(warmup, 0)
    if trade_start > common_end:
        raise StudyError("The common history is shorter than the warm-up period.")
    total_bars = int((common_end - trade_start) / step) + 1
    holdout_bars = int(Decimal(total_bars) * protocol.holdout_fraction)
    development_bars = total_bars - holdout_bars
    if development_bars < 1 or holdout_bars < 1:
        raise StudyError("Not enough common history for development and holdout.")
    split = trade_start + step * development_bars

    per_symbol: dict[str, dict[str, Any]] = {}
    holdout_segments: list[SegmentResult] = []
    development_segments: list[SegmentResult] = []
    for item in series:
        begin = index_of(item, trade_start)
        middle = index_of(item, split)
        finish = index_of(item, common_end) + 1
        development = run_segment(
            item.candles, signals[item.symbol], costs, start=begin, end=middle
        )
        holdout = run_segment(
            item.candles, signals[item.symbol], costs, start=middle, end=finish
        )
        development_segments.append(development)
        holdout_segments.append(holdout)
        per_symbol[item.symbol] = {
            "development": _segment_summary(development),
            "holdout": _segment_summary(holdout),
            "holdout_trades": holdout.trades,
        }

    verdict, evidence = decide(protocol, holdout_segments, symbols)
    development_pooled = trade_stats(
        [trade for segment in development_segments for trade in segment.trades]
    )
    report = {
        "report_type": "LEAN_SPOT_STRATEGY_STUDY",
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
            "development_start": trade_start,
            "holdout_start": split,
            "end": common_end,
            "development_bars": development_bars,
            "holdout_bars": holdout_bars,
        },
        "verdict": verdict,
        "holdout_evidence": evidence,
        "development_pooled_trade_stats": development_pooled,
        "per_symbol": per_symbol,
        "limitations": LIMITATIONS,
        "authority": {
            "qualification_authorized": False,
            "approval_authorized": False,
            "execution_authorized": False,
        },
    }
    return _jsonable(report)


def to_json(report: dict[str, Any]) -> str:
    return json.dumps(report, indent=2, sort_keys=True) + "\n"


def _pct(value: Any) -> str:
    if value is None:
        return "n/a"
    return f"{Decimal(value) * 100:.2f}%"


def _num(value: Any) -> str:
    return "n/a" if value is None else f"{Decimal(value):.2f}"


def to_markdown(report: dict[str, Any]) -> str:
    verdict = report["verdict"]
    evidence = report["holdout_evidence"]
    pooled = evidence["pooled"]
    portfolio = evidence["portfolio"]
    holding = evidence["buy_and_hold_portfolio"]
    periods = report["periods"]
    lines = [
        f"# Strategy study: {report['strategy']['strategy_id']} "
        f"v{report['strategy']['version']}",
        "",
        f"**{report['label']}**",
        "",
        f"## Verdict: {verdict['status']}",
        "",
        *[f"- {reason}" for reason in verdict["reasons"]],
        "",
        f"Holdout period: {periods['holdout_start']} to {periods['end']} "
        f"({periods['holdout_bars']} bars). Development period (not judged): "
        f"{periods['development_start']} onward ({periods['development_bars']} bars).",
        "",
        "## Holdout, all symbols pooled (after costs)",
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
        "## Per symbol (holdout)",
        "",
        "| Symbol | Trades | Expectancy | Return | Max DD | B&H return | B&H max DD |",
        "|---|---|---|---|---|---|---|",
    ]
    for symbol, item in report["per_symbol"].items():
        hold = item["holdout"]
        stats = hold["trade_stats"]
        lines.append(
            f"| {symbol} | {stats['trades']} | {_pct(stats['expectancy'])} | "
            f"{_pct(hold['strategy_curve']['total_return'])} | "
            f"{_pct(hold['strategy_curve']['max_drawdown'])} | "
            f"{_pct(hold['buy_and_hold_curve']['total_return'])} | "
            f"{_pct(hold['buy_and_hold_curve']['max_drawdown'])} |"
        )
    costs = report["costs"]
    lines += [
        "",
        "## Provenance",
        "",
        f"- Method: `{report['method_version']}`",
        f"- Strategy digest: `{report['strategy']['content_sha256']}`",
        f"- Protocol `{report['protocol']['protocol_id']}` "
        f"v{report['protocol']['version']}: `{report['protocol']['content_sha256']}`",
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
