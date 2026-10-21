# ADR-0011: Proposed Binance USDⓈ-M personal derivatives-data scope

## Metadata

| Field | Value |
|---|---|
| Status | Proposed |
| Date | 2026-10-20 |
| Decision owner | Platform Architect |
| Human approver | Pending |
| GitHub issue / PR | [#39](https://github.com/AnjanaKavinda/crypto-trading-ai-agent-platform/issues/39) |
| Open decision ID | OD-0002, OD-0004 |
| Related ADRs | [ADR-0004](ADR-0004-initial-market-data-provider-and-asset-scope.md) |
| Supersedes / superseded by | — |

## Context

Issue #39 has a provider-neutral funding/open-interest normalizer, but a real
Futures source and the remaining basis, liquidation, and positioning semantics
are not approved. ADR-0004 explicitly limits its accepted market-data scope to
Spot; neither Spot approval nor public endpoint access grants Futures permission.

Issue #39 records a narrow proposal for personal research by one user:
Binance USDⓈ-M perpetual BTCUSDT and ETHUSDT, public market data, read-only,
opt-in, with funding and open-interest history as the initial data kinds. The
repository owner handles applicable terms independently. This proposal does
not assert terms, rights, regional reachability, coverage, historical
completeness, or a provider service-level guarantee.

The official USDⓈ-M REST reference documents distinct funding-history,
current open-interest, and open-interest-history endpoints. It states that
open-interest history is limited to the latest month and that periods with no
trades may be omitted. These are implementation constraints to recheck during
preflight, not evidence of data rights or a promise of complete history:
[USDⓈ-M Futures market-data REST reference](https://developers.binance.com/en/docs/catalog/core-trading-derivatives-trading-usd-s-m-futures/api/rest-api/market-data).

The current reference also leaves two normalization details unresolved:

- `GET /fapi/v1/fundingRate` returns `fundingRate` and `fundingTime`, but no
  per-record funding interval. `GET /fapi/v1/fundingInfo` exposes
  `fundingIntervalHours` for symbols with funding-cap, floor, or interval
  adjustments; it is not a historical interval attached to each funding
  record. Do not infer an interval for a history row or apply today's interval
  retrospectively. Preserve interval as unknown unless an independently
  verified, time-bounded source establishes it.
- `GET /futures/data/openInterestHist` describes `sumOpenInterest` as total
  open interest and `sumOpenInterestValue` as total open-interest value, but
  the USDⓈ-M reference does not state their units. Preserve the raw fields
  separately and leave their units unknown; do not label them as contracts,
  base asset, or quote value, convert them, or calculate derived quantities
  until the unit semantics are independently verified.

These endpoint semantics were checked against the official reference on
2026-10-21. Recheck them during implementation preflight because provider
documentation and response schemas can change. This review does not establish
that requests are permitted under applicable terms or reachable from the
owner's region.

## Alternatives

### Option A — Keep the existing provider-neutral fixtures only

Benefits:
- Requires no provider selection, network access, or rights assumption.
- Keeps the bounded funding/open-interest foundation testable.

Costs, risks, and constraints:
- Does not provide current or historical real derivatives observations.
- Leaves #39 incomplete and blocks downstream use of derivatives evidence.

### Option B — Propose a tightly bounded Binance USDⓈ-M personal research adapter

Benefits:
- Matches the specific BTCUSDT/ETHUSDT perpetual proposal already recorded in #39.
- Keeps derivatives acquisition separate from Spot and limits the first real
  data slice to funding and open interest.

Costs, risks, and constraints:
- Requires explicit human approval for OD-0002 and a bounded disposition of
  OD-0004 before any provider request.
- Product coverage, regional reachability, applicable terms, retention,
  available history, cadence, and the USD $100/month total research ceiling
  require owner review and preflight evidence.
- This scope does not settle the meaning or completeness of basis,
  liquidation, positioning, or cross-venue comparisons.

## Decision

**Proposed for human review:** select Option B only for a disabled-by-default,
read-only personal research adapter, limited initially to public funding and
open-interest observations for Binance USDⓈ-M BTCUSDT and ETHUSDT perpetuals.
Do not enable requests or claim permission unless and until the human owner
accepts this ADR and completes the applicable terms and regional-access review.
Funding records must not be annualized or used to calculate interval-specific
funding cost when their applicable interval is unknown. Open-interest values
must retain unknown units until verified; consumers must not compare, convert,
or derive signals from them as though their units were established.

Basis may be added only after the provider's spot/futures reference, price
units, observation-time alignment, contract identity, maturity, and annualized
period are all preserved without inference. Liquidation observations may be
added only with explicit sampling/coverage semantics; sampled records must not
be described as exchange-wide totals. Positioning and cross-venue comparisons
remain unavailable until source compatibility, unit mapping, and coverage are
reviewed.

## Reasoning

This is a proposed sub-scope, not a claim that the entire derivatives-market
decision is resolved. It follows the Master Playbook v2.2 Chat 4 separation of
acquisition, normalization, validation, storage, and interpretation; preserves
the approved provider-neutral C-001/C-002 boundary; and leaves analysis to
Chat 5 issue #61. It does not silently extend ADR-0004's Spot decision.

The proposal uses the smallest derivatives scope already stated in #39 and
does not assume that technical documentation, a public endpoint, or an
existing Spot decision grants permission. The documented one-month OI-history
limit and omitted no-trade periods require explicit coverage gaps; the
normalizer must not fabricate continuity or extrapolate older history.

## Consequences

If accepted, implementation may proceed only for the stated public read-only
funding/OI scope and after a no-cost preflight confirms source availability,
regional reachability, endpoint behavior, and the owner's applicable terms.
Requests remain off by default, bounded by explicit symbol, record, time-window,
timeout, and rate limits. No exchange account key, trading permission,
private/account endpoint, always-on collector, or order capability is allowed.

Store exact source provenance and raw-content digests under the existing
lineage path, while preserving observation, provider, retrieval, ingestion,
and availability times. Report partial, empty, stale, unavailable, or
limited-history results explicitly. Do not convert missing periods into zero
values or continuous series.

No basis, liquidation, positioning, cross-venue comparison, analysis,
strategy, risk, approval, execution, customer distribution, or live-trading
authority is implied. The downstream Chat 5 #61 and later cost/risk work remain
blocked until their own dependencies and evidence are satisfied.

## Contract and traceability impact

| Area | References and impact |
|---|---|
| Playbook requirements | Master Playbook v2.2, Chat 4: preserve derivatives scope and provenance; separate acquisition, normalization, validation, storage, and interpretation; no fabricated coverage. |
| Cross-cutting artifacts | OD-0002 and OD-0004 remain Open. ADR-0004's Spot scope is unchanged. |
| Contracts / events | No shared contract, event, or C-002 schema change proposed. Existing C-001/C-002-compatible normalization and source lineage remain in use. |
| Requirements traceability | GitHub #39; downstream Chat 5 GitHub #61. |
| Versioning / migration | None. No persistence migration is proposed. |

## Safety, security, and failure behavior

No authenticated exchange credentials or secrets are required or permitted by
this proposal. No requests occur before human approval and explicit opt-in.
No orders or trading endpoints are implemented. Reject mismatched symbols,
market type, units, timestamps, malformed or future-dated observations, and
unbounded responses. Preserve provider gaps and unavailable states; fail closed
when source, terms, coverage, or chronology cannot be verified. No live-trading
or customer-facing use is authorized.

## Approval record

Pending human repository owner disposition. Until recorded here, the ADR is
Proposed and grants no implementation or data-use authority.
