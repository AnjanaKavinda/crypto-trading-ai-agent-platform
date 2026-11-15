# ADR-0029: Validation freshness assessment boundary

## Metadata

| Field | Value |
|---|---|
| Status | Accepted |
| Date | 2026-11-15 |
| Decision owner | AnjanaKavinda |
| Human approver | Owner Execution Packet for issue #102 |
| GitHub issue / PR | #102 / implementation PR pending |
| Open decision ID | — |
| Related ADRs | ADR-0015, ADR-0020, ADR-0028 |
| Supersedes / superseded by | — |

## Decision

Add C-106 schema 1 as an immutable, deterministic, observation-only freshness
assessment for the exact supplied C-028v2 result and exact C-024v2 package. The
caller supplies both the typed current identity snapshot and timezone-aware
`as_of`; the evaluator does not resolve latest/global state, fetch artifacts,
or treat unbound caller assertions as verified evidence. The snapshot is an
explicit comparison input, not authentication of external truth or proof of
global/complete change history; C-106 computes comparisons rather than accepting
caller-supplied match or status assertions.

C-106 validates the C-028/C-024 source digests and their cross-bindings, then
compares the explicit current candidate, strategy, package, data-quality,
dataset, cost, methodology, rule-set, market-context, regime-validation, and
code-build references by artifact identity, schema, and content digest. It also
compares explicit asset, instrument, timeframe, and regime scope values with
the scope bound to C-028. Missing or uncomparable required current evidence
takes precedence as `INCONCLUSIVE`; otherwise explicit mismatches are `STALE`;
otherwise reaching any declared source, gate, package, or result expiry is
`EXPIRED`; otherwise the observation is `CURRENT`. Expiry uses existing declared
timestamps only and is inclusive at the boundary.

The original C-028 outcome and gate evidence are preserved. `FAIL` and
`INSUFFICIENT_VALIDATION` cannot be upgraded. `CURRENT_FOR_GOVERNANCE_REVIEW`
requires both original C-028 `PASS` and C-106 `CURRENT`; it is not production
eligibility, approval, activation, readiness, or execution authority.
Performance decay is always `NOT_ASSESSED` with an explicit reason; no rolling
metric or `StrategyDecayState` is calculated.

## Compatibility and boundaries

- C-028v2, C-024v2, C-025v2, C-105v1, and ADR-0028 remain unchanged.
- C-106 is on-demand only. The lineage codec has closed C-106 schema-1 support
  for deterministic inspection, while lineage retention is rejected.
- A code-build identity is accepted only from an explicitly typed
  `CODE_BUILD` reference already bound into the exact supplied C-028/C-024
  source closure. No methodology/runtime substitution is permitted. If absent,
  freshness is `INCONCLUSIVE`.
- No migrations, DDL, persistence, API, scheduler, global registry, or
  qualification/strategy/risk/approval/execution integration is introduced.

## Traceability

This boundary follows Master Playbook v2.2 Chat 7 and the existing C-024v2 /
C-028v2 contract bindings. It introduces no statistical claim and does not
recompute validation metrics. The owner Execution Packet for issue #102 is the
bounded implementation authorization; independent review and manual owner
merge remain required.
