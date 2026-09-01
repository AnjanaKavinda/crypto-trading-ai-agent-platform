# Agent Handoff Matrix

## Primary handoffs
- Data services -> Analysis agents: MarketSnapshot, DataQualityReport, FeatureSet.
- Analysis agents -> Meta-Analysis: AgentResult, EvidenceItems, limitations, conflicts.
- Meta-Analysis -> Strategy Engine: MarketContext, ConfluenceAssessment, ConflictAssessment, AdversarialAssessment.
- Strategy Engine -> Validation: StrategyVersion, SignalDefinition, QualificationRules, HistoricalEvidenceRequirements.
- Validation -> Risk: ValidationResult, expectancy, win rate, drawdown, regime performance, robustness.
- Risk -> Approval: RiskProposal, constraints, warnings, risk decision.
- Approval -> Execution: ApprovalDecision, approved parameters, risk revalidation id.
- Execution -> Learning: Orders, fills, position, trade outcome.
- Learning -> Governance: Insights, hypotheses, experiments, recommendations.
