# trading_platform_api package skeleton

This package provides the FastAPI backend foundation, bounded PostgreSQL persistence, and the local-only personal Spot research API.

## Scope in this issue

- Defines the importable `trading_platform_api` package in `apps/api/src`.
- Provides `create_app()` and module-level `app` ASGI objects.
- Uses static non-secret application metadata (title and version).
- Adds typed runtime context settings for deployment environment and operating mode.
- Adds deterministic standard-library structured logging primitives in
  `trading_platform_api.structured_logging`.
- Adds read-only `/health`, `/health/live`, and fail-closed
  `/health/trading-readiness` operational endpoints.
- Adds a lazy PostgreSQL async persistence foundation in
  `trading_platform_api.persistence`.
- Adds an app-local Alembic migration baseline under `apps/api/migrations`.
- Adds the immutable C-060 audit-event model, PostgreSQL table, and
  insert/flush-only store foundation in `trading_platform_api.audit`.
- Adds a broker-neutral immutable event envelope and narrow asynchronous
  publisher/consumer protocols in `trading_platform_api.events`.

## Selected persistence foundation

- **Relational system of record:** PostgreSQL
- **Application persistence/session layer:** SQLAlchemy 2.x async
- **PostgreSQL async driver:** `asyncpg`
- **Schema migrations:** Alembic

These components provide configuration parsing, engine/session factories, and a narrow async transaction scope. The Spot research path adds only immutable canonical lineage records and an append-only API read-model index; it does not add startup database connections or live-trading behavior.

## Configuration

- `TRADING_PLATFORM_ENVIRONMENT`: `dev`, `test`, `staging`, `prod` (default: `dev`)
- `TRADING_PLATFORM_MODE`: `research`, `backtest`, `paper`, `shadow`, `testnet`, `live-supervised` (default: `research`)
- `ENABLE_LIVE_TRADING`: `true` or `false` (default: `false`)
- `ENABLE_AUTO_EXECUTION`: `true` or `false` (default: `false`)
- `ENABLE_ADAPTIVE_STRATEGIES`: `true` or `false` (default: `false`)
- `ENABLE_LEARNING`: `true` or `false` (default: `false`)
- `ENABLE_EXPERIMENTS`: `true` or `false` (default: `false`)
- `DATABASE_URL`: required only when persistence or Alembic is explicitly invoked; must use the SQLAlchemy async PostgreSQL form:
  `postgresql+asyncpg://placeholder_user@db-host:5432/placeholder_db` (placeholder only; supply secrets through the environment)

Configuration values identify runtime context and eligibility only, and do not grant trading or execution authority.

## Lazy connection and secret handling

- Importing `trading_platform_api`, importing the persistence package, or creating the FastAPI application does **not** require `DATABASE_URL`.
- Engine construction is explicit and lazy; no PostgreSQL connection is opened during module import or FastAPI app creation.
- Database configuration fails closed only when persistence is explicitly requested.
- Database settings and configuration errors redact secret-bearing connection details; passwords, full URLs, and query-string secrets must not appear in reprs or deterministic error messages.

## Alembic usage

The committed `apps/api/alembic.ini` file stores no URL or credentials. Online and offline commands read `DATABASE_URL` at runtime through the same sanitized persistence configuration.

Offline SQL generation:

```bash
DATABASE_URL='postgresql+asyncpg://placeholder_user@localhost:5432/placeholder_db' \
alembic -c apps/api/alembic.ini upgrade head --sql
```

Revision graph inspection:

```bash
alembic -c apps/api/alembic.ini heads
```

Online migration execution against an explicitly supplied environment:

```bash
DATABASE_URL='postgresql+asyncpg://placeholder_user@db-host:5432/placeholder_db' \
alembic -c apps/api/alembic.ini upgrade head
```

The baseline migration is intentionally schema-empty. It creates **no** production tables, extensions, enums, indexes, triggers, seed data, or other domain objects.

The next revision creates only `audit_events` and its declared constraints and
indexes. Audit records are append-only at the application-store boundary:
the store exposes append only, joins the caller-owned transaction, and never
commits, updates, deletes, upserts, or silently falls back to another store.
Corrections create a new record with `supersedes_audit_id`; they never rewrite
history.

Downgrading the audit revision is intentionally blocked because dropping the
table would destroy historical evidence. Hash chaining/tamper verification is
not part of this foundation and remains owned by Canonical Issue 135.

## Deferred decisions and operating-mode impact

This foundation does **not** resolve time-series technology, production topology, replicas, sharding, pooling/tuning, retention, tenancy, vector storage, or domain schema ownership. Those decisions remain governed and deferred.

Production audit retention, database roles/grants, audit search/export,
automatic instrumentation, and integration into safety/trading workflows are
also deferred to their owning governed decisions and issues.

The event foundation defines metadata and interfaces only. It does not provide
or claim broker delivery, an in-memory production bus, transactional outbox or
inbox behavior, durable deduplication, acknowledgement, retry, dead-letter,
quarantine, replay, routing, serialization, startup wiring, domain consumers,
or trading integration. Those capabilities have explicit governed owners in
canonical Issues 184-189. An event is evidence that something occurred; it is
never risk approval, human approval, trading readiness, or execution authority.

Persistence availability does not imply trading readiness, execution authority, or live-trading enablement. Live trading remains disabled until later approved phases add the required risk, approval, execution, audit, and reconciliation controls.

## Binance Spot personal-research adapter (Issue #282)

`trading_platform_api.market_data.binance_spot` provides a public, read-only
Binance Spot provider for `BTC-USDT-SPOT` and `ETH-USDT-SPOT` at venue
`BINANCE-SPOT`. It supports bounded UTC klines and recent raw trades over REST,
bounded raw trade/kline WebSocket sessions, and checksum-verified daily kline
and raw-trade archives. It uses the existing #35–#37 provider and normalizer
contracts. It is not wired to the API application or any background job.

Collection is **off by default**. Before creating an enabled settings object,
record the applicable personal-use terms/retention review, Sri Lankan access
review and opt-in integration evidence as non-secret references. The adapter
checks live Spot symbol metadata before every collection session. It supports
only fixed public Binance market-data hosts and never accepts an API key or
calls private, account or order endpoints. These references are assertions by
the operator; code cannot establish legal rights or geographic eligibility.

```python
from trading_platform_api.market_data.binance_spot import (
    BinanceSpotArchive, BinanceSpotProvider, BinanceSpotSettings,
)

settings = BinanceSpotSettings()  # disabled; no import-time I/O
# After the three reviews are recorded separately, construct an enabled
# settings object with their non-secret record IDs and call fetch/stream/day.
```

The provider `MarketDataRequest` uses `BTC-USDT-SPOT` or `ETH-USDT-SPOT`,
`BINANCE-SPOT`, and `OHLCV` or `TRADE`. Its timeframe comes from
`BinanceSpotSettings` (default `1m`), because the existing provider request
does not carry a timeframe. A REST call is limited to ten pages of at most
1000 rows; a single historical window is at most 90 days, and the requested
range must fit its record budget. Recent `/api/v3/trades` has no historical
cursor, so time-ranged raw trades use the separate checksummed daily archive
reader. Archive data is available only after the daily publication. Archive
reader batches have 1000 or fewer rows and reject a day beyond its explicit
record/byte budgets. Re-download and checksum comparison expose archive
revisions; no persistent dataset revision registry is created here.

WebSocket sessions subscribe to one approved raw stream and close after the
explicit message budget. A disconnect before the first message gets at most
two bounded retries. Disconnect, idle timeout or invalid data after emission
invalidates that session; a caller must reconcile explicitly before starting
another session. Each batch preserves source hashes and timestamps, but a
successful batch is not a C-003 quality verdict, data persistence, continuous
live coverage, trading readiness or permission for customer display.

Deterministic fixtures run in normal CI:

```bash
python -m pytest -q tests/backend/test_binance_spot_adapter.py
```

No external-data test runs by default. A later opt-in integration session must
record terms and regional eligibility, confirm live BTCUSDT, ETHUSDT,
BNBUSDT, SOLUSDT and XRPUSDT metadata,
exercise public REST and WebSocket endpoints, inspect archive checksum and
microsecond timestamp behavior, and retain a non-secret evidence reference.
Until then, do not enable collection. Historical gaps, archive revisions and
stream disconnects require explicit reconciliation before analysis can claim
continuous data. Order books, futures, credentials and execution remain outside
this adapter.

### Point-in-time reconstruction (Issue #45)

`market_data.point_in_time.reconstruct_pinned_snapshot` validates an exact
C-002 snapshot against its C-001 observations, C-091 sources and C-092 dataset.
The caller supplies a trusted lineage digest from the original experiment
manifest and an explicit `survivorship_sensitive` policy. Snapshot membership,
dataset version/cutoff, schema, venue and cross-record chronology must match.
The function returns immutable evidence in snapshot order, or raises
`PointInTimeError`; it never substitutes a newer version or partially succeeds.

Source retrieval/availability and observation ingestion/availability must be
no later than the historical cutoff. Newly downloaded old candles therefore
cannot establish what this platform knew before download. OHLCV also requires
trusted `(market_data_id, interval_end)` finality evidence, just as C-003 needs
external finality because C-001 does not encode it. Embedded observations are
checked against their source availability. This verifies supplied provenance
claims and an independently supplied lineage pin, not raw-content hash preimages.

The original API retains its conservative `survivorship_sensitive=True` rejection;
passing `False` permits fixed-universe research only. Use the additive
`market_data.history_selection.reconstruct_history` API when approved C-101
HistoricalUniverse and C-102 ObservationRevision evidence is available. Supply
the exact universe and C-092 dataset, authentic complete revision/source
history, cutoff, and independently trusted universe/lineage hashes. C-101
describes a complete named universe at that time, not today's watchlist.

The new API selects only revisions available at the cutoff, follows explicit
supersession ancestry, and rejects ambiguous roots, forks, cycles, missing
parents, backdated evidence and incomplete member coverage. A missing member's
observations cannot be silently dropped. A genuinely empty, explicitly complete
universe produces an empty selection. Universe intervals are half-open.
Candle revisions require trusted finalized interval ends. Observation keys
must retain one event time and encode provider event/interval identity.

The result includes C-103 ReconstructionManifest with selected revision IDs,
eligible ancestry/source hashes, universe hash, dataset reference and selection
policy version. Input ordering cannot affect the result. Later unavailable
revisions and later delisting cannot rewrite the earlier pinned reconstruction.
This proves consistency of supplied evidence, not provider truth or completeness
of a caller's omitted records. No authenticated ingestion of C-101/C-102 exists
yet; fabricated completeness/finality declarations are never acceptable.
Per-timeframe completeness and other quality checks still require C-003.
Existing C-001–C-100 payloads and the exact-pin API are unchanged. #46 owns
durable provenance storage; these controls do not implement a full backtester.

### Durable lineage and archive evidence (Issues #46–#47)

`lineage.store.SqlAlchemyLineageStore` persists C-001/C-002/C-003,
C-091/C-092 and C-101/C-102/C-103 records in PostgreSQL. Apply the reviewed
`0005_market_payload_archive` migration with the existing Alembic configuration:

    python -m alembic -c apps/api/alembic.ini upgrade head

Supply `DATABASE_URL` through the existing configuration mechanism; do not
commit or print credentials. Construct the store with an explicit async
session inside the existing transaction context. Append sources first, then
observations/datasets/universes, revisions in ancestry order, then
snapshots/manifests and their C-003 quality reports. Every referenced record must already exist in the same
transaction or be committed. No automatic commit, migration or connection
occurs on import.

New C-001 anchors keep identity and evidence digests in `lineage_records`;
canonical C-001 bytes are stored in `lineage_market_payloads`. Migration 0005
backfills this hot table only for legacy Binance Spot OHLCV rows in the five
approved instruments, without removing those original documents. Other C-001
types, venues and instruments remain inline. `get(key)` remains compatible with inline rows,
then reads the hot payload, then an archive object when configured. Each path
checks the document digest, decoded identity, evidence digest and lineage
edges.

`append_validated_market_snapshot(...)` appends source records, ordered
observations, their C-002 snapshot and exact C-003 report in that order. It
rejects any non-VALID report, identity/cutoff mismatch, source mismatch or
observation order mismatch before writing. The caller must obtain C-003 from
the reviewed quality assessor and own the surrounding transaction. This
helper does not itself authenticate provider data or create a quality verdict.

`append(record)` returns its stable `LineageKey`; identical retries succeed
without mutation, while conflicting content under one identity/version raises
`LineageError`. `get(key)` returns the exact validated typed record, checking
canonical document/content hashes and stored edges. `resolve((key, ...))`
resolves and verifies exact dependencies with a hard maximum of 1,000 records;
pass a lower `maximum_records` when appropriate. Returned objects can be fed
directly into the existing #45 reconstruction APIs. Records use canonical
`wire-1` payloads; unsupported versions and unknown types are rejected.

`archive_market_data_batch(...)` publishes at most 500 same-day, same-venue,
same-instrument, 90-day-old C-001 records as deterministic gzip JSONL plus a
content-checked manifest. It reads both objects back, verifies the complete
bundle and member digests, and appends the database manifest and
`COLD_VERIFIED` events in the caller's transaction. It never removes a hot
payload. The filesystem object-store adapter is for local development and
tests. The optional Backblaze B2 adapter is available with the `archive`
dependency extra; it requires `TRADING_PLATFORM_B2_ENDPOINT_URL`,
`TRADING_PLATFORM_B2_REGION`, `TRADING_PLATFORM_B2_BUCKET`,
`TRADING_PLATFORM_B2_APPLICATION_KEY_ID`, `TRADING_PLATFORM_B2_APPLICATION_KEY`,
`TRADING_PLATFORM_B2_ENCRYPTION_ACTIVE_KEY_ID`, and
`TRADING_PLATFORM_B2_ENCRYPTION_KEYS_JSON`. The endpoint must be the HTTPS S3
endpoint for the configured region, bucket versioning must be enabled, and the
keyring contains base64-encoded 32-byte AES keys keyed by key ID. Keep all
credentials and encryption keys in a secret manager; no B2 credentials or
automatic production selection are configured by this adapter. Phase 1 uses
the local filesystem and encrypted local backup adapter. Cloud configuration
and cloud cost controls are deferred by ADR-0007.

The migration keeps lineage edges and identity/digest anchors append-only. A
narrow C-001 document relocation is allowed only after cold membership and
`COLD_VERIFIED`/`HOT_REMOVED` evidence exist. Hot payload deletes have the same
database guard. A one-shot local `prune-hot` command requires explicit operator
confirmation, a fresh verified backup, a successful disposable restore, and
cold resolver/reference checks before source removal; it is never scheduled
or run automatically. See `docs/operations/issue-47-backup-bundle.md`. This is
not protection against a database administrator disabling triggers or
replacing backups.
Caller-owned transactions determine batch atomicity. Concurrent identical
inserts use PostgreSQL conflict handling; conflicting content is rejected.
Database transaction failures propagate without blind retries.

The store retains normalized evidence, provider/adapter/schema and usage
references, all contract timestamps, revision links and content digests. Cold
archive writes and fail-closed reads are implemented behind an immutable object
store port; cloud B2 configuration and automated retention remain deferred.
Production topology, continuous ingestion and trading readiness also remain
out of scope. Downgrading restores inline C-001 documents
from hot payloads and fails if a cold-only restore is required; use only a
disposable database or an explicitly approved restore plan.

Product CI uses an isolated PostgreSQL 16 service to exercise migrations,
readback/reconstruction, conflicting concurrent inserts, rollback and mutation
rejection. Locally, integration tests require `LINEAGE_TEST_DATABASE_URL`
pointing to a disposable loopback database named `lineage_test`; without it,
those tests are explicitly skipped and must not be reported as database proof.
The fixture upgrades and downgrades that database. Never point it at retained
research data. The CI service's trust authentication is for that disposable
runner only and is not a deployment configuration.

### Owner-authorized one-shot check

Issue #282 records the owner's personal-use assumption and public symbol
preflight. From the repository root, on a machine with permitted Binance
access, install the package with `python -m pip install -e .` and run:

    python -m trading_platform_api.market_data.binance_spot.smoke --terms-ref issue-282-terms-review-20260928 --region-ref issue-282-region-preflight-20260927 --preflight-ref issue-282-region-preflight-20260927 --archive

This command creates an enabled provider for this invocation only. It checks
two closed one-minute candles and two recent trades for each of five approved symbols,
consumes two BTCUSDT trade-stream messages, and optionally checks one
published BTCUSDT daily kline archive (two UTC days old) with the adapter's
checksum verification. It stops after bounded reads or a 120-second deadline.
It prints statuses and counts, not market payloads or credentials; a failed
or incomplete check exits nonzero. Remove `--archive` if archive-use rights
remain unresolved.

Record sanitized output, UTC run time, PR commit, connection region, and any
error code in Issue #282. The preflight reference starts the check; it does
not claim that integration already passed. No startup wiring, scheduled
collection, trading, or default opt-in is introduced.

## Provider-neutral derivatives foundation (Issue #39)

`market_data.derivatives.normalize_derivatives` accepts bounded funding and
open-interest observations for one explicit instrument, venue, market type
and contract per call. Funding rates are signed fractions **per supplied
interval**; open interest requires an explicit `contracts`, `base_asset` or
`quote_asset` unit. The result carries C-091 source hashes, C-001 observations,
C-002-compatible `DerivativesData`, and a separate contract/provider-event
identity handoff. This transforms caller-supplied data; it is not a provider
parser or a data-quality verdict. Exact duplicates are tracked within one
batch only. Empty input is empty; gaps are never interpolated.

The batch rejects mixed instruments/contracts, provider identities, unknown
units, invalid time order, non-finite values and over-budget payloads. No
network source, historical coverage, store, liquidation totals, basis
reference, quality assessment, analysis, orders or execution is added. A
read-only derivatives adapter requires its own approved market/product
decision, concrete source semantics and owner-run integration evidence.
Tests use synthetic fixtures:

```bash
python -m pytest -q tests/backend/test_derivatives_normalization.py
```

## Deterministic Spot OHLCV quality (Issue #44)

`market_data.quality.assess_data_quality` evaluates a supplied C-002 snapshot,
its C-001 closed-candle observations and C-091 sources under an explicit
versioned `DataQualityPolicy`. Its half-open UTC coverage window, candle
interval, required OHLCV metrics and bounds, recent-slot freshness window and
missing-interval allowance are caller-supplied. It emits C-003 only when all
seven dimensions have measurable denominators. The caller must persist the
policy version/parameters alongside the report for reproducibility; C-003 has
no policy-version field. Nothing is fetched or made authoritative for risk.

| C-003 dimension | Numerator / denominator |
|---|---|
| Completeness | supplied required metric cells / required cells in supplied observations |
| Freshness | covered recent expected candle slots / expected recent slots |
| Accuracy | supplied candles passing explicit bounds, OHLC relationships, positive price, nonnegative volume and common price unit / supplied candles |
| Consistency | supplied candles matching identity, time order/alignment, closed-time retrieval and finality evidence / supplied candles |
| Source reliability | supplied candles with matching C-091 source and snapshot provenance / supplied candles; measures **provenance presence**, not exchange honesty |
| Coverage | observed valid slots / declared expected slots |
| Continuity | adjacent pairs of observed slots / adjacent pairs of expected slots |

One provider's own consistency is measurable; independent source agreement is
**not** assessed. If the policy requires independent comparison or a generic
caller cannot supply raw-candle finality evidence, assessment fails with no
C-003 verdict. C-001 does not preserve `is_final`. For the pinned Binance
Spot adapter v1 only, `assess_complete_binance_spot_batch` accepts a COMPLETE
OHLCV batch because that adapter marks any provisional candle PARTIAL with a
warning. PARTIAL, EMPTY, unknown adapter versions and warning-bearing batches
fail closed; future versions need a reviewed equivalent. Empty observations
or sources also fail without invented
0/1 scores. Missing/incorrect identity and bounds produce invalid or
unavailable status; absent recent slots produce stale; gaps exceeding the
allowance produce incomplete; allowed gaps produce degraded. `VALID` does
not authorize analysis, risk, approval or execution by itself.

```bash
python -m pytest -q tests/backend/test_data_quality.py
```

## Spot research indicator metadata (Issue #49)

`analysis.indicator_registry.SPOT_RESEARCH_INDICATORS` is an immutable,
exact-version metadata catalog for EMA, ATR, Bollinger and realized-volatility
methods. It describes inputs, parameters, warm-up, output shape, regimes,
failure modes and correlated evidence. Metadata does not itself calculate an
indicator or establish data authenticity.

```bash
PYTHONPATH=apps/api/src python -m pytest -q tests/backend/test_indicator_registry.py
```

## Deterministic Spot moving averages (Issue #50)

`analysis.moving_averages.calculate_moving_average` computes configurable SMA,
EMA and linearly weighted WMA from supplied canonical C-001 closed OHLCV,
an exact C-002 snapshot and a matching **VALID** C-003 quality report. EMA
starts with the first period's SMA and uses `2/(period+1)` thereafter; WMA
weights the oldest close by 1 and newest by period. Values before warm-up
are `None`; arithmetic uses Decimal without display rounding. Input IDs,
price units, candle continuity, source membership, availability and as-of
cutoff must match. Any stale/degraded/gapped or mismatched evidence raises
without producing a series. The caller is responsible for obtaining the C-003
report from the reviewed quality assessor; a hand-constructed VALID report is
not independent proof of authentic exchange data. No provider collection,
storage, C-012 evidence assembly, signal or trading endpoint is added here.

The #49 EMA 20/50 metadata version 1 remains historically planned. Version 2
declares the reviewed EMA formula; generic SMA/EMA/WMA metadata version 1
defines parameter bounds.

```bash
PYTHONPATH=apps/api/src python -m pytest -q tests/backend/test_moving_averages.py
```

## Deterministic Spot volatility measures (Issue #52)

`analysis.volatility` provides ATR-14 using 14 true ranges, seeded with their
arithmetic mean and then Wilder's recurrence; the first true range uses the
second candle's high/low and prior close. Bollinger bands use a trailing close
mean, population standard deviation and fixed 2σ multiplier. Bandwidth is
`(upper - lower) / middle`; expansion/compression/unchanged is an exact
comparison with the prior bandwidth and is descriptive context only. Annualized
realized volatility uses sample standard deviation of close-to-close log
returns, multiplied by the square root of continuous-market periods per year
(365 days). Its unit is an annualized fraction, not a percentage or implied
volatility.

All functions require ordered contiguous closed OHLCV from the exact C-002
snapshot and a matching VALID C-003 report. They preserve source IDs, method
version and as-of metadata, return `None` during warm-up, and fail closed for
invalid quality, mismatched units, malformed candles, unavailable data or
unsupported periods/timeframes. Decimal operations use precision 34 for these
volatility formulas. The outputs do not classify high/low regimes, set
thresholds, size positions, infer a strategy or authorize trades. Realized
volatility is historical close-return dispersion; implied volatility and
historical percentile/regime analysis remain out of scope.

```bash
PYTHONPATH=apps/api/src python -m pytest -q tests/backend/test_volatility.py
```

## Local Spot research API (Issue #344)

The API exposes `GET /api/research/spot/symbols`, bounded
`GET /api/research/spot/{instrument_id}/candles`, and explicit
`POST /api/research/spot/{instrument_id}/refresh` operations for the five
approved Binance Spot instruments. Reads select the newest persisted snapshot
at or before the optional `as_of` cutoff for the requested timeframe. `limit`
is a maximum candle count; snapshots are never silently truncated because
quality and indicators are bound to the exact C-002 observation set. Results
include exact C-091 source records, C-001/C-002/C-003 identities, the complete
versioned C-003 v1 policy and digest, calculation versions, and explicit
`AVAILABLE`, `WARMUP`, or `UNAVAILABLE` indicator states. C-104 order flow
remains explicitly unavailable because this API does not collect trade/book
inputs. No endpoint creates a signal, trade, or order.

Run the API using the loopback-only launcher:

```bash
PYTHONPATH=apps/api/src python -m trading_platform_api
```

The launcher accepts only a literal loopback `--host` (`127.0.0.1` by default
or `::1`) and rejects LAN/public binds. Configure one exact loopback frontend
origin with `TRADING_PLATFORM_FRONTEND_ORIGIN`; wildcard and non-local origins
are rejected. The API also validates local Host and Origin headers and returns
`Cache-Control: no-store`.

Collection is off unless `TRADING_PLATFORM_BINANCE_SPOT_ENABLED=true` and all
three non-secret review references are configured:
`TRADING_PLATFORM_BINANCE_SPOT_TERMS_REVIEW_REFERENCE`,
`TRADING_PLATFORM_BINANCE_SPOT_REGION_REVIEW_REFERENCE`, and
`TRADING_PLATFORM_BINANCE_SPOT_INTEGRATION_REFERENCE`. The adapter checks
`exchangeInfo` eligibility separately on every symbol refresh. This opt-in does
not establish customer display or redistribution rights.

The immutable owner-approved `personal-binance-spot-ohlcv-v1` profile requires
finalized OHLCV, `open`/`high`/`low`/`close`/`volume`, zero missing intervals for
`VALID`, one timeframe interval of freshness, OHLC bounds `[1e-18, 1e18]`, and
volume bounds `[0, 1e18]`. Independent comparison is explicitly
`NOT_ASSESSED_SINGLE_SOURCE`; there is no arbitrary environment or request
override. Refresh requests supply timeframe, a 2–501 candle bound, and an aligned
half-open coverage window that must not extend into the future or exceed the
provider's 90-day OHLCV capability. The effective refresh limit is
`min(501, floor(90 days / timeframe interval))`: 90 daily candles and 501
four-hour candles are allowed; reads remain independently bounded at 501.
The service rejects over-window requests before provider access. The exact
resolved policy and hash are stored with the matching C-002 snapshot and C-003
report.

Set `DATABASE_URL` and apply the existing Alembic migrations through
`0006_spot_research_read_model` before requesting refresh or historical reads.
Downgrading this append-only history index is intentionally prohibited.
The optional `TRADING_PLATFORM_LOCAL_MARKET_ARCHIVE_ROOT` enables exact lineage
reads for archived payloads. Without it, unavailable cold payloads fail closed.
The provider is only constructed for an explicit refresh; application import,
startup, symbol listing, and ordinary reads do not contact Binance. Local
refresh calls are serialized, capped at 501 closed candles, cancellable on
client disconnect, and subject to a process-local request throttle.
Reads likewise cap history at 501; the existing provider REST pager fetches
within that explicit record budget. Serving evaluates the last closed candle
against the current or requested as-of cutoff without modifying the stored C-003
report. Stale snapshots retain their original report but are served as `STALE`
with current indicators unavailable. Explicit earlier cutoffs are labeled
`HISTORICAL`.

### Frontend handoff for Issues #145/#146

- List the allowlisted instrument IDs from `GET /api/research/spot/symbols`;
  treat that response as supported scope, not proof of current exchange
  eligibility.
- POST an explicit `{ "timeframe", "coverage_start", "coverage_end", "limit" }`
  JSON body to the selected instrument's `/refresh` route. Render sanitized
  problem responses and the returned quality status; a non-`VALID` report is
  never indicator authority or a trade signal.
- For a persisted result, GET the instrument's `/candles` route with the same
  `timeframe`, a `limit` at least as large as the snapshot (maximum 501), and optional
  `as_of`. Render the server's candle timestamps, exact as-of/snapshot/source/
  report/policy identifiers, and indicator calculation versions. Do not
  recalculate indicators in the browser or represent warm-up nulls as zero.
- Show historical data as personal research only. Customer redistribution and
  customer-facing derived analytics are not authorized by this API.

The only unresolved owner decision is approval of the versioned Binance Spot
OHLCV C-003 v1 policy profile listed above. The existing C-003 v1 assessor
remains authoritative; no thresholds are inferred or accepted from API requests
or arbitrary environment values. Until an approved profile is added, refresh
remains unavailable.

```bash
PYTHONPATH=apps/api/src python -m pytest -q tests/backend/test_spot_research_api.py
```
