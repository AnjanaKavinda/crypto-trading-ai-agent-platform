from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from trading_platform_api.agents import (
    AgentResult,
    AgentResultExpectation,
    AgentResultStatus,
    ModelAvailability,
    ModelCapabilityTier,
    ModelRoutingDecision,
)
from trading_platform_api.analysis import (
    AnalyticalUncertainty,
    ResolutionStatus,
    UncertaintyCategory,
)
from trading_platform_api.orchestration import (
    build_spot_result_graph,
    run_spot_result_graph,
)

NOW = datetime(2026, 10, 21, 4, 0, tzinfo=UTC)


def _route() -> ModelRoutingDecision:
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


def _result(*, status: AgentResultStatus = AgentResultStatus.COMPLETE) -> AgentResult:
    route = _route()
    evidence_id = uuid4()
    output = AnalyticalUncertainty(
        uncertainty_id=uuid4(),
        category=UncertaintyCategory.INTERPRETATION,
        description="One analytical caveat remains.",
        affected_finding_ids=(),
        affected_domains=("technical",),
        severity=Decimal("0.2"),
        reducible=False,
        required_evidence=(),
        as_of=NOW,
        expires_at=NOW + timedelta(minutes=1),
        resolution_status=ResolutionStatus.UNRESOLVED,
    )
    return AgentResult(
        result_id=uuid4(),
        task_id=uuid4(),
        context_id=uuid4(),
        agent_id="personal-spot-research",
        agent_version="1",
        routing_decision=route,
        tool_access_ids=(),
        generated_at=NOW,
        expires_at=NOW + timedelta(minutes=2),
        status=status,
        confidence=None,
        supporting_evidence_ids=(evidence_id,),
        contradicting_evidence_ids=(),
        unresolved_risks=("insufficient independent evidence",)
        if status is AgentResultStatus.NO_TRADE
        else (),
        output=output,
    )


def _expectation(value: AgentResult) -> AgentResultExpectation:
    return AgentResultExpectation(
        task_id=value.task_id,
        context_id=value.context_id,
        agent_id=value.agent_id,
        agent_version=value.agent_version,
        routing_decision=value.routing_decision,
        allowed_tool_access_ids=(),
        allowed_evidence_ids=value.supporting_evidence_ids,
        allowed_output_schemas={"C-069": ("1", AnalyticalUncertainty)},
    )


def test_graph_validates_output_and_preserves_checkpoint_provenance() -> None:
    value = _result()
    checkpointer = InMemorySaver()
    graph = build_spot_result_graph(
        expectation=_expectation(value), checkpointer=checkpointer, clock=lambda: NOW
    )
    correlation_id = uuid4()

    state = asyncio.run(
        run_spot_result_graph(
            graph,
            correlation_id=correlation_id,
            agent_result=value,
            thread_id=str(value.task_id),
        )
    )

    assert state["status"] == "ACCEPTED"
    assert state["agent_result"] is value
    assert state["correlation_id"] == correlation_id
    assert state["validated_at"].tzinfo is UTC
    assert state["validation_error"] is None
    checkpoint = graph.get_state({"configurable": {"thread_id": str(value.task_id)}})
    assert checkpoint.values["correlation_id"] == correlation_id


def test_graph_keeps_no_trade_as_a_valid_terminal_state() -> None:
    value = _result(status=AgentResultStatus.NO_TRADE)
    graph = build_spot_result_graph(
        expectation=_expectation(value), checkpointer=None, clock=lambda: NOW
    )

    state = asyncio.run(
        run_spot_result_graph(
            graph,
            correlation_id=uuid4(),
            agent_result=value,
            thread_id=str(value.task_id),
        )
    )

    assert state["status"] == "NO_TRADE"
    assert state["agent_result"].unresolved_risks


def test_graph_rejects_result_outside_trusted_task_binding() -> None:
    expected = _result()
    untrusted = _result()
    graph = build_spot_result_graph(
        expectation=_expectation(expected), checkpointer=None, clock=lambda: NOW
    )

    state = asyncio.run(
        run_spot_result_graph(
            graph,
            correlation_id=uuid4(),
            agent_result=untrusted,
            thread_id=str(expected.task_id),
        )
    )

    assert state["status"] == "REJECTED"
    assert "task identity" in state["validation_error"]


def test_graph_refuses_tool_access_and_unregistered_output_contracts() -> None:
    value = _result()
    with pytest.raises(ValueError, match="must not receive tool access"):
        build_spot_result_graph(
            expectation=replace(
                _expectation(value), allowed_tool_access_ids=(uuid4(),)
            ),
            checkpointer=None,
        )


def test_timeout_returns_a_correlated_fail_closed_state() -> None:
    class SlowGraph:
        async def ainvoke(self, _state: object, *, config: object) -> object:
            await asyncio.sleep(0.05)
            return {}

    value = _result()
    correlation_id = uuid4()
    state = asyncio.run(
        run_spot_result_graph(
            SlowGraph(),
            correlation_id=correlation_id,
            agent_result=value,
            thread_id=str(value.task_id),
            timeout_seconds=0.001,
        )
    )

    assert state["status"] == "TIMED_OUT"
    assert state["correlation_id"] == correlation_id
    assert state["agent_result"] is value

    with pytest.raises(ValueError, match="registered agent output allowlist"):
        build_spot_result_graph(
            expectation=replace(
                _expectation(value),
                allowed_output_schemas={
                    "C-999": ("1", AnalyticalUncertainty),
                },
            ),
            checkpointer=None,
        )
