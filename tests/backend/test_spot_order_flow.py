"""Synthetic deterministic Spot order-flow tests; no providers or market claims."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from test_data_quality_spot_v2 import (
    CUTOFF,
    INSTRUMENT_ID,
    VENUE_ID,
    book_quality_policy,
    initial_book,
    snapshot_for_books,
    trade_event,
    trade_policy,
)
from test_trade_tick_normalization import policy as trade_normalization_policy
from trading_platform_api.analysis import (
    AnalysisRecordReference,
    InputBindingV2,
    InputModality,
    ObservationSourceBinding,
    OrderFlowMetricName,
    OrderFlowMetricState,
    SpotOrderFlowError,
    SpotOrderFlowPolicy,
    VersionReference,
    calculate_spot_order_flow,
    create_analysis_snapshot_v2,
    resolve_analysis_snapshot_v2,
    validate_order_flow_assessment,
)
from trading_platform_api.contracts.serialization import canonical_sha256
from trading_platform_api.market_data import (
    AssessmentPolicyReference,
    BookLevel,
    DataQualityDimension,
    DataQualityDimensionReasonCode,
    DataQualityDimensionResult,
    DataQualityDimensionState,
    DataQualityReportV2,
    DataQualityStatus,
    MarketSnapshot,
    NormalizedTradeTicks,
    ReportedSide,
    SideSemantics,
    assess_normalized_spot_order_book,
    assess_normalized_spot_trades,
    normalize_trade_ticks,
)

NOW = CUTOFF
EXPIRES = CUTOFF + timedelta(seconds=5)
BASE = "BTC"
QUOTE = "USDT"
METHOD_POLICY = SpotOrderFlowPolicy(BASE, QUOTE, depth_levels=1)


def _id(value: int) -> UUID:
    return UUID(f"00000000-0000-0000-0000-{value:012d}")


def _ref(
    contract: str, record: object, record_id: str, lineage: str
) -> AnalysisRecordReference:
    return AnalysisRecordReference(
        contract,
        record_id,
        str(getattr(record, "schema_version")),
        lineage,
        canonical_sha256(record),
    )


def _trade_inputs(
    *,
    unknown_side: bool = False,
    sequenced: bool = True,
) -> tuple[NormalizedTradeTicks, MarketSnapshot, DataQualityReportV2]:
    events = tuple(
        trade_event(
            f"flow-event-{index}",
            when=datetime(2026, 1, 1, tzinfo=UTC) + timedelta(seconds=index + 1),
            sequence=100 + index if sequenced else None,
            sequence_scope="synthetic-trade-stream" if sequenced else None,
            reported_side=ReportedSide.BUY if index == 0 else ReportedSide.SELL,
            side_semantics=(
                SideSemantics.UNKNOWN
                if unknown_side and index == 1
                else SideSemantics.AGGRESSOR
            ),
            quantity=Decimal("2.000") if index == 0 else Decimal("3.000"),
            instrument_id=INSTRUMENT_ID,
            venue_id=VENUE_ID,
            price_unit=QUOTE,
            quantity_unit=BASE,
        )
        for index in range(2)
    )
    normalized = normalize_trade_ticks(
        events,
        trade_normalization_policy(
            instrument_id=INSTRUMENT_ID,
            venue_id=VENUE_ID,
            price_unit=QUOTE,
            quantity_unit=BASE,
            maximum_records=2,
        ),
    )
    snapshot = MarketSnapshot(
        uuid4(),
        CUTOFF,
        CUTOFF,
        INSTRUMENT_ID,
        VENUE_ID,
        tuple(item.market_data_id for item in normalized.market_data),
        tuple(item.source_record_id for item in normalized.source_records),
    )
    quality_policy = trade_policy(cutoff=CUTOFF)
    report = assess_normalized_spot_trades(
        snapshot, normalized, quality_policy, assessed_at=CUTOFF
    )
    return normalized, snapshot, report


def _book_inputs():
    transition = initial_book()
    snapshot = snapshot_for_books((transition,), cutoff=CUTOFF)
    report = assess_normalized_spot_order_book(
        snapshot,
        (transition,),
        book_quality_policy(cutoff=CUTOFF),
        assessed_at=CUTOFF,
    )
    return transition, snapshot, report


def _analysis_case(
    *,
    unknown_side: bool = False,
    sequenced: bool = True,
    failed_trade_accuracy: bool = False,
    degraded_book: bool = False,
    include_trade: bool = True,
    include_book: bool = True,
):
    trade = (
        _trade_inputs(unknown_side=unknown_side, sequenced=sequenced)
        if include_trade
        else None
    )
    if trade is not None and failed_trade_accuracy:
        normalized, snapshot, report = trade
        dimensions = tuple(
            DataQualityDimensionResult(
                value.dimension,
                DataQualityDimensionState.UNAVAILABLE,
                reason_code=DataQualityDimensionReasonCode.MISSING_REQUIRED_EVIDENCE,
            )
            if value.dimension is DataQualityDimension.ACCURACY
            else value
            for value in report.dimensions
        )
        trade = (
            normalized,
            snapshot,
            replace(
                report, dimensions=dimensions, status=DataQualityStatus.UNAVAILABLE
            ),
        )
    book = _book_inputs() if include_book else None
    if book is not None and degraded_book:
        transition, snapshot, report = book
        book = (
            transition,
            snapshot,
            replace(
                report,
                status=DataQualityStatus.DEGRADED,
                anomalies=("extreme-spread-warning",),
            ),
        )
    bindings = []
    snapshots: dict[UUID, MarketSnapshot] = {}
    reports: dict[UUID, DataQualityReportV2] = {}
    modalities: list[InputModality] = []
    if trade is not None:
        handoff, snapshot, report = trade
        snapshots[snapshot.snapshot_id] = snapshot
        reports[report.report_id] = report
        modalities.append(InputModality.SPOT_TRADES)
        bindings.append(
            InputBindingV2(
                _id(101),
                InputModality.SPOT_TRADES,
                _ref("C-002", snapshot, str(snapshot.snapshot_id), "1"),
                snapshot.as_of,
                CUTOFF,
                INSTRUMENT_ID,
                VENUE_ID,
                _ref("C-003", report, str(report.report_id), "2"),
                AssessmentPolicyReference(
                    report.assessment_policy_id, report.assessment_policy_version
                ),
                tuple(
                    ObservationSourceBinding(
                        _ref(
                            "C-001", observation, str(observation.market_data_id), "1"
                        ),
                        _ref("C-091", source, str(source.source_record_id), "1"),
                    )
                    for observation, source in zip(
                        handoff.market_data, handoff.source_records
                    )
                ),
                tuple(
                    _ref("C-091", source, str(source.source_record_id), "1")
                    for source in handoff.source_records
                ),
            )
        )
    if book is not None:
        transition, snapshot, report = book
        snapshots[snapshot.snapshot_id] = snapshot
        reports[report.report_id] = report
        modalities.append(InputModality.ORDER_BOOK)
        bindings.append(
            InputBindingV2(
                _id(102),
                InputModality.ORDER_BOOK,
                _ref("C-002", snapshot, str(snapshot.snapshot_id), "1"),
                snapshot.as_of,
                CUTOFF,
                INSTRUMENT_ID,
                VENUE_ID,
                _ref("C-003", report, str(report.report_id), "2"),
                AssessmentPolicyReference(
                    report.assessment_policy_id, report.assessment_policy_version
                ),
                (
                    ObservationSourceBinding(
                        _ref(
                            "C-001",
                            transition.market_data,
                            str(transition.market_data.market_data_id),
                            "1",
                        ),
                        _ref(
                            "C-091",
                            transition.source_record,
                            str(transition.source_record.source_record_id),
                            "1",
                        ),
                    ),
                ),
                (
                    _ref(
                        "C-091",
                        transition.source_record,
                        str(transition.source_record.source_record_id),
                        "1",
                    ),
                ),
            )
        )
    bindings.sort(
        key=lambda item: (item.modality.value, item.market_snapshot.record_id)
    )
    assessment_id = _id(103)
    evidence_ids = {
        modality: _id(110 + index) for index, modality in enumerate(modalities)
    }
    manifest = create_analysis_snapshot_v2(
        snapshot_id=_id(100),
        asset="BTC",
        instrument_id=INSTRUMENT_ID,
        venue_id=VENUE_ID,
        timeframe="1m",
        analysis_cutoff=CUTOFF,
        created_at=CUTOFF,
        expires_at=EXPIRES,
        bindings=tuple(bindings),
        assessment_ids=(assessment_id,),
        evidence_ids=tuple(evidence_ids.values()) or (_id(199),),
        provenance=(VersionReference("spot-order-flow-test", "1"),),
    )
    return trade, book, snapshots, reports, manifest, assessment_id, evidence_ids


def _calculate(case, *, policy: SpotOrderFlowPolicy = METHOD_POLICY):
    trade, book, snapshots, reports, manifest, assessment_id, evidence_ids = case
    return calculate_spot_order_flow(
        manifest,
        trade_handoff=None if trade is None else trade[0],
        book_handoff=None if book is None else (book[0],),
        snapshots=snapshots,
        reports=reports,
        policy=policy,
        assessment_id=assessment_id,
        evidence_ids=evidence_ids,
        calculated_at=CUTOFF,
        validated_at=NOW,
    )


def _metric(result, name: OrderFlowMetricName):
    return next(item for item in result.assessment.metrics if item.name is name)


def test_spot_order_flow_calculates_deterministic_book_and_trade_metrics() -> None:
    case = _analysis_case()
    result = _calculate(case)
    assert result.assessment.state.value == "AVAILABLE"
    expected = {
        OrderFlowMetricName.BEST_BID_PRICE: Decimal("99.00"),
        OrderFlowMetricName.BEST_ASK_PRICE: Decimal("101.00"),
        OrderFlowMetricName.MIDPOINT_PRICE: Decimal("100.00"),
        OrderFlowMetricName.ABSOLUTE_SPREAD: Decimal("2.00"),
        OrderFlowMetricName.SPREAD_BPS: Decimal("200"),
        OrderFlowMetricName.BID_DEPTH: Decimal("2.000"),
        OrderFlowMetricName.ASK_DEPTH: Decimal("3.000"),
        OrderFlowMetricName.BID_NOTIONAL: Decimal("198.00000"),
        OrderFlowMetricName.ASK_NOTIONAL: Decimal("303.00000"),
        OrderFlowMetricName.BOOK_IMBALANCE: Decimal("-0.2"),
        OrderFlowMetricName.TRADE_RECORD_COUNT: 2,
        OrderFlowMetricName.BUY_AGGRESSOR_VOLUME: Decimal("2.000"),
        OrderFlowMetricName.SELL_AGGRESSOR_VOLUME: Decimal("3.000"),
        OrderFlowMetricName.VOLUME_DELTA: Decimal("-1.000"),
        OrderFlowMetricName.CUMULATIVE_DELTA: Decimal("-1.000"),
    }
    assert {item.name: item.value for item in result.assessment.metrics} == expected
    assert len(result.evidence) == 2
    assert all(item.usable for item in result.evidence)
    assert all(
        item.method == VersionReference("spot-order-flow", "1")
        for item in result.assessment.metrics
    )
    book_imbalance = _metric(result, OrderFlowMetricName.BOOK_IMBALANCE)
    assert any(
        "bid depth − ask depth" in limitation and "denominator" in limitation
        for limitation in book_imbalance.limitations
    )
    trade_delta = _metric(result, OrderFlowMetricName.CUMULATIVE_DELTA)
    assert any(
        "anchored at the first event" in limitation
        for limitation in trade_delta.limitations
    )
    assert any("C-003 schema 2 report" in item for item in trade_delta.limitations)
    assert any("policy spot-trade-quality@" in item for item in trade_delta.limitations)
    assert any(
        "continuity=1/1 sequence_transitions" in item
        for item in trade_delta.limitations
    )

    trade, book, snapshots, reports, manifest, _, _ = case
    observations = {
        item.market_data_id: item
        for item in (*trade[0].market_data, book[0].market_data)
    }
    sources = {
        item.source_record_id: item
        for item in (*trade[0].source_records, book[0].source_record)
    }
    resolved = resolve_analysis_snapshot_v2(
        manifest,
        now=NOW,
        snapshots=snapshots,
        reports=reports,
        observations=observations,
        sources=sources,
    )
    validate_order_flow_assessment(
        result.assessment,
        manifest,
        resolved_bindings=resolved,
        evidence={item.evidence_id: item for item in result.evidence},
        now=NOW,
    )


def test_unknown_aggressor_side_never_becomes_directional_flow() -> None:
    result = _calculate(_analysis_case(unknown_side=True))
    assert _metric(result, OrderFlowMetricName.TRADE_RECORD_COUNT).state is (
        OrderFlowMetricState.AVAILABLE
    )
    for name in (
        OrderFlowMetricName.BUY_AGGRESSOR_VOLUME,
        OrderFlowMetricName.SELL_AGGRESSOR_VOLUME,
        OrderFlowMetricName.VOLUME_DELTA,
        OrderFlowMetricName.CUMULATIVE_DELTA,
    ):
        metric = _metric(result, name)
        assert metric.state is OrderFlowMetricState.UNAVAILABLE
        assert metric.value is None
        assert "Unknown" in metric.unavailable_reason
    trade_evidence = next(
        item for item in result.evidence if item.binding_ids[0] == _id(101)
    )
    assert "unknown-aggressor" in " ".join(trade_evidence.limitations)


def test_degraded_book_findings_remain_visible_without_discarding_valid_metrics() -> (
    None
):
    result = _calculate(_analysis_case(degraded_book=True))
    book_metrics = tuple(
        item
        for item in result.assessment.metrics
        if item.name
        in {
            OrderFlowMetricName.BEST_BID_PRICE,
            OrderFlowMetricName.BEST_ASK_PRICE,
            OrderFlowMetricName.MIDPOINT_PRICE,
            OrderFlowMetricName.ABSOLUTE_SPREAD,
            OrderFlowMetricName.SPREAD_BPS,
            OrderFlowMetricName.BID_DEPTH,
            OrderFlowMetricName.ASK_DEPTH,
            OrderFlowMetricName.BID_NOTIONAL,
            OrderFlowMetricName.ASK_NOTIONAL,
            OrderFlowMetricName.BOOK_IMBALANCE,
        }
    )
    assert all(
        metric.state is OrderFlowMetricState.AVAILABLE for metric in book_metrics
    )
    assert all(
        any("status DEGRADED" in item for item in metric.limitations)
        and "extreme-spread-warning" in metric.limitations
        for metric in book_metrics
    )
    book_evidence = next(
        item for item in result.evidence if item.binding_ids[0] == _id(102)
    )
    assert book_evidence.quality_status is DataQualityStatus.DEGRADED
    assert "extreme-spread-warning" in book_evidence.limitations


def test_duplicate_provider_event_identity_cannot_inflate_trade_metrics() -> None:
    case = _analysis_case()
    trade, book, snapshots, reports, manifest, assessment_id, evidence_ids = case
    normalized = trade[0]
    duplicate_identity = replace(
        normalized.identities[1],
        provider_event_id=normalized.identities[0].provider_event_id,
    )
    duplicate_handoff = replace(
        normalized,
        identities=(normalized.identities[0], duplicate_identity),
    )
    with pytest.raises(SpotOrderFlowError, match="Duplicate TRADE provider event"):
        calculate_spot_order_flow(
            manifest,
            trade_handoff=duplicate_handoff,
            book_handoff=(book[0],),
            snapshots=snapshots,
            reports=reports,
            policy=METHOD_POLICY,
            assessment_id=assessment_id,
            evidence_ids=evidence_ids,
            calculated_at=CUTOFF,
            validated_at=NOW,
        )


def test_displayed_depth_uses_exact_configured_top_n_without_truncation() -> None:
    result = _calculate(
        _analysis_case(),
        policy=SpotOrderFlowPolicy(BASE, QUOTE, depth_levels=3),
    )
    for name in (
        OrderFlowMetricName.BEST_BID_PRICE,
        OrderFlowMetricName.BEST_ASK_PRICE,
        OrderFlowMetricName.ABSOLUTE_SPREAD,
        OrderFlowMetricName.SPREAD_BPS,
    ):
        assert _metric(result, name).state is OrderFlowMetricState.AVAILABLE
    assert _metric(result, OrderFlowMetricName.SPREAD_BPS).value == Decimal("200")
    for name in (
        OrderFlowMetricName.BID_DEPTH,
        OrderFlowMetricName.ASK_DEPTH,
        OrderFlowMetricName.BID_NOTIONAL,
        OrderFlowMetricName.ASK_NOTIONAL,
        OrderFlowMetricName.BOOK_IMBALANCE,
    ):
        metric = _metric(result, name)
        assert metric.state is OrderFlowMetricState.UNAVAILABLE
        assert metric.value is None
        assert "top 3 levels" in metric.unavailable_reason


@pytest.mark.parametrize(
    ("side", "price"),
    (("bid", Decimal("101.00")), ("ask", Decimal("99.00"))),
)
def test_locked_or_crossed_point_book_is_rejected(side: str, price: Decimal) -> None:
    case = _analysis_case()
    trade, book, snapshots, reports, manifest, assessment_id, evidence_ids = case
    transition = book[0]
    state = transition.state
    invalid_state = (
        replace(state, bids=(BookLevel(price, Decimal("2.000")),))
        if side == "bid"
        else replace(state, asks=(BookLevel(price, Decimal("3.000")),))
    )
    with pytest.raises(SpotOrderFlowError, match="crossed"):
        calculate_spot_order_flow(
            manifest,
            trade_handoff=trade[0],
            book_handoff=(replace(transition, state=invalid_state),),
            snapshots=snapshots,
            reports=reports,
            policy=METHOD_POLICY,
            assessment_id=assessment_id,
            evidence_ids=evidence_ids,
            calculated_at=CUTOFF,
            validated_at=NOW,
        )


def test_malformed_book_level_numeric_type_fails_closed() -> None:
    case = _analysis_case()
    trade, book, snapshots, reports, manifest, assessment_id, evidence_ids = case
    transition = book[0]
    invalid_state = replace(
        transition.state,
        bids=(BookLevel(Decimal("99.00"), 2),),  # type: ignore[arg-type]
    )
    with pytest.raises(SpotOrderFlowError, match="Invalid or crossed"):
        calculate_spot_order_flow(
            manifest,
            trade_handoff=trade[0],
            book_handoff=(replace(transition, state=invalid_state),),
            snapshots=snapshots,
            reports=reports,
            policy=METHOD_POLICY,
            assessment_id=assessment_id,
            evidence_ids=evidence_ids,
            calculated_at=CUTOFF,
            validated_at=NOW,
        )


def test_unverified_trade_sequence_fails_closed_for_trade_metrics() -> None:
    result = _calculate(_analysis_case(sequenced=False))
    for name in (
        OrderFlowMetricName.TRADE_RECORD_COUNT,
        OrderFlowMetricName.BUY_AGGRESSOR_VOLUME,
        OrderFlowMetricName.SELL_AGGRESSOR_VOLUME,
        OrderFlowMetricName.VOLUME_DELTA,
        OrderFlowMetricName.CUMULATIVE_DELTA,
    ):
        assert _metric(result, name).state is OrderFlowMetricState.UNAVAILABLE


def test_each_trade_metric_stays_unavailable_when_required_quality_dimension_fails() -> (
    None
):
    result = _calculate(_analysis_case(failed_trade_accuracy=True))
    assert _metric(result, OrderFlowMetricName.BEST_BID_PRICE).state is (
        OrderFlowMetricState.AVAILABLE
    )
    for name in (
        OrderFlowMetricName.TRADE_RECORD_COUNT,
        OrderFlowMetricName.BUY_AGGRESSOR_VOLUME,
        OrderFlowMetricName.SELL_AGGRESSOR_VOLUME,
        OrderFlowMetricName.VOLUME_DELTA,
        OrderFlowMetricName.CUMULATIVE_DELTA,
    ):
        metric = _metric(result, name)
        assert metric.state is OrderFlowMetricState.UNAVAILABLE
        assert "accuracy=UNAVAILABLE" in metric.unavailable_reason


def test_gap_in_normalized_sequence_is_rejected_not_reinterpreted() -> None:
    case = _analysis_case()
    trade, book, snapshots, reports, manifest, assessment_id, evidence_ids = case
    handoff = trade[0]
    changed_identity = replace(
        handoff.identities[1], sequence=handoff.identities[1].sequence + 1
    )
    invalid = replace(
        handoff,
        identities=(handoff.identities[0], changed_identity),
    )
    with pytest.raises(SpotOrderFlowError, match="gap or reversal"):
        calculate_spot_order_flow(
            manifest,
            trade_handoff=invalid,
            book_handoff=(book[0],),
            snapshots=snapshots,
            reports=reports,
            policy=METHOD_POLICY,
            assessment_id=assessment_id,
            evidence_ids=evidence_ids,
            calculated_at=CUTOFF,
            validated_at=NOW,
        )


def test_cross_modality_units_must_match_exact_quality_policies() -> None:
    with pytest.raises(SpotOrderFlowError, match="TRADE handoff"):
        _calculate(
            _analysis_case(),
            policy=SpotOrderFlowPolicy("ETH", QUOTE, depth_levels=1),
        )


def test_snapshot_report_or_modality_lineage_mismatch_fails_closed() -> None:
    case = _analysis_case()
    trade, book, snapshots, reports, manifest, assessment_id, evidence_ids = case
    wrong_report = replace(
        next(iter(reports.values())), status=DataQualityStatus.INVALID
    )
    wrong_reports = dict(reports)
    wrong_reports[wrong_report.report_id] = wrong_report
    with pytest.raises(SpotOrderFlowError, match="resolution failed closed"):
        calculate_spot_order_flow(
            manifest,
            trade_handoff=trade[0],
            book_handoff=(book[0],),
            snapshots=snapshots,
            reports=wrong_reports,
            policy=METHOD_POLICY,
            assessment_id=assessment_id,
            evidence_ids=evidence_ids,
            calculated_at=CUTOFF,
            validated_at=NOW,
        )


def test_venue_mismatch_in_snapshot_binding_fails_closed() -> None:
    case = _analysis_case()
    trade, book, snapshots, reports, manifest, assessment_id, evidence_ids = case
    altered_snapshot = replace(trade[1], venue_id="SYNTHETIC-OTHER-VENUE")
    altered_snapshots = dict(snapshots)
    altered_snapshots[altered_snapshot.snapshot_id] = altered_snapshot
    with pytest.raises(SpotOrderFlowError, match="resolution failed closed"):
        calculate_spot_order_flow(
            manifest,
            trade_handoff=trade[0],
            book_handoff=(book[0],),
            snapshots=altered_snapshots,
            reports=reports,
            policy=METHOD_POLICY,
            assessment_id=assessment_id,
            evidence_ids=evidence_ids,
            calculated_at=CUTOFF,
            validated_at=NOW,
        )


def test_trade_tick_inputs_are_not_misrepresented_as_trade_flow() -> None:
    case = _analysis_case()
    trade, book, snapshots, reports, manifest, assessment_id, evidence_ids = case
    tick_binding = replace(manifest.bindings[0], modality=InputModality.SPOT_TICKS)
    invalid_manifest = create_analysis_snapshot_v2(
        snapshot_id=manifest.snapshot_id,
        asset=manifest.asset,
        instrument_id=manifest.instrument_id,
        venue_id=manifest.venue_id,
        timeframe=manifest.timeframe,
        analysis_cutoff=manifest.analysis_cutoff,
        created_at=manifest.created_at,
        expires_at=manifest.expires_at,
        bindings=tuple(
            sorted(
                (tick_binding, *manifest.bindings[1:]),
                key=lambda item: (item.modality.value, item.market_snapshot.record_id),
            )
        ),
        assessment_ids=manifest.assessment_ids,
        evidence_ids=manifest.evidence_ids,
        provenance=manifest.provenance,
    )
    with pytest.raises(SpotOrderFlowError, match="supports only TRADE"):
        calculate_spot_order_flow(
            invalid_manifest,
            trade_handoff=trade[0],
            book_handoff=(book[0],),
            snapshots=snapshots,
            reports=reports,
            policy=METHOD_POLICY,
            assessment_id=assessment_id,
            evidence_ids=evidence_ids,
            calculated_at=CUTOFF,
            validated_at=NOW,
        )
