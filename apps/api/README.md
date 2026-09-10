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
  `postgresql+asyncpg://app_user:<password>@db-host:5432/trading_platform`

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
DATABASE_URL='******localhost:5432/placeholder' \
alembic -c apps/api/alembic.ini upgrade head --sql
```

Revision graph inspection:

```bash
alembic -c apps/api/alembic.ini heads
```

Online migration execution against an explicitly supplied environment:

```bash
DATABASE_URL='postgresql+asyncpg://app_user:<password>@db-host:5432/trading_platform' \
alembic -c apps/api/alembic.ini upgrade head
```

The baseline migration is intentionally schema-empty. It creates **no** production tables, extensions, enums, indexes, triggers, seed data, or other domain objects.

## Deferred decisions and operating-mode impact

This foundation does **not** resolve time-series technology, production topology, replicas, sharding, pooling/tuning, retention, tenancy, vector storage, or domain schema ownership. Those decisions remain governed and deferred.

Persistence availability does not imply trading readiness, execution authority, or live-trading enablement. Live trading remains disabled until later approved phases add the required risk, approval, execution, audit, and reconciliation controls.
