# Chat 9 — Human Approval, Execution, CCXT & Exchange Integration

> Full source-derived Chat 9 content from the uploaded Master Playbook v2.2 DOCX. This is not a summary. Source Markdown lines 27276–30579 of the complete conversion.

---

Master Prompt — Chat 9

V2.1 INLINE UPGRADE - CHAT 9 HUMAN APPROVAL, EXECUTION, CCXT & EXCHANGE INTEGRATION

Purpose: implement a controlled human-in-the-loop execution path where only explicitly approved, validated, and risk-accepted configurations become executable intents.

Retained Scope

Preserve HumanApprovalGateway, approval, rejection, parameter modification, pre-execution validation, exchange abstraction, CCXT adapter, order creation, monitoring, lifecycle management, reconciliation, idempotency, errors, partial fills, retries, and duplicate-order prevention.

v2.1 Corrections and Enhancements

Add ApprovalBindingHash over signal version, evidence version, strategy version, validation version, risk version, account snapshot, portfolio snapshot, and exact approved parameters.

Separate ApprovalRequest, ApprovalDecision, ExecutionIntent, OrderRequest, ExchangeOrder, Fill, Position, and TradeOutcome.

Approval changed, expired, stale, or mismatched means no execution.

Uncertain exchange state means reconciliation, not blind retry.

No execution without final pre-execution validation and idempotency key.

Chat 9 Required Contracts

ApprovalRequest, ApprovalDecision, ApprovalBindingHash, ExecutionIntent, OrderRequest, Order, ExchangeOrder, Fill, Position, Trade, ExecutionReport, ReconciliationReport, IdempotencyKey, ExecutionState.

Acceptance Criteria

No approval equals no live execution.

Approval is tied to the exact configuration and cannot be reused after material change.

AI agents cannot directly access unrestricted exchange credentials or trading endpoints.

\# ENTERPRISE-GRADE SUPERVISED AUTONOMOUS CRYPTO TRADING PLATFORM

\# GITHUB COPILOT IMPLEMENTATION PROMPT - 9

\# CHAT 9 — HUMAN APPROVAL, EXECUTION, CCXT

\# & EXCHANGE INTEGRATION

============================================================

PROJECT CONTINUITY

============================================================

You are continuing the implementation of the enterprise-grade,

supervised autonomous AI crypto analysis and trading platform.

The project follows the ORIGINAL 12-CHAT IMPLEMENTATION

PLAYBOOK.

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

CURRENT:

CHAT 9

Human Approval, Execution, CCXT &

Exchange Integration

FUTURE:

CHAT 10

AI Safety, Security, Audit, Observability &

Failure Recovery

CHAT 11

Frontend, Dashboard & Trader UX

CHAT 12

Implementation Roadmap, Repository Structure,

Testing & Copilot Coding Protocol

============================================================

NON-NEGOTIABLE ARCHITECTURAL RULE

============================================================

DO NOT DEVIATE FROM THE ORIGINAL 12-CHAT PLAYBOOK.

Do not redesign previous phases.

Do not duplicate CHAT 5.

Do not duplicate CHAT 6.

Do not duplicate CHAT 7.

Do not duplicate CHAT 8.

CHAT 9 is specifically responsible for:

HUMAN APPROVAL

TRADE AUTHORIZATION

ORDER VALIDATION

ORDER CONSTRUCTION

EXCHANGE CONNECTIVITY

ORDER SUBMISSION

ORDER MONITORING

ORDER LIFECYCLE MANAGEMENT

POSITION STATE SYNCHRONIZATION

EXECUTION RECONCILIATION

CCXT INTEGRATION

EXCHANGE-SPECIFIC ADAPTERS

EXECUTION SAFETY CONTROLS

============================================================

PRIMARY OBJECTIVE

============================================================

Build a highly controlled human-in-the-loop execution

system.

The system must allow the AI trading platform to:

1\. Generate an analysis.

2\. Generate a validated signal.

3\. Generate a risk proposal.

4\. Present the proposed trade to the human.

5\. Allow the human to modify permitted parameters.

6\. Recalculate risk after modifications.

7\. Require explicit human approval.

8\. Validate the approved configuration again.

9\. Submit the order to the selected exchange.

10\. Monitor execution.

11\. Reconcile actual exchange state.

12\. Report execution results.

============================================================

CORE PRINCIPLE

============================================================

ANALYSIS

↓

VALIDATION

↓

RISK

↓

HUMAN REVIEW

↓

HUMAN APPROVAL

↓

FINAL PRE-EXECUTION VALIDATION

↓

ORDER CREATION

↓

EXCHANGE

↓

ORDER MONITORING

↓

POSITION RECONCILIATION

No step may silently bypass the previous step.

============================================================

SECTION 1 — HUMAN-IN-THE-LOOP GATE

============================================================

Create:

HumanApprovalGateway

The gateway must require explicit approval.

Valid states:

PENDING_APPROVAL

APPROVED

REJECTED

EXPIRED

CANCELLED

SUPERSEDED

EXECUTING

EXECUTED

FAILED

============================================================

SECTION 2 — NO IMPLICIT APPROVAL

============================================================

The following must NEVER count as approval:

\- viewing a signal

\- opening a dashboard

\- changing a field

\- generating a report

\- receiving a notification

\- replying ambiguously

\- AI recommendation

\- risk engine PASS

\- strategy validation PASS

Only an explicit approval action counts.

============================================================

SECTION 3 — APPROVAL OBJECT

============================================================

Create:

TradeApproval

containing:

\- approval_id

\- risk_proposal_id

\- signal_id

\- user_id

\- approved_parameters

\- approval_timestamp

\- approval_method

\- approval_status

\- approval_expiry

\- confirmation_hash

\- client_context

\- approval_version

============================================================

SECTION 4 — APPROVAL MUST REFER TO EXACT PARAMETERS

============================================================

The human must approve a specific configuration.

Example:

BTCUSDT

LONG

Entry:

100,000

Stop:

97,500

Take Profit:

105,000

Amount:

\$500

Leverage:

5x

Margin Mode:

ISOLATED

The approval applies ONLY to this exact configuration.

If any parameter changes afterward:

the previous approval becomes invalid.

============================================================

SECTION 5 — APPROVAL HASH

============================================================

Generate a deterministic hash from:

\- signal

\- strategy version

\- asset

\- direction

\- entry

\- SL

\- TP

\- amount

\- position size

\- leverage

\- margin mode

\- exchange

\- order type

Store:

approval_hash

Before execution:

recalculate hash.

If hashes differ:

STOP EXECUTION.

============================================================

SECTION 6 — HUMAN EDITABLE PARAMETERS

============================================================

Allow human modification of approved trade

parameters before final approval:

\- amount

\- position size

\- leverage

\- stop loss

\- take profit

\- entry price

\- order type

\- margin mode

\- maximum slippage

However:

EVERY CHANGE MUST RETURN TO CHAT 8 RISK VALIDATION.

============================================================

SECTION 7 — PARAMETER CHANGE FLOW

============================================================

Example:

AI proposal:

Amount:

\$500

Leverage:

5x

SL:

\$95,000

Human changes:

Leverage:

10x

DO NOT execute.

Instead:

Human change

↓

Risk Engine

↓

Recalculate

↓

Validate

↓

Generate new RiskProposal

↓

Human approval

↓

Execution

============================================================

SECTION 8 — APPROVAL EXPIRATION

============================================================

Trade approvals must expire.

Reasons:

\- market price changed

\- signal became stale

\- risk state changed

\- account state changed

\- portfolio changed

\- liquidity changed

\- order book changed

\- funding changed

\- strategy invalidated

Configurable expiration:

approval_ttl

============================================================

SECTION 9 — MARKET CHANGE REVALIDATION

============================================================

Before execution compare:

approved entry

against:

current market price.

If deviation exceeds:

maximum_entry_deviation

require:

REVALIDATION.

Do not execute stale approvals.

============================================================

SECTION 10 — RISK REVALIDATION

============================================================

Immediately before execution:

recalculate:

\- account equity

\- available balance

\- current positions

\- portfolio exposure

\- leverage

\- margin

\- liquidation

\- maximum loss

\- risk limits

\- liquidity

\- price deviation

The final execution check must consume

fresh state.

============================================================

SECTION 11 — DOUBLE-SUBMISSION PREVENTION

============================================================

Prevent duplicate orders.

Every execution request must have:

idempotency_key

If the same request arrives again:

return the existing execution result.

Do not submit another order.

============================================================

SECTION 12 — EXECUTION STATE MACHINE

============================================================

Implement:

DRAFT

PENDING_APPROVAL

APPROVED

PRE_EXECUTION_VALIDATION

READY_TO_EXECUTE

SUBMITTING

SUBMITTED

PARTIALLY_FILLED

FILLED

CANCEL_PENDING

CANCELLED

REJECTED

FAILED

EXPIRED

RECONCILING

RECONCILED

UNKNOWN

============================================================

SECTION 13 — ORDER LIFECYCLE

============================================================

Order lifecycle:

TradeProposal

↓

HumanApproval

↓

PreExecutionValidation

↓

OrderRequest

↓

ExchangeSubmission

↓

ExchangeOrder

↓

Monitoring

↓

Fill Events

↓

Position Update

↓

Reconciliation

============================================================

SECTION 14 — ORDER REQUEST

============================================================

Create:

OrderRequest

containing:

\- execution_id

\- approval_id

\- exchange

\- account

\- symbol

\- side

\- order_type

\- quantity

\- price

\- stop_loss

\- take_profit

\- leverage

\- margin_mode

\- reduce_only

\- post_only

\- time_in_force

\- client_order_id

\- idempotency_key

\- max_slippage

============================================================

SECTION 15 — ORDER TYPES

============================================================

Support where exchange capability exists:

MARKET

LIMIT

STOP

STOP_LIMIT

TAKE_PROFIT

TAKE_PROFIT_LIMIT

TRAILING_STOP

REDUCE_ONLY

Do not assume every exchange supports every order type.

============================================================

SECTION 16 — EXCHANGE CAPABILITY MODEL

============================================================

Create:

ExchangeCapabilities

including:

\- supported markets

\- supported order types

\- supported margin modes

\- supported leverage

\- supported stop orders

\- supported take profit

\- supported reduce-only

\- supported post-only

\- precision

\- minimum order size

\- maximum order size

\- price limits

The execution engine must validate capabilities

before submission.

============================================================

SECTION 17 — CCXT ABSTRACTION

============================================================

Use CCXT as the primary exchange integration

abstraction.

Do NOT spread raw CCXT calls throughout the

application.

Create:

ExchangeGateway

and:

CCXTExchangeAdapter

The domain layer must depend on the application's

exchange abstraction rather than CCXT directly.

============================================================

SECTION 18 — EXCHANGE ADAPTER

============================================================

Create an adapter architecture:

ExchangeGateway

↓

CCXTExchangeAdapter

↓

Exchange-specific implementation

Support future exchanges without changing

core trading logic.

============================================================

SECTION 19 — EXCHANGE REGISTRY

============================================================

Create:

ExchangeRegistry

Responsibilities:

\- register exchanges

\- load exchange configuration

\- resolve adapter

\- expose capabilities

\- manage health status

============================================================

SECTION 20 — EXCHANGE ACCOUNT

============================================================

Represent:

ExchangeAccount

containing:

\- exchange

\- account_id

\- environment

\- market_type

\- currency

\- permissions

\- status

Never store raw API credentials in domain objects.

============================================================

SECTION 21 — API CREDENTIAL SECURITY

============================================================

Exchange API credentials must:

\- never be stored in source code

\- never be committed to Git

\- never be logged

\- never appear in AI prompts

\- never appear in error messages

\- never appear in UI

\- never be stored as plain text

Use:

secret management

environment-specific secure configuration

============================================================

SECTION 22 — MINIMUM EXCHANGE PERMISSIONS

============================================================

Use least privilege.

Where possible:

READ

TRADE

Do NOT require:

WITHDRAW

unless absolutely necessary.

This platform must not require withdrawal

permissions for trading.

============================================================

SECTION 23 — API KEY ENVIRONMENT

============================================================

Clearly distinguish:

SANDBOX

TESTNET

PAPER

LIVE

The system must prevent accidental live execution

when configured for testing.

============================================================

SECTION 24 — LIVE TRADING SAFETY

============================================================

Live trading must require explicit configuration.

Example:

execution_environment = LIVE

Do not default to LIVE.

============================================================

SECTION 25 — PAPER TRADING

============================================================

Support:

PAPER

where exchange orders are simulated.

Paper execution must use the same:

OrderRequest

validation

execution state machine

and reconciliation concepts

where practical.

============================================================

SECTION 26 — TESTNET

============================================================

Support exchange testnet/sandbox environments

where available.

Never assume testnet behavior exactly matches live.

============================================================

SECTION 27 — SYMBOL NORMALIZATION

============================================================

Create canonical:

Instrument

representation.

Normalize differences such as:

BTC/USDT

BTCUSDT

BTC-USDT

etc.

Do not let exchange-specific symbol formats

leak throughout the domain.

============================================================

SECTION 28 — MARKET TYPES

============================================================

Explicitly distinguish:

SPOT

MARGIN

PERPETUAL

FUTURES

OPTIONS

if supported.

Do not mix instrument semantics.

============================================================

SECTION 29 — LEVERAGE SETTING

============================================================

If leverage must be configured on the exchange:

perform it only after:

human approval

and:

pre-execution validation.

Verify exchange accepted the requested leverage.

If actual leverage differs:

STOP.

============================================================

SECTION 30 — MARGIN MODE

============================================================

Support where available:

ISOLATED

CROSS

Verify actual exchange state before submitting

the order.

============================================================

SECTION 31 — ORDER PRECISION

============================================================

Before submission normalize:

\- quantity precision

\- price precision

\- contract size

\- minimum quantity

\- minimum notional

Do not silently round in a way that materially

changes risk.

============================================================

SECTION 32 — PRECISION REVALIDATION

============================================================

After exchange precision normalization:

recalculate:

\- quantity

\- notional

\- risk

\- leverage

\- maximum loss

If the normalized order violates risk limits:

REJECT.

============================================================

SECTION 33 — MARKET ORDER SAFETY

============================================================

Market orders must include:

maximum slippage protection

where exchange capabilities permit.

Do not assume a market order will execute

at the displayed price.

============================================================

SECTION 34 — LIMIT ORDER SAFETY

============================================================

Validate:

price

quantity

tick size

minimum notional

time-in-force

post-only

before submission.

============================================================

SECTION 35 — STOP LOSS PROTECTION

============================================================

Where supported, create exchange-native

protective orders.

If exchange-native protection is unavailable:

the system must explicitly identify the limitation.

Do not claim guaranteed protection.

============================================================

SECTION 36 — TAKE PROFIT

============================================================

Support exchange-native TP where available.

Otherwise:

represent TP as a managed execution instruction.

Do not assume every exchange supports identical

TP behavior.

============================================================

SECTION 37 — REDUCE ONLY

============================================================

For closing/reducing positions:

use reduce-only where supported and appropriate.

Never unintentionally turn a closing order

into an opposite position.

============================================================

SECTION 38 — POSITION MODE

============================================================

Where supported, account for:

ONE-WAY

HEDGE

position modes.

Never assume the exchange is in the expected mode.

Verify actual state.

============================================================

SECTION 39 — PRE-EXECUTION CHECKLIST

============================================================

Before submission verify:

\[ \] Human approval valid

\[ \] Approval not expired

\[ \] Approval hash matches

\[ \] Signal still valid

\[ \] Strategy still valid

\[ \] Risk proposal still valid

\[ \] Account state fresh

\[ \] Portfolio state fresh

\[ \] Balance sufficient

\[ \] Margin sufficient

\[ \] Leverage valid

\[ \] Margin mode valid

\[ \] Position limits valid

\[ \] Portfolio limits valid

\[ \] Price deviation acceptable

\[ \] Liquidity acceptable

\[ \] Slippage acceptable

\[ \] Exchange healthy

\[ \] API credentials valid

\[ \] Exchange capabilities valid

\[ \] Quantity valid

\[ \] Price valid

\[ \] Order type valid

\[ \] Stop-loss valid

\[ \] Take-profit valid

\[ \] Idempotency key valid

ALL REQUIRED CHECKS MUST PASS.

============================================================

SECTION 40 — FAIL CLOSED

============================================================

If a required execution condition is unknown:

DO NOT EXECUTE.

Examples:

unknown balance

unknown position

unknown leverage

unknown margin mode

unknown exchange status

unknown order status

unknown approval state

unknown risk state

============================================================

SECTION 41 — ORDER SUBMISSION

============================================================

Create:

ExecutionService

Responsibilities:

\- validate final order

\- construct exchange order

\- submit order

\- record exchange response

\- transition execution state

Do not allow direct UI-to-exchange calls.

============================================================

SECTION 42 — EXCHANGE RESPONSE

============================================================

Normalize exchange responses into:

OrderResult

containing:

\- internal_order_id

\- exchange_order_id

\- status

\- symbol

\- side

\- order_type

\- requested_quantity

\- executed_quantity

\- average_price

\- remaining_quantity

\- fee

\- timestamp

\- raw_reference

Do not expose raw exchange responses

through the domain API unless explicitly required.

============================================================

SECTION 43 — ORDER STATUS NORMALIZATION

============================================================

Normalize exchange statuses into:

OPEN

PARTIALLY_FILLED

FILLED

CANCELLED

REJECTED

EXPIRED

UNKNOWN

============================================================

SECTION 44 — PARTIAL FILLS

============================================================

Support partial execution.

Track:

requested quantity

filled quantity

remaining quantity

average fill price

fees

realized/unrealized effects

Risk state must reflect actual fill.

============================================================

SECTION 45 — PARTIAL FILL RISK

============================================================

If a partial fill occurs:

recalculate:

\- actual position size

\- actual risk

\- remaining order risk

\- SL/TP requirements

\- portfolio exposure

Do not assume full fill.

============================================================

SECTION 46 — ORDER MONITOR

============================================================

Create:

OrderMonitor

Monitor:

\- open orders

\- fills

\- cancellations

\- rejections

\- exchange disconnects

\- unexpected state changes

Use event-driven updates where supported.

============================================================

SECTION 47 — POLLING FALLBACK

============================================================

If websocket/event updates are unavailable:

support controlled polling.

Polling must:

\- use configurable intervals

\- handle rate limits

\- stop when order is terminal

\- reconcile after completion

============================================================

SECTION 48 — WEBSOCKET SUPPORT

============================================================

Where supported:

consume exchange websocket events.

Handle:

\- order updates

\- fills

\- position updates

\- balance updates

Never assume websocket messages are perfectly ordered.

============================================================

SECTION 49 — EVENT DEDUPLICATION

============================================================

Exchange events may be duplicated.

Implement idempotent event processing.

Each event should have:

event_id

or deterministic deduplication logic.

============================================================

SECTION 50 — EVENT ORDERING

============================================================

Do not assume:

event arrival order = event occurrence order.

Use:

exchange timestamp

sequence numbers

or reconciliation

where available.

============================================================

SECTION 51 — RECONCILIATION

============================================================

Create:

ExecutionReconciliationService

Compare:

INTERNAL STATE

vs

EXCHANGE STATE

Reconcile:

\- orders

\- fills

\- positions

\- balances

\- leverage

\- margin

============================================================

SECTION 52 — RECONCILIATION STATES

============================================================

Create:

IN_SYNC

DRIFT_DETECTED

RECONCILIATION_REQUIRED

RECONCILIATION_FAILED

UNKNOWN

============================================================

SECTION 53 — POSITION RECONCILIATION

============================================================

The exchange is the authoritative source

for actual live position state.

If:

internal position ≠ exchange position

flag:

POSITION_STATE_DRIFT

Do not silently overwrite audit history.

============================================================

SECTION 54 — ORDER RECONCILIATION

============================================================

If internal state says:

ORDER_FILLED

but exchange says:

OPEN

do not assume internal state is correct.

Trigger reconciliation.

============================================================

SECTION 55 — UNKNOWN EXECUTION STATE

============================================================

If order submission returns a timeout:

DO NOT automatically retry.

The request may have reached the exchange.

First:

query exchange using:

client_order_id

or:

exchange_order_id

or:

reconciliation process.

This prevents duplicate orders.

============================================================

SECTION 56 — NETWORK FAILURE

============================================================

Handle:

\- timeout

\- DNS failure

\- connection reset

\- exchange unavailable

\- rate limit

\- authentication failure

Never blindly retry an order submission.

============================================================

SECTION 57 — RETRY POLICY

============================================================

Distinguish:

SAFE_TO_RETRY

from:

MUST_RECONCILE_FIRST

Example:

GET balance:

SAFE_TO_RETRY

POST order:

MUST_RECONCILE_FIRST after uncertain response.

============================================================

SECTION 58 — RATE LIMITING

============================================================

Respect CCXT/exchange rate limits.

Implement:

\- request throttling

\- exponential backoff where appropriate

\- endpoint prioritization

\- rate-limit monitoring

Never bypass exchange rate limits.

============================================================

SECTION 59 — EXCHANGE HEALTH

============================================================

Create:

ExchangeHealthMonitor

Track:

\- API availability

\- latency

\- websocket status

\- error rate

\- rate-limit status

\- market data freshness

If exchange health is unacceptable:

block new execution.

============================================================

SECTION 60 — MARKET DATA FRESHNESS

============================================================

Before market execution:

verify market data timestamp.

If data is stale:

REJECT or REVALIDATE.

Never execute based on stale critical data.

============================================================

SECTION 61 — PRICE PROTECTION

============================================================

Before execution:

compare:

approved price

current market price

order book

spread

slippage estimate

If deviation exceeds configured limits:

BLOCK EXECUTION.

============================================================

SECTION 62 — LIQUIDITY PROTECTION

============================================================

Before execution verify:

\- volume

\- spread

\- order book depth

\- expected market impact

If conditions changed materially since approval:

require revalidation.

============================================================

SECTION 63 — FUNDING REVALIDATION

============================================================

For perpetuals:

check current funding conditions.

If funding changes materially:

recalculate risk where configured.

============================================================

SECTION 64 — BALANCE REVALIDATION

============================================================

Immediately before execution:

retrieve fresh available balance.

Do not rely solely on the earlier snapshot.

============================================================

SECTION 65 — POSITION REVALIDATION

============================================================

Immediately before execution:

retrieve current positions.

Ensure the approved trade does not conflict

with a newly opened or closed position.

============================================================

SECTION 66 — CONCURRENT EXECUTION CONTROL

============================================================

Prevent multiple executions from modifying

the same account state simultaneously.

Use:

distributed lock

or:

transactional concurrency control.

============================================================

SECTION 67 — CLIENT ORDER ID

============================================================

Generate deterministic or unique:

client_order_id

It must allow mapping:

Internal Execution

↕

Exchange Order

============================================================

SECTION 68 — EXECUTION RECORD

============================================================

Create:

ExecutionRecord

containing:

\- execution_id

\- approval_id

\- risk_proposal_id

\- exchange

\- account

\- symbol

\- side

\- order_type

\- requested_quantity

\- submitted_price

\- leverage

\- margin_mode

\- client_order_id

\- exchange_order_id

\- submission_time

\- execution_status

\- fill_status

\- final_average_price

\- final_quantity

\- fees

\- slippage

\- execution_latency

\- error_code

\- error_message

\- created_at

\- updated_at

============================================================

SECTION 69 — EXECUTION REPORT

============================================================

Create:

ExecutionReport

containing:

========================================

EXECUTION REPORT

========================================

Execution ID:

Approval ID:

Signal ID:

Strategy:

Exchange:

Symbol:

Direction:

----------------------------------------

APPROVED

----------------------------------------

Entry:

Stop Loss:

Take Profit:

Amount:

Leverage:

Margin Mode:

----------------------------------------

ACTUAL EXECUTION

----------------------------------------

Requested Quantity:

Executed Quantity:

Average Entry:

Actual Slippage:

Fees:

Funding:

Execution Latency:

----------------------------------------

STATUS

----------------------------------------

Order Status:

Position Status:

Reconciliation Status:

----------------------------------------

RISK

----------------------------------------

Approved Risk:

Actual Risk:

Portfolio Impact:

----------------------------------------

RESULT

----------------------------------------

SUCCESS

PARTIAL

FAILED

UNKNOWN

========================================

============================================================

SECTION 70 — EXECUTION AUDIT TRAIL

============================================================

Record:

\- original signal

\- strategy version

\- validation version

\- risk proposal

\- user modifications

\- approval

\- approval hash

\- final order

\- exchange response

\- fills

\- cancellations

\- reconciliation

\- final position state

Everything must be reconstructable.

============================================================

SECTION 71 — USER MODIFICATION HISTORY

============================================================

Example:

Version 1

Amount:

\$500

Leverage:

5x

SL:

95,000

↓

User changed leverage.

Version 2

Amount:

\$500

Leverage:

10x

SL:

95,000

↓

Risk recalculated.

↓

Human approved Version 2.

Only Version 2 can execute.

============================================================

SECTION 72 — APPROVAL REVOCATION

============================================================

Support:

revoke approval

cancel pending execution

expire approval

supersede approval

If execution has not started:

prevent submission.

If execution has started:

do not pretend revocation can undo an exchange

operation.

Represent actual state honestly.

============================================================

SECTION 73 — MANUAL EMERGENCY CONTROL

============================================================

The architecture must support a future emergency:

GLOBAL_EXECUTION_PAUSE

When active:

no new orders may be submitted.

Existing positions remain subject to their

actual exchange state.

Do not automatically close positions unless

explicitly configured elsewhere.

============================================================

SECTION 74 — EXECUTION CIRCUIT BREAKER

============================================================

Automatically prevent new execution when:

\- exchange unavailable

\- repeated order failures

\- reconciliation drift

\- abnormal slippage

\- abnormal latency

\- stale market data

\- account state unknown

\- risk state unknown

\- excessive execution errors

============================================================

SECTION 75 — NO AUTOMATIC RECOVERY THAT CREATES RISK

============================================================

Never automatically:

\- double an order

\- increase leverage

\- widen stop loss

\- remove stop loss

\- increase position size

\- reverse position

during recovery.

============================================================

SECTION 76 — EXECUTION AGENT

============================================================

The Execution Agent may:

\- prepare orders

\- validate orders

\- submit approved orders

\- monitor execution

\- report state

The Execution Agent must NOT:

\- create an unapproved trade

\- change approved risk parameters

\- override risk limits

\- bypass human approval

\- withdraw funds

\- transfer funds

============================================================

SECTION 77 — AI EXECUTION BOUNDARY

============================================================

AI agents must never directly possess unrestricted

exchange credentials.

Use:

ExecutionService

as the controlled execution boundary.

AI requests:

"Execute approved order X."

ExecutionService verifies:

approval

risk

authorization

state

then executes.

============================================================

SECTION 78 — TOOL PERMISSION MODEL

============================================================

Separate permissions:

ANALYSIS_AGENT

READ_MARKET_DATA

RISK_AGENT

READ_ACCOUNT_STATE

APPROVAL_GATEWAY

AUTHORIZE_EXECUTION

EXECUTION_SERVICE

TRADE

No agent receives unnecessary permissions.

============================================================

SECTION 79 — WITHDRAWAL PROHIBITION

============================================================

The trading system must NOT support:

\- withdrawals

\- fund transfers

\- address management

These are outside the scope of the trading

execution engine.

============================================================

SECTION 80 — EXCHANGE FAILURE MODES

============================================================

Handle:

API unavailable

websocket unavailable

rate limit

invalid credentials

insufficient balance

invalid quantity

invalid price

invalid leverage

invalid margin mode

market closed

symbol unavailable

order rejected

partial fill

order timeout

unknown order status

position mismatch

balance mismatch

exchange maintenance

============================================================

SECTION 81 — ERROR TAXONOMY

============================================================

Create structured errors:

APPROVAL_INVALID

APPROVAL_EXPIRED

APPROVAL_MISMATCH

RISK_REVALIDATION_FAILED

ACCOUNT_STATE_STALE

PORTFOLIO_STATE_STALE

PRICE_DEVIATION

LIQUIDITY_FAILURE

EXCHANGE_UNAVAILABLE

AUTHENTICATION_FAILURE

RATE_LIMIT

INVALID_ORDER

INSUFFICIENT_BALANCE

INSUFFICIENT_MARGIN

INVALID_LEVERAGE

INVALID_SYMBOL

ORDER_REJECTED

ORDER_TIMEOUT

UNKNOWN_ORDER_STATE

POSITION_DRIFT

RECONCILIATION_FAILURE

EXECUTION_PAUSED

============================================================

SECTION 82 — TESTNET-FIRST DEVELOPMENT

============================================================

Development must default to:

PAPER

or:

TESTNET

Never LIVE.

Live execution must require explicit deployment

configuration.

============================================================

SECTION 83 — EXECUTION TESTING

============================================================

Create tests for:

Human approval

Approval expiration

Approval hash

Parameter modification

Risk revalidation

Price deviation

Balance revalidation

Position revalidation

Idempotency

Duplicate submission

Partial fills

Full fills

Order cancellation

Order rejection

Timeout

Network failure

Exchange failure

Rate limits

Precision

Minimum order size

Maximum order size

Leverage

Margin mode

Reduce-only

Position mode

Reconciliation

State drift

Unknown order state

Circuit breaker

Execution pause

============================================================

SECTION 84 — CRITICAL EXECUTION TESTS

============================================================

Test this exact scenario:

AI proposes:

BTC LONG

Amount:

\$500

Leverage:

5x

SL:

95,000

TP:

105,000

Human changes:

Leverage:

10x

Expected:

old approval invalid

risk recalculation

new RiskProposal

new approval required

new approval hash

no execution until approved

============================================================

Test:

Human approves.

Market moves significantly.

Expected:

pre-execution validation detects price deviation.

Execution:

BLOCKED.

============================================================

Test:

Order submission times out.

Expected:

NO BLIND RETRY.

System:

RECONCILES EXCHANGE STATE.

============================================================

Test:

Exchange reports partial fill.

Expected:

actual position state reflects partial quantity.

============================================================

Test:

Internal state says FILLED.

Exchange says OPEN.

Expected:

RECONCILIATION_REQUIRED.

============================================================

SECTION 85 — SECURITY TESTING

============================================================

Verify:

API keys never appear in logs.

API keys never enter AI prompts.

API keys never enter error responses.

API keys never appear in database records

unless securely managed by a dedicated secret

management mechanism.

Unauthorized execution requests fail.

Unapproved orders fail.

Expired approvals fail.

Modified approved parameters fail until

reapproved.

============================================================

SECTION 86 — OBSERVABILITY

============================================================

Track:

\- approval requests

\- approvals

\- rejections

\- expirations

\- parameter modifications

\- risk revalidations

\- execution requests

\- exchange requests

\- exchange latency

\- order results

\- fills

\- failures

\- reconciliation

\- state drift

\- circuit breaker events

============================================================

SECTION 87 — EXECUTION METRICS

============================================================

Calculate:

\- order success rate

\- rejection rate

\- partial fill rate

\- average execution latency

\- average slippage

\- maximum slippage

\- exchange error rate

\- reconciliation failures

\- duplicate prevention events

\- stale-order prevention

\- approval-to-execution latency

============================================================

SECTION 88 — EXECUTION QUALITY

============================================================

Compare:

approved entry

vs:

actual average execution.

Calculate:

slippage

execution latency

fill ratio

market impact

Do not claim strategy performance using

theoretical prices after live execution begins.

Actual execution results must be recorded.

============================================================

SECTION 89 — DATABASE / PERSISTENCE

============================================================

Persist:

TradeApproval

RiskProposalReference

OrderRequest

ExecutionRecord

OrderEvent

FillEvent

ReconciliationRecord

ExchangeAccountReference

ExecutionError

ExecutionStateTransition

============================================================

SECTION 90 — STATE MACHINE INTEGRITY

============================================================

Do not permit illegal transitions.

Example:

PENDING_APPROVAL

↓

APPROVED

valid.

But:

PENDING_APPROVAL

↓

FILLED

invalid.

All state transitions must be validated.

============================================================

SECTION 91 — EVENT SOURCING / AUDIT

============================================================

Where practical, maintain execution events:

ApprovalCreated

ApprovalModified

ApprovalApproved

ApprovalExpired

PreExecutionValidationStarted

PreExecutionValidationPassed

PreExecutionValidationFailed

OrderSubmissionStarted

OrderSubmitted

OrderPartiallyFilled

OrderFilled

OrderCancelled

OrderRejected

ReconciliationStarted

ReconciliationCompleted

ReconciliationFailed

============================================================

SECTION 92 — CHAT 8 → CHAT 9 CONTRACT

============================================================

CHAT 8 provides:

RiskProposal

containing:

\- signal

\- strategy

\- entry

\- stop loss

\- take profit

\- amount

\- position size

\- leverage

\- margin mode

\- maximum loss

\- risk percentage

\- liquidation analysis

\- portfolio impact

\- stress analysis

\- risk decision

\- warnings

\- constraints

CHAT 9 consumes this proposal.

============================================================

SECTION 93 — CHAT 9 → CHAT 10 CONTRACT

============================================================

CHAT 9 provides:

\- execution events

\- approval events

\- order events

\- exchange events

\- reconciliation events

\- execution errors

\- authentication events

\- state transitions

\- security-relevant events

\- circuit-breaker events

CHAT 10 will provide the broader:

SAFETY

SECURITY

AUDIT

OBSERVABILITY

FAILURE RECOVERY

framework.

============================================================

SECTION 94 — CHAT 9 DOES NOT OWN

============================================================

CHAT 9 does NOT own:

market analysis

technical analysis

fundamental analysis

SMC

Wyckoff

meta-analysis

strategy research

backtesting

statistical validation

position-sizing methodology

portfolio optimization

AI model selection

frontend design

system-wide observability architecture

These belong to previous or future chats.

============================================================

SECTION 95 — FINAL EXECUTION FLOW

============================================================

MARKET DATA

↓

CHAT 5

MARKET ANALYSIS

↓

CHAT 6

TRADING STRATEGY / SIGNAL

↓

CHAT 7

QUANT VALIDATION

↓

CHAT 8

RISK / POSITION SIZE

↓

CHAT 9

HUMAN APPROVAL

↓

FINAL RISK REVALIDATION

↓

ORDER VALIDATION

↓

CCXT

↓

EXCHANGE

↓

ORDER MONITORING

↓

FILL

↓

POSITION RECONCILIATION

↓

EXECUTION REPORT

↓

CHAT 10

SAFETY / AUDIT / OBSERVABILITY

============================================================

SECTION 96 — FINAL HUMAN-IN-THE-LOOP PRINCIPLE

============================================================

The system is SUPERVISED AUTONOMOUS.

It is NOT FULLY AUTONOMOUS.

The AI may:

ANALYZE

RESEARCH

GENERATE SIGNALS

VALIDATE

PROPOSE

CALCULATE RISK

PREPARE ORDERS

MONITOR EXECUTION

REPORT RESULTS

But the system must NOT independently create

and execute a new live trade without explicit

human approval.

============================================================

SECTION 97 — FINAL EXECUTION PRINCIPLE

============================================================

NO APPROVAL

=

NO EXECUTION

APPROVAL CHANGED

=

REVALIDATION REQUIRED

APPROVAL EXPIRED

=

NO EXECUTION

MARKET CHANGED MATERIALly

=

REVALIDATION REQUIRED

RISK LIMIT FAILED

=

NO EXECUTION

ACCOUNT STATE UNKNOWN

=

NO EXECUTION

EXCHANGE STATE UNKNOWN

=

NO BLIND RETRY

POSITION STATE MISMATCH

=

RECONCILIATION REQUIRED

============================================================

SECTION 98 — FINAL ARCHITECTURAL PRINCIPLE

============================================================

CHAT 5

WHAT IS THE MARKET DOING?

↓

CHAT 6

IS THERE A VALID TRADING SETUP?

↓

CHAT 7

DOES THE STRATEGY HAVE ROBUST

HISTORICAL EVIDENCE?

↓

CHAT 8

WHAT IS THE APPROPRIATE RISK,

POSITION SIZE AND PORTFOLIO IMPACT?

↓

CHAT 9

DOES THE HUMAN APPROVE THIS

EXACT TRADE CONFIGURATION?

↓

FINAL VALIDATION

↓

EXECUTION

↓

RECONCILIATION

↓

CHAT 10

IS THE COMPLETE SYSTEM SAFE,

AUDITABLE AND RESILIENT?

============================================================

END OF CHAT 9

============================================================
