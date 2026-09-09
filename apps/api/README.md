# trading_platform_api package skeleton

This package provides the minimal FastAPI bootstrap entrypoint for the backend repository skeleton.

## Scope in this issue

- Defines the importable `trading_platform_api` package in `apps/api/src`.
- Provides `create_app()` and module-level `app` ASGI objects.
- Uses static non-secret application metadata (title and version).
- Adds typed runtime context settings for deployment environment and operating mode.

## Configuration

- `TRADING_PLATFORM_ENVIRONMENT`: `dev`, `test`, `staging`, `prod` (default: `dev`)
- `TRADING_PLATFORM_MODE`: `research`, `backtest`, `paper`, `shadow`, `testnet`, `live-supervised` (default: `research`)

Configuration values identify runtime context only and do not grant trading or execution authority.

## Out of scope in this skeleton

This skeleton intentionally does **not** include:

- trading or strategy logic
- execution or exchange integrations
- persistence or database integration
- logging infrastructure
- health/readiness/liveness endpoints
- feature flags
