# Spot bias audit observation (Issue #100)

`run_spot_bias_audit` accepts one frozen `SpotBacktestRunRequest` and uses the
existing archive-bound Spot replay entry point and exact result resolver. It
does not accept caller-authored metrics, market data, or replay outputs.

The schema-2 C-094 observation binds:

- the canonical request identity;
- exact C-027v3 result and trace when a trusted replay exists;
- C-021v2 strategy identity;
- C-092 dataset ID/version/digest and native C-101 universe ID/version;
- exact C-102 revision and C-091 source pins plus C-103 manifest digest;
- audit method/version, as-of, creation, and expiry timestamps.

The producer emits the nine C-094 checks once and in the frozen order:
point-in-time, look-ahead, feature/target leakage,
normalization-parameter leakage, survivorship, selection, data snooping,
multiple testing, and universe methodology.

Only point-in-time and look-ahead checks can be supported, and only after the
trusted replay result is resolved and verified. The other seven checks remain
`INCONCLUSIVE` with a category-specific reason; replay success does not imply
those risks were checked. As a result, a complete replay currently remains an
`INCONCLUSIVE` audit.

If replay is unavailable, the result stays bound to the exact request and has no
invented replay result, trace, or digest. Invalid or mismatched pins, provenance,
or chronology fail closed. Every result is deterministic under canonical
SHA-256/UUIDv5 identity rules.

C-094v1 and its consumers are unchanged. C-094v2 is observation-only, is not
accepted by qualification, and cannot be retained by the lineage store. It
grants no strategy, risk, approval, learning, or execution authority. No API,
provider, migration, DDL, or new replay path is introduced.
