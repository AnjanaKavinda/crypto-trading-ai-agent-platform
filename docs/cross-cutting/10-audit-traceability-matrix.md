# Audit and Traceability Matrix

| Decision/action | Must record |
|---|---|
| Analysis | inputs, source refs, agent/model/prompt versions, output schema, uncertainty |
| Signal | strategy version, evidence graph, regime, qualification, expiry/invalidation |
| Validation | dataset/version, assumptions, costs, methodology, metrics, status |
| Risk | account/portfolio snapshots, limits, calculations, risk-model version, vetoes |
| Approval | user identity, exact parameters/hash, timestamp, reason, expiry, revalidation |
| Execution | intent, idempotency key, exchange/account, request/response, order IDs, timestamps |
| Reconciliation | internal vs exchange state, discrepancies, resolution |
| Outcome | actual entry/exit/fills/fees/slippage/funding/PnL/MAE/MFE |
| Learning | experience refs, observation, hypothesis, experiment and evidence |
| Governance | proposal, reviewers, decision, conditions, effective version, rollback target |
| Safety/Security | policy, state, event, affected components, response/recovery |

Material audit records are append-only/immutable where practical.
