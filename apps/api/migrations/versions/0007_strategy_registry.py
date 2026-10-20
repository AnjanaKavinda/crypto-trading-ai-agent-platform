"""Add immutable strategy identities, versions, and lifecycle histories."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0007_strategy_registry"
down_revision = "0006_spot_research_read_model"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "strategy_registry_identities",
        sa.Column("strategy_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("content_sha256", sa.String(length=64), nullable=False),
        sa.Column("canonical_document", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "content_sha256 ~ '^[0-9a-f]{64}$'",
            name="ck_strategy_registry_identity_digest",
        ),
        sa.CheckConstraint(
            "octet_length(canonical_document) <= 1000000",
            name="ck_strategy_registry_identity_document_size",
        ),
        sa.PrimaryKeyConstraint("strategy_id", name="pk_strategy_registry_identities"),
    )
    op.create_table(
        "strategy_registry_versions",
        sa.Column("strategy_version_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("strategy_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("semantic_version", sa.String(length=128), nullable=False),
        sa.Column("parent_version_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("content_sha256", sa.String(length=64), nullable=False),
        sa.Column("document_sha256", sa.String(length=64), nullable=False),
        sa.Column("canonical_document", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "content_sha256 ~ '^[0-9a-f]{64}$' AND document_sha256 ~ '^[0-9a-f]{64}$'",
            name="ck_strategy_registry_version_digests",
        ),
        sa.CheckConstraint(
            "length(btrim(semantic_version)) > 0",
            name="ck_strategy_registry_semantic_version_nonblank",
        ),
        sa.CheckConstraint(
            "octet_length(canonical_document) <= 1000000",
            name="ck_strategy_registry_version_document_size",
        ),
        sa.ForeignKeyConstraint(
            ["strategy_id"],
            ["strategy_registry_identities.strategy_id"],
            name="fk_strategy_registry_version_identity",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["strategy_id", "parent_version_id"],
            [
                "strategy_registry_versions.strategy_id",
                "strategy_registry_versions.strategy_version_id",
            ],
            name="fk_strategy_registry_version_parent",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint(
            "strategy_version_id", name="pk_strategy_registry_versions"
        ),
        sa.UniqueConstraint(
            "strategy_id",
            "semantic_version",
            name="uq_strategy_registry_semantic_version",
        ),
        sa.UniqueConstraint(
            "strategy_id",
            "strategy_version_id",
            name="uq_strategy_registry_version_owner",
        ),
    )
    op.create_table(
        "strategy_registry_lifecycle_events",
        sa.Column("event_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("audit_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("axis", sa.String(length=32), nullable=False),
        sa.Column("strategy_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("strategy_version_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "rollback_target_version_id", postgresql.UUID(as_uuid=True), nullable=True
        ),
        sa.Column(
            "resolves_suspension_event_id", postgresql.UUID(as_uuid=True), nullable=True
        ),
        sa.Column("environment", sa.String(length=16), nullable=True),
        sa.Column("operating_mode", sa.String(length=32), nullable=True),
        sa.Column("from_status", sa.String(length=64), nullable=True),
        sa.Column("to_status", sa.String(length=64), nullable=False),
        sa.Column("actor", sa.String(length=255), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column(
            "decision_reference",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column(
            "evidence_references",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column("effective_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "event_id",
            "strategy_id",
            "axis",
            name="uq_strategy_registry_event_subject_axis",
        ),
        sa.ForeignKeyConstraint(
            ["resolves_suspension_event_id", "strategy_id", "axis"],
            [
                "strategy_registry_lifecycle_events.event_id",
                "strategy_registry_lifecycle_events.strategy_id",
                "strategy_registry_lifecycle_events.axis",
            ],
            name="fk_strategy_registry_event_resolved_suspension",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "axis IN ('STRATEGY_AVAILABILITY','C021_VERSION','ARTIFACT_VERSION')",
            name="ck_strategy_registry_event_axis",
        ),
        sa.CheckConstraint(
            "(axis = 'STRATEGY_AVAILABILITY' AND strategy_version_id IS NULL) OR "
            "(axis IN ('C021_VERSION','ARTIFACT_VERSION') AND strategy_version_id IS NOT NULL)",
            name="ck_strategy_registry_event_subject_axis",
        ),
        sa.CheckConstraint(
            "(axis <> 'STRATEGY_AVAILABILITY' OR to_status IN "
            "('EXPERIMENTAL','ACTIVE','SUSPENDED','DEPRECATED')) AND "
            "(axis <> 'C021_VERSION' OR to_status IN "
            "('RESEARCH','VALIDATED','APPROVED_FOR_SHADOW','APPROVED_FOR_PAPER',"
            "'APPROVED_FOR_PRODUCTION','ACTIVE','RETIRED','REJECTED','ROLLED_BACK')) AND "
            "(axis <> 'ARTIFACT_VERSION' OR to_status IN "
            "('DRAFT','CANDIDATE','VALIDATED','APPROVED_FOR_SHADOW','APPROVED_FOR_PAPER',"
            "'APPROVED_FOR_PRODUCTION','ACTIVE','REJECTED','RETIRED','ROLLED_BACK'))",
            name="ck_strategy_registry_event_target_status",
        ),
        sa.CheckConstraint(
            "((COALESCE(axis = 'STRATEGY_AVAILABILITY' AND from_status = 'SUSPENDED' "
            "AND to_status = 'ACTIVE', FALSE) AND resolves_suspension_event_id IS NOT NULL) OR "
            "(NOT COALESCE(axis = 'STRATEGY_AVAILABILITY' AND from_status = 'SUSPENDED' "
            "AND to_status = 'ACTIVE', FALSE) AND resolves_suspension_event_id IS NULL))",
            name="ck_strategy_registry_event_suspension_resolution",
        ),
        sa.CheckConstraint(
            "(to_status = 'ROLLED_BACK' AND axis IN ('C021_VERSION','ARTIFACT_VERSION') "
            "AND rollback_target_version_id IS NOT NULL "
            "AND rollback_target_version_id <> strategy_version_id) OR "
            "(to_status <> 'ROLLED_BACK' AND rollback_target_version_id IS NULL)",
            name="ck_strategy_registry_event_rollback_target",
        ),
        sa.CheckConstraint(
            "(axis = 'STRATEGY_AVAILABILITY' AND environment IS NULL AND operating_mode IS NULL) OR "
            "(axis IN ('C021_VERSION','ARTIFACT_VERSION') AND "
            "((from_status IS NULL AND environment IS NULL AND operating_mode IS NULL) OR "
            "(from_status IS NOT NULL AND environment IS NOT NULL AND operating_mode IS NOT NULL)))",
            name="ck_strategy_registry_event_environment_mode_scope",
        ),
        sa.CheckConstraint(
            "environment IS NULL OR environment IN ('dev','test','staging','prod')",
            name="ck_strategy_registry_event_environment",
        ),
        sa.CheckConstraint(
            "operating_mode IS NULL OR operating_mode IN "
            "('research','backtest','paper','shadow','testnet','live-supervised')",
            name="ck_strategy_registry_event_operating_mode",
        ),
        sa.CheckConstraint(
            "length(btrim(actor)) > 0 AND length(btrim(reason)) > 0",
            name="ck_strategy_registry_event_actor_reason",
        ),
        sa.CheckConstraint(
            "effective_at <= recorded_at",
            name="ck_strategy_registry_event_effective_time",
        ),
        sa.ForeignKeyConstraint(
            ["strategy_id"],
            ["strategy_registry_identities.strategy_id"],
            name="fk_strategy_registry_event_identity",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["strategy_id", "strategy_version_id"],
            [
                "strategy_registry_versions.strategy_id",
                "strategy_registry_versions.strategy_version_id",
            ],
            name="fk_strategy_registry_event_version",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["strategy_id", "rollback_target_version_id"],
            [
                "strategy_registry_versions.strategy_id",
                "strategy_registry_versions.strategy_version_id",
            ],
            name="fk_strategy_registry_event_rollback_target",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["audit_id"],
            ["audit_events.audit_id"],
            name="fk_strategy_registry_event_audit",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint(
            "event_id", name="pk_strategy_registry_lifecycle_events"
        ),
        sa.UniqueConstraint("audit_id", name="uq_strategy_registry_event_audit"),
    )
    op.create_index(
        "ix_strategy_registry_events_subject_axis_time",
        "strategy_registry_lifecycle_events",
        ["strategy_id", "strategy_version_id", "axis", "effective_at", "recorded_at"],
    )
    for table in (
        "strategy_registry_identities",
        "strategy_registry_versions",
        "strategy_registry_lifecycle_events",
    ):
        op.execute(
            f"CREATE TRIGGER {table}_immutable BEFORE UPDATE OR DELETE OR TRUNCATE "
            f"ON {table} FOR EACH STATEMENT EXECUTE FUNCTION reject_lineage_mutation()"
        )


def downgrade() -> None:
    raise RuntimeError(
        "Destructive downgrade is prohibited for immutable strategy registry history."
    )
