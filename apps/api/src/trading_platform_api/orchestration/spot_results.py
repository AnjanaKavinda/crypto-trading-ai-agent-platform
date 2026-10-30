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
from uuid import UUID, uuid4

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph

from trading_platform_api.agents.contracts import (
    AgentEvaluation,
    AgentEvaluationFailureClass,
    AgentEvaluationOutcome,
    AgentResult,
    AgentResultStatus,
)
from trading_platform_api.agents.evaluation import build_agent_evaluation
from trading_platform_api.agents.registry import PERSONAL_SPOT_RESEARCH_AGENT
from trading_platform_api.agents.result_validation import (
    AgentResultExpectation,
    AgentResultValidationError,
    validate_agent_result,
)
from trading_platform_api.config import (
    AppSettingsError,
    DeploymentEnvironment,
    OperatingMode,
    load_app_settings,
)
from trading_platform_api.risk import ContractReference


class SpotResultState(TypedDict, total=False):
    """Checkpoint-safe state carrying result identity and provenance."""

    correlation_id: UUID
    trace_id: UUID
    agent_result: AgentResult
    agent_evaluation: AgentEvaluation
    status: Literal[
        "PENDING", "ACCEPTED", "NO_TRADE", "REJECTED", "TIMED_OUT", "FAILED"
    ]
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
    expectation: AgentResultExpectation,
    correlation_id: UUID,
    agent_result: AgentResult,
    thread_id: str,
    timeout_seconds: float = 5.0,
    trace_id: UUID | None = None,
    environment: DeploymentEnvironment | None = None,
    mode: OperatingMode | None = None,
    calibration_refs: tuple[ContractReference, ...] = (),
    reliability_refs: tuple[ContractReference, ...] = (),
    clock: Callable[[], datetime] | None = None,
) -> SpotResultState:
    """Run with explicit thread correlation and a bounded deadline.

    Cancellation is allowed to propagate to the caller. A timeout fails closed
    while retaining the submitted result and correlation identity for diagnosis.
    """

    if not isinstance(correlation_id, UUID):
        raise ValueError("correlation_id must be a UUID")
    if not isinstance(agent_result, AgentResult):
        raise ValueError("a typed C-062 AgentResult is required")
    if not isinstance(expectation, AgentResultExpectation):
        raise ValueError("a trusted AgentResultExpectation is required")
    if not isinstance(thread_id, str) or not thread_id.strip():
        raise ValueError("thread_id is required for checkpoint correlation")
    if isinstance(timeout_seconds, bool) or not isinstance(
        timeout_seconds, (int, float)
    ):
        raise ValueError("timeout_seconds must be a positive number")
    if not 0 < timeout_seconds <= 60:
        raise ValueError("timeout_seconds must be between 0 and 60 seconds")
    try:
        settings = load_app_settings()
    except AppSettingsError:
        raise ValueError("runtime environment and mode must be valid") from None
    resolved_environment = environment or settings.environment
    resolved_mode = mode or settings.mode
    if not isinstance(resolved_environment, DeploymentEnvironment):
        raise ValueError("environment must be a DeploymentEnvironment")
    if resolved_mode is not OperatingMode.RESEARCH:
        raise ValueError("PERSONAL_SPOT_RESEARCH evaluations require research mode")
    resolved_trace_id = trace_id or uuid4()
    if not isinstance(resolved_trace_id, UUID):
        raise ValueError("trace_id must be a UUID")
    get_now = clock or (lambda: datetime.now(UTC))
    started_at = agent_result.routing_decision.decided_at
    ended_at = agent_result.generated_at

    state: SpotResultState = {
        "correlation_id": correlation_id,
        "trace_id": resolved_trace_id,
        "agent_result": agent_result,
        "status": "PENDING",
        "validation_error": None,
        "validated_at": None,
    }
    config: Mapping[str, object] = {"configurable": {"thread_id": thread_id}}
    try:
        async with asyncio.timeout(timeout_seconds):
            result_state = await graph.ainvoke(state, config=config)  # type: ignore[attr-defined]
    except TimeoutError:
        evaluated_at = get_now()
        return _with_evaluation(
            state={
                **state,
                "status": "TIMED_OUT",
                "validation_error": "result validation exceeded its deadline",
                "validated_at": evaluated_at,
            },
            expectation=expectation,
            outcome=AgentEvaluationOutcome.TIMED_OUT,
            failure_classification=AgentEvaluationFailureClass.EVALUATION_TIMEOUT,
            validation_completed=False,
            started_at=started_at,
            ended_at=ended_at,
            evaluated_at=evaluated_at,
            duration_ms=_duration_ms(started_at, ended_at, evaluated_at),
            environment=resolved_environment,
            mode=resolved_mode,
            calibration_refs=calibration_refs,
            reliability_refs=reliability_refs,
        )
    except Exception:
        evaluated_at = get_now()
        return _with_evaluation(
            state={
                **state,
                "status": "FAILED",
                "validation_error": "result evaluation failed",
                "validated_at": evaluated_at,
            },
            expectation=expectation,
            outcome=AgentEvaluationOutcome.FAILED,
            failure_classification=AgentEvaluationFailureClass.EVALUATION_FAILURE,
            validation_completed=False,
            started_at=started_at,
            ended_at=ended_at,
            evaluated_at=evaluated_at,
            duration_ms=_duration_ms(started_at, ended_at, evaluated_at),
            environment=resolved_environment,
            mode=resolved_mode,
            calibration_refs=calibration_refs,
            reliability_refs=reliability_refs,
        )

    evaluated_at = get_now()
    status = result_state.get("status")
    if status in ("ACCEPTED", "NO_TRADE"):
        outcome = AgentEvaluationOutcome.COMPLETED
        failure_classification = None
        validation_completed = True
    elif status == "REJECTED":
        outcome = AgentEvaluationOutcome.REJECTED_INVALID
        failure_classification = AgentEvaluationFailureClass.RESULT_VALIDATION_REJECTED
        validation_completed = True
    elif status == "TIMED_OUT":
        outcome = AgentEvaluationOutcome.TIMED_OUT
        failure_classification = AgentEvaluationFailureClass.EVALUATION_TIMEOUT
        validation_completed = False
    else:
        outcome = AgentEvaluationOutcome.FAILED
        failure_classification = AgentEvaluationFailureClass.EVALUATION_FAILURE
        validation_completed = False
    return _with_evaluation(
        state=result_state,
        expectation=expectation,
        outcome=outcome,
        failure_classification=failure_classification,
        validation_completed=validation_completed,
        started_at=started_at,
        ended_at=ended_at,
        evaluated_at=evaluated_at,
        duration_ms=_duration_ms(started_at, ended_at, evaluated_at),
        environment=resolved_environment,
        mode=resolved_mode,
        calibration_refs=calibration_refs,
        reliability_refs=reliability_refs,
    )


def _with_evaluation(
    *,
    state: Mapping[str, object],
    expectation: AgentResultExpectation,
    outcome: AgentEvaluationOutcome,
    failure_classification: AgentEvaluationFailureClass | None,
    validation_completed: bool,
    started_at: datetime,
    ended_at: datetime,
    evaluated_at: datetime,
    duration_ms: int | None,
    environment: DeploymentEnvironment,
    mode: OperatingMode,
    calibration_refs: tuple[ContractReference, ...],
    reliability_refs: tuple[ContractReference, ...],
) -> SpotResultState:
    result = state.get("agent_result")
    correlation_id = state.get("correlation_id")
    trace_id = state.get("trace_id")
    if not isinstance(result, AgentResult):
        raise ValueError("a typed C-062 result is required for C-066 evaluation")
    if not isinstance(correlation_id, UUID) or not isinstance(trace_id, UUID):
        raise ValueError("C-066 correlation and trace identities are required")
    evaluation = build_agent_evaluation(
        result,
        expectation=expectation,
        correlation_id=correlation_id,
        trace_id=trace_id,
        environment=environment,
        mode=mode,
        started_at=started_at,
        ended_at=ended_at,
        evaluated_at=evaluated_at,
        duration_ms=duration_ms,
        outcome=outcome,
        failure_classification=failure_classification,
        validation_completed=validation_completed,
        calibration_refs=calibration_refs,
        reliability_refs=reliability_refs,
    )
    result_state = dict(state)
    result_state["agent_evaluation"] = evaluation
    return result_state  # type: ignore[return-value]


def _duration_ms(
    started_at: datetime, ended_at: datetime, evaluated_at: datetime
) -> int | None:
    """Return route-to-result latency only when timestamps establish the order."""

    if started_at > ended_at or ended_at > evaluated_at:
        return None
    return int((ended_at - started_at).total_seconds() * 1000)
