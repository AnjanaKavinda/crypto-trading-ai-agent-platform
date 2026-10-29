from __future__ import annotations

import base64
import json
import os
import subprocess
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from trading_platform_api.lineage.docker_local_backup import (
    _REPO_ROOT,
    COMPOSE_FILE,
    DockerBackupError,
    _inspect_postgres,
    _parse_env_value,
    _protect_windows_file,
    _read_env_file,
    _require_local_docker,
    _validate_protected_file,
    _validate_settings,
    _worker_user,
    main,
    run_backup,
)


def _protect_windows_test_file(path: Path) -> None:
    """Give a synthetic Windows secret file the production-required ACL."""
    if os.name != "nt":
        return
    _protect_windows_file(path)


def _configuration(tmp_path: Path) -> tuple[Path, Path, Path, Path]:
    archive = tmp_path / "archive"
    backup = tmp_path / "backups"
    archive.mkdir()
    backup.mkdir()
    service = tmp_path / "pg_service.conf"
    password = "test" + "-password"  # pragma: allowlist secret
    service.write_text(
        "[source]\nhost=127.0.0.1\nport=5432\ndbname=source\nuser=research\n"
        f"password={password}\n",
        encoding="utf-8",
    )
    service.chmod(0o600)
    _protect_windows_test_file(service)
    env = tmp_path / "backup.env"
    env.write_text(
        f"DATABASE_URL=postgresql+asyncpg://research:{password}@127.0.0.1:5432/source\n"
        f"TRADING_PLATFORM_LOCAL_ARCHIVE_ROOT={archive}\n"
        f"TRADING_PLATFORM_LOCAL_BACKUP_ROOT={backup}\n"
        "TRADING_PLATFORM_LOCAL_ENCRYPTION_ACTIVE_KEY_ID=test-key\n"  # pragma: allowlist secret
        f"TRADING_PLATFORM_LOCAL_ENCRYPTION_KEYS_JSON={json.dumps({'test-key': base64.b64encode(bytes(range(32))).decode('ascii')})}\n"  # pragma: allowlist secret
        f"TRADING_PLATFORM_PG_SERVICE_FILE={service}\n"
        "TRADING_PLATFORM_PG_DUMP_SERVICE=source\n",  # pragma: allowlist secret
        encoding="utf-8",
    )
    env.chmod(0o600)
    _protect_windows_test_file(env)
    return env, service, archive, backup


def _postgres_inspect(project: str, *, ports: dict | None = None) -> dict:
    return {
        "Config": {
            "Labels": {
                "com.docker.compose.project": project,
                "com.docker.compose.service": "postgres",
                "com.docker.compose.project.working_dir": str(_REPO_ROOT),
                "com.docker.compose.project.config_files": str(COMPOSE_FILE),
            },
            "Env": ["POSTGRES_DB=source", "POSTGRES_USER=research"],
        },
        "State": {"Running": True, "Health": {"Status": "healthy"}},
        "Mounts": [
            {
                "Type": "volume",
                "Name": f"{project}_research-data",
                "Destination": "/var/lib/postgresql/data",
            }
        ],
        "NetworkSettings": {"Networks": {f"{project}_database": {}}},
        "HostConfig": {"PortBindings": ports or {}},
    }


def test_env_parser_handles_quoted_paths_and_preserves_json_quotes() -> None:
    assert _parse_env_value('"C:/private folder/settings.env"') == (
        "C:/private folder/settings.env"
    )
    assert _parse_env_value('{"key":"base64"}') == '{"key":"base64"}'
    assert _parse_env_value("C:/private folder # local") == "C:/private folder"


def test_worker_identity_matches_host_bind_mount_access() -> None:
    if os.name == "nt":
        assert _worker_user() == "0:0"
    else:
        assert _worker_user() == f"{os.getuid()}:{os.getgid()}"


def test_windows_file_protection_does_not_require_privileged_owner_reset(
    tmp_path: Path,
) -> None:
    protected = tmp_path / "protected.env"
    protected.write_text("safe=value\n", encoding="utf-8")
    identity = subprocess.CompletedProcess([], 0, "S-1-5-21-1000\n", "")
    success = subprocess.CompletedProcess([], 0, b"", b"")
    with patch(
        "trading_platform_api.lineage.docker_local_backup.subprocess.run",
        side_effect=[identity, success, success, success, success],
    ) as run:
        _protect_windows_file(protected)

    acl_commands = [call.args[0] for call in run.call_args_list[1:]]
    assert all("/setowner" not in command for command in acl_commands)
    assert [command[2] for command in acl_commands] == [
        "/inheritance:r",
        "/grant:r",
        "/grant:r",
        "/grant:r",
    ]


@pytest.mark.skipif(os.name != "nt", reason="Windows ACL validation requires Windows")
@pytest.mark.parametrize(
    ("returncode", "expected_code"),
    [
        (2, "WINDOWS_ACL_NOT_REGULAR_FILE"),
        (3, "WINDOWS_ACL_OWNER_INVALID"),
        (4, "WINDOWS_ACL_DENY_RULE"),
        (5, "WINDOWS_ACL_UNAPPROVED_PRINCIPAL"),
        (6, "WINDOWS_ACL_OWNER_ACCESS_MISSING"),
        (7, "WINDOWS_ACL_CHECK_FAILED"),
        (9, "WINDOWS_ACL_UNKNOWN_FAILURE"),
    ],
)
def test_windows_acl_validator_exit_codes_are_safely_mapped(
    tmp_path: Path, returncode: int, expected_code: str
) -> None:
    protected = tmp_path / "protected.env"
    protected.write_text("safe=value\n", encoding="utf-8")
    result = subprocess.CompletedProcess([], returncode, b"private", b"private")
    with patch(
        "trading_platform_api.lineage.docker_local_backup.subprocess.run",
        return_value=result,
    ):
        with pytest.raises(DockerBackupError) as failure:
            _validate_protected_file(protected)

    assert failure.value.code == expected_code
    assert "private" not in str(failure.value)


def test_main_emits_only_stable_diagnostic_fields(
    capsys: pytest.CaptureFixture[str],
) -> None:
    private_detail = "private-path-and-credential"
    with (
        patch(
            "trading_platform_api.lineage.docker_local_backup._parser"
        ) as parser_factory,
        patch(
            "trading_platform_api.lineage.docker_local_backup.run_backup",
            side_effect=DockerBackupError(
                private_detail,
                stage="worker-execution",
                code="BACKUP_WORKER_FAILED",
            ),
        ),
    ):
        parser = parser_factory.return_value
        parser.parse_args.return_value = SimpleNamespace(
            project="spot-test-safe",
            config=Path("protected.env"),
            operation="backup",
            confirm_retained_project=None,
        )
        parser.exit.side_effect = SystemExit(2)
        with pytest.raises(SystemExit, match="2"):
            main()

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == (
        "LOCAL_BACKUP_DIAGNOSTIC stage=worker-execution code=BACKUP_WORKER_FAILED\n"
    )
    assert private_detail not in captured.err


def test_settings_require_external_file_and_reject_duplicate_keys(
    tmp_path: Path,
) -> None:
    env, _, _, _ = _configuration(tmp_path)
    values = _read_env_file(env)
    assert values["TRADING_PLATFORM_PG_DUMP_SERVICE"] == "source"
    duplicate = tmp_path / "duplicate.env"
    duplicate.write_text("DATABASE_URL=first\nDATABASE_URL=second\n", encoding="utf-8")
    duplicate.chmod(0o600)
    with pytest.raises(DockerBackupError, match="repeats"):
        _read_env_file(duplicate)


def test_validation_boundaries_have_stable_categories(tmp_path: Path) -> None:
    env, _, archive, _ = _configuration(tmp_path)
    original = env.read_text(encoding="utf-8")
    env.write_text(f"{original}DATABASE_URL=duplicate\n", encoding="utf-8")
    with pytest.raises(DockerBackupError) as schema_failure:
        _validate_settings(env, "backup")
    assert schema_failure.value.code == "SETTINGS_SCHEMA_INVALID"
    env.write_text(original, encoding="utf-8")

    with patch(
        "trading_platform_api.lineage.docker_local_backup._validate_protected_file",
        side_effect=DockerBackupError("private ACL detail"),
    ):
        with pytest.raises(DockerBackupError) as acl_failure:
            _validate_settings(env, "backup")
    assert acl_failure.value.code == "SETTINGS_ACL_INVALID"

    with patch(
        "trading_platform_api.lineage.docker_local_backup._validate_protected_file",
        side_effect=[None, DockerBackupError("private service ACL detail")],
    ):
        with pytest.raises(DockerBackupError) as service_acl_failure:
            _validate_settings(env, "backup")
    assert service_acl_failure.value.code == "SERVICE_FILE_ACL_INVALID"

    missing = tmp_path / "missing-archive"
    env.write_text(
        env.read_text(encoding="utf-8").replace(str(archive), str(missing)),
        encoding="utf-8",
    )
    with pytest.raises(DockerBackupError) as path_failure:
        _validate_settings(env, "backup")
    assert path_failure.value.code == "PATH_VALIDATION_FAILED"

    encryption_dir = tmp_path / "encryption"
    encryption_dir.mkdir()
    env, _, _, _ = _configuration(encryption_dir)
    env.write_text(
        env.read_text(encoding="utf-8").replace(
            "ENCRYPTION_ACTIVE_KEY_ID=test-key",
            "ENCRYPTION_ACTIVE_KEY_ID=missing-key",
        ),
        encoding="utf-8",
    )
    with pytest.raises(DockerBackupError) as encryption_failure:
        _validate_settings(env, "backup")
    assert encryption_failure.value.code == "ENCRYPTION_CONFIG_INVALID"


def test_restore_service_is_optional_for_backup_configuration(tmp_path: Path) -> None:
    env, _, _, _ = _configuration(tmp_path)
    values = _read_env_file(env)
    assert "TRADING_PLATFORM_PG_RESTORE_SERVICE" not in values


def test_remote_docker_context_is_rejected_even_with_local_host_override() -> None:
    with (
        patch.dict(
            os.environ,
            {
                "DOCKER_CONTEXT": "remote-production",
                "DOCKER_HOST": "unix:///tmp/docker.sock",
            },
            clear=False,
        ),
        patch(
            "trading_platform_api.lineage.docker_local_backup._run_docker",
            return_value="ssh://docker.example.invalid",
        ) as docker,
    ):
        with pytest.raises(DockerBackupError, match="local socket or named pipe"):
            _require_local_docker()
    assert docker.call_args.args[0][:3] == [
        "context",
        "inspect",
        "remote-production",
    ]


def test_source_configuration_is_validated_before_docker_invocation(
    tmp_path: Path,
) -> None:
    env, _, _, _ = _configuration(tmp_path)
    contents = env.read_text(encoding="utf-8")
    env.write_text(
        contents.replace("127.0.0.1:5432/source", "192.168.1.10:5432/source"),
        encoding="utf-8",
    )
    with patch(
        "trading_platform_api.lineage.docker_local_backup._run_docker"
    ) as docker:
        with pytest.raises(DockerBackupError, match="worker loopback") as failure:
            run_backup("spot-test-safe", env, "backup")
    assert failure.value.code == "DATABASE_URL_INVALID"
    docker.assert_not_called()


def test_service_file_rejects_hostaddr_override_before_docker(
    tmp_path: Path,
) -> None:
    env, service, _, _ = _configuration(tmp_path)
    service.write_text(
        service.read_text(encoding="utf-8").replace(
            "host=127.0.0.1", "host=127.0.0.1\nhostaddr=192.168.1.10"
        ),
        encoding="utf-8",
    )
    service.chmod(0o600)
    with patch(
        "trading_platform_api.lineage.docker_local_backup._run_docker"
    ) as docker:
        with pytest.raises(
            DockerBackupError, match="unsupported connection options"
        ) as failure:
            run_backup("spot-test-safe", env, "backup")
    assert failure.value.code == "PG_SERVICE_INVALID"
    docker.assert_not_called()


def test_database_url_rejects_connection_override_before_docker(
    tmp_path: Path,
) -> None:
    env, _, _, _ = _configuration(tmp_path)
    env.write_text(
        env.read_text(encoding="utf-8").replace(
            "/source\n", "/source?host=192.168.1.10\n", 1
        ),
        encoding="utf-8",
    )
    env.chmod(0o600)
    with patch(
        "trading_platform_api.lineage.docker_local_backup._run_docker"
    ) as docker:
        with pytest.raises(
            DockerBackupError, match="DATABASE_URL must include credentials"
        ):
            run_backup("spot-test-safe", env, "backup")
    docker.assert_not_called()


def test_retained_project_requires_explicit_confirmation(tmp_path: Path) -> None:
    env, _, _, _ = _configuration(tmp_path)
    with patch(
        "trading_platform_api.lineage.docker_local_backup._run_docker"
    ) as docker:
        with pytest.raises(
            DockerBackupError, match="require --confirm-retained-project"
        ):
            run_backup("spot-research", env, "backup")
    docker.assert_not_called()


def test_arbitrary_compose_project_is_rejected_before_docker(tmp_path: Path) -> None:
    env, _, _, _ = _configuration(tmp_path)
    with patch(
        "trading_platform_api.lineage.docker_local_backup._run_docker"
    ) as docker:
        with pytest.raises(DockerBackupError, match=r"spot-test-\*"):
            run_backup("unrelated-compose-project", env, "backup")
    docker.assert_not_called()


def test_postgres_identity_requires_private_healthy_expected_volume(
    tmp_path: Path,
) -> None:
    env, _, _, _ = _configuration(tmp_path)
    values = _read_env_file(env)
    container = _postgres_inspect("spot-test-safe")
    volume = {
        "Labels": {
            "com.docker.compose.project": "spot-test-safe",
            "com.docker.compose.volume": "research-data",
        }
    }
    network = {
        "Labels": {
            "com.docker.compose.project": "spot-test-safe",
            "com.docker.compose.network": "database",
        }
    }
    with patch(
        "trading_platform_api.lineage.docker_local_backup._run_docker",
        side_effect=[
            "a" * 64,
            json.dumps([container]),
            json.dumps([volume]),
            json.dumps([network]),
        ],
    ):
        container_id, observed = _inspect_postgres("spot-test-safe", values)
    assert container_id == "a" * 64
    assert observed["Config"]["Labels"]["com.docker.compose.service"] == "postgres"

    exposed = _postgres_inspect(
        "spot-test-safe", ports={"5432/tcp": [{"HostPort": "5432"}]}
    )
    with patch(
        "trading_platform_api.lineage.docker_local_backup._run_docker",
        side_effect=["a" * 64, json.dumps([exposed])],
    ):
        with pytest.raises(DockerBackupError, match="private-port boundary"):
            _inspect_postgres("spot-test-safe", values)


def test_postgres_identity_rejects_a_different_compose_file(
    tmp_path: Path,
) -> None:
    env, _, _, _ = _configuration(tmp_path)
    values = _read_env_file(env)
    container = _postgres_inspect("spot-test-safe")
    container["Config"]["Labels"]["com.docker.compose.project.config_files"] = (
        "/tmp/other-compose.yaml"
    )
    with patch(
        "trading_platform_api.lineage.docker_local_backup._run_docker",
        side_effect=["a" * 64, json.dumps([container])],
    ) as docker:
        with pytest.raises(DockerBackupError, match="private-port boundary"):
            _inspect_postgres("spot-test-safe", values)
    assert docker.call_count == 2


def test_backup_runner_uses_postgres_network_namespace_and_read_only_archive(
    tmp_path: Path,
) -> None:
    env, _, archive, backup = _configuration(tmp_path)
    inspect = _postgres_inspect("spot-test-safe")
    with (
        patch("trading_platform_api.lineage.docker_local_backup._require_local_docker"),
        patch(
            "trading_platform_api.lineage.docker_local_backup._inspect_postgres",
            return_value=("a" * 64, inspect),
        ),
        patch(
            "trading_platform_api.lineage.docker_local_backup._run_docker",
            side_effect=["", "Backup verified: key=key sha256=digest", ""],
        ) as docker,
    ):
        output = run_backup("spot-test-safe", env, "backup")

    assert output == "Backup verified: key=key sha256=digest"
    build_args = docker.call_args_list[0].args[0]
    run_args = docker.call_args_list[1].args[0]
    assert build_args[:2] == ["build", "--quiet"]
    assert run_args[run_args.index("--network") + 1] == "container:" + "a" * 64
    assert run_args[run_args.index("--user") + 1] == _worker_user()
    assert run_args[run_args.index("--cap-drop") + 1] == "ALL"
    assert run_args[run_args.index("--security-opt") + 1] == "no-new-privileges"
    assert docker.call_args_list[2].args[0][0:3] == ["ps", "--all", "--quiet"]
    assert run_args[run_args.index("--mount") + 1].endswith(
        f"source={archive.as_posix()},target=/backup/archive,readonly"
    )
    assert run_args[
        run_args.index("--mount", run_args.index("--mount") + 1) + 1
    ].endswith(f"source={backup.as_posix()},target=/backup/bundles")
    assert "-p" not in run_args and "--publish" not in run_args


def test_failed_worker_is_removed_only_after_run_label_verification(
    tmp_path: Path,
) -> None:
    env, _, _, _ = _configuration(tmp_path)
    postgres = _postgres_inspect("spot-test-safe")
    worker = {
        "Config": {
            "Labels": {
                "com.trading-platform.backup-runner": "true",
                "com.trading-platform.backup-run-id": "run-id",
            }
        }
    }
    with (
        patch("trading_platform_api.lineage.docker_local_backup._require_local_docker"),
        patch(
            "trading_platform_api.lineage.docker_local_backup._inspect_postgres",
            return_value=("a" * 64, postgres),
        ),
        patch("trading_platform_api.lineage.docker_local_backup.uuid.uuid4") as uuid4,
        patch(
            "trading_platform_api.lineage.docker_local_backup._run_docker",
            side_effect=[
                "",
                DockerBackupError("simulated timeout"),
                "b" * 64,
                json.dumps([worker]),
                "",
                "",
            ],
        ) as docker,
    ):
        uuid4.return_value.hex = "run-id"
        with pytest.raises(DockerBackupError, match="simulated timeout"):
            run_backup("spot-test-safe", env, "backup")

    cleanup_call = docker.call_args_list[4].args[0]
    assert cleanup_call[:3] == ["rm", "--force", "lineage-backup-run-id"]
    assert docker.call_args_list[5].args[0][-1] == (
        "label=com.trading-platform.backup-run-id=run-id"
    )


@pytest.mark.skipif(
    os.name == "nt", reason="POSIX file-mode validation is Windows-specific"
)
def test_posix_backup_files_require_exact_0600(tmp_path: Path) -> None:
    protected = tmp_path / "protected.env"
    protected.write_text("safe=value\n", encoding="utf-8")
    protected.chmod(0o600)
    _validate_protected_file(protected)
    protected.chmod(0o644)
    with pytest.raises(DockerBackupError, match="mode 0600"):
        _validate_protected_file(protected)


@pytest.mark.skipif(os.name != "nt", reason="Windows ACL validation requires Windows")
def test_windows_backup_acl_accepts_owner_protected_temp_file(tmp_path: Path) -> None:
    protected = tmp_path / "protected.env"
    protected.write_text("safe=value\n", encoding="utf-8")
    _protect_windows_test_file(protected)
    _validate_protected_file(protected)


@pytest.mark.skipif(os.name != "nt", reason="Windows ACL validation requires Windows")
def test_windows_backup_acl_rejects_broad_everyone_access(tmp_path: Path) -> None:
    protected = tmp_path / "protected.env"
    protected.write_text("safe=value\n", encoding="utf-8")
    _protect_windows_test_file(protected)
    result = subprocess.run(
        ["icacls.exe", str(protected), "/grant", "*S-1-1-0:R"],
        capture_output=True,
        check=False,
        timeout=10,
    )
    if result.returncode:
        pytest.skip("Could not create a disposable broad-access ACL fixture.")
    with pytest.raises(DockerBackupError, match="ACL is not owner-restricted"):
        _validate_protected_file(protected)
