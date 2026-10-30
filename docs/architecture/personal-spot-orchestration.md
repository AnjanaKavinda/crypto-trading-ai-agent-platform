# Personal Spot result orchestration

Issue #73 implements the first bounded LangGraph orchestration slice for
`PERSONAL_SPOT_RESEARCH`. The graph accepts an already-produced C-062
`AgentResult`, validates it against trusted task, context, agent/version, route,
tool, evidence, expiry, and exact output-schema bindings, then takes one of three
explicit terminal transitions: `ACCEPTED`, `NO_TRADE`, or `REJECTED`.

```text
PENDING → validate_result → ACCEPTED
                         → NO_TRADE
                         → REJECTED
```

The state carries a correlation UUID, the full typed result and its provenance,
the terminal status, validation time, and a bounded failure reason. Unknown,
expired, mismatched, or malformed results fail closed as `REJECTED`. `NO_TRADE`
remains a valid terminal result.

## Safety and replay behavior

The graph does not call a model, tool, provider, risk service, approval service,
or execution component. Its only node performs deterministic validation and
has no external side effects. Checkpoint replay therefore repeats validation
only; it cannot repeat a model request, tool call, or trading action. No retry
policy is installed. Caller cancellation propagates. The async wrapper applies
a deadline and returns `TIMED_OUT` with the correlation and submitted result
preserved.

Graph construction requires the exact registered
`personal-spot-research@1` agent, rejects any tool-access grant, and ensures the
trusted output-schema allowlist is a subset of that C-061 definition. This
profile remains read-only and has no risk, approval, or execution authority.

## Checkpoint composition

The graph accepts a caller-supplied LangGraph checkpointer. This keeps the graph
usable with in-memory test storage or a separately approved persistent saver
without choosing a storage technology or retention policy here. A persistent
deployment must provide a saver with the required durability, access controls,
and retention behavior before claiming restart recovery. The graph requires a
LangGraph `thread_id` for checkpoint correlation.

## Debate and critic handoff

Issue #75 composes one validated C-062 result and its exact C-066 evaluation
with the existing C-006 v5 Spot context. `compose_spot_debate` revalidates the
C-062 task/context/agent/route/evidence/schema bindings, requires the completed
C-066 record to bind the same result and correlation/trace identities, and
reuses the C-006/C-007/C-008/C-019 validators plus the C-093 owner registry.

The orchestration-local result carries separate bullish and bearish branches
made only from C-009's typed directional components and exact evidence IDs. It
retains C-010 conflicts, C-019 counter-thesis/contradictory evidence/failure
conditions, C-069 uncertainty, and C-093 dependence data through the original
validated C-006 object. Missing directional evidence stays unavailable. A
categorical unresolved conclusion preserves mixed evidence and first-class
`NO_TRADE`; it does not vote, score, infer probability, or choose a winner.

This is a deterministic composition step, not three agent invocations. It adds
no prompt or model calls, side effects, canonical contract/version, strategy
evaluation, risk calculation, approval, or execution authority. A future
agent-generated thesis workflow would need its own registered prompts/routes
and separately validated C-062 outputs before it could feed this handoff.

## Market thesis projection

Issue #83 adds `compose_spot_market_thesis` as a deterministic projection of
the validated debate result. Bull, bear, and base/neutral cases are distinct
typed branches. A branch is available only when its exact C-009 direction has
supporting evidence; contradictory-only and absent branches remain unavailable.
Neutral evidence is never inferred from a missing directional branch.

The thesis retains the original debate envelope, including its exact C-006
context, task/context/correlation/trace IDs, C-010 conflicts, C-019 findings,
C-069 uncertainties, and C-093 dependence report. C-019 failure conditions are
preserved verbatim as unassigned invalidation candidates because the approved
inputs do not bind each one to a particular thesis branch. Assumptions are
explicitly marked as not supplied by the approved inputs; none are inferred
from evidence or narrative. The thesis uses the upstream expiry and adds no
new freshness window.

The projection is compatible with `NO_TRADE` and does not create strategy
setups, candidates, signals, risk decisions, approvals, or execution authority.
It does not produce narrative text, probabilities, expected returns, or
profitability claims.

## Deliberately deferred

This first slice validates one completed analyst result; it does not yet launch
analysts, parallelize analysis, add automatic retries, or implement a human
interrupt workflow. Those paths need bounded orchestration adapters and
idempotency semantics of their own. In particular, a human pause must not be
interpreted as approval, and no graph event can authorize trading. This work
does not claim full Chat 5 completion; full-platform dependencies and excluded
domains remain governed by Issue #73.
