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
  Governance artifacts are labeled separately and are not domain contracts.
* Verification references point to the current test, state, permission,
  failure, or audit baseline. A future implementation slice must add concrete
  executable tests without changing the requirement mapping.

## Requirement-to-chat-to-contract-to-test baseline

| ID | Playbook requirement boundary | Authoritative source | Primary contracts or governance artifacts | Required controls | Verification baseline | Review owner |
|---|---|---|---|---|---|---|
| RT-001 | Constitution, operating modes, evidence, deterministic risk, human approval, auditability, and governed learning | `docs/playbook/01-specification/01-chat-1-product-requirements-system-constitution.md` | `MarketSnapshot`, `EvidenceItem`, `RiskProposal`, `ApprovalDecision`, `SafetyDecision`, `AuditEvent` | Permission matrix; state machines; failure/recovery matrix | `TB-001` | Architect + QA |
| RT-002 | Planes, bounded contexts, service boundaries, control-plane boundaries, and environment separation | `docs/playbook/01-specification/02-chat-2-enterprise-system-architecture.md` | `SystemAwarenessSnapshot`, `SafetyDecision`, `TradingReadinessState` | Agent responsibility/handoff matrices; permission matrix | `TB-002` | Architect |
| RT-003 | Runtime agent responsibilities, handoffs, permissions, model routing, adversarial analysis, and per-result evaluation | `docs/playbook/01-specification/03-chat-3-multi-ai-agent-trading-intelligence.md` | `AnalysisSnapshot`, `EvidenceItem`, `AdversarialAssessment`, `AgentPerformance`, `AgentEvaluation` | Responsibility, handoff, permission, C-066 outcome/schema/evidence, and disagreement-preserving debate controls | `TB-003`; `tests/backend/test_agent_evaluation.py`; `tests/backend/test_spot_orchestration.py`; `tests/backend/test_spot_debate.py` | Architect + Trading Intelligence |
| RT-004 | Market data, alternative data, quality, freshness, provenance, and source agreement | `docs/playbook/01-specification/04-chat-4-market-data-data-engineering.md` | `MarketData`, `MarketSnapshot`, `DataQualityReport`, `FeatureSet`, `EventRiskAssessment` | Evidence graph; failure/recovery matrix | `TB-004` | Trading Intelligence + Backend + QA |
| RT-005 | Technical, fundamental, SMC, Wyckoff, derivatives, on-chain, sentiment, regime, confluence, and conflict analysis | `docs/playbook/01-specification/05-chat-5-analysis-meta-analysis-engine.md` | `MarketContext`, `MarketRegime`, `TechnicalAssessment`, `FundamentalAssessment`, `SMCAssessment`, `WyckoffAssessment`, `DerivativesAssessment`, `OnChainAssessment`, `SentimentAssessment`, `ConfluenceAssessment`, `ConflictAssessment` | Evidence independence and statistical separation rules | `TB-005` | Trading Intelligence + QA |
| RT-006 | Versioned strategies, candidate signals, evidence qualification, expiration, and first-class NO_TRADE | `docs/playbook/01-specification/06-chat-6-strategy-signal-evidence-qualification.md` | `Strategy`, `StrategyVersion`, `StrategyEligibility`, `SignalCandidate`, `SignalEvidencePackage`, `SignalQualification`, `NoTradeDecision` | State machine; evidence graph; version registry | `TB-006` | Trading Intelligence + QA |
| RT-007 | Reproducible backtesting, OOS, walk-forward, robustness, cost assumptions, and anti-overfitting | `docs/playbook/01-specification/07-chat-7-quant-validation-anti-overfitting.md` | `BacktestResult`, `ValidationResult`, `WalkForwardResult`, `RobustnessResult`, `CalibrationResult` | Version registry; evidence/statistical separation rules | `TB-007` | Trading Intelligence + QA |
| RT-008 | Deterministic account, portfolio, position sizing, leverage, liquidation, limits, and revalidation | `docs/playbook/01-specification/08-chat-8-risk-portfolio-position-sizing.md` | `AccountSnapshot`, `PortfolioSnapshot`, `RiskProposal`, `RiskAssessment`, `PositionSizingResult` | Permission matrix; state machine; failure/recovery matrix | `TB-008` | Backend + QA |
| RT-009 | Human approval, exact-parameter binding, execution intent, order lifecycle, and reconciliation | `docs/playbook/01-specification/09-chat-9-human-approval-execution-exchanges.md` | `ApprovalRequest`, `ApprovalDecision`, `ExecutionIntent`, `Order`, `Fill`, `Position`, `Trade` | Decision provenance graph; permission matrix; execution state machine | `TB-009` | Backend + QA + Human |
| RT-010 | Safety, security, observability, audit, failure recovery, readiness, and kill-switch controls | `docs/playbook/01-specification/10-chat-10-safety-security-observability-recovery.md` | `SafetyDecision`, `TradingReadinessState`, `AuditEvent`, `SystemAwarenessSnapshot` | Audit matrix; failure/recovery matrix; permission matrix | `TB-010` | QA/Security + Architect |
| RT-011 | Supervision cockpit, trader-facing explanations, approval visibility, and safe mode presentation | `docs/playbook/01-specification/11-chat-11-frontend-dashboard-trader-ux.md` | `SignalEvidencePackage`, `RiskProposal`, `ApprovalRequest`, `ApprovalDecision`, `NoTradeDecision`, `SystemAwarenessSnapshot` | Decision provenance graph; permission matrix | `TB-011` | Future frontend work + QA |
| RT-012 | Repository structure, implementation slices, contracts-first delivery, CI, release gates, and Copilot protocol | `docs/playbook/01-specification/12-chat-12-implementation-roadmap-copilot-protocol.md` | `StrategyVersion`, `ValidationResult`; governance artifacts: `ReleaseGate`, `CIValidationReport` | Version registry; definition of done; test traceability matrix | `TB-012` | Architect + QA |
| RT-013 | Immutable experience, performance/drift evaluation, hypotheses, experiments, governance, and controlled adaptation | `docs/playbook/01-specification/13-chat-13-adaptive-intelligence-learning.md` | `Experience`, `LearningObservation`, `LearningInsight`, `Hypothesis`, `Experiment`, `ExperimentResult`, `GovernanceDecision`, `StrategyChangeProposal`, `AgentPerformance`, `StrategyPerformance`, `DriftAssessment`, `SystemAwarenessSnapshot` | Decision provenance graph; version registry; learning state machine | `TB-013` | Trading Intelligence + Architect + QA |

## Verification baseline

`TB-###` identifiers are stable verification requirements for implementation
and review. They are mapped to the existing cross-cutting test matrix where
an invariant already exists; otherwise they identify a required future
contract, permission, state, failure, or audit test. They are not claims that
an executable test has already been implemented.

| ID | Verification requirement | Existing baseline |
|---|---|---|
| TB-001 | No approval, failed risk, unsafe mode, invalid confidence semantics, or insufficient evidence permits live execution. | Test matrix: no approval, risk failure, mode isolation, AI confidence, NO_TRADE |
| TB-002 | Architecture boundaries, permissions, and operating-mode isolation remain compatible. | Permission matrix; contract compatibility; mode-isolation row |
| TB-003 | Agent outputs are schema-validated and learning/analysis agents cannot execute. | Permission matrix; learning-cannot-execute row |
| TB-004 | Missing/stale/degraded data and invalid provenance block applicable actions. | Failure/recovery matrix; stale-data row |
| TB-005 | Correlated evidence is not double-counted and quantitative fields remain distinct. | Evidence graph; AI-confidence/probability row |
| TB-006 | Signal lifecycle, expiry, qualification, and NO_TRADE reasons are enforced. | State machine; NO_TRADE and invalid-signal rows |
| TB-007 | Small samples, failed validation, and missing OOS/WF/robustness evidence cannot qualify a result. | Test matrix: small sample row |
| TB-008 | Risk calculations remain deterministic and parameter changes force revalidation. | Test matrix: risk failure and parameter-modification rows |
| TB-009 | Approval is explicit and bound; duplicate, partial, and unknown execution states reconcile safely. | Test matrix: approval, idempotency, retry, reconciliation rows |
| TB-010 | Safety/readiness/audit controls fail closed and secrets remain absent. | Failure matrix; secrets row |
| TB-011 | Trader-facing views preserve provenance, NO_TRADE, approval state, and confidence semantics. | Contract/provenance checks required by implementation slice |
| TB-012 | Implementation slices preserve contracts, versioning, required checks, and release gates. | Definition of done; contract-breaking-change and secrets rows |
| TB-013 | Learning is append-only/traceable, cannot execute or auto-promote, and distinguishes actual outcomes from counterfactuals. | Permission matrix; learning/governance requirements |

## Market Intelligence architecture mapping

The proposed Market Intelligence Fabric extends the baseline; it does not create a new Playbook chat or imply that a runtime capability is complete.

| Concern | Traceability | Current authority and control |
|---|---|---|
| Fabric placement and provider/agent boundary | RT-002, RT-003, RT-004 | Existing C-001/C-002/C-003 handoff, provider adapters, permission matrix, and data-quality controls |
| Source lineage, comparison, freshness, and conflict | RT-004, RT-005 | C-003 and C-091/C-092 evidence; preserve source identity and explicit disagreement |
| Analysis-only interpretation and MarketIntelligenceSnapshot concept | RT-003, RT-005 | Existing C-006/C-007/C-008 and domain assessment contracts remain canonical; the named snapshot is conceptual until separately governed |
| Strategy, qualification, and NO_TRADE | RT-006, RT-007 | Existing C-021–C-026 and Chat 7 validation remain authoritative |
| Risk, approval, and execution boundaries | RT-008, RT-009 | Existing deterministic risk, permission, state-machine, and human approval controls are unchanged |
| Learning and feature-value evaluation | RT-013 | Outcomes remain factual/provenance-bound; learning cannot directly change production behavior |

Design details and owner direction are recorded in [Market Intelligence Fabric](../architecture/market-intelligence-fabric.md), proposed ADR-0014, and Wave 0 issue #421. CoinGlass is an architectural supplementary source role only; OD-0002/OD-0004, provider terms, and actual ingestion remain unresolved. No `docs/playbook/**` content was changed.

## Baseline usage and status

Every implementation issue must reference the applicable `RT-###` row(s),
contract(s), and verification baseline before code or runtime behavior is
changed. The baseline is complete for the 13-chat scope; executable evidence
is delivered incrementally by the implementation and QA work associated with
each row. No row grants execution authority or changes the live-trading gate.
