# ADR-0027: Spot bias audit observation boundary

## Metadata

| Field | Value |
|---|---|
| Status | Accepted |
| Date | 2026-11-15 |
| Decision owner | AnjanaKavinda |
| Human approver | Owner Execution Packet for issue #100 |
| GitHub issue / PR | #100 / implementation PR pending |
| Open decision ID | — |
| Related ADRs | ADR-0018, ADR-0019, ADR-0022, ADR-0023, ADR-0024, ADR-0025, ADR-0026 |
| Supersedes / superseded by | — |

## Decision

Preserve the C-094 schema-1 `BiasCheckReport` and its consumers. Add C-094 schema
2 as a deterministic, observation-only Spot bias audit over one exact
archive-backed C-027v3 replay. C-094v2 binds the exact replay request/result,
trace, C-021v2 strategy, C-092 dataset, C-101 universe, C-102 revisions,
C-103 manifest, C-091 source pins, method, and explicit timestamps through typed
references and native dataset/universe identities.

The producer may report point-in-time and look-ahead checks only after the
existing trusted replay and exact result resolver succeed. Each result contains
the nine C-094 check categories exactly once. Feature/target leakage,
normalization-parameter leakage, survivorship, selection, data snooping,
multiple testing, and universe methodology remain `INCONCLUSIVE` with explicit
unavailability reasons; this slice does not claim to verify them.

Canonical SHA-256 and UUIDv5 identities exclude the generated result ID and its
own digest. Missing replay evidence produces an inconclusive request-bound
result with no invented replay result, trace, or digest. Invalid pins,
mismatched provenance, and contradictory chronology fail closed.

## Consequences and boundaries

- C-094v1 and its consumers remain unchanged.
- C-094v2 is not accepted by `QualificationGateV2`, qualification, lineage
  retention, strategy status, learning, risk, approval, or execution.
- The lineage codec adds closed C-094 schema-2 support; C-094v1 codec behavior
  and readers are unchanged. The lineage store rejects schema-2 retention.
- The producer reuses only `run_spot_backtest` and
  `resolve_spot_backtest_result`. It introduces no replay engine, API, provider,
  scheduler, schema migration, DDL, or storage authority.
- A complete replay can still yield only `INCONCLUSIVE` because seven categories
  are deliberately unsupported. This is not a qualification verdict,
  profitability claim, or statistical probability.

## Traceability

The implementation follows Master Playbook v2.2 Chat 7 and ADR-0019's
deterministic replay boundary. It updates the C-094 domain, version, provenance,
and usage records. The owner Execution Packet for issue #100 is the bounded
implementation authorization; independent review and manual owner merge remain
required.
