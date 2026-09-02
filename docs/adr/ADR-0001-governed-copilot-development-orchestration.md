# ADR-0001: Governed Copilot development orchestration

## Metadata

| Field | Value |
|---|---|
| Status | Proposed |
| Date | 2026-09-02 |
| Decision owner | Platform Architect |
| Human approver | Pending |
| GitHub issue / PR | Issue #193 / Pending |
| Open decision ID | — |
| Related ADRs | — |
| Supersedes / superseded by | — |

## Context

The repository needs a controlled GitHub Copilot development workflow that can
dispatch eligible issues and coordinate review without transferring final merge
authority from the human repository owner. This decision concerns development
automation only. It is distinct from the platform's runtime multi-agent
orchestration and neither changes runtime contracts nor authorizes trading,
exchange access, credentials, or live trading.

The intended V1 control path is:

```text
Eligibility and dependency validation → agent resolution → Copilot assignment
→ Copilot execution → PR creation → deterministic checks → independent review
and bounded correction → READY_FOR_HUMAN_MERGE → human approval and merge
```

Normal backlog work uses `dev` as its base branch. The human architecture owner
confirmed that `dev`, not the stale `develop` reference, is the integration
branch for this repository.

## Alternatives

### Option A — Manual issue assignment and review only

Benefits:

- No automation-controller implementation or controller credentials.
- Human review remains explicit at every step.

Costs, risks, and constraints:

- Repetitive eligibility, routing, and provenance checks are performed
  inconsistently.
- Does not provide a reliable, auditable control plane for supervised Copilot
  dispatch.

### Option B — Governed automated dispatch with a mandatory human merge gate

Benefits:

- Makes issue eligibility, agent routing, checks, review, and escalation
  explicit, auditable, and repeatable.
- Preserves independent review and human final merge authority.
- Allows fail-closed handling of unknown or unsafe automation state.

Costs, risks, and constraints:

- Requires a later implementation issue to provide a least-privilege
  controller, durable audit records, and deterministic validation.
- Incorrect controller behavior must block progression rather than infer a
  safe state.

### Option C — Fully autonomous dispatch, approval, and merge

Benefits:

- Minimizes human workflow steps.

Costs, risks, and constraints:

- Violates the repository's mandatory human authority and no-self-merge rules.
- Creates an unacceptable path for an automation error to merge unsafe or
  incompatible changes.

## Decision

Propose Option B: implement a future, supervised development-orchestration
controller that follows the contract in
[`../copilot-team/03-github-workflow/AUTOMATED-AGENT-ORCHESTRATION.md`](../copilot-team/03-github-workflow/AUTOMATED-AGENT-ORCHESTRATION.md).

V1 may automatically validate, dispatch, observe, request independent review,
and manage a bounded correction loop. It must never approve or merge a PR into
`dev` or `main`. Only the human repository owner may make the final merge
decision. This ADR is Proposed and is not implementation authority until that
owner accepts it.

## Reasoning

The proposed model preserves the existing four-agent handoff and merge-gate
controls while making automation state observable and fail closed. It does not
alter the authority of the Master Playbook, cross-cutting controls, or existing
shared contracts. It also does not resolve OD-0024; a material source conflict
still blocks dispatch and requires human architecture review.

## Consequences

- A follow-up implementation issue must implement the documented controller
  contract, labels, state persistence, audit events, checks, review integration,
  and least-privilege permissions.
- The controller must use `dev` as the normal base branch and must not create
  or use `develop`.
- The controller must never auto-merge or bypass required independent review.
- Backlog Issue 004, GitHub `AnjanaKavinda/crypto-trading-ai-agent-platform#6`,
  is reserved as the first V1 pilot after this ADR is accepted and the
  controller implementation is merged. It is not started by this issue.
- No runtime trading-platform contract, event, mode, capability, or open
  decision is changed.

## Contract and traceability impact

| Area | References and impact |
|---|---|
| Playbook requirements | Chats 1, 2, 10, and 12: supervision, explicit boundaries, safety, auditability, and implementation governance |
| Cross-cutting artifacts | `03-agent-responsibility-matrix.md`, `04-agent-handoff-matrix.md`, `05-permission-matrix.md`, `08-state-machine-registry.md`, `10-audit-traceability-matrix.md`, `11-failure-recovery-matrix.md`, `13-requirements-traceability.md`, and `15-definition-of-done.md` |
| Contracts / events | None changed. The implementation must use a separately governed development-automation audit schema; it must not redefine runtime contracts or events. |
| Requirements traceability | Issue #193; the orchestration contract records state, dispatch, review, and pilot requirements. |
| Versioning / migration | No migration. The contract becomes implementable only after this ADR is accepted. |

## Safety, security, and failure behavior

Development automation is untrusted until its deterministic eligibility,
authorization, and state checks pass. Ambiguous dependencies, missing or
conflicting agent mappings, material source conflicts, failed checks, unknown
PR/review state, and unavailable audit persistence block dispatch or
progression and escalate to the human owner. Retries are bounded and must not
duplicate an active dispatch or PR.

The controller must use least privilege and must not hold, expose, or generate
exchange credentials. It cannot create live orders, alter runtime risk,
approval, execution, reconciliation, strategy-promotion, model/prompt
production, learning-production, or live-trading decisions. The existing
invariants remain unchanged: no approval means no live execution, risk remains
deterministic, LLM output is untrusted until validated, and `NO_TRADE` remains
valid.

## Approval record

Pending human repository-owner review. On approval or rejection, update this
record and the ADR register without rewriting the decision history.
