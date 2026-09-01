# Chat 12 — Implementation Roadmap, Repository Structure, Testing & Copilot Protocol

> Full source-derived Chat 12 content from the uploaded Master Playbook v2.2 DOCX. This is not a summary. Source Markdown lines 38412–42957 of the complete conversion.

---

Master Prompt — Chat 12

V2.1 INLINE UPGRADE - CHAT 12 IMPLEMENTATION ROADMAP, REPOSITORY STRUCTURE, TESTING & COPILOT CODING PROTOCOL

## V2.2 COPILOT IMPLEMENTATION REQUIREMENT - METHODOLOGY TAXONOMY

Copilot must implement methodology taxonomy as explicit contracts/schemas rather than free-form prose only.

Required contracts include MethodologyCategory, IndicatorMetadata, FundamentalAssessment, TechnicalIndicatorAssessment, OnChainAssessment, SentimentAssessment, ConfluenceIndependenceAssessment, and TraderFacingExplanation.

Tests must verify that confluence does not double-count correlated indicators and that AI confidence, evidence score, historical conditional win rate, and probability remain separate fields.

Implementation must preserve all v2.1 artifacts: contract registry, agent matrix, handoff matrix, evidence graph, decision provenance, permission matrix, state machines, version registry, audit matrix, failure matrix, and test traceability matrix.

Purpose: convert the 13-chat specification into incremental, contract-driven, testable implementation prompts for GitHub Copilot without simplifying the system.

Retained Scope

Preserve repository structure, incremental phases, testing categories, CI/CD, documentation, ADRs, observability, security, and Copilot discipline.

v2.1 Corrections and Enhancements

Add a complete Contract Registry under /contracts and documentation under /docs/contracts.

Add /docs/agents/agent-responsibility-matrix.md and /docs/agents/agent-handoff-matrix.md.

Add /docs/traceability/evidence-graph.md, decision-provenance-graph.md, audit-matrix.md, and test-traceability-matrix.md.

Add implementation slices that produce domain contracts before service logic.

Require Copilot to inspect repository state before every implementation task and map each code change to a chat, contract, and acceptance criterion.

Add release gates for research-only, paper-trading, supervised-live-testnet, and live-supervised readiness.

Chat 12 Required Contracts/Artifacts

RepositoryMap, ImplementationSlice, CopilotTaskPrompt, DefinitionOfDone, TestTraceabilityMatrix, ContractRegistry, ADR, MigrationPlan, ReleaseGate, EnvironmentConfig, CIValidationReport.

Acceptance Criteria

Copilot never receives one giant uncontrolled build prompt.

Every implementation task includes objective, context, affected files, contracts, business rules, tests, security requirements, acceptance criteria, and do-not-do constraints.

Live execution remains disabled until explicit release gates are satisfied.

============================================================

ENTERPRISE-GRADE SUPERVISED AUTONOMOUS AI CRYPTO TRADING

PLATFORM

============================================================

GITHUB COPILOT IMPLEMENTATION PLAYBOOK

CHAT 12

IMPLEMENTATION ROADMAP

REPOSITORY STRUCTURE

TESTING

CI/CD

DEPLOYMENT

GITHUB COPILOT CODING PROTOCOL

DEFINITION OF DONE

============================================================

AUTHORITATIVE PROJECT CONTEXT

============================================================

This is the final implementation-planning stage of the

same enterprise-grade supervised autonomous AI crypto

trading platform.

The previous 11 chats are authoritative.

DO NOT redesign them.

DO NOT replace their architecture.

DO NOT create a new architecture.

DO NOT introduce a new phase numbering system.

DO NOT merge the previous chats.

This document converts the existing architecture and

requirements into an executable engineering plan.

============================================================

COMPLETED ARCHITECTURAL CAPABILITIES

============================================================

The system already defines:

1\. Product and system constitution

2\. Enterprise system architecture

3\. Multi-AI agent architecture

4\. Market data and alternative data

5\. Technical analysis

6\. Fundamental analysis

7\. Smart Money Concepts

8\. Wyckoff analysis

9\. Fibonacci analysis

10\. Sentiment analysis

11\. On-chain analysis

12\. Derivatives analysis

13\. Meta-analysis

14\. Strategy engine

15\. Signal generation

16\. Evidence-based validation

17\. Historical validation

18\. Backtesting

19\. Walk-forward validation

20\. Anti-overfitting controls

21\. Risk management

22\. Portfolio management

23\. Position sizing

24\. Human approval gateway

25\. CCXT/exchange integration

26\. Execution management

27\. Safety controls

28\. Security

29\. Audit

30\. Observability

31\. Failure recovery

32\. Professional trader dashboard

33\. Human-in-the-loop UX

============================================================

PRIMARY ENGINEERING PRINCIPLE

============================================================

Build the system incrementally.

Every component must have:

\- clear responsibility

\- explicit interfaces

\- tests

\- observability

\- failure handling

\- configuration

\- documentation

Do not implement the entire system in one step.

Do not generate thousands of lines of speculative code.

Implement one bounded capability at a time.

Compile.

Test.

Validate.

Review.

Then continue.

============================================================

SECTION 1 — IMPLEMENTATION STRATEGY

============================================================

Implementation order:

FOUNDATION

↓

DOMAIN MODEL

↓

DATA PLATFORM

↓

ANALYSIS ENGINE

↓

AGENT ORCHESTRATION

↓

STRATEGY ENGINE

↓

VALIDATION

↓

BACKTESTING

↓

RISK

↓

HUMAN APPROVAL

↓

EXECUTION

↓

MONITORING

↓

FRONTEND

↓

SECURITY

↓

OBSERVABILITY

↓

PRODUCTION HARDENING

============================================================

SECTION 2 — IMPLEMENTATION RULE

============================================================

Never implement execution before:

\- data validation

\- strategy validation

\- risk validation

\- approval workflow

\- safety controls

\- auditability

The live execution system must be one of the

LAST capabilities enabled.

============================================================

SECTION 3 — TECHNOLOGY PRINCIPLE

============================================================

Use the technologies already selected in the project

architecture.

Do not introduce alternative frameworks simply because

they are fashionable.

Where a technology decision was not finalized previously,

select the simplest enterprise-appropriate option that

preserves:

\- modularity

\- testability

\- observability

\- scalability

\- security

============================================================

SECTION 4 — REPOSITORY DESIGN

============================================================

Use a modular monorepo unless the previously defined

architecture explicitly requires separate repositories.

Recommended high-level structure:

/

├── apps/

├── services/

├── packages/

├── agents/

├── data/

├── infrastructure/

├── tests/

├── docs/

├── scripts/

├── configs/

└── .github/

============================================================

SECTION 5 — APPLICATIONS

============================================================

/apps

Contains user-facing applications.

Example:

/apps/web

Trader dashboard.

Do not put business-critical trading logic inside

frontend applications.

============================================================

SECTION 6 — SERVICES

============================================================

/services

Contains backend bounded services/modules.

Conceptually:

/services/api

/services/orchestrator

/services/market-data

/services/analysis

/services/strategy

/services/validation

/services/risk

/services/execution

/services/portfolio

/services/audit

/services/notification

Do not duplicate domain logic between services.

============================================================

SECTION 7 — AGENTS

============================================================

/agents

Contains AI agent implementations.

Examples:

/agents/market

/agents/technical

/agents/fundamental

/agents/smc

/agents/wyckoff

/agents/sentiment

/agents/onchain

/agents/derivatives

/agents/quant

/agents/risk

/agents/signal

/agents/supervisor

============================================================

SECTION 8 — SHARED PACKAGES

============================================================

/packages

Contains reusable contracts and infrastructure.

Examples:

/packages/contracts

/packages/domain

/packages/config

/packages/logging

/packages/observability

/packages/security

/packages/events

============================================================

SECTION 9 — DATA

============================================================

/data

Contains data-related components.

Examples:

/data/ingestion

/data/normalization

/data/quality

/data/storage

/data/features

Raw and processed data must remain distinguishable.

============================================================

SECTION 10 — INFRASTRUCTURE

============================================================

/infrastructure

Contains:

\- Docker

\- infrastructure-as-code

\- deployment configuration

\- environment configuration

\- observability infrastructure

\- database configuration

\- messaging infrastructure

============================================================

SECTION 11 — TEST STRUCTURE

============================================================

/tests

Organize by:

/tests/unit

/tests/integration

/tests/contract

/tests/e2e

/tests/backtest

/tests/strategy

/tests/risk

/tests/execution

/tests/security

/tests/chaos

============================================================

SECTION 12 — DOCUMENTATION

============================================================

/docs

Include:

architecture

ADRs

API contracts

agent specifications

strategy specifications

data contracts

risk rules

execution rules

security model

deployment

runbooks

incident procedures

testing

============================================================

SECTION 13 — AGENT CONTRACT

============================================================

Every AI agent must implement a standardized contract.

Conceptually:

AgentInput

AgentContext

AgentOutput

AgentEvidence

AgentMetadata

AgentError

Agent output must be structured.

Do not rely on free-form natural-language output

for machine-critical decisions.

============================================================

SECTION 14 — AGENT OUTPUT

============================================================

Every analysis agent should return structured

information including:

agent_id

agent_version

analysis_timestamp

asset

timeframe

direction

confidence

findings

evidence

contradictions

data_sources

data_freshness

limitations

============================================================

SECTION 15 — AI OUTPUT SAFETY

============================================================

Never allow raw LLM output to directly execute trades.

Pipeline:

LLM

↓

Structured Output

↓

Schema Validation

↓

Business Validation

↓

Quant Validation

↓

Risk Validation

↓

Human Approval

↓

Execution

============================================================

SECTION 16 — MODEL ABSTRACTION

============================================================

Do not hard-code business logic directly to

one model provider.

Create a model abstraction.

Support model configuration by:

provider

model

version

temperature where applicable

token limits

timeout

retry policy

============================================================

SECTION 17 — PROMPT VERSIONING

============================================================

All production prompts must be versioned.

Track:

prompt_id

version

purpose

model

created_at

updated_at

author

evaluation status

============================================================

SECTION 18 — AGENT VERSIONING

============================================================

Every agent must have:

agent_id

version

configuration_version

prompt_version

model_version

This is required for reproducibility.

============================================================

SECTION 19 — DATA CONTRACTS

============================================================

Create explicit schemas for:

MarketData

OHLCV

OrderBook

Trades

FundingRate

OpenInterest

Liquidations

OnChainMetrics

SentimentData

NewsData

FundamentalData

============================================================

SECTION 20 — DATA QUALITY

============================================================

Every important data object should include:

timestamp

source

symbol

timeframe where applicable

quality status

freshness

sequence information where applicable

============================================================

SECTION 21 — DATA QUALITY STATES

============================================================

VALID

STALE

INCOMPLETE

INVALID

UNKNOWN

============================================================

SECTION 22 — MARKET DATA PIPELINE

============================================================

Implement:

SOURCE

↓

INGESTION

↓

VALIDATION

↓

NORMALIZATION

↓

DEDUPLICATION

↓

TIMESTAMP ALIGNMENT

↓

QUALITY CHECK

↓

STORAGE

↓

FEATURE GENERATION

↓

ANALYSIS

============================================================

SECTION 23 — ANALYSIS PIPELINE

============================================================

Implement:

MARKET DATA

↓

TECHNICAL

FUNDAMENTAL

SMC

WYCKOFF

FIBONACCI

SENTIMENT

ON-CHAIN

DERIVATIVES

QUANT

↓

META-ANALYSIS

↓

CONFLUENCE

↓

SIGNAL CANDIDATE

============================================================

SECTION 24 — META-ANALYSIS

============================================================

Meta-analysis must not simply average agent outputs.

It should evaluate:

\- agreement

\- disagreement

\- evidence quality

\- evidence freshness

\- source reliability

\- regime compatibility

\- historical strategy performance

\- contradictions

\- uncertainty

============================================================

SECTION 25 — SIGNAL PIPELINE

============================================================

Implement:

ANALYSIS

↓

STRATEGY MATCH

↓

SIGNAL GENERATION

↓

EVIDENCE COLLECTION

↓

HISTORICAL VALIDATION

↓

OUT-OF-SAMPLE VALIDATION

↓

WALK-FORWARD VALIDATION

↓

RISK ANALYSIS

↓

SIGNAL STATUS

============================================================

SECTION 26 — 75%+ REQUIREMENT

============================================================

The project requirement is to identify signals/strategies

with validated historical performance targeting

greater than 75%.

NEVER represent this as a guarantee of future profit.

The implementation must record:

metric

sample size

test period

market

timeframe

strategy

in-sample result

out-of-sample result

walk-forward result

regime

cost assumptions

fees

slippage

drawdown

============================================================

SECTION 27 — SIGNAL STATUS

============================================================

Use explicit states:

GENERATED

VALIDATING

VALIDATED

FAILED_VALIDATION

EXPIRED

BLOCKED

READY_FOR_APPROVAL

APPROVED

REJECTED

============================================================

SECTION 28 — NO-TRADE PRINCIPLE

============================================================

The system must be capable of producing:

NO TRADE

Reasons may include:

insufficient evidence

poor R/R

strategy failure

market regime mismatch

agent disagreement

stale data

risk violation

execution risk

safety block

============================================================

SECTION 29 — BACKTESTING

============================================================

Backtesting must include realistic:

fees

slippage

latency assumptions where appropriate

funding

position sizing

leverage

liquidation mechanics where applicable

============================================================

SECTION 30 — LOOK-AHEAD BIAS

============================================================

Prevent:

future data leakage

future candle leakage

future fundamental information

future sentiment information

future on-chain information

future feature leakage

============================================================

SECTION 31 — SURVIVORSHIP BIAS

============================================================

Historical datasets must account for assets that:

failed

were delisted

became inactive

changed market availability

where relevant to the strategy.

============================================================

SECTION 32 — ANTI-OVERFITTING

============================================================

Do not optimize strategies exclusively

against historical results.

Require:

training period

validation period

test period

walk-forward evaluation

============================================================

SECTION 33 — STRATEGY REGISTRY

============================================================

Create a strategy registry.

Every strategy contains:

strategy_id

name

version

description

parameters

supported_assets

supported_timeframes

market_regimes

entry_rules

exit_rules

risk_constraints

validation_metrics

status

============================================================

SECTION 34 — STRATEGY STATES

============================================================

DRAFT

TESTING

VALIDATING

PAPER

APPROVED

LIVE

SUSPENDED

RETIRED

============================================================

SECTION 35 — RISK ENGINE

============================================================

Risk engine must independently validate:

position size

leverage

stop loss

take profit

maximum loss

portfolio exposure

margin

drawdown

concentration

correlation

liquidation risk

============================================================

SECTION 36 — USER PARAMETERS

============================================================

The user may modify:

amount

position size

leverage

entry

stop loss

take profit

order type

time in force

within configured safety limits.

============================================================

SECTION 37 — REVALIDATION

============================================================

Any material user modification invalidates

previous risk approval.

Example:

AI:

3x leverage

User:

5x leverage

Required:

MODIFICATION

↓

REVALIDATION

↓

APPROVAL

============================================================

SECTION 38 — APPROVAL

============================================================

No live execution without explicit human approval.

Approval must include:

signal_id

trade_candidate_id

parameters

risk result

validation result

user identity

timestamp

approval version

============================================================

SECTION 39 — APPROVAL IMMUTABILITY

============================================================

Once approved, the approved trade configuration

must be immutable.

Any modification requires:

new validation

new approval

============================================================

SECTION 40 — EXECUTION

============================================================

Execution must be isolated from analysis.

Conceptual pipeline:

APPROVED TRADE

↓

EXECUTION PRECHECK

↓

RISK CHECK

↓

SAFETY CHECK

↓

EXCHANGE CHECK

↓

ORDER SUBMISSION

↓

ORDER MONITORING

↓

RECONCILIATION

============================================================

SECTION 41 — CCXT

============================================================

Use the previously selected CCXT-based exchange

integration architecture.

Create an exchange abstraction.

The rest of the system must not depend directly

on individual exchange implementations.

============================================================

SECTION 42 — PAPER TRADING

============================================================

Before live trading implement:

paper trading

simulation

execution replay

Live trading must not be the first execution mode.

============================================================

SECTION 43 — RECONCILIATION

============================================================

Continuously reconcile:

internal orders

exchange orders

internal positions

exchange positions

internal balances

exchange balances

Mismatch must trigger safety handling.

============================================================

SECTION 44 — AUDIT

============================================================

Every material event must be auditable.

Examples:

market snapshot

agent execution

signal creation

validation

risk calculation

parameter modification

approval

order submission

exchange response

fill

position change

risk event

kill switch

system failure

============================================================

SECTION 45 — CORRELATION ID

============================================================

Every end-to-end trading workflow must have:

correlation_id

This allows:

signal

analysis

risk

approval

execution

position

audit

to be traced together.

============================================================

SECTION 46 — OBSERVABILITY

============================================================

Implement:

structured logs

metrics

traces

health checks

alerts

dashboards

============================================================

SECTION 47 — CRITICAL METRICS

============================================================

Track:

data latency

data freshness

agent latency

agent failure rate

signal generation rate

validation failure rate

risk rejection rate

approval rate

execution latency

execution failure rate

slippage

fees

PnL

drawdown

system errors

============================================================

SECTION 48 — SECURITY

============================================================

Never commit:

API keys

exchange secrets

private keys

tokens

passwords

credentials

to source control.

============================================================

SECTION 49 — SECRET MANAGEMENT

============================================================

Use secure secret management.

Configuration must distinguish:

development

testing

staging

paper

production

============================================================

SECTION 50 — ENVIRONMENT SEPARATION

============================================================

Never allow development configuration

to accidentally connect to production trading.

============================================================

SECTION 51 — LIVE TRADING SAFETY

============================================================

Production live trading must require

explicit environment configuration.

Example conceptual requirement:

TRADING_MODE=LIVE

and additional safety gates.

============================================================

SECTION 52 — KILL SWITCH

============================================================

Implement:

GLOBAL_KILL_SWITCH

EXECUTION_KILL_SWITCH

AGENT_KILL_SWITCH

The execution layer must respect these controls.

============================================================

SECTION 53 — CI/CD

============================================================

Every pull request must run:

formatting

linting

type checking

unit tests

integration tests

security checks

dependency checks

build

============================================================

SECTION 54 — BRANCH PROTECTION

============================================================

Protected branches should require:

successful CI

review

tests

no critical security findings

============================================================

SECTION 55 — AUTOMATED TESTING PYRAMID

============================================================

Use:

many unit tests

moderate integration tests

fewer end-to-end tests

specialized trading simulations

============================================================

SECTION 56 — UNIT TESTS

============================================================

Test:

indicators

market structure

signal rules

strategy logic

risk calculations

position sizing

state transitions

validation rules

serialization

============================================================

SECTION 57 — INTEGRATION TESTS

============================================================

Test:

database

message bus

market data

agent orchestration

risk service

approval service

execution adapter

============================================================

SECTION 58 — CONTRACT TESTS

============================================================

Validate:

frontend/backend contracts

service/service contracts

exchange adapter contracts

agent schemas

event schemas

============================================================

SECTION 59 — END-TO-END TESTS

============================================================

Test complete workflow:

market data

↓

analysis

↓

signal

↓

validation

↓

risk

↓

approval

↓

execution simulation

↓

position

↓

closure

↓

audit

============================================================

SECTION 60 — TRADING SCENARIO TESTS

============================================================

Create deterministic scenarios for:

bull market

bear market

range

high volatility

low liquidity

flash crash

gap

exchange outage

data outage

agent failure

risk breach

position mismatch

============================================================

SECTION 61 — FAILURE INJECTION

============================================================

Test:

market data unavailable

database unavailable

message queue unavailable

AI model timeout

AI model invalid output

exchange timeout

exchange rejection

duplicate order

network interruption

stale data

partial fill

============================================================

SECTION 62 — CHAOS TESTING

============================================================

Verify that failures result in:

safe degradation

trade blocking where necessary

no duplicate execution

correct recovery

complete audit trail

============================================================

SECTION 63 — IDEMPOTENCY

============================================================

Critical commands must be idempotent.

Especially:

approve

execute

cancel

close

reconcile

============================================================

SECTION 64 — DUPLICATE EXECUTION PROTECTION

============================================================

The system must prevent:

duplicate orders

duplicate approvals

duplicate fills

duplicate event processing

============================================================

SECTION 65 — STATE MACHINES

============================================================

Use explicit state machines for:

signal

trade candidate

approval

order

position

system health

agent lifecycle

Do not implement critical state transitions

using scattered boolean flags.

============================================================

SECTION 66 — DATABASE MIGRATIONS

============================================================

All schema changes must be version-controlled.

Never manually modify production schemas

without migration tracking.

============================================================

SECTION 67 — CONFIGURATION

============================================================

Centralize configuration.

Separate:

application configuration

strategy configuration

risk configuration

agent configuration

exchange configuration

environment configuration

============================================================

SECTION 68 — CONFIGURATION VALIDATION

============================================================

Application startup must validate required

configuration.

Fail safely when required configuration is invalid.

============================================================

SECTION 69 — DOCUMENTATION-AS-CODE

============================================================

Keep documentation synchronized with implementation.

Important architecture decisions must be documented.

============================================================

SECTION 70 — ADR

============================================================

Use Architecture Decision Records.

Each ADR should contain:

decision

context

alternatives

reasoning

consequences

============================================================

SECTION 71 — API DOCUMENTATION

============================================================

Maintain versioned API documentation.

Document:

request

response

authentication

authorization

errors

idempotency

rate limits

============================================================

SECTION 72 — ERROR CONTRACT

============================================================

Use structured error responses.

Include:

error_code

message

correlation_id

timestamp

details where safe

Never expose internal stack traces.

============================================================

SECTION 73 — EVENT ARCHITECTURE

============================================================

Use explicit domain events.

Examples:

MarketDataUpdated

AnalysisCompleted

SignalGenerated

SignalValidated

RiskApproved

TradeApprovalRequested

TradeApproved

TradeRejected

OrderSubmitted

OrderFilled

PositionOpened

PositionClosed

RiskLimitBreached

KillSwitchActivated

============================================================

SECTION 74 — EVENT VERSIONING

============================================================

Events must be versioned.

Do not silently change event schemas.

============================================================

SECTION 75 — RETRY POLICY

============================================================

Retries must be deliberate.

Do NOT blindly retry trading commands.

Retry policy must distinguish:

safe reads

idempotent operations

non-idempotent operations

order submission

============================================================

SECTION 76 — TIMEOUTS

============================================================

Every external call requires appropriate

timeout handling.

No indefinite waiting.

============================================================

SECTION 77 — CIRCUIT BREAKERS

============================================================

Use circuit breakers for unstable external

dependencies where appropriate.

Especially:

exchange

market data

AI model providers

============================================================

SECTION 78 — RATE LIMITING

============================================================

Respect exchange and external provider

rate limits.

Track rate-limit state.

============================================================

SECTION 79 — COST CONTROL

============================================================

Track AI usage:

tokens

requests

latency

cost

model

Avoid unnecessary repeated AI calls.

============================================================

SECTION 80 — AI FALLBACK

============================================================

AI failure must NOT automatically mean:

trade using another model.

Fallback behavior must be explicitly defined.

For critical analysis failure:

prefer:

NO TRADE

over:

unvalidated trade.

============================================================

SECTION 81 — DETERMINISTIC CORE

============================================================

Critical financial logic should be deterministic.

Examples:

position sizing

risk limits

maximum loss

margin checks

approval state

execution permissions

AI may provide recommendations.

AI must not override deterministic safety rules.

============================================================

SECTION 82 — HUMAN-IN-THE-LOOP

============================================================

Human approval remains mandatory for

live trade execution according to the

system constitution.

============================================================

SECTION 83 — FRONTEND IMPLEMENTATION

============================================================

Implement the frontend only after the backend

contracts are sufficiently stable.

Use the Chat 11 UX specification.

Do not duplicate business logic in frontend.

============================================================

SECTION 84 — FRONTEND MODULES

============================================================

Implement:

dashboard

markets

analysis

signals

approvals

positions

portfolio

risk

strategies

backtests

agents

alerts

system

audit

settings

============================================================

SECTION 85 — FRONTEND DATA SOURCES

============================================================

Frontend receives:

REST/API data

real-time events

authenticated user context

Never communicate directly with exchanges.

============================================================

SECTION 86 — FRONTEND APPROVAL

============================================================

Approval UI must:

display final validated state

display user modifications

display risk

display warnings

request explicit approval

============================================================

SECTION 87 — COPILOT DEVELOPMENT PRINCIPLE

============================================================

GitHub Copilot is an implementation assistant.

It is NOT the architect.

It must follow:

system constitution

architecture

domain contracts

coding standards

security rules

testing requirements

============================================================

SECTION 88 — COPILOT MUST READ FIRST

============================================================

Before generating code, Copilot must inspect:

README

architecture documentation

ADR documents

domain models

API contracts

existing implementations

tests

configuration

============================================================

SECTION 89 — COPILOT TASK SIZE

============================================================

Give Copilot small, bounded tasks.

Good:

"Implement the SignalValidationService

according to this interface and add unit tests."

Bad:

"Build the entire trading platform."

============================================================

SECTION 90 — COPILOT IMPLEMENTATION LOOP

============================================================

For every feature:

1\. Define requirement

2\. Define interface

3\. Define data contract

4\. Implement

5\. Add unit tests

6\. Run tests

7\. Review

8\. Refactor

9\. Add integration test

10\. Document

============================================================

SECTION 91 — COPILOT NEVER ASSUMES

============================================================

If an interface or business rule is unclear:

do not invent a critical trading rule.

Use the existing specification.

If still undefined:

mark it as TODO/decision-required

rather than silently inventing behavior.

============================================================

SECTION 92 — COPILOT CODE REVIEW

============================================================

Every generated implementation must be reviewed for:

correctness

security

race conditions

financial calculation correctness

idempotency

failure handling

logging

observability

test coverage

architecture compliance

============================================================

SECTION 93 — FINANCIAL CODE REVIEW

============================================================

Critical code receives additional scrutiny.

Especially:

position sizing

leverage

margin

liquidation

SL

TP

PnL

fees

slippage

risk

order quantity

price precision

============================================================

SECTION 94 — NO MAGIC NUMBERS

============================================================

Do not hard-code:

risk limits

leverage limits

fees

timeouts

thresholds

strategy parameters

Use validated configuration or domain constants.

============================================================

SECTION 95 — TYPE SAFETY

============================================================

Use strong types for critical concepts.

Avoid passing raw strings/numbers

where domain types are appropriate.

============================================================

SECTION 96 — MONEY REPRESENTATION

============================================================

Use appropriate decimal/fixed-precision

representation for financial calculations.

Do not use binary floating-point casually

for monetary calculations.

============================================================

SECTION 97 — LOGGING

============================================================

Use structured logs.

Include:

timestamp

service

component

event

correlation_id

severity

Never log:

API keys

secrets

private credentials

============================================================

SECTION 98 — OBSERVABILITY IN CODE

============================================================

Important operations must produce:

logs

metrics

traces

where appropriate.

============================================================

SECTION 99 — FEATURE FLAGS

============================================================

Use feature flags for dangerous capabilities.

Especially:

live trading

new strategies

new exchanges

experimental agents

============================================================

SECTION 100 — LIVE TRADING ENABLEMENT

============================================================

Live trading must be explicitly enabled.

Default:

DISABLED

Development:

DISABLED

Testing:

DISABLED

Paper:

ENABLED

Production:

EXPLICITLY ENABLED

============================================================

SECTION 101 — DEPLOYMENT ENVIRONMENTS

============================================================

Use:

LOCAL

DEVELOPMENT

TEST

STAGING

PAPER

PRODUCTION

Production must be isolated.

============================================================

SECTION 102 — STAGING

============================================================

Staging should closely reproduce production

without access to real trading funds.

============================================================

SECTION 103 — PAPER TRADING

============================================================

Paper trading must use:

realistic market data

fees

slippage

execution behavior

risk controls

============================================================

SECTION 104 — PRODUCTION DEPLOYMENT GATE

============================================================

Production deployment requires:

tests passing

security checks

migration validation

configuration validation

observability validation

rollback readiness

approval

============================================================

SECTION 105 — ROLLBACK

============================================================

Every deployment must have a rollback strategy.

Trading state must be handled safely during rollback.

============================================================

SECTION 106 — DATABASE BACKUPS

============================================================

Implement backup and recovery procedures

for critical persistent data.

============================================================

SECTION 107 — DISASTER RECOVERY

============================================================

Define recovery procedures for:

database loss

service failure

exchange failure

AI provider failure

message bus failure

infrastructure failure

============================================================

SECTION 108 — RECOVERY PRINCIPLE

============================================================

Recovery must preserve:

auditability

position accuracy

order accuracy

risk state

approval state

============================================================

SECTION 109 — RECONCILIATION AFTER RECOVERY

============================================================

After restart/recovery:

do not blindly resume trading.

Perform:

market synchronization

exchange synchronization

order reconciliation

position reconciliation

balance reconciliation

risk validation

system health validation

Then determine:

READY

DEGRADED

BLOCKED

============================================================

SECTION 110 — SECURITY TESTING

============================================================

Test:

authentication

authorization

RBAC

session security

API security

secret exposure

injection

rate limiting

audit integrity

approval authorization

execution authorization

============================================================

SECTION 111 — THREAT MODEL

============================================================

Threat-model:

AI prompt injection

malicious market data

malicious external content

compromised exchange credentials

unauthorized approval

duplicate execution

API abuse

model manipulation

data poisoning

insider misuse

============================================================

SECTION 112 — AI PROMPT INJECTION

============================================================

External content must never be treated as

trusted instructions.

News/social/web content is DATA.

It must never override system instructions.

============================================================

SECTION 113 — DATA POISONING

============================================================

External market and alternative data

must pass validation.

Suspicious anomalies must be flagged.

============================================================

SECTION 114 — DEPENDENCY MANAGEMENT

============================================================

Pin or appropriately constrain production

dependencies.

Monitor vulnerabilities.

Update dependencies through controlled changes.

============================================================

SECTION 115 — PERFORMANCE TESTING

============================================================

Measure:

market-data throughput

agent throughput

signal latency

risk latency

approval latency

execution latency

database performance

============================================================

SECTION 116 — LOAD TESTING

============================================================

Test:

high market-data volume

many simultaneous signals

multiple open positions

multiple concurrent users

high alert volume

============================================================

SECTION 117 — CONCURRENCY

============================================================

Test concurrent:

signal generation

risk evaluation

approval

order updates

position updates

reconciliation

============================================================

SECTION 118 — DATA CONSISTENCY

============================================================

The system must maintain consistent state between:

market data

signals

risk

orders

positions

balances

audit

============================================================

SECTION 119 — TEST DATA

============================================================

Maintain deterministic fixtures for:

markets

orders

positions

signals

risk scenarios

exchange responses

============================================================

SECTION 120 — MOCK EXCHANGE

============================================================

Create a mock exchange adapter for testing.

Support:

order acceptance

rejection

partial fills

full fills

timeouts

duplicate responses

network failures

position updates

============================================================

SECTION 121 — BACKTEST DATA VERSIONING

============================================================

Track the exact dataset version used

for every backtest.

Record:

dataset

period

source

version

parameters

============================================================

SECTION 122 — REPRODUCIBILITY

============================================================

A historical signal/backtest must be reproducible.

Store:

strategy version

parameters

dataset version

agent versions

model versions

prompt versions

configuration

============================================================

SECTION 123 — EXPERIMENT TRACKING

============================================================

Track strategy experiments.

Every experiment should include:

hypothesis

parameters

dataset

results

evaluation metrics

conclusion

============================================================

SECTION 124 — MODEL EVALUATION

============================================================

Evaluate AI agents separately.

Metrics may include:

classification accuracy

agreement

evidence quality

calibration

latency

failure rate

cost

Do not equate these metrics directly

with trading profitability.

============================================================

SECTION 125 — STRATEGY EVALUATION

============================================================

Evaluate strategies using:

win rate

expectancy

profit factor

Sharpe

Sortino

max drawdown

trade count

fees

slippage

regime performance

============================================================

SECTION 126 — LIVE PERFORMANCE

============================================================

Track live strategy performance separately

from historical performance.

============================================================

SECTION 127 — PAPER/LIVE SEPARATION

============================================================

Never combine paper and live trades into

one performance dataset without explicit labeling.

============================================================

SECTION 128 — RELEASE PROCESS

============================================================

Each release must have:

version

release notes

migration notes

configuration changes

risk changes

known issues

rollback plan

============================================================

SECTION 129 — RELEASE APPROVAL

============================================================

Trading-critical releases require additional

review before enabling live trading.

============================================================

SECTION 130 — IMPLEMENTATION ROADMAP

============================================================

Execute implementation in the following

engineering sequence.

STAGE A

Repository and development foundation

STAGE B

Core domain and contracts

STAGE C

Persistence and infrastructure

STAGE D

Market data platform

STAGE E

Analysis engines

STAGE F

Agent orchestration

STAGE G

Strategy and signal engine

STAGE H

Backtesting and validation

STAGE I

Risk and portfolio

STAGE J

Human approval

STAGE K

Paper execution

STAGE L

Exchange integration

STAGE M

Live execution safeguards

STAGE N

Frontend

STAGE O

Observability and operational hardening

STAGE P

Production readiness

============================================================

SECTION 131 — STAGE A

============================================================

Create:

repository

development environment

coding standards

CI

basic documentation

configuration framework

logging framework

testing framework

Acceptance:

project builds

tests execute

CI passes

============================================================

SECTION 132 — STAGE B

============================================================

Implement:

domain entities

value objects

enums

state machines

contracts

events

Acceptance:

domain tests pass.

============================================================

SECTION 133 — STAGE C

============================================================

Implement:

database

migrations

repositories

message infrastructure

cache where required

audit persistence

Acceptance:

integration tests pass.

============================================================

SECTION 134 — STAGE D

============================================================

Implement:

market-data connectors

normalization

validation

storage

streaming

quality monitoring

Acceptance:

historical and real-time data

are available to downstream systems.

============================================================

SECTION 135 — STAGE E

============================================================

Implement analysis modules:

technical

fundamental

SMC

Wyckoff

Fibonacci

sentiment

on-chain

derivatives

quant

Acceptance:

each engine independently tested.

============================================================

SECTION 136 — STAGE F

============================================================

Implement:

agent registry

agent lifecycle

agent execution

agent contracts

orchestration

timeouts

retries

failure handling

Acceptance:

multi-agent analysis executes

deterministically from a given input snapshot.

============================================================

SECTION 137 — STAGE G

============================================================

Implement:

strategy registry

strategy engine

signal generation

confluence

evidence collection

signal lifecycle

Acceptance:

candidate signals are generated

with complete structured evidence.

============================================================

SECTION 138 — STAGE H

============================================================

Implement:

backtesting

walk-forward

out-of-sample

cost modeling

anti-overfitting

performance reporting

Acceptance:

strategy validation is reproducible.

============================================================

SECTION 139 — STAGE I

============================================================

Implement:

risk engine

position sizing

portfolio exposure

leverage controls

SL/TP validation

drawdown controls

concentration

Acceptance:

invalid trades are deterministically rejected.

============================================================

SECTION 140 — STAGE J

============================================================

Implement:

trade candidates

approval workflow

user modifications

revalidation

approval state

audit

Acceptance:

no approval = no execution.

============================================================

SECTION 141 — STAGE K

============================================================

Implement paper execution.

Acceptance:

complete trading lifecycle works

without real funds.

============================================================

SECTION 142 — STAGE L

============================================================

Implement:

CCXT abstraction

exchange adapters

order management

fill handling

reconciliation

Acceptance:

exchange integration works against

sandbox/test environments where available.

============================================================

SECTION 143 — STAGE M

============================================================

Implement:

kill switches

execution gates

production configuration

final risk checks

emergency controls

Acceptance:

safety tests pass.

============================================================

SECTION 144 — STAGE N

============================================================

Implement Chat 11 frontend.

Acceptance:

human can:

observe

analyze

inspect evidence

configure trade

review risk

approve/reject

monitor execution

monitor positions

============================================================

SECTION 145 — STAGE O

============================================================

Implement:

metrics

dashboards

alerts

tracing

runbooks

incident handling

reconciliation monitoring

Acceptance:

operators can understand system state.

============================================================

SECTION 146 — STAGE P

============================================================

Production readiness review.

Verify:

security

performance

reliability

observability

risk

execution

audit

backup

recovery

documentation

============================================================

SECTION 147 — PRODUCTION GO-LIVE GATE

============================================================

LIVE TRADING MUST NOT BE ENABLED merely because

the application builds.

Require:

functional validation

risk validation

security validation

paper trading validation

execution validation

reconciliation validation

observability validation

operational readiness

human approval

============================================================

SECTION 148 — FINAL LIVE TRADING CHECKLIST

============================================================

\[ \] Market data reliable

\[ \] Alternative data reliable

\[ \] Analysis engines validated

\[ \] Agents validated

\[ \] Strategies validated

\[ \] Backtests reproducible

\[ \] Out-of-sample validation complete

\[ \] Walk-forward validation complete

\[ \] Risk engine validated

\[ \] Approval workflow validated

\[ \] Paper trading validated

\[ \] Exchange adapter validated

\[ \] Reconciliation validated

\[ \] Kill switch validated

\[ \] Security validated

\[ \] Audit validated

\[ \] Monitoring operational

\[ \] Alerts operational

\[ \] Backup operational

\[ \] Recovery tested

\[ \] Rollback tested

\[ \] Human supervisor trained

\[ \] Production approval granted

============================================================

SECTION 149 — DEFINITION OF DONE

============================================================

A feature is NOT complete when code compiles.

A feature is complete only when:

\[ \] Requirement implemented

\[ \] Architecture compliant

\[ \] Domain contract defined

\[ \] Unit tests added

\[ \] Integration tests added where required

\[ \] Error handling implemented

\[ \] Security reviewed

\[ \] Observability added

\[ \] Documentation updated

\[ \] CI passes

\[ \] Code reviewed

\[ \] Acceptance criteria passed

============================================================

SECTION 150 — TRADING FEATURE DEFINITION OF DONE

============================================================

For any trading-critical feature additionally require:

\[ \] Risk impact analyzed

\[ \] Failure modes analyzed

\[ \] Idempotency reviewed

\[ \] Financial calculations reviewed

\[ \] Audit events implemented

\[ \] Reconciliation behavior defined

\[ \] Kill-switch interaction tested

\[ \] Human approval interaction tested

============================================================

SECTION 151 — COPILOT PROMPT TEMPLATE

============================================================

For every implementation task use this structure:

PROJECT CONTEXT:

\[Relevant architecture\]

TASK:

\[One bounded implementation task\]

REQUIREMENTS:

\[Exact requirements\]

INTERFACES:

\[Existing interfaces\]

CONSTRAINTS:

\[Security/safety/architecture constraints\]

INPUTS:

\[Input contract\]

OUTPUTS:

\[Output contract\]

ERRORS:

\[Expected failure modes\]

TEST REQUIREMENTS:

\[Required tests\]

OBSERVABILITY:

\[Required logs/metrics/traces\]

ACCEPTANCE CRITERIA:

\[Explicit conditions\]

============================================================

SECTION 152 — EXAMPLE COPILOT TASK

============================================================

TASK:

Implement SignalValidationService.

CONSTRAINTS:

\- Must not execute trades.

\- Must not bypass risk.

\- Must use strategy validation results.

\- Must verify data freshness.

\- Must verify historical validation.

\- Must return structured validation status.

\- Must produce audit information.

TEST:

\- valid signal

\- invalid signal

\- stale data

\- failed backtest

\- insufficient sample

\- regime mismatch

\- contradictory evidence

============================================================

SECTION 153 — COPILOT REVIEW PROMPT

============================================================

After implementation ask Copilot:

"Review this implementation against the project

architecture and requirements.

Identify:

1\. Architecture violations

2\. Security issues

3\. Financial calculation risks

4\. Race conditions

5\. State-management issues

6\. Idempotency problems

7\. Error-handling gaps

8\. Missing tests

9\. Observability gaps

10\. Documentation gaps

Do not rewrite immediately.

First provide the findings."

============================================================

SECTION 154 — COPILOT TEST PROMPT

============================================================

Ask Copilot:

"Generate tests for this implementation.

Cover:

happy paths

edge cases

invalid inputs

failure modes

concurrency

idempotency

security

state transitions

financial precision

external dependency failures."

============================================================

SECTION 155 — COPILOT SECURITY REVIEW

============================================================

Ask Copilot:

"Perform a security review.

Check for:

secret exposure

authorization bypass

injection

unsafe deserialization

untrusted AI output

prompt injection

unsafe external content

logging of sensitive data

insecure configuration

privilege escalation."

============================================================

SECTION 156 — COPILOT TRADING SAFETY REVIEW

============================================================

Ask Copilot:

"Review this code as a financial trading

system component.

Verify:

\- no unauthorized execution

\- no risk bypass

\- no approval bypass

\- no duplicate execution

\- no unsafe retry

\- no stale data usage

\- no unsafe fallback

\- correct financial precision

\- correct state transitions

\- complete auditability."

============================================================

SECTION 157 — CODE QUALITY RULE

============================================================

Prefer:

simple

explicit

testable

maintainable

observable

modular

code.

Avoid unnecessary abstraction.

============================================================

SECTION 158 — DO NOT OVERENGINEER

============================================================

Do not create abstractions without a real

architectural requirement.

Enterprise-grade does NOT mean unnecessarily

complex.

============================================================

SECTION 159 — DO NOT UNDERENGINEER

============================================================

Do not simplify away:

risk

security

audit

validation

reconciliation

observability

approval

failure recovery

============================================================

SECTION 160 — FINAL SYSTEM DEVELOPMENT LOOP

============================================================

REQUIREMENT

↓

DESIGN

↓

CONTRACT

↓

IMPLEMENT

↓

TEST

↓

REVIEW

↓

INTEGRATE

↓

OBSERVE

↓

VALIDATE

↓

DOCUMENT

↓

RELEASE

============================================================

SECTION 161 — FINAL TRADING LIFECYCLE

============================================================

MARKET DATA

↓

DATA QUALITY

↓

MULTI-AI ANALYSIS

↓

META-ANALYSIS

↓

STRATEGY

↓

SIGNAL

↓

EVIDENCE

↓

HISTORICAL VALIDATION

↓

OUT-OF-SAMPLE

↓

WALK-FORWARD

↓

RISK

↓

TRADE CANDIDATE

↓

HUMAN CONFIGURATION

↓

REVALIDATION

↓

HUMAN APPROVAL

↓

SAFETY GATE

↓

EXECUTION

↓

EXCHANGE

↓

RECONCILIATION

↓

POSITION MANAGEMENT

↓

CLOSURE

↓

PERFORMANCE

↓

AUDIT

============================================================

SECTION 162 — FINAL NON-NEGOTIABLE SAFETY RULES

============================================================

NO APPROVAL

=

NO LIVE TRADE

RISK FAILURE

=

NO LIVE TRADE

STALE CRITICAL DATA

=

NO LIVE TRADE

SAFETY BLOCK

=

NO LIVE TRADE

UNKNOWN EXCHANGE STATE

=

NO LIVE TRADE

POSITION MISMATCH

=

NO NEW LIVE TRADE

EXPIRED SIGNAL

=

NO LIVE TRADE

EXPIRED APPROVAL

=

NO LIVE TRADE

INVALID AI OUTPUT

=

NO LIVE TRADE

AI FAILURE

=

NO AUTOMATIC UNSAFE FALLBACK

KILL SWITCH

=

EXECUTION BLOCKED

USER MODIFIES MATERIAL PARAMETERS

=

REVALIDATION REQUIRED

============================================================

SECTION 163 — FINAL ARCHITECTURAL PRINCIPLE

============================================================

AI provides intelligence.

Quantitative systems provide validation.

Risk systems provide constraints.

Safety systems provide enforcement.

The human provides final authorization.

Execution systems execute only authorized,

validated, risk-compliant trades.

============================================================

SECTION 164 — FINAL PROJECT COMPLETION CRITERIA

============================================================

The platform is considered production-ready

only when it can demonstrate:

1\. Reliable market-data ingestion.

2\. Multi-dimensional market analysis.

3\. Multi-agent independent reasoning.

4\. Meta-analysis and evidence aggregation.

5\. Reproducible strategy evaluation.

6\. Proper out-of-sample validation.

7\. Walk-forward validation.

8\. Anti-overfitting controls.

9\. Deterministic risk enforcement.

10\. Human-controlled trade configuration.

11\. Mandatory human approval.

12\. Safe execution.

13\. Exchange reconciliation.

14\. Real-time monitoring.

15\. Complete audit trail.

16\. Security controls.

17\. Failure recovery.

18\. Emergency controls.

19\. Paper-trading validation.

20\. Production operational readiness.

============================================================

SECTION 165 — FINAL DEVELOPMENT ORDER

============================================================

DO NOT SKIP AHEAD.

Implement in order:

FOUNDATION

→ DOMAIN

→ DATA

→ ANALYSIS

→ AGENTS

→ STRATEGIES

→ VALIDATION

→ BACKTESTING

→ RISK

→ APPROVAL

→ PAPER TRADING

→ EXECUTION

→ FRONTEND

→ OBSERVABILITY

→ SECURITY HARDENING

→ PRODUCTION

============================================================

SECTION 166 — END OF ORIGINAL 12-CHAT PLAYBOOK

============================================================

Chats 1–12 now form the complete

enterprise-grade design and implementation

playbook for the supervised autonomous AI

crypto trading platform.

The next activity is NOT another architecture chat.

The next activity is implementation.

Use this playbook as the governing specification

for GitHub Copilot.

============================================================

END

============================================================
