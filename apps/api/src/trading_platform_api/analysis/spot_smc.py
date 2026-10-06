"""Deterministic, analysis-only Spot Smart Money Concepts observations."""

from __future__ import annotations

import json
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from decimal import Decimal, localcontext
from hashlib import sha256
from typing import TypeAlias
from uuid import UUID, uuid5

from trading_platform_api.analysis.contracts import (
    AnalyticalFinding,
    AssessmentStatus,
    ClaimClassification,
    DomainObservation,
    EvidenceItem,
    EvidenceRelation,
    MethodologyCategory,
    SMCAssessment,
    TechnicalAssessment,
    VersionReference,
)
from trading_platform_api.analysis.indicator_registry import (
    SPOT_RESEARCH_INDICATORS,
    IndicatorMetadataError,
    IndicatorPhase,
)
from trading_platform_api.analysis.market_structure import (
    MARKET_STRUCTURE_EVIDENCE_VERSION,
    MARKET_STRUCTURE_INDICATOR_ID,
    MARKET_STRUCTURE_METADATA_VERSION,
    MARKET_STRUCTURE_METHOD_VERSION,
    BreakDirection,
    MarketStructureAnalysis,
    MarketStructureScale,
    StructuralBreak,
    StructureEventType,
)
from trading_platform_api.analysis.price_action import (
    _INTERVALS,
    PRICE_ACTION_METADATA_VERSION,
    PRICE_ACTION_METHOD_VERSION,
    PivotKind,
    PivotObservation,
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
    DataQualityStatus,
    MarketData,
    MarketSnapshot,
)

SPOT_SMC_INDICATOR_ID = "spot-smart-money-concepts"
SPOT_SMC_METADATA_VERSION = "1"
SPOT_SMC_METHOD_VERSION = "spot-smc-v1"
SPOT_SMC_EVIDENCE_VERSION = "spot-smc-evidence-v1"
_MAX_CANDLES = 10_000
_MAX_SWEEP_COMPARISONS = 1_000_000
_MAX_LIFECYCLE_COMPARISONS = 1_000_000
_MAX_POLICY_TEXT = 128
_WORK_PRECISION = 512
_RATIO_PRECISION = 34
_IDENTITY_NAMESPACE = UUID("1a501d06-86d0-5e41-9e23-6fd7874cb13b")
_LIMITATIONS = (
    "Descriptive Spot OHLCV observations only; not a signal, recommendation, "
    "validation, risk decision, approval, or execution permission.",
    "OHLCV-derived heuristic only; no hidden stops, confirmed stop clusters, "
    "institutional intent, order-book liquidity, or order flow is inferred.",
    "No probability, predictive value, profitability, guaranteed support/resistance, "
    "or future market direction is asserted.",
    "Internal and external are caller-designated pivot scales on one timeframe; "
    "no multi-timeframe inference is made.",
)
_UNCERTAINTY = (
    "All observations derive from the same Spot OHLCV source and are correlated.",
    "Potential liquidity areas are heuristic price groupings, not observed orders.",
)


class SpotSMCError(ValueError):
    """Spot SMC observations cannot be calculated safely."""


@dataclass(frozen=True, slots=True)
class SpotSMCPolicy:
    """Immutable caller-owned thresholds; no registry defaults are applied."""

    policy_id: str
    version: str
    price_tolerance: Decimal
    sweep_buffer: Decimal
    minimum_pivot_count: int
    order_block_lookback: int
    displacement_lookback: int
    minimum_body_fraction: Decimal
    minimum_range_multiple: Decimal
    maximum_output_records: int

    def __post_init__(self) -> None:
        for name in ("policy_id", "version"):
            value = getattr(self, name)
            if (
                not isinstance(value, str)
                or not value
                or value != value.strip()
                or len(value) > _MAX_POLICY_TEXT
            ):
                raise SpotSMCError(f"{name} must be bounded nonblank text.")
        try:
            tolerance = _bounded_decimal("price_tolerance", self.price_tolerance)
            buffer = _bounded_decimal("sweep_buffer", self.sweep_buffer)
            body = _bounded_decimal("minimum_body_fraction", self.minimum_body_fraction)
            multiple = _bounded_decimal(
                "minimum_range_multiple", self.minimum_range_multiple
            )
        except (TypeError, ValueError) as exc:
            raise SpotSMCError(
                "SMC policy decimals must be bounded finite Decimals."
            ) from exc
        if tolerance <= 0:
            raise SpotSMCError("price_tolerance must be strictly positive.")
        if buffer < 0:
            raise SpotSMCError("sweep_buffer must not be negative.")
        if not Decimal(0) <= body <= Decimal(1):
            raise SpotSMCError("minimum_body_fraction must be in [0, 1].")
        if not Decimal(0) < multiple <= Decimal(1000):
            raise SpotSMCError("minimum_range_multiple must be in (0, 1000].")
        for name, value in (
            ("minimum_pivot_count", self.minimum_pivot_count),
            ("order_block_lookback", self.order_block_lookback),
            ("displacement_lookback", self.displacement_lookback),
            ("maximum_output_records", self.maximum_output_records),
        ):
            maximum = _MAX_CANDLES if name == "maximum_output_records" else 500
            minimum = 2 if name == "minimum_pivot_count" else 1
            if type(value) is not int or not minimum <= value <= maximum:
                raise SpotSMCError(f"{name} must be in [{minimum}, {maximum}].")


_AttributeValue: TypeAlias = (
    str
    | Decimal
    | bool
    | int
    | UUID
    | datetime
    | None
    | tuple[str | Decimal | UUID | datetime, ...]
)


@dataclass(frozen=True, slots=True)
class SMCAttribute:
    name: str
    value: _AttributeValue

    def __post_init__(self) -> None:
        if (
            not isinstance(self.name, str)
            or not self.name
            or self.name != self.name.strip()
            or len(self.name) > 128
        ):
            raise SpotSMCError("SMC attribute names must be bounded nonblank text.")
        value = self.value
        if value is not None and type(value) not in (
            str,
            Decimal,
            bool,
            int,
            UUID,
            datetime,
            tuple,
        ):
            raise SpotSMCError("SMC attributes contain an unsupported value.")
        if isinstance(value, Decimal):
            try:
                _bounded_decimal(self.name, value)
            except ValueError as exc:
                raise SpotSMCError("SMC attribute Decimal is not bounded.") from exc
        if isinstance(value, datetime) and (
            value.tzinfo is None or value.utcoffset() is None
        ):
            raise SpotSMCError("SMC attribute timestamps must be timezone-aware.")
        if isinstance(value, tuple) and not all(
            type(item) in (str, Decimal, UUID, datetime) for item in value
        ):
            raise SpotSMCError("SMC attribute tuple contains an unsupported value.")


@dataclass(frozen=True, slots=True)
class SMCObject:
    """C-008 evidence payload record shared by all deterministic SMC observations."""

    object_id: UUID
    category: str
    subtype: str
    asset: str
    instrument_id: str
    venue_id: str
    timeframe: str
    price_unit: str
    lower_price: Decimal | None
    upper_price: Decimal | None
    creation_time: datetime
    available_at: datetime
    as_of: datetime
    source_market_data_ids: tuple[UUID, ...]
    source_pivot_ids: tuple[UUID, ...]
    source_event_ids: tuple[UUID, ...]
    detection_rule: str
    method_version: str
    policy_id: str
    policy_version: str
    policy_parameters: SpotSMCPolicy
    lifecycle_state: str
    mitigation_percentage: Decimal | None
    supporting_evidence_ids: tuple[UUID, ...]
    uncertainty: tuple[str, ...]
    limitations: tuple[str, ...]
    expires_at: datetime
    invalidation_condition: str
    details: tuple[SMCAttribute, ...]

    def __post_init__(self) -> None:
        for name in (
            "category",
            "subtype",
            "asset",
            "instrument_id",
            "venue_id",
            "timeframe",
            "price_unit",
            "detection_rule",
            "method_version",
            "policy_id",
            "policy_version",
            "lifecycle_state",
            "invalidation_condition",
        ):
            value = getattr(self, name)
            if not isinstance(value, str) or not value or value != value.strip():
                raise SpotSMCError(f"{name} must be nonblank text.")
        if type(self.object_id) is not UUID:
            raise SpotSMCError("object_id must be a UUID.")
        for name in (
            "creation_time",
            "available_at",
            "as_of",
            "expires_at",
        ):
            value = getattr(self, name)
            if (
                not isinstance(value, datetime)
                or value.tzinfo is None
                or value.utcoffset() is None
            ):
                raise SpotSMCError(f"{name} must be timezone-aware.")
        if self.creation_time > self.as_of or self.creation_time > self.available_at:
            raise SpotSMCError("SMC creation and availability times are inconsistent.")
        if self.available_at > self.expires_at:
            raise SpotSMCError("SMC observation cannot expire before it is available.")
        if (self.lower_price is None) != (self.upper_price is None):
            raise SpotSMCError("SMC price range bounds must both be present or absent.")
        if self.lower_price is not None and self.upper_price is not None:
            try:
                _bounded_decimal("lower_price", self.lower_price)
                _bounded_decimal("upper_price", self.upper_price)
            except ValueError as exc:
                raise SpotSMCError("SMC price range is not bounded.") from exc
            if self.lower_price > self.upper_price:
                raise SpotSMCError("SMC lower price must not exceed upper price.")
        for name in (
            "source_market_data_ids",
            "source_pivot_ids",
            "source_event_ids",
            "supporting_evidence_ids",
        ):
            values = getattr(self, name)
            if (
                type(values) is not tuple
                or not all(type(item) is UUID for item in values)
                or len(set(values)) != len(values)
            ):
                raise SpotSMCError(f"{name} must be a unique UUID tuple.")
        if not self.source_market_data_ids or not self.supporting_evidence_ids:
            raise SpotSMCError("Every SMC object requires market and C-008 lineage.")
        if not isinstance(self.policy_parameters, SpotSMCPolicy):
            raise SpotSMCError("Every SMC object requires its exact caller policy.")
        if self.mitigation_percentage is not None:
            try:
                _bounded_decimal("mitigation_percentage", self.mitigation_percentage)
            except ValueError as exc:
                raise SpotSMCError("mitigation_percentage is not bounded.") from exc
            if not Decimal(0) <= self.mitigation_percentage <= Decimal(100):
                raise SpotSMCError("mitigation_percentage must be in [0, 100].")
        if (
            type(self.details) is not tuple
            or not all(type(item) is SMCAttribute for item in self.details)
            or len({item.name for item in self.details}) != len(self.details)
        ):
            raise SpotSMCError("SMC details must be uniquely named immutable values.")
        if type(self.uncertainty) is not tuple or type(self.limitations) is not tuple:
            raise SpotSMCError("SMC uncertainty and limitations must be immutable.")


@dataclass(frozen=True, slots=True)
class SpotSMCAnalysis:
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
    policy: SpotSMCPolicy
    objects: tuple[SMCObject, ...]
    evidence: EvidenceItem
    assessment: SMCAssessment


@dataclass(frozen=True, slots=True)
class _Candle:
    observation: MarketData
    opening: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    end: datetime


@dataclass(frozen=True, slots=True)
class _Displacement:
    candle_index: int
    direction: BreakDirection | None
    qualifies: bool
    body_fraction: Decimal | None
    range_value: Decimal
    prior_median_range: Decimal | None
    reason: str | None


@dataclass(frozen=True, slots=True)
class _SMCEvidence:
    payload_version: str
    method_version: str
    indicator_id: str
    metadata_version: str
    timeframe: str
    asset: str
    instrument_id: str
    venue_id: str
    price_unit: str
    snapshot_id: UUID
    quality_report_id: UUID
    as_of: datetime
    evidence_expires_at: datetime
    source_record_ids: tuple[UUID, ...]
    input_market_data_ids: tuple[UUID, ...]
    source_market_structure_evidence_id: UUID
    source_market_structure_method_version: str
    internal_pivot_policy: SupportResistancePolicy
    external_pivot_policy: SupportResistancePolicy
    smc_policy: SpotSMCPolicy
    objects: tuple[SMCObject, ...]
    uncertainty: tuple[str, ...]
    limitations: tuple[str, ...]


def _stable_id(*parts: object) -> UUID:
    return uuid5(_IDENTITY_NAMESPACE, canonical_json_dumps(parts))


def _immutable_json(value: object) -> object:
    if isinstance(value, list):
        return tuple(_immutable_json(item) for item in value)
    if isinstance(value, dict):
        return {key: _immutable_json(item) for key, item in value.items()}
    return value


def _validate_structure_input(
    *,
    structure: MarketStructureAnalysis,
    snapshot: MarketSnapshot,
    observations: tuple[MarketData, ...],
    quality: DataQualityReport,
    timeframe: str,
) -> None:
    if type(structure) is not MarketStructureAnalysis:
        raise SpotSMCError("The exact #56 MarketStructureAnalysis is required.")
    if (
        structure.indicator_id != MARKET_STRUCTURE_INDICATOR_ID
        or structure.metadata_version != MARKET_STRUCTURE_METADATA_VERSION
        or structure.method_version != MARKET_STRUCTURE_METHOD_VERSION
    ):
        raise SpotSMCError("Unknown exact #56 method or metadata version.")
    if (
        structure.snapshot_id != snapshot.snapshot_id
        or structure.quality_report_id != quality.report_id
        or structure.instrument_id != snapshot.instrument_id
        or structure.venue_id != snapshot.venue_id
        or structure.asset != snapshot.instrument_id
        or structure.timeframe != timeframe
        or structure.as_of != snapshot.as_of
        or structure.source_record_ids != snapshot.source_record_ids
        or structure.input_market_data_ids != snapshot.market_data_ids
        or tuple(item.market_data_id for item in observations)
        != snapshot.market_data_ids
    ):
        raise SpotSMCError("#56 output lineage does not match the exact input.")
    if (
        type(structure.evidence) is not EvidenceItem
        or structure.evidence.contract_id != "C-008"
        or structure.evidence.method
        != VersionReference(
            MARKET_STRUCTURE_INDICATOR_ID, MARKET_STRUCTURE_METHOD_VERSION
        )
        or structure.evidence.data_quality_report_id != quality.report_id
        or structure.evidence.source_record_ids != snapshot.source_record_ids
        or structure.evidence.quality_status is not DataQualityStatus.VALID
        or not structure.evidence.usable
        or structure.evidence.expires_at != structure.evidence_expires_at
    ):
        raise SpotSMCError("#56 C-008 evidence lineage is invalid.")
    if (
        type(structure.assessment) is not TechnicalAssessment
        or structure.assessment.contract_id != "C-012"
        or structure.assessment.assessment_id is None
        or structure.assessment.data_quality_report_id != quality.report_id
        or structure.assessment.evidence_ids != (structure.evidence.evidence_id,)
        or structure.assessment.instrument_id != snapshot.instrument_id
        or structure.assessment.timeframe != timeframe
        or structure.assessment.as_of != snapshot.as_of
        or structure.assessment.status is not AssessmentStatus.AVAILABLE
    ):
        raise SpotSMCError("#56 C-012 assessment lineage is invalid.")
    try:
        metadata = SPOT_RESEARCH_INDICATORS.get(
            structure.indicator_id, structure.metadata_version
        )
    except IndicatorMetadataError as exc:
        raise SpotSMCError("Exact #56 registry lookup failed.") from exc
    if (
        metadata.phase is not IndicatorPhase.VALIDATED
        or metadata.calculation_version != MARKET_STRUCTURE_METHOD_VERSION
        or timeframe not in metadata.timeframes
    ):
        raise SpotSMCError("Exact #56 method is not validated for this timeframe.")
    try:
        encoded = structure.evidence.value
        if (
            type(encoded) is not str
            or len(encoded.encode("utf-8")) > MAX_DOCUMENT_BYTES
        ):
            raise SpotSMCError("#56 C-008 evidence is invalid or oversized.")
        payload = json.loads(encoded)
        if (
            type(payload) is not dict
            or canonical_json_dumps(_immutable_json(payload)) != encoded
        ):
            raise SpotSMCError("#56 C-008 evidence is not canonical.")
        expected = {
            "payload_version": MARKET_STRUCTURE_EVIDENCE_VERSION,
            "method_version": structure.method_version,
            "timeframe": timeframe,
            "asset": structure.asset,
            "instrument_id": snapshot.instrument_id,
            "venue_id": snapshot.venue_id,
            "price_unit": structure.price_unit,
            "snapshot_id": snapshot.snapshot_id,
            "quality_report_id": quality.report_id,
            "as_of": snapshot.as_of,
            "source_record_ids": snapshot.source_record_ids,
            "input_market_data_ids": snapshot.market_data_ids,
            "internal_pivot_policy": structure.internal_pivot_policy,
            "external_pivot_policy": structure.external_pivot_policy,
            "break_policy": structure.break_policy,
            "internal_pivot_method_version": PRICE_ACTION_METHOD_VERSION,
            "internal_pivot_metadata_version": PRICE_ACTION_METADATA_VERSION,
            "external_pivot_method_version": PRICE_ACTION_METHOD_VERSION,
            "external_pivot_metadata_version": PRICE_ACTION_METADATA_VERSION,
            "swings": structure.swings,
            "states": structure.states,
            "events": structure.events,
            "uncertainty": structure.uncertainty,
            "limitations": structure.limitations,
        }
        if any(
            key not in payload
            or canonical_json_dumps(_immutable_json(payload[key]))
            != canonical_json_dumps(value)
            for key, value in expected.items()
        ):
            raise SpotSMCError("#56 C-008 evidence differs from its exact output.")
    except SpotSMCError:
        raise
    except (
        UnicodeError,
        json.JSONDecodeError,
        RecursionError,
        TypeError,
        ValueError,
    ) as exc:
        raise SpotSMCError("#56 C-008 evidence is invalid.") from exc
    if type(structure.events) is not tuple or not all(
        type(event) is StructuralBreak for event in structure.events
    ):
        raise SpotSMCError("#56 events must be an immutable exact output tuple.")


def _object(
    *,
    category: str,
    subtype: str,
    snapshot: MarketSnapshot,
    timeframe: str,
    price_unit: str,
    lower_price: Decimal | None,
    upper_price: Decimal | None,
    creation_time: datetime,
    available_at: datetime | None = None,
    source_market_data_ids: tuple[UUID, ...],
    source_pivot_ids: tuple[UUID, ...],
    source_event_ids: tuple[UUID, ...],
    detection_rule: str,
    policy: SpotSMCPolicy,
    lifecycle_state: str,
    mitigation_percentage: Decimal | None,
    supporting_evidence_ids: tuple[UUID, ...],
    expires_at: datetime,
    invalidation_condition: str,
    details: tuple[SMCAttribute, ...],
) -> SMCObject:
    identity = _stable_id(
        SPOT_SMC_METHOD_VERSION,
        category,
        subtype,
        snapshot.snapshot_id,
        source_market_data_ids,
        source_pivot_ids,
        source_event_ids,
        policy,
    )
    return SMCObject(
        object_id=identity,
        category=category,
        subtype=subtype,
        asset=snapshot.instrument_id,
        instrument_id=snapshot.instrument_id,
        venue_id=snapshot.venue_id,
        timeframe=timeframe,
        price_unit=price_unit,
        lower_price=lower_price,
        upper_price=upper_price,
        creation_time=creation_time,
        available_at=available_at or creation_time,
        as_of=snapshot.as_of,
        source_market_data_ids=source_market_data_ids,
        source_pivot_ids=source_pivot_ids,
        source_event_ids=source_event_ids,
        detection_rule=detection_rule,
        method_version=SPOT_SMC_METHOD_VERSION,
        policy_id=policy.policy_id,
        policy_version=policy.version,
        policy_parameters=policy,
        lifecycle_state=lifecycle_state,
        mitigation_percentage=mitigation_percentage,
        supporting_evidence_ids=supporting_evidence_ids,
        uncertainty=_UNCERTAINTY,
        limitations=_LIMITATIONS,
        expires_at=expires_at,
        invalidation_condition=invalidation_condition,
        details=details,
    )


def _penetration(*, proximal: Decimal, far: Decimal, extreme: Decimal) -> Decimal:
    width = abs(proximal - far)
    if width == 0:
        beyond_proximal = (
            extreme <= proximal if proximal >= far else extreme >= proximal
        )
        return Decimal(100) if beyond_proximal else Decimal(0)
    with localcontext() as context:
        context.prec = _RATIO_PRECISION
        raw_distance = proximal - extreme if proximal > far else extreme - proximal
        distance = min(width, max(Decimal(0), raw_distance))
        return distance / width * Decimal(100)


def _fvg_objects(
    *,
    candles: tuple[_Candle, ...],
    snapshot: MarketSnapshot,
    timeframe: str,
    price_unit: str,
    policy: SpotSMCPolicy,
    supporting_evidence_ids: tuple[UUID, ...],
    expires_at: datetime,
) -> list[SMCObject]:
    result: list[SMCObject] = []
    lifecycle_comparisons = 0
    for index in range(2, len(candles)):
        first, third = candles[index - 2], candles[index]
        if third.low > first.high:
            direction = "bullish"
            lower, upper = first.high, third.low
            proximal, far = upper, lower
        elif third.high < first.low:
            direction = "bearish"
            lower, upper = third.high, first.low
            proximal, far = lower, upper
        else:
            continue
        maximum_fill = Decimal(0)
        state = "active"
        available_at = third.end
        invalidated_at: _Candle | None = None
        lifecycle_ids: list[UUID] = []
        for later in candles[index + 1 :]:
            lifecycle_comparisons += 1
            if lifecycle_comparisons > _MAX_LIFECYCLE_COMPARISONS:
                raise SpotSMCError("FVG lifecycle work exceeds its bounded limit.")
            lifecycle_ids.append(later.observation.market_data_id)
            penetration_extreme = later.low if direction == "bullish" else later.high
            current_fill = _penetration(
                proximal=proximal, far=far, extreme=penetration_extreme
            )
            maximum_fill = max(maximum_fill, current_fill)
            beyond_far_edge = (
                later.close < far if direction == "bullish" else later.close > far
            )
            if beyond_far_edge:
                state = "invalidated"
                maximum_fill = Decimal(100)
                available_at = later.end
                invalidated_at = later
                break
            if maximum_fill == Decimal(100):
                state = "filled"
            if maximum_fill > 0:
                if state != "filled":
                    state = "partially-filled"
            available_at = later.end
        rule = (
            "Bullish FVG when third closed candle low is strictly above first "
            "closed candle high; bearish FVG when third high is strictly below "
            "first low. Equality is not a gap. Only later candles update wick fill."
        )
        result.append(
            _object(
                category="fair-value-gap",
                subtype=direction,
                snapshot=snapshot,
                timeframe=timeframe,
                price_unit=price_unit,
                lower_price=lower,
                upper_price=upper,
                creation_time=third.end,
                available_at=available_at,
                source_market_data_ids=(
                    first.observation.market_data_id,
                    candles[index - 1].observation.market_data_id,
                    third.observation.market_data_id,
                    *lifecycle_ids,
                ),
                source_pivot_ids=(),
                source_event_ids=(),
                detection_rule=rule,
                policy=policy,
                lifecycle_state=state,
                mitigation_percentage=maximum_fill,
                supporting_evidence_ids=supporting_evidence_ids,
                expires_at=expires_at,
                invalidation_condition=(
                    "Invalidated terminally only when a later closed candle closes "
                    "strictly beyond the far edge; a wick at the far edge is filled."
                ),
                details=(
                    SMCAttribute("direction", direction),
                    SMCAttribute(
                        "creation_candle_id", third.observation.market_data_id
                    ),
                    SMCAttribute("proximal_edge", proximal),
                    SMCAttribute("far_edge", far),
                    SMCAttribute("maximum_wick_fill_percentage", maximum_fill),
                    SMCAttribute(
                        "invalidating_candle_id",
                        invalidated_at.observation.market_data_id
                        if invalidated_at
                        else None,
                    ),
                    SMCAttribute(
                        "invalidation_time",
                        invalidated_at.end if invalidated_at else None,
                    ),
                ),
            )
        )
        if len(result) > policy.maximum_output_records:
            raise SpotSMCError("Spot SMC output exceeds the caller policy bound.")
    return result


def _liquidity_objects(
    *,
    structure: MarketStructureAnalysis,
    candles: tuple[_Candle, ...],
    snapshot: MarketSnapshot,
    timeframe: str,
    price_unit: str,
    policy: SpotSMCPolicy,
    supporting_evidence_ids: tuple[UUID, ...],
    expires_at: datetime,
    output_records_already_built: int,
) -> list[SMCObject]:
    if output_records_already_built > policy.maximum_output_records:
        raise SpotSMCError("Spot SMC output exceeds the caller policy bound.")
    areas: list[SMCObject] = []
    pivots = tuple(swing.pivot for swing in structure.swings)
    for kind in (PivotKind.HIGH, PivotKind.LOW):
        ordered = sorted(
            (pivot for pivot in pivots if pivot.kind is kind),
            key=lambda pivot: (pivot.source_time, pivot.pivot_id.hex),
        )
        groups: list[list[PivotObservation]] = []
        anchor: Decimal | None = None
        for pivot in ordered:
            if (
                not groups
                or anchor is None
                or abs(pivot.price - anchor) > policy.price_tolerance
            ):
                groups.append([pivot])
                anchor = pivot.price
            else:
                groups[-1].append(pivot)
        for group in groups:
            if len(group) < policy.minimum_pivot_count:
                continue
            if (
                output_records_already_built + len(areas)
                >= policy.maximum_output_records
            ):
                raise SpotSMCError("Spot SMC output exceeds the caller policy bound.")
            typed_group = tuple(group)
            prices = tuple(item.price for item in typed_group)
            creation_time = max(item.confirmation_time for item in typed_group)
            lower, upper = min(prices), max(prices)
            subtype = (
                "potential-high-side-area"
                if kind is PivotKind.HIGH
                else "potential-low-side-area"
            )
            area = _object(
                category="liquidity",
                subtype=subtype,
                snapshot=snapshot,
                timeframe=timeframe,
                price_unit=price_unit,
                lower_price=lower,
                upper_price=upper,
                creation_time=creation_time,
                source_market_data_ids=tuple(
                    dict.fromkeys(item.source_market_data_id for item in typed_group)
                ),
                source_pivot_ids=tuple(item.pivot_id for item in typed_group),
                source_event_ids=(),
                detection_rule=(
                    "Group confirmed pivots of the same kind in source-time order "
                    "within price_tolerance of the fixed first-pivot anchor; each "
                    "pivot is assigned once and a group requires minimum_pivot_count."
                ),
                policy=policy,
                lifecycle_state="potential-area",
                mitigation_percentage=None,
                supporting_evidence_ids=supporting_evidence_ids,
                expires_at=expires_at,
                invalidation_condition=(
                    "Superseded by source-pivot correction or a new exact method or "
                    "caller-policy version; not a confirmed stop cluster."
                ),
                details=(
                    SMCAttribute("pivot_kind", kind.value),
                    SMCAttribute("anchor_price", typed_group[0].price),
                    SMCAttribute(
                        "pivot_ids", tuple(item.pivot_id for item in typed_group)
                    ),
                    SMCAttribute(
                        "pivot_prices",
                        tuple(item.price for item in typed_group),
                    ),
                    SMCAttribute(
                        "pivot_source_times",
                        tuple(item.source_time for item in typed_group),
                    ),
                ),
            )
            areas.append(area)
            if (
                output_records_already_built + len(areas)
                > policy.maximum_output_records
            ):
                raise SpotSMCError("Spot SMC output exceeds the caller policy bound.")
    if len(areas) * len(candles) > _MAX_SWEEP_COMPARISONS:
        raise SpotSMCError("Potential-liquidity sweep work exceeds its bounded limit.")
    sweeps: list[SMCObject] = []
    for area in areas:
        kind = PivotKind.HIGH if "high-side" in area.subtype else PivotKind.LOW
        assert area.lower_price is not None and area.upper_price is not None
        for candle in candles:
            if candle.end <= area.available_at:
                continue
            if kind is PivotKind.HIGH:
                qualifies = (
                    candle.high > area.upper_price + policy.sweep_buffer
                    and candle.close <= area.upper_price
                )
                extreme = candle.high
                depth = candle.high - area.upper_price
                side = "high-side"
            else:
                qualifies = (
                    candle.low < area.lower_price - policy.sweep_buffer
                    and candle.close >= area.lower_price
                )
                extreme = candle.low
                depth = area.lower_price - candle.low
                side = "low-side"
            if not qualifies:
                continue
            if (
                output_records_already_built + len(areas) + len(sweeps)
                >= policy.maximum_output_records
            ):
                raise SpotSMCError("Spot SMC output exceeds the caller policy bound.")
            sweeps.append(
                _object(
                    category="liquidity",
                    subtype="liquidity-sweep",
                    snapshot=snapshot,
                    timeframe=timeframe,
                    price_unit=price_unit,
                    lower_price=area.lower_price,
                    upper_price=area.upper_price,
                    creation_time=candle.end,
                    source_market_data_ids=(
                        *area.source_market_data_ids,
                        candle.observation.market_data_id,
                    ),
                    source_pivot_ids=area.source_pivot_ids,
                    source_event_ids=(),
                    detection_rule=(
                        f"Potential {side} sweep requires a closed candle extreme "
                        "strictly beyond the area edge plus/minus sweep_buffer and "
                        "close at or inside that edge; equality is not a sweep."
                    ),
                    policy=policy,
                    lifecycle_state="reclaimed",
                    mitigation_percentage=None,
                    supporting_evidence_ids=supporting_evidence_ids,
                    expires_at=expires_at,
                    invalidation_condition=(
                        "Superseded by correction of the source candle, pivot area, "
                        "or exact method/policy version."
                    ),
                    details=(
                        SMCAttribute("area_id", area.object_id),
                        SMCAttribute("side", side),
                        SMCAttribute(
                            "source_candle_id", candle.observation.market_data_id
                        ),
                        SMCAttribute("extreme", extreme),
                        SMCAttribute("wick_depth", depth),
                        SMCAttribute("close", candle.close),
                        SMCAttribute("reclaimed", True),
                        SMCAttribute("sweep_time", candle.end),
                    ),
                )
            )
    return areas + sweeps


def _median_decimal(values: tuple[Decimal, ...]) -> Decimal:
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / Decimal(2)


def _displacement_measures(
    *,
    candles: tuple[_Candle, ...],
    policy: SpotSMCPolicy,
) -> tuple[_Displacement, ...]:
    result: list[_Displacement] = []
    for index, candle in enumerate(candles):
        candle_range = candle.high - candle.low
        body = abs(candle.close - candle.opening)
        direction = (
            BreakDirection.UP
            if candle.close > candle.opening
            else BreakDirection.DOWN
            if candle.close < candle.opening
            else None
        )
        if index < policy.displacement_lookback:
            result.append(
                _Displacement(
                    index,
                    direction,
                    False,
                    None,
                    candle_range,
                    None,
                    "insufficient-prior-range-history",
                )
            )
            continue
        prior_ranges = tuple(
            candles[item].high - candles[item].low
            for item in range(index - policy.displacement_lookback, index)
        )
        prior_median = _median_decimal(prior_ranges)
        if candle_range == 0:
            result.append(
                _Displacement(
                    index, None, False, None, candle_range, prior_median, "zero-range"
                )
            )
            continue
        with localcontext() as context:
            context.prec = _RATIO_PRECISION
            body_fraction = body / candle_range
        qualifies = (
            direction is not None
            and body_fraction >= policy.minimum_body_fraction
            and candle_range >= prior_median * policy.minimum_range_multiple
        )
        reason = None if qualifies else "threshold-not-met" if direction else "doji"
        result.append(
            _Displacement(
                index,
                direction,
                qualifies,
                body_fraction,
                candle_range,
                prior_median,
                reason,
            )
        )
    return tuple(result)


def _displacement_objects(
    *,
    candles: tuple[_Candle, ...],
    measures: tuple[_Displacement, ...],
    snapshot: MarketSnapshot,
    timeframe: str,
    price_unit: str,
    policy: SpotSMCPolicy,
    supporting_evidence_ids: tuple[UUID, ...],
    expires_at: datetime,
) -> list[SMCObject]:
    result: list[SMCObject] = []
    for measure in measures:
        candle = candles[measure.candle_index]
        history = tuple(
            item.observation.market_data_id
            for item in candles[
                max(
                    0, measure.candle_index - policy.displacement_lookback
                ) : measure.candle_index
            ]
        )
        result.append(
            _object(
                category="displacement",
                subtype=measure.direction.value if measure.direction else "unavailable",
                snapshot=snapshot,
                timeframe=timeframe,
                price_unit=price_unit,
                lower_price=candle.low,
                upper_price=candle.high,
                creation_time=candle.end,
                source_market_data_ids=(candle.observation.market_data_id, *history),
                source_pivot_ids=(),
                source_event_ids=(),
                detection_rule=(
                    "A non-zero-range closed candle qualifies only when its body/range "
                    "is at least minimum_body_fraction and its range is at least "
                    "minimum_range_multiple times the median range of the immediately "
                    "preceding displacement_lookback candles; complete history required."
                ),
                policy=policy,
                lifecycle_state=(
                    "unavailable"
                    if measure.reason == "insufficient-prior-range-history"
                    else "displacement"
                    if measure.qualifies
                    else "not-displacement"
                ),
                mitigation_percentage=None,
                supporting_evidence_ids=supporting_evidence_ids,
                expires_at=expires_at,
                invalidation_condition=(
                    "Superseded by source candle correction or exact method/policy change."
                ),
                details=(
                    SMCAttribute("source_candle_id", candle.observation.market_data_id),
                    SMCAttribute(
                        "direction",
                        measure.direction.value if measure.direction else None,
                    ),
                    SMCAttribute("body", abs(candle.close - candle.opening)),
                    SMCAttribute("range", measure.range_value),
                    SMCAttribute("body_fraction", measure.body_fraction),
                    SMCAttribute("prior_median_range", measure.prior_median_range),
                    SMCAttribute("qualifies", measure.qualifies),
                    SMCAttribute("unavailable_reason", measure.reason),
                    SMCAttribute("prior_candle_ids", history),
                ),
            )
        )
    return result


def _structure_event_objects(
    *,
    structure: MarketStructureAnalysis,
    candles: tuple[_Candle, ...],
    snapshot: MarketSnapshot,
    timeframe: str,
    price_unit: str,
    policy: SpotSMCPolicy,
    expires_at: datetime,
    output_records_already_built: int,
) -> tuple[list[SMCObject], dict[UUID, tuple[StructuralBreak, int]]]:
    result: list[SMCObject] = []
    event_map: dict[UUID, tuple[StructuralBreak, int]] = {}
    data_index = {
        candle.observation.market_data_id: index for index, candle in enumerate(candles)
    }
    for event in structure.events:
        category = {
            StructureEventType.BREAK_OF_STRUCTURE: "bos",
            StructureEventType.CHANGE_OF_CHARACTER: "choch",
            StructureEventType.MARKET_STRUCTURE_SHIFT: "mss",
        }.get(event.event_type)
        if category is None:
            continue
        if output_records_already_built + len(result) >= policy.maximum_output_records:
            raise SpotSMCError("Spot SMC output exceeds the caller policy bound.")
        if (
            event.instrument_id != snapshot.instrument_id
            or event.venue_id != snapshot.venue_id
            or event.timeframe != timeframe
            or event.confirmation_time > snapshot.as_of
            or event.confirming_market_data_id not in data_index
            or event.reference_pivot.source_market_data_id not in data_index
            or event.confirmation_time
            != candles[data_index[event.confirming_market_data_id]].end
        ):
            raise SpotSMCError("#56 structural event has invalid source lineage.")
        event_id = _stable_id(
            "market-structure-event",
            structure.evidence.evidence_id,
            event,
        )
        event_map[event_id] = (event, data_index[event.confirming_market_data_id])
        result.append(
            _object(
                category=category,
                subtype=f"{event.scale.value}-{event.direction.value}",
                snapshot=snapshot,
                timeframe=timeframe,
                price_unit=price_unit,
                lower_price=event.reference_price,
                upper_price=event.reference_price,
                creation_time=event.confirmation_time,
                source_market_data_ids=tuple(
                    dict.fromkeys(
                        (
                            event.reference_pivot.source_market_data_id,
                            event.reference_pivot.confirmation_market_data_id,
                            event.confirming_market_data_id,
                        )
                    )
                ),
                source_pivot_ids=(event.reference_pivot.pivot_id,),
                source_event_ids=(event_id,),
                detection_rule=event.detection_rule,
                policy=policy,
                lifecycle_state="confirmed-structure-event",
                mitigation_percentage=None,
                supporting_evidence_ids=(structure.evidence.evidence_id,),
                expires_at=expires_at,
                invalidation_condition=event.invalidation_condition,
                details=(
                    SMCAttribute("source_event_type", event.event_type.value),
                    SMCAttribute("source_scale", event.scale.value),
                    SMCAttribute("source_direction", event.direction.value),
                    SMCAttribute(
                        "source_market_structure_evidence_id",
                        structure.evidence.evidence_id,
                    ),
                    SMCAttribute("reference_price", event.reference_price),
                    SMCAttribute("confirming_close", event.confirming_close),
                    SMCAttribute(
                        "confirming_market_data_id", event.confirming_market_data_id
                    ),
                    SMCAttribute(
                        "confirming_candle_time", event.confirming_candle_time
                    ),
                    SMCAttribute("confirmation_time", event.confirmation_time),
                    SMCAttribute("break_buffer", event.break_buffer),
                    SMCAttribute(
                        "consecutive_close_count", event.consecutive_close_count
                    ),
                    SMCAttribute("prior_state", event.prior_state.value),
                ),
            )
        )
    return result, event_map


def _order_block_objects(
    *,
    events: dict[UUID, tuple[StructuralBreak, int]],
    candles: tuple[_Candle, ...],
    measures: tuple[_Displacement, ...],
    snapshot: MarketSnapshot,
    timeframe: str,
    price_unit: str,
    policy: SpotSMCPolicy,
    supporting_evidence_ids: tuple[UUID, ...],
    expires_at: datetime,
    output_records_already_built: int,
) -> list[SMCObject]:
    result: list[SMCObject] = []
    lifecycle_comparisons = 0

    def append_bounded(record: SMCObject) -> None:
        if output_records_already_built + len(result) >= policy.maximum_output_records:
            raise SpotSMCError("Spot SMC output exceeds the caller policy bound.")
        result.append(record)

    for event_id, (event, final_index) in events.items():
        final_measure = measures[final_index]
        expected_direction = event.direction
        if (
            not final_measure.qualifies
            or final_measure.direction is not expected_direction
        ):
            append_bounded(
                _object(
                    category="order-block",
                    subtype="unavailable-no-confirming-displacement",
                    snapshot=snapshot,
                    timeframe=timeframe,
                    price_unit=price_unit,
                    lower_price=None,
                    upper_price=None,
                    creation_time=event.confirmation_time,
                    source_market_data_ids=(event.confirming_market_data_id,),
                    source_pivot_ids=(event.reference_pivot.pivot_id,),
                    source_event_ids=(event_id,),
                    detection_rule=(
                        "Order blocks are considered only for #56 BOS/CHoCH/MSS "
                        "events whose final confirming candle qualifies as displacement "
                        "in the event direction."
                    ),
                    policy=policy,
                    lifecycle_state="unavailable",
                    mitigation_percentage=None,
                    supporting_evidence_ids=supporting_evidence_ids,
                    expires_at=expires_at,
                    invalidation_condition=(
                        "No order block is emitted unless the final confirming candle "
                        "meets the exact caller displacement policy and event direction."
                    ),
                    details=(
                        SMCAttribute(
                            "reason", "final-confirming-candle-not-displacement"
                        ),
                        SMCAttribute("source_event_id", event_id),
                        SMCAttribute("source_event_type", event.event_type.value),
                        SMCAttribute("expected_direction", expected_direction.value),
                    ),
                )
            )
            continue
        first_run_index = final_index - event.consecutive_close_count + 1
        if first_run_index < 0:
            raise SpotSMCError(
                "#56 event confirmation run precedes its source candles."
            )
        lower_search = max(0, first_run_index - policy.order_block_lookback)
        candidates = []
        for index in range(lower_search, first_run_index):
            lifecycle_comparisons += 1
            if lifecycle_comparisons > _MAX_LIFECYCLE_COMPARISONS:
                raise SpotSMCError(
                    "Order-block lookback work exceeds its bounded limit."
                )
            if (
                candles[index].close < candles[index].opening
                if expected_direction is BreakDirection.UP
                else candles[index].close > candles[index].opening
            ):
                candidates.append(index)
        if not candidates:
            append_bounded(
                _object(
                    category="order-block",
                    subtype="unavailable-no-opposing-body",
                    snapshot=snapshot,
                    timeframe=timeframe,
                    price_unit=price_unit,
                    lower_price=None,
                    upper_price=None,
                    creation_time=event.confirmation_time,
                    source_market_data_ids=tuple(
                        candle.observation.market_data_id
                        for candle in candles[lower_search:first_run_index]
                    )
                    or (event.confirming_market_data_id,),
                    source_pivot_ids=(event.reference_pivot.pivot_id,),
                    source_event_ids=(event_id,),
                    detection_rule=(
                        "Select the most recent opposing-body candle in the bounded "
                        "lookback before the event's first consecutive-close confirmation."
                    ),
                    policy=policy,
                    lifecycle_state="unavailable",
                    mitigation_percentage=None,
                    supporting_evidence_ids=supporting_evidence_ids,
                    expires_at=expires_at,
                    invalidation_condition=(
                        "No order block is emitted when no opposing-body candle exists "
                        "inside the caller-bounded lookback."
                    ),
                    details=(
                        SMCAttribute("reason", "no-opposing-body-in-bounded-lookback"),
                        SMCAttribute("source_event_id", event_id),
                        SMCAttribute("lookback_start_index", lower_search),
                        SMCAttribute("first_confirmation_run_index", first_run_index),
                    ),
                )
            )
            continue
        origin_index = candidates[-1]
        origin = candles[origin_index]
        bullish = expected_direction is BreakDirection.UP
        lower, upper = origin.low, origin.high
        proximal, far = (upper, lower) if bullish else (lower, upper)
        direction_name = "bullish" if bullish else "bearish"
        maximum_mitigation = Decimal(0)
        lifecycle_ids: list[UUID] = []
        status = "active"
        invalidated_at: _Candle | None = None
        invalidated_index: int | None = None
        available_at = snapshot.as_of
        for later_index in range(final_index + 1, len(candles)):
            lifecycle_comparisons += 1
            if lifecycle_comparisons > _MAX_LIFECYCLE_COMPARISONS:
                raise SpotSMCError(
                    "Order-block lifecycle work exceeds its bounded limit."
                )
            later = candles[later_index]
            lifecycle_ids.append(later.observation.market_data_id)
            extreme = later.low if bullish else later.high
            maximum_mitigation = max(
                maximum_mitigation,
                _penetration(proximal=proximal, far=far, extreme=extreme),
            )
            invalid = later.close < lower if bullish else later.close > upper
            if invalid:
                status = "invalidated"
                maximum_mitigation = Decimal(100)
                invalidated_at = later
                invalidated_index = later_index
                available_at = later.end
                break
            status = (
                "fully-mitigated"
                if maximum_mitigation == Decimal(100)
                else "partially-mitigated"
                if maximum_mitigation > 0
                else "active"
            )
        rule = (
            "Only a #56 BOS/CHoCH/MSS event whose final confirming candle qualifies "
            "as displacement in the event direction can create an order block. "
            "Choose the most recent opposing-body candle in the bounded lookback "
            "before the event's first consecutive-close confirmation candle; zone "
            "is the full source candle low-high range."
        )
        selection_ids = tuple(
            candles[index].observation.market_data_id
            for index in range(lower_search, first_run_index)
        )
        block = _object(
            category="order-block",
            subtype=direction_name,
            snapshot=snapshot,
            timeframe=timeframe,
            price_unit=price_unit,
            lower_price=lower,
            upper_price=upper,
            creation_time=event.confirmation_time,
            available_at=available_at,
            source_market_data_ids=tuple(
                dict.fromkeys(
                    (
                        *selection_ids,
                        origin.observation.market_data_id,
                        event.confirming_market_data_id,
                        *lifecycle_ids,
                    )
                )
            ),
            source_pivot_ids=(event.reference_pivot.pivot_id,),
            source_event_ids=(event_id,),
            detection_rule=rule,
            policy=policy,
            lifecycle_state=status,
            mitigation_percentage=maximum_mitigation,
            supporting_evidence_ids=supporting_evidence_ids,
            expires_at=expires_at,
            invalidation_condition=(
                "A bullish block is invalidated only by a later close strictly below "
                "its lower edge; a bearish block only by a later close strictly above "
                "its upper edge."
            ),
            details=(
                SMCAttribute("origin_candle_id", origin.observation.market_data_id),
                SMCAttribute("origin_candle_time", origin.observation.event_time),
                SMCAttribute("origin_full_low", lower),
                SMCAttribute("origin_full_high", upper),
                SMCAttribute("source_event_id", event_id),
                SMCAttribute("source_event_type", event.event_type.value),
                SMCAttribute("source_scale", event.scale.value),
                SMCAttribute("source_direction", event.direction.value),
                SMCAttribute(
                    "first_confirmation_run_candle_id",
                    candles[first_run_index].observation.market_data_id,
                ),
                SMCAttribute("proximal_edge", proximal),
                SMCAttribute("far_edge", far),
                SMCAttribute(
                    "invalidating_candle_id",
                    invalidated_at.observation.market_data_id
                    if invalidated_at
                    else None,
                ),
                SMCAttribute(
                    "transition_time", invalidated_at.end if invalidated_at else None
                ),
            ),
        )
        append_bounded(block)
        if invalidated_at is None:
            continue
        breaker_bullish = not bullish
        breaker_direction = "bullish" if breaker_bullish else "bearish"
        breaker_proximal, breaker_far = (
            (upper, lower) if breaker_bullish else (lower, upper)
        )
        breaker_status = "active"
        breaker_mitigation = Decimal(0)
        breaker_ids: list[UUID] = []
        breaker_invalidated_at: _Candle | None = None
        assert invalidated_index is not None
        breaker_available_at = snapshot.as_of
        for later_index in range(invalidated_index + 1, len(candles)):
            lifecycle_comparisons += 1
            if lifecycle_comparisons > _MAX_LIFECYCLE_COMPARISONS:
                raise SpotSMCError("Breaker lifecycle work exceeds its bounded limit.")
            later = candles[later_index]
            breaker_ids.append(later.observation.market_data_id)
            close_invalidates = (
                later.close < lower if breaker_bullish else later.close > upper
            )
            if close_invalidates:
                breaker_status = "invalidated"
                breaker_invalidated_at = later
                breaker_available_at = later.end
                break
            intersects = later.high >= lower and later.low <= upper
            if intersects:
                extreme = later.low if breaker_bullish else later.high
                breaker_mitigation = max(
                    breaker_mitigation,
                    _penetration(
                        proximal=breaker_proximal,
                        far=breaker_far,
                        extreme=extreme,
                    ),
                )
                breaker_status = "mitigated"
        append_bounded(
            _object(
                category="breaker-block",
                subtype=breaker_direction,
                snapshot=snapshot,
                timeframe=timeframe,
                price_unit=price_unit,
                lower_price=lower,
                upper_price=upper,
                creation_time=invalidated_at.end,
                available_at=breaker_available_at,
                source_market_data_ids=tuple(
                    dict.fromkeys(
                        (
                            origin.observation.market_data_id,
                            invalidated_at.observation.market_data_id,
                            *breaker_ids,
                        )
                    )
                ),
                source_pivot_ids=(event.reference_pivot.pivot_id,),
                source_event_ids=(event_id,),
                detection_rule=(
                    "A breaker is created only when its originating order block is "
                    "invalidated; its direction is opposite the block. It becomes "
                    "mitigated only on a later closed-candle range intersection."
                ),
                policy=policy,
                lifecycle_state=breaker_status,
                mitigation_percentage=breaker_mitigation,
                supporting_evidence_ids=supporting_evidence_ids,
                expires_at=expires_at,
                invalidation_condition=(
                    "A bullish breaker is invalidated by a later close strictly below "
                    "its lower/far edge; a bearish breaker by a later close strictly "
                    "above its upper/far edge."
                ),
                details=(
                    SMCAttribute("origin_order_block_id", block.object_id),
                    SMCAttribute(
                        "transition_candle_id",
                        invalidated_at.observation.market_data_id,
                    ),
                    SMCAttribute("transition_time", invalidated_at.end),
                    SMCAttribute("direction", breaker_direction),
                    SMCAttribute("mitigation_percentage", breaker_mitigation),
                    SMCAttribute("origin_event_id", event_id),
                    SMCAttribute(
                        "invalidating_candle_id",
                        breaker_invalidated_at.observation.market_data_id
                        if breaker_invalidated_at
                        else None,
                    ),
                    SMCAttribute(
                        "invalidation_time",
                        breaker_invalidated_at.end if breaker_invalidated_at else None,
                    ),
                ),
            )
        )
    return result


def _premium_discount_object(
    *,
    structure: MarketStructureAnalysis,
    candles: tuple[_Candle, ...],
    snapshot: MarketSnapshot,
    timeframe: str,
    price_unit: str,
    policy: SpotSMCPolicy,
    supporting_evidence_ids: tuple[UUID, ...],
    expires_at: datetime,
) -> SMCObject:
    pivots = tuple(
        swing.pivot
        for swing in structure.swings
        if swing.scale is MarketStructureScale.EXTERNAL
        and swing.pivot.confirmation_time <= snapshot.as_of
    )
    highs = [pivot for pivot in pivots if pivot.kind is PivotKind.HIGH]
    lows = [pivot for pivot in pivots if pivot.kind is PivotKind.LOW]
    high_pivot = (
        max(highs, key=lambda item: (item.confirmation_time, item.source_time))
        if highs
        else None
    )
    low_pivot = (
        max(lows, key=lambda item: (item.confirmation_time, item.source_time))
        if lows
        else None
    )
    last = candles[-1]
    if high_pivot is None or low_pivot is None:
        state, reason, midpoint, lower, upper = (
            "unavailable",
            "missing-latest-confirmed-external-high-or-low",
            None,
            None,
            None,
        )
    elif high_pivot.price <= low_pivot.price:
        state, reason, midpoint, lower, upper = (
            "unavailable",
            "external-high-must-be-strictly-above-external-low",
            None,
            None,
            None,
        )
    else:
        lower, upper = low_pivot.price, high_pivot.price
        with localcontext() as context:
            context.prec = _WORK_PRECISION
            midpoint = (high_pivot.price + low_pivot.price) / Decimal(2)
        state = (
            "premium"
            if last.close > midpoint
            else "discount"
            if last.close < midpoint
            else "equilibrium"
        )
        reason = None
    source_pivots = tuple(
        pivot.pivot_id for pivot in (high_pivot, low_pivot) if pivot is not None
    )
    source_ids = tuple(
        dict.fromkeys(
            (
                last.observation.market_data_id,
                *(
                    pivot.source_market_data_id
                    for pivot in (high_pivot, low_pivot)
                    if pivot
                ),
            )
        )
    )
    return _object(
        category="premium-discount",
        subtype=state,
        snapshot=snapshot,
        timeframe=timeframe,
        price_unit=price_unit,
        lower_price=lower,
        upper_price=upper,
        creation_time=last.end,
        source_market_data_ids=source_ids,
        source_pivot_ids=source_pivots,
        source_event_ids=(),
        detection_rule=(
            "Use the latest confirmed external high and low pivots available at "
            "snapshot cutoff; require positive range and compare last closed price "
            "strictly with their midpoint."
        ),
        policy=policy,
        lifecycle_state=state,
        mitigation_percentage=None,
        supporting_evidence_ids=supporting_evidence_ids,
        expires_at=expires_at,
        invalidation_condition=(
            "Superseded by a new confirmed external anchor, source correction, or "
            "exact method/policy version change; descriptive only."
        ),
        details=(
            SMCAttribute("unavailable_reason", reason),
            SMCAttribute(
                "external_high_pivot_id", high_pivot.pivot_id if high_pivot else None
            ),
            SMCAttribute(
                "external_high_price", high_pivot.price if high_pivot else None
            ),
            SMCAttribute(
                "external_high_time", high_pivot.source_time if high_pivot else None
            ),
            SMCAttribute(
                "external_low_pivot_id", low_pivot.pivot_id if low_pivot else None
            ),
            SMCAttribute("external_low_price", low_pivot.price if low_pivot else None),
            SMCAttribute(
                "external_low_time", low_pivot.source_time if low_pivot else None
            ),
            SMCAttribute("midpoint", midpoint),
            SMCAttribute("last_closed_price", last.close),
        ),
    )


def _evidence_contract(
    *,
    payload: _SMCEvidence,
    snapshot: MarketSnapshot,
    quality: DataQualityReport,
    timeframe: str,
) -> EvidenceItem:
    encoded = canonical_json_dumps(payload)
    if len(encoded.encode("utf-8")) > MAX_DOCUMENT_BYTES:
        raise SpotSMCError("Spot SMC evidence exceeds the output size bound.")
    digest = sha256(encoded.encode("utf-8")).hexdigest()
    evidence_id = _stable_id(
        "evidence",
        snapshot.snapshot_id,
        quality.report_id,
        SPOT_SMC_METHOD_VERSION,
        SPOT_SMC_EVIDENCE_VERSION,
        digest,
    )
    interval = timedelta(seconds=_INTERVALS[timeframe])
    try:
        expires_at = quality.assessed_at + interval
    except OverflowError as exc:
        raise SpotSMCError(
            "Spot SMC evidence expiry exceeds timestamp bounds."
        ) from exc
    return EvidenceItem(
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
        expires_at=expires_at,
        method=VersionReference(SPOT_SMC_INDICATOR_ID, SPOT_SMC_METHOD_VERSION),
        value=encoded,
        unit=payload.price_unit,
        interpretation=(
            "Deterministic, versioned Spot OHLCV Smart Money Concepts observations; "
            "descriptive analysis only."
        ),
        quality_status=quality.status,
        data_quality_report_id=quality.report_id,
        reliability=quality.source_reliability,
        limitations=payload.limitations,
        provenance=(
            VersionReference("C-001", "1"),
            VersionReference("C-002", "1"),
            VersionReference("C-003", "1"),
            VersionReference("C-008", "1"),
            VersionReference("C-013", "1"),
            VersionReference(
                MARKET_STRUCTURE_INDICATOR_ID, MARKET_STRUCTURE_METHOD_VERSION
            ),
            VersionReference("canonical-json", CANONICAL_JSON_VERSION),
            VersionReference("spot-smc-evidence", SPOT_SMC_EVIDENCE_VERSION),
        ),
        usable=True,
    )


def calculate_spot_smc(
    *,
    snapshot: MarketSnapshot,
    observations: tuple[MarketData, ...],
    quality: DataQualityReport,
    timeframe: str,
    market_structure: MarketStructureAnalysis,
    policy: SpotSMCPolicy,
    metadata_version: str = SPOT_SMC_METADATA_VERSION,
) -> SpotSMCAnalysis:
    """Calculate bounded Spot SMC observations from canonical closed OHLCV."""
    if (
        type(snapshot) is not MarketSnapshot
        or type(quality) is not DataQualityReport
        or type(observations) is not tuple
        or not observations
        or len(observations) > _MAX_CANDLES
        or not all(type(item) is MarketData for item in observations)
    ):
        raise SpotSMCError(
            "Canonical bounded snapshot, quality and candles are required."
        )
    if type(policy) is not SpotSMCPolicy:
        raise SpotSMCError("An explicit immutable caller policy is required.")
    if type(timeframe) is not str or timeframe not in _INTERVALS:
        raise SpotSMCError("Unsupported Spot timeframe.")
    if type(metadata_version) is not str:
        raise SpotSMCError("metadata_version must be an exact version string.")
    try:
        metadata = SPOT_RESEARCH_INDICATORS.get(SPOT_SMC_INDICATOR_ID, metadata_version)
    except (IndicatorMetadataError, TypeError) as exc:
        raise SpotSMCError("Unknown exact Spot SMC metadata version.") from exc
    if (
        metadata.phase is not IndicatorPhase.VALIDATED
        or metadata.calculation_version != SPOT_SMC_METHOD_VERSION
        or timeframe not in metadata.timeframes
    ):
        raise SpotSMCError("Spot SMC method is not validated for this timeframe.")
    if not snapshot.instrument_id.endswith("-SPOT") or not snapshot.venue_id.endswith(
        "-SPOT"
    ):
        raise SpotSMCError("Only canonical Spot instruments and venues are supported.")
    try:
        _, price_unit = _ohlc(
            snapshot=snapshot,
            observations=observations,
            quality=quality,
            timeframe=timeframe,
        )
    except (VolatilityError, ArithmeticError) as exc:
        raise SpotSMCError("Spot OHLCV failed shared analysis validation.") from exc
    interval = timedelta(seconds=_INTERVALS[timeframe])
    if observations[-1].event_time + interval != snapshot.as_of:
        raise SpotSMCError("The latest closed candle must end at snapshot cutoff.")
    _validate_structure_input(
        structure=market_structure,
        snapshot=snapshot,
        observations=observations,
        quality=quality,
        timeframe=timeframe,
    )
    if (
        market_structure.price_unit != price_unit
        or market_structure.internal_pivot_policy.price_unit != price_unit
        or market_structure.external_pivot_policy.price_unit != price_unit
    ):
        raise SpotSMCError("#56 pivot and OHLCV price units do not match.")
    try:
        expiry = quality.assessed_at + interval
    except OverflowError as exc:
        raise SpotSMCError("Spot SMC expiry exceeds timestamp bounds.") from exc
    candles: list[_Candle] = []
    for item in observations:
        metrics = {metric.metric_name: metric for metric in item.metrics}
        candles.append(
            _Candle(
                item,
                metrics["open"].value,
                metrics["high"].value,
                metrics["low"].value,
                metrics["close"].value,
                item.event_time + interval,
            )
        )
    candle_tuple = tuple(candles)
    support_evidence_ids = (market_structure.evidence.evidence_id,)
    with localcontext() as context:
        context.prec = _WORK_PRECISION
        fvg = _fvg_objects(
            candles=candle_tuple,
            snapshot=snapshot,
            timeframe=timeframe,
            price_unit=price_unit,
            policy=policy,
            supporting_evidence_ids=support_evidence_ids,
            expires_at=expiry,
        )
        displacements = _displacement_measures(candles=candle_tuple, policy=policy)
        displacement_records = _displacement_objects(
            candles=candle_tuple,
            measures=displacements,
            snapshot=snapshot,
            timeframe=timeframe,
            price_unit=price_unit,
            policy=policy,
            supporting_evidence_ids=support_evidence_ids,
            expires_at=expiry,
        )
        output_records_already_built = len(fvg) + len(displacement_records) + 1
        if output_records_already_built > policy.maximum_output_records:
            raise SpotSMCError("Spot SMC output exceeds the caller policy bound.")
        structure_objects, events = _structure_event_objects(
            structure=market_structure,
            candles=candle_tuple,
            snapshot=snapshot,
            timeframe=timeframe,
            price_unit=price_unit,
            policy=policy,
            expires_at=expiry,
            output_records_already_built=output_records_already_built,
        )
        output_records_already_built += len(structure_objects)
        premium_discount = _premium_discount_object(
            structure=market_structure,
            candles=candle_tuple,
            snapshot=snapshot,
            timeframe=timeframe,
            price_unit=price_unit,
            policy=policy,
            supporting_evidence_ids=support_evidence_ids,
            expires_at=expiry,
        )
        liquidity = _liquidity_objects(
            structure=market_structure,
            candles=candle_tuple,
            snapshot=snapshot,
            timeframe=timeframe,
            price_unit=price_unit,
            policy=policy,
            supporting_evidence_ids=support_evidence_ids,
            expires_at=expiry,
            output_records_already_built=output_records_already_built,
        )
        output_records_already_built += len(liquidity)
        order_blocks = _order_block_objects(
            events=events,
            candles=candle_tuple,
            measures=displacements,
            snapshot=snapshot,
            timeframe=timeframe,
            price_unit=price_unit,
            policy=policy,
            supporting_evidence_ids=support_evidence_ids,
            expires_at=expiry,
            output_records_already_built=output_records_already_built,
        )
    objects = tuple(
        sorted(
            (
                *fvg,
                *liquidity,
                *displacement_records,
                *structure_objects,
                *order_blocks,
                premium_discount,
            ),
            key=lambda item: (
                item.creation_time,
                item.category,
                item.object_id.hex,
            ),
        )
    )
    data_availability = {
        item.market_data_id: item.availability_time for item in observations
    }
    objects = tuple(
        replace(
            item,
            available_at=max(
                (
                    item.creation_time,
                    *(
                        data_availability[source_id]
                        for source_id in item.source_market_data_ids
                    ),
                )
            ),
        )
        for item in objects
    )
    if len(objects) > policy.maximum_output_records:
        raise SpotSMCError("Spot SMC output exceeds the caller policy bound.")
    payload = _SMCEvidence(
        payload_version=SPOT_SMC_EVIDENCE_VERSION,
        method_version=SPOT_SMC_METHOD_VERSION,
        indicator_id=metadata.indicator_id,
        metadata_version=metadata.metadata_version,
        timeframe=timeframe,
        asset=snapshot.instrument_id,
        instrument_id=snapshot.instrument_id,
        venue_id=snapshot.venue_id,
        price_unit=price_unit,
        snapshot_id=snapshot.snapshot_id,
        quality_report_id=quality.report_id,
        as_of=snapshot.as_of,
        evidence_expires_at=expiry,
        source_record_ids=snapshot.source_record_ids,
        input_market_data_ids=snapshot.market_data_ids,
        source_market_structure_evidence_id=market_structure.evidence.evidence_id,
        source_market_structure_method_version=market_structure.method_version,
        internal_pivot_policy=market_structure.internal_pivot_policy,
        external_pivot_policy=market_structure.external_pivot_policy,
        smc_policy=policy,
        objects=objects,
        uncertainty=_UNCERTAINTY,
        limitations=_LIMITATIONS,
    )
    evidence = _evidence_contract(
        payload=payload,
        snapshot=snapshot,
        quality=quality,
        timeframe=timeframe,
    )
    evidence_ids = tuple(
        dict.fromkeys((evidence.evidence_id, market_structure.evidence.evidence_id))
    )
    observations_out = tuple(
        DomainObservation(
            observation_type=item.category,
            value=f"{item.subtype}:{item.object_id}",
            unit=item.price_unit,
            timeframe=timeframe,
            calculation=VersionReference(
                metadata.indicator_id, metadata.calculation_version
            ),
            evidence_ids=evidence_ids,
        )
        for item in objects
    )
    finding = AnalyticalFinding(
        finding_id=_stable_id("finding", evidence.evidence_id),
        category="spot-smc-observation",
        classification=ClaimClassification.FACT,
        statement=(
            "Deterministic Spot OHLCV SMC observations and lifecycle states are "
            "recorded in linked C-008 evidence; they carry no trading authority."
        ),
        evidence_ids=evidence_ids,
        method=VersionReference(metadata.indicator_id, metadata.calculation_version),
        invalidation_condition=(
            "Superseded by correction of source candles, pivots, or structure events, "
            "or a new exact method or caller-policy version."
        ),
        limitations=_LIMITATIONS,
    )
    status = (
        AssessmentStatus.PARTIAL
        if premium_discount.subtype == "unavailable"
        else AssessmentStatus.AVAILABLE
    )
    assessment = SMCAssessment(
        assessment_id=_stable_id("assessment", evidence.evidence_id),
        asset=snapshot.instrument_id,
        instrument_id=snapshot.instrument_id,
        timeframe=timeframe,
        as_of=snapshot.as_of,
        available_at=quality.assessed_at,
        expires_at=expiry,
        status=status,
        analytical_confidence=Decimal(0),
        findings=(finding,),
        observations=observations_out,
        evidence_ids=evidence_ids,
        contradiction_ids=(),
        uncertainty_ids=(),
        data_quality_report_id=quality.report_id,
        provenance=(
            VersionReference("C-001", "1"),
            VersionReference("C-002", "1"),
            VersionReference("C-003", "1"),
            VersionReference("C-008", "1"),
            VersionReference("C-013", "1"),
            VersionReference(metadata.indicator_id, metadata.calculation_version),
            VersionReference(
                MARKET_STRUCTURE_INDICATOR_ID, MARKET_STRUCTURE_METHOD_VERSION
            ),
        ),
        methodology=MethodologyCategory.TECHNICAL,
    )
    return SpotSMCAnalysis(
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
        evidence_expires_at=expiry,
        source_record_ids=snapshot.source_record_ids,
        input_market_data_ids=snapshot.market_data_ids,
        price_unit=price_unit,
        policy=policy,
        objects=objects,
        evidence=evidence,
        assessment=assessment,
    )


__all__ = [
    "SPOT_SMC_EVIDENCE_VERSION",
    "SPOT_SMC_INDICATOR_ID",
    "SPOT_SMC_METADATA_VERSION",
    "SPOT_SMC_METHOD_VERSION",
    "SMCAttribute",
    "SMCObject",
    "SpotSMCAnalysis",
    "SpotSMCError",
    "SpotSMCPolicy",
    "calculate_spot_smc",
]
