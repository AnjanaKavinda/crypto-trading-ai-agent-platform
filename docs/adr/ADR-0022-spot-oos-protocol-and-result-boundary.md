# ADR-0022 — Spot OOS protocol and result boundary

- Status: Accepted
- Date: 2026-11-11
- Decision owner: AnjanaKavinda; explicit “Approved. Continue” authorization
- Issue: [#95, canonical backlog 093](https://github.com/AnjanaKavinda/crypto-trading-ai-agent-platform/issues/95)
- Baseline: `e71c8c5c1bfd32355d619c046cb76877b6a5f6e4`
- Requirements: [Chat 7 — Quant validation and anti-overfitting](../playbook/01-specification/07-chat-7-quant-validation-anti-overfitting.md), particularly partition, selection, sample and uncertainty controls; ADR-0019 execution boundary.

## Context and impact

C-071 schema 1 uses a UUID dataset version, a positive sample and nonempty
metrics. The merged Spot replay preserves native string C-092 IDs/versions,
dataset digests and reconstruction manifests, and legitimately returns zero
trades. Reinterpreting v1 or inventing a UUID/rate would lose provenance.
Existing qualification consumers accept C-071 schema 1 only.

## Decision

Add C-071 schema 2 in `validation/oos_contracts_v2.py`, with the bounded
coordinator in `validation/spot_oos.py`. Preserve all schema-1 payloads,
identities and readers. Dispatch explicitly by contract and schema; unknown
versions fail closed. No down-conversion, historical rewrite or backfill.

A frozen protocol binds ordered TRAIN, VALIDATION and TEST/OUT_OF_SAMPLE
windows, cutoffs, warm-up, embargo, strategy/parameter candidates, comparable
execution/cost policies, metrics policy and minimum raw trade count. Selection
is either one predeclared fixed strategy with no optimizer or highest exact
validation net realized profit among the completely recorded candidate grid,
with UUID ordering to break ties. TRAIN/VALIDATION cutoffs cannot expose the
holdout. Decisions use half-open windows; bar-close fills may complete at the
right endpoint. Cross-boundary inventory is unsupported.

An injected trusted process-local research journal owns recording order and
clock; freeze precedes selection and holdout access. Historical market times
may precede the research job. Completeness defaults to unproven. Explicit
completeness is a source assumption about the supplied research workflow,
never a proof of absent off-system trials. Exported timestamps/hash chains
alone cannot authenticate or resume a live journal. A host must inject and
retain the same recorder, record relevant prior access and declare completeness
only when established. This issue adds no HTTP route or durable journal store.

Recorded overlapping access/trials contaminate the holdout, including another
protocol, data revision, venue or timeframe over the same instrument window.
New IDs cannot reset supplied exposure history. The public runner reuses #92
archive-bound replay and #94 metrics; it does not implement another simulator,
cost model or formula set. Development and holdout runs remain separate.

The result binds the frozen protocol, exact recorded journal snapshot, C-027v3
runs (including original C-092 dataset and manifest identity), versioned metrics
references, availability states, sample checks and timestamps. Canonical
UUIDv5 identity excludes only its generated ID and own digest. Readback checks
the live recorder's issued result plus exact replay/metrics closure.

Contamination is FAILED; unresolved inputs/history or insufficient samples are
INCONCLUSIVE. OBSERVED means a resolved recorded held-out observation with the
declared raw sample threshold, never statistical qualification. No confidence
interval, independence estimate, probability or profitability claim is added.
Identical pinned requests on the same recorder return the original immutable
result; later market corrections cannot rewrite its calculation.

## Compatibility and retention

Closed lineage codec registration allows canonical inspection. The store's
reference boundary explicitly rejects C-071 v1 and v2 retention; codec support
is not storage approval. No DDL, migration or retained C-071 storage is added.
Schema-1 qualification allowlists stay unchanged and reject schema 2. A later
consumer adapter requires explicit review before qualification, promotion,
risk or approval use. Paper, testnet and live execution remain gated.

## Validation and consequences

Focused tests cover v1 wire compatibility, unknown-version rejection, canonical
roundtrip, retention denial, forged-result rejection, partition/cutoff/policy
checks, complete candidate selection, reuse and incomplete history. Existing
PostgreSQL replay fixtures exercise the public OOS runner and readback with a
labeled synthetic positive trade and authentic production RSI zero-trade case.
No synthetic performance is represented as market profitability evidence.

The journal is bounded to 512 events and the candidate grid to 16 entries.
Durable trust/resume, broader multiple-testing/bias controls, walk-forward,
bootstrap, sensitivity, regime validation and Futures remain later work.
See [usage and limits](../architecture/issue-95-spot-oos.md).
