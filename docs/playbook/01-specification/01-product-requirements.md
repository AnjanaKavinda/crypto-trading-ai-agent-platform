# Product Requirements and System Constitution

## Objective
Build a supervised autonomous crypto trading intelligence and execution platform that combines market data, multi-agent analysis, quantitative validation, risk management, human approval, controlled execution, auditability, and experience learning.

## Functional requirements
- Market intelligence: OHLCV, trades, order book, liquidity, spreads, market depth.
- Technical analysis: indicators, support/resistance, price action, market structure, SMC, Wyckoff, Fibonacci, volume, VWAP, volume profile.
- Fundamental analysis: tokenomics, supply, vesting, unlocks, utility, team, whitepaper/use-case, GitHub/developer activity, partnerships, TVL, protocol revenue, adoption.
- On-chain analysis: active addresses, transactions, exchange flows, whale activity, holder distribution, stablecoin flows, network security.
- Derivatives: funding, open interest, liquidations, basis, long/short ratios, options metrics where available.
- Sentiment: news, social media, Fear & Greed, narrative momentum, crowding, abnormal social activity.
- Meta-analysis: regime, confluence, conflicts, adversarial review, evidence independence.
- Strategy: multiple strategy families, versioned strategy definitions, eligibility by regime.
- Signal: candidate signals, evidence reports, 75% historical conditional win-rate qualification, no-trade state.
- Validation: backtest, OOS, walk-forward, Monte Carlo, sensitivity, transaction costs, slippage, liquidity, robustness.
- Risk: deterministic position sizing, leverage, liquidation, maximum loss, exposure, correlation, stress testing.
- Approval: explicit human approval, exact configuration binding, revalidation after modifications.
- Execution: exchange abstraction, CCXT behind adapter, order monitoring, reconciliation, idempotency.
- Post-trade: outcome attribution, agent performance, strategy performance, learning.

## Non-functional requirements
Secure, observable, auditable, modular, testable, model-agnostic, exchange-agnostic, strategy-agnostic, data-provider-agnostic, fault-tolerant, fail-closed, and maintainable.

## Acceptance criteria
This phase is complete when the product scope, responsibilities, operating modes, safety principles, audit principles, evidence model, risk model, approval model, agent/service responsibilities, and open decisions are documented.
