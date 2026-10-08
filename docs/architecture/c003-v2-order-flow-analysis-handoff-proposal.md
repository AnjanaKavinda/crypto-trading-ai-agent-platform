# C-003 v2 order-flow analysis handoff proposal

## Status and scope

**Proposed for owner review only — not approved for implementation.** This is
the focused architecture/contract proposal for GitHub issue #338 and the
handoff to **GitHub #60 (canonical Issue 058 — Order-flow and liquidity
analysis engine)**. It does not retarget #60 to canonical Issue 060 (on-chain
analysis).

No shared contract, schema, code, persistence behavior, producer, or consumer
is changed by this proposal. The repository owner must approve the contract
direction before any shared-contract implementation or #60 consumer
implementation begins. Keep #60 blocked until that decision is recorded. The
Master Playbook is not modified.

## Governing constraints and current boundary

Chat 3 requires deterministic engines to calculate facts and AI analysts to
interpret them; Chat 5 §§14–15 (lines 1057–1119) require order-flow and
microstructure analysis to remain evidence-based and analysis-only. Unavailable
flow data must be reported as unavailable, not neutral. Chat 5 expressly does
not authorize execution decisions. See
[`03-chat-3-multi-ai-agent-trading-intelligence.md`](../playbook/01-specification/03-chat-3-multi-ai-agent-trading-intelligence.md)
and
[`05-chat-5-analysis-meta-analysis-engine.md`](../playbook/01-specification/05-chat-5-analysis-meta-analysis-engine.md).

The current source chain is modality-bound:

1. C-001 `MarketData` observations identify their C-091 `DataSourceRecord`.
   C-002 `MarketSnapshot` carries ordered C-001 IDs and source-record IDs.
2. The #337 producer returns an in-memory C-003 schema-2 report for one C-002
   snapshot and one resolved policy. The report binds its `snapshot_id`, policy
   ID/version, and seven dimension states. Its optional per-dimension evidence
   reference is not guaranteed on every report, so the current report alone
   does not guarantee a C-002 content-digest binding. Trade, tick, and
   order-book inputs are assessed separately.
3. C-003 schema 2 is read/decode compatible, but v2 lineage writes and report
   persistence remain disabled. Preserve this boundary. ADR-0008's C-003 v1
   identities and canonical bytes remain unchanged.
4. C-007 schema 1 carries one `market_snapshot_id` and one
   `data_quality_report_id`; C-006 schema 1 carries one report ID. C-008 schema
   1 can list multiple source-record and dataset IDs, but has only one report
   UUID and no typed C-002 reference or C-003 schema-version/policy binding.
   The assessment union has no order-flow/microstructure type; mapping these
   outputs into an unrelated technical or SMC category would change meaning.

Relevant implementation references: `apps/api/src/trading_platform_api/market_data/quality.py:1169-1221,1408-1450`
(`assess_normalized_spot_trades`, `assess_normalized_spot_ticks`, and
`assess_normalized_spot_order_book`), `market_data/contracts.py:430-447,581-846`
(C-002 and C-003 schema-2 models), `analysis/contracts.py:274-342,756-883`
(C-008/C-007/C-006 schema-1 shapes), `lineage/codec.py:48-85,157-174`, and
[`ADR-0008`](../adr/ADR-0008-versioned-c003-v2-compatibility.md). C-003 schema 2
identifies lineage version 2, while schema 1 remains version 1; the existing
lineage key includes the version. The #337 in-memory report is not evidence
that v2 writes or multi-modality aggregation has been enabled.

## Can C-008 alone preserve the required lineage?

**No, not for a combined C-007/C-006 output.** Existing C-008 fields are
useful: `source_record_ids` and `dataset_versions` support multiple inputs,
and `provenance` records version references. But a report UUID alone cannot
select the C-003 v1/v2 lineage identity, verify the report digest, or bind its
policy. Nor does C-008 identify the C-002 snapshot whose source membership was
assessed. More fundamentally, one C-008 per modality cannot overcome the
single-snapshot/single-report fields in C-007 and C-006. Generic provenance
strings are not a substitute for validated, typed source bindings.

A future consumer could store separate per-modality evidence items, but it
could not claim that one canonical analysis snapshot unambiguously consumed
both exact snapshots, reports, policies, and source closures. Treating one
report as representative of both modalities would be ambiguous and unsafe.

## Options

| Option | Canonical serialization/version impact | Consumers and migration | Reconstruction and safety |
|---|---|---|---|
| **1. C-008 per-evidence links; retain C-006/C-007 v1** | No shape or identity changes. C-008's single report UUID remains insufficient to encode exact C-003 version/policy/digest and snapshot binding. | Could emit separate per-modality C-008 items, but #60 cannot create one cross-modal C-007/C-006 without reusing a singular field or inventing undocumented joins. Existing readers need no migration. | Preserves each evidence item's source IDs but does **not** reconstruct one combined analysis to both snapshots/reports. A consumer-side join or overloaded provenance would be implicit and fail closed only by convention. Not recommended. |
| **2. Versioned analysis extension (recommended)** | Keep all v1 C-006/C-007/C-008 schema identities and serialized bytes unchanged. Add explicit schema-2 models under the same IDs, retaining `canonical-json-v1` and `wire-1`; schema version dispatches the model. No global version bump and no C-003 v1 change. Propose a new typed C-104 `OrderFlowAssessment` (schema 1), subject to registry approval. | Add strict v2 decoding/validation and migrate only the #60 consumer after owner approval. Existing v1 consumers continue to read v1 and reject unknown versions; no automatic v1-to-v2 conversion. Future C-006/C-007/C-008 readers must resolve exact bindings before use. | An immutable C-007 v2 input manifest binds each C-002 snapshot to exactly one C-003 v2 report, policy, and C-001/C-091 membership closure. C-008 v2 evidence names the manifest bindings it used. Unknown versions, broken membership, missing references, and digest mismatches reject. This is the only option compared that supports exact cross-modal reconstruction. |
| **3. Single-modality output; defer synthesis** | No schema/version changes. Restrict output to separate, existing C-008 v1 evidence items or noncanonical local results; do not emit a C-006/C-007 cross-modal context or claim a typed order-flow assessment. | #60 may implement only evidence for one modality at a time; combining results and canonical typed output are explicitly deferred to a later approved issue. No migration now. | Safest interim boundary, but does not satisfy #60's combined trade/tick and book objective. It must not imply cross-modal confluence or silently combine two snapshots. Use only if the owner declines Option 2. |

## Recommended model for owner decision

Approve Option 2 in principle, subject to final field/schema review:

- **C-007 schema 2 is the source-input manifest.** Replace the singular
  snapshot/report linkage with a non-empty, deterministically ordered collection
  of typed input bindings. Each binding identifies its modality; exact C-002
  identity, schema version, and canonical digest; exact C-003 identity,
  schema/lineage version, and canonical digest; and the C-003 assessment policy
  ID/version. The binding also enumerates exact C-001 observation and C-091
  source-record identities/digests (and C-092 identity/digest when present).
  Enforce that report `snapshot_id` matches the paired C-002, its report
  digest resolves exactly, any embedded C-002 evidence digest matches that
  snapshot, and the C-001/C-091 membership matches the snapshot. The manifest
  itself must always carry the C-002 digest; do not rely on the report's
  optional per-dimension reference. Hash the complete manifest into the C-007
  content hash.
- **C-008 schema 2 binds evidence to the manifest.** Retain evidence-specific
  source IDs, timestamps, method/version, limits, quality and expiry; replace
  the ambiguous single report UUID with one or more typed manifest-binding
  references. Each item names only the bindings actually used to calculate
  that evidence. Thus a book-only spread binds to the book input, while an
  evidence item that genuinely compares flow and book binds to both. C-008 v1
  remains unchanged.
- **C-006 schema 2 references the C-007 v2 manifest and typed assessments**
  rather than presenting one report UUID as the quality state for a
  multi-modality result. Do not duplicate an independently editable binding
  list in C-006; resolve it through the exact C-007 reference.
- **Add a typed `OrderFlowAssessment` candidate as C-104**, with a per-metric
  result state, value, unit, time/window, deterministic method version, evidence
  IDs, and C-007 binding IDs. The assessment can be `PARTIAL` only when each
  metric independently states whether it is available; unavailable metrics
  are never represented as neutral. This is a proposed registry addition, not
  an allocation made by this document.

For every referenced record, the final design must bind `(contract_id,
record_id, schema/lineage version, canonical digest)`. C-002's exact membership
must resolve to the listed C-001 observations and C-091 source records; each
C-001 source ID must resolve to its matching C-091 record. The report reference
must resolve to the matching C-003 v2 record and exact policy. Where a C-003
dimension includes an evidence reference to C-002, that digest must match, but
it does not replace the mandatory C-002 digest in the C-007 binding or the full
source closure. Missing, duplicated, mismatched, or unresolvable references
invalidate the affected metric and the combined output. C-008 evidence cannot
outlive its input bindings or expiry.

This provides a deterministic reconstruction path:

`C-006 v2 → C-007 v2 manifest → (C-002 snapshot, C-003 v2 report, policy) → C-001 observations → C-091 source records → C-104 metrics → C-008 evidence`

Any future immutable persistence for analysis artifacts is a separate decision.
This proposal does not enable persistence, add lineage writers, or change the
current in-memory C-003 v2 boundary.

## Metric semantics and dimension gates

The following are proposed minimum gates, not an approved quality policy.
**C-003 top-level `VALID` is necessary but not sufficient**: consumers must
inspect the exact policy and relevant dimensions in every bound report.
`MEASURED` requires its positive denominator or immutable evidence reference;
missing evidence is `UNAVAILABLE`, never measured zero or `NOT_APPLICABLE`.
The current C-003 v2 model permits `NOT_APPLICABLE` only for continuity with
`SINGLE_POINT_SNAPSHOT` and an exact report-policy match. That state is not
measured continuity.

| Metric class | Deterministic definition and units | Required C-003 v2 evidence and availability |
|---|---|---|
| **Spread** | Best ask minus best bid in the configured price unit; optional full spread in bps is `20,000 × (ask − bid) / (ask + bid)`. Require positive, uncrossed top levels and one common point-in-time book. | The book report must be `VALID`; completeness, freshness, accuracy, consistency, source reliability, and coverage must be `MEASURED` and pass that exact policy. Continuity may be `NOT_APPLICABLE/SINGLE_POINT_SNAPSHOT` only for a point-snapshot spread. |
| **Displayed depth** | Sum quantities across an explicitly configured top-N bid and ask levels, in the configured quantity unit; any quote-notional total must identify its price basis and quote unit. | Same snapshot gates as spread, plus all N levels on both sides present and validated. If a window is built from book deltas, continuity must instead be `MEASURED` and pass its sequence policy; point-snapshot N/A cannot qualify it. |
| **Book imbalance** | `(bid depth − ask depth) / (bid depth + ask depth)` over the same configured N levels, time, and units; requires a positive denominator. | Same gates as displayed depth. Label it displayed-book quantity imbalance, not order execution likelihood or hidden liquidity. |
| **Buy/sell volume and volume delta** | For a declared trade window, sum quantities only for normalized C-001 TRADE events with explicit `AGGRESSOR` semantics and known BUY/SELL side. Delta is buy volume minus sell volume in the same quantity unit. | Trade report must be `VALID`; all seven dimensions including continuity must be `MEASURED` and pass. Require explicit sequence scope, complete expected population/window, and verified contiguous sequence evidence. Any unknown aggressor side makes the full-window directional totals/delta `UNAVAILABLE`; never infer side from price movement, maker side, or ticks. |
| **Cumulative delta** | Ordered cumulative sum of per-event volume delta from an explicit window start/anchor; output records the window and sequence basis. | Same strict trade gates as volume delta, with complete ordered sequence for the full stated window. Missing boundary, gap, reversal, duplicate conflict, or unknown aggressor side makes the full-window value `UNAVAILABLE`/`INVALID`; no hidden carry-in or implicit reset. |

Quality status mapping is fail-closed: `INVALID`, `STALE`, `UNAVAILABLE`,
unknown policy/version, unresolved provenance, or a required dimension not
measured/passing cannot produce an `AVAILABLE` metric. `INCOMPLETE` or
`DEGRADED` is not promoted to `VALID`; the assessment may contain another
independently qualified metric, but the affected metric remains unavailable
unless an explicitly approved policy defines a bounded partial population.
Use `PARTIAL` only for an assessment containing independently gated metrics,
with each unavailable result and reason explicit. Follow Chat 5's
`DATA_UNAVAILABLE` rather than `NEUTRAL` distinction.

`TradeTickQuality.sequence_verified` and a top-level report status alone are
not proof that a requested analytical window is complete. The consumer must
verify that policy expected-count and transition denominators cover the
declared window, sequence scope is consistent, and transitions have no gaps.
The C-003 continuity state must be `MEASURED`; an N/A point snapshot never
satisfies any sequence-dependent metric.

## Explicitly bounded methodology and exclusions

Calculations are deterministic, versioned, read-only transformations of the
provided normalized records. A point book may support spread, displayed depth,
and book imbalance. A trade sequence may support directional volume, delta, and
cumulative delta only under the strict side and sequence gates above. Keep
book-depth imbalance distinct from aggressor-volume delta.

Do not infer unknown aggressor side. Do not infer stop locations or claim
hidden stop clusters. Do not label absorption or exhaustion, set “large trade”
thresholds, claim execution pressure/market impact, or estimate executable
liquidity without separately approved, versioned definitions and the required
evidence. Do not manufacture measurements from absent data.

The analysis layer remains read-only. No signals, strategy qualification,
risk/position sizing, approval, execution, provider calls, live collection,
persistence enablement, or cross-modal claim unsupported by the listed input
bindings is in scope.

## Consumer impact, rollout, and rollback

**Affected consumers:** GitHub #60 (canonical Issue 058) is the immediate
consumer. Future Strategy, Validation, UX, Audit, and Learning consumers of
C-006/C-007/C-008 must either explicitly support schema 2 and resolve the
manifest, or continue to reject it. Existing v1 consumers and C-003 v1 readers
must not reinterpret v2.

**Proposed sequence after owner approval:**

1. Record the human decision on the contract direction, C-104 allocation,
   exact field semantics, policy requirements, and compatibility rules.
2. In a separate contract implementation change, add only versioned C-006,
   C-007, and C-008 schema-2 models (and C-104 if approved), with strict
   canonical round trips, reference-closure checks, and tests proving v1
   identities/bytes are unchanged. Add no storage writer or provider behavior.
3. Independently migrate and validate each receiving reader. C-003 v2 write
   enablement and persistence remain disabled; no migration may rewrite or
   backfill v1 records.
4. Unblock #60 only after the owner records approval. Implement its consumer
   against the two explicit modality bindings and the approved metric gates;
   keep #60 analysis-only and in-memory unless separately approved.
5. Consider any later v2 persistence/write enablement as a separate, explicitly
   reviewed rollout, after all receiving readers are ready, consistent with
   ADR-0008.

Rollback disables routing to the new analysis schemas and returns
`UNAVAILABLE`/`NO_TRADE` rather than substituting v1 or combining ambiguous
records. Preserve all historical v1 bytes and any later immutable v2 records;
do not rewrite or delete them. Unknown schema versions, missing links, or
digest mismatches reject. No database migration is proposed here.

## Exact handoff to GitHub #60 (canonical Issue 058)

Until owner approval is recorded, #60 remains blocked at the contract
dependency. After approval, #60 may consume the in-memory normalized TRADE/TICK
and ORDER_BOOK paths and their separate C-003 v2 reports, build the approved
C-007 input manifest, and emit only the approved typed C-104/C-008 analysis
outputs. It must preserve separate trade and book reports/policies, use the
metric-specific gates above, and fail closed on unknown side, unavailable
quality, sequence gaps, or unresolved lineage. It must not enable C-003 v2
writes, persistence, network/provider behavior, signals, strategy qualification,
risk, approval, or execution.

## Approval requested

The repository owner is asked to approve or reject Option 2, including the
typed manifest/evidence linkage and provisional C-104 direction, or direct the
safe single-modality fallback. No implementation approval is implied by this
proposal. The current #337 in-memory boundary and disabled v2 writes remain
unchanged pending that decision.
