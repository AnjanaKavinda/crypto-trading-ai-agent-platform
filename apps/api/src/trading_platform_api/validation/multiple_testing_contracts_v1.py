"""C-105 schema 1: deterministic, observation-only multiple-testing assessment."""

from __future__ import annotations

from dataclasses import dataclass, field, fields
from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from uuid import NAMESPACE_URL, UUID, uuid5

from trading_platform_api.contracts.serialization import canonical_sha256
from trading_platform_api.risk import ContractReference
from trading_platform_api.validation.contracts import PartitionPurpose
from trading_platform_api.validation.contracts_v2 import ValidationArtifactReferenceV2
from trading_platform_api.validation.oos_contracts_v2 import (
    OOSEventKind,
    OOSJournalEvent,
    OOSJournalSnapshot,
    OOSProtocolV2,
    OOSResultV2,
    OOSSelectionMode,
    OOSWindow,
)

METHOD = "spot-multiple-testing-observation-v1"
METHOD_VERSION = "1"
IDENTITY_METHOD = "spot-multiple-testing-identity-v1"
_NAMESPACE = uuid5(
    NAMESPACE_URL, "trading-platform:C-105:1:spot-multiple-testing-identity-v1"
)
_CORRECTION_STATUS = "NOT_APPLIED"
_INTERPRETATION = "UNADJUSTED_DESCRIPTIVE_ONLY"
_EVENT_EVIDENCE_TYPES = {
    ("C-027", "3"),
    ("SPOT_PERFORMANCE_REPORT", "1"),
    ("SPOT_OOS_REQUEST", "1"),
}


class MultipleTestingOutcome(StrEnum):
    OBSERVED = "OBSERVED"
    INCONCLUSIVE = "INCONCLUSIVE"
    FAILED = "FAILED"


@dataclass(frozen=True, slots=True)
class CandidateHypothesisMapping:
    candidate_id: UUID
    hypothesis_refs: tuple[ContractReference, ...]

    def __post_init__(self) -> None:
        if type(self.candidate_id) is not UUID or type(self.hypothesis_refs) is not tuple:
            raise ValueError("Invalid C-105 candidate/hypothesis mapping.")
        if any(
            type(item) is not ContractReference
            or item.contract_id != "C-048"
            or item.schema_version != "1"
            for item in self.hypothesis_refs
        ):
            raise ValueError(
                "C-105 hypothesis references must be typed C-048 references."
            )
        if len(set(self.hypothesis_refs)) != len(self.hypothesis_refs):
            raise ValueError("C-105 hypothesis references must be unique.")
        if not self.hypothesis_refs:
            raise ValueError("C-105 candidates require at least one hypothesis.")


@dataclass(frozen=True, slots=True)
class CandidateConfiguration:
    candidate_id: UUID
    strategy_ref: ValidationArtifactReferenceV2
    configuration_ref: ValidationArtifactReferenceV2
    cost_ref: ValidationArtifactReferenceV2
    cost_adapter_ref: ValidationArtifactReferenceV2
    execution_policy_sha256: str

    def __post_init__(self) -> None:
        if (
            type(self.candidate_id) is not UUID
            or type(self.strategy_ref) is not ValidationArtifactReferenceV2
            or self.strategy_ref.artifact_type != "C-021"
            or type(self.configuration_ref) is not ValidationArtifactReferenceV2
            or self.configuration_ref.artifact_type != "PARAMETER_SET"
            or type(self.cost_ref) is not ValidationArtifactReferenceV2
            or self.cost_ref.artifact_type != "C-027"
            or type(self.cost_adapter_ref) is not ValidationArtifactReferenceV2
            or type(self.execution_policy_sha256) is not str
            or len(self.execution_policy_sha256) != 64
            or any(
                character not in "0123456789abcdef"
                for character in self.execution_policy_sha256
            )
        ):
            raise ValueError("Invalid C-105 candidate/configuration binding.")


@dataclass(frozen=True, slots=True)
class MultipleTestingCounts:
    unique_strategy_count: int
    unique_configuration_count: int
    unique_hypothesis_count: int
    protocol_count: int
    development_trial_count: int
    held_out_result_count: int

    def __post_init__(self) -> None:
        if any(
            type(getattr(self, field.name)) is not int or getattr(self, field.name) < 0
            for field in fields(self)
        ):
            raise ValueError("C-105 counts must be nonnegative integers.")
        if self.protocol_count != 1:
            raise ValueError("C-105 describes exactly one OOS protocol.")


@dataclass(frozen=True, slots=True)
class BestValidationObservation:
    metric_name: str | None
    metric_value: Decimal | None
    evidence_reference: ValidationArtifactReferenceV2 | None
    unavailable_reason: str | None

    def __post_init__(self) -> None:
        available = self.metric_name is not None
        if available:
            if (
                type(self.metric_name) is not str
                or not self.metric_name
                or type(self.metric_value) is not Decimal
                or not self.metric_value.is_finite()
                or type(self.evidence_reference) is not ValidationArtifactReferenceV2
                or self.evidence_reference.artifact_type != "SPOT_PERFORMANCE_REPORT"
                or self.evidence_reference.version != "1"
                or self.unavailable_reason is not None
            ):
                raise ValueError("Invalid available C-105 validation observation.")
        elif (
            self.metric_value is not None
            or self.evidence_reference is not None
            or type(self.unavailable_reason) is not str
            or not self.unavailable_reason
        ):
            raise ValueError("Unavailable C-105 observation must be explicit.")


def _utc(value: datetime) -> datetime:
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("C-105 timestamp must be timezone-aware.")
    return value.astimezone(UTC)


def _payload(
    value: SpotMultipleTestingPlanV1 | MultipleTestingAssessment,
    omitted: set[str],
) -> dict[str, object]:
    return {
        item.name: getattr(value, item.name)
        for item in fields(value)
        if item.name not in omitted
    }


@dataclass(frozen=True, slots=True)
class SpotMultipleTestingPlanV1:
    """Immutable pre-access commitment to one finite C-071v2 candidate search."""

    plan_id: UUID
    content_sha256: str
    journal_id: UUID
    authority: ValidationArtifactReferenceV2
    protocol: OOSProtocolV2
    journal_prefix_length: int
    journal_prefix_sha256: str
    candidate_configurations: tuple[CandidateConfiguration, ...]
    candidate_hypothesis_map: tuple[CandidateHypothesisMapping, ...]
    selection_policy: OOSSelectionMode
    window: OOSWindow
    metrics_policy_sha256: str
    development_partition_ids: tuple[UUID, ...]
    validation_partition_id: UUID
    held_out_partition_id: UUID
    metric_name: str
    frozen_at: datetime
    correction_status: str = _CORRECTION_STATUS
    interpretation: str = _INTERPRETATION
    method: str = METHOD
    method_version: str = METHOD_VERSION
    identity_method: str = IDENTITY_METHOD
    contract_id: str = field(default="C-105", init=False)
    schema_version: str = field(default="1", init=False)

    def __post_init__(self) -> None:
        if (
            type(self.plan_id) is not UUID
            or type(self.journal_id) is not UUID
            or type(self.authority) is not ValidationArtifactReferenceV2
            or type(self.protocol) is not OOSProtocolV2
            or self.protocol.journal_id != self.journal_id
            or self.protocol.authority != self.authority
            or type(self.candidate_configurations) is not tuple
            or type(self.candidate_hypothesis_map) is not tuple
            or any(
                type(item) is not CandidateConfiguration
                for item in self.candidate_configurations
            )
            or any(
                type(item) is not CandidateHypothesisMapping
                for item in self.candidate_hypothesis_map
            )
            or any(not item.hypothesis_refs for item in self.candidate_hypothesis_map)
            or type(self.selection_policy) is not OOSSelectionMode
            or type(self.window) is not OOSWindow
            or self.window != self.protocol.window
            or type(self.metrics_policy_sha256) is not str
            or len(self.metrics_policy_sha256) != 64
            or any(
                character not in "0123456789abcdef"
                for character in self.metrics_policy_sha256
            )
            or type(self.development_partition_ids) is not tuple
            or type(self.validation_partition_id) is not UUID
            or type(self.held_out_partition_id) is not UUID
            or type(self.metric_name) is not str
            or not self.metric_name
        ):
            raise ValueError("Invalid C-105 frozen search plan.")
        candidates = self.protocol.candidates
        expected = tuple(
            CandidateConfiguration(
                item.candidate_id,
                item.strategy,
                item.parameters,
                item.costs,
                item.cost_adapter,
                item.execution_policy_sha256,
            )
            for item in candidates
        )
        if (
            self.candidate_configurations != expected
            or tuple(item.candidate_id for item in self.candidate_hypothesis_map)
            != tuple(item.candidate_id for item in candidates)
            or len({item.candidate_id for item in self.candidate_hypothesis_map})
            != len(candidates)
            or self.development_partition_ids
            != tuple(item.partition_id for item in self.protocol.partitions[:-1])
            or self.validation_partition_id
            != next(
                item.partition_id
                for item in self.protocol.partitions
                if item.purpose is PartitionPurpose.VALIDATION
            )
            or self.held_out_partition_id != self.protocol.partitions[-1].partition_id
            or self.selection_policy is not self.protocol.selection_mode
            or self.metrics_policy_sha256 != self.protocol.metrics_policy_sha256
        ):
            raise ValueError("C-105 plan does not freeze the exact protocol search space.")
        object.__setattr__(self, "frozen_at", _utc(self.frozen_at))
        if (
            self.correction_status != _CORRECTION_STATUS
            or self.interpretation != _INTERPRETATION
            or self.method != METHOD
            or self.method_version != METHOD_VERSION
            or self.identity_method != IDENTITY_METHOD
            or self.contract_id != "C-105"
            or self.schema_version != "1"
            or self.frozen_at < self.protocol.frozen_at
            or type(self.journal_prefix_length) is not int
            or self.journal_prefix_length < 1
            or type(self.journal_prefix_sha256) is not str
            or len(self.journal_prefix_sha256) != 64
            or any(
                character not in "0123456789abcdef"
                for character in self.journal_prefix_sha256
            )
        ):
            raise ValueError("Unsupported C-105 plan semantics or chronology.")
        expected_digest = canonical_sha256(
            _payload(self, {"plan_id", "content_sha256"})
        )
        if (
            self.content_sha256 != expected_digest
            or self.plan_id != uuid5(_NAMESPACE, "plan:" + expected_digest)
        ):
            raise ValueError("C-105 plan identity mismatch.")

    @classmethod
    def build(
        cls,
        *,
        journal_id,
        authority,
        protocol,
        journal_prefix_length,
        journal_prefix_sha256,
        candidate_hypothesis_map,
        metric_name,
        frozen_at,
    ):
        configurations = tuple(
            CandidateConfiguration(
                item.candidate_id,
                item.strategy,
                item.parameters,
                item.costs,
                item.cost_adapter,
                item.execution_policy_sha256,
            )
            for item in protocol.candidates
        )
        hypotheses = candidate_hypothesis_map or tuple(
            CandidateHypothesisMapping(item.candidate_id, ()) for item in protocol.candidates
        )
        values = dict(
            journal_id=journal_id,
            authority=authority,
            protocol=protocol,
            journal_prefix_length=journal_prefix_length,
            journal_prefix_sha256=journal_prefix_sha256,
            candidate_configurations=configurations,
            candidate_hypothesis_map=hypotheses,
            selection_policy=protocol.selection_mode,
            window=protocol.window,
            metrics_policy_sha256=protocol.metrics_policy_sha256,
            development_partition_ids=tuple(
                p.partition_id for p in protocol.partitions[:-1]
            ),
            validation_partition_id=next(
                p.partition_id
                for p in protocol.partitions
                if p.purpose is PartitionPurpose.VALIDATION
            ),
            held_out_partition_id=protocol.partitions[-1].partition_id,
            metric_name=metric_name,
            frozen_at=frozen_at,
            correction_status=_CORRECTION_STATUS,
            interpretation=_INTERPRETATION,
            method=METHOD,
            method_version=METHOD_VERSION,
            identity_method=IDENTITY_METHOD,
            contract_id="C-105", schema_version="1",
        )
        digest = canonical_sha256(values)
        return cls(
            plan_id=uuid5(_NAMESPACE, "plan:" + digest),
            content_sha256=digest,
            **{
                key: value
                for key, value in values.items()
                if key not in {"contract_id", "schema_version"}
            },
        )


def assessment_event_is_valid(
    event: OOSJournalEvent,
    *,
    plan: SpotMultipleTestingPlanV1,
    oos_result: OOSResultV2,
    seen_event_digests: set[str],
) -> bool:
    protocol_candidates = {
        candidate.candidate_id for candidate in plan.protocol.candidates
    }
    if (
        event.recorded_at < plan.frozen_at
        or event.content_sha256 in seen_event_digests
        or (
            event.protocol_sha256 == plan.protocol.content_sha256
            and event.candidate_id is not None
            and event.candidate_id not in protocol_candidates
        )
    ):
        return False
    evidence_types = tuple(
        (reference.artifact_type, reference.version) for reference in event.evidence
    )
    if (
        len(evidence_types) != len(set(evidence_types))
        or not set(evidence_types) <= _EVENT_EVIDENCE_TYPES
    ):
        return False
    allowed_evidence: tuple[set[tuple[str, str]], ...]
    if event.kind in (OOSEventKind.ACCESS, OOSEventKind.SELECT):
        allowed_evidence = (set(),)
    elif event.kind is OOSEventKind.TRIAL:
        allowed_evidence = (
            set(),
            {
                ("C-027", "3"),
                ("SPOT_PERFORMANCE_REPORT", "1"),
                ("SPOT_OOS_REQUEST", "1"),
            },
        )
    elif event.kind is OOSEventKind.RESULT:
        allowed_evidence = (
            {("SPOT_OOS_REQUEST", "1")},
            {
                ("C-027", "3"),
                ("SPOT_PERFORMANCE_REPORT", "1"),
                ("SPOT_OOS_REQUEST", "1"),
            },
        )
    else:
        allowed_evidence = (set(),)
    if set(evidence_types) not in allowed_evidence:
        return False
    if ("C-027", "3") in evidence_types:
        matching = []
        for run in oos_result.runs:
            partition = next(
                (
                    part
                    for part in plan.protocol.partitions
                    if part.partition_id == run.partition_id
                ),
                None,
            )
            if partition is None:
                continue
            run_window = OOSWindow(
                plan.window.venue,
                plan.window.instrument_id,
                plan.window.timeframe,
                partition.start,
                partition.end,
            )
            held = partition.partition_id == plan.held_out_partition_id
            backtest_ref = ValidationArtifactReferenceV2(
                "C-027", run.backtest.result_id, "3", run.backtest.content_sha256
            )
            expected_refs = (
                (run.request, backtest_ref, run.metrics_report)
                if held
                else (backtest_ref, run.metrics_report, run.request)
            )
            expected_kind = OOSEventKind.RESULT if held else OOSEventKind.TRIAL
            if (
                event.kind is expected_kind
                and event.window == run_window
                and event.candidate_id == run.candidate.candidate_id
                and event.evidence == expected_refs
            ):
                matching.append(run)
        if len(matching) != 1:
            return False
    elif event.kind is OOSEventKind.RESULT and event.evidence != (
        oos_result.request_reference,
    ):
        return False
    return True


@dataclass(frozen=True, slots=True)
class MultipleTestingAssessment:
    """C-105 schema 1 observation of exact supplied C-071 journal/result evidence."""

    result_id: UUID
    content_sha256: str
    plan: SpotMultipleTestingPlanV1
    oos_result: OOSResultV2
    outcome: MultipleTestingOutcome
    counts: MultipleTestingCounts
    selected_candidate_id: UUID | None
    rejected_candidate_ids: tuple[UUID, ...]
    best_validation_observation: BestValidationObservation
    observed_events: tuple[OOSJournalEvent, ...]
    preserved_terminal_attempts: tuple[OOSJournalEvent, ...]
    journal_tail: tuple[OOSJournalEvent, ...] = ()
    correction_status: str = _CORRECTION_STATUS
    interpretation: str = _INTERPRETATION
    method: str = METHOD
    method_version: str = METHOD_VERSION
    identity_method: str = IDENTITY_METHOD
    contract_id: str = field(default="C-105", init=False)
    schema_version: str = field(default="1", init=False)

    def __post_init__(self) -> None:
        if (
            type(self.result_id) is not UUID
            or type(self.plan) is not SpotMultipleTestingPlanV1
            or type(self.oos_result) is not OOSResultV2
            or self.oos_result.protocol != self.plan.protocol
            or type(self.outcome) is not MultipleTestingOutcome
            or type(self.counts) is not MultipleTestingCounts
            or type(self.best_validation_observation)
            is not BestValidationObservation
            or type(self.observed_events) is not tuple
            or type(self.preserved_terminal_attempts) is not tuple
            or type(self.journal_tail) is not tuple
            or type(self.rejected_candidate_ids) is not tuple
        ):
            raise ValueError("Invalid C-105 assessment binding.")
        if (
            self.correction_status != _CORRECTION_STATUS
            or self.interpretation != _INTERPRETATION
            or self.method != METHOD
            or self.method_version != METHOD_VERSION
            or self.identity_method != IDENTITY_METHOD
            or self.contract_id != "C-105"
            or self.schema_version != "1"
        ):
            raise ValueError("Unsupported C-105 assessment semantics.")
        events = self.oos_result.journal.events
        if any(type(event) is not OOSJournalEvent for event in self.journal_tail):
            raise ValueError("C-105 supplied journal tail is invalid.")
        complete_journal = OOSJournalSnapshot(
            self.oos_result.journal.journal_id,
            self.oos_result.journal.authority,
            self.oos_result.journal.declared_complete,
            (*events, *self.journal_tail),
        )
        all_events = complete_journal.events
        prefix = events[: self.plan.journal_prefix_length]
        if (
            self.oos_result.journal.journal_id != self.plan.journal_id
            or self.oos_result.journal.authority != self.plan.authority
            or len(events) < self.plan.journal_prefix_length
            or canonical_sha256(tuple(e.content_sha256 for e in prefix))
            != self.plan.journal_prefix_sha256
            or any(e.recorded_at > self.plan.frozen_at for e in prefix)
        ):
            raise ValueError("C-105 result does not extend its frozen pre-access prefix.")
        freeze = tuple(
            e
            for e in prefix
            if e.kind is OOSEventKind.FREEZE
            and e.protocol_sha256 == self.plan.protocol.content_sha256
        )
        if (
            len(freeze) != 1
            or freeze[0].recorded_at != self.plan.protocol.frozen_at
            or any(
                e.protocol_sha256 == self.plan.protocol.content_sha256
                and e.kind
                in (OOSEventKind.ACCESS, OOSEventKind.TRIAL, OOSEventKind.RESULT)
                for e in prefix
            )
            or any(
                e.kind in (OOSEventKind.ACCESS, OOSEventKind.TRIAL)
                and e.window.overlaps(self.plan.window)
                for e in prefix
            )
        ):
            raise ValueError("C-105 plan was not frozen before data access.")
        held_out_window = OOSWindow(
            self.plan.window.venue,
            self.plan.window.instrument_id,
            self.plan.window.timeframe,
            self.plan.protocol.partitions[-1].start,
            self.plan.protocol.partitions[-1].end,
        )
        expected_events = tuple(
            e
            for e in all_events[self.plan.journal_prefix_length :]
            if e.protocol_sha256 == self.plan.protocol.content_sha256
            or (
                e.kind in (OOSEventKind.ACCESS, OOSEventKind.TRIAL)
                and e.window.overlaps(held_out_window)
            )
        )
        if self.observed_events != expected_events:
            raise ValueError("C-105 event snapshot mismatch.")
        seen_event_digests: set[str] = set()
        invalid_event_evidence = False
        for event in self.observed_events:
            if not assessment_event_is_valid(
                event,
                plan=self.plan,
                oos_result=self.oos_result,
                seen_event_digests=seen_event_digests,
            ):
                invalid_event_evidence = True
            seen_event_digests.add(event.content_sha256)
        results = tuple(
            e
            for e in self.observed_events
            if e.protocol_sha256 == self.plan.protocol.content_sha256
            and e.kind is OOSEventKind.RESULT
        )
        terminal_results = tuple(
            e
            for e in events[self.plan.journal_prefix_length :]
            if e.protocol_sha256 == self.plan.protocol.content_sha256
            and e.kind is OOSEventKind.RESULT
        )
        tail_failure = any(
            e.protocol_sha256 == self.plan.protocol.content_sha256
            or (
                e.kind in (OOSEventKind.ACCESS, OOSEventKind.TRIAL)
                and e.window.overlaps(held_out_window)
            )
            for e in self.journal_tail
        )
        expected_outcome = (
            MultipleTestingOutcome.FAILED
            if tail_failure or invalid_event_evidence
            else MultipleTestingOutcome(self.oos_result.outcome.value)
        )
        if (
            self.preserved_terminal_attempts
            != tuple(
                e
                for e in self.observed_events
                if e.kind
                in (OOSEventKind.ACCESS, OOSEventKind.TRIAL, OOSEventKind.RESULT)
            )
            or len(terminal_results) != 1
            or terminal_results[0] != self.oos_result.journal.events[-1]
            or results.count(terminal_results[0]) != 1
            or self.outcome is not expected_outcome
        ):
            raise ValueError("C-105 terminal attempt/result closure failure.")
        selected = self.oos_result.selected_candidate
        if (selected.candidate_id if selected else None) != self.selected_candidate_id:
            raise ValueError("C-105 selected candidate mismatch.")
        expected_rejected = tuple(
            c.candidate_id
            for c in self.plan.protocol.candidates
            if selected is not None and c.candidate_id != selected.candidate_id
        )
        if self.rejected_candidate_ids != expected_rejected:
            raise ValueError("C-105 rejected candidate set mismatch.")
        development_windows = {
            OOSWindow(
                self.plan.window.venue,
                self.plan.window.instrument_id,
                self.plan.window.timeframe,
                partition.start,
                partition.end,
            )
            for partition in self.plan.protocol.partitions[:-1]
        }
        dev_trials = sum(
            event.kind is OOSEventKind.TRIAL and event.window in development_windows
            for event in self.observed_events
        )
        held_runs = tuple(
            run
            for run in self.oos_result.runs
            if run.partition_id == self.plan.held_out_partition_id
        )
        hypotheses = {
            ref
            for mapping in self.plan.candidate_hypothesis_map
            for ref in mapping.hypothesis_refs
        }
        strategies = {c.strategy for c in self.plan.protocol.candidates}
        configurations = {
            (c.parameters, c.costs, c.cost_adapter, c.execution_policy_sha256)
            for c in self.plan.protocol.candidates
        }
        expected_counts = MultipleTestingCounts(
            len(strategies),
            len(configurations),
            len(hypotheses),
            1,
            dev_trials,
            len(held_runs),
        )
        if self.counts != expected_counts:
            raise ValueError("C-105 assessment accounting mismatch.")
        if self.plan.selection_policy is OOSSelectionMode.FIXED:
            if self.best_validation_observation != BestValidationObservation(
                None, None, None, "FIXED_PROTOCOL_HAS_NO_OPTIMIZATION_SELECTION"
            ):
                raise ValueError(
                    "FIXED C-105 assessment must mark best validation unavailable."
                )
        else:
            from json import loads

            from trading_platform_api.lineage.codec import decode_value
            from trading_platform_api.validation.spot_metrics import (
                MetricState,
                SpotPerformanceReport,
            )

            candidates = []
            for run in self.oos_result.runs:
                if run.partition_id != self.plan.validation_partition_id:
                    continue
                report = decode_value(SpotPerformanceReport, loads(run.report_document))
                metric = report.get(self.plan.metric_name)
                if metric.state is MetricState.AVAILABLE and metric.metric is not None:
                    candidates.append(
                        (
                            metric.metric.value,
                            str(run.candidate.candidate_id),
                            run.metrics_report,
                        )
                    )
            if candidates:
                expected_value, _, expected_ref = sorted(
                    candidates, key=lambda item: (-item[0], item[1])
                )[0]
                if (
                    self.best_validation_observation.metric_name
                    != self.plan.metric_name
                    or self.best_validation_observation.metric_value != expected_value
                    or self.best_validation_observation.evidence_reference
                    != expected_ref
                ):
                    raise ValueError("C-105 best validation observation is not exact.")
            elif self.best_validation_observation != BestValidationObservation(
                None, None, None, "NO_VALID_DEVELOPMENT_METRIC"
            ):
                raise ValueError(
                    "C-105 best validation observation must be unavailable."
                )
        digest = canonical_sha256(_payload(self, {"result_id", "content_sha256"}))
        if self.content_sha256 != digest or self.result_id != uuid5(
            _NAMESPACE, "result:" + digest
        ):
            raise ValueError("C-105 assessment identity mismatch.")

    @property
    def attempted_trial_count(self) -> int:
        """Recorded C-071 TRIAL events; not a statistical sample size."""
        return sum(event.kind is OOSEventKind.TRIAL for event in self.observed_events)

    @classmethod
    def build(
        cls,
        *,
        plan,
        oos_result,
        outcome,
        counts,
        selected_candidate_id,
        rejected_candidate_ids,
        best_validation_observation,
        journal_tail=(),
    ):
        held_out_window = OOSWindow(
            plan.window.venue,
            plan.window.instrument_id,
            plan.window.timeframe,
            plan.protocol.partitions[-1].start,
            plan.protocol.partitions[-1].end,
        )
        supplied_events = (
            *oos_result.journal.events,
            *journal_tail,
        )
        events = tuple(
            e
            for e in supplied_events[plan.journal_prefix_length :]
            if e.protocol_sha256 == plan.protocol.content_sha256
            or (
                e.kind in (OOSEventKind.ACCESS, OOSEventKind.TRIAL)
                and e.window.overlaps(held_out_window)
            )
        )
        values = dict(
            plan=plan,
            oos_result=oos_result,
            outcome=outcome,
            counts=counts,
            selected_candidate_id=selected_candidate_id,
            rejected_candidate_ids=rejected_candidate_ids,
            best_validation_observation=best_validation_observation,
            observed_events=events,
            preserved_terminal_attempts=tuple(
                e
                for e in events
                if e.kind
                in (OOSEventKind.ACCESS, OOSEventKind.TRIAL, OOSEventKind.RESULT)
            ),
            journal_tail=journal_tail,
            correction_status=_CORRECTION_STATUS,
            interpretation=_INTERPRETATION,
            method=METHOD,
            method_version=METHOD_VERSION,
            identity_method=IDENTITY_METHOD,
            contract_id="C-105",
            schema_version="1",
        )
        digest = canonical_sha256(values)
        return cls(
            result_id=uuid5(_NAMESPACE, "result:" + digest),
            content_sha256=digest,
            **{
                key: value
                for key, value in values.items()
                if key not in {"contract_id", "schema_version"}
            },
        )


# Backwards-compatible type name for the closed C-105 lineage dispatch.
SpotMultipleTestingResultV1 = MultipleTestingAssessment
