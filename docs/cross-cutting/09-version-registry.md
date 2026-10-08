# Version Registry

This registry defines the immutable baseline for governed artifact versioning.
It preserves exact historical resolution for trades, decisions, validations,
experiments, and rollback actions without redefining canonical contract
schemas.

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

This release provides codec and lineage read compatibility only. V2 writes,
producers, and analysis-consumer migration remain disabled/deferred. Before a
producer is added, it must resolve an exact recognized assessment-policy ID
and version and verify any `NOT_APPLICABLE` permission. Revalidate every
receiving reader, add consumer dimension-required checks, and independently
review/approve enabling v2 writes before rollout.

## Issue #341 — C-006/C-007/C-008 schema 2 and C-104

The repository owner approved the additive Option 2 direction in merged PR
#340 for issue #338. C-006/C-007/C-008 schema `1` payloads, identities, and
readers remain unchanged. Schema `2` is selected explicitly under the same
contract IDs and `wire-1`; no implicit v1-to-v2 conversion is permitted.
C-104 `OrderFlowAssessment` is the sequential additive schema-1 contract
recorded in the domain registry. C-003 v2 remains in-memory only; this change
does not enable its lineage writes or persistence.

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
