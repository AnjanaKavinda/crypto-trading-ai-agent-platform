# Issue #74 Spot finding adapter boundary

## Status

Implementation boundary proposal for the owner-approved
`PERSONAL_SPOT_RESEARCH` path. This document does not approve a methodology,
change a C-### contract, or complete Issue #74.

## Current repository state

- PR #399 added a bounded runner for caller-supplied local operations that
  already return a typed `SpotMetaFinding`.
- The runtime agent registry contains one `PERSONAL_SPOT_RESEARCH` agent. It
  does not register separate trend, momentum, volatility, or other domain
  agents.
- Existing Spot calculators and API projections expose typed observations and
  explicit availability states. There is no production adapter that maps those
  outputs to `SpotMetaFinding`.
- `SpotMetaFinding` requires semantic direction, relation, evidence strength,
  readiness, and (for ready findings) exact evidence, binding, and method
  provenance. Choosing these semantic values from raw calculator outputs is a
  methodology decision, not a transport operation.

## Proposed adapter rule

An adapter may construct a `SpotMetaFinding` only when an existing, versioned
calculator or a separately approved methodology explicitly supplies every
semantic field. The adapter must not infer bullish/bearish direction, strength,
materiality, pivots, thresholds, support/resistance, or a trading conclusion
from a descriptive value or label.

For any missing, partial, warm-up, stale, invalid, or policy-dependent result,
the fan-out outcome must preserve an explicit non-success status and a bounded
reason code. It must not manufacture a ready finding with neutral or unknown
values merely to make the task appear complete. The current fan-out result
shape has `FAILED` and `TIMED_OUT` outcomes but no distinct `UNAVAILABLE`
outcome/reason field; add that internal status before wiring unavailable
calculator results into the runner.

Every ready finding must retain the exact C-008 evidence IDs, C-007 binding ID,
method/version, and validated Spot scope. Feed the resulting findings to C-093
before confluence interpretation. For this profile, C-093 may report observed
shared inputs and must continue to leave statistical independence unestablished.

## Candidate task lanes

The names below identify existing analytical areas, not approved independent
agents or evidence streams.

| Candidate lane | Existing source | Adapter status |
|---|---|---|
| Market regime | Resolved C-005 regime on the exact C-007 binding | Already included by the C-093 path; do not duplicate it as a finding. |
| Trend / momentum / volatility | Existing deterministic indicator and regime calculations over the same validated Spot OHLCV snapshot | No approved conversion from calculator outputs to `SpotMetaFinding` semantics. |
| Volume / VWAP / volume profile | Existing Spot OHLCV analyses and their API projections | Preserve each backend status and provenance; no approved directional-finding adapter. |
| Price action / market structure | Existing calculators; some results depend on caller policy or pivot context | Keep unavailable when required policy/context is absent; do not infer patterns, pivots, or levels. |
| Fibonacci / SMC / Wyckoff | Existing bounded calculators where inputs and policy are available | No approved adapter mapping to `SpotMetaFinding`; do not promote labels to directional evidence. |

These lanes share one validated OHLCV scope. Distinct lane names, methods, or
calculators do not make the outputs independent. If all lanes use the same
snapshot, quality report, and source records, that shared lineage must be
preserved for C-093 to identify observed dependence.

## Recommended implementation order

1. Extend the internal fan-out outcome with an explicit unavailable state and
   bounded reason code; test partial success and unavailable results without
   erasing successful findings.
2. Add adapters only for outputs whose existing calculator already defines the
   required semantics and exact provenance. Keep unsupported mappings
   unavailable.
3. Run C-093 over the exact findings and bindings, and retain its limitations
   in downstream results. Do not convert lane count into a vote, confidence, or
   independence score.
4. Consider separate model-backed domain agents only after their identities,
   permissions, inputs, output schemas, and invocation/idempotency/cost/replay
   behavior are explicitly approved. The current single-agent profile does not
   authorize that dispatch.

No shared contract or Master Playbook change is proposed here. If implementation
needs a shared result schema or a new semantic mapping, stop and submit that
specific contract/methodology proposal before coding it.
