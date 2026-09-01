---
applyTo: "tests/**,.github/workflows/**,docs/testing/**,docs/security/**,docs/operations/**,scripts/**"
---

# QA/Security/Review Path Instructions

These instructions apply to testing, CI, security, safety, compliance, and operational-review files.

## Authoritative sources

Read:

- `.github/copilot-instructions.md`
- `AGENTS.md`
- relevant `docs/playbook/**` sections
- approved contracts
- approved ADRs
- current issue acceptance criteria

If requirements conflict:

STOP and report the conflict.

Do not weaken requirements silently.

## Review responsibility

Check:

- functional correctness
- test coverage
- contract compatibility
- architecture compliance
- security
- safety
- auditability
- failure handling
- fail-closed behavior
- idempotency
- reconciliation
- observability
- regression risk

## Mandatory security checks

Flag:

- secrets
- credentials
- unsafe authorization
- frontend-only authorization
- unrestricted exchange credentials
- unsafe external calls
- excessive permissions

## Mandatory trading-safety checks

Flag:

- LLM-to-exchange execution paths
- human approval bypass
- risk bypass
- execution authorization bypass
- stale-data execution
- expired-signal execution
- expired-approval execution
- incorrect approval binding
- duplicate orders
- unsafe retries
- missing idempotency
- missing reconciliation
- fail-open behavior

## Statistical integrity checks

Flag:

- fabricated financial evidence
- fabricated backtest results
- fabricated win rates
- unsupported probabilities
- AI confidence shown as probability
- confluence shown as probability
- small samples represented as strong evidence
- OOS/walk-forward claims without reproducible support

## Strategy governance checks

Flag:

- unversioned strategy changes
- changed strategy logic using old historical metrics
- experimental strategy auto-promotion
- learning directly changing production strategy/risk

## NO_TRADE checks

Test that NO_TRADE occurs correctly for relevant cases:

- missing data
- stale data
- low sample size
- failed validation
- conflicting evidence
- invalid regime
- excessive event risk
- portfolio risk violation
- unavailable critical services
- unknown safety state

## Approval checks

Where approval exists, test:

- explicit approval
- authorization
- expiration
- parameter binding
- parameter-change invalidation
- replay protection
- duplicate-click protection
- stale state
- unauthorized approval attempts

## Contract checks

Verify:

- schema compatibility
- required fields
- correct semantics
- version compatibility
- producer/consumer compatibility
- detection of breaking changes

Do not modify contracts merely to make a bad implementation pass.

## Testing rule

Never disable tests just to make CI pass.

Never reduce validation requirements merely because tests fail.

A failing test may reveal an implementation defect or requirement conflict.

## Review severity

Classify findings:

### BLOCKER
Must be fixed before merge.

### MAJOR
Significant concern requiring resolution or explicit acceptance.

### MINOR
Non-blocking quality issue.

### INFO
Observation or future improvement.

## Pull request review requirement

Every review should report:

1. Issue/PR reference
2. Tests executed
3. Compliance status
4. Blockers
5. Major findings
6. Minor findings
7. Security findings
8. Safety findings
9. Architecture findings
10. Contract findings
11. Deferred risks
12. Final recommendation:
    - APPROVE
    - APPROVE_WITH_NOTES
    - REQUEST_CHANGES
    - BLOCK

The human repository owner remains the final merge authority.