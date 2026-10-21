from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from trading_platform_api.agents import (
    ModelAvailability,
    ModelCapabilityTier,
    ModelRequest,
    ModelResponse,
    ModelRoute,
    ModelRoutingError,
    ModelRoutingPolicy,
    ProviderAvailabilityEvidence,
    invoke_provider,
    resolve_model_route,
)

NOW = datetime(2026, 10, 21, 4, 0, tzinfo=UTC)


def request() -> ModelRequest:
    return ModelRequest(
        request_id=uuid4(),
        workload_id="spot-research-summary-v1",
        capability_tier=ModelCapabilityTier.ECONOMICAL_FAST,
        prompt_id="spot-summary",
        prompt_version="1",
        content="Summarize the supplied evidence without issuing a trade instruction.",
        requested_input_tokens=500,
        requested_output_tokens=100,
    )


def route() -> ModelRoute:
    return ModelRoute(
        capability_tier=ModelCapabilityTier.ECONOMICAL_FAST,
        provider_id="approved-provider",
        model_id="approved-model",
        model_version="2026-10-01",
        prompt_id="spot-summary",
        prompt_version="1",
        policy_id="personal-spot-model-policy",
        policy_version="1",
        approved_workloads=("spot-research-summary-v1",),
        max_input_tokens=1000,
        max_output_tokens=200,
        max_request_cost_usd=Decimal("0.10"),
    )


def policy() -> ModelRoutingPolicy:
    return ModelRoutingPolicy(
        policy_id="personal-spot-model-policy",
        policy_version="1",
        routes=(route(),),
        valid_until=NOW + timedelta(hours=1),
    )


def availability(
    status: ModelAvailability = ModelAvailability.AVAILABLE,
) -> ProviderAvailabilityEvidence:
    return ProviderAvailabilityEvidence(
        provider_id="approved-provider",
        model_id="approved-model",
        status=status,
        evidence_reference="health-check-123",
        checked_at=NOW - timedelta(seconds=1),
        valid_until=NOW + timedelta(minutes=5),
    )


def decision(request_value: ModelRequest | None = None):
    return resolve_model_route(
        policy=policy(),
        request=request_value or request(),
        availability=availability(),
        now=NOW,
        remaining_budget_usd=Decimal("0.10"),
    )


def test_route_is_explicit_and_produces_c067_with_provenance() -> None:
    req = request()
    result = decision(req)

    assert result.contract_id == "C-067"
    assert result.schema_version == "1"
    assert result.request_id == req.request_id
    assert result.request_sha256 == req.request_sha256
    assert result.provider_id == "approved-provider"
    assert result.model_id == "approved-model"
    assert result.prompt_version == req.prompt_version
    assert result.availability is ModelAvailability.AVAILABLE
    assert result.availability_reference == "health-check-123"
    assert result.fallback_policy.value == "DENY"


@pytest.mark.parametrize(
    ("requested", "available", "budget", "clock"),
    [
        (
            ModelCapabilityTier.PREMIUM_STRONGEST_AVAILABLE,
            ModelAvailability.AVAILABLE,
            Decimal("1"),
            NOW,
        ),
        (
            ModelCapabilityTier.ECONOMICAL_FAST,
            ModelAvailability.DEGRADED,
            Decimal("1"),
            NOW,
        ),
        (
            ModelCapabilityTier.ECONOMICAL_FAST,
            ModelAvailability.AVAILABLE,
            Decimal("0.01"),
            NOW,
        ),
        (
            ModelCapabilityTier.ECONOMICAL_FAST,
            ModelAvailability.AVAILABLE,
            Decimal("1"),
            NOW + timedelta(hours=2),
        ),
    ],
)
def test_missing_unavailable_over_budget_or_expired_route_fails_closed(
    requested: ModelCapabilityTier,
    available: ModelAvailability,
    budget: Decimal,
    clock: datetime,
) -> None:
    req = replace(request(), capability_tier=requested)
    with pytest.raises(ModelRoutingError):
        resolve_model_route(
            policy=policy(),
            request=req,
            availability=availability(available),
            now=clock,
            remaining_budget_usd=budget,
        )


class FakeProvider:
    provider_id = "approved-provider"

    def __init__(self, result: ModelResponse) -> None:
        self.result = result
        self.calls = 0

    async def generate(self, request_value: ModelRequest) -> ModelResponse:
        self.calls += 1
        return self.result


def provider_response(
    req: ModelRequest, *, model_version: str = "2026-10-01"
) -> ModelResponse:
    return ModelResponse(
        request_id=req.request_id,
        provider_id="approved-provider",
        model_id="approved-model",
        returned_model_version=model_version,
        content="Evidence summary; uncertainty remains.",
        started_at=NOW + timedelta(seconds=1),
        completed_at=NOW + timedelta(seconds=2),
        input_tokens=400,
        output_tokens=80,
        actual_cost_usd=Decimal("0.03"),
        availability=ModelAvailability.AVAILABLE,
    )


def test_provider_call_is_bound_and_enforces_metadata_cost_and_usage() -> None:
    req = request()
    selected = decision(req)
    provider = FakeProvider(provider_response(req))

    result = asyncio.run(
        invoke_provider(
            provider=provider,
            decision=selected,
            request=req,
            now=NOW,
        )
    )

    assert result == provider.result
    assert provider.calls == 1


def test_modified_request_is_rejected_before_provider_call() -> None:
    req = request()
    selected = decision(req)
    changed = replace(req, content="Different evidence and prompt content.")
    provider = FakeProvider(provider_response(req))

    with pytest.raises(ModelRoutingError, match="not bound"):
        asyncio.run(
            invoke_provider(
                provider=provider,
                decision=selected,
                request=changed,
                now=NOW,
            )
        )
    assert provider.calls == 0


def test_unapproved_model_version_and_unknown_cost_fail_closed() -> None:
    req = request()
    selected = decision(req)
    provider = FakeProvider(provider_response(req, model_version="latest"))
    with pytest.raises(ModelRoutingError, match="unapproved model version"):
        asyncio.run(
            invoke_provider(provider=provider, decision=selected, request=req, now=NOW)
        )

    provider.result = replace(provider_response(req), actual_cost_usd=None)
    with pytest.raises(ModelRoutingError, match="cost is unknown"):
        asyncio.run(
            invoke_provider(provider=provider, decision=selected, request=req, now=NOW)
        )


def test_provider_exception_is_sanitized_and_not_retried() -> None:
    class FailingProvider:
        provider_id = "approved-provider"

        async def generate(self, request_value: ModelRequest) -> ModelResponse:
            raise RuntimeError("api_key=must-not-leak")

    req = request()
    with pytest.raises(ModelRoutingError, match="no retry or fallback") as error:
        asyncio.run(
            invoke_provider(
                provider=FailingProvider(),
                decision=decision(req),
                request=req,
                now=NOW,
            )
        )
    assert "api_key" not in str(error.value)
