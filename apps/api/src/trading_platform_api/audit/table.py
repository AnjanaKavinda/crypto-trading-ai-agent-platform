from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from trading_platform_api.audit.models import (
    AUDIT_SCHEMA_VERSION,
    AuditEvent,
    AuditEventType,
)

_EVENT_TYPE_SQL = ", ".join(f"'{event_type.value}'" for event_type in AuditEventType)


class AuditBase(DeclarativeBase):
    pass


class AuditEventRow(AuditBase):
    __tablename__ = "audit_events"
    __table_args__ = (
        CheckConstraint(
            f"schema_version = '{AUDIT_SCHEMA_VERSION}'",
            name="ck_audit_events_schema_version",
        ),
        CheckConstraint(
            f"event_type IN ({_EVENT_TYPE_SQL})",
            name="ck_audit_events_event_type",
        ),
        CheckConstraint(
            "length(btrim(actor)) > 0", name="ck_audit_events_actor_nonblank"
        ),
        CheckConstraint(
            "length(btrim(action)) > 0", name="ck_audit_events_action_nonblank"
        ),
        CheckConstraint(
            "length(btrim(source)) > 0", name="ck_audit_events_source_nonblank"
        ),
        CheckConstraint(
            "length(btrim(result)) > 0", name="ck_audit_events_result_nonblank"
        ),
        CheckConstraint(
            "length(btrim(correlation_id)) > 0",
            name="ck_audit_events_correlation_id_nonblank",
        ),
        CheckConstraint(
            "length(btrim(trace_id)) > 0",
            name="ck_audit_events_trace_id_nonblank",
        ),
        CheckConstraint(
            "reason IS NULL OR length(btrim(reason)) > 0",
            name="ck_audit_events_reason_nonblank",
        ),
        CheckConstraint(
            "subject_type IS NULL OR length(btrim(subject_type)) > 0",
            name="ck_audit_events_subject_type_nonblank",
        ),
        CheckConstraint(
            "subject_id IS NULL OR length(btrim(subject_id)) > 0",
            name="ck_audit_events_subject_id_nonblank",
        ),
        CheckConstraint(
            "(subject_type IS NULL AND subject_id IS NULL) OR "
            "(subject_type IS NOT NULL AND subject_id IS NOT NULL)",
            name="ck_audit_events_subject_pair",
        ),
        CheckConstraint(
            "supersedes_audit_id IS NULL OR supersedes_audit_id <> audit_id",
            name="ck_audit_events_not_self_superseding",
        ),
        Index("ix_audit_events_correlation_id", "correlation_id"),
        Index("ix_audit_events_occurred_at", "occurred_at"),
        Index("ix_audit_events_event_type", "event_type"),
        Index("ix_audit_events_subject", "subject_type", "subject_id"),
    )

    audit_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True), primary_key=True
    )
    schema_version: Mapped[str] = mapped_column(String(16), nullable=False)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    actor: Mapped[str] = mapped_column(String(255), nullable=False)
    action: Mapped[str] = mapped_column(String(255), nullable=False)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    source: Mapped[str] = mapped_column(String(255), nullable=False)
    result: Mapped[str] = mapped_column(String(128), nullable=False)
    correlation_id: Mapped[str] = mapped_column(String(128), nullable=False)
    trace_id: Mapped[str] = mapped_column(String(128), nullable=False)
    subject_type: Mapped[str | None] = mapped_column(String(128), nullable=True)
    subject_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    supersedes_audit_id: Mapped[UUID | None] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("audit_events.audit_id"),
        nullable=True,
    )

    @classmethod
    def from_event(cls, event: AuditEvent) -> "AuditEventRow":
        return cls(
            audit_id=event.audit_id,
            schema_version=event.schema_version,
            event_type=event.event_type.value,
            occurred_at=event.occurred_at,
            recorded_at=event.recorded_at,
            actor=event.actor,
            action=event.action,
            reason=event.reason,
            source=event.source,
            result=event.result,
            correlation_id=event.correlation_id,
            trace_id=event.trace_id,
            subject_type=event.subject_type,
            subject_id=event.subject_id,
            supersedes_audit_id=event.supersedes_audit_id,
        )
