# ADR-0005: Personal derivatives market-data scope

## Metadata

| Field | Value |
|---|---|
| Status | Proposed |
| Date | 2026-09-28 |
| Decision owner | Platform Architect |
| Human approver | Pending manual review/merge |
| GitHub issue / PR | #39 / pending |
| Open decision ID | OD-0001, OD-0002, OD-0003, OD-0004 (bounded data sub-scope only) |
| Related ADRs | ADR-0004 (Spot-only personal research) |
| Supersedes / superseded by | — |

## Context

Issue #39 now has provider-neutral funding and open-interest normalization
(PR #289). A source must be selected before a real, read-only derivatives
adapter can be built. ADR-0004 authorizes only the Spot data design; it
explicitly excludes derivatives. The owner's present priority is one-person
research under an approximately $100/month total budget, with a usable,
auditable paper-trading path before any customer offering.

The [Binance USDⓈ-M public REST market-data reference](https://developers.binance.com/en/docs/catalog/core-trading-derivatives-trading-usd-s-m-futures/api/rest-api/market-data)
documents funding history and open-interest history at `fapi.binance.com`.
It documents a funding history limit of 1000 and ascending range results;
open-interest history has a 500-record limit and a latest-month availability
window. Funding history does not itself report the interval applicable to
each historical rate. The documented USDⓈ-M open-interest history fields do
not give an unambiguous unit for `sumOpenInterest`. These gaps must not be
filled with a default assumption or by copying COIN-M units.

## Alternatives

### A. Public Binance USDⓈ-M data, narrowly scoped (proposed)

Benefits: one source already used for personal Spot research; public
documentation; BTCUSDT/ETHUSDT perpetuals; no paid aggregator dependency.

Costs/limits: a separate Futures host and product scope, bounded historical
coverage, rate limits, unit and interval ambiguity, regional availability and
owner-managed terms. Source availability does not prove data rights or profit.

### B. Licensed derivatives aggregator

Benefits: potentially broader coverage and clearer commercial rights after
a tailored agreement. Costs/limits: unverified price/rights and provenance
transformations; not the first source within the owner's budget.

### C. Fixtures only

Benefits: no external-data uncertainty. Cost: no actual derivatives evidence
for analysis, so Phase 1 cannot evaluate derivatives conditions.

## Proposed decision

For **personal research by one user only**, select public, read-only Binance
USDⓈ-M **BTCUSDT and ETHUSDT perpetual** market data as the candidate source
for Issue #39. The first network slice may make bounded, explicit-request REST
calls to funding history and open-interest history; no API key, exchange
account, trading endpoint, scheduled collector or customer redistribution is
authorized. The owner handles applicable Binance terms separately. This ADR
does not decide an execution venue, leverage policy, trading-market eligibility,
or wider exchange/asset universe. The broad OD-0001/0002/0003/0004 decisions
remain open outside this narrow data sub-scope.

Do not emit canonical funding observations until the applicable interval for
their timestamps is verified from an authoritative source or an explicit,
reviewed interval mapping. Do not emit canonical OI observations until the
unit for the selected USDⓈ-M field is verified and captured in the adapter
version. Until then, expose a sanitized `UNAVAILABLE`/unsupported capability
for that metric and preserve raw-source identity for review; never label an
unknown quantity `contracts`, base asset or quote notional. A gap, adjustment,
rate limit, incomplete page, changed schema or stale result must stay explicit.
Do not infer exchange-wide liquidation totals from sampled streams; basis and
liquidation coverage need separate source-semantics review in #39.

## Reasoning and implementation sequence

This confines the first actual derivatives feed to the owner's budget and
symbols while preserving the Playbook's futures scope. After approval, build
the adapter behind an opt-in flag, with short timeouts, explicit row/page
budgets, no automatic long backfill, deterministic provider fixtures and an
owner-run one-shot preflight. Verify current symbol metadata and regional
reachability from the owner's connection. Use the already merged #39
normalizer only for metrics with proven units/intervals; do not weaken it.

## Contract and traceability impact

| Area | References and impact |
|---|---|
| Playbook | Chat 4 funding/OI units, source provenance and incomplete-liquidation limits; Chat 5 analysis remains downstream |
| Cross-cutting | OD-0001/0002/0003/0004 stay open outside this sub-scope; C-003 quality and decision provenance still required before analysis |
| Contracts/events | C-001/C-002/C-091 and #35 provider boundary reused; no shared schema or event change |
| Traceability | Issue #39, PR #289, and later opt-in adapter PR; no performance claim |
| Versioning/migration | New provider adapter version only; no database migration |

## Safety, security, and failure behavior

The adapter has no account or order API and remains disabled by default.
Unknown source semantics, invalid timestamps, errors or missing history prevent
normalization for the affected metric. A successful API response is not a
quality verdict, complete market view, strategy qualification, risk approval
or live-trading authority. No secret or raw sensitive response is logged.

## Approval record

Pending human review. This proposal is not implementation authority until
manually accepted and merged by the owner.
