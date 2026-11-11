"""Pure observed Spot metrics over canonical replay evidence (no qualification)."""

from __future__ import annotations

from dataclasses import dataclass, fields, replace
from datetime import UTC, datetime, timedelta
from decimal import ROUND_HALF_EVEN, Context, Decimal, DecimalException, localcontext
from enum import StrEnum
from uuid import NAMESPACE_URL, UUID, uuid5

from trading_platform_api.contracts.serialization import canonical_sha256
from trading_platform_api.market_data.ohlcv import _TIMEFRAMES
from trading_platform_api.validation.contracts import MetricValue
from trading_platform_api.validation.contracts_v2 import ValidationArtifactReferenceV2
from trading_platform_api.validation.dataset_loader import LoadedValidationDataset
from trading_platform_api.validation.spot_backtest import (
    SpotBacktestBundle,
    SpotBacktestTrace,
    SpotBacktestTrade,
    resolve_spot_backtest_result,
)
from trading_platform_api.validation.spot_execution import (
    OrderSide,
    SimulationFill,
    _bars,
)

METHOD = "spot-observed-metrics-v1"
_CONTEXT = Context(prec=50, rounding=ROUND_HALF_EVEN)
_NAMESPACE = uuid5(NAMESPACE_URL, f"trading-platform:{METHOD}")
MAX_POINTS = 1000
ZERO = Decimal(0)
ONE = Decimal(1)


class MetricsInputError(ValueError):
    """Evidence or calculation policy cannot support a trustworthy report."""


def _require(condition: bool, reason: str) -> None:
    if not condition:
        raise MetricsInputError(reason)


def _number(value: Decimal, *, positive: bool = False) -> None:
    _require(
        type(value) is Decimal
        and value.is_finite()
        and len(value.as_tuple().digits) <= 60
        and -30 <= int(value.as_tuple().exponent) <= 30
        and value.adjusted() <= 30
        and (not positive or value > 0),
        "INVALID_OR_EXCESSIVE_NUMBER",
    )


def _time(value: datetime) -> datetime:
    _require(type(value) is datetime and value.utcoffset() is not None, "INVALID_TIME")
    return value.astimezone(UTC)


@dataclass(frozen=True, slots=True)
class MetricsPolicy:
    method: str
    version: str
    quote_unit: str
    valuation_mode: str
    interval_seconds: int
    periods_per_year: Decimal
    risk_free_return: Decimal
    minimum_acceptable_return: Decimal
    min_trade_sample: int
    min_return_sample: int
    report_timestamp: datetime

    def __post_init__(self) -> None:
        _require(
            self.method == METHOD
            and self.version == "1"
            and self.valuation_mode == "BAR_CLOSE",
            "UNSUPPORTED_METRICS_POLICY",
        )
        _require(
            type(self.quote_unit) is str
            and 0 < len(self.quote_unit) <= 32
            and self.quote_unit == self.quote_unit.strip(),
            "INVALID_QUOTE_UNIT",
        )
        _require(
            type(self.interval_seconds) is int
            and 1 <= self.interval_seconds <= 31_536_000,
            "INVALID_INTERVAL",
        )
        _number(self.periods_per_year, positive=True)
        _require(self.periods_per_year <= 31_536_000, "EXCESSIVE_ANNUALIZATION")
        _number(self.risk_free_return)
        _number(self.minimum_acceptable_return)
        for value in (self.min_trade_sample, self.min_return_sample):
            _require(
                type(value) is int and 1 <= value <= MAX_POINTS,
                "INVALID_SAMPLE_MINIMUM",
            )
        object.__setattr__(self, "report_timestamp", _time(self.report_timestamp))


class MetricState(StrEnum):
    AVAILABLE = "AVAILABLE"
    UNDEFINED = "UNDEFINED"
    UNAVAILABLE = "UNAVAILABLE"


@dataclass(frozen=True, slots=True)
class ObservedMetric:
    name: str
    state: MetricState
    reason: str | None
    metric: MetricValue | None
    sample_count: int
    warnings: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class InitialRisk:
    trade_id: UUID
    amount: Decimal
    quote_unit: str
    methodology: str
    source: ValidationArtifactReferenceV2

    def __post_init__(self) -> None:
        _require(type(self.trade_id) is UUID, "INVALID_RISK_TRADE_ID")
        _number(self.amount, positive=True)
        _require(
            type(self.methodology) is str
            and 0 < len(self.methodology) <= 128
            and self.methodology == self.methodology.strip(),
            "INVALID_RISK_METHOD",
        )
        _require(
            type(self.source) is ValidationArtifactReferenceV2,
            "UNRESOLVED_RISK_REFERENCE",
        )


@dataclass(frozen=True, slots=True)
class EquityPoint:
    timestamp: datetime
    cash: Decimal
    inventory: Decimal
    equity: Decimal
    period_return: Decimal | None
    absolute_drawdown: Decimal
    fractional_drawdown: Decimal


@dataclass(frozen=True, slots=True)
class DrawdownEpisode:
    peak_at: datetime
    trough_at: datetime
    recovered_at: datetime | None
    observed_until: datetime
    depth: Decimal
    fraction: Decimal
    underwater_seconds: Decimal
    recovery_seconds: Decimal
    censored: bool


@dataclass(frozen=True, slots=True)
class TradeObservation:
    trade_id: UUID
    completed_at: datetime
    profit: Decimal
    cash_return: Decimal
    r_multiple: Decimal | None
    mae: Decimal | None
    mfe: Decimal | None
    excursion_reason: str | None


@dataclass(frozen=True, slots=True)
class RealizedBucket:
    frequency: str
    start: datetime
    profit: Decimal
    trade_count: int


@dataclass(frozen=True, slots=True)
class SpotPerformanceReport:
    report_id: UUID
    content_sha256: str
    method: str
    policy: MetricsPolicy
    result_id: UUID
    result_schema: str
    result_sha256: str
    trace_sha256: str
    dataset_sha256: str
    manifest_sha256: str
    cost_sha256: str
    strategy_sha256: str
    input_sha256: str
    metrics: tuple[ObservedMetric, ...]
    trades: tuple[TradeObservation, ...]
    equity: tuple[EquityPoint, ...]
    drawdowns: tuple[DrawdownEpisode, ...]
    buckets: tuple[RealizedBucket, ...]
    warnings: tuple[str, ...]

    def get(self, name: str) -> ObservedMetric:
        return next(item for item in self.metrics if item.name == name)


def _available(
    name: str, value: Decimal, unit: str, n: int, minimum: int
) -> ObservedMetric:
    _require(
        value.is_finite() and value.adjusted() <= 100, "METRIC_NUMERIC_RANGE_EXCEEDED"
    )
    return ObservedMetric(
        name,
        MetricState.AVAILABLE,
        None,
        MetricValue(name, value, unit, METHOD),
        n,
        ("INSUFFICIENT_SAMPLE",) if n < minimum else (),
    )


def _missing(
    name: str, reason: str, n: int = 0, state: MetricState = MetricState.UNAVAILABLE
) -> ObservedMetric:
    return ObservedMetric(name, state, reason, None, n, ())


def _fill_cash(fill: SimulationFill) -> Decimal:
    cost = fill.costs.fee + fill.costs.spread + fill.costs.slippage
    notional = fill.quantity * fill.gross_price
    return -notional - cost if fill.side is OrderSide.BUY else notional - cost


def _verified_fills(trace: SpotBacktestTrace) -> tuple[SimulationFill, ...]:
    simulations = (trace.entry_trace,) + (
        (trace.exit_trace,) if trace.exit_trace else ()
    )
    fills = tuple(f for simulation in simulations for f in simulation.fills)
    _require(
        len(fills) <= MAX_POINTS and len({f.fill_id for f in fills}) == len(fills),
        "DUPLICATE_OR_EXCESSIVE_FILLS",
    )
    cash, inventory = trace.policy.initial_cash, trace.policy.initial_inventory
    known: set[UUID] = set()
    for simulation in simulations:
        _require(
            all(
                a.observed_at <= b.observed_at
                for a, b in zip(simulation.fills, simulation.fills[1:])
            ),
            "NONCHRONOLOGICAL_FILLS",
        )
        for fill in simulation.fills:
            _require(
                type(fill.fill_id) is UUID
                and type(fill.order_id) is UUID
                and type(fill.side) is OrderSide,
                "INVALID_FILL_ID_OR_SIDE",
            )
            _time(fill.observed_at)
            _number(fill.quantity, positive=True)
            _number(fill.gross_price, positive=True)
            for cost in (fill.costs.fee, fill.costs.spread, fill.costs.slippage):
                _number(cost)
                _require(cost >= 0, "NEGATIVE_FILL_COST")
            _require(
                trace.policy.period_start < fill.observed_at <= trace.policy.period_end,
                "FILL_OUTSIDE_PERIOD",
            )
            cash += _fill_cash(fill)
            inventory += fill.quantity if fill.side is OrderSide.BUY else -fill.quantity
            _require(cash >= 0 and inventory >= 0, "INVALID_CASH_OR_INVENTORY")
            known.add(fill.fill_id)
        _require(
            (cash, inventory) == (simulation.final_cash, simulation.final_inventory),
            "TERMINAL_BALANCE_MISMATCH",
        )
    _require(
        len(trace.trades) <= MAX_POINTS
        and len({t.trade_id for t in trace.trades}) == len(trace.trades),
        "DUPLICATE_OR_EXCESSIVE_TRADES",
    )
    used: set[UUID] = set()
    by_id = {f.fill_id: f for f in fills}
    for trade in trace.trades:
        _require(type(trade.trade_id) is UUID, "INVALID_TRADE_ID")
        _number(trade.entry_cash_outflow, positive=True)
        ids = trade.entry_fill_ids + trade.exit_fill_ids
        _require(
            bool(trade.entry_fill_ids)
            and bool(trade.exit_fill_ids)
            and len(set(ids)) == len(ids)
            and set(ids) <= known
            and not used.intersection(ids),
            "TRADE_FILL_MEMBERSHIP_MISMATCH",
        )
        used.update(ids)
        entry = tuple(by_id[i] for i in trade.entry_fill_ids)
        exit_ = tuple(by_id[i] for i in trade.exit_fill_ids)
        _require(
            all(
                f.side is OrderSide.BUY and f.order_id == trade.entry_order_id
                for f in entry
            )
            and all(
                f.side is OrderSide.SELL and f.order_id == trade.exit_order_id
                for f in exit_
            )
            and max(f.observed_at for f in entry) < min(f.observed_at for f in exit_),
            "TRADE_EVENT_ORDER_MISMATCH",
        )
        _require(
            sum((f.quantity for f in entry), ZERO)
            == sum((f.quantity for f in exit_), ZERO)
            == trade.quantity
            and -sum((_fill_cash(f) for f in entry), ZERO) == trade.entry_cash_outflow
            and sum((_fill_cash(f) for f in exit_), ZERO) == trade.exit_cash_inflow
            and trade.exit_cash_inflow - trade.entry_cash_outflow
            == trade.realized_cash_delta,
            "TRADE_CASH_RECONCILIATION_FAILED",
        )
    return tuple(sorted(fills, key=lambda f: (f.observed_at, str(f.fill_id))))


def _trade_metrics(
    trades: tuple[TradeObservation, ...], policy: MetricsPolicy
) -> list[ObservedMetric]:
    n = len(trades)
    profits = tuple(t.profit for t in trades)
    wins = tuple(p for p in profits if p > 0)
    losses = tuple(-p for p in profits if p < 0)
    gross, loss = sum(wins, ZERO), sum(losses, ZERO)
    values = {
        "total_trades": (Decimal(n), "count"),
        "winning_trades": (Decimal(len(wins)), "count"),
        "losing_trades": (Decimal(len(losses)), "count"),
        "breakeven_trades": (Decimal(n - len(wins) - len(losses)), "count"),
        "gross_profit": (gross, policy.quote_unit),
        "gross_loss": (loss, policy.quote_unit),
        "net_realized_profit": (gross - loss, policy.quote_unit),
    }
    output = [
        _available(k, v, u, n, policy.min_trade_sample) for k, (v, u) in values.items()
    ]
    optional = {
        "win_rate": (Decimal(len(wins)), Decimal(n), "ratio", "NO_CLOSED_TRADES"),
        "loss_rate": (Decimal(len(losses)), Decimal(n), "ratio", "NO_CLOSED_TRADES"),
        "average_win": (
            gross,
            Decimal(len(wins)),
            policy.quote_unit,
            "NO_WINNING_TRADES",
        ),
        "average_loss": (
            loss,
            Decimal(len(losses)),
            policy.quote_unit,
            "NO_LOSING_TRADES",
        ),
        "expectancy": (gross - loss, Decimal(n), policy.quote_unit, "NO_CLOSED_TRADES"),
        "profit_factor": (gross, loss, "ratio", "NO_LOSSES"),
        "largest_win": (
            max(wins, default=ZERO),
            ONE if wins else ZERO,
            policy.quote_unit,
            "NO_WINNING_TRADES",
        ),
        "largest_loss": (
            max(losses, default=ZERO),
            ONE if losses else ZERO,
            policy.quote_unit,
            "NO_LOSING_TRADES",
        ),
    }
    for name, (num, den, unit, reason) in optional.items():
        output.append(
            _available(name, num / den, unit, n, policy.min_trade_sample)
            if den
            else _missing(name, reason, n, MetricState.UNDEFINED)
        )
    for name, sign in (
        ("maximum_consecutive_wins", 1),
        ("maximum_consecutive_losses", -1),
    ):
        current = longest = 0
        for profit in profits:
            current = current + 1 if profit * sign > 0 else 0
            longest = max(longest, current)
        output.append(
            _available(name, Decimal(longest), "count", n, policy.min_trade_sample)
        )
    rs = tuple(t.r_multiple for t in trades if t.r_multiple is not None)
    for name in ("average_r", "median_r", "cumulative_r"):
        if not n:
            output.append(_missing(name, "NO_CLOSED_TRADES", n, MetricState.UNDEFINED))
        elif len(rs) != n:
            output.append(
                _missing(name, "INITIAL_RISK_NOT_PROVIDED_FOR_FULL_SAMPLE", n)
            )
        else:
            ordered = sorted(rs)
            value = (
                sum(rs, ZERO) / n
                if name == "average_r"
                else sum(rs, ZERO)
                if name == "cumulative_r"
                else (ordered[(n - 1) // 2] + ordered[n // 2]) / 2
            )
            output.append(_available(name, value, "R", n, policy.min_trade_sample))
    return output


def _buckets(trades: tuple[TradeObservation, ...]) -> tuple[RealizedBucket, ...]:
    groups: dict[tuple[str, datetime], tuple[Decimal, int]] = {}
    for trade in trades:
        day = trade.completed_at.astimezone(UTC).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        for frequency, start in (
            ("DAY", day),
            ("WEEK", day - timedelta(days=day.weekday())),
            ("MONTH", day.replace(day=1)),
        ):
            profit, count = groups.get((frequency, start), (ZERO, 0))
            groups[frequency, start] = profit + trade.profit, count + 1
    return tuple(
        RealizedBucket(f, at, p, n) for (f, at), (p, n) in sorted(groups.items())
    )


_EQUITY_NAMES = (
    "cumulative_return",
    "maximum_absolute_drawdown",
    "maximum_fractional_drawdown",
    "average_absolute_drawdown",
    "average_fractional_drawdown",
    "drawdown_episodes",
    "maximum_underwater_seconds",
    "maximum_recovery_seconds",
    "recovery_factor",
    "volatility",
    "sharpe",
    "sortino",
    "cagr",
    "calmar",
    "exposure",
    "turnover",
)


def _equity_statistics(
    points: tuple[EquityPoint, ...], policy: MetricsPolicy
) -> tuple[list[ObservedMetric], tuple[DrawdownEpisode, ...]]:
    """Statistics use right endpoints over equal intervals; initial equity is E0."""
    _require(2 <= len(points) <= MAX_POINTS + 1, "INVALID_EQUITY_SAMPLE")
    _require(all(p.equity > 0 for p in points), "NONPOSITIVE_EQUITY")
    m = len(points) - 1
    returns = tuple(
        points[i].equity / points[i - 1].equity - ONE for i in range(1, len(points))
    )
    step = timedelta(seconds=policy.interval_seconds)
    _require(
        all(b.timestamp - a.timestamp == step for a, b in zip(points, points[1:])),
        "IRREGULAR_GRID",
    )
    peak = points[0]
    trough = peak
    active = False
    episodes: list[DrawdownEpisode] = []
    for point in points[1:]:
        if point.equity >= peak.equity:
            if active:
                episodes.append(_episode(peak, trough, point, point.timestamp))
            peak, trough, active = point, point, False
        else:
            active = True
            if point.equity < trough.equity:
                trough = point
    if active:
        episodes.append(_episode(peak, trough, None, points[-1].timestamp))
    absolute = tuple(p.absolute_drawdown for p in points[1:])
    fractions = tuple(p.fractional_drawdown for p in points[1:])
    max_abs, max_frac = max(absolute), max(fractions)
    net = points[-1].equity - points[0].equity
    values = {
        "cumulative_return": (points[-1].equity / points[0].equity - ONE, "ratio"),
        "maximum_absolute_drawdown": (max_abs, policy.quote_unit),
        "maximum_fractional_drawdown": (max_frac, "ratio"),
        "average_absolute_drawdown": (sum(absolute, ZERO) / m, policy.quote_unit),
        "average_fractional_drawdown": (sum(fractions, ZERO) / m, "ratio"),
        "drawdown_episodes": (Decimal(len(episodes)), "count"),
        "maximum_underwater_seconds": (
            max((e.underwater_seconds for e in episodes), default=ZERO),
            "seconds",
        ),
    }
    output = [
        _available(k, v, u, m, policy.min_return_sample) for k, (v, u) in values.items()
    ]
    completed = tuple(e for e in episodes if not e.censored)
    output.append(
        _available(
            "maximum_recovery_seconds",
            max(e.recovery_seconds for e in completed),
            "seconds",
            m,
            policy.min_return_sample,
        )
        if completed
        else _missing(
            "maximum_recovery_seconds", "NO_RECOVERED_EPISODE", m, MetricState.UNDEFINED
        )
    )
    output.append(
        _available(
            "recovery_factor", net / max_abs, "ratio", m, policy.min_return_sample
        )
        if max_abs
        else _missing("recovery_factor", "ZERO_DRAWDOWN", m, MetricState.UNDEFINED)
    )
    try:
        cagr = (points[-1].equity / points[0].equity) ** (
            policy.periods_per_year / Decimal(m)
        ) - ONE
    except DecimalException:
        cagr = Decimal("Infinity")
    if not cagr.is_finite() or cagr.adjusted() > 100:
        output.append(_missing("cagr", "ANNUALIZED_NUMERIC_RANGE_EXCEEDED", m))
        output.append(_missing("calmar", "ANNUALIZED_NUMERIC_RANGE_EXCEEDED", m))
    else:
        output.append(_available("cagr", cagr, "ratio", m, policy.min_return_sample))
        output.append(
            _available("calmar", cagr / max_frac, "ratio", m, policy.min_return_sample)
            if max_frac
            else _missing("calmar", "ZERO_DRAWDOWN", m, MetricState.UNDEFINED)
        )
    if m < max(2, policy.min_return_sample):
        output.extend(
            _missing(k, "INSUFFICIENT_RETURN_SAMPLE", m)
            for k in ("volatility", "sharpe", "sortino")
        )
    else:
        mean = sum(returns, ZERO) / m
        variance = sum(((r - mean) ** 2 for r in returns), ZERO) / (m - 1)
        deviation = variance.sqrt()
        annual = policy.periods_per_year.sqrt()
        output.append(
            _available(
                "volatility", deviation * annual, "ratio", m, policy.min_return_sample
            )
        )
        output.append(
            _available(
                "sharpe",
                (mean - policy.risk_free_return) / deviation * annual,
                "ratio",
                m,
                policy.min_return_sample,
            )
            if deviation
            else _missing("sharpe", "ZERO_VARIANCE", m, MetricState.UNDEFINED)
        )
        downside = (
            sum(
                (min(r - policy.minimum_acceptable_return, ZERO) ** 2 for r in returns),
                ZERO,
            )
            / m
        ).sqrt()
        output.append(
            _available(
                "sortino",
                (mean - policy.minimum_acceptable_return) / downside * annual,
                "ratio",
                m,
                policy.min_return_sample,
            )
            if downside
            else _missing("sortino", "NO_DOWNSIDE_DEVIATION", m, MetricState.UNDEFINED)
        )
    return output, tuple(episodes)


def _episode(
    peak: EquityPoint,
    trough: EquityPoint,
    recovered: EquityPoint | None,
    until: datetime,
) -> DrawdownEpisode:
    return DrawdownEpisode(
        peak.timestamp,
        trough.timestamp,
        recovered.timestamp if recovered else None,
        until,
        peak.equity - trough.equity,
        (peak.equity - trough.equity) / peak.equity,
        Decimal(str((until - peak.timestamp).total_seconds())),
        Decimal(str((until - trough.timestamp).total_seconds())),
        recovered is None,
    )


def _equity_path(
    data: LoadedValidationDataset,
    trace: SpotBacktestTrace,
    fills: tuple[SimulationFill, ...],
    policy: MetricsPolicy,
) -> tuple[EquityPoint, ...]:
    execution = trace.policy
    bars = _bars(
        data, execution
    )  # Reuse kernel's exact C-001/C-091/C-102/C-103 validation.
    _require(len(bars) <= MAX_POINTS, "EXCESSIVE_PRICE_PATH")
    _require(
        _TIMEFRAMES[execution.timeframe] == policy.interval_seconds,
        "POLICY_TIMEFRAME_MISMATCH",
    )
    # Close valuation is supported only when finalized prices were available at that close.
    _require(
        all(b.available == b.ended for b in bars),
        "CLOSE_PRICE_NOT_AVAILABLE_AT_VALUATION",
    )
    cash, inventory = execution.initial_cash, execution.initial_inventory
    initial_equity = cash
    if inventory:
        starting = tuple(
            r
            for r in data.reconstruction.selected_revisions
            if r.finalized_interval_end == execution.period_start
            and r.availability_time <= execution.period_start
        )
        _require(len(starting) == 1, "INITIAL_INVENTORY_VALUATION_NOT_PROVIDED")
        initial_equity += inventory * next(
            m.value for m in starting[0].observation.metrics if m.metric_name == "close"
        )
    _require(initial_equity > 0, "NONPOSITIVE_INITIAL_EQUITY")
    points = [
        EquityPoint(
            execution.period_start, cash, inventory, initial_equity, None, ZERO, ZERO
        )
    ]
    index = 0
    high = initial_equity
    for bar in bars:
        while index < len(fills) and fills[index].observed_at <= bar.ended:
            fill = fills[index]
            with localcontext(Context(prec=120, rounding=ROUND_HALF_EVEN)):
                cash += _fill_cash(fill)
                inventory += (
                    fill.quantity if fill.side is OrderSide.BUY else -fill.quantity
                )
            index += 1
        close = next(
            m.value
            for m in bar.revision.observation.metrics
            if m.metric_name == "close"
        )
        equity = cash + inventory * close
        _require(equity > 0, "NONPOSITIVE_EQUITY")
        high = max(high, equity)
        points.append(
            EquityPoint(
                bar.ended,
                cash,
                inventory,
                equity,
                equity / points[-1].equity - ONE,
                high - equity,
                (high - equity) / high,
            )
        )
    _require(index == len(fills), "UNVALUED_FILL")
    terminal = trace.exit_trace or trace.entry_trace
    _require(
        (cash, inventory) == (terminal.final_cash, terminal.final_inventory),
        "VALUATION_TERMINAL_BALANCE_MISMATCH",
    )
    return tuple(points)


def _excursion(
    trade: SpotBacktestTrade,
    fills: tuple[SimulationFill, ...],
    data: LoadedValidationDataset | None,
) -> tuple[Decimal | None, Decimal | None, str | None]:
    if data is None:
        return None, None, "PRICE_PATH_NOT_PROVIDED"
    by_id = {f.fill_id: f for f in fills}
    entries = tuple(by_id[i] for i in trade.entry_fill_ids)
    exits = tuple(by_id[i] for i in trade.exit_fill_ids)
    if len(entries) != 1 or len(exits) != 1:
        return None, None, "CHANGING_EXPOSURE_OR_PARTIAL_FILLS"
    entry, exit_ = entries[0], exits[0]
    bars = tuple(
        r
        for r in data.reconstruction.selected_revisions
        if entry.observed_at <= r.observation.event_time < exit_.observed_at
    )
    if not bars or any(
        r.finalized_interval_end is None or r.finalized_interval_end > exit_.observed_at
        for r in bars
    ):
        return None, None, "PARTIAL_BOUNDARY_OR_MISSING_HELD_BARS"
    # Fill event marks completion, not the intrabar execution instant. Boundary
    # bars are ambiguous under this kernel: only wholly-held intervals are reported.
    exit_revision = by_id[trade.exit_fill_ids[0]].revision_id
    if any(r.revision_id == exit_revision for r in bars):
        return None, None, "PARTIAL_EXIT_BAR_AMBIGUITY"
    lows = tuple(
        next(m.value for m in r.observation.metrics if m.metric_name == "low")
        for r in bars
    )
    highs = tuple(
        next(m.value for m in r.observation.metrics if m.metric_name == "high")
        for r in bars
    )
    return (
        min(min(lows) - entry.gross_price, ZERO),
        max(max(highs) - entry.gross_price, ZERO),
        None,
    )


def calculate_spot_performance_metrics(
    bundle: SpotBacktestBundle,
    policy: MetricsPolicy,
    *,
    price_path: LoadedValidationDataset | None = None,
    initial_risks: tuple[InitialRisk, ...] = (),
) -> SpotPerformanceReport:
    """Resolve canonical evidence before calculation; all timestamps are pinned inputs."""
    _require(type(policy) is MetricsPolicy, "INVALID_POLICY")
    _require(
        type(initial_risks) is tuple
        and len(initial_risks) <= MAX_POINTS
        and all(type(r) is InitialRisk for r in initial_risks),
        "INVALID_RISK_INPUTS",
    )
    try:
        with localcontext(_CONTEXT):
            return _calculate(bundle, policy, price_path, initial_risks)
    except MetricsInputError:
        raise
    except (ValueError, DecimalException, KeyError, StopIteration) as exc:
        raise MetricsInputError(f"INVALID_REPLAY_OR_NUMERIC_EVIDENCE: {exc}") from exc


def _calculate(
    bundle: SpotBacktestBundle,
    policy: MetricsPolicy,
    price_path: LoadedValidationDataset | None,
    risks: tuple[InitialRisk, ...],
) -> SpotPerformanceReport:
    _require(
        type(bundle) is SpotBacktestBundle and bundle.trace is not None,
        "UNRESOLVED_BUNDLE",
    )
    assert bundle.trace is not None
    _require(
        len(bundle.trace.trades) <= MAX_POINTS
        and len(bundle.trace.entry_trace.fills) <= MAX_POINTS
        and (
            bundle.trace.exit_trace is None
            or len(bundle.trace.exit_trace.fills) <= MAX_POINTS
        ),
        "EXCESSIVE_TRACE",
    )
    result = resolve_spot_backtest_result(bundle)
    trace = bundle.trace
    assert trace is not None
    _require(policy.quote_unit == trace.policy.quote_unit, "QUOTE_UNIT_MISMATCH")
    _require(policy.report_timestamp >= result.created_at, "REPORT_PRECEDES_RESULT")
    with localcontext(Context(prec=120, rounding=ROUND_HALF_EVEN)):
        fills = _verified_fills(trace)
    risk_by_id = {r.trade_id: r for r in risks}
    _require(
        len(risk_by_id) == len(risks)
        and set(risk_by_id) <= {t.trade_id for t in trace.trades}
        and all(r.quote_unit == policy.quote_unit for r in risks),
        "RISK_ID_OR_UNIT_MISMATCH",
    )
    if price_path is not None:
        _require(
            type(price_path) is LoadedValidationDataset
            and price_path == bundle.execution_dataset,
            "PRICE_PATH_PIN_MISMATCH",
        )
        points = _equity_path(price_path, trace, fills, policy)
    else:
        points = ()
    by_id = {f.fill_id: f for f in fills}
    ordered = sorted(
        trace.trades,
        key=lambda t: (
            max(by_id[i].observed_at for i in t.exit_fill_ids),
            str(t.trade_id),
        ),
    )
    trades = tuple(
        TradeObservation(
            t.trade_id,
            max(by_id[i].observed_at for i in t.exit_fill_ids),
            t.realized_cash_delta,
            t.realized_cash_delta / t.entry_cash_outflow,
            t.realized_cash_delta / risk_by_id[t.trade_id].amount
            if t.trade_id in risk_by_id
            else None,
            *_excursion(t, fills, price_path),
        )
        for t in ordered
    )
    metrics = _trade_metrics(trades, policy)
    episodes: tuple[DrawdownEpisode, ...] = ()
    if points:
        equity_metrics, episodes = _equity_statistics(points, policy)
        metrics.extend(equity_metrics)
        # Exact duration integration across fill events, left-constant inventory.
        inventory = trace.policy.initial_inventory
        previous = trace.policy.period_start
        exposed = ZERO
        for fill in fills:
            if inventory != 0:
                exposed += Decimal(str((fill.observed_at - previous).total_seconds()))
            inventory += fill.quantity if fill.side is OrderSide.BUY else -fill.quantity
            previous = fill.observed_at
        if inventory != 0:
            exposed += Decimal(
                str((trace.policy.period_end - previous).total_seconds())
            )
        duration = Decimal(
            str((trace.policy.period_end - trace.policy.period_start).total_seconds())
        )
        metrics.append(
            _available(
                "exposure",
                exposed / duration,
                "ratio",
                len(points) - 1,
                policy.min_return_sample,
            )
        )
        mean_equity = sum((p.equity for p in points[1:]), ZERO) / (len(points) - 1)
        metrics.append(
            _available(
                "turnover",
                sum((f.quantity * f.gross_price for f in fills), ZERO) / mean_equity,
                "ratio",
                len(points) - 1,
                policy.min_return_sample,
            )
        )
    else:
        metrics.extend(
            _missing(name, "PRICE_PATH_NOT_PROVIDED") for name in _EQUITY_NAMES
        )
    for name, attribute in (("mae", "mae"), ("mfe", "mfe")):
        values = tuple(getattr(t, attribute) for t in trades)
        if values and all(v is not None for v in values):
            metrics.append(
                _available(
                    name,
                    sum(values, ZERO) / len(values),
                    f"{policy.quote_unit}/unit",
                    len(values),
                    policy.min_trade_sample,
                )
            )
        else:
            reason = next(
                (t.excursion_reason for t in trades if t.excursion_reason),
                "NO_CLOSED_TRADES",
            )
            metrics.append(_missing(name, reason, len(trades)))
    metrics.append(_missing("benchmark_relative_return", "BENCHMARK_NOT_PROVIDED"))
    warnings: tuple[str, ...] = (
        "OBSERVED_NOT_QUALIFIED",
        "NO_INDEPENDENCE_OR_PROBABILITY_CLAIM",
    )
    terminal = trace.exit_trace or trace.entry_trace
    if terminal.final_inventory:
        warnings += ("OPEN_INVENTORY_NOT_INCLUDED_IN_CLOSED_TRADE_PROFIT",)
    input_digest = canonical_sha256(
        (
            result.content_sha256,
            policy,
            price_path.dataset_sha256 if price_path else None,
            price_path.manifest_sha256 if price_path else None,
            tuple(sorted(risks, key=lambda r: str(r.trade_id))),
        )
    )
    report = SpotPerformanceReport(
        report_id=UUID(int=0),
        content_sha256="",
        method=METHOD,
        policy=policy,
        result_id=result.result_id,
        result_schema=result.schema_version,
        result_sha256=result.content_sha256,
        trace_sha256=trace.content_sha256,
        dataset_sha256=result.dataset_sha256,
        manifest_sha256=result.manifest_sha256,
        cost_sha256=result.cost_assumptions.content_sha256,
        strategy_sha256=result.strategy_version.content_sha256,
        input_sha256=input_digest,
        metrics=tuple(sorted(metrics, key=lambda m: m.name)),
        trades=trades,
        equity=points,
        drawdowns=episodes,
        buckets=_buckets(trades),
        warnings=warnings,
    )
    digest = canonical_sha256(
        {
            f.name: getattr(report, f.name)
            for f in fields(report)
            if f.name not in {"report_id", "content_sha256"}
        }
    )
    return replace(report, report_id=uuid5(_NAMESPACE, digest), content_sha256=digest)
