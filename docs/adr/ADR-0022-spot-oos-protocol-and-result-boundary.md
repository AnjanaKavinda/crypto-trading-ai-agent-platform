# ADR-0022 — Spot OOS

Accepted by AnjanaKavinda 2026-11-11 for #95/canonical 093, base e71c8c5c1bfd32355d619c046cb76877b6a5f6e4; Master Playbook Chat 7/ADR-0019.

Preserve C-071v1; add observation-only v2 with native dataset IDs, zero trades, closed codec and retention denial. Freeze partition/cutoff/warm-up/embargo/candidate/selection/cost/metrics/sample policy before access. Reuse #92/#94; separate development/holdout; reject reuse/crossing inventory.

Process-local journal owns clock/order/receipts/issuance. Completeness covers supplied history only; no restart authentication. Construction/decoding binds exact protocol/journal/request/partition/candidate/artifact/cost/data/replay/report/timestamps. Require live authentication/recomputation. UUIDv5/SHA-256 excludes own ID/digest.

Separate contamination/integrity/sample: contamination FAILED, missing evidence/sample INCONCLUSIVE. OBSERVED grants no qualification/profitability/execution authority; correction-stable readback, 512 events/16 candidates. No migration/storage/DDL/API; robustness/Futures downstream, paper/testnet/live gated. [Usage/tests](../architecture/issue-95-spot-oos.md).
