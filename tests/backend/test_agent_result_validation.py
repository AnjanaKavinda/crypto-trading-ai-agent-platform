from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from trading_platform_api.agents import (
    AgentResult,
    AgentResultExpectation,
    AgentResultStatus,
    AgentResultValidationError,
    ModelAvailability,
    ModelCapabilityTier,
    ModelRoutingDecision,
    validate_agent_result,
)

NOW = datetime(2026, 10, 21, 4, 0, tzinfo=UTC)


def routing_decision() -> ModelRoutingDecision:
    return ModelRoutingDecision(
        request_id=uuid4(),
        request_sha256="a" * 64,
        workload_id="personal-spot-research",
        capability_tier=ModelCapabilityTier.ECONOMICAL_FAST,
        provider_id="approved-provider",
        model_id="approved-model",
        model_version="2026-10-01",
        prompt_id="spot-summary",
        prompt_version="1",
        policy_id="spot-policy",
        policy_version="1",
        decided_at=NOW - timedelta(seconds=1),
        expires_at=NOW + timedelta(minutes=5),
        max_input_tokens=1000,
        max_output_tokens=200,
        max_request_cost_usd=Decimal("0.10"),
        availability=ModelAvailability.AVAILABLE,
        availability_reference="health-check-123",
        availability_checked_at=NOW - timedelta(seconds=2),
    )


def result(**changes: object) -> AgentResult:
    decision = routing_decision()
    values: dict[str, object] = {
        "result_id": uuid4(),
        "task_id": uuid4(),
        "context_id": uuid4(),
        "agent_id": "spot-summary-agent",
        "agent_version": "1",
        "routing_decision": decision,
        "tool_access_ids": (uuid4(),),
        "generated_at": NOW,
        "expires_at": NOW + timedelta(minutes=2),
        "status": AgentResultStatus.COMPLETE,
        "confidence": Decimal("0.6"),
        "supporting_evidence_ids": (uuid4(),),
        "contradicting_evidence_ids": (),
        "unresolved_risks": (),
        "output": decision,
    }
    values.update(changes)
    return AgentResult(**values)  # type: ignore[arg-type]


def expectation(value: AgentResult) -> AgentResultExpectation:
    return AgentResultExpectation(
        task_id=value.task_id,
        context_id=value.context_id,
        agent_id=value.agent_id,
        agent_version=value.agent_version,
        routing_decision=value.routing_decision,
        allowed_tool_access_ids=value.tool_access_ids,
        allowed_evidence_ids=(
            value.supporting_evidence_ids + value.contradicting_evidence_ids
        ),
        allowed_output_schemas={"C-067": ("1", ModelRoutingDecision)},
    )


def test_result_requires_exact_trusted_bindings_and_registered_output() -> None:
    value = result()

    assert (
        validate_agent_result(value, expectation=expectation(value), now=NOW) is value
    )


@pytest.mark.parametrize(
    "changes",
    [
        {"task_id": uuid4()},
        {"context_id": uuid4()},
        {"agent_id": "other-agent"},
        {"agent_version": "2"},
        {"routing_decision": routing_decision()},
        {"tool_access_ids": (uuid4(), uuid4())},
        {"generated_at": NOW + timedelta(seconds=1)},
        {"expires_at": NOW},
        {"status": AgentResultStatus.INSUFFICIENT_DATA},
    ],
)
def test_mismatched_or_incomplete_results_fail_closed(
    changes: dict[str, object],
) -> None:
    value = result()
    changed = replace(value, **changes)
    with pytest.raises(AgentResultValidationError):
        validate_agent_result(changed, expectation=expectation(value), now=NOW)


def test_unknown_output_contract_and_expired_route_are_rejected() -> None:
    value = result()
    with pytest.raises(AgentResultValidationError, match="not allowlisted"):
        validate_agent_result(
            value,
            expectation=replace(
                expectation(value),
                allowed_output_schemas={"C-999": ("1", ModelRoutingDecision)},
            ),
            now=NOW,
        )
    expired = replace(
        value,
        routing_decision=replace(value.routing_decision, expires_at=NOW),
    )
    with pytest.raises(AgentResultValidationError, match="expired"):
        validate_agent_result(expired, expectation=expectation(expired), now=NOW)


def test_evidence_references_must_resolve_within_the_bound_context() -> None:
    value = result()
    trusted = replace(
        expectation(value),
        allowed_evidence_ids=(),
    )

    with pytest.raises(AgentResultValidationError, match="evidence provenance"):
        validate_agent_result(value, expectation=trusted, now=NOW)


def test_no_trade_is_valid_and_keeps_its_unresolved_risk() -> None:
    value = result(
        status=AgentResultStatus.NO_TRADE,
        confidence=None,
        unresolved_risks=("insufficient independent evidence",),
    )

    validated = validate_agent_result(value, expectation=expectation(value), now=NOW)
    assert validated.status is AgentResultStatus.NO_TRADE


def test_confidence_without_supporting_evidence_is_rejected_at_construction() -> None:
    with pytest.raises(ValueError, match="supporting evidence"):
        result(supporting_evidence_ids=())
