from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import FrozenInstanceError, dataclass, field, fields, replace
from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal
from enum import StrEnum
from types import MappingProxyType
from uuid import UUID, uuid4

import pytest
import trading_platform_api.contracts as contracts_package
from trading_platform_api.contracts import (
    CANONICAL_JSON_VERSION,
    MAX_DOCUMENT_BYTES,
    MAX_NESTING_DEPTH,
    BreakingChangeEvidence,
    CompatibilityStatus,
    ContractSchemaDescriptor,
    ContractSerializationError,
    ParsedContractDocument,
    SchemaChangeKind,
    SchemaFieldDescriptor,
    SchemaVersioningError,
    SupportedVersionTransition,
    UnknownFieldPolicy,
    assess_schema_compatibility,
    canonical_json_dumps,
    canonical_sha256,
    compatibility_report_sha256,
    contract_document,
    contract_sha256,
    describe_dataclass_contract,
    parse_contract_document,
    require_governed_compatibility,
    serialize_contract,
    to_canonical_data,
)
from trading_platform_api.risk import ContractReference
from trading_platform_api.strategy import (
    NoTradeDecision,
    NoTradeReason,
    SignalLifecycleState,
    VersionReference,
)

NOW = datetime(2026, 9, 26, 15, 0, tzinfo=UTC)
IDENTITY = UUID("12345678-1234-5678-90ab-1234567890ab")
SHA_A = "a" * 64


class SyntheticState(StrEnum):
    READY = "READY"
    BLOCKED = "BLOCKED"


@dataclass(frozen=True, slots=True)
class SyntheticChild:
    name: str
    amount: Decimal


@dataclass(frozen=True, slots=True)
class SyntheticContract:
    CONTRACT_ID = "C-777"
    SCHEMA_VERSION = "1"

    entity_id: UUID
    created_at: datetime
    amount: Decimal
    state: SyntheticState
    child: SyntheticChild
    values: tuple[Decimal, ...]
    metadata: Mapping[str, object]
    enabled: bool
    count: int
    note: str | None
    optional_label: str = "default-label"
    contract_id: str = field(default="C-777", init=False)
    schema_version: str = field(default="1", init=False)


@dataclass(frozen=True, slots=True)
class SensitiveContract:
    api_key: str
    contract_id: str = field(default="C-778", init=False)
    schema_version: str = field(default="1", init=False)


def synthetic(**overrides: object) -> SyntheticContract:
    values: dict[str, object] = {
        "entity_id": IDENTITY,
        "created_at": NOW,
        "amount": Decimal("1200.5000"),
        "state": SyntheticState.READY,
        "child": SyntheticChild("nested", Decimal("0.2500")),
        "values": (Decimal("1.00"), Decimal("-0.000")),
        "metadata": {"source": "synthetic", "attempt": 2},
        "enabled": True,
        "count": 3,
        "note": None,
        "optional_label": "default-label",
    }
    values.update(overrides)
    return SyntheticContract(**values)  # type: ignore[arg-type]


def payload_fields() -> tuple[str, ...]:
    return tuple(
        item.name
        for item in fields(SyntheticContract)
        if item.name not in {"contract_id", "schema_version"}
    )


def encoded_document(document: Mapping[str, object]) -> str:
    return json.dumps(
        document,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def parsed_document(serialized: str, **overrides: object) -> ParsedContractDocument:
    values: dict[str, object] = {
        "expected_contract_id": "C-777",
        "supported_canonicalization_versions": (CANONICAL_JSON_VERSION,),
        "supported_schema_versions": ("1",),
        "supported_payload_versions": ("wire-1",),
        "required_payload_fields": tuple(
            name for name in payload_fields() if name != "optional_label"
        ),
        "optional_payload_fields": ("optional_label",),
    }
    values.update(overrides)
    return parse_contract_document(serialized, **values)  # type: ignore[arg-type]


def transition(
    previous_schema: str = "1",
    previous_payload: str = "wire-1",
    current_schema: str = "1",
    current_payload: str = "wire-2",
) -> SupportedVersionTransition:
    return SupportedVersionTransition(
        previous_schema_version=previous_schema,
        previous_payload_version=previous_payload,
        current_schema_version=current_schema,
        current_payload_version=current_payload,
        evidence_reference="compatibility/approved-transition-1",
    )


def descriptor(
    *,
    contract_id: str = "C-777",
    schema_version: str = "1",
    payload_version: str = "wire-1",
    schema_fields: tuple[SchemaFieldDescriptor, ...] | None = None,
) -> ContractSchemaDescriptor:
    return ContractSchemaDescriptor(
        contract_id=contract_id,
        schema_version=schema_version,
        payload_version=payload_version,
        fields=schema_fields
        or (
            SchemaFieldDescriptor("entity_id", "uuid.UUID", True),
            SchemaFieldDescriptor("amount", "decimal.Decimal", True),
        ),
    )


def governed_evidence(
    report_digest: str, **overrides: object
) -> BreakingChangeEvidence:
    values: dict[str, object] = {
        "evidence_id": uuid4(),
        "report_sha256": report_digest,
        "impact_analysis_ref": "governance/impact-1",
        "migration_plan_ref": "governance/migration-1",
        "deprecation_plan_ref": "governance/deprecation-1",
        "rollback_plan_ref": "governance/rollback-1",
        "approval_ref": "governance/human-approval-1",
        "previous_supported_versions": ("1", "wire-1"),
        "approved_at": NOW,
        "effective_at": NOW + timedelta(days=30),
    }
    values.update(overrides)
    return BreakingChangeEvidence(**values)  # type: ignore[arg-type]


def no_trade_decision() -> NoTradeDecision:
    return NoTradeDecision(
        decision_id=IDENTITY,
        market_context_id=uuid4(),
        candidate_id=None,
        strategy_version_id=None,
        reasons=(NoTradeReason.NO_SETUP,),
        explanation="Synthetic no-trade decision",
        blocking_evidence_ids=(),
        conflict_ids=(),
        uncertainty_ids=(),
        data_quality_report_id=None,
        provenance=(VersionReference("strategy", uuid4(), "1.0.0", SHA_A),),
        correlation_id="correlation-1",
        lifecycle=SignalLifecycleState.NO_TRADE,
        decided_at=NOW,
        expires_at=NOW + timedelta(minutes=5),
    )


def test_serialization_is_deterministic_and_version_dimensions_are_distinct() -> None:
    item = synthetic()
    first = serialize_contract(item, payload_version="wire-1")
    second = serialize_contract(item, payload_version="wire-1")
    assert first == second
    assert contract_sha256(item, payload_version="wire-1") == contract_sha256(
        item, payload_version="wire-1"
    )
    decoded = json.loads(first)
    assert set(decoded) == {
        "canonicalization_version",
        "contract_id",
        "schema_version",
        "payload_version",
        "payload",
    }
    assert decoded["canonicalization_version"] == "canonical-json-v1"
    assert decoded["contract_id"] == "C-777"
    assert decoded["schema_version"] == "1"
    assert decoded["payload_version"] == "wire-1"
    assert "contract_id" not in decoded["payload"]
    assert "schema_version" not in decoded["payload"]


def test_nested_canonical_types_have_exact_encodings() -> None:
    decoded = contract_document(synthetic(), payload_version="wire-1")["payload"]
    assert isinstance(decoded, dict)
    assert decoded["entity_id"] == "12345678-1234-5678-90ab-1234567890ab"
    assert decoded["created_at"] == "2026-09-26T15:00:00.000000Z"
    assert decoded["amount"] == "1200.5"
    assert decoded["state"] == "READY"
    assert decoded["child"] == {"name": "nested", "amount": "0.25"}
    assert decoded["values"] == ["1", "0"]
    assert decoded["metadata"] == {"source": "synthetic", "attempt": 2}
    assert decoded["enabled"] is True
    assert decoded["count"] == 3
    assert decoded["note"] is None


def test_timezone_and_equivalent_decimal_values_are_normalized() -> None:
    offset = timezone(timedelta(hours=5, minutes=30))
    shifted = synthetic(
        created_at=datetime(2026, 9, 26, 20, 30, tzinfo=offset),
        amount=Decimal("1200.500000"),
    )
    assert serialize_contract(shifted, payload_version="wire-1") == serialize_contract(
        synthetic(), payload_version="wire-1"
    )


def test_key_order_is_recursive_and_source_mapping_is_not_mutated() -> None:
    source = {"z": {"b": 2, "a": 1}, "a": "first"}
    before = {"z": dict(source["z"]), "a": "first"}
    assert canonical_json_dumps(source) == '{"a":"first","z":{"a":1,"b":2}}'
    assert source == before


@pytest.mark.parametrize(
    "value",
    [
        1.0,
        Decimal("NaN"),
        Decimal("Infinity"),
        b"binary",
        bytearray(b"binary"),
        {"unordered"},
        frozenset({"unordered"}),
        ["mutable"],
        object(),
    ],
)
def test_ambiguous_or_unsupported_values_are_rejected(value: object) -> None:
    with pytest.raises(ContractSerializationError):
        canonical_json_dumps(value)


def test_naive_datetime_non_string_mapping_key_and_cycles_are_rejected() -> None:
    with pytest.raises(ContractSerializationError, match="timezone-aware"):
        canonical_json_dumps(datetime(2026, 9, 26, 15, 0))
    with pytest.raises(ContractSerializationError, match="keys must be strings"):
        canonical_json_dumps({1: "invalid"})
    cyclic: dict[str, object] = {}
    cyclic["self"] = cyclic
    with pytest.raises(ContractSerializationError, match="cyclic"):
        canonical_json_dumps(cyclic)

    deeply_nested: object = "leaf"
    for _ in range(MAX_NESTING_DEPTH + 2):
        deeply_nested = (deeply_nested,)
    with pytest.raises(ContractSerializationError, match="nesting depth"):
        canonical_json_dumps(deeply_nested)


@pytest.mark.parametrize(
    "field_name",
    [
        "password",
        "secret",
        "api-key",
        "private_key",
        "access_token",
        "refresh-token",
        "credential",
    ],
)
def test_sensitive_mapping_field_names_are_rejected(field_name: str) -> None:
    with pytest.raises(ContractSerializationError, match="sensitive"):
        canonical_json_dumps({field_name: "synthetic-canary"})


def test_sensitive_dataclass_field_is_rejected() -> None:
    with pytest.raises(ContractSerializationError, match="sensitive"):
        serialize_contract(
            SensitiveContract("synthetic-canary"), payload_version="wire-1"
        )


def test_existing_canonical_dataclass_serializes_without_modification() -> None:
    decision = no_trade_decision()
    serialized = serialize_contract(decision, payload_version="no-trade-wire-1")
    assert json.loads(serialized)["contract_id"] == "C-026"
    assert decision.decision_id == IDENTITY
    assert decision.lifecycle is SignalLifecycleState.NO_TRADE
    descriptor = describe_dataclass_contract(
        NoTradeDecision, payload_version="no-trade-wire-1"
    )
    assert descriptor.contract_id == "C-026"


def test_reference_value_object_cannot_masquerade_as_its_target_contract() -> None:
    reference = ContractReference("C-045", IDENTITY, "1", SHA_A, NOW)
    with pytest.raises(ContractSerializationError, match="fixed init=False"):
        serialize_contract(reference, payload_version="wire-1")


def test_parsing_returns_immutable_plain_data_without_object_construction() -> None:
    result = parsed_document(serialize_contract(synthetic(), payload_version="wire-1"))
    assert isinstance(result.payload, MappingProxyType)
    assert result.payload["child"] == {"amount": "0.25", "name": "nested"}
    assert isinstance(result.payload["values"], tuple)
    with pytest.raises(TypeError):
        result.payload["amount"] = "2"  # type: ignore[index]


@pytest.mark.parametrize(
    ("key", "value", "message"),
    [
        ("canonicalization_version", "unknown-json", "canonicalization_version"),
        ("contract_id", "C-778", "contract_id"),
        ("schema_version", "2", "schema_version"),
        ("payload_version", "wire-2", "payload_version"),
    ],
)
def test_parsing_rejects_unexpected_identity_or_versions(
    key: str, value: str, message: str
) -> None:
    document = contract_document(synthetic(), payload_version="wire-1")
    document[key] = value
    with pytest.raises(ContractSerializationError, match=message):
        parsed_document(encoded_document(document))


def test_parsing_rejects_unknown_envelope_and_missing_or_unknown_payload_fields() -> (
    None
):
    document = contract_document(synthetic(), payload_version="wire-1")
    document["unexpected"] = True
    with pytest.raises(ContractSerializationError, match="document fields"):
        parsed_document(encoded_document(document))

    document = contract_document(synthetic(), payload_version="wire-1")
    payload = document["payload"]
    assert isinstance(payload, dict)
    payload.pop("entity_id")
    with pytest.raises(ContractSerializationError, match="missing required"):
        parsed_document(encoded_document(document))

    document = contract_document(synthetic(), payload_version="wire-1")
    payload = document["payload"]
    assert isinstance(payload, dict)
    payload["future_optional"] = "value"
    serialized = encoded_document(document)
    with pytest.raises(ContractSerializationError, match="unknown fields"):
        parsed_document(serialized)
    result = parsed_document(
        serialized, unknown_field_policy=UnknownFieldPolicy.ALLOW_ADDITIVE
    )
    assert result.payload["future_optional"] == "value"


@pytest.mark.parametrize(
    "serialized",
    [
        "not-json",
        "[]",
        "null",
        '{"canonicalization_version":"canonical-json-v1","contract_id":"C-777",'
        '"schema_version":"1","payload_version":"wire-1","payload":1.5}',
        '{"canonicalization_version":"canonical-json-v1",'
        '"canonicalization_version":"canonical-json-v1",'
        '"contract_id":"C-777","schema_version":"1",'
        '"payload_version":"wire-1","payload":{}}',
    ],
)
def test_parsing_rejects_malformed_scalar_float_and_duplicate_json(
    serialized: str,
) -> None:
    with pytest.raises(ContractSerializationError):
        parsed_document(serialized)


def test_parsing_rejects_valid_but_noncanonical_json_text() -> None:
    canonical = serialize_contract(synthetic(), payload_version="wire-1")
    noncanonical = json.dumps(json.loads(canonical), indent=2, sort_keys=False)
    with pytest.raises(ContractSerializationError, match="exact canonical JSON"):
        parsed_document(noncanonical)


def test_parsing_rejects_invalid_utf8_and_sensitive_payload_fields() -> None:
    with pytest.raises(ContractSerializationError, match="UTF-8"):
        parsed_document(b"\xff")
    document = contract_document(synthetic(), payload_version="wire-1")
    payload = document["payload"]
    assert isinstance(payload, dict)
    payload["client_secret"] = "synthetic-canary"  # pragma: allowlist secret
    with pytest.raises(ContractSerializationError, match="sensitive"):
        parsed_document(
            encoded_document(document),
            unknown_field_policy=UnknownFieldPolicy.ALLOW_ADDITIVE,
        )


def test_parsing_enforces_document_size_and_nesting_limits() -> None:
    serialized = serialize_contract(synthetic(), payload_version="wire-1")
    with pytest.raises(ContractSerializationError, match="maximum size"):
        parsed_document(serialized, maximum_document_bytes=10)

    document = contract_document(synthetic(), payload_version="wire-1")
    payload = document["payload"]
    assert isinstance(payload, dict)
    nested: object = "leaf"
    for _ in range(5):
        nested = {"level": nested}
    payload["future_optional"] = nested
    with pytest.raises(ContractSerializationError, match="nesting depth"):
        parsed_document(
            encoded_document(document),
            unknown_field_policy=UnknownFieldPolicy.ALLOW_ADDITIVE,
            maximum_nesting_depth=3,
        )
    assert MAX_DOCUMENT_BYTES > len(serialized)


def test_schema_description_is_stable_and_detects_required_fields() -> None:
    first = describe_dataclass_contract(SyntheticContract, payload_version="wire-1")
    second = describe_dataclass_contract(SyntheticContract, payload_version="wire-1")
    assert first == second
    assert first.contract_id == "C-777"
    assert first.schema_version == "1"
    required = {item.name for item in first.fields if item.required}
    assert "entity_id" in required
    assert "optional_label" not in required
    assert "contract_id" not in {item.name for item in first.fields}
    state = next(item for item in first.fields if item.name == "state")
    assert state.enum_values == ("READY", "BLOCKED")


def test_identical_descriptors_have_no_changes() -> None:
    original = descriptor()
    report = assess_schema_compatibility(original, original)
    assert report.status is CompatibilityStatus.IDENTICAL
    assert report.changes == ()


def test_optional_addition_requires_explicit_supported_version_transition() -> None:
    previous = descriptor()
    current = descriptor(
        payload_version="wire-2",
        schema_fields=(
            *previous.fields,
            SchemaFieldDescriptor("note", "str | None", False),
        ),
    )
    unsupported = assess_schema_compatibility(previous, current)
    assert unsupported.status is CompatibilityStatus.BREAKING
    assert (
        unsupported.changes[-1].kind is SchemaChangeKind.VERSION_TRANSITION_UNSUPPORTED
    )

    supported = assess_schema_compatibility(
        previous, current, supported_transitions=(transition(),)
    )
    assert supported.status is CompatibilityStatus.BACKWARD_COMPATIBLE
    assert {item.kind for item in supported.changes} == {
        SchemaChangeKind.ADDED_OPTIONAL,
        SchemaChangeKind.VERSION_TRANSITION_SUPPORTED,
    }


def test_unversioned_shape_change_fails_closed() -> None:
    previous = descriptor()
    current = descriptor(
        schema_fields=(
            *previous.fields,
            SchemaFieldDescriptor("note", "str | None", False),
        )
    )
    report = assess_schema_compatibility(previous, current)
    assert report.status is CompatibilityStatus.BREAKING
    assert report.changes[-1].kind is SchemaChangeKind.VERSION_TRANSITION_UNSUPPORTED


@pytest.mark.parametrize(
    ("current", "kind"),
    [
        (
            descriptor(
                payload_version="wire-2",
                schema_fields=(
                    SchemaFieldDescriptor("entity_id", "uuid.UUID", True),
                    SchemaFieldDescriptor("amount", "decimal.Decimal", True),
                    SchemaFieldDescriptor("required_new", "str", True),
                ),
            ),
            SchemaChangeKind.ADDED_REQUIRED,
        ),
        (
            descriptor(
                payload_version="wire-2",
                schema_fields=(SchemaFieldDescriptor("entity_id", "uuid.UUID", True),),
            ),
            SchemaChangeKind.REMOVED,
        ),
        (
            descriptor(
                payload_version="wire-2",
                schema_fields=(
                    SchemaFieldDescriptor("entity_id", "str", True),
                    SchemaFieldDescriptor("amount", "decimal.Decimal", True),
                ),
            ),
            SchemaChangeKind.TYPE_CHANGED,
        ),
        (
            descriptor(
                payload_version="wire-2",
                schema_fields=(
                    SchemaFieldDescriptor("entity_id", "uuid.UUID", False),
                    SchemaFieldDescriptor("amount", "decimal.Decimal", True),
                ),
            ),
            SchemaChangeKind.OPTIONALITY_CHANGED,
        ),
        (
            descriptor(contract_id="C-778", payload_version="wire-2"),
            SchemaChangeKind.CONTRACT_ID_CHANGED,
        ),
    ],
)
def test_breaking_shape_changes_remain_breaking_with_supported_transition(
    current: ContractSchemaDescriptor, kind: SchemaChangeKind
) -> None:
    report = assess_schema_compatibility(
        descriptor(), current, supported_transitions=(transition(),)
    )
    assert report.status is CompatibilityStatus.BREAKING
    assert kind in {item.kind for item in report.changes}


def test_enum_vocabulary_change_is_breaking() -> None:
    old_field = SchemaFieldDescriptor(
        "state", "SyntheticState", True, ("READY", "BLOCKED")
    )
    new_field = SchemaFieldDescriptor("state", "SyntheticState", True, ("READY",))
    report = assess_schema_compatibility(
        descriptor(schema_fields=(old_field,)),
        descriptor(payload_version="wire-2", schema_fields=(new_field,)),
        supported_transitions=(transition(),),
    )
    assert report.status is CompatibilityStatus.BREAKING
    assert SchemaChangeKind.ENUM_VALUES_CHANGED in {
        item.kind for item in report.changes
    }


def test_breaking_change_requires_exact_governed_evidence() -> None:
    previous = descriptor()
    current = descriptor(
        payload_version="wire-2",
        schema_fields=(SchemaFieldDescriptor("entity_id", "uuid.UUID", True),),
    )
    report = assess_schema_compatibility(
        previous, current, supported_transitions=(transition(),)
    )
    with pytest.raises(SchemaVersioningError, match="governed evidence"):
        require_governed_compatibility(report)
    evidence = governed_evidence(compatibility_report_sha256(report))
    require_governed_compatibility(report, evidence)
    with pytest.raises(SchemaVersioningError, match="not bound"):
        require_governed_compatibility(report, replace(evidence, report_sha256=SHA_A))


def test_compatible_report_rejects_unnecessary_breaking_evidence() -> None:
    report = assess_schema_compatibility(descriptor(), descriptor())
    require_governed_compatibility(report)
    with pytest.raises(SchemaVersioningError, match="not valid"):
        require_governed_compatibility(report, governed_evidence(SHA_A))


@pytest.mark.parametrize(
    "overrides",
    [
        {"impact_analysis_ref": " "},
        {"migration_plan_ref": ""},
        {"deprecation_plan_ref": " "},
        {"rollback_plan_ref": ""},
        {"approval_ref": " "},
        {"previous_supported_versions": ()},
        {"previous_supported_versions": ("1", "1")},
        {"approved_at": datetime(2026, 9, 26, 15, 0)},
        {"effective_at": NOW - timedelta(seconds=1)},
    ],
)
def test_breaking_evidence_rejects_incomplete_or_invalid_data(
    overrides: dict[str, object],
) -> None:
    with pytest.raises(SchemaVersioningError):
        governed_evidence(SHA_A, **overrides)


def test_evidence_must_preserve_previous_schema_and_payload_versions() -> None:
    current = descriptor(
        payload_version="wire-2",
        schema_fields=(SchemaFieldDescriptor("entity_id", "uuid.UUID", True),),
    )
    report = assess_schema_compatibility(
        descriptor(), current, supported_transitions=(transition(),)
    )
    evidence = governed_evidence(
        compatibility_report_sha256(report), previous_supported_versions=("1",)
    )
    with pytest.raises(SchemaVersioningError, match="previous schema and payload"):
        require_governed_compatibility(report, evidence)


def test_version_transition_records_are_nontrivial_and_unique() -> None:
    with pytest.raises(SchemaVersioningError, match="must change"):
        transition(current_payload="wire-1")
    current = descriptor(payload_version="wire-2")
    duplicate = transition()
    with pytest.raises(SchemaVersioningError, match="duplicates"):
        assess_schema_compatibility(
            descriptor(),
            current,
            supported_transitions=(duplicate, duplicate),
        )


def test_public_value_objects_are_frozen_slotted_and_exports_are_exact() -> None:
    item = descriptor()
    assert "__dict__" not in dir(item)
    with pytest.raises(FrozenInstanceError):
        item.contract_id = "C-778"  # type: ignore[misc]
    expected = {
        "BreakingChangeEvidence",
        "CANONICAL_JSON_VERSION",
        "CanonicalScalar",
        "CanonicalValue",
        "CompatibilityReport",
        "CompatibilityStatus",
        "ContractSchemaDescriptor",
        "ContractSerializationError",
        "MAX_DOCUMENT_BYTES",
        "MAX_NESTING_DEPTH",
        "ParsedContractDocument",
        "SchemaChange",
        "SchemaChangeKind",
        "SchemaFieldDescriptor",
        "SchemaVersioningError",
        "SupportedVersionTransition",
        "UnknownFieldPolicy",
        "canonical_json_dumps",
        "canonical_sha256",
        "compatibility_report_sha256",
        "contract_document",
        "contract_sha256",
        "serialize_contract",
        "parse_contract_document",
        "describe_dataclass_contract",
        "assess_schema_compatibility",
        "require_governed_compatibility",
        "to_canonical_data",
    }
    assert set(contracts_package.__all__) == expected


def test_canonical_hash_is_lowercase_sha256_and_value_sensitive() -> None:
    first = canonical_sha256({"value": Decimal("1.0")})
    second = canonical_sha256({"value": Decimal("2.0")})
    assert len(first) == 64
    assert first == first.lower()
    assert first != second


def test_to_canonical_data_does_not_return_domain_objects() -> None:
    result = to_canonical_data(synthetic())
    assert isinstance(result, dict)
    assert all(not isinstance(value, SyntheticChild) for value in result.values())
