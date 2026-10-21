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

## Deliberately deferred

This first slice validates one completed analyst result; it does not yet launch
analysts, parallelize analysis, add automatic retries, or implement a human
interrupt workflow. Those paths need bounded orchestration adapters and
idempotency semantics of their own. In particular, a human pause must not be
interpreted as approval, and no graph event can authorize trading. This work
does not claim full Chat 5 completion; full-platform dependencies and excluded
domains remain governed by Issue #73.
