# Chat 1 — Product Requirements & System Constitution

> Full source-derived Chat 1 content from the uploaded Master Playbook v2.2 DOCX. This is not a summary. Source Markdown lines 3199–5750 of the complete conversion.

---

Master Prompt — Chat 1

V2.1 INLINE UPGRADE - CHAT 1 PRODUCT REQUIREMENTS & SYSTEM CONSTITUTION

Purpose: make Chat 1 the controlling constitution for the complete supervised autonomous crypto trading platform. This insert strengthens but does not replace the original Chat 1 requirements.

Retained Scope

Preserve the original objective of a disciplined professional trading research and execution team.

Preserve technical, quantitative, SMC, Wyckoff, Fibonacci, volume/order flow, derivatives, on-chain, tokenomics, news, sentiment, macro, regime, strategy, evidence, validation, risk, approval, execution, monitoring, post-trade intelligence, and continuous improvement requirements.

Preserve the three operating modes: Research, Paper Trading, and Live Supervised Trading, with no silent promotion between modes.

v2.1 Corrections and Enhancements

Define professional trader behavior as a governed workflow, not an LLM persona.

Define NO_TRADE as a first-class valid decision with machine-readable reason codes.

Define evidence freshness and signal expiration as mandatory signal properties.

Define approval binding to immutable decision snapshots.

Define operational self-awareness as awareness of knowns, unknowns, data reliability, agent health, strategy health, drift, validation freshness, risk state, and system readiness.

Chat 1 Required Contracts

GlobalConstitution, OperatingModePolicy, TradeEligibilityPolicy, EvidencePolicy, ApprovalPolicy, RiskPolicy, SecurityPolicy, AuditPolicy, LearningGovernancePolicy, OpenDecisionRecord.

Acceptance Criteria

Every later chat can trace its requirements back to this constitution.

No implementation prompt can treat AI confidence as probability or a 75 percent historical threshold as a future guarantee.

All live trading remains human-approved, deterministic-risk-gated, and auditable.

# **Enterprise-Grade Supervised Autonomous Crypto Trading Intelligence & Execution Platform**

## **GitHub Copilot Master Prompt — Chat 1**

You are acting as the **Principal Software Architect, Quantitative Trading Systems Architect, AI Agent Architect, Security Architect, and Senior Engineering Lead** for this project.

We are designing and incrementally implementing an **enterprise-grade, AI-powered, supervised crypto market analysis, trading intelligence, and trading execution platform**.

This is NOT a simple crypto trading bot.

It is a **multi-agent trading intelligence and supervised execution platform** whose purpose is to analyse cryptocurrency markets using multiple independent analytical disciplines, evaluate trading opportunities using reproducible historical evidence, present transparent trading signals to a human supervisor, and execute trades only after explicit approval and deterministic risk validation.

The system must be designed so that AI assists with analysis and reasoning while **critical financial calculations, risk controls, permissions, execution constraints, and transaction integrity remain deterministic and auditable**.

# **1. PRIMARY OBJECTIVE**

Build a platform capable of behaving like a highly disciplined professional trading research and execution team.

The system should:

1.  Collect and normalize real-time and historical crypto market data.

2.  Analyse markets using technical analysis.

3.  Analyse market structure and price action.

4.  Analyse Smart Money Concepts.

5.  Analyse Wyckoff methodology.

6.  Analyse Fibonacci structures and confluence.

7.  Analyse volume and order flow.

8.  Analyse derivatives markets.

9.  Analyse funding rates.

10. Analyse open interest.

11. Analyse liquidations.

12. Analyse futures basis and related derivatives metrics where available.

13. Analyse on-chain activity.

14. Analyse tokenomics and project fundamentals.

15. Analyse news and events.

16. Analyse social sentiment.

17. Analyse macroeconomic/intermarket conditions.

18. Determine the current market regime.

19. Evaluate multiple trading strategies independently.

20. Combine strategy outputs using a transparent strategy ensemble.

21. Generate candidate trading signals.

22. Validate signals using historical and statistical evidence.

23. Produce a detailed Evidence Report.

24. Determine whether a signal is trade-eligible.

25. Apply deterministic risk management.

26. Present the opportunity to the human supervisor.

27. Allow the human supervisor to modify trade parameters.

28. Recalculate and revalidate risk after modifications.

29. Require explicit human approval before live execution.

30. Execute approved trades through a controlled exchange abstraction.

31. Monitor positions after execution.

32. Perform post-trade analysis.

33. Measure strategy and agent performance.

34. Continuously improve the analytical system through measured evidence rather than unsupported assumptions.

# **2. CORE PHILOSOPHY**

The system must follow these principles:

## **2.1 AI is an analyst, not an unrestricted trader**

LLMs may:

- interpret information;

- reason about market context;

- compare hypotheses;

- explain technical structures;

- summarize evidence;

- identify conflicting signals;

- propose strategies;

- rank opportunities;

- generate research reports.

LLMs must NOT independently:

- transfer funds;

- bypass risk limits;

- directly call exchange trading APIs;

- fabricate historical statistics;

- claim statistical probabilities without evidence;

- modify security controls;

- disable safeguards;

- bypass human approval for live trading.

# **3. ABSOLUTE NON-NEGOTIABLE RULES**

Implement these as architectural principles.

### **Rule 1 — No fabricated evidence**

The system must never invent:

- win rates;

- historical performance;

- backtest results;

- sample sizes;

- probabilities;

- Sharpe ratios;

- drawdowns;

- profit factors;

- market data;

- news;

- on-chain statistics.

Every quantitative claim must originate from a reproducible calculation or trusted data source.

### **Rule 2 — AI confidence is NOT statistical probability**

Do not represent an LLM's confidence as a probability of trade success.

Keep these separate:

AI Analytical Confidence

Statistical Validation

Historical Win Rate

Expected Value

Trade Quality Score

Risk Score

### **Rule 3 — Win rate alone is insufficient**

Never classify a strategy as successful solely because its win rate exceeds a threshold.

Evaluate:

- win rate;

- average win;

- average loss;

- expectancy;

- profit factor;

- Sharpe ratio;

- Sortino ratio;

- Calmar ratio;

- maximum drawdown;

- volatility;

- sample size;

- out-of-sample performance;

- walk-forward performance;

- regime performance;

- transaction fees;

- funding costs;

- slippage;

- liquidity;

- tail risk.

### **Rule 4 — Default statistical eligibility target**

The default trade-eligibility target is:

Validated historical win rate \>= 75%

However, this is NOT a guarantee and must never be represented as one.

The threshold must be configurable.

A signal should only become trade-eligible when it also satisfies configurable:

- minimum sample size;

- out-of-sample validation;

- walk-forward validation;

- positive expectancy;

- minimum profit factor;

- acceptable drawdown;

- compatible market regime;

- data quality;

- liquidity;

- execution;

- portfolio risk constraints.

The system must allow different thresholds for different:

- assets;

- strategies;

- timeframes;

- market regimes;

- account profiles.

# **4. SYSTEM OPERATING MODES**

The platform must support three completely separated operating modes.

## **MODE 1 — RESEARCH**

Purpose:

Market research and signal discovery.

Characteristics:

- no order execution;

- no exchange trading permissions;

- full analytical exploration;

- historical analysis;

- signal generation;

- strategy research.

## **MODE 2 — PAPER TRADING**

Purpose:

Validate strategies under simulated execution.

Characteristics:

- simulated orders;

- simulated fills;

- realistic fees;

- realistic slippage assumptions;

- funding simulation where applicable;

- position tracking;

- P&L;

- drawdown;

- performance attribution.

Paper trading must NOT share live execution state.

## **MODE 3 — LIVE SUPERVISED TRADING**

Purpose:

Execute real trades under strict human supervision.

Required sequence:

Market Analysis

↓

Candidate Signal

↓

Statistical Validation

↓

Evidence Report

↓

Risk Validation

↓

Human Review

↓

Human Parameter Modification

↓

Risk Recalculation

↓

Final Validation

↓

Explicit Human Approval

↓

Execution

↓

Position Monitoring

There must be no silent transition from Research or Paper Trading to Live Trading.

# **5. HIGH-LEVEL ARCHITECTURE**

Use the following logical architecture as the foundation.

HUMAN SUPERVISOR

│

▼

┌──────────────────────────┐

│ Trading Orchestrator & │

│ Human Approval Gateway │

└────────────┬─────────────┘

│

▼

ANALYSIS WORKFLOWS

│

┌───────────────────┼──────────────────┐

│ │ │

▼ ▼ ▼

┌────────────────┐ ┌────────────────┐ ┌────────────────┐

│ Market Data │ │ Technical & │ │ Fundamental & │

│ Intelligence │ │ Quant Analysis │ │ On-chain │

│ │ │ │ │ Intelligence │

└───────┬────────┘ └───────┬────────┘ └───────┬────────┘

│ │ │

└───────────────────┼──────────────────┘

│

┌────────▼─────────┐

│ Derivatives & │

│ Sentiment │

└────────┬─────────┘

│

┌────────▼─────────┐

│ Market Regime & │

│ Meta-Analysis │

└────────┬─────────┘

│

┌────────▼─────────┐

│ Strategy Ensemble│

│ & Signal Engine │

└────────┬─────────┘

│

┌────────▼─────────┐

│ Validation & │

│ Evidence Engine │

└────────┬─────────┘

│

┌────────▼─────────┐

│ Deterministic │

│ Risk Engine │

└────────┬─────────┘

│

HUMAN APPROVAL

│

┌────────▼─────────┐

│ Execution Engine │

│ / CCXT │

└────────┬─────────┘

│

EXCHANGE

│

┌────────▼─────────┐

│ Position Monitor │

└────────┬─────────┘

│

┌────────▼─────────┐

│ Post-Trade & │

│ Performance │

│ Intelligence │

└──────────────────┘

Do not collapse these responsibilities into one giant AI agent.

# **6. AGENT AND SERVICE BOUNDARIES**

Use the following logical components.

## **6.1 Trading Orchestrator & Human Approval Gateway**

Responsibilities:

- workflow orchestration;

- state management;

- agent routing;

- LangGraph workflow management;

- human-in-the-loop pauses;

- approval;

- rejection;

- parameter modification;

- timeout;

- cancellation;

- emergency halt;

- workflow recovery;

- audit events.

The orchestrator must not directly execute exchange orders.

## **6.2 Market Data Intelligence**

Responsible for:

- OHLCV;

- tick/trade data;

- order books;

- spreads;

- volume;

- market depth;

- funding;

- open interest;

- liquidations;

- futures basis;

- derivatives data;

- historical data;

- data quality validation;

- timestamp validation;

- stale-data detection.

Separate data acquisition from AI interpretation wherever practical.

## **6.3 Technical & Quantitative Analysis Agent**

Support:

### **Classical technical analysis**

- SMA;

- EMA;

- WMA;

- RSI;

- MACD;

- Stochastic;

- CCI;

- ADX;

- ATR;

- Bollinger Bands;

- Ichimoku;

- VWAP;

- OBV;

- volume profile.

### **Price action**

- support;

- resistance;

- trend;

- channels;

- breakouts;

- reversals;

- consolidation;

- volatility compression;

- volatility expansion.

### **Market structure**

- HH;

- HL;

- LH;

- LL;

- BOS;

- CHoCH;

- liquidity zones.

### **Smart Money Concepts**

- order blocks;

- fair value gaps;

- liquidity sweeps;

- breaker blocks;

- mitigation;

- premium/discount;

- inducement where reliably defined.

### **Wyckoff**

- accumulation;

- distribution;

- spring;

- upthrust;

- SOS;

- SOW;

- volume/price relationships.

### **Fibonacci**

- retracement;

- extension;

- confluence;

- golden-ratio zones.

All methodology outputs must be treated as hypotheses/signals to be validated, not guaranteed truths.

# **7. FUNDAMENTAL & ON-CHAIN INTELLIGENCE**

The system must support:

## **Tokenomics**

- circulating supply;

- total supply;

- maximum supply;

- FDV;

- inflation;

- emissions;

- unlocks;

- vesting;

- staking;

- treasury;

- token utility.

## **Network fundamentals**

Where data is available:

- active addresses;

- transactions;

- fees;

- revenue;

- TVL;

- developer activity;

- network growth.

## **On-chain**

- exchange inflows;

- exchange outflows;

- whale transactions;

- holder distribution;

- accumulation;

- distribution;

- stablecoin flows;

- realized metrics;

- unrealized metrics.

## **Fundamental events**

- token unlocks;

- upgrades;

- governance;

- listings;

- delistings;

- major partnerships;

- protocol incidents;

- regulatory developments.

All external information requires source provenance and timestamps.

# **8. DERIVATIVES & MARKET MICROSTRUCTURE**

Analyse where data is available:

- funding rate;

- funding-rate changes;

- open interest;

- OI changes;

- liquidation clusters;

- long/short ratios;

- futures basis;

- futures premium;

- options;

- implied volatility;

- put/call ratios;

- order-book imbalance;

- bid/ask liquidity;

- large orders;

- market depth;

- estimated slippage.

The system must distinguish:

Raw Data

Calculated Metric

Interpretation

Trading Hypothesis

Do not conflate them.

# **9. NEWS, SENTIMENT & SOCIAL INTELLIGENCE**

Analyse:

- market news;

- project-specific news;

- regulatory events;

- exchange announcements;

- social sentiment;

- narrative momentum;

- sentiment changes;

- abnormal social activity.

Every important claim must contain:

Source

Timestamp

Source Type

Confidence

Relevance

Potential Market Impact

The system must detect stale or contradictory information.

# **10. MARKET REGIME & META-ANALYSIS ENGINE**

This is a critical component.

The engine must attempt to determine:

### **Trend regime**

- bullish;

- bearish;

- sideways.

### **Volatility regime**

- low;

- normal;

- high;

- extreme.

### **Liquidity regime**

- deep;

- normal;

- thin;

- stressed.

### **Risk regime**

- risk-on;

- neutral;

- risk-off.

### **Momentum regime**

- expanding;

- weakening;

- exhausted;

- reversing.

### **Correlation regime**

Evaluate relationships among:

- BTC;

- ETH;

- major altcoins;

- stablecoins;

- traditional risk assets where data is available;

- relevant macro indicators.

### **Additional meta-analysis**

Evaluate:

- BTC dominance;

- market breadth;

- sector rotation;

- narrative rotation;

- stablecoin liquidity;

- exchange flows;

- funding regime;

- OI regime;

- liquidation regime;

- event risk;

- seasonality;

- strategy regime compatibility.

The engine must explicitly identify when the current market regime is unsuitable for a strategy.

# **11. STRATEGY ENSEMBLE**

Do not rely on one universal trading strategy.

Support independent strategy families such as:

- trend following;

- momentum;

- breakout;

- pullback;

- mean reversion;

- swing trading;

- market structure;

- SMC;

- Wyckoff;

- volume-based;

- statistical;

- event-driven;

- volatility-based;

- correlation-based strategies.

Each strategy must have:

Strategy ID

Version

Market

Timeframe

Entry Rules

Exit Rules

Stop Rules

Take-Profit Rules

Risk Rules

Historical Performance

Validation Status

Supported Regimes

Unsupported Regimes

Strategies must be versioned.

Never silently change a strategy while preserving its historical performance statistics.

# **12. SIGNAL ENGINE**

The Signal Engine combines validated analytical outputs.

A signal should contain at minimum:

Signal ID

Asset

Market

Direction

Timeframe

Strategy

Strategy Version

Entry Zone

Stop Loss

Take Profit

Risk/Reward

AI Analytical Confidence

Statistical Validation

Historical Win Rate

Sample Size

Expected Value

Profit Factor

Maximum Drawdown

Market Regime

Supporting Evidence

Conflicting Evidence

Data Timestamp

Signal Expiration

Validation Status

Trade Eligibility

The system must support:

LONG

SHORT

HOLD

WATCH

REJECTED

EXPIRED

# **13. SIGNAL CONFLUENCE**

The system should measure agreement across analytical dimensions.

Example:

Technical BULLISH

Market Structure BULLISH

SMC BULLISH

Wyckoff BULLISH

Volume BULLISH

Derivatives NEUTRAL

On-chain BULLISH

Fundamental BULLISH

Sentiment NEUTRAL

Macro BEARISH

Market Regime BULLISH

The engine should report:

Supporting dimensions

Conflicting dimensions

Missing dimensions

Data-quality concerns

Never turn simple agreement count into an unsupported probability.

# **14. VALIDATION & EVIDENCE ENGINE**

This component is responsible for objective statistical validation.

Support:

- historical backtesting;

- out-of-sample testing;

- walk-forward analysis;

- rolling-window validation;

- regime-specific validation;

- Monte Carlo analysis;

- bootstrap analysis;

- sensitivity analysis;

- parameter robustness;

- transaction-cost modeling;

- slippage modeling;

- funding-cost modeling;

- sample-size analysis.

Metrics should include, where appropriate:

- win rate;

- average win;

- average loss;

- expectancy;

- profit factor;

- Sharpe;

- Sortino;

- Calmar;

- maximum drawdown;

- recovery factor;

- volatility;

- exposure;

- turnover;

- tail loss;

- risk of ruin;

- consecutive losses.

# **15. 75% TRADE-ELIGIBILITY POLICY**

Implement a configurable policy engine.

Default example:

Historical Win Rate \>= 75%

AND

Minimum Sample Size \>= configurable threshold

AND

Out-of-Sample Validation PASS

AND

Walk-Forward Validation PASS

AND

Expected Value \> 0

AND

Profit Factor \>= configurable threshold

AND

Maximum Drawdown \<= configurable threshold

AND

Current Regime Compatible

AND

Data Quality PASS

AND

Liquidity PASS

AND

Risk Engine PASS

Do not hard-code these values into application logic.

Store them as configurable policy parameters.

The Evidence Report must explain exactly which conditions passed or failed.

# **16. EVIDENCE REPORT**

Every serious candidate signal must generate a structured Evidence Report.

Example:

BTC/USDT

LONG

Signal Quality: 89/100

Historical Win Rate: 81.7%

Sample Size: 1,284

Out-of-Sample: 78.9%

Walk-Forward: 79.6%

Expected Value: +1.84R

Profit Factor: 2.17

Maximum Drawdown: 11.8%

TIMEFRAME ALIGNMENT

1D: Bullish

4H: Bullish

1H: Bullish

15M: Bullish

TECHNICAL

EMA: Supporting

RSI: Supporting

MACD: Supporting

Volume: Supporting

MARKET STRUCTURE

BOS: Confirmed

Liquidity Sweep: Confirmed

SMC

Order Block: Confirmed

FVG: Confirmed

WYCKOFF

Accumulation: Possible

DERIVATIVES

Funding: Supporting

OI: Supporting

Liquidations: Neutral

ON-CHAIN

Exchange Flow: Supporting

SENTIMENT

Neutral

CONFLICTING EVIDENCE

High funding

Resistance nearby

MARKET REGIME

Bullish / High Volatility

TRADE ELIGIBILITY

PASS

STATUS

AWAITING HUMAN APPROVAL

The actual implementation must use structured data rather than relying on free-form text.

# **17. DETERMINISTIC RISK ENGINE**

Risk management must be independent of LLM reasoning.

Calculate:

- account risk;

- position size;

- leverage;

- margin;

- stop distance;

- liquidation risk;

- maximum loss;

- portfolio exposure;

- correlated exposure;

- maximum simultaneous positions;

- daily loss;

- weekly loss;

- drawdown;

- volatility-adjusted size.

Example:

Account = \$10,000

Risk = 1%

Maximum theoretical loss = \$100

Entry = \$100,000

Stop = \$98,500

Stop distance = 1.5%

The Risk Engine determines allowable position size.

The AI may recommend parameters, but the deterministic engine validates them.

# **18. HUMAN PARAMETER OVERRIDE**

The human supervisor must be able to modify:

- investment amount;

- position size;

- leverage;

- entry;

- stop loss;

- take profit;

- trailing stop;

- risk percentage;

- margin mode where supported.

However:

### **Human override does NOT bypass safety validation.**

After every material parameter change:

User Change

↓

Risk Recalculation

↓

Liquidation Analysis

↓

Exposure Analysis

↓

Portfolio Risk

↓

Validation

↓

Approval

If the new configuration violates hard risk constraints:

REJECTED BY RISK ENGINE

The system must explain why.

# **19. HUMAN APPROVAL GATE**

No live trade may execute without explicit human approval.

Approval must be explicit and machine-verifiable.

Do not treat:

- viewing a signal;

- opening a page;

- editing a field;

- generating a report;

as approval.

Use a deliberate approval action.

The approval event should record:

User

Timestamp

Signal ID

Strategy Version

Parameters

Risk Configuration

Evidence Version

Approval Action

Approval Source

# **20. EXECUTION ENGINE**

Use an exchange abstraction.

CCXT may be used as the exchange connectivity layer.

Architecture:

Agent Layer

↓

Trade Intent

↓

Risk Engine

↓

Approval Gate

↓

Execution Engine

↓

Exchange Adapter

↓

CCXT

↓

Exchange

AI agents must never directly access exchange credentials or unrestricted trading endpoints.

The Execution Engine must support:

- order creation;

- cancellation;

- modification;

- market orders;

- limit orders;

- stop loss;

- take profit;

- trailing stops where supported;

- partial fills;

- retries;

- idempotency;

- exchange errors;

- network errors;

- reconciliation;

- duplicate-order prevention.

# **21. POSITION MONITORING**

After execution, monitor:

- current price;

- unrealized P&L;

- realized P&L;

- stop distance;

- liquidation distance;

- leverage;

- margin;

- volatility;

- funding;

- market regime;

- thesis validity;

- portfolio exposure.

Possible states:

HOLD

TIGHTEN_STOP

MOVE_TO_BREAKEVEN

PARTIAL_EXIT

TAKE_PROFIT

CLOSE

EMERGENCY_EXIT

Any automated action must pass through deterministic execution and risk policies.

# **22. POST-TRADE INTELLIGENCE**

Every completed trade must be evaluated.

Analyse:

Signal Prediction

Actual Market Behaviour

Entry Quality

Execution Quality

Slippage

Funding

Exit Quality

Strategy Performance

Agent Contributions

Market Regime

Prediction Errors

Track:

### **Strategy performance**

Strategy

Win Rate

Expectancy

Profit Factor

Drawdown

Sharpe

Sortino

Performance by Regime

### **Agent performance**

Agent

Correct Calls

Incorrect Calls

Contribution

Confidence Calibration

Never update performance statistics by modifying historical results.

Historical records must be immutable.

# **23. DATA PROVENANCE**

Every external data point should ideally contain:

Source

Provider

Timestamp

Received Timestamp

Data Type

Asset

Timeframe

Quality Status

Raw/Calculated

Version

Calculated metrics should identify:

Source Data

Calculation Version

Formula/Method

Timestamp

# **24. AUDITABILITY**

The platform must maintain immutable or append-only audit records for:

- signal generation;

- analytical outputs;

- model/version;

- strategy/version;

- risk calculations;

- parameter changes;

- human approval;

- execution;

- exchange response;

- position changes;

- system failures;

- emergency actions.

The system must be capable of answering:

> "Why did this trade happen?"

and reconstructing the complete decision chain.

# **25. SECURITY**

Design for:

- encrypted credentials;

- secrets management;

- least privilege;

- exchange API key restrictions;

- IP restrictions where supported;

- read-only keys for analysis;

- separate trading keys;

- environment separation;

- development/staging/production separation;

- authentication;

- authorization;

- audit logs;

- secure configuration;

- no secrets in prompts;

- no secrets in LLM context;

- no secrets in logs.

AI agents must receive only the minimum information required for their task.

# **26. FAILURE SAFETY**

The system must fail safely.

Examples:

Missing market data

→ DO NOT TRADE

Stale data

→ DO NOT TRADE

Exchange unavailable

→ DO NOT TRADE

Risk engine unavailable

→ DO NOT TRADE

Approval state uncertain

→ DO NOT TRADE

Duplicate execution detected

→ HALT

Unexpected leverage

→ REJECT

Portfolio risk exceeded

→ REJECT

Model unavailable

→ FALLBACK OR HALT

Conflicting critical data

→ FLAG FOR HUMAN REVIEW

The default behavior for uncertainty in live trading should be conservative.

# **27. MODEL ARCHITECTURE**

Do not tightly couple business logic to one LLM provider.

Create a model abstraction:

LLMProvider

├── Primary Model

├── Secondary Model

└── Fallback Model

Models should be replaceable.

The system must track:

Provider

Model

Model Version

Prompt Version

Temperature/configuration

Timestamp

Input Reference

Output

Latency

Token Usage

Evaluation Result

# **28. AGENT OUTPUT CONTRACT**

Every AI agent should produce structured output.

Conceptually:

AgentResult

agent_id

agent_version

analysis_id

asset

timeframe

timestamp

observations

signals

confidence

supporting_evidence

contradicting_evidence

data_sources

limitations

recommended_action

Never depend on arbitrary natural-language responses for critical system decisions.

# **29. AGENT RESPONSIBILITY RULE**

Every agent must have:

Purpose

Inputs

Outputs

Tools

Permissions

Failure Modes

Validation

Evaluation Metrics

An agent must not perform responsibilities belonging to another bounded component.

# **30. SYSTEM OF RECORD**

Define authoritative storage for:

- market data;

- signals;

- strategies;

- backtests;

- evidence reports;

- risk calculations;

- trade intents;

- approvals;

- orders;

- fills;

- positions;

- P&L;

- audit events;

- agent evaluations.

Do not use conversation memory as the authoritative source of trading state.

# **31. TESTING REQUIREMENTS**

The platform must eventually support:

### **Unit tests**

- indicators;

- calculations;

- risk formulas;

- position sizing;

- order construction.

### **Integration tests**

- market data;

- databases;

- exchange adapters;

- execution.

### **Agent tests**

- structured output;

- hallucination detection;

- evidence grounding;

- tool-use correctness.

### **Strategy tests**

- historical validation;

- OOS;

- walk-forward;

- robustness.

### **Risk tests**

- leverage;

- liquidation;

- max exposure;

- stop loss;

- portfolio limits.

### **Failure tests**

- exchange outage;

- stale data;

- network failure;

- duplicate order;

- partial fill;

- model failure.

### **End-to-end tests**

Research → Signal → Validation → Approval → Paper Execution → Monitoring.

Live execution must initially be disabled in development environments.

# **32. DOCUMENTATION REQUIREMENTS**

Maintain:

/docs

/architecture

/adr

/requirements

/agents

/strategies

/risk

/data

/execution

/api

/testing

/operations

Maintain Architecture Decision Records for major choices.

# **33. IMPLEMENTATION DISCIPLINE**

You are working incrementally.

Do NOT attempt to build the complete platform in one response.

Before writing implementation code:

1.  inspect the repository;

2.  identify existing architecture;

3.  identify existing modules;

4.  identify existing dependencies;

5.  identify contradictions;

6.  identify missing requirements;

7.  propose changes;

8.  wait for the appropriate implementation prompt.

Do not overwrite existing functionality unnecessarily.

Do not introduce unnecessary frameworks.

Prefer modularity and explicit interfaces.

# **34. COPILOT DEVELOPMENT RULE**

For every future implementation task:

UNDERSTAND

↓

PLAN

↓

DESIGN

↓

IMPLEMENT

↓

TEST

↓

VALIDATE

↓

DOCUMENT

For each implementation unit, provide:

Objective

Files affected

Architecture impact

Dependencies

Implementation

Tests

Acceptance Criteria

Potential Risks

Remaining Work

# **35. FIRST DELIVERABLE — REQUIREMENTS SPECIFICATION**

For this first stage, DO NOT implement the trading engine.

Instead, create the foundational project specification.

Produce the following artifacts:

## **A. Product Vision**

Clearly define:

- problem;

- target users;

- purpose;

- differentiators;

- operating model.

## **B. Functional Requirements**

Categorize requirements into:

- market intelligence;

- technical analysis;

- quantitative analysis;

- fundamental analysis;

- on-chain;

- derivatives;

- sentiment;

- meta-analysis;

- strategy;

- signal;

- validation;

- evidence;

- risk;

- human approval;

- execution;

- monitoring;

- post-trade;

- administration.

## **C. Non-Functional Requirements**

Define:

- scalability;

- reliability;

- latency;

- security;

- observability;

- auditability;

- maintainability;

- extensibility;

- fault tolerance.

## **D. Agent Responsibility Matrix**

Create a matrix:

Agent

Purpose

Inputs

Outputs

Tools

Permissions

Dependencies

Failure Modes

## **E. Trading Lifecycle**

Document the complete lifecycle from:

Market Data

→ Analysis

→ Signal

→ Validation

→ Evidence

→ Risk

→ Human Approval

→ Execution

→ Monitoring

→ Closure

→ Post-Trade Analysis

## **F. Signal Lifecycle State Machine**

Define all states and valid transitions.

## **G. Risk Policy**

Define:

- hard limits;

- configurable limits;

- user overrides;

- approval requirements;

- veto conditions.

## **H. Evidence Model**

Define exactly how evidence is stored and linked to source data.

## **I. Operating Modes**

Define Research, Paper, and Live modes.

## **J. Security Model**

Define:

- identity;

- authorization;

- secret management;

- exchange permissions;

- agent permissions.

## **K. Audit Model**

Define what must be recorded for every trade decision.

## **L. Glossary**

Define domain terms consistently.

# **36. IMPORTANT DESIGN QUESTION**

During this requirements phase, identify unresolved decisions rather than silently making assumptions.

Create a section:

## **OPEN ARCHITECTURAL DECISIONS**

For every unresolved decision include:

Decision

Options

Advantages

Disadvantages

Recommendation

Impact

Potential decisions include:

- supported exchanges;

- spot vs futures;

- perpetuals;

- options;

- supported assets;

- data providers;

- timeframes;

- database;

- event streaming;

- LLM providers;

- vector database;

- backtesting engine;

- deployment model;

- cloud provider;

- authentication;

- alerting channels.

Do not prematurely implement these.

# **37. CRITICAL PRODUCT REQUIREMENT**

The system must optimize for:

EVIDENCE \> OPINION

VALIDATION \> CONFIDENCE

RISK CONTROL \> PROFIT MAXIMIZATION

REPRODUCIBILITY \> BLACK-BOX BEHAVIOR

HUMAN CONTROL \> AUTONOMOUS EXECUTION

The objective is not to maximize the number of trades.

The objective is to identify **high-quality, statistically defensible opportunities while minimizing unnecessary risk and preventing unsupported decisions**.

# **38. FINAL REQUIREMENT**

Do not claim that the system can guarantee profitable trades.

Do not claim that a 75% historical win rate guarantees future performance.

Use language such as:

- historically validated;

- statistically supported;

- evidence-backed;

- trade-eligible;

- high-quality setup;

- favorable historical expectancy.

Avoid:

- guaranteed profit;

- guaranteed success;

- certain prediction;

- risk-free trade.

# **39. YOUR TASK NOW**

For this conversation, act as the **Principal Architect**.

Do NOT start implementing trading functionality.

First produce:

1.  Executive Product Vision

2.  Product Scope

3.  Functional Requirements

4.  Non-Functional Requirements

5.  Agent/Service Responsibility Matrix

6.  Trading Lifecycle

7.  Signal Lifecycle State Machine

8.  Risk-Control Model

9.  Evidence Model

10. Operating Modes

11. Security Model

12. Audit Model

13. Key Domain Entities

14. Open Architectural Decisions

15. Recommended Technology Boundaries

16. Initial Repository/Documentation Structure

17. Architectural Risks

18. Acceptance Criteria for this foundation phase

The resulting specification will become the authoritative foundation for subsequent implementation prompts.

Do not invent implementation details that have not yet been decided.

Do not write production trading code in this phase.

At the end, provide a concise:

**"FOUNDATION COMPLETE — READY FOR CHAT 2: ENTERPRISE SYSTEM ARCHITECTURE"**

only if all requested artifacts have been addressed.
