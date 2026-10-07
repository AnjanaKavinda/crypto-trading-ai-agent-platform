import asyncio
import json
from datetime import UTC, datetime
from decimal import Decimal, localcontext
from uuid import UUID

import pytest
from trading_platform_api.contracts.serialization import canonical_sha256
from trading_platform_api.lineage.codec import (
    LineageError,
    LineageKey,
    decode,
    encode,
    key_for,
)
from trading_platform_api.lineage.store import (
    SqlAlchemyLineageStore,
    append_validated_market_snapshot,
    references,
)
from trading_platform_api.market_data.contracts import (
    AssessmentPolicyReference,
    DataQualityDimension,
    DataQualityDimensionReasonCode,
    DataQualityDimensionResult,
    DataQualityDimensionState,
    DataQualityEvidenceReference,
    DataQualityReport,
    DataQualityReportV2,
    DataQualityStatus,
    MarketDataContractError,
)

NOW = datetime(2026, 1, 1, tzinfo=UTC)
REPORT_ID = UUID("00000000-0000-0000-0000-000000000003")
SNAPSHOT_ID = UUID("00000000-0000-0000-0000-000000000002")
POLICY = AssessmentPolicyReference("point-snapshot", "1")


def measured(dimension: DataQualityDimension) -> DataQualityDimensionResult:
    return DataQualityDimensionResult(
        dimension,
        DataQualityDimensionState.MEASURED,
        Decimal("1"),
        numerator=1,
        denominator=1,
        basis_unit="observations",
    )


def report(
    dimensions: tuple[DataQualityDimensionResult, ...] | None = None,
    *,
    status: DataQualityStatus = DataQualityStatus.VALID,
    **changes: object,
) -> DataQualityReportV2:
    values: dict[str, object] = dict(
        report_id=REPORT_ID,
        snapshot_id=SNAPSHOT_ID,
        assessed_at=NOW,
        required_data_cutoff=NOW,
        assessment_policy_id=POLICY.policy_id,
        assessment_policy_version=POLICY.version,
        dimensions=(
            tuple(map(measured, DataQualityDimension))
            if dimensions is None
            else dimensions
        ),
        status=status,
    )
    values.update(changes)
    return DataQualityReportV2(**values)  # type: ignore[arg-type]


def v1_report() -> DataQualityReport:
    return DataQualityReport(
        REPORT_ID,
        SNAPSHOT_ID,
        NOW,
        NOW,
        *(Decimal("1") for _ in range(7)),
        DataQualityStatus.VALID,
    )


def test_v2_requires_the_exact_ordered_dimension_set() -> None:
    dimensions = tuple(map(measured, DataQualityDimension))
    assert report(dimensions).dimensions == dimensions
    with pytest.raises(MarketDataContractError, match="exactly once"):
        report(dimensions[:-1])
    with pytest.raises(MarketDataContractError, match="exactly once"):
        report((dimensions[0], *dimensions[:-1]))
    with pytest.raises(MarketDataContractError, match="canonical order"):
        report((dimensions[1], dimensions[0], *dimensions[2:]))


@pytest.mark.parametrize(
    "changes",
    [
        {"score": Decimal("1.1")},
        {"score": Decimal("NaN")},
        {"score": Decimal("0.5"), "denominator": 0},
        {"score": Decimal("0.5"), "numerator": 2, "denominator": 1},
        {"score": Decimal("0.5"), "numerator": 1},
        {"score": Decimal("0.6"), "numerator": 1, "denominator": 2},
        {"score": Decimal("0"), "numerator": 0, "denominator": 1},
    ],
)
def test_measured_dimension_rejects_invalid_or_unaudited_basis(
    changes: dict[str, object],
) -> None:
    values: dict[str, object] = {
        "dimension": DataQualityDimension.COVERAGE,
        "state": DataQualityDimensionState.MEASURED,
        "score": Decimal("1"),
        "numerator": 1,
        "denominator": 1,
        "basis_unit": "observations",
    }
    values.update(changes)
    with pytest.raises(MarketDataContractError):
        DataQualityDimensionResult(**values)  # type: ignore[arg-type]


def test_measured_zero_requires_a_positive_denominator_and_immutable_evidence() -> None:
    evidence = DataQualityEvidenceReference(
        "C-091", "source-record", "1", "a" * 64
    )
    zero = DataQualityDimensionResult(
        DataQualityDimension.CONTINUITY,
        DataQualityDimensionState.MEASURED,
        Decimal("0"),
        numerator=0,
        denominator=1,
        basis_unit="observations",
        evidence_reference=evidence,
    )
    assert zero.score == 0
    with pytest.raises(MarketDataContractError, match="measured zero"):
        DataQualityDimensionResult(
            DataQualityDimension.CONTINUITY,
            DataQualityDimensionState.MEASURED,
            Decimal("0"),
            evidence_reference=evidence,
        )


def test_measurement_ratio_validation_ignores_ambient_decimal_precision() -> None:
    with localcontext() as context:
        context.prec = 5
        value = DataQualityDimensionResult(
            DataQualityDimension.COVERAGE,
            DataQualityDimensionState.MEASURED,
            Decimal("0.3333333333333333333333333333"),
            numerator=1,
            denominator=3,
            basis_unit="observations",
        )
    assert value.score == Decimal("0.3333333333333333333333333333")


def test_v2_evidence_reference_is_a_hashed_lineage_dependency() -> None:
    evidence = DataQualityEvidenceReference(
        "C-091", "source-record", "1", "a" * 64
    )
    dimensions = tuple(
        DataQualityDimensionResult(
            dimension,
            DataQualityDimensionState.MEASURED,
            Decimal("0"),
            numerator=0,
            denominator=1,
            basis_unit="observations",
            evidence_reference=evidence,
        )
        if dimension is DataQualityDimension.CONTINUITY
        else measured(dimension)
        for dimension in DataQualityDimension
    )
    linked = references(report(dimensions))
    assert tuple(reference.key for reference in linked) == (
        LineageKey("C-002", str(SNAPSHOT_ID)),
        LineageKey("C-091", "source-record", "1"),
    )
    assert linked[1].evidence_sha256 == "a" * 64


def test_not_applicable_requires_matching_policy_and_has_no_measurement() -> None:
    n_a = DataQualityDimensionResult(
        DataQualityDimension.CONTINUITY,
        DataQualityDimensionState.NOT_APPLICABLE,
        reason_code=DataQualityDimensionReasonCode.SINGLE_POINT_SNAPSHOT,
        not_applicable_policy=POLICY,
    )
    dimensions = tuple(
        n_a if dimension is DataQualityDimension.CONTINUITY else measured(dimension)
        for dimension in DataQualityDimension
    )
    assert report(dimensions).dimensions[-1].state is DataQualityDimensionState.NOT_APPLICABLE
    with pytest.raises(MarketDataContractError, match="policy reference"):
        report(dimensions, assessment_policy_version="2")
    with pytest.raises(MarketDataContractError, match="measurement bases"):
        DataQualityDimensionResult(
            DataQualityDimension.CONTINUITY,
            DataQualityDimensionState.NOT_APPLICABLE,
            Decimal("0"),
            reason_code=DataQualityDimensionReasonCode.SINGLE_POINT_SNAPSHOT,
            not_applicable_policy=POLICY,
        )


def test_unavailable_requires_a_closed_reason_set_and_valid_cannot_be_unavailable() -> None:
    unavailable = DataQualityDimensionResult(
        DataQualityDimension.CONTINUITY,
        DataQualityDimensionState.UNAVAILABLE,
        reason_code=DataQualityDimensionReasonCode.SEQUENCE_UNVERIFIED,
    )
    dimensions = tuple(
        unavailable
        if dimension is DataQualityDimension.CONTINUITY
        else measured(dimension)
        for dimension in DataQualityDimension
    )
    with pytest.raises(MarketDataContractError, match="VALID status"):
        report(dimensions)
    assert (
        report(dimensions, status=DataQualityStatus.UNAVAILABLE).dimensions[-1]
        == unavailable
    )
    with pytest.raises(ValueError):
        DataQualityDimensionReasonCode("FUTURE_REASON")
    with pytest.raises(MarketDataContractError, match="recognized unavailable"):
        DataQualityDimensionResult(
            DataQualityDimension.CONTINUITY,
            DataQualityDimensionState.UNAVAILABLE,
        )


def test_policy_references_are_structurally_validated() -> None:
    for policy_id, version in (("", "1"), ("policy", ""), ("bad space", "1")):
        with pytest.raises(MarketDataContractError):
            AssessmentPolicyReference(policy_id, version)
    with pytest.raises(MarketDataContractError):
        report(assessment_policy_version="")


def test_c003_v1_canonical_bytes_digest_and_identity_are_unchanged() -> None:
    expected = (
        '{"canonicalization_version":"canonical-json-v1","contract_id":"C-003",'
        '"payload":{"accuracy":"1","anomalies":[],"assessed_at":'
        '"2026-01-01T00:00:00.000000Z","completeness":"1","consistency":"1",'
        '"continuity":"1","coverage":"1","duplicate_record_ids":[],"freshness":"1",'
        '"invalid_record_ids":[],"missing_fields":[],"report_id":'
        '"00000000-0000-0000-0000-000000000003","required_data_cutoff":'
        '"2026-01-01T00:00:00.000000Z","snapshot_id":'
        '"00000000-0000-0000-0000-000000000002","source_conflicts":[],'
        '"source_reliability":"1","status":"VALID"},"payload_version":"wire-1",'
        '"schema_version":"1"}'
    )
    legacy = v1_report()
    assert encode(legacy) == expected
    assert canonical_sha256(legacy) == (
        "6db37205"
        "049b7110"
        "ac4e306c"
        "4badc4c7"
        "58dfd715"
        "618be34d"
        "1da30261"
        "4cfb6a54"
    )
    assert key_for(legacy) == LineageKey("C-003", str(REPORT_ID), "1")
    assert type(decode(expected)) is DataQualityReport


def test_v2_codec_is_version_directed_and_has_a_distinct_lineage_identity() -> None:
    v2 = report()
    document = encode(v2)
    assert '"schema_version":"2"' in document
    assert type(decode(document)) is DataQualityReportV2
    assert decode(document) == v2
    assert key_for(v2) == LineageKey("C-003", str(REPORT_ID), "2")
    assert key_for(v1_report()) != key_for(v2)
    envelope = json.loads(document)
    envelope["schema_version"] = "3"
    with pytest.raises(LineageError):
        decode(json.dumps(envelope, separators=(",", ":"), sort_keys=True))
    for schema_version in ("1", "future"):
        envelope = json.loads(document)
        envelope["schema_version"] = schema_version
        with pytest.raises(LineageError):
            decode(json.dumps(envelope, separators=(",", ":"), sort_keys=True))
    with pytest.raises(LineageError):
        decode(document + " ")


def test_codec_rejects_unknown_v2_state_and_reason_codes() -> None:
    dimensions = tuple(
        DataQualityDimensionResult(
            dimension,
            DataQualityDimensionState.NOT_APPLICABLE,
            reason_code=DataQualityDimensionReasonCode.SINGLE_POINT_SNAPSHOT,
            not_applicable_policy=POLICY,
        )
        if dimension is DataQualityDimension.CONTINUITY
        else measured(dimension)
        for dimension in DataQualityDimension
    )
    document = encode(report(dimensions))
    for field_name, value in (("state", "FUTURE_STATE"), ("reason_code", "FUTURE")):
        envelope = json.loads(document)
        envelope["payload"]["dimensions"][-1][field_name] = value
        with pytest.raises(LineageError):
            decode(json.dumps(envelope, separators=(",", ":"), sort_keys=True))


def test_existing_validated_snapshot_writer_does_not_accept_v2() -> None:
    from test_lineage_quality import MemoryLineageStore, records_for_report

    sources, observations, snapshot, _ = records_for_report()
    store = MemoryLineageStore()
    with pytest.raises(LineageError, match="Invalid bounded"):
        asyncio.run(
            append_validated_market_snapshot(
                store,
                sources=sources,
                observations=observations,
                snapshot=snapshot,
                quality=report(),
            )
        )
    assert store.appended == []


def test_generic_lineage_store_keeps_v2_writes_disabled() -> None:
    store = object.__new__(SqlAlchemyLineageStore)
    with pytest.raises(LineageError, match="writes are disabled"):
        asyncio.run(store.append(report()))
