# Version Registry

This registry defines the immutable baseline for governed artifact versioning.
It preserves exact historical resolution for trades, decisions, validations,
experiments, and rollback actions without redefining canonical contract
schemas.

## ADR-0019 — C-027 schema 3 compatibility foundation

Owner merge of #446 (`9f749089fb26d10c3914f47cf8d548d7e314945a`, 2026-11-09)
accepted additive `BacktestResultV3`, binding exact C-021v2, C-092/C-103,
C-027v2 cost assumptions and deterministic simulator/trace provenance. C-027v1
BacktestResult and C-027v2 CostAssumptionSetV2 retain their layouts, meanings and
identities. The generic canonical serializer continues to preserve all schemas.
The bounded lineage codec now dispatches C-027 schemas 2 and 3 explicitly; its
historical schema-1 rejection remains unchanged.

Schema-3 result identity is UUIDv5 under the namespace derived by
`uuid5(NAMESPACE_URL, "trading-platform:C-027:3:backtest-result-identity-v1")`.
Its name input is the canonical digest of all result fields except `result_id`
and `content_sha256`, including fixed metadata and explicit replay timestamps.
No wall-clock value or random identifier is generated during result building.
Canonical UTC normalization preserves identity across equivalent offsets.

Embedded dataset/manifest identities, coverage, cutoff, full digests and source
membership must agree. OBSERVED requires PASSED data-integrity and point-in-time
checks; FAILED/INCONCLUSIVE require explicit reasons. Missing metrics remain
`METRICS_NOT_COMPUTED`, and observed results never grant qualification. Fixed
Spot/BACKTEST metadata cannot be overwritten through the builder. Environments
are bounded to existing DEV/TEST enums for this foundation.

This contract/codec foundation does not implement a simulator, validate trace
authenticity, or publish durable results. Lineage-store append is explicitly
blocked until a governed simulation-trace resolver can prove the full closure.
No DDL, historical rewrite, cost/metric formula, OOS or execution is introduced.

## Issue #70 — C-062 AgentResult schema 1

C-062 schema `1` is a frozen, attributable result envelope bound to exact task
and context IDs, agent/version, C-067 routing decision, tool-access IDs,
generation/expiry times, result status, evidence references, unresolved risks,
and a typed output contract. Downstream validation requires a trusted caller
binding, context-resolved evidence IDs, and an allowlist of exact output
contract IDs, schema versions, and types; unknown output is rejected without
coercion. Confidence is bounded to
`0..1` and cannot be nonzero without supporting evidence; it remains an agent
assessment, not a probability or qualification. `NO_TRADE` and
`INSUFFICIENT_DATA` remain valid non-action outcomes. This does not add result
quarantine persistence, model invocation, approval, risk, or execution
authority.

## Issue #71 — C-061 AgentDefinition schema 1

C-061 schema `1` records an immutable `(agent_id, agent_version)` definition
with its bounded role, purpose, contract input/output allowlists, tool names,
allowed modes, dependencies, and non-escalatable authority boundaries. The
registry resolves an exact version and rejects attempts to redefine an
existing identity/version pair. A new role meaning requires a new
`agent_version`; it does not rewrite an older definition. The initial
`PERSONAL_SPOT_RESEARCH` registration is analysis-only, declares no tools, and
has no risk, human-approval, order, or exchange-execution authority. Registry
membership is descriptive metadata only: runtime grants remain owned by C-063
and C-064, subject to C-098 policy ceilings. Definitions are currently
code-registered in memory; durable persistence and lifecycle promotion are not
introduced by this issue.

## Issue #462 — bounded Spot producer method versions

The producer's unavailable-input methods are code-registered as
`spot-profile-technical-unavailable-adapter@1` for the typed C-012 UNAVAILABLE
assessment and `spot-profile-unavailability-severity@1` for its scoped C-069
projection. Their identities and the exact input closure are part of the
producer request key. These methods do not claim a technical-structure
calculation, confidence estimate, probability, or market-risk score. The
C-019 method/model/prompt route remains separately configured and allowlisted;
absence of that configuration blocks the model handoff.

## Issue #72 — C-063/C-064 permission enforcement

C-063 schema `1` binds one exact C-061 agent version, role, environment, and
mode to a C-098 policy ceiling, a bounded validity window, and explicit C-064
access IDs. C-064 schema `1` is one immutable tool/action/resource scope with
an append-only revision number. An
access is usable only when the exact tool, action, resource, environment, and
mode match both the C-061 definition and a C-098 grant, and the policy, profile,
grant, and access are all active. Wildcard scopes, unknown versions, missing
grants, expired state, and revoked state deny access. Every decision is
appended to C-060 before the result is returned; audit-store failure blocks the
request. Revocation appends a C-060 event and returns a new immutable revoked
revision while retaining the earlier record. The `PERSONAL_SPOT_RESEARCH`
agent currently declares no tools, so its runtime profile remains
deny-by-default with no tool grants.

## Issue #77 — C-066 AgentEvaluation schema 1

C-066 schema `1` is one immutable evaluation for exactly one C-062 `AgentResult`.
It binds the C-062 result ID/schema, task/context/correlation/trace IDs, exact
C-061 agent/version, the C-067 routing decision (including provider/model and
prompt ID/version), output contract/schema when resolvable, evaluation method
ID/version, deployment environment, research mode, route-decision/result
timestamps, evaluated-at time, route-to-result duration when the timestamps
establish a valid order, and applicable failure/schema state.
Invocation/evaluation outcome, C-062 result status, and schema validity are
separate axes. `COMPLETED`, `FAILED`,
`TIMED_OUT`, and `REJECTED_INVALID` are evaluation outcomes; C-062 statuses
including `NO_TRADE` and `INSUFFICIENT_DATA` remain unchanged. Unknown or invalid
output fails closed.

Grounding preserves exact supporting/contradicting evidence IDs, method
`personal-spot-c062-result-validation` version `1`, and a bounded state that
reports reference presence/allowlist validation only; it is not an evidence
quality score. Calibration/reliability are optional C-031/C-052 references only.
No aggregate statistics are generated by schema 1. A real labelled dataset,
approved method, sample/window definition, and uncertainty/limitations are
required before calibration values can be produced.

The schema contains no raw prompt, credential, secret, or private reasoning
fields. It grants no permission or approval authority and cannot change model,
prompt, strategy, risk, or execution behavior. The implementation is bounded to
the current `PERSONAL_SPOT_RESEARCH` result-validation path; evaluation records
are returned as typed values and are not persisted. Existing structured logging
may be used only as an optional safe projection. OD-0016 remains Open; this
schema selects no observability backend, vendor, collector, or topology.

## Required immutable registry record

| Registry field | Required content | Baseline rule |
|---|---|---|
| Artifact identity | stable artifact type and stable artifact ID | artifact identity is permanent and distinct from any version ID |
| Version identity | immutable version ID / semantic label for one exact meaning | any new meaning, configuration, ruleset, or behavior requires a new version |
| Content / configuration hash | deterministic hash of governed content and configuration | identical version ID must always resolve to the same content hash |
| Lineage | parent version, supersedes target, rollback target where applicable | lineage is append-only and must preserve historical ancestry |
| Lifecycle status | `DRAFT`, `CANDIDATE`, `VALIDATED`, `APPROVED_FOR_SHADOW`, `APPROVED_FOR_PAPER`, `APPROVED_FOR_PRODUCTION`, `ACTIVE`, `REJECTED`, `RETIRED`, `ROLLED_BACK` as applicable | drafts/candidates are not production authority; shadow/paper/production-eligible progression is governed and status changes are append-only events, not in-place rewrites |
| Governance identity | creator, governed approver, and governing decision authority | creation and promotion are attributable and machine-verifiable |
| Timestamps | created, approved, effective, retired timestamps | time fields record when the version existed, not when history is viewed later |
| Compatibility constraints | contract/schema compatibility, required consumers/producers, migration notes | incompatible or unresolved compatibility blocks governed use |
| Dependency constraints | exact dependent versions or allowed ranges with mode/environment scope | safety-critical paths must resolve dependencies exactly, not heuristically |
| Validation / evidence references | validation results, datasets, experiments, shadow/paper evidence, supporting audit links | promotion requires applicable evidence for the artifact class |
| Governance / audit references | governance decision, audit event, release gate, incident, exception references | every promotion, rejection, retirement, or rollback must be auditable |
| Rollback references | governed rollback pointer/state change and superseded active reference | rollback creates a new governed state/pointer and never rewrites historical records |
| Environment / mode eligibility | allowed environments and operating modes (`Research`, `Backtest`, `Paper`, `Shadow`, `Testnet`, `Live` when later approved) | eligibility limits where a version may run; it does not grant per-trade authority |
| Historical resolution | exact lookup material needed to reconstruct prior trades, approvals, validations, experiments, and deployments | missing, unknown, or incompatible resolution fails closed for safety-critical paths |

## Artifact coverage baseline

| Versioned artifact class | Minimum versioned content |
|---|---|
| Strategy / parameters | strategy identity, rules, parameter set, qualification criteria, supported regimes, parent version |
| Model / provider | provider, model family/version, routing constraints, configuration, safety/usage constraints |
| Prompt / template | prompt/template content, variables, guardrails, intended task scope, linked model constraints |
| Agent configuration | allowed tools, role constraints, routing/runtime configuration, safety limits |
| Dataset / source mapping | dataset composition, source lineage, provider mapping, sampling/partitioning rules |
| Feature / indicator | deterministic calculation definition, parameters, dependencies, and methodology category |
| Validation methodology | backtest/OOS/WF/robustness/bias-check methodology and assumptions |
| Risk model / policy | deterministic risk formulas, veto rules, leverage/liquidation constraints, policy thresholds |
| Safety policy | readiness, incident, prompt-injection, permission, kill-switch, and fail-closed rules |
| Contract / schema | canonical contract/schema version, compatibility status, migration reference |
| API | endpoint/interface shape, behavior contract, compatibility/deprecation status |
| Application release | application build/release identity, included governed version set, release gate reference |
| Infrastructure / configuration | deployment/runtime configuration, environment scope, dependency bindings |
| Experiment | hypothesis linkage, experiment design, candidate versions under test, evaluation scope |

## Lifecycle and promotion rules

| Rule | Required behavior |
|---|---|
| New meaning = new version | changing strategy logic, parameters, prompts, models, policies, contracts, dependencies, or governed configuration creates a new immutable version |
| Drafts and candidates | `DRAFT` and `CANDIDATE` versions may be reviewed or validated, but they are never production authority |
| Validation before promotion | applicable validation/evidence must exist before `APPROVED_FOR_SHADOW`, `APPROVED_FOR_PAPER`, `APPROVED_FOR_PRODUCTION`, or `ACTIVE` status is granted |
| Explicit governance | promotion, rejection, retirement, and rollback require an explicit governed decision with audit references |
| Learning boundary | learning/research may propose candidate versions and experiments, but cannot promote, activate, or retire production authority |
| Rollback | rollback is an auditable governed pointer/state change to another known-good version; it never mutates historical version records |
| Eligibility vs authorization | `APPROVED_FOR_PRODUCTION` (production-eligible) or `ACTIVE` never bypasses readiness, deterministic risk, human approval, idempotency, reconciliation, or execution gates |
| Fail-closed resolution | missing, unknown, incompatible, or unverifiable version resolution blocks safety-critical approval/execution/use until corrected |

## Historical reconstruction baseline

Every historical trade, approval, validation, experiment, governance decision,
and release must resolve the exact version IDs and hashes for the governed
artifacts it depended on. Pointer changes such as activation, retirement, or
rollback are new auditable records layered on top of immutable version records,
never history rewrites.

## Issue #45 historical evidence extension

C-101 HistoricalUniverse, C-102 ObservationRevision and C-103
ReconstructionManifest are additive schema-1 contracts approved by the owner
on 2026-09-28. Existing contract/schema and payload versions are unchanged.
They use the existing canonical JSON and SHA-256 machinery; no migration of
stored legacy payloads is required. Older consumers must reject unknown
contract IDs rather than interpret these as legacy dataset records.

Universe effective intervals are half-open; publication/ingestion/availability
times remain separate. A complete universe version is selected by a trusted
pin, and older memberships remain immutable after delisting. Revision chains
must have one root, explicit predecessors, no forks/cycles, and nondecreasing
publication/ingestion/availability times. Equal timestamps are resolved only
by explicit ancestry. Missing ancestry blocks reconstruction.

`historical-selection-v1` filters by availability at the requested cutoff,
then selects chain tips within the pinned universe. The manifest hashes the
universe, all eligible revision ancestry, source records, selected revision
IDs and C-092 reference/lineage. Later unavailable revisions do not enter an
earlier manifest. Selection coverage requires an observation for every member;
it does not certify continuous per-timeframe coverage (C-003 remains required).
Trusted upstream provenance must establish completeness, authentic finality,
and stable observation keys. C-092 source membership includes the universe
and eligible ancestry used to make the selection; unrelated/future sources
cannot silently enter that exact dataset. #46 owns persistence and immutable
ID/content binding, not new selection semantics.

## Issue #335 — C-003 schema 2 compatibility

[`ADR-0008`](../adr/ADR-0008-versioned-c003-v2-compatibility.md) records the
owner-approved additive C-003 v2 boundary. C-003 schema `1` remains byte- and
identity-compatible; schema `2` uses the existing `wire-1` envelope and a
distinct typed model selected by `schema_version`. No global schema or
canonicalization version changes.

The lineage key remains `(C-003, report_id, schema_version)`: schema 1 keeps
version `1`, while schema 2 uses version `2`. The existing key/unique constraint
already includes `version`, so there is no DDL, rewrite, backfill, or v1
reinterpretation.

This release provided codec and lineage read compatibility only. General v2
writes, producers, and analysis-consumer migration remain disabled/deferred.
Before any producer is added, it must resolve an exact recognized
assessment-policy ID and version and verify any `NOT_APPLICABLE` permission.
Revalidate every receiving reader, add consumer dimension-required checks, and
independently review/approve enabling writes for that consumer before rollout.

### Issue #375 — in-memory Spot OHLCV producer and C-005 consumer

The owner approved an in-memory C-003 schema-2 producer for the existing Spot
OHLCV regime calculation. Its policy ID remains
`personal-binance-spot-ohlcv-v1`; the resolved assessment-policy version also
binds the supported instrument, timeframe, exact closed-candle window and
cutoff. The approved one-interval freshness allowance, zero missing-interval
tolerance, metric bounds, required OHLCV fields, and single-source semantics
are unchanged. The v2 dimension values are derived from the existing
deterministic v1 assessment, then each dimension is bound to the canonical
C-002 snapshot digest. The resulting report identity is stable for the same
snapshot, policy scope and assessment time.

The C-005 Spot regime, moving-average and realized-volatility gates validate
the exact resolved C-003 schema-2 report and reject mismatched snapshot,
source membership, policy, timeframe, window, cutoff or digest evidence. C-003
schema-1 serialization and API quality projection remain unchanged. General
C-003 schema-2 persistence and generic lineage writes remain disabled; a
later, narrow personal Spot analysis-lineage exception is recorded under
Issue #74 below.

## Issue #341 — C-006/C-007/C-008 schema 2 and C-104

The repository owner approved the additive Option 2 direction in merged PR
#340 for issue #338. C-006/C-007/C-008 schema `1` payloads, identities, and
readers remain unchanged. Schema `2` is selected explicitly under the same
contract IDs and `wire-1`; no implicit v1-to-v2 conversion is permitted.
C-104 `OrderFlowAssessment` is the sequential additive schema-1 contract
recorded in the domain registry. C-003 v2 remains in-memory only; this change
does not enable its lineage writes or persistence.

Before C-104's first merge, its schema-1 metric set was completed to preserve
each agreed #60 output independently: best bid/ask, midpoint, absolute spread,
spread bps, bid/ask depth and notional, book imbalance, trade-record count,
buy/sell aggressor volume, volume delta, and cumulative delta. Each is a typed
metric component with its own value/unit, state, calculation time/window, method
version, evidence IDs, and one modality binding. Trade-record count is an
integer with `trades` unit; spread bps uses `bps`. This completes the proposed
unreleased schema-1 allocation and does not introduce a cross-modal metric or
calculation/runtime behavior.

C-104 declares distinct base and quote units. Price and notional metrics use
the quote unit; depth and trade-volume/delta metrics use the base unit;
imbalance uses `ratio`; spread bps uses `bps`; and trade-record count uses
`trades`. Assessment validation checks the declared base/quote units against
the exact resolved C-003 policy for each used modality.

Canonical dependency digests for C-001 observations, C-002 snapshots, C-003
schema-2 reports, C-091 source records, and C-092 dataset versions are
`SHA-256(canonical_json_dumps(record).encode("utf-8"))`, using the existing
canonical JSON v1 serializer over the complete typed record, including its
`contract_id` and `schema_version` metadata. References separately preserve the
exact lineage version: C-003 schema `2` resolves to lineage version `2`; the
other referenced schema-1 records use their contract-specific lineage identity
(the C-092 dataset version is its lineage version). No C-003 writer or store is
used.

The C-007 schema-2 manifest `content_sha256` preimage is the canonical
`wire-1` contract envelope (`canonicalization_version`, `contract_id`,
`schema_version`, `payload_version`, and `payload`) with only
`payload.content_sha256` omitted. This avoids a self-referential hash and
includes the C-007 schema version in the digest. C-008 schema-2 evidence uses
the same typed-record canonical JSON digest as other dependency records; its
canonical wire document includes the full evidence payload and fixed contract
metadata in the envelope. Repeated encoding and hashing must be deterministic.

C-007 bindings are ordered by modality then snapshot ID and close over the exact
C-002 membership, C-001 observations, C-091 sources, and optional C-092
dataset. C-008 expiry cannot exceed its referenced manifest or dependency
expiry; C-006 and C-104 expiry cannot exceed the manifest. Unknown schemas,
policies, missing/duplicate references, stale inputs, and digest mismatches
fail closed. Book point-snapshot continuity may be N/A only under the exact
resolved policy; sequence metrics require measured passing continuity.
In-memory resolvers take an explicit validation time rather than consulting
the wall clock implicitly; expired manifests, dependencies, evidence, and
assessments reject at that time.

## Issue #370 — C-006/C-007 schema 3 and C-009/C-010 schema 2

C-009/C-010 schema 1 remains unchanged. Schema 2 is an explicit additive
version; no numeric evidence-strength or severity value is converted to or
from the new categorical vocabularies. C-009 evidence strength uses
`VERY_STRONG`, `STRONG`, `MODERATE`, `WEAK`, or `UNKNOWN`; dependence is an
independent required dimension. Components sharing an input binding cannot
claim independence. Shared OHLCV-derived indicators are dependent/correlated;
a single OHLCV snapshot cannot establish statistical independence. Analytical
confidence is interpretive only—not trade-success probability, profitability,
expected return, expected value, or win rate—and when unavailable carries
neither a numeric value nor a method reference.

C-009 indeterminate status and reason codes preserve missing, partial, invalid,
stale, or insufficient evidence without manufacturing neutral, zero, aligned,
or confidence values. C-010 schema 2 uses `LOW`, `MODERATE`, `HIGH`, `CRITICAL`,
or `UNKNOWN` severity and validates its categorical severity against the
versioned decision table:

| Severity | Required finding |
|---|---|
| `LOW` | Localized disagreement with no material change to interpretation. |
| `MODERATE` | Disagreement affects a material interpretation but has no direct opposing validated conclusion. |
| `HIGH` | Direct opposition between valid, materially relevant conclusions. |
| `CRITICAL` | A conflict invalidates a required premise or makes the analysis unsafe to rely on. |
| `UNKNOWN` | Evidence cannot establish materiality. |

Evidence-establishment status and resolution status are separate. Severity
does not itself create a trading gate. Absence of a C-010 record means there is
no conflict assessment; `NONE` is not a severity.

C-006 schema 3 references the exact C-007 schema-3 manifest and embeds only
C-009/C-010 schema-2 records. Existing C-006 schema 1/2 and C-007 schema 1/2
readers and payloads remain unchanged. The C-007 schema-3 output reference
binds every C-009/C-010 assessment and its referenced C-093 report by contract
ID, record ID, schema version, lineage version, and canonical content digest.
It also binds the source C-002 snapshots, exact C-003 schema-2 reports and
C-008 evidence through the manifest input bindings and evidence membership.
The context and assessments refer to the manifest by immutable ID/schema to
avoid a circular digest; the manifest digest then commits to the canonical
digests of the outputs.

The C-007 schema-3 `content_sha256` uses the existing `wire-1` envelope and
`canonical-json-v1` serialization, omitting only its own
`payload.content_sha256` from the hash preimage. Every output digest is
`SHA-256(canonical_json_dumps(typed_output).encode("utf-8"))`. Unsupported or
mismatched nested schema versions, output identities/digests, evidence
membership, snapshots, reports, stale inputs, or status/reason combinations
fail closed. C-093 remains owned by issue #67; this addition defines only its
typed output reference and does not duplicate its report implementation. Since
the C-093 schema/lineage registry is owned by #67, C-006 v3 validation requires
the caller to provide the exact supported C-093 output references resolved by
that registry; an opaque reference alone does not establish version support.

This is a contracts/codec/validation addition only. It enables no producer,
confluence/conflict calculation, persistence, strategy eligibility, signal,
risk, approval, trading, or execution behavior. C-009/C-010 v2 consumers must
remain disabled until profile-specific methodology is separately implemented
and tested.

## Issue #374 — Additive Spot OHLCV analysis path

Issue #374 adds explicit schema dispatch while retaining every existing
contract version and historical digest:

| Contract | New schema / lineage | Binding rule |
|---|---:|---|
| C-005 | `1 / 1` (current `MarketRegime`) | C-007 v4 references its canonical typed-record digest; the record must match the exact instrument, timeframe, snapshot as-of, expiry, and C-008 evidence set. |
| C-007 | `4 / 4` | One bounded Spot-profile `spot-ohlcv` binding; references exact C-002/C-003 v2, C-001/C-091 records, C-005 v1, and C-008 v2. |
| C-008 | Existing `2 / 2` | No contract change. The v4-specific closure validator proves binding, observation/source membership, quality, method, cutoff, and expiry against the resolved C-007 v4 binding. |
| C-009 | `3 / 3` | Preserves #370 categorical strength, dependence, status/reason, and non-probabilistic confidence semantics; requires C-007 schema 4 and a C-093 reference accepted by the C-093 owner's registry. |
| C-010 | `3 / 3` | Preserves #370 categorical severity and decision table; requires C-007 schema 4. |
| C-006 | `4 / 4` | References the exact C-007 v4 digest and embeds only the C-009/C-010 v3 forms. |

C-007 v4 uses the existing `canonical-json-v1` / `wire-1` envelope. Its
`content_sha256` preimage includes `canonicalization_version`, contract ID,
schema version, payload version, and every payload field except its own
`payload.content_sha256`. Dependency and output digests use
`SHA-256(canonical_json_dumps(typed_record).encode("utf-8"))`. The new OHLCV
binding explicitly records timeframe and coverage window; resolver validation
delegates the approved C-003 v2 policy/window checks to the existing
`validate_spot_ohlcv_quality_v2` gate. No C-003 writer, persistence, migration,
or producer behavior is enabled.

The implementation fixes C-005's current model identity as schema/lineage
`1/1` from the existing `MarketRegime` contract, and C-008 schema/lineage as
`2/2` from its existing versioned model. At the time #374 was implemented,
C-093 intentionally remained unversioned; the reference boundary did not
assume its schema or lineage. Issue #67 now registers the first canonical C-093
version and its resolver below.

Shared C-009 components over the single OHLCV binding cannot claim
`INDEPENDENT`; the versioned contract makes dependence explicit and does not
infer independence from multiple derived features. Unknown versions, stale or
invalid quality, source/snapshot/window mismatch, incomplete evidence closure,
tampered digests, unsupported C-093 references, and expiry violations fail
closed. All changes remain analysis-contract and validation only: no
confluence/conflict calculation, C-093 implementation, API projection,
strategy eligibility, validation, risk, approval, order, or execution behavior
is enabled. #67 remains the sole owner of C-093 and calculations; #68 remains
downstream. The 13-chat target and full Chat 5 requirements remain open, and
held issues #39–#43 are unchanged.

## Issue #67 — C-093 and deterministic Spot meta-analysis

| Contract / method | Schema / lineage or method version | Binding and calculation rule |
|---|---:|---|
| C-093 `AgentIndependenceReport` | `1 / 1` | Canonical immutable report; exact C-002 snapshot and digest, C-007 v4 manifest ID/schema plus canonical binding digest, C-005 regime and digest, C-003 v2 quality identity/digest, evidence/source/observation IDs, time window, methods, and expiry. The final manifest digest is excluded to avoid a self-reference cycle. |
| C-093 reference | `agent-independence / c093-deterministic-v1` | Resolved only by `C093Registry`; full contract/id/schema/lineage/method/digest match required. |
| C-009 Spot confluence | `spot-confluence / spot-confluence-v1` | C-005 direction plus READY findings bound to the same validated C-007 v4 scope; preserve per-component strength and dependence, but aggregate status remains INDETERMINATE/UNKNOWN because the single OHLCV source cannot establish independent evidence streams. |
| C-010 Spot conflict | `spot-conflict / spot-conflict-v1` | Record only actual opposing directions from the exact regime/findings; severity follows the C-010 categorical table; missing materiality is UNKNOWN and CRITICAL requires explicit unsafe/invalid-premise evidence. |

Shared source, observation, or binding evidence records `PARTIALLY_DEPENDENT`;
shared windows/methods/agent/model/prompt also record partial dependence.

## Issue #74 — durable personal Spot analysis lineage

Merged PR #412 accepted ADR-0012. Its implementation scope enables only the
exact personal, local Spot refresh closure: C-003 schema/lineage `2/2`, C-005
`1/1`, C-007 `4/4`, C-008 `2/2`, and C-093 `1/1`, with the exact C-002/C-001/
C-091 parents already present in the append-only lineage graph. The refresh
path writes the immutable analysis association; GET resolves it read-only and
revalidates current freshness. Existing snapshots without the association and
stale/corrupt/mismatched closures remain analysis-unavailable. This exception
does not authorize general C-003 v2 writes, additional profiles, or any
strategy, risk, approval, paper/testnet execution, or live-trading behavior.
No observed overlap is `UNKNOWN`, never `INDEPENDENT`. These are categorical
evidence-overlap labels, not estimates of statistical correlation. Distinct
feature names, methods, agents, models, or prompts cannot establish
independence. C-009 does not count or weight correlated findings and therefore
keeps the current single-source Spot profile INDETERMINATE; it does not compute
probability, win rate, expected return, or profitability. This
analysis-only implementation does not alter C-006, create strategy/risk
eligibility, resolve conflicts, or enable approvals or execution. Full Chat 5
and held issues #39–#43 remain open/on hold; #68 remains downstream.

## Issue #379 — accepted C-019/C-006 Spot adversarial version path

[`ADR-0010`](../adr/ADR-0010-proposed-c019-v2-c006-v5-spot-adversarial-path.md)
records the human repository owner's explicit approval of Option A on 2026-10-19:

| Contract | Approved schema / lineage | Approved binding |
|---|---:|---|
| C-019 `AdversarialAssessment` | `2 / 2` | Embedded in C-006 v5; binds the exact C-007 v4 manifest ID/digest, Spot instrument/timeframe/window and cutoff, C-003 v2 report ID/digest, exact usable C-008 v2 evidence references/digests and source/observation lineage, as-of/expiry, and exact method/model/prompt version references. |
| C-006 `MarketContext` | `5 / 5` | References the exact C-007 v4 manifest and embeds C-019 v2; preserves C-009/C-010 v3 and existing C-093 reference behavior. |

The approved version path is implemented by issue #381 after ADR-0010 was
accepted and merged. C-019 v2 remains outside the C-007 v4 output closure,
avoiding a digest cycle; contradictory evidence must belong to the exact usable
C-008 set already closed over by that manifest. C-019 v2 captures the exact
manifest and C-003 v2 references, Spot instrument/timeframe/window/cutoff scope,
usable C-008 content digests and source/observation lineage, and explicit
method/model/prompt version references. Its consumer validator resolves those
references against the same C-007 v4 manifest and requires exact supported
method/model/prompt versions and the confidence method when available. All
C-006 v1–v4, C-007 v1–v4, C-009/C-010 v1–v3, C-019 v1, and C-093 v1 payloads
and readers remain unchanged.

Analytical confidence is interpretive only, never a probability. C-019 v2 uses
a required discriminated state: `AVAILABLE` includes a bounded numeric
interpretive value and its exact confidence method/version reference;
`UNAVAILABLE` includes an explicit reason and no value or method. Consumers
must handle either state explicitly; no zero, default, or fabricated value is
permitted. No strategy eligibility, signal qualification, validation, risk,
approval, order, or execution authority is added. Issue #68 remains blocked
until this contract implementation is merged; its producer/consumer work remains
separately bounded.

## Issue #428 — direct-owner governance provenance

| Governance artifact | Version | Compatibility and binding |
|---|---:|---|
| Dispatched-agent reviewer request | `1.0` | Existing request shape remains unchanged and requires agent role plus the governed implementation session. |
| Direct-owner reviewer request | `1.1` | Explicit `DIRECT_OWNER`, `github-user:<controller>` implementation identity, and controller identity; no agent role or agent session fields. Binds repository, linked issue, PR, exact head, `dev` base, derived review tier, bounded context, and required checks. |
| Dispatched-agent review provenance | `1.2` | Existing artifact signature and implementation-session semantics remain unchanged. |
| Direct-owner review provenance | `1.3` | Additive signed artifact with explicit origin, owner/controller identity, `dev` base, linked issue, PR/head, derived tier, current-head independent reviewer identity/session, producer/run, timestamp, disposition, and typed review evidence. R1 binds a trusted current-head GitHub review; R2/R3 bind the existing model result and handoff. Agent-only fields are forbidden. |

Consumers select owner provenance only when the authenticated PR author is the
configured controller and require schema `1.3`; they do not infer owner origin
from missing agent fields. Both origins require current-head review, successful
configured deterministic checks, substantive governance validation, and human
merge authority. Synchronizing a PR head invalidates prior provenance. No
historical `1.2` artifact is migrated or rewritten.

## ADR-0015 — Wave 3 qualification contract versions

The owner-approved additive boundary is recorded in
[`ADR-0015`](../adr/ADR-0015-wave-3-prequalification-evidence-and-statistical-qualification-contract-boundary.md).
The approved scope is `PERSONAL_SPOT_RESEARCH`; it grants no risk, human
approval, order, paper/testnet, or live-execution authority.

| Contract | Schema 1 | Schema 2 | Compatibility and identity |
|---|---|---|---|
| C-024 SignalEvidencePackage | Historical package/graph semantics remain frozen, including the v1 qualification-node topology. | `SignalEvidencePackageV2` uses `EvidenceGraphV2`, ending at the exact C-023 candidate; includes explicit upstream provenance and C-093 dependence including `UNKNOWN`; package ID is UUIDv5 derived from the canonical content SHA-256. | Distinct `schema_version`; no v1 reinterpretation, rewrite or backfill. Digest covers schema and all package references/content. |
| C-025 SignalQualification | Existing nullable validation and generic rule-result semantics remain historical only. | `SignalQualificationV2` binds candidate, strategy version, C-024v2, C-028v2 result and expiration; QUALIFIED requires C-028v2 PASS and every mandatory gate PASS. | New typed consumer model and schema discriminator; old readers must reject unknown v2 rather than coerce. |
| C-027 BacktestResult | Numeric research assumptions retain existing semantics. | `CostAssumptionSetV2` and `ResearchAssumptionV2` add APPLICABLE / NOT_APPLICABLE / UNKNOWN; Spot funding applicability is explicit and NOT_APPLICABLE without numeric value. | Additive schema-2 value-object boundary; NOT_APPLICABLE requires rationale/provenance; UNKNOWN cannot pass cost applicability. |
| C-028 ValidationResult | Existing Chat 7 validation output remains unchanged. | `QualificationValidationResultV2` binds separately versioned rule configuration, observed conditional rate/sample/expectancy, statistical-support references, authoritative gates and freshness. Outcomes are PASS / FAIL / INSUFFICIENT_VALIDATION. | Exact strategy, candidate, package digest, methodology and rule scope are hashed; equality meets the rate gate only. |

The current persistence model does not store C-024/C-025/C-027/C-028 artifacts;
this contract foundation therefore adds no database migration. If persistence
is added or changed later, resolution must include schema version in its key,
and prior v1 lookup remains available. Existing `wire-1` canonical JSON and
SHA-256 machinery remains in use; no global canonicalization change occurs.

## ADR-0016 — C-026 invalid-provenance reason

[`ADR-0016`](../adr/ADR-0016-c026-v2-invalid-provenance-reason.md) versions
the C-026 reason vocabulary without changing the v1 enum or historical
artifacts.

| Contract | Schema 1 | Schema 2 | Compatibility and identity |
|---|---|---|---|
| C-026 NoTradeDecision | `NoTradeDecision` and its closed `NoTradeReason` vocabulary remain unchanged. | `NoTradeDecisionV2` reuses the v1 field shape; `NoTradeReasonV2` adds exactly `INVALID_PROVENANCE`. | Existing canonical JSON envelope carries schema `2`; older schema-1-only readers reject it as unsupported. No v1 rewrite/backfill. |

Both schemas use the current `canonical-json-v1` / `wire-1` mechanism. Schema
and reason are part of serialized content and its digest. C-045 learning stores
versioned C-026 references without decoding the payload, so it needs no schema
change. The current repository has no C-026-specific persistence or runtime
producer; no DDL, migration, or backfill is needed. Future C-026 persistence
must key/read by schema version.

## ADR-0017 — Wave 4 C-021/C-070 schema compatibility foundation

[`ADR-0017`](../adr/ADR-0017-proposed-wave-4-lifecycle-api-and-invalidation-boundary.md)
was accepted by the repository owner through PR #442. This contract-foundation
slice adds typed schema-2 meanings while preserving all schema-1 records and
hashes. It does not implement #89 lifecycle runtime or #90 APIs.

| Contract | Schema 1 | Schema 2 | Compatibility and identity |
|---|---|---|---|
| C-021 StrategyVersion | Frozen `StrategyVersion` and existing content-hash preimage. | `StrategyVersionV2` adds non-empty `InvalidationRuleSetV2` referencing exact same-record conditions/groups with PASS/FAIL and ANY/ALL. | Closed `(C-021, schema_version)` registry dispatch preserves concrete type; no down-conversion. V2 hashes the complete schema-2 record except its digest. Personal Spot v2 is semantic `2.0.0`, parented to immutable v1.0.0, and configures every required group as CONDITION_GROUP/FAIL with ANY. |
| C-070 Signal | Frozen qualified-only `Signal` with legacy `SignalLineage`. | `SignalV2`/`SignalLineageV2` bind C-023v1, C-021v2, C-024v2, C-025v2, and C-028v2 references and construct deterministic UUIDv5 identity from canonical signal content. | V1-only consumers remain unsupported for v2 and must reject it. C-070v2 requires qualified status and PASS validation gates; its expiry is bounded by upstream validity. No risk, approval, order, or execution fields are introduced. |

C-021 row persistence already stores the canonical envelope and digest, so
schema dispatch requires no DDL or historical rewrite. The strategy store
accepts only exact v1/v2 model types and rejects unknown schema discriminators.
C-045 accepts C-070 references in its existing version-qualified reference
record and preserves them without decoding the signal payload. Existing
C-023/C-024v2/C-025v2/C-026v2/C-028v2 meanings are unchanged. Lifecycle events,
expiry processing, invalidation evaluation, supersession, WATCH, persistence,
and API routes remain assigned to later issues.


## ADR-0022 — C-071

V1 payload/UUID dataset/identity/qualification readers stay frozen. Observation-only v2 binds native C-092 IDs/versions, C-027v3 runs, dataset/manifest, #94 reports and protocol/journal; zero/unavailable/inconclusive/contaminated samples remain explicit. Closed codec 1/2, no conversion; UUIDv5 excludes own ID/digest, method `spot-oos-observation-v1`. V2 qualification and C-071 retention rejected; no migration/DDL.

Internal SPOT_OOS_REQUEST@1 binds request/archive/data/execution/parameter/cost/timestamps, without retention authority. Require canonical artifacts/reports and live issuance/recomputation. As-of equals held-out request/replay; expiry cannot exceed request/any replay. [ADR](../adr/ADR-0022-spot-oos-protocol-and-result-boundary.md).

## ADR-0023 — C-029

C-029v1 payloads, identities, and consumers remain unchanged. Observation-only
schema 2 binds an immutable Spot walk-forward protocol and all planned folds to
their exact C-071v2 results, C-027v3/#94 reports, native dataset/manifest pins,
and shared journal receipts. Explicit unavailable and terminal states are
preserved; canonical construction and decoding enforce aggregate and outcome
closure. UUIDv5/SHA-256 identities exclude generated result ID and own digest.
Unknown versions fail closed. V2 qualification and C-029 retention are denied;
codec support is not storage authorization. No migration or DDL.
[ADR](../adr/ADR-0023-spot-walk-forward-observation-boundary.md).

## ADR-0024 — C-072

C-072v1 payloads, identities, and consumers remain unchanged. Observation-only
Spot schema 2 binds exact C-027v3/#94 evidence, the source return-series digest,
timeframe, block length/horizon, signed seed, versioned PRNG/index mapping,
fixed 10,000-path budget, Decimal statistics, and nearest-rank quantiles.
Unknown versions fail closed. Schema 2 is not accepted by C-030/qualification
consumers and cannot be retained by the lineage store; codec support is not
storage authority. No migration or DDL.
[ADR](../adr/ADR-0024-spot-monte-carlo-observation-boundary.md).

## ADR-0025 — C-073

C-073v1 payloads, identities, and consumers remain unchanged. Observation-only
Spot schema 2 binds a frozen one-parameter grid and separate fee/spread/slippage
stress scenarios to exact C-027v3 replays and recomputed `SpotPerformanceReport`
reports, shared data/time/strategy scope, `MetricsPolicy`, assumptions, and
timestamps. All tested points and descriptive Decimal deltas/flags are retained
in the result; no optimal parameter is selected. Unknown versions fail closed.
V2 is not accepted
by C-030/qualification consumers and cannot be retained by the lineage store;
codec support is not storage authority. No migration or DDL.
[ADR](../adr/ADR-0025-spot-sensitivity-observation-boundary.md).

## ADR-0026 — C-074

C-074v1 and its consumers remain unchanged. Observation-only Spot schema 2
binds a frozen ordered request/policy plan to each exact C-027v3 replay,
`SpotPerformanceReport`/`MetricsPolicy`, and archived decision-time
C-005/C-006v5/C-007v4/C-008 evidence closure.
Required contexts remain explicit, with all additional observed contexts
retained in first-occurrence order. Metrics preserve independent availability,
units, samples, warnings, and reasons; no aggregation pools samples or returns.
Unknown versions fail closed, and no C-030/C-028 qualification or lineage
retention authority is added. [ADR](../adr/ADR-0026-spot-regime-validation-observation-boundary.md).

`SpotPerformanceReport` and `MetricsPolicy` are implementation-level Spot
metrics artifacts, not C-094 contracts. C-094 remains the registered
`BiasCheckReport`.

## ADR-0027 — C-094

C-094v1 payloads, identities, and consumers remain unchanged. Observation-only
Spot schema 2 binds an exact C-027v3 replay request/result/trace, C-021v2
strategy, and C-092/C-101/C-102/C-103/C-091 archive closure. The lineage codec
adds closed schema-2 support; C-094v1 codec behavior remains unchanged and
unsupported schema versions fail closed. All nine
bias categories are emitted once, but only point-in-time and look-ahead checks
may be supported by a trusted replay. The remaining seven are inconclusive with
explicit reasons. C-094v2 is not accepted by qualification and cannot be
retained by the lineage store; codec support is not storage authority. No
migration or DDL. [ADR](../adr/ADR-0027-spot-bias-observation-boundary.md).

## ADR-0028 — C-105

C-105 schema 1 is an observation-only record built from one exact OOS protocol,
the supplied process-local journal prefix, and an issued C-071v2 result. It
preserves subsequent protocol-bound events, including incomplete and aborted
attempts, and exact C-027v3/#94 references where present. The frozen correction
status is `NOT_APPLIED`; interpretation is `UNADJUSTED_DESCRIPTIVE_ONLY`.
FIXED protocols have no required development-trial minimum. C-105 does not apply
correction, rank/select holdout candidates, infer complete global research
history, or grant qualification, learning, or promotion authority. Closed codec
support is read/inspection compatibility only; lineage retention is denied. No
migration, DDL, or general registry lifecycle is introduced.
[ADR](../adr/ADR-0028-spot-multiple-testing-observation-boundary.md).

## ADR-0029 — C-106

C-106 schema 1 is an observation-only, deterministic assessment over the exact
supplied C-028v2 result, C-024v2 package, typed current snapshot, and explicit
timezone-aware `as_of`. Canonical identity binds the exact source digests,
current snapshot digest, comparison results, declared expiries, preserved
validation outcome, status, and reasons. Missing/uncomparable identities take
precedence over mismatches; mismatches take precedence over declared expiry.
Expiry is inclusive at the `as_of` boundary.

Only an explicitly typed `CODE_BUILD` reference in the original C-028/C-024
source closure can provide that identity; absence is inconclusive, and no
methodology or runtime substitution is allowed. C-106 preserves C-028 outcome
and gates; `CURRENT_FOR_GOVERNANCE_REVIEW` requires original PASS and C-106
CURRENT, but grants no qualification, production eligibility, approval,
activation, readiness, or execution authority. Performance decay is
`NOT_ASSESSED`; rolling metrics and `StrategyDecayState` remain out of scope.
Closed codec schema-1 support is for inspection only; lineage retention is
denied. No migration, DDL, persistence, API, scheduler, or global registry is
introduced. [ADR](../adr/ADR-0029-validation-freshness-assessment-boundary.md).

## Issue #103 — embedded risk policy/configuration values

The immutable `RiskLimitPolicyConfiguration` embeds a non-empty, duplicate-free
tuple of typed risk-limit definitions and exact `VersionReference` values for
both its policy and configuration. It is not a new canonical contract or
persisted/version-resolved registry. The content digest uses the existing
`canonical-json-v1` canonical JSON and SHA-256 machinery. Its preimage contains
the exact policy/configuration component and version identities and all typed
limit/scope content, but excludes both referenced `content_sha256` values and
the policy object's own `content_sha256`; the resulting digest must equal the
own digest and both reference digests.

The six ordered scope levels are `SYSTEM`, `ACCOUNT`, `PORTFOLIO`, `STRATEGY`,
`TRADE`, and `USER_REQUEST`, each bound to an explicit operating mode and
applicable identities. Overlapping same-level definitions conflict. An
applicable lower-level definition must preserve a `HARD` parent and may only
retain an equal or tighter comparable bound. No supplied tuple can prove that
external policy sources or omitted definitions are complete.

This addition defines no default policy or numeric thresholds, policy
store/resolver/API/DB/migration, consumers, account/portfolio math, or
approval/execution authority. Existing `PASS_WITH_WARNING` semantics remain;
this value-object change does not enforce downstream human review or
acknowledgment for soft breaches.

## Issue #104 (canonical 102) — offline account evidence values

`OFFLINE_ACCOUNT_EVIDENCE` adds immutable, nonpersisted risk-package evidence,
context, permission-observation and deterministic assessment values only.
There is no new C ID or schema version. C-032 `AccountSnapshot` schema `1`
retains its exact constructor, monetary/currency rules, fixed metadata and
legacy `content_sha256` semantics; C-033/`PortfolioSnapshot` consumers are
unchanged. No migration or codec/storage registration is introduced.

`OfflineAccountEvidence.content_sha256` uses the existing
`canonical-json-v1`/`canonical_sha256` serializer over every envelope field
except its own digest. The preimage includes the entire supplied snapshot,
including C-032's legacy digest and fixed contract/schema metadata, plus
observed account UUID/source string/source `VersionReference`/venue/mode and
all read/trade/withdraw/transfer observations, including missing and `UNKNOWN`
values. Construction/verification reject mismatched evidence digests, and
assessment verifies again. A recomputed binding is not authentication of the
legacy digest, external provenance, account truth, or completeness.

The separate assessment accepts an explicit expected context and a supplied
timezone-aware evaluation datetime, normalized to UTC without a clock.
Expected context and evaluation time are comparison inputs, not assertions
that external truth is current. Unknown/missing or mismatching context,
observed account/source/version conflicting with C-032, missing/unknown
permissions, non-`VALID` snapshots, future `as_of`/capture or evaluation
strictly after `valid_until` yield explicit noncurrent reasons; equality at
the boundary passes. Known `DENIED` is a complete observation. All permission
observations are descriptive only, and independent-source reconciliation
always remains `UNKNOWN`, even when currentness passes.

Chat 8 §§6,78 and ADR-0018 boundaries remain intact: no financial formulas,
zero filling, FX, derived authoritative funds, account mutation, store,
network/integration, downstream consumer wiring, risk decision, approval or
execution authority. External verification and consumer integration remain
deferred. Focused cases are added in `tests/backend/test_risk_contracts.py`.

## Issue #103 (canonical issue; GitHub #105) — offline exposure and correlation

The profile adds immutable nonpersisted values/calculations only. It does not
add a contract ID or schema, persistence/codec registration, database,
migration, API, scheduler, external lookup, or downstream authority. The
earlier Issue #103 embedded policy/configuration entry is a separate retained
implementation slice.

Exposure input is the explicit C-032 account plus caller-supplied C-075
positions and per-position venue identity. `VALID` status, same account,
positive equity and notional, unique position/snapshot identities, aware
evaluation time, nonfuture `as_of`/capture, and freshness are required.
`evaluated_at == valid_until` is valid. Invalid or unpriced evidence and
missing/malformed venue information fail closed. Repeated instrument exposure
is aggregated rather than omitted.

Each `(dimension, key, currency)` breakdown keeps gross long, gross short,
signed net (`long - short`), and gross (`long + short`). Currency, asset,
instrument, venue, and direction are separate dimensions. No unlike-currency
netting or cross-currency sum is emitted. Same-currency concentration is gross
currency notional divided by positive account equity; per-asset concentration
is each `(asset, currency)` gross notional divided by positive account equity.
Both use finite `Decimal` arithmetic at precision 34 with half-even rounding
and without a `[0, 1]` clamp. Foreign-currency concentration is explicitly
`UNKNOWN` because FX is out of scope.
This is not mark-to-market, loss/PnL, exposure-limit or risk-decision logic.
The aggregation carries account/snapshot identity, exact position snapshot
IDs, evaluation time, and a canonical digest binding the supplied account,
sorted position/venue inputs, and evaluation time; that digest does not
authenticate external truth.

Each caller-supplied return series binds its instrument, source identity,
`VersionReference`, finite Decimal log returns, strictly increasing aware
timestamps, and a canonical SHA-256 over exactly those series fields.
Correlation's exact inclusive
window, minimum count (caller-supplied, at least three), optional explicitly
named benchmark, and all input series are bound in output provenance. Each pair
requires identical timestamp sets inside that window. A mismatch yields
`UNKNOWN` / `TIMESTAMP_MISMATCH` for correlation and beta, with no value or used
samples; it never silently drops observations to form an intersection. Outside
the window, differing timestamps do not affect the estimates. Pearson uses sample
covariance divided by sample standard deviations; benchmark beta uses sample
covariance divided by the explicitly named benchmark's sample variance.
Decimal operations use precision 34 with half-even rounding; there is no
annualization or float arithmetic. Pearson results at most `1e-32` outside
`[-1, 1]` due to rounding are corrected to the nearest boundary; larger
violations fail closed. Output identifies every exact aligned sample
timestamp/count, source, version, series digest, and overall input digest.

Insufficient or unalignable samples, zero pair variance, and zero benchmark
variance produce explicit `UNKNOWN` results/reasons rather than zero. No
default window, minimum count, benchmark, interpolation, resampling, forward
fill, cleaning, or omission of malformed series exists. These descriptive
statistics do not claim confidence, independence, persistence, future
stability, authorization, a limit decision, or trading authority.
Return-series digests bind supplied content deterministically; they do not
authenticate its source, external provenance, or market data. Neither
exposure nor return digests authenticate account truth.

C-033 and C-075 schema 1 constructors, meanings and consumers remain unchanged.
Legacy C-033 correlation fields are not populated or reinterpreted. No real
market/account/exchange access, secrets, credentials, FX, strategy grouping,
pending orders, leverage/margin, threshold, approval, execution, or live
trading path is introduced. Focused synthetic tests live in
`tests/backend/test_risk_contracts.py`.

## Issue #104 (canonical issue; GitHub #106) — offline position sizing

C-036 remains schema 1 with unchanged fields, constructor and consumers.
The pure `calculate_position_size` function accepts immutable nonpersisted
`PositionSizingRequest`, `SizingInstrumentTerms` and `SizingCosts` values.
No new canonical contract ID, codec, persistence, API, migration or external
integration is added.

Inputs explicitly bind model, policy, configuration, effective-budget,
instrument and cost versions; volatility/Kelly versions are required for
those methods. A caller-attested common validity window covers all supplied
assumptions. Account/portfolio IDs, schema versions, digests and expiries must
match `RiskContext`; the portfolio must embed the exact supplied account with
matching equity. Snapshots (including embedded positions), context references
and assumptions must be current at the explicit evaluation time. An expiry
equal to evaluation is valid. Reference digests and expiries are mandatory.

The result content digest hashes the complete request and complete C-036
output fields excluding the output `content_sha256`. This binds every supplied
value, version, result ID, time, reason and computed amount. VersionReference
digests identify caller-supplied versions; neither those identifiers nor the
result hash authenticate external truth or policy-budget completeness.
Result validity is bounded by the earliest evidence/reference expiry. A
failure on expired inputs expires at evaluation and carries no recommendation.

The domain registry documents all five formulas and unit conventions.
Precision is 34, half-even, isolated from the caller's Decimal context;
unit and final stepped monetary calculations must be exact or fail closed.
Targets/step counts round down and Kelly's losing term rounds up. All methods
respect the effective risk, quantity, notional and free-margin caps; a reduced
notional, percentage, Kelly or volatility-derived target is explicit WARNING.
Unrepresentable/structurally malformed
inputs raise `RiskContractError`; invalid or insufficient evidence produces
FAILED/INSUFFICIENT_DATA with reasons and no recommendation.

Kelly is research/backtest only and uses explicit probability/payoff/fraction
versions. Volatility uses an explicitly supplied loss-per-unit, never an
estimated statistic. Only LINEAR instruments and same-currency amounts are
supported. The effective budget is already policy/open-risk adjusted by the
caller. No sizing result evaluates that policy, establishes overall risk
acceptability, or grants approval/execution authority. Leverage, liquidation,
portfolio decisions, synchronization, external lookup, credentials, live
trading and runtime wiring remain excluded. Focused synthetic regressions
are in `tests/backend/test_risk_contracts.py`.

## Issue #105 (canonical; GitHub #107) — offline stop-loss assessment

C-078 `StopLossAssessment` remains schema `1` with its exact constructor,
fields, meanings and consumers. `StopLossAssessmentRequest`,
`StopLossStructuralEvidence`, `StopLossVolatilityEvidence`, and
`StopLossLiquidationEvidence` are immutable nonpersisted inputs only; no new
canonical ID, codec, persistence, API, database, migration, or runtime wiring
is introduced. `calculate_stop_loss_assessment` reuses the existing linear
`SizingInstrumentTerms` and `SizingCosts` values and does not change C-036.

The request explicitly binds result ID, evaluation time, `RiskContext`, exact
matching C-032/C-033 snapshots and source versions, model/policy/configuration
versions, proposed quantity, effective maximum-loss budget, entry/stop,
instrument/cost/gap provenance, policy minimum distance, and a common
assumption validity window. Account/portfolio IDs, schema, digests, expiry,
state, equity and currency must match their references; embedded positions
must be current. C-021, C-028 and C-070 references accept schemas `1` and `2`;
C-023, C-032 and C-033 references require schema `1`. Unknown schemas fail
closed. Every reference requires a digest and expiry; the complete
version-qualified references are retained without payload down-conversion,
and C-078 output remains schema `1`.
Evidence/as-of times cannot be future-dated; an expiry equal to
evaluation passes. Stale, future, absent, or unknown evidence cannot produce
PASSED. The caller-attested budget is already reduced for applicable policy
and open-risk consumption; the calculator neither verifies policy
completeness nor authenticates external truth.

The supported instrument model is explicitly `LINEAR`. Quantity is contract
units, multiplier is base units per contract, entry/stop/gap are quote-price
units, and fee/slippage/funding are quote currency per contract. Entry and
stop must conform to tick size; quantity must be within supplied bounds and
an exact quantity-step multiple anchored at zero. Notional is
`entry * multiplier * quantity` and cannot exceed instrument maximum.
No FX, external lookup, nonlinear model, quantity adjustment, leverage
selection, or stop rounding is introduced.

LONG requires stop below entry; SHORT requires stop above entry. The
calculator reports absolute stop distance and distance/entry ratio; ratio
division is isolated at Decimal precision 34, half-even. C-078 `RatioValue`
cannot encode a ratio above one, so exact distance is checked against entry
before division. A ratio above one fails closed even when precision-34
rounding would yield one. Explicit policy and caller-supplied volatility minimum
distances use the request's explicit `price_unit_currency`; no volatility
estimate or hidden multiplier is derived. Structural acceptance requires a
current, versioned C-023 interval
with inclusive price bounds and exact C-021 strategy, context, asset,
instrument, and side lineage. This caller-attested materialized interval does
not claim to evaluate every strategy invalidation rule. A bare boolean or
unpriced qualitative evidence cannot pass.

For leveraged exposure, liquidation assessment consumes caller-supplied
current price and nonnegative minimum buffer in quote-price units. Liquidation
must be beyond the stop in the adverse direction, and the distance from stop
to liquidation must meet the buffer. No liquidation engine or C-077 result
is generated. Explicit no-liquidation applicability is accepted only with
caller-attested fully funded spot evidence; unknown applicability or missing
leveraged liquidation price is insufficient.

Maximum loss is:

`quantity * ((abs(entry - stop) + adverse_gap_displacement) * multiplier + fee_per_unit + slippage_per_unit + funding_per_unit)`

All monetary inputs use the same account/instrument quote currency. Gap
displacement is separate additional adverse price movement. Fee, slippage,
funding and gap values are explicit, version-bound, nonnegative costs (zero
must be explicit). Monetary arithmetic runs in an isolated precision-34
Decimal context with `Inexact` trapped; unrepresentable arithmetic raises
`RiskContractError`. The budget comparison is exact, with no tolerance,
rounding up quantity, loss clamp, or stop adjustment. This is an
assumption-bounded estimate, not a guaranteed maximum market loss.

Only complete current evidence and passing structural, volatility,
liquidation, distance, quantity, notional, and hard-loss-budget checks produce
PASSED. Deterministic constraint breaches produce FAILED; missing/stale/
unknown evidence produces INSUFFICIENT_DATA with reason codes. Missing or
directionally invalid stops leave stop and derived C-078 fields unset to
preserve the existing constructor invariant; callers retain the original
request alongside the result. The canonical digest binds the complete request
and all output fields except its own digest. `valid_until` is bounded by the
earliest applicable context/reference, account/portfolio/position, source,
assumption, structural, volatility, and liquidation expiry; incomplete
evidence is valid only at evaluation. Digests bind content, not provider truth.
The existing C-078 `cost_assumptions` field contains only the supplied
`SizingCosts` version; gap, instrument, policy, and other request versions are
bound by the complete request digest without changing C-078 field semantics.

The assessment validates only stop-specific evidence. It does not generate a
stop, size a position, estimate volatility, evaluate all strategy rules,
choose leverage, calculate liquidation, assess portfolio impact, perform
policy hierarchy resolution, approve risk, or authorize approval/execution.
A C-036 sizing pass does not imply stop validity; a C-078 pass does not imply
overall risk approval or execution authority.

## Issue #107 — offline leverage and margin assessment

C-076 `LeverageAssessment` remains schema 1 with unchanged constructor, fields,
meaning, consumers, and authority. The pure
`calculate_leverage_assessment(LeverageAssessmentRequest)` recomputes C-036
from the exact supplied `PositionSizingRequest`. The immutable request and
`LinearMarginRuleEvidence` are nonpersisted inputs, not new canonical
contracts. No API, codec, persistence, migration, external access, or runtime
wiring is added.

The request explicitly supplies result identity/time, requested leverage,
margin mode, policy/account/venue leverage caps, post-trade gross leverage
cap, minimum free-margin buffer, additional reserved quote-currency cost, and
one versioned caller-attested rule tier bound to venue, instrument, account
snapshot, and exact mode. Model/policy/configuration versions and the common
validity window are inherited from the sizing request. No cap defaults,
policy precedence resolver, leverage recommendation, clamping, or override
exists. An edit requires a fresh assessment.

Only LINEAR rules with matching CROSS or ISOLATED mode pass. Inclusive tier
bounds, initial rate, maintenance rate, rule version, and validity are
explicit. The implementation uses one supplied tier and does not discover or
select exchange tiers. It assumes incremental same-currency linear margin
only, with no cross/isolated behavioral equivalence claim, offsets, netting,
hedging benefits, collateral conversion, FX, or liquidation assumptions.

The recomputed sizing result must be current, bounded, and consistent with
exact quantity, entry, multiplier, initial margin per unit, currency, context,
account, portfolio, and instrument terms. Current account/portfolio snapshots
and complete positions are required. Position identities must be unique;
absolute position notionals are summed and must equal C-033 gross exposure.
An empty positions tuple is zero exposure only for an explicitly VALID
portfolio reporting zero gross exposure. Positive matching equity is required.
Account/rule evidence is caller-attested; this is not live account/rule
authentication, reconciliation, or balance reconstruction.

For `N` recommended notional and `M` recommended margin:

- required initial margin is `max(M, N / requested_leverage,
  N * initial_margin_rate)`;
- proposed margin `M` must cover that requirement;
- incremental maintenance margin is `N * maintenance_margin_rate`;
- effective leverage is `N / M`;
- post-trade gross leverage is `(existing absolute gross + N) / equity`.

All leverage limits use exact cross multiplication. `M` plus the explicit
incremental reserve must fit both available balance and free margin, and the
remaining free margin must meet the explicit buffer. Decimal arithmetic is
isolated at precision 34; exact sums/products and threshold comparisons fail
closed when unrepresentable, while division and reported ratios round upward.
Hard breaches are FAILED and dominate unknown evidence/warnings. Missing,
stale, future, or unknown required evidence is INSUFFICIENT_DATA. Upstream
sizing warnings propagate and retain their calculated margin/leverage evidence.
A known requested-leverage cap breach remains FAILED even when rule evidence
is missing; absent equity is INSUFFICIENT_DATA, not a proven numeric breach.
Failed/insufficient assessments omit numeric
recommendations; C-036/C-076 passes do not constitute overall risk acceptance,
approval, or execution authority.

The canonical digest binds the complete request, recomputed C-036 output, and
C-076 output fields except its own digest. Validity is bounded by the sizing
evidence, context/snapshot/position references, and supplied margin rule;
equality at expiry is valid. Hash binding does not authenticate data-source
truth, completeness, or exchange-rule authenticity.

## Issue #110 — offline supplied liquidation-estimate assessment

C-077 `LiquidationAssessment` remains schema 1 with unchanged constructor,
fields, meanings, consumers, and availability constraints. The pure
`calculate_liquidation_assessment(LiquidationAssessmentRequest)` recomputes the
exact supplied `LeverageAssessmentRequest` through
`calculate_leverage_assessment`. Its immutable estimate, threshold, cost, and
request dataclasses are nonpersisted inputs only. No liquidation-price formula
calculator, API, codec, persistence, migration, external adapter, or runtime
integration is added.

The only supported estimate is caller-attested LINEAR evidence binding the
exact leverage request, recomputed sizing quantity, context, entry/stop/side,
instrument and venue, account/portfolio snapshot identities, margin mode,
source identity, formula and exchange-constraint versions, and aware as-of and
expiry. The declared formula/source versions and content digest do not prove
authenticity or formula correctness. Missing/unknown/unsupported formula data,
incomplete CROSS evidence, mismatched/stale/future estimates, and unsupported
cost treatment are unavailable. Margin modes are never substituted and no
exchange liquidation price is calculated or inferred.

Minimum entry-distance ratio, absolute stop buffer, and normal/stress adverse
displacement are explicit current versioned quote-price assumptions. Fee and
funding reserves are nonnegative, versioned, currency-matched inputs. The sole
supported cost treatment attests that both reserves are already included in
the supplied estimate. An unknown treatment or any case requiring adjustment
of the supplied price is unavailable; the calculator neither subtracts
reserves nor infers zero. LONG/SHORT adverse-direction entry and stop
clearances are compared exactly in quote-price units; entry distances are
cross-multiplied against the ratio threshold. Equality passes, but liquidation
at or inside the stop is a hard failure. Reported C-077 ratios are entry
denominated, rounded down, and never clamped. Non-positive or unrepresentable
distances are `UNAVAILABLE` with no estimated numeric fields; an independently
known hard failure yields `FAILED` despite the `DISTANCE_NOT_REPRESENTABLE`
reason. Other unrepresentable distances yield `INSUFFICIENT_DATA`.

The evaluator requires current matching C-021/C-028/C-070 refs in supported
schema 1/2 and C-032/C-033 schema-1 snapshot references with exact content
digests and expiry. It propagates upstream WARNING and numeric evidence and
never upgrades upstream FAILED/INSUFFICIENT_DATA. Known hard failures dominate
missing evidence. `NOT_APPLICABLE` is not a pass and no fully-funded Spot
resolver exists. A representable current estimate with a distance or buffer
threshold breach remains `AVAILABLE/FAILED`; wrong-side, at/inside-stop, or
unrepresentable distances are `UNAVAILABLE`, with no estimated numeric
fields, and a known hard failure takes precedence over insufficiency. The
canonical digest binds the complete request, recomputed C-076
assessment, and C-077 output excluding its own digest; it is content binding,
not source authentication. Validity is bounded by all related context,
reference, snapshot, rule, estimate, and threshold expiries; equality is valid.
C-077 is a component observation, not overall risk acceptance, approval, or
execution authority.

The supplied estimate embeds the exact liquidation-cost evidence as its
`cost_basis`. Missing cost binding is unavailable; changed amounts, treatment,
version, currency or timestamps cannot reuse the old estimate. Invalid price,
venue, quantity or unit evidence cannot produce a passing relationship label.
The shared sizing precheck distinguishes absent snapshot digest/expiry from a
known conflicting value: missing provenance remains insufficient, while known
identity/schema/digest/expiry mismatches still fail. No canonical constructor
or schema changes accompany this dependency correction.

## Issue #108 — C-079 offline take-profit assessment

C-079 `TakeProfitAssessment` remains schema `1`; its constructor, fields,
semantics, and consumers are unchanged. The additive
`TakeProfitAssessmentRequest`, `TakeProfitTargetBound`, and
`calculate_take_profit_assessment` are immutable nonpersisted implementation
inputs/behavior only. No new canonical contract ID, codec, persistence,
migration, API, or runtime integration is introduced.

The request binds explicit result ID/evaluation time, exact C-078 request
inputs (recomputed through `calculate_stop_loss_assessment`), current typed
C-036 sizing evidence, targets, per-target current priced strategy bounds,
versioned per-target `SizingCosts`, and positive versioned minimum R:R. The
stop must pass; C-036 must be current, schema 1, same-context, and match the
stop quantity, distance, and instrument/cost assumptions. Its nominal loss
plus the exact adverse-gap adjustment must match recomputed C-078 maximum
loss. C-036/stop warnings propagate.
C-036 notional/margin amounts and currencies are validated against exact
quantity/entry/instrument terms, notional cap and available margin. Its
min/max/step bounds must match the instrument; nominal loss must fit its risk
budget. Warnings do not bypass these checks or permit missing bounded outputs.
Hard failures dominate missing evidence and warnings; missing, stale, future,
or unknown evidence cannot pass.

Input target expected profit must be unset (even zero is rejected). The target
sequence is immutable, unique, and ascending; allocations sum
exactly to one. LONG prices increase and SHORT prices decrease, all targets
conform to the instrument tick, and each allocated quantity satisfies
minimum/maximum/step bounds without rounding or adjustment. Each expected
profit is directional gross profit less that target's explicit adverse
fee/slippage/funding inputs. The minimum R:R test compares exact cross
products with recomputed C-078 maximum loss before division; the reported ratio
is descriptive and rounded downward at precision 34 so it never overstates R:R.
Priced bounds bind exact C-021/C-023 and `RiskContext` lineage and must be
current. C-021/C-028/C-070 schema 1/2 references use the registered explicit
compatibility dispatch; C-079 output stays schema 1.

Arithmetic is isolated to Decimal precision 34, half-even, with exact
operations trapped and unrepresentable arithmetic rejected as
`RiskContractError`. The canonical result digest covers the complete request
and complete C-079 output except its digest; result expiry is the earliest
applicable context, upstream, assumption, and target-bound expiry. Callers
retain the exact nonpersisted request alongside its C-079 result. This
observation grants no sizing, policy, portfolio, approval, execution, or
authorization authority.

## Issue #111 — offline portfolio impact and concentration limits

`calculate_portfolio_impact(PortfolioImpactRequest)` produces existing C-080
schema 1 without changing its fields, constructor, consumers or authority.
Immutable internal basis, policy, position/classification, correlation-scenario
and liquidity evidence values are nonpersisted inputs, not new C-### contracts.
Every evidence value binds the exact leverage/stop request basis, an explicit
version and an aware validity window. No service, API, codec, database,
migration, provider access or runtime integration is added.

The calculator recomputes C-036, C-076 and C-078 and checks their common account,
portfolio, context, entry, stop, quantity, instrument, costs and policy/configuration
basis. Proposed notional/margin come from sizing; proposed risk comes from the
passed or explicitly failed stop observation's calculated cost/gap-inclusive
loss. Any upstream failure/insufficiency cannot become a pass; warnings retain
numeric observations. If essential evidence is absent, the function raises a
specific RiskContractError rather than fabricating required C-080 buckets.

Existing positions require exact one-to-one snapshot coverage, current matching
account/source/unit data, explicit venue, version-qualified strategy and regime,
correlation scenario memberships and explicit nonnegative open-risk amounts.
Existing nonempty exposure aggregation reuses #105; genuine empty portfolios
have an explicit zero total bucket without a synthetic position. Recomputed
gross and signed net must agree with C-033. Before/after buckets retain gross
notional and risk by total, asset, strategy, regime, scenario, venue/instrument
and direction. Short exposure does not cancel gross risk. Strategy group keys
bind C-021 entity/schema/content identity, excluding reference expiry; regime
keys bind the full supplied VersionReference.

Correlation scenarios are caller-attested assumptions with instrument coverage,
methodology, version and validity, not evidence of empirical independence or
stable correlation. Overlapping scenario buckets count each position once per
group and once in total. Missing membership, scenario coverage or group cap
cannot grant a pass. Liquidity capacity is explicitly a versioned gross-exposure
capacity under supplied assumptions at the fully bound snapshot/entry basis;
it is not raw order-book depth, measured execution quality or an execution guarantee.

The explicit effective policy applies HARD before/after gross, absolute-net,
gross-leverage, margin-utilization, free-margin, current-drawdown, total-risk
and asset/strategy/regime/scenario concentration checks. Group notional is
compared with equity times its cap before division; no default cap, netting
benefit or policy hierarchy resolver is supplied. Position open-risk sums plus
C-033 pending risk plus C-078 proposal loss consume the total budget. A breached
budget leaves remaining_risk_budget unset, never zero-clamped. Nonzero pending
risk remains in total observations but its unknown notional/group attribution
prevents PASSED; the positive profile requires explicit zero pending risk.

Margin utilization uses C-032 used margin, adding C-036 proposed margin after.
Remaining free margin subtracts proposed margin and the exact C-076 incremental
reserve once. Current marks/equity are static: before/after drawdown retains
C-033 current drawdown without claiming simulated fills, future PnL or stress
projection. Stress modeling remains #112. Recomputed upstream values and all
supplied evidence/output bind the canonical result digest; the digest proves
content binding, not source authenticity, complete accounts, classifications,
liquidity or guaranteed losses.

Arithmetic uses isolated Decimal precision 34. Monetary sums/products and
threshold cross-products must be exact or raise RiskContractError. Descriptive
#105 aggregation retains its own rounding context; the policy calculator never
uses rounded concentrations for acceptance. Reported notional/risk/margin ratios
round upward and free-buffer ratios downward. C-080 RatioValue remains [0,1]:
unrepresentable genuine values or missing mandatory exposure information raise
explicit errors, without schema changes, placeholders, omission or clamping.
Known HARD breaches dominate missing evidence and warnings; otherwise missing
policy/cap/scenario/liquidity evidence yields INSUFFICIENT_DATA. All relevant
expiry boundaries constrain the result; equality at expiry is current.

No optimizer, empirical correlation/beta estimator, FX/collateral conversion,
close/reduce/netting model, source authentication, order/approval/risk-proposal
workflow or execution authority is introduced. C-080 is a bounded offline
component assessment, not overall trading readiness or live portfolio integration.

## Issue #112 — offline supplied stress and finite-path ruin assessment

`calculate_stress_assessment(StressAssessmentRequest)` recomputes the exact
#111 portfolio request and produces unchanged C-081 schema 1. Its immutable
policy, projection and net-PnL path inputs are nonpersisted helper types, not
new canonical contracts. All inputs bind the complete portfolio basis, source,
scenario/cost versions and aware validity windows. Known upstream failures,
insufficiency and warnings cannot become an overall pass.

Required scenario types are explicit: RISK_OF_RUIN plus at least one of
VOLATILITY, GAP, LIQUIDITY, FUNDING or CORRELATION. Supplied materialized
projections must cover every existing/proposed instrument with numeric shocks
and units, explicit included-cost assumptions, loss, margin and minimum
liquidation distance. This assessor does not derive valuations from shocks or
authenticate caller-supplied assumptions. Missing/currentness/lineage evidence
prevents a pass; missing required types appear as unavailable scenarios with
unset numeric values. Zero liquidation distance is always a hard breach.
For these non-ruin adverse projections, included cost reserve cannot exceed total
projected loss; favorable PnL cannot offset the declared included reserve. Signed
net-PnL ruin paths retain their separately declared semantics.

For current equity E, current drawdown d and projected loss L, fixed-high-water
mark drawdown is d + (1-d)*L/E. Exact cross-products check loss, drawdown,
margin utilization against E-L and liquidation-distance limits before display
rounding. Exhausted equity fails; unrepresentable drawdown stays unset rather
than being clamped. Worst loss, drawdown and margin are independently available
only when every required scenario supplies that metric.

`calculate_ruin_observation` reports typed finite-sample path/hit counts and a
conditional observed frequency, not calibrated probability or trading
confidence. Immutable equal-horizon paths contain signed net quote-PnL
increments, including caller-declared costs. Any prefix reaching the explicit
capital floor counts as a hit even if capital later recovers. Empty,
undersized, expired or invalid evidence never supplies a zero-risk frequency.
Hit thresholds use exact counts; reported frequency rounds upward. Maximum
path loss is measured against initial equity, not a dynamically rising peak.
The C-081 digest binds the typed observation; human-readable diagnostics are
not an authoritative probability field. C-081 gains no probability field.

Ruin paths retain static planned margin and explicitly report path liquidation
as NOT_MODELED_FOR_PNL_PATHS. Separately required stress projections supply
liquidation-distance evidence. C-072 schema 2 remains observation-only under
ADR-0024 and is not accepted or wired into Risk. No Monte Carlo generator,
market-price simulator, source authenticity guarantee, exchange liquidation
formula, policy resolver, API, execution or approval authority is introduced.

Arithmetic uses isolated Decimal precision 34 with exact sums/products or an
explicit RiskContractError; reported drawdown/frequency round conservatively.
Bounds are 128 supplied projections, 10,000 paths and 1,000,000 increments.
Canonical digests bind full input/output content without authenticating sources.
Missing cost/shock metadata permits rejection from known breaches only; numeric
outputs remain unavailable. Foreign money is rejected even with other incomplete
evidence. All upstream and supplied evidence expiries constrain results. Focused tests
cover these component semantics; this does not claim live integrated readiness.

## Issue #113 — offline risk proposals and immutable replay snapshots

`risk.proposals.build_risk_proposal(RiskProposalRequest)` reuses the existing
C-036/C-076/C-077/C-078/C-079/C-080/C-081 calculators and emits unchanged C-034,
C-035 and C-082 schema 1 objects. It accepts no supplied aggregate PASS or
assessment/decision. Exact request bases, evaluation time and recomputed sizing
must agree. Caller-supplied references bind signal, validation, strategy,
account/portfolio, C-024 v1/v2 evidence and C-002 market identity/content/expiry;
they are not authenticated source resolution or a qualification decision.

The nonpersisted frozen RiskProposalSnapshot bundles source inputs and proposal.
Its account/portfolio views reuse existing C-032/C-033 values; its trade view
retains the exact immutable requests, parameters, policy/configuration/model
versions, assumptions and evidence. Canonical digests bind these inputs and the
nested assessment/decision/output. Replay is deterministic; hashes bind content,
not source authenticity or profitability. Initial revision is 1; explicit rebuilds
supersede a supplied prior proposal at revision + 1 with new proposal, assessment
and decision identities. No historical object is mutated; persistent identity
uniqueness and source retrieval are outside this offline component.

Hard vetoes dominate insufficiency, then warnings; required references cannot
silently expire or lack provenance while passing. Checks retain prefixed unique
limit identities and reasons. Proposal lifetime is bounded by all component and
reference expiries and requested TTL. Missing mandatory canonical amounts retain
explicit contract-error behavior; no placeholders or schema reinterpretation.
In particular, C-034 requires its maximum_loss to match C-036, so a differing
C-078 gap/cost-inclusive loss is explicitly rejected rather than understated.
Supply a coherent conservative common loss basis before constructing a proposal.

This is research-only assembly. Risk-state labels are explicit versioned policy
metadata, not inferred probabilities. Mandatory constraints and a trade-parameter
edit whitelist preserve approved=False, executable=False and
execution_authorized=False. No persistence/codec/API/UI, provider access,
qualification/robustness integration, policy resolver, human approval or execution
is added. #114 owns material-change triggers, invalidation and revalidation.
Only proposal-focused tests and changed-file checks are run locally; required
Product/Governance CI remains unchanged.


## Canonical issue 112 / GitHub #114 — offline risk revalidation

`risk.revalidation.revalidate_risk_proposal(RiskRevalidationRequest)` detects
material changes to an immutable #113 snapshot and rebuilds all risk components
through `build_risk_proposal` exactly once. C-083 `RiskRevalidationResult` stays at
schema 1 with its existing constructor and trigger vocabulary. Account and trade
identity must remain the same; the replacement must explicitly link the original
proposal and supply distinct proposal/assessment/decision identities. Backdated
evaluation is rejected. Material source changes and expired original proposals
require a new revision; unchanged inputs raise `RISK_REVALIDATION_NOT_REQUIRED`
before any rebuild. Expiry equality remains current.

Detection retains economic values, source identities/hashes/versions, evidence
windows, policy/configuration/assumptions and trade parameters. Calculation IDs,
previous linkage and evaluation clocks are omitted from material comparison.
Derived C-036 and ruin-request binding hashes are normalized so clock-only
refreshes do not manufacture material changes; ruin binding hashes are verified
before normalization and the full path payload remains compared. Unclassified
material configuration/evidence edits conservatively trigger POLICY and are
reported as calculation_assumptions. Full original inputs and replacement outputs
remain bound by the result digest; normalization does not alter replay evidence.

`RiskRevalidationSnapshot` is an immutable, nonpersisted source/result/replacement
bundle. It explicitly invalidates prior risk progression without mutating the
historical snapshot. REJECT maps to FAILED, PASS/PASS_WITH_WARNING to PASSED
(with warnings retained), and other verdicts to INSUFFICIENT_DATA. Validity comes
from the rebuilt proposal; missing mandatory evidence and incompatible common
loss bases retain #113's explicit contract errors. Risk acceptance supplies no
human approval or execution authority: approved, executable and execution_authorized
remain false. No persistence, API, provider access or new dependency is added.

This slice handles supplied research risk inputs, not live readiness or approval
state. Existing human approvals are never transferred to a replacement revision.
Approval-context integration belongs to GitHub #115–#119 and readiness/safety to
#129–#130; C-083 schema 1 is not reinterpreted to claim those capabilities. Local
validation is limited to revalidation-focused tests and changed-file checks;
required Product/Governance CI remains unchanged.


## GitHub #86 / canonical 084 — ADR-0030 study-policy foundation

`validation.qualification_study_v3` adds frozen dataset pins, study-policy values
and `QualificationStudyProtocolV3`, an internal supporting value for the future
C-028v3 bridge. This does not register or issue a C-028v3 result. C-028v2,
C-025v2, C-070v2 and all observation contracts remain unchanged.

The protocol binds exact strategy schema/semantic version/content, parameters,
configuration, method/build, costs, native string dataset IDs/versions and
manifest digests, Spot scope, evaluation window, declared freeze/access/expiry
boundaries and every statistical-policy field. Pure structural checks reject
ambiguous/nonfinite units, malformed references, invalid windows, duplicate or
unordered dataset pins and noncanonical content identity. Dataset pins are
bounded to 16; this is a metadata resource bound, not a statistical sample limit.
Canonical SHA-256 and deterministic UUIDv5 bind all values; changed policy or
source pins require a new identity. No numerical policy defaults are supplied.

Quote-currency expectancy per resolved trade and normalized-R expectancy are
separate units. Drawdown is an equity-peak fraction; rates are fractions rather
than percentages. Effective-sample/dependence/uncertainty, risk, robustness,
selection and return-basis methods are explicit versioned references. Naming a
method does not implement or validate it. The issuer must later resolve the
actual data/manifests, strategy/configuration, cost objects and method outputs.

Declared freeze/access timestamps are caller claims, not trusted journal
receipts or proof of precommitment. Structural validity, content hashes and a
reference confer no source authenticity, gate PASS, qualification or trading
authority. Qualification/execution flags stay false. Existing lineage encoding
and qualification allowlists reject this internal protocol as authoritative
input. No codec, persistence/retention, API, provider, dependency or migration
change is included. Verified result issuance, compatible result/consumer types,
trusted freeze/access verification and production wiring remain under #86.

Validation is limited to study-focused tests and changed-file quality checks.
This foundation does not close #86/#299 or pass the Spot operational gate.


## GitHub #86 / canonical 084 — C-028v3 result and closed codec

ADR-0030 adds `QualificationValidationResultV3` in
`validation/qualification_result_v3.py` and a standalone closed codec in
`validation/qualification_result_codec_v3.py`. This is the structural result
boundary, not a verified statistical issuer or production qualification path.

The frozen result embeds the exact C-023 candidate, C-024v2 package and
content-addressed study protocol. Strategy schema and semantic versions remain
separate; candidate/package scope, IDs and digests must agree with the protocol.
Declared freeze/journal references and holdout-access, as-of, creation and expiry
times are explicit. Result validity is bounded by the protocol, candidate,
package and all gate windows. Canonical SHA-256 and UUIDv5 bind the content.

Each mandatory gate appears once in canonical order with explicit typed source
and method pins, criterion, reasons, outcome and validity. Research-selection
is mandatory; calibration is included only when the frozen policy requires it.
FAIL dominates INSUFFICIENT_VALIDATION. Structural PASS requires every declared
mandatory gate PASS and coherent nonmissing policy metrics. Known rate,
expectancy and drawdown breaches must retain FAIL. Raw sample is an integer;
effective sample cannot exceed it. Rates/drawdown are Decimal fractions;
expectancy has an explicit quote-per-resolved-trade or normalized-R unit bound
to policy. Uncertainty binds interval, confidence, effective sample, dependence
and method/source identities. Historical risk uses historical evidence; no
current-trade C-070/C-035 dependency is introduced.

The codec uses canonical-json-v1 / wire-1 with C-028 schema 3 and rejects
unknown fields/versions, altered fixed metadata/content, noncanonical scalars
and legacy coercion. Existing C-028v1/v2, observation contracts, central lineage
allowlists, retention and qualification consumers are unchanged. Legacy
qualification rejects the new result as unsupported, yielding no qualification.

Source references and declared outcomes are not authenticated evidence. Even a
coherent synthetic PASS grants no qualification, approval or execution authority;
all three flags are false. Real source resolution/replay, trusted freeze/access
receipts, statistical issuance, compatible C-025/C-070 consumers, persistence
and API wiring remain required under #86. No provider, dependency, migration or
execution change is included. Focused result/codec tests cover the new boundary;
#86 and #299 remain open and the Spot operational milestone is not complete.


## GitHub #86 / canonical 084 — C-025v3 / C-070v3 structural consumers

Accepted ADR-0030 adds `SignalQualificationV3`, `SignalLineageV3` and `SignalV3`
in `strategy/qualification_consumers_v3.py`, with a standalone closed codec in
`strategy/qualification_consumer_codec_v3.py`. These are the remaining
first-stage consumer formats, not verified issuance or production wiring.

C-025v3 embeds the exact C-028v3 and derives its candidate, C-024v2 package and
C-021 semantic-version/content references. It maps PASS to QUALIFIED, FAIL to
REJECTED and INSUFFICIENT_VALIDATION to INSUFFICIENT_EVIDENCE; it invents no
WATCH or HIGH_EVIDENCE promotion. Reasons remain in the full validation result.
Evaluation and expiry are explicit UTC times bounded by the exact upstream
candidate/package/protocol/result validity. Canonical SHA-256 and deterministic
UUIDv5 bind every field; status and references cannot be caller overrides.

C-070v3 requires that declared qualification PASS, exact StrategyVersionV2 and
package-bound MarketContextV5. Its scope, direction, evidence/quality IDs,
lineage, regime, conflict and uncertainty IDs are derived from those objects.
The actual strategy schema 2, semantic version/digest and supported scope must
match. Expiry cannot outlive qualification, validation, candidate, package,
context or regime; source/assessment times cannot be future-dated.

The preserved `parameter_set` surface is the C-021 semantic-version reference,
as in C-070v2. For schema 3, `configuration` references the full frozen study
protocol, including its rule policy and separate backtest parameter/configuration
pins. No historical artifact or reference is relabelled. `regime_id` is proved
from the exact context's typed C-005, never supplied as an unrelated UUID. The
protocol's declared regime string remains a separate method-policy input; this
slice does not invent an authoritative C-005 label/mapping.

`market_context_document` stores the existing canonical C-006v5 lineage-codec
envelope, retaining assessment discriminators needed by its closed reader. The
typed `market_context` property decodes that exact document. This reuses C-006's
approved codec rather than weakening its discriminator rules or introducing
dynamic deserialization. Source identity still matches the package's existing
canonical context digest. The outer codec is canonical-json-v1 / wire-1 with
explicit C-025 or C-070 schema 3, closed fields and bounded document size.

These are immutable structural values. Synthetic QUALIFIED/PASS fixtures confer
no qualification, approval or execution authority; all three flags remain false.
Verified source/journal replay, gate/statistical issuance and research-selection
completeness remain required before real qualification. Existing strategy,
lineage/retention, lifecycle, NO_TRADE, freshness, API and risk readers retain
their schemas and reject these unsupported versions. No provider, dependency,
migration, persistence or execution change is included. #86/#299 remain open
for the issuer, approved retention, runtime integration and operational evidence.
Local validation is limited to consumer-focused tests and changed-file checks.
