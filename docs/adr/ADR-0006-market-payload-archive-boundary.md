# ADR-0006: Separate immutable market evidence from hot payload storage

## Metadata

| Field | Value |
|---|---|
| Status | Accepted |
| Date | 2026-10-04 |
| Decision owner | Platform Architect |
| Human approver | AnjanaKavinda |
| GitHub issue / PR | [#47](https://github.com/AnjanaKavinda/crypto-trading-ai-agent-platform/issues/47) / [#305](https://github.com/AnjanaKavinda/crypto-trading-ai-agent-platform/pull/305) |
| Open decision ID | OD-0008, OD-0017 (bounded personal Spot OHLCV scope) |
| Related ADRs | ADR-0003, ADR-0005 |
| Supersedes / superseded by | — |

## Context

ADR-0005 is accepted for one-user Spot OHLCV: 90 days hot in PostgreSQL,
five years minimum in immutable cold archive, and longer while retained
analysis references the observations. It also requires lineage references to
remain resolvable.

The current lineage implementation stores each full canonical C-001 document
in `lineage_records.document`. Migration 0003 installs database triggers that
reject update, delete, and truncate on both `lineage_records` and
`lineage_links`. This preserves byte-level immutability, but means simply
copying old rows to object storage cannot reduce PostgreSQL's retained payload
size. Deleting or rewriting lineage rows would break existing integrity and
foreign-key guarantees.

The Playbook calls for object storage for large historical datasets and a
relational store for metadata. The accepted retention tier choice therefore
needs a payload boundary while preserving C-001 identity, evidence digests,
dependency edges, point-in-time behavior, and exact replay.

## Options considered

### Option A — Keep complete payloads in PostgreSQL and copy them to cold storage

- Preserves the current append-only model without a schema transition.
- Does not reduce PostgreSQL payload growth and therefore does not satisfy the
  90-day hot-storage objective.
- Adds a second copy that still needs reconciliation and backup.

### Option B — Split immutable lineage anchors from tiered C-001 payloads

- Keep C-001 identity, canonical evidence digest, source links, and all
  dependent edges in append-only PostgreSQL lineage tables.
- Store the canonical C-001 bytes in a separately governed hot-payload table
  for the 90-day hot window, then in compressed immutable cold objects.
- Record archive manifests containing object identity, canonical payload
  digest, compressed-object digest, covered C-001 keys, and time range.
- Resolve an observation from hot storage first, then cold storage; verify the
  decoded identity and both digests before returning it.
- Delete a hot payload only after the cold object is read back and verified,
  its manifest is durable, and all required references still resolve.
- Requires an additive payload table, an explicit payload-location lifecycle,
  and a compatibility migration for existing inline Spot OHLCV rows. A one-time
  migration may change physical placement only; evidence identity and digest
  remain fixed and are revalidated before and after transfer.

### Option C — Partition the existing lineage tables by event date

- Could simplify physical retention for some tables.
- Existing cross-partition foreign keys, immutable triggers, and mixed-contract
  rows make this a larger schema redesign; it does not by itself define cold
  object resolution or archive verification.

## Decision

**Select Option B for the personal Spot OHLCV scope.**

Preserve the current public C-001 contract and lineage keys. Separate
physical payload placement from semantic evidence identity:

1. Keep lineage key, version, evidence SHA-256, and dependency links in
   append-only tables. Never delete or rewrite these anchors or links.
2. Introduce a hot payload table keyed by the exact lineage identity. Inserts
   are immutable. Model storage movement with an append-only location-event
   ledger (`HOT_WRITTEN`, `COLD_VERIFIED`, and `HOT_REMOVED`); do not update
   one mutable status field. A removal event is
   permitted only after verified cold publication and a successful backup /
   restore gate. The event ledger and evidence anchors are retained longer
   than the payload lifecycle.
3. Store cold data in immutable compressed objects partitioned by UTC date,
   venue, and instrument. Use a bounded manifest that maps exact lineage keys
   to object hashes and coverage. Object paths must not be derived from
   unchecked user input.
4. Resolve by exact key and verify the canonical document digest, decoded
   C-001 identity, evidence digest, and manifest membership before analysis.
   Missing, corrupt, or unavailable hot/cold payloads fail closed; callers do
   not receive an unverified or partially resolved snapshot.
5. Transfer in stages: write object → read back and verify → persist immutable
   manifest and `COLD_VERIFIED` event → verify the resolver against the
   original C-001 anchor and all dependent C-002/C-003 records → confirm a
   recoverable off-device backup and tested restore point → append
   `HOT_REMOVED` and remove only the eligible hot payload. Failures before
   final verification leave the hot copy intact. Retries are idempotent by
   object digest.
6. Backfill only the five approved Binance Spot OHLCV instruments from inline
   C-001 rows into hot-payload storage. Other C-001 types, venues, and
   instruments remain inline. Read/write compatibility remains available
   throughout the migration. No legacy inline payload is removed before
   off-device backup and restore verification, and successful cold resolution
   are recorded.
7. Keep existing C-002/C-003 snapshots, source records, analyses, and lineage
   links in PostgreSQL initially. They identify and validate the referenced
   history; cold C-001 payloads remain addressable through the resolver.

The accepted 90-day/five-year/reference-aware policy and $5 monthly backup cap
remain as stated in ADR-0005. Production deployment, non-OHLCV data, and
customer tenancy remain out of scope.

## Impact and approval conditions

- **Schema:** add hot payload and archive manifest/catalog tables; change C-001
  persistence/read paths; add an append-only payload-location event ledger.
  Preserve lineage primary keys and dependency FKs.
- **Compatibility:** existing C-001 rows remain readable inline while approved
  OHLCV rows are copied to hot payload storage and verified. Other C-001 rows
  remain inline. A rollback must retain either a verified
  cold copy or an inline/hot copy for every anchor.
- **Contracts:** no semantic change to C-001/C-002/C-003. Storage location and
  transfer state are persistence metadata, not market facts or quality status.
- **Security:** archive and backup credentials remain external; no secrets in
  code, logs, tests, issue text, or object paths. All failures are visible and
  fail closed.
- **Operations:** measure PostgreSQL growth, archive size, B2 requests/egress,
  backup size, restore time, and total spend before enabling scheduled purge.
- **Provider integration:** this ADR selects the payload boundary and lifecycle,
  not a deployed B2 client or credential setup. Implement the object-store
  adapter behind a narrow interface; enable it only after server-side
  credentials, encryption configuration, cost caps, and restore evidence are
  available. Do not store keys in the repository or browser.
- **Testing:** corrupt/missing objects, partial transfer, duplicate retry,
  mismatch, outage, resolver fail-closed, reference preservation, migration
  restart, and restore must be covered before deleting any hot payload.
- **No purge authority:** acceptance of this ADR alone does not enable a
  scheduled retention job. That job requires tested implementation and a
  separately reviewed rollout plan.

## Playbook and traceability

| Area | References |
|---|---|
| Playbook | Chat 4 §§49–50 require dataset-specific retention and object storage for large historical datasets; §114 requires dataset-specific cache behavior. |
| Cross-cutting | OD-0008 and OD-0017 remain open beyond this bounded personal Spot scope. |
| Contracts | C-001 market observation; C-002 snapshot; C-003 quality report; no semantic change proposed. |
| Requirements | GitHub #47 retention lifecycle; #299 real-data Spot research vertical slice. |
| Migration | Additive transition from inline C-001 documents to hot/cold payload lookup; never delete lineage anchors or links. |

## Approval record

Accepted by `AnjanaKavinda`, human repository owner, on 2026-10-04 in this
conversation after review of the Option B recommendation. Approval covers the
personal Spot OHLCV payload/lineage separation, verified cold archive, and
append-only storage-location events described here. Production topology,
customer data, other data kinds, live trading, and activation of automated
purge remain outside this approval.
