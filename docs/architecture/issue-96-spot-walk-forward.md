# Spot walk-forward observations (Issue #96)

`run_spot_walk_forward` is the offline application entry point for the bounded
PERSONAL_SPOT_RESEARCH profile. It accepts a frozen `WalkForwardPlanSpecV2`, one
pre-pinned request row for each generated fold, the existing shared
`OOSResearchJournal`, and the already configured backtest dependencies. It
generates grid-aligned rolling or anchored TRAIN/VALIDATION/TEST windows, freezes
each fold through the existing Spot OOS protocol, and executes the TEST partition
only through the archive-bound Spot backtest and #94 metrics path.

```python
from trading_platform_api.validation.spot_walk_forward import (
    resolve_spot_walk_forward_result,
    run_spot_walk_forward,
)

bundle = await run_spot_walk_forward(
    journal=walk_journal,
    spec=walk_spec,
    requests=walk_requests,
    session=session,
    strategy_registry=registry,
    lineage_store=lineage,
)
result = resolve_spot_walk_forward_result(bundle, journal=walk_journal)
```

The runnable end-to-end example builds those values from the accepted archived
Spot fixture and exercises both a synthetic positive-analysis case and the
production-RSI zero-trade case:

```sh
LINEAGE_TEST_DATABASE_URL=postgresql+asyncpg://localhost/lineage_test \
  python -m pytest -q \
  tests/backend/test_spot_backtest_postgres.py::test_persisted_postgresql_spot_backtest_entry_and_fail_closed_cases
```

That test uses only its local PostgreSQL test schema and recorded fixtures; it
makes no provider or exchange calls. Its synthetic positive case is test evidence
for implementation behavior only, not a market result. Without the local
PostgreSQL test database, run the fold, aggregation, cancellation, and codec
checks with:

```sh
python -m pytest -q tests/backend/test_spot_walk_forward.py
```

## Reading the result

C-029 schema 2 is observation-only. Each planned fold remains present with its
TRAIN, selection-VALIDATION, and TEST bounds, pinned requests, exact OOS result
when one exists, journal receipt identity, check states, raw trades, and the #94
metric value/state/reason/unit/sample/warnings. Missing values are not replaced
with zero. Failed, inconclusive, and cancelled folds remain visible in coverage.

Metric aggregates include comparable available-fold counts, unavailable reasons,
mean, median, population standard deviation, min/max and deterministic fold IDs.
Total trade counts are descriptive and have no best/worst direction. The
consistency ratio uses positive held-out net-realized-profit folds over folds
with an available net-realized-profit metric; its numerator, denominator,
planned-fold count, and missing-fold count are reported. This ratio is not a
probability, qualification score, or claim that folds are independent.

## Boundaries and limitations

- `OBSERVED` means complete evidence under the frozen observation policy; it does
  not mean profitable, qualified, or approved to trade.
- The workflow supports a fixed candidate or the existing finite declared
  validation-net-profit selection policy. It adds no optimizer or parameter
  search engine.
- It reports no pooled win rate or Sharpe, compounded return, uncertainty
  interval, bootstrap/Monte Carlo result, sensitivity, or regime qualification.
- Candle history without matching archive-bound replay inputs is not fabricated
  into execution evidence. Capacity, expiry, altered pins, and prior held-out
  access fail closed; incomplete or insufficient evidence remains inconclusive.
- C-029v1 and its consumers are unchanged. C-029v2 is not accepted for
  qualification and is not authorized for durable lineage retention. No API,
  scheduler, provider, exchange, risk, approval, or execution authority is added.
- This completes only the bounded Spot research observation slice. It does not
  close the broader C-029/full-platform, Futures, or profitability requirements.
