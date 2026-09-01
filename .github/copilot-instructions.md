# Copilot Repository Instructions

This repository implements an enterprise-grade supervised autonomous crypto trading intelligence and execution platform.

The authoritative product and engineering specification is:

- `docs/playbook/**`
- Master Playbook v2.2
- approved Architecture Decision Records (ADRs)
- approved shared contracts

The Master Playbook v2.2 is the source of truth.

If a conflict exists between:
1. Master Playbook v2.2
2. this file
3. `AGENTS.md`
4. agent-specific instructions
5. path-specific instructions
6. an implementation task or issue

the agent must STOP and report the conflict instead of silently choosing an interpretation.

---

## 1. Core Product Principle

This platform is a supervised autonomous crypto trading intelligence system.

It is NOT:
- a simple trading bot
- a single-LLM trading assistant
- an automatic buy/sell script
- an uncontrolled autonomous trader
- a black-box system with untraceable decisions

The platform combines:
- market data
- multi-domain analysis
- multi-agent analysis
- technical analysis
- fundamental analysis
- on-chain analysis
- sentiment analysis
- derivatives analysis
- market-regime analysis
- Smart Money Concepts
- Wyckoff methodology
- Fibonacci analysis
- volume and order-flow analysis
- strategy intelligence
- statistical validation
- evidence generation
- deterministic risk management
- human supervision
- controlled execution
- auditability
- post-trade evaluation
- experience learning
- governed adaptive intelligence

Human supervision remains the final authority for live trading.

---

## 2. Non-Negotiable Rules

All Copilot agents and tasks must obey the following rules.

- Do not simplify this system into a basic trading bot.
- Do not remove functionality from the Master Playbook because implementation is difficult.
- Do not create Chat 14 or introduce a parallel architecture that contradicts the 13-chat structure.
- Do not implement live trading unless an explicitly approved later implementation phase requests it and all safety prerequisites are satisfied.
- Do not create, request, store, expose, or generate real exchange API credentials.
- Do not put secrets in code, prompts, logs, tests, fixtures, examples, comments, issue bodies, pull requests, or documentation.
- Do not allow LLMs or AI agents to directly call exchange trading APIs.
- Do not allow LLM outputs to become executable orders without deterministic validation and human approval.
- Do not fabricate market data.
- Do not fabricate historical performance.
- Do not fabricate backtest results.
- Do not fabricate win rates.
- Do not fabricate probabilities.
- Do not fabricate sample sizes.
- Do not fabricate Sharpe ratios.
- Do not fabricate Sortino ratios.
- Do not fabricate drawdowns.
- Do not fabricate profit factors.
- Do not fabricate expectancy.
- Do not fabricate on-chain statistics.
- Do not fabricate news or external data.
- Do not treat AI confidence as statistical probability.
- Do not treat analytical confluence as statistical proof.
- Do not treat historical performance as a future guarantee.
- Do not bypass human approval.
- Do not bypass deterministic risk validation.
- Do not bypass security controls.
- Do not bypass audit requirements.
- Do not bypass execution authorization.
- Do not bypass reconciliation requirements.
- Do not silently change strategy logic without versioning.
- Do not silently change prompt logic when performance changes.
- Do not silently change shared contracts.
- Do not modify existing architecture without an Architecture Decision Record when the change is architectural.
- Do not enable unsafe fail-open behavior.

When safety cannot be established, fail closed.

---

## 3. Development Workflow

For every task:

1. Read the relevant playbook sections.
2. Read the relevant contracts.
3. Read approved ADRs.
4. Inspect the current repository structure and implementation.
5. Identify affected domains, services, contracts, and files.
6. Identify risks and dependencies.
7. Propose the smallest safe implementation plan.
8. Make the minimum required change.
9. Add or update tests.
10. Validate contract compatibility.
11. Validate architecture compatibility.
12. Update documentation where behavior or architecture changes.
13. State risks, assumptions, and remaining work.
14. Open or update a pull request for review.

Do not perform unrelated refactors during a scoped issue.

Do not create competing abstractions when an approved contract or service already exists.

Do not infer missing architectural decisions silently.

If a decision is unresolved:
- document the issue
- record options
- record advantages/disadvantages
- make a recommendation
- wait for architectural/human approval when required

---

## 4. Architecture Boundaries

AI and deterministic responsibilities must remain clearly separated.

### AI may:

- analyze
- summarize
- interpret
- compare
- challenge
- reason qualitatively
- identify conflicts
- generate hypotheses
- propose strategies
- rank opportunities
- explain conclusions
- monitor
- generate research artifacts
- generate evidence summaries
- support post-trade evaluation
- generate learning hypotheses

### Deterministic services must own:

- indicator calculations
- mathematical calculations
- statistical metrics
- historical backtesting
- out-of-sample testing
- walk-forward validation
- robustness calculations
- position sizing
- leverage calculations
- liquidation calculations
- risk limits
- portfolio constraints
- approval binding
- order construction
- execution validation
- execution authorization
- duplicate-order prevention
- idempotency
- reconciliation
- audit records
- state transitions
- hard rejection rules

LLMs may assist interpretation, but deterministic code remains authoritative for critical financial and execution logic.

---

## 5. Analytical Layer Boundaries

Always distinguish:

Raw Data
→ Calculated Metric
→ Analytical Interpretation
→ Trading Hypothesis
→ Candidate Signal
→ Statistical Validation
→ Risk Assessment
→ Human Approval
→ Execution

These stages are not interchangeable.

Analytical agents must not directly:
- approve trades
- calculate authoritative risk limits
- create live orders
- execute trades
- bypass validation

---

## 6. Evidence and Statistics Rules

All quantitative claims must originate from:
- trusted data sources
- reproducible calculations
- versioned research results
- validated historical datasets

Historical performance must preserve context.

When reporting performance metrics, include where applicable:
- strategy ID
- strategy version
- asset
- market
- timeframe
- market regime
- sample size
- test period
- in-sample status
- out-of-sample status
- walk-forward status
- transaction-cost assumptions
- slippage assumptions
- funding assumptions
- data version
- validation version

Never present:

`Historical win rate = 78%`

as:

`78% probability that the next trade will win`

unless a separately validated calibrated probabilistic model supports that exact statement.

Maintain clear separation between:
- AI Analytical Confidence
- Evidence Strength
- Evidence Score
- Historical Conditional Win Rate
- Statistical Validation
- Expected Value
- Trade Quality Score
- Risk Score
- Calibrated Probability

---

## 7. 75% Qualification Rule

The configured 75% threshold is a historical conditional qualification rule, not a guarantee.

A candidate must not qualify solely because:

`historical_win_rate >= 0.75`

Qualification should also consider configurable requirements such as:
- minimum sample size
- out-of-sample validation
- walk-forward validation
- positive expectancy
- profit factor
- maximum drawdown
- robustness
- current regime compatibility
- data quality
- liquidity
- execution conditions
- portfolio constraints
- risk validation

The exact quantitative validation belongs to the validation framework.

---

## 8. Evidence Independence Rule

Do not simply count indicators or agents.

Multiple signals derived from the same:
- model
- prompt
- data source
- indicator family
- feature set
- reasoning source

must not be treated as fully independent confirmations.

Confluence must consider:
- independence
- correlation
- data quality
- regime fit
- contradictory evidence
- evidence freshness
- model diversity
- prompt diversity
- source diversity

Ten agents repeating the same underlying signal do not equal ten independent confirmations.

---

## 9. No-Trade Rule

`NO_TRADE` is a valid, expected, and preferred outcome when evidence or safety is insufficient.

Examples include:
- stale data
- missing data
- degraded data
- insufficient evidence
- low sample size
- failed quantitative validation
- regime mismatch
- conflicting critical evidence
- low liquidity
- excessive event risk
- excessive portfolio risk
- strategy decay
- model drift
- unavailable risk service
- uncertain approval state
- uncertain exchange state
- unreconciled position state
- unresolved execution risk
- unknown system safety state

Uncertainty must never be converted into a trade merely to force action.

Prefer:

`NO_TRADE`

over:

`UNCERTAIN_TRADE`

---

## 10. Operating Modes

The system must preserve strict separation between:

### Research Mode
- no live execution
- no trading permissions
- research and analysis only
- historical testing allowed
- strategy research allowed

### Paper Trading Mode
- simulated orders
- simulated fills
- simulated fees
- simulated slippage
- simulated funding where applicable
- separate state from live trading

### Live Supervised Trading Mode
- only available after explicit approved implementation phase
- human approval required
- deterministic risk required
- final pre-execution validation required
- full audit and reconciliation required

There must be no silent transition from Research or Paper Trading to Live Trading.

---

## 11. Live Trading Rule

Until explicitly approved through a future production-readiness phase:

`LIVE TRADING = DISABLED`

No live trade may execute unless all required conditions exist and pass.

At minimum:

1. Validated market data
2. Validated candidate signal
3. Evidence package
4. Quantitative validation
5. Deterministic risk proposal
6. Human review
7. Human approval bound to exact parameters
8. Final pre-execution validation
9. Execution safety checks
10. Audit event creation
11. Reconciliation path
12. System trading readiness is acceptable

No approval means no execution.

Approval changed means revalidation required.

Approval expired means no execution.

Material market change means revalidation required.

Risk failure means no execution.

Unknown account state means no execution.

Unknown exchange state means no blind retry.

Unreconciled position state means reconciliation required.

---

## 12. Human Approval Rule

Human approval is mandatory for configured live trades.

Approval must be:
- explicit
- deliberate
- authenticated
- machine-verifiable
- tied to the exact trade configuration

Approval must be bound to:
- signal version
- strategy version
- evidence version
- validation version
- risk version
- entry
- stop loss
- take profit
- amount
- leverage
- risk percentage
- account snapshot
- portfolio snapshot
- timestamp

If a material parameter changes, prior approval becomes invalid and the trade must be revalidated.

Viewing a signal is not approval.

Editing a field is not approval.

Opening a page is not approval.

Generating a report is not approval.

---

## 13. Human Parameter Modification Rule

The human supervisor may modify permitted trade parameters such as:
- investment amount
- position size
- leverage
- entry
- stop loss
- take profit
- trailing stop
- risk percentage
- supported margin mode

Human changes do not bypass risk validation.

After every material change:

User Change
→ Risk Recalculation
→ Liquidation Analysis
→ Exposure Analysis
→ Portfolio Risk Analysis
→ Validation
→ Approval

Hard risk violations must result in rejection.

---

## 14. Shared Contract Rule

Shared contracts are authoritative interfaces between bounded components.

No agent may silently:
- rename a shared contract
- redefine a contract's purpose
- change field semantics
- remove required fields
- change validation behavior
- introduce incompatible schemas
- create a duplicate competing contract

Breaking contract changes require:
1. impact analysis
2. architecture review
3. ADR where appropriate
4. versioning decision
5. migration plan
6. human approval when required

Shared contracts should be versioned.

Backward-compatible evolution is preferred.

---

## 15. Strategy Versioning Rule

Strategies must be immutable by version.

Never silently modify strategy logic while keeping historical statistics attached to the same version.

Strategy changes require a new version.

A strategy version should track:
- strategy ID
- version
- rules
- parameters
- qualification criteria
- supported regimes
- validation references
- creation timestamp
- parent version
- lifecycle status

Experimental strategies must not automatically become production strategies.

---

## 16. Model and Prompt Versioning Rule

Track where applicable:
- provider
- model
- model version
- prompt version
- configuration
- timestamp
- input reference
- output reference
- latency
- token usage
- evaluation result

Do not directly rewrite production prompts because of one failed trade.

Prompt/model changes must follow controlled evaluation.

---

## 17. Learning and Adaptive Intelligence

Learning systems may:
- record experiences
- evaluate outcomes
- measure agent performance
- measure strategy performance
- detect calibration problems
- detect drift
- identify recurring failures
- identify recurring successes
- generate learning observations
- generate hypotheses
- propose experiments
- compare champion/challenger versions
- support shadow-mode evaluation

Learning systems must NOT:
- directly execute trades
- directly change production strategies
- directly change production prompts
- directly change risk limits
- automatically increase leverage
- automatically increase risk
- automatically promote experimental models
- automatically promote experimental strategies
- rewrite historical trading records
- present counterfactual results as actual results

Production changes must follow:

Observation
→ Hypothesis
→ Experiment
→ Validation
→ Governance
→ Versioning
→ Shadow/Paper Testing
→ Human Approval
→ Production Eligibility

---

## 18. Historical Record Immutability

Material decision facts should be append-only or immutable wherever practical.

Do not silently rewrite:
- market snapshots
- signals
- validation results
- risk proposals
- approvals
- orders
- fills
- trade outcomes
- learning experiences
- audit events

Corrections should create a correction or superseding record with provenance.

---

## 19. Security Rules

Use least privilege.

Never expose secrets to AI agents unless absolutely necessary and explicitly approved.

Prefer:
- read-only credentials for analysis
- separate credentials for trading
- environment separation
- secret managers
- encrypted configuration
- restricted exchange permissions
- restricted IP access where supported

Do not store secrets in:
- repository files
- prompts
- LLM context
- logs
- test fixtures
- examples
- documentation
- issue bodies
- pull requests

---

## 20. Auditability and Traceability

Every important production decision must be reconstructable.

The system should be able to answer:

`Why did this trade happen?`

Traceability should connect:

Trade
→ Order
→ Execution Intent
→ Approval
→ Risk Proposal
→ Validation Result
→ Signal
→ Strategy Version
→ Evidence
→ Analysis
→ Market Snapshot
→ Source Data
→ Model/Prompt Versions

And later:

Trade Outcome
→ Evaluation
→ Experience
→ Learning Observation
→ Hypothesis
→ Experiment
→ Governance Decision

---

## 21. Failure-Safety Rules

Fail safely.

Examples:

Missing market data
→ NO_TRADE

Stale market data
→ NO_TRADE

Risk engine unavailable
→ NO_TRADE

Approval state uncertain
→ NO_TRADE

Exchange unavailable before opening a new trade
→ NO_TRADE

Duplicate execution detected
→ HALT / RECONCILE

Unexpected leverage
→ REJECT

Portfolio risk exceeded
→ REJECT

Critical conflicting evidence
→ HUMAN_REVIEW or NO_TRADE

Unknown safety state
→ DO_NOT_ACT

Do not retry uncertain exchange submissions blindly.

---

## 22. Agent Collaboration Rules

All custom Copilot development agents must also follow:

- `AGENTS.md`
- applicable `.github/instructions/*.instructions.md`
- approved ADRs
- approved contracts

Agent-specific instructions may specialize behavior but must not weaken this file.

No agent may merge its own pull request.

The human repository owner is the final authority for:
- merges
- architectural approval
- high-risk code approval
- production readiness
- live-trading enablement
- risk-policy changes
- execution-policy changes
- strategy-promotion approval

---

## 23. Shared Ownership Rule

An agent must not independently modify a shared authoritative contract while another agent is implementing against it.

Examples of shared areas:
- shared contracts
- domain entities
- risk interfaces
- execution interfaces
- signal schemas
- strategy schemas
- version registries
- `.github/**`
- architectural configuration

When a shared contract changes:

Change Proposal
→ Impact Analysis
→ Architecture Review
→ Version Decision
→ Human Approval if required
→ Implementation
→ Contract Tests

---

## 24. Pull Request Rule

Every implementation PR should state:

1. Issue being implemented
2. Agent responsible
3. Objective
4. Relevant Master Playbook sections
5. Contracts affected
6. Files changed
7. Architecture impact
8. Tests added or updated
9. Security/safety impact
10. Known risks
11. Deferred work
12. Acceptance-criteria status

No agent may merge its own PR.

---

## 25. High-Risk Change Rule

The following always require explicit human review:

- risk calculations
- position sizing
- leverage logic
- liquidation logic
- portfolio-limit logic
- approval logic
- authorization
- secrets management
- exchange integration
- CCXT integration
- execution logic
- order construction
- retries
- reconciliation
- strategy promotion
- model/prompt production changes
- learning-driven production changes
- live-trading configuration

---

## 26. Testing Rules

Critical logic must be testable.

Tests should eventually cover:

### Unit
- indicators
- calculations
- position sizing
- risk formulas
- validation rules
- order construction

### Integration
- market data
- persistence
- event infrastructure
- APIs
- exchange adapters
- execution

### Agent
- structured output
- grounding
- hallucination resistance
- evidence references
- tool correctness
- limitations reporting

### Strategy
- backtesting
- OOS validation
- walk-forward validation
- robustness

### Risk
- leverage
- liquidation
- stop loss
- maximum exposure
- portfolio constraints

### Failure
- stale data
- model failure
- database failure
- exchange outage
- network failure
- duplicate order
- partial fill
- uncertain exchange response

Do not disable failing tests simply to make CI pass.

---

## 27. First Project Phase

The first project phase must build only:

- repository structure
- documentation
- ADR foundation
- shared contract foundation
- CI foundation
- backend skeleton
- configuration and environment separation
- audit/event foundation
- safe research-mode market-data foundation
- data-quality foundation
- safe analytical foundations
- tests
- architecture-compliance checks

Do NOT build first:
- production exchange execution
- live trading
- real exchange credentials
- autonomous execution
- production leverage trading
- automatic strategy promotion
- uncontrolled adaptive learning

---

## 28. Initial Implementation Order

Preferred early implementation order:

1. Repository discovery
2. Documentation foundation
3. ADR foundation
4. Contract registry
5. Backend skeleton
6. CI/test foundation
7. Configuration/environment separation
8. Audit/event foundation
9. Market-data contracts
10. Data-quality engine
11. Architecture compliance review
12. Deterministic indicator foundation
13. Market context
14. Market regime
15. Evidence model
16. Candidate signal model
17. No-trade model
18. Quant validation foundation
19. Deterministic risk foundation
20. Human approval foundation
21. Paper trading
22. Exchange abstraction
23. Testnet/sandbox integration where available
24. Controlled live execution only after production-readiness approval

---

## 29. Definition of Done

A task is complete only when:

- requirements are satisfied
- relevant playbook sections are satisfied
- contracts are respected
- tests are added or updated
- tests pass
- no unrelated changes were introduced
- no secrets were introduced
- security requirements are satisfied
- documentation is updated where necessary
- ADR is updated when architecture changes
- safety invariants remain intact
- risks are documented
- deferred work is documented
- PR is ready for independent review

Generated code alone does not mean a task is complete.

---

## 30. Final Repository Principle

The platform must always prefer:

EVIDENCE > OPINION

VALIDATION > CONFIDENCE

RISK CONTROL > PROFIT MAXIMIZATION

REPRODUCIBILITY > BLACK-BOX BEHAVIOR

HUMAN CONTROL > UNCONTROLLED AUTONOMY

NO_TRADE > UNCERTAIN_TRADE

The system must be:

SUPERVISED

AUTONOMOUS

BUT NEVER UNCONTROLLED