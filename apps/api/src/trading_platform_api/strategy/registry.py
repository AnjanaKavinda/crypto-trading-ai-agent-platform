"""Governed immutable strategy registry domain and lifecycle transitions."""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field, fields
from datetime import UTC, datetime
from enum import StrEnum
from typing import Protocol
from uuid import UUID, uuid4

from trading_platform_api.audit import AuditEvent, AuditEventType
from trading_platform_api.config import DeploymentEnvironment, OperatingMode
from trading_platform_api.contracts.serialization import (
    CANONICAL_JSON_VERSION,
    canonical_sha256,
)
from trading_platform_api.strategy.contracts import (
    Strategy,
    StrategyLifecycle,
    StrategyVersion,
    VersionReference,
)


class StrategyRegistryError(ValueError):
    """Invalid registry operation with a stable machine-readable error code."""

    def __init__(
        self, message: str, *, code: str = "STRATEGY_REGISTRY_INVALID"
    ) -> None:
        super().__init__(message)
        self.code = code


class StrategyAvailability(StrEnum):
    EXPERIMENTAL = "EXPERIMENTAL"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    DEPRECATED = "DEPRECATED"


class ArtifactVersionLifecycle(StrEnum):
    """The shared Version Registry axis, distinct from C-021 lifecycle."""

    DRAFT = "DRAFT"
    CANDIDATE = "CANDIDATE"
    VALIDATED = "VALIDATED"
    APPROVED_FOR_SHADOW = "APPROVED_FOR_SHADOW"
    APPROVED_FOR_PAPER = "APPROVED_FOR_PAPER"
    APPROVED_FOR_PRODUCTION = "APPROVED_FOR_PRODUCTION"
    ACTIVE = "ACTIVE"
    REJECTED = "REJECTED"
    RETIRED = "RETIRED"
    ROLLED_BACK = "ROLLED_BACK"


class LifecycleAxis(StrEnum):
    STRATEGY_AVAILABILITY = "STRATEGY_AVAILABILITY"
    C021_VERSION = "C021_VERSION"
    ARTIFACT_VERSION = "ARTIFACT_VERSION"


@dataclass(frozen=True, slots=True)
class ResolvedLifecycleReference:
    """Exact owner-resolved governance or validation reference."""

    reference: VersionReference
    status: str
    subject_id: UUID
    expires_at: datetime | None = None
    environment: DeploymentEnvironment | None = None
    operating_mode: OperatingMode | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.reference, VersionReference):
            raise StrategyRegistryError("reference must be a VersionReference.")
        _required_text("resolved status", self.status, limit=64)
        if re.fullmatch(r"[A-Z][A-Z0-9_]*", self.status) is None:
            raise StrategyRegistryError(
                "resolved status must use canonical uppercase vocabulary."
            )
        if not isinstance(self.subject_id, UUID):
            raise StrategyRegistryError("resolved subject_id must be a UUID.")
        if self.expires_at is not None:
            object.__setattr__(
                self, "expires_at", _aware_utc("expires_at", self.expires_at)
            )


class LifecycleReferenceResolver(Protocol):
    async def resolve(
        self, reference: VersionReference, *, at: datetime
    ) -> ResolvedLifecycleReference | None: ...


class StrategyRegistryStore(Protocol):
    async def register_strategy(
        self,
        strategy: Strategy,
        initial_event: RegistryLifecycleEvent,
        audit_event: AuditEvent,
    ) -> None: ...

    async def register_version(
        self,
        version: StrategyVersion,
        initial_events: tuple[RegistryLifecycleEvent, RegistryLifecycleEvent],
        audit_events: tuple[AuditEvent, AuditEvent],
    ) -> None: ...

    async def get_strategy(self, strategy_id: UUID) -> Strategy | None: ...

    async def get_version(
        self, strategy_version_id: UUID
    ) -> StrategyVersion | None: ...

    async def get_version_by_semantic_version(
        self, strategy_id: UUID, semantic_version: str
    ) -> StrategyVersion | None: ...

    async def current_status(
        self,
        axis: LifecycleAxis,
        strategy_id: UUID,
        strategy_version_id: UUID | None,
        *,
        as_of: datetime | None = None,
    ) -> str | None: ...

    async def history(
        self,
        axis: LifecycleAxis,
        strategy_id: UUID,
        strategy_version_id: UUID | None,
    ) -> tuple[RegistryLifecycleEvent, ...]: ...

    async def append_transition(
        self,
        event: RegistryLifecycleEvent,
        audit_event: AuditEvent,
        *,
        expected_from_status: str,
    ) -> bool: ...

    async def append_rejected_transition(self, audit_event: AuditEvent) -> None: ...


@dataclass(frozen=True, slots=True)
class RegistryLifecycleEvent:
    """Append-only event for exactly one of the three independent status axes."""

    axis: LifecycleAxis
    strategy_id: UUID
    strategy_version_id: UUID | None
    from_status: str | None
    to_status: str
    actor: str
    reason: str
    decision_reference: VersionReference
    evidence_references: tuple[VersionReference, ...]
    effective_at: datetime
    recorded_at: datetime
    rollback_target_version_id: UUID | None = None
    resolves_suspension_event_id: UUID | None = None
    environment: DeploymentEnvironment | None = None
    operating_mode: OperatingMode | None = None
    event_id: UUID = field(default_factory=uuid4)
    audit_id: UUID = field(default_factory=uuid4)

    def __post_init__(self) -> None:
        if not isinstance(self.axis, LifecycleAxis):
            raise StrategyRegistryError("axis must be a LifecycleAxis.")
        if not isinstance(self.strategy_id, UUID):
            raise StrategyRegistryError("strategy_id must be a UUID.")
        if self.axis is LifecycleAxis.STRATEGY_AVAILABILITY:
            if self.strategy_version_id is not None:
                raise StrategyRegistryError(
                    "strategy availability must target a strategy identity."
                )
            if self.environment is not None or self.operating_mode is not None:
                raise StrategyRegistryError(
                    "strategy availability cannot carry version environment/mode scope."
                )
        elif not isinstance(self.strategy_version_id, UUID):
            raise StrategyRegistryError("version lifecycle requires a version ID.")
        elif self.from_status is None:
            if self.environment is not None or self.operating_mode is not None:
                raise StrategyRegistryError(
                    "initial version lifecycle states cannot carry transition scope."
                )
        elif not isinstance(self.environment, DeploymentEnvironment) or not isinstance(
            self.operating_mode, OperatingMode
        ):
            raise StrategyRegistryError(
                "version lifecycle transitions require explicit environment and mode."
            )
        if self.to_status == "ROLLED_BACK":
            if (
                self.axis is LifecycleAxis.STRATEGY_AVAILABILITY
                or not isinstance(self.rollback_target_version_id, UUID)
                or self.rollback_target_version_id == self.strategy_version_id
            ):
                raise StrategyRegistryError(
                    "rolled-back version events require a distinct rollback target."
                )
        elif self.rollback_target_version_id is not None:
            raise StrategyRegistryError(
                "rollback_target_version_id is valid only for ROLLED_BACK events."
            )
        resolves_suspension = (
            self.axis is LifecycleAxis.STRATEGY_AVAILABILITY
            and self.from_status == StrategyAvailability.SUSPENDED.value
            and self.to_status == StrategyAvailability.ACTIVE.value
        )
        if resolves_suspension != isinstance(self.resolves_suspension_event_id, UUID):
            raise StrategyRegistryError(
                "suspension reactivation must link exactly one prior suspension event."
            )
        if self.resolves_suspension_event_id == self.event_id:
            raise StrategyRegistryError(
                "a lifecycle event cannot resolve itself as a suspension event."
            )
        if self.from_status is not None:
            _required_text("from_status", self.from_status)
        _required_text("to_status", self.to_status)
        if self.from_status is None:
            initial_status = {
                LifecycleAxis.STRATEGY_AVAILABILITY: StrategyAvailability.EXPERIMENTAL.value,
                LifecycleAxis.C021_VERSION: StrategyLifecycle.RESEARCH.value,
                LifecycleAxis.ARTIFACT_VERSION: ArtifactVersionLifecycle.DRAFT.value,
            }[self.axis]
            if self.to_status != initial_status:
                raise StrategyRegistryError(
                    "registry lifecycle initial state is invalid."
                )
        elif self.to_status not in _transitions_for(self.axis, self.from_status):
            raise StrategyRegistryError("registry lifecycle transition is invalid.")
        _required_text("actor", self.actor, limit=255)
        _required_text("reason", self.reason, limit=2000)
        if not isinstance(self.decision_reference, VersionReference):
            raise StrategyRegistryError(
                "decision_reference must be a VersionReference."
            )
        if (
            not isinstance(self.evidence_references, tuple)
            or not self.evidence_references
        ):
            raise StrategyRegistryError("evidence_references must not be empty.")
        if not all(
            isinstance(item, VersionReference) for item in self.evidence_references
        ):
            raise StrategyRegistryError("evidence_references contain an invalid item.")
        if len(set(self.evidence_references)) != len(self.evidence_references):
            raise StrategyRegistryError(
                "evidence_references must not contain duplicates."
            )
        effective_at = _aware_utc("effective_at", self.effective_at)
        recorded_at = _aware_utc("recorded_at", self.recorded_at)
        object.__setattr__(self, "effective_at", effective_at)
        object.__setattr__(self, "recorded_at", recorded_at)
        if effective_at > recorded_at:
            raise StrategyRegistryError("effective_at must not be in the future.")
        if not isinstance(self.event_id, UUID) or not isinstance(self.audit_id, UUID):
            raise StrategyRegistryError("event_id and audit_id must be UUIDs.")
        if self.event_id != self.audit_id:
            raise StrategyRegistryError("event_id must equal its C-060 audit_id.")


@dataclass(frozen=True, slots=True)
class TransitionResult:
    accepted: bool
    reason_code: str
    current_status: str | None
    event: RegistryLifecycleEvent | None
    audit_event: AuditEvent


@dataclass(frozen=True, slots=True)
class ResolvedStrategyVersion:
    strategy: Strategy
    version: StrategyVersion
    availability: StrategyAvailability
    c021_lifecycle: StrategyLifecycle
    artifact_lifecycle: ArtifactVersionLifecycle

    @property
    def selectable_for_research(self) -> bool:
        return (
            self.availability
            in {StrategyAvailability.EXPERIMENTAL, StrategyAvailability.ACTIVE}
            and self.c021_lifecycle
            not in {
                StrategyLifecycle.REJECTED,
                StrategyLifecycle.RETIRED,
                StrategyLifecycle.ROLLED_BACK,
            }
            and self.artifact_lifecycle
            not in {
                ArtifactVersionLifecycle.REJECTED,
                ArtifactVersionLifecycle.RETIRED,
                ArtifactVersionLifecycle.ROLLED_BACK,
            }
        )


_NUMERIC_IDENTIFIER = r"(?:0|[1-9][0-9]*)"
_ALPHANUMERIC_IDENTIFIER = r"(?:[0-9A-Za-z-]*[A-Za-z-][0-9A-Za-z-]*)"
_PRERELEASE_IDENTIFIER = rf"(?:{_NUMERIC_IDENTIFIER}|{_ALPHANUMERIC_IDENTIFIER})"
_BUILD_IDENTIFIER = r"[0-9A-Za-z-]+"
_SEMVER = re.compile(
    rf"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)"
    rf"(?:-({_PRERELEASE_IDENTIFIER}(?:\.{_PRERELEASE_IDENTIFIER})*))?"
    rf"(?:\+({_BUILD_IDENTIFIER}(?:\.{_BUILD_IDENTIFIER})*))?$"
)
_AVAILABILITY_TRANSITIONS = {
    StrategyAvailability.EXPERIMENTAL.value: frozenset(
        {"ACTIVE", "SUSPENDED", "DEPRECATED"}
    ),
    StrategyAvailability.ACTIVE.value: frozenset({"SUSPENDED", "DEPRECATED"}),
    StrategyAvailability.SUSPENDED.value: frozenset({"ACTIVE", "DEPRECATED"}),
    StrategyAvailability.DEPRECATED.value: frozenset(),
}
_MATURITY_SEQUENCE = (
    "VALIDATED",
    "APPROVED_FOR_SHADOW",
    "APPROVED_FOR_PAPER",
    "APPROVED_FOR_PRODUCTION",
    "ACTIVE",
)
_C021_TRANSITIONS = {
    StrategyLifecycle.RESEARCH.value: frozenset({StrategyLifecycle.VALIDATED.value}),
    **{
        state: frozenset(
            {next_state, StrategyLifecycle.REJECTED.value}
            if next_state is not None
            else {StrategyLifecycle.REJECTED.value}
        )
        for state, next_state in zip(
            _MATURITY_SEQUENCE,
            (*_MATURITY_SEQUENCE[1:], None),
            strict=True,
        )
    },
    StrategyLifecycle.ACTIVE.value: frozenset(
        {
            StrategyLifecycle.REJECTED.value,
            StrategyLifecycle.RETIRED.value,
            StrategyLifecycle.ROLLED_BACK.value,
        }
    ),
    StrategyLifecycle.REJECTED.value: frozenset(),
    StrategyLifecycle.RETIRED.value: frozenset(),
    StrategyLifecycle.ROLLED_BACK.value: frozenset(),
}
_ARTIFACT_TRANSITIONS = {
    ArtifactVersionLifecycle.DRAFT.value: frozenset(
        {ArtifactVersionLifecycle.CANDIDATE.value}
    ),
    ArtifactVersionLifecycle.CANDIDATE.value: frozenset(
        {
            ArtifactVersionLifecycle.VALIDATED.value,
            ArtifactVersionLifecycle.REJECTED.value,
        }
    ),
    **{
        state: frozenset(
            {next_state, ArtifactVersionLifecycle.REJECTED.value}
            if next_state is not None
            else {ArtifactVersionLifecycle.REJECTED.value}
        )
        for state, next_state in zip(
            tuple(_MATURITY_SEQUENCE),
            (*_MATURITY_SEQUENCE[1:], None),
            strict=True,
        )
    },
    ArtifactVersionLifecycle.ACTIVE.value: frozenset(
        {
            ArtifactVersionLifecycle.REJECTED.value,
            ArtifactVersionLifecycle.RETIRED.value,
            ArtifactVersionLifecycle.ROLLED_BACK.value,
        }
    ),
    ArtifactVersionLifecycle.REJECTED.value: frozenset(),
    ArtifactVersionLifecycle.RETIRED.value: frozenset(),
    ArtifactVersionLifecycle.ROLLED_BACK.value: frozenset(),
}


def strategy_version_content_sha256(version: StrategyVersion) -> str:
    """Hash the complete C-021 record except its self-referential digest."""

    if type(version) is not StrategyVersion:
        raise StrategyRegistryError("version must be an exact StrategyVersion.")
    payload = {
        item.name: getattr(version, item.name)
        for item in fields(version)
        if item.name != "content_sha256"
    }
    return canonical_sha256(
        {
            "canonicalization_version": CANONICAL_JSON_VERSION,
            "contract_id": version.contract_id,
            "schema_version": version.schema_version,
            "payload_version": "wire-1",
            "payload": payload,
        }
    )


def validate_semantic_version(value: str) -> None:
    if type(value) is not str or _SEMVER.fullmatch(value) is None:
        raise StrategyRegistryError("semantic_version must be canonical SemVer.")


def semantic_version_is_greater(candidate: str, parent: str) -> bool:
    validate_semantic_version(candidate)
    validate_semantic_version(parent)
    candidate_match = _SEMVER.fullmatch(candidate)
    parent_match = _SEMVER.fullmatch(parent)
    assert candidate_match is not None and parent_match is not None
    candidate_core = tuple(int(candidate_match.group(i)) for i in range(1, 4))
    parent_core = tuple(int(parent_match.group(i)) for i in range(1, 4))
    if candidate_core != parent_core:
        return candidate_core > parent_core
    candidate_pre = candidate_match.group(4)
    parent_pre = parent_match.group(4)
    if candidate_pre is None:
        return parent_pre is not None
    if parent_pre is None:
        return False
    return _compare_prerelease(candidate_pre, parent_pre) > 0


def _compare_prerelease(first: str, second: str) -> int:
    first_parts = first.split(".")
    second_parts = second.split(".")
    for left, right in zip(first_parts, second_parts):
        if left == right:
            continue
        left_numeric = left.isdigit()
        right_numeric = right.isdigit()
        if left_numeric and right_numeric:
            return (int(left) > int(right)) - (int(left) < int(right))
        if left_numeric != right_numeric:
            return -1 if left_numeric else 1
        return (left > right) - (left < right)
    return (len(first_parts) > len(second_parts)) - (
        len(first_parts) < len(second_parts)
    )


class StrategyRegistry:
    """Application service over a durable, append-only registry store.

    The caller owns transaction commit/rollback. Reference resolution is
    delegated to the owning validation/governance registries; missing resolver
    support fails closed for all status transitions beyond initial registration.
    """

    def __init__(
        self,
        store: StrategyRegistryStore,
        *,
        reference_resolver: LifecycleReferenceResolver | None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._store = store
        self._reference_resolver = reference_resolver
        self._clock = clock or (lambda: datetime.now(UTC))

    async def register_strategy(
        self,
        strategy: Strategy,
        *,
        actor: str,
        reason: str,
        decision_reference: VersionReference,
        evidence_references: tuple[VersionReference, ...],
        effective_at: datetime | None = None,
    ) -> None:
        if type(strategy) is not Strategy:
            raise StrategyRegistryError("strategy must be the exact C-020 contract.")
        now = _aware_utc("recorded_at", self._clock())
        moment = _aware_utc("effective_at", effective_at or now)
        if moment > now:
            raise StrategyRegistryError(
                "effective_at must not be in the future.", code="FUTURE_EFFECTIVE_TIME"
            )
        if moment < strategy.created_at:
            raise StrategyRegistryError(
                "strategy availability cannot predate the C-020 identity.",
                code="PREMATURE_EFFECTIVE_TIME",
            )
        await self._verify_governance_reference(
            decision_reference,
            subject_id=strategy.strategy_id,
            at=moment,
            expected_status="APPROVED",
        )
        await self._verify_evidence_references(
            evidence_references, subject_id=None, at=moment
        )
        event = _make_event(
            axis=LifecycleAxis.STRATEGY_AVAILABILITY,
            strategy_id=strategy.strategy_id,
            strategy_version_id=None,
            from_status=None,
            to_status=StrategyAvailability.EXPERIMENTAL.value,
            actor=actor,
            reason=reason,
            decision_reference=decision_reference,
            evidence_references=evidence_references,
            effective_at=moment,
            recorded_at=now,
        )
        await self._store.register_strategy(
            strategy,
            event,
            _audit_for(event, accepted=True),
        )

    async def register_version(
        self,
        version: StrategyVersion,
        *,
        actor: str,
        reason: str,
        decision_reference: VersionReference,
        evidence_references: tuple[VersionReference, ...],
        effective_at: datetime | None = None,
    ) -> None:
        if version.lifecycle is not StrategyLifecycle.RESEARCH:
            raise StrategyRegistryError(
                "new C-021 versions must enter through RESEARCH."
            )
        validate_semantic_version(version.semantic_version)
        if version.content_sha256 != strategy_version_content_sha256(version):
            raise StrategyRegistryError(
                "C-021 content_sha256 does not match content.",
                code="CONTENT_HASH_MISMATCH",
            )
        if await self._store.get_strategy(version.strategy_id) is None:
            raise StrategyRegistryError(
                "strategy identity is unknown.", code="UNKNOWN_STRATEGY_IDENTITY"
            )
        parent: StrategyVersion | None = None
        if version.parent_version_id is not None:
            parent = await self._store.get_version(version.parent_version_id)
            if parent is None or parent.strategy_id != version.strategy_id:
                raise StrategyRegistryError(
                    "parent version is unknown or mismatched.",
                    code="UNKNOWN_OR_MISMATCHED_PARENT_VERSION",
                )
            if version.created_at < parent.created_at:
                raise StrategyRegistryError(
                    "child version creation cannot predate its parent.",
                    code="PREMATURE_VERSION_CREATION_TIME",
                )
            if not semantic_version_is_greater(
                version.semantic_version, parent.semantic_version
            ):
                raise StrategyRegistryError(
                    "child semantic_version must exceed its parent.",
                    code="NON_MONOTONIC_SEMANTIC_VERSION",
                )

        now = _aware_utc("recorded_at", self._clock())
        moment = _aware_utc("effective_at", effective_at or now)
        if moment > now:
            raise StrategyRegistryError(
                "effective_at must not be in the future.", code="FUTURE_EFFECTIVE_TIME"
            )
        identity = await self._store.get_strategy(version.strategy_id)
        if identity is not None and version.created_at < identity.created_at:
            raise StrategyRegistryError(
                "C-021 version creation cannot predate the C-020 identity.",
                code="PREMATURE_VERSION_CREATION_TIME",
            )
        if moment < version.created_at:
            raise StrategyRegistryError(
                "version lifecycle cannot predate the immutable C-021 version.",
                code="PREMATURE_EFFECTIVE_TIME",
            )
        await self._verify_governance_reference(
            decision_reference,
            subject_id=version.strategy_version_id,
            at=moment,
            expected_status="APPROVED",
        )
        if not set(version.provenance).issubset(evidence_references):
            raise StrategyRegistryError(
                "registration evidence must include every immutable C-021 provenance reference."
            )
        await self._verify_evidence_references(
            evidence_references, subject_id=None, at=moment
        )
        c021_event = _make_event(
            axis=LifecycleAxis.C021_VERSION,
            strategy_id=version.strategy_id,
            strategy_version_id=version.strategy_version_id,
            from_status=None,
            to_status=StrategyLifecycle.RESEARCH.value,
            actor=actor,
            reason=reason,
            decision_reference=decision_reference,
            evidence_references=evidence_references,
            effective_at=moment,
            recorded_at=now,
        )
        artifact_event = _make_event(
            axis=LifecycleAxis.ARTIFACT_VERSION,
            strategy_id=version.strategy_id,
            strategy_version_id=version.strategy_version_id,
            from_status=None,
            to_status=ArtifactVersionLifecycle.DRAFT.value,
            actor=actor,
            reason=reason,
            decision_reference=decision_reference,
            evidence_references=evidence_references,
            effective_at=moment,
            recorded_at=now,
        )
        await self._store.register_version(
            version,
            (c021_event, artifact_event),
            (
                _audit_for(c021_event, accepted=True),
                _audit_for(artifact_event, accepted=True),
            ),
        )

    async def transition(
        self,
        *,
        axis: LifecycleAxis,
        strategy_id: UUID,
        strategy_version_id: UUID | None,
        to_status: str,
        actor: str,
        reason: str,
        decision_reference: VersionReference,
        evidence_references: tuple[VersionReference, ...],
        environment: DeploymentEnvironment | None = None,
        operating_mode: OperatingMode | None = None,
        effective_at: datetime | None = None,
        rollback_target_version_id: UUID | None = None,
    ) -> TransitionResult:
        if not isinstance(axis, LifecycleAxis):
            raise StrategyRegistryError(
                "axis must be a LifecycleAxis.", code="INVALID_LIFECYCLE_AXIS"
            )
        now = _aware_utc("recorded_at", self._clock())
        moment = _aware_utc("effective_at", effective_at or now)
        if moment > now:
            return await self._reject(
                axis,
                strategy_id,
                strategy_version_id,
                to_status,
                actor,
                "FUTURE_EFFECTIVE_TIME",
                "effective_at must not be in the future",
                moment,
                now,
            )
        subject_id = (
            strategy_id
            if axis is LifecycleAxis.STRATEGY_AVAILABILITY
            else strategy_version_id
        )
        if subject_id is None:
            return await self._reject(
                axis,
                strategy_id,
                strategy_version_id,
                to_status,
                actor,
                "VERSION_ID_REQUIRED",
                "version lifecycle requires a version ID",
                moment,
                now,
            )
        strategy = await self._store.get_strategy(strategy_id)
        version = (
            None
            if strategy_version_id is None
            else await self._store.get_version(strategy_version_id)
        )
        if strategy is None or (
            axis is not LifecycleAxis.STRATEGY_AVAILABILITY
            and (version is None or version.strategy_id != strategy_id)
        ):
            return await self._reject(
                axis,
                strategy_id,
                strategy_version_id,
                to_status,
                actor,
                "UNKNOWN_SUBJECT",
                "registry subject is unknown or mismatched",
                moment,
                now,
            )

        if moment < strategy.created_at or (
            version is not None and moment < version.created_at
        ):
            return await self._reject(
                axis,
                strategy_id,
                strategy_version_id,
                to_status,
                actor,
                "PREMATURE_EFFECTIVE_TIME",
                "lifecycle transition cannot predate its immutable subject",
                moment,
                now,
            )
        current = await self._store.current_status(
            axis, strategy_id, strategy_version_id
        )
        if current is None:
            return await self._reject(
                axis,
                strategy_id,
                strategy_version_id,
                to_status,
                actor,
                "MISSING_INITIAL_STATE",
                "registry lifecycle has no initial event",
                moment,
                now,
            )
        allowed = _transitions_for(axis, current)
        if to_status not in allowed:
            return await self._reject(
                axis,
                strategy_id,
                strategy_version_id,
                to_status,
                actor,
                "ILLEGAL_TRANSITION",
                "requested lifecycle transition is not allowed",
                moment,
                now,
                current_status=current,
            )
        if (to_status == "ROLLED_BACK") != (rollback_target_version_id is not None):
            return await self._reject(
                axis,
                strategy_id,
                strategy_version_id,
                to_status,
                actor,
                "ROLLBACK_TARGET_REQUIRED"
                if to_status == "ROLLED_BACK"
                else "UNEXPECTED_ROLLBACK_TARGET",
                "rollback transitions require exactly one immutable target version",
                moment,
                now,
                current_status=current,
            )
        if rollback_target_version_id is not None:
            rollback_target = await self._store.get_version(rollback_target_version_id)
            if (
                axis is LifecycleAxis.STRATEGY_AVAILABILITY
                or rollback_target is None
                or rollback_target.strategy_id != strategy_id
                or rollback_target_version_id == strategy_version_id
            ):
                return await self._reject(
                    axis,
                    strategy_id,
                    strategy_version_id,
                    to_status,
                    actor,
                    "UNKNOWN_OR_INCOMPATIBLE_ROLLBACK_TARGET",
                    "rollback target must be a distinct version of the same strategy",
                    moment,
                    now,
                    current_status=current,
                )
            if (
                environment not in rollback_target.environments
                or operating_mode not in rollback_target.operating_modes
            ):
                return await self._reject(
                    axis,
                    strategy_id,
                    strategy_version_id,
                    to_status,
                    actor,
                    "INCOMPATIBLE_ROLLBACK_TARGET_SCOPE",
                    "rollback target does not allow the requested environment/mode",
                    moment,
                    now,
                    current_status=current,
                )
            target_status = await self._store.current_status(
                axis, strategy_id, rollback_target_version_id, as_of=moment
            )
            if target_status not in {"APPROVED_FOR_PRODUCTION", "ACTIVE"}:
                return await self._reject(
                    axis,
                    strategy_id,
                    strategy_version_id,
                    to_status,
                    actor,
                    "ROLLBACK_TARGET_NOT_GOVERNED_READY",
                    "rollback target must be approved for production or active on this lifecycle axis",
                    moment,
                    now,
                    current_status=current,
                )
        if axis is not LifecycleAxis.STRATEGY_AVAILABILITY:
            assert version is not None
            if (
                environment not in version.environments
                or operating_mode not in version.operating_modes
            ):
                return await self._reject(
                    axis,
                    strategy_id,
                    strategy_version_id,
                    to_status,
                    actor,
                    "INCOMPATIBLE_ENVIRONMENT_MODE",
                    "transition environment/mode is not declared by the immutable version",
                    moment,
                    now,
                    current_status=current,
                )
        elif environment is not None or operating_mode is not None:
            return await self._reject(
                axis,
                strategy_id,
                strategy_version_id,
                to_status,
                actor,
                "AVAILABILITY_SCOPE_MISMATCH",
                "strategy availability is identity-level and has no environment/mode axis",
                moment,
                now,
                current_status=current,
            )

        ref_failure = await self._transition_reference_failure(
            axis,
            to_status,
            subject_id=subject_id,
            decision_reference=decision_reference,
            evidence_references=evidence_references,
            environment=environment,
            operating_mode=operating_mode,
            at=moment,
        )
        if ref_failure is not None:
            return await self._reject(
                axis,
                strategy_id,
                strategy_version_id,
                to_status,
                actor,
                ref_failure,
                ref_failure.lower().replace("_", " "),
                moment,
                now,
                current_status=current,
            )
        history = await self._store.history(axis, strategy_id, strategy_version_id)
        resolves_suspension_event_id = None
        if (
            axis is LifecycleAxis.STRATEGY_AVAILABILITY
            and current == StrategyAvailability.SUSPENDED.value
            and to_status == StrategyAvailability.ACTIVE.value
        ):
            if not history or history[-1].to_status != StrategyAvailability.SUSPENDED.value:
                return await self._reject(
                    axis,
                    strategy_id,
                    strategy_version_id,
                    to_status,
                    actor,
                    "SUSPENSION_CAUSE_EVENT_MISSING",
                    "reactivation cannot resolve an unavailable suspension event",
                    moment,
                    now,
                    current_status=current,
                )
            resolves_suspension_event_id = history[-1].event_id
        if history and moment <= history[-1].effective_at:
            return await self._reject(
                axis,
                strategy_id,
                strategy_version_id,
                to_status,
                actor,
                "OUT_OF_ORDER_EFFECTIVE_TIME",
                "effective time predates the latest event",
                moment,
                now,
                current_status=current,
            )
        event = _make_event(
            axis=axis,
            strategy_id=strategy_id,
            strategy_version_id=strategy_version_id,
            from_status=current,
            to_status=to_status,
            actor=actor,
            reason=reason,
            decision_reference=decision_reference,
            evidence_references=evidence_references,
            effective_at=moment,
            recorded_at=now,
            rollback_target_version_id=rollback_target_version_id,
            resolves_suspension_event_id=resolves_suspension_event_id,
            environment=environment,
            operating_mode=operating_mode,
        )
        audit = _audit_for(event, accepted=True)
        appended = await self._store.append_transition(
            event, audit, expected_from_status=current
        )
        if not appended:
            rejected = _audit_for(
                event, accepted=False, result="CONCURRENT_STATE_CHANGE"
            )
            await self._store.append_rejected_transition(rejected)
            return TransitionResult(
                False, "CONCURRENT_STATE_CHANGE", current, None, rejected
            )
        return TransitionResult(True, "ACCEPTED", to_status, event, audit)

    async def resolve_version(
        self,
        *,
        strategy_id: UUID,
        strategy_version_id: UUID | None = None,
        semantic_version: str | None = None,
        as_of: datetime | None = None,
    ) -> ResolvedStrategyVersion:
        if (strategy_version_id is None) == (semantic_version is None):
            raise StrategyRegistryError(
                "provide exactly one of strategy_version_id or semantic_version."
            )
        if semantic_version is not None:
            validate_semantic_version(semantic_version)
            version = await self._store.get_version_by_semantic_version(
                strategy_id, semantic_version
            )
        else:
            version = await self._store.get_version(strategy_version_id)  # type: ignore[arg-type]
        strategy = await self._store.get_strategy(strategy_id)
        if strategy is None or version is None or version.strategy_id != strategy_id:
            raise StrategyRegistryError(
                "exact strategy version resolution failed.",
                code="EXACT_VERSION_NOT_FOUND",
            )
        moment = _aware_utc("as_of", as_of or self._clock())
        availability = await self._store.current_status(
            LifecycleAxis.STRATEGY_AVAILABILITY, strategy_id, None, as_of=moment
        )
        c021_status = await self._store.current_status(
            LifecycleAxis.C021_VERSION,
            strategy_id,
            version.strategy_version_id,
            as_of=moment,
        )
        artifact_status = await self._store.current_status(
            LifecycleAxis.ARTIFACT_VERSION,
            strategy_id,
            version.strategy_version_id,
            as_of=moment,
        )
        if availability is None or c021_status is None or artifact_status is None:
            raise StrategyRegistryError(
                "exact lifecycle history is incomplete.",
                code="LIFECYCLE_HISTORY_INCOMPLETE",
            )
        try:
            return ResolvedStrategyVersion(
                strategy,
                version,
                StrategyAvailability(availability),
                StrategyLifecycle(c021_status),
                ArtifactVersionLifecycle(artifact_status),
            )
        except ValueError:
            raise StrategyRegistryError(
                "stored lifecycle state is unsupported."
            ) from None

    async def _transition_reference_failure(
        self,
        axis: LifecycleAxis,
        to_status: str,
        *,
        subject_id: UUID | None,
        decision_reference: VersionReference,
        evidence_references: tuple[VersionReference, ...],
        environment: DeploymentEnvironment | None,
        operating_mode: OperatingMode | None,
        at: datetime,
    ) -> str | None:
        if self._reference_resolver is None:
            return "REFERENCE_RESOLVER_UNAVAILABLE"
        if decision_reference.artifact_type != "C-057":
            return "GOVERNANCE_DECISION_REFERENCE_REQUIRED"
        decision = await self._reference_resolver.resolve(decision_reference, at=at)
        expected_decision_status = "REJECTED" if to_status == "REJECTED" else "APPROVED"
        if (
            decision is None
            or decision.reference != decision_reference
            or decision.subject_id != subject_id
            or decision.status != expected_decision_status
            or (decision.expires_at is not None and decision.expires_at <= at)
            or (
                axis is LifecycleAxis.STRATEGY_AVAILABILITY
                and (
                    decision.environment is not None
                    or decision.operating_mode is not None
                )
            )
            or (
                decision.environment is not None
                and decision.environment is not environment
            )
            or (
                decision.operating_mode is not None
                and decision.operating_mode is not operating_mode
            )
        ):
            return "GOVERNANCE_DECISION_UNRESOLVED_OR_INVALID"
        if not evidence_references:
            return "LIFECYCLE_EVIDENCE_REQUIRED"
        resolved_evidence: list[ResolvedLifecycleReference] = []
        for reference in evidence_references:
            resolved = await self._reference_resolver.resolve(reference, at=at)
            if (
                resolved is None
                or resolved.reference != reference
                or (subject_id is not None and resolved.subject_id != subject_id)
                or _reference_is_unusable(resolved, at=at)
            ):
                return "LIFECYCLE_EVIDENCE_UNRESOLVED_OR_EXPIRED"
            if (
                resolved.environment is not None
                and resolved.environment is not environment
            ) or (
                resolved.operating_mode is not None
                and resolved.operating_mode is not operating_mode
            ):
                return "INCOMPATIBLE_REFERENCE_SCOPE"
            resolved_evidence.append(resolved)
        if to_status == "VALIDATED" and not any(
            item.reference.artifact_type == "C-028" and item.status == "PASSED"
            for item in resolved_evidence
        ):
            return "PASSED_VALIDATION_EVIDENCE_REQUIRED"
        if axis is not LifecycleAxis.STRATEGY_AVAILABILITY and (
            to_status.startswith("APPROVED_FOR_") or to_status == "ACTIVE"
        ):
            if not any(
                item.reference.artifact_type == "C-028" and item.status == "PASSED"
                for item in resolved_evidence
            ):
                return "PASSED_VALIDATION_EVIDENCE_REQUIRED"
        return None

    async def _verify_governance_reference(
        self,
        reference: VersionReference,
        *,
        subject_id: UUID,
        at: datetime,
        expected_status: str,
    ) -> None:
        if self._reference_resolver is None:
            raise StrategyRegistryError(
                "lifecycle reference resolver is unavailable.",
                code="REFERENCE_RESOLVER_UNAVAILABLE",
            )
        resolved = await self._reference_resolver.resolve(reference, at=at)
        if (
            reference.artifact_type != "C-057"
            or resolved is None
            or resolved.reference != reference
            or resolved.subject_id != subject_id
            or resolved.status != expected_status
            or (resolved.expires_at is not None and resolved.expires_at <= at)
        ):
            raise StrategyRegistryError(
                "governance decision reference is unresolved or invalid."
            )

    async def _verify_evidence_references(
        self,
        references: tuple[VersionReference, ...],
        *,
        subject_id: UUID | None,
        at: datetime,
    ) -> None:
        if not references:
            raise StrategyRegistryError(
                "registration evidence references are required."
            )
        if self._reference_resolver is None:
            raise StrategyRegistryError(
                "lifecycle reference resolver is unavailable.",
                code="REFERENCE_RESOLVER_UNAVAILABLE",
            )
        for reference in references:
            resolved = await self._reference_resolver.resolve(reference, at=at)
            if (
                resolved is None
                or resolved.reference != reference
                or (subject_id is not None and resolved.subject_id != subject_id)
                or _reference_is_unusable(resolved, at=at)
            ):
                raise StrategyRegistryError(
                    "registration evidence is unresolved or expired."
                )

    async def _reject(
        self,
        axis: LifecycleAxis,
        strategy_id: UUID,
        strategy_version_id: UUID | None,
        to_status: str,
        actor: str,
        code: str,
        reason: str,
        effective_at: datetime,
        recorded_at: datetime,
        *,
        current_status: str | None = None,
    ) -> TransitionResult:
        subject_id = (
            strategy_id
            if axis is LifecycleAxis.STRATEGY_AVAILABILITY
            else strategy_version_id
        )
        event_id = uuid4()
        audit = AuditEvent(
            event_type=AuditEventType.CONFIGURATION_CHANGED,
            actor=actor,
            action=f"strategy_registry.{axis.value.lower()}.rejected",
            source="trading-platform.strategy-registry",
            result=code,
            correlation_id=str(event_id),
            trace_id=str(event_id),
            audit_id=event_id,
            occurred_at=min(effective_at, recorded_at),
            recorded_at=recorded_at,
            reason=reason,
            subject_type=axis.value,
            subject_id=str(subject_id or strategy_id),
        )
        await self._store.append_rejected_transition(audit)
        return TransitionResult(False, code, current_status, None, audit)


def _transitions_for(axis: LifecycleAxis, current: str) -> frozenset[str]:
    if axis is LifecycleAxis.STRATEGY_AVAILABILITY:
        return _AVAILABILITY_TRANSITIONS.get(current, frozenset())
    if axis is LifecycleAxis.C021_VERSION:
        return _C021_TRANSITIONS.get(current, frozenset())
    if axis is LifecycleAxis.ARTIFACT_VERSION:
        return _ARTIFACT_TRANSITIONS.get(current, frozenset())
    return frozenset()


def _make_event(
    *,
    axis: LifecycleAxis,
    strategy_id: UUID,
    strategy_version_id: UUID | None,
    from_status: str | None,
    to_status: str,
    actor: str,
    reason: str,
    decision_reference: VersionReference,
    evidence_references: tuple[VersionReference, ...],
    effective_at: datetime,
    recorded_at: datetime,
    rollback_target_version_id: UUID | None = None,
    resolves_suspension_event_id: UUID | None = None,
    environment: DeploymentEnvironment | None = None,
    operating_mode: OperatingMode | None = None,
) -> RegistryLifecycleEvent:
    event_id = uuid4()
    return RegistryLifecycleEvent(
        axis=axis,
        strategy_id=strategy_id,
        strategy_version_id=strategy_version_id,
        from_status=from_status,
        to_status=to_status,
        actor=actor,
        reason=reason,
        decision_reference=decision_reference,
        evidence_references=evidence_references,
        effective_at=effective_at,
        recorded_at=recorded_at,
        rollback_target_version_id=rollback_target_version_id,
        resolves_suspension_event_id=resolves_suspension_event_id,
        environment=environment,
        operating_mode=operating_mode,
        event_id=event_id,
        audit_id=event_id,
    )


def _audit_for(
    event: RegistryLifecycleEvent,
    *,
    accepted: bool,
    result: str | None = None,
    subject_id: UUID | None = None,
) -> AuditEvent:
    return AuditEvent(
        event_type=AuditEventType.CONFIGURATION_CHANGED,
        actor=event.actor,
        action=f"strategy_registry.{event.axis.value.lower()}.{event.to_status.lower()}",
        source="trading-platform.strategy-registry",
        result=result or ("ACCEPTED" if accepted else "REJECTED"),
        correlation_id=str(event.event_id),
        trace_id=str(event.event_id),
        audit_id=event.audit_id,
        occurred_at=event.effective_at,
        recorded_at=event.recorded_at,
        reason=event.reason,
        subject_type=event.axis.value,
        subject_id=str(subject_id or event.strategy_version_id or event.strategy_id),
    )


_UNUSABLE_EVIDENCE_STATUSES = frozenset(
    {
        "BLOCKED",
        "EXPIRED",
        "FAILED",
        "INCOMPLETE",
        "INCONCLUSIVE",
        "INVALID",
        "MISSING",
        "NOT_RUN",
        "PENDING",
        "REJECTED",
        "REVOKED",
        "RUNNING",
        "STALE",
        "UNKNOWN",
        "UNAVAILABLE",
    }
)


def _reference_is_unusable(
    reference: ResolvedLifecycleReference, *, at: datetime
) -> bool:
    return reference.status in _UNUSABLE_EVIDENCE_STATUSES or (
        reference.expires_at is not None and reference.expires_at <= at
    )


def _required_text(name: str, value: object, *, limit: int = 512) -> str:
    if type(value) is not str or not value.strip() or value != value.strip():
        raise StrategyRegistryError(f"{name} must be nonblank canonical text.")
    if len(value.encode("utf-8")) > limit:
        raise StrategyRegistryError(f"{name} exceeds its size limit.")
    return value


def _aware_utc(name: str, value: datetime) -> datetime:
    if (
        not isinstance(value, datetime)
        or value.tzinfo is None
        or value.utcoffset() is None
    ):
        raise StrategyRegistryError(f"{name} must be timezone-aware.")
    return value.astimezone(UTC)


__all__ = [
    "ArtifactVersionLifecycle",
    "LifecycleAxis",
    "LifecycleReferenceResolver",
    "RegistryLifecycleEvent",
    "ResolvedLifecycleReference",
    "ResolvedStrategyVersion",
    "StrategyAvailability",
    "StrategyRegistry",
    "StrategyRegistryError",
    "StrategyRegistryStore",
    "TransitionResult",
    "semantic_version_is_greater",
    "strategy_version_content_sha256",
    "validate_semantic_version",
]
