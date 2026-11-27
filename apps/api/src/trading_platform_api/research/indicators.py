"""Deterministic indicators over validated closed candles.

The formulas match ``analysis.moving_averages`` (EMA: SMA seed, alpha
2/(N+1); SMA: running trailing sum) and ``analysis.volatility.calculate_atr14`` (Wilder ATR: first true
range starts at candle two, first value at index ``period``),
``analysis.momentum.calculate_rsi`` (Wilder RSI, arithmetic-mean seed) and
``analysis.volatility.calculate_bollinger_bands`` (per-window mean, population
deviation, 2 sigma) and ``analysis.volatility.calculate_realized_volatility``
(sample stdev of log returns, annualised). ADX and the prior-window Donchian
channels have no registered platform method yet; ``adx_wilder``
is the standard Wilder definition; both are documented below. They are
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


def sma(values: Sequence[Decimal], period: int) -> list[Decimal | None]:
    if period < 1:
        raise ValueError("period must be positive.")
    if len(values) < period:
        return [None] * len(values)
    out: list[Decimal | None] = [None] * (period - 1)
    divisor = Decimal(period)
    running = sum(values[:period], Decimal(0))
    out.append(running / divisor)
    for index in range(period, len(values)):
        running += values[index] - values[index - period]
        out.append(running / divisor)
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


def rsi_wilder(values: Sequence[Decimal], period: int = 14) -> list[Decimal | None]:
    if period < 1:
        raise ValueError("period must be positive.")
    out: list[Decimal | None] = [None] * len(values)
    with localcontext() as context:
        context.prec = 34
        changes = [values[i] - values[i - 1] for i in range(1, len(values))]
        if len(changes) < period:
            return out
        gains = [max(change, Decimal(0)) for change in changes]
        losses = [max(-change, Decimal(0)) for change in changes]
        average_gain = sum(gains[:period], Decimal(0)) / Decimal(period)
        average_loss = sum(losses[:period], Decimal(0)) / Decimal(period)
        for change_index in range(period, len(changes) + 1):
            if change_index > period:
                index = change_index - 1
                average_gain = (
                    average_gain * Decimal(period - 1) + gains[index]
                ) / Decimal(period)
                average_loss = (
                    average_loss * Decimal(period - 1) + losses[index]
                ) / Decimal(period)
            if average_gain == 0 and average_loss == 0:
                out[change_index] = Decimal(50)
            elif average_loss == 0:
                out[change_index] = Decimal(100)
            elif average_gain == 0:
                out[change_index] = Decimal(0)
            else:
                strength = average_gain / average_loss
                out[change_index] = Decimal(100) - (
                    Decimal(100) / (Decimal(1) + strength)
                )
    return out


def bollinger(
    values: Sequence[Decimal], period: int = 20
) -> list[tuple[Decimal, Decimal, Decimal] | None]:
    """(middle, upper, lower) per bar: window mean +/- 2 population sigma."""
    if period < 1:
        raise ValueError("period must be positive.")
    out: list[tuple[Decimal, Decimal, Decimal] | None] = []
    with localcontext() as context:
        context.prec = 34
        for end in range(1, len(values) + 1):
            if end < period:
                out.append(None)
                continue
            window = values[end - period : end]
            middle = sum(window, Decimal(0)) / Decimal(period)
            variance = sum(
                ((value - middle) ** 2 for value in window), Decimal(0)
            ) / Decimal(period)
            deviation = variance.sqrt()
            out.append(
                (
                    middle,
                    middle + Decimal(2) * deviation,
                    middle - Decimal(2) * deviation,
                )
            )
    return out


def adx_wilder(candles: Sequence[Candle], period: int = 14) -> list[Decimal | None]:
    """Wilder ADX. First directional movement and true range at candle two.

    +DM = up move if up > down and up > 0, else 0 (down move likewise).
    TR, +DM and -DM are Wilder-smoothed like ATR (mean seed of the first
    ``period`` values, then ``(prev x (period - 1) + x) / period``);
    DI = 100 x smoothed DM / smoothed TR; DX = 100 x |+DI - -DI| / (+DI + -DI)
    (0 when both are 0). ADX seeds with the mean of the first ``period`` DX
    values and is then Wilder-smoothed. First value at index ``2 x period - 1``.
    """
    if period < 1:
        raise ValueError("period must be positive.")
    out: list[Decimal | None] = [None] * len(candles)
    if len(candles) < 2 * period:
        return out
    with localcontext() as context:
        context.prec = 34
        tr: list[Decimal] = []
        plus: list[Decimal] = []
        minus: list[Decimal] = []
        for index in range(1, len(candles)):
            bar, prior = candles[index], candles[index - 1]
            tr.append(
                max(
                    bar.high - bar.low,
                    abs(bar.high - prior.close),
                    abs(bar.low - prior.close),
                )
            )
            up = bar.high - prior.high
            down = prior.low - bar.low
            plus.append(up if up > down and up > 0 else Decimal(0))
            minus.append(down if down > up and down > 0 else Decimal(0))
        size = Decimal(period)
        s_tr = sum(tr[:period], Decimal(0)) / size
        s_plus = sum(plus[:period], Decimal(0)) / size
        s_minus = sum(minus[:period], Decimal(0)) / size
        dx: list[Decimal] = []
        for offset in range(period - 1, len(tr)):
            if offset >= period:
                s_tr = (s_tr * (size - 1) + tr[offset]) / size
                s_plus = (s_plus * (size - 1) + plus[offset]) / size
                s_minus = (s_minus * (size - 1) + minus[offset]) / size
            if s_tr == 0:
                di_plus = di_minus = Decimal(0)
            else:
                di_plus = Decimal(100) * s_plus / s_tr
                di_minus = Decimal(100) * s_minus / s_tr
            total = di_plus + di_minus
            dx.append(
                Decimal(0)
                if total == 0
                else Decimal(100) * abs(di_plus - di_minus) / total
            )
        # dx[k] belongs to candle index period + k.
        adx = sum(dx[:period], Decimal(0)) / size
        out[2 * period - 1] = adx
        for k in range(period, len(dx)):
            adx = (adx * (size - 1) + dx[k]) / size
            out[period + k] = adx
    return out


def prior_highest_high(candles: Sequence[Candle], period: int) -> list[Decimal | None]:
    """Highest high of the ``period`` candles before ``t`` (``t`` excluded).

    Donchian upper channel as used by tournament candidate C3. First value at
    index ``period``.
    """
    if period < 1:
        raise ValueError("period must be positive.")
    return [
        None
        if index < period
        else max(item.high for item in candles[index - period : index])
        for index in range(len(candles))
    ]


def prior_lowest_low(candles: Sequence[Candle], period: int) -> list[Decimal | None]:
    """Lowest low of the ``period`` candles before ``t`` (``t`` excluded)."""
    if period < 1:
        raise ValueError("period must be positive.")
    return [
        None
        if index < period
        else min(item.low for item in candles[index - period : index])
        for index in range(len(candles))
    ]


def realised_volatility(
    values: Sequence[Decimal], period: int = 20, periods_per_year: int = 365
) -> list[Decimal | None]:
    """Annualised sample stdev of the last ``period`` close-to-close log returns.

    Same arithmetic as ``analysis.volatility.calculate_realized_volatility``:
    ``ln(c_t) - ln(c_{t-1})``, divisor ``period - 1``, times
    ``sqrt(periods_per_year)``. First value at index ``period``.
    """
    if period < 2 or periods_per_year < 1:
        raise ValueError("period must be at least 2 and periods_per_year positive.")
    out: list[Decimal | None] = [None] * len(values)
    with localcontext() as context:
        context.prec = 34
        returns = [
            values[index].ln() - values[index - 1].ln()
            for index in range(1, len(values))
        ]
        annualiser = Decimal(periods_per_year).sqrt()
        for end in range(period, len(returns) + 1):
            window = returns[end - period : end]
            mean = sum(window, Decimal(0)) / Decimal(period)
            variance = sum(
                ((value - mean) ** 2 for value in window), Decimal(0)
            ) / Decimal(period - 1)
            out[end] = variance.sqrt() * annualiser
    return out
