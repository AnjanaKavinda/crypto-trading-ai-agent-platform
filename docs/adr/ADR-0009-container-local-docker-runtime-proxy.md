# ADR-0009: Container-local Docker runtime and authenticated API proxy

## Metadata

| Field | Value |
|---|---|
| Status | Accepted |
| Date | 2026-10-09 |
| Decision owner | Platform Architect |
| Human approver | AnjanaKavinda |
| GitHub issue / PR | [#350](https://github.com/AnjanaKavinda/crypto-trading-ai-agent-platform/issues/350) |
| Open decision ID | — |
| Related ADRs | ADR-0003, ADR-0007 |
| Supersedes / superseded by | — |

## Context

Issue #350 requests a local Docker Compose runtime for the existing read-only Spot research UI, API, migration job, and PostgreSQL. The API currently protects itself by accepting only loopback connections and loopback Host values. In a Compose network, the API sees the web proxy as a non-loopback peer; publishing the API port or weakening the request guard would change the existing trust boundary.

The deployment must remain local to the researcher's machine. The browser needs a same-origin API path, while the API and database must remain private to Compose. This is a bounded deployment exception, not a general proxy-trust feature or a change to the native launcher.

## Alternatives

### Option A — Keep native loopback deployment only

Benefits:

- Preserves the current API trust boundary without modification.
- Requires no proxy authentication or container-specific configuration.

Costs, risks, and constraints:

- Does not satisfy the requested Docker Compose workflow.
- Leaves the UI and API on separate local origins and does not provide the requested single web entrypoint.

### Option B — Publish the API on a host loopback port

Benefits:

- Keeps the API unreachable from non-host interfaces when the binding is correct.
- Avoids API trust in a container proxy.

Costs, risks, and constraints:

- Exposes an additional host port and retains cross-origin browser requests.
- Requires careful host binding on every supported platform and does not provide the requested private API service boundary.

### Option C — Publish only a loopback web entrypoint and authenticate its private proxy hop

Benefits:

- Provides one same-origin browser entrypoint.
- Leaves API and PostgreSQL ports unpublished and private to Compose.
- Allows the native API launcher and its loopback protections to remain unchanged.

Costs, risks, and constraints:

- Requires a narrowly scoped container-only API mode and proxy-authentication secret.
- A local machine or Docker-daemon administrator can inspect container configuration and secrets; this is not protection from a hostile host user.
- Adds configuration and tests for Host, Origin, research mode, and proxy-authentication failure cases.

## Decision

**Select Option C.** The human repository owner approved this bounded local Docker decision on 2026-10-10. This acceptance applies only to native local and Docker-local deployment; cloud deployment requires a separate architecture decision.

The local Compose runtime will publish only the static web/reverse-proxy service on a configurable loopback host address, defaulting to `127.0.0.1:5173`. API and PostgreSQL have no published host ports. The API and database communicate only over private Compose networking; the web service proxies same-origin `/api` requests to the API.

The API may accept a request from the proxy only when all of the following hold:

1. The process is explicitly configured for the Compose-only local mode. The ordinary native launcher continues to require loopback binding and retains its current loopback peer/Host protections.
2. A cryptographically random 256-bit proxy secret is configured for both proxy and API. The proxy overwrites, rather than forwards, any client-supplied proxy-authentication header. The API compares the received credential in constant time and rejects a missing or incorrect value.
3. The request Host is an exact allowed loopback host and port for the configured local UI origin. The browser Origin, when present and required for a state-changing or protected request, must exactly match the configured loopback UI origin. No wildcard CORS or forwarded-host trust is added.
4. Research mode is explicitly enabled, and live-trading and automatic-execution flags are false. Missing, malformed, or contradictory mode/configuration values fail closed.
5. The API has no host-published port and accepts proxy-authenticated traffic only over the private Compose network.

The secret is supplied through the ignored local root `.env` file to the proxy and API containers only. It is never embedded in an image, rendered into the UI, returned by an endpoint, or sent by browser JavaScript. `.env.example` contains a placeholder and instructions for generating a fresh secret; it contains no usable credential.

This decision does not authorize exchange API keys, cloud services, external exposure, new collection behavior, trading, order placement, or changes to market-data/analysis/lineage contracts. The Docker stack remains a local convenience boundary, not a defense against an administrator or other process with control of the host or Docker daemon.

## Reasoning

A same-origin web entrypoint avoids direct browser access to the API while keeping the API and database off host-published ports. Authenticating the proxy hop prevents any other container-network peer from impersonating the trusted web proxy merely by reaching the API. Exact loopback Host/Origin validation and fail-closed research-mode checks preserve the intended local research boundary.

The exception is limited to the Docker launcher. Applying proxy trust to the native launcher, accepting arbitrary forwarded headers, using wildcard CORS, publishing the API, or enabling trading/execution would exceed this proposal and require a new review.

## Consequences

- Docker Compose is the sole launcher allowed to opt into the container-local proxy path; native startup remains loopback-only.
- The web entrypoint is bound to a loopback host address. API and PostgreSQL ports remain unpublished.
- The local proxy secret must be generated per checkout and kept in the ignored `.env`; secret rotation requires restarting the proxy and API together.
- Missing or invalid secret, unexpected Host/Origin, disabled research mode, or enabled trading/execution fails closed.
- The Compose deployment uses local PostgreSQL storage. Normal `docker compose down` preserves its named volume; `docker compose down -v` deletes that local research data.
- Implementation, tests, and CI coverage belong to issue #350 and may proceed under this accepted boundary.
- This ADR does not authorize a weakening of the native request guard or a public/LAN deployment.

## Contract and traceability impact

| Area | References and impact |
|---|---|
| Playbook requirements | Phase 1 local research, read-only operation, and no-live-trading user direction; no Master Playbook requirement is changed. |
| Cross-cutting artifacts | ADR register and issue #350 deployment scope; update deployment documentation during implementation. |
| Contracts / events | None. No market-data, analysis, lineage, or event contract changes. |
| Requirements traceability | Issue #350; local runtime prerequisite for the bounded smoke sequence in issue #299. |
| Versioning / migration | No contract versioning. Compose starts PostgreSQL, runs Alembic migration as a one-shot service, then starts the API. |

## Safety, security, and failure behavior

This is a local deployment boundary, not a production security boundary. The host user and Docker-daemon administrator are trusted and can inspect local container configuration. The proxy secret protects the API hop from unauthenticated peers on the Compose network; it does not protect against a compromised host.

No credentials for exchange trading are introduced. Binance collection remains disabled by default. Live trading, order placement, automated execution, cloud storage, and public/LAN access remain disabled and out of scope. Requests fail closed when required secret, exact local Host/Origin, or research-mode settings are missing or invalid. The native API path remains unchanged.

## Approval record

Accepted by `AnjanaKavinda`, human repository owner, on 2026-10-10 for local Docker deployment as bounded above. Cloud deployment, public/LAN exposure, and any changes to trading/execution behavior are not approved by this ADR.
