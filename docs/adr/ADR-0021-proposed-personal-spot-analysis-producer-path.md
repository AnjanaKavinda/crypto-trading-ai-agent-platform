# ADR-0021: Proposed PERSONAL_SPOT_RESEARCH analysis producer path

## Metadata

| Field | Value |
|---|---|
| Status | Proposed |
| Date | 2026-11-06 |
| Decision owner | Platform Architect |
| Human approver | Pending |
| GitHub issue / PR | [Issue #462](https://github.com/AnjanaKavinda/crypto-trading-ai-agent-platform/issues/462) |
| Open decision ID | OD-0027 |
| Related ADRs | ADR-0002, ADR-0010, ADR-0012, ADR-0020 |
| Supersedes / superseded by | — |

## Context

The merged PERSONAL_SPOT_RESEARCH strategy-signal API (#90) consumes a persisted
C-062/C-066/C-067 handoff. It deliberately does not create that handoff or call
a provider. The bounded #68 implementation validates a caller-supplied
adversarial draft and builds C-019 v2 inside C-006 v5, but requires an existing
validated C-006 v4 / C-007 v4 context and performs no provider call, refresh,
persistence, or API work.

The production Spot refresh path does not construct the full upstream context
required by #68. C-006 v4 embeds C-019 v1, whose required content cannot be
truthfully synthesized as a placeholder merely to obtain a C-006 v4 object.
The existing Spot request path also needs a controlled finalization point for
the exact C-007 v4 manifest and the registered deterministic findings and
independence output. Without a producer decision, adding only a model call to
#90 would leave the result unvalidated, unpersisted, or impossible to consume.

The Phase 1 product objective includes both Spot and Futures research. This
decision covers only the Spot producer prerequisite. It does not authorize a
Futures feed or complete Phase 1. Futures remains sequenced after the Spot gate,
with its own source decision and validated data path through #39 before the
approved personal slice of #61.

## Alternatives

### Option A — Synthesize a C-006 v4 base context

Create a C-006 v4 object from the live Spot refresh outputs, then pass it to the
existing #68 binder.

Benefits:

- Reuses the existing #68 function signature.
- Requires fewer visible builder changes.

Costs, risks, and constraints:

- C-006 v4 requires C-019 v1. The current Spot pipeline does not produce the
  substantive C-019 v1 assessment required by that contract.
- Filling C-019 v1 with empty, default, or model-invented values would be
  misleading and could create false analytical provenance.
- Producing both C-019 v1 and C-019 v2 would duplicate or confuse the primary
  interpretation and adversarial responsibilities.

**Not recommended.**

### Option B — Add a direct, validated C-006 v5 producer path

Add an additive producer/builder path that consumes the exact finalized C-007
v4 manifest, exact resolved C-003/C-008 Spot bindings, deterministic C-005
regime and assessments, C-009/C-010 findings, and registry-resolved C-093
independence output. It validates these components and the provider-produced
typed C-019 v2 draft, then constructs and validates C-006 v5 directly. The
existing C-006 v1–v4 contracts and the existing #68 C-006 v4 consumer/binder
remain unchanged.

Benefits:

- Does not invent or fabricate a C-019 v1 assessment.
- Keeps the primary Spot interpretation deterministic and provenance-bound.
- Uses the already approved C-019 v2 / C-006 v5 contract path without changing
  schema versions, C-007 v4 closure, or historical payload semantics.
- Provides one explicit validated boundary for the exact inputs required by the
  strategy-signal handoff.

Costs, risks, and constraints:

- Requires an additive producer path and full integration tests.
- The deterministic inputs and exact output references must be assembled from
  the live Spot analysis path; missing or mismatched inputs block the result.
- A production model/provider configuration remains a separate allowlisted
  configuration and empirical-quality prerequisite under ADR-0002.

**Recommended.**

### Option C — Expand C-007 v4 or reinterpret existing C-006/C-019 schemas

Put C-019 output or additional meta-analysis outputs into the C-007 v4 closure,
or reinterpret C-006 v4 / C-019 v1 to support the producer.

Benefits:

- Could make some references appear co-located in a single manifest.

Costs, risks, and constraints:

- Conflicts with ADR-0010's explicit decision to keep C-019 v2 outside the
  C-007 v4 output closure.
- Changes the meaning or compatibility of accepted schema versions and risks
  digest cycles or historical identity changes.
- Requires a larger contract-version and migration decision than this producer
  needs.

**Not recommended.**

## Decision

**Proposed: Option B.** The human repository owner has not yet approved this
architecture decision. No runtime implementation is authorized by this
proposal.

The proposed producer boundary is:

1. An explicit user request selects one exact, validated, current Spot snapshot.
2. Deterministic producers compute the registered Spot regime, evidence,
   confluence/conflict, and independence outputs against the exact input scope.
3. The producer finalizes the existing C-007 v4 manifest with exact,
   already-supported C-005/C-008/C-009/C-010/C-093 references. It does not add
   C-019 to the manifest closure or change supported output kinds.
4. The provider-neutral router invokes only an explicitly configured and
   allowlisted C-067 route to draft the bounded C-019 v2 adversarial content.
5. A new additive builder validates the exact manifest, C-003/C-008 provenance,
   deterministic assessments, C-093 reference, model draft, supported
   method/model/prompt versions, and expiry; it constructs C-006 v5 directly
   and runs the full C-006 v5 validator.
6. The accepted #90 orchestration path persists exactly one linked C-062 result,
   one C-066 evaluation, and the exact C-067 routing provenance, then exposes
   only the resulting handoff to the strategy-signal API.

The deterministic primary Spot interpretation is the exact registered C-005
regime, its C-007-bound evidence, and deterministic C-009/C-010 findings bound
to the validated snapshot. The C-006 assessment identities must remain exactly
those declared by the finalized manifest.
The model may produce only the adversarial/counter-thesis draft accepted by
#68. It may not replace the deterministic primary interpretation, invent
market data or calculations, or produce qualification, risk, approval, or
execution authority.

This ADR does not select a specific runtime provider or model. ADR-0002's
development-review mapping is not a runtime trading-analysis approval. A
production route must be explicitly allowlisted and configured, and its model
must satisfy ADR-0002's quality-first requirements for this workload. Until
then, a missing or unapproved route fails closed and no provider call is made.
There is no automatic retry, provider/model fallback, or background invocation.

## Reasoning

Option B is the smallest truthful path that composes the current approved
contracts. The primary interpretation can be represented by deterministic
regime and analytical records already associated with C-007, while C-019 v2
records the distinct adversarial challenge. C-006 v5 already embeds those
components and binds the exact C-007 v4 manifest. No contract change is needed
to express this composition; the change is an additive runtime producer path.

Keeping C-007 v4's supported output kinds intact preserves ADR-0010's
no-digest-cycle design. C-019 v2 remains outside the manifest output closure
and binds its exact digest, quality report, and usable evidence records. C-093 remains
resolved through its owner registry, with dependence and indeterminate states
preserved; multiple findings from the same Spot OHLCV input do not become
independent evidence.

The proposal preserves #68's deterministic binder for its existing use and
preserves #90's exact-reference, fail-closed consumer boundary. It adds only an
upstream producer path. It does not claim that a model's analytical output is
profitable or statistically validated; those remain separate evidence and
qualification questions.

## Consequences

Positive:

- A complete user-triggered Spot producer can feed the merged #90 API without
  fabricating a legacy assessment or weakening provenance.
- All provider output remains untrusted until typed parsing, evidence
  resolution, version checks, freshness checks, and C-006 v5 validation pass.
- Existing C-006/C-019 and C-007 schemas remain stable.

Operational obligations and limits:

- This proposal is not implementation authority until the owner approves it.
- The producer remains unavailable when its provider/model route is not
  configured and validated.
- Provider timeout, malformed output, stale snapshot, missing evidence,
  persistence failure, or provenance mismatch must yield a blocked/
  `NO_TRADE` result; no candidate may advance from partial output.
- Provider credentials remain outside source control, prompts, logs, tests,
  provenance payloads, and documentation.
- User-triggered analysis remains research-only. It adds no strategy
  qualification, independent profitability claim, risk, human approval,
  exchange credential, paper/testnet/live trading, or order submission.
- Futures remains a required Phase 1 workstream after Spot, but requires the
  separate source/product decision and validated data path in #39 before #61.

Implementation sequencing after approval:

1. Implement the deterministic Spot finalization and additive direct C-006 v5
   producer path with contract/provenance tests.
2. Implement bounded, user-triggered routing and validated persistence of the
   C-062/C-066/C-067 handoff under #462.
3. Enable a real provider route only after an explicit provider/model
   configuration and workload-quality review under ADR-0002.
4. Merge the complete Spot producer, then run the Wave 4 integrated checkpoint
   at the exact current `dev` SHA.
5. Assign #91 only if its dependencies and checkpoint pass.
6. Continue the Futures Phase 1 lane under #39 and #61; this Spot ADR does not
   close that obligation.

## Contract and traceability impact

| Area | References and impact |
|---|---|
| Playbook requirements | Master Playbook v2.2, Chat 5 analysis/evidence requirements and Chat 6 candidate-signal separation. No Playbook text change. |
| Cross-cutting artifacts | OD-0027 tracks this proposed producer composition. Preserve the Evidence Graph, C-067 routing provenance, C-062/C-066 one-to-one linkage, and C-093 owner registry. |
| Contracts / events | No contract schema or event changes proposed. Use C-003 v2, C-005 v1, C-007 v4, C-008 v2, C-009/C-010 v3, C-093 v1, C-019 v2, C-006 v5, C-062/C-066/C-067 v1. Use only the output kinds already supported for the existing C-007 v4 analysis closure. |
| Requirements traceability | [Issue #462](https://github.com/AnjanaKavinda/crypto-trading-ai-agent-platform/issues/462); preserve #68, #90, #91 gates; Futures #39 then personal slice #61 remains required for Phase 1. |
| Versioning / migration | None proposed. Existing identities, canonical bytes, hashes, codecs, and readers remain unchanged. New runtime records use existing versioned contracts. |

## Safety, security, and failure behavior

- This decision concerns explicit user-triggered analysis in research mode.
- The provider receives no exchange credentials and has no tools or direct
  exchange/network access beyond the approved model adapter.
- Inputs and outputs are bounded; route, model/prompt/method versions, usage,
  and cost limits are auditable.
- Missing configuration, disallowed route, timeout, output schema failure,
  unresolved evidence, stale data, unsupported versions, or persistence errors
  fail closed. No fallback route or stale cached handoff may be substituted.
- No model output is authoritative for deterministic calculations, strategy
  qualification, statistical claims, risk, approval, or execution.
- Research / Backtest / Paper / Shadow / Testnet / Live separation remains
  unchanged. Live trading remains disabled.

## Approval record

Pending human repository owner review. Until approved, this ADR is not
implementation authority and Issue #462 must not implement the proposed runtime
architecture.
