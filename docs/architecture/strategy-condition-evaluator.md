# PERSONAL_SPOT_RESEARCH strategy condition evaluator

Issue #80 adds a deterministic runtime evaluator for the existing frozen C-020
and C-021 contracts. It introduces no shared contract or persistence change.
The evaluator consumes one exact `ResolvedStrategyVersion` from the immutable
registry and a runtime-local view of validated Spot debate and fan-out outputs.
It rechecks the C-021 content hash, strategy/version identity, profile scope,
correlation/trace binding, and freshness before resolving features.

## Feature boundary

Feature paths are explicit allowlist entries. The resolver reads typed values
from C-006 schema 5, C-005 regime dimensions, C-009 confluence components, and
the typed Spot fan-out finding for RSI-14. The RSI value is accepted only when
its finding carries the approved adapter, RSI calculation, metadata, unit, and
component/evidence binding. Each condition result retains its source contract,
schema version, and exact method/provenance references. LLM text, arbitrary
feature paths, dynamic imports, reflection, and executable expressions are not
accepted.

Supported paths are:

- `market.asset`, `market.instrument_id`
- `market.regime.direction`
- `market.regime.dimension.trend.state`
- `market.regime.dimension.realized-volatility.state`
- `market.regime.dimension.transition.state`
- `spot.confluence.state`
- `spot.finding.<approved Spot domain>.direction`, `.relation`, or
  `.evidence_strength`
- `spot.momentum.rsi14.value`, when the exact validated RSI finding is present

Current Spot outputs do not provide an approved percentile distribution or the
exact previous/current ordered pair required by cross operators. Those four
operators return `UNKNOWN` with `UNSUPPORTED_OPERATOR`. Unknown, missing,
stale, or unavailable features remain `UNKNOWN`; absence is never inferred
from missing input. `ABSENT` can match only an explicit typed `ABSENT` state,
which the current Spot resolver does not synthesize.

Declared C-021 required evidence categories are checked against a closed
profile map: `technical` requires a present Spot analytical finding, `regime`
requires all allowlisted C-005 dimensions, and `confluence` requires the exact
C-009 state. Missing supported categories or an unknown category makes the
overall result `UNKNOWN`; downstream eligibility remains out of scope.

## Operator and group semantics

Categorical and typed scalar equality is exact. Numeric comparisons use finite
`Decimal` values and strict bounded decimal strings. `IN_RANGE` uses the closed
interval `[lower, upper]` and rejects reversed bounds. `PRESENT` passes only for
a present, available typed feature. Unsupported feature/operator combinations
fail closed.

Conditions use three-valued `PASS`, `FAIL`, and `UNKNOWN` results. `AND` is
unknown when any required child is unknown; `OR` passes only if at least one
child independently passes; `NOT` preserves unknown. C-021 currently has no
root group field, so its declared groups are combined conjunctively. A future
nested expression/root model requires an approved contract change.

The versioned DSL definition is `1`. Runtime bounds cap strategies at 64
conditions, 32 groups, 64 condition references per group, four expected values
per condition, and 256 characters per path/value. A limit violation returns an
unknown evaluation.

## Authority boundary

Evaluation reports only whether declared deterministic conditions passed,
failed, or remained unknown for this exact strategy version and Spot context.
It does not compute eligibility or qualification, emit C-023 or a signal,
approve risk or human action, or authorize paper, order, or live execution.
It produces no trading-performance statistics. Chat 7 remains the authority
for statistical validation.
