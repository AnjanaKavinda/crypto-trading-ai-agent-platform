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
currency, two exact venue instrument IDs**. BTC/USDT and ETH/USDT are *candidate
examples*, not approved identifiers or an assertion that a particular provider
offers them under the necessary rights. No other assets, market types or
automatic cross-provider substitution are in this draft scope.

The owner has clarified that this is an **internal research product now and a
customer-facing product later**, with one internal user initially and a hard
**$100/month research ceiling**. Analysis
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
| Binance Spot, exchange native | [Spot REST](https://developers.binance.com/en/docs/products/spot/rest-api) distinguishes public `NONE` market-data endpoints; [current spot streams](https://developers.binance.com/en/docs/catalog/core-trading-spot-trading/api/ws-streams/~) document trades, klines and diff depth with update-ID ranges. | Public access is not a license. The [current developer terms page](https://developers.binance.com/en/docs/products/spot/PROD-TERMS-OF-USE) points to product terms; permission for the exact internal AI, retention, customer distribution and Sri Lanka/deployment use must be verified. Regional reachability, exact instruments and contract compatibility are **unverified**. |
| Binance public historical archive | Binance's own [public-data repository](https://github.com/binance/binance-public-data) documents daily/monthly spot klines, aggregate trades and trades, their checksums and the historical timestamp-unit change from 2025-01-01. Daily archives arrive the next day, so use them for history/reconciliation, **not** live analysis. | The repository's MIT license covers its code; it does **not** establish a right to redistribute underlying market data or derived customer outputs. Archive revisions and gaps require versioned ingestion and checksums. |
| Kaiko, licensed aggregator | [Channel matrix](https://docs.kaiko.com/explore-our-data/subscriptions-channel-availability) lists OHLCV and trades through stream/REST and L2 feeds through subscription-dependent channels. Kaiko describes [exchange redistribution relationships](https://www.kaiko.com/exchange-agreements). | [Pricing/licensing](https://www.kaiko.com/about-kaiko/pricing-and-contracts) is custom and depends on instruments, data kind, granularity, historical/live access and usage. No quote, subscribed tier, terms for this product/AI/derived works/storage, exact venue feed, or provider-specific sequencing evidence exists. A Kaiko feed cannot silently be treated as exchange-native truth or conflated across venues. |
| CoinAPI Market Data, venue-filtered aggregator | [WebSocket](https://www.coinapi.io/products/market-data-api/docs/websocket) carries trade, quote, book and OHLCV kinds; [REST historical OHLCV](https://www.coinapi.io/products/market-data-api/docs/rest-api/ohlcv/ohlcv/symbol_id/history/get) can support bounded backfill. Its [message reference](https://www.coinapi.io/products/market-data-api/docs/websocket/messages) distinguishes exchange time from CoinAPI receive time and documents connection-lifetime sequences. [Published monthly pricing](https://www.coinapi.io/products/market-data-api/pricing) gives Startup $79 (trades/OHLCV), Streamer $249 (adds quotes) and Pro $599 (adds WebSocket book), subject to usage. | One user does not reduce bytes sent to our collector. [Usage policy](https://www.coinapi.io/usage-policy) treats internal research/AI as generally internal, but customer-facing data/analytics and redistribution need a use-case review and possibly a separate agreement. Exact exchange-symbol coverage, regional rights, retention/derived rights, book checksum/sequence behavior, actual GiB, Tier 2 OHLCV usage and historical completeness remain unverified. Standard subscription is **not** an approved customer license. |
| Coinbase Exchange, exchange native | Public [market-data interfaces](https://docs.cdp.coinbase.com/exchange/concepts/overview) are documented. | [Market Data Terms of Use](https://www.coinbase.com/legal/market_data), updated 2026-08-07, limit use to personal/research or internal entity use and, absent prior express written consent, prohibit third-party distribution of data/derived works and use of market data to develop or operate AI/ML systems. **Not eligible for selection here without verified written permission covering the planned use.** |
| ATAS desktop analytics | [Free Start plan](https://atas.net/pricing/) and [C# indicator examples](https://github.com/AtasPlatform/Indicators) can support independent chart/volume research. [Indicator API](https://docs.atas.net/en/md_DataFeedsCore_2Docs_2en_20025__ReceivingProcessingData.html) exposes ticks and depth to indicators. | [ATAS says it does not provide its own full online feed](https://help.atas.net/en/support/solutions/articles/72000649936-online-market-data-and-data-feed-in-atas); its Crypto Data connector has limited depth and full crypto depth needs an exchange connection. An indicator extension is not an evidenced standalone data export/redistribution license. Optional cross-check UI, not the agent's source of truth. |
| No provider yet | No external dependency, cost, license assumption or fabricated source. | #282 stays blocked; real-time analysis is not claimed. Only synthetic tests and approved foundations continue. |

No accepted terms analysis, provider-specific market availability, current
regional eligibility, commercial quote, or contractual permission has been
supplied for the intended future customer use. The absence of a visible
prohibition is not approval.

## Normalizer and contract compatibility

| Boundary | Required handoff / observed conflict |
|---|---|
| #35 provider protocol | A descriptor and capability record must state provider/schema/adapter/licensing IDs, exact data kinds, historical/realtime support, auth requirement and known/unknown limits. A supported capability is not a C-003 quality verdict. |
| #36 OHLCV | Keep provider open/close times, partial/uncommitted status and revisions. Never treat an in-progress Kraken candle as closed, fill a missing interval, or claim arbitrary backfill from its 720-entry endpoint. |
| #37 trades/ticks | Preserve venue trade identity, exact decimal units, order/time semantics and provenance. An aggregator's transformed data must retain original venue and transformation lineage; do not equate aggregation with a raw venue trade. |
| #38 order book | `BookDelta` requires integer sequence start/end and a provider-specific continuity verifier; one delta cannot repeat a side/price, and state depth cannot exceed 100 or be silently truncated. Kraken v2's [documented book update](https://docs.kraken.com/exchange/api-reference/spot-websocket-v2/book) can repeat the same price in one message, has no sequence field in the documented payload, and its [guide](https://docs.kraken.com/exchange/guides/websockets/book-checksum-v2) requires truncation to subscribed depth. Therefore it **cannot** be wired to #38 by inventing sequence numbers or dropping updates. Binance's documented ID ranges may support a verifier, but snapshot buffering and finite depth need separate proof. Kaiko needs a documented feed-specific proof. |
| Binance depth handoff | [Current spot stream reference](https://developers.binance.com/en/docs/catalog/core-trading-spot-trading/api/ws-streams/~) documents `U`/`u` update ID ranges and 1000ms or 100ms diff-depth delivery. Use current official snapshot/buffer/restart rules, prove depth and duplicate-level compatibility with captured fixtures, and reject gaps. Do not invent a checksum or silently trim beyond #38's 100-level bound. |
| CoinAPI book handoff | [CoinAPI book messages](https://www.coinapi.io/products/market-data-api/docs/websocket/messages) have `is_snapshot` and a sequence valid only for the connection; `book5`/`book20`/`book50` are bounded snapshots. Do not treat this connection sequence as a permanent venue sequence or assert end-to-end exchange checksum. After reconnect, obtain a new snapshot and new lineage. Verify a bounded snapshot or delta mapping with real documented fixtures before using #38; any incompatible rule gets its own reviewed correction. |
| C-001/C-002/C-091/C-092 | Canonical observations, point-in-time snapshots, immutable source/licensing identity and reproducible dataset lineage remain required. One C-001 source-record ID does not replace the full book's local source-lineage handoff. No external feed creates a C-003 VALID verdict by itself. |

If a chosen feed cannot meet a normalizer's rules, propose and review a
**separate bounded compatibility change with deterministic provider fixtures**
before #282. Do not widen this documentation PR or silently weaken #38.

## Alternatives and recommendation

### A. Exchange-native spot feed after confirming applicable terms

Preferred internal-research candidate under the $100 ceiling: Binance Spot
public data on one venue, likely BTCUSDT and ETHUSDT if those exact instruments
and Sri Lankan/deployment access are verified. Public REST/WebSocket trades,
klines and depth have no separately published subscription fee; historical
daily/monthly archives support repeatable research. Use only `NONE`/public
market-data interfaces, never a trading key. The relevant regional/product
terms and rights to retain data, run internal AI research and eventually show
derived outputs to customers remain unresolved; no claim of a blanket free
commercial license. Kraken is an alternate if its required commercial
permission and book compatibility are addressed.

### B. Licensed aggregator under an explicit subscription

Alternative if direct access, coverage or rights fail: **CoinAPI Market Data
Startup** for live trades/OHLCV ($79/month), but a 24/7 collector, backup and
AI exceed the stated all-in $100 ceiling. Its Pro live-book tier is $599.
Compare Kaiko for a written commercial quote before customer release. Actual instrument
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

**Recommendation: A, Binance public Spot as the first candidate for a
one-user research feed under $100/month; D for network activation until the
terms, region and compatibility gates close.** This revises the earlier
CoinAPI preference in response to the owner's hard spending ceiling. Start
with checksummed historical klines/trades plus public live trades/klines; add
bounded book only after #38 continuity/depth compatibility is proven. Use
ATAS Start as an optional independent visual analysis tool, not an upstream
agent data source. Request written rights for customer display, derived
analytics, AI and retention before any customer launch. If A fails its gates,
reassess scope or budget rather than silently switching venues or substituting
ATAS. No option is selected by merging this Proposed ADR.

The owner's ATAS research-workbench choice is compatible with this route.
The broader comparison proposing Binance + Bybit + CoinGlass should be treated
as a later research roadmap, not as approval to ingest them together in #282:

| Suggested expansion | Decision boundary for the first adapter |
|---|---|
| Bybit/OKX/Deribit | Each added venue requires its own symbol mapping, terms, continuity fixtures and data-quality evidence. No automatic fallback or silently pooled price. |
| Open interest, funding and liquidation streams | These describe derivatives positions/markets, not the approved candidate spot feed. Decide the derivatives data scope separately before combining it with spot analysis. [Bybit's OI endpoint](https://bybit-exchange.github.io/docs/v5/market/open-interest) explicitly covers linear/inverse contracts. |
| CoinGlass Hobbyist | Its [published $29/month tier](https://www.coinglass.com/pricing) is labeled **personal use**; commercial tiers start higher. Do not add it to the baseline budget or infer company/customer rights, endpoint history or suitability for low-latency decisions. |
| Locally collected exchange history | We can preserve a valuable, reproducible research copy, but storing bytes does not transfer ownership or customer redistribution rights. Preserve the source terms and retention constraints with every dataset. |

## Proposed data flow and quality gates

1. After applicable use terms and geography are verified, one registered
   **exchange venue and exact spot symbols** feed a bounded public WebSocket
   subscription. The exchange's daily/monthly archive supplies historical
   klines/trades with checksum validation; REST reconciles bounded gaps.
   Archives arrive the next day, so they cannot repair a live gap in real time.
   Capture exchange event time, local ingest time, venue symbol, provider ID,
   source archive/stream version and applicable terms reference. Do not invent
   a distinct provider-receive timestamp for a direct exchange connection.
2. Validate schema, symbol mapping, numeric units, clock skew, duplicates,
   sequence scope, heartbeat, and reconnect/gap behavior. Store source records
   and reconciliation evidence with immutable lineage; quarantine bad or
   ambiguous messages and reconcile REST versus stream on overlapping closed
   windows. Exchange time may precede local ingestion.
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
lag, gap and disconnect rates, historical coverage, storage growth, and
documented incident behavior under volatile periods.

## Storage and historical data for the research pilot

Keep PostgreSQL (already an accepted foundation) for normalized observations,
quality verdicts, provenance and analysis metadata. Store compressed,
immutable, date/venue/symbol-partitioned source files on the existing local
machine or a single small research host; preserve upstream archive checksums
and our own hashes. Back up encrypted daily partitions and database snapshots
to a separate B2 bucket, versioned with a restore test. A local-only copy is
insufficient for loss/corruption recovery. The [public archive](https://github.com/binance/binance-public-data)
has daily/monthly klines and trades with checksums, so do not pay a vendor to
reconstruct that same approved internal history. Never treat next-day archive
data as live. Historical depth is not supplied by these listed archive kinds:
capture it prospectively only if the order-book feed is approved, and impose
measured retention/cost limits. This does not decide OD-0008/0013/0017's full
production topology, storage technology or retention policy.

## One-person monthly budget (USD, hard ceiling $100)

Public prices checked 2026-09-27. These are **scenario calculations**, not
contractual quotes. They exclude tax, staff time, transaction/exchange fees,
commercial redistribution rights, and any unsupported overage. No subscription
is purchased by this ADR.

| Component | Monthly plan | Basis |
|---|---:|---|
| Binance public Spot market data + historical archive | $0 separate vendor subscription | Public endpoints/archive [documented](https://developers.binance.com/en/docs/products/spot/rest-api); subject to terms, access, rate limits and no customer redistribution claim. |
| Existing research laptop and local PostgreSQL/source files | $0 incremental | Assumes sufficient free disk and intermittent collection; one-user laptop is not 24/7 service. |
| Optional 24/7 small research host | $24 | Example [DigitalOcean 2 vCPU/4 GiB Basic](https://www.digitalocean.com/pricing/droplets), sizing unvalidated. Only pay if always-on collection is needed. |
| Off-site encrypted backup allowance | $5 cap | [B2 starts at $6.95/TB-month](https://www.backblaze.com/cloud-storage/pricing), first 10 GB free; actual GB, egress and requests must be metered. Local working storage cost is excluded. |
| Metered AI-analysis allowance | $25 cap | Owner-set usage cap, **not** a quoted model price or an authorized model selection. |
| Operational/tax/extra data buffer | $15 cap | Owner-set contingency; actual taxes and regional fees unknown. |
| **Planned total with optional host** | **$69/month** | $31 remains under the hard $100 ceiling; stop discretionary spend before overrun. Without host: $45/month. |

The market-data $0 line is an assumption about **no separately published API
subscription fee**, not free permission for every use. If applicable terms
forbid this internal AI workflow or regional access, option A is not viable.
No paid live-news service is in this research budget; official announcements
may be used as separately attributed manual research, but the agent must
report news coverage as absent until OD-0006 selects a licensed feed. A
published production news package alone is [$449/month](https://newsapi.org/pricing).
For customer-facing release, **monthly cost is not yet knowable**: obtain a
written market-data redistribution/derived-output license and a separately
scoped production deployment budget. The $69 pilot is not a customer launch
budget. Record daily storage/bytes, restore tests and any provider costs;
scale back collection or stop at the hard ceiling, never hide an overrun.

## Performance-evidence requirement

The owner's desired >85% trade win rate is a **research target**, never a
property of the feed or a deployment promise. Define win/loss including fees,
spread, slippage, funding (if later relevant) and unresolved outcomes. Report
the full trade count, confidence interval, net expectancy, drawdown and regime
breakdown, not only the win percentage. For example, a strategy winning 85%
of trades at +1 unit but losing 15% at -6 units has expected gross outcome
`0.85*1 - 0.15*6 = -0.05` units before costs. Use separated training and
walk-forward/untouched out-of-sample intervals, then paper-trading evidence.
Do not optimize on the test interval or infer future win probability from an
unrepresentative historical sample. If evidence is insufficient, return
`NO_TRADE`; no live execution is authorized.

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
