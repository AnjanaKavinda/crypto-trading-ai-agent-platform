# Issue #92 — Spot strategy replay verification status

## Scope and boundary

`run_spot_backtest` is the offline continuation from per-decision replay inputs
to archived analysis, deterministic Spot scenario simulation, and a canonical
C-027v3 result. Its inputs are exact persisted pins and trusted resolvers. It
does not call a provider, model, research API, or exchange. An unavailable or
inconsistent input yields `INCONCLUSIVE`; a scenario is not a qualification,
approval, risk decision, or permission to trade.

The replay uses archived C-006/C-062/C-066 analysis rather than generating new
analysis. Each archived evaluation must have started, ended, and been evaluated
no later than the corresponding decision. Analysis manifests and source/
observation digests must match that decision's exact point-in-time input closure.
The existing setup detector may produce a hypothetical setup, `NO_SETUP`, or
`NO_ORDER`; recorded `NO_TRADE` remains distinct from those outcomes. The
scenario uses explicit version-bound parameters and the configured deterministic
Spot cost adapter. Result readback verifies the C-027v3 artifact closure and its
references.

## Focused coverage in the repository

The `test_spot_backtest*.py` tests cover the archived-evaluation point-in-time
predicate, fail-closed public entry guard, and exact decision-journal validation
at the execution-kernel seam, including overlap deduplication and post-cutoff
revision rejection. Existing adjacent tests provide focused coverage of the
component seams:

- `test_spot_replay_inputs.py` covers deterministic per-decision journal
  identity, exact dataset/source/strategy pin rejection, per-decision cutoff
  behavior, earlier-decision stability after a later correction, and acceptance
  of a selectable C-021 `RESEARCH` lifecycle only when BACKTEST is explicitly
  allowed.
- `test_spot_replay_inputs_postgres.py` persists synthetic lineage and strategy
  lifecycle records, performs read-only replay-input resolution, and checks
  deterministic readback and earlier-decision stability after a later
  correction.
- `test_spot_execution.py` covers synthetic deterministic fills, no-order
  scenarios, invalid/missing execution inputs, and a read-only PostgreSQL
  dataset-loader-to-execution replay.
- `test_wave4_persisted_handoff.py` checks persisted synthetic producer
  handoff/recomposition and artifact reads. Its producer stage uses test-owned
  providers; it is not an end-to-end `run_spot_backtest` fixture.

These are component tests, not evidence that the full strategy replay path has
been exercised. In particular, they do not establish persisted positive
`run_spot_backtest` execution/readback, genuine end-to-end `NO_ORDER` or
recorded `NO_TRADE`, archive-missing/mismatch rejection through the public
runner, or tamper rejection of a persisted backtest result.

## Integrated fixture blocker and remaining tests

A truthful positive persisted fixture must join all of the following using
synthetic records: the per-decision C-092/C-103 closures and historical strategy
lifecycle; a separate execution dataset; persisted C-006 context plus its
matching C-091/C-001-backed analysis snapshot, fanout, evidence and persisted
agent handoff; and exact archive pins whose decision times, cutoffs, lookback
window, bindings, and hashes agree. The current fixtures build these pieces at
different seams, but do not produce that mutually consistent archive/input
closure. The persisted producer fixture can produce synthetic archived analysis
separately, but its generated context bindings/window are not proven to match
the replay fixture's exact pinned per-decision history. Directly composing the
two fixtures would therefore not truthfully establish a persisted positive
offline replay. No provider or model call belongs inside the replay itself.

The required follow-up is to build a fully synthetic archived analysis closure
whose provenance and bindings are derived from the exact per-decision records,
persist it with the strategy and execution closures in an isolated disposable
PostgreSQL schema, then assert repeatable public-runner output, successful
`resolve_spot_backtest_result` readback, `NO_ORDER`/`NO_TRADE`, missing and
mismatched archive rejection, digest/tamper rejection, and no effect on earlier
decisions after a later correction. No market-performance or production
readiness claim follows from these tests.

## Verification report for this change

On the current implementation head, Ruff passed for the affected production
files and the new kernel-journal test. Focused existing strategy, eligibility,
execution, replay-input, and research API regressions passed **151 tests / 68
skipped**; execution and replay-input regressions passed **70 tests / 1
skipped**; the new kernel-journal tests passed **2 tests**. The new
public-entry/timestamp test file was not run after its addition. The required
integrated `run_spot_backtest` PostgreSQL replay, result readback, and acceptance
scenarios remain unverified. Hosted Product/Governance CI and independent R3
review must also run on the final head; no hosted result is claimed here.
