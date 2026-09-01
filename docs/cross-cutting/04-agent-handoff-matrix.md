# Agent / Service Handoff Matrix

| Producer | Output contract | Consumer | Validation gate | Failure behavior |
|---|---|---|---|---|
| Data | MarketSnapshot + DataQualityReport | Analysis | freshness/schema/quality | NO_TRADE / degraded |
| Analysis | MarketContext | Strategy | schema/evidence/conflict | reject / request analysis |
| Strategy | StrategyEligibility/SignalCandidate | Signal/Validation | version + setup rules | no setup / NO_TRADE |
| Signal | SignalEvidencePackage/Qualification | Quant Validation | completeness/freshness | rejected candidate |
| Quant Validation | ValidationResult | Risk | reproducible status/freshness | NO_TRADE |
| Risk | RiskProposal | Approval Gateway | deterministic limits | reject |
| Approval Gateway | ApprovalDecision | Execution Gateway | auth + exact-parameter binding + expiry | no execution |
| Execution Gateway | ExecutionIntent | Execution Engine | idempotency + readiness + final validation | no execution |
| Execution | Order/Fill | Reconciliation/Portfolio | exchange acknowledgement | reconcile / UNKNOWN |
| Trade Lifecycle | TradeOutcome | Learning | actual vs counterfactual distinction | incomplete experience |
| Learning | Hypothesis | Experiment | provenance/falsifiability | reject hypothesis |
| Experiment/Quant | ExperimentResult | Governance | OOS/WF/robustness | no promotion |
| Governance | GovernanceDecision | Version/Deployment | explicit approval | remain shadow/paper |

## Mandatory rule
No downstream component may reinterpret an upstream contract in order to bypass the upstream authority boundary.
