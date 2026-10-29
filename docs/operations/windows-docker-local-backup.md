# Windows backup and restore through Docker Desktop

This procedure runs the existing Issue #47 encrypted backup CLI in a
short-lived Linux container sharing the selected PostgreSQL container's
network namespace. It does not publish PostgreSQL, start the application, run
migrations, or access an exchange/provider. The host configuration is external
to the repository and is checked before Docker is invoked.

## Use disposable data first

Run and review the isolated Product CI acceptance test from the repository
root:

```powershell
.venv\Scripts\python.exe tests/docker/test_local_stack.py
```

The test creates its own uniquely named `spot-test-*` Compose project, source
database, PostgreSQL volume, encryption key, and restore database. It exercises
encrypted backup publication, full readback verification, and restoration of a
known probe row, then removes only the owned disposable project. It compares
the retained `spot-research` container, network, and volume identities before
and after. The test never reads repository `.env` and must not be pointed at
`spot-research`.

## Prepare operator configuration

Only use this section for an explicitly authorized operator backup or restore.
The implementation PR and disposable acceptance test do not authorize an
operation on retained research data.

1. Create an external configuration directory, separate from the repository,
   the archive root, and the encrypted backup root. The archive root must be
   the one already used by the selected database. The two data roots must
   already exist and must not contain one another.
2. Create a dedicated `backup.env` with exactly these settings:

   - `DATABASE_URL`: `postgresql+asyncpg://USER:PERCENT_ENCODED_PASSWORD@127.0.0.1:5432/DATABASE`. # pragma: allowlist secret
     The URL must identify the selected Compose database. Use a URL-encoded
     password here; the corresponding libpq service uses its raw password.
   - `TRADING_PLATFORM_LOCAL_ARCHIVE_ROOT`: existing archive root.
   - `TRADING_PLATFORM_LOCAL_BACKUP_ROOT`: separate existing bundle directory.
   - `TRADING_PLATFORM_LOCAL_ENCRYPTION_ACTIVE_KEY_ID`: selected key ID.
   - `TRADING_PLATFORM_LOCAL_ENCRYPTION_KEYS_JSON`: JSON keyring with
     base64-encoded 32-byte AES keys. Obtain and retain keys through the
     operator's approved secret-management process.
   - `TRADING_PLATFORM_PG_SERVICE_FILE`: external `pg_service.conf` path.
   - `TRADING_PLATFORM_PG_DUMP_SERVICE`: source section name.
   - `TRADING_PLATFORM_PG_RESTORE_SERVICE`: optional for backup; required for
     restore and must name an empty `trading_restore_*` database.

   Illustrative template (replace every angle-bracket value; this is not a
   ready-to-run configuration):

   ```dotenv
   DATABASE_URL=postgresql+asyncpg://<user>:<url-encoded-password>@127.0.0.1:5432/<source-database> # pragma: allowlist secret
   TRADING_PLATFORM_LOCAL_ARCHIVE_ROOT="C:/private/trading/archive"
   TRADING_PLATFORM_LOCAL_BACKUP_ROOT="C:/private/trading/backups"
   TRADING_PLATFORM_LOCAL_ENCRYPTION_ACTIVE_KEY_ID=<key-id>
   TRADING_PLATFORM_LOCAL_ENCRYPTION_KEYS_JSON={"<key-id>":"<base64-32-byte-key>"}
   TRADING_PLATFORM_PG_SERVICE_FILE="C:/private/trading/pg_service.conf"
   TRADING_PLATFORM_PG_DUMP_SERVICE=source
   TRADING_PLATFORM_PG_RESTORE_SERVICE=trading_restore_local
   ```

   The restore service setting may be omitted until a restore drill. Do not
   keep the illustrative placeholders in the real file. Do not copy application
   `.env` settings into this dedicated file.

3. Put only the configured source and, when needed, restore sections in
   `pg_service.conf`. Each section must specify `host=127.0.0.1`, `port=5432`,
   the exact database and user, and the matching password. Do not put a
   password-bearing connection string in a command.
4. Protect both files with Windows ACLs. They must be regular non-reparse
   files owned by the current user. Allow only the current user, SYSTEM, and
   Administrators; do not grant access to Users, Everyone, or inherited broad
   principals. The runner checks this before reading the files and fails
   closed if the ACL check cannot run. Store encryption keys outside the repo
   and retain every key needed by existing bundles.

   To replace inherited access with only the allowed principals on each file,
   run this PowerShell snippet after creating the files (it prints no file
   contents or secret values):

   ```powershell
   $currentSid = [Security.Principal.WindowsIdentity]::GetCurrent().User.Value
   foreach ($file in @($configPath, $servicePath)) {
       $acl = Get-Acl -LiteralPath $file
       $acl.SetAccessRuleProtection($true, $false)
       foreach ($rule in @($acl.Access)) {
           [void]$acl.RemoveAccessRuleSpecific($rule)
       }
       foreach ($sid in @($currentSid, 'S-1-5-18', 'S-1-5-32-544')) {
           $rule = [Security.AccessControl.FileSystemAccessRule]::new(
               $sid,
               [Security.AccessControl.FileSystemRights]::FullControl,
               [Security.AccessControl.AccessControlType]::Allow
           )
           [void]$acl.AddAccessRule($rule)
       }
       Set-Acl -LiteralPath $file -AclObject $acl
   }
   ```

   Set `$configPath` and `$servicePath` in the same PowerShell session to the
   two exact file paths. The runner independently verifies ownership and ACLs
   before use; do not continue if it rejects either file.
5. Verify the source database name/user against the selected Compose service
   and confirm its PostgreSQL data volume is the expected project volume. The
   runner checks the project/service labels, health, private port boundary,
   volume name, database, user, and expected network before it starts a worker.
   It rejects remote Docker contexts and requires an explicit project name.

The host runner reads the config and service file into memory, passes a
temporary restricted worker environment by file path, and mounts the service
file read-only. The worker stages it in a private Linux temporary directory
with mode `0600`. On POSIX hosts the worker uses the caller's numeric user and
group IDs so created bundles remain operator-owned. On Windows it runs as root
inside the isolated Linux container because Docker Desktop bind mounts use the
Windows user's ACLs; Linux capabilities are dropped and privilege escalation
is disabled. This does not grant Windows Administrator access. The worker is
removed after completion. Secrets are not printed in command arguments or
output; Docker daemon administrators remain trusted as described by ADR-0009
and ADR-0013.

## Explicit operator commands

From the repository root, back up a selected project:

```powershell
# If the repository's Python environment has not installed the project yet:
.venv\Scripts\python.exe -m pip install -e .

.venv\Scripts\python.exe -m trading_platform_api.lineage.docker_local_backup `
  --project <exact-compose-project> `
  --config <external-protected-backup.env> `
  backup
```

The command builds the dedicated worker image, runs only against the selected
healthy PostgreSQL container, and prints the verified bundle key and digest.
Accept a backup only when the command succeeds. Preserve the resulting bundle
and its decryption keys.

To restore, first create an empty database whose name starts with
`trading_restore_` in the same disposable/local PostgreSQL deployment and add
its matching protected libpq service section. Set
`TRADING_PLATFORM_PG_RESTORE_SERVICE` in the config, then run:

```powershell
.venv\Scripts\python.exe -m trading_platform_api.lineage.docker_local_backup `
  --project <exact-compose-project> `
  --config <external-protected-backup.env> `
  restore <verified-bundle-key>
```

The existing restore CLI verifies the encrypted bundle before restoration and
refuses a non-empty or non-`trading_restore_*` target. The runner accepts only
the selected local Docker project and its healthy, unpublished PostgreSQL
service. It never runs the `prune-hot` command.

## Retained data boundary

Do not use the operator commands on `spot-research` as part of routine testing
or post-merge verification. A retained-data operation requires separate,
explicit owner authorization after the disposable test passes and the exact
backup source, archive root, encryption keys, and restore target have been
verified. This issue does not authorize migration `0008`, backup/restore of
retained data, source deletion, project teardown, or volume replacement.
