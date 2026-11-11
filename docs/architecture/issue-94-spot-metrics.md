# #94 — observed personal Spot performance metrics

Status: implementation for DIRECT_OWNER review. This module consumes the exact
archive-bound #92 replay, retaining #473's synthetic-positive and production
RSI/no-order distinction. It does not change C-027v3, qualify a strategy, publish
an API, persist records, or enable trading. Chat 7 sections 17–24 and ADR-0019
remain authoritative. #95–#101 validation controls and Futures remain downstream.

## Runnable usage

Inside the existing asynchronous replay workflow, after obtaining `bundle` from
`await run_spot_backtest(...)`:

```python
from decimal import Decimal
from trading_platform_api.validation.spot_metrics import (
    METHOD, MetricsPolicy, calculate_spot_performance_metrics,
)

policy = MetricsPolicy(
    method=METHOD, version="1", quote_unit="USDT", valuation_mode="BAR_CLOSE",
    interval_seconds=60, periods_per_year=Decimal(525600),
    risk_free_return=Decimal("0"), minimum_acceptable_return=Decimal("0"),
    min_trade_sample=30, min_return_sample=2,
    report_timestamp=bundle.result.created_at,
)
report = calculate_spot_performance_metrics(
    bundle, policy, price_path=bundle.execution_dataset,
)
print(report.result_id, report.get("net_realized_profit"))
print(report.get("sharpe"), report.get("mae"))
```

The timestamp and every numeric assumption above are explicit example choices,
not defaults. The annualization example uses 365 × 24 × 60 periods for a 24/7
market. The caller must declare an appropriate convention for its interval.
Reproduce both persisted examples locally using a disposable PostgreSQL database:

```bash
LINEAGE_TEST_DATABASE_URL=postgresql+asyncpg://postgres@127.0.0.1:5432/lineage_test \
python -m pytest -q tests/backend/test_spot_backtest_postgres.py
python -m pytest -q tests/backend/test_spot_metrics.py
```

## Evidence and identities

The pure function resolves the canonical bundle before calculating. It verifies
unique fills/trades, sides, completion ordering, exact entry/exit quantities,
recorded fee/spread/slippage cash movements, and both simulation terminal balances.
The combined fill stream is ordered by completion time and fill ID and must keep
cash and inventory nonnegative at every event. This single-entry replay requires
all entry fills to complete before any exit fill; terminal balances reconcile in
that same chronological order. Entry/exit fees are already included in trade cash deltas and are never charged
again in trade statistics. Equity reconstruction applies each fill's gross cash
movement and three recorded costs exactly once.

The report pins result ID/schema/digest, trace, dataset, manifest, costs, strategy,
policy, optional path pins and sorted initial-risk declarations. It is an internal
immutable dataclass with a UUIDv5 derived from its canonical content hash. Both
identity fields are omitted from the content hash preimage; all other report
fields are included. The namespace is UUIDv5(NAMESPACE_URL,
`trading-platform:spot-observed-metrics-v1`). No wall clock or external service is
used. Repeated input pins produce identical reports, including after a later
archive correction. Existing historical result IDs and metric tuples are unchanged.

Input numbers are finite Decimal values, at most 60 coefficient digits, exponent
−30 through +30, adjusted exponent ≤30. Series/trades/fills are bounded to 1,000;
policy sample minima to 1–1,000; periods/year to 31,536,000. Canonical encoding
also enforces the repository's 1 MB document limit. Invalid inputs raise
`MetricsInputError`; excessive computed metric magnitudes are rejected. Annualized
CAGR/Calmar that exceed adjusted exponent 100 are explicitly unavailable while
other observed measurements remain usable. Formula arithmetic uses a private
50-digit ROUND_HALF_EVEN Decimal context; fill reconciliation uses the kernel's
120-digit context. Decimal square root and power use that local context, without
binary floating point. Small negative CAGR values can round to −1 at this precision.

## Availability and sample size

Every metric has AVAILABLE, UNDEFINED or UNAVAILABLE state, a reason when absent,
its exact sample count, and warnings. An observed count or trade statistic can be
available below the declared minimum, with `INSUFFICIENT_SAMPLE`. Sharpe, Sortino
and sample volatility require at least two returns and the explicit minimum.
This does not establish independence, confidence intervals, probability, or
statistical qualification.

- No trades: counts and closed-trade gross/net realized profit are zero. Rates,
  expectancy and extrema are undefined. Zero realized profit is not a portfolio
  return or proof of zero risk.
- No losses: profit factor is undefined (`NO_LOSSES`), never infinite or zero.
- Missing price path: equity metrics are `PRICE_PATH_NOT_PROVIDED`; trade
  statistics remain available. Initial inventory without a pinned initial price
  fails closed, rather than assuming its value is zero.
- Missing initial risks: R aggregates are unavailable unless every reported trade
  has a positive quote amount, matching trade ID/unit, declared methodology and
  canonical source reference. These are caller-supplied pinned risk declarations;
  the engine does not infer a stop or independently certify the source's economics.
- No benchmark: `BENCHMARK_NOT_PROVIDED`. No outperformance claim is made.
- Open inventory: closed-trade statistics remain distinct and a report warning
  identifies inventory excluded from realized profit. Equity includes it if valued.

Ordered trade observations preserve profit, cash return and optional R. The signs
provide win/loss/breakeven and R distributions; cumulative R is their sum. Maximum
win/loss streaks reset on breakeven. UTC daily, Monday-start weekly and calendar
monthly buckets use final exit-fill completion. Extrema describe the observed
sample only; no fitted tail probability or independent-trade claim is made.

## Equity, returns and drawdowns

The optional path must equal `bundle.execution_dataset`. The engine reuses the
execution kernel's `_bars` validator for scope, OHLCV, source/revision hashes,
units, finality and complete regular coverage. Each finalized close must be
available at that close; delayed/revised closes unavailable at the valuation are
rejected. No execution-path revision is injected into historical decision inputs.

E0 is initial cash plus initial inventory at an exact already-available close at
the period start (required only for nonzero initial inventory). Events at each
subsequent close apply fills first, then mark `cash + inventory × close`. This is
completion-event accounting under the existing bar simulator, not a claim about
an unobserved intrabar fill clock. All equity denominators must be positive.

Returns are consecutive simple equity ratios minus one; cumulative return uses
last/first. High-water drawdowns are recorded in quote units and fractions.
Average drawdown uses equally weighted right-endpoint intervals, excluding E0.
Episodes start at the most recent peak, end on recovery to that peak, and retain
peak/trough/recovery timestamps, observed underwater and recovery durations.
Unfinished episodes are explicitly censored; they never count as completed
recoveries. All episodes are retained so the worst depth/period is inspectable.
Recovery factor is total equity gain divided by maximum absolute drawdown.

Volatility uses sample variance (m−1) and sqrt(periods/year). Sharpe subtracts the
explicit per-period risk-free return. Sortino uses mean excess over the minimum
acceptable return and RMS negative excess across **all m returns**. Zero variance,
no downside or zero drawdown ratios are undefined. CAGR uses
`(E_last/E_first) ** (periods_per_year/m) − 1`; Calmar divides it by maximum
fractional drawdown. No annualization or risk-free value is inferred.

Exposure integrates nonzero inventory exactly between completion events through
the end of the observation window. Turnover divides total absolute gross fill
notional (excluding costs) by time-weighted marked equity, using equal-grid right
endpoints. Both disclose the same window and policy as the curve.

## MAE/MFE limits

Excursions are signed gross quote-per-unit changes from entry VWAP: MAE ≤0,
MFE ≥0. Only constant-quantity longs and wholly held bars can support them. Partial
fills/changing exposure or missing/partial boundary bars yield specific reasons.
The current kernel fills from bar evidence and records completion at availability;
the exit bar can include prices after execution. Its extrema therefore cannot
prove a whole-trade excursion. Current persisted positive acceptance truthfully
reports `PARTIAL_EXIT_BAR_AMBIGUITY`; no entry/exit-only excursion is fabricated.

## Verification

Hand-computed +30/−10/0 trades, empty/one-sided samples, R and calendar
buckets, 100→120→90→108 drawdown, recovery/censoring, sample variance and downside
denominator, zero variance/no downside, annualization and numeric bounds are
covered. Kernel-backed tests exercise real pinned-price marking, costs, open
inventory, grid/unit failures and fill tampering. The PostgreSQL public runner
cases calculate reports, retain exact result pins, reject tampering/foreign paths,
and verify report stability after a later correction. Synthetic evidence remains
explicitly synthetic; actual profitability and broader validation are not inferred.
