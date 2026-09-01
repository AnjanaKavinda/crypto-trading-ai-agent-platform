# Chat 11 — Frontend, Dashboard & Trader UX

> Full source-derived Chat 11 content from the uploaded Master Playbook v2.2 DOCX. This is not a summary. Source Markdown lines 34288–38411 of the complete conversion.

---

Master Prompt — Chat 11

V2.1 INLINE UPGRADE - CHAT 11 FRONTEND, DASHBOARD & TRADER UX

## V2.2 UI METHODOLOGY EXPLANATION REQUIREMENT

The trader UI must explain each signal using the methodology categories: Fundamental, Technical, On-Chain, Sentiment, Derivatives/Order Flow, Regime, Event Risk, and Adversarial Review.

The UI should group technical indicators by purpose: volume/structure, trend, momentum, volatility/risk, and volume confirmation.

For each visible indicator, the UI should show what it measures, why it matters, what regime it works best in, and its failure modes. It must not present indicator output as a guarantee.

The Evidence Report UI must distinguish educational explanation from validated statistical evidence.

Purpose: make the frontend a professional supervision cockpit. The UI displays, requests, configures, approves, rejects, and monitors; it does not become the trading brain.

Retained Scope

Preserve overview, markets, AI analysis, signals, trade approval, positions, portfolio, orders, strategies, backtesting, risk, AI agents, system health, alerts, audit, and settings.

Preserve human as final decision-maker and backend as authoritative.

v2.1 Corrections and Enhancements

Add explicit Evidence Report, Evidence Graph, Decision Provenance, and data freshness display.

Add No-Trade/Abstention UI with reason codes and suggested next actions.

Add adversarial review panel showing counter-thesis, failure conditions, contradictory evidence, event risk, and limitations.

Add risk editor with recalculation status and stale-approval warnings.

Add System Awareness dashboard for data health, market regime, agent health, strategy health, validation freshness, drift, execution health, exchange health, portfolio risk, unknowns, and operational state.

Add agent performance, strategy decay, learning insights, experiment status, and governance queue views.

Chat 11 Required Contracts

SignalViewModel, EvidenceReportView, RiskProposalView, ApprovalView, NoTradeView, AgentHealthView, SystemAwarenessView, StrategyPerformanceView, AuditTimelineView, ExecutionMonitorView, GovernanceQueueView.

Acceptance Criteria

The UI cannot silently approve or execute trades.

Every approved trade screen shows evidence, validation, risk, warnings, conflicts, adversarial review, and exact approved parameters.

The UI never displays historical win rate as guaranteed probability.

\# ============================================================

\# ENTERPRISE-GRADE SUPERVISED AUTONOMOUS CRYPTO TRADING SYSTEM

\# ============================================================

\#

\# GITHUB COPILOT IMPLEMENTATION PLAYBOOK

\#

\# CHAT 11

\# FRONTEND, DASHBOARD & TRADER UX

\#

\# ============================================================

============================================================

PROJECT CONTINUITY

============================================================

You are continuing the same enterprise-grade

supervised autonomous AI crypto trading platform.

DO NOT redesign the previously completed architecture.

The original 12-chat playbook is authoritative.

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

CHAT 6

Strategy Engine, Signal Generation &

75%+ Evidence/Validation

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

CURRENT:

CHAT 11

Frontend, Dashboard & Trader UX

NEXT:

CHAT 12

Implementation Roadmap, Repository Structure,

Testing & GitHub Copilot Coding Protocol

============================================================

CHAT 11 OBJECTIVE

============================================================

Design the complete professional trader-facing

frontend and user experience.

The frontend must allow the human supervisor to:

\- monitor markets

\- inspect AI analysis

\- inspect trading signals

\- inspect evidence

\- inspect historical validation

\- inspect risk

\- modify permitted trade parameters

\- approve/reject trades

\- monitor execution

\- monitor positions

\- monitor portfolio

\- monitor system health

\- monitor AI agents

\- monitor safety controls

\- inspect audit history

============================================================

CORE UX PRINCIPLE

============================================================

The UI is NOT the trading brain.

The backend remains authoritative.

Frontend:

DISPLAY

REQUEST

CONFIGURE

APPROVE

REJECT

MONITOR

The frontend must NEVER independently calculate

critical trading decisions.

============================================================

HUMAN SUPERVISION MODEL

============================================================

The user is the final decision-maker.

The system may:

ANALYZE

PROPOSE

VALIDATE

WARN

RECOMMEND

BUT:

NO APPROVAL

=

NO LIVE TRADE

============================================================

SECTION 1 — APPLICATION SHELL

============================================================

Create a professional trading application shell.

Primary areas:

1\. Overview

2\. Markets

3\. AI Analysis

4\. Signals

5\. Trade Approval

6\. Positions

7\. Portfolio

8\. Orders

9\. Strategies

10\. Backtesting

11\. Risk

12\. AI Agents

13\. System Health

14\. Alerts

15\. Audit

16\. Settings

============================================================

SECTION 2 — GLOBAL HEADER

============================================================

Display:

\- application name

\- environment

\- system safety state

\- trading readiness

\- exchange connectivity

\- market-data status

\- active alerts

\- user profile

\- authentication state

============================================================

SECTION 3 — TRADING STATUS

============================================================

Always visibly show:

TRADING:

ENABLED

RESTRICTED

BLOCKED

EMERGENCY STOP

============================================================

SECTION 4 — SYSTEM SAFETY STATUS

============================================================

Show:

NORMAL

DEGRADED

RESTRICTED

BLOCKED

EMERGENCY

============================================================

SECTION 5 — EXCHANGE STATUS

============================================================

Display:

\- exchange

\- connectivity

\- API health

\- websocket health

\- latency

\- rate-limit state

\- synchronization state

============================================================

SECTION 6 — MARKET OVERVIEW

============================================================

Provide market overview:

\- BTC

\- ETH

\- major pairs

\- selected watchlist

\- market regime

\- volatility

\- volume

\- funding

\- open interest

============================================================

SECTION 7 — MARKET WATCHLIST

============================================================

Allow the user to create watchlists.

Each asset may display:

\- price

\- 24h change

\- volume

\- volatility

\- funding

\- open interest

\- AI signal state

\- trend state

============================================================

SECTION 8 — MARKET DETAIL

============================================================

For each selected asset provide:

price chart

volume

indicators

order book

trades

funding

open interest

liquidations

market structure

============================================================

SECTION 9 — MULTI-TIMEFRAME VIEW

============================================================

Support:

1m

5m

15m

30m

1h

4h

1D

1W

where supported by backend data.

============================================================

SECTION 10 — TECHNICAL ANALYSIS PANEL

============================================================

Display backend-generated:

\- trend

\- EMA

\- SMA

\- RSI

\- MACD

\- ATR

\- Bollinger Bands

\- support

\- resistance

\- volume analysis

\- momentum

\- volatility

============================================================

SECTION 11 — SMART MONEY CONCEPT PANEL

============================================================

Display:

\- market structure

\- BOS

\- CHoCH

\- liquidity zones

\- order blocks

\- fair value gaps

\- premium/discount

\- equal highs

\- equal lows

\- liquidity sweeps

============================================================

SECTION 12 — WYCKOFF PANEL

============================================================

Display:

\- accumulation

\- markup

\- distribution

\- markdown

\- phase classification

\- spring

\- upthrust

\- volume/price relationship

============================================================

SECTION 13 — FIBONACCI PANEL

============================================================

Display relevant:

\- retracement levels

\- extension levels

\- confluence zones

============================================================

SECTION 14 — FUNDAMENTAL ANALYSIS PANEL

============================================================

Display backend-generated:

\- project fundamentals

\- tokenomics

\- supply

\- emissions

\- unlocks

\- ecosystem activity

\- development activity

\- adoption

\- network metrics

\- protocol revenue where available

\- risks

\- catalysts

============================================================

SECTION 15 — SENTIMENT PANEL

============================================================

Display:

\- social sentiment

\- news sentiment

\- market sentiment

\- fear/greed

\- sentiment trend

\- sentiment confidence

Clearly distinguish:

OBSERVED DATA

from:

AI INTERPRETATION.

============================================================

SECTION 16 — ON-CHAIN PANEL

============================================================

Where available:

\- active addresses

\- transaction activity

\- exchange inflows

\- exchange outflows

\- whale activity

\- holder distribution

\- realized metrics

\- network activity

============================================================

SECTION 17 — DERIVATIVES PANEL

============================================================

Display:

\- funding rate

\- open interest

\- liquidations

\- long/short ratio

\- basis

\- estimated leverage

\- derivatives positioning

============================================================

SECTION 18 — MARKET REGIME

============================================================

Display detected regime:

TRENDING_BULLISH

TRENDING_BEARISH

RANGING

HIGH_VOLATILITY

LOW_VOLATILITY

ACCUMULATION

DISTRIBUTION

UNKNOWN

============================================================

SECTION 19 — AI AGENT CONSENSUS

============================================================

Show every relevant agent independently.

Example:

Technical Agent

BULLISH

SMC Agent

BULLISH

Wyckoff Agent

NEUTRAL

Fundamental Agent

BULLISH

Sentiment Agent

BEARISH

Quant Agent

BULLISH

============================================================

SECTION 20 — AGENT DISAGREEMENT

============================================================

Make disagreement visible.

Example:

4 / 6 agents bullish

1 / 6 neutral

1 / 6 bearish

Do NOT hide disagreement behind a single

AI-generated score.

============================================================

SECTION 21 — AI REASONING DISPLAY

============================================================

Display concise evidence and reasoning.

Do not expose hidden chain-of-thought.

Show:

\- conclusions

\- supporting evidence

\- indicators

\- data references

\- confidence metadata

\- contradictions

\- risks

============================================================

SECTION 22 — SIGNAL CENTER

============================================================

Create a central:

SIGNAL CENTER

Every candidate trade appears here.

============================================================

SECTION 23 — SIGNAL CARD

============================================================

Each signal must show:

\- signal ID

\- asset

\- direction

\- strategy

\- timeframe

\- entry zone

\- stop loss

\- take profit

\- risk/reward

\- validation status

\- historical performance

\- sample size

\- out-of-sample result

\- confidence

\- evidence score

\- signal expiration

\- timestamp

============================================================

SECTION 24 — 75%+ SIGNAL REQUIREMENT

============================================================

The UI must NOT display:

"75% guaranteed"

or:

"75% chance of profit"

Instead display the exact validated metric.

Example:

Historical Win Rate:

78.4%

Sample:

1,247 trades

Out-of-Sample:

74.1%

Walk-Forward:

76.3%

Current Regime:

Compatible

Validation:

PASSED

============================================================

SECTION 25 — EVIDENCE REPORT

============================================================

Every high-quality signal must have:

EVIDENCE REPORT

Include:

1\. Technical Evidence

2\. Fundamental Evidence

3\. SMC Evidence

4\. Wyckoff Evidence

5\. Fibonacci Evidence

6\. Sentiment Evidence

7\. On-Chain Evidence

8\. Derivatives Evidence

9\. Quantitative Evidence

10\. Strategy Evidence

11\. Historical Evidence

12\. Risk Evidence

13\. Contradictory Evidence

============================================================

SECTION 26 — EVIDENCE STRENGTH

============================================================

Each evidence item should have:

\- source

\- timestamp

\- direction

\- strength

\- relevance

\- reliability

============================================================

SECTION 27 — SIGNAL DECISION

============================================================

Display:

STRONG BUY

BUY

WEAK BUY

NEUTRAL

WEAK SELL

SELL

STRONG SELL

NO TRADE

The frontend must display backend decision.

It must not independently determine it.

============================================================

SECTION 28 — SIGNAL FILTERING

============================================================

Allow filtering by:

asset

direction

strategy

timeframe

market regime

validation status

win rate

risk/reward

confidence

signal age

============================================================

SECTION 29 — SIGNAL DETAILS

============================================================

Clicking a signal opens full analysis.

Sections:

Overview

Market Context

Technical

SMC

Wyckoff

Fundamental

Sentiment

On-Chain

Derivatives

Quant

Backtest

Validation

Risk

Evidence

Conflicts

Recommendation

============================================================

SECTION 30 — TRADE CANDIDATE

============================================================

A validated signal becomes:

TRADE CANDIDATE

It is NOT yet an executable trade.

============================================================

SECTION 31 — TRADE CONFIGURATION

============================================================

Allow the human to configure permitted inputs:

\- position size

\- capital allocation

\- leverage

\- entry type

\- stop loss

\- take profit

\- trailing stop if supported

\- maximum slippage

\- time-in-force

============================================================

SECTION 32 — PARAMETER VALIDATION

============================================================

Whenever the user changes:

amount

leverage

stop loss

take profit

entry

risk settings

the backend must recalculate:

\- risk

\- liquidation estimate

\- margin

\- exposure

\- risk/reward

\- portfolio impact

============================================================

SECTION 33 — FRONTEND MUST NOT TRUST LOCAL CALCULATIONS

============================================================

The UI may display preview calculations.

Final validation must come from backend.

Backend is authoritative.

============================================================

SECTION 34 — PARAMETER CHANGE WARNING

============================================================

If user changes AI-recommended values:

show:

"User-modified parameter"

Example:

AI Recommended Leverage:

3x

User Selected:

5x

Status:

MODIFIED

REQUIRES REVALIDATION

============================================================

SECTION 35 — APPROVAL SCREEN

============================================================

Create a dedicated:

TRADE APPROVAL GATE

Show all final parameters.

============================================================

SECTION 36 — APPROVAL SUMMARY

============================================================

Display:

Asset

Direction

Entry

Stop Loss

Take Profit

Position Size

Capital

Leverage

Estimated Margin

Maximum Loss

Risk/Reward

Expected Fees

Estimated Slippage

Strategy

Signal ID

Risk Status

Validation Status

============================================================

SECTION 37 — APPROVAL CHECKLIST

============================================================

Before approval show:

\[ \] Signal validated

\[ \] Strategy validated

\[ \] Risk validated

\[ \] Data fresh

\[ \] Market conditions acceptable

\[ \] Exchange healthy

\[ \] Execution ready

\[ \] No critical safety alerts

\[ \] User parameters validated

============================================================

SECTION 38 — APPROVAL ACTIONS

============================================================

Provide:

APPROVE TRADE

REJECT TRADE

MODIFY TRADE

CANCEL

============================================================

SECTION 39 — APPROVAL CONFIRMATION

============================================================

For live execution:

require explicit confirmation.

Example:

"I understand this order may result in financial loss."

Do not use deceptive UI patterns.

============================================================

SECTION 40 — APPROVAL IMMUTABILITY

============================================================

After approval:

the approved configuration is immutable.

Changing:

leverage

size

SL

TP

entry

requires:

new validation

new approval

============================================================

SECTION 41 — EXECUTION MONITOR

============================================================

After approval show:

ORDER SUBMITTED

ORDER ACCEPTED

PARTIALLY FILLED

FILLED

CANCELLED

REJECTED

UNKNOWN

============================================================

SECTION 42 — LIVE ORDER MONITOR

============================================================

Display:

\- order ID

\- exchange order ID

\- symbol

\- side

\- order type

\- requested price

\- executed price

\- requested quantity

\- executed quantity

\- remaining quantity

\- fees

\- slippage

\- status

\- timestamps

============================================================

SECTION 43 — POSITION MONITOR

============================================================

Display:

\- symbol

\- direction

\- size

\- entry

\- current price

\- unrealized PnL

\- realized PnL

\- leverage

\- margin

\- liquidation price

\- stop loss

\- take profit

\- exposure

============================================================

SECTION 44 — PORTFOLIO DASHBOARD

============================================================

Display:

\- total equity

\- available balance

\- used margin

\- unrealized PnL

\- realized PnL

\- daily PnL

\- drawdown

\- exposure

\- leverage

\- concentration

============================================================

SECTION 45 — PORTFOLIO RISK

============================================================

Show:

portfolio risk

asset concentration

strategy concentration

correlation exposure

margin utilization

drawdown

============================================================

SECTION 46 — RISK DASHBOARD

============================================================

Display:

Daily Loss Limit

Current Daily Loss

Maximum Drawdown

Current Drawdown

Position Limit

Current Exposure

Leverage Limit

Current Leverage

Margin Utilization

============================================================

SECTION 47 — RISK WARNINGS

============================================================

Show prominent warnings for:

\- excessive leverage

\- excessive concentration

\- high volatility

\- insufficient margin

\- poor risk/reward

\- portfolio correlation

\- liquidation proximity

============================================================

SECTION 48 — ACTIVE TRADE VIEW

============================================================

Each active trade must show:

Original Signal

Approved Configuration

Current Position

Live Risk

PnL

Market Conditions

AI Monitoring

Risk Monitoring

Execution Status

============================================================

SECTION 49 — TRADE TIMELINE

============================================================

Provide chronological timeline:

Signal Generated

Analysis Completed

Validation Completed

Risk Approved

User Modified

Risk Revalidated

User Approved

Order Submitted

Order Accepted

Order Filled

Position Opened

Position Managed

Position Closed

============================================================

SECTION 50 — AI AGENT DASHBOARD

============================================================

Show:

Agent

Status

Last Run

Latency

Success Rate

Failure Rate

Current Task

Model

Version

============================================================

SECTION 51 — AGENT STATUS

============================================================

States:

RUNNING

IDLE

DEGRADED

FAILED

DISABLED

BLOCKED

============================================================

SECTION 52 — AGENT DETAIL

============================================================

Show:

agent purpose

current status

model

version

prompt version

tools

last execution

errors

performance metrics

Do not expose sensitive internal credentials.

============================================================

SECTION 53 — STRATEGY DASHBOARD

============================================================

Show:

\- strategy name

\- version

\- status

\- assets

\- timeframes

\- historical win rate

\- out-of-sample performance

\- walk-forward performance

\- drawdown

\- sample size

\- current regime compatibility

============================================================

SECTION 54 — STRATEGY COMPARISON

============================================================

Allow comparison of validated strategies.

Metrics:

Win Rate

Profit Factor

Expectancy

Sharpe

Sortino

Max Drawdown

Trade Count

Average Win

Average Loss

Regime Performance

============================================================

SECTION 55 — BACKTEST VIEW

============================================================

Display:

\- strategy

\- period

\- market

\- timeframe

\- trades

\- win rate

\- expectancy

\- profit factor

\- drawdown

\- Sharpe

\- Sortino

\- out-of-sample results

\- walk-forward results

============================================================

SECTION 56 — ANTI-OVERFITTING DISPLAY

============================================================

Explicitly display:

IN-SAMPLE

OUT-OF-SAMPLE

WALK-FORWARD

PAPER/LIVE

Do not allow users to confuse them.

============================================================

SECTION 57 — PERFORMANCE DECOMPOSITION

============================================================

Show performance by:

market regime

asset

timeframe

long/short

strategy

month

volatility regime

============================================================

SECTION 58 — ALERT CENTER

============================================================

Create:

ALERT CENTER

Categories:

MARKET

TRADING

RISK

AI

SECURITY

SYSTEM

EXECUTION

============================================================

SECTION 59 — ALERT SEVERITY

============================================================

INFO

WARNING

HIGH

CRITICAL

============================================================

SECTION 60 — CRITICAL ALERTS

============================================================

Critical alerts must be highly visible.

Examples:

Emergency Stop

Exchange Failure

Position Mismatch

Unauthorized Execution Attempt

Risk Limit Breach

Security Incident

Reconciliation Failure

============================================================

SECTION 61 — SYSTEM HEALTH DASHBOARD

============================================================

Display:

Market Data

AI Agents

Database

Message Queue

Risk

Approval

Execution

Exchange

Audit

Security

============================================================

SECTION 62 — HEALTH STATES

============================================================

HEALTHY

DEGRADED

UNHEALTHY

UNKNOWN

============================================================

SECTION 63 — TRADING READINESS

============================================================

Show:

TRADING READINESS

Components:

Market Data

Risk

Approval

Execution

Exchange

Database

Queue

Audit

Security

Overall:

READY

DEGRADED

BLOCKED

EMERGENCY

UNKNOWN

============================================================

SECTION 64 — SAFETY CONTROL PANEL

============================================================

Authorized users may view:

Global Risk Kill Switch

Execution Kill Switch

Agent Kill Switches

Circuit Breakers

Emergency Mode

============================================================

SECTION 65 — KILL SWITCH UI

============================================================

Display current state.

For authorized users provide:

ACTIVATE

DEACTIVATE

with explicit confirmation.

============================================================

SECTION 66 — KILL SWITCH AUDIT

============================================================

Every change must display:

who

when

reason

previous state

new state

============================================================

SECTION 67 — AUDIT DASHBOARD

============================================================

Provide searchable audit history.

Filters:

date

user

trade

signal

agent

strategy

event

severity

exchange

correlation ID

============================================================

SECTION 68 — DECISION TRACE UI

============================================================

For every trade provide:

MARKET DATA

↓

ANALYSIS

↓

SIGNAL

↓

VALIDATION

↓

RISK

↓

USER MODIFICATION

↓

APPROVAL

↓

EXECUTION

↓

EXCHANGE

↓

FILL

↓

POSITION

============================================================

SECTION 69 — CORRELATION ID

============================================================

Allow authorized users to search:

correlation_id

This should retrieve the complete

decision lifecycle.

============================================================

SECTION 70 — SECURITY DASHBOARD

============================================================

Display security state:

Authentication

Authorization

API Connectivity

Credential Status

Security Alerts

Recent Security Events

Never expose secrets.

============================================================

SECTION 71 — SETTINGS

============================================================

Provide settings for:

\- user preferences

\- watchlists

\- default chart settings

\- notification preferences

\- trading defaults

\- display preferences

Critical safety/risk settings require

backend authorization.

============================================================

SECTION 72 — TRADING DEFAULTS

============================================================

Allow configurable defaults for:

\- default position amount

\- default leverage

\- default stop loss

\- default take profit

\- preferred order type

But:

defaults are NOT approvals.

Every live trade must pass backend validation.

============================================================

SECTION 73 — RESPONSIVE DESIGN

============================================================

Support:

desktop

tablet

mobile

Desktop is the primary professional

trading interface.

============================================================

SECTION 74 — REAL-TIME UPDATES

============================================================

Use appropriate real-time communication

for:

\- prices

\- order status

\- positions

\- PnL

\- alerts

\- agent status

\- system status

Do not use inefficient polling where

real-time streaming is appropriate.

============================================================

SECTION 75 — DATA FRESHNESS

============================================================

Display freshness for critical data.

Example:

BTC Price

Updated 350ms ago

Order Book

Updated 120ms ago

Funding

Updated 15s ago

============================================================

SECTION 76 — STALE DATA UX

============================================================

If data becomes stale:

visually indicate:

STALE

Do not display stale information

as live information.

============================================================

SECTION 77 — ERROR HANDLING

============================================================

Never silently fail.

Display:

what failed

when it failed

impact

recommended action

Do not expose internal stack traces.

============================================================

SECTION 78 — LOADING STATES

============================================================

Use explicit states:

LOADING

UPDATING

STALE

FAILED

UNAVAILABLE

============================================================

SECTION 79 — NO-DATA STATES

============================================================

Distinguish:

NO DATA

from:

DATA FAILED

from:

DATA NOT AVAILABLE

============================================================

SECTION 80 — TRADE SAFETY UX

============================================================

Avoid:

one-click accidental execution.

Use deliberate approval flow.

============================================================

SECTION 81 — CONFIRMATION UX

============================================================

For high-risk trades require stronger confirmation.

Examples:

high leverage

large position

unusual asset

high concentration

abnormal market

============================================================

SECTION 82 — HUMAN OVERRIDE VISIBILITY

============================================================

When user changes AI recommendation:

clearly show:

AI VALUE

USER VALUE

DIFFERENCE

REVALIDATION STATUS

============================================================

SECTION 83 — TRADE REVIEW PAGE

============================================================

Before final approval provide one consolidated

review screen.

Sections:

Signal

Evidence

Validation

Risk

User Parameters

Portfolio Impact

Execution Conditions

Warnings

Approval

============================================================

SECTION 84 — TRADE REVIEW EXAMPLE

============================================================

BTCUSDT

Direction:

LONG

AI Entry:

100,000

User Entry:

99,800

AI Stop:

97,500

User Stop:

97,000

AI Leverage:

3x

User Leverage:

5x

Position:

\$1,000

Risk:

\$30

Risk/Reward:

2.8

Validation:

PASSED

User Modification:

YES

Revalidation:

PASSED

Approval:

PENDING

============================================================

SECTION 85 — TRADE REJECTION UX

============================================================

If backend rejects:

show:

REJECTED

Reason

Rule

Risk Impact

Recommended Correction

============================================================

SECTION 86 — BLOCKED TRADE UX

============================================================

If system blocks trading:

show:

TRADING BLOCKED

Reason

Blocking Component

Timestamp

Recovery Status

============================================================

SECTION 87 — NO TRADE UX

============================================================

"No Trade" is a valid and important outcome.

Display:

NO TRADE

Reason:

insufficient evidence

poor risk/reward

agent disagreement

stale data

invalid regime

risk violation

safety block

============================================================

SECTION 88 — PERFORMANCE DASHBOARD

============================================================

Display:

Total Trades

Win Rate

Loss Rate

Profit Factor

Expectancy

PnL

Sharpe

Sortino

Max Drawdown

Average Win

Average Loss

Fees

Slippage

============================================================

SECTION 89 — LIVE VS HISTORICAL

============================================================

Clearly distinguish:

BACKTEST

PAPER

LIVE

Never mix them into one performance metric.

============================================================

SECTION 90 — SIGNAL PERFORMANCE

============================================================

Show actual historical performance

of each signal/strategy.

Break down:

overall

regime

asset

timeframe

long

short

============================================================

SECTION 91 — MODEL PERFORMANCE

============================================================

Track AI model performance separately from

strategy performance.

Do not equate model accuracy with trading profitability.

============================================================

SECTION 92 — NOTIFICATION SYSTEM

============================================================

Support:

in-app

browser

mobile

WhatsApp

where supported by the platform's

notification architecture.

Critical alerts must follow Chat 10

safety and escalation rules.

============================================================

SECTION 93 — NOTIFICATION PREFERENCES

============================================================

Allow users to configure:

signal alerts

trade approval alerts

execution alerts

risk alerts

system alerts

security alerts

Critical safety/security notifications

cannot be disabled if policy requires them.

============================================================

SECTION 94 — ACCESS CONTROL

============================================================

Frontend must respect backend roles.

Example:

VIEWER

ANALYST

TRADER

ADMIN

SECURITY_ADMIN

SYSTEM_OPERATOR

============================================================

SECTION 95 — ROLE-BASED UI

============================================================

Do not merely hide buttons.

Backend authorization remains authoritative.

Frontend visibility is only UX.

============================================================

SECTION 96 — SESSION SECURITY

============================================================

Handle:

session expiry

reauthentication

logout

unauthorized access

approval timeout

============================================================

SECTION 97 — APPROVAL SESSION EXPIRATION

============================================================

If approval expires:

invalidate approval UI state.

Require fresh validation.

============================================================

SECTION 98 — CONCURRENT MODIFICATION

============================================================

If another process changes a trade candidate:

frontend must detect stale state.

Require refresh/revalidation.

============================================================

SECTION 99 — IDEMPOTENT UI ACTIONS

============================================================

Prevent duplicate:

approve

cancel

execute

modify

actions.

============================================================

SECTION 100 — ACCESSIBILITY

============================================================

Support:

keyboard navigation

clear labels

sufficient contrast

screen reader semantics

focus management

non-color-only status indicators

============================================================

SECTION 101 — INTERNATIONALIZATION

============================================================

Design the frontend so that localization

can be added later.

Avoid hard-coded UI strings throughout components.

============================================================

SECTION 102 — TIMEZONE

============================================================

Display timestamps consistently.

Allow user timezone preference.

Store backend timestamps in a

consistent canonical format.

============================================================

SECTION 103 — NUMBER FORMATTING

============================================================

Correctly display:

price

quantity

percentage

PnL

fees

leverage

funding

volume

market capitalization

Use asset-specific precision where required.

============================================================

SECTION 104 — FINANCIAL NUMBER SAFETY

============================================================

Never use unsafe floating-point assumptions

for critical monetary calculations.

Backend remains authoritative.

============================================================

SECTION 105 — CHARTING

============================================================

Professional charts should support:

candlesticks

volume

indicators

market structure

order blocks

FVG

support/resistance

entries

stop loss

take profit

liquidation

positions

============================================================

SECTION 106 — CHART ANNOTATIONS

============================================================

Allow backend-driven annotations:

BOS

CHoCH

OB

FVG

liquidity sweep

support

resistance

Fibonacci

entry

SL

TP

============================================================

SECTION 107 — CHART SOURCE

============================================================

Every displayed AI-derived annotation must

be traceable to backend analysis.

Do not fabricate chart intelligence

in frontend code.

============================================================

SECTION 108 — DATA SOURCE INDICATOR

============================================================

Show whether information originates from:

EXCHANGE

ON-CHAIN

NEWS

SOCIAL

AI

QUANT

USER

============================================================

SECTION 109 — TRUST INDICATORS

============================================================

Use clear visual indicators for:

VERIFIED

VALIDATED

ESTIMATED

AI-GENERATED

USER-DEFINED

STALE

UNKNOWN

============================================================

SECTION 110 — FRONTEND SECURITY

============================================================

Never store:

exchange secret keys

private keys

sensitive credentials

server-side secrets

in browser local storage.

============================================================

SECTION 111 — API SECURITY

============================================================

All backend requests must use authenticated

and authorized APIs.

Never rely on frontend authorization.

============================================================

SECTION 112 — WEBSOCKET SECURITY

============================================================

Authenticate protected real-time channels.

Validate server messages.

Do not allow client-controlled messages

to directly trigger execution.

============================================================

SECTION 113 — TRADE ACTION BOUNDARY

============================================================

The frontend must never directly call

an exchange API.

Architecture:

Frontend

↓

Backend API

↓

Authorization

↓

Safety Policy

↓

Risk

↓

Approval

↓

Execution

↓

Exchange

============================================================

SECTION 114 — FRONTEND STATE MANAGEMENT

============================================================

Separate:

SERVER STATE

UI STATE

FORM STATE

APPROVAL STATE

REAL-TIME STATE

Do not duplicate authoritative backend state

unnecessarily.

============================================================

SECTION 115 — CACHE POLICY

============================================================

Market data may use appropriate caching.

Critical trading state must use

fresh backend state.

============================================================

SECTION 116 — OFFLINE MODE

============================================================

If frontend loses connectivity:

clearly show:

OFFLINE

Do not imply that trading state is current.

============================================================

SECTION 117 — RECONNECT

============================================================

After reconnect:

refresh:

orders

positions

balances

risk

approval state

alerts

system state

============================================================

SECTION 118 — REAL-TIME CONFLICT

============================================================

If local UI state differs from server state:

SERVER STATE WINS.

============================================================

SECTION 119 — DASHBOARD CUSTOMIZATION

============================================================

Allow users to customize:

widgets

watchlists

charts

layout

timeframes

visible metrics

But do not allow customization

to bypass safety controls.

============================================================

SECTION 120 — USER EXPERIENCE PRIORITY

============================================================

Priority order:

1\. Safety

2\. Correctness

3\. Clarity

4\. Decision quality

5\. Speed

6\. Visual polish

============================================================

SECTION 121 — INFORMATION HIERARCHY

============================================================

The most important information should

always be immediately visible:

Trading State

Risk State

Active Alerts

Pending Approvals

Open Positions

Critical System Health

============================================================

SECTION 122 — COGNITIVE LOAD

============================================================

Do not overwhelm the user with every

AI output simultaneously.

Use progressive disclosure.

Summary first.

Evidence on demand.

Full technical detail available.

============================================================

SECTION 123 — EXECUTIVE SUMMARY

============================================================

Dashboard top section should answer:

What is happening?

What opportunities exist?

What risks exist?

What needs my approval?

Is the system safe?

Are there active positions?

============================================================

SECTION 124 — SIGNAL PRIORITY

============================================================

Rank signals by backend-provided priority.

Possible factors:

validation

evidence

risk/reward

market regime

freshness

strategy quality

Frontend must not invent the ranking formula.

============================================================

SECTION 125 — SIGNAL EXPIRATION

============================================================

Every signal should have:

created_at

expires_at

status

Expired signals cannot be approved.

============================================================

SECTION 126 — TRADE CANDIDATE LIFECYCLE

============================================================

Display:

GENERATED

ANALYZING

VALIDATING

VALIDATED

RISK_REVIEW

READY_FOR_APPROVAL

MODIFIED

REVALIDATION_REQUIRED

APPROVED

EXECUTING

EXECUTED

REJECTED

EXPIRED

CANCELLED

============================================================

SECTION 127 — POSITION LIFECYCLE

============================================================

Display:

PENDING

OPENING

OPEN

PARTIALLY_CLOSED

CLOSING

CLOSED

UNKNOWN

============================================================

SECTION 128 — SYSTEM LIFECYCLE

============================================================

Display:

STARTING

INITIALIZING

SYNCHRONIZING

READY

DEGRADED

BLOCKED

EMERGENCY

RECOVERING

============================================================

SECTION 129 — AUDIT UX

============================================================

Every major action should provide:

VIEW AUDIT EVENT

or:

VIEW DECISION TRACE

============================================================

SECTION 130 — TRADE EXPORT

============================================================

Authorized users may export:

trade history

signals

performance

audit records

risk records

Respect privacy and security policies.

============================================================

SECTION 131 — REPORTING

============================================================

Support reports for:

daily trading

weekly performance

strategy performance

risk

AI performance

execution quality

system health

============================================================

SECTION 132 — PERFORMANCE ATTRIBUTION

============================================================

Where possible attribute PnL to:

strategy

signal

asset

regime

agent recommendation

execution

Do not falsely attribute causality.

============================================================

SECTION 133 — USER MODIFICATION ATTRIBUTION

============================================================

If user changed:

entry

SL

TP

leverage

size

show the effect in trade history.

Example:

Original AI recommendation

↓

User modification

↓

Final approved configuration

↓

Execution outcome

============================================================

SECTION 134 — MOBILE APPROVAL

============================================================

If mobile approval is supported:

show only the essential information first:

asset

direction

entry

SL

TP

size

leverage

risk

R/R

validation

warnings

Full evidence remains available.

============================================================

SECTION 135 — APPROVAL FROM NOTIFICATION

============================================================

Notifications must NOT directly execute trades.

Notification:

"Trade approval required."

User opens secure approval screen.

Authenticated approval occurs through

the backend.

============================================================

SECTION 136 — WHATSAPP

============================================================

WhatsApp may be used for:

notifications

alerts

approval prompts

status updates

human communication

But:

WhatsApp messages must NEVER bypass

backend authentication, authorization,

risk validation, or safety controls.

============================================================

SECTION 137 — NO CHAT-TO-TRADE BYPASS

============================================================

A natural-language message such as:

"Buy BTC 10x now"

must NOT directly execute.

It must become:

REQUEST

↓

VALIDATION

↓

RISK

↓

APPROVAL

↓

EXECUTION

============================================================

SECTION 138 — UX SAFETY INVARIANTS

============================================================

The frontend must enforce these UX rules:

NO APPROVAL

=

NO EXECUTION

EXPIRED SIGNAL

=

NO APPROVAL

EXPIRED APPROVAL

=

NO EXECUTION

RISK FAILURE

=

NO EXECUTION

STALE CRITICAL DATA

=

NO EXECUTION

SAFETY BLOCK

=

NO EXECUTION

UNKNOWN STATE

=

NO EXECUTION

============================================================

SECTION 139 — FRONTEND TESTING

============================================================

Test:

signal display

evidence display

risk display

parameter modification

revalidation

approval

approval expiration

approval replay

duplicate clicks

execution status

position updates

real-time updates

stale data

offline mode

reconnection

role permissions

unauthorized actions

kill switch UI

emergency mode

audit display

============================================================

SECTION 140 — CRITICAL UX TEST

============================================================

Scenario:

AI recommends:

3x leverage

\$1,000 position

SL = X

TP = Y

User changes:

5x leverage

\$2,000 position

Expected:

UI marks parameters as modified.

Backend revalidates risk.

Old approval becomes invalid.

New approval is required.

============================================================

SECTION 141 — EMERGENCY TEST

============================================================

Scenario:

Global kill switch activated.

Expected frontend:

shows EMERGENCY STOP

disables new trade approval/execution

shows reason

shows timestamp

shows affected systems

continues safe monitoring

============================================================

SECTION 142 — EXCHANGE FAILURE TEST

============================================================

Scenario:

Exchange becomes unavailable.

Expected:

exchange status = UNHEALTHY

trading readiness = BLOCKED

new execution disabled

existing state clearly marked

reconciliation workflow visible

============================================================

SECTION 143 — POSITION MISMATCH TEST

============================================================

Scenario:

internal position differs from exchange.

Expected:

POSITION MISMATCH

new trading blocked

reconciliation required

critical alert shown

============================================================

SECTION 144 — SIGNAL EXPIRATION TEST

============================================================

Scenario:

signal expires while approval screen

is open.

Expected:

approval disabled

signal marked expired

fresh signal required

============================================================

SECTION 145 — SECURITY TEST

============================================================

Scenario:

unauthorized user attempts to access

approval or execution endpoint.

Expected:

backend denies request.

Frontend displays:

UNAUTHORIZED

============================================================

SECTION 146 — FRONTEND ARCHITECTURE

============================================================

Use a modular architecture.

Recommended conceptual modules:

/app

/dashboard

/markets

/analysis

/signals

/approvals

/trading

/positions

/portfolio

/strategies

/backtests

/risk

/agents

/alerts

/system

/audit

/settings

Do not tightly couple modules.

============================================================

SECTION 147 — DOMAIN COMPONENTS

============================================================

Create reusable domain components:

SignalCard

EvidencePanel

RiskSummary

TradeReview

ApprovalGate

PositionCard

OrderStatus

AgentStatus

SystemHealth

AlertPanel

AuditTimeline

DecisionTrace

MarketChart

============================================================

SECTION 148 — API CONTRACTS

============================================================

Frontend must consume versioned backend APIs.

Examples:

GET /api/v1/markets

GET /api/v1/signals

GET /api/v1/signals/{id}

GET /api/v1/risk

GET /api/v1/positions

GET /api/v1/orders

GET /api/v1/agents

GET /api/v1/system/health

GET /api/v1/audit

Approval:

POST /api/v1/trade-candidates/{id}/validate

POST /api/v1/trade-candidates/{id}/approve

POST /api/v1/trade-candidates/{id}/reject

Do not assume these exact endpoints

if Chat 12 defines different contracts.

Use the final backend API contract.

============================================================

SECTION 149 — FRONTEND/BACKEND CONTRACT

============================================================

Frontend DTOs must be separate from

internal backend domain models.

Use explicit API contracts.

============================================================

SECTION 150 — API VERSIONING

============================================================

Do not break existing frontend contracts

without versioning.

============================================================

SECTION 151 — FINAL UX ARCHITECTURE

============================================================

HUMAN

│

▼

TRADING DASHBOARD

│

┌───────────────────┼────────────────────┐

│ │ │

▼ ▼ ▼

ANALYSIS SIGNALS PORTFOLIO

│ │ │

▼ ▼ ▼

EVIDENCE VALIDATION RISK

│

▼

TRADE REVIEW

│

▼

HUMAN APPROVAL

│

▼

BACKEND SAFETY

│

▼

EXECUTION

============================================================

SECTION 152 — FINAL DESIGN PRINCIPLE

============================================================

The frontend should make the human:

INFORMED

NOTIFIED

AWARE OF RISK

ABLE TO VERIFY

ABLE TO APPROVE

ABLE TO REJECT

ABLE TO STOP

But never:

BYPASS SAFETY

============================================================

SECTION 153 — FINAL USER DECISION FLOW

============================================================

MARKET DETECTED

↓

AI ANALYSIS

↓

SIGNAL

↓

EVIDENCE REPORT

↓

VALIDATION

↓

RISK ASSESSMENT

↓

TRADE CANDIDATE

↓

USER REVIEWS

↓

USER MODIFIES PARAMETERS

OPTIONAL

↓

RISK REVALIDATION

↓

USER APPROVAL

↓

EXECUTION

↓

MONITORING

↓

POSITION MANAGEMENT

↓

CLOSURE

↓

PERFORMANCE ANALYSIS

↓

AUDIT

============================================================

SECTION 154 — CHAT 11 BOUNDARY

============================================================

Do NOT redesign:

AI analysis engines

market data architecture

strategy architecture

backtesting engine

risk engine

execution engine

safety architecture

security architecture

Chat 11 only defines how those systems

are presented and controlled by the user.

============================================================

SECTION 155 — CHAT 12 CONTRACT

============================================================

Chat 12 will define:

implementation roadmap

repository structure

technology choices

service boundaries

database structure

API implementation plan

frontend implementation plan

agent implementation plan

testing strategy

CI/CD

deployment

GitHub Copilot coding workflow

coding standards

development phases

milestones

acceptance criteria

Definition of Done

============================================================

END OF CHAT 11

============================================================
