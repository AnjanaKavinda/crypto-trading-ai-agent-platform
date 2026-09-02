# Governed automated Copilot development orchestration

## Status and scope

This is the proposed V1 orchestration contract for Issue #193 and is governed
by proposed [ADR-0001](../../adr/ADR-0001-governed-copilot-development-orchestration.md).
It applies only after that ADR is accepted and a separately reviewed
implementation is merged.

It governs GitHub Copilot development work, not runtime trading agents. It
does not implement a controller, GitHub Actions workflow, script, auto-merge,
runtime contract, or trading capability. `dev` is the base branch for normal
backlog work. `main` remains stable and reviewed.

## V1 authority and boundaries

The human repository owner alone may approve and merge a PR. No automation,
Copilot agent, reviewer agent, label, check, or state transition may merge to
`dev` or `main`, approve a merge, or override a human decision.

The future implementation must enforce this boundary with GitHub branch
protections or rulesets: `dev` and `main` require an authenticated human-owner
approval and human merge action. Controller and Copilot identities must not
approve or merge PRs, bypass protections, alter rulesets, or possess
merge-capable credentials.

The implementation must use a least-privilege controller identity whose
permissions are limited to documented issue, label, assignment, PR-status,
check-status, and audit operations. It must not have administration, ruleset,
branch-protection bypass, workflow-editing, repository-contents write,
pull-request approval, or merge permission. The controller must verify that a
dispatch-triggering event actor is an authorized human owner or approved
automation identity before it processes the event.

The controller may validate issue metadata, resolve an agent, construct a
prompt, assign Copilot, observe PR/check/review status, and transition the
workflow state. It may not alter shared contracts, risk limits, leverage or
position sizing, approval/authentication, execution/reconciliation, strategy
promotion, production model/prompt behavior, learning-production promotion,
or live-trading enablement.

## Agent-label mapping

Exactly one of these labels is required for automatic dispatch:

| Label | Resolved agent |
|---|---|
| `agent:architect` | Platform Architect |
| `agent:backend-foundation` | Backend/Foundation Engineer |
| `agent:trading-intelligence` | Trading Intelligence Engineer |
| `agent:qa-security-review` | QA/Security Reviewer |

Zero, multiple, unknown, or contradictory agent labels are a blocked state;
the controller must not select an agent heuristically.

## Eligibility and dependency gates

Before assignment, the controller deterministically records and verifies all
of the following:

1. The issue is open, in scope, and has exactly one valid agent label applied
   by an authorized human owner or approved automation identity. Unauthorized
   issue-body or label changes block dispatch and require human review.
2. The issue body has a complete objective, acceptance criteria, boundaries,
   relevant authoritative references, and an explicit base branch of `dev`.
3. The canonical backlog number is resolved from the issue body and/or the
   catalog mapping—not from the GitHub issue number. The mapping evidence and
   resolved canonical number are recorded. If they disagree or are absent,
   dispatch is blocked.
4. Every declared dependency is closed/accepted as required by the catalog or
   issue body. A missing, ambiguous, or nonterminal dependency blocks
   dispatch.
5. The issue does not overlap an active issue that owns the same shared
   contract, domain entity, state machine, architectural boundary, or
   `.github/**` artifact.
6. No material conflict exists among the issue, applicable repository
   instructions, approved ADRs, contracts, cross-cutting artifacts, and
   Playbook sources. OD-0024 remains unresolved and must be escalated when
   its precedence ambiguity is material.
7. The target is not prohibited by the current phase, including a request to
   enable live trading, self-merge, bypass human approval, or bypass
   deterministic risk.

The V1 pilot is canonical Backlog Issue 004, mapped to GitHub issue
`AnjanaKavinda/crypto-trading-ai-agent-platform#6`. It is reserved for the
first dispatch only after ADR-0001 is accepted and the automation
implementation has merged; this document does not dispatch or begin it.

## Launch-prompt construction

The controller constructs a reproducible prompt from immutable references,
rather than an agent-selected summary:

1. GitHub issue identifier, title, body, canonical backlog-number resolution
   evidence, labels, dependencies, and target base branch, after mandatory
   secret detection and safe handling.
2. Applicable repository instructions, path-specific instructions, approved
   ADRs, shared contracts, cross-cutting artifacts, and relevant Playbook
   sections.
3. The resolved agent role, permitted editable paths, and required review/test
   obligations.
4. A safety wrapper that prohibits secrets, live-trading enablement,
   LLM-to-exchange execution, approval/risk bypasses, fabricated evidence,
   self-merge, and unrelated changes; it requires fail-closed escalation for
   a material source conflict.
5. A request for a PR that identifies scope, traceability, safety impact,
   validation, risks, deferred work, and the human final merge gate.

Before prompt rendering, the controller must detect suspected secrets in issue
content and any other mutable input. It must not copy suspected secrets into a
prompt, audit record, check annotation, or log; it must block dispatch and
escalate through a restricted human incident process using safe references.
The controller records content hashes or immutable references for every safe
prompt input, the rendered prompt, controller version, dispatch timestamp, and
Copilot assignment identifier.

All mutable or external content—issue text and labels, PR descriptions,
comments, review findings, check output, and correction instructions—is
untrusted data. The controller must delimit it as non-authoritative scope
input, reject any attempt to override repository instructions or the safety
wrapper, and block/escalate ambiguous or malicious content. It must apply the
same secret-handling process before using any such content in a correction
prompt.

## State machine

| State | Entry condition | Allowed transition | Required outcome |
|---|---|---|---|
| `workflow:ready` | All eligibility gates pass; no active dispatch | `agent-running`, `blocked`, `human-decision-required` | Dispatch only after durable audit recording. |
| `workflow:agent-running` | Copilot assignment is confirmed | `review`, `changes-requested`, `blocked`, `human-decision-required` | Detect the linked PR and monitor bounded execution. |
| `workflow:review` | PR exists and deterministic checks have completed successfully | `changes-requested`, `ready-to-merge`, `blocked`, `human-decision-required` | Require independent QA/Security review where applicable. |
| `workflow:changes-requested` | A deterministic check or authorized independent review requests correction | `agent-running`, `blocked`, `human-decision-required` | Start only a bounded, deduplicated correction dispatch. |
| `workflow:ready-to-merge` | Required checks and independent review pass; scope and audit evidence are complete | `complete`, `changes-requested`, `blocked`, `human-decision-required` | Await a human decision; never merge automatically. |
| `workflow:blocked` | A fail-closed gate fails or state is unsafe/unknown | `human-decision-required` | Preserve evidence; make no automatic forward transition. |
| `workflow:human-decision-required` | Human judgment is required, including high risk or unresolved ambiguity | `ready`, `changes-requested`, `complete`, `blocked` | Human records the disposition before progression. |
| `workflow:complete` | Human owner merges, closes, cancels, or otherwise records final disposition | none | Terminal, immutable final record. |

All transitions not listed are illegal and must be rejected and audited.
`workflow:ready-to-merge` is not merge authorization.

## PR, checks, review, and correction behavior

The controller identifies the PR through the recorded dispatch/issue
relationship and verifies its base branch is `dev`. Missing, multiple,
unlinked, or unexpected-base PRs block progression. It verifies required
deterministic checks and records their names, runs, conclusions, and commit
SHA. A failed, missing, cancelled, stale, or unknown required check blocks
progression.

An independent reviewer must be resolved from the appropriate review
requirements. The implementing agent cannot self-approve or self-merge.
Review findings are classified as blocker, major, minor, or informational.
Blockers and unresolved majors transition to `workflow:changes-requested` or
`workflow:human-decision-required`; they cannot reach
`workflow:ready-to-merge`.

Correction dispatches must reference the same issue, PR, review findings, and
current commit SHA. They are idempotent, bounded by a configured maximum
attempt count, and may not silently expand issue scope. Exhaustion, an
unresolved review disagreement, a duplicate/uncertain dispatch, or an
unexpected PR state transitions to `workflow:blocked` and then
`workflow:human-decision-required`.

## High-risk human-review categories

The following always require explicit human review and cannot be automatically
marked ready to merge solely by checks or agent review:

- shared contracts and contract-versioning/migration;
- risk, leverage, position sizing, liquidation, and portfolio limits;
- approval, authentication, and authorization;
- CCXT/exchange integration, order construction, execution, retries,
  idempotency, and reconciliation;
- strategy promotion;
- production model or prompt changes;
- learning-driven production promotion;
- live-trading enablement, secrets management, or dangerous production flags.

## Audit and provenance

Every dispatch and transition requires an append-only audit record before its
effect. At minimum, record:

- workflow-run, transition, correlation, causation, issue, canonical-backlog,
  dispatch, assignment, PR, review, and check identifiers;
- prior and new state, timestamp, actor/controller identity and version,
  reason, decision inputs, and immutable evidence references;
- canonical-number mapping and dependency evaluation;
- resolved agent and label set;
- prompt-input references/hashes, rendered-prompt hash, applicable-instruction
  references, safety-wrapper version, and target branch;
- PR head/base SHA, check outcomes, reviewer identity/role, review findings,
  correction attempt number, and final human disposition.

Audit-write failure, missing provenance, or an unverifiable correlation blocks
dispatch and progression.

## Fail-closed escalation

The controller must transition to `workflow:blocked` and request human
resolution for ambiguous dependencies, missing agent mappings, source
conflicts, failed or unknown checks, unexpected PR state, unavailable audit
storage, duplicate/unknown dispatch state, or any condition for which it
cannot prove safety. It must not skip checks, infer acceptance, retry without
a bound, reuse stale approval-like state, or advance based on labels alone.

Human resolution records the decision and evidence. Only then may the
controller transition through an explicitly allowed state; it still may not
merge.

## Follow-up implementation scope

A follow-up automation issue may implement this controller and its
least-privilege GitHub integration, durable audit storage, state persistence,
idempotency, check/review adapters, labels, test coverage, and operational
observability. It must not implement auto-merge, modify `main`, create a
`develop` branch, begin Issue 004 before the stated pilot conditions, or
introduce runtime/application/trading behavior.
