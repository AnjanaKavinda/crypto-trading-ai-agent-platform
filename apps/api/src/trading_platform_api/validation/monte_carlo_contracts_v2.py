"""Observation-only C-072 schema 2 for Spot block-bootstrap evidence."""

from dataclasses import dataclass, field, fields
from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from uuid import NAMESPACE_URL, UUID, uuid5

from trading_platform_api.contracts.serialization import canonical_sha256
from trading_platform_api.validation.contracts import ValidationContractError
from trading_platform_api.validation.contracts_v2 import ValidationArtifactReferenceV2

METHOD = "spot-moving-block-bootstrap"
METHOD_VERSION = "1"
IDENTITY_METHOD = "spot-monte-carlo-identity-v1"
ITERATIONS = 10_000
MAX_RECORDED_SOURCE_INTERVALS = 100_000
QUANTILES = (Decimal("0.025"), Decimal("0.5"), Decimal("0.975"))
_EXPECTED_METRICS = (
    ("terminal_compounded_return", "ratio"),
    ("maximum_fractional_drawdown", "ratio"),
    ("longest_negative_bar_streak", "bars"),
)
ASSUMPTIONS = (
    "NON_CIRCULAR_CONTIGUOUS_BLOCKS_SAMPLED_WITH_REPLACEMENT",
    "DEPENDENCE_PRESERVED_ONLY_WITHIN_SAMPLED_BLOCKS",
    "OBSERVED_PATH_CONDITIONAL_NOT_FUTURE_PERFORMANCE",
    "NO_TRADE_SHUFFLE_NO_FOLD_POOLING_NO_PARAMETRIC_FIT",
    "NET_PER_TIMEFRAME_BAR_EQUITY_RETURNS",
)
WARNINGS = (
    "2.5_TO_97.5_PERCENTILE_CONDITIONAL_95_BOOTSTRAP_RANGE",
    "PERCENTILE_RANGE_IS_CONDITIONAL_NOT_A_FUTURE_GUARANTEE",
    "LONGER_DEPENDENCE_AND_REGIME_CHANGES_ARE_NOT_MODELED",
)
MONTE_CARLO_NAMESPACE_V2 = uuid5(
    NAMESPACE_URL, "trading-platform:C-072:2:spot-monte-carlo-identity-v1"
)


class MonteCarloOutcomeV2(StrEnum):
    OBSERVED = "OBSERVED"
    INCONCLUSIVE = "INCONCLUSIVE"
    FAILED = "FAILED"


def _text(name: str, value: object) -> None:
    if (
        type(value) is not str
        or not value.strip()
        or value != value.strip()
        or len(value.encode("utf-8")) > 256
    ):
        raise ValidationContractError(f"{name} must be a bounded trimmed string.")


def _digest(name: str, value: object) -> None:
    if (
        type(value) is not str
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ValidationContractError(f"{name} must be lowercase SHA-256.")


def _time(name: str, value: object) -> datetime:
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise ValidationContractError(f"{name} must be timezone-aware.")
    return value.astimezone(UTC)


def _decimal(name: str, value: object) -> None:
    if type(value) is not Decimal or not value.is_finite():
        raise ValidationContractError(f"{name} must be a finite Decimal.")


@dataclass(frozen=True, slots=True)
class MonteCarloPolicyV2:
    timeframe: str
    block_length: int
    path_horizon: int
    prng: str = field(default="splitmix64-v1", init=False)
    index_mapping: str = field(default="uint64-modulo-valid-start-v1", init=False)
    quantile_method: str = field(default="nearest-rank-v1", init=False)
    method: str = field(default=METHOD, init=False)
    method_version: str = field(default=METHOD_VERSION, init=False)
    iterations: int = field(default=ITERATIONS, init=False)

    def __post_init__(self) -> None:
        _text("timeframe", self.timeframe)
        if (
            type(self.block_length) is not int
            or not 0 <= self.block_length <= 2_000
            or type(self.path_horizon) is not int
            or not 0 <= self.path_horizon <= MAX_RECORDED_SOURCE_INTERVALS
        ):
            raise ValidationContractError("Bootstrap policy bounds are invalid.")


@dataclass(frozen=True, slots=True)
class MetricQuantileV2:
    quantile: Decimal
    value: Decimal

    def __post_init__(self) -> None:
        _decimal("quantile", self.quantile)
        _decimal("value", self.value)
        if self.quantile not in QUANTILES:
            raise ValidationContractError("Unsupported bootstrap quantile.")


@dataclass(frozen=True, slots=True)
class MetricDistributionV2:
    name: str
    unit: str
    observed_value: Decimal
    quantiles: tuple[MetricQuantileV2, ...]

    def __post_init__(self) -> None:
        _text("metric name", self.name)
        _text("metric unit", self.unit)
        _decimal("observed_value", self.observed_value)
        if (
            type(self.quantiles) is not tuple
            or len(self.quantiles) != len(QUANTILES)
            or any(type(item) is not MetricQuantileV2 for item in self.quantiles)
            or tuple(item.quantile for item in self.quantiles) != QUANTILES
        ):
            raise ValidationContractError(
                "Each metric requires ordered 2.5%, 50%, and 97.5% quantiles."
            )
        if self.name == "longest_negative_bar_streak":
            values = (self.observed_value, *(item.value for item in self.quantiles))
            if any(value != value.to_integral_value() for value in values):
                raise ValidationContractError("Bar streak values must be integral.")


@dataclass(frozen=True, slots=True)
class MonteCarloResultV2:
    result_id: UUID
    outcome: MonteCarloOutcomeV2
    backtest: ValidationArtifactReferenceV2
    trace: ValidationArtifactReferenceV2
    strategy_version: ValidationArtifactReferenceV2
    cost_assumptions: ValidationArtifactReferenceV2
    dataset_id: str
    dataset_version: str
    dataset_sha256: str
    dataset_lineage_sha256: str
    manifest_sha256: str
    metrics_report_id: UUID
    metrics_report_sha256: str
    metrics_method: str
    metrics_policy_sha256: str
    metrics_input_sha256: str
    source_returns_sha256: str
    instrument_id: str
    venue: str
    timeframe: str
    policy: MonteCarloPolicyV2
    seed: int
    source_return_count: int
    metrics: tuple[MetricDistributionV2, ...]
    assumptions: tuple[str, ...]
    warnings: tuple[str, ...]
    reasons: tuple[str, ...]
    source_as_of: datetime
    source_created_at: datetime
    source_expires_at: datetime
    metrics_report_timestamp: datetime
    as_of: datetime
    created_at: datetime
    content_sha256: str
    scope_profile: str = field(default="PERSONAL_SPOT_RESEARCH", init=False)
    market_type: str = field(default="SPOT", init=False)
    contract_id: str = field(default="C-072", init=False)
    schema_version: str = field(default="2", init=False)
    identity_method: str = field(default=IDENTITY_METHOD, init=False)

    def __post_init__(self) -> None:
        if type(self.result_id) is not UUID or type(self.metrics_report_id) is not UUID:
            raise ValidationContractError("Result identities must be UUIDs.")
        if type(self.outcome) is not MonteCarloOutcomeV2:
            raise ValidationContractError("Unsupported Monte Carlo terminal state.")
        for name, reference, kind, version in (
            ("backtest", self.backtest, "C-027", "3"),
            ("trace", self.trace, "SIMULATION_TRACE", None),
            ("strategy_version", self.strategy_version, "C-021", "2"),
            ("cost_assumptions", self.cost_assumptions, "C-027", "2"),
        ):
            if (
                type(reference) is not ValidationArtifactReferenceV2
                or reference.artifact_type != kind
                or (version is not None and reference.version != version)
            ):
                raise ValidationContractError(f"{name} reference is not exact.")
        for name in (
            "metrics_report_sha256",
            "metrics_policy_sha256",
            "metrics_input_sha256",
            "source_returns_sha256",
            "dataset_sha256",
            "dataset_lineage_sha256",
            "manifest_sha256",
            "content_sha256",
        ):
            _digest(name, getattr(self, name))
        for name in (
            "metrics_method",
            "instrument_id",
            "venue",
            "timeframe",
            "dataset_id",
            "dataset_version",
        ):
            _text(name, getattr(self, name))
        if self.policy.timeframe != self.timeframe:
            raise ValidationContractError("Policy and result timeframes must match.")
        if (
            type(self.policy) is not MonteCarloPolicyV2
            or type(self.seed) is not int
            or not -(2**63) <= self.seed < 2**63
            or type(self.source_return_count) is not int
            or not 0 <= self.source_return_count <= MAX_RECORDED_SOURCE_INTERVALS
        ):
            raise ValidationContractError("Invalid bootstrap seed or source count.")
        if type(self.metrics) is not tuple or any(
            type(item) is not MetricDistributionV2 for item in self.metrics
        ):
            raise ValidationContractError("Metrics must be an immutable typed tuple.")
        if len({item.name for item in self.metrics}) != len(self.metrics):
            raise ValidationContractError("Metric names must be unique.")
        if (
            len(self.assumptions) != len(set(self.assumptions))
            or len(self.warnings) != len(set(self.warnings))
            or len(self.reasons) != len(set(self.reasons))
        ):
            raise ValidationContractError("Explanations must be unique.")
        if (
            type(self.assumptions) is not tuple
            or type(self.warnings) is not tuple
            or type(self.reasons) is not tuple
        ):
            raise ValidationContractError(
                "Assumptions, warnings, and reasons must be tuples."
            )
        for item in (*self.assumptions, *self.warnings, *self.reasons):
            _text("result explanation", item)
        if self.assumptions != ASSUMPTIONS:
            raise ValidationContractError("Bootstrap assumptions must be explicit.")
        for name in (
            "source_as_of",
            "source_created_at",
            "source_expires_at",
            "metrics_report_timestamp",
            "as_of",
            "created_at",
        ):
            object.__setattr__(self, name, _time(name, getattr(self, name)))
        if not (
            self.source_as_of <= self.source_created_at < self.source_expires_at
            and self.source_created_at <= self.metrics_report_timestamp
            and self.as_of <= self.created_at
        ):
            raise ValidationContractError("Result chronology is inconsistent.")
        if self.outcome is MonteCarloOutcomeV2.OBSERVED:
            if (
                self.source_return_count < 100
                or self.policy.path_horizon != self.source_return_count
                or tuple((item.name, item.unit) for item in self.metrics)
                != _EXPECTED_METRICS
                or self.policy.block_length < 2
                or self.policy.block_length > self.source_return_count // 2
                or self.source_return_count < 20 * self.policy.block_length
                or self.reasons
                or self.assumptions != ASSUMPTIONS
                or self.warnings != WARNINGS
            ):
                raise ValidationContractError(
                    "Observed results require a complete supported path."
                )
            if any(
                left.value > right.value
                for metric in self.metrics
                for left, right in zip(
                    metric.quantiles, metric.quantiles[1:], strict=False
                )
            ):
                raise ValidationContractError("Metric quantiles must be ordered.")
        elif self.metrics or not self.reasons or self.warnings:
            raise ValidationContractError(
                "Non-observed results require reasons and no fabricated metrics."
            )
        expected = canonical_sha256(self.identity_payload())
        if self.content_sha256 != expected or self.result_id != uuid5(
            MONTE_CARLO_NAMESPACE_V2, expected
        ):
            raise ValidationContractError("Monte Carlo identity/content mismatch.")

    def identity_payload(self) -> dict[str, object]:
        return {
            item.name: getattr(self, item.name)
            for item in fields(self)
            if item.name not in {"result_id", "content_sha256"}
        }

    @classmethod
    def build(cls, **values: object) -> "MonteCarloResultV2":
        expected = {item.name for item in fields(cls) if item.init} - {
            "result_id",
            "content_sha256",
        }
        if set(values) != expected:
            raise ValidationContractError("Exact Monte Carlo result fields required.")
        payload = dict(values)
        for item in fields(cls):
            if not item.init:
                payload[item.name] = item.default
        digest = canonical_sha256(payload)
        return cls(
            **values,  # type: ignore[arg-type]
            result_id=uuid5(MONTE_CARLO_NAMESPACE_V2, digest),
            content_sha256=digest,
        )


__all__ = [
    "ITERATIONS",
    "MAX_RECORDED_SOURCE_INTERVALS",
    "METHOD",
    "METHOD_VERSION",
    "ASSUMPTIONS",
    "MetricDistributionV2",
    "MetricQuantileV2",
    "MonteCarloOutcomeV2",
    "MonteCarloPolicyV2",
    "MonteCarloResultV2",
    "WARNINGS",
]
