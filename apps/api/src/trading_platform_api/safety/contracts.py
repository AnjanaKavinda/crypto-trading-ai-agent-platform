from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from typing import ClassVar, TypeVar, cast
from uuid import UUID

from trading_platform_api.risk import ContractReference, VersionReference

CONTRACT_SCHEMA_VERSION = "1"
_SHA256 = re.compile(r"[0-9a-f]{64}")
_T = TypeVar("_T")


class SafetyContractError(ValueError):
    """Raised when safety or security evidence is structurally invalid."""


class SafetyDecisionType(StrEnum):
    ALLOW = "ALLOW"
    DENY = "DENY"
    REQUIRE_APPROVAL = "REQUIRE_APPROVAL"
    REQUIRE_REVALIDATION = "REQUIRE_REVALIDATION"
    ESCALATE = "ESCALATE"
    BLOCK = "BLOCK"


class TradingReadinessStatus(StrEnum):
    READY = "READY"
    DEGRADED = "DEGRADED"
    BLOCKED = "BLOCKED"
    EMERGENCY = "EMERGENCY"
    UNKNOWN = "UNKNOWN"


class OperationalSafetyState(StrEnum):
    INITIALIZING = "INITIALIZING"
    READY = "READY"
    DEGRADED = "DEGRADED"
    RESTRICTED = "RESTRICTED"
    BLOCKED = "BLOCKED"
    EMERGENCY_STOP = "EMERGENCY_STOP"
    RECOVERY = "RECOVERY"
    UNKNOWN = "UNKNOWN"


class KillSwitchState(StrEnum):
    INACTIVE = "INACTIVE"
    ACTIVE = "ACTIVE"
    UNKNOWN = "UNKNOWN"


class CircuitBreakerState(StrEnum):
    CLOSED = "CLOSED"
    OPEN = "OPEN"
    HALF_OPEN = "HALF_OPEN"


class ComponentHealthStatus(StrEnum):
    HEALTHY = "HEALTHY"
    DEGRADED = "DEGRADED"
    UNHEALTHY = "UNHEALTHY"
    UNKNOWN = "UNKNOWN"


class SecuritySeverity(StrEnum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"
    UNKNOWN = "UNKNOWN"


class SecurityEventType(StrEnum):
    AUTHENTICATION_FAILURE = "AUTHENTICATION_FAILURE"
    AUTHORIZATION_DENIED = "AUTHORIZATION_DENIED"
    CREDENTIAL_COMPROMISE_SUSPECTED = "CREDENTIAL_COMPROMISE_SUSPECTED"
    SECRET_EXPOSURE_SUSPECTED = "SECRET_EXPOSURE_SUSPECTED"  # pragma: allowlist secret
    PROMPT_INJECTION = "PROMPT_INJECTION"
    TOOL_POLICY_VIOLATION = "TOOL_POLICY_VIOLATION"
    TAMPER_DETECTED = "TAMPER_DETECTED"
    ANOMALOUS_ACCESS = "ANOMALOUS_ACCESS"
    OTHER = "OTHER"
    UNKNOWN = "UNKNOWN"


class InvestigationStatus(StrEnum):
    NOT_STARTED = "NOT_STARTED"
    IN_PROGRESS = "IN_PROGRESS"
    CLOSED = "CLOSED"
    UNKNOWN = "UNKNOWN"


class FailureClassification(StrEnum):
    TRANSIENT = "TRANSIENT"
    RECOVERABLE = "RECOVERABLE"
    NON_RECOVERABLE = "NON_RECOVERABLE"
    UNKNOWN = "UNKNOWN"
    SECURITY_CRITICAL = "SECURITY_CRITICAL"


class FailureOperationKind(StrEnum):
    READ_ONLY = "READ_ONLY"
    IDEMPOTENT_WRITE = "IDEMPOTENT_WRITE"
    FINANCIAL_SIDE_EFFECT = "FINANCIAL_SIDE_EFFECT"
    UNKNOWN = "UNKNOWN"


class RecoveryActionType(StrEnum):
    NO_ACTION = "NO_ACTION"
    CONTROLLED_RETRY = "CONTROLLED_RETRY"
    RECONCILE = "RECONCILE"
    ISOLATE = "ISOLATE"
    DEGRADE = "DEGRADE"
    BLOCK = "BLOCK"
    ACTIVATE_CIRCUIT_BREAKER = "ACTIVATE_CIRCUIT_BREAKER"
    ACTIVATE_KILL_SWITCH = "ACTIVATE_KILL_SWITCH"
    ESCALATE_TO_HUMAN = "ESCALATE_TO_HUMAN"
    RESTORE_FROM_BACKUP = "RESTORE_FROM_BACKUP"


class RecoveryStatus(StrEnum):
    PROPOSED = "PROPOSED"
    AUTHORIZED = "AUTHORIZED"
    IN_PROGRESS = "IN_PROGRESS"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    UNKNOWN = "UNKNOWN"


class PromptInjectionVerdict(StrEnum):
    CLEAR = "CLEAR"
    SUSPICIOUS = "SUSPICIOUS"
    MALICIOUS = "MALICIOUS"
    UNKNOWN = "UNKNOWN"


class IncidentStatus(StrEnum):
    OPEN = "OPEN"
    CONTAINED = "CONTAINED"
    RECOVERING = "RECOVERING"
    RESOLVED = "RESOLVED"
    CLOSED = "CLOSED"
    UNKNOWN = "UNKNOWN"


def _text(name: str, value: object, *, maximum: int = 255) -> str:
    if not isinstance(value, str):
        raise SafetyContractError(f"{name} must be a string.")
    if not value.strip():
        raise SafetyContractError(f"{name} must not be blank.")
    if value != value.strip():
        raise SafetyContractError(f"{name} must not contain surrounding whitespace.")
    if len(value) > maximum:
        raise SafetyContractError(f"{name} must not exceed {maximum} characters.")
    return value


def _uuid(name: str, value: object) -> UUID:
    if not isinstance(value, UUID):
        raise SafetyContractError(f"{name} must be a UUID.")
    return value


def _time(name: str, value: object) -> datetime:
    if not isinstance(value, datetime):
        raise SafetyContractError(f"{name} must be a datetime.")
    if value.tzinfo is None or value.utcoffset() is None:
        raise SafetyContractError(f"{name} must be timezone-aware.")
    return value.astimezone(UTC)


def _optional_time(name: str, value: object) -> datetime | None:
    if value is None:
        return None
    return _time(name, value)


def _digest(name: str, value: object) -> str:
    result = _text(name, value, maximum=64)
    if _SHA256.fullmatch(result) is None:
        raise SafetyContractError(f"{name} must be a lowercase SHA-256 digest.")
    return result


def _positive_decimal(name: str, value: object) -> Decimal:
    if (
        not isinstance(value, Decimal)
        or isinstance(value, bool)
        or not value.is_finite()
    ):
        raise SafetyContractError(f"{name} must be a finite Decimal.")
    if value <= 0:
        raise SafetyContractError(f"{name} must be positive.")
    return value


def _nonnegative_int(name: str, value: object) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise SafetyContractError(f"{name} must be a non-negative integer.")
    return value


def _positive_int(name: str, value: object) -> int:
    result = _nonnegative_int(name, value)
    if result == 0:
        raise SafetyContractError(f"{name} must be a positive integer.")
    return result


def _bool(name: str, value: object) -> bool:
    if not isinstance(value, bool):
        raise SafetyContractError(f"{name} must be a boolean.")
    return value


def _tuple(name: str, value: object, *, empty: bool = True) -> tuple[object, ...]:
    if not isinstance(value, tuple):
        raise SafetyContractError(f"{name} must be a tuple.")
    if not empty and not value:
        raise SafetyContractError(f"{name} must not be empty.")
    return value


def _unique(name: str, values: tuple[object, ...]) -> None:
    try:
        unique_count = len(set(values))
    except TypeError as exc:
        raise SafetyContractError(f"{name} must have hashable identities.") from exc
    if unique_count != len(values):
        raise SafetyContractError(f"{name} must not contain duplicates.")


def _typed_tuple(
    name: str, value: object, expected: type[_T], *, empty: bool = True
) -> tuple[_T, ...]:
    values = _tuple(name, value, empty=empty)
    if any(not isinstance(item, expected) for item in values):
        raise SafetyContractError(f"{name} contains an invalid type.")
    return cast(tuple[_T, ...], values)


def _text_tuple(name: str, value: object, *, empty: bool = True) -> tuple[str, ...]:
    values = _tuple(name, value, empty=empty)
    result = tuple(_text(f"{name}[{index}]", item) for index, item in enumerate(values))
    _unique(name, result)
    return result


def _references(
    name: str,
    value: object,
    *,
    contract_id: str | None = None,
    empty: bool = True,
) -> tuple[ContractReference, ...]:
    values = _typed_tuple(name, value, ContractReference, empty=empty)
    if contract_id is not None and any(
        ref.contract_id != contract_id for ref in values
    ):
        raise SafetyContractError(f"{name} must contain only {contract_id} references.")
    _unique(name, tuple((ref.contract_id, ref.entity_id) for ref in values))
    return values


def _reference(name: str, value: object, contract_id: str) -> ContractReference:
    if not isinstance(value, ContractReference) or value.contract_id != contract_id:
        raise SafetyContractError(f"{name} must be a {contract_id} reference.")
    return value


def _version(name: str, value: object) -> VersionReference:
    if not isinstance(value, VersionReference):
        raise SafetyContractError(f"{name} must be a VersionReference.")
    return value


def _ordered(
    earlier_name: str, earlier: datetime, later_name: str, later: datetime
) -> None:
    if earlier > later:
        raise SafetyContractError(f"{earlier_name} must not be after {later_name}.")


def _enum(name: str, value: object, expected: type[_T]) -> _T:
    if not isinstance(value, expected):
        raise SafetyContractError(f"{name} must be a {expected.__name__}.")
    return value


@dataclass(frozen=True, slots=True)
class EvidenceReference:
    evidence_type: str
    evidence_id: UUID
    source: str
    source_version: str
    content_sha256: str

    def __post_init__(self) -> None:
        _text("evidence_type", self.evidence_type)
        _uuid("evidence_id", self.evidence_id)
        _text("source", self.source)
        _text("source_version", self.source_version)
        _digest("content_sha256", self.content_sha256)


@dataclass(frozen=True, slots=True)
class SafetyContextReference:
    action: str
    actor: str
    environment: str
    mode: str
    input_content_sha256: str
    correlation_id: str
    trace_id: str
    evaluated_at: datetime

    def __post_init__(self) -> None:
        for name in (
            "action",
            "actor",
            "environment",
            "mode",
            "correlation_id",
            "trace_id",
        ):
            _text(name, getattr(self, name))
        _digest("input_content_sha256", self.input_content_sha256)
        object.__setattr__(
            self, "evaluated_at", _time("evaluated_at", self.evaluated_at)
        )


@dataclass(frozen=True, slots=True)
class ReadinessComponent:
    component_id: str
    status: ComponentHealthStatus
    evidence: EvidenceReference
    observed_at: datetime
    as_of: datetime
    freshness_seconds: Decimal
    current: bool
    reason_codes: tuple[str, ...]

    def __post_init__(self) -> None:
        _text("component_id", self.component_id)
        _enum("status", self.status, ComponentHealthStatus)
        if not isinstance(self.evidence, EvidenceReference):
            raise SafetyContractError("evidence must be an EvidenceReference.")
        observed_at = _time("observed_at", self.observed_at)
        as_of = _time("as_of", self.as_of)
        _ordered("as_of", as_of, "observed_at", observed_at)
        object.__setattr__(self, "observed_at", observed_at)
        object.__setattr__(self, "as_of", as_of)
        _positive_decimal("freshness_seconds", self.freshness_seconds)
        _bool("current", self.current)
        reasons = _text_tuple("reason_codes", self.reason_codes)
        if (
            self.status is not ComponentHealthStatus.HEALTHY or not self.current
        ) and not reasons:
            raise SafetyContractError(
                "Non-healthy or stale component requires reason_codes."
            )


@dataclass(frozen=True, slots=True)
class KillSwitchSnapshot:
    switch_id: str
    scope: str
    state: KillSwitchState
    activation_source: str
    reason_codes: tuple[str, ...]
    actor_ref: str
    observed_at: datetime
    changed_at: datetime
    evidence: EvidenceReference

    def __post_init__(self) -> None:
        for name in ("switch_id", "scope", "activation_source", "actor_ref"):
            _text(name, getattr(self, name))
        _enum("state", self.state, KillSwitchState)
        reasons = _text_tuple("reason_codes", self.reason_codes)
        if self.state is not KillSwitchState.INACTIVE and not reasons:
            raise SafetyContractError(
                "Active or unknown kill switch requires reason_codes."
            )
        observed_at = _time("observed_at", self.observed_at)
        changed_at = _time("changed_at", self.changed_at)
        _ordered("changed_at", changed_at, "observed_at", observed_at)
        object.__setattr__(self, "observed_at", observed_at)
        object.__setattr__(self, "changed_at", changed_at)
        if not isinstance(self.evidence, EvidenceReference):
            raise SafetyContractError("evidence must be an EvidenceReference.")


@dataclass(frozen=True, slots=True)
class CircuitBreakerSnapshot:
    breaker_id: str
    scope: str
    state: CircuitBreakerState
    failure_count: int
    window_seconds: int
    observed_at: datetime
    reason_codes: tuple[str, ...]
    evidence: EvidenceReference
    opened_at: datetime | None = None
    recovery_test_ref: EvidenceReference | None = None

    def __post_init__(self) -> None:
        _text("breaker_id", self.breaker_id)
        _text("scope", self.scope)
        _enum("state", self.state, CircuitBreakerState)
        _nonnegative_int("failure_count", self.failure_count)
        _positive_int("window_seconds", self.window_seconds)
        observed_at = _time("observed_at", self.observed_at)
        opened_at = _optional_time("opened_at", self.opened_at)
        if opened_at is not None:
            _ordered("opened_at", opened_at, "observed_at", observed_at)
        object.__setattr__(self, "observed_at", observed_at)
        object.__setattr__(self, "opened_at", opened_at)
        reasons = _text_tuple("reason_codes", self.reason_codes)
        if self.state is not CircuitBreakerState.CLOSED and not reasons:
            raise SafetyContractError(
                "Open or half-open breaker requires reason_codes."
            )
        if self.state is CircuitBreakerState.OPEN and opened_at is None:
            raise SafetyContractError("Open breaker requires opened_at.")
        if (
            self.state is CircuitBreakerState.HALF_OPEN
            and self.recovery_test_ref is None
        ):
            raise SafetyContractError("Half-open breaker requires recovery_test_ref.")
        if self.recovery_test_ref is not None and not isinstance(
            self.recovery_test_ref, EvidenceReference
        ):
            raise SafetyContractError("recovery_test_ref must be an EvidenceReference.")
        if not isinstance(self.evidence, EvidenceReference):
            raise SafetyContractError("evidence must be an EvidenceReference.")


@dataclass(frozen=True, slots=True)
class PolicyRule:
    rule_id: str
    priority: int
    subjects: tuple[str, ...]
    actions: tuple[str, ...]
    resources: tuple[str, ...]
    environments: tuple[str, ...]
    modes: tuple[str, ...]
    condition_ref: str
    condition_sha256: str
    decision: SafetyDecisionType
    reason_code: str

    def __post_init__(self) -> None:
        _text("rule_id", self.rule_id)
        _positive_int("priority", self.priority)
        for name in ("subjects", "actions", "resources", "environments", "modes"):
            _text_tuple(name, getattr(self, name), empty=False)
        _text("condition_ref", self.condition_ref)
        _digest("condition_sha256", self.condition_sha256)
        _enum("decision", self.decision, SafetyDecisionType)
        _text("reason_code", self.reason_code)


@dataclass(frozen=True, slots=True)
class PermissionGrant:
    grant_id: str
    action: str
    tool: str
    resource: str
    environments: tuple[str, ...]
    modes: tuple[str, ...]
    valid_from: datetime
    valid_until: datetime
    constraints_sha256: str

    def __post_init__(self) -> None:
        for name in ("grant_id", "action", "tool", "resource"):
            _text(name, getattr(self, name))
        _text_tuple("environments", self.environments, empty=False)
        _text_tuple("modes", self.modes, empty=False)
        valid_from = _time("valid_from", self.valid_from)
        valid_until = _time("valid_until", self.valid_until)
        _ordered("valid_from", valid_from, "valid_until", valid_until)
        if valid_from == valid_until:
            raise SafetyContractError(
                "Permission grant validity window must be positive."
            )
        object.__setattr__(self, "valid_from", valid_from)
        object.__setattr__(self, "valid_until", valid_until)
        _digest("constraints_sha256", self.constraints_sha256)


@dataclass(frozen=True, slots=True)
class SafetyPolicy:
    CONTRACT_ID: ClassVar[str] = "C-097"
    SCHEMA_VERSION: ClassVar[str] = CONTRACT_SCHEMA_VERSION

    policy_id: UUID
    name: str
    revision: int
    version: VersionReference
    rules: tuple[PolicyRule, ...]
    scopes: tuple[str, ...]
    environments: tuple[str, ...]
    modes: tuple[str, ...]
    effective_at: datetime
    expires_at: datetime
    created_at: datetime
    owner_ref: str
    default_decision: SafetyDecisionType
    configuration_version: VersionReference
    content_sha256: str
    contract_id: str = field(default="C-097", init=False)
    schema_version: str = field(default=CONTRACT_SCHEMA_VERSION, init=False)

    def __post_init__(self) -> None:
        _uuid("policy_id", self.policy_id)
        _text("name", self.name)
        _positive_int("revision", self.revision)
        _version("version", self.version)
        rules = _typed_tuple("rules", self.rules, PolicyRule, empty=False)
        rule_ids = tuple(rule.rule_id for rule in rules)
        priorities = tuple(rule.priority for rule in rules)
        _unique("rule identities", rule_ids)
        _unique("rule priorities", priorities)
        if priorities != tuple(sorted(priorities)):
            raise SafetyContractError("rules must be ordered by ascending priority.")
        for name in ("scopes", "environments", "modes"):
            _text_tuple(name, getattr(self, name), empty=False)
        effective_at = _time("effective_at", self.effective_at)
        expires_at = _time("expires_at", self.expires_at)
        created_at = _time("created_at", self.created_at)
        _ordered("created_at", created_at, "effective_at", effective_at)
        _ordered("effective_at", effective_at, "expires_at", expires_at)
        if effective_at == expires_at:
            raise SafetyContractError("Safety policy validity window must be positive.")
        object.__setattr__(self, "effective_at", effective_at)
        object.__setattr__(self, "expires_at", expires_at)
        object.__setattr__(self, "created_at", created_at)
        _text("owner_ref", self.owner_ref)
        _enum("default_decision", self.default_decision, SafetyDecisionType)
        if self.default_decision is SafetyDecisionType.ALLOW:
            raise SafetyContractError(
                "Safety policy default decision must fail closed."
            )
        _version("configuration_version", self.configuration_version)
        _digest("content_sha256", self.content_sha256)


_READINESS_PROJECTION = {
    OperationalSafetyState.INITIALIZING: TradingReadinessStatus.UNKNOWN,
    OperationalSafetyState.READY: TradingReadinessStatus.READY,
    OperationalSafetyState.DEGRADED: TradingReadinessStatus.DEGRADED,
    OperationalSafetyState.RESTRICTED: TradingReadinessStatus.DEGRADED,
    OperationalSafetyState.BLOCKED: TradingReadinessStatus.BLOCKED,
    OperationalSafetyState.EMERGENCY_STOP: TradingReadinessStatus.EMERGENCY,
    OperationalSafetyState.RECOVERY: TradingReadinessStatus.DEGRADED,
    OperationalSafetyState.UNKNOWN: TradingReadinessStatus.UNKNOWN,
}


@dataclass(frozen=True, slots=True)
class TradingReadinessState:
    CONTRACT_ID: ClassVar[str] = "C-059"
    SCHEMA_VERSION: ClassVar[str] = CONTRACT_SCHEMA_VERSION

    readiness_id: UUID
    status: TradingReadinessStatus
    internal_state: OperationalSafetyState
    components: tuple[ReadinessComponent, ...]
    kill_switches: tuple[KillSwitchSnapshot, ...]
    circuit_breakers: tuple[CircuitBreakerSnapshot, ...]
    active_incident_refs: tuple[ContractReference, ...]
    active_failure_refs: tuple[ContractReference, ...]
    reconciliation_refs: tuple[ContractReference, ...]
    blocks_new_approval: bool
    blocks_new_execution: bool
    reason_codes: tuple[str, ...]
    affected_scopes: tuple[str, ...]
    audit_available: bool
    evaluated_at: datetime
    as_of: datetime
    valid_until: datetime
    policy_version: VersionReference
    configuration_version: VersionReference
    content_sha256: str
    contract_id: str = field(default="C-059", init=False)
    schema_version: str = field(default=CONTRACT_SCHEMA_VERSION, init=False)

    def __post_init__(self) -> None:
        _uuid("readiness_id", self.readiness_id)
        _enum("status", self.status, TradingReadinessStatus)
        _enum("internal_state", self.internal_state, OperationalSafetyState)
        if _READINESS_PROJECTION[self.internal_state] is not self.status:
            raise SafetyContractError(
                "Readiness status does not match canonical projection."
            )
        components = _typed_tuple(
            "components", self.components, ReadinessComponent, empty=False
        )
        _unique("component identities", tuple(item.component_id for item in components))
        switches = _typed_tuple("kill_switches", self.kill_switches, KillSwitchSnapshot)
        _unique("kill switch identities", tuple(item.switch_id for item in switches))
        breakers = _typed_tuple(
            "circuit_breakers", self.circuit_breakers, CircuitBreakerSnapshot
        )
        _unique(
            "circuit breaker identities", tuple(item.breaker_id for item in breakers)
        )
        incidents = _references(
            "active_incident_refs", self.active_incident_refs, contract_id="C-099"
        )
        failures = _references(
            "active_failure_refs", self.active_failure_refs, contract_id="C-087"
        )
        reconciliations = _references(
            "reconciliation_refs", self.reconciliation_refs, contract_id="C-096"
        )
        _bool("blocks_new_approval", self.blocks_new_approval)
        _bool("blocks_new_execution", self.blocks_new_execution)
        reasons = _text_tuple("reason_codes", self.reason_codes)
        _text_tuple("affected_scopes", self.affected_scopes, empty=False)
        _bool("audit_available", self.audit_available)
        evaluated_at = _time("evaluated_at", self.evaluated_at)
        as_of = _time("as_of", self.as_of)
        valid_until = _time("valid_until", self.valid_until)
        _ordered("as_of", as_of, "evaluated_at", evaluated_at)
        _ordered("evaluated_at", evaluated_at, "valid_until", valid_until)
        if evaluated_at == valid_until:
            raise SafetyContractError("Readiness validity window must be positive.")
        object.__setattr__(self, "evaluated_at", evaluated_at)
        object.__setattr__(self, "as_of", as_of)
        object.__setattr__(self, "valid_until", valid_until)
        _version("policy_version", self.policy_version)
        _version("configuration_version", self.configuration_version)
        _digest("content_sha256", self.content_sha256)

        active_switch = any(
            item.state is not KillSwitchState.INACTIVE for item in switches
        )
        unsafe_breaker = any(
            item.state is not CircuitBreakerState.CLOSED for item in breakers
        )
        if self.status is TradingReadinessStatus.READY:
            if any(
                item.status is not ComponentHealthStatus.HEALTHY or not item.current
                for item in components
            ):
                raise SafetyContractError("READY requires current healthy components.")
            if active_switch or unsafe_breaker:
                raise SafetyContractError(
                    "READY cannot contain active safety controls."
                )
            if incidents or failures or reconciliations:
                raise SafetyContractError(
                    "READY cannot contain unresolved critical evidence."
                )
            if not self.audit_available:
                raise SafetyContractError(
                    "READY requires the audit path to be available."
                )
            if self.blocks_new_approval or self.blocks_new_execution:
                raise SafetyContractError(
                    "READY must not claim new approval/execution is blocked."
                )
        else:
            if not self.blocks_new_execution:
                raise SafetyContractError(
                    "Every non-READY state must block new execution."
                )
            if not reasons:
                raise SafetyContractError(
                    "Every non-READY state requires reason_codes."
                )
        if (
            self.status
            in {
                TradingReadinessStatus.BLOCKED,
                TradingReadinessStatus.EMERGENCY,
                TradingReadinessStatus.UNKNOWN,
            }
            and not self.blocks_new_approval
        ):
            raise SafetyContractError(
                "Blocked/emergency/unknown readiness must block approval."
            )


@dataclass(frozen=True, slots=True)
class SafetyDecision:
    CONTRACT_ID: ClassVar[str] = "C-058"
    SCHEMA_VERSION: ClassVar[str] = CONTRACT_SCHEMA_VERSION

    decision_id: UUID
    policy: SafetyPolicy
    context: SafetyContextReference
    readiness: TradingReadinessState
    kill_switches: tuple[KillSwitchSnapshot, ...]
    circuit_breakers: tuple[CircuitBreakerSnapshot, ...]
    security_event_refs: tuple[ContractReference, ...]
    failure_event_refs: tuple[ContractReference, ...]
    injection_assessment_refs: tuple[ContractReference, ...]
    reconciliation_refs: tuple[ContractReference, ...]
    decision: SafetyDecisionType
    reason_codes: tuple[str, ...]
    affected_scopes: tuple[str, ...]
    producer_ref: str
    execution_adjacent: bool
    decided_at: datetime
    as_of: datetime
    valid_until: datetime
    policy_version: VersionReference
    configuration_version: VersionReference
    content_sha256: str
    contract_id: str = field(default="C-058", init=False)
    schema_version: str = field(default=CONTRACT_SCHEMA_VERSION, init=False)

    def __post_init__(self) -> None:
        _uuid("decision_id", self.decision_id)
        if not isinstance(self.policy, SafetyPolicy):
            raise SafetyContractError("policy must be a SafetyPolicy.")
        if not isinstance(self.context, SafetyContextReference):
            raise SafetyContractError("context must be a SafetyContextReference.")
        if not isinstance(self.readiness, TradingReadinessState):
            raise SafetyContractError("readiness must be a TradingReadinessState.")
        switches = _typed_tuple("kill_switches", self.kill_switches, KillSwitchSnapshot)
        _unique("kill switch identities", tuple(item.switch_id for item in switches))
        breakers = _typed_tuple(
            "circuit_breakers", self.circuit_breakers, CircuitBreakerSnapshot
        )
        _unique(
            "circuit breaker identities", tuple(item.breaker_id for item in breakers)
        )
        security = _references(
            "security_event_refs", self.security_event_refs, contract_id="C-086"
        )
        failures = _references(
            "failure_event_refs", self.failure_event_refs, contract_id="C-087"
        )
        injections = _references(
            "injection_assessment_refs",
            self.injection_assessment_refs,
            contract_id="C-089",
        )
        reconciliations = _references(
            "reconciliation_refs", self.reconciliation_refs, contract_id="C-096"
        )
        _enum("decision", self.decision, SafetyDecisionType)
        _text_tuple("reason_codes", self.reason_codes, empty=False)
        _text_tuple("affected_scopes", self.affected_scopes, empty=False)
        _text("producer_ref", self.producer_ref)
        _bool("execution_adjacent", self.execution_adjacent)
        decided_at = _time("decided_at", self.decided_at)
        as_of = _time("as_of", self.as_of)
        valid_until = _time("valid_until", self.valid_until)
        _ordered("as_of", as_of, "decided_at", decided_at)
        _ordered("decided_at", decided_at, "valid_until", valid_until)
        if self.context.evaluated_at > decided_at:
            raise SafetyContractError("context cannot be evaluated after the decision.")
        if self.readiness.as_of > as_of or self.readiness.evaluated_at > decided_at:
            raise SafetyContractError(
                "Safety decision cannot predate readiness evidence."
            )
        if decided_at == valid_until:
            raise SafetyContractError(
                "Safety decision validity window must be positive."
            )
        if not (self.policy.effective_at <= decided_at < self.policy.expires_at):
            raise SafetyContractError("Safety decision requires an effective policy.")
        if valid_until > self.policy.expires_at:
            raise SafetyContractError("Safety decision cannot outlive its policy.")
        if valid_until > self.readiness.valid_until:
            raise SafetyContractError(
                "Safety decision cannot outlive readiness evidence."
            )
        object.__setattr__(self, "decided_at", decided_at)
        object.__setattr__(self, "as_of", as_of)
        object.__setattr__(self, "valid_until", valid_until)
        _version("policy_version", self.policy_version)
        if self.policy_version != self.policy.version:
            raise SafetyContractError(
                "policy_version must match the exact SafetyPolicy."
            )
        _version("configuration_version", self.configuration_version)
        _digest("content_sha256", self.content_sha256)

        if self.decision is SafetyDecisionType.ALLOW and self.execution_adjacent:
            if self.readiness.status is not TradingReadinessStatus.READY:
                raise SafetyContractError("Execution-adjacent ALLOW requires READY.")
            if any(item.state is not KillSwitchState.INACTIVE for item in switches):
                raise SafetyContractError(
                    "ALLOW cannot coexist with an active kill switch."
                )
            if any(item.state is not CircuitBreakerState.CLOSED for item in breakers):
                raise SafetyContractError(
                    "ALLOW cannot coexist with an unsafe breaker."
                )
            if security or failures or injections or reconciliations:
                raise SafetyContractError(
                    "ALLOW cannot coexist with unresolved evidence."
                )
        if switches != self.readiness.kill_switches:
            raise SafetyContractError(
                "kill_switches must match the exact readiness evidence."
            )
        if breakers != self.readiness.circuit_breakers:
            raise SafetyContractError(
                "circuit_breakers must match the exact readiness evidence."
            )


@dataclass(frozen=True, slots=True)
class SecurityEvent:
    CONTRACT_ID: ClassVar[str] = "C-086"
    SCHEMA_VERSION: ClassVar[str] = CONTRACT_SCHEMA_VERSION

    event_id: UUID
    event_type: SecurityEventType
    severity: SecuritySeverity
    actor_ref: str
    source: str
    affected_resource: str
    action: str
    result: str
    detected_at: datetime
    occurred_at: datetime
    recorded_at: datetime
    correlation_id: str
    trace_id: str
    evidence_refs: tuple[EvidenceReference, ...]
    investigation_status: InvestigationStatus
    reason_codes: tuple[str, ...]
    source_version: VersionReference
    content_sha256: str
    audit_ref: ContractReference | None = None
    contract_id: str = field(default="C-086", init=False)
    schema_version: str = field(default=CONTRACT_SCHEMA_VERSION, init=False)

    def __post_init__(self) -> None:
        _uuid("event_id", self.event_id)
        _enum("event_type", self.event_type, SecurityEventType)
        _enum("severity", self.severity, SecuritySeverity)
        for name in (
            "actor_ref",
            "source",
            "affected_resource",
            "action",
            "result",
            "correlation_id",
            "trace_id",
        ):
            _text(name, getattr(self, name))
        occurred_at = _time("occurred_at", self.occurred_at)
        detected_at = _time("detected_at", self.detected_at)
        recorded_at = _time("recorded_at", self.recorded_at)
        _ordered("occurred_at", occurred_at, "detected_at", detected_at)
        _ordered("detected_at", detected_at, "recorded_at", recorded_at)
        object.__setattr__(self, "occurred_at", occurred_at)
        object.__setattr__(self, "detected_at", detected_at)
        object.__setattr__(self, "recorded_at", recorded_at)
        evidence = _typed_tuple("evidence_refs", self.evidence_refs, EvidenceReference)
        _unique("evidence identities", tuple(item.evidence_id for item in evidence))
        _enum("investigation_status", self.investigation_status, InvestigationStatus)
        reasons = _text_tuple("reason_codes", self.reason_codes, empty=False)
        _version("source_version", self.source_version)
        _digest("content_sha256", self.content_sha256)
        if self.audit_ref is not None:
            _reference("audit_ref", self.audit_ref, "C-060")
        if (
            self.severity
            in {
                SecuritySeverity.HIGH,
                SecuritySeverity.CRITICAL,
                SecuritySeverity.UNKNOWN,
            }
            and self.investigation_status is InvestigationStatus.CLOSED
            and not evidence
        ):
            raise SafetyContractError(
                "Critical/unknown closed event requires evidence."
            )
        if self.event_type is SecurityEventType.UNKNOWN and not reasons:
            raise SafetyContractError("Unknown security event requires reason_codes.")


@dataclass(frozen=True, slots=True)
class FailureEvent:
    CONTRACT_ID: ClassVar[str] = "C-087"
    SCHEMA_VERSION: ClassVar[str] = CONTRACT_SCHEMA_VERSION

    failure_id: UUID
    classification: FailureClassification
    operation_kind: FailureOperationKind
    source: str
    component: str
    operation: str
    affected_scope: str
    error_code: str
    reason_codes: tuple[str, ...]
    correlation_id: str
    trace_id: str
    detected_at: datetime
    occurred_at: datetime
    retry_safe: bool
    attempt_count: int
    state_known: bool
    reconciliation_required: bool
    evidence_refs: tuple[EvidenceReference, ...]
    source_version: VersionReference
    configuration_version: VersionReference
    content_sha256: str
    security_event_ref: ContractReference | None = None
    contract_id: str = field(default="C-087", init=False)
    schema_version: str = field(default=CONTRACT_SCHEMA_VERSION, init=False)

    def __post_init__(self) -> None:
        _uuid("failure_id", self.failure_id)
        _enum("classification", self.classification, FailureClassification)
        _enum("operation_kind", self.operation_kind, FailureOperationKind)
        for name in (
            "source",
            "component",
            "operation",
            "affected_scope",
            "error_code",
            "correlation_id",
            "trace_id",
        ):
            _text(name, getattr(self, name))
        _text_tuple("reason_codes", self.reason_codes, empty=False)
        occurred_at = _time("occurred_at", self.occurred_at)
        detected_at = _time("detected_at", self.detected_at)
        _ordered("occurred_at", occurred_at, "detected_at", detected_at)
        object.__setattr__(self, "occurred_at", occurred_at)
        object.__setattr__(self, "detected_at", detected_at)
        _bool("retry_safe", self.retry_safe)
        _nonnegative_int("attempt_count", self.attempt_count)
        _bool("state_known", self.state_known)
        _bool("reconciliation_required", self.reconciliation_required)
        evidence = _typed_tuple("evidence_refs", self.evidence_refs, EvidenceReference)
        _unique("evidence identities", tuple(item.evidence_id for item in evidence))
        _version("source_version", self.source_version)
        _version("configuration_version", self.configuration_version)
        _digest("content_sha256", self.content_sha256)
        if self.security_event_ref is not None:
            _reference("security_event_ref", self.security_event_ref, "C-086")
        if (
            self.operation_kind
            in {
                FailureOperationKind.FINANCIAL_SIDE_EFFECT,
                FailureOperationKind.UNKNOWN,
            }
            and self.retry_safe
        ):
            raise SafetyContractError(
                "Financial/unknown operation cannot be safely retried."
            )
        if self.classification is FailureClassification.UNKNOWN:
            if self.retry_safe or self.state_known or not self.reconciliation_required:
                raise SafetyContractError(
                    "Unknown failure must fail closed and reconcile."
                )
        if self.classification is FailureClassification.SECURITY_CRITICAL:
            if self.retry_safe or self.security_event_ref is None:
                raise SafetyContractError(
                    "Security-critical failure requires security evidence and no retry."
                )


@dataclass(frozen=True, slots=True)
class RecoveryAction:
    CONTRACT_ID: ClassVar[str] = "C-088"
    SCHEMA_VERSION: ClassVar[str] = CONTRACT_SCHEMA_VERSION

    recovery_id: UUID
    failure: FailureEvent
    action_type: RecoveryActionType
    status: RecoveryStatus
    target: str
    scope: str
    policy_ref: ContractReference
    authorization_ref: EvidenceReference | None
    idempotency_key: str | None
    side_effecting: bool
    retry_limit: int
    retry_count: int
    reconciliation_ref: ContractReference | None
    requested_at: datetime
    authorized_at: datetime | None
    started_at: datetime | None
    completed_at: datetime | None
    result_codes: tuple[str, ...]
    actor_ref: str
    blocks_affected_scope: bool
    evidence_refs: tuple[EvidenceReference, ...]
    source_version: VersionReference
    configuration_version: VersionReference
    content_sha256: str
    contract_id: str = field(default="C-088", init=False)
    schema_version: str = field(default=CONTRACT_SCHEMA_VERSION, init=False)

    def __post_init__(self) -> None:
        _uuid("recovery_id", self.recovery_id)
        if not isinstance(self.failure, FailureEvent):
            raise SafetyContractError("failure must be a FailureEvent.")
        _enum("action_type", self.action_type, RecoveryActionType)
        _enum("status", self.status, RecoveryStatus)
        _text("target", self.target)
        _text("scope", self.scope)
        _reference("policy_ref", self.policy_ref, "C-097")
        if self.authorization_ref is not None and not isinstance(
            self.authorization_ref, EvidenceReference
        ):
            raise SafetyContractError("authorization_ref must be an EvidenceReference.")
        if self.idempotency_key is not None:
            _text("idempotency_key", self.idempotency_key)
        _bool("side_effecting", self.side_effecting)
        _nonnegative_int("retry_limit", self.retry_limit)
        _nonnegative_int("retry_count", self.retry_count)
        if self.retry_count > self.retry_limit:
            raise SafetyContractError("retry_count must not exceed retry_limit.")
        if self.reconciliation_ref is not None:
            _reference("reconciliation_ref", self.reconciliation_ref, "C-096")
        requested_at = _time("requested_at", self.requested_at)
        authorized_at = _optional_time("authorized_at", self.authorized_at)
        started_at = _optional_time("started_at", self.started_at)
        completed_at = _optional_time("completed_at", self.completed_at)
        if authorized_at is not None:
            _ordered("requested_at", requested_at, "authorized_at", authorized_at)
        if started_at is not None:
            _ordered(
                "authorized_at" if authorized_at is not None else "requested_at",
                authorized_at or requested_at,
                "started_at",
                started_at,
            )
        if completed_at is not None:
            _ordered(
                "started_at" if started_at is not None else "requested_at",
                started_at or requested_at,
                "completed_at",
                completed_at,
            )
        object.__setattr__(self, "requested_at", requested_at)
        object.__setattr__(self, "authorized_at", authorized_at)
        object.__setattr__(self, "started_at", started_at)
        object.__setattr__(self, "completed_at", completed_at)
        results = _text_tuple("result_codes", self.result_codes)
        _text("actor_ref", self.actor_ref)
        _bool("blocks_affected_scope", self.blocks_affected_scope)
        evidence = _typed_tuple("evidence_refs", self.evidence_refs, EvidenceReference)
        _unique("evidence identities", tuple(item.evidence_id for item in evidence))
        _version("source_version", self.source_version)
        _version("configuration_version", self.configuration_version)
        _digest("content_sha256", self.content_sha256)

        if self.side_effecting and (
            self.authorization_ref is None or self.idempotency_key is None
        ):
            raise SafetyContractError(
                "Side-effecting recovery requires authorization and idempotency."
            )
        if self.action_type is RecoveryActionType.CONTROLLED_RETRY:
            if not self.failure.retry_safe or self.failure.operation_kind in {
                FailureOperationKind.FINANCIAL_SIDE_EFFECT,
                FailureOperationKind.UNKNOWN,
            }:
                raise SafetyContractError(
                    "Controlled retry is unsafe for this failure."
                )
        if (
            self.status
            in {
                RecoveryStatus.AUTHORIZED,
                RecoveryStatus.IN_PROGRESS,
                RecoveryStatus.SUCCEEDED,
            }
            and self.authorization_ref is None
        ):
            raise SafetyContractError(
                "Authorized/active/succeeded recovery needs authorization."
            )
        if self.status is RecoveryStatus.SUCCEEDED and (
            completed_at is None or not results or not evidence
        ):
            raise SafetyContractError("Succeeded recovery requires result evidence.")
        if (
            self.status
            in {
                RecoveryStatus.FAILED,
                RecoveryStatus.CANCELLED,
                RecoveryStatus.UNKNOWN,
            }
            and not self.blocks_affected_scope
        ):
            raise SafetyContractError(
                "Unsuccessful/unknown recovery must remain blocked."
            )


@dataclass(frozen=True, slots=True)
class PromptInjectionAssessment:
    CONTRACT_ID: ClassVar[str] = "C-089"
    SCHEMA_VERSION: ClassVar[str] = CONTRACT_SCHEMA_VERSION

    assessment_id: UUID
    untrusted_content_ref: EvidenceReference
    actor_ref: str
    agent_ref: str
    model_ref: str
    prompt_ref: str
    tool_context_ref: str
    verdict: PromptInjectionVerdict
    severity: SecuritySeverity
    indicators: tuple[str, ...]
    requested_effects: tuple[str, ...]
    required_responses: tuple[str, ...]
    blocks_tool_escalation: bool
    assessed_at: datetime
    as_of: datetime
    valid_until: datetime
    detector_version: VersionReference
    model_version: VersionReference
    prompt_version: VersionReference
    policy_version: VersionReference
    content_sha256: str
    contract_id: str = field(default="C-089", init=False)
    schema_version: str = field(default=CONTRACT_SCHEMA_VERSION, init=False)

    def __post_init__(self) -> None:
        _uuid("assessment_id", self.assessment_id)
        if not isinstance(self.untrusted_content_ref, EvidenceReference):
            raise SafetyContractError(
                "untrusted_content_ref must be an EvidenceReference."
            )
        for name in (
            "actor_ref",
            "agent_ref",
            "model_ref",
            "prompt_ref",
            "tool_context_ref",
        ):
            _text(name, getattr(self, name))
        _enum("verdict", self.verdict, PromptInjectionVerdict)
        _enum("severity", self.severity, SecuritySeverity)
        indicators = _text_tuple("indicators", self.indicators)
        effects = _text_tuple("requested_effects", self.requested_effects)
        responses = _text_tuple("required_responses", self.required_responses)
        _bool("blocks_tool_escalation", self.blocks_tool_escalation)
        assessed_at = _time("assessed_at", self.assessed_at)
        as_of = _time("as_of", self.as_of)
        valid_until = _time("valid_until", self.valid_until)
        _ordered("as_of", as_of, "assessed_at", assessed_at)
        _ordered("assessed_at", assessed_at, "valid_until", valid_until)
        if assessed_at == valid_until:
            raise SafetyContractError("Assessment validity window must be positive.")
        object.__setattr__(self, "assessed_at", assessed_at)
        object.__setattr__(self, "as_of", as_of)
        object.__setattr__(self, "valid_until", valid_until)
        for name in (
            "detector_version",
            "model_version",
            "prompt_version",
            "policy_version",
        ):
            _version(name, getattr(self, name))
        _digest("content_sha256", self.content_sha256)
        if self.verdict is not PromptInjectionVerdict.CLEAR:
            if not indicators or not responses or not self.blocks_tool_escalation:
                raise SafetyContractError(
                    "Suspicious/malicious/unknown assessment must fail closed."
                )
        elif self.severity in {
            SecuritySeverity.HIGH,
            SecuritySeverity.CRITICAL,
            SecuritySeverity.UNKNOWN,
        }:
            raise SafetyContractError(
                "CLEAR assessment cannot have critical/unknown severity."
            )
        if (
            effects
            and self.verdict is not PromptInjectionVerdict.CLEAR
            and not self.blocks_tool_escalation
        ):
            raise SafetyContractError("Unsafe requested effects must remain blocked.")


_PROHIBITED_AGENT_CAPABILITIES = {
    "HUMAN_TRADE_APPROVAL",
    "POLICY_OVERRIDE",
    "WITHDRAW_FUNDS",
    "TRANSFER_FUNDS",
    "UNRESTRICTED_CREDENTIAL_ACCESS",
    "ARBITRARY_TOOL_EXECUTION",
    "DIRECT_AI_ORDER_SUBMISSION",
}


@dataclass(frozen=True, slots=True)
class AgentPermissionPolicy:
    CONTRACT_ID: ClassVar[str] = "C-098"
    SCHEMA_VERSION: ClassVar[str] = CONTRACT_SCHEMA_VERSION

    policy_id: UUID
    name: str
    revision: int
    version: VersionReference
    agent_roles: tuple[str, ...]
    agent_identities: tuple[str, ...]
    grants: tuple[PermissionGrant, ...]
    denied_capabilities: tuple[str, ...]
    default_deny: bool
    environments: tuple[str, ...]
    modes: tuple[str, ...]
    effective_at: datetime
    expires_at: datetime
    created_at: datetime
    issuer_ref: str
    configuration_version: VersionReference
    content_sha256: str
    contract_id: str = field(default="C-098", init=False)
    schema_version: str = field(default=CONTRACT_SCHEMA_VERSION, init=False)

    def __post_init__(self) -> None:
        _uuid("policy_id", self.policy_id)
        _text("name", self.name)
        _positive_int("revision", self.revision)
        _version("version", self.version)
        _text_tuple("agent_roles", self.agent_roles, empty=False)
        _text_tuple("agent_identities", self.agent_identities)
        grants = _typed_tuple("grants", self.grants, PermissionGrant)
        _unique("grant identities", tuple(item.grant_id for item in grants))
        denied = _text_tuple(
            "denied_capabilities", self.denied_capabilities, empty=False
        )
        if not _PROHIBITED_AGENT_CAPABILITIES.issubset(set(denied)):
            raise SafetyContractError(
                "Agent policy must deny all prohibited capabilities."
            )
        for grant in grants:
            if grant.action in _PROHIBITED_AGENT_CAPABILITIES or grant.tool in {
                "ARBITRARY",
                "UNRESTRICTED",
            }:
                raise SafetyContractError("Agent grant contains prohibited authority.")
        _bool("default_deny", self.default_deny)
        if not self.default_deny:
            raise SafetyContractError("Agent permission policy must default deny.")
        _text_tuple("environments", self.environments, empty=False)
        _text_tuple("modes", self.modes, empty=False)
        effective_at = _time("effective_at", self.effective_at)
        expires_at = _time("expires_at", self.expires_at)
        created_at = _time("created_at", self.created_at)
        _ordered("created_at", created_at, "effective_at", effective_at)
        _ordered("effective_at", effective_at, "expires_at", expires_at)
        if effective_at == expires_at:
            raise SafetyContractError("Agent policy validity window must be positive.")
        object.__setattr__(self, "effective_at", effective_at)
        object.__setattr__(self, "expires_at", expires_at)
        object.__setattr__(self, "created_at", created_at)
        _text("issuer_ref", self.issuer_ref)
        _version("configuration_version", self.configuration_version)
        _digest("content_sha256", self.content_sha256)
        if any(
            not set(grant.environments).issubset(self.environments)
            or not set(grant.modes).issubset(self.modes)
            or grant.valid_from < self.effective_at
            or grant.valid_until > self.expires_at
            for grant in grants
        ):
            raise SafetyContractError("Permission grant exceeds its policy ceiling.")


@dataclass(frozen=True, slots=True)
class SafetyIncidentReport:
    CONTRACT_ID: ClassVar[str] = "C-099"
    SCHEMA_VERSION: ClassVar[str] = CONTRACT_SCHEMA_VERSION

    incident_id: UUID
    status: IncidentStatus
    severity: SecuritySeverity
    title: str
    category: str
    affected_scopes: tuple[str, ...]
    affected_resources: tuple[str, ...]
    security_event_refs: tuple[ContractReference, ...]
    failure_event_refs: tuple[ContractReference, ...]
    injection_assessment_refs: tuple[ContractReference, ...]
    other_evidence_refs: tuple[EvidenceReference, ...]
    containment_actions: tuple[str, ...]
    recovery_actions: tuple[RecoveryAction, ...]
    readiness_ref: ContractReference
    safety_decision_ref: ContractReference
    detected_at: datetime
    declared_at: datetime
    contained_at: datetime | None
    resolved_at: datetime | None
    closed_at: datetime | None
    owner_ref: str
    human_authorization_ref: EvidenceReference | None
    root_cause_codes: tuple[str, ...]
    remediation_codes: tuple[str, ...]
    blocks_critical_actions: bool
    policy_version: VersionReference
    configuration_version: VersionReference
    source_version: VersionReference
    content_sha256: str
    contract_id: str = field(default="C-099", init=False)
    schema_version: str = field(default=CONTRACT_SCHEMA_VERSION, init=False)

    def __post_init__(self) -> None:
        _uuid("incident_id", self.incident_id)
        _enum("status", self.status, IncidentStatus)
        _enum("severity", self.severity, SecuritySeverity)
        _text("title", self.title)
        _text("category", self.category)
        _text_tuple("affected_scopes", self.affected_scopes, empty=False)
        _text_tuple("affected_resources", self.affected_resources, empty=False)
        security = _references(
            "security_event_refs", self.security_event_refs, contract_id="C-086"
        )
        failures = _references(
            "failure_event_refs", self.failure_event_refs, contract_id="C-087"
        )
        injections = _references(
            "injection_assessment_refs",
            self.injection_assessment_refs,
            contract_id="C-089",
        )
        other = _typed_tuple(
            "other_evidence_refs", self.other_evidence_refs, EvidenceReference
        )
        _unique("other evidence identities", tuple(item.evidence_id for item in other))
        if not (security or failures or injections or other):
            raise SafetyContractError("Incident requires originating evidence.")
        containment = _text_tuple("containment_actions", self.containment_actions)
        recoveries = _typed_tuple(
            "recovery_actions", self.recovery_actions, RecoveryAction
        )
        _unique("recovery identities", tuple(item.recovery_id for item in recoveries))
        _reference("readiness_ref", self.readiness_ref, "C-059")
        _reference("safety_decision_ref", self.safety_decision_ref, "C-058")
        detected_at = _time("detected_at", self.detected_at)
        declared_at = _time("declared_at", self.declared_at)
        contained_at = _optional_time("contained_at", self.contained_at)
        resolved_at = _optional_time("resolved_at", self.resolved_at)
        closed_at = _optional_time("closed_at", self.closed_at)
        _ordered("detected_at", detected_at, "declared_at", declared_at)
        previous_name = "declared_at"
        previous = declared_at
        for name, value in (
            ("contained_at", contained_at),
            ("resolved_at", resolved_at),
            ("closed_at", closed_at),
        ):
            if value is not None:
                _ordered(previous_name, previous, name, value)
                previous_name, previous = name, value
        object.__setattr__(self, "detected_at", detected_at)
        object.__setattr__(self, "declared_at", declared_at)
        object.__setattr__(self, "contained_at", contained_at)
        object.__setattr__(self, "resolved_at", resolved_at)
        object.__setattr__(self, "closed_at", closed_at)
        _text("owner_ref", self.owner_ref)
        if self.human_authorization_ref is not None and not isinstance(
            self.human_authorization_ref, EvidenceReference
        ):
            raise SafetyContractError(
                "human_authorization_ref must be an EvidenceReference."
            )
        roots = _text_tuple("root_cause_codes", self.root_cause_codes)
        remediations = _text_tuple("remediation_codes", self.remediation_codes)
        _bool("blocks_critical_actions", self.blocks_critical_actions)
        for name in ("policy_version", "configuration_version", "source_version"):
            _version(name, getattr(self, name))
        _digest("content_sha256", self.content_sha256)

        if self.status in {IncidentStatus.CONTAINED, IncidentStatus.RECOVERING} and (
            contained_at is None or not containment
        ):
            raise SafetyContractError(
                "Contained/recovering incident needs containment evidence."
            )
        if self.status in {IncidentStatus.RESOLVED, IncidentStatus.CLOSED}:
            if (
                contained_at is None
                or resolved_at is None
                or not containment
                or not recoveries
                or any(
                    item.status is not RecoveryStatus.SUCCEEDED for item in recoveries
                )
                or not roots
                or not remediations
            ):
                raise SafetyContractError(
                    "Resolved/closed incident needs recovery evidence."
                )
        if self.status is IncidentStatus.CLOSED and closed_at is None:
            raise SafetyContractError("Closed incident requires closed_at.")
        if self.severity in {
            SecuritySeverity.HIGH,
            SecuritySeverity.CRITICAL,
            SecuritySeverity.UNKNOWN,
        } and self.status not in {IncidentStatus.RESOLVED, IncidentStatus.CLOSED}:
            if not self.blocks_critical_actions:
                raise SafetyContractError(
                    "Unresolved critical/unknown incident must block."
                )


__all__ = [
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
]
