# Spot Monte Carlo observation (Issue #97)

`run_spot_monte_carlo` analyzes one exact, observed C-027v3 Spot backtest and
its frozen #94 `SpotPerformanceReport`. It accepts no free-standing return
series and performs no network, provider, API, or exchange calls.

```python
from trading_platform_api.validation.spot_metrics import (
    calculate_spot_performance_metrics,
)
from trading_platform_api.validation.spot_monte_carlo import (
    run_spot_monte_carlo,
)

report = calculate_spot_performance_metrics(
    backtest_bundle,
    frozen_metrics_policy,
    price_path=backtest_bundle.execution_dataset,
)
result = run_spot_monte_carlo(
    backtest_bundle,
    report,
    block_length=5,
    seed=-2026,
    as_of=analysis_as_of,
    created_at=analysis_created_at,
)
```

The producer re-resolves the archived replay, recomputes and matches the exact
#94 report, verifies Spot/BACKTEST/data-integrity/point-in-time state, checks
freshness and sample sufficiency, and hashes the ordered timestamped bar-return
series before sampling. It freezes the source horizon and timeframe in the
result. The example is an interface illustration; synthetic fixtures in the
test suite are implementation evidence only, not market or performance claims.

## Reading the result

C-072v2 has only `OBSERVED`, `INCONCLUSIVE`, or `FAILED` terminal outcomes.
`OBSERVED` contains the separate observed-path statistics and the three
per-metric percentile summaries:

- `terminal_compounded_return` (`ratio`)
- `maximum_fractional_drawdown` (`ratio`)
- `longest_negative_bar_streak` (`bars`)

Quantiles are nearest-rank 2.5%, 50%, and 97.5%. The 2.5–97.5% values form a
conditional percentile bootstrap range, not a guaranteed future range or a
probability of future performance. Missing values are never zero-filled.

## Method and limitations

- Non-circular moving blocks are sampled with replacement from ordered net
  per-timeframe-bar equity returns. Blocks retain source order; only the final
  block is truncated to the original path horizon.
- Dependence is preserved only within each sampled block. Longer dependence,
  regime change, IID trade resampling, parametric/Gaussian fitting, future data,
  and walk-forward fold pooling are not modeled.
- A caller-supplied signed 64-bit seed drives versioned SplitMix64 and a
  versioned modulo mapping to valid block starts. There is no default or hidden
  entropy.
- The source requires at least 100 complete intervals, a block length of at
  least 2 and no more than half the source, at least 20 block-length units, and
  #94 return/trade sample sufficiency. It includes no trade win-rate/expectancy
  intervals or intrabar drawdown.
- The source limit is 2,000 intervals and the run is exactly 10,000 paths, with
  a 20,000,000 generated-return ceiling. The source is not truncated and the
  iteration count is never reduced.
- C-029 folds are not inputs; no pooling or independence assumption is made
  across folds.
- `INCONCLUSIVE` represents missing/insufficient evidence or an exceeded
  resource bound. `FAILED` represents invalid/tampered/mismatched/stale/
  expired/non-Spot evidence.
- C-072v1, C-030/C-028, strategy status, learning, risk, approval, and execution
  are not changed or integrated. C-072v2 codec support does not authorize
  durable retention.
- This is Spot-only research evidence. It does not complete the Phase 1 Futures
  obligation or make a profitability claim.

Focused deterministic tests:

```sh
python -m pytest -q tests/backend/test_monte_carlo.py
```

The archive-bound C-027v3/#94 integration cases run in the existing local
PostgreSQL test:

```sh
LINEAGE_TEST_DATABASE_URL=postgresql+asyncpg://localhost/lineage_test \
  python -m pytest -q \
  tests/backend/test_spot_backtest_postgres.py::test_persisted_postgresql_spot_backtest_entry_and_fail_closed_cases
```
