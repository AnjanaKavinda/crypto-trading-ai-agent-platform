# Event Contract Registry

This registry governs event integration semantics, ownership, and safety behavior
across bounded domains. It does not redefine the canonical cross-domain contract
meanings in [`01-domain-contract-registry.md`](./01-domain-contract-registry.md).

## Canonical event envelope

Event-driven integration must use versioned structured events. Every event
envelope must carry, at minimum:

| Field | Requirement |
|---|---|
| `event_id` | Globally unique immutable event identity; reused unchanged during replay. |
| `event_type` | Canonical event name/family classification; identifies semantic intent. |
| `schema_version` | Version of the event-envelope schema (metadata contract), independent of payload schema version. |
| `occurred_at` | Business occurrence timestamp in producer context. |
| `recorded_at` | Timestamp when producer durably recorded/published the event. |
| `correlation_id` | End-to-end trace correlation identifier. |
| `causation_id` | Parent trigger identity (command/event/request) for provenance. |
| `producer` | Authoritative producer identity (service/domain role). |
| `producer_version` | Producer implementation/model/prompt/build version that emitted the event. |
| `environment` | Runtime environment (`dev`/`test`/`staging`/`prod`). |
| `mode` | Operating mode (`research`/`backtest`/`paper`/`shadow`/`testnet`/`live-supervised`). |
| `aggregate_ref` | Aggregate/entity reference (`contract_id`, entity key, and version where applicable). |
| `payload_contract_id` | Canonical contract ID (`C-###`) represented by payload when applicable. |
| `payload_contract_version` | Version/revision tag for the canonical payload contract schema, distinct from envelope `schema_version`. |
| `audit_ref` | Link to immutable audit trail (`C-060 AuditEvent` or equivalent audit handle). |
| `data_classification` | Classification label (public/internal/restricted/confidential). |
| `idempotency_key` | Deterministic deduplication key for at-least-once-safe processing. |

## Event vs command semantics and producer authority

- Commands request an action from a specific owner and may be rejected.
- Events report that something already occurred and are immutable decision facts.
- Each event family has one authoritative producer owner; downstream consumers must
  not republish the same semantic fact under a competing meaning.
- Consumers may project/read-model events, but projections cannot override the
  source producer’s canonical record or change shared contract meaning.

## Delivery, ordering, and fail-closed behavior

- Delivery contract is at-least-once; consumers must be idempotent by
  `event_id` and/or `idempotency_key`.
- Duplicate events must not create duplicate financial actions (orders, fills,
  approvals, or risk decisions).
- Ordering is guaranteed only within an explicit ordering scope/key
  (for example `aggregate_ref`); global ordering must never be assumed.
- Retries must be bounded by policy-defined limits; exhausted retries route to
  dead-letter/quarantine with audit evidence.
- Invalid, unknown, or incompatible schema versions must fail closed:
  reject/quarantine + audit + safety escalation where impact is critical.
- Unknown safety state, uncertain approval state, or unreconciled execution state
  must result in no new execution action until resolved.

## Durable publication, outbox-equivalent, and replay

- Producers must durably persist publication intent before broker delivery
  (outbox-equivalent or transactional durability pattern).
- Recovery/retry flows must preserve original `event_id`, timestamps, and
  provenance rather than emitting semantic duplicates.
- Replay is allowed for reconstruction/backfill/audit, but replay must not
  authorize or duplicate financial side effects.
- Execution, approval, risk, and reconciliation consumers must bind replay to
  deterministic idempotency checks and authoritative state validation.

## Compatibility, versioning, and source-of-record boundary

- Event schemas evolve with explicit versioning; breaking changes require impact
  analysis, compatibility strategy, migration plan, and governed approval.
- Consumers must declare supported schema versions and fail closed for unknown
  versions in safety-critical paths.
- Backward-compatible additive evolution is preferred.
- Events transport facts; they do not replace authoritative system-of-record
  entities (`Order`, `Position`, `Trade`, `ApprovalDecision`, `RiskProposal`,
  `SafetyDecision`, reconciliation records, or audit records).

## Event-family registry coverage

| Event family | Representative events | Authoritative producer | Primary consumers |
|---|---|---|---|
| Market ingestion | MarketDataReceived, MarketSnapshotCreated | Data | Analysis, Safety, UX |
| Data quality | DataQualityChanged, DataStale | Data Quality | Analysis, Safety, UX |
| Regime | MarketRegimeChanged | Regime Engine | Strategy, Validation, Risk, Learning |
| Analysis | AnalysisCompleted | Analysis | Strategy, Audit, UX, Learning |
| Meta analysis | ConflictDetected | Meta Analysis | Strategy, Safety, Audit, UX |
| Critic analysis | AdversarialConcernRaised | Critic | Strategy, Meta Analysis, Audit, UX |
| Agent runtime | AgentResultPublished | Agent Runtime | Orchestrator, Handoff, Audit |
| Signal/NO_TRADE | SignalCandidateCreated, SignalQualified, SignalRejected, SignalExpired, NoTradeDecided | Signal Engine | Validation, Risk, UX, Learning |
| Validation | ValidationStarted, ValidationPassed, ValidationFailed, ValidationExpired | Quant Validation | Risk, Governance, UX |
| Risk | RiskProposalCreated, RiskRejected, RiskRevalidated, RiskLimitBreached, RiskDecisionRecorded | Risk | Approval, Safety, UX, Audit |
| Approval request lifecycle | ApprovalRequested, ApprovalModified | Approval Gateway | Human/UX, Audit |
| Approval decision lifecycle | ApprovalGranted, ApprovalRejected, ApprovalExpired, ApprovalInvalidated | Human Gateway | Execution, Audit, UX |
| Execution | ExecutionIntentCreated, OrderSubmissionStarted, OrderAccepted, OrderRejected, PartialFill, FillReceived, OrderCancelled, ExecutionUnknown | Execution | Reconciliation, Monitoring, Safety |
| Reconciliation | ReconciliationStarted, ReconciliationDriftDetected, ReconciliationResolved, ReconciliationBlocked | Reconciliation | Execution, Portfolio, Risk, Safety, Audit |
| Position lifecycle | PositionOpened, PositionUpdated, PositionClosed | Portfolio | Risk, UX, Learning |
| Trade/Outcome lifecycle | TradeOpened, TradeClosed, TradeOutcomeRecorded | Trade Lifecycle | Learning, Governance, Audit, UX |
| Safety control | TradingBlocked, KillSwitchActivated, CircuitBreakerOpened, SafetyStateChanged | Safety Control Plane | All critical services, Audit, Ops |
| Security | SecurityIncidentRaised, PermissionDenied, PromptInjectionDetected | Security | Safety, Audit, Ops, Governance |
| Runtime failure | FailureDetected | Runtime Services | Safety, Recovery, Audit, Ops |
| Recovery actions | RecoveryActionStarted, RecoveryActionCompleted | Recovery Control Plane | Runtime Services, Safety, Audit, Ops |
| Learning records | ExperienceRecorded, InsightCreated | Learning | Governance, Validation |
| Research experimentation | HypothesisCreated, ExperimentCompleted | Research | Governance, Validation, Learning |
| Governance | ChallengerApprovedForShadow, CandidateApprovedForPaper, ProductionPromotionApproved, RollbackRequested | Governance | Deployment, Registry, Audit |

## Security, audit, and critical failure requirements

- Every material event must be traceable to immutable audit evidence and
  producer identity/version.
- Event payloads must follow least-privilege disclosure and data-classification
  policy; sensitive fields require controlled access and redaction in non-needful
  consumers.
- Security and safety events (`C-086`, `C-087`, `C-088`, `C-089`, `C-099`) cannot
  be silently suppressed, downgraded, or dropped.
- Critical publication or consumption failures must create explicit failure events
  and route through governed recovery, not blind retry loops.
- No approval = no live execution; event presence alone never authorizes trading.
