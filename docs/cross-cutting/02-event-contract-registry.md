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
| `schema_version` | Version of this event envelope + payload schema contract. |
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
| `payload_contract_version` | Version/revision tag for the canonical payload contract schema. |
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
| Market/Data ingestion | MarketDataReceived, MarketSnapshotCreated, DataQualityChanged, DataStale | Data services | Analysis, Safety, UX |
| Regime | MarketRegimeChanged | Regime Engine | Strategy, Validation, Risk, Learning |
| Agent/Analysis | AnalysisCompleted, ConflictDetected, AdversarialConcernRaised, AgentResultPublished | Analysis/Meta/Orchestrator | Strategy, Audit, UX, Learning |
| Signal/NO_TRADE | SignalCandidateCreated, SignalQualified, SignalRejected, SignalExpired, NoTradeDecided | Signal Engine | Validation, Risk, UX, Learning |
| Validation | ValidationStarted, ValidationPassed, ValidationFailed, ValidationExpired | Quant Validation | Risk, Governance, UX |
| Risk | RiskProposalCreated, RiskRejected, RiskRevalidated, RiskLimitBreached, RiskDecisionRecorded | Risk | Approval, Safety, UX, Audit |
| Approval | ApprovalRequested, ApprovalModified, ApprovalGranted, ApprovalRejected, ApprovalExpired, ApprovalInvalidated | Approval Gateway | Execution, Audit, UX |
| Execution | ExecutionIntentCreated, OrderSubmissionStarted, OrderAccepted, OrderRejected, PartialFill, FillReceived, OrderCancelled, ExecutionUnknown | Execution | Reconciliation, Monitoring, Safety |
| Reconciliation | ReconciliationStarted, ReconciliationDriftDetected, ReconciliationResolved, ReconciliationBlocked | Reconciliation | Execution, Portfolio, Risk, Safety, Audit |
| Position/Trade/Outcome | PositionOpened, PositionUpdated, PositionClosed, TradeOpened, TradeClosed, TradeOutcomeRecorded | Portfolio/Execution/Trade Lifecycle | Risk, UX, Learning, Governance |
| Safety/Security/Recovery | TradingBlocked, KillSwitchActivated, CircuitBreakerOpened, SafetyStateChanged, SecurityIncidentRaised, PermissionDenied, PromptInjectionDetected, FailureDetected, RecoveryActionStarted, RecoveryActionCompleted | Safety/Security/Recovery control planes | All critical services, Audit, Ops |
| Learning | ExperienceRecorded, InsightCreated, HypothesisCreated, ExperimentCompleted | Learning/Research | Governance, Validation |
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
