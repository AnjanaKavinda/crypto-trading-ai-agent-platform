# API Contract Groups

## API groups
- Market Data: snapshots, candles, order books, derivatives, on-chain, fundamentals, sentiment.
- Analysis: market context, evidence, confluence, conflicts, adversarial review.
- Strategy: strategies, versions, eligibility, parameters.
- Signal: candidates, qualified signals, evidence packages, no-trade reasons.
- Validation: backtests, OOS, walk-forward, robustness, validation reports.
- Risk: account snapshot, portfolio snapshot, risk proposal, recalculation.
- Approval: approval requests, decisions, expiry, modification.
- Execution: execution intents, orders, fills, positions, reconciliation.
- Audit: decision trace, event log, provenance.
- Learning: experiences, observations, insights, hypotheses, experiments, governance.
- System: readiness, health, safety, alerts, kill switches.

## API design rule
Critical APIs must accept/return versioned structured contracts, not arbitrary natural-language payloads.
