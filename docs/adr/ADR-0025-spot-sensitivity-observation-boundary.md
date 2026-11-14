# ADR-0025: Spot sensitivity observation boundary

## Metadata

| Field | Value |
|---|---|
| Status | Accepted |
| Date | 2026-11-14 |
| Decision owner | AnjanaKavinda |
| Human approver | AnjanaKavinda (owner-assigned issue #98 Execution Packet) |
| GitHub issue / PR | #98 |
| Open decision ID | — |
| Related ADRs | ADR-0015, ADR-0019, ADR-0024 |
| Supersedes / superseded by | — |

## Context

Issue #98 requires deterministic, offline sensitivity evidence for one exact
archive-bound Spot backtest. C-073v1 already exists and has established
consumers; its payload, identity, and consumers must remain unchanged.

## Alternatives

### Option A — Add an observation-only C-073 schema 2

Preserves v1 compatibility while binding every scenario to its exact backtest,
metrics report, policy, parameter/cost assumptions, and provenance.

### Option B — Extend C-073v1 or integrate sensitivity with qualification

Would reinterpret existing payloads or introduce qualification authority beyond
the bounded issue scope.

## Decision

Use an additive, immutable C-073 schema 2 for deterministic Spot sensitivity
observations. The offline producer reuses the C-027v3 Spot replay and C-094
metrics pipeline. C-073v1 and its consumers remain unchanged.

The analysis varies exactly one supported Spot parameter over a frozen,
increasing 3–5 point grid containing the baseline and values on both sides.
Quantity uses the execution policy's quantity unit; timing parameters use
seconds. Four independent cost scenarios increase fee, spread, and slippage
together by 25%, 50%, 100%, and 200% from baseline assumptions. Cost and
parameter variations are not combined. The total is at most nine scenarios.

Every scenario reports after-cost cumulative return (ratio), maximum fractional
drawdown (ratio), and total trades (count), or an explicit inconclusive state
when the exact C-094 metric policy's sample sufficiency is not met. Decimal
arithmetic computes deltas, observed degradation, strict isolated local peaks,
and tested crossings through zero. These are descriptive observations; they do
not select or optimize parameters or qualify a strategy.

## Reasoning

The schema-2 result binds exact archive-pinned C-027v3 replays, recomputed C-094
reports, the shared market/data/time window, strategy version, unvaried policy,
parameter grid, cost multipliers, metric policy, timestamps, state, and reasons.
Its immutable identity derives from canonical content. Invalid, stale,
non-Spot, altered, or mismatched provenance is FAILED; missing or insufficient
metrics is INCONCLUSIVE.

## Consequences

The result is conditional evidence for the tested dataset and frozen policy,
not out-of-sample, future-performance, or profitability evidence. This Spot-only
slice does not satisfy the Phase 1 Futures obligation. No provider, API/UI,
credential, order, exchange, storage, qualification, strategy status, learning,
risk, approval, or execution path is added.

## Contract and traceability impact

| Area | References and impact |
|---|---|
| Playbook requirements | Deterministic analysis, evidence provenance, and explicit limits on statistical claims. |
| Cross-cutting artifacts | C-073v2 is registered; C-073v1 remains unchanged. |
| Contracts / events | Additive C-073 schema 2; exact C-027v3 and C-094 scenario references. |
| Requirements traceability | Issue #98 and `docs/architecture/issue-96-spot-sensitivity.md`. |
| Versioning / migration | Closed schema dispatch; unknown versions fail closed. No migration or DDL. |

## Safety, security, and failure behavior

This is offline research-only analysis. It creates no live-trading capability,
credential use, risk decision, approval, execution, or durable retention
authority. Invalid provenance fails; unavailable or insufficient metrics remain
inconclusive. C-073v2 is not accepted by C-030 or qualification consumers and
cannot be retained by the lineage store.

## Approval record

The repository owner authorized this bounded profile and additive C-073 schema
2 through the owner-authored Execution Packet for issue #98 on 2026-11-14.
