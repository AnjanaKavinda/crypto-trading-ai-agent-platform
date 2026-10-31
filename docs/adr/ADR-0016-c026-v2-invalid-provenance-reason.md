# ADR-0016: Version C-026 invalid-provenance reason

## Metadata

| Field | Value |
|---|---|
| Status | Accepted |
| Date | 2026-10-31 |
| Decision owner | Platform Architect |
| Human approver | AnjanaKavinda (owner instruction for bounded contract foundation, 2026-10-31) |
| GitHub issue / PR | #88 / shared-contract PR |
| Open decision ID | — |
| Related ADRs | ADR-0008, ADR-0015 |
| Supersedes / superseded by | — |

## Context

Live Issue #88 and Chat 6 require a successful first-class C-026 `NO_TRADE`
result with machine-readable abstention reasons, including invalid evidence.
The current `NoTradeReason` vocabulary has no truthful code for invalid
provenance, identity, digest, or future-dated invalid input. `INSUFFICIENT_DATA`
does not preserve that distinction, and explanatory text is not semantic
authority.

C-026 schema 1 is an immutable serialized contract consumed by downstream
readers, including learning references. The repository's canonical envelope
identifies a typed contract by `(contract_id, schema_version)` and readers
reject unsupported schema versions. An enum member is part of that typed
schema: extending the schema-1 enum would leave older schema-1 consumers unable
to decode a payload that still claims schema 1.

## Alternatives

### Option A — Add `INVALID_PROVENANCE` to the schema-1 enum

Benefits: one type and a smaller source diff.

Costs, risks, and constraints: breaks closed-enum schema-1 consumers while
claiming the payload is schema 1; it changes interpretation without a version
discriminator. Rejected.

### Option B — Add C-026 schema 2 with a versioned reason enum

Benefits: preserves every v1 reason, wire representation, and historical hash;
older readers can reject the schema-2 discriminator before interpreting the
new reason.

Costs, risks, and constraints: adds a second typed model and requires readers
that need the new reason to opt into schema 2. Selected.

### Option C — Map the condition to `INSUFFICIENT_DATA` or explanation text

Costs, risks, and constraints: loses the required machine-readable distinction
and can misstate invalid provenance as missing or insufficient evidence.
Rejected.

## Decision

Add additive C-026 schema 2 as `NoTradeDecisionV2` with `NoTradeReasonV2`.
The v2 decision reuses the v1 field shape and validations, with the schema
discriminator set to `2` and the reason type selected from the v2 closed
vocabulary. The v2 vocabulary contains every v1 value plus exactly one new
reason: `INVALID_PROVENANCE`. Schema 1 and `NoTradeReason` remain unchanged.

`INVALID_PROVENANCE` means a required provenance binding is invalid or
unverifiable, including identity/digest mismatch or invalid source-time
ordering. It does not mean merely missing, stale, or insufficient evidence;
the existing codes retain those meanings. Explanation remains supplementary
text and cannot replace the typed reason.

Both versions retain first-class successful `NO_TRADE` lifecycle semantics,
optional candidate/strategy IDs, explicit provenance, and deterministic
identity supplied by the eventual producer. Neither version adds risk/human
approval, order intent, or paper/testnet/live execution authority.

## Reasoning

This is the smallest versioned change that preserves historical meaning and
allows schema-aware consumers to fail closed. It follows Chat 6's requirement
for machine-readable reason codes and uses the repository's existing versioned
contract pattern. No Master Playbook change is needed.

## Consequences

- Existing C-026 schema-1 serialized artifacts and hashes remain valid and are
  not rewritten or backfilled.
- New v2 artifacts serialize under the existing `canonical-json-v1` / `wire-1`
  envelope with `contract_id: C-026` and `schema_version: 2`. Hashing includes
  the versioned document and reason value.
- A reader supporting only schema 1 rejects schema 2 through the existing
  unsupported-schema path. It must not coerce to v1 or reinterpret the reason.
- The learning contract accepts C-026 by contract ID and stores
  `ContractReference.schema_version`; it does not parse C-026 payloads. No
  learning schema change is needed, and a v2 reference is covered by tests.
- No C-026 runtime producer or C-026-specific persistence model exists in the
  current tree. No database migration, DDL, history rewrite, or backfill is
  required. Any future persistence must retain schema version in the key, as
  the generic lineage model already does.
- Runtime mapping remains Issue #88 work and must use v2 when emitting
  `INVALID_PROVENANCE`; this ADR adds no mapper or execution capability.

## Safety and validation

Tests freeze the schema-1 reason vocabulary and canonical serialization,
exercise v2 serialization/parsing and unsupported-version rejection, preserve
duplicate/empty-reason rejection and the `NO_TRADE` lifecycle invariant, and
verify the learning consumer accepts a versioned C-026 reference. No runtime
qualification, risk, approval, or execution behavior changes.
