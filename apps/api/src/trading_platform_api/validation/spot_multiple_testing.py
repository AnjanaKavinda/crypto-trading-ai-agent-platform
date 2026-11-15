"""C-105 deterministic observer over one issued C-071v2 OOS result."""

from __future__ import annotations

import json
from decimal import Decimal

from trading_platform_api.contracts.serialization import canonical_sha256
from trading_platform_api.lineage.codec import decode_value
from trading_platform_api.risk import ContractReference
from trading_platform_api.validation.contracts_v2 import (
    ValidationArtifactReferenceV2,
)
from trading_platform_api.validation.multiple_testing_contracts_v1 import (
    BestValidationObservation,
    CandidateHypothesisMapping,
    MultipleTestingAssessment,
    MultipleTestingCounts,
    MultipleTestingOutcome,
    SpotMultipleTestingPlanV1,
    assessment_event_is_valid,
)
from trading_platform_api.validation.oos_contracts_v2 import (
    OOSEventKind,
    OOSProtocolV2,
    OOSSelectionMode,
    utc,
)
from trading_platform_api.validation.spot_metrics import (
    MetricState,
    SpotPerformanceReport,
)
from trading_platform_api.validation.spot_oos import (
    OOSResearchJournal,
    SpotOOSBundle,
    _window,
    resolve_spot_oos_result,
)


def freeze_spot_multiple_testing_plan(
    *,
    journal: OOSResearchJournal,
    protocol: OOSProtocolV2,
    candidate_hypothesis_map: tuple[CandidateHypothesisMapping, ...] | None = None,
    hypothesis_refs: tuple[ContractReference, ...] = (),
    metric_name: str = "net_realized_profit",
) -> SpotMultipleTestingPlanV1:
    """Freeze C-105 policy and finite candidate/configuration space pre-access."""
    if (
        type(journal) is not OOSResearchJournal
        or type(protocol) is not OOSProtocolV2
        or journal._protocols.get(protocol.content_sha256) != protocol
        or (journal.snapshot.journal_id, journal.snapshot.authority)
        != (protocol.journal_id, protocol.authority)
    ):
        raise ValueError("MULTIPLE_TESTING_PROTOCOL_OR_JOURNAL_UNRESOLVED")
    if protocol.content_sha256 in journal._multiple_testing_plans:
        raise ValueError("MULTIPLE_TESTING_PLAN_ALREADY_FROZEN")
    if metric_name != "net_realized_profit":
        raise ValueError("MULTIPLE_TESTING_METRIC_POLICY_INVALID")
    if type(hypothesis_refs) is not tuple or any(
        type(ref) is not ContractReference
        or ref.contract_id != "C-048"
        or ref.schema_version != "1"
        for ref in hypothesis_refs
    ):
        raise ValueError("MULTIPLE_TESTING_HYPOTHESIS_REFERENCE_INVALID")
    if len(set(hypothesis_refs)) != len(hypothesis_refs):
        raise ValueError("MULTIPLE_TESTING_HYPOTHESIS_REFERENCE_DUPLICATE")
    if candidate_hypothesis_map is None and not hypothesis_refs:
        raise ValueError("MULTIPLE_TESTING_HYPOTHESES_REQUIRED")
    candidates = protocol.candidates
    if candidate_hypothesis_map is None:
        candidate_hypothesis_map = tuple(
            CandidateHypothesisMapping(candidate.candidate_id, hypothesis_refs)
            for candidate in candidates
        )
    if (
        type(candidate_hypothesis_map) is not tuple
        or any(
            type(item) is not CandidateHypothesisMapping
            for item in candidate_hypothesis_map
        )
        or tuple(item.candidate_id for item in candidate_hypothesis_map)
        != tuple(item.candidate_id for item in candidates)
    ):
        raise ValueError("MULTIPLE_TESTING_CANDIDATE_HYPOTHESIS_MAPPING_MISMATCH")
    scopes = (
        protocol.window,
        *(_window(protocol, partition) for partition in protocol.partitions),
    )
    for event in journal.snapshot.events:
        if event.protocol_sha256 == protocol.content_sha256 and event.kind in (
            OOSEventKind.ACCESS, OOSEventKind.TRIAL, OOSEventKind.RESULT
        ):
            raise ValueError("MULTIPLE_TESTING_PLAN_AFTER_PROTOCOL_ACCESS")
        if event.kind in (OOSEventKind.ACCESS, OOSEventKind.TRIAL) and any(
            event.window.overlaps(scope) for scope in scopes
        ):
            raise ValueError("MULTIPLE_TESTING_PLAN_AFTER_SCOPED_ACCESS")
    freeze_events = tuple(
        event for event in journal.snapshot.events
        if event.kind is OOSEventKind.FREEZE
        and event.protocol_sha256 == protocol.content_sha256
        and event.recorded_at == protocol.frozen_at
    )
    if len(freeze_events) != 1:
        raise ValueError("MULTIPLE_TESTING_FREEZE_RECEIPT_INVALID")
    frozen_at = utc(journal._clock())
    events = journal.snapshot.events
    if events and events[-1].recorded_at > frozen_at:
        raise ValueError("MULTIPLE_TESTING_PLAN_CHRONOLOGY_MISMATCH")
    mapped_hypotheses = {
        ref
        for mapping in candidate_hypothesis_map
        for ref in mapping.hypothesis_refs
    }
    if not mapped_hypotheses:
        raise ValueError("MULTIPLE_TESTING_HYPOTHESES_REQUIRED")
    if hypothesis_refs and mapped_hypotheses != set(hypothesis_refs):
        raise ValueError("MULTIPLE_TESTING_HYPOTHESIS_MAPPING_UNDECLARED")
    plan = SpotMultipleTestingPlanV1.build(
        journal_id=journal.snapshot.journal_id,
        authority=journal.snapshot.authority,
        protocol=protocol,
        journal_prefix_length=len(events),
        journal_prefix_sha256=canonical_sha256(tuple(e.content_sha256 for e in events)),
        candidate_hypothesis_map=candidate_hypothesis_map,
        metric_name=metric_name,
        frozen_at=frozen_at,
    )
    journal._multiple_testing_plans[protocol.content_sha256] = plan
    return plan


def _best_development_observation(plan, result) -> BestValidationObservation:
    if plan.selection_policy is OOSSelectionMode.FIXED:
        return BestValidationObservation(
            None, None, None, "FIXED_PROTOCOL_HAS_NO_OPTIMIZATION_SELECTION"
        )
    observations: list[
        tuple[Decimal, str, ValidationArtifactReferenceV2]
    ] = []
    for run in result.runs:
        if run.partition_id != plan.validation_partition_id:
            continue
        report = decode_value(SpotPerformanceReport, json.loads(run.report_document))
        metric = report.get(plan.metric_name)
        if metric.state is MetricState.AVAILABLE and metric.metric is not None:
            observations.append(
                (metric.metric.value, str(run.candidate.candidate_id), run.metrics_report)
            )
    if not observations:
        return BestValidationObservation(None, None, None, "NO_VALID_DEVELOPMENT_METRIC")
    value, _, evidence_ref = sorted(
        observations, key=lambda item: (-item[0], item[1])
    )[0]
    return BestValidationObservation(
        plan.metric_name, value, evidence_ref, None
    )


def observe_spot_multiple_testing(
    *,
    journal: OOSResearchJournal,
    protocol: OOSProtocolV2,
    bundle: SpotOOSBundle,
) -> MultipleTestingAssessment:
    """Assess only the recorder-issued exact OOS snapshot; never rank held-out results."""
    if type(journal) is not OOSResearchJournal or type(protocol) is not OOSProtocolV2:
        raise ValueError("MULTIPLE_TESTING_PROTOCOL_OR_JOURNAL_UNRESOLVED")
    plan = journal._multiple_testing_plans.get(protocol.content_sha256)
    if type(plan) is not SpotMultipleTestingPlanV1 or plan.protocol != protocol:
        raise ValueError("MULTIPLE_TESTING_PLAN_UNRESOLVED")
    result = resolve_spot_oos_result(bundle, journal=journal)
    current_snapshot = journal.snapshot
    if (
        result.protocol != protocol
        or result.journal.events
        != current_snapshot.events[: len(result.journal.events)]
        or result.journal.journal_id != plan.journal_id
        or result.journal.authority != plan.authority
        or not result.journal.events
    ):
        raise ValueError("MULTIPLE_TESTING_OOS_RESULT_MISMATCH")
    # OOSJournalSnapshot validates the entire sequence, previous-hash chain, and
    # monotonic receipt chronology. Check selection and holdout isolation again at
    # the C-105 boundary rather than trusting a caller-supplied result.
    events = current_snapshot.events
    journal_tail = events[len(result.journal.events) :]
    selects = tuple(
        event for event in events
        if event.protocol_sha256 == protocol.content_sha256
        and event.kind is OOSEventKind.SELECT
    )
    holdout = _window(protocol, protocol.partitions[-1])
    development_windows = {
        _window(protocol, partition) for partition in protocol.partitions[:-1]
    }
    selected_id = (
        result.selected_candidate.candidate_id
        if result.selected_candidate
        else None
    )
    selection_valid = (
        len(selects) == 1 and selects[0].candidate_id == selected_id
    ) or (
        not selects and selected_id is None and result.outcome.value == "INCONCLUSIVE"
    )
    post_plan_events = events[plan.journal_prefix_length:]
    holdout_violation = any(
        event.window.overlaps(holdout)
        and (
            event.kind is OOSEventKind.TRIAL
            or (
                event.kind is OOSEventKind.ACCESS
                and (
                    event.protocol_sha256 != protocol.content_sha256
                    or event.purpose != "FINAL_HOLDOUT_EXECUTION"
                    or (selects and event.sequence < selects[0].sequence)
                )
            )
        )
        for event in post_plan_events
    )
    trial_scope_violation = any(
        event.protocol_sha256 == protocol.content_sha256
        and event.kind is OOSEventKind.TRIAL
        and event.window not in development_windows
        for event in post_plan_events
    )
    base_result_receipts = tuple(
        event
        for event in result.journal.events[plan.journal_prefix_length :]
        if event.protocol_sha256 == protocol.content_sha256
        and event.kind is OOSEventKind.RESULT
    )
    if (
        len(base_result_receipts) != 1
        or base_result_receipts[0] != result.journal.events[-1]
    ):
        raise ValueError("MULTIPLE_TESTING_TERMINAL_RECEIPT_UNRESOLVED")
    post_plan_protocol_events = tuple(
        event
        for event in events[plan.journal_prefix_length :]
        if event.protocol_sha256 == protocol.content_sha256
    )
    trials = tuple(
        event
        for event in post_plan_protocol_events
        if event.kind is OOSEventKind.TRIAL
        and event.window in development_windows
    )
    results = tuple(
        event
        for event in post_plan_protocol_events
        if event.kind is OOSEventKind.RESULT
    )
    tail_violation = any(
        event.protocol_sha256 == protocol.content_sha256
        or (
            event.kind in (OOSEventKind.ACCESS, OOSEventKind.TRIAL)
            and event.window.overlaps(holdout)
        )
        for event in journal_tail
    )
    relevant_events = tuple(
        event
        for event in post_plan_events
        if event.protocol_sha256 == protocol.content_sha256
        or (
            event.kind in (OOSEventKind.ACCESS, OOSEventKind.TRIAL)
            and event.window.overlaps(holdout)
        )
    )
    seen_event_digests: set[str] = set()
    evidence_violation = False
    for event in relevant_events:
        if not assessment_event_is_valid(
            event,
            plan=plan,
            oos_result=result,
            seen_event_digests=seen_event_digests,
        ):
            evidence_violation = True
        seen_event_digests.add(event.content_sha256)
    outcome = (
        MultipleTestingOutcome.FAILED
        if result.outcome.value == "FAILED"
        or not selection_valid
        or holdout_violation
        or trial_scope_violation
        or tail_violation
        or evidence_violation
        or len(results) != 1
        else MultipleTestingOutcome(result.outcome.value)
    )
    held_runs = tuple(run for run in result.runs if run.partition_id == plan.held_out_partition_id)
    unique_hypotheses = {
        ref
        for mapping in plan.candidate_hypothesis_map
        for ref in mapping.hypothesis_refs
    }
    counts = MultipleTestingCounts(
        unique_strategy_count=len({item.strategy for item in protocol.candidates}),
        unique_configuration_count=len(
            {
                (
                    item.parameters,
                    item.costs,
                    item.cost_adapter,
                    item.execution_policy_sha256,
                )
                for item in protocol.candidates
            }
        ),
        unique_hypothesis_count=len(unique_hypotheses),
        protocol_count=1,
        development_trial_count=len(trials),
        held_out_result_count=len(held_runs),
    )
    rejected = tuple(
        item.candidate_id
        for item in protocol.candidates
        if selected_id is not None and item.candidate_id != selected_id
    )
    return MultipleTestingAssessment.build(
        plan=plan,
        oos_result=result,
        outcome=outcome,
        counts=counts,
        selected_candidate_id=selected_id,
        rejected_candidate_ids=rejected,
        best_validation_observation=_best_development_observation(plan, result),
        journal_tail=journal_tail,
    )
