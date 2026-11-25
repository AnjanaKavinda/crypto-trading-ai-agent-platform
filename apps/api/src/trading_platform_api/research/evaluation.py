"""Pre-registered evaluation protocol, metrics and verdict.

The protocol is fixed in code before any real-data run and reported by its
digest. Changing any criterion requires a new protocol version; a result is
only valid against the protocol version it names.

Verdict rules (holdout segment, all symbols pooled):

- INCONCLUSIVE when fewer than ``min_holdout_trades`` trades exist.
- FAIL when pooled expectancy <= 0, the equal-weight portfolio return <= 0
  (does not beat cash), portfolio max drawdown exceeds the limit, or the
  portfolio return/drawdown ratio is below buy-and-hold's.
- PASS only when none of the above apply, the profit factor reaches
  ``min_profit_factor`` and the bootstrap lower bound of the mean trade
  return is above zero. Otherwise INCONCLUSIVE.

A PASS is historical research evidence for this exact strategy version, data
and cost assumptions. It is not a probability that a future trade wins and
grants no trading authority.
"""

from __future__ import annotations

import json
import random
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from decimal import Decimal
from hashlib import sha256

from trading_platform_api.research.backtest import SegmentResult, Trade


@dataclass(frozen=True, slots=True)
class EvaluationProtocol:
    protocol_id: str = "spot-trend-holdout"
    version: int = 1
    holdout_fraction: Decimal = Decimal("0.30")
    min_holdout_trades: int = 30
    max_portfolio_drawdown: Decimal = Decimal("0.30")
    min_profit_factor: Decimal = Decimal("1.20")
    bootstrap_resamples: int = 5000
    bootstrap_lower_quantile: Decimal = Decimal("0.05")
    bootstrap_seed: int = 20261125
    baselines: tuple[str, ...] = ("CASH", "BUY_AND_HOLD")

    def describe(self) -> dict[str, object]:
        payload = asdict(self)
        for key, value in payload.items():
            if isinstance(value, Decimal):
                payload[key] = str(value)
        payload["baselines"] = list(self.baselines)
        return payload

    @property
    def content_sha256(self) -> str:
        document = json.dumps(self.describe(), sort_keys=True, separators=(",", ":"))
        return sha256(document.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class TradeStats:
    trades: int
    wins: int
    win_rate: Decimal | None
    expectancy: Decimal | None
    average_win: Decimal | None
    average_loss: Decimal | None
    profit_factor: Decimal | None
    average_r: Decimal | None


@dataclass(frozen=True, slots=True)
class CurveStats:
    total_return: Decimal
    max_drawdown: Decimal
    return_to_drawdown: Decimal | None


@dataclass(frozen=True, slots=True)
class Verdict:
    status: str
    reasons: tuple[str, ...]


def trade_stats(trades: Sequence[Trade]) -> TradeStats:
    count = len(trades)
    if count == 0:
        return TradeStats(0, 0, None, None, None, None, None, None)
    returns = [item.net_return for item in trades]
    gains = [value for value in returns if value > 0]
    losses = [value for value in returns if value <= 0]
    loss_sum = -sum(losses, Decimal(0))
    return TradeStats(
        trades=count,
        wins=len(gains),
        win_rate=Decimal(len(gains)) / Decimal(count),
        expectancy=sum(returns, Decimal(0)) / Decimal(count),
        average_win=sum(gains, Decimal(0)) / len(gains) if gains else None,
        average_loss=sum(losses, Decimal(0)) / len(losses) if losses else None,
        profit_factor=sum(gains, Decimal(0)) / loss_sum if loss_sum > 0 else None,
        average_r=sum((item.r_multiple for item in trades), Decimal(0))
        / Decimal(count),
    )


def curve_stats(curve: Sequence[Decimal]) -> CurveStats:
    peak = Decimal(1)
    worst = Decimal(0)
    for value in curve:
        peak = max(peak, value)
        worst = max(worst, (peak - value) / peak)
    total = curve[-1] - Decimal(1)
    ratio = total / worst if worst > 0 else None
    return CurveStats(total, worst, ratio)


def portfolio_curve(curves: Sequence[Sequence[Decimal]]) -> tuple[Decimal, ...]:
    """Equal-weight, never-rebalanced portfolio of per-symbol equity curves."""
    lengths = {len(curve) for curve in curves}
    if len(lengths) != 1:
        raise ValueError("Portfolio curves must share the same bar timeline.")
    count = Decimal(len(curves))
    return tuple(sum(values, Decimal(0)) / count for values in zip(*curves))


def bootstrap_lower_bound(
    returns: Sequence[Decimal], protocol: EvaluationProtocol
) -> Decimal | None:
    if len(returns) < 2:
        return None
    rng = random.Random(protocol.bootstrap_seed)
    size = len(returns)
    means = sorted(
        sum((returns[rng.randrange(size)] for _ in range(size)), Decimal(0))
        / Decimal(size)
        for _ in range(protocol.bootstrap_resamples)
    )
    position = int(protocol.bootstrap_lower_quantile * protocol.bootstrap_resamples)
    return means[position]


def decide(
    protocol: EvaluationProtocol,
    holdout: Sequence[SegmentResult],
) -> tuple[Verdict, dict[str, object]]:
    pooled = [trade for segment in holdout for trade in segment.trades]
    stats = trade_stats(pooled)
    strategy = curve_stats(portfolio_curve([item.equity for item in holdout]))
    holding = curve_stats(
        portfolio_curve([item.buy_and_hold_equity for item in holdout])
    )
    lower = bootstrap_lower_bound([item.net_return for item in pooled], protocol)
    evidence: dict[str, object] = {
        "pooled": stats,
        "portfolio": strategy,
        "buy_and_hold_portfolio": holding,
        "bootstrap_lower_bound_mean_return": lower,
    }
    if stats.trades < protocol.min_holdout_trades:
        return (
            Verdict(
                "INCONCLUSIVE",
                (
                    f"INSUFFICIENT_SAMPLE: {stats.trades} holdout trades < "
                    f"{protocol.min_holdout_trades}",
                ),
            ),
            evidence,
        )
    assert stats.expectancy is not None
    failures: list[str] = []
    if stats.expectancy <= 0:
        failures.append("NON_POSITIVE_EXPECTANCY_AFTER_COSTS")
    if strategy.total_return <= 0:
        failures.append("DOES_NOT_BEAT_CASH")
    if strategy.max_drawdown > protocol.max_portfolio_drawdown:
        failures.append("DRAWDOWN_LIMIT_EXCEEDED")
    if holding.return_to_drawdown is not None and (
        strategy.return_to_drawdown is None
        and strategy.total_return <= holding.total_return
        or strategy.return_to_drawdown is not None
        and strategy.return_to_drawdown < holding.return_to_drawdown
    ):
        failures.append("DOES_NOT_BEAT_BUY_AND_HOLD_RISK_ADJUSTED")
    if failures:
        return Verdict("FAIL", tuple(failures)), evidence
    weak: list[str] = []
    if stats.profit_factor is not None and (
        stats.profit_factor < protocol.min_profit_factor
    ):
        weak.append("PROFIT_FACTOR_BELOW_THRESHOLD")
    if lower is None or lower <= 0:
        weak.append("EXPECTANCY_NOT_DISTINGUISHABLE_FROM_ZERO")
    if weak:
        return Verdict("INCONCLUSIVE", tuple(weak)), evidence
    return Verdict("PASS", ("ALL_PREREGISTERED_CRITERIA_MET",)), evidence
