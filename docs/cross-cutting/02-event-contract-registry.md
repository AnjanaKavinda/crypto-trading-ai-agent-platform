# Event Contract Registry

Event-driven integration must use versioned structured events. Every event carries `event_id`, `event_type`, `schema_version`, `occurred_at`, `correlation_id`, `causation_id`, producer identity, payload reference and audit metadata where applicable.

| Event family | Representative events | Producer | Consumers |
|---|---|---|---|
| Market/Data | MarketDataReceived, MarketSnapshotCreated, DataQualityChanged, DataStale | Data services | Analysis, Safety, UX |
| Regime | MarketRegimeChanged | Regime Engine | Strategy, Validation, Risk, Learning |
| Analysis | AnalysisCompleted, ConflictDetected, AdversarialConcernRaised | Analysis/Meta | Strategy, Audit, UX |
| Signal | SignalCandidateCreated, SignalQualified, SignalRejected, SignalExpired, NoTradeDecided | Signal Engine | Validation, Risk, UX, Learning |
| Validation | ValidationStarted, ValidationPassed, ValidationFailed, ValidationExpired | Quant | Risk, Governance, UX |
| Risk | RiskProposalCreated, RiskRejected, RiskRevalidated, RiskLimitBreached | Risk | Approval, Safety, UX |
| Approval | ApprovalRequested, ApprovalModified, ApprovalGranted, ApprovalRejected, ApprovalExpired, ApprovalInvalidated | Approval Gateway | Execution, Audit, UX |
| Execution | ExecutionIntentCreated, OrderSubmissionStarted, OrderAccepted, OrderRejected, PartialFill, FillReceived, OrderCancelled, ExecutionUnknown | Execution | Reconciliation, Monitoring, Safety |
| Position | PositionOpened, PositionUpdated, PositionClosed | Portfolio/Execution | Risk, UX, Learning |
| Safety | TradingBlocked, KillSwitchActivated, CircuitBreakerOpened, SafetyStateChanged | Safety | All critical services |
| Security | SecurityIncidentRaised, PermissionDenied, PromptInjectionDetected | Security | Safety, Audit, Ops |
| Learning | ExperienceRecorded, InsightCreated, HypothesisCreated, ExperimentCompleted | Learning/Research | Governance |
| Governance | ChallengerApprovedForShadow, CandidateApprovedForPaper, ProductionPromotionApproved, RollbackRequested | Governance | Deployment, Registry, Audit |

## Event rules
- Delivery must be idempotent where retries are possible.
- Consumers must tolerate duplicate delivery without duplicate financial action.
- Execution-critical events require durable persistence and reconciliation.
- An event cannot silently substitute for the authoritative system-of-record entity.
