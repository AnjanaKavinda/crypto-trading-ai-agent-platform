# Wave Execution Plan

**Status:** Wave 0 plan for owner review  
**Updated:** 2026-10-30  
**Owning issue:** #421  
**Baseline:** `dev` at `b5ccae72cecd477c407cb5753023d3e3ce4275e7`

This is a delivery-management overlay on the authoritative 183-issue catalog, each GitHub issue's current implementation contract, Master Playbook Chat 12, and the owner decision in #299. It changes how independent work is organized; it does not replace issue dependencies, approved scope, safety gates, or human review.

## Current state and sequencing

- #299 remains open. Its 2026-10-28 owner decision is: complete and verify the personal Spot research workflow, then deliver Futures research, then consider any later mode only with explicit approval.
- #414 and #415 are closed. PR #420's isolated Docker acceptance reports 10 tests passed; this does not close #299 or establish profitability.
- #39 (derivatives ingestion) and #61 (derivatives analysis) remain open. ADR-0011 is Proposed and OD-0002/OD-0004 remain Open.
- #70, #71, #73, #75, #76, #77, and #78 are open. #72 and #74 are closed and stay closed.
- #256 is closed. Its release/readiness requirements and each issue's remaining profile-specific gates still apply.
- The real five-pair Spot smoke recorded in #299 had four VALID snapshots and BNB correctly withheld as stale. The issue remains open for its broader candidate/NO_TRADE and prospective measurement completion gate.
- No Wave 0 change alters the current local, single-user, read-only boundary.

## Priority classification

This classification covers issues relevant to the personal research path and the requested Waves 0–9. It does not rewrite priority labels or reclassify unrelated automation/platform work.

| Priority | Scope and issues | Rationale / constraints |
|---|---|---|
| **P0 — Critical path** | #299; open orchestration #70, #71, #73, #75–#78; strategy #80–#90; validation #91–#102; research E2E #172; decision display #148–#149 once their stated dependencies are met | Required to reach provenance-bound data → analysis → strategy → evidence → candidate/NO_TRADE → measurement. Preserve each issue's profile scope, dependencies, and CI/review gates. |
| **P1 — Parallel enablers** | Derivatives #39/#61 after the Spot gate; broader analysis #62–#68 outside the current Spot profile; AuthN/AuthZ #136 and safety compliance #142 as explicit gates for #148/#149; supporting visibility/audit #154/#155 | Useful in parallel or as later gates; must not block unrelated Spot work or bypass their issue requirements. Provider-specific Futures ingestion waits on OD-0002/OD-0004 and applicable source terms. |
| **P2 — Enhancements** | Grounded analysis chat #297; visual preview #298; Bookmap-style order-flow/liquidity views #355 | Valuable only when based on the same validated, provenance-bound evidence; #355 remains blocked on validated trade/depth history. |
| **P3 — Later / production** | Risk/approval/execution and paper/testnet implementation/readiness issues #103–#141 (with #136/#142 as noted above); execution-oriented UI #150–#153; paper/testnet/live and broad operations/readiness #171–#185; production event/notification work #257–#264 | Retain for later phases. They do not authorize app-driven execution in personal research. Paper/testnet needs explicit later approval; Live needs a separate readiness decision and explicit owner approval. |

P0 measurement caveat: #157/#158 currently depend on the execution/reconciliation group #125–#142 and describe actual factual outcomes, while #299 requires prospective logging of manual owner-placed trades and `NO_TRADE` decisions in research mode. Before Wave 5 implementation, reconcile whether existing C-044/C-045 and #157/#158 cover this input without execution state. If not, create one bounded, governed research-log issue after checking the current contracts. Wave 0 does not add an unregistered contract or silently remove safety dependencies.

## Wave plan

| Wave | Objective and included work | Dependencies and allowed parallel work | Exit criteria / safety gates |
|---|---|---|---|
| **0 — Architecture / project control** | #421: record the Market Intelligence architecture, reconcile #39/#61, priorities, traceability, and this plan. | One issue and one PR. | Proposed ADR and documents reviewable; no Playbook, runtime, provider, schema, migration, or mode changes. Owner reviews/merges before Wave 1. |
| **1 — Orchestration foundation** | **Exact open set:** #70 structured result validation, #71 agent registry, #73 LangGraph foundation, #75 debate/critic, #76 memory boundary, #77 instrumentation, #78 failure/fallback tests. Keep closed #72/#74 closed. | Profile-scoped validated Spot outputs plus #34/#256 gates. Freeze C-061/C-062 schemas and output allowlists before parallel consumers. Then allow up to 2–3 streams: result validation/registry; vendor-neutral memory boundary (no vector store/retention choice); observability and failure-test work. #73 integrates only validated bounded nodes; #75 follows its typed state/result boundary. | All seven open issues meet their personal-profile requirements; invalid/unknown output rejects, NO_TRADE remains valid, cancellation/fallback is bounded, provenance is retained, and no node receives provider/risk/approval/execution authority. |
| **2 — Strategy core** | #80 condition DSL, #81 eligibility, #82 setup detection, #83 market thesis. | Wave 1 profile requirements complete. #80 precedes #81/#82; #83 may proceed in parallel against frozen `MarketContext` and evidence contracts. | Deterministic, versioned conditions; eligible market/context only; explicit counter-thesis, expiry and uncertainty; no candidate is executable. |
| **3 — Candidate, evidence, NO_TRADE** | #84 candidate engine, #85 evidence package, #86 qualification, #87 historical conditional rule, #88 NO_TRADE. | #84 follows eligible strategy/setup. #85 binds exact evidence and counter-evidence. #86/#87 consume authoritative Chat 7 results; #88 can develop alongside qualification once reason codes and validated evidence states are fixed. | Candidate or NO_TRADE is explicit; incomplete/stale/conflicting evidence fails closed; the 75% historical rule is not a future guarantee; no AI confidence substitutes for statistical validation. |
| **4 — Lifecycle, API, product view** | #89 lifecycle/expiry/invalidation; #90 read-only strategy/signal API; #148 evidence report and #149 signal/NO_TRADE UI; supporting #154/#155 only when their own scope is ready. | #89 consumes #84–#88; #90 follows lifecycle and evidence contracts. #148/#149 retain their stated #136/#142 gates. No authentication or safety gate is waived to accelerate UI. | Read-only, inspectable, accessible evidence and reason states with exact provenance; no approval/order endpoints or hidden reasoning. |
| **5 — Research validation** | #91 dataset versions/point-in-time loader; #92 backtest model; #93 costs; #94–#102 metrics, OOS, walk-forward, resampling, robustness, regime, bias, experiment controls, freshness; prospective decision and outcome logging under #299. | Follows strategy/evidence requirements. Cost, data-version, and test-window definitions precede performance claims. #92 remains blocked by OD-0011 until resolved. Resolve the manual outcome logging gap above before relying on #157/#158. | Reproducible OOS/WF evidence, adequate sample and uncertainty, realistic fees/slippage/liquidity/funding, no look-ahead, baseline and feature ablations. No fabricated performance or profitability claim. |
| **6 — Derivatives intelligence** | #39 ingestion and #61 analysis; source comparison, deterministic features, and Market Intelligence composition within approved scope. | After the #299 Spot gate. Resolve market/instrument/source/terms and data semantics before provider-specific requests. #39 data validation/provenance precedes #61 analysis; serialize any shared-contract proposal. | Direct venue facts and supplementary intelligence remain distinguishable; exact units, coverage, and timestamps; deterministic calculations and explicit uncertainty; no execution authority. |
| **7 — Futures research** | Extend the validated decision path to the explicitly chosen Futures market/instruments. | After Wave 6 and explicit OD-0002/OD-0004 dispositions. Reuse workflow only through distinct Futures evidence/contracts, methods, quality, costs, and eligibility. | Futures candidate/NO_TRADE and measurement remain separate from Spot; no credentials, paper/testnet, or live functionality unless later explicitly authorized. |
| **8 — Paper trading** | Paper/testnet path and readiness only if a later owner decision authorizes it; relevant #120–#142/#173/#182 gates. | Requires full deterministic risk, safety, authentication, approval, idempotency, reconciliation, audit, recovery, and isolated-mode evidence. Human approval required before work that crosses the current authorization boundary. | Paper is isolated and never presented as Live. Testnet requires a separate approval and source/scope gate. |
| **9 — Supervised Live / production readiness** | Production security, legal/provider, deployment, operations, recovery, readiness, and live gates; relevant #171–#185 and #264. | A separate future proposal after every prior criterion and open decision is resolved. Explicit owner approval is required; no auto-merge or self-approval. | Live stays disabled until an approved readiness record, exact scope, bounded authority, human approval, monitoring, reconciliation, rollback, and review evidence all pass. |

## Parallel execution and shared contracts

- Rule: **issue-level discipline, wave-level parallelism**. Every stream owns one scoped issue and produces its own tests, PR, independent review, and human merge.
- Limit to **2–3 active implementation streams**. More streams increase contract, merge, architecture, and review risk without removing sequential dependencies.
- Contract work is serialized: contract decision → reviewed merge/version freeze → parallel consumers. Two streams must not edit the same shared contract or schema concurrently. If consumers need a contract change, one owner prepares and merges it first; dependent branches rebase/update from latest `dev`.
- Keep each PR bounded; branch from current `dev`; avoid overlapping files; integrate and validate at wave checkpoints. No agent merges its own PR.

## Risk-based validation

**Every PR:** focused tests for the changed behavior; applicable contract tests; lint, format, type, security/secret, issue-specific, governance, and repository-required CI. The plan does not weaken mandatory checks.

**Wave checkpoint:** full backend and frontend suites, migrations and compatibility, Docker-local integration/acceptance, and dependent-service behavior.

**Milestone checkpoint:** real-data end-to-end read-only path, point-in-time replay, stale/missing/conflicting data and provider failures, prospective decision/outcome records, cost-aware validation, and mode-isolation evidence.

Migrations, security boundaries, shared contracts, auth, risk, approvals, and any execution-related work require stronger immediate tests/review as their issues specify. A skipped check is reported as skipped; no check is described as passing unless it ran.

## Master Playbook and source decisions

- `docs/playbook/**` is unchanged. The Fabric extends Chat 2/4/5 and the existing 13-chat flow; it creates no “Chat 14.”
- ADR-0014 is Proposed until owner review. It records CoinGlass's supplementary architecture role but does not approve an actual data product, source, terms, instrument, credentials, subscription, or request.
- OD-0002/OD-0004 remain open; proposed ADR-0011 remains unchanged. #39/#61 remain open. #414/#415 remain closed.
- Future issues must preserve the current #299 sequence and the full-platform dependency graph. Closed issues are retained as historical evidence.
