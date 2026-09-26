"""Reusable assertions for canonical contract tests.

This module deliberately stays in the test tree.  It exercises the public
serialization and versioning APIs without becoming a second schema registry or
an untrusted-data-to-domain-object decoder.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from trading_platform_api.contracts import (
    CANONICAL_JSON_VERSION,
    CompatibilityReport,
    CompatibilityStatus,
    ContractSchemaDescriptor,
    ParsedContractDocument,
    SupportedVersionTransition,
    UnknownFieldPolicy,
    assess_schema_compatibility,
    canonical_sha256,
    contract_document,
    describe_dataclass_contract,
    parse_contract_document,
    serialize_contract,
)


@dataclass(frozen=True, slots=True)
class ContractHarnessCase:
    """The explicit wire contract expected for one valid domain instance."""

    instance: object
    descriptor: ContractSchemaDescriptor

    @classmethod
    def from_contract(
        cls, instance: object, *, payload_version: str
    ) -> ContractHarnessCase:
        descriptor = describe_dataclass_contract(
            type(instance), payload_version=payload_version
        )
        return cls(instance=instance, descriptor=descriptor)

    @property
    def required_payload_fields(self) -> tuple[str, ...]:
        return tuple(item.name for item in self.descriptor.fields if item.required)

    @property
    def optional_payload_fields(self) -> tuple[str, ...]:
        return tuple(item.name for item in self.descriptor.fields if not item.required)


def _plain_data(value: object) -> object:
    if isinstance(value, Mapping):
        return {key: _plain_data(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_plain_data(item) for item in value]
    return value


def parse_case_document(
    case: ContractHarnessCase,
    serialized: str | bytes,
    *,
    supported_canonicalization_versions: tuple[str, ...] = (CANONICAL_JSON_VERSION,),
    supported_schema_versions: tuple[str, ...] | None = None,
    supported_payload_versions: tuple[str, ...] | None = None,
    unknown_field_policy: UnknownFieldPolicy = UnknownFieldPolicy.REJECT,
) -> ParsedContractDocument:
    """Parse plain canonical data under the exact schema declared by ``case``."""

    descriptor = case.descriptor
    return parse_contract_document(
        serialized,
        expected_contract_id=descriptor.contract_id,
        supported_canonicalization_versions=supported_canonicalization_versions,
        supported_schema_versions=(descriptor.schema_version,)
        if supported_schema_versions is None
        else supported_schema_versions,
        supported_payload_versions=(descriptor.payload_version,)
        if supported_payload_versions is None
        else supported_payload_versions,
        required_payload_fields=case.required_payload_fields,
        optional_payload_fields=case.optional_payload_fields,
        unknown_field_policy=unknown_field_policy,
    )


def assert_canonical_round_trip(
    case: ContractHarnessCase,
) -> ParsedContractDocument:
    """Prove deterministic serialization and a strict plain-data round trip."""

    descriptor = case.descriptor
    first = serialize_contract(
        case.instance, payload_version=descriptor.payload_version
    )
    second = serialize_contract(
        case.instance, payload_version=descriptor.payload_version
    )
    assert first == second

    document = contract_document(
        case.instance, payload_version=descriptor.payload_version
    )
    assert set(document["payload"]) == {
        *case.required_payload_fields,
        *case.optional_payload_fields,
    }

    parsed = parse_case_document(case, first)
    assert parsed.contract_id == descriptor.contract_id
    assert parsed.schema_version == descriptor.schema_version
    assert parsed.payload_version == descriptor.payload_version
    assert _plain_data(parsed.payload) == document["payload"]
    return parsed


def assert_stable_schema_descriptor(
    contract_type: type[object], *, payload_version: str
) -> ContractSchemaDescriptor:
    """Prove repeated schema inspection yields identical content and digest."""

    first = describe_dataclass_contract(contract_type, payload_version=payload_version)
    second = describe_dataclass_contract(contract_type, payload_version=payload_version)
    assert first == second
    assert canonical_sha256(first) == canonical_sha256(second)
    return first


def assert_unique_contract_ids(
    contract_types: tuple[type[object], ...], *, payload_version: str
) -> tuple[ContractSchemaDescriptor, ...]:
    """Fail when two canonical schema types claim the same contract identity."""

    descriptors = tuple(
        assert_stable_schema_descriptor(item, payload_version=payload_version)
        for item in contract_types
    )
    owners: dict[str, type[object]] = {}
    for contract_type, descriptor in zip(contract_types, descriptors, strict=True):
        previous = owners.get(descriptor.contract_id)
        assert previous is None, (
            f"duplicate canonical contract id {descriptor.contract_id}: "
            f"{previous.__module__}.{previous.__qualname__} and "
            f"{contract_type.__module__}.{contract_type.__qualname__}"
        )
        owners[descriptor.contract_id] = contract_type
    return descriptors


def assert_compatibility(
    previous: ContractSchemaDescriptor,
    current: ContractSchemaDescriptor,
    expected_status: CompatibilityStatus,
    *,
    supported_transitions: tuple[SupportedVersionTransition, ...] = (),
) -> CompatibilityReport:
    """Assert deterministic compatibility classification and report hashing."""

    first = assess_schema_compatibility(
        previous,
        current,
        supported_transitions=supported_transitions,
    )
    second = assess_schema_compatibility(
        previous,
        current,
        supported_transitions=supported_transitions,
    )
    assert first == second
    assert first.status is expected_status
    assert canonical_sha256(first) == canonical_sha256(second)
    return first
