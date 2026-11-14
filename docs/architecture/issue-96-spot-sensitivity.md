# Issue #98 — Spot parameter sensitivity

## Scope and method

The offline producer accepts one exact archive-bound observed C-027v3 Spot run
and its recomputed C-094 performance report. It freezes an increasing grid of
3–5 values for exactly one supported parameter:

| Parameter | Unit |
|---|---|
| `quantity` | Execution policy quantity unit |
| `entry_expiry` | Seconds |
| `holding_interval` | Seconds |
| `exit_expiry` | Seconds |

The grid includes the baseline and at least one lower and one higher value.
Every parameter scenario otherwise preserves the exact request, strategy,
market, timeframe, dataset, manifest, execution, and cost inputs. Separate
cost-stress scenarios apply fee, spread, and slippage multipliers of `1.25`,
`1.5`, `2`, and `3` to baseline assumptions; no parameter/cost Cartesian
product is generated. Including the baseline, the maximum scenario count is
nine.

Every scenario reports the C-094 after-cost cumulative return (ratio), maximum
fractional drawdown (ratio), and total trades (count), with exact backtest and
metrics-report identities, content digests, policy, assumptions, and
timestamps. Deterministic Decimal deltas describe return/drawdown degradation,
strict isolated local return peaks, and tested crossings of cumulative return
through zero. All tested points are retained; no point is selected as optimal.

## Evidence states and boundaries

Each archived replay and C-094 report must resolve and recompute from exact
inputs. Scenarios must share the exact market/data/time window, strategy
version, and unvaried policy. Altered, mismatched, non-Spot, stale, expired, or
non-point-in-time provenance is `FAILED`; missing or insufficient metrics are
`INCONCLUSIVE`.

C-073v2 is immutable and content/identity-bound. C-073v1 and its consumers
remain unchanged, unknown versions fail closed, and lineage retention is denied.
The result is not accepted by C-030 or qualification and does not affect
strategy status, learning, risk, approval, or execution.

This is conditional evidence for the tested dataset and policy only. It is not
out-of-sample or future-performance proof, does not claim profitability, and
does not complete the Phase 1 Futures obligation. Synthetic fixtures validate
implementation behavior only; they are not market or performance claims.
