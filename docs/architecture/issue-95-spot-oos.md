# #95 — Personal Spot OOS

[ADR-0022](../adr/ADR-0022-spot-oos-protocol-and-result-boundary.md): observation-only C-071v2.

```bash
PYTHONPATH=apps/api/src python -m pytest -q tests/backend/test_spot_oos.py
# Disposable LINEAGE_TEST_DATABASE_URL:
PYTHONPATH=apps/api/src python -m pytest -q tests/backend/test_spot_backtest_postgres.py
```

Inject `OOSResearchJournal` with keyword identity/authority/clock/completeness/prior-history inputs; retain it. Completeness cannot prove no off-system research or authenticate restart.

Use `candidate_from_request` and UTC TRAIN/VALIDATION/TEST-or-OOS partitions with `freeze_spot_oos_protocol`. FIXED selects one candidate. VALIDATION_NET_PROFIT needs `run_spot_oos_partition` for every candidate/development partition then `select_spot_oos_candidate`: highest validation net profit, UUID tie break. Recorder-serialized keyed development trials return the canonical result for exact repeats and reject conflicting duplicates before access. Selection/pre-access revalidate receipts/recomputed trials.

`run_spot_oos` uses trusted session/registry/store. As-of equals request/replay; future expiry cannot exceed request/any replay. One recorder serializes holdout execution through terminalization, so concurrent exact repeats await the canonical cached result. Development ACCESS+TRIAL and holdout ACCESS+RESULT capacity is reserved as a complete sequence before access. Exceptions and cancellation record a sanitized terminal receipt at or after the current journal tail before unused capacity is released; recorded access is never erased. A later non-identical invocation sees the prior terminal result and returns a canonical reuse failure. Replay and metric reasons pass through the shared integrity classifier before status assembly. Inspect reasons/metrics/counts; call `resolve_spot_oos_result(bundle, journal=journal)`. Log other access with `journal.record_access`.

Decisions [start,end), fills (start,end], every partition point-in-time cutoff no later than its own partition end, flat boundary inventory. Reuse crosses identities/revisions. A typed terminal receipt binds outcome/check/reason state and the immutable SPOT_OOS_REQUEST@1 reference; construction and canonical decode derive exact integrity/contamination/outcome closure for OBSERVED, INCONCLUSIVE and FAILED results. Recorded duplicate selection is contamination and produces a canonical FAILED result rather than an internal construction error. Separate integrity/contamination/sample checks: substitution/contamination FAILED, missing/zero samples INCONCLUSIVE; no profitability/statistical/qualification/execution authority.

SPOT_OOS_REQUEST@1 and run/report receipts bind canonical configuration/model/#94 documents (1 MB/report), requiring live issuance/recomputation. Tests cover real producer archives, synthetic positive/real-RSI zero-trade; no profitability evidence.

Identity/bounds/compatibility and deferred scope follow ADR-0022.
