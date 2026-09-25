# Issue 188 — Event retry, quarantine, dead-letter and replay recovery

GitHub owner: #261.

Implement retryable/terminal classification, bounded attempts/backoff,
acknowledgement rules, immutable quarantine/dead-letter evidence,
operator-authorized replay and safety escalation. Preserve original event
identity, timestamps and provenance. Never retry indefinitely or blindly.

Dependencies: 017, 186-187 and safety/recovery contracts.

Out of scope: exchange order retry and reconciliation.
