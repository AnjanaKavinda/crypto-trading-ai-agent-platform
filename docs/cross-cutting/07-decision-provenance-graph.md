# Decision Provenance Graph

A production trade must be traceable backward:

`Trade → Orders/Fills → ExecutionIntent → ApprovalDecision → RiskProposal → ValidationResult → Signal → StrategyVersion → EvidenceGraph → AnalysisSnapshot → MarketSnapshot → Source Data`

And forward:

`TradeOutcome → Experience → Evaluation → LearningObservation → Hypothesis → Experiment → ExperimentResult → GovernanceDecision → New Version`

Model, prompt, dataset, strategy, risk-model, policy and configuration versions must be linked where relevant.


## ADR-0022 — Spot OOS

C-071v2 binds protocol/journal to separate development/holdout C-027v3 runs, #94 reports and native C-092 dataset/manifest pins. Require canonical closure/live issuance/recomputation. Missing history INCONCLUSIVE; reuse FAILED. Completeness covers supplied records only. No qualification/risk/promotion/execution/retention edge. [ADR](../adr/ADR-0022-spot-oos-protocol-and-result-boundary.md).

## ADR-0023 — Spot walk-forward

C-029v2 binds the frozen rolling/anchored plan and every planned fold to its
TRAIN/selection-VALIDATION/TEST bounds, point-in-time cutoffs, selected
parameters, exact C-071v2/C-027v3/#94 evidence, and shared research-journal
receipts. Failed integrity or contamination is FAILED; missing folds or
insufficient frozen coverage is INCONCLUSIVE. Descriptive aggregates preserve
units, method, fold coverage, and UUID tie-breaks. No qualification, profitability,
independence, pooled metric, execution, or retention edge.
[ADR](../adr/ADR-0023-spot-walk-forward-observation-boundary.md).

## ADR-0024 — Spot Monte Carlo

C-072v2 binds one exact observed C-027v3 Spot result, its trace/strategy/
dataset/manifest/cost pins, the exact #94 report/method/policy/input digests,
and the ordered source-return digest. The frozen block-bootstrap policy binds
timeframe, block length, path horizon, seed, PRNG/index mapping, iteration count,
and nearest-rank quantiles. It has only OBSERVED/INCONCLUSIVE/FAILED outcomes;
no qualification, risk, learning, execution, or retention edge is authorized.
[ADR](../adr/ADR-0024-spot-monte-carlo-observation-boundary.md).
