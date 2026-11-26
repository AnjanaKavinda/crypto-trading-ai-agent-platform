"""Owner-results protocol v1: score the owner's own recorded Spot trades.

Owner-approved 2026-11-26 ("E4 OK" on #516), fixed before any owner result was
scored. Changing a criterion needs a new protocol version.

- Only the latest version of each outcome counts (corrections supersede).
- A trade counts when its position is CLOSED and its net result is known.
  Net return = net result / USDT spent on its BUY fills (fees included).
- Trades with UNKNOWN fees are listed and block a PASS; open positions are
  listed and not scored.
- Equity compounds the counted trades in order of first fill (whole equity per
  trade, as in the strategy protocol); max drawdown is measured on that curve.
- INCONCLUSIVE below ``min_trades``. FAIL when expectancy <= 0, total return
  <= 0 (does not beat cash) or max drawdown > ``max_drawdown``. PASS also needs
  profit factor >= ``min_profit_factor`` and a bootstrap 5% lower bound of the
  mean trade return > 0, with no UNKNOWN-fee trades.
- Buy-and-hold baseline: for each coin traded, hold it from the first entry
  fill to the last exit fill, using the close of the persisted, quality-VALID
  4h candle that closed at or within one candle before each time; the
  baseline is the equal-weight mean across coins. Missing candles make it
  UNAVAILABLE with the reason, never estimated. It is reported beside the
  verdict and does not change it.
- NO_TRADE (ABSTAIN) decisions: each is compared with holding that coin for
  ``no_trade_horizon_days`` from the declared time, using the same candle
  rule. Standing aside was better when that hold return is <= 0. Decisions
  whose horizon has not passed are PENDING. Kept separate from trade P&L.

Facts stay owner-reported and unverified; a PASS is evidence about past
decisions only and grants no trading authority.
"""

from __future__ import annotations

import json
import random
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from hashlib import sha256
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from trading_platform_api.learning.trade_outcome import OwnerTradeOutcome


@dataclass(frozen=True, slots=True)
class OwnerResultsProtocol:
    protocol_id: str = "owner-results"
    version: int = 1
    min_trades: int = 30
    max_drawdown: Decimal = Decimal("0.30")
    min_profit_factor: Decimal = Decimal("1.20")
    no_trade_horizon_days: int = 7
    bootstrap_resamples: int = 5000
    bootstrap_lower_quantile: Decimal = Decimal("0.05")
    bootstrap_seed: int = 20261126
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
class NoTradeDecision:
    """A current (not superseded) ABSTAIN journal declaration."""

    entry_id: str
    instrument_id: str | None
    declared_at: datetime


# price_at(instrument_id, time) -> (close, None) or (None, reason)
PriceLookup = Callable[[str, datetime], tuple[Decimal | None, str | None]]


def price_points(
    outcomes: Sequence[OwnerTradeOutcome],
    decisions: Sequence[NoTradeDecision],
    protocol: OwnerResultsProtocol,
    now: datetime,
) -> list[tuple[str, datetime]]:
    """Every (instrument, time) whose candle close the baselines need."""
    points: set[tuple[str, datetime]] = set()
    for instrument, (start, end) in _holding_windows(outcomes).items():
        points.update({(instrument, start), (instrument, end)})
    horizon = timedelta(days=protocol.no_trade_horizon_days)
    for item in decisions:
        if item.instrument_id is not None and item.declared_at + horizon <= now:
            points.update(
                {
                    (item.instrument_id, item.declared_at),
                    (item.instrument_id, item.declared_at + horizon),
                }
            )
    return sorted(points)


def _holding_windows(
    outcomes: Sequence[OwnerTradeOutcome],
) -> dict[str, tuple[datetime, datetime]]:
    windows: dict[str, tuple[datetime, datetime]] = {}
    for item in current_outcomes(outcomes):
        if net_return(item) is None:
            continue
        start, end = item.fills[0].executed_at, item.fills[-1].executed_at
        if item.instrument_id in windows:
            old_start, old_end = windows[item.instrument_id]
            start, end = min(start, old_start), max(end, old_end)
        windows[item.instrument_id] = (start, end)
    return windows


def _hold(
    price_at: PriceLookup, instrument: str, start: datetime, end: datetime
) -> tuple[dict[str, object], Decimal | None]:
    first, first_reason = price_at(instrument, start)
    last, last_reason = price_at(instrument, end)
    row: dict[str, object] = {
        "instrument_id": instrument,
        "start": start.isoformat(),
        "end": end.isoformat(),
        "start_close": _text(first),
        "end_close": _text(last),
    }
    if first is None or last is None:
        row.update(status="UNAVAILABLE", reason=first_reason or last_reason)
        return row, None
    value = last / first - Decimal(1)
    row.update(status="AVAILABLE", hold_return=str(value))
    return row, value


def buy_and_hold_baseline(
    outcomes: Sequence[OwnerTradeOutcome], price_at: PriceLookup
) -> dict[str, object]:
    windows = _holding_windows(outcomes)
    if not windows:
        return {"status": "UNAVAILABLE", "reason": "No counted trades.", "coins": []}
    rows, values = [], []
    for instrument, (start, end) in sorted(windows.items()):
        row, value = _hold(price_at, instrument, start, end)
        rows.append(row)
        values.append(value)
    if any(value is None for value in values):
        return {
            "status": "UNAVAILABLE",
            "reason": "A persisted VALID 4h candle is missing for a holding window.",
            "coins": rows,
        }
    known = [value for value in values if value is not None]
    return {
        "status": "AVAILABLE",
        "basis": "equal-weight hold of each traded coin, first entry to last exit",
        "total_return": str(sum(known, Decimal(0)) / Decimal(len(known))),
        "coins": rows,
    }


def no_trade_comparison(
    decisions: Sequence[NoTradeDecision],
    price_at: PriceLookup,
    protocol: OwnerResultsProtocol,
    now: datetime,
) -> dict[str, object]:
    horizon = timedelta(days=protocol.no_trade_horizon_days)
    rows: list[dict[str, object]] = []
    evaluated: list[Decimal] = []
    for item in sorted(decisions, key=lambda d: (d.declared_at, d.entry_id)):
        base: dict[str, object] = {
            "entry_id": item.entry_id,
            "declared_at": item.declared_at.isoformat(),
            "horizon_end": (item.declared_at + horizon).isoformat(),
        }
        if item.instrument_id is None:
            rows.append(
                {
                    **base,
                    "status": "UNAVAILABLE",
                    "reason": "Entry has no snapshot-linked instrument (C-107v1).",
                }
            )
            continue
        if item.declared_at + horizon > now:
            rows.append(
                {**base, "instrument_id": item.instrument_id, "status": "PENDING"}
            )
            continue
        row, value = _hold(
            price_at, item.instrument_id, item.declared_at, item.declared_at + horizon
        )
        if value is not None:
            evaluated.append(value)
            row["standing_aside_better"] = value <= 0
        rows.append({**base, **row})
    return {
        "status": "AVAILABLE" if evaluated else "UNAVAILABLE",
        "horizon_days": protocol.no_trade_horizon_days,
        "decisions": len(rows),
        "evaluated": len(evaluated),
        "standing_aside_better": sum(1 for value in evaluated if value <= 0),
        "average_hold_return": _text(
            sum(evaluated, Decimal(0)) / Decimal(len(evaluated)) if evaluated else None
        ),
        "items": rows,
    }


def _text(value: Decimal | None) -> str | None:
    return None if value is None else str(value)


def current_outcomes(
    outcomes: Sequence[OwnerTradeOutcome],
) -> list[OwnerTradeOutcome]:
    """Drop every outcome a later correction supersedes."""
    superseded = {
        item.supersedes.artifact_id for item in outcomes if item.supersedes is not None
    }
    return [item for item in outcomes if item.outcome_id not in superseded]


def net_return(outcome: OwnerTradeOutcome) -> Decimal | None:
    if outcome.position_status != "CLOSED" or outcome.net_result_usdt is None:
        return None
    spent = sum(
        (
            fill.quantity * fill.price_usdt
            for fill in outcome.fills
            if fill.side == "BUY"
        ),
        Decimal(0),
    )
    return outcome.net_result_usdt / spent


def _bootstrap_lower_bound(
    returns: Sequence[Decimal], protocol: OwnerResultsProtocol
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
    index = int(protocol.bootstrap_lower_quantile * protocol.bootstrap_resamples)
    return means[index]


def score_owner_results(
    outcomes: Sequence[OwnerTradeOutcome],
    protocol: OwnerResultsProtocol | None = None,
    *,
    decisions: Sequence[NoTradeDecision] = (),
    price_at: PriceLookup | None = None,
    now: datetime | None = None,
) -> dict[str, object]:
    protocol = protocol or OwnerResultsProtocol()
    current = sorted(
        current_outcomes(outcomes),
        key=lambda item: (item.fills[0].executed_at, str(item.outcome_id)),
    )
    scored: list[tuple[OwnerTradeOutcome, Decimal]] = []
    excluded: list[dict[str, str]] = []
    for item in current:
        value = net_return(item)
        if value is None:
            excluded.append(
                {
                    "outcome_id": str(item.outcome_id),
                    "reason": item.net_result_reason or "NET_RESULT_UNAVAILABLE",
                }
            )
        else:
            scored.append((item, value))
    returns = [value for _, value in scored]
    gains = [value for value in returns if value > 0]
    losses = [value for value in returns if value <= 0]
    loss_sum = -sum(losses, Decimal(0))
    count = len(returns)
    expectancy = sum(returns, Decimal(0)) / Decimal(count) if count else None
    profit_factor = sum(gains, Decimal(0)) / loss_sum if loss_sum > 0 else None
    equity = Decimal(1)
    peak = Decimal(1)
    worst = Decimal(0)
    for value in returns:
        equity *= Decimal(1) + value
        peak = max(peak, equity)
        worst = max(worst, (peak - equity) / peak)
    total_return = equity - Decimal(1)
    lower_bound = _bootstrap_lower_bound(returns, protocol)
    fee_unknown = sum(1 for item in excluded if item["reason"] == "FEE_UNKNOWN")

    reasons: list[str] = []
    if count < protocol.min_trades:
        status = "INCONCLUSIVE"
        reasons.append(
            f"INSUFFICIENT_SAMPLE: {count} closed trades < {protocol.min_trades}"
        )
    else:
        assert expectancy is not None
        if expectancy <= 0:
            reasons.append("NON_POSITIVE_EXPECTANCY_AFTER_FEES")
        if total_return <= 0:
            reasons.append("DOES_NOT_BEAT_CASH")
        if worst > protocol.max_drawdown:
            reasons.append("DRAWDOWN_LIMIT_EXCEEDED")
        if reasons:
            status = "FAIL"
        else:
            if profit_factor is not None and profit_factor < protocol.min_profit_factor:
                reasons.append("PROFIT_FACTOR_BELOW_MINIMUM")
            if lower_bound is None or lower_bound <= 0:
                reasons.append("BOOTSTRAP_LOWER_BOUND_NOT_POSITIVE")
            if fee_unknown:
                reasons.append(f"FEE_UNKNOWN_TRADES_PRESENT: {fee_unknown}")
            status = "INCONCLUSIVE" if reasons else "PASS"

    return {
        "protocol": protocol.describe(),
        "protocol_sha256": protocol.content_sha256,
        "verdict": {"status": status, "reasons": reasons},
        "trades": {
            "counted": count,
            "wins": len(gains),
            "win_rate": _text(Decimal(len(gains)) / Decimal(count) if count else None),
            "expectancy": _text(expectancy),
            "profit_factor": _text(profit_factor),
            "total_return": _text(total_return if count else None),
            "max_drawdown": _text(worst if count else None),
            "net_result_usdt": _text(
                sum(
                    (
                        item.net_result_usdt
                        for item, _ in scored
                        if item.net_result_usdt is not None
                    ),
                    Decimal(0),
                )
                if count
                else None
            ),
            "bootstrap_lower_bound": _text(lower_bound),
            "items": [
                {
                    "outcome_id": str(item.outcome_id),
                    "instrument_id": item.instrument_id,
                    "first_fill_at": item.fills[0].executed_at.isoformat(),
                    "net_return": str(value),
                    "net_result_usdt": str(item.net_result_usdt),
                    "net_result_basis": item.net_result_basis,
                    "decision_recorded_before_first_fill": (
                        item.decision_recorded_before_first_fill
                    ),
                }
                for item, value in scored
            ],
            "excluded": excluded,
        },
        "baselines": {
            "CASH": {"status": "AVAILABLE", "total_return": "0"},
            "BUY_AND_HOLD": (
                buy_and_hold_baseline(outcomes, price_at)
                if price_at is not None
                else {
                    "status": "UNAVAILABLE",
                    "reason": "Persisted candle prices were not supplied.",
                }
            ),
        },
        "no_trade_decisions": (
            no_trade_comparison(decisions, price_at, protocol, now)
            if price_at is not None and now is not None
            else {
                "status": "UNAVAILABLE",
                "horizon_days": protocol.no_trade_horizon_days,
                "reason": "Persisted candle prices were not supplied.",
            }
        ),
        "trade_facts_verified": False,
        "execution_authorized": False,
    }
