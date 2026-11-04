from __future__ import annotations

from decimal import Decimal

import pytest
from trading_platform_api.validation.performance_metrics import (
    MetricAvailability,
    PerformanceMetricError,
    PerformanceSampleState,
    TradePerformanceObservation,
    calculate_performance_metrics,
)


def trade(
    pnl: str,
    return_fraction: str,
    *,
    mae: str = "1",
    mfe: str = "2",
) -> TradePerformanceObservation:
    return TradePerformanceObservation(
        Decimal(pnl),
        Decimal(return_fraction),
        Decimal(mae),
        Decimal(mfe),
    )


def test_observed_metrics_use_deterministic_formulas() -> None:
    report = calculate_performance_metrics(
        trades=(
            trade("10", "0.01"),
            trade("-5", "-0.005"),
            trade("20", "0.02"),
            trade("-10", "-0.01"),
        ),
        initial_equity=Decimal("1000"),
        periods_per_year=Decimal("365"),
        return_period="trade",
        minimum_sample_size=4,
    )
    assert report.sample_state is PerformanceSampleState.OBSERVED
    assert report.by_name("total_trades").value == Decimal("4")
    assert report.by_name("win_rate").value == Decimal("0.5")
    assert report.by_name("gross_profit").value == Decimal("30")
    assert report.by_name("gross_loss").value == Decimal("15")
    assert report.by_name("net_profit").value == Decimal("15")
    assert report.by_name("profit_factor").value == Decimal("2")
    assert report.by_name("expectancy").value == Decimal("3.75")
    assert report.by_name("largest_win").value == Decimal("20")
    assert report.by_name("largest_loss").value == Decimal("10")
    assert report.by_name("maximum_drawdown").value == Decimal("10")
    assert report.by_name("recovery_factor").value == Decimal("1.5")
    assert report.by_name("sharpe_ratio").availability is MetricAvailability.AVAILABLE
    assert report.by_name("sortino_ratio").availability is MetricAvailability.AVAILABLE


def test_empty_and_one_sided_samples_are_explicitly_unavailable() -> None:
    empty = calculate_performance_metrics(
        trades=(),
        initial_equity=Decimal("100"),
        periods_per_year=Decimal("365"),
        return_period="trade",
    )
    assert empty.sample_state is PerformanceSampleState.INSUFFICIENT_SAMPLE
    assert empty.by_name("win_rate").reason == "ZERO_DENOMINATOR"
    assert empty.by_name("expectancy").reason == "NO_TRADES"
    assert empty.by_name("profit_factor").reason == "ZERO_GROSS_LOSS"
    assert empty.by_name("sharpe_ratio").reason == "INSUFFICIENT_RETURNS"

    wins = calculate_performance_metrics(
        trades=(trade("1", "0.01"), trade("2", "0.02")),
        initial_equity=Decimal("100"),
        periods_per_year=Decimal("365"),
        return_period="trade",
    )
    assert wins.by_name("profit_factor").reason == "ZERO_GROSS_LOSS"
    assert wins.by_name("sortino_ratio").reason == "NO_DOWNSIDE_RETURNS"


def test_zero_return_variance_is_not_infinite_sharpe() -> None:
    report = calculate_performance_metrics(
        trades=(
            trade("1", "0.01"),
            trade("1", "0.01"),
            trade("1", "0.01"),
        ),
        initial_equity=Decimal("100"),
        periods_per_year=Decimal("365"),
        return_period="trade",
    )
    sharpe = report.by_name("sharpe_ratio")
    assert sharpe.availability is MetricAvailability.UNAVAILABLE
    assert sharpe.reason == "ZERO_RETURN_VARIANCE"


def test_drawdown_tracks_peak_to_trough_not_total_loss_only() -> None:
    report = calculate_performance_metrics(
        trades=(
            trade("100", "0.10"),
            trade("-50", "-0.045"),
            trade("-60", "-0.057"),
            trade("20", "0.02"),
        ),
        initial_equity=Decimal("1000"),
        periods_per_year=Decimal("365"),
        return_period="trade",
    )
    assert report.by_name("maximum_drawdown").value == Decimal("110")
    assert report.by_name("maximum_drawdown_fraction").value == Decimal("0.1")


def test_small_sample_remains_observed_data_but_is_marked_insufficient() -> None:
    report = calculate_performance_metrics(
        trades=(trade("1", "0.01"),) * 5,
        initial_equity=Decimal("100"),
        periods_per_year=Decimal("365"),
        return_period="trade",
        minimum_sample_size=30,
    )
    assert report.sample_size == 5
    assert report.sample_state is PerformanceSampleState.INSUFFICIENT_SAMPLE


@pytest.mark.parametrize(
    "kwargs",
    [
        {"initial_equity": Decimal("0")},
        {"periods_per_year": Decimal("0")},
        {"return_period": ""},
        {"minimum_sample_size": 0},
    ],
)
def test_invalid_metric_configuration_fails_closed(kwargs) -> None:
    values = {
        "trades": (trade("1", "0.01"),),
        "initial_equity": Decimal("100"),
        "periods_per_year": Decimal("365"),
        "return_period": "trade",
        "minimum_sample_size": 30,
    }
    values.update(kwargs)
    with pytest.raises(PerformanceMetricError):
        calculate_performance_metrics(**values)
