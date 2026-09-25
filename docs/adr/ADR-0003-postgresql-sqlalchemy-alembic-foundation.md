# ADR-0003: PostgreSQL, SQLAlchemy async, and Alembic persistence foundation

## Metadata

| Field | Value |
|---|---|
| Status | Accepted |
| Date | 2026-09-09 |
| Decision owner | Platform Architect |
| Human approver | AnjanaKavinda |
| GitHub issue / PR | AnjanaKavinda/crypto-trading-ai-agent-platform#18 / this implementation PR |
| Open decision ID | OD-0008 |
| Related ADRs | ADR-0001 |
| Supersedes / superseded by | — |

## Context

Issue 016 requires the first production-shaped persistence and migration foundation for later backend slices. The platform needs a governed relational system-of-record direction, async session/transaction primitives, and version-controlled migrations without inventing domain schemas, startup connections, or unresolved production topology.

Chat 2 requires deterministic transaction integrity, explicit system-of-record boundaries, and separation between the control/data planes and later execution concerns. Chat 12 Section 66 requires all schema changes to be version-controlled and tracked through migrations. OD-0008 remained open for the broader relational/time-series topology, so implementation needed a bounded decision that approved only the initial relational foundation while explicitly deferring the unresolved topology and time-series questions.

## Alternatives

### Option A — Raw PostgreSQL driver with custom SQL and hand-managed migrations

Benefits:

- minimal framework surface area;
- direct SQL control.

Costs, risks, and constraints:

- application code would need to reinvent async session/transaction abstractions;
- migration discipline would require custom tooling or manual operational process;
- higher risk of inconsistent transaction handling across later repositories and services.

### Option B — SQLAlchemy 2.x async + `asyncpg` + Alembic

Benefits:

- approved async PostgreSQL foundation with explicit engine/session boundaries;
- mature migration workflow aligned with Chat 12 Section 66;
- supports later bounded model ownership without forcing startup connections or premature schema design.

Costs, risks, and constraints:

- introduces ORM/session and migration tooling that later slices must configure carefully;
- invalid URLs and secret-bearing configuration require strict redaction and fail-closed validation;
- does not answer broader time-series, production-topology, or schema-ownership questions.

### Option C — Another ORM or migration/tooling combination

Benefits:

- could optimize for different developer ergonomics or framework preferences.

Costs, risks, and constraints:

- would reopen a human-approved technology decision during implementation;
- would add unnecessary migration and persistence variability this early in the foundation phase;
- would increase compatibility and governance overhead without approved architectural benefit.

## Decision

Select **Option B: PostgreSQL as the initial relational system of record, SQLAlchemy 2.x async as the persistence/session foundation, `asyncpg` as the async PostgreSQL driver, and Alembic as the schema-migration tool**.

This decision is intentionally bounded. It approves the relational persistence foundation only. It does not select time-series extensions/products, production topology, replicas, sharding, pooling/tuning, retention, tenancy, domain schemas, or vector storage.

## Reasoning

This option best satisfies the currently approved scope:

1. It matches the human-approved bounded decision for Issue 016 and avoids reopening provider/tooling selection during implementation.
2. It gives later backend issues a deterministic async engine/session base without coupling application import/startup to database availability.
3. It provides version-controlled migration discipline required by Chat 12 Section 66 while keeping the baseline schema empty until model-owning issues are approved.
4. It preserves fail-closed behavior for invalid configuration and does not introduce any live-trading, approval, execution, risk, or exchange authority.
5. It keeps OD-0008 visibly open for the unresolved time-series and deployment-topology decisions rather than falsely declaring the entire storage architecture complete.

## Consequences

Positive:

- later backend slices can build on a stable async PostgreSQL persistence abstraction;
- Alembic revision history can start immediately with a governed empty baseline;
- the application remains import-safe and startup-safe when `DATABASE_URL` is absent.

Negative / operational obligations:

- runtime environments must provide a valid secret-managed `DATABASE_URL` before persistence or migrations are explicitly used;
- later model-owning issues must register governed SQLAlchemy metadata before any autogeneration is enabled;
- domain schemas, migration ownership, production rollout policy, topology, and time-series choices remain deferred.

Implementation sequencing:

1. record this bounded accepted decision;
2. update OD-0008 to link the approved relational foundation while preserving the open topology questions;
3. add secret-safe database configuration, lazy async engine/session factories, and a narrow transaction scope;
4. add an empty Alembic baseline only;
5. let later governed issues add owned metadata, domain tables, and production migration policy.

## Contract and traceability impact

| Area | References and impact |
|---|---|
| Playbook requirements | Chat 2 enterprise architecture; Chat 12 Section 66 migration discipline; preserves fail-closed foundation sequencing |
| Cross-cutting artifacts | Updates `docs/cross-cutting/14-open-decisions.md` OD-0008; references `docs/cross-cutting/12-test-traceability-matrix.md` for deterministic persistence/configuration testing expectations |
| Contracts / events | No shared domain-contract or event-contract semantic change; foundation only |
| Requirements traceability | Issue 016 / GitHub #18; persistence abstraction and migration foundation acceptance criteria |
| Versioning / migration | Starts Alembic revision history with one empty reversible baseline; future schema ownership remains governed |

## Safety, security, and failure behavior

- `DATABASE_URL` is secret-bearing configuration and must never be committed, logged, or exposed in reprs or deterministic configuration errors.
- Missing, blank, malformed, sync-driver, SQLite, or other-dialect URLs must fail closed only when persistence is explicitly requested.
- Engine creation must be explicit and lazy; importing the API package or creating the FastAPI app must not connect to PostgreSQL.
- This ADR introduces no live-trading path, no readiness implication, no approval or risk authority, and no exchange integration.
- If later explicit database use fails because PostgreSQL is unavailable, the application must propagate the typed database/SQLAlchemy failure rather than retry blindly or fall back to another store.

## Approval record

Accepted by `AnjanaKavinda`, human repository owner and final architecture authority, on 2026-09-09 in GitHub Issue `AnjanaKavinda/crypto-trading-ai-agent-platform#18`.

Approval scope:

- PostgreSQL is the initial relational system of record.
- SQLAlchemy 2.x async is the Python persistence/session foundation.
- `asyncpg` is the PostgreSQL async driver.
- Alembic is the schema-migration tool.

Explicitly deferred by the approval:

- time-series extensions/products;
- production topology, replicas, sharding, and pooling/tuning;
- retention, tenancy, and domain schema ownership;
- vector storage and any live-trading implications.
