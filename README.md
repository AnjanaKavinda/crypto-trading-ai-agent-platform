# Enterprise-Grade Supervised Autonomous Crypto Trading Platform

This repository contains the source specification, development governance, Copilot multi-agent operating model, cross-cutting engineering contracts, and implementation backlog for an enterprise-grade supervised autonomous cryptocurrency trading intelligence platform.

The system is designed to behave like a disciplined trading research and execution organization rather than a simple trading bot.

Live trading is not the starting objective.

The initial objective is to establish a safe, testable, auditable, contract-driven software foundation.

---

## 1. Core System Principle

The platform is:

**SUPERVISED**

**AUTONOMOUS**

**EVIDENCE-DRIVEN**

**RISK-CONTROLLED**

**HUMAN-GOVERNED**

but never uncontrolled.

The human supervisor remains the final authority for live trading.

The system may:

- collect and normalize data
- analyze markets
- generate evidence
- compare strategies
- generate candidate signals
- perform quantitative validation
- calculate deterministic risk
- propose trades
- simulate trades
- paper trade
- monitor positions
- evaluate outcomes
- learn from experience
- generate hypotheses
- run governed experiments

The system must not bypass:

- human approval
- deterministic risk controls
- safety policies
- security controls
- execution authorization
- audit requirements
- reconciliation requirements

---

## 2. Authoritative Source Hierarchy

Implementation decisions must follow this precedence order:

1. `docs/playbook/**`
2. `docs/cross-cutting/**`
3. approved Architecture Decision Records
4. `.github/copilot-instructions.md`
5. `AGENTS.md`
6. `.github/agents/*.agent.md`
7. `.github/instructions/*.instructions.md`
8. approved GitHub issue requirements
9. implementation code

If two authoritative sources conflict:

**STOP**

**REPORT THE CONFLICT**

**DO NOT SILENTLY CHOOSE AN INTERPRETATION**

The conflict must be reviewed before implementation continues.

---

## 3. Master Playbook

The authoritative product and architecture specification is located under:

```text
docs/playbook/
```

The Master Playbook is currently versioned as:

```text
Master Playbook v2.2
```

It preserves the original architecture and includes the v2.0, v2.1, and v2.2 corrections and enhancements.

The architecture is organized into thirteen major specification areas:

1. Product Requirements & System Constitution
2. Enterprise System Architecture
3. Multi-AI Agent & Trading Intelligence Architecture
4. Market Data, Alternative Data & Data Engineering
5. Technical / Fundamental / SMC / Wyckoff / Meta-Analysis
6. Strategy Engine, Signal Generation & Evidence Qualification
7. Backtesting, Quant Validation & Anti-Overfitting
8. Risk Management, Portfolio Management & Position Sizing
9. Human Approval, Execution, CCXT & Exchange Integration
10. AI Safety, Security, Audit, Observability & Failure Recovery
11. Frontend, Dashboard & Trader UX
12. Implementation Roadmap, Repository Structure, Testing & Copilot Protocol
13. Adaptive Intelligence, Self-Awareness & Experience Learning

Do not create a parallel architecture that bypasses these specifications.

Do not create a new Chat 14.

---

## 4. Repository Documentation Structure

```text
docs/
├── audit/
│   └── COMPLETENESS-AUDIT.md
│
├── adr/
│   ├── README.md
│   └── ADR-TEMPLATE.md
│
├── playbook/
│   ├── 00-master/
│   ├── 01-specification/
│   ├── 02-guidance/
│   ├── 03-reference/
│   ├── START-HERE.md
│   └── README.md
│
├── cross-cutting/
│   ├── 01-domain-contract-registry.md
│   ├── 02-event-contract-registry.md
│   ├── 03-agent-responsibility-matrix.md
│   ├── 04-agent-handoff-matrix.md
│   ├── 05-permission-matrix.md
│   ├── 06-evidence-graph.md
│   ├── 07-decision-provenance-graph.md
│   ├── 08-state-machine-registry.md
│   ├── 09-version-registry.md
│   ├── 10-audit-traceability-matrix.md
│   ├── 11-failure-recovery-matrix.md
│   ├── 12-test-traceability-matrix.md
│   ├── 13-requirements-traceability.md
│   ├── 14-open-decisions.md
│   └── 15-definition-of-done.md
│
└── copilot-team/
    ├── 00-start-here/
    ├── 01-setup/
    ├── 02-agents/
    ├── 03-github-workflow/
    ├── 04-issues/
    ├── 05-prompts/
    ├── 06-safety/
    ├── 07-roadmap/
    ├── 08-checklists/
    ├── 09-templates/
    ├── START-HERE.md
    └── README.md
```

---

## 5. Cross-Cutting Engineering Artifacts

The following artifacts are first-class engineering controls:

- Domain Contract Registry
- Event Contract Registry
- Agent Responsibility Matrix
- Agent Handoff Matrix
- Permission Matrix
- Evidence Graph
- Decision Provenance Graph
- State Machine Registry
- Version Registry
- Audit and Traceability Matrix
- Failure and Recovery Matrix
- Test Traceability Matrix
- Requirements Traceability Matrix
- Open Decision Register
- Definition of Done

These artifacts are not optional documentation.

They define the interfaces and controls that implementation must follow.

---

## 6. Copilot Development Team

This repository uses a controlled four-agent software-development model.

The four Copilot development agents are:

### Platform Architect

Responsible for:

- architecture
- ADRs
- contract governance
- boundaries
- traceability
- implementation sequencing
- architecture conflict detection

### Backend/Foundation Engineer

Responsible for:

- backend foundation
- APIs
- configuration
- persistence
- database infrastructure
- audit/event infrastructure
- deterministic platform services

### Trading Intelligence Engineer

Responsible for:

- market intelligence
- technical analysis
- fundamental analysis
- on-chain analysis
- sentiment analysis
- derivatives
- SMC
- Wyckoff
- Fibonacci
- market regime
- evidence
- strategy
- signals
- NO_TRADE
- quantitative validation integration

### QA / Security Reviewer

Responsible for:

- tests
- CI
- security
- safety validation
- contract compatibility
- architecture compliance
- failure-mode validation
- pull-request review

The human repository owner remains the final authority for merges and high-risk decisions.

---

## 7. Copilot Configuration

Repository-wide Copilot governance:

```text
.github/copilot-instructions.md
```

Custom selectable Copilot agents:

```text
.github/agents/
```

Path-specific implementation rules:

```text
.github/instructions/
```

Team operating rules:

```text
AGENTS.md
```

Issue templates:

```text
.github/ISSUE_TEMPLATE/
```

Pull-request template:

```text
.github/pull_request_template.md
```

All Copilot agents must follow the global repository instructions.

Agent-specific instructions may strengthen or specialize the global rules.

They must never weaken them.

---

## 8. Development-Agent Workflow

The preferred implementation workflow is:

```text
Architect
    ↓
Defines boundaries / contracts / acceptance criteria
    ↓
Backend or Trading Intelligence Agent
    ↓
Implements one scoped issue
    ↓
QA / Security Agent
    ↓
Independent review and testing
    ↓
Human Owner
    ↓
Approve / Reject / Request Changes
    ↓
Merge
```

Agents must work on one clearly scoped issue at a time.

No agent may merge its own pull request.

---

## 9. GitHub Issue Backlog

The implementation backlog is maintained under:

```text
docs/copilot-team/04-issues/
```

The backlog contains the complete planned implementation lifecycle.

Do not execute all issues simultaneously.

Issue execution must follow:

- dependency order
- phase gates
- architecture approval
- contract readiness
- safety readiness
- human review

The backlog exists to preserve complete feature coverage, not to encourage uncontrolled parallel development.

---

## 10. Initial Development Rule

The first task is not:

```text
Build the complete trading platform.
```

The first task is:

```text
Repository Architecture Discovery
```

The Architect Agent must inspect the repository before application implementation begins.

During repository discovery:

- do not implement product code
- do not install unnecessary dependencies
- do not create exchange integration
- do not create credentials
- do not implement live trading
- do not modify trading architecture

---

## 11. Initial Implementation Sequence

The preferred early sequence is:

```text
Repository Discovery
        ↓
Specification Readiness
        ↓
ADR Foundation
        ↓
Requirements Traceability
        ↓
Contract Governance
        ↓
Domain/Event Contract Foundation
        ↓
Backend Foundation
        ↓
CI / Testing Foundation
        ↓
Configuration / Environment Separation
        ↓
Audit / Event Infrastructure
        ↓
Market Data Foundation
        ↓
Data Quality
        ↓
Analytical Foundation
```

Only after those foundations are stable should the project progress into:

- strategy
- signal qualification
- backtesting
- risk
- human approval
- paper execution
- exchange abstraction
- testnet
- supervised live execution

---

## 12. Operating Modes

The platform must distinguish:

### Research Mode

Analysis and research only.

No exchange execution.

### Backtest Mode

Historical simulation.

No real orders.

### Paper Trading Mode

Simulated trading and execution.

No real funds.

### Shadow Mode

Production-like evaluation without active trade authority.

### Testnet Mode

Exchange sandbox/test environment where supported.

### Live Supervised Trading Mode

Real trading.

Requires explicit production-readiness approval.

There must be no silent transition between modes.

---

## 13. Live Trading Status

Until explicitly approved:

```text
LIVE TRADING = DISABLED
```

Dangerous capabilities must default to OFF.

No Copilot agent may independently enable live trading.

---

## 14. Human Approval Principle

For configured live trading:

```text
NO HUMAN APPROVAL
=
NO EXECUTION
```

Human approval must be explicit and bound to the exact trade configuration.

Material changes to:

- entry
- stop loss
- take profit
- position size
- leverage
- risk percentage
- strategy version
- evidence
- validation result
- risk model
- account state
- portfolio state

require revalidation where applicable.

---

## 15. Deterministic Risk Principle

Risk management is independent from AI reasoning authority.

Critical calculations must be deterministic and testable.

Examples:

- risk per trade
- position size
- leverage
- liquidation risk
- portfolio exposure
- correlation exposure
- maximum loss
- drawdown limits
- margin requirements

AI may explain risk.

AI may not override authoritative risk limits.

---

## 16. NO_TRADE Principle

`NO_TRADE` is a first-class valid system decision.

The platform must not be optimized simply to generate trades.

Examples of valid NO_TRADE conditions:

- stale data
- degraded data
- insufficient evidence
- conflicting evidence
- low sample size
- failed validation
- regime mismatch
- event risk
- liquidity risk
- excessive portfolio exposure
- model drift
- strategy decay
- unavailable risk service
- uncertain approval state
- uncertain execution state
- unknown safety state

A correct NO_TRADE decision is considered successful system behavior.

---

## 17. Evidence and Statistical Integrity

Never fabricate:

- market data
- evidence
- win rates
- backtests
- probabilities
- sample sizes
- Sharpe ratios
- Sortino ratios
- expectancy
- profit factors
- drawdowns
- OOS results
- walk-forward results

Always distinguish:

```text
AI Confidence
Evidence Strength
Historical Win Rate
Expected Value
Calibrated Probability
Risk Score
```

These are not interchangeable.

Historical performance is not a guarantee of future performance.

---

## 18. 75% Qualification Rule

The configured 75% requirement is a historical conditional qualification threshold.

It does not mean:

```text
75% probability that the next trade will win.
```

Qualification must consider additional evidence such as:

- sample size
- out-of-sample validation
- walk-forward validation
- expectancy
- drawdown
- robustness
- regime compatibility
- fees
- slippage
- liquidity
- data quality
- risk acceptance

---

## 19. Evidence Independence

Do not simply count indicators or agents.

Multiple correlated indicators are not independent confirmation.

Multiple agents using the same:

- model
- prompt
- data
- indicators
- feature set

must not automatically be counted as independent evidence.

Evidence confluence must account for dependence and correlation.

---

## 20. AI-to-Execution Boundary

Never allow:

```text
LLM
→
Direct Exchange Order
```

The required control path is conceptually:

```text
Data
→
Analysis
→
Strategy
→
Signal
→
Validation
→
Risk
→
Human Approval
→
Execution Intent
→
Execution
→
Exchange Adapter
→
Exchange
→
Reconciliation
```

---

## 21. Strategy Versioning

Strategies must be versioned.

Never silently change strategy logic while retaining old performance statistics.

A changed strategy must receive a new version and new validation record.

---

## 22. Adaptive Intelligence and Learning

The learning layer may:

- record experiences
- measure agent performance
- measure strategy performance
- identify failures
- identify successes
- detect drift
- generate hypotheses
- propose experiments
- compare champion/challenger versions

Learning must not directly:

- execute trades
- change production strategies
- change production prompts
- change risk limits
- increase leverage
- automatically promote experimental models
- rewrite historical outcomes

The learning lifecycle is:

```text
Experience
→
Observation
→
Insight
→
Hypothesis
→
Experiment
→
Validation
→
Governance
→
Versioning
→
Shadow / Paper Testing
→
Human Approval
→
Production Eligibility
```

---

## 23. Security Rules

Never store or expose:

- exchange API secrets
- private keys
- model-provider credentials
- database passwords
- unrestricted production tokens

Use least privilege.

Separate permissions for:

- analysis
- research
- risk
- approval
- execution
- administration

---

## 24. Auditability

Every important production decision must be reconstructable.

The system should be able to answer:

```text
What happened?
When?
Why?
Which data?
Which analysis?
Which evidence?
Which agent?
Which model?
Which prompt?
Which strategy?
Which validation?
Which risk calculation?
Who approved it?
What parameters were approved?
What was executed?
What happened afterward?
```

---

## 25. Testing Principles

Testing must eventually include:

- unit tests
- integration tests
- contract tests
- API tests
- database tests
- agent tests
- orchestration tests
- backtest tests
- risk tests
- approval tests
- execution tests
- security tests
- failure-recovery tests
- end-to-end tests

Critical safety invariants must have automated verification where practical.

Never disable failing tests simply to pass CI.

---

## 26. Pull Request Requirements

Every implementation PR should identify:

1. Issue number
2. Agent responsible
3. Objective
4. Relevant playbook sections
5. Contracts affected
6. Files changed
7. Architecture impact
8. Tests added or updated
9. Security impact
10. Safety impact
11. Known risks
12. Deferred work
13. Acceptance-criteria status

No agent may merge its own PR.

---

## 27. High-Risk Changes

The following always require explicit human review:

- risk calculations
- leverage logic
- position sizing
- liquidation logic
- portfolio limits
- authentication
- authorization
- secrets management
- human approval
- exchange integration
- CCXT
- execution
- order construction
- execution retries
- reconciliation
- production strategy promotion
- model/prompt production changes
- adaptive production changes
- live-trading configuration

---

## 28. Definition of Done

Generated code alone does not mean an issue is complete.

A task is complete only when:

- issue requirements are satisfied
- relevant playbook requirements are satisfied
- contracts are respected
- architecture is respected
- tests are added or updated
- tests pass
- no unrelated changes were introduced
- no secrets were introduced
- security requirements are met
- safety requirements are met
- documentation is updated
- ADR is updated when required
- risks are documented
- deferred work is documented
- PR is ready for independent review

See:

```text
docs/cross-cutting/15-definition-of-done.md
```

for the authoritative detailed Definition of Done.

---

## 29. Repository Development Principle

Always prefer:

```text
EVIDENCE > OPINION

VALIDATION > CONFIDENCE

SAFETY > SPEED

RISK CONTROL > PROFIT MAXIMIZATION

REPRODUCIBILITY > BLACK-BOX BEHAVIOR

AUDITABILITY > HIDDEN AUTOMATION

HUMAN CONTROL > UNCONTROLLED AUTONOMY

NO_TRADE > UNCERTAIN_TRADE
```

---

## 30. Current Project Status

The repository is currently in:

```text
PRE-IMPLEMENTATION / SPECIFICATION FOUNDATION
```

The immediate objective is to finalize and validate:

- Master Playbook
- cross-cutting artifacts
- Copilot development-team configuration
- GitHub issue backlog
- repository governance
- pre-implementation readiness

Application implementation must not begin until the pre-implementation readiness gate is satisfied.

---

## 31. Start Here

For product architecture:

```text
docs/playbook/START-HERE.md
```

For Copilot development workflow:

```text
docs/copilot-team/00-start-here/START-HERE.md
```

For engineering contracts and control artifacts:

```text
docs/cross-cutting/
```

For the Architecture Decision Record register and template:

```text
docs/adr/
```

For implementation backlog:

```text
docs/copilot-team/04-issues/
```

For repository-wide Copilot rules:

```text
.github/copilot-instructions.md
```

For four-agent team rules:

```text
AGENTS.md
```

---

## Final Principle

Build this system as if it may eventually manage serious capital.

Therefore:

**SAFETY FIRST**

**EVIDENCE FIRST**

**AUDITABILITY FIRST**

**RISK FIRST**

**HUMAN CONTROL FIRST**

Performance optimization comes only after correctness, validation, safety, and governance.
