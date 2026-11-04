# ADR-0017: Proposed Wave 4 lifecycle, invalidation, and signal API boundary

## Metadata

| Field | Value |
|---|---|
| Status | Proposed |
| Date | 2026-11-03 |
| Decision owner | Platform Architect |
| Human approver | Pending |
| GitHub issue / PR | #89, #90; Wave 4 contract-freeze PR |
| Open decision ID | — |
| Related ADRs | ADR-0008, ADR-0015, ADR-0016 |
| Supersedes / superseded by | — |

## Scope

This proposal freezes only the PERSONAL_SPOT_RESEARCH lifecycle and API
boundary. It authorizes no runtime implementation. It does not change Chat 6,
the Master Playbook, qualification logic, C-026 mapping, risk, approval,
execution, Futures, or the #148/#149 user interface work.

## Context and source of truth

At verified `dev` baseline
`0f50932c8084604061841dc1e054590694551fbc`, Wave 3 contracts and runtime
through #88 are merged. Live #89 requires governed candidate/watch/qualified/
rejected/expired/superseded outcomes, explicit invalidation and additive
history. Live #90 requires bounded candidate/evidence/qualification/NO_TRADE
read/evaluate APIs and prohibits approval or execution operations. Both retain
the PERSONAL_SPOT_RESEARCH and Chat 7 authority boundaries.

The repository sources establish these current constraints:

- Chat 6 requires explicit invalidation conditions, expiry, separate
  candidate/qualification/NO_TRADE/signal artifacts, and says Chat 6 ends at
  presentation to a human. It places approval in Chat 9.
- C-021 schema 1 (`StrategyVersion`) has a free-text `invalidation_concept`;
  it has no condition/group references or trigger polarity. The condition DSL
  already evaluates exact condition and group identities as `PASS`, `FAIL`, or
  `UNKNOWN`.
- C-023 schema 1 is immutable and always has lifecycle `CANDIDATE`. Its
  `invalidation_concept` is descriptive. The current setup builder emits it
  with empty `reference_values`; it does not bind an executable invalidation
  condition.
- C-025 schema 2 is the authoritative deterministic consumer of C-024v2 and
  C-028v2. C-026 schema 2 has typed `INVALID_PROVENANCE`; neither should be
  recomputed or rewritten by #89.
- C-070 schema 1 accepts only qualified status and a passed C-028
  `ValidationReference`, but `SignalLineage` contains bare UUIDs for the
  candidate, evidence package, and qualification. It does not bind their
  schema versions or content digests, nor a digest-qualified C-028v2 result.
- The existing cross-cutting state registry requires invalid, duplicate,
  out-of-order, or unauthorized transitions to be rejected and recorded as a
  C-060 audit event. It has a generic signal row, but does not yet define the
  Wave 3 artifact-level transitions or typed invalidation guards.
- The current API guard only accepts loopback-addressed requests. RFC 9457
  problem responses, no-store behavior, and correlation IDs already exist.
- Live #148 and #149 explicitly remain unassignable until #256 releases the
  phase, #136 Authentication/Authorization is available, and #142 Safety
  compliance passes. They are deferred here.

The source paths are Chat 6 at
`docs/playbook/01-specification/06-chat-6-strategy-signal-evidence-qualification.md`;
state/version rules at `docs/cross-cutting/08-state-machine-registry.md` and
`docs/cross-cutting/09-version-registry.md`; C-021/C-023/C-070 at
`apps/api/src/trading_platform_api/strategy/contracts.py`; C-021 hashing and
resolution at `apps/api/src/trading_platform_api/strategy/registry.py`; and
condition truth/evaluation at
`apps/api/src/trading_platform_api/strategy/condition_evaluator.py`.

## Alternatives

### A. Keep free-text C-021v1 invalidation and infer triggers from prose

Rejected. Prose has no typed identity, truth polarity, freshness binding, or
deterministic evaluation. It cannot prove invalidation.

### B. Add invalidation fields to C-021v1 or extend C-070v1 in place

Rejected. These are serialized, digested contracts with closed schema
meanings. Existing v1 artifacts and hashes must remain valid and unchanged.

### C. Publish C-070v1 after resolving all source references outside the signal

Rejected. A C-070v1 artifact would still expose only bare lineage IDs. A
consumer cannot distinguish a same-ID artifact schema collision or verify the
exact C-024v2/C-025v2/C-028v2 chain from the C-070 record itself.

### D. Add a new globally shared lifecycle-event contract

Rejected for this bounded profile. Only #89 and #90 need the history boundary
now, and Wave 5 can refer directly to immutable C-023/C-026/C-070 artifacts.
A global event contract would create additional consumers and registry
obligations without a current cross-domain requirement. C-060 remains the
canonical audit linkage; a typed lifecycle record stays local to the strategy
service.

### E. Add C-021v2/C-070v2 plus a local append-only lifecycle record

Selected. This versions only the two contract surfaces whose current shapes
cannot truthfully express the required invalidation and exact qualified-signal
lineage. Existing v1 artifacts stay readable and retain their meaning.

## Decision proposed

### 1. C-021 schema 2 invalidation rules

Add `StrategyVersionV2` under contract `C-021`, schema `2`. Retain the v1
fields and meanings. Add one required typed invalidation rule set:

```text
InvalidationRuleSetV2
  triggers: non-empty tuple[InvalidationTriggerV2]
  combine: ANY | ALL

InvalidationTriggerV2
  target_type: CONDITION | CONDITION_GROUP
  target_id: UUID
  trigger_truth: PASS | FAIL
```

Each target must resolve to a condition or condition group in the same exact
C-021v2 record. Trigger references must be unique. `UNKNOWN` is not an allowed
trigger truth. `ANY` means any listed truth match invalidates; `ALL` means all
listed truth matches are required in the same valid evaluation. No new
condition language or feature/operator vocabulary is introduced. Existing
condition and group definitions, the recorded DSL/method version, and the
condition evaluator remain authoritative.

A condition/group may also participate in setup qualification: the explicit
trigger truth gives it a distinct invalidation meaning (for example, a
previously passing setup condition becoming `FAIL`). Do not infer invalidation
from a candidate's free-text description or from an unreferenced condition.

Only an exact, fresh C-021v2 evaluation whose referenced targets are all
available may trigger this rule set. A matched PASS/FAIL polarity is an
invalidation event. `UNKNOWN`, stale input, invalid provenance, unsupported
schema, missing rule references, or an unavailable evaluator is not an
invalidation proof: progression stops and the applicable C-026v2 abstention
reason is emitted (`STALE_DATA`, `VALIDATION_INCONCLUSIVE`, or
`INVALID_PROVENANCE` as applicable). No invalidation is inferred from C-023
`analytical_confidence` or `evidence_strength`.

C-023 remains schema 1. Its existing exact `SignalConcept.method` reference to
C-021 binds the strategy version; the descriptive invalidation concept is not
an executable rule. C-021v1 remains valid for history, but a new qualified
C-070v2 cannot be issued from a C-021v1 strategy because it lacks a typed
invalidation rule set. No strategy record is upgraded in place. A strategy
that needs the Wave 4 lifecycle must receive a new C-021v2 version and exact
new C-023 candidate.

### C-021 schema-1/schema-2 runtime dispatch

Both C-021 schemas are first-class stored records. Define a closed
`StrategyVersionRecord = StrategyVersion | StrategyVersionV2` union and
make registry protocol/store `register_version`, `get_version`, and semantic-version
lookup return that union. `ResolvedStrategyVersion.version` retains the exact
concrete v1 or v2 object. It must never decode v2 into a v1-shaped copy.

The registry dispatches by the canonical document envelope's
`(contract_id, schema_version)` pair. The existing table already stores the
envelope in `canonical_document` and uses UUID primary identity plus a unique
`(strategy_id, semantic_version)`; no schema column is needed. Its codec currently
hard-codes schema 1, so implementation must add an explicit C-021 schema-2
decoder/encoder while retaining the schema-1 codec. `get_version()` validates
the row identity, envelope, selected model, and schema-specific digest; unknown
schema values raise the existing unsupported/invalid-record error and never
fall back to v1. Semantic-version lookup stays keyed by the C-020 strategy
identity and SemVer, independent of C-021 schema. The existing SemVer
comparator remains the parent/child ordering rule.

`strategy_version_content_sha256` becomes a schema dispatcher over exact model
types: schema 1 uses the existing frozen preimage unchanged; schema 2 hashes the
complete C-021v2 payload, including invalidation rules, with only the
self-referential digest omitted. `ResolvedStrategyVersion` carries the union
through #80/#81/#82. #80 runs the same existing condition DSL/evaluator once
over shared condition/group fields and binds its result to the exact version
ID, SemVer, digest, and schema-derived digest. It does not strip the v2 rule
set: #89 reads invalidation metadata from the retained v2 object and evaluates
the already-produced condition/group results. #81 and #82 use the shared typed
fields while preserving the exact resolved object; candidate construction
copies the strategy identity/version and exact `SignalConcept.method` reference.
C-023 schema 1 retains the C-021 SemVer in `VersionReference.version` and the
C-021 content digest; that digest commits to the C-021 schema discriminator.
Consumers resolve the candidate's strategy-version ID and verify the reference
digest against the resolved schema-specific record; they do not infer schema
from SemVer.

C-024v2 continues to bind the exact C-021 ID, SemVer, and schema-sensitive
content digest. #85/#87/#86/#88 keep their existing exact reference checks and
pass the immutable C-021 identity through; they do not need a v1 projection or
a broad C-023/C-024/C-025/C-026/C-028 version bump. Unsupported C-021 schema
or digest mismatch blocks candidate/evidence/qualification/signal progression
as invalid provenance.

### Personal Spot strategy upgrade

The existing C-021v1 Personal Spot strategy record remains immutable under
the same C-020 strategy identity. A usable C-021v2 strategy is a new record
with a new `strategy_version_id`, a schema-2 digest, `parent_version_id` set
to the prior version where the existing registry parent rule applies, and a
SemVer greater than its parent under the existing comparator. It enters
through the existing governed `RESEARCH` registration and artifact `DRAFT`
lifecycle, with the required decision/evidence references. No historical
candidate or strategy row is rewritten.

Do not choose a new SemVer in this ADR: the repository defines only canonical
SemVer validation and monotonic parent ordering, not whether this change is a
minor or major release. Record the chosen SemVer in the version-specific
registration decision before creating the new artifact. Current approved
strategy semantics contain prose such as “structure invalidation” but do not
identify condition/group IDs or trigger polarity. Therefore the actual
C-021v2 trigger set is a separate bounded strategy-configuration decision.
It must be approved from explicit strategy semantics before #89 can publish
C-070v2 for the Personal Spot strategy; do not derive or invent triggers from
the prose.

### 2. C-070 schema 2 exact publication lineage

Add `SignalV2` / `SignalLineageV2` under `C-070`, schema `2`. Preserve the
qualified-signal fields and validations from v1, and replace the bare lineage
identities with exact `VersionReference` values for:

- C-023 candidate;
- C-021 strategy version;
- C-024 evidence package;
- C-025 qualification;
- C-028 authoritative validation result.

The v2 model requires C-023v1, C-021v2, C-024v2, C-025v2, and C-028v2 exact
references. The qualification reference must match the candidate, strategy,
evidence-package, and validation references carried by that C-025v2 record;
the C-028 reference must resolve to the C-025v2 embedded validation result.
The model still requires a qualified C-025 status and PASS from every
mandatory C-028 gate. Its expiry cannot exceed the candidate, package,
validation, and qualification validity. C-070v2 is emitted only after
resolving those exact immutable artifacts; #89 does not synthesize or
re-evaluate qualification. `signal_id` is UUIDv5 of the canonical digest of
the complete immutable C-070v2 payload with `signal_id` omitted; this includes
the exact lineage references, issue time, and effective expiry, making an
exact replay idempotent without collapsing different evidence chains.

C-070v1 remains valid for historical artifacts. Consumers that only support
v1 reject v2 as unsupported; they do not drop the added references or coerce
the record. No risk, approval, order intent, or execution field is added.

### 3. Lifecycle history and transition projection

Keep `C-023`, `C-025`, `C-026`, and `C-070` immutable. Their lifecycle fields
continue to describe the artifact at creation. #89 maintains an internal,
immutable `SignalLifecycleEvent` record and derives current display state from
the append-only event stream. The local record includes a deterministic event
ID, subject `VersionReference`, prior and resulting projection states,
machine-readable event/reason, exact triggering artifact references,
event time, recorded time, correlation ID, and linked C-060 audit ID. Each
transition is paired with a C-060 audit record under the existing state
registry rule. Duplicate delivery is idempotent; illegal transitions are
rejected and audited. A materialized current-state view is disposable and
rebuildable from the immutable records.

The bounded event vocabulary is `CREATED`, `WATCHED`, `QUALIFIED`,
`REJECTED`, `NO_TRADE`, `INVALIDATED`, `EXPIRED`, and `SUPERSEDED`. Typed
lifecycle causes are `SOURCE_DECISION`, `INVALIDATION_RULE_MATCHED`,
`MATERIAL_CONTEXT_CHANGE`, `EFFECTIVE_EXPIRY_REACHED`, and
`EXPLICIT_SUCCESSOR`; C-026 reason codes remain on the referenced C-026v2
artifact and are not copied into free text. The event ID is UUIDv5 over the
canonical event identity (subject reference, event/cause, exact source and
trigger references, resulting state, and event time), excluding the generated
ID, recorded time, and audit ID. Expiry event time is the exact effective
expiry; invalidation event time is the source evaluation time; supersession
event time is the successor candidate's creation time.

Use these meanings:

| Projection | Sole authority |
|---|---|
| `CANDIDATE` | Exact C-023 candidate exists and its current references are valid. |
| `WATCH` | An explicit typed C-025 `WATCH` result exists. Never infer from confidence, missing proof, stale data, or a developing candidate. Current #86 runtime does not emit WATCH; until an approved producer does, the Personal Spot path reports it unavailable. |
| `QUALIFIED` | Exact C-025v2 is qualified and a matching C-070v2 is successfully resolved. |
| `REJECTED` | Exact C-025 result is `REJECTED`; its C-028 result proves a failed mandatory gate. |
| `NO_TRADE` | Successful C-026v2 decision with one or more typed reasons. This is separate from a C-025 `REJECTED` result and can reference the same evaluation. |
| `INVALIDATED` | A current, exact C-021v2 invalidation trigger matches, or valid current source evidence proves a material context change against the exact qualified artifact. |
| `EXPIRED` | Current time is at or beyond the subject's effective expiry. Effective expiry is the earliest expiry of all required exact inputs. |
| `SUPERSEDED` | A new exact candidate/signal explicitly names the prior subject as its replacement. The pair must share strategy ID/version, asset, instrument, timeframe, and direction. Never infer replacement from recency alone. |

Missing, stale, invalid, future-dated, or mismatched provenance is an
insufficient/invalid-input outcome, not a positive invalidation proof. It
blocks new qualification and C-070 publication; C-026v2 carries the truthful
reason. A valid new C-006/C-007 context supersedes an old context only when
the transition is explicitly recorded; a different context ID alone does not
prove a setup invalidation.

The local history is append-only, not a new global C-contract. There is no
current persisted C-023/C-025/C-070 store or lifecycle history to migrate. The
#89 implementation must add a schema migration for its lifecycle-event table
before persisting history; it must not backfill or rewrite prior artifacts.
The audit linkage uses the existing C-060 schema and persistence. If event and
audit persistence cannot be made atomic, the implementation must use a
deterministic idempotency key and fail closed until both records can be
resolved.

### 4. PERSONAL_SPOT_RESEARCH API boundary (#90)

The API exposes bounded list/detail reads over exact candidate, qualification,
evidence package, validation, C-026, C-070, and lifecycle records. Responses
include `contract_id`, `schema_version`, artifact ID, content digest where
available, exact `VersionReference` lineage, `as_of`, `valid_until`, current
projection state, and machine-readable reasons. Unknown schemas, stale state,
or unresolved lineage are represented explicitly and fail closed; the API
does not silently substitute a newer artifact.

One `POST` evaluation boundary may accept only references to a registered
strategy version and a current validated Spot market context. It invokes the
existing bounded domain pipeline and may create candidate/evidence/
qualification/NO_TRADE/qualified-signal artifacts according to their owners.
It accepts no caller-supplied market values, statistical results, gate
outcomes, invalidation results, or C-070 fields. It is idempotent on a
canonical digest of the exact request references and profile scope. Reads do
not cause re-evaluation or lifecycle mutation. There are no candidate CRUD,
qualification override, lifecycle-edit, approval, risk, order, or execution
routes.

List operations use bounded keyset pagination ordered by `(occurred_at,
event_id)`, with an opaque cursor bound to the exact filters and a page maximum
of 100. The only write-shaped operation is the bounded evaluate request that
live #90 authorizes; there are no separate create or mutation routes. It returns
the state projection and artifacts produced by the domain owners. #90 does not
recompute invalidation, expiry, supersession, WATCH, or qualification from raw
fields. WATCH is returned as unavailable/not produced for this profile. Detail endpoints enforce the same exact-reference and current-profile
checks. Responses use the existing RFC 9457 problem format, correlation IDs,
bounded fields, and `Cache-Control: no-store`; no raw prompts, hidden
reasoning, credentials, or unbounded nested source payloads are exposed.

For this local Personal Spot path, preserve the existing loopback-only API
guard and exact local-origin checks. The route/service boundary must accept a
future authorization dependency from #136 without treating loopback access as
authenticated identity. Do not open a non-loopback listener or add a bypass.
The UI work in #148/#149 remains blocked until its own #136/#142 gates pass.

## Lifecycle transition rules

The lifecycle projection is not a permission state machine. Required guards:

1. C-023 candidate → C-025 qualification/NO_TRADE, preserving the merged
   Wave 3 chain; never skip C-024v2/C-028v2/C-025v2.
2. Only C-025v2 qualified plus exact provenance → C-070v2 `QUALIFIED`.
3. C-025 `WATCH` and `REJECTED`, C-026 `NO_TRADE`, and C-070 `QUALIFIED` are
   distinct source outcomes. Do not coerce one into another.
4. `EXPIRED`, `INVALIDATED`, and `SUPERSEDED` append a lifecycle event; they do
   not mutate or delete the source artifact.
5. An input mismatch or unsupported schema blocks progression and produces
   C-026v2 `INVALID_PROVENANCE` when a NO_TRADE record is otherwise valid.
6. No lifecycle state grants risk approval, human approval, order intent,
   paper/testnet use, or live execution.

## Wave 5 provenance handoff

Wave 4 projections expose stable, version-qualified references needed by later
prospective research logging: C-026v2 decision ID/reference, C-070v2 qualified
signal ID/reference, exact C-021 strategy ID/version/digest, and exact
market/evidence references including C-006, C-007, C-003, C-008, C-009,
C-010, and C-069 where present. Consumers resolve by contract, schema, ID,
and digest; they do not reconstruct a decision from a mutable current
strategy or latest market snapshot. This enables later logging of both
NO_TRADE and qualified-signal decisions without adding outcome logging to
Wave 4.

Before Wave 5 relies on prospective measurements, manual owner-trade outcome,
cost, and baseline logging still needs an approved contract/scope decision.
This ADR defines no trade-outcome schema and does not treat app observations
as proof of an owner-placed trade.

## Contract-freeze matrix

| Area | Current source | Gap | Decision | Version impact | Producer changes | Consumer changes | Migration impact | Issue |
|---|---|---|---|---|---|---|---|---|
| Invalidation | C-021v1 prose; existing C-021 condition/group DSL | No typed targets or polarity | C-021v2 rules reference same-version condition/group IDs with PASS/FAIL and ANY/ALL; UNKNOWN is never proof | C-021 schema 2 only | #89 evaluates existing condition results and retained v2 rule metadata | #80/#81/#82 dispatch typed version; #89 consumes trigger | Additive strategy row; no rewrite | #89 / contract foundation |
| C-021 version dispatch | Registry protocol/store, codec, digest helper, resolved model currently accept v1 only | V2 cannot safely enter current runtime | Closed union and schema dispatcher; unknown schema fails closed; one existing DSL | C-021 v1 and v2 coexist | Registry and resolver become union-aware | #80/#81/#82 retain exact concrete version; #85/#87/#86/#88 preserve refs | Canonical envelope already stores discriminator; decoder change, no table DDL | Contract foundation |
| Personal Spot strategy upgrade | Current v1 strategy and governed registry | No approved invalidation rule set or SemVer increment policy | Same C-020 identity; new C-021v2 ID, parent prior where required, higher governed SemVer; exact triggers need separate bounded approval | New immutable C-021v2 record | Owner-approved strategy registration through RESEARCH/DRAFT | Candidate/evidence/qualification resolve exact v2 digest | No backfill or mutation; insert new record | Strategy configuration decision, then #89 |
| C-070 publication | C-070v1 UUID-only lineage and C-028 v1-style validation ref | Cannot verify exact C-024v2/C-025v2/C-028v2 lineage from signal | C-070v2 carries exact references for C-023/C-021/C-024/C-025/C-028 | C-070 schema 2 | #89 publishes only from current qualified C-025v2 and complete C-028v2 PASS | API/learning support version-qualified reference; unsupported readers reject | No current C-070 store; no backfill | Contract foundation, #89 |
| Expiry | Candidate, package, qualification, validation, gate and context validities | No common lifecycle expiry event | Effective expiry is earliest exact required-input expiry; append event at that instant | Local lifecycle event only | #89 | #90 projects; no source artifact mutation | New append-only event table; no history backfill | #89 |
| Invalidation | C-021v2 trigger results or valid material source change | Prose/stale/mismatched data cannot prove invalidity | Exact fresh trigger match or valid material change; otherwise block and issue truthful C-026 | C-021v2; C-026v2 already exists | #89 | #90 reads event projection | New events only | #89 |
| Supersession | No canonical predecessor field in C-023 | Recency alone is ambiguous | Local event binds prior and successor exact refs; same strategy ID/version digest, asset, instrument, timeframe, direction | Local event only | #89 records explicit successor | #90 reads both refs | No candidate rewrite | #89 |
| WATCH | C-025 vocabulary includes WATCH; current deterministic #86 producer does not emit it | No approved producer | Unavailable/not produced for PERSONAL_SPOT_RESEARCH | None | None until separately approved producer | #90 reports unavailable; #149 remains deferred | None | #89/#90; #149 later |
| Lifecycle history | C-060 audit plus no typed signal history | Audit fields alone do not hold typed transition provenance | Local immutable event plus C-060 linkage and idempotent atomic write/fail-closed recovery | Local record version, not global C contract | #89 | #90 read model | Add table migration; no backfill | #89 |
| #90 API | Live #90 permits read/create-evaluate boundaries | No strategy/signal router; evaluate semantics need limits | List/detail plus reference-only bounded evaluate; no CRUD/override/approval/risk/order/execution; projection comes from #89 | API representation only | #90 orchestration boundary | Clients consume exact refs/states | Event table from #89 only | #90 |
| #148/#149 | Live issues require #136 and #142; both open | Required auth/safety gates unmet | Keep deferred; no local-only exception | None | None | Start after both gates pass | None | #148/#149 later |
| Wave 5 handoff | C-026v2/C-070v2 and exact upstream refs | Manual owner-trade outcome/cost/baseline logging not yet governed | Expose stable refs now; approve logging contract/scope before Wave 5 measurements | No Wave 4 outcome contract | No outcome logger in #89/#90 | Wave 5 resolves stable refs | None now | Wave 5/#299 prerequisite |

## Compatibility, identity, and migration

| Surface | Existing | Proposed | Historical validity | Persistence / migration |
|---|---|---|---|---|
| C-021 | Schema 1 `StrategyVersion`, free-text invalidation concept. | Schema 2 adds typed invalidation rules referencing same-version condition/group IDs. | All v1 payloads and hashes remain valid; no rewrite. | No existing strategy-version artifact table or data migration. Registry must dispatch by schema. |
| C-070 | Schema 1 `Signal` with bare lineage UUIDs. | Schema 2 exact-reference lineage for C-023/C-021/C-024/C-025/C-028. | All v1 signals remain valid; no rewrite. | No current C-070 persistence. Registry and consumers must dispatch/reject unsupported schema. |
| Lifecycle history | No typed lifecycle history record/store. C-060 audit exists. | Local immutable event model plus audit linkage. | No prior lifecycle history to migrate/backfill. | New append-only table and forward migration required when #89 implements persistence; no backfill. |
| API | Current read-only Personal Spot routes and loopback guard; no strategy/signal router. | Bounded version-aware list/detail and one reference-only evaluate boundary. | No serialized API response fixture is a canonical contract. Existing routes remain. | No database migration beyond the lifecycle event table. API paths are additive and must be documented/tested. |

Both contract versions retain `canonical-json-v1` / `wire-1`. C-021v2 hashes
the complete typed C-021 schema-2 record except its self-referential digest;
C-070v2 hashes/serializes its complete exact lineage. No canonical serializer,
global contract version, or unrelated strategy contract is bumped.

The C-045 learning consumer stores typed contract references with
`schema_version`; it must accept and preserve C-070v2 references without
decoding C-070 payloads. Add an explicit compatibility test. Existing
risk/approval/execution consumers must reject unsupported C-070v2 until a
separate authorized consumer change; this research-only ADR does not add
execution support.

## Validation plan after approval

- Freeze byte/hash fixtures and closed vocabularies for C-021v1 and C-070v1.
- Test C-021v2 valid condition/group refs, duplicates, absent refs, trigger
  polarity, and canonical digest stability.
- Test that `UNKNOWN`, stale, future-dated, unsupported, and mismatched
  evaluation inputs cannot produce `INVALIDATED` or `QUALIFIED`.
- Test C-070v2 exact C-025/C-028/C-024/C-023/C-021 reference binding,
  qualification gate requirement, and expiry bounds; test unsupported-version
  rejection in v1 consumers.
- Test lifecycle transition matrix, idempotent deterministic event IDs,
  append-only behavior, duplicate/illegal transition rejection, expiry,
  invalidation, explicit supersession, and C-060 linkage.
- Test the additive lifecycle table migration, restart/replay, and consistency
  when audit persistence fails.
- Test API cursor/filter binding and bounds, exact reference resolution,
  stale/unknown response states, RFC 9457 errors, no-store/correlation
  behavior, loopback guard, and absence of approval/execution routes.
- Test C-045 learning preservation of C-070v2 references. Do not make a
  risk/execution consumer accept C-070v2 in this scope.

No tests were run for this architecture proposal; runtime implementation is
not authorized by this ADR.

## Security and safety impact

The proposed contracts and API do not grant authority. Invalidation is
deterministic only from exact versioned conditions and fresh typed inputs.
Unknown/missing/stale/mismatched inputs fail closed. C-023 confidence and
evidence-strength placeholders remain non-evidence and are not consulted.
Requests accept references, not caller-authored values or statistical gates.
The API preserves loopback-only operation and does not expose hidden reasoning
or secrets. C-060 audit linkage records transitions; the local event store
provides typed provenance. No risk, approval, order, exchange, paper/testnet,
or live capability is added.

## Implementation order after approval

1. Approve this ADR; add C-021v2 and C-070v2 contract types, serializers,
   registry/version entries, compatibility tests, and learning-reference test.
2. Implement #89 invalidation/expiry/supersession and append-only lifecycle
   storage against the frozen types; emit C-070v2 only from exact C-025v2.
3. Implement #90 read/evaluate APIs against the frozen lifecycle projection.
4. Run the integrated Wave 4 PERSONAL_SPOT_RESEARCH checkpoint.
5. Start #148/#149 only after their explicit #136/#142 gates pass; do not
   assign either issue before then.

## Approval record

Pending human repository-owner review. Until accepted, this proposal is not
implementation authority. No runtime code, schema, migration, or issue scope
has been changed by this proposal.
