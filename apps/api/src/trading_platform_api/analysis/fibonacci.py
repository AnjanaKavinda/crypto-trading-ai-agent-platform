"""Deterministic, analysis-only Spot Fibonacci reference observations."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import ROUND_HALF_EVEN, Decimal, localcontext
from hashlib import sha256
from uuid import UUID, uuid5

from trading_platform_api.analysis.contracts import (
    AnalyticalFinding,
    AssessmentStatus,
    ClaimClassification,
    DomainObservation,
    EvidenceItem,
    EvidenceRelation,
    FibonacciAssessment,
    MethodologyCategory,
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
    ClassifiedSwing,
    MarketStructureAnalysis,
    MarketStructurePolicy,
    MarketStructureScale,
)
from trading_platform_api.analysis.price_action import (
    _INTERVALS,
    PRICE_ACTION_INDICATOR_ID,
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

SPOT_FIBONACCI_INDICATOR_ID = "spot-fibonacci"
SPOT_FIBONACCI_METADATA_VERSION = "1"
SPOT_FIBONACCI_METHOD_VERSION = "spot-fibonacci-v1"
SPOT_FIBONACCI_EVIDENCE_VERSION = "spot-fibonacci-evidence-v1"
_MAX_CANDLES = 10_000
_MAX_POLICY_TEXT = 128
_MAX_CLOSES = 500
_WORK_PRECISION = 512
_MAX_TOTAL_EVIDENCE_BYTES = MAX_DOCUMENT_BYTES * 20
_IDENTITY_NAMESPACE = UUID("32451777-4ba5-58b2-bd14-24bb55ccfabc")
_RETRACEMENT_RATIOS = tuple(
    Decimal(value) for value in ("0.236", "0.382", "0.500", "0.618", "0.786", "1.000")
)
_EXTENSION_RATIOS = tuple(Decimal(value) for value in ("1.272", "1.618", "2.618"))
_LIMITATIONS = (
    "Descriptive Spot OHLCV reference levels only; not a signal, recommendation, "
    "validation, risk decision, approval, or execution permission.",
    "Anchors are explicitly caller-selected confirmed pivots, not an objectively "
    "canonical pair.",
    "No level, touch, or cluster asserts support, resistance, a target, likelihood, "
    "profitability, or future price direction.",
    "All ratios from one pivot pair share price data and are highly correlated; "
    "confluence is not independent evidence or predictive confidence.",
    "Analysis is same-timeframe and point-in-time; no future-candle look-ahead, "
    "alternative data, multi-timeframe inference, or repainting is used.",
)
_UNCERTAINTY = (
    "Analytical confidence is uncalibrated and reported as zero; it is not probability.",
    "All Fibonacci levels and confluence groups derive from the same pivot pair and "
    "source candles and are highly correlated.",
)
_PIVOT_TIE_RULE = (
    "earliest equal extreme wins: strictly more extreme than all left candles "
    "and at least as extreme as all right candles"
)


class SpotFibonacciError(ValueError):
    """Spot Fibonacci observations cannot be calculated safely."""


@dataclass(frozen=True, slots=True)
class SpotFibonacciPolicy:
    """Immutable caller-selected anchors, ratios, and invalidation rules."""

    policy_id: str
    version: str
    scale: MarketStructureScale
    origin_pivot_id: UUID
    endpoint_pivot_id: UUID
    retracement_ratios: tuple[Decimal, ...]
    extension_ratios: tuple[Decimal, ...]
    confluence_tolerance: Decimal
    invalidation_buffer: Decimal
    invalidation_consecutive_close_count: int
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
                raise SpotFibonacciError(f"{name} must be bounded nonblank text.")
        if not isinstance(self.scale, MarketStructureScale):
            raise SpotFibonacciError(
                "scale must be an explicit market-structure scale."
            )
        if (
            type(self.origin_pivot_id) is not UUID
            or type(self.endpoint_pivot_id) is not UUID
        ):
            raise SpotFibonacciError("Anchor IDs must be UUIDs.")
        if self.origin_pivot_id == self.endpoint_pivot_id:
            raise SpotFibonacciError("Origin and endpoint pivot IDs must be distinct.")
        for name, selected, allowed in (
            ("retracement_ratios", self.retracement_ratios, _RETRACEMENT_RATIOS),
            ("extension_ratios", self.extension_ratios, _EXTENSION_RATIOS),
        ):
            if (
                type(selected) is not tuple
                or not selected
                or not all(type(item) is Decimal for item in selected)
                or len(set(selected)) != len(selected)
                or not set(selected).issubset(allowed)
            ):
                raise SpotFibonacciError(
                    f"{name} must be a nonempty unique subset of supported ratios."
                )
        for name in ("confluence_tolerance", "invalidation_buffer"):
            try:
                value = _bounded_decimal(name, getattr(self, name))
            except (TypeError, ValueError) as exc:
                raise SpotFibonacciError(
                    f"{name} must be a bounded finite Decimal."
                ) from exc
            if value <= 0:
                raise SpotFibonacciError(f"{name} must be strictly positive.")
        if (
            type(self.invalidation_consecutive_close_count) is not int
            or not 1 <= self.invalidation_consecutive_close_count <= _MAX_CLOSES
        ):
            raise SpotFibonacciError(
                f"invalidation_consecutive_close_count must be in [1, {_MAX_CLOSES}]."
            )
        if (
            type(self.maximum_output_records) is not int
            or not 1 <= self.maximum_output_records <= _MAX_CANDLES
        ):
            raise SpotFibonacciError(
                f"maximum_output_records must be in [1, {_MAX_CANDLES}]."
            )


@dataclass(frozen=True, slots=True)
class FibonacciAnchor:
    pivot_id: UUID
    kind: PivotKind
    price: Decimal
    source_market_data_id: UUID
    source_time: datetime
    confirmation_market_data_id: UUID
    confirmation_time: datetime
    scale: MarketStructureScale
    timeframe: str
    policy_id: str
    policy_version: str
    method_version: str


@dataclass(frozen=True, slots=True)
class FibonacciLevel:
    level_id: UUID
    category: str
    ratio: Decimal
    price: Decimal
    confluence_group_ids: tuple[UUID, ...]
    evidence_id: UUID


@dataclass(frozen=True, slots=True)
class FibonacciConfluenceGroup:
    group_id: UUID
    member_level_ids: tuple[UUID, ...]
    member_ratios: tuple[Decimal, ...]
    member_prices: tuple[Decimal, ...]
    fixed_anchor_price: Decimal
    lower_bound: Decimal
    upper_bound: Decimal
    tolerance: Decimal
    evidence_id: UUID


@dataclass(frozen=True, slots=True)
class FibonacciInvalidation:
    invalidated: bool
    threshold_price: Decimal
    buffer: Decimal
    consecutive_close_count: int
    observed_consecutive_closes: int
    confirming_market_data_id: UUID | None
    confirmation_time: datetime | None
    evidence_id: UUID


@dataclass(frozen=True, slots=True)
class SpotFibonacciAnalysis:
    indicator_id: str
    metadata_version: str
    method_version: str
    timeframe: str
    instrument_id: str
    venue_id: str
    snapshot_id: UUID
    quality_report_id: UUID
    as_of: datetime
    evidence_expires_at: datetime
    source_record_ids: tuple[UUID, ...]
    input_market_data_ids: tuple[UUID, ...]
    price_unit: str
    policy: SpotFibonacciPolicy
    direction: str
    move: Decimal
    anchors: tuple[FibonacciAnchor, FibonacciAnchor]
    levels: tuple[FibonacciLevel, ...]
    confluence_groups: tuple[FibonacciConfluenceGroup, ...]
    invalidation: FibonacciInvalidation
    evidence: tuple[EvidenceItem, ...]
    assessment: FibonacciAssessment


def _stable_id(*parts: object) -> UUID:
    return uuid5(_IDENTITY_NAMESPACE, canonical_json_dumps(parts))


def _policy_reference(policy: SpotFibonacciPolicy) -> VersionReference:
    return VersionReference(
        "spot-fibonacci-policy",
        canonical_json_dumps((policy.policy_id, policy.version)),
    )


def _immutable_json(value: object) -> object:
    if isinstance(value, list):
        return tuple(_immutable_json(item) for item in value)
    if isinstance(value, dict):
        return {key: _immutable_json(item) for key, item in value.items()}
    return value


def _same_json(actual: object, expected: object) -> bool:
    return canonical_json_dumps(_immutable_json(actual)) == canonical_json_dumps(
        expected
    )


def _validate_structure(
    *,
    structure: MarketStructureAnalysis,
    snapshot: MarketSnapshot,
    quality: DataQualityReport,
    observations: tuple[MarketData, ...],
    timeframe: str,
    price_unit: str,
) -> dict[UUID, tuple[MarketStructureScale, PivotObservation]]:
    if type(structure) is not MarketStructureAnalysis:
        raise SpotFibonacciError("The exact #56 MarketStructureAnalysis is required.")
    if (
        structure.indicator_id != MARKET_STRUCTURE_INDICATOR_ID
        or structure.metadata_version != MARKET_STRUCTURE_METADATA_VERSION
        or structure.method_version != MARKET_STRUCTURE_METHOD_VERSION
    ):
        raise SpotFibonacciError("Unregistered exact #56 method or metadata version.")
    if (
        structure.timeframe != timeframe
        or structure.instrument_id != snapshot.instrument_id
        or structure.asset != snapshot.instrument_id
        or structure.venue_id != snapshot.venue_id
        or structure.snapshot_id != snapshot.snapshot_id
        or structure.quality_report_id != quality.report_id
        or structure.as_of != snapshot.as_of
        or structure.source_record_ids != snapshot.source_record_ids
        or structure.input_market_data_ids != snapshot.market_data_ids
        or structure.price_unit != price_unit
        or type(structure.internal_pivot_policy) is not SupportResistancePolicy
        or type(structure.external_pivot_policy) is not SupportResistancePolicy
        or type(structure.break_policy) is not MarketStructurePolicy
        or structure.internal_pivot_policy.price_unit != price_unit
        or structure.external_pivot_policy.price_unit != price_unit
    ):
        raise SpotFibonacciError("#56 output lineage does not match exact inputs.")
    try:
        metadata = SPOT_RESEARCH_INDICATORS.get(
            MARKET_STRUCTURE_INDICATOR_ID, structure.metadata_version
        )
    except IndicatorMetadataError as exc:
        raise SpotFibonacciError("Exact #56 metadata lookup failed.") from exc
    if (
        metadata.phase is not IndicatorPhase.VALIDATED
        or metadata.calculation_version != MARKET_STRUCTURE_METHOD_VERSION
        or timeframe not in metadata.timeframes
    ):
        raise SpotFibonacciError("#56 method is not validated for this timeframe.")
    evidence = structure.evidence
    if (
        type(evidence) is not EvidenceItem
        or evidence.contract_id != "C-008"
        or evidence.method.component != MARKET_STRUCTURE_INDICATOR_ID
        or evidence.method.version != MARKET_STRUCTURE_METHOD_VERSION
        or evidence.source_record_ids != snapshot.source_record_ids
        or evidence.data_quality_report_id != quality.report_id
        or evidence.quality_status is not DataQualityStatus.VALID
        or evidence.expires_at != structure.evidence_expires_at
        or evidence.observed_at != snapshot.as_of
        or evidence.available_at != quality.assessed_at
        or evidence.unit != price_unit
        or evidence.reliability != quality.source_reliability
        or not evidence.usable
        or VersionReference(PRICE_ACTION_INDICATOR_ID, PRICE_ACTION_METHOD_VERSION)
        not in evidence.provenance
        or VersionReference(
            "market-structure-evidence", MARKET_STRUCTURE_EVIDENCE_VERSION
        )
        not in evidence.provenance
    ):
        raise SpotFibonacciError("#56 C-008 evidence lineage is invalid.")
    assessment = structure.assessment
    if (
        type(assessment) is not TechnicalAssessment
        or assessment.contract_id != "C-012"
        or assessment.status is not AssessmentStatus.AVAILABLE
        or assessment.instrument_id != snapshot.instrument_id
        or assessment.timeframe != timeframe
        or assessment.as_of != snapshot.as_of
        or assessment.data_quality_report_id != quality.report_id
        or assessment.evidence_ids != (evidence.evidence_id,)
        or assessment.available_at != quality.assessed_at
        or assessment.expires_at != structure.evidence_expires_at
    ):
        raise SpotFibonacciError("#56 assessment lineage is invalid.")
    if (
        type(evidence.value) is not str
        or len(evidence.value.encode("utf-8")) > MAX_DOCUMENT_BYTES
    ):
        raise SpotFibonacciError("#56 C-008 evidence exceeds its bound.")
    try:
        payload = json.loads(evidence.value)
        if (
            type(payload) is not dict
            or canonical_json_dumps(_immutable_json(payload)) != evidence.value
        ):
            raise SpotFibonacciError("#56 C-008 evidence is not canonical.")
        expected_fields = {
            "payload_version": MARKET_STRUCTURE_EVIDENCE_VERSION,
            "method_version": structure.method_version,
            "timeframe": timeframe,
            "instrument_id": snapshot.instrument_id,
            "venue_id": snapshot.venue_id,
            "asset": structure.asset,
            "price_unit": price_unit,
            "snapshot_id": snapshot.snapshot_id,
            "quality_report_id": quality.report_id,
            "as_of": snapshot.as_of,
            "evidence_expires_at": structure.evidence_expires_at,
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
        if set(payload) != set(expected_fields) or any(
            not _same_json(payload[field], expected)
            for field, expected in expected_fields.items()
        ):
            raise SpotFibonacciError("#56 C-008 evidence does not match its output.")
    except SpotFibonacciError:
        raise
    except (
        UnicodeError,
        json.JSONDecodeError,
        RecursionError,
        TypeError,
        ValueError,
    ) as exc:
        raise SpotFibonacciError("#56 C-008 evidence is invalid.") from exc

    index_by_id = {
        candle.market_data_id: index for index, candle in enumerate(observations)
    }
    result: dict[UUID, tuple[MarketStructureScale, PivotObservation]] = {}
    swings = structure.swings
    if (
        type(swings) is not tuple
        or not all(type(swing) is ClassifiedSwing for swing in swings)
        or not all(type(swing.pivot) is PivotObservation for swing in swings)
        or len({swing.pivot.pivot_id for swing in swings}) != len(swings)
    ):
        raise SpotFibonacciError("#56 pivots must be unique confirmed swings.")
    for swing in swings:
        pivot = swing.pivot
        if (
            not isinstance(swing.scale, MarketStructureScale)
            or type(pivot) is not PivotObservation
            or type(pivot.kind) is not PivotKind
            or pivot.method_version != PRICE_ACTION_METHOD_VERSION
        ):
            raise SpotFibonacciError("#56 pivot method or scale is invalid.")
        policy = (
            structure.internal_pivot_policy
            if swing.scale is MarketStructureScale.INTERNAL
            else structure.external_pivot_policy
        )
        source_index = index_by_id.get(pivot.source_market_data_id)
        if (
            source_index is None
            or pivot.policy_id != policy.policy_id
            or pivot.policy_version != policy.version
            or pivot.left_window != policy.left_window
            or pivot.right_window != policy.right_window
            or pivot.tie_rule != _PIVOT_TIE_RULE
            or source_index < pivot.left_window
        ):
            raise SpotFibonacciError("#56 pivot policy or source identity is invalid.")
        confirmation_index = source_index + pivot.right_window
        if (
            confirmation_index >= len(observations)
            or observations[confirmation_index].market_data_id
            != pivot.confirmation_market_data_id
        ):
            raise SpotFibonacciError("#56 pivot confirmation identity is invalid.")
        source = observations[source_index]
        confirmation = observations[confirmation_index]
        metrics = {metric.metric_name: metric for metric in source.metrics}
        price_field = "high" if pivot.kind is PivotKind.HIGH else "low"
        source_price = metrics[price_field].value
        try:
            _bounded_decimal("pivot.price", pivot.price)
        except (TypeError, ValueError) as exc:
            raise SpotFibonacciError(
                "#56 pivot price exceeds supported Decimal bounds."
            ) from exc
        left_prices = tuple(
            {metric.metric_name: metric.value for metric in candle.metrics}[price_field]
            for candle in observations[source_index - pivot.left_window : source_index]
        )
        right_prices = tuple(
            {metric.metric_name: metric.value for metric in candle.metrics}[price_field]
            for candle in observations[source_index + 1 : confirmation_index + 1]
        )
        is_confirmed_extreme = (
            pivot.price > max(left_prices) and pivot.price >= max(right_prices)
            if pivot.kind is PivotKind.HIGH
            else pivot.price < min(left_prices) and pivot.price <= min(right_prices)
        )
        if (
            pivot.price != source_price
            or pivot.source_time != source.event_time
            or pivot.confirmation_time
            != confirmation.event_time + timedelta(seconds=_INTERVALS[timeframe])
            or pivot.confirmation_time > snapshot.as_of
            or pivot.source_time >= confirmation.event_time
            or not is_confirmed_extreme
        ):
            raise SpotFibonacciError(
                "#56 pivot is unconfirmed, not an exact local extreme, or mismatches source OHLC."
            )
        result[pivot.pivot_id] = (swing.scale, pivot)
    return result


def _level_payload(
    *,
    evidence_kind: str,
    snapshot: MarketSnapshot,
    quality: DataQualityReport,
    structure: MarketStructureAnalysis,
    timeframe: str,
    price_unit: str,
    policy: SpotFibonacciPolicy,
    direction: str,
    move: Decimal,
    anchors: tuple[FibonacciAnchor, FibonacciAnchor],
    source_ids: tuple[UUID, ...],
    level: FibonacciLevel | None = None,
    group: FibonacciConfluenceGroup | None = None,
    invalidation: dict[str, object] | None = None,
) -> dict[str, object]:
    if level is not None:
        value: object = {
            "level_id": level.level_id,
            "category": level.category,
            "ratio": level.ratio,
            "price": level.price,
            "confluence_group_ids": level.confluence_group_ids,
        }
    elif group is not None:
        value = {
            "group_id": group.group_id,
            "member_level_ids": group.member_level_ids,
            "member_ratios": group.member_ratios,
            "member_prices": group.member_prices,
            "fixed_anchor_price": group.fixed_anchor_price,
            "lower_bound": group.lower_bound,
            "upper_bound": group.upper_bound,
            "tolerance": group.tolerance,
        }
    else:
        value = invalidation
    return {
        "evidence_version": SPOT_FIBONACCI_EVIDENCE_VERSION,
        "method_id": SPOT_FIBONACCI_INDICATOR_ID,
        "metadata_version": SPOT_FIBONACCI_METADATA_VERSION,
        "method_version": SPOT_FIBONACCI_METHOD_VERSION,
        "evidence_kind": evidence_kind,
        "policy": policy,
        "anchor_selection": "explicit-caller-selection",
        "direction": direction,
        "move": move,
        "anchors": anchors,
        "timeframe": timeframe,
        "price_unit": price_unit,
        "as_of": snapshot.as_of,
        "evidence_expires_at": snapshot.as_of
        + timedelta(seconds=_INTERVALS[timeframe]),
        "snapshot_id": snapshot.snapshot_id,
        "quality_report_id": quality.report_id,
        "source_record_ids": snapshot.source_record_ids,
        "input_market_data_ids": snapshot.market_data_ids,
        "source_market_data_ids": source_ids,
        "market_structure_evidence_id": structure.evidence.evidence_id,
        "value": value,
        "uncertainty": _UNCERTAINTY,
        "limitations": _LIMITATIONS,
    }


def _make_evidence(
    *,
    payload: dict[str, object],
    snapshot: MarketSnapshot,
    quality: DataQualityReport,
    expires_at: datetime,
    price_unit: str,
    evidence_kind: str,
    policy: SpotFibonacciPolicy,
) -> EvidenceItem:
    encoded = canonical_json_dumps(payload)
    if len(encoded.encode("utf-8")) > MAX_DOCUMENT_BYTES:
        raise SpotFibonacciError("Fibonacci evidence exceeds the output byte bound.")
    digest = sha256(encoded.encode("utf-8")).hexdigest()
    evidence_id = _stable_id(
        "evidence", snapshot.snapshot_id, quality.report_id, evidence_kind, digest
    )
    return EvidenceItem(
        evidence_id=evidence_id,
        source_record_ids=snapshot.source_record_ids,
        dataset_versions=(snapshot.dataset_version,)
        if snapshot.dataset_version
        else (),
        feature_ids=(
            f"C-002:snapshot:{snapshot.snapshot_id}",
            *(f"C-001:market-data:{item_id}" for item_id in snapshot.market_data_ids),
        ),
        classification=ClaimClassification.FACT,
        relation=EvidenceRelation.NEUTRAL,
        observed_at=snapshot.as_of,
        available_at=quality.assessed_at,
        expires_at=expires_at,
        method=VersionReference(
            SPOT_FIBONACCI_INDICATOR_ID, SPOT_FIBONACCI_METHOD_VERSION
        ),
        value=encoded,
        unit=price_unit,
        interpretation=(
            "Deterministic, point-in-time Spot Fibonacci reference calculation; "
            "descriptive only."
        ),
        quality_status=quality.status,
        data_quality_report_id=quality.report_id,
        reliability=quality.source_reliability,
        limitations=(*_LIMITATIONS, *_UNCERTAINTY),
        provenance=(
            VersionReference("C-001", "1"),
            VersionReference("C-002", "1"),
            VersionReference("C-003", "1"),
            VersionReference("C-008", "1"),
            VersionReference("C-068", "1"),
            VersionReference(
                MARKET_STRUCTURE_INDICATOR_ID, MARKET_STRUCTURE_METHOD_VERSION
            ),
            VersionReference(
                "market-structure-evidence", MARKET_STRUCTURE_EVIDENCE_VERSION
            ),
            VersionReference("canonical-json", CANONICAL_JSON_VERSION),
            VersionReference(
                "spot-fibonacci-evidence", SPOT_FIBONACCI_EVIDENCE_VERSION
            ),
            _policy_reference(policy),
        ),
        usable=True,
    )


def _fixed_anchor_groups(
    levels: tuple[FibonacciLevel, ...], tolerance: Decimal
) -> tuple[
    tuple[
        UUID,
        tuple[UUID, ...],
        tuple[Decimal, ...],
        tuple[Decimal, ...],
        Decimal,
        Decimal,
        Decimal,
    ],
    ...,
]:
    ordered = sorted(levels, key=lambda level: (level.price, str(level.level_id)))
    groups = []
    index = 0
    with localcontext() as context:
        context.prec = _WORK_PRECISION
        while index < len(ordered):
            fixed_anchor = ordered[index].price
            end = index + 1
            while end < len(ordered) and ordered[end].price - fixed_anchor <= tolerance:
                end += 1
            members = ordered[index:end]
            if len(members) > 1:
                groups.append(
                    (
                        _stable_id(
                            "confluence",
                            tuple(item.level_id for item in members),
                            fixed_anchor,
                            tolerance,
                        ),
                        tuple(item.level_id for item in members),
                        tuple(item.ratio for item in members),
                        tuple(item.price for item in members),
                        fixed_anchor,
                        members[0].price,
                        members[-1].price,
                    )
                )
            index = end
    return tuple(groups)


def calculate_spot_fibonacci(
    *,
    snapshot: MarketSnapshot,
    observations: tuple[MarketData, ...],
    quality: DataQualityReport,
    market_structure: MarketStructureAnalysis,
    timeframe: str,
    policy: SpotFibonacciPolicy,
    metadata_version: str = SPOT_FIBONACCI_METADATA_VERSION,
) -> SpotFibonacciAnalysis:
    """Calculate caller-selected Fibonacci levels from exact confirmed #56 pivots."""
    if (
        type(snapshot) is not MarketSnapshot
        or type(quality) is not DataQualityReport
        or type(observations) is not tuple
        or not observations
        or len(observations) > _MAX_CANDLES
        or not all(type(item) is MarketData for item in observations)
    ):
        raise SpotFibonacciError(
            "Canonical bounded snapshot, quality, and candles are required."
        )
    if type(policy) is not SpotFibonacciPolicy:
        raise SpotFibonacciError("An explicit immutable caller policy is required.")
    if type(timeframe) is not str or timeframe not in _INTERVALS:
        raise SpotFibonacciError("Unsupported Spot timeframe.")
    if type(metadata_version) is not str:
        raise SpotFibonacciError("metadata_version must be an exact version string.")
    try:
        metadata = SPOT_RESEARCH_INDICATORS.get(
            SPOT_FIBONACCI_INDICATOR_ID, metadata_version
        )
    except (IndicatorMetadataError, TypeError) as exc:
        raise SpotFibonacciError(
            "Unknown exact Spot Fibonacci metadata version."
        ) from exc
    if (
        metadata.phase is not IndicatorPhase.VALIDATED
        or metadata.calculation_version != SPOT_FIBONACCI_METHOD_VERSION
        or timeframe not in metadata.timeframes
    ):
        raise SpotFibonacciError(
            "Fibonacci method is not validated for this timeframe."
        )
    if not snapshot.instrument_id.endswith("-SPOT") or not snapshot.venue_id.endswith(
        "-SPOT"
    ):
        raise SpotFibonacciError(
            "Only canonical Spot instruments and venues are supported."
        )
    try:
        _, price_unit = _ohlc(
            snapshot=snapshot,
            observations=observations,
            quality=quality,
            timeframe=timeframe,
        )
    except (VolatilityError, ArithmeticError) as exc:
        raise SpotFibonacciError(
            "Spot OHLCV failed shared analysis validation."
        ) from exc
    try:
        for candle in observations:
            metrics = {metric.metric_name: metric for metric in candle.metrics}
            for name in ("open", "high", "low", "close"):
                _bounded_decimal(name, metrics[name].value)
    except (KeyError, TypeError, ValueError) as exc:
        raise SpotFibonacciError(
            "OHLC prices exceed supported Decimal bounds."
        ) from exc
    if (
        tuple(dict.fromkeys(item.source_record_id for item in observations))
        != snapshot.source_record_ids
    ):
        raise SpotFibonacciError("Ordered candle provenance must match the snapshot.")
    interval = timedelta(seconds=_INTERVALS[timeframe])
    if observations[-1].event_time + interval != snapshot.as_of:
        raise SpotFibonacciError(
            "The latest closed candle must end at snapshot cutoff."
        )
    try:
        expires_at = snapshot.as_of + interval
    except OverflowError as exc:
        raise SpotFibonacciError(
            "Fibonacci evidence expiry exceeds timestamp bounds."
        ) from exc
    if quality.assessed_at >= expires_at:
        raise SpotFibonacciError(
            "Quality was assessed at or after Fibonacci evidence expiry."
        )
    if len(observations) < metadata.minimum_warmup_candles:
        raise SpotFibonacciError("Insufficient warm-up for the registered method.")

    pivots = _validate_structure(
        structure=market_structure,
        snapshot=snapshot,
        quality=quality,
        observations=observations,
        timeframe=timeframe,
        price_unit=price_unit,
    )
    try:
        origin_scale, origin = pivots[policy.origin_pivot_id]
        endpoint_scale, endpoint = pivots[policy.endpoint_pivot_id]
    except KeyError as exc:
        raise SpotFibonacciError("Caller anchor ID is unknown or unconfirmed.") from exc
    if origin_scale is not policy.scale or endpoint_scale is not policy.scale:
        raise SpotFibonacciError("Both anchors must use the caller-designated scale.")
    source_index = {
        item.market_data_id: index for index, item in enumerate(observations)
    }
    if (
        source_index[origin.source_market_data_id]
        >= source_index[endpoint.source_market_data_id]
        or origin.confirmation_time >= endpoint.confirmation_time
    ):
        raise SpotFibonacciError(
            "Origin must precede endpoint in source and confirmation time."
        )
    if origin.kind is endpoint.kind:
        raise SpotFibonacciError("Fibonacci anchor pivot kinds must alternate.")
    if origin.kind is PivotKind.LOW and endpoint.kind is PivotKind.HIGH:
        direction = "bullish"
        if endpoint.price <= origin.price:
            raise SpotFibonacciError(
                "Bullish anchors must define an upward price move."
            )
    elif origin.kind is PivotKind.HIGH and endpoint.kind is PivotKind.LOW:
        direction = "bearish"
        if endpoint.price >= origin.price:
            raise SpotFibonacciError(
                "Bearish anchors must define a downward price move."
            )
    else:
        raise SpotFibonacciError("Anchor kinds do not define a valid impulse.")
    try:
        _bounded_decimal("origin.price", origin.price)
        _bounded_decimal("endpoint.price", endpoint.price)
    except ValueError as exc:
        raise SpotFibonacciError("Anchor prices exceed Decimal bounds.") from exc
    with localcontext() as context:
        context.prec = _WORK_PRECISION
        move = abs(endpoint.price - origin.price)
        try:
            _bounded_decimal("anchor move", move)
        except ValueError as exc:
            raise SpotFibonacciError("Anchor move exceeds Decimal bounds.") from exc
        if move <= 0:
            raise SpotFibonacciError("Anchor move must be strictly positive.")
    anchors = tuple(
        FibonacciAnchor(
            pivot_id=pivot.pivot_id,
            kind=pivot.kind,
            price=pivot.price,
            source_market_data_id=pivot.source_market_data_id,
            source_time=pivot.source_time,
            confirmation_market_data_id=pivot.confirmation_market_data_id,
            confirmation_time=pivot.confirmation_time,
            scale=policy.scale,
            timeframe=timeframe,
            policy_id=pivot.policy_id,
            policy_version=pivot.policy_version,
            method_version=pivot.method_version,
        )
        for pivot in (origin, endpoint)
    )
    source_ids = tuple(
        dict.fromkeys(
            (
                origin.source_market_data_id,
                origin.confirmation_market_data_id,
                endpoint.source_market_data_id,
                endpoint.confirmation_market_data_id,
            )
        )
    )
    with localcontext() as context:
        context.prec = _WORK_PRECISION
        context.rounding = ROUND_HALF_EVEN
        values: list[tuple[str, Decimal, Decimal]] = []
        for category, ratios in (
            ("retracement-level", policy.retracement_ratios),
            ("extension-level", policy.extension_ratios),
        ):
            for ratio in sorted(ratios):
                if category == "retracement-level":
                    price = (
                        endpoint.price - move * ratio
                        if direction == "bullish"
                        else endpoint.price + move * ratio
                    )
                else:
                    price = (
                        origin.price + move * ratio
                        if direction == "bullish"
                        else origin.price - move * ratio
                    )
                try:
                    _bounded_decimal("fibonacci level", price)
                except ValueError as exc:
                    raise SpotFibonacciError(
                        "Fibonacci level exceeds Decimal bounds."
                    ) from exc
                if price <= 0:
                    raise SpotFibonacciError(
                        "Fibonacci levels must be positive prices."
                    )
                values.append((category, ratio, price))

        levels_without_evidence = tuple(
            FibonacciLevel(
                level_id=_stable_id(
                    "level",
                    snapshot.snapshot_id,
                    quality.report_id,
                    policy,
                    category,
                    ratio,
                    price,
                ),
                category=category,
                ratio=ratio,
                price=price,
                confluence_group_ids=(),
                evidence_id=UUID(int=0),
            )
            for category, ratio, price in values
        )
        raw_groups = _fixed_anchor_groups(
            levels_without_evidence, policy.confluence_tolerance
        )
        grouped_ids = {
            level_id: tuple(group[0] for group in raw_groups if level_id in group[1])
            for level_id in (item.level_id for item in levels_without_evidence)
        }
        levels = tuple(
            FibonacciLevel(
                level.level_id,
                level.category,
                level.ratio,
                level.price,
                grouped_ids[level.level_id],
                level.evidence_id,
            )
            for level in levels_without_evidence
        )
        group_values = tuple(
            FibonacciConfluenceGroup(
                group_id=item[0],
                member_level_ids=item[1],
                member_ratios=item[2],
                member_prices=item[3],
                fixed_anchor_price=item[4],
                lower_bound=item[5],
                upper_bound=item[6],
                tolerance=policy.confluence_tolerance,
                evidence_id=UUID(int=0),
            )
            for item in raw_groups
        )

    closes_after_endpoint = tuple(
        candle
        for candle in observations
        if candle.event_time + interval > endpoint.confirmation_time
    )
    with localcontext() as context:
        context.prec = _WORK_PRECISION
        threshold = (
            origin.price - policy.invalidation_buffer
            if direction == "bullish"
            else origin.price + policy.invalidation_buffer
        )
        try:
            _bounded_decimal("invalidation threshold", threshold)
        except ValueError as exc:
            raise SpotFibonacciError(
                "Invalidation threshold exceeds Decimal bounds."
            ) from exc
        if threshold <= 0:
            raise SpotFibonacciError("Invalidation threshold must be a positive price.")
    close_values = []
    for candle in closes_after_endpoint:
        close_metric = next(
            metric for metric in candle.metrics if metric.metric_name == "close"
        )
        try:
            _bounded_decimal("close", close_metric.value)
        except ValueError as exc:
            raise SpotFibonacciError(
                "Invalidation close exceeds Decimal bounds."
            ) from exc
        close_values.append((candle, close_metric.value))
    wick_only_breaches_count = 0
    for candle, close in close_values:
        candle_metrics = {metric.metric_name: metric.value for metric in candle.metrics}
        wick_crossed = (
            candle_metrics["low"] < threshold
            if direction == "bullish"
            else candle_metrics["high"] > threshold
        )
        close_inside = (
            close >= threshold if direction == "bullish" else close <= threshold
        )
        if wick_crossed and close_inside:
            wick_only_breaches_count += 1

    consecutive = 0
    confirming_candle: MarketData | None = None
    for candle, close in close_values:
        outside = close < threshold if direction == "bullish" else close > threshold
        consecutive = consecutive + 1 if outside else 0
        if consecutive >= policy.invalidation_consecutive_close_count:
            confirming_candle = candle
            break
    invalidation_source_ids = tuple(
        candle.market_data_id for candle in closes_after_endpoint
    )

    evidence_items: list[EvidenceItem] = []
    anchor_evidence = _make_evidence(
        payload=_level_payload(
            evidence_kind="anchor",
            snapshot=snapshot,
            quality=quality,
            structure=market_structure,
            timeframe=timeframe,
            price_unit=price_unit,
            policy=policy,
            direction=direction,
            move=move,
            anchors=anchors,  # type: ignore[arg-type]
            source_ids=source_ids,
            invalidation={
                "selected_by_caller": True,
                "origin_pivot_id": origin.pivot_id,
                "endpoint_pivot_id": endpoint.pivot_id,
            },
        ),
        snapshot=snapshot,
        quality=quality,
        expires_at=expires_at,
        price_unit=price_unit,
        evidence_kind="anchor",
        policy=policy,
    )
    evidence_items.append(anchor_evidence)

    group_evidence: dict[UUID, EvidenceItem] = {}
    for group in group_values:
        payload = _level_payload(
            evidence_kind="confluence",
            snapshot=snapshot,
            quality=quality,
            structure=market_structure,
            timeframe=timeframe,
            price_unit=price_unit,
            policy=policy,
            direction=direction,
            move=move,
            anchors=anchors,  # type: ignore[arg-type]
            source_ids=source_ids,
            group=group,
        )
        item = _make_evidence(
            payload=payload,
            snapshot=snapshot,
            quality=quality,
            expires_at=expires_at,
            price_unit=price_unit,
            evidence_kind=f"confluence:{group.group_id}",
            policy=policy,
        )
        group_evidence[group.group_id] = item
        evidence_items.append(item)

    final_levels = []
    for level in levels:
        payload = _level_payload(
            evidence_kind=level.category,
            snapshot=snapshot,
            quality=quality,
            structure=market_structure,
            timeframe=timeframe,
            price_unit=price_unit,
            policy=policy,
            direction=direction,
            move=move,
            anchors=anchors,  # type: ignore[arg-type]
            source_ids=source_ids,
            level=level,
        )
        item = _make_evidence(
            payload=payload,
            snapshot=snapshot,
            quality=quality,
            expires_at=expires_at,
            price_unit=price_unit,
            evidence_kind=f"{level.category}:{level.level_id}",
            policy=policy,
        )
        evidence_items.append(item)
        final_levels.append(
            FibonacciLevel(
                level.level_id,
                level.category,
                level.ratio,
                level.price,
                level.confluence_group_ids,
                item.evidence_id,
            )
        )
    levels = tuple(final_levels)

    final_groups = []
    for group in group_values:
        item = group_evidence[group.group_id]
        final_groups.append(
            FibonacciConfluenceGroup(
                group.group_id,
                group.member_level_ids,
                group.member_ratios,
                group.member_prices,
                group.fixed_anchor_price,
                group.lower_bound,
                group.upper_bound,
                group.tolerance,
                item.evidence_id,
            )
        )
    groups = tuple(final_groups)
    invalidated = confirming_candle is not None
    observed_count = (
        policy.invalidation_consecutive_close_count if invalidated else consecutive
    )
    invalidation_record = {
        "invalidated": invalidated,
        "direction": direction,
        "origin_price": origin.price,
        "threshold_price": threshold,
        "buffer": policy.invalidation_buffer,
        "consecutive_close_count": policy.invalidation_consecutive_close_count,
        "observed_consecutive_closes": observed_count,
        "strict_comparison": "below" if direction == "bullish" else "above",
        "wick_only_breaches_count": wick_only_breaches_count,
        "evaluated_after_endpoint_confirmation": endpoint.confirmation_time,
        "confirming_market_data_id": (
            confirming_candle.market_data_id if confirming_candle else None
        ),
        "confirmation_time": (
            confirming_candle.event_time + interval if confirming_candle else None
        ),
    }
    invalidation_evidence = _make_evidence(
        payload=_level_payload(
            evidence_kind="invalidation",
            snapshot=snapshot,
            quality=quality,
            structure=market_structure,
            timeframe=timeframe,
            price_unit=price_unit,
            policy=policy,
            direction=direction,
            move=move,
            anchors=anchors,  # type: ignore[arg-type]
            source_ids=invalidation_source_ids or source_ids,
            invalidation=invalidation_record,
        ),
        snapshot=snapshot,
        quality=quality,
        expires_at=expires_at,
        price_unit=price_unit,
        evidence_kind="invalidation",
        policy=policy,
    )
    evidence_items.append(invalidation_evidence)
    invalidation = FibonacciInvalidation(
        invalidated,
        threshold,
        policy.invalidation_buffer,
        policy.invalidation_consecutive_close_count,
        observed_count,
        confirming_candle.market_data_id if confirming_candle else None,
        confirming_candle.event_time + interval if confirming_candle else None,
        invalidation_evidence.evidence_id,
    )

    observations_output = [
        DomainObservation(
            "anchor",
            canonical_json_dumps(
                {
                    "direction": direction,
                    "move": move,
                    "origin": anchors[0],
                    "endpoint": anchors[1],
                    "selection": "explicit-caller-selection",
                }
            ),
            price_unit,
            timeframe,
            VersionReference(
                SPOT_FIBONACCI_INDICATOR_ID, SPOT_FIBONACCI_METHOD_VERSION
            ),
            (anchor_evidence.evidence_id,),
        )
    ]
    findings: list[AnalyticalFinding] = [
        AnalyticalFinding(
            _stable_id("finding", anchor_evidence.evidence_id),
            "anchor",
            ClaimClassification.FACT,
            "Caller-selected confirmed same-timeframe Spot pivots define a positive price move.",
            (anchor_evidence.evidence_id,),
            VersionReference(
                SPOT_FIBONACCI_INDICATOR_ID, SPOT_FIBONACCI_METHOD_VERSION
            ),
            "Superseded by corrected source candles, different anchor IDs, or a new policy/method version.",
            _LIMITATIONS,
        )
    ]
    evidence_by_group = {item.group_id: item for item in groups}
    for level in levels:
        member_groups = tuple(
            evidence_by_group[group_id] for group_id in level.confluence_group_ids
        )
        evidence_ids = (
            level.evidence_id,
            *(item.evidence_id for item in member_groups),
        )
        observations_output.append(
            DomainObservation(
                level.category,
                canonical_json_dumps(
                    {
                        "level_id": level.level_id,
                        "ratio": level.ratio,
                        "price": level.price,
                        "as_of": snapshot.as_of,
                        "confluence_group_ids": level.confluence_group_ids,
                        "correlated_not_independent": bool(member_groups),
                    }
                ),
                price_unit,
                timeframe,
                VersionReference(
                    SPOT_FIBONACCI_INDICATOR_ID, SPOT_FIBONACCI_METHOD_VERSION
                ),
                evidence_ids,
            )
        )
        findings.append(
            AnalyticalFinding(
                _stable_id("finding", level.evidence_id),
                level.category,
                ClaimClassification.FACT,
                f"Caller-selected {level.category} reference level at ratio {level.ratio}.",
                evidence_ids,
                VersionReference(
                    SPOT_FIBONACCI_INDICATOR_ID, SPOT_FIBONACCI_METHOD_VERSION
                ),
                "Expires at the next boundary for this timeframe or on source/policy correction.",
                _LIMITATIONS,
            )
        )
    for group in groups:
        findings.append(
            AnalyticalFinding(
                _stable_id("finding", group.evidence_id),
                "confluence-reference",
                ClaimClassification.FACT,
                "A fixed-anchor tolerance group contains overlapping calculated levels.",
                (group.evidence_id,),
                VersionReference(
                    SPOT_FIBONACCI_INDICATOR_ID, SPOT_FIBONACCI_METHOD_VERSION
                ),
                "Expires with the linked level evidence or on source/policy correction.",
                _LIMITATIONS,
            )
        )
    observations_output.append(
        DomainObservation(
            "invalidation",
            canonical_json_dumps(invalidation_record),
            price_unit,
            timeframe,
            VersionReference(
                SPOT_FIBONACCI_INDICATOR_ID, SPOT_FIBONACCI_METHOD_VERSION
            ),
            (invalidation_evidence.evidence_id,),
        )
    )
    findings.append(
        AnalyticalFinding(
            _stable_id("finding", invalidation_evidence.evidence_id),
            "invalidation",
            ClaimClassification.FACT,
            "The explicit strict consecutive-close invalidation rule is evaluated through the snapshot cutoff.",
            (invalidation_evidence.evidence_id,),
            VersionReference(
                SPOT_FIBONACCI_INDICATOR_ID, SPOT_FIBONACCI_METHOD_VERSION
            ),
            "Superseded by a source correction, new snapshot, or new policy/method version.",
            _LIMITATIONS,
        )
    )
    all_evidence = tuple(evidence_items)
    if (
        len(observations_output) + len(all_evidence) > policy.maximum_output_records
        or len(all_evidence) > policy.maximum_output_records
    ):
        raise SpotFibonacciError("Fibonacci output exceeds the caller policy bound.")
    if sum(len(item.value.encode("utf-8")) for item in all_evidence) > (
        _MAX_TOTAL_EVIDENCE_BYTES
    ):
        raise SpotFibonacciError("Fibonacci evidence exceeds the aggregate byte bound.")
    assessment = FibonacciAssessment(
        assessment_id=_stable_id(
            "assessment",
            snapshot.snapshot_id,
            quality.report_id,
            SPOT_FIBONACCI_METHOD_VERSION,
            policy,
            tuple(item.evidence_id for item in all_evidence),
        ),
        asset=snapshot.instrument_id,
        instrument_id=snapshot.instrument_id,
        timeframe=timeframe,
        as_of=snapshot.as_of,
        available_at=quality.assessed_at,
        expires_at=expires_at,
        status=AssessmentStatus.AVAILABLE,
        analytical_confidence=Decimal(0),
        findings=tuple(findings),
        observations=tuple(observations_output),
        evidence_ids=tuple(item.evidence_id for item in all_evidence),
        contradiction_ids=(),
        uncertainty_ids=tuple(item.evidence_id for item in all_evidence),
        data_quality_report_id=quality.report_id,
        provenance=(
            VersionReference("C-001", "1"),
            VersionReference("C-002", "1"),
            VersionReference("C-003", "1"),
            VersionReference("C-008", "1"),
            VersionReference("C-068", "1"),
            VersionReference(
                MARKET_STRUCTURE_INDICATOR_ID, MARKET_STRUCTURE_METHOD_VERSION
            ),
            VersionReference(
                SPOT_FIBONACCI_INDICATOR_ID, SPOT_FIBONACCI_METHOD_VERSION
            ),
            _policy_reference(policy),
        ),
        methodology=MethodologyCategory.TECHNICAL,
    )
    return SpotFibonacciAnalysis(
        SPOT_FIBONACCI_INDICATOR_ID,
        metadata.metadata_version,
        metadata.calculation_version,
        timeframe,
        snapshot.instrument_id,
        snapshot.venue_id,
        snapshot.snapshot_id,
        quality.report_id,
        snapshot.as_of,
        expires_at,
        snapshot.source_record_ids,
        snapshot.market_data_ids,
        price_unit,
        policy,
        direction,
        move,
        anchors,  # type: ignore[arg-type]
        levels,
        groups,
        invalidation,
        all_evidence,
        assessment,
    )


__all__ = [
    "SPOT_FIBONACCI_EVIDENCE_VERSION",
    "SPOT_FIBONACCI_INDICATOR_ID",
    "SPOT_FIBONACCI_METADATA_VERSION",
    "SPOT_FIBONACCI_METHOD_VERSION",
    "FibonacciAnchor",
    "FibonacciConfluenceGroup",
    "FibonacciInvalidation",
    "FibonacciLevel",
    "SpotFibonacciAnalysis",
    "SpotFibonacciError",
    "SpotFibonacciPolicy",
    "calculate_spot_fibonacci",
]
