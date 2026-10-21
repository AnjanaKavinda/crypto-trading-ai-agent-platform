from __future__ import annotations

from types import MappingProxyType
from typing import Mapping

from trading_platform_api.agents.contracts import AgentDefinition


class AgentRegistryError(ValueError):
    """Raised when an agent definition cannot be registered or resolved."""


class AgentRegistry:
    """In-memory immutable-version index; registration never grants permissions."""

    def __init__(self, definitions: tuple[AgentDefinition, ...] = ()) -> None:
        self._definitions: dict[tuple[str, str], AgentDefinition] = {}
        for definition in definitions:
            self.register(definition)

    @property
    def definitions(self) -> Mapping[tuple[str, str], AgentDefinition]:
        return MappingProxyType(self._definitions.copy())

    def register(self, definition: AgentDefinition) -> AgentDefinition:
        if not isinstance(definition, AgentDefinition):
            raise AgentRegistryError("definition must be a validated C-061 contract.")
        key = (definition.agent_id, definition.agent_version)
        existing = self._definitions.get(key)
        if existing is not None:
            if existing == definition:
                return existing
            raise AgentRegistryError("registered agent versions are immutable.")
        self._definitions[key] = definition
        return definition

    def resolve(self, agent_id: str, agent_version: str) -> AgentDefinition:
        try:
            return self._definitions[(agent_id, agent_version)]
        except (KeyError, TypeError):
            raise AgentRegistryError(
                "exact registered agent version is unavailable."
            ) from None


PERSONAL_SPOT_RESEARCH_AGENT = AgentDefinition(
    agent_id="personal-spot-research",
    agent_version="1",
    role="spot-market-research-analyst",
    purpose=(
        "Interpret validated Spot research inputs and return attributable "
        "analysis for the single-user read-only research profile."
    ),
    allowed_inputs=("C-002", "C-003", "C-004", "C-005", "C-068"),
    allowed_outputs=("C-006", "C-007", "C-008", "C-009", "C-010", "C-019", "C-069"),
    allowed_tools=(),
    allowed_modes=("PERSONAL_SPOT_RESEARCH",),
    dependencies=("validated-spot-profile", "approved-model-route-C-067"),
    authority_boundaries=(
        "analysis-only",
        "no-deterministic-risk-authority",
        "no-human-approval-authority",
        "no-order-or-exchange-execution-authority",
        "non-action outcomes remain valid",
    ),
)


PERSONAL_SPOT_AGENT_REGISTRY = AgentRegistry((PERSONAL_SPOT_RESEARCH_AGENT,))


def resolve_agent_definition(agent_id: str, agent_version: str) -> AgentDefinition:
    """Resolve only the explicitly registered version; never use a latest alias."""

    try:
        return PERSONAL_SPOT_AGENT_REGISTRY.resolve(agent_id, agent_version)
    except AgentRegistryError:
        raise
