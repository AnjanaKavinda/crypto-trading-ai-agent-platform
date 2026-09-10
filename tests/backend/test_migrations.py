from __future__ import annotations

import importlib.util
import io
from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory

REPO_ROOT = Path(__file__).resolve().parents[2]
ALEMBIC_INI_PATH = REPO_ROOT / "apps/api/alembic.ini"
VERSIONS_DIR = REPO_ROOT / "apps/api/migrations/versions"
BASELINE_PATH = VERSIONS_DIR / "0001_persistence_baseline.py"
VALID_DATABASE_URL = "******localhost:5432/placeholder"


def _load_baseline_module():
    spec = importlib.util.spec_from_file_location("baseline_migration", BASELINE_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _create_alembic_config(*, output_buffer: io.StringIO | None = None) -> Config:
    return Config(str(ALEMBIC_INI_PATH), output_buffer=output_buffer)


def test_alembic_configuration_contains_no_committed_url_or_credentials() -> None:
    alembic_ini = ALEMBIC_INI_PATH.read_text(encoding="utf-8")
    normalized = alembic_ini.lower()

    assert "sqlalchemy.url" not in normalized
    assert "postgresql+asyncpg://" not in normalized
    assert "password" not in normalized
    assert "username" not in normalized


def test_revision_graph_has_one_stable_head_and_empty_baseline_metadata() -> None:
    script_directory = ScriptDirectory.from_config(_create_alembic_config())
    baseline_module = _load_baseline_module()

    assert script_directory.get_heads() == ["0001_persistence_baseline"]
    assert [path.name for path in VERSIONS_DIR.glob("*.py")] == ["0001_persistence_baseline.py"]
    assert baseline_module.revision == "0001_persistence_baseline"
    assert baseline_module.down_revision is None
    assert baseline_module.branch_labels is None
    assert baseline_module.depends_on is None


def test_baseline_upgrade_and_downgrade_are_reversible_no_ops() -> None:
    baseline_module = _load_baseline_module()

    assert baseline_module.upgrade() is None
    assert baseline_module.downgrade() is None


def test_offline_migration_sql_generation_succeeds_without_engine_creation(
    monkeypatch,
) -> None:
    output_buffer = io.StringIO()
    monkeypatch.setenv("DATABASE_URL", VALID_DATABASE_URL)
    session_module = __import__("trading_platform_api.persistence.session", fromlist=["unused"])

    def fail_engine_creation(*args, **kwargs):
        raise AssertionError("offline migration generation must not create an engine")

    monkeypatch.setattr(session_module, "create_async_engine_instance", fail_engine_creation)

    command.upgrade(_create_alembic_config(output_buffer=output_buffer), "head", sql=True)

    sql_output = output_buffer.getvalue().upper()
    assert "0001_PERSISTENCE_BASELINE" in sql_output
    assert "BEGIN" in sql_output
    assert "COMMIT" in sql_output


def test_generated_baseline_sql_contains_no_schema_or_domain_ddl(monkeypatch) -> None:
    output_buffer = io.StringIO()
    monkeypatch.setenv("DATABASE_URL", VALID_DATABASE_URL)

    command.upgrade(_create_alembic_config(output_buffer=output_buffer), "head", sql=True)

    sql_output = output_buffer.getvalue().upper()
    for forbidden_fragment in (
        "CREATE TABLE",
        "ALTER TABLE",
        "DROP TABLE",
        "CREATE INDEX",
        "CREATE EXTENSION",
        "CREATE TYPE",
        "ALTER TYPE",
        "CREATE TRIGGER",
        "INSERT INTO",
    ):
        assert forbidden_fragment not in sql_output
