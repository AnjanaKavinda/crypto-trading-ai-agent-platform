# ADR-0020: Personal Spot strategy artifact persistence for the Strategy/Signal API

## Metadata

| Field | Value |
|---|---|
| Status | Accepted |
| Date | 2026-11-05 |
| Decision owner | Platform Architect |
| Human approver | AnjanaKavinda (owner-approved #90 refinement, 2026-11-05) |
| GitHub issue / PR | #90 / PR #458 proposal; PR #460 acceptance record |
| Open decision ID | — |
| Related ADRs | ADR-0003, ADR-0012, ADR-0017 |
| Supersedes / superseded by | Supersedes only ADR-0017's prohibition on persistence/migrations for the #90 API path; ADR-0017 otherwise remains in force |

## Context

The PERSONAL_SPOT_RESEARCH portion of #90 requires exact, repeatable reads of
C-023 candidates, C-024v2 evidence packages, C-025v2 qualifications, C-028v2
validation results, C-026v2 NO_TRADE decisions, C-070v2 signals, and #89
lifecycle history. Its reference-only evaluate operation must be idempotent for
the same profile and exact request references.

The #80–#89 producers currently construct the strategy and signal artifacts in
memory. The lineage store persists the approved market and analysis closures,
but its codec and database constraint do not yet admit the strategy artifacts.
ADR-0012 expressly limits its retention decision to its enumerated analysis
contracts. ADR-0017 otherwise prohibits migrations beyond the lifecycle event
table. Consequently, implementing #90 as currently refined would either return
ephemeral artifacts as though they were durable or require an unapproved
storage expansion.

The local PostgreSQL lineage graph is already the platform's immutable,
digest-checked artifact store. A bounded extension can preserve producer-owned
artifact semantics while avoiding a competing store and establishing one
durable idempotency result for each canonical evaluate request.

## Alternatives

### Option A — Keep strategy outputs request-scoped

Benefits:

- No additional durable artifact storage or migration.

Costs, risks, and constraints:

- Exact API readback cannot work after the originating request ends.
- A retry may rerun the pipeline and produce new identities or lifecycle
  effects, violating #90's idempotency requirement.
- The API cannot truthfully claim durable evidence lineage.

### Option B — Extend the existing immutable lineage graph for the bounded Spot path

Benefits:

- Reuses canonical serialization, exact keys, digest checks, immutable inserts,
  and dependency-link verification already used by the repository.
- Gives producer outputs, API readback, and idempotent evaluate results one
  auditable local persistence boundary.

Costs, risks, and constraints:

- Requires a forward-only additive migration, closed schema-aware codecs,
  producer write integration, and API read integration.
- Requires explicit retention and failure behavior for the added artifacts.

### Option C — Add a parallel strategy-artifact database/store

Benefits:

- Could isolate the strategy domain's schema and lifecycle.

Costs, risks, and constraints:

- Duplicates immutable identity, digest, lineage, backup, and readback
  mechanisms already provided by the lineage graph.
- Creates another source of truth and synchronization boundary without a
  current deployment or scale requirement.

## Decision

**Accepted:** Select Option B for the single-user local
`PERSONAL_SPOT_RESEARCH` profile only. The owner accepted the core persistence
decision in the #90 implementation refinement dated 2026-11-05; PR #458 merged
the proposal document and PR #460 synchronized the acceptance record. The owner
approved the bounded input-closure extension on 2026-11-06. Implementation
remains limited to the decisions below.

1. Extend the existing lineage graph with closed, explicit codecs and exact
   `(contract_id, record_id, schema_version)` identities for the supported
   strategy outputs: C-023v1, C-024v2, C-025v2, C-026v2, C-028v2, and C-070v2.
   Do not add dynamic deserialization, schema fallback, `latest` lookup, or
   in-place updates. The implementation must enumerate and validate the exact
   producer-owned reference closure required by these artifacts before writing
   the migration; unsupported referenced contracts fail closed and must not be
   silently omitted from lineage verification.
2. Strategy producers own persistence of their immutable outputs. The evaluate
   application service coordinates the exact existing pipeline and appends its
   output closure and one immutable evaluate-result binding within one database
   transaction. A result binding is unique by profile scope and canonical
   digest of the exact strategy-version and validated Spot-context references.
   A matching retry returns the exact previously recorded outcome without
   rerunning producers or adding another lifecycle event. A digest collision
   with different canonical request material is an integrity error.
3. Preserve each artifact's exact schema version, canonical payload, content
   digest, identity, validity bounds, correlation identity where present, and
   version-qualified references. C-060 and #89 lifecycle events remain
   append-only and must refer to the exact persisted artifact identity/digest.
   Reads resolve exact keys and verify canonical digests and lineage. They do
   not recompute producers, qualification, validation, expiry, invalidation, or
   lifecycle state.
4. Perform a forward-only additive migration. Add only the necessary supported
   strategy contract identities, constraints, indexes, and immutable
   evaluate-result binding to the existing PostgreSQL lineage persistence
   foundation. Preserve existing rows and schema behavior. Do not rewrite or
   backfill historical in-memory outputs. Downgrade must not delete durable
   records; follow the repository's forward-only migration convention.
5. Retain each persisted strategy artifact and evaluate-result binding for at
   least as long as any retained input or downstream record refers to it. No
   TTL or automatic purge may remove a referenced record. This ADR selects no
   fixed retention duration or deletion workflow. Include the records in the
   approved local database backup.
6. A successful API response that claims a durable result is allowed only after
   the transaction commits and exact read-after-write verification succeeds.
   On storage or lineage failure, roll back the evaluate transaction, return a
   bounded unavailable/integrity problem, and do not report an in-memory result
   as durable. Existing valid market/analysis records remain unaffected.
7. Apply only to PERSONAL_SPOT_RESEARCH on the current local PostgreSQL
   deployment. Spot GET/list operations remain read-only and bounded by #90's
   cursor and page-size rules. Existing loopback, no-store, correlation,
   problem-response, and future authorization-seam requirements remain in
   force.

### Owner-approved input-closure extension (2026-11-06)

The existing #80 condition builder requires the exact typed #68 debate and
fan-out handoffs. C-006 alone does not carry the C-062/C-066 identity needed to
validate the debate handoff, and the fan-out outcomes are stored in the Spot
analysis read model rather than as typed lineage records. #90 must resolve
these exact upstream outputs before it can run the existing deterministic
pipeline.

1. Extend the closed lineage codec and contract allowlist to persist only the
   required `C-062v1 AgentResult`, `C-066v1 AgentEvaluation`, and nested
   `C-067v1 ModelRoutingDecision` records. This is persistence of existing
   contracts; it changes no contract meaning, schema version, prompt content,
   provider behavior, or agent authority.
2. Add an append-only, immutable producer handoff binding that pins one exact
   C-006v5 context digest to the exact C-062v1 result digest and its one exact
   C-066v1 evaluation digest, including their correlation/trace identity. The
   writer must validate the C-062 output equals that C-006 record and that
   C-066 references that exact C-062 result and context. Ambiguous or
   conflicting bindings fail closed; no latest-by-time selection is allowed.
3. Reuse the existing immutable Spot analysis row for fan-out outcomes. Decode
   it through a closed typed decoder, verify its stored digest and exact C-007
   manifest binding, and require its correlation ID to match the exact C-066
   evaluation. Do not rerun fan-out during evaluate. Recompose the internal
   `SpotDebateResult` only through the existing deterministic validator from
   the exact persisted C-062/C-066/C-006 closure; it remains an orchestration
   value, not a new persisted domain contract.
4. Keep the extension producer-owned. It adds no HTTP ingestion endpoint,
   caller-authored context, model/provider call, external service, shared
   contract, or strategy behavior. The existing upstream producer may append
   the exact handoff closure through an internal persistence method. Missing
   producer outputs remain unavailable and fail closed.
5. Add only the additive DDL needed for the closed contract allowlist and the
   immutable C-006/C-062/C-066 handoff binding. Preserve exact existing
   immutability, backup, retention, transaction, digest, and fail-closed rules
   above. No historical backfill is authorized.

This extension does not change #90's reference-only request shape: evaluate
still accepts only exact C-021v2 and C-006v5 references. It resolves the exact
producer handoff by the requested C-006 identity and will never synthesize or
substitute missing inputs.

## Reasoning

Option B reuses the repository's established immutable evidence and exact
lineage model. It closes the functional gap between #90's durable read contract
and the current request-scoped producer outputs while preserving a narrow
single-user research boundary. A canonical evaluate-result binding makes retry
behavior durable across process restarts; uniqueness and transaction scope
prevent a retry from duplicating lifecycle history. The schema allowlist and
codec remain closed so adding persistence does not turn arbitrary payloads
into trusted evidence.

This is an additive persistence capability, not a change to any producer's
contract meaning. If the exact transitive lineage closure cannot be represented
without changing a shared contract or breaking existing lineage invariants,
implementation must stop and bring back that specific conflict for review.

## Consequences

- After acceptance, refine #90 against the exact producer reference closure,
  persistence transaction, idempotency binding, and migration described here.
- Implement producer-owned append-only persistence and exact API readback in
  #90 only. Keep #91 blocked until #90 and the Wave 4 integrated checkpoint
  pass on the exact merged tree.
- The new records become part of local database backup and require storage,
  migration, transaction, conflict, idempotency, readback, and fail-closed
  regression coverage.
- This decision does not make the system suitable for profitability claims;
  prospective decision/outcome logging and Wave 5 validation remain later work.

## Contract and traceability impact

| Area | References and impact |
|---|---|
| Playbook requirements | Chat 6 strategy/signal evidence and qualification boundary; no approval or execution authority |
| Cross-cutting artifacts | Version Registry; lineage graph; lifecycle state registry; provenance and fail-closed rules |
| Contracts / events | C-023v1, C-024v2, C-025v2, C-026v2, C-028v2, C-070v2 plus exact C-062v1/C-066v1/C-067v1 producer input closure and existing C-060 linkage; persistence only, no contract semantics or versions changed |
| Requirements traceability | GitHub #90 PERSONAL_SPOT_RESEARCH refinement; #89 lifecycle dependency |
| Versioning / migration | Closed codec dispatch by exact contract/schema; forward-only additive migration; no historical backfill or destructive downgrade |

## Safety, security, and failure behavior

No risk, approval, credential, exchange, order, paper/testnet/live execution,
Futures, customer multi-tenancy, or UI authority is added. The API remains a
research read/evaluate surface. Invalid, unsupported, missing, mismatched, or
corrupt lineage fails closed. Database errors cannot produce a successful
durable-result response. GET/list never writes or triggers evaluation.

If this ADR is not accepted, #90's durable-artifact implementation remains
blocked; the current in-memory service may not be presented as satisfying the
durable exact-read or retry-idempotency requirements.

## Approval record

Core persistence decision accepted by AnjanaKavinda in the owner-approved #90
refinement dated 2026-11-05; proposal document merged in PR #458 and acceptance
record synchronized by merged PR #460. The bounded C-062/C-066/C-067 input-
closure extension was explicitly approved by AnjanaKavinda on 2026-11-06 in
the current implementation discussion. Runtime implementation remains limited
to this ADR's scope.
