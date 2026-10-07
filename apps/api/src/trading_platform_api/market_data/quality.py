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
from trading_platform_api.market_data.order_book import (
    BookFailure,
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
    unit: str | None = None

    def __post_init__(self) -> None:
        if (
            not self.name
            or self.name != self.name.strip()
            or type(self.minimum) is not Decimal
            or type(self.maximum) is not Decimal
            or not self.minimum.is_finite()
            or not self.maximum.is_finite()
            or self.minimum > self.maximum
            or (
                self.unit is not None
                and (
                    not isinstance(self.unit, str)
                    or not self.unit
                    or self.unit != self.unit.strip()
                )
            )
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
    interval_seconds: int | None
    freshness_seconds: int
    maximum_missing_intervals: int | None
    required_metrics: tuple[str, ...]
    metric_bounds: tuple[MetricBound, ...]
    require_independent_comparison: bool = False
    expected_record_count: int | None = None
    maximum_missing_records: int = 0
    provider_complete: bool = False
    provider_identity: tuple[str, str, str, str, str] | None = None
    expected_sequence_start: int | None = None
    expected_sequence_end: int | None = None

    def __post_init__(self) -> None:
        for name in ("policy_version", "instrument_id", "venue_id"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value or value != value.strip():
                raise DataQualityAssessmentError(f"{name} must be explicit.")
        if type(self.data_kind) is not ProviderDataKind or self.data_kind not in (
            ProviderDataKind.OHLCV,
            ProviderDataKind.TRADE,
            ProviderDataKind.TICK,
            ProviderDataKind.ORDER_BOOK,
        ):
            raise DataQualityAssessmentError(
                "This bounded assessor supports OHLCV, TRADE, TICK, or ORDER_BOOK."
            )
        if type(self.freshness_seconds) is not int or self.freshness_seconds <= 0:
            raise DataQualityAssessmentError("freshness_seconds must be positive.")
        if type(self.require_independent_comparison) is not bool:
            raise DataQualityAssessmentError("Comparator policy must be boolean.")
        cutoff = _utc("required_data_cutoff", self.required_data_cutoff)
        start = _utc("coverage_start", self.coverage_start)
        end = _utc("coverage_end", self.coverage_end)
        if not start < end <= cutoff:
            raise DataQualityAssessmentError("Invalid closed-history coverage window.")
        if type(self.required_metrics) is not tuple:
            raise DataQualityAssessmentError("Required metrics must be a tuple.")
        if self.data_kind is ProviderDataKind.OHLCV:
            window = (end - start).total_seconds()
            if (
                type(self.interval_seconds) is not int
                or self.interval_seconds <= 0
                or window % self.interval_seconds
                or not 2 <= window / self.interval_seconds <= 10000
            ):
                raise DataQualityAssessmentError(
                    "Coverage must have 2–10000 exact slots."
                )
            if (
                type(self.maximum_missing_intervals) is not int
                or self.maximum_missing_intervals < 0
            ):
                raise DataQualityAssessmentError("Invalid missing-interval allowance.")
            if not {"open", "high", "low", "close", "volume"}.issubset(
                self.required_metrics
            ):
                raise DataQualityAssessmentError("OHLCV metrics are required.")
        elif (
            self.interval_seconds is not None
            or self.maximum_missing_intervals is not None
        ):
            raise DataQualityAssessmentError(
                "Event and book policies must not use candle interval fields."
            )
        if (
            type(self.required_metrics) is not tuple
            or any(
                not isinstance(name, str) or not name or name != name.strip()
                for name in self.required_metrics
            )
            or len(self.required_metrics) != len(set(self.required_metrics))
            or (self.data_kind is ProviderDataKind.OHLCV and not self.required_metrics)
            or (
                self.data_kind in (ProviderDataKind.TRADE, ProviderDataKind.TICK)
                and not {"price"}.issubset(self.required_metrics)
            )
            or (
                self.data_kind is ProviderDataKind.TRADE
                and "quantity" not in self.required_metrics
            )
            or (
                self.data_kind is ProviderDataKind.ORDER_BOOK
                and not self.required_metrics
            )
        ):
            raise DataQualityAssessmentError(
                "Required metrics must be explicit and unique."
            )
        if (
            type(self.metric_bounds) is not tuple
            or not all(type(bound) is MetricBound for bound in self.metric_bounds)
            or {bound.name for bound in self.metric_bounds}
            != set(self.required_metrics)
            or len(self.metric_bounds) != len(self.required_metrics)
        ):
            raise DataQualityAssessmentError("Every required metric needs a bound.")
        if self.data_kind is not ProviderDataKind.OHLCV and any(
            not bound.unit for bound in self.metric_bounds
        ):
            raise DataQualityAssessmentError(
                "Every event/book metric bound must declare a unit."
            )
        if self.data_kind is not ProviderDataKind.OHLCV:
            if self.expected_record_count is not None and (
                type(self.expected_record_count) is not int
                or not 1 <= self.expected_record_count <= 10000
            ):
                raise DataQualityAssessmentError("Invalid expected record count.")
            if (
                type(self.maximum_missing_records) is not int
                or self.maximum_missing_records < 0
                or type(self.provider_complete) is not bool
                or (self.expected_record_count is None and not self.provider_complete)
            ):
                raise DataQualityAssessmentError(
                    "Expected record count or provider completeness is required."
                )
            if (
                self.provider_identity is None
                or type(self.provider_identity) is not tuple
                or len(self.provider_identity) != 5
                or any(
                    not isinstance(value, str) or not value or value != value.strip()
                    for value in self.provider_identity
                )
            ):
                raise DataQualityAssessmentError(
                    "Exact provider identity is required for event/book data."
                )
            if (self.expected_sequence_start is None) != (
                self.expected_sequence_end is None
            ) or (
                self.expected_sequence_start is not None
                and (
                    type(self.expected_sequence_start) is not int
                    or type(self.expected_sequence_end) is not int
                    or self.expected_sequence_start < 0
                    or self.expected_sequence_end < self.expected_sequence_start
                )
            ):
                raise DataQualityAssessmentError("Invalid expected sequence range.")
            if (
                self.expected_sequence_start is not None
                and self.expected_record_count is not None
                and self.data_kind in (ProviderDataKind.TRADE, ProviderDataKind.TICK)
                and self.expected_sequence_end is not None
                and self.expected_sequence_end - self.expected_sequence_start + 1
                != self.expected_record_count
            ):
                raise DataQualityAssessmentError(
                    "Expected sequence range must match expected record count."
                )
            if self.data_kind is ProviderDataKind.ORDER_BOOK and (
                self.expected_sequence_start is None
                or self.expected_sequence_end is None
                or self.expected_sequence_start >= self.expected_sequence_end
            ):
                raise DataQualityAssessmentError(
                    "Order-book policy requires an explicit delta sequence window."
                )
        object.__setattr__(self, "required_data_cutoff", cutoff)
        object.__setattr__(self, "coverage_start", start)
        object.__setattr__(self, "coverage_end", end)


def _assess_event_or_book_quality(
    snapshot: MarketSnapshot,
    observations: tuple[MarketData, ...],
    sources: tuple[DataSourceRecord, ...],
    policy: DataQualityPolicy,
    *,
    assessed_at: datetime,
    dataset: DatasetVersion | None,
    trade_ticks: NormalizedTradeTicks | None,
    book_transitions: tuple[BookTransition, ...] | None,
) -> DataQualityReport:
    """Use explicit event counts and sequence evidence, never candle slots.

    For each modality, completeness is present required metric cells over
    expected cells, freshness is fresh records over supplied records, accuracy
    is in-bound records over supplied records, consistency is correctly linked
    and ordered records over supplied records, source reliability is exact C-091
    links over supplied records, coverage is supplied records over expected
    records, and continuity is verified adjacent sequences over expected
    transitions.
    """
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
            "Finite observations and exact source records are required."
        )
    observation_ids = tuple(item.market_data_id for item in observations)
    source_ids = tuple(item.source_record_id for item in sources)
    if (
        len(set(observation_ids)) != len(observation_ids)
        or len(set(source_ids)) != len(source_ids)
        or set(snapshot.market_data_ids) != set(observation_ids)
        or len(snapshot.market_data_ids) != len(observation_ids)
        or set(snapshot.source_record_ids) != set(source_ids)
        or len(snapshot.source_record_ids) != len(source_ids)
    ):
        raise DataQualityAssessmentError(
            "Snapshot must contain the exact assessed observations and sources."
        )
    if policy.require_independent_comparison:
        raise DataQualityAssessmentError(
            "Independent comparable source evidence was not supplied."
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

    expected = policy.expected_record_count or len(observations)
    if len(observations) > expected:
        raise DataQualityAssessmentError("Snapshot exceeds expected record coverage.")
    source_by_id = {source.source_record_id: source for source in sources}
    provider_identity = policy.provider_identity
    assert provider_identity is not None
    metric_bounds = {bound.name: bound for bound in policy.metric_bounds}
    missing_fields: list[str] = []
    invalid_ids: list[str] = []
    duplicate_ids: list[str] = []
    anomalies: list[str] = []
    complete_cells = 0
    accurate_count = 0
    consistent_count = 0
    reliable_count = 0
    fresh_count = 0
    previous_time: datetime | None = None
    for item in observations:
        label = str(item.market_data_id)
        metrics = {metric.metric_name: metric for metric in item.metrics}
        complete_cells += len(set(metrics) & set(policy.required_metrics))
        absent_metrics = set(policy.required_metrics) - set(metrics)
        missing_fields.extend(f"{label}:{name}" for name in sorted(absent_metrics))
        source = source_by_id.get(item.source_record_id)
        linked = (
            source is not None
            and item.instrument_id == policy.instrument_id
            and item.venue_id == policy.venue_id
            and item.observation_type == policy.data_kind.value
            and (
                source.provider_id,
                source.provider_version,
                source.raw_schema_version,
                source.adapter_version,
                source.licensing_reference,
            )
            == provider_identity
            and source.provider_event_time == item.event_time
            and source.availability_time <= cutoff
            and source.retrieval_time <= source.availability_time
            and item.event_time <= item.provider_time <= item.ingestion_time
            and item.ingestion_time <= item.availability_time <= cutoff
            and policy.coverage_start <= item.event_time < policy.coverage_end
            and (previous_time is None or item.event_time >= previous_time)
        )
        if linked:
            reliable_count += 1
            consistent_count += 1
            if cutoff - item.event_time <= timedelta(seconds=policy.freshness_seconds):
                fresh_count += 1
        else:
            invalid_ids.append(label)
        accurate = not absent_metrics
        for name in policy.required_metrics:
            metric = metrics.get(name)
            bound = metric_bounds[name]
            if metric is not None and (
                metric.unit != bound.unit
                or not bound.minimum <= metric.value <= bound.maximum
                or (
                    policy.data_kind
                    in (
                        ProviderDataKind.TRADE,
                        ProviderDataKind.TICK,
                        ProviderDataKind.ORDER_BOOK,
                    )
                    and name.endswith(("price", "quantity"))
                    and metric.value <= 0
                )
            ):
                accurate = False
                invalid_ids.append(label)
        if accurate:
            accurate_count += 1
        else:
            anomalies.append(label)
        previous_time = item.event_time
    if missing_fields:
        invalid_ids.extend(field.split(":", 1)[0] for field in missing_fields)
    if len(observations) < expected:
        missing_fields.append(f"missing-records:{expected - len(observations)}")
    if dataset is not None and set(dataset.source_record_ids) != set(source_ids):
        invalid_ids.append("dataset-source-mismatch")

    continuity_numerator = 0
    continuity_denominator = max(expected - 1, 1)
    if policy.data_kind in (ProviderDataKind.TRADE, ProviderDataKind.TICK):
        if (
            trade_ticks is None
            or type(trade_ticks) is not NormalizedTradeTicks
            or trade_ticks.data_kind is not policy.data_kind
            or trade_ticks.market_data != observations
            or trade_ticks.source_records != sources
            or len(trade_ticks.identities) != len(observations)
        ):
            raise DataQualityAssessmentError(
                "Exact normalized trade/tick identity and quality handoff is required."
            )
        for identity, item, source in zip(
            trade_ticks.identities, observations, sources
        ):
            if (
                identity.market_data_id != item.market_data_id
                or identity.source_record_id != item.source_record_id
                or identity.source_record_id != source.source_record_id
                or not identity.provider_event_id
            ):
                invalid_ids.append(str(item.market_data_id))
        event_ids = tuple(item.provider_event_id for item in trade_ticks.identities)
        duplicate_event_ids = {
            event_id for event_id in event_ids if event_ids.count(event_id) > 1
        }
        duplicate_ids.extend(sorted(duplicate_event_ids))
        duplicate_ids.extend(trade_ticks.quality.duplicate_event_ids)
        sequences = tuple(item.sequence for item in trade_ticks.identities)
        scopes = {item.sequence_scope for item in trade_ticks.identities}
        if any(value is None for value in sequences) and not all(
            value is None for value in sequences
        ):
            invalid_ids.append("mixed-sequence-availability")
        elif all(value is not None for value in sequences):
            numbers = tuple(value for value in sequences if value is not None)
            continuity_numerator = (
                1
                if expected == 1 and trade_ticks.quality.sequence_verified
                else sum(
                    current == previous + 1
                    for previous, current in zip(numbers, numbers[1:])
                )
            )
            if (
                len(scopes) != 1
                or continuity_numerator != len(numbers) - 1
                or not trade_ticks.quality.sequence_verified
            ):
                invalid_ids.append("sequence-gap-or-verification-mismatch")
            if policy.expected_sequence_start is not None and (
                numbers[0] != policy.expected_sequence_start
                or numbers[-1] != policy.expected_sequence_end
            ):
                invalid_ids.append("sequence-range-mismatch")
        else:
            if trade_ticks.quality.sequence_verified:
                invalid_ids.append("sequence-verification-handoff-mismatch")
            anomalies.append("sequence-unverified")
        if trade_ticks.quality.empty:
            raise DataQualityAssessmentError("Empty event batches cannot be assessed.")
        unknown_ids = set(trade_ticks.quality.unknown_aggressor_event_ids)
        if not unknown_ids.issubset(event_ids):
            invalid_ids.append("unknown-aggressor-identity-mismatch")
        for event_identity in trade_ticks.identities:
            unknown = (
                event_identity.side_semantics is not SideSemantics.AGGRESSOR
                or event_identity.reported_side is ReportedSide.UNKNOWN
            )
            if (
                unknown and event_identity.aggressor_side is not ReportedSide.UNKNOWN
            ) or (
                not unknown
                and event_identity.aggressor_side is not event_identity.reported_side
            ):
                invalid_ids.append(str(event_identity.market_data_id))
            if unknown:
                unknown_ids.add(event_identity.provider_event_id)
        if unknown_ids:
            anomalies.extend(
                f"unknown-aggressor:{event_id}" for event_id in sorted(unknown_ids)
            )
    else:
        if (
            trade_ticks is not None
            or type(book_transitions) is not tuple
            or not book_transitions
            or not all(type(item) is BookTransition for item in book_transitions)
        ):
            raise DataQualityAssessmentError(
                "Order-book assessment requires exact transition handoffs only."
            )
        book_state = book_transitions[-1].state
        if (
            type(book_state) is not BookState
            or book_state.policy.instrument_id != policy.instrument_id
            or book_state.policy.venue_id != policy.venue_id
            or book_state.provider_identity != provider_identity
            or book_state.market_data_ids != observation_ids
            or book_state.source_lineage != source_ids
            or book_state.policy.extreme_spread_bps is None
        ):
            raise DataQualityAssessmentError(
                "Order-book state, thresholds, and snapshot lineage must match."
            )
        if (
            not book_state.bids
            or not book_state.asks
            or book_state.bids[0].price >= book_state.asks[0].price
        ):
            invalid_ids.append("empty-locked-or-crossed-book")
        if book_state.status is BookStatus.INVALID:
            invalid_ids.append(
                f"book-state:{(book_state.failure or BookFailure.INVALID_INPUT).value}"
            )
        if any(item.state.status is not BookStatus.VALID for item in book_transitions):
            invalid_ids.append("invalid-book-transition-state")
        canonical_transitions = tuple(
            item
            for item in book_transitions
            if item.market_data is not None or item.source_record is not None
        )
        duplicate_transitions = tuple(
            item for item in book_transitions if item.quality.duplicate
        )
        duplicate_ids.extend(
            item.state.fingerprints[-1].event_id
            for item in duplicate_transitions
            if item.state.fingerprints
        )
        if len(canonical_transitions) != len(observations):
            raise DataQualityAssessmentError(
                "Every snapshot book observation needs its matching transition."
            )
        fingerprints = book_state.fingerprints
        if len(fingerprints) != len(observations):
            raise DataQualityAssessmentError(
                "Book state fingerprints must cover the exact snapshot observations."
            )
        for index, (transition, item, source) in enumerate(
            zip(canonical_transitions, observations, sources)
        ):
            if (
                transition.market_data is None
                or transition.source_record is None
                or transition.market_data != item
                or transition.source_record != source
                or transition.state.market_data_ids != observation_ids[: index + 1]
                or transition.state.source_lineage != source_ids[: index + 1]
            ):
                invalid_ids.append(str(item.market_data_id))
            elif not _book_metrics_match(transition):
                invalid_ids.append(str(item.market_data_id))
            fingerprint = fingerprints[index]
            checksum_status = transition.quality.checksum
            if fingerprint.checksum is None:
                if checksum_status is not ChecksumStatus.NOT_AVAILABLE:
                    invalid_ids.append(str(item.market_data_id))
                else:
                    anomalies.append(f"checksum-not-available:{item.market_data_id}")
            elif checksum_status is not ChecksumStatus.VERIFIED:
                invalid_ids.append(str(item.market_data_id))
            if transition.quality.extreme_spread is True:
                anomalies.append(f"extreme-spread:{item.market_data_id}")
        fingerprints = book_state.fingerprints
        first, last = fingerprints[0], fingerprints[-1]
        if (
            len(fingerprints) > 1
            and first.sequence_end is not None
            and last.sequence_end is not None
            and book_state.sequence == last.sequence_end
            and all(
                current.sequence_start is not None
                and current.sequence_end is not None
                and previous.sequence_end is not None
                and current.sequence_start <= previous.sequence_end + 1
                and current.sequence_end > previous.sequence_end
                for previous, current in zip(fingerprints, fingerprints[1:])
            )
            and book_state.status is BookStatus.VALID
        ):
            continuity_numerator = len(fingerprints) - 1
            if (
                first.sequence_end != policy.expected_sequence_start
                or last.sequence_end != policy.expected_sequence_end
            ):
                invalid_ids.append("book-sequence-range-mismatch")
        else:
            anomalies.append("book-delta-continuity-unverified")

    denominator = expected * len(policy.required_metrics)
    completeness = _ratio(complete_cells, denominator)
    freshness = _ratio(fresh_count, len(observations))
    accuracy = _ratio(accurate_count, len(observations))
    consistency = _ratio(consistent_count, len(observations))
    source_reliability = _ratio(reliable_count, len(observations))
    coverage = _ratio(len(observations), expected)
    continuity = _ratio(continuity_numerator, continuity_denominator)
    if invalid_ids or duplicate_ids:
        status = DataQualityStatus.INVALID
    elif reliable_count < len(observations):
        status = DataQualityStatus.UNAVAILABLE
    elif fresh_count < len(observations):
        status = DataQualityStatus.STALE
    elif expected - len(observations) > policy.maximum_missing_records:
        status = DataQualityStatus.INCOMPLETE
    elif (
        len(observations) < expected
        or anomalies
        or continuity_numerator < continuity_denominator
    ):
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


def _book_metrics_match(transition: BookTransition) -> bool:
    if transition.market_data is None:
        return False
    expected: dict[str, tuple[Decimal, str]] = {}
    for side_name, levels in (
        ("bid", transition.state.bids),
        ("ask", transition.state.asks),
    ):
        for index, level in enumerate(levels, start=1):
            expected[f"{side_name}_{index}_price"] = (
                level.price,
                transition.state.policy.price_unit,
            )
            expected[f"{side_name}_{index}_quantity"] = (
                level.quantity,
                transition.state.policy.quantity_unit,
            )
    supplied = {
        metric.metric_name: (metric.value, metric.unit)
        for metric in transition.market_data.metrics
    }
    return supplied == expected


def assess_data_quality(
    snapshot: MarketSnapshot,
    observations: tuple[MarketData, ...],
    sources: tuple[DataSourceRecord, ...],
    policy: DataQualityPolicy,
    *,
    assessed_at: datetime,
    finalized_market_data_ids: tuple[UUID, ...] | None = None,
    dataset: DatasetVersion | None = None,
    trade_ticks: NormalizedTradeTicks | None = None,
    book_transitions: tuple[BookTransition, ...] | None = None,
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
    if policy.data_kind is not ProviderDataKind.OHLCV:
        if finalized_market_data_ids is not None:
            raise DataQualityAssessmentError(
                "Candle finality evidence is not valid for event/book data."
            )
        return _assess_event_or_book_quality(
            snapshot,
            observations,
            sources,
            policy,
            assessed_at=assessed_at,
            dataset=dataset,
            trade_ticks=trade_ticks,
            book_transitions=book_transitions,
        )
    if trade_ticks is not None or book_transitions is not None:
        raise DataQualityAssessmentError(
            "Non-OHLCV handoffs cannot be used with a candle policy."
        )
    if policy.interval_seconds is None or policy.maximum_missing_intervals is None:
        raise DataQualityAssessmentError("OHLCV interval policy is incomplete.")
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
