"""Disposable offline Compose acceptance test; invoked explicitly by Product CI."""

from __future__ import annotations

import json
import subprocess
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[2]


def compose(*args: str) -> str:
    return subprocess.check_output(
        ["docker", "compose", *args], cwd=ROOT, text=True
    ).strip()


def inspect(service: str) -> dict:
    container_id = compose("ps", "--all", "--quiet", service)
    return json.loads(
        subprocess.check_output(["docker", "inspect", container_id], text=True)
    )[0]


def database(sql: str) -> str:
    return compose(
        "exec",
        "-T",
        "postgres",
        "sh",
        "-c",
        'exec psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Atc "$1"',
        "--",
        sql,
    )


class LocalStackAcceptanceTests(unittest.TestCase):
    def test_offline_stack_and_persistence(self) -> None:
        config = json.loads(compose("config", "--format", "json"))
        self.assertEqual(set(config["services"]), {"web", "api", "migrate", "postgres"})
        web_env = config["services"]["web"]["environment"]
        host, port = web_env["LOCAL_WEB_HOST"], web_env["LOCAL_WEB_PORT"]
        origin = f"http://{host}" if port == "80" else f"http://{host}:{port}"
        secret = web_env["LOCAL_PROXY_SECRET"]
        self.assertEqual(
            config["services"]["api"]["environment"][
                "TRADING_PLATFORM_BINANCE_SPOT_ENABLED"
            ],
            "false",
        )
        for service in ("api", "postgres", "migrate"):
            self.assertFalse(config["services"][service].get("ports"))
            self.assertFalse(inspect(service)["HostConfig"]["PortBindings"])
        for service in ("postgres", "migrate"):
            self.assertNotIn(
                "LOCAL_PROXY_SECRET", config["services"][service]["environment"]
            )
        binding = inspect("web")["HostConfig"]["PortBindings"]["8080/tcp"]
        self.assertEqual(binding, [{"HostIp": host, "HostPort": port}])
        self.assertEqual(inspect("migrate")["State"]["ExitCode"], 0)
        self.assertEqual(inspect("migrate")["State"]["Status"], "exited")
        for service in ("web", "api", "postgres"):
            self.assertEqual(inspect(service)["State"]["Health"]["Status"], "healthy")
        web_networks = set(inspect("web")["NetworkSettings"]["Networks"])
        db_networks = set(inspect("postgres")["NetworkSettings"]["Networks"])
        self.assertFalse(web_networks & db_networks)

        def get(path: str, headers: dict | None = None) -> bytes:
            with urlopen(
                Request(origin + path, headers=headers or {}), timeout=10
            ) as response:
                if path.endswith(".mjs"):
                    self.assertEqual(
                        response.headers.get_content_type(), "application/javascript"
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
            self.assertNotIn(secret.encode(), content)
        self.assertIn(b'API_ORIGIN = ""', get("/src/runtime-config.mjs"))
        self.assertEqual(json.loads(get("/api/health"))["status"], "HEALTHY")
        symbols = json.loads(get("/api/research/spot/symbols"))
        self.assertEqual(len(symbols["instruments"]), 5)
        instrument = symbols["instruments"][0]["instrument_id"]
        # This read reaches the migrated database but invents no market data.
        with self.assertRaises(HTTPError) as missing:
            get(f"/api/research/spot/{instrument}/candles?timeframe=1m&limit=2")
        self.assertEqual(missing.exception.code, 404)
        end = datetime.now(UTC).replace(second=0, microsecond=0) - timedelta(minutes=1)
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
                "X-Correlation-ID": "00000000-0000-4000-8000-000000000360",
            },
            method="POST",
        )
        with self.assertRaises(HTTPError) as disabled:
            urlopen(refresh, timeout=10)
        self.assertEqual(disabled.exception.code, 403)
        self.assertEqual(
            json.loads(disabled.exception.read())["code"], "COLLECTION_NOT_ENABLED"
        )
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
        logs = compose("logs", "--no-color", "api", "web")
        self.assertIn("refresh_request_received", logs)
        self.assertIn("proxy_response_completed", logs)
        self.assertIn("00000000-0000-4000-8000-000000000360", logs)
        self.assertIn(fallback_id, logs)
        self.assertNotIn(canary, logs)
        # The proxy must overwrite a spoofed browser credential.
        spoofed_headers = {
            "X-Local-Proxy-Secret": "wrong"  # pragma: allowlist secret
        }
        self.assertEqual(
            json.loads(get("/api/health", spoofed_headers))["status"], "HEALTHY"
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
        # Direct access from the API container has no trusted proxy credential.
        self.assertIn(
            "421",
            compose(
                "exec",
                "-T",
                "api",
                "python",
                "-c",
                "import urllib.request, urllib.error; "
                "r=urllib.request.Request('http://127.0.0.1:8000/health'); "
                "\ntry: urllib.request.urlopen(r)\n"
                "except urllib.error.HTTPError as e: print(e.code)",
            ),
        )
        self.assertEqual(
            database("SELECT version_num FROM alembic_version"),
            "0008_spot_analysis_lineage",
        )
        # This is an infrastructure probe, not fabricated market/research data.
        database("CREATE TABLE docker_ci_persistence_probe (id integer PRIMARY KEY)")
        database("INSERT INTO docker_ci_persistence_probe VALUES (1)")
        volume = inspect("postgres")["Mounts"][0]["Name"]
        compose("down")
        compose("up", "--wait", "--wait-timeout", "180")
        self.assertEqual(inspect("postgres")["Mounts"][0]["Name"], volume)
        self.assertEqual(database("SELECT id FROM docker_ci_persistence_probe"), "1")
        database("DROP TABLE docker_ci_persistence_probe")
        self.assertEqual(json.loads(get("/api/health"))["status"], "HEALTHY")


if __name__ == "__main__":
    unittest.main()
