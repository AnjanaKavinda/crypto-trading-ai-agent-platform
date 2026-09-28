# trading_platform_api package skeleton

This package provides the minimal FastAPI bootstrap entrypoint for the backend repository skeleton plus the bounded PostgreSQL async persistence and migration foundation approved for Issue 016.

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

These components provide configuration parsing, engine/session factories, a narrow async transaction scope, and an empty migration baseline only. They do **not** introduce domain tables, CRUD repositories, startup database connections, additional health probes, or any live-trading behavior.

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
record terms and regional eligibility, confirm live BTCUSDT/ETHUSDT metadata,
exercise public REST and WebSocket endpoints, inspect archive checksum and
microsecond timestamp behavior, and retain a non-secret evidence reference.
Until then, do not enable collection. Historical gaps, archive revisions and
stream disconnects require explicit reconciliation before analysis can claim
continuous data. Order books, futures, credentials and execution remain outside
this adapter.

### Owner-authorized one-shot check

Issue #282 records the owner's personal-use assumption and public symbol
preflight. From the repository root, on a machine with permitted Binance
access, install the package with `python -m pip install -e .` and run:

    python -m trading_platform_api.market_data.binance_spot.smoke --terms-ref issue-282-terms-review-20260928 --region-ref issue-282-region-preflight-20260927 --preflight-ref issue-282-region-preflight-20260927 --archive

This command creates an enabled provider for this invocation only. It checks
two closed one-minute candles and two recent trades for each approved symbol,
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
