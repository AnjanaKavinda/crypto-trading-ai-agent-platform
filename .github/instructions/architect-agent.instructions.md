---
applyTo: "docs/**,.github/**,AGENTS.md,README.md"
---

# Architect Agent Path Instructions

These instructions apply when Copilot modifies architecture, governance, documentation, repository instructions, or agent configuration.

## Authoritative sources

Before modifying files in this scope, read:

- `.github/copilot-instructions.md`
- `AGENTS.md`
- relevant `docs/playbook/**` sections
- relevant approved ADRs
- relevant approved contracts

The Master Playbook v2.2 is authoritative.

If these sources conflict:

STOP.

Report the conflict.

Do not silently choose an interpretation.

## Responsibilities

When modifying this scope, preserve:

- architecture consistency
- 13-chat structure
- domain boundaries
- service boundaries
- agent boundaries
- AI vs deterministic separation
- contract governance
- architecture traceability
- ADR discipline
- implementation sequencing
- feature coverage

## Architecture change rule

Do not silently change architecture.

If an architectural change is required:

Change Proposal
→ Impact Analysis
→ ADR
→ Human Review
→ Approved Change
→ Implementation

## Contract rule

Do not silently redefine shared contracts.

Architecture documentation may govern shared contracts, but production contract semantics must not be changed casually.

Breaking changes require:

- impact analysis
- versioning decision
- migration strategy
- architecture review
- human approval where required

## Safety rules

Never:

- create Chat 14
- collapse the platform into a basic trading bot
- bypass human approval
- weaken deterministic risk
- introduce LLM-to-exchange execution
- introduce secrets
- invent performance statistics
- silently remove playbook functionality

## Documentation rule

Documentation changes must preserve traceability between:

Requirement
→ Architecture
→ Contract
→ Implementation
→ Test

## Pull request requirement

Every relevant PR must state:

1. Issue number
2. Objective
3. What changed
4. Why it changed
5. Relevant playbook sections
6. Contracts affected
7. ADRs affected
8. Files changed
9. Tests or validation performed
10. Architecture impact
11. Risks
12. Deferred work
13. Acceptance criteria status