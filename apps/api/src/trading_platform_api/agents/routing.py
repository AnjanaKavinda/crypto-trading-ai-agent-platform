from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Protocol, runtime_checkable

from trading_platform_api.agents.contracts import (
    AgentContractError,
    FallbackPolicy,
    ModelAvailability,
    ModelRequest,
    ModelResponse,
    ModelRoute,
    ModelRoutingDecision,
    ModelRoutingPolicy,
)
from trading_platform_api.contracts.serialization import canonical_sha256


class ModelRoutingError(ValueError):
    """Raised when a route or provider invocation cannot be safely resolved."""


_SENSITIVE = re.compile(
    r"(?i)(api[-_ ]?key|authorization|password|secret|token)\s*[:=]"
)


def _safe_identifier(name: str, value: object) -> str:
    if (
        not isinstance(value, str)
        or not value.strip()
        or value != value.strip()
        or len(value) > 255
        or any(ord(char) < 32 for char in value)
        or _SENSITIVE.search(value)
    ):
        raise ModelRoutingError(f"{name} must be safe non-blank text.")
    return value


@dataclass(frozen=True, slots=True)
class ProviderAvailabilityEvidence:
    provider_id: str
    model_id: str
    status: ModelAvailability
    evidence_reference: str
    checked_at: datetime
    valid_until: datetime

    def __post_init__(self) -> None:
        for name in ("provider_id", "model_id", "evidence_reference"):
            _safe_identifier(name, getattr(self, name))
        if not isinstance(self.status, ModelAvailability):
            raise ModelRoutingError("availability status is invalid.")
        for name in ("checked_at", "valid_until"):
            value = getattr(self, name)
            if not isinstance(value, datetime) or value.tzinfo is None:
                raise ModelRoutingError(f"{name} must be timezone-aware.")
            object.__setattr__(self, name, value.astimezone(UTC))
        if self.valid_until <= self.checked_at:
            raise ModelRoutingError(
                "availability evidence must have positive validity."
            )


@runtime_checkable
class ModelProvider(Protocol):
    """Provider adapter boundary; implementations obtain secrets outside contracts."""

    @property
    def provider_id(self) -> str: ...

    async def generate(self, request: ModelRequest) -> ModelResponse: ...


def resolve_model_route(
    *,
    policy: ModelRoutingPolicy,
    request: ModelRequest,
    availability: ProviderAvailabilityEvidence,
    now: datetime,
    remaining_budget_usd: Decimal,
) -> ModelRoutingDecision:
    """Resolve an exact allowlisted route or fail closed; never downgrade/fallback."""

    if not isinstance(policy, ModelRoutingPolicy):
        raise ModelRoutingError("policy must be a ModelRoutingPolicy.")
    if not isinstance(request, ModelRequest):
        raise ModelRoutingError("request must be a ModelRequest.")
    if not isinstance(availability, ProviderAvailabilityEvidence):
        raise ModelRoutingError("fresh provider availability evidence is required.")
    if not isinstance(now, datetime) or now.tzinfo is None:
        raise ModelRoutingError("now must be timezone-aware.")
    decision_time = now.astimezone(UTC)
    if decision_time >= policy.valid_until:
        raise ModelRoutingError("routing policy is expired.")
    if (
        decision_time < availability.checked_at
        or decision_time >= availability.valid_until
    ):
        raise ModelRoutingError(
            "provider availability evidence is stale or future-dated."
        )
    if availability.status is not ModelAvailability.AVAILABLE:
        raise ModelRoutingError("provider/model is not affirmatively available.")

    route = next(
        (
            item
            for item in policy.routes
            if item.capability_tier is request.capability_tier
        ),
        None,
    )
    if route is None:
        raise ModelRoutingError("no approved route exists for the requested tier.")
    if request.workload_id not in route.approved_workloads:
        raise ModelRoutingError("workload is not approved for the selected route.")
    if (
        request.prompt_id != route.prompt_id
        or request.prompt_version != route.prompt_version
    ):
        raise ModelRoutingError("request prompt does not match the approved route.")
    if request.requested_input_tokens > route.max_input_tokens:
        raise ModelRoutingError("request exceeds the approved input-token bound.")
    if request.requested_output_tokens > route.max_output_tokens:
        raise ModelRoutingError("request exceeds the approved output-token bound.")
    if (
        not isinstance(remaining_budget_usd, Decimal)
        or not remaining_budget_usd.is_finite()
        or remaining_budget_usd < route.max_request_cost_usd
    ):
        raise ModelRoutingError("remaining budget is below the route's maximum cost.")
    if (
        availability.provider_id != route.provider_id
        or availability.model_id != route.model_id
    ):
        raise ModelRoutingError(
            "availability evidence does not match the selected route."
        )

    try:
        return ModelRoutingDecision(
            request_id=request.request_id,
            request_sha256=request.request_sha256,
            workload_id=request.workload_id,
            capability_tier=route.capability_tier,
            provider_id=route.provider_id,
            model_id=route.model_id,
            model_version=route.model_version,
            prompt_id=route.prompt_id,
            prompt_version=route.prompt_version,
            policy_id=policy.policy_id,
            policy_version=policy.policy_version,
            decided_at=decision_time,
            expires_at=min(policy.valid_until, availability.valid_until),
            max_input_tokens=route.max_input_tokens,
            max_output_tokens=route.max_output_tokens,
            max_request_cost_usd=route.max_request_cost_usd,
            availability=availability.status,
            availability_reference=availability.evidence_reference,
            availability_checked_at=availability.checked_at,
            fallback_policy=FallbackPolicy.DENY,
        )
    except AgentContractError:
        raise ModelRoutingError("resolved route failed contract validation.") from None


async def invoke_provider(
    *,
    provider: ModelProvider,
    decision: ModelRoutingDecision,
    request: ModelRequest,
    now: datetime,
) -> ModelResponse:
    """Make one bounded provider call and reject mismatched or over-budget results."""

    if not isinstance(decision, ModelRoutingDecision):
        raise ModelRoutingError("decision must be a validated C-067 record.")
    if not isinstance(request, ModelRequest):
        raise ModelRoutingError("request must be a ModelRequest.")
    if not isinstance(now, datetime) or now.tzinfo is None:
        raise ModelRoutingError("now must be timezone-aware.")
    instant = now.astimezone(UTC)
    if decision.fallback_policy is not FallbackPolicy.DENY:
        raise ModelRoutingError("automatic fallback is prohibited.")
    if decision.availability is not ModelAvailability.AVAILABLE:
        raise ModelRoutingError("provider availability is not validated.")
    if (
        decision.availability_checked_at is None
        or decision.availability_checked_at > instant
        or instant < decision.decided_at
        or decision.expires_at <= instant
    ):
        raise ModelRoutingError("route or availability evidence is stale.")
    if (
        request.request_id != decision.request_id
        or canonical_sha256(request) != decision.request_sha256
        or request.workload_id != decision.workload_id
        or request.capability_tier is not decision.capability_tier
        or request.prompt_id != decision.prompt_id
        or request.prompt_version != decision.prompt_version
    ):
        raise ModelRoutingError("request is not bound to the routing decision.")
    if (
        request.requested_input_tokens > decision.max_input_tokens
        or request.requested_output_tokens > decision.max_output_tokens
    ):
        raise ModelRoutingError("request exceeds the decision's token bounds.")
    if provider.provider_id != decision.provider_id:
        raise ModelRoutingError("provider adapter does not match the routing decision.")

    try:
        response = await provider.generate(request)
    except Exception:
        raise ModelRoutingError(
            "provider call failed; no retry or fallback was attempted."
        ) from None
    if not isinstance(response, ModelResponse):
        raise ModelRoutingError("provider returned an invalid response type.")
    if (
        response.request_id != decision.request_id
        or response.provider_id != decision.provider_id
        or response.model_id != decision.model_id
    ):
        raise ModelRoutingError(
            "provider response identity does not match the decision."
        )
    if response.returned_model_version != decision.model_version:
        raise ModelRoutingError("provider returned an unapproved model version.")
    if (
        response.started_at < decision.decided_at
        or response.completed_at > decision.expires_at
    ):
        raise ModelRoutingError(
            "provider response timestamps are outside the invocation."
        )
    if response.availability is not ModelAvailability.AVAILABLE:
        raise ModelRoutingError("provider response is degraded or unavailable.")
    if response.input_tokens > decision.max_input_tokens:
        raise ModelRoutingError("provider response exceeds the input-token bound.")
    if response.output_tokens > decision.max_output_tokens:
        raise ModelRoutingError("provider response exceeds the output-token bound.")
    if response.actual_cost_usd is None:
        raise ModelRoutingError("provider cost is unknown; budget cannot be verified.")
    if response.actual_cost_usd > decision.max_request_cost_usd:
        raise ModelRoutingError("provider response exceeds the request-cost ceiling.")
    return response
