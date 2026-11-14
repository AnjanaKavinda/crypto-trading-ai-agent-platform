# ADR-0024 — Spot Monte Carlo observation boundary

## Metadata

| Field | Value |
|---|---|
| Status | Accepted |
| Date | 2026-11-14 |
| Decision owner | Platform Architect |
| Human approver | AnjanaKavinda; owner Execution Packet for issue #97 |
| GitHub issue / PR | #97 / implementation PR pending |
| Open decision ID | — |
| Related ADRs | ADR-0018, ADR-0019, ADR-0022, ADR-0023 |
| Supersedes / superseded by | — |

## Context

Chat 7 requires deterministic Monte Carlo and bootstrap analysis. C-072v1 has a
generic result shape but cannot bind the exact archive-backed return series,
sampling dependence policy, units, and terminal observation states needed for
this bounded Spot implementation. The owner Execution Packet for #97 freezes an
additive, offline `PERSONAL_SPOT_RESEARCH` boundary and assigns the Trading
Intelligence Engineer.

## Alternatives

### Option A — Reuse C-072v1

Benefits:

- Avoid a new schema.

Costs, risks, and constraints:

- Cannot bind the exact C-027v3/#94 source closure and deterministic block
  protocol without changing the historical payload and consumers.
- Free-text assumptions cannot safely carry the required units and terminal
  states.

### Option B — Add observation-only C-072 schema 2

Benefits:

- Preserves C-072v1 payloads, identities, and consumers.
- Binds the exact Spot replay, metrics report, policy, source return-series
  digest, resampling protocol, seed, outputs, and timestamps.
- Keeps conditional resampling evidence separate from qualification and trading
  authority.

Costs, risks, and constraints:

- V1-only readers and durable retention must reject schema 2.
- Codec support does not authorize storage or downstream consumption.

## Decision

Adopt Option B for the bounded Spot research profile. C-072 schema 2 is an
immutable, observation-only result. Keep C-072v1 unchanged.

The only input is one verified observed Spot C-027v3 backtest and its exact #94
metrics report. The runtime recomputes and compares the report from the same
bundle; it does not accept caller-provided return arrays. It resamples ordered
net per-timeframe-bar equity returns using non-circular moving blocks with
replacement. Block length, source horizon, method versions, signed seed, PRNG,
index mapping, iteration count, and nearest-rank quantiles are explicit and
identity-bound.

The implementation requires at least 100 complete returns, at least 20
block-length units, a block length from 2 through half the source length, #94
sample sufficiency, and at least one observed trade. It rejects source paths
over 2,000 intervals and preflights the fixed 10,000 paths / 20,000,000
bar-return ceiling before sampling. The last sampled block alone may be
truncated to the original path horizon.

Each path reports terminal compounded return (ratio), maximum fractional
drawdown (ratio), and longest consecutive negative-bar streak (bars). Observed
path values are retained separately. Percentiles use deterministic nearest-rank
2.5%, 50%, and 97.5% quantiles. The 2.5–97.5% range is a conditional percentile
bootstrap range, not a future-performance guarantee.

## Reasoning

The method preserves ordered return dependence only inside sampled blocks. It
does not model longer dependence or regime changes. It assumes no IID trade
shuffle, fold independence, parametric fit, future data, or fold pooling.
Compounding and drawdown use deterministic Decimal arithmetic. Fixed method and
identity versions, an explicit signed seed, and canonical SHA-256/UUIDv5 closure
make identical inputs reproducible.

`OBSERVED`, `INCONCLUSIVE`, and `FAILED` are the only outcomes. Inadequate
samples, missing returns, or exhausted bounds remain `INCONCLUSIVE`; altered,
mismatched, stale, expired, non-Spot, or non-point-in-time evidence is rejected
as `FAILED`. The result never reports `PASSED`, `ROBUST`, or `QUALIFIED`.

## Consequences

- C-072v1 and its consumers remain unchanged; C-072v2 is not connected to C-030,
  C-028, strategy status, learning, risk, approval, or execution.
- C-072v2 is supported only by the closed lineage codec for canonical
  encode/decode. `SqlAlchemyLineageStore` rejects its retention.
- No migration, DDL, API/UI, scheduler, provider, exchange, credential, or
  Futures path is added.
- Trade win-rate/expectancy intervals, intrabar drawdown, sensitivity, regime
  validation, and fold resampling remain out of scope.
- This completes only the bounded Spot research slice, not the Futures
  obligation or the full platform.

## Contract and traceability impact

| Area | References and impact |
|---|---|
| Playbook requirements | Master Playbook v2.2, Chat 7 Monte Carlo/bootstrap requirements |
| Cross-cutting artifacts | C-072 row in the domain registry; C-072v2 version registration; provenance edge from exact C-027v3 and #94 report |
| Contracts / events | Additive observation-only C-072v2; C-072v1 unchanged |
| Requirements traceability | Issue #97 acceptance checklist and `docs/architecture/issue-97-spot-monte-carlo.md` |
| Versioning / migration | Closed schema dispatch; v1/unknown versions rejected by this codec; no migration, DDL, or durable retention |

## Safety, security, and failure behavior

This is deterministic offline analysis over already observed archived data. It
adds no network/provider call, credential, order, approval, risk, qualification,
or execution authority. No missing return is zero-filled, and no input path is
silently truncated. Unknown or invalid evidence fails closed; insufficient
evidence remains inconclusive. The result is not accepted by qualification or
durable-retention consumers.

## Approval record

The owner Execution Packet on issue #97 assigns this bounded profile, freezes
the C-072v2 Spot-only observation boundary, and records the applicable
profile-scoped dependency disposition. Human owner review and manual PR merge
remain mandatory.
