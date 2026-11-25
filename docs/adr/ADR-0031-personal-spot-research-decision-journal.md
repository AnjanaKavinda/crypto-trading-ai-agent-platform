# ADR-0031: Personal Spot research decision journal

## Metadata

| Field | Value |
|---|---|
| Status | Accepted |
| Date | 2026-11-25 |
| Decision owner | Platform Architect |
| Human approver | AnjanaKavinda: owner merge of PR #513, confirmed in project conversation 2026-11-25 |
| Issue | #157; operational coordination #299 |
| Related decisions | Accepted ADR-0017, ADR-0020, ADR-0009; ADR-0030 unchanged |
| Contract proposal | Additive C-107 schema 1, ResearchDecisionJournalEntry; identifier unused at verified base |
| Verified base | `4f1e81022c11eaf9501e7949336b0f7e728c9e7e` (merged PR #512) |

## Problem and delivery priority

The owner can inspect persisted research records and evidence after #511/#512,
but cannot save a distinct declaration of their own research decision. The
Phase 1 Spot gate in #299 requires prospective decision/outcome measurement;
it does not require profitability or a statistically qualified signal first.

#157 is the existing capture owner. Its full C-045 learning ledger remains a
separate scope: it requires canonical agent/safety provenance, and EXECUTED
experience requires approval, execution and factual outcome. C-044 additionally
requires a C-043 trade, nonempty orders/fills and C-096 reconciliation. Neither
contract truthfully represents an unverified user declaration/manual result.
Do not fabricate those references or reinterpret existing contract meanings.

ADR-0017 explicitly leaves manual outcome/cost/baseline logging to an approved
contract/scope decision. ADR-0020 authorizes only its enumerated retained
artifacts. A new journal contract, retention expansion and local write surface
therefore need this bounded decision before implementation.

## Recommendation

Add one append-only research-decision record, proposed C-107v1, using the
existing local PostgreSQL lineage foundation. Implement one working slice:
explicit user declaration -> verified immutable insert -> exact readback ->
read-only history. Do not create a parallel database, generic journal framework,
event transport, full learning pipeline or manual-outcome model in this slice.

The declaration may say ABSTAIN or EXTERNAL_TRADE_INTENT. It records the user's
claim, not a platform trade decision or authorization. Preserve and display the
backend's source outcome separately, including NO_TRADE. Disagreement must not
change source records, qualification, risk, approval or execution. Logging an
external intention does not permit the application to act on it.

Alternatives: waiting for full execution would delay the personal workflow;
reusing factual C-044 or EXECUTED C-045 would invent missing authority/facts;
browser-only notes would not provide durable exact provenance. Reject those
alternatives for this slice. The existing factual/learning contracts remain
unchanged and no automatic conversion into them is introduced.

## Exact first-slice record and request

The implementation must register the following closed, versioned C-107v1
shape after approval. No model or persistence change is implemented here.

| Field | Required meaning and validation |
|---|---|
| `contract_id`, `schema_version` | Fixed C-107 / 1; unknown fields/versions rejected by a closed codec. |
| `entry_id`, `content_sha256` | UUIDv5 and lowercase SHA-256 of canonical content excluding those two identity fields. Use an explicit journal identity namespace/version; changing any recorded fact changes identity. |
| `profile`, `operating_mode` | Fixed PERSONAL_SPOT_RESEARCH / RESEARCH. No Futures, paper, testnet or live scope. |
| `request_id`, `request_sha256` | Client UUID idempotency key and digest of the exact normalized client request, including explicit nulls. Same profile/key with changed material is 409; identical retry returns the original committed entry. |
| `source` | Exact contract/UUID/schema/digest for one persisted C-026v2, C-023v1 or C-070v2. Resolve full existing lineage; no caller-authored artifact payload or latest lookup. A C-024 package is not mandatory for NO_TRADE. |
| `market_context` | Exact server-resolved C-006v5 reference associated with that source. Verify Spot scope and source/context identity; do not accept caller-invented scope or substitute a current snapshot. |
| `source_observation` | Closed supporting snapshot: recorded backend projection (nullable, preserved verbatim within existing bounds), reason codes, source occurrence/expiry (expiry nullable), and nullable latest lifecycle-event pin. Pin = event UUID, snapshot-format version 1, canonical SHA-256 of the complete existing typed event. This is not an invented C-060 reference or an execution state. Derive all fields on the server. |
| `declared_action` | Exactly ABSTAIN or EXTERNAL_TRADE_INTENT. No APPROVE, EXECUTE, override or risk-acceptance action. |
| `declared_at`, `recorded_at` | Timezone-aware UTC; client declared time cannot be after server recorded time. Preserve both; a backdated declaration never proves prospective recording. Reject a reversed server clock behind relevant source/history/parent records. |
| `note` | Plain text, zero to 2,000 characters; no HTML interpretation, provider/model use, secret logging or statistical meaning. |
| `supersedes`, `correction_reason` | Nullable exact prior C-107 reference and reason. Both present or both absent; verify existing prior same-profile entry, ordering and no cycle. Append a correction; never change the original record/time. Corrections do not inherit earlier prospective timing or become additional independent samples. |
| `origin`, `identity_assurance` | Fixed LOCAL_USER_DECLARATION / LOCAL_SESSION_UNAUTHENTICATED. Loopback/proxy admission is not authenticated owner identity. Do not claim an authenticated principal, exchange verification or owner signature. |
| `qualification_authorized`, `approval_authorized`, `execution_authorized`, `trade_facts_verified` | All fixed false. These records cannot satisfy risk, approval, factual-outcome or strategy-promotion gates. |

Only request ID, exact source reference, action, declared time, note and optional
correction fields are client inputs. Identity, profile/mode, context, source
observation, recorded time, request digest and authority metadata are server
owned. Idempotency binds the client material before enrichment; a retry must
not rerecord a later clock, lifecycle projection or source observation.
Canonicalize UUIDs and UTC timestamps using existing repository serialization;
preserve note text without trimming. An omitted note normalizes to an empty
string, and omitted correction fields to explicit nulls. Bound correction text
to 2,000 characters too; the total request byte limit still applies.

Expired sources may be recorded as historical declarations, visibly preserving
their time bounds; they never become current. Missing, future-dated, invalid,
unresolved or mismatched source/context/parent evidence rejects the write.
No fabricated default source, state, reason, evidence package or timestamp.

## Storage, retention and local admission

Extend only the existing closed lineage codec/reference graph and SQL contract
allowlist for C-107v1. Add a unique `(profile, request_id)` binding to its exact
request digest and committed C-107 reference. Use one transaction and verify
canonical read-after-write before reporting durable success. Conflicts and
uncertain storage results must not create a new request identity automatically.
Retry/recovery reuses the same key; expose bounded exact key/reference reads.

Use a forward-only additive migration and immutable insert rules. Preserve
all existing rows, codecs, references and backups; no backfill, destructive
downgrade, update or delete route. Retain entries, correction ancestors,
idempotency bindings and referenced source/history at least while any retained
record refers to them; initially provide no automatic purge. Include them in
the existing local encrypted database backup. This proposal authorizes no
operation on the owner's retained database; its separate backup/migration gate
still applies. Migration tests use disposable databases only.

The API is restricted to the existing local research deployment and admission
controls: exact loopback Host/Origin, configured native frontend origin or
existing authenticated Docker proxy, JSON-only bounded request body (16 KiB),
no-store responses, bounded pagination (default 20, maximum 100) and correlation
tracing. The new write requires an allowed Origin; absent or foreign Origin
fails closed. Reuse existing origin configuration, not caller-selected origin
or browser-exposed proxy credentials. No public/customer write endpoint or
new authentication exception. An authorized local process can still submit a
declaration; the fixed unauthenticated identity assurance makes that limitation
explicit. Actual multi-user/authenticated use remains gated on #136/#142.

The UI must require an explicit declared action and explicit save operation;
viewing/selecting a record never writes. Label the save as a research
declaration, show the backend outcome separately, and do not present external
intention as a recommended or approved trade. Use DOM text for notes and
reasons; no localStorage credential/note ledger, external service or paid model.

## Focused implementation acceptance after approval

Deliver these together as one working first-slice PR, rather than another
contract-only foundation followed by several disconnected implementation PRs.

1. Closed C-107v1/codec with exact source/context binding, deterministic identity,
   client/server field separation, units-free declaration and honest identity.
2. Atomic insert/readback, restart-safe idempotency, conflicting retry rejection,
   append-only corrections and preserved historical references. Exercise an
   actual disposable PostgreSQL path; no broad unrelated suite locally.
3. Local POST/exact-read/list API and UI save/history against real persisted
   synthetic source records, including NO_TRADE without a package. Verify
   foreign/missing Origin, oversized input, stale/future/mismatched source,
   storage failure, duplicate/concurrent retry and safe note rendering.
4. One complete genuine-defect review and focused correction verification;
   required exact-head hosted CI and owner manual merge. Do not wait for separate
   independent-review automation under the current owner direction.

## Deferred outcomes and approval boundary

Manual entry/exit/quantity/currency/fees/slippage/funding observations and their
cost/performance evaluation need a separately explicit owner-reported shape,
not C-044 with invented orders/fills/reconciliation. They follow the decision
journal and must distinguish reported trading from platform readiness,
backtests, paper/testnet evidence and reconciled execution. This proposal does
not select their schema or make the full #157/#158 learning engines ready.

While Proposed, this document did not authorize implementation. Owner acceptance
now permits only the listed contract, storage/migration and HTTP/UI first-slice
work; no credential, qualification, risk, approval, exchange or execution authority
is granted. Approval of this exact boundary permits the listed
first-slice implementation without another routine direction approval;
concrete contract/storage/security contradictions still return for review.
Futures follows the actual Spot operational gate, not profitability evidence.

## Approval record

Accepted by owner merge of PR #513 (`b56e55effa096a65c4bb4b7b4ff3f4bf56ec8e48`),
confirmed by the owner on 2026-11-25. This accepts the exact first-slice contract,
storage and local write boundary above; it does not approve operations on the
owner's retained database or enable trading execution.
