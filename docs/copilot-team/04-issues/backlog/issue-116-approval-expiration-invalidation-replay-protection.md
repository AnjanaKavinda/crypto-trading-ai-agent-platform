# Issue 116 — Approval expiration/invalidation/replay protection

## Phase
09 Approval/Execution

## Primary agent
Backend/Foundation Agent

## Playbook reference
Chat 9

## Objective
Prevent stale/replayed approval.

## Dependencies
101-112

## Required reading
- `.github/copilot-instructions.md`
- `AGENTS.md`
- relevant `docs/playbook/**`
- relevant `docs/cross-cutting/**` / approved contracts and ADRs

## Scope
- Inspect existing implementation first.
- Implement/document only this issue's bounded responsibility.
- Reuse approved contracts and existing working components.
- Add/update appropriate tests or validation evidence.
- Update documentation/traceability where necessary.

## Out of scope
- Unrelated refactoring.
- Silent architecture or shared-contract changes.
- Live trading unless this issue explicitly concerns a later approved readiness decision.
- Real credentials/secrets.
- Fabricated market/performance evidence.

## Acceptance criteria
- [ ] Objective is fully satisfied.
- [ ] Relevant playbook boundaries are preserved.
- [ ] Approved contracts are used or a change proposal is raised.
- [ ] Tests/validation appropriate to the change exist and pass.
- [ ] Security/safety impact is documented.
- [ ] Failure behavior is defined for critical paths.
- [ ] Documentation/ADR/version records are updated where required.
- [ ] No unrelated changes or secrets are introduced.
- [ ] PR is ready for independent QA/human review.

## Safety invariants
No approval = no live execution. Risk and critical calculations remain deterministic. AI/LLM output is untrusted until validated. NO_TRADE is valid. Learning cannot directly change production execution/risk.
