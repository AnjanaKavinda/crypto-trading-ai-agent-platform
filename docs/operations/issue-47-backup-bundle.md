# Issue #47 local backup operations

Phase 1 uses a local deployment and local filesystems. The backup directory
must be separate from the archive directory. This is a recovery copy on the
same machine, not off-device disaster recovery. Cloud storage, subscriptions,
and the ADR-0005 cloud-spend limits are deferred by ADR-0007.

## Configure

Install the API package in the environment used for the local PostgreSQL
instance. Set these values in an environment file outside the repository with
mode `0600`:

- `DATABASE_URL`: local PostgreSQL async URL for the source database.
- `TRADING_PLATFORM_LOCAL_ARCHIVE_ROOT`: local immutable archive root.
- `TRADING_PLATFORM_LOCAL_BACKUP_ROOT`: separate local backup root.
- `TRADING_PLATFORM_LOCAL_ENCRYPTION_ACTIVE_KEY_ID` and
  `TRADING_PLATFORM_LOCAL_ENCRYPTION_KEYS_JSON`: AES-256 keyring for backup
  encryption. Keep key material outside git and retain old key IDs while any
  bundles still use them.
- `TRADING_PLATFORM_PG_SERVICE_FILE`: path to a libpq service file with mode
  `0600`.
- `TRADING_PLATFORM_PG_DUMP_SERVICE`: libpq service name for the source
  database; its database name must match `DATABASE_URL` and its host must be
  loopback.

The command uses a libpq service name, never a password-bearing DSN in process
arguments. It rejects remote hosts and refuses overlapping archive and backup
roots.

## Run and schedule

Create one backup manually:

```sh
python -m trading_platform_api.lineage.local_backup_cli backup
```

It runs `pg_dump` in custom format, enumerates every archive object and
manifest referenced by `lineage_archive_members`, validates their database
digests, builds the bounded bundle, encrypts it with AES-GCM, writes it
immutably, then reads and verifies the full bundle. Any missing or corrupt
referenced object fails the run.

For a daily systemd user timer, copy the service and timer from
`scripts/systemd/` into `~/.config/systemd/user/`, adjust `WorkingDirectory`
and the Python environment path in the service, then run:

```sh
systemctl --user daemon-reload
systemctl --user enable --now trading-platform-local-backup.timer
systemctl --user list-timers trading-platform-local-backup.timer
```

Use `systemctl --user status trading-platform-local-backup.service` and
`journalctl --user -u trading-platform-local-backup.service` to inspect local
failures. Do not delete a prior backup until a later restore has been checked.

## Restore drill

Create an empty, disposable local PostgreSQL database whose name starts with
`trading_restore_`. Add a loopback libpq service with the same prefix and set
`TRADING_PLATFORM_PG_RESTORE_SERVICE` to its service name. Then run:

```sh
python -m trading_platform_api.lineage.local_backup_cli restore daily/YYYY/MM/DD/backup-id.zip
```

The command verifies the complete bundle before restoring archive objects and
calling `pg_restore`. It never creates, drops, or selects a database outside
the required disposable `trading_restore_*` target. After restoration, run the
lineage resolver against restored C-001 keys and verify referenced analysis
inputs resolve before treating the restore as proven.

The backup command and object-integrity unit tests do not replace a completed
restore drill. Hot-payload removal remains disabled until a disposable restore
and resolver/reference checks have been recorded and separately reviewed.
