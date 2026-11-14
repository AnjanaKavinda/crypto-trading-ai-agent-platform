"""Observation-only C-073 schema 2 for Spot parameter sensitivity."""

from dataclasses import dataclass, field, fields
from datetime import UTC, datetime
from decimal import ROUND_HALF_EVEN, Context, Decimal, localcontext
from enum import StrEnum
from uuid import NAMESPACE_URL, UUID, uuid5

from trading_platform_api.contracts.serialization import canonical_sha256
from trading_platform_api.validation.contracts import ValidationContractError
from trading_platform_api.validation.contracts_v2 import ValidationArtifactReferenceV2

METRICS_METHOD = "spot-observed-metrics-v1"

METHOD = "spot-parameter-sensitivity"
METHOD_VERSION = "1"
IDENTITY_METHOD = "spot-sensitivity-identity-v1"
PARAMETERS = {
    "quantity": None,
    "entry_expiry": "seconds",
    "holding_interval": "seconds",
    "exit_expiry": "seconds",
}
GRID_LIMIT = 5
SCENARIO_LIMIT = 9
COST_MULTIPLIERS = (
    Decimal("1"),
    Decimal("1.25"),
    Decimal("1.5"),
    Decimal("2"),
    Decimal("3"),
)
ASSUMPTIONS = (
    "ONE_PARAMETER_VARIED_AT_A_TIME",
    "COST_STRESS_VARIED_SEPARATELY_FROM_PARAMETER_GRID",
    "CONDITIONAL_ON_EXACT_OBSERVED_SPOT_DATA_AND_POLICY",
    "DESCRIPTIVE_NOT_SELECTION_OR_QUALIFICATION",
    "NOT_OUT_OF_SAMPLE_OR_FUTURE_PERFORMANCE_EVIDENCE",
)
WARNINGS = (
    "NO_OPTIMAL_PARAMETER_SELECTED",
    "LOCAL_PEAKS_AND_DEGRADATION_ARE_DESCRIPTIVE_ONLY",
    "DOES_NOT_COMPLETE_FUTURES_VALIDATION",
)
SENSITIVITY_NAMESPACE_V2 = uuid5(
    NAMESPACE_URL, "trading-platform:C-073:2:spot-sensitivity-identity-v1"
)


class SensitivityOutcomeV2(StrEnum):
    OBSERVED = "OBSERVED"
    INCONCLUSIVE = "INCONCLUSIVE"
    FAILED = "FAILED"


class SensitivityScenarioKindV2(StrEnum):
    PARAMETER = "PARAMETER"
    COST = "COST"


def _text(name: str, value: object, *, maximum: int = 256) -> None:
    if (
        type(value) is not str
        or not value.strip()
        or value != value.strip()
        or len(value.encode("utf-8")) > maximum
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


def _decimal(name: str, value: object, *, positive: bool = False) -> None:
    if (
        type(value) is not Decimal
        or not value.is_finite()
        or (positive and value <= 0)
    ):
        raise ValidationContractError(f"{name} must be a finite Decimal.")


def _reference(
    name: str,
    value: object,
    artifact_type: str,
    version: str | None = None,
) -> None:
    if (
        type(value) is not ValidationArtifactReferenceV2
        or value.artifact_type != artifact_type
        or (version is not None and value.version != version)
    ):
        raise ValidationContractError(f"{name} reference is not exact.")


@dataclass(frozen=True, slots=True)
class SensitivityMetricsPolicyV2:
    method: str
    version: str
    quote_unit: str
    valuation_mode: str
    interval_seconds: int
    periods_per_year: Decimal
    risk_free_return: Decimal
    minimum_acceptable_return: Decimal
    min_trade_sample: int
    min_return_sample: int
    report_timestamp: datetime

    def __post_init__(self) -> None:
        if self.method != METRICS_METHOD or self.version != "1":
            raise ValidationContractError("Unsupported Spot metrics policy.")
        if self.valuation_mode != "BAR_CLOSE":
            raise ValidationContractError("Unsupported Spot valuation mode.")
        _text("metrics quote unit", self.quote_unit, maximum=32)
        if (
            type(self.interval_seconds) is not int
            or not 1 <= self.interval_seconds <= 31_536_000
            or type(self.min_trade_sample) is not int
            or not 1 <= self.min_trade_sample <= 1_000
            or type(self.min_return_sample) is not int
            or not 1 <= self.min_return_sample <= 1_000
        ):
            raise ValidationContractError("Spot metrics policy bounds are invalid.")
        for name in (
            "periods_per_year",
            "risk_free_return",
            "minimum_acceptable_return",
        ):
            _decimal(name, getattr(self, name), positive=name == "periods_per_year")
        if self.periods_per_year > 31_536_000:
            raise ValidationContractError("Spot annualization is excessive.")
        object.__setattr__(
            self, "report_timestamp", _time("report_timestamp", self.report_timestamp)
        )

    @classmethod
    def from_policy(cls, policy: object) -> "SensitivityMetricsPolicyV2":
        if type(policy).__name__ != "MetricsPolicy":
            raise ValidationContractError("Exact C-094 metrics policy is required.")
        return cls(
            policy.method,  # type: ignore[attr-defined]
            policy.version,  # type: ignore[attr-defined]
            policy.quote_unit,  # type: ignore[attr-defined]
            policy.valuation_mode,  # type: ignore[attr-defined]
            policy.interval_seconds,  # type: ignore[attr-defined]
            policy.periods_per_year,  # type: ignore[attr-defined]
            policy.risk_free_return,  # type: ignore[attr-defined]
            policy.minimum_acceptable_return,  # type: ignore[attr-defined]
            policy.min_trade_sample,  # type: ignore[attr-defined]
            policy.min_return_sample,  # type: ignore[attr-defined]
            policy.report_timestamp,  # type: ignore[attr-defined]
        )


@dataclass(frozen=True, slots=True)
class SensitivityMetricsV2:
    cumulative_return: Decimal
    maximum_fractional_drawdown: Decimal
    total_trades: int

    def __post_init__(self) -> None:
        _decimal("cumulative_return", self.cumulative_return)
        _decimal(
            "maximum_fractional_drawdown", self.maximum_fractional_drawdown
        )
        if (
            self.maximum_fractional_drawdown < 0
            or self.maximum_fractional_drawdown > 1
            or type(self.total_trades) is not int
            or self.total_trades < 0
        ):
            raise ValidationContractError("Sensitivity metric values are invalid.")


@dataclass(frozen=True, slots=True)
class SensitivityScenarioV2:
    key: str
    kind: SensitivityScenarioKindV2
    parameter_value: Decimal
    cost_multiplier: Decimal
    outcome: SensitivityOutcomeV2
    backtest: ValidationArtifactReferenceV2 | None
    trace: ValidationArtifactReferenceV2 | None
    cost_assumptions: ValidationArtifactReferenceV2
    metrics_report_id: UUID | None
    metrics_report_sha256: str | None
    metrics_input_sha256: str | None
    metrics: SensitivityMetricsV2 | None
    return_delta: Decimal | None
    drawdown_delta: Decimal | None
    return_degraded: bool
    drawdown_degraded: bool
    local_peak: bool
    reasons: tuple[str, ...]
    backtest_as_of: datetime | None = None
    backtest_created_at: datetime | None = None
    backtest_expires_at: datetime | None = None
    metrics_report_timestamp: datetime | None = None

    def __post_init__(self) -> None:
        _text("scenario key", self.key)
        if type(self.kind) is not SensitivityScenarioKindV2:
            raise ValidationContractError("Scenario kind is unsupported.")
        if type(self.outcome) is not SensitivityOutcomeV2:
            raise ValidationContractError("Scenario outcome is unsupported.")
        _decimal("parameter_value", self.parameter_value, positive=True)
        _decimal("cost_multiplier", self.cost_multiplier, positive=True)
        if self.cost_multiplier not in COST_MULTIPLIERS:
            raise ValidationContractError("Unsupported cost multiplier.")
        if self.kind is SensitivityScenarioKindV2.PARAMETER:
            if self.cost_multiplier != Decimal("1"):
                raise ValidationContractError("Parameter scenarios use baseline costs.")
        elif self.cost_multiplier == Decimal("1"):
            raise ValidationContractError("Cost scenarios must stress costs.")
        if self.backtest is not None:
            _reference("backtest", self.backtest, "C-027", "3")
        if self.trace is not None:
            _reference("trace", self.trace, "SIMULATION_TRACE")
        if (self.backtest is None) != (self.trace is None):
            raise ValidationContractError("Backtest and trace references must pair.")
        _reference("cost_assumptions", self.cost_assumptions, "C-027", "2")
        if self.metrics_report_id is not None and type(self.metrics_report_id) is not UUID:
            raise ValidationContractError("Metrics report identity must be a UUID.")
        for name in ("metrics_report_sha256", "metrics_input_sha256"):
            value = getattr(self, name)
            if value is not None:
                _digest(name, value)
        for name in (
            "backtest_as_of",
            "backtest_created_at",
            "backtest_expires_at",
            "metrics_report_timestamp",
        ):
            value = getattr(self, name)
            if value is not None:
                object.__setattr__(self, name, _time(name, value))
        backtest_times = (
            self.backtest_as_of,
            self.backtest_created_at,
            self.backtest_expires_at,
        )
        if self.backtest is None:
            if any(value is not None for value in backtest_times):
                raise ValidationContractError("Backtest timestamps require a result.")
        elif (
            self.backtest_as_of is None
            or self.backtest_created_at is None
            or self.backtest_expires_at is None
            or not self.backtest_as_of
            <= self.backtest_created_at
            < self.backtest_expires_at
        ):
            raise ValidationContractError("Scenario backtest chronology is invalid.")
        report_fields = (
            self.metrics_report_id,
            self.metrics_report_sha256,
            self.metrics_input_sha256,
            self.metrics_report_timestamp,
        )
        if any(value is not None for value in report_fields) and not all(
            value is not None for value in report_fields
        ):
            raise ValidationContractError("Metrics report closure is incomplete.")
        for name in ("return_delta", "drawdown_delta"):
            value = getattr(self, name)
            if value is not None:
                _decimal(name, value)
        if any(
            type(value) is not bool
            for value in (
                self.return_degraded,
                self.drawdown_degraded,
                self.local_peak,
            )
        ):
            raise ValidationContractError("Sensitivity flags must be booleans.")
        if type(self.reasons) is not tuple or len(set(self.reasons)) != len(
            self.reasons
        ):
            raise ValidationContractError("Scenario reasons must be immutable/unique.")
        for reason in self.reasons:
            _text("scenario reason", reason)
        if self.outcome is SensitivityOutcomeV2.OBSERVED:
            if (
                self.backtest is None
                or self.trace is None
                or self.metrics_report_id is None
                or self.metrics_report_sha256 is None
                or self.metrics_input_sha256 is None
                or self.metrics_report_timestamp is None
                or self.backtest_as_of is None
                or self.backtest_created_at is None
                or self.backtest_expires_at is None
                or type(self.metrics) is not SensitivityMetricsV2
                or self.return_delta is None
                or self.drawdown_delta is None
                or self.reasons
            ):
                raise ValidationContractError("Observed scenario closure is incomplete.")
        elif not self.reasons:
            raise ValidationContractError("Non-observed scenarios require reasons.")
        elif self.outcome is SensitivityOutcomeV2.FAILED and (
            self.metrics is not None
            or self.return_delta is not None
            or self.drawdown_delta is not None
            or self.return_degraded
            or self.drawdown_degraded
            or self.local_peak
        ):
            raise ValidationContractError("Failed scenarios cannot report metrics.")
        elif self.outcome is SensitivityOutcomeV2.INCONCLUSIVE and (
            (self.return_delta is None) != (self.drawdown_delta is None)
            or (
                self.return_delta is None
                and (self.return_degraded or self.drawdown_degraded)
            )
            or (
                self.return_delta is not None
                and (
                    self.metrics is None
                    or self.drawdown_delta is None
                    or self.return_degraded != (self.return_delta < 0)
                    or self.drawdown_degraded != (self.drawdown_delta > 0)
                    or self.local_peak
                )
            )
        ):
            raise ValidationContractError("Inconclusive scenario flags are inconsistent.")


@dataclass(frozen=True, slots=True)
class SensitivityZeroCrossingV2:
    series: SensitivityScenarioKindV2
    lower_key: str
    upper_key: str

    def __post_init__(self) -> None:
        if type(self.series) is not SensitivityScenarioKindV2:
            raise ValidationContractError("Zero-crossing series is invalid.")
        _text("lower_key", self.lower_key)
        _text("upper_key", self.upper_key)
        if self.lower_key == self.upper_key:
            raise ValidationContractError("Zero crossing requires adjacent scenarios.")


@dataclass(frozen=True, slots=True)
class SensitivityResultV2:
    result_id: UUID
    outcome: SensitivityOutcomeV2
    parameter_name: str
    parameter_unit: str
    quantity_unit: str
    baseline_value: Decimal
    parameter_grid: tuple[Decimal, ...]
    cost_multipliers: tuple[Decimal, ...]
    input_request_sha256: str
    source_bundle_sha256: str
    source_backtest: ValidationArtifactReferenceV2
    source_trace: ValidationArtifactReferenceV2
    source_metrics_report_id: UUID
    source_metrics_report_sha256: str
    strategy_version: ValidationArtifactReferenceV2
    source_cost_assumptions: ValidationArtifactReferenceV2
    source_as_of: datetime
    source_created_at: datetime
    source_expires_at: datetime
    dataset_id: str
    dataset_version: str
    dataset_sha256: str
    dataset_lineage_sha256: str
    manifest_sha256: str
    venue: str
    instrument_id: str
    timeframe: str
    period_start: datetime
    period_end: datetime
    metrics_method: str
    metrics_policy: SensitivityMetricsPolicyV2
    metrics_policy_sha256: str
    scenarios: tuple[SensitivityScenarioV2, ...]
    zero_crossings: tuple[SensitivityZeroCrossingV2, ...]
    assumptions: tuple[str, ...]
    warnings: tuple[str, ...]
    reasons: tuple[str, ...]
    as_of: datetime
    created_at: datetime
    content_sha256: str
    scope_profile: str = field(default="PERSONAL_SPOT_RESEARCH", init=False)
    market_type: str = field(default="SPOT", init=False)
    method: str = field(default=METHOD, init=False)
    method_version: str = field(default=METHOD_VERSION, init=False)
    contract_id: str = field(default="C-073", init=False)
    schema_version: str = field(default="2", init=False)
    identity_method: str = field(default=IDENTITY_METHOD, init=False)

    def __post_init__(self) -> None:
        if type(self.result_id) is not UUID or type(self.source_metrics_report_id) is not UUID:
            raise ValidationContractError("Sensitivity identities must be UUIDs.")
        if type(self.outcome) is not SensitivityOutcomeV2:
            raise ValidationContractError("Sensitivity terminal state is unsupported.")
        if self.parameter_name not in PARAMETERS:
            raise ValidationContractError("Unsupported sensitivity parameter.")
        _text("parameter_unit", self.parameter_unit)
        _text("quantity_unit", self.quantity_unit)
        _decimal("baseline_value", self.baseline_value, positive=True)
        if (
            type(self.parameter_grid) is not tuple
            or not 3 <= len(self.parameter_grid) <= GRID_LIMIT
            or any(type(value) is not Decimal for value in self.parameter_grid)
            or any(not value.is_finite() or value <= 0 for value in self.parameter_grid)
            or any(left >= right for left, right in zip(self.parameter_grid, self.parameter_grid[1:]))
            or self.baseline_value not in self.parameter_grid
            or not any(value < self.baseline_value for value in self.parameter_grid)
            or not any(value > self.baseline_value for value in self.parameter_grid)
        ):
            raise ValidationContractError("Sensitivity grid must be ordered around baseline.")
        if (
            (self.parameter_name == "quantity" and self.parameter_unit != self.quantity_unit)
            or (
                self.parameter_name != "quantity"
                and self.parameter_unit != PARAMETERS[self.parameter_name]
            )
        ):
            raise ValidationContractError("Sensitivity parameter unit does not match.")
        if self.parameter_unit == "seconds" and any(
            value != value.to_integral_value() for value in self.parameter_grid
        ):
            raise ValidationContractError("Interval parameters must be whole seconds.")
        if self.cost_multipliers != COST_MULTIPLIERS:
            raise ValidationContractError("Cost stress multipliers are fixed.")
        for name in (
            "input_request_sha256",
            "source_bundle_sha256",
            "source_metrics_report_sha256",
            "dataset_sha256",
            "dataset_lineage_sha256",
            "manifest_sha256",
            "metrics_policy_sha256",
            "content_sha256",
        ):
            _digest(name, getattr(self, name))
        _reference("source_backtest", self.source_backtest, "C-027", "3")
        _reference("source_trace", self.source_trace, "SIMULATION_TRACE")
        _reference("strategy_version", self.strategy_version, "C-021", "2")
        _reference("source_cost_assumptions", self.source_cost_assumptions, "C-027", "2")
        for name in ("dataset_id", "dataset_version", "venue", "instrument_id", "timeframe", "metrics_method"):
            _text(name, getattr(self, name))
        if type(self.metrics_policy) is not SensitivityMetricsPolicyV2:
            raise ValidationContractError("Exact Spot metrics policy is required.")
        if (
            self.metrics_method != METRICS_METHOD
            or canonical_sha256(self.metrics_policy) != self.metrics_policy_sha256
        ):
            raise ValidationContractError("Spot metrics policy digest mismatch.")
        object.__setattr__(self, "period_start", _time("period_start", self.period_start))
        object.__setattr__(self, "period_end", _time("period_end", self.period_end))
        object.__setattr__(self, "source_as_of", _time("source_as_of", self.source_as_of))
        object.__setattr__(
            self, "source_created_at", _time("source_created_at", self.source_created_at)
        )
        object.__setattr__(
            self, "source_expires_at", _time("source_expires_at", self.source_expires_at)
        )
        object.__setattr__(self, "as_of", _time("as_of", self.as_of))
        object.__setattr__(self, "created_at", _time("created_at", self.created_at))
        if not (
            self.period_start < self.period_end
            and self.source_as_of <= self.source_created_at
            < self.source_expires_at
            and self.as_of <= self.created_at
        ):
            raise ValidationContractError("Sensitivity chronology is inconsistent.")
        if self.outcome is not SensitivityOutcomeV2.FAILED and not (
            self.source_created_at
            <= self.metrics_policy.report_timestamp
            <= self.as_of
            < self.source_expires_at
        ):
            raise ValidationContractError("Observed evidence is stale or non-point-in-time.")
        if (
            type(self.scenarios) is not tuple
            or not 3 <= len(self.scenarios) <= SCENARIO_LIMIT
            or any(type(item) is not SensitivityScenarioV2 for item in self.scenarios)
            or len({item.key for item in self.scenarios}) != len(self.scenarios)
        ):
            raise ValidationContractError("Sensitivity scenarios are invalid.")
        parameter_scenarios = tuple(
            item
            for item in self.scenarios
            if item.kind is SensitivityScenarioKindV2.PARAMETER
        )
        cost_scenarios = tuple(
            item for item in self.scenarios if item.kind is SensitivityScenarioKindV2.COST
        )
        if (
            tuple(item.parameter_value for item in parameter_scenarios)
            != self.parameter_grid
            or tuple(item.cost_multiplier for item in cost_scenarios)
            != COST_MULTIPLIERS[1:]
            or any(item.parameter_value != self.baseline_value for item in cost_scenarios)
        ):
            raise ValidationContractError("Sensitivity scenario plan is incomplete.")
        baseline_scenarios = tuple(
            item
            for item in parameter_scenarios
            if item.parameter_value == self.baseline_value
        )
        if len(baseline_scenarios) != 1:
            raise ValidationContractError("Exactly one baseline scenario is required.")
        baseline_metrics = baseline_scenarios[0].metrics
        for scenario in self.scenarios:
            if scenario.backtest is not None and (
                scenario.backtest_as_of != self.source_as_of
                or scenario.backtest_created_at != self.source_created_at
                or scenario.backtest_expires_at != self.source_expires_at
            ):
                raise ValidationContractError(
                    "Scenario replay timestamps differ from the frozen source."
                )
            if (
                scenario.metrics_report_timestamp is not None
                and scenario.metrics_report_timestamp
                != self.metrics_policy.report_timestamp
            ):
                raise ValidationContractError("Scenario metrics policy time changed.")
            if scenario.outcome is SensitivityOutcomeV2.FAILED:
                continue
            if scenario.metrics is not None and baseline_metrics is not None:
                with localcontext(Context(prec=50, rounding=ROUND_HALF_EVEN)):
                    expected_return_delta = (
                        scenario.metrics.cumulative_return
                        - baseline_metrics.cumulative_return
                    )
                    expected_drawdown_delta = (
                        scenario.metrics.maximum_fractional_drawdown
                        - baseline_metrics.maximum_fractional_drawdown
                    )
                if (
                    scenario.return_delta != expected_return_delta
                    or scenario.drawdown_delta != expected_drawdown_delta
                    or scenario.return_degraded != (expected_return_delta < 0)
                    or scenario.drawdown_degraded != (expected_drawdown_delta > 0)
                ):
                    raise ValidationContractError("Sensitivity deltas are inconsistent.")
            elif (
                scenario.return_delta is not None
                or scenario.drawdown_delta is not None
                or scenario.return_degraded
                or scenario.drawdown_degraded
            ):
                raise ValidationContractError("Sensitivity deltas require baseline metrics.")
        expected_peaks: set[str] = set()
        for left, current, right in zip(
            parameter_scenarios,
            parameter_scenarios[1:],
            parameter_scenarios[2:],
            strict=False,
        ):
            if (
                left.metrics is not None
                and current.metrics is not None
                and right.metrics is not None
                and current.metrics.cumulative_return > left.metrics.cumulative_return
                and current.metrics.cumulative_return > right.metrics.cumulative_return
            ):
                expected_peaks.add(current.key)
        if any(
            scenario.local_peak
            != (scenario.kind is SensitivityScenarioKindV2.PARAMETER and scenario.key in expected_peaks)
            for scenario in self.scenarios
        ):
            raise ValidationContractError("Local-peak flags are inconsistent.")
        if type(self.zero_crossings) is not tuple or any(
            type(item) is not SensitivityZeroCrossingV2 for item in self.zero_crossings
        ):
            raise ValidationContractError("Zero crossings must be immutable and typed.")
        expected_crossings: list[SensitivityZeroCrossingV2] = []
        for kind in SensitivityScenarioKindV2:
            ordered = (
                (baseline_scenarios[0], *cost_scenarios)
                if kind is SensitivityScenarioKindV2.COST
                else parameter_scenarios
            )
            for left, right in zip(ordered, ordered[1:]):
                if left.metrics is None or right.metrics is None:
                    continue
                first = left.metrics.cumulative_return
                second = right.metrics.cumulative_return
                if (first < 0 <= second) or (second < 0 <= first):
                    expected_crossings.append(
                        SensitivityZeroCrossingV2(kind, left.key, right.key)
                    )
        if self.zero_crossings != tuple(expected_crossings):
            raise ValidationContractError("Zero-crossing flags are inconsistent.")
        for name in ("assumptions", "warnings", "reasons"):
            values = getattr(self, name)
            if type(values) is not tuple or len(values) != len(set(values)):
                raise ValidationContractError(f"{name} must be immutable and unique.")
            for value in values:
                _text(name, value)
        if self.assumptions != ASSUMPTIONS:
            raise ValidationContractError("Sensitivity assumptions are fixed.")
        if self.outcome is SensitivityOutcomeV2.OBSERVED:
            if (
                self.reasons
                or self.warnings != WARNINGS
                or any(item.outcome is not SensitivityOutcomeV2.OBSERVED for item in self.scenarios)
            ):
                raise ValidationContractError("Observed sensitivity must be complete.")
        elif not self.reasons or self.warnings:
            raise ValidationContractError("Non-observed sensitivity requires reasons only.")
        expected = canonical_sha256(self.identity_payload())
        if self.content_sha256 != expected or self.result_id != uuid5(
            SENSITIVITY_NAMESPACE_V2, expected
        ):
            raise ValidationContractError("Sensitivity identity/content mismatch.")

    def identity_payload(self) -> dict[str, object]:
        return {
            item.name: getattr(self, item.name)
            for item in fields(self)
            if item.name not in {"result_id", "content_sha256"}
        }

    @classmethod
    def build(cls, **values: object) -> "SensitivityResultV2":
        required = {item.name for item in fields(cls) if item.init} - {
            "result_id",
            "content_sha256",
        }
        if set(values) != required:
            raise ValidationContractError("Exact sensitivity result fields required.")
        payload = dict(values)
        for item in fields(cls):
            if not item.init:
                payload[item.name] = item.default
        digest = canonical_sha256(payload)
        return cls(
            **values,  # type: ignore[arg-type]
            result_id=uuid5(SENSITIVITY_NAMESPACE_V2, digest),
            content_sha256=digest,
        )


__all__ = [
    "ASSUMPTIONS",
    "COST_MULTIPLIERS",
    "GRID_LIMIT",
    "METHOD",
    "METHOD_VERSION",
    "PARAMETERS",
    "SCENARIO_LIMIT",
    "SensitivityMetricsV2",
    "SensitivityOutcomeV2",
    "SensitivityResultV2",
    "SensitivityScenarioKindV2",
    "SensitivityScenarioV2",
    "SensitivityZeroCrossingV2",
    "WARNINGS",
]
