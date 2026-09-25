# Issue 184 — Event-streaming technology ADR (OD-0007)

GitHub owner: #257.

Evaluate Redis Streams, RabbitMQ, Kafka and relevant managed messaging against
the approved event contract's throughput, latency, durability, ordering,
replay, acknowledgement, DLQ, operations, security, cost and deployment needs.
Obtain human ADR approval and update OD-0007 before any concrete adapter.

Dependencies: 018, 029; deployment inputs where material.

Out of scope: broker implementation, domain wiring and trading behavior.
