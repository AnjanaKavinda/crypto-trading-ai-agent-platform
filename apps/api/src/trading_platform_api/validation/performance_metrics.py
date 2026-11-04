"""Deterministic observed performance metrics for Chat 7 research."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum


class PerformanceMetricError(ValueError):
    """Metric input is invalid or cannot be interpreted deterministically."""


class MetricAvailability(StrEnum):
    AVAILABLE = "AVAILABLE"
    UNAVAILABLE = "UNAVAILABLE"


class PerformanceSampleState(StrEnum):
    OBSERVED = "OBSERVED"
    INSUFFICIENT_SAMPLE = "INSUFFICIENT_SAMPLE"


@dataclass(frozen=True, slots=True)
class TradePerformanceObservation:
    pnl: Decimal
    mae: Decimal
    mfe: Decimal

    def __post_init__(self) -> None:
        for name in ("pnl", "mae", "mfe"):
            value = getattr(self, name)
            if not isinstance(value, Decimal) or not value.is_finite():
                raise PerformanceMetricError(f"{name} must be a finite Decimal.")
        if self.mae < 0 or self.mfe < 0:
            raise PerformanceMetricError("MAE/MFE are positive excursion magnitudes.")


@dataclass(frozen=True, slots=True)
class PerformanceMetric:
    name: str
    availability: MetricAvailability
    value: Decimal | None
    unit: str
    reason: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name.strip():
            raise PerformanceMetricError("metric name must be non-blank.")
        if not isinstance(self.availability, MetricAvailability):
            raise PerformanceMetricError("metric availability is invalid.")
        if not isinstance(self.unit, str) or not self.unit.strip():
            raise PerformanceMetricError("metric unit must be non-blank.")
        if self.availability is MetricAvailability.AVAILABLE:
            if (
                not isinstance(self.value, Decimal)
                or not self.value.is_finite()
                or self.reason is not None
            ):
                raise PerformanceMetricError(
                    "available metric requires finite value and no reason."
                )
        elif self.value is not None or not self.reason:
            raise PerformanceMetricError(
                "unavailable metric requires no value and a reason."
            )


@dataclass(frozen=True, slots=True)
class PerformanceMetricsReport:
    metrics: tuple[PerformanceMetric, ...]
    sample_state: PerformanceSampleState
    sample_size: int
    minimum_sample_size: int
    periods_per_year: Decimal
    return_period: str
    quote_unit: str

    def __post_init__(self) -> None:
        if (
            not self.metrics
            or len({item.name for item in self.metrics}) != len(self.metrics)
            or any(type(item) is not PerformanceMetric for item in self.metrics)
        ):
            raise PerformanceMetricError("metrics must be non-empty and unique.")
        if (
            type(self.sample_size) is not int
            or type(self.minimum_sample_size) is not int
            or self.sample_size < 0
            or self.minimum_sample_size < 1
        ):
            raise PerformanceMetricError("sample sizes are invalid.")
        if not isinstance(self.sample_state, PerformanceSampleState):
            raise PerformanceMetricError("sample_state is invalid.")
        if (
            not isinstance(self.periods_per_year, Decimal)
            or not self.periods_per_year.is_finite()
            or self.periods_per_year <= 0
        ):
            raise PerformanceMetricError("periods_per_year must be positive.")
        if not isinstance(self.return_period, str) or not self.return_period.strip():
            raise PerformanceMetricError("return_period must be explicit.")
        if not isinstance(self.quote_unit, str) or not self.quote_unit.strip():
            raise PerformanceMetricError("quote_unit must be explicit.")

    def by_name(self, name: str) -> PerformanceMetric:
        for metric in self.metrics:
            if metric.name == name:
                return metric
        raise KeyError(name)


def calculate_performance_metrics(
    *,
    trades: tuple[TradePerformanceObservation, ...],
    period_returns: tuple[Decimal, ...],
    initial_equity: Decimal,
    periods_per_year: Decimal,
    return_period: str,
    quote_unit: str,
    minimum_sample_size: int = 30,
) -> PerformanceMetricsReport:
    if (
        type(trades) is not tuple
        or any(type(item) is not TradePerformanceObservation for item in trades)
    ):
        raise PerformanceMetricError("trades must be an exact immutable tuple.")
    if type(period_returns) is not tuple or any(
        not isinstance(item, Decimal) or not item.is_finite()
        for item in period_returns
    ):
        raise PerformanceMetricError(
            "period_returns must be an immutable tuple of finite Decimals."
        )
    if (
        not isinstance(initial_equity, Decimal)
        or not initial_equity.is_finite()
        or initial_equity <= 0
    ):
        raise PerformanceMetricError("initial_equity must be positive.")
    if (
        not isinstance(periods_per_year, Decimal)
        or not periods_per_year.is_finite()
        or periods_per_year <= 0
    ):
        raise PerformanceMetricError("periods_per_year must be positive.")
    if type(minimum_sample_size) is not int or minimum_sample_size < 1:
        raise PerformanceMetricError("minimum_sample_size must be positive.")
    if not isinstance(return_period, str) or not return_period.strip():
        raise PerformanceMetricError("return_period must be explicit.")
    if not isinstance(quote_unit, str) or not quote_unit.strip():
        raise PerformanceMetricError("quote_unit must be explicit.")

    count = len(trades)
    wins = tuple(item for item in trades if item.pnl > 0)
    losses = tuple(item for item in trades if item.pnl < 0)
    flats = count - len(wins) - len(losses)
    gross_profit = sum((item.pnl for item in wins), Decimal("0"))
    gross_loss = sum((-item.pnl for item in losses), Decimal("0"))
    net_profit = sum((item.pnl for item in trades), Decimal("0"))
    returns = period_returns
    max_drawdown, max_drawdown_fraction = _drawdown(
        trades=trades, initial_equity=initial_equity
    )

    metrics: list[PerformanceMetric] = [
        _available("total_trades", Decimal(count), "count"),
        _available("winning_trades", Decimal(len(wins)), "count"),
        _available("losing_trades", Decimal(len(losses)), "count"),
        _available("flat_trades", Decimal(flats), "count"),
        _ratio_metric("win_rate", Decimal(len(wins)), Decimal(count)),
        _ratio_metric("loss_rate", Decimal(len(losses)), Decimal(count)),
        _mean_metric("average_win", tuple(item.pnl for item in wins), quote_unit),
        _mean_metric(
            "average_loss", tuple(-item.pnl for item in losses), quote_unit
        ),
        _extreme_metric("largest_win", tuple(item.pnl for item in wins), max, quote_unit),
        _extreme_metric(
            "largest_loss",
            tuple(-item.pnl for item in losses),
            max,
            quote_unit,
        ),
        _available("gross_profit", gross_profit, quote_unit),
        _available("gross_loss", gross_loss, quote_unit),
        _available("net_profit", net_profit, quote_unit),
        (
            _available("profit_factor", gross_profit / gross_loss, "ratio")
            if gross_loss > 0
            else _unavailable("profit_factor", "ratio", "ZERO_GROSS_LOSS")
        ),
        (
            _available("expectancy", net_profit / Decimal(count), f"{quote_unit}/trade")
            if count
            else _unavailable("expectancy", f"{quote_unit}/trade", "NO_TRADES")
        ),
        _mean_metric("average_mae", tuple(item.mae for item in trades), quote_unit),
        _mean_metric("average_mfe", tuple(item.mfe for item in trades), quote_unit),
        _available("maximum_drawdown", max_drawdown, quote_unit),
        _available("maximum_drawdown_fraction", max_drawdown_fraction, "fraction"),
        (
            _available("recovery_factor", net_profit / max_drawdown, "ratio")
            if max_drawdown > 0
            else _unavailable("recovery_factor", "ratio", "ZERO_DRAWDOWN")
        ),
        _risk_adjusted_metric(
            "sharpe_ratio",
            returns,
            periods_per_year=periods_per_year,
            downside_only=False,
        ),
        _risk_adjusted_metric(
            "sortino_ratio",
            returns,
            periods_per_year=periods_per_year,
            downside_only=True,
        ),
    ]

    return PerformanceMetricsReport(
        metrics=tuple(metrics),
        sample_state=(
            PerformanceSampleState.OBSERVED
            if count >= minimum_sample_size
            else PerformanceSampleState.INSUFFICIENT_SAMPLE
        ),
        sample_size=count,
        minimum_sample_size=minimum_sample_size,
        periods_per_year=periods_per_year,
        return_period=return_period,
        quote_unit=quote_unit,
    )


def _available(name: str, value: Decimal, unit: str) -> PerformanceMetric:
    return PerformanceMetric(name, MetricAvailability.AVAILABLE, value, unit)


def _unavailable(name: str, unit: str, reason: str) -> PerformanceMetric:
    return PerformanceMetric(
        name,
        MetricAvailability.UNAVAILABLE,
        None,
        unit,
        reason,
    )


def _ratio_metric(name: str, numerator: Decimal, denominator: Decimal) -> PerformanceMetric:
    if denominator == 0:
        return _unavailable(name, "fraction", "ZERO_DENOMINATOR")
    return _available(name, numerator / denominator, "fraction")


def _mean_metric(
    name: str, values: tuple[Decimal, ...], unit: str
) -> PerformanceMetric:
    if not values:
        return _unavailable(name, unit, "EMPTY_SAMPLE")
    return _available(name, sum(values, Decimal("0")) / Decimal(len(values)), unit)


def _extreme_metric(
    name: str,
    values: tuple[Decimal, ...],
    operation,
    unit: str,
) -> PerformanceMetric:
    if not values:
        return _unavailable(name, unit, "EMPTY_SAMPLE")
    return _available(name, operation(values), unit)


def _drawdown(
    *,
    trades: tuple[TradePerformanceObservation, ...],
    initial_equity: Decimal,
) -> tuple[Decimal, Decimal]:
    equity = initial_equity
    peak = initial_equity
    max_amount = Decimal("0")
    max_fraction = Decimal("0")
    for trade in trades:
        equity += trade.pnl
        if equity > peak:
            peak = equity
        amount = peak - equity
        fraction = amount / peak if peak > 0 else Decimal("0")
        if amount > max_amount:
            max_amount = amount
        if fraction > max_fraction:
            max_fraction = fraction
    return max_amount, max_fraction


def _sample_standard_deviation(values: tuple[Decimal, ...]) -> Decimal | None:
    if len(values) < 2:
        return None
    mean = sum(values, Decimal("0")) / Decimal(len(values))
    variance = sum(
        ((item - mean) * (item - mean) for item in values),
        Decimal("0"),
    ) / Decimal(len(values) - 1)
    return variance.sqrt()


def _risk_adjusted_metric(
    name: str,
    returns: tuple[Decimal, ...],
    *,
    periods_per_year: Decimal,
    downside_only: bool,
) -> PerformanceMetric:
    if len(returns) < 2:
        return _unavailable(name, "ratio", "INSUFFICIENT_RETURNS")
    mean = sum(returns, Decimal("0")) / Decimal(len(returns))
    if downside_only:
        downside = tuple(item for item in returns if item < 0)
        if not downside:
            return _unavailable(name, "ratio", "NO_DOWNSIDE_RETURNS")
        denominator = (
            sum((item * item for item in downside), Decimal("0"))
            / Decimal(len(returns))
        ).sqrt()
    else:
        deviation = _sample_standard_deviation(returns)
        if deviation is None:
            return _unavailable(name, "ratio", "INSUFFICIENT_RETURNS")
        denominator = deviation
    if denominator == 0:
        return _unavailable(name, "ratio", "ZERO_RETURN_VARIANCE")
    return _available(
        name,
        mean / denominator * periods_per_year.sqrt(),
        "ratio",
    )


__all__ = [
    "MetricAvailability",
    "PerformanceMetric",
    "PerformanceMetricError",
    "PerformanceMetricsReport",
    "PerformanceSampleState",
    "TradePerformanceObservation",
    "calculate_performance_metrics",
]
