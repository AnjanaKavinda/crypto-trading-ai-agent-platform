# ADR-0026: Spot regime validation observation boundary

## Metadata

| Field | Value |
|---|---|
| Status | Accepted |
| Date | 2026-11-14 |
| Decision owner | AnjanaKavinda |
| Human approver | AnjanaKavinda (owner-assigned issue #99 Execution Packet) |
| GitHub issue / PR | #99 / #487 |
| Open decision ID | — |
| Related ADRs | ADR-0015, ADR-0019, ADR-0021, ADR-0025 |
| Supersedes / superseded by | — |

## Context

Issue #99 requires reproducible, observation-only Spot performance and coverage
by asset, instrument, venue, timeframe, and the decision-time regime. C-074v1
remains unchanged; its single-result input and free-text regime slices cannot
bind each archived C-027v3 replay, `SpotPerformanceReport`, and C-005 evidence
closure needed by this profile.

## Alternatives

### Option A — Add observation-only C-074 schema 2

Bind a frozen set of archived Spot replay requests and metric policies to
decision-time regime attributions, per-run `SpotPerformanceReport`
observations, and explicit required/observed coverage while leaving existing
C-074v1 consumers unchanged.

### Option B — Extend C-074v1 or integrate with qualification

Would reinterpret existing payloads or give the bounded Spot slice qualification
or deployment meaning that it does not possess.

## Decision

Use an additive immutable C-074 schema 2. The producer reuses the trusted
archive-bound Spot backtest and the existing `SpotPerformanceReport` metrics
implementation. It attributes each run to the decision producing its sole
entry order, or to the first pinned decision when no entry order exists.
Attribution is resolved only from the verified archived
C-006v5/C-007v4/C-005 closure and evidence valid at that decision's information
cutoff and time.

The existing Spot taxonomy is preserved exactly: trend `bullish`, `bearish`, or
`mixed`; realized volatility `high`, `typical`, or `low`; and transition
`possible` or `not-observed-in-lookback`. Mixed is not ranging, possible is not
confirmed, and analytical confidence is not a probability.

Each planned run and every required or observed context is emitted in stable
input/first-occurrence order. Metrics retain their report availability, unit,
sample, warning, and reason states. Missing contexts, zero trades, or
insufficient metrics remain inconclusive; invalid evidence fails closed.

## Reasoning

This preserves deterministic replay and calculation ownership while making
asset/timeframe/regime coverage visible without pooling returns or samples.
Analysis output binds exact request, C-027v3 result/trace,
`SpotPerformanceReport`/`MetricsPolicy`,
strategy, cost, data/manifest, and archived C-005 evidence identities. Frozen
inputs prevent selection or optimization during analysis. Canonical C-074v2
identity is derived from content, and unknown schema versions fail closed.

## Consequences

C-074v1 and its consumers remain unchanged. C-074v2 is descriptive evidence for
the exact frozen Spot runs; it is not qualification, OOS/robustness proof,
profitability, strategy eligibility, or deployment evidence. It does not create
a new regime classifier, metrics engine, network/provider path, or durable
retention authority. Futures, true ranging, confirmed macro regimes, and
full-platform statistical qualification remain deferred.

## Contract and traceability impact

| Area | References and impact |
|---|---|
| Playbook requirements | Chat 7 sections 30–32: regime, asset, and timeframe separation without hiding weak contexts behind aggregate averages. |
| Cross-cutting artifacts | C-074v2 is additive; C-074v1 remains unchanged. |
| Contracts / events | Exact C-027v3 replay and `SpotPerformanceReport`/`MetricsPolicy` evidence closure; archived C-005/C-006v5/C-007v4 attribution. |
| Requirements traceability | Issue #99 and `docs/architecture/issue-99-spot-regime-validation.md`. |
| Versioning / migration | Closed C-074 schema-2 codec dispatch; unknown versions rejected; no migration or DDL. |

## Safety, security, and failure behavior

This is offline `PERSONAL_SPOT_RESEARCH`. C-074v2 grants no risk, approval,
execution, signal, qualification, strategy-status, or retention authority. It is
not accepted by C-030/C-028 qualification consumers. Invalid or altered pins,
unknown taxonomy, non-Spot results, stale sources, or decision-time evidence
fail closed; missing data and insufficient metrics remain inconclusive. No
credentials, provider calls, live trading, or operating-mode transitions are
added.

## Approval record

The repository owner authorized the bounded offline Spot profile and additive
C-074v2 through the owner-authored Execution Packet for issue #99 on 2026-11-14.
