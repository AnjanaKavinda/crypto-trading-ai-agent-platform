"""Append-only SQLAlchemy store for exact C-020/C-021 strategy records."""

from __future__ import annotations

import json
import types
from dataclasses import fields, is_dataclass
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Any, get_args, get_origin, get_type_hints
from uuid import UUID

from sqlalchemy import and_, insert, select
from sqlalchemy.ext.asyncio import AsyncSession

from trading_platform_api.audit.models import AuditEvent, AuditEventType
from trading_platform_api.audit.table import AuditEventRow
from trading_platform_api.config import DeploymentEnvironment, OperatingMode
from trading_platform_api.contracts.serialization import (
    MAX_DOCUMENT_BYTES,
    contract_sha256,
    serialize_contract,
)
from trading_platform_api.strategy.contracts import (
    Strategy,
    StrategyVersion,
    VersionReference,
)
from trading_platform_api.strategy.registry import (
    LifecycleAxis,
    RegistryLifecycleEvent,
    StrategyRegistryError,
    strategy_version_content_sha256,
)
from trading_platform_api.strategy.tables import (
    strategy_registry_identities,
    strategy_registry_lifecycle_events,
    strategy_registry_versions,
)

_MODELS: dict[str, type[Strategy] | type[StrategyVersion]] = {
    "C-020": Strategy,
    "C-021": StrategyVersion,
}


class SqlAlchemyStrategyRegistryStore:
    """SQL-backed store; transaction commit and rollback belong to the caller."""

    def __init__(self, session: AsyncSession) -> None:
        if not isinstance(session, AsyncSession):
            raise TypeError("session must be an AsyncSession.")
        self._session = session

    async def register_strategy(
        self,
        strategy: Strategy,
        initial_event: RegistryLifecycleEvent,
        audit_event: AuditEvent,
    ) -> None:
        if type(strategy) is not Strategy:
            raise StrategyRegistryError("strategy must be the exact C-020 contract.")
        _validate_initial_event(
            initial_event,
            axis=LifecycleAxis.STRATEGY_AVAILABILITY,
            strategy_id=strategy.strategy_id,
            strategy_version_id=None,
            status="EXPERIMENTAL",
        )
        _validate_audit_binding(initial_event, audit_event)
        document = serialize_contract(strategy, payload_version="wire-1")
        if len(document.encode("utf-8")) > MAX_DOCUMENT_BYTES:
            raise StrategyRegistryError("C-020 document exceeds the registry limit.")
        await self._session.execute(
            insert(strategy_registry_identities).values(
                strategy_id=strategy.strategy_id,
                content_sha256=contract_sha256(strategy, payload_version="wire-1"),
                canonical_document=document,
                created_at=strategy.created_at,
            )
        )
        self._session.add(AuditEventRow.from_event(audit_event))
        await self._session.flush()
        await self._insert_event(initial_event, flush=True)

    async def register_version(
        self,
        version: StrategyVersion,
        initial_events: tuple[RegistryLifecycleEvent, RegistryLifecycleEvent],
        audit_events: tuple[AuditEvent, AuditEvent],
    ) -> None:
        if type(version) is not StrategyVersion:
            raise StrategyRegistryError("version must be the exact C-021 contract.")
        if version.content_sha256 != strategy_version_content_sha256(version):
            raise StrategyRegistryError("C-021 content_sha256 does not match content.")
        if len(initial_events) != 2 or len(audit_events) != 2:
            raise StrategyRegistryError(
                "C-021 registration requires two initial lifecycle events."
            )
        expected = (
            (LifecycleAxis.C021_VERSION, "RESEARCH"),
            (LifecycleAxis.ARTIFACT_VERSION, "DRAFT"),
        )
        for event, audit_event, (axis, status) in zip(
            initial_events, audit_events, expected, strict=True
        ):
            _validate_initial_event(
                event,
                axis=axis,
                strategy_id=version.strategy_id,
                strategy_version_id=version.strategy_version_id,
                status=status,
            )
            _validate_audit_binding(event, audit_event)
        document = serialize_contract(version, payload_version="wire-1")
        if len(document.encode("utf-8")) > MAX_DOCUMENT_BYTES:
            raise StrategyRegistryError("C-021 document exceeds the registry limit.")
        await self._session.execute(
            insert(strategy_registry_versions).values(
                strategy_version_id=version.strategy_version_id,
                strategy_id=version.strategy_id,
                semantic_version=version.semantic_version,
                parent_version_id=version.parent_version_id,
                content_sha256=version.content_sha256,
                document_sha256=contract_sha256(version, payload_version="wire-1"),
                canonical_document=document,
                created_at=version.created_at,
            )
        )
        for audit_event in audit_events:
            self._session.add(AuditEventRow.from_event(audit_event))
        await self._session.flush()
        for event in initial_events:
            await self._insert_event(event, flush=False)
        await self._session.flush()

    async def get_strategy(self, strategy_id: UUID) -> Strategy | None:
        result = await self._session.execute(
            select(strategy_registry_identities).where(
                strategy_registry_identities.c.strategy_id == strategy_id
            )
        )
        row = result.mappings().one_or_none()
        if row is None:
            return None
        record = _decode_contract(row["canonical_document"], "C-020")
        if (
            type(record) is not Strategy
            or record.strategy_id != strategy_id
            or record.created_at != row["created_at"]
            or contract_sha256(record, payload_version="wire-1")
            != row["content_sha256"]
        ):
            raise StrategyRegistryError(
                "stored C-020 record failed identity verification."
            )
        return record

    async def get_version(self, strategy_version_id: UUID) -> StrategyVersion | None:
        result = await self._session.execute(
            select(strategy_registry_versions).where(
                strategy_registry_versions.c.strategy_version_id == strategy_version_id
            )
        )
        row = result.mappings().one_or_none()
        return None if row is None else self._decode_version_row(row)

    async def get_version_by_semantic_version(
        self, strategy_id: UUID, semantic_version: str
    ) -> StrategyVersion | None:
        result = await self._session.execute(
            select(strategy_registry_versions).where(
                and_(
                    strategy_registry_versions.c.strategy_id == strategy_id,
                    strategy_registry_versions.c.semantic_version == semantic_version,
                )
            )
        )
        row = result.mappings().one_or_none()
        return None if row is None else self._decode_version_row(row)

    async def current_status(
        self,
        axis: LifecycleAxis,
        strategy_id: UUID,
        strategy_version_id: UUID | None,
        *,
        as_of: datetime | None = None,
    ) -> str | None:
        filters = [
            strategy_registry_lifecycle_events.c.axis == axis.value,
            strategy_registry_lifecycle_events.c.strategy_id == strategy_id,
        ]
        if strategy_version_id is None:
            filters.append(
                strategy_registry_lifecycle_events.c.strategy_version_id.is_(None)
            )
        else:
            filters.append(
                strategy_registry_lifecycle_events.c.strategy_version_id
                == strategy_version_id
            )
        if as_of is not None:
            filters.append(strategy_registry_lifecycle_events.c.effective_at <= as_of)
        statement = (
            select(strategy_registry_lifecycle_events.c.to_status)
            .where(*filters)
            .order_by(
                strategy_registry_lifecycle_events.c.effective_at.desc(),
                strategy_registry_lifecycle_events.c.recorded_at.desc(),
                strategy_registry_lifecycle_events.c.event_id.desc(),
            )
            .limit(1)
        )
        result = await self._session.execute(statement)
        return result.scalar_one_or_none()

    async def history(
        self,
        axis: LifecycleAxis,
        strategy_id: UUID,
        strategy_version_id: UUID | None,
    ) -> tuple[RegistryLifecycleEvent, ...]:
        filters = [
            strategy_registry_lifecycle_events.c.axis == axis.value,
            strategy_registry_lifecycle_events.c.strategy_id == strategy_id,
        ]
        if strategy_version_id is None:
            filters.append(
                strategy_registry_lifecycle_events.c.strategy_version_id.is_(None)
            )
        else:
            filters.append(
                strategy_registry_lifecycle_events.c.strategy_version_id
                == strategy_version_id
            )
        result = await self._session.execute(
            select(strategy_registry_lifecycle_events)
            .where(*filters)
            .order_by(
                strategy_registry_lifecycle_events.c.effective_at,
                strategy_registry_lifecycle_events.c.recorded_at,
                strategy_registry_lifecycle_events.c.event_id,
            )
        )
        return tuple(_event_from_row(row) for row in result.mappings())

    async def append_transition(
        self,
        event: RegistryLifecycleEvent,
        audit_event: AuditEvent,
        *,
        expected_from_status: str,
    ) -> bool:
        await self._lock_subject(event)
        current = await self.current_status(
            event.axis, event.strategy_id, event.strategy_version_id
        )
        if event.from_status != expected_from_status or current != expected_from_status:
            return False
        history = await self.history(
            event.axis, event.strategy_id, event.strategy_version_id
        )
        if history and event.effective_at <= history[-1].effective_at:
            return False
        if event.axis is not LifecycleAxis.STRATEGY_AVAILABILITY:
            if event.strategy_version_id is None:
                return False
            source_version = await self.get_version(event.strategy_version_id)
            if (
                source_version is None
                or event.environment not in source_version.environments
                or event.operating_mode not in source_version.operating_modes
            ):
                return False
            if event.rollback_target_version_id is not None:
                target_version = await self.get_version(
                    event.rollback_target_version_id
                )
                if (
                    target_version is None
                    or target_version.strategy_id != event.strategy_id
                    or event.environment not in target_version.environments
                    or event.operating_mode not in target_version.operating_modes
                ):
                    return False
                target_status = await self.current_status(
                    event.axis,
                    event.strategy_id,
                    event.rollback_target_version_id,
                    as_of=event.effective_at,
                )
                if target_status not in {"APPROVED_FOR_PRODUCTION", "ACTIVE"}:
                    return False
        _validate_audit_binding(event, audit_event)
        await self._session.flush()
        self._session.add(AuditEventRow.from_event(audit_event))
        await self._session.flush()
        await self._insert_event(event, flush=True)
        return True

    async def append_rejected_transition(self, audit_event: AuditEvent) -> None:
        if type(audit_event) is not AuditEvent:
            raise TypeError("audit_event must be a validated C-060 AuditEvent.")
        if audit_event.event_type is not AuditEventType.CONFIGURATION_CHANGED:
            raise StrategyRegistryError(
                "rejected lifecycle attempts require C-060 change audit."
            )
        self._session.add(AuditEventRow.from_event(audit_event))
        await self._session.flush()

    async def _lock_subject(self, event: RegistryLifecycleEvent) -> None:
        table = (
            strategy_registry_identities
            if event.axis is LifecycleAxis.STRATEGY_AVAILABILITY
            else strategy_registry_versions
        )
        identity_column = (
            table.c.strategy_id
            if event.axis is LifecycleAxis.STRATEGY_AVAILABILITY
            else table.c.strategy_version_id
        )
        identity_value = (
            event.strategy_id
            if event.axis is LifecycleAxis.STRATEGY_AVAILABILITY
            else event.strategy_version_id
        )
        await self._session.execute(
            select(identity_column)
            .where(identity_column == identity_value)
            .with_for_update()
        )

    async def _insert_event(
        self, event: RegistryLifecycleEvent, *, flush: bool
    ) -> None:
        await self._session.execute(
            insert(strategy_registry_lifecycle_events).values(
                event_id=event.event_id,
                audit_id=event.audit_id,
                axis=event.axis.value,
                strategy_id=event.strategy_id,
                strategy_version_id=event.strategy_version_id,
                rollback_target_version_id=event.rollback_target_version_id,
                resolves_suspension_event_id=event.resolves_suspension_event_id,
                environment=(event.environment.value if event.environment else None),
                operating_mode=(
                    event.operating_mode.value if event.operating_mode else None
                ),
                from_status=event.from_status,
                to_status=event.to_status,
                actor=event.actor,
                reason=event.reason,
                decision_reference=_reference_document(event.decision_reference),
                evidence_references=[
                    _reference_document(item) for item in event.evidence_references
                ],
                effective_at=event.effective_at,
                recorded_at=event.recorded_at,
            )
        )
        if flush:
            await self._session.flush()

    def _decode_version_row(self, row: Any) -> StrategyVersion:
        record = _decode_contract(row["canonical_document"], "C-021")
        if (
            type(record) is not StrategyVersion
            or record.strategy_version_id != row["strategy_version_id"]
            or record.strategy_id != row["strategy_id"]
            or record.semantic_version != row["semantic_version"]
            or record.parent_version_id != row["parent_version_id"]
            or record.created_at != row["created_at"]
            or record.content_sha256 != row["content_sha256"]
            or contract_sha256(record, payload_version="wire-1")
            != row["document_sha256"]
            or strategy_version_content_sha256(record) != row["content_sha256"]
        ):
            raise StrategyRegistryError(
                "stored C-021 record failed content verification."
            )
        return record


def _validate_initial_event(
    event: RegistryLifecycleEvent,
    *,
    axis: LifecycleAxis,
    strategy_id: UUID,
    strategy_version_id: UUID | None,
    status: str,
) -> None:
    if (
        event.axis is not axis
        or event.strategy_id != strategy_id
        or event.strategy_version_id != strategy_version_id
        or event.from_status is not None
        or event.to_status != status
    ):
        raise StrategyRegistryError(
            "initial lifecycle event does not match its registry record."
        )


def _validate_audit_binding(
    event: RegistryLifecycleEvent, audit_event: AuditEvent
) -> None:
    expected_subject_id = str(event.strategy_version_id or event.strategy_id)
    expected_action = (
        f"strategy_registry.{event.axis.value.lower()}.{event.to_status.lower()}"
    )
    if (
        type(audit_event) is not AuditEvent
        or audit_event.event_type is not AuditEventType.CONFIGURATION_CHANGED
        or audit_event.audit_id != event.audit_id
        or audit_event.actor != event.actor
        or audit_event.action != expected_action
        or audit_event.source != "trading-platform.strategy-registry"
        or audit_event.result != "ACCEPTED"
        or audit_event.correlation_id != str(event.event_id)
        or audit_event.trace_id != str(event.event_id)
        or audit_event.occurred_at != event.effective_at
        or audit_event.recorded_at != event.recorded_at
        or audit_event.reason != event.reason
        or audit_event.subject_type != event.axis.value
        or audit_event.subject_id != expected_subject_id
    ):
        raise StrategyRegistryError(
            "C-060 audit event does not bind the lifecycle event."
        )


def _decode_contract(document: str, expected_contract: str) -> object:
    try:
        if (
            type(document) is not str
            or len(document.encode("utf-8")) > MAX_DOCUMENT_BYTES
        ):
            raise ValueError
        envelope = json.loads(document)
        if (
            type(envelope) is not dict
            or set(envelope)
            != {
                "canonicalization_version",
                "contract_id",
                "schema_version",
                "payload_version",
                "payload",
            }
            or envelope["canonicalization_version"] != "canonical-json-v1"
            or envelope["contract_id"] != expected_contract
            or envelope["schema_version"] != "1"
            or envelope["payload_version"] != "wire-1"
            or type(envelope["payload"]) is not dict
        ):
            raise ValueError
        model = _MODELS[expected_contract]
        payload = dict(envelope["payload"])
        payload.update(contract_id=expected_contract, schema_version="1")
        record = _decode_value(model, payload)
        if serialize_contract(record, payload_version="wire-1") != document:
            raise ValueError
        return record
    except (ValueError, TypeError, KeyError, RecursionError, ArithmeticError):
        raise StrategyRegistryError(
            "stored strategy contract is invalid or noncanonical."
        ) from None


def _decode_value(kind: Any, value: Any) -> Any:
    origin = get_origin(kind)
    args = get_args(kind)
    if origin in (types.UnionType,):
        if value is None and type(None) in args:
            return None
        candidates = [item for item in args if item is not type(None)]
        if len(candidates) != 1:
            raise StrategyRegistryError("ambiguous stored strategy union.")
        return _decode_value(candidates[0], value)
    if origin is tuple and len(args) == 2 and args[1] is Ellipsis:
        if type(value) is not list:
            raise StrategyRegistryError("stored contract sequence is invalid.")
        return tuple(_decode_value(args[0], item) for item in value)
    if kind in (str, int, bool):
        if type(value) is not kind:
            raise StrategyRegistryError("stored contract scalar type is invalid.")
        return value
    if kind in (UUID, datetime, Decimal):
        if type(value) is not str:
            raise StrategyRegistryError("stored contract scalar encoding is invalid.")
        if kind is datetime:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        return kind(value)
    if isinstance(kind, type) and issubclass(kind, Enum):
        if type(value) is not str:
            raise StrategyRegistryError("stored enum encoding is invalid.")
        return kind(value)
    if isinstance(kind, type) and is_dataclass(kind):
        if type(value) is not dict or set(value) != {
            item.name for item in fields(kind)
        }:
            raise StrategyRegistryError("stored contract fields do not match.")
        hints = get_type_hints(kind)
        return kind(
            **{
                item.name: _decode_value(hints[item.name], value[item.name])
                for item in fields(kind)
                if item.init
            }
        )
    raise StrategyRegistryError("unsupported stored strategy contract value.")


def _reference_document(reference: VersionReference) -> dict[str, object]:
    return {
        "artifact_type": reference.artifact_type,
        "artifact_id": str(reference.artifact_id),
        "version": reference.version,
        "content_sha256": reference.content_sha256,
    }


def _event_from_row(row: Any) -> RegistryLifecycleEvent:
    return RegistryLifecycleEvent(
        axis=LifecycleAxis(row["axis"]),
        strategy_id=row["strategy_id"],
        strategy_version_id=row["strategy_version_id"],
        rollback_target_version_id=row["rollback_target_version_id"],
        resolves_suspension_event_id=row["resolves_suspension_event_id"],
        environment=(
            None
            if row["environment"] is None
            else DeploymentEnvironment(row["environment"])
        ),
        operating_mode=(
            None
            if row["operating_mode"] is None
            else OperatingMode(row["operating_mode"])
        ),
        from_status=row["from_status"],
        to_status=row["to_status"],
        actor=row["actor"],
        reason=row["reason"],
        decision_reference=_reference_from_document(row["decision_reference"]),
        evidence_references=tuple(
            _reference_from_document(item) for item in row["evidence_references"]
        ),
        effective_at=row["effective_at"],
        recorded_at=row["recorded_at"],
        event_id=row["event_id"],
        audit_id=row["audit_id"],
    )


def _reference_from_document(document: Any) -> VersionReference:
    if type(document) is not dict or set(document) != {
        "artifact_type",
        "artifact_id",
        "version",
        "content_sha256",
    }:
        raise StrategyRegistryError("stored lifecycle reference is invalid.")
    return VersionReference(
        artifact_type=document["artifact_type"],
        artifact_id=UUID(document["artifact_id"]),
        version=document["version"],
        content_sha256=document["content_sha256"],
    )


__all__ = ["SqlAlchemyStrategyRegistryStore"]
