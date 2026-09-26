from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from uuid import UUID

import pytest
from contract_harness import (
    ContractHarnessCase,
    assert_canonical_round_trip,
    assert_compatibility,
    assert_stable_schema_descriptor,
    assert_unique_contract_ids,
    parse_case_document,
)
from trading_platform_api.analysis import AnalysisSnapshot
from trading_platform_api.contracts import (
    BreakingChangeEvidence,
    CompatibilityStatus,
    ContractSerializationError,
    SchemaFieldDescriptor,
    SchemaVersioningError,
    SupportedVersionTransition,
    compatibility_report_sha256,
    require_governed_compatibility,
)
from trading_platform_api.execution import ApprovalRequest
from trading_platform_api.learning import Experience
from trading_platform_api.market_data import (
    DataQualityReport,
    DataQualityStatus,
    MarketData,
)
from trading_platform_api.risk import RiskProposal
from trading_platform_api.safety import SafetyDecision
from trading_platform_api.strategy import Signal
from trading_platform_api.validation import ValidationResult

NOW = datetime(2026, 9, 26, 16, 30, tzinfo=UTC)
IDENTITY = UUID("12345678-1234-5678-90ab-1234567890ab")


class SyntheticState(StrEnum):
    READY = "READY"
    BLOCKED = "BLOCKED"


@dataclass(frozen=True, slots=True)
class SyntheticContract:
    amount: Decimal
    observed_at: datetime
    state: SyntheticState
    note: str | None = None
    contract_id: str = field(default="C-777", init=False)
    schema_version: str = field(default="1", init=False)


@dataclass(frozen=True, slots=True)
class DuplicateSyntheticContract:
    value: str
    contract_id: str = field(default="C-777", init=False)
    schema_version: str = field(default="1", init=False)


def quality_report() -> DataQualityReport:
    return DataQualityReport(
        report_id=IDENTITY,
        snapshot_id=UUID("22345678-1234-5678-90ab-1234567890ab"),
        assessed_at=NOW,
        required_data_cutoff=NOW,
        completeness=Decimal("1.000"),
        freshness=Decimal("0.9500"),
        accuracy=Decimal("0.900"),
        consistency=Decimal("0.850"),
        source_reliability=Decimal("0.800"),
        coverage=Decimal("0.750"),
        continuity=Decimal("0.700"),
        status=DataQualityStatus.VALID,
    )


def synthetic_case() -> ContractHarnessCase:
    return ContractHarnessCase.from_contract(
        SyntheticContract(
            amount=Decimal("1200.5000"),
            observed_at=NOW,
            state=SyntheticState.READY,
        ),
        payload_version="wire-1",
    )


def canonical_document(case: ContractHarnessCase) -> dict[str, object]:
    return json.loads(
        json.dumps(
            {
                "canonicalization_version": "canonical-json-v1",
                "contract_id": case.descriptor.contract_id,
                "schema_version": case.descriptor.schema_version,
                "payload_version": case.descriptor.payload_version,
                "payload": {
                    "amount": "1200.5",
                    "note": None,
                    "observed_at": "2026-09-26T16:30:00.000000Z",
                    "state": "READY",
                },
            },
            separators=(",", ":"),
            sort_keys=True,
        )
    )


def encode(document: dict[str, object]) -> str:
    return json.dumps(document, separators=(",", ":"), sort_keys=True)


def test_actual_contract_round_trip_preserves_enum_decimal_and_timestamp() -> None:
    case = ContractHarnessCase.from_contract(
        quality_report(), payload_version="quality-wire-1"
    )

    parsed = assert_canonical_round_trip(case)

    assert parsed.payload["status"] == "VALID"
    assert parsed.payload["completeness"] == "1"
    assert parsed.payload["freshness"] == "0.95"
    assert parsed.payload["assessed_at"] == "2026-09-26T16:30:00.000000Z"


def test_schema_descriptor_is_stable_and_preserves_enum_vocabulary() -> None:
    descriptor = assert_stable_schema_descriptor(
        SyntheticContract, payload_version="wire-1"
    )

    fields = {item.name: item for item in descriptor.fields}
    assert fields["amount"].type_name == "decimal.Decimal"
    assert fields["observed_at"].type_name == "datetime.datetime"
    assert fields["state"].enum_values == ("READY", "BLOCKED")
    assert fields["note"].required is False


def test_harness_covers_every_implemented_contract_family() -> None:
    descriptors = assert_unique_contract_ids(
        (
            MarketData,
            AnalysisSnapshot,
            Signal,
            ValidationResult,
            RiskProposal,
            ApprovalRequest,
            SafetyDecision,
            Experience,
        ),
        payload_version="wire-1",
    )

    assert tuple(item.contract_id for item in descriptors) == (
        "C-001",
        "C-007",
        "C-070",
        "C-028",
        "C-034",
        "C-037",
        "C-058",
        "C-045",
    )


def test_harness_rejects_unknown_versions() -> None:
    case = synthetic_case()
    document = canonical_document(case)

    for name, value in (
        ("canonicalization_version", "canonical-json-v2"),
        ("schema_version", "2"),
        ("payload_version", "wire-2"),
    ):
        changed = dict(document)
        changed[name] = value
        with pytest.raises(ContractSerializationError, match="unsupported"):
            parse_case_document(case, encode(changed))


def test_harness_rejects_noncanonical_wire_text() -> None:
    case = synthetic_case()
    with pytest.raises(ContractSerializationError, match="exact canonical"):
        parse_case_document(case, encode(canonical_document(case)) + "\n")


def test_harness_rejects_missing_required_and_unknown_payload_fields() -> None:
    case = synthetic_case()
    document = canonical_document(case)
    payload = dict(document["payload"])  # type: ignore[arg-type]
    payload.pop("amount")
    document["payload"] = payload
    with pytest.raises(ContractSerializationError, match="missing.*amount"):
        parse_case_document(case, encode(document))

    document = canonical_document(case)
    payload = dict(document["payload"])  # type: ignore[arg-type]
    payload["unexpected"] = "value"
    document["payload"] = payload
    with pytest.raises(ContractSerializationError, match="unknown.*unexpected"):
        parse_case_document(case, encode(document))


def test_harness_detects_duplicate_canonical_contract_owners() -> None:
    descriptors = assert_unique_contract_ids(
        (SyntheticContract, DataQualityReport), payload_version="wire-1"
    )
    assert tuple(item.contract_id for item in descriptors) == ("C-777", "C-003")

    with pytest.raises(AssertionError, match="duplicate canonical contract id C-777"):
        assert_unique_contract_ids(
            (SyntheticContract, DuplicateSyntheticContract),
            payload_version="wire-1",
        )


def test_compatibility_harness_accepts_only_proven_optional_addition() -> None:
    previous = assert_stable_schema_descriptor(
        SyntheticContract, payload_version="wire-1"
    )
    current = type(previous)(
        contract_id=previous.contract_id,
        schema_version="2",
        payload_version="wire-2",
        fields=previous.fields + (SchemaFieldDescriptor("label", "str | None", False),),
    )
    transition = SupportedVersionTransition(
        previous_schema_version="1",
        previous_payload_version="wire-1",
        current_schema_version="2",
        current_payload_version="wire-2",
        evidence_reference="compatibility/approved-transition-1",
    )

    report = assert_compatibility(
        previous,
        current,
        CompatibilityStatus.BACKWARD_COMPATIBLE,
        supported_transitions=(transition,),
    )

    require_governed_compatibility(report)


@pytest.mark.parametrize(
    "replacement",
    [
        (),
        (SchemaFieldDescriptor("amount", "str", True),),
        (SchemaFieldDescriptor("required_addition", "str", True),),
    ],
)
def test_compatibility_harness_classifies_unproven_changes_as_breaking(
    replacement: tuple[SchemaFieldDescriptor, ...],
) -> None:
    previous = assert_stable_schema_descriptor(
        SyntheticContract, payload_version="wire-1"
    )
    current = type(previous)(
        contract_id=previous.contract_id,
        schema_version="2",
        payload_version="wire-2",
        fields=replacement or previous.fields[1:],
    )

    report = assert_compatibility(previous, current, CompatibilityStatus.BREAKING)
    with pytest.raises(SchemaVersioningError, match="governed evidence"):
        require_governed_compatibility(report)


def test_breaking_evidence_must_bind_exact_report_and_previous_versions() -> None:
    previous = assert_stable_schema_descriptor(
        SyntheticContract, payload_version="wire-1"
    )
    current = type(previous)(
        contract_id=previous.contract_id,
        schema_version="2",
        payload_version="wire-2",
        fields=previous.fields[1:],
    )
    report = assert_compatibility(previous, current, CompatibilityStatus.BREAKING)
    evidence = BreakingChangeEvidence(
        evidence_id=IDENTITY,
        report_sha256=compatibility_report_sha256(report),
        impact_analysis_ref="governance/impact-1",
        migration_plan_ref="governance/migration-1",
        deprecation_plan_ref="governance/deprecation-1",
        rollback_plan_ref="governance/rollback-1",
        approval_ref="governance/human-approval-1",
        previous_supported_versions=("1", "wire-1"),
        approved_at=NOW,
        effective_at=NOW,
    )

    require_governed_compatibility(report, evidence)

    mismatched = BreakingChangeEvidence(
        evidence_id=IDENTITY,
        report_sha256="a" * 64,
        impact_analysis_ref="governance/impact-1",
        migration_plan_ref="governance/migration-1",
        deprecation_plan_ref="governance/deprecation-1",
        rollback_plan_ref="governance/rollback-1",
        approval_ref="governance/human-approval-1",
        previous_supported_versions=("1", "wire-1"),
        approved_at=NOW,
        effective_at=NOW,
    )
    with pytest.raises(SchemaVersioningError, match="not bound"):
        require_governed_compatibility(report, mismatched)
