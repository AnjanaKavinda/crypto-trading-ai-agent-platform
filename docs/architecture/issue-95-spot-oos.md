# Issue #95 — Personal Spot OOS observation

[ADR-0022](../adr/ADR-0022-spot-oos-protocol-and-result-boundary.md) defines
C-071v2 observations. This workflow reuses archive-bound replay and net-cost
metrics; outputs grant no qualification or execution authority.

## Runnable verification

From the repository's installed development environment:

```bash
PYTHONPATH=apps/api/src python -m pytest -q tests/backend/test_spot_oos.py
```

With disposable PostgreSQL in `LINEAGE_TEST_DATABASE_URL`:

```bash
PYTHONPATH=apps/api/src python -m pytest -q tests/backend/test_spot_backtest_postgres.py
```

That fixture demonstrates public freeze → runner → resolve with persisted archive
inputs. The synthetic positive case is OBSERVED; production RSI is zero-trade
INCONCLUSIVE with undefined win rate. Synthetic trades are test evidence only.
It also verifies reuse rejection and stable readback after market corrections.

## Invocation and trust boundary

Inject `OOSResearchJournal(journal_id=..., authority=..., clock=...,
declared_complete=...)` from the trusted job; completeness defaults to False.
Supply all relevant prior access in `prior_history`; new empty history cannot
clear a used holdout. Retain this process-local recorder for freeze receipts,
event order, issuance and readback. Exported hashes/timestamps cannot authenticate
restart/resume. No API, persistent/global exposure ledger or remote attestation.

1. Build TRAIN, VALIDATION, then TEST/OUT_OF_SAMPLE `DataPartition` objects with
   UTC boundaries/cutoffs. Development cutoffs cannot exceed holdout start;
   final data must resolve by its cutoff. Final `used_for_optimization=False`.
2. Use `candidate_from_request(request)` on each `SpotBacktestRunRequest` to pin
   strategy, parameters, costs and comparable execution policy except partition
   boundaries. Require zero initial inventory and positive capital.
3. Call `freeze_spot_oos_protocol(journal=..., window=OOSWindow(...),
   partitions=..., candidates=..., selection_mode=..., metrics_policy=...,
   warmup_bars=..., embargo_seconds=..., mark_equity=..., environment=...)`.
   Fixed mode requires one candidate and records its selection immediately.
4. For `VALIDATION_NET_PROFIT`, call `await run_spot_oos_partition(...)` for each
   candidate's exact TRAIN and VALIDATION request/archive closure. Then call
   `select_spot_oos_candidate(..., candidate_id=...)`: highest validation net
   realized profit wins, with UUID tie break. Missing/unresolved trials reject
   selection; partition metrics remain separate.
5. Call `await run_spot_oos(journal=..., protocol=..., request=holdout_request,
   metrics_policy=..., session=..., strategy_registry=..., lineage_store=...,
   as_of=..., expires_at=...)`. Inspect outcome/reasons, metrics, warnings and
   raw trades. Resolve with
   `resolve_spot_oos_result(bundle, journal=journal)`.

Call `journal.record_access(...)` for other research access. Complete supplied
history is a host assumption, not proof of absent off-system experiments; an
owner with arbitrary Python access is trusted. Missing completeness is
INCONCLUSIVE. Reusing the same inspected instrument/window is FAILED across new
protocol UUIDs, dataset corrections, timeframe or venue labels.

## Time, sample and identity semantics

Decisions use `[start, end)`; bar-close fills use `(start, end]`. Initial/terminal
inventory must be flat. Warm-up is limited to frozen `warmup_bars` and existing
PIT checks. Embargo is the minimum whole-second partition gap. Research recording
time need not precede historical candles.

C-071v2 embeds exact C-027v3 results with native dataset IDs/versions and
dataset/manifest digests, plus separate #94 reports and availability states.
Sample size is raw completed holdout trades, not independent samples. Zero trades
cannot create a rate or pass. OBSERVED meets declared raw sample and recorded
integrity checks only; later statistical/robustness gates remain separate.

Identity uses canonical JSON SHA-256/UUIDv5 excluding generated ID and own digest;
events chain the preceding hash. Bounds: 512 events, 16 candidates. Identical
successful/replay-inconclusive requests return their original bundle despite
later corrections. New requests cannot reuse inspected holdout. Readback
requires recorder issuance and exact replay/report closure, not hashes alone.

Each development TRIAL and final RESULT journal event binds a
`SPOT_OOS_REQUEST@1` reference: a deterministic UUID and SHA-256 of the exact
replay inputs, archive pins, execution dataset/manifest digests, execution and
parameter/cost pins, and replay timestamps. Dataset digests bind native identity
and version. The coordinator reconstructs these pins from the canonical returned
replay and compares them with the originating request before calculating metrics.
Substituted evidence is FAILED. Readback repeats the comparison against the
recorded request receipt; even a preflight-inconclusive result retains that receipt.
The internal bundle retains its originating request for this verification.

The OOS `as_of` must equal the request's `result_as_of` before any holdout access
or cache lookup. When a held-out replay resolves, its C-027v3 `as_of` must also
match; construction and readback enforce this for observed and inconclusive
results alike. Creation/expiry remain the separately pinned research timestamps.

The codec preserves C-071v1 and rejects unknown schemas. C-071 retention is
blocked; no DDL. Qualification rejects v2. Strategy readiness, risk/approval,
providers and trading gates are unchanged.
