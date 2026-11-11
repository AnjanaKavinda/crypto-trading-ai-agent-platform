"""Additive C-071 schema 2; observed OOS evidence, never qualification authority."""

from __future__ import annotations

from dataclasses import dataclass, field, fields
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid5

from trading_platform_api.config import DeploymentEnvironment, OperatingMode
from trading_platform_api.contracts.serialization import canonical_sha256
from trading_platform_api.market_data.ohlcv import _TIMEFRAMES
from trading_platform_api.validation.contracts import (
    CheckOutcome,
    DataPartition,
    MetricValue,
    PartitionPurpose,
)
from trading_platform_api.validation.contracts_v2 import ValidationArtifactReferenceV2
from trading_platform_api.validation.contracts_v3 import BacktestResultV3

METHOD = "spot-oos-observation-v1"
NAMESPACE = uuid5(NAMESPACE_URL, "trading-platform:C-071:2:spot-oos-v1")
MAX_EVENTS = 512
MAX_CANDIDATES = 16


def require(condition: bool, reason: str) -> None:
    if not condition:
        raise ValueError(reason)


def text(value: str) -> None:
    require(
        type(value) is str and 0 < len(value) <= 256 and value == value.strip(),
        "INVALID_OOS_TEXT",
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
        # A new venue, timeframe or data revision does not erase knowledge of
        # the same instrument's held-out market period.
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
            all(p.point_in_time_cutoff <= holdout.start for p in self.partitions[:2]),
            "DEVELOPMENT_CUTOFF_REACHES_HOLDOUT",
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

    def __post_init__(self) -> None:
        require(
            type(self.partition_id) is UUID and type(self.backtest) is BacktestResultV3,
            "INVALID_OOS_RUN_BINDING",
        )
        ref(self.metrics_report, "SPOT_PERFORMANCE_REPORT", "1")


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
    selected_candidate: OOSCandidateV2 | None
    runs: tuple[OOSRunBindingV2, ...]
    metrics: tuple[OOSMetricV2, ...]
    contamination: CheckOutcome
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
        require(
            type(self.sample_size) is int
            and self.sample_size >= 0
            and type(self.outcome) is OOSOutcome,
            "INVALID_OOS_SAMPLE_OR_OUTCOME",
        )
        require(
            type(self.contamination) is CheckOutcome
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
        require(
            type(self.reason_codes) is tuple and type(self.warnings) is tuple,
            "INVALID_OOS_REASONS",
        )
        for value in self.reason_codes + self.warnings:
            text(value)
        if self.outcome is OOSOutcome.OBSERVED:
            require(
                self.contamination is CheckOutcome.PASSED
                and self.sample_sufficiency is CheckOutcome.PASSED
                and self.sample_size >= self.protocol.minimum_trades
                and self.selected_candidate is not None
                and not self.reason_codes,
                "OBSERVED_OOS_REQUIRES_VALID_EVIDENCE",
            )
            held = tuple(
                r
                for r in self.runs
                if r.partition_id == self.protocol.partitions[-1].partition_id
            )
            require(
                len(held) == 1
                and self.sample_size == len(held[0].backtest.simulated_trade_ids),
                "OOS_SAMPLE_BINDING_MISMATCH",
            )
        else:
            require(bool(self.reason_codes), "MISSING_OOS_FAILURE_REASON")
        require(
            self.content_sha256 == canonical_sha256(self.identity_payload())
            and self.result_id == uuid5(NAMESPACE, "result:" + self.content_sha256),
            "OOS_RESULT_DIGEST_MISMATCH",
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
