# Chat 3 — Multi-AI Agent & Trading Intelligence Architecture

> Full source-derived Chat 3 content from the uploaded Master Playbook v2.2 DOCX. This is not a summary. Source Markdown lines 8795–12311 of the complete conversion.

---

Master Prompt — Chat 3

V2.1 INLINE UPGRADE - CHAT 3 MULTI-AI AGENT & TRADING INTELLIGENCE ARCHITECTURE

Purpose: formalize the multi-agent intelligence system as a supervised research team with explicit permissions, structured outputs, adversarial review, and no direct execution authority.

Retained Scope

Preserve technical, fundamental, quantitative, market structure, derivatives, on-chain, sentiment, macro, order-flow, regime, strategy, signal aggregator, risk, and human supervisor responsibilities.

Preserve the rule that deterministic engines calculate facts while LLM agents interpret, compare, explain, and propose.

v2.1 Corrections and Enhancements

Add formal Agent Responsibility Matrix inside Chat 3.

Add Agent Handoff Matrix for agent-to-agent and agent-to-service transitions.

Promote Devil's Advocate / Counter-Thesis Agent to an explicit role that challenges trade theses, highlights failure conditions, and cannot approve or execute trades.

Add Agent Independence Analysis to prevent correlated agents from being counted as independent evidence.

Add model routing, prompt versioning, memory access limits, tool permission scopes, and failure behavior per agent.

Chat 3 Required Contracts

AgentDefinition, AgentResult, AgentPermissionProfile, AgentToolAccess, AgentHandoff, AgentEvaluation, AdversarialAssessment, AgentIndependenceReport, ModelRoutingDecision.

Acceptance Criteria

Every agent has purpose, inputs, outputs, tools, permissions, dependencies, failure modes, validation, and evaluation metrics.

No agent can directly call exchange trading endpoints or bypass risk/human approval.

Multi-agent agreement cannot be treated as statistical proof unless independence and evidence quality are established.

# **Enterprise-Grade Supervised Autonomous Crypto Trading Platform**

## **GitHub Copilot Master Prompt — Chat 3**

### **Multi-AI Trading Intelligence, Agent Team & Decision Architecture**

You are continuing the implementation planning for the enterprise-grade supervised autonomous crypto trading platform defined in:

- Chat 1 — Product Requirements & System Constitution

- Chat 2 — Enterprise System Architecture

Those documents are authoritative.

Do not contradict them unless you identify a genuine architectural flaw. If you identify one, document it as an Architecture Decision rather than silently changing the design.

You are acting as the **Principal Software Architect, Quantitative Trading Systems Architect, AI Agent Architect, Security Architect, and Senior Engineering Lead** for this project.

We are designing and incrementally implementing an **enterprise-grade, AI-powered, supervised crypto market analysis, trading intelligence, and trading execution platform**.

This is NOT a simple crypto trading bot.

It is a **multi-agent trading intelligence and supervised execution platform** whose purpose is to analyse cryptocurrency markets using multiple independent analytical disciplines, evaluate trading opportunities using reproducible historical evidence, present transparent trading signals to a human supervisor, and execute trades only after explicit approval and deterministic risk validation.

The system must be designed so that AI assists with analysis and reasoning while **critical financial calculations, risk controls, permissions, execution constraints, and transaction integrity remain deterministic and auditable**.

# **1. CORE CONCEPT**

The system should behave conceptually like a professional trading desk.

Instead of:

User

↓

One AI

↓

BUY

build:

MARKET

│

▼

MARKET CONTEXT

│

┌──────────────┼──────────────┐

│ │ │

▼ ▼ ▼

Technical Fundamental Quantitative

Analyst Analyst Analyst

│ │ │

├──────────────┼──────────────┤

│ │ │

▼ ▼ ▼

Market Derivatives On-Chain

Structure Analyst Analyst

│ │ │

├──────────────┼──────────────┤

│ │ │

▼ ▼ ▼

Sentiment Macro Order Flow

Analyst Analyst Analyst

│ │ │

└──────────────┼──────────────┘

▼

MARKET REGIME ENGINE

│

▼

STRATEGY EVALUATION

│

▼

MULTI-AGENT DEBATE

│

▼

SIGNAL AGGREGATOR

│

▼

STATISTICAL VALIDATION

│

▼

EVIDENCE REPORT

│

▼

RISK ENGINE

│

▼

HUMAN TRADER

# **2. MOST IMPORTANT ARCHITECTURAL RULE**

Do NOT implement every analytical component as an LLM.

Use three categories.

## **Category A — Deterministic Engines**

These should calculate facts.

Examples:

- RSI;

- EMA;

- SMA;

- MACD;

- ATR;

- ADX;

- Bollinger Bands;

- VWAP;

- Fibonacci levels;

- volume profile;

- volatility;

- market structure;

- order-book imbalance;

- funding;

- open interest;

- liquidation statistics;

- correlations;

- statistical metrics;

- position sizing;

- backtesting;

- risk calculations.

These components should be deterministic and testable.

# **3. CATEGORY B — AI ANALYSTS**

AI agents interpret deterministic outputs and external information.

Examples:

Technical Analysis Agent

Fundamental Analysis Agent

On-Chain Intelligence Agent

Derivatives Intelligence Agent

Sentiment Agent

Macro Agent

Market Structure Agent

SMC Analyst

Wyckoff Analyst

Strategy Analyst

Market Regime Analyst

AI agents should produce structured hypotheses and explanations.

They must reference the underlying evidence.

# **4. CATEGORY C — GOVERNANCE / DECISION AGENTS**

These agents coordinate or challenge analytical conclusions.

Examples:

Research Coordinator

Confluence Analyst

Contrarian / Devil's Advocate

Strategy Selector

Signal Synthesizer

Evidence Reviewer

Trade Thesis Reviewer

These agents do NOT have unrestricted execution permissions.

# **5. PROPOSED AGENT ORGANIZATION**

Design the system around the following logical teams.

TEAM 1 — DATA & MARKET INTELLIGENCE

TEAM 2 — TECHNICAL & MARKET STRUCTURE

TEAM 3 — FUNDAMENTAL & ON-CHAIN

TEAM 4 — DERIVATIVES & MARKET MICROSTRUCTURE

TEAM 5 — SENTIMENT & MACRO

TEAM 6 — STRATEGY RESEARCH

TEAM 7 — META-ANALYSIS & REGIME

TEAM 8 — DEBATE & CHALLENGE

TEAM 9 — SIGNAL & EVIDENCE

TEAM 10 — RISK

TEAM 11 — EXECUTION

TEAM 12 — POST-TRADE INTELLIGENCE

# **6. TEAM 1 — DATA & MARKET INTELLIGENCE**

This team does not make trading decisions.

Its purpose is to establish a reliable market context.

Components:

Market Data Collector

Data Quality Engine

Market Context Builder

Cross-Exchange Aggregator

Feature Calculator

Outputs:

MarketContext

DataQualityReport

MarketSnapshot

# **7. MARKET CONTEXT BUILDER**

Create a canonical MarketContext.

It should contain:

Asset

Trading Pair

Exchange

Timestamp

OHLCV

Volume

Order Book

Trades

Volatility

ATR

Liquidity

Funding Rate

Open Interest

Liquidations

Basis

Technical Features

Market Structure

On-Chain Metrics

Fundamentals

News

Sentiment

Macro Context

Market Regime

Data Quality

The context should support multiple timeframes.

# **8. MULTI-TIMEFRAME ANALYSIS**

The system must not analyze only one timeframe.

Support configurable timeframe hierarchies such as:

Macro:

1W

1D

Higher Timeframe:

4H

Execution Context:

1H

Entry:

15M

5M

Optional:

1M

Do not hard-code this exact hierarchy.

Make it configurable by strategy.

The system must distinguish:

Higher-Timeframe Bias

Middle-Timeframe Structure

Lower-Timeframe Entry

# **9. TEAM 2 — TECHNICAL & MARKET STRUCTURE**

Design separate analytical modules.

## **Classical Technical Analyst**

Analyze:

- SMA;

- EMA;

- RSI;

- MACD;

- Stochastic;

- CCI;

- ADX;

- ATR;

- Bollinger Bands;

- Ichimoku;

- VWAP;

- OBV.

## **Price Action Analyst**

Analyze:

- trend;

- support;

- resistance;

- breakout;

- rejection;

- consolidation;

- range;

- volatility expansion;

- volatility compression.

## **Market Structure Analyst**

Analyze:

- HH;

- HL;

- LH;

- LL;

- BOS;

- CHoCH;

- swing structure;

- liquidity areas.

# **10. SMART MONEY CONCEPTS ANALYST**

Create an SMC analytical capability.

Support concepts such as:

Liquidity Pools

Liquidity Sweep

Order Blocks

Breaker Blocks

Fair Value Gaps

Displacement

Premium / Discount

Inducement

Market Structure Shift

Important:

Different practitioners define SMC concepts differently.

Therefore:

1.  Define precise operational rules.

2.  Version those definitions.

3.  Backtest them.

4.  Do not allow an LLM to arbitrarily redefine them.

5.  Store methodology version.

Example:

SMC_RULESET_V1

SMC_RULESET_V2

# **11. WYCKOFF ANALYST**

Support:

Accumulation

Distribution

Markup

Markdown

Spring

Upthrust

SOS

SOW

PS

SC

AR

ST

Do not rely solely on an LLM to identify Wyckoff phases.

Use deterministic price/volume features where possible.

Then allow the AI analyst to interpret the pattern.

# **12. FIBONACCI ANALYST**

Support:

Retracement

Extension

Projection

Confluence

The system should identify potential relationships with:

- market structure;

- order blocks;

- support/resistance;

- volume;

- liquidity.

Do not treat Fibonacci levels as inherently predictive.

Their value must be empirically evaluated.

# **13. VOLUME & ORDER FLOW ANALYSIS**

Create deterministic capabilities for:

Volume Profile

VWAP

OBV

Volume Delta where available

Cumulative Delta where available

Order Book Imbalance

Bid/Ask Imbalance

Liquidity Depth

Large Orders

Trade Flow

The system should distinguish:

Observed Order Flow

from:

AI Interpretation

# **14. TEAM 3 — FUNDAMENTAL & ON-CHAIN**

Create:

## **Fundamental Analyst**

Analyze:

Tokenomics

Supply

FDV

Inflation

Unlocks

Vesting

Utility

Treasury

Staking

Protocol Revenue

Protocol Fees

TVL

Developer Activity

Network Growth

## **On-Chain Analyst**

Analyze:

Active Addresses

Transactions

Exchange Inflows

Exchange Outflows

Whale Activity

Holder Distribution

Stablecoin Flows

Accumulation

Distribution

Realized Metrics

The system must account for asset-specific differences.

A metric useful for Bitcoin may not be meaningful for every altcoin.

# **15. FUNDAMENTAL EVENT ANALYSIS**

Detect events such as:

Token Unlock

Protocol Upgrade

Exchange Listing

Exchange Delisting

Governance Vote

Major Partnership

Security Incident

Chain Upgrade

Regulatory Event

Major Funding Event

Events should have:

Event

Timestamp

Source

Reliability

Expected Impact

Actual Impact

# **16. TEAM 4 — DERIVATIVES & MICROSTRUCTURE**

Analyze:

Funding Rate

Funding Trend

Open Interest

OI Change

Liquidations

Long/Short Ratios

Basis

Futures Premium

Options

Implied Volatility

Put/Call

Order Book

Market Depth

The system should identify situations such as:

Price ↑ + OI ↑

Price ↑ + OI ↓

Price ↓ + OI ↑

Price ↓ + OI ↓

and interpret them within context rather than treating them as universal signals.

# **17. TEAM 5 — SENTIMENT & MACRO**

## **Sentiment Analyst**

Analyze:

- news;

- social sentiment;

- sentiment acceleration;

- narrative momentum;

- abnormal activity;

- fear/greed measures where reliable.

## **Macro Analyst**

Analyze relevant:

- interest rates;

- inflation;

- dollar strength;

- liquidity;

- risk appetite;

- equity markets;

- commodities;

- major macroeconomic events.

The system must support configurable macro inputs.

# **18. SOURCE TRUST MODEL**

Not all sources are equally reliable.

Create a source trust framework.

Example:

Tier 1

Official Exchange

Official Project

Government / Regulatory

Primary Blockchain Data

Tier 2

Established Data Provider

Established Research Organization

Tier 3

Major News Organization

Tier 4

Social Media

Anonymous Accounts

Unverified Sources

Do not blindly assign universal trust scores.

Make the source reliability framework configurable.

# **19. TEAM 6 — STRATEGY RESEARCH**

The strategy layer must remain separate from raw analysis.

A strategy consumes:

Market Features

Analytical Signals

Market Regime

Risk Constraints

and produces:

Trade Hypothesis

Examples:

Trend Following

Momentum

Breakout

Pullback

Mean Reversion

Swing

SMC

Wyckoff

Volume

Statistical Arbitrage

Event Driven

Volatility

Strategies must be versioned.

# **20. STRATEGY COMPATIBILITY**

Each strategy must declare:

Supported Markets

Supported Timeframes

Supported Regimes

Preferred Volatility

Liquidity Requirements

Minimum Data

Risk Characteristics

Example:

Mean Reversion

Good:

Range-bound

Stable volatility

Bad:

Strong directional breakout

Extreme volatility

The system must reject strategies incompatible with the current regime.

# **21. TEAM 7 — MARKET REGIME ENGINE**

This is one of the most important components.

Determine:

Trend Regime

Volatility Regime

Liquidity Regime

Momentum Regime

Risk Regime

Correlation Regime

Market Breadth

BTC Dominance

Sector Rotation

Narrative Regime

Derivatives Regime

Possible classification:

BULL TREND

BEAR TREND

RANGE

HIGH VOLATILITY

LOW VOLATILITY

RISK ON

RISK OFF

TRANSITION

UNKNOWN

Do not force a classification when evidence is insufficient.

Allow:

UNKNOWN / LOW CONFIDENCE

# **22. REGIME DETECTION MUST BE EMPIRICAL**

Where possible, use measurable features.

Do not allow the LLM to simply say:

> "The market feels bullish."

Instead:

Feature

Value

Threshold

Classification

Evidence

Then AI interprets the regime.

# **23. TEAM 8 — MULTI-AGENT DEBATE**

This is where the architecture becomes substantially stronger than a conventional trading bot.

Do not immediately aggregate all agent outputs.

Instead use:

Independent Analysis

↓

Initial Trade Thesis

↓

Contrarian Review

↓

Evidence Challenge

↓

Thesis Revision

↓

Final Synthesis

# **24. DEVIL'S ADVOCATE AGENT**

Create a dedicated Contrarian Agent.

Its job is NOT to generate trades.

Its job is to ask:

Why is this trade wrong?

What evidence contradicts it?

Which assumptions are weak?

Is the setup overfit?

Is the market regime incompatible?

Is there a liquidity problem?

Is the signal based on correlated indicators?

Could the apparent confluence be redundant?

Is the historical sample adequate?

Could this be a false breakout?

What would invalidate the thesis?

This agent should actively attempt to reject weak setups.

# **25. CORRELATED-EVIDENCE DETECTION**

This is critical.

Do not count:

RSI bullish

MACD bullish

EMA bullish

as three independent pieces of evidence.

They may all reflect the same underlying momentum.

The system should classify evidence into groups.

Example:

Momentum

Trend

Volume

Market Structure

Liquidity

Derivatives

Fundamentals

On-chain

Sentiment

Macro

Calculate confluence with awareness of dependency.

Avoid naive:

10 signals = 10 votes

# **26. EVIDENCE WEIGHTING**

Design a transparent evidence model.

Each evidence item should contain:

Evidence ID

Category

Observation

Direction

Strength

Source

Timestamp

Method

Independence Group

Reliability

Historical Relevance

Example:

RSI bullish

Category = Momentum

Independence Group = Momentum

EMA bullish

Category = Trend

Independence Group = Trend

Funding negative

Category = Derivatives

Independence Group = Derivatives

# **27. CONFLUENCE ENGINE**

Create a deterministic/constrained Confluence Engine.

It should calculate:

Evidence Coverage

Evidence Strength

Evidence Independence

Contradiction Score

Data Quality

Regime Compatibility

Do not represent this as a probability unless statistically calibrated.

# **28. SIGNAL SYNTHESIS**

The Signal Synthesizer receives:

All Agent Results

Market Regime

Strategy Results

Evidence

Contradictions

Historical Validation

and generates:

Candidate Signal

It must explain:

Why LONG?

Why SHORT?

Why NOT TRADE?

# **29. "NO TRADE" MUST BE A FIRST-CLASS OUTCOME**

The system must be comfortable saying:

NO TRADE

Reasons may include:

Insufficient Evidence

Conflicting Evidence

Poor Risk/Reward

Bad Market Regime

Insufficient Sample

Poor Liquidity

High Event Risk

Data Quality Failure

Strategy Incompatibility

Statistical Validation Failure

Optimize for decision quality, not trade frequency.

# **30. SIGNAL CLASSIFICATION**

Use explicit states:

WATCH

CANDIDATE

VALIDATING

VALIDATED

TRADE-ELIGIBLE

HUMAN REVIEW

APPROVED

REJECTED

EXPIRED

INVALIDATED

# **31. SIGNAL QUALITY SCORE**

Create a composite quality score, but do not call it probability.

Potential dimensions:

Technical Quality

Market Structure Quality

Fundamental Quality

On-Chain Quality

Derivatives Quality

Sentiment Quality

Macro Quality

Regime Compatibility

Evidence Independence

Historical Validation

Risk/Reward

Data Quality

The formula must be deterministic and versioned.

# **32. STATISTICAL PROBABILITY**

If the system eventually presents:

Estimated Probability

it must be statistically calibrated.

Possible methods:

- empirical conditional frequency;

- Bayesian models;

- logistic regression;

- calibrated classifiers;

- bootstrapping;

- probability calibration.

An LLM-generated number is NOT an acceptable probability.

# **33. AGENT CONFIDENCE**

Keep separate:

AI Confidence

from:

Statistical Probability

Example:

Technical Agent Confidence = 0.88

Historical Conditional Win Rate = 0.79

Calibrated Probability = 0.76

These must never be silently combined.

# **34. AGENT DISAGREEMENT**

The system must preserve disagreement.

Example:

Technical LONG

Fundamental LONG

On-chain LONG

Derivatives SHORT

Macro NEUTRAL

Sentiment LONG

Contrarian SHORT

Do not hide this disagreement behind one final score.

The Evidence Report must show it.

# **35. ANALYTICAL CONSENSUS**

Create a consensus object:

ConsensusResult

bullish_agents

bearish_agents

neutral_agents

supporting_evidence

contradicting_evidence

independent_support

independent_conflict

consensus_status

Possible:

STRONG_CONSENSUS

MODERATE_CONSENSUS

MIXED

CONFLICTED

INSUFFICIENT_DATA

# **36. STRATEGY ENSEMBLE**

Allow multiple strategies to evaluate the same market.

Example:

Trend Strategy PASS

Breakout Strategy PASS

SMC Strategy PASS

Wyckoff WATCH

Mean Reversion FAIL

The system can then identify:

Strategy Convergence

But again:

**Strategy convergence is evidence, not guaranteed probability.**

# **37. META-ANALYSIS**

Create a dedicated Meta-Analysis layer.

It should ask:

Which strategies currently work?

Which strategies currently fail?

Which indicators are redundant?

Which market regimes produce the best performance?

Which assets behave differently?

Are signals concentrated in one methodology?

Is the current signal consistent across independent analytical families?

Has strategy performance degraded?

Is the apparent edge statistically stable?

# **38. META-ANALYSIS OF THE ANALYSTS**

The platform should eventually evaluate the agents themselves.

For each agent track:

Prediction

Actual Outcome

Correctness

Confidence

Calibration

Market Regime

Asset

Timeframe

Strategy

This allows questions such as:

Which analyst is strongest in trending markets?

Which analyst performs poorly during high volatility?

Does the fundamental analyst improve long-term trades?

Does the derivatives analyst improve short-term entries?

# **39. AGENT PERFORMANCE MUST NOT AUTOMATICALLY CONTROL LIVE TRADING**

Agent performance may influence future weighting only through a controlled, versioned policy.

Never allow:

Agent says something

→ system automatically increases its authority

Instead:

Performance Analysis

↓

Evaluation

↓

Policy Proposal

↓

Human/Controlled Deployment

↓

New Version

# **40. AGENT MEMORY**

Do NOT create uncontrolled persistent memory for trading decisions.

Use structured historical records.

Potential knowledge sources:

Previous Trades

Previous Signals

Strategy Research

Post-Trade Reviews

Market Regime History

Agent Evaluation

Every retrieved historical example must include provenance.

# **41. RAG**

Use RAG for:

- research papers;

- methodology;

- strategy documentation;

- asset documentation;

- exchange documentation;

- internal research.

Do not use RAG as a substitute for live market data.

# **42. PROMPT ARCHITECTURE**

Each agent should have:

System Prompt

Role Definition

Allowed Tools

Input Contract

Output Contract

Reasoning Policy

Evidence Requirements

Safety Rules

Prompts must be version-controlled.

Example:

technical-agent-v1.0

technical-agent-v1.1

# **43. AGENT TOOL PERMISSIONS**

Define explicit tool scopes.

Example:

Technical Agent:

READ market data

READ indicators

READ structure

NO trading

Fundamental Agent:

READ project data

READ news

READ on-chain

NO trading

Strategy Agent:

READ analytical outputs

READ strategy registry

READ historical validation

NO trading

Risk Agent:

READ account

READ portfolio

READ market

CALCULATE risk

NO unrestricted trading

Execution Agent:

READ approved TradeIntent

EXECUTE only permitted order

# **44. AGENT COMMUNICATION**

Agents should communicate using structured objects.

Do NOT rely on agents reading arbitrary previous LLM conversations.

Use:

AnalysisResult

EvidenceItem

RegimeResult

StrategyResult

ConsensusResult

ValidationResult

RiskAssessment

TradeIntent

# **45. AGENT ORCHESTRATION**

Use LangGraph as the orchestration layer.

Support:

Parallel Execution

Conditional Routing

Retries

Timeouts

Human Interrupts

Checkpoints

State Persistence

Workflow Replay

Example:

START

↓

Market Context

↓

Parallel Analysts

├── Technical

├── Fundamental

├── On-chain

├── Derivatives

├── Sentiment

├── Macro

└── Structure

↓

Regime

↓

Strategy Evaluation

↓

Consensus

↓

Contrarian Challenge

↓

Synthesis

↓

Validation

↓

Evidence

↓

Risk

↓

Human

# **46. ADAPTIVE ANALYSIS**

Do not always execute every agent at maximum depth.

Introduce analysis tiers.

## **Tier 1 — Fast Scan**

Used for broad market scanning.

Price

Volume

Trend

Volatility

Funding

OI

Basic Sentiment

## **Tier 2 — Candidate Analysis**

For promising setups.

Add:

Market Structure

SMC

Wyckoff

Derivatives

On-chain

Fundamentals

## **Tier 3 — Deep Validation**

For trade-eligible candidates.

Add:

Historical validation

Regime testing

Strategy ensemble

Robustness

Monte Carlo

Detailed evidence

Contrarian review

This controls cost and latency.

# **47. MARKET SCANNER**

Design a scanner that can evaluate many assets.

Pipeline:

Universe

↓

Liquidity Filter

↓

Data Quality Filter

↓

Fast Scan

↓

Candidate Ranking

↓

Deep Analysis

↓

Validation

Do not run expensive deep AI analysis on every asset continuously.

# **48. ASSET UNIVERSE**

Make the universe configurable.

Potential filters:

Volume

Liquidity

Market Cap

Exchange Availability

Spread

Volatility

Data Availability

Trading Pair

Avoid illiquid assets unless explicitly enabled.

# **49. SIGNAL EXPIRATION**

Every signal must have a validity window.

Example:

Signal generated:

10:00

Valid until:

11:00

The exact duration must depend on strategy/timeframe.

If expired:

EXPIRED

It must require fresh analysis to become active again.

# **50. THESIS INVALIDATION**

Every signal must explicitly define:

Thesis

Invalidation Conditions

Examples:

BOS fails

Support breaks

Funding changes materially

Expected liquidity sweep does not occur

Macro event invalidates setup

Data quality deteriorates

# **51. EVENT RISK**

The system should identify upcoming events.

Examples:

Economic releases

Central bank decisions

ETF decisions

Token unlocks

Major protocol upgrades

Exchange announcements

The strategy engine must determine whether event risk:

Allows Trade

Requires Caution

Blocks Trade

according to policy.

# **52. EVIDENCE TRACEABILITY**

Every signal claim must be traceable.

Example:

Signal

↓

Evidence Report

↓

Evidence Item

↓

Analysis Result

↓

Feature

↓

Raw Data

↓

Provider

This is essential for auditability.

# **53. REPRODUCIBILITY**

Given:

Signal ID

Data Snapshot

Strategy Version

Agent Versions

Prompt Versions

Configuration Version

Model Version

the system should be able to reconstruct the analysis as closely as technically possible.

# **54. DECISION RECORD**

Create a structured:

DecisionRecord

containing:

Market Context

Analytical Results

Agent Disagreements

Strategy Results

Regime

Evidence

Validation

Risk

Final Recommendation

This becomes the primary explanation artifact.

# **55. NO BLACK-BOX FINAL SCORE**

Avoid:

AI Score = 87

Therefore BUY

Instead:

Technical Evidence

\+

Structure Evidence

\+

Derivatives Evidence

\+

Fundamental Evidence

\+

Regime Compatibility

\+

Historical Validation

\-

Contradictions

\-

Risk Constraints

=

Trade Eligibility

Each component must remain inspectable.

# **56. DECISION HIERARCHY**

The final decision pipeline must be:

RAW DATA

↓

FEATURES

↓

ANALYTICAL OBSERVATIONS

↓

AI INTERPRETATIONS

↓

MARKET REGIME

↓

STRATEGY HYPOTHESES

↓

CONTRARIAN CHALLENGE

↓

SIGNAL

↓

STATISTICAL VALIDATION

↓

EVIDENCE

↓

RISK

↓

HUMAN APPROVAL

↓

EXECUTION

No stage may silently skip a higher-level control.

# **57. TRADING DECISION TYPES**

The AI system should be able to produce:

LONG CANDIDATE

SHORT CANDIDATE

WATCH

NO TRADE

WAIT FOR CONFIRMATION

INVALIDATED

Do not force every market condition into LONG/SHORT.

# **58. SIGNAL PRIORITY**

Signals can be ranked:

LOW

MEDIUM

HIGH

CRITICAL

but ranking must not override risk controls.

# **59. HUMAN-READABLE REASONING**

The Evidence Report should explain:

### **Thesis**

Why the setup exists.

### **Supporting Evidence**

What supports it.

### **Contradicting Evidence**

What challenges it.

### **Historical Evidence**

How similar setups performed.

### **Regime**

Why the current environment is suitable or unsuitable.

### **Risk**

What can go wrong.

### **Invalidation**

What would make the thesis invalid.

### **Final Status**

Why it is or is not trade-eligible.

# **60. IMPORTANT STATISTICAL RULE**

A signal cannot say:

SUCCESS RATE = 82%

unless the system can answer:

82% of what?

Which strategy?

Which asset?

Which timeframe?

Which market regime?

What entry definition?

What exit definition?

What stop?

What take profit?

What sample size?

What historical period?

What fees?

What slippage?

Was it out-of-sample?

Was it walk-forward validated?

Was there look-ahead bias?

Was there data leakage?

If these questions cannot be answered:

STATISTICAL VALIDATION = INSUFFICIENT

# **61. MULTI-AGENT DECISION QUALITY**

The system should optimize for:

Independent Evidence

\+

Historical Validation

\+

Regime Compatibility

\+

Risk/Reward

\+

Robustness

not:

Number of Agents Agreeing

# **62. AGENT HALLUCINATION DEFENSE**

If an agent claims:

"Funding is strongly negative."

the system must verify the actual funding data.

If an agent claims:

"Historical win rate is 81%."

the system must retrieve the actual validation result.

Agents must never be trusted as the source of numerical truth.

# **63. AI OUTPUT VALIDATION**

Every agent output must pass:

Schema Validation

Evidence Validation

Source Validation

Timestamp Validation

Numerical Consistency

Permission Validation

Invalid outputs should be rejected or flagged.

# **64. AGENT FAILURE**

Define behavior when an agent fails.

Examples:

Technical Agent unavailable

→ continue if policy permits

Fundamental Agent unavailable

→ mark fundamental analysis unavailable

Risk Agent unavailable

→ LIVE TRADING BLOCKED

Validation Engine unavailable

→ TRADE-ELIGIBILITY BLOCKED

Critical market data unavailable

→ ANALYSIS BLOCKED

# **65. AGENT HEALTH**

Track:

Availability

Latency

Failure Rate

Schema Failure

Tool Failure

Evidence Quality

Historical Accuracy

Calibration

Cost

# **66. MODEL ROUTING**

Do not use the most expensive model for every task.

Design model routing.

Example:

Fast Model:

Market classification

Summarization

Simple interpretation

Advanced Model:

Complex synthesis

Contrarian reasoning

Deep research

Deterministic Engine:

Risk

Statistics

Indicators

Backtesting

Model routing must be configurable.

# **67. MODEL ENSEMBLE**

Where justified, evaluate multiple models for high-value analysis.

For example:

Model A → Analysis

Model B → Critique

Model C → Synthesis

But do not assume multiple LLMs create statistical independence.

They may share similar biases.

# **68. AGENT INDEPENDENCE**

For important signals, preserve independent analytical paths.

Example:

Price/Volume path

Derivatives path

On-chain path

Fundamental path

Sentiment path

Do not let one early LLM conclusion contaminate all subsequent agents.

# **69. INFORMATION FLOW CONTROL**

Prefer:

Raw Evidence

→ Independent Agents

rather than:

Agent A

→ Agent B

→ Agent C

→ Agent D

unless sequential reasoning is genuinely required.

This reduces confirmation cascades.

# **70. CONFIRMATION BIAS DEFENSE**

Agents should not be told:

"Find evidence supporting this LONG trade."

Instead ask:

"Evaluate whether a LONG hypothesis is supported or rejected."

For every candidate trade require both:

Bull Case

Bear Case

# **71. BULL / BEAR THESIS**

Create:

BullCase

BearCase

Each contains:

Evidence

Assumptions

Catalysts

Invalidation

Risks

Historical Analogues

The system should compare them.

# **72. TRADE THESIS SCORECARD**

Create a structured scorecard:

Market Regime

Trend

Momentum

Structure

Liquidity

Volume

Derivatives

On-chain

Fundamentals

Sentiment

Macro

Strategy Fit

Historical Evidence

Risk/Reward

Contradictions

The scorecard is explanatory.

It must not become an arbitrary probability generator.

# **73. PROFESSIONAL TRADER BEHAVIOR**

The system should emulate disciplined behavior:

Wait for setup

Wait for confirmation

Reject poor risk/reward

Avoid revenge trading

Avoid overtrading

Respect stop loss

Respect risk limits

Avoid emotional decisions

Avoid unsupported predictions

The AI should explicitly identify when:

NO EDGE

exists.

# **74. OVERTRADING CONTROL**

Implement:

Maximum Signals

Maximum Trades

Cooldown Period

Duplicate Signal Detection

Repeated Entry Prevention

Daily Trade Limit

Strategy Exposure Limit

All configurable.

# **75. TRADE DUPLICATION**

If multiple agents/strategies produce essentially the same opportunity:

BTC LONG Strategy A

BTC LONG Strategy B

BTC LONG Strategy C

do not automatically treat them as three independent opportunities.

Detect correlated/duplicate signals.

# **76. PORTFOLIO-AWARE ANALYSIS**

Signal evaluation should eventually consider:

Existing Positions

Existing Exposure

Correlation

Sector Exposure

BTC Exposure

Stablecoin Exposure

Strategy Exposure

Exchange Exposure

A great individual trade may still be a bad portfolio trade.

# **77. PORTFOLIO CONSTRAINT**

Signal eligibility should eventually include:

Individual Trade Quality

\+

Portfolio Compatibility

not just:

Individual Trade Quality

# **78. AGENT DECISION GRAPH**

Design a graph similar to:

START

│

▼

Market Context

│

├─────────────┬─────────────┬─────────────┐

▼ ▼ ▼ ▼

Technical Fundamental Derivatives Sentiment

│ │ │ │

├─────────────┴─────────────┴─────────────┤

│

▼

Market Regime

│

▼

Strategy Evaluation

│

▼

Bull Thesis + Bear Thesis

│

▼

Contrarian Challenge

│

▼

Evidence Reconciliation

│

▼

Signal Synthesis

│

▼

Statistical Validation

│

▼

Evidence Report

│

▼

Risk Engine

│

▼

Human Approval

# **79. RESEARCH VS LIVE AGENTS**

Clearly separate:

Research Agents

from:

Live Trading Agents

Research agents can perform expensive analysis.

Live agents must have strict latency and permission constraints.

# **80. LIVE TRADING AGENT RESTRICTION**

The live trading workflow should never require an LLM to make a last-second discretionary decision about:

Maximum Loss

Position Size

Risk Limit

Permission

Those decisions belong to deterministic policy engines.

# **81. AGENT EVALUATION FRAMEWORK**

Create an evaluation framework.

For each agent evaluate:

Accuracy

Precision

Recall where applicable

Calibration

False Positive Rate

False Negative Rate

Evidence Quality

Consistency

Latency

Cost

Robustness

Metrics should be task-specific.

# **82. STRATEGY EVALUATION**

Separately evaluate:

Strategy Performance

Do not confuse:

Agent Accuracy

with:

Trading Strategy Performance

An agent can identify market direction correctly but still produce poor trades because of bad entries/exits.

# **83. POST-TRADE LEARNING**

After each completed trade:

Prediction

→ Actual Outcome

→ Error Analysis

→ Agent Attribution

→ Strategy Attribution

→ Regime Attribution

Generate a:

PostTradeReview

# **84. CONTINUOUS IMPROVEMENT**

Do NOT allow automatic self-modification of:

- trading rules;

- risk limits;

- execution policies;

- system prompts;

- model routing;

- strategy parameters.

Instead:

Observed Performance

↓

Research

↓

Proposed Change

↓

Backtest

↓

Validation

↓

Review

↓

Version

↓

Deployment

# **85. REQUIRED DOMAIN OBJECTS**

Design schemas for:

MarketContext

AnalysisResult

EvidenceItem

EvidenceReport

RegimeResult

StrategyResult

BullCase

BearCase

ConsensusResult

ChallengeResult

Signal

ValidationResult

RiskAssessment

TradeIntent

PostTradeReview

AgentEvaluation

# **86. AGENT CONTRACT**

Create a reusable contract:

AgentContract

agent_id

agent_version

role

input_schema

output_schema

allowed_tools

allowed_data

model_configuration

prompt_version

timeout

retry_policy

failure_policy

evaluation_policy

# **87. AGENT RESULT CONTRACT**

Create:

AgentResult

analysis_id

agent_id

agent_version

timestamp

asset

timeframe

observations\[\]

signals\[\]

supporting_evidence\[\]

contradicting_evidence\[\]

confidence

data_references\[\]

calculation_references\[\]

limitations\[\]

# **88. EVIDENCE ITEM**

Create:

EvidenceItem

evidence_id

category

observation

direction

strength

source

source_type

timestamp

data_reference

calculation_reference

independence_group

reliability

supports

contradicts

# **89. CHALLENGE RESULT**

Create:

ChallengeResult

challenge_id

target_signal

critic_agent

arguments_against

weak_assumptions

missing_evidence

risk_factors

invalidation_conditions

recommendation

# **90. DECISION RECORD**

Create:

DecisionRecord

decision_id

signal_id

market_context_reference

analysis_references

regime_reference

strategy_references

validation_reference

risk_reference

bull_case

bear_case

contrarian_case

final_status

decision_timestamp

# **91. ARCHITECTURAL CONSTRAINT**

No agent should directly modify:

Account Balance

Risk Limits

Orders

Positions

Trade History

Validation Results

Historical Data

Audit Records

Agents produce recommendations.

Domain services own state changes.

# **92. FINAL DECISION AUTHORITY**

The final authority chain must remain:

AI Analysis

↓

Validation

↓

Risk Policy

↓

Human Approval

↓

Execution

No AI agent can skip this chain.

# **93. REQUIRED DIAGRAMS**

Create:

### **1. Multi-Agent Topology**

Show every agent/team and relationship.

### **2. Agent Permission Matrix**

Show:

Agent × Tool × Permission

### **3. Information Flow Diagram**

Show how data moves between agents.

### **4. Analysis Workflow**

Show parallel analysis.

### **5. Debate Workflow**

Show:

Bull Case

Bear Case

Contrarian

Reconciliation

### **6. Signal Synthesis Workflow**

### **7. Failure Workflow**

### **8. Agent Evaluation Workflow**

### **9. Post-Trade Learning Workflow**

# **94. REQUIRED AGENT MATRIX**

Create a table with:

| **Agent** | **Purpose** | **Inputs** | **Outputs** | **Tools** | **Model** | **Deterministic Dependencies** | **Permission** | **Failure Mode** |
|-----------|-------------|------------|-------------|-----------|-----------|--------------------------------|----------------|------------------|

Include all proposed agents.

# **95. REQUIRED AGENT GROUPS**

At minimum evaluate:

### **Data**

- Market Data

- Data Quality

### **Technical**

- Technical Indicator

- Price Action

- Market Structure

- SMC

- Wyckoff

- Fibonacci

- Volume/Order Flow

### **Fundamental**

- Fundamental

- Tokenomics

- On-chain

- Event

### **Market**

- Derivatives

- Sentiment

- Macro

- Correlation

- Market Regime

### **Strategy**

- Strategy Research

- Strategy Selector

- Strategy Ensemble

### **Decision**

- Bull Case

- Bear Case

- Devil's Advocate

- Confluence

- Signal Synthesizer

- Evidence Reviewer

### **Risk**

- Risk Engine

- Portfolio Risk

### **Execution**

- Execution Service

- Position Monitor

### **Learning**

- Trade Evaluator

- Agent Evaluator

- Strategy Evaluator

- Research/Improvement Engine

# **96. AVOID AGENT EXPLOSION**

Do not automatically create one LLM agent for every bullet above.

Determine which capabilities should be:

Deterministic Module

LLM Agent

LangGraph Node

LangGraph Subgraph

Background Worker

Service

Explain the reasoning.

The architecture should minimize unnecessary complexity.

# **97. COST-AWARE AGENT EXECUTION**

Design:

Fast Scan

↓

Candidate Detection

↓

Selective Deep Analysis

Only high-quality candidates should enter expensive multi-agent debate.

# **98. LATENCY-AWARE EXECUTION**

Classify agents:

Real-Time

Near Real-Time

Research

Offline

Do not put slow research agents into latency-sensitive execution paths unnecessarily.

# **99. ARCHITECTURAL ACCEPTANCE CRITERIA**

This phase is complete only when:

- agent responsibilities are explicit;

- deterministic vs AI responsibilities are explicit;

- every agent has an input/output contract;

- every agent has tool permissions;

- agent disagreement is preserved;

- contradictory evidence is preserved;

- no-trade is supported;

- bull and bear cases are supported;

- devil's advocate exists;

- correlated evidence is recognized;

- market regimes are explicit;

- strategies are versioned;

- AI confidence is separated from statistical probability;

- numerical claims are independently verified;

- evidence is traceable;

- analysis is reproducible;

- agent performance is measurable;

- strategy performance is separated from agent performance;

- portfolio context is supported;

- AI cannot directly execute trades;

- AI cannot bypass risk;

- AI cannot modify historical results;

- live execution remains behind human approval.

# **100. REQUIRED DELIVERABLES**

For this Chat 3 phase, produce:

1.  Multi-Agent Architecture

2.  Agent Team Structure

3.  Agent Responsibility Matrix

4.  Deterministic vs AI Responsibility Matrix

5.  Agent Permission Matrix

6.  Agent Input/Output Contracts

7.  Market Context Schema

8.  Evidence Schema

9.  Multi-Timeframe Architecture

10. Market Regime Architecture

11. Strategy Ensemble Architecture

12. Bull/Bear Thesis Architecture

13. Devil's Advocate Architecture

14. Confluence Architecture

15. Meta-Analysis Architecture

16. Agent Evaluation Architecture

17. Agent Memory Architecture

18. RAG Architecture

19. Model Routing Architecture

20. Adaptive Analysis Tiers

21. Market Scanner Architecture

22. Signal Synthesis Architecture

23. No-Trade Architecture

24. Information Flow Diagram

25. Agent Topology Diagram

26. Agent Security Boundary

27. Failure Model

28. Cost/Latency Model

29. Key ADRs

30. Open Architectural Decisions

31. Architecture Risks

32. Implementation Dependencies

# **101. FINAL PRINCIPLE**

The platform must behave like a disciplined professional trading research team:

OBSERVE

↓

MEASURE

↓

ANALYZE

↓

CHALLENGE

↓

COMPARE

↓

VALIDATE

↓

ASSESS RISK

↓

WAIT

↓

HUMAN APPROVAL

↓

EXECUTE

↓

MONITOR

↓

LEARN

Never:

PREDICT

↓

TRADE

The platform's intelligence should come from **multiple independent evidence streams, deterministic quantitative analysis, statistical validation, adversarial review, and disciplined risk management**, not from an LLM pretending to know the future.

# **102. FINAL OUTPUT**

At the end of this phase provide:

## **MULTI-AGENT ARCHITECTURE DECISION SUMMARY**

Include:

1.  Final recommended agent topology

2.  Agents that should be LLM-based

3.  Components that should be deterministic

4.  Components that should be conventional services

5.  Components that should be LangGraph nodes/subgraphs

6.  Recommended model-routing strategy

7.  Recommended analysis pipeline

8.  Recommended debate pipeline

9.  Recommended evidence pipeline

10. Highest-risk architectural decisions

11. Remaining unresolved decisions

12. Recommended implementation order

Do NOT implement live trading.

Do NOT connect to production exchanges.

Do NOT generate exchange credentials.

Do NOT automatically modify strategies based on AI output.

End with:

**MULTI-AGENT ARCHITECTURE COMPLETE — READY FOR CHAT 4: MARKET DATA, ALTERNATIVE DATA & DATA ENGINEERING**
