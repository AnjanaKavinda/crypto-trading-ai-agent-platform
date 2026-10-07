# ADR-0008: Versioned C-003 v2 compatibility and rollout

## Metadata

| Field | Value |
|---|---|
| Status | Accepted |
| Date | 2026-10-07 |
| Decision owner | Platform Architect |
| Human approver | AnjanaKavinda |
| GitHub issue / PR | [#335](https://github.com/AnjanaKavinda/crypto-trading-ai-agent-platform/issues/335) |
| Open decision ID | — |
| Related ADRs | ADR-0003, ADR-0006 |
| Supersedes / superseded by | — |

## Context

C-003 v1 stores seven scalar scores, so it cannot distinguish a measured score
from an unavailable or inapplicable dimension. Replacing its shape or changing
the global market-data schema version would change historical canonical bytes
or unrelated contract identities. The lineage store already keys records by
`(contract_id, record_id, version)` and preserves immutable payloads.

Issue #335 implements the owner-directed Option B from proposal #334 as a
compatibility foundation only. It does not migrate a producer or analysis
consumer.

## Alternatives

### Option A — Change C-003 v1 or the global schema/wire version

Benefits:

- One model could expose the richer dimension state.

Costs, risks, and constraints:

- Reinterprets or changes canonical v1 payloads and historical identities.
- A global version change would affect C-001, C-002, C-091, C-092, and other
  contracts that are not part of this decision.

### Option B — Add a distinct C-003 schema v2

Benefits:

- Preserves v1 model, bytes, hashes, keys, and readers exactly.
- Lets the C-003 schema version select a separately validated v2 model while
  retaining the existing `wire-1` envelope.

Costs, risks, and constraints:

- Producers and consumers must be explicitly migrated before v2 writing is
  enabled.
- Assessment policy definitions must be versioned and resolved by producers;
  structural contract validation alone cannot establish policy permission.

## Decision

**Select Option B.** Keep `DataQualityReport` at C-003 schema `1` unchanged and
add the distinct `DataQualityReportV2` for C-003 schema `2`. Both use
`canonical-json-v1` and `wire-1`; the C-003 `schema_version` selects the model.
Do not change `CONTRACT_SCHEMA_VERSION` or any other contract's schema.

V2 contains exactly one canonically ordered typed result for each of the seven
dimensions. Results have one explicit state:

- `MEASURED`: finite Decimal score in `[0, 1]`, backed by a positive-denominator
  numerator/denominator and unit or a hashed immutable evidence reference.
  Measured zero additionally requires both a positive denominator and an
  immutable evidence reference.
- `NOT_APPLICABLE`: no score or measurement basis; requires
  `SINGLE_POINT_SNAPSHOT` and an explicit assessment-policy ID/version equal to
  the report's policy binding.
- `UNAVAILABLE`: no score or measurement basis; requires one of
  `MISSING_REQUIRED_EVIDENCE`, `SEQUENCE_UNVERIFIED`,
  `DENOMINATOR_UNAVAILABLE`, or `PROVENANCE_UNVERIFIABLE`.

Unknown state and reason values reject. V2 `VALID` reports reject any
`UNAVAILABLE` dimension; absent a resolved policy registry, all dimensions are
treated as required at this compatibility boundary. N/A remains distinct from
positive evidence, and any consumer that requires a dimension must check its
state.

The C-003 lineage key uses version `1` for schema 1 (preserving every existing
identity) and version `2` for schema 2. Existing lineage primary keys already
include the version field, so no DDL or data migration is required. The generic
lineage writer rejects v2 until consumers are ready; decode and exact-key
readback support v2.

## Reasoning

The versioned model provides explicit availability and measurement provenance
without redefining v1 or the generic wire format. A missing or unverifiable
required input cannot be called N/A: only the explicit point-snapshot reason is
structurally permitted, and producers must resolve the exact policy version
and confirm it permits that state before emitting a report.

## Consequences

- V1 persisted reports are never rewritten, backfilled, or reinterpreted.
- The codec dispatches C-003 by both contract ID and schema version; unknown
  versions fail closed.
- Immutable evidence references are carried into lineage links and checked
  against the referenced content digest.
- This ADR does not make analysis consumers accept v2 and does not add a v2
  producer.
- Rollout order is: merge v2 contract/codec/read compatibility; revalidate
  reader migration needs; migrate and validate all receiving consumers; add a
  producer that resolves a known policy version; only then separately approve
  enabling v2 writes.

## Contract and traceability impact

| Area | References and impact |
|---|---|
| Playbook requirements | Chat 4 data quality and reproducible snapshot requirements; no Master Playbook text changed. |
| Cross-cutting artifacts | C-003 in `01-domain-contract-registry.md`; version resolution rules in `09-version-registry.md`. |
| Contracts / events | C-003 schema 1 unchanged; C-003 schema 2 added; no event contract changes. |
| Requirements traceability | Issue #335; proposal/owner direction in issues #333 and #334. |
| Versioning / migration | `wire-1` retained; C-003 lineage version distinguishes schema; existing composite key reused; no migration. |

## Safety, security, and failure behavior

No market-data provider, network, trading, signal, risk, approval, or execution
behavior changes. Missing required evidence remains unavailable and fails
closed. Unknown policy or schema versions reject. V2 writing remains disabled,
live trading remains disabled, and `NO_TRADE` remains available.

## Approval record

Accepted by `AnjanaKavinda`, human repository owner, on 2026-10-07 for the
versioned C-003 v2 compatibility boundary and rollout sequence described here.
V2 production, consumer migration, policy registry/producer implementation, and
enabling v2 writes are not approved by this ADR.
