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
from each `SpotMetaFinding`. Callers pass successful findings to the
existing C-093 `assess_agent_independence` path with the validated snapshot,
quality report, manifest, and bindings. C-093 records observed shared inputs;
it does not establish statistical independence or correlation for this Spot
profile. Shared OHLCV evidence therefore remains explicitly dependent or
unknown. Fan-out count is never a vote count or confidence score.

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
