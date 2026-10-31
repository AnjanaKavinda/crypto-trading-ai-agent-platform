# Evidence Graph

Canonical chain:

`Source Data → Data Quality → Feature/Observation → Analytical Finding → EvidenceItem → Strategy Condition → Signal Candidate → Qualification → Validation → Risk → Approval → Execution → Outcome → Experience`

Every edge must be reconstructable through IDs/version references. Evidence nodes must carry source, timestamp, method, freshness/expiry, reliability, supporting/contradictory relation, and provenance.

## C-024 pre-qualification boundary

C-024 schema 1 retains its historical graph and semantics. C-024 schema 2 is
the pre-qualification evidence package: its versioned graph terminates at the
exact C-023 SignalCandidate using `EVIDENCE → FINDING → STRATEGY_CONDITION →
CANDIDATE`. It must not contain or require a future C-025 qualification. The
subsequent qualification binds the exact C-024v2 package and authoritative
Chat 7 C-028v2 result. C-093 dependence state, including `UNKNOWN`, is preserved
without coercion; supporting and contradictory evidence remain distinct.
Package expiry is bounded by the referenced candidate, market-context and
analysis-snapshot expiries and by source-derived graph-node freshness; this
version introduces no TTL.

## Independence
Confluence is not raw vote counting. Correlated indicators, shared model outputs, shared prompts, or identical data sources must not be counted as independent confirmations.

## Statistical separation
Keep separate fields for AI confidence, evidence strength, evidence score, historical conditional win rate, expectancy, risk score, and calibrated probability.
