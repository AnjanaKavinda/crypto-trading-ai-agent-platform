# Runtime Agent / Component Responsibility Matrix

This is for the **trading platform runtime team**, not the four GitHub Copilot development agents.

| Component | Primary responsibility | Inputs | Outputs | May recommend? | May approve? | May execute? |
|---|---|---|---|---:|---:|---:|
| Market/Data | Gather/normalize/quality-check data | providers | MarketSnapshot/DataQuality | No | No | No |
| Technical Analyst | Deterministic/structured technical interpretation | MarketSnapshot | TechnicalAssessment | Yes | No | No |
| Price Action / Structure | structure/BOS/CHoCH/SR | MarketSnapshot | Structure findings | Yes | No | No |
| SMC Analyst | OB/FVG/liquidity structures | MarketSnapshot | SMCAssessment | Yes | No | No |
| Wyckoff Analyst | accumulation/distribution/events | MarketSnapshot | WyckoffAssessment | Yes | No | No |
| Fibonacci Analyst | retracement/extension confluence | MarketSnapshot | FibonacciAssessment | Yes | No | No |
| Derivatives Analyst | funding/OI/liquidation/basis | derivatives data | DerivativesAssessment | Yes | No | No |
| On-Chain Analyst | network/flow/holder evidence | on-chain data | OnChainAssessment | Yes | No | No |
| Fundamental Analyst | tokenomics/usage/team/events | fundamental data | FundamentalAssessment | Yes | No | No |
| Sentiment/Narrative | social/news/narrative evidence | sentiment feeds | SentimentAssessment | Yes | No | No |
| Regime Engine | classify contextual regime | features/evidence | MarketRegime | No | No | No |
| Meta-Analysis | combine evidence with independence/conflicts | assessments | MarketContext | Yes | No | No |
| Devil's Advocate | counter-thesis and failure challenge | MarketContext | AdversarialAssessment | Yes | No | No |
| Strategy Engine | evaluate versioned strategies | MarketContext | StrategyEligibility/Setup | Yes | No | No |
| Signal Engine | create/qualify candidate or NO_TRADE | strategy setup/evidence | SignalCandidate/NoTrade | Yes | No | No |
| Quant Validator | backtest/OOS/WF/robustness | strategy version/dataset | ValidationResult | No | No | No |
| Risk Engine | deterministic portfolio/trade risk | validated signal/account/portfolio | RiskProposal | No | No | No |
| Human Approval Gateway | authenticate and bind human decision | risk proposal/evidence | ApprovalDecision | Human | **Yes** | No |
| Execution Engine | execute only approved intent | ExecutionIntent | Order/Fill | No | No | **Approved only** |
| Reconciliation | reconcile exchange vs internal state | orders/fills/exchange | reconciled state | No | No | No new trade |
| Safety Control Plane | enforce readiness/policies/kill switches | all critical states | SafetyDecision | No | veto | veto/control |
| Monitoring | observe positions/system | runtime state | alerts/status | Yes | No | No |
| Learning | evaluate experience/performance/drift | Experience | observations/insights | Yes | No | No |
| Research/Experiment | test hypotheses/challengers | hypotheses/data | ExperimentResult | Yes | No | No |
| Governance | approve version lifecycle promotion | validated experiment | GovernanceDecision | No | production governance | No trade |
