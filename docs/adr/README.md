# Architecture Decision Records

This directory is the canonical register for Architecture Decision Records (ADRs).
ADRs record approved architectural choices, material architecture changes, and the
disposition of alternatives. They do not override an explicit Master Playbook
requirement or resolve an authoritative-source conflict. An ADR must not silently
contradict an approved contract or cross-cutting artifact.

## Register

| ID | Title | Status | Date | Owner / approver | Open decision | Contracts | Supersedes | Superseded by |
|---|---|---|---|---|---|---|---|---|
| ADR-0001 | [Governed Copilot development orchestration](ADR-0001-governed-copilot-development-orchestration.md) | Proposed | 2026-09-02 | Platform Architect / Pending | — | None | — | — |

## Creating an ADR

1. Confirm the decision is not already explicitly required by the Master Playbook.
2. For an open decision, link the record in
   [`../cross-cutting/14-open-decisions.md`](../cross-cutting/14-open-decisions.md).
3. Copy [`ADR-TEMPLATE.md`](ADR-TEMPLATE.md) to
   `ADR-NNNN-short-kebab-case.md`, using the next unused sequential number.
   `ADR-0000` is reserved for the template and is not a decision record.
4. Keep the ADR `Proposed` until the human repository owner approves it.
5. Add the proposed or accepted record to this register and update linked
   open-decision, issue, contract, and traceability records where applicable.

Each ADR must link its GitHub issue/PR, relevant Playbook requirements,
affected contracts and events, and any related traceability records. Contract
changes also require the applicable impact analysis, versioning decision, and
migration plan; an ADR alone does not authorize an incompatible contract change.

## Status lifecycle

The only ADR statuses are:

```text
Proposed → Accepted
         ↘ Rejected
Accepted → Superseded
```

- **Proposed:** documented for review; it is not implementation authority.
- **Accepted:** approved by the human repository owner and eligible to guide
  implementation. It does not override an explicit Master Playbook requirement.
- **Rejected:** not approved; it must not be implemented as an architecture
  decision.
- **Superseded:** an accepted ADR replaced by a later accepted ADR. Both records
  must link to one another; historical rationale remains immutable.

`Deprecated` is not an ADR status. When an accepted architecture is deprecated,
create and accept a replacement ADR, mark the prior ADR `Superseded`, and record
the migration and compatibility consequences in both records.

## Decision ownership and safety

The Platform Architect prepares ADRs and maintains this register. The human
repository owner is the final authority for acceptance, rejection, and
architecture changes. High-risk decisions remain subject to explicit human
review, including risk, approval, authorization, secrets, exchange integration,
execution, reconciliation, strategy promotion, and live-trading configuration.

If an implementation depends on a missing, proposed, rejected, superseded, or
materially ambiguous ADR, it must stop and seek human architecture review.
Likewise, an unresolved material conflict among an ADR, a contract, a
cross-cutting artifact, the Playbook, or governance instructions must be
reported and require human architecture review. While OD-0024 remains unresolved,
this foundation does not declare ADRs or contracts/cross-cutting artifacts to be
the higher authority. This is governance failure behavior; it introduces no
runtime execution path.

## When an ADR is required

Create an ADR when a material architecture choice, boundary, technology
selection, contract-versioning approach, migration, or exception to an
established implementation approach must be decided. Do not create an ADR merely
to restate an already explicit Master Playbook requirement; implementation may
follow that requirement while preserving its traceability.

Open decisions remain unresolved until a decision is necessary and receives the
required ADR and human review. This register does not select technologies,
providers, operating modes, or any trading behavior.

## Scope and deferred governance

This foundation creates no decision-specific ADR and changes no contracts,
runtime behavior, credentials, risk controls, approval controls, or live-trading
configuration. The recorded source-precedence conflict and stale historical path
reference remain deferred for separate human governance resolution.
