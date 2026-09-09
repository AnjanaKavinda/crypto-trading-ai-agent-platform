# trading_platform_api package skeleton

This package provides the minimal FastAPI bootstrap entrypoint for the backend repository skeleton.

## Scope in this issue

- Defines the importable `trading_platform_api` package in `apps/api/src`.
- Provides `create_app()` and module-level `app` ASGI objects only.
- Uses static non-secret application metadata (title and version).

## Out of scope in this skeleton

This skeleton intentionally does **not** include:

- trading or strategy logic
- environment configuration
- execution or exchange integrations
- persistence or database integration
- logging infrastructure
- health/readiness/liveness endpoints
- feature flags
