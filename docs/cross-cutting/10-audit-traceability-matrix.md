# Audit and Traceability Matrix

This matrix complements the requirement baseline in
[13-requirements-traceability.md](13-requirements-traceability.md). `RT-###`
references are mandatory on material records or their immutable provenance
links. Recording a trace does not authorize an action; safety, deterministic
risk, and human approval gates remain authoritative.

| RT reference | Decision/action | Primary contract(s) | Must record | Required verification |
|---|---|---|---|---|
| RT-003, RT-004, RT-005 | Analysis | `AnalysisSnapshot`, `EvidenceItem`, `MarketSnapshot` | inputs, source refs, data quality/freshness, agent/model/prompt versions, output schema, uncertainty, supporting and contradictory evidence | `TB-003`, `TB-004`, `TB-005` |
| RT-006 | Signal | `StrategyVersion`, `SignalCandidate`, `SignalEvidencePackage`, `SignalQualification`, `NoTradeDecision` | strategy version, evidence graph, regime, qualification, expiry/invalidation, abstention reason where applicable | `TB-006` |
| RT-007 | Validation | `BacktestResult`, `ValidationResult`, `WalkForwardResult`, `RobustnessResult` | dataset/version, assumptions, costs, methodology, metrics, sample size, OOS/WF status, robustness, validation status | `TB-007` |
| RT-008 | Risk | `AccountSnapshot`, `PortfolioSnapshot`, `RiskProposal`, `RiskAssessment` | account/portfolio snapshots, limits, deterministic calculations, risk-model version, vetoes, revalidation inputs | `TB-008` |
| RT-009 | Approval | `ApprovalRequest`, `ApprovalDecision` | authenticated user identity, exact parameters/hash, signal/strategy/evidence/validation/risk versions, timestamp, reason, expiry, revalidation | `TB-009` |
| RT-009 | Execution | `ExecutionIntent`, `Order`, `Fill`, `Trade` | approved intent, idempotency key, exchange/account, request/response, order IDs, timestamps, state transitions | `TB-009` |
| RT-009, RT-010 | Reconciliation | `Order`, `Fill`, `Position`, `Trade` | internal vs exchange state, discrepancies, authoritative source, resolution, operator/system action | `TB-009`, `TB-010` |
| RT-009, RT-013 | Outcome | `TradeOutcome`, `Experience` | actual entry/exit/fills/fees/slippage/funding/PnL/MAE/MFE, actual-vs-counterfactual label, source references | `TB-013` |
| RT-013 | Learning | `Experience`, `LearningObservation`, `LearningInsight`, `Hypothesis`, `Experiment`, `ExperimentResult` | experience refs, observation, hypothesis, experiment/version, evidence, actual/counterfactual distinction | `TB-013` |
| RT-012, RT-013 | Governance | `StrategyChangeProposal`, `GovernanceDecision` | proposal, reviewers, decision, conditions, effective version, rollback target, validation and shadow/paper evidence | `TB-012`, `TB-013` |
| RT-001, RT-010 | Safety/Security | `SafetyDecision`, `TradingReadinessState`, `AuditEvent` | policy, readiness state, event, affected components, decision, response/recovery, security provenance | `TB-001`, `TB-010` |

Material audit records are append-only/immutable where practical.

## Trace reconstruction

The minimum backward chain is:

`Trade → Order/Fill → ExecutionIntent → ApprovalDecision → RiskProposal → ValidationResult → SignalCandidate → StrategyVersion → SignalEvidencePackage → AnalysisSnapshot → MarketSnapshot → Source Data`

The minimum forward chain is:

`TradeOutcome → Experience → LearningObservation → Hypothesis → Experiment → ExperimentResult → GovernanceDecision → New Version`

Missing or unverifiable links are an audit failure and must not be silently
filled with inferred or fabricated data.
