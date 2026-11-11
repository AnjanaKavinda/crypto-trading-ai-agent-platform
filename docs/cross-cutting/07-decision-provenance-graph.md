# Decision Provenance Graph

A production trade must be traceable backward:

`Trade → Orders/Fills → ExecutionIntent → ApprovalDecision → RiskProposal → ValidationResult → Signal → StrategyVersion → EvidenceGraph → AnalysisSnapshot → MarketSnapshot → Source Data`

And forward:

`TradeOutcome → Experience → Evaluation → LearningObservation → Hypothesis → Experiment → ExperimentResult → GovernanceDecision → New Version`

Model, prompt, dataset, strategy, risk-model, policy and configuration versions must be linked where relevant.


## ADR-0022 — Recorded Spot OOS observation closure

C-071v2 binds a frozen partition/selection/cost/metrics protocol and the trusted
process-local journal snapshot to each exact C-027v3 run and separate #94 metrics
report. Each embedded run retains its native C-092 dataset identity/version and
canonical dataset/reconstruction-manifest digests. TRAIN/VALIDATION bindings
remain separate from held-out metrics. Readback requires both canonical closure
and the live recorder's issued-result receipt; a caller-supplied hash alone is
not precommitment evidence. Missing complete supplied history is INCONCLUSIVE;
recorded reuse is FAILED. Completeness is a source assumption, not proof of no
off-system research. OBSERVED carries no qualification, risk, promotion or
execution edge. No C-071 durable lineage retention is authorized.

See [ADR-0022](../adr/ADR-0022-spot-oos-protocol-and-result-boundary.md) and
[workflow usage](../architecture/issue-95-spot-oos.md).
