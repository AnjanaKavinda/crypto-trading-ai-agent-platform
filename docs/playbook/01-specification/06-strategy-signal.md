# Strategy, Signal Generation and Evidence Qualification

## Objective
Convert MarketContext into strategy eligibility, candidate signals, signal evidence, qualification decisions, and NO_TRADE outcomes.

## Strategy families
Trend following, momentum, breakout, pullback, mean reversion, swing trading, market structure, SMC, Wyckoff, volume-based, statistical, event-driven, volatility-based, correlation-based.

## Signal states
CANDIDATE, QUALIFIED, REJECTED, EXPIRED, SUPERSEDED, NO_TRADE.

## 75% qualification rule
The default configurable rule is historical conditional win rate >= 75%, but only with minimum sample size, positive expectancy, acceptable drawdown, OOS/walk-forward validation, regime compatibility, liquidity, data quality, transaction costs, slippage, and risk constraints.

## Evidence package
Each signal must include technical, fundamental, SMC, Wyckoff, derivatives, on-chain, sentiment, macro, regime, historical, risk, conflict, and limitation evidence.

## No-trade engine
NO_TRADE reasons include insufficient evidence, low sample size, failed validation, regime mismatch, conflicting evidence, stale data, degraded data, high event risk, low liquidity, excessive risk, strategy decay, model drift, execution unsafe, portfolio limit, and system not ready.
