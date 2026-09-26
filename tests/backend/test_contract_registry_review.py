from __future__ import annotations

import dataclasses
import importlib
import inspect
import re
from collections import defaultdict
from pathlib import Path

from trading_platform_api.analysis import AgentIndependenceReference
from trading_platform_api.audit import AuditEvent
from trading_platform_api.contracts import describe_dataclass_contract
from trading_platform_api.learning import (
    CalibrationRecord,
    Experience,
    ExperienceRecord,
)
from trading_platform_api.strategy import ValidationReference
from trading_platform_api.validation import CalibrationResult

REGISTRY_PATH = Path("docs/cross-cutting/01-domain-contract-registry.md")
CONTRACT_PACKAGES = (
    "market_data",
    "analysis",
    "strategy",
    "validation",
    "risk",
    "execution",
    "safety",
    "learning",
)
DEFERRED_CONTRACTS = {
    "C-061": "AgentDefinition",
    "C-062": "AgentResult",
    "C-063": "AgentPermissionProfile",
    "C-064": "AgentToolAccess",
    "C-065": "AgentHandoff",
    "C-066": "AgentEvaluation",
    "C-067": "ModelRoutingDecision",
    "C-093": "AgentIndependenceReport",
}
REFERENCE_ONLY_TYPES = {
    ValidationReference: "C-028",
    AgentIndependenceReference: "C-093",
}
ALIAS_NAMES = {"CalibrationRecord", "ExperienceRecord"}
AUTHORITY_METHOD_NAMES = {
    "approve",
    "authorize",
    "execute",
    "place_order",
    "send_order",
    "submit_order",
    "trade",
}


def _registry_rows() -> dict[str, str]:
    rows: dict[str, str] = {}
    pattern = re.compile(r"^\| (C-\d{3}) \| `?([^|`]+?)`? \|")
    for line in REGISTRY_PATH.read_text(encoding="utf-8").splitlines():
        match = pattern.match(line)
        if match is None:
            continue
        contract_id, name = match.groups()
        assert contract_id not in rows, f"duplicate registry row {contract_id}"
        rows[contract_id] = name.strip()
    return rows


def _fixed_contract_id(contract_type: type[object]) -> str | None:
    class_value = getattr(contract_type, "contract_id", None)
    if isinstance(class_value, str):
        return class_value
    for item in dataclasses.fields(contract_type):
        if item.name == "contract_id" and isinstance(item.default, str):
            return item.default
    return None


def _exported_contract_candidates() -> tuple[tuple[str, type[object]], ...]:
    candidates: list[tuple[str, type[object]]] = []
    for package_name in CONTRACT_PACKAGES:
        package = importlib.import_module(f"trading_platform_api.{package_name}")
        for export_name in package.__all__:
            exported = getattr(package, export_name)
            if (
                inspect.isclass(exported)
                and dataclasses.is_dataclass(exported)
                and _fixed_contract_id(exported) is not None
            ):
                candidates.append((export_name, exported))
    candidates.append(("AuditEvent", AuditEvent))
    return tuple(candidates)


def _canonical_owners() -> dict[str, type[object]]:
    owners_by_id: dict[str, list[tuple[str, type[object]]]] = defaultdict(list)
    reference_types = set(REFERENCE_ONLY_TYPES)
    for export_name, contract_type in _exported_contract_candidates():
        if export_name in ALIAS_NAMES or contract_type in reference_types:
            continue
        contract_id = _fixed_contract_id(contract_type)
        assert contract_id is not None
        owners_by_id[contract_id].append((export_name, contract_type))

    duplicates = {
        contract_id: [name for name, _ in owners]
        for contract_id, owners in owners_by_id.items()
        if len(owners) != 1
    }
    assert duplicates == {}, f"duplicate canonical owners: {duplicates}"
    return {contract_id: owners[0][1] for contract_id, owners in owners_by_id.items()}


def test_registry_classifies_every_canonical_contract() -> None:
    registry = _registry_rows()
    owners = _canonical_owners()

    assert set(registry) == {f"C-{number:03d}" for number in range(1, 101)}
    assert len(set(registry.values())) == 100
    assert set(owners) == set(registry) - set(DEFERRED_CONTRACTS)
    assert len(owners) == 92
    assert {
        contract_id: registry[contract_id] for contract_id in DEFERRED_CONTRACTS
    } == DEFERRED_CONTRACTS
    assert {
        contract_id: contract_type.__name__
        for contract_id, contract_type in owners.items()
    } == {contract_id: registry[contract_id] for contract_id in owners}


def test_every_canonical_owner_has_stable_v1_schema_metadata() -> None:
    for contract_id, contract_type in _canonical_owners().items():
        parameters = contract_type.__dataclass_params__
        assert parameters.frozen is True, contract_type.__qualname__
        assert hasattr(contract_type, "__slots__"), contract_type.__qualname__

        first = describe_dataclass_contract(contract_type, payload_version="wire-1")
        second = describe_dataclass_contract(contract_type, payload_version="wire-1")
        assert first == second
        assert first.contract_id == contract_id
        assert first.schema_version == "1"


def test_aliases_and_reference_only_types_are_not_competing_owners() -> None:
    assert ExperienceRecord is Experience
    assert CalibrationRecord is CalibrationResult
    assert _fixed_contract_id(ValidationReference) == "C-028"
    assert _fixed_contract_id(AgentIndependenceReference) == "C-093"

    owners = _canonical_owners()
    assert owners["C-028"].__name__ == "ValidationResult"
    assert "C-093" not in owners


def test_c060_uses_the_canonical_contract_machinery() -> None:
    descriptor = describe_dataclass_contract(AuditEvent, payload_version="wire-1")

    assert descriptor.contract_id == "C-060"
    assert descriptor.schema_version == "1"
    assert {item.name for item in descriptor.fields}.issuperset(
        {"event_type", "actor", "action", "correlation_id", "trace_id"}
    )


def test_contract_models_expose_no_imperative_trading_authority() -> None:
    for contract_type in _canonical_owners().values():
        exposed = {
            name
            for name, value in inspect.getmembers(contract_type)
            if callable(value) and not name.startswith("__")
        }
        assert exposed.isdisjoint(AUTHORITY_METHOD_NAMES), contract_type.__qualname__
