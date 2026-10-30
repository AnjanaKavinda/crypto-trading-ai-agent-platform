from __future__ import annotations

import asyncio
from dataclasses import dataclass, replace
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
        if status in (AgentResultStatus.NO_TRADE, AgentResultStatus.INSUFFICIENT_DATA)
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
            expectation=_expectation(value),
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
    assert state["agent_evaluation"].result_id == value.result_id
    assert state["agent_evaluation"].schema_state.value == "VALID"
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
            expectation=_expectation(value),
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
            expectation=_expectation(expected),
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
            expectation=_expectation(value),
            correlation_id=correlation_id,
            agent_result=value,
            thread_id=str(value.task_id),
            timeout_seconds=0.001,
        )
    )

    assert state["status"] == "TIMED_OUT"
    assert state["correlation_id"] == correlation_id
    assert state["agent_result"] is value
    assert state["agent_evaluation"].outcome.value == "TIMED_OUT"
    assert state["agent_evaluation"].schema_state.value == "UNKNOWN"

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


def test_result_graph_rejects_c061_c067_tool_and_schema_mismatches() -> None:
    @dataclass(frozen=True)
    class UnsupportedOutputV2:
        contract_id: str = "C-069"
        schema_version: str = "2"

    valid = _result()
    expectation = _expectation(valid)
    variants = (
        replace(valid, agent_id="unregistered-agent"),
        replace(valid, agent_version="2"),
        replace(
            valid,
            routing_decision=replace(valid.routing_decision, provider_id="other"),
        ),
        replace(
            valid,
            routing_decision=replace(valid.routing_decision, model_id="other"),
        ),
        replace(
            valid,
            routing_decision=replace(valid.routing_decision, prompt_version="2"),
        ),
        replace(valid, tool_access_ids=(uuid4(),)),
        replace(valid, output=UnsupportedOutputV2()),
        replace(valid, output="malformed provider output"),
    )

    for candidate in variants:
        graph = build_spot_result_graph(
            expectation=expectation, checkpointer=None, clock=lambda: NOW
        )
        state = asyncio.run(
            run_spot_result_graph(
                graph,
                expectation=expectation,
                correlation_id=uuid4(),
                trace_id=uuid4(),
                agent_result=candidate,
                thread_id=str(valid.task_id),
                clock=lambda: NOW,
            )
        )

        assert state["status"] == "REJECTED"
        assert state["agent_result"] is candidate
        assert state["agent_evaluation"].outcome.value == "REJECTED_INVALID"
        assert state["agent_evaluation"].result_status is candidate.status


def test_graph_requires_registered_c061_agent_and_version_at_build_time() -> None:
    valid = _result()
    for identity in ({"agent_id": "other-agent"}, {"agent_version": "2"}):
        with pytest.raises(ValueError, match="registered PERSONAL_SPOT_RESEARCH"):
            build_spot_result_graph(
                expectation=replace(_expectation(valid), **identity),
                checkpointer=None,
            )


def test_no_typed_c062_means_no_graph_run_or_c066_evaluation() -> None:
    class CountingGraph:
        calls = 0

        async def ainvoke(self, _state: object, *, config: object) -> object:
            self.calls += 1
            return {}

    value = _result()
    graph = CountingGraph()
    with pytest.raises(ValueError, match="typed C-062"):
        asyncio.run(
            run_spot_result_graph(
                graph,
                expectation=_expectation(value),
                correlation_id=uuid4(),
                trace_id=uuid4(),
                agent_result=None,  # type: ignore[arg-type]
                thread_id=str(value.task_id),
            )
        )

    assert graph.calls == 0


def test_result_graph_caller_cancellation_propagates() -> None:
    async def exercise() -> None:
        started = asyncio.Event()

        class BlockingGraph:
            async def ainvoke(self, _state: object, *, config: object) -> object:
                started.set()
                await asyncio.Event().wait()

        value = _result()
        task = asyncio.create_task(
            run_spot_result_graph(
                BlockingGraph(),
                expectation=_expectation(value),
                correlation_id=uuid4(),
                trace_id=uuid4(),
                agent_result=value,
                thread_id=str(value.task_id),
            )
        )
        await asyncio.wait_for(started.wait(), timeout=0.2)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, timeout=0.2)

    asyncio.run(exercise())


def test_checkpoint_replay_revalidates_and_preserves_new_identity() -> None:
    async def exercise() -> None:
        value = _result()
        expectation = _expectation(value)
        graph = build_spot_result_graph(
            expectation=expectation,
            checkpointer=InMemorySaver(),
            clock=lambda: NOW,
        )
        correlation_id, trace_id = uuid4(), uuid4()
        first = await run_spot_result_graph(
            graph,
            expectation=expectation,
            correlation_id=correlation_id,
            trace_id=trace_id,
            agent_result=value,
            thread_id=str(value.task_id),
            clock=lambda: NOW,
        )

        changed = replace(value, task_id=uuid4(), context_id=uuid4())
        replay_correlation, replay_trace = uuid4(), uuid4()
        replay = await run_spot_result_graph(
            graph,
            expectation=expectation,
            correlation_id=replay_correlation,
            trace_id=replay_trace,
            agent_result=changed,
            thread_id=str(value.task_id),
            clock=lambda: NOW,
        )

        assert first["status"] == "ACCEPTED"
        assert first["correlation_id"] == correlation_id
        assert first["trace_id"] == trace_id
        assert first["agent_result"].task_id == value.task_id
        assert first["agent_result"].context_id == value.context_id
        assert replay["status"] == "REJECTED"
        assert replay["agent_result"] is changed
        assert replay["agent_result"].task_id == changed.task_id
        assert replay["agent_result"].context_id == changed.context_id
        assert replay["correlation_id"] == replay_correlation
        assert replay["trace_id"] == replay_trace
        assert replay["agent_evaluation"].outcome.value == "REJECTED_INVALID"

    asyncio.run(exercise())
