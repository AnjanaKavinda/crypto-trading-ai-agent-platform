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
- `test_spot_backtest_postgres.py` runs the real public runner in an isolated
  PostgreSQL schema. It joins persisted producer outputs, exact archive pins,
  synthetic per-decision history and execution data, and an explicitly
  BACKTEST-enabled registered strategy. It verifies canonical C-027v3 readback,
  no-order behavior, archive-pin mismatch rejection, artifact tamper rejection,
  and stability after a later source correction.

## Integrated fixture result and remaining blocker

The PostgreSQL test reaches the public runner with mutually bound persisted
analysis and per-decision inputs, and the resulting observed no-order bundle
passes `resolve_spot_backtest_result`. It also confirms that replay itself
makes no model call. The archived producer finding is bullish but has
`FindingReadiness.PARTIAL`; the condition-context builder therefore correctly
omits `spot.finding.<domain>.direction`. The existing condition/setup path
reports `CONDITIONS_UNKNOWN`, so there is no confirmed long setup and no
responsible way to assert an entry, exit, fills, or itemized fill costs from
these authentic archived records. Changing or supplementing the archived
finding to force a setup would invalidate the requested provenance.

The test does not claim a positive trade. A positive replay still requires
authentic archived analysis with a READY, evidence-backed long finding matched
to the exact per-decision C-001/C-091 closure. No model call, fabricated
analysis, qualification claim, or live execution is part of this verification.

## Verification report for this change

The isolated PostgreSQL integration test passes for canonical readback,
no-order, archive mismatch, tamper rejection, and correction stability. It does
not demonstrate positive entry/exit/fills because the persisted producer
finding is PARTIAL. Hosted Product/Governance CI and independent R3 review must
also run on the final head; no hosted result is claimed here.
