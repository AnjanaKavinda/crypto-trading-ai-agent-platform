# ADR-0004: Initial market-data provider and asset scope

## Metadata

| Field | Value |
|---|---|
| Status | Proposed |
| Date | 2026-09-27 |
| Decision owner | Platform Architect |
| Human approver | Pending: AnjanaKavinda |
| GitHub issue / PR | [#281](https://github.com/AnjanaKavinda/crypto-trading-ai-agent-platform/issues/281) / pending decision PR |
| Open decision ID | OD-0003 (market-data sub-scope), OD-0004 |
| Related ADRs | ADR-0001 |
| Supersedes / superseded by | — |

## Context and decision boundary

The platform has a provider-neutral boundary (#35), OHLCV (#36), trade/tick
(#37), and order-book (#38) normalization. No production market-data source,
license, instrument universe, or live ingestion adapter is approved. #282 must
not infer those choices from a public endpoint or this proposed record.

This decision concerns **market data only**. It cannot authorize an execution
venue, order endpoint, exchange credentials, derivatives, on-chain/news data,
strategy, signal, risk, or live trading. OD-0001, OD-0002, OD-0005/0006 and
the wider OD-0003 asset universe remain open. The proposed narrow starting
universe for human consideration is **BTC and ETH spot, one venue, one quote
currency, two exact venue instrument IDs**. BTC/USD and ETH/USD are *candidate
examples*, not approved identifiers or an assertion that a particular provider
offers them under the necessary rights. No other assets, market types or
automatic cross-provider substitution are in this draft scope.

The minimum desired feed is bounded historical/real-time OHLCV and trades,
with a reliable live book only after its provider-specific rules are
compatible. If the owner requires all three data kinds in the first adapter,
the selected feed must satisfy the order-book compatibility gate below.

## Evidence method

Official provider technical and licensing/terms pages were consulted on
2026-09-27. Links below are the evidence, not a promise of commercial rights,
pricing, geographic availability, or a service-level guarantee. "Unknown"
means no sufficient evidence or contract has been supplied; no inference from
public API access is permitted. Technical behavior must be checked again at
implementation because providers change their interfaces.

| Candidate | Verified capability | Boundaries and unresolved evidence |
|---|---|---|
| Kraken Spot, exchange native | [Public OHLC](https://docs.kraken.com/api-reference/market-data/get-ohlc-data), [WebSocket v2 book](https://docs.kraken.com/exchange/api-reference/spot-websocket-v2/book) and [book maintenance/checksum guide](https://docs.kraken.com/exchange/guides/websockets/book-checksum-v2); public spot data does not require an account key according to [Kraken support](https://support.kraken.com/articles/360000919966-how-to-create-an-api-key). | OHLC REST returns at most 720 recent entries and includes an uncommitted candle. [Downloadable OHLCVT](https://support.kraken.com/articles/360047124832-downloadable-historical-ohlcvt-open-high-low-close-volume-trades-data) exists but is a separate historical path, not arbitrary REST backfill. Kraken's [API notice](https://docs-legacy.kraken.com/api/docs/guides/global-intro/) says prior permission is needed for non-personal commercial use of public data; permission for this exact product, storage, AI, display and derived outputs is **unverified**. Book compatibility fails as described below. |
| Binance Spot, exchange native | [Spot REST](https://developers.binance.com/en/docs/products/spot/rest-api) distinguishes public market-data endpoints and a data-only base host. [Official spot stream documentation](https://developers.binance.com/docs/binance-spot-api-docs/web-socket-streams) describes depth updates with update-ID ranges and snapshot/stream reconciliation; this URL is identified as legacy documentation and needs confirmation against current production schema. | Public access is not a license. The [current developer terms page](https://developers.binance.com/en/docs/products/spot/PROD-TERMS-OF-USE) points to region-dependent product terms; no verified permission for our commercial AI/derived-data, storage, redistribution, or Sri Lanka/deployment use was obtained. Exact product scope, current stream rules, historical coverage and contract compatibility are **unverified**. |
| Kaiko, licensed aggregator | [Channel matrix](https://docs.kaiko.com/explore-our-data/subscriptions-channel-availability) lists OHLCV and trades through stream/REST and L2 feeds through subscription-dependent channels. Kaiko describes [exchange redistribution relationships](https://www.kaiko.com/exchange-agreements). | [Pricing/licensing](https://www.kaiko.com/about-kaiko/pricing-and-contracts) is custom and depends on instruments, data kind, granularity, historical/live access and usage. No quote, subscribed tier, terms for this product/AI/derived works/storage, exact venue feed, or provider-specific sequencing evidence exists. A Kaiko feed cannot silently be treated as exchange-native truth or conflated across venues. |
| Coinbase Exchange, exchange native | Public [market-data interfaces](https://docs.cdp.coinbase.com/exchange/concepts/overview) are documented. | [Market Data Terms of Use](https://www.coinbase.com/legal/market_data), updated 2026-08-07, limit use to personal/research or internal entity use and, absent prior express written consent, prohibit third-party distribution of data/derived works and use of market data to develop or operate AI/ML systems. **Not eligible for selection here without verified written permission covering the planned use.** |
| No provider yet | No external dependency, cost, license assumption or fabricated source. | #282 stays blocked; real-time analysis is not claimed. Only synthetic tests and approved foundations continue. |

No quote, licensed scope, provider-specific market availability, current
regional eligibility, or contractual permission has been supplied for any
option. The absence of a visible prohibition is not approval.

## Normalizer and contract compatibility

| Boundary | Required handoff / observed conflict |
|---|---|
| #35 provider protocol | A descriptor and capability record must state provider/schema/adapter/licensing IDs, exact data kinds, historical/realtime support, auth requirement and known/unknown limits. A supported capability is not a C-003 quality verdict. |
| #36 OHLCV | Keep provider open/close times, partial/uncommitted status and revisions. Never treat an in-progress Kraken candle as closed, fill a missing interval, or claim arbitrary backfill from its 720-entry endpoint. |
| #37 trades/ticks | Preserve venue trade identity, exact decimal units, order/time semantics and provenance. An aggregator's transformed data must retain original venue and transformation lineage; do not equate aggregation with a raw venue trade. |
| #38 order book | `BookDelta` requires integer sequence start/end and a provider-specific continuity verifier; one delta cannot repeat a side/price, and state depth cannot exceed 100 or be silently truncated. Kraken v2's [documented book update](https://docs.kraken.com/exchange/api-reference/spot-websocket-v2/book) can repeat the same price in one message, has no sequence field in the documented payload, and its [guide](https://docs.kraken.com/exchange/guides/websockets/book-checksum-v2) requires truncation to subscribed depth. Therefore it **cannot** be wired to #38 by inventing sequence numbers or dropping updates. Binance's documented ID ranges may support a verifier, but snapshot buffering and finite depth need separate proof. Kaiko needs a documented feed-specific proof. |
| C-001/C-002/C-091/C-092 | Canonical observations, point-in-time snapshots, immutable source/licensing identity and reproducible dataset lineage remain required. One C-001 source-record ID does not replace the full book's local source-lineage handoff. No external feed creates a C-003 VALID verdict by itself. |

If a chosen feed cannot meet a normalizer's rules, propose and review a
**separate bounded compatibility change with deterministic provider fixtures**
before #282. Do not widen this documentation PR or silently weaken #38.

## Alternatives and recommendation

### A. Exchange-native spot feed after documented commercial permission

Candidate implementations: Kraken or Binance; select exactly one source,
instrument mapping and data-kind set. Direct provenance and public-data
interfaces may reduce integration and subscription cost. Permission, region,
historical limits and order-book semantics differ by exchange. A lower nominal
API cost does not remove licensing or compatibility work.

### B. Licensed aggregator under an explicit subscription

Candidate: Kaiko. It may simplify historical access and commercial rights
negotiation, with delivery per paid tier. Actual instrument coverage, venue
identity, raw versus transformed observations, L2 channel, latency, price,
storage, AI and downstream display rights require a quote and signed scope.
No license or budget approval exists.

### C. Coinbase under separately negotiated written permission

Technically possible, but its published terms prohibit the intended AI use
absent consent. It is excluded from a default self-service selection.

### D. Defer production source selection

Continue deterministic foundations while obtaining a written permission or
licensed quote and a feed-to-normalizer compatibility proof. This avoids an
unlicensed or silently incorrect live book, but delays #282 and real data.

**Recommendation for this proposed ADR: D for production activation now.**
Evaluate A first for a narrowly internal, data-only spot slice if commercial
rights and terms are confirmed, and B if a priced license better fits the
intended company/end-user use. This is an inference from the current evidence,
not an accepted vendor choice. The owner may choose A/B/C only with the
recorded evidence and exact scope below; no option is selected by merging this
Proposed ADR.

## Decision request and evidence needed for acceptance

The human owner must record in #281 and the ADR:

1. Intended deployment/business model: internal research only versus
   customer-facing product, whether data or derived analytics leave the
   organization, and whether AI/ML consumes the feed.
2. Exact spot provider/contracting entity, allowed location(s) including Sri
   Lanka and deployment region, approved BTC/ETH venue symbols and quote asset,
   supported data kinds and history horizon; no assumption that OD-0002
   execution market scope follows.
3. Written right or applicable subscription terms for commercial access,
   retention, raw/derived use, model development/inference, attribution,
   display/redistribution, and termination/migration; approved cost ceiling.
4. Official current payload and continuity/checksum/depth semantics; a
   provider-specific deterministic fixture proving #36–#38 compatibility or
   an explicit follow-up correction before any incompatible data kind is used.
5. Exact #282 acceptance scope. If OHLCV/trades are approved first and book is
   deferred, human approval must amend #282 rather than treating its existing
   all-kind acceptance criteria as satisfied.

Until these are present, status remains Proposed; OD-0003/0004 remain Open.
The owner may reject or request another alternative without authorizing live
ingestion. This ADR must be updated to Accepted with the approved exact
option, evidence and conditions before #282 starts network integration.

## Consequences, traceability and safety

| Area | Impact |
|---|---|
| Playbook | Chat 4 §§5–16, 34–37, 43–45, 57–60, 92–98, 101–108: provider abstraction, asset/venue identity, point-in-time history, rate limits, source provenance and fail-closed quality. |
| Cross-cutting | OD-0003/0004 linked as Open pending disposition. OD-0001/0002/0005/0006 and data retention/deployment decisions are not resolved. |
| Contracts | C-001/C-002/C-003/C-091/C-092 unchanged. No event or schema version changed by this proposal. |
| Implementation | #282 remains blocked pending accepted decision and compatible data-kind scope. A later bounded adapter owns protocol, cancellation, rate limiting, health and recovery. |
| Migration/exit | Preserve venue, provider, raw-schema, adapter version, licensing reference and immutable dataset/source identity. Switching provider cannot rewrite old datasets or silently mix unlike feeds. |
| Failure | Unknown rights, region, fee, endpoint behavior, sequence, checksum, stale/revised data or schema change blocks the affected ingestion and downstream quality/readiness. No private account or order endpoint, credential, broker, trading authority, fallback or live execution is introduced. |

## Approval record

Pending. No provider, instrument, subscription, commercial use or network
integration is approved by this Proposed record. The human owner must state
the accepted option and exact conditions; update this section, register and
open-decision entries in the approving PR. A manual merge of a Proposed ADR
records research only and does not authorize #282.
