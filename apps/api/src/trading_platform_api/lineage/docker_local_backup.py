"""Safely invoke the local lineage backup worker against one Compose database."""

from __future__ import annotations

import argparse
import configparser
import contextlib
import json
import os
import re
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path
from typing import Any, Iterator

from sqlalchemy.engine import make_url

from trading_platform_api.lineage.archive_storage import (
    ArchiveStorageError,
    ClientSideEncryption,
)

_PROJECT_NAME = re.compile(r"^[a-z0-9][a-z0-9_-]{0,62}$")
_SERVICE_NAME = re.compile(r"^[A-Za-z0-9_.-]{1,63}$")
_LOOPBACK_HOSTS = {"localhost", "127.0.0.1", "::1"}
_SERVICE_KEYS = {"host", "port", "dbname", "user", "password"}
_RETAINED_PROJECT = "spot-research"
_POSTGRES_PORT = 5432
_BACKUP_IMAGE = "trading-platform-lineage-backup:local"
_COMMAND_TIMEOUT = 1800
_DOCKER_PREFLIGHT_TIMEOUT = 10


def _find_repository_root() -> Path:
    current = Path.cwd().resolve()
    for candidate in (current, *current.parents):
        if (candidate / "compose.yaml").is_file() and (
            candidate / "apps" / "api" / "Dockerfile.backup"
        ).is_file():
            return candidate
    return Path(__file__).resolve().parents[5]


_REPO_ROOT = _find_repository_root()
COMPOSE_FILE = _REPO_ROOT / "compose.yaml"
_ACL_CHECK = _REPO_ROOT / "scripts" / "windows" / "verify-protected-backup-file.ps1"
_REQUIRED_ENV_KEYS = {
    "DATABASE_URL",
    "TRADING_PLATFORM_LOCAL_ARCHIVE_ROOT",
    "TRADING_PLATFORM_LOCAL_BACKUP_ROOT",
    "TRADING_PLATFORM_LOCAL_ENCRYPTION_ACTIVE_KEY_ID",
    "TRADING_PLATFORM_LOCAL_ENCRYPTION_KEYS_JSON",
    "TRADING_PLATFORM_PG_SERVICE_FILE",
    "TRADING_PLATFORM_PG_DUMP_SERVICE",
}
_ALLOWED_ENV_KEYS = _REQUIRED_ENV_KEYS | {"TRADING_PLATFORM_PG_RESTORE_SERVICE"}
_WINDOWS_ACL_ERROR_CODES = {
    2: "WINDOWS_ACL_NOT_REGULAR_FILE",
    3: "WINDOWS_ACL_OWNER_INVALID",
    4: "WINDOWS_ACL_DENY_RULE",
    5: "WINDOWS_ACL_UNAPPROVED_PRINCIPAL",
    6: "WINDOWS_ACL_OWNER_ACCESS_MISSING",
    7: "WINDOWS_ACL_CHECK_FAILED",
}


class DockerBackupError(RuntimeError):
    """A safe local Docker backup or restore could not be performed."""

    def __init__(
        self,
        message: str,
        *,
        stage: str = "validation",
        code: str = "BACKUP_VALIDATION_FAILED",
    ) -> None:
        super().__init__(message)
        self.stage = stage
        self.code = code


@contextlib.contextmanager
def _validation_boundary(code: str) -> Iterator[None]:
    """Attach one stable category without changing the internal failure detail."""
    try:
        yield
    except DockerBackupError as exc:
        if exc.stage == "validation" and exc.code == "BACKUP_VALIDATION_FAILED":
            exc.code = code
        raise


def _windows_acl_environment() -> dict[str, str]:
    environment = os.environ.copy()
    # Do not let a parent pwsh process make Windows PowerShell 5.1 load PowerShell 7 modules.
    environment["PSModulePath"] = str(
        Path(os.environ.get("SystemRoot", r"C:\Windows"))
        / "System32"
        / "WindowsPowerShell"
        / "v1.0"
        / "Modules"
    )
    return environment


def _protect_windows_file(path: Path) -> None:
    """Restrict the file DACL to its existing owner, SYSTEM, and Administrators."""
    try:
        result = subprocess.run(
            [
                "powershell.exe",
                "-NoLogo",
                "-NoProfile",
                "-NonInteractive",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(_ACL_CHECK),
                "-Path",
                str(path.resolve()),
                "-Protect",
            ],
            check=False,
            capture_output=True,
            env=_windows_acl_environment(),
            timeout=_DOCKER_PREFLIGHT_TIMEOUT,
        )
    except (OSError, subprocess.TimeoutExpired):
        raise DockerBackupError("Windows backup file ACL could not be restricted.") from None
    if result.returncode:
        raise DockerBackupError("Windows backup file ACL could not be restricted.")


def _read_env_file(path: Path) -> dict[str, str]:
    if path.is_symlink() or not path.is_file():
        raise DockerBackupError("Backup settings file is unavailable.")
    values: dict[str, str] = {}
    try:
        lines = path.read_text(encoding="utf-8-sig").splitlines()
    except (OSError, UnicodeError):
        raise DockerBackupError(
            "Backup settings file could not be read safely."
        ) from None
    for raw_line in lines:
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        key, separator, raw_value = line.partition("=")
        key = key.strip()
        if not separator or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key):
            raise DockerBackupError("Backup settings file has invalid syntax.")
        if key in values:
            raise DockerBackupError("Backup settings file repeats a setting.")
        values[key] = _parse_env_value(raw_value.strip())
    missing = _REQUIRED_ENV_KEYS - values.keys()
    if missing:
        raise DockerBackupError("Backup settings file is missing required settings.")
    if values.keys() - _ALLOWED_ENV_KEYS:
        raise DockerBackupError(
            "Backup settings file contains unrelated settings; use a dedicated backup file."
        )
    return values


def _parse_env_value(value: str) -> str:
    if value.startswith("'"):
        end = value.find("'", 1)
        if end < 0 or value[end + 1 :].strip().split(" #", 1)[0].strip():
            raise DockerBackupError("Backup settings file has invalid quoting.")
        return value[1:end]
    if value.startswith('"'):
        escaped = False
        end = -1
        for index, char in enumerate(value[1:], 1):
            if char == '"' and not escaped:
                end = index
                break
            if char == "\\" and not escaped:
                escaped = True
            else:
                escaped = False
        if end < 0 or value[end + 1 :].strip().split(" #", 1)[0].strip():
            raise DockerBackupError("Backup settings file has invalid quoting.")
        quoted = value[1:end]
        return re.sub(
            r"\\([\\\"nrt])",
            lambda match: {"n": "\n", "r": "\r", "t": "\t"}.get(
                match.group(1), match.group(1)
            ),
            quoted,
        )
    return value.split(" #", 1)[0].strip()


def _validate_protected_file(path: Path) -> None:
    if path.is_symlink() or not path.is_file():
        raise DockerBackupError("A protected backup file is missing or is a symlink.")
    if os.name == "nt":
        if not _ACL_CHECK.is_file():
            raise DockerBackupError("Windows backup ACL validation is unavailable.")
        try:
            result = subprocess.run(
                [
                    "powershell.exe",
                    "-NoLogo",
                    "-NoProfile",
                    "-NonInteractive",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-File",
                    str(_ACL_CHECK),
                    "-Path",
                    str(path.resolve()),
                ],
                check=False,
                capture_output=True,
                env=_windows_acl_environment(),
                timeout=_DOCKER_PREFLIGHT_TIMEOUT,
            )
        except (OSError, subprocess.TimeoutExpired):
            raise DockerBackupError(
                "Windows backup file protection could not be verified."
            ) from None
        if result.returncode:
            code = _WINDOWS_ACL_ERROR_CODES.get(
                result.returncode, "WINDOWS_ACL_UNKNOWN_FAILURE"
            )
            raise DockerBackupError(
                "Windows backup file ACL is not owner-restricted.",
                code=code,
            )
    elif path.stat().st_mode & 0o777 != 0o600:
        raise DockerBackupError("Backup files must have mode 0600 on this host.")


def _resolve_external_path(raw: str, *, directory: bool) -> Path:
    path = Path(raw).expanduser()
    if path.is_symlink():
        raise DockerBackupError("Backup paths must not be symlinks.")
    try:
        resolved = path.resolve(strict=True)
    except OSError:
        raise DockerBackupError("A configured backup path is unavailable.") from None
    if directory and not resolved.is_dir():
        raise DockerBackupError(
            "Archive and backup roots must be existing directories."
        )
    if not directory and not resolved.is_file():
        raise DockerBackupError("The PostgreSQL service file is unavailable.")
    if _REPO_ROOT.resolve() == resolved or _REPO_ROOT.resolve() in resolved.parents:
        raise DockerBackupError(
            "Backup settings and data paths must be outside the repository."
        )
    if "," in resolved.as_posix():
        raise DockerBackupError("Docker bind paths cannot contain commas.")
    return resolved


def _service_section(
    parser: configparser.ConfigParser, name: str
) -> configparser.SectionProxy:
    if not _SERVICE_NAME.fullmatch(name):
        raise DockerBackupError("PostgreSQL service name is invalid.")
    try:
        return parser[name]
    except KeyError:
        raise DockerBackupError("PostgreSQL service section is missing.") from None


def _validate_settings(
    config_path: Path, operation: str
) -> tuple[dict[str, str], Path, Path, Path, str, str | None]:
    with _validation_boundary("SETTINGS_SCHEMA_INVALID"):
        config_path = config_path.expanduser()
        if config_path.is_symlink() or not config_path.is_file():
            raise DockerBackupError("Backup settings file is unavailable.")
        config_path = config_path.resolve(strict=True)
        if (
            _REPO_ROOT.resolve() == config_path
            or _REPO_ROOT.resolve() in config_path.parents
        ):
            raise DockerBackupError(
                "Backup settings must be stored outside the repository."
            )
        values = _read_env_file(config_path)
    with _validation_boundary("SETTINGS_ACL_INVALID"):
        _validate_protected_file(config_path)
    with _validation_boundary("PATH_VALIDATION_FAILED"):
        archive = _resolve_external_path(
            values["TRADING_PLATFORM_LOCAL_ARCHIVE_ROOT"], directory=True
        )
        backups = _resolve_external_path(
            values["TRADING_PLATFORM_LOCAL_BACKUP_ROOT"], directory=True
        )
        if (
            archive == backups
            or archive in backups.parents
            or backups in archive.parents
        ):
            raise DockerBackupError(
                "Archive and backup roots must be separate and non-nested."
            )
        service_file = _resolve_external_path(
            values["TRADING_PLATFORM_PG_SERVICE_FILE"], directory=False
        )
    with _validation_boundary("SERVICE_FILE_ACL_INVALID"):
        _validate_protected_file(service_file)
    with _validation_boundary("DATABASE_URL_INVALID"):
        try:
            url = make_url(values["DATABASE_URL"])
        except Exception:
            raise DockerBackupError("DATABASE_URL is invalid.") from None
        if (
            url.drivername != "postgresql+asyncpg"
            or url.host not in _LOOPBACK_HOSTS
            or url.password is None
            or (url.port or _POSTGRES_PORT) != _POSTGRES_PORT
            or url.query
            or not url.database
            or not url.username
        ):
            raise DockerBackupError(
                "DATABASE_URL must include credentials and target worker loopback on port 5432."
            )
    with _validation_boundary("PG_SERVICE_INVALID"):
        parser = configparser.ConfigParser(interpolation=None)
        try:
            parser.read(service_file, encoding="utf-8")
        except (OSError, configparser.Error):
            raise DockerBackupError(
                "PostgreSQL service configuration is invalid."
            ) from None
        dump_name = values["TRADING_PLATFORM_PG_DUMP_SERVICE"]
        restore_name: str | None = values.get("TRADING_PLATFORM_PG_RESTORE_SERVICE")
        allowed_services = {dump_name}
        if restore_name:
            allowed_services.add(restore_name)
        if parser.defaults() or set(parser.sections()) != allowed_services:
            raise DockerBackupError(
                "PostgreSQL service file must contain only configured backup services."
            )
        for service in parser.sections():
            if any(key.startswith("include") for key in parser[service]):
                raise DockerBackupError(
                    "PostgreSQL service-file includes are not allowed."
                )
        dump = _service_section(parser, dump_name)
        _validate_service_target(dump, url.database, url.username, url.password)
    with _validation_boundary("ENCRYPTION_CONFIG_INVALID"):
        try:
            ClientSideEncryption.from_environment(
                values, prefix="TRADING_PLATFORM_LOCAL"
            )
        except (ArchiveStorageError, ValueError, TypeError):
            raise DockerBackupError(
                "Backup encryption key configuration is invalid."
            ) from None
    if operation == "restore":
        with _validation_boundary("PG_SERVICE_INVALID"):
            if not restore_name:
                raise DockerBackupError(
                    "A disposable PostgreSQL restore service is required."
                )
            restore = _service_section(parser, restore_name)
            target_database = restore.get("dbname", "")
            if not restore_name.startswith(
                "trading_restore_"
            ) or not target_database.startswith("trading_restore_"):
                raise DockerBackupError(
                    "Restore is allowed only to a trading_restore_* database."
                )
            if target_database == url.database:
                raise DockerBackupError(
                    "Restore target must differ from the source database."
                )
            _validate_service_target(
                restore, target_database, url.username, url.password
            )
    return values, archive, backups, service_file, dump_name, restore_name


def _validate_service_target(
    section: configparser.SectionProxy,
    database: str,
    username: str,
    password: str | None,
) -> None:
    if set(section) - _SERVICE_KEYS:
        raise DockerBackupError(
            "PostgreSQL service contains unsupported connection options."
        )
    if section.get("host", "") not in _LOOPBACK_HOSTS:
        raise DockerBackupError(
            "PostgreSQL service must use the worker's loopback host."
        )
    if section.get("dbname") != database or section.get("user") != username:
        raise DockerBackupError(
            "PostgreSQL service database or user does not match configuration."
        )
    if section.get("password", fallback="") != (password or ""):
        raise DockerBackupError(
            "PostgreSQL service credentials do not match configuration."
        )
    try:
        port = section.getint("port", fallback=_POSTGRES_PORT)
    except ValueError:
        raise DockerBackupError("PostgreSQL service port is invalid.") from None
    if port != _POSTGRES_PORT:
        raise DockerBackupError(
            "PostgreSQL service must use port 5432 in the worker network namespace."
        )


def _run_docker(arguments: list[str], *, timeout: int) -> str:
    environment = os.environ.copy()
    for name in tuple(environment):
        if name.startswith("COMPOSE_") or name in _ALLOWED_ENV_KEYS:
            environment.pop(name, None)
    try:
        result = subprocess.run(
            ["docker", *arguments],
            cwd=_REPO_ROOT,
            env=environment,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
            timeout=timeout,
        )
    except FileNotFoundError:
        raise DockerBackupError(
            "Docker CLI is not available on PATH.",
            stage="docker-invocation",
            code="DOCKER_CLI_UNAVAILABLE",
        ) from None
    except subprocess.TimeoutExpired:
        raise DockerBackupError(
            "Docker command timed out; output was suppressed.",
            stage="docker-invocation",
            code="DOCKER_COMMAND_TIMEOUT",
        ) from None
    if result.returncode:
        stage = "worker-execution" if arguments[0] == "run" else "docker-invocation"
        code = (
            "BACKUP_WORKER_FAILED" if arguments[0] == "run" else "DOCKER_COMMAND_FAILED"
        )
        raise DockerBackupError(
            "Docker command failed; output was suppressed to protect local settings.",
            stage=stage,
            code=code,
        )
    return (result.stdout or "").strip()


def _require_local_docker() -> None:
    environment = os.environ.copy()
    selected_context = environment.get("DOCKER_CONTEXT")
    override = environment.get("DOCKER_HOST")
    if selected_context:
        endpoint = _run_docker(
            [
                "context",
                "inspect",
                selected_context,
                "--format",
                "{{.Endpoints.docker.Host}}",
            ],
            timeout=_DOCKER_PREFLIGHT_TIMEOUT,
        )
        if not endpoint.startswith(("unix://", "npipe://")):
            raise DockerBackupError(
                "Docker endpoint is not a local socket or named pipe."
            )
    elif override:
        if not override.startswith(("unix://", "npipe://")):
            raise DockerBackupError(
                "Docker endpoint is not a local socket or named pipe."
            )
    else:
        context = _run_docker(["context", "show"], timeout=_DOCKER_PREFLIGHT_TIMEOUT)
        endpoint = _run_docker(
            [
                "context",
                "inspect",
                context,
                "--format",
                "{{.Endpoints.docker.Host}}",
            ],
            timeout=_DOCKER_PREFLIGHT_TIMEOUT,
        )
        if not endpoint.startswith(("unix://", "npipe://")):
            raise DockerBackupError(
                "Docker endpoint is not a local socket or named pipe."
            )
    _run_docker(
        ["version", "--format", "{{.Server.Version}}"],
        timeout=_DOCKER_PREFLIGHT_TIMEOUT,
    )


def _inspect_postgres(
    project: str, values: dict[str, str]
) -> tuple[str, dict[str, Any]]:
    ids = _run_docker(
        [
            "ps",
            "--quiet",
            "--filter",
            f"label=com.docker.compose.project={project}",
            "--filter",
            "label=com.docker.compose.service=postgres",
        ],
        timeout=_DOCKER_PREFLIGHT_TIMEOUT,
    ).splitlines()
    if len(ids) != 1 or not re.fullmatch(r"[0-9a-f]{12,64}", ids[0]):
        raise DockerBackupError(
            "Exactly one running PostgreSQL service is required for this project."
        )
    inspected = _run_docker(["inspect", ids[0]], timeout=_DOCKER_PREFLIGHT_TIMEOUT)
    try:
        records = json.loads(inspected)
        container = records[0]
        labels = container["Config"]["Labels"]
        state = container["State"]
        health = state.get("Health", {}).get("Status")
        environment = dict(
            item.split("=", 1)
            for item in container["Config"].get("Env", [])
            if "=" in item
        )
        mounts = container["Mounts"]
        networks = container["NetworkSettings"]["Networks"]
        bindings = container["HostConfig"].get("PortBindings") or {}
    except (ValueError, KeyError, IndexError, TypeError):
        raise DockerBackupError(
            "PostgreSQL deployment identity could not be verified."
        ) from None
    expected_workdir = os.path.normcase(os.path.realpath(_REPO_ROOT))
    configured_workdir = labels.get("com.docker.compose.project.working_dir", "")
    configured_files = labels.get("com.docker.compose.project.config_files", "")
    config_files = [
        item.strip() for item in configured_files.split(",") if item.strip()
    ]
    expected_compose = os.path.normcase(os.path.realpath(COMPOSE_FILE))
    if (
        labels.get("com.docker.compose.project") != project
        or labels.get("com.docker.compose.service") != "postgres"
        or os.path.normcase(os.path.realpath(configured_workdir)) != expected_workdir
        or len(config_files) != 1
        or os.path.normcase(os.path.realpath(config_files[0])) != expected_compose
        or not state.get("Running")
        or health != "healthy"
        or any(bindings.values())
    ):
        raise DockerBackupError(
            "PostgreSQL project, health, or private-port boundary is invalid."
        )
    expected_database = values["DATABASE_URL"]
    url = make_url(expected_database)
    if (
        environment.get("POSTGRES_DB") != url.database
        or environment.get("POSTGRES_USER") != url.username
    ):
        raise DockerBackupError(
            "Configured source database or user does not match the Compose service."
        )
    if url.port not in (None, _POSTGRES_PORT):
        raise DockerBackupError(
            "Configured source port does not match PostgreSQL port 5432."
        )
    expected_volume = f"{project}_research-data"
    data_mounts = [
        mount
        for mount in mounts
        if mount.get("Destination") == "/var/lib/postgresql/data"
    ]
    if (
        len(data_mounts) != 1
        or data_mounts[0].get("Type") != "volume"
        or data_mounts[0].get("Name") != expected_volume
    ):
        raise DockerBackupError(
            "PostgreSQL data volume does not match the selected Compose project."
        )
    volume_metadata = _run_docker(
        ["volume", "inspect", expected_volume], timeout=_DOCKER_PREFLIGHT_TIMEOUT
    )
    try:
        volume_labels = json.loads(volume_metadata)[0]["Labels"] or {}
    except (ValueError, KeyError, IndexError, TypeError):
        raise DockerBackupError(
            "PostgreSQL data volume ownership could not be verified."
        ) from None
    if (
        volume_labels.get("com.docker.compose.project") != project
        or volume_labels.get("com.docker.compose.volume") != "research-data"
    ):
        raise DockerBackupError(
            "PostgreSQL data volume is not owned by the selected Compose project."
        )
    expected_network = f"{project}_database"
    if set(networks) != {expected_network}:
        raise DockerBackupError(
            "PostgreSQL is not attached only to the expected private database network."
        )
    network_metadata = _run_docker(
        ["network", "inspect", expected_network], timeout=_DOCKER_PREFLIGHT_TIMEOUT
    )
    try:
        network_labels = json.loads(network_metadata)[0]["Labels"] or {}
    except (ValueError, KeyError, IndexError, TypeError):
        raise DockerBackupError(
            "PostgreSQL network ownership could not be verified."
        ) from None
    if (
        network_labels.get("com.docker.compose.project") != project
        or network_labels.get("com.docker.compose.network") != "database"
    ):
        raise DockerBackupError(
            "PostgreSQL network is not owned by the selected Compose project."
        )
    if (
        project == _RETAINED_PROJECT
        and expected_volume != "spot-research_research-data"
    ):
        raise DockerBackupError("Retained research volume identity did not match.")
    return ids[0], container


def _mount(source: Path, target: str, *, readonly: bool = False) -> str:
    parts = ["type=bind", f"source={source.as_posix()}", f"target={target}"]
    if readonly:
        parts.append("readonly")
    return ",".join(parts)


def _worker_user() -> str:
    """Use the host owner for POSIX bind mounts; Windows uses Docker Desktop's ACL bridge."""
    if os.name == "nt":
        return "0:0"
    return f"{os.getuid()}:{os.getgid()}"


@contextlib.contextmanager
def _worker_environment_file(
    values: dict[str, str], restore_service: str | None
) -> Iterator[Path]:
    worker_values = {
        "DATABASE_URL": values["DATABASE_URL"],
        "TRADING_PLATFORM_LOCAL_ARCHIVE_ROOT": "/backup/archive",
        "TRADING_PLATFORM_LOCAL_BACKUP_ROOT": "/backup/bundles",
        "TRADING_PLATFORM_LOCAL_ENCRYPTION_ACTIVE_KEY_ID": values[
            "TRADING_PLATFORM_LOCAL_ENCRYPTION_ACTIVE_KEY_ID"
        ],
        "TRADING_PLATFORM_LOCAL_ENCRYPTION_KEYS_JSON": values[
            "TRADING_PLATFORM_LOCAL_ENCRYPTION_KEYS_JSON"
        ],
        "TRADING_PLATFORM_PG_SERVICE_FILE": "/tmp/pg_service.conf",
        "TRADING_PLATFORM_PG_DUMP_SERVICE": values["TRADING_PLATFORM_PG_DUMP_SERVICE"],
    }
    if restore_service is not None:
        worker_values["TRADING_PLATFORM_PG_RESTORE_SERVICE"] = restore_service
    if any("\n" in value or "\r" in value for value in worker_values.values()):
        raise DockerBackupError(
            "Backup worker settings contain unsupported line breaks."
        )
    with tempfile.TemporaryDirectory(prefix="trading-lineage-backup-") as directory:
        env_file = Path(directory) / "worker.env"
        env_file.write_text(
            "".join(f"{key}={value}\n" for key, value in worker_values.items()),
            encoding="utf-8",
        )
        try:
            if os.name == "nt":
                _protect_windows_file(env_file)
            else:
                env_file.chmod(0o600)
        except OSError:
            raise DockerBackupError(
                "Backup worker settings file could not be protected."
            ) from None
        _validate_protected_file(env_file)
        yield env_file


def _cleanup_owned_container(name: str, run_id: str) -> None:
    candidates = _run_docker(
        ["ps", "--all", "--quiet", "--filter", f"name=^/{name}$"],
        timeout=_DOCKER_PREFLIGHT_TIMEOUT,
    ).splitlines()
    if not candidates:
        return
    if len(candidates) != 1:
        raise DockerBackupError("Backup worker cleanup target is ambiguous.")
    inspected = _run_docker(
        ["inspect", candidates[0]], timeout=_DOCKER_PREFLIGHT_TIMEOUT
    )
    try:
        container = json.loads(inspected)[0]
        labels = container["Config"]["Labels"]
    except (ValueError, KeyError, IndexError, TypeError):
        raise DockerBackupError(
            "Backup worker cleanup ownership could not be verified."
        ) from None
    if (
        labels.get("com.trading-platform.backup-runner") != "true"
        or labels.get("com.trading-platform.backup-run-id") != run_id
    ):
        raise DockerBackupError(
            "Refusing cleanup of a container not created by this invocation."
        )
    _run_docker(["rm", "--force", name], timeout=_DOCKER_PREFLIGHT_TIMEOUT)


def _assert_worker_removed(run_id: str) -> None:
    remaining = _run_docker(
        [
            "ps",
            "--all",
            "--quiet",
            "--filter",
            f"label=com.trading-platform.backup-run-id={run_id}",
        ],
        timeout=_DOCKER_PREFLIGHT_TIMEOUT,
    ).splitlines()
    if remaining:
        raise DockerBackupError(
            "The one-shot backup worker remains after its operation."
        )


def run_backup(
    project: str,
    config_path: Path,
    operation: str,
    object_key: str | None = None,
    *,
    confirm_retained_project: str | None = None,
) -> str:
    if not _PROJECT_NAME.fullmatch(project):
        raise DockerBackupError("Compose project name is invalid.")
    if project != _RETAINED_PROJECT and not project.startswith("spot-test-"):
        raise DockerBackupError(
            "Only spot-research or a disposable spot-test-* project is supported."
        )
    if operation not in {"backup", "restore"} or (operation == "restore") != bool(
        object_key
    ):
        raise DockerBackupError("Backup operation is invalid.")
    if project == _RETAINED_PROJECT and confirm_retained_project != _RETAINED_PROJECT:
        raise DockerBackupError(
            "Operations on spot-research require --confirm-retained-project spot-research."
        )
    if project != _RETAINED_PROJECT and confirm_retained_project is not None:
        raise DockerBackupError(
            "Retained-project confirmation does not match the target project."
        )

    values, archive, backups, service_file, _dump_service, restore_service = (
        _validate_settings(config_path, operation)
    )
    _require_local_docker()
    postgres_id, _container = _inspect_postgres(project, values)

    _run_docker(
        [
            "build",
            "--quiet",
            "--file",
            "apps/api/Dockerfile.backup",
            "--tag",
            _BACKUP_IMAGE,
            ".",
        ],
        timeout=900,
    )
    run_id = uuid.uuid4().hex
    container_name = f"lineage-backup-{run_id[:20]}"
    with _worker_environment_file(values, restore_service) as worker_env_file:
        command = [
            "run",
            "--rm",
            "--name",
            container_name,
            "--label",
            "com.trading-platform.backup-runner=true",
            "--label",
            f"com.trading-platform.backup-run-id={run_id}",
            "--user",
            _worker_user(),
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges",
            "--network",
            f"container:{postgres_id}",
            "--env-file",
            str(worker_env_file),
            "--mount",
            _mount(archive, "/backup/archive", readonly=operation == "backup"),
            "--mount",
            _mount(backups, "/backup/bundles"),
            "--mount",
            _mount(service_file, "/run/backup-config/pg_service.conf", readonly=True),
            _BACKUP_IMAGE,
            operation,
        ]
        if operation == "restore":
            command.append(object_key or "")
        try:
            output = _run_docker(command, timeout=_COMMAND_TIMEOUT)
        except BaseException:
            _cleanup_owned_container(container_name, run_id)
            _assert_worker_removed(run_id)
            raise
        try:
            _assert_worker_removed(run_id)
        except DockerBackupError:
            _cleanup_owned_container(container_name, run_id)
            _assert_worker_removed(run_id)
            raise
    return output


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run the encrypted lineage backup worker in the selected local "
            "PostgreSQL container's private network namespace."
        )
    )
    parser.add_argument(
        "--project", required=True, help="exact Docker Compose project name"
    )
    parser.add_argument(
        "--config",
        required=True,
        type=Path,
        help="protected external backup settings file",
    )
    parser.add_argument(
        "--confirm-retained-project",
        help="required exact project name when operating on spot-research",
    )
    operations = parser.add_subparsers(dest="operation", required=True)
    operations.add_parser("backup", help="create and verify one encrypted backup")
    restore = operations.add_parser(
        "restore", help="restore to an empty disposable trading_restore_* database"
    )
    restore.add_argument("object_key")
    return parser


def main() -> None:
    arguments = _parser().parse_args()
    try:
        result = run_backup(
            arguments.project,
            arguments.config,
            arguments.operation,
            getattr(arguments, "object_key", None),
            confirm_retained_project=arguments.confirm_retained_project,
        )
    except DockerBackupError as exc:
        print(
            f"LOCAL_BACKUP_DIAGNOSTIC stage={exc.stage} code={exc.code}",
            file=sys.stderr,
        )
        _parser().exit(2, "local Docker backup failed; details suppressed.\n")
    if result:
        print(result)


if __name__ == "__main__":
    main()
