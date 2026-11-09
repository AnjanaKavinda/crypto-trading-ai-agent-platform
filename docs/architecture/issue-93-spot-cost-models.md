# Issue #93 — bounded Spot execution-cost models

## Scope and authority

This implementation provides configured, versioned Spot cost assumptions for
`PERSONAL_SPOT_RESEARCH` and a pure `ExecutionCostAdapter` for the #92 scenario
kernel. It uses C-027v2 and preserves C-027v1, C-027v3, C-028v2, and accepted
ADR-0019. It does not publish backtest results, qualify a strategy, or grant risk,
approval, or execution authority.

The only supported source kind is
`CONFIGURED_RESEARCH_ASSUMPTION`. A profile's source reference and methodology
identify the provenance of those inputs, but do not claim that fee tiers or
market costs were verified against an exchange feed.

## Profile and identity

`SpotExecutionCostProfile` is immutable and binds:

- venue, Spot instrument, base asset, price unit, and quantity unit;
- fee tier, explicit maker and taker fee basis points;
- full quoted spread, adverse slippage, stress multiplier, and latency in bars;
- versioned source reference, source kind, and methodology version;
- `available_at`, `effective_from`, and `valid_until`.

The canonical profile digest includes all of these fields. C-027v2 assumption
sets bind that profile reference to an exact strategy version and asset. Their
IDs are deterministic UUIDv5 values derived from the canonical immutable input;
no wall clock or generated random identity is used.

Fees, spread, and slippage must be explicit, finite, positive, and within the
bounded Decimal input range. Latency may be zero only as an explicit configured
value; it has no implicit default. Spot funding is required and marked
`NOT_APPLICABLE` with no numeric value. Missing, unknown, unsupported, or invalid
inputs are unavailable, never substituted with zero.

## Cost interpretation

The profile's spread is the full quoted spread in basis points. The C-027v2
spread assumption retains that full-spread value (after stress), while the
adverse per-fill charge uses half of it. Slippage is charged in full after the
stress multiplier. The selected fee is applied to gross quote-currency notional;
fees are not stress-multiplied. This bounded model does not infer a fee currency
different from the configured quote unit.

Maker and taker rates remain explicit profile metadata. The production adapter
uses the conservative TAKER rate for all supported order kinds, including
LIMIT; order type alone does not establish a maker fill. Maker fee calculations
are available only as explicit research arithmetic and are not emitted by this
kernel adapter.

All monetary operations use a fixed local 120-digit Decimal context with
`ROUND_HALF_EVEN`, independent of ambient Decimal settings. Inputs and outputs
are finite and bounded.

## Time, request binding, and failure behavior

The adapter requires the profile to have been available by the order decision
time and effective over the actual allocation interval
`[bar_start, bar_end)`. The interval end may equal `valid_until`; the fill's
later `observed_at`/availability timestamp does not redefine the interval.
The internal request also binds the exact source-revision ID and canonical
digest for the bar.

Before quoting, the adapter verifies exact venue, instrument, asset, units,
latency, strategy-bound C-027v2 identity, profile/model digest, and requested
time. It prices the actual fill quantity multiplied by the gross fill price.
The returned quote binds the canonical digest of the complete request,
assumption-set ID/digest, and deterministic adapter reference. Adapter identity
itself binds the exact profile and assumption-set digests.

Missing/stale/future-unavailable profiles, mismatched scope or costs, invalid
intervals, unsupported applicability, malformed provenance, and non-finite or
out-of-range values fail closed as an inconclusive simulation. The adapter is
pure, local, and read-only; it does not access providers, exchanges, credentials,
or mutable latest-version selectors.

## Verification and limitations

Tests use explicitly synthetic Spot cost profiles and synthetic historical
dataset fixtures. They cover maker/taker metadata, spread convention, stress,
slippage, latency, deterministic arithmetic and identities across Decimal
contexts, temporal boundaries, request/revision binding, scope mismatches, and
dataset-loader → #92 kernel → production adapter integration with partial fills.

Local verification on the implementation tree: focused tests **75 passed / 1
skipped**; full backend **1,829 passed / 89 skipped** without a database;
production-adapter PostgreSQL read-only replay **1 passed** with a disposable
database; Ruff, formatting, mypy, wheel build, dependency check, Product CI
workflow-contract tests, Governance CI tests, and secret scan passed. Skips are
not counted as passes.

This work does not implement Futures funding, exchange fee ingestion, historical
strategy replay, trace closure, C-027v3 publication, metrics, OOS, or walk-forward
validation. Those remain separate issue scopes (#92, #94, and #95 as applicable).
No profitability, qualification, or production-readiness claim follows from
these models or synthetic tests.
