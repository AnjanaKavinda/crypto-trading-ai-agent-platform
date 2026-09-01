# Chat 6 — Strategy Engine, Signal Generation & 75%+ Evidence Qualification

> Full source-derived Chat 6 content from the uploaded Master Playbook v2.2 DOCX. This is not a summary. Source Markdown lines 18626–21435 of the complete conversion.

---

Master Prompt — Chat 6

V2.1 INLINE UPGRADE - CHAT 6 STRATEGY, SIGNAL GENERATION & 75 PERCENT EVIDENCE QUALIFICATION

Purpose: turn MarketContext into candidate signals and qualification decisions while preserving the boundary that Chat 7 independently validates robust historical/statistical evidence.

Retained Scope

Preserve strategy definitions, strategy versions, entry/invalidation/target rules, evidence graph, confluence, bull/bear case, Devil's Advocate integration, signal lifecycle, signal expiration, APIs, tests, observability, and security boundaries.

Preserve the correct 75 percent terminology: historical conditional win rate under defined test conditions, not guaranteed probability.

v2.1 Corrections and Enhancements

Promote NO_TRADE Decision Engine to a first-class component owned primarily by Chat 6 and consumed by UI, risk, safety, and learning.

Define machine-readable NoTradeReason codes.

Separate SignalCandidate, QualifiedSignal, RejectedSignal, ExpiredSignal, SupersededSignal, WatchSignal, and NoTradeDecision.

Add EvidenceFreshness and SignalExpiry checks to qualification.

Make the Evidence Graph mandatory from data to finding to strategy condition to signal qualification.

Chat 6 Required Contracts

Strategy, StrategyVersion, StrategyEligibility, StrategyCondition, SignalCandidate, Signal, SignalEvidencePackage, EvidenceGraph, SignalQualification, QualificationRuleSet, NoTradeDecision, NoTradeReason, SignalLifecycleState.

Acceptance Criteria

A signal cannot qualify solely on win rate.

A tiny sample cannot qualify even with a high win rate.

Every qualified signal includes sample size, period, asset, timeframe, strategy version, validation status, assumptions, fees/slippage handling, regime compatibility, and evidence freshness.

\# ENTERPRISE-GRADE SUPERVISED AUTONOMOUS CRYPTO TRADING PLATFORM

\# GITHUB COPILOT IMPLEMENTATION PROMPT - 6

\# CHAT 6 — STRATEGY ENGINE, SIGNAL GENERATION &

\# 75%+ EVIDENCE / VALIDATION FRAMEWORK

============================================================

PROJECT CONTINUITY

============================================================

You are continuing the implementation of the enterprise-grade,

supervised autonomous AI crypto analysis and trading platform.

The project follows a fixed 12-chat implementation playbook.

COMPLETED:

CHAT 1

Product Requirements & System Constitution

CHAT 2

Enterprise System Architecture

CHAT 3

Multi-AI Agent & Trading Intelligence Architecture

CHAT 4

Market Data, Alternative Data & Data Engineering

CHAT 5

Technical/Fundamental/SMC/Wyckoff/Meta-Analysis Engine

CURRENT:

CHAT 6

Strategy Engine, Signal Generation &

75%+ Evidence/Validation

FUTURE:

CHAT 7

Backtesting, Quant Validation &

Anti-Overfitting Framework

CHAT 8

Risk Management, Portfolio Management &

Position Sizing

CHAT 9

Human Approval, Execution, CCXT &

Exchange Integration

CHAT 10

AI Safety, Security, Audit, Observability &

Failure Recovery

CHAT 11

Frontend, Dashboard & Trader UX

CHAT 12

Implementation Roadmap, Repository Structure,

Testing & Copilot Coding Protocol

IMPORTANT:

Do not redesign the overall architecture.

Do not skip phases.

Do not implement responsibilities belonging to future phases.

Do not duplicate Chat 5 unnecessarily.

Do not implement live exchange execution.

Do not implement final portfolio allocation.

Do not implement autonomous trade execution.

============================================================

CHAT 6 OBJECTIVE

============================================================

Build the STRATEGY AND SIGNAL INTELLIGENCE LAYER.

The system must consume the structured analytical outputs

from CHAT 5 and determine:

1\. Which trading strategies are applicable.

2\. Whether current market conditions satisfy a strategy.

3\. Whether a candidate trading setup exists.

4\. What type of signal is being considered.

5\. What evidence supports the candidate.

6\. What evidence contradicts the candidate.

7\. What historical evidence is currently available.

8\. Whether the candidate satisfies configurable qualification

requirements.

9\. Whether the candidate should be presented to the human

as a qualified opportunity.

This layer creates CANDIDATE SIGNALS.

It does NOT execute them.

============================================================

CORE ARCHITECTURAL BOUNDARY

============================================================

CHAT 5:

DATA

↓

FEATURES

↓

ANALYSIS

↓

MARKET CONTEXT

↓

EVIDENCE

CHAT 6:

MARKET CONTEXT

↓

STRATEGY ELIGIBILITY

↓

SETUP DETECTION

↓

SIGNAL CONSTRUCTION

↓

SIGNAL EVIDENCE

↓

QUALIFICATION

↓

SIGNAL CANDIDATE

CHAT 7:

SIGNAL / STRATEGY

↓

BACKTEST

↓

OUT-OF-SAMPLE

↓

WALK-FORWARD

↓

STATISTICAL VALIDATION

↓

ANTI-OVERFITTING

↓

VALIDATED PERFORMANCE

CHAT 8:

VALIDATED SIGNAL

↓

RISK

↓

POSITION SIZE

↓

PORTFOLIO IMPACT

CHAT 9:

QUALIFIED TRADE

↓

HUMAN APPROVAL

↓

EXECUTION

============================================================

SECTION 1 — STRATEGY ENGINE

============================================================

Create a configurable Strategy Engine.

A strategy is a formal collection of:

\- market conditions

\- analytical prerequisites

\- setup conditions

\- entry conditions

\- invalidation conditions

\- exit concepts

\- supported assets

\- supported timeframes

\- applicable market regimes

\- required evidence

\- optional filters

A strategy must NOT be represented merely as an LLM prompt.

It must have a machine-readable definition.

============================================================

SECTION 2 — STRATEGY REGISTRY

============================================================

Create:

StrategyRegistry

Each strategy must have:

\- strategy_id

\- name

\- description

\- version

\- status

\- strategy_type

\- supported_assets

\- supported_timeframes

\- supported_market_regimes

\- required_conditions

\- optional_conditions

\- entry_logic

\- invalidation_logic

\- exit_logic

\- evidence_requirements

\- configuration

\- created_at

\- updated_at

Strategy status:

EXPERIMENTAL

ACTIVE

SUSPENDED

DEPRECATED

Do not silently modify an active strategy.

============================================================

SECTION 3 — STRATEGY TYPES

============================================================

Support a flexible strategy framework.

Examples:

TREND_FOLLOWING

BREAKOUT

BREAKOUT_RETEST

PULLBACK

MEAN_REVERSION

MOMENTUM

LIQUIDITY_SWEEP

SMC_STRUCTURE

WYCKOFF

RANGE_TRADING

VOLATILITY_EXPANSION

DERIVATIVES_POSITIONING

MULTI_FACTOR

EVENT_DRIVEN

Do not assume these strategies are profitable.

They are strategy templates.

Their effectiveness must later be validated.

============================================================

SECTION 4 — STRATEGY COMPOSITION

============================================================

Allow strategies to consume multiple analytical domains.

Example:

SMC Pullback Strategy

Required context:

\- bullish higher-timeframe structure

\- bullish market regime

\- liquidity sweep

\- bullish displacement

\- FVG/order-block context

\- lower-timeframe confirmation

Another example:

Trend Continuation Strategy

\- higher-timeframe trend

\- trend strength

\- momentum alignment

\- volume confirmation

\- acceptable volatility regime

The strategy engine must NOT assume that more conditions

automatically mean a better strategy.

============================================================

SECTION 5 — STRATEGY CONDITIONS

============================================================

Implement machine-readable conditions.

Example:

condition:

{

"feature": "market_structure.direction",

"operator": "EQUALS",

"value": "BULLISH"

}

Support operators such as:

EQUALS

NOT_EQUALS

GREATER_THAN

LESS_THAN

GREATER_THAN_OR_EQUAL

LESS_THAN_OR_EQUAL

IN_RANGE

PERCENTILE_ABOVE

PERCENTILE_BELOW

CROSSES_ABOVE

CROSSES_BELOW

PRESENT

ABSENT

============================================================

SECTION 6 — CONDITION GROUPS

============================================================

Support:

AND

OR

NOT

Example:

AND:

\- bullish HTF structure

\- bullish momentum

\- positive volume confirmation

OR:

\- liquidity sweep

\- breakout-retest

This must be deterministic.

============================================================

SECTION 7 — STRATEGY ELIGIBILITY

============================================================

Before creating a signal, evaluate:

Is the strategy applicable?

Check:

\- asset

\- timeframe

\- market regime

\- volatility regime

\- liquidity conditions

\- data availability

\- strategy status

\- required analytical conditions

Return:

ELIGIBLE

NOT_ELIGIBLE

INSUFFICIENT_DATA

============================================================

SECTION 8 — SETUP DETECTION

============================================================

Once a strategy is eligible, determine whether

the current market contains its required setup.

Possible states:

NO_SETUP

DEVELOPING

SETUP_FORMING

SETUP_CONFIRMED

INVALIDATED

EXPIRED

Do not convert every eligible strategy into a signal.

============================================================

SECTION 9 — SIGNAL TYPES

============================================================

Support:

LONG

SHORT

and analytical states:

WATCH

DEVELOPING

NO_TRADE

The system must not create a tradable signal simply

because a strategy is eligible.

============================================================

SECTION 10 — SIGNAL CANDIDATE

============================================================

Create:

SignalCandidate

with:

\- signal_id

\- strategy_id

\- strategy_version

\- asset

\- instrument

\- direction

\- timeframe

\- creation_timestamp

\- expiration_timestamp

\- setup_state

\- entry_model

\- invalidation_model

\- supporting_evidence

\- contradictory_evidence

\- analytical_context

\- qualification_state

\- evidence_score

\- data_quality

\- analytical_confidence

Do not include final execution state.

============================================================

SECTION 11 — ENTRY MODEL

============================================================

Define candidate entry concepts.

Examples:

MARKET

LIMIT

BREAKOUT

RETEST

PULLBACK

LIQUIDITY_SWEEP

STRUCTURE_CONFIRMATION

The system should calculate a candidate entry zone

where appropriate.

However, the final executable order parameters belong

to CHAT 9.

============================================================

SECTION 12 — STOP-LOSS CONCEPT

============================================================

The strategy may define an analytical invalidation level.

Examples:

\- structure invalidation

\- swing invalidation

\- ATR-based invalidation

\- liquidity invalidation

\- strategy-specific invalidation

Important:

This is a CANDIDATE analytical stop/invalidation concept.

Final user-controlled SL and execution parameters

belong to later phases.

============================================================

SECTION 13 — TAKE-PROFIT CONCEPT

============================================================

Support candidate target concepts:

\- structure target

\- liquidity target

\- Fibonacci target

\- volume-profile target

\- fixed R multiple

\- previous high/low

\- VWAP target

These are analytical target concepts.

Do not execute them.

============================================================

SECTION 14 — SIGNAL CONFLUENCE

============================================================

Consume Chat 5's confluence analysis.

Determine:

\- supporting analytical domains

\- independent evidence

\- correlated evidence

\- conflicting evidence

\- missing evidence

Do not double-count correlated indicators.

============================================================

SECTION 15 — EVIDENCE GRAPH

============================================================

Create an EvidenceGraph.

Represent:

Evidence

↓

Analytical Finding

↓

Strategy Condition

↓

Signal Qualification

Example:

Funding percentile = 95

↓

Derivatives positioning elevated

↓

Strategy filter satisfied

↓

Candidate signal receives evidence

Every signal must be explainable through this graph.

============================================================

SECTION 16 — EVIDENCE CATEGORIES

============================================================

Classify evidence as:

TECHNICAL

STRUCTURE

SMC

WYCKOFF

VOLUME

ORDER_FLOW

LIQUIDITY

DERIVATIVES

ON_CHAIN

FUNDAMENTAL

TOKENOMICS

SENTIMENT

NARRATIVE

MACRO

INTERMARKET

VOLATILITY

REGIME

HISTORICAL

Historical evidence is handled as a validation input,

not generated by the analytical agents.

============================================================

SECTION 17 — EVIDENCE STRENGTH

============================================================

Each evidence item may be classified:

VERY_STRONG

STRONG

MODERATE

WEAK

UNKNOWN

This is analytical evidence strength.

It must NOT be represented as probability of winning.

============================================================

SECTION 18 — SIGNAL EVIDENCE SCORE

============================================================

Create:

EvidenceScore

The score should consider:

\- number of supporting domains

\- independence of evidence

\- quality of evidence

\- data freshness

\- regime compatibility

\- contradictory evidence

\- missing evidence

Do not simply count indicators.

Do not interpret:

EvidenceScore = 80

as:

80% probability of profit.

============================================================

SECTION 19 — HISTORICAL PERFORMANCE INPUT

============================================================

The strategy engine may consume historical validation

metrics produced by the validation framework.

Examples:

\- historical win rate

\- sample size

\- expectancy

\- profit factor

\- maximum drawdown

\- out-of-sample metrics

\- regime-specific performance

However:

CHAT 6 defines how these metrics are used as

qualification criteria.

CHAT 7 is responsible for producing rigorous,

validated versions of these metrics.

============================================================

SECTION 20 — 75%+ REQUIREMENT

============================================================

The user's requested screening requirement is:

Minimum historical success rate = 75%

Implement this as a CONFIGURABLE QUALIFICATION RULE.

Example:

minimum_historical_win_rate = 0.75

BUT:

Do NOT interpret this as:

"75% guaranteed probability of winning."

The correct terminology is:

"Historical conditional win rate"

or:

"Historical strategy win rate under defined test conditions."

============================================================

SECTION 21 — 75% GATE

============================================================

A candidate may qualify for the user's preferred

high-evidence category only when the configured

requirements are satisfied.

Example:

historical_win_rate \>= 0.75

AND

minimum_sample_size satisfied

AND

positive expectancy

AND

acceptable risk metrics

AND

validation status acceptable

AND

data quality acceptable

AND

strategy applicable to current regime

The exact quantitative validation of these metrics

belongs to CHAT 7.

============================================================

SECTION 22 — SAMPLE SIZE

============================================================

Never allow a tiny sample to qualify simply because

the win rate is high.

Example:

5 trades

5 winners

100% win rate

must NOT automatically qualify.

Create:

MinimumSampleSizeRequirement

as a configurable parameter.

CHAT 7 will establish the statistically rigorous

validation methodology.

============================================================

SECTION 23 — CONDITIONAL WIN RATE

============================================================

Historical performance must be conditional on:

\- asset

\- timeframe

\- strategy

\- strategy version

\- market regime

\- setup definition

\- entry rules

\- exit rules

\- trading costs where applicable

Do not display a generic:

"Strategy win rate = 82%"

without context.

Instead:

"BTC / 1H / Strategy X / Regime Y /

Historical Win Rate = 82% / N = 312"

============================================================

SECTION 24 — QUALIFICATION STATES

============================================================

Create:

QUALIFIED_HIGH_EVIDENCE

QUALIFIED

WATCH

INSUFFICIENT_EVIDENCE

CONFLICTED

REJECTED

EXPIRED

A candidate should become:

QUALIFIED_HIGH_EVIDENCE

only when the configured evidence and validation

requirements are satisfied.

============================================================

SECTION 25 — SIGNAL RANKING

============================================================

When multiple qualified candidates exist,

rank them using transparent criteria.

Consider:

\- evidence quality

\- evidence independence

\- historical validation quality

\- regime compatibility

\- expected risk/reward

\- data quality

\- contradictory evidence

\- liquidity conditions

Do NOT rank solely by historical win rate.

============================================================

SECTION 26 — SIGNAL DEDUPLICATION

============================================================

Prevent duplicate signals.

Example:

Strategy A:

BTC breakout

Strategy B:

BTC momentum breakout

Strategy C:

BTC volume breakout

may represent the same underlying thesis.

Create a mechanism to identify correlated/duplicate

market theses.

============================================================

SECTION 27 — MARKET THESIS

============================================================

Create:

MarketThesis

with:

\- thesis_id

\- asset

\- direction

\- thesis_summary

\- supporting_evidence

\- contradictory_evidence

\- analytical_domains

\- strategy_candidates

\- market_regime

\- confidence

\- timestamp

\- expiration

A thesis is NOT an order.

============================================================

SECTION 28 — BULL / BEAR CASE

============================================================

Every significant candidate must contain:

BULL_CASE

BEAR_CASE

For LONG:

Bull case explains why continuation/upside

could occur.

Bear case explains why the setup could fail

or reverse.

For SHORT:

reverse accordingly.

============================================================

SECTION 29 — DEVIL'S ADVOCATE

============================================================

Consume Chat 5's Devil's Advocate analysis.

Additionally evaluate:

\- strongest reason for failure

\- contradictory market evidence

\- invalidating conditions

\- crowded positioning

\- unusual volatility

\- event risk

\- regime mismatch

Do not hide contradictory evidence.

============================================================

SECTION 30 — SIGNAL INVALIDATION

============================================================

Every candidate signal must define invalidation conditions.

Examples:

\- structure invalidation

\- setup invalidation

\- time expiration

\- volatility regime change

\- liquidity condition failure

\- strategy condition failure

\- critical data invalidation

============================================================

SECTION 31 — SIGNAL EXPIRATION

============================================================

Every signal must have:

created_at

valid_until

A signal must automatically become:

EXPIRED

after its validity period.

Do not allow stale signals to remain active indefinitely.

============================================================

SECTION 32 — EVENT FILTER

============================================================

Where Chat 4/5 provide event information,

strategies may specify event constraints.

Examples:

\- major macro event

\- token unlock

\- protocol upgrade

\- major governance event

Possible states:

NORMAL

EVENT_RISK

HIGH_EVENT_RISK

Do not implement full macro event infrastructure here.

Consume the data provided by previous layers.

============================================================

SECTION 33 — REGIME COMPATIBILITY

============================================================

Each strategy must define:

preferred regimes

acceptable regimes

incompatible regimes

Example:

strategy:

TREND_FOLLOWING

preferred:

STRONG_BULL

STRONG_BEAR

acceptable:

BULL

BEAR

potentially incompatible:

RANGE

This is a strategy configuration.

It is NOT proof of profitability.

============================================================

SECTION 34 — MULTI-TIMEFRAME STRATEGY LOGIC

============================================================

Strategies may require:

Higher timeframe context

Trading timeframe setup

Lower timeframe trigger

Example:

1D:

Bullish

4H:

Bullish

1H:

Pullback

15M:

Structure confirmation

The strategy engine should be able to evaluate

these relationships.

============================================================

SECTION 35 — SIGNAL QUALITY GATES

============================================================

Implement sequential gates:

GATE 1

Data Quality

GATE 2

Strategy Eligibility

GATE 3

Setup Detection

GATE 4

Evidence Quality

GATE 5

Evidence Conflict

GATE 6

Historical Evidence Availability

GATE 7

75%+ Requirement

GATE 8

Minimum Sample Size

GATE 9

Risk/Reward Availability

GATE 10

Regime Compatibility

GATE 11

Signal Freshness

GATE 12

Final Qualification

A failed gate must have an explicit reason.

============================================================

SECTION 36 — FAILURE REASONS

============================================================

Examples:

INSUFFICIENT_DATA

STRATEGY_NOT_ELIGIBLE

NO_SETUP

CONFLICTING_EVIDENCE

INSUFFICIENT_SAMPLE_SIZE

HISTORICAL_WIN_RATE_BELOW_THRESHOLD

VALIDATION_UNAVAILABLE

REGIME_MISMATCH

POOR_RISK_REWARD

SIGNAL_EXPIRED

DATA_STALE

STRATEGY_SUSPENDED

============================================================

SECTION 37 — SIGNAL EXPLANATION

============================================================

The system must be able to explain:

Why was this setup detected?

Which strategy matched?

Which conditions were satisfied?

Which conditions failed?

What evidence supports it?

What evidence contradicts it?

What historical data supports the strategy?

What historical data does not support it?

Why did it qualify?

Why did it fail qualification?

============================================================

SECTION 38 — SIGNAL REPORT

============================================================

Create:

SignalEvidenceReport

Structure:

========================================

SIGNAL EVIDENCE REPORT

========================================

Asset:

Direction:

Strategy:

Strategy Version:

Timeframe:

Market Regime:

Setup State:

----------------------------------------

CURRENT ANALYTICAL CONTEXT

----------------------------------------

Technical:

Structure:

SMC:

Wyckoff:

Volume:

Order Flow:

Liquidity:

Derivatives:

On-Chain:

Fundamental:

Tokenomics:

Sentiment:

Macro:

Volatility:

----------------------------------------

STRATEGY CONDITIONS

----------------------------------------

Satisfied Conditions:

Failed Conditions:

Optional Conditions:

----------------------------------------

SUPPORTING EVIDENCE

----------------------------------------

Evidence Items:

Independent Evidence:

Correlated Evidence:

----------------------------------------

CONTRADICTORY EVIDENCE

----------------------------------------

Conflicts:

Devil's Advocate:

Bear Case:

----------------------------------------

HISTORICAL EVIDENCE

----------------------------------------

Historical Win Rate:

Sample Size:

Validation Status:

Expectancy:

Profit Factor:

Drawdown:

----------------------------------------

QUALIFICATION

----------------------------------------

Minimum Required Win Rate:

75% Requirement:

Sample Size Requirement:

Evidence Score:

Qualification State:

Qualification Reasons:

----------------------------------------

CANDIDATE SETUP

----------------------------------------

Entry Concept:

Invalidation Concept:

Target Concept:

Signal Expiration:

----------------------------------------

UNCERTAINTIES

----------------------------------------

----------------------------------------

FINAL STATUS

----------------------------------------

QUALIFIED / WATCH / REJECTED /

INSUFFICIENT_EVIDENCE / CONFLICTED

========================================

IMPORTANT:

This report does not authorize execution.

============================================================

SECTION 39 — MACHINE-READABLE SIGNAL CONTRACT

============================================================

Create a strict schema.

Example:

{

"signal_id": "...",

"strategy_id": "...",

"strategy_version": "...",

"asset": "BTCUSDT",

"direction": "LONG",

"timeframe": "1H",

"setup_state": "SETUP_CONFIRMED",

"market_regime": "...",

"entry_concept": {

"type": "...",

"zone": {}

},

"invalidation_concept": {},

"target_concepts": \[\],

"supporting_evidence": \[\],

"contradictory_evidence": \[\],

"evidence_score": 0,

"historical_evidence": {

"win_rate": 0,

"sample_size": 0,

"validation_status": "..."

},

"qualification": {

"status": "...",

"reasons": \[\]

},

"analytical_confidence": 0,

"data_quality": {},

"created_at": "...",

"expires_at": "..."

}

============================================================

SECTION 40 — SEPARATE CONFIDENCE FROM WIN RATE

============================================================

Never confuse:

Analytical Confidence

with:

Historical Win Rate

Example:

Analytical Confidence = 0.88

Historical Win Rate = 0.76

These represent different concepts.

Do not calculate:

Probability of winning = 88%

unless a separately calibrated statistical model

supports such a statement.

============================================================

SECTION 41 — HISTORICAL PERFORMANCE DATA CONTRACT

============================================================

Define a contract that allows CHAT 7 to provide:

\- strategy_id

\- strategy_version

\- asset

\- timeframe

\- regime

\- sample_size

\- win_rate

\- expectancy

\- profit_factor

\- max_drawdown

\- validation_status

\- test_period

\- methodology_version

CHAT 6 consumes this information.

CHAT 7 owns its rigorous production.

============================================================

SECTION 42 — STRATEGY VERSIONING

============================================================

A signal must reference the exact strategy version.

Example:

Strategy:

SMC-Liquidity-Sweep

Version:

2.1.0

If the strategy definition changes:

create:

2.2.0

Do not overwrite historical strategy definitions.

============================================================

SECTION 43 — PARAMETER CONFIGURATION

============================================================

Strategy parameters must be configurable.

Examples:

\- timeframe

\- lookback

\- RSI threshold

\- ATR multiplier

\- minimum volume

\- structure rules

\- liquidity rules

\- entry distance

\- expiration duration

Do not hard-code strategy parameters throughout

the codebase.

============================================================

SECTION 44 — PARAMETER PROVENANCE

============================================================

Every signal must record:

\- parameter set

\- parameter version

\- strategy version

\- configuration version

This is essential for later backtesting and

reproducibility.

============================================================

SECTION 45 — AI ROLE

============================================================

AI agents may help with:

\- setup interpretation

\- qualitative context

\- alternative hypothesis

\- explanation

\- evidence synthesis

But deterministic code must control:

\- strategy condition evaluation

\- thresholds

\- signal state

\- scoring calculations

\- qualification rules

\- historical metric comparison

LLMs must not silently override deterministic

qualification rules.

============================================================

SECTION 46 — MULTI-AGENT STRATEGY REVIEW

============================================================

Use specialized AI roles where appropriate:

Strategy Analyst

Confluence Analyst

Contrarian Analyst

Evidence Reviewer

Signal Explanation Agent

The final signal state must still be produced by

a deterministic orchestration/qualification layer.

============================================================

SECTION 47 — DISAGREEMENT HANDLING

============================================================

If AI analysts disagree:

record:

\- agent conclusion

\- evidence

\- disagreement type

\- resolution

Do not simply average text outputs.

============================================================

SECTION 48 — NO HALLUCINATED EVIDENCE

============================================================

AI agents must never invent:

\- historical trades

\- win rates

\- market data

\- funding values

\- on-chain activity

\- news

\- backtest results

If unavailable:

return:

DATA_UNAVAILABLE

============================================================

SECTION 49 — AUDIT TRAIL

============================================================

Every candidate signal must be auditable.

Store:

\- input AnalysisSnapshot

\- strategy version

\- parameters

\- conditions

\- evidence

\- qualification results

\- model versions

\- agent outputs

\- timestamps

A future auditor must be able to determine

why the signal was qualified or rejected.

============================================================

SECTION 50 — SIGNAL LIFECYCLE

============================================================

Implement:

DETECTED

↓

ANALYZING

↓

QUALIFICATION_PENDING

↓

QUALIFIED

↓

PRESENTED_TO_HUMAN

↓

APPROVED / REJECTED

Also:

INVALIDATED

EXPIRED

SUPERSEDED

Important:

CHAT 6 ends at:

PRESENTED_TO_HUMAN

The actual approval workflow belongs to CHAT 9.

============================================================

SECTION 51 — NO AUTONOMOUS EXECUTION

============================================================

STRICTLY PROHIBITED IN CHAT 6:

\- exchange API trading

\- order placement

\- order cancellation

\- position management

\- withdrawals

\- leverage execution

\- capital allocation

\- live trade execution

Do not implement these.

============================================================

SECTION 52 — NO FINAL PORTFOLIO RISK

============================================================

Do not implement full:

\- portfolio allocation

\- portfolio optimization

\- correlation-based capital allocation

\- portfolio-level leverage

\- risk-of-ruin execution controls

These belong to CHAT 8.

Signal-level analytical risk/reward information

may be represented where necessary.

============================================================

SECTION 53 — NO FULL BACKTEST ENGINE

============================================================

Do not implement the complete:

\- backtesting engine

\- walk-forward engine

\- Monte Carlo framework

\- anti-overfitting framework

\- multiple-testing correction framework

\- statistical research engine

Those belong to CHAT 7.

CHAT 6 only defines the interface by which

validated historical metrics are consumed.

============================================================

SECTION 54 — TESTING

============================================================

Create unit and integration tests for:

Strategy registration

Strategy versioning

Condition evaluation

AND/OR/NOT logic

Strategy eligibility

Setup detection

Signal construction

Evidence mapping

Evidence dependency

Confluence

Conflict handling

75% threshold

Minimum sample size

Qualification states

Signal ranking

Signal deduplication

Signal expiration

Signal invalidation

Regime compatibility

Historical metrics consumption

Strategy parameter versioning

Signal schema

Evidence report

Audit trail

AI disagreement

Missing data

Invalid data

============================================================

SECTION 55 — EDGE CASES

============================================================

Test cases including:

100% win rate with tiny sample

74.9% historical win rate

75.0% historical win rate

75.1% historical win rate

High win rate but negative expectancy

High win rate but excessive drawdown

High win rate in one regime but poor performance

in the current regime

Strong technical evidence but weak derivatives

Strong structure but poor data quality

Conflicting AI analysts

Expired setup

Invalidated setup

Duplicate signals

Missing historical validation

Stale market data

Strategy version mismatch

============================================================

SECTION 56 — OBSERVABILITY

============================================================

Track:

\- strategies evaluated

\- strategies eligible

\- setups detected

\- signals generated

\- signals rejected

\- signals qualified

\- qualification failure reasons

\- evidence conflicts

\- AI disagreements

\- processing latency

\- data quality failures

============================================================

SECTION 57 — PERFORMANCE

============================================================

The strategy engine must support efficient evaluation

across many:

\- assets

\- timeframes

\- strategies

Avoid unnecessary LLM calls.

Use deterministic preprocessing and rule evaluation

before invoking AI reasoning.

============================================================

SECTION 58 — SECURITY

============================================================

The strategy engine must not have access to:

\- withdrawal credentials

\- exchange execution secrets

\- fund-transfer permissions

Use least privilege.

The strategy engine is analytical.

============================================================

SECTION 59 — REQUIRED DOMAIN OBJECTS

============================================================

Create or define:

Strategy

StrategyVersion

StrategyCondition

StrategyConditionGroup

StrategyEligibility

StrategySetup

MarketThesis

SignalCandidate

SignalEvidence

EvidenceGraph

SignalQualification

QualificationRule

QualificationResult

HistoricalPerformanceSnapshot

SignalExpiration

SignalInvalidation

StrategyParameterSet

SignalEvidenceReport

============================================================

SECTION 60 — REQUIRED APIs

============================================================

Design APIs such as:

GET /strategies

GET /strategies/{strategy_id}

POST /strategies/evaluate

POST /strategies/{strategy_id}/evaluate

GET /signals

GET /signals/{signal_id}

GET /signals/{signal_id}/evidence

GET /signals/{signal_id}/qualification

GET /market-theses

GET /strategy-performance

Do not create execution endpoints.

============================================================

SECTION 61 — STRATEGY ENGINE FLOW

============================================================

The complete CHAT 6 flow must be:

CHAT 5

MARKET CONTEXT

│

▼

STRATEGY REGISTRY

│

▼

STRATEGY ELIGIBILITY

│

┌──────┴──────┐

│ │

NOT ELIGIBLE ELIGIBLE

│ │

▼ ▼

REJECT SETUP DETECTION

│

┌──────┴──────┐

│ │

NO SETUP SETUP

│ │

▼ ▼

REJECT EVIDENCE FUSION

│

▼

CONFLICT ANALYSIS

│

▼

HISTORICAL EVIDENCE

│

▼

QUALIFICATION

│

┌───────┴────────┐

│ │

FAILED PASSED

│ │

▼ ▼

REJECTED QUALIFIED

│

▼

SIGNAL REPORT

│

▼

PRESENT TO HUMAN

│

▼

CHAT 9

============================================================

SECTION 62 — FINAL OUTPUT OF CHAT 6

============================================================

CHAT 6 must produce:

1\. Strategy Engine

2\. Strategy Registry

3\. Strategy Versioning

4\. Strategy Condition Engine

5\. Strategy Eligibility Engine

6\. Setup Detection Engine

7\. Signal Candidate Engine

8\. Market Thesis Engine

9\. Evidence Graph

10\. Confluence Integration

11\. Conflict Detection

12\. Signal Evidence Scoring

13\. Historical Evidence Interface

14\. 75%+ Qualification Gate

15\. Minimum Sample Size Gate

16\. Signal Qualification Engine

17\. Signal Ranking

18\. Signal Deduplication

19\. Bull/Bear Case

20\. Devil's Advocate Integration

21\. Signal Expiration

22\. Signal Invalidation

23\. Signal Evidence Report

24\. Machine-readable Signal Contract

25\. Strategy Parameter Management

26\. Strategy Version Management

27\. Signal Audit Trail

28\. Signal Lifecycle

29\. APIs

30\. Unit Tests

31\. Integration Tests

32\. Observability

33\. Security Boundaries

34\. Documentation

============================================================

SECTION 63 — CHAT 7 HANDOFF

============================================================

CHAT 6 must provide CHAT 7 with:

\- strategy definitions

\- strategy versions

\- strategy conditions

\- entry rules

\- invalidation rules

\- target rules

\- parameter sets

\- signal definitions

\- historical evidence requirements

\- performance metric contracts

\- qualification rules

CHAT 7 will then independently determine whether

the strategies and signals actually demonstrate

statistically credible historical performance.

============================================================

SECTION 64 — CRITICAL PERFORMANCE PRINCIPLE

============================================================

NEVER SAY:

"This strategy has a 75% probability of winning."

unless a properly calibrated probabilistic model

supports that exact statement.

Instead say:

"Historical conditional win rate:

75% under the specified test conditions."

Always display:

\- sample size

\- test period

\- asset

\- timeframe

\- strategy version

\- validation status

\- performance assumptions

============================================================

SECTION 65 — FINAL ARCHITECTURAL PRINCIPLE

============================================================

CHAT 6 answers:

"IS THERE A FORMAL TRADING SETUP?"

It does NOT answer:

"DOES THIS STRATEGY DEFINITIVELY WORK?"

CHAT 7 answers that.

It does NOT answer:

"HOW MUCH CAPITAL SHOULD WE RISK?"

CHAT 8 answers that.

It does NOT answer:

"SHOULD THE TRADE ACTUALLY BE EXECUTED?"

CHAT 9 answers that through human approval.

Therefore preserve the architecture:

CHAT 5

WHAT IS THE MARKET DOING?

↓

CHAT 6

IS THERE A FORMAL TRADING SETUP?

↓

CHAT 7

DOES THE STRATEGY HAVE ROBUST HISTORICAL

AND STATISTICAL EVIDENCE?

↓

CHAT 8

WHAT IS THE APPROPRIATE RISK?

↓

CHAT 9

DOES THE HUMAN APPROVE EXECUTION?

↓

CHAT 10

IS THE SYSTEM SAFE, AUDITABLE AND RESILIENT?

↓

CHAT 11

HOW DOES THE HUMAN INTERACT WITH IT?

↓

CHAT 12

HOW DO WE IMPLEMENT, TEST AND DEPLOY THE

COMPLETE SYSTEM?

============================================================

END OF CHAT 6

============================================================
