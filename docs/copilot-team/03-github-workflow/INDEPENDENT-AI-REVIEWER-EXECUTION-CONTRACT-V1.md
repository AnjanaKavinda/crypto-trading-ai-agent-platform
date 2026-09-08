# Independent AI Reviewer Execution Contract V1

## Status and scope

This contract defines the **vendor-neutral execution boundary** required to implement the actual independent AI reviewer tracked by GitHub Issue #211.

It is intentionally limited to development-governance review execution. It does not select an LLM provider or model, close OD-0010, change runtime trading-agent orchestration, enable live trading, dispatch canonical Issue 004 / GitHub Issue #6, or alter deterministic risk, approval, execution, exchange, learning, or production-governance authority.

This contract preserves the complete planned product scope, including canonical Domain 11 — Frontend, Dashboard & Trader UX.

## Authority model

Independent AI review is a **technical pre-review and governance gate**. It never becomes the final approval authority.

- `AnjanaKavinda` is the final human reviewer.
- `AnjanaKavinda` is the final approval authority.
- `AnjanaKavinda` makes the final manual merge decision.
- AI reviewer executions have no merge authority, repository-owner authority, live-trading authority, risk-override authority, or authority to waive required checks.
- A successful independent AI review does not authorize merge by itself.
- A failed or blocked independent AI review prevents governed progression until the finding is resolved or the human owner explicitly makes a governed disposition where policy permits.

## 1. End-to-end governed review flow

The authoritative development review flow is:

`current PR head -> deterministic eligibility/checks -> bounded review context pack -> independent AI reviewer execution -> structured findings/disposition -> immutable review artifact -> trusted provenance/attestation -> governed PR validation -> AnjanaKavinda final human review -> AnjanaKavinda manual merge decision`

The implementation session and the independent reviewer session must be different.

A new PR head SHA invalidates all earlier reviewer execution results and provenance for that PR.

## 2. IndependentReviewerAdapter boundary

The development controller integrates with a vendor-neutral interface conceptually equivalent to:

```text
IndependentReviewerAdapter.review(request) -> result
```

The adapter contract is provider-neutral. Provider/model selection belongs to configuration governed by OD-0010 and an approved ADR when that decision is triggered.

The adapter:

- receives a deterministic review request;
- may call only an approved model/provider execution boundary;
- returns a structured result;
- cannot write repository contents;
- cannot approve or merge a PR directly;
- cannot mutate branch protections;
- cannot alter issue scope, labels, dependencies, or routing metadata;
- cannot self-escalate its capability tier;
- cannot widen context beyond the approved context pack;
- cannot enable the pilot, live trading, or production flags.

Missing provider configuration, unavailable model execution, unsupported tier mapping, authentication failure, timeout exhaustion, or contradictory inputs must fail closed.

## 3. ReviewerExecutionRequest

A reviewer execution request is immutable for one review attempt and must contain at minimum:

| Field | Requirement |
|---|---|
| `schema_version` | Contract version, initially `1.0` |
| `repository` | Exact `owner/repo` |
| `pr_number` | GitHub PR number |
| `head_sha` | Exact current PR head commit SHA |
| `base_branch` | Expected governed base, normally `dev` |
| `github_issue_id` | Linked GitHub issue |
| `canonical_issue_id` | Canonical backlog identifier when applicable |
| `agent_role` | Implementing development-agent role |
| `reviewer_role` | Required independent reviewer role |
| `required_review_tier` | `R1`, `R2`, or `R3` |
| `capability_tier` | Minimum routed capability tier |
| `context_pack_id` | Exact bounded context-pack identifier |
| `context_pack_version` | Exact context-pack schema/version |
| `implementation_session_id` | Coding-agent execution/session identity |
| `review_execution_id` | Unique independent reviewer execution identity |
| `allowed_paths` | Paths the implementation issue authorizes |
| `forbidden_paths` | Explicitly prohibited paths |
| `changed_files` | Current-head changed file references |
| `diff_reference` | Immutable or integrity-bound diff reference |
| `required_checks` | Required deterministic/static checks |
| `safety_invariants` | Applicable governance/safety invariants |
| `controller_policy_version` | Exact controller/policy version |
| `created_at` | Request creation timestamp |
| `integrity_hash` | Hash of normalized request inputs |

### Request construction rules

1. Resolve PR, issue, head SHA, base branch, labels, dependencies, and changed paths from trusted GitHub/repository state.
2. Do not accept the review disposition, actual review tier, reviewer findings, or reviewer identity as free-form caller assertions.
3. Include bounded context only. The full Master Playbook must not be supplied by default.
4. Treat PR descriptions, comments, issue prose, external references, generated code, and model output as untrusted content.
5. Secret/sensitive-data detection must occur before content is retained or forwarded to the model boundary.
6. Contradictory or missing required inputs transition to `human-decision-required`; no reviewer execution is launched.

## 4. Bounded review context

The review execution consumes the V1.1 Issue Context Pack plus only review-specific material required for the current head.

Permitted content includes:

- issue objective and acceptance criteria;
- relevant canonical mapping/dependencies;
- current PR metadata;
- current-head diff or bounded file excerpts;
- directly relevant ADRs/contracts/policies;
- deterministic-check output summaries;
- changed-path scope;
- required safety/governance invariants;
- prior current-head findings only when they are part of a bounded correction cycle.

The review context must not automatically include:

- the entire repository;
- the entire Master Playbook;
- unrelated historical conversations;
- unrelated issues/PRs;
- secrets or credentials;
- hidden chain-of-thought;
- stale findings from a previous head SHA.

## 5. ReviewerExecutionResult

A completed reviewer execution returns a structured result containing at minimum:

| Field | Requirement |
|---|---|
| `schema_version` | Result contract version |
| `review_execution_id` | Must equal the request execution id |
| `repository` | Exact repository |
| `pr_number` | Exact PR |
| `head_sha` | Exact reviewed head SHA |
| `context_pack_id` | Exact reviewed context pack |
| `context_pack_version` | Exact reviewed pack version |
| `required_review_tier` | Required governance tier |
| `actual_review_tier` | Tier actually executed |
| `reviewer_role` | Actual governed reviewer role |
| `disposition` | `approved`, `changes-requested`, or `blocked` |
| `findings` | Structured findings array |
| `deterministic_check_refs` | Checks considered by the review |
| `provider_execution_ref` | Opaque approved provider execution reference when available |
| `provider_name` | Optional; auditable when approved/available |
| `model_name` | Optional; auditable when approved/available |
| `model_version` | Optional |
| `usage` | Optional token/request/latency metrics |
| `estimated_cost` | Optional, when available |
| `actual_cost` | Optional, when available |
| `started_at` / `completed_at` | Execution timestamps |
| `result_integrity_hash` | Hash of normalized result data |

Hidden chain-of-thought, private reasoning traces, credentials, and unnecessary model internals must not be stored.

### Finding schema

Each finding should contain:

- `finding_id`;
- `severity`: info / low / medium / high / critical;
- `category`: architecture / security / governance / correctness / testing / statistical / risk / execution / maintainability / scope / other;
- `title`;
- `summary`;
- `path` when applicable;
- `line_or_location` when applicable;
- `contract_or_policy_reference` when applicable;
- `blocking`: boolean;
- `recommended_action`.

A reviewer result may be `approved` only when there are no unresolved blocking findings.

## 6. Review-tier semantics

Review tiers are hierarchical:

- R1 satisfies R1 only.
- R2 satisfies R1 and R2.
- R3 satisfies R1, R2, and R3.

The required tier is determined by governance inputs, never by the reviewer model.

Architecture, ADRs, shared contracts, state machines, permissions, security controls, statistical authority, deterministic risk, approval/execution/CCXT, secrets, and dangerous production flags remain R3-class work unless a later approved policy changes that classification.

The model cannot downgrade the required tier.

## 7. Timeouts, retries, escalation, and blocked states

### Timeouts

Each provider adapter must expose deterministic timeout configuration. Timeout expiry is a failed attempt, not an approval.

### Retry policy

Default policy:

- one initial review execution;
- at most one automatic retry for a transient provider/transport failure;
- no automatic retry for architecture ambiguity, contradictory policy, scope ambiguity, or a substantive reviewer finding;
- no unbounded retry loop.

### Escalation

- R1 execution may escalate to R2 only through controller policy.
- R2 may escalate to R3 only through controller policy.
- The model may report uncertainty but cannot authorize its own escalation.
- R3 exhaustion or unresolved ambiguity transitions to `human-decision-required`.

## 8. AI-credit and cost guardrails

These controls are mandatory for development orchestration.

1. **Bounded context by default.** Never send the full Master Playbook or full repository unless a separately approved exception explicitly requires it.
2. **Deterministic checks first.** Run static validation, tests, linting, contract checks, path/scope checks, and security scanners before expensive AI review where applicable.
3. **Minimum sufficient tier.** Use the cheapest tier allowed by policy; never use premium solely for convenience.
4. **No premium boilerplate.** Formatting, boilerplate, routine docs, and simple tests must not default to premium.
5. **Bounded correction loop.** One implementation attempt plus a bounded number of correction attempts. Repeated premium cycles require explicit human authorization.
6. **Architecture ambiguity stops dispatch.** If unresolved architecture/provider/contract ambiguity caused the failure, transition to `human-decision-required` instead of sending another premium attempt.
7. **No expensive retry on unchanged evidence.** Reuse deterministic results and current-head artifacts that are still valid.
8. **Head-aware reuse.** Cached analysis may be reused only when it is explicitly bound to the same current head SHA and context-pack version.
9. **Usage observability.** Record provider/model, token/request counts, latency, and estimated/actual cost when available.
10. **Expensive-run human gate.** If estimated or observed usage exceeds configured thresholds, another premium rerun requires explicit approval by `AnjanaKavinda`.
11. **No cost-driven safety downgrade.** Cost never permits a lower-than-required review tier or capability tier.
12. **No credit burn to resolve governance uncertainty.** Governance/architecture uncertainty must be resolved as an architecture decision before coding-agent redispatch.

### Recommended configurable thresholds

The contract defines configuration keys without fixing provider-specific monetary values:

- `max_review_attempts_per_head`;
- `max_correction_attempts_per_pr`;
- `max_context_bytes_by_tier`;
- `max_tokens_by_tier` when measurable;
- `expensive_run_token_threshold`;
- `expensive_run_cost_threshold`;
- `provider_timeout_seconds`;
- `transient_retry_limit`.

Threshold values are environment/configuration decisions and must not be hard-coded into domain logic.

## 9. Provenance/attestation handoff

A successful reviewer result does not directly satisfy governed review.

The result must be passed to the trusted provenance/attestation layer implemented by Issue #209 / PR #210.

The handoff must bind at minimum:

- repository;
- PR number;
- linked issue;
- current head SHA;
- review execution id;
- reviewer identity/session;
- implementation session;
- required and actual review tier;
- disposition;
- provider execution reference when available;
- result integrity hash;
- trusted producer workflow/run identity;
- policy version;
- timestamp.

The attestation layer validates integrity and current-head binding. It does not invent reviewer findings or disposition.

## 10. Provider/model boundary and OD-0010

OD-0010 remains open.

This contract does not choose OpenAI, Anthropic, Google, GitHub Copilot, a local model, or any other provider/model.

A provider-specific adapter may be implemented only after an approved configuration/ADR authorizes the execution path required for that environment.

The domain contract must remain stable when providers are changed.

Provider-specific code must live behind the adapter boundary and must not leak provider-specific model semantics into governance contracts.

## 11. Failure and fail-closed rules

The review pipeline must block governed progression when any of the following occurs:

- current head cannot be verified;
- linked issue/canonical mapping cannot be resolved;
- required review tier cannot be determined;
- context pack is missing, stale, oversized, contradictory, or unsafe;
- provider adapter is unavailable or unauthorized;
- reviewer execution result cannot be integrity-validated;
- reviewer execution session equals implementation session;
- result head SHA differs from current PR head;
- required deterministic checks are absent or failed;
- attestation/provenance cannot be persisted or verified;
- required reviewer result is `changes-requested` or `blocked`;
- cost/attempt threshold requires human approval and none exists.

Failure must never be converted into implicit approval.

## 12. Human final review and merge

After all required deterministic checks, independent AI review, and provenance validation succeed:

1. the PR enters a human-review-ready state;
2. `AnjanaKavinda` performs the final human review;
3. `AnjanaKavinda` may request additional changes regardless of AI disposition;
4. `AnjanaKavinda` makes the final approval decision;
5. `AnjanaKavinda` manually merges or declines to merge.

No automation may perform the final merge.

## 13. UI and product-scope preservation

This contract changes only development orchestration.

It does not remove, reduce, postpone indefinitely, or supersede canonical Domain 11 — Frontend, Dashboard & Trader UX.

The planned product continues to require rich trader-facing visualization, including as applicable:

- multi-timeframe market charts;
- Technical / SMC / Wyckoff / Fibonacci overlays;
- market regime visualization;
- sentiment, on-chain, derivatives, event-risk, and alternative-data views;
- multi-agent analysis and disagreement visualization;
- evidence qualification and NO_TRADE explanations;
- signal, confidence, uncertainty, and validation views;
- deterministic risk and position-sizing panels;
- human editing/approval of entry, stop-loss, take-profit, leverage, amount, and related parameters with revalidation;
- portfolio, positions, orders, execution lifecycle, and reconciliation views;
- backtest, statistical-validation, calibration, drift, and agent-performance analytics;
- strategy versions, learning/experience, governance, audit, alerts, and notification views;
- responsive desktop-first trader UX.

Detailed UI architecture and implementation remain in their canonical product phase and must not be silently dropped.

## 14. Implementation readiness gate for Issue #211

Issue #211 may move from blocked to implementation-ready only after all of the following are true:

- this contract is approved and merged;
- the provenance/attestation foundation is merged;
- the provider/model execution boundary required for the target environment is approved without silently bypassing OD-0010;
- reviewer/session configuration strategy is defined;
- cost guardrail configuration is defined;
- no unresolved architecture ambiguity remains in the adapter boundary.

Issue #211 must remain blocked until those conditions are satisfied.

Canonical Issue 004 / GitHub Issue #6 remains blocked independently until all pilot prerequisites are satisfied and `AnjanaKavinda` explicitly authorizes pilot activation.

## Traceability

- GitHub Issue #212 — vendor-neutral reviewer execution contract and cost guardrails
- GitHub Issue #211 — actual independent AI reviewer execution adapter
- GitHub Issue #209 / PR #210 — trusted review provenance/attestation foundation
- `MODEL-ROUTING-GOVERNANCE-V1.1.md`
- ADR-0001 governed Copilot development orchestration
- OD-0010 LLM provider/model routing policy
- Canonical Domain 11 — Frontend, Dashboard & Trader UX
