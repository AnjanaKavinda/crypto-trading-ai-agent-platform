from __future__ import annotations

from dataclasses import FrozenInstanceError, fields
from datetime import UTC, datetime, timedelta, timezone
from uuid import UUID, uuid4

import pytest
from trading_platform_api.config import DeploymentEnvironment, OperatingMode
from trading_platform_api.events import (
    EVENT_SCHEMA_VERSION,
    AggregateReference,
    DataClassification,
    EventEnvelope,
    EventValidationError,
)


def _envelope(**overrides: object) -> EventEnvelope[object]:
    values: dict[str, object] = {
        "event_type": "MarketSnapshotCreated",
        "correlation_id": "correlation-1",
        "causation_id": "request-1",
        "producer": "data-service",
        "producer_version": "build-1",
        "environment": DeploymentEnvironment.TEST,
        "mode": OperatingMode.RESEARCH,
        "aggregate_ref": AggregateReference("C-002", "BTC-USD:1m"),
        "payload_contract_id": "C-002",
        "payload_contract_version": "1",
        "audit_ref": uuid4(),
        "data_classification": DataClassification.INTERNAL,
        "idempotency_key": "market-snapshot:BTC-USD:1m:1",
        "payload": {"snapshot_id": "snapshot-1"},
    }
    values.update(overrides)
    return EventEnvelope(**values)  # type: ignore[arg-type]


def test_data_classification_vocabulary_is_exact() -> None:
    assert {value.value for value in DataClassification} == {
        "public",
        "internal",
        "restricted",
        "confidential",
    }


def test_valid_envelope_has_exact_foundation_fields_and_defaults() -> None:
    envelope = _envelope()

    assert {item.name for item in fields(envelope)} == {
        "event_type",
        "correlation_id",
        "causation_id",
        "producer",
        "producer_version",
        "environment",
        "mode",
        "aggregate_ref",
        "payload_contract_id",
        "payload_contract_version",
        "audit_ref",
        "data_classification",
        "idempotency_key",
        "payload",
        "event_id",
        "occurred_at",
        "recorded_at",
        "schema_version",
    }
    assert isinstance(envelope.event_id, UUID)
    assert envelope.schema_version == EVENT_SCHEMA_VERSION == "1"
    assert envelope.occurred_at.tzinfo is UTC
    assert envelope.recorded_at.tzinfo is UTC


def test_envelope_and_aggregate_reference_are_frozen() -> None:
    envelope = _envelope()

    with pytest.raises(FrozenInstanceError):
        envelope.event_type = "Changed"  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        envelope.aggregate_ref.entity_id = "changed"  # type: ignore[misc]


def test_supplied_identity_timestamps_and_payload_identity_are_preserved() -> None:
    event_id = uuid4()
    payload = object()
    offset = timezone(timedelta(hours=5, minutes=30))
    occurred_at = datetime(2026, 9, 25, 12, 0, tzinfo=offset)
    recorded_at = datetime(2026, 9, 25, 12, 1, tzinfo=offset)

    envelope = _envelope(
        event_id=event_id,
        occurred_at=occurred_at,
        recorded_at=recorded_at,
        payload=payload,
    )

    assert envelope.event_id is event_id
    assert envelope.occurred_at == occurred_at.astimezone(UTC)
    assert envelope.recorded_at == recorded_at.astimezone(UTC)
    assert envelope.payload is payload


@pytest.mark.parametrize("field_name", ["occurred_at", "recorded_at"])
def test_naive_timestamps_are_rejected(field_name: str) -> None:
    with pytest.raises(
        EventValidationError, match=rf"{field_name} must be timezone-aware"
    ):
        _envelope(**{field_name: datetime(2026, 9, 25, 12, 0)})


@pytest.mark.parametrize(
    "field_name",
    [
        "event_type",
        "correlation_id",
        "causation_id",
        "producer",
        "producer_version",
        "payload_contract_version",
        "idempotency_key",
    ],
)
@pytest.mark.parametrize("invalid_value", ["", "   ", "\t"])
def test_required_envelope_text_rejects_blank_values(
    field_name: str, invalid_value: str
) -> None:
    with pytest.raises(EventValidationError, match=rf"{field_name} must not be blank"):
        _envelope(**{field_name: invalid_value})


@pytest.mark.parametrize(
    "field_name",
    [
        "event_type",
        "correlation_id",
        "causation_id",
        "producer",
        "producer_version",
        "payload_contract_version",
        "idempotency_key",
    ],
)
def test_required_envelope_text_rejects_non_string_values(field_name: str) -> None:
    with pytest.raises(EventValidationError, match=rf"{field_name} must be a string"):
        _envelope(**{field_name: 123})


def test_text_is_not_silently_trimmed() -> None:
    envelope = _envelope(event_type=" MarketSnapshotCreated ")

    assert envelope.event_type == " MarketSnapshotCreated "


@pytest.mark.parametrize("invalid_value", ["C-01", "C-0001", "c-001", " C-001 "])
@pytest.mark.parametrize("field_name", ["contract_id", "payload_contract_id"])
def test_contract_ids_must_use_exact_canonical_format(
    field_name: str, invalid_value: str
) -> None:
    with pytest.raises(EventValidationError, match=r"must match C-\[0-9\]\{3\}"):
        if field_name == "contract_id":
            AggregateReference(invalid_value, "entity-1")
        else:
            _envelope(payload_contract_id=invalid_value)


@pytest.mark.parametrize("field_name", ["entity_id", "version"])
def test_aggregate_reference_rejects_blank_supplied_text(field_name: str) -> None:
    values: dict[str, object] = {
        "contract_id": "C-002",
        "entity_id": "entity-1",
        "version": "1",
    }
    values[field_name] = " "

    with pytest.raises(EventValidationError, match=rf"{field_name} must not be blank"):
        AggregateReference(**values)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("field_name", "invalid_value", "message"),
    [
        ("event_id", "event-1", "event_id must be a UUID"),
        ("audit_ref", "audit-1", "audit_ref must be a UUID"),
        ("environment", "test", "environment must be a DeploymentEnvironment"),
        ("mode", "research", "mode must be an OperatingMode"),
        (
            "aggregate_ref",
            "C-002:entity-1",
            "aggregate_ref must be an AggregateReference",
        ),
        (
            "data_classification",
            "internal",
            "data_classification must be a DataClassification",
        ),
    ],
)
def test_typed_metadata_rejects_unvalidated_values(
    field_name: str, invalid_value: object, message: str
) -> None:
    with pytest.raises(EventValidationError, match=message):
        _envelope(**{field_name: invalid_value})


def test_none_payload_is_rejected_without_inspecting_valid_payloads() -> None:
    with pytest.raises(EventValidationError, match="payload must not be None"):
        _envelope(payload=None)
