"""Deterministic append-only signal lifecycle runtime for PERSONAL_SPOT_RESEARCH."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Protocol
from uuid import UUID, uuid5

from sqlalchemy import insert, select
from sqlalchemy.ext.asyncio import AsyncSession

from trading_platform_api.analysis.versioned_contracts_v5 import MarketContextV5
from trading_platform_api.audit.models import AuditEvent, AuditEventType
from trading_platform_api.audit.table import AuditEventRow
from trading_platform_api.contracts.serialization import canonical_sha256
from trading_platform_api.strategy.condition_evaluator import (
    ConditionTruth,
    StrategyConditionEvaluation,
)
from trading_platform_api.strategy.contracts import SignalCandidate, VersionReference
from trading_platform_api.strategy.contracts_v2 import (
    InvalidationCombinationV2,
    InvalidationTargetTypeV2,
    InvalidationTruthV2,
    SignalEvidencePackageV2,
    SignalQualificationV2,
    SignalV2,
    StrategyVersionV2,
)
from trading_platform_api.strategy.tables import signal_lifecycle_events

_EVENT_NAMESPACE = UUID("2b41822f-4ec5-5d2b-a683-19d975c59b1c")


class SignalLifecycleError(ValueError):
    """Raised when lifecycle state or provenance cannot be proven."""


class SignalLifecycleEventType(StrEnum):
    CREATED = "CREATED"
    WATCHED = "WATCHED"
    QUALIFIED = "QUALIFIED"
    REJECTED = "REJECTED"
    NO_TRADE = "NO_TRADE"
    INVALIDATED = "INVALIDATED"
    EXPIRED = "EXPIRED"
    SUPERSEDED = "SUPERSEDED"


class SignalLifecycleCause(StrEnum):
    SOURCE_DECISION = "SOURCE_DECISION"
    INVALIDATION_RULE_MATCHED = "INVALIDATION_RULE_MATCHED"
    EFFECTIVE_EXPIRY_REACHED = "EFFECTIVE_EXPIRY_REACHED"
    EXPLICIT_SUCCESSOR = "EXPLICIT_SUCCESSOR"


class SignalLifecycleProjection(StrEnum):
    CANDIDATE = "CANDIDATE"
    WATCH = "WATCH"
    QUALIFIED = "QUALIFIED"
    REJECTED = "REJECTED"
    NO_TRADE = "NO_TRADE"
    INVALIDATED = "INVALIDATED"
    EXPIRED = "EXPIRED"
    SUPERSEDED = "SUPERSEDED"


@dataclass(frozen=True, slots=True)
class SignalLifecycleEvent:
    subject: VersionReference
    prior_state: SignalLifecycleProjection | None
    resulting_state: SignalLifecycleProjection
    event_type: SignalLifecycleEventType
    cause: SignalLifecycleCause
    source_references: tuple[VersionReference, ...]
    event_time: datetime
    recorded_at: datetime
    correlation_id: str
    event_id: UUID = field(init=False)
    audit_id: UUID = field(init=False)

    def __post_init__(self) -> None:
        if type(self.subject) is not VersionReference:
            raise SignalLifecycleError("subject must be an exact VersionReference.")
        if (
            self.prior_state is not None
            and type(self.prior_state) is not SignalLifecycleProjection
        ):
            raise SignalLifecycleError("prior_state is invalid.")
        if type(self.resulting_state) is not SignalLifecycleProjection:
            raise SignalLifecycleError("resulting_state is invalid.")
        if type(self.event_type) is not SignalLifecycleEventType:
            raise SignalLifecycleError("event_type is invalid.")
        if type(self.cause) is not SignalLifecycleCause:
            raise SignalLifecycleError("cause is invalid.")
        if (
            type(self.source_references) is not tuple
            or not self.source_references
            or any(
                type(item) is not VersionReference for item in self.source_references
            )
            or len(set(self.source_references)) != len(self.source_references)
        ):
            raise SignalLifecycleError(
                "source_references must be unique exact references."
            )
        ordered_sources = tuple(
            sorted(
                self.source_references,
                key=lambda item: (
                    item.artifact_type,
                    str(item.artifact_id),
                    item.version,
                    item.content_sha256,
                ),
            )
        )
        object.__setattr__(self, "source_references", ordered_sources)
        event_time = _utc("event_time", self.event_time)
        recorded_at = _utc("recorded_at", self.recorded_at)
        if event_time > recorded_at:
            raise SignalLifecycleError("event_time cannot follow recorded_at.")
        if not isinstance(self.correlation_id, str) or not self.correlation_id.strip():
            raise SignalLifecycleError("correlation_id must be non-blank.")
        _validate_transition(
            self.prior_state, self.resulting_state, self.event_type, self.cause
        )
        identity = {
            "subject": self.subject,
            "event_type": self.event_type.value,
            "cause": self.cause.value,
            "source_references": self.source_references,
            "resulting_state": self.resulting_state.value,
            "event_time": event_time,
        }
        event_id = uuid5(_EVENT_NAMESPACE, canonical_sha256(identity))
        object.__setattr__(self, "event_time", event_time)
        object.__setattr__(self, "recorded_at", recorded_at)
        object.__setattr__(self, "event_id", event_id)
        object.__setattr__(self, "audit_id", event_id)


@dataclass(frozen=True, slots=True)
class SignalLifecycleAppendResult:
    accepted: bool
    duplicate: bool
    projection: SignalLifecycleProjection | None
    event: SignalLifecycleEvent | None
    audit_event: AuditEvent


class SignalLifecycleStore(Protocol):
    async def history(
        self, subject: VersionReference
    ) -> tuple[SignalLifecycleEvent, ...]: ...

    async def append(
        self, event: SignalLifecycleEvent, audit_event: AuditEvent
    ) -> bool: ...

    async def append_rejected(self, audit_event: AuditEvent) -> None: ...


class SqlAlchemySignalLifecycleStore:
    """Append-only lifecycle store; transaction ownership remains with the caller."""

    def __init__(self, session: AsyncSession) -> None:
        if not isinstance(session, AsyncSession):
            raise TypeError("session must be an AsyncSession.")
        self._session = session

    async def history(
        self, subject: VersionReference
    ) -> tuple[SignalLifecycleEvent, ...]:
        rows = await self._session.execute(
            select(signal_lifecycle_events)
            .where(
                signal_lifecycle_events.c.subject_contract_id == subject.artifact_type,
                signal_lifecycle_events.c.subject_id == subject.artifact_id,
                signal_lifecycle_events.c.subject_version == subject.version,
                signal_lifecycle_events.c.subject_sha256 == subject.content_sha256,
            )
            .order_by(
                signal_lifecycle_events.c.event_time,
                signal_lifecycle_events.c.recorded_at,
                signal_lifecycle_events.c.event_id,
            )
        )
        return tuple(_event_from_row(row) for row in rows.mappings())

    async def append(
        self, event: SignalLifecycleEvent, audit_event: AuditEvent
    ) -> bool:
        _validate_audit_binding(event, audit_event, accepted=True)
        existing = await self._session.execute(
            select(signal_lifecycle_events).where(
                signal_lifecycle_events.c.event_id == event.event_id
            )
        )
        row = existing.mappings().one_or_none()
        if row is not None:
            return _event_from_row(row) == event

        history = await self.history(event.subject)
        current = history[-1].resulting_state if history else None
        if current is not event.prior_state:
            return False
        if history and event.event_time <= history[-1].event_time:
            return False

        self._session.add(AuditEventRow.from_event(audit_event))
        await self._session.flush()
        await self._session.execute(
            insert(signal_lifecycle_events).values(
                event_id=event.event_id,
                audit_id=event.audit_id,
                subject_contract_id=event.subject.artifact_type,
                subject_id=event.subject.artifact_id,
                subject_version=event.subject.version,
                subject_sha256=event.subject.content_sha256,
                prior_state=event.prior_state.value if event.prior_state else None,
                resulting_state=event.resulting_state.value,
                event_type=event.event_type.value,
                cause=event.cause.value,
                source_references=[
                    _reference_document(item) for item in event.source_references
                ],
                event_time=event.event_time,
                recorded_at=event.recorded_at,
                correlation_id=event.correlation_id,
            )
        )
        await self._session.flush()
        return True

    async def append_rejected(self, audit_event: AuditEvent) -> None:
        if type(audit_event) is not AuditEvent:
            raise TypeError("audit_event must be C-060.")
        existing = await self._session.execute(
            select(AuditEventRow.audit_id).where(
                AuditEventRow.audit_id == audit_event.audit_id
            )
        )
        if existing.scalar_one_or_none() is not None:
            return
        self._session.add(AuditEventRow.from_event(audit_event))
        await self._session.flush()


class SignalLifecycleRuntime:
    def __init__(self, store: SignalLifecycleStore) -> None:
        self._store = store

    async def record(
        self,
        event: SignalLifecycleEvent,
        *,
        actor: str,
    ) -> SignalLifecycleAppendResult:
        history = await self._store.history(event.subject)
        current = history[-1].resulting_state if history else None
        if any(item.event_id == event.event_id for item in history):
            audit = _audit_for(event, actor=actor, accepted=True)
            return SignalLifecycleAppendResult(True, True, current, event, audit)
        if current is not event.prior_state:
            audit = _audit_for(event, actor=actor, accepted=False)
            await self._store.append_rejected(audit)
            return SignalLifecycleAppendResult(False, False, current, None, audit)
        audit = _audit_for(event, actor=actor, accepted=True)
        accepted = await self._store.append(event, audit)
        if not accepted:
            rejected = _audit_for(event, actor=actor, accepted=False)
            await self._store.append_rejected(rejected)
            return SignalLifecycleAppendResult(False, False, current, None, rejected)
        return SignalLifecycleAppendResult(
            True, False, event.resulting_state, event, audit
        )

    async def projection(
        self, subject: VersionReference
    ) -> SignalLifecycleProjection | None:
        history = await self._store.history(subject)
        return history[-1].resulting_state if history else None


def publish_qualified_signal(
    *,
    candidate: SignalCandidate,
    strategy: StrategyVersionV2,
    package: SignalEvidencePackageV2,
    qualification: SignalQualificationV2,
    market_context: MarketContextV5,
    now: datetime,
    recorded_at: datetime,
    correlation_id: str,
    signal_fields: dict[str, object],
) -> tuple[SignalV2, SignalLifecycleEvent]:
    """Resolve the exact qualified C-070v2 and its matching lifecycle event."""
    signal = SignalV2.build(
        candidate=candidate,
        strategy=strategy,
        package=package,
        qualification=qualification,
        market_context=market_context,
        now=now,
        signal_fields=signal_fields,
    )
    candidate_ref = VersionReference(
        "C-023", candidate.candidate_id, "1", canonical_sha256(candidate)
    )
    signal_ref = VersionReference(
        "C-070", signal.signal_id, "2", canonical_sha256(signal)
    )
    event = SignalLifecycleEvent(
        subject=candidate_ref,
        prior_state=SignalLifecycleProjection.CANDIDATE,
        resulting_state=SignalLifecycleProjection.QUALIFIED,
        event_type=SignalLifecycleEventType.QUALIFIED,
        cause=SignalLifecycleCause.SOURCE_DECISION,
        source_references=(
            signal_ref,
            signal.lineage.qualification,
            signal.lineage.validation,
        ),
        event_time=signal.created_at,
        recorded_at=recorded_at,
        correlation_id=correlation_id,
    )
    return signal, event


def invalidation_rule_matches(
    *,
    version: StrategyVersionV2,
    evaluation: StrategyConditionEvaluation,
    now: datetime,
) -> bool:
    at = _utc("now", now)
    if (
        type(version) is not StrategyVersionV2
        or type(evaluation) is not StrategyConditionEvaluation
        or evaluation.strategy_id != version.strategy_id
        or evaluation.strategy_version_id != version.strategy_version_id
        or evaluation.semantic_version != version.semantic_version
        or evaluation.content_sha256 != version.content_sha256
        or evaluation.evaluated_at > at
        or evaluation.expires_at <= at
    ):
        return False
    condition_truth = {item.condition_id: item.truth for item in evaluation.conditions}
    group_truth = {item.group_id: item.truth for item in evaluation.groups}
    matches: list[bool] = []
    for trigger in version.invalidation_rules.triggers:
        values = (
            condition_truth
            if trigger.target_type is InvalidationTargetTypeV2.CONDITION
            else group_truth
        )
        truth = values.get(trigger.target_id)
        expected = (
            ConditionTruth.PASS
            if trigger.trigger_truth is InvalidationTruthV2.PASS
            else ConditionTruth.FAIL
        )
        matches.append(truth is expected)
    if version.invalidation_rules.combine is InvalidationCombinationV2.ANY:
        return any(matches)
    return bool(matches) and all(matches)


def effective_expiry(*values: datetime) -> datetime:
    if not values:
        raise SignalLifecycleError("at least one expiry is required.")
    return min(_utc("expiry", value) for value in values)


def can_explicitly_supersede(
    *,
    predecessor: SignalCandidate,
    successor: SignalCandidate,
    strategy_version: VersionReference,
) -> bool:
    return (
        type(predecessor) is SignalCandidate
        and type(successor) is SignalCandidate
        and type(strategy_version) is VersionReference
        and strategy_version.artifact_type == "C-021"
        and predecessor.candidate_id != successor.candidate_id
        and predecessor.strategy_id == successor.strategy_id
        and predecessor.strategy_version_id
        == successor.strategy_version_id
        == strategy_version.artifact_id
        and predecessor.entry_concept.method.version == strategy_version.version
        and successor.entry_concept.method.version == strategy_version.version
        and predecessor.entry_concept.method.content_sha256
        == successor.entry_concept.method.content_sha256
        == strategy_version.content_sha256
        and predecessor.asset == successor.asset
        and predecessor.instrument_id == successor.instrument_id
        and predecessor.timeframe == successor.timeframe
        and predecessor.direction == successor.direction
    )


def _validate_transition(
    prior: SignalLifecycleProjection | None,
    result: SignalLifecycleProjection,
    event: SignalLifecycleEventType,
    cause: SignalLifecycleCause,
) -> None:
    if event is SignalLifecycleEventType.WATCHED:
        raise SignalLifecycleError(
            "WATCH has no approved PERSONAL_SPOT_RESEARCH producer."
        )
    allowed = {
        SignalLifecycleEventType.CREATED: (
            None,
            SignalLifecycleProjection.CANDIDATE,
            SignalLifecycleCause.SOURCE_DECISION,
        ),
        SignalLifecycleEventType.QUALIFIED: (
            SignalLifecycleProjection.CANDIDATE,
            SignalLifecycleProjection.QUALIFIED,
            SignalLifecycleCause.SOURCE_DECISION,
        ),
        SignalLifecycleEventType.REJECTED: (
            SignalLifecycleProjection.CANDIDATE,
            SignalLifecycleProjection.REJECTED,
            SignalLifecycleCause.SOURCE_DECISION,
        ),
        SignalLifecycleEventType.NO_TRADE: (
            SignalLifecycleProjection.CANDIDATE,
            SignalLifecycleProjection.NO_TRADE,
            SignalLifecycleCause.SOURCE_DECISION,
        ),
        SignalLifecycleEventType.INVALIDATED: (
            {SignalLifecycleProjection.CANDIDATE, SignalLifecycleProjection.QUALIFIED},
            SignalLifecycleProjection.INVALIDATED,
            SignalLifecycleCause.INVALIDATION_RULE_MATCHED,
        ),
        SignalLifecycleEventType.EXPIRED: (
            {SignalLifecycleProjection.CANDIDATE, SignalLifecycleProjection.QUALIFIED},
            SignalLifecycleProjection.EXPIRED,
            SignalLifecycleCause.EFFECTIVE_EXPIRY_REACHED,
        ),
        SignalLifecycleEventType.SUPERSEDED: (
            {SignalLifecycleProjection.CANDIDATE, SignalLifecycleProjection.QUALIFIED},
            SignalLifecycleProjection.SUPERSEDED,
            SignalLifecycleCause.EXPLICIT_SUCCESSOR,
        ),
    }[event]
    expected_prior, expected_result, expected_cause = allowed
    prior_ok = (
        prior in expected_prior
        if isinstance(expected_prior, set)
        else prior is expected_prior
    )
    if not prior_ok or result is not expected_result or cause is not expected_cause:
        raise SignalLifecycleError("illegal lifecycle transition.")


def _audit_for(
    event: SignalLifecycleEvent, *, actor: str, accepted: bool
) -> AuditEvent:
    event_type = AuditEventType.SIGNAL_UPDATED
    if accepted and event.event_type is SignalLifecycleEventType.CREATED:
        event_type = AuditEventType.SIGNAL_CREATED
    elif not accepted or event.event_type is SignalLifecycleEventType.REJECTED:
        event_type = AuditEventType.SIGNAL_REJECTED
    return AuditEvent(
        event_type=event_type,
        actor=actor,
        action=f"signal_lifecycle.{event.event_type.value.lower()}",
        source="trading-platform.signal-lifecycle",
        result="ACCEPTED" if accepted else "REJECTED",
        correlation_id=event.correlation_id,
        trace_id=str(event.event_id),
        audit_id=event.audit_id if accepted else uuid5(event.event_id, "rejected"),
        occurred_at=event.event_time,
        recorded_at=event.recorded_at,
        reason=event.cause.value,
        subject_type=event.subject.artifact_type,
        subject_id=str(event.subject.artifact_id),
    )


def _validate_audit_binding(
    event: SignalLifecycleEvent, audit: AuditEvent, *, accepted: bool
) -> None:
    expected = _audit_for(event, actor=audit.actor, accepted=accepted)
    if audit != expected:
        raise SignalLifecycleError("C-060 audit event does not bind lifecycle event.")


def _reference_document(reference: VersionReference) -> dict[str, str]:
    return {
        "artifact_type": reference.artifact_type,
        "artifact_id": str(reference.artifact_id),
        "version": reference.version,
        "content_sha256": reference.content_sha256,
    }


def _reference_from_document(value: object) -> VersionReference:
    if type(value) is not dict or set(value) != {
        "artifact_type",
        "artifact_id",
        "version",
        "content_sha256",
    }:
        raise SignalLifecycleError("stored lifecycle reference is invalid.")
    return VersionReference(
        value["artifact_type"],
        UUID(value["artifact_id"]),
        value["version"],
        value["content_sha256"],
    )


def _event_from_row(row: Any) -> SignalLifecycleEvent:
    event = SignalLifecycleEvent(
        subject=VersionReference(
            row["subject_contract_id"],
            row["subject_id"],
            row["subject_version"],
            row["subject_sha256"],
        ),
        prior_state=(
            None
            if row["prior_state"] is None
            else SignalLifecycleProjection(row["prior_state"])
        ),
        resulting_state=SignalLifecycleProjection(row["resulting_state"]),
        event_type=SignalLifecycleEventType(row["event_type"]),
        cause=SignalLifecycleCause(row["cause"]),
        source_references=tuple(
            _reference_from_document(item) for item in row["source_references"]
        ),
        event_time=row["event_time"],
        recorded_at=row["recorded_at"],
        correlation_id=row["correlation_id"],
    )
    if event.event_id != row["event_id"] or event.audit_id != row["audit_id"]:
        raise SignalLifecycleError("stored lifecycle identity is invalid.")
    return event


def _utc(name: str, value: object) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise SignalLifecycleError(f"{name} must be timezone-aware.")
    return value.astimezone(UTC)


__all__ = [
    "SignalLifecycleAppendResult",
    "SignalLifecycleCause",
    "SignalLifecycleError",
    "SignalLifecycleEvent",
    "SignalLifecycleEventType",
    "SignalLifecycleProjection",
    "SignalLifecycleRuntime",
    "SqlAlchemySignalLifecycleStore",
    "can_explicitly_supersede",
    "effective_expiry",
    "invalidation_rule_matches",
    "publish_qualified_signal",
]
