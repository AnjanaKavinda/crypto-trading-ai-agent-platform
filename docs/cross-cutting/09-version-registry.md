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
