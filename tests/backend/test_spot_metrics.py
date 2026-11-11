"""Hand-calculated metrics and evidence-boundary regressions."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal, localcontext
from uuid import UUID, uuid4

import pytest
from trading_platform_api.validation.contracts_v2 import ValidationArtifactReferenceV2
from trading_platform_api.validation.spot_metrics import (
    _CONTEXT,
    METHOD,
    EquityPoint,
    InitialRisk,
    MetricsInputError,
    MetricsPolicy,
    MetricState,
    TradeObservation,
    _buckets,
    _equity_statistics,
    _trade_metrics,
    calculate_spot_performance_metrics,
)

D = Decimal
NOW = datetime(2026, 1, 1, tzinfo=UTC)


def policy(**changes):
    return replace(
        MetricsPolicy(
            METHOD, "1", "USDT", "BAR_CLOSE", 60, D(12), D(0), D(0), 10, 2, NOW
        ),
        **changes,
    )


def observations(profits, risks=None):
    return tuple(
        TradeObservation(
            UUID(int=i + 1),
            NOW + timedelta(minutes=i),
            D(p),
            D(p) / 100,
            D(p) / D(risks[i]) if risks else None,
            None,
            None,
            "PRICE_PATH_NOT_PROVIDED",
        )
        for i, p in enumerate(profits)
    )


def trade_metrics(profits, risks=None):
    with localcontext(_CONTEXT):
        return {
            m.name: m for m in _trade_metrics(observations(profits, risks), policy())
        }


def value(metrics, name):
    assert metrics[name].state is MetricState.AVAILABLE
    return metrics[name].metric.value


def curve(equities):
    high = D(equities[0])
    result = []
    for i, e in enumerate(equities):
        e = D(e)
        high = max(high, e)
        result.append(
            EquityPoint(
                NOW + timedelta(minutes=i),
                e,
                D(0),
                e,
                None,
                high - e,
                (high - e) / high,
            )
        )
    return tuple(result)


def equity_metrics(equities, **changes):
    with localcontext(_CONTEXT):
        metrics, episodes = _equity_statistics(curve(equities), policy(**changes))
    return {m.name: m for m in metrics}, episodes


def test_cost_inclusive_hand_calculated_closed_trades():
    metrics = trade_metrics([30, -10, 0])
    assert value(metrics, "total_trades") == 3
    for name in ("winning_trades", "losing_trades", "breakeven_trades"):
        assert value(metrics, name) == 1
    assert value(metrics, "profit_factor") == 3
    assert value(metrics, "net_realized_profit") == 20
    assert value(metrics, "gross_profit") == 30
    assert value(metrics, "gross_loss") == 10
    with localcontext(_CONTEXT):
        assert value(metrics, "expectancy") == D(20) / 3
        assert value(metrics, "win_rate") == D(1) / 3
    assert metrics["expectancy"].warnings == ("INSUFFICIENT_SAMPLE",)
    assert metrics["average_r"].reason == "INITIAL_RISK_NOT_PROVIDED_FOR_FULL_SAMPLE"


@pytest.mark.parametrize(
    "profits,pf_reason,rate",
    [
        ([10, 20], "NO_LOSSES", 1),
        ([-5, -10], None, 0),
        ([0, 0], "NO_LOSSES", 0),
        ([], "NO_LOSSES", None),
    ],
)
def test_empty_and_one_sided_trade_samples(profits, pf_reason, rate):
    metrics = trade_metrics(profits)
    if pf_reason:
        assert metrics["profit_factor"].state is MetricState.UNDEFINED
        assert metrics["profit_factor"].reason == pf_reason
    else:
        assert value(metrics, "profit_factor") == 0
    if rate is None:
        assert metrics["win_rate"].reason == "NO_CLOSED_TRADES"
        assert value(metrics, "net_realized_profit") == 0
    else:
        assert value(metrics, "win_rate") == rate


def test_r_distributions_streaks_and_calendar_buckets():
    obs = observations([30, 10, 0, -10, -5], [10, 10, 10, 10, 10])
    with localcontext(_CONTEXT):
        metrics = {m.name: m for m in _trade_metrics(obs, policy())}
    assert value(metrics, "average_r") == D("0.5")
    assert value(metrics, "median_r") == 0
    assert value(metrics, "cumulative_r") == D("2.5")
    assert value(metrics, "maximum_consecutive_wins") == 2
    assert value(metrics, "maximum_consecutive_losses") == 2
    buckets = _buckets(obs)
    assert len(buckets) == 3
    assert all(b.trade_count == 5 and b.profit == 25 for b in buckets)
    assert next(b.start for b in buckets if b.frequency == "WEEK").weekday() == 0


def test_known_drawdown_with_censored_episode():
    metrics, episodes = equity_metrics([100, 120, 90, 108])
    assert value(metrics, "maximum_absolute_drawdown") == 30
    assert value(metrics, "maximum_fractional_drawdown") == D("0.25")
    assert value(metrics, "average_absolute_drawdown") == 14
    with localcontext(_CONTEXT):
        assert value(metrics, "recovery_factor") == D(8) / 30
    assert len(episodes) == 1
    assert episodes[0].censored
    assert episodes[0].underwater_seconds == 120
    assert episodes[0].recovery_seconds == 60
    assert metrics["maximum_recovery_seconds"].reason == "NO_RECOVERED_EPISODE"


def test_recovered_drawdown_and_sample_variance():
    metrics, episodes = equity_metrics([100, 120, 90, 108, 120])
    assert episodes[0].recovered_at == NOW + timedelta(minutes=4)
    assert not episodes[0].censored
    assert value(metrics, "maximum_recovery_seconds") == 120
    with localcontext(_CONTEXT):
        returns = (D("0.2"), D("-0.25"), D("0.2"), D(120) / 108 - 1)
        mean = sum(returns) / 4
        std = (sum((r - mean) ** 2 for r in returns) / 3).sqrt()
        assert value(metrics, "volatility") == std * D(12).sqrt()
        assert value(metrics, "sharpe") == mean / std * D(12).sqrt()
        downside = (D("0.25") ** 2 / 4).sqrt()
        assert value(metrics, "sortino") == mean / downside * D(12).sqrt()


@pytest.mark.parametrize("path", [[100, 100, 100], [100, 110, 121]])
def test_constant_returns_and_no_downside_are_undefined(path):
    metrics, _ = equity_metrics(path)
    assert metrics["sharpe"].reason == "ZERO_VARIANCE"
    assert metrics["sortino"].reason == "NO_DOWNSIDE_DEVIATION"
    assert metrics["calmar"].reason == "ZERO_DRAWDOWN"


def test_annualization_risk_free_and_minimum_samples():
    metrics, _ = equity_metrics(
        [100, 120, 90, 108], periods_per_year=D(3), risk_free_return=D("0.01")
    )
    assert value(metrics, "cagr") == D("0.08")
    assert value(metrics, "calmar") == D("0.32")
    metrics, _ = equity_metrics([100, 120], min_return_sample=2)
    assert metrics["sharpe"].reason == "INSUFFICIENT_RETURN_SAMPLE"


def test_invalid_equity_or_grid():
    with pytest.raises(MetricsInputError, match="NONPOSITIVE"):
        _equity_statistics(curve([100, 0]), policy())
    points = curve([100, 110, 100])
    with pytest.raises(MetricsInputError, match="IRREGULAR_GRID"):
        _equity_statistics(
            (
                points[0],
                replace(points[1], timestamp=NOW + timedelta(seconds=1)),
                points[2],
            ),
            policy(),
        )


@pytest.mark.parametrize(
    "changes",
    [
        {"periods_per_year": D("NaN")},
        {"risk_free_return": D("Infinity")},
        {"periods_per_year": D("1e100")},
        {"method": "unknown"},
        {"min_trade_sample": 0},
        {"interval_seconds": True},
        {"quote_unit": " USDT"},
        {"report_timestamp": NOW.replace(tzinfo=None)},
    ],
)
def test_policy_rejects_invalid_inputs(changes):
    with pytest.raises(MetricsInputError):
        policy(**changes)


def test_risk_requires_positive_amount_and_exact_reference():
    reference = ValidationArtifactReferenceV2("C-034", uuid4(), "1", "a" * 64)
    InitialRisk(uuid4(), D(1), "USDT", "declared-risk-v1", reference)
    with pytest.raises(MetricsInputError):
        InitialRisk(uuid4(), D(0), "USDT", "declared-risk-v1", reference)
    with pytest.raises(MetricsInputError):
        InitialRisk(uuid4(), D(1), "USDT", "declared-risk-v1", None)


def test_public_function_rejects_unresolved_bundle():
    with pytest.raises(MetricsInputError):
        calculate_spot_performance_metrics(object(), policy())


def test_verified_price_path_marks_inventory_and_does_not_double_charge_costs():
    from types import SimpleNamespace

    from test_spot_execution import fixture, run
    from trading_platform_api.validation.spot_metrics import (
        _equity_path,
        _verified_fills,
    )

    case = fixture()
    simulation = run(case).trace
    assert simulation is not None
    trace = SimpleNamespace(
        policy=case["policy"], entry_trace=simulation, exit_trace=None, trades=()
    )
    with localcontext(_CONTEXT):
        fills = _verified_fills(trace)
        points = _equity_path(case["data"], trace, fills, policy())
    assert points[0].equity == 1000
    assert points[-1].cash == simulation.final_cash
    assert points[-1].inventory == simulation.final_inventory == 1
    assert points[-1].equity == simulation.final_cash + 100
    assert points[-1].equity == D("999.86")
    assert sum(p.period_return is not None for p in points) == 8


def test_path_requires_full_grid_exact_units_and_initial_inventory_valuation():
    from types import SimpleNamespace

    from test_spot_execution import fixture
    from trading_platform_api.validation.spot_execution import SimulationUnavailable
    from trading_platform_api.validation.spot_metrics import _equity_path

    case = fixture()
    trace = SimpleNamespace(policy=case["policy"])
    with pytest.raises(MetricsInputError, match="TIMEFRAME"):
        _equity_path(case["data"], trace, (), policy(interval_seconds=300))
    trace.policy = replace(case["policy"], initial_inventory=D(1))
    with pytest.raises(MetricsInputError, match="INITIAL_INVENTORY"):
        _equity_path(case["data"], trace, (), policy())
    trace.policy = replace(case["policy"], quote_unit="USD")
    with pytest.raises(SimulationUnavailable, match="UNITS"):
        _equity_path(case["data"], trace, (), policy())
    case = fixture(count=7)
    trace.policy = case["policy"]
    with pytest.raises(SimulationUnavailable, match="GAP"):
        _equity_path(case["data"], trace, (), policy())


def test_fill_tamper_duplicate_and_terminal_balance_rejected():
    from types import SimpleNamespace

    from test_spot_execution import fixture, run
    from trading_platform_api.validation.spot_metrics import _verified_fills

    case = fixture()
    simulation = run(case).trace
    assert simulation is not None
    trace = SimpleNamespace(
        policy=case["policy"], entry_trace=simulation, exit_trace=None, trades=()
    )
    trace.entry_trace = replace(simulation, final_cash=simulation.final_cash + D(1))
    with pytest.raises(MetricsInputError, match="TERMINAL_BALANCE"):
        _verified_fills(trace)
    trace.entry_trace = replace(
        simulation, fills=(simulation.fills[0], simulation.fills[0])
    )
    with pytest.raises(MetricsInputError, match="DUPLICATE"):
        _verified_fills(trace)
    trace.entry_trace = replace(
        simulation, fills=(replace(simulation.fills[0], quantity=D("NaN")),)
    )
    with pytest.raises(MetricsInputError, match="NUMBER"):
        _verified_fills(trace)


def test_partial_entry_fills_make_excursions_unavailable():
    from types import SimpleNamespace

    from trading_platform_api.validation.spot_metrics import _excursion

    trade = SimpleNamespace(
        entry_fill_ids=(UUID(int=1), UUID(int=2)), exit_fill_ids=(UUID(int=3),)
    )
    fills = tuple(SimpleNamespace(fill_id=UUID(int=i)) for i in (1, 2, 3))
    assert _excursion(trade, fills, object()) == (
        None,
        None,
        "CHANGING_EXPOSURE_OR_PARTIAL_FILLS",
    )


def test_extreme_annualization_is_unavailable_without_losing_other_metrics():
    metrics, _ = equity_metrics([1, 100, 10000], periods_per_year=D(31536000))
    assert metrics["cagr"].reason == "ANNUALIZED_NUMERIC_RANGE_EXCEEDED"
    assert value(metrics, "cumulative_return") == 9999
