"""Deterministic bar-by-bar long-only Spot backtest with explicit costs.

Timing (no look-ahead): every decision uses data up to and including bar
``i``'s close; entries and signal exits fill at bar ``i + 1``'s open. A stop
is checked against each held bar's low, including the entry bar, and fills at
the stop price or at the bar's open if the bar opens through the stop. When
the signals carry a trailing distance, the stop is raised after each held
bar's close to ``highest close since entry - distance`` and is never lowered;
``Trade.stop_price`` and the R multiple keep the initial stop.

Sizing: the whole strategy equity is invested per trade (no leverage), so
results are growth of 1 unit of equity. Costs are applied on both sides:
fill price moves against the trade by the slippage rate and a fee is charged
on traded notional.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from trading_platform_api.research.candles import Candle
from trading_platform_api.research.strategy import StrategySignals

_BPS = Decimal("10000")


@dataclass(frozen=True, slots=True)
class CostAssumptions:
    """Configured research assumptions, not observed exchange fills."""

    fee_bps_per_side: Decimal = Decimal("10")
    slippage_bps_per_side: Decimal = Decimal("5")
    basis: str = "Binance Spot regular-tier taker fee (0.10%) plus 5 bps slippage"

    def __post_init__(self) -> None:
        for value in (self.fee_bps_per_side, self.slippage_bps_per_side):
            if not value.is_finite() or value < 0 or value >= _BPS:
                raise ValueError("Cost rates must be finite and in [0, 10000) bps.")

    @property
    def fee_rate(self) -> Decimal:
        return self.fee_bps_per_side / _BPS

    @property
    def slippage_rate(self) -> Decimal:
        return self.slippage_bps_per_side / _BPS


@dataclass(frozen=True, slots=True)
class Trade:
    entry_time: datetime
    entry_price: Decimal
    stop_price: Decimal
    exit_time: datetime
    exit_price: Decimal
    exit_reason: str
    gross_return: Decimal
    net_return: Decimal
    r_multiple: Decimal
    bars_held: int


@dataclass(frozen=True, slots=True)
class SegmentResult:
    start: datetime
    end: datetime
    bars: int
    trades: tuple[Trade, ...]
    equity: tuple[Decimal, ...]
    buy_and_hold_equity: tuple[Decimal, ...]
    bars_in_market: int


def _buy_fill(price: Decimal, costs: CostAssumptions) -> Decimal:
    return price * (Decimal(1) + costs.slippage_rate)


def _sell_fill(price: Decimal, costs: CostAssumptions) -> Decimal:
    return price * (Decimal(1) - costs.slippage_rate)


def _liquidation_value(
    units: Decimal, price: Decimal, costs: CostAssumptions
) -> Decimal:
    return units * _sell_fill(price, costs) * (Decimal(1) - costs.fee_rate)


def run_segment(
    candles: tuple[Candle, ...],
    signals: StrategySignals,
    costs: CostAssumptions,
    *,
    start: int,
    end: int,
) -> SegmentResult:
    """Trade bars ``start <= i < end``; any open position closes at bar end-1."""
    if not signals.first_tradable_index <= start < end <= len(candles):
        raise ValueError("Segment must lie inside the tradable candle range.")
    if len(signals.enter_long) != len(candles) or (
        signals.trail_distance is not None
        and len(signals.trail_distance) != len(candles)
    ):
        raise ValueError("Signals do not match the candle series.")
    cash = Decimal(1)
    units = Decimal(0)
    entry: tuple[int, Decimal, Decimal, Decimal] | None = None  # idx, px, stop, cost
    pending_entry = False
    pending_exit = False
    stop_now = Decimal(0)
    highest_close = Decimal(0)
    trades: list[Trade] = []
    equity: list[Decimal] = []
    in_market = 0

    def close_position(index: int, raw_price: Decimal, reason: str) -> None:
        nonlocal cash, units, entry
        assert entry is not None
        entry_index, entry_fill, stop, basis = entry
        proceeds = _liquidation_value(units, raw_price, costs)
        raw_entry = candles[entry_index].open
        risk = units * (entry_fill - stop)
        trades.append(
            Trade(
                entry_time=candles[entry_index].open_time,
                entry_price=entry_fill,
                stop_price=stop,
                exit_time=candles[index].open_time,
                exit_price=_sell_fill(raw_price, costs),
                exit_reason=reason,
                gross_return=raw_price / raw_entry - Decimal(1),
                net_return=proceeds / basis - Decimal(1),
                r_multiple=(proceeds - basis) / risk,
                bars_held=index - entry_index + 1,
            )
        )
        cash, units, entry = proceeds, Decimal(0), None

    for index in range(start, end):
        bar = candles[index]
        if pending_entry and entry is None:
            distance = signals.stop_distance[index - 1]
            assert distance is not None
            fill = _buy_fill(bar.open, costs)
            stop = fill - distance
            if stop > 0:
                basis = cash
                units = cash * (Decimal(1) - costs.fee_rate) / fill
                entry = (index, fill, stop, basis)
                stop_now, highest_close = stop, Decimal(0)
                cash = Decimal(0)
        elif pending_exit and entry is not None:
            close_position(index, bar.open, "SIGNAL_EXIT")
        pending_entry = pending_exit = False

        if entry is not None and bar.low <= stop_now:
            close_position(index, min(bar.open, stop_now), "STOP")

        if entry is not None:
            in_market += 1
            equity.append(_liquidation_value(units, bar.close, costs))
            highest_close = max(highest_close, bar.close)
            trail = signals.trail_distance
            distance = trail[index] if trail is not None else None
            if distance is not None:
                stop_now = max(stop_now, highest_close - distance)
        else:
            equity.append(cash)

        has_next = index + 1 < end
        if entry is None and has_next and signals.enter_long[index]:
            pending_entry = True
        elif entry is not None and has_next and signals.exit_long[index]:
            pending_exit = True

    if entry is not None:
        close_position(end - 1, candles[end - 1].close, "END_OF_SEGMENT")
        equity[-1] = cash

    first_fill = _buy_fill(candles[start].open, costs)
    hold_units = (Decimal(1) - costs.fee_rate) / first_fill
    hold = tuple(
        _liquidation_value(hold_units, candles[index].close, costs)
        for index in range(start, end)
    )
    return SegmentResult(
        start=candles[start].open_time,
        end=candles[end - 1].open_time,
        bars=end - start,
        trades=tuple(trades),
        equity=tuple(equity),
        buy_and_hold_equity=hold,
        bars_in_market=in_market,
    )
