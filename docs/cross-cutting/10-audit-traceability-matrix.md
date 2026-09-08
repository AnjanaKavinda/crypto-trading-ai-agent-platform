# Audit and Traceability Matrix

This matrix complements the requirement baseline in
[13-requirements-traceability.md](13-requirements-traceability.md). `RT-###`
references are mandatory on material records or their immutable provenance
links. Recording a trace does not authorize an action; safety, deterministic
risk, and human approval gates remain authoritative.

| RT reference | Decision/action | Primary contract(s) | Must record | Required verification |
|---|---|---|---|---|
| RT-003, RT-004, RT-005 | Analysis | `AnalysisSnapshot`, `EvidenceItem`, `MarketSnapshot` | inputs, source refs, data quality/freshness, agent/model/prompt versions, output schema, uncertainty, supporting and contradictory evidence | Schema/provenance validation; stale or invalid input handling |
| RT-006 | Signal | `StrategyVersion`, `SignalCandidate`, `SignalEvidencePackage`, `SignalQualification`, `NoTradeDecision` | strategy version, evidence graph, regime, qualification, expiry/invalidation, abstention reason where applicable | Signal state and NO_TRADE tests |
| RT-007 | Validation | `BacktestResult`, `ValidationResult`, `WalkForwardResult`, `RobustnessResult` | dataset/version, assumptions, costs, methodology, metrics, sample size, OOS/WF status, robustness, validation status | Quant validation and small-sample evidence tests |
| RT-008 | Risk | `AccountSnapshot`, `PortfolioSnapshot`, `RiskProposal`, `RiskAssessment` | account/portfolio snapshots, limits, deterministic calculations, risk-model version, vetoes, revalidation inputs | Risk failure, sizing, leverage, liquidation, and parameter-change tests |
| RT-009 | Approval | `ApprovalRequest`, `ApprovalDecision` | authenticated user identity, exact parameters/hash, signal/strategy/evidence/validation/risk versions, timestamp, reason, expiry, revalidation | Explicit approval, binding, expiry, and replay tests |
| RT-009 | Execution | `ExecutionIntent`, `Order`, `Fill`, `Trade` | approved intent, idempotency key, exchange/account, request/response, order IDs, timestamps, state transitions | Idempotency, authorization, and order lifecycle tests |
| RT-009, RT-010 | Reconciliation | `Order`, `Fill`, `Position`, `Trade` | internal vs exchange state, discrepancies, authoritative source, resolution, operator/system action | Unknown response, duplicate, partial-fill, and mismatch recovery tests |
| RT-009, RT-013 | Outcome | `TradeOutcome`, `Experience` | actual entry/exit/fills/fees/slippage/funding/PnL/MAE/MFE, actual-vs-counterfactual label, source references | Historical reconstruction and outcome integrity tests |
| RT-013 | Learning | `Experience`, `LearningObservation`, `LearningInsight`, `Hypothesis`, `Experiment`, `ExperimentResult` | experience refs, observation, hypothesis, experiment/version, evidence, actual/counterfactual distinction | Learning permission and governance tests |
| RT-012, RT-013 | Governance | `StrategyChangeProposal`, `GovernanceDecision` | proposal, reviewers, decision, conditions, effective version, rollback target, validation and shadow/paper evidence | No auto-promotion; version and rollback checks |
| RT-001, RT-010 | Safety/Security | `SafetyDecision`, `TradingReadinessState`, `AuditEvent` | policy, readiness state, event, affected components, decision, response/recovery, security provenance | Fail-closed, readiness, audit durability, and secret-scan checks |

Material audit records are append-only/immutable where practical.

## Trace reconstruction

The minimum backward chain is:

`Trade → Order/Fill → ExecutionIntent → ApprovalDecision → RiskProposal → ValidationResult → SignalCandidate → StrategyVersion → SignalEvidencePackage → AnalysisSnapshot → MarketSnapshot → Source Data`

The minimum forward chain is:

`TradeOutcome → Experience → LearningObservation → Hypothesis → Experiment → ExperimentResult → GovernanceDecision → New Version`

Missing or unverifiable links are an audit failure and must not be silently
filled with inferred or fabricated data.
