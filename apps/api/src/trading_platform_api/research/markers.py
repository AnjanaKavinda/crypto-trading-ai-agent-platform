"""Chart markers for ``ema-trend-atr-stop`` v1 over one persisted Spot snapshot.

The markers replay the research backtest (``run_segment``) over the served,
quality-checked candles of a single snapshot. They are research evidence for a
chart, not a verdict, a signal to trade or an order. Every value carries one
label:

- ``VERIFIED_FACT``: read or recomputed from the persisted, validated candles.
- ``RESEARCH_PROPOSAL``: depends on a research assumption (cost model, stop
  rule, owner-entered sizing inputs).
- ``NOT_APPLICABLE``: has no meaning for this long-only Spot strategy.
- ``UNAVAILABLE``: cannot be computed; ``reason`` says why.

Fails closed: if the snapshot is not VALID or is stale, or if a required
indicator is not available, no markers are returned. EMA20, EMA50 and ATR14
are recomputed by the research formulas and must equal the snapshot's served
indicator values exactly at every marker, otherwise no markers are returned.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime
from decimal import ROUND_DOWN, Decimal
from typing import Any

from trading_platform_api.research.backtest import CostAssumptions, run_segment
from trading_platform_api.research.candles import Candle
from trading_platform_api.research.indicators import atr_wilder, ema
from trading_platform_api.research.strategy import EmaTrendAtrStop

SIZING_INPUTS_MISSING = "enter account size and risk %"
QUANTITY_STEP = Decimal("0.00000001")
_REQUIRED_INDICATORS = ("ema-20", "ema-50", "atr-14")
_EVIDENCE_SCOPE = (
    "Replays ema-trend-atr-stop v1 over this snapshot only. Not a strategy "
    "verdict, not a recommendation and not an order."
)


def _fact(value: object) -> dict[str, Any]:
    return {"label": "VERIFIED_FACT", "value": _text(value), "reason": None}


def _proposal(value: object, reason: str) -> dict[str, Any]:
    return {"label": "RESEARCH_PROPOSAL", "value": _text(value), "reason": reason}


def _unavailable(reason: str) -> dict[str, Any]:
    return {"label": "UNAVAILABLE", "value": None, "reason": reason}


def _not_applicable(reason: str) -> dict[str, Any]:
    return {"label": "NOT_APPLICABLE", "value": None, "reason": reason}


def _text(value: object) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat().replace("+00:00", "Z")
    return value


def position_size(
    *,
    entry: Decimal,
    stop: Decimal,
    account_size: Decimal | None,
    risk_pct: Decimal | None,
) -> dict[str, Any]:
    """Spot size = (account x risk%) / (entry - stop), capped at account / entry."""
    if account_size is None or risk_pct is None:
        return {"quantity": _unavailable(SIZING_INPUTS_MISSING), "capped": None}
    if not (account_size.is_finite() and risk_pct.is_finite()):
        raise ValueError("Sizing inputs must be finite.")
    if account_size <= 0 or not Decimal(0) < risk_pct <= Decimal(100):
        raise ValueError("Require account_size > 0 and 0 < risk_pct <= 100.")
    distance = entry - stop
    if entry <= 0 or distance <= 0:
        return {
            "quantity": _unavailable("entry must be above a positive stop"),
            "capped": None,
        }
    risk_amount = account_size * risk_pct / Decimal(100)
    by_risk = risk_amount / distance
    cap = account_size / entry
    capped = by_risk > cap
    quantity = (cap if capped else by_risk).quantize(QUANTITY_STEP, ROUND_DOWN)
    basis = (
        "capped at account / entry: Spot, no leverage"
        if capped
        else "(account x risk%) / (entry - stop), before fees"
    )
    return {
        "quantity": _proposal(quantity, basis),
        "capped": capped,
        "risk_amount_usdt": _proposal(risk_amount, "account x risk%"),
        "notional_usdt": _proposal(quantity * entry, "quantity x entry"),
        "loss_at_stop_usdt": _proposal(
            quantity * distance, "quantity x (entry - stop), before fees"
        ),
    }


def _served_values(
    indicators: Mapping[str, Any], name: str, count: int
) -> list[Decimal | None]:
    points = indicators[name]["result"]["points"]
    if len(points) != count:
        raise ValueError(f"{name} points do not match the candles.")
    return [None if p["value"] is None else Decimal(p["value"]) for p in points]


def _empty(status: str, reason_code: str, base: dict[str, Any]) -> dict[str, Any]:
    return {**base, "status": status, "reason_code": reason_code, "markers": []}


def build_strategy_markers(
    *,
    candles: Sequence[Candle],
    data_quality_status: str,
    indicators: Mapping[str, Any],
    account_size: Decimal | None = None,
    risk_pct: Decimal | None = None,
    strategy: EmaTrendAtrStop | None = None,
    costs: CostAssumptions | None = None,
) -> dict[str, Any]:
    strategy = strategy or EmaTrendAtrStop()
    costs = costs or CostAssumptions()
    base: dict[str, Any] = {
        "strategy": {
            "strategy_id": strategy.strategy_id,
            "version": strategy.version,
            "content_sha256": strategy.content_sha256,
            "parameters": strategy.describe(),
        },
        "costs": {
            "fee_bps_per_side": str(costs.fee_bps_per_side),
            "slippage_bps_per_side": str(costs.slippage_bps_per_side),
            "basis": costs.basis,
            "label": "RESEARCH_PROPOSAL",
        },
        "sizing_inputs": {
            "account_size_usdt": None if account_size is None else str(account_size),
            "risk_pct": None if risk_pct is None else str(risk_pct),
        },
        "evidence_scope": _EVIDENCE_SCOPE,
        "not_applicable": {
            "leverage": _not_applicable("Spot research, no leverage"),
            "take_profit": _not_applicable("v1 exits on EMA cross or stop only"),
            "funding": _not_applicable("Spot has no funding payments"),
        },
    }
    if data_quality_status != "VALID":
        return _empty("UNAVAILABLE", f"DATA_QUALITY_{data_quality_status}", base)
    for name in _REQUIRED_INDICATORS:
        item = indicators.get(name)
        if item is None or item.get("status") != "AVAILABLE":
            reason = None if item is None else item.get("reason_code")
            return _empty("UNAVAILABLE", reason or "INDICATOR_UNAVAILABLE", base)

    candles = tuple(candles)
    signals = strategy.signals(candles)
    start = signals.first_tradable_index
    if len(candles) <= start + 1:
        return _empty("WARMUP", "INSUFFICIENT_HISTORY", base)

    closes = [item.close for item in candles]
    fast = ema(closes, strategy.fast_period)
    slow = ema(closes, strategy.slow_period)
    atr = atr_wilder(candles, strategy.atr_period)
    served = {
        "ema-20": _served_values(indicators, "ema-20", len(candles)),
        "ema-50": _served_values(indicators, "ema-50", len(candles)),
        "atr-14": _served_values(indicators, "atr-14", len(candles)),
    }
    computed = {"ema-20": fast, "ema-50": slow, "atr-14": atr}
    index_of = {item.open_time: index for index, item in enumerate(candles)}

    def readout(index: int) -> dict[str, Any]:
        for name, values in computed.items():
            if values[index] != served[name][index]:
                raise _ParityError(name)
        bar = candles[index]
        return {
            "candle_open_time": _fact(bar.open_time),
            "open": _fact(bar.open),
            "high": _fact(bar.high),
            "low": _fact(bar.low),
            "close": _fact(bar.close),
            "ema_20": _fact(served["ema-20"][index]),
            "ema_50": _fact(served["ema-50"][index]),
            "atr_14": _fact(served["atr-14"][index]),
        }

    def cross_condition(index: int, direction: str) -> dict[str, Any]:
        text = "above" if direction == "up" else "below"
        return {
            "condition": f"EMA20 closed {text} EMA50 after being on the other side",
            "met": True,
            "previous_ema_20": _fact(fast[index - 1]),
            "previous_ema_50": _fact(slow[index - 1]),
            "ema_20": _fact(fast[index]),
            "ema_50": _fact(slow[index]),
        }

    def buy_marker(
        signal_index: int, fill: tuple[int, Decimal, Decimal] | None
    ) -> dict[str, Any]:
        atr_value = atr[signal_index]
        distance = signals.stop_distance[signal_index]
        assert atr_value is not None and distance is not None
        marker: dict[str, Any] = {
            "side": "BUY",
            "time": _fact(candles[signal_index].open_time),
            "signal_known_at": "signal candle close",
            "conditions": [
                cross_condition(signal_index, "up"),
                {
                    "condition": "ATR14 is positive",
                    "met": True,
                    "atr_14": _fact(atr_value),
                },
            ],
            "indicators": readout(signal_index),
            "stop_distance": _proposal(
                distance, f"{strategy.stop_atr_multiple} x ATR14 at signal close"
            ),
        }
        if fill is None:
            pending = "fills at the next candle's open, which is not closed yet"
            marker.update(
                status="PENDING_FILL",
                fill_time=_unavailable(pending),
                entry_open=_unavailable(pending),
                modelled_entry_fill=_unavailable(pending),
                stop=_unavailable(pending),
                position_size={"quantity": _unavailable(pending), "capped": None},
            )
            return marker
        fill_index, fill_price, stop = fill
        marker.update(
            status="FILLED",
            fill_time=_fact(candles[fill_index].open_time),
            entry_open=_fact(candles[fill_index].open),
            modelled_entry_fill=_proposal(
                fill_price, "next candle open plus modelled slippage"
            ),
            stop=_proposal(stop, "modelled entry fill minus stop distance"),
            position_size=position_size(
                entry=fill_price,
                stop=stop,
                account_size=account_size,
                risk_pct=risk_pct,
            ),
        )
        return marker

    def sell_marker(trade: Any, exit_index: int) -> dict[str, Any]:
        if trade.exit_reason == "STOP":
            signal_index = exit_index
            conditions = [
                {
                    "condition": "candle low reached the stop",
                    "met": True,
                    "low": _fact(candles[exit_index].low),
                    "stop": _proposal(trade.stop_price, "modelled stop"),
                }
            ]
        else:
            signal_index = exit_index - 1
            conditions = [cross_condition(signal_index, "down")]
        return {
            "side": "SELL",
            "status": "FILLED",
            "exit_reason": trade.exit_reason,
            "time": _fact(candles[signal_index].open_time),
            "signal_known_at": (
                "intrabar at the stop"
                if trade.exit_reason == "STOP"
                else "signal candle close"
            ),
            "fill_time": _fact(candles[exit_index].open_time),
            "conditions": conditions,
            "indicators": readout(signal_index),
            "modelled_exit_fill": _proposal(
                trade.exit_price, "exit price minus modelled slippage"
            ),
            "net_return": _proposal(trade.net_return, "after modelled fees/slippage"),
            "r_multiple": _proposal(trade.r_multiple, "net result / initial risk"),
        }

    result = run_segment(candles, signals, costs, start=start, end=len(candles))
    markers: list[dict[str, Any]] = []
    last = len(candles) - 1
    position_open = False
    try:
        for trade in result.trades:
            entry_index = index_of[trade.entry_time]
            markers.append(
                buy_marker(
                    entry_index - 1,
                    (entry_index, trade.entry_price, trade.stop_price),
                )
            )
            if trade.exit_reason == "END_OF_SEGMENT":
                position_open = True
                if signals.exit_long[last]:
                    pending_sell = {
                        "side": "SELL",
                        "status": "PENDING_FILL",
                        "exit_reason": "SIGNAL_EXIT",
                        "time": _fact(candles[last].open_time),
                        "signal_known_at": "signal candle close",
                        "fill_time": _unavailable(
                            "fills at the next candle's open, which is not closed yet"
                        ),
                        "conditions": [cross_condition(last, "down")],
                        "indicators": readout(last),
                    }
                    markers.append(pending_sell)
                continue
            markers.append(sell_marker(trade, index_of[trade.exit_time]))
        if not position_open and signals.enter_long[last]:
            markers.append(buy_marker(last, None))
    except _ParityError:
        return _empty("UNAVAILABLE", "INDICATOR_PARITY_FAILED", base)
    return {
        **base,
        "status": "AVAILABLE",
        "reason_code": None,
        "position": "OPEN" if position_open else "FLAT",
        "markers": markers,
    }


class _ParityError(Exception):
    """Research indicator values differ from the snapshot's served values."""
