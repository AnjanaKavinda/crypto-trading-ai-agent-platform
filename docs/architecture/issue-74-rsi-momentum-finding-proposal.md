# Issue #74 RSI momentum finding methodology proposal

## Status

This is a review proposal for one bounded PERSONAL_SPOT_RESEARCH lane. It does
not approve or implement a calculator-to-SpotMetaFinding adapter, change a
shared C-### contract, or complete Issue #74. Adapter code remains blocked until
this method is accepted and its exact lineage inputs are available.

## Why RSI14 is the candidate

The existing deterministic RSI calculator uses Wilder RSI with an arithmetic
mean seed, defaults to period 14, records indicator metadata and calculation
versions, and exposes READY, WARMUP, and UNDEFINED point states. It consumes
validated Spot OHLCV. This makes it a narrower first proposal than translating
prose or combining multiple indicators.

RSI is calculated from the same Spot OHLCV snapshot as other current analysis.
The lane must not be called an independent confirmation. C-093 must receive the
finding and preserve any observed shared binding, observations, sources, and
window overlap. Statistical independence remains unestablished.

## Proposed semantic mapping for review

The following is a proposed descriptive rule, not an approved trading signal:

| RSI14 value | Proposed direction |
|---|---|
| Greater than 50 | BULLISH |
| Less than 50 | BEARISH |
| Exactly 50 | NEUTRAL |

The threshold at 50 is the only proposed directional threshold. The adapter
must not add 30/70 overbought or oversold thresholds, persistence rules, price
targets, or trade conclusions in this slice.

For the relation to the exact resolved C-005 regime direction:

- Same bullish/bearish direction: SUPPORTING.
- Opposite bullish/bearish direction: CONTRADICTING.
- If either direction is neutral, mixed, or unknown: NEUTRAL.

The mapping must use typed enum values and must never parse an explanation,
label, or API prose.

## Readiness and strength

The RSI calculation does not estimate calibrated evidence strength. Therefore,
a finding produced under this proposal must use evidence strength UNKNOWN and
readiness PARTIAL. This explicitly prevents the current confluence calculator
from presenting it as a complete evidence-strength-bearing result. The adapter
must not upgrade it to READY or invent a strength from RSI distance to 50.

If the product later wants a usable strength scale or a READY finding, that
requires a separate methodology decision backed by validation evidence.

## Exact lineage gate

A production adapter may emit the proposed PARTIAL finding only when it can
resolve all of the following to the same validated analysis scope:

- Exact RSI14 point, candle cutoff, instrument, timeframe, and price unit.
- RSI metadata and calculation versions.
- Exact C-008 evidence IDs for the RSI observation and their resolved quality
  report and source lineage.
- Exact C-007 binding ID covering the same snapshot, quality report, and C-005
  regime.
- The existing C-005 regime direction used for the relation comparison.

The current RSISeries carries snapshot, quality report, cutoff, input market
data IDs, parameters, metadata version, and calculation version. Those fields
alone are not substitutes for C-008 evidence IDs or a resolved C-007 binding.
If the exact C-008 evidence and matching C-007 binding cannot be resolved, the
task must return UNAVAILABLE with INPUT_UNAVAILABLE. It must not manufacture
evidence IDs or bindings from the RSI output.

The finding method must pin a new explicit adapter-method version and also
retain the RSI metadata/calculation versions in provenance. Its stable identity
must be derived from the exact analysis scope and RSI method inputs so replay
does not create duplicate findings.

## Unavailable and failure behavior

- WARMUP point: UNAVAILABLE / INSUFFICIENT_WARMUP.
- UNDEFINED point: UNAVAILABLE / INPUT_UNAVAILABLE.
- Missing or mismatched C-008/C-007 lineage: UNAVAILABLE / INPUT_UNAVAILABLE.
- Stale input: UNAVAILABLE / STALE_INPUT.
- Invalid or inconsistent scope: task failure / INVALID_INPUT.
- Timeout and unexpected exceptions retain the existing bounded timeout/failure
  outcomes.

No unavailable case may become a neutral or directional finding.

## Explicit review decisions

Before implementation, confirm or revise:

1. Whether RSI14 above/below/exactly 50 should map to bullish/bearish/neutral
   context.
2. Whether relation should compare against the resolved C-005 regime as
   described.
3. Whether PARTIAL readiness with UNKNOWN strength is the right safe first
   output, with confluence remaining indeterminate.
4. Whether the exact C-008 evidence and C-007 binding gate is sufficient for
   this lane.

No strategy, signal, confidence score, risk decision, approval, order,
execution, or live-trading behavior is proposed.
