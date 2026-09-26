from __future__ import annotations

from dataclasses import FrozenInstanceError, fields, replace
from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import get_type_hints
from uuid import uuid4

import pytest
import trading_platform_api.safety as safety_package
from trading_platform_api.audit import AuditEvent, AuditEventType
from trading_platform_api.audit.models import AUDIT_SCHEMA_VERSION
from trading_platform_api.execution import ExecutionIntent
from trading_platform_api.health import TradingReadinessStatus as HealthReadinessStatus
from trading_platform_api.risk import ContractReference, VersionReference
from trading_platform_api.safety import (
    AgentPermissionPolicy,
    CircuitBreakerSnapshot,
    CircuitBreakerState,
    ComponentHealthStatus,
    EvidenceReference,
    FailureClassification,
    FailureEvent,
    FailureOperationKind,
    IncidentStatus,
    InvestigationStatus,
    KillSwitchSnapshot,
    KillSwitchState,
    OperationalSafetyState,
    PermissionGrant,
    PolicyRule,
    PromptInjectionAssessment,
    PromptInjectionVerdict,
    ReadinessComponent,
    RecoveryAction,
    RecoveryActionType,
    RecoveryStatus,
    SafetyContextReference,
    SafetyContractError,
    SafetyDecision,
    SafetyDecisionType,
    SafetyIncidentReport,
    SafetyPolicy,
    SecurityEvent,
    SecurityEventType,
    SecuritySeverity,
    TradingReadinessState,
    TradingReadinessStatus,
)

NOW = datetime(2026, 9, 26, 9, 0, tzinfo=UTC)
SHA_A = "a" * 64
SHA_B = "b" * 64
SHA_C = "c" * 64


def version(component: str = "safety") -> VersionReference:
    return VersionReference(component=component, version="1.0.0", content_sha256=SHA_A)


def ref(contract_id: str) -> ContractReference:
    return ContractReference(
        contract_id=contract_id,
        entity_id=uuid4(),
        schema_version="1",
        content_sha256=SHA_A,
        valid_until=NOW + timedelta(hours=1),
    )


def evidence(evidence_type: str = "SYNTHETIC_TEST_EVIDENCE") -> EvidenceReference:
    return EvidenceReference(
        evidence_type=evidence_type,
        evidence_id=uuid4(),
        source="synthetic-test",
        source_version="1",
        content_sha256=SHA_A,
    )


def component(**overrides: object) -> ReadinessComponent:
    values: dict[str, object] = {
        "component_id": "audit",
        "status": ComponentHealthStatus.HEALTHY,
        "evidence": evidence(),
        "observed_at": NOW,
        "as_of": NOW - timedelta(seconds=1),
        "freshness_seconds": Decimal("30"),
        "current": True,
        "reason_codes": (),
    }
    values.update(overrides)
    return ReadinessComponent(**values)  # type: ignore[arg-type]


def kill_switch(**overrides: object) -> KillSwitchSnapshot:
    values: dict[str, object] = {
        "switch_id": "global-risk",
        "scope": "new-trades",
        "state": KillSwitchState.INACTIVE,
        "activation_source": "safety-control-plane",
        "reason_codes": (),
        "actor_ref": "safety-service",
        "observed_at": NOW,
        "changed_at": NOW - timedelta(seconds=1),
        "evidence": evidence(),
    }
    values.update(overrides)
    return KillSwitchSnapshot(**values)  # type: ignore[arg-type]


def breaker(**overrides: object) -> CircuitBreakerSnapshot:
    values: dict[str, object] = {
        "breaker_id": "exchange-failures",
        "scope": "exchange",
        "state": CircuitBreakerState.CLOSED,
        "failure_count": 0,
        "window_seconds": 60,
        "observed_at": NOW,
        "reason_codes": (),
        "evidence": evidence(),
        "opened_at": None,
        "recovery_test_ref": None,
    }
    values.update(overrides)
    return CircuitBreakerSnapshot(**values)  # type: ignore[arg-type]


def policy_rule(**overrides: object) -> PolicyRule:
    values: dict[str, object] = {
        "rule_id": "deny-unknown",
        "priority": 1,
        "subjects": ("execution-service",),
        "actions": ("submit-order",),
        "resources": ("exchange",),
        "environments": ("test",),
        "modes": ("paper",),
        "condition_ref": "condition/unknown-state",
        "condition_sha256": SHA_A,
        "decision": SafetyDecisionType.BLOCK,
        "reason_code": "UNKNOWN_STATE",
    }
    values.update(overrides)
    return PolicyRule(**values)  # type: ignore[arg-type]


def policy(**overrides: object) -> SafetyPolicy:
    values: dict[str, object] = {
        "policy_id": uuid4(),
        "name": "synthetic safety policy",
        "revision": 1,
        "version": version("safety-policy"),
        "rules": (policy_rule(),),
        "scopes": ("execution",),
        "environments": ("test",),
        "modes": ("paper",),
        "effective_at": NOW - timedelta(hours=1),
        "expires_at": NOW + timedelta(hours=1),
        "created_at": NOW - timedelta(hours=2),
        "owner_ref": "safety-governance",
        "default_decision": SafetyDecisionType.BLOCK,
        "configuration_version": version("configuration"),
        "content_sha256": SHA_B,
    }
    values.update(overrides)
    return SafetyPolicy(**values)  # type: ignore[arg-type]


def readiness(**overrides: object) -> TradingReadinessState:
    values: dict[str, object] = {
        "readiness_id": uuid4(),
        "status": TradingReadinessStatus.READY,
        "internal_state": OperationalSafetyState.READY,
        "components": (component(),),
        "kill_switches": (kill_switch(),),
        "circuit_breakers": (breaker(),),
        "active_incident_refs": (),
        "active_failure_refs": (),
        "reconciliation_refs": (),
        "blocks_new_approval": False,
        "blocks_new_execution": False,
        "reason_codes": (),
        "affected_scopes": ("new-trades",),
        "audit_available": True,
        "evaluated_at": NOW,
        "as_of": NOW - timedelta(seconds=1),
        "valid_until": NOW + timedelta(minutes=5),
        "policy_version": version("safety-policy"),
        "configuration_version": version("configuration"),
        "content_sha256": SHA_C,
    }
    values.update(overrides)
    return TradingReadinessState(**values)  # type: ignore[arg-type]


def context() -> SafetyContextReference:
    return SafetyContextReference(
        action="submit-order",
        actor="execution-service",
        environment="test",
        mode="paper",
        input_content_sha256=SHA_A,
        correlation_id="correlation-1",
        trace_id="trace-1",
        evaluated_at=NOW - timedelta(seconds=1),
    )


def decision(**overrides: object) -> SafetyDecision:
    exact_policy = policy()
    exact_readiness = overrides.get("readiness")
    if not isinstance(exact_readiness, TradingReadinessState):
        exact_readiness = readiness()
    values: dict[str, object] = {
        "decision_id": uuid4(),
        "policy": exact_policy,
        "context": context(),
        "readiness": exact_readiness,
        "kill_switches": exact_readiness.kill_switches,
        "circuit_breakers": exact_readiness.circuit_breakers,
        "security_event_refs": (),
        "failure_event_refs": (),
        "injection_assessment_refs": (),
        "reconciliation_refs": (),
        "decision": SafetyDecisionType.ALLOW,
        "reason_codes": ("POLICY_CLEAR",),
        "affected_scopes": ("new-trades",),
        "producer_ref": "deterministic-safety-control-plane",
        "execution_adjacent": True,
        "decided_at": NOW,
        "as_of": NOW - timedelta(seconds=1),
        "valid_until": NOW + timedelta(minutes=4),
        "policy_version": exact_policy.version,
        "configuration_version": version("configuration"),
        "content_sha256": SHA_C,
    }
    values.update(overrides)
    return SafetyDecision(**values)  # type: ignore[arg-type]


def failure(**overrides: object) -> FailureEvent:
    values: dict[str, object] = {
        "failure_id": uuid4(),
        "classification": FailureClassification.RECOVERABLE,
        "operation_kind": FailureOperationKind.READ_ONLY,
        "source": "market-data-adapter",
        "component": "market-data",
        "operation": "read-status",
        "affected_scope": "market-data",
        "error_code": "TEMPORARY_TIMEOUT",
        "reason_codes": ("UPSTREAM_TIMEOUT",),
        "correlation_id": "correlation-1",
        "trace_id": "trace-1",
        "detected_at": NOW,
        "occurred_at": NOW - timedelta(seconds=1),
        "retry_safe": True,
        "attempt_count": 0,
        "state_known": True,
        "reconciliation_required": False,
        "evidence_refs": (evidence(),),
        "source_version": version("market-data"),
        "configuration_version": version("configuration"),
        "content_sha256": SHA_B,
        "security_event_ref": None,
    }
    values.update(overrides)
    return FailureEvent(**values)  # type: ignore[arg-type]


def recovery(**overrides: object) -> RecoveryAction:
    values: dict[str, object] = {
        "recovery_id": uuid4(),
        "failure": failure(),
        "action_type": RecoveryActionType.CONTROLLED_RETRY,
        "status": RecoveryStatus.SUCCEEDED,
        "target": "market-data-adapter",
        "scope": "market-data",
        "policy_ref": ref("C-097"),
        "authorization_ref": evidence("SYNTHETIC_AUTHORIZATION"),
        "idempotency_key": "recovery-1",
        "side_effecting": True,
        "retry_limit": 1,
        "retry_count": 1,
        "reconciliation_ref": None,
        "requested_at": NOW,
        "authorized_at": NOW + timedelta(seconds=1),
        "started_at": NOW + timedelta(seconds=2),
        "completed_at": NOW + timedelta(seconds=3),
        "result_codes": ("READ_RESTORED",),
        "actor_ref": "recovery-control-plane",
        "blocks_affected_scope": False,
        "evidence_refs": (evidence("SYNTHETIC_RECOVERY_RESULT"),),
        "source_version": version("recovery"),
        "configuration_version": version("configuration"),
        "content_sha256": SHA_C,
    }
    values.update(overrides)
    return RecoveryAction(**values)  # type: ignore[arg-type]


EXPECTED_CONTRACT_IDS = {
    SafetyDecision: "C-058",
    TradingReadinessState: "C-059",
    SecurityEvent: "C-086",
    FailureEvent: "C-087",
    RecoveryAction: "C-088",
    PromptInjectionAssessment: "C-089",
    SafetyPolicy: "C-097",
    AgentPermissionPolicy: "C-098",
    SafetyIncidentReport: "C-099",
}


def test_contract_ids_and_schema_versions_are_exact() -> None:
    assert {contract.CONTRACT_ID for contract in EXPECTED_CONTRACT_IDS} == set(
        EXPECTED_CONTRACT_IDS.values()
    )
    assert all(contract.SCHEMA_VERSION == "1" for contract in EXPECTED_CONTRACT_IDS)
    for contract, contract_id in EXPECTED_CONTRACT_IDS.items():
        defaults = {item.name: item.default for item in fields(contract)}
        assert defaults["contract_id"] == contract_id
        assert defaults["schema_version"] == "1"


def test_canonical_enum_vocabularies_are_exact() -> None:
    assert {item.value for item in SafetyDecisionType} == {
        "ALLOW",
        "DENY",
        "REQUIRE_APPROVAL",
        "REQUIRE_REVALIDATION",
        "ESCALATE",
        "BLOCK",
    }
    assert {item.value for item in TradingReadinessStatus} == {
        "READY",
        "DEGRADED",
        "BLOCKED",
        "EMERGENCY",
        "UNKNOWN",
    }
    assert {item.value for item in CircuitBreakerState} == {
        "CLOSED",
        "OPEN",
        "HALF_OPEN",
    }


def test_contracts_are_frozen_slotted_and_collections_require_tuples() -> None:
    item = policy()
    assert "__dict__" not in dir(item)
    with pytest.raises(FrozenInstanceError):
        item.name = "changed"  # type: ignore[misc]
    with pytest.raises(SafetyContractError, match="must be a tuple"):
        policy(rules=[policy_rule()])


@pytest.mark.parametrize(
    "invalid_digest",
    ["A" * 64, "a" * 63, "g" * 64],
)
def test_lowercase_sha256_is_required(invalid_digest: str) -> None:
    with pytest.raises(SafetyContractError, match="lowercase SHA-256"):
        replace(evidence(), content_sha256=invalid_digest)


def test_uuid_utc_decimal_integer_and_boolean_types_are_strict() -> None:
    with pytest.raises(SafetyContractError, match="UUID"):
        EvidenceReference("TEST", "not-uuid", "source", "1", SHA_A)  # type: ignore[arg-type]
    with pytest.raises(SafetyContractError, match="timezone-aware"):
        component(observed_at=datetime(2026, 9, 26, 9, 0))
    with pytest.raises(SafetyContractError, match="finite Decimal"):
        component(freshness_seconds=float("inf"))
    with pytest.raises(SafetyContractError, match="non-negative integer"):
        breaker(failure_count=True)
    with pytest.raises(SafetyContractError, match="boolean"):
        readiness(blocks_new_execution=0)


def test_aware_times_are_normalized_to_utc() -> None:
    offset = timezone(timedelta(hours=5, minutes=30))
    local = datetime(2026, 9, 26, 14, 30, tzinfo=offset)
    item = context()
    changed = SafetyContextReference(
        action=item.action,
        actor=item.actor,
        environment=item.environment,
        mode=item.mode,
        input_content_sha256=item.input_content_sha256,
        correlation_id=item.correlation_id,
        trace_id=item.trace_id,
        evaluated_at=local,
    )
    assert changed.evaluated_at.tzinfo is UTC


def test_policy_rules_are_unique_ordered_and_fail_closed_by_default() -> None:
    with pytest.raises(SafetyContractError, match="default decision must fail closed"):
        policy(default_decision=SafetyDecisionType.ALLOW)
    duplicate = policy_rule(rule_id="duplicate", priority=1)
    with pytest.raises(SafetyContractError, match="rule priorities"):
        policy(rules=(duplicate, policy_rule(rule_id="second", priority=1)))
    with pytest.raises(SafetyContractError, match="ordered"):
        policy(
            rules=(
                policy_rule(rule_id="two", priority=2),
                policy_rule(rule_id="one", priority=1),
            )
        )


def test_decision_requires_effective_exact_policy_and_cannot_outlive_it() -> None:
    expired = policy(expires_at=NOW - timedelta(seconds=1))
    with pytest.raises(SafetyContractError, match="effective policy"):
        decision(policy=expired, policy_version=expired.version)
    exact = policy()
    with pytest.raises(SafetyContractError, match="policy_version must match"):
        decision(policy=exact, policy_version=version("different-policy"))
    with pytest.raises(SafetyContractError, match="cannot outlive its policy"):
        decision(
            policy=exact,
            policy_version=exact.version,
            valid_until=exact.expires_at + timedelta(seconds=1),
        )


@pytest.mark.parametrize(
    ("internal", "external"),
    [
        (OperationalSafetyState.READY, TradingReadinessStatus.READY),
        (OperationalSafetyState.DEGRADED, TradingReadinessStatus.DEGRADED),
        (OperationalSafetyState.RESTRICTED, TradingReadinessStatus.DEGRADED),
        (OperationalSafetyState.RECOVERY, TradingReadinessStatus.DEGRADED),
        (OperationalSafetyState.BLOCKED, TradingReadinessStatus.BLOCKED),
        (OperationalSafetyState.EMERGENCY_STOP, TradingReadinessStatus.EMERGENCY),
        (OperationalSafetyState.INITIALIZING, TradingReadinessStatus.UNKNOWN),
        (OperationalSafetyState.UNKNOWN, TradingReadinessStatus.UNKNOWN),
    ],
)
def test_canonical_readiness_projection(
    internal: OperationalSafetyState, external: TradingReadinessStatus
) -> None:
    if external is TradingReadinessStatus.READY:
        item = readiness(internal_state=internal, status=external)
    else:
        item = readiness(
            internal_state=internal,
            status=external,
            blocks_new_approval=external
            in {
                TradingReadinessStatus.BLOCKED,
                TradingReadinessStatus.EMERGENCY,
                TradingReadinessStatus.UNKNOWN,
            },
            blocks_new_execution=True,
            reason_codes=("NOT_READY",),
        )
    assert item.status is external


def test_incompatible_readiness_projection_is_rejected() -> None:
    with pytest.raises(SafetyContractError, match="canonical projection"):
        readiness(
            internal_state=OperationalSafetyState.EMERGENCY_STOP,
            status=TradingReadinessStatus.READY,
        )


@pytest.mark.parametrize(
    "overrides",
    [
        {"components": (component(current=False, reason_codes=("STALE",)),)},
        {"audit_available": False},
        {
            "kill_switches": (
                kill_switch(
                    state=KillSwitchState.ACTIVE,
                    reason_codes=("HUMAN_STOP",),
                ),
            )
        },
        {
            "circuit_breakers": (
                breaker(
                    state=CircuitBreakerState.OPEN,
                    reason_codes=("FAILURES",),
                    opened_at=NOW - timedelta(seconds=1),
                ),
            )
        },
        {"active_failure_refs": (ref("C-087"),)},
    ],
)
def test_ready_requires_current_healthy_unblocked_evidence(
    overrides: dict[str, object],
) -> None:
    with pytest.raises(SafetyContractError, match="READY"):
        readiness(**overrides)


@pytest.mark.parametrize(
    "status",
    [
        TradingReadinessStatus.DEGRADED,
        TradingReadinessStatus.BLOCKED,
        TradingReadinessStatus.EMERGENCY,
        TradingReadinessStatus.UNKNOWN,
    ],
)
def test_every_non_ready_state_blocks_new_execution(
    status: TradingReadinessStatus,
) -> None:
    internal = {
        TradingReadinessStatus.DEGRADED: OperationalSafetyState.DEGRADED,
        TradingReadinessStatus.BLOCKED: OperationalSafetyState.BLOCKED,
        TradingReadinessStatus.EMERGENCY: OperationalSafetyState.EMERGENCY_STOP,
        TradingReadinessStatus.UNKNOWN: OperationalSafetyState.UNKNOWN,
    }[status]
    with pytest.raises(SafetyContractError, match="block new execution"):
        readiness(
            status=status,
            internal_state=internal,
            blocks_new_approval=True,
            blocks_new_execution=False,
            reason_codes=("NOT_READY",),
        )


@pytest.mark.parametrize(
    "override",
    [
        {
            "readiness": readiness(
                status=TradingReadinessStatus.DEGRADED,
                internal_state=OperationalSafetyState.DEGRADED,
                blocks_new_execution=True,
                reason_codes=("DEGRADED",),
            )
        },
        {
            "kill_switches": (
                kill_switch(state=KillSwitchState.UNKNOWN, reason_codes=("NO_SIGNAL",)),
            )
        },
        {
            "circuit_breakers": (
                breaker(
                    state=CircuitBreakerState.HALF_OPEN,
                    reason_codes=("RECOVERY_TEST",),
                    recovery_test_ref=evidence(),
                ),
            )
        },
        {"failure_event_refs": (ref("C-087"),)},
    ],
)
def test_execution_adjacent_allow_fails_closed(override: dict[str, object]) -> None:
    with pytest.raises(SafetyContractError, match="ALLOW"):
        decision(**override)


def test_decision_snapshots_must_exactly_match_readiness_evidence() -> None:
    different_switch = kill_switch(
        switch_id="execution",
        scope="execution",
    )
    with pytest.raises(SafetyContractError, match="exact readiness evidence"):
        decision(kill_switches=(different_switch,))


def test_require_approval_is_not_human_approval_or_execution_authority() -> None:
    item = decision(
        decision=SafetyDecisionType.REQUIRE_APPROVAL,
        execution_adjacent=False,
    )
    assert item.decision is SafetyDecisionType.REQUIRE_APPROVAL
    assert "approval" not in {field.name for field in fields(SafetyDecision)}


def security_event(**overrides: object) -> SecurityEvent:
    values: dict[str, object] = {
        "event_id": uuid4(),
        "event_type": SecurityEventType.AUTHORIZATION_DENIED,
        "severity": SecuritySeverity.HIGH,
        "actor_ref": "agent-1",
        "source": "tool-gateway",
        "affected_resource": "restricted-tool",
        "action": "invoke",
        "result": "DENIED",
        "detected_at": NOW,
        "occurred_at": NOW - timedelta(seconds=1),
        "recorded_at": NOW + timedelta(seconds=1),
        "correlation_id": "correlation-1",
        "trace_id": "trace-1",
        "evidence_refs": (evidence(),),
        "investigation_status": InvestigationStatus.IN_PROGRESS,
        "reason_codes": ("NOT_ALLOWED",),
        "source_version": version("security"),
        "content_sha256": SHA_B,
        "audit_ref": ref("C-060"),
    }
    values.update(overrides)
    return SecurityEvent(**values)  # type: ignore[arg-type]


def test_security_event_is_distinct_sanitized_attributable_evidence() -> None:
    item = security_event()
    assert not isinstance(item, AuditEvent)
    names = {field.name for field in fields(SecurityEvent)}
    assert not names.intersection({"token", "credential", "raw_prompt", "raw_payload"})
    assert item.audit_ref is not None and item.audit_ref.contract_id == "C-060"


def test_unknown_failure_forbids_retry_and_requires_reconciliation() -> None:
    with pytest.raises(SafetyContractError, match="Unknown failure"):
        failure(
            classification=FailureClassification.UNKNOWN,
            operation_kind=FailureOperationKind.UNKNOWN,
            retry_safe=False,
            state_known=True,
            reconciliation_required=True,
        )
    item = failure(
        classification=FailureClassification.UNKNOWN,
        operation_kind=FailureOperationKind.UNKNOWN,
        retry_safe=False,
        state_known=False,
        reconciliation_required=True,
    )
    assert item.reconciliation_required


def test_financial_side_effect_failure_cannot_be_retry_safe() -> None:
    with pytest.raises(SafetyContractError, match="cannot be safely retried"):
        failure(
            operation_kind=FailureOperationKind.FINANCIAL_SIDE_EFFECT,
            retry_safe=True,
        )


def test_security_critical_failure_requires_linked_security_evidence() -> None:
    with pytest.raises(SafetyContractError, match="requires security evidence"):
        failure(
            classification=FailureClassification.SECURITY_CRITICAL,
            retry_safe=False,
        )


def test_side_effecting_recovery_requires_authorization_and_idempotency() -> None:
    with pytest.raises(SafetyContractError, match="authorization and idempotency"):
        recovery(authorization_ref=None)


def test_controlled_retry_cannot_wrap_financial_or_unknown_failure() -> None:
    unsafe = failure(
        classification=FailureClassification.UNKNOWN,
        operation_kind=FailureOperationKind.UNKNOWN,
        retry_safe=False,
        state_known=False,
        reconciliation_required=True,
    )
    with pytest.raises(SafetyContractError, match="Controlled retry is unsafe"):
        recovery(failure=unsafe)


def test_failed_or_unknown_recovery_keeps_scope_blocked() -> None:
    with pytest.raises(SafetyContractError, match="must remain blocked"):
        recovery(
            status=RecoveryStatus.UNKNOWN,
            completed_at=None,
            result_codes=(),
            evidence_refs=(),
            blocks_affected_scope=False,
        )


def injection_assessment(**overrides: object) -> PromptInjectionAssessment:
    values: dict[str, object] = {
        "assessment_id": uuid4(),
        "untrusted_content_ref": evidence("UNTRUSTED_CONTENT_HASH"),
        "actor_ref": "external-content",
        "agent_ref": "analysis-agent",
        "model_ref": "model/version",
        "prompt_ref": "prompt/version",
        "tool_context_ref": "tool-context/hash",
        "verdict": PromptInjectionVerdict.MALICIOUS,
        "severity": SecuritySeverity.CRITICAL,
        "indicators": ("POLICY_BYPASS_ATTEMPT",),
        "requested_effects": ("EXECUTE_TRADE",),
        "required_responses": ("BLOCK_TOOL_ESCALATION",),
        "blocks_tool_escalation": True,
        "assessed_at": NOW,
        "as_of": NOW - timedelta(seconds=1),
        "valid_until": NOW + timedelta(minutes=5),
        "detector_version": version("detector"),
        "model_version": version("model"),
        "prompt_version": version("prompt"),
        "policy_version": version("policy"),
        "content_sha256": SHA_C,
    }
    values.update(overrides)
    return PromptInjectionAssessment(**values)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "verdict",
    [
        PromptInjectionVerdict.SUSPICIOUS,
        PromptInjectionVerdict.MALICIOUS,
        PromptInjectionVerdict.UNKNOWN,
    ],
)
def test_unsafe_injection_assessment_blocks_tool_escalation(
    verdict: PromptInjectionVerdict,
) -> None:
    with pytest.raises(SafetyContractError, match="must fail closed"):
        injection_assessment(verdict=verdict, blocks_tool_escalation=False)


def test_clear_injection_assessment_cannot_claim_critical_or_unknown_severity() -> None:
    with pytest.raises(SafetyContractError, match="CLEAR assessment"):
        injection_assessment(
            verdict=PromptInjectionVerdict.CLEAR,
            severity=SecuritySeverity.CRITICAL,
            indicators=(),
            requested_effects=(),
            required_responses=(),
            blocks_tool_escalation=False,
        )


PROHIBITED_CAPABILITIES = (
    "HUMAN_TRADE_APPROVAL",
    "POLICY_OVERRIDE",
    "WITHDRAW_FUNDS",
    "TRANSFER_FUNDS",
    "UNRESTRICTED_CREDENTIAL_ACCESS",
    "ARBITRARY_TOOL_EXECUTION",
    "DIRECT_AI_ORDER_SUBMISSION",
)


def permission_grant(**overrides: object) -> PermissionGrant:
    values: dict[str, object] = {
        "grant_id": "read-market-data",
        "action": "READ_MARKET_DATA",
        "tool": "market-data-reader",
        "resource": "market-data",
        "environments": ("test",),
        "modes": ("research",),
        "valid_from": NOW,
        "valid_until": NOW + timedelta(hours=1),
        "constraints_sha256": SHA_A,
    }
    values.update(overrides)
    return PermissionGrant(**values)  # type: ignore[arg-type]


def permission_policy(**overrides: object) -> AgentPermissionPolicy:
    values: dict[str, object] = {
        "policy_id": uuid4(),
        "name": "analysis-agent ceiling",
        "revision": 1,
        "version": version("permission-policy"),
        "agent_roles": ("analysis-agent",),
        "agent_identities": (),
        "grants": (permission_grant(),),
        "denied_capabilities": PROHIBITED_CAPABILITIES,
        "default_deny": True,
        "environments": ("test",),
        "modes": ("research",),
        "effective_at": NOW,
        "expires_at": NOW + timedelta(hours=1),
        "created_at": NOW - timedelta(hours=1),
        "issuer_ref": "security-governance",
        "configuration_version": version("configuration"),
        "content_sha256": SHA_B,
    }
    values.update(overrides)
    return AgentPermissionPolicy(**values)  # type: ignore[arg-type]


def test_agent_permission_policy_is_default_deny_and_bounded() -> None:
    item = permission_policy()
    assert item.default_deny
    with pytest.raises(SafetyContractError, match="default deny"):
        permission_policy(default_deny=False)
    with pytest.raises(SafetyContractError, match="prohibited capabilities"):
        permission_policy(denied_capabilities=("WITHDRAW_FUNDS",))


def test_agent_grant_cannot_encode_prohibited_authority() -> None:
    with pytest.raises(SafetyContractError, match="prohibited authority"):
        permission_policy(
            grants=(permission_grant(action="DIRECT_AI_ORDER_SUBMISSION"),)
        )


def test_permission_grant_cannot_exceed_policy_scope_or_validity() -> None:
    with pytest.raises(SafetyContractError, match="exceeds its policy ceiling"):
        permission_policy(grants=(permission_grant(environments=("production",)),))


def incident(**overrides: object) -> SafetyIncidentReport:
    completed_recovery = recovery()
    values: dict[str, object] = {
        "incident_id": uuid4(),
        "status": IncidentStatus.RESOLVED,
        "severity": SecuritySeverity.HIGH,
        "title": "Synthetic authorization incident",
        "category": "AUTHORIZATION",
        "affected_scopes": ("tool-access",),
        "affected_resources": ("restricted-tool",),
        "security_event_refs": (ref("C-086"),),
        "failure_event_refs": (),
        "injection_assessment_refs": (),
        "other_evidence_refs": (),
        "containment_actions": ("ACCESS_BLOCKED",),
        "recovery_actions": (completed_recovery,),
        "readiness_ref": ref("C-059"),
        "safety_decision_ref": ref("C-058"),
        "detected_at": NOW,
        "declared_at": NOW + timedelta(seconds=1),
        "contained_at": NOW + timedelta(seconds=2),
        "resolved_at": NOW + timedelta(seconds=4),
        "closed_at": None,
        "owner_ref": "security-owner",
        "human_authorization_ref": evidence("SYNTHETIC_HUMAN_AUTHORIZATION"),
        "root_cause_codes": ("POLICY_SCOPE_VIOLATION",),
        "remediation_codes": ("POLICY_REVIEWED",),
        "blocks_critical_actions": False,
        "policy_version": version("safety-policy"),
        "configuration_version": version("configuration"),
        "source_version": version("incident-service"),
        "content_sha256": SHA_C,
    }
    values.update(overrides)
    return SafetyIncidentReport(**values)  # type: ignore[arg-type]


def test_incident_requires_originating_evidence() -> None:
    with pytest.raises(SafetyContractError, match="originating evidence"):
        incident(security_event_refs=())


def test_resolved_incident_requires_containment_and_recovery_evidence() -> None:
    with pytest.raises(SafetyContractError, match="recovery evidence"):
        incident(recovery_actions=())


def test_unresolved_critical_incident_remains_blocking() -> None:
    with pytest.raises(SafetyContractError, match="must block"):
        incident(
            status=IncidentStatus.OPEN,
            containment_actions=(),
            recovery_actions=(),
            contained_at=None,
            resolved_at=None,
            root_cause_codes=(),
            remediation_codes=(),
            blocks_critical_actions=False,
        )


def test_existing_c060_audit_contract_remains_canonical_and_unchanged() -> None:
    assert AUDIT_SCHEMA_VERSION == "1"
    assert not hasattr(safety_package, "AuditEvent")
    assert {item.value for item in AuditEventType} == {
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
    audit = AuditEvent(
        event_type=AuditEventType.SECURITY_EVENT,
        actor="security-service",
        action="record-event",
        source="security",
        result="RECORDED",
        correlation_id="correlation-1",
        trace_id="trace-1",
    )
    assert audit.schema_version == "1"
    assert audit.occurred_at.tzinfo is UTC
    assert "__dict__" not in dir(audit)
    with pytest.raises(FrozenInstanceError):
        audit.result = "CHANGED"  # type: ignore[misc]


def test_execution_contract_keeps_reference_only_c058_c059_boundary() -> None:
    hints = get_type_hints(ExecutionIntent)
    assert hints["safety_decision"] is ContractReference
    assert hints["readiness_state"] is ContractReference
    assert ref("C-058").contract_id == SafetyDecision.CONTRACT_ID
    assert ref("C-059").contract_id == TradingReadinessState.CONTRACT_ID


def test_health_readiness_vocabulary_remains_compatible() -> None:
    assert {item.value for item in HealthReadinessStatus} == {
        item.value for item in TradingReadinessStatus
    }


def test_duplicate_stable_identities_are_rejected() -> None:
    first = component()
    duplicate = component(evidence=evidence("OTHER"))
    with pytest.raises(SafetyContractError, match="component identities"):
        readiness(components=(first, duplicate))


def test_schema_surface_contains_no_runtime_or_secret_bearing_fields() -> None:
    public_fields = {
        field.name for contract in EXPECTED_CONTRACT_IDS for field in fields(contract)
    }
    assert not public_fields.intersection(
        {
            "password",
            "token",
            "api_key",
            "credential",
            "raw_prompt",
            "raw_payload",
            "provider_session",
            "callback",
        }
    )
    source = Path(safety_package.__file__).with_name("contracts.py").read_text()
    assert "fastapi" not in source.lower()
    assert "sqlalchemy" not in source.lower()
    assert "httpx" not in source.lower()
    assert "requests." not in source.lower()
    assert "ccxt" not in source.lower()


def test_invalid_enum_strings_fail_deterministically() -> None:
    with pytest.raises(SafetyContractError, match="TradingReadinessStatus"):
        readiness(status="READY")  # type: ignore[arg-type]


def test_public_package_exports_only_the_bounded_contract_surface() -> None:
    assert set(safety_package.__all__) == {
        "CONTRACT_SCHEMA_VERSION",
        "AgentPermissionPolicy",
        "CircuitBreakerSnapshot",
        "CircuitBreakerState",
        "ComponentHealthStatus",
        "EvidenceReference",
        "FailureClassification",
        "FailureEvent",
        "FailureOperationKind",
        "IncidentStatus",
        "InvestigationStatus",
        "KillSwitchSnapshot",
        "KillSwitchState",
        "OperationalSafetyState",
        "PermissionGrant",
        "PolicyRule",
        "PromptInjectionAssessment",
        "PromptInjectionVerdict",
        "ReadinessComponent",
        "RecoveryAction",
        "RecoveryActionType",
        "RecoveryStatus",
        "SafetyContextReference",
        "SafetyContractError",
        "SafetyDecision",
        "SafetyDecisionType",
        "SafetyIncidentReport",
        "SafetyPolicy",
        "SecurityEvent",
        "SecurityEventType",
        "SecuritySeverity",
        "TradingReadinessState",
        "TradingReadinessStatus",
    }
