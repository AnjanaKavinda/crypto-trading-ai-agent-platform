# Decision Provenance Graph

A production trade must be traceable backward:

`Trade → Orders/Fills → ExecutionIntent → ApprovalDecision → RiskProposal → ValidationResult → Signal → StrategyVersion → EvidenceGraph → AnalysisSnapshot → MarketSnapshot → Source Data`

And forward:

`TradeOutcome → Experience → Evaluation → LearningObservation → Hypothesis → Experiment → ExperimentResult → GovernanceDecision → New Version`

Model, prompt, dataset, strategy, risk-model, policy and configuration versions must be linked where relevant.
