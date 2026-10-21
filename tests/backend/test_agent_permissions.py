from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from trading_platform_api.agents import (
    PERSONAL_SPOT_RESEARCH_AGENT,
    AgentContractError,
    AgentDefinition,
    AgentPermissionEnforcementError,
    AgentPermissionProfile,
    AgentToolAccess,
    PermissionOutcome,
    enforce_agent_tool_access,
    revoke_agent_permission_profile,
    revoke_agent_tool_access,
)
from trading_platform_api.audit import AuditEvent
from trading_platform_api.risk import VersionReference
from trading_platform_api.safety import AgentPermissionPolicy, PermissionGrant

NOW = datetime(2026, 10, 21, 12, 0, tzinfo=UTC)
SHA = "a" * 64
PROHIBITED = (
    "HUMAN_TRADE_APPROVAL",
    "POLICY_OVERRIDE",
    "WITHDRAW_FUNDS",
    "TRANSFER_FUNDS",
    "UNRESTRICTED_CREDENTIAL_ACCESS",
    "ARBITRARY_TOOL_EXECUTION",
    "DIRECT_AI_ORDER_SUBMISSION",
)


def definition() -> AgentDefinition:
    return AgentDefinition(
        agent_id="test-spot-agent",
        agent_version="1",
        role="spot-research-analyst",
        purpose="Read validated Spot research data.",
        allowed_inputs=("C-002",),
        allowed_outputs=("C-006",),
        allowed_tools=("spot-data-reader",),
        allowed_modes=("PERSONAL_SPOT_RESEARCH",),
        dependencies=("validated-spot-profile",),
        authority_boundaries=("analysis-only", "no-execution"),
    )


def permission_policy(*, grants: tuple[PermissionGrant, ...] | None = None):
    grant = PermissionGrant(
        grant_id="spot-read-grant",
        action="READ",
        tool="spot-data-reader",
        resource="validated-spot-market-data",
        environments=("local",),
        modes=("PERSONAL_SPOT_RESEARCH",),
        valid_from=NOW - timedelta(minutes=10),
        valid_until=NOW + timedelta(hours=1),
        constraints_sha256=SHA,
    )
    return AgentPermissionPolicy(
        policy_id=uuid4(),
        name="Personal Spot research permission ceiling",
        revision=1,
        version=VersionReference("agent-permission-policy", "1", SHA),
        agent_roles=("spot-research-analyst",),
        agent_identities=("test-spot-agent@1",),
        grants=(grant,) if grants is None else grants,
        denied_capabilities=PROHIBITED,
        default_deny=True,
        environments=("local",),
        modes=("PERSONAL_SPOT_RESEARCH",),
        effective_at=NOW - timedelta(minutes=10),
        expires_at=NOW + timedelta(hours=1),
        created_at=NOW - timedelta(hours=1),
        issuer_ref="security-governance",
        configuration_version=VersionReference("configuration", "1", SHA),
        content_sha256=SHA,
    )


def profile(
    *,
    policy: AgentPermissionPolicy | None = None,
    access_ids: tuple | None = None,
    agent_id: str = "test-spot-agent",
    agent_version: str = "1",
    role: str = "spot-research-analyst",
    mode: str = "PERSONAL_SPOT_RESEARCH",
) -> AgentPermissionProfile:
    return AgentPermissionProfile(
        profile_id=uuid4(),
        agent_id=agent_id,
        agent_version=agent_version,
        role=role,
        environment="local",
        mode=mode,
        policy=policy or permission_policy(),
        tool_access_ids=(uuid4(),) if access_ids is None else access_ids,
        valid_from=NOW - timedelta(minutes=5),
        valid_until=NOW + timedelta(minutes=30),
    )


def access(
    selected_profile: AgentPermissionProfile,
    *,
    grant_id: str = "spot-read-grant",
    tool: str = "spot-data-reader",
    resource: str = "validated-spot-market-data",
    action: str = "READ",
) -> AgentToolAccess:
    return AgentToolAccess(
        access_id=selected_profile.tool_access_ids[0],
        profile_id=selected_profile.profile_id,
        grant_id=grant_id,
        tool=tool,
        resource=resource,
        action=action,
        environment="local",
        mode="PERSONAL_SPOT_RESEARCH",
        valid_from=NOW - timedelta(minutes=5),
        valid_until=NOW + timedelta(minutes=20),
    )


class MemoryAuditStore:
    def __init__(self) -> None:
        self.events: list[AuditEvent] = []

    async def append(self, event: AuditEvent) -> None:
        self.events.append(event)


class FailingAuditStore:
    async def append(self, event: AuditEvent) -> None:
        raise RuntimeError("audit unavailable")


def authorize(
    selected_profile: AgentPermissionProfile,
    selected_access: AgentToolAccess,
    audit_store: MemoryAuditStore | FailingAuditStore,
    **overrides: object,
):
    values: dict[str, object] = {
        "definition": definition(),
        "profile": selected_profile,
        "access": selected_access,
        "action": "READ",
        "tool": "spot-data-reader",
        "resource": "validated-spot-market-data",
        "environment": "local",
        "mode": "PERSONAL_SPOT_RESEARCH",
        "now": NOW,
        "correlation_id": "correlation-1",
        "trace_id": "trace-1",
        "audit_store": audit_store,
    }
    values.update(overrides)
    return asyncio.run(enforce_agent_tool_access(**values))  # type: ignore[arg-type]


def test_exact_tool_access_is_allowed_only_after_audit_append() -> None:
    selected_profile = profile()
    selected_access = access(selected_profile)
    audit = MemoryAuditStore()

    decision = authorize(selected_profile, selected_access, audit)

    assert decision.outcome is PermissionOutcome.ALLOW
    assert decision.reason_code == "PERMISSION_GRANTED"
    assert decision.audit_event.result == "ALLOW"
    assert audit.events == [decision.audit_event]


@pytest.mark.parametrize(
    ("request_change", "expected_reason"),
    [
        ({"tool": "other-tool"}, "REQUEST_OUTSIDE_ACCESS_SCOPE"),
        ({"resource": "other-resource"}, "REQUEST_OUTSIDE_ACCESS_SCOPE"),
        ({"mode": "LIVE"}, "MODE_NOT_ALLOWED"),
        ({"environment": "cloud"}, "ENVIRONMENT_NOT_ALLOWED"),
    ],
)
def test_mismatched_tool_resource_mode_or_environment_is_denied_and_audited(
    request_change: dict[str, str], expected_reason: str
) -> None:
    selected_profile = profile()
    audit = MemoryAuditStore()

    decision = authorize(
        selected_profile, access(selected_profile), audit, **request_change
    )

    assert decision.outcome is PermissionOutcome.DENY
    assert decision.reason_code == expected_reason
    assert audit.events[0].result == "DENY"


def test_unlisted_or_revoked_access_is_denied() -> None:
    selected_profile = profile()
    not_listed = AgentToolAccess(
        access_id=uuid4(),
        profile_id=selected_profile.profile_id,
        grant_id="spot-read-grant",
        tool="spot-data-reader",
        resource="validated-spot-market-data",
        action="READ",
        environment="local",
        mode="PERSONAL_SPOT_RESEARCH",
        valid_from=NOW - timedelta(minutes=5),
        valid_until=NOW + timedelta(minutes=20),
    )
    decision = authorize(selected_profile, not_listed, MemoryAuditStore())
    assert decision.reason_code == "ACCESS_NOT_IN_PROFILE"

    audit = MemoryAuditStore()
    revoked = asyncio.run(
        revoke_agent_tool_access(
            access(selected_profile),
            revoked_at=NOW,
            actor="security-governance",
            correlation_id="correlation-2",
            trace_id="trace-2",
            audit_store=audit,
        )
    )
    assert revoked.revoked_at == NOW
    assert revoked.revision == 2
    assert revoked.revocation_audit_ref is not None
    denied = authorize(selected_profile, revoked, MemoryAuditStore())
    assert denied.reason_code == "ACCESS_REVOKED"


def test_revoked_profile_denies_and_audit_failure_never_allows() -> None:
    selected_profile = profile()
    audit = MemoryAuditStore()
    revoked_profile = asyncio.run(
        revoke_agent_permission_profile(
            selected_profile,
            revoked_at=NOW,
            actor="security-governance",
            correlation_id="correlation-3",
            trace_id="trace-3",
            audit_store=audit,
        )
    )
    assert selected_profile.revision == 1
    assert revoked_profile.revision == 2
    denied = authorize(
        revoked_profile,
        access(selected_profile),
        MemoryAuditStore(),
    )
    assert denied.reason_code == "PROFILE_REVOKED"
    with pytest.raises(AgentPermissionEnforcementError, match="access is denied"):
        authorize(
            selected_profile,
            access(selected_profile),
            FailingAuditStore(),
        )


def test_policy_grant_mismatch_and_empty_personal_profile_deny_by_default() -> None:
    selected_profile = profile()
    audit = MemoryAuditStore()
    decision = authorize(
        selected_profile,
        access(selected_profile, grant_id="unknown-grant"),
        audit,
    )
    assert decision.reason_code == "POLICY_GRANT_NOT_FOUND"

    empty_policy = permission_policy(grants=())
    no_access_profile = profile(policy=empty_policy, access_ids=())
    assert no_access_profile.tool_access_ids == ()


def test_registered_personal_spot_agent_cannot_receive_undeclared_tool_access() -> None:
    ceiling = permission_policy(grants=())
    ceiling = replace(
        ceiling,
        agent_roles=(PERSONAL_SPOT_RESEARCH_AGENT.role,),
        agent_identities=(
            f"{PERSONAL_SPOT_RESEARCH_AGENT.agent_id}@"
            f"{PERSONAL_SPOT_RESEARCH_AGENT.agent_version}",
        ),
    )
    access_id = uuid4()
    selected_profile = profile(
        policy=ceiling,
        access_ids=(access_id,),
        agent_id=PERSONAL_SPOT_RESEARCH_AGENT.agent_id,
        agent_version=PERSONAL_SPOT_RESEARCH_AGENT.agent_version,
        role=PERSONAL_SPOT_RESEARCH_AGENT.role,
    )
    attempted_access = access(selected_profile)

    decision = authorize(
        selected_profile,
        attempted_access,
        MemoryAuditStore(),
        definition=PERSONAL_SPOT_RESEARCH_AGENT,
    )

    assert decision.outcome is PermissionOutcome.DENY
    assert decision.reason_code == "TOOL_NOT_DECLARED_BY_AGENT"


def test_profile_and_tool_access_reject_out_of_ceiling_and_wildcards() -> None:
    selected_policy = permission_policy()
    with pytest.raises(AgentContractError, match="mode exceeds"):
        profile(policy=selected_policy, mode="LIVE")
    with pytest.raises(AgentContractError, match="exact scope"):
        AgentToolAccess(
            access_id=uuid4(),
            profile_id=uuid4(),
            grant_id="spot-read-grant",
            tool="*",
            resource="validated-spot-market-data",
            action="READ",
            environment="local",
            mode="PERSONAL_SPOT_RESEARCH",
            valid_from=NOW,
            valid_until=NOW + timedelta(minutes=5),
        )
