# ADR-0007: Local-first backup for the personal research phase

## Metadata

| Field | Value |
|---|---|
| Status | Accepted |
| Date | 2026-10-04 |
| Decision owner | Platform Architect |
| Human approver | AnjanaKavinda |
| GitHub issue / PR | [#47](https://github.com/AnjanaKavinda/crypto-trading-ai-agent-platform/issues/47) / [#309](https://github.com/AnjanaKavinda/crypto-trading-ai-agent-platform/pull/309) |
| Related ADRs | ADR-0003, ADR-0005, ADR-0006 |
| Scope | Phase 1 local personal research deployment |

## Decision

For Phase 1, run PostgreSQL and the immutable archive/backup stores on the
user's local deployment. Do not require a cloud bucket, cloud credentials,
subscription, or monthly cloud-spend evidence to operate this phase. This
decision records the owner's explicit scope change on 2026-10-04.

The local backup target must be a separate directory from the local archive
target. Backup bundles include a PostgreSQL dump and every cold object and
manifest still referenced by archive metadata. A bundle is reported successful
only after immutable publication, full read-back, and digest verification.
Use the local AES-GCM envelope adapter for backup bundles and keep its keyring
outside the repository. Restore must verify the complete bundle before calling
the database restore operation and must target a disposable local PostgreSQL
database.

## Preserved policy

- Keep the accepted five Binance Spot OHLCV instruments, 90-day hot window,
  five-year cold minimum, and longer retention while retained analyses
  reference observations.
- Keep lineage identities, evidence hashes, and dependency edges append-only.
- Missing or corrupt archive members fail closed. A verified archive read does
  not make invalid or stale C-003 data eligible for analysis.
- Do not enable automated hot-payload removal as part of this phase change.
  Removal still requires verified cold membership, successful local backup and
  disposable restore evidence, and resolver checks. No reference anchor or
  dependency edge is removed.
- Keep live trading disabled and the user as the final authority.

## Deferred

Off-device backup, cloud provider selection, cloud versioning configuration,
cloud cost forecasts, the US$5/month backup limit, and the US$100/month
research-spend limit are deferred until a later phase. Local storage has a
single-machine failure domain: disk loss, theft, or a destructive local event
can destroy both production and backup copies. The Phase 1 local backup is a
development/research recovery mechanism, not disaster recovery.

ADR-0007 supersedes ADR-0005's off-device B2 and cost-limit clauses and ADR-0006's
off-device-backup prerequisite for this phase only. Other accepted retention
and lineage constraints remain in force. Enabling cloud backup or automated
purge requires a later owner-reviewed decision.
