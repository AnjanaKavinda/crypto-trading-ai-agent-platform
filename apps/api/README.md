# trading_platform_api package skeleton

This package provides the minimal FastAPI bootstrap entrypoint for the backend repository skeleton.

## Scope in this issue

- Defines the importable `trading_platform_api` package in `apps/api/src`.
- Provides `create_app()` and module-level `app` ASGI objects.
- Uses static non-secret application metadata (title and version).
- Adds typed runtime context settings for deployment environment and operating mode.
- Adds deterministic standard-library structured logging primitives in
  `trading_platform_api.structured_logging`.
- Adds read-only `/health`, `/health/live`, and fail-closed
  `/health/trading-readiness` operational endpoints.

## Configuration

- `TRADING_PLATFORM_ENVIRONMENT`: `dev`, `test`, `staging`, `prod` (default: `dev`)
- `TRADING_PLATFORM_MODE`: `research`, `backtest`, `paper`, `shadow`, `testnet`, `live-supervised` (default: `research`)
- `ENABLE_LIVE_TRADING`: `true` or `false` (default: `false`)
- `ENABLE_AUTO_EXECUTION`: `true` or `false` (default: `false`)
- `ENABLE_ADAPTIVE_STRATEGIES`: `true` or `false` (default: `false`)
- `ENABLE_LEARNING`: `true` or `false` (default: `false`)
- `ENABLE_EXPERIMENTS`: `true` or `false` (default: `false`)

Configuration values identify runtime context and eligibility only, and do not grant trading or execution authority.

## Out of scope in this skeleton

This skeleton intentionally does **not** include:

- trading or strategy logic
- execution or exchange integrations
- persistence or database integration
- an authoritative trading-readiness evaluator
