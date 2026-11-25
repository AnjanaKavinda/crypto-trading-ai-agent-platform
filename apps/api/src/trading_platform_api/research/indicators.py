"""Deterministic indicators over validated closed candles.

The formulas match ``analysis.moving_averages`` (EMA: SMA seed, alpha
2/(N+1)) and ``analysis.volatility.calculate_atr14`` (Wilder ATR: first true
range starts at candle two, first value at index ``period``). They are
restated here only because those functions are bound to bounded market
snapshots (at most 10,000 candles); a long backtest needs the same arithmetic
over a full history. Warm-up positions are ``None``.
"""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal, localcontext

from trading_platform_api.research.candles import Candle


def ema(values: Sequence[Decimal], period: int) -> list[Decimal | None]:
    if period < 1:
        raise ValueError("period must be positive.")
    if len(values) < period:
        return [None] * len(values)
    out: list[Decimal | None] = [None] * (period - 1)
    previous = sum(values[:period], Decimal(0)) / Decimal(period)
    out.append(previous)
    alpha = Decimal(2) / Decimal(period + 1)
    for value in values[period:]:
        previous = alpha * value + (Decimal(1) - alpha) * previous
        out.append(previous)
    return out


def atr_wilder(candles: Sequence[Candle], period: int = 14) -> list[Decimal | None]:
    if period < 1:
        raise ValueError("period must be positive.")
    values: list[Decimal | None] = [None] * len(candles)
    ranges = [
        max(
            item.high - item.low,
            abs(item.high - candles[index - 1].close),
            abs(item.low - candles[index - 1].close),
        )
        for index, item in enumerate(candles)
        if index > 0
    ]
    if len(ranges) < period:
        return values
    with localcontext() as context:
        context.prec = 34
        previous = sum(ranges[:period], Decimal(0)) / Decimal(period)
        values[period] = previous
        for index, true_range in enumerate(ranges[period:], start=period + 1):
            previous = (previous * Decimal(period - 1) + true_range) / Decimal(period)
            values[index] = previous
    return values
