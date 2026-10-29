"""Stage a mounted libpq service file securely before running the backup CLI."""

from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path

from trading_platform_api.lineage.local_backup_cli import main as backup_main

_MOUNTED_SERVICE_FILE = Path("/run/backup-config/pg_service.conf")


def main() -> None:
    """Copy the read-only host file to private Linux storage, then dispatch."""
    if _MOUNTED_SERVICE_FILE.is_symlink() or not _MOUNTED_SERVICE_FILE.is_file():
        raise SystemExit(
            "local backup failed: protected PostgreSQL service file is unavailable"
        )

    with tempfile.TemporaryDirectory(prefix="lineage-backup-config-") as directory:
        service_file = Path(directory) / "pg_service.conf"
        shutil.copyfile(_MOUNTED_SERVICE_FILE, service_file)
        service_file.chmod(0o600)
        os.environ["TRADING_PLATFORM_PG_SERVICE_FILE"] = str(service_file)
        backup_main()


if __name__ == "__main__":
    main()
