# Issue #99 — Spot regime validation observation boundary

## Scope and method

The offline producer consumes a frozen ordered plan of archive-bound C-027v3
Spot backtests and explicit C-094 `MetricsPolicy` values. Each run reuses the
existing Spot replay and computes C-094 metrics using that run's execution
dataset as the price path. Every request, strategy version, policy, cost model,
dataset, manifest, and timestamp remains bound to its exact digest and units.

The decision attribution is the decision producing the run's sole entry order.
If there is no entry order, the first pinned decision is used and marked
`NO_ENTRY_FIRST_DECISION`. The attributed C-005 state and C-008 evidence resolve
only from the verified archived C-006v5/C-007v4 closure. Scope, information
cutoff, availability, and expiry are checked at the historical decision time,
not against today's freshness.

The profile records the existing taxonomy only:

| Dimension | States |
|---|---|
| Trend | `bullish`, `bearish`, `mixed` |
| Realized volatility | `high`, `typical`, `low` |
| Transition | `possible`, `not-observed-in-lookback` |

`mixed` does not mean ranging; `possible` does not mean confirmed transition.
The profile's analytical confidence is uncalibrated and is not probability.

## Evidence and coverage

Every planned run is emitted in input order with exact request/result/trace and
metrics-report identities, policy, parameters, execution/cost/data provenance,
periods, timestamps, decision attribution, regime/evidence references, and
per-metric C-094 state, value, unit, sample count, warnings, and reason. A metric
that is available remains visible if another metric is unavailable.

Required contexts are emitted in plan order. Every observed non-required context
is also emitted in first-occurrence order. Context references identify matching
run observations only; their metric sample counts are not pooled. Overlapping or
reused windows are potentially dependent.

Invalid provenance is `FAILED`; missing required coverage, zero trades, or
insufficient/unavailable metric evidence is `INCONCLUSIVE`. `OBSERVED` means
complete descriptive evidence only. No pooled return/equity curve, summed
drawdown, profitability verdict, selection, optimization, or invented minimum
sample threshold is produced.

## Boundaries and limitations

C-074v2 is immutable and canonically content/identity-bound. The codec supports
only the explicit schema version; v1 remains unchanged and unknown versions
fail closed. C-074v2 is not accepted by C-030/C-028 qualification consumers and
cannot be retained by the lineage store.

This is `PERSONAL_SPOT_RESEARCH`, not full-platform completion, qualification,
OOS/robustness proof, or deployment eligibility. Futures, true ranging,
confirmed macro regimes, broad independent cross-asset evidence, and full
statistical qualification remain outside this slice.
