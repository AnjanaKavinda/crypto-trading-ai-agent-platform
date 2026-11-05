# ADR-0019: Deterministic internal backtest execution engine

## Metadata

| Field | Value |
|---|---|
| Status | Proposed |
| Date | 2026-11-05 |
| Decision owner | Platform Architect |
| Human approver | Pending owner merge |
| GitHub issue / PR | #92; architecture preflight |
| Open decision ID | OD-0011 |
| Related ADRs | ADR-0017, ADR-0018 |
| Supersedes / superseded by | — |

## Context

Issue #92 requires a deterministic backtest execution model with explicit order
timing, fill assumptions, liquidity/capacity, partial fills, fees, slippage,
funding, spread, latency, token/venue events, and deterministic seeds without
future-data leakage.

The platform's Phase 1 purpose is evidence-quality personal Spot and Futures
research. Backtest results must therefore be reproducible from exact dataset,
strategy, method, cost-model, and execution-model versions. A third-party
backtesting framework may be useful for exploratory analysis, but its internal
fill/order semantics cannot become an opaque source of truth for canonical
validation evidence.

## Decision

Adopt a repository-owned deterministic event/execution simulation kernel as the
authoritative backtesting engine for #92 and downstream validation.

The canonical engine will:

- consume immutable point-in-time dataset versions from #91;
- consume exact strategy/version references;
- consume versioned execution-cost assumptions from #93;
- use explicit event-time ordering and deterministic seeds;
- prohibit same-bar future information unless the execution rule explicitly
  proves the information was available at the simulated decision time;
- model order intent, eligibility, simulated submission time, fill eligibility,
  partial fills, cancellations/expiry, and final simulated fills as separate
  deterministic records;
- model Spot and Futures execution semantics separately;
- treat funding, fees, spread, slippage and latency as explicit inputs rather
  than hidden defaults;
- keep liquidity/capacity assumptions explicit and fail closed when required
  market evidence is unavailable;
- preserve exact provenance for every simulated fill and performance result;
- emit no live order, exchange request, credential access, approval or execution
  authority.

The engine is a validation simulator only. It is not the live/paper execution
service.

## Third-party libraries

No third-party backtesting engine is the canonical execution authority.

Libraries such as VectorBT may be used later as optional offline research or
cross-check tooling, provided:

- their outputs are not treated as canonical evidence without reconciliation;
- licensing is compatible with the intended use;
- their assumptions are explicitly mapped to the platform's frozen execution
  model;
- they cannot silently override platform fill, timing, cost, or point-in-time
  rules.

This avoids coupling validation correctness to a library's implicit defaults or
future version changes.

## Deterministic execution model

For every simulated decision, the engine must bind:

- dataset version ID and checksum;
- strategy ID/version/digest;
- signal/candidate or NO_TRADE reference where applicable;
- execution-model version;
- cost-model version;
- venue/market/instrument;
- decision time;
- information-availability cutoff;
- order type and side;
- requested quantity/notional;
- fill rule;
- latency assumption;
- spread/slippage rule;
- fee tier;
- Futures funding rule where applicable;
- deterministic seed when stochastic stress simulation is explicitly enabled.

A canonical replay with the same exact inputs must produce the same result.

## Fill timing

The default conservative rule is next-eligible-event execution. A signal derived
from a bar close cannot fill at that same close unless the strategy and dataset
prove the required decision inputs were available before the fill event.

Same-timestamp ambiguity must fail closed or be resolved by an explicitly
versioned event-priority rule.

## Liquidity and partial fills

The engine must not assume infinite liquidity by default.

Capacity/liquidity behavior must be represented by an explicit policy. If no
approved liquidity evidence exists for a strategy that requires it, validation
is INCONCLUSIVE rather than silently assuming full fills.

Partial fills are first-class simulated records. Remaining quantity may carry,
expire, or cancel only under the configured deterministic order policy.

## Spot vs Futures

Spot and Futures share the simulation framework but not market semantics.

Futures additionally require explicit:

- contract specification;
- multiplier/quantity units;
- funding interval and funding reference;
- mark/index/last-price semantics where applicable;
- leverage/margin assumptions only after the relevant risk contracts are
  approved;
- liquidation modeling only after the later deterministic risk scope exists.

Until those inputs are approved, Futures simulations must report unavailable or
inconclusive rather than reuse Spot assumptions.

## Failure behavior

Fail closed for:

- missing or non-point-in-time-safe data;
- future leakage;
- unknown dataset or strategy version;
- unresolved cost model;
- unsupported order semantics;
- ambiguous units;
- invalid event ordering;
- missing required liquidity/funding inputs;
- non-deterministic replay.

No zero-fee, zero-slippage, zero-funding, infinite-liquidity, or zero-latency
assumption may be silently substituted.

## Compatibility

This decision does not require changing existing strategy/signal contracts.
#92 should introduce only the validation-domain records required to represent
simulation inputs/results. Shared-contract changes require their own versioned
proposal.

#94/#95 and later validation consumers must consume exact backtest-result
versions, not mutable "latest" simulations.

## Implementation order

1. Complete #90 and the Wave 4 checkpoint.
2. Implement #91 immutable point-in-time datasets.
3. Accept this ADR and resolve OD-0011.
4. Refine #92 against #91 and #93 contract boundaries.
5. Implement the internal deterministic execution kernel.
6. Implement/version #93 cost models and bind them to simulations.
7. Run #94 metrics and #95 OOS validation on exact simulation artifacts.

#93 may define its contracts in parallel where doing so does not create a
circular dependency, but performance claims require exact cost-bound simulation.

## Validation requirements

#92 must include deterministic tests for:

- no look-ahead;
- next-event timing;
- same-timestamp ambiguity;
- exact replay;
- partial fills;
- insufficient liquidity;
- order expiry/cancellation;
- fee/slippage/spread/latency hooks;
- Futures funding hooks without silently enabling Futures runtime;
- malformed/missing data;
- unsupported order types;
- explicit unavailable/inconclusive outcomes.

## Security and safety

This ADR adds no exchange connectivity, credentials, approval, risk bypass,
paper/testnet trading, or live execution. It defines only an offline/research
simulation authority for validation evidence.

## Approval

Proposed under the delegated architecture authority for the PERSONAL_SPOT_RESEARCH
and future PERSONAL_FUTURES_RESEARCH validation path. It becomes the accepted
resolution of OD-0011 only when the repository owner merges the associated PR.
