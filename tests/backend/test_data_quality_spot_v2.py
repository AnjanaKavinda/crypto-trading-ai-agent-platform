"""Synthetic tests for in-memory C-003 v2 Spot quality assessments."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from test_order_book_normalization import (
    T0 as BOOK_T0,
)
from test_order_book_normalization import (
    contiguous,
)
from test_order_book_normalization import (
    delta as book_delta,
)
from test_order_book_normalization import (
    initial as normalize_initial_book,
)
from test_order_book_normalization import (
    policy as book_normalization_policy,
)
from test_order_book_normalization import (
    snapshot as raw_book_snapshot,
)
from test_trade_tick_normalization import (
    T0,
)
from test_trade_tick_normalization import (
    event as trade_event,
)
from test_trade_tick_normalization import (
    policy as trade_normalization_policy,
)
from trading_platform_api.market_data import (
    AssessmentPolicyReference,
    BookFailure,
    BookSide,
    BookTransition,
    ChecksumStatus,
    DataQualityAssessmentError,
    DataQualityDimension,
    DataQualityDimensionReasonCode,
    DataQualityDimensionState,
    DataQualityStatus,
    DatasetVersion,
    DatasetVersionReference,
    LevelChange,
    MarketSnapshot,
    NormalizedTradeTicks,
    OrderBookError,
    ProviderDataKind,
    ReportedSide,
    SideSemantics,
    SpotQualityMetricRule,
    SpotQualityPolicy,
    apply_book_delta,
    assess_normalized_spot_order_book,
    assess_normalized_spot_ticks,
    assess_normalized_spot_trades,
    normalize_book_snapshot,
    normalize_trade_ticks,
)

CUTOFF = T0 + timedelta(seconds=10)
PRICE_RULE = SpotQualityMetricRule(
    "price", "synthetic-quote", Decimal("1"), Decimal("1000")
)
QUANTITY_RULE = SpotQualityMetricRule(
    "quantity", "synthetic-base", Decimal("0.001"), Decimal("100")
)


def trade_batch(
    *,
    count: int = 2,
    sequenced: bool = True,
    kind: ProviderDataKind = ProviderDataKind.TRADE,
    cutoff: datetime = CUTOFF,
    side_semantics: SideSemantics = SideSemantics.AGGRESSOR,
) -> tuple[NormalizedTradeTicks, MarketSnapshot]:
    events = tuple(
        trade_event(
            f"event-{index}",
            when=T0 + timedelta(seconds=index),
            data_kind=kind,
            quantity=Decimal("2.000") if kind is ProviderDataKind.TRADE else None,
            sequence=index + 100 if sequenced else None,
            sequence_scope="trade-stream" if sequenced else None,
            reported_side=ReportedSide.BUY,
            side_semantics=side_semantics,
        )
        for index in range(count)
    )
    normalized = normalize_trade_ticks(
        events,
        trade_normalization_policy(data_kind=kind, maximum_records=max(count, 1)),
    )
    return normalized, MarketSnapshot(
        uuid4(),
        cutoff,
        cutoff,
        "synthetic-instrument",
        "synthetic-venue",
        tuple(item.market_data_id for item in normalized.market_data),
        tuple(item.source_record_id for item in normalized.source_records),
    )


def trade_policy(
    *,
    kind: ProviderDataKind = ProviderDataKind.TRADE,
    expected: int | None = 2,
    transitions: int | None = 1,
    freshness: int = 10,
    maximum_missing: int = 0,
    policy_id: str | None = None,
    cutoff: datetime = CUTOFF,
    require_comparison: bool = False,
) -> SpotQualityPolicy:
    if kind is ProviderDataKind.TRADE:
        profile = policy_id or "spot-trade-quality"
        rules = (PRICE_RULE, QUANTITY_RULE)
    else:
        profile = policy_id or "spot-tick-quality"
        rules = (PRICE_RULE,)
    return SpotQualityPolicy(
        profile,
        "1",
        kind,
        "synthetic-instrument",
        "synthetic-venue",
        cutoff,
        expected,
        freshness,
        rules,
        expected_transition_count=transitions,
        maximum_missing_records=maximum_missing,
        require_independent_comparison=require_comparison,
    )


def book_metric_rules() -> tuple[SpotQualityMetricRule, ...]:
    return (
        SpotQualityMetricRule(
            "bid_1_price", "synthetic-quote", Decimal("1"), Decimal("1000")
        ),
        SpotQualityMetricRule(
            "bid_1_quantity", "synthetic-base", Decimal("0"), Decimal("100")
        ),
        SpotQualityMetricRule(
            "ask_1_price", "synthetic-quote", Decimal("1"), Decimal("1000")
        ),
        SpotQualityMetricRule(
            "ask_1_quantity", "synthetic-base", Decimal("0"), Decimal("100")
        ),
    )


BOOK_POLICY = book_normalization_policy(extreme_spread_bps=None)


def initial_book() -> BookTransition:
    return normalize_initial_book(selected_policy=BOOK_POLICY)


def book_quality_policy(
    *,
    point: bool = True,
    expected: int | None = None,
    transitions: int | None = None,
    freshness: int = 10,
    policy_id: str | None = None,
) -> SpotQualityPolicy:
    return SpotQualityPolicy(
        policy_id or ("spot-order-book-point" if point else "spot-order-book-delta"),
        "1",
        ProviderDataKind.ORDER_BOOK,
        "synthetic-instrument",
        "synthetic-venue",
        BOOK_T0 + timedelta(seconds=10),
        (1 if point else 2) if expected is None else expected,
        freshness,
        book_metric_rules(),
        expected_transition_count=transitions if point else (
            1 if transitions is None else transitions
        ),
        require_checksum=bool(policy_id and policy_id.endswith("-checksum")),
    )


def snapshot_for_books(transitions: tuple[BookTransition, ...]) -> MarketSnapshot:
    observations = tuple(
        item.market_data
        for item in transitions
        if item.market_data is not None
    )
    sources = tuple(
        item.source_record
        for item in transitions
        if item.source_record is not None
    )
    return MarketSnapshot(
        uuid4(),
        BOOK_T0 + timedelta(seconds=10),
        BOOK_T0 + timedelta(seconds=10),
        "synthetic-instrument",
        "synthetic-venue",
        tuple(item.market_data_id for item in observations),
        tuple(item.source_record_id for item in sources),
    )


def test_trade_assessment_measures_all_seven_dimensions_from_exact_evidence() -> None:
    normalized, snapshot = trade_batch()
    report = assess_normalized_spot_trades(
        snapshot,
        normalized,
        trade_policy(),
        assessed_at=CUTOFF,
    )
    assert report.status is DataQualityStatus.VALID
    assert tuple(item.dimension for item in report.dimensions) == tuple(
        DataQualityDimension
    )
    assert tuple(item.score for item in report.dimensions) == (Decimal("1"),) * 7
    assert tuple(item.basis_unit for item in report.dimensions) == (
        "metric_cells",
        "observations",
        "observations",
        "observations",
        "source_records",
        "observations",
        "sequence_transitions",
    )
    assert report.dimensions[0].numerator == 4
    assert report.dimensions[0].denominator == 4
    assert all(item.evidence_reference is None for item in report.dimensions)
    assert report.assessment_policy_id == "spot-trade-quality"


def test_tick_requires_only_explicit_metric_cells_and_does_not_infer_side() -> None:
    normalized, snapshot = trade_batch(
        kind=ProviderDataKind.TICK,
        side_semantics=SideSemantics.UNKNOWN,
    )
    report = assess_normalized_spot_ticks(
        snapshot,
        normalized,
        trade_policy(kind=ProviderDataKind.TICK),
        assessed_at=CUTOFF,
    )
    assert report.status is DataQualityStatus.DEGRADED
    assert report.dimensions[0].numerator == 2
    assert report.dimensions[0].denominator == 2
    assert report.anomalies == ("unknown-aggressor:event-0", "unknown-aggressor:event-1")
    assert all(
        metric.metric_name != "aggressor_sign"
        for item in normalized.market_data
        for metric in item.metrics
    )


def test_unverified_sequence_and_missing_denominators_are_unavailable() -> None:
    normalized, snapshot = trade_batch(sequenced=False)
    unverified = assess_normalized_spot_trades(
        snapshot, normalized, trade_policy(), assessed_at=CUTOFF
    )
    continuity = unverified.dimensions[-1]
    assert unverified.status is DataQualityStatus.UNAVAILABLE
    assert continuity.state is DataQualityDimensionState.UNAVAILABLE
    assert continuity.reason_code is DataQualityDimensionReasonCode.SEQUENCE_UNVERIFIED
    assert continuity.score is continuity.numerator is continuity.denominator is None

    no_denominator = assess_normalized_spot_trades(
        snapshot,
        normalized,
        trade_policy(expected=None, transitions=None),
        assessed_at=CUTOFF,
    )
    assert no_denominator.status is DataQualityStatus.UNAVAILABLE
    assert all(
        result.state is DataQualityDimensionState.UNAVAILABLE
        for result in no_denominator.dimensions[:-1]
    )
    assert all(result.score is None for result in no_denominator.dimensions)
    assert (
        no_denominator.dimensions[0].reason_code
        is DataQualityDimensionReasonCode.DENOMINATOR_UNAVAILABLE
    )


def test_expected_coverage_bounds_and_deterministic_status_precedence() -> None:
    normalized, snapshot = trade_batch(count=3)
    partial = replace(
        normalized,
        market_data=normalized.market_data[:2],
        source_records=normalized.source_records[:2],
        identities=normalized.identities[:2],
    )
    partial_snapshot = replace(
        snapshot,
        market_data_ids=snapshot.market_data_ids[:2],
        source_record_ids=snapshot.source_record_ids[:2],
    )
    incomplete = assess_normalized_spot_trades(
        partial_snapshot,
        partial,
        trade_policy(expected=3, transitions=2),
        assessed_at=CUTOFF,
    )
    assert incomplete.status is DataQualityStatus.INCOMPLETE
    assert incomplete.dimensions[5].score == Decimal(2) / Decimal(3)

    degraded = assess_normalized_spot_trades(
        partial_snapshot,
        partial,
        trade_policy(expected=3, transitions=2, maximum_missing=2),
        assessed_at=CUTOFF,
    )
    assert degraded.status is DataQualityStatus.DEGRADED
    assert degraded.dimensions[-1].state is DataQualityDimensionState.MEASURED

    old_cutoff = T0 + timedelta(seconds=100)
    old_normalized, old_snapshot = trade_batch(count=3, cutoff=old_cutoff)
    stale_snapshot = replace(
        old_snapshot,
        market_data_ids=old_snapshot.market_data_ids[:2],
        source_record_ids=old_snapshot.source_record_ids[:2],
    )
    stale_normalized = replace(
        old_normalized,
        market_data=old_normalized.market_data[:2],
        source_records=old_normalized.source_records[:2],
        identities=old_normalized.identities[:2],
    )
    stale = assess_normalized_spot_trades(
        stale_snapshot,
        stale_normalized,
        trade_policy(expected=3, transitions=2, freshness=10, cutoff=old_cutoff),
        assessed_at=old_cutoff,
    )
    assert stale.status is DataQualityStatus.STALE
    unavailable_and_stale = assess_normalized_spot_trades(
        stale_snapshot,
        replace(
            stale_normalized,
            identities=tuple(
                replace(identity, sequence=None, sequence_scope=None)
                for identity in stale_normalized.identities
            ),
            quality=replace(stale_normalized.quality, sequence_verified=False),
        ),
        trade_policy(expected=3, transitions=2, freshness=10, cutoff=old_cutoff),
        assessed_at=old_cutoff,
    )
    assert unavailable_and_stale.status is DataQualityStatus.UNAVAILABLE

    unsequenced, unsequenced_snapshot = trade_batch(sequenced=False)
    bad_metric = replace(
        unsequenced.market_data[0],
        metrics=(
            replace(unsequenced.market_data[0].metrics[0], value=Decimal("1001")),
            *unsequenced.market_data[0].metrics[1:],
        ),
    )
    invalid_and_unavailable = replace(
        unsequenced,
        market_data=(bad_metric, unsequenced.market_data[1]),
    )
    combined = assess_normalized_spot_trades(
        unsequenced_snapshot,
        invalid_and_unavailable,
        trade_policy(),
        assessed_at=CUTOFF,
    )
    assert combined.status is DataQualityStatus.INVALID


def test_trade_empty_duplicates_missing_fields_and_invalid_bounds_fail_closed() -> None:
    empty = normalize_trade_ticks(
        (), trade_normalization_policy(maximum_records=1)
    )
    _, populated_snapshot = trade_batch()
    with pytest.raises(DataQualityAssessmentError, match="empty normalized batch"):
        assess_normalized_spot_trades(
            populated_snapshot,
            empty,
            trade_policy(),
            assessed_at=CUTOFF,
        )

    normalized, snapshot = trade_batch()
    duplicate = replace(
        normalized,
        quality=replace(
            normalized.quality, duplicate_event_ids=("event-0",)
        ),
    )
    assert (
        assess_normalized_spot_trades(
            snapshot, duplicate, trade_policy(), assessed_at=CUTOFF
        ).status
        is DataQualityStatus.INVALID
    )

    missing = replace(
        normalized,
        market_data=(
            replace(
                normalized.market_data[0],
                metrics=tuple(
                    metric
                    for metric in normalized.market_data[0].metrics
                    if metric.metric_name != "quantity"
                ),
            ),
            normalized.market_data[1],
        ),
    )
    missing_report = assess_normalized_spot_trades(
        snapshot, missing, trade_policy(), assessed_at=CUTOFF
    )
    assert missing_report.status is DataQualityStatus.INCOMPLETE
    assert missing_report.dimensions[0].score == Decimal("0.75")
    assert missing_report.missing_fields == (
        f"{normalized.market_data[0].market_data_id}:quantity",
    )

    wrong_unit = replace(
        normalized.market_data[0],
        metrics=tuple(
            replace(metric, unit="wrong-unit")
            if metric.metric_name == "price"
            else metric
            for metric in normalized.market_data[0].metrics
        ),
    )
    invalid = replace(
        normalized,
        market_data=(wrong_unit, normalized.market_data[1]),
    )
    assert (
        assess_normalized_spot_trades(
            snapshot, invalid, trade_policy(), assessed_at=CUTOFF
        ).status
        is DataQualityStatus.INVALID
    )


def test_measured_zero_has_only_the_contract_required_immutable_evidence() -> None:
    normalized, snapshot = trade_batch()
    zero_policy = trade_policy()
    zero_policy = replace(
        zero_policy,
        metric_rules=(
            SpotQualityMetricRule(
                "price", "synthetic-quote", Decimal("1000"), Decimal("2000")
            ),
            SpotQualityMetricRule(
                "quantity", "synthetic-base", Decimal("1000"), Decimal("2000")
            ),
        ),
    )
    report = assess_normalized_spot_trades(
        snapshot, normalized, zero_policy, assessed_at=CUTOFF
    )
    assert report.status is DataQualityStatus.INVALID
    assert report.dimensions[0].score == Decimal("0")
    assert report.dimensions[0].evidence_reference.record_id == str(snapshot.snapshot_id)
    assert report.dimensions[2].score == Decimal("0")
    assert report.dimensions[2].evidence_reference.record_id == str(snapshot.snapshot_id)


def test_policy_snapshot_cutoff_source_and_dataset_identity_are_exact() -> None:
    normalized, snapshot = trade_batch()
    with pytest.raises(DataQualityAssessmentError, match="Unknown"):
        SpotQualityPolicy(
            "caller-policy",
            "1",
            ProviderDataKind.TRADE,
            "synthetic-instrument",
            "synthetic-venue",
            CUTOFF,
            2,
            10,
            (PRICE_RULE, QUANTITY_RULE),
            expected_transition_count=1,
        )
    with pytest.raises(DataQualityAssessmentError, match="Unknown"):
        SpotQualityPolicy(
            "spot-trade-quality",
            "2",
            ProviderDataKind.TRADE,
            "synthetic-instrument",
            "synthetic-venue",
            CUTOFF,
            2,
            10,
            (PRICE_RULE, QUANTITY_RULE),
            expected_transition_count=1,
        )
    with pytest.raises(DataQualityAssessmentError, match="Independent"):
        assess_normalized_spot_trades(
            snapshot,
            normalized,
            trade_policy(
                policy_id="spot-trade-quality-independent",
                require_comparison=True,
            ),
            assessed_at=CUTOFF,
        )
    with pytest.raises(DataQualityAssessmentError, match="cutoff"):
        assess_normalized_spot_trades(
            snapshot,
            normalized,
            trade_policy(cutoff=CUTOFF + timedelta(seconds=1)),
            assessed_at=CUTOFF + timedelta(seconds=1),
        )
    with pytest.raises(DataQualityAssessmentError, match="ordered"):
        assess_normalized_spot_trades(
            replace(snapshot, market_data_ids=snapshot.market_data_ids[:1]),
            normalized,
            trade_policy(),
            assessed_at=CUTOFF,
        )
    with pytest.raises(DataQualityAssessmentError, match="Transition denominator"):
        trade_policy(expected=3, transitions=1)

    wrong_instrument = replace(
        normalized.market_data[0], instrument_id="other-instrument"
    )
    wrong_input = replace(
        normalized,
        market_data=(wrong_instrument, normalized.market_data[1]),
    )
    with pytest.raises(DataQualityAssessmentError, match="identity"):
        assess_normalized_spot_trades(
            snapshot, wrong_input, trade_policy(), assessed_at=CUTOFF
        )

    wrong_source = replace(
        normalized.source_records[0], source_record_id=uuid4()
    )
    wrong_source_batch = replace(
        normalized, source_records=(wrong_source, normalized.source_records[1])
    )
    wrong_source_snapshot = replace(
        snapshot,
        source_record_ids=(
            wrong_source.source_record_id,
            snapshot.source_record_ids[1],
        ),
    )
    with pytest.raises(DataQualityAssessmentError, match="ordered"):
        assess_normalized_spot_trades(
            wrong_source_snapshot,
            wrong_source_batch,
            trade_policy(),
            assessed_at=CUTOFF,
        )
    with pytest.raises(DataQualityAssessmentError, match="Dataset"):
        assess_normalized_spot_trades(
            snapshot,
            normalized,
            trade_policy(),
            assessed_at=CUTOFF,
            dataset=DatasetVersion(
                "unreferenced",
                "1",
                CUTOFF,
                T0,
                CUTOFF,
                CUTOFF,
                tuple(item.source_record_id for item in normalized.source_records),
                "1",
                "a" * 64,
            ),
        )
    linked = replace(
        snapshot,
        dataset_version=DatasetVersionReference("trades", "v1"),
    )
    dataset = DatasetVersion(
        "trades",
        "v1",
        CUTOFF,
        T0,
        CUTOFF,
        CUTOFF,
        tuple(item.source_record_id for item in normalized.source_records),
        "1",
        "b" * 64,
    )
    assert (
        assess_normalized_spot_trades(
            linked,
            normalized,
            trade_policy(),
            assessed_at=CUTOFF,
            dataset=dataset,
        ).status
        is DataQualityStatus.VALID
    )
    with pytest.raises(DataQualityAssessmentError, match="Dataset"):
        assess_normalized_spot_trades(
            linked,
            normalized,
            trade_policy(),
            assessed_at=CUTOFF,
            dataset=replace(dataset, version="wrong"),
        )
    with pytest.raises(DataQualityAssessmentError, match="Dataset"):
        assess_normalized_spot_trades(
            linked,
            normalized,
            trade_policy(),
            assessed_at=CUTOFF,
            dataset=replace(dataset, source_record_ids=dataset.source_record_ids[:1]),
        )


def test_trade_tick_out_of_order_and_gapped_sequence_do_not_receive_a_score() -> None:
    normalized, snapshot = trade_batch()
    reversed_batch = replace(
        normalized,
        market_data=normalized.market_data[::-1],
        source_records=normalized.source_records[::-1],
        identities=normalized.identities[::-1],
    )
    reversed_snapshot = replace(
        snapshot,
        market_data_ids=snapshot.market_data_ids[::-1],
        source_record_ids=snapshot.source_record_ids[::-1],
    )
    with pytest.raises(DataQualityAssessmentError, match="sequence"):
        assess_normalized_spot_trades(
            reversed_snapshot, reversed_batch, trade_policy(), assessed_at=CUTOFF
        )
    gapped = replace(
        normalized,
        identities=(
            normalized.identities[0],
            replace(normalized.identities[1], sequence=normalized.identities[1].sequence + 1),
        ),
    )
    with pytest.raises(DataQualityAssessmentError, match="sequence"):
        assess_normalized_spot_trades(
            snapshot, gapped, trade_policy(), assessed_at=CUTOFF
        )
    wrong_scope = replace(
        normalized,
        identities=(
            normalized.identities[0],
            replace(normalized.identities[1], sequence_scope="other-stream"),
        ),
    )
    with pytest.raises(DataQualityAssessmentError, match="sequence"):
        assess_normalized_spot_trades(
            snapshot, wrong_scope, trade_policy(), assessed_at=CUTOFF
        )
    unsequenced, snapshot = trade_batch(sequenced=False)
    reversed_batch = replace(
        unsequenced,
        market_data=unsequenced.market_data[::-1],
        source_records=unsequenced.source_records[::-1],
        identities=unsequenced.identities[::-1],
    )
    reversed_snapshot = replace(
        snapshot,
        market_data_ids=snapshot.market_data_ids[::-1],
        source_record_ids=snapshot.source_record_ids[::-1],
    )
    with pytest.raises(DataQualityAssessmentError, match="identity or cutoff"):
        assess_normalized_spot_trades(
            reversed_snapshot, reversed_batch, trade_policy(), assessed_at=CUTOFF
        )

    future_events = tuple(
        trade_event(
            f"future-{index}",
            when=CUTOFF + timedelta(seconds=index + 1),
            sequence=index + 1,
            sequence_scope="trade-stream",
            reported_side=ReportedSide.BUY,
            side_semantics=SideSemantics.AGGRESSOR,
        )
        for index in range(2)
    )
    future = normalize_trade_ticks(
        future_events,
        trade_normalization_policy(maximum_records=2),
    )
    future_snapshot = MarketSnapshot(
        uuid4(),
        CUTOFF,
        CUTOFF,
        "synthetic-instrument",
        "synthetic-venue",
        tuple(item.market_data_id for item in future.market_data),
        tuple(item.source_record_id for item in future.source_records),
    )
    with pytest.raises(DataQualityAssessmentError, match="cutoff"):
        assess_normalized_spot_trades(
            future_snapshot, future, trade_policy(), assessed_at=CUTOFF
        )


def test_order_book_point_snapshot_marks_only_continuity_not_applicable() -> None:
    transition = initial_book()
    snapshot = snapshot_for_books((transition,))
    report = assess_normalized_spot_order_book(
        snapshot,
        (transition,),
        book_quality_policy(),
        assessed_at=BOOK_T0 + timedelta(seconds=10),
    )
    continuity = report.dimensions[-1]
    assert report.status is DataQualityStatus.VALID
    assert continuity.state is DataQualityDimensionState.NOT_APPLICABLE
    assert continuity.reason_code is DataQualityDimensionReasonCode.SINGLE_POINT_SNAPSHOT
    assert continuity.not_applicable_policy == AssessmentPolicyReference(
        "spot-order-book-point", "1"
    )
    assert continuity.score is continuity.numerator is continuity.denominator is None
    assert transition.quality.checksum is ChecksumStatus.NOT_AVAILABLE


def test_order_book_delta_continuity_is_measured_only_for_verified_window() -> None:
    initial = initial_book()
    delta = apply_book_delta(
        initial.state,
        book_delta(),
        BOOK_POLICY,
        as_of=BOOK_T0 + timedelta(seconds=7),
        sequence_verifier=contiguous,
    )
    snapshot = snapshot_for_books((initial, delta))
    report = assess_normalized_spot_order_book(
        snapshot,
        (initial, delta),
        book_quality_policy(point=False),
        assessed_at=BOOK_T0 + timedelta(seconds=10),
    )
    assert report.status is DataQualityStatus.VALID
    assert report.dimensions[-1].state is DataQualityDimensionState.MEASURED
    assert report.dimensions[-1].numerator == report.dimensions[-1].denominator == 1
    assert report.dimensions[-1].basis_unit == "sequence_transitions"

    missing_delta_snapshot = snapshot_for_books((initial,))
    missing_delta = assess_normalized_spot_order_book(
        missing_delta_snapshot,
        (initial,),
        book_quality_policy(point=False),
        assessed_at=BOOK_T0 + timedelta(seconds=10),
    )
    assert missing_delta.status is DataQualityStatus.UNAVAILABLE
    assert (
        missing_delta.dimensions[-1].reason_code
        is DataQualityDimensionReasonCode.SEQUENCE_UNVERIFIED
    )


def test_order_book_duplicate_failed_state_checksum_and_staleness_findings() -> None:
    initial = initial_book()
    first_delta = apply_book_delta(
        initial.state,
        book_delta(),
        BOOK_POLICY,
        as_of=BOOK_T0 + timedelta(seconds=7),
        sequence_verifier=contiguous,
    )
    duplicate = apply_book_delta(
        first_delta.state,
        book_delta(),
        BOOK_POLICY,
        as_of=BOOK_T0 + timedelta(seconds=7),
        sequence_verifier=contiguous,
    )
    duplicate_snapshot = snapshot_for_books((initial, first_delta))
    assert (
        assess_normalized_spot_order_book(
            duplicate_snapshot,
            (initial, first_delta, duplicate),
            book_quality_policy(point=False),
            assessed_at=BOOK_T0 + timedelta(seconds=10),
        ).status
        is DataQualityStatus.INVALID
    )

    failed = apply_book_delta(
        initial.state,
        book_delta(sequence_start=12, sequence_end=12),
        BOOK_POLICY,
        as_of=BOOK_T0 + timedelta(seconds=7),
        sequence_verifier=contiguous,
    )
    failed_report = assess_normalized_spot_order_book(
        snapshot_for_books((initial,)),
        (initial, failed),
        book_quality_policy(point=False),
        assessed_at=BOOK_T0 + timedelta(seconds=10),
    )
    assert failed.state.failure is BookFailure.SEQUENCE
    assert failed_report.status is DataQualityStatus.INVALID
    assert failed_report.anomalies == ("book-failure:SEQUENCE",)

    for changes, expected_failure in (
        (
            (LevelChange(BookSide.BID, Decimal("101.00"), Decimal("1.000")),),
            BookFailure.CROSSED,
        ),
        (
            (LevelChange(BookSide.BID, Decimal("102.00"), Decimal("1.000")),),
            BookFailure.CROSSED,
        ),
        (
            (
                LevelChange(BookSide.ASK, Decimal("101.00"), Decimal("0.000")),
                LevelChange(BookSide.ASK, Decimal("102.00"), Decimal("0.000")),
            ),
            BookFailure.DEPTH,
        ),
    ):
        bad_transition = apply_book_delta(
            initial.state,
            book_delta(changes=changes),
            BOOK_POLICY,
            as_of=BOOK_T0 + timedelta(seconds=7),
            sequence_verifier=contiguous,
        )
        assert bad_transition.state.failure is expected_failure
        invalid_report = assess_normalized_spot_order_book(
            snapshot_for_books((initial,)),
            (initial, bad_transition),
            book_quality_policy(point=False),
            assessed_at=BOOK_T0 + timedelta(seconds=10),
        )
        assert invalid_report.status is DataQualityStatus.INVALID
        assert f"book-failure:{expected_failure.value}" in invalid_report.anomalies

    stale_policy = book_quality_policy(freshness=2)
    stale = assess_normalized_spot_order_book(
        snapshot_for_books((initial,)),
        (initial,),
        stale_policy,
        assessed_at=BOOK_T0 + timedelta(seconds=10),
    )
    assert stale.status is DataQualityStatus.STALE


def test_order_book_rejects_unbound_failure_and_source_lineage() -> None:
    initial = initial_book()
    bad_observation = replace(
        initial.market_data,
        source_record_id=uuid4(),
    )
    bad_transition = replace(initial, market_data=bad_observation)
    with pytest.raises(DataQualityAssessmentError, match="lineage"):
        assess_normalized_spot_order_book(
            snapshot_for_books((initial,)),
            (bad_transition,),
            book_quality_policy(),
            assessed_at=BOOK_T0 + timedelta(seconds=10),
        )


def test_order_book_mismatched_declared_checksum_is_invalid() -> None:
    checked = normalize_book_snapshot(
        raw_book_snapshot(checksum="synthetic-checksum"),
        BOOK_POLICY,
        as_of=BOOK_T0 + timedelta(seconds=3),
        checksum_verifier=lambda bids, asks, checksum: True,
    )
    failed = apply_book_delta(
        checked.state,
        book_delta(checksum="different-checksum"),
        BOOK_POLICY,
        as_of=BOOK_T0 + timedelta(seconds=7),
        sequence_verifier=contiguous,
        checksum_verifier=lambda bids, asks, checksum: False,
    )
    assert failed.state.failure is BookFailure.CHECKSUM
    report = assess_normalized_spot_order_book(
        snapshot_for_books((checked,)),
        (checked, failed),
        book_quality_policy(point=False),
        assessed_at=BOOK_T0 + timedelta(seconds=10),
    )
    assert report.status is DataQualityStatus.INVALID
    assert report.anomalies == ("book-failure:CHECKSUM",)


def test_order_book_checksum_required_policy_and_verification_boundary() -> None:
    normalized_policy = BOOK_POLICY
    verified = normalize_book_snapshot(
        raw_book_snapshot(checksum="synthetic-checksum"),
        normalized_policy,
        as_of=BOOK_T0 + timedelta(seconds=3),
        checksum_verifier=lambda bids, asks, checksum: checksum == "synthetic-checksum",
    )
    report = assess_normalized_spot_order_book(
        snapshot_for_books((verified,)),
        (verified,),
        book_quality_policy(policy_id="spot-order-book-point-checksum"),
        assessed_at=BOOK_T0 + timedelta(seconds=10),
    )
    assert verified.quality.checksum is ChecksumStatus.VERIFIED
    assert report.status is DataQualityStatus.VALID

    missing_checksum = initial_book()
    unavailable = assess_normalized_spot_order_book(
        snapshot_for_books((missing_checksum,)),
        (missing_checksum,),
        book_quality_policy(policy_id="spot-order-book-point-checksum"),
        assessed_at=BOOK_T0 + timedelta(seconds=10),
    )
    assert unavailable.status is DataQualityStatus.UNAVAILABLE
    assert (
        unavailable.dimensions[2].reason_code
        is DataQualityDimensionReasonCode.MISSING_REQUIRED_EVIDENCE
    )

    with pytest.raises(OrderBookError, match="verifier"):
        normalize_book_snapshot(
            raw_book_snapshot(checksum="synthetic-checksum"),
            normalized_policy,
            as_of=BOOK_T0 + timedelta(seconds=3),
        )
