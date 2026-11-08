# ADR-0021: Proposed PERSONAL_SPOT_RESEARCH analysis producer path

## Metadata

| Field | Value |
|---|---|
| Status | Accepted on merge of PR #464 |
| Date | 2026-11-06 |
| Decision owner | Platform Architect |
| Human approver | AnjanaKavinda, by merging PR #464 |
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
regime, C-009/C-010 findings, and registry-resolved C-093 independence output.
Because #56's distinct C-008 evidence cannot satisfy the unchanged C-007 v4
regime-evidence resolver, include a typed C-012 `UNAVAILABLE` assessment with
an exact C-069 explanation rather than projecting or relabeling #56 evidence.
Validate these components and the provider-produced typed C-019 v2 draft,
then construct and validate C-006 v5 directly. Existing C-006 v1–v4 contracts
and the existing #68 C-006 v4 consumer/binder remain unchanged.

Benefits:

- Does not fabricate a C-019 v1 assessment.
- Keeps the C-005 regime deterministic and provenance-bound.
- Makes missing technical context explicit and prevents strategies that
  require available C-012 findings from advancing.
- Uses the approved C-019 v2 / C-006 v5 contract path without changing schema
  versions, C-007 v4 closure, or historical payload semantics.

Costs, risks, and constraints:

- This is a regime-centered research handoff; it does not include #56 technical
  findings in the C-006 closure.
- Any strategy requiring available C-012 must return NO_TRADE.
- Requires an additive producer path and full integration tests.
- Deterministic inputs and exact output references must be assembled from the
  live Spot analysis path; missing or mismatched inputs block the result.
- A future multi-method evidence closure requires a separate owner-approved
  versioned contract design.
- A production model/provider configuration remains a separate allowlisted
  configuration and empirical-quality prerequisite under ADR-0002.

**Recommended, with the stated limitation.**

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

**Option B is accepted when PR #464 is merged by the human repository owner.**
That merge records the decision to keep C-007 v4/C-006 v5, expose C-012 as
unavailable, and proceed under the exact persistence, idempotency, provenance,
and fail-closed requirements below. Before that merge, no runtime
implementation is authorized.

The proposed producer boundary is:

1. The only producer invocation is an explicit successful Spot refresh. The
   refresh creates or selects one exact validated snapshot; no separate
   analyze-only request may attach a new analysis closure to an existing
   snapshot.
2. Resolve C-003/C-005/C-008 from that snapshot and run only registered
   deterministic producers valid for the exact C-007 v4 closure. Preserve
   C-005 as C-006's separate `regime` field. Do not relabel or project #56
   `spot-market-structure` evidence into the C-007 v4
   `spot-market-regime` evidence set. When #56 cannot be admitted, construct
   the explicit C-012 `UNAVAILABLE` assessment and C-069 explanation described
   below; then run the remaining local finding tasks.
3. Allocate the final C-007 snapshot identity once. Build an in-memory seed
   manifest containing the immutable input scope and supported C-005/C-008
   references, then run C-093 against that exact scope. C-093's approved input
   fingerprint excludes analysis-output references, so adding final outputs
   does not change the assessed input scope or create a digest cycle.
4. Build C-009 and any C-010 records from the deterministic findings and exact
   C-093 result. Finalize the C-007 v4 manifest in memory with the exact
   supported C-005/C-008/C-009/C-010/C-093 references. Its `assessment_ids`
   contains the exact C-012 assessment ID; `analysis_outputs` contains only
   contracts allowed by C-007 v4. Validate the final manifest, all referenced
   records, and their digests before any analysis-closure persistence.
5. Prepare the required deterministic C-006 inputs truthfully: `regime` is the
   exact C-005 result; `assessments` contains the exact C-012 UNAVAILABLE assessment
   whose ID is in the finalized manifest; `multi_timeframe_state` records only
   the timeframe(s) actually selected and validated for this request; and the
   nonempty C-069 uncertainty set is derived deterministically from exact
   coverage and unavailable profile inputs. Validate these values and all
   deterministic C-007 dependencies, but do not construct or claim full
   C-006 v5 validation yet: its required C-019 v2 assessment does not exist
   until after the provider call. Do not invent assessments, timeframes, or
   uncertainty records to satisfy nonempty fields; fail closed if any input is
   unavailable.
6. Reserve the producer request durably before invoking the provider, using
   the idempotency rules below. Only after the reservation succeeds may the
   provider-neutral router invoke an explicitly configured and allowlisted
   C-067 route to draft the bounded C-019 v2 adversarial content.
7. Validate the model draft, construct C-019 v2 and the complete C-006 v5,
   then run the full C-006 v5 validator against the exact finalized C-007
   digest. Only after that validation, atomically persist:
   - the final C-007 v4 closure and every referenced record;
   - the standalone C-006 v5 lineage record, keyed by its exact context ID and
     schema version, with its canonical content digest and exact C-007 reference;
   - the exact C-062 result whose output is that same C-006 v5 record;
   - exactly one linked C-066 evaluation, with the exact C-006 context ID;
   - the exact C-067 routing provenance; and
   - the completed producer-request reservation.
   Bind fan-out, C-006, C-062, and C-066 to the same exact context,
   correlation, and trace identities required by #90. Persist C-006 through
   the bounded internal Spot write path; do not add or change an HTTP/API
   operation in #90. Expose only the fully persisted exact handoff to #90.

The market snapshot/raw market-data write may precede this flow. Under accepted
ADR-0012, analysis records are appended only within the same explicit successful
refresh operation; no analyze-only endpoint, GET, UI reload, or readback may
write an analysis bundle. The immutable analysis closure is written only once,
after final C-007/C-019/C-006 construction and full validation. A snapshot with
an existing exact, current bundle may be read/replayed without a write. A
snapshot without a bundle remains analysis-unavailable until a later successful
explicit refresh creates its matching bundle. Never rewrite, append, or
backfill a different manifest for a legacy snapshot. If analysis persistence
fails, preserve the valid OHLCV refresh result and return analysis unavailable,
as required by ADR-0012. No amendment to ADR-0012 is proposed.

### C-012 context availability mapping

The current #56 `MarketStructureAnalysis` is not admissible as an available
C-012 assessment in the C-007 v4/C-006 v5 closure. The C-007 v4 resolver
requires the exact C-005 regime evidence IDs and requires every bound C-008
record to use the `spot-market-regime` method. #56 emits distinct
`spot-market-structure` evidence. Converting its C-008 version, adding
lineage, or changing its asset cannot make those records satisfy the resolver
without changing their analytical meaning. The original #56 assessment and
evidence remain immutable and outside this C-007 v4 closure.

Preserve the existing contracts and use an explicit, typed C-012
`UNAVAILABLE` assessment when no C-012 evidence is admissible under the exact
C-007 v4 binding. Include its identity in the manifest's `assessment_ids` and
include the exact assessment in C-006 v5. It has no findings, observations,
evidence IDs, or contradiction IDs; it references the exact C-003 v2 quality
report, uses the `UNAVAILABLE` status, and links the deterministic C-069
uncertainty explaining that #56 evidence is incompatible with the C-007 v4
regime-evidence binding. Register the assessment's provenance method/version
before runtime use. Its required numeric confidence field is not interpreted
when status is `UNAVAILABLE`; every consumer must branch on status and must
never treat that value as a confidence estimate.

C-005 remains the evidence-backed primary regime in C-006's separate `regime`
field. Only its exact C-008 v2 `spot-market-regime` evidence is bound by
C-007 v4 and available to C-019 v2. C-006 v5 validation still resolves the
full C-007 v4 closure and requires the exact C-012 assessment ID listed in the
manifest. This is a truthful availability record, not a projection of #56
findings and not a claim that technical structure was analyzed in this
context.

If the regime, evidence, C-003 quality, or unavailable assessment cannot be
validated exactly, the producer is blocked. Any strategy or candidate path
that requires an `AVAILABLE` C-012 assessment must return NO_TRADE; it must
not advance a candidate using the unavailable assessment. This producer
supplies a valid regime-centered research handoff while exposing the missing
technical context. Enabling #56 technical findings in the same C-007 closure
requires a separate owner-approved, versioned contract design and is outside
this no-schema-change proposal.

### Exact C-006 v5 field mapping (no placeholder analysis)

C-006 v5 has required fields that are not all populated by C-005/C-009/C-010.
Use this exact mapping:

- `regime` is the exact validated C-005 regime; it remains separate from
  `assessments`.
- `assessments` contains one C-012 `TechnicalAssessment` with status
  `UNAVAILABLE`, created by a deterministic unavailable-state adapter because
  the current request has no approved #55/#56 pivot/break policy and the
  available #56 method evidence is not admissible in C-007 v4. It has no
  findings, observations, or evidence IDs. Its stable identity binds the exact
  snapshot ID/digest, C-003 ID/digest, unavailable reason, and registered
  adapter version. It must not be represented as a #56 calculation result or
  given a numeric confidence interpretation.
- `assessment_ids` is exactly the ordered identity list for
  `context.assessments`; C-005 remains represented by `context.regime` and
  the C-007 binding. C-009/C-010 remain exact manifest outputs, not entries in
  the C-006 v5 `VersionedAssessment` tuple.
- `multi_timeframe_state` is the explicit singleton
  `("UNAVAILABLE:CROSS_TIMEFRAME_NOT_REQUESTED",)` for this one-timeframe
  producer request. It records that no cross-timeframe comparison was made;
  it must never be parsed as a directional finding.
- `uncertainties` contains deterministic C-069 v1 records derived from the
  exact snapshot scope and unavailable-input reason. IDs bind the same exact
  snapshot and reason. No unprovided timeframe, finding, evidence, or confidence
  is synthesized.

### C-069 v1 unavailable-context projection

For the exact C-012 unavailable condition, build one C-069 v1 record using a
registered deterministic projection method 
`spot-profile-unavailability-severity-v1`:

- `category`: `METHOD`, because the required structure method/policy is not
  available in the approved C-007 v4 evidence closure.
- `affected_finding_ids`: empty; no structure finding was produced.
- `affected_domains`: exactly `("spot-market-structure",)`.
- `severity`: decimal `1.0`, meaning complete unavailability of this affected
  domain for this request only. It is not probability, analytical confidence,
  market-risk score, or a global context score; it cannot block unrelated
  domains by itself.
- `reducible`: true; `required_evidence` names both the approved #55/#56
  pivot/break policies and an accepted multi-method C-007 compatibility
  decision. Until both exist, resolution remains blocked.
- `as_of`: exact C-007 analysis cutoff. `expires_at`: the earliest expiry among
  the exact C-003 quality report, C-007 manifest, and C-012 unavailable
  assessment; it must not exceed C-006 expiry.
- `resolution_status`: `UNRESOLVED`.
- `uncertainty_id`: deterministic from exact C-007 snapshot identity/digest,
  C-012 unavailable reason, and this projection method/version.

This method/version is provenance and part of the producer idempotency key.
If any required bound or scope cannot be derived from these exact inputs, the
producer fails closed instead of inventing a value.

If C-012 v1 or C-069 v1 cannot represent this mapping truthfully, stop for an
architecture correction; do not weaken validation or create a new contract
version inside this producer implementation.

### Why this proposal does not add a multi-method contract lane

The C-007 v4 resolver binds C-008 evidence to the exact regime evidence and
method. Admitting available #56 `spot-market-structure` evidence would require
a new additive evidence-manifest version and a compatibility path through the
following existing pins:

| Area | Current pin | Compatibility work required for available #56 evidence |
|---|---|---|
| C-007 analysis manifest | v4 | New schema/lineage version with distinct, typed evidence groups and method-specific closure validation |
| C-006 context / C-019 adversarial | C-006 v5 / C-019 v2 pin C-007 v4 | New versions that bind the new manifest and preserve exact evidence semantics |
| C-009 / C-010 / C-093 | C-009/C-010 v3 and C-093 v1 pin C-007 v4 | New versions or an explicitly compatible binding design |
| Closed lineage and persistence | C-007 v4, C-006 v5 and their current typed codecs/allowlists | Additive codecs, durable identities, allowlist/migration, exact read/resolve behavior |
| Strategy chain and API | #80–#90 resolve exact C-007 v4/C-006 v5 and evidence closure | Additive consumer compatibility and end-to-end revalidation without changing #90's frozen API |

This is a material shared-contract and consumer expansion, not a local #462
producer correction. It also would not create usable #56 evidence by itself:
the current approved profile does not supply the pivot/break policies #55/#56
require. Keep this proposal on C-007 v4/C-006 v5, expose C-012 as unavailable,
and require NO_TRADE for strategies that declare C-012 required. Revisit the
multi-method lane only after the required deterministic policies are approved
through their existing issue/decision path and a separately scoped compatibility
decision is accepted. Do not treat this Spot producer or the Phase 1 objective
as complete while any required strategy evidence remains unavailable; Futures
is still a separate required Phase 1 lane.

### Producer request identity, reservation, and replay

The producer request key is the canonical SHA-256 digest of a
versioned `ProducerRequestIdentity` value using the repository's canonical
serialization version. Its identity has four explicit components:

1. **Profile and agent:** the exact `PERSONAL_SPOT_RESEARCH` profile ID/version
   and the registry-resolved C-061 agent ID, definition version, and capability
   profile version.
2. **Input closure:** the exact C-002 snapshot ID/schema/lineage/content digest;
   C-003 quality report ID/schema/lineage/digest and quality-policy ID/version;
   C-005 regime ID/schema/lineage/digest plus regime method/profile versions;
   the sorted exact C-008 evidence IDs/schema/lineage/digests and each evidence
   method version; the C-007 v4 manifest ID/schema/lineage/digest; its exact
   C-001 observation IDs/digests and C-091 source IDs/digests; and the selected
   timeframe and coverage bounds.
3. **Producer vector:** the schema/lineage versions and exact method/profile
   versions used for C-012 unavailable-state projection, C-009 confluence,
   C-010 conflict, C-093 independence, and C-069 uncertainty projection. Include
   C-003, C-005, C-008, and C-007 versions here as resolved identity fields too;
   duplicate mention in the input closure is intentional and the canonical
   object has one value per named component.
4. **Handoff and routing:** the exact C-019 method/model/prompt IDs and versions,
   C-067 route identity/version, and schema/lineage versions for the resulting
   C-019 v2, C-006 v5, C-062, C-066, C-067, and C-069 records.

Encode the version vector as sorted `(component_role, contract_id, schema_version,
lineage_version, component_id, component_version)` tuples, with explicit nulls
only where the contract has no such field. A changed profile, agent, source or
observation closure, schema/lineage version, deterministic method, route, model,
or prompt version MUST produce a different key. Compute the key only after
validating exact current inputs and resolving the allowlisted route, but before
any provider invocation. The identity never contains prompt text, credentials,
or model output.

An additive internal persistence record with a unique request key is inserted
as `IN_PROGRESS` before the provider call. A concurrent duplicate observes the
existing reservation and does not make another provider call. The successful
completion transaction records the exact C-006/C-019/C-062/C-066/C-067
references and marks the reservation `COMPLETED`. A repeated identical request
may replay only that exact stored handoff after re-resolving every reference
and confirming freshness; stale, changed, missing, or mismatched inputs return
a typed unavailable/blocked result and never fall back to a newer snapshot.
Terminal failure is stored as a bounded failure state and replayed without
retry. An abandoned `IN_PROGRESS` reservation is treated as indeterminate and
must not trigger an automatic provider retry. A changed snapshot, provenance,
or approved route/version produces a different request key.

The reservation contains no raw prompt, credential, or provider response text.
It follows the accepted Spot lineage backup/retention rules and is covered by
an additive migration. The migration adds no public contract, C-007 output kind,
or shared schema version and does not rewrite historical rows.

The deterministic primary Spot interpretation is the exact registered C-005
regime and its C-007-bound C-008 evidence, together with deterministic
C-009/C-010 findings bound to the validated snapshot. The C-012 assessment is
explicitly `UNAVAILABLE` whenever #56 evidence cannot be admitted by the
unchanged C-007 v4 resolver; it must not contain projected #56 findings.
C-006 `assessments` identities must equal the C-007 `assessment_ids` exactly.
C-005 remains represented by C-006 `regime` and the C-007 binding; it is not
misrepresented as a `VersionedAssessment`.
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
contracts without pretending the existing #56 output satisfies C-007 v4.
C-006 v5 separates C-005 regime from its required typed assessment list. The
current `assessment_ids=(C-005 regime ID,)` is invalid. The exact #56 C-012
assessment cannot be admitted as available because its C-008 evidence uses
`spot-market-structure`, while C-007 v4 binds only C-005 evidence using
`spot-market-regime`. A typed C-012 `UNAVAILABLE` mapping satisfies the
schema status semantics without changing evidence identity or method.
Consumers fail closed for strategies requiring available technical analysis.
A future multi-method evidence closure requires its own owner-approved
versioning decision. Timeframe state and C-069 uncertainties derive from the
exact Spot scope and profile limitations, not fabricated defaults.

The finalization order preserves the immutable analysis closure: all supported
outputs and C-006 required fields are assembled and validated before the
single analysis persistence write. C-093 hashes the exact input scope while
excluding output references by design, allowing the final manifest to include
the registry-resolved C-093 output without a digest cycle. The request
reservation prevents identical requests from duplicating provider calls, and
freshness-checked replay prevents stale handoffs from re-entering #90.

Keeping C-007 v4's supported output kinds intact preserves ADR-0010's
no-digest-cycle design. C-019 v2 remains outside the manifest output closure
and binds its exact digest, quality report, and usable evidence records. C-093 remains
resolved through its owner registry, with dependence and indeterminate states
preserved; multiple findings from the same Spot OHLCV input do not become
independent evidence.

The proposal preserves #68's deterministic binder for its existing use and
preserves #90's exact-reference, fail-closed consumer boundary. It adds only an
upstream producer path. The standalone C-006 v5 record is explicitly persisted
because #90 resolves that exact input from lineage; this is producer-owned
persistence under the existing closed C-006 codec/identity, not a change to
#90's API or behavior. It does not claim that a model's analytical output is
profitable or statistically validated; those remain separate evidence and
qualification questions.

## Consequences

Positive:

- A regime-centered user-triggered Spot producer can feed the merged #90 API
  without a fabricated legacy assessment or weakened provenance; incompatible
  technical context is explicitly unavailable.
- All provider output remains untrusted until typed parsing, evidence
  resolution, version checks, freshness checks, and C-006 v5 validation pass.
- Existing C-006/C-019 and C-007 schemas remain stable.

Operational obligations and limits:

- This proposal is not implementation authority until the owner approves it.
- The producer remains unavailable when its provider/model route is not
  configured and validated.
- Identical requests cannot produce duplicate provider calls. A stored exact
  handoff is replayed only after current freshness and lineage checks; failed
  or indeterminate requests do not retry automatically.
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

1. Implement deterministic Spot finalization and direct C-006 v5 production
   with an explicit unavailable C-012 state and contract/provenance tests;
   require NO_TRADE for strategies needing available C-012.
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
| Cross-cutting artifacts | OD-0027 tracks this proposed producer composition. Register the C-012 unavailable-state provenance method/version before runtime use; do not implement a #56-to-C-007-v4 evidence projection. Preserve the Evidence Graph, C-067 routing provenance, C-062/C-066 one-to-one linkage, and C-093 owner registry. |
| Contracts / events | No contract schema or event changes proposed. A later multi-method evidence closure requires separate owner-approved versioning design. Use C-003 v2, C-005 v1, C-007 v4, C-008 v2, C-009/C-010 v3, C-012 v1, C-019 v2, C-006 v5, C-062/C-066/C-067 v1, and C-069 v1. Use only the output kinds already supported for the existing C-007 v4 analysis closure. |
| Requirements traceability | [Issue #462](https://github.com/AnjanaKavinda/crypto-trading-ai-agent-platform/issues/462); preserve #68, #90, #91 gates; Futures #39 then personal slice #61 remains required for Phase 1. |
| Versioning / migration | No public contract schema or output-kind changes. Use the existing closed C-006 v5 identity/codec and add it to the producer-owned append allowlist so #90 can resolve its exact standalone context. Add one internal producer-request reservation table with a unique canonical request key; use a forward-only additive migration and preserve existing identities, canonical bytes, hashes, codecs, readers, backup, and retention rules. No historical backfill. |

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

Owner approval is recorded by merging PR #464. After that merge, this ADR is
implementation authority for the bounded Issue #462 runtime path. Until the
merge, Issue #462 must not implement the proposed runtime architecture.
