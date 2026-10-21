from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, is_dataclass
from datetime import UTC, datetime
from types import MappingProxyType
from typing import TypeAlias
from uuid import UUID

from trading_platform_api.agents.contracts import (
    AgentContractError,
    AgentResult,
    AgentResultStatus,
    ModelRoutingDecision,
)
from trading_platform_api.contracts.serialization import (
    ContractSerializationError,
    canonical_json_dumps,
)

OutputSchema: TypeAlias = tuple[str, type[object]]


class AgentResultValidationError(ValueError):
    """Raised when an untrusted agent result is not safe for downstream use."""


@dataclass(frozen=True, slots=True)
class AgentResultExpectation:
    """Trusted task binding and exact output-schema allowlist from the caller."""

    task_id: UUID
    context_id: UUID
    agent_id: str
    agent_version: str
    routing_decision: ModelRoutingDecision
    allowed_tool_access_ids: tuple[UUID, ...]
    allowed_evidence_ids: tuple[UUID, ...]
    allowed_output_schemas: Mapping[str, OutputSchema]

    def __post_init__(self) -> None:
        if not isinstance(self.task_id, UUID) or not isinstance(self.context_id, UUID):
            raise AgentResultValidationError("task binding is invalid.")
        if not isinstance(self.agent_id, str) or not self.agent_id.strip():
            raise AgentResultValidationError("agent binding is invalid.")
        if not isinstance(self.agent_version, str) or not self.agent_version.strip():
            raise AgentResultValidationError("agent version binding is invalid.")
        if not isinstance(self.routing_decision, ModelRoutingDecision):
            raise AgentResultValidationError("validated model routing is required.")
        if not isinstance(self.allowed_tool_access_ids, tuple) or any(
            not isinstance(item, UUID) for item in self.allowed_tool_access_ids
        ):
            raise AgentResultValidationError("tool allowlist is invalid.")
        if len(set(self.allowed_tool_access_ids)) != len(self.allowed_tool_access_ids):
            raise AgentResultValidationError("tool allowlist contains duplicates.")
        if not isinstance(self.allowed_evidence_ids, tuple) or any(
            not isinstance(item, UUID) for item in self.allowed_evidence_ids
        ):
            raise AgentResultValidationError("evidence allowlist is invalid.")
        if len(set(self.allowed_evidence_ids)) != len(self.allowed_evidence_ids):
            raise AgentResultValidationError("evidence allowlist contains duplicates.")
        if not isinstance(self.allowed_output_schemas, Mapping):
            raise AgentResultValidationError("output schema allowlist is required.")
        schemas = dict(self.allowed_output_schemas)
        for contract_id, schema in schemas.items():
            if (
                not isinstance(contract_id, str)
                or re.fullmatch(r"C-[0-9]{3}", contract_id) is None
                or not isinstance(schema, tuple)
                or len(schema) != 2
                or not isinstance(schema[0], str)
                or not isinstance(schema[1], type)
            ):
                raise AgentResultValidationError("output schema allowlist is invalid.")
        object.__setattr__(self, "allowed_output_schemas", MappingProxyType(schemas))


def validate_agent_result(
    result: object, *, expectation: AgentResultExpectation, now: datetime
) -> AgentResult:
    """Validate C-062 against trusted task, route, tool, time, and schema bindings.

    The allowlist is supplied by trusted application code and maps each permitted
    contract ID to its exact schema version and exact frozen dataclass type. The
    validator does not coerce provider output or infer a missing contract.
    """

    if not isinstance(expectation, AgentResultExpectation):
        raise AgentResultValidationError("trusted result expectations are required.")
    if not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None:
        raise AgentResultValidationError("validation time must be timezone-aware.")
    instant = now.astimezone(UTC)
    if not isinstance(result, AgentResult):
        raise AgentResultValidationError("result is not a typed C-062 AgentResult.")
    try:
        if result.task_id != expectation.task_id:
            raise AgentResultValidationError("task identity does not match.")
        if result.context_id != expectation.context_id:
            raise AgentResultValidationError("context identity does not match.")
        if (result.agent_id, result.agent_version) != (
            expectation.agent_id,
            expectation.agent_version,
        ):
            raise AgentResultValidationError("agent identity does not match.")
        if result.routing_decision != expectation.routing_decision:
            raise AgentResultValidationError("model/prompt provenance does not match.")
        if not set(result.tool_access_ids).issubset(
            expectation.allowed_tool_access_ids
        ):
            raise AgentResultValidationError("tool provenance is not allowed.")
        evidence_refs = set(result.supporting_evidence_ids) | set(
            result.contradicting_evidence_ids
        )
        if not evidence_refs.issubset(expectation.allowed_evidence_ids):
            raise AgentResultValidationError("evidence provenance is not allowed.")
        if result.generated_at > instant:
            raise AgentResultValidationError("result timestamp is future-dated.")
        if result.generated_at < result.routing_decision.decided_at:
            raise AgentResultValidationError("result predates its routing decision.")
        if result.routing_decision.expires_at <= instant:
            raise AgentResultValidationError("model/prompt provenance has expired.")
        if result.expires_at <= instant:
            raise AgentResultValidationError("result has expired.")
        if (
            result.status is AgentResultStatus.INSUFFICIENT_DATA
            and not result.unresolved_risks
        ):
            raise AgentResultValidationError(
                "INSUFFICIENT_DATA results must explain the unresolved gap."
            )

        # Runtime-agent contracts declare this identity on their type, while the
        # approved analysis contracts carry it as a frozen dataclass field. The
        # exact output type remains allowlisted below, so reading the instance
        # field does not permit coercion or an unregistered schema.
        contract_id = getattr(
            type(result.output),
            "__contract_id__",
            getattr(result.output, "contract_id", None),
        )
        if not isinstance(contract_id, str):
            raise AgentResultValidationError("output contract identity is missing.")
        schema = expectation.allowed_output_schemas.get(contract_id)
        if schema is None:
            raise AgentResultValidationError("output contract is not allowlisted.")
        schema_version, expected_type = schema
        if type(result.output) is not expected_type:
            raise AgentResultValidationError("output type does not match its schema.")
        params = getattr(type(result.output), "__dataclass_params__", None)
        if not is_dataclass(result.output) or not getattr(params, "frozen", False):
            raise AgentResultValidationError("output must be an immutable contract.")
        if (
            getattr(result.output, "contract_id", None) != contract_id
            or getattr(result.output, "schema_version", None) != schema_version
        ):
            raise AgentResultValidationError("output contract version is unknown.")
        canonical_json_dumps(result.output)
        return result
    except (AgentContractError, ContractSerializationError, AttributeError, TypeError):
        raise AgentResultValidationError(
            "result failed structural or canonical contract validation."
        ) from None
