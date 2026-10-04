# Issue #47 backup bundle boundary

The lineage backup helpers package a caller-supplied PostgreSQL dump and the
exact cold archive objects selected by the caller. `build_backup_bundle`
creates a deterministic ZIP with a versioned manifest, byte counts, and
SHA-256 digests for every member. `publish_backup_bundle` writes through an
injected immutable object store and reads the complete bundle back before it
reports success. `load_verified_backup` validates the complete manifest and
all member digests before exposing either the database dump or archive bytes.

The caller must publish to a separately configured, versioned, client-encrypted
off-device bucket. The existing B2 adapter provides encryption, enabled
versioning checks, immutable keys, and encrypted read-back for such a store.
Backup keys must be unique per run so a later daily snapshot does not replace
an earlier restore point.

`BackupLimits.max_bundle_bytes` is a hard per-bundle byte bound. The
`backup_costs` module validates a timezone-aware, current-month operator spend
report and projects storage plus planned egress against the approved US$5
backup allowance and US$100 total research budget. Its forecast is
conservative: it ignores provider free tiers and adds a full-month storage and
egress estimate to month-to-date spend. Missing, stale, or over-budget evidence
raises `BackupBudgetError`.

This is a cost-gate building block, not an integrated backup command: no caller
currently supplies the spend report or inventory, and no cloud billing API or
provider-side monetary cap is configured by this code. The operator must
provide measured month-to-date spend and the complete post-backup object
inventory before any future publisher integration can proceed.

The backup helper does not invoke `pg_dump` or `pg_restore`, enumerate
database-referenced archive objects, schedule daily runs, or restore into
PostgreSQL. Tests prove deterministic packaging, member integrity checks,
immutable publication, verified byte recovery with a fake store, and isolated
cost forecast behavior. They do not constitute measured billing evidence. A
disposable PostgreSQL restore and a credentialed B2 round trip remain required
before this can count as operational backup/restore evidence.

No retention scheduler or payload-removal path is enabled by this change.
Keep source hot payloads until the complete backup, restore, reference, and
cost-control gates have passed independent review.
