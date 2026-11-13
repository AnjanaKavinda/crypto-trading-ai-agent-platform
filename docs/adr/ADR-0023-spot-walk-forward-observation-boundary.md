# ADR-0023 — Spot walk-forward observation boundary

## Metadata

| Field | Value |
|---|---|
| Status | Accepted |
| Date | 2026-11-13 |
| Decision owner | Platform Architect |
| Human approver | AnjanaKavinda; owner-assigned Trading Intelligence Engineer dispatch for #96 |
| GitHub issue / PR | #96 / #481 |
| Open decision ID | — |
| Related ADRs | ADR-0018, ADR-0019, ADR-0022 |
| Supersedes / superseded by | — |

## Context

Issue #96 completes the bounded `PERSONAL_SPOT_RESEARCH` path for deterministic
walk-forward observations over the accepted archive-bound Spot backtest and OOS
engines. The owner Execution Packet pins `dev` at
`e3775fea0eeee7d898933ca6e035bf7b27d76008`, freezes this scope, and assigns the
Trading Intelligence Engineer. Its matching generated `DISPATCH_READY` and
trusted `ASSIGNMENT_COMPLETED` records bind dispatch key
`30705c303cc7c7bc0f693b6375cf795a1e623961c66d42f8e3aaa8f3ab7d9550`.

The existing C-029v1 schema cannot truthfully represent incomplete, unavailable,
failed, or fully evidenced per-fold replay/report/journal observations. The
walk-forward result must therefore be an additive observation contract without
changing v1 or granting qualification, retention, profitability, risk, approval,
or execution authority.

## Alternatives

### Option A — Extend C-029v1

Benefits:

- Avoid a second schema.

Costs, risks, and constraints:

- Changes frozen identities and consumers.
- Cannot safely encode explicit unavailable and terminal fold observations
  without semantic incompatibility.

### Option B — Add observation-only C-029 schema 2

Benefits:

- Preserves C-029v1 payloads, identities, and readers.
- Binds per-fold OOS evidence, exact replay/report provenance, and explicit
  unavailable or failed states.
- Keeps observation separate from qualification and trading authority.

Costs, risks, and constraints:

- V1-only qualification and retention readers must reject schema 2.
- Construction, decoding, and live resolution require semantic closure.

## Decision

Adopt Option B for the bounded Spot research profile. Add C-029 schema 2 as an
immutable, observation-only result. Keep C-029v1 and its consumers unchanged.
Use canonical SHA-256 and UUIDv5 identities that exclude the generated result ID
and its own digest.

Freeze the complete rolling or anchored fold plan, finite candidates, selection
policy, sample/metric/aggregation policies, point-in-time rules, and bounded
resource budget before accessing any scored held-out partition. Execute each
fold through the existing Spot OOS and replay/report producers. A fold's
selection-validation partition is development evidence and is not the scored
held-out partition. Preserve one shared research-history journal across folds.
Every planned fold must receive a terminal observation, including failures,
missing archives, and cancellation.

Aggregate only comparable available metrics under a versioned deterministic
Decimal method. Preserve unavailable reasons, coverage, and fold identities.
The overall outcome is `FAILED` on integrity or contamination failure,
`INCONCLUSIVE` on incomplete coverage or unmet frozen sample minima, and
`OBSERVED` only for complete valid observations. No pooled win-rate or Sharpe,
compounded return, probability, statistical interval, qualification result, or
profitability claim is produced.

## Reasoning

The decision follows Master Playbook v2.2 Chat 7 and ADR-0019's deterministic
archive-bound replay authority. ADR-0022 supplies the accepted OOS protocol,
candidate selection, journal reservations, terminal receipts, and C-071v2
closure. The additive schema provides truthful observation states without
rewriting an accepted contract or changing its qualification consumers.

## Consequences

- C-029v1 is unchanged; C-029v2 is registered only for closed canonical
  encoding/decoding and in-memory observation.
- Existing candidate selection is limited to fixed or finite declared
  validation-net-profit selection. No optimizer or parameter search is added.
- No migration, DDL, durable C-029 retention, API, scheduler, provider, or
  exchange integration is authorized.
- Futures semantics remain separate and deferred to the approved Futures path.
- Resampling, sensitivity, regime validation, broader bias controls, and
  multiple-testing gates remain owned by their downstream issues.
- This ADR records bounded profile completion only; it does not claim
  full-platform completion or profitability.

## Contract and traceability impact

| Area | References and impact |
|---|---|
| Playbook requirements | Master Playbook v2.2 constitution; Chat 7 §§2–5, 17–29, 36–42, 54–59 |
| Cross-cutting artifacts | C-029 row in domain registry; C-029 schema/version registration; walk-forward provenance graph |
| Contracts / events | Additive C-029v2 observations; C-029v1 unchanged; consume existing C-071v2 and C-027v3/#94 evidence |
| Requirements traceability | Issue #96 acceptance checklist; architecture usage and limitations guide |
| Versioning / migration | Closed schema dispatch; unknown versions rejected; no migration, DDL, or durable retention |

## Safety, security, and failure behavior

This decision is offline, local, and read-only with respect to exchange activity.
It adds no credentials, orders, approval, risk, or execution path. Unknown
versions, altered pins, duplicate receipts, out-of-budget plans, and evidence
contradictions fail closed. Missing or insufficient evidence remains explicitly
inconclusive. C-029v2 is not accepted by qualification or learning consumers and
does not authorize storage.

## Approval record

The owner assigned the issue to the native Trading Intelligence Engineer after
the current Execution Packet and matching trusted `DISPATCH_READY` /
`ASSIGNMENT_COMPLETED` records were generated. This explicit assignment is the
bounded implementation approval for #96 only. Human owner review and manual PR
merge remain mandatory.
