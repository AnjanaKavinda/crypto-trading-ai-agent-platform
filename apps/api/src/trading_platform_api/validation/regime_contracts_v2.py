"""Observation-only C-074 schema 2 for archived Spot regime evidence."""

from __future__ import annotations

from dataclasses import dataclass, field, fields
from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any, cast
from uuid import NAMESPACE_URL, UUID, uuid5

from trading_platform_api.analysis.spot_market_regime import (
    SPOT_MARKET_REGIME_PROFILE_VERSION,
)
from trading_platform_api.analysis.versioned_contracts_v4 import (
    AnalysisOutputReferenceV4,
    AnalysisSnapshotReferenceV4,
)
from trading_platform_api.contracts.serialization import canonical_sha256
from trading_platform_api.market_data.ohlcv import _TIMEFRAMES
from trading_platform_api.validation.contracts import ValidationContractError
from trading_platform_api.validation.contracts_v2 import ValidationArtifactReferenceV2

METHOD = "spot-regime-validation-observation-v1"
METHOD_VERSION = "1"
IDENTITY_METHOD = "spot-regime-validation-identity-v1"
MAX_RUNS = 32
MAX_REQUIRED_CONTEXTS = 32
_NAMESPACE = uuid5(
    NAMESPACE_URL, "trading-platform:C-074:2:spot-regime-validation-identity-v1"
)
_TRENDS = frozenset({"bullish", "bearish", "mixed"})
_VOLATILITY = frozenset({"high", "typical", "low"})
_TRANSITIONS = frozenset({"possible", "not-observed-in-lookback"})
_METRICS = (
    ("cumulative_return", "ratio"),
    ("maximum_fractional_drawdown", "ratio"),
    ("total_trades", "count"),
)
WARNINGS = (
    "DESCRIPTIVE_OBSERVATION_ONLY",
    "OVERLAPPING_OR_REUSED_MARKET_WINDOWS_MAY_BE_DEPENDENT",
    "NO_POOLED_METRICS_OR_CROSS_ASSET_GENERALIZATION",
)


def _text(name: str, value: object, maximum: int = 256) -> None:
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


def _unique(name: str, values: tuple[object, ...]) -> None:
    if len(set(values)) != len(values):
        raise ValidationContractError(f"{name} must be unique.")


class RegimeObservationStateV2(StrEnum):
    OBSERVED = "OBSERVED"
    INCONCLUSIVE = "INCONCLUSIVE"
    FAILED = "FAILED"


class RegimeMetricStateV2(StrEnum):
    AVAILABLE = "AVAILABLE"
    UNDEFINED = "UNDEFINED"
    UNAVAILABLE = "UNAVAILABLE"


class RegimeCoverageStateV2(StrEnum):
    OBSERVED = "OBSERVED"
    INCONCLUSIVE = "INCONCLUSIVE"
    FAILED = "FAILED"
    MISSING = "MISSING"


class DecisionAttributionRuleV2(StrEnum):
    ENTRY_ORDER_DECISION = "ENTRY_ORDER_DECISION"
    NO_ENTRY_FIRST_DECISION = "NO_ENTRY_FIRST_DECISION"


@dataclass(frozen=True, slots=True)
class RegimeMetricsPolicyV2:
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

    @classmethod
    def from_policy(cls, policy: Any) -> "RegimeMetricsPolicyV2":
        if type(policy).__name__ != "MetricsPolicy":
            raise ValidationContractError("Exact C-094 metrics policy is required.")
        return cls(
            policy.method,
            policy.version,
            policy.quote_unit,
            policy.valuation_mode,
            policy.interval_seconds,
            policy.periods_per_year,
            policy.risk_free_return,
            policy.minimum_acceptable_return,
            policy.min_trade_sample,
            policy.min_return_sample,
            policy.report_timestamp,
        )

    def __post_init__(self) -> None:
        for name in ("method", "version", "quote_unit", "valuation_mode"):
            _text(name, getattr(self, name), 128)
        if (
            self.method != "spot-observed-metrics-v1"
            or self.version != "1"
            or self.valuation_mode != "BAR_CLOSE"
            or type(self.interval_seconds) is not int
            or not 1 <= self.interval_seconds <= 31_536_000
            or len(self.quote_unit) > 32
        ):
            raise ValidationContractError("Unsupported C-094 metrics policy.")
        for name in (
            "periods_per_year",
            "risk_free_return",
            "minimum_acceptable_return",
        ):
            value = getattr(self, name)
            if (
                type(value) is not Decimal
                or not value.is_finite()
                or len(value.as_tuple().digits) > 60
                or not -30 <= int(value.as_tuple().exponent) <= 30
                or value.adjusted() > 30
            ):
                raise ValidationContractError(f"{name} must be a finite Decimal.")
        if not 0 < self.periods_per_year <= 31_536_000:
            raise ValidationContractError("periods_per_year is outside C-094 bounds.")
        for name in ("min_trade_sample", "min_return_sample"):
            if (
                type(getattr(self, name)) is not int
                or not 1 <= getattr(self, name) <= 1000
            ):
                raise ValidationContractError(f"{name} must be positive.")
        object.__setattr__(
            self, "report_timestamp", _time("report_timestamp", self.report_timestamp)
        )


@dataclass(frozen=True, slots=True)
class RegimeContextKeyV2:
    venue: str
    asset: str
    instrument_id: str
    timeframe: str
    profile_version: str
    trend: str
    realized_volatility: str
    transition: str

    def __post_init__(self) -> None:
        for name in ("venue", "asset", "instrument_id", "timeframe"):
            _text(name, getattr(self, name), 128)
        if self.timeframe not in _TIMEFRAMES:
            raise ValidationContractError("Unsupported Spot timeframe.")
        if self.profile_version != SPOT_MARKET_REGIME_PROFILE_VERSION:
            raise ValidationContractError("Unsupported C-005 Spot regime profile.")
        if self.trend not in _TRENDS:
            raise ValidationContractError("Unknown C-005 Spot trend state.")
        if self.realized_volatility not in _VOLATILITY:
            raise ValidationContractError("Unknown C-005 Spot volatility state.")
        if self.transition not in _TRANSITIONS:
            raise ValidationContractError("Unknown C-005 Spot transition state.")


@dataclass(frozen=True, slots=True)
class RegimeMetricObservationV2:
    name: str
    state: RegimeMetricStateV2
    value: Decimal | None
    unit: str
    sample_count: int
    sufficient: bool
    reason: str | None
    warnings: tuple[str, ...]

    def __post_init__(self) -> None:
        if type(self.name) is not str or (self.name, self.unit) not in _METRICS:
            raise ValidationContractError("Unsupported C-094 metric or unit.")
        if type(self.state) is not RegimeMetricStateV2:
            raise ValidationContractError("Metric state is invalid.")
        if type(self.sample_count) is not int or self.sample_count < 0:
            raise ValidationContractError("Metric sample count must be nonnegative.")
        if type(self.sufficient) is not bool:
            raise ValidationContractError("Metric sufficiency must be explicit.")
        if self.value is not None and (
            type(self.value) is not Decimal or not self.value.is_finite()
        ):
            raise ValidationContractError("Metric value must be a finite Decimal.")
        if (self.state is RegimeMetricStateV2.AVAILABLE) != (self.value is not None):
            raise ValidationContractError("Metric state/value availability mismatch.")
        if self.sufficient and self.state is not RegimeMetricStateV2.AVAILABLE:
            raise ValidationContractError("Unavailable metric cannot be sufficient.")
        if self.reason is not None:
            _text("metric reason", self.reason)
        if self.state is not RegimeMetricStateV2.AVAILABLE and self.reason is None:
            raise ValidationContractError("Unavailable metric requires a reason.")
        if type(self.warnings) is not tuple:
            raise ValidationContractError("Metric warnings must be an immutable tuple.")
        for warning in self.warnings:
            _text("metric warning", warning)
        _unique("metric warnings", self.warnings)


@dataclass(frozen=True, slots=True)
class SpotRegimeObservationV2:
    run_index: int
    state: RegimeObservationStateV2
    reason_codes: tuple[str, ...]
    request_sha256: str
    request_parameters_sha256: str
    execution_policy_sha256: str
    metrics_policy: RegimeMetricsPolicyV2
    metrics_policy_sha256: str
    backtest: ValidationArtifactReferenceV2 | None
    trace: ValidationArtifactReferenceV2 | None
    source_bundle_sha256: str | None
    metrics_report_id: UUID | None
    metrics_report_sha256: str | None
    metrics_input_sha256: str | None
    strategy_version: ValidationArtifactReferenceV2
    cost_assumptions: ValidationArtifactReferenceV2
    cost_adapter: ValidationArtifactReferenceV2
    dataset_id: str | None
    dataset_version: str | None
    dataset_sha256: str
    dataset_lineage_sha256: str | None
    manifest_sha256: str
    quote_unit: str
    quantity_unit: str
    venue: str
    asset: str
    instrument_id: str
    timeframe: str
    source_as_of: datetime | None
    source_created_at: datetime | None
    source_expires_at: datetime | None
    metrics_report_timestamp: datetime | None
    period_start: datetime
    period_end: datetime
    attribution_rule: DecisionAttributionRuleV2 | None
    decision_id: UUID | None
    decision_time: datetime | None
    market_context: ValidationArtifactReferenceV2 | None
    analysis_snapshot: AnalysisSnapshotReferenceV4 | None
    regime: AnalysisOutputReferenceV4 | None
    evidence: tuple[AnalysisOutputReferenceV4, ...]
    context_key: RegimeContextKeyV2 | None
    metrics: tuple[RegimeMetricObservationV2, ...]

    def __post_init__(self) -> None:
        if type(self.run_index) is not int or not 0 <= self.run_index < MAX_RUNS:
            raise ValidationContractError("Run index is outside the frozen plan.")
        if type(self.state) is not RegimeObservationStateV2:
            raise ValidationContractError("Run observation state is invalid.")
        if (
            self.state is not RegimeObservationStateV2.OBSERVED
            and not self.reason_codes
        ):
            raise ValidationContractError("Non-observed run requires explicit reasons.")
        for name in (
            "request_sha256",
            "request_parameters_sha256",
            "execution_policy_sha256",
            "metrics_policy_sha256",
            "dataset_sha256",
            "manifest_sha256",
        ):
            _digest(name, getattr(self, name))
        if type(self.metrics_policy) is not RegimeMetricsPolicyV2:
            raise ValidationContractError("Exact C-094 metrics policy is required.")
        if canonical_sha256(self.metrics_policy) != self.metrics_policy_sha256:
            raise ValidationContractError("Metrics policy digest mismatch.")
        for name, reference, kind, version in (
            ("backtest", self.backtest, "C-027", "3"),
            ("trace", self.trace, "SIMULATION_TRACE", None),
            ("strategy_version", self.strategy_version, "C-021", "2"),
            ("cost_assumptions", self.cost_assumptions, "C-027", "2"),
            (
                "cost_adapter",
                self.cost_adapter,
                "SPOT-COST-ADAPTER",
                "spot-execution-cost-adapter-v1",
            ),
        ):
            if reference is not None and (
                type(reference) is not ValidationArtifactReferenceV2
                or reference.artifact_type != kind
                or (version is not None and reference.version != version)
            ):
                raise ValidationContractError(f"{name} reference is not exact.")
        if self.backtest is None:
            if self.state is RegimeObservationStateV2.OBSERVED or any(
                item is not None
                for item in (
                    self.trace,
                    self.source_bundle_sha256,
                    self.metrics_report_id,
                    self.metrics_report_sha256,
                    self.metrics_input_sha256,
                    self.dataset_id,
                    self.dataset_version,
                    self.dataset_lineage_sha256,
                )
            ):
                raise ValidationContractError(
                    "Unresolved run has partial source closure."
                )
        else:
            if self.trace is None or self.source_bundle_sha256 is None:
                raise ValidationContractError("Observed replay requires trace closure.")
            _digest("source_bundle_sha256", self.source_bundle_sha256)
            if self.metrics_report_id is not None:
                if type(self.metrics_report_id) is not UUID:
                    raise ValidationContractError("Metrics report identity is invalid.")
                _digest("metrics_report_sha256", self.metrics_report_sha256)
                _digest("metrics_input_sha256", self.metrics_input_sha256)
            elif any(
                item is not None
                for item in (self.metrics_report_sha256, self.metrics_input_sha256)
            ):
                raise ValidationContractError("Metrics report identity is required.")
            _text("dataset_id", self.dataset_id)
            _text("dataset_version", self.dataset_version)
            _digest("dataset_lineage_sha256", self.dataset_lineage_sha256)
        for name in ("venue", "asset", "instrument_id", "timeframe"):
            _text(name, getattr(self, name), 128)
        _text("quote_unit", self.quote_unit, 32)
        _text("quantity_unit", self.quantity_unit, 32)
        if self.metrics_policy.quote_unit != self.quote_unit:
            raise ValidationContractError("Metrics quote unit differs from execution.")
        if self.metrics_policy.interval_seconds != _TIMEFRAMES.get(self.timeframe):
            raise ValidationContractError("Metrics interval differs from timeframe.")
        times = (
            self.source_as_of,
            self.source_created_at,
            self.source_expires_at,
            self.metrics_report_timestamp,
        )
        if self.backtest is None:
            if any(value is not None for value in times):
                raise ValidationContractError(
                    "Unresolved source has result timestamps."
                )
        else:
            if any(type(value) is not datetime for value in times):
                raise ValidationContractError(
                    "Resolved source timestamps are required."
                )
            for name in (
                "source_as_of",
                "source_created_at",
                "source_expires_at",
                "metrics_report_timestamp",
            ):
                if getattr(self, name) is not None:
                    object.__setattr__(self, name, _time(name, getattr(self, name)))
            if self.state is not RegimeObservationStateV2.FAILED:
                if any(value is None for value in times):
                    raise ValidationContractError(
                        "Nonfailed source timestamps are incomplete."
                    )
                source_as_of = cast(datetime, self.source_as_of)
                source_created_at = cast(datetime, self.source_created_at)
                source_expires_at = cast(datetime, self.source_expires_at)
                report_timestamp = cast(datetime, self.metrics_report_timestamp)
                if not (
                    source_as_of <= source_created_at < source_expires_at
                    and report_timestamp >= source_created_at
                    and report_timestamp == self.metrics_policy.report_timestamp
                ):
                    raise ValidationContractError(
                        "Source/report chronology is invalid."
                    )
        start = _time("period_start", self.period_start)
        end = _time("period_end", self.period_end)
        if start >= end:
            raise ValidationContractError("Run period is invalid.")
        object.__setattr__(self, "period_start", start)
        object.__setattr__(self, "period_end", end)
        if type(self.reason_codes) is not tuple:
            raise ValidationContractError("Run reasons must be an immutable tuple.")
        for reason in self.reason_codes:
            _text("run reason", reason)
        _unique("run reasons", self.reason_codes)
        if type(self.evidence) is not tuple or any(
            type(item) is not AnalysisOutputReferenceV4 or item.contract_id != "C-008"
            for item in self.evidence
        ):
            raise ValidationContractError(
                "Exact C-008 evidence references are required."
            )
        _unique(
            "run evidence references", tuple(item.record_id for item in self.evidence)
        )
        if self.state is RegimeObservationStateV2.FAILED and not self.reason_codes:
            raise ValidationContractError("Failed run requires explicit reasons.")
        attribution = (
            self.attribution_rule,
            self.decision_id,
            self.decision_time,
            self.market_context,
            self.analysis_snapshot,
            self.regime,
            self.context_key,
        )
        if self.attribution_rule is None:
            if any(item is not None for item in attribution[1:]) or self.evidence:
                raise ValidationContractError(
                    "Unattributed run has partial regime data."
                )
        else:
            if (
                type(self.attribution_rule) is not DecisionAttributionRuleV2
                or type(self.decision_id) is not UUID
                or type(self.decision_time) is not datetime
                or type(self.market_context) is not ValidationArtifactReferenceV2
                or self.market_context.artifact_type != "C-006"
                or self.market_context.version != "5"
                or type(self.analysis_snapshot) is not AnalysisSnapshotReferenceV4
                or type(self.regime) is not AnalysisOutputReferenceV4
                or self.regime.contract_id != "C-005"
                or type(self.context_key) is not RegimeContextKeyV2
            ):
                raise ValidationContractError(
                    "Decision-time regime closure is incomplete."
                )
            object.__setattr__(
                self, "decision_time", _time("decision_time", self.decision_time)
            )
        if (
            type(self.metrics) is not tuple
            or tuple((item.name, item.unit) for item in self.metrics) != _METRICS
        ):
            raise ValidationContractError("C-094 metrics must be complete and ordered.")
        if any(type(item) is not RegimeMetricObservationV2 for item in self.metrics):
            raise ValidationContractError("C-094 metric observation is invalid.")
        for item in self.metrics:
            minimum = (
                self.metrics_policy.min_trade_sample
                if item.name == "total_trades"
                else self.metrics_policy.min_return_sample
            )
            expected_sufficient = (
                item.state is RegimeMetricStateV2.AVAILABLE
                and item.sample_count >= minimum
                and "INSUFFICIENT_SAMPLE" not in item.warnings
            )
            if item.sufficient is not expected_sufficient:
                raise ValidationContractError(
                    "Metric sample sufficiency is inconsistent."
                )
            if (
                item.name == "total_trades"
                and item.value is not None
                and (item.value < 0 or item.value != item.value.to_integral_value())
            ):
                raise ValidationContractError("Total-trade metric must be a count.")
        if self.context_key is not None and (
            self.context_key.venue,
            self.context_key.asset,
            self.context_key.instrument_id,
            self.context_key.timeframe,
        ) != (self.venue, self.asset, self.instrument_id, self.timeframe):
            raise ValidationContractError("Context key differs from run scope.")
        if self.state is RegimeObservationStateV2.OBSERVED and (
            self.backtest is None
            or self.metrics_report_id is None
            or self.attribution_rule is None
            or any(not item.sufficient for item in self.metrics)
            or self.reason_codes
        ):
            raise ValidationContractError("Observed run is incomplete or inconclusive.")


@dataclass(frozen=True, slots=True)
class RegimeContextCoverageV2:
    key: RegimeContextKeyV2
    required: bool
    state: RegimeCoverageStateV2
    run_indexes: tuple[int, ...]
    sufficient_run_indexes: tuple[int, ...]

    def __post_init__(self) -> None:
        if type(self.key) is not RegimeContextKeyV2 or type(self.required) is not bool:
            raise ValidationContractError(
                "Context coverage key/required flag is invalid."
            )
        if type(self.state) is not RegimeCoverageStateV2:
            raise ValidationContractError("Context coverage state is invalid.")
        for name, values in (
            ("run_indexes", self.run_indexes),
            ("sufficient_run_indexes", self.sufficient_run_indexes),
        ):
            if type(values) is not tuple or any(
                type(item) is not int or not 0 <= item < MAX_RUNS for item in values
            ):
                raise ValidationContractError(f"{name} must contain run indexes.")
            _unique(name, values)
        if not set(self.sufficient_run_indexes).issubset(self.run_indexes):
            raise ValidationContractError("Sufficient runs must be covered runs.")
        if self.state is RegimeCoverageStateV2.MISSING and self.run_indexes:
            raise ValidationContractError("Missing context cannot reference runs.")
        if self.state is not RegimeCoverageStateV2.MISSING and not self.run_indexes:
            raise ValidationContractError("Present context must reference a run.")
        if self.required and self.state is RegimeCoverageStateV2.MISSING:
            return


@dataclass(frozen=True, slots=True)
class SpotRegimeValidationResultV2:
    result_id: UUID
    outcome: RegimeObservationStateV2
    strategy_version: ValidationArtifactReferenceV2
    metrics_method: str
    metrics_method_version: str
    minimum_trade_sample: int
    minimum_return_sample: int
    required_contexts: tuple[RegimeContextKeyV2, ...]
    observations: tuple[SpotRegimeObservationV2, ...]
    contexts: tuple[RegimeContextCoverageV2, ...]
    warnings: tuple[str, ...]
    reasons: tuple[str, ...]
    as_of: datetime
    created_at: datetime
    content_sha256: str
    scope_profile: str = field(default="PERSONAL_SPOT_RESEARCH", init=False)
    market_type: str = field(default="SPOT", init=False)
    method: str = field(default=METHOD, init=False)
    method_version: str = field(default=METHOD_VERSION, init=False)
    contract_id: str = field(default="C-074", init=False)
    schema_version: str = field(default="2", init=False)
    identity_method: str = field(default=IDENTITY_METHOD, init=False)

    def __post_init__(self) -> None:
        if type(self.result_id) is not UUID:
            raise ValidationContractError("C-074v2 result identity must be a UUID.")
        if type(self.outcome) is not RegimeObservationStateV2:
            raise ValidationContractError("C-074v2 outcome is invalid.")
        if (
            type(self.strategy_version) is not ValidationArtifactReferenceV2
            or self.strategy_version.artifact_type != "C-021"
            or self.strategy_version.version != "2"
        ):
            raise ValidationContractError("Exact C-021v2 strategy is required.")
        if (
            self.metrics_method != "spot-observed-metrics-v1"
            or self.metrics_method_version != "1"
        ):
            raise ValidationContractError("Unsupported C-094 metrics method.")
        if any(
            type(value) is not int or not 1 <= value <= 1000
            for value in (self.minimum_trade_sample, self.minimum_return_sample)
        ):
            raise ValidationContractError("C-094 sample minimums are invalid.")
        if (
            type(self.required_contexts) is not tuple
            or not 1 <= len(self.required_contexts) <= MAX_REQUIRED_CONTEXTS
            or any(
                type(item) is not RegimeContextKeyV2 for item in self.required_contexts
            )
        ):
            raise ValidationContractError("Required context plan is invalid.")
        _unique("required context keys", self.required_contexts)
        if (
            type(self.observations) is not tuple
            or not 1 <= len(self.observations) <= MAX_RUNS
            or any(
                type(item) is not SpotRegimeObservationV2 for item in self.observations
            )
            or tuple(item.run_index for item in self.observations)
            != tuple(range(len(self.observations)))
        ):
            raise ValidationContractError("Run observations must preserve plan order.")
        _unique(
            "planned requests",
            tuple(item.request_sha256 for item in self.observations),
        )
        _unique(
            "backtest results",
            tuple(
                item.backtest.artifact_id for item in self.observations if item.backtest
            ),
        )
        if any(
            item.strategy_version != self.strategy_version
            or item.metrics_policy.method != self.metrics_method
            or item.metrics_policy.version != self.metrics_method_version
            or item.metrics_policy.min_trade_sample != self.minimum_trade_sample
            or item.metrics_policy.min_return_sample != self.minimum_return_sample
            for item in self.observations
        ):
            raise ValidationContractError(
                "Run strategy or C-094 method policy differs."
            )
        observed_keys = tuple(
            dict.fromkeys(
                item.context_key
                for item in self.observations
                if item.context_key is not None
                and item.context_key not in self.required_contexts
            )
        )
        expected_keys = (*self.required_contexts, *observed_keys)
        if (
            type(self.contexts) is not tuple
            or tuple(item.key for item in self.contexts) != expected_keys
            or any(type(item) is not RegimeContextCoverageV2 for item in self.contexts)
        ):
            raise ValidationContractError("Context coverage order/closure is invalid.")
        for coverage in self.contexts:
            matching = tuple(
                item.run_index
                for item in self.observations
                if item.context_key == coverage.key
            )
            sufficient = tuple(
                item.run_index
                for item in self.observations
                if item.context_key == coverage.key
                and item.state is RegimeObservationStateV2.OBSERVED
            )
            expected_state = (
                RegimeCoverageStateV2.MISSING
                if not matching
                else RegimeCoverageStateV2.OBSERVED
                if sufficient
                else RegimeCoverageStateV2.FAILED
                if all(
                    self.observations[index].state is RegimeObservationStateV2.FAILED
                    for index in matching
                )
                else RegimeCoverageStateV2.INCONCLUSIVE
            )
            if (
                coverage.required != (coverage.key in self.required_contexts)
                or coverage.run_indexes != matching
                or coverage.sufficient_run_indexes != sufficient
                or coverage.state is not expected_state
            ):
                raise ValidationContractError("Context coverage state is inconsistent.")
        if type(self.warnings) is not tuple or type(self.reasons) is not tuple:
            raise ValidationContractError("Explanations must be immutable tuples.")
        for item in (*self.warnings, *self.reasons):
            _text("result explanation", item)
        _unique("result warnings", self.warnings)
        _unique("result reasons", self.reasons)
        if self.warnings != WARNINGS:
            raise ValidationContractError(
                "C-074v2 method limitations must be explicit."
            )
        if (
            any(
                item.state is RegimeCoverageStateV2.MISSING
                for item in self.contexts
                if item.required
            )
            and "REQUIRED_CONTEXT_COVERAGE_MISSING" not in self.reasons
        ):
            raise ValidationContractError(
                "Missing context requires an explicit reason."
            )
        if self.outcome is RegimeObservationStateV2.OBSERVED and self.reasons:
            raise ValidationContractError(
                "Observed result cannot carry failure reasons."
            )
        if self.outcome is RegimeObservationStateV2.FAILED and not self.reasons:
            raise ValidationContractError("Failed result requires explicit reasons.")
        as_of = _time("as_of", self.as_of)
        created_at = _time("created_at", self.created_at)
        if created_at < as_of:
            raise ValidationContractError("Creation time precedes analysis cutoff.")
        object.__setattr__(self, "as_of", as_of)
        object.__setattr__(self, "created_at", created_at)
        expected_outcome = (
            RegimeObservationStateV2.FAILED
            if any(
                item.state is RegimeObservationStateV2.FAILED
                for item in self.observations
            )
            else RegimeObservationStateV2.INCONCLUSIVE
            if any(
                coverage.state is not RegimeCoverageStateV2.OBSERVED
                for coverage in self.contexts
                if coverage.required
            )
            or any(
                item.state is not RegimeObservationStateV2.OBSERVED
                for item in self.observations
            )
            else RegimeObservationStateV2.OBSERVED
        )
        if self.outcome is not expected_outcome:
            raise ValidationContractError("C-074v2 outcome does not match evidence.")
        if self.outcome is not RegimeObservationStateV2.OBSERVED and not self.reasons:
            raise ValidationContractError(
                "Non-observed result requires explicit reasons."
            )
        if any(
            item.state is not RegimeObservationStateV2.FAILED
            and (
                item.source_created_at is None
                or item.source_expires_at is None
                or item.metrics_report_timestamp is None
                or item.source_created_at > as_of
                or item.source_expires_at <= as_of
                or item.metrics_report_timestamp > as_of
            )
            for item in self.observations
        ):
            raise ValidationContractError("Nonfailed source is stale at analysis time.")
        _digest("content_sha256", self.content_sha256)
        if self.content_sha256 != result_content_sha256(self):
            raise ValidationContractError("C-074v2 content digest mismatch.")
        if self.result_id != uuid5(_NAMESPACE, self.content_sha256):
            raise ValidationContractError("C-074v2 result identity mismatch.")

    @classmethod
    def build(cls, **values: object) -> "SpotRegimeValidationResultV2":
        payload: dict[str, Any] = {
            key: value
            for key, value in values.items()
            if key not in {"result_id", "content_sha256"}
        }
        digest_payload = {
            **payload,
            **(
                {
                    "scope_profile": "PERSONAL_SPOT_RESEARCH",
                    "market_type": "SPOT",
                    "method": METHOD,
                    "method_version": METHOD_VERSION,
                    "contract_id": "C-074",
                    "schema_version": "2",
                    "identity_method": IDENTITY_METHOD,
                }
            ),
        }
        digest = canonical_sha256(digest_payload)
        return cls(
            result_id=uuid5(_NAMESPACE, digest), content_sha256=digest, **payload
        )


def result_content_sha256(result: SpotRegimeValidationResultV2) -> str:
    return canonical_sha256(
        {
            item.name: getattr(result, item.name)
            for item in fields(result)
            if item.name not in {"result_id", "content_sha256"}
        }
    )
