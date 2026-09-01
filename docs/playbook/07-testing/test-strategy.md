# Test Strategy

## Test layers
Unit tests, integration tests, contract tests, e2e tests, backtest validation tests, strategy tests, risk tests, execution tests, security tests, chaos/failure tests, learning/governance tests.

## Critical test requirements
- Indicators and calculations deterministic.
- Risk formulas exact and audited.
- No live trading in development/test.
- Approval cannot be bypassed.
- Modified parameters require revalidation.
- Unknown state fails closed.
- 75% threshold is configurable and never displayed as guarantee.
- Evidence graph/provenance required for trade eligibility.
