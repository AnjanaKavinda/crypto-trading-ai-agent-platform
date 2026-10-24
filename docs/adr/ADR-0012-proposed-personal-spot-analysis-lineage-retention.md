# ADR-0012: Retention for personal Spot analysis lineage

## Metadata

| Field | Value |
|---|---|
| Status | Accepted |
| Date | 2026-10-24 |
| Decision owner | Platform Architect |
| Human approver | AnjanaKavinda (PR #412 merged 2026-10-24) |
| GitHub issue / PR | #74 / #412 |
| Open decision ID | OD-0008, OD-0017 (bounded personal Spot analysis-artifact scope only) |
| Related ADRs | ADR-0003, ADR-0005, ADR-0006, ADR-0007 |
| Supersedes / superseded by | — |

## Context

Issue #74's local `PERSONAL_SPOT_RESEARCH` request path returns a request-scoped
analysis bundle alongside a validated Spot snapshot. The bundle contains
C-003 v2 quality, C-005 regime, C-007 v4 manifest, C-008 v2 evidence,
fan-out outcomes, and a C-093 v1 dependence report. The bundle is returned to
the caller but is not durably stored. PR #408 explicitly deferred durable
analysis-record retention as a later Issue #74 step.

ADR-0005 accepts PostgreSQL and a local immutable archive/backup lifecycle for
Spot OHLCV. It does not define retention, archival, or deletion rules for these
analysis artifacts. ADR-0006 likewise defines the market-payload boundary, not
analysis-record storage. The generic lineage store uses closed contract codecs
and exact dependency links; it currently does not support the full analysis
bundle. Persisting the bundle therefore needs a bounded data-lifecycle decision
before adding codecs, store behavior, migrations, or API readback semantics.

The decision is needed to make a saved analysis reproducible and auditable
without making a read-only GET write records, extending OHLCV retention rules
silently, or implying that a successful refresh grants trading authority.

## Alternatives

### Option A — Keep analysis request-scoped and ephemeral

Benefits:

- No new analysis-record retention or deletion policy.
- No persistence, migration, backup, archive, or readback failure modes.

Costs, risks, and constraints:

- A later GET cannot retrieve the exact C-007/C-008/C-093 closure from an
  earlier refresh.
- A user cannot replay the exact analysis decision after its response is lost,
  even while the OHLCV snapshot remains retained.
- Issue #74's request-path lineage remains response-only.

### Option B — Persist the exact personal Spot analysis closure

Benefits:

- The same immutable OHLCV snapshot can be associated with the exact quality,
  regime, manifest, evidence, task outcomes, and C-093 dependence result that
  were returned for a refresh.
- Readback can verify canonical payloads, digests, identities, and exact parent
  references instead of rebuilding or guessing prior request context.

Costs, risks, and constraints:

- Requires explicit local retention and deletion rules for analysis artifacts.
- Requires strict versioned codecs and dependency links; unsupported or corrupt
  records must fail closed.
- A failed analysis-record write must not be reported as durable success or
  invalidate an already accepted OHLCV snapshot.
- A GET must not create or update stored records.

## Decision

**Accepted:** Select Option B for the one-user, local
`PERSONAL_SPOT_RESEARCH` profile only, subject to the retention rules below.

1. Persist only the exact validated closure needed to reproduce the Spot
   analysis response: C-003 v2, C-005 v1, C-007 v4, C-008 v2, C-093 v1, and
   their exact C-002/C-001/C-091 parents. Preserve canonical payload, identity,
   schema/lineage version, digest, correlation identity, source/observation
   references, and dependency edges.
2. Append analysis records only as part of an explicit successful refresh
   operation. Do not persist from GET, UI reload, or readback. A GET resolves
   the exact records associated with the selected snapshot and revalidates
   current freshness before serving them.
3. Keep analysis records in the existing local PostgreSQL lineage graph and
   include them in the already-approved local database backup. Do not add a
   new database, cloud service, vector store, or external archive tier in this
   decision.
4. Retain each analysis record for at least as long as any exact input or
   downstream retained record refers to it. No cache TTL or automatic purge may
   remove a referenced record. Any broader fixed retention duration or deletion
   workflow remains outside this decision and requires a separate owner-approved
   decision.
5. If a refresh's analysis closure cannot be persisted or verified, preserve
   the valid OHLCV refresh result but return an explicit analysis-persistence
   unavailable state. Do not label that analysis durable, reuse a different
   snapshot's bundle, or silently fall back to an in-memory result as though it
   were stored.
6. Existing snapshots without a durable analysis bundle remain valid candle
   data. Their analysis readback is explicitly unavailable until a later
   successful explicit refresh creates a matching bundle; GET does not backfill.

This decision would not change C-003/C-005/C-007/C-008/C-093 semantics or
versions. It does not authorize retention of other data domains or any
customer-facing, cloud, or production storage policy.

## Reasoning

Option B is the smallest path that makes the exact refresh analysis replayable
while preserving the approved local-first PostgreSQL foundation and existing
immutable lineage model. Tying retention to exact dependency references avoids
inventing a cache TTL for evidence. This decision does not extend
ADR-0005's five-year OHLCV archive duration to analysis artifacts and does not
choose an unapproved cold archive. Existing data-quality and freshness gates
continue to control whether analysis may be served as current.

The explicit-refresh-only write boundary preserves GET as read-only. A failed
analysis write does not roll back a valid market-data refresh, but the response
must distinguish a usable persisted OHLCV snapshot from unavailable analysis
lineage.

## Consequences

Implementation authority is limited to this accepted personal Spot scope:

- The implementation PR adds strict closed codec support, exact
  parent/reference validation, append-only persistence, transactional
  refresh-path integration, and read-only resolution for existing snapshots.
- Tests must cover exact round-trip and digest verification, missing/mismatched
  references, duplicate/idempotent append behavior, write failure, stale
  readback, legacy snapshots without a bundle, and that GET does not write.
- Production retention and data-domain expansion remain unresolved.

Production retention and data-domain expansion remain unresolved. Issue #74
remains open until its implementation acceptance criteria are satisfied.

## Contract and traceability impact

| Area | References and impact |
|---|---|
| Playbook requirements | Chat 3: exact agent provenance and uncertainty; Chat 4: source and retention lifecycle; Chat 5: point-in-time analysis; Chat 10: audit and recovery. |
| Cross-cutting artifacts | Evidence Graph; Version Registry; Audit/Traceability Matrix; Test Traceability Matrix; OD-0008 and OD-0017. |
| Contracts / events | C-003 v2, C-005 v1, C-007 v4, C-008 v2, C-093 v1 and existing C-001/C-002/C-091 parents; no semantic or version changes. |
| Requirements traceability | Issue #74, bounded `PERSONAL_SPOT_RESEARCH` request-path analysis; PR #408 explicitly deferred durable lineage. |
| Versioning / migration | Prefer existing append-only lineage tables; add only closed, version-pinned codecs/reference validation. Any required schema migration must be additive, reviewed, and preserve existing records. |

## Safety, security, and failure behavior

- Local, single-user, read-only Spot research only.
- Persist no prompts, hidden reasoning, credentials, execution requests, or
  unrelated market domains.
- C-093 still reports observed dependence only; statistical independence is
  not claimed.
- Stale, invalid, mismatched, missing, corrupt, or unsupported records remain
  unavailable and are never promoted to current-valid evidence.
- Persistence cannot create a strategy, signal, risk decision, approval,
  order, paper/testnet execution, exchange authority, or live-trading path.
- If approval is absent or the retention rule is ambiguous, keep analysis
  request-scoped and ephemeral.

## Approval record

Accepted by the human repository owner through merge of PR #412 on 2026-10-24.
This ADR authorizes only the personal local Spot analysis-lineage scope above.
