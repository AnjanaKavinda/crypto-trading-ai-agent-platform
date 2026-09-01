# Evidence Graph

Canonical chain:

`Source Data → Data Quality → Feature/Observation → Analytical Finding → EvidenceItem → Strategy Condition → Signal Candidate → Qualification → Validation → Risk → Approval → Execution → Outcome → Experience`

Every edge must be reconstructable through IDs/version references. Evidence nodes must carry source, timestamp, method, freshness/expiry, reliability, supporting/contradictory relation, and provenance.

## Independence
Confluence is not raw vote counting. Correlated indicators, shared model outputs, shared prompts, or identical data sources must not be counted as independent confirmations.

## Statistical separation
Keep separate fields for AI confidence, evidence strength, evidence score, historical conditional win rate, expectancy, risk score, and calibrated probability.
