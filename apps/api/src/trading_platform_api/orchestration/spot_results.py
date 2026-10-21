"""LangGraph workflow for validating one bounded PERSONAL_SPOT_RESEARCH result.

The graph deliberately consumes an already-created C-062 result. It does not
invoke models, tools, market providers, risk, approval, or execution systems.
Its nodes are deterministic and side-effect free, so checkpoint resume/replay
cannot repeat an external action.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from typing import Literal, TypedDict
from uuid import UUID

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph

from trading_platform_api.agents.contracts import AgentResult, AgentResultStatus
from trading_platform_api.agents.registry import PERSONAL_SPOT_RESEARCH_AGENT
from trading_platform_api.agents.result_validation import (
    AgentResultExpectation,
    AgentResultValidationError,
    validate_agent_result,
)


class SpotResultState(TypedDict, total=False):
    """Checkpoint-safe state carrying result identity and provenance."""

    correlation_id: UUID
    agent_result: AgentResult
    status: Literal["PENDING", "ACCEPTED", "NO_TRADE", "REJECTED", "TIMED_OUT"]
    validation_error: str | None
    validated_at: datetime | None


def build_spot_result_graph(
    *,
    expectation: AgentResultExpectation,
    checkpointer: BaseCheckpointSaver | None,
    clock: Callable[[], datetime] | None = None,
):
    """Compile the explicit result-validation graph with caller-owned checkpointing.

    The trusted expectation is captured by the validator node and is never read
    from graph state. Callers may supply a persistent LangGraph checkpointer at
    composition time; this module selects no storage backend or retention policy.
    """

    if not isinstance(expectation, AgentResultExpectation):
        raise TypeError("a trusted AgentResultExpectation is required")
    if expectation.agent_id != PERSONAL_SPOT_RESEARCH_AGENT.agent_id or (
        expectation.agent_version != PERSONAL_SPOT_RESEARCH_AGENT.agent_version
    ):
        raise ValueError("only the registered PERSONAL_SPOT_RESEARCH agent is allowed")
    if expectation.allowed_tool_access_ids:
        raise ValueError("PERSONAL_SPOT_RESEARCH must not receive tool access")
    if not set(expectation.allowed_output_schemas).issubset(
        PERSONAL_SPOT_RESEARCH_AGENT.allowed_outputs
    ):
        raise ValueError("result schemas exceed the registered agent output allowlist")
    get_now = clock or (lambda: datetime.now(UTC))

    def validate_result(state: SpotResultState) -> SpotResultState:
        try:
            result = validate_agent_result(
                state.get("agent_result"),
                expectation=expectation,
                now=get_now(),
            )
        except (AgentResultValidationError, TypeError, ValueError) as exc:
            return {
                "status": "REJECTED",
                "validation_error": str(exc),
                "validated_at": get_now(),
            }

        status: Literal["NO_TRADE", "ACCEPTED"] = (
            "NO_TRADE" if result.status is AgentResultStatus.NO_TRADE else "ACCEPTED"
        )
        return {
            "agent_result": result,
            "status": status,
            "validation_error": None,
            "validated_at": get_now(),
        }

    def route_result(
        state: SpotResultState,
    ) -> Literal["accepted", "no_trade", "rejected"]:
        status = state.get("status")
        if status == "ACCEPTED":
            return "accepted"
        if status == "NO_TRADE":
            return "no_trade"
        return "rejected"

    builder = StateGraph(SpotResultState)
    builder.add_node("validate_result", validate_result)
    builder.add_node("accepted", lambda _state: {})
    builder.add_node("no_trade", lambda _state: {})
    builder.add_node("rejected", lambda _state: {})
    builder.add_edge(START, "validate_result")
    builder.add_conditional_edges(
        "validate_result",
        route_result,
        {"accepted": "accepted", "no_trade": "no_trade", "rejected": "rejected"},
    )
    for terminal in ("accepted", "no_trade", "rejected"):
        builder.add_edge(terminal, END)
    return builder.compile(checkpointer=checkpointer)


async def run_spot_result_graph(
    graph: object,
    *,
    correlation_id: UUID,
    agent_result: AgentResult,
    thread_id: str,
    timeout_seconds: float = 5.0,
) -> SpotResultState:
    """Run with explicit thread correlation and a bounded deadline.

    Cancellation is allowed to propagate to the caller. A timeout fails closed
    while retaining the submitted result and correlation identity for diagnosis.
    """

    if not isinstance(correlation_id, UUID):
        raise ValueError("correlation_id must be a UUID")
    if not isinstance(agent_result, AgentResult):
        raise ValueError("a typed C-062 AgentResult is required")
    if not isinstance(thread_id, str) or not thread_id.strip():
        raise ValueError("thread_id is required for checkpoint correlation")
    if isinstance(timeout_seconds, bool) or not isinstance(
        timeout_seconds, (int, float)
    ):
        raise ValueError("timeout_seconds must be a positive number")
    if not 0 < timeout_seconds <= 60:
        raise ValueError("timeout_seconds must be between 0 and 60 seconds")

    state: SpotResultState = {
        "correlation_id": correlation_id,
        "agent_result": agent_result,
        "status": "PENDING",
        "validation_error": None,
        "validated_at": None,
    }
    config: Mapping[str, object] = {"configurable": {"thread_id": thread_id}}
    try:
        async with asyncio.timeout(timeout_seconds):
            return await graph.ainvoke(state, config=config)  # type: ignore[attr-defined]
    except TimeoutError:
        return {
            **state,
            "status": "TIMED_OUT",
            "validation_error": "result validation exceeded its deadline",
            "validated_at": datetime.now(UTC),
        }
