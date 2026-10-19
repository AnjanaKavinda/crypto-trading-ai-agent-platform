"""PostgreSQL Core tables for immutable strategy registry records."""

from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    ForeignKeyConstraint,
    Index,
    String,
    Table,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID

from trading_platform_api.audit.table import AuditEventRow

# Reuse the audit metadata so the C-060 foreign key is part of this schema view.
metadata = AuditEventRow.metadata

strategy_registry_identities = Table(
    "strategy_registry_identities",
    metadata,
    Column("strategy_id", UUID(as_uuid=True), primary_key=True),
    Column("content_sha256", String(64), nullable=False),
    Column("canonical_document", Text, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    CheckConstraint(
        "content_sha256 ~ '^[0-9a-f]{64}$'",
        name="ck_strategy_registry_identity_digest",
    ),
    CheckConstraint(
        "octet_length(canonical_document) <= 1000000",
        name="ck_strategy_registry_identity_document_size",
    ),
)

strategy_registry_versions = Table(
    "strategy_registry_versions",
    metadata,
    Column("strategy_version_id", UUID(as_uuid=True), primary_key=True),
    Column("strategy_id", UUID(as_uuid=True), nullable=False),
    Column("semantic_version", String(128), nullable=False),
    Column("parent_version_id", UUID(as_uuid=True), nullable=True),
    Column("content_sha256", String(64), nullable=False),
    Column("document_sha256", String(64), nullable=False),
    Column("canonical_document", Text, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    UniqueConstraint(
        "strategy_id", "semantic_version", name="uq_strategy_registry_semantic_version"
    ),
    UniqueConstraint(
        "strategy_id", "strategy_version_id", name="uq_strategy_registry_version_owner"
    ),
    ForeignKeyConstraint(
        ["strategy_id"],
        ["strategy_registry_identities.strategy_id"],
        name="fk_strategy_registry_version_identity",
        ondelete="RESTRICT",
    ),
    ForeignKeyConstraint(
        ["strategy_id", "parent_version_id"],
        [
            "strategy_registry_versions.strategy_id",
            "strategy_registry_versions.strategy_version_id",
        ],
        name="fk_strategy_registry_version_parent",
        ondelete="RESTRICT",
    ),
    CheckConstraint(
        "content_sha256 ~ '^[0-9a-f]{64}$' AND document_sha256 ~ '^[0-9a-f]{64}$'",
        name="ck_strategy_registry_version_digests",
    ),
    CheckConstraint(
        "length(btrim(semantic_version)) > 0",
        name="ck_strategy_registry_semantic_version_nonblank",
    ),
    CheckConstraint(
        "octet_length(canonical_document) <= 1000000",
        name="ck_strategy_registry_version_document_size",
    ),
)

strategy_registry_lifecycle_events = Table(
    "strategy_registry_lifecycle_events",
    metadata,
    Column("event_id", UUID(as_uuid=True), primary_key=True),
    Column("audit_id", UUID(as_uuid=True), nullable=False, unique=True),
    Column("axis", String(32), nullable=False),
    Column("strategy_id", UUID(as_uuid=True), nullable=False),
    Column("strategy_version_id", UUID(as_uuid=True), nullable=True),
    Column("rollback_target_version_id", UUID(as_uuid=True), nullable=True),
    Column("environment", String(16), nullable=True),
    Column("operating_mode", String(32), nullable=True),
    Column("from_status", String(64), nullable=True),
    Column("to_status", String(64), nullable=False),
    Column("actor", String(255), nullable=False),
    Column("reason", Text, nullable=False),
    Column("decision_reference", JSONB, nullable=False),
    Column("evidence_references", JSONB, nullable=False),
    Column("effective_at", DateTime(timezone=True), nullable=False),
    Column("recorded_at", DateTime(timezone=True), nullable=False),
    ForeignKeyConstraint(
        ["strategy_id"],
        ["strategy_registry_identities.strategy_id"],
        name="fk_strategy_registry_event_identity",
        ondelete="RESTRICT",
    ),
    ForeignKeyConstraint(
        ["audit_id"],
        ["audit_events.audit_id"],
        name="fk_strategy_registry_event_audit",
        ondelete="RESTRICT",
    ),
    ForeignKeyConstraint(
        ["strategy_id", "strategy_version_id"],
        [
            "strategy_registry_versions.strategy_id",
            "strategy_registry_versions.strategy_version_id",
        ],
        name="fk_strategy_registry_event_version",
        ondelete="RESTRICT",
    ),
    ForeignKeyConstraint(
        ["strategy_id", "rollback_target_version_id"],
        [
            "strategy_registry_versions.strategy_id",
            "strategy_registry_versions.strategy_version_id",
        ],
        name="fk_strategy_registry_event_rollback_target",
        ondelete="RESTRICT",
    ),
    CheckConstraint(
        "axis IN ('STRATEGY_AVAILABILITY','C021_VERSION','ARTIFACT_VERSION')",
        name="ck_strategy_registry_event_axis",
    ),
    CheckConstraint(
        "(axis = 'STRATEGY_AVAILABILITY' AND strategy_version_id IS NULL) OR "
        "(axis IN ('C021_VERSION','ARTIFACT_VERSION') AND strategy_version_id IS NOT NULL)",
        name="ck_strategy_registry_event_subject_axis",
    ),
    CheckConstraint(
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
    CheckConstraint(
        "(to_status = 'ROLLED_BACK' AND axis IN ('C021_VERSION','ARTIFACT_VERSION') "
        "AND rollback_target_version_id IS NOT NULL "
        "AND rollback_target_version_id <> strategy_version_id) OR "
        "(to_status <> 'ROLLED_BACK' AND rollback_target_version_id IS NULL)",
        name="ck_strategy_registry_event_rollback_target",
    ),
    CheckConstraint(
        "(axis = 'STRATEGY_AVAILABILITY' AND environment IS NULL AND operating_mode IS NULL) OR "
        "(axis IN ('C021_VERSION','ARTIFACT_VERSION') AND "
        "((from_status IS NULL AND environment IS NULL AND operating_mode IS NULL) OR "
        "(from_status IS NOT NULL AND environment IS NOT NULL AND operating_mode IS NOT NULL)))",
        name="ck_strategy_registry_event_environment_mode_scope",
    ),
    CheckConstraint(
        "environment IS NULL OR environment IN ('dev','test','staging','prod')",
        name="ck_strategy_registry_event_environment",
    ),
    CheckConstraint(
        "operating_mode IS NULL OR operating_mode IN "
        "('research','backtest','paper','shadow','testnet','live-supervised')",
        name="ck_strategy_registry_event_operating_mode",
    ),
    CheckConstraint(
        "length(btrim(actor)) > 0 AND length(btrim(reason)) > 0",
        name="ck_strategy_registry_event_actor_reason",
    ),
    CheckConstraint(
        "effective_at <= recorded_at",
        name="ck_strategy_registry_event_effective_time",
    ),
    Index(
        "ix_strategy_registry_events_subject_axis_time",
        "strategy_id",
        "strategy_version_id",
        "axis",
        "effective_at",
        "recorded_at",
    ),
)

__all__ = [
    "metadata",
    "strategy_registry_identities",
    "strategy_registry_lifecycle_events",
    "strategy_registry_versions",
]
