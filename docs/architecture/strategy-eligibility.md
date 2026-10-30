# PERSONAL_SPOT_RESEARCH strategy eligibility

Issue #81 adds a deterministic gate for whether an exact registered C-021
version may proceed to setup detection. It reuses C-020/C-021, the immutable
#79 registry, C-022, C-006 v5, C-007 v4, and the #80
`StrategyConditionEvaluation`. It creates no setup, C-023 candidate, signal,
qualification, statistical result, risk decision, approval, order, or execution
action.

## Provenance before C-022

The runtime requires the authoritative `AnalysisSnapshotV4` and its one
`ResolvedSpotOHLCVBindingV4`. It resolves the manifest again from the exact
snapshot, C-003 report, observations, sources, C-005 regime, and C-008 evidence
carried by that binding. The reconstructed resolution must equal the supplied
resolved binding.

Before emitting C-022, it also verifies that:

- C-006 references the exact C-007 snapshot ID, schema, and content digest;
- C-006 asset, instrument, context time, timeframe, evidence, and regime match
  C-007 and the resolved binding;
- C-009 and each C-010 (when present) bind to the same C-007 snapshot and exact
  C-003 report reference, and their C-007 output references match their digest;
- the C-003 reference ID, schema, lineage, and digest match the resolved report;
- C-003 is valid, not future-dated, and within the resolved dependency expiry.

The C-022 `data_quality_report_id` comes only from that verified C-003 report.
If any part of the chain is absent, stale, ambiguous, or mismatched, the
runtime-local `StrategyEligibilityEvaluation` returns `INSUFFICIENT_DATA` with
no C-022 object. It never substitutes an ID.

## Eligibility rules

The evaluator checks exact strategy/version/content-hash binding, registry
selectability, current C-021 lifecycle axes, supported asset/instrument/timeframe,
and explicit environment and operating mode. The PERSONAL_SPOT_RESEARCH path
requires Research mode. Invalid or suspended/deprecated lifecycle states return
`NOT_ELIGIBLE`; unsupported declared asset/instrument/timeframe/mode also
returns `NOT_ELIGIBLE`.

The current profile recognizes the C-005 dimensions `trend`,
`realized-volatility`, and `transition`, and their typed states as exposed by
#80. Required preferred/acceptable dimension names must be present. An
incompatible configured dimension that is present returns `NOT_ELIGIBLE`.
Unknown dimensions, unknown states, or unavailable required dimensions return
`INSUFFICIENT_DATA`; no other Spot or Futures regime semantics are inferred.

Condition truth is consumed, not recalculated. `PASS` may proceed only after all
other checks pass. `FAIL` returns `NOT_ELIGIBLE`. `UNKNOWN`, unsupported #80
operators/runtime cases, invalid evidence, stale input, or mismatched result
binding return `INSUFFICIENT_DATA`. The #80 evaluator remains authoritative for
feature provenance, evidence categories, typed comparisons, and three-valued
group behavior.

The C-022 expiry is the earliest context, regime, confluence, condition, and
resolved Spot dependency expiry. Eligibility IDs are deterministic for the
exact version, context, evaluation time, outcome, and reason codes.

## Authority boundary

`ELIGIBLE` means only that the strategy version may proceed to setup detection.
It does not imply qualification, profitability, risk approval, human approval,
or execution authority. `NOT_ELIGIBLE` and `INSUFFICIENT_DATA` block downstream
setup/candidate creation. This layer does not emit `NO_TRADE`; later layers own
that outcome. Chat 7 remains the authority for statistical validation.
