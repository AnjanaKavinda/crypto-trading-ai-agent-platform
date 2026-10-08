"""Deterministic, analysis-only Spot order-flow calculations."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import ROUND_HALF_EVEN, Decimal, localcontext
from typing import Mapping
from uuid import UUID

from trading_platform_api.analysis.contracts import (
    ClaimClassification,
    EvidenceRelation,
    VersionReference,
)
from trading_platform_api.analysis.versioned_contracts import (
    AnalysisSnapshotV2,
    AnalysisV2ContractError,
    EvidenceItemV2,
    InputModality,
    OrderFlowAssessment,
    OrderFlowAssessmentState,
    OrderFlowMetric,
    OrderFlowMetricName,
    OrderFlowMetricState,
    ResolvedInputBinding,
    resolve_analysis_snapshot_v2,
)
from trading_platform_api.market_data.contracts import (
    DataQualityDimension,
    DataQualityDimensionState,
    DataQualityReportV2,
    DataQualityStatus,
    DatasetVersion,
    DataSourceRecord,
    MarketData,
    MarketSnapshot,
    MetricValue,
)
from trading_platform_api.market_data.order_book import (
    BookFingerprint,
    BookLevel,
    BookPolicy,
    BookQuality,
    BookState,
    BookStatus,
    BookTransition,
    ChecksumStatus,
)
from trading_platform_api.market_data.providers import ProviderDataKind
from trading_platform_api.market_data.trades import (
    NormalizedTradeTicks,
    ReportedSide,
    SideSemantics,
    TradeTickIdentity,
    TradeTickQuality,
)


SPOT_ORDER_FLOW_METHOD = VersionReference("spot-order-flow", "1")
_BASE_DIMENSIONS = (
    DataQualityDimension.COMPLETENESS,
    DataQualityDimension.FRESHNESS,
    DataQualityDimension.ACCURACY,
    DataQualityDimension.CONSISTENCY,
    DataQualityDimension.SOURCE_RELIABILITY,
    DataQualityDimension.COVERAGE,
)
_BOOK_METRICS = frozenset(
    {
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
_DIRECTIONAL_METRICS = frozenset(
    {
        OrderFlowMetricName.BUY_AGGRESSOR_VOLUME,
        OrderFlowMetricName.SELL_AGGRESSOR_VOLUME,
        OrderFlowMetricName.VOLUME_DELTA,
        OrderFlowMetricName.CUMULATIVE_DELTA,
    }
)


class SpotOrderFlowError(ValueError):
    """Sanitized invalid-input failure for the bounded Spot analysis."""


@dataclass(frozen=True, slots=True)
class SpotOrderFlowPolicy:
    """Explicit units and displayed depth used by this calculation version."""

    base_unit: str
    quote_unit: str
    depth_levels: int

    def __post_init__(self) -> None:
        for name in ("base_unit", "quote_unit"):
            value = getattr(self, name)
            if (
                not isinstance(value, str)
                or not value
                or value != value.strip()
                or len(value) > 255
            ):
                raise SpotOrderFlowError(f"{name} must be an explicit unit.")
        if self.base_unit == self.quote_unit:
            raise SpotOrderFlowError("base_unit and quote_unit must be distinct.")
        if type(self.depth_levels) is not int or not 1 <= self.depth_levels <= 100:
            raise SpotOrderFlowError("depth_levels must be an integer in [1, 100].")


@dataclass(frozen=True, slots=True)
class SpotOrderFlowResult:
    assessment: OrderFlowAssessment
    evidence: tuple[EvidenceItemV2, ...]


def _metric_map(observation: MarketData) -> dict[str, MetricValue]:
    result = {item.metric_name: item for item in observation.metrics}
    if len(result) != len(observation.metrics):
        raise SpotOrderFlowError("Normalized observation has duplicate metrics.")
    return result


def _dimension_passes(
    item: ResolvedInputBinding, required: tuple[DataQualityDimension, ...]
) -> bool:
    report = item.report
    policy = item.policy
    expected = policy.expected_record_count
    if (
        report.status not in {DataQualityStatus.VALID, DataQualityStatus.DEGRADED}
        or expected is None
        or expected != len(item.observations)
        or not item.direct_inputs_pass
        or policy.require_independent_comparison
        or policy.require_checksum
    ):
        return False
    results = {result.dimension: result for result in report.dimensions}
    for dimension in required:
        result = results[dimension]
        if (
            result.state is not DataQualityDimensionState.MEASURED
            or result.numerator is None
            or result.denominator is None
            or result.score != Decimal("1")
            or result.numerator != result.denominator
        ):
            return False
        expected_denominator = (
            expected * len(policy.metric_rules)
            if dimension is DataQualityDimension.COMPLETENESS
            else policy.expected_transition_count
            if dimension is DataQualityDimension.CONTINUITY
            else expected
        )
        expected_unit = {
            DataQualityDimension.COMPLETENESS: "metric_cells",
            DataQualityDimension.FRESHNESS: "observations",
            DataQualityDimension.ACCURACY: "observations",
            DataQualityDimension.CONSISTENCY: "observations",
            DataQualityDimension.SOURCE_RELIABILITY: "source_records",
            DataQualityDimension.COVERAGE: "observations",
            DataQualityDimension.CONTINUITY: "sequence_transitions",
        }[dimension]
        if (
            expected_denominator is None
            or result.denominator != expected_denominator
            or result.basis_unit != expected_unit
        ):
            return False
    return True


def _validate_trade_handoff(
    item: ResolvedInputBinding,
    normalized: NormalizedTradeTicks,
    policy: SpotOrderFlowPolicy,
) -> tuple[TradeTickIdentity, ...]:
    if (
        type(normalized) is not NormalizedTradeTicks
        or normalized.data_kind is not ProviderDataKind.TRADE
        or type(normalized.quality) is not TradeTickQuality
        or type(normalized.market_data) is not tuple
        or type(normalized.source_records) is not tuple
        or type(normalized.identities) is not tuple
        or normalized.quality.empty
        or len(normalized.market_data) != len(normalized.source_records)
        or len(normalized.market_data) != len(normalized.identities)
        or normalized.market_data != item.observations
        or normalized.source_records != item.sources
        or item.binding.modality is not InputModality.SPOT_TRADES
        or item.policy.data_kind is not ProviderDataKind.TRADE
        or tuple(rule.name for rule in item.policy.metric_rules)
        != ("price", "quantity")
        or item.policy.metric_rules[0].unit != policy.quote_unit
        or item.policy.metric_rules[1].unit != policy.base_unit
    ):
        raise SpotOrderFlowError("Exact normalized TRADE handoff is required.")

    identities = normalized.identities
    unknown_ids: list[str] = []
    has_sequence: bool | None = None
    previous_sequence: int | None = None
    sequence_scope: str | None = None
    for identity, observation in zip(identities, normalized.market_data):
        if (
            type(identity) is not TradeTickIdentity
            or type(identity.market_data_id) is not UUID
            or type(identity.source_record_id) is not UUID
            or type(identity.provider_event_id) is not str
            or not identity.provider_event_id
            or identity.provider_event_id != identity.provider_event_id.strip()
            or identity.market_data_id != observation.market_data_id
            or identity.source_record_id != observation.source_record_id
            or observation.observation_type != ProviderDataKind.TRADE.value
            or observation.instrument_id != item.binding.instrument_id
            or observation.venue_id != item.binding.venue_id
            or type(identity.reported_side) is not ReportedSide
            or type(identity.side_semantics) is not SideSemantics
            or type(identity.aggressor_side) is not ReportedSide
            or identity.aggressor_side
            is not (
                identity.reported_side
                if identity.side_semantics is SideSemantics.AGGRESSOR
                else ReportedSide.UNKNOWN
            )
        ):
            raise SpotOrderFlowError("TRADE identity does not match normalized data.")
        metrics = _metric_map(observation)
        price = metrics.get("price")
        quantity = metrics.get("quantity")
        if (
            price is None
            or quantity is None
            or price.unit != item.policy.metric_rules[0].unit
            or quantity.unit != item.policy.metric_rules[1].unit
            or price.value <= 0
            or quantity.value <= 0
        ):
            raise SpotOrderFlowError("TRADE price/quantity units or values mismatch.")
        signed = metrics.get("aggressor_sign")
        if identity.aggressor_side is ReportedSide.UNKNOWN:
            unknown_ids.append(identity.provider_event_id)
            if signed is not None:
                raise SpotOrderFlowError("Unknown aggressor side has a signed metric.")
        else:
            expected_sign = (
                Decimal("1")
                if identity.aggressor_side is ReportedSide.BUY
                else Decimal("-1")
            )
            if signed is None or signed.unit != "sign" or signed.value != expected_sign:
                raise SpotOrderFlowError("Aggressor sign does not match side evidence.")
        if identity.sequence is not None and (
            type(identity.sequence) is not int or identity.sequence < 0
        ):
            raise SpotOrderFlowError("Invalid TRADE sequence.")
        if (identity.sequence is None) != (identity.sequence_scope is None):
            raise SpotOrderFlowError("TRADE sequence and scope must be paired.")
        if identity.sequence_scope is not None:
            if (
                type(identity.sequence_scope) is not str
                or not identity.sequence_scope
                or identity.sequence_scope != identity.sequence_scope.strip()
            ):
                raise SpotOrderFlowError("Invalid TRADE sequence scope.")
            if sequence_scope is not None and identity.sequence_scope != sequence_scope:
                raise SpotOrderFlowError("Mixed TRADE sequence scopes.")
            sequence_scope = identity.sequence_scope
        if has_sequence is not None and (identity.sequence is not None) != has_sequence:
            raise SpotOrderFlowError("Mixed sequenced and unsequenced TRADE records.")
        has_sequence = identity.sequence is not None
        if identity.sequence is not None:
            if (
                previous_sequence is not None
                and identity.sequence != previous_sequence + 1
            ):
                raise SpotOrderFlowError("TRADE sequence has a gap or reversal.")
            previous_sequence = identity.sequence

    if (
        type(normalized.quality.empty) is not bool
        or normalized.quality.empty
        or type(normalized.quality.unknown_aggressor_event_ids) is not tuple
        or normalized.quality.unknown_aggressor_event_ids != tuple(unknown_ids)
        or type(normalized.quality.duplicate_event_ids) is not tuple
        or normalized.quality.duplicate_event_ids
        or type(normalized.quality.sequence_verified) is not bool
        or normalized.quality.sequence_verified is not bool(has_sequence)
    ):
        raise SpotOrderFlowError("TRADE quality handoff does not match its records.")
    return identities


def _validate_point_book(
    item: ResolvedInputBinding,
    transitions: tuple[BookTransition, ...],
    policy: SpotOrderFlowPolicy,
) -> BookState:
    if (
        type(transitions) is not tuple
        or len(transitions) != 1
        or type(transitions[0]) is not BookTransition
    ):
        raise SpotOrderFlowError("One normalized point-book transition is required.")
    transition = transitions[0]
    state = transition.state
    if (
        type(state) is not BookState
        or state.status is not BookStatus.VALID
        or type(state.policy) is not BookPolicy
        or type(transition.quality) is not BookQuality
        or type(transition.quality.checksum) is not ChecksumStatus
        or transition.quality.checksum is ChecksumStatus.FAILED
        or type(transition.quality.duplicate) is not bool
        or transition.quality.duplicate
        or (
            transition.quality.extreme_spread is not None
            and type(transition.quality.extreme_spread) is not bool
        )
        or transition.market_data is None
        or transition.source_record is None
        or len(item.observations) != 1
        or len(item.sources) != 1
        or transition.market_data != item.observations[0]
        or transition.source_record != item.sources[0]
        or state.instrument_id != item.binding.instrument_id
        or state.venue_id != item.binding.venue_id
        or state.policy.instrument_id != item.binding.instrument_id
        or state.policy.venue_id != item.binding.venue_id
        or state.policy.price_unit != policy.quote_unit
        or state.policy.quantity_unit != policy.base_unit
        or type(state.bids) is not tuple
        or type(state.asks) is not tuple
        or len(state.bids) > state.policy.maximum_depth
        or len(state.asks) > state.policy.maximum_depth
        or state.source_lineage != (item.sources[0].source_record_id,)
        or state.market_data_ids != (item.observations[0].market_data_id,)
        or state.event_time != item.observations[0].event_time
        or type(state.fingerprints) is not tuple
        or len(state.fingerprints) != 1
        or type(state.fingerprints[0]) is not BookFingerprint
        or state.fingerprints[0].event_time != state.event_time
        or state.fingerprints[0].digest != item.sources[0].content_sha256
        or state.fingerprints[0].sequence_start != state.sequence
        or state.fingerprints[0].sequence_end != state.sequence
        or state.provider_identity
        != (
            item.sources[0].provider_id,
            item.sources[0].provider_version,
            item.sources[0].raw_schema_version,
            item.sources[0].adapter_version,
            item.sources[0].licensing_reference,
        )
        or item.binding.modality is not InputModality.ORDER_BOOK
        or item.policy.data_kind is not ProviderDataKind.ORDER_BOOK
        or not item.policy.assessment_policy_id.startswith("spot-order-book-point")
        or item.policy.expected_record_count != 1
    ):
        raise SpotOrderFlowError("Exact normalized point-book handoff is required.")
    if (
        not state.bids
        or not state.asks
        or not all(type(value) is BookLevel for value in (*state.bids, *state.asks))
    ):
        raise SpotOrderFlowError("Point book requires bid and ask levels.")
    if (
        state.bids[0].price <= 0
        or state.asks[0].price <= state.bids[0].price
        or any(
            type(level.price) is not Decimal
            or type(level.quantity) is not Decimal
            or not level.price.is_finite()
            or not level.quantity.is_finite()
            or level.price <= 0
            or level.quantity <= 0
            for level in (*state.bids, *state.asks)
        )
        or tuple(level.price for level in state.bids)
        != tuple(sorted((level.price for level in state.bids), reverse=True))
        or tuple(level.price for level in state.asks)
        != tuple(sorted(level.price for level in state.asks))
    ):
        raise SpotOrderFlowError("Invalid or crossed normalized point book.")

    metrics = _metric_map(item.observations[0])
    for side, levels in (("bid", state.bids), ("ask", state.asks)):
        for index, level in enumerate(levels, start=1):
            price = metrics.get(f"{side}_{index}_price")
            quantity = metrics.get(f"{side}_{index}_quantity")
            if (
                price is None
                or quantity is None
                or price.value != level.price
                or quantity.value != level.quantity
                or price.unit != policy.quote_unit
                or quantity.unit != policy.base_unit
            ):
                raise SpotOrderFlowError("Book levels do not match C-001 handoff.")
    return state


def _limitations(item: ResolvedInputBinding, depth_levels: int) -> tuple[str, ...]:
    report = item.report
    findings = tuple(
        dict.fromkeys(
            (
                *report.missing_fields,
                *report.invalid_record_ids,
                *report.duplicate_record_ids,
                *report.anomalies,
                *report.source_conflicts,
            )
        )
    )
    if item.binding.modality is InputModality.ORDER_BOOK:
        return (*findings, f"configured displayed depth uses top {depth_levels} levels")
    return findings


def _quality_failure_reason(
    item: ResolvedInputBinding, required: tuple[DataQualityDimension, ...]
) -> str:
    failed: list[str] = []
    results = {value.dimension: value for value in item.report.dimensions}
    expected_count = item.policy.expected_record_count
    for dimension in required:
        result = results[dimension]
        if result.state is not DataQualityDimensionState.MEASURED:
            reason = "" if result.reason_code is None else f" ({result.reason_code.value})"
            failed.append(f"{dimension.value}={result.state.value}{reason}")
            continue
        expected_denominator = (
            expected_count * len(item.policy.metric_rules)
            if dimension is DataQualityDimension.COMPLETENESS
            and expected_count is not None
            else item.policy.expected_transition_count
            if dimension is DataQualityDimension.CONTINUITY
            else expected_count
        )
        expected_unit = {
            DataQualityDimension.COMPLETENESS: "metric_cells",
            DataQualityDimension.FRESHNESS: "observations",
            DataQualityDimension.ACCURACY: "observations",
            DataQualityDimension.CONSISTENCY: "observations",
            DataQualityDimension.SOURCE_RELIABILITY: "source_records",
            DataQualityDimension.COVERAGE: "observations",
            DataQualityDimension.CONTINUITY: "sequence_transitions",
        }[dimension]
        if (
            result.numerator != result.denominator
            or result.score != Decimal("1")
            or result.denominator != expected_denominator
            or result.basis_unit != expected_unit
        ):
            failed.append(f"{dimension.value}=NOT_PASSING_OR_DENOMINATOR_MISMATCH")
    if item.report.status not in {DataQualityStatus.VALID, DataQualityStatus.DEGRADED}:
        failed.insert(0, f"report-status={item.report.status.value}")
    if not failed:
        return "Required C-003 policy or direct-input gates are not passing."
    return "Required C-003 evidence is not passing: " + ", ".join(failed) + "."


def _build_evidence(
    item: ResolvedInputBinding,
    evidence_id: UUID,
    *,
    depth_levels: int,
    expires_at: datetime,
    usable: bool,
) -> EvidenceItemV2 | None:
    source_reliability = next(
        (
            value
            for value in item.report.dimensions
            if value.dimension is DataQualityDimension.SOURCE_RELIABILITY
        ),
        None,
    )
    if (
        source_reliability is None
        or source_reliability.state is not DataQualityDimensionState.MEASURED
        or source_reliability.score is None
        or not item.sources
        or not item.observations
    ):
        return None
    observed_at = max(value.event_time for value in item.observations)
    available_at = max(
        (
            *(value.availability_time for value in item.observations),
            *(value.availability_time for value in item.sources),
        )
    )
    evidence_expiry = min(item.dependency_expires_at, expires_at)
    modality = item.binding.modality
    kind = (
        "normalized point ORDER_BOOK"
        if modality is InputModality.ORDER_BOOK
        else "normalized spot TRADE"
    )
    return EvidenceItemV2(
        evidence_id=evidence_id,
        binding_ids=(item.binding.binding_id,),
        observation_ids=tuple(value.market_data_id for value in item.observations),
        source_record_ids=tuple(value.source_record_id for value in item.observations),
        dataset_versions=(
            ()
            if item.dataset is None
            else ((item.dataset.dataset_id, item.dataset.version),)
        ),
        feature_ids=(),
        classification=ClaimClassification.FACT,
        relation=EvidenceRelation.SUPPORTING,
        observed_at=observed_at,
        available_at=available_at,
        expires_at=evidence_expiry,
        method=SPOT_ORDER_FLOW_METHOD,
        value=f"{len(item.observations)} normalized records",
        unit=None,
        interpretation=(
            f"Exact {kind} input provenance; deterministic calculations use "
            "method spot-order-flow-v1"
            + (
                f" and configured top-{depth_levels} displayed levels."
                if modality is InputModality.ORDER_BOOK
                else "."
            )
            + " This evidence is not a trade decision."
        ),
        quality_status=item.report.status,
        reliability=source_reliability.score,
        limitations=_limitations(item, depth_levels),
        provenance=(
            VersionReference("normalized-handoff", "1"),
            VersionReference(
                "C-003-policy",
                f"{item.report.assessment_policy_id}@{item.report.assessment_policy_version}",
            ),
        ),
        usable=usable,
    )


def _unit(name: OrderFlowMetricName, policy: SpotOrderFlowPolicy) -> str:
    if name in {
        OrderFlowMetricName.BEST_BID_PRICE,
        OrderFlowMetricName.BEST_ASK_PRICE,
        OrderFlowMetricName.MIDPOINT_PRICE,
        OrderFlowMetricName.ABSOLUTE_SPREAD,
        OrderFlowMetricName.BID_NOTIONAL,
        OrderFlowMetricName.ASK_NOTIONAL,
    }:
        return policy.quote_unit
    if name in {
        OrderFlowMetricName.BID_DEPTH,
        OrderFlowMetricName.ASK_DEPTH,
        OrderFlowMetricName.BUY_AGGRESSOR_VOLUME,
        OrderFlowMetricName.SELL_AGGRESSOR_VOLUME,
        OrderFlowMetricName.VOLUME_DELTA,
        OrderFlowMetricName.CUMULATIVE_DELTA,
    }:
        return policy.base_unit
    if name is OrderFlowMetricName.SPREAD_BPS:
        return "bps"
    if name is OrderFlowMetricName.BOOK_IMBALANCE:
        return "ratio"
    return "trades"


def calculate_spot_order_flow(
    manifest: AnalysisSnapshotV2,
    *,
    trade_handoff: NormalizedTradeTicks | None,
    book_handoff: tuple[BookTransition, ...] | None,
    snapshots: Mapping[UUID, MarketSnapshot],
    reports: Mapping[UUID, DataQualityReportV2],
    datasets: Mapping[tuple[str, str], DatasetVersion] | None = None,
    policy: SpotOrderFlowPolicy,
    assessment_id: UUID,
    evidence_ids: Mapping[InputModality, UUID],
    calculated_at: datetime,
    validated_at: datetime,
) -> SpotOrderFlowResult:
    """Calculate order-flow metrics from exact resolved Spot handoffs.

    Only normalized TRADE records and one normalized point ORDER_BOOK snapshot
    are supported. No side is inferred, and no metric is a signal or execution
    instruction. Cumulative delta starts at the first explicitly bound trade;
    it never imports a hidden carry-in.
    """
    if (
        type(manifest) is not AnalysisSnapshotV2
        or type(policy) is not SpotOrderFlowPolicy
        or not isinstance(snapshots, Mapping)
        or not isinstance(reports, Mapping)
        or not isinstance(evidence_ids, Mapping)
    ):
        raise SpotOrderFlowError("Exact manifest, policy, snapshots, and reports required.")
    if not isinstance(assessment_id, UUID):
        raise SpotOrderFlowError("assessment_id must be a UUID.")
    if (
        not isinstance(calculated_at, datetime)
        or calculated_at.tzinfo is None
        or calculated_at.utcoffset() is None
        or not isinstance(validated_at, datetime)
        or validated_at.tzinfo is None
        or validated_at.utcoffset() is None
    ):
        raise SpotOrderFlowError("calculated_at and validated_at must be timezone-aware.")
    calculation_time = calculated_at.astimezone(manifest.analysis_cutoff.tzinfo)
    by_modality: dict[InputModality, ResolvedInputBinding] = {}
    manifest_bindings = {item.modality: item for item in manifest.bindings}
    if len(manifest_bindings) != len(manifest.bindings):
        raise SpotOrderFlowError("Only one binding per Spot modality is supported.")
    for modality in manifest_bindings:
        if modality not in {
            InputModality.SPOT_TRADES,
            InputModality.ORDER_BOOK,
        }:
            raise SpotOrderFlowError("This slice supports only TRADE and point-book inputs.")
    if (trade_handoff is None) != (InputModality.SPOT_TRADES not in manifest_bindings):
        raise SpotOrderFlowError("TRADE handoff presence must match the C-007 manifest.")
    if (book_handoff is None) != (InputModality.ORDER_BOOK not in manifest_bindings):
        raise SpotOrderFlowError("Book handoff presence must match the C-007 manifest.")
    if any(
        type(key) is not InputModality or type(value) is not UUID
        for key, value in evidence_ids.items()
    ) or not set(evidence_ids).issubset(set(manifest_bindings)):
        raise SpotOrderFlowError("Evidence IDs must reference bound modalities.")
    if (
        assessment_id not in manifest.assessment_ids
        or len(set(evidence_ids.values())) != len(evidence_ids)
    ):
        raise SpotOrderFlowError("Assessment identity must be predeclared in C-007.")

    observations: dict[UUID, MarketData] = {}
    sources = {}
    if trade_handoff is not None:
        if (
            type(trade_handoff) is not NormalizedTradeTicks
            or trade_handoff.data_kind is not ProviderDataKind.TRADE
            or type(trade_handoff.market_data) is not tuple
            or type(trade_handoff.source_records) is not tuple
            or type(trade_handoff.identities) is not tuple
            or type(trade_handoff.quality) is not TradeTickQuality
            or not trade_handoff.market_data
            or len(trade_handoff.market_data) != len(trade_handoff.source_records)
            or len(trade_handoff.market_data) != len(trade_handoff.identities)
            or not all(type(value) is MarketData for value in trade_handoff.market_data)
            or not all(
                type(value) is DataSourceRecord for value in trade_handoff.source_records
            )
        ):
            raise SpotOrderFlowError("Exact normalized TRADE handoff is required.")
        for observation in trade_handoff.market_data:
            if observation.market_data_id in observations:
                raise SpotOrderFlowError("Duplicate TRADE observation identity.")
            observations[observation.market_data_id] = observation
        for source in trade_handoff.source_records:
            if source.source_record_id in sources:
                raise SpotOrderFlowError("Duplicate TRADE source identity.")
            sources[source.source_record_id] = source
    if book_handoff is not None:
        if (
            type(book_handoff) is not tuple
            or len(book_handoff) != 1
            or type(book_handoff[0]) is not BookTransition
            or book_handoff[0].market_data is None
            or book_handoff[0].source_record is None
            or type(book_handoff[0].market_data) is not MarketData
            or type(book_handoff[0].source_record) is not DataSourceRecord
        ):
            raise SpotOrderFlowError("One normalized point-book transition is required.")
        observation = book_handoff[0].market_data
        source = book_handoff[0].source_record
        if observation.market_data_id in observations or source.source_record_id in sources:
            raise SpotOrderFlowError("Duplicate order-book input identity.")
        observations[observation.market_data_id] = observation
        sources[source.source_record_id] = source
    try:
        resolved_bindings = resolve_analysis_snapshot_v2(
            manifest,
            now=validated_at,
            snapshots=snapshots,
            reports=reports,
            observations=observations,
            sources=sources,
            datasets=datasets,
        )
    except (AnalysisV2ContractError, ValueError, TypeError, KeyError) as exc:
        raise SpotOrderFlowError("C-007 input resolution failed closed.") from exc
    by_modality = {item.binding.modality: item for item in resolved_bindings}
    if any(
        item.snapshot.as_of != manifest.analysis_cutoff
        for item in resolved_bindings
    ):
        raise SpotOrderFlowError(
            "Every Spot modality snapshot must match the exact analysis cutoff."
        )
    trade_identities: tuple[TradeTickIdentity, ...] = ()
    trade_item = by_modality.get(InputModality.SPOT_TRADES)
    if trade_item is not None:
        assert trade_handoff is not None
        trade_identities = _validate_trade_handoff(trade_item, trade_handoff, policy)
    book_state: BookState | None = None
    book_item = by_modality.get(InputModality.ORDER_BOOK)
    if book_item is not None:
        assert book_handoff is not None
        book_state = _validate_point_book(book_item, book_handoff, policy)

    if not (
        calculation_time <= manifest.analysis_cutoff
        and calculation_time >= max(
            (item.snapshot.as_of for item in resolved_bindings),
            default=calculation_time,
        )
    ):
        raise SpotOrderFlowError("Calculation time is outside bound input cutoffs.")

    base_pass: dict[InputModality, bool] = {}
    for modality, item in by_modality.items():
        base_pass[modality] = _dimension_passes(item, _BASE_DIMENSIONS)
    evidence_by_modality: dict[InputModality, EvidenceItemV2] = {}
    for modality, item in by_modality.items():
        source_reliability_measured = any(
            result.dimension is DataQualityDimension.SOURCE_RELIABILITY
            and result.state is DataQualityDimensionState.MEASURED
            and result.score is not None
            for result in item.report.dimensions
        )
        if not source_reliability_measured:
            if modality in evidence_ids:
                raise SpotOrderFlowError(
                    "C-008 evidence reliability is unavailable; no numeric substitute is permitted."
                )
            continue
        if modality not in evidence_ids:
            raise SpotOrderFlowError(
                "A C-008 identity is required for measurable source reliability."
            )
        if evidence_ids[modality] not in manifest.evidence_ids:
            raise SpotOrderFlowError("C-008 evidence identity is not predeclared in C-007.")
        evidence = _build_evidence(
            item,
            evidence_ids[modality],
            depth_levels=policy.depth_levels,
            expires_at=manifest.expires_at,
            usable=base_pass[modality],
        )
        if evidence is not None:
            evidence_by_modality[modality] = evidence

    metric_values: dict[OrderFlowMetricName, tuple[Decimal | int, UUID, str]] = {}
    book_base_dimensions = _BASE_DIMENSIONS
    book_quality = (
        book_item is not None
        and base_pass.get(InputModality.ORDER_BOOK, False)
        and _dimension_passes(book_item, book_base_dimensions)
    )
    if book_state is not None and book_item is not None and book_quality:
        bids, asks = book_state.bids, book_state.asks
        evidence_id = evidence_ids[InputModality.ORDER_BOOK]
        bid = bids[0].price
        ask = asks[0].price
        with localcontext() as context:
            context.prec = 80
            midpoint = (bid + ask) / Decimal("2")
            spread = ask - bid
            bid_levels = bids[: policy.depth_levels]
            ask_levels = asks[: policy.depth_levels]
            depth_available = (
                len(bid_levels) == policy.depth_levels
                and len(ask_levels) == policy.depth_levels
            )
            if depth_available:
                bid_depth = sum((level.quantity for level in bid_levels), Decimal(0))
                ask_depth = sum((level.quantity for level in ask_levels), Decimal(0))
                bid_notional = sum(
                    (level.price * level.quantity for level in bid_levels), Decimal(0)
                )
                ask_notional = sum(
                    (level.price * level.quantity for level in ask_levels), Decimal(0)
                )
                with localcontext() as ratio_context:
                    ratio_context.prec = 28
                    ratio_context.rounding = ROUND_HALF_EVEN
                    spread_bps = Decimal("20000") * spread / (ask + bid)
                    imbalance = (bid_depth - ask_depth) / (bid_depth + ask_depth)
                metric_values.update(
                    {
                        OrderFlowMetricName.BID_DEPTH: (bid_depth, evidence_id, ""),
                        OrderFlowMetricName.ASK_DEPTH: (ask_depth, evidence_id, ""),
                        OrderFlowMetricName.BID_NOTIONAL: (
                            bid_notional,
                            evidence_id,
                            f"notional sums each displayed level's price × quantity across top {policy.depth_levels} levels",
                        ),
                        OrderFlowMetricName.ASK_NOTIONAL: (
                            ask_notional,
                            evidence_id,
                            f"notional sums each displayed level's price × quantity across top {policy.depth_levels} levels",
                        ),
                        OrderFlowMetricName.BOOK_IMBALANCE: (
                            imbalance,
                            evidence_id,
                            "displayed-book quantity imbalance only; not execution likelihood or hidden liquidity",
                        ),
                        OrderFlowMetricName.SPREAD_BPS: (
                            spread_bps,
                            evidence_id,
                            "spread bps = 20,000 × (ask − bid) / (ask + bid)",
                        ),
                    }
                )
        metric_values.update(
            {
                OrderFlowMetricName.BEST_BID_PRICE: (bid, evidence_id, ""),
                OrderFlowMetricName.BEST_ASK_PRICE: (ask, evidence_id, ""),
                OrderFlowMetricName.MIDPOINT_PRICE: (midpoint, evidence_id, ""),
                OrderFlowMetricName.ABSOLUTE_SPREAD: (spread, evidence_id, ""),
            }
        )

    trade_count_pass = (
        trade_item is not None
        and base_pass.get(InputModality.SPOT_TRADES, False)
        and bool(evidence_by_modality.get(InputModality.SPOT_TRADES))
    )
    trade_start: datetime | None = None
    trade_end: datetime | None = None
    if trade_item is not None and trade_identities:
        trade_start = min(value.event_time for value in trade_item.observations)
        trade_end = trade_item.snapshot.as_of
    positive_trade_window = (
        trade_start is not None and trade_end is not None and trade_start < trade_end
    )
    trade_evidence_id = (
        evidence_by_modality[InputModality.SPOT_TRADES].evidence_id
        if InputModality.SPOT_TRADES in evidence_by_modality
        else None
    )
    if trade_count_pass and positive_trade_window and trade_evidence_id is not None:
        metric_values[OrderFlowMetricName.TRADE_RECORD_COUNT] = (
            len(trade_identities),
            trade_evidence_id,
            "",
        )

    sequence_dimensions_pass = (
        trade_item is not None
        and _dimension_passes(
            trade_item,
            (*_BASE_DIMENSIONS, DataQualityDimension.CONTINUITY),
        )
    )
    strict_sequence = (
        trade_handoff is not None
        and trade_handoff.quality.sequence_verified
        and trade_item is not None
        and bool(trade_identities)
        and all(
            identity.sequence is not None and identity.sequence_scope is not None
            for identity in trade_identities
        )
        and not trade_handoff.quality.duplicate_event_ids
        and sequence_dimensions_pass
    )
    known_aggressors = bool(trade_identities) and all(
        identity.side_semantics is SideSemantics.AGGRESSOR
        and identity.aggressor_side in {ReportedSide.BUY, ReportedSide.SELL}
        for identity in trade_identities
    )
    if (
        strict_sequence
        and known_aggressors
        and positive_trade_window
        and trade_item is not None
        and trade_evidence_id is not None
    ):
        with localcontext() as context:
            context.prec = 80
            buy_volume = sum(
                (
                    _metric_map(observation)["quantity"].value
                    for identity, observation in zip(
                        trade_identities, trade_item.observations
                    )
                    if identity.aggressor_side is ReportedSide.BUY
                ),
                Decimal(0),
            )
            sell_volume = sum(
                (
                    _metric_map(observation)["quantity"].value
                    for identity, observation in zip(
                        trade_identities, trade_item.observations
                    )
                    if identity.aggressor_side is ReportedSide.SELL
                ),
                Decimal(0),
            )
        delta = buy_volume - sell_volume
        metric_values.update(
            {
                OrderFlowMetricName.BUY_AGGRESSOR_VOLUME: (
                    buy_volume,
                    trade_evidence_id,
                    "",
                ),
                OrderFlowMetricName.SELL_AGGRESSOR_VOLUME: (
                    sell_volume,
                    trade_evidence_id,
                    "",
                ),
                OrderFlowMetricName.VOLUME_DELTA: (delta, trade_evidence_id, ""),
                OrderFlowMetricName.CUMULATIVE_DELTA: (
                    delta,
                    trade_evidence_id,
                    "cumulative delta is anchored at the first explicitly bound event; no carry-in",
                ),
            }
        )

    limitations_by_modality = {
        modality: _limitations(item, policy.depth_levels)
        for modality, item in by_modality.items()
    }
    metrics: list[OrderFlowMetric] = []
    for name in OrderFlowMetricName:
        modality = (
            InputModality.ORDER_BOOK if name in _BOOK_METRICS else InputModality.SPOT_TRADES
        )
        item = by_modality.get(modality)
        evidence = evidence_by_modality.get(modality)
        selected = metric_values.get(name)
        if selected is not None and item is not None and evidence is not None:
            value, evidence_id, calculation_limit = selected
            metric_limitations = (
                *limitations_by_modality[modality],
                *((calculation_limit,) if calculation_limit else ()),
            )
            metrics.append(
                OrderFlowMetric(
                    name=name,
                    state=OrderFlowMetricState.AVAILABLE,
                    value=value,
                    unit=_unit(name, policy),
                    calculated_at=calculation_time,
                    window_start=(
                        item.snapshot.as_of
                        if modality is InputModality.ORDER_BOOK
                        else trade_start
                    ),
                    window_end=item.snapshot.as_of,
                    method=SPOT_ORDER_FLOW_METHOD,
                    evidence_ids=(evidence_id,),
                    binding_ids=(item.binding.binding_id,),
                    limitations=metric_limitations,
                )
            )
            continue
        reasons = []
        if item is None:
            reasons.append(f"No {modality.value} input is bound.")
        elif not base_pass.get(modality, False):
            required = (
                (*_BASE_DIMENSIONS, DataQualityDimension.CONTINUITY)
                if name in _DIRECTIONAL_METRICS
                else _BASE_DIMENSIONS
            )
            reasons.append(_quality_failure_reason(item, required))
        elif modality is InputModality.ORDER_BOOK and name in {
            OrderFlowMetricName.BID_DEPTH,
            OrderFlowMetricName.ASK_DEPTH,
            OrderFlowMetricName.BID_NOTIONAL,
            OrderFlowMetricName.ASK_NOTIONAL,
            OrderFlowMetricName.BOOK_IMBALANCE,
        }:
            reasons.append(
                f"Both book sides do not contain the configured top {policy.depth_levels} levels."
            )
        elif name is OrderFlowMetricName.TRADE_RECORD_COUNT and not positive_trade_window:
            reasons.append("A positive-duration trade window cannot be established.")
        elif name in _DIRECTIONAL_METRICS and not known_aggressors:
            reasons.append("Unknown or non-aggressor side prevents full-window directional totals.")
        elif name in _DIRECTIONAL_METRICS and not strict_sequence:
            reasons.append("Verified contiguous sequence and passing continuity are required.")
        else:
            reasons.append("Required evidence or calculation inputs are unavailable.")
        can_bind = (
            item is not None
            and evidence is not None
            and (
                modality is InputModality.ORDER_BOOK
                or positive_trade_window
            )
        )
        metrics.append(
            OrderFlowMetric(
                name=name,
                state=OrderFlowMetricState.UNAVAILABLE,
                value=None,
                unit=_unit(name, policy),
                calculated_at=calculation_time,
                window_start=(
                    item.snapshot.as_of
                    if item is not None and modality is InputModality.ORDER_BOOK
                    else trade_start
                    if trade_start is not None and positive_trade_window
                    else item.snapshot.as_of
                    if item is not None
                    else manifest.analysis_cutoff
                ),
                window_end=(
                    item.snapshot.as_of
                    if item is not None
                    else manifest.analysis_cutoff
                ),
                method=SPOT_ORDER_FLOW_METHOD,
                evidence_ids=(evidence_ids[modality],) if can_bind else (),
                binding_ids=(item.binding.binding_id,) if can_bind and item else (),
                limitations=limitations_by_modality.get(modality, ()),
                unavailable_reason=" ".join(reasons),
            )
        )

    states = {value.state for value in metrics}
    state = (
        OrderFlowAssessmentState.AVAILABLE
        if states == {OrderFlowMetricState.AVAILABLE}
        else OrderFlowAssessmentState.UNAVAILABLE
        if states == {OrderFlowMetricState.UNAVAILABLE}
        else OrderFlowAssessmentState.PARTIAL
    )
    assessment = OrderFlowAssessment(
        assessment_id=assessment_id,
        asset=manifest.asset,
        instrument_id=manifest.instrument_id,
        venue_id=manifest.venue_id,
        base_unit=policy.base_unit,
        quote_unit=policy.quote_unit,
        as_of=manifest.analysis_cutoff,
        expires_at=manifest.expires_at,
        state=state,
        metrics=tuple(metrics),
    )
    output_evidence = tuple(
        evidence_by_modality[modality]
        for modality in (InputModality.ORDER_BOOK, InputModality.SPOT_TRADES)
        if modality in evidence_by_modality
    )
    return SpotOrderFlowResult(assessment, output_evidence)


__all__ = [
    "SPOT_ORDER_FLOW_METHOD",
    "SpotOrderFlowError",
    "SpotOrderFlowPolicy",
    "SpotOrderFlowResult",
    "calculate_spot_order_flow",
]
