# Issue #95 — Personal Spot OOS observation

[ADR-0022](../adr/ADR-0022-spot-oos-protocol-and-result-boundary.md) records the
owner-approved C-071 schema-2 decision. This Python workflow composes the
existing archive-bound replay and cost-inclusive metrics engines. It produces
inspectable observations, not OOS_SUPPORTED qualification or execution authority.

## Runnable verification

From the repository root, using the repository's installed development environment:

```bash
PYTHONPATH=apps/api/src python -m pytest -q tests/backend/test_spot_oos.py
```

For the persisted end-to-end example, supply a disposable PostgreSQL database
through the existing `LINEAGE_TEST_DATABASE_URL` integration-test convention, then run:

```bash
PYTHONPATH=apps/api/src python -m pytest -q tests/backend/test_spot_backtest_postgres.py
```

See that fixture for the full public freeze → runner → resolve usage with a real
session, registry, retained archive inputs and metrics policy. Its parameterized
synthetic positive case produces OBSERVED; production RSI produces an honest
zero-trade INCONCLUSIVE result and undefined win rate. Synthetic fixture trades
are test evidence only. The test also rejects reused windows and verifies pinned
readback after later market corrections.

## Invocation and trust boundary

Inject one `OOSResearchJournal(journal_id=..., authority=..., clock=...,
declared_complete=...)` from the trusted research job. Completeness defaults to
False. Populate `prior_history` with all relevant recorded prior access; never
create a fresh empty history merely to clear a used holdout. The recorder owns
event sequence and clock. Caller-authored hashes or timestamps cannot substitute
for its live freeze receipt and issued-result registry. This is process-local:
exporting canonical records does not create an authenticated restart/resume path.
The host must retain the recorder for replay/readback. No API endpoint, persistent
journal, global exposure database or remote attestation service is included.

1. Build ordered `DataPartition` objects: TRAIN, VALIDATION, then TEST or
   OUT_OF_SAMPLE. Provide UTC boundaries and point-in-time cutoffs. TRAIN and
   VALIDATION cutoffs must be at or before holdout start. Final data must resolve
   by its declared cutoff. Set `used_for_optimization=False` on the final partition.
2. Derive each immutable candidate with `candidate_from_request(request)` from
   an existing `SpotBacktestRunRequest`. Pin strategy, parameters, costs and the
   same execution policy except partition period boundaries. Initial inventory
   must be zero and initial capital positive.
3. Call `freeze_spot_oos_protocol(journal=..., window=OOSWindow(...),
   partitions=..., candidates=..., selection_mode=..., metrics_policy=...,
   warmup_bars=..., embargo_seconds=..., mark_equity=..., environment=...)`.
   Fixed mode requires one candidate and records its selection immediately.
4. For `VALIDATION_NET_PROFIT`, call `await run_spot_oos_partition(...)` for
   each candidate's TRAIN and VALIDATION request. Each request has its exact
   partition period and archived inputs. Only resolved replay/metrics trials
   enter selection. Then call `select_spot_oos_candidate(..., candidate_id=...)`;
   the engine verifies the highest validation net realized profit and UUID tie
   break. Missing trials reject selection. Training metrics are not pooled into
   validation or holdout metrics.
5. Call `await run_spot_oos(journal=..., protocol=..., request=holdout_request,
   metrics_policy=..., session=..., strategy_registry=..., lineage_store=...,
   as_of=..., expires_at=...)`. Inspect outcome, reason codes, metric states,
   warnings and raw trade count. Resolve with
   `resolve_spot_oos_result(bundle, journal=journal)`.

Record other relevant research access with `journal.record_access(...)` before
running. Complete supplied history is an explicit host assumption, not proof that
undisclosed off-system experiments did not occur. A local owner with arbitrary
Python access is inside the trusted boundary. Missing completeness is
INCONCLUSIVE. Reusing inspected history remains FAILED even with new protocol
UUIDs, dataset corrections or different timeframe/venue labels over the same
instrument/window.

## Time, sample and identity semantics

Market partition windows are half-open `[start, end)`. Decisions must belong to
that interval. Existing replay's bar-close fills may complete at `end`; fills
must lie in `(start, end]`, and both initial and terminal inventory must be flat.
Warm-up may precede start only within frozen `warmup_bars`; archived analysis
and replay retain their point-in-time checks. Embargo is a minimum gap in whole
seconds between adjacent partitions. Research receipt time is distinct from
historical candle time and need not precede those candles.

C-071v2 embeds each exact C-027v3 result, preserving native dataset string IDs,
versions, digest and manifest digest, and pins each separate metrics report.
Metric values, units, unavailable reasons and warnings come from #94. Sample
size is the raw completed holdout trade count; it is not an effective independent
sample. Zero trades never create a rate or passing sample. An OBSERVED result
meets only the declared sample threshold and recorded integrity conditions;
walk-forward, robustness, selection bias and statistical qualification remain
separate gates.

Protocol and result identities use canonical JSON SHA-256 and UUIDv5; generated
IDs and own digests are excluded from their own identity preimages. Event hashes
include the preceding event hash. Bounds are 512 journal events and 16 candidates.
Identical successful or replay-inconclusive requests on the same live recorder
return their original pinned bundle. Later events/corrections do not revise that
historical result. A new request over the already inspected holdout is rejected.
Canonical serialization alone does not prove a result was issued: readback also
requires the recorder and exact replay/report closure.

C-071v1 remains unchanged. The closed codec accepts versions 1 and 2 and rejects
unknown versions. The retained lineage store explicitly rejects C-071 retention;
no DDL is added. Current qualification readers reject schema 2. This workflow
changes no strategy readiness, risk/approval policy, providers or trading gates.
