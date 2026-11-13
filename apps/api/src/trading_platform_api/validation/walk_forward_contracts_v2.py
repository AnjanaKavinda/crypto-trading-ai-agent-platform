"""Additive C-029 schema 2 for observation-only Spot walk-forward evidence."""

from __future__ import annotations

from dataclasses import dataclass, field, fields
from datetime import UTC, datetime, timedelta
from decimal import ROUND_HALF_EVEN, Context, Decimal, localcontext
from enum import StrEnum
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid5

from trading_platform_api.config import DeploymentEnvironment, OperatingMode
from trading_platform_api.contracts.serialization import (
    CANONICAL_JSON_VERSION,
    canonical_sha256,
)
from trading_platform_api.market_data.ohlcv import _TIMEFRAMES
from trading_platform_api.validation.contracts import (
    CheckOutcome,
    DataPartition,
    MetricValue,
    PartitionPurpose,
)
from trading_platform_api.validation.contracts_v2 import ValidationArtifactReferenceV2
from trading_platform_api.validation.oos_contracts_v2 import (
    MAX_CANDIDATES,
    MAX_EVENTS,
    OOSCandidateV2,
    OOSEventKind,
    OOSJournalSnapshot,
    OOSOutcome,
    OOSProtocolV2,
    OOSResultV2,
    OOSSelectionMode,
    OOSWindow,
)
from trading_platform_api.validation.spot_metrics import (
    METHOD as METRICS_METHOD,
)
from trading_platform_api.validation.spot_metrics import (
    MetricsPolicy,
    MetricState,
    TradeObservation,
)

METHOD = "spot-walk-forward-observation-v1"
AGGREGATION_METHOD = "walk-forward-descriptive-decimal-v1"
NAMESPACE = uuid5(NAMESPACE_URL, "trading-platform:C-029:2:" + METHOD)
MAX_FOLDS = 128
_ARITHMETIC = Context(prec=50, rounding=ROUND_HALF_EVEN)
_METRIC_NAMES = (
    "total_trades",
    "win_rate",
    "expectancy",
    "profit_factor",
    "maximum_fractional_drawdown",
    "sharpe",
    "sortino",
    "cumulative_return",
    "net_realized_profit",
)
_HIGHER_IS_BETTER = frozenset(
    {
        "win_rate",
        "expectancy",
        "profit_factor",
        "sharpe",
        "sortino",
        "cumulative_return",
        "net_realized_profit",
    }
)


def _require(condition: bool, reason: str) -> None:
    if not condition:
        raise ValueError(reason)


def _digest(value: str) -> None:
    _require(
        type(value) is str
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value),
        "INVALID_WALK_FORWARD_DIGEST",
    )


def _text(value: str) -> None:
    _require(
        type(value) is str and bool(value) and value == value.strip(),
        "INVALID_WALK_FORWARD_TEXT",
    )


def _utc(value: datetime) -> datetime:
    _require(
        type(value) is datetime and value.tzinfo is not None,
        "INVALID_WALK_FORWARD_TIME",
    )
    return value.astimezone(UTC)


def _payload(value: Any, omitted: set[str]) -> dict[str, object]:
    return {
        item.name: getattr(value, item.name)
        for item in fields(value)
        if item.name not in omitted
    }


def _grid_aligned(value: datetime, timeframe: str) -> bool:
    seconds = _TIMEFRAMES[timeframe]
    anchor = (
        datetime(1970, 1, 5, tzinfo=UTC)
        if timeframe == "1w"
        else datetime(1970, 1, 1, tzinfo=UTC)
    )
    elapsed = value - anchor
    return (
        elapsed.microseconds == 0
        and (elapsed.days * 86400 + elapsed.seconds) % seconds == 0
    )


def _receipt_outcome(
    event: Any,
) -> tuple[OOSOutcome, CheckOutcome, CheckOutcome, CheckOutcome]:
    parts = event.purpose.split(":", 5)
    _require(
        event.kind is OOSEventKind.RESULT
        and len(parts) == 6
        and parts[0] == "RECORDED_OUTCOME",
        "INVALID_WALK_FORWARD_TERMINAL_RECEIPT",
    )
    _digest(parts[5])
    try:
        return (
            OOSOutcome(parts[1]),
            CheckOutcome(parts[2]),
            CheckOutcome(parts[3]),
            CheckOutcome(parts[4]),
        )
    except ValueError as error:
        raise ValueError("INVALID_WALK_FORWARD_TERMINAL_RECEIPT") from error


class WalkForwardMode(StrEnum):
    ROLLING = "ROLLING"
    ANCHORED = "ANCHORED"


class WalkForwardOutcome(StrEnum):
    OBSERVED = "OBSERVED"
    INCONCLUSIVE = "INCONCLUSIVE"
    FAILED = "FAILED"


class FoldTerminalState(StrEnum):
    OBSERVED = "OBSERVED"
    INCONCLUSIVE = "INCONCLUSIVE"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class MetricDirection(StrEnum):
    HIGHER = "HIGHER_IS_BETTER"
    LOWER = "LOWER_IS_BETTER"
    DESCRIPTIVE = "DESCRIPTIVE_ONLY"


@dataclass(frozen=True, slots=True)
class WalkForwardFoldPlanV2:
    fold_id: UUID
    index: int
    training: DataPartition
    selection_validation: DataPartition
    heldout: DataPartition

    def __post_init__(self) -> None:
        _require(type(self.fold_id) is UUID, "INVALID_FOLD_ID")
        _require(type(self.index) is int and self.index >= 0, "INVALID_FOLD_INDEX")
        parts = (self.training, self.selection_validation, self.heldout)
        _require(
            all(type(item) is DataPartition for item in parts),
            "INVALID_FOLD_PARTITIONS",
        )
        _require(
            (
                self.training.purpose,
                self.selection_validation.purpose,
                self.heldout.purpose,
            )
            == (
                PartitionPurpose.TRAIN,
                PartitionPurpose.VALIDATION,
                PartitionPurpose.TEST,
            ),
            "INVALID_FOLD_PARTITION_ROLES",
        )
        _require(
            len({item.partition_id for item in parts}) == 3,
            "DUPLICATE_FOLD_PARTITION_ID",
        )
        _require(
            self.training.end <= self.selection_validation.start
            and self.selection_validation.end <= self.heldout.start,
            "FOLD_PARTITION_OVERLAP",
        )
        _require(
            all(
                item.point_in_time_cutoff == item.end and not item.used_for_optimization
                for item in (self.selection_validation, self.heldout)
            )
            and self.training.point_in_time_cutoff == self.training.end
            and self.training.used_for_optimization,
            "INVALID_FOLD_POINT_IN_TIME_CUTOFF",
        )


@dataclass(frozen=True, slots=True)
class WalkForwardRequestPinV2:
    request: ValidationArtifactReferenceV2
    fold_id: UUID
    candidate_id: UUID
    partition_id: UUID
    partition_role: PartitionPurpose
    result_as_of: datetime
    created_at: datetime
    expires_at: datetime
    strategy: ValidationArtifactReferenceV2
    parameter_set: ValidationArtifactReferenceV2
    cost_assumptions: ValidationArtifactReferenceV2
    cost_adapter: ValidationArtifactReferenceV2
    execution_policy_sha256: str
    execution_dataset_sha256: str
    execution_manifest_sha256: str
    archive_pins_sha256: str

    def __post_init__(self) -> None:
        _require(
            type(self.request) is ValidationArtifactReferenceV2
            and self.request.artifact_type == "SPOT_OOS_REQUEST"
            and self.request.version == "1",
            "INVALID_WALK_FORWARD_REQUEST_REFERENCE",
        )
        _require(
            type(self.fold_id) is UUID
            and type(self.candidate_id) is UUID
            and type(self.partition_id) is UUID
            and self.partition_role
            in (
                PartitionPurpose.TRAIN,
                PartitionPurpose.VALIDATION,
                PartitionPurpose.TEST,
            ),
            "INVALID_WALK_FORWARD_REQUEST_SCOPE",
        )
        _require(
            type(self.strategy) is ValidationArtifactReferenceV2
            and self.strategy.artifact_type == "C-021"
            and self.strategy.version == "2"
            and type(self.parameter_set) is ValidationArtifactReferenceV2
            and self.parameter_set.artifact_type == "PARAMETER_SET"
            and type(self.cost_assumptions) is ValidationArtifactReferenceV2
            and self.cost_assumptions.artifact_type == "C-027"
            and self.cost_assumptions.version == "2"
            and type(self.cost_adapter) is ValidationArtifactReferenceV2,
            "INVALID_WALK_FORWARD_REQUEST_ARTIFACTS",
        )
        for value in (
            self.execution_policy_sha256,
            self.execution_dataset_sha256,
            self.execution_manifest_sha256,
            self.archive_pins_sha256,
        ):
            _digest(value)
        for name in ("result_as_of", "created_at", "expires_at"):
            object.__setattr__(self, name, _utc(getattr(self, name)))
        _require(
            self.result_as_of <= self.created_at < self.expires_at,
            "INVALID_WALK_FORWARD_REQUEST_TIME",
        )


@dataclass(frozen=True, slots=True)
class WalkForwardPlanSpecV2:
    scope: OOSWindow
    mode: WalkForwardMode
    training_bars: int
    validation_bars: int
    heldout_bars: int
    step_bars: int
    embargo_bars: int
    warmup_bars: int
    minimum_folds: int
    minimum_trades: int
    minimum_returns: int
    maximum_folds: int
    maximum_candidates: int
    maximum_events: int
    candidates: tuple[OOSCandidateV2, ...]
    selection_mode: OOSSelectionMode
    metrics_policy: MetricsPolicy
    environment: DeploymentEnvironment
    journal_id: UUID
    authority: ValidationArtifactReferenceV2
    frozen_at: datetime
    request_bindings_by_fold: tuple[tuple[WalkForwardRequestPinV2, ...], ...] = ()

    def __post_init__(self) -> None:
        _require(type(self.scope) is OOSWindow, "INVALID_WALK_FORWARD_SCOPE")
        _require(type(self.mode) is WalkForwardMode, "INVALID_WALK_FORWARD_MODE")
        for name in (
            "training_bars",
            "validation_bars",
            "heldout_bars",
            "step_bars",
        ):
            _require(
                type(getattr(self, name)) is int
                and 0 < getattr(self, name) <= 1_000_000,
                "INVALID_WALK_FORWARD_WINDOW_LENGTH",
            )
        _require(
            type(self.embargo_bars) is int and 0 <= self.embargo_bars <= 100_000,
            "INVALID_WALK_FORWARD_EMBARGO",
        )
        _require(
            type(self.warmup_bars) is int and 0 <= self.warmup_bars <= 10_000,
            "INVALID_WALK_FORWARD_WARMUP",
        )
        _require(self.step_bars >= self.heldout_bars, "HELDOUT_WINDOWS_OVERLAP")
        _require(
            type(self.minimum_folds) is int and 2 <= self.minimum_folds <= MAX_FOLDS,
            "INVALID_MINIMUM_FOLDS",
        )
        _require(
            type(self.minimum_trades) is int
            and 1 <= self.minimum_trades <= 1000
            and self.minimum_trades == self.metrics_policy.min_trade_sample,
            "INVALID_MINIMUM_TRADE_SAMPLE",
        )
        _require(
            type(self.minimum_returns) is int
            and 1 <= self.minimum_returns <= 1000
            and self.minimum_returns == self.metrics_policy.min_return_sample,
            "INVALID_MINIMUM_RETURN_SAMPLE",
        )
        _require(
            type(self.maximum_folds) is int
            and self.minimum_folds <= self.maximum_folds <= MAX_FOLDS,
            "INVALID_MAXIMUM_FOLDS",
        )
        _require(
            type(self.maximum_events) is int and 1 <= self.maximum_events <= MAX_EVENTS,
            "INVALID_EVENT_BUDGET",
        )
        _require(
            type(self.candidates) is tuple
            and 1 <= len(self.candidates) <= MAX_CANDIDATES
            and all(type(item) is OOSCandidateV2 for item in self.candidates)
            and len({item.candidate_id for item in self.candidates})
            == len(self.candidates),
            "INVALID_CANDIDATES",
        )
        _require(
            type(self.maximum_candidates) is int
            and 1 <= self.maximum_candidates <= MAX_CANDIDATES
            and len(self.candidates) <= self.maximum_candidates,
            "INVALID_CANDIDATE_BUDGET",
        )
        _require(
            len(
                {
                    (
                        item.strategy,
                        item.costs,
                        item.cost_adapter,
                        item.execution_policy_sha256,
                    )
                    for item in self.candidates
                }
            )
            == 1,
            "WALK_FORWARD_CANDIDATE_SCOPE_MISMATCH",
        )
        _require(
            type(self.selection_mode) is OOSSelectionMode
            and type(self.metrics_policy) is MetricsPolicy,
            "INVALID_WALK_FORWARD_SELECTION_POLICY",
        )
        _require(
            (self.selection_mode is not OOSSelectionMode.FIXED)
            or len(self.candidates) == 1,
            "FIXED_SELECTION_REQUIRES_ONE_CANDIDATE",
        )
        _require(
            self.environment in (DeploymentEnvironment.DEV, DeploymentEnvironment.TEST)
            and type(self.journal_id) is UUID,
            "UNSUPPORTED_WALK_FORWARD_ENVIRONMENT",
        )
        _require(
            type(self.authority) is ValidationArtifactReferenceV2,
            "INVALID_WALK_FORWARD_AUTHORITY",
        )
        object.__setattr__(self, "frozen_at", _utc(self.frozen_at))
        step = _TIMEFRAMES[self.scope.timeframe]
        _require(
            _grid_aligned(self.scope.start, self.scope.timeframe)
            and _grid_aligned(self.scope.end, self.scope.timeframe)
            and self.metrics_policy.interval_seconds == step,
            "WALK_FORWARD_GRID_MISMATCH",
        )
        _require(
            self.embargo_bars * step <= 31_536_000,
            "WALK_FORWARD_EMBARGO_EXCEEDS_OOS_LIMIT",
        )
        if self.request_bindings_by_fold:
            fold_count = len(generate_walk_forward_folds(self))
            expected_per_fold = (
                1
                if self.selection_mode is OOSSelectionMode.FIXED
                else 3 * len(self.candidates)
            )
            _require(
                type(self.request_bindings_by_fold) is tuple
                and len(self.request_bindings_by_fold) == fold_count
                and all(
                    type(row) is tuple
                    and len(row) == expected_per_fold
                    and all(
                        type(reference) is WalkForwardRequestPinV2 for reference in row
                    )
                    and len({reference.request.artifact_id for reference in row})
                    == len(row)
                    for row in self.request_bindings_by_fold
                ),
                "INVALID_WALK_FORWARD_REQUEST_PLAN",
            )


def generate_walk_forward_folds(
    spec: WalkForwardPlanSpecV2,
) -> tuple[WalkForwardFoldPlanV2, ...]:
    """Generate an immutable, UTC grid-aligned plan without reading held-out data."""
    _require(type(spec) is WalkForwardPlanSpecV2, "INVALID_WALK_FORWARD_SPEC")
    step = timedelta(seconds=_TIMEFRAMES[spec.scope.timeframe])
    train_span = step * spec.training_bars
    validation_span = step * spec.validation_bars
    heldout_span = step * spec.heldout_bars
    embargo = step * spec.embargo_bars
    cursor = spec.scope.start + train_span + validation_span + embargo * 2
    folds: list[WalkForwardFoldPlanV2] = []
    preimage = canonical_sha256(
        _payload(spec, {"frozen_at", "request_bindings_by_fold"})
    )
    while cursor + heldout_span <= spec.scope.end:
        validation_end = cursor - embargo
        validation_start = validation_end - validation_span
        training_end = validation_start - embargo
        training_start = (
            spec.scope.start
            if spec.mode is WalkForwardMode.ANCHORED
            else training_end - train_span
        )
        _require(
            spec.scope.start <= training_start < training_end
            and training_end <= validation_start < validation_end <= cursor,
            "INVALID_GENERATED_FOLD_BOUNDARIES",
        )
        index = len(folds)
        fold_id = uuid5(NAMESPACE, f"fold:{preimage}:{index}")
        folds.append(
            WalkForwardFoldPlanV2(
                fold_id,
                index,
                DataPartition(
                    uuid5(NAMESPACE, f"partition:{fold_id}:train"),
                    PartitionPurpose.TRAIN,
                    training_start,
                    training_end,
                    training_end,
                    True,
                ),
                DataPartition(
                    uuid5(NAMESPACE, f"partition:{fold_id}:validation"),
                    PartitionPurpose.VALIDATION,
                    validation_start,
                    validation_end,
                    validation_end,
                    False,
                ),
                DataPartition(
                    uuid5(NAMESPACE, f"partition:{fold_id}:heldout"),
                    PartitionPurpose.TEST,
                    cursor,
                    cursor + heldout_span,
                    cursor + heldout_span,
                    False,
                ),
            )
        )
        _require(len(folds) <= spec.maximum_folds, "WALK_FORWARD_FOLD_BUDGET_EXCEEDED")
        cursor += step * spec.step_bars
    _require(len(folds) >= spec.minimum_folds, "INSUFFICIENT_WALK_FORWARD_FOLDS")
    per_fold_events = (
        4
        if spec.selection_mode is OOSSelectionMode.FIXED
        else 4 * len(spec.candidates) + 4
    )
    _require(
        len(folds) * per_fold_events <= spec.maximum_events,
        "WALK_FORWARD_EVENT_BUDGET_EXCEEDED",
    )
    for previous, current in zip(folds, folds[1:]):
        _require(
            previous.heldout.end <= current.heldout.start,
            "HELDOUT_WINDOWS_OVERLAP",
        )
    return tuple(folds)


@dataclass(frozen=True, slots=True)
class WalkForwardProtocolV2:
    protocol_id: UUID
    content_sha256: str
    spec: WalkForwardPlanSpecV2
    folds: tuple[WalkForwardFoldPlanV2, ...]
    method: str = field(default=METHOD, init=False)
    contract_id: str = field(default="C-029", init=False)
    schema_version: str = field(default="2", init=False)
    canonicalization_version: str = field(default=CANONICAL_JSON_VERSION, init=False)
    aggregation_method: str = field(default=AGGREGATION_METHOD, init=False)

    def __post_init__(self) -> None:
        _require(type(self.protocol_id) is UUID, "INVALID_WALK_FORWARD_PROTOCOL_ID")
        _require(type(self.spec) is WalkForwardPlanSpecV2, "INVALID_WALK_FORWARD_SPEC")
        expected = generate_walk_forward_folds(self.spec)
        _require(
            type(self.folds) is tuple and self.folds == expected,
            "WALK_FORWARD_PROTOCOL_FOLD_PLAN_MISMATCH",
        )
        _require(
            bool(self.folds) and len(self.folds) <= self.spec.maximum_folds,
            "INVALID_WALK_FORWARD_FOLD_COUNT",
        )
        _require(
            len(self.spec.request_bindings_by_fold) == len(self.folds),
            "WALK_FORWARD_REQUEST_PLAN_NOT_FROZEN",
        )
        for fold, pins in zip(
            self.folds, self.spec.request_bindings_by_fold, strict=True
        ):
            expected_roles = (
                ((self.spec.candidates[0], fold.heldout, PartitionPurpose.TEST),)
                if self.spec.selection_mode is OOSSelectionMode.FIXED
                else tuple(
                    (candidate, partition, role)
                    for candidate in self.spec.candidates
                    for partition, role in (
                        (fold.training, PartitionPurpose.TRAIN),
                        (fold.selection_validation, PartitionPurpose.VALIDATION),
                        (fold.heldout, PartitionPurpose.TEST),
                    )
                )
            )
            _require(
                tuple(
                    (
                        pin.candidate_id,
                        pin.partition_id,
                        pin.partition_role,
                    )
                    for pin in pins
                )
                == tuple(
                    (
                        candidate.candidate_id,
                        partition.partition_id,
                        role,
                    )
                    for candidate, partition, role in expected_roles
                )
                and all(
                    (
                        pin.strategy,
                        pin.parameter_set,
                        pin.cost_assumptions,
                        pin.cost_adapter,
                        pin.execution_policy_sha256,
                    )
                    == (
                        candidate.strategy,
                        candidate.parameters,
                        candidate.costs,
                        candidate.cost_adapter,
                        candidate.execution_policy_sha256,
                    )
                    and pin.result_as_of == partition.end
                    for pin, (candidate, partition, _) in zip(
                        pins, expected_roles, strict=True
                    )
                ),
                "WALK_FORWARD_REQUEST_PLAN_MISMATCH",
            )
        all_request_ids = tuple(
            pin.request.artifact_id
            for row in self.spec.request_bindings_by_fold
            for pin in row
        )
        _require(
            len(set(all_request_ids)) == len(all_request_ids),
            "DUPLICATE_WALK_FORWARD_REQUEST_BINDING",
        )
        _digest(self.content_sha256)
        sha = canonical_sha256(_payload(self, {"protocol_id", "content_sha256"}))
        _require(
            self.content_sha256 == sha
            and self.protocol_id == uuid5(NAMESPACE, "protocol:" + sha),
            "WALK_FORWARD_PROTOCOL_DIGEST_MISMATCH",
        )

    @classmethod
    def build(cls, spec: WalkForwardPlanSpecV2) -> WalkForwardProtocolV2:
        folds = generate_walk_forward_folds(spec)
        preimage = {
            "spec": spec,
            "folds": folds,
            "method": METHOD,
            "contract_id": "C-029",
            "schema_version": "2",
            "canonicalization_version": CANONICAL_JSON_VERSION,
            "aggregation_method": AGGREGATION_METHOD,
        }
        sha = canonical_sha256(preimage)
        return cls(
            uuid5(NAMESPACE, "protocol:" + sha),
            sha,
            spec,
            folds,
        )


@dataclass(frozen=True, slots=True)
class WalkForwardMetricV2:
    name: str
    state: MetricState
    reason: str | None
    value: MetricValue | None
    unit: str
    sample_count: int
    warnings: tuple[str, ...]

    def __post_init__(self) -> None:
        _text(self.name)
        _text(self.unit)
        _require(type(self.state) is MetricState, "INVALID_WALK_FORWARD_METRIC_STATE")
        _require(
            type(self.sample_count) is int and self.sample_count >= 0,
            "INVALID_WALK_FORWARD_METRIC_SAMPLE",
        )
        _require(
            type(self.warnings) is tuple
            and all(type(item) is str for item in self.warnings),
            "INVALID_WALK_FORWARD_METRIC_WARNINGS",
        )
        if self.state is MetricState.AVAILABLE:
            _require(
                type(self.value) is MetricValue
                and self.value.name == self.name
                and self.value.unit == self.unit
                and self.value.methodology_version == METRICS_METHOD
                and self.reason is None,
                "INVALID_AVAILABLE_WALK_FORWARD_METRIC",
            )
        else:
            _require(
                self.value is None and type(self.reason) is str and bool(self.reason),
                "MISSING_WALK_FORWARD_METRIC_REASON",
            )


@dataclass(frozen=True, slots=True)
class WalkForwardMetricAggregateV2:
    name: str
    unit: str
    direction: MetricDirection
    planned_count: int
    completed_count: int
    available_count: int
    unavailable_count: int
    failed_count: int
    inconclusive_count: int
    unavailable_reasons: tuple[tuple[str, int], ...]
    mean: Decimal | None
    median: Decimal | None
    population_standard_deviation: Decimal | None
    minimum: Decimal | None
    minimum_fold_id: UUID | None
    maximum: Decimal | None
    maximum_fold_id: UUID | None
    best_fold_id: UUID | None
    worst_fold_id: UUID | None
    method: str = AGGREGATION_METHOD

    def __post_init__(self) -> None:
        _text(self.name)
        _text(self.unit)
        _require(
            type(self.direction) is MetricDirection
            and self.method == AGGREGATION_METHOD,
            "INVALID_WALK_FORWARD_AGGREGATION_METHOD",
        )
        for name in (
            "planned_count",
            "completed_count",
            "available_count",
            "unavailable_count",
            "failed_count",
            "inconclusive_count",
        ):
            _require(
                type(getattr(self, name)) is int and getattr(self, name) >= 0,
                "INVALID_WALK_FORWARD_COVERAGE",
            )
        _require(
            self.completed_count + self.failed_count + self.inconclusive_count
            == self.planned_count
            and self.available_count + self.unavailable_count == self.planned_count,
            "WALK_FORWARD_COVERAGE_MISMATCH",
        )
        _require(
            type(self.unavailable_reasons) is tuple
            and all(
                type(reason) is str
                and bool(reason)
                and type(count) is int
                and count > 0
                for reason, count in self.unavailable_reasons
            )
            and sum(count for _, count in self.unavailable_reasons)
            == self.unavailable_count,
            "WALK_FORWARD_UNAVAILABLE_COVERAGE_MISMATCH",
        )
        stats = (
            self.mean,
            self.median,
            self.population_standard_deviation,
            self.minimum,
            self.maximum,
        )
        if self.available_count:
            _require(
                all(type(value) is Decimal and value.is_finite() for value in stats)
                and self.minimum_fold_id is not None
                and self.maximum_fold_id is not None
                and (
                    self.direction is MetricDirection.DESCRIPTIVE
                    and self.best_fold_id is self.worst_fold_id is None
                    or self.direction is not MetricDirection.DESCRIPTIVE
                    and self.best_fold_id is not None
                    and self.worst_fold_id is not None
                ),
                "MISSING_WALK_FORWARD_AGGREGATE",
            )
        else:
            _require(
                all(value is None for value in stats)
                and all(
                    value is None
                    for value in (
                        self.minimum_fold_id,
                        self.maximum_fold_id,
                        self.best_fold_id,
                        self.worst_fold_id,
                    )
                ),
                "AGGREGATE_WITHOUT_AVAILABLE_METRICS",
            )


@dataclass(frozen=True, slots=True)
class WalkForwardConsistencyV2:
    positive_folds: int
    available_return_folds: int
    planned_folds: int
    missing_return_folds: int
    ratio: Decimal | None

    def __post_init__(self) -> None:
        for name in (
            "positive_folds",
            "available_return_folds",
            "planned_folds",
            "missing_return_folds",
        ):
            _require(
                type(getattr(self, name)) is int and getattr(self, name) >= 0,
                "INVALID_WALK_FORWARD_CONSISTENCY",
            )
        _require(
            self.positive_folds <= self.available_return_folds
            and self.available_return_folds + self.missing_return_folds
            == self.planned_folds,
            "WALK_FORWARD_CONSISTENCY_DENOMINATOR_MISMATCH",
        )
        if self.available_return_folds:
            with localcontext(_ARITHMETIC):
                expected_ratio = Decimal(self.positive_folds) / Decimal(
                    self.available_return_folds
                )
            _require(
                type(self.ratio) is Decimal and self.ratio == expected_ratio,
                "WALK_FORWARD_CONSISTENCY_RATIO_MISMATCH",
            )
        else:
            _require(self.ratio is None, "WALK_FORWARD_CONSISTENCY_WITHOUT_SAMPLE")


@dataclass(frozen=True, slots=True)
class WalkForwardFoldObservationV2:
    fold_id: UUID
    state: FoldTerminalState
    oos_protocol: OOSProtocolV2
    oos_result: OOSResultV2 | None
    request_bindings: tuple[ValidationArtifactReferenceV2, ...]
    journal_id: UUID
    receipt_id: UUID | None
    receipt_sha256: str | None
    integrity: CheckOutcome
    contamination: CheckOutcome
    sample_sufficiency: CheckOutcome
    selected_candidate_id: UUID | None
    metrics: tuple[WalkForwardMetricV2, ...]
    trades: tuple[TradeObservation, ...]
    reason_codes: tuple[str, ...]

    def __post_init__(self) -> None:
        _require(type(self.fold_id) is UUID, "INVALID_OBSERVATION_FOLD_ID")
        _require(type(self.state) is FoldTerminalState, "INVALID_FOLD_TERMINAL_STATE")
        _require(type(self.oos_protocol) is OOSProtocolV2, "INVALID_FOLD_OOS_PROTOCOL")
        _require(
            type(self.journal_id) is UUID
            and self.journal_id == self.oos_protocol.journal_id,
            "FOLD_JOURNAL_ID_MISMATCH",
        )
        _require(
            type(self.request_bindings) is tuple
            and bool(self.request_bindings)
            and all(
                type(item) is ValidationArtifactReferenceV2
                and item.artifact_type == "SPOT_OOS_REQUEST"
                and item.version == "1"
                for item in self.request_bindings
            )
            and len({item.artifact_id for item in self.request_bindings})
            == len(self.request_bindings),
            "INVALID_FOLD_REQUEST_BINDINGS",
        )
        _require(
            (self.receipt_id is None) == (self.receipt_sha256 is None),
            "INCOMPLETE_FOLD_RECEIPT_IDENTITY",
        )
        if self.receipt_sha256 is not None:
            _digest(self.receipt_sha256)
            _require(type(self.receipt_id) is UUID, "INVALID_FOLD_RECEIPT_ID")
        _require(
            all(
                type(value) is CheckOutcome
                for value in (
                    self.integrity,
                    self.contamination,
                    self.sample_sufficiency,
                )
            ),
            "INVALID_FOLD_CHECK_STATES",
        )
        _require(
            type(self.metrics) is tuple
            and tuple(item.name for item in self.metrics) == _METRIC_NAMES,
            "INVALID_FOLD_METRICS",
        )
        _require(
            type(self.trades) is tuple
            and all(type(item) is TradeObservation for item in self.trades)
            and type(self.reason_codes) is tuple,
            "INVALID_FOLD_REPORT_FIELDS",
        )
        _require(
            len({item.trade_id for item in self.trades}) == len(self.trades),
            "DUPLICATE_FOLD_TRADE",
        )
        if self.oos_result is None:
            _require(
                not self.trades
                and self.state
                in (
                    FoldTerminalState.FAILED,
                    FoldTerminalState.INCONCLUSIVE,
                    FoldTerminalState.CANCELLED,
                )
                and all(
                    item.state is not MetricState.AVAILABLE for item in self.metrics
                ),
                "UNBOUND_FOLD_RESULT",
            )
            if self.receipt_sha256 is not None:
                _require(
                    self.receipt_id
                    == uuid5(NAMESPACE, "journal-receipt:" + self.receipt_sha256),
                    "FOLD_RECEIPT_MISMATCH",
                )
            _require(
                self.state is FoldTerminalState.CANCELLED
                or self.receipt_id is not None,
                "MISSING_FOLD_TERMINAL_RECEIPT",
            )
        else:
            result = self.oos_result
            _require(
                type(result) is OOSResultV2
                and result.protocol == self.oos_protocol
                and result.journal.journal_id == self.journal_id
                and (
                    result.selected_candidate is None
                    and self.selected_candidate_id is None
                    or result.selected_candidate is not None
                    and result.selected_candidate.candidate_id
                    == self.selected_candidate_id
                ),
                "FOLD_OOS_RESULT_BINDING_MISMATCH",
            )
            _require(
                self.reason_codes == result.reason_codes,
                "FOLD_REASON_BINDING_MISMATCH",
            )
            _require(
                result.outcome is not OOSOutcome.FAILED
                or self.state is FoldTerminalState.FAILED,
                "FOLD_OUTCOME_CONTRADICTION",
            )
            _require(
                result.outcome is not OOSOutcome.OBSERVED
                or self.state is FoldTerminalState.OBSERVED,
                "FOLD_OUTCOME_CONTRADICTION",
            )
            _require(
                result.outcome is not OOSOutcome.INCONCLUSIVE
                or self.state
                in (FoldTerminalState.INCONCLUSIVE, FoldTerminalState.CANCELLED),
                "FOLD_OUTCOME_CONTRADICTION",
            )
            _require(
                result.integrity == self.integrity
                and result.contamination == self.contamination
                and result.sample_sufficiency == self.sample_sufficiency,
                "FOLD_CHECK_BINDING_MISMATCH",
            )
            terminal = result.journal.events[-1]
            _require(
                terminal.kind is OOSEventKind.RESULT
                and terminal.protocol_sha256 == self.oos_protocol.content_sha256
                and terminal.content_sha256 == self.receipt_sha256
                and self.receipt_id
                == uuid5(NAMESPACE, "journal-receipt:" + terminal.content_sha256),
                "FOLD_RECEIPT_MISMATCH",
            )
            expected_requests = {
                reference
                for event in result.journal.events
                if event.protocol_sha256 == self.oos_protocol.content_sha256
                and event.kind is OOSEventKind.TRIAL
                for reference in event.evidence
                if reference.artifact_type == "SPOT_OOS_REQUEST"
            }
            expected_requests.add(result.request_reference)
            _require(
                expected_requests <= set(self.request_bindings),
                "FOLD_REQUEST_BINDING_MISMATCH",
            )
            heldout_runs = tuple(
                run
                for run in result.runs
                if run.partition_id == result.protocol.partitions[-1].partition_id
            )
            if heldout_runs:
                _require(len(heldout_runs) == 1, "DUPLICATE_FOLD_HELDOUT_RUN")
                report = heldout_runs[0].resolve_report()
                _require(
                    self.trades == report.trades,
                    "FOLD_RAW_TRADES_MISMATCH",
                )
                for item in self.metrics:
                    metric = report.get(item.name)
                    _require(
                        (
                            item.state,
                            item.reason,
                            item.value,
                            item.unit,
                            item.sample_count,
                            item.warnings,
                        )
                        == (
                            metric.state,
                            metric.reason,
                            metric.metric,
                            metric.metric.unit if metric.metric else item.unit,
                            metric.sample_count,
                            metric.warnings,
                        ),
                        "FOLD_METRIC_REPORT_MISMATCH",
                    )
            else:
                _require(
                    not self.trades
                    and all(
                        item.state is not MetricState.AVAILABLE for item in self.metrics
                    ),
                    "FOLD_REPORT_WITHOUT_HELDOUT_RUN",
                )
        _require(
            self.selected_candidate_id is None
            or self.selected_candidate_id
            in {item.candidate_id for item in self.oos_protocol.candidates},
            "UNKNOWN_FOLD_CANDIDATE",
        )


def _aggregate(
    observations: tuple[WalkForwardFoldObservationV2, ...],
) -> tuple[WalkForwardMetricAggregateV2, ...]:
    output = []
    for name in _METRIC_NAMES:
        rows = tuple(
            (fold, next(m for m in fold.metrics if m.name == name))
            for fold in observations
        )
        available = tuple(
            (fold, metric)
            for fold, metric in rows
            if metric.state is MetricState.AVAILABLE and metric.value is not None
        )
        units = {metric.unit for _, metric in rows}
        _require(len(units) == 1, "INCOMPATIBLE_WALK_FORWARD_METRIC_UNITS")
        reasons: dict[str, int] = {}
        for _, metric in rows:
            if metric.state is not MetricState.AVAILABLE:
                assert metric.reason is not None
                reasons[metric.reason] = reasons.get(metric.reason, 0) + 1
        completed = sum(fold.state is FoldTerminalState.OBSERVED for fold, _ in rows)
        failed = sum(fold.state is FoldTerminalState.FAILED for fold, _ in rows)
        inconclusive = len(rows) - completed - failed
        if available:
            with localcontext(_ARITHMETIC):
                values = sorted(
                    metric.value.value for _, metric in available if metric.value
                )
                count = len(values)
                mean = sum(values, Decimal(0)) / count
                middle = count // 2
                median = (
                    values[middle]
                    if count % 2
                    else (values[middle - 1] + values[middle]) / Decimal(2)
                )
                variance = (
                    sum(((item - mean) ** 2 for item in values), Decimal(0)) / count
                )
                deviation = variance.sqrt()
            minimum, maximum = values[0], values[-1]
            min_id = min(
                str(fold.fold_id)
                for fold, metric in available
                if metric.value and metric.value.value == minimum
            )
            max_id = min(
                str(fold.fold_id)
                for fold, metric in available
                if metric.value and metric.value.value == maximum
            )
            direction = (
                MetricDirection.DESCRIPTIVE
                if name == "total_trades"
                else MetricDirection.HIGHER
                if name in _HIGHER_IS_BETTER
                else MetricDirection.LOWER
            )
            best_id, worst_id = (
                (None, None)
                if direction is MetricDirection.DESCRIPTIVE
                else (max_id, min_id)
                if direction is MetricDirection.HIGHER
                else (min_id, max_id)
            )
            output.append(
                WalkForwardMetricAggregateV2(
                    name,
                    next(iter(units)),
                    direction,
                    len(rows),
                    completed,
                    len(available),
                    len(rows) - len(available),
                    failed,
                    inconclusive,
                    tuple(sorted(reasons.items())),
                    mean,
                    median,
                    deviation,
                    minimum,
                    UUID(min_id),
                    maximum,
                    UUID(max_id),
                    UUID(best_id) if best_id is not None else None,
                    UUID(worst_id) if worst_id is not None else None,
                )
            )
        else:
            output.append(
                WalkForwardMetricAggregateV2(
                    name,
                    next(iter(units)),
                    MetricDirection.DESCRIPTIVE
                    if name == "total_trades"
                    else MetricDirection.HIGHER
                    if name in _HIGHER_IS_BETTER
                    else MetricDirection.LOWER,
                    len(rows),
                    completed,
                    0,
                    len(rows),
                    failed,
                    inconclusive,
                    tuple(sorted(reasons.items())),
                    None,
                    None,
                    None,
                    None,
                    None,
                    None,
                    None,
                    None,
                    None,
                )
            )
    return tuple(output)


def _consistency(
    observations: tuple[WalkForwardFoldObservationV2, ...],
) -> WalkForwardConsistencyV2:
    values = tuple(
        metric
        for fold in observations
        for metric in fold.metrics
        if metric.name == "net_realized_profit"
    )
    available = tuple(
        item
        for item in values
        if item.state is MetricState.AVAILABLE and item.value is not None
    )
    positive = sum(item.value.value > 0 for item in available if item.value is not None)
    with localcontext(_ARITHMETIC):
        ratio = Decimal(positive) / Decimal(len(available)) if available else None
    return WalkForwardConsistencyV2(
        positive,
        len(available),
        len(observations),
        len(observations) - len(available),
        ratio,
    )


def derive_walk_forward_outcome(
    observations: tuple[WalkForwardFoldObservationV2, ...],
    minimum_folds: int,
    minimum_returns: int = 1,
) -> WalkForwardOutcome:
    _require(bool(observations), "MISSING_WALK_FORWARD_OBSERVATIONS")
    if any(
        item.integrity is CheckOutcome.FAILED
        or item.contamination is CheckOutcome.FAILED
        or item.state is FoldTerminalState.FAILED
        for item in observations
    ):
        return WalkForwardOutcome.FAILED
    if len(observations) < minimum_folds or any(
        item.state is not FoldTerminalState.OBSERVED
        or item.sample_sufficiency is not CheckOutcome.PASSED
        for item in observations
    ):
        return WalkForwardOutcome.INCONCLUSIVE
    available_returns = sum(
        metric.state is MetricState.AVAILABLE
        for fold in observations
        for metric in fold.metrics
        if metric.name == "cumulative_return"
    )
    if available_returns < minimum_returns:
        return WalkForwardOutcome.INCONCLUSIVE
    return WalkForwardOutcome.OBSERVED


@dataclass(frozen=True, slots=True)
class WalkForwardResultV2:
    result_id: UUID
    content_sha256: str
    protocol: WalkForwardProtocolV2
    journal: OOSJournalSnapshot
    observations: tuple[WalkForwardFoldObservationV2, ...]
    aggregates: tuple[WalkForwardMetricAggregateV2, ...]
    consistency: WalkForwardConsistencyV2
    outcome: WalkForwardOutcome
    reason_codes: tuple[str, ...]
    as_of: datetime
    created_at: datetime
    expires_at: datetime
    method: str = field(default=METHOD, init=False)
    contract_id: str = field(default="C-029", init=False)
    schema_version: str = field(default="2", init=False)
    operating_mode: OperatingMode = field(default=OperatingMode.BACKTEST, init=False)
    market_scope: str = field(default="SPOT", init=False)
    canonicalization_version: str = field(default=CANONICAL_JSON_VERSION, init=False)

    def __post_init__(self) -> None:
        _require(type(self.result_id) is UUID, "INVALID_WALK_FORWARD_RESULT_ID")
        _require(
            type(self.protocol) is WalkForwardProtocolV2,
            "INVALID_WALK_FORWARD_PROTOCOL",
        )
        _require(
            type(self.journal) is OOSJournalSnapshot,
            "INVALID_WALK_FORWARD_JOURNAL",
        )
        _require(
            (self.journal.journal_id, self.journal.authority)
            == (self.protocol.spec.journal_id, self.protocol.spec.authority),
            "WALK_FORWARD_JOURNAL_MISMATCH",
        )
        _require(
            type(self.observations) is tuple
            and tuple(item.fold_id for item in self.observations)
            == tuple(item.fold_id for item in self.protocol.folds),
            "WALK_FORWARD_FOLD_COVERAGE_MISMATCH",
        )
        partitions = tuple(
            (fold.training, fold.selection_validation, fold.heldout)
            for fold in self.protocol.folds
        )
        _require(
            all(
                observation.oos_protocol.partitions == expected
                and observation.oos_protocol.candidates == self.protocol.spec.candidates
                and observation.oos_protocol.selection_mode
                is self.protocol.spec.selection_mode
                and observation.oos_protocol.metrics_policy_sha256
                == canonical_sha256(self.protocol.spec.metrics_policy)
                and observation.oos_protocol.warmup_bars
                == self.protocol.spec.warmup_bars
                and observation.oos_protocol.embargo_seconds
                == self.protocol.spec.embargo_bars
                * _TIMEFRAMES[self.protocol.spec.scope.timeframe]
                and observation.oos_protocol.environment
                is self.protocol.spec.environment
                and observation.oos_protocol.window.venue
                == self.protocol.spec.scope.venue
                and observation.oos_protocol.window.instrument_id
                == self.protocol.spec.scope.instrument_id
                and observation.oos_protocol.window.timeframe
                == self.protocol.spec.scope.timeframe
                and (
                    observation.oos_protocol.window.start,
                    observation.oos_protocol.window.end,
                )
                == (expected[-1].start, expected[-1].end)
                and observation.request_bindings
                == tuple(
                    pin.request
                    for pin in self.protocol.spec.request_bindings_by_fold[index]
                )
                for index, (observation, expected) in enumerate(
                    zip(self.observations, partitions, strict=True)
                )
            ),
            "WALK_FORWARD_OOS_PROTOCOL_PLAN_MISMATCH",
        )
        for observation in self.observations:
            freezes = tuple(
                event
                for event in self.journal.events
                if event.kind is OOSEventKind.FREEZE
                and event.protocol_sha256 == observation.oos_protocol.content_sha256
            )
            _require(len(freezes) == 1, "WALK_FORWARD_FREEZE_RECEIPT_MISMATCH")
            if observation.oos_result is None:
                selections = tuple(
                    event
                    for event in self.journal.events
                    if event.kind is OOSEventKind.SELECT
                    and event.protocol_sha256 == observation.oos_protocol.content_sha256
                )
                _require(
                    observation.selected_candidate_id
                    == (selections[0].candidate_id if len(selections) == 1 else None),
                    "WALK_FORWARD_SELECTION_BINDING_MISMATCH",
                )
        _require(
            type(self.aggregates) is tuple
            and self.aggregates == _aggregate(self.observations)
            and self.consistency == _consistency(self.observations),
            "WALK_FORWARD_AGGREGATE_MISMATCH",
        )
        expected_outcome = derive_walk_forward_outcome(
            self.observations,
            self.protocol.spec.minimum_folds,
            self.protocol.spec.minimum_returns,
        )
        _require(
            self.outcome is expected_outcome,
            "WALK_FORWARD_OUTCOME_BINDING_MISMATCH",
        )
        _require(
            type(self.reason_codes) is tuple
            and all(type(value) is str and value for value in self.reason_codes),
            "INVALID_WALK_FORWARD_REASONS",
        )
        expected_reasons = {
            reason
            for observation in self.observations
            for reason in observation.reason_codes
        }
        if self.outcome is WalkForwardOutcome.INCONCLUSIVE:
            expected_reasons.add("WALK_FORWARD_COVERAGE_INCOMPLETE")
        if self.outcome is WalkForwardOutcome.FAILED:
            expected_reasons.add("WALK_FORWARD_INTEGRITY_OR_CONTAMINATION_FAILURE")
        _require(
            self.reason_codes == tuple(sorted(expected_reasons)),
            "WALK_FORWARD_REASON_COVERAGE_MISMATCH",
        )
        _require(
            all(
                result.protocol == observation.oos_protocol
                and result.journal.journal_id == self.journal.journal_id
                and self.journal.events[: len(result.journal.events)]
                == result.journal.events
                for observation in self.observations
                if (result := observation.oos_result) is not None
            ),
            "WALK_FORWARD_OOS_JOURNAL_MISMATCH",
        )
        receipts = tuple(item.receipt_sha256 for item in self.observations)
        identified_receipts = tuple(value for value in receipts if value is not None)
        _require(
            len(set(identified_receipts)) == len(identified_receipts),
            "DUPLICATE_WALK_FORWARD_RECEIPT",
        )
        for observation in self.observations:
            if observation.receipt_sha256 is None:
                _require(
                    observation.state is FoldTerminalState.CANCELLED
                    and not any(
                        event.protocol_sha256 == observation.oos_protocol.content_sha256
                        and event.kind is OOSEventKind.RESULT
                        for event in self.journal.events
                    ),
                    "MISSING_FOLD_TERMINAL_RECEIPT",
                )
                continue
            receipt = next(
                (
                    event
                    for event in self.journal.events
                    if event.content_sha256 == observation.receipt_sha256
                ),
                None,
            )
            _require(
                receipt is not None
                and receipt.kind is OOSEventKind.RESULT
                and receipt.protocol_sha256 == observation.oos_protocol.content_sha256
                and observation.receipt_id
                == uuid5(NAMESPACE, "journal-receipt:" + receipt.content_sha256),
                "WALK_FORWARD_RECEIPT_MISMATCH",
            )
            if observation.oos_result is None:
                outcome, contamination, integrity, sample = _receipt_outcome(receipt)
                _require(
                    (contamination, integrity, sample)
                    == (
                        observation.contamination,
                        observation.integrity,
                        observation.sample_sufficiency,
                    )
                    and (
                        observation.state is FoldTerminalState.CANCELLED
                        and outcome is OOSOutcome.INCONCLUSIVE
                        or observation.state is FoldTerminalState.FAILED
                        and outcome is not OOSOutcome.OBSERVED
                        or observation.state is FoldTerminalState.INCONCLUSIVE
                        and outcome is OOSOutcome.INCONCLUSIVE
                    ),
                    "WALK_FORWARD_TERMINAL_STATE_RECEIPT_MISMATCH",
                )
            event_requests = {
                reference
                for event in self.journal.events
                if event.protocol_sha256 == observation.oos_protocol.content_sha256
                for reference in event.evidence
                if reference.artifact_type == "SPOT_OOS_REQUEST"
            }
            _require(
                event_requests <= set(observation.request_bindings),
                "WALK_FORWARD_REQUEST_PROVENANCE_MISMATCH",
            )
        result_ids = tuple(
            observation.oos_result.result_id
            for observation in self.observations
            if observation.oos_result is not None
        )
        _require(
            len(set(result_ids)) == len(result_ids),
            "DUPLICATE_WALK_FORWARD_OOS_RESULT",
        )
        for name in ("as_of", "created_at", "expires_at"):
            object.__setattr__(self, name, _utc(getattr(self, name)))
        request_pins = tuple(
            pin for row in self.protocol.spec.request_bindings_by_fold for pin in row
        )
        heldout_as_of = max(
            pin.result_as_of
            for pin in request_pins
            if pin.partition_role is PartitionPurpose.TEST
        )
        result_created = tuple(
            observation.oos_result.created_at
            for observation in self.observations
            if observation.oos_result is not None
        )
        result_expiries = tuple(
            observation.oos_result.expires_at
            for observation in self.observations
            if observation.oos_result is not None
        )
        _require(
            self.as_of <= self.created_at < self.expires_at
            and self.protocol.spec.frozen_at <= self.created_at,
            "INVALID_WALK_FORWARD_RESULT_TIME",
        )
        _require(
            self.as_of == heldout_as_of
            and self.created_at >= max(pin.created_at for pin in request_pins)
            and self.expires_at <= min(pin.expires_at for pin in request_pins)
            and (not result_created or self.created_at >= max(result_created))
            and (not result_expiries or self.expires_at <= min(result_expiries)),
            "WALK_FORWARD_RESULT_TIME_BOUNDARY_MISMATCH",
        )
        _digest(self.content_sha256)
        sha = canonical_sha256(_payload(self, {"result_id", "content_sha256"}))
        _require(
            self.content_sha256 == sha
            and self.result_id == uuid5(NAMESPACE, "result:" + sha),
            "WALK_FORWARD_RESULT_DIGEST_MISMATCH",
        )

    @classmethod
    def build(cls, **values: Any) -> WalkForwardResultV2:
        preimage = dict(
            values,
            method=METHOD,
            contract_id="C-029",
            schema_version="2",
            operating_mode=OperatingMode.BACKTEST,
            market_scope="SPOT",
            canonicalization_version=CANONICAL_JSON_VERSION,
        )
        sha = canonical_sha256(preimage)
        return cls(
            result_id=uuid5(NAMESPACE, "result:" + sha),
            content_sha256=sha,
            **values,
        )


def metric_from_report(report: Any, name: str, unit: str) -> WalkForwardMetricV2:
    """Copy one required #94 metric without converting unavailable values to zero."""
    metric = report.get(name)
    return WalkForwardMetricV2(
        name,
        metric.state,
        metric.reason,
        metric.metric,
        metric.metric.unit if metric.metric is not None else unit,
        metric.sample_count,
        metric.warnings,
    )


def unavailable_metric(name: str, unit: str, reason: str) -> WalkForwardMetricV2:
    return WalkForwardMetricV2(name, MetricState.UNAVAILABLE, reason, None, unit, 0, ())


def build_metric_aggregates(
    observations: tuple[WalkForwardFoldObservationV2, ...],
) -> tuple[WalkForwardMetricAggregateV2, ...]:
    return _aggregate(observations)


def build_consistency(
    observations: tuple[WalkForwardFoldObservationV2, ...],
) -> WalkForwardConsistencyV2:
    return _consistency(observations)
