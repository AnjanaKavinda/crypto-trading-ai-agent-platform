from dataclasses import FrozenInstanceError, replace

import pytest
from trading_platform_api.agents import (
    AgentContractError,
    AgentDefinition,
    AgentRegistry,
    AgentRegistryError,
    PERSONAL_SPOT_AGENT_REGISTRY,
    PERSONAL_SPOT_RESEARCH_AGENT,
    resolve_agent_definition,
)


def definition() -> AgentDefinition:
    return AgentDefinition(
        agent_id="test-research-agent",
        agent_version="1",
        role="research-analyst",
        purpose="Interpret validated inputs.",
        allowed_inputs=("C-002",),
        allowed_outputs=("C-006",),
        allowed_tools=(),
        allowed_modes=("PERSONAL_SPOT_RESEARCH",),
        dependencies=("validated-spot-profile",),
        authority_boundaries=("analysis-only", "no-execution"),
    )


def test_personal_spot_definition_is_exact_profile_and_has_no_granted_access() -> None:
    agent = resolve_agent_definition("personal-spot-research", "1")

    assert agent is PERSONAL_SPOT_RESEARCH_AGENT
    assert (
        PERSONAL_SPOT_AGENT_REGISTRY.resolve(agent.agent_id, agent.agent_version)
        == agent
    )
    assert agent.contract_id == "C-061"
    assert agent.schema_version == "1"
    assert agent.allowed_modes == ("PERSONAL_SPOT_RESEARCH",)
    assert agent.allowed_tools == ()
    assert agent.permissions_granted is False
    assert not {"C-061", "C-063", "C-064"}.intersection(agent.allowed_outputs)
    assert "no-deterministic-risk-authority" in agent.authority_boundaries
    assert "no-human-approval-authority" in agent.authority_boundaries
    assert "no-order-or-exchange-execution-authority" in agent.authority_boundaries


def test_registry_is_exact_versioned_and_rejects_redefinition() -> None:
    registered = definition()
    registry = AgentRegistry((registered,))

    assert registry.resolve(registered.agent_id, "1") is registered
    with pytest.raises(AgentRegistryError, match="exact registered"):
        registry.resolve(registered.agent_id, "2")
    with pytest.raises(AgentRegistryError, match="immutable"):
        registry.register(replace(registered, purpose="Changed meaning."))
    assert registry.register(registered) is registered


def test_registry_snapshot_cannot_mutate_registry() -> None:
    registered = definition()
    registry = AgentRegistry((registered,))

    with pytest.raises(TypeError):
        registry.definitions[("other", "1")] = registered  # type: ignore[index]
    assert registry.resolve(registered.agent_id, registered.agent_version) is registered


@pytest.mark.parametrize(
    "changes",
    [
        {"allowed_inputs": ["C-002"]},
        {"allowed_outputs": ()},
        {"allowed_modes": ()},
        {"authority_boundaries": ()},
        {"allowed_inputs": ("C-002", "C-002")},
    ],
)
def test_invalid_or_unbounded_definition_is_rejected(
    changes: dict[str, object],
) -> None:
    values = {
        "agent_id": "invalid-agent",
        "agent_version": "1",
        "role": "analyst",
        "purpose": "Interpret validated inputs.",
        "allowed_inputs": ("C-002",),
        "allowed_outputs": ("C-006",),
        "allowed_tools": (),
        "allowed_modes": ("PERSONAL_SPOT_RESEARCH",),
        "dependencies": (),
        "authority_boundaries": ("analysis-only",),
    }
    values.update(changes)

    with pytest.raises(AgentContractError):
        AgentDefinition(**values)  # type: ignore[arg-type]


def test_definition_is_frozen_and_registry_requires_a_contract() -> None:
    agent = definition()
    with pytest.raises(FrozenInstanceError):
        agent.role = "different-role"  # type: ignore[misc]
    with pytest.raises(AgentRegistryError, match="validated C-061"):
        AgentRegistry().register(object())  # type: ignore[arg-type]
