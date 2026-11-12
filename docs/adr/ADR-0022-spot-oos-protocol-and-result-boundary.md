# ADR-0022 — Spot OOS protocol and result boundary

- Status: Accepted
- Date: 2026-11-11
- Decision owner: AnjanaKavinda; explicit “Approved. Continue” authorization
- Issue: [#95, canonical backlog 093](https://github.com/AnjanaKavinda/crypto-trading-ai-agent-platform/issues/95)
- Baseline: `e71c8c5c1bfd32355d619c046cb76877b6a5f6e4`
- Requirements: [Chat 7](../playbook/01-specification/07-chat-7-quant-validation-anti-overfitting.md); ADR-0019.

## Context and impact

C-071v1's UUID dataset reference and positive sample cannot represent native
C-092 string identities or zero-trade replay. Existing qualification accepts
only v1. Preserve it and add C-071v2; never invent a dataset UUID or rate.

## Decision

Implement `validation/oos_contracts_v2.py` and `validation/spot_oos.py`.
Closed contract/schema dispatch preserves v1 and rejects unknown versions.
No historical rewrite, down-conversion or backfill.

Freeze TRAIN, VALIDATION and TEST/OUT_OF_SAMPLE boundaries, cutoffs, warm-up,
embargo, candidates, execution/cost/metrics policies and minimum raw trades.
Select one predeclared fixed strategy or the highest validation net realized
profit over complete recorded trials, breaking ties by UUID. Development
cutoffs cannot expose holdout. Decisions use half-open windows; bar-close
fills may complete at the right endpoint. Cross-boundary inventory is unsupported.

The injected process-local journal owns clock and event order: freeze, selection,
then holdout access. Historical candles may predate research recording.
Completeness defaults to unproven; host-declared completeness covers supplied
history, never undisclosed off-system trials. Retain the live recorder and prior
access history; exported hashes/timestamps cannot authenticate or resume it.
No HTTP route or durable journal is added.

Overlapping recorded access/trials contaminate the same instrument window across
protocol IDs, data revisions, venues and timeframes. Reuse #92 archive-bound
replay and #94 metrics; keep development and holdout runs separate.

Bind protocol, journal snapshot, exact C-027v3/C-092/manifest and metrics pins,
availability, sample checks and timestamps. Canonical UUIDv5 identity excludes
generated ID and own digest. Readback verifies recorder issuance and replay/metrics closure.
TRIAL/RESULT events bind the originating request digest, including exact archive,
dataset/manifest, replay inputs and timestamps. Returned replay pins must equal
that request; OOS as-of equals the held-out request and any resolved replay.

Contamination is FAILED; unresolved evidence or insufficient samples are
INCONCLUSIVE. OBSERVED meets recorded integrity and raw sample requirements
only. No qualification, independence/interval estimate, probability or
profitability claim. Identical pinned requests return their original result;
later corrections cannot change its calculation.

## Compatibility and retention

Codec support permits inspection, not storage: reject C-071v1/v2 retention.
No DDL/migration. Preserve qualification allowlists rejecting v2; qualification,
promotion, risk or approval consumption needs later explicit review.
Paper/testnet/live execution remain gated.

## Validation and consequences

Tests verify compatibility, integrity and public PostgreSQL positive/zero-trade
paths. Synthetic trades are test evidence only. Bounds: 512 events, 16 candidates.
Durable resume, broader bias controls, walk-forward, bootstrap, sensitivity,
regimes and Futures are deferred. See [usage](../architecture/issue-95-spot-oos.md).
