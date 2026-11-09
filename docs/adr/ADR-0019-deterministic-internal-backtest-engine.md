# ADR-0019: Deterministic internal backtest execution engine

## Metadata

| Field | Value |
|---|---|
| Status | Proposed |
| Date | 2026-11-05 |
| Decision owner | Platform Architect |
| Human approver | Pending owner merge |
| GitHub issue / PR | #92 / #446; refreshed after #447 |
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

This decision does not change existing strategy/signal contracts. It also
proposes the additive C-027 schema-3 boundary below for owner review; no code or
schema dispatch is introduced by this documentation PR.

### Proposed C-027 schema 3 — BacktestResultV3

The compatibility audit found that C-027v1 `BacktestResult` embeds
`ReproducibilityContext` with numeric `ResearchAssumption` values. The current
C-027v2 `CostAssumptionSetV2` instead requires explicit `NOT_APPLICABLE` Spot
funding. Converting that state into a v1 numeric funding assumption would invent
an input and discard applicability semantics. These versions must remain intact.

Propose additive **C-027 schema 3 `BacktestResultV3`**, preserving:

| Schema | Meaning and compatibility |
|---|---|
| 1 | Historical BacktestResult and its existing numeric assumptions; unchanged. |
| 2 | CostAssumptionSetV2 and typed cost applicability; unchanged. |
| 3 (proposed) | BacktestResult binding exact versioned data, strategy, typed costs and simulation provenance. No reinterpretation of schemas 1 or 2. |

The schema-3 result must bind at minimum:

- exact C-021 schema/version/identity/content digest and immutable parameters;
- exact C-092 dataset ID/version/canonical digest and C-103 canonical digest,
  preserving #91's dataset coverage, cutoff, historical universe, ordered
  constituents, source hashes and revision ancestry;
- exact C-027v2 assumption-set identity/content digest, including its strategy,
  asset and market bindings; Spot funding stays `NOT_APPLICABLE`;
- immutable simulator/execution-model/configuration identities and versions,
  explicit event-priority, latency, capacity and intrabar policies, and an
  explicit deterministic seed policy;
- simulated period, decision-time availability rules and exact trace/fill/trade
  references with canonical content digests;
- reproducible observed metrics and their method versions when present, explicit
  sample counts, data-integrity/point-in-time outcomes and failure/warning state;
- creation/as-of/validity timestamps and environment/research-mode identity.

Result identity is deterministic UUIDv5 from the canonical immutable result
content digest under a fixed, versioned method namespace. The content-hash
preimage omits both the generated result ID and its own digest to avoid circular
hashing. Timestamps are explicit pinned inputs, never a fresh wall-clock value
inserted during replay. Method/namespace/preimage rules must be frozen with the
schema implementation and covered by canonical compatibility tests.

This is not a new qualification result: C-028v2 and the mandatory sample, OOS,
walk-forward, robustness, regime, cost and freshness requirements are unchanged.
Observed simulator output cannot grant statistical qualification by itself.
Missing or unverifiable inputs cannot produce a successful canonical result;
return an explicit failed/inconclusive state without fabricated references or
statistics. #94 owns metric formulas and #95 owns OOS partition semantics.

Implementation must use closed `(contract_id, schema_version)` dispatch, reject
unsupported versions, and preserve old serialized payloads and identifiers.
Schema-1/2-only readers must reject schema 3 rather than down-convert. Add
compatibility and digest/reference tests before exposing the new result to
consumers. No historical migration, rewrite, dependency installation or retained
database change is authorized by accepting this ADR alone. If durable storage
requires DDL, submit a separate reviewed migration before using it.

#94/#95 and later validation consumers must consume exact backtest-result
versions, not mutable "latest" simulations.

## Implementation order

1. Complete #90 and the Wave 4 checkpoint (verified after #466).
2. Implement #91 immutable point-in-time datasets (#447 merged; verified base
   `fd4b31db16cda17e21648a5504d694793ca05f60`).
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

PR #446 originally used ADR-0018 for this proposal. That number is now occupied
by accepted development-governance architecture; this refresh consolidates the
backtest proposal into ADR-0019 and removes the unmerged duplicate. The accepted
ADR-0018 is not changed or superseded.

The owner is asked to approve both the repository-owned engine choice and the
additive C-027v3 contract boundary. This ADR remains Proposed until explicit owner
approval/merge of #446; that merge constitutes acceptance of both decisions and
resolution of OD-0011. Record Accepted/Resolved metadata and the exact approving
merge in the subsequent implementation refinement before runtime edits.

The initial runtime remains PERSONAL_SPOT_RESEARCH. Future Futures research must
first satisfy #39 data and #61 analysis plus its own scoped simulation contracts;
accepting this proposal does not authorize Futures delivery or trading execution.
