# ADR-0002: Vendor-neutral LLM provider and model routing policy

## Metadata

| Field | Value |
|---|---|
| Status | Proposed |
| Date | 2026-09-06 |
| Decision owner | Platform Architect |
| Human approver | Pending — AnjanaKavinda |
| GitHub issue / PR | #214 / pending |
| Open decision ID | OD-0010 |
| Related ADRs | ADR-0001 |
| Supersedes / superseded by | — |

## Context

OD-0010 requires an explicit LLM provider/model routing policy before the independent AI reviewer execution adapter in Issue #211 can be implemented.

The repository already defines vendor-neutral capability tiers — `economical-fast`, `strong-coding-reasoning`, and `premium-strongest-available` — plus review tiers R1/R2/R3. PR #213 added a vendor-neutral `IndependentReviewerAdapter` execution contract and explicit AI-cost guardrails.

A provider decision is required now because implementing Issue #211 without one would force the coding agent to invent provider-specific behavior, recreate architecture decisions during implementation, or consume additional premium AI credits resolving ambiguity.

The decision must preserve provider portability, fail-closed governance, bounded contexts, independent reviewer/session separation, and human final authority. It must not change runtime trading, deterministic risk, approval, execution, exchange, learning, or live-trading authority.

Current public pricing snapshot used only as a decision input, not a permanent contract:

- OpenAI GPT-5.6 Luna: approximately $0.20 / 1M input tokens and $1.20 / 1M output tokens.
- OpenAI GPT-5.6 Terra: approximately $2 / 1M input tokens and $12 / 1M output tokens.
- OpenAI GPT-5.6 Sol: approximately $4 / 1M input tokens and $20 / 1M output tokens.

Official references:
- https://developers.openai.com/api/docs/models
- https://openai.com/api/

Pricing and model availability are operational configuration data and may change without changing this ADR.

## Alternatives

### Option A — Single hard-coded provider/model family

Bind orchestration and reviewer logic directly to one provider and model family.

Benefits:

- simplest initial implementation;
- least configuration.

Costs, risks, and constraints:

- provider lock-in;
- provider/model names leak into governance code and contracts;
- model migration requires code changes;
- weak portability and resilience;
- conflicts with the vendor-neutral adapter already approved in PR #213.

### Option B — Vendor-neutral adapters with allowlisted provider/model mappings

Keep provider/model selection outside domain contracts. Route capability/review tiers deterministically, then resolve each tier through approved configuration to a provider/model adapter.

Benefits:

- preserves stable contracts;
- allows cost-aware tier mapping;
- supports later provider substitution without changing governance semantics;
- centralizes security, audit, timeout, retry, and usage controls;
- keeps provider choice explicit and human-governed.

Costs, risks, and constraints:

- more configuration than Option A;
- each provider adapter requires validation;
- fallback policy must be tightly controlled;
- configuration errors must fail closed.

### Option C — Unmanaged per-agent provider/model selection

Allow each development or runtime agent to choose its own provider/model.

Benefits:

- local flexibility;
- potentially fast experimentation.

Costs, risks, and constraints:

- non-deterministic routing;
- poor auditability;
- cost drift;
- inconsistent safety/security controls;
- agents could implicitly escalate capability or change provider behavior;
- incompatible with the governed model-routing architecture.

## Decision

Select **Option B: vendor-neutral adapters with allowlisted provider/model mappings**.

The routing contract selects capability/review tiers. A separate approved configuration maps those tiers to provider/model identifiers.

For the first implementation of the **development-governance independent reviewer only**, approve OpenAI as the initial provider mapping:

| Governance capability | Initial approved model |
|---|---|
| `economical-fast` / R1-eligible review | `gpt-5.6-luna` |
| `strong-coding-reasoning` / R2 review | `gpt-5.6-terra` |
| `premium-strongest-available` / R3 review | `gpt-5.6-sol` |

This initial mapping is configuration, not a domain-contract guarantee.

Other providers may be introduced behind the same adapter boundary after explicit validation and human approval. Provider/model identifiers must not be embedded into review request/result domain contracts beyond optional audit metadata.

Runtime trading-agent model mappings are not fixed by this initial development-review mapping. They must use the same policy shape — approved adapter plus allowlisted configuration — and remain subject to their own implementation readiness, security, cost, and governance controls.

## Reasoning

This option best matches the existing architecture and current development needs:

1. PR #213 already establishes a provider-neutral execution contract.
2. The current GPT-5.6 family maps cleanly to the repository's economical/strong/premium tiers, allowing cost-sensitive R1/R2 use while reserving the strongest model for R3.
3. Provider/model pricing and availability change faster than domain contracts; therefore they belong in governed configuration.
4. A multi-provider adapter boundary avoids future lock-in without introducing uncontrolled provider switching.
5. The decision prevents another coding-agent cycle from resolving provider ambiguity during implementation.
6. Cost optimization remains subordinate to required tier, safety, correctness, security, statistical integrity, deterministic risk, and human approval.

## Consequences

Positive:

- Issue #211 can be implemented against a stable provider-neutral adapter.
- Development AI-review cost can be controlled by tier.
- Provider/model changes can occur through governed configuration and validation rather than domain-contract rewrites.
- Provider/model/version/usage/cost can be audited when available.
- No model gains additional authority.

Negative / operational obligations:

- OpenAI credentials and secret management must be configured separately before execution.
- Provider adapter behavior, timeouts, structured-output validation, and failure handling require tests.
- Model aliases must not silently change trust semantics; where reproducibility requires it, deployments should record the exact returned model/version metadata.
- Cross-provider automatic fallback is not enabled by this ADR.
- Provider outages fail closed unless a separately approved fallback mapping exists.

Implementation sequencing:

1. accept this ADR through human review;
2. update OD-0010 to Accepted/Resolved only after approval;
3. configure provider/model mapping and secrets outside domain contracts;
4. implement Issue #211 as a bounded adapter task;
5. independently review and provenance-attest the implementation;
6. keep canonical Issue 004 / GitHub #6 blocked until all pilot prerequisites are satisfied.

## Contract and traceability impact

| Area | References and impact |
|---|---|
| Playbook requirements | Preserves multi-agent governance, human authority, auditability, and cost-aware AI usage |
| Cross-cutting artifacts | OD-0010 in `docs/cross-cutting/14-open-decisions.md`; no impact to OD-0024 |
| Contracts / events | Uses `INDEPENDENT-AI-REVIEWER-EXECUTION-CONTRACT-V1.md`; provider mapping remains outside its domain schema |
| Requirements traceability | Issue #214, Issue #211, Issue #209 / PR #210, PR #213 |
| Versioning / migration | Initial provider mapping is configuration; future adapters/mappings require validation and human approval but do not require domain-contract version changes unless semantics change |

## Safety, security, and failure behavior

- Provider API credentials are secrets and must never be stored in repository variables, prompts, comments, provenance payloads, or audit logs.
- Missing credentials, unapproved provider/model mapping, unavailable provider, schema-validation failure, timeout exhaustion, stale head, or ambiguous configuration fails closed.
- No AI model may approve or merge repository changes as final authority.
- Independent AI review remains a technical pre-review/governance gate.
- `AnjanaKavinda` is the final human reviewer, final approval authority, and final manual merge authority.
- No provider/model receives live-trading, exchange, deterministic-risk, approval, execution, or production-promotion authority.
- No automatic cross-provider fallback is permitted for R3/high-risk review without a separately approved mapping and validation.
- Cost thresholds and bounded retry/context rules from the independent reviewer contract remain mandatory.
- `GOVERNED_PILOT_ENABLED` remains false/unset until separately authorized.
- Canonical Issue 004 / GitHub Issue #6 remains blocked until its full prerequisite set is satisfied.

## Approval record

Pending human repository-owner review.

If approved by `AnjanaKavinda`, update:
- Status -> `Accepted`;
- Human approver -> `AnjanaKavinda`;
- approval date/conditions;
- ADR register;
- OD-0010 status and linked ADR.

Until that approval is recorded, this ADR is Proposed and must not be treated as implementation authority.
