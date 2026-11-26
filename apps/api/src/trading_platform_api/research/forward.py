"""Prospective (forward) stage of protocol v2: SIMULATED signals and outcomes.

Pre-registered on #516 (2026-11-26). For each candidate strategy version the
forward record replays the frozen rules over candles that closed on or after
``prospective_start`` (indicators may warm up on earlier candles). Every
signal and outcome here is SIMULATED research evidence: fills at the next
open plus modelled slippage, the strategy's own stop/exit rules and modelled
fees. Nothing here is an order, a recommendation or a trading permission.

Stage status uses only the pre-registered rules:

- no recorded historical study verdict          -> NOT_VALIDATED
- historical verdict INCONCLUSIVE               -> NOT_VALIDATED
- historical verdict FAIL                       -> FAIL
- HISTORICAL_PASS, no forward bar evaluated yet -> HISTORICAL_PASS
- HISTORICAL_PASS, review point not reached     -> FORWARD_TESTING
- review point reached (A: 15 trades or 6 months; B: 30 trades or 3 months,
  whichever first): FORWARD_PASS if pooled expectancy after costs > 0 and the
  forward portfolio max drawdown <= historical max drawdown x 1.5, else FAIL.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from trading_platform_api.research.backtest import (
    CostAssumptions,
    SegmentResult,
    Trade,
    run_segment,
)
from trading_platform_api.research.candles import Candle
from trading_platform_api.research.evaluation import (
    WalkForwardProtocol,
    curve_stats,
    portfolio_curve,
    trade_stats,
)
from trading_platform_api.research.strategy import RangeReversion4h, TrendDailyRegime

ForwardStrategy = TrendDailyRegime | RangeReversion4h
SIMULATED = "SIMULATED"
DRAWDOWN_TOLERANCE = Decimal("1.5")


@dataclass(frozen=True, slots=True)
class ForwardReview:
    trades: int
    months: int


# Pre-registered prospective review points (#516, protocol v2).
FORWARD_REVIEWS: dict[str, ForwardReview] = {
    "trend-daily-regime": ForwardReview(trades=15, months=6),
    "range-reversion-4h": ForwardReview(trades=30, months=3),
}


@dataclass(frozen=True, slots=True)
class HistoricalVerdict:
    """The recorded historical-stage verdict of one study report."""

    status: str  # HISTORICAL_PASS / FAIL / INCONCLUSIVE
    strategy_sha256: str
    max_drawdown: Decimal  # development-era portfolio max drawdown


@dataclass(frozen=True, slots=True)
class SymbolForward:
    symbol: str
    segment: SegmentResult | None
    signals: tuple[dict[str, Any], ...]


def _day(value: str) -> datetime:
    return datetime.fromisoformat(value).replace(tzinfo=UTC)


def add_months(moment: datetime, months: int) -> datetime:
    """Same day-of-month ``months`` later (clamped to the month's last day)."""
    month_index = moment.month - 1 + months
    year, month = moment.year + month_index // 12, month_index % 12 + 1
    for day in (moment.day, 30, 29, 28):
        try:
            return moment.replace(year=year, month=month, day=day)
        except ValueError:
            continue
    raise ValueError("Unreachable month arithmetic.")


def _iso(moment: datetime) -> str:
    return moment.isoformat().replace("+00:00", "Z")


def _simulated(value: Decimal, basis: str) -> dict[str, Any]:
    return {"label": SIMULATED, "value": str(value), "basis": basis}


def _trade_signal(trade: Trade, candles: Sequence[Candle]) -> dict[str, Any]:
    index_of = {item.open_time: index for index, item in enumerate(candles)}
    entry_index = index_of[trade.entry_time]
    signal: dict[str, Any] = {
        "signal_candle_open_time": _iso(candles[entry_index - 1].open_time),
        "entry_time": _iso(trade.entry_time),
        "proposed_entry": "next candle open plus modelled slippage",
        "simulated_entry_fill": _simulated(
            trade.entry_price, "next open plus slippage"
        ),
        "simulated_initial_stop": _simulated(
            trade.stop_price, "entry fill minus pre-registered ATR stop distance"
        ),
    }
    if trade.exit_reason == "END_OF_SEGMENT":
        return {
            **signal,
            "status": "OPEN",
            "mark_to_market_return": _simulated(
                trade.net_return, "at the last close, after modelled costs"
            ),
        }
    return {
        **signal,
        "status": "CLOSED",
        "exit_time": _iso(trade.exit_time),
        "exit_reason": trade.exit_reason,
        "simulated_exit_fill": _simulated(trade.exit_price, "after slippage"),
        "simulated_net_return": _simulated(trade.net_return, "after modelled costs"),
        "simulated_r_multiple": _simulated(trade.r_multiple, "net result / risk"),
    }


FORWARD_STRATEGIES: dict[str, ForwardStrategy] = {
    "trend-daily-regime": TrendDailyRegime(),
    "range-reversion-4h": RangeReversion4h(),
}
_HISTORICAL_STATUSES = {"HISTORICAL_PASS", "FAIL", "INCONCLUSIVE"}


def historical_verdict_from_report(report: dict[str, Any]) -> HistoricalVerdict:
    """Read the historical verdict from a protocol v2 study report; fail closed.

    The report must be a walk-forward study of a registered candidate, with the
    exact current strategy and protocol digests.
    """
    if report.get("report_type") != "LEAN_SPOT_WALK_FORWARD_STUDY":
        raise ValueError("Not a protocol v2 walk-forward study report.")
    if report.get("stage") != "HISTORICAL":
        raise ValueError("Only a HISTORICAL-stage report carries this verdict.")
    described = report.get("strategy") or {}
    strategy = FORWARD_STRATEGIES.get(str(described.get("strategy_id")))
    if strategy is None or described.get("version") != strategy.version:
        raise ValueError("The report's strategy is not a registered candidate.")
    if described.get("content_sha256") != strategy.content_sha256:
        raise ValueError("The report's strategy digest does not match v1.")
    protocol = WalkForwardProtocol()
    if (report.get("protocol") or {}).get("content_sha256") != protocol.content_sha256:
        raise ValueError("The report's protocol digest does not match v2.")
    status = (report.get("verdict") or {}).get("status")
    if status not in _HISTORICAL_STATUSES:
        raise ValueError("The report has no recognised historical verdict.")
    portfolio = (report.get("development_era_evidence") or {}).get("portfolio") or {}
    try:
        drawdown = Decimal(str(portfolio["max_drawdown"]))
    except (KeyError, ArithmeticError) as exc:
        raise ValueError("The report lacks the development-era max drawdown.") from exc
    if not drawdown.is_finite() or drawdown < 0:
        raise ValueError("The development-era max drawdown is invalid.")
    return HistoricalVerdict(status, strategy.content_sha256, drawdown)


def symbol_forward(
    strategy: ForwardStrategy,
    symbol: str,
    candles: Sequence[Candle],
    *,
    prospective_start: datetime,
    costs: CostAssumptions,
) -> SymbolForward:
    """Replay the frozen rules over the closed candles from ``prospective_start``."""
    candles = tuple(candles)
    signals = strategy.signals(candles)
    start = next(
        (i for i, c in enumerate(candles) if c.open_time >= prospective_start),
        None,
    )
    if start is None:
        return SymbolForward(symbol, None, ())
    if start < signals.first_tradable_index:
        raise ValueError(
            f"{symbol}: indicators are not warmed up at the prospective start; "
            "provide earlier candles."
        )
    segment = run_segment(candles, signals, costs, start=start, end=len(candles))
    items = [_trade_signal(trade, candles) for trade in segment.trades]
    last = len(candles) - 1
    open_position = any(t.exit_reason == "END_OF_SEGMENT" for t in segment.trades)
    if not open_position and signals.enter_long[last]:
        items.append(
            {
                "signal_candle_open_time": _iso(candles[last].open_time),
                "status": "PENDING_ENTRY",
                "proposed_entry": "next candle open plus modelled slippage",
            }
        )
    return SymbolForward(symbol, segment, tuple(items))


def forward_stage(
    strategy: ForwardStrategy,
    historical: HistoricalVerdict | None,
    segments: Sequence[SegmentResult],
    *,
    as_of: datetime,
    prospective_start: datetime,
) -> dict[str, Any]:
    """Stage status, forward statistics and the rule that produced it."""
    review = FORWARD_REVIEWS[strategy.strategy_id]
    closed = [
        trade
        for segment in segments
        for trade in segment.trades
        if trade.exit_reason != "END_OF_SEGMENT"
    ]
    stats = trade_stats(closed)
    curve = (
        curve_stats(portfolio_curve([item.equity for item in segments]))
        if segments
        else None
    )
    review_at = add_months(prospective_start, review.months)
    reached = stats.trades >= review.trades or as_of >= review_at
    summary: dict[str, Any] = {
        "label": SIMULATED,
        "closed_trades": stats.trades,
        "win_rate": stats.win_rate,
        "expectancy": stats.expectancy,
        "max_drawdown": None if curve is None else curve.max_drawdown,
        "review_point": {
            "trades": review.trades,
            "date": _iso(review_at),
            "reached": reached,
        },
    }

    def result(stage: str, reason: str) -> dict[str, Any]:
        return {"stage": stage, "reason": reason, "forward": summary}

    if historical is None:
        return result("NOT_VALIDATED", "NO_HISTORICAL_VERDICT_RECORDED")
    if historical.strategy_sha256 != strategy.content_sha256:
        return result("NOT_VALIDATED", "HISTORICAL_VERDICT_FOR_OTHER_STRATEGY_DIGEST")
    if historical.status == "FAIL":
        return result("FAIL", "HISTORICAL_FAIL")
    if historical.status != "HISTORICAL_PASS":
        return result("NOT_VALIDATED", f"HISTORICAL_{historical.status}")
    if curve is None or not any(item.bars for item in segments):
        return result("HISTORICAL_PASS", "NO_FORWARD_CANDLES_YET")
    if not reached:
        return result("FORWARD_TESTING", "REVIEW_POINT_NOT_REACHED")
    limit = historical.max_drawdown * DRAWDOWN_TOLERANCE
    if stats.expectancy is None or stats.expectancy <= 0:
        return result("FAIL", "FORWARD_EXPECTANCY_NOT_POSITIVE")
    if curve.max_drawdown > limit:
        return result("FAIL", "FORWARD_DRAWDOWN_ABOVE_1_5X_HISTORICAL")
    return result("FORWARD_PASS", "PREREGISTERED_FORWARD_CRITERIA_MET")


def forward_record(
    strategy: ForwardStrategy,
    series: Mapping[str, Sequence[Candle]],
    *,
    historical: HistoricalVerdict | None,
    as_of: datetime,
    costs: CostAssumptions | None = None,
    protocol: WalkForwardProtocol | None = None,
) -> dict[str, Any]:
    """Forward signals per symbol plus the strategy's stage status."""
    protocol = protocol or WalkForwardProtocol()
    costs = costs or CostAssumptions()
    start = _day(protocol.prospective_start)
    per_symbol = [
        symbol_forward(strategy, symbol, candles, prospective_start=start, costs=costs)
        for symbol, candles in sorted(series.items())
    ]
    segments = [item.segment for item in per_symbol if item.segment is not None]
    if segments and len({item.bars for item in segments}) != 1:
        raise ValueError("Forward segments must cover the same candles per symbol.")
    return {
        "label": "SIMULATED RESEARCH EVIDENCE - NOT AN ORDER",
        "strategy": {
            "strategy_id": strategy.strategy_id,
            "version": strategy.version,
            "content_sha256": strategy.content_sha256,
        },
        "protocol": {
            "protocol_id": protocol.protocol_id,
            "version": protocol.version,
            "content_sha256": protocol.content_sha256,
            "prospective_start": _iso(start),
        },
        "costs": {
            "fee_bps_per_side": str(costs.fee_bps_per_side),
            "slippage_bps_per_side": str(costs.slippage_bps_per_side),
            "basis": costs.basis,
        },
        "signals": {item.symbol: list(item.signals) for item in per_symbol},
        **forward_stage(
            strategy,
            historical,
            segments,
            as_of=as_of,
            prospective_start=start,
        ),
        "authority": {
            "qualification_authorized": False,
            "approval_authorized": False,
            "execution_authorized": False,
        },
    }
