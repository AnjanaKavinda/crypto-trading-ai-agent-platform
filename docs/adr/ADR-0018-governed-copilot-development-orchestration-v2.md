# ADR-0018: Governed Copilot development orchestration V2

## Metadata

| Field | Value |
|---|---|
| Status | Accepted |
| Date | 2026-11-05 |
| Decision owner | Platform Architect |
| Human approver | AnjanaKavinda (human repository owner) |
| Scope | Development automation only |
| Supersedes | Pilot-only dispatch restrictions in ADR-0001/V1.1 where explicitly amended below |

## Context

ADR-0001 established a supervised Copilot development flow with deterministic
eligibility, custom agent routing, independent review, bounded correction, and a
mandatory human merge gate. The implementation was intentionally pilot-scoped.

The pilot controls now create avoidable development latency:

- governed dispatch is restricted by a per-issue pilot allowlist;
- approved profile-scoped completion cannot be represented when a broader
  full-platform GitHub issue intentionally remains open;
- implementation agents stop too readily on ordinary implementation choices;
- some path instructions still target obsolete repository paths;
- architecture and correction review can be reopened repeatedly after a decision
  has already been frozen.

The trading/runtime authority model is unchanged. This ADR governs software
development orchestration only.

## Decision

Adopt Governed Copilot Development Orchestration V2.

The normal path is:

```text
Architecture/controller preflight
→ exact Execution Packet
→ deterministic custom-agent routing
→ human-triggered Copilot assignment
→ bounded implementation
→ Product CI + Governance CI
→ independent exact-head review
→ bounded same-branch correction
→ controller final review
→ human owner merge
```

### 1. Execution Packet

Every governed implementation dispatch requires one current owner/controller
Execution Packet posted on the issue before Copilot assignment.

The packet binds at minimum:

- GitHub issue number;
- `dev` base branch;
- exact base SHA;
- scope/profile;
- architecture state (`FROZEN` for implementation);
- primary custom agent;
- explicitly satisfied profile-scoped dependencies, when any;
- implementation boundaries;
- stop conditions.

A packet is implementation authority only for its exact issue/base/scope. It is
not runtime trading authority.

A stale packet whose base SHA is no longer an ancestor/current approved base
must be refreshed before dispatch.

### 2. Profile-scoped dependency satisfaction

The controller may mark a canonical dependency satisfied in the Execution
Packet only when an approved issue/ADR/merged checkpoint explicitly records
profile-scoped completion while preserving the broader issue as open.

The dispatcher must never infer this from an open issue, labels, or missing
fields.

Absent explicit packet evidence, the normal closed-dependency rule remains.

### 3. Pilot graduation

The per-issue `GOVERNED_PILOT_ISSUES` allowlist is retired as a dispatch and
review authorization mechanism.

A global fail-closed automation switch remains mandatory. V2 uses
`GOVERNED_AUTOMATION_ENABLED`; the existing `GOVERNED_PILOT_ENABLED` value may
be accepted temporarily as a compatibility alias during migration.

Actor allowlists, branch protection verification, deterministic routing,
review tiers, exact-head provenance, and duplicate-dispatch protection remain.

### 4. Architecture authority

The controller/Platform Architect freezes architecture before implementation.

Implementation agents consume frozen architecture and resolve ordinary local
implementation details themselves.

They stop only for:

- a concrete contradiction with the frozen issue/ADR/contract;
- a required destructive migration;
- an expansion of safety, credential, approval, execution, or live-trading
  authority;
- missing information that cannot be truthfully derived.

They must not reopen accepted architecture merely because another reasonable
implementation exists.

### 5. Existing-implementation classification

Before editing, the implementer records exactly one:

- `ALREADY_COMPLETE`
- `PARTIALLY_COMPLETE`
- `MISSING`
- `BLOCKED`

Only genuinely missing issue scope is implemented.

### 6. Review and correction discipline

First review is limited to:

- issue acceptance criteria;
- frozen architecture/contracts;
- compatibility;
- security/safety;
- concrete regressions.

After a correction, review is limited to the correction plus exact-head
regression unless a new concrete defect is demonstrated.

A new head SHA invalidates prior readiness.

### 7. Human authority

Copilot/custom agents may implement, test, open/update PRs, and correct concrete
review/CI defects.

They may not:

- merge or enable auto-merge;
- approve their own implementation;
- expand issue scope;
- silently alter shared architecture/contracts;
- change trading runtime authority.

The human repository owner remains the final merge authority.

## Consequences

- The custom-agent model remains the normal implementation mechanism.
- Controller effort shifts toward architecture, dependency preflight, and final
  review instead of manual file editing.
- Independent review remains mandatory according to the configured review tier.
- Product CI and Governance CI remain required checks.
- `governance-gate` remains diagnostic unless repository rulesets explicitly
  make it required.
- Existing V1/V1.1 provenance remains valid; historical dispatch records are not
  rewritten.
- This ADR does not authorize paper, testnet, live trading, credentials, order
  submission, risk approval, or execution.

## Approval record

Accepted by AnjanaKavinda on 2026-11-05 during the Trading Agent development
workflow. The approval authorizes this bounded development-automation upgrade
and the corresponding repository instruction/controller changes. It does not
authorize automatic merge or any trading/runtime capability.
