# Issue 187 — Durable consumer inbox and general event idempotency

GitHub owner: #260.

Provide atomic durable identity claim plus side-effect semantics for
at-least-once event delivery. Identical duplicates are safe; conflicting reuse
is rejected/quarantined; concurrency, crash recovery, retention and audit
evidence are explicit.

Dependencies: 016, 018, 029 and 186.

Out of scope: execution-command idempotency owned by Issue 119.
