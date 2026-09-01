# Chat 5 — Technical / Fundamental / SMC / Wyckoff / Meta-Analysis Engine

> Full source-derived Chat 5 content from the uploaded Master Playbook v2.2 DOCX. This is not a summary. Source Markdown lines 15712–18625 of the complete conversion.

---

Master Prompt — Chat 5

V2.1 INLINE UPGRADE - CHAT 5 TECHNICAL/FUNDAMENTAL/SMC/WYCKOFF/META-ANALYSIS ENGINE

Purpose: strengthen Chat 5 as the analysis-only layer that produces MarketContext. Chat 5 must not perform final strategy validation, final position sizing, human approval, or execution.

Retained Scope

Preserve technical analysis, price action, market structure, Smart Money Concepts, Wyckoff, Fibonacci, derivatives, on-chain, sentiment, macro, confluence, and conflict detection.

Preserve analysis-only boundary: Chat 5 answers what the market is doing, not whether to execute a trade.

v2.1 Corrections and Enhancements

Promote Market Regime Engine to a shared first-class analytical service with trend, volatility, liquidity, risk, momentum, correlation, funding, OI, liquidation, and strategy compatibility regimes.

Strengthen Fundamental Intelligence with tokenomics, supply, emissions, unlocks, vesting, staking, treasury, utility, TVL, revenue, active addresses, developer activity, governance, ecosystem growth, and protocol health.

Promote Event Risk Assessment for macro, regulatory, exchange, project, token unlock, governance, hack/security, stablecoin, ETF, and protocol events.

Add AdversarialAssessment output that challenges bullish/bearish theses.

Make ConflictAssessment and AnalyticalUncertainty explicit outputs.

Chat 5 Required Contracts

MarketContext, AnalysisSnapshot, EvidenceItem, TechnicalAssessment, FundamentalAssessment, SMCAssessment, WyckoffAssessment, FibonacciAssessment, DerivativesAssessment, OnChainAssessment, SentimentAssessment, EventRiskAssessment, MarketRegime, ConfluenceAssessment, ConflictAssessment, AdversarialAssessment, AnalyticalUncertainty.

Acceptance Criteria

Chat 5 produces structured MarketContext with evidence and uncertainty.

Chat 5 does not create final trade decisions, final 75 percent qualification, final risk, approval, or execution.

Every analytical claim is traceable to evidence and data provenance.

# V2.2 INLINE METHODOLOGY ENHANCEMENT - CHAT 5

Chat 5 must expose a trader-readable methodology classification while still producing structured machine-readable MarketContext. The four major methodology categories are Fundamental Analysis, Technical Analysis, On-Chain Analysis, and Sentiment Analysis.

FundamentalAnalysis must explicitly include whitepaper/use-case review, token necessity, team/delivery history, GitHub/developer activity, partnership quality, real adoption, tokenomics, unlocks, vesting, treasury, TVL, protocol revenue, governance, and ecosystem health.

TechnicalAnalysis must classify indicators by purpose: trend, momentum, volatility/risk, volume/structure, market structure, SMC/Wyckoff/Fibonacci, and volume confirmation.

OnChainAnalysis must classify network activity, exchange flows, whale behavior, holder distribution, stablecoin flows, network security, miner/validator behavior where applicable, and capital-flow changes.

SentimentAnalysis must classify Fear & Greed, social volume, social narrative, community channels, funding rates, crowded positioning, and abnormal sentiment spikes.

IndicatorMetadata must include category, purpose, inputs, timeframe, calculation version, best regimes, weak regimes, failure modes, evidence-independence flag, and output schema.

Confluence must assess independence and quality of evidence, not simply count indicators or agents.

# **CHAT 5 — TECHNICAL, FUNDAMENTAL, SMC, WYCKOFF & META-ANALYSIS ENGINE**

\# ENTERPRISE-GRADE SUPERVISED AUTONOMOUS CRYPTO TRADING PLATFORM

\# GITHUB COPILOT IMPLEMENTATION PROMPT - 5

\# CHAT 5 — MARKET ANALYSIS & META-ANALYSIS INTELLIGENCE ENGINE

You are continuing the development of an enterprise-grade,

supervised autonomous AI crypto analysis and trading platform.

IMPORTANT:

This is CHAT 5 of a larger implementation playbook.

The following phases have already been completed:

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

The architecture and decisions established in previous phases are authoritative.

Do not redesign previous architecture unnecessarily.

Do not introduce unrelated technologies.

Do not skip existing architectural boundaries.

You are acting as the **Principal Software Architect, Quantitative Trading Systems Architect, AI Agent Architect, Security Architect, and Senior Engineering Lead** for this project.

We are designing and incrementally implementing an **enterprise-grade, AI-powered, supervised crypto market analysis, trading intelligence, and trading execution platform**.

This is NOT a simple crypto trading bot.

It is a **multi-agent trading intelligence and supervised execution platform** whose purpose is to analyse cryptocurrency markets using multiple independent analytical disciplines, evaluate trading opportunities using reproducible historical evidence, present transparent trading signals to a human supervisor, and execute trades only after explicit approval and deterministic risk validation.

The system must be designed so that AI assists with analysis and reasoning while **critical financial calculations, risk controls, permissions, execution constraints, and transaction integrity remain deterministic and auditable**.

============================================================

PRIMARY OBJECTIVE

============================================================

Build the enterprise-grade MARKET ANALYSIS INTELLIGENCE ENGINE.

The purpose of this layer is to transform normalized,

validated market and alternative data into structured,

traceable analytical observations and market interpretations.

This layer MUST NOT be responsible for:

\- final trading strategy selection

\- final trade signal generation

\- 75%+ win-rate qualification

\- strategy backtesting

\- walk-forward validation

\- Monte Carlo validation

\- final position sizing

\- portfolio allocation

\- leverage decisions

\- order execution

\- exchange order placement

\- autonomous trading

Those responsibilities belong to later phases.

This phase is ANALYSIS ONLY.

The output of this phase will become structured input

to CHAT 6 — Strategy Engine, Signal Generation &

75%+ Evidence/Validation.

============================================================

CORE PRINCIPLE

============================================================

The system must maintain a strict separation between:

DATA

↓

FEATURES

↓

ANALYSIS

↓

INTERPRETATION

↓

MARKET CONTEXT

and later:

MARKET CONTEXT

↓

STRATEGY

↓

SIGNAL

↓

VALIDATION

↓

HUMAN APPROVAL

↓

EXECUTION

Do not collapse these layers.

============================================================

ANALYTICAL PHILOSOPHY

============================================================

The system must behave like a professional multi-disciplinary

market research desk.

No single indicator, model, AI agent, or trading theory

should dominate the analytical output.

The system should examine the market from multiple

independent analytical perspectives.

Required analytical domains:

1\. Technical Analysis

2\. Price Action

3\. Market Structure

4\. Smart Money Concepts

5\. Wyckoff

6\. Fibonacci

7\. Volume Analysis

8\. Order Flow

9\. Liquidity Analysis

10\. Derivatives Analysis

11\. Volatility Analysis

12\. On-Chain Analysis

13\. Fundamental Analysis

14\. Tokenomics Analysis

15\. Sentiment Analysis

16\. Narrative Analysis

17\. Macro Analysis

18\. Intermarket Analysis

19\. Correlation Analysis

20\. Market Regime Analysis

21\. Cycle Analysis

22\. Meta-Analysis

============================================================

IMPORTANT AI DESIGN PRINCIPLE

============================================================

LLMs must NOT be responsible for calculations that can

be deterministically performed by software.

Use deterministic code for:

\- indicators

\- mathematical calculations

\- statistics

\- price levels

\- volatility

\- correlations

\- market structure rules

\- data transformations

Use AI agents for:

\- interpretation

\- contextual reasoning

\- hypothesis generation

\- qualitative analysis

\- cross-domain explanation

\- anomaly interpretation

\- research synthesis

Every AI conclusion must be traceable back to structured

data and analytical features.

============================================================

SECTION 1 — ANALYTICAL AGENT ARCHITECTURE

============================================================

Create specialized analytical agents/services.

At minimum:

Technical Analysis Agent

Price Action Agent

Market Structure Agent

SMC Agent

Wyckoff Agent

Volume Analysis Agent

Order Flow Agent

Liquidity Analysis Agent

Derivatives Analysis Agent

Volatility Agent

On-Chain Analysis Agent

Fundamental Analysis Agent

Tokenomics Agent

Sentiment Agent

Narrative Agent

Macro Analysis Agent

Intermarket Agent

Correlation Agent

Market Regime Agent

Cycle Analysis Agent

Meta-Analysis Agent

Each agent must have:

\- clearly defined responsibility

\- input contract

\- output contract

\- analytical rules

\- confidence representation

\- evidence references

\- data quality awareness

\- timestamp

\- version

\- error handling

============================================================

SECTION 2 — TECHNICAL ANALYSIS ENGINE

============================================================

Implement a deterministic technical-analysis engine.

Support configurable:

Trend indicators:

\- SMA

\- EMA

\- WMA

\- HMA where appropriate

Momentum:

\- RSI

\- MACD

\- Stochastic

\- ROC

\- CCI

Trend strength:

\- ADX

\- DI+

\- DI-

Volatility:

\- ATR

\- Bollinger Bands

\- Bollinger Band Width

\- Historical Volatility

\- Realized Volatility

Volume-related:

\- OBV

\- Volume moving averages

\- Volume rate of change

All indicators must be configurable.

Do not hard-code strategy-specific thresholds in the

analysis layer.

Example:

RSI = 72

is an observation.

The analysis agent may interpret:

"RSI is in an historically elevated region."

But it must NOT conclude:

"Therefore SHORT."

Strategy decisions belong to CHAT 6.

============================================================

SECTION 3 — PRICE ACTION ENGINE

============================================================

Analyze:

\- Candle body

\- Candle range

\- Upper wick

\- Lower wick

\- Close location

\- Range expansion

\- Range contraction

\- Breakout

\- Failed breakout

\- Rejection

\- Consolidation

\- Compression

\- Expansion

Support pattern identification:

\- engulfing

\- pin bar

\- hammer

\- shooting star

\- inside bar

\- outside bar

\- doji

\- morning star

\- evening star

Patterns must be contextual observations.

Never treat a candlestick pattern as an automatic

trade signal.

============================================================

SECTION 4 — MARKET STRUCTURE ENGINE

============================================================

Build a deterministic market-structure engine.

Detect:

\- swing highs

\- swing lows

\- higher highs

\- higher lows

\- lower highs

\- lower lows

\- internal structure

\- external structure

\- structural break

\- Break of Structure

\- Change of Character

\- Market Structure Shift

Every structural event must contain:

\- asset

\- timeframe

\- timestamp

\- price

\- structure type

\- detection rule

\- source candles

\- strength/context

\- invalidation condition

Avoid subjective structure labels whenever possible.

============================================================

SECTION 5 — SUPPORT & RESISTANCE

============================================================

Identify:

\- major highs

\- major lows

\- local highs

\- local lows

\- horizontal levels

\- repeated rejection levels

\- breakout levels

\- previous daily levels

\- previous weekly levels

\- previous monthly levels

\- session levels

\- dynamic levels

For every detected level store:

\- price

\- timeframe

\- detection method

\- creation timestamp

\- number of interactions

\- recent interactions

\- historical significance

\- current status

============================================================

SECTION 6 — MULTI-TIMEFRAME ANALYSIS

============================================================

The system must support configurable timeframe hierarchies.

Example:

Macro:

1D

1W

Higher:

4H

Trading:

1H

Lower:

15M

5M

Do not hard-code this hierarchy.

Analyze relationships between timeframes.

Example:

1D structure:

Bullish

4H structure:

Bullish

1H structure:

Bearish correction

15M:

Neutral

The system should report:

"Multi-timeframe alignment/conflict"

rather than automatically generating a trade.

============================================================

SECTION 7 — SMART MONEY CONCEPTS ENGINE

============================================================

Implement SMC as a structured analytical framework.

Support:

\- Order Blocks

\- Breaker Blocks

\- Fair Value Gaps

\- Liquidity Pools

\- Equal Highs

\- Equal Lows

\- Liquidity Sweeps

\- BOS

\- CHoCH

\- MSS

\- Displacement

\- Imbalances

\- Premium/Discount zones

Important:

SMC concepts must have explicit detection rules.

Do not allow an LLM to arbitrarily label a candle

as an Order Block.

Every detected SMC object must contain:

\- type

\- timeframe

\- price range

\- creation time

\- detection rule

\- current status

\- mitigation status

\- invalidation condition

\- supporting evidence

============================================================

SECTION 8 — FAIR VALUE GAP ENGINE

============================================================

Detect:

\- bullish FVG

\- bearish FVG

Track lifecycle:

Created

Active

Partially Filled

Filled

Invalidated

Store:

\- price range

\- timeframe

\- creation time

\- fill percentage

\- current status

============================================================

SECTION 9 — LIQUIDITY ANALYSIS

============================================================

Identify potential liquidity areas.

Examples:

\- equal highs

\- equal lows

\- previous highs

\- previous lows

\- session extremes

\- range extremes

\- obvious structural levels

Important:

Do not claim knowledge of hidden stop orders.

Use terminology:

"Potential Liquidity Area"

rather than:

"Confirmed Stop Cluster"

unless actual data supports that conclusion.

============================================================

SECTION 10 — LIQUIDITY SWEEP ANALYSIS

============================================================

Detect potential:

\- liquidity sweep

\- stop run

\- failed breakout

\- reclaim

\- rejection

\- displacement after sweep

Record:

\- liquidity level

\- sweep price

\- wick depth

\- volume

\- displacement

\- reclaim

\- timeframe

\- timestamp

This is an analytical observation only.

============================================================

SECTION 11 — WYCKOFF ENGINE

============================================================

Implement structured Wyckoff analysis.

Support:

\- Accumulation

\- Distribution

\- Markup

\- Markdown

\- Trading Range

\- Spring

\- Upthrust

\- Sign of Strength

\- Sign of Weakness

\- Preliminary Support

\- Preliminary Supply

\- Last Point of Support

\- Last Point of Supply

Also analyze:

\- Effort vs Result

\- Volume spread

\- Absorption

\- Climactic action

\- No Demand

\- No Supply

Do not allow an LLM to arbitrarily declare:

"BTC is in accumulation."

The system should provide:

Observed structural evidence

\+

Wyckoff interpretation

\+

uncertainty

============================================================

SECTION 12 — FIBONACCI ENGINE

============================================================

Support configurable Fibonacci:

Retracement:

23.6

38.2

50

61.8

78.6

100

Extension:

127.2

161.8

261.8 where appropriate

Support configurable swing anchors.

Store:

\- anchor points

\- timeframe

\- levels

\- calculation

\- timestamp

Do not treat Fibonacci levels as inherently predictive.

They are analytical reference levels.

============================================================

SECTION 13 — VOLUME ANALYSIS

============================================================

Analyze:

\- raw volume

\- relative volume

\- volume moving average

\- volume spikes

\- volume contraction

\- volume expansion

\- volume-price relationship

Support:

\- OBV

\- VWAP

\- Anchored VWAP

\- Volume Profile where data permits

Volume Profile:

\- POC

\- VAH

\- VAL

\- HVN

\- LVN

Every calculation must identify:

\- timeframe

\- session/anchor

\- source data

\- calculation parameters

============================================================

SECTION 14 — ORDER FLOW ENGINE

============================================================

Where reliable order-flow data is available, analyze:

\- bid/ask imbalance

\- volume delta

\- cumulative volume delta

\- aggressive buying

\- aggressive selling

\- absorption

\- exhaustion

\- large trades

\- liquidity imbalance

Do not fabricate order-flow information if the

data source does not provide it.

If unavailable:

status = DATA_UNAVAILABLE

not:

status = NEUTRAL

============================================================

SECTION 15 — MARKET MICROSTRUCTURE

============================================================

Analyze where data permits:

\- bid/ask spread

\- market depth

\- order book imbalance

\- liquidity depth

\- trade size distribution

\- execution pressure

\- market impact indicators

This analysis should later support execution and

risk engines, but no execution decision should occur

in CHAT 5.

============================================================

SECTION 16 — DERIVATIVES ANALYSIS

============================================================

Analyze:

\- Funding Rate

\- Open Interest

\- Futures Basis

\- Futures Premium

\- Long/Short ratios

\- Liquidations

\- Options metrics where available

Analyze relationships such as:

Price + OI

Price + Funding

Price + Liquidations

Price + Basis

Avoid simplistic universal interpretations.

Example:

"Price rising + OI rising"

is an observation.

The system may interpret possible positioning behavior,

but it must not automatically conclude:

"BUY."

============================================================

SECTION 17 — FUNDING ANALYSIS

============================================================

Calculate:

\- current funding

\- historical funding

\- funding percentile

\- funding z-score

\- funding trend

\- funding acceleration

\- funding divergence

Relative measurements should be preferred over

arbitrary universal thresholds.

============================================================

SECTION 18 — OPEN INTEREST ANALYSIS

============================================================

Analyze:

\- current OI

\- OI change

\- OI percentage change

\- OI velocity

\- OI/price relationship

\- OI/volume relationship

Classify observed positioning conditions such as:

\- increasing exposure

\- decreasing exposure

\- leverage expansion

\- leverage contraction

These are analytical interpretations, not trade signals.

============================================================

SECTION 19 — LIQUIDATION ANALYSIS

============================================================

Analyze:

\- liquidation volume

\- long liquidation

\- short liquidation

\- liquidation clusters

\- liquidation spikes

\- liquidation cascades

\- post-liquidation price behavior

Maintain historical context.

============================================================

SECTION 20 — ON-CHAIN ANALYSIS

============================================================

Where available analyze:

\- active addresses

\- transaction volume

\- exchange inflows

\- exchange outflows

\- whale transfers

\- holder distribution

\- stablecoin flows

\- network activity

\- fees

\- revenue

\- TVL

\- token movement

Always distinguish:

Observed transfer

from:

Confirmed buying/selling.

A blockchain transfer does not automatically indicate

a market transaction.

============================================================

SECTION 21 — WHALE ANALYSIS

============================================================

Analyze:

\- large transfers

\- exchange deposits

\- exchange withdrawals

\- whale accumulation indicators

\- whale distribution indicators

\- dormant wallet activity

Provide evidence and uncertainty.

============================================================

SECTION 22 — FUNDAMENTAL ANALYSIS

============================================================

Analyze:

Project:

\- purpose

\- utility

\- ecosystem

\- adoption

\- developer activity

\- competitive position

\- security

\- governance

\- network growth

Financial:

\- revenue

\- fees

\- users

\- TVL

\- treasury

\- protocol economics

Fundamental analysis should produce structured

observations rather than trading signals.

============================================================

SECTION 23 — TOKENOMICS ANALYSIS

============================================================

Analyze:

\- circulating supply

\- total supply

\- maximum supply

\- inflation

\- emission

\- vesting

\- unlocks

\- FDV

\- market cap

\- investor allocation

\- team allocation

\- treasury

\- ecosystem allocation

\- holder concentration

Generate:

TokenomicsRiskAssessment

but do not convert it into a trade signal.

============================================================

SECTION 24 — TOKEN UNLOCK ANALYSIS

============================================================

Track:

\- upcoming unlocks

\- unlock amount

\- percentage of circulating supply

\- investor unlocks

\- team unlocks

\- ecosystem unlocks

\- vesting schedules

Store event timestamps.

Later strategy and validation layers can determine

whether these events have measurable trading implications.

============================================================

SECTION 25 — SENTIMENT ANALYSIS

============================================================

Analyze:

\- news sentiment

\- social sentiment

\- mention volume

\- sentiment velocity

\- sentiment distribution

\- fear/greed indicators

\- positive/negative narrative changes

Separate:

Market sentiment

from:

Asset sentiment

from:

Narrative sentiment

============================================================

SECTION 26 — NARRATIVE ANALYSIS

============================================================

Detect crypto narratives dynamically.

Potential examples:

\- AI

\- DeFi

\- RWA

\- Layer 1

\- Layer 2

\- DePIN

\- Gaming

\- Infrastructure

\- Stablecoins

\- Memecoins

Do not permanently hard-code the narrative universe.

Track:

\- mention growth

\- social engagement

\- capital rotation

\- trading volume

\- relative performance

\- narrative acceleration

\- narrative exhaustion

Classify:

Emerging

Accelerating

Mature

Exhausting

Declining

These are analytical classifications.

============================================================

SECTION 27 — MACRO ANALYSIS

============================================================

Where reliable data is available analyze:

\- DXY

\- interest rates

\- treasury yields

\- inflation

\- liquidity conditions

\- equity markets

\- risk appetite

Classify macro environment:

\- risk-on

\- risk-off

\- liquidity expansion

\- liquidity contraction

Do not automatically translate macro conditions

into BUY/SELL decisions.

============================================================

SECTION 28 — INTERMARKET ANALYSIS

============================================================

Analyze relationships among:

\- BTC

\- ETH

\- total crypto market

\- Nasdaq

\- S&P 500

\- DXY

\- Gold

\- Treasury yields

Use rolling measurements where appropriate.

Do not assume historical correlations remain permanent.

============================================================

SECTION 29 — CORRELATION ENGINE

============================================================

Support:

\- Pearson correlation

\- Spearman correlation

\- rolling correlation

\- correlation stability

\- correlation breakdown

Store:

\- period

\- timeframe

\- sample size

\- correlation value

\- timestamp

============================================================

SECTION 30 — VOLATILITY REGIME ANALYSIS

============================================================

Analyze:

\- ATR

\- realized volatility

\- historical volatility

\- volatility percentile

\- Bollinger Band Width

\- range compression

\- range expansion

Classify:

\- low volatility

\- normal volatility

\- high volatility

\- extreme volatility

\- transition

This is market context.

It is not a strategy-selection decision.

============================================================

SECTION 31 — MARKET REGIME ANALYSIS

============================================================

Create a Market Regime Engine.

Possible classifications:

\- strong bullish trend

\- bullish trend

\- neutral/range

\- bearish trend

\- strong bearish trend

\- high-volatility regime

\- low-volatility regime

\- transition regime

Use multiple observations:

\- trend

\- volatility

\- momentum

\- structure

\- liquidity

\- derivatives

\- macro

The engine should explain WHY it classified

the current regime.

============================================================

SECTION 32 — MARKET CYCLE ANALYSIS

============================================================

Analyze longer-term context:

\- market cycle

\- historical cycle phase

\- halving context

\- liquidity cycles

\- market maturity

\- risk appetite

Do not assume historical crypto cycles will repeat.

Cycle analysis is contextual evidence only.

============================================================

SECTION 33 — ANALYTICAL CONFLUENCE

============================================================

Create a Confluence Analysis layer.

The purpose is NOT to create trading signals.

The purpose is to determine whether analytical

observations are:

ALIGNED

PARTIALLY ALIGNED

CONFLICTING

STRONGLY CONFLICTING

Example:

Technical:

Bullish

Structure:

Bullish

SMC:

Bullish

Derivatives:

Bearish

Macro:

Risk-Off

Result:

PARTIALLY ALIGNED / CONFLICTED

The system must expose the conflict rather than

hide it.

============================================================

SECTION 34 — EVIDENCE DEPENDENCY

============================================================

Do not count correlated indicators as fully independent

evidence.

Example:

RSI

MACD

Stochastic

may all represent related momentum behavior.

Therefore the system should distinguish:

Independent Evidence

Partially Dependent Evidence

Highly Correlated Evidence

This prevents future strategy layers from

double-counting confirmation.

============================================================

SECTION 35 — META-ANALYSIS ENGINE

============================================================

Build a meta-analysis layer that evaluates the

quality and relationships of analytical observations.

Questions the engine should be capable of answering:

Which analytical domains agree?

Which disagree?

Which evidence is independent?

Which evidence is correlated?

Which observations are strong?

Which observations are weak?

Which observations are based on missing data?

Which observations are based on stale data?

Which analytical methodology is applicable

to the current market context?

The meta-analysis layer must NOT answer:

"Should we trade?"

That belongs to CHAT 6.

============================================================

SECTION 36 — FACT / INFERENCE / ASSUMPTION

============================================================

Every AI-generated analytical conclusion must

be classified as:

FACT

INFERENCE

ASSUMPTION

UNCERTAINTY

Example:

FACT:

Funding is at the 94th historical percentile.

INFERENCE:

Current positioning is unusually expensive for longs.

ASSUMPTION:

Extreme positioning could increase vulnerability

to a reversal.

UNCERTAINTY:

Historical relationship may not persist in the

current market regime.

============================================================

SECTION 37 — DEVIL'S ADVOCATE ANALYSIS

============================================================

Create a Devil's Advocate analytical agent.

Its responsibility:

Challenge the current interpretation.

Identify:

\- contradictory evidence

\- alternative explanations

\- data limitations

\- regime mismatch

\- false patterns

\- possible measurement errors

\- confirmation bias

It must NOT attempt to force a BUY or SELL decision.

============================================================

SECTION 38 — ALTERNATIVE HYPOTHESIS ANALYSIS

============================================================

For important market conditions generate:

Primary Interpretation

Alternative Interpretation

Evidence Supporting Each

Evidence Against Each

Unknowns

This is intended to reduce confirmation bias.

============================================================

SECTION 39 — DATA QUALITY AWARENESS

============================================================

Every analytical output must carry data-quality metadata.

Possible statuses:

VALID

PARTIAL

STALE

MISSING

CONFLICTING

LOW_CONFIDENCE_DATA

UNAVAILABLE

Never convert missing information into a neutral

analytical value.

============================================================

SECTION 40 — ANALYSIS CONFIDENCE

============================================================

Agents may produce an analytical confidence score.

However:

Analytical confidence MUST NOT be represented as:

Probability of Profit

Probability of Winning

Expected Return

Trading Success Rate

Those belong to later quantitative validation.

Example:

confidence = 0.82

means:

"High confidence in the analytical interpretation"

NOT:

"82% chance of winning a trade."

============================================================

SECTION 41 — ANALYSIS OUTPUT CONTRACT

============================================================

Every analytical agent must return structured output.

Example:

{

"analysis_id": "...",

"agent": "technical_analysis",

"agent_version": "...",

"asset": "BTCUSDT",

"timeframe": "1H",

"timestamp": "...",

"observations": \[\],

"interpretations": \[\],

"evidence": \[\],

"contradictions": \[\],

"uncertainties": \[\],

"data_quality": {

"status": "VALID",

"coverage": 1.0,

"freshness": "...",

"source_count": 3

},

"analytical_confidence": 0.0

}

Do not use uncontrolled free-form prose as the canonical

machine-readable state.

============================================================

SECTION 42 — EVIDENCE ITEM CONTRACT

============================================================

Every important analytical claim should reference

one or more EvidenceItem objects.

Example:

{

"evidence_id": "...",

"source": "...",

"dataset": "...",

"feature": "...",

"value": "...",

"timestamp": "...",

"timeframe": "...",

"calculation": "...",

"interpretation": "...",

"quality": "VALID"

}

============================================================

SECTION 43 — ANALYSIS SNAPSHOT

============================================================

Create an immutable AnalysisSnapshot.

It must capture:

\- asset

\- instrument

\- timestamp

\- timeframe

\- market data version

\- calculated features

\- analytical outputs

\- agent versions

\- configuration

\- model versions

\- prompt versions where applicable

\- data quality

The purpose is reproducibility.

A historical analysis must be reconstructable.

============================================================

SECTION 44 — ANALYTICAL LINEAGE

============================================================

Maintain lineage:

RAW DATA

↓

NORMALIZED DATA

↓

FEATURE

↓

ANALYTICAL OBSERVATION

↓

INTERPRETATION

↓

MARKET CONTEXT

Every important conclusion should be traceable

back to its underlying data.

============================================================

SECTION 45 — ANALYTICAL REPORT

============================================================

Create a comprehensive Market Analysis Report.

Structure:

MARKET OVERVIEW

PRICE ACTION

TECHNICAL ANALYSIS

MARKET STRUCTURE

SMART MONEY CONCEPTS

WYCKOFF

FIBONACCI

VOLUME

ORDER FLOW

LIQUIDITY

DERIVATIVES

ON-CHAIN

FUNDAMENTAL

TOKENOMICS

SENTIMENT

NARRATIVE

MACRO

INTERMARKET

VOLATILITY

MARKET REGIME

CROSS-DOMAIN CONFLUENCE

CONFLICTING EVIDENCE

ALTERNATIVE HYPOTHESES

DATA QUALITY

ANALYTICAL UNCERTAINTIES

DEVIL'S ADVOCATE

OVERALL MARKET CONTEXT

IMPORTANT:

The report must NOT contain a final:

BUY

SELL

EXECUTE

trade recommendation.

Instead it should provide the analytical context

required by the future strategy engine.

============================================================

SECTION 46 — MARKET CONTEXT OBJECT

============================================================

Create:

MarketContext

containing:

\- asset

\- timestamp

\- multi-timeframe state

\- trend state

\- momentum state

\- volatility state

\- market structure state

\- liquidity state

\- derivatives state

\- on-chain state

\- fundamental state

\- sentiment state

\- macro state

\- regime state

\- confluence state

\- conflict state

\- data quality

\- analytical uncertainties

This object becomes the principal input to CHAT 6.

============================================================

SECTION 47 — NO SIGNAL GENERATION

============================================================

STRICT RULE:

CHAT 5 must NOT create:

\- BUY signal

\- SELL signal

\- LONG signal

\- SHORT signal

\- entry signal

\- trading strategy

\- trade probability

\- win-rate qualification

\- 75% threshold

\- final stop loss

\- final take profit

\- final leverage

\- final position size

If an analytical agent observes:

"Price is above the 200 EMA"

it must report the observation.

It must not automatically create:

"BUY."

============================================================

SECTION 48 — NO BACKTESTING

============================================================

Do not implement strategy backtesting in CHAT 5.

Do not implement:

\- historical strategy win rate

\- profit factor

\- Sharpe

\- Sortino

\- expectancy

\- maximum drawdown

\- walk-forward validation

\- Monte Carlo

\- bootstrap validation

\- strategy optimization

These belong to CHAT 7.

============================================================

SECTION 49 — NO EXECUTION

============================================================

Do not connect to live trading execution.

Do not:

\- place orders

\- modify orders

\- cancel orders

\- manage positions

\- select leverage

\- allocate capital

Those belong to later phases.

============================================================

SECTION 50 — TESTING

============================================================

Create comprehensive tests for:

Technical indicators

Price action detection

Swing detection

Market structure

BOS

CHoCH

MSS

Order Blocks

FVG

Liquidity zones

Liquidity sweeps

Wyckoff structures

Fibonacci

Volume

VWAP

Volume Profile

Order Flow

Funding

Open Interest

Liquidations

On-chain metrics

Tokenomics

Sentiment

Narrative

Macro

Intermarket

Correlation

Volatility

Market Regime

Confluence

Evidence dependency

Data quality

Analytical lineage

Analysis snapshots

Agent output contracts

============================================================

SECTION 51 — FAILURE HANDLING

============================================================

If one analytical agent fails:

Do NOT fabricate its result.

Mark:

UNAVAILABLE

and continue analysis where possible.

If critical market data is missing:

mark the analysis:

DATA_INCOMPLETE

The system must expose limitations.

============================================================

SECTION 52 — OBSERVABILITY

============================================================

Record:

\- analysis latency

\- agent latency

\- errors

\- missing data

\- data freshness

\- agent status

\- model usage

\- token usage where applicable

\- analytical conflicts

\- analysis completion

============================================================

SECTION 53 — VERSIONING

============================================================

Version:

\- analytical rules

\- indicator configuration

\- SMC rules

\- Wyckoff rules

\- regime rules

\- agent versions

\- prompts

\- model versions

\- schemas

Historical analysis must retain the versions used

to generate it.

============================================================

SECTION 54 — SECURITY

============================================================

The analysis layer must not have permission to:

\- access withdrawal credentials

\- place exchange orders

\- transfer funds

\- modify live positions

Use least privilege.

Analytical agents should be isolated from execution credentials.

============================================================

SECTION 55 — ARCHITECTURAL BOUNDARY

============================================================

The final architecture of CHAT 5 must be:

MARKET DATA

│

▼

DATA QUALITY LAYER

│

▼

FEATURE ENGINEERING

│

▼

┌──────────────────────┐

│ ANALYTICAL AGENTS │

└──────────────────────┘

│

┌────────────────┼────────────────┐

▼ ▼ ▼

Technical Structure Quantitative

Price Action SMC/Wyckoff Measurements

│ │ │

├────────────────┼────────────────┤

▼ ▼ ▼

Derivatives On-Chain Fundamental

│ │ │

├────────────────┼────────────────┤

▼ ▼ ▼

Sentiment Macro Intermarket

│ │ │

└────────────────┼────────────────┘

▼

MARKET REGIME

│

▼

CONFLUENCE ANALYSIS

│

▼

CONFLICT ANALYSIS

│

▼

META-ANALYSIS ENGINE

│

▼

DEVIL'S ADVOCATE

│

▼

MARKET CONTEXT

│

▼

ANALYSIS EVIDENCE REPORT

│

▼

CHAT 6 INPUT

CHAT 5 ENDS HERE.

============================================================

SECTION 56 — REQUIRED DELIVERABLES

============================================================

At the completion of CHAT 5, produce:

1\. Analytical architecture

2\. Analytical agent definitions

3\. Technical analysis engine

4\. Price action engine

5\. Market structure engine

6\. SMC engine

7\. Wyckoff engine

8\. Fibonacci engine

9\. Volume engine

10\. Order flow engine

11\. Liquidity engine

12\. Derivatives engine

13\. On-chain analysis engine

14\. Fundamental analysis engine

15\. Tokenomics engine

16\. Sentiment engine

17\. Narrative engine

18\. Macro engine

19\. Intermarket engine

20\. Correlation engine

21\. Volatility engine

22\. Market regime engine

23\. Cycle analysis engine

24\. Confluence engine

25\. Evidence dependency engine

26\. Meta-analysis engine

27\. Devil's Advocate agent

28\. Alternative hypothesis framework

29\. Data-quality framework

30\. Analysis confidence framework

31\. EvidenceItem schema

32\. MarketContext schema

33\. AnalysisSnapshot schema

34\. AnalysisReport schema

35\. Analytical lineage

36\. Agent contracts

37\. API contracts

38\. Unit tests

39\. Integration tests

40\. Failure-handling strategy

41\. Observability

42\. Versioning strategy

43\. Security boundaries

44\. Documentation

============================================================

SECTION 57 — STRICT HANDOFF TO CHAT 6

============================================================

CHAT 5 must produce a clean handoff to:

CHAT 6 —

STRATEGY ENGINE, SIGNAL GENERATION &

75%+ EVIDENCE/VALIDATION

CHAT 6 will consume:

MarketContext

AnalysisSnapshot

EvidenceItems

Analytical Findings

Confluence Information

Conflict Information

Market Regime

Data Quality

Analytical Uncertainty

CHAT 6 will then determine:

\- which strategies are applicable

\- whether a trading setup exists

\- how signals are constructed

\- how signals are ranked

\- how historical evidence is evaluated

\- how the 75%+ requirement is applied

CHAT 5 must NOT implement those decisions.

============================================================

FINAL PRINCIPLE

============================================================

The objective of CHAT 5 is NOT:

"Predict the market."

The objective is:

"Build a professional, multi-dimensional,

traceable representation of what the market is doing,

why the analytical agents believe it is doing so,

what evidence supports each interpretation,

what evidence conflicts with it,

and what remains uncertain."

The next layer will decide whether those analytical

conditions constitute a valid trading strategy/setup.

END OF CHAT 5.

## **Why this version is better**

The key correction is the **clean boundary**:

CHAT 4

DATA ENGINE

↓

CHAT 5

MARKET ANALYSIS ENGINE

↓

"WHAT IS HAPPENING?"

↓

CHAT 6

STRATEGY + SIGNAL ENGINE

↓

"IS THERE A TRADE?"

↓

CHAT 7

QUANT VALIDATION ENGINE

↓

"DOES THE EVIDENCE HOLD?"

↓

CHAT 8

RISK / PORTFOLIO

↓

"HOW MUCH RISK?"

↓

CHAT 9

HUMAN + EXECUTION

↓

"SHOULD WE EXECUTE?"
