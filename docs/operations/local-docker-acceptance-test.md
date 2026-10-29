# Local Docker acceptance test

Run the Product CI Docker acceptance test from the repository root:

```powershell
.venv\Scripts\python.exe tests/docker/test_local_stack.py
```

On a POSIX shell with the project's Python dependencies installed:

```sh
python tests/docker/test_local_stack.py
```

The test checks Docker Desktop responsiveness before changing Docker state. It creates a unique Compose project, a temporary settings file derived from `.env.example`, and a disposable PostgreSQL volume. The web service binds only to `127.0.0.1` on a dynamically selected port. API and PostgreSQL ports remain private. The test disables Spot provider collection.

The test does not read, create, or modify the repository's `.env`. It passes the temporary settings file and unique project name explicitly to every Compose command. It records safe container, network, and volume identities for the retained `spot-research` project before startup and compares them after cleanup; it does not print container environment variables, rendered Compose configuration, generated credentials, or raw logs.

The existing negative-control refresh request is sent only to the disposable local API. Because collection is disabled, it must return `403 COLLECTION_NOT_ENABLED` without making an external market-data request. The test also verifies migration `0008_spot_analysis_lineage` and persistence across a restart of its disposable database volume.

On success, cleanup runs only against the unique test project, removes that project's disposable volume, verifies its containers/networks/volumes are gone, and verifies retained `spot-research` identities are unchanged. It never runs a global prune or an unqualified Compose teardown.

If Docker is unresponsive, a resource identity is ambiguous, or ownership labels cannot be verified, the test fails closed. Do not manually clean up resources based only on a partial name; inspect the reported project ownership first. The existing retained database is never migrated by this test. Applying a migration to retained data remains gated on the separately verified backup procedure in Issue #414 and separate owner authorization.
