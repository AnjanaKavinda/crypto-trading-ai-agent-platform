"""Run the offline Compose acceptance test in a disposable project.

This entry point owns its temporary settings, Compose project, containers,
networks, and database volume. It never reads or writes the repository's .env.
"""

from __future__ import annotations

import json
import os
import re
import secrets
import socket
import subprocess
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest import mock
from urllib.error import HTTPError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[2]
COMPOSE_FILE = ROOT / "compose.yaml"
ENV_EXAMPLE = ROOT / ".env.example"
RETAINED_PROJECT = "spot-research"
RETAINED_VOLUME = "spot-research_research-data"
COMMAND_TIMEOUT_SECONDS = 180
DOCKER_PREFLIGHT_TIMEOUT_SECONDS = 10
PROJECT_NAME_PATTERN = re.compile(r"[a-z0-9][a-z0-9_-]*\Z")


def _run(
    command: list[str],
    *,
    cwd: Path = ROOT,
    env: dict[str, str] | None = None,
    timeout: int = COMMAND_TIMEOUT_SECONDS,
    operation: str,
) -> subprocess.CompletedProcess[str]:
    """Run a Docker command without echoing arguments, output, or settings."""
    try:
        result = subprocess.run(
            command,
            cwd=cwd,
            env=env,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except FileNotFoundError:
        raise RuntimeError("Docker CLI is not available on PATH.") from None
    except subprocess.TimeoutExpired:
        raise RuntimeError(
            f"{operation} did not finish within {timeout} seconds; "
            "no retry was attempted."
        ) from None
    if result.returncode:
        raise RuntimeError(
            f"{operation} failed with exit code {result.returncode}; "
            "command output is suppressed to avoid exposing local settings."
        )
    return result


def _parse_env_example(path: Path = ENV_EXAMPLE) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        key, separator, value = line.partition("=")
        if not separator or not key.strip():
            raise ValueError("The documented local settings example is malformed.")
        values[key.strip()] = value
    return values


def _choose_loopback_port() -> str:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return str(probe.getsockname()[1])


def _project_name() -> str:
    return f"spot-test-{secrets.token_hex(8)}"


def _require_local_docker_endpoint(endpoint: str) -> None:
    if not endpoint.startswith(("unix://", "npipe://")):
        raise RuntimeError(
            "The selected Docker endpoint is not a local Unix socket or Windows "
            "named pipe; refusing to run the acceptance test."
        )


def _compose_child_environment(setting_names: set[str]) -> dict[str, str]:
    env = os.environ.copy()
    for key in tuple(env):
        if key.startswith("COMPOSE_") or key in setting_names:
            env.pop(key, None)
    return env


def _docker_output(
    *args: str,
    timeout: int = COMMAND_TIMEOUT_SECONDS,
    operation: str,
) -> str:
    result = _run(
        ["docker", *args],
        timeout=timeout,
        operation=operation,
    )
    return result.stdout.strip()


class DisposableComposeProject:
    """Own one uniquely named Compose project and verify scoped cleanup."""

    def __init__(self) -> None:
        self.project = _project_name()
        if self.project == RETAINED_PROJECT or not PROJECT_NAME_PATTERN.fullmatch(
            self.project
        ):
            raise RuntimeError("Generated Compose project name is unsafe.")
        self._temporary: tempfile.TemporaryDirectory[str] | None = None
        self.settings_path: Path | None = None
        self._setting_names: set[str] = set()
        self._child_env: dict[str, str] = {}
        self._may_have_resources = False
        self._retained_before: dict[str, str] | None = None

    def __enter__(self) -> DisposableComposeProject:
        self._check_docker_responsive()
        self._retained_before = self._retained_inventory()
        self._assert_project_empty(self.project)
        self._temporary = tempfile.TemporaryDirectory(prefix="spot-research-test-")
        try:
            self.settings_path = Path(self._temporary.name) / "compose.env"
            self._write_temporary_settings(self.settings_path)
            self._child_env = _compose_child_environment(self._setting_names)
            self.compose("config", "--quiet", operation="validate isolated Compose")
        except Exception:
            self._temporary.cleanup()
            self._temporary = None
            raise
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> bool:
        cleanup_error: Exception | None = None
        try:
            if self._may_have_resources:
                self._remove_owned_project()
            if self._retained_before != self._retained_inventory():
                raise RuntimeError(
                    "Retained spot-research container or volume identities changed "
                    "during the isolated acceptance test."
                )
        except Exception as error:
            cleanup_error = error
        finally:
            if self._temporary is not None:
                self._temporary.cleanup()
        if cleanup_error is not None:
            if exc is not None:
                raise RuntimeError(
                    "The acceptance test failed and its isolated cleanup or "
                    "retained-resource verification also failed."
                ) from cleanup_error
            raise cleanup_error
        return False

    @property
    def origin(self) -> str:
        if self.settings_path is None:
            raise RuntimeError("Temporary Compose settings are unavailable.")
        values = _parse_env_example(self.settings_path)
        return values["TRADING_PLATFORM_FRONTEND_ORIGIN"]

    def compose(self, *args: str, operation: str) -> str:
        if self.settings_path is None:
            raise RuntimeError("Isolated Compose settings are not initialized.")
        command = [
            "docker",
            "compose",
            "--project-name",
            self.project,
            "--project-directory",
            str(ROOT),
            "--env-file",
            str(self.settings_path),
            "--file",
            str(COMPOSE_FILE),
            *args,
        ]
        result = _run(
            command,
            env=self._child_env,
            operation=operation,
        )
        return result.stdout.strip()

    def start(self) -> None:
        self._may_have_resources = True
        self.compose(
            "up",
            "--build",
            "--detach",
            "--wait",
            "--wait-timeout",
            "180",
            operation="start isolated offline Compose project",
        )
        self._assert_owned_project(self.project)

    def inspect(self, service: str) -> dict:
        container_ids = self.compose(
            "ps",
            "--all",
            "--quiet",
            service,
            operation=f"locate isolated {service} container",
        ).splitlines()
        if len(container_ids) != 1:
            raise RuntimeError(
                f"Expected one isolated {service} container; found {len(container_ids)}."
            )
        raw = _docker_output(
            "inspect",
            container_ids[0],
            operation=f"inspect isolated {service} container",
        )
        data = json.loads(raw)
        if len(data) != 1:
            raise RuntimeError(f"Could not uniquely inspect isolated {service}.")
        labels = data[0].get("Config", {}).get("Labels", {}) or {}
        if labels.get("com.docker.compose.project") != self.project:
            raise RuntimeError(
                f"Refusing to use {service}; its Compose ownership is unverified."
            )
        return data[0]

    def database(self, sql: str) -> str:
        return self.compose(
            "exec",
            "--no-TTY",
            "postgres",
            "sh",
            "-c",
            'exec psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" '
            '-d "$POSTGRES_DB" -Atc "$1"',
            "--",
            sql,
            operation="query isolated test database",
        )

    def restart_preserving_volume(self, volume_name: str) -> None:
        self._assert_owned_project(self.project)
        before = self._volume_identity(volume_name)
        self.compose("down", operation="stop isolated project for persistence check")
        after_down = self._volume_identity(volume_name)
        if before != after_down:
            raise RuntimeError(
                "The isolated database volume identity changed during the "
                "persistence restart."
            )
        self.compose(
            "up",
            "--detach",
            "--wait",
            "--wait-timeout",
            "180",
            operation="restart isolated project for persistence check",
        )
        postgres = self.inspect("postgres")
        mounted = self._postgres_data_volume(postgres)
        if mounted != volume_name or self._volume_identity(volume_name) != before:
            raise RuntimeError(
                "The isolated PostgreSQL volume was replaced during restart."
            )

    @staticmethod
    def _postgres_data_volume(container: dict) -> str:
        mounts = [
            mount
            for mount in container.get("Mounts", [])
            if mount.get("Destination") == "/var/lib/postgresql/data"
        ]
        if len(mounts) != 1 or mounts[0].get("Type") != "volume":
            raise RuntimeError(
                "The isolated PostgreSQL data mount is missing or not a Docker volume."
            )
        return str(mounts[0].get("Name", ""))

    def _check_docker_responsive(self) -> None:
        docker_host = os.environ.get("DOCKER_HOST")
        if docker_host:
            endpoint = docker_host
        else:
            context = _docker_output(
                "context",
                "show",
                timeout=DOCKER_PREFLIGHT_TIMEOUT_SECONDS,
                operation="identify the active local Docker context",
            )
            endpoint = _docker_output(
                "context",
                "inspect",
                context,
                "--format",
                "{{.Endpoints.docker.Host}}",
                timeout=DOCKER_PREFLIGHT_TIMEOUT_SECONDS,
                operation="verify the active Docker endpoint is local",
            )
        _require_local_docker_endpoint(endpoint)
        _docker_output(
            "version",
            "--format",
            "{{.Server.Version}}",
            timeout=DOCKER_PREFLIGHT_TIMEOUT_SECONDS,
            operation="check Docker Desktop responsiveness",
        )

    def _write_temporary_settings(self, path: Path) -> None:
        values = _parse_env_example()
        self._setting_names = set(values)
        compose_variables = set(
            re.findall(
                r"\$\{([A-Z][A-Z0-9_]*)",
                COMPOSE_FILE.read_text(encoding="utf-8"),
            )
        )
        if not compose_variables.issubset(values):
            raise RuntimeError(
                "Compose references settings missing from the documented "
                "environment example; refusing to inherit process values."
            )
        web_port = _choose_loopback_port()
        overrides = {
            "POSTGRES_PASSWORD": secrets.token_hex(24),
            "LOCAL_PROXY_SECRET": secrets.token_hex(32),
            "LOCAL_WEB_HOST": "127.0.0.1",
            "LOCAL_WEB_PORT": web_port,
            "TRADING_PLATFORM_FRONTEND_ORIGIN": f"http://127.0.0.1:{web_port}",
            "TRADING_PLATFORM_MODE": "research",
            "ENABLE_LIVE_TRADING": "false",
            "ENABLE_AUTO_EXECUTION": "false",
            "TRADING_PLATFORM_BINANCE_SPOT_ENABLED": "false",
        }
        missing = overrides.keys() - values.keys()
        if missing:
            raise RuntimeError(
                "The documented environment example is missing required local "
                "acceptance settings."
            )
        values.update(overrides)
        rendered: list[str] = []
        for raw_line in ENV_EXAMPLE.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#"):
                rendered.append(raw_line)
                continue
            key, _, _ = line.partition("=")
            rendered.append(f"{key.strip()}={values[key.strip()]}")
        path.write_text("\n".join(rendered) + "\n", encoding="utf-8")
        try:
            path.chmod(0o600)
        except OSError:
            # The file contains generated disposable settings only. Compose
            # receives its explicit path; no owner configuration is involved.
            pass

    def _retained_inventory(self) -> dict[str, str]:
        containers = _docker_output(
            "ps",
            "--all",
            "--filter",
            f"label=com.docker.compose.project={RETAINED_PROJECT}",
            "--format",
            "{{.ID}}|{{.Names}}|{{.Image}}",
            timeout=DOCKER_PREFLIGHT_TIMEOUT_SECONDS,
            operation="snapshot retained Compose container identities",
        )
        networks = _docker_output(
            "network",
            "ls",
            "--filter",
            f"label=com.docker.compose.project={RETAINED_PROJECT}",
            "--format",
            "{{.ID}}|{{.Name}}",
            timeout=DOCKER_PREFLIGHT_TIMEOUT_SECONDS,
            operation="snapshot retained Compose network identities",
        )
        volumes = _docker_output(
            "volume",
            "ls",
            "--filter",
            f"label=com.docker.compose.project={RETAINED_PROJECT}",
            "--format",
            "{{.Name}}",
            timeout=DOCKER_PREFLIGHT_TIMEOUT_SECONDS,
            operation="snapshot retained Compose volume identities",
        )
        all_volumes = _docker_output(
            "volume",
            "ls",
            "--format",
            "{{.Name}}",
            timeout=DOCKER_PREFLIGHT_TIMEOUT_SECONDS,
            operation="check retained PostgreSQL volume existence",
        ).splitlines()
        primary_volume = "<absent>"
        if RETAINED_VOLUME in all_volumes:
            primary_volume = _docker_output(
                "volume",
                "inspect",
                "--format",
                "{{.Name}}|{{.Driver}}|{{.Mountpoint}}|{{json .Labels}}",
                RETAINED_VOLUME,
                timeout=DOCKER_PREFLIGHT_TIMEOUT_SECONDS,
                operation="snapshot retained PostgreSQL volume identity",
            )
        return {
            "containers": containers,
            "networks": networks,
            "volumes": volumes,
            "primary_volume": primary_volume if primary_volume else "<absent>",
        }

    def _project_resources(self, project: str) -> dict[str, list[str]]:
        return {
            "containers": _docker_output(
                "ps",
                "--all",
                "--filter",
                f"label=com.docker.compose.project={project}",
                "--format",
                "{{.ID}}",
                timeout=DOCKER_PREFLIGHT_TIMEOUT_SECONDS,
                operation=f"list containers owned by {project}",
            ).splitlines(),
            "networks": _docker_output(
                "network",
                "ls",
                "--filter",
                f"label=com.docker.compose.project={project}",
                "--format",
                "{{.ID}}",
                timeout=DOCKER_PREFLIGHT_TIMEOUT_SECONDS,
                operation=f"list networks owned by {project}",
            ).splitlines(),
            "volumes": _docker_output(
                "volume",
                "ls",
                "--filter",
                f"label=com.docker.compose.project={project}",
                "--format",
                "{{.Name}}",
                timeout=DOCKER_PREFLIGHT_TIMEOUT_SECONDS,
                operation=f"list volumes owned by {project}",
            ).splitlines(),
        }

    def _assert_project_empty(self, project: str) -> None:
        resources = self._project_resources(project)
        if any(resources.values()):
            raise RuntimeError(
                "Generated Compose project name is already in use; "
                "refusing to start or clean it."
            )

    def _assert_owned_project(self, project: str) -> None:
        resources = self._project_resources(project)
        for container_id in resources["containers"]:
            labels_raw = _docker_output(
                "inspect",
                "--format",
                "{{index .Config.Labels \"com.docker.compose.project\"}}",
                container_id,
                operation="verify disposable container ownership",
            )
            if labels_raw != project:
                raise RuntimeError(
                    "Refusing cleanup because a container's project ownership "
                    "cannot be proven."
                )
        for network_id in resources["networks"]:
            labels_raw = _docker_output(
                "network",
                "inspect",
                "--format",
                "{{index .Labels \"com.docker.compose.project\"}}",
                network_id,
                operation="verify disposable network ownership",
            )
            if labels_raw != project:
                raise RuntimeError(
                    "Refusing cleanup because a network's project ownership "
                    "cannot be proven."
                )
        for volume_name in resources["volumes"]:
            labels_raw = _docker_output(
                "volume",
                "inspect",
                "--format",
                "{{index .Labels \"com.docker.compose.project\"}}",
                volume_name,
                operation="verify disposable volume ownership",
            )
            if labels_raw != project:
                raise RuntimeError(
                    "Refusing cleanup because a volume's project ownership "
                    "cannot be proven."
                )

    def _volume_identity(self, volume_name: str) -> str:
        identity = _docker_output(
            "volume",
            "inspect",
            "--format",
            "{{.Name}}|{{.Driver}}|{{.Mountpoint}}|{{json .Labels}}",
            volume_name,
            operation="verify isolated PostgreSQL volume identity",
        )
        labels_raw = _docker_output(
            "volume",
            "inspect",
            "--format",
            "{{index .Labels \"com.docker.compose.project\"}}",
            volume_name,
            operation="verify isolated PostgreSQL volume ownership",
        )
        if labels_raw != self.project or volume_name == RETAINED_VOLUME:
            raise RuntimeError(
                "Refusing to use a database volume without isolated project ownership."
            )
        return identity

    def _remove_owned_project(self) -> None:
        self._assert_owned_project(self.project)
        self.compose(
            "down",
            "--volumes",
            "--remove-orphans",
            operation="remove only the isolated Compose project",
        )
        remaining = self._project_resources(self.project)
        if any(remaining.values()):
            raise RuntimeError(
                "Isolated Compose resources remain after project-scoped cleanup."
            )


class LocalStackHarnessUnitTests(unittest.TestCase):
    def test_compose_project_name_is_unique_and_valid(self) -> None:
        project = _project_name()
        self.assertNotEqual(project, RETAINED_PROJECT)
        self.assertRegex(project, PROJECT_NAME_PATTERN)
        self.assertNotEqual(project, _project_name())

    def test_only_local_docker_sockets_are_accepted(self) -> None:
        for endpoint in (
            "unix:///var/run/docker.sock",
            "npipe:////./pipe/docker_engine",
        ):
            _require_local_docker_endpoint(endpoint)
        for endpoint in ("tcp://localhost:2376", "ssh://docker-host"):
            with self.assertRaises(RuntimeError):
                _require_local_docker_endpoint(endpoint)

    def test_compose_commands_always_use_the_isolated_project_and_settings(self) -> None:
        with tempfile.TemporaryDirectory(prefix="spot-compose-args-") as temp:
            settings = Path(temp) / "compose.env"
            stack = DisposableComposeProject()
            stack.settings_path = settings
            stack._child_env = {}
            with mock.patch(
                f"{__name__}._run",
                return_value=subprocess.CompletedProcess([], 0, "ok", ""),
            ) as run:
                stack.compose("ps", "--all", operation="inspect test project")
        command = run.call_args.args[0]
        self.assertEqual(command[0:2], ["docker", "compose"])
        self.assertEqual(command[2:4], ["--project-name", stack.project])
        self.assertIn("--env-file", command)
        self.assertEqual(command[command.index("--env-file") + 1], str(settings))
        self.assertIn("--project-directory", command)
        self.assertIn("--file", command)
        self.assertNotEqual(stack.project, RETAINED_PROJECT)

    def test_compose_child_environment_removes_project_and_setting_overrides(self) -> None:
        setting_names = {"LOCAL_WEB_PORT", "POSTGRES_PASSWORD"}
        with mock.patch.dict(
            os.environ,
            {
                "COMPOSE_PROJECT_NAME": RETAINED_PROJECT,
                "COMPOSE_FILE": "compose.yaml",
                "LOCAL_WEB_PORT": "5173",
                "POSTGRES_PASSWORD": "must-not-be-used",
                "DOCKER_CONTEXT": "desktop-linux",
            },
            clear=False,
        ):
            child = _compose_child_environment(setting_names)
        self.assertNotIn("COMPOSE_PROJECT_NAME", child)
        self.assertNotIn("COMPOSE_FILE", child)
        self.assertNotIn("LOCAL_WEB_PORT", child)
        self.assertNotIn("POSTGRES_PASSWORD", child)
        self.assertEqual(child["DOCKER_CONTEXT"], "desktop-linux")

    def test_generated_settings_are_research_only_and_loopback_bound(self) -> None:
        with tempfile.TemporaryDirectory(prefix="spot-research-settings-test-") as temp:
            path = Path(temp) / "compose.env"
            harness = DisposableComposeProject()
            harness._write_temporary_settings(path)
            values = _parse_env_example(path)
        self.assertEqual(values["LOCAL_WEB_HOST"], "127.0.0.1")
        self.assertRegex(values["LOCAL_WEB_PORT"], r"^[0-9]+$")
        self.assertEqual(
            values["TRADING_PLATFORM_FRONTEND_ORIGIN"],
            f"http://127.0.0.1:{values['LOCAL_WEB_PORT']}",
        )
        self.assertEqual(values["TRADING_PLATFORM_MODE"], "research")
        self.assertEqual(values["ENABLE_LIVE_TRADING"], "false")
        self.assertEqual(values["ENABLE_AUTO_EXECUTION"], "false")
        self.assertEqual(values["TRADING_PLATFORM_BINANCE_SPOT_ENABLED"], "false")
        self.assertRegex(values["LOCAL_PROXY_SECRET"], r"^[0-9a-f]{64}$")
        self.assertRegex(values["POSTGRES_PASSWORD"], r"^[0-9a-f]{48}$")


class LocalStackAcceptanceTests(unittest.TestCase):
    def test_offline_stack_and_persistence(self) -> None:
        with DisposableComposeProject() as stack:
            stack.start()
            config = json.loads(
                stack.compose(
                    "config",
                    "--format",
                    "json",
                    operation="read isolated Compose service configuration",
                )
            )
            self.assertEqual(
                set(config["services"]), {"web", "api", "migrate", "postgres"}
            )
            web_env = config["services"]["web"]["environment"]
            host, port = web_env["LOCAL_WEB_HOST"], web_env["LOCAL_WEB_PORT"]
            origin = stack.origin
            secret = web_env["LOCAL_PROXY_SECRET"]
            self.assertEqual(host, "127.0.0.1")
            self.assertEqual(
                config["services"]["api"]["environment"][
                    "TRADING_PLATFORM_BINANCE_SPOT_ENABLED"
                ],
                "false",
            )
            for service in ("api", "postgres", "migrate"):
                self.assertFalse(
                    config["services"][service].get("ports"),
                    f"{service} must not publish a host port",
                )
                self.assertFalse(
                    stack.inspect(service)["HostConfig"]["PortBindings"],
                    f"{service} must not publish a host port",
                )
            for service in ("postgres", "migrate"):
                self.assertNotIn(
                    "LOCAL_PROXY_SECRET",
                    config["services"][service]["environment"],
                )
            binding = stack.inspect("web")["HostConfig"]["PortBindings"]["8080/tcp"]
            self.assertEqual(binding, [{"HostIp": host, "HostPort": port}])
            self.assertEqual(stack.inspect("migrate")["State"]["ExitCode"], 0)
            self.assertEqual(stack.inspect("migrate")["State"]["Status"], "exited")
            for service in ("web", "api", "postgres"):
                self.assertEqual(
                    stack.inspect(service)["State"]["Health"]["Status"], "healthy"
                )
            web_networks = set(
                stack.inspect("web")["NetworkSettings"]["Networks"]
            )
            db_networks = set(
                stack.inspect("postgres")["NetworkSettings"]["Networks"]
            )
            self.assertFalse(web_networks & db_networks)

            postgres = stack.inspect("postgres")
            volume_name = stack._postgres_data_volume(postgres)
            self.assertNotEqual(volume_name, RETAINED_VOLUME)
            self.assertTrue(stack._volume_identity(volume_name))

            def get(path: str, headers: dict | None = None) -> bytes:
                with urlopen(
                    Request(origin + path, headers=headers or {}), timeout=10
                ) as response:
                    if path.endswith(".mjs"):
                        self.assertEqual(
                            response.headers.get_content_type(),
                            "application/javascript",
                        )
                    return response.read()

            for path in (
                "/",
                "/watchlist.html",
                "/src/research-api.mjs",
                "/src/runtime-config.mjs",
                "/src/app.mjs",
                "/src/watchlist.mjs",
            ):
                content = get(path)
                self.assertTrue(content)
                if secret.encode() in content:
                    self.fail("A generated proxy secret was exposed by the web app.")
            self.assertIn(b'API_ORIGIN = ""', get("/src/runtime-config.mjs"))
            self.assertEqual(json.loads(get("/api/health"))["status"], "HEALTHY")
            symbols = json.loads(get("/api/research/spot/symbols"))
            self.assertEqual(len(symbols["instruments"]), 5)
            instrument = symbols["instruments"][0]["instrument_id"]
            # This read reaches only the disposable migrated database.
            with self.assertRaises(HTTPError) as missing:
                get(f"/api/research/spot/{instrument}/candles?timeframe=1m&limit=2")
            self.assertEqual(missing.exception.code, 404)
            end = datetime.now(UTC).replace(second=0, microsecond=0) - timedelta(
                minutes=1
            )
            body = json.dumps(
                {
                    "timeframe": "1m",
                    "coverage_start": (end - timedelta(minutes=2)).isoformat(),
                    "coverage_end": end.isoformat(),
                    "limit": 2,
                }
            ).encode()
            refresh = Request(
                origin + f"/api/research/spot/{instrument}/refresh",
                data=body,
                headers={
                    "Content-Type": "application/json",
                    "Origin": origin,
                    "X-Correlation-ID": (
                        "00000000-0000-4000-8000-000000000360"
                    ),
                },
                method="POST",
            )
            with self.assertRaises(HTTPError) as disabled:
                urlopen(refresh, timeout=10)
            self.assertEqual(disabled.exception.code, 403)
            disabled_body = json.loads(disabled.exception.read())
            self.assertEqual(disabled_body["code"], "COLLECTION_NOT_ENABLED")
            self.assertEqual(
                disabled.exception.headers.get("X-Correlation-ID"),
                "00000000-0000-4000-8000-000000000360",
            )
            canary = "secret-canary-not-a-valid-uuid"  # pragma: allowlist secret
            invalid_refresh = Request(
                origin + f"/api/research/spot/{instrument}/refresh",
                data=body,
                headers={
                    "Content-Type": "application/json",
                    "Origin": origin,
                    "X-Correlation-ID": canary,
                },
                method="POST",
            )
            with self.assertRaises(HTTPError) as invalid_id:
                urlopen(invalid_refresh, timeout=10)
            fallback_id = invalid_id.exception.headers.get("X-Correlation-ID")
            self.assertRegex(fallback_id or "", r"^[0-9a-f]{32}$")
            logs = stack.compose(
                "logs",
                "--no-color",
                "api",
                "web",
                operation="read isolated application logs",
            )
            expected_log_events = (
                "refresh_request_received",
                "proxy_response_completed",
                "00000000-0000-4000-8000-000000000360",
                fallback_id,
            )
            if any(event not in logs for event in expected_log_events):
                self.fail("Expected sanitized lifecycle evidence was absent from logs.")
            if canary in logs:
                self.fail("Invalid correlation ID was present in isolated logs.")
            # The proxy must overwrite a spoofed browser credential.
            spoofed_headers = {
                "X-Local-Proxy-Secret": "wrong"  # pragma: allowlist secret
            }
            self.assertEqual(
                json.loads(get("/api/health", spoofed_headers))["status"],
                "HEALTHY",
            )
            for headers in (
                {"Host": "evil.invalid"},
                {"Host": "192.168.1.2:5173"},
                {"Origin": "http://evil.invalid"},
                {"Origin": "null"},
            ):
                with self.assertRaises(HTTPError) as error:
                    get("/api/health", headers)
                self.assertIn(error.exception.code, (403, 421))
            # Direct API access has no trusted proxy credential.
            self.assertIn(
                "421",
                stack.compose(
                    "exec",
                    "--no-TTY",
                    "api",
                    "python",
                    "-c",
                    "import urllib.request, urllib.error; "
                    "r=urllib.request.Request('http://127.0.0.1:8000/health'); "
                    "\ntry: urllib.request.urlopen(r)\n"
                    "except urllib.error.HTTPError as e: print(e.code)",
                    operation="verify isolated API proxy boundary",
                ),
            )
            self.assertEqual(
                stack.database("SELECT version_num FROM alembic_version"),
                "0008_spot_analysis_lineage",
            )
            # This is an infrastructure probe, not market or research data.
            stack.database(
                "CREATE TABLE docker_ci_persistence_probe (id integer PRIMARY KEY)"
            )
            stack.database("INSERT INTO docker_ci_persistence_probe VALUES (1)")
            stack.restart_preserving_volume(volume_name)
            self.assertEqual(
                stack.database("SELECT id FROM docker_ci_persistence_probe"), "1"
            )
            stack.database("DROP TABLE docker_ci_persistence_probe")
            self.assertEqual(json.loads(get("/api/health"))["status"], "HEALTHY")


if __name__ == "__main__":
    unittest.main()
