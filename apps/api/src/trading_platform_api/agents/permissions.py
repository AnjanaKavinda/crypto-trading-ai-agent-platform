from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Protocol
from uuid import UUID, uuid4

from trading_platform_api.agents.contracts import (
    AgentDefinition,
    AgentPermissionProfile,
    AgentToolAccess,
)
from trading_platform_api.risk import ContractReference

if TYPE_CHECKING:
    from trading_platform_api.audit.models import AuditEvent


class AgentPermissionEnforcementError(ValueError):
    """Raised when a permission decision cannot be safely audited."""


class AuditEventWriter(Protocol):
    async def append(self, event: AuditEvent) -> None: ...


class PermissionOutcome(StrEnum):
    ALLOW = "ALLOW"
    DENY = "DENY"


@dataclass(frozen=True, slots=True)
class AgentPermissionDecision:
    """Auditable result of one exact-scope C-061/C-063/C-064/C-098 check."""

    decision_id: UUID
    outcome: PermissionOutcome
    reason_code: str
    agent_id: str
    agent_version: str
    profile_id: UUID
    access_id: UUID
    policy_id: UUID
    policy_version: str
    action: str
    tool: str
    resource: str
    environment: str
    mode: str
    evaluated_at: datetime
    audit_event: AuditEvent


def _utc_now(name: str, value: object) -> datetime:
    if (
        not isinstance(value, datetime)
        or value.tzinfo is None
        or value.utcoffset() is None
    ):
        raise AgentPermissionEnforcementError(f"{name} must be timezone-aware.")
    return value.astimezone(UTC)


def _permission_reason(
    *,
    definition: AgentDefinition,
    profile: AgentPermissionProfile,
    access: AgentToolAccess,
    action: str,
    tool: str,
    resource: str,
    environment: str,
    mode: str,
    now: datetime,
) -> str:
    policy = profile.policy
    if (profile.agent_id, profile.agent_version, profile.role) != (
        definition.agent_id,
        definition.agent_version,
        definition.role,
    ):
        return "AGENT_DEFINITION_MISMATCH"
    if mode not in definition.allowed_modes or mode != profile.mode:
        return "MODE_NOT_ALLOWED"
    if environment != profile.environment:
        return "ENVIRONMENT_NOT_ALLOWED"
    if access.profile_id != profile.profile_id:
        return "ACCESS_PROFILE_MISMATCH"
    if access.access_id not in profile.tool_access_ids:
        return "ACCESS_NOT_IN_PROFILE"
    if access.revoked_at is not None and now >= access.revoked_at:
        return "ACCESS_REVOKED"
    if profile.revoked_at is not None and now >= profile.revoked_at:
        return "PROFILE_REVOKED"
    if not profile.valid_from <= now < profile.valid_until:
        return "PROFILE_INACTIVE"
    if not policy.effective_at <= now < policy.expires_at:
        return "POLICY_INACTIVE"
    if not access.valid_from <= now < access.valid_until:
        return "ACCESS_INACTIVE"
    if (
        profile.role not in policy.agent_roles
        or (
            policy.agent_identities
            and f"{definition.agent_id}@{definition.agent_version}"
            not in policy.agent_identities
        )
    ):
        return "AGENT_OUTSIDE_POLICY_CEILING"
    if environment not in policy.environments or mode not in policy.modes:
        return "SCOPE_OUTSIDE_POLICY_CEILING"
    if (action, tool, resource, environment, mode) != (
        access.action,
        access.tool,
        access.resource,
        access.environment,
        access.mode,
    ):
        return "REQUEST_OUTSIDE_ACCESS_SCOPE"
    if tool not in definition.allowed_tools:
        return "TOOL_NOT_DECLARED_BY_AGENT"
    grant = next(
        (item for item in policy.grants if item.grant_id == access.grant_id), None
    )
    if grant is None:
        return "POLICY_GRANT_NOT_FOUND"
    if (
        grant.action != access.action
        or grant.tool != access.tool
        or grant.resource != access.resource
        or access.environment not in grant.environments
        or access.mode not in grant.modes
        or access.valid_from < grant.valid_from
        or access.valid_until > grant.valid_until
    ):
        return "ACCESS_EXCEEDS_POLICY_GRANT"
    if not policy.default_deny:
        return "POLICY_NOT_DEFAULT_DENY"
    return "PERMISSION_GRANTED"


async def enforce_agent_tool_access(
    *,
    definition: AgentDefinition,
    profile: AgentPermissionProfile,
    access: AgentToolAccess,
    action: str,
    tool: str,
    resource: str,
    environment: str,
    mode: str,
    now: datetime,
    correlation_id: str,
    trace_id: str,
    audit_store: AuditEventWriter,
) -> AgentPermissionDecision:
    """Evaluate exact scope and persist the C-060 decision before returning it."""

    if not isinstance(definition, AgentDefinition):
        raise AgentPermissionEnforcementError("validated C-061 is required.")
    if not isinstance(profile, AgentPermissionProfile):
        raise AgentPermissionEnforcementError("validated C-063 is required.")
    if not isinstance(access, AgentToolAccess):
        raise AgentPermissionEnforcementError("validated C-064 is required.")
    from trading_platform_api.audit.models import AuditEvent, AuditEventType

    instant = _utc_now("now", now)
    for name, value in (
        ("action", action),
        ("tool", tool),
        ("resource", resource),
        ("environment", environment),
        ("mode", mode),
        ("correlation_id", correlation_id),
        ("trace_id", trace_id),
    ):
        if not isinstance(value, str) or not value.strip() or value != value.strip():
            raise AgentPermissionEnforcementError(f"{name} is invalid.")

    reason = _permission_reason(
        definition=definition,
        profile=profile,
        access=access,
        action=action,
        tool=tool,
        resource=resource,
        environment=environment,
        mode=mode,
        now=instant,
    )
    outcome = (
        PermissionOutcome.ALLOW
        if reason == "PERMISSION_GRANTED"
        else PermissionOutcome.DENY
    )
    decision_id = uuid4()
    event = AuditEvent(
        event_type=AuditEventType.SECURITY_EVENT,
        actor=f"agent:{definition.agent_id}@{definition.agent_version}",
        action="AGENT_PERMISSION_DECISION",
        source="agent-permission-enforcement",
        result=outcome.value,
        correlation_id=correlation_id,
        trace_id=trace_id,
        occurred_at=instant,
        recorded_at=instant,
        reason=(
            f"{reason}; policy={profile.policy.policy_id}; "
            f"version={profile.policy.version.version}"
        ),
        subject_type="agent-permission-decision",
        subject_id=str(decision_id),
    )
    try:
        await audit_store.append(event)
    except Exception:
        raise AgentPermissionEnforcementError(
            "permission decision could not be audited; access is denied."
        ) from None
    return AgentPermissionDecision(
        decision_id=decision_id,
        outcome=outcome,
        reason_code=reason,
        agent_id=definition.agent_id,
        agent_version=definition.agent_version,
        profile_id=profile.profile_id,
        access_id=access.access_id,
        policy_id=profile.policy.policy_id,
        policy_version=profile.policy.version.version,
        action=action,
        tool=tool,
        resource=resource,
        environment=environment,
        mode=mode,
        evaluated_at=instant,
        audit_event=event,
    )


async def revoke_agent_tool_access(
    access: AgentToolAccess,
    *,
    revoked_at: datetime,
    actor: str,
    correlation_id: str,
    trace_id: str,
    audit_store: AuditEventWriter,
) -> AgentToolAccess:
    """Append a revocation audit event, then return an immutable revoked grant."""

    if not isinstance(access, AgentToolAccess) or access.revoked_at is not None:
        raise AgentPermissionEnforcementError("active C-064 access is required.")
    from trading_platform_api.audit.models import AuditEvent, AuditEventType

    instant = _utc_now("revoked_at", revoked_at)
    if not access.valid_from <= instant < access.valid_until:
        raise AgentPermissionEnforcementError(
            "revocation time is outside the access window."
        )
    event = AuditEvent(
        event_type=AuditEventType.SECURITY_EVENT,
        actor=actor,
        action="AGENT_TOOL_ACCESS_REVOKED",
        source="agent-permission-enforcement",
        result="REVOKED",
        correlation_id=correlation_id,
        trace_id=trace_id,
        occurred_at=instant,
        recorded_at=instant,
        reason="Explicit permission revocation.",
        subject_type="agent-tool-access",
        subject_id=str(access.access_id),
    )
    try:
        await audit_store.append(event)
    except Exception:
        raise AgentPermissionEnforcementError(
            "revocation could not be audited; grant state was not changed."
        ) from None
    reference = ContractReference(
        contract_id="C-060",
        entity_id=event.audit_id,
        schema_version=event.schema_version,
    )
    return replace(
        access,
        revision=access.revision + 1,
        revoked_at=instant,
        revocation_audit_ref=reference,
    )


async def revoke_agent_permission_profile(
    profile: AgentPermissionProfile,
    *,
    revoked_at: datetime,
    actor: str,
    correlation_id: str,
    trace_id: str,
    audit_store: AuditEventWriter,
) -> AgentPermissionProfile:
    """Revoke the whole profile, with the C-060 event persisted first."""

    if (
        not isinstance(profile, AgentPermissionProfile)
        or profile.revoked_at is not None
    ):
        raise AgentPermissionEnforcementError("active C-063 profile is required.")
    from trading_platform_api.audit.models import AuditEvent, AuditEventType

    instant = _utc_now("revoked_at", revoked_at)
    if not profile.valid_from <= instant < profile.valid_until:
        raise AgentPermissionEnforcementError(
            "revocation time is outside the profile window."
        )
    event = AuditEvent(
        event_type=AuditEventType.SECURITY_EVENT,
        actor=actor,
        action="AGENT_PERMISSION_PROFILE_REVOKED",
        source="agent-permission-enforcement",
        result="REVOKED",
        correlation_id=correlation_id,
        trace_id=trace_id,
        occurred_at=instant,
        recorded_at=instant,
        reason="Explicit permission profile revocation.",
        subject_type="agent-permission-profile",
        subject_id=str(profile.profile_id),
    )
    try:
        await audit_store.append(event)
    except Exception:
        raise AgentPermissionEnforcementError(
            "revocation could not be audited; profile state was not changed."
        ) from None
    reference = ContractReference(
        contract_id="C-060",
        entity_id=event.audit_id,
        schema_version=event.schema_version,
    )
    return replace(
        profile,
        revision=profile.revision + 1,
        revoked_at=instant,
        revocation_audit_ref=reference,
    )
