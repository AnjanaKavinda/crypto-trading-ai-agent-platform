# Start Here — Controlled 4-Agent Project Initiation

## Recommended starting model

Use exactly four starting agents:

```text
1. Architect Agent
2. Backend/Foundation Agent
3. AI-Trading Intelligence Agent
4. QA/Security/Review Agent
```

You remain the final authority:

```text
You = Product Owner + Chief Architect + Final Reviewer
Copilot = task execution assistant
GitHub Issues = bounded task prompts
Pull Requests = review gates
CI = automated safety net
```

## Project rule

Start with documentation, architecture, contracts, CI, and safe research-mode components. Do not start with exchange execution, leverage, real API keys, or live trading.

## First day checklist

- [ ] Create GitHub repository.
- [ ] Add Master Playbook v2.2 files.
- [ ] Add this instruction package.
- [ ] Add `.github/copilot-instructions.md`.
- [ ] Add `.github/instructions/*.instructions.md` files.
- [ ] Create labels from `03-github-workflow/github-labels.md`.
- [ ] Create Issue 001 from `04-issues/issue-001-repository-discovery.md`.
- [ ] Assign Issue 001 to Copilot/Architect Agent.
- [ ] Ensure Issue 001 says **do not modify code**.

## First 8 issues

1. Repository Discovery Only
2. Documentation Foundation
3. ADR Foundation
4. Domain Contract Registry Skeleton
5. Backend Project Skeleton
6. CI Foundation
7. Market Data and Data Quality Contracts
8. Architecture Compliance Review

Do not skip Issue 001.
