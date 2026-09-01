---
applyTo: "apps/api/**,packages/**,infrastructure/**,tests/backend/**,.github/workflows/**"
---

# Backend/Foundation Path Instructions

These instructions apply to backend, infrastructure, configuration, persistence, and deterministic platform foundation code.

## Authoritative sources

Read before implementation:

- `.github/copilot-instructions.md`
- `AGENTS.md`
- relevant `docs/playbook/**` sections
- relevant approved ADRs
- relevant approved contracts

If instructions conflict:

STOP and report the conflict.

## Backend responsibilities

Preserve:

- FastAPI application boundaries
- dependency injection
- configuration separation
- persistence abstraction
- database boundaries
- audit/event infrastructure
- health/readiness behavior
- secure configuration
- deterministic validation
- environment isolation
- testability

## Contract rule

Use approved contracts.

Do not create a competing representation of an existing shared domain object.

Do not silently:

- rename contract fields
- remove required fields
- change field meaning
- alter validation semantics
- create incompatible schemas

If a contract is insufficient, raise a contract-change request.

## Financial safety

Critical monetary and financial calculations must:

- be deterministic
- be testable
- use safe numeric representations
- not rely on LLM-generated arithmetic
- not use unsafe floating-point assumptions

Examples include:

- money
- position size
- leverage
- risk percentage
- margin
- liquidation calculations
- fees
- slippage
- portfolio exposure

## Environment rules

Keep separate:

- Development
- Test
- Staging
- Production

Keep operating modes separate:

- Research
- Paper Trading
- Live Supervised Trading

No configuration may silently enable live trading.

## Security rules

Never:

- add real exchange credentials
- expose secrets
- commit secrets
- put secrets in tests
- log secrets
- pass unrestricted exchange credentials to AI agents

## Execution rule

Foundation code must not introduce live trading.

No direct exchange execution.

No unrestricted CCXT calls.

No withdrawal/fund-transfer capability.

Later execution work must still remain behind:

Authorization
→ Safety
→ Risk
→ Approval
→ Final Validation
→ Execution
→ Audit
→ Reconciliation

## Testing rule

Add or update tests for all behavior changed by the issue.

Where relevant include:

- unit tests
- integration tests
- contract tests
- failure-path tests

Do not disable failing tests merely to pass CI.

## Pull request requirement

Every relevant PR must state:

1. Issue number
2. Objective
3. What changed
4. Why it changed
5. Contracts used
6. Files changed
7. Tests added/updated
8. Architecture impact
9. Security impact
10. Risks
11. Deferred work
12. Acceptance criteria status