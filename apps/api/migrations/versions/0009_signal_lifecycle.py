"""Persist immutable signal lifecycle events with C-060 linkage."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0009_signal_lifecycle"
down_revision = "0008_spot_analysis_lineage"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "signal_lifecycle_events",
        sa.Column("event_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("audit_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("subject_contract_id", sa.String(length=16), nullable=False),
        sa.Column("subject_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("subject_version", sa.String(length=128), nullable=False),
        sa.Column("subject_sha256", sa.String(length=64), nullable=False),
        sa.Column("prior_state", sa.String(length=32), nullable=True),
        sa.Column("resulting_state", sa.String(length=32), nullable=False),
        sa.Column("event_type", sa.String(length=32), nullable=False),
        sa.Column("cause", sa.String(length=64), nullable=False),
        sa.Column("source_references", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("event_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("correlation_id", sa.String(length=128), nullable=False),
        sa.CheckConstraint(
            "subject_sha256 ~ '^[0-9a-f]{64}$'",
            name="ck_signal_lifecycle_subject_digest",
        ),
        sa.CheckConstraint(
            "resulting_state IN "
            "('CANDIDATE','WATCH','QUALIFIED','REJECTED','NO_TRADE','INVALIDATED','EXPIRED','SUPERSEDED')",
            name="ck_signal_lifecycle_resulting_state",
        ),
        sa.CheckConstraint(
            "prior_state IS NULL OR prior_state IN "
            "('CANDIDATE','WATCH','QUALIFIED','REJECTED','NO_TRADE','INVALIDATED','EXPIRED','SUPERSEDED')",
            name="ck_signal_lifecycle_prior_state",
        ),
        sa.CheckConstraint(
            "event_type IN "
            "('CREATED','WATCHED','QUALIFIED','REJECTED','NO_TRADE','INVALIDATED','EXPIRED','SUPERSEDED')",
            name="ck_signal_lifecycle_event_type",
        ),
        sa.CheckConstraint(
            "cause IN "
            "('SOURCE_DECISION','INVALIDATION_RULE_MATCHED','EFFECTIVE_EXPIRY_REACHED','EXPLICIT_SUCCESSOR')",
            name="ck_signal_lifecycle_cause",
        ),
        sa.CheckConstraint(
            "event_time <= recorded_at",
            name="ck_signal_lifecycle_event_time",
        ),
        sa.CheckConstraint(
            "length(btrim(correlation_id)) > 0",
            name="ck_signal_lifecycle_correlation_nonblank",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(source_references) = 'array' "
            "AND jsonb_array_length(source_references) > 0",
            name="ck_signal_lifecycle_sources",
        ),
        sa.ForeignKeyConstraint(
            ["audit_id"],
            ["audit_events.audit_id"],
            name="fk_signal_lifecycle_event_audit",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("event_id", name="pk_signal_lifecycle_events"),
        sa.UniqueConstraint("audit_id", name="uq_signal_lifecycle_audit"),
    )
    op.create_index(
        "ix_signal_lifecycle_subject_time",
        "signal_lifecycle_events",
        [
            "subject_contract_id",
            "subject_id",
            "subject_version",
            "event_time",
            "recorded_at",
        ],
        unique=False,
    )
    op.execute(
        """CREATE FUNCTION reject_signal_lifecycle_mutation() RETURNS trigger
        LANGUAGE plpgsql AS $$ BEGIN
        RAISE EXCEPTION 'Signal lifecycle history is append-only';
        RETURN NULL; END; $$"""
    )
    op.execute(
        """CREATE TRIGGER signal_lifecycle_events_immutable
        BEFORE UPDATE OR DELETE OR TRUNCATE ON signal_lifecycle_events
        FOR EACH STATEMENT EXECUTE FUNCTION reject_signal_lifecycle_mutation()"""
    )


def downgrade() -> None:
    raise RuntimeError(
        "Destructive downgrade is prohibited for durable signal lifecycle history."
    )
