# #95 — Personal Spot OOS observations

[ADR-0022](../adr/ADR-0022-spot-oos-protocol-and-result-boundary.md) governs C-071v2. Outputs grant no qualification/execution authority.

```bash
PYTHONPATH=apps/api/src python -m pytest -q tests/backend/test_spot_oos.py
# LINEAGE_TEST_DATABASE_URL must point to disposable PostgreSQL:
PYTHONPATH=apps/api/src python -m pytest -q tests/backend/test_spot_backtest_postgres.py
```

The persisted fixture demonstrates public freeze/replay/readback: synthetic OBSERVED, real RSI zero-trade INCONCLUSIVE, substitution/reuse rejection and correction stability. Synthetic trades test implementation only.

## Workflow

Inject `OOSResearchJournal` with journal_id, authority, clock, declared_complete (default False), and prior_history. Retain this live process-local recorder and all prior access. Completeness covers supplied recorded history, never undisclosed off-system research; hashes cannot authenticate restart/resume.

Build UTC TRAIN/VALIDATION/TEST-or-OOS DataPartitions, then `candidate_from_request`. Freeze partitions/candidates/selection/metrics/warm-up/embargo/valuation/environment with `freeze_spot_oos_protocol`. FIXED selects its sole candidate; VALIDATION_NET_PROFIT requires `run_spot_oos_partition` for every candidate/TRAIN/VALIDATION, then `select_spot_oos_candidate`: highest validation net profit, UUID tie break. Metrics remain separate.

Invoke `run_spot_oos` using these pins and trusted session/registry/store; inspect reasons/metrics/counts. Read back with `resolve_spot_oos_result(bundle, journal=journal)`; log other access via `journal.record_access`.

## Invariants

Decisions use [start,end), bar-close fills (start,end]; inventory starts/ends flat. Frozen warm-up/embargo and PIT cutoffs prevent leakage. Research recording may follow historical candles. Reuse contaminates instrument/windows across IDs, revisions, venues/timeframes. Missing evidence is INCONCLUSIVE; contamination/substitution FAILED. Zero trades cannot pass/invent rates. OBSERVED claims no profitability, independence or intervals.

TRIAL/RESULT receipts bind SPOT_OOS_REQUEST@1: replay inputs, archives, dataset/manifest (including native IDs/versions), execution/parameter/cost pins and timestamps. Returned canonical pins must match before metrics. Readback checks receipts and the bundle's originating request. As-of equals request before access/cache lookup and resolved C-027v3 at construction/readback, including inconclusive outcomes.

C-071v2 binds exact dataset/run/report closure. SHA-256/UUIDv5 excludes ID/own digest; events chain hashes. Limits: 512 events/16 candidates. Exact repeats/corrections preserve prior results; readback needs live issuance. V1 stays unchanged; unknown schemas, v2 qualification and C-071 retention are rejected. No durable journal/API/DDL/provider/trading changes.
