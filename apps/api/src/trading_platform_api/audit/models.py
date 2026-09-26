from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from uuid import UUID, uuid4


class AuditValidationError(ValueError):
    """Raised when an audit event violates the C-060 foundation contract."""


class AuditEventType(StrEnum):
    USER_LOGIN = "USER_LOGIN"
    USER_LOGOUT = "USER_LOGOUT"
    SIGNAL_CREATED = "SIGNAL_CREATED"
    SIGNAL_UPDATED = "SIGNAL_UPDATED"
    SIGNAL_REJECTED = "SIGNAL_REJECTED"
    RISK_CREATED = "RISK_CREATED"
    RISK_REJECTED = "RISK_REJECTED"
    APPROVAL_CREATED = "APPROVAL_CREATED"
    APPROVAL_MODIFIED = "APPROVAL_MODIFIED"
    APPROVAL_APPROVED = "APPROVAL_APPROVED"
    APPROVAL_REVOKED = "APPROVAL_REVOKED"
    EXECUTION_STARTED = "EXECUTION_STARTED"
    ORDER_SUBMITTED = "ORDER_SUBMITTED"
    ORDER_FILLED = "ORDER_FILLED"
    ORDER_CANCELLED = "ORDER_CANCELLED"
    ORDER_REJECTED = "ORDER_REJECTED"
    RECONCILIATION_STARTED = "RECONCILIATION_STARTED"
    RECONCILIATION_FAILED = "RECONCILIATION_FAILED"
    KILL_SWITCH_ACTIVATED = "KILL_SWITCH_ACTIVATED"
    KILL_SWITCH_DEACTIVATED = "KILL_SWITCH_DEACTIVATED"
    CONFIGURATION_CHANGED = "CONFIGURATION_CHANGED"
    MODEL_CHANGED = "MODEL_CHANGED"
    PROMPT_CHANGED = "PROMPT_CHANGED"
    SECURITY_EVENT = "SECURITY_EVENT"


AUDIT_SCHEMA_VERSION = "1"
AUDIT_TEXT_LIMITS = {
    "actor": 255,
    "action": 255,
    "source": 255,
    "result": 128,
    "correlation_id": 128,
    "trace_id": 128,
    "subject_type": 128,
    "subject_id": 255,
}


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _required_text(field_name: str, value: object) -> None:
    if not isinstance(value, str):
        raise AuditValidationError(f"{field_name} must be a string.")
    if not value.strip():
        raise AuditValidationError(f"{field_name} must not be blank.")
    maximum_length = AUDIT_TEXT_LIMITS.get(field_name)
    if maximum_length is not None and len(value) > maximum_length:
        raise AuditValidationError(
            f"{field_name} must not exceed {maximum_length} characters."
        )


def _optional_text(field_name: str, value: object) -> None:
    if value is None:
        return
    _required_text(field_name, value)


def _utc_datetime(field_name: str, value: object) -> datetime:
    if not isinstance(value, datetime):
        raise AuditValidationError(f"{field_name} must be a datetime.")
    if value.tzinfo is None or value.utcoffset() is None:
        raise AuditValidationError(f"{field_name} must be timezone-aware.")
    return value.astimezone(UTC)


@dataclass(frozen=True, slots=True)
class AuditEvent:
    event_type: AuditEventType
    actor: str
    action: str
    source: str
    result: str
    correlation_id: str
    trace_id: str
    audit_id: UUID = field(default_factory=uuid4)
    occurred_at: datetime = field(default_factory=_utc_now)
    recorded_at: datetime = field(default_factory=_utc_now)
    reason: str | None = None
    subject_type: str | None = None
    subject_id: str | None = None
    supersedes_audit_id: UUID | None = None
    contract_id: str = field(default="C-060", init=False)
    schema_version: str = field(default=AUDIT_SCHEMA_VERSION, init=False)

    def __post_init__(self) -> None:
        if not isinstance(self.event_type, AuditEventType):
            raise AuditValidationError("event_type must be an AuditEventType.")
        if not isinstance(self.audit_id, UUID):
            raise AuditValidationError("audit_id must be a UUID.")
        if self.supersedes_audit_id is not None and not isinstance(
            self.supersedes_audit_id, UUID
        ):
            raise AuditValidationError(
                "supersedes_audit_id must be a UUID when supplied."
            )

        for field_name in (
            "actor",
            "action",
            "source",
            "result",
            "correlation_id",
            "trace_id",
        ):
            _required_text(field_name, getattr(self, field_name))
        for field_name in ("reason", "subject_type", "subject_id"):
            _optional_text(field_name, getattr(self, field_name))

        if (self.subject_type is None) != (self.subject_id is None):
            raise AuditValidationError(
                "subject_type and subject_id must be supplied together."
            )
        if self.supersedes_audit_id == self.audit_id:
            raise AuditValidationError("An audit event must not supersede itself.")

        object.__setattr__(
            self, "occurred_at", _utc_datetime("occurred_at", self.occurred_at)
        )
        object.__setattr__(
            self, "recorded_at", _utc_datetime("recorded_at", self.recorded_at)
        )
