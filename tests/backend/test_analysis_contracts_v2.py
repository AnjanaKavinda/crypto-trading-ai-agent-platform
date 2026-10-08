from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from hashlib import sha256
from uuid import UUID

import pytest
from trading_platform_api.analysis import (
    AdversarialAssessment,
    AgentIndependenceReference,
    AnalysisRecordReference,
    AnalysisSnapshotReference,
    AnalysisV2ContractError,
    AnalyticalDirection,
    AnalyticalFinding,
    AnalyticalUncertainty,
    AssessmentStatus,
    ClaimClassification,
    ConfluenceAssessment,
    ConfluenceComponent,
    ConfluenceState,
    DomainObservation,
    EvidenceDependence,
    EvidenceItemV2,
    EvidenceRelation,
    FundamentalAssessment,
    InputBindingV2,
    InputModality,
    MarketContextV2,
    MarketRegime,
    MethodologyCategory,
    ObservationSourceBinding,
    OrderFlowAssessment,
    OrderFlowAssessmentState,
    OrderFlowMetric,
    OrderFlowMetricName,
    OrderFlowMetricState,
    RegimeDimension,
    ResolutionStatus,
    UncertaintyCategory,
    VersionReference,
    analysis_snapshot_v2_sha256,
    create_analysis_snapshot_v2,
    decode_analysis_contract,
    encode_analysis_contract,
    resolve_analysis_snapshot_v2,
    validate_market_context_v2,
    validate_order_flow_assessment,
)
from trading_platform_api.contracts.serialization import canonical_sha256
from trading_platform_api.market_data import (
    AssessmentPolicyReference as QualityPolicyReference,
)
from trading_platform_api.market_data import (
    DataQualityDimension,
    DataQualityDimensionReasonCode,
    DataQualityDimensionResult,
    DataQualityDimensionState,
    DataQualityReportV2,
    DataQualityStatus,
    DatasetVersion,
    DatasetVersionReference,
    DataSourceRecord,
    MarketData,
    MarketSnapshot,
    MetricValue,
    ProviderDataKind,
    SpotQualityMetricRule,
    SpotQualityPolicy,
)

T0 = datetime(2026, 1, 1, tzinfo=UTC)
CUTOFF = T0 + timedelta(seconds=10)
CREATED = CUTOFF + timedelta(seconds=1)
EXPIRES = CUTOFF + timedelta(seconds=5)
INSTRUMENT = "BTC-USDT-SPOT"
VENUE = "BINANCE-SPOT"
HASH = "a" * 64


def _id(number: int) -> UUID:
    return UUID(f"00000000-0000-0000-0000-{number:012d}")


def _policy(modality: InputModality, cutoff: datetime = CUTOFF) -> SpotQualityPolicy:
    if modality is InputModality.ORDER_BOOK:
        policy_id = "spot-order-book-point"
        kind = ProviderDataKind.ORDER_BOOK
        expected = 1
        transitions = None
        rules = (
            SpotQualityMetricRule(
                "bid_1_price", "USDT", Decimal("1e-18"), Decimal("1e18")
            ),
            SpotQualityMetricRule(
                "bid_1_quantity", "BTC", Decimal("0"), Decimal("1e18")
            ),
            SpotQualityMetricRule(
                "ask_1_price", "USDT", Decimal("1e-18"), Decimal("1e18")
            ),
            SpotQualityMetricRule(
                "ask_1_quantity", "BTC", Decimal("0"), Decimal("1e18")
            ),
        )
    elif modality is InputModality.SPOT_TRADES:
        policy_id = "spot-trade-quality"
        kind = ProviderDataKind.TRADE
        expected = 2
        transitions = 1
        rules = (
            SpotQualityMetricRule("price", "USDT", Decimal("1e-18"), Decimal("1e18")),
            SpotQualityMetricRule("quantity", "BTC", Decimal("1e-18"), Decimal("1e18")),
        )
    else:
        raise AssertionError("Test helper supports trade and point-book inputs.")
    return SpotQualityPolicy(
        policy_id,
        "1",
        kind,
        INSTRUMENT,
        VENUE,
        cutoff,
        expected,
        10,
        rules,
        expected_transition_count=transitions,
    )


def _source(source_id: UUID, event_time: datetime) -> DataSourceRecord:
    return DataSourceRecord(
        source_id,
        "provider",
        "provider-v1",
        event_time,
        event_time,
        event_time,
        "raw-v1",
        "adapter-v1",
        "licensed-source",
        HASH,
    )


def _observation(
    observation_id: UUID,
    source_id: UUID,
    modality: InputModality,
    event_time: datetime,
) -> MarketData:
    kind = {
        InputModality.SPOT_TRADES: ProviderDataKind.TRADE,
        InputModality.ORDER_BOOK: ProviderDataKind.ORDER_BOOK,
    }[modality]
    metrics = (
        (
            MetricValue("bid_1_price", Decimal("99"), "USDT"),
            MetricValue("bid_1_quantity", Decimal("2"), "BTC"),
            MetricValue("ask_1_price", Decimal("101"), "USDT"),
            MetricValue("ask_1_quantity", Decimal("3"), "BTC"),
        )
        if modality is InputModality.ORDER_BOOK
        else (
            MetricValue("price", Decimal("100"), "USDT"),
            MetricValue("quantity", Decimal("1"), "BTC"),
        )
    )
    return MarketData(
        observation_id,
        INSTRUMENT,
        VENUE,
        kind.value,
        event_time,
        event_time,
        event_time,
        event_time,
        source_id,
        metrics,
    )


def _report(
    snapshot: MarketSnapshot,
    policy: SpotQualityPolicy,
    *,
    status: DataQualityStatus = DataQualityStatus.VALID,
    failed_dimension: DataQualityDimension | None = None,
    anomalies: tuple[str, ...] = (),
) -> DataQualityReportV2:
    expected = policy.expected_record_count
    assert expected is not None
    denominators = {
        DataQualityDimension.COMPLETENESS: expected * len(policy.metric_rules),
        DataQualityDimension.FRESHNESS: expected,
        DataQualityDimension.ACCURACY: expected,
        DataQualityDimension.CONSISTENCY: expected,
        DataQualityDimension.SOURCE_RELIABILITY: expected,
        DataQualityDimension.COVERAGE: expected,
        DataQualityDimension.CONTINUITY: policy.expected_transition_count,
    }
    units = {
        DataQualityDimension.COMPLETENESS: "metric_cells",
        DataQualityDimension.FRESHNESS: "observations",
        DataQualityDimension.ACCURACY: "observations",
        DataQualityDimension.CONSISTENCY: "observations",
        DataQualityDimension.SOURCE_RELIABILITY: "source_records",
        DataQualityDimension.COVERAGE: "observations",
        DataQualityDimension.CONTINUITY: "sequence_transitions",
    }
    dimensions = []
    for dimension in DataQualityDimension:
        if (
            dimension is DataQualityDimension.CONTINUITY
            and policy.data_kind is ProviderDataKind.ORDER_BOOK
            and policy.expected_record_count == 1
        ):
            dimensions.append(
                DataQualityDimensionResult(
                    dimension,
                    DataQualityDimensionState.NOT_APPLICABLE,
                    reason_code=DataQualityDimensionReasonCode.SINGLE_POINT_SNAPSHOT,
                    not_applicable_policy=QualityPolicyReference(
                        policy.assessment_policy_id, policy.resolved_policy_version
                    ),
                )
            )
            continue
        denominator = denominators[dimension]
        assert denominator is not None
        if dimension is failed_dimension:
            dimensions.append(
                DataQualityDimensionResult(
                    dimension,
                    DataQualityDimensionState.UNAVAILABLE,
                    reason_code=DataQualityDimensionReasonCode.MISSING_REQUIRED_EVIDENCE,
                )
            )
        else:
            dimensions.append(
                DataQualityDimensionResult(
                    dimension,
                    DataQualityDimensionState.MEASURED,
                    Decimal("1"),
                    numerator=denominator,
                    denominator=denominator,
                    basis_unit=units[dimension],
                )
            )
    return DataQualityReportV2(
        _id(300 + int(policy.data_kind is ProviderDataKind.ORDER_BOOK)),
        snapshot.snapshot_id,
        CUTOFF,
        snapshot.as_of,
        policy.assessment_policy_id,
        policy.resolved_policy_version,
        tuple(dimensions),
        status,
        anomalies=anomalies,
    )


def _record_ref(
    contract_id: str, record: object, record_id: str, lineage: str
) -> AnalysisRecordReference:
    return AnalysisRecordReference(
        contract_id,
        record_id,
        str(getattr(record, "schema_version")),
        lineage,
        canonical_sha256(record),
    )


def _case(
    *,
    modalities: tuple[InputModality, ...] = (
        InputModality.SPOT_TRADES,
        InputModality.ORDER_BOOK,
    ),
    failed_modality: InputModality | None = None,
    failed_status: DataQualityStatus = DataQualityStatus.UNAVAILABLE,
    degraded_modality: InputModality | None = None,
    anomaly: str | None = None,
    future_modality: InputModality | None = None,
    stale_modality: InputModality | None = None,
    dataset_modality: InputModality | None = None,
    snapshot_cutoffs: dict[InputModality, datetime] | None = None,
) -> tuple[
    tuple[InputBindingV2, ...],
    dict[UUID, MarketSnapshot],
    dict[UUID, DataQualityReportV2],
    dict[UUID, MarketData],
    dict[UUID, DataSourceRecord],
    dict[tuple[str, str], DatasetVersion],
]:
    bindings = []
    snapshots = {}
    reports = {}
    observations = {}
    sources = {}
    datasets = {}
    for index, modality in enumerate(modalities):
        snapshot_cutoff = (
            CUTOFF
            if snapshot_cutoffs is None
            else snapshot_cutoffs.get(modality, CUTOFF)
        )
        policy = _policy(modality, snapshot_cutoff)
        event_times = (
            (
                snapshot_cutoff - timedelta(seconds=2),
                snapshot_cutoff - timedelta(seconds=1),
            )
            if modality is InputModality.SPOT_TRADES
            else (snapshot_cutoff,)
        )
        record_values = []
        source_values = []
        for offset, when in enumerate(event_times):
            number = 10 + (index * 10) + offset
            observation_time = (
                snapshot_cutoff + timedelta(seconds=1)
                if modality is future_modality
                else snapshot_cutoff - timedelta(seconds=20)
                if modality is stale_modality
                else when
            )
            source = _source(_id(number + 100), observation_time)
            observation = _observation(
                _id(number), source.source_record_id, modality, observation_time
            )
            record_values.append(observation)
            source_values.append(source)
            observations[observation.market_data_id] = observation
            sources[source.source_record_id] = source
        dataset = (
            DatasetVersion(
                f"dataset-{modality.value}",
                "v1",
                snapshot_cutoff,
                min(item.event_time for item in record_values),
                max(item.event_time for item in record_values),
                snapshot_cutoff,
                tuple(item.source_record_id for item in source_values),
                "1",
                HASH,
            )
            if modality is dataset_modality
            else None
        )
        if dataset is not None:
            datasets[(dataset.dataset_id, dataset.version)] = dataset
        snapshot = MarketSnapshot(
            _id(200 + index),
            snapshot_cutoff,
            snapshot_cutoff,
            INSTRUMENT,
            VENUE,
            tuple(item.market_data_id for item in record_values),
            tuple(item.source_record_id for item in source_values),
            None
            if dataset is None
            else DatasetVersionReference(dataset.dataset_id, dataset.version),
        )
        policy_report_status = (
            failed_status
            if modality is failed_modality
            else DataQualityStatus.DEGRADED
            if modality is degraded_modality
            else DataQualityStatus.VALID
        )
        report = _report(
            snapshot,
            policy,
            status=policy_report_status,
            failed_dimension=(
                DataQualityDimension.FRESHNESS if modality is failed_modality else None
            ),
            anomalies=(anomaly,) if modality is degraded_modality and anomaly else (),
        )
        snapshots[snapshot.snapshot_id] = snapshot
        reports[report.report_id] = report
        binding_id = _id(400 + index)
        bindings.append(
            InputBindingV2(
                binding_id,
                modality,
                _record_ref("C-002", snapshot, str(snapshot.snapshot_id), "1"),
                snapshot.as_of,
                CUTOFF,
                INSTRUMENT,
                VENUE,
                _record_ref("C-003", report, str(report.report_id), "2"),
                QualityPolicyReference(
                    policy.assessment_policy_id, policy.resolved_policy_version
                ),
                tuple(
                    ObservationSourceBinding(
                        _record_ref(
                            "C-001", observation, str(observation.market_data_id), "1"
                        ),
                        _record_ref("C-091", source, str(source.source_record_id), "1"),
                    )
                    for observation, source in zip(record_values, source_values)
                ),
                tuple(
                    _record_ref("C-091", source, str(source.source_record_id), "1")
                    for source in source_values
                ),
                None
                if dataset is None
                else _record_ref("C-092", dataset, dataset.dataset_id, dataset.version),
            )
        )
    bindings.sort(
        key=lambda item: (item.modality.value, item.market_snapshot.record_id)
    )
    return tuple(bindings), snapshots, reports, observations, sources, datasets


def _evidence(
    binding: InputBindingV2,
    report: DataQualityReportV2,
    observations: tuple[MarketData, ...],
    evidence_id: UUID,
) -> EvidenceItemV2:
    limitations = (
        *report.missing_fields,
        *report.invalid_record_ids,
        *report.duplicate_record_ids,
        *report.anomalies,
        *report.source_conflicts,
    )
    return EvidenceItemV2(
        evidence_id,
        (binding.binding_id,),
        tuple(item.market_data_id for item in observations),
        tuple(item.source_record_id for item in observations),
        (),
        (),
        ClaimClassification.FACT,
        EvidenceRelation.SUPPORTING,
        min(item.event_time for item in observations),
        CUTOFF,
        EXPIRES,
        VersionReference("order-flow-method", "1"),
        "observed",
        "USDT",
        "Synthetic contract evidence.",
        report.status,
        Decimal("1"),
        limitations,
        (VersionReference("producer", "1"),),
        report.status in {DataQualityStatus.VALID, DataQualityStatus.DEGRADED},
    )


def _metric(
    name: OrderFlowMetricName,
    binding: InputBindingV2,
    evidence_id: UUID,
    *,
    value: Decimal | None = Decimal("1"),
    state: OrderFlowMetricState = OrderFlowMetricState.AVAILABLE,
    window_start: datetime | None = None,
    reason: str | None = None,
    limitations: tuple[str, ...] = (),
) -> OrderFlowMetric:
    point = binding.modality is InputModality.ORDER_BOOK
    return OrderFlowMetric(
        name,
        state,
        value,
        "USDT",
        CUTOFF,
        CUTOFF if point else (window_start or CUTOFF - timedelta(seconds=2)),
        CUTOFF,
        VersionReference("order-flow-method", "1"),
        (evidence_id,),
        (binding.binding_id,),
        limitations,
        reason,
    )


def _manifest(
    bindings: tuple[InputBindingV2, ...],
    assessments: tuple[UUID, ...],
    evidence: tuple[UUID, ...],
):
    return create_analysis_snapshot_v2(
        snapshot_id=_id(500),
        asset="BTC",
        instrument_id=INSTRUMENT,
        venue_id=VENUE,
        timeframe="1m",
        analysis_cutoff=CUTOFF,
        created_at=CREATED,
        expires_at=EXPIRES,
        bindings=bindings,
        assessment_ids=assessments,
        evidence_ids=evidence,
        provenance=(VersionReference("analysis", "2"),),
    )


def _resolved(case: tuple[object, ...]):
    bindings, snapshots, reports, observations, sources, datasets = case
    manifest = _manifest(bindings, (_id(600),), (_id(700), _id(701)))
    resolved = resolve_analysis_snapshot_v2(
        manifest,
        now=CREATED,
        snapshots=snapshots,
        reports=reports,
        observations=observations,
        sources=sources,
        datasets=datasets,
    )
    return manifest, resolved


def test_v1_analysis_records_keep_schema_and_canonical_identity() -> None:
    from trading_platform_api.analysis import (
        AnalysisSnapshot,
        EvidenceItem,
        MarketContext,
    )

    evidence = EvidenceItem(
        _id(1),
        (_id(2),),
        (),
        (),
        ClaimClassification.FACT,
        EvidenceRelation.SUPPORTING,
        T0,
        T0 + timedelta(seconds=1),
        T0 + timedelta(seconds=2),
        VersionReference("method", "1"),
        "value",
        None,
        "interpretation",
        DataQualityStatus.VALID,
        _id(3),
        Decimal("1"),
        (),
        (VersionReference("producer", "1"),),
        True,
    )
    snapshot = AnalysisSnapshot(
        _id(4),
        "BTC",
        INSTRUMENT,
        "1m",
        T0,
        T0 + timedelta(seconds=1),
        T0 + timedelta(seconds=2),
        _id(5),
        _id(6),
        (),
        (),
        (_id(7),),
        (_id(8),),
        (VersionReference("analysis", "1"),),
        HASH,
    )
    evidence_id = _id(8)
    fixed_assessment = FundamentalAssessment(
        _id(10),
        "BTC",
        INSTRUMENT,
        "1h",
        T0,
        T0 + timedelta(seconds=1),
        T0 + timedelta(seconds=2),
        AssessmentStatus.AVAILABLE,
        Decimal("0.7"),
        (
            AnalyticalFinding(
                _id(11),
                "use-case",
                ClaimClassification.FACT,
                "Usage increased.",
                (evidence_id,),
                VersionReference("method", "1"),
                "Usage reverses.",
            ),
        ),
        (
            DomainObservation(
                "use-case",
                "increased",
                None,
                "1h",
                VersionReference("calculation", "1"),
                (evidence_id,),
            ),
        ),
        (evidence_id,),
        (),
        (),
        _id(6),
        (VersionReference("agent", "1"),),
        MethodologyCategory.FUNDAMENTAL,
    )
    regime = MarketRegime(
        _id(12),
        "BTC",
        INSTRUMENT,
        "1h",
        T0,
        T0 + timedelta(seconds=2),
        AnalyticalDirection.MIXED,
        (RegimeDimension("volatility", "normal", (evidence_id,)),),
        "Regime context.",
        Decimal("0.5"),
        (evidence_id,),
        (),
    )
    confluence = ConfluenceAssessment(
        _id(13),
        T0,
        T0 + timedelta(seconds=2),
        ConfluenceState.ALIGNED,
        (
            ConfluenceComponent(
                "fundamental",
                AnalyticalDirection.BULLISH,
                EvidenceRelation.SUPPORTING,
                Decimal("0.6"),
                __import__(
                    "trading_platform_api.analysis", fromlist=["EvidenceDependence"]
                ).EvidenceDependence.INDEPENDENT,
                (evidence_id,),
            ),
        ),
        Decimal("0.5"),
        Decimal("0.6"),
        AgentIndependenceReference(_id(14), "1"),
        "Independent evidence.",
    )
    context = MarketContext(
        _id(9),
        "BTC",
        INSTRUMENT,
        T0,
        T0 + timedelta(seconds=2),
        ("1m stable",),
        regime,
        (fixed_assessment,),
        confluence,
        (),
        AdversarialAssessment(
            _id(15),
            T0,
            T0 + timedelta(seconds=2),
            "Alternative explanation.",
            ("Liquidity effects",),
            (evidence_id,),
            ("Reversal",),
            (),
            (),
            (),
            Decimal("0.5"),
        ),
        (
            AnalyticalUncertainty(
                _id(16),
                UncertaintyCategory.DATA,
                "Data uncertainty.",
                (_id(11),),
                ("fundamental",),
                Decimal("0.2"),
                True,
                ("additional source",),
                T0,
                T0 + timedelta(seconds=2),
                ResolutionStatus.UNRESOLVED,
            ),
        ),
        (evidence_id,),
        _id(4),
        _id(6),
    )
    expected_hashes = (
        (
            (
                "2a3e22e7",
                "dbb9b0a5",
                "12d76c53",
                "9e7d8cf8",
                "aacb006b",
                "9f5e3c36",
                "b4a4b6b5",
                "79281b9b",
            ),
            (
                "809293a9",
                "050e2727",
                "fbb0a504",
                "34ae4f6d",
                "4867cd44",
                "25834d0f",
                "ab1ddfe5",
                "9c53e7ad",
            ),
        ),
        (
            (
                "cf3fa2f8",
                "1c510ddb",
                "68158330",
                "47b96782",
                "2211d7f6",
                "e7a5a2f6",
                "b77034c5",
                "9748368a",
            ),
            (
                "323b720e",
                "74980032",
                "d226c794",
                "8ed3e462",
                "e9391b1b",
                "e4af08b7",
                "76419d41",
                "5808abc7",
            ),
        ),
        (
            (
                "c304e89d",
                "9f1e1808",
                "0765d8d4",
                "241b888b",
                "ebd4fd1a",
                "8fc9892e",
                "cb1b5bcc",
                "786478e9",
            ),
            (
                "5dfcd861",
                "9cdeb635",
                "38140686",
                "6d61db53",
                "04995ed6",
                "f4dbe5f1",
                "e4ea42ba",
                "2f7a145e",
            ),
        ),
    )
    records = (evidence, snapshot, context)
    for record, expected in zip(records, expected_hashes):
        encoded = encode_analysis_contract(record)
        assert canonical_sha256(record) == "".join(expected[0])
        assert sha256(encoded.encode("utf-8")).hexdigest() == "".join(expected[1])
        assert decode_analysis_contract(encoded) == record


def test_v2_manifest_mixed_bindings_and_codec_are_deterministic() -> None:
    case = _case()
    manifest, resolved = _resolved(case)
    assert [item.binding.modality for item in resolved] == [
        InputModality.ORDER_BOOK,
        InputModality.SPOT_TRADES,
    ]
    assert analysis_snapshot_v2_sha256(manifest) == manifest.content_sha256
    assert encode_analysis_contract(manifest) == encode_analysis_contract(manifest)
    assert decode_analysis_contract(encode_analysis_contract(manifest)) == manifest
    assert (
        decode_analysis_contract(encode_analysis_contract(manifest).encode())
        == manifest
    )
    with pytest.raises(AnalysisV2ContractError, match="UTF-8"):
        decode_analysis_contract(b"\xff")


def test_v2_c008_and_c006_round_trip_and_manifest_reference_closure() -> None:
    case = _case()
    bindings, _, reports, observations, _, _ = case
    assessment_id = _id(600)
    evidence_by_binding = {
        item.modality: _evidence(
            item,
            next(
                report
                for report in reports.values()
                if report.snapshot_id == UUID(item.market_snapshot.record_id)
            ),
            tuple(
                observations[UUID(link.observation.record_id)]
                for link in item.observations
            ),
            _id(700 + index),
        )
        for index, item in enumerate(bindings)
    }
    trades = next(
        item for item in bindings if item.modality is InputModality.SPOT_TRADES
    )
    book = next(item for item in bindings if item.modality is InputModality.ORDER_BOOK)
    trade_evidence = evidence_by_binding[InputModality.SPOT_TRADES]
    book_evidence = evidence_by_binding[InputModality.ORDER_BOOK]
    assessment = OrderFlowAssessment(
        assessment_id,
        "BTC",
        INSTRUMENT,
        VENUE,
        CUTOFF,
        EXPIRES,
        OrderFlowAssessmentState.AVAILABLE,
        (
            _metric(
                OrderFlowMetricName.TRADE_VOLUME, trades, trade_evidence.evidence_id
            ),
            _metric(OrderFlowMetricName.SPREAD, book, book_evidence.evidence_id),
        ),
    )
    manifest = _manifest(
        bindings,
        (assessment_id,),
        (trade_evidence.evidence_id, book_evidence.evidence_id),
    )
    assert (
        decode_analysis_contract(encode_analysis_contract(trade_evidence))
        == trade_evidence
    )

    regime = MarketRegime(
        _id(800),
        "BTC",
        INSTRUMENT,
        "1m",
        CUTOFF,
        EXPIRES,
        AnalyticalDirection.MIXED,
        (RegimeDimension("volatility", "normal", (_id(801),)),),
        "Regime context.",
        Decimal("0.5"),
        (_id(801),),
        (),
    )
    context = MarketContextV2(
        _id(802),
        "BTC",
        INSTRUMENT,
        CUTOFF,
        EXPIRES,
        ("1m mixed",),
        regime,
        (assessment,),
        ConfluenceAssessment(
            _id(803),
            CUTOFF,
            EXPIRES,
            ConfluenceState.ALIGNED,
            (
                ConfluenceComponent(
                    "order-flow",
                    AnalyticalDirection.MIXED,
                    EvidenceRelation.SUPPORTING,
                    Decimal("0.5"),
                    EvidenceDependence.INDEPENDENT,
                    (_id(801),),
                ),
            ),
            Decimal("0.5"),
            Decimal("0.5"),
            AgentIndependenceReference(_id(804), "1"),
            "Confluence context.",
        ),
        (),
        AdversarialAssessment(
            _id(805),
            CUTOFF,
            EXPIRES,
            "Alternative explanation.",
            ("Liquidity effects",),
            (_id(801),),
            ("Invalidation occurs",),
            (),
            (),
            (),
            Decimal("0.5"),
        ),
        (
            AnalyticalUncertainty(
                _id(806),
                UncertaintyCategory.DATA,
                "Coverage uncertainty.",
                (_id(801),),
                ("order-flow",),
                Decimal("0.2"),
                True,
                ("additional source",),
                CUTOFF,
                EXPIRES,
                ResolutionStatus.UNRESOLVED,
            ),
        ),
        manifest.evidence_ids,
        AnalysisSnapshotReference(manifest.snapshot_id, "2", manifest.content_sha256),
    )
    assert decode_analysis_contract(encode_analysis_contract(context)) == context
    _, resolved = _resolved(case)
    validate_order_flow_assessment(
        assessment,
        manifest,
        resolved_bindings=resolved,
        evidence={
            trade_evidence.evidence_id: trade_evidence,
            book_evidence.evidence_id: book_evidence,
        },
        now=CREATED,
    )
    validate_market_context_v2(
        context,
        manifest,
        resolved_bindings=resolved,
        evidence={
            trade_evidence.evidence_id: trade_evidence,
            book_evidence.evidence_id: book_evidence,
        },
        now=CREATED,
    )
    future_evidence = replace(
        trade_evidence, available_at=CUTOFF + timedelta(seconds=1)
    )
    with pytest.raises(
        AnalysisV2ContractError, match="future observation/availability"
    ):
        validate_order_flow_assessment(
            assessment,
            manifest,
            resolved_bindings=resolved,
            evidence={
                future_evidence.evidence_id: future_evidence,
                book_evidence.evidence_id: book_evidence,
            },
            now=CREATED,
        )
    expired_evidence = replace(trade_evidence, expires_at=CREATED)
    with pytest.raises(AnalysisV2ContractError, match="Evidence or manifest is stale"):
        validate_order_flow_assessment(
            assessment,
            manifest,
            resolved_bindings=resolved,
            evidence={
                expired_evidence.evidence_id: expired_evidence,
                book_evidence.evidence_id: book_evidence,
            },
            now=CREATED,
        )


def test_report_dimension_gates_and_degraded_findings_are_metric_specific() -> None:
    case = _case(
        failed_modality=InputModality.SPOT_TRADES,
        failed_status=DataQualityStatus.DEGRADED,
        degraded_modality=InputModality.ORDER_BOOK,
        anomaly="book-limit-warning",
    )
    bindings, snapshots, reports, observations, sources, datasets = case
    manifest = _manifest(bindings, (_id(600),), (_id(700), _id(701)))
    resolved = resolve_analysis_snapshot_v2(
        manifest,
        now=CREATED,
        snapshots=snapshots,
        reports=reports,
        observations=observations,
        sources=sources,
        datasets=datasets,
    )
    trade = next(
        item for item in bindings if item.modality is InputModality.SPOT_TRADES
    )
    book = next(item for item in bindings if item.modality is InputModality.ORDER_BOOK)
    trade_report = reports[UUID(trade.data_quality_report.record_id)]
    book_report = reports[UUID(book.data_quality_report.record_id)]
    assert trade_report.status is DataQualityStatus.DEGRADED
    trade_data = tuple(
        observations[UUID(link.observation.record_id)] for link in trade.observations
    )
    book_data = tuple(
        observations[UUID(link.observation.record_id)] for link in book.observations
    )
    trade_evidence = _evidence(trade, trade_report, trade_data, _id(700))
    book_evidence = _evidence(book, book_report, book_data, _id(701))
    assessment = OrderFlowAssessment(
        _id(600),
        "BTC",
        INSTRUMENT,
        VENUE,
        CUTOFF,
        EXPIRES,
        OrderFlowAssessmentState.PARTIAL,
        (
            _metric(
                OrderFlowMetricName.TRADE_VOLUME,
                trade,
                trade_evidence.evidence_id,
                state=OrderFlowMetricState.UNAVAILABLE,
                value=None,
                reason="required freshness dimension unavailable",
            ),
            _metric(
                OrderFlowMetricName.SPREAD,
                book,
                book_evidence.evidence_id,
                limitations=("book-limit-warning",),
            ),
        ),
    )
    validate_order_flow_assessment(
        assessment,
        manifest,
        resolved_bindings=resolved,
        evidence={
            trade_evidence.evidence_id: trade_evidence,
            book_evidence.evidence_id: book_evidence,
        },
        now=CREATED,
    )
    bad = replace(
        assessment,
        metrics=(
            replace(
                assessment.metrics[0],
                state=OrderFlowMetricState.AVAILABLE,
                value=Decimal("0"),
                unavailable_reason=None,
            ),
            assessment.metrics[1],
        ),
        state=OrderFlowAssessmentState.AVAILABLE,
    )
    with pytest.raises(AnalysisV2ContractError, match="failed required"):
        validate_order_flow_assessment(
            bad,
            manifest,
            resolved_bindings=resolved,
            evidence={
                trade_evidence.evidence_id: trade_evidence,
                book_evidence.evidence_id: book_evidence,
            },
            now=CREATED,
        )


def test_manifest_rejects_stale_digests_unknown_policies_and_future_observations() -> (
    None
):
    case = _case()
    bindings, snapshots, reports, observations, sources, datasets = case
    manifest = _manifest(bindings, (_id(600),), (_id(700), _id(701)))
    altered = next(iter(observations.values()))
    tampered = replace(
        altered, metrics=(MetricValue("different", Decimal("1"), "unit"),)
    )
    with pytest.raises(AnalysisV2ContractError, match="provenance or cutoff"):
        resolve_analysis_snapshot_v2(
            manifest,
            now=CREATED,
            snapshots=snapshots,
            reports=reports,
            observations={**observations, altered.market_data_id: tampered},
            sources=sources,
        )

    binding = bindings[0]
    unknown_policy = replace(
        binding,
        assessment_policy=QualityPolicyReference("unknown-policy", "1"),
    )
    changed_bindings = tuple(
        unknown_policy if item.binding_id == binding.binding_id else item
        for item in bindings
    )
    invalid_manifest = _manifest(changed_bindings, (_id(600),), (_id(700), _id(701)))
    with pytest.raises(AnalysisV2ContractError, match="policy"):
        resolve_analysis_snapshot_v2(
            invalid_manifest,
            now=CREATED,
            snapshots=snapshots,
            reports=reports,
            observations=observations,
            sources=sources,
            datasets=datasets,
        )

    future_case = _case(future_modality=InputModality.SPOT_TRADES)
    (
        future_bindings,
        future_snapshots,
        future_reports,
        future_obs,
        future_sources,
        future_datasets,
    ) = future_case
    future_manifest = _manifest(future_bindings, (_id(600),), (_id(700), _id(701)))
    with pytest.raises(AnalysisV2ContractError, match="cutoff mismatch"):
        resolve_analysis_snapshot_v2(
            future_manifest,
            now=CREATED,
            snapshots=future_snapshots,
            reports=future_reports,
            observations=future_obs,
            sources=future_sources,
            datasets=future_datasets,
        )
    with pytest.raises(AnalysisV2ContractError, match="not currently valid"):
        resolve_analysis_snapshot_v2(
            manifest,
            now=EXPIRES,
            snapshots=snapshots,
            reports=reports,
            observations=observations,
            sources=sources,
            datasets=datasets,
        )


def test_unknown_schema_duplicate_bindings_and_stale_manifest_hash_fail_closed() -> (
    None
):
    case = _case()
    bindings = case[0]
    with pytest.raises(AnalysisV2ContractError, match="deterministic"):
        create_analysis_snapshot_v2(
            snapshot_id=_id(500),
            asset="BTC",
            instrument_id=INSTRUMENT,
            venue_id=VENUE,
            timeframe="1m",
            analysis_cutoff=CUTOFF,
            created_at=CREATED,
            expires_at=EXPIRES,
            bindings=tuple(reversed(bindings)),
            assessment_ids=(_id(600),),
            evidence_ids=(_id(700), _id(701)),
            provenance=(VersionReference("analysis", "2"),),
        )
    manifest = _manifest(bindings, (_id(600),), (_id(700), _id(701)))
    with pytest.raises(AnalysisV2ContractError, match="content_sha256"):
        replace(manifest, timeframe="5m")
    envelope = encode_analysis_contract(manifest).replace(
        '"schema_version":"2"', '"schema_version":"3"'
    )
    with pytest.raises(AnalysisV2ContractError, match="schema"):
        decode_analysis_contract(envelope)
    duplicate = replace(bindings[0], binding_id=bindings[1].binding_id)
    with pytest.raises(ValueError, match="duplicate"):
        _manifest((duplicate, bindings[1]), (_id(600),), (_id(700), _id(701)))


def test_attempted_cross_modal_metric_is_rejected_and_unavailable_needs_reason() -> (
    None
):
    trade = next(
        item for item in _case()[0] if item.modality is InputModality.SPOT_TRADES
    )
    with pytest.raises(AnalysisV2ContractError, match="one modality"):
        OrderFlowMetric(
            OrderFlowMetricName.VOLUME_DELTA,
            OrderFlowMetricState.AVAILABLE,
            Decimal("0"),
            "BTC",
            CUTOFF,
            CUTOFF - timedelta(seconds=2),
            CUTOFF,
            VersionReference("order-flow-method", "1"),
            (_id(700),),
            (trade.binding_id, _id(999)),
        )
    with pytest.raises(AnalysisV2ContractError, match="explicit reason"):
        OrderFlowMetric(
            OrderFlowMetricName.TRADE_VOLUME,
            OrderFlowMetricState.UNAVAILABLE,
            None,
            "BTC",
            CUTOFF,
            CUTOFF - timedelta(seconds=2),
            CUTOFF,
            VersionReference("order-flow-method", "1"),
            (_id(700),),
            (trade.binding_id,),
        )


def test_exact_report_linkage_policy_resolution_and_duplicate_membership_fail_closed() -> (
    None
):
    bindings, snapshots, reports, observations, sources, datasets = _case()
    trade = next(
        item for item in bindings if item.modality is InputModality.SPOT_TRADES
    )
    original_report = reports[UUID(trade.data_quality_report.record_id)]
    mismatched_report = replace(original_report, snapshot_id=_id(999))
    mismatched_binding = replace(
        trade,
        data_quality_report=_record_ref(
            "C-003", mismatched_report, str(mismatched_report.report_id), "2"
        ),
    )
    mismatched_bindings = tuple(
        mismatched_binding if item.binding_id == trade.binding_id else item
        for item in bindings
    )
    mismatch_manifest = _manifest(
        mismatched_bindings, (_id(600),), (_id(700), _id(701))
    )
    with pytest.raises(
        AnalysisV2ContractError, match="identity, digest, policy, or cutoff"
    ):
        resolve_analysis_snapshot_v2(
            mismatch_manifest,
            now=CREATED,
            snapshots=snapshots,
            reports={**reports, mismatched_report.report_id: mismatched_report},
            observations=observations,
            sources=sources,
            datasets=datasets,
        )

    unknown_policy_report = replace(
        original_report,
        assessment_policy_version="2",
    )
    unknown_policy_binding = replace(
        trade,
        data_quality_report=_record_ref(
            "C-003", unknown_policy_report, str(unknown_policy_report.report_id), "2"
        ),
        assessment_policy=QualityPolicyReference(
            original_report.assessment_policy_id, "2"
        ),
    )
    unknown_policy_bindings = tuple(
        unknown_policy_binding if item.binding_id == trade.binding_id else item
        for item in bindings
    )
    unknown_policy_manifest = _manifest(
        unknown_policy_bindings, (_id(600),), (_id(700), _id(701))
    )
    with pytest.raises(
        AnalysisV2ContractError, match="Unknown C-003 assessment policy"
    ):
        resolve_analysis_snapshot_v2(
            unknown_policy_manifest,
            now=CREATED,
            snapshots=snapshots,
            reports={**reports, unknown_policy_report.report_id: unknown_policy_report},
            observations=observations,
            sources=sources,
            datasets=datasets,
        )

    with pytest.raises(ValueError, match="observation references"):
        replace(
            trade,
            observations=(trade.observations[0], trade.observations[0]),
        )


def test_dataset_closure_and_different_snapshot_cutoffs_are_explicit() -> None:
    cutoffs = {
        InputModality.ORDER_BOOK: CUTOFF - timedelta(seconds=1),
        InputModality.SPOT_TRADES: CUTOFF,
    }
    case = _case(
        dataset_modality=InputModality.ORDER_BOOK,
        snapshot_cutoffs=cutoffs,
    )
    bindings, snapshots, reports, observations, sources, datasets = case
    manifest = _manifest(bindings, (_id(600),), (_id(700), _id(701)))
    resolved = resolve_analysis_snapshot_v2(
        manifest,
        now=CREATED,
        snapshots=snapshots,
        reports=reports,
        observations=observations,
        sources=sources,
        datasets=datasets,
    )
    assert len({item.snapshot.as_of for item in resolved}) == 2
    assert sum(item.dataset is not None for item in resolved) == 1

    with pytest.raises(AnalysisV2ContractError, match="C-092 dataset is unresolved"):
        resolve_analysis_snapshot_v2(
            manifest,
            now=CREATED,
            snapshots=snapshots,
            reports=reports,
            observations=observations,
            sources=sources,
        )
    dataset_key, dataset = next(iter(datasets.items()))
    changed_dataset = replace(dataset, lineage_sha256="b" * 64)
    with pytest.raises(AnalysisV2ContractError, match="C-092 identity"):
        resolve_analysis_snapshot_v2(
            manifest,
            now=CREATED,
            snapshots=snapshots,
            reports=reports,
            observations=observations,
            sources=sources,
            datasets={dataset_key: changed_dataset},
        )


def test_stale_book_and_unknown_aggressor_make_only_dependent_metrics_unavailable() -> (
    None
):
    stale_case = _case(stale_modality=InputModality.ORDER_BOOK)
    bindings, snapshots, reports, observations, sources, datasets = stale_case
    manifest = _manifest(bindings, (_id(600),), (_id(701),))
    resolved = resolve_analysis_snapshot_v2(
        manifest,
        now=CREATED,
        snapshots=snapshots,
        reports=reports,
        observations=observations,
        sources=sources,
        datasets=datasets,
    )
    book = next(item for item in bindings if item.modality is InputModality.ORDER_BOOK)
    book_report = reports[UUID(book.data_quality_report.record_id)]
    book_observations = tuple(
        observations[UUID(item.observation.record_id)] for item in book.observations
    )
    book_evidence = _evidence(book, book_report, book_observations, _id(701))
    assessment = OrderFlowAssessment(
        _id(600),
        "BTC",
        INSTRUMENT,
        VENUE,
        CUTOFF,
        EXPIRES,
        OrderFlowAssessmentState.AVAILABLE,
        (_metric(OrderFlowMetricName.SPREAD, book, book_evidence.evidence_id),),
    )
    with pytest.raises(AnalysisV2ContractError, match="failed required"):
        validate_order_flow_assessment(
            assessment,
            manifest,
            resolved_bindings=resolved,
            evidence={book_evidence.evidence_id: book_evidence},
            now=CREATED,
        )

    unknown_side_case = _case(
        degraded_modality=InputModality.SPOT_TRADES,
        anomaly="unknown-aggressor:event-1",
    )
    bindings, snapshots, reports, observations, sources, datasets = unknown_side_case
    manifest = _manifest(bindings, (_id(601),), (_id(702),))
    resolved = resolve_analysis_snapshot_v2(
        manifest,
        now=CREATED,
        snapshots=snapshots,
        reports=reports,
        observations=observations,
        sources=sources,
        datasets=datasets,
    )
    trade = next(
        item for item in bindings if item.modality is InputModality.SPOT_TRADES
    )
    trade_report = reports[UUID(trade.data_quality_report.record_id)]
    trade_observations = tuple(
        observations[UUID(item.observation.record_id)] for item in trade.observations
    )
    trade_evidence = _evidence(trade, trade_report, trade_observations, _id(702))
    flow = OrderFlowAssessment(
        _id(601),
        "BTC",
        INSTRUMENT,
        VENUE,
        CUTOFF,
        EXPIRES,
        OrderFlowAssessmentState.AVAILABLE,
        (
            _metric(
                OrderFlowMetricName.VOLUME_DELTA,
                trade,
                trade_evidence.evidence_id,
                limitations=("unknown-aggressor:event-1",),
            ),
        ),
    )
    with pytest.raises(AnalysisV2ContractError, match="Unknown aggressor side"):
        validate_order_flow_assessment(
            flow,
            manifest,
            resolved_bindings=resolved,
            evidence={trade_evidence.evidence_id: trade_evidence},
            now=CREATED,
        )


def test_trade_continuity_na_and_window_boundary_cannot_qualify_flow() -> None:
    case = _case(modalities=(InputModality.SPOT_TRADES,))
    bindings, snapshots, reports, observations, sources, datasets = case
    trade = bindings[0]
    original = reports[UUID(trade.data_quality_report.record_id)]
    n_a_continuity = DataQualityDimensionResult(
        DataQualityDimension.CONTINUITY,
        DataQualityDimensionState.NOT_APPLICABLE,
        reason_code=DataQualityDimensionReasonCode.SINGLE_POINT_SNAPSHOT,
        not_applicable_policy=QualityPolicyReference(
            original.assessment_policy_id, original.assessment_policy_version
        ),
    )
    report_dimensions = tuple(
        n_a_continuity if item.dimension is DataQualityDimension.CONTINUITY else item
        for item in original.dimensions
    )
    n_a_report = replace(original, dimensions=report_dimensions)
    changed_binding = replace(
        trade,
        data_quality_report=_record_ref(
            "C-003", n_a_report, str(n_a_report.report_id), "2"
        ),
    )
    changed_bindings = (changed_binding,)
    manifest = _manifest(changed_bindings, (_id(600),), (_id(700),))
    resolved = resolve_analysis_snapshot_v2(
        manifest,
        now=CREATED,
        snapshots=snapshots,
        reports={**reports, n_a_report.report_id: n_a_report},
        observations=observations,
        sources=sources,
        datasets=datasets,
    )
    trade_observations = tuple(
        observations[UUID(item.observation.record_id)]
        for item in changed_binding.observations
    )
    evidence = _evidence(changed_binding, n_a_report, trade_observations, _id(700))
    flow = OrderFlowAssessment(
        _id(600),
        "BTC",
        INSTRUMENT,
        VENUE,
        CUTOFF,
        EXPIRES,
        OrderFlowAssessmentState.AVAILABLE,
        (
            _metric(
                OrderFlowMetricName.TRADE_VOLUME, changed_binding, evidence.evidence_id
            ),
        ),
    )
    with pytest.raises(AnalysisV2ContractError, match="failed required"):
        validate_order_flow_assessment(
            flow,
            manifest,
            resolved_bindings=resolved,
            evidence={evidence.evidence_id: evidence},
            now=CREATED,
        )

    valid_case = _case(modalities=(InputModality.SPOT_TRADES,))
    valid_bindings, snapshots, reports, observations, sources, datasets = valid_case
    manifest = _manifest(valid_bindings, (_id(601),), (_id(701),))
    resolved = resolve_analysis_snapshot_v2(
        manifest,
        now=CREATED,
        snapshots=snapshots,
        reports=reports,
        observations=observations,
        sources=sources,
        datasets=datasets,
    )
    valid_trade = valid_bindings[0]
    report = reports[UUID(valid_trade.data_quality_report.record_id)]
    valid_observations = tuple(
        observations[UUID(item.observation.record_id)]
        for item in valid_trade.observations
    )
    evidence = _evidence(valid_trade, report, valid_observations, _id(701))
    out_of_window = _metric(
        OrderFlowMetricName.TRADE_VOLUME,
        valid_trade,
        evidence.evidence_id,
        window_start=CUTOFF - timedelta(seconds=3),
    )
    assessment = OrderFlowAssessment(
        _id(601),
        "BTC",
        INSTRUMENT,
        VENUE,
        CUTOFF,
        EXPIRES,
        OrderFlowAssessmentState.AVAILABLE,
        (out_of_window,),
    )
    with pytest.raises(AnalysisV2ContractError, match="window does not match"):
        validate_order_flow_assessment(
            assessment,
            manifest,
            resolved_bindings=resolved,
            evidence={evidence.evidence_id: evidence},
            now=CREATED,
        )


def test_partial_metric_requires_a_value_and_explanation() -> None:
    trade = next(
        item for item in _case()[0] if item.modality is InputModality.SPOT_TRADES
    )
    partial = _metric(
        OrderFlowMetricName.TRADE_VOLUME,
        trade,
        _id(700),
        state=OrderFlowMetricState.PARTIAL,
        limitations=("partial population",),
    )
    assert partial.value == Decimal("1")
    with pytest.raises(AnalysisV2ContractError, match="PARTIAL metrics require"):
        replace(partial, limitations=())
    with pytest.raises(AnalysisV2ContractError, match="cannot be negative"):
        _metric(
            OrderFlowMetricName.SPREAD,
            trade,
            _id(700),
            value=Decimal("-1"),
        )
    with pytest.raises(AnalysisV2ContractError, match="between -1 and 1"):
        _metric(
            OrderFlowMetricName.BOOK_IMBALANCE,
            trade,
            _id(700),
            value=Decimal("1.1"),
        )
