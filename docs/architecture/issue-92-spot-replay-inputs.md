# Issue #92 — per-decision Spot replay inputs

This slice implements the first input-only foundation for the remaining
PERSONAL_SPOT_RESEARCH replay work. Issue #92 remains open.

## Resolution contract

`build_spot_replay_input_journal` accepts an immutable request with a finite,
strictly increasing tuple of decision times. Each decision carries exact C-092
and C-103 SHA-256 pins, its information cutoff, and its required lookback
interval. The interval end must equal the information cutoff; there is no
implicit warmup, forward filling, or fallback to a final-cutoff manifest.

Every decision is independently loaded through `load_validation_dataset` using
the supplied trusted lineage resolver. The persisted dataset and manifest
cutoffs must equal that decision's information cutoff. The loaded closure must
use schema 1 and `historical-selection-v1`; its pinned universe must contain
exactly the declared Spot instrument at the declared venue and be both effective
and available at the cutoff. The usable view contains only finalized OHLCV bars
whose exact lookback coverage is continuous, whose units match the request, and
whose publication, ingestion, retrieval, availability, event, and finality
times do not exceed the cutoff.

The strategy pin contains the C-020 identity, exact C-021v2 ID, semantic version,
and content digest. Resolution uses `StrategyRegistry.resolve_version` with
`as_of=decision_time`. A version created after that decision, one without
complete historical lifecycle state, a non-selectable or research-only
lifecycle, or a version that does not explicitly allow the declared Spot,
environment, timeframe, and BACKTEST scope is unavailable.

## Bounds and deterministic identity

The request must set positive finite limits no greater than 64 decisions, 8,192
total resolved lineage records, and 2,000 records per decision. Each declared
lookback is also bounded by its per-decision record limit. The resolver budget
counts the records returned for each exact C-103 closure; exhaustion fails the
entire request.

Decision records use method `spot-per-decision-replay-input-v1`. Their
canonical preimage binds the request's decision/cutoff/lookback/scope, exact
C-092/C-103 digests and dataset identity, manifest source/revision pins,
selected/usable revision IDs, exact strategy digest, and resolved lifecycle
state. The canonical preimage is limited to 1,000,000 bytes. Decision IDs are
UUIDv5 values derived from their content digests. The journal digest binds the
ordered decision IDs and digests. No wall clock, random identity, provider/model
call, persistence write, or execution call is made.

Any invalid schedule, exhausted budget, missing lineage, hash/schema/cutoff
mismatch, unavailable lookback, or ineligible strategy raises a typed
`SpotReplayInputUnavailable` naming the decision index/time and reason. A
successful partial journal is never returned.

## Boundaries and downstream seam

The returned journal is an internal immutable record, not a C-number or a
published result. It creates no C-023 candidate, C-026 `NO_TRADE`, agent
provenance, execution intent, simulation trace, fill, trade, risk decision, or
approval. It does not interpret strategy prose or execute the Spot scenario
kernel.

The journal supplies exact point-in-time inputs for a separate continuation:
historical analysis/feature production, authentic C-023 or `NO_TRADE` artifacts,
strategy-to-scenario mapping, then canonical trace/fill/trade closure before
C-027v3 publication. This is the seam to the existing #80/#81/#82 and
`NO_TRADE` path; those components are not executed or claimed complete here.
The existing C-027v3 publication guard remains in place. Metrics #94 and OOS #95
remain deferred.

The lineage loader validates the supplied immutable closure, not the truth or
completeness of external provider history. Hash consistency alone cannot prove
that a provider omitted no records. All tests use explicitly synthetic evidence
and make no market-performance claim.
