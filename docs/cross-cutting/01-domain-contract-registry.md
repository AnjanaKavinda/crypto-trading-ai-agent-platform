# Domain Contract Registry

Registry approval defines cross-domain semantics and ownership only. It does not approve implementation schemas, technology providers, or runtime integrations.

## Classification policy

Only genuine cross-domain contracts receive `C-###`.

| Class | `C-###` eligible | Rule |
|---|---|---|
| Cross-domain contract | Yes | Shared semantic interface crossing bounded domains, with one authoritative producer, primary consumers, and a safety-relevant invariant. |
| Embedded/value object | No | Structured field inside a canonical contract; semantics scoped by parent contract. |
| Enum / state vocabulary | No | Allowed states, lifecycle values, or policy enums used by contracts. |
| Internal service record | No | Service-local implementation record, report, or adapter detail; may be surfaced via read models but not as canonical cross-domain meaning. |
| UI / read-model DTO | No | Frontend/view projection; cannot redefine domain semantics. |
| Architecture/development-governance artifact | No | Repository/process/governance artifact (ADR, CI, release, roadmap, traceability). |

## Canonical cross-domain contracts

IDs `C-001`–`C-060` are preserved unchanged. New IDs are appended sequentially.

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
| C-061 | AgentDefinition | Agent Governance | Orchestrator, Evaluation, Safety | Declares bounded role, allowed inputs/outputs, and non-escalatable authority. |
| C-062 | AgentResult | Agent Runtime | Orchestrator, Handoff, Audit | Structured, attributable, time-bounded output for a specific task context. |
| C-063 | AgentPermissionProfile | Security Governance | Orchestrator, Safety, Approval | Machine-enforceable least-privilege runtime grant bound to role/mode and constrained by `AgentPermissionPolicy`. |
| C-064 | AgentToolAccess | Orchestrator Security | Runtime Agent Shell, Audit | Tool grant is explicit, scoped, revocable, and never implies execution authority. |
| C-065 | AgentHandoff | Orchestrator | Downstream Agents, Audit, Learning | Handoff preserves provenance, unresolved risks, and bounded responsibilities. |
| C-066 | AgentEvaluation | Evaluation | Governance, Learning, Orchestrator | Evaluation is evidence-based and cannot directly modify production execution/risk behavior. |
| C-067 | ModelRoutingDecision | Model Governance | Runtime Agent Router, Audit, Safety | Model/provider choice must be explicit, attributable, and policy-compliant. |
| C-068 | FibonacciAssessment | Technical Analysis | MarketContext, Strategy | Fibonacci findings are reproducible from deterministic inputs and include invalidation context. |
| C-069 | AnalyticalUncertainty | Analysis | Strategy, UX, Safety | Uncertainty must be explicit and cannot be converted into trade authority. |
| C-070 | Signal | Signal Engine | Risk, Approval, UX | Qualified signal only; never executable authority and never a substitute for `ExecutionIntent`. |
| C-071 | OOSResult | Quant Validation | ValidationResult, Governance, Risk | Out-of-sample evidence is explicitly partitioned from in-sample optimization. |
| C-072 | MonteCarloResult | Quant Validation | RobustnessResult, Risk, Governance | Simulation assumptions, sample size, and seed context are traceable and reproducible. |
| C-073 | SensitivityResult | Quant Validation | RobustnessResult, Risk | Parameter sensitivity must expose degradation boundaries, not only best-case points. |
| C-074 | RegimeValidationResult | Quant Validation | ValidationResult, Strategy, Risk | Validation must state regime scope and reject regime-mismatched deployment. |
| C-075 | PositionSnapshot | Portfolio | Risk, Reconciliation, UX | Point-in-time position truth is attributable and reconcilable to fills/orders. |
| C-076 | LeverageAssessment | Risk | RiskProposal, Approval | Leverage limits are deterministic and fail-closed on unknown account/exchange state. |
| C-077 | LiquidationAssessment | Risk | RiskProposal, Approval, Safety | Liquidation distance assumptions are explicit, deterministic, and conservative. |
| C-078 | StopLossAssessment | Risk | RiskProposal, Approval | Stop-loss validity must align with strategy logic and maximum-loss policy bounds. |
| C-079 | TakeProfitAssessment | Risk | RiskProposal, Approval | Take-profit targets must preserve risk-reward and invalidation consistency. |
| C-080 | PortfolioImpact | Risk Engine | Approval, Safety, UX | New proposal impact must not violate portfolio-wide exposure constraints. |
| C-081 | StressTestResult | Risk Engine | Risk, Governance, Safety | Stress scenarios and resulting breaches must be explicit and auditable. |
| C-082 | RiskDecision | Risk | Approval, Execution, Audit | Deterministic risk verdict is authoritative for risk gating and cannot independently authorize execution outside approved/revalidated `ExecutionIntent` flow. |
| C-083 | RiskRevalidationResult | Risk | Approval, Execution, Safety | Material changes or stale context require revalidation before any execution path. |
| C-084 | OrderRequest | Execution Gateway | Exchange Adapter, Audit | Exchange submission request must derive from approved intent and enforce idempotency binding. |
| C-085 | ExchangeOrder | Exchange Adapter | Execution, Reconciliation, Monitoring | Exchange-specific order state must reconcile back to canonical `Order` without semantic drift. |
| C-086 | SecurityEvent | Security | Safety, Audit, Governance | Security-critical event triggers governed response paths; no silent suppression. |
| C-087 | FailureEvent | Runtime Services | Safety, Recovery, Audit | Critical failure events are explicit, attributable, and policy-routable. |
| C-088 | RecoveryAction | Recovery Control Plane | Runtime Services, Audit, Governance | Recovery actions are policy-bounded, idempotent where required, and never bypass safety gates. |
| C-089 | PromptInjectionAssessment | Security | Safety, Agent Governance, Audit | Prompt-injection risk is explicit and must gate unsafe tool/authority escalation. |
| C-090 | CounterfactualAnalysis | Evaluation | Governance, Strategy Evaluation | Counterfactual outcomes remain distinct from factual trade outcomes and audit history. |
| C-091 | DataSourceRecord | Data | Analysis, Validation, Audit | Immutable source/provider/time/licensing/provenance identity for ingested data. |
| C-092 | DatasetVersion | Data Governance | Validation, Research, Audit | Exact reproducible dataset composition and lineage; never silently mutated. |
| C-093 | AgentIndependenceReport | Evaluation | Meta Analysis, Governance, Audit | Independence and correlation limits must prevent duplicate evidence/agent reasoning from being counted as independent confirmation. |
| C-094 | BiasCheckReport | Quant Validation | Validation, Governance, Audit | Leakage, survivorship, look-ahead, and selection-bias checks are explicit and auditable. |
| C-095 | ExecutionReport | Execution | Reconciliation, Monitoring, Audit, Safety | Attributable execution outcome including partial/unknown/failure states; never treated as reconciled by assumption. |
| C-096 | ReconciliationReport | Reconciliation | Portfolio, Risk, Safety, Audit | Internal-versus-exchange deltas remain explicit and block conflicting action while unresolved. |
| C-097 | SafetyPolicy | Safety Governance | Safety Control Plane, Approval, Execution, Audit | Versioned fail-closed policy authority that control decisions must enforce. |
| C-098 | AgentPermissionPolicy | Security Governance | Orchestrator, Safety, Audit | Versioned least-privilege authority ceiling that runtime profiles cannot exceed. |
| C-099 | SafetyIncidentReport | Security | Safety, Operations, Governance, Audit | Immutable incident scope/evidence/response status with no silent suppression. |
| C-100 | ChampionChallengerRecord | Evaluation | Validation, Governance, Registry, Audit | Versioned champion/challenger comparison record; cannot authorize automatic production promotion. |

## Canonical name / alias / supersession clarifications

| Canonical | Alias / related name | Disposition |
|---|---|---|
| C-045 Experience | ExperienceRecord | Alias for canonical cross-domain meaning in Chat 13 usage. |
| C-070 Signal | SignalCandidate (C-023), SignalQualification (C-025), NoTradeDecision (C-026) | Distinct lifecycle contracts: candidate → qualification/NO_TRADE → qualified signal. `Signal` cannot bypass qualification. |
| C-024 SignalEvidencePackage | EvidenceGraph | `EvidenceGraph` is an embedded/value-object structure within the package, not a separate canonical contract. |
| C-063 AgentPermissionProfile | AgentPermissionPolicy (C-098) | `AgentPermissionPolicy` is the canonical versioned authority ceiling; `AgentPermissionProfile` is a runtime grant constrained by that ceiling. Neither grants trade approval or exchange execution authority. |
| C-031 CalibrationResult | CalibrationRecord | Alias in Chat 13 terminology. |

## Chats 2–13 coverage and disposition

Every explicit required name is dispositioned as registered canonical contract, alias, value object, enum/state vocabulary, internal service record, UI/read-model DTO, or governance artifact.

| Chat | Required names | Disposition |
|---|---|---|
| Chat 2 | SystemContext, ArchitectureDecisionRecord, PlaneBoundary, ServiceBoundary, EventBoundary, DeploymentBoundary, IntegrationBoundary, RuntimeMode, EnvironmentBoundary | Governance artifacts except `RuntimeMode` (enum/state vocabulary). |
| Chat 3 | AgentDefinition, AgentResult, AgentPermissionProfile, AgentToolAccess, AgentHandoff, AgentEvaluation, AdversarialAssessment, AgentIndependenceReport, ModelRoutingDecision | Registered: C-061, C-062, C-063, C-064, C-065, C-066, C-019, C-093, C-067. |
| Chat 4 | MarketData, MarketSnapshot, DataQualityReport, DataSourceRecord, DatasetVersion, EventData, FundamentalData, OnChainData, DerivativesData, SentimentData, MacroData, FeatureSet | Registered: C-001, C-002, C-003, C-091, C-092, C-004. Data-type payloads (`EventData`, `FundamentalData`, `OnChainData`, `DerivativesData`, `SentimentData`, `MacroData`) are embedded/value objects. |
| Chat 5 | MarketContext, AnalysisSnapshot, EvidenceItem, TechnicalAssessment, FundamentalAssessment, SMCAssessment, WyckoffAssessment, FibonacciAssessment, DerivativesAssessment, OnChainAssessment, SentimentAssessment, EventRiskAssessment, MarketRegime, ConfluenceAssessment, ConflictAssessment, AdversarialAssessment, AnalyticalUncertainty | Registered: C-006, C-007, C-008, C-012, C-011, C-013, C-014, C-068, C-015, C-016, C-017, C-018, C-005, C-009, C-010, C-019, C-069. |
| Chat 6 | Strategy, StrategyVersion, StrategyEligibility, StrategyCondition, SignalCandidate, Signal, SignalEvidencePackage, EvidenceGraph, SignalQualification, QualificationRuleSet, NoTradeDecision, NoTradeReason, SignalLifecycleState | Registered: C-020, C-021, C-022, C-023, C-070, C-024, C-025, C-026. `StrategyCondition`, `QualificationRuleSet`, `NoTradeReason` are embedded/value objects. `EvidenceGraph` embedded/value object alias under C-024. `SignalLifecycleState` enum/state vocabulary. |
| Chat 7 | BacktestResult, ValidationResult, OOSResult, WalkForwardResult, RobustnessResult, BiasCheckReport, MonteCarloResult, SensitivityResult, RegimeValidationResult, ValidationFreshness, DatasetVersion, StrategyValidationStatus | Registered: C-027, C-028, C-071, C-029, C-030, C-094, C-072, C-073, C-074, C-092. `ValidationFreshness`, `StrategyValidationStatus` enum/state vocabularies. |
| Chat 8 | AccountSnapshot, PortfolioSnapshot, PositionSnapshot, RiskProposal, RiskAssessment, PositionSizingResult, LeverageAssessment, LiquidationAssessment, StopLossAssessment, TakeProfitAssessment, PortfolioImpact, StressTestResult, RiskDecision, RiskRevalidationResult | Registered: C-032, C-033, C-075, C-034, C-035, C-036, C-076, C-077, C-078, C-079, C-080, C-081, C-082, C-083. |
| Chat 9 | ApprovalRequest, ApprovalDecision, ApprovalBindingHash, ExecutionIntent, OrderRequest, Order, ExchangeOrder, Fill, Position, Trade, ExecutionReport, ReconciliationReport, IdempotencyKey, ExecutionState | Registered: C-037, C-038, C-039, C-084, C-040, C-085, C-041, C-042, C-043, C-095, C-096. `ApprovalBindingHash`, `IdempotencyKey` embedded/value objects. `ExecutionState` enum/state vocabulary. |
| Chat 10 | SafetyPolicy, SafetyDecision, TradingReadinessState, KillSwitchState, CircuitBreakerState, SecurityEvent, AuditEvent, FailureEvent, RecoveryAction, AgentPermissionPolicy, PromptInjectionAssessment, SafetyIncidentReport | Registered: C-097, C-058, C-059, C-086, C-060, C-087, C-088, C-098, C-089, C-099. `KillSwitchState`, `CircuitBreakerState` enum/state vocabularies. |
| Chat 11 | SignalViewModel, EvidenceReportView, RiskProposalView, ApprovalView, NoTradeView, AgentHealthView, SystemAwarenessView, StrategyPerformanceView, AuditTimelineView, ExecutionMonitorView, GovernanceQueueView | All classified as UI/read-model DTOs (presentation contracts only; no `C-###`). |
| Chat 12 | MethodologyCategory, IndicatorMetadata, FundamentalAssessment, TechnicalIndicatorAssessment, OnChainAssessment, SentimentAssessment, ConfluenceIndependenceAssessment, TraderFacingExplanation, RepositoryMap, ImplementationSlice, CopilotTaskPrompt, DefinitionOfDone, TestTraceabilityMatrix, ContractRegistry, ADR, MigrationPlan, ReleaseGate, EnvironmentConfig, CIValidationReport, agent matrix, handoff matrix, evidence graph, decision provenance, permission matrix, state machines, version registry, audit matrix, failure matrix, test traceability matrix | Registered: C-011, C-012, C-016, C-017. `TechnicalIndicatorAssessment` aliases Technical scope under C-012. `ConfluenceIndependenceAssessment` aliases independence logic across C-009 and C-093. `MethodologyCategory` enum/state vocabulary. `IndicatorMetadata`, `EnvironmentConfig` embedded/value objects. `TraderFacingExplanation` UI/read-model DTO. Remaining names are governance artifacts. |
| Chat 13 | ExperienceRecord, LearningObservation, LearningInsight, Hypothesis, Experiment, ExperimentResult, CounterfactualAnalysis, AgentPerformance, StrategyPerformance, CalibrationRecord, DriftAssessment, SystemAwarenessSnapshot, KnowledgeArtifact, GovernanceDecision, StrategyChangeProposal, ChampionChallengerRecord | Registered: C-045 (alias `ExperienceRecord`), C-046, C-047, C-048, C-049, C-050, C-090, C-052, C-053, C-031 (alias `CalibrationRecord`), C-055, C-054, C-056, C-057, C-051, C-100. |

## Approval scope and change control

- Registry approval establishes cross-domain semantics and ownership; schemas and implementation artifacts are intentionally deferred.
- Breaking changes require impact analysis, migration/version strategy, architecture review, and explicit human approval.
- Historical contract meaning is never silently rewritten; corrections are additive/superseding with provenance.
- `SignalCandidate` is never an order, `Signal` never bypasses qualification, and `ApprovalDecision` remains bound to exact immutable configuration.
- Risk, approval, safety, idempotency, reconciliation, learning-governance, and fail-closed boundaries remain mandatory.
- Open technology/provider choices remain unresolved per [`14-open-decisions.md`](./14-open-decisions.md).

## Deferred consistency work (out of scope for this issue)

- Align non-registry artifacts that still use deprecated or context-local names with canonical names/aliases above (without changing semantics).
- Resolve cross-artifact `TradingReadinessState` vocabulary drift (`01-domain-contract-registry.md`, `08-state-machine-registry.md`, Chat 10) through governed impact analysis and ADR/human approval before any semantic harmonization.
- Add schema-level contract definitions and compatibility tests in later implementation phases.

## Validation evidence for this update

- Existing IDs `C-001`–`C-060` preserved and unique.
- New IDs appended sequentially `C-061`–`C-100`, unique and not reused.
- Every explicit Chats 2–13 required name has a disposition in this document.
- Every newly registered contract includes authoritative producer, primary consumers, and safety-relevant invariant.
