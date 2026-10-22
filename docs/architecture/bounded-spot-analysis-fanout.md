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

The merged Option A decision in PR #405 keeps the C-007 v4/C-008 v2 evidence
closure intact. Before a finding can be emitted, the caller supplies an exact
C-007 manifest, its matching resolved binding, and the C-008 source items
already bound to that C-005 regime. Each item passes the existing resolver
validation, uses the binding's regime method/profile, and covers part of the
RSI inputs. The selected items' combined observation and source IDs must equal
the full RSI input scope. The finding retains those source evidence IDs while
carrying the exact calculated RSI value/unit and the pinned metadata and
calculation versions in its typed fields. It does not claim that a C-008
regime item contains a derived RSI value or create evidence IDs from RSI output.

The RSI calculator accepts the resolver's validated C-003 v2 quality report
and bound source records, so its quality identity can match the resolved C-007
binding. An end-to-end regression test exercises resolution, calculation, and
adaptation together. The adapter still returns an explicit unavailable outcome
when evidence is absent, partial, stale, or outside that exact scope.

Warm-up and undefined points remain unavailable; stale dependencies remain
stale; inconsistent input scope remains invalid. This adapter does not change
the C-008 or C-007 contracts and does not grant strategy, risk, approval, or
execution authority.

`build_spot_rsi14_task` composes the deterministic RSI calculation and the
adapter as one callable `spot-momentum` task. It reads the exact resolved
snapshot, observations, C-003 v2 report, sources, and selected C-008 evidence;
the shared fan-out then preserves its result or bounded unavailable reason and
passes successful findings to C-093. The integration test confirms the shared
OHLCV evidence remains dependent and statistical independence is false. This
derived finding is accepted by C-093 only when its adapter method/version,
RSI metadata/calculation versions, and the resolved source method/profile are
all present in its typed provenance. Other findings retain the existing rule
that their method must be present on their cited evidence.

## Request-path handoff

The local Spot refresh and stored-candle read now compose the validated C-002
snapshot, C-003 v1 report, observations, source records, and approved quality
policy into a request-scoped C-003 v2 report, C-005 regime, C-008 v2 evidence,
and C-007 v4 manifest. The implementation resolves that exact closure before
creating the RSI task and running the bounded fan-out/C-093 assessment. The API
returns the manifest record and digest, C-003 v2 report, C-008 evidence, task
outcomes, and C-093 report under `analysis_fanout`, allowing the caller to
inspect the exact provenance used for the finding.

This is an in-memory, deterministic handoff over validated Spot data already
stored by the existing research path. C-003 v2, C-005, C-008 v2, C-007 v4, and
C-093 request results are not added to durable lineage storage by this slice.
The new C-007/C-008 output is not emitted when quality is invalid/stale, the
regime is in warm-up, dependencies have expired, or exact resolution fails;
the API returns an explicit `UNAVAILABLE` reason. A valid resolved manifest
with an unavailable RSI task remains `PARTIAL` and retains the C-093 dependence
report. The historical C-003 v1 response and existing indicator/analysis
projections remain unchanged.

The request correlation ID is deterministically converted to a UUID for the
fan-out contract without changing the existing HTTP correlation format. No
provider call is added to the read path, no external agent/model is dispatched,
and no retry/checkpoint behavior is introduced. Durable C-007/C-008/C-093
lineage storage and later Docker Desktop end-to-end user testing remain
deferred. This work adds no strategy, signal qualification, risk, approval,
order, paper/testnet, exchange execution, or live-trading authority.
