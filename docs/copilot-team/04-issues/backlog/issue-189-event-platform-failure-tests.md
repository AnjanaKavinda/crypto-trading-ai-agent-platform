# Issue 189 — Event-platform integration, replay and failure tests

GitHub owner: #262.

Test commit/publish/ack crash windows, duplicates, conflicting identity,
concurrency, ordering gaps, incompatible schemas, poison messages, outages,
retry exhaustion, DLQ inspection, authorized replay and restricted-data
redaction. Prove no duplicate financial side effect.

Dependencies: 184-188.

Out of scope: exactly-once claims and live exchange testing.
