# Canonical Contract Registry

## Contract ownership rule
Producer owns creation and meaning. Consumers may read/use but must not redefine.

## Core contracts
- MarketData: normalized raw market observation.
- MarketSnapshot: timestamped state for asset/instrument/exchange.
- DataQualityReport: completeness, freshness, source agreement, anomalies, quality status.
- FeatureSet: calculated features and references to source data/calculation versions.
- MarketRegime: trend, volatility, liquidity, risk, momentum, correlation, regime confidence, validity.
- MarketContext: analytical context from Chat 5; analysis only, not trade authorization.
- AnalysisSnapshot: agent outputs, methods, evidence, conflicts, versions.
- EvidenceItem: type, source, timestamp, observation, measurement, method, reliability, data reference, expiration.
- ConfluenceAssessment: supporting/neutral/contradicting factors, weighting method, independence analysis.
- ConflictAssessment: contradictions, severity, missing data, uncertainty.
- AdversarialAssessment: counter-thesis, failure conditions, contradictory evidence, data/model/event risks.
- Strategy / StrategyVersion: versioned strategy definitions and qualification criteria.
- StrategyEligibility: current applicability by asset, timeframe, regime, data quality, liquidity.
- Signal: candidate or qualified opportunity, not an order.
- SignalEvidence: evidence package and graph references.
- SignalQualification: historical conditional win rate, sample, validation status, OOS/walk-forward, robustness.
- ValidationResult: independent quant validation result.
- RiskProposal: deterministic risk output.
- ApprovalRequest / ApprovalDecision: human approval records.
- ExecutionIntent: bridge from approved decision to execution.
- Order / Position / Trade / TradeOutcome: execution and lifecycle records.
- Experience: immutable cross-cutting learning record.
- LearningObservation / LearningInsight / Hypothesis / Experiment / ExperimentResult.
- AgentPerformance / StrategyPerformance / SystemAwarenessSnapshot / GovernanceDecision.

## Versioning
Every shared contract must include schema version, created timestamp, producer, data lineage, and validation status.
