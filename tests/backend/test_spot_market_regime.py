"""Versioned Spot-regime threshold behavior stays deterministic and descriptive."""

from decimal import Decimal

import pytest
from trading_platform_api.analysis.spot_market_regime import (
    SpotMarketRegimeError,
    _median,
    _transition_state,
    _trend_state,
    _volatility_state,
)


@pytest.mark.parametrize(
    ("close", "ema20", "ema50", "expected"),
    (
        (Decimal("12"), Decimal("11"), Decimal("10"), "bullish"),
        (Decimal("8"), Decimal("9"), Decimal("10"), "bearish"),
        (Decimal("10"), Decimal("11"), Decimal("9"), "mixed"),
        (Decimal("10"), Decimal("10"), Decimal("10"), "mixed"),
    ),
)
def test_trend_requires_price_and_ema_ordering_to_agree(
    close: Decimal,
    ema20: Decimal,
    ema50: Decimal,
    expected: str,
) -> None:
    assert _trend_state(close, ema20, ema50) == expected


@pytest.mark.parametrize(
    ("current", "baseline", "expected"),
    (
        (Decimal("1.5"), Decimal("1"), "high"),
        (Decimal("0.5"), Decimal("1"), "low"),
        (Decimal("1.49"), Decimal("1"), "typical"),
        (Decimal("0.51"), Decimal("1"), "typical"),
    ),
)
def test_volatility_threshold_boundaries_are_explicit(
    current: Decimal,
    baseline: Decimal,
    expected: str,
) -> None:
    state, _ = _volatility_state(current, baseline)
    assert state == expected


def test_zero_volatility_baseline_is_unavailable_not_low_or_neutral() -> None:
    with pytest.raises(SpotMarketRegimeError, match="baseline is zero"):
        _volatility_state(Decimal("1"), Decimal("0"))


def test_median_is_exact_for_even_and_odd_reference_windows() -> None:
    assert _median((Decimal("1"), Decimal("3"), Decimal("2"))) == Decimal("2")
    assert _median((Decimal("1"), Decimal("3"))) == Decimal("2")


@pytest.mark.parametrize(
    ("current", "recent", "expected"),
    (
        ("bullish", ("bullish",) * 5, "not-observed-in-lookback"),
        ("bullish", ("bullish", "mixed", "bullish"), "possible"),
        ("mixed", ("mixed",) * 5, "possible"),
    ),
)
def test_transition_state_reports_observations_without_claiming_stability(
    current: str,
    recent: tuple[str, ...],
    expected: str,
) -> None:
    assert _transition_state(current, recent) == expected
