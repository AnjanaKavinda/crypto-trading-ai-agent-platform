from __future__ import annotations

import re
from collections.abc import Sequence
from datetime import datetime
from uuid import UUID, uuid4

from trading_platform_api.agents.contracts import (
    AGENT_EVALUATION_METHOD_ID,
    AGENT_EVALUATION_METHOD_VERSION,
    AgentEvaluation,
    AgentEvaluationFailureClass,
    AgentEvaluationOutcome,
    AgentEvaluationSchemaState,
    AgentGroundingState,
    AgentResult,
)
from trading_platform_api.agents.result_validation import AgentResultExpectation
from trading_platform_api.config import DeploymentEnvironment, OperatingMode
from trading_platform_api.contracts.serialization import (
    ContractSerializationError,
    canonical_json_dumps,
)
from trading_platform_api.risk import ContractReference

_CONTRACT_ID = re.compile(r"C-[0-9]{3}")


def build_agent_evaluation(
    result: AgentResult,
    *,
    expectation: AgentResultExpectation,
    correlation_id: UUID,
    trace_id: UUID,
    environment: DeploymentEnvironment,
    mode: OperatingMode,
    started_at: datetime,
    ended_at: datetime,
    evaluated_at: datetime,
    duration_ms: int | None,
    outcome: AgentEvaluationOutcome,
    failure_classification: AgentEvaluationFailureClass | None,
    validation_completed: bool,
    calibration_refs: Sequence[ContractReference] = (),
    reliability_refs: Sequence[ContractReference] = (),
) -> AgentEvaluation:
    """Build C-066 from one C-062 result without copying provider output.

    The method validates the result against the caller's trusted C-062
    expectation. Grounding state reports only whether the exact evidence IDs
    are present and allowlisted; it does not score evidence quality.
    """

    if not isinstance(result, AgentResult):
        raise TypeError("a typed C-062 AgentResult is required")
    if not isinstance(expectation, AgentResultExpectation):
        raise TypeError("a trusted AgentResultExpectation is required")
    schema_state, output_contract_id, output_schema_version = _schema_binding(
        result.output,
        expectation=expectation,
        validation_completed=validation_completed,
    )
    evidence_ids = set(result.supporting_evidence_ids) | set(
        result.contradicting_evidence_ids
    )
    if not validation_completed:
        grounding_state = AgentGroundingState.UNKNOWN
    elif not evidence_ids:
        grounding_state = AgentGroundingState.NO_REFERENCES
    elif evidence_ids.issubset(set(expectation.allowed_evidence_ids)):
        grounding_state = AgentGroundingState.REFERENCES_VALIDATED
    else:
        grounding_state = AgentGroundingState.INVALID_REFERENCES

    if (
        outcome is AgentEvaluationOutcome.REJECTED_INVALID
        and schema_state is AgentEvaluationSchemaState.INVALID
    ):
        failure_classification = AgentEvaluationFailureClass.OUTPUT_SCHEMA_INVALID

    return AgentEvaluation(
        evaluation_id=uuid4(),
        result_id=result.result_id,
        result_schema_version=result.schema_version,
        task_id=result.task_id,
        context_id=result.context_id,
        correlation_id=correlation_id,
        trace_id=trace_id,
        agent_id=result.agent_id,
        agent_version=result.agent_version,
        routing_decision_ref=ContractReference(
            "C-067",
            result.routing_decision.request_id,
            result.routing_decision.schema_version,
        ),
        provider_id=result.routing_decision.provider_id,
        model_id=result.routing_decision.model_id,
        model_version=result.routing_decision.model_version,
        prompt_id=result.routing_decision.prompt_id,
        prompt_version=result.routing_decision.prompt_version,
        output_contract_id=output_contract_id,
        output_schema_version=output_schema_version,
        evaluation_method_id=AGENT_EVALUATION_METHOD_ID,
        evaluation_method_version=AGENT_EVALUATION_METHOD_VERSION,
        environment=environment,
        mode=mode,
        started_at=started_at,
        ended_at=ended_at,
        evaluated_at=evaluated_at,
        duration_ms=duration_ms,
        outcome=outcome,
        result_status=result.status,
        schema_state=schema_state,
        failure_classification=failure_classification,
        supporting_evidence_ids=result.supporting_evidence_ids,
        contradicting_evidence_ids=result.contradicting_evidence_ids,
        grounding_state=grounding_state,
        calibration_refs=tuple(calibration_refs),
        reliability_refs=tuple(reliability_refs),
    )


def _schema_binding(
    output: object,
    *,
    expectation: AgentResultExpectation,
    validation_completed: bool,
) -> tuple[AgentEvaluationSchemaState, str | None, str | None]:
    contract_id = getattr(
        type(output), "__contract_id__", getattr(output, "contract_id", None)
    )
    schema_version = getattr(output, "schema_version", None)
    if (
        not isinstance(contract_id, str)
        or _CONTRACT_ID.fullmatch(contract_id) is None
        or not isinstance(schema_version, str)
        or not schema_version.strip()
        or schema_version != schema_version.strip()
    ):
        return AgentEvaluationSchemaState.UNKNOWN, None, None
    if not validation_completed:
        return AgentEvaluationSchemaState.UNKNOWN, contract_id, schema_version

    allowed = expectation.allowed_output_schemas.get(contract_id)
    params = getattr(type(output), "__dataclass_params__", None)
    if (
        allowed is None
        or type(output) is not allowed[1]
        or schema_version != allowed[0]
        or not getattr(params, "frozen", False)
    ):
        return AgentEvaluationSchemaState.INVALID, contract_id, schema_version
    try:
        canonical_json_dumps(output)
    except (ContractSerializationError, TypeError, ValueError):
        return AgentEvaluationSchemaState.INVALID, contract_id, schema_version
    return AgentEvaluationSchemaState.VALID, contract_id, schema_version


__all__ = [
    "AGENT_EVALUATION_METHOD_ID",
    "AGENT_EVALUATION_METHOD_VERSION",
    "build_agent_evaluation",
]
