# Bounded Spot analysis fan-out

This document records the first profile-scoped slice of Issue #74 for
`PERSONAL_SPOT_RESEARCH`. The runner executes caller-supplied local,
deterministic Spot analysis operations over unique domains already allowed by
`SUPPORTED_SPOT_FINDING_DOMAINS`. It does not dispatch model calls or
provider requests.

Each task has a UUID and one explicit domain. Every outcome carries the shared
correlation UUID, task UUID, domain, status, and the original typed finding when
successful. The runner bounds concurrency to four, applies a per-task deadline,
preserves successful findings when another task is unavailable, fails, or times
out, and never retries. Expected unavailable states use a bounded reason code
such as `POLICY_REQUIRED` or `INSUFFICIENT_WARMUP`; malformed or mismatched
findings fail as `INVALID_FINDING`. Callback exception text is not exposed.

## Evidence and independence

The fan-in preserves evidence IDs, input bindings, method, and finding identity
from each `SpotMetaFinding`. The
`run_spot_analysis_fanout_with_independence` composition passes only successful
findings to the existing C-093 `assess_agent_independence` path, alongside the
caller's exact validated manifest, resolved bindings, evidence, and evaluation
time. C-093 records observed shared inputs; it does not establish statistical
independence or correlation for this Spot profile. Shared OHLCV evidence
therefore remains explicitly dependent or unknown. Invalid scope fails closed
instead of being returned as a task-level failure. Fan-out count is never a
vote count or confidence score.

## Replay and authority boundary

The runner does not create a LangGraph checkpoint and accepts only local,
deterministic, side-effect-free analysis operations. It does not invoke models,
tools, providers, risk, approval, or execution services. Cancellation propagates,
and there is no retry/fallback policy. Results remain analytical findings and
cannot authorize a strategy, signal, risk decision, human approval, order, or
trade.

This is a bounded foundation, not completion of Chat 3 or full Issue #74.
Future external agent dispatch needs separately validated invocation,
idempotency, cost/deadline, permission, and replay behavior before it can be
added.

## RSI14 finding adapter

The first domain adapter, `adapt_rsi14_finding`, applies the approved mapping
from `issue-74-rsi-momentum-finding-proposal.md`. It accepts only the existing
RSI metadata version `1`, calculation version
`rsi-wilder-sma-seed-v1`, and period `14`. It uses strict comparison at 50,
compares typed direction to the resolved C-005 regime, and emits only
`PARTIAL` readiness with `UNKNOWN` strength. Stable finding identity includes
the binding, snapshot, quality report, cutoff, exact evidence IDs, method and
indicator versions.

Before a finding can be emitted, the caller supplies an exact C-007 manifest,
its matching resolved C-007 binding, and C-008 items. Each item must pass the
existing C-007/C-008 resolver validation and must identify this RSI result:
method `rsi` at the pinned calculation version, feature `rsi` or `rsi14`, the
exact RSI value/unit, and provenance references `indicator-metadata:rsi` and
`rsi` at the series' metadata and calculation versions. Binding, OHLCV
observations, source records, freshness, and quality must match the resolved
scope. The adapter never derives evidence IDs from RSI output. Because the
repository does not yet provide a production RSI-to-C-008 evidence producer,
missing or differently scoped RSI evidence remains `UNAVAILABLE` with
`INPUT_UNAVAILABLE` until a separately approved producer supplies it.

Warm-up and undefined points remain unavailable; stale dependencies remain
stale; inconsistent input scope remains invalid. This adapter does not change
the C-008 or C-007 contracts and does not grant strategy, risk, approval, or
execution authority.
