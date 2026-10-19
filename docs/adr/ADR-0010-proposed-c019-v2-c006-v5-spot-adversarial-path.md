# ADR-0010: Proposed versioned C-019/C-006 Spot adversarial path

## Metadata

| Field | Value |
|---|---|
| Status | Accepted |
| Date | 2026-10-19 |
| Decision owner | Platform Architect |
| Human approver | AnjanaKavinda (explicit owner approval, 2026-10-19) |
| GitHub issue / PR | [Issue #379](https://github.com/AnjanaKavinda/crypto-trading-ai-agent-platform/issues/379) |
| Open decision ID | OD-0025 |
| Related ADRs | ADR-0008 |
| Supersedes / superseded by | — |

## Context

Issue #379 blocks the bounded Spot adversarial producer in issue #68 because
C-007 v4 does not allow C-019 outputs, while C-006 v4 embeds the existing
C-019 schema-1 assessment without binding its evidence and scope to the exact
C-007 manifest. C-019 schema 1 lacks the required Spot scope and provenance
closure.

This record follows the explicit option, compatibility, and owner-decision
structure used for issue #373. That precedent does not transfer approval to
this decision; the human repository owner explicitly selected Option A on
2026-10-19, as recorded below.

The current C-007 v4 output whitelist and C-006 v4/C-019 v1 semantics are
already merged compatibility boundaries. This decision does not reinterpret their payloads or hashes. Contract
implementation remains a separate, bounded follow-up and may begin only after
this accepted ADR is merged.

## Alternatives

### Option A — Add C-019 schema 2 and C-006 schema 5

Benefits:

- Adds the missing scope, evidence, freshness, and method provenance without
  changing C-007 v4 or existing C-006/C-019 payloads.
- Keeps the addition bounded to the C-019 assessment embedded in a new C-006
  version.

Costs, risks, and constraints:

- Requires explicit schema dispatch and consumer compatibility tests.
- C-019 v2 must close over the exact existing C-007 v4 evidence references;
  it cannot be added to the C-007 v4 output closure.

### Option B — Add a C-007 v5 path

Benefits:

- Could make a versioned C-019 output a member of a new manifest closure.

Costs, risks, and constraints:

- Requires a broader version transition and compatibility analysis for
  C-007, C-006, and any dependent C-009/C-010/C-093 references.
- Is unnecessary if C-019 remains an embedded C-006 component.

## Decision

**Accepted: Option A.** The human repository owner explicitly approved this
version path on 2026-10-19. This ADR records the architecture decision; it does
not itself implement contracts or authorize a producer. A separate implementation
issue is required after this ADR merges, and #68 remains blocked until that
contract implementation is merged.

The approved additive versions are:

| Contract | Proposed schema / lineage | Owner / registry |
|---|---:|---|
| C-019 `AdversarialAssessment` | `2 / 2` | Critic owns the semantic assessment; Analysis owns its contract model and codec dispatch. |
| C-006 `MarketContext` | `5 / 5` | Analysis owns the semantic context, contract model, and codec dispatch. |

The Domain Contract Registry remains the canonical semantic registry: C-019
remains owned by Critic, C-006 by Analysis, and neither contract receives a new
ID. The Version Registry is the canonical schema/lineage mapping. During
implementation, the analysis codec's exact `(contract_id, schema_version)`
dispatch and corresponding versioned contract models must be updated together;
these are implementation points, not additional canonical registries. C-007
v4, C-008 v2, C-003 v2, C-005 v1, C-009/C-010 v3, and C-093 v1 retain their
existing owners and registrations; issue #67 remains the owner of C-093
implementation and calculation.

## Reasoning

Option A is the smallest additive path for the bounded consumer. C-019 v2
remains embedded in C-006 v5 and is not a C-007 v4 output. C-019 v2 binds to
the exact C-007 v4 manifest identity and final content digest. The manifest
already closes over the exact C-008 evidence outputs and C-003 quality binding;
the assessment must cite the exact C-003 v2 report identity/digest and only
those exact usable C-008 v2 evidence records, their content digests, and their
source/observation lineage. It also binds the Spot instrument, timeframe,
coverage window, snapshot/cutoff, `as_of`, expiry, and exact method, model, and
prompt version references. Missing or unresolvable required provenance makes
the result unusable; it must not be fabricated or inferred.

There is no digest cycle: the C-007 v4 manifest does not contain a C-019 output
reference. C-019 v2 references the already finalized C-007 v4 manifest and
evidence digests, and C-006 v5 embeds C-019 v2 while independently referencing
that same exact C-007 v4 manifest. Neither C-007 nor C-019 references C-006.
The exact C-008 evidence set in C-019 must be a subset of the usable evidence
set validated against that manifest; contradictory evidence IDs must be members
of that same set.

Analytical confidence is interpretive only; it is never a probability,
calibrated likelihood, historical win rate, evidence score, or qualification.
C-019 v2 must represent confidence as a required discriminated state: `AVAILABLE`
requires a defensible numeric interpretive value and an exact method/version
reference; `UNAVAILABLE` requires an explicit reason and carries no value.
Consumers must handle both states explicitly. Do not substitute zero, a default,
or a fabricated number, and never treat unknown confidence as neutral or as
evidence of safety.

## Consequences

- Existing C-006 schema 1–4 and C-019 schema 1 payloads, identities, canonical
  bytes, hashes, and readers remain unchanged. No implicit conversion or
  historical rewrite is permitted.
- C-006 schema 5 explicitly embeds C-019 schema 2 and binds the exact C-007 v4
  reference. Unknown or incompatible versions reject/fail closed.
- C-007 schemas 1–4 remain unchanged. In particular, C-007 v4's closed output
  whitelist is not expanded.
- C-009/C-010 schemas 1–3 and C-093 schema 1 remain unchanged. C-006 v5
  preserves the existing C-009/C-010 v3 forms and C-093 reference behavior.
- No `canonical-json-v1`, `wire-1`, or global schema version changes are
  proposed. New schema and lineage versions are selected explicitly.
- After approval, a separate implementation issue must specify schema models,
  codec/registry dispatch, manifest/evidence validation, and compatibility,
  digest, stale/expiry, mismatch, unsupported-version, and fail-closed tests.
  Issue #68 remains blocked until that implementation is merged and its exact
  versions are confirmed.

## Contract and traceability impact

| Area | References and impact |
|---|---|
| Playbook requirements | Master Playbook v2.2, Chat 3 adversarial-agent permissions and Chat 5 analysis-only/evidence requirements; no Playbook text changes. |
| Cross-cutting artifacts | Domain Contract Registry retains C-019/C-006 semantics and owners; Version Registry records the proposed version mapping only after approval; the analysis codec's `(contract_id, schema_version)` dispatch is the implementation registration point; Evidence Graph and Handoff Matrix require reconstructable evidence and fail-closed unresolved conflicts. |
| Contracts / events | C-019 schema 2 and C-006 schema 5 proposed; no event contract or new C-ID. No changes to C-007 v4, C-008 v2, C-003 v2, C-005 v1, C-009/C-010 v3, or C-093 v1. |
| Requirements traceability | [Issue #379](https://github.com/AnjanaKavinda/crypto-trading-ai-agent-platform/issues/379) and [issue #68](https://github.com/AnjanaKavinda/crypto-trading-ai-agent-platform/issues/68). Update #68 with the accepted and merged versions, and keep it blocked until contract implementation merges; prepare a separate implementation issue after approval. |
| Versioning / migration | Additive schema/lineage `2/2` and `5/5`; retain `canonical-json-v1` / `wire-1`; no backfill, rewrite, or migration of historical records. |

## Compatibility matrix

| Existing contract versions | Compatibility rule under the proposal |
|---|---|
| C-006 schemas 1–4 | Preserve payloads, identity, hashes, and readers; no conversion. C-006 v5 is a separate explicit dispatch case. |
| C-007 schemas 1–4 | Preserve all versions. C-007 v4's output closure and validation remain unchanged; C-019 is not added to it. |
| C-009/C-010 schemas 1–3 | Preserve all versions. C-006 v5 keeps the existing C-009/C-010 v3 forms without changing their interpretation. |
| C-019 schema 1 | Preserve payloads, identity, hashes, and readers; never reinterpret as schema 2. |
| C-093 schema 1 | Preserve the existing C-007 v4 reference and owner-resolved method/version validation; no C-093 change or ownership transfer. |

## Safety, security, and failure behavior

This is analysis-only contract versioning. It adds no strategy eligibility,
signal qualification, statistical validation, risk, approval, order, or
execution authority. The adversarial assessment can challenge a thesis and
record contradictory evidence, but cannot approve or execute.

Unknown versions, unsupported/mismatched manifest or evidence references,
stale/expired inputs, missing required provenance, or an unresolved critical
conflict fail closed and cannot advance beyond analysis. Preserve evidence
independence limits: shared Spot OHLCV inputs do not become independent
confirmations merely because they produce multiple findings. `NO_TRADE` remains
preferred whenever evidence or safety is insufficient.

## Approval record

Approved by `AnjanaKavinda`, human repository owner, on 2026-10-19: Option A
(C-019 schema/lineage 2/2 embedded in C-006 schema/lineage 5/5), with the
required typed confidence state defined above. The ADR becomes effective as
implementation authority when merged. This approval does not approve a producer,
consumer migration, persistence, or any trading behavior.
