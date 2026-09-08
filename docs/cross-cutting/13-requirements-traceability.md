# Requirements Traceability

This is the baseline map from the authoritative 13-chat playbook to the
contracts, cross-cutting controls, and verification evidence that must be
used by implementation slices. It is a governance artifact, not evidence that
the mapped runtime capability has already been implemented.

## Traceability key

* `RT-###` identifies a requirement family for issue, implementation, and
  review references.
* Contract names refer to the authoritative
  [domain contract registry](01-domain-contract-registry.md).
* Verification references point to the current test, state, permission,
  failure, or audit baseline. A future implementation slice must add concrete
  executable tests without changing the requirement mapping.

## Requirement-to-chat-to-contract-to-test baseline

| ID | Playbook requirement boundary | Authoritative source | Primary contracts | Required controls | Verification baseline | Review owner |
|---|---|---|---|---|---|---|
| RT-001 | Constitution, operating modes, evidence, deterministic risk, human approval, auditability, and governed learning | `docs/playbook/01-specification/01-chat-1-product-requirements-system-constitution.md` | `MarketSnapshot`, `EvidenceItem`, `RiskProposal`, `ApprovalDecision`, `SafetyDecision`, `AuditEvent` | Permission matrix; state machines; failure/recovery matrix | Test matrix: no approval, risk failure, mode isolation, AI confidence separation, NO_TRADE, secrets | Architect + QA |
| RT-002 | Planes, bounded contexts, service boundaries, control-plane boundaries, and environment separation | `docs/playbook/01-specification/02-chat-2-enterprise-system-architecture.md` | `SystemAwarenessSnapshot`, `SafetyDecision`, `TradingReadinessState` | Agent responsibility/handoff matrices; permission matrix | Contract compatibility, permission, and research/paper/live isolation checks | Architect |
| RT-003 | Runtime agent responsibilities, handoffs, permissions, model routing, and adversarial analysis | `docs/playbook/01-specification/03-chat-3-multi-ai-agent-trading-intelligence.md` | `AnalysisSnapshot`, `EvidenceItem`, `AdversarialAssessment`, `AgentPerformance` | Responsibility, handoff, and permission matrices | Learning cannot execute; contract/schema validation; AI output remains untrusted | Architect + Trading Intelligence |
| RT-004 | Market data, alternative data, quality, freshness, provenance, and source agreement | `docs/playbook/01-specification/04-chat-4-market-data-data-engineering.md` | `MarketData`, `MarketSnapshot`, `DataQualityReport`, `FeatureSet`, `EventRiskAssessment` | Evidence graph; failure/recovery matrix | Stale/missing data blocks applicable actions; source and freshness validation | Trading Intelligence + Backend + QA |
| RT-005 | Technical, fundamental, SMC, Wyckoff, derivatives, on-chain, sentiment, regime, confluence, and conflict analysis | `docs/playbook/01-specification/05-chat-5-analysis-meta-analysis-engine.md` | `MarketContext`, `MarketRegime`, `TechnicalAssessment`, `FundamentalAssessment`, `SMCAssessment`, `WyckoffAssessment`, `DerivativesAssessment`, `OnChainAssessment`, `SentimentAssessment`, `ConfluenceAssessment`, `ConflictAssessment` | Evidence independence and statistical separation rules | Correlated evidence is not double-counted; confidence, evidence, win rate, and probability remain separate | Trading Intelligence + QA |
| RT-006 | Versioned strategies, candidate signals, evidence qualification, expiration, and first-class NO_TRADE | `docs/playbook/01-specification/06-chat-6-strategy-signal-evidence-qualification.md` | `Strategy`, `StrategyVersion`, `StrategyEligibility`, `SignalCandidate`, `SignalEvidencePackage`, `SignalQualification`, `NoTradeDecision` | State machine; evidence graph; version registry | NO_TRADE for insufficient/conflicting/invalid evidence; invalid or expired signal blocks execution | Trading Intelligence + QA |
| RT-007 | Reproducible backtesting, OOS, walk-forward, robustness, cost assumptions, and anti-overfitting | `docs/playbook/01-specification/07-chat-7-quant-validation-anti-overfitting.md` | `BacktestResult`, `ValidationResult`, `WalkForwardResult`, `RobustnessResult`, `CalibrationResult` | Version registry; evidence/statistical separation rules | Small sample is not strong evidence; validation failure/unavailability prevents execution | Trading Intelligence + QA |
| RT-008 | Deterministic account, portfolio, position sizing, leverage, liquidation, limits, and revalidation | `docs/playbook/01-specification/08-chat-8-risk-portfolio-position-sizing.md` | `AccountSnapshot`, `PortfolioSnapshot`, `RiskProposal`, `RiskAssessment`, `PositionSizingResult` | Permission matrix; state machine; failure/recovery matrix | Risk failure = no execution; parameter modification invalidates stale approval; deterministic calculations | Backend + QA |
| RT-009 | Human approval, exact-parameter binding, execution intent, order lifecycle, and reconciliation | `docs/playbook/01-specification/09-chat-9-human-approval-execution-exchanges.md` | `ApprovalRequest`, `ApprovalDecision`, `ExecutionIntent`, `Order`, `Fill`, `Position`, `Trade` | Decision provenance graph; permission matrix; execution state machine | Explicit approval, replay prevention, idempotency, unknown response reconciliation, partial-fill handling | Backend + QA + Human |
| RT-010 | Safety, security, observability, audit, failure recovery, readiness, and kill-switch controls | `docs/playbook/01-specification/10-chat-10-safety-security-observability-recovery.md` | `SafetyDecision`, `TradingReadinessState`, `AuditEvent`, `SystemAwarenessSnapshot` | Audit matrix; failure/recovery matrix; permission matrix | Fail closed for stale data, unavailable risk, uncertain approval/exchange state, and audit failure; secret scan | QA/Security + Architect |
| RT-011 | Supervision cockpit, trader-facing explanations, approval visibility, and safe mode presentation | `docs/playbook/01-specification/11-chat-11-frontend-dashboard-trader-ux.md` | `SignalEvidencePackage`, `RiskProposal`, `ApprovalRequest`, `ApprovalDecision`, `NoTradeDecision`, `SystemAwarenessSnapshot` | Decision provenance graph; permission matrix | UI/contract checks preserve confidence-vs-probability and make NO_TRADE/approval state explicit | Future frontend work + QA |
| RT-012 | Repository structure, implementation slices, contracts-first delivery, CI, release gates, and Copilot protocol | `docs/playbook/01-specification/12-chat-12-implementation-roadmap-copilot-protocol.md` | `StrategyVersion`, `ValidationResult`, `ReleaseGate` (governance artifact), `CIValidationReport` (governance artifact) | Version registry; definition of done; test traceability matrix | Contract breaking-change detection; secrets scan; required test and release-gate evidence | Architect + QA |
| RT-013 | Immutable experience, performance/drift evaluation, hypotheses, experiments, governance, and controlled adaptation | `docs/playbook/01-specification/13-chat-13-adaptive-intelligence-learning.md` | `Experience`, `LearningObservation`, `LearningInsight`, `Hypothesis`, `Experiment`, `ExperimentResult`, `GovernanceDecision`, `StrategyChangeProposal`, `AgentPerformance`, `StrategyPerformance`, `DriftAssessment`, `SystemAwarenessSnapshot` | Decision provenance graph; version registry; learning state machine | Learning cannot execute or auto-promote; actual vs counterfactual outcomes remain distinct; governance required | Trading Intelligence + Architect + QA |

## Baseline usage and status

Every implementation issue must reference the applicable `RT-###` row(s),
contract(s), and verification baseline before code or runtime behavior is
changed. The baseline is complete for the 13-chat scope; executable evidence
is delivered incrementally by the implementation and QA work associated with
each row. No row grants execution authority or changes the live-trading gate.
