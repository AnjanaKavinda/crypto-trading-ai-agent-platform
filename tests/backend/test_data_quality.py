"""Deterministic, synthetic tests of C-003 verdicts and fail-closed inputs."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from trading_platform_api.market_data import (
    BookDelta,
    BookFailure,
    BookLevel,
    BookPolicy,
    BookSide,
    BookSnapshot,
    BookSource,
    BookStatus,
    ChecksumStatus,
    DataQualityAssessmentError,
    DataQualityPolicy,
    DataQualityStatus,
    DatasetVersion,
    DatasetVersionReference,
    DataSourceRecord,
    LevelChange,
    MarketData,
    MarketSnapshot,
    MetricBound,
    MetricValue,
    NormalizedTradeTicks,
    ProviderBatch,
    ProviderBatchStatus,
    ProviderDataKind,
    RawTradeTick,
    ReportedSide,
    SideSemantics,
    TradeTickPolicy,
    apply_book_delta,
    assess_complete_binance_spot_batch,
    assess_data_quality,
    normalize_book_snapshot,
    normalize_trade_ticks,
)

START = datetime(2026, 1, 1, tzinfo=UTC)
STEP = timedelta(minutes=1)
CUTOFF = START + 3 * STEP
NAMES = ("open", "high", "low", "close", "volume")


def policy(**changes: object) -> DataQualityPolicy:
    fields: dict[str, object] = dict(
        policy_version="synthetic-policy-v1",
        data_kind=ProviderDataKind.OHLCV,
        instrument_id="BTCUSDT-SPOT",
        venue_id="synthetic-venue",
        required_data_cutoff=CUTOFF,
        coverage_start=START,
        coverage_end=CUTOFF,
        interval_seconds=60,
        freshness_seconds=60,
        maximum_missing_intervals=0,
        required_metrics=NAMES,
        metric_bounds=tuple(
            MetricBound(name, Decimal("0"), Decimal("1000")) for name in NAMES
        ),
    )
    fields.update(changes)
    return DataQualityPolicy(**fields)  # type: ignore[arg-type]


def evidence(
    indices: tuple[int, ...] = (0, 1, 2),
) -> tuple[MarketSnapshot, tuple[MarketData, ...], tuple[DataSourceRecord, ...], tuple]:
    observations: list[MarketData] = []
    sources: list[DataSourceRecord] = []
    for index in indices:
        opened = START + index * STEP
        closed = opened + STEP
        source_id = uuid4()
        source = DataSourceRecord(
            source_id,
            "synthetic",
            "1",
            opened,
            closed,
            closed,
            "raw-v1",
            "adapter-v1",
            "synthetic",
            "a" * 64,
        )
        data = MarketData(
            uuid4(),
            "BTCUSDT-SPOT",
            "synthetic-venue",
            "OHLCV",
            opened,
            opened,
            closed,
            closed,
            source_id,
            (
                MetricValue("open", Decimal("10"), "USDT"),
                MetricValue("high", Decimal("12"), "USDT"),
                MetricValue("low", Decimal("9"), "USDT"),
                MetricValue("close", Decimal("11"), "USDT"),
                MetricValue("volume", Decimal("5"), "BTC"),
            ),
        )
        sources.append(source)
        observations.append(data)
    snapshot = MarketSnapshot(
        uuid4(),
        CUTOFF,
        CUTOFF,
        "BTCUSDT-SPOT",
        "synthetic-venue",
        tuple(item.market_data_id for item in observations),
        tuple(item.source_record_id for item in sources),
    )
    finality = tuple(item.market_data_id for item in observations)
    return snapshot, tuple(observations), tuple(sources), finality


def assess(data: tuple | None = None, policy_override: DataQualityPolicy | None = None):
    snapshot, observations, sources, finality = data or evidence()
    return assess_data_quality(
        snapshot,
        observations,
        sources,
        policy_override or policy(),
        assessed_at=CUTOFF,
        finalized_market_data_ids=finality,
    )


def normalized_events(
    *,
    kind: ProviderDataKind = ProviderDataKind.TRADE,
    sequences: tuple[int | None, ...] = (5, 6),
    side_semantics: SideSemantics = SideSemantics.AGGRESSOR,
) -> tuple[NormalizedTradeTicks, MarketSnapshot, DataQualityPolicy]:
    event_times = (CUTOFF - timedelta(seconds=20), CUTOFF - timedelta(seconds=10))
    raw = tuple(
        RawTradeTick(
            source_record_id=uuid4(),
            market_data_id=uuid4(),
            provider_event_id=f"event-{index}",
            instrument_id="BTCUSDT-SPOT",
            venue_id="synthetic-venue",
            data_kind=kind,
            event_time=event_time,
            price=Decimal("100"),
            quantity=Decimal("1") if kind is ProviderDataKind.TRADE else None,
            price_unit="USDT",
            quantity_unit="BTC",
            reported_side=ReportedSide.BUY,
            side_semantics=side_semantics,
            sequence=sequences[index],
            sequence_scope="spot-stream" if sequences[index] is not None else None,
            raw_source_bytes=f"event-{index}".encode(),
            provider_id="synthetic-provider",
            provider_version="fixture-v1",
            raw_schema_version="fixture-schema-v1",
            adapter_version="fixture-adapter-v1",
            licensing_reference="synthetic-fixture",
            retrieval_time=event_time + timedelta(seconds=1),
            ingestion_time=event_time + timedelta(seconds=2),
            availability_time=event_time + timedelta(seconds=3),
        )
        for index, event_time in enumerate(event_times)
    )
    trade_policy = TradeTickPolicy(
        instrument_id="BTCUSDT-SPOT",
        venue_id="synthetic-venue",
        data_kind=kind,
        price_unit="USDT",
        quantity_unit="BTC",
        price_places=2,
        quantity_places=2,
    )
    normalized = normalize_trade_ticks(raw, trade_policy)
    snapshot = MarketSnapshot(
        uuid4(),
        CUTOFF,
        CUTOFF,
        "BTCUSDT-SPOT",
        "synthetic-venue",
        tuple(item.market_data_id for item in normalized.market_data),
        tuple(item.source_record_id for item in normalized.source_records),
    )
    metrics = ("price", "quantity") if kind is ProviderDataKind.TRADE else ("price",)
    bounds = tuple(
        MetricBound(
            name,
            Decimal("0"),
            Decimal("1000"),
            "USDT" if name == "price" else "BTC",
        )
        for name in metrics
    )
    quality_policy = DataQualityPolicy(
        policy_version="synthetic-event-quality-v1",
        data_kind=kind,
        instrument_id="BTCUSDT-SPOT",
        venue_id="synthetic-venue",
        required_data_cutoff=CUTOFF,
        coverage_start=CUTOFF - timedelta(seconds=30),
        coverage_end=CUTOFF,
        interval_seconds=None,
        freshness_seconds=60,
        maximum_missing_intervals=None,
        required_metrics=metrics,
        metric_bounds=bounds,
        expected_record_count=2,
        provider_identity=(
            "synthetic-provider",
            "fixture-v1",
            "fixture-schema-v1",
            "fixture-adapter-v1",
            "synthetic-fixture",
        ),
        expected_sequence_start=(
            sequences[0] if all(value is not None for value in sequences) else None
        ),
        expected_sequence_end=(
            sequences[-1] if all(value is not None for value in sequences) else None
        ),
    )
    return normalized, snapshot, quality_policy


def book_evidence(
    *,
    checksum: bool = False,
) -> tuple[tuple, MarketSnapshot, DataQualityPolicy]:
    book_policy = BookPolicy(
        instrument_id="BTCUSDT-SPOT",
        venue_id="synthetic-venue",
        price_unit="USDT",
        quantity_unit="BTC",
        price_places=2,
        quantity_places=2,
        maximum_depth=2,
        maximum_age_seconds=60,
        maximum_lineage=5,
        extreme_spread_bps=Decimal("1000"),
    )
    verifier = (lambda bids, asks, value: True) if checksum else None

    def source(event_id: str, seconds_ago: int) -> BookSource:
        event_time = CUTOFF - timedelta(seconds=seconds_ago)
        return BookSource(
            source_record_id=uuid4(),
            market_data_id=uuid4(),
            event_id=event_id,
            instrument_id="BTCUSDT-SPOT",
            venue_id="synthetic-venue",
            provider_id="synthetic-provider",
            provider_version="fixture-v1",
            raw_schema_version="fixture-schema-v1",
            adapter_version="fixture-adapter-v1",
            licensing_reference="synthetic-fixture",
            event_time=event_time,
            retrieval_time=event_time + timedelta(seconds=1),
            ingestion_time=event_time + timedelta(seconds=2),
            availability_time=event_time + timedelta(seconds=3),
            raw_source_bytes=event_id.encode(),
        )

    initial_source = source("book-snapshot", 20)
    initial = normalize_book_snapshot(
        BookSnapshot(
            initial_source,
            (
                BookLevel(Decimal("99"), Decimal("2")),
                BookLevel(Decimal("98"), Decimal("1")),
            ),
            (
                BookLevel(Decimal("101"), Decimal("2")),
                BookLevel(Decimal("102"), Decimal("1")),
            ),
            10,
            "snapshot-checksum" if checksum else None,
        ),
        book_policy,
        as_of=CUTOFF,
        checksum_verifier=verifier,
    )
    delta_source = source("book-delta", 10)
    delta = apply_book_delta(
        initial.state,
        BookDelta(
            delta_source,
            (LevelChange(BookSide.BID, Decimal("99"), Decimal("1.5")),),
            11,
            11,
            "delta-checksum" if checksum else None,
        ),
        book_policy,
        as_of=CUTOFF,
        sequence_verifier=lambda previous, start, end: (
            start == previous + 1 and end == start
        ),
        checksum_verifier=verifier,
    )
    transitions = (initial, delta)
    observations = tuple(item.market_data for item in transitions)
    sources = tuple(item.source_record for item in transitions)
    assert all(item is not None for item in observations + sources)
    data = tuple(item for item in observations if item is not None)
    source_records = tuple(item for item in sources if item is not None)
    snapshot = MarketSnapshot(
        uuid4(),
        CUTOFF,
        CUTOFF,
        "BTCUSDT-SPOT",
        "synthetic-venue",
        tuple(item.market_data_id for item in data),
        tuple(item.source_record_id for item in source_records),
    )
    metric_names = tuple(metric.metric_name for metric in data[-1].metrics)
    quality_policy = DataQualityPolicy(
        policy_version="synthetic-book-quality-v1",
        data_kind=ProviderDataKind.ORDER_BOOK,
        instrument_id="BTCUSDT-SPOT",
        venue_id="synthetic-venue",
        required_data_cutoff=CUTOFF,
        coverage_start=CUTOFF - timedelta(seconds=30),
        coverage_end=CUTOFF,
        interval_seconds=None,
        freshness_seconds=60,
        maximum_missing_intervals=None,
        required_metrics=metric_names,
        metric_bounds=tuple(
            MetricBound(
                name,
                Decimal("0"),
                Decimal("1000"),
                "USDT" if name.endswith("_price") else "BTC",
            )
            for name in metric_names
        ),
        expected_record_count=2,
        provider_identity=(
            "synthetic-provider",
            "fixture-v1",
            "fixture-schema-v1",
            "fixture-adapter-v1",
            "synthetic-fixture",
        ),
        expected_sequence_start=10,
        expected_sequence_end=11,
    )
    return transitions, snapshot, quality_policy


def test_complete_single_source_is_valid_without_claiming_cross_source_agreement() -> (
    None
):
    report = assess()
    assert report.contract_id == "C-003"
    assert report.status is DataQualityStatus.VALID
    assert (
        report.completeness,
        report.freshness,
        report.accuracy,
        report.consistency,
        report.source_reliability,
        report.coverage,
        report.continuity,
    ) == (Decimal("1"),) * 7


def test_comparator_and_finality_are_required_evidence_not_zero_scores() -> None:
    with pytest.raises(DataQualityAssessmentError, match="Independent"):
        assess(policy_override=policy(require_independent_comparison=True))
    snapshot, observations, sources, _ = evidence()
    with pytest.raises(DataQualityAssessmentError, match="finality"):
        assess_data_quality(
            snapshot,
            observations,
            sources,
            policy(),
            assessed_at=CUTOFF,
            finalized_market_data_ids=None,
        )


def test_gap_and_latest_missing_have_distinct_status_and_measured_ratios() -> None:
    gap = assess(evidence((0, 2)))
    assert gap.status is DataQualityStatus.INCOMPLETE
    assert gap.coverage == Decimal(2) / 3
    assert gap.continuity == Decimal("0")
    allowed = assess(evidence((0, 2)), policy(maximum_missing_intervals=1))
    assert allowed.status is DataQualityStatus.DEGRADED
    stale = assess(evidence((0, 1)))
    assert stale.status is DataQualityStatus.STALE
    assert stale.freshness == Decimal("0")


def test_missing_source_is_unavailable_and_conflict_is_invalid() -> None:
    snapshot, observations, sources, finality = evidence()
    missing = assess((snapshot, observations, sources[:-1], finality))
    assert missing.status is DataQualityStatus.UNAVAILABLE
    assert missing.source_reliability == Decimal(2) / 3
    wrong = replace(observations[0], instrument_id="ETHUSDT-SPOT")
    invalid = assess((snapshot, (wrong,) + observations[1:], sources, finality))
    assert invalid.status is DataQualityStatus.INVALID
    assert str(wrong.market_data_id) in invalid.invalid_record_ids


def test_provisional_duplicate_out_of_order_and_bound_failure_are_invalid() -> None:
    snapshot, observations, sources, finality = evidence()
    assert (
        assess((snapshot, observations, sources, finality[:-1])).status
        is DataQualityStatus.INVALID
    )
    assert (
        assess((snapshot, observations[::-1], sources, finality)).status
        is DataQualityStatus.INVALID
    )
    duplicate = assess((snapshot, observations + (observations[0],), sources, finality))
    assert duplicate.status is DataQualityStatus.INVALID
    assert duplicate.duplicate_record_ids
    high = replace(
        observations[0],
        metrics=tuple(
            MetricValue(
                m.metric_name,
                Decimal("1001") if m.metric_name == "high" else m.value,
                m.unit,
            )
            for m in observations[0].metrics
        ),
    )
    assert (
        assess((snapshot, (high,) + observations[1:], sources, finality)).status
        is DataQualityStatus.INVALID
    )


def test_missing_metric_and_early_candle_retrieval_cannot_be_valid() -> None:
    snapshot, observations, sources, finality = evidence()
    missing = replace(
        observations[0],
        metrics=tuple(m for m in observations[0].metrics if m.metric_name != "volume"),
    )
    report = assess((snapshot, (missing,) + observations[1:], sources, finality))
    assert report.status is DataQualityStatus.INVALID
    assert report.completeness == Decimal(14) / 15
    assert any("volume" in field for field in report.missing_fields)
    early = replace(sources[0], retrieval_time=START + timedelta(seconds=30))
    report = assess((snapshot, observations, (early,) + sources[1:], finality))
    assert report.status is DataQualityStatus.INVALID


def test_inconsistent_price_units_and_foreign_finality_are_invalid() -> None:
    snapshot, observations, sources, finality = evidence()
    wrong_unit = replace(
        observations[0],
        metrics=tuple(
            MetricValue(
                m.metric_name, m.value, "USD" if m.metric_name == "high" else m.unit
            )
            for m in observations[0].metrics
        ),
    )
    assert (
        assess((snapshot, (wrong_unit,) + observations[1:], sources, finality)).accuracy
        == Decimal(2) / 3
    )
    report = assess((snapshot, observations, sources, finality + (uuid4(),)))
    assert report.status is DataQualityStatus.INVALID
    second = replace(
        observations[1],
        metrics=tuple(
            MetricValue(
                m.metric_name, m.value, "ETH" if m.metric_name == "volume" else m.unit
            )
            for m in observations[1].metrics
        ),
    )
    assert (
        assess(
            (snapshot, (observations[0], second, observations[2]), sources, finality)
        ).status
        is DataQualityStatus.INVALID
    )


def test_mixed_provider_cannot_claim_unmeasured_agreement() -> None:
    snapshot, observations, sources, finality = evidence()
    with pytest.raises(DataQualityAssessmentError, match="Mixed providers"):
        assess(
            (
                snapshot,
                observations,
                (sources[0], replace(sources[1], provider_id="other"), sources[2]),
                finality,
            )
        )


def test_cutoff_empty_denominator_and_invalid_policy_fail_closed() -> None:
    snapshot, observations, sources, finality = evidence()
    with pytest.raises(DataQualityAssessmentError):
        assess((snapshot, (), sources, ()))
    with pytest.raises(DataQualityAssessmentError, match="cutoff"):
        assess_data_quality(
            snapshot,
            observations,
            sources,
            policy(),
            assessed_at=START,
            finalized_market_data_ids=finality,
        )
    with pytest.raises(DataQualityAssessmentError):
        policy(metric_bounds=(MetricBound("close", Decimal("0"), Decimal("1")),))


def test_dataset_identity_and_lineage_must_match_snapshot() -> None:
    snapshot, observations, sources, finality = evidence()
    dataset = DatasetVersion(
        "synthetic-data",
        "v1",
        CUTOFF,
        START,
        CUTOFF,
        CUTOFF,
        tuple(s.source_record_id for s in sources),
        "1",
        "b" * 64,
    )
    linked = replace(
        snapshot,
        dataset_version=DatasetVersionReference("synthetic-data", "v1"),
    )
    report = assess_data_quality(
        linked,
        observations,
        sources,
        policy(),
        assessed_at=CUTOFF,
        finalized_market_data_ids=finality,
        dataset=dataset,
    )
    assert report.status is DataQualityStatus.VALID
    with pytest.raises(DataQualityAssessmentError, match="Dataset"):
        assess_data_quality(
            linked,
            observations,
            sources,
            policy(),
            assessed_at=CUTOFF,
            finalized_market_data_ids=finality,
            dataset=replace(dataset, version="different"),
        )
    bad_lineage = replace(dataset, source_record_ids=dataset.source_record_ids[:-1])
    result = assess_data_quality(
        linked,
        observations,
        sources,
        policy(),
        assessed_at=CUTOFF,
        finalized_market_data_ids=finality,
        dataset=bad_lineage,
    )
    assert result.status is DataQualityStatus.INVALID


def test_known_complete_spot_batch_can_supply_finality_without_a_contract_change() -> (
    None
):
    snapshot, observations, sources, _ = evidence()
    known_sources = tuple(
        replace(
            s,
            provider_id="binance-spot-public",
            provider_version="spot-api-2026-09",
            adapter_version="binance-spot-adapter-v1",
        )
        for s in sources
    )
    batch = ProviderBatch(
        uuid4(),
        "binance-spot-public",
        "spot-api-2026-09",
        ProviderDataKind.OHLCV,
        ProviderBatchStatus.COMPLETE,
        CUTOFF,
        CUTOFF + timedelta(seconds=30),
        known_sources,
        observations,
        (snapshot,),
    )
    assert (
        assess_complete_binance_spot_batch(batch, policy(), assessed_at=CUTOFF).status
        is DataQualityStatus.VALID
    )
    with pytest.raises(DataQualityAssessmentError, match="Complete trusted"):
        assess_complete_binance_spot_batch(
            replace(
                batch,
                status=ProviderBatchStatus.PARTIAL,
                warnings=("Provisional candle present.",),
            ),
            policy(),
            assessed_at=CUTOFF,
        )
    with pytest.raises(DataQualityAssessmentError, match="Complete trusted"):
        assess_complete_binance_spot_batch(
            replace(
                batch,
                source_records=tuple(
                    replace(s, adapter_version="v2") for s in known_sources
                ),
            ),
            policy(),
            assessed_at=CUTOFF,
        )


@pytest.mark.parametrize(
    ("kind", "sequences"),
    [
        (ProviderDataKind.TRADE, (5, 6)),
        (ProviderDataKind.TICK, (5, 6)),
    ],
)
def test_event_quality_uses_exact_handoff_and_measured_sequence_coverage(
    kind: ProviderDataKind, sequences: tuple[int, ...]
) -> None:
    normalized, snapshot, quality_policy = normalized_events(
        kind=kind, sequences=sequences
    )
    report = assess_data_quality(
        snapshot,
        normalized.market_data,
        normalized.source_records,
        quality_policy,
        assessed_at=CUTOFF,
        trade_ticks=normalized,
    )
    assert report.snapshot_id == snapshot.snapshot_id
    assert report.status is DataQualityStatus.VALID
    assert (
        report.completeness,
        report.freshness,
        report.accuracy,
        report.consistency,
        report.source_reliability,
        report.coverage,
        report.continuity,
    ) == (Decimal("1"),) * 7


def test_unverified_sequence_and_unknown_aggressor_degrade_without_inventing_side() -> (
    None
):
    normalized, snapshot, quality_policy = normalized_events(
        sequences=(None, None),
        side_semantics=SideSemantics.UNKNOWN,
    )
    report = assess_data_quality(
        snapshot,
        normalized.market_data,
        normalized.source_records,
        quality_policy,
        assessed_at=CUTOFF,
        trade_ticks=normalized,
    )
    assert report.status is DataQualityStatus.DEGRADED
    assert report.continuity == Decimal("0")
    assert "sequence-unverified" in report.anomalies
    assert any(item.startswith("unknown-aggressor:") for item in report.anomalies)
    assert all(
        metric.metric_name != "aggressor_sign"
        for item in normalized.market_data
        for metric in item.metrics
    )


def test_event_empty_duplicate_missing_coverage_and_comparator_fail_closed() -> None:
    normalized, snapshot, quality_policy = normalized_events()
    with pytest.raises(DataQualityAssessmentError, match="exact assessed"):
        assess_data_quality(
            snapshot,
            normalized.market_data[:-1],
            normalized.source_records[:-1],
            quality_policy,
            assessed_at=CUTOFF,
            trade_ticks=replace(
                normalized,
                market_data=normalized.market_data[:-1],
                source_records=normalized.source_records[:-1],
                identities=normalized.identities[:-1],
            ),
        )
    with pytest.raises(DataQualityAssessmentError, match="Empty"):
        empty = replace(normalized, quality=replace(normalized.quality, empty=True))
        assess_data_quality(
            snapshot,
            normalized.market_data,
            normalized.source_records,
            quality_policy,
            assessed_at=CUTOFF,
            trade_ticks=empty,
        )
    duplicate_handoff = replace(
        normalized,
        quality=replace(normalized.quality, duplicate_event_ids=("event-0",)),
    )
    duplicate_report = assess_data_quality(
        snapshot,
        normalized.market_data,
        normalized.source_records,
        quality_policy,
        assessed_at=CUTOFF,
        trade_ticks=duplicate_handoff,
    )
    assert duplicate_report.status is DataQualityStatus.INVALID
    assert duplicate_report.duplicate_record_ids == ("event-0",)
    partial_policy = replace(
        quality_policy,
        expected_record_count=3,
        expected_sequence_start=None,
        expected_sequence_end=None,
    )
    incomplete = assess_data_quality(
        snapshot,
        normalized.market_data,
        normalized.source_records,
        partial_policy,
        assessed_at=CUTOFF,
        trade_ticks=normalized,
    )
    assert incomplete.status is DataQualityStatus.INCOMPLETE
    assert incomplete.coverage == Decimal(2) / 3
    with pytest.raises(DataQualityAssessmentError, match="Independent"):
        assess_data_quality(
            snapshot,
            normalized.market_data,
            normalized.source_records,
            replace(quality_policy, require_independent_comparison=True),
            assessed_at=CUTOFF,
            trade_ticks=normalized,
        )


def test_event_cutoff_freshness_units_and_snapshot_membership_are_checked() -> None:
    normalized, snapshot, quality_policy = normalized_events()
    stale = assess_data_quality(
        snapshot,
        normalized.market_data,
        normalized.source_records,
        replace(quality_policy, freshness_seconds=1),
        assessed_at=CUTOFF,
        trade_ticks=normalized,
    )
    assert stale.status is DataQualityStatus.STALE
    assert stale.freshness == Decimal("0")
    data = normalized.market_data[0]
    wrong_unit = replace(
        data,
        metrics=(replace(data.metrics[0], unit="OTHER"),) + data.metrics[1:],
    )
    wrong_handoff = replace(
        normalized, market_data=(wrong_unit,) + normalized.market_data[1:]
    )
    invalid = assess_data_quality(
        snapshot,
        wrong_handoff.market_data,
        wrong_handoff.source_records,
        quality_policy,
        assessed_at=CUTOFF,
        trade_ticks=wrong_handoff,
    )
    assert invalid.status is DataQualityStatus.INVALID
    with pytest.raises(DataQualityAssessmentError, match="exact assessed"):
        assess_data_quality(
            replace(
                snapshot, market_data_ids=(uuid4(),) + snapshot.market_data_ids[1:]
            ),
            normalized.market_data,
            normalized.source_records,
            quality_policy,
            assessed_at=CUTOFF,
            trade_ticks=normalized,
        )


def test_event_policy_requires_completeness_evidence_and_rejects_sequence_gaps() -> (
    None
):
    normalized, snapshot, quality_policy = normalized_events()
    with pytest.raises(DataQualityAssessmentError, match="Expected record count"):
        replace(
            quality_policy,
            expected_record_count=None,
            provider_complete=False,
        )
    gapped = replace(
        normalized,
        identities=(
            normalized.identities[0],
            replace(normalized.identities[1], sequence=8),
        ),
    )
    report = assess_data_quality(
        snapshot,
        gapped.market_data,
        gapped.source_records,
        quality_policy,
        assessed_at=CUTOFF,
        trade_ticks=gapped,
    )
    assert report.status is DataQualityStatus.INVALID
    assert "sequence-gap-or-verification-mismatch" in report.invalid_record_ids
    stale_snapshot = replace(
        snapshot,
        as_of=CUTOFF - timedelta(seconds=1),
    )
    with pytest.raises(DataQualityAssessmentError, match="cutoff mismatch"):
        assess_data_quality(
            stale_snapshot,
            normalized.market_data,
            normalized.source_records,
            quality_policy,
            assessed_at=CUTOFF,
            trade_ticks=normalized,
        )


def test_event_assessment_is_repeatable_except_report_identity() -> None:
    normalized, snapshot, quality_policy = normalized_events()

    def result():
        return assess_data_quality(
            snapshot,
            normalized.market_data,
            normalized.source_records,
            quality_policy,
            assessed_at=CUTOFF,
            trade_ticks=normalized,
        )

    first, second = result(), result()
    assert first.report_id != second.report_id
    assert (
        first.snapshot_id,
        first.assessed_at,
        first.required_data_cutoff,
        first.completeness,
        first.freshness,
        first.accuracy,
        first.consistency,
        first.source_reliability,
        first.coverage,
        first.continuity,
        first.status,
        first.missing_fields,
        first.invalid_record_ids,
        first.duplicate_record_ids,
        first.anomalies,
    ) == (
        second.snapshot_id,
        second.assessed_at,
        second.required_data_cutoff,
        second.completeness,
        second.freshness,
        second.accuracy,
        second.consistency,
        second.source_reliability,
        second.coverage,
        second.continuity,
        second.status,
        second.missing_fields,
        second.invalid_record_ids,
        second.duplicate_record_ids,
        second.anomalies,
    )


def test_single_verified_event_has_vacuously_complete_sequence_continuity() -> None:
    normalized, _, quality_policy = normalized_events()
    single = replace(
        normalized,
        market_data=normalized.market_data[:1],
        source_records=normalized.source_records[:1],
        identities=normalized.identities[:1],
    )
    snapshot = MarketSnapshot(
        uuid4(),
        CUTOFF,
        CUTOFF,
        "BTCUSDT-SPOT",
        "synthetic-venue",
        (single.market_data[0].market_data_id,),
        (single.source_records[0].source_record_id,),
    )
    single_policy = replace(
        quality_policy,
        expected_record_count=1,
        expected_sequence_end=quality_policy.expected_sequence_start,
    )
    report = assess_data_quality(
        snapshot,
        single.market_data,
        single.source_records,
        single_policy,
        assessed_at=CUTOFF,
        trade_ticks=single,
    )
    assert report.status is DataQualityStatus.VALID
    assert report.continuity == Decimal("1")


def test_order_book_delta_lineage_checksum_and_all_seven_dimensions() -> None:
    transitions, snapshot, quality_policy = book_evidence(checksum=True)
    report = assess_data_quality(
        snapshot,
        tuple(item.market_data for item in transitions if item.market_data is not None),
        tuple(
            item.source_record for item in transitions if item.source_record is not None
        ),
        quality_policy,
        assessed_at=CUTOFF,
        book_transitions=transitions,
    )
    assert report.status is DataQualityStatus.VALID
    assert (
        report.completeness,
        report.freshness,
        report.accuracy,
        report.consistency,
        report.source_reliability,
        report.coverage,
        report.continuity,
    ) == (Decimal("1"),) * 7
    assert all(item.quality.checksum is ChecksumStatus.VERIFIED for item in transitions)


def test_order_book_point_snapshot_missing_checksum_and_duplicate_degrade_or_reject() -> (
    None
):
    transitions, snapshot, quality_policy = book_evidence()
    no_checksum = assess_data_quality(
        snapshot,
        tuple(item.market_data for item in transitions if item.market_data is not None),
        tuple(
            item.source_record for item in transitions if item.source_record is not None
        ),
        quality_policy,
        assessed_at=CUTOFF,
        book_transitions=transitions,
    )
    assert no_checksum.status is DataQualityStatus.DEGRADED
    assert any("checksum-not-available" in item for item in no_checksum.anomalies)
    duplicate = replace(
        transitions[-1],
        source_record=None,
        market_data=None,
        quality=replace(transitions[-1].quality, duplicate=True),
    )
    duplicate_report = assess_data_quality(
        snapshot,
        tuple(item.market_data for item in transitions if item.market_data is not None),
        tuple(
            item.source_record for item in transitions if item.source_record is not None
        ),
        quality_policy,
        assessed_at=CUTOFF,
        book_transitions=transitions + (duplicate,),
    )
    assert duplicate_report.status is DataQualityStatus.INVALID
    assert duplicate_report.duplicate_record_ids == ("book-delta",)


def test_order_book_invalid_state_stale_checksum_and_lineage_fail_closed() -> None:
    transitions, snapshot, quality_policy = book_evidence(checksum=True)
    invalid_state = replace(
        transitions[-1].state,
        status=BookStatus.INVALID,
        failure=BookFailure.SEQUENCE,
    )
    invalid_transition = replace(transitions[-1], state=invalid_state)
    invalid = assess_data_quality(
        snapshot,
        tuple(item.market_data for item in transitions if item.market_data is not None),
        tuple(
            item.source_record for item in transitions if item.source_record is not None
        ),
        quality_policy,
        assessed_at=CUTOFF,
        book_transitions=(transitions[0], invalid_transition),
    )
    assert invalid.status is DataQualityStatus.INVALID
    assert "book-state:SEQUENCE" in invalid.invalid_record_ids
    bad_checksum = replace(
        transitions[-1],
        quality=replace(transitions[-1].quality, checksum=ChecksumStatus.NOT_AVAILABLE),
    )
    checksum_report = assess_data_quality(
        snapshot,
        tuple(item.market_data for item in transitions if item.market_data is not None),
        tuple(
            item.source_record for item in transitions if item.source_record is not None
        ),
        quality_policy,
        assessed_at=CUTOFF,
        book_transitions=(transitions[0], bad_checksum),
    )
    assert checksum_report.status is DataQualityStatus.INVALID
    bad_lineage_state = replace(
        transitions[-1].state, source_lineage=transitions[-1].state.source_lineage[:-1]
    )
    with pytest.raises(DataQualityAssessmentError, match="state, thresholds"):
        assess_data_quality(
            snapshot,
            tuple(
                item.market_data for item in transitions if item.market_data is not None
            ),
            tuple(
                item.source_record
                for item in transitions
                if item.source_record is not None
            ),
            quality_policy,
            assessed_at=CUTOFF,
            book_transitions=(
                transitions[0],
                replace(transitions[-1], state=bad_lineage_state),
            ),
        )


def test_order_book_stale_and_crossed_state_cannot_be_valid() -> None:
    transitions, snapshot, quality_policy = book_evidence(checksum=True)
    observations = tuple(
        item.market_data for item in transitions if item.market_data is not None
    )
    sources = tuple(
        item.source_record for item in transitions if item.source_record is not None
    )
    stale = assess_data_quality(
        snapshot,
        observations,
        sources,
        replace(quality_policy, freshness_seconds=1),
        assessed_at=CUTOFF,
        book_transitions=transitions,
    )
    assert stale.status is DataQualityStatus.STALE
    crossed_state = replace(
        transitions[-1].state,
        bids=(BookLevel(Decimal("102"), Decimal("1")),),
        asks=(BookLevel(Decimal("101"), Decimal("1")),),
    )
    crossed = assess_data_quality(
        snapshot,
        observations,
        sources,
        quality_policy,
        assessed_at=CUTOFF,
        book_transitions=(
            transitions[0],
            replace(transitions[-1], state=crossed_state),
        ),
    )
    assert crossed.status is DataQualityStatus.INVALID
    assert "empty-locked-or-crossed-book" in crossed.invalid_record_ids


def test_event_identity_handoff_must_match_exact_records() -> None:
    normalized, snapshot, quality_policy = normalized_events()
    foreign_identity = replace(
        normalized.identities[0],
        market_data_id=uuid4(),
        provider_event_id="foreign-event",
    )
    forged = replace(
        normalized,
        identities=(foreign_identity,) + normalized.identities[1:],
    )
    report = assess_data_quality(
        snapshot,
        forged.market_data,
        forged.source_records,
        quality_policy,
        assessed_at=CUTOFF,
        trade_ticks=forged,
    )
    assert report.status is DataQualityStatus.INVALID
    assert str(normalized.market_data[0].market_data_id) in report.invalid_record_ids


def test_book_metrics_must_match_levels_and_checksum_status() -> None:
    transitions, snapshot, quality_policy = book_evidence(checksum=True)
    last = transitions[-1]
    assert last.market_data is not None
    tampered = replace(
        last.market_data,
        metrics=tuple(
            replace(metric, value=metric.value + Decimal("1"))
            for metric in last.market_data.metrics
        ),
    )
    tampered_transition = replace(last, market_data=tampered)
    report = assess_data_quality(
        snapshot,
        (transitions[0].market_data, tampered),
        (transitions[0].source_record, last.source_record),
        quality_policy,
        assessed_at=CUTOFF,
        book_transitions=(transitions[0], tampered_transition),
    )
    assert report.status is DataQualityStatus.INVALID
    assert str(tampered.market_data_id) in report.invalid_record_ids
