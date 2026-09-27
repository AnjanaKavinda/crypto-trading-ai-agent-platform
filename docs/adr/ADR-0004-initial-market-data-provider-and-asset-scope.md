# ADR-0004: Initial market-data provider and asset scope

## Metadata

| Field | Value |
|---|---|
| Status | Proposed |
| Date | 2026-09-27 |
| Decision owner | Platform Architect |
| Human approver | Pending: AnjanaKavinda |
| GitHub issue / PR | [#281](https://github.com/AnjanaKavinda/crypto-trading-ai-agent-platform/issues/281) / [draft PR #287](https://github.com/AnjanaKavinda/crypto-trading-ai-agent-platform/pull/287) |
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

The owner has clarified that this is an **internal research product now and a
customer-facing product later**, with one internal user initially. Analysis
must use actual, current, quality-checked observations, not synthetic or
unlabelled delayed data. The first affordable feed can cover historical/live
OHLCV and trades; a live book is a separately priced and verified data kind.
If the owner requires all three in the first adapter, the selected paid tier
must satisfy the order-book compatibility gate below.

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
| CoinAPI Market Data, venue-filtered aggregator | [WebSocket](https://www.coinapi.io/products/market-data-api/docs/websocket) carries trade, quote, book and OHLCV kinds; [REST historical OHLCV](https://www.coinapi.io/products/market-data-api/docs/rest-api/ohlcv/ohlcv/symbol_id/history/get) can support bounded backfill. Its [message reference](https://www.coinapi.io/products/market-data-api/docs/websocket/messages) distinguishes exchange time from CoinAPI receive time and documents connection-lifetime sequences. [Published monthly pricing](https://www.coinapi.io/products/market-data-api/pricing) gives Startup $79 (trades/OHLCV), Streamer $249 (adds quotes) and Pro $599 (adds WebSocket book), subject to usage. | One user does not reduce bytes sent to our collector. [Usage policy](https://www.coinapi.io/usage-policy) treats internal research/AI as generally internal, but customer-facing data/analytics and redistribution need a use-case review and possibly a separate agreement. Exact exchange-symbol coverage, regional rights, retention/derived rights, book checksum/sequence behavior, actual GiB, Tier 2 OHLCV usage and historical completeness remain unverified. Standard subscription is **not** an approved customer license. |
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
| CoinAPI book handoff | [CoinAPI book messages](https://www.coinapi.io/products/market-data-api/docs/websocket/messages) have `is_snapshot` and a sequence valid only for the connection; `book5`/`book20`/`book50` are bounded snapshots. Do not treat this connection sequence as a permanent venue sequence or assert end-to-end exchange checksum. After reconnect, obtain a new snapshot and new lineage. Verify a bounded snapshot or delta mapping with real documented fixtures before using #38; any incompatible rule gets its own reviewed correction. |
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

Preferred candidate for a measured internal pilot: **CoinAPI Market Data
Startup**, one named spot venue and at most two exact BTC/ETH symbols, with
historical REST and live trades/OHLCV. It has a published entry price and
explicit internal AI guidance. For a book-based analysis requirement, Pro is
the published book tier; do not imply Startup includes live L2. Compare Kaiko
for a written commercial quote before customer release. Actual instrument
coverage, venue identity, raw versus transformed observations, latency,
retention, AI and downstream display rights require checking the plan and
signed scope. No license or budget approval exists.

### C. Coinbase under separately negotiated written permission

Technically possible, but its published terms prohibit the intended AI use
absent consent. It is excluded from a default self-service selection.

### D. Defer production source selection

Continue deterministic foundations while obtaining a written permission or
licensed quote and a feed-to-normalizer compatibility proof. This avoids an
unlicensed or silently incorrect live book, but delays #282 and real data.

**Recommendation: B, CoinAPI as the first candidate for a one-user internal
research feed; D for production activation until the evidence gates close.**
This is a proposed, conditional route, not vendor approval. Start with
historical REST plus live trades/OHLCV; add L2 only if measurements show it is
needed and the Pro tier plus provider-specific semantics are approved. Request
written rights for future customer display, derived analytics, AI and retention
before launching that mode. If those rights, coverage or budget fail, compare
Kaiko and an exchange-native contract; preserve the adapter boundary and
dataset identity. No option is selected by merging this Proposed ADR.

## Proposed data flow and quality gates

1. A registered, licensed **single venue and exact spot symbols** feed a
   bounded CoinAPI WebSocket subscription. REST supplies documented historical
   intervals and reconnect backfill; neither stream nor REST silently fills a
   missing interval. Capture exchange event time, provider receive time, local
   ingest time, original venue symbol, provider ID, schema and license reference.
2. Validate schema, symbol mapping, numeric units, clock skew, duplicates,
   sequence scope, heartbeat, and reconnect/gap behavior. Store source records
   and reconciliation evidence with immutable lineage; quarantine bad or
   ambiguous messages and reconcile REST versus stream on overlapping closed
   windows. Exchange time may precede provider receipt and local ingestion.
3. Feed #35–#38 normalizers only compatible data kinds, then C-003 quality and
   configurable freshness gates. A provisional candle stays provisional. If a
   source is stale, contradictory, partial or missing, downstream analysis is
   marked unavailable or qualified; it does not manufacture a price or signal.
4. Use point-in-time, versioned observations for feature calculation and
   backtests. Analysis records the dataset/source IDs, as-of time and quality
   verdict. Deterministic validation and human approval remain in front of any
   future execution; this decision provides no order capability.
5. Internal UI displays qualified analysis with source venue and as-of time.
   Customer display/API remains disabled until written rights explicitly cover
   the actual outputs, users, geography and retention. A later second source
   is an independently tagged cross-check, never an automatic mixed price.

This is *near-real-time delivery*, with actual end-to-end lag measured as
`local_ingest_time - exchange_event_time`; no latency SLA or correctness is
inferred from a WebSocket label. Pilot acceptance requires captured p50/p95/p99
lag, gap and disconnect rates, historical coverage, billing bytes, and
documented incident behavior under volatile periods.

## One-person monthly budget (USD, planning scenario)

Public prices checked 2026-09-27. These are **scenario calculations**, not
contractual quotes. They exclude tax, staff time, transaction/exchange fees,
commercial redistribution rights, and any unsupported overage. No subscription
is purchased by this ADR.

| Component | Internal research: trades/OHLCV | With live L2 and licensed live news | Basis |
|---|---:|---:|---|
| CoinAPI Market Data | $79 | $599 | [Startup/Pro published monthly plans](https://www.coinapi.io/products/market-data-api/pricing); Pro is needed for WebSocket book. Startup includes 32 GiB/day Tier 1; Pro 512 GiB/day. Tier 2 OHLCV has separate allowance/rates; meter before committing. |
| Small always-on compute | $24 | $24 | Example [DigitalOcean 2 vCPU/4 GiB Basic](https://www.digitalocean.com/pricing/droplets); sizing is an unvalidated planning assumption, not an approved deployment topology. |
| Weekly backup | $7.20 | $7.20 | 30% of $24 from [published backup rate](https://www.digitalocean.com/pricing/droplets); storage/restore needs testing. |
| Extra storage and bounded AI analysis | $45 allowance | $45 allowance | Internal spending cap, **not** a provider price: $20 storage + $25 metered AI. A model/vendor is not selected here. |
| NewsAPI Business | $0, not included | $449 | Optional [published commercial production price](https://newsapi.org/pricing); news is a distinct OD-0006 decision, not market truth. Its free Developer plan is delayed and cannot run in production, even internally. |
| Planning subtotal | **$155.20/month** | **$1,124.20/month** | Arithmetic only if the stated tiers/allowances fit actual traffic; quotes, overage, tax and customer rights remain additional/unknown. |

For customer-facing release, **monthly cost is not yet knowable**: add a
written CoinAPI redistribution/display and derived-AI license quote (or a
different provider's signed quote), plus customer hosting/egress and any news
rights. The internal $155.20 is not a legitimate customer launch budget. The
pilot must meter GiB/day by channel and REST credits, cap/alert spend and test
whether the chosen plan truly covers both exact symbols during peak activity.
Do not subscribe to news or L2 simply because these estimates list them.

## Decision request and evidence needed for acceptance

The human owner must record in #281 and the ADR:

1. Recorded business model: one-person internal research now; customer-facing
   data/derived analysis later; AI consumes the feed. Specify exactly what
   customers may see and whether raw data, charts, signals or an API leave the
   organization before negotiating rights.
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
