# Issue 186 — Production event transport adapter and lifecycle

GitHub owner: #259.

Implement the approved broker behind Issue 018 protocols with explicit lazy
startup/shutdown, bounded publish/consume, acknowledgement, backpressure,
ordering-scope, schema validation, security and health semantics. Never fall
back to an in-memory production bus.

Dependencies: 018, 029 and approved Issue 184 ADR.

Out of scope: outbox/inbox, business consumers and financial retry policy.
