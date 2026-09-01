---
applyTo: "services/market-data/**,services/analysis/**,services/strategy/**,services/validation/**,agents/**,tests/trading-intelligence/**"
---

# AI-Trading Intelligence Path Instructions

These instructions apply to market intelligence, analysis, strategy, evidence, signal, no-trade, and validation implementation.

## Authoritative sources

Read:

- `.github/copilot-instructions.md`
- `AGENTS.md`
- relevant `docs/playbook/**` sections
- approved analytical contracts
- approved ADRs

If sources conflict:

STOP and report the conflict.

## Analytical stage separation

Always preserve:

Raw Data
→ Calculated Metric
→ Analytical Finding
→ Interpretation
→ Trading Hypothesis
→ Candidate Signal
→ Statistical Validation
→ Risk Assessment
→ Human Approval
→ Execution

Do not collapse these stages.

## Deterministic analysis rule

Deterministic calculations must remain deterministic.

Examples:

- indicators
- statistics
- market structure calculations where formalized
- backtesting
- OOS metrics
- walk-forward metrics
- robustness metrics

An LLM may explain results.

An LLM must not invent results.

## Evidence rule

Every candidate signal must be traceable to evidence.

Evidence should preserve where applicable:

- source
- provider
- timestamp
- data freshness
- data quality
- method
- calculation version
- model/prompt version
- supporting evidence
- contradictory evidence
- limitations

## Statistical integrity

Never invent:

- win rate
- sample size
- expectancy
- profit factor
- drawdown
- Sharpe
- Sortino
- probabilities
- OOS results
- walk-forward results
- robustness results

Do not claim profitability.

Do not treat:

- AI confidence
- evidence score
- confluence score
- historical win rate

as equivalent to probability.

## 75% rule

The 75% requirement is a configurable historical conditional qualification threshold.

It is not a future guarantee.

Qualification must also consider relevant validation conditions such as:

- sample size
- OOS
- walk-forward
- expectancy
- robustness
- drawdown
- regime compatibility
- data quality
- liquidity

## Evidence independence

Do not double-count correlated evidence.

Examples:

- multiple moving averages may belong to one trend family
- several momentum indicators may share similar information
- several agents using the same model/data are not fully independent

Confluence must consider independence and correlation.

## NO_TRADE rule

NO_TRADE is a first-class valid outcome.

Return NO_TRADE where appropriate for:

- insufficient evidence
- low sample size
- stale data
- contradictory evidence
- failed validation
- regime mismatch
- poor liquidity
- high event risk
- strategy decay
- model drift
- unknown critical state

Never force BUY or SELL merely to produce an action.

## Strategy governance

Do not silently change strategy logic.

Strategy changes require a new version.

Do not automatically promote experimental strategies.

Do not automatically change production prompts/models from learning output.

## Execution boundary

Do not:

- directly call exchange trading APIs
- access unrestricted exchange credentials
- create live orders
- bypass risk
- bypass human approval
- convert a signal directly into an executable order

## Testing rule

All analytical outputs must be structured and testable.

Where relevant test:

- deterministic calculations
- schema validation
- evidence traceability
- NO_TRADE behavior
- confidence/probability separation
- confluence independence
- stale-data behavior
- regime incompatibility
- validation failure

## Pull request requirement

Every relevant PR must state:

1. Issue number
2. Objective
3. Methodology affected
4. Relevant playbook sections
5. Contracts affected
6. Evidence/data dependencies
7. What changed
8. Why it changed
9. Tests added/updated
10. Statistical assumptions
11. Limitations
12. Risks
13. Deferred work
14. Acceptance criteria status