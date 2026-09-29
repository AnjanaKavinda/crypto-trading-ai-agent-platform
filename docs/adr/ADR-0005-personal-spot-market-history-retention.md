# ADR-0005: Personal Spot market-history storage and retention

## Metadata

| Field | Value |
|---|---|
| Status | Accepted |
| Date | 2026-09-29 |
| Decision owner | Platform Architect |
| Human approver | AnjanaKavinda |
| GitHub issue / PR | AnjanaKavinda/crypto-trading-ai-agent-platform#47 / implementation PR |
| Open decision ID | OD-0008, OD-0017 (bounded personal-research sub-decisions) |
| Related ADRs | ADR-0003, ADR-0004 |
| Supersedes / superseded by | — |

## Context

The personal Spot research phase covers Binance public Spot OHLCV for BTCUSDT,
ETHUSDT, BNBUSDT, SOLUSDT and XRPUSDT. Accurate indicator warm-up, point-in-time
analysis, backtests and later replay require retained normalized observations
and their exact provider, quality and calculation provenance. The owner approved
a 90-day hot PostgreSQL window, a five-year cold archive, retention of inputs
while dependent analyses remain, and encrypted versioned off-device backups.

This is a bounded research decision. It does not resolve production hosting,
tenancy, time-series extensions, customer redistribution, or retention for
trades, order books, derivatives, news, on-chain, fundamental, audit or vector
data. Network collection remains subject to ADR-0004's provider opt-in gates.

## Alternatives

### Option A — Keep only transient provider responses

Benefits:

- minimal storage and operational setup.

Costs, risks, and constraints:

- cannot reliably reproduce prior analysis or preserve indicator warm-up;
- upstream corrections and changed availability can alter later calculations;
- no durable history for backtests or point-in-time reconstruction.

### Option B — PostgreSQL hot data plus immutable cold archive and off-site backup

Benefits:

- fast recent research queries, longer history, and exact input reconstruction;
- keeps provenance, quality verdicts and analysis references linked;
- compressed cold files limit database growth while versioned backups support recovery.

Costs, risks, and constraints:

- archival, restore, encryption-key and integrity-check operations must be built
  and tested;
- actual disk, archive and egress costs must be measured against the US$100/month
  personal-research ceiling;
- retention must respect the applicable provider terms and cannot purge data
  referenced by retained analysis.

### Option C — Use a dedicated time-series database or managed warehouse

Benefits:

- may simplify large-scale time-series querying and operations later.

Costs, risks, and constraints:

- adds a service, cost and topology decision before personal-pilot volume is
  measured;
- exceeds this bounded decision and would require resolving OD-0008 further.

## Decision

Select **Option B** for the one-user personal Spot research phase:

1. Keep normalized OHLCV, source/snapshot/quality metadata and recent queryable
   history in the accepted PostgreSQL foundation. The hot window is 90 days.
2. Move older canonical market-history payloads to compressed, immutable files
   partitioned by UTC date, venue and symbol. Retain the cold archive for at
   least five years from observation time, and longer while any retained
   analysis, experiment or backtest references those inputs.
3. Keep immutable lineage identifiers, hashes and dependency edges resolvable;
   do not apply a cache TTL or delete action to referenced evidence. A stale or
   failed quality verdict is never served as current valid analysis.
4. Persist each quality assessment with its exact snapshot. Only a matching
   `VALID` C-003 report makes a snapshot eligible for indicator calculation or
   a current-analysis response. Non-VALID outcomes remain explicit and cannot
   be promoted by storage.
5. Back up database snapshots and archive files daily to a separate versioned
   off-device B2 bucket using client-side encryption and a tested restore path.
   Keep the personal backup allowance at or below US$5/month and the total
   research spend at or below US$100/month; measure actual volume and egress.
6. Start with the approved five Spot pairs and OHLCV only. Do not persist trades,
   depth, derivatives, news, on-chain, fundamentals or customer data under this
   ADR.

The hot/cold and backup policy is approved for personal research, not as a
production retention or deployment policy. PostgreSQL remains the chosen
relational foundation; no time-series extension or production cloud topology
is selected.

## Reasoning

This choice preserves analysis reproducibility and builds on PostgreSQL,
SQLAlchemy async and Alembic already accepted by ADR-0003. It also follows the
personal Spot storage direction and cost envelope in ADR-0004 while keeping
historical payloads immutable and separating recent query behavior from longer
retention. A five-year minimum gives a useful multi-year research history; the
reference-protection rule prevents retained analysis from losing its inputs.
OHLCV-only scope controls volume until observed research needs justify other
data kinds.

## Consequences

Positive:

- analysis can be recalculated against exact, quality-checked input snapshots;
- indicator warm-up can use retained history rather than synthetic or browser
  values;
- source corrections can be represented as new immutable evidence rather than
  silent overwrites.

Operational obligations:

- archive compaction, payload resolution, checksums, client-side encryption,
  backup versioning and restore tests require separate implementation and
  operational verification;
- stale, incomplete, degraded or invalid C-003 snapshots are never eligible for
  indicator reads;
- collection and archive writes stay disabled until ADR-0004's terms, regional
  and integration-evidence gates are configured;
- cost/volume monitoring must stop optional collection or backup expansion
  before exceeding the approved personal budget, without silently deleting
  referenced evidence.

## Contract and traceability impact

| Area | References and impact |
|---|---|
| Playbook requirements | Chat 4 Sections 49, 50, 113–115: dataset-specific retention, storage tiers, cache TTL/invalidation, explicit source and freshness; Chat 5: point-in-time analysis |
| Cross-cutting artifacts | Bounded accepted sub-decisions for OD-0008 and OD-0017; #47 implementation and #299 real-data vertical slice |
| Contracts / events | No C-001/C-002/C-003/C-091 semantics changed; persist exact versions and link C-003 to C-002 |
| Requirements traceability | #47 retention; #299 real-data Spot path; existing lineage store #46 |
| Versioning / migration | Additive lineage codec support for existing C-003; Alembic migration extends accepted lineage persistence allowlist |

## Safety, security, and failure behavior

- No exchange credentials, private endpoints, trading permissions, orders,
  approvals or live-trading authority are introduced.
- Provider data and quality reports are treated as untrusted inputs; strict
  canonical decoding, identity/hash checks and quality-state matching are
  required before analytical use.
- Missing, stale, non-VALID, mismatched, corrupt or unavailable data fails
  closed as unavailable; storage cannot author a VALID verdict.
- Database/archive/backup failure must be surfaced; no silent fallback to
  unpersisted data may be represented as durable or replayable evidence.
- Encryption keys remain external secret-managed configuration and must never
  enter repository content, logs, issues or PRs.
- The personal API remains local-only until the separate AuthN/AuthZ and safety
  gates are approved.

## Approval record

Accepted by `AnjanaKavinda`, human repository owner, on 2026-09-29 in the
continuation of the trading-platform development chat. Approval covers only the
personal Spot OHLCV hot/cold retention and backup policy stated in this ADR.
Production retention, tenancy, deployment topology and all other data kinds
remain open.
