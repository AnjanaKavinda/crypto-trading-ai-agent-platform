from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import timedelta
from uuid import uuid4

import pytest
from test_qualification_rule_evaluator import request
from test_strategy_evidence_package import _package
from test_wave4_contract_foundation import _v2_case
from trading_platform_api.contracts.serialization import canonical_sha256
from trading_platform_api.strategy import (
    ConditionTruth,
    SignalLifecycleCause,
    SignalLifecycleError,
    SignalLifecycleEvent,
    SignalLifecycleEventType,
    SignalLifecycleProjection,
    SignalLifecycleRuntime,
    VersionReference,
    can_explicitly_supersede,
    effective_expiry,
    evaluate_qualification_rules,
    evaluate_signal_qualification_v2,
    invalidation_rule_matches,
    publish_qualified_signal,
)

NOW_OFFSET = timedelta(seconds=2)


class MemoryLifecycleStore:
    def __init__(self) -> None:
        self.events: dict[VersionReference, list[SignalLifecycleEvent]] = {}
        self.rejected = []

    async def history(self, subject: VersionReference):
        return tuple(self.events.get(subject, ()))

    async def append(self, event: SignalLifecycleEvent, audit_event):
        items = self.events.setdefault(event.subject, [])
        if any(item.event_id == event.event_id for item in items):
            return True
        current = items[-1].resulting_state if items else None
        if current is not event.prior_state:
            return False
        items.append(event)
        return True

    async def append_rejected(self, audit_event):
        self.rejected.append(audit_event)


def _candidate_ref(candidate):
    return VersionReference(
        "C-023",
        candidate.candidate_id,
        "1",
        canonical_sha256(candidate),
    )


def _source_ref(kind: str = "C-025"):
    return VersionReference(kind, uuid4(), "2", "a" * 64)


def _event(
    *,
    subject,
    prior,
    result,
    event_type,
    cause,
    event_time,
):
    return SignalLifecycleEvent(
        subject=subject,
        prior_state=prior,
        resulting_state=result,
        event_type=event_type,
        cause=cause,
        source_references=(_source_ref(),),
        event_time=event_time,
        recorded_at=event_time + timedelta(seconds=1),
        correlation_id="issue-89",
    )


def test_lifecycle_event_identity_is_deterministic_and_watch_is_unavailable() -> None:
    _, _, _, candidate = _v2_case()
    subject = _candidate_ref(candidate)
    first = _event(
        subject=subject,
        prior=None,
        result=SignalLifecycleProjection.CANDIDATE,
        event_type=SignalLifecycleEventType.CREATED,
        cause=SignalLifecycleCause.SOURCE_DECISION,
        event_time=candidate.created_at,
    )
    repeat = _event(
        subject=subject,
        prior=None,
        result=SignalLifecycleProjection.CANDIDATE,
        event_type=SignalLifecycleEventType.CREATED,
        cause=SignalLifecycleCause.SOURCE_DECISION,
        event_time=candidate.created_at,
    )
    assert first.event_id == repeat.event_id
    assert first.audit_id == first.event_id

    with pytest.raises(SignalLifecycleError, match="WATCH"):
        _event(
            subject=subject,
            prior=SignalLifecycleProjection.CANDIDATE,
            result=SignalLifecycleProjection.WATCH,
            event_type=SignalLifecycleEventType.WATCHED,
            cause=SignalLifecycleCause.SOURCE_DECISION,
            event_time=candidate.created_at + timedelta(seconds=1),
        )


def test_runtime_replay_idempotency_and_illegal_transition_audit() -> None:
    _, _, _, candidate = _v2_case()
    subject = _candidate_ref(candidate)
    store = MemoryLifecycleStore()
    runtime = SignalLifecycleRuntime(store)
    created = _event(
        subject=subject,
        prior=None,
        result=SignalLifecycleProjection.CANDIDATE,
        event_type=SignalLifecycleEventType.CREATED,
        cause=SignalLifecycleCause.SOURCE_DECISION,
        event_time=candidate.created_at,
    )
    qualified = _event(
        subject=subject,
        prior=SignalLifecycleProjection.CANDIDATE,
        result=SignalLifecycleProjection.QUALIFIED,
        event_type=SignalLifecycleEventType.QUALIFIED,
        cause=SignalLifecycleCause.SOURCE_DECISION,
        event_time=candidate.created_at + timedelta(seconds=1),
    )

    first = asyncio.run(runtime.record(created, actor="owner"))
    duplicate = asyncio.run(runtime.record(created, actor="owner"))
    second = asyncio.run(runtime.record(qualified, actor="owner"))
    assert first.accepted and not first.duplicate
    assert duplicate.accepted and duplicate.duplicate
    assert second.accepted
    assert (
        asyncio.run(runtime.projection(subject)) is SignalLifecycleProjection.QUALIFIED
    )

    illegal = _event(
        subject=subject,
        prior=SignalLifecycleProjection.CANDIDATE,
        result=SignalLifecycleProjection.EXPIRED,
        event_type=SignalLifecycleEventType.EXPIRED,
        cause=SignalLifecycleCause.EFFECTIVE_EXPIRY_REACHED,
        event_time=candidate.created_at + timedelta(seconds=2),
    )
    rejected = asyncio.run(runtime.record(illegal, actor="owner"))
    assert not rejected.accepted
    assert rejected.projection is SignalLifecycleProjection.QUALIFIED
    assert store.rejected[-1].result == "REJECTED"


def test_qualified_wave3_chain_publishes_c070v2_and_lifecycle_event() -> None:
    case, strategy, _, candidate = _v2_case()
    package_result = _package(case, candidate=candidate)
    assert package_result.package is not None
    package = package_result.package
    evaluated_at = candidate.created_at + timedelta(seconds=10)
    validation = evaluate_qualification_rules(
        request(
            candidate=candidate,
            evidence_package=package,
            evaluated_at=evaluated_at,
        )
    )
    assert validation.validation is not None
    qualification = evaluate_signal_qualification_v2(
        candidate=candidate,
        evidence_package=package,
        validation=validation.validation,
        evaluated_at=evaluated_at + timedelta(seconds=1),
    )
    assert qualification.qualification is not None
    signal_fields = {
        "market_context_id": candidate.market_context_id,
        "analysis_snapshot_id": candidate.analysis_snapshot_id,
        "asset": candidate.asset,
        "instrument_id": candidate.instrument_id,
        "timeframe": candidate.timeframe,
        "direction": candidate.direction,
        "evidence_ids": candidate.supporting_evidence_ids,
        "data_quality_report_id": candidate.data_quality_report_id,
    }
    signal, event = publish_qualified_signal(
        candidate=candidate,
        strategy=strategy.version,
        package=package,
        qualification=qualification.qualification,
        market_context=case[2].market_context,
        now=evaluated_at + timedelta(seconds=2),
        recorded_at=evaluated_at + timedelta(seconds=3),
        correlation_id="issue-89-qualified",
        signal_fields=signal_fields,
    )
    repeat_signal, repeat_event = publish_qualified_signal(
        candidate=candidate,
        strategy=strategy.version,
        package=package,
        qualification=qualification.qualification,
        market_context=case[2].market_context,
        now=evaluated_at + timedelta(seconds=2),
        recorded_at=evaluated_at + timedelta(seconds=3),
        correlation_id="issue-89-qualified",
        signal_fields=signal_fields,
    )
    assert signal == repeat_signal
    assert event.event_id == repeat_event.event_id
    assert event.resulting_state is SignalLifecycleProjection.QUALIFIED
    assert event.source_references[0].artifact_type == "C-070"
    assert event.source_references[0].artifact_id == signal.signal_id


def test_personal_spot_invalidation_requires_exact_fresh_fail() -> None:
    case, _, version, _ = _v2_case()
    evaluation = case[5]
    now = evaluation.evaluated_at + NOW_OFFSET
    groups = tuple(
        replace(item, truth=ConditionTruth.FAIL) if index == 0 else item
        for index, item in enumerate(evaluation.groups)
    )
    failed = replace(evaluation, truth=ConditionTruth.FAIL, groups=groups)
    assert invalidation_rule_matches(version=version, evaluation=failed, now=now)

    unknown_groups = tuple(
        replace(item, truth=ConditionTruth.UNKNOWN) if index == 0 else item
        for index, item in enumerate(evaluation.groups)
    )
    unknown = replace(evaluation, truth=ConditionTruth.UNKNOWN, groups=unknown_groups)
    assert not invalidation_rule_matches(version=version, evaluation=unknown, now=now)
    assert not invalidation_rule_matches(
        version=version,
        evaluation=failed,
        now=evaluation.expires_at,
    )
    assert not invalidation_rule_matches(
        version=version,
        evaluation=replace(failed, content_sha256="b" * 64),
        now=now,
    )


def test_effective_expiry_uses_earliest_authoritative_boundary() -> None:
    _, _, _, candidate = _v2_case()
    values = (
        candidate.expires_at,
        candidate.expires_at - timedelta(seconds=10),
        candidate.expires_at - timedelta(seconds=5),
    )
    assert effective_expiry(*values) == values[1]


def test_supersession_requires_explicit_same_version_and_scope() -> None:
    _, _, version, candidate = _v2_case()
    strategy_ref = VersionReference(
        "C-021",
        version.strategy_version_id,
        version.semantic_version,
        version.content_sha256,
    )
    successor = replace(
        candidate,
        candidate_id=uuid4(),
        created_at=candidate.created_at + timedelta(seconds=1),
    )
    assert can_explicitly_supersede(
        predecessor=candidate,
        successor=successor,
        strategy_version=strategy_ref,
    )
    assert not can_explicitly_supersede(
        predecessor=candidate,
        successor=replace(successor, strategy_version_id=uuid4()),
        strategy_version=strategy_ref,
    )
    assert not can_explicitly_supersede(
        predecessor=candidate,
        successor=replace(successor, direction=type(candidate.direction).SHORT),
        strategy_version=strategy_ref,
    )
