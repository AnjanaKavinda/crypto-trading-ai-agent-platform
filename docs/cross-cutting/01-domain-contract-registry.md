# Domain Contract Registry

Registry approval defines cross-domain semantics and ownership only. It does not approve implementation schemas, technology providers, or runtime integrations.

## Classification policy

Only genuine cross-domain contracts receive `C-###`.

| Class | `C-###` eligible | Rule |
|---|---|---|
| Cross-domain contract | Yes | Shared semantic interface crossing bounded domains, with one authoritative producer, primary consumers, and a safety-relevant invariant. |
| Embedded/value object | No | Structured field inside a canonical contract; semantics scoped by parent contract. |
| Enum / state vocabulary | No | Allowed states, lifecycle values, or policy enums used by contracts. |
| Internal service record | No | Service-local implementation record, report, or adapter detail; may be surfaced via read models but not as canonical cross-domain meaning. |
| UI / read-model DTO | No | Frontend/view projection; cannot redefine domain semantics. |
| Architecture/development-governance artifact | No | Repository/process/governance artifact (ADR, CI, release, roadmap, traceability). |

## Canonical cross-domain contracts

IDs `C-001`–`C-060` are preserved unchanged. New IDs are appended sequentially.

| ID | Contract | Owner/Producer | Primary Consumers | Core invariant |
|---|---|---|---|---|
| C-001 | MarketData | Data | Analysis, Research | Normalized market observations; not analysis. |
| C-002 | MarketSnapshot | Data | Analysis, Strategy, Learning | Point-in-time market state with source references. |
| C-003 | DataQualityReport | Data Quality | All downstream domains | Versioned quality assessment; v1 preserves scalar scores, while v2 makes per-dimension availability, measurement basis, policy, and evidence explicit. |
| C-004 | FeatureSet | Feature/Quant | Analysis, Validation | Versioned deterministic derived features. |
| C-005 | MarketRegime | Regime Engine | Analysis, Strategy, Validation, Risk, UX, Learning | Contextual regime classification with evidence and validity window. |
| C-006 | MarketContext | Analysis | Strategy | Chat 5 analytical synthesis; cannot authorize trades. |
| C-007 | AnalysisSnapshot | Analysis | Strategy, Audit, Learning | Immutable/versioned analytical output snapshot. |
| C-008 | EvidenceItem | Analysis/Data | Strategy, Validation, UX, Audit | Traceable evidence with source, time, method, reliability and expiry. |
| C-009 | ConfluenceAssessment | Meta Analysis | Strategy | Evidence-backed categorical support/neutral/contradiction with explicit dependence; never raw vote counting. |
| C-010 | ConflictAssessment | Meta Analysis | Strategy, Safety | Conflicting evidence and severity. |
| C-011 | FundamentalAssessment | Fundamental | MarketContext | Crypto-native fundamental evidence. |
| C-012 | TechnicalAssessment | Technical | MarketContext | Deterministic/structured technical findings. |
| C-013 | SMCAssessment | SMC | MarketContext | Structured SMC observations and invalidation. |
| C-014 | WyckoffAssessment | Wyckoff | MarketContext | Structured phase/event interpretation. |
| C-015 | DerivativesAssessment | Derivatives | MarketContext | Funding, OI, liquidation, basis and positioning evidence. |
| C-016 | OnChainAssessment | On-chain | MarketContext | Blockchain-native activity/flow evidence. |
| C-017 | SentimentAssessment | Sentiment | MarketContext | Sentiment/narrative evidence with provenance. |
| C-018 | EventRiskAssessment | Event Risk | Strategy, Risk, Safety, UX | Known event risks and timing windows. |
| C-019 | AdversarialAssessment | Critic | Strategy, Meta Analysis | Counter-thesis, failure conditions and contradictory evidence. |
| C-020 | Strategy | Strategy | Strategy Engine, Research | Immutable strategy identity and rules family. |
| C-021 | StrategyVersion | Strategy Governance | Validation, Signal, Learning | Schema 1 remains frozen; schema 2 adds typed same-version condition/group invalidation rules. Versioned rules/parameters/eligibility with lifecycle status. |
| C-022 | StrategyEligibility | Strategy | Signal | Eligibility by asset/timeframe/regime/data state. |
| C-023 | SignalCandidate | Signal | Qualification | Candidate setup; never an order. |
| C-024 | SignalEvidencePackage | Signal | Validation, Risk, Approval, UX | v1 retained; v2 is pre-qualification evidence ending at the exact C-023 candidate. |
| C-025 | SignalQualification | Signal/Validation | Risk, UX | v1 retained; v2 requires exact C-024v2 and authoritative C-028v2; historical conditional qualification, not probability. |
| C-026 | NoTradeDecision | Signal | UX, Risk, Safety, Learning | Schema 1 reason vocabulary is frozen; schema 2 adds only typed `INVALID_PROVENANCE` while preserving first-class abstention semantics. |
| C-027 | BacktestResult | Quant Validation | Validation, Research | v1 retained; v2 cost-assumption value objects express APPLICABLE / NOT_APPLICABLE / UNKNOWN explicitly; ADR-0019 v3 binds exact dataset/manifest, typed costs and simulation provenance. |
| C-028 | ValidationResult | Quant Validation | Risk, Approval | v1 retained; v2 binds qualification rule configuration, observed results, statistical-support gates, and validation outcome. |
| C-029 | WalkForwardResult | Quant Validation | Validation, Learning | V1 remains unchanged. ADR-0023 adds observation-only Spot schema 2 binding planned folds, exact C-071v2/C-027v3/#94 evidence, journal receipts, explicit unavailable states, and descriptive aggregates; no qualification or retention authority. |
| C-030 | RobustnessResult | Quant Validation | Risk, Governance | Sensitivity/Monte Carlo/regime robustness summary. |
| C-031 | CalibrationResult | Quant/Model Evaluation | Meta Analysis, Learning | Calibration separate from AI confidence. |
| C-032 | AccountSnapshot | Risk | Risk, Approval, Execution | Point-in-time account state. |
| C-033 | PortfolioSnapshot | Risk | Risk, Approval | Point-in-time portfolio exposures/correlations. |
| C-034 | RiskProposal | Risk | Approval | Deterministic entry/SL/TP/size/leverage/risk decision. |
| C-035 | RiskAssessment | Risk | Approval, Audit | Detailed deterministic risk checks and vetoes. |
| C-036 | PositionSizingResult | Risk | RiskProposal | Deterministic sizing result. |
| C-037 | ApprovalRequest | Approval Gateway | Human/UX | Exact configuration presented for decision. |
| C-038 | ApprovalDecision | Human Gateway | Execution | Authenticated decision bound to exact configuration. |
| C-039 | ExecutionIntent | Execution Gateway | Execution Engine | Approved, risk-valid, idempotent intent. |
| C-040 | Order | Execution | Exchange, Monitoring, Audit | Order state and exchange identifiers. |
| C-041 | Fill | Execution/Exchange | Position, Reconciliation | Fill execution fact. |
| C-042 | Position | Portfolio/Execution | Monitoring, Risk, UX | Authoritative position state. |
| C-043 | Trade | Trade Lifecycle | Learning, Audit | Lifecycle aggregate of approved execution. |
| C-044 | TradeOutcome | Trade Lifecycle | Learning, Performance | Actual outcome distinct from counterfactuals. |
| C-045 | Experience | Learning | Evaluation, Memory | Immutable decision lifecycle reference. |
| C-046 | LearningObservation | Learning | Insight | Observed pattern with support and scope. |
| C-047 | LearningInsight | Learning | Hypothesis | Evidence-bounded insight; not production authority. |
| C-048 | Hypothesis | Research/Learning | Experiment | Falsifiable proposed improvement. |
| C-049 | Experiment | Research | Quant Validation | Versioned controlled test. |
| C-050 | ExperimentResult | Quant/Learning | Governance | Validated/inconclusive/degraded comparison. |
| C-051 | StrategyChangeProposal | Learning/Governance | Governance | Proposal only; cannot directly mutate production. |
| C-052 | AgentPerformance | Evaluation | Orchestrator, Governance, UX | Contextual reliability/calibration/drift. |
| C-053 | StrategyPerformance | Evaluation | Governance, UX | Performance by version/regime/asset/timeframe. |
| C-054 | SystemAwarenessSnapshot | Awareness | Orchestrator, UX, Safety | Data/agent/strategy/risk/execution/unknown state. |
| C-055 | DriftAssessment | Evaluation | Governance, Safety | Data/model/prompt/strategy/calibration drift. |
| C-056 | KnowledgeArtifact | Knowledge Governance | Retrieval, Research | State-labelled knowledge with provenance. |
| C-057 | GovernanceDecision | Governance | Deployment, Registry | Approved/rejected/shadow/paper/rollback decision. |
| C-058 | SafetyDecision | Safety Control Plane | All control/execution paths | Fail-closed safety policy decision. |
| C-059 | TradingReadinessState | Safety | Approval, Execution, UX | READY/DEGRADED/BLOCKED/EMERGENCY/UNKNOWN. |
| C-060 | AuditEvent | Audit | Audit Store, Security | Immutable material action/decision event. |
| C-061 | AgentDefinition | Agent Governance | Orchestrator, Evaluation, Safety | Declares bounded role, allowed inputs/outputs, and non-escalatable authority. |
| C-062 | AgentResult | Agent Runtime | Orchestrator, Handoff, Audit | Structured, attributable, time-bounded output for a specific task context. |
| C-063 | AgentPermissionProfile | Security Governance | Orchestrator, Safety, Approval | Machine-enforceable least-privilege runtime grant bound to role/mode and constrained by `AgentPermissionPolicy`. |
| C-064 | AgentToolAccess | Orchestrator Security | Runtime Agent Shell, Audit | Tool grant is explicit, scoped, revocable, and never implies execution authority. |
| C-065 | AgentHandoff | Orchestrator | Downstream Agents, Audit, Learning | Handoff preserves provenance, unresolved risks, and bounded responsibilities. |
| C-066 | AgentEvaluation | Evaluation | Governance, Learning, Orchestrator | Evaluation is evidence-based and cannot directly modify production execution/risk behavior. Schema 1 is one evaluation per C-062 result; see the Version Registry for the bounded PERSONAL_SPOT_RESEARCH implementation. |
| C-067 | ModelRoutingDecision | Model Governance | Runtime Agent Router, Audit, Safety | Model/provider choice must be explicit, attributable, and policy-compliant. |
| C-068 | FibonacciAssessment | Technical Analysis | MarketContext, Strategy | Fibonacci findings are reproducible from deterministic inputs and include invalidation context. |
| C-069 | AnalyticalUncertainty | Analysis | Strategy, UX, Safety | Uncertainty must be explicit and cannot be converted into trade authority. |
| C-070 | Signal | Signal Engine | Risk, Approval, UX | Schema 1 remains frozen; schema 2 binds exact candidate/strategy/evidence/qualification/validation lineage. Qualified signal only; never executable authority and never a substitute for `ExecutionIntent`. |
| C-071 | OOSResult | Quant Validation | ValidationResult, Governance, Risk | Out-of-sample evidence is explicitly partitioned from in-sample optimization. ADR-0022 adds observation-only schema 2 for exact Spot C-027v3/dataset/metrics/protocol/journal closure and zero/inconclusive samples; v1 unchanged. No schema-2 qualification or retained storage approval. |
| C-072 | MonteCarloResult | Quant Validation | RobustnessResult, Risk, Governance | V1 remains unchanged. ADR-0024 adds observation-only Spot schema 2 binding exact C-027v3/#94 provenance and deterministic block-bootstrap assumptions, units, seed, source-return digest, and terminal state; no C-030/qualification integration or retention. |
| C-073 | SensitivityResult | Quant Validation | RobustnessResult, Risk | V1 remains unchanged. ADR-0025 adds observation-only Spot schema 2 bound to exact C-027v3/#94 scenarios, policy, parameter/cost assumptions, metrics, and provenance; no qualification integration or retention. |
| C-074 | RegimeValidationResult | Quant Validation | ValidationResult, Strategy, Risk | V1 regime-scope semantics remain unchanged. ADR-0026 adds observation-only Spot schema 2 binding exact C-027v3/#94 runs to decision-time C-005 contexts and explicit asset/timeframe coverage; no C-030/C-028 qualification or retention authority. |
| C-075 | PositionSnapshot | Portfolio | Risk, Reconciliation, UX | Point-in-time position truth is attributable and reconcilable to fills/orders. |
| C-076 | LeverageAssessment | Risk | RiskProposal, Approval | Schema 1 remains unchanged. Offline leverage/margin assessment is deterministic, fail-closed on unknown evidence, and never grants overall risk acceptance, approval, or execution authority. |
| C-077 | LiquidationAssessment | Risk | RiskProposal, Approval, Safety | Schema 1 and its constructor/consumers remain unchanged. Issue #110 adds a pure offline assessment of caller-supplied, versioned LINEAR liquidation-price evidence; it never calculates or authenticates an exchange liquidation price. |
| C-078 | StopLossAssessment | Risk | RiskProposal, Approval | Stop-loss validity must align with strategy logic and maximum-loss policy bounds. |
| C-079 | TakeProfitAssessment | Risk | RiskProposal, Approval | Take-profit targets must preserve risk-reward and invalidation consistency. |
| C-080 | PortfolioImpact | Risk Engine | Approval, Safety, UX | New proposal impact must not violate portfolio-wide exposure constraints. |
| C-081 | StressTestResult | Risk Engine | Risk, Governance, Safety | Stress scenarios and resulting breaches must be explicit and auditable. |
| C-082 | RiskDecision | Risk | Approval, Execution, Audit | Deterministic risk verdict is authoritative for risk gating and cannot independently authorize execution outside approved/revalidated `ExecutionIntent` flow. |
| C-083 | RiskRevalidationResult | Risk | Approval, Execution, Safety | Material changes or stale context require revalidation before any execution path. |
| C-084 | OrderRequest | Execution Gateway | Exchange Adapter, Audit | Exchange submission request must derive from approved intent and enforce idempotency binding. |
| C-085 | ExchangeOrder | Exchange Adapter | Execution, Reconciliation, Monitoring | Exchange-specific order state must reconcile back to canonical `Order` without semantic drift. |
| C-086 | SecurityEvent | Security | Safety, Audit, Governance | Security-critical event triggers governed response paths; no silent suppression. |
| C-087 | FailureEvent | Runtime Services | Safety, Recovery, Audit | Critical failure events are explicit, attributable, and policy-routable. |
| C-088 | RecoveryAction | Recovery Control Plane | Runtime Services, Audit, Governance | Recovery actions are policy-bounded, idempotent where required, and never bypass safety gates. |
| C-089 | PromptInjectionAssessment | Security | Safety, Agent Governance, Audit | Prompt-injection risk is explicit and must gate unsafe tool/authority escalation. |
| C-090 | CounterfactualAnalysis | Evaluation | Governance, Strategy Evaluation | Counterfactual outcomes remain distinct from factual trade outcomes and audit history. |
| C-091 | DataSourceRecord | Data | Analysis, Validation, Audit | Immutable source/provider/time/licensing/provenance identity for ingested data. |
| C-092 | DatasetVersion | Data Governance | Validation, Research, Audit | Exact reproducible dataset composition and lineage; never silently mutated. |
| C-093 | AgentIndependenceReport | Evaluation | Meta Analysis, Governance, Audit | Records exact evidence/source/binding/method overlap; unknown remains unknown and no statistical independence or correlation is inferred. |
| C-094 | BiasCheckReport | Quant Validation | Validation, Governance, Audit | Schema 1 remains unchanged. ADR-0027 adds observation-only Spot schema 2 binding exact archive-backed C-027v3 replay/request/trace, C-021, and C-092/C-101/C-102/C-103/C-091 provenance. Only point-in-time/look-ahead checks can be supported by verified replay; seven other categories remain explicitly inconclusive. No qualification or retention authority. |
| C-095 | ExecutionReport | Execution | Reconciliation, Monitoring, Audit, Safety | Attributable execution outcome including partial/unknown/failure states; never treated as reconciled by assumption. |
| C-096 | ReconciliationReport | Reconciliation | Portfolio, Risk, Safety, Audit | Internal-versus-exchange deltas remain explicit and block conflicting action while unresolved. |
| C-097 | SafetyPolicy | Safety Governance | Safety Control Plane, Approval, Execution, Audit | Versioned fail-closed policy authority that control decisions must enforce. |
| C-098 | AgentPermissionPolicy | Security Governance | Orchestrator, Safety, Audit | Versioned least-privilege authority ceiling that runtime profiles cannot exceed. |
| C-099 | SafetyIncidentReport | Security | Safety, Operations, Governance, Audit | Immutable incident scope/evidence/response status with no silent suppression. |
| C-100 | ChampionChallengerRecord | Evaluation | Validation, Governance, Registry, Audit | Versioned champion/challenger comparison record; cannot authorize automatic production promotion. |
| C-101 | HistoricalUniverse | Data | Research, Validation | Complete, source-bound, versioned membership with separate effective and knowledge intervals; retain delisted instruments historically. |
| C-102 | ObservationRevision | Data | Research, Validation | Immutable observation identity and explicit supersession ancestry; later availability cannot leak into earlier cutoffs. |
| C-103 | ReconstructionManifest | Data | Research, Validation, Audit | Pins universe, selected revisions, ancestry/source hashes, dataset version and deterministic selection policy. |
| C-104 | OrderFlowAssessment | Analysis | MarketContext, Strategy, Audit, Learning | Per-metric order-flow availability and evidence are bound to exact modality inputs; assessment cannot authorize trades. |
| C-105 | MultipleTestingAssessment | Quant Validation | Research, Audit | Schema 1 records only exact supplied C-071v2 protocol/journal attempts with unadjusted descriptive status; no correction, holdout selection, qualification, learning, or retention authority. |
| C-106 | ValidationFreshnessAssessmentV1 | Quant Validation | Research, Governance, Audit | Schema 1 observes freshness for the exact supplied C-028v2/C-024v2 pair and explicit typed current snapshot; it preserves validation outcome and grants no qualification, approval, activation, readiness, or retention authority. |

Issue #45 additive extension: owner approval on 2026-09-28. C-101–C-103 start
at schema `1`; C-001–C-100 retain their existing layouts and IDs.
`HistoricalEvidencePin` is an embedded value object. `HistoricalReconstruction`
is an internal result, not an additional canonical contract. Universe/source
completeness must originate in trusted ingestion; these contracts cannot prove
external provider truth or that a caller omitted no history. C-101 is pinned
explicitly, never selected from today's watchlist. C-102 keys include provider,
venue, instrument, kind, stable observation key and event time. The only initial
ordering policy is `explicit-supersedes-v1`; no guessed numeric/lexical ordering.

## C-003 schema evolution

C-003 schema `1` remains the existing `DataQualityReport` contract without
payload or identity changes. Schema `2` is a separate representation with one
typed result for each quality dimension, explicit measured/not-applicable/
unavailable state, versioned assessment policy, and auditable measurement or
evidence basis. Both use `wire-1`; the C-003 schema version selects the model.
Schema `2` has lineage identity version `2`, while historical schema `1`
records retain identity version `1` and their original digests.

Schema `2` was initially decode/read compatibility only. No general producer
or analysis consumer is enabled by that compatibility boundary. A producer
must resolve and validate the exact assessment-policy definition before
producing a v2 report; unknown policy versions fail closed.

Issue #375 adds the approved single-source Spot OHLCV C-003 schema-2 assessment
as an in-memory report for the C-005 Spot regime path. It reuses the existing
`personal-binance-spot-ohlcv-v1` thresholds and v1 deterministic score
calculation, resolves timeframe/window/cutoff through the C-003 v2 policy
registry, and binds every measured dimension to the canonical C-002 snapshot
digest. C-003 schema-1 storage and response projection remain unchanged; v2
general lineage writes and persistence remain disabled. The C-005 regime
evidence identifies the actual C-003 schema-2 report and policy. The policy
does not assert independent-source comparison or provider truth. The later
owner-approved ADR-0012 exception permits only the exact C-003 v2 closure for
the personal local Spot analysis lineage path; see its issue-specific entry in
the version registry. This does not enable other C-003 v2 producers or writers.

## Issue #341 — versioned order-flow analysis contracts

The repository owner approved Option 2 in merged PR #340 for issue #338. C-104
is allocated additively as the next sequential ID, with schema `1`;
C-006/C-007/C-008 schema `1` identities and bytes remain unchanged. Their
schema-2 forms use the existing `canonical-json-v1` / `wire-1` encoding and
explicit schema dispatch. C-007 schema 2 is the immutable modality input
manifest; C-008 schema 2 binds evidence to the manifest bindings actually used;
C-006 schema 2 references that manifest and typed assessments without copying
its binding list. C-003 v2 remains in-memory only: this allocation does not
enable report writes, persistence, or a producer.

C-104 `OrderFlowAssessment` is analysis-only. Its schema-1 metric vocabulary
separately represents best bid/ask, midpoint, absolute spread, spread bps,
bid/ask depth and notional, book imbalance, trade-record count, buy/sell
aggressor volume, volume delta, and cumulative delta. Each component has an
explicit `AVAILABLE`, `PARTIAL`, or `UNAVAILABLE` state, a typed value and unit,
and binds to exactly one modality: book components to one point-book binding,
trade components to one exact trade-window binding. Trade-record count is a
non-negative integer with unit `trades`; spread bps uses unit `bps`; book
imbalance uses `ratio`. Price and notional components use the assessment's
explicit quote unit; depth and trade-volume/delta components use its explicit
base unit. Validation requires those base/quote units to match the exact
resolved C-003 modality policy. The assessment grants no signal, risk, approval,
or execution authority.

## Issue #101 — C-105 multiple-testing observation

C-105 schema 1 is an observation-only PERSONAL_SPOT_RESEARCH record over one
exact supplied `OOSResearchJournal`/`OOSProtocolV2` chain and its issued
C-071v2 result. Its plan is frozen before protocol-scoped access or trials. It
preserves exact protocol events and existing C-027v3/#94 evidence references
without applying a correction or ranking/selecting holdout outcomes. The
correction state is `NOT_APPLIED` and the interpretation is
`UNADJUSTED_DESCRIPTIVE_ONLY`. It neither proves global history completeness nor
grants qualification, learning, retention, risk, approval, or execution
authority. See [ADR-0028](../adr/ADR-0028-spot-multiple-testing-observation-boundary.md).

## Issue #102 — C-106 validation freshness observation

C-106 schema 1 is an on-demand, immutable PERSONAL_SPOT_RESEARCH assessment of
one exact supplied C-028v2 result and its exact C-024v2 evidence package against
an explicit typed current snapshot and timezone-aware `as_of`. It compares
artifact identity, schema, and content digest; missing/uncomparable current
evidence is `INCONCLUSIVE`, explicit changes are `STALE`, and declared expiry is
`EXPIRED` at the boundary. The original C-028 outcome and gate evidence remain
unchanged. A missing original code-build identity is inconclusive; no method or
runtime identity substitutes for it. C-106 never resolves latest/global state,
calculates rolling decay metrics, changes qualification, or grants production
eligibility, approval, activation, readiness, or retention. See
[ADR-0029](../adr/ADR-0029-validation-freshness-assessment-boundary.md).

## Issue #370 — Additive analysis contract schemas

C-009 and C-010 schema 1 retain their existing numeric fields and exact
serialization. Their schema-2 forms use independent categorical vocabularies:
C-009 evidence strength is `VERY_STRONG`, `STRONG`, `MODERATE`, `WEAK`, or
`UNKNOWN`, while evidence dependence is a required separate field; C-010
severity is `LOW`, `MODERATE`, `HIGH`, `CRITICAL`, or `UNKNOWN`. No conversion
between schema-1 numbers and schema-2 categories is defined.

C-006 schema 3 carries only the C-009/C-010 schema-2 forms and binds to a
C-007 schema-3 manifest. C-007 schema 3 adds canonical output references that
bind C-009/C-010/C-093 contract IDs, identities, schema/lineage versions, and
content digests. The schema-3 implementation adds no producer or calculation
authority. C-093's report implementation remains owned by issue #67.

Issue #374 adds an additive Spot OHLCV path: C-007 schema 4 explicitly binds
`spot-ohlcv` inputs and their exact C-002/C-003/C-001/C-091 records, timeframe,
window, C-005 schema-1/lineage-1 regime, and C-008 schema-2/lineage-2 evidence.
The existing C-008 schema-2 fields are reused only through the C-007 v4
binding-aware validator; no C-008 wire field or historical payload is changed.
C-009/C-010 schema 3 retain the #370 categorical states and bind to C-007
schema 4. C-006 schema 4 contains those new output types and an exact C-007 v4
reference. C-093 remains owned by #67; its exact schema/lineage, method, and
digest must resolve through that owner's registry before validation. This
path grants no calculation, qualification, risk, approval, or execution
authority.

Issue #67 registers the first C-093 owner version as schema/lineage `1/1`
through `C093Registry`. The canonical immutable report binds the exact C-002
snapshot, C-007 v4 manifest ID/schema, C-005 regime, C-003 quality report,
canonical C-007 Spot binding digest, C-008 evidence, participant methods, and
analysis window. The report deliberately does not include the final C-007
manifest digest because that manifest commits to this report's output
reference. Pairwise
factors record observed shared evidence, sources, bindings, windows, methods,
agents, models, and prompts. Shared inputs are marked `PARTIALLY_DEPENDENT`;
absence of observed overlap is `UNKNOWN`. The report never claims statistical
independence or estimates statistical correlation. C-093 references resolve
only when the complete identity, owner-registered versions/method, and
canonical digest match.

The Spot C-009/C-010 schema-3 calculators consume the resolver-validated C-005
regime and exact READY findings. C-009 combines the regime direction with
typed finding directions and preserves categorical component strengths, but
returns `INDETERMINATE` with aggregate strength `UNKNOWN`: C-007 v4 has one
OHLCV input and cannot establish the meaningfully independent streams that
Chat 5 requires for a valid confluence. Analytical confidence remains
unavailable (`NOT_ASSESSED`). It does not weight or count correlated features.
C-010 emits records only for
opposing directions; unresolved materiality remains `UNKNOWN`, and critical
severity requires an explicitly invalid premise or unsafe-to-rely finding.
Both calculators preserve exact evidence, method, snapshot, quality, and
expiry references and grant no strategy, risk, approval, or execution
authority. This is the bounded Spot analysis slice; full Chat 5 and held
issues #39–#43 remain open/on hold.

## Canonical name / alias / supersession clarifications

| Canonical | Alias / related name | Disposition |
|---|---|---|
| C-045 Experience | ExperienceRecord | Alias for canonical cross-domain meaning in Chat 13 usage. |
| C-070 Signal | SignalCandidate (C-023), SignalQualification (C-025), NoTradeDecision (C-026) | Distinct lifecycle contracts: candidate → qualification/NO_TRADE → qualified signal. C-070v2 binds exact versioned lineage. `Signal` cannot bypass qualification. |
| C-024 SignalEvidencePackage | EvidenceGraph | `EvidenceGraph` is an embedded/value-object structure within the package, not a separate canonical contract. |
| C-063 AgentPermissionProfile | AgentPermissionPolicy (C-098) | `AgentPermissionPolicy` is the canonical versioned authority ceiling; `AgentPermissionProfile` is a runtime grant constrained by that ceiling. Neither grants trade approval or exchange execution authority. |
| C-031 CalibrationResult | CalibrationRecord | Alias in Chat 13 terminology. |

## Chats 2–13 coverage and disposition

Every explicit required name is dispositioned as registered canonical contract, alias, value object, enum/state vocabulary, internal service record, UI/read-model DTO, or governance artifact.

| Chat | Required names | Disposition |
|---|---|---|
| Chat 2 | SystemContext, ArchitectureDecisionRecord, PlaneBoundary, ServiceBoundary, EventBoundary, DeploymentBoundary, IntegrationBoundary, RuntimeMode, EnvironmentBoundary | Governance artifacts except `RuntimeMode` (enum/state vocabulary). |
| Chat 3 | AgentDefinition, AgentResult, AgentPermissionProfile, AgentToolAccess, AgentHandoff, AgentEvaluation, AdversarialAssessment, AgentIndependenceReport, ModelRoutingDecision | Registered: C-061, C-062, C-063, C-064, C-065, C-066, C-019, C-093, C-067. |
| Chat 4 | MarketData, MarketSnapshot, DataQualityReport, DataSourceRecord, DatasetVersion, EventData, FundamentalData, OnChainData, DerivativesData, SentimentData, MacroData, FeatureSet | Registered: C-001, C-002, C-003, C-091, C-092, C-004. Data-type payloads (`EventData`, `FundamentalData`, `OnChainData`, `DerivativesData`, `SentimentData`, `MacroData`) are embedded/value objects. |
| Chat 5 | MarketContext, AnalysisSnapshot, EvidenceItem, TechnicalAssessment, FundamentalAssessment, SMCAssessment, WyckoffAssessment, FibonacciAssessment, DerivativesAssessment, OnChainAssessment, SentimentAssessment, EventRiskAssessment, MarketRegime, ConfluenceAssessment, ConflictAssessment, AdversarialAssessment, AnalyticalUncertainty | Registered: C-006, C-007, C-008, C-012, C-011, C-013, C-014, C-068, C-015, C-016, C-017, C-018, C-005, C-009, C-010, C-019, C-069. |
| Chat 6 | Strategy, StrategyVersion, StrategyEligibility, StrategyCondition, SignalCandidate, Signal, SignalEvidencePackage, EvidenceGraph, SignalQualification, QualificationRuleSet, NoTradeDecision, NoTradeReason, SignalLifecycleState | Registered: C-020, C-021, C-022, C-023, C-070, C-024, C-025, C-026. C-021v2 includes `InvalidationRuleSetV2`/`InvalidationTriggerV2`; C-070v2 includes exact `SignalLineageV2`. `StrategyCondition`, `QualificationRuleSet`, `NoTradeReason` are embedded/value objects. `EvidenceGraph` embedded/value object alias under C-024. `SignalLifecycleState` enum/state vocabulary. |
| Chat 7 | BacktestResult, ValidationResult, OOSResult, WalkForwardResult, RobustnessResult, BiasCheckReport, MultipleTestingObservation, MonteCarloResult, SensitivityResult, RegimeValidationResult, ValidationFreshness, DatasetVersion, StrategyValidationStatus | Registered: C-027, C-028, C-071, C-029, C-030, C-094, C-105, C-072, C-073, C-074, C-092, C-106. `ValidationFreshness`, `StrategyValidationStatus` enum/state vocabularies. C-105 and C-106 implement bounded observation-only exceptions in ADR-0028 and ADR-0029; neither grants downstream authority. |
| Chat 8 | AccountSnapshot, PortfolioSnapshot, PositionSnapshot, RiskProposal, RiskAssessment, PositionSizingResult, LeverageAssessment, LiquidationAssessment, StopLossAssessment, TakeProfitAssessment, PortfolioImpact, StressTestResult, RiskDecision, RiskRevalidationResult | Registered: C-032, C-033, C-075, C-034, C-035, C-036, C-076, C-077, C-078, C-079, C-080, C-081, C-082, C-083. |
| Chat 9 | ApprovalRequest, ApprovalDecision, ApprovalBindingHash, ExecutionIntent, OrderRequest, Order, ExchangeOrder, Fill, Position, Trade, ExecutionReport, ReconciliationReport, IdempotencyKey, ExecutionState | Registered: C-037, C-038, C-039, C-084, C-040, C-085, C-041, C-042, C-043, C-095, C-096. `ApprovalBindingHash`, `IdempotencyKey` embedded/value objects. `ExecutionState` enum/state vocabulary. |
| Chat 10 | SafetyPolicy, SafetyDecision, TradingReadinessState, KillSwitchState, CircuitBreakerState, SecurityEvent, AuditEvent, FailureEvent, RecoveryAction, AgentPermissionPolicy, PromptInjectionAssessment, SafetyIncidentReport | Registered: C-097, C-058, C-059, C-086, C-060, C-087, C-088, C-098, C-089, C-099. `KillSwitchState`, `CircuitBreakerState` enum/state vocabularies. |
| Chat 11 | SignalViewModel, EvidenceReportView, RiskProposalView, ApprovalView, NoTradeView, AgentHealthView, SystemAwarenessView, StrategyPerformanceView, AuditTimelineView, ExecutionMonitorView, GovernanceQueueView | All classified as UI/read-model DTOs (presentation contracts only; no `C-###`). |
| Chat 12 | MethodologyCategory, IndicatorMetadata, FundamentalAssessment, TechnicalIndicatorAssessment, OnChainAssessment, SentimentAssessment, ConfluenceIndependenceAssessment, TraderFacingExplanation, RepositoryMap, ImplementationSlice, CopilotTaskPrompt, DefinitionOfDone, TestTraceabilityMatrix, ContractRegistry, ADR, MigrationPlan, ReleaseGate, EnvironmentConfig, CIValidationReport, agent matrix, handoff matrix, evidence graph, decision provenance, permission matrix, state machines, version registry, audit matrix, failure matrix, test traceability matrix | Registered: C-011, C-012, C-016, C-017. `TechnicalIndicatorAssessment` aliases Technical scope under C-012. `ConfluenceIndependenceAssessment` aliases independence logic across C-009 and C-093. `MethodologyCategory` enum/state vocabulary. `IndicatorMetadata`, `EnvironmentConfig` embedded/value objects. `TraderFacingExplanation` UI/read-model DTO. Remaining names are governance artifacts. |
| Chat 13 | ExperienceRecord, LearningObservation, LearningInsight, Hypothesis, Experiment, ExperimentResult, CounterfactualAnalysis, AgentPerformance, StrategyPerformance, CalibrationRecord, DriftAssessment, SystemAwarenessSnapshot, KnowledgeArtifact, GovernanceDecision, StrategyChangeProposal, ChampionChallengerRecord | Registered: C-045 (alias `ExperienceRecord`), C-046, C-047, C-048, C-049, C-050, C-090, C-052, C-053, C-031 (alias `CalibrationRecord`), C-055, C-054, C-056, C-057, C-051, C-100. |

## Issue #103 — embedded risk policy/configuration values

`RiskLimitScope`, `RiskLimitDefinition`, and `RiskLimitPolicyConfiguration` are
immutable embedded/value objects under the existing Chat 8 risk contracts; they
are not new cross-domain contracts and receive no `C-###` identifier. Their
scope precedence is `SYSTEM > ACCOUNT > PORTFOLIO > STRATEGY > TRADE >
USER_REQUEST`. A supplied applicable lower-level definition cannot disable,
soften, replace with a non-comparable limit, or weaken a `HARD` parent; only an
equal or tighter comparable `HARD` bound is permitted. Omitted external policy
definitions cannot be detected, so these objects do not prove policy
completeness. Existing `PASS_WITH_WARNING` behavior is preserved; these values
do not enforce downstream human review or acknowledgment for soft breaches.

This is a typed value-object and validation boundary only. It adds no default
policy or thresholds, policy store/resolver/API/database/migration, risk
consumer, account/portfolio calculation, approval, or execution authority.

## Issue #104 (canonical 102) — offline account evidence

The frozen `OFFLINE_ACCOUNT_EVIDENCE` scope adds only nonpersisted, immutable
`AccountEvidenceContext`, `AccountPermissionObservations`,
`OfflineAccountEvidence`, and `OfflineAccountAssessment` values in the risk
package. These are embedded/internal values, not new `C-###` contracts.
`AccountSnapshot` C-032 schema `1`, its constructor/financial validation, its
legacy digest meaning, and `PortfolioSnapshot` consumers remain unchanged.
Chat 8 §§6 and 78 and ADR-0018 govern this bounded implementation.

Evidence embeds the entire supplied C-032 snapshot and explicitly observed
account UUID, source string, source `VersionReference`, venue, operating mode,
and read/trade/withdraw/transfer permission observations. Context identities
and observations may be explicitly missing (`None`); permissions additionally
have typed `UNKNOWN`, `ALLOWED`, and `DENIED` observations. Known `DENIED`
observations are complete data, not failures of observation. No observation,
including `ALLOWED`, grants any permission to the platform or risk engine.

Assessment compares an explicitly supplied expected context to the observed
context and binds observed account/source/version to C-032. Unknown or
conflicting identities, missing/unknown permission observations, non-`VALID`
snapshots, future snapshot `as_of`/capture, or evaluation after `valid_until`
produce noncurrent results with explicit reason codes. Equality at capture
and expiry passes. Evaluation time must be explicitly timezone-aware and is
normalized to UTC; no wall clock is consulted. Independent-source
reconciliation is always `UNKNOWN`, even for otherwise current evidence.
Currentness describes only these supplied inputs, not external account truth,
privilege, risk acceptance, approval, readiness, or execution authority.

The evidence digest binds the complete snapshot (including its legacy
`content_sha256` and fixed contract/schema metadata) and all observed offline
metadata, excluding only the evidence's own digest. Verification recomputes
that binding before assessment; it does not authenticate the legacy digest,
the source, or provider truth. Money remains finite typed `Decimal` with
explicit currency and C-032 validation: no missing-to-zero conversion, FX,
balance inference, authoritative derived funds, or financial reconciliation
formula is introduced.

No persisted schema, codec registration, store, migration, API, integration,
network call, downstream wiring, execution, or approval path is added.
External completeness, independent-source verification, ingestion and all
consumer integration remain deferred; this scope does not complete live
account integration.

## Issue #103 (canonical issue; GitHub #105) — offline exposure and correlation

This profile adds only immutable, nonpersisted risk-package values and pure
deterministic calculations. It creates no `C-###` contract, stored artifact,
codec, API, database object, migration, consumer wiring, or architecture
change. The earlier embedded risk policy/configuration entry labeled Issue #103
is a separate retained implementation slice.

Exposure aggregation requires an explicit `VALID` C-032 account snapshot with
positive equity, a nonempty tuple of explicit C-075 position snapshots, one
nonblank caller-supplied venue per position, and an aware evaluation timestamp.
Every snapshot must belong to the same account, must not be future-dated, and
must remain fresh; equality at `valid_until` is accepted. Position and snapshot
identities must be unique. Invalid, incomplete, unpriced, malformed, missing
venue, or duplicate input fails closed rather than being omitted or zero-filled.
Repeated instruments are intentionally grouped, not discarded.

For each currency, asset, instrument, venue, and direction bucket, gross long
and gross short are retained separately; signed net is `gross_long -
gross_short`, and gross is `gross_long + gross_short`. Buckets retain their
currency, so unlike currencies are neither netted nor summed into a fictitious
portfolio-wide number. Same-currency concentration is `currency_gross /
account_equity`; per-asset concentration is each `(asset, currency)` gross
notional divided by account equity. Both use finite `Decimal` at precision 34
and half-even rounding and are not clamped to `[0, 1]`. Concentration in a
currency different from account equity is explicitly `UNKNOWN`
(`FOREIGN_CURRENCY_NO_FX`); no FX or currency conversion is inferred. These
observations are not thresholds, limit checks, loss/PnL formulas,
mark-to-market, or trading decisions.
The aggregation carries account/snapshot identity, exact position snapshot
IDs, evaluation time, and a canonical digest binding the supplied account,
sorted position/venue inputs, and evaluation time. That digest is a content
binding, not external authentication.

Pairwise analysis accepts only caller-supplied immutable, source/version and
SHA-256 input-digest-bound series of finite Decimal close-to-close log returns.
Each series digest is the canonical SHA-256 of its instrument ID, source ID,
`VersionReference`, and exact observation tuple.
The caller supplies an explicit inclusive aware-time window and minimum sample
count of at least three. Each series has a unique instrument identity and
strictly increasing timestamps. Each pair requires identical timestamp sets
inside the window. A mismatch returns `UNKNOWN` with `TIMESTAMP_MISMATCH`, no
value, and zero used samples for both correlation and beta; unmatched
observations are never silently dropped. Mismatches outside the explicit window
do not affect the calculation. There is no cleaning, resampling, interpolation,
forward-fill, or default window/count. Pearson correlation is sample covariance
divided by the product of sample standard deviations. Optional beta is sample
covariance divided by the sample variance of only the explicitly named,
supplied benchmark. Arithmetic uses Decimal precision 34 with half-even
rounding and is not annualized. Pearson results at most `1e-32` beyond
`[-1, 1]` due to rounding are corrected to the nearest boundary; larger
violations fail closed.

Results retain exact window, aligned sample timestamps/counts, each series'
source/version/content digest, and an input digest binding the series, window,
minimum sample count, and optional benchmark. Insufficient aligned samples,
unalignable inputs, zero variance, or zero benchmark variance return `UNKNOWN`
with an explicit reason, never numeric zero. Values are descriptive only: they
do not establish statistical confidence, independence, persistence, future
stability, authorization, a risk-limit result, or a trade decision.
Return-series digests provide deterministic content binding, not
authentication of source identity, external provenance, or market data.
Neither exposure nor return digests authenticate account truth.

C-033 `PortfolioSnapshot` and C-075 `PositionSnapshot` remain schema 1 with
their exact existing constructors, meanings, and consumers. This profile does
not populate, reinterpret, or change legacy C-033 correlation fields. It adds
no market/account/exchange lookup, external access, credentials, approval,
execution, FX, leverage/margin, pending-order, strategy-grouping, threshold,
loss/PnL, or mark-to-market behavior. No secrets or live-execution path are
introduced.

## Issue #104 (canonical issue; GitHub #106) — offline position sizing

`calculate_position_size(PositionSizingRequest)` calculates the existing C-036
schema 1 without changing its constructor, fields, consumers, or authority.
`SizingInstrumentTerms`, `SizingCosts`, and `PositionSizingRequest` are immutable
nonpersisted inputs, not new canonical contracts. There is no API, storage,
producer, exchange access, or runtime integration.

The caller supplies an explicit result ID, evaluation time, `RiskContext`,
matching valid account/portfolio snapshots, positive effective risk budget,
policy/configuration/budget/model versions, and a common assumptions-validity
window. The caller attests that window covers the supplied instrument, costs,
budget and selected volatility/Kelly inputs. All context references require
digests and explicit expiry. Snapshot IDs, schema, digests and expiry must
match their references; portfolio account/equity must match the supplied account.
Future or expired snapshots, embedded positions, assumptions or references
cannot produce a recommendation. Equality at expiry is accepted.

Only explicitly identified `LINEAR` instruments are supported. Quantity is
contract units, multiplier is base units per contract, price is quote per base,
and costs/margin are quote currency per contract. Entry/stop must conform to
the supplied tick, and stop direction must be valid for LONG or SHORT.
All money uses the account/instrument quote currency; FX is not inferred.
The caller supplies nonnegative round-trip adverse fee, slippage and funding
per contract (including explicit zero if applicable), positive initial margin
per contract, quantity min/max/step and maximum notional.

Per-unit stop loss is `abs(entry - stop) * multiplier`. Per-unit entry notional
is `entry * multiplier`. The five existing methods are:

- RISK_BASED: target quantity is effective budget divided by per-unit stop
  loss plus adverse costs.
- FIXED_NOTIONAL: target quantity is requested notional divided by per-unit
  entry notional.
- PERCENTAGE_OF_EQUITY: target notional is equity times the explicit fraction
  in `(0, 1]`.
- VOLATILITY_ADJUSTED: budget denominator is
  `max(per-unit stop loss, supplied volatility loss per unit) + adverse costs`.
  The reported maximum loss is this conservative loss basis times quantity,
  not a volatility forecast or guaranteed worst loss.
- FRACTIONAL_KELLY: target notional is equity times
  `fraction * (p - (1 - p) / win_loss_ratio)`. Probability is in `[0, 1]`,
  fraction is in `(0, 1]`, and payoff ratio is positive. Versioned caller
  estimates are required; only RESEARCH/BACKTEST is allowed. A nonpositive
  edge returns FAILED/NO_TRADE, never a fallback method.

Every method is capped by effective budget, maximum quantity, maximum notional
and available free margin. Quantities are rounded down to step multiples
anchored at zero, never up to minimum; an infeasible minimum returns no trade.
Budget above account equity is rejected because C-036's account-risk ratio
cannot represent a loss fraction above one. The caller must have already
reduced the effective budget for policy hierarchy and consumed/open risk;
this calculator does not evaluate that hierarchy or authenticate the budget.

Arithmetic uses an isolated Decimal precision-34, half-even context. Unit
loss/notional/margin and final stepped amounts must be exactly representable;
otherwise calculation raises `RiskContractError`. Step counts and target
calculations round down, and Kelly's losing-probability term rounds up.
Every final amount is checked against its cap without tolerance or upward
rounding. Account risk is reported loss/equity, half-even at precision 34.
Capped notional/percentage/Kelly targets and volatility budget-derived targets
(including step reductions) yield WARNING with `REQUESTED_TARGET_REDUCED`,
not silent target alteration.

Malformed inputs raise `RiskContractError`; missing/currentness failures
yield INSUFFICIENT_DATA and deterministic constraint failures yield FAILED,
with explicit reasons and no recommended size/notional/margin/loss.
Failed expired evidence produces a result expiring at evaluation time, never
a PASSED result with refreshed validity. The result digest is canonical SHA-256
of `{"request": request, "result": result fields except content_sha256}`.
It binds exact versions, context, inputs and outputs, but authenticates neither
source identity nor external completeness.

No volatility/Kelly estimation, nonlinear instrument model, leverage selection,
liquidation, portfolio-impact decision, stop recommendation, approval, order
construction or execution is introduced. C-036 PASSED is a sizing observation,
not a risk-policy pass or trade authorization. Later leverage (#109),
liquidation (#110), portfolio impact (#111), proposal (#113) and revalidation
(#114) work retain their own responsibilities.

## Issue #105 (canonical; GitHub #107) — offline stop-loss assessment

`calculate_stop_loss_assessment(StopLossAssessmentRequest)` produces the
existing C-078 schema `1` without changing its constructor, fields, meanings,
consumers, or authority. The request and its immutable structural, volatility,
and liquidation evidence values are nonpersisted inputs, not new canonical
contracts. The calculator is pure and offline; it adds no codec, persistence,
API, database, migration, external lookup, or runtime integration.

The request explicitly binds a result UUID, evaluation time, `RiskContext`,
matching C-032/C-033 snapshots and their source versions, model/policy/
configuration versions, effective maximum-loss budget, proposed quantity,
entry/stop, linear instrument terms, adverse costs, gap displacement and
version, policy minimum stop distance, and an assumptions validity window.
The caller has already reduced the effective budget for policy and consumed
open risk; the calculator neither resolves policy hierarchy nor authenticates
that budget. Account/portfolio identity, equity, currency, schema, content
digest, source version, timestamp and expiry must agree with the context and
caller-supplied evidence. C-021, C-028 and C-070 references accept registered
schemas `1` and `2`; C-023, C-032 and C-033 references require schema `1`.
Unknown schemas fail closed. All references require a digest and expiry;
version-qualified identities are preserved without payload down-conversion.
Evaluation at an expiry boundary is accepted. C-078 output remains schema `1`.

Only the existing `SizingInstrumentTerms` and `SizingCosts` linear inputs from
issue #106 are consumed. Quantity is in contract units; multiplier is base
units per contract; prices and gap displacement are quote currency per base
unit; fee, slippage and funding are adverse quote currency per contract.
Entry, stop, multiplier, tick, step, quantity bounds and maximum notional are
validated explicitly. Entry and stop must be tick-conforming; quantity must
be within minimum/maximum bounds and an exact step multiple anchored at zero.
No FX, nonlinear instrument model, exchange lookup, stop movement, rounding,
or quantity adjustment is performed.

LONG requires `stop < entry`; SHORT requires `stop > entry`. The result
includes absolute stop distance and `distance / entry`, with ratio arithmetic
at fixed Decimal precision 34, half-even. C-078 `RatioValue` cannot represent
a ratio above one, so the exact distance is compared with entry before ratio
division; out-of-range ratios fail closed even if rounding would yield one.
An explicit, version-bound policy minimum distance and
caller-supplied, versioned volatility minimum-distance threshold are both in
the request's explicit `price_unit_currency` and are compared to actual
distance. The volatility value is an input threshold, not an estimated
volatility statistic.

Structural alignment requires current caller-attested C-023 invalidation
evidence with a priced inclusive lower/upper acceptable-stop interval, exact
strategy-version and risk-context references, and matching asset, instrument,
and side. A bare boolean is not evidence; unpriced/qualitative invalidation is
not evaluated. The interval is a materialized boundary, not a claim that the
calculator evaluates every C-021 strategy rule. Leveraged positions require
current, versioned caller-supplied liquidation price and nonnegative
stop-to-liquidation buffer evidence. Liquidation must be beyond the stop in
the adverse direction and the buffer must be met. No-liquidation
nonapplicability passes only with explicit caller-attested fully funded spot
evidence. Unknown applicability, missing leveraged liquidation price, or
stale evidence cannot pass.

For valid same-currency inputs, maximum loss is calculated exactly at isolated
Decimal precision 34:

`quantity * ((abs(entry - stop) + adverse_gap_displacement) * multiplier + fee_per_unit + slippage_per_unit + funding_per_unit)`

Costs must be nonnegative and explicit, including explicit zero values.
Adverse gap displacement is additional price movement and is not an
already-cost-inclusive aggregate. Monetary arithmetic that cannot be
represented exactly at precision 34 raises `RiskContractError`; budget
comparison has no tolerance or loss clamp. The estimate is bounded by the
supplied assumptions, not a guaranteed maximum market loss.

`PASSED` requires all evidence to be present/current and structural,
volatility, liquidation, instrument, quantity, distance, notional, and hard
loss-budget checks to pass. Deterministic constraint breaches are `FAILED`;
missing, stale, future, or unknown evidence is `INSUFFICIENT_DATA`. If the stop
is missing or directionally invalid, C-078 leaves the stop and derived fields
unset to preserve its constructor invariant; callers must retain the original
request alongside the result. The canonical result digest binds the complete
request, assumptions, versions, reason codes, and all C-078 output fields
except its own digest. `valid_until` is bounded by the earliest applicable
context, snapshot, source, assumption, strategy, volatility, and liquidation
expiry; an incomplete/stale assessment is valid only at evaluation time.
The existing C-078 `cost_assumptions` field retains only the supplied
`SizingCosts` version; gap, instrument, policy, and other request versions
remain bound by the complete request digest. Hashes bind supplied content but
do not authenticate external truth.

The assessment validates only stop-specific inputs. It does not generate a
stop, estimate volatility, evaluate all strategy rules, size a position,
calculate leverage/liquidation, decide portfolio impact, approve risk, or
authorize approval/execution. A sizing pass does not imply stop validity, and
a stop pass is not overall risk approval or execution authority.

## Issue #107 — offline leverage and margin assessment

C-076 `LeverageAssessment` remains schema `1` with its exact constructor,
fields, meanings, consumers, and authority. The pure
`calculate_leverage_assessment(LeverageAssessmentRequest)` reuses
`PositionSizingRequest`, recalculates C-036 with `calculate_position_size`, and
returns the existing C-076 result. `LinearMarginRuleEvidence` and
`LeverageAssessmentRequest` are immutable nonpersisted inputs, not new
canonical contracts. No codec, API, database, migration, external lookup, or
runtime integration is introduced.

The request binds a result UUID and evaluation time; the exact sizing request;
requested leverage; explicit policy, account, venue, and post-trade gross
leverage caps; margin mode; minimum remaining free margin; incremental
reserved quote-currency cost; and caller-attested, versioned margin-tier
evidence. The sizing request's explicit model/policy/configuration versions and
common assumption-validity window remain bound in full. There is no default,
policy hierarchy resolver, clamping, or override path. Material edits require
a fresh request and assessment.

Only LINEAR models and matching explicitly supplied CROSS or ISOLATED
incremental margin rules are supported. Rule evidence binds venue, instrument,
account and exact mode, applicable inclusive gross-notional tier bounds,
initial/maintenance rates, version, and validity. The caller supplies one
applicable tier; the calculator does not query or select venue tiers. No
offsets, netting, hedging benefit, collateral conversion, FX, or liquidation
behavior is inferred.

The calculator requires current, matching C-032/C-033 snapshots and complete
valid C-075 positions, rejects duplicate snapshot/position identities, sums
absolute position notionals, and checks that this gross sum agrees with C-033.
An explicitly valid empty position tuple represents zero exposure only when
C-033 gross exposure is zero. It requires positive matching equity and uses
both available balance and free margin. Account/source assertions and supplied
rule content remain caller-attested; this does not authenticate exchange rules,
reconcile the external account, reconstruct balances, or estimate collateral
haircuts.

For recomputed C-036 notional `N` and proposed margin `M`, notional and margin
are verified against exact quantity/instrument terms. Required initial margin
is `max(M, N / requested_leverage, N * initial_margin_rate)`; only the
division is rounded upward at Decimal precision 34. `M` must cover that
requirement. Maintenance margin is the incremental `N * maintenance_rate`;
effective leverage is `N / M`. Post-trade gross leverage uses absolute
existing gross exposure plus `N`, divided by matching equity. Leverage caps
are checked by exact cross multiplication. `M` plus the explicit incremental
reserve must fit available balance and leave the minimum free-margin buffer.
Only the required-margin division and reported ratios are rounded upward;
unrepresentable arithmetic raises `RiskContractError`.

Hard breaches yield `FAILED`; missing, stale, future, or unknown required
evidence yields `INSUFFICIENT_DATA`; upstream sizing warnings propagate, and a
hard failure dominates. Failed/insufficient results do not carry numeric
recommendations. The digest binds the complete request, recomputed C-036
evidence, and C-076 output excluding its own digest; it proves content binding,
not source authenticity. Validity is bounded by upstream and rule expiries;
expiry equality is valid. C-036/C-076 passes are component observations only,
not overall risk acceptance, human approval, or execution authority.

## Issue #110 — offline supplied liquidation-estimate assessment

C-077 `LiquidationAssessment` remains schema `1` with its exact constructor,
fields, meanings, consumers, and availability constraints. The pure
`calculate_liquidation_assessment(LiquidationAssessmentRequest)` recomputes the
exact supplied `LeverageAssessmentRequest` through
`calculate_leverage_assessment`. Its immutable estimate, threshold, cost, and
request values are nonpersisted inputs, not new canonical contracts. No
liquidation formula, API, codec, persistence, migration, external adapter, or
runtime integration is introduced.

Only current caller-attested LINEAR evidence is supported. It binds the exact
request and C-036 sizing quantity; context, entry, stop, side, instrument,
venue, account and portfolio snapshots, margin mode, source identity, formula
and exchange-constraint versions; and aware as-of/expiry times. Formula and
constraint digests bind declared content but do not authenticate the source or
verify an exchange formula. Missing/unknown formula inputs, incomplete CROSS
account evidence, stale/future/mismatched estimate basis or source context, and
unsupported cost treatment are unavailable. ISOLATED and CROSS evidence are
never substituted. The function does not infer a liquidation price.

Threshold inputs are explicit, versioned quote-price assumptions: minimum
entry-distance ratio, absolute stop buffer, and normal/stress adverse
displacements. Fee/funding reserves are nonnegative, currency-matched,
versioned, and accepted only when the caller explicitly attests they are
already included in the supplied estimate. Any treatment needing a price
adjustment is unavailable; reserves are not subtracted and zero is never
inferred. LONG and SHORT comparisons use the adverse direction, positive
entry-distance and stop-clearance, exact threshold comparisons, and
entry-denominated C-077 ratios. Equality meets a threshold; liquidation at or
inside the stop is a hard failure. If either distance is non-positive or
outside the representable C-077 range, availability is `UNAVAILABLE` and all
three estimated numeric fields are omitted. A known wrong-side or at/inside-
stop hard failure takes precedence over `INSUFFICIENT_DATA`; otherwise a
representable current estimate that breaches a distance or buffer threshold
remains `AVAILABLE/FAILED`.

Current matching C-021/C-028/C-070 references (schema 1 or 2) and exact
C-032/C-033 schema-1 snapshot references with digests and expiries are
required. Known hard failures dominate missing evidence, upstream FAILED or
INSUFFICIENT_DATA is never upgraded, and upstream WARNING plus numeric evidence
propagates. NOT_APPLICABLE is not treated as PASSED; there is no fully-funded
Spot resolver. A representable current estimate with a distance or buffer
threshold breach remains `AVAILABLE/FAILED`; wrong-side, at/inside-stop, or
unrepresentable distances are `UNAVAILABLE`, with no estimated numeric
fields, and a known hard failure takes precedence over insufficiency. The
digest binds the complete request, recomputed C-076
assessment, and C-077 output excluding its own digest; it proves content
binding only. Validity is bounded by all related upstream evidence and
assumption expiries; equality is current. No result grants overall risk
acceptance, approval, or execution authority.

## Issue #108 — offline take-profit / risk-reward assessment

C-079 `TakeProfitAssessment` remains schema `1` with its exact constructor,
fields, meanings, consumers, and authority. The pure offline
`calculate_take_profit_assessment(TakeProfitAssessmentRequest)` reuses the
existing C-079, C-078, C-036, `TakeProfitTarget`, `SizingCosts`,
`SizingInstrumentTerms`, and `RiskContext` contracts. Its immutable request
and per-target bound values are nonpersisted inputs, not new canonical
contracts; there is no codec, API, database, migration, external lookup, or
runtime integration.

The request binds a result UUID and evaluation time; an exact
`StopLossAssessmentRequest` that is recalculated by
`calculate_stop_loss_assessment`; the typed current C-036 result; context and
entry; immutable ascending-sequence targets; a current priced bound per
target; explicit `SizingCosts` with a version per target; a positive explicit
minimum risk-reward ratio and version; and model/assumption versions and a
validity window. The stop must pass. C-036 must be a current schema-1
`PositionSizingResult` in the same context and its recommended quantity,
stop distance, and instrument/cost assumptions must match the stop inputs.
Notional and initial margin are checked against the exact entry, multiplier,
quantity and instrument terms, including the notional cap and available margin.
All supplied sizing money uses the quote currency; sizing min/max/step bounds
match the instrument and nominal loss cannot exceed the sizing risk budget.
These checks also apply to warnings; missing bounded outputs remain unknown.
Its nominal maximum loss plus the exact supplied adverse-gap adjustment must
match recomputed C-078 maximum loss. A C-036 warning is retained as a C-079
warning; missing or stale evidence is `INSUFFICIENT_DATA`, and hard failures
take precedence over missing data and warnings.

Input target `expected_profit` must be unset, including zero; this calculator
computes it. Targets must sum to exactly one allocation. LONG targets are strictly
ascending above entry; SHORT targets are strictly descending below entry.
Every target price conforms to the supplied instrument tick. Each allocated
quantity (sizing quantity times target allocation) must satisfy the
instrument's minimum, maximum, and step bounds without adjustment. For each
target, directional gross profit is reduced by that target's explicit
per-unit fee, slippage, and funding from versioned `SizingCosts`; no costs or
price data are inferred. A versioned minimum R:R is checked by exact
cross-multiplication against the recomputed C-078 maximum loss; the displayed
ratio is rounded downward at precision 34 and is not used as the threshold
authority.

Each target also requires current caller-supplied priced bounds with exact
C-021 strategy, C-023 invalidation, `RiskContext`, asset, instrument, side,
and sequence lineage. C-021/C-028/C-070 schema 1 and 2 references are
accepted through explicit dispatch; other referenced contracts retain their
registered schema requirements. Expiry is the earliest applicable request,
context, stop, sizing, and target-bound expiry. The result digest canonically
binds the complete request and all C-079 result fields except the digest.
Callers retain the exact nonpersisted request alongside the C-079 result.
Arithmetic uses an isolated precision-34, half-even Decimal context; exact
operations are trapped and unrepresentable values raise
`RiskContractError`.

No sizing, portfolio-policy resolution, approval, execution, or broader risk
decision is introduced. C-079 is an assessment only, not a trade
authorization; all market/strategy bounds and source truth remain
caller-supplied and unauthenticated.

## Approval scope and change control

- Registry approval establishes cross-domain semantics and ownership; schemas and implementation artifacts are intentionally deferred.
- Breaking changes require impact analysis, migration/version strategy, architecture review, and explicit human approval.
- Historical contract meaning is never silently rewritten; corrections are additive/superseding with provenance.
- `SignalCandidate` is never an order, `Signal` never bypasses qualification, and `ApprovalDecision` remains bound to exact immutable configuration.
- Risk, approval, safety, idempotency, reconciliation, learning-governance, and fail-closed boundaries remain mandatory.
- Open technology/provider choices remain unresolved per [`14-open-decisions.md`](./14-open-decisions.md).

## Deferred consistency work (out of scope for this issue)

- Align non-registry artifacts that still use deprecated or context-local names with canonical names/aliases above (without changing semantics).
- Resolve cross-artifact `TradingReadinessState` vocabulary drift (`01-domain-contract-registry.md`, `08-state-machine-registry.md`, Chat 10) through governed impact analysis and ADR/human approval before any semantic harmonization.
- Add schema-level contract definitions and compatibility tests in later implementation phases.

## Validation evidence for this update

- Existing IDs `C-001`–`C-060` preserved and unique.
- New IDs appended sequentially `C-061`–`C-100`, unique and not reused.
- Every explicit Chats 2–13 required name has a disposition in this document.
- Every newly registered contract includes authoritative producer, primary consumers, and safety-relevant invariant.
