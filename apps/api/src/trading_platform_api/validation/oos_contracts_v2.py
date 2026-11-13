"""Additive C-071 schema 2; observed OOS evidence, never qualification authority."""

from __future__ import annotations

import json
from dataclasses import dataclass, field, fields
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid5

from trading_platform_api.config import DeploymentEnvironment, OperatingMode
from trading_platform_api.contracts.serialization import (
    canonical_json_dumps,
    canonical_sha256,
)
from trading_platform_api.market_data.ohlcv import _TIMEFRAMES
from trading_platform_api.validation.contracts import (
    CheckOutcome,
    DataPartition,
    MetricValue,
    PartitionPurpose,
)
from trading_platform_api.validation.contracts_v2 import (
    CostAssumptionSetV2,
    ValidationArtifactReferenceV2,
)
from trading_platform_api.validation.contracts_v3 import BacktestResultV3

METHOD = "spot-oos-observation-v1"
NAMESPACE = uuid5(NAMESPACE_URL, "trading-platform:C-071:2:spot-oos-v1")
MAX_EVENTS = 512
MAX_CANDIDATES = 16

_INTEGRITY_FAILURE_REASONS = frozenset(
    {
        "CROSS_BOUNDARY_OPEN_INVENTORY",
        "OOS_CUTOFF_MISMATCH",
        "OOS_DECISION_OUTSIDE_PARTITION",
        "OOS_EXECUTION_WINDOW_MISMATCH",
        "OOS_FILL_OUTSIDE_PARTITION",
        "OOS_METRICS_POLICY_MISMATCH",
        "OOS_REQUIRES_FLAT_POSITIVE_CAPITAL",
        "OOS_REPLAY_CANDIDATE_MISMATCH",
        "OOS_REPLAY_REQUEST_CLOSURE_MISMATCH",
        "OOS_REQUEST_NOT_SELECTED_STRATEGY",
        "OOS_RESULT_CUTOFF_MISMATCH",
        "OOS_RESULT_WINDOW_MISMATCH",
        "OOS_SCOPE_OR_UNIT_MISMATCH",
        "OOS_STRATEGY_PARAMETERS_OR_COST_MISMATCH",
        "OOS_TRACE_UNRESOLVED",
        "OOS_WARMUP_EXCEEDED",
        "INVALID_OOS_BACKTEST_REQUEST",
    }
)
_CONTAMINATION_FAILURE_REASONS = frozenset(
    {
        "HOLDOUT_PREVIOUSLY_ACCESSED_OR_REUSED",
        "HOLDOUT_RESELECTION",
        "SELECTION_CHANGED_AFTER_FREEZE",
        "SELECTION_PRECEDES_FREEZE",
    }
)


def is_integrity_failure_reason(reason: str) -> bool:
    return reason.split(":", 1)[0] in _INTEGRITY_FAILURE_REASONS


def is_contamination_failure_reason(reason: str) -> bool:
    return reason.split(":", 1)[0] in _CONTAMINATION_FAILURE_REASONS


def derive_integrity_status(*, failed: bool, unresolved: bool) -> CheckOutcome:
    if failed:
        return CheckOutcome.FAILED
    if unresolved:
        return CheckOutcome.INCONCLUSIVE
    return CheckOutcome.PASSED


def require(condition: bool, reason: str) -> None:
    if not condition:
        raise ValueError(reason)


def text(value: str) -> None:
    require(
        type(value) is str and 0 < len(value) <= 256 and value == value.strip(),
        "INVALID_OOS_TEXT",
    )


def result_receipt_purpose(
    outcome: OOSOutcome,
    contamination: CheckOutcome,
    integrity: CheckOutcome,
    sample_sufficiency: CheckOutcome,
    reason_codes: tuple[str, ...],
) -> str:
    return ":".join(
        (
            "RECORDED_OUTCOME",
            outcome.value,
            contamination.value,
            integrity.value,
            sample_sufficiency.value,
            canonical_sha256(reason_codes),
        )
    )


def digest(value: str) -> None:
    require(
        type(value) is str
        and len(value) == 64
        and all(c in "0123456789abcdef" for c in value),
        "INVALID_OOS_DIGEST",
    )


def utc(value: datetime) -> datetime:
    require(
        type(value) is datetime and value.utcoffset() is not None, "INVALID_OOS_TIME"
    )
    return value.astimezone(UTC)


def payload(value: Any, omitted: set[str]) -> dict[str, object]:
    return {
        f.name: getattr(value, f.name) for f in fields(value) if f.name not in omitted
    }


def ref(
    value: ValidationArtifactReferenceV2, kind: str, version: str | None = None
) -> None:
    require(
        type(value) is ValidationArtifactReferenceV2
        and value.artifact_type == kind
        and (version is None or value.version == version),
        "INVALID_OOS_REFERENCE",
    )


def _wire(value):
    if isinstance(value, list):
        return tuple(_wire(v) for v in value)
    if isinstance(value, dict):
        return {k: _wire(v) for k, v in value.items()}
    return value


class OOSSelectionMode(StrEnum):
    FIXED = "PREDECLARED_FIXED_STRATEGY_NO_OPTIMIZATION"
    VALIDATION_NET_PROFIT = "MAX_VALIDATION_NET_REALIZED_PROFIT_V1"


class OOSOutcome(StrEnum):
    OBSERVED = "OBSERVED"
    INCONCLUSIVE = "INCONCLUSIVE"
    FAILED = "FAILED"


class OOSEventKind(StrEnum):
    FREEZE = "FREEZE"
    SELECT = "SELECT"
    ACCESS = "ACCESS"
    TRIAL = "TRIAL"
    RESULT = "RESULT"


@dataclass(frozen=True, slots=True)
class OOSWindow:
    venue: str
    instrument_id: str
    timeframe: str
    start: datetime
    end: datetime

    def __post_init__(self) -> None:
        for value in (self.venue, self.instrument_id, self.timeframe):
            text(value)
        require(
            self.instrument_id.endswith("-SPOT") and self.timeframe in _TIMEFRAMES,
            "UNSUPPORTED_OOS_SCOPE",
        )
        object.__setattr__(self, "start", utc(self.start))
        object.__setattr__(self, "end", utc(self.end))
        require(self.start < self.end, "EMPTY_OOS_WINDOW")

    def overlaps(self, other: OOSWindow) -> bool:
        return (
            self.instrument_id == other.instrument_id
            and self.start < other.end
            and other.start < self.end
        )


@dataclass(frozen=True, slots=True)
class OOSCandidateV2:
    strategy: ValidationArtifactReferenceV2
    parameters: ValidationArtifactReferenceV2
    costs: ValidationArtifactReferenceV2
    cost_adapter: ValidationArtifactReferenceV2
    execution_policy_sha256: str

    def __post_init__(self) -> None:
        ref(self.strategy, "C-021", "2")
        ref(self.parameters, "PARAMETER_SET")
        ref(self.costs, "C-027", "2")
        require(
            type(self.cost_adapter) is ValidationArtifactReferenceV2,
            "INVALID_OOS_COST_ADAPTER",
        )
        digest(self.execution_policy_sha256)

    @property
    def candidate_id(self) -> UUID:
        return uuid5(NAMESPACE, canonical_sha256(self))


@dataclass(frozen=True, slots=True)
class OOSProtocolV2:
    protocol_id: UUID
    content_sha256: str
    journal_id: UUID
    authority: ValidationArtifactReferenceV2
    window: OOSWindow
    partitions: tuple[DataPartition, ...]
    candidates: tuple[OOSCandidateV2, ...]
    selection_mode: OOSSelectionMode
    metrics_policy_sha256: str
    minimum_trades: int
    warmup_bars: int
    embargo_seconds: int
    mark_equity: bool
    environment: DeploymentEnvironment
    frozen_at: datetime
    method: str = field(default="spot-oos-protocol-v1", init=False)

    def __post_init__(self) -> None:
        require(
            type(self.protocol_id) is UUID and type(self.journal_id) is UUID,
            "INVALID_PROTOCOL_ID",
        )
        require(
            type(self.authority) is ValidationArtifactReferenceV2
            and type(self.window) is OOSWindow,
            "INVALID_PROTOCOL_AUTHORITY",
        )
        require(
            type(self.partitions) is tuple
            and len(self.partitions) == 3
            and all(type(p) is DataPartition for p in self.partitions),
            "INVALID_OOS_PARTITIONS",
        )
        train, validation, holdout = self.partitions
        require(
            train.purpose is PartitionPurpose.TRAIN
            and validation.purpose is PartitionPurpose.VALIDATION
            and holdout.purpose
            in (PartitionPurpose.TEST, PartitionPurpose.OUT_OF_SAMPLE),
            "INVALID_PARTITION_ROLES",
        )
        require(
            len({p.partition_id for p in self.partitions}) == 3,
            "DUPLICATE_PARTITION_ID",
        )
        require(
            type(self.embargo_seconds) is int
            and 0 <= self.embargo_seconds <= 31_536_000,
            "INVALID_EMBARGO",
        )
        step = _TIMEFRAMES[self.window.timeframe]
        for partition in self.partitions:
            require(
                partition.start < partition.end
                and partition.start.microsecond == partition.end.microsecond == 0,
                "EMPTY_OR_FRACTIONAL_PARTITION",
            )
            require(
                int(partition.start.timestamp()) % step
                == int(partition.end.timestamp()) % step
                == 0,
                "UNALIGNED_PARTITION",
            )
        for a, b in zip(self.partitions, self.partitions[1:]):
            require(
                a.end + timedelta(seconds=self.embargo_seconds) <= b.start,
                "PARTITION_OVERLAP_OR_EMBARGO",
            )
        require(
            all(p.point_in_time_cutoff <= p.end for p in self.partitions),
            "DEVELOPMENT_CUTOFF_EXCEEDS_PARTITION",
        )
        require(
            (holdout.start, holdout.end) == (self.window.start, self.window.end)
            and not holdout.used_for_optimization,
            "INVALID_FINAL_HOLDOUT",
        )
        require(
            type(self.candidates) is tuple
            and 1 <= len(self.candidates) <= MAX_CANDIDATES
            and all(type(c) is OOSCandidateV2 for c in self.candidates)
            and len({c.candidate_id for c in self.candidates}) == len(self.candidates),
            "INVALID_OOS_CANDIDATES",
        )
        require(
            type(self.selection_mode) is OOSSelectionMode, "UNSUPPORTED_OOS_SELECTION"
        )
        if self.selection_mode is OOSSelectionMode.FIXED:
            require(len(self.candidates) == 1, "FIXED_SELECTION_REQUIRES_ONE_CANDIDATE")
        digest(self.metrics_policy_sha256)
        require(
            type(self.minimum_trades) is int and 1 <= self.minimum_trades <= 1000,
            "INVALID_OOS_SAMPLE_MINIMUM",
        )
        require(
            type(self.warmup_bars) is int
            and 0 <= self.warmup_bars <= 10_000
            and type(self.mark_equity) is bool,
            "INVALID_OOS_VALUATION_POLICY",
        )
        require(
            self.environment in (DeploymentEnvironment.DEV, DeploymentEnvironment.TEST),
            "UNSUPPORTED_OOS_ENVIRONMENT",
        )
        object.__setattr__(self, "frozen_at", utc(self.frozen_at))
        expected = canonical_sha256(payload(self, {"protocol_id", "content_sha256"}))
        require(
            self.content_sha256 == expected
            and self.protocol_id == uuid5(NAMESPACE, "protocol:" + expected),
            "PROTOCOL_DIGEST_MISMATCH",
        )

    @classmethod
    def build(cls, **values) -> OOSProtocolV2:
        preimage = dict(values, method="spot-oos-protocol-v1")
        sha = canonical_sha256(preimage)
        return cls(
            protocol_id=uuid5(NAMESPACE, "protocol:" + sha),
            content_sha256=sha,
            **values,
        )


@dataclass(frozen=True, slots=True)
class OOSJournalEvent:
    sequence: int
    recorded_at: datetime
    kind: OOSEventKind
    window: OOSWindow
    protocol_sha256: str | None
    candidate_id: UUID | None
    purpose: str
    evidence: tuple[ValidationArtifactReferenceV2, ...]
    previous_sha256: str
    content_sha256: str

    def __post_init__(self) -> None:
        require(
            type(self.sequence) is int and 0 <= self.sequence < MAX_EVENTS,
            "INVALID_JOURNAL_SEQUENCE",
        )
        object.__setattr__(self, "recorded_at", utc(self.recorded_at))
        require(
            type(self.kind) is OOSEventKind and type(self.window) is OOSWindow,
            "INVALID_JOURNAL_EVENT",
        )
        if self.protocol_sha256 is not None:
            digest(self.protocol_sha256)
        require(
            self.candidate_id is None or type(self.candidate_id) is UUID,
            "INVALID_JOURNAL_CANDIDATE",
        )
        text(self.purpose)
        require(
            type(self.evidence) is tuple
            and len(self.evidence) <= 8
            and all(type(e) is ValidationArtifactReferenceV2 for e in self.evidence),
            "INVALID_JOURNAL_EVIDENCE",
        )
        digest(self.previous_sha256)
        require(
            self.content_sha256 == canonical_sha256(payload(self, {"content_sha256"})),
            "JOURNAL_EVENT_DIGEST_MISMATCH",
        )

    @classmethod
    def build(cls, **values) -> OOSJournalEvent:
        return cls(content_sha256=canonical_sha256(values), **values)


@dataclass(frozen=True, slots=True)
class OOSJournalSnapshot:
    journal_id: UUID
    authority: ValidationArtifactReferenceV2
    declared_complete: bool
    events: tuple[OOSJournalEvent, ...]

    def __post_init__(self) -> None:
        require(
            type(self.journal_id) is UUID
            and type(self.authority) is ValidationArtifactReferenceV2
            and type(self.declared_complete) is bool
            and type(self.events) is tuple
            and len(self.events) <= MAX_EVENTS,
            "INVALID_RESEARCH_JOURNAL",
        )
        previous = "0" * 64
        at: datetime | None = None
        for index, event in enumerate(self.events):
            require(
                type(event) is OOSJournalEvent
                and event.sequence == index
                and event.previous_sha256 == previous
                and (at is None or at <= event.recorded_at),
                "INVALID_JOURNAL_CHAIN",
            )
            previous, at = event.content_sha256, event.recorded_at

    @property
    def content_sha256(self) -> str:
        return canonical_sha256(self)


@dataclass(frozen=True, slots=True)
class OOSRunBindingV2:
    partition_id: UUID
    backtest: BacktestResultV3
    metrics_report: ValidationArtifactReferenceV2
    candidate: OOSCandidateV2
    execution_model: str
    configuration: str
    cost_assumptions: CostAssumptionSetV2
    request: ValidationArtifactReferenceV2
    report_document: str

    def __post_init__(self) -> None:
        try:
            self._validate()
        except (
            KeyError,
            TypeError,
            AttributeError,
            RecursionError,
            StopIteration,
        ) as error:
            raise ValueError("INVALID_OOS_RUN_DOCUMENT") from error

    def _validate(self) -> None:
        b, c = self.backtest, self.candidate
        require(
            type(self.partition_id) is UUID
            and type(b) is BacktestResultV3
            and type(c) is OOSCandidateV2
            and type(self.cost_assumptions) is CostAssumptionSetV2,
            "INVALID_OOS_RUN_BINDING",
        )
        ref(self.metrics_report, "SPOT_PERFORMANCE_REPORT", "1")
        ref(self.request, "SPOT_OOS_REQUEST", "1")
        for document, reference in (
            (self.execution_model, b.execution_model),
            (self.configuration, b.configuration),
        ):
            require(
                type(document) is str and len(document) <= 32768, "INVALID_RUN_DOCUMENT"
            )
            require(
                canonical_json_dumps(_wire(json.loads(document))) == document
                and canonical_sha256(_wire(json.loads(document)))
                == reference.content_sha256,
                "OOS_RUN_ARTIFACT_MISMATCH",
            )
        model, config = json.loads(self.execution_model), json.loads(self.configuration)
        p = model["policy"]
        require(
            (b.strategy_version, b.parameter_set, b.cost_assumptions)
            == (c.strategy, c.parameters, c.costs)
            and self.cost_assumptions.content_sha256 == c.costs.content_sha256
            and self.cost_assumptions.assumption_set_id == c.costs.artifact_id
            and canonical_sha256(_wire(model["parameters"]))
            == c.parameters.content_sha256
            and model["parameters"]["strategy_version_id"]
            == str(c.strategy.artifact_id)
            and model["parameters"]["strategy_sha256"] == c.strategy.content_sha256
            and config["input_request"]["strategy"]["strategy_version_id"]
            == str(c.strategy.artifact_id)
            and config["input_request"]["strategy"]["content_sha256"]
            == c.strategy.content_sha256
            and model["cost_adapter"]
            == json.loads(canonical_json_dumps(c.cost_adapter))
            and canonical_sha256(
                {k: v for k, v in p.items() if k not in {"period_start", "period_end"}}
            )
            == c.execution_policy_sha256
            and (b.venue, b.instrument_id, b.timeframe, b.environment)
            == tuple(
                p[k] for k in ("venue", "instrument_id", "timeframe", "environment")
            )
            and [p["period_start"], p["period_end"]]
            == json.loads(canonical_json_dumps((b.period_start, b.period_end)))
            and config["execution_policy"] == p
            and (
                config["execution_dataset_sha256"],
                config["execution_manifest_sha256"],
            )
            == (b.dataset_sha256, b.manifest_sha256)
            and [config[k] for k in ("result_as_of", "created_at", "expires_at")]
            == json.loads(canonical_json_dumps((b.as_of, b.created_at, b.expires_at))),
            "OOS_RUN_CANDIDATE_OR_POLICY_MISMATCH",
        )
        expected = canonical_sha256(
            _wire(
                dict(
                    inputs=config["input_request"],
                    archives=config["archive_pins"],
                    dataset=b.dataset_sha256,
                    manifest=b.manifest_sha256,
                    execution=p,
                    parameters=model["parameters"],
                    costs=self.cost_assumptions,
                    adapter=c.cost_adapter,
                    as_of=b.as_of,
                    created=b.created_at,
                    expiry=b.expires_at,
                )
            )
        )
        require(
            self.request.content_sha256 == expected
            and self.request.artifact_id
            == uuid5(NAMESPACE_URL, "spot-oos-request-v1:" + expected),
            "OOS_RUN_REQUEST_DIGEST_MISMATCH",
        )
        self.resolve_report()

    def resolve_report(self):
        from trading_platform_api.lineage.codec import decode_value
        from trading_platform_api.validation.spot_metrics import (
            _NAMESPACE as metric_namespace,
        )
        from trading_platform_api.validation.spot_metrics import METHOD as metric_method
        from trading_platform_api.validation.spot_metrics import (
            MetricState,
            SpotPerformanceReport,
        )

        require(
            type(self.report_document) is str
            and len(self.report_document.encode()) <= 1_000_000,
            "OOS_REPORT_DOCUMENT_BUDGET",
        )
        report = decode_value(SpotPerformanceReport, json.loads(self.report_document))
        sha = canonical_sha256(payload(report, {"report_id", "content_sha256"}))
        b = self.backtest
        require(
            canonical_json_dumps(report) == self.report_document
            and sha == report.content_sha256 == self.metrics_report.content_sha256
            and report.report_id
            == self.metrics_report.artifact_id
            == uuid5(metric_namespace, sha),
            "OOS_REPORT_DIGEST_MISMATCH",
        )
        require(
            report.method == metric_method
            and report.policy.method == metric_method
            and report.policy.version == "1"
            and (
                report.result_id,
                report.result_schema,
                report.result_sha256,
                report.trace_sha256,
                report.dataset_sha256,
                report.manifest_sha256,
                report.cost_sha256,
                report.strategy_sha256,
            )
            == (
                b.result_id,
                b.schema_version,
                b.content_sha256,
                b.trace.content_sha256,
                b.dataset_sha256,
                b.manifest_sha256,
                b.cost_assumptions.content_sha256,
                b.strategy_version.content_sha256,
            ),
            "OOS_REPORT_INPUT_MISMATCH",
        )
        total = report.get("total_trades")
        require(
            sorted(t.trade_id for t in report.trades) == sorted(b.simulated_trade_ids)
            and total.state is MetricState.AVAILABLE
            and total.metric is not None
            and total.metric.value == total.sample_count == len(report.trades),
            "OOS_REPORT_SAMPLE_MISMATCH",
        )
        return report


@dataclass(frozen=True, slots=True)
class OOSMetricV2:
    name: str
    state: str
    reason: str | None
    value: MetricValue | None
    sample_count: int
    warnings: tuple[str, ...]

    def __post_init__(self) -> None:
        text(self.name)
        require(
            self.state in ("AVAILABLE", "UNDEFINED", "UNAVAILABLE")
            and type(self.sample_count) is int
            and self.sample_count >= 0
            and type(self.warnings) is tuple,
            "INVALID_OOS_METRIC_STATE",
        )
        if self.state == "AVAILABLE":
            require(
                type(self.value) is MetricValue
                and self.value.name == self.name
                and self.reason is None,
                "INVALID_AVAILABLE_METRIC",
            )
        else:
            require(
                self.value is None and type(self.reason) is str and bool(self.reason),
                "MISSING_METRIC_REASON",
            )


@dataclass(frozen=True, slots=True)
class OOSResultV2:
    result_id: UUID
    content_sha256: str
    protocol: OOSProtocolV2
    journal: OOSJournalSnapshot
    request_reference: ValidationArtifactReferenceV2
    selected_candidate: OOSCandidateV2 | None
    runs: tuple[OOSRunBindingV2, ...]
    metrics: tuple[OOSMetricV2, ...]
    contamination: CheckOutcome
    integrity: CheckOutcome
    sample_sufficiency: CheckOutcome
    sample_size: int
    outcome: OOSOutcome
    reason_codes: tuple[str, ...]
    warnings: tuple[str, ...]
    as_of: datetime
    created_at: datetime
    expires_at: datetime
    method: str = field(default=METHOD, init=False)
    contract_id: str = field(default="C-071", init=False)
    schema_version: str = field(default="2", init=False)
    operating_mode: OperatingMode = field(default=OperatingMode.BACKTEST, init=False)

    def __post_init__(self) -> None:
        require(
            type(self.protocol) is OOSProtocolV2
            and type(self.journal) is OOSJournalSnapshot,
            "UNRESOLVED_OOS_PROTOCOL",
        )
        require(
            (self.protocol.journal_id, self.protocol.authority)
            == (self.journal.journal_id, self.journal.authority),
            "OOS_JOURNAL_AUTHORITY_MISMATCH",
        )
        require(
            type(self.request_reference) is ValidationArtifactReferenceV2
            and self.request_reference.artifact_type == "SPOT_OOS_REQUEST"
            and self.request_reference.version == "1",
            "OOS_REQUEST_RECEIPT_MISMATCH",
        )
        require(
            self.selected_candidate is None
            or self.selected_candidate in self.protocol.candidates,
            "UNKNOWN_SELECTED_CANDIDATE",
        )
        require(
            type(self.runs) is tuple
            and len(self.runs) <= 2 * MAX_CANDIDATES + 1
            and all(type(r) is OOSRunBindingV2 for r in self.runs),
            "INVALID_OOS_RUNS",
        )
        require(
            type(self.metrics) is tuple
            and all(type(m) is OOSMetricV2 for m in self.metrics)
            and len({m.name for m in self.metrics}) == len(self.metrics),
            "INVALID_OOS_METRICS",
        )
        for keys in (
            [(r.partition_id, r.candidate.candidate_id) for r in self.runs],
            [r.backtest.result_id for r in self.runs],
            [r.metrics_report.artifact_id for r in self.runs],
            [r.request.artifact_id for r in self.runs],
        ):
            require(len(set(keys)) == len(self.runs), "DUPLICATE_OOS_RUN")
        require(
            type(self.sample_size) is int
            and self.sample_size >= 0
            and type(self.outcome) is OOSOutcome,
            "INVALID_OOS_SAMPLE_OR_OUTCOME",
        )
        require(
            type(self.contamination) is CheckOutcome
            and type(self.integrity) is CheckOutcome
            and type(self.sample_sufficiency) is CheckOutcome,
            "INVALID_OOS_CHECKS",
        )
        for name in ("as_of", "created_at", "expires_at"):
            object.__setattr__(self, name, utc(getattr(self, name)))
        require(
            self.as_of <= self.created_at < self.expires_at
            and self.protocol.frozen_at <= self.created_at,
            "INVALID_OOS_RESULT_TIME",
        )
        held = tuple(
            r
            for r in self.runs
            if r.partition_id == self.protocol.partitions[-1].partition_id
        )
        require(
            all(r.backtest.as_of == self.as_of for r in held),
            "OOS_AS_OF_REPLAY_MISMATCH",
        )
        require(
            all(self.expires_at <= r.backtest.expires_at for r in self.runs),
            "OOS_EXPIRY_EXCEEDS_RUN",
        )
        require(bool(held) or not self.metrics, "OOS_METRICS_WITHOUT_HOLDOUT")
        require(
            len(held) <= 1
            and self.sample_size
            == (len(held[0].backtest.simulated_trade_ids) if held else 0)
            and (self.sample_sufficiency is CheckOutcome.PASSED)
            == (self.sample_size >= self.protocol.minimum_trades),
            "OOS_SAMPLE_BINDING_MISMATCH",
        )
        require(
            type(self.reason_codes) is tuple and type(self.warnings) is tuple,
            "INVALID_OOS_REASONS",
        )
        for value in self.reason_codes + self.warnings:
            text(value)
        self._validate_closure()
        if self.outcome is OOSOutcome.OBSERVED:
            require(
                self.contamination is CheckOutcome.PASSED
                and self.integrity is CheckOutcome.PASSED
                and self.sample_sufficiency is CheckOutcome.PASSED
                and self.sample_size >= self.protocol.minimum_trades
                and self.selected_candidate is not None
                and not self.reason_codes,
                "OBSERVED_OOS_REQUIRES_VALID_EVIDENCE",
            )
            require(
                len(held) == 1
                and self.sample_size == len(held[0].backtest.simulated_trade_ids),
                "OOS_SAMPLE_BINDING_MISMATCH",
            )
        else:
            require(bool(self.reason_codes), "MISSING_OOS_FAILURE_REASON")
        require(
            (self.outcome is OOSOutcome.FAILED)
            == (CheckOutcome.FAILED in (self.contamination, self.integrity)),
            "OOS_FAILURE_CHECK_MISMATCH",
        )
        require(
            self.content_sha256 == canonical_sha256(self.identity_payload())
            and self.result_id == uuid5(NAMESPACE, "result:" + self.content_sha256),
            "OOS_RESULT_DIGEST_MISMATCH",
        )

    def _validate_closure(self) -> None:
        try:
            self._check_closure()
        except (KeyError, TypeError, AttributeError, RecursionError) as error:
            raise ValueError("INVALID_OOS_RESULT_CLOSURE") from error

    def _check_closure(self) -> None:
        protocol = self.protocol
        events = tuple(
            e
            for e in self.journal.events
            if e.protocol_sha256 == protocol.content_sha256
        )
        freezes = tuple(e for e in events if e.kind is OOSEventKind.FREEZE)
        selections = tuple(e for e in events if e.kind is OOSEventKind.SELECT)
        require(
            all(e.purpose == protocol.selection_mode.value for e in selections),
            "OOS_SELECTION_PURPOSE_MISMATCH",
        )
        if self.selected_candidate is not None:
            require(
                len(selections) >= 1
                and len(freezes) == 1
                and selections[0].candidate_id == self.selected_candidate.candidate_id
                and selections[0].window == protocol.window
                and freezes[0].sequence < selections[0].sequence,
                "OOS_SELECTION_RECEIPT_UNRESOLVED",
            )
        if self.outcome is OOSOutcome.OBSERVED or any(
            r.partition_id == protocol.partitions[-1].partition_id for r in self.runs
        ):
            require(
                self.journal.declared_complete
                and len(freezes) == len(selections) == 1
                and freezes[0].recorded_at == protocol.frozen_at
                and freezes[0].purpose == "PRECOMMITMENT"
                and freezes[0].sequence < selections[0].sequence
                and freezes[0].window == selections[0].window == protocol.window
                and self.selected_candidate is not None
                and selections[0].candidate_id == self.selected_candidate.candidate_id,
                "OOS_PROTOCOL_RECEIPTS_UNRESOLVED",
            )
        elif self.runs:
            require(
                len(freezes) == 1 and freezes[0].recorded_at == protocol.frozen_at,
                "OOS_PROTOCOL_RECEIPTS_UNRESOLVED",
            )
        require(
            bool(events)
            and events[-1] == self.journal.events[-1]
            and events[-1].kind is OOSEventKind.RESULT
            and events[-1].window == protocol.window,
            "OOS_RESULT_RECEIPT_UNRESOLVED",
        )
        require(
            self.created_at == events[-1].recorded_at,
            "OOS_RESULT_RECEIPT_TIME_MISMATCH",
        )
        access = tuple(
            e
            for e in self.journal.events
            if e.kind in (OOSEventKind.ACCESS, OOSEventKind.TRIAL)
            and e.window.overlaps(protocol.window)
        )
        canonical_access = tuple(
            e
            for e in access
            if e.kind is OOSEventKind.ACCESS
            and e.protocol_sha256 == protocol.content_sha256
            and e.purpose == "FINAL_HOLDOUT_EXECUTION"
            and self.selected_candidate is not None
            and e.candidate_id == self.selected_candidate.candidate_id
        )
        prior_results = tuple(e for e in events[:-1] if e.kind is OOSEventKind.RESULT)
        prior_terminal_access = any(
            access_event.sequence < result_event.sequence
            for access_event in canonical_access
            for result_event in prior_results
        )
        contaminated = (
            len(access) != len(canonical_access)
            or len(canonical_access) > 1
            or prior_terminal_access
            or len(selections) > 1
        )
        expected_contamination_reasons: set[str] = set()
        if (
            len(access) != len(canonical_access)
            or len(canonical_access) > 1
            or prior_terminal_access
        ):
            expected_contamination_reasons.add("HOLDOUT_PREVIOUSLY_ACCESSED_OR_REUSED")
        if len(selections) > 1:
            expected_contamination_reasons.add("SELECTION_CHANGED_AFTER_FREEZE")
        if len(freezes) == 1:
            freeze = freezes[0]
            if any(
                event.kind is OOSEventKind.SELECT
                and event.window.overlaps(protocol.window)
                and event.sequence < freeze.sequence
                and any(
                    access_event.kind is OOSEventKind.ACCESS
                    and access_event.window.overlaps(protocol.window)
                    and access_event.sequence < freeze.sequence
                    for access_event in self.journal.events
                )
                for event in self.journal.events
            ):
                expected_contamination_reasons.add("HOLDOUT_RESELECTION")
            if selections and selections[0].sequence <= freeze.sequence:
                expected_contamination_reasons.add("SELECTION_PRECEDES_FREEZE")
        declared_contamination_reasons = {
            reason
            for reason in self.reason_codes
            if is_contamination_failure_reason(reason)
        }
        require(
            declared_contamination_reasons == expected_contamination_reasons,
            "OOS_CONTAMINATION_REASON_MISMATCH",
        )
        protocol_receipts_resolved = (
            self.journal.declared_complete
            and len(freezes) == len(selections) == 1
            and freezes[0].recorded_at == protocol.frozen_at
            and freezes[0].purpose == "PRECOMMITMENT"
            and freezes[0].sequence < selections[0].sequence
            and freezes[0].window == selections[0].window == protocol.window
            and self.selected_candidate is not None
            and selections[0].candidate_id == self.selected_candidate.candidate_id
        )
        expected_contamination = (
            CheckOutcome.FAILED
            if contaminated
            else CheckOutcome.PASSED
            if protocol_receipts_resolved
            else CheckOutcome.INCONCLUSIVE
        )
        used_receipts = set()
        for run in self.runs:
            partition = next(
                (p for p in protocol.partitions if p.partition_id == run.partition_id),
                None,
            )
            b = run.backtest
            require(
                partition is not None
                and run.candidate in protocol.candidates
                and (b.venue, b.instrument_id, b.timeframe, b.environment)
                == (
                    protocol.window.venue,
                    protocol.window.instrument_id,
                    protocol.window.timeframe,
                    protocol.environment,
                ),
                "OOS_RUN_SCOPE_OR_PARTITION_MISMATCH",
            )
            assert partition is not None
            held = partition == protocol.partitions[-1]
            report = run.resolve_report()
            require(
                canonical_sha256(report.policy) == protocol.metrics_policy_sha256
                and report.input_sha256
                == canonical_sha256(
                    (
                        b.content_sha256,
                        report.policy,
                        b.dataset_sha256 if protocol.mark_equity else None,
                        b.manifest_sha256 if protocol.mark_equity else None,
                        (),
                    )
                ),
                "OOS_REPORT_POLICY_MISMATCH",
            )
            if held:
                require(
                    self.metrics
                    == tuple(
                        OOSMetricV2(
                            m.name,
                            m.state.value,
                            m.reason,
                            m.metric,
                            m.sample_count,
                            m.warnings,
                        )
                        for m in report.metrics
                    ),
                    "OOS_METRICS_REPORT_MISMATCH",
                )
            require(
                (b.period_start, b.period_end) == (partition.start, partition.end)
                and b.as_of <= partition.point_in_time_cutoff
                and (not held or run.candidate == self.selected_candidate),
                "OOS_RUN_WINDOW_CUTOFF_OR_SELECTION_MISMATCH",
            )
            for decision in json.loads(run.configuration)["input_request"]["decisions"]:
                at = datetime.fromisoformat(decision["decision_time"])
                require(
                    partition.start <= at < partition.end
                    and datetime.fromisoformat(decision["information_cutoff"]) <= at
                    and datetime.fromisoformat(decision["lookback_start"])
                    >= partition.start
                    - timedelta(
                        seconds=protocol.warmup_bars
                        * _TIMEFRAMES[protocol.window.timeframe]
                    ),
                    "OOS_RUN_DECISION_BOUNDARY_MISMATCH",
                )
            matches = tuple(
                e
                for e in events
                if e.kind is (OOSEventKind.RESULT if held else OOSEventKind.TRIAL)
                and e.candidate_id == run.candidate.candidate_id
                and e.window
                == OOSWindow(
                    protocol.window.venue,
                    protocol.window.instrument_id,
                    protocol.window.timeframe,
                    partition.start,
                    partition.end,
                )
                and run.request in e.evidence
                and run.metrics_report in e.evidence
                and ValidationArtifactReferenceV2(
                    "C-027", b.result_id, "3", b.content_sha256
                )
                in e.evidence
            )
            require(len(matches) == 1, "OOS_RUN_RECEIPT_UNRESOLVED")
            receipt = matches[0]
            require(
                receipt.sequence not in used_receipts
                and len(receipt.evidence) == 3
                and (
                    held
                    or (
                        receipt.purpose == partition.purpose.value
                        and freezes[0].sequence < receipt.sequence
                        and (
                            not selections or receipt.sequence < selections[0].sequence
                        )
                    )
                ),
                "OOS_RUN_RECEIPT_REUSED_OR_UNORDERED",
            )
            used_receipts.add(receipt.sequence)
            if held:
                assert receipt is not None
                require(
                    selections[0].sequence < receipt.sequence
                    and any(
                        e.kind is OOSEventKind.ACCESS
                        and e.purpose == "FINAL_HOLDOUT_EXECUTION"
                        and e.window == protocol.window
                        and e.candidate_id == run.candidate.candidate_id
                        and selections[0].sequence < e.sequence < receipt.sequence
                        for e in events
                    ),
                    "OOS_HOLDOUT_ACCESS_ORDER_MISMATCH",
                )
        if (
            self.selected_candidate is not None
            and protocol.selection_mode is OOSSelectionMode.VALIDATION_NET_PROFIT
        ):
            development = {
                (r.partition_id, r.candidate.candidate_id): r
                for r in self.runs
                if r.partition_id != protocol.partitions[-1].partition_id
            }
            require(
                set(development)
                == {
                    (p.partition_id, c.candidate_id)
                    for p in protocol.partitions[:2]
                    for c in protocol.candidates
                }
                and sum(e.kind is OOSEventKind.TRIAL for e in events)
                == len(development),
                "OOS_SELECTION_MATRIX_INCOMPLETE",
            )
            scores = []
            for candidate in protocol.candidates:
                metric = (
                    development[
                        protocol.partitions[1].partition_id, candidate.candidate_id
                    ]
                    .resolve_report()
                    .get("net_realized_profit")
                )
                require(
                    metric.state.value == "AVAILABLE" and metric.metric is not None,
                    "OOS_SELECTION_METRIC_UNAVAILABLE",
                )
                scores.append(
                    (
                        metric.metric.value.copy_negate(),
                        str(candidate.candidate_id),
                        candidate,
                    )
                )
            require(
                self.selected_candidate == min(scores, key=lambda s: (s[0], s[1]))[2],
                "OOS_SELECTION_CRITERION_MISMATCH",
            )
        require(
            self.contamination is expected_contamination,
            "OOS_CONTAMINATION_STATUS_MISMATCH",
        )
        held_runs = tuple(
            r
            for r in self.runs
            if r.partition_id == protocol.partitions[-1].partition_id
        )
        integrity_failure_declared = any(
            is_integrity_failure_reason(reason) for reason in self.reason_codes
        )
        unresolved_integrity_declared = any(
            reason != "INSUFFICIENT_OOS_TRADE_SAMPLE"
            and not is_integrity_failure_reason(reason)
            and not is_contamination_failure_reason(reason)
            for reason in self.reason_codes
        )
        expected_integrity = derive_integrity_status(
            failed=integrity_failure_declared,
            unresolved=unresolved_integrity_declared,
        )
        require(
            self.integrity is expected_integrity,
            "OOS_INTEGRITY_STATUS_MISMATCH",
        )
        expected_outcome = (
            OOSOutcome.FAILED
            if CheckOutcome.FAILED in (expected_contamination, expected_integrity)
            else OOSOutcome.INCONCLUSIVE
            if CheckOutcome.INCONCLUSIVE
            in (
                expected_contamination,
                expected_integrity,
                self.sample_sufficiency,
            )
            else OOSOutcome.OBSERVED
        )
        require(self.outcome is expected_outcome, "OOS_OUTCOME_STATUS_MISMATCH")
        require(
            events[-1].purpose
            == result_receipt_purpose(
                self.outcome,
                self.contamination,
                self.integrity,
                self.sample_sufficiency,
                self.reason_codes,
            ),
            "OOS_RESULT_RECEIPT_UNRESOLVED",
        )
        expected_terminal_evidence = (self.request_reference,) + (
            (
                ValidationArtifactReferenceV2(
                    "C-027",
                    held_runs[0].backtest.result_id,
                    "3",
                    held_runs[0].backtest.content_sha256,
                ),
                held_runs[0].metrics_report,
            )
            if held_runs
            else ()
        )
        require(
            events[-1].evidence == expected_terminal_evidence,
            "OOS_REQUEST_RECEIPT_MISMATCH",
        )

    def identity_payload(self) -> dict[str, object]:
        return payload(self, {"result_id", "content_sha256"})

    @classmethod
    def build(cls, **values) -> OOSResultV2:
        preimage = dict(
            values,
            method=METHOD,
            contract_id="C-071",
            schema_version="2",
            operating_mode=OperatingMode.BACKTEST,
        )
        sha = canonical_sha256(preimage)
        return cls(
            result_id=uuid5(NAMESPACE, "result:" + sha), content_sha256=sha, **values
        )
