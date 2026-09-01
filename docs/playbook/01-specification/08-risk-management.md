# Risk Management, Portfolio and Position Sizing

## Objective
Evaluate what a candidate trade would do to the account and portfolio under selected risk parameters.

## Deterministic risk calculations
Account risk, position size, leverage, margin, stop distance, liquidation risk, maximum loss, portfolio exposure, correlated exposure, simultaneous position limit, daily/weekly loss, drawdown, volatility-adjusted size, concentration, stress testing.

## Human modification behavior
If the user changes amount, entry, stop loss, take profit, leverage, risk percentage, margin mode, or trailing stop, recalculate risk, liquidation, exposure, portfolio risk, and hard constraints before approval.

## Output
RiskProposal with signal, entry, SL, TP, amount, position size, leverage, margin, max loss, risk percentage, liquidation analysis, portfolio impact, stress analysis, warnings, constraints, risk model version, and risk decision.

## Boundary
Risk does not decide whether the strategy is profitable and does not execute. Chat 9 owns approval/execution.
