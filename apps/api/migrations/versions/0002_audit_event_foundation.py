"""create the append-only audit event foundation"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0002_audit_event_foundation"
down_revision = "0001_persistence_baseline"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "audit_events",
        sa.Column("audit_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("schema_version", sa.String(length=16), nullable=False),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("actor", sa.String(length=255), nullable=False),
        sa.Column("action", sa.String(length=255), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("source", sa.String(length=255), nullable=False),
        sa.Column("result", sa.String(length=128), nullable=False),
        sa.Column("correlation_id", sa.String(length=128), nullable=False),
        sa.Column("trace_id", sa.String(length=128), nullable=False),
        sa.Column("subject_type", sa.String(length=128), nullable=True),
        sa.Column("subject_id", sa.String(length=255), nullable=True),
        sa.Column("supersedes_audit_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.CheckConstraint(
            "schema_version = '1'", name="ck_audit_events_schema_version"
        ),
        sa.CheckConstraint(
            "event_type IN ('USER_LOGIN', 'USER_LOGOUT', 'SIGNAL_CREATED', "
            "'SIGNAL_UPDATED', 'SIGNAL_REJECTED', 'RISK_CREATED', "
            "'RISK_REJECTED', 'APPROVAL_CREATED', 'APPROVAL_MODIFIED', "
            "'APPROVAL_APPROVED', 'APPROVAL_REVOKED', 'EXECUTION_STARTED', "
            "'ORDER_SUBMITTED', 'ORDER_FILLED', 'ORDER_CANCELLED', "
            "'ORDER_REJECTED', 'RECONCILIATION_STARTED', "
            "'RECONCILIATION_FAILED', 'KILL_SWITCH_ACTIVATED', "
            "'KILL_SWITCH_DEACTIVATED', 'CONFIGURATION_CHANGED', "
            "'MODEL_CHANGED', 'PROMPT_CHANGED', 'SECURITY_EVENT')",
            name="ck_audit_events_event_type",
        ),
        sa.CheckConstraint(
            "length(btrim(actor)) > 0", name="ck_audit_events_actor_nonblank"
        ),
        sa.CheckConstraint(
            "length(btrim(action)) > 0", name="ck_audit_events_action_nonblank"
        ),
        sa.CheckConstraint(
            "length(btrim(source)) > 0", name="ck_audit_events_source_nonblank"
        ),
        sa.CheckConstraint(
            "length(btrim(result)) > 0", name="ck_audit_events_result_nonblank"
        ),
        sa.CheckConstraint(
            "length(btrim(correlation_id)) > 0",
            name="ck_audit_events_correlation_id_nonblank",
        ),
        sa.CheckConstraint(
            "length(btrim(trace_id)) > 0",
            name="ck_audit_events_trace_id_nonblank",
        ),
        sa.CheckConstraint(
            "reason IS NULL OR length(btrim(reason)) > 0",
            name="ck_audit_events_reason_nonblank",
        ),
        sa.CheckConstraint(
            "subject_type IS NULL OR length(btrim(subject_type)) > 0",
            name="ck_audit_events_subject_type_nonblank",
        ),
        sa.CheckConstraint(
            "subject_id IS NULL OR length(btrim(subject_id)) > 0",
            name="ck_audit_events_subject_id_nonblank",
        ),
        sa.CheckConstraint(
            "(subject_type IS NULL AND subject_id IS NULL) OR "
            "(subject_type IS NOT NULL AND subject_id IS NOT NULL)",
            name="ck_audit_events_subject_pair",
        ),
        sa.CheckConstraint(
            "supersedes_audit_id IS NULL OR supersedes_audit_id <> audit_id",
            name="ck_audit_events_not_self_superseding",
        ),
        sa.ForeignKeyConstraint(
            ["supersedes_audit_id"],
            ["audit_events.audit_id"],
            name="fk_audit_events_supersedes_audit_id",
        ),
        sa.PrimaryKeyConstraint("audit_id", name="pk_audit_events"),
    )
    op.create_index(
        "ix_audit_events_correlation_id", "audit_events", ["correlation_id"]
    )
    op.create_index("ix_audit_events_occurred_at", "audit_events", ["occurred_at"])
    op.create_index("ix_audit_events_event_type", "audit_events", ["event_type"])
    op.create_index(
        "ix_audit_events_subject", "audit_events", ["subject_type", "subject_id"]
    )


def downgrade() -> None:
    raise RuntimeError(
        "Destructive downgrade is prohibited for append-only audit history."
    )
