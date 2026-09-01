# Branching and Pull Request Rules

## Branches

```text
main      = stable, reviewed, releasable baseline
develop   = integration branch
agent/*   = one issue per branch
```

## Branch naming

```text
agent/architect/issue-001-repository-discovery
agent/backend/issue-005-api-skeleton
agent/ai/issue-007-market-data-contracts
agent/qa/issue-006-ci-foundation
```

## PR requirements

Every PR must include:

1. Linked issue
2. Agent role
3. Summary of changes
4. Files changed
5. Playbook references
6. Contract impact
7. Tests added/updated
8. Safety/security impact
9. What was intentionally not implemented
10. Remaining work

## Merge rules

- No direct push to `main`.
- No agent merges its own PR.
- CI must pass.
- Human owner must review.
- Security-sensitive changes require QA/Security/Review Agent review.
- Architecture changes require ADR review.

## Red flags

Reject PRs that include:

- live trading code before approval
- exchange credentials
- LLM-to-exchange execution paths
- fabricated backtest/performance data
- missing tests for deterministic logic
- strategy changes without versioning
- disabled tests
- undocumented architecture changes
