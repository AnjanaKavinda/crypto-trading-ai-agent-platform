from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from typing import TypeVar, cast
from uuid import UUID

CONTRACT_SCHEMA_VERSION = "1"
_SHA256 = re.compile(r"[0-9a-f]{64}")
_T = TypeVar("_T")


class ValidationContractError(ValueError):
    """Raised when quantitative validation evidence is structurally invalid."""


class ValidationLifecycle(StrEnum):
    NOT_RUN = "NOT_RUN"
    RUNNING = "RUNNING"
    PASSED = "PASSED"
    FAILED = "FAILED"
    INCONCLUSIVE = "INCONCLUSIVE"
    STALE = "STALE"
    EXPIRED = "EXPIRED"


class StrategyEvidenceLevel(StrEnum):
    NOT_TESTED = "NOT_TESTED"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"
    FAILED_DATA_QUALITY = "FAILED_DATA_QUALITY"
    FAILED_SAMPLE_SIZE = "FAILED_SAMPLE_SIZE"
    OBSERVED_75_PLUS = "OBSERVED_75_PLUS"
    STATISTICALLY_SUPPORTED = "STATISTICALLY_SUPPORTED"
    OOS_SUPPORTED = "OOS_SUPPORTED"
    WALK_FORWARD_SUPPORTED = "WALK_FORWARD_SUPPORTED"
    ROBUST = "ROBUST"
    REJECTED = "REJECTED"
    DEGRADED = "DEGRADED"
    SUSPENDED = "SUSPENDED"


class CheckOutcome(StrEnum):
    PASSED = "PASSED"
    FAILED = "FAILED"
    INCONCLUSIVE = "INCONCLUSIVE"
    NOT_RUN = "NOT_RUN"


class PartitionPurpose(StrEnum):
    TRAIN = "TRAIN"
    VALIDATION = "VALIDATION"
    TEST = "TEST"
    OUT_OF_SAMPLE = "OUT_OF_SAMPLE"


class AssumptionCategory(StrEnum):
    FEE = "FEE"
    SPREAD = "SPREAD"
    SLIPPAGE = "SLIPPAGE"
    FUNDING = "FUNDING"
    LATENCY = "LATENCY"
    INTRABAR = "INTRABAR"


class RobustnessCheckType(StrEnum):
    COST = "COST"
    SLIPPAGE = "SLIPPAGE"
    LATENCY = "LATENCY"


class BiasCheckType(StrEnum):
    POINT_IN_TIME = "POINT_IN_TIME"
    LOOK_AHEAD = "LOOK_AHEAD"
    FEATURE_TARGET_LEAKAGE = "FEATURE_TARGET_LEAKAGE"
    NORMALIZATION_PARAMETER_LEAKAGE = "NORMALIZATION_PARAMETER_LEAKAGE"
    SURVIVORSHIP = "SURVIVORSHIP"
    SELECTION = "SELECTION"
    DATA_SNOOPING = "DATA_SNOOPING"
    MULTIPLE_TESTING = "MULTIPLE_TESTING"
    UNIVERSE_METHODOLOGY = "UNIVERSE_METHODOLOGY"


class ValidationGate(StrEnum):
    DATA_INTEGRITY = "DATA_INTEGRITY"
    POINT_IN_TIME_CORRECTNESS = "POINT_IN_TIME_CORRECTNESS"
    LOOK_AHEAD_BIAS = "LOOK_AHEAD_BIAS"
    DATA_LEAKAGE = "DATA_LEAKAGE"
    SUFFICIENT_SAMPLE = "SUFFICIENT_SAMPLE"
    EXECUTION_REALISM = "EXECUTION_REALISM"
    COST_REALISM = "COST_REALISM"
    IN_SAMPLE_PERFORMANCE = "IN_SAMPLE_PERFORMANCE"
    OUT_OF_SAMPLE_PERFORMANCE = "OUT_OF_SAMPLE_PERFORMANCE"
    WALK_FORWARD_STABILITY = "WALK_FORWARD_STABILITY"
    STATISTICAL_UNCERTAINTY = "STATISTICAL_UNCERTAINTY"
    PARAMETER_ROBUSTNESS = "PARAMETER_ROBUSTNESS"
    REGIME_ROBUSTNESS = "REGIME_ROBUSTNESS"
    ASSET_ROBUSTNESS = "ASSET_ROBUSTNESS"
    COST_SLIPPAGE_ROBUSTNESS = "COST_SLIPPAGE_ROBUSTNESS"
    OVERFITTING_ASSESSMENT = "OVERFITTING_ASSESSMENT"
    MULTIPLE_TESTING_ASSESSMENT = "MULTIPLE_TESTING_ASSESSMENT"
    FINAL_VALIDATION = "FINAL_VALIDATION"


class ValidationFailureCode(StrEnum):
    INSUFFICIENT_SAMPLE = "INSUFFICIENT_SAMPLE"
    LOOKAHEAD_BIAS = "LOOKAHEAD_BIAS"
    DATA_LEAKAGE = "DATA_LEAKAGE"
    SURVIVORSHIP_BIAS = "SURVIVORSHIP_BIAS"
    SELECTION_BIAS = "SELECTION_BIAS"
    UNREALISTIC_EXECUTION = "UNREALISTIC_EXECUTION"
    UNREALISTIC_COSTS = "UNREALISTIC_COSTS"
    NEGATIVE_EXPECTANCY = "NEGATIVE_EXPECTANCY"
    EXCESSIVE_DRAWDOWN = "EXCESSIVE_DRAWDOWN"
    POOR_OOS_PERFORMANCE = "POOR_OOS_PERFORMANCE"
    WALK_FORWARD_DEGRADATION = "WALK_FORWARD_DEGRADATION"
    PARAMETER_FRAGILITY = "PARAMETER_FRAGILITY"
    REGIME_FRAGILITY = "REGIME_FRAGILITY"
    ASSET_FRAGILITY = "ASSET_FRAGILITY"
    HIGH_DATA_SNOOPING_RISK = "HIGH_DATA_SNOOPING_RISK"
    MULTIPLE_TESTING_RISK = "MULTIPLE_TESTING_RISK"
    STATISTICALLY_UNCERTAIN = "STATISTICALLY_UNCERTAIN"
    WIN_RATE_BELOW_THRESHOLD = "WIN_RATE_BELOW_THRESHOLD"
    COST_SENSITIVE = "COST_SENSITIVE"
    SLIPPAGE_SENSITIVE = "SLIPPAGE_SENSITIVE"
    LATENCY_SENSITIVE = "LATENCY_SENSITIVE"
    STALE_EVIDENCE = "STALE_EVIDENCE"
    INCOMPATIBLE_VERSION = "INCOMPATIBLE_VERSION"


def _text(name: str, value: object) -> str:
    if not isinstance(value, str):
        raise ValidationContractError(f"{name} must be a string.")
    if not value.strip():
        raise ValidationContractError(f"{name} must not be blank.")
    if value != value.strip():
        raise ValidationContractError(
            f"{name} must not contain surrounding whitespace."
        )
    return value


def _uuid(name: str, value: object) -> UUID:
    if not isinstance(value, UUID):
        raise ValidationContractError(f"{name} must be a UUID.")
    return value


def _time(name: str, value: object) -> datetime:
    if not isinstance(value, datetime):
        raise ValidationContractError(f"{name} must be a datetime.")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValidationContractError(f"{name} must be timezone-aware.")
    return value.astimezone(UTC)


def _decimal(name: str, value: object) -> Decimal:
    if (
        not isinstance(value, Decimal)
        or isinstance(value, bool)
        or not value.is_finite()
    ):
        raise ValidationContractError(f"{name} must be a finite Decimal.")
    return value


def _ratio(name: str, value: object) -> Decimal:
    result = _decimal(name, value)
    if not Decimal("0") <= result <= Decimal("1"):
        raise ValidationContractError(f"{name} must be between 0 and 1.")
    return result


def _tuple(name: str, value: object, *, empty: bool = True) -> tuple[object, ...]:
    if not isinstance(value, tuple):
        raise ValidationContractError(f"{name} must be a tuple.")
    if not empty and not value:
        raise ValidationContractError(f"{name} must not be empty.")
    return value


def _typed_tuple(
    name: str, value: object, kind: type[_T], *, empty: bool = True
) -> tuple[_T, ...]:
    values = _tuple(name, value, empty=empty)
    if not all(isinstance(item, kind) for item in values):
        raise ValidationContractError(f"{name} contains an invalid item type.")
    return cast(tuple[_T, ...], values)


def _unique(name: str, values: tuple[object, ...]) -> None:
    try:
        if len(set(values)) != len(values):
            raise ValidationContractError(f"{name} must not contain duplicates.")
    except TypeError as exc:
        raise ValidationContractError(f"{name} items must be hashable.") from exc


def _text_tuple(name: str, value: object, *, empty: bool = True) -> tuple[str, ...]:
    values = _tuple(name, value, empty=empty)
    result = tuple(_text(f"{name}[{i}]", item) for i, item in enumerate(values))
    _unique(name, result)
    return result


def _enum_tuple(
    name: str, value: object, kind: type[_T], *, empty: bool = True
) -> tuple[_T, ...]:
    values = _typed_tuple(name, value, kind, empty=empty)
    _unique(name, values)
    return values


def _ordered(
    first_name: str, first: datetime, second_name: str, second: datetime
) -> None:
    if first > second:
        raise ValidationContractError(f"{first_name} must not be after {second_name}.")


def _digest(name: str, value: object) -> str:
    result = _text(name, value)
    if _SHA256.fullmatch(result) is None:
        raise ValidationContractError(f"{name} must be a lowercase SHA-256 digest.")
    return result


def _positive_int(name: str, value: object, *, allow_zero: bool = False) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValidationContractError(f"{name} must be an integer.")
    if value < 0 or (not allow_zero and value == 0):
        qualifier = "non-negative" if allow_zero else "positive"
        raise ValidationContractError(f"{name} must be {qualifier}.")
    return value


@dataclass(frozen=True, slots=True)
class ArtifactReference:
    artifact_type: str
    artifact_id: UUID
    version: str
    content_sha256: str

    def __post_init__(self) -> None:
        _text("artifact_type", self.artifact_type)
        _uuid("artifact_id", self.artifact_id)
        _text("version", self.version)
        _digest("content_sha256", self.content_sha256)


@dataclass(frozen=True, slots=True)
class ResultReference:
    contract_id: str
    result_id: UUID
    strategy_version_id: UUID
    lifecycle: ValidationLifecycle
    valid_until: datetime

    def __post_init__(self) -> None:
        contract = _text("contract_id", self.contract_id)
        if re.fullmatch(r"C-[0-9]{3}", contract) is None:
            raise ValidationContractError("contract_id must match C-###.")
        _uuid("result_id", self.result_id)
        _uuid("strategy_version_id", self.strategy_version_id)
        if not isinstance(self.lifecycle, ValidationLifecycle):
            raise ValidationContractError("lifecycle must be a ValidationLifecycle.")
        object.__setattr__(self, "valid_until", _time("valid_until", self.valid_until))


@dataclass(frozen=True, slots=True)
class DataPartition:
    partition_id: UUID
    purpose: PartitionPurpose
    start: datetime
    end: datetime
    point_in_time_cutoff: datetime
    used_for_optimization: bool

    def __post_init__(self) -> None:
        _uuid("partition_id", self.partition_id)
        if not isinstance(self.purpose, PartitionPurpose):
            raise ValidationContractError("purpose must be a PartitionPurpose.")
        start = _time("start", self.start)
        end = _time("end", self.end)
        cutoff = _time("point_in_time_cutoff", self.point_in_time_cutoff)
        _ordered("start", start, "end", end)
        _ordered("end", end, "point_in_time_cutoff", cutoff)
        if not isinstance(self.used_for_optimization, bool):
            raise ValidationContractError("used_for_optimization must be a bool.")
        if (
            self.purpose in {PartitionPurpose.TEST, PartitionPurpose.OUT_OF_SAMPLE}
            and self.used_for_optimization
        ):
            raise ValidationContractError(
                "test/OOS partition cannot be used for optimization."
            )
        object.__setattr__(self, "start", start)
        object.__setattr__(self, "end", end)
        object.__setattr__(self, "point_in_time_cutoff", cutoff)


@dataclass(frozen=True, slots=True)
class ResearchAssumption:
    category: AssumptionCategory
    model: ArtifactReference
    value: Decimal
    unit: str
    justification: str

    def __post_init__(self) -> None:
        if not isinstance(self.category, AssumptionCategory):
            raise ValidationContractError("category must be an AssumptionCategory.")
        if not isinstance(self.model, ArtifactReference):
            raise ValidationContractError("model must be an ArtifactReference.")
        value = _decimal("value", self.value)
        if value < 0:
            raise ValidationContractError("assumption value must be non-negative.")
        _text("unit", self.unit)
        _text("justification", self.justification)


@dataclass(frozen=True, slots=True)
class MetricValue:
    name: str
    value: Decimal
    unit: str
    methodology_version: str

    def __post_init__(self) -> None:
        _text("name", self.name)
        _decimal("value", self.value)
        _text("unit", self.unit)
        _text("methodology_version", self.methodology_version)


@dataclass(frozen=True, slots=True)
class StatisticalInterval:
    name: str
    method: str
    confidence_level: Decimal
    lower: Decimal
    point: Decimal
    upper: Decimal
    sample_size: int

    def __post_init__(self) -> None:
        _text("name", self.name)
        _text("method", self.method)
        _ratio("confidence_level", self.confidence_level)
        lower = _decimal("lower", self.lower)
        point = _decimal("point", self.point)
        upper = _decimal("upper", self.upper)
        if not lower <= point <= upper:
            raise ValidationContractError(
                "interval must satisfy lower <= point <= upper."
            )
        _positive_int("sample_size", self.sample_size)


@dataclass(frozen=True, slots=True)
class ReproducibilityContext:
    strategy: ArtifactReference
    strategy_version: ArtifactReference
    parameter_set: ArtifactReference
    configuration: ArtifactReference
    dataset: ArtifactReference
    feature_definitions: tuple[ArtifactReference, ...]
    execution_model: ArtifactReference
    validation_methodology: ArtifactReference
    statistical_methodology: ArtifactReference
    software: ArtifactReference
    partitions: tuple[DataPartition, ...]
    assumptions: tuple[ResearchAssumption, ...]
    asset_universe: tuple[str, ...]
    instrument_ids: tuple[str, ...]
    timeframe: str
    strategies_tested: int
    hypotheses_tested: int
    parameter_combinations_tested: int
    correlation_id: str

    def __post_init__(self) -> None:
        for name in (
            "strategy",
            "strategy_version",
            "parameter_set",
            "configuration",
            "dataset",
            "execution_model",
            "validation_methodology",
            "statistical_methodology",
            "software",
        ):
            if not isinstance(getattr(self, name), ArtifactReference):
                raise ValidationContractError(f"{name} must be an ArtifactReference.")
        for name, contract_id in (
            ("strategy", "C-020"),
            ("strategy_version", "C-021"),
            ("dataset", "C-092"),
        ):
            if getattr(self, name).artifact_type != contract_id:
                raise ValidationContractError(f"{name} must reference {contract_id}.")
        features = _typed_tuple(
            "feature_definitions",
            self.feature_definitions,
            ArtifactReference,
            empty=False,
        )
        _unique("feature_definitions", features)
        partitions = _typed_tuple(
            "partitions", self.partitions, DataPartition, empty=False
        )
        _unique("partition identities", tuple(item.partition_id for item in partitions))
        ordered = sorted(partitions, key=lambda item: item.start)
        for previous, current in zip(ordered, ordered[1:], strict=False):
            if previous.end > current.start:
                raise ValidationContractError("data partitions must not overlap.")
        assumptions = _typed_tuple(
            "assumptions", self.assumptions, ResearchAssumption, empty=False
        )
        categories = tuple(item.category for item in assumptions)
        _unique("assumption categories", categories)
        missing = set(AssumptionCategory) - set(categories)
        if missing:
            raise ValidationContractError(
                "all execution/cost assumptions are required."
            )
        _text_tuple("asset_universe", self.asset_universe, empty=False)
        _text_tuple("instrument_ids", self.instrument_ids, empty=False)
        _text("timeframe", self.timeframe)
        for name in (
            "strategies_tested",
            "hypotheses_tested",
            "parameter_combinations_tested",
        ):
            _positive_int(name, getattr(self, name))
        _text("correlation_id", self.correlation_id)


@dataclass(frozen=True, slots=True)
class _ResultBase:
    result_id: UUID
    strategy_version_id: UUID
    lifecycle: ValidationLifecycle
    created_at: datetime
    as_of: datetime
    valid_until: datetime
    warnings: tuple[str, ...]
    failures: tuple[ValidationFailureCode, ...]
    schema_version: str = field(default=CONTRACT_SCHEMA_VERSION, init=False)

    def __post_init__(self) -> None:
        _uuid("result_id", self.result_id)
        _uuid("strategy_version_id", self.strategy_version_id)
        if not isinstance(self.lifecycle, ValidationLifecycle):
            raise ValidationContractError("lifecycle must be a ValidationLifecycle.")
        created = _time("created_at", self.created_at)
        as_of = _time("as_of", self.as_of)
        valid = _time("valid_until", self.valid_until)
        _ordered("as_of", as_of, "created_at", created)
        _ordered("created_at", created, "valid_until", valid)
        _text_tuple("warnings", self.warnings)
        failures = _enum_tuple("failures", self.failures, ValidationFailureCode)
        if self.lifecycle is ValidationLifecycle.PASSED and failures:
            raise ValidationContractError("PASSED result cannot contain failure codes.")
        if (
            self.lifecycle
            in {
                ValidationLifecycle.FAILED,
                ValidationLifecycle.INCONCLUSIVE,
                ValidationLifecycle.STALE,
                ValidationLifecycle.EXPIRED,
            }
            and not failures
        ):
            raise ValidationContractError(
                "non-authoritative result requires failure codes."
            )
        object.__setattr__(self, "created_at", created)
        object.__setattr__(self, "as_of", as_of)
        object.__setattr__(self, "valid_until", valid)


@dataclass(frozen=True, slots=True)
class BacktestResult(_ResultBase):
    context: ReproducibilityContext
    metrics: tuple[MetricValue, ...]
    intervals: tuple[StatisticalInterval, ...]
    simulated_trade_count: int
    data_integrity: CheckOutcome
    point_in_time_correct: CheckOutcome
    content_sha256: str
    contract_id: str = field(default="C-027", init=False)

    def __post_init__(self) -> None:
        _ResultBase.__post_init__(self)
        if not isinstance(self.context, ReproducibilityContext):
            raise ValidationContractError("context must be a ReproducibilityContext.")
        metrics = _typed_tuple("metrics", self.metrics, MetricValue, empty=False)
        _unique("metric names", tuple(item.name for item in metrics))
        intervals = _typed_tuple("intervals", self.intervals, StatisticalInterval)
        _unique("interval names", tuple(item.name for item in intervals))
        _positive_int(
            "simulated_trade_count", self.simulated_trade_count, allow_zero=True
        )
        for name in ("data_integrity", "point_in_time_correct"):
            if not isinstance(getattr(self, name), CheckOutcome):
                raise ValidationContractError(f"{name} must be a CheckOutcome.")
        if self.lifecycle is ValidationLifecycle.PASSED and (
            self.data_integrity is not CheckOutcome.PASSED
            or self.point_in_time_correct is not CheckOutcome.PASSED
        ):
            raise ValidationContractError(
                "PASSED backtest requires data and point-in-time checks."
            )
        _digest("content_sha256", self.content_sha256)


@dataclass(frozen=True, slots=True)
class OOSResult(_ResultBase):
    backtest_result_id: UUID
    dataset_version_id: UUID
    partition: DataPartition
    metrics: tuple[MetricValue, ...]
    intervals: tuple[StatisticalInterval, ...]
    sample_size: int
    contract_id: str = field(default="C-071", init=False)

    def __post_init__(self) -> None:
        _ResultBase.__post_init__(self)
        _uuid("backtest_result_id", self.backtest_result_id)
        _uuid("dataset_version_id", self.dataset_version_id)
        if not isinstance(self.partition, DataPartition):
            raise ValidationContractError("partition must be a DataPartition.")
        if (
            self.partition.purpose is not PartitionPurpose.OUT_OF_SAMPLE
            or self.partition.used_for_optimization
        ):
            raise ValidationContractError(
                "OOS result requires a separated non-optimization partition."
            )
        _typed_tuple("metrics", self.metrics, MetricValue, empty=False)
        _typed_tuple("intervals", self.intervals, StatisticalInterval)
        _positive_int("sample_size", self.sample_size)


@dataclass(frozen=True, slots=True)
class WalkForwardFold:
    fold_id: UUID
    training_partition: DataPartition
    validation_partition: DataPartition
    parameter_set: ArtifactReference
    metrics: tuple[MetricValue, ...]
    sample_size: int
    outcome: CheckOutcome

    def __post_init__(self) -> None:
        _uuid("fold_id", self.fold_id)
        if (
            not isinstance(self.training_partition, DataPartition)
            or self.training_partition.purpose is not PartitionPurpose.TRAIN
        ):
            raise ValidationContractError("training_partition must be TRAIN.")
        if (
            not isinstance(self.validation_partition, DataPartition)
            or self.validation_partition.purpose is not PartitionPurpose.VALIDATION
        ):
            raise ValidationContractError("validation_partition must be VALIDATION.")
        _ordered(
            "training end",
            self.training_partition.end,
            "validation start",
            self.validation_partition.start,
        )
        if not isinstance(self.parameter_set, ArtifactReference):
            raise ValidationContractError("parameter_set must be an ArtifactReference.")
        _typed_tuple("metrics", self.metrics, MetricValue, empty=False)
        _positive_int("sample_size", self.sample_size)
        if not isinstance(self.outcome, CheckOutcome):
            raise ValidationContractError("outcome must be a CheckOutcome.")


@dataclass(frozen=True, slots=True)
class WalkForwardResult(_ResultBase):
    backtest_result_id: UUID
    folds: tuple[WalkForwardFold, ...]
    aggregate_metrics: tuple[MetricValue, ...]
    contract_id: str = field(default="C-029", init=False)

    def __post_init__(self) -> None:
        _ResultBase.__post_init__(self)
        _uuid("backtest_result_id", self.backtest_result_id)
        folds = _typed_tuple("folds", self.folds, WalkForwardFold, empty=False)
        _unique("fold identities", tuple(item.fold_id for item in folds))
        ordered = sorted(folds, key=lambda item: item.validation_partition.start)
        for previous, current in zip(ordered, ordered[1:], strict=False):
            if previous.validation_partition.end > current.validation_partition.start:
                raise ValidationContractError(
                    "walk-forward validation periods overlap."
                )
        _typed_tuple(
            "aggregate_metrics", self.aggregate_metrics, MetricValue, empty=False
        )


@dataclass(frozen=True, slots=True)
class DistributionPoint:
    quantile: Decimal
    value: Decimal

    def __post_init__(self) -> None:
        _ratio("quantile", self.quantile)
        _decimal("value", self.value)


@dataclass(frozen=True, slots=True)
class MonteCarloResult(_ResultBase):
    input_result_id: UUID
    technique: str
    iterations: int
    seed: int
    seed_policy: str
    sampling_assumptions: tuple[str, ...]
    distribution: tuple[DistributionPoint, ...]
    methodology: ArtifactReference
    contract_id: str = field(default="C-072", init=False)

    def __post_init__(self) -> None:
        _ResultBase.__post_init__(self)
        _uuid("input_result_id", self.input_result_id)
        _text("technique", self.technique)
        _positive_int("iterations", self.iterations)
        if not isinstance(self.seed, int) or isinstance(self.seed, bool):
            raise ValidationContractError("seed must be an integer.")
        _text("seed_policy", self.seed_policy)
        _text_tuple("sampling_assumptions", self.sampling_assumptions, empty=False)
        distribution = _typed_tuple(
            "distribution", self.distribution, DistributionPoint, empty=False
        )
        _unique("distribution quantiles", tuple(item.quantile for item in distribution))
        if not isinstance(self.methodology, ArtifactReference):
            raise ValidationContractError("methodology must be an ArtifactReference.")


@dataclass(frozen=True, slots=True)
class SensitivityPoint:
    parameter: str
    value: Decimal
    metric: MetricValue
    is_baseline: bool

    def __post_init__(self) -> None:
        _text("parameter", self.parameter)
        _decimal("value", self.value)
        if not isinstance(self.metric, MetricValue):
            raise ValidationContractError("metric must be a MetricValue.")
        if not isinstance(self.is_baseline, bool):
            raise ValidationContractError("is_baseline must be a bool.")


@dataclass(frozen=True, slots=True)
class SensitivityResult(_ResultBase):
    input_result_id: UUID
    points: tuple[SensitivityPoint, ...]
    degradation_boundaries: tuple[str, ...]
    contract_id: str = field(default="C-073", init=False)

    def __post_init__(self) -> None:
        _ResultBase.__post_init__(self)
        _uuid("input_result_id", self.input_result_id)
        points = _typed_tuple("points", self.points, SensitivityPoint, empty=False)
        _unique(
            "sensitivity points", tuple((item.parameter, item.value) for item in points)
        )
        if sum(item.is_baseline for item in points) != 1:
            raise ValidationContractError(
                "sensitivity requires exactly one baseline point."
            )
        if len(points) < 2:
            raise ValidationContractError(
                "sensitivity requires surrounding parameter evidence."
            )
        _text_tuple("degradation_boundaries", self.degradation_boundaries, empty=False)


@dataclass(frozen=True, slots=True)
class RegimeSlice:
    regime: str
    sample_size: int
    metrics: tuple[MetricValue, ...]
    outcome: CheckOutcome

    def __post_init__(self) -> None:
        _text("regime", self.regime)
        _positive_int("sample_size", self.sample_size, allow_zero=True)
        _typed_tuple("metrics", self.metrics, MetricValue)
        if not isinstance(self.outcome, CheckOutcome):
            raise ValidationContractError("outcome must be a CheckOutcome.")
        if self.outcome is CheckOutcome.PASSED and self.sample_size == 0:
            raise ValidationContractError("passed regime requires observations.")


@dataclass(frozen=True, slots=True)
class RegimeValidationResult(_ResultBase):
    input_result_id: UUID
    taxonomy: ArtifactReference
    required_regimes: tuple[str, ...]
    slices: tuple[RegimeSlice, ...]
    contract_id: str = field(default="C-074", init=False)

    def __post_init__(self) -> None:
        _ResultBase.__post_init__(self)
        _uuid("input_result_id", self.input_result_id)
        if not isinstance(self.taxonomy, ArtifactReference):
            raise ValidationContractError("taxonomy must be an ArtifactReference.")
        required = _text_tuple("required_regimes", self.required_regimes, empty=False)
        slices = _typed_tuple("slices", self.slices, RegimeSlice, empty=False)
        _unique("regime slices", tuple(item.regime for item in slices))
        available = {item.regime for item in slices}
        if not set(required).issubset(available):
            raise ValidationContractError("required regime evidence is missing.")
        if self.lifecycle is ValidationLifecycle.PASSED and any(
            item.regime in required and item.outcome is not CheckOutcome.PASSED
            for item in slices
        ):
            raise ValidationContractError(
                "PASSED regime result cannot hide failed required regimes."
            )


@dataclass(frozen=True, slots=True)
class BiasCheck:
    check_type: BiasCheckType
    outcome: CheckOutcome
    evidence_references: tuple[str, ...]
    reason: str

    def __post_init__(self) -> None:
        if not isinstance(self.check_type, BiasCheckType):
            raise ValidationContractError("check_type must be a BiasCheckType.")
        if not isinstance(self.outcome, CheckOutcome):
            raise ValidationContractError("outcome must be a CheckOutcome.")
        _text_tuple("evidence_references", self.evidence_references, empty=False)
        _text("reason", self.reason)


@dataclass(frozen=True, slots=True)
class BiasCheckReport(_ResultBase):
    input_result_id: UUID
    checks: tuple[BiasCheck, ...]
    contract_id: str = field(default="C-094", init=False)

    def __post_init__(self) -> None:
        _ResultBase.__post_init__(self)
        _uuid("input_result_id", self.input_result_id)
        checks = _typed_tuple("checks", self.checks, BiasCheck, empty=False)
        types = tuple(item.check_type for item in checks)
        _unique("bias check types", types)
        if set(types) != set(BiasCheckType):
            raise ValidationContractError("bias report requires every critical check.")
        if self.lifecycle is ValidationLifecycle.PASSED and any(
            item.outcome is not CheckOutcome.PASSED for item in checks
        ):
            raise ValidationContractError(
                "PASSED bias report requires all checks to pass."
            )


@dataclass(frozen=True, slots=True)
class RobustnessCheck:
    check_type: RobustnessCheckType
    outcome: CheckOutcome
    evidence_reference: str

    def __post_init__(self) -> None:
        if not isinstance(self.check_type, RobustnessCheckType):
            raise ValidationContractError("check_type must be a RobustnessCheckType.")
        if not isinstance(self.outcome, CheckOutcome):
            raise ValidationContractError("outcome must be a CheckOutcome.")
        _text("evidence_reference", self.evidence_reference)


@dataclass(frozen=True, slots=True)
class RobustnessResult(_ResultBase):
    monte_carlo: ResultReference
    sensitivity: ResultReference
    regime_validation: ResultReference
    cost_slippage_latency_checks: tuple[RobustnessCheck, ...]
    worst_case_metrics: tuple[MetricValue, ...]
    evidence_level: StrategyEvidenceLevel
    contract_id: str = field(default="C-030", init=False)

    def __post_init__(self) -> None:
        _ResultBase.__post_init__(self)
        expected = (
            ("monte_carlo", "C-072"),
            ("sensitivity", "C-073"),
            ("regime_validation", "C-074"),
        )
        for name, contract_id in expected:
            ref = getattr(self, name)
            if not isinstance(ref, ResultReference) or ref.contract_id != contract_id:
                raise ValidationContractError(f"{name} must reference {contract_id}.")
            if ref.strategy_version_id != self.strategy_version_id:
                raise ValidationContractError(
                    "robustness component strategy version mismatch."
                )
        checks = _typed_tuple(
            "cost_slippage_latency_checks",
            self.cost_slippage_latency_checks,
            RobustnessCheck,
            empty=False,
        )
        check_types = tuple(item.check_type for item in checks)
        _unique("robustness check types", check_types)
        if set(check_types) != set(RobustnessCheckType):
            raise ValidationContractError(
                "cost, slippage and latency checks are required."
            )
        _typed_tuple(
            "worst_case_metrics", self.worst_case_metrics, MetricValue, empty=False
        )
        if not isinstance(self.evidence_level, StrategyEvidenceLevel):
            raise ValidationContractError(
                "evidence_level must be a StrategyEvidenceLevel."
            )
        if self.evidence_level is StrategyEvidenceLevel.ROBUST:
            refs = (self.monte_carlo, self.sensitivity, self.regime_validation)
            if (
                self.lifecycle is not ValidationLifecycle.PASSED
                or any(ref.lifecycle is not ValidationLifecycle.PASSED for ref in refs)
                or any(item.outcome is not CheckOutcome.PASSED for item in checks)
            ):
                raise ValidationContractError(
                    "ROBUST requires complete passed component evidence."
                )


@dataclass(frozen=True, slots=True)
class CalibrationBin:
    lower_bound: Decimal
    upper_bound: Decimal
    predicted_probability: Decimal
    observed_frequency: Decimal
    sample_size: int

    def __post_init__(self) -> None:
        lower = _ratio("lower_bound", self.lower_bound)
        upper = _ratio("upper_bound", self.upper_bound)
        _ordered_decimal("lower_bound", lower, "upper_bound", upper)
        _ratio("predicted_probability", self.predicted_probability)
        _ratio("observed_frequency", self.observed_frequency)
        _positive_int("sample_size", self.sample_size)


def _ordered_decimal(
    first_name: str, first: Decimal, second_name: str, second: Decimal
) -> None:
    if first > second:
        raise ValidationContractError(
            f"{first_name} must not be greater than {second_name}."
        )


@dataclass(frozen=True, slots=True)
class CalibrationResult(_ResultBase):
    model: ArtifactReference
    target_definition: str
    prediction_window: str
    observation_window: str
    calibration_method: ArtifactReference
    sample_size: int
    bins: tuple[CalibrationBin, ...]
    metrics: tuple[MetricValue, ...]
    intervals: tuple[StatisticalInterval, ...]
    contract_id: str = field(default="C-031", init=False)

    def __post_init__(self) -> None:
        _ResultBase.__post_init__(self)
        if not isinstance(self.model, ArtifactReference) or not isinstance(
            self.calibration_method, ArtifactReference
        ):
            raise ValidationContractError(
                "model/calibration_method must be ArtifactReference objects."
            )
        for name in ("target_definition", "prediction_window", "observation_window"):
            _text(name, getattr(self, name))
        _positive_int("sample_size", self.sample_size)
        bins = _typed_tuple("bins", self.bins, CalibrationBin, empty=False)
        _unique(
            "calibration bins",
            tuple((item.lower_bound, item.upper_bound) for item in bins),
        )
        _typed_tuple("metrics", self.metrics, MetricValue, empty=False)
        _typed_tuple("intervals", self.intervals, StatisticalInterval)


@dataclass(frozen=True, slots=True)
class ValidationGateResult:
    gate: ValidationGate
    outcome: CheckOutcome
    evidence_references: tuple[str, ...]
    reason: str

    def __post_init__(self) -> None:
        if not isinstance(self.gate, ValidationGate):
            raise ValidationContractError("gate must be a ValidationGate.")
        if not isinstance(self.outcome, CheckOutcome):
            raise ValidationContractError("outcome must be a CheckOutcome.")
        _text_tuple("evidence_references", self.evidence_references, empty=False)
        _text("reason", self.reason)


@dataclass(frozen=True, slots=True)
class ValidationResult(_ResultBase):
    signal_candidate_id: UUID
    evidence_package_id: UUID
    backtest: ResultReference
    oos: ResultReference
    walk_forward: ResultReference
    robustness: ResultReference
    bias_report: ResultReference
    calibration: ResultReference | None
    evidence_level: StrategyEvidenceLevel
    gates: tuple[ValidationGateResult, ...]
    metrics: tuple[MetricValue, ...]
    intervals: tuple[StatisticalInterval, ...]
    invalidation_triggers: tuple[str, ...]
    content_sha256: str
    contract_id: str = field(default="C-028", init=False)

    def __post_init__(self) -> None:
        _ResultBase.__post_init__(self)
        _uuid("signal_candidate_id", self.signal_candidate_id)
        _uuid("evidence_package_id", self.evidence_package_id)
        required = (
            ("backtest", "C-027"),
            ("oos", "C-071"),
            ("walk_forward", "C-029"),
            ("robustness", "C-030"),
            ("bias_report", "C-094"),
        )
        references: list[ResultReference] = []
        for name, contract_id in required:
            ref = getattr(self, name)
            if not isinstance(ref, ResultReference) or ref.contract_id != contract_id:
                raise ValidationContractError(f"{name} must reference {contract_id}.")
            if ref.strategy_version_id != self.strategy_version_id:
                raise ValidationContractError(
                    "validation component strategy version mismatch."
                )
            references.append(ref)
        if self.calibration is not None:
            if (
                not isinstance(self.calibration, ResultReference)
                or self.calibration.contract_id != "C-031"
            ):
                raise ValidationContractError("calibration must reference C-031.")
            if self.calibration.strategy_version_id != self.strategy_version_id:
                raise ValidationContractError("calibration strategy version mismatch.")
            references.append(self.calibration)
        if not isinstance(self.evidence_level, StrategyEvidenceLevel):
            raise ValidationContractError(
                "evidence_level must be a StrategyEvidenceLevel."
            )
        gates = _typed_tuple("gates", self.gates, ValidationGateResult, empty=False)
        gate_types = tuple(item.gate for item in gates)
        _unique("validation gates", gate_types)
        if set(gate_types) != set(ValidationGate):
            raise ValidationContractError("ValidationResult requires all 18 gates.")
        _typed_tuple("metrics", self.metrics, MetricValue, empty=False)
        _typed_tuple("intervals", self.intervals, StatisticalInterval, empty=False)
        _text_tuple("invalidation_triggers", self.invalidation_triggers, empty=False)
        _digest("content_sha256", self.content_sha256)
        if self.lifecycle is ValidationLifecycle.PASSED:
            if any(
                ref.lifecycle is not ValidationLifecycle.PASSED for ref in references
            ):
                raise ValidationContractError(
                    "PASSED validation requires passed components."
                )
            if any(ref.valid_until < self.valid_until for ref in references):
                raise ValidationContractError(
                    "validation component expires before aggregate result."
                )
            if any(gate.outcome is not CheckOutcome.PASSED for gate in gates):
                raise ValidationContractError(
                    "PASSED validation requires all gates to pass."
                )
            if self.evidence_level in {
                StrategyEvidenceLevel.NOT_TESTED,
                StrategyEvidenceLevel.INSUFFICIENT_DATA,
                StrategyEvidenceLevel.FAILED_DATA_QUALITY,
                StrategyEvidenceLevel.FAILED_SAMPLE_SIZE,
                StrategyEvidenceLevel.REJECTED,
                StrategyEvidenceLevel.DEGRADED,
                StrategyEvidenceLevel.SUSPENDED,
            }:
                raise ValidationContractError(
                    "PASSED lifecycle contradicts evidence level."
                )


__all__ = [
    "CONTRACT_SCHEMA_VERSION",
    "ArtifactReference",
    "AssumptionCategory",
    "BacktestResult",
    "BiasCheck",
    "BiasCheckReport",
    "BiasCheckType",
    "CalibrationBin",
    "CalibrationResult",
    "CheckOutcome",
    "DataPartition",
    "DistributionPoint",
    "MetricValue",
    "MonteCarloResult",
    "OOSResult",
    "PartitionPurpose",
    "RegimeSlice",
    "RegimeValidationResult",
    "ReproducibilityContext",
    "ResearchAssumption",
    "ResultReference",
    "RobustnessCheck",
    "RobustnessCheckType",
    "RobustnessResult",
    "SensitivityPoint",
    "SensitivityResult",
    "StatisticalInterval",
    "StrategyEvidenceLevel",
    "ValidationContractError",
    "ValidationFailureCode",
    "ValidationGate",
    "ValidationGateResult",
    "ValidationLifecycle",
    "ValidationResult",
    "WalkForwardFold",
    "WalkForwardResult",
]
