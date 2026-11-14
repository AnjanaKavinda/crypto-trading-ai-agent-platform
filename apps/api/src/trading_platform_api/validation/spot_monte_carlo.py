"""Offline moving-block bootstrap over one verified observed Spot equity path."""

from dataclasses import fields
from datetime import UTC, datetime, timedelta
from decimal import (
    ROUND_CEILING,
    ROUND_HALF_EVEN,
    Context,
    Decimal,
    DecimalException,
    localcontext,
)
from uuid import NAMESPACE_URL, uuid5

from trading_platform_api.contracts.serialization import canonical_sha256
from trading_platform_api.validation.contracts import CheckOutcome
from trading_platform_api.validation.contracts_v2 import ValidationArtifactReferenceV2
from trading_platform_api.validation.contracts_v3 import (
    BacktestOutcomeV3,
    BacktestResultV3,
)
from trading_platform_api.validation.monte_carlo_contracts_v2 import (
    ASSUMPTIONS,
    ITERATIONS,
    MAX_RECORDED_SOURCE_INTERVALS,
    WARNINGS,
    MetricDistributionV2,
    MetricQuantileV2,
    MonteCarloOutcomeV2,
    MonteCarloPolicyV2,
    MonteCarloResultV2,
)
from trading_platform_api.validation.spot_backtest import (
    SpotBacktestBundle,
    SpotBacktestOutcome,
    resolve_spot_backtest_result,
)
from trading_platform_api.validation.spot_metrics import (
    METHOD as METRICS_METHOD,
)
from trading_platform_api.validation.spot_metrics import (
    MetricsInputError,
    SpotPerformanceReport,
    calculate_spot_performance_metrics,
)

_ARITHMETIC = Context(prec=50, rounding=ROUND_HALF_EVEN)
_MASK_64 = (1 << 64) - 1
_SPLITMIX_GAMMA = 0x9E3779B97F4A7C15
_MAX_SOURCE_INTERVALS = 2_000
_MAX_GENERATED_RETURNS = 20_000_000
_MIN_SOURCE_INTERVALS = 100
_METRIC_NAMES = (
    ("terminal_compounded_return", "ratio"),
    ("maximum_fractional_drawdown", "ratio"),
    ("longest_negative_bar_streak", "bars"),
)


class SpotMonteCarloInputError(ValueError):
    """The supplied pinned research artifacts cannot be analyzed safely."""


def _report_digest(report: SpotPerformanceReport) -> str:
    return canonical_sha256(
        {
            item.name: getattr(report, item.name)
            for item in fields(report)
            if item.name not in {"report_id", "content_sha256"}
        }
    )


def _report_identity_is_valid(report: SpotPerformanceReport) -> bool:
    digest = _report_digest(report)
    namespace = uuid5(NAMESPACE_URL, f"trading-platform:{METRICS_METHOD}")
    return report.content_sha256 == digest and report.report_id == uuid5(
        namespace, digest
    )


def _source_returns(
    report: SpotPerformanceReport,
) -> tuple[tuple[datetime, Decimal | None], ...]:
    if not report.equity:
        return ()
    return tuple((point.timestamp, point.period_return) for point in report.equity[1:])


def _splitmix64(seed: int):
    state = seed & _MASK_64

    def next_value() -> int:
        nonlocal state
        state = (state + _SPLITMIX_GAMMA) & _MASK_64
        value = state
        value = ((value ^ (value >> 30)) * 0xBF58476D1CE4E5B9) & _MASK_64
        value = ((value ^ (value >> 27)) * 0x94D049BB133111EB) & _MASK_64
        return value ^ (value >> 31)

    return next_value


def _sampled_indices(
    source_count: int, block_length: int, path_horizon: int, seed: int
) -> tuple[int, ...]:
    """Return one deterministic path using non-circular contiguous source blocks."""
    next_value = _splitmix64(seed)
    valid_starts = source_count - block_length + 1
    indexes: list[int] = []
    while len(indexes) < path_horizon:
        start = next_value() % valid_starts
        indexes.extend(range(start, start + block_length))
    return tuple(indexes[:path_horizon])


def _block_policy_valid(source_count: int, block_length: int) -> bool:
    return (
        block_length >= 2
        and block_length <= source_count // 2
        and source_count >= 20 * block_length
    )


def _source_budget_exceeded(source_count: int) -> bool:
    return (
        source_count > _MAX_SOURCE_INTERVALS
        or source_count * ITERATIONS > _MAX_GENERATED_RETURNS
    )


def _path_statistics(returns: tuple[Decimal, ...]) -> tuple[Decimal, Decimal, Decimal]:
    equity = Decimal(1)
    peak = equity
    maximum_drawdown = Decimal(0)
    longest_negative = current_negative = 0
    for value in returns:
        factor = Decimal(1) + value
        if not factor.is_finite() or factor <= 0:
            raise SpotMonteCarloInputError("INVALID_SOURCE_RETURN")
        equity *= factor
        if not equity.is_finite():
            raise SpotMonteCarloInputError("NUMERIC_RANGE_EXCEEDED")
        peak = max(peak, equity)
        maximum_drawdown = max(maximum_drawdown, (peak - equity) / peak)
        current_negative = current_negative + 1 if value < 0 else 0
        longest_negative = max(longest_negative, current_negative)
    return equity - Decimal(1), maximum_drawdown, Decimal(longest_negative)


def _nearest_rank(values: list[Decimal], quantile: Decimal) -> Decimal:
    ordered = sorted(values)
    rank = (len(ordered) * quantile).to_integral_value(rounding=ROUND_CEILING)
    return ordered[max(0, int(rank) - 1)]


def _bootstrap_statistics(
    returns: tuple[Decimal, ...], block_length: int, seed: int
) -> tuple[Decimal, Decimal, Decimal, tuple[tuple[Decimal, ...], ...]]:
    with localcontext(_ARITHMETIC):
        observed = _path_statistics(returns)
        next_value = _splitmix64(seed)
        distributions: list[list[Decimal]] = [[], [], []]
        valid_starts = len(returns) - block_length + 1
        for _ in range(ITERATIONS):
            sampled: list[Decimal] = []
            while len(sampled) < len(returns):
                start = next_value() % valid_starts
                end = min(start + block_length, len(returns))
                sampled.extend(returns[start:end])
            terminal, drawdown, streak = _path_statistics(
                tuple(sampled[: len(returns)])
            )
            for values, value in zip(
                distributions, (terminal, drawdown, streak), strict=True
            ):
                values.append(value)
        quantiles = tuple(
            tuple(
                _nearest_rank(values, quantile)
                for quantile in (
                    Decimal("0.025"),
                    Decimal("0.5"),
                    Decimal("0.975"),
                )
            )
            for values in distributions
        )
        return (*observed, quantiles)


def _result_values(
    bundle: SpotBacktestBundle,
    result: BacktestResultV3,
    report: SpotPerformanceReport,
    *,
    block_length: int,
    seed: int,
    returns: tuple[tuple[datetime, Decimal | None], ...],
    outcome: MonteCarloOutcomeV2,
    metrics: tuple[MetricDistributionV2, ...] = (),
    reasons: tuple[str, ...] = (),
    as_of: datetime,
    created_at: datetime,
) -> MonteCarloResultV2:
    policy = MonteCarloPolicyV2(result.timeframe, block_length, len(returns))
    trace = result.trace
    return MonteCarloResultV2.build(
        outcome=outcome,
        backtest=ValidationArtifactReferenceV2(
            "C-027", result.result_id, "3", result.content_sha256
        ),
        trace=trace,
        strategy_version=result.strategy_version,
        cost_assumptions=result.cost_assumptions,
        dataset_id=result.dataset.dataset_id,
        dataset_version=result.dataset.version,
        dataset_sha256=result.dataset_sha256,
        dataset_lineage_sha256=result.dataset.lineage_sha256,
        manifest_sha256=result.manifest_sha256,
        metrics_report_id=report.report_id,
        metrics_report_sha256=report.content_sha256,
        metrics_method=report.method,
        metrics_policy_sha256=canonical_sha256(report.policy),
        metrics_input_sha256=report.input_sha256,
        source_returns_sha256=canonical_sha256(returns),
        instrument_id=result.instrument_id,
        venue=result.venue,
        timeframe=result.timeframe,
        policy=policy,
        seed=seed,
        source_return_count=len(returns),
        metrics=metrics,
        assumptions=ASSUMPTIONS,
        warnings=WARNINGS if outcome is MonteCarloOutcomeV2.OBSERVED else (),
        reasons=reasons,
        source_as_of=result.as_of,
        source_created_at=result.created_at,
        source_expires_at=result.expires_at,
        metrics_report_timestamp=report.policy.report_timestamp,
        as_of=as_of,
        created_at=created_at,
    )


def _verified_metrics_report(
    bundle: SpotBacktestBundle, report: SpotPerformanceReport
) -> bool:
    if not _report_identity_is_valid(report) or report.method != METRICS_METHOD:
        return False
    try:
        verified = calculate_spot_performance_metrics(
            bundle,
            report.policy,
            price_path=bundle.execution_dataset if report.equity else None,
        )
    except (
        MetricsInputError,
        ValueError,
        TypeError,
        KeyError,
        AttributeError,
        DecimalException,
    ):
        return False
    return verified == report


def run_spot_monte_carlo(
    bundle: SpotBacktestBundle,
    report: SpotPerformanceReport,
    *,
    block_length: int,
    seed: int,
    as_of: datetime,
    created_at: datetime,
) -> MonteCarloResultV2:
    """Analyze the exact C-027v3/#94 Spot path; never accepts return arrays."""
    if (
        type(bundle) is not SpotBacktestBundle
        or type(report) is not SpotPerformanceReport
        or type(bundle.result) is not BacktestResultV3
    ):
        raise SpotMonteCarloInputError("EXACT_SPOT_BACKTEST_AND_METRICS_REQUIRED")
    if (
        type(seed) is not int
        or not -(2**63) <= seed < 2**63
        or type(block_length) is not int
        or not 0 <= block_length <= MAX_RECORDED_SOURCE_INTERVALS
        or type(as_of) is not datetime
        or as_of.tzinfo is None
        or as_of.utcoffset() is None
        or type(created_at) is not datetime
        or created_at.tzinfo is None
        or created_at.utcoffset() is None
        or created_at < as_of
    ):
        raise SpotMonteCarloInputError("INVALID_CALLER_POLICY_OR_TIME")
    result = bundle.result
    source_returns = _source_returns(report)
    try:
        resolve_spot_backtest_result(bundle)
    except (ValueError, TypeError, KeyError, AttributeError):
        return _result_values(
            bundle,
            result,
            report,
            block_length=block_length,
            seed=seed,
            returns=source_returns,
            outcome=MonteCarloOutcomeV2.FAILED,
            reasons=("BACKTEST_PROVENANCE_MISMATCH",),
            as_of=as_of,
            created_at=created_at,
        )
    trace = bundle.trace
    if trace is None:
        return _result_values(
            bundle,
            result,
            report,
            block_length=block_length,
            seed=seed,
            returns=source_returns,
            outcome=MonteCarloOutcomeV2.FAILED,
            reasons=("BACKTEST_TRACE_MISSING",),
            as_of=as_of,
            created_at=created_at,
        )
    if (
        bundle.outcome is not SpotBacktestOutcome.OBSERVED
        or result.outcome is not BacktestOutcomeV3.OBSERVED
        or result.market_type != "SPOT"
        or result.data_integrity is not CheckOutcome.PASSED
        or result.point_in_time_correct is not CheckOutcome.PASSED
        or result.operating_mode.value != "BACKTEST"
        or result.environment.value not in {"DEV", "TEST"}
        or result.trace.content_sha256 != trace.content_sha256
    ):
        return _result_values(
            bundle,
            result,
            report,
            block_length=block_length,
            seed=seed,
            returns=source_returns,
            outcome=MonteCarloOutcomeV2.FAILED,
            reasons=("UNSUPPORTED_OR_UNOBSERVED_BACKTEST",),
            as_of=as_of,
            created_at=created_at,
        )
    if (
        report.result_id != result.result_id
        or report.result_schema != result.schema_version
        or report.result_sha256 != result.content_sha256
        or report.trace_sha256 != trace.content_sha256
        or report.dataset_sha256 != result.dataset_sha256
        or report.manifest_sha256 != result.manifest_sha256
        or report.cost_sha256 != result.cost_assumptions.content_sha256
        or report.strategy_sha256 != result.strategy_version.content_sha256
        or not _verified_metrics_report(bundle, report)
    ):
        return _result_values(
            bundle,
            result,
            report,
            block_length=block_length,
            seed=seed,
            returns=source_returns,
            outcome=MonteCarloOutcomeV2.FAILED,
            reasons=("METRICS_REPORT_PROVENANCE_MISMATCH",),
            as_of=as_of,
            created_at=created_at,
        )
    if _source_budget_exceeded(len(source_returns)):
        return _result_values(
            bundle,
            result,
            report,
            block_length=block_length,
            seed=seed,
            returns=source_returns,
            outcome=MonteCarloOutcomeV2.INCONCLUSIVE,
            reasons=("SOURCE_INTERVAL_BUDGET_EXCEEDED",),
            as_of=as_of,
            created_at=created_at,
        )
    now = as_of.astimezone(UTC)
    created = created_at.astimezone(UTC)
    if (
        report.policy.report_timestamp > now
        or result.expires_at <= now
        or report.policy.report_timestamp < result.created_at
        or now > created
    ):
        return _result_values(
            bundle,
            result,
            report,
            block_length=block_length,
            seed=seed,
            returns=source_returns,
            outcome=MonteCarloOutcomeV2.FAILED,
            reasons=("STALE_EXPIRED_OR_NON_POINT_IN_TIME_INPUT",),
            as_of=as_of,
            created_at=created_at,
        )
    count = len(source_returns)
    if (
        not source_returns
        or any(value is None for _, value in source_returns)
        or any(
            second[0] - first[0] != timedelta(seconds=report.policy.interval_seconds)
            for first, second in zip(source_returns, source_returns[1:])
        )
    ):
        return _result_values(
            bundle,
            result,
            report,
            block_length=block_length,
            seed=seed,
            returns=source_returns,
            outcome=MonteCarloOutcomeV2.INCONCLUSIVE,
            reasons=("MISSING_OR_IRREGULAR_SOURCE_RETURNS",),
            as_of=as_of,
            created_at=created_at,
        )
    complete_returns = tuple(value for _, value in source_returns if value is not None)
    if (
        count < _MIN_SOURCE_INTERVALS
        or count < report.policy.min_return_sample
        or not report.trades
        or not result.simulated_trade_ids
    ):
        return _result_values(
            bundle,
            result,
            report,
            block_length=block_length,
            seed=seed,
            returns=source_returns,
            outcome=MonteCarloOutcomeV2.INCONCLUSIVE,
            reasons=("INSUFFICIENT_OBSERVED_RETURN_OR_TRADE_SAMPLE",),
            as_of=as_of,
            created_at=created_at,
        )
    if not _block_policy_valid(count, block_length):
        return _result_values(
            bundle,
            result,
            report,
            block_length=block_length,
            seed=seed,
            returns=source_returns,
            outcome=MonteCarloOutcomeV2.FAILED,
            reasons=("INVALID_OR_INSUFFICIENT_BLOCK_POLICY",),
            as_of=as_of,
            created_at=created_at,
        )
    if _source_budget_exceeded(count):
        return _result_values(
            bundle,
            result,
            report,
            block_length=block_length,
            seed=seed,
            returns=source_returns,
            outcome=MonteCarloOutcomeV2.INCONCLUSIVE,
            reasons=("GENERATED_RETURN_BUDGET_EXCEEDED",),
            as_of=as_of,
            created_at=created_at,
        )
    report_metrics = {metric.name: metric for metric in report.metrics}
    if any(
        name not in report_metrics
        or report_metrics[name].state.value != "AVAILABLE"
        or report_metrics[name].sample_count < minimum
        or "INSUFFICIENT_SAMPLE" in report_metrics[name].warnings
        for name, minimum in (
            ("cumulative_return", report.policy.min_return_sample),
            ("maximum_fractional_drawdown", report.policy.min_return_sample),
            ("total_trades", report.policy.min_trade_sample),
        )
    ):
        return _result_values(
            bundle,
            result,
            report,
            block_length=block_length,
            seed=seed,
            returns=source_returns,
            outcome=MonteCarloOutcomeV2.INCONCLUSIVE,
            reasons=("METRICS_SAMPLE_SUFFICIENCY_NOT_MET",),
            as_of=as_of,
            created_at=created_at,
        )
    try:
        *observed, quantiles = _bootstrap_statistics(
            complete_returns, block_length, seed
        )
        metrics = tuple(
            MetricDistributionV2(
                name,
                unit,
                observed[index],
                tuple(
                    MetricQuantileV2(quantile, quantiles[index][quantile_index])
                    for quantile_index, quantile in enumerate(
                        (Decimal("0.025"), Decimal("0.5"), Decimal("0.975"))
                    )
                ),
            )
            for index, (name, unit) in enumerate(_METRIC_NAMES)
        )
    except (DecimalException, SpotMonteCarloInputError, OverflowError):
        return _result_values(
            bundle,
            result,
            report,
            block_length=block_length,
            seed=seed,
            returns=source_returns,
            outcome=MonteCarloOutcomeV2.FAILED,
            reasons=("DETERMINISTIC_NUMERIC_CALCULATION_FAILED",),
            as_of=as_of,
            created_at=created_at,
        )
    return _result_values(
        bundle,
        result,
        report,
        block_length=block_length,
        seed=seed,
        returns=source_returns,
        outcome=MonteCarloOutcomeV2.OBSERVED,
        metrics=metrics,
        as_of=as_of,
        created_at=created_at,
    )


__all__ = ["SpotMonteCarloInputError", "run_spot_monte_carlo"]
