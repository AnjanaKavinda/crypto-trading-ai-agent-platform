# Copilot 4-Agent Startup Manual


---

<!-- 00-start-here/START-HERE.md -->

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


---

<!-- 01-setup/REPOSITORY-SETUP.md -->

# Repository Setup Instructions

## Recommended repository name

```text
crypto-trading-ai-agent-platform
```

## Initial folder structure

Create or verify this structure:

```text
crypto-trading-ai-agent-platform/
├── docs/
│   ├── master-playbook/
│   ├── architecture/
│   ├── requirements/
│   ├── agents/
│   ├── strategies/
│   ├── risk/
│   ├── data/
│   ├── execution/
│   ├── api/
│   ├── testing/
│   ├── security/
│   └── operations/
├── contracts/
│   ├── market/
│   ├── analysis/
│   ├── strategy/
│   ├── validation/
│   ├── risk/
│   ├── execution/
│   └── learning/
├── agents/
├── apps/
│   ├── api/
│   └── web/
├── services/
├── packages/
├── infrastructure/
├── tests/
├── scripts/
├── .github/
│   ├── copilot-instructions.md
│   ├── instructions/
│   ├── ISSUE_TEMPLATE/
│   └── workflows/
├── AGENTS.md
└── README.md
```

## Copy files

Copy the Copilot-ready Markdown package into:

```text
docs/master-playbook/
```

Copy the instruction files from this package into the repository root. Keep these paths exactly:

```text
.github/copilot-instructions.md
.github/instructions/*.instructions.md
AGENTS.md
```

GitHub supports repository-level instructions with `.github/copilot-instructions.md`; path-specific instruction files can be organized under `.github/instructions` and use `*.instructions.md` file names. Check your Copilot environment’s settings to ensure custom instructions are enabled.

## Initial branch strategy

```text
main      = stable reviewed baseline
develop   = integration branch
agent/*   = one branch per issue/agent task
```

Never let Copilot push directly to `main`.


---

<!-- 02-agents/FOUR-AGENT-MODEL.md -->

# Four-Agent Model

## Why four agents?

Four agents give you separation of responsibility without making management too difficult.

```text
Architect Agent
  ↓ defines boundaries and docs
Backend/Foundation Agent
  ↓ builds safe foundations
AI-Trading Intelligence Agent
  ↓ builds analysis and signal intelligence
QA/Security/Review Agent
  ↓ tests, reviews, and blocks unsafe paths
Human Owner
  ↓ final approval and merge
```

## Work ownership table

| Area | Primary Agent | Reviewer |
|---|---|---|
| Architecture | Architect | Human |
| Docs | Architect | Human |
| ADRs | Architect | Human |
| Domain contracts | Backend/Foundation | Architect |
| Market/analysis contracts | AI-Trading Intelligence | Architect + QA |
| Backend skeleton | Backend/Foundation | QA |
| CI | QA/Security/Review | Human |
| Testing | QA/Security/Review | Backend/Foundation |
| Security | QA/Security/Review | Human |
| Strategy/signal models | AI-Trading Intelligence | Architect + QA |
| Risk models | Backend/Foundation + QA | Architect + Human |
| Execution | Later phase only | Architect + QA + Human |

## Core collaboration rule

No agent owns final approval. Every PR requires human review.


---

<!-- 03-github-workflow/github-labels.md -->

# GitHub Labels

Create these labels.

## Agent labels

```text
agent:architect
agent:backend-foundation
agent:ai-trading-intelligence
agent:qa-security-review
```

## Phase labels

```text
phase:foundation
phase:contracts
phase:data
phase:analysis
phase:validation
phase:risk
phase:approval
phase:execution
phase:frontend
phase:learning
phase:governance
```

## Type labels

```text
type:docs
type:architecture
type:contract
type:backend
type:frontend
type:test
type:security
type:ci
type:adr
type:review
```

## Risk labels

```text
risk:low
risk:medium
risk:high
risk:blocked-live-trading
risk:security-sensitive
risk:requires-human-review
```

## Status labels

```text
status:ready-for-copilot
status:needs-human-decision
status:blocked
status:ready-for-review
status:changes-requested
```


---

<!-- 03-github-workflow/branching-and-pr-rules.md -->

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


---

<!-- 06-safety/NON-NEGOTIABLE-SAFETY-RULES.md -->

# Non-Negotiable Safety Rules

## Live trading

No live trading until all prerequisites are complete.

## Exchange credentials

No real exchange credentials in:

- source code
- tests
- fixtures
- prompts
- docs
- logs
- screenshots
- issue descriptions
- pull requests

## AI execution boundary

AI agents must never directly call exchange trading APIs.

Correct path:

```text
AI Analysis
  ↓
Signal
  ↓
Validation
  ↓
Risk Proposal
  ↓
Human Approval
  ↓
Execution Intent
  ↓
Execution Engine
  ↓
Exchange Adapter
```

## Evidence integrity

The system must not fabricate:

- win rates
- probabilities
- backtest results
- sample sizes
- Sharpe ratios
- profit factors
- drawdowns
- market data
- on-chain data
- news

## 75% rule

Use:

```text
Historical conditional win rate >= 75% under defined test conditions
```

Do not use:

```text
75% guaranteed chance to win
```

## No-trade rule

The platform must prefer **NO TRADE** over **UNCERTAIN TRADE**.


---

<!-- 07-roadmap/30-DAY-STARTUP-ROADMAP.md -->

# 30-Day Startup Roadmap

## Week 1 — Project control foundation

- Day 1: Create repo, upload Master Playbook v2.2 package, add instructions, add labels.
- Day 2: Issue 001 — Repository Discovery Only.
- Day 3: Issue 002 — Documentation Foundation.
- Day 4: Issue 003 — ADR Foundation.
- Day 5: Issue 004 — Contract Registry Skeleton.
- Day 6: Issue 006 — CI Foundation.
- Day 7: Review, cleanup, merge only safe PRs.

## Week 2 — Backend foundation

- Issue 005 — Backend Project Skeleton.
- Issue 007 — Market Data Contracts.
- Issue 008 — Architecture Compliance Review.
- Issue 009 — Configuration and Environment Model.
- Issue 010 — Audit Event Foundation.

## Week 3 — Domain and contracts

- Issue 011 — Analysis Contracts.
- Issue 012 — Strategy/Signal Contracts.
- Issue 013 — Validation Contracts.
- Issue 014 — Risk Contracts.
- Issue 015 — Approval/Execution Intent Contracts.

## Week 4 — Safe research-mode vertical slice

Build only:

```text
Static/sample market input
  ↓
Data quality validation
  ↓
Technical indicator calculation
  ↓
MarketContext
  ↓
Candidate Signal / Watch / No-Trade
  ↓
Evidence Report
```

No live trading.
No real exchange execution.
No leverage.
No real API keys.


---

<!-- 08-checklists/PR-REVIEW-CHECKLIST.md -->

# Pull Request Review Checklist

## Required

- [ ] PR links to issue.
- [ ] PR states agent role.
- [ ] PR scope matches issue.
- [ ] No unrelated files changed.
- [ ] Tests added or updated.
- [ ] Documentation updated where needed.
- [ ] Safety impact explained.
- [ ] Security impact explained.
- [ ] Architecture impact explained.
- [ ] What was intentionally not implemented is stated.

## Block PR if any are true

- [ ] Live trading added before approval.
- [ ] Exchange credentials added.
- [ ] LLM can call exchange trading API directly.
- [ ] Human approval is bypassed.
- [ ] Risk validation is bypassed.
- [ ] Backtest/performance data is fabricated.
- [ ] AI confidence is represented as probability.
- [ ] Tests are disabled to pass CI.
- [ ] Strategy logic changed without versioning.
- [ ] Architecture changed without ADR.


---

<!-- 08-checklists/FOUNDATION-COMPLIANCE-CHECKLIST.md -->

# Foundation Compliance Checklist

Use this after Issues 001–008.

- [ ] Repository structure exists.
- [ ] Master Playbook v2.2 is present.
- [ ] `.github/copilot-instructions.md` exists.
- [ ] Four agent instruction files exist.
- [ ] AGENTS.md exists.
- [ ] ADR template exists.
- [ ] Open decisions file exists.
- [ ] Contract folders exist.
- [ ] Backend skeleton exists.
- [ ] CI exists.
- [ ] Tests run.
- [ ] No live trading code exists.
- [ ] No real credentials exist.
- [ ] No LLM-to-exchange execution path exists.
- [ ] No fabricated performance data exists.
- [ ] Human approval rule is documented.
- [ ] Risk validation rule is documented.
- [ ] No-trade rule is documented.
- [ ] 75% rule uses historical conditional win-rate language.
