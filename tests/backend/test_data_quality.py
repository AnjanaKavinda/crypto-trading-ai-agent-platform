"""Deterministic, synthetic tests of C-003 verdicts and fail-closed inputs."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from trading_platform_api.market_data import (
    DataQualityAssessmentError,
    DataQualityPolicy,
    DataQualityStatus,
    DatasetVersion,
    DatasetVersionReference,
    DataSourceRecord,
    MarketData,
    MarketSnapshot,
    MetricBound,
    MetricValue,
    ProviderBatch,
    ProviderBatchStatus,
    ProviderDataKind,
    assess_complete_binance_spot_batch,
    assess_data_quality,
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
