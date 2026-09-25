from __future__ import annotations

import importlib.util
import io
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from trading_platform_api.audit.table import AuditEventRow

REPO_ROOT = Path(__file__).resolve().parents[2]
ALEMBIC_INI_PATH = REPO_ROOT / "apps/api/alembic.ini"
MIGRATION_PATH = (
    REPO_ROOT / "apps/api/migrations/versions/0002_audit_event_foundation.py"
)
VALID_DATABASE_URL = (
    "postgresql+asyncpg://placeholder_user@localhost:5432/placeholder_db"
)


def _config(*, output_buffer: io.StringIO | None = None) -> Config:
    return Config(str(ALEMBIC_INI_PATH), output_buffer=output_buffer)


def _migration_module():
    spec = importlib.util.spec_from_file_location("audit_migration", MIGRATION_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_table_maps_exact_foundation_columns_and_no_mutation_or_hash_fields() -> None:
    table = AuditEventRow.__table__
    expected = {
        "audit_id",
        "schema_version",
        "event_type",
        "occurred_at",
        "recorded_at",
        "actor",
        "action",
        "reason",
        "source",
        "result",
        "correlation_id",
        "trace_id",
        "subject_type",
        "subject_id",
        "supersedes_audit_id",
    }
    assert set(table.columns.keys()) == expected
    assert table.c.audit_id.primary_key is True
    assert table.c.reason.nullable is True
    assert table.c.subject_type.nullable is True
    assert table.c.subject_id.nullable is True
    assert table.c.supersedes_audit_id.nullable is True
    for required in expected - {
        "reason",
        "subject_type",
        "subject_id",
        "supersedes_audit_id",
    }:
        assert table.c[required].nullable is False
    forbidden = {
        "updated_at",
        "deleted_at",
        "is_deleted",
        "payload",
        "details",
        "previous_hash",
        "record_hash",
    }
    assert forbidden.isdisjoint(table.columns.keys())
    constraint_names = {constraint.name for constraint in table.constraints}
    assert "ck_audit_events_schema_version" in constraint_names
    assert "ck_audit_events_event_type" in constraint_names
    assert "ck_audit_events_reason_nonblank" in constraint_names
    assert "ck_audit_events_subject_type_nonblank" in constraint_names
    assert "ck_audit_events_subject_id_nonblank" in constraint_names


def test_migration_lineage_and_single_head() -> None:
    migration = _migration_module()
    scripts = ScriptDirectory.from_config(_config())
    assert migration.revision == "0002_audit_event_foundation"
    assert migration.down_revision == "0001_persistence_baseline"
    assert scripts.get_heads() == ["0002_audit_event_foundation"]


def test_offline_upgrade_contains_only_audit_foundation_ddl(monkeypatch) -> None:
    output = io.StringIO()
    monkeypatch.setenv("DATABASE_URL", VALID_DATABASE_URL)

    command.upgrade(_config(output_buffer=output), "head", sql=True)

    sql = output.getvalue().upper()
    assert "CREATE TABLE AUDIT_EVENTS" in sql
    assert "CREATE INDEX IX_AUDIT_EVENTS_CORRELATION_ID" in sql
    assert "CREATE INDEX IX_AUDIT_EVENTS_OCCURRED_AT" in sql
    assert "CREATE INDEX IX_AUDIT_EVENTS_EVENT_TYPE" in sql
    assert "CREATE INDEX IX_AUDIT_EVENTS_SUBJECT" in sql
    assert "DROP TABLE AUDIT_EVENTS" not in sql
    for forbidden in (
        "CREATE EXTENSION",
        "CREATE ROLE",
        "CREATE TRIGGER",
        "INSERT INTO AUDIT_EVENTS",
        "UPDATE AUDIT_EVENTS",
        "DELETE FROM AUDIT_EVENTS",
        "PREVIOUS_HASH",
        "RECORD_HASH",
    ):
        assert forbidden not in sql
    created_tables = [
        line for line in sql.splitlines() if line.startswith("CREATE TABLE ")
    ]
    assert created_tables == [
        "CREATE TABLE ALEMBIC_VERSION (",
        "CREATE TABLE AUDIT_EVENTS (",
    ]


def test_destructive_downgrade_is_explicitly_blocked() -> None:
    migration = _migration_module()
    with pytest.raises(RuntimeError, match="Destructive downgrade is prohibited"):
        migration.downgrade()
