# Domain Contract Registry

This registry is authoritative for cross-domain meaning. Producer owns creation semantics; consumers may not redefine them.

| ID | Contract | Owner/Producer | Primary Consumers | Core invariant |
|---|---|---|---|---|
| C-001 | MarketData | Data | Analysis, Research | Normalized market observations; not analysis. |
| C-002 | MarketSnapshot | Data | Analysis, Strategy, Learning | Point-in-time market state with source references. |
| C-003 | DataQualityReport | Data Quality | All downstream domains | Freshness, completeness, anomalies, source agreement and quality status. |
| C-004 | FeatureSet | Feature/Quant | Analysis, Validation | Versioned deterministic derived features. |
| C-005 | MarketRegime | Regime Engine | Analysis, Strategy, Validation, Risk, UX, Learning | Contextual regime classification with evidence and validity window. |
| C-006 | MarketContext | Analysis | Strategy | Chat 5 analytical synthesis; cannot authorize trades. |
| C-007 | AnalysisSnapshot | Analysis | Strategy, Audit, Learning | Immutable/versioned analytical output snapshot. |
| C-008 | EvidenceItem | Analysis/Data | Strategy, Validation, UX, Audit | Traceable evidence with source, time, method, reliability and expiry. |
| C-009 | ConfluenceAssessment | Meta Analysis | Strategy | Weighted support/neutral/contradiction with independence analysis. |
| C-010 | ConflictAssessment | Meta Analysis | Strategy, Safety | Conflicting evidence and severity. |
| C-011 | FundamentalAssessment | Fundamental | MarketContext | Crypto-native fundamental evidence. |
| C-012 | TechnicalAssessment | Technical | MarketContext | Deterministic/structured technical findings. |
| C-013 | SMCAssessment | SMC | MarketContext | Structured SMC observations and invalidation. |
| C-014 | WyckoffAssessment | Wyckoff | MarketContext | Structured phase/event interpretation. |
| C-015 | DerivativesAssessment | Derivatives | MarketContext | Funding, OI, liquidation, basis and positioning evidence. |
| C-016 | OnChainAssessment | On-chain | MarketContext | Blockchain-native activity/flow evidence. |
| C-017 | SentimentAssessment | Sentiment | MarketContext | Sentiment/narrative evidence with provenance. |
| C-018 | EventRiskAssessment | Event Risk | Strategy, Risk, Safety, UX | Known event risks and timing windows. |
| C-019 | AdversarialAssessment | Critic | Strategy, Meta Analysis | Counter-thesis, failure conditions and contradictory evidence. |
| C-020 | Strategy | Strategy | Strategy Engine, Research | Immutable strategy identity and rules family. |
| C-021 | StrategyVersion | Strategy Governance | Validation, Signal, Learning | Versioned rules/parameters/eligibility with lifecycle status. |
| C-022 | StrategyEligibility | Strategy | Signal | Eligibility by asset/timeframe/regime/data state. |
| C-023 | SignalCandidate | Signal | Qualification | Candidate setup; never an order. |
| C-024 | SignalEvidencePackage | Signal | Validation, Risk, Approval, UX | Evidence graph and qualification context. |
| C-025 | SignalQualification | Signal/Validation | Risk, UX | Historical conditional qualification, not probability. |
| C-026 | NoTradeDecision | Signal | UX, Risk, Safety, Learning | First-class abstention with machine-readable reasons. |
| C-027 | BacktestResult | Quant Validation | Validation, Research | Reproducible backtest with costs/assumptions. |
| C-028 | ValidationResult | Quant Validation | Risk, Approval | OOS/walk-forward/robustness and validation status. |
| C-029 | WalkForwardResult | Quant Validation | Validation, Learning | Walk-forward folds/results. |
| C-030 | RobustnessResult | Quant Validation | Risk, Governance | Sensitivity/Monte Carlo/regime robustness summary. |
| C-031 | CalibrationResult | Quant/Model Evaluation | Meta Analysis, Learning | Calibration separate from AI confidence. |
| C-032 | AccountSnapshot | Risk | Risk, Approval, Execution | Point-in-time account state. |
| C-033 | PortfolioSnapshot | Risk | Risk, Approval | Point-in-time portfolio exposures/correlations. |
| C-034 | RiskProposal | Risk | Approval | Deterministic entry/SL/TP/size/leverage/risk decision. |
| C-035 | RiskAssessment | Risk | Approval, Audit | Detailed deterministic risk checks and vetoes. |
| C-036 | PositionSizingResult | Risk | RiskProposal | Deterministic sizing result. |
| C-037 | ApprovalRequest | Approval Gateway | Human/UX | Exact configuration presented for decision. |
| C-038 | ApprovalDecision | Human Gateway | Execution | Authenticated decision bound to exact configuration. |
| C-039 | ExecutionIntent | Execution Gateway | Execution Engine | Approved, risk-valid, idempotent intent. |
| C-040 | Order | Execution | Exchange, Monitoring, Audit | Order state and exchange identifiers. |
| C-041 | Fill | Execution/Exchange | Position, Reconciliation | Fill execution fact. |
| C-042 | Position | Portfolio/Execution | Monitoring, Risk, UX | Authoritative position state. |
| C-043 | Trade | Trade Lifecycle | Learning, Audit | Lifecycle aggregate of approved execution. |
| C-044 | TradeOutcome | Trade Lifecycle | Learning, Performance | Actual outcome distinct from counterfactuals. |
| C-045 | Experience | Learning | Evaluation, Memory | Immutable decision lifecycle reference. |
| C-046 | LearningObservation | Learning | Insight | Observed pattern with support and scope. |
| C-047 | LearningInsight | Learning | Hypothesis | Evidence-bounded insight; not production authority. |
| C-048 | Hypothesis | Research/Learning | Experiment | Falsifiable proposed improvement. |
| C-049 | Experiment | Research | Quant Validation | Versioned controlled test. |
| C-050 | ExperimentResult | Quant/Learning | Governance | Validated/inconclusive/degraded comparison. |
| C-051 | StrategyChangeProposal | Learning/Governance | Governance | Proposal only; cannot directly mutate production. |
| C-052 | AgentPerformance | Evaluation | Orchestrator, Governance, UX | Contextual reliability/calibration/drift. |
| C-053 | StrategyPerformance | Evaluation | Governance, UX | Performance by version/regime/asset/timeframe. |
| C-054 | SystemAwarenessSnapshot | Awareness | Orchestrator, UX, Safety | Data/agent/strategy/risk/execution/unknown state. |
| C-055 | DriftAssessment | Evaluation | Governance, Safety | Data/model/prompt/strategy/calibration drift. |
| C-056 | KnowledgeArtifact | Knowledge Governance | Retrieval, Research | State-labelled knowledge with provenance. |
| C-057 | GovernanceDecision | Governance | Deployment, Registry | Approved/rejected/shadow/paper/rollback decision. |
| C-058 | SafetyDecision | Safety Control Plane | All control/execution paths | Fail-closed safety policy decision. |
| C-059 | TradingReadinessState | Safety | Approval, Execution, UX | READY/DEGRADED/BLOCKED/EMERGENCY/UNKNOWN. |
| C-060 | AuditEvent | Audit | Audit Store, Security | Immutable material action/decision event. |

## Global contract rules

- Contracts are versioned.
- Breaking changes require impact analysis, migration strategy and architecture review.
- Critical financial values use deterministic representations and validation.
- Historical records are not silently rewritten.
- `SignalCandidate` is not an order.
- `ApprovalDecision` applies only to its exact immutable configuration.
- `Experience` references trading facts; it does not replace them.
- Learning contracts never carry execution authority.
