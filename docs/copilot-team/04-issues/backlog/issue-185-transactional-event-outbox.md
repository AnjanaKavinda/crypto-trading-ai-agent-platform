# Issue 185 — Transactional event outbox and durable publication

GitHub owner: #258.

Implement governed PostgreSQL outbox persistence and a bounded dispatcher so
authoritative state and publication intent commit atomically. Preserve immutable
event identity/provenance, crash recovery, concurrency safety and explicit
failed/quarantined state without claiming exactly-once delivery.

Dependencies: 016-018, 029, 184 and the approved transport adapter boundary.

Out of scope: consumer deduplication, domain producers and live execution.
