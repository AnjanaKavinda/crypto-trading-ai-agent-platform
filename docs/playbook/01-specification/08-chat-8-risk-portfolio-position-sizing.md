# Chat 8 — Risk Management, Portfolio Management & Position Sizing

> Full source-derived Chat 8 content from the uploaded Master Playbook v2.2 DOCX. This is not a summary. Source Markdown lines 24458–27275 of the complete conversion.

---

Master Prompt — Chat 8

V2.1 INLINE UPGRADE - CHAT 8 RISK MANAGEMENT, PORTFOLIO & POSITION SIZING

Purpose: deterministically assess account risk, portfolio impact, position size, leverage, liquidation, and constraints for a validated candidate trade.

Retained Scope

Preserve deterministic risk engine, account risk, position size, leverage, margin, stop distance, liquidation risk, maximum loss, portfolio exposure, correlated exposure, daily/weekly loss, drawdown, and volatility-adjusted sizing.

Preserve Chat 8 boundary: it does not decide whether the strategy is profitable and does not execute.

v2.1 Corrections and Enhancements

Make RiskProposal immutable and versioned with AccountRiskSnapshot, PortfolioRiskSnapshot, TradeRiskSnapshot, RiskModelVersion, and PolicyVersion.

Add event-risk adjustment, liquidity adjustment, concentration analysis, correlation shock, slippage stress, funding stress, and liquidation distance checks.

Require full recalculation after human changes to amount, size, leverage, entry, stop loss, take profit, trailing stop, risk percentage, or margin mode.

Add stale-risk invalidation when market, account, portfolio, evidence, strategy, risk model, or policy materially changes.

Chat 8 Required Contracts

AccountSnapshot, PortfolioSnapshot, PositionSnapshot, RiskProposal, RiskAssessment, PositionSizingResult, LeverageAssessment, LiquidationAssessment, StopLossAssessment, TakeProfitAssessment, PortfolioImpact, StressTestResult, RiskDecision, RiskRevalidationResult.

Acceptance Criteria

All critical risk numbers come from deterministic code, not LLM reasoning.

Hard risk constraints veto unsafe configurations even after human modification.

RiskProposal passed to Chat 9 includes warnings, constraints, assumptions, and exact parameter snapshot.

\# ENTERPRISE-GRADE SUPERVISED AUTONOMOUS CRYPTO TRADING PLATFORM

\# GITHUB COPILOT IMPLEMENTATION PROMPT - 8

\# CHAT 8 — RISK MANAGEMENT, PORTFOLIO MANAGEMENT

\# & POSITION SIZING

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

CURRENT:

CHAT 8

Risk Management, Portfolio Management &

Position Sizing

FUTURE:

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

============================================================

NON-NEGOTIABLE ARCHITECTURAL RULE

============================================================

DO NOT DEVIATE FROM THE ORIGINAL 12-CHAT PLAYBOOK.

Do not redesign previous phases.

Do not duplicate CHAT 7.

Do not implement exchange execution.

Do not implement order placement.

Do not implement the final human approval workflow.

Do not implement the frontend.

Do not implement withdrawal functionality.

Do not allow AI agents to independently determine

or execute final capital allocation.

This phase is responsible for:

RISK ANALYSIS

POSITION SIZING

PORTFOLIO RISK

LEVERAGE ANALYSIS

STOP-LOSS RISK

TAKE-PROFIT RISK/REWARD

CORRELATION

EXPOSURE

DRAWDOWN CONTROL

LIQUIDATION RISK

RISK-OF-RUIN

CAPITAL PRESERVATION

TRADE RISK PROPOSAL

============================================================

PRIMARY OBJECTIVE

============================================================

Build an enterprise-grade risk management and portfolio

management engine that receives validated strategy

signals from CHAT 7 and produces a transparent,

configurable risk proposal.

The system must answer:

1\. How much capital could be allocated?

2\. How much capital is actually at risk?

3\. Where is the analytical invalidation level?

4\. What position size corresponds to the chosen risk?

5\. What leverage is being considered?

6\. What is the liquidation risk?

7\. How does this trade affect the portfolio?

8\. Are there correlated existing positions?

9\. Does the trade violate portfolio limits?

10\. What happens under adverse price movement?

11\. What is the estimated risk of ruin?

12\. Is the proposed trade within configured risk limits?

============================================================

CRITICAL PRINCIPLE

============================================================

RISK MANAGEMENT MUST BE SEPARATE FROM SIGNAL QUALITY.

A strategy can have:

HIGH VALIDATION QUALITY

but still be:

TOO RISKY TO TRADE.

Example:

Strategy validation:

ROBUST_75_PLUS

But:

\- excessive leverage

\- insufficient liquidity

\- high portfolio correlation

\- unacceptable liquidation distance

\- excessive account exposure

Therefore:

VALIDATED STRATEGY

does NOT mean:

AUTOMATICALLY ACCEPTABLE RISK.

============================================================

SECTION 1 — RISK MANAGEMENT PIPELINE

============================================================

Implement:

Validated Signal

↓

Trade Risk Analysis

↓

Account State

↓

Portfolio State

↓

Position Sizing

↓

Leverage Analysis

↓

SL/TP Risk Analysis

↓

Correlation Analysis

↓

Stress Testing

↓

Risk-of-Ruin Analysis

↓

Risk Limits

↓

Risk Proposal

↓

Human Approval

↓

CHAT 9

============================================================

SECTION 2 — RISK ENGINE

============================================================

Create:

RiskManagementEngine

Responsibilities:

\- calculate trade risk

\- calculate position size

\- evaluate leverage

\- evaluate stop-loss distance

\- evaluate portfolio exposure

\- evaluate correlation

\- evaluate liquidation risk

\- enforce configured risk limits

\- generate risk warnings

\- generate risk proposal

The engine must be deterministic for quantitative

calculations.

============================================================

SECTION 3 — RISK CONFIGURATION

============================================================

All important risk inputs must be configurable.

Examples:

maximum_account_risk_per_trade

maximum_portfolio_risk

maximum_position_size

maximum_leverage

maximum_asset_exposure

maximum_sector/theme exposure

maximum_correlated_exposure

maximum_drawdown_limit

maximum_daily_loss

maximum_weekly_loss

maximum_open_positions

minimum_liquidation_distance

minimum_liquidity

maximum_slippage_assumption

minimum_risk_reward

maximum_concurrent_risk

The system must not hard-code these values.

============================================================

SECTION 4 — USER-CONTROLLABLE PARAMETERS

============================================================

The human must eventually be able to modify:

\- trade amount

\- risk percentage

\- position size

\- leverage

\- stop loss

\- take profit

\- entry price

\- order type

\- maximum acceptable slippage

However:

USER INPUT

must be validated by the Risk Engine.

Example:

Human selects:

Leverage = 50x

The system must NOT simply accept it.

It must calculate:

\- liquidation risk

\- margin requirement

\- price distance to liquidation

\- portfolio impact

\- maximum loss under SL

\- exchange constraints

Then return:

APPROVED_BY_RISK_RULES

or:

REQUIRES_REVIEW

or:

REJECTED_BY_RISK_RULES

============================================================

SECTION 5 — RISK PROPOSAL

============================================================

Create:

RiskProposal

containing:

\- proposal_id

\- signal_id

\- account_snapshot_id

\- portfolio_snapshot_id

\- entry_price

\- stop_loss

\- take_profit

\- position_size

\- notional_value

\- margin_required

\- leverage

\- maximum_loss

\- expected_profit

\- risk_reward_ratio

\- account_risk_percentage

\- portfolio_risk_percentage

\- liquidation_price

\- liquidation_distance

\- exposure

\- correlation_exposure

\- risk_status

\- warnings

\- constraints

\- created_at

\- expires_at

This is NOT an executable order.

============================================================

SECTION 6 — ACCOUNT MODEL

============================================================

Create an account risk abstraction.

Support:

\- account equity

\- available balance

\- used margin

\- free margin

\- unrealized P&L

\- realized P&L

\- current drawdown

\- daily P&L

\- weekly P&L

Do not implement exchange account mutation.

CHAT 9 will handle live exchange integration.

============================================================

SECTION 7 — PORTFOLIO MODEL

============================================================

Create:

PortfolioSnapshot

containing:

\- equity

\- cash

\- margin

\- open positions

\- pending risk

\- total exposure

\- directional exposure

\- asset exposure

\- correlated exposure

\- portfolio drawdown

\- portfolio volatility

============================================================

SECTION 8 — POSITION RISK

============================================================

For a long position:

risk_to_stop =

position_size ×

(entry_price - stop_loss)

For a short position:

risk_to_stop =

position_size ×

(stop_loss - entry_price)

Then incorporate:

fees

slippage

funding

other configured costs

The exact implementation must use the selected

instrument model.

============================================================

SECTION 9 — RISK PERCENTAGE

============================================================

Calculate:

account_risk_percentage =

maximum_loss / account_equity

Example:

Account equity:

\$10,000

Maximum loss:

\$100

Risk:

1%

Do not confuse:

position notional

with:

capital at risk.

============================================================

SECTION 10 — POSITION SIZING

============================================================

Support risk-based position sizing.

Conceptually:

position_size =

acceptable_risk /

stop_distance

Adjust for:

\- contract specification

\- fees

\- slippage

\- leverage

\- minimum order size

\- maximum order size

\- exchange precision

Do not allow leverage to artificially reduce

the actual price risk.

============================================================

SECTION 11 — FIXED-CAPITAL SIZING

============================================================

Also support:

FIXED_NOTIONAL

Example:

\$500 position

The engine must calculate:

\- percentage of account

\- stop-loss risk

\- leverage

\- margin

\- portfolio exposure

============================================================

SECTION 12 — PERCENTAGE-EQUITY SIZING

============================================================

Support:

PERCENTAGE_OF_EQUITY

Example:

2% of account equity

Calculate:

notional

margin

stop risk

portfolio impact

============================================================

SECTION 13 — VOLATILITY-ADJUSTED SIZING

============================================================

Support optional:

VOLATILITY_ADJUSTED

Position size may account for:

\- ATR

\- realized volatility

\- implied volatility where available

Higher volatility should generally result in

smaller exposure for a fixed risk budget.

============================================================

SECTION 14 — KELLY CRITERION

============================================================

Support Kelly-based research calculations.

But DO NOT automatically use full Kelly for live trading.

Support:

\- full Kelly

\- fractional Kelly

\- capped Kelly

Example:

0.25 Kelly

must remain subject to:

maximum risk per trade

maximum portfolio risk

maximum leverage

human approval

============================================================

SECTION 15 — RISK BUDGET

============================================================

Create:

RiskBudget

Support:

\- per-trade risk

\- daily risk

\- weekly risk

\- portfolio risk

\- strategy risk

\- asset risk

\- directional risk

Example:

Daily risk budget = 3%

Open positions consume part of this budget.

============================================================

SECTION 16 — CONCURRENT RISK

============================================================

Calculate:

total_open_risk

\+

new_trade_risk

\+

contingent_risk

The system must prevent hidden aggregation

of risk.

============================================================

SECTION 17 — CORRELATED POSITIONS

============================================================

Calculate exposure to correlated assets.

Examples:

BTC

ETH

SOL

may share significant market exposure.

Do not treat:

BTC LONG

and:

ETH LONG

as completely independent.

Support:

\- return correlation

\- volatility correlation

\- beta

\- rolling correlation

============================================================

SECTION 18 — CORRELATION WINDOWS

============================================================

Support:

7D

30D

90D

180D

custom windows

Use rolling measurements where appropriate.

============================================================

SECTION 19 — BETA EXPOSURE

============================================================

Where appropriate calculate:

asset beta to BTC

or another configured benchmark.

This helps identify hidden portfolio concentration.

============================================================

SECTION 20 — DIRECTIONAL EXPOSURE

============================================================

Calculate:

gross long exposure

gross short exposure

net exposure

Example:

\$20k long

\$5k short

Net:

\$15k long

Do not consider the portfolio neutral merely because

both long and short positions exist.

============================================================

SECTION 21 — ASSET CONCENTRATION

============================================================

Calculate:

asset exposure / total portfolio equity

Flag excessive concentration.

============================================================

SECTION 22 — STRATEGY CONCENTRATION

============================================================

Track risk by:

strategy

strategy family

market thesis

asset

direction

timeframe

This prevents multiple signals from creating

hidden concentration.

============================================================

SECTION 23 — MARKET-THESIS CONCENTRATION

============================================================

Example:

BTC LONG

ETH LONG

SOL LONG

may all depend on:

"Crypto market enters broad bullish expansion."

The system should identify shared thesis risk.

============================================================

SECTION 24 — LEVERAGE ENGINE

============================================================

Create:

LeverageRiskEngine

Evaluate:

\- requested leverage

\- maximum permitted leverage

\- margin requirement

\- liquidation distance

\- effective exposure

\- portfolio leverage

\- maintenance margin

\- initial margin

\- liquidation risk

============================================================

SECTION 25 — LEVERAGE PRINCIPLE

============================================================

Leverage increases exposure.

Leverage does NOT reduce underlying price risk.

Example:

\$1,000 capital

10x leverage

\$10,000 notional

A 5% adverse price movement approximately creates

\$500 gross price loss before costs.

The system must clearly display this relationship.

============================================================

SECTION 26 — CROSS MARGIN / ISOLATED MARGIN

============================================================

Support distinction between:

ISOLATED

CROSS

Do not assume identical liquidation behavior.

Record margin mode in the risk proposal.

============================================================

SECTION 27 — LIQUIDATION ANALYSIS

============================================================

Where exchange-specific formulas/data are available,

calculate estimated liquidation price.

Otherwise:

return:

LIQUIDATION_ESTIMATE_UNAVAILABLE

Do not invent liquidation prices.

============================================================

SECTION 28 — LIQUIDATION DISTANCE

============================================================

Calculate:

distance from entry to estimated liquidation.

Compare against:

stop loss

normal volatility

stress volatility

If liquidation is closer than the intended

risk boundary:

REJECT or WARN according to configuration.

============================================================

SECTION 29 — STOP LOSS ENGINE

============================================================

Support analytical stop-loss concepts from CHAT 6.

Allow human override.

Validate:

\- stop relative to entry

\- stop distance

\- minimum distance

\- maximum risk

\- volatility

\- structure

\- liquidation distance

============================================================

SECTION 30 — STOP LOSS OVERRIDE

============================================================

If the AI proposes:

SL = \$95,000

Human changes:

SL = \$96,000

the Risk Engine must recalculate:

\- risk

\- position size

\- R:R

\- liquidation relationship

\- portfolio impact

Do not retain stale calculations.

============================================================

SECTION 31 — TAKE PROFIT ENGINE

============================================================

Support:

\- single target

\- multiple targets

\- partial exits

\- trailing concepts

Calculate:

risk/reward

expected R

expected P&L

Do not execute these orders.

============================================================

SECTION 32 — RISK/REWARD

============================================================

Calculate:

R:R =

potential_reward / potential_risk

Do not use R:R as a standalone predictor of profitability.

It must be interpreted together with:

historical strategy performance

win rate

expectancy

drawdown

execution assumptions

============================================================

SECTION 33 — EXPECTED VALUE

============================================================

Consume CHAT 7 validated expectancy where available.

Calculate estimated trade expected value:

EV =

probability-weighted outcome

or strategy expectancy where appropriate.

Do not fabricate probabilities.

If no calibrated probability exists,

use historical expectancy rather than pretending

to know future probability.

============================================================

SECTION 34 — STOP/TP CONSISTENCY

============================================================

Check whether:

entry

stop

target

are consistent with:

strategy

market structure

historical strategy behavior

volatility

risk limits

============================================================

SECTION 35 — MAXIMUM LOSS

============================================================

Calculate conservative maximum loss including:

\- stop loss

\- estimated slippage

\- fees

\- funding where relevant

\- adverse execution

Do not only calculate:

entry → stop

============================================================

SECTION 36 — GAP / SLIPPAGE RISK

============================================================

Crypto markets can move rapidly.

The system must model:

normal slippage

stress slippage

extreme slippage

Where stop execution is not guaranteed,

show:

EXPECTED LOSS

and:

STRESS LOSS

============================================================

SECTION 37 — LIQUIDITY RISK

============================================================

Evaluate:

\- volume

\- order book depth

\- spread

\- expected market impact

\- position size relative to liquidity

Flag:

LOW_LIQUIDITY

HIGH_MARKET_IMPACT

or:

LIQUIDITY_UNAVAILABLE

============================================================

SECTION 38 — MARKET IMPACT

============================================================

Estimate:

position size / available liquidity

Where order-book data is available,

use it.

Do not assume unlimited liquidity.

============================================================

SECTION 39 — VOLATILITY STRESS

============================================================

Stress the proposed trade under:

1x volatility

1.5x volatility

2x volatility

3x volatility

where appropriate.

Calculate:

\- adverse price movement

\- expected loss

\- liquidation proximity

\- portfolio drawdown

============================================================

SECTION 40 — GAP STRESS

============================================================

Simulate sudden price movement.

Examples:

\- 2%

\- 5%

\- 10%

\- configurable shock

Calculate portfolio impact.

============================================================

SECTION 41 — CORRELATION BREAKDOWN

============================================================

Do not assume historical correlations remain stable.

Stress:

correlation → 1

for correlated long positions where appropriate.

Identify:

hidden concentration risk.

============================================================

SECTION 42 — PORTFOLIO STRESS TESTING

============================================================

Support scenarios such as:

BTC -5%

BTC -10%

BTC -20%

Broad crypto market -10%

Broad crypto market -20%

Volatility spike

Liquidity collapse

Funding spike

Correlation increase

Calculate:

portfolio P&L

portfolio drawdown

margin impact

liquidation proximity

============================================================

SECTION 43 — RISK-OF-RUIN

============================================================

Implement a research-grade risk-of-ruin analysis.

Use validated strategy characteristics from CHAT 7.

Consider:

\- win rate

\- loss rate

\- payoff distribution

\- risk per trade

\- losing streaks

\- trade frequency

Do not treat risk-of-ruin as exact prediction.

Clearly label it as a model estimate.

============================================================

SECTION 44 — LOSING STREAK ANALYSIS

============================================================

Consume CHAT 7's historical and Monte Carlo

losing-streak distributions.

Calculate:

expected losing streak

95th percentile

99th percentile

stress losing streak

Evaluate whether account risk remains acceptable.

============================================================

SECTION 45 — DRAWDOWN BUDGET

============================================================

Support:

maximum allowed portfolio drawdown.

Example:

MAX_DRAWDOWN = 20%

If projected or actual drawdown exceeds

configured thresholds:

risk state changes.

============================================================

SECTION 46 — DAILY LOSS LIMIT

============================================================

Support:

maximum daily loss.

If reached:

NO_NEW_RISK

or:

TRADING_PAUSE

according to configuration.

This is a risk-control state,

not an exchange execution action.

============================================================

SECTION 47 — WEEKLY LOSS LIMIT

============================================================

Support:

maximum weekly loss.

Same principle as daily limits.

============================================================

SECTION 48 — CONSECUTIVE LOSS CONTROL

============================================================

Support configurable controls after:

3 losses

5 losses

10 losses

etc.

Possible states:

NORMAL

CAUTION

REDUCED_RISK

PAUSED

These are configurable risk policies.

============================================================

SECTION 49 — STRATEGY DRAWDOWN CONTROL

============================================================

If a validated strategy experiences

live/recent drawdown beyond configured limits,

flag:

STRATEGY_DEGRADED

and reduce or suspend new risk according

to configuration.

Do not modify CHAT 7's validation methodology.

============================================================

SECTION 50 — PORTFOLIO VOLATILITY

============================================================

Estimate portfolio volatility.

Where sufficient data exists,

support covariance-based calculations.

Do not assume zero correlation.

============================================================

SECTION 51 — MARGIN UTILIZATION

============================================================

Calculate:

used margin

available margin

proposed margin

post-trade margin

margin utilization %

Flag excessive utilization.

============================================================

SECTION 52 — FREE MARGIN BUFFER

============================================================

Maintain configurable minimum free-margin buffer.

Example:

minimum_free_margin_percentage

The system must prevent risk proposals that

violate this threshold.

============================================================

SECTION 53 — PORTFOLIO LEVERAGE

============================================================

Calculate:

gross notional / equity

and:

net notional / equity

Display both.

============================================================

SECTION 54 — EFFECTIVE LEVERAGE

============================================================

Differentiate:

account leverage

position leverage

portfolio leverage

effective exposure

These must not be conflated.

============================================================

SECTION 55 — RISK LIMIT HIERARCHY

============================================================

Implement:

SYSTEM LIMITS

↓

ACCOUNT LIMITS

↓

PORTFOLIO LIMITS

↓

STRATEGY LIMITS

↓

TRADE LIMITS

↓

USER REQUEST

↓

FINAL RISK PROPOSAL

A lower-level request cannot override

a higher-level hard limit.

============================================================

SECTION 56 — HARD VS SOFT LIMITS

============================================================

Support:

HARD_LIMIT

SOFT_LIMIT

Hard limit:

must reject.

Soft limit:

requires human review/acknowledgment.

============================================================

SECTION 57 — USER OVERRIDE POLICY

============================================================

The user may modify:

amount

leverage

SL

TP

entry

risk percentage

But:

HARD risk limits cannot be overridden through

normal trade input.

If an override capability is later introduced,

it must require explicit elevated authorization.

Do not implement privileged override mechanisms here.

============================================================

SECTION 58 — RISK STATES

============================================================

Create:

SAFE

LOW_RISK

MODERATE_RISK

HIGH_RISK

EXTREME_RISK

REJECTED

PAUSED

INSUFFICIENT_DATA

============================================================

SECTION 59 — RISK DECISION

============================================================

Create:

RiskDecision

Possible:

PASS

PASS_WITH_WARNING

REQUIRES_HUMAN_REVIEW

REJECT

INSUFFICIENT_DATA

The Risk Engine must explain every decision.

============================================================

SECTION 60 — RISK EXPLANATION

============================================================

Every proposal must answer:

Why is this position size recommended?

How much can be lost?

What percentage of equity is at risk?

What leverage is used?

What happens if SL is hit?

What happens under stress?

What is liquidation distance?

What portfolio exposure does it create?

What correlated positions exist?

Which limits are close to being violated?

============================================================

SECTION 61 — RISK REPORT

============================================================

Create:

RiskAssessmentReport

Structure:

========================================

RISK ASSESSMENT REPORT

========================================

Signal:

Strategy:

Asset:

Direction:

----------------------------------------

ACCOUNT

----------------------------------------

Equity:

Available Balance:

Current Drawdown:

Daily P&L:

Weekly P&L:

----------------------------------------

PROPOSED TRADE

----------------------------------------

Entry:

Stop Loss:

Take Profit:

Position Size:

Notional:

Leverage:

Margin:

----------------------------------------

TRADE RISK

----------------------------------------

Maximum Loss:

Risk %:

Risk in R:

Reward:

R:R:

----------------------------------------

LIQUIDATION

----------------------------------------

Margin Mode:

Liquidation Estimate:

Liquidation Distance:

----------------------------------------

PORTFOLIO IMPACT

----------------------------------------

Current Exposure:

New Exposure:

Gross Exposure:

Net Exposure:

Correlated Exposure:

Post-Trade Risk:

----------------------------------------

STRESS

----------------------------------------

Normal:

High Volatility:

Extreme Volatility:

Market Shock:

----------------------------------------

RISK LIMITS

----------------------------------------

Per Trade:

Daily:

Weekly:

Portfolio:

Leverage:

Margin:

----------------------------------------

RISK DECISION

----------------------------------------

PASS

PASS_WITH_WARNING

REQUIRES_HUMAN_REVIEW

REJECT

----------------------------------------

WARNINGS

----------------------------------------

----------------------------------------

RECOMMENDATION

----------------------------------------

========================================

============================================================

SECTION 62 — RISK PROPOSAL VERSIONING

============================================================

Every risk proposal must be versioned.

Example:

RiskProposal v1

Human changes leverage.

Create:

RiskProposal v2

Human changes stop loss.

Create:

RiskProposal v3

Never silently mutate historical risk calculations.

============================================================

SECTION 63 — PARAMETER PROVENANCE

============================================================

Record:

\- source signal

\- strategy version

\- validation version

\- risk model version

\- account snapshot

\- portfolio snapshot

\- user inputs

\- default parameters

\- overridden parameters

\- calculation timestamp

============================================================

SECTION 64 — IMMUTABLE SNAPSHOTS

============================================================

Create:

AccountRiskSnapshot

PortfolioRiskSnapshot

TradeRiskSnapshot

These ensure that the risk proposal can be reconstructed.

============================================================

SECTION 65 — RISK MODEL VERSIONING

============================================================

Version:

\- position sizing model

\- leverage model

\- liquidation model

\- cost model

\- stress model

\- risk limits

\- risk-of-ruin model

Changing a risk model must create a new version.

============================================================

SECTION 66 — MULTI-AI RISK REVIEW

============================================================

AI agents may assist with:

Risk Analyst

Portfolio Analyst

Stress-Test Analyst

Contrarian Risk Analyst

But deterministic code controls:

\- numerical calculations

\- limits

\- position sizing

\- risk thresholds

\- hard rejection rules

============================================================

SECTION 67 — AI RISK ROLE

============================================================

AI must NEVER:

\- invent account equity

\- invent positions

\- invent liquidation prices

\- invent fees

\- invent leverage constraints

\- override hard risk limits

\- approve an otherwise rejected trade

AI explains quantitative outputs.

It does not replace the risk engine.

============================================================

SECTION 68 — RISK DISAGREEMENT

============================================================

If AI risk analysts disagree:

record:

\- analyst

\- conclusion

\- evidence

\- disagreement

\- resolution

Do not average textual outputs.

============================================================

SECTION 69 — MISSING DATA

============================================================

If required data is unavailable:

return:

INSUFFICIENT_DATA

Examples:

\- account equity unavailable

\- position state unavailable

\- liquidation model unavailable

\- liquidity unavailable

\- funding unavailable

Do not invent values.

============================================================

SECTION 70 — NO EXECUTION

============================================================

STRICTLY PROHIBITED IN CHAT 8:

\- exchange order placement

\- order cancellation

\- order modification

\- position modification

\- withdrawals

\- fund transfers

\- live trading

CHAT 9 owns execution.

============================================================

SECTION 71 — HUMAN APPROVAL BOUNDARY

============================================================

CHAT 8 produces:

Risk Proposal

CHAT 9 consumes:

Risk Proposal

and manages:

Human Approval

Execution

The architecture must therefore support:

RiskProposal

↓

Await Human Approval

↓

Approved Configuration

↓

CHAT 9

Do not implement the actual approval UI/workflow here.

============================================================

SECTION 72 — USER PARAMETER HANDOFF

============================================================

The future approval workflow must support

human modification of:

Amount

Leverage

Stop Loss

Take Profit

Entry

Risk Percentage

Before execution.

When any value changes:

Risk Engine must recalculate the entire proposal.

Example:

User changes:

\$500 → \$1,000

System recalculates:

\- position size

\- risk

\- margin

\- liquidation

\- portfolio exposure

\- stress loss

\- risk status

============================================================

SECTION 73 — RISK PROPOSAL API

============================================================

Design APIs such as:

POST /risk/assess

GET /risk/proposals

GET /risk/proposals/{proposal_id}

POST /risk/proposals/{proposal_id}/recalculate

GET /risk/proposals/{proposal_id}/stress

GET /risk/portfolio

GET /risk/account

GET /risk/limits

GET /risk/exposure

Do not create:

POST /orders

POST /positions

POST /withdrawals

Those belong to CHAT 9 or later.

============================================================

SECTION 74 — DOMAIN OBJECTS

============================================================

Create or define:

RiskConfiguration

RiskLimit

RiskBudget

AccountSnapshot

PortfolioSnapshot

PositionSnapshot

TradeRiskInput

PositionSizeResult

LeverageAssessment

LiquidationAssessment

StopLossAssessment

TakeProfitAssessment

RiskRewardAssessment

CorrelationAssessment

ExposureAssessment

StressTestResult

RiskOfRuinResult

RiskProposal

RiskDecision

RiskAssessmentReport

RiskModelVersion

============================================================

SECTION 75 — TESTING

============================================================

Create comprehensive tests for:

Position sizing

Fixed notional sizing

Percentage-equity sizing

Risk-based sizing

Volatility sizing

Kelly calculations

Fractional Kelly

Stop-loss calculations

Take-profit calculations

R:R

Fees

Slippage

Funding

Leverage

Margin

Liquidation

Isolated margin

Cross margin

Portfolio exposure

Correlation

Beta

Gross exposure

Net exposure

Risk budget

Daily loss limit

Weekly loss limit

Drawdown limits

Free margin

Stress testing

Risk-of-ruin

Losing streaks

Hard limits

Soft limits

User parameter changes

Risk proposal recalculation

Risk proposal versioning

Missing data

Invalid input

============================================================

SECTION 76 — CRITICAL EDGE CASES

============================================================

Test:

Zero account equity

Negative account equity

Zero stop distance

Stop above entry for LONG

Stop below entry for SHORT

Take profit on wrong side

Extreme leverage

Leverage above configured limit

Liquidation before stop

Stop extremely close to liquidation

Insufficient margin

Insufficient liquidity

Huge position relative to order book

Correlated portfolio

Maximum daily loss reached

Maximum weekly loss reached

Maximum drawdown reached

Multiple simultaneous signals

Conflicting long/short positions

User doubles position size

User increases leverage

User moves SL closer

User moves SL farther away

User removes SL

User changes entry price

Missing funding

Missing liquidation model

Missing account state

Stale portfolio state

============================================================

SECTION 77 — OBSERVABILITY

============================================================

Track:

\- risk assessments

\- risk rejections

\- risk warnings

\- hard-limit violations

\- soft-limit warnings

\- position sizing calculations

\- leverage assessments

\- stress tests

\- risk-of-ruin calculations

\- portfolio exposure changes

\- parameter overrides

============================================================

SECTION 78 — SECURITY

============================================================

The risk engine must NOT possess permissions for:

\- exchange trading

\- withdrawals

\- fund transfers

Use least privilege.

Risk calculation is not execution permission.

============================================================

SECTION 79 — CHAT 7 → CHAT 8 CONTRACT

============================================================

CHAT 7 provides:

\- validated strategy

\- strategy version

\- historical performance

\- expectancy

\- win rate

\- drawdown

\- losing streak distribution

\- volatility

\- regime performance

\- robustness

\- validation status

CHAT 8 consumes these inputs.

============================================================

SECTION 80 — CHAT 8 → CHAT 9 CONTRACT

============================================================

CHAT 8 provides:

RiskProposal

containing:

\- signal

\- entry

\- SL

\- TP

\- amount

\- position size

\- leverage

\- margin

\- maximum loss

\- risk percentage

\- liquidation analysis

\- portfolio impact

\- stress analysis

\- risk decision

\- warnings

\- constraints

CHAT 9 will consume this proposal.

CHAT 9 must NOT blindly execute it.

The human approval layer must occur first.

============================================================

SECTION 81 — FINAL ARCHITECTURAL FLOW

============================================================

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

WHAT IS THE APPROPRIATE RISK,

POSITION SIZE AND PORTFOLIO IMPACT?

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

HOW DO WE IMPLEMENT, TEST AND DEPLOY

THE COMPLETE SYSTEM?

============================================================

SECTION 82 — FINAL PRINCIPLE

============================================================

CHAT 8 DOES NOT DECIDE WHETHER THE STRATEGY

IS PROFITABLE.

CHAT 7 determines historical/statistical evidence.

CHAT 8 determines:

"WHAT WOULD THIS TRADE DO TO THE ACCOUNT

AND PORTFOLIO UNDER THE SELECTED RISK PARAMETERS?"

CHAT 8 does NOT execute.

CHAT 9 owns:

HUMAN APPROVAL

ORDER CREATION

EXCHANGE EXECUTION

POSITION MANAGEMENT

============================================================

END OF CHAT 8

============================================================
