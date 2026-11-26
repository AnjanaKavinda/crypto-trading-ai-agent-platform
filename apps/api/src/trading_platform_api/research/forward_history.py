"""Stitch one contiguous forward history from several persisted snapshots.

Each persisted Spot snapshot holds at most 501 candles and one refresh covers
at most 90 days, so a forward replay that starts at its fixed warm-up start
(see ``forward.history_start``) is assembled from several snapshots. Nothing
is repaired or interpolated: overlapping snapshots must agree exactly, and a
missing candle between the warm-up start and the latest candle fails closed.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timedelta

from trading_platform_api.research.candles import Candle


def covering_snapshots(
    windows: Sequence[tuple[datetime, int]],
    *,
    covered_from: datetime,
    start: datetime,
    step: timedelta,
) -> list[datetime]:
    """Snapshot ``as_of`` times that extend coverage back to ``start``.

    ``windows`` are (as_of, candle_count) pairs; a snapshot covers the candles
    opening in ``[as_of - count x step, as_of)``. Greedy: each pick touches or
    overlaps the current earliest candle and reaches furthest back.
    """
    chosen: list[datetime] = []
    earliest = covered_from
    while earliest > start:
        best: tuple[datetime, datetime] | None = None
        for as_of, count in windows:
            first_open = as_of - step * count
            if as_of >= earliest and first_open < earliest:
                if best is None or first_open < best[1]:
                    best = (as_of, first_open)
        if best is None:
            raise ValueError(
                f"No persisted snapshot covers the candles before {earliest:%Y-%m-%d %H:%M} "
                "UTC; refresh that historical window first."
            )
        chosen.append(best[0])
        earliest = best[1]
    return chosen


def merge_windows(
    windows: Sequence[Sequence[Candle]], *, start: datetime, step: timedelta
) -> tuple[Candle, ...]:
    """One contiguous series from ``start``; overlaps must be identical."""
    by_time: dict[datetime, Candle] = {}
    for window in windows:
        for candle in window:
            seen = by_time.get(candle.open_time)
            if seen is not None and seen != candle:
                raise ValueError(
                    f"Persisted snapshots disagree on the candle at {candle.open_time}."
                )
            by_time[candle.open_time] = candle
    times = sorted(moment for moment in by_time if moment >= start)
    if not times or times[0] != start:
        raise ValueError(f"No persisted candle opens at the warm-up start {start}.")
    for previous, current in zip(times, times[1:]):
        if current - previous != step:
            raise ValueError(f"Persisted candles have a gap after {previous}.")
    return tuple(by_time[moment] for moment in times)
