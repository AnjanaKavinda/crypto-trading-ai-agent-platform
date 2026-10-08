"""Deterministic quality assessment of supplied, immutable market evidence.

The caller supplies the coverage policy and OHLCV finality evidence. No API
response, provider success, or absence of findings is an implicit verdict.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import ROUND_HALF_EVEN, Context, Decimal
from types import MappingProxyType
from uuid import UUID, uuid4

from trading_platform_api.contracts.serialization import canonical_sha256
from trading_platform_api.market_data.contracts import (
    CONTRACT_SCHEMA_VERSION,
    AssessmentPolicyReference,
    DataQualityDimension,
    DataQualityDimensionReasonCode,
    DataQualityDimensionResult,
    DataQualityDimensionState,
    DataQualityEvidenceReference,
    DataQualityReport,
    DataQualityReportV2,
    DataQualityStatus,
    DatasetVersion,
    DataSourceRecord,
    MarketData,
    MarketSnapshot,
)
from trading_platform_api.market_data.order_book import (
    BookFailure,
    BookPolicy,
    BookQuality,
    BookState,
    BookStatus,
    BookTransition,
    ChecksumStatus,
)
from trading_platform_api.market_data.providers import (
    ProviderBatch,
    ProviderBatchStatus,
    ProviderDataKind,
)
from trading_platform_api.market_data.trades import (
    NormalizedTradeTicks,
    ReportedSide,
    SideSemantics,
    TradeTickIdentity,
    TradeTickQuality,
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


@dataclass(frozen=True, slots=True)
class SpotQualityMetricRule:
    name: str
    unit: str
    minimum: Decimal
    maximum: Decimal

    def __post_init__(self) -> None:
        if (
            not isinstance(self.name, str)
            or not self.name
            or self.name != self.name.strip()
            or len(self.name) > 255
            or not isinstance(self.unit, str)
            or not self.unit
            or self.unit != self.unit.strip()
            or len(self.unit) > 255
            or type(self.minimum) is not Decimal
            or type(self.maximum) is not Decimal
            or not self.minimum.is_finite()
            or not self.maximum.is_finite()
            or self.minimum > self.maximum
        ):
            raise DataQualityAssessmentError("Invalid explicit Spot metric rule.")


_SPOT_DIMENSION_PROFILE_VERSION = "spot-dimensions-v1"
_MAX_SPOT_RECORDS = 10_000
_SPOT_METRIC_MINIMUM = Decimal("1e-18")
_SPOT_METRIC_MAXIMUM = Decimal("1e18")
_SPOT_INSTRUMENT_PROFILES = MappingProxyType(
    {
        "BTC-USDT-SPOT": ("BINANCE-SPOT", "USDT", "BTC"),
        "ETH-USDT-SPOT": ("BINANCE-SPOT", "USDT", "ETH"),
        "BNB-USDT-SPOT": ("BINANCE-SPOT", "USDT", "BNB"),
        "SOL-USDT-SPOT": ("BINANCE-SPOT", "USDT", "SOL"),
        "XRP-USDT-SPOT": ("BINANCE-SPOT", "USDT", "XRP"),
    }
)


@dataclass(frozen=True, slots=True)
class _SpotPolicyDefinition:
    data_kind: ProviderDataKind
    mode: str
    require_independent_comparison: bool
    require_checksum: bool
    freshness_seconds: int
    maximum_missing_records: int
    metric_rules: tuple[tuple[str, Decimal, Decimal], ...]
    dimension_profile_version: str = _SPOT_DIMENSION_PROFILE_VERSION


def _spot_policy_definition(
    data_kind: ProviderDataKind,
    mode: str,
    *,
    independent: bool = False,
    checksum: bool = False,
    maximum_missing_records: int = 0,
) -> _SpotPolicyDefinition:
    if data_kind is ProviderDataKind.TRADE:
        names: tuple[str, ...] = ("price", "quantity")
    elif data_kind is ProviderDataKind.TICK:
        names = ("price",)
    else:
        names = ("bid_1_price", "bid_1_quantity", "ask_1_price", "ask_1_quantity")
    return _SpotPolicyDefinition(
        data_kind,
        mode,
        independent,
        checksum,
        freshness_seconds=10,
        maximum_missing_records=maximum_missing_records,
        metric_rules=tuple(
            (
                name,
                Decimal("0")
                if name.endswith("quantity")
                and data_kind is ProviderDataKind.ORDER_BOOK
                else _SPOT_METRIC_MINIMUM,
                _SPOT_METRIC_MAXIMUM,
            )
            for name in names
        ),
    )


_SPOT_POLICY_DEFINITIONS = MappingProxyType(
    {
        ("spot-trade-quality", "1"): _spot_policy_definition(
            ProviderDataKind.TRADE, "sequence"
        ),
        ("spot-tick-quality", "1"): _spot_policy_definition(
            ProviderDataKind.TICK, "sequence"
        ),
        ("spot-order-book-point", "1"): _spot_policy_definition(
            ProviderDataKind.ORDER_BOOK, "point"
        ),
        ("spot-order-book-delta", "1"): _spot_policy_definition(
            ProviderDataKind.ORDER_BOOK, "delta"
        ),
        ("spot-trade-quality-independent", "1"): _spot_policy_definition(
            ProviderDataKind.TRADE, "sequence", independent=True
        ),
        ("spot-tick-quality-independent", "1"): _spot_policy_definition(
            ProviderDataKind.TICK, "sequence", independent=True
        ),
        ("spot-order-book-point-independent", "1"): _spot_policy_definition(
            ProviderDataKind.ORDER_BOOK, "point", independent=True
        ),
        ("spot-order-book-delta-independent", "1"): _spot_policy_definition(
            ProviderDataKind.ORDER_BOOK, "delta", independent=True
        ),
        ("spot-order-book-point-checksum", "1"): _spot_policy_definition(
            ProviderDataKind.ORDER_BOOK, "point", checksum=True
        ),
        ("spot-order-book-delta-checksum", "1"): _spot_policy_definition(
            ProviderDataKind.ORDER_BOOK, "delta", checksum=True
        ),
        ("spot-trade-quality-one-missing", "1"): _spot_policy_definition(
            ProviderDataKind.TRADE, "sequence", maximum_missing_records=1
        ),
    }
)


@dataclass(frozen=True, slots=True)
class SpotQualityPolicy:
    """Bind explicit instrument/snapshot scope to a recognized immutable policy.

    Metric names, bounds, freshness, missing-record tolerance, and modality
    semantics are fixed by the local policy definition. Units and population
    counts are explicit scope inputs and are included in the report reference.
    """

    assessment_policy_id: str
    assessment_policy_version: str
    data_kind: ProviderDataKind
    instrument_id: str
    venue_id: str
    required_data_cutoff: datetime
    expected_record_count: int | None
    freshness_seconds: int
    metric_rules: tuple[SpotQualityMetricRule, ...]
    expected_transition_count: int | None = None
    maximum_missing_records: int = 0
    require_independent_comparison: bool = False
    require_checksum: bool = False

    def __post_init__(self) -> None:
        for name in (
            "assessment_policy_id",
            "assessment_policy_version",
            "instrument_id",
            "venue_id",
        ):
            value = getattr(self, name)
            if (
                not isinstance(value, str)
                or not value
                or value != value.strip()
                or len(value) > 255
            ):
                raise DataQualityAssessmentError(f"{name} must be explicit.")
        reference = (self.assessment_policy_id, self.assessment_policy_version)
        definition = _SPOT_POLICY_DEFINITIONS.get(reference)
        if definition is None or type(self.data_kind) is not ProviderDataKind:
            raise DataQualityAssessmentError("Unknown Spot assessment policy/version.")
        if (
            self.data_kind is not definition.data_kind
            or self.require_independent_comparison
            is not definition.require_independent_comparison
            or self.require_checksum is not definition.require_checksum
        ):
            raise DataQualityAssessmentError("Policy and data kind do not match.")
        instrument = _SPOT_INSTRUMENT_PROFILES.get(self.instrument_id)
        if instrument is None or self.venue_id != instrument[0]:
            raise DataQualityAssessmentError(
                "Instrument and venue are outside the recognized Spot scope."
            )
        if (
            (
                self.expected_record_count is not None
                and (
                    type(self.expected_record_count) is not int
                    or not 1 <= self.expected_record_count <= _MAX_SPOT_RECORDS
                )
            )
            or type(self.freshness_seconds) is not int
            or self.freshness_seconds != definition.freshness_seconds
            or type(self.maximum_missing_records) is not int
            or self.maximum_missing_records != definition.maximum_missing_records
            or (
                self.expected_record_count is not None
                and self.maximum_missing_records > self.expected_record_count
            )
            or (
                self.expected_record_count is None and self.maximum_missing_records != 0
            )
            or type(self.require_independent_comparison) is not bool
            or type(self.require_checksum) is not bool
        ):
            raise DataQualityAssessmentError("Invalid bounded Spot policy values.")
        cutoff = _utc("required_data_cutoff", self.required_data_cutoff)
        if (
            type(self.metric_rules) is not tuple
            or len(self.metric_rules) != len(definition.metric_rules)
            or not all(
                type(rule) is SpotQualityMetricRule for rule in self.metric_rules
            )
            or any(
                (rule.name, rule.minimum, rule.maximum) != approved
                for rule, approved in zip(self.metric_rules, definition.metric_rules)
            )
        ):
            raise DataQualityAssessmentError(
                "Metric rules must match the recognized Spot policy definition."
            )
        if any(
            rule.unit
            != (instrument[2] if rule.name.endswith("quantity") else instrument[1])
            for rule in self.metric_rules
        ):
            raise DataQualityAssessmentError(
                "Metric units must match the recognized instrument profile."
            )
        if self.expected_transition_count is not None and (
            type(self.expected_transition_count) is not int
            or not 1 <= self.expected_transition_count <= _MAX_SPOT_RECORDS
            or (
                self.expected_record_count is not None
                and self.expected_transition_count >= self.expected_record_count
            )
        ):
            raise DataQualityAssessmentError("Invalid expected transition count.")
        if definition.mode != "point" and (
            (self.expected_record_count is None)
            != (self.expected_transition_count is None)
            or (
                self.expected_record_count is not None
                and self.expected_transition_count != self.expected_record_count - 1
            )
        ):
            raise DataQualityAssessmentError(
                "Transition denominator must match the expected adjacent-record count."
            )
        if definition.mode == "point" and (
            self.expected_record_count != 1
            or self.expected_transition_count is not None
        ):
            raise DataQualityAssessmentError(
                "Point-snapshot policy requires one record and no transition count."
            )
        if definition.mode == "delta" and self.expected_record_count == 1:
            raise DataQualityAssessmentError(
                "Delta policy requires a multi-record window."
            )
        object.__setattr__(self, "required_data_cutoff", cutoff)

    @classmethod
    def resolve_reference(
        cls,
        assessment_policy_id: str,
        assessment_policy_version: str,
    ) -> SpotQualityPolicy:
        """Reconstruct an effective policy from a C-003 v2 report reference."""
        if (
            type(assessment_policy_id) is not str
            or type(assessment_policy_version) is not str
            or len(assessment_policy_version) > 128
        ):
            raise DataQualityAssessmentError("Unknown Spot policy reference.")
        parts = assessment_policy_version.split(":")
        if len(parts) != 5 or not all(parts):
            raise DataQualityAssessmentError("Unknown Spot policy reference.")
        definition = _SPOT_POLICY_DEFINITIONS.get((assessment_policy_id, parts[0]))
        if definition is None:
            raise DataQualityAssessmentError("Unknown Spot policy reference.")
        instrument_id = parts[1]
        instrument = _SPOT_INSTRUMENT_PROFILES.get(instrument_id)
        if instrument is None:
            raise DataQualityAssessmentError("Unknown Spot instrument reference.")
        try:
            cutoff_token = parts[4]
            if (
                len(cutoff_token) != 22
                or cutoff_token[8] != "T"
                or cutoff_token[21] != "Z"
                or not (cutoff_token[:8] + cutoff_token[9:21]).isascii()
                or not (cutoff_token[:8] + cutoff_token[9:21]).isdecimal()
            ):
                raise ValueError
            cutoff = datetime(
                int(cutoff_token[:4]),
                int(cutoff_token[4:6]),
                int(cutoff_token[6:8]),
                int(cutoff_token[9:11]),
                int(cutoff_token[11:13]),
                int(cutoff_token[13:15]),
                int(cutoff_token[15:21]),
                tzinfo=UTC,
            )
        except ValueError as exc:
            raise DataQualityAssessmentError("Malformed Spot policy cutoff.") from exc

        def decode_count(value: str) -> int | None:
            if value == "-":
                return None
            if not value.isascii() or not value.isdecimal():
                raise DataQualityAssessmentError("Malformed Spot policy population.")
            count = int(value)
            if str(count) != value:
                raise DataQualityAssessmentError("Malformed Spot policy population.")
            return count

        expected_record_count = decode_count(parts[2])
        expected_transition_count = decode_count(parts[3])
        rules = tuple(
            SpotQualityMetricRule(
                name,
                instrument[2] if name.endswith("quantity") else instrument[1],
                minimum,
                maximum,
            )
            for name, minimum, maximum in definition.metric_rules
        )
        return cls(
            assessment_policy_id,
            parts[0],
            definition.data_kind,
            instrument_id,
            instrument[0],
            cutoff,
            expected_record_count,
            definition.freshness_seconds,
            rules,
            expected_transition_count=expected_transition_count,
            maximum_missing_records=definition.maximum_missing_records,
            require_independent_comparison=definition.require_independent_comparison,
            require_checksum=definition.require_checksum,
        )

    @property
    def resolved_policy_version(self) -> str:
        expected = (
            "-"
            if self.expected_record_count is None
            else str(self.expected_record_count)
        )
        transitions = (
            "-"
            if self.expected_transition_count is None
            else str(self.expected_transition_count)
        )
        cutoff = self.required_data_cutoff
        cutoff_token = (
            f"{cutoff.year:04d}{cutoff.month:02d}{cutoff.day:02d}T"
            f"{cutoff.hour:02d}{cutoff.minute:02d}{cutoff.second:02d}"
            f"{cutoff.microsecond:06d}Z"
        )
        return (
            f"{self.assessment_policy_version}:{self.instrument_id}:"
            f"{expected}:{transitions}:{cutoff_token}"
        )


def _spot_dimension(
    dimension: DataQualityDimension,
    numerator: int,
    denominator: int,
    unit: str,
    evidence: DataQualityEvidenceReference,
) -> DataQualityDimensionResult:
    if denominator <= 0 or numerator < 0 or numerator > denominator:
        raise DataQualityAssessmentError("Invalid Spot quality measurement basis.")
    score = Context(prec=28, rounding=ROUND_HALF_EVEN).divide(
        Decimal(numerator), Decimal(denominator)
    )
    return DataQualityDimensionResult(
        dimension,
        DataQualityDimensionState.MEASURED,
        score,
        numerator=numerator,
        denominator=denominator,
        basis_unit=unit,
        evidence_reference=evidence if numerator == 0 else None,
    )


def _spot_unavailable(
    dimension: DataQualityDimension,
    reason: DataQualityDimensionReasonCode,
) -> DataQualityDimensionResult:
    return DataQualityDimensionResult(
        dimension,
        DataQualityDimensionState.UNAVAILABLE,
        reason_code=reason,
    )


def _spot_quality_report(
    snapshot: MarketSnapshot,
    policy: SpotQualityPolicy,
    *,
    assessed_at: datetime,
    observations: tuple[MarketData, ...],
    sources: tuple[DataSourceRecord, ...],
    dataset: DatasetVersion | None,
    sequence_verified: bool,
    sequence_scope_valid: bool,
    duplicate_ids: tuple[str, ...] = (),
    anomalies: tuple[str, ...] = (),
    invalid_ids: tuple[str, ...] = (),
    missing_fields: tuple[str, ...] = (),
    stale_state: bool = False,
    checksum_unavailable: bool = False,
    point_snapshot: bool = False,
) -> DataQualityReportV2:
    now = _utc("assessed_at", assessed_at)
    cutoff = policy.required_data_cutoff
    if now < cutoff or snapshot.as_of != cutoff or snapshot.created_at > now:
        raise DataQualityAssessmentError("Assessment/snapshot cutoff mismatch.")
    if (
        snapshot.instrument_id != policy.instrument_id
        or snapshot.venue_id != policy.venue_id
    ):
        raise DataQualityAssessmentError("Snapshot identity does not match policy.")
    if policy.require_independent_comparison:
        raise DataQualityAssessmentError(
            "Independent comparable source evidence was not supplied."
        )
    if (
        type(observations) is not tuple
        or type(sources) is not tuple
        or len(observations) > _MAX_SPOT_RECORDS
        or not all(type(item) is MarketData for item in observations)
        or not all(type(item) is DataSourceRecord for item in sources)
    ):
        raise DataQualityAssessmentError("Invalid bounded normalized evidence.")
    observation_ids = tuple(item.market_data_id for item in observations)
    source_ids = tuple(item.source_record_id for item in sources)
    if (
        len(set(observation_ids)) != len(observation_ids)
        or len(set(source_ids)) != len(source_ids)
        or observation_ids != snapshot.market_data_ids
        or source_ids != snapshot.source_record_ids
        or tuple(item.source_record_id for item in observations) != source_ids
    ):
        raise DataQualityAssessmentError(
            "Exact ordered C-001/C-091 snapshot membership is required."
        )
    if dataset is None:
        if snapshot.dataset_version is not None:
            raise DataQualityAssessmentError(
                "Referenced C-092 dataset evidence is required."
            )
    else:
        _validate_spot_dataset(snapshot, sources, dataset, policy)
    source_by_id = {item.source_record_id: item for item in sources}
    provider_identity: tuple[str, str, str, str, str] | None = None
    previous_event_time: datetime | None = None
    for item in observations:
        source = source_by_id.get(item.source_record_id)
        if (
            source is None
            or item.instrument_id != policy.instrument_id
            or item.venue_id != policy.venue_id
            or item.observation_type != policy.data_kind.value
            or item.event_time > cutoff
            or item.provider_time > cutoff
            or item.ingestion_time > cutoff
            or item.availability_time > cutoff
            or (
                previous_event_time is not None
                and item.event_time < previous_event_time
            )
            or source.provider_event_time != item.provider_time
            or source.retrieval_time > item.ingestion_time
            or source.availability_time > item.availability_time
            or source.availability_time > cutoff
        ):
            raise DataQualityAssessmentError(
                "Observation/source identity or cutoff mismatch."
            )
        identity = (
            source.provider_id,
            source.provider_version,
            source.raw_schema_version,
            source.adapter_version,
            source.licensing_reference,
        )
        if provider_identity is not None and identity != provider_identity:
            raise DataQualityAssessmentError("Mixed source identity.")
        provider_identity = identity
        previous_event_time = item.event_time

    evidence = DataQualityEvidenceReference(
        "C-002",
        str(snapshot.snapshot_id),
        snapshot.schema_version,
        canonical_sha256(snapshot),
    )
    metric_cells = 0
    accurate_records = 0
    missing = list(missing_fields)
    invalid = list(invalid_ids)
    for item in observations:
        metrics = {metric.metric_name: metric for metric in item.metrics}
        invalid_metric = False
        record_accurate = True
        for rule in policy.metric_rules:
            metric = metrics.get(rule.name)
            if metric is None:
                missing.append(f"{item.market_data_id}:{rule.name}")
                record_accurate = False
                continue
            valid = (
                metric.unit == rule.unit
                and rule.minimum <= metric.value <= rule.maximum
            )
            if valid:
                metric_cells += 1
            else:
                invalid_metric = True
                record_accurate = False
        if invalid_metric:
            invalid.append(str(item.market_data_id))
        if record_accurate:
            accurate_records += 1
    expected = policy.expected_record_count
    observed = len(observations)
    if expected is not None and observed > expected:
        raise DataQualityAssessmentError(
            "Observed records exceed the policy's exact expected population."
        )
    expected_cells = None if expected is None else expected * len(policy.metric_rules)
    fresh_count = sum(
        1
        for item in observations
        if timedelta(0)
        <= cutoff - item.event_time
        <= timedelta(seconds=policy.freshness_seconds)
    )
    latest_stale = (
        stale_state
        or not observations
        or (
            cutoff - observations[-1].event_time
            > timedelta(seconds=policy.freshness_seconds)
        )
    )
    transition_count = policy.expected_transition_count
    if point_snapshot:
        continuity = DataQualityDimensionResult(
            DataQualityDimension.CONTINUITY,
            DataQualityDimensionState.NOT_APPLICABLE,
            reason_code=DataQualityDimensionReasonCode.SINGLE_POINT_SNAPSHOT,
            not_applicable_policy=AssessmentPolicyReference(
                policy.assessment_policy_id, policy.resolved_policy_version
            ),
        )
    elif not sequence_verified or not sequence_scope_valid:
        continuity = _spot_unavailable(
            DataQualityDimension.CONTINUITY,
            DataQualityDimensionReasonCode.SEQUENCE_UNVERIFIED,
        )
    elif transition_count is None:
        continuity = _spot_unavailable(
            DataQualityDimension.CONTINUITY,
            DataQualityDimensionReasonCode.DENOMINATOR_UNAVAILABLE,
        )
    elif observed < 2:
        continuity = _spot_unavailable(
            DataQualityDimension.CONTINUITY,
            DataQualityDimensionReasonCode.MISSING_REQUIRED_EVIDENCE,
        )
    else:
        transitions = min(observed - 1, transition_count)
        continuity = _spot_dimension(
            DataQualityDimension.CONTINUITY,
            transitions,
            transition_count,
            "sequence_transitions",
            evidence,
        )
    if checksum_unavailable:
        accuracy = _spot_unavailable(
            DataQualityDimension.ACCURACY,
            DataQualityDimensionReasonCode.MISSING_REQUIRED_EVIDENCE,
        )
    elif expected is None:
        accuracy = _spot_unavailable(
            DataQualityDimension.ACCURACY,
            DataQualityDimensionReasonCode.DENOMINATOR_UNAVAILABLE,
        )
    else:
        accuracy = _spot_dimension(
            DataQualityDimension.ACCURACY,
            accurate_records,
            expected,
            "observations",
            evidence,
        )
    dimensions = (
        (
            _spot_unavailable(
                DataQualityDimension.COMPLETENESS,
                DataQualityDimensionReasonCode.DENOMINATOR_UNAVAILABLE,
            )
            if expected_cells is None
            else _spot_dimension(
                DataQualityDimension.COMPLETENESS,
                metric_cells,
                expected_cells,
                "metric_cells",
                evidence,
            )
        ),
        (
            _spot_unavailable(
                DataQualityDimension.FRESHNESS,
                DataQualityDimensionReasonCode.DENOMINATOR_UNAVAILABLE,
            )
            if expected is None
            else _spot_dimension(
                DataQualityDimension.FRESHNESS,
                fresh_count,
                expected,
                "observations",
                evidence,
            )
        ),
        accuracy,
        (
            _spot_unavailable(
                DataQualityDimension.CONSISTENCY,
                DataQualityDimensionReasonCode.DENOMINATOR_UNAVAILABLE,
            )
            if expected is None
            else _spot_dimension(
                DataQualityDimension.CONSISTENCY,
                observed,
                expected,
                "observations",
                evidence,
            )
        ),
        (
            _spot_unavailable(
                DataQualityDimension.SOURCE_RELIABILITY,
                DataQualityDimensionReasonCode.DENOMINATOR_UNAVAILABLE,
            )
            if expected is None
            else _spot_dimension(
                DataQualityDimension.SOURCE_RELIABILITY,
                len(sources),
                expected,
                "source_records",
                evidence,
            )
        ),
        (
            _spot_unavailable(
                DataQualityDimension.COVERAGE,
                DataQualityDimensionReasonCode.DENOMINATOR_UNAVAILABLE,
            )
            if expected is None
            else _spot_dimension(
                DataQualityDimension.COVERAGE,
                observed,
                expected,
                "observations",
                evidence,
            )
        ),
        continuity,
    )
    all_missing = tuple(dict.fromkeys(missing))
    all_invalid = tuple(dict.fromkeys(invalid))
    all_duplicates = tuple(dict.fromkeys(duplicate_ids))
    all_anomalies = tuple(dict.fromkeys(anomalies))
    unavailable = any(
        item.state is DataQualityDimensionState.UNAVAILABLE for item in dimensions
    )
    missing_population = 0 if expected is None else expected - observed
    if all_invalid or all_duplicates:
        status = DataQualityStatus.INVALID
    elif unavailable:
        status = DataQualityStatus.UNAVAILABLE
    elif latest_stale:
        status = DataQualityStatus.STALE
    elif missing_population > policy.maximum_missing_records or (
        all_missing and policy.maximum_missing_records == 0
    ):
        status = DataQualityStatus.INCOMPLETE
    elif missing_population or all_missing or all_anomalies:
        status = DataQualityStatus.DEGRADED
    else:
        status = DataQualityStatus.VALID
    return DataQualityReportV2(
        report_id=uuid4(),
        snapshot_id=snapshot.snapshot_id,
        assessed_at=now,
        required_data_cutoff=cutoff,
        assessment_policy_id=policy.assessment_policy_id,
        assessment_policy_version=policy.resolved_policy_version,
        dimensions=dimensions,
        status=status,
        missing_fields=all_missing,
        invalid_record_ids=all_invalid,
        duplicate_record_ids=all_duplicates,
        anomalies=all_anomalies,
    )


def assess_normalized_spot_trades(
    snapshot: MarketSnapshot,
    normalized: NormalizedTradeTicks,
    policy: SpotQualityPolicy,
    *,
    assessed_at: datetime,
    dataset: DatasetVersion | None = None,
) -> DataQualityReportV2:
    """Assess exact normalized TRADE evidence; no provider fetch or side inference.

    Per-record dimensions use the policy's expected population as denominator.
    Completeness is valid required metric cells / (expected records * required
    metric rules). Freshness is in-age observations / expected records.
    Accuracy is observations passing required units and bounds / expected
    records. Consistency is exact, ordered C-001/C-091 links / expected records.
    Source reliability is verifiable C-091 records / expected records; it makes
    no claim about provider truth. Coverage is observations / expected records.
    Continuity is verified adjacent transitions / the positive policy transition
    denominator; absent sequence or sequence scope is UNAVAILABLE.
    """
    if (
        type(policy) is not SpotQualityPolicy
        or policy.data_kind is not ProviderDataKind.TRADE
    ):
        raise DataQualityAssessmentError("TRADE assessment policy is required.")
    return _assess_trade_tick_as_kind(
        snapshot, normalized, policy, assessed_at=assessed_at, dataset=dataset
    )


def assess_normalized_spot_ticks(
    snapshot: MarketSnapshot,
    normalized: NormalizedTradeTicks,
    policy: SpotQualityPolicy,
    *,
    assessed_at: datetime,
    dataset: DatasetVersion | None = None,
) -> DataQualityReportV2:
    """Assess exact normalized TICK evidence under the C-003 v2 dimension basis.

    Completeness, freshness, accuracy, consistency, source reliability, coverage,
    and continuity use the same explicit numerators, denominators, and units as
    the TRADE assessor. TICK rules may require price and may explicitly require
    quantity; quantity is otherwise not inferred or treated as missing.
    """
    if (
        type(policy) is not SpotQualityPolicy
        or policy.data_kind is not ProviderDataKind.TICK
    ):
        raise DataQualityAssessmentError("TICK assessment policy is required.")
    return _assess_trade_tick_as_kind(
        snapshot, normalized, policy, assessed_at=assessed_at, dataset=dataset
    )


def _assess_trade_tick_as_kind(
    snapshot: MarketSnapshot,
    normalized: NormalizedTradeTicks,
    policy: SpotQualityPolicy,
    *,
    assessed_at: datetime,
    dataset: DatasetVersion | None,
) -> DataQualityReportV2:
    expected_kind = policy.data_kind
    if (
        type(normalized) is not NormalizedTradeTicks
        or normalized.data_kind is not expected_kind
        or type(normalized.quality) is not TradeTickQuality
        or type(normalized.market_data) is not tuple
        or type(normalized.source_records) is not tuple
        or type(normalized.identities) is not tuple
        or len(normalized.market_data) != len(normalized.source_records)
        or len(normalized.identities) != len(normalized.market_data)
        or type(normalized.quality.empty) is not bool
        or normalized.quality.empty is not (not normalized.market_data)
        or type(normalized.quality.sequence_verified) is not bool
        or not all(type(item) is TradeTickIdentity for item in normalized.identities)
    ):
        raise DataQualityAssessmentError(
            "Exact normalized trade/tick handoff required."
        )
    if normalized.quality.empty:
        raise DataQualityAssessmentError(
            "An empty normalized batch has no exact C-002 market-data membership."
        )
    unknown = tuple(
        identity.provider_event_id
        for identity in normalized.identities
        if identity.aggressor_side is ReportedSide.UNKNOWN
    )
    if (
        type(normalized.quality.unknown_aggressor_event_ids) is not tuple
        or tuple(normalized.quality.unknown_aggressor_event_ids) != unknown
        or type(normalized.quality.duplicate_event_ids) is not tuple
        or not all(
            type(event_id) is str and event_id and event_id == event_id.strip()
            for event_id in normalized.quality.duplicate_event_ids
        )
    ):
        raise DataQualityAssessmentError("Trade/tick quality handoff mismatch.")
    if any(
        identity.market_data_id != item.market_data_id
        or identity.source_record_id != item.source_record_id
        for identity, item in zip(normalized.identities, normalized.market_data)
    ):
        raise DataQualityAssessmentError(
            "Trade/tick identity does not match C-001/C-091."
        )
    for identity, item in zip(normalized.identities, normalized.market_data):
        if (
            type(identity.market_data_id) is not UUID
            or type(identity.source_record_id) is not UUID
            or type(identity.provider_event_id) is not str
            or not identity.provider_event_id
            or identity.provider_event_id != identity.provider_event_id.strip()
            or type(identity.reported_side) is not ReportedSide
            or type(identity.side_semantics) is not SideSemantics
            or type(identity.aggressor_side) is not ReportedSide
        ):
            raise DataQualityAssessmentError("Invalid trade/tick identity fields.")
        metrics = {metric.metric_name: metric for metric in item.metrics}
        permitted_names = {rule.name for rule in policy.metric_rules} | {
            "aggressor_sign",
            "quantity",
        }
        if set(metrics) - permitted_names:
            raise DataQualityAssessmentError("Unexpected trade/tick metric field.")
        sign = metrics.get("aggressor_sign")
        if identity.aggressor_side is ReportedSide.UNKNOWN:
            if sign is not None:
                raise DataQualityAssessmentError(
                    "Unknown aggressor side cannot produce a signed metric."
                )
        elif (
            sign is None
            or sign.unit != "sign"
            or sign.value
            != (
                Decimal("1")
                if identity.aggressor_side is ReportedSide.BUY
                else Decimal("-1")
            )
        ):
            raise DataQualityAssessmentError("Signed aggressor metric is inconsistent.")
    sequence_values = tuple(identity.sequence for identity in normalized.identities)
    scopes = tuple(identity.sequence_scope for identity in normalized.identities)
    scoped_sequence = (
        bool(sequence_values)
        and all(type(value) is int and value >= 0 for value in sequence_values)
        and len(set(scopes)) == 1
        and scopes[0] is not None
    )
    sequence_verified = normalized.quality.sequence_verified
    if sequence_verified and (
        not scoped_sequence
        or any(
            type(current) is not int
            or type(following) is not int
            or following != current + 1
            for current, following in zip(sequence_values, sequence_values[1:])
        )
    ):
        raise DataQualityAssessmentError(
            "Unverified or conflicting trade/tick sequence."
        )
    if not sequence_verified and any(
        sequence is not None or scope is not None
        for sequence, scope in zip(sequence_values, scopes)
    ):
        raise DataQualityAssessmentError(
            "Trade/tick sequence verification is inconsistent."
        )
    if any(
        type(identity.reported_side) is not ReportedSide
        or type(identity.side_semantics) is not SideSemantics
        or type(identity.aggressor_side) is not ReportedSide
        for identity in normalized.identities
    ):
        raise DataQualityAssessmentError("Invalid trade/tick side handoff.")
    if any(
        identity.aggressor_side
        is not (
            identity.reported_side
            if identity.side_semantics is SideSemantics.AGGRESSOR
            else ReportedSide.UNKNOWN
        )
        for identity in normalized.identities
    ):
        raise DataQualityAssessmentError(
            "Trade/tick aggressor handoff is inconsistent."
        )
    return _spot_quality_report(
        snapshot,
        policy,
        assessed_at=assessed_at,
        observations=normalized.market_data,
        sources=normalized.source_records,
        dataset=dataset,
        sequence_verified=sequence_verified,
        sequence_scope_valid=scoped_sequence,
        duplicate_ids=tuple(normalized.quality.duplicate_event_ids),
        anomalies=tuple(f"unknown-aggressor:{event_id}" for event_id in unknown),
    )


def _validate_spot_dataset(
    snapshot: MarketSnapshot,
    sources: tuple[DataSourceRecord, ...],
    dataset: DatasetVersion,
    policy: SpotQualityPolicy,
) -> None:
    reference = snapshot.dataset_version
    if (
        type(dataset) is not DatasetVersion
        or reference is None
        or (dataset.dataset_id, dataset.version)
        != (reference.dataset_id, reference.version)
        or dataset.point_in_time_cutoff > policy.required_data_cutoff
        or dataset.canonical_schema_version != CONTRACT_SCHEMA_VERSION
        or dataset.created_at > snapshot.created_at
        or dataset.coverage_start
        > min(
            (item.provider_event_time for item in sources),
            default=policy.required_data_cutoff,
        )
        or dataset.coverage_end
        < max(
            (item.provider_event_time for item in sources),
            default=policy.required_data_cutoff,
        )
        or dataset.source_record_ids != tuple(item.source_record_id for item in sources)
        or tuple(item.source_record_id for item in sources)
        != snapshot.source_record_ids
    ):
        raise DataQualityAssessmentError(
            "Dataset identity or source membership mismatch."
        )


def assess_normalized_spot_order_book(
    snapshot: MarketSnapshot,
    transitions: tuple[BookTransition, ...],
    policy: SpotQualityPolicy,
    *,
    assessed_at: datetime,
    dataset: DatasetVersion | None = None,
) -> DataQualityReportV2:
    """Assess an exact normalized book state or delta history, never live data.

    Completeness is valid required metric cells / (expected records * required
    metric rules); freshness is in-age observations / expected records; accuracy
    is valid observations / expected records; consistency and source reliability
    are exact linked observations and C-091 records / expected records; coverage
    is observations / expected records; continuity is verified applied deltas /
    the declared positive transition count. Only the recognized point policy
    makes continuity NOT_APPLICABLE. Declared checksums must have been verified.
    """
    if (
        type(policy) is not SpotQualityPolicy
        or policy.data_kind is not ProviderDataKind.ORDER_BOOK
        or type(transitions) is not tuple
        or not transitions
        or len(transitions) > _MAX_SPOT_RECORDS
        or not all(type(item) is BookTransition for item in transitions)
    ):
        raise DataQualityAssessmentError(
            "Exact normalized order-book handoff required."
        )
    definition = _SPOT_POLICY_DEFINITIONS.get(
        (policy.assessment_policy_id, policy.assessment_policy_version)
    )
    if definition is None:
        raise DataQualityAssessmentError("Unknown order-book policy.")
    mode = definition.mode
    point_policy = mode == "point"
    if point_policy and len(transitions) != 1:
        raise DataQualityAssessmentError(
            "Point-snapshot policy requires one transition."
        )
    if mode == "delta" and policy.expected_transition_count is None:
        raise DataQualityAssessmentError("Unknown order-book policy.")
    observations: list[MarketData] = []
    sources: list[DataSourceRecord] = []
    duplicate_ids: list[str] = []
    anomalies: list[str] = []
    invalid_ids: list[str] = []
    stale_state = False
    checksum_unavailable = False
    previous_state: BookState | None = None
    terminal_invalid = False
    for transition in transitions:
        state = transition.state
        if (
            type(state) is not BookState
            or type(state.policy) is not BookPolicy
            or state.policy.instrument_id != policy.instrument_id
            or type(transition.quality) is not BookQuality
        ):
            raise DataQualityAssessmentError(
                "Book state does not match assessment policy."
            )
        if (
            state.venue_id != policy.venue_id
            or state.instrument_id != policy.instrument_id
            or type(state.status) is not BookStatus
            or type(transition.quality.checksum) is not ChecksumStatus
            or type(transition.quality.duplicate) is not bool
            or (
                transition.quality.extreme_spread is not None
                and type(transition.quality.extreme_spread) is not bool
            )
        ):
            raise DataQualityAssessmentError("Book state identity is inconsistent.")
        if state.status is BookStatus.INVALID:
            if (
                terminal_invalid
                or previous_state is None
                or transition.source_record is not None
                or transition.market_data is not None
                or type(state.failure) is not BookFailure
                or (
                    previous_state is not None
                    and (
                        state.source_lineage != previous_state.source_lineage
                        or state.market_data_ids != previous_state.market_data_ids
                    )
                )
            ):
                raise DataQualityAssessmentError(
                    "Invalid book transition handoff mismatch."
                )
            terminal_invalid = True
            anomalies.append(f"book-failure:{state.failure.value}")
            if state.failure is BookFailure.STALE:
                stale_state = True
            else:
                invalid_ids.append(f"book-failure:{state.failure.value}")
            previous_state = state
            continue
        if (
            terminal_invalid
            or state.status is not BookStatus.VALID
            or state.failure is not None
        ):
            raise DataQualityAssessmentError("Invalid order-book state sequence.")
        if transition.quality.duplicate:
            if (
                previous_state is None
                or state != previous_state
                or transition.source_record is not None
                or transition.market_data is not None
                or transition.quality.checksum is not ChecksumStatus.NOT_AVAILABLE
            ):
                raise DataQualityAssessmentError(
                    "Duplicate transition changed book state."
                )
            duplicate_ids.append(
                state.fingerprints[-1].event_id
                if state.fingerprints
                else "duplicate-book"
            )
            previous_state = state
            continue
        if (
            type(transition.source_record) is not DataSourceRecord
            or type(transition.market_data) is not MarketData
        ):
            raise DataQualityAssessmentError("Book transition lacks exact C-001/C-091.")
        source = transition.source_record
        observation = transition.market_data
        source_identity = (
            source.provider_id,
            source.provider_version,
            source.raw_schema_version,
            source.adapter_version,
            source.licensing_reference,
        )
        expected_lineage = (
            (source.source_record_id,)
            if previous_state is None
            else previous_state.source_lineage + (source.source_record_id,)
        )
        expected_market_ids = (
            (observation.market_data_id,)
            if previous_state is None
            else previous_state.market_data_ids + (observation.market_data_id,)
        )
        if (
            observation.source_record_id != source.source_record_id
            or state.source_lineage != expected_lineage
            or state.market_data_ids != expected_market_ids
            or observation.observation_type != ProviderDataKind.ORDER_BOOK.value
            or not state.fingerprints
            or state.fingerprints[-1].digest != source.content_sha256
            or state.fingerprints[-1].event_time != observation.event_time
            or state.provider_identity != source_identity
        ):
            raise DataQualityAssessmentError(
                "Book source lineage does not match snapshot."
            )
        if previous_state is not None and (
            state.source_lineage[: len(previous_state.source_lineage)]
            != previous_state.source_lineage
            or state.market_data_ids[: len(previous_state.market_data_ids)]
            != previous_state.market_data_ids
            or len(state.source_lineage) != len(previous_state.source_lineage) + 1
            or len(state.market_data_ids) != len(previous_state.market_data_ids) + 1
        ):
            raise DataQualityAssessmentError(
                "Book transition lineage is not sequential."
            )
        if len(state.fingerprints) != len(state.source_lineage):
            raise DataQualityAssessmentError("Book fingerprint lineage is incomplete.")
        if (
            state.event_time != state.fingerprints[-1].event_time
            or state.sequence != state.fingerprints[-1].sequence_end
        ):
            raise DataQualityAssessmentError("Book state and sequence handoff differ.")
        declared = state.fingerprints[-1].checksum is not None
        if declared and transition.quality.checksum is not ChecksumStatus.VERIFIED:
            invalid_ids.append(str(observation.market_data_id))
            anomalies.append(f"checksum-unverified:{observation.market_data_id}")
        if not declared and transition.quality.checksum is ChecksumStatus.VERIFIED:
            raise DataQualityAssessmentError("Undeclared checksum cannot be verified.")
        if policy.require_checksum and (
            not declared or transition.quality.checksum is not ChecksumStatus.VERIFIED
        ):
            checksum_unavailable = True
        if transition.quality.extreme_spread is True:
            anomalies.append(f"extreme-spread:{observation.market_data_id}")
        expected_metrics = tuple(
            (
                f"{side}_{index}_{suffix}",
                level.price if suffix == "price" else level.quantity,
                state.policy.price_unit
                if suffix == "price"
                else state.policy.quantity_unit,
            )
            for side, levels in (("bid", state.bids), ("ask", state.asks))
            for index, level in enumerate(levels, start=1)
            for suffix in ("price", "quantity")
        )
        actual_metrics = tuple(
            (metric.metric_name, metric.value, metric.unit)
            for metric in observation.metrics
        )
        if actual_metrics != expected_metrics:
            invalid_ids.append(str(observation.market_data_id))
        if any(
            not isinstance(level.price, Decimal)
            or not level.price.is_finite()
            or level.price <= 0
            or not isinstance(level.quantity, Decimal)
            or not level.quantity.is_finite()
            or level.quantity <= 0
            for level in (*state.bids, *state.asks)
        ):
            invalid_ids.append(str(observation.market_data_id))
        observations.append(observation)
        sources.append(source)
        previous_state = state
    if dataset is not None:
        _validate_spot_dataset(snapshot, tuple(sources), dataset, policy)
    if mode == "delta" and len(observations) < 2:
        sequence_verified = False
        sequence_scope_valid = False
    else:
        sequence_verified = (
            len(observations) >= 2
            and all(
                item.sequence_start is not None and item.sequence_end is not None
                for item in previous_state.fingerprints
            )
            if previous_state is not None
            else False
        )
        sequence_scope_valid = sequence_verified
    if previous_state is not None and previous_state.status is BookStatus.VALID:
        sequence = previous_state.sequence
        if sequence is None and mode == "delta":
            sequence_verified = False
            sequence_scope_valid = False
        if len(previous_state.source_lineage) != len(observations):
            raise DataQualityAssessmentError(
                "Book state and snapshot membership differ."
            )
    if tuple(item.market_data_id for item in observations) != snapshot.market_data_ids:
        raise DataQualityAssessmentError("Book C-001 membership differs from C-002.")
    if tuple(item.source_record_id for item in sources) != snapshot.source_record_ids:
        raise DataQualityAssessmentError("Book C-091 membership differs from C-002.")
    if dataset is None and snapshot.dataset_version is not None:
        raise DataQualityAssessmentError(
            "Referenced C-092 dataset evidence is required."
        )
    if dataset is not None:
        _validate_spot_dataset(snapshot, tuple(sources), dataset, policy)
    point_applicable = point_policy and len(observations) == 1 and not terminal_invalid
    report = _spot_quality_report(
        snapshot,
        policy,
        assessed_at=assessed_at,
        observations=tuple(observations),
        sources=tuple(sources),
        dataset=dataset,
        sequence_verified=sequence_verified,
        sequence_scope_valid=sequence_scope_valid,
        duplicate_ids=tuple(duplicate_ids),
        anomalies=tuple(anomalies),
        invalid_ids=tuple(invalid_ids),
        stale_state=stale_state,
        checksum_unavailable=checksum_unavailable,
        point_snapshot=point_applicable,
    )
    return report
