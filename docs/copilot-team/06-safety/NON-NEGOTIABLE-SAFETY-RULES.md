# Non-Negotiable Safety Rules

## Live trading

No live trading until all prerequisites are complete.

## Exchange credentials

No real exchange credentials in:

- source code
- tests
- fixtures
- prompts
- docs
- logs
- screenshots
- issue descriptions
- pull requests

## AI execution boundary

AI agents must never directly call exchange trading APIs.

Correct path:

```text
AI Analysis
  ↓
Signal
  ↓
Validation
  ↓
Risk Proposal
  ↓
Human Approval
  ↓
Execution Intent
  ↓
Execution Engine
  ↓
Exchange Adapter
```

## Evidence integrity

The system must not fabricate:

- win rates
- probabilities
- backtest results
- sample sizes
- Sharpe ratios
- profit factors
- drawdowns
- market data
- on-chain data
- news

## 75% rule

Use:

```text
Historical conditional win rate >= 75% under defined test conditions
```

Do not use:

```text
75% guaranteed chance to win
```

## No-trade rule

The platform must prefer **NO TRADE** over **UNCERTAIN TRADE**.
