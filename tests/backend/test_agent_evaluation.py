from __future__ import annotations

import asyncio
from dataclasses import dataclass, fields, replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from trading_platform_api.agents import (
    AGENT_EVALUATION_METHOD_ID,
    AGENT_EVALUATION_METHOD_VERSION,
    AgentContractError,
    AgentEvaluationFailureClass,
    AgentEvaluationOutcome,
    AgentEvaluationSchemaState,
    AgentGroundingState,
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
from trading_platform_api.config import DeploymentEnvironment, OperatingMode
from trading_platform_api.contracts import canonical_sha256, serialize_contract
from trading_platform_api.orchestration import (
    build_spot_result_graph,
    run_spot_result_graph,
)
from trading_platform_api.risk import ContractReference

NOW = datetime(2026, 10, 30, 4, 0, tzinfo=UTC)


def _route() -> ModelRoutingDecision:
    return ModelRoutingDecision(
        request_id=uuid4(),
        request_sha256="a" * 64,
        workload_id="personal-spot-research",
        capability_tier=ModelCapabilityTier.ECONOMICAL_FAST,
        provider_id="approved-provider",
        model_id="approved-model",
        model_version="model-v1",
        prompt_id="spot-summary",
        prompt_version="prompt-v1",
        policy_id="spot-policy",
        policy_version="1",
        decided_at=NOW - timedelta(seconds=1),
        expires_at=NOW + timedelta(minutes=5),
        max_input_tokens=1000,
        max_output_tokens=200,
        max_request_cost_usd=Decimal("0.10"),
        availability=ModelAvailability.AVAILABLE,
        availability_reference="provider-health-check",
        availability_checked_at=NOW - timedelta(seconds=2),
    )


def _result(
    status: AgentResultStatus = AgentResultStatus.COMPLETE,
) -> AgentResult:
    evidence_id = uuid4()
    return AgentResult(
        result_id=uuid4(),
        task_id=uuid4(),
        context_id=uuid4(),
        agent_id="personal-spot-research",
        agent_version="1",
        routing_decision=_route(),
        tool_access_ids=(),
        generated_at=NOW,
        expires_at=NOW + timedelta(minutes=2),
        status=status,
        confidence=None,
        supporting_evidence_ids=(evidence_id,),
        contradicting_evidence_ids=(),
        unresolved_risks=("evidence remains incomplete",)
        if status in (AgentResultStatus.NO_TRADE, AgentResultStatus.INSUFFICIENT_DATA)
        else (),
        output=AnalyticalUncertainty(
            uncertainty_id=uuid4(),
            category=UncertaintyCategory.INTERPRETATION,
            description="A research caveat remains.",
            affected_finding_ids=(),
            affected_domains=("technical",),
            severity=Decimal("0.2"),
            reducible=False,
            required_evidence=(),
            as_of=NOW,
            expires_at=NOW + timedelta(minutes=1),
            resolution_status=ResolutionStatus.UNRESOLVED,
        ),
    )


def _expectation(result: AgentResult) -> AgentResultExpectation:
    return AgentResultExpectation(
        task_id=result.task_id,
        context_id=result.context_id,
        agent_id=result.agent_id,
        agent_version=result.agent_version,
        routing_decision=result.routing_decision,
        allowed_tool_access_ids=(),
        allowed_evidence_ids=result.supporting_evidence_ids
        + result.contradicting_evidence_ids,
        allowed_output_schemas={"C-069": ("1", AnalyticalUncertainty)},
    )


def _run(result: AgentResult, *, graph: object | None = None, **kwargs: object):
    expectation = _expectation(result)
    actual_graph = graph or build_spot_result_graph(
        expectation=expectation, checkpointer=InMemorySaver(), clock=lambda: NOW
    )
    return asyncio.run(
        run_spot_result_graph(
            actual_graph,
            expectation=expectation,
            correlation_id=uuid4(),
            trace_id=uuid4(),
            environment=DeploymentEnvironment.TEST,
            mode=OperatingMode.RESEARCH,
            agent_result=result,
            thread_id=str(result.task_id),
            **kwargs,
        )
    )["agent_evaluation"]


def test_successful_evaluation_binds_exact_c062_c067_and_method_identity() -> None:
    result = _result()
    expectation = _expectation(result)
    state = asyncio.run(
        run_spot_result_graph(
            build_spot_result_graph(
                expectation=expectation, checkpointer=None, clock=lambda: NOW
            ),
            expectation=expectation,
            correlation_id=uuid4(),
            trace_id=uuid4(),
            environment=DeploymentEnvironment.TEST,
            mode=OperatingMode.RESEARCH,
            agent_result=result,
            thread_id=str(result.task_id),
            clock=lambda: NOW,
        )
    )
    evaluation = state["agent_evaluation"]

    assert evaluation.contract_id == "C-066"
    assert evaluation.schema_version == "1"
    assert evaluation.result_contract_id == "C-062"
    assert evaluation.result_id == result.result_id
    assert evaluation.result_schema_version == result.schema_version == "1"
    assert evaluation.task_id == result.task_id
    assert evaluation.context_id == result.context_id
    assert evaluation.correlation_id == state["correlation_id"]
    assert evaluation.trace_id == state["trace_id"]
    assert evaluation.agent_id == result.agent_id
    assert evaluation.agent_version == result.agent_version
    assert evaluation.routing_decision_ref.contract_id == "C-067"
    assert (
        evaluation.routing_decision_ref.entity_id == result.routing_decision.request_id
    )
    assert evaluation.routing_decision_ref.schema_version == "1"
    assert evaluation.provider_id == "approved-provider"
    assert evaluation.model_id == "approved-model"
    assert evaluation.model_version == "model-v1"
    assert evaluation.prompt_id == "spot-summary"
    assert evaluation.prompt_version == "prompt-v1"
    assert evaluation.output_contract_id == "C-069"
    assert evaluation.output_schema_version == "1"
    assert evaluation.evaluation_method_id == AGENT_EVALUATION_METHOD_ID
    assert evaluation.evaluation_method_version == AGENT_EVALUATION_METHOD_VERSION
    assert evaluation.environment is DeploymentEnvironment.TEST
    assert evaluation.mode is OperatingMode.RESEARCH
    assert evaluation.outcome is AgentEvaluationOutcome.COMPLETED
    assert evaluation.result_status is AgentResultStatus.COMPLETE
    assert evaluation.schema_state is AgentEvaluationSchemaState.VALID
    assert evaluation.started_at <= evaluation.ended_at <= evaluation.evaluated_at
    assert evaluation.duration_ms == 1000


@pytest.mark.parametrize(
    "status", [AgentResultStatus.NO_TRADE, AgentResultStatus.INSUFFICIENT_DATA]
)
def test_non_action_c062_statuses_remain_valid_evaluation_results(
    status: AgentResultStatus,
) -> None:
    evaluation = _run(_result(status))

    assert evaluation.outcome is AgentEvaluationOutcome.COMPLETED
    assert evaluation.result_status is status
    assert evaluation.schema_state is AgentEvaluationSchemaState.VALID


def test_invocation_evaluation_failure_is_recorded_without_exception_content() -> None:
    class FailedGraph:
        async def ainvoke(self, _state: object, *, config: object) -> object:
            raise RuntimeError("private chain-of-thought and secret=do-not-copy")

    evaluation = _run(_result(), graph=FailedGraph())
    payload = serialize_contract(evaluation, payload_version="1")

    assert evaluation.outcome is AgentEvaluationOutcome.FAILED
    assert evaluation.result_status is AgentResultStatus.COMPLETE
    assert (
        evaluation.failure_classification
        is AgentEvaluationFailureClass.EVALUATION_FAILURE
    )
    assert evaluation.schema_state is AgentEvaluationSchemaState.UNKNOWN
    assert "private chain-of-thought" not in payload
    assert "do-not-copy" not in payload


def test_timeout_is_recorded_as_distinct_from_c062_status() -> None:
    class SlowGraph:
        async def ainvoke(self, _state: object, *, config: object) -> object:
            await asyncio.sleep(0.05)
            return {}

    result = _result(AgentResultStatus.INSUFFICIENT_DATA)
    evaluation = _run(result, graph=SlowGraph(), timeout_seconds=0.001)

    assert evaluation.outcome is AgentEvaluationOutcome.TIMED_OUT
    assert evaluation.result_status is AgentResultStatus.INSUFFICIENT_DATA
    assert (
        evaluation.failure_classification
        is AgentEvaluationFailureClass.EVALUATION_TIMEOUT
    )
    assert evaluation.schema_state is AgentEvaluationSchemaState.UNKNOWN


def test_invalid_output_schema_is_explicit_and_fail_closed() -> None:
    @dataclass(frozen=True)
    class UnknownOutput:
        contract_id: str = "C-999"
        schema_version: str = "1"

    result = replace(_result(), output=UnknownOutput())
    evaluation = _run(result)

    assert evaluation.outcome is AgentEvaluationOutcome.REJECTED_INVALID
    assert evaluation.result_status is AgentResultStatus.COMPLETE
    assert evaluation.schema_state is AgentEvaluationSchemaState.INVALID
    assert (
        evaluation.failure_classification
        is AgentEvaluationFailureClass.OUTPUT_SCHEMA_INVALID
    )
    assert evaluation.output_contract_id == "C-999"
    assert evaluation.output_schema_version == "1"


def test_unknown_output_shape_is_explicit_and_fail_closed() -> None:
    result = replace(_result(), output="untyped provider content")
    evaluation = _run(result)

    assert evaluation.outcome is AgentEvaluationOutcome.REJECTED_INVALID
    assert evaluation.schema_state is AgentEvaluationSchemaState.UNKNOWN
    assert evaluation.output_contract_id is None
    assert evaluation.output_schema_version is None


def test_invalid_timestamp_order_is_preserved_without_fabricated_latency() -> None:
    result = replace(_result(), generated_at=NOW - timedelta(seconds=3))
    evaluation = _run(result)

    assert evaluation.outcome is AgentEvaluationOutcome.REJECTED_INVALID
    assert evaluation.started_at > evaluation.ended_at
    assert evaluation.duration_ms is None


def test_evidence_references_are_exact_and_grounding_is_non_numeric() -> None:
    result = _result()
    evaluation = _run(result)

    assert evaluation.supporting_evidence_ids == result.supporting_evidence_ids
    assert evaluation.contradicting_evidence_ids == result.contradicting_evidence_ids
    assert evaluation.grounding_state is AgentGroundingState.REFERENCES_VALIDATED
    assert not any("score" in field.name for field in fields(evaluation))


def test_calibration_and_reliability_are_reference_only_hooks() -> None:
    result = _result()
    calibration = ContractReference("C-031", uuid4(), "1")
    reliability = ContractReference("C-052", uuid4(), "1")
    evaluation = _run(
        result,
        calibration_refs=(calibration,),
        reliability_refs=(reliability,),
    )

    assert evaluation.calibration_refs == (calibration,)
    assert evaluation.reliability_refs == (reliability,)
    assert not any(
        token in field.name.lower()
        for field in fields(evaluation)
        for token in ("probability", "brier", "win_rate", "precision", "recall")
    )

    with pytest.raises(AgentContractError, match="C-031/C-052"):
        _run(
            result,
            calibration_refs=(ContractReference("C-060", uuid4(), "1"),),
        )


def test_contract_has_no_prompt_secret_reasoning_or_authority_fields() -> None:
    evaluation = _run(_result())
    field_names = {field.name.lower() for field in fields(evaluation)}
    payload = serialize_contract(evaluation, payload_version="1")

    assert not any(
        token in field_name
        for field_name in field_names
        for token in ("prompt_content", "secret", "credential", "reasoning", "content")
    )
    assert "prompt_content" not in payload
    assert "chain-of-thought" not in payload
    assert not hasattr(evaluation, "approve")
    assert not hasattr(evaluation, "authorize")
    assert not hasattr(evaluation, "execute")


def test_canonical_serialization_hash_and_schema_version_are_stable() -> None:
    evaluation = _run(_result())
    first = serialize_contract(evaluation, payload_version="1")
    equivalent = replace(evaluation)

    assert first == serialize_contract(equivalent, payload_version="1")
    digest = canonical_sha256(evaluation)
    assert digest == canonical_sha256(equivalent)
    assert len(digest) == 64
    assert evaluation.schema_version == "1"


def test_personal_spot_evaluation_cannot_run_outside_research_mode() -> None:
    result = _result()
    expectation = _expectation(result)
    graph = build_spot_result_graph(
        expectation=expectation, checkpointer=None, clock=lambda: NOW
    )

    with pytest.raises(ValueError, match="require research mode"):
        asyncio.run(
            run_spot_result_graph(
                graph,
                expectation=expectation,
                correlation_id=uuid4(),
                trace_id=uuid4(),
                environment=DeploymentEnvironment.TEST,
                mode=OperatingMode.LIVE_SUPERVISED,
                agent_result=result,
                thread_id=str(result.task_id),
            )
        )
