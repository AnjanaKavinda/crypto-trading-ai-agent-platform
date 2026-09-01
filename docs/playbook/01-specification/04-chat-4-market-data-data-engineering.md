# Chat 4 — Market Data, Alternative Data & Data Engineering

> Full source-derived Chat 4 content from the uploaded Master Playbook v2.2 DOCX. This is not a summary. Source Markdown lines 12312–15711 of the complete conversion.

---

Master Prompt — Chat 4

V2.1 INLINE UPGRADE - CHAT 4 MARKET DATA, ALTERNATIVE DATA & DATA ENGINEERING

Purpose: make data quality, provenance, freshness, lineage, and contracts explicit across all market, alternative, fundamental, event, and historical datasets.

Retained Scope

Preserve market data, OHLCV, trades, order books, spreads, volume, depth, funding, open interest, liquidations, futures basis, derivatives, historical data, and quality validation.

Preserve separation of acquisition, normalization, validation, storage, and interpretation.

v2.1 Corrections and Enhancements

Add DataQualityReport as a first-class contract consumed by analysis, strategy, risk, safety, and UX.

Add EventData contract for macro events, token unlocks, protocol upgrades, governance, listings, delistings, regulatory events, security incidents, and exchange incidents.

Add FundamentalData contract for tokenomics, supply, emissions, unlocks, vesting, treasury, revenue, TVL, users, developer activity, governance, and protocol health.

Add data freshness and staleness thresholds per data category.

Add provider abstraction and source provenance for every external claim.

Chat 4 Required Contracts

MarketData, MarketSnapshot, DataQualityReport, DataSourceRecord, DatasetVersion, EventData, FundamentalData, OnChainData, DerivativesData, SentimentData, MacroData, FeatureSet.

Acceptance Criteria

No downstream signal can claim evidence without source, timestamp, data quality, and lineage.

Stale, degraded, missing, or conflicting data can trigger NO_TRADE or human review.

Historical datasets used for validation are versioned and reproducible.

# **ENTERPRISE-GRADE SUPERVISED AUTONOMOUS CRYPTO TRADING PLATFORM**

## **GitHub Copilot Master Prompt — Chat 4**

### **Market Data, Alternative Data, Data Engineering & Data Quality Architecture**

You are continuing the implementation planning for the enterprise-grade supervised autonomous crypto trading platform defined in:

- Chat 1 — Product Requirements & System Constitution

- Chat 2 — Enterprise System Architecture

- Chat 3 — Multi-AI Trading Intelligence & Agent Architecture

These documents are authoritative.

Do not contradict previous architectural decisions without identifying the conflict and documenting an Architecture Decision Record (ADR).

This phase focuses exclusively on the **data foundation** required by the trading intelligence platform.

You are acting as the **Principal Software Architect, Quantitative Trading Systems Architect, AI Agent Architect, Security Architect, and Senior Engineering Lead** for this project.

We are designing and incrementally implementing an **enterprise-grade, AI-powered, supervised crypto market analysis, trading intelligence, and trading execution platform**.

This is NOT a simple crypto trading bot.

It is a **multi-agent trading intelligence and supervised execution platform** whose purpose is to analyse cryptocurrency markets using multiple independent analytical disciplines, evaluate trading opportunities using reproducible historical evidence, present transparent trading signals to a human supervisor, and execute trades only after explicit approval and deterministic risk validation.

The system must be designed so that AI assists with analysis and reasoning while **critical financial calculations, risk controls, permissions, execution constraints, and transaction integrity remain deterministic and auditable**.

# **1. PRIMARY OBJECTIVE**

Build a data architecture capable of supporting:

Real-Time Market Analysis

Historical Analysis

Technical Analysis

Market Structure Analysis

SMC

Wyckoff

Volume Analysis

Order Flow

Derivatives Analysis

On-Chain Analysis

Fundamental Analysis

Sentiment Analysis

Macro Analysis

Backtesting

Walk-Forward Testing

Monte Carlo Testing

Strategy Research

Signal Generation

Risk Management

Portfolio Analysis

Post-Trade Analysis

AI Agent Evaluation

The data architecture must prioritize:

Correctness

Completeness

Timeliness

Consistency

Traceability

Reproducibility

Availability

Scalability

Cost Efficiency

Security

# **2. CORE DATA PRINCIPLE**

The AI must NEVER be the source of truth for numerical market data.

For example, an AI agent must never invent:

BTC price

Funding rate

Open interest

Volume

Liquidations

Market cap

Token supply

Historical win rate

Instead:

External Data Source

↓

Data Ingestion

↓

Validation

↓

Normalization

↓

Storage

↓

Feature Calculation

↓

AI Agents

AI interprets data.

It does not create the underlying numerical facts.

# **3. DATA ARCHITECTURE**

Design the following logical layers:

External Data Providers

│

▼

Data Connectors

│

▼

Ingestion Layer

│

▼

Message/Event Layer

│

▼

Validation & Quality Layer

│

▼

Normalization Layer

│

▼

Canonical Data Model

│

├───────────────┐

▼ ▼

Hot Data Store Historical Store

│ │

└───────┬───────┘

▼

Feature Engineering

│

▼

Feature Store

│

┌───────┼────────┐

▼ ▼ ▼

Analytics AI Backtesting

# **4. DATA SOURCE CATEGORIES**

Support multiple categories.

## **Market Data**

OHLCV

Trades

Tick Data

Order Book

Bid/Ask

Spread

VWAP

Volume

Liquidity

## **Derivatives**

Funding

Open Interest

Liquidations

Long/Short Ratio

Basis

Futures

Options

Implied Volatility

## **On-Chain**

Transactions

Active Addresses

Whale Activity

Exchange Flows

Holder Distribution

Stablecoin Flows

TVL

Protocol Revenue

Gas

Network Activity

## **Fundamental**

Tokenomics

Supply

Circulating Supply

FDV

Unlocks

Vesting

Treasury

Revenue

Fees

Protocol Usage

Developer Activity

Governance

## **Sentiment**

News

Social Media

Community Activity

Search Trends

Fear/Greed

Narrative Momentum

## **Macro**

Interest Rates

Inflation

Employment

Dollar Index

Treasury Yields

Liquidity

Equity Indices

Commodity Markets

Economic Calendar

# **5. DATA PROVIDER ABSTRACTION**

Do not tightly couple the application to one provider.

Create interfaces such as:

MarketDataProvider

DerivativesDataProvider

OnChainDataProvider

FundamentalDataProvider

NewsDataProvider

SentimentDataProvider

MacroDataProvider

Providers should be replaceable.

Example:

Provider A

Provider B

Provider C

should implement the same logical contract where possible.

# **6. PROVIDER REGISTRY**

Create a provider registry.

Example:

ProviderRegistry

provider_id

provider_type

supported_assets

supported_markets

supported_metrics

rate_limits

historical_depth

real_time_support

quality_score

cost

status

The system should know what each provider can actually supply.

# **7. MULTI-SOURCE REDUNDANCY**

For critical market data, support multiple providers.

Example:

Exchange A

Exchange B

Exchange C

↓

Cross-Source Comparison

↓

Canonical Market Data

Do not blindly average prices.

Define explicit aggregation rules.

# **8. EXCHANGE DATA**

Support exchange-specific data.

Examples of logical exchange categories:

Spot

Futures

Perpetual

Options

The system must distinguish:

Exchange

Market Type

Trading Pair

Contract

Quote Currency

Settlement Currency

# **9. SYMBOL NORMALIZATION**

Different exchanges may represent the same asset differently.

Examples:

BTC/USDT

BTC-USDT

BTCUSDT

XBT/USDT

Create a canonical instrument model.

Example:

Instrument

instrument_id

base_asset

quote_asset

exchange

market_type

contract_type

settlement_asset

contract_size

tick_size

lot_size

status

# **10. ASSET IDENTITY**

Separate:

Asset

from:

Instrument

Example:

Asset:

BTC

Instrument:

BTC/USDT Binance Spot

Instrument:

BTC/USDT Exchange Futures

Instrument:

BTC/USD Perpetual

This distinction is mandatory.

# **11. OHLCV DATA**

Support:

1m

3m

5m

15m

30m

1h

2h

4h

6h

12h

1d

1w

but make supported timeframes configurable.

Each candle must include:

timestamp

open

high

low

close

volume

trade_count where available

source

exchange

instrument

# **12. CANDLE TIMESTAMP STANDARD**

Define a canonical timestamp policy.

Use:

UTC

internally.

Never store trading timestamps ambiguously.

Document whether candle timestamps represent:

Candle Open

or:

Candle Close

and enforce this consistently.

# **13. CANDLE COMPLETENESS**

Detect:

Missing Candles

Duplicate Candles

Overlapping Candles

Invalid OHLC

Zero Volume

Timestamp Gaps

Out-of-Order Data

Create:

CandleQualityReport

# **14. OHLC VALIDATION**

Validate:

High \>= max(Open, Close)

Low \<= min(Open, Close)

High \>= Low

Volume \>= 0

Reject impossible data.

Do not silently repair corrupted data without recording the repair.

# **15. ORDER BOOK**

Support configurable depth.

Example:

Top 10

Top 20

Top 50

Top 100

Store:

timestamp

bid levels

ask levels

exchange

instrument

sequence number where available

# **16. ORDER BOOK QUALITY**

Detect:

Sequence Gaps

Stale Book

Duplicate Updates

Negative Quantities

Crossed Book

Extreme Spread

Missing Updates

If order-book quality is insufficient:

ORDER_FLOW_ANALYSIS = UNAVAILABLE

Do not manufacture order-flow signals.

# **17. TRADES / TICKS**

Where available capture:

trade_id

timestamp

price

quantity

side

exchange

instrument

Support reconstruction of:

Trade Flow

Volume Delta

Aggressive Buying

Aggressive Selling

Large Trades

# **18. FUNDING RATE**

Store:

timestamp

exchange

instrument

funding_rate

funding_interval

predicted_funding where available

Do not assume all exchanges use the same funding interval.

# **19. OPEN INTEREST**

Track:

Open Interest

OI Change

OI Percentage Change

OI by Exchange

OI Aggregate

Make sure units are normalized.

Distinguish:

Contract Quantity

USD Notional

Asset Notional

# **20. LIQUIDATIONS**

Where available track:

Long Liquidations

Short Liquidations

Total Liquidations

Liquidation Volume

Liquidation Clusters

Timestamp

Exchange

Instrument

Do not infer exchange-wide liquidations from incomplete data without marking the limitation.

# **21. BASIS**

Support:

Spot Price

Futures Price

Basis

Annualized Basis

The system should understand:

Contango

Backwardation

where relevant.

# **22. OPTIONS DATA**

Where available support:

Strike

Expiry

Call/Put

Open Interest

Volume

Implied Volatility

Greeks

Put/Call Ratio

Skew

Term Structure

This should be optional because availability varies significantly by asset.

# **23. ON-CHAIN DATA**

Create a provider-independent model.

Support:

Chain

Block

Address

Transaction

Token

Wallet

Exchange

Protocol

Metrics may include:

Active Addresses

New Addresses

Transaction Volume

Exchange Inflows

Exchange Outflows

Whale Transfers

Holder Concentration

Stablecoin Supply

Stablecoin Flows

TVL

Fees

Revenue

# **24. ON-CHAIN DATA PROVENANCE**

Every on-chain metric must identify:

Blockchain

Provider

Calculation Method

Block Height

Block Timestamp

Extraction Timestamp

This is critical for reproducibility.

# **25. TOKENOMICS**

Create a structured tokenomics model.

Support:

Total Supply

Max Supply

Circulating Supply

Current Inflation

Emission Schedule

Burn Mechanism

Unlock Schedule

Vesting

Team Allocation

Investor Allocation

Treasury

Ecosystem Allocation

Track changes over time.

Do not treat current tokenomics as static.

# **26. TOKEN UNLOCK DATA**

Create:

TokenUnlockEvent

asset

timestamp

amount

percentage_supply

recipient_category

source

confidence

Upcoming unlocks should become event-risk inputs.

# **27. FUNDAMENTAL DATA VERSIONING**

Fundamental metrics can be revised.

Therefore preserve:

Observed Value

Observation Time

Publication Time

Revision Time

Source

Version

This prevents look-ahead bias.

# **28. NEWS DATA**

Store:

headline

body/reference

publisher

publication_time

retrieval_time

asset

entities

topic

sentiment

source_reliability

Never overwrite the original publication timestamp.

# **29. NEWS EVENT NORMALIZATION**

Multiple news sources may report the same event.

Create:

Event Deduplication

Example:

20 articles

↓

Same underlying event

↓

1 canonical event

But preserve all source references.

# **30. SENTIMENT ENGINE**

Do not reduce sentiment to:

Bullish = 1

Bearish = -1

Create richer features:

Sentiment Score

Sentiment Confidence

Sentiment Velocity

Mention Volume

Mention Velocity

Source Reliability

Narrative Strength

Narrative Change

# **31. SOCIAL DATA**

Where legally and technically permitted, support:

Social Mentions

Engagement

Volume

Influencer Activity

Narrative Trends

Clearly separate:

Raw Social Signal

from:

AI Interpretation

# **32. BOT / MANIPULATION AWARENESS**

Social sentiment may contain:

Bots

Spam

Coordinated Campaigns

Manipulation

Duplicate Posts

Fake Engagement

Build quality filters.

Do not interpret raw social volume as genuine demand.

# **33. MACRO DATA**

Create a macro data abstraction.

Support:

Economic Indicator

Release

Forecast

Previous

Actual

Revision

Timestamp

Critical distinction:

What was known at that time?

This is essential for backtesting.

# **34. POINT-IN-TIME DATA**

The platform MUST support point-in-time reconstruction.

For every backtest timestamp:

Only information available at that timestamp

may be used.

This is a non-negotiable requirement.

# **35. LOOK-AHEAD BIAS PREVENTION**

Prevent:

Future Candle Data

Future Fundamental Revisions

Future News

Future Token Unlock Information

Future On-Chain Data

Future Sentiment

from entering historical decisions.

# **36. DATA LATENCY**

Track:

event_time

provider_time

ingestion_time

processing_time

availability_time

Calculate:

Data Latency

This allows the system to distinguish:

Real-Time

Delayed

Historical

Stale

# **37. STALE DATA DETECTION**

Every live data stream should have:

Expected Update Frequency

Maximum Acceptable Age

Example:

Order Book:

Very short TTL

Daily Fundamental:

Longer TTL

These values must be configurable.

# **38. DATA QUALITY SCORE**

Create a Data Quality Score based on:

Completeness

Freshness

Accuracy

Consistency

Source Reliability

Coverage

Continuity

But do not hide the underlying dimensions.

Always expose the individual metrics.

# **39. DATA QUALITY STATES**

Use:

VALID

DEGRADED

STALE

INCOMPLETE

INVALID

UNAVAILABLE

Critical downstream systems must respond accordingly.

# **40. DATA QUALITY GATE**

Before signal generation:

Data Quality Gate

must verify required datasets.

Example:

Technical Strategy:

OHLCV required

Order Flow Strategy:

OHLCV + Trades + Order Book required

Derivatives Strategy:

Funding + OI required

On-chain Strategy:

On-chain data required

If required data is unavailable:

Strategy = NOT_ELIGIBLE

# **41. DATA FRESHNESS GATE**

Do not allow stale data to silently generate a live signal.

Example:

Market data stale

→ Signal generation blocked

Sentiment stale

→ Sentiment factor marked unavailable

Do not substitute fake values.

# **42. DATA NORMALIZATION**

Normalize:

Timestamp

Currency

Units

Symbols

Decimals

Contract Size

Volume

Price

Notional Value

Keep original raw values where possible.

# **43. RAW DATA VS CANONICAL DATA**

Maintain:

RAW

and:

CANONICAL

layers.

Example:

Raw Exchange Response

↓

Raw Storage

↓

Parser

↓

Canonical Market Event

Never destroy the raw source unnecessarily.

# **44. DATA LINEAGE**

Every derived metric should be traceable.

Example:

Signal

↓

Indicator

↓

Feature

↓

Canonical Data

↓

Raw Data

↓

Provider

Store lineage metadata.

# **45. FEATURE ENGINEERING**

Build a feature engineering framework.

Examples:

Returns

Log Returns

Volatility

ATR

Momentum

Trend Strength

Volume Change

OI Change

Funding Z-Score

Liquidity

Spread

Order Book Imbalance

Features must be:

Versioned

Timestamped

Reproducible

Testable

# **46. FEATURE VERSIONING**

Example:

feature-set-v1

feature-set-v2

Never silently change a feature definition used by historical strategies.

# **47. FEATURE STORE**

Design a feature store capable of supporting:

Offline Training

Backtesting

Online Inference

Signal Analysis

Agent Analysis

Ensure offline and online feature calculations are consistent.

# **48. FEATURE LEAKAGE**

Detect features that accidentally contain future information.

Example:

Future close

Future volume

Future revised fundamental metric

The feature framework must explicitly classify:

Available At

time.

# **49. DATA RETENTION**

Define retention policies separately for:

Tick Data

Order Book

OHLCV

Derivatives

On-chain

News

Features

Signals

Trade Logs

Audit Logs

Do not assume every dataset needs indefinite retention.

# **50. STORAGE ARCHITECTURE**

Evaluate suitable storage patterns for:

### **Hot Data**

Low-latency current market state.

### **Time-Series Data**

Historical candles, trades, funding, OI.

### **Analytical Data**

Aggregations and features.

### **Object Storage**

Raw provider responses and large historical datasets.

### **Relational Database**

Metadata, configurations, signals, decisions, audit records.

Choose technology based on workload.

Do not blindly introduce databases simply because they are popular.

# **51. EVENT-DRIVEN DATA PIPELINE**

Design an event-driven architecture.

Example:

Exchange Stream

↓

Market Event

↓

Message Broker

↓

Consumers

├── Storage

├── Feature Engine

├── Order Flow

├── Alerting

└── Market Context

# **52. EVENT TYPES**

Define canonical events such as:

MarketTickReceived

CandleClosed

OrderBookUpdated

TradeReceived

FundingUpdated

OpenInterestUpdated

LiquidationDetected

OnChainMetricUpdated

NewsReceived

MacroEventReceived

FeatureCalculated

DataQualityChanged

# **53. EVENT SCHEMA**

Every event should contain:

event_id

event_type

event_version

event_time

source

ingestion_time

correlation_id

asset/instrument

payload

schema_version

# **54. IDEMPOTENCY**

Data ingestion must be idempotent.

If the same event arrives twice:

Do not duplicate it.

Use appropriate event identity/deduplication mechanisms.

# **55. ORDERING**

Where event ordering matters:

Sequence Number

or equivalent mechanisms must be used.

Do not assume network arrival order equals market event order.

# **56. RECONCILIATION**

Periodically reconcile:

Streaming Data

vs

Historical REST Data

Detect discrepancies.

Example:

Live candle

vs

final exchange candle

The final historical record may need correction.

Record the correction rather than silently overwriting history.

# **57. HISTORICAL BACKFILL**

Design a safe backfill system.

Requirements:

Range

Provider

Instrument

Timeframe

Progress

Retry

Rate Limit

Validation

Deduplication

Checkpoint

Backfills must not corrupt existing datasets.

# **58. RATE LIMIT MANAGEMENT**

Each provider should have:

Requests Per Minute

Requests Per Second

Burst Limit

Quota

Retry Policy

Backoff

The ingestion framework must enforce these limits.

# **59. RETRY POLICY**

Use appropriate strategies:

Exponential Backoff

Jitter

Maximum Retries

Circuit Breaker

Dead Letter Queue

Do not retry indefinitely.

# **60. PROVIDER FAILOVER**

For critical data:

Primary Provider

↓ failure

Secondary Provider

↓ failure

Degraded Mode

Failover must be explicit.

Do not silently mix incompatible provider datasets.

# **61. CROSS-EXCHANGE PRICE AGGREGATION**

If aggregating prices:

Define:

Eligible Exchanges

Liquidity Weight

Outlier Detection

Timestamp Synchronization

Spread Filtering

Do not simply average all exchanges.

# **62. OUTLIER DETECTION**

Detect:

Flash Spikes

Bad Ticks

Exchange Anomalies

Price Gaps

Volume Anomalies

But never automatically delete suspicious data.

Use:

Raw

Flagged

Validated

states.

# **63. DATA CORRECTION**

Corrections must be auditable.

Store:

Original Value

Corrected Value

Reason

Source

Timestamp

Correction Version

# **64. MARKET DATA SNAPSHOT**

Create a reproducible:

MarketSnapshot

containing all data needed to reconstruct an analysis at a particular timestamp.

Example:

BTC

Timestamp

OHLCV

Order Book

Trades

Funding

OI

Liquidations

Market Regime Inputs

# **65. ANALYSIS SNAPSHOT**

Create:

AnalysisSnapshot

which references:

MarketSnapshot

Feature Version

Agent Versions

Strategy Versions

Configuration Version

This allows historical analysis reproduction.

# **66. DATA SNAPSHOT FOR BACKTESTING**

Backtesting must be able to request:

Data as known at T

not:

Current database value for T

This distinction is mandatory.

# **67. DATA CLOCK**

Define a canonical internal clock.

All systems should use:

UTC

and synchronize timestamps.

Document:

Event Time

Processing Time

Decision Time

Execution Time

as separate concepts.

# **68. DATA BUS**

Choose and document the event/message infrastructure.

Evaluate options based on:

Throughput

Ordering

Durability

Replay

Latency

Operational Complexity

Cost

Do not choose technology solely because it is popular.

# **69. REPLAYABILITY**

The platform must support replaying historical events.

Example:

Historical Events

↓

Event Replay

↓

Feature Engine

↓

Analysis Agents

↓

Strategy

↓

Validation

This is extremely important for testing the autonomous system.

# **70. DETERMINISTIC REPLAY**

Where possible:

Same Input

\+

Same Configuration

\+

Same Version

=

Equivalent Output

For LLM outputs, preserve:

Model

Prompt Version

Parameters

Input

Output

Timestamp

and recognize that exact reproducibility may not always be possible.

# **71. DATA SECURITY**

Protect:

API Keys

Provider Credentials

Exchange Credentials

Internal Tokens

Never store secrets in:

Source Code

Git

Logs

Agent Prompts

Database Plaintext

Use secure secret management.

# **72. DATA PRIVACY**

For user-specific data such as:

Portfolio

Balances

Trading History

Risk Preferences

apply appropriate isolation.

Do not expose one user's data to another tenant.

# **73. MULTI-TENANCY**

Design data boundaries from the beginning.

Support:

Tenant

User

Portfolio

Account

Exchange Connection

Even if the first deployment is single-user.

# **74. DATA ACCESS CONTROL**

Define:

Public Market Data

Internal Analytical Data

User Portfolio Data

Trading Data

Sensitive Credentials

Audit Data

with separate access policies.

# **75. DATA OBSERVABILITY**

Monitor:

Ingestion Rate

Data Latency

Missing Data

Provider Errors

Data Quality

Event Lag

Storage Growth

Feature Calculation Latency

Create alerts.

# **76. DATA HEALTH DASHBOARD**

The platform should eventually display:

Provider Status

Market Data Status

Derivatives Status

On-chain Status

Sentiment Status

Macro Status

Freshness

Coverage

Quality

Latency

# **77. DATA INCIDENT MANAGEMENT**

Define behavior for:

Provider Outage

Bad Data

Stale Stream

Exchange Disconnect

Schema Change

API Change

Historical Correction

The system must enter safe degraded modes rather than producing unreliable trading signals.

# **78. PROVIDER SCHEMA CHANGE**

External APIs change.

Create:

Provider Adapter Version

Schema Version

Compatibility Layer

Contract Tests

Provider changes should not silently corrupt canonical data.

# **79. DATA CONTRACT TESTING**

Create automated tests that verify:

Provider Response

→ Adapter

→ Canonical Model

for each provider.

# **80. DATA QUALITY TESTING**

Test:

Completeness

Uniqueness

Validity

Consistency

Freshness

Range

Referential Integrity

Temporal Integrity

# **81. HISTORICAL DATA VALIDATION**

Before using a dataset for backtesting:

verify:

Coverage

Missing Periods

Exchange Changes

Symbol Changes

Splits/Contract Changes where relevant

Timezone

Fees

Funding

Delistings

# **82. SURVIVORSHIP BIAS**

The historical universe must include assets that:

Later Failed

Were Delisted

Lost Liquidity

Stopped Trading

where the research objective requires it.

Do not backtest only today's successful assets.

# **83. DELISTED ASSETS**

Maintain historical instrument lifecycle:

Listed

Active

Suspended

Delisted

Expired

Strategies must know whether an instrument was actually tradable at a given time.

# **84. EXCHANGE LIFECYCLE**

Track:

Exchange

Market Listing

Trading Status

Maintenance

Delisting

Contract Expiry

This prevents unrealistic backtests.

# **85. FEES DATA**

Historical performance must eventually account for:

Trading Fees

Maker/Taker

Funding

Borrowing

Withdrawal

Other Relevant Costs

Fees should be versioned by exchange/account tier where applicable.

# **86. SLIPPAGE MODEL**

Create configurable slippage models.

Potential approaches:

Fixed

Percentage

Spread-Based

Order-Book-Based

Volume-Based

Market-Impact

Backtesting must not assume zero slippage.

# **87. LIQUIDITY MODEL**

Track:

Volume

Depth

Spread

Estimated Market Impact

Use these to determine whether a hypothetical position could realistically be executed.

# **88. DATA-DRIVEN POSITION FEASIBILITY**

Eventually the Risk Engine should ask:

Can this position realistically be entered/exited

without unacceptable market impact?

This requires data from:

Liquidity

Order Book

Volume

Spread

Volatility

# **89. DATA QUALITY → TRADING SAFETY**

Establish hard rules.

Examples:

Critical market data unavailable

→ No trade

Price stream stale

→ No trade

Order book unavailable

→ Order-flow strategies disabled

Funding unavailable

→ Derivatives strategy degraded

On-chain unavailable

→ On-chain evidence marked unavailable

Never fabricate missing values.

# **90. DATA QUALITY → EVIDENCE REPORT**

The Evidence Report must show:

Data Sources

Data Freshness

Data Coverage

Data Quality

Missing Inputs

Provider Conflicts

This prevents false confidence.

# **91. PROVIDER CONFLICTS**

If:

Provider A = X

Provider B = Y

and the discrepancy exceeds a configurable threshold:

DATA CONFLICT

The system must investigate or downgrade confidence.

# **92. SOURCE PROVENANCE**

Every analytical input must be able to answer:

Where did this number come from?

When was it obtained?

When was it valid?

How was it transformed?

Which provider supplied it?

Which calculation generated it?

# **93. DATA LINEAGE GRAPH**

Design a lineage graph:

Raw Data

↓

Canonical Data

↓

Feature

↓

Analysis

↓

Strategy

↓

Signal

↓

Evidence

↓

Decision

Every node should have an identifier.

# **94. CANONICAL DATA IDENTIFIERS**

Create stable IDs for:

Asset

Instrument

Exchange

Market

Data Source

Feature

Event

Snapshot

Avoid using display names as primary identifiers.

# **95. DATA VERSIONING**

Version:

Raw Schema

Canonical Schema

Feature Definition

Provider Adapter

Data Correction

Derived Dataset

# **96. DATASET REGISTRY**

Create a:

DatasetRegistry

containing:

Dataset ID

Version

Owner

Source

Coverage

Frequency

Quality

Schema

Retention

Status

# **97. RESEARCH DATASETS**

Allow analysts to create immutable datasets such as:

BTC-1H-2020-2026-V1

Crypto-Derivatives-2023-2026-V2

OnChain-BTC-V1

Once used in published backtests, the dataset version must remain reproducible.

# **98. BACKTEST DATA CONTRACT**

A backtest must explicitly declare:

Dataset Version

Date Range

Assets

Timeframes

Fees

Slippage

Funding

Execution Assumptions

Latency

Data Availability Rules

No hidden assumptions.

# **99. DATA SIMULATION**

Create synthetic data capabilities for testing:

Normal Market

Bull Market

Bear Market

Flash Crash

Low Liquidity

High Volatility

Exchange Outage

Provider Failure

Missing Data

Stale Data

Use these for resilience testing.

# **100. CHAOS TESTING**

Test:

Exchange disconnect

Provider outage

Message loss

Duplicate events

Out-of-order events

Delayed data

Corrupt candle

Invalid order book

API rate-limit

Database failure

The platform must fail safely.

# **101. REQUIRED DATA DOMAIN OBJECTS**

Design schemas for at least:

Asset

Instrument

Exchange

Market

OHLCV

Trade

OrderBookSnapshot

FundingRate

OpenInterest

Liquidation

OptionsMetric

OnChainMetric

TokenomicsSnapshot

TokenUnlockEvent

NewsEvent

SentimentObservation

MacroObservation

EconomicEvent

MarketEvent

DataQualityReport

DataSnapshot

Feature

FeatureSet

Dataset

Provider

ProviderCapability

DataLineage

# **102. DATA PROVIDER CONTRACT**

Create:

DataProviderContract

containing:

provider_id

provider_version

data_types

markets

assets

historical_support

realtime_support

rate_limits

authentication

schema_version

quality_characteristics

# **103. DATA PIPELINE CONTRACT**

Create:

DataPipelineContract

containing:

pipeline_id

source

input_schema

output_schema

schedule

latency_target

quality_rules

retry_policy

failure_policy

retention_policy

# **104. DATA QUALITY CONTRACT**

Create:

DataQualityResult

containing:

dataset

timestamp

completeness

freshness

accuracy

consistency

source_reliability

missing_fields

invalid_records

duplicate_records

conflicts

status

# **105. DATA ACCESS LAYERS**

Create separate logical APIs/services for:

Market Data Service

Derivatives Data Service

On-Chain Data Service

Fundamental Data Service

Sentiment Data Service

Macro Data Service

Feature Service

Historical Data Service

Data Quality Service

Do not expose raw provider APIs directly to AI agents.

# **106. AGENT DATA ACCESS**

Agents should request data through controlled interfaces.

Example:

Technical Agent

→ MarketDataService

Derivatives Agent

→ DerivativesDataService

OnChain Agent

→ OnChainDataService

Macro Agent

→ MacroDataService

This provides consistent validation and auditing.

# **107. DATA REQUEST CONTRACT**

Agents should specify:

Asset

Instrument

Timeframe

Time Range

Metrics

Maximum Age

Required Quality

Example:

BTC

1H

Last 30 days

OHLCV + Volume

Quality \>= VALID

# **108. DATA RESPONSE CONTRACT**

Return:

Data

Source

Timestamp

Freshness

Quality

Coverage

Warnings

Lineage

Never return raw numbers without metadata.

# **109. DATA ACCESS AUDIT**

Log:

Agent

User

Tenant

Data Requested

Time Range

Provider

Timestamp

Result

This allows investigation of analytical decisions.

# **110. PERFORMANCE REQUIREMENTS**

Define realistic targets for:

Market Data Retrieval

Feature Calculation

Market Snapshot

Historical Query

Backtest Dataset Preparation

Agent Data Request

Do not optimize prematurely.

Measure first.

# **111. SCALABILITY**

The design should eventually support:

Hundreds/Thousands of Instruments

Multiple Exchanges

Multiple Timeframes

High-Frequency Market Events

Multiple Users

Multiple Portfolios

But keep the initial implementation modular and operationally simple.

# **112. COST MANAGEMENT**

Track:

Provider Cost

Storage Cost

Bandwidth

API Calls

Compute

Feature Processing

AI Data Consumption

Avoid retrieving expensive datasets unnecessarily.

# **113. DATA CACHING**

Use caching where appropriate.

Candidates:

Current Market Context

Recent OHLCV

Provider Metadata

Slow-Changing Fundamentals

Macro Data

Cache TTL must be dataset-specific.

# **114. CACHE INVALIDATION**

Never use stale cached data unknowingly.

Every cache entry must have:

Created

Updated

Expires

Source

Version

# **115. SECURITY BOUNDARY**

Separate:

Public Market Data

from:

Private Account Data

and:

Exchange Credentials

The market-analysis agents should not automatically have access to private credentials.

# **116. IMPORTANT ARCHITECTURAL RULE**

The data platform must NOT depend on the LLM layer.

It should remain operational even if:

All AI models are unavailable.

This allows:

Data collection

Backtesting

Research

Monitoring

Validation

to continue independently.

# **117. IMPORTANT ARCHITECTURAL RULE**

The trading system must be able to answer:

> "What did the system know at the exact moment this signal was generated?"

This should be possible through:

Data Snapshot

\+

Feature Snapshot

\+

Agent Inputs

\+

Configuration Version

\+

Strategy Version

# **118. IMPORTANT ARCHITECTURAL RULE**

Never modify historical data silently.

If data is corrected:

Original Version

→ Correction

→ New Version

Historical research must identify which version it used.

# **119. DATA → SIGNAL TRACEABILITY**

A final signal should be traceable to:

Signal

↓

Evidence

↓

Agent Analysis

↓

Feature

↓

Canonical Dataset

↓

Raw Provider Data

This is mandatory for the Evidence Report.

# **120. REQUIRED DIAGRAMS**

Create:

### **Diagram 1**

Enterprise Data Architecture

### **Diagram 2**

Real-Time Data Pipeline

### **Diagram 3**

Historical Data Pipeline

### **Diagram 4**

Alternative Data Pipeline

### **Diagram 5**

Data Quality Architecture

### **Diagram 6**

Feature Engineering Architecture

### **Diagram 7**

Point-in-Time / Anti-Look-Ahead Architecture

### **Diagram 8**

Data Lineage

### **Diagram 9**

Provider Failover

### **Diagram 10**

Event-Driven Data Architecture

### **Diagram 11**

Data Access Security Boundary

### **Diagram 12**

Data Replay Architecture

# **121. REQUIRED TABLES**

Create:

### **Provider Capability Matrix**

| **Provider** | **Market** | **OHLCV** | **Trades** | **Order Book** | **Funding** | **OI** | **Liquidations** | **On-Chain** | **News** | **Macro** |
|--------------|------------|-----------|------------|----------------|-------------|--------|------------------|--------------|----------|-----------|

Do not invent provider capabilities.

Mark unknown values as:

TBD

Create:

### **Data Quality Matrix**

| **Dataset** | **Freshness** | **Completeness** | **Validation** | **Required For** | **Failure Behavior** |
|-------------|---------------|------------------|----------------|------------------|----------------------|

Create:

### **Data Retention Matrix**

| **Dataset** | **Hot Retention** | **Historical Retention** | **Storage** |
|-------------|-------------------|--------------------------|-------------|

Create:

### **Agent Data Access Matrix**

| **Agent** | **Data** | **Read** | **Write** | **Historical** | **Real-Time** |
|-----------|----------|----------|-----------|----------------|---------------|

# **122. REQUIRED TESTING**

Create tests for:

Candle Validation

Timestamp Validation

Order Book Validation

Duplicate Detection

Missing Data

Outlier Detection

Provider Failover

Rate Limits

Retries

Idempotency

Event Ordering

Backfill

Reconciliation

Point-in-Time Queries

Feature Leakage

Data Lineage

Dataset Versioning

Replay

Chaos Testing

# **123. ACCEPTANCE CRITERIA**

This phase is complete only when:

- multiple data sources are supported;

- providers are abstracted;

- asset and instrument identities are separated;

- timestamps are normalized;

- raw and canonical data are separated;

- data quality is measurable;

- stale data is detected;

- provider conflicts are detected;

- historical data is versioned;

- point-in-time queries are supported;

- look-ahead bias protections exist;

- survivorship bias is considered;

- delisted assets can be represented;

- funding/OI/liquidations are supported;

- on-chain data is supported;

- tokenomics is supported;

- news/sentiment is supported;

- macro data is supported;

- data lineage exists;

- feature versioning exists;

- event replay exists;

- provider failover exists;

- rate limits are handled;

- ingestion is idempotent;

- data access is audited;

- agents cannot directly access raw providers;

- missing data cannot silently become fake data;

- data quality can block trading;

- data snapshots can reproduce historical analysis.

# **124. IMPLEMENTATION PRINCIPLE**

Build the data platform before attempting sophisticated autonomous trading.

Recommended dependency chain:

Provider Adapters

↓

Canonical Models

↓

Validation

↓

Storage

↓

Event Pipeline

↓

Feature Engineering

↓

Market Context

↓

AI Analysis

↓

Strategy

Do not reverse this order.

# **125. COPILOT IMPLEMENTATION RULE**

Before generating implementation code:

1.  Inspect the existing repository.

2.  Inspect existing architecture documents.

3.  Identify what already exists.

4.  Do not duplicate existing services.

5.  Propose changes before modifying architecture.

6.  Use modular boundaries.

7.  Write tests alongside implementation.

8.  Keep provider integrations behind interfaces.

9.  Keep secrets outside source control.

10. Do not introduce unnecessary infrastructure.

# **126. FINAL DELIVERABLE**

At the end of this phase produce:

1.  Final Data Architecture

2.  Data Source Strategy

3.  Provider Abstraction Architecture

4.  Canonical Data Model

5.  Event Model

6.  Storage Architecture

7.  Historical Data Architecture

8.  Real-Time Data Architecture

9.  Alternative Data Architecture

10. Data Quality Framework

11. Point-in-Time Architecture

12. Anti-Look-Ahead Framework

13. Feature Engineering Architecture

14. Feature Store Architecture

15. Data Lineage Architecture

16. Dataset Versioning Architecture

17. Provider Failover Strategy

18. Replay Architecture

19. Data Security Model

20. Data Access Model

21. Data Retention Model

22. Data Observability Model

23. Testing Strategy

24. Chaos Testing Strategy

25. Required Domain Models

26. Required Interfaces

27. Required APIs

28. Required Background Workers

29. Required Events

30. Required ADRs

31. Architecture Risks

32. Open Decisions

33. Implementation Dependencies

34. Recommended Implementation Order

Do NOT implement live trading.

Do NOT connect production exchange credentials.

Do NOT place real orders.

Do NOT allow AI agents to bypass data quality gates.

End with:

**DATA ARCHITECTURE COMPLETE — READY FOR CHAT 5: TECHNICAL, FUNDAMENTAL, MARKET STRUCTURE & META-ANALYSIS ENGINE**
