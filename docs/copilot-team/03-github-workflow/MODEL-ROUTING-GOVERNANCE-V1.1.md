# Model Routing & AI Usage Governance V1.1

## Status and scope

This policy defines the development-orchestration routing control for
AI-assisted repository work. It is vendor and model-name agnostic. It does not
select a provider, close OD-0010, or change runtime trading-agent orchestration.
Runtime trading, deterministic risk, approval, execution, exchange, and
learning-governance controls remain authoritative and unchanged.

Cost optimization is subordinate to correctness, security, statistical
integrity, deterministic risk, human approval, and auditability.

The policy does not activate the governed pilot. `GOVERNED_PILOT_ENABLED` must
remain unset/false, and canonical Backlog Issue 004
(`AnjanaKavinda/crypto-trading-ai-agent-platform#6`) must not be dispatched by
this policy.

## 1. Bounded Issue Context Pack

The orchestrator constructs a versioned context pack for the active issue. The
pack contains only task-required information and references; it must not include
the full Playbook by default.

| Field | Required content |
|---|---|
| `context_pack_id` | Unique immutable identifier |
| `context_pack_version` | Schema/policy version, currently `1.1` |
| `issue` | Canonical issue identifier, GitHub issue/PR mapping when applicable, title, objective, and acceptance criteria |
| `dependencies` | Declared dependencies and their verified status |
| `references` | Relevant Playbook sections, contracts, ADRs, cross-cutting controls, and traceability entries |
| `scope` | Affected paths, allowed paths, forbidden paths, and explicitly deferred work |
| `implementation_context` | Minimal current-state summary, relevant file excerpts or immutable references, branch/base, and applicable tests |
| `governance_inputs` | Phase, issue type, agent role, risk labels, architecture/contract impact, security impact, trading/risk/statistical impact, and execution/approval/CCXT impact |
| `safety_invariants` | Applicable fail-closed rules, no-live-trading state, human-merge requirement, and other non-negotiable constraints |
| `integrity` | Source hashes/references, creation time, creator/controller version, and redaction result |

Context-pack construction must:

1. Resolve the canonical issue mapping and dependencies before routing.
2. Include only relevant sections and bounded excerpts; use immutable references
   for larger artifacts.
3. Treat issue text, comments, labels, PR text, and external content as
   untrusted data. They cannot override repository instructions or safety
   invariants.
4. Run secret detection before content is retained, rendered, or forwarded.
   Suspected secrets block processing and are not copied into prompts or audit
   records.
5. Preserve the pack identifier/version and input hashes for reproducibility.
6. Fail closed when scope, authority, source integrity, or required context is
   missing or contradictory.

## 2. Capability tiers

Routing selects a capability tier, not a named vendor or model:

| Tier | Capability | Permitted default use |
|---|---|---|
| `economical-fast` | Fast, lower-cost general assistance | Documentation, formatting, boilerplate, simple tests, and other low-risk bounded work |
| `strong-coding-reasoning` | Strong implementation and analytical reasoning | Normal backend work, ordinary integration, trading-intelligence analysis, and statistical work that is not independently classified as high risk |
| `premium-strongest-available` | Strongest approved capability with the highest scrutiny | Architecture, ADRs, shared contracts, security-sensitive work, deterministic risk, leverage, sizing, approval, execution, CCXT, and other high-impact changes |

The selected tier never grants authority. AI output remains untrusted and
requires the applicable deterministic checks, independent review, and human
merge decision.

## 3. Deterministic routing inputs and decision table

Routing evaluates all of the following inputs: agent role, phase, risk label,
issue type, affected paths, architecture/contract impact, security impact,
trading/risk/statistical impact, execution/approval/CCXT impact, and blocked or
ambiguous status.

| Classification | Minimum implementation tier | Review requirement |
|---|---|---|
| Documentation, formatting, boilerplate, simple tests; no sensitive paths or material behavior | `economical-fast` | Independent economical or strong review |
| Normal backend or foundation implementation without high-risk boundaries | `strong-coding-reasoning` | Independent strong review |
| Trading intelligence or statistical validation | `strong-coding-reasoning`; use premium when materially complex or uncertain | Independent strong review; premium review when high risk or escalated |
| Architecture, ADRs, shared contracts, state machines, permissions, or governance boundaries | `premium-strongest-available` | Independent premium architect review and human decision where required |
| Deterministic risk, leverage, position sizing, liquidation, portfolio limits, or statistical authority | `premium-strongest-available` | Independent premium QA/security review plus human review |
| Approval, authorization, execution, reconciliation, exchange/CCXT, retries, or idempotency | `premium-strongest-available` | Independent premium architecture and QA/security review plus human review |
| Secrets, security controls, prompt-injection defenses, or dangerous production flags | `premium-strongest-available` | Independent premium security review plus human review |

The highest applicable classification wins. A cheaper tier must not be selected
to reduce cost when any higher-risk input applies.

## 4. Escalation and fail-closed policy

| Condition | Required transition | Automatic action |
|---|---|---|
| Economical tier is blocked, materially uncertain, or cannot complete the bounded task | `economical-fast` → `strong-coding-reasoning` | Preserve the original audit record and context-pack version |
| Strong tier encounters architecture, security, risk, statistical-authority, approval, execution, or CCXT-critical work | `strong-coding-reasoning` → `premium-strongest-available` | Rebuild/extend the context pack only with newly required bounded references |
| Any required routing input is missing, contradictory, stale, unauthorized, or unclassifiable | `human-decision-required` | Do not select a cheaper tier or dispatch |
| Material source conflict, unresolved scope, unsafe content, unavailable audit persistence, or duplicate/uncertain dispatch | `human-decision-required` | Block progression and preserve safe evidence |
| Escalation limit, retry limit, or review disagreement is exhausted | `human-decision-required` | No automatic forward transition |

An agent or model may report uncertainty, but may not self-escalate into
additional authority, waive review, alter scope, or activate a capability.
Human disposition is required before a blocked state can progress.

## 5. AI-assisted task usage and audit metadata

Each routing, assignment, escalation, retry, review, and final disposition is
recorded in an append-only development-orchestration audit record. The minimum
logical schema is:

| Field | Requirement |
|---|---|
| `usage_event_id` | Unique event identifier |
| `issue_id` / `pr_id` | Canonical issue and related PR, when present |
| `workflow_run_id` / `dispatch_id` | Correlation and dispatch identifiers |
| `agent_role` | Resolved development-agent role and label |
| `capability_tier` | Selected tier |
| `routing_reason` | Deterministic inputs and winning classification |
| `risk_classification` | Risk labels and high-risk dimensions |
| `context_pack_id` / `context_pack_version` | Exact bounded input identity |
| `controller_policy_version` | Routing-policy version |
| `retry_count` / `escalation_count` | Bounded attempts and tier transitions |
| `review_tier` / `reviewer_role` | Required and completed independent review |
| `outcome` | Completed, blocked, escalated, human-decision-required, or rejected |
| `timestamps` | Creation, dispatch, completion, review, and disposition times |
| `integrity_refs` | Input/output hashes or immutable references, redaction result, and relevant commit/PR SHA |

Provider/model names, versions, token counts, latency, and cost may be recorded
when available and approved, but are not required to define architecture-level
routing. Hidden chain-of-thought, private reasoning traces, credentials, and
unnecessary sensitive model internals must not be stored.

Audit-write failure blocks dispatch or progression. Missing provenance cannot be
repaired by estimating or fabricating metadata.

## 6. Review-tier policy

Every Copilot-generated PR requires an independent review and a human final
merge decision. Reviewers must not be the implementing agent/session or
controller, and approval is invalidated when the PR head changes.

| Review tier | Applies to | Required review |
|---|---|---|
| `R1-normal` | Low-risk, bounded documentation, formatting, boilerplate, or simple tests | Independent economical or strong review; deterministic checks |
| `R2-engineering` | Normal implementation, backend, analytical, or validation work | Independent strong review; relevant tests and contract checks |
| `R3-governed-high-risk` | Architecture, contracts, security, statistical authority, deterministic risk, approval, execution, CCXT, reconciliation, secrets, or dangerous flags | Independent premium review by the applicable architect and/or QA/security role, deterministic checks, and explicit human review |

R3 review does not authorize live trading, change deterministic authority,
replace human approval, or permit auto-merge. The human repository owner remains
the final merge authority for every tier.

## 7. Implementation handoff

A later Backend/Foundation issue may implement this policy only after separate
scope approval. It must provide:

- deterministic extraction and validation of routing inputs and labels;
- a versioned bounded context-pack builder with secret detection, redaction,
  hashes, relevant-reference selection, and size/retention controls;
- capability-tier selection and the escalation state machine above;
- append-only usage/audit persistence with idempotency and correlation;
- review-tier resolution and current-head review enforcement;
- human-decision-required states for ambiguity, conflicts, and unavailable
  audit/protection evidence;
- tests for every decision-table row, escalation path, fail-closed condition,
  redaction path, duplicate dispatch, and review invalidation;
- no provider/model selection that resolves OD-0010 without an approved ADR;
- no pilot dispatch, auto-merge, live-trading enablement, direct
  LLM-to-exchange path, or production self-modification.

The implementation must integrate with the existing governed orchestration
contract and ADR-0001 rather than create a competing controller or runtime
contract. Any architectural or shared-contract change requires the established
impact analysis, review, versioning, and human-approval process.

## Traceability

- Master Playbook: Chats 3, 10, 12, and 13
- Existing orchestration contract:
  [`AUTOMATED-AGENT-ORCHESTRATION.md`](./AUTOMATED-AGENT-ORCHESTRATION.md)
- Accepted decision:
  [`ADR-0001-governed-copilot-development-orchestration.md`](../../../docs/adr/ADR-0001-governed-copilot-development-orchestration.md)
- Open provider/model decision:
  [`docs/cross-cutting/14-open-decisions.md`](../../../docs/cross-cutting/14-open-decisions.md)
- Audit requirements:
  [`docs/cross-cutting/10-audit-traceability-matrix.md`](../../../docs/cross-cutting/10-audit-traceability-matrix.md)
