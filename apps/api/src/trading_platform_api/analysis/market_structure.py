"""Deterministic, analysis-only Spot market-structure observations."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal, localcontext
from enum import StrEnum
from hashlib import sha256
from uuid import UUID, uuid5

from trading_platform_api.analysis.contracts import (
    AnalyticalFinding,
    AssessmentStatus,
    ClaimClassification,
    DomainObservation,
    EvidenceItem,
    EvidenceRelation,
    MethodologyCategory,
    TechnicalAssessment,
    VersionReference,
)
from trading_platform_api.analysis.indicator_registry import (
    SPOT_RESEARCH_INDICATORS,
    IndicatorMetadataError,
    IndicatorPhase,
)
from trading_platform_api.analysis.price_action import (
    _INTERVALS,
    PRICE_ACTION_INDICATOR_ID,
    PRICE_ACTION_METADATA_VERSION,
    PRICE_ACTION_METHOD_VERSION,
    PivotKind,
    PivotObservation,
    PriceActionAnalysis,
    SupportResistancePolicy,
    _bounded_decimal,
)
from trading_platform_api.analysis.volatility import VolatilityError, _ohlc
from trading_platform_api.contracts.serialization import (
    CANONICAL_JSON_VERSION,
    MAX_DOCUMENT_BYTES,
    canonical_json_dumps,
)
from trading_platform_api.market_data.contracts import (
    DataQualityReport,
    MarketData,
    MarketSnapshot,
)

MARKET_STRUCTURE_INDICATOR_ID = "spot-market-structure"
MARKET_STRUCTURE_METADATA_VERSION = "1"
MARKET_STRUCTURE_METHOD_VERSION = "spot-market-structure-v1"
MARKET_STRUCTURE_EVIDENCE_VERSION = "spot-market-structure-evidence-v1"
_MAX_CANDLES = 10_000
_MAX_BREAK_CLOSES = 500
_IDENTITY_NAMESPACE = UUID("6718c1d3-277b-5779-9d69-87b06a13eea4")


class MarketStructureError(ValueError):
    """Market-structure observations cannot be calculated safely."""


class MarketStructureScale(StrEnum):
    INTERNAL = "internal"
    EXTERNAL = "external"


class SwingClassification(StrEnum):
    HIGHER_HIGH = "HH"
    LOWER_HIGH = "LH"
    EQUAL_HIGH = "equal-high"
    HIGHER_LOW = "HL"
    LOWER_LOW = "LL"
    EQUAL_LOW = "equal-low"


class StructureDirection(StrEnum):
    BULLISH = "bullish"
    BEARISH = "bearish"
    MIXED = "mixed"


class StructureEventType(StrEnum):
    BREAK_OF_STRUCTURE = "BOS"
    CHANGE_OF_CHARACTER = "CHoCH"
    MARKET_STRUCTURE_SHIFT = "MSS"
    UNCLASSIFIED_BREAK = "unclassified-structural-break"


class BreakDirection(StrEnum):
    UP = "up"
    DOWN = "down"


@dataclass(frozen=True, slots=True)
class MarketStructurePolicy:
    """Immutable, explicit policy for close-only structural breaks."""

    policy_id: str
    version: str
    break_buffer: Decimal
    consecutive_close_count: int

    def __post_init__(self) -> None:
        for name, value in (("policy_id", self.policy_id), ("version", self.version)):
            if (
                not isinstance(value, str)
                or not value
                or value != value.strip()
                or len(value) > 128
            ):
                raise MarketStructureError(f"{name} must be bounded nonblank text.")
        try:
            buffer = _bounded_decimal("break_buffer", self.break_buffer)
        except (TypeError, ValueError) as exc:
            raise MarketStructureError(
                "break_buffer must be a bounded Decimal."
            ) from exc
        if buffer <= 0:
            raise MarketStructureError("break_buffer must be strictly positive.")
        if (
            type(self.consecutive_close_count) is not int
            or not 1 <= self.consecutive_close_count <= _MAX_BREAK_CLOSES
        ):
            raise MarketStructureError(
                f"consecutive_close_count must be in [1, {_MAX_BREAK_CLOSES}]."
            )


@dataclass(frozen=True, slots=True)
class ClassifiedSwing:
    scale: MarketStructureScale
    pivot: PivotObservation
    classification: SwingClassification | None


@dataclass(frozen=True, slots=True)
class StructureState:
    scale: MarketStructureScale
    direction: StructureDirection
    reason: str
    latest_high_classification: SwingClassification | None
    latest_low_classification: SwingClassification | None
    continuation_pivot_id: UUID | None
    protected_pivot_id: UUID | None


@dataclass(frozen=True, slots=True)
class StructuralBreak:
    asset: str
    instrument_id: str
    venue_id: str
    timeframe: str
    scale: MarketStructureScale
    event_type: StructureEventType
    direction: BreakDirection
    reference_pivot: PivotObservation
    reference_price: Decimal
    confirming_market_data_id: UUID
    confirming_candle_time: datetime
    confirmation_time: datetime
    confirming_close: Decimal
    break_buffer: Decimal
    consecutive_close_count: int
    prior_state: StructureDirection
    detection_rule: str
    invalidation_condition: str


@dataclass(frozen=True, slots=True)
class _MarketStructureEvidence:
    payload_version: str
    method_version: str
    timeframe: str
    instrument_id: str
    venue_id: str
    asset: str
    price_unit: str
    snapshot_id: UUID
    quality_report_id: UUID
    as_of: datetime
    evidence_expires_at: datetime
    source_record_ids: tuple[UUID, ...]
    input_market_data_ids: tuple[UUID, ...]
    internal_pivot_policy: SupportResistancePolicy
    external_pivot_policy: SupportResistancePolicy
    break_policy: MarketStructurePolicy
    internal_pivot_method_version: str
    internal_pivot_metadata_version: str
    external_pivot_method_version: str
    external_pivot_metadata_version: str
    swings: tuple[ClassifiedSwing, ...]
    states: tuple[StructureState, ...]
    events: tuple[StructuralBreak, ...]
    uncertainty: tuple[str, ...]
    limitations: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class MarketStructureAnalysis:
    indicator_id: str
    metadata_version: str
    method_version: str
    timeframe: str
    asset: str
    instrument_id: str
    venue_id: str
    snapshot_id: UUID
    quality_report_id: UUID
    as_of: datetime
    evidence_expires_at: datetime
    source_record_ids: tuple[UUID, ...]
    input_market_data_ids: tuple[UUID, ...]
    price_unit: str
    internal_pivot_policy: SupportResistancePolicy
    external_pivot_policy: SupportResistancePolicy
    break_policy: MarketStructurePolicy
    swings: tuple[ClassifiedSwing, ...]
    states: tuple[StructureState, ...]
    events: tuple[StructuralBreak, ...]
    uncertainty: tuple[str, ...]
    limitations: tuple[str, ...]
    evidence: EvidenceItem
    assessment: TechnicalAssessment


def _stable_id(*parts: object) -> UUID:
    return uuid5(_IDENTITY_NAMESPACE, canonical_json_dumps(parts))


def _validate_price_action(
    *,
    analysis: PriceActionAnalysis,
    snapshot: MarketSnapshot,
    quality: DataQualityReport,
    observations: tuple[MarketData, ...],
    timeframe: str,
    pivot_policy: SupportResistancePolicy,
) -> None:
    if type(analysis) is not PriceActionAnalysis:
        raise MarketStructureError(
            "Both exact #55 PriceActionAnalysis results are required."
        )
    if (
        analysis.indicator_id != PRICE_ACTION_INDICATOR_ID
        or analysis.metadata_version != PRICE_ACTION_METADATA_VERSION
        or analysis.method_version != PRICE_ACTION_METHOD_VERSION
    ):
        raise MarketStructureError("Unregistered #55 method or metadata version.")
    if (
        analysis.snapshot_id != snapshot.snapshot_id
        or analysis.quality_report_id != quality.report_id
        or analysis.instrument_id != snapshot.instrument_id
        or analysis.venue_id != snapshot.venue_id
        or analysis.timeframe != timeframe
        or analysis.as_of != snapshot.as_of
        or analysis.source_record_ids != snapshot.source_record_ids
        or analysis.input_market_data_ids != snapshot.market_data_ids
        or tuple(item.market_data_id for item in observations)
        != snapshot.market_data_ids
    ):
        raise MarketStructureError(
            "#55 output lineage does not match the exact inputs."
        )
    if (
        analysis.evidence.contract_id != "C-008"
        or analysis.evidence.data_quality_report_id != quality.report_id
        or analysis.evidence.source_record_ids != snapshot.source_record_ids
        or analysis.evidence.method.component != PRICE_ACTION_INDICATOR_ID
        or analysis.evidence.method.version != PRICE_ACTION_METHOD_VERSION
        or analysis.assessment.contract_id != "C-012"
        or analysis.assessment.data_quality_report_id != quality.report_id
        or analysis.assessment.evidence_ids != (analysis.evidence.evidence_id,)
        or analysis.assessment.instrument_id != snapshot.instrument_id
        or analysis.assessment.timeframe != timeframe
        or analysis.assessment.as_of != snapshot.as_of
        or analysis.assessment.status is not AssessmentStatus.AVAILABLE
    ):
        raise MarketStructureError(
            "#55 evidence and C-012 assessment lineage is invalid."
        )
    if analysis.support_resistance_policy != pivot_policy:
        raise MarketStructureError(
            "The designated pivot policy differs from #55 output."
        )
    try:
        metadata = SPOT_RESEARCH_INDICATORS.get(
            analysis.indicator_id, analysis.metadata_version
        )
    except IndicatorMetadataError as exc:
        raise MarketStructureError("Exact #55 metadata lookup failed.") from exc
    if (
        metadata.phase is not IndicatorPhase.VALIDATED
        or metadata.calculation_version != PRICE_ACTION_METHOD_VERSION
        or timeframe not in metadata.timeframes
    ):
        raise MarketStructureError("The exact #55 method is not validated here.")
    candles_by_id = {item.market_data_id: item for item in observations}
    interval = timedelta(seconds=_INTERVALS[timeframe])
    if (
        type(analysis.pivots) is not tuple
        or not all(type(pivot) is PivotObservation for pivot in analysis.pivots)
        or len({pivot.pivot_id for pivot in analysis.pivots}) != len(analysis.pivots)
    ):
        raise MarketStructureError("Pivot output must be an immutable unique tuple.")
    for pivot in analysis.pivots:
        if type(pivot) is not PivotObservation:
            raise MarketStructureError("Pivot output contains an invalid record.")
        source = candles_by_id.get(pivot.source_market_data_id)
        confirmation = candles_by_id.get(pivot.confirmation_market_data_id)
        if (
            source is None
            or confirmation is None
            or pivot.source_time != source.event_time
            or pivot.confirmation_time != confirmation.event_time + interval
            or pivot.confirmation_time > snapshot.as_of
            or pivot.source_time >= confirmation.event_time
            or pivot.left_window != pivot_policy.left_window
            or pivot.right_window != pivot_policy.right_window
            or pivot.policy_id != pivot_policy.policy_id
            or pivot.policy_version != pivot_policy.version
            or pivot.method_version != PRICE_ACTION_METHOD_VERSION
            or pivot.price <= 0
        ):
            raise MarketStructureError(
                "Pivot confirmation or source lineage is invalid."
            )


def _classify(
    pivots: tuple[PivotObservation, ...], scale: MarketStructureScale
) -> tuple[ClassifiedSwing, ...]:
    result: list[ClassifiedSwing] = []
    prior: dict[PivotKind, PivotObservation] = {}
    for pivot in sorted(
        pivots,
        key=lambda item: (item.confirmation_time, item.source_time, item.kind.value),
    ):
        previous = prior.get(pivot.kind)
        classification: SwingClassification | None = None
        if previous is not None:
            if pivot.kind is PivotKind.HIGH:
                classification = (
                    SwingClassification.HIGHER_HIGH
                    if pivot.price > previous.price
                    else SwingClassification.LOWER_HIGH
                    if pivot.price < previous.price
                    else SwingClassification.EQUAL_HIGH
                )
            else:
                classification = (
                    SwingClassification.HIGHER_LOW
                    if pivot.price > previous.price
                    else SwingClassification.LOWER_LOW
                    if pivot.price < previous.price
                    else SwingClassification.EQUAL_LOW
                )
        result.append(ClassifiedSwing(scale, pivot, classification))
        prior[pivot.kind] = pivot
    return tuple(result)


def _state(
    scale: MarketStructureScale,
    visible: tuple[ClassifiedSwing, ...],
) -> StructureState:
    latest_high = next(
        (item for item in reversed(visible) if item.pivot.kind is PivotKind.HIGH), None
    )
    latest_low = next(
        (item for item in reversed(visible) if item.pivot.kind is PivotKind.LOW), None
    )
    high_class = latest_high.classification if latest_high else None
    low_class = latest_low.classification if latest_low else None
    if latest_high is None or latest_low is None:
        reason = "insufficient-confirmed-high-low-history"
        direction = StructureDirection.MIXED
    elif (
        high_class is SwingClassification.HIGHER_HIGH
        and low_class is SwingClassification.HIGHER_LOW
    ):
        direction = StructureDirection.BULLISH
        reason = "latest-high-HH-and-latest-low-HL"
    elif (
        high_class is SwingClassification.LOWER_HIGH
        and low_class is SwingClassification.LOWER_LOW
    ):
        direction = StructureDirection.BEARISH
        reason = "latest-high-LH-and-latest-low-LL"
    elif high_class is None or low_class is None:
        direction = StructureDirection.MIXED
        reason = "first-confirmed-pivot-of-kind-is-unclassified"
    elif (
        high_class in (SwingClassification.EQUAL_HIGH,)
        or low_class is SwingClassification.EQUAL_LOW
    ):
        direction = StructureDirection.MIXED
        reason = "latest-pivot-is-equal-and-has-no-directional-classification"
    else:
        direction = StructureDirection.MIXED
        reason = "latest-high-and-low-classifications-conflict"

    continuation: UUID | None = None
    protected: UUID | None = None
    if direction is StructureDirection.BULLISH:
        continuation = latest_high.pivot.pivot_id if latest_high else None
        protected = latest_low.pivot.pivot_id if latest_low else None
    elif direction is StructureDirection.BEARISH:
        continuation = latest_low.pivot.pivot_id if latest_low else None
        protected = latest_high.pivot.pivot_id if latest_high else None
    return StructureState(
        scale,
        direction,
        reason,
        high_class,
        low_class,
        continuation,
        protected,
    )


def _evidence_contracts(
    *,
    payload: _MarketStructureEvidence,
    snapshot: MarketSnapshot,
    quality: DataQualityReport,
    timeframe: str,
    indicator_id: str,
    method_version: str,
) -> tuple[EvidenceItem, TechnicalAssessment]:
    encoded = canonical_json_dumps(payload)
    if len(encoded.encode("utf-8")) > MAX_DOCUMENT_BYTES:
        raise MarketStructureError(
            "Market-structure evidence exceeds the output bound."
        )
    digest = sha256(encoded.encode("utf-8")).hexdigest()
    evidence_id = _stable_id(
        "evidence",
        snapshot.snapshot_id,
        quality.report_id,
        method_version,
        MARKET_STRUCTURE_EVIDENCE_VERSION,
        digest,
    )
    method = VersionReference(indicator_id, method_version)
    provenance = (
        VersionReference("C-001", "1"),
        VersionReference("C-002", "1"),
        VersionReference("C-003", "1"),
        VersionReference(PRICE_ACTION_INDICATOR_ID, PRICE_ACTION_METHOD_VERSION),
        VersionReference("canonical-json", CANONICAL_JSON_VERSION),
        VersionReference(
            "market-structure-evidence", MARKET_STRUCTURE_EVIDENCE_VERSION
        ),
    )
    evidence = EvidenceItem(
        evidence_id=evidence_id,
        source_record_ids=snapshot.source_record_ids,
        dataset_versions=(snapshot.dataset_version,)
        if snapshot.dataset_version
        else (),
        feature_ids=(),
        classification=ClaimClassification.FACT,
        relation=EvidenceRelation.NEUTRAL,
        observed_at=snapshot.as_of,
        available_at=quality.assessed_at,
        expires_at=payload.evidence_expires_at,
        method=method,
        value=encoded,
        unit=payload.price_unit,
        interpretation=(
            "Deterministic, versioned Spot market-structure observations; "
            "descriptive evidence only."
        ),
        quality_status=quality.status,
        data_quality_report_id=quality.report_id,
        reliability=quality.source_reliability,
        limitations=payload.limitations,
        provenance=provenance,
        usable=True,
    )
    evidence_ids = (evidence_id,)
    findings = (
        AnalyticalFinding(
            finding_id=_stable_id("finding", evidence_id),
            category="market-structure-observation",
            classification=ClaimClassification.FACT,
            statement=(
                "Confirmed Spot pivots, classifications, states, and close-based "
                "structural breaks are recorded in linked C-008 evidence."
            ),
            evidence_ids=evidence_ids,
            method=method,
            invalidation_condition=(
                "Superseded by correction of source candles/pivots or a change to "
                "the exact method or caller policy version."
            ),
            limitations=payload.limitations,
        ),
    )
    observations = tuple(
        DomainObservation(
            observation_type="market-structure",
            value=(
                f"{state.scale.value}:{state.direction.value}:{state.reason}:"
                f"high={state.latest_high_classification.value if state.latest_high_classification else 'unclassified'}:"
                f"low={state.latest_low_classification.value if state.latest_low_classification else 'unclassified'}"
            ),
            unit=None,
            timeframe=timeframe,
            calculation=method,
            evidence_ids=evidence_ids,
        )
        for state in payload.states
    ) + tuple(
        DomainObservation(
            observation_type="market-structure",
            value=(
                f"{event.scale.value}:{event.event_type.value}:{event.direction.value}:"
                f"reference={event.reference_price}:close={event.confirming_close}:"
                f"confirmation={event.confirmation_time.isoformat()}"
            ),
            unit=payload.price_unit,
            timeframe=timeframe,
            calculation=method,
            evidence_ids=evidence_ids,
        )
        for event in payload.events
    )
    assessment = TechnicalAssessment(
        assessment_id=_stable_id("assessment", evidence_id),
        asset=payload.asset,
        instrument_id=snapshot.instrument_id,
        timeframe=timeframe,
        as_of=snapshot.as_of,
        available_at=quality.assessed_at,
        expires_at=payload.evidence_expires_at,
        status=AssessmentStatus.AVAILABLE,
        analytical_confidence=Decimal(1),
        findings=findings,
        observations=observations,
        evidence_ids=evidence_ids,
        contradiction_ids=(),
        uncertainty_ids=(),
        data_quality_report_id=quality.report_id,
        provenance=provenance,
        methodology=MethodologyCategory.TECHNICAL,
    )
    return evidence, assessment


def calculate_spot_market_structure(
    *,
    snapshot: MarketSnapshot,
    observations: tuple[MarketData, ...],
    quality: DataQualityReport,
    timeframe: str,
    internal_price_action: PriceActionAnalysis,
    external_price_action: PriceActionAnalysis,
    internal_pivot_policy: SupportResistancePolicy,
    external_pivot_policy: SupportResistancePolicy,
    break_policy: MarketStructurePolicy,
    metadata_version: str = MARKET_STRUCTURE_METADATA_VERSION,
) -> MarketStructureAnalysis:
    """Classify confirmed pivots and detect policy-defined close-only breaks."""
    if (
        type(snapshot) is not MarketSnapshot
        or type(quality) is not DataQualityReport
        or type(observations) is not tuple
        or not observations
        or len(observations) > _MAX_CANDLES
        or not all(type(item) is MarketData for item in observations)
    ):
        raise MarketStructureError(
            "Canonical bounded snapshot, quality and candles are required."
        )
    if type(timeframe) is not str or timeframe not in _INTERVALS:
        raise MarketStructureError("Unsupported Spot timeframe.")
    if (
        type(internal_pivot_policy) is not SupportResistancePolicy
        or type(external_pivot_policy) is not SupportResistancePolicy
        or type(break_policy) is not MarketStructurePolicy
    ):
        raise MarketStructureError(
            "Explicit immutable pivot and break policies are required."
        )
    if (
        external_pivot_policy.left_window < internal_pivot_policy.left_window
        or external_pivot_policy.right_window < internal_pivot_policy.right_window
        or (
            external_pivot_policy.left_window == internal_pivot_policy.left_window
            and external_pivot_policy.right_window == internal_pivot_policy.right_window
        )
    ):
        raise MarketStructureError(
            "External windows must be no smaller and not identical."
        )
    if type(metadata_version) is not str:
        raise MarketStructureError("metadata_version must be an exact version string.")
    try:
        metadata = SPOT_RESEARCH_INDICATORS.get(
            MARKET_STRUCTURE_INDICATOR_ID, metadata_version
        )
    except (IndicatorMetadataError, TypeError) as exc:
        raise MarketStructureError(
            "Unknown exact market-structure metadata version."
        ) from exc
    if (
        metadata.phase is not IndicatorPhase.VALIDATED
        or timeframe not in metadata.timeframes
    ):
        raise MarketStructureError(
            "Market-structure method is not validated for timeframe."
        )
    if not snapshot.instrument_id.endswith("-SPOT") or not snapshot.venue_id.endswith(
        "-SPOT"
    ):
        raise MarketStructureError(
            "Only canonical Spot instruments and venues are supported."
        )
    try:
        _ohlc(
            snapshot=snapshot,
            observations=observations,
            quality=quality,
            timeframe=timeframe,
        )
    except (VolatilityError, ArithmeticError) as exc:
        raise MarketStructureError(
            "Spot OHLCV failed shared analysis validation."
        ) from exc
    interval = timedelta(seconds=_INTERVALS[timeframe])
    if observations[-1].event_time + interval != snapshot.as_of:
        raise MarketStructureError(
            "The latest candle must be current at the snapshot cutoff."
        )

    for analysis, policy in (
        (internal_price_action, internal_pivot_policy),
        (external_price_action, external_pivot_policy),
    ):
        _validate_price_action(
            analysis=analysis,
            snapshot=snapshot,
            quality=quality,
            observations=observations,
            timeframe=timeframe,
            pivot_policy=policy,
        )
    if (
        internal_price_action.price_unit != external_price_action.price_unit
        or internal_price_action.input_market_data_ids
        != external_price_action.input_market_data_ids
        or internal_price_action.source_record_ids
        != external_price_action.source_record_ids
    ):
        raise MarketStructureError(
            "Internal and external pivots must share exact data and units."
        )
    if (
        internal_pivot_policy.price_unit != external_pivot_policy.price_unit
        or internal_pivot_policy.price_unit != internal_price_action.price_unit
    ):
        raise MarketStructureError(
            "Pivot-policy price units must match the input price unit."
        )
    try:
        metadata = SPOT_RESEARCH_INDICATORS.get(
            MARKET_STRUCTURE_INDICATOR_ID, metadata_version
        )
        _bounded_decimal("break_buffer", break_policy.break_buffer)
    except (IndicatorMetadataError, TypeError, ValueError) as exc:
        raise MarketStructureError("Invalid exact metadata or break policy.") from exc

    internal_swings = _classify(
        internal_price_action.pivots, MarketStructureScale.INTERNAL
    )
    external_swings = _classify(
        external_price_action.pivots, MarketStructureScale.EXTERNAL
    )
    all_swings = internal_swings + external_swings
    scale_swings = {
        MarketStructureScale.INTERNAL: internal_swings,
        MarketStructureScale.EXTERNAL: external_swings,
    }
    pivot_by_id = {swing.pivot.pivot_id: swing.pivot for swing in all_swings}
    values: list[tuple[Decimal, Decimal, Decimal, Decimal]] = []
    price_unit: str | None = None
    for candle in observations:
        metrics = {metric.metric_name: metric for metric in candle.metrics}
        opening_metric, high_metric, low_metric, close_metric = (
            metrics[name] for name in ("open", "high", "low", "close")
        )
        for metric in (opening_metric, high_metric, low_metric, close_metric):
            _bounded_decimal(metric.metric_name, metric.value)
        if price_unit is None:
            price_unit = close_metric.unit
        if any(
            metric.unit != price_unit
            for metric in (opening_metric, high_metric, low_metric, close_metric)
        ):
            raise MarketStructureError("OHLC price units must remain consistent.")
        values.append(
            (
                opening_metric.value,
                high_metric.value,
                low_metric.value,
                close_metric.value,
            )
        )
    assert price_unit is not None
    if (
        internal_price_action.price_unit != price_unit
        or external_price_action.price_unit != price_unit
    ):
        raise MarketStructureError(
            "Pivot results must use the canonical input price unit."
        )

    counts: dict[tuple[UUID, BreakDirection], int] = {}
    emitted: set[tuple[UUID, BreakDirection]] = set()
    events: list[StructuralBreak] = []
    for candle, (_, _, _, close_value) in zip(observations, values, strict=True):
        candle_end = candle.event_time + interval
        for scale in (MarketStructureScale.INTERNAL, MarketStructureScale.EXTERNAL):
            visible = tuple(
                swing
                for swing in scale_swings[scale]
                if swing.pivot.confirmation_time <= candle_end
            )
            state = _state(scale, visible)
            references: list[
                tuple[PivotObservation, BreakDirection, StructureEventType]
            ] = []
            if state.direction is StructureDirection.BULLISH:
                continuation = (
                    pivot_by_id.get(state.continuation_pivot_id)
                    if state.continuation_pivot_id is not None
                    else None
                )
                protected = (
                    pivot_by_id.get(state.protected_pivot_id)
                    if state.protected_pivot_id is not None
                    else None
                )
                if continuation is not None and protected is not None:
                    references.extend(
                        (
                            (
                                continuation,
                                BreakDirection.UP,
                                StructureEventType.BREAK_OF_STRUCTURE,
                            ),
                            (
                                protected,
                                BreakDirection.DOWN,
                                StructureEventType.CHANGE_OF_CHARACTER
                                if scale is MarketStructureScale.INTERNAL
                                else StructureEventType.MARKET_STRUCTURE_SHIFT,
                            ),
                        )
                    )
            elif state.direction is StructureDirection.BEARISH:
                continuation = (
                    pivot_by_id.get(state.continuation_pivot_id)
                    if state.continuation_pivot_id is not None
                    else None
                )
                protected = (
                    pivot_by_id.get(state.protected_pivot_id)
                    if state.protected_pivot_id is not None
                    else None
                )
                if continuation is not None and protected is not None:
                    references.extend(
                        (
                            (
                                continuation,
                                BreakDirection.DOWN,
                                StructureEventType.BREAK_OF_STRUCTURE,
                            ),
                            (
                                protected,
                                BreakDirection.UP,
                                StructureEventType.CHANGE_OF_CHARACTER
                                if scale is MarketStructureScale.INTERNAL
                                else StructureEventType.MARKET_STRUCTURE_SHIFT,
                            ),
                        )
                    )
            else:
                latest_high = next(
                    (
                        item.pivot
                        for item in reversed(visible)
                        if item.pivot.kind is PivotKind.HIGH
                    ),
                    None,
                )
                latest_low = next(
                    (
                        item.pivot
                        for item in reversed(visible)
                        if item.pivot.kind is PivotKind.LOW
                    ),
                    None,
                )
                if latest_high is not None:
                    references.append(
                        (
                            latest_high,
                            BreakDirection.UP,
                            StructureEventType.UNCLASSIFIED_BREAK,
                        )
                    )
                if latest_low is not None:
                    references.append(
                        (
                            latest_low,
                            BreakDirection.DOWN,
                            StructureEventType.UNCLASSIFIED_BREAK,
                        )
                    )

            current_reference_keys = {
                (reference.pivot_id, direction)
                for reference, direction, _ in references
            }
            scale_pivot_ids = {swing.pivot.pivot_id for swing in scale_swings[scale]}
            for key in counts:
                if key[0] in scale_pivot_ids and key not in current_reference_keys:
                    counts[key] = 0

            for reference, direction, event_type in references:
                key = (reference.pivot_id, direction)
                if candle_end <= reference.confirmation_time or key in emitted:
                    continue
                with localcontext() as context:
                    context.prec = 512
                    beyond = (
                        close_value > reference.price + break_policy.break_buffer
                        if direction is BreakDirection.UP
                        else close_value < reference.price - break_policy.break_buffer
                    )
                counts[key] = counts.get(key, 0) + 1 if beyond else 0
                if counts[key] < break_policy.consecutive_close_count:
                    continue
                emitted.add(key)
                detection = (
                    f"{break_policy.consecutive_close_count} consecutive closed Spot "
                    f"candle closes strictly {'above' if direction is BreakDirection.UP else 'below'} "
                    f"the confirmed pivot by more than {break_policy.break_buffer} {price_unit}."
                )
                events.append(
                    StructuralBreak(
                        asset=snapshot.instrument_id,
                        instrument_id=snapshot.instrument_id,
                        venue_id=snapshot.venue_id,
                        timeframe=timeframe,
                        scale=scale,
                        event_type=event_type,
                        direction=direction,
                        reference_pivot=reference,
                        reference_price=reference.price,
                        confirming_market_data_id=candle.market_data_id,
                        confirming_candle_time=candle.event_time,
                        confirmation_time=candle_end,
                        confirming_close=close_value,
                        break_buffer=break_policy.break_buffer,
                        consecutive_close_count=break_policy.consecutive_close_count,
                        prior_state=state.direction,
                        detection_rule=detection,
                        invalidation_condition=(
                            "Superseded by correction of a source/confirmation candle or "
                            "by a new exact method or caller-policy version."
                        ),
                    )
                )

    current_states = tuple(
        _state(
            scale,
            tuple(
                swing
                for swing in scale_swings[scale]
                if swing.pivot.confirmation_time <= snapshot.as_of
            ),
        )
        for scale in (MarketStructureScale.INTERNAL, MarketStructureScale.EXTERNAL)
    )
    events_tuple = tuple(events)
    uncertainty = (
        "All structure observations derive from the same Spot OHLCV source and are correlated.",
        "No probability, significance, future direction, or trade setup is inferred.",
    )
    limitations = (
        "Analysis-only descriptive evidence; not a signal, recommendation, validation, risk decision, approval, or execution permission.",
        "Internal and external designate caller-selected pivot windows on one timeframe, not a multi-timeframe hierarchy.",
        "Breaks use closed candle closes and caller policy only; wick, volume, displacement, liquidity, SMC, and Wyckoff interpretations are excluded.",
        "Evidence expires one timeframe after quality assessment; a new snapshot and quality report are required to extend validity.",
    )
    try:
        evidence_expiry = quality.assessed_at + interval
    except OverflowError as exc:
        raise MarketStructureError(
            "Evidence expiry exceeds supported timestamp range."
        ) from exc
    payload = _MarketStructureEvidence(
        payload_version=MARKET_STRUCTURE_EVIDENCE_VERSION,
        method_version=MARKET_STRUCTURE_METHOD_VERSION,
        timeframe=timeframe,
        instrument_id=snapshot.instrument_id,
        venue_id=snapshot.venue_id,
        asset=snapshot.instrument_id,
        price_unit=price_unit,
        snapshot_id=snapshot.snapshot_id,
        quality_report_id=quality.report_id,
        as_of=snapshot.as_of,
        evidence_expires_at=evidence_expiry,
        source_record_ids=snapshot.source_record_ids,
        input_market_data_ids=snapshot.market_data_ids,
        internal_pivot_policy=internal_pivot_policy,
        external_pivot_policy=external_pivot_policy,
        break_policy=break_policy,
        internal_pivot_method_version=internal_price_action.method_version,
        internal_pivot_metadata_version=internal_price_action.metadata_version,
        external_pivot_method_version=external_price_action.method_version,
        external_pivot_metadata_version=external_price_action.metadata_version,
        swings=all_swings,
        states=current_states,
        events=events_tuple,
        uncertainty=uncertainty,
        limitations=limitations,
    )
    evidence, assessment = _evidence_contracts(
        payload=payload,
        snapshot=snapshot,
        quality=quality,
        timeframe=timeframe,
        indicator_id=metadata.indicator_id,
        method_version=metadata.calculation_version,
    )
    return MarketStructureAnalysis(
        indicator_id=metadata.indicator_id,
        metadata_version=metadata.metadata_version,
        method_version=metadata.calculation_version,
        timeframe=timeframe,
        asset=snapshot.instrument_id,
        instrument_id=snapshot.instrument_id,
        venue_id=snapshot.venue_id,
        snapshot_id=snapshot.snapshot_id,
        quality_report_id=quality.report_id,
        as_of=snapshot.as_of,
        evidence_expires_at=evidence_expiry,
        source_record_ids=snapshot.source_record_ids,
        input_market_data_ids=snapshot.market_data_ids,
        price_unit=price_unit,
        internal_pivot_policy=internal_pivot_policy,
        external_pivot_policy=external_pivot_policy,
        break_policy=break_policy,
        swings=all_swings,
        states=current_states,
        events=events_tuple,
        uncertainty=uncertainty,
        limitations=limitations,
        evidence=evidence,
        assessment=assessment,
    )


__all__ = [
    "MARKET_STRUCTURE_EVIDENCE_VERSION",
    "MARKET_STRUCTURE_INDICATOR_ID",
    "MARKET_STRUCTURE_METADATA_VERSION",
    "MARKET_STRUCTURE_METHOD_VERSION",
    "BreakDirection",
    "ClassifiedSwing",
    "MarketStructureAnalysis",
    "MarketStructureError",
    "MarketStructurePolicy",
    "MarketStructureScale",
    "StructuralBreak",
    "StructureDirection",
    "StructureEventType",
    "StructureState",
    "SwingClassification",
    "calculate_spot_market_structure",
]
