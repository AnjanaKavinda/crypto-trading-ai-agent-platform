# Master Constitution v2.2

Status: Copilot-ready distilled constitution derived from Master Playbook v2.2. The DOCX in `/00-master/MASTER-PLAYBOOK-v2.2.docx` remains the source of truth.

## Product identity

The platform is an enterprise-grade supervised autonomous crypto trading intelligence and execution platform. It is designed to behave like a disciplined professional trading research organization, not a simple trading bot, not a single LLM trading assistant, and not an uncontrolled autonomous trader.

## Global invariants

1. Human approval is mandatory for live trading.
2. No approval means no live execution.
3. Approval applies only to the exact approved trade configuration.
4. Any material change to entry, amount, leverage, stop loss, take profit, margin mode, risk percentage, account state, portfolio state, market state, or evidence version requires revalidation.
5. AI confidence is not statistical probability.
6. Historical win rate is not a guarantee of future performance.
7. The 75% threshold means historical conditional win-rate qualification under defined test conditions, not a prediction.
8. Win rate alone is insufficient; sample size, expectancy, drawdown, robustness, OOS, walk-forward, regime compatibility, data quality, liquidity, slippage, fees, and portfolio risk must be considered.
9. The system must prefer NO_TRADE over uncertain trade.
10. AI outputs are untrusted until validated, grounded, and checked against deterministic policies.
11. Deterministic services control financial calculations, risk, validation, order construction, execution constraints, reconciliation, and audit.
12. LLMs may analyze, compare, explain, summarize, propose, and challenge, but they may not bypass risk, approval, security, audit, or execution controls.
13. No LLM may directly call unrestricted exchange trading APIs.
14. No secrets in prompts, LLM context, logs, or agent memory.
15. Historical trading records, strategy versions, prompt versions, model versions, approval records, and execution events must be immutable or append-only.
16. Counterfactual results are never actual results.
17. Learning cannot directly execute trades or modify production strategies.
18. Experimental strategies, prompts, models, and agent weightings require validation, governance, and shadow/paper testing before production eligibility.
19. If data, risk, approval, account, exchange, or safety state is unknown, fail closed.
20. Every production decision must be reconstructable from source data to outcome.

## Operating modes

- Research: analysis and research only; no live execution permission.
- Paper Trading: simulated execution with realistic fees, slippage, funding, fills, P&L, attribution, and isolated state.
- Live Supervised Trading: requires analysis, candidate signal, statistical validation, evidence report, risk validation, human review, optional human parameter modification, risk recalculation, final validation, explicit approval, execution, and monitoring.

## System lifecycle

```text
DATA -> DATA QUALITY -> MARKET STATE -> MULTI-DOMAIN ANALYSIS -> META-ANALYSIS -> MARKET REGIME -> STRATEGY EVALUATION -> SETUP DETECTION -> SIGNAL GENERATION -> EVIDENCE VALIDATION -> QUANT VALIDATION -> RISK ASSESSMENT -> HUMAN REVIEW -> OPTIONAL PARAMETER MODIFICATION -> RISK REVALIDATION -> FINAL PRE-EXECUTION VALIDATION -> HUMAN APPROVAL -> EXECUTION -> RECONCILIATION -> POSITION MONITORING -> TRADE OUTCOME -> POST-TRADE EVALUATION -> EXPERIENCE RECORDING -> LEARNING -> RESEARCH -> EXPERIMENT -> VALIDATION -> GOVERNANCE -> CONTROLLED IMPROVEMENT
```

## v2.2 methodology patch

The analysis methodology layer must explicitly classify crypto analysis into Fundamental Analysis, Technical Analysis, On-Chain Analysis, and Sentiment Analysis. Institutional indicator taxonomy must classify technical tools by purpose: volume/structure, trend, momentum, volatility/risk, and confirmation. Confluence is valid only when evidence streams are meaningfully independent.
