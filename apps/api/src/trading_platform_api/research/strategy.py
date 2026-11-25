"""Versioned rule-based Spot strategies for the lean research lane.

A strategy is an immutable parameter set plus deterministic rules. Any change
to a rule or parameter must ship as a new ``version``; results are always
reported against ``content_sha256``.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from decimal import Decimal
from hashlib import sha256

from trading_platform_api.research.candles import Candle
from trading_platform_api.research.indicators import atr_wilder, ema


@dataclass(frozen=True, slots=True)
class StrategySignals:
    """Per-bar decisions known at that bar's close."""

    enter_long: tuple[bool, ...]
    exit_long: tuple[bool, ...]
    stop_distance: tuple[Decimal | None, ...]
    first_tradable_index: int


@dataclass(frozen=True, slots=True)
class EmaTrendAtrStop:
    """Long-only trend following.

    - Enter long at the next bar's open after EMA(fast) closes above EMA(slow)
      having been at or below it on the previous close.
    - Initial protective stop: entry fill minus ``stop_atr_multiple`` x ATR,
      using the ATR known at the signal close. The stop does not trail.
    - Exit at the next bar's open after EMA(fast) closes below EMA(slow), or at
      the stop if a bar trades through it (at the open if it gaps through).
    """

    strategy_id: str = "ema-trend-atr-stop"
    version: int = 1
    fast_period: int = 20
    slow_period: int = 50
    atr_period: int = 14
    stop_atr_multiple: Decimal = Decimal("2")

    def __post_init__(self) -> None:
        if not 1 < self.fast_period < self.slow_period:
            raise ValueError("Require 1 < fast_period < slow_period.")
        if self.atr_period < 1 or self.stop_atr_multiple <= 0:
            raise ValueError("ATR period and stop multiple must be positive.")

    def describe(self) -> dict[str, object]:
        payload = asdict(self)
        payload["stop_atr_multiple"] = str(self.stop_atr_multiple)
        return payload

    @property
    def content_sha256(self) -> str:
        document = json.dumps(self.describe(), sort_keys=True, separators=(",", ":"))
        return sha256(document.encode("utf-8")).hexdigest()

    def signals(self, candles: tuple[Candle, ...]) -> StrategySignals:
        closes = [item.close for item in candles]
        fast = ema(closes, self.fast_period)
        slow = ema(closes, self.slow_period)
        atr = atr_wilder(candles, self.atr_period)
        enter: list[bool] = []
        leave: list[bool] = []
        stops: list[Decimal | None] = []
        for index in range(len(candles)):
            now_f, now_s = fast[index], slow[index]
            before_f = fast[index - 1] if index > 0 else None
            before_s = slow[index - 1] if index > 0 else None
            ready = None not in (now_f, now_s, before_f, before_s)
            current_atr = atr[index]
            if ready:
                assert now_f is not None and now_s is not None
                assert before_f is not None and before_s is not None
                up = before_f <= before_s and now_f > now_s
                down = before_f >= before_s and now_f < now_s
            else:
                up = down = False
            usable = up and current_atr is not None and current_atr > 0
            enter.append(usable)
            leave.append(down)
            stops.append(
                current_atr * self.stop_atr_multiple
                if current_atr is not None
                else None
            )
        first = max(self.slow_period, self.atr_period + 1)
        return StrategySignals(tuple(enter), tuple(leave), tuple(stops), first)
