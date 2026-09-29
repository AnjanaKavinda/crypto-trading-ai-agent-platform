"""Deterministic quality assessment of supplied, immutable market evidence.

The caller supplies the coverage policy and OHLCV finality evidence. No API
response, provider success, or absence of findings is an implicit verdict.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

from trading_platform_api.market_data.contracts import (
    DataQualityReport,
    DataQualityStatus,
    DatasetVersion,
    DataSourceRecord,
    MarketData,
    MarketSnapshot,
)
from trading_platform_api.market_data.providers import (
    ProviderBatch,
    ProviderBatchStatus,
    ProviderDataKind,
)


class DataQualityAssessmentError(ValueError):
    """Mandatory evidence or a measurable denominator is unavailable."""


def _utc(name: str, value: object) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise DataQualityAssessmentError(f"{name} must be timezone-aware.")
    if value.utcoffset() is None:
        raise DataQualityAssessmentError(f"{name} must be timezone-aware.")
    return value.astimezone(UTC)


def _ratio(numerator: int, denominator: int) -> Decimal:
    if denominator <= 0:
        raise DataQualityAssessmentError("A required dimension cannot be measured.")
    return Decimal(numerator) / Decimal(denominator)


@dataclass(frozen=True, slots=True)
class MetricBound:
    name: str
    minimum: Decimal
    maximum: Decimal

    def __post_init__(self) -> None:
        if (
            not self.name
            or self.name != self.name.strip()
            or type(self.minimum) is not Decimal
            or type(self.maximum) is not Decimal
            or not self.minimum.is_finite()
            or not self.maximum.is_finite()
            or self.minimum > self.maximum
        ):
            raise DataQualityAssessmentError("Invalid explicit metric bound.")


@dataclass(frozen=True, slots=True)
class DataQualityPolicy:
    policy_version: str
    data_kind: ProviderDataKind
    instrument_id: str
    venue_id: str
    required_data_cutoff: datetime
    coverage_start: datetime
    coverage_end: datetime
    interval_seconds: int
    freshness_seconds: int
    maximum_missing_intervals: int
    required_metrics: tuple[str, ...]
    metric_bounds: tuple[MetricBound, ...]
    require_independent_comparison: bool = False

    def __post_init__(self) -> None:
        for name in ("policy_version", "instrument_id", "venue_id"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value or value != value.strip():
                raise DataQualityAssessmentError(f"{name} must be explicit.")
        if (
            type(self.data_kind) is not ProviderDataKind
            or self.data_kind is not ProviderDataKind.OHLCV
        ):
            raise DataQualityAssessmentError(
                "This bounded assessor supports OHLCV only."
            )
        for name in ("interval_seconds", "freshness_seconds"):
            value = getattr(self, name)
            if type(value) is not int or value <= 0:
                raise DataQualityAssessmentError(f"{name} must be positive.")
        if (
            type(self.maximum_missing_intervals) is not int
            or self.maximum_missing_intervals < 0
        ):
            raise DataQualityAssessmentError("Invalid missing-interval allowance.")
        if type(self.require_independent_comparison) is not bool:
            raise DataQualityAssessmentError("Comparator policy must be boolean.")
        cutoff = _utc("required_data_cutoff", self.required_data_cutoff)
        start = _utc("coverage_start", self.coverage_start)
        end = _utc("coverage_end", self.coverage_end)
        if not start < end <= cutoff:
            raise DataQualityAssessmentError("Invalid closed-history coverage window.")
        window = (end - start).total_seconds()
        if (
            window % self.interval_seconds
            or not 2 <= window / self.interval_seconds <= 10000
        ):
            raise DataQualityAssessmentError("Coverage must have 2–10000 exact slots.")
        if (
            type(self.required_metrics) is not tuple
            or not self.required_metrics
            or not {"open", "high", "low", "close", "volume"}.issubset(
                self.required_metrics
            )
            or len(self.required_metrics) != len(set(self.required_metrics))
            or any(not name or name != name.strip() for name in self.required_metrics)
        ):
            raise DataQualityAssessmentError("Required metrics must be unique.")
        if (
            type(self.metric_bounds) is not tuple
            or not all(type(bound) is MetricBound for bound in self.metric_bounds)
            or {bound.name for bound in self.metric_bounds}
            != set(self.required_metrics)
            or len(self.metric_bounds) != len(self.required_metrics)
        ):
            raise DataQualityAssessmentError("Every required metric needs a bound.")
        object.__setattr__(self, "required_data_cutoff", cutoff)
        object.__setattr__(self, "coverage_start", start)
        object.__setattr__(self, "coverage_end", end)


def assess_data_quality(
    snapshot: MarketSnapshot,
    observations: tuple[MarketData, ...],
    sources: tuple[DataSourceRecord, ...],
    policy: DataQualityPolicy,
    *,
    assessed_at: datetime,
    finalized_market_data_ids: tuple[UUID, ...] | None,
    dataset: DatasetVersion | None = None,
) -> DataQualityReport:
    """Assess the supplied snapshot, not a live provider or trading readiness.

    Seven scores have explicit denominators. Source reliability measures
    verifiable provenance *presence*, never exchange honesty or price truth.
    The finality IDs must come from trusted raw candle evidence; C-001 does
    not contain `is_final`. Missing finality yields no report at all.
    """
    if (
        not isinstance(policy, DataQualityPolicy)
        or type(snapshot) is not MarketSnapshot
    ):
        raise DataQualityAssessmentError("Policy and snapshot are required.")
    now = _utc("assessed_at", assessed_at)
    cutoff = policy.required_data_cutoff
    if now < cutoff or snapshot.as_of != cutoff:
        raise DataQualityAssessmentError("Assessment/snapshot cutoff mismatch.")
    if (
        snapshot.instrument_id != policy.instrument_id
        or snapshot.venue_id != policy.venue_id
    ):
        raise DataQualityAssessmentError("Snapshot identity does not match policy.")
    if (
        type(observations) is not tuple
        or type(sources) is not tuple
        or not observations
        or not sources
        or len(observations) > 10000
        or not all(type(item) is MarketData for item in observations)
        or not all(type(item) is DataSourceRecord for item in sources)
    ):
        raise DataQualityAssessmentError(
            "Finite observations and sources are required."
        )
    if (
        type(finalized_market_data_ids) is not tuple
        or not all(type(item) is UUID for item in finalized_market_data_ids)
        or len(set(finalized_market_data_ids)) != len(finalized_market_data_ids)
    ):
        raise DataQualityAssessmentError(
            "Trusted candle finality evidence is required."
        )
    if policy.require_independent_comparison:
        raise DataQualityAssessmentError(
            "Independent comparable source evidence was not supplied."
        )
    if len({(s.provider_id, s.provider_version) for s in sources}) != 1:
        raise DataQualityAssessmentError(
            "Mixed providers require independent comparison semantics."
        )
    if snapshot.dataset_version is not None:
        if (
            type(dataset) is not DatasetVersion
            or dataset.dataset_id != snapshot.dataset_version.dataset_id
            or dataset.version != snapshot.dataset_version.version
            or dataset.point_in_time_cutoff > cutoff
            or dataset.coverage_start > policy.coverage_start
            or dataset.coverage_end < policy.coverage_end
        ):
            raise DataQualityAssessmentError("Dataset identity or coverage is missing.")
    elif dataset is not None:
        raise DataQualityAssessmentError("Unreferenced dataset cannot be assessed.")

    expected = (
        int((policy.coverage_end - policy.coverage_start).total_seconds())
        // policy.interval_seconds
    )
    step = timedelta(seconds=policy.interval_seconds)
    bounds = {bound.name: bound for bound in policy.metric_bounds}
    source_by_id = {item.source_record_id: item for item in sources}
    source_duplicates = len(source_by_id) != len(sources)
    observed_slots: set[int] = set()
    observation_ids: set[UUID] = set()
    duplicate_ids: list[str] = []
    invalid_ids: list[str] = []
    unavailable_ids: list[str] = []
    missing_fields: list[str] = []
    anomalies: list[str] = []
    valid_cells = 0
    accurate_count = 0
    consistent_count = 0
    reliable_count = 0
    prior_time: datetime | None = None
    reference_units = {
        metric.metric_name: metric.unit for metric in observations[0].metrics
    }
    final_set = set(finalized_market_data_ids)
    for item in observations:
        label = str(item.market_data_id)
        if item.market_data_id in observation_ids:
            duplicate_ids.append(label)
        observation_ids.add(item.market_data_id)
        metrics = {metric.metric_name: metric for metric in item.metrics}
        present = set(metrics) & set(policy.required_metrics)
        valid_cells += len(present)
        if present != set(policy.required_metrics):
            missing_fields.extend(
                f"{label}:{name}"
                for name in policy.required_metrics
                if name not in present
            )
        source = source_by_id.get(item.source_record_id)
        linked = (
            source is not None
            and item.source_record_id in snapshot.source_record_ids
            and item.market_data_id in snapshot.market_data_ids
            and item.instrument_id == policy.instrument_id
            and item.venue_id == policy.venue_id
            and item.observation_type == policy.data_kind.value
        )
        if linked:
            reliable_count += 1
        in_time = (
            policy.coverage_start <= item.event_time < policy.coverage_end
            and item.event_time + step <= cutoff
            and item.availability_time <= cutoff
            and item.ingestion_time <= cutoff
            and (prior_time is None or item.event_time > prior_time)
            and source is not None
            and source.provider_event_time >= item.event_time
            and source.provider_event_time <= item.provider_time
            and source.retrieval_time >= item.event_time + step
            and source.availability_time <= cutoff
        )
        offset = (item.event_time - policy.coverage_start).total_seconds()
        aligned = offset >= 0 and offset % policy.interval_seconds == 0
        if aligned and in_time:
            observed_slots.add(int(offset // policy.interval_seconds))
        if linked and in_time and aligned and item.market_data_id in final_set:
            consistent_count += 1
        elif source is None:
            unavailable_ids.append(label)
        else:
            invalid_ids.append(label)
        if any(
            name in metrics and metrics[name].unit != reference_units.get(name)
            for name in policy.required_metrics
        ):
            invalid_ids.append(label)
        price_units = {
            metrics[name].unit
            for name in ("open", "high", "low", "close")
            if name in metrics
        }
        if all(
            name in metrics
            and bounds[name].minimum <= metrics[name].value <= bounds[name].maximum
            for name in policy.required_metrics
        ) and (
            all(name in metrics for name in ("open", "high", "low", "close"))
            and len(price_units) == 1
            and min(metrics[name].value for name in ("open", "high", "low", "close"))
            > 0
            and metrics["volume"].value >= 0
            and metrics["low"].value
            <= min(metrics["open"].value, metrics["close"].value)
            and metrics["high"].value
            >= max(metrics["open"].value, metrics["close"].value)
        ):
            accurate_count += 1
        else:
            anomalies.append(label)
        prior_time = item.event_time
    if source_duplicates:
        duplicate_ids.append("duplicate-source-id")
    if final_set != observation_ids:
        invalid_ids.append("finality-identity-mismatch")
    if set(snapshot.market_data_ids) != observation_ids:
        invalid_ids.append("snapshot-observation-mismatch")
    if set(snapshot.source_record_ids) - set(source_by_id):
        unavailable_ids.append("snapshot-source-missing")
    if set(source_by_id) - set(snapshot.source_record_ids):
        invalid_ids.append("snapshot-source-mismatch")
    if dataset is not None and set(dataset.source_record_ids) != set(source_by_id):
        invalid_ids.append("dataset-source-mismatch")
    if len(observed_slots) < expected:
        missing_fields.append(f"missing-intervals:{expected - len(observed_slots)}")
    missing_fields.extend(f"source-unavailable:{item}" for item in unavailable_ids)

    recent_slots = min(
        expected,
        max(
            1,
            (policy.freshness_seconds + policy.interval_seconds - 1)
            // policy.interval_seconds,
        ),
    )
    fresh_count = len(observed_slots & set(range(expected - recent_slots, expected)))
    # An internally complete historical window is still stale for a later
    # decision cutoff. Slot coverage alone cannot establish current freshness.
    if cutoff - policy.coverage_end > timedelta(seconds=policy.freshness_seconds):
        fresh_count = 0

    # Each dimension describes a measured fraction of supplied/expected facts.
    completeness = _ratio(valid_cells, len(observations) * len(policy.required_metrics))
    freshness = _ratio(fresh_count, recent_slots)
    accuracy = _ratio(accurate_count, len(observations))
    consistency = _ratio(consistent_count, len(observations))
    source_reliability = _ratio(reliable_count, len(observations))
    coverage = _ratio(len(observed_slots), expected)
    continuity = _ratio(
        sum(
            1
            for index in range(expected - 1)
            if index in observed_slots and index + 1 in observed_slots
        ),
        expected - 1,
    )
    if invalid_ids or duplicate_ids or anomalies:
        status = DataQualityStatus.INVALID
    elif unavailable_ids or reliable_count < len(observations):
        status = DataQualityStatus.UNAVAILABLE
    elif fresh_count < recent_slots:
        status = DataQualityStatus.STALE
    elif expected - len(observed_slots) > policy.maximum_missing_intervals:
        status = DataQualityStatus.INCOMPLETE
    elif len(observed_slots) < expected:
        status = DataQualityStatus.DEGRADED
    else:
        status = DataQualityStatus.VALID
    return DataQualityReport(
        report_id=uuid4(),
        snapshot_id=snapshot.snapshot_id,
        assessed_at=now,
        required_data_cutoff=cutoff,
        completeness=completeness,
        freshness=freshness,
        accuracy=accuracy,
        consistency=consistency,
        source_reliability=source_reliability,
        coverage=coverage,
        continuity=continuity,
        status=status,
        missing_fields=tuple(dict.fromkeys(missing_fields)),
        invalid_record_ids=tuple(dict.fromkeys(invalid_ids)),
        duplicate_record_ids=tuple(dict.fromkeys(duplicate_ids)),
        anomalies=tuple(dict.fromkeys(anomalies)),
    )


def assess_complete_binance_spot_batch(
    batch: ProviderBatch, policy: DataQualityPolicy, *, assessed_at: datetime
) -> DataQualityReport:
    """Bind one known adapter's COMPLETE candle guarantee to finality IDs.

    BinanceSpotAdapter v1 emits PARTIAL plus a warning for provisional
    candles; a future adapter version needs its own reviewed handoff. A
    caller-supplied generic ProviderBatch never gains this privilege.
    """
    if (
        type(batch) is not ProviderBatch
        or batch.provider_id != "binance-spot-public"
        or batch.provider_version != "spot-api-2026-09"
        or batch.data_kind is not ProviderDataKind.OHLCV
        or batch.status is not ProviderBatchStatus.COMPLETE
        or batch.warnings
        or len(batch.snapshots) != 1
        or not batch.market_data
        or any(
            source.adapter_version != "binance-spot-adapter-v1"
            or source.provider_id != batch.provider_id
            for source in batch.source_records
        )
    ):
        raise DataQualityAssessmentError(
            "Complete trusted Spot candle batch is required."
        )
    return assess_data_quality(
        batch.snapshots[0],
        batch.market_data,
        batch.source_records,
        policy,
        assessed_at=assessed_at,
        finalized_market_data_ids=tuple(
            item.market_data_id for item in batch.market_data
        ),
    )
