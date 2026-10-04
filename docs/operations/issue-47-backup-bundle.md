# Issue #47 local backup boundary

Phase 1 uses a local deployment and local filesystems. A backup target must be
on a separate directory from the archive root. It is not an off-device
disaster-recovery copy; both directories share the machine's failure domain.
Cloud storage, subscriptions, and the ADR-0005 cloud-spend limits are deferred
by ADR-0007.

`lineage.backups` packages a caller-supplied PostgreSQL dump and exact archive
object bytes into a deterministic ZIP. `lineage.local_backups` enumerates
archive objects through `lineage_archive_members`, checks the compressed
object and manifest digests against PostgreSQL metadata, and includes both
objects in the bundle. Missing or corrupt referenced objects stop backup
creation. Publication uses an immutable object-store port and verifies the
entire local read-back before returning the bundle digest.

`EncryptedObjectStore` encrypts the local backup target with AES-GCM before
writing it to `LocalFilesystemObjectStore`. Configure
`TRADING_PLATFORM_LOCAL_ENCRYPTION_ACTIVE_KEY_ID` and
`TRADING_PLATFORM_LOCAL_ENCRYPTION_KEYS_JSON` through the deployment's secret
environment. Do not put key material in the repository. Keep old key IDs in the
keyring until all bundles encrypted with them have expired or been migrated.

`restore_local_backup` validates the bundle and all member hashes before it
republishes the archive objects and invokes the supplied database-restore
callback. The callback must restore into a disposable local PostgreSQL
database. The helper never chooses, drops, or connects to a database. The
integration owner supplies the `pg_dump` capture and `pg_restore` callback;
this library does not yet provide a scheduled command or timer.

The current backup boundary does not remove hot payloads. C-001 lineage
identities, evidence digests, dependency links, and archive membership remain
intact. Automated removal remains disabled until local backup and disposable
restore are exercised operationally, resolver and reference checks are
recorded, and a separate rollout is reviewed.

Tests cover immutable local storage, encryption at rest, complete referenced
object collection, digest failure, bundle read-back, and rejection of corrupt
bundles before a restore callback. These tests do not claim an end-to-end
PostgreSQL dump/restore, a daily schedule, or off-machine recovery.
