# Decision Provenance Graph

## Purpose
Make every production decision reconstructable.

## Required trace for a trade
```text
Trade -> ApprovalDecision -> RiskProposal -> ValidationResult -> Signal -> StrategyVersion -> MarketContext -> AnalysisSnapshot -> AgentOutputs -> EvidenceItems -> MarketSnapshot -> DataSources -> DataQualityReport
```

## Required trace for learning
```text
TradeOutcome -> Experience -> Evaluation -> LearningObservation -> LearningInsight -> Hypothesis -> Experiment -> ExperimentResult -> GovernanceDecision -> Strategy/Prompt/Model Version
```

## Audit requirement
No production action may lack traceability references. Missing provenance blocks production eligibility.
