"""Focused tests for stitching a forward history from persisted snapshots.

All candles are SYNTHETIC; none represent real market data.
"""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from trading_platform_api.research.candles import Candle
from trading_platform_api.research.forward_history import (
    covering_snapshots,
    merge_windows,
)

STEP = timedelta(days=1)
START = datetime(2026, 5, 10, tzinfo=UTC)


def candles(first: int, count: int, close: str = "100") -> tuple[Candle, ...]:
    return tuple(
        Candle(
            START + STEP * (first + i),
            Decimal(1),
            Decimal(2),
            Decimal(1),
            Decimal(close),
            Decimal(1),
        )
        for i in range(count)
    )


def window(first: int, count: int) -> tuple[datetime, int]:
    """(as_of, candle_count) of a snapshot holding candles first..first+count-1."""
    return START + STEP * (first + count), count


def test_greedy_cover_reaches_the_warm_up_start_with_fewest_snapshots() -> None:
    available = [
        window(200, 90),
        window(110, 90),
        window(100, 90),
        window(20, 90),
        window(0, 90),
    ]
    chosen = covering_snapshots(
        available, covered_from=START + STEP * 200, start=START, step=STEP
    )
    # 200..289 is the latest read; 110..199 reaches furthest back while touching
    # it, then 20..109 and 0..89.
    assert chosen == [window(110, 90)[0], window(20, 90)[0], window(0, 90)[0]]
    assert covering_snapshots([], covered_from=START, start=START, step=STEP) == []


def test_cover_fails_closed_on_a_gap() -> None:
    with pytest.raises(ValueError, match="No persisted snapshot covers"):
        covering_snapshots(
            [window(0, 90)], covered_from=START + STEP * 120, start=START, step=STEP
        )


def test_merge_requires_identical_overlaps_and_no_gaps() -> None:
    merged = merge_windows([candles(80, 40), candles(0, 90)], start=START, step=STEP)
    assert len(merged) == 120 and merged[0].open_time == START
    trimmed = merge_windows([candles(0, 120)], start=START + STEP * 10, step=STEP)
    assert trimmed[0].open_time == START + STEP * 10
    with pytest.raises(ValueError, match="disagree"):
        merge_windows([candles(80, 40, "101"), candles(0, 90)], start=START, step=STEP)
    with pytest.raises(ValueError, match="gap"):
        merge_windows([candles(95, 10), candles(0, 90)], start=START, step=STEP)
    with pytest.raises(ValueError, match="warm-up start"):
        merge_windows([candles(1, 90)], start=START, step=STEP)
