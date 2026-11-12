# Decision Provenance Graph

A production trade must be traceable backward:

`Trade → Orders/Fills → ExecutionIntent → ApprovalDecision → RiskProposal → ValidationResult → Signal → StrategyVersion → EvidenceGraph → AnalysisSnapshot → MarketSnapshot → Source Data`

And forward:

`TradeOutcome → Experience → Evaluation → LearningObservation → Hypothesis → Experiment → ExperimentResult → GovernanceDecision → New Version`

Model, prompt, dataset, strategy, risk-model, policy and configuration versions must be linked where relevant.


## ADR-0022 — Spot OOS

C-071v2 binds protocol/journal to separate development/holdout C-027v3 runs, #94 reports and native C-092 dataset/manifest pins. Require canonical closure/live issuance/recomputation. Missing history INCONCLUSIVE; reuse FAILED. Completeness covers supplied records only. No qualification/risk/promotion/execution/retention edge. [ADR](../adr/ADR-0022-spot-oos-protocol-and-result-boundary.md).
