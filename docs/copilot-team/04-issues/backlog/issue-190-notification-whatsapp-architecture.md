# Issue 190 — Notification/WhatsApp architecture (OD-0015)

GitHub owner: #263.

Resolve notification providers and define webhook identity, consent, templates,
delivery state, rate limits, retries, deduplication, privacy/retention, secrets,
audit and outage behavior. Notifications and WhatsApp replies are not approval
or execution authority by default.

Dependencies: authentication, secrets, events, audit, safety and deployment.
