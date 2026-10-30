# Strategy setup detection

Issue #82 adds a deterministic runtime gate for the PERSONAL_SPOT_RESEARCH
Spot path. It consumes the immutable registry resolution, #80 condition result,
#81 eligibility result, C-006 v5 MarketContext, and the same authoritative
C-007/C-003 resolved Spot binding that produced C-022.

## Outcome and candidate

`evaluate_strategy_setup()` returns a runtime-local
`SetupDetectionEvaluation` with one of:

- `SETUP_DETECTED`, carrying the existing C-023 `SignalCandidate`;
- `NO_SETUP`, for a deterministic failed gate;
- `INSUFFICIENT_INPUT`, for unknown, stale, unavailable, or mismatched input.

No candidate is produced unless C-021 identity/hash, C-006/C-007/C-003
provenance, #80 context/strategy binding and `PASS`, and #81 `ELIGIBLE` with a
current exact C-022 all match. C-022's C-003 ID must equal the report in the
resolved Spot binding. C-009/C-010 quality references, when present, must bind
to that same report. Candidate expiry is the earliest expiry across the
condition context/result, C-022, C-006/C-009/C-019, C-007, and resolved Spot
dependencies.

Direction is accepted only from passed #80 `EQUALS` conditions on exact
allowlisted `spot.finding.<domain>.direction` C-009 features. Opposing passed
direction conditions, no directional condition, stale evidence, or evidence
not present in the current C-006/C-007 chain fails closed. C-009 supporting
evidence for the chosen direction is carried as support; opposing support,
C-009 contradiction, and C-019 contradictory references are retained as
contradictory evidence.

Entry, invalidation, and target text is copied as conceptual C-021 metadata and
references the exact C-021 version. No prices or numeric trade parameters are
derived. `analytical_confidence` and `evidence_strength` remain zero as in the
Chat 6 C-023 example: this layer computes neither confidence nor an evidence
score. This is not a qualification decision or profitability claim.

The existing C-023 is sufficient for confirmed candidate output. No-setup and
insufficient-input results are runtime-local and create no C-023 or C-026.
Market Thesis (#83) is not an input or a gate; it cannot override deterministic
condition or eligibility results.

## Authority boundary

This module creates only a research `SignalCandidate` with lifecycle
`CANDIDATE` and setup state `SETUP_CONFIRMED`. It does not construct an
evidence package, qualify the candidate, create a qualified Signal or NO_TRADE,
calculate statistical metrics, perform risk/approval, create orders, or
execute. Chat 7 remains authoritative for statistical validation.
