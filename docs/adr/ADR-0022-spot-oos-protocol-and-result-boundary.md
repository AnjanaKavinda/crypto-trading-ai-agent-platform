# ADR-0022 — Spot OOS boundary

Accepted 2026-11-11: AnjanaKavinda explicitly approved #95 (canonical 093), baseline e71c8c5c1bfd32355d619c046cb76877b6a5f6e4. Authority: Master Playbook Chat 7/ADR-0019.

Preserve C-071v1; add observation-only v2 for native dataset IDs and zero trades, closed codec dispatch and retention denial. Freeze partition/cutoff/warm-up/embargo/candidate/selection/cost/metrics/sample policy before holdout access. Reuse #92/#94, separating development/holdout and rejecting reused windows or crossing inventory.

The injected process-local journal owns clock/order/receipts/issuance; supplied completeness cannot prove absence of off-system research or authenticate restart. Bind exact protocol/journal/dataset/manifest/replay/report closure; originating request receipts and held-out as-of must match returned pins. Canonical SHA-256/UUIDv5 excludes generated ID/own digest.

Contamination FAILED; missing evidence/sample INCONCLUSIVE; OBSERVED grants no qualification/profitability/execution authority. Preserve correction-stable readback. Limits: 512 events/16 candidates. No migration/storage/DDL/API. Robustness/Futures remain downstream; paper/testnet/live gated. [Usage/tests](../architecture/issue-95-spot-oos.md).
