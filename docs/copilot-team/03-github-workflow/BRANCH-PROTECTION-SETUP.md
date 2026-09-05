# Branch Protection Setup

This repository uses GitHub repository rulesets as the durable protection source for the governed Copilot orchestrator.

## Required branches

Both `dev` and `main` must have active, independently verifiable protection before canonical Issue 004 / GitHub #6 can be activated.

The required invariants are:

- changes enter through pull requests;
- at least one approving review is required;
- stale approvals are dismissed after new pushes;
- review threads must be resolved;
- the `governance-ci` status check must pass;
- required status checks are strict;
- branch deletion is blocked;
- non-fast-forward / force pushes are blocked;
- no ruleset bypass actors are configured;
- no merge queue rule is configured;
- repository auto-merge remains disabled.

## Governance CI

`.github/workflows/governance-ci.yml` defines a job whose stable check name is `governance-ci`. GitHub required-status-check configuration uses the job/check name rather than the workflow display name.

## One-time ruleset application

Run from an admin-capable GitHub CLI session after this change is merged to `dev`:

```powershell
gh auth status
pwsh ./scripts/setup-branch-rulesets.ps1 -Repo AnjanaKavinda/crypto-trading-ai-agent-platform
```

The setup is idempotent:

- existing `protect-main` is updated in place;
- `protect-dev` is created if absent, otherwise updated;
- duplicate same-name rulesets cause a fail-closed error;
- `GOVERNED_REQUIRED_CHECKS` is set to `governance-ci`.

The setup script does not enable `GOVERNED_PILOT_ENABLED`.

## Verification

After applying the rulesets:

```powershell
pwsh ./scripts/verify-branch-rulesets.ps1 -Repo AnjanaKavinda/crypto-trading-ai-agent-platform
```

Do not enable the Issue 004 pilot unless verification passes for both branches and the live GitHub Rulesets API confirms the same state.

## Safety boundary

Ruleset setup does not authorize merging, production execution, live trading, or exchange access. Human final merge authority remains mandatory.
