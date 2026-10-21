from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from typing import ClassVar
from uuid import UUID

from trading_platform_api.risk import ContractReference
from trading_platform_api.safety import AgentPermissionPolicy

CONTRACT_SCHEMA_VERSION = "1"
_SENSITIVE = re.compile(
    r"(?i)(api[-_ ]?key|authorization|password|secret|token)\s*[:=]|"
    r"\bbearer\s+\S+|://[^/\s:@]+:[^/\s@]+@"
)


class AgentContractError(ValueError):
    """Raised when an agent or routing contract is invalid."""


class ModelCapabilityTier(StrEnum):
    ECONOMICAL_FAST = "economical-fast"
    STRONG_CODING_REASONING = "strong-coding-reasoning"
    PREMIUM_STRONGEST_AVAILABLE = "premium-strongest-available"


class ModelAvailability(StrEnum):
    AVAILABLE = "AVAILABLE"
    DEGRADED = "DEGRADED"
    UNAVAILABLE = "UNAVAILABLE"
    UNKNOWN = "UNKNOWN"


class FallbackPolicy(StrEnum):
    DENY = "DENY"


class AgentResultStatus(StrEnum):
    COMPLETE = "COMPLETE"
    PARTIAL = "PARTIAL"
    NO_TRADE = "NO_TRADE"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"


@dataclass(frozen=True, slots=True)
class AgentDefinition:
    """C-061 immutable role metadata; it does not grant runtime permissions."""

    agent_id: str
    agent_version: str
    role: str
    purpose: str
    allowed_inputs: tuple[str, ...]
    allowed_outputs: tuple[str, ...]
    allowed_tools: tuple[str, ...]
    allowed_modes: tuple[str, ...]
    dependencies: tuple[str, ...]
    authority_boundaries: tuple[str, ...]
    contract_id: str = field(default="C-061", init=False)
    schema_version: str = field(default=CONTRACT_SCHEMA_VERSION, init=False)

    __contract_id__: ClassVar[str] = "C-061"

    def __post_init__(self) -> None:
        for name in ("agent_id", "agent_version", "role", "purpose"):
            _text(name, getattr(self, name))
        for name in (
            "allowed_inputs",
            "allowed_outputs",
            "allowed_tools",
            "allowed_modes",
            "dependencies",
            "authority_boundaries",
        ):
            values = getattr(self, name)
            if not isinstance(values, tuple):
                raise AgentContractError(f"{name} must be a tuple.")
            normalized = tuple(_text(f"{name} item", value) for value in values)
            if len(set(normalized)) != len(normalized):
                raise AgentContractError(f"{name} must not contain duplicates.")
            object.__setattr__(self, name, normalized)
        if not self.allowed_inputs or not self.allowed_outputs:
            raise AgentContractError("agent inputs and outputs must be declared.")
        if not self.allowed_modes or not self.authority_boundaries:
            raise AgentContractError(
                "agent modes and authority boundaries are required."
            )

    @property
    def permissions_granted(self) -> bool:
        """C-061 is descriptive only; C-063/C-064 govern runtime grants."""

        return False


@dataclass(frozen=True, slots=True)
class AgentPermissionProfile:
    """C-063 runtime scope bound to one definition and one C-098 ceiling."""

    profile_id: UUID
    agent_id: str
    agent_version: str
    role: str
    environment: str
    mode: str
    policy: AgentPermissionPolicy
    tool_access_ids: tuple[UUID, ...]
    valid_from: datetime
    valid_until: datetime
    revision: int = 1
    revoked_at: datetime | None = None
    revocation_audit_ref: ContractReference | None = None
    contract_id: str = field(default="C-063", init=False)
    schema_version: str = field(default=CONTRACT_SCHEMA_VERSION, init=False)

    __contract_id__: ClassVar[str] = "C-063"

    def __post_init__(self) -> None:
        if not isinstance(self.profile_id, UUID):
            raise AgentContractError("profile_id must be a UUID.")
        for name in ("agent_id", "agent_version", "role", "environment", "mode"):
            _text(name, getattr(self, name))
        if not isinstance(self.policy, AgentPermissionPolicy):
            raise AgentContractError("policy must be a validated C-098 policy.")
        if self.role not in self.policy.agent_roles:
            raise AgentContractError("profile role exceeds the C-098 policy.")
        if self.policy.agent_identities and (
            f"{self.agent_id}@{self.agent_version}" not in self.policy.agent_identities
        ):
            raise AgentContractError("profile identity exceeds the C-098 policy.")
        if self.environment not in self.policy.environments:
            raise AgentContractError("profile environment exceeds the C-098 policy.")
        if self.mode not in self.policy.modes:
            raise AgentContractError("profile mode exceeds the C-098 policy.")
        if not isinstance(self.tool_access_ids, tuple) or any(
            not isinstance(item, UUID) for item in self.tool_access_ids
        ):
            raise AgentContractError("tool_access_ids must be a tuple of UUIDs.")
        if len(set(self.tool_access_ids)) != len(self.tool_access_ids):
            raise AgentContractError("tool_access_ids must not contain duplicates.")
        _positive_int("revision", self.revision)
        valid_from = _utc("valid_from", self.valid_from)
        valid_until = _utc("valid_until", self.valid_until)
        if valid_from >= valid_until:
            raise AgentContractError("profile validity window must be positive.")
        if (
            valid_from < self.policy.effective_at
            or valid_until > self.policy.expires_at
        ):
            raise AgentContractError("profile validity exceeds the C-098 policy.")
        revoked_at = (
            None if self.revoked_at is None else _utc("revoked_at", self.revoked_at)
        )
        if (revoked_at is None) != (self.revocation_audit_ref is None):
            raise AgentContractError("revocation requires a C-060 audit reference.")
        if revoked_at is not None and not valid_from <= revoked_at < valid_until:
            raise AgentContractError("revocation time is outside the profile window.")
        if revoked_at is not None:
            if not isinstance(self.revocation_audit_ref, ContractReference):
                raise AgentContractError(
                    "revocation reference must be a contract reference."
                )
            if self.revocation_audit_ref.contract_id != "C-060":
                raise AgentContractError("revocation reference must target C-060.")
        object.__setattr__(self, "valid_from", valid_from)
        object.__setattr__(self, "valid_until", valid_until)
        object.__setattr__(self, "revoked_at", revoked_at)


@dataclass(frozen=True, slots=True)
class AgentToolAccess:
    """C-064 immutable, exact-scope, revocable access to one tool/resource."""

    access_id: UUID
    profile_id: UUID
    grant_id: str
    tool: str
    resource: str
    action: str
    environment: str
    mode: str
    valid_from: datetime
    valid_until: datetime
    revision: int = 1
    revoked_at: datetime | None = None
    revocation_audit_ref: ContractReference | None = None
    contract_id: str = field(default="C-064", init=False)
    schema_version: str = field(default=CONTRACT_SCHEMA_VERSION, init=False)

    __contract_id__: ClassVar[str] = "C-064"

    def __post_init__(self) -> None:
        if not isinstance(self.access_id, UUID) or not isinstance(
            self.profile_id, UUID
        ):
            raise AgentContractError("access and profile IDs must be UUIDs.")
        for name in (
            "grant_id",
            "tool",
            "resource",
            "action",
            "environment",
            "mode",
        ):
            value = _text(name, getattr(self, name))
            if value in {"*", "ANY", "UNRESTRICTED", "ARBITRARY"}:
                raise AgentContractError(f"{name} must use an exact scope.")
        valid_from = _utc("valid_from", self.valid_from)
        valid_until = _utc("valid_until", self.valid_until)
        if valid_from >= valid_until:
            raise AgentContractError("tool access validity window must be positive.")
        _positive_int("revision", self.revision)
        revoked_at = (
            None if self.revoked_at is None else _utc("revoked_at", self.revoked_at)
        )
        if (revoked_at is None) != (self.revocation_audit_ref is None):
            raise AgentContractError("revocation requires a C-060 audit reference.")
        if revoked_at is not None:
            if not valid_from <= revoked_at < valid_until:
                raise AgentContractError(
                    "revocation time is outside the access window."
                )
            if not isinstance(self.revocation_audit_ref, ContractReference):
                raise AgentContractError(
                    "revocation reference must be a contract reference."
                )
            if self.revocation_audit_ref.contract_id != "C-060":
                raise AgentContractError("revocation reference must target C-060.")
        object.__setattr__(self, "valid_from", valid_from)
        object.__setattr__(self, "valid_until", valid_until)
        object.__setattr__(self, "revoked_at", revoked_at)


@dataclass(frozen=True, slots=True)
class AgentResult:
    """C-062 result bound to one task, context, route, and typed output."""

    result_id: UUID
    task_id: UUID
    context_id: UUID
    agent_id: str
    agent_version: str
    routing_decision: ModelRoutingDecision
    tool_access_ids: tuple[UUID, ...]
    generated_at: datetime
    expires_at: datetime
    status: AgentResultStatus
    confidence: Decimal | None
    supporting_evidence_ids: tuple[UUID, ...]
    contradicting_evidence_ids: tuple[UUID, ...]
    unresolved_risks: tuple[str, ...]
    output: object
    contract_id: str = field(default="C-062", init=False)
    schema_version: str = field(default=CONTRACT_SCHEMA_VERSION, init=False)

    __contract_id__: ClassVar[str] = "C-062"

    def __post_init__(self) -> None:
        if not isinstance(self.result_id, UUID):
            raise AgentContractError("result_id must be a UUID.")
        if not isinstance(self.task_id, UUID) or not isinstance(self.context_id, UUID):
            raise AgentContractError("task_id and context_id must be UUIDs.")
        for name in ("agent_id", "agent_version"):
            _text(name, getattr(self, name))
        if not isinstance(self.routing_decision, ModelRoutingDecision):
            raise AgentContractError("routing_decision must be a validated C-067.")
        if not isinstance(self.tool_access_ids, tuple) or any(
            not isinstance(item, UUID) for item in self.tool_access_ids
        ):
            raise AgentContractError("tool_access_ids must be a tuple of UUIDs.")
        if len(set(self.tool_access_ids)) != len(self.tool_access_ids):
            raise AgentContractError("tool_access_ids must not contain duplicates.")
        generated_at = _utc("generated_at", self.generated_at)
        expires_at = _utc("expires_at", self.expires_at)
        if expires_at <= generated_at:
            raise AgentContractError("expires_at must be later than generated_at.")
        object.__setattr__(self, "generated_at", generated_at)
        object.__setattr__(self, "expires_at", expires_at)
        if not isinstance(self.status, AgentResultStatus):
            raise AgentContractError("status must be a known AgentResultStatus.")
        if self.confidence is not None and (
            not isinstance(self.confidence, Decimal)
            or not self.confidence.is_finite()
            or not Decimal(0) <= self.confidence <= Decimal(1)
        ):
            raise AgentContractError("confidence must be a finite Decimal from 0 to 1.")
        for name in ("supporting_evidence_ids", "contradicting_evidence_ids"):
            values = getattr(self, name)
            if not isinstance(values, tuple) or any(
                not isinstance(item, UUID) for item in values
            ):
                raise AgentContractError(f"{name} must be a tuple of UUIDs.")
            if len(set(values)) != len(values):
                raise AgentContractError(f"{name} must not contain duplicates.")
        if (
            self.confidence not in (None, Decimal(0))
            and not self.supporting_evidence_ids
        ):
            raise AgentContractError(
                "non-zero confidence requires supporting evidence."
            )
        if not isinstance(self.unresolved_risks, tuple):
            raise AgentContractError("unresolved_risks must be a tuple.")
        for risk in self.unresolved_risks:
            _text("unresolved_risk", risk)
        if self.status is AgentResultStatus.NO_TRADE and not self.unresolved_risks:
            raise AgentContractError("NO_TRADE results must state an unresolved risk.")


def _text(name: str, value: object, *, maximum: int = 255) -> str:
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise AgentContractError(f"{name} must be non-blank trimmed text.")
    if len(value) > maximum:
        raise AgentContractError(f"{name} must not exceed {maximum} characters.")
    if any(ord(char) < 32 for char in value):
        raise AgentContractError(f"{name} must not contain control characters.")
    if _SENSITIVE.search(value):
        raise AgentContractError(f"{name} must not contain credentials or secrets.")
    return value


def _utc(name: str, value: object) -> datetime:
    if (
        not isinstance(value, datetime)
        or value.tzinfo is None
        or value.utcoffset() is None
    ):
        raise AgentContractError(f"{name} must be timezone-aware.")
    return value.astimezone(UTC)


def _positive_int(name: str, value: object) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise AgentContractError(f"{name} must be a positive integer.")
    return value


def _non_negative_decimal(name: str, value: object) -> Decimal:
    if not isinstance(value, Decimal) or not value.is_finite() or value < 0:
        raise AgentContractError(f"{name} must be a finite non-negative Decimal.")
    return value


@dataclass(frozen=True, slots=True)
class ModelRoute:
    """An explicit, non-secret, workload-validated provider/model mapping."""

    capability_tier: ModelCapabilityTier
    provider_id: str
    model_id: str
    model_version: str
    prompt_id: str
    prompt_version: str
    policy_id: str
    policy_version: str
    approved_workloads: tuple[str, ...]
    max_input_tokens: int
    max_output_tokens: int
    max_request_cost_usd: Decimal

    def __post_init__(self) -> None:
        if not isinstance(self.capability_tier, ModelCapabilityTier):
            raise AgentContractError("capability_tier must be a ModelCapabilityTier.")
        for name in (
            "provider_id",
            "model_id",
            "model_version",
            "prompt_id",
            "prompt_version",
            "policy_id",
            "policy_version",
        ):
            _text(name, getattr(self, name))
        if (
            not isinstance(self.approved_workloads, tuple)
            or not self.approved_workloads
        ):
            raise AgentContractError("approved_workloads must be a non-empty tuple.")
        workloads = tuple(
            _text("approved_workload", item) for item in self.approved_workloads
        )
        if len(set(workloads)) != len(workloads):
            raise AgentContractError("approved_workloads must not contain duplicates.")
        _positive_int("max_input_tokens", self.max_input_tokens)
        _positive_int("max_output_tokens", self.max_output_tokens)
        _non_negative_decimal("max_request_cost_usd", self.max_request_cost_usd)


@dataclass(frozen=True, slots=True)
class ModelRoutingPolicy:
    """Explicit route allowlist; absent tiers never receive an implicit default."""

    policy_id: str
    policy_version: str
    routes: tuple[ModelRoute, ...]
    valid_until: datetime

    def __post_init__(self) -> None:
        _text("policy_id", self.policy_id)
        _text("policy_version", self.policy_version)
        if not isinstance(self.routes, tuple) or not self.routes:
            raise AgentContractError("routes must be a non-empty tuple.")
        if not all(isinstance(route, ModelRoute) for route in self.routes):
            raise AgentContractError("routes must contain ModelRoute values.")
        tiers = tuple(route.capability_tier for route in self.routes)
        if len(set(tiers)) != len(tiers):
            raise AgentContractError("policy must define at most one route per tier.")
        if any(route.policy_id != self.policy_id for route in self.routes):
            raise AgentContractError("every route must reference this policy_id.")
        if any(route.policy_version != self.policy_version for route in self.routes):
            raise AgentContractError("every route must reference this policy_version.")
        object.__setattr__(self, "valid_until", _utc("valid_until", self.valid_until))


@dataclass(frozen=True, slots=True)
class ModelRoutingDecision:
    """Canonical C-067 record of an explicit model route selection."""

    request_id: UUID
    request_sha256: str
    workload_id: str
    capability_tier: ModelCapabilityTier
    provider_id: str
    model_id: str
    model_version: str
    prompt_id: str
    prompt_version: str
    policy_id: str
    policy_version: str
    decided_at: datetime
    expires_at: datetime
    max_input_tokens: int
    max_output_tokens: int
    max_request_cost_usd: Decimal
    availability: ModelAvailability = ModelAvailability.UNKNOWN
    availability_reference: str | None = None
    availability_checked_at: datetime | None = None
    fallback_policy: FallbackPolicy = FallbackPolicy.DENY
    contract_id: str = field(default="C-067", init=False)
    schema_version: str = field(default=CONTRACT_SCHEMA_VERSION, init=False)

    __contract_id__: ClassVar[str] = "C-067"

    def __post_init__(self) -> None:
        if not isinstance(self.request_id, UUID):
            raise AgentContractError("request_id must be a UUID.")
        if re.fullmatch(r"[0-9a-f]{64}", self.request_sha256) is None:
            raise AgentContractError(
                "request_sha256 must be a lowercase SHA-256 digest."
            )
        for name in (
            "workload_id",
            "provider_id",
            "model_id",
            "model_version",
            "prompt_id",
            "prompt_version",
            "policy_id",
            "policy_version",
        ):
            _text(name, getattr(self, name))
        if not isinstance(self.capability_tier, ModelCapabilityTier):
            raise AgentContractError("capability_tier must be a ModelCapabilityTier.")
        if not isinstance(self.availability, ModelAvailability):
            raise AgentContractError("availability must be a ModelAvailability.")
        if not isinstance(self.fallback_policy, FallbackPolicy):
            raise AgentContractError("fallback_policy must be a FallbackPolicy.")
        if self.availability is ModelAvailability.UNKNOWN:
            if (
                self.availability_reference is not None
                or self.availability_checked_at is not None
            ):
                raise AgentContractError(
                    "unknown availability must not claim evidence or a check time."
                )
        else:
            _text("availability_reference", self.availability_reference)
            object.__setattr__(
                self,
                "availability_checked_at",
                _utc("availability_checked_at", self.availability_checked_at),
            )
        decided_at = _utc("decided_at", self.decided_at)
        expires_at = _utc("expires_at", self.expires_at)
        if expires_at <= decided_at:
            raise AgentContractError("expires_at must be later than decided_at.")
        object.__setattr__(self, "decided_at", decided_at)
        object.__setattr__(self, "expires_at", expires_at)
        _positive_int("max_input_tokens", self.max_input_tokens)
        _positive_int("max_output_tokens", self.max_output_tokens)
        _non_negative_decimal("max_request_cost_usd", self.max_request_cost_usd)


@dataclass(frozen=True, slots=True)
class ModelRequest:
    """Bounded prompt request sent only to an explicitly selected provider."""

    request_id: UUID
    workload_id: str
    capability_tier: ModelCapabilityTier
    prompt_id: str
    prompt_version: str
    content: str
    requested_input_tokens: int
    requested_output_tokens: int

    def __post_init__(self) -> None:
        if not isinstance(self.request_id, UUID):
            raise AgentContractError("request_id must be a UUID.")
        for name in ("workload_id", "prompt_id", "prompt_version"):
            _text(name, getattr(self, name))
        _text("content", self.content, maximum=1_000_000)
        if not isinstance(self.capability_tier, ModelCapabilityTier):
            raise AgentContractError("capability_tier must be a ModelCapabilityTier.")
        _positive_int("requested_input_tokens", self.requested_input_tokens)
        _positive_int("requested_output_tokens", self.requested_output_tokens)

    @property
    def request_sha256(self) -> str:
        """Digest the complete immutable request without persisting prompt text."""

        from trading_platform_api.contracts.serialization import canonical_sha256

        return canonical_sha256(self)


@dataclass(frozen=True, slots=True)
class ModelResponse:
    """Untrusted provider output plus usage and timing metadata."""

    request_id: UUID
    provider_id: str
    model_id: str
    returned_model_version: str | None
    content: str
    started_at: datetime
    completed_at: datetime
    input_tokens: int
    output_tokens: int
    actual_cost_usd: Decimal | None
    availability: ModelAvailability

    def __post_init__(self) -> None:
        if not isinstance(self.request_id, UUID):
            raise AgentContractError("request_id must be a UUID.")
        for name in ("provider_id", "model_id"):
            _text(name, getattr(self, name))
        if self.returned_model_version is not None:
            _text("returned_model_version", self.returned_model_version)
        _text("content", self.content, maximum=1_000_000)
        started_at = _utc("started_at", self.started_at)
        completed_at = _utc("completed_at", self.completed_at)
        if completed_at < started_at:
            raise AgentContractError("completed_at must not precede started_at.")
        object.__setattr__(self, "started_at", started_at)
        object.__setattr__(self, "completed_at", completed_at)
        _positive_int("input_tokens", self.input_tokens)
        _positive_int("output_tokens", self.output_tokens)
        if self.actual_cost_usd is not None:
            _non_negative_decimal("actual_cost_usd", self.actual_cost_usd)
        if not isinstance(self.availability, ModelAvailability):
            raise AgentContractError("availability must be a ModelAvailability.")
