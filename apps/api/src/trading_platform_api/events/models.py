from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Generic, TypeVar
from uuid import UUID, uuid4

from trading_platform_api.config import DeploymentEnvironment, OperatingMode


class EventValidationError(ValueError):
    """Raised when event metadata violates the canonical envelope contract."""


class DataClassification(StrEnum):
    PUBLIC = "public"
    INTERNAL = "internal"
    RESTRICTED = "restricted"
    CONFIDENTIAL = "confidential"


EVENT_SCHEMA_VERSION = "1"
_CONTRACT_ID_PATTERN = re.compile(r"C-[0-9]{3}")


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _required_text(field_name: str, value: object) -> None:
    if not isinstance(value, str):
        raise EventValidationError(f"{field_name} must be a string.")
    if not value.strip():
        raise EventValidationError(f"{field_name} must not be blank.")


def _optional_text(field_name: str, value: object) -> None:
    if value is not None:
        _required_text(field_name, value)


def _contract_id(field_name: str, value: object) -> None:
    _required_text(field_name, value)
    if _CONTRACT_ID_PATTERN.fullmatch(value) is None:
        raise EventValidationError(f"{field_name} must match C-[0-9]{{3}} exactly.")


def _utc_datetime(field_name: str, value: object) -> datetime:
    if not isinstance(value, datetime):
        raise EventValidationError(f"{field_name} must be a datetime.")
    if value.tzinfo is None or value.utcoffset() is None:
        raise EventValidationError(f"{field_name} must be timezone-aware.")
    return value.astimezone(UTC)


@dataclass(frozen=True, slots=True)
class AggregateReference:
    contract_id: str
    entity_id: str
    version: str | None = None

    def __post_init__(self) -> None:
        _contract_id("contract_id", self.contract_id)
        _required_text("entity_id", self.entity_id)
        _optional_text("version", self.version)


PayloadT = TypeVar("PayloadT")


@dataclass(frozen=True, slots=True)
class EventEnvelope(Generic[PayloadT]):
    event_type: str
    correlation_id: str
    causation_id: str
    producer: str
    producer_version: str
    environment: DeploymentEnvironment
    mode: OperatingMode
    aggregate_ref: AggregateReference
    payload_contract_id: str
    payload_contract_version: str
    audit_ref: UUID
    data_classification: DataClassification
    idempotency_key: str
    payload: PayloadT
    event_id: UUID = field(default_factory=uuid4)
    occurred_at: datetime = field(default_factory=_utc_now)
    recorded_at: datetime = field(default_factory=_utc_now)
    schema_version: str = field(default=EVENT_SCHEMA_VERSION, init=False)

    def __post_init__(self) -> None:
        for field_name in (
            "event_type",
            "correlation_id",
            "causation_id",
            "producer",
            "producer_version",
            "payload_contract_version",
            "idempotency_key",
        ):
            _required_text(field_name, getattr(self, field_name))

        _contract_id("payload_contract_id", self.payload_contract_id)

        if not isinstance(self.event_id, UUID):
            raise EventValidationError("event_id must be a UUID.")
        if not isinstance(self.audit_ref, UUID):
            raise EventValidationError("audit_ref must be a UUID.")
        if not isinstance(self.environment, DeploymentEnvironment):
            raise EventValidationError(
                "environment must be a DeploymentEnvironment."
            )
        if not isinstance(self.mode, OperatingMode):
            raise EventValidationError("mode must be an OperatingMode.")
        if not isinstance(self.aggregate_ref, AggregateReference):
            raise EventValidationError(
                "aggregate_ref must be an AggregateReference."
            )
        if not isinstance(self.data_classification, DataClassification):
            raise EventValidationError(
                "data_classification must be a DataClassification."
            )
        if self.payload is None:
            raise EventValidationError("payload must not be None.")

        object.__setattr__(
            self, "occurred_at", _utc_datetime("occurred_at", self.occurred_at)
        )
        object.__setattr__(
            self, "recorded_at", _utc_datetime("recorded_at", self.recorded_at)
        )
