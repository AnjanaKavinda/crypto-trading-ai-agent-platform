# ADR-0018: Deterministic platform-owned backtest simulation kernel

## Metadata

| Field | Value |
|---|---|
| Status | Proposed |
| Date | 2026-11-05 |
| Decision owner | Platform Architect |
| Human approver | Pending |
| GitHub issue / PR | #92; OD-0011 decision PR |
| Open decision ID | OD-0011 |
| Related ADRs | ADR-0003, ADR-0005, ADR-0015, ADR-0017 |
| Supersedes / superseded by | — |

## Context

Issue #92 requires a deterministic backtest execution model after the Wave 4
strategy/lifecycle/API chain is complete. The live issue is explicitly blocked
by OD-0011, which reserves the backtesting-engine implementation choice for the
human repository owner.

Chat 7 requires point-in-time-correct strategy replay, deterministic simulation,
explicit order timing and fill assumptions, intrabar ambiguity handling,
liquidity/capacity constraints, partial fills, realistic costs, deterministic
seeds, and exact versioned provenance. The current Python backend has no
backtesting-engine dependency and already owns the contracts, point-in-time
data, strategy semantics, cost assumptions, validation gates, and provenance
that the simulator must consume.

The initial implementation target is the single-user
`PERSONAL_SPOT_RESEARCH` profile. It is research-only and does not submit
orders, connect to exchange trading APIs, or grant execution authority.

## Alternatives

### Option A — Platform-owned deterministic simulation kernel behind a narrow adapter

Implement a small event/bar simulation kernel inside the backend. The kernel is
driven only by exact versioned historical inputs and approved execution-model
configuration. It emits platform C-027/backtest artifacts and supporting typed
simulation records. Keep the public boundary narrow so a future alternative
engine can implement the same adapter without changing Chat 7 contracts.

Benefits:

- complete control over point-in-time and no-look-ahead semantics;
- deterministic ordering, seeds, fills, and intrabar policy are testable in the
  repository;
- no hidden third-party fill/cost defaults;
- no new heavy runtime dependency for the personal research profile;
- exact integration with C-021/C-023/C-027/C-028/C-071 and C-092 provenance;
- easiest path to fail closed when required history or cost evidence is absent.

Costs, risks, and constraints:

- the project owns implementation and maintenance;
- the initial simulator is intentionally narrower than mature external engines;
- additional order types, tick/depth simulation, derivatives, and portfolio
  simulation require later scoped extensions;
- correctness requires strong golden/replay/property tests.

### Option B — Backtrader as the authoritative engine

Benefits:

- mature event-driven framework and common order concepts;
- substantial existing community examples.

Costs, risks, and constraints:

- platform contracts would need translation into Backtrader semantics;
- engine defaults and lifecycle behavior can diverge from the exact Chat 7
  assumptions unless wrapped and independently verified;
- adds a dependency whose abstractions are broader than the bounded Personal
  Spot requirement;
- does not remove the need for custom point-in-time, provenance, cost, and
  validation controls.

### Option C — VectorBT as the authoritative engine

Benefits:

- efficient vectorized research and parameter sweeps;
- strong exploratory-analysis ergonomics.

Costs, risks, and constraints:

- vectorized execution is not the natural authority for explicit order timing,
  partial fills, latency, intrabar ambiguity, and event sequencing;
- high-throughput parameter search can increase overfitting risk unless tightly
  governed;
- still requires a custom deterministic execution layer for the #92 acceptance
  criteria.

### Option D — LEAN or another full external execution/backtest platform

Benefits:

- broad asset/order/simulation functionality.

Costs, risks, and constraints:

- significantly larger operational and dependency footprint;
- duplicates platform-owned strategy, data, provenance, and validation
  boundaries;
- unnecessary for the initial one-user Spot research slice;
- increases integration surface before the project has validated the bounded
  research workflow.

## Decision

Select **Option A**: use a platform-owned deterministic simulation kernel behind
a narrow engine adapter as the authoritative #92 implementation.

The first implementation is bounded to PERSONAL_SPOT_RESEARCH and exact
historical Spot inputs. The adapter boundary must make the engine replaceable
later without changing the simulation caller boundary.

The #92 implementation also requires an additive **C-027 schema 3
`BacktestResultV3`**. C-027v1 remains the historical BacktestResult and
C-027v2 remains the typed cost-assumption value-object boundary introduced for
PERSONAL_SPOT_RESEARCH qualification. Neither existing schema is reinterpreted.

C-027v3 returns to the canonical BacktestResult responsibility while binding
the newer exact inputs needed for truthful Spot simulation. It must reference,
at minimum:

- exact C-021v2 strategy/version provenance;
- exact C-092 dataset version and C-103 reconstruction manifest;
- exact C-027v2 CostAssumptionSetV2;
- immutable parameter/configuration references;
- immutable simulator/execution-model version and deterministic seed/policy;
- the exact simulated period and point-in-time cutoff;
- deterministic simulation trace/trade identities and aggregate metrics;
- explicit data-integrity and point-in-time outcomes;
- creation/as-of/validity timestamps and typed failure/warning state.

The C-027v3 result ID is deterministic UUIDv5 over the canonical immutable
payload with the generated ID omitted. Missing, stale, future-leaking,
unsupported, or unverifiable inputs prevent publication.

This schema-3 boundary is necessary because C-027v1's inline numeric
`ResearchAssumption` model cannot truthfully represent the C-027v2
`NOT_APPLICABLE` Spot-funding state without inventing a numeric funding
value. #92 must not coerce C-027v2 cost semantics back into v1.

This ADR remains `Proposed` until the human repository owner approves it.
No #92 implementation may rely on this selection or C-027v3 contract decision
before approval.

## Reasoning

The decisive requirement is not feature breadth; it is reproducibility and
truthful validation. Chat 7 requires the simulator to prove exactly what was
known, when a signal could act, how a fill was determined, which costs applied,
and how ambiguity was resolved. Those semantics are already governed by this
repository's contracts and point-in-time data model.

A small owned kernel keeps those semantics explicit and testable and avoids
importing a third-party engine's implicit execution assumptions. It also
matches the current budget and single-user scope while retaining an adapter
seam for future comparison or replacement.

External libraries may later be used as non-authoritative cross-checks or may
be proposed as alternate adapter implementations. They must not silently
become the source of truth for fills, costs, timestamps, or validation status.

## Consequences

After approval:

1. #91 must provide exact point-in-time C-092/reconstruction inputs.
2. #92 may implement the deterministic simulator and adapter.
3. #92 publishes C-027v3 results only from exact C-027v2 cost assumptions;
   Spot funding remains explicitly NOT_APPLICABLE without a fabricated numeric
   value.
4. #93 supplies versioned fee/slippage/spread/funding/latency assumptions.
5. #94 and later validation issues consume simulator outputs; they do not
   recalculate execution semantics.
6. #95 OOS partitions invoke the same deterministic simulator with frozen
   strategy/configuration inputs.

The first simulator must support the bounded Spot requirements actually used by
the profile and explicitly report unsupported features. It must not emulate
unsupported tick/depth/futures behavior from candle data.

A future engine replacement or second authoritative implementation requires a
new reviewed ADR or a superseding decision because changing execution semantics
can change historical results.

## Contract and traceability impact

| Area | References and impact |
|---|---|
| Playbook requirements | Chat 7 Sections 1–16: point-in-time data, deterministic replay, trade simulation, intrabar ambiguity, costs, slippage, funding, spread, latency. |
| Cross-cutting artifacts | Resolves OD-0011 after approval; Wave 5 plan may proceed through #92. |
| Contracts / events | Additive C-027 schema 3 `BacktestResultV3`; C-027v1 and C-027v2 remain unchanged. C-027v3 binds exact C-021v2, C-092, C-103 and C-027v2 cost-assumption references plus deterministic simulator provenance. C-028v2 qualification semantics remain unchanged. |
| Requirements traceability | #92 backtest execution model; supports downstream #93–#102. |
| Versioning / migration | C-027 schema 3 is additive and requires closed schema dispatch/compatibility tests; no historical rewrite. No database migration or third-party dependency is authorized by this ADR alone. Execution-model configuration and simulator version must be immutable/version-qualified in produced results. |

## Safety, security, and failure behavior

The simulator is research-only. It has no exchange credentials, exchange order
submission, approval, portfolio-risk, or live execution capability.

Missing, stale, ambiguous, future-leaking, unsupported, or unverifiable inputs
must fail closed. Zero costs, perfect fills, favorable intrabar ordering, or
synthetic missing history must never be silently assumed.

If this ADR is not approved, OD-0011 remains Open and #92 remains blocked.

## Approval record

Pending human repository-owner disposition. Approval should be recorded by
setting this ADR to `Accepted`, updating OD-0011 to `Resolved`, recording
the disposition date, and linking the approving PR.
