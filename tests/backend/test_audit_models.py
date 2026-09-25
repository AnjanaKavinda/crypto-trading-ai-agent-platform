from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import UTC, datetime, timedelta, timezone
from uuid import UUID, uuid4

import pytest

from trading_platform_api.audit import AuditEvent, AuditEventType, AuditValidationError


EXPECTED_EVENT_TYPES = {
    "USER_LOGIN",
    "USER_LOGOUT",
    "SIGNAL_CREATED",
    "SIGNAL_UPDATED",
    "SIGNAL_REJECTED",
    "RISK_CREATED",
    "RISK_REJECTED",
    "APPROVAL_CREATED",
    "APPROVAL_MODIFIED",
    "APPROVAL_APPROVED",
    "APPROVAL_REVOKED",
    "EXECUTION_STARTED",
    "ORDER_SUBMITTED",
    "ORDER_FILLED",
    "ORDER_CANCELLED",
    "ORDER_REJECTED",
    "RECONCILIATION_STARTED",
    "RECONCILIATION_FAILED",
    "KILL_SWITCH_ACTIVATED",
    "KILL_SWITCH_DEACTIVATED",
    "CONFIGURATION_CHANGED",
    "MODEL_CHANGED",
    "PROMPT_CHANGED",
    "SECURITY_EVENT",
}


def _event(**overrides) -> AuditEvent:
    values = {
        "event_type": AuditEventType.SECURITY_EVENT,
        "actor": "safety-service",
        "action": "reject-unauthorized-transition",
        "source": "safety-control-plane",
        "result": "REJECTED",
        "correlation_id": "correlation-1",
        "trace_id": "trace-1",
    }
    values.update(overrides)
    return AuditEvent(**values)


def test_event_type_vocabulary_is_exact() -> None:
    assert {member.value for member in AuditEventType} == EXPECTED_EVENT_TYPES


def test_valid_event_has_immutable_identity_version_and_utc_timestamps() -> None:
    event = _event()

    assert isinstance(event.audit_id, UUID)
    assert event.schema_version == "1"
    assert event.occurred_at.tzinfo is UTC
    assert event.recorded_at.tzinfo is UTC
    with pytest.raises(FrozenInstanceError):
        event.result = "CHANGED"  # type: ignore[misc]


def test_supplied_identity_and_aware_timestamps_are_preserved_and_normalized() -> None:
    audit_id = uuid4()
    offset = timezone(timedelta(hours=5, minutes=30))
    occurred_at = datetime(2026, 9, 25, 15, 0, tzinfo=offset)
    recorded_at = datetime(2026, 9, 25, 15, 1, tzinfo=offset)
    event = _event(
        audit_id=audit_id,
        occurred_at=occurred_at,
        recorded_at=recorded_at,
    )

    assert event.audit_id == audit_id
    assert event.occurred_at == occurred_at.astimezone(UTC)
    assert event.recorded_at == recorded_at.astimezone(UTC)
    assert event.occurred_at.tzinfo is UTC
    assert event.recorded_at.tzinfo is UTC


@pytest.mark.parametrize("field_name", ["occurred_at", "recorded_at"])
def test_naive_timestamp_is_rejected(field_name: str) -> None:
    with pytest.raises(AuditValidationError, match="timezone-aware"):
        _event(**{field_name: datetime(2026, 9, 25, 10, 0)})


@pytest.mark.parametrize(
    "field_name",
    ["actor", "action", "source", "result", "correlation_id", "trace_id"],
)
@pytest.mark.parametrize("invalid_value", ["", "   "])
def test_required_text_rejects_blank_values(
    field_name: str, invalid_value: str
) -> None:
    with pytest.raises(AuditValidationError, match="must not be blank"):
        _event(**{field_name: invalid_value})


@pytest.mark.parametrize("field_name", ["reason", "subject_type", "subject_id"])
def test_optional_text_rejects_blank_when_supplied(field_name: str) -> None:
    overrides = {"subject_type": "Order", "subject_id": "order-1"}
    overrides[field_name] = " "
    with pytest.raises(AuditValidationError, match="must not be blank"):
        _event(**overrides)


@pytest.mark.parametrize(
    "overrides",
    [
        {"subject_type": "Order"},
        {"subject_id": "order-1"},
    ],
)
def test_subject_reference_must_be_complete(overrides: dict[str, str]) -> None:
    with pytest.raises(AuditValidationError, match="supplied together"):
        _event(**overrides)


def test_self_supersession_is_rejected() -> None:
    audit_id = uuid4()
    with pytest.raises(AuditValidationError, match="must not supersede itself"):
        _event(audit_id=audit_id, supersedes_audit_id=audit_id)


def test_event_type_must_be_validated_enum() -> None:
    with pytest.raises(AuditValidationError, match="AuditEventType"):
        _event(event_type="SECURITY_EVENT")  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("field_name", "maximum_length"),
    [
        ("actor", 255),
        ("action", 255),
        ("source", 255),
        ("result", 128),
        ("correlation_id", 128),
        ("trace_id", 128),
        ("subject_type", 128),
        ("subject_id", 255),
    ],
)
def test_bounded_text_rejects_database_overflow(
    field_name: str, maximum_length: int
) -> None:
    overrides = {"subject_type": "Order", "subject_id": "order-1"}
    overrides[field_name] = "x" * (maximum_length + 1)
    with pytest.raises(AuditValidationError, match="must not exceed"):
        _event(**overrides)
