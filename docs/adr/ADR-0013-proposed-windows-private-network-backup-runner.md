# ADR-0013: Proposed Windows backups through the private Docker network

## Metadata

| Field | Value |
|---|---|
| Status | Accepted |
| Date | 2026-10-29 |
| Decision owner | Platform Architect |
| Human approver | AnjanaKavinda (PR #418 merge) |
| GitHub issue / PR | [#414](https://github.com/AnjanaKavinda/crypto-trading-ai-agent-platform/issues/414), [#418](https://github.com/AnjanaKavinda/crypto-trading-ai-agent-platform/pull/418) |
| Open decision ID | OD-0026 |
| Related ADRs | ADR-0007, ADR-0009 |
| Supersedes / superseded by | — |

## Context

Issue #414 needs a supported Windows/Docker Desktop process for backing up and
restoring the PostgreSQL database used by the existing local research stack.
The Issue #47 host-side CLI requires loopback PostgreSQL connectivity and a
libpq service file with POSIX mode `0600`. The Compose PostgreSQL service has no
host-published port and is reachable only on its private network. Windows
filesystem permissions do not reliably satisfy the CLI's POSIX mode check.

ADR-0009 approves publishing only the loopback web entrypoint. It keeps the API
and PostgreSQL ports unpublished and private to Compose. A host port, even one
bound to loopback, would add a publication path outside that accepted decision.
Issue #414 therefore needs an explicit choice for a backup process that can
reach PostgreSQL without changing that boundary.

## Alternatives

### Option A — Publish a temporary PostgreSQL port on host loopback

Benefits:

- Reuses the existing host-side backup CLI and its loopback validation.
- Uses host-installed PostgreSQL client tools.

Costs, risks, and constraints:

- Adds a host-published PostgreSQL path, even if temporary and loopback-bound.
- Conflicts with ADR-0009's decision to publish only the web entrypoint.
- Requires proving that the port is removed after every success and failure.

### Option B — Run an explicitly invoked, one-shot backup worker on the existing private Compose database network

Benefits:

- Keeps PostgreSQL unpublished to the host and LAN.
- Reaches the selected PostgreSQL service through the already private Compose
  network.
- Can stage protected files in a Linux container filesystem with the required
  restrictive mode while validating their Windows ACL protection before use.

Costs, risks, and constraints:

- Requires a Docker-aware launcher and explicit target identity checks.
- A worker with valid database credentials can access the database while it is
  attached to the private network; invocation and lifetime must be bounded.
- Windows ACL checks, secret staging, and cleanup need dedicated tests.

### Option C — Keep the current host-only CLI and defer Windows/Docker support

Benefits:

- Makes no deployment or backup implementation change.
- Avoids adding a database-accessing worker.

Costs, risks, and constraints:

- Leaves the retained local database without the supported pre-migration backup
  path required by Issue #414.
- Continues to block safe post-merge database operations on this setup.

## Decision

**Select Option B.** The human repository owner accepted this bounded decision
by merging PR #418 on 2026-10-29. It permits an explicitly invoked,
short-lived backup/restore worker attached only to the existing local Compose
database network. PostgreSQL remains without host-published ports and is not
reachable from the host LAN. The host and Docker-daemon administrator remain
trusted as specified by ADR-0009.

The worker must:

1. Validate the exact Compose project, PostgreSQL container/service identity,
   source database, port, user, archive root, and separate backup root before
   any backup or restore operation; reject mismatches without fallback.
2. Run only through an explicit operator command. It must not start with the
   application, run migrations, refresh market data, or schedule itself.
3. Share only the validated PostgreSQL container's network namespace. On
   POSIX hosts, run with the caller's numeric UID/GID so created bundles remain
   operator-owned. On Windows, run as root only inside the isolated Linux
   container, with Linux capabilities dropped and privilege escalation
   disabled; this does not grant Windows Administrator access.
4. Use a Windows-protected external configuration file. Validate its ACLs
   before use, mount it read-only, and stage required files in a private
   container temporary filesystem with restrictive permissions. Secrets must
   not appear in command-line arguments, source control, or logs.
5. Preserve Issue #47's encrypted immutable bundle, full readback and digest
   verification, archive-reference validation, key retention, and restore
   checks.
6. Restore only to an empty, explicitly disposable `trading_restore_*`
   database; fail closed on any other target or non-empty target.
7. Be exercised only against disposable source and restore data in this issue.
   It must not back up, restore, migrate, reset, or alter the retained
   `spot-research` database or volume.

This ADR authorizes no host-published PostgreSQL port, API exposure, public or
LAN access, automated backup schedule, hot-payload pruning, migration of the
retained database, provider operation, or trading/execution behavior.

## Reasoning

Option B uses the existing private Compose network as the only database
transport and avoids adding a host-visible database endpoint. It addresses the
Windows host's POSIX mode limitation by checking host-side ACL protection and
staging the files inside the Linux worker with restrictive permissions. The
worker's exact-target validation and explicit invocation preserve the
fail-closed, operator-controlled character of Issue #47.

Issue #414's phrase “inaccessible from non-loopback hosts” must mean that
PostgreSQL is not published to the host or LAN; the explicitly approved
one-shot worker may connect from the private Compose network. This definition
must be made explicit in Issue #414 before implementation.

## Consequences

- Issue #414 may proceed to implementation only after the human repository
  owner accepts this ADR.
- The backup worker is an operator-invoked local maintenance tool, not a
  continuously running service.
- The existing web-only host publication rule remains in effect.
- Windows ACL validation, protected-file staging, private-network target
  validation, and failure cleanup become test requirements.
- A successful disposable drill does not authorize a backup, restore, or
  migration against retained local data. Those remain separately authorized
  operations.
- Off-device backup remains outside this decision and is governed by ADR-0007.

## Contract and traceability impact

| Area | References and impact |
|---|---|
| Playbook requirements | Chat 2 architecture boundaries; Chat 10 security, failure recovery, and observability; Chat 12 implementation and test traceability. No product or trading requirement changes. |
| Cross-cutting artifacts | ADR register; open decision OD-0026; Issue #414 acceptance criteria. |
| Contracts / events | None. No C-001, C-003, archive, analysis, API, event, or trading contract changes. |
| Requirements traceability | GitHub Issue #414; preserves Issue #47 backup and restore safeguards. |
| Versioning / migration | No schema or migration change. Migration `0008_spot_analysis_lineage` is explicitly excluded. |

## Safety, security, and failure behavior

The worker receives no exchange credentials and has no market-data provider,
refresh, approval, order, execution, paper/testnet, or live-trading capability.
It receives database access only while explicitly invoked and attached to the
private Compose database network. It must stop before data operations if
project identity, container identity, database selector, path separation,
Windows ACLs, encryption configuration, or restore-target emptiness cannot be
verified. It must remove only resources it created, by validated unique
identity, and preserve all pre-existing containers, networks, databases, and
volumes.

## Approval record

Accepted by AnjanaKavinda, human repository owner, by merging PR #418 on
2026-10-29. Implementation may proceed within the stated limits.
